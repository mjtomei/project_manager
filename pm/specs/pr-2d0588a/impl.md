# Implementation Spec: Tmux Popup PR Switcher and Prefix-Key PM Command Runner

## Requirements

### R1: PR Action Picker Popup (prefix+P)

Register a tmux prefix key binding (prefix+P) in `_register_tmux_bindings()` (`pm_core/cli/session.py`) that opens a `tmux display-popup` containing an action-based PR picker.

**Action-based design**: Instead of discovering existing tmux windows, the picker loads all PRs from `project.yaml` and shows available actions for the PR of the current window, based on status. This is more robust than window tracking — the pm commands themselves handle window creation/switching.

**PR discovery**: Use `store.load(state_root())` to load all PRs. The picker is **scoped to the current window's PR** only — it determines the active PR by parsing `#{window_name}` and shows only that PR's actions. From a non-PR window the picker shows a "Switch to a PR window" hint and exits.

**Available actions** (all returned for any non-terminal status; merged/closed PRs have no actions):
- start, review, review-loop, qa, merge

The action representing the PR's current phase is marked with a `●` indicator. If the action's tmux window is already open, the line is annotated with `[open]`.

**Display format**: One header line (non-selectable) showing display ID, status, and title; one selectable line per action below:
```
  #158  (in_progress)  Add popup picker
  ● start              #158
    review             #158
    review-loop        #158
    qa                 #158
    merge              #158
```

**Shortcut keys** (fzf `--expect`): `s`=start, `d`=review, `l`=review-loop, `a`=qa, `g`=merge. `q`/`Esc` quits.

**Command execution**: On selection:
- Direct CLI commands (start, review, merge): run `pm pr <action> <pr_id>` as subprocess
- TUI-routed commands (qa, review-loop): enqueue via `trigger_tui_command()` (SIGUSR2 + per-session queue file)

**Popup lifecycle**: The popup opens, runs the picker, and closes on selection or Escape. It must not resize or reflow the underlying window/pane layout.

### R2: PM Command Runner Popup (prefix+M)

Register a tmux prefix key binding (prefix+M) in `_register_tmux_bindings()` that opens a `tmux display-popup` with an interactive prompt where the user types a pm command.

**Command execution**: The popup runs `pm _popup-cmd #{session_name}` which:
1. Displays a `pm> ` prompt
2. Accepts a pm command (e.g., `pr list`, `pr start pr-001`)
3. Executes `pm <command>` in the popup
4. On error, keeps popup open for user to read output

**Refocus behavior**: If the executed command creates a new tmux window (e.g., `pm pr start`), the invoking session should switch to that window. Since the command runs inside the popup (which is part of the same tmux session group), the existing `select_window()` mechanism will handle this automatically.

**Popup lifecycle**: Same as R1 — opens, runs, closes without affecting the TUI layout.

### R3: TUI Command Bar Enhancement (review-loop PR_ID)

Extend `handle_command_submitted` in `pm_core/tui/pr_view.py` to accept `review-loop [start|stop] [PR_ID]`. With no subcommand it toggles (current behavior). `start` always starts (idempotent — logs a message if a loop is already running for that PR), so repeated picker presses don't accidentally stop a running loop. `stop` stops. The optional `PR_ID` selects the PR in the tree before acting. This lets the popup picker route review-loop commands with a specific target. (The `strict` variant from the original PR notes was dropped in commit b9c9b54.)

## Implicit Requirements

### IR1: Picker Uses pm CLI Internally

The `tmux display-popup` runs `pm _popup-picker #{session_name} #{window_name}`. This keeps logic in Python while running in the popup shell. The picker loads project state via `store.load()` and runs pm commands via subprocess or TUI routing.

### IR2: Session Name Resolution in Popup Context

Inside a tmux popup, `#{session_name}` resolves to the session that launched the popup. The scripts use this to validate the pm session and route commands correctly.

### IR3: Socket Path Propagation

For shared sessions using `PM_TMUX_SOCKET`, the popup inherits the environment of the invoking pane. The `pm` CLI picks up `PM_TMUX_SOCKET` from the environment.

### IR4: TUI Routing for QA and Review Loops

QA (`pr qa`) and review loops require the TUI's Textual app context.
Routing happens via a SIGUSR2 + per-session command-queue file IPC,
following the SIGUSR1 reload pattern added in commit 9c30b38:

- TUI on mount: writes `~/.pm/tui-{session}.cmd-queue` (initially empty)
  and registers a SIGUSR2 handler that drains the queue file line-by-line
  and dispatches each line through the same path as
  `CommandSubmitted` (`handle_command_submitted`).
- External callers (`trigger_tui_command(session, cmd)` in
  `pm_core/cli/helpers.py`): append the command line to the queue file
  under a file lock, then `os.kill(tui_pid, SIGUSR2)`.
- The queue model means the picker (and any future caller) can enqueue
  multiple commands at once and they run in order without needing
  `tmux send-keys` or focus-dependent timing.

This replaces the earlier brittle `send-keys '/' → sleep → -l "<cmd>"
→ Enter` approach where literal text could leak to whichever widget
held focus before Textual finished focusing the command bar (observed
as `r`/`e` etc. firing as TUI key bindings — refresh, edit-pane —
instead of being typed into the command bar).

### IR5: fzf Dependency

- Use fzf if available for rich fuzzy-find interaction
- Fall back to a simple numbered-list selector if fzf is not present
- Show a one-line hint when using the fallback

### IR6: Bindings Are Global

`_register_tmux_bindings()` registers bindings globally. The popup scripts gracefully handle being invoked from non-pm sessions (show "Not a pm session" and exit).

## Ambiguities

### A1: Exact Key Bindings

**Resolution**: `prefix+P` for the PR action picker (mnemonic: PR/Pick), `prefix+M` for the command runner (mnemonic: coMmand). Avoids `prefix+C` which conflicts with tmux's default `new-window`.

### A2: Popup Size

**Resolution**: PR picker: 80 columns wide, 80% height. Command runner: 80 columns wide, 50% height.

### A3: Current Window Detection for Default PR

**Resolution**: Parse `#{window_name}` of the invoking window. Strip prefixes (`review-`, `qa-`, `merge-`) to get the base PR display ID.

### A4: Command Runner Output Visibility

**Resolution**: On error (non-zero exit), keep popup open with "Press Enter to close..." prompt. On success, popup closes immediately.

## Edge Cases

### E1: No Actionable PRs

If all PRs are merged/closed, show "No PRs with available actions." and exit.

### E2: Non-PM Session Invocation

Show "Not a pm session." and exit.

### E3: TUI Pane Not Found for Routed Commands

If QA or review-loop is selected but the TUI pane can't be found, show an error and keep the popup open.

### E4: display-popup and Tmux Version

`tmux display-popup` requires tmux 3.2+. Should gracefully fail on older tmux.

## Implementation Plan

### Files Modified

1. **`pm_core/cli/session.py`** — New popup commands and action logic:
   - `_PR_ACTIONS` dict mapping status → available actions
   - `_actions_for_status()` — lookup actions for a status
   - `_current_window_pr_id()` — extract PR display ID from window name
   - `_build_picker_lines()` — format PR+action lines for picker
   - `_run_picker_command()` — execute direct CLI or TUI-routed command
   - `popup_picker_cmd` — `pm _popup-picker` CLI command
   - `popup_cmd_cmd` — `pm _popup-cmd` CLI command
   - Two `bind-key` calls in `_register_tmux_bindings()`

2. **`pm_core/tui/pr_view.py`** — Enhanced `handle_command_submitted()`:
   - `review-loop PR_ID` support: select PR in tree before starting loop
   - `review-loop strict PR_ID` and `review-loop stop PR_ID` variants

3. **`tests/test_popup_picker.py`** — Tests for action-based picker logic

### Architecture

```
prefix+P → display-popup 'pm _popup-picker $(tmux display-message ...)'
                ↓
         Load PRs from project.yaml
                ↓
         Build action lines per PR status
                ↓
         fzf (or fallback numbered list)
                ↓
         On selection:
           ├─ Direct: pm pr start/review/merge PR_ID (subprocess)
           └─ TUI:    trigger_tui_command(session, "pr qa PR_ID")
                      ├─ append cmd to ~/.pm/tui-{session}.cmd-queue
                      └─ os.kill(tui_pid, SIGUSR2)
                           ↓
                    TUI SIGUSR2 handler drains queue → dispatches
                    each line through handle_command_submitted

prefix+M → display-popup 'pm _popup-cmd #{session_name}'
                ↓
         pm> prompt → user types command → subprocess → exit
```
