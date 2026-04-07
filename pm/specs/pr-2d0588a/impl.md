# Implementation Spec: Tmux Popup PR Switcher and Prefix-Key PM Command Runner

## Requirements

### R1: PR Switcher Popup (prefix+P)

Register a tmux prefix key binding (prefix+P) in `_register_tmux_bindings()` (`pm_core/cli/session.py:52-106`) that opens a `tmux display-popup` containing a picker listing all active PR windows in the current session.

**Window discovery**: Use `tmux_mod.list_windows(session)` (`pm_core/tmux.py:360-374`) to enumerate all windows. Match window names against the PR naming convention:
- Implementation: `#{gh_pr_number}` (e.g., `#158`) or `pr-NNN`
- Review: `review-#{gh_pr_number}` or `review-pr-NNN`
- QA main: `qa-#{gh_pr_number}` or `qa-pr-NNN`
- QA scenarios: `qa-#{gh_pr_number}-sN` or `qa-pr-NNN-sN`
- Merge: `merge-#{gh_pr_number}` or `merge-pr-NNN`

**Grouping**: Windows are grouped by PR display ID. Each group shows the PR's phases (impl, review, merge) as top-level entries. QA sessions (main + scenario windows) are collapsed by default — marked with a collapse indicator (e.g., `[+] QA (3)`) that the user can expand (e.g., `[-] QA → qa-#158, qa-#158-s1, qa-#158-s2`).

**Default selection**: The picker defaults to highlighting windows belonging to the PR of the current active window. The active window is determined by `#{window_name}` of the invoking pane's window.

**Window switching**: On selection, call `tmux select-window -t {session}:{window_index}` (matching the existing `select_window()` in `pm_core/tmux.py:385-394`). This switches only the invoking session's view, not all grouped sessions.

**Popup lifecycle**: The popup opens, runs the picker, and closes on selection or Escape. It must not resize or reflow the underlying window/pane layout.

### R2: PM Command Runner Popup (prefix+C)

Register a tmux prefix key binding (prefix+C) in `_register_tmux_bindings()` that opens a `tmux display-popup` with an interactive prompt where the user types a pm command.

**Command execution**: The popup runs a shell script that:
1. Displays a `pm> ` prompt
2. Accepts a pm command (e.g., `pr list`, `pr start pr-001`)
3. Executes `pm <command>` in the popup
4. Shows output, then exits (or stays open briefly for the user to read)

**Refocus behavior**: If the executed command creates a new tmux window (e.g., `pm pr start`), the invoking session should switch to that window. Since the command runs inside the popup (which is part of the same tmux session group), the existing `select_window()` mechanism used by `pm pr start` (`pm_core/cli/pr.py:994-1030`) will handle this automatically — `pm pr start` calls `tmux_mod.new_window()` or `tmux_mod.new_window_get_pane()` with `switch=True`, which creates the window in the base session. The popup runs in the invoking session context, so `_get_current_pm_session()` should resolve correctly.

**Popup lifecycle**: Same as R1 — opens, runs, closes without affecting the TUI layout.

## Implicit Requirements

### IR1: Picker Script Must Be Self-Contained Shell

The `tmux display-popup` command runs a shell command. The picker and command runner scripts must be standalone shell scripts (or inline shell commands) that can be invoked from `bind-key ... display-popup '...'`. They cannot rely on Python imports running inside the popup since the popup shell has no guaranteed Python environment context. However, they CAN call `pm` CLI commands for data gathering.

### IR2: Session Name Resolution in Popup Context

Inside a tmux popup, `#{session_name}` resolves to the session that launched the popup. The scripts need to use this to:
- List windows for the correct session (base session, not grouped)
- Call `select-window` targeting the correct grouped session
- Ensure `_get_current_pm_session()` resolves correctly for pm commands

### IR3: Socket Path Propagation

For shared sessions using `PM_TMUX_SOCKET`, the popup inherits the environment of the invoking pane. The `pm` CLI will pick up `PM_TMUX_SOCKET` from the environment, so tmux commands inside the popup will target the correct server. The `display-popup` command itself must use `_tmux_cmd()` (which respects socket path) if invoked programmatically, or the binding must be registered via `_tmux_cmd("bind-key", ...)` which already handles this.

### IR4: Non-PR Windows Excluded from Picker

Windows like the TUI (`tui`), notes, and any other non-PR windows should not appear in the PR switcher. Only windows matching the PR naming patterns should be listed.

### IR5: fzf Dependency

The task says "fzf-style picker" but fzf may not be installed. The implementation should:
- Use fzf if available for rich fuzzy-find interaction (arrow keys, fuzzy search, live filtering)
- Fall back to a simple numbered-list selector (`select`-style) if fzf is not present
- Show a one-line hint when using the fallback: `"Tip: install fzf for a better experience (brew install fzf / apt install fzf)"`

### IR6: Bindings Are Global

`_register_tmux_bindings()` registers bindings globally (no `-n` flag, uses `-T prefix`). The new bindings will be active in ALL tmux sessions, not just pm sessions. The popup scripts should gracefully handle being invoked from non-pm sessions (e.g., show "Not a pm session" and exit).

## Ambiguities

### A1: Exact Key Bindings

**Ambiguity**: The task suggests `prefix+P` and `prefix+C` but doesn't mandate them.

**Resolution**: Use `prefix+P` for the PR switcher (mnemonic: PR/Pick) and `prefix+M` for the command runner (mnemonic: coMmand). Avoid `prefix+C` as it conflicts with tmux's default `new-window` binding. If the user prefers different keys, they can be adjusted.

