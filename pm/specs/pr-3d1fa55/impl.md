# Spec: pr-3d1fa55 — terminal-status PRs keep their tmux windows when finalized outside pm merge flow

## Summary
A PR that reaches a terminal status (`merged`/`closed`) by any path *other
than* pm's interactive merge flow keeps all of its tmux windows open (impl,
`review-`, `merge-`, `qa-<id>`, and every `qa-<id>-sN` scenario window).
Window teardown must become a function of the PR's status, run on every
TUI reload/sync, not a side effect of the merge command.

## Relevant code

- `pm_core/cli/session.py:953` — `_TERMINAL_STATUSES = {"merged", "closed"}`.
- `pm_core/pr_cleanup.py` — `cleanup_pr_resources(session, pr)` is the
  comprehensive teardown: kills tmux windows (`kill_pr_windows`), removes QA
  containers + push-proxy sockets, prunes the pane registry, drops the per-PR
  runtime-state file. Safe/idempotent when no resources exist.
- `pm_core/cli/helpers.py:301` — `kill_pr_windows`: kills `{display_id}`,
  `review-{display_id}`, `merge-{display_id}`, `qa-{display_id}`, and every
  `qa-{display_id}-s*` scenario window (parks grouped clients first).
- `pm_core/qa_loop.py:344` — `_cleanup_stale_scenario_windows` (the teardown
  cited in the task; QA-window-only variant, superseded here by the broader
  `cleanup_pr_resources`).
- `pm_core/tui/sync.py` — `do_normal_sync` (periodic + manual `r`) and
  `startup_github_sync`. Both already detect *merged* PRs and call
  `_kill_merged_pr_windows` → `cleanup_pr_resources`, but only on the sync
  that **observes the transition**.

## Root cause (confirmed)

Window teardown only fires on the transition `non-terminal → merged`, and
that detection is fragile:

1. **Masked transition.** `background_sync` reloads `app._data` from disk
   (`sync.py:63,71-72`) *before* calling `do_normal_sync`, which then
   snapshots `old_statuses` from the already-reloaded data (`sync.py:133`).
   So an external `pm pr edit --status merged` made between two syncs is read
   into `app._data` first; the subsequent transition check compares
   merged-vs-merged and detects nothing → windows orphan.
2. **`closed` never handled.** Both `_kill_merged_pr_windows` and the
   transition detection only consider `"merged"`. A PR reaching `closed`
   (via edit or GitHub sync `status_updates`) never triggers teardown.
3. **Content-merge / diverged SHAs.** Such PRs aren't auto-detected by
   sync at all; once marked terminal via edit they hit case (1)/(2).

## Requirements

- **R1** — Reaching `merged`/`closed` by any path (edit, sync-detected,
  content-merge) closes the PR's impl/`review-`/`merge-`/`qa-`/`qa-…-sN`
  windows on the next TUI reload/sync. *Implemented:* new
  `_reclaim_terminal_pr_windows(app)` in `sync.py` sweeps all PRs whose
  status ∈ `_TERMINAL_STATUSES` and calls `cleanup_pr_resources` for any with
  live windows. Called at the end of `do_normal_sync` and after the GitHub
  startup sync's display update.
- **R2** — No orphaned windows remain for terminal-status PRs. The sweep is
  self-healing: it runs every sync, so a PR whose teardown was missed once is
  reclaimed on the following refresh.
- **R3** — Active/non-terminal PRs unaffected. The sweep skips any PR whose
  status ∉ `_TERMINAL_STATUSES`.
- **R4** — Test: a PR with open windows that is merged via `pm pr edit`
  (masked transition) has its windows reclaimed. *Implemented* in
  `tests/test_tui_sync_parse_error.py`
  (`TestReclaimTerminalPrWindows` + `TestDoNormalSyncReclaimsTerminalWindows`).

## Implicit requirements

- **Idempotency / cost.** The sweep must not re-tear-down or do per-sync work
  for terminal PRs that are already clean. Resolved by a cheap name check:
  list windows once, intersect against the PR's candidate window names
  (`display_id`, `review-/merge-/qa-` prefixes, `qa-…-s` prefix); only call
  `cleanup_pr_resources` when a live window actually matches.
- **Single source of truth for terminal statuses.** The sweep imports
  `_TERMINAL_STATUSES` from `cli/session.py` (lazy import inside the function
  to avoid any import-order coupling).
- **No new resource leaks.** Reuse `cleanup_pr_resources`, which already
  handles windows + containers + sockets + registry + runtime-state, so the
  out-of-merge-flow path reclaims everything the merge flow would.
- **Guards.** Respect the existing pattern: no-op when `app._session_name` is
  unset or the tmux session does not exist.

## Ambiguities (resolved)

- **Keep or replace the transition-based `_kill_merged_pr_windows`?**
  *Kept.* It performs immediate cleanup on the observed-merge path and feeds
  `auto_start.check_and_start`. The new status-based sweep is added as a
  safety net; overlap is harmless because the sweep's name check makes
  already-cleaned PRs a no-op.
- **Where to run the sweep?** In `do_normal_sync` (the periodic + manual `r`
  reload path that `background_sync` drives) and after `startup_github_sync`'s
  display update. These are the "TUI reload/sync" chokepoints named in the
  task.
- **Reuse `_cleanup_stale_scenario_windows` (qa_loop) per the task hint?**
  That helper only covers `qa-` windows. `cleanup_pr_resources` is the
  superset (impl/review/merge/qa + containers + registry + runtime-state) and
  is the right reuse target for "impl/merge/review/qa windows."

## Edge cases

- PR merged via `pm pr edit` while its windows are open, with `app._data`
  already holding the merged status → covered by the sweep (the headline bug).
- PR `closed` via edit or GitHub sync → covered (was never handled before).
- Terminal PR with no live windows → cheap no-op (skipped before cleanup).
- Non-terminal PR with live windows → untouched.
- No tmux session / no `_session_name` → guarded no-op.
- `tmux.list_windows` failure → logged, sweep returns without raising (won't
  crash the sync loop).
