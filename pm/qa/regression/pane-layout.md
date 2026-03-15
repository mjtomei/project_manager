---
title: Pane Layout Refresh
description: Test that pane kill/relaunch properly refreshes layout
tags: [tui, local, vanilla, github, containerized, uncontainerized]
---
You are testing the pm TUI pane layout refresh behavior. Your goal is to verify
that when panes are killed and relaunched, the layout is properly refreshed.

## Background

The pm TUI manages a tmux session with multiple panes (TUI, notes, guide, etc.).
When a pane is killed and relaunched, the layout should automatically rebalance.
There have been bugs where:
- Killing a pane leaves a gap or unbalanced layout
- Relaunching a pane from the TUI doesn't trigger rebalance
- The pane registry gets out of sync with actual tmux panes

## Available Tools

You have access to these commands:
- `pm tui view` - See current TUI state (also adds to legacy history)
- `pm tui send <keys>` - Send keystrokes to TUI (g=guide, n=notes, r=refresh, x=dismiss)
- `pm tui frames` - View automatically captured frames (captured on every UI change)
- `pm tui frames --all` - View all captured frames
- `pm tui capture --frame-rate N --buffer-size N` - Configure capture settings
- `pm tui clear-frames` - Clear captured frames
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"` - List panes with sizes
- `tmux kill-pane -t <pane_id>` - Kill a specific pane
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry

## Test Procedure

1. First, record the original state:
   - Run `pm tui clear-frames` to start with empty frame buffer
   - Run `pm tui view` to see the TUI
   - Run `tmux list-panes` to see all panes and their sizes
   - Check the pane registry - note the pane order (by "order" field)
   - SAVE THIS STATE - you must restore it at the end

2. Example scenarios, test as many as you think are useful:

   a) Kill guide pane via tmux, relaunch via TUI 'g' key:
      - Note current pane IDs and sizes
      - Find the guide pane ID from registry
      - Kill it with `tmux kill-pane -t <id>`
      - Wait 1 second, check layout
      - Press 'g' in TUI to relaunch guide
      - Verify layout rebalances (panes should have similar sizes)

   b) Kill notes pane, relaunch via TUI 'n' key:
      - Similar to above but for notes pane

   c) Kill a pane and check registry cleanup:
      - Kill a pane
      - Verify registry no longer contains that pane ID
      - Verify TUI still works (press 'r' to refresh)

3. For each scenario, verify:
   - Pane registry matches actual tmux panes
   - Layout is reasonably balanced (no tiny or huge panes)
   - TUI remains responsive
   - Check `pm tui frames` to see captured state changes during the test

4. RESTORE ORIGINAL STATE:
   - Kill and relaunch panes in the correct order to restore original pane order
   - For example, if you tested guide then notes, you need to:
     * Kill the notes pane you created
     * Kill the guide pane you created
     * Relaunch notes first (press 'n')
     * Relaunch guide second (press 'g')
   - This ensures the registry order matches the original
   - Verify final state matches original state

## Expected Behavior

From pm_core/pane_layout.py, the expected behavior is:
- When a pane exits, the EXIT trap calls `pm _pane-exited` which unregisters the pane
- The `rebalance()` function should be called to redistribute space
- The TUI's `_launch_pane()` method registers new panes and calls rebalance

## Reporting

After running your tests, report your findings in this format:

```
TEST RESULTS
============
Scenario A: [PASS/FAIL] - <brief description>
Scenario B: [PASS/FAIL] - <brief description>

Details:
<any issues found or notable observations>

OVERALL: [PASS/FAIL]
```

Use PASS if behavior matches expected, FAIL if there are bugs or unexpected behavior.
