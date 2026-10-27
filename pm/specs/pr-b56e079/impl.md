# pr-b56e079 — picker-driven `pr merge` swallows errors and skips resolve window

## Requirements

1. **Picker `merge` action launches resolve window like the TUI does.**
   - `pm_core/cli/session.py` defines `_ALL_ACTIONS` (line 872) with the
     entry `("merge", "pr merge {pr_id}")`. The TUI's merge action in
     `pm_core/tui/pr_view.py:202` instead invokes
     `pr merge --resolve-window {pr_id}`.
   - The picker entry must include `--resolve-window` so a conflicting
     merge launches a Claude resolution window in a new tmux window
     (the same UX as the TUI command bar).

2. **Errors from picker-dispatched commands are visible to the user.**
   - `_run_picker_command` (session.py:1420–1445) currently runs the
     subprocess with inherited stdout/stderr, then calls `_wait_dismiss`
     only on non-zero exit. The reported symptom is that the popup
     closes without legible output. The dispatch should capture the
     subprocess's stdout/stderr and re-emit them itself on failure so
     the popup TTY/raw-mode does not eat the bytes, and the user always
     sees what failed before pressing a key to dismiss.

3. **In-tmux pm invocations behave like TUI command-bar invocations.**
   - When `pm` runs inside the project tmux session it should set
     `PM_IN_TMUX_SESSION=1` so subcommands can opt into tmux-aware
     behavior. `pm_core/wrapper.py` is the natural injection point.
   - `pm pr merge` consumes the env var: when set and `--resolve-window`
     was not explicitly passed, default `resolve_window=True`. This
     gives shell-pane and popup-shell invocations parity with the TUI
     command bar without changing behavior outside tmux.

4. **Tests.**
   - Unit test that the picker `merge` action template now contains
     `--resolve-window`.
   - Unit test that `_run_picker_command` re-emits captured stderr on
     non-zero exit (mock `subprocess.run`, assert echo prefix and
     `_wait_dismiss` invoked).
   - Unit test for the env-var default in `pr merge` (covered by
     verifying `PM_IN_TMUX_SESSION=1` produces resolve-window behavior;
     simplest to assert the option default function or invoke through
     CliRunner with a stubbed merge path).

## Implicit Requirements

- The picker's `merge` entry must remain the only direct-CLI merge
  dispatcher; TUI dispatches via `pr_view.py` already pass the flag
  explicitly, so the `PM_IN_TMUX_SESSION` default does not double up.
- Capturing stderr in `_run_picker_command` must not break `tui:`-routed
  commands (which take a different code path) and must not block long
  operations from showing progress. Since direct-CLI dispatch is used
  only for `pr start` / `pr review` / `pr merge` (all short dispatch
  steps that hand off to a Claude window), capturing the dispatcher's
  output is acceptable.
- `PM_IN_TMUX_SESSION` is set only when `$TMUX` is present, so running
  `pm` from a non-tmux shell is unaffected.

## Ambiguities (resolved)

- **Should `pm pr merge` auto-enable `--resolve-window` whenever
  `PM_IN_TMUX_SESSION` is set, or only when also invoked from the
  picker?** Resolution: env-var driven, per the task's "more generally"
  guidance — any in-tmux invocation defaults to TUI-parity behavior.
  Outside tmux, the flag stays opt-in.
- **Streaming vs captured output for picker dispatch.** Resolution:
  capture and re-emit. Picker dispatches are short and the streaming
  output was already unreliable inside the popup raw TTY.

## Edge Cases

- Merge that succeeds (no conflicts) — `pr merge` exits 0, picker
  closes silently. Unchanged behavior.
- Merge that needs a resolve window — `pr merge --resolve-window`
  launches the window and exits 0. Picker closes; window handles
  resolution. New, correct behavior.
- Merge that errors before/after launching the window (e.g.
  branch-protection rejection on GitHub fallback path) — picker now
  surfaces stderr and waits for keypress.
- `pm pr merge` from a non-tmux shell — `PM_IN_TMUX_SESSION` not set,
  behavior unchanged (no auto resolve-window).
- TUI command-bar `pr merge --resolve-window` — already explicit, env
  var default has no effect.
