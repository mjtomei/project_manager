# pr-b423bfd — picker spinner shows 'review-loop: done…' on ERROR

## Code paths

- `pm_core/runtime_state.py` — `set_action_state`, `VALID_STATES` (includes `done` and `failed`).
- `pm_core/tui/review_loop_ui.py:315` — `_on_complete_from_thread` always writes
  `state="done"` with `verdict=state.latest_verdict`. This is the source of the
  state-vs-verdict mismatch when the loop ends with `ERROR` / `KILLED`.
- `pm_core/review_loop.py:280-288` — terminal verdicts emitted by the loop:
  - `VERDICT_KILLED = "KILLED"` (pane killed before verdict)
  - `"ERROR"` (raw string set in the generic exception handler)
  - `VERDICT_PASS / VERDICT_NEEDS_WORK / VERDICT_INPUT_REQUIRED`
  Plus `latest_verdict` may be empty if the loop is stopped before any
  iteration completes.
- `pm_core/cli/session.py:_wait_for_tui_command` (line 1171+) — popup spinner
  loop. Today exits only when the target tmux window opens; ignores `cur_state`
  beyond using it as a label. Never inspects terminal states.
- `_wait_dismiss` (line 1384) — already exists for "press a key to close" UX.

## Requirements

1. **Map ERROR/KILLED verdicts to `state="failed"`.**  In
   `_on_complete_from_thread`, choose state based on `state.latest_verdict`:
   - `PASS` → `state="done"`
   - `NEEDS_WORK` → `state="done"` (loop hit max-iterations or was stopped — still
     a clean termination, not a launch/runtime failure)
   - `ERROR` / `KILLED` → `state="failed"`
   - empty/missing verdict → `state="done"` (e.g. user-requested stop with no
     iteration completed)

2. **Spinner exits on terminal state.** `_wait_for_tui_command` must check
   `cur_state in {"done", "failed"}` each tick and exit the spin loop instead
   of waiting indefinitely for a tmux window that may never appear (review-loop
   has no persistent target window once iterations stop).
   - On `state="done"` with success-ish verdict (PASS, empty, NEEDS_WORK):
     dismiss popup automatically as today (the user got what they asked for).
   - On `state="failed"` OR verdict in {ERROR, KILLED}: print a clear final
     line ("✗ review-loop: failed (ERROR)") and call `_wait_dismiss` so the
     user sees the failure before the popup closes.

3. **Picker label reflects verdict on terminal states.** When `cur_state` is
   `failed`, label as `failed (<verdict>)` instead of `done…`. (Not strictly
   required — terminal-exit handles the bug — but improves the spinner final
   frame.)

## Implicit requirements

- `_wait_for_tui_command` runs in the popup process; `_wait_dismiss` already
  handles cbreak/tty correctly and is safe to call from there. Need to make
  sure the cursor-show / termios restore in the existing `finally` block runs
  before `_wait_dismiss` so it doesn't double-toggle cbreak.
- The spinner must still wait for window appearance for non-terminal states;
  only short-circuit when state is terminal.
- `review-loop` is the action that triggered this bug. Other actions (start,
  review, qa) end with `state="done"` only after their pane exists, so the
  window-open path still wins for them — but the terminal-state check is
  benign for all actions.

## Edge cases

- Loop superseded: `_on_complete_from_thread` already returns early via
  `_is_active_loop`; nothing changes there.
- A previous run left `state="done"` in runtime_state; the new launch writes
  `state="running"` synchronously in `_start_loop` (line 236) before the
  popup's spinner first reads, so the spinner won't immediately exit on a
  stale terminal entry. Confirmed by reading review_loop_ui.py lines 230-240.
- `latest_verdict` may be the empty string when the loop stopped before any
  iteration; treat as success-ish (state="done").

## Tests

`tests/test_review_loop_terminal_state.py`:
- `_on_complete_from_thread` with verdict=ERROR writes state="failed".
- `_on_complete_from_thread` with verdict=KILLED writes state="failed".
- `_on_complete_from_thread` with verdict=PASS writes state="done".
- `_on_complete_from_thread` with empty verdict writes state="done".

`tests/test_picker_spinner_terminal.py` (or extend existing):
- `_wait_for_tui_command` exits when runtime_state shows state="failed".
- `_wait_for_tui_command` exits when runtime_state shows state="done" without
  needing a tmux window (review-loop case).
- These tests will exercise the spinner via mocks for tmux/stdin since real
  tty interaction isn't viable in CI.

## Ambiguities

None unresolved. The bug description provides the resolution choices and I
picked the more localized one: writers emit `failed` for failure verdicts,
picker exits on terminal state.
