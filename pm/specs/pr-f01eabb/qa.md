# QA Spec: TUI spinner for PRs in QA status

## Requirements

The tech tree TUI should animate a spinner for PRs in `qa` status, mirroring
the existing impl/review spinner semantics:

1. **Active QA pane → cyan spinner glyph** (one of `◐◓◑◒`, animated by
   `_anim_frame`) appended to the status text. Triggered when at least
   one QA scenario pane registered under `qa:<pr_id>:s<idx>` is tracked
   and neither idle nor waiting.
2. **Waiting-for-input QA pane → yellow `⏸` glyph.** Waiting takes
   priority over active across all of the PR's scenarios.
3. **All QA panes idle / no QA panes tracked → no marker.**
4. **Gating:** only applies when `status == "qa"` AND the PR row has a
   `workdir`. Non-qa statuses must be unaffected.
5. **Lifecycle wiring** (in `poll_qa_state`):
   - Each `QAScenario` with both `pane_id` and `transcript_path` set is
     lazily registered with `app._pane_idle_tracker` under
     `qa:<pr_id>:s<index>` and polled every tick.
   - Scenarios missing pane_id or transcript_path are skipped silently.
   - `tracker.register` ValueErrors are swallowed (e.g. transcript can't
     yield a session_id yet).
   - On QA loop completion (second tick after `_ui_complete_notified`),
     all `qa:<pr_id>:s*` entries are unregistered before the loop is
     removed from `app._qa_loops`.
6. **Key namespace:** `qa:` prefix prevents collision with impl/review
   keys (which are bare `pr_id`).

## Setup

Manual TUI test against a throwaway project per `tui-manual-test.md`.
We need a PR forced into `qa` status with the in-memory `_qa_loops`
state populated and at least one `QAScenario` having `pane_id` /
`transcript_path` set so registration succeeds.

A unit-test pass is also valuable — `tests/test_tech_tree_qa_spinner.py`
exercises `qa_pane_state` aggregation and `poll_qa_state` registration
wiring.

## Edge Cases

- Multiple scenarios with mixed states (waiting wins over active wins
  over idle).
- Scenario without a transcript yet → skipped, no spinner.
- PR with `workdir=None` in qa status → no spinner.
- Other PRs' `qa:` keys don't leak into this PR's aggregation.
- Non-qa status (e.g. `in_progress`, `in_review`) remains driven by the
  pre-existing `pr_id`-keyed branch — must not regress.
- Completion lifecycle: tracker must be cleaned up so `tracked_keys()`
  doesn't grow.

## Pass/Fail Criteria

PASS:
- Unit tests in `tests/test_tech_tree_qa_spinner.py` pass.
- `qa_pane_state` returns waiting/active/idle correctly per the rules
  above.
- `poll_qa_state` registers tracker entries for scenarios with full
  pane/transcript info, skips incomplete ones, and unregisters on
  completion.
- Tech tree renders a cyan spinner glyph for a `qa` PR with an active
  pane, `⏸` for waiting, and nothing for fully-idle / no panes.
- Non-qa status PRs render exactly as before.

FAIL:
- Spinner appears for non-qa statuses or for qa PRs without a workdir.
- Tracker entries leak across PRs or persist after QA completes.
- Crash on a scenario missing pane_id/transcript_path or on a
  ValueError from `register`.
- Waiting state not winning over active when both are present.

## Ambiguities

None unresolved. Spec author documented two questions in `impl.md`
(container vs tmux scenarios; pane_id without transcript) and resolved
both.

## Mocks

No external service mocks needed. The unit tests use a real
`PaneIdleTracker` plus filesystem transcript symlinks in `tmp_path`,
and patch `pm_core.tmux.pane_exists` / `pm_core.hook_events.read_event`
where the registration path would otherwise hit tmux or the hook
event log. For TUI manual testing, follow `tui-manual-test.md` against
a throwaway project — no production data or external services touched.
