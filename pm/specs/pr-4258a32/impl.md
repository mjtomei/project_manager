# Implementation Spec: get_workdir helper that recovers a missing workdir from the filesystem

## Summary

A PR's `workdir` field in `project.yaml` is a machine-local absolute path.
When it goes stale (the PR was started under another HOME/machine, the
record was rewritten, or the path was never recorded) pm currently treats
the workdir as gone and clones a **second** workdir, even though the
original clone — with the PR branch, uncommitted work, stashes and evidence
— is still sitting in this machine's project workdirs directory.  Concrete
case (PR note): #136/pr-6aa74c6 recorded
`/home/mjtomei/.../pm-pr-6aa74c6-fuzzy-select-for-pr-and-plan-command-ab512a43`
while its intact clone was
`/home/matt/.pm/workdirs/project-manager-828c8d0a/pm-pr-6aa74c6-fuzzy-select-for-pr-and-plan-command-10e74920`
(same branch slug, different base-hash suffix and HOME).

This PR adds a bounded, on-demand resolver that keeps the existing fast path
(recorded path exists → return it, no git, no scan) and only when the
recorded path is missing scans **this project's** workdirs directory for a
clone whose name matches the PR's branch slug, verifies its repository and
branch identity read-only, and re-links it.  Ambiguity is reported, never
resolved by picking the first match.

## Requirements

### R1: Shared helper module `pm_core/workdirs.py`

New module (low-level: imports `store`, `paths`; never `pm_core.cli`).

- `project_workdirs_dir(data) -> Path` — the `<workdirs_base>/<name>-<repo_id[:8]>`
  (or `<workdirs_base>/<name>`) directory.  The body of
  `pm_core/cli/helpers.py:_workdirs_dir` moves here; `_workdirs_dir` stays as
  a thin delegate so existing imports/patches (`pr_mod._workdirs_dir` in
  `tests/test_github_draft_pr.py`) keep working.  Unlike today it must not be
  required to `mkdir` for a read-only lookup (callers that provision keep
  their own `mkdir`).  `pm_core/pr_sync.py:find_workdir`'s private copy of
  the same naming (its any-clone fallback for merge checks) uses it too.
- `workdir_lock(project_dir, pr_id)` — context manager holding the existing
  per-PR provisioning lock `project_dir/.workdir-{pr_id}.lock` (exclusive,
  blocking `fcntl.flock`), exactly the lock `_ensure_workdir` takes today.
  `_ensure_workdir` is switched to use it so recovery and cloning share one
  lock.
- `branch_slug(branch)` / `workdir_name(branch, base_hash="")` — the clone
  naming (`<branch_slug>-<base_hash>`, or the bare slug).  `pr start` and
  `_clone_workdir` name new clones with `workdir_name` and discovery matches
  `branch_slug`, so naming and recovery share one definition.
- `stored_workdir(root, pr_id)` — the on-disk record re-read after taking the
  lock (the double-check); `_ensure_workdir` and the resolver both use it.
- `resolve_workdir(data, pr_entry, root=None, *, project_dir=None,
  persist=True, locked=False) -> WorkdirResolution`.
- `get_workdir(data, pr_entry, root=None, **kw) -> str | None` — the public
  convenience: `resolve_workdir(...).path`.
- `WorkdirResolution` dataclass: `path`, `status`
  (`"recorded" | "recovered" | "ambiguous" | "missing"`), `recorded` (the
  stale value, if any), `candidates` (verified paths), `rejected`
  (`(path, reason)` pairs), and `describe()` producing the user-facing text.

### R2: Fast path unchanged

If `pr_entry["workdir"]` is set and `Path(...).exists()` →
`status="recorded"`, returned directly: no git subprocess, no directory
listing, no lock, no write.  (Same `exists()` test the existing call sites
use.)

### R3: Bounded discovery when the recorded path is missing or absent

Only when the field is empty or its path does not exist, and the PR has a
`branch`:

1. List **one directory**: `project_workdirs_dir(data)` (or the caller's
   `project_dir`), non-recursively.  A missing/unreadable dir → no candidates
   (no `mkdir`).
