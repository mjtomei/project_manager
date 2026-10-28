# Implementation Spec — pr-62ad13d

Make `pm pr close` a non-destructive lifecycle action: retain the registry
entry, the remote branch, and the local workdir.

## 1. Requirements (grounded in the codebase)

### R1 — Default close sets `status: closed` and preserves the record

- Current code: `pm_core/cli/pr.py:3426` `pr_close()`. Lines 3477-3487 drop the
  entry (`data["prs"] = [p for p in ... if p["id"] != target_id]`) and reassign
  `project.active_pr`.
- New behaviour: inside `store.locked_update(root, apply)`, fetch the PR with
  `store.get_pr(data, pr_id)` (fresh on-disk state, not the pre-lock snapshot),
  set `pr["status"] = "closed"`, and call `_record_status_timestamp(pr, "closed")`
  (`pm_core/cli/helpers.py:446`). Every other key — `title`, `description`,
  `notes`, `depends_on`, `branch`, `workdir`, `plan`, `gh_pr`, `gh_pr_number`,
  `created_at`, `started_at`, `reviewed_at`, `signed_off_at`, `merged_at`,
  sign-off/merge-evidence fields — is left untouched.
- `_record_status_timestamp` is extended with a `closed` branch that sets
  `closed_at` (mirrors `merged_at`). `updated_at` is always set. No other
  timestamp is touched.

### R2 — Close the GitHub PR; never delete a branch

- Current code: `gh_ops.close_pr(gh_pr_number, delete_branch=not keep_branch)`
  (`pm_core/cli/pr.py:3457`); `pm_core/gh_ops.py:303` appends `--delete-branch`
  when true.
- New: call `gh_ops.close_pr(gh_pr_number)` (default `delete_branch=False`).
  `gh_ops.close_pr` keeps its parameter for other callers/tests; `pm pr close`
  never passes it.
- Preserve the existing failure tolerance: `SystemExit` raised by `_check_gh`
  (gh missing/unauthenticated) and any other exception are caught, reported as
  warnings, and do **not** abort the local status change.
- No `gh` call when `gh_pr_number` is absent, when `--keep-github` is given, or
  when the local status is already `merged` (a merged GitHub PR cannot be
  closed; see A5).

### R3 — Preserve the workdir and every file in it

- Delete the `shutil.rmtree(workdir)` block (`pm_core/cli/pr.py:3471-3475`).
- No `git clean`, `git reset`, stash/drop, or other filesystem cleanup as a
  side effect of close. `shutil` stays imported for unrelated call sites
  (`pr.py:1031`, `pr.py:1060`, `pr.py:3163`).
- A `workdir` reference that points at a missing path is preserved verbatim.

### R4 — Cleanup remains a separate, explicit operation

Audit of close-adjacent teardown paths (all stay explicit / merged-only):

- `pm pr cleanup` (`pm_core/cli/pr.py:3168`) — explicit; unchanged.
- `pm pr cleanup --resources` → `pr_cleanup.cleanup_pr_resources`
  (`pm_core/pr_cleanup.py:36`) — explicit; unchanged.
- TUI `Y` cleanup (`pm_core/tui/pr_view.py:515`) — explicit key; unchanged.
- `_kill_merged_pr_windows` (`pm_core/tui/sync.py:50`) — fires only for
  `merged_prs` from sync, never for `closed`.
- `_finalize_merge` (`pm_core/cli/pr.py:1919`) — merge path only.
- `pm_core/tui/auto_start.py` target pruning removes *targets* for terminal
  PRs; it does not delete branches/workdirs.

No new hook, delayed deletion, or fallback is added. The close command itself
must not kill tmux windows/containers either (that is `--resources`).

### R5 — Explicit registry-only removal

Add `--remove` to `pm pr close`:

- Behaviour: close the GitHub PR according to `--keep-github` (skipped when the
  local status is `merged`), then delete the registry entry *instead of*
  recording the closure — no `status`/`closed_at` write on a record that no
  longer exists.
- Never deletes the branch, the workdir, or any file; never the default; never
  implied by another flag.
- When the PR is already `merged`, `--remove` skips the GitHub call (nothing to
  close) and only deletes the record.
