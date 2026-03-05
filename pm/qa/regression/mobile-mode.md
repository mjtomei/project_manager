---
title: Mobile Mode
description: Test mobile mode auto-zoom, force flag, pane switching, and status command
---
You are testing the mobile mode feature for the pm TUI. Mobile mode auto-zooms
the active pane when the terminal is narrow (< 120 columns) or when force-enabled,
making the tool usable on mobile devices and narrow SSH sessions.

## Background

The pm tool manages tmux sessions with multiple side-by-side panes. On small
terminals these panes become unusable. Mobile mode solves this by:
- Auto-detecting narrow terminals (< 120 cols)
- Supporting a force-mobile flag (`pm session mobile --force`)
- Auto-zooming the active pane on every pane switch
- Zooming the TUI on session start when mobile

Key implementation details:
- `pm _pane-switch <session> <direction>` — internal command that unzooms,
  switches pane, then re-zooms if mobile
- `pm session mobile` — show/toggle mobile mode status
- tmux prefix keys (o, Up, Down, Left, Right) are overridden to use `_pane-switch`
- Force flag stored at `~/.pm/pane-registry/<session>.mobile`
- TUI's `_launch_pane` uses `select_pane_smart` which zooms in mobile mode

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"` - List panes
- `tmux display -t <session> -p "#{window_width} #{window_zoomed_flag}"` - Window info
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `ls ~/.pm/pane-registry/<session>.mobile` - Check force-mobile flag
- `tmux display-message -p "#{session_name}"` - Get session name

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Record initial state:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"` - pane sizes
   - `tmux display -t <session> -p "#{window_width} #{window_zoomed_flag}"` - width and zoom
   - `ls ~/.pm/pane-registry/<session>.mobile 2>&1` - force flag status
4. Run `pm session mobile` to see current mobile status

### Part 1: Mobile Status Command

1. Run `pm session mobile` and verify output shows:
   - Session name
   - Mobile active: True/False
   - Force flag: True/False
   - Window width and threshold (120)

### Part 2: Force Mobile On

1. Enable force mobile:
   - `pm session mobile --force`
   - Verify output says "force-enabled"
   - `ls ~/.pm/pane-registry/<session>.mobile` - file should exist

2. Verify mobile status:
   - `pm session mobile` - should show "Mobile active: True", "Force flag: True"

3. Check zoom state on ALL windows:
   - List all windows: `tmux list-windows -t <session> -F "#{window_index} #{window_name}"`
   - For EACH window that has multiple panes, verify it is zoomed:
     `tmux display -t <session>:<window_index> -p "#{window_zoomed_flag}"` - should be "1"
   - Windows with only one pane can't be zoomed (that's expected)
   - The active pane in each multi-pane window should be the zoomed one

### Part 3: Pane Switching in Mobile Mode

1. Test prefix-o (next pane) via _pane-switch:
   - Record current active pane: `tmux display -t <session> -p "#{pane_id}"`
   - Run `pm _pane-switch <session> next`
   - Check active pane changed: `tmux display -t <session> -p "#{pane_id}"`
   - Check still zoomed: `tmux display -t <session> -p "#{window_zoomed_flag}"` → "1"

2. Test directional switching:
   - First unzoom to see all panes: `tmux resize-pane -t <session> -Z`
   - Record pane positions: `tmux list-panes -t <session> -F "#{pane_id} #{pane_left} #{pane_top}"`
   - Re-zoom: `tmux resize-pane -t <session> -Z`
   - Run `pm _pane-switch <session> -R` (move right)
   - Verify zoom is still on: `tmux display -t <session> -p "#{window_zoomed_flag}"` → "1"
   - Run `pm _pane-switch <session> -L` (move left)
   - Verify zoom is still on

3. Cycle through all panes:
   - Run `pm _pane-switch <session> next` several times
   - After each, verify zoom flag is "1"
   - After cycling back to start, verify we're on the original pane

### Part 4: TUI Pane Launch in Mobile Mode