2. Name filter: `^<slug>(-<7..40 hex>)?$` where
   `slug = branch_slug(branch)` — the naming `pr start` / `_clone_workdir`
   use via `workdir_name` (`<branch_slug>-<base_hash>`, or the bare
   slug when no hash).  Dot entries (`.tmp-<pr>`, lock files) and non-dirs
   are skipped.  Entries resolving to the same real path are deduplicated,
   keeping the real directory over a symlink alias (so the recorded path is
   the clone itself, whatever the alias's name sorts as).
3. If no name matches, return `missing` without taking any lock.

QA scenario clones live under `<workdirs_base>/qa/<pr>-*/scenario-N/repo` and
meta workdirs under `<workdirs_base>/meta-*`; neither is in the project dir,
so they are never candidates.

### R4: Read-only identity verification of each candidate

All git calls use `GIT_OPTIONAL_LOCKS=0`, a timeout, and never `status`,
`checkout`, `fetch`, `stash` or any write.  Repository-locating variables
(`GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_INDEX_FILE`, …) are
dropped from git's environment, so a pm run that inherits them (e.g. from a
git hook) still inspects each candidate rather than that repository.  A
candidate is **verified** only if all hold:

- **Own repository**: `git rev-parse --show-toplevel` resolves to the
  candidate itself (a plain dir, or a subdir of some other repo, is rejected).
- **Repository identity**: when `project.repo_id` is cached, the repo contains
  that root commit (`git cat-file -e <repo_id>^{commit}`); otherwise the
  `origin` fetch URL equals `project.repo` (normalized: trailing `/` and
  `.git` ignored).  With neither available it is rejected as unverifiable.
- **Branch/PR identity**: `HEAD` is the symbolic ref `refs/heads/<pr branch>`,
  or — mid-rebase with a detached HEAD — the rebase's `head-name`
  (`rebase-merge/` or `rebase-apply/`) names that branch.  Any other branch
  or a plain detached HEAD is rejected with the branch named in the reason.

The PR branch embeds the PR id (`pm/pr-<id>-…`), so branch identity is PR
identity; it also separates PRs whose 50-char-truncated slugs collide.

### R5: Outcome rules (no first-match picking)

- Exactly one verified candidate → `status="recovered"`: `pr_entry["workdir"]`
  is updated in memory and, when `root` is given and `persist`, persisted with
  `store.locked_update` as a compare-and-set (written only if the on-disk
  record is still empty or still points at a non-existent path; if another
  writer recorded an existing path meanwhile, that path is adopted instead).
  A persistence failure (lock timeout etc.) is logged; the in-memory result
  still stands.
- Two or more verified → `status="ambiguous"`, `path=None`, all candidates
  listed by `describe()`; nothing is written and callers must **not** clone.
  More than `MAX_CANDIDATES` name matches are `ambiguous` without being
  verified (`unverified=True`); `describe()` says they only match by name.
- None verified → `status="missing"` with the rejected candidates and reasons;
  callers fall back to their existing behavior (clone).
- `WorkdirResolution.reportable` (recovered, ambiguous, or any rejected
  same-named candidate) tells callers to show `describe()`, so a fresh clone
  made next to a skipped one — or `pm pr cd` failing — says which clones were
  skipped and why.

### R6: Serialized with provisioning

Verification + adoption runs under `workdir_lock(project_dir, pr_id)`.
Under the lock the resolver re-reads the authoritative record
(`store.load(root)`) when `root` is given and adopts an existing path a
concurrent caller just persisted (double-checked, mirroring
`_ensure_workdir`).  Callers that already hold the lock pass `locked=True`
(flock is per open-file-description, so re-locking in-process would
deadlock).

### R7: Wire into on-demand call sites (not registry load)

- `pm_core/cli/helpers.py:_ensure_workdir` — after its existing double-check,
  under the lock: `resolve_workdir(..., locked=True)`; recovered → return it
  (no clone); ambiguous → print `describe()` to stderr and return `None` (no
  clone); missing → `_clone_workdir` as before (skipped same-named clones
  are listed on stderr first).  This covers every existing
  consumer: `pm pr review` window (`cli/pr.py` review window), `pm pr done`,
  merge window, `signoff.py` launch, `qa_loop.py` QA launch.  The QA
  launch runs in the TUI, where that stderr report is never shown, so
  on failure it re-resolves (no persist) and its ERROR status line names
  the ambiguity instead of "does not exist … could not be created".
- `pm_core/cli/pr.py:pr_start` — when no `--workdir` is given and the recorded
  path is missing, resolve (with `project_dir=_workdirs_dir(data)`) before
  printing "workdir missing, creating a new one" / cloning.  Recovered → reuse
  it (existing dirty-tree guard then skips pull/checkout on a dirty tree);
  ambiguous → warn, and if a clone would be needed exit 1 without cloning (an
  already-open PR window is still switched to, as today); missing → clone as
  before.  An explicit `--workdir` skips discovery and is used as given
  (no "workdir missing, creating a new one" message; the existing
  in_progress reuse of an *existing* recorded path is unchanged).
- `pm_core/cli/pr.py:pr_cd` (`pm pr cd`) — use the resolver so a stale record
  is recovered instead of "Workdir … does not exist"; ambiguity is reported.
