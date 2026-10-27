# Spec: pr-0c530e1 — cleanup leaves loop state stale; sequential container stops

## Requirements

1. **Clear runtime state on cleanup.** `pm_core.pr_cleanup.cleanup_pr_resources`
   must remove the per-PR runtime state file at
   `~/.pm/runtime/{pr_id}.json` (path returned by
   `pm_core.runtime_state.runtime_path`). This single file holds *all*
   per-action entries for the PR — `qa`, `review-loop`, `review`,
   `start`, `merge`, etc. (see `pm_core/runtime_state.py:13-31` schema).
   Deleting it is equivalent to clearing both the "QA loop state" and
   "review loop state" mentioned in the task description, plus any
   other lingering action entries.

2. **Parallelize container teardown.** `pm_core.container.cleanup_pr_containers`
   currently calls `remove_container` sequentially in the matching loop
   (`pm_core/container.py:1085`). Each `remove_container` waits a 10s
   inspect-poll deadline (`container.py:872-892`) plus the runtime's
   own SIGTERM grace inside `rm -f`. Replace the serial loop with a
   `concurrent.futures.ThreadPoolExecutor` submission so total wall
   time is `≈ max(per-container)` not `Σ`.

3. **Merge-detection cleanup parity.** `_kill_merged_pr_windows` in
   `pm_core/tui/sync.py` must call `cleanup_pr_resources` (not just
   `kill_pr_windows`) so auto-on-merge tears down containers,
   push-proxy sockets, pane registry entries, and runtime state —
   matching the manual `Y`/`y` cleanup path. Without this, merged
   PRs leave containers running indefinitely after windows are killed.

4. **Surface state-clear in the summary.** Existing summary dict has
   `windows`, `containers`, `registry_windows`, `sockets`. Add a
   `runtime_state` boolean (or path string) so callers/tests can
   verify clearing happened. Keep `format_summary` backwards-compatible
   (no new line unless cleared).

## Implicit Requirements

- `runtime_path` and removal must be best-effort: if the file doesn't
  exist (PR never had a loop), don't error. Already a no-op semantics
  for `Path.unlink(missing_ok=True)`.
- Parallel removal must preserve dedup (`seen` set) and the returned
  ordering needn't be deterministic, but tests pin order — preserve
  insertion order by collecting candidate names first, then mapping
  futures back. Existing test `test_session_tagged_and_legacy_dedup`
  expects `["pm-mysess-qa-pr-001-l1-s0", "pm-qa-pr-001-l2-s0"]`.
- Exceptions in individual `remove_container` calls must still be
  logged-and-swallowed, never propagated, matching current behavior.

## Ambiguities

- "Audit other persistent loop state for the same issue." The only
  on-disk loop state I found is `~/.pm/runtime/{pr_id}.json`
  (`runtime_state.py`). Hook events live under per-session_id keys
  (transient, garbage-collected on next event), and `pane_registry`
  is already cleaned. Resolved: deleting the runtime file is the
  complete fix.
- Worker count for the thread pool. Use `min(len(candidates), 8)` —
  enough to parallelize the common 1–4 container case without
  spamming the runtime daemon.

## Edge Cases

- Cleanup called on a PR with no QA loop ever started → runtime file
  absent → unlink no-ops, summary `runtime_state` = False.
- Cleanup called concurrently with a live `set_action_state` writer
  (race: TUI sets QA running while user presses `yt`). The flock in
  `runtime_state` doesn't protect against unlink. Acceptable: the
  user just asked to tear everything down; if the QA loop lingers
  past unlink, the next `set_action_state` will recreate the file.
  We delete *after* `cleanup_pr_containers` so the loop's panes are
  already gone and won't write again.
- ThreadPool: `_run_runtime` is a subprocess call, releases the GIL.
  Threads are appropriate.