**Update after review**: Use whatever keys the user confirms. Starting with P and M.

### A2: QA Collapse/Expand Mechanism

**Ambiguity**: How does collapse/expand work in a shell-based picker? fzf doesn't natively support tree folding.

**Resolution**: Two-tier approach:
- **With fzf**: Show QA entries as a single collapsed summary line by default (e.g., `  [+] QA (3 sessions)`). If the user selects this line, re-run the picker with QA expanded for that PR. Alternatively, use fzf's `--bind` to toggle visibility.
- **Without fzf**: Show collapsed by default with a numbered option to expand.

A simpler alternative: Always show QA entries but indent/dim them, with the main phases (impl, review, merge) listed first. The "collapsed by default" could mean QA scenario windows (`qa-#N-sM`) are hidden but the main QA window (`qa-#N`) is shown.

**Proposed resolution**: Show the main QA window (`qa-#N`) in the list. QA scenario windows (`qa-#N-sM`) are hidden by default. Include a `[+] N more QA sessions` toggle line; selecting it re-invokes the picker with scenarios visible.

### A3: Popup Size

**Ambiguity**: What size should the popups be?

**Resolution**: PR switcher: 80 columns wide, height adapts to content (min 10, max 80% of terminal). Command runner: 80x10 (just needs a prompt line + some output space). Use `display-popup -w 80 -h <height>` with percentage-based sizing.

### A4: Current Window Detection for Default PR

**Ambiguity**: How to determine which PR the current window belongs to, for default-selection in the picker.

**Resolution**: Parse `#{window_name}` of the invoking window. Strip prefixes (`review-`, `qa-`, `merge-`) to get the base PR display ID. If the window name doesn't match any PR pattern, don't default-select anything.

### A5: What "Active PR Windows" Means

**Ambiguity**: Does "active" mean windows that currently exist in tmux, or PRs with active status in project.yaml?

**Resolution**: Windows that currently exist in the tmux session. The picker is about navigating between open windows, not about PR status. A PR with status "merged" could still have windows open if they haven't been cleaned up yet.

### A6: Command Runner Output Visibility

**Ambiguity**: Should the popup stay open after command execution for the user to read output, or close immediately?

**Resolution**: For commands that produce output (like `pr list`), keep the popup open until the user presses a key. For commands that create windows (like `pr start`), the popup can close immediately since focus will shift to the new window. Simplest approach: always wait for keypress after command completes, with a "Press any key to close" prompt.

## Edge Cases

### E1: No PR Windows Open

If no PR windows exist in the session, the picker should show "No PR windows open" and exit gracefully.

### E2: Non-PM Session Invocation

Since bindings are global, invoking from a non-pm tmux session should show an appropriate message ("Not a pm session") and exit.

### E3: Window Killed Between Listing and Selection

If a window is killed between when the picker lists it and when the user selects it, `select-window` will fail silently (returns non-zero). This is acceptable — no special handling needed.

### E4: Multiple Sessions Viewing Same Windows

In grouped sessions, multiple terminals may be attached. The popup should only affect the invoking terminal's session, which `#{session_name}` in the tmux format string provides.

### E5: Popup Invoked While Another Popup Is Open

tmux only allows one popup per client. If a popup is already open, `display-popup` replaces it. This is acceptable default behavior.

### E6: Very Long PR Lists

If there are many PRs with many windows, the picker list could be long. fzf handles this well with scrolling and fuzzy search. The fallback selector should paginate or scroll.

### E7: Command Runner and Environment

The command runner popup inherits the environment of the pane that invoked it. `PM_TMUX_SOCKET`, `PM_PROJECT`, and other env vars will be available. However, the popup's working directory may differ from the pm project root. The script should set the working directory appropriately or rely on pm's project-root discovery.

### E8: display-popup and Tmux Version

`tmux display-popup` requires tmux 3.2+. The current environment has tmux 3.2a, which supports it. Should gracefully fail on older tmux with a message if needed.

## Implementation Plan

### Files to Modify

1. **`pm_core/cli/session.py`** — Add two new `bind-key` calls in `_register_tmux_bindings()` for prefix+P and prefix+M (or chosen keys).

2. **`pm_core/tmux_popup.py`** (new) — Module containing:
   - `generate_picker_script(session: str) -> str` — Generates the shell script for the PR window picker
   - `generate_command_runner_script(session: str) -> str` — Generates the shell script for the pm command prompt
   - Helper to build the window list grouped by PR

3. **`pm_core/cli/popup.py`** (new, optional) — CLI commands `pm _popup-picker` and `pm _popup-cmd` that the popup scripts can call to:
   - List windows grouped by PR in a formatted way
   - Execute the window switch

### Architecture Approach

The cleanest approach: register the bindings as `display-popup` calls that invoke `pm _popup-picker` and `pm _popup-cmd` internal CLI commands. This keeps the logic in Python while running in the popup shell. Similar pattern to existing internal commands like `pm _pane-closed`, `pm _pane-switch`, etc.

```
prefix+P → display-popup 'pm _popup-picker #{session_name} #{window_name}'
prefix+M → display-popup 'pm _popup-cmd #{session_name}'
```

The `_popup-picker` command:
1. Loads the tmux window list
2. Groups by PR display ID
3. Formats with collapse markers for QA
4. Pipes to fzf (or fallback selector)
5. Parses selection and calls select-window

The `_popup-cmd` command:
1. Shows `pm> ` prompt (using `read`)
2. Runs the entered pm command
3. Waits for keypress to dismiss
