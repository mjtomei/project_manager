# QA Spec: get_workdir helper that recovers a missing workdir from the filesystem (pr-4258a32)

## What changed (user-level summary)

A PR's `workdir` field in `project.yaml` is a machine-local absolute path.
When it goes stale — the PR was started under another HOME or machine, the
record was rewritten, or the field was dropped — pm used to treat the
workdir as gone: `pm pr cd` failed, `pm pr merge` refused ("workdir not
found … Restore the workdir"), and start/review/QA/sign-off cloned a
**second** workdir next to the intact original (with its branch, dirty
work, stashes and evidence).

Now, only when a specific PR's workdir is actually needed and its record is
missing or points nowhere, pm looks in **this project's workdirs dir**
(`$HOME/.pm/workdirs/<project>-<repo_id[:8]>/`, one level) for a directory
named after the PR's branch slug (`<slug>` or `<slug>-<7..64 hex>`),
verifies it read-only (its own git repo, this project's repository, checked
out on the PR branch — or mid-rebase of it), and re-links it (writes the
record back with a compare-and-set). Two or more verified clones are
reported as ambiguous and nothing is chosen or cloned. Look-alikes that fail
verification are listed as "skipped … : <reason>" and never taken over by a
fresh clone. A recorded path that exists is used as-is (fast path); nothing
runs on registry load (`pm pr list`, TUI tree, sync).

User-facing entry points wired to recovery:

| Surface | Stale record + 1 verified clone | 2+ verified clones | Only rejected look-alikes |
|---|---|---|---|
| `pm pr cd` | re-link message, shell in clone, record updated | exit 1, clones listed, "Not choosing one" | exit 1, "skipped …: reason" lines |
| `pm pr start` (no `--workdir`) | "reusing its recovered workdir" (in_progress), no clone | ambiguity on stderr, "Not creating another workdir", exit 1 | skipped list, fresh clone at a *different* name |
| `pm pr start --workdir D` | discovery skipped, D used, no "workdir missing" | same | same |
| review window / `pm pr review`, sign-off window, merge window, TUI QA launch (via `_ensure_workdir`) | re-link, window opens in clone | no clone, failure reported (TUI QA: ERROR log names the ambiguity) | skipped list, fresh clone at a different name |
| `pm pr merge` | re-link before the sign-off gate; gate judges re-linked HEAD | ambiguity printed; gate refuses as for a missing workdir | gate refuses as before |

## 1. Requirements (Given / When / Then)

### R1 — Moved-HOME recovery through `pm pr cd`
- **Given** an in_progress PR whose recorded workdir is a path under another
  HOME that does not exist on this machine, and the PR's original clone is
  intact in this machine's project workdirs dir (possibly with a different
  hash suffix than the record), holding commits, unstaged + staged edits,
  untracked files, a stash and an evidence/scratch directory,
- **When** the user runs `pm pr cd <pr>`,
- **Then** pm prints "Workdir for <pr>: recorded path <old> is missing;
  re-linked the existing clone on <branch> at <clone>", the shell opens in
  the clone, `project.yaml` now records the clone path, and the clone's
  `git status --porcelain`, staged diff, untracked files, stash list,
  evidence dir, HEAD, reflog and `.git/index` (bytes + mtime) are unchanged.

### R2 — Fast path after re-link
- **Given** R1 has re-linked the record,
- **When** the user runs `pm pr cd <pr>` again,
- **Then** no re-link/discovery message is printed and the same directory
  opens; `project.yaml` is not rewritten.

### R3 — No discovery on registry load
- **Given** a project with one or more PRs whose records are stale while
  their clones are intact,
- **When** the user runs read-only listing commands (`pm pr list`,
  `pm pr list --workdirs`, `pm pr show <pr>`) or opens the TUI,
- **Then** `project.yaml` is byte-identical afterwards (no re-link written)
  and no `.workdir-<pr>.lock` file appears in the project workdirs dir.

