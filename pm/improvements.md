# Improvements

Improvements suggested by the autonomous monitor.

## PRs

### PR: Add periodic auto-start scan for state changes
- **description**: Auto-start currently only scans for ready PRs on startup and after merge events. Add a periodic scan (every 30-60 seconds) that checks for newly-ready PRs. This would handle cases where PRs are manually reset, status changes are made outside auto-start's flow, or state recovery after crashes.
- **tests**: Enable auto-start. Wait for periodic scan to detect a ready PR. Verify it starts the PR without requiring a merge event trigger.
- **files**: Auto-start loop logic — add a timer-based scan alongside event-based triggers.

---

### PR: Tmux popup PR switcher and prefix-key pm command runner
- **description**: Add two tmux integrations registered via `_register_tmux_bindings`: (1) A prefix-key binding (e.g. `prefix + P`) that opens a `tmux display-popup` with an fzf-style picker listing all active PR windows with their status and phase (implementation/review/QA). Selecting one switches to that window in the current session only (using `select-window`, not `switch_sessions_to_window`). (2) A prefix-key binding (e.g. `prefix + :` or `prefix + C`) that opens a `tmux display-popup` with a `pm` command prompt — the user types a pm command (e.g. `pr start pr-123`, `plan review`), it runs in the popup, and if the command opens a window it refocuses using the same mechanism as TUI-launched commands. Both popups run and exit without affecting the current window's pane layout or resizing the TUI. **Human-guided testing needed**: popup display from various window contexts, refocus behavior after selecting a PR, command execution in popup, verify TUI window is not resized.
- **tests**: Test that the tmux bindings are registered in `_register_tmux_bindings`. Test that the PR picker script lists windows with correct status labels. Test that selecting a PR switches the window in the invoking session only. Test that the command runner popup executes pm commands and exits cleanly.
- **files**: pm_core/cli/session.py, pm_core/tmux.py, pm_core/tui/pane_ops.py
- **depends_on**:
