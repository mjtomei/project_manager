---
title: Help Screen & Keybindings
description: Open help screen with ? and verify all documented keybindings work
---
You are testing the pm TUI help screen and verifying that every keybinding
documented in the help screen actually works. Your goal is to open the help
screen with '?', verify its contents, then systematically test each key.

## Background

The TUI has a help modal (HelpScreen) that opens when the user presses '?'.
It lists all available keybindings grouped by category:
- Tree Navigation: arrow keys, hjkl, Enter
- PR Actions: s, d, c, p, e, v
- Panes & Views: /, g, n, m, L, b
- Other: r, Ctrl+R, ?, q

Each key should produce a visible response - either a state change, a log
message, a new pane, or a modal. Keys that would be destructive (s=start PR,
d=done PR, q=quit) should be tested carefully to avoid changing project state.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `tmux display-message -p "#{session_name}"` - Get session name

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Run `pm tui view` to verify TUI is running and on the tech tree view
3. If in guide mode, press 'g' to dismiss and show the tech tree
4. Get session name: `tmux display-message -p "#{session_name}"`
5. Record initial pane count: `tmux list-panes -t <session> -F "#{pane_id}"`

### Part 1: Help Screen Content

1. Open help screen:
   - `pm tui send ?`
   - Wait 1 second
   - `pm tui view` to capture the help screen

2. Verify help screen contains ALL these keybindings:
   - Tree Navigation section:
     * Arrow keys / hjkl - Move selection
     * Enter - Show PR details
   - PR Actions section:
     * s - Start selected PR
     * z - Modifier: kill existing before next command
     * d - Mark PR as done
     * c - Launch Claude for PR
     * e - Edit selected PR
     * v - View plan file
   - Panes & Views section:
     * / - Open command bar
     * g - Toggle guide view
     * n - Open notes
     * m - Meta: work on pm itself
     * L - View TUI log
     * b - Rebalance panes
   - Other section:
     * r - Refresh / sync with GitHub
     * Ctrl+R - Restart TUI
     * ? - Show this help
     * q - Detach from session

3. Close help screen:
   - `pm tui send Escape`
   - `pm tui view` to verify help is dismissed

### Part 2: Safe Keybinding Tests

Test each key that is safe to press (won't change PR state or quit):

1. **Navigation keys** (test with frames):
   - `pm tui send Down` → selection should move down
   - `pm tui view` → verify selection changed
   - `pm tui send Up` → selection should move back
   - `pm tui send Right` → move to next column (if deps exist)
   - `pm tui send Left` → move back
   - `pm tui send j` → same as Down
   - `pm tui send k` → same as Up
   - `pm tui send l` → same as Right
   - `pm tui send h` → same as Left

2. **Enter** (show detail panel):
   - `pm tui send Enter`
   - `pm tui view` → detail panel should appear on right side
   - Verify it shows PR info (ID, title, status, plan context)

3. **v** (view plan):
   - `pm tui send v`
   - Wait 1 second
   - Check if a new pane opened with the plan file
   - `tmux list-panes` to verify pane count increased
   - Check pane registry for role "plan"

4. **/** (command bar):
   - `pm tui send /`
   - `pm tui view` → command bar should be focused
   - `pm tui send Escape` → should unfocus command bar

5. **g** (toggle guide):
   - `pm tui send g`
   - Wait 1 second
   - `pm tui view` → should either show guide view or launch guide pane
   - If guide pane launched, verify via `tmux list-panes`
   - Press 'g' again if needed to return to tech tree

6. **n** (notes):
   - `pm tui send n`
   - Wait 1 second
   - `tmux list-panes` → should see a new notes pane
   - Check registry for role "notes"

7. **L** (view log):
   - `pm tui send L`
   - Wait 1 second
   - `tmux list-panes` → should see a new log pane
   - Check registry for role "log"

8. **r** (refresh):
   - `pm tui send r`
   - `pm tui view` → log line should show "Refreshing..." or sync result

9. **b** (rebalance):
   - `pm tui send b`
   - `pm tui view` → log line should show "Layout rebalanced"

10. **?** (help - test open/close cycle):
    - `pm tui send ?`
    - `pm tui view` → help screen should appear
    - `pm tui send ?` → pressing again should close it
    - `pm tui view` → verify back to normal view

11. **e** (edit PR):
    - `pm tui send e`
    - Wait 1 second
    - `tmux list-panes` → should see editor pane
    - Note: editor may open and close quickly if EDITOR is not set

### Part 3: Destructive Keys (observe only)

Do NOT press these, just verify they exist in help:
- **s** - Would start a PR (changes project state)
- **d** - Would mark PR as done (changes project state)
- **c** - Would launch Claude (resource-intensive)
- **m** - Would launch meta session
- **q** - Would detach from tmux (ends test)
- **Ctrl+R** - Would restart TUI (disrupts test)

### Part 4: Cleanup

1. Kill any panes that were created during testing (notes, log, plan, etc.)
   - Use pane registry to find pane IDs
   - `tmux kill-pane -t <pane_id>` for each
2. Verify TUI is still responsive: `pm tui view`
3. Final pane count should match initial count

## Expected Behavior

- Help screen should be a modal overlay that lists ALL keybindings
- Each key should produce a visible effect (log message, pane, or state change)
- Keys should not error or crash when pressed with no PR selected
- Help screen should open/close cleanly with '?' or Escape

## Reporting

```
HELP SCREEN & KEYBINDINGS TEST
===============================

## Part 1: Help Screen Content
Help screen opens: [PASS/FAIL]
All keybindings documented: [PASS/FAIL]
  Missing keys (if any): <list>
  Extra/unexpected keys (if any): <list>
Help screen closes: [PASS/FAIL]

## Part 2: Keybinding Tests

Navigation:
  Down/j: [PASS/FAIL]
  Up/k: [PASS/FAIL]
  Right/l: [PASS/FAIL]
  Left/h: [PASS/FAIL]

PR Actions:
  Enter (detail panel): [PASS/FAIL] - <what detail panel shows>
  v (view plan): [PASS/FAIL] - <pane created? role correct?>
  e (edit PR): [PASS/FAIL] - <pane created?>

Panes & Views:
  / (command bar): [PASS/FAIL] - <focuses/unfocuses correctly?>
  g (guide): [PASS/FAIL] - <behavior observed>
  n (notes): [PASS/FAIL] - <pane created? role correct?>
  L (log): [PASS/FAIL] - <pane created? role correct?>
  r (refresh): [PASS/FAIL] - <log message>
  b (rebalance): [PASS/FAIL] - <log message>

Other:
  ? (help toggle): [PASS/FAIL] - <opens and closes cleanly?>

## Part 3: Destructive Keys
All documented in help: [PASS/FAIL]
  s (start PR): [PRESENT/MISSING]
  z (kill existing modifier): [PRESENT/MISSING]
  d (done PR): [PRESENT/MISSING]
  c (claude): [PRESENT/MISSING]
  m (meta): [PRESENT/MISSING]
  q (quit): [PRESENT/MISSING]
  Ctrl+R (restart): [PRESENT/MISSING]

## Part 4: Cleanup
Panes cleaned up: [PASS/FAIL]
TUI responsive after tests: [PASS/FAIL]

## Issues Found
<list any keybindings that don't work, produce errors, or behave unexpectedly>

## Frame Analysis
Total frames captured: <N>
Key state changes observed: <summary>

OVERALL: [PASS/FAIL]
```