### R4 — `pm pr start` reuses a recovered clone
- **Given** an in_progress PR with a stale record and an intact, dirty clone,
- **When** the user starts the PR again (CLI or TUI start action),
- **Then** pm says it is reusing the recovered workdir (never "workdir
  missing, creating a new one"), reports the uncommitted-changes guard
  ("skipping git pull/checkout"), no second clone appears in the workdirs
  dir, the implementation window opens in the original clone, the dirty /
  staged / untracked / stash content is intact, and the record points at
  the clone.

### R5 — `pm pr start --workdir` is used as given
- **Given** a PR with a stale record and an intact clone,
- **When** the user starts it with an explicit `--workdir <dir>`,
- **Then** no discovery report and no "workdir missing, creating a new one"
  message is printed; `<dir>` is the workdir used and recorded.

### R6 — Ambiguity is reported, never resolved
- **Given** a stale record and two verified clones of the PR branch in the
  project workdirs dir (e.g. the original plus a copy the user made),
- **When** the user runs `pm pr cd`, `pm pr start`, or launches a
  review/sign-off window for the PR,
- **Then** each lists both clone paths with "Not choosing one…", exits
  non-zero / opens no window, writes nothing to `project.yaml`, and creates
  no third clone (`pm pr start` says "Not creating another workdir").

### R7 — Ambiguity resolved by the user
- **Given** R6's state,
- **When** the user moves one clone out of the workdirs dir (or checks out
  another branch in it) and runs `pm pr cd` again,
- **Then** the remaining clone is re-linked as in R1.

### R8 — Look-alikes are skipped with a reason and never taken over
- **Given** a stale record and, in the project workdirs dir, only
  same-named directories that are not this PR's clone — the old clone with
  `master` checked out, a plain non-git dir, a clone of a different
  repository, a detached-HEAD clone —
- **When** the user runs `pm pr cd`,
- **Then** it exits non-zero and prints one "skipped <path>: <reason>" line
  per look-alike ("on branch master, not <branch>", "not a git repository",
  "different repository …", "HEAD is detached").
- **When** the user instead runs `pm pr start` (or a review window launch),
- **Then** the same skipped list is printed, a fresh clone is created at a
  name that differs from every look-alike (e.g. `<slug>-<full hash>`), the
  look-alikes are untouched (master clone still on master with its files),
  and the record points at the fresh clone. When no free name exists, pm
  refuses ("…names … are taken by directories that aren't its clone; move
  them aside"), removes its temp clone, and records nothing.

### R9 — Out-of-project clones are never candidates
- **Given** a stale record and clones of the PR branch only outside the
  project workdirs dir (QA scenario clones under `~/.pm/workdirs/qa/…`,
  meta workdirs, another project's workdirs dir, the stale path's parent),
- **When** the user needs the workdir (`pm pr cd` / start),
- **Then** none is adopted; `pm pr cd` reports no clone found; start clones
  fresh into the project workdirs dir.

### R10 — In-flight git state is recovered and preserved
- **Given** the intact clone is mid-rebase of the PR branch (detached HEAD),
  mid-merge with conflicts, or has another git process holding
  `.git/index.lock`,
- **When** the user runs `pm pr cd`,
- **Then** the clone is re-linked (mid-rebase accepted via the rebase's
  head-name), the rebase/merge/lock state is exactly as before (`git status`
  still says rebasing / merging; `index.lock` still present and not
  created/removed by pm).

### R11 — Inherited GIT_DIR does not fool verification
- **Given** the user's shell exports `GIT_DIR`/`GIT_WORK_TREE` pointing at
  some other repository, a stale record, and a same-named *plain* dir,
- **When** the user runs `pm pr cd`,
- **Then** the plain dir is still skipped as "not a git repository" (not
  re-linked); with a real clone present, that clone is re-linked.

### R12 — Recorded path that reappears wins
- **Given** a stale record whose path is restored (e.g. a remount or symlink
  at the old location) before the next use, while a same-named clone also
  exists in the workdirs dir,
- **When** the user runs `pm pr cd`,
- **Then** the recorded path is used as-is and the record is not changed.

### R13 — Concurrent recovery converges
- **Given** a stale record and one intact clone,
- **When** several actors at once need the workdir (parallel `pm pr cd`,
  `pm pr start`, review and sign-off window launches from different panes),
- **Then** all land in the same clone, exactly one clone exists, no
  `.tmp-<pr>` dir remains, `project.yaml` is valid with a single record
  equal to the clone, and no traceback/lock error appears.
- **Given** a stale record and **no** clone anywhere,
- **When** two actors launch windows that need the workdir at once,
- **Then** exactly one fresh clone is made and both use it.
- **Given** another writer updating `project.yaml` at the same time (repeated
  `pm pr note add` on the same PR, `pm pr edit` on another PR),
- **Then** all their edits survive alongside the re-link.
- **Given** two different PRs, both stale, recovered in parallel,
- **Then** each gets its own clone; no cross-linking.

### R14 — TUI surfaces
- **Given** a pm session (TUI, fake-claude) with a PR whose record is stale
  and whose clone is intact,
- **When** the user triggers review / sign-off / start / QA from the TUI,
- **Then** the window opens with its pane cwd in the original clone, the
  record is re-linked, and no second clone appears.
- **Given** two verified clones,
- **When** the user starts QA from the TUI,
- **Then** the TUI log shows a QA ERROR that names the ambiguity ("N clones
  of <branch> in <dir>, not choosing one; move the extra clone(s) aside"),
  not "does not exist on this machine and could not be created"; no qa
  window and no clone are created.

### R15 — `pm pr merge` with a stale record
- **Given** a PR with a valid recorded merge approval (sign-off) for its
  current HEAD, and its record goes stale with the clone intact,
- **When** the user runs `pm pr merge`,
- **Then** pm prints the re-link message and the merge proceeds (gate reads
  the re-linked HEAD) instead of "workdir not found … Restore the workdir".
- **Given** the re-linked clone's HEAD moved after the approval,
- **Then** the gate refuses with its normal "stale (HEAD moved since)"
  wording.
- **Given** two verified clones,
- **Then** the ambiguity is printed and the merge is refused; nothing is
  merged.

## 2. Setup

Cross-cutting (every scenario):
1. Install pm from this PR's clone (`./install.sh --local`, or the venv steps
   in `tui-manual-test.md`) and confirm `pm which` points at it.
2. Use an isolated `HOME` (the container's own) so `~/.pm/workdirs` is
   scratch; never touch the host's PM state.
3. Create a throwaway git project, `pm init --backend local --no-import`,
   add PRs, commit/push project state so `pm pr start` accepts them.
4. `pm pr start <pr>` once to create the genuine clone under
   `~/.pm/workdirs/<project>-<repo_id8>/pm-pr-<id>-<slug>-<hash>` (inside a
   pm session with fake-claude so no real Claude runs).
5. Put user work in the clone: a commit, an unstaged edit, a staged edit, an
   untracked file, a stash, an evidence dir. Snapshot `git status
   --porcelain`, `git stash list`, `git rev-parse HEAD`, reflog,
   `sha256sum .git/index` + `stat .git/index`.
6. Make the record stale the way a user hits it: either run the start as
   `HOME=/home/olduser` and then move `~/.pm/workdirs/<project>-…` into the
   new HOME, or rewrite the PR's `workdir` (bootstrap-only edit, as a pull
   from another machine would) to a non-existent path under another HOME
   with a different hash suffix; or delete the field (absent record).
7. Look-alikes for edge cases: `cp -a` / second `git clone` of the clone
   with the PR branch checked out (verified duplicate); `git checkout master`
   in a copy (wrong branch); `mkdir` (plain dir); `git init` of an unrelated
   repo; `git checkout --detach`; `ln -s` alias — all named `<slug>-<hex>`.

## 3. Edge Cases

- **E1 Absent field**: Given the `workdir` field is missing entirely and the
  clone is intact, When `pm pr cd` / `pm pr review` / TUI review run, Then
  the clone is re-linked (the field is written).
- **E2 PR without a branch**: Given a PR record with no `branch`, When `pm pr
  cd`, Then the usual "does not exist" message; no scan error.
- **E3 Workdirs dir absent** (fresh machine): Given no
  `~/.pm/workdirs/<project>-…` dir, When `pm pr cd`, Then a clean "does not
  exist" error; the dir is not created by the lookup.
- **E4 Symlink alias**: Given the real clone plus a `<slug>-<hex>` symlink to
  it, When recovered, Then not ambiguous and the record names the real
  directory, not the alias.
- **E5 Many name matches** (>16 same-named dirs): Then reported as ambiguous
  "named after … (more than 16; none verified)"; nothing adopted.
- **E6 Detached HEAD** (not a rebase): skipped "HEAD is detached".
- **E7 `.tmp-<pr>` leftover partial clone**: never a candidate.
- **E8 Stale path reappears** (R12).
- **E9 Different repository under the same name**: skipped "different
  repository (root commit … absent)".
- **E10 Fresh-clone name collision**: Given the only same-named dir is the
  user's master-checked-out clone at exactly the name a fresh clone would
  take, When `pm pr start`, Then the fresh clone goes to a different name
  and the master clone is not checked out to the PR branch.
- **E11 GIT_DIR in env** (R11).
- **E12 index.lock held by a concurrent git process** (R10).

## 4. Pass / Fail Criteria

PASS when every Then above is observable on the user's surface (command
output/exit code, TUI pane/log, files under `~/.pm/workdirs`, the
`project.yaml` record) and:
- an intact, verifiable clone is always re-linked, never duplicated;
- no candidate's working tree, index content, untracked files, stash,
  rebase/merge state, refs or evidence changes as a result of *discovery*
  (pr start's own post-adoption pull/checkout/dirty-check behaves exactly
  as for an existing recorded path);
- ambiguity and rejected look-alikes are reported with paths and reasons,
  nothing is picked, and no fresh clone overwrites/checks out over them;
- concurrent actors converge on one clone and one consistent record, with
  other writers' `project.yaml` edits preserved;
- read-only listing/TUI load does not write `project.yaml`.

FAIL on: a second clone made while a verified one exists; a clone adopted
from `qa/`, another project, or the wrong branch; any change to the clone's
git/work state caused by discovery; a missing/garbled report; a traceback;
lost concurrent edits; a `project.yaml` rewrite on plain listing; a merge
published after an ambiguity.

## 5. Ambiguities (resolved)

- **A1 How to make a record stale in a test.** A real user hits this via a
  HOME rename / project.yaml from another machine. Moving the workdirs tree
  to a new HOME, or a bootstrap-only rewrite of the `workdir` field, both
  produce the same on-disk state; either is acceptable. All subsequent
  actions go through pm CLI/TUI.
- **A2 "Preserved" with `pm pr start`.** Discovery itself is read-only (index
  bytes + mtime unchanged for `pm pr cd`/`pm pr merge` discovery). `pm pr
  start` then runs its pre-existing dirty check (`git status`, which may
  refresh index stat data) and, on a clean tree, pull/checkout — same as for
  an existing recorded path. For start, preservation means content (staged /
  unstaged / untracked / stash / commits), not index bytes.
- **A3 Surfaces not wired by this PR.** Some consumers read the field
  directly: `pm pr signoff record` / `signoff integrate` (HEAD lookup), the
  TUI review-loop / auto-start guards that skip a PR whose field is
  *absent*, `pm pr list --workdirs`. The impl spec scopes recovery to the
  `_ensure_workdir` callers plus `pr start`/`pr cd`/`pr merge`. QA treats a
  stale record through those other surfaces as observational: a clear,
  actionable message passes; a misleading "Start the PR first" while an
  intact clone exists (absent field through the TUI review loop) is
  reported as a finding for follow-up rather than a hard failure of this
  PR's core behavior.
- **A4 Existing-but-wrong recorded path.** Trusted unverified (fast path) by
  design; not a failure.

No [UNRESOLVED] ambiguities.
