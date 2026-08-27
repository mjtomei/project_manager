# pr-23d97f8 — popup spinner unresponsive to q/Esc/Ctrl+C

## Requirements

The picker popup spinner in `pm_core/cli/session.py:_wait_for_tui_command`
(`session.py:1217-1545`) must remain dismissable via q/Q/Esc/Ctrl+C in all
failure modes, not just the happy path. Three hypotheses from the task:

1. **cbreak setup failed silently.** Already partly handled at
   `session.py:1355-1371` — `cbreak_ok` is tracked but the spinner still
   loops, and `sys.stdin.read(1)` won't return per-char in canonical mode,
   so q/Esc do nothing until Enter (and even then are read as a line).
2. **Per-tick tmux/state call blocks.** `tmux_mod.list_windows(session)` at
   `session.py:1271` and `_rs.get_action_state(pr_id, action)` at
   `session.py:1379` round-trip the tmux server / read JSON. While blocked,
   the `select.select` keypress poll at `session.py:1513` isn't running.
3. **Race-induced state confusion.** No exit condition is ever reached.
   q/Esc still work in this case; UX hint is the fix.

## Implementation

### Per-tick observability (diagnostic ask)

Already mostly present: `PM_SPINNER_TRACE=1` logs `cur_state`,
`cur_window_ids`, `saw_disappear`, `window_open` per tick. Extend to also
log `cbreak_ok` and per-tick keypresses so the three hypotheses can be
distinguished from logs alone.

### Hypothesis 1 fix — cbreak failure → exit immediately

If `cbreak_ok is False`, the spinner cannot honor q/Esc per-character.
Rather than spinning unresponsively until the underlying command finishes,
log a warning, print a short message indicating the popup is being closed
because input handling is unavailable, and return immediately. The queued
TUI command is unaffected (it's already in the SIGUSR2 queue).

### Hypothesis 2 fix — wall-clock per-tick warnings + watchdog exit

Wrap each tick's `tmux_mod.list_windows` + `_rs.get_action_state` calls
with a wall-clock measurement. If a single tick exceeds a threshold (1.0s),
log a warning; if >=N consecutive ticks (5) all exceed the threshold, exit
the spinner with an error message rather than continuing to block. We
deliberately don't add hard timeouts to the calls themselves (would require
threads/signals, risky around tmux subprocess invocation).

### Hypothesis 3 fix — stuck-spinner UX hint

Track ticks since last observed state/window change. After 100 ticks (~15s)
with no change, repaint the spinner label with an explicit
"press q/Esc to dismiss" hint so the user knows dismissal is available.
Doesn't change correctness — q/Esc already work in this case.

### Defensive: drain Ctrl+C explicitly

`KeyboardInterrupt` handler at `session.py:1536-1538` returns silently. If
the tmux call swallows SIGINT (Python signals are only delivered between
opcodes, but a blocking `subprocess.run` inside `tmux_mod.list_windows`
would still re-raise on return). No change needed beyond ensuring the
finally block restores terminal state — already in place at
`session.py:1539-1545`.

## Implicit requirements

- The fix must not regress the happy path: q/Esc dismissal still works
  when cbreak succeeds and tmux is responsive.
- The cbreak-failure exit must release `_rs.request_suppress_switch` so
  the eventual completion doesn't steal focus, mirroring the keypress
  exit path at `session.py:1521-1527`.
- Terminal state must be restored in all exit paths (already handled by
  the `finally` at `session.py:1539-1545`).
- New log fields shouldn't spam normal runs — gate per-tick detail on the
  existing `PM_SPINNER_TRACE` env var. Watchdog/cbreak-fail warnings log
  unconditionally since they signal a real problem.

## Edge cases

- `cbreak_ok == False` but the action completes within one or two ticks
  (terminal-state short-circuit fires): without the fix, the user sees
  the popup briefly then it closes. The fix exits immediately, which is
  also fine — no worse than current.
- Watchdog trips on a transient tmux server hiccup that recovers: 5
  consecutive >1s ticks ≈ 5+ seconds of unresponsiveness, which already
  feels broken. Exiting with an error message is preferable to
  continuing to block.
- Stuck-spinner hint after 100 ticks: if the action genuinely takes >15s
  (long review-loop iteration), the hint appears as part of the label.
  Acceptable — it's truthful and non-disruptive.

## Ambiguities

None unresolved. Proceeding with implementation.