- `pm_core/cli/pr.py:pr_merge` (`pm pr merge`) — under the per-PR merge
  lock, before the sign-off gate and the `--no-signoff-check` /
  `--propagation-only` recovery branch, resolve (never clone: the gate reads
  the workdir HEAD only) so a stale record is re-linked instead of refused as
  "workdir not found … Restore the workdir".  The gate still decides: a
  re-linked HEAD that isn't the approved one refuses as usual; ambiguity is
  reported and the gate refuses as it would for a missing workdir.

Nothing is added to `store.load`, the TUI tech tree, `pm pr list`, sync or
other all-PR loops.

## Implicit Requirements

- Discovery never mutates a candidate: no checkout/pull/stash/clean/index
  refresh — dirty files, index, untracked files, stashes and evidence dirs
  are left exactly as found.  Post-adoption behavior equals the existing
  recorded-path behavior of each caller (e.g. `pr start` still skips
  pull/checkout on a dirty tree; `_ensure_workdir` returns without touching
  the tree).
- `agent_machine`, status and other fields are not changed by recovery.
- The lock file creation needs the project dir to exist; it exists whenever
  there is a name-matched candidate (the resolver only locks then, or the
  caller already created it).
- Tests patching `pm_core.paths.workdirs_base`, `pr_mod._workdirs_dir` or
  `git_ops.run_git` must keep passing; the resolver uses its own `git`
  subprocess helper (not `git_ops.run_git`), so tests that stub `run_git`
  don't feed fake output into verification.
- Logged via `pm_core.paths.configure_logger`-style module logger: recovered
  path (info), ambiguity and rejected candidates (warning/info).

## Ambiguities (resolved)

### A1: Where does the helper live — `store.get_workdir`?
`store.py` is the YAML persistence layer with no git/filesystem-scan
dependencies.  The helper goes in a new `pm_core/workdirs.py` (`get_workdir`
/ `resolve_workdir`), which uses `store` for the record and persistence.

### A2: What is a "stale" recorded path?
A recorded path that does not exist on this machine.  An existing recorded
path is trusted unverified (the required fast path); verifying it on every
access would add git calls to every consumer.

### A3: Persist the recovered path?
Yes, compare-and-set — the incident needed a manual re-link, and persisting
makes the next access take the fast path.  `get_workdir` without `root`
updates only the in-memory entry.

### A4: Candidates that fail verification
Not adopted; reported as rejected with a reason; the caller's previous
fallback (clone) proceeds.  Only *multiple verified* candidates block
cloning, since then the correct workdir provably exists but can't be chosen
safely.

### A5: Which directories are scanned?
Only this project's workdirs dir (one level).  Not the recorded path's
parent (it belongs to another HOME/machine), not `qa/`, not other projects.

## Edge Cases

- **Recorded path under another HOME** (the incident): recorded path missing →
  slug match on `<slug>-<different hash>` → verified → re-linked.
- **Two clones on the PR branch** (an old one and one made by a later
  start, or a fixture copied into the project dir): ambiguous → listed, no
  clone, no write.  `describe()` lists them and tells the user to move the
  extra clone(s) aside (or check out another branch there); the next
  on-demand use re-links the one that remains.  (`pm pr start --workdir` is
  not suggested: it launches a session and is skipped entirely when the PR's
  window already exists.)
- **Same slug, different branch** (50-char truncation collision, or the user
  checked out `master` in the old clone): rejected with the actual branch;
  falls back to clone.
- **Mid-rebase workdir** (detached HEAD): accepted via `head-name`.
- **Mid-merge / dirty workdir**: HEAD still on the branch → accepted;
  untouched.
- **`.tmp-<pr_id>` partial clone**: dot entry, skipped.
- **Different repo in a same-named dir**: root commit absent → rejected.
- **Symlink alias to the same clone**: deduplicated by real path (not
  ambiguous); the real directory, not the alias, is recorded.
- **pm run with `GIT_DIR` set** (git hook): git's location variables are
  dropped, so a plain same-named dir is still rejected.
- **PR without `branch`**: no discovery; `missing`.
- **Concurrent callers**: second caller waits on the per-PR lock, then adopts
  the persisted record from the first.
- **Stale path reappears** (a remount) after the fast-path check: the
  under-lock re-read and the compare-and-set both keep any record that
  exists by then — never overwritten with the discovered clone.
- **Workdirs dir absent** (fresh machine): no listing error, no `mkdir`,
  `missing`.
- **Pre-existing `_clone_workdir` name collision** (an existing
  `<slug>-<hash>` dir equal to the fresh clone's name): unchanged behavior;
  a verified dir of that name is already adopted before cloning is reached.