- `project.active_pr` is reassigned exactly as today when it pointed at the
  removed PR: first remaining non-terminal PR, else `None`.
- Help text documents it as registry-only.

### R6 — `--keep-github` kept; `--keep-branch` deprecated no-op

- `--keep-github` keeps its meaning: do not touch the GitHub PR.
- `--keep-branch` is accepted (no error, no removal of the option) and is a
  no-op; branch retention is unconditional. Help text says so explicitly
  ("Deprecated no-op: close never deletes branches").

### R7 — Warn about dependents; never auto-satisfy

- After the status write, compute dependents: entries whose `depends_on`
  contains the closed id and whose own status is not `merged`/`closed`.
- Print a warning (stderr) naming them, e.g.
  `Warning: 2 dependent PR(s) remain blocked by #163: pr-002 (B), pr-003 (C)`.
  With `--remove` the warning instead says the dependents depend on the
  *removed* record (their `depends_on` now names a PR that does not exist), so
  the message must not imply a `closed` status is what blocks them.
- Do not change dependent statuses, do not add the closed id to any "merged"
  set, do not remove it from `depends_on`.
- `graph.ready_prs` (`pm_core/graph.py:40`) only treats *merged* dependencies
  as satisfied, so closed dependencies keep dependents blocked — no code change
  needed. `autostart_state._derive` (`pm_core/autostart_state.py:426`) reports
  `closed` as done, and `tui/auto_start.py:491` rejects terminal targets.

### R8 — Closed PRs cannot be started (or merged) again

- Auto-start: `graph.ready_prs` only selects `pending` PRs; `auto_start` also
  refuses terminal targets. No change needed.
- Manual `pm pr start`: only `merged` is refused today (`pm_core/cli/pr.py:938`).
  Add a `closed` guard next to it: refuse with exit 1 and point at
  `pm pr edit <id> --status pending` to reopen deliberately.
- Manual `pm pr merge` (added in review iteration c02f i2): a closed PR must not
  be publishable either — merging rewrites the closure into `merged` and erases
  the reason the PR was retired. The guard sits *after* the
  `--no-signoff-check` / `--propagation-only` recovery branch so recovering a
  merge that is already published still works if the record was closed
  meanwhile. This matters more now than before the PR: the retained workdir
  means `_infer_pr_id`'s cwd match can resolve a closed PR for an id-less
  `pm pr merge` (its cwd step ignores the status filter).

### R9 — Terminal statuses are durable across GitHub sync

- `pr_sync.sync_from_github` (`pm_core/pr_sync.py:367`) maps an OPEN GitHub PR
  to `in_progress`/`in_review`. That would silently un-close a PR closed with
  `--keep-github` (or when the `gh` call failed), losing the historical record.
- Mirror the existing `qa`/`sign_off` preservation: when GitHub reports OPEN
  and the local status is `closed`, skip the PR (keep `closed`).
- `merged` is terminal in the same way (review c02f i8, incidental fix): a
  local merge record must not be rewritten to `in_review`/`in_progress` by
  GitHub OPEN (the merge landed outside GitHub) nor to `closed` by GitHub
  CLOSED. Either rewrite erases `merged_at`/merge evidence and re-blocks the
  dependents the merge satisfied. The docstring states the rule.
- The same rule must hold inside the locked apply, not only against the
  pre-lock snapshot: `sync_from_github` computes `status_updates` before taking
  the store lock, so a `pm pr close` (or `pm pr merge`) landing during the
  GitHub round-trip would otherwise be overwritten. Both the `save_state`
  apply in `sync_from_github` and the TUI's `startup_github_sync` apply skip a
  status update when the fresh entry is already `merged`/`closed` (a discovered
  `merged` still finalizes — GitHub is authoritative about a merge).
- `pr_sync.sync_prs` (TUI/`pm pr sync`) already ignores non-active statuses;
  unchanged.

### R10 — Help and docs consistency

- `pm_core/cli/__init__.py:617`: update the one-line help to describe the new
  behaviour.
- `pm/qa/regression/command-dedup.md` uses `pm pr close` to delete dummy PRs;
  switch those cleanup steps (and the tool list line) to `pm pr close <id>
  --remove`.
- `pm/qa/regression/multi-window-registry.md` cleanup steps use
  `pm pr close <id> --keep-branch`; the flag remains valid but the entry now
  persists — update to `pm pr close <id> --remove` where the PR must disappear.

### R11 — Regression coverage (`tests/test_pr_close.py`)

All tests use disposable tmp projects and the fake GitHub transport
(`FakeGitHubBackend`, `tests/conftest.py:34/50`); no real PRs, branches, or
workdirs are touched.

1. Default close: exit 0; entry retained; `status == "closed"`;
   `closed_at` set; `updated_at` changed; every other field deep-equal to the
   pre-close entry (notes, `depends_on`, description, branch, workdir, plan,
   gh fields, prior timestamps).
2. GitHub: `backend.calls` contains `["pr","close","42"]` and no
   `--delete-branch`; fake PR state `CLOSED`; with a git-backed fake the
   branch still exists in `backend.git_repo`.
3. Workdir: tracked modification, untracked file, ignored file, and a
   `captures/` fixture are byte-identical after close (snapshot hashes).
4. `--keep-github`: no `pr close` call recorded; local status `closed`.
5. `--keep-branch`: accepted; no branch deletion; entry retained.
6. No `gh_pr_number`: no gh call; status `closed`.
7. Absent workdir path: close succeeds; `workdir` reference preserved.
8. Repeat close: exit 0; entry still present; status `closed`; notes not
   duplicated.
9. `--remove`: entry gone; workdir and branch intact; `active_pr` reassigned.
10. Dependents: warning names the dependent(s); dependent status unchanged
    (not merged, not started); `ready_prs` still excludes it.
11. GitHub failure (`simulate_*` / exception / `SystemExit`): exit 0, warning
    printed, status `closed`, entry + workdir intact.
12. `pm pr start <closed>`: refused with exit 1.
13. `sync_from_github` with GitHub OPEN and local `closed`: status stays
    `closed`.
14. `pm pr merge <closed>`: refused with exit 1 (`reopen` in the message);
    nothing published; status and workdir intact.
15. `pm pr merge <closed> --propagation-only`: recovery still runs (R8
    ordering).
16. Concurrent `--remove` between load and lock: exit 0, entry stays gone, no
    exception, and the command does not claim it removed the record.
17. `pm pr add` of a title+description that matches a retained `closed` entry:
    the duplicate message names the closed status and the reopen command
    (`pm pr edit <id> --status pending`).
18. `active_pr` (A2): a default close moves it off the now-closed entry to the
    first remaining non-terminal PR, and closing a PR never moves a pointer
    that names a different PR.
19. `--remove` on a `merged` PR leaves the GitHub PR alone (a merged GitHub PR
    cannot be closed) and reports the *local* record — "left unchanged (the PR
    is recorded as merged)" — instead of claiming it was left "open", and
    without asserting a GitHub state no call verified.
20. `--keep-github` reports the GitHub PR as "unchanged", never as "open"
    (its GitHub state may be closed or merged), and wins over the merged
    wording on `--remove` (review c02f i7).
21. `--remove` dependent warning says the dependents reference the removed
    record; their status/`depends_on` are untouched and `ready_prs` stays
    empty.
22. Sync race (R9): `status_updates` computed from a stale snapshot do not
    overwrite a `closed` status written before the lock, in both
    `sync_from_github(save_state=True)` and the TUI `startup_github_sync`
    apply — while a merge discovered on GitHub still finalizes over the
    concurrently closed record (review c02f i7).
23. Malformed dependent (review c02f i6): a hand-edited `prs` entry with no
    `id` whose `depends_on` names the closed PR must not crash the dependent
    warning — it runs *after* the status write, so a `KeyError: 'id'` there
    would turn a persisted close into a traceback.  The scan iterates
    `usable_prs`, like every other id-indexing loop.  Covered for both the
    default close and `--remove`.
