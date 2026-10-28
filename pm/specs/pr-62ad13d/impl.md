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

- Behaviour: run the normal close (GitHub close per `--keep-github`, status set
  in the registry), then delete the registry entry only.
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
- Do not change dependent statuses, do not add the closed id to any "merged"
  set, do not remove it from `depends_on`.
- `graph.ready_prs` (`pm_core/graph.py:40`) only treats *merged* dependencies
  as satisfied, so closed dependencies keep dependents blocked — no code change
  needed. `autostart_state._derive` (`pm_core/autostart_state.py:426`) reports
  `closed` as done, and `tui/auto_start.py:491` rejects terminal targets.

### R8 — Closed PRs cannot be started again

- Auto-start: `graph.ready_prs` only selects `pending` PRs; `auto_start` also
  refuses terminal targets. No change needed.
- Manual `pm pr start`: only `merged` is refused today (`pm_core/cli/pr.py:938`).
  Add a `closed` guard next to it: refuse with exit 1 and point at
  `pm pr edit <id> --status pending` to reopen deliberately.

### R9 — Closed status is durable across GitHub sync

- `pr_sync.sync_from_github` (`pm_core/pr_sync.py:367`) maps an OPEN GitHub PR
  to `in_progress`/`in_review`. That would silently un-close a PR closed with
  `--keep-github` (or when the `gh` call failed), losing the historical record.
- Mirror the existing `qa`/`sign_off` preservation: when GitHub reports OPEN
  and the local status is `closed`, skip the PR (keep `closed`).
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

Existing test `tests/test_pr_enhancements.py:746` (`TestGitHubCloseResilience`)
asserts the *old* destructive outcome (workdir removed, entry removed) and must
be rewritten to assert retention.

## 2. Implicit requirements

- **Lock discipline.** Status mutation happens inside `store.locked_update`
  using the freshly loaded entry; a concurrent `--remove` (entry gone) must not
  raise — re-check `store.get_pr` inside `apply` and no-op.
- **TUI refresh.** Keep `trigger_tui_refresh()` so the TUI reloads; closed PRs
  are already hidden by default (`pm_core/tui/tree_layout.py:172`) and filtered
  from `pm pr list --open` (`pm_core/cli/pr.py:517`).
- **Schema.** `closed` is already a valid status (`pm_core/pr_utils.py:5`) and
  `store` does not validate per-field keys, so `closed_at` is safe.
- **Output stability.** Messages must not claim removal unless `--remove` is
  used; scripts/tests that grepped the old `Removed pr-001` line are updated.
- **No new destructive fallback.** The only filesystem operations in the close
  path after this change are reads (`Path.exists` for the message).
- **Concurrency/ordering.** The `gh` call stays outside the store lock
  (`store.locked_update` must not be held across network calls).
- **Merge/spec gates untouched.** Close never writes sign-off or merge fields;
  a merged PR cannot be closed without `--remove` (A5).

## 3. Ambiguities and resolutions

- **A1 — What does `--remove` do about GitHub?** Resolved: `--remove` is
  registry-only *for local resources*. The GitHub PR is still closed according
  to `--keep-github` (so `pm pr close --remove` reproduces the old
  "close GitHub + forget the entry" flow, minus branch/workdir deletion).
  Documented in help text.
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
  retried); `updated_at` is refreshed.
- **A7 — Runtime notice for `--keep-branch`?** Resolved: none; the deprecation
  lives in `--help` (a runtime line would be noise in QA scripts that still
  pass the flag).

No **[UNRESOLVED]** ambiguities.

## 4. Edge cases

- **Entry vanishes between load and update** (concurrent `--remove`): the
  `apply` closure no-ops; command still exits 0 with the earlier summary.
- **`gh` unavailable / unauthenticated**: `SystemExit` swallowed as today →
  warning, status still `closed`, nothing deleted.
- **GitHub says the PR is already closed/merged**: fake/real `gh` may exit
  non-zero; treated as a warning, local lifecycle still proceeds.
- **`--keep-github` then `pm pr sync-github`**: status stays `closed` (R9).
- **`--remove` on the active PR**: `active_pr` reassigned; TUI reloads.
- **Closed PR in a plan / dependency graph**: it keeps rendering as closed
  (hidden by default in the tree), dependents stay blocked and are warned
  about; nothing is auto-satisfied.
- **`--remove` for a PR with a `merged` status**: record removed; GitHub,
  branch and workdir untouched.
- **`pr_id` given as `#N` or bare number**: `_require_pr` resolution unchanged.
- **Close while another process holds the store lock**: `StoreLockTimeout`
  propagates as today (no destructive partial state; the gh close may already
  have happened — acceptable, documented by ordering).
- **Workdir is a symlink or on another mount**: untouched (no rmtree).

## 5. Files to change

- `pm_core/cli/pr.py` — `pr_close` rewrite (`--remove`, warnings, messages),
  `pr_start` closed guard.
- `pm_core/cli/helpers.py` — `_record_status_timestamp` `closed_at`.
- `pm_core/pr_sync.py` — keep local `closed` when GitHub reports OPEN.
- `pm_core/gh_ops.py` — docstring note only (no signature change).
- `pm_core/cli/__init__.py` — help line.
- `pm/qa/regression/command-dedup.md`, `pm/qa/regression/multi-window-registry.md`
  — cleanup steps use `--remove`.
- `tests/test_pr_close.py` (new) and `tests/test_pr_enhancements.py`
  (`TestGitHubCloseResilience` rewrite).

## 6. Out of scope

- Real GitHub operations of any kind; all verification uses the fake backend.
- Changing `pm pr cleanup`, `pm pr merge`, or TUI cleanup keys.
- Branch deletion features (e.g. `gh pr close --delete-branch`) — removed from
  the close path entirely; no replacement command is added.
