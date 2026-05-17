# Spec: TUI spinner for PRs in QA status

## Requirements

1. **Extend the spinner conditional in `pm_core/tui/tech_tree.py:533`.**
   The current block (lines 533–544) renders `⏸` / spinner glyph when
   `status in ("in_progress", "in_review")` and the PR has a workdir, by
   consulting `app._pane_idle_tracker` keyed by `pr_id`. Add an additional
   branch for `status == "qa"` that consults the same tracker but for a
   *set* of QA-scenario keys belonging to the PR (since QA runs N parallel
   scenarios in their own panes — see `pm_core/qa_loop.py:1086,1316,1430`
   where each scenario gets its own `pane_id`).

2. **Wire QA panes into `_pane_idle_tracker`.** Mirror the lazy-registration
   pattern in `pm_core/tui/review_loop_ui.py:_poll_impl_idle` (lines
   666–731). Source the per-scenario `pane_id` and `transcript_path` from
   `QAScenario` (set in `pm_core/qa_loop.py` after launch). Use a key
   scheme `qa:<pr_id>:s<scenario_index>` so the tracker can hold multiple
   QA panes per PR alongside the existing `pr_id`-keyed impl/review entry.
   Add the polling call to the existing shared poll in
   `pm_core/tui/qa_loop_ui.py:poll_qa_state` (already invoked from
   `review_loop_ui.py:293`).

3. **Per-PR aggregate state for the renderer.** When rendering, gather all
   `qa:<pr_id>:s*` keys from `tracker.tracked_keys()`. If any pane is
   `is_waiting_for_input` show `⏸` (yellow); else if any pane is active
   (tracked, not idle, not waiting) show the spinner glyph (cyan); else
   no marker. This matches the impl/review semantics one-to-one.

4. **Tests** (in `tests/test_tech_tree_qa_spinner.py` — new, focused on
   the small helper extracted from the conditional):
   - PR in qa with at least one active QA pane → spinner state.
   - PR in qa with all QA panes idle → no marker.
   - PR in qa with no QA panes tracked → no marker.
   - PR in qa with a QA pane waiting for input → waiting state.
   - Non-qa statuses pass through unchanged (covered by existing
     impl/review path being untouched; assert via a passthrough test).

## Implicit Requirements

- The QA-scenario key namespace (`qa:<pr_id>:s<idx>`) must not collide with
  existing impl/review keys (which use plain `pr_id`). The `qa:` prefix
  guarantees disjointness.
- The lazy-poll registration must tolerate scenarios whose `pane_id` /
  `transcript_path` haven't been set yet (early in the QA loop's startup
  before windows are created), and skip them silently — same as
  `_poll_impl_idle` skips PRs whose transcript symlink isn't created yet.
- `PaneIdleTracker.register` raises `ValueError` if the transcript path
  can't yield a session_id; catch and skip that tick.
- Cleanup: when the QA loop finishes, the tracker entries become "gone"
  on next poll (pane disappears) and naturally stop emitting active
  state. We don't need explicit unregister to satisfy the spec, but we
  should unregister on QA loop completion to keep the tracker tidy and
  ensure `tracked_keys()` doesn't grow unbounded — do this in
  `poll_qa_state` when the loop is being removed (already a deletion
  point at line 276).

## Ambiguities

- **Container vs tmux QA scenarios.** Container scenarios also expose
  `pane_id` and `transcript_path` on the QAScenario (qa_loop.py:1316),
  so the same registration path works for both — no special-casing
  needed. Resolved.
- **Scenarios with `pane_id` set but `transcript_path` is None.** Some
  qa_loop paths set pane_id without transcript_path immediately. Skip
  registration until both are present. Resolved.

## Edge Cases

- **No app._qa_loops entry but PR is in qa status.** This happens when
  the TUI restarts mid-QA — the panes still exist but the loop state is
  gone. We won't auto-register, so no spinner. Acceptable: matches
  impl/review behavior where stale tmux panes don't show spinner unless
  the in-memory loop state knows about them. (Impl actually does
  re-discover panes via `_find_impl_pane` + tmux window name, but for
  QA we'd need to re-scan windows by name pattern; punt this to a
  later PR — task says "no per-scenario count, separate richer-progress
  PR" implying this scope is conservative.)
- **PR with workdir=None in qa status.** Per requirement, gated on
  `pr.get("workdir")` like impl/review.
- **Mixed scenario states (one waiting, others active).** Waiting takes
  priority, matching the existing impl/review precedence (waiting before
  spinner).
