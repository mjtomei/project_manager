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
- Tree Navigation: arrow keys, hjkl, J/K, x, X, f, F
- PR Actions: s, d, g, e/Enter, v, M, A, w
- Panes & Views: c, H, /, n, m, L, p, t, q, b
- Companion Pane: S, G
- Other: z, r, C, Ctrl+R, ?, ctrl+b d
- Review Loop: zz d, zzz d, z d

When the QA view is active, the help screen shows QA-specific navigation
instead of Tree Navigation (j/k, Enter, e, a, q=back).

Each key should produce a visible response - either a state change, a log
message, a new pane, or a modal. Keys that would be destructive (s=start PR,
g=merge PR, d=done PR) should be tested carefully to avoid changing project state.

Note: q now toggles the QA instructions view (it no longer quits). Use
ctrl+b d to detach from the tmux session.

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
3. Get session name: `tmux display-message -p "#{session_name}"`
4. Record initial pane count: `tmux list-panes -t <session> -F "#{pane_id}"`

### Part 1: Help Screen Content

1. Open help screen:
   - `pm tui send ?`
   - Wait 1 second
   - `pm tui view` to capture the help screen

2. Verify help screen contains ALL these keybindings:
   - Tree Navigation section:
     * Arrow keys / hjkl - Move selection
     * J/K - Jump to next/prev plan
     * x - Hide/show plan group
     * X - Toggle merged PRs
     * f - Cycle status filter
     * F - Cycle sort field
   - PR Actions section:
     * s - Start selected PR
     * d - Review (zz d: loop, zzz d: strict)
     * g - Merge PR
     * e / Enter - Edit selected PR
     * v - View plan file
     * M - Move to plan
     * A - Auto-start to selected PR / off
     * wf - Focus watcher window
     * ww - List watchers & status
     * ws - Start/stop watcher
   - Panes & Views section:
     * c - Launch Claude session
     * H - Launch guide (setup or assist)
     * / - Open command bar
     * n - Open notes
     * m - Meta: work on pm itself
     * L - View TUI log
     * p - Toggle plans view
     * t - Start QA on selected PR
     * q - Toggle QA instructions
     * b - Rebalance panes
   - Companion Pane section:
     * S - Start PR with companion pane
     * G - Merge with companion pane
   - Other section:
     * z - Modifier: kill existing before next
     * r - Refresh / sync with GitHub
     * C - Show shared connect command
     * Ctrl+R - Restart TUI
     * ? - Show this help
     * ctrl+b d - Detach from session
   - Review Loop section:
     * zz d - Start loop
     * zzz d - Start strict loop
     * z d - Stop loop / fresh done

3. Verify footer says: "Press Esc/? to close  |  h to discuss pm"

4. Close help screen:
   - `pm tui send Escape`
   - `pm tui view` to verify help is dismissed

### Part 2: Safe Keybinding Tests

