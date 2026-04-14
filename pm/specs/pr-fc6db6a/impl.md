# Implementation Spec: Prevent plain 'd' from opening duplicate review window when review loop is running

## Requirements

1. **Check `app._review_loops` in `done_pr()`** (`pm_core/tui/pr_view.py:123-158`): Before proceeding with the fast-path window check or spawning a new review subprocess, `done_pr()` must check whether a review loop is already managing the selected PR via `app._review_loops.get(pr_id)`.

2. **Show informational message and return early**: If `app._review_loops[pr_id]` exists and `loop.running` is True, display a message like `"Review loop running for {pr_id}"` via `app.log_message()` and return without opening a review window or spawning a subprocess.

3. **Placement**: The check must happen after `pr_id` is resolved (line 128) but before the fast-path window check (line 136) and before `run_command()` (line 158). This ensures both code paths are guarded.

## Implicit Requirements

1. **Only block when loop is actually running**: The check must verify `loop.running is True`, not merely that a key exists in `_review_loops`. A loop entry can persist after completion with `running=False` (see `ReviewLoopState` in `pm_core/review_loop.py:84-100`). A non-running loop entry should not block `done_pr()`.

2. **Apply regardless of `fresh` parameter**: Even when `fresh=True` (which skips the fast-path), a running review loop should still block. The `fresh` flag is used by `z d` via `stop_loop_or_fresh_done()` (`pm_core/tui/review_loop_ui.py:66-79`), which already checks `_review_loops` before calling `done_pr(app, fresh=True)`. But `done_pr(fresh=True)` could theoretically be called from other paths, so the guard should be unconditional.

3. **Consistent pattern with existing code**: The check pattern should match the existing idiom used in `start_or_stop_loop()` (`review_loop_ui.py:93-94`) and `stop_loop_or_fresh_done()` (`review_loop_ui.py:73-74`):
   ```python
   loop = app._review_loops.get(pr_id)
   if loop and loop.running:
       ...
   ```

## Ambiguities

1. **Should the check use `sticky` for the message?**
   - `_start_loop()` uses `sticky=3` for its "loop started" message. The blocking message here is transient user feedback.
   - **Resolution**: Use plain `app.log_message()` without `sticky` — the message is informational and does not need to persist across screen refreshes.

2. **Should this also guard `done_pr(fresh=True)` calls?**
   - The only caller that passes `fresh=True` is `stop_loop_or_fresh_done()` which already checks `_review_loops` and only calls `done_pr(fresh=True)` when no loop is running.
   - **Resolution**: Guard unconditionally (before the `if not fresh:` block) for defense in depth. This adds no cost and protects against future callers.

## Edge Cases

1. **Loop between iterations (window momentarily absent)**: When the review loop is between iterations, the review tmux window may be killed and not yet recreated. The fast-path `find_window_by_name()` returns None, so without this fix `done_pr()` falls through to `run_command()` and spawns a competing review. The `_review_loops` check catches this because `loop.running` remains True between iterations.

2. **`get_pm_session()` returns None**: If `get_pm_session()` returns None (e.g., pane registry race from pr-e3cf481), the fast-path is entirely skipped (`session` is falsy on line 140). Without this fix, `done_pr()` falls through to spawning a new review window. The `_review_loops` check is placed before this code, so it catches the case regardless.

3. **Loop just completed but not yet cleaned up**: If the loop finished (verdict reached) but `running` is already set to False, `done_pr()` should proceed normally — the user may want to open a fresh review. The `loop.running` check handles this correctly.

4. **Multiple PRs with loops**: `_review_loops` is keyed by `pr_id`, so checking `app._review_loops.get(pr_id)` only blocks the specific PR that has a running loop. Pressing `d` on a different PR works as expected.