24. Repeat close of a legacy `closed` entry with no `closed_at` (review c02f
    i8): the entry keeps none — a repeat close moves `updated_at` only.
    `_record_status_timestamp` would otherwise stamp "now", inventing a
    closure time for a PR closed before the field existed (A6: only a *fresh*
    closure records one).  Covered by
    `test_repeat_close_does_not_invent_a_closure_time`.
25. `merged` durability in sync (review c02f i8, R9): GitHub OPEN does not
    reopen a locally `merged` PR and GitHub CLOSED does not rewrite it to
    `closed`; the locked apply also skips a stale update when the fresh entry
    is already `merged` (CLI `sync_from_github` and the TUI
    `startup_github_sync`).  Covered by
    `test_sync_from_github_does_not_reopen_a_merged_pr`,
    `test_sync_from_github_does_not_close_a_merged_pr`,
    `test_sync_from_github_keeps_a_concurrently_merged_pr`, and
    `test_tui_startup_github_sync_keeps_a_concurrently_merged_pr`.

Existing test `tests/test_pr_enhancements.py:746` (`TestGitHubCloseResilience`)
asserts the *old* destructive outcome (workdir removed, entry removed) and must
be rewritten to assert retention.

## 2. Implicit requirements

- **Lock discipline.** Status mutation happens inside `store.locked_update`
  using the freshly loaded entry; a concurrent `--remove` (entry gone) must not
  raise — re-check `store.get_pr` inside `apply` and no-op. The merged guard is
  re-checked inside `apply` too: a merge landing between the pre-lock load and
  the lock must not be rewritten to `closed` (the pre-lock refusal message is
  reused and the command exits 1).
- **TUI refresh.** Keep `trigger_tui_refresh()` so the TUI reloads; closed PRs
  are already hidden by default (`pm_core/tui/tree_layout.py:172`) and filtered
  from `pm pr list --open` (`pm_core/cli/pr.py:517`).
- **Schema.** `closed` is already a valid status (`pm_core/pr_utils.py:5`) and
  `store` does not validate per-field keys, so `closed_at` is safe.
- **Output stability.** Messages must not claim removal unless `--remove` is
  used; scripts/tests that grepped the old `Removed pr-001` line are updated.
  A concurrent removal is reported as "removed concurrently" for both the
  close and `--remove` paths — never as "Removed registry entry" when another
  process already did it.
- **Retained closed entries are duplicates.** `pm pr add` matches
  title+description against every entry, so a closed record now blocks
  re-adding the same PR.  The duplicate message therefore names the closed
  status and points at `pm pr edit <id> --status pending` (the deliberate
  reopen path) rather than leaving the add silently unfulfilled.
- **No new destructive fallback.** The close path performs no filesystem
  writes at all — the workdir is not even stat'ed any more; the "Kept:" line
  prints the retained references verbatim.
- **Concurrency/ordering.** The `gh` call stays outside the store lock
  (`store.locked_update` must not be held across network calls).
- **Merge/spec gates untouched.** Close never writes sign-off or merge fields;
  a merged PR cannot be closed without `--remove` (A5).

## 3. Ambiguities and resolutions

- **A1 — What does `--remove` do about GitHub?** Resolved: `--remove` is
  registry-only *for local resources*. The GitHub PR is still closed according
  to `--keep-github` (so `pm pr close --remove` reproduces the old
  "close GitHub + forget the entry" flow, minus branch/workdir deletion).
  `--keep-github` takes precedence over every status-specific message: it
  always means "leave the GitHub PR alone" (a merged record cannot be closed,
  so the call is skipped either way). Documented in help text.
- **A2 — What happens to `project.active_pr` on default close?** Resolved: if
  it pointed at the closed PR, reassign to the first remaining non-terminal PR,
  else `None` (mirrors the old reassignment, without ever selecting a
  merged/closed entry). The closed entry itself keeps all its fields.
- **A3 — Add a `closed_at` timestamp?** Resolved: yes, set by
  `_record_status_timestamp(pr, "closed")`, mirroring `merged_at`. Not added to
  `_make_pr_entry` (no schema churn for other PRs).
- **A4 — Should close tear down tmux windows/containers?** Resolved: no.
  Those are live resources owned by explicit `pm pr cleanup --resources`
  (and by merge detection). Close must not silently remove anything.