Test each key that is safe to press (won't change PR state):

1. **Navigation keys** (test with frames):
   - `pm tui send Down` -> selection should move down
   - `pm tui view` -> verify selection changed
   - `pm tui send Up` -> selection should move back
   - `pm tui send Right` -> move to next column (if deps exist)
   - `pm tui send Left` -> move back
   - `pm tui send j` -> same as Down
   - `pm tui send k` -> same as Up
   - `pm tui send l` -> same as Right
   - `pm tui send h` -> same as Left

2. **Enter** (show detail panel):
   - `pm tui send Enter`
   - `pm tui view` -> detail panel should appear on right side
   - Verify it shows PR info (ID, title, status, plan context)

3. **v** (view plan):
   - `pm tui send v`
   - Wait 1 second
   - Check if a new pane opened with the plan file
   - `tmux list-panes` to verify pane count increased
   - Check pane registry for role "plan"

4. **/** (command bar):
   - `pm tui send /`
   - `pm tui view` -> command bar should be focused
   - `pm tui send Escape` -> should unfocus command bar

5. **q** (toggle QA):
   - `pm tui send q`
   - `pm tui view` -> should show QA instructions pane (does NOT quit)
   - `pm tui send q` -> pressing again should toggle back to tree view
   - `pm tui view` -> verify back to normal tree view

6. **t** (start QA on selected PR):
   - Select a PR first, then `pm tui send t`
   - Should start QA on the selected PR
   - Note: this launches QA processing, so use carefully

7. **H** (launch guide):
   - `pm tui send H`
   - Wait 1 second
   - `pm tui view` -> should launch guide pane
   - If guide pane launched, verify via `tmux list-panes`

8. **n** (notes):
   - `pm tui send n`
   - Wait 1 second
   - `tmux list-panes` -> should see a new notes pane
   - Check registry for role "notes"

9. **L** (view log):
   - `pm tui send L`
   - Wait 1 second
   - `tmux list-panes` -> should see a new log pane
   - Check registry for role "log"

10. **r** (refresh):
    - `pm tui send r`
    - `pm tui view` -> log line should show "Refreshing..." or sync result

11. **b** (rebalance):
    - `pm tui send b`
    - `pm tui view` -> log line should show "Layout rebalanced"

12. **?** (help - test open/close cycle):
    - `pm tui send ?`
    - `pm tui view` -> help screen should appear
    - `pm tui send ?` -> pressing again should close it
    - `pm tui view` -> verify back to normal view

13. **e** (edit PR):
    - `pm tui send e`
    - Wait 1 second
    - `tmux list-panes` -> should see editor pane
    - Note: editor may open and close quickly if EDITOR is not set

14. **p** (toggle plans view):
    - `pm tui send p`
    - `pm tui view` -> should show plans view
    - `pm tui send p` -> toggle back to tree view

### Part 3: QA View Help

1. Toggle into QA view: `pm tui send q`
2. Open help: `pm tui send ?`
3. Verify QA Navigation section shows:
   - jk / arrows - Move selection
   - Enter - Run selected item
   - e - Edit item
   - a - Add instruction
   - q - Back to tree view
4. Close help: `pm tui send Escape`
5. Toggle back: `pm tui send q`

### Part 4: Destructive Keys (observe only)

Do NOT press these, just verify they exist in help:
- **s** - Would start a PR (changes project state)
- **d** - Would mark PR as done (changes project state)
- **g** - Would merge PR (changes project state)
- **c** - Would launch Claude (resource-intensive)
- **m** - Would launch meta session
- **Ctrl+R** - Would restart TUI (disrupts test)

### Part 5: Cleanup

1. Kill any panes that were created during testing (notes, log, plan, etc.)
   - Use pane registry to find pane IDs
   - `tmux kill-pane -t <pane_id>` for each
2. Verify TUI is still responsive: `pm tui view`
3. Final pane count should match initial count

## Expected Behavior

- Help screen should be a modal overlay that lists ALL keybindings
- Each key should produce a visible effect (log message, pane, or state change)
- Keys should not error or crash when pressed with no PR selected
- Help screen should open/close cleanly with '?' or Escape (q does NOT close help)
- Pressing q in the main TUI toggles QA instructions (does not quit)
- Help screen in QA view shows QA-specific navigation

## Reporting

```
HELP SCREEN & KEYBINDINGS TEST
===============================

## Part 1: Help Screen Content
Help screen opens: [PASS/FAIL]
All keybindings documented: [PASS/FAIL]
  Missing keys (if any): <list>
  Extra/unexpected keys (if any): <list>
Footer correct (Esc/? to close): [PASS/FAIL]
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
  q (toggle QA): [PASS/FAIL] - <toggles QA view on/off?>
  t (start QA): [PASS/FAIL] - <starts QA on selected PR?>
  H (guide): [PASS/FAIL] - <behavior observed>
  / (command bar): [PASS/FAIL] - <focuses/unfocuses correctly?>
  n (notes): [PASS/FAIL] - <pane created? role correct?>
  L (log): [PASS/FAIL] - <pane created? role correct?>
  p (plans): [PASS/FAIL] - <toggles plans view?>
  r (refresh): [PASS/FAIL] - <log message>
  b (rebalance): [PASS/FAIL] - <log message>

Other:
  ? (help toggle): [PASS/FAIL] - <opens and closes cleanly?>

## Part 3: QA View Help
QA navigation shown: [PASS/FAIL]
  j/k movement: [PRESENT/MISSING]
  Enter run: [PRESENT/MISSING]
  e edit: [PRESENT/MISSING]
  a add: [PRESENT/MISSING]
  q back: [PRESENT/MISSING]

## Part 4: Destructive Keys
All documented in help: [PASS/FAIL]
  s (start PR): [PRESENT/MISSING]
  z (kill existing modifier): [PRESENT/MISSING]
  d (done PR): [PRESENT/MISSING]
  g (merge PR): [PRESENT/MISSING]
  c (claude): [PRESENT/MISSING]
  m (meta): [PRESENT/MISSING]
  Ctrl+R (restart): [PRESENT/MISSING]

## Part 5: Cleanup
Panes cleaned up: [PASS/FAIL]
TUI responsive after tests: [PASS/FAIL]

## Issues Found
<list any keybindings that don't work, produce errors, or behave unexpectedly>

## Frame Analysis
Total frames captured: <N>
Key state changes observed: <summary>

OVERALL: [PASS/FAIL]
```
