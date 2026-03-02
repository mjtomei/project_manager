---
title: TUI Restart Pane Deduplication
description: Test that restarting TUI doesn't create duplicate panes
---
You are testing that restarting the TUI does not create duplicate panes. Your goal
is to verify that when the TUI restarts (e.g., via 'R' key or crash recovery), it
reuses existing panes rather than launching new ones.

## Background

The TUI auto-launches certain panes (like guide) when conditions are met. There's a
bug where restarting the TUI while guide is running causes a SECOND guide pane to
be created, leaving the user with duplicate panes.

The fix should:
- Check if a pane for the task already exists before launching
- If it exists, switch focus to it instead of creating a new one
- Use the same task identification as session resume (pane registry role field)

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes (R=restart, g=guide, n=notes, x=dismiss)
- `pm tui frames` - View captured frames (automatically recorded on UI changes)
- `pm tui frames --all` - View all captured frames
- `pm tui clear-frames` - Clear frame buffer to start fresh
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_title}"` - List panes
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `tmux display-message -p "#{session_name}"` - Get current session name

## Test Procedure

### Scenario A: Restart TUI while guide is running

1. SETUP:
   - Run `pm tui clear-frames` to start with empty frame buffer
   - Run `pm tui view` to verify TUI is running
   - Get session name: `tmux display-message -p "#{session_name}"`
   - Check pane registry: `cat ~/.pm/pane-registry/<session>.json`
   - Count panes with role "guide" - should be 0 or 1
   - List all panes: `tmux list-panes -t <session> -F "#{pane_id}"`
   - Record initial pane count

2. LAUNCH GUIDE (if not running):
   - Press 'g' to launch guide pane
   - Wait 2 seconds for guide to start
   - Check registry again - should have exactly 1 guide pane
   - Record pane count (should be initial + 1 if guide wasn't running)

3. RESTART TUI:
   - Press 'R' to restart the TUI
   - Wait 2 seconds for TUI to restart
   - Check registry - should still have exactly 1 guide pane (NOT 2)
   - Count panes - should be same as before restart
   - If there are 2 guide panes, the test FAILS

4. VERIFY:
   - Run `pm tui view` - TUI should be responsive
   - The original guide pane should still be there
   - No duplicate guide panes should exist
   - Run `pm tui frames --all` to see state transitions during restart
   - Frame triggers should show "mount" after restart, content should be consistent

### Scenario B: Restart TUI after guide is done

1. SETUP (skip if guide is already done):
   - This scenario tests behavior when guide workflow is complete
   - If you can't complete the guide, note this as N/A

2. RESTART TUI:
   - Press 'R' to restart
   - Wait 2 seconds
   - Run `pm tui view`

3. VERIFY:
   - TUI should show normal tech tree view (not guide progress)
   - No new guide pane should be auto-launched
   - Check registry for guide panes - should be 0

### Scenario C: Manual guide launch deduplication

1. With guide already running (from Scenario A):
   - Press 'g' to try launching guide again
   - This should NOT create a second guide pane
   - Instead, it should focus the existing guide pane (or do nothing)

2. VERIFY:
   - Check registry - still exactly 1 guide pane
   - Pane count unchanged

## Expected Behavior

The TUI should:
1. Before launching a pane, check if one with that role already exists in registry
2. If it exists and the pane is still alive, focus it instead of creating new
3. Only create a new pane if none exists or the existing one is dead

## Reporting

```
TEST RESULTS
============
Scenario A (restart with guide): [PASS/FAIL] - <pane count before/after>
Scenario B (restart after done): [PASS/FAIL or N/A] - <description>
Scenario C (manual dedup): [PASS/FAIL] - <guide pane count>

Details:
<observations, pane counts, any duplicate panes found>

Registry states:
<before restart>
<after restart>

OVERALL: [PASS/FAIL]
```
