---
title: Pane Launch Deduplication
description: Test that pane launch keys (g, n) don't create duplicates
---
You are testing that the TUI pane launch commands don't create duplicate panes.
Your goal is to verify that pressing 'g' (guide), 'n' (notes), or other pane
launch keys when that pane is already open focuses the existing pane instead
of creating a new one.

## Background

The TUI has several keybindings that launch panes:
- 'g' - Launch guide pane
- 'n' - Launch notes pane

Previously, pressing these keys when the pane was already open would create
duplicate panes. The fix should detect existing panes and focus them instead.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames (automatically recorded on UI changes)
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer to start fresh
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `tmux display-message -p "#{session_name}"` - Get session name

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Record initial state:
   - `tmux list-panes -t <session> -F "#{pane_id}"` - count panes
   - `cat ~/.pm/pane-registry/<session>.json` - note registered panes

### Scenario A: Guide pane deduplication

1. If guide pane is NOT running:
   - Press 'g' to launch guide
   - Wait 2 seconds
   - Count panes - should be initial + 1
   - Check registry - should have 1 guide pane

2. With guide pane running:
   - Press 'g' again
   - Wait 1 second
   - Count panes - should be SAME as before (no new pane)
   - Check registry - should still have exactly 1 guide pane
   - The TUI log should say "Focused existing guide pane"

3. Press 'g' a third time:
   - Same verification - no new panes created

### Scenario B: Notes pane deduplication

1. If notes pane is NOT running:
   - Press 'n' to launch notes
   - Wait 1 second
   - Count panes and check registry

2. With notes pane running:
   - Press 'n' again
   - Wait 1 second
   - Count panes - should be SAME (no new pane)
   - Check registry - should still have exactly 1 notes pane

3. Press 'n' a third time:
   - Same verification

### Scenario C: Multiple rapid presses

1. With both guide and notes running, record pane count
2. Rapidly send multiple commands:
   - `pm tui send g`
   - `pm tui send n`
   - `pm tui send g`
   - `pm tui send n`
3. Wait 2 seconds
4. Count panes - should be SAME as before
5. Check registry - should still have exactly 1 of each role

### Scenario D: Focus switching

1. With guide and notes both running:
   - Note which pane is currently focused (use `tmux display-message -p "#{pane_id}"`)
   - Press 'g' - should focus guide pane
   - Check focused pane changed to guide
   - Press 'n' - should focus notes pane
   - Check focused pane changed to notes
   - Run `pm tui frames` to verify the TUI logged "Focused existing X pane" messages

### Scenario E: Command bar with status command

The TUI has a command bar (focused with '/') that can run pm commands.
Test that the command bar properly executes commands.

1. First, make sure TUI pane is focused (press Escape to unfocus command bar if needed)
2. Focus command bar: `pm tui send /`
3. Type status command: `pm tui send status`
4. Press Enter: `pm tui send Enter`
5. Wait 1 second
6. Check `pm tui view` - log line should show command output or status info
7. Pane count should be unchanged (status doesn't create panes)

### Scenario F: Command bar with sync command

Test another command bar command:

1. Focus TUI pane
2. `pm tui send /` to focus command bar
3. `pm tui send sync` to type sync command
4. `pm tui send Enter` to execute
5. Wait 2 seconds
6. Check `pm tui view` - should see sync result in log line
7. Pane count should be unchanged

### Scenario G: Command bar escape to cancel

Test that Escape cancels command input:

1. Focus command bar: `pm tui send /`
2. Type partial command: `pm tui send stat`
3. Press Escape: `pm tui send Escape`
4. Command bar should unfocus without executing
5. TUI should return to normal state

## Expected Behavior

From pm_core/tui/pane_ops.py launch_pane():
- Calls pane_registry.find_live_pane_by_role() to check for existing pane
- If found, calls tmux_mod.select_pane() to focus it
- Only creates new pane if no existing live pane found
- Logs "Focused existing {role} pane" when reusing

## Reporting

```
TEST RESULTS
============
Scenario A (guide dedup): [PASS/FAIL] - <pane counts: before/after 'g' presses>
Scenario B (notes dedup): [PASS/FAIL] - <pane counts: before/after 'n' presses>
Scenario C (rapid presses): [PASS/FAIL] - <pane count unchanged? Y/N>
Scenario D (focus switching): [PASS/FAIL] - <focus changed correctly? Y/N>
Scenario E (cmd bar status): [PASS/FAIL] - <status output visible? Y/N>
Scenario F (cmd bar sync): [PASS/FAIL] - <sync output visible? Y/N>
Scenario G (cmd bar escape): [PASS/FAIL] - <escape cancels input? Y/N>

Details:
<observations, any duplicate panes created, log messages seen>

Pane counts:
- Initial: <N>
- After guide launch: <N>
- After guide re-press: <N>
- After notes launch: <N>
- After notes re-press: <N>
- After rapid presses: <N>

Command bar tests:
- Command bar focused with '/': Y/N
- Status command output visible: Y/N
- Sync command output visible: Y/N
- Escape cancels without executing: Y/N

Frame analysis:
- Total frames captured: <N>
- Key triggers seen: <list of triggers from pm tui frames --all>
- "Focused existing" messages in log line: Y/N

OVERALL: [PASS/FAIL]
```