1. With force-mobile still on:
   - `pm tui send n` to launch/focus notes pane
   - Wait 1 second
   - Check zoom: `tmux display -t <session> -p "#{window_zoomed_flag}"` → "1"
   - The notes pane should be zoomed (fully visible)

2. Focus back to TUI:
   - `pm _pane-switch <session> next` (or use direction to find TUI)
   - Check zoom still on
   - `pm tui view` - TUI should be visible and responsive

### Part 5: Rebalance in Mobile Mode

1. Run `pm tui send b` to trigger rebalance from TUI
   - Or run `pm rebalance` directly
   - After rebalance, active pane should still be zoomed
   - `tmux display -t <session> -p "#{window_zoomed_flag}"` → "1"

### Part 6: Force Mobile Off

1. Disable force mobile:
   - `pm session mobile --no-force`
   - Verify output says "force-disabled"
   - `ls ~/.pm/pane-registry/<session>.mobile 2>&1` - file should NOT exist

2. Check status:
   - `pm session mobile` - Force flag should be False
   - Mobile active depends on actual window width

3. Verify ALL windows are unzoomed:
   - List all windows: `tmux list-windows -t <session> -F "#{window_index} #{window_name}"`
   - For EACH window, verify it is NOT zoomed:
     `tmux display -t <session>:<window_index> -p "#{window_zoomed_flag}"` - should be "0"
   - All panes in multi-pane windows should be visible side-by-side

4. If window is narrow (< 120):
   - Mobile active should still be True (auto-detected)
   - Zoom behavior continues

### Part 7: Cleanup Verification

1. Verify that `pm session kill` would clean up the flag:
   - DON'T actually kill the session
   - Just verify the code path exists by checking:
     `ls ~/.pm/pane-registry/<session>.mobile 2>&1` - should not exist (we disabled it)

2. Restore original state:
   - If mobile was off at the start and is now off, nothing to do
   - Run `pm rebalance` to ensure clean layout
   - Verify all panes are visible: `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"`

## Expected Behavior

- `pm session mobile` shows status without changing anything
- `pm session mobile --force` enables force-mobile, triggers rebalance, zooms active pane on ALL windows
- `pm session mobile --no-force` disables force-mobile, unzooms ALL windows, triggers rebalance
- `pm _pane-switch` unzooms → switches pane → re-zooms (in mobile mode)
- `pm _pane-switch` just switches pane (in desktop mode, no zoom)
- TUI `_launch_pane` auto-zooms new/existing panes via `select_pane_smart`
- `rebalance()` zooms active pane after layout when mobile
- Force flag is at `~/.pm/pane-registry/<session>.mobile`
- Threshold is 120 columns

## Reporting

```
MOBILE MODE TEST RESULTS
========================

## Part 1: Status Command
pm session mobile output correct: [PASS/FAIL]
  Shows session name: [Yes/No]
  Shows mobile active: [Yes/No]
  Shows force flag: [Yes/No]
  Shows width and threshold: [Yes/No]

## Part 2: Force Mobile On
--force enables flag file: [PASS/FAIL]
Status shows force-enabled: [PASS/FAIL]
All multi-pane windows zoomed: [PASS/FAIL]

## Part 3: Pane Switching
_pane-switch next: [PASS/FAIL] - <pane changed? still zoomed?>
_pane-switch -R: [PASS/FAIL] - <still zoomed?>
_pane-switch -L: [PASS/FAIL] - <still zoomed?>
Full cycle returns to start: [PASS/FAIL]

## Part 4: TUI Pane Launch
Notes pane auto-zoomed: [PASS/FAIL]
Switch back to TUI works: [PASS/FAIL]

## Part 5: Rebalance
Rebalance preserves zoom: [PASS/FAIL]

## Part 6: Force Mobile Off
--no-force removes flag: [PASS/FAIL]
Status shows force-disabled: [PASS/FAIL]
All windows unzoomed: [PASS/FAIL]

## Part 7: Cleanup
Original state restored: [PASS/FAIL]

## Issues Found
<list any bugs, unexpected behavior>

## Notes
Window width during test: <N> columns
Threshold: 120 columns
Auto-mobile triggered: [Yes/No]

OVERALL: [PASS/FAIL]
```
