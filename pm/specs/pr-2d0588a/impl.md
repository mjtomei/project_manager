# Implementation Spec: Tmux Popup PR Switcher and Prefix-Key PM Command Runner

## Requirements

### R1: PR Action Picker Popup (prefix+P)

Register a tmux prefix key binding (prefix+P) in `_register_tmux_bindings()` (`pm_core/cli/session.py`) that opens a `tmux display-popup` containing an action-based PR picker.

**Action-based design**: Instead of discovering existing tmux windows, the picker loads all PRs from `project.yaml` and shows available actions per PR based on status. This is more robust than window tracking — the pm commands themselves handle window creation/switching.

**PR discovery**: Use `store.load(state_root())` to load all PRs. Filter to PRs with actionable statuses (not merged/closed).

**Available actions per status**:
- `pending` → start
- `in_progress` → start, review, qa, review-loop
- `in_review` → start, review, qa, review-loop, merge
- `qa` → start, review, qa, review-loop

**Display format**: Each PR gets a header line (non-selectable) showing display ID, status, and title. Below it, indented action lines are selectable:
```
> #158  (in_progress)  Add popup picker
    start          #158
    review         #158
    qa             #158
    review-loop    #158
  #160  (pending)  Fix login bug
    start          #160
```

**Default selection**: The picker defaults to highlighting actions for the PR of the current active window, determined by parsing `#{window_name}`.

**Command execution**: On selection:
- Direct CLI commands (start, review, merge): run `pm pr <action> <pr_id>` as subprocess
- TUI-routed commands (qa, review-loop): send the command to the TUI command bar via `tmux send-keys` to the TUI pane

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

Extend `handle_command_submitted` in `pm_core/tui/pr_view.py` to accept `review-loop PR_ID` (e.g., `review-loop pr-001`, `review-loop strict pr-001`). This allows the popup picker to route review-loop commands through the TUI command bar with a specific PR target, rather than relying on the currently selected tree item.

## Implicit Requirements

### IR1: Picker Uses pm CLI Internally

The `tmux display-popup` runs `pm _popup-picker #{session_name} #{window_name}`. This keeps logic in Python while running in the popup shell. The picker loads project state via `store.load()` and runs pm commands via subprocess or TUI routing.

### IR2: Session Name Resolution in Popup Context

Inside a tmux popup, `#{session_name}` resolves to the session that launched the popup. The scripts use this to validate the pm session and route commands correctly.

### IR3: Socket Path Propagation

For shared sessions using `PM_TMUX_SOCKET`, the popup inherits the environment of the invoking pane. The `pm` CLI picks up `PM_TMUX_SOCKET` from the environment.

### IR4: TUI Routing for QA and Review Loops

QA (`pr qa`) and review loops require the TUI's Textual app context. The picker routes these commands by finding the TUI pane and sending keystrokes: `Escape` → `/` → command text → `Enter`. This reuses the TUI's existing command bar interception for `pr qa PR_ID` and `review-loop PR_ID`.

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
prefix+P → display-popup 'pm _popup-picker #{session_name} #{window_name}'
                ↓
         Load PRs from project.yaml
                ↓
         Build action lines per PR status
                ↓
         fzf (or fallback numbered list)
                ↓
         On selection:
           ├─ Direct: pm pr start/review/merge PR_ID (subprocess)
           └─ TUI:    send-keys to TUI pane → / pr qa PR_ID Enter

prefix+M → display-popup 'pm _popup-cmd #{session_name}'
                ↓
         pm> prompt → user types command → subprocess → exit
```