- **A5 — Close on a `merged` PR?** Resolved: refuse (exit 1) without
  `--remove`, because rewriting `merged` → `closed` erases merge history and
  merge-integrity evidence. With `--remove`, delete the registry record only
  (no GitHub call, no branch/workdir deletion). Message points at `--remove`.
- **A6 — Repeat close on an already `closed` PR?** Resolved: idempotent
  success. The entry stays `closed`; the GitHub close is re-attempted unless
  `--keep-github` (so a close whose `gh` call previously failed can be
  retried); `updated_at` is refreshed. The original `closed_at` is preserved
  (only a fresh closure — i.e. from a non-`closed` status — records a new one),
  so repeated close never rewrites closure history.  An entry that was already
  `closed` before `closed_at` existed stays without one: a repeat close must
  not stamp "now" and invent a closure time (review c02f i8).
- **A7 — Runtime notice for `--keep-branch`?** Resolved: none; the deprecation
  lives in `--help` (a runtime line would be noise in QA scripts that still
  pass the flag).

No **[UNRESOLVED]** ambiguities.

## 4. Edge cases

- **Entry vanishes between load and update** (concurrent `--remove`): the
  `apply` closure no-ops and sets `missing_at_lock`; the command exits 0 with
  a "removed concurrently; nothing to close/remove" message (covered by
  `test_close_noops_when_entry_removed_concurrently` and
  `test_remove_noops_when_entry_removed_concurrently`).
- **`gh` unavailable / unauthenticated**: `SystemExit` swallowed as today →
  warning, status still `closed`, nothing deleted.
- **GitHub says the PR is already closed/merged**: fake/real `gh` may exit
  non-zero; treated as a warning, local lifecycle still proceeds.
- **`--keep-github` then `pm pr sync-github`**: status stays `closed` (R9).
- **`--remove` on the active PR**: `active_pr` reassigned; TUI reloads.
- **Closed PR in a plan / dependency graph**: it keeps rendering as closed
  (hidden by default in the tree), dependents stay blocked and are warned
  about; nothing is auto-satisfied.
- **`pm pr merge` on a closed PR**: refused (R8) unless it is a
  `--no-signoff-check` / `--propagation-only` recovery of an already-published
  merge; `pm pr edit --status` is the deliberate reopen path.
- **`--remove` for a PR with a `merged` status**: record removed; GitHub,
  branch and workdir untouched.
- **`pr_id` given as `#N` or bare number**: `_require_pr` resolution unchanged.
- **Close while another process holds the store lock**: `StoreLockTimeout`
  propagates as today (no destructive partial state; the gh close may already
  have happened — acceptable, documented by ordering).
- **Workdir is a symlink or on another mount**: untouched (no rmtree).

## 5. Files to change

- `pm_core/cli/pr.py` — `pr_close` rewrite (`--remove`, warnings, messages),
  `pr_start` and `pr_merge` closed guards, and a closed-duplicate hint in
  `pr_add` (retained closed entries now match its duplicate check).
- `pm_core/cli/helpers.py` — `_record_status_timestamp` `closed_at`.
- `pm_core/pr_sync.py` — keep local `closed` when GitHub reports OPEN, at
  snapshot time and again inside the locked apply.
- `pm_core/tui/sync.py` — the startup GitHub sync's apply applies the same
  closed-is-terminal guard.
- `pm_core/gh_ops.py` — docstring note only (no signature change).
- `pm_core/cli/__init__.py` — help line.
- `pm/qa/regression/command-dedup.md`, `pm/qa/regression/multi-window-registry.md`
  — cleanup steps use `--remove`.
- `tests/test_pr_close.py` (new), `tests/test_pr_enhancements.py`
  (`TestGitHubCloseResilience` rewrite), and `tests/test_sync_merge_integrity.py`
  (TUI startup-sync closed race).

## 6. Out of scope

- Real GitHub operations of any kind; all verification uses the fake backend.
- Changing `pm pr cleanup`, `pm pr merge`, or TUI cleanup keys.
- Branch deletion features (e.g. `gh pr close --delete-branch`) — removed from
  the close path entirely; no replacement command is added.
