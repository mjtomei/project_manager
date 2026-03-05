---
title: Window Resize Rebalance
description: Test that layout auto-rebalances on window resize (portrait vs landscape)
---
You are testing that pane layout automatically rebalances when the terminal
window is resized -- the core behavior of the window-size=smallest grouped-session
fix (PR-023). The test manually resizes the tmux window to simulate portrait
and landscape aspect ratios, verifies the layout changes accordingly, and
restores the original size at the end.

## Background

When multiple terminals connect to the same pm session via grouped tmux
sessions (e.g. a landscape monitor and a portrait monitor), each terminal may
have different dimensions. With `window-size=smallest`, the tmux window follows
the smallest connected client's size. A global `window-resized` hook
triggers `pm _window-resized` which calls `rebalance()`, recomputing the
layout based on the new dimensions.

Key implementation details:
- `window-size=smallest` is set on all sessions in the group
- Global `window-resized` hook fires `run-shell 'pm _window-resized'`
- `rebalance()` uses `w >= h * 2` to account for character aspect ratio (~2:1 h:w)
- `is_mobile()` triggers for terminals narrower than 120 columns
- Layout uses a recursive binary split: `{ }` for horizontal, `[ ]` for vertical

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"` - Pane geometries
- `tmux display -t <session> -p "#{window_width} #{window_height}"` - Window size
- `tmux resize-window -t <session> -x <width> -y <height>` - Resize window manually
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `tmux display-message -p "#{session_name}"` - Get session name
- `tmux show-options -t <session> window-size` - Check window-size setting

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Get base session name (strip ~N suffix)
4. Record initial state -- SAVE ALL OF THESE for restoration:
   - Window size: `tmux display -t <session> -p "#{window_width} #{window_height}"`
   - Pane geometries: `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - Pane registry: `cat ~/.pm/pane-registry/<base>.json`
   - Window-size option: `tmux show-options -t <session> window-size`
5. The session should have at least 2 panes for this test to be meaningful.
   If it doesn't, press 'n' to open notes pane.

### Part 1: Verify window-size=smallest

1. Check the window-size setting:
   - `tmux show-options -t <base> window-size` - should show "smallest"
   - If grouped sessions exist, check one: `tmux show-options -t <base>~1 window-size`
   - Both should show "smallest"

2. Check the global window-resized hook:
   - `tmux show-hooks -g` - should include `window-resized[0] run-shell "pm _window-resized ..."`

### Part 2: Landscape Layout (wide terminal)

1. Resize window to a clear landscape aspect ratio:
   - `tmux resize-window -t <session> -x 200 -y 50`
   - Wait 1-2 seconds for the hook to fire and rebalance to complete

2. Verify layout is horizontal (side-by-side):
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - Panes should be arranged LEFT-RIGHT (different pane_left values, same pane_top = 0)
   - Each pane should be roughly half the window width (accounting for separator)

3. Verify pane registry is NOT marked user_modified:
   - `cat ~/.pm/pane-registry/<base>.json` - check "user_modified" is false

### Part 3: Portrait Layout (tall terminal)

1. Resize window to a clear portrait aspect ratio:
   - `tmux resize-window -t <session> -x 80 -y 120`
   - Wait 1-2 seconds for the hook to fire

2. Verify layout is vertical (stacked):
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - Panes should be arranged TOP-BOTTOM (different pane_top values, same pane_left = 0)
   - Each pane should be roughly half the window height

3. This is the core bug this PR fixes -- a portrait terminal should get a
   vertical split, not be stuck with the landscape layout.

### Part 4: Client-Driven Resize (simulates moving to a different monitor)

This is the critical test. Parts 2-3 use `tmux resize-window` which is an
explicit command and fires `after-resize-window`. But when a user moves
their terminal to a different monitor, the resize comes from the client
(SIGWINCH), which only fires the `window-resized` hook. We must test this
path separately using `tmux refresh-client -C WxH`.

1. First, set the window back to a known landscape state:
   - `tmux resize-window -t <session> -x 200 -y 50`
   - Wait 1-2 seconds, verify panes are side-by-side

2. Now simulate moving to a portrait monitor via client resize:
   - `tmux refresh-client -C 80,120`
   - Wait 1-2 seconds for the `window-resized` hook to fire

3. Verify the layout auto-rebalanced to vertical (stacked):
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - Panes should be arranged TOP-BOTTOM (different pane_top values)
   - If panes are still side-by-side, the hook is NOT firing for client
     resizes -- this is the bug that `window-resized` (not `after-resize-window`)
     was needed to fix

4. Simulate moving back to landscape monitor:
   - `tmux refresh-client -C 200,50`
   - Wait 1-2 seconds
   - Verify panes switched back to side-by-side

5. Reset client size to auto:
   - `tmux refresh-client -C ""`  (or omit -C to reset)
   - This clears the manual client size override

### Part 5: Mobile Mode Trigger on Narrow Resize

1. Resize window to narrow (mobile) width:
   - `tmux resize-window -t <session> -x 80 -y 24`
   - Wait 1-2 seconds

2. Check if mobile mode auto-detected:
   - `pm session mobile` - should show "Mobile active: True" (80 < 120 threshold)
   - Active pane should be zoomed: `tmux display -t <session> -p "#{window_zoomed_flag}"` -> "1"

3. Resize back to desktop width:
   - `tmux resize-window -t <session> -x 200 -y 50`
   - Wait 1-2 seconds
   - `pm session mobile` - should show "Mobile active: False" (200 >= 120)
   - Zoom should be off (if no force flag): `tmux display -t <session> -p "#{window_zoomed_flag}"` -> "0"

### Part 6: Manual Rebalance After Resize

1. Resize to an unusual aspect ratio:
   - `tmux resize-window -t <session> -x 160 -y 80`
   - Wait 1-2 seconds
   - Verify panes redistributed:
     `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - With 160x80 (landscape), panes should be side-by-side

2. Run manual rebalance and verify it works:
   - `pm rebalance`
   - Check panes again -- layout should be consistent

### Part 7: TUI Responsiveness After Resize

1. Verify TUI is still responsive:
   - `pm tui view` - should render without errors
   - `pm tui send r` (refresh) - should work
   - `pm tui frames` - check recent frames show no errors

### Part 8: Restore Original Size

IMPORTANT: Always restore the window to its original size!

1. Resize back to the original dimensions recorded in Setup:
   - `tmux resize-window -t <session> -x <original_width> -y <original_height>`
   - Wait 1-2 seconds for rebalance

2. Clear the manual window-size override that `tmux resize-window -x -y` sets:
   - `tmux set-window-option -u -t <session> window-size`
   - Without this, the window stays in "manual" sizing mode and will NOT
     auto-resize to follow the attached client, even after `resize-window -A`.
   - Verify it's cleared: `tmux show-window-options -t <session>` should NOT
     show `window-size manual`.

3. Optionally, also run `tmux resize-window -t <session> -A` to snap the
   window size back to the largest attached client immediately.

4. Verify restoration:
   - Pane geometries should match the original state (or be close)
   - TUI should be responsive: `pm tui view`
   - Registry should still have user_modified=false

## Expected Behavior

- Landscape (physically wider): horizontal split `{left,right}` -- panes side-by-side
- Portrait (physically taller): vertical split `[top,bottom]` -- panes stacked
- The split compares `w >= h * 2` to account for character aspect ratio (~2:1 h:w)
- Narrow (< 120 cols): mobile mode triggers, active pane zooms
- `rebalance()` is called automatically after resize via tmux hook
- Multiple panes: recursive binary split alternates horizontal/vertical
- Layout computation from `pane_layout.py`:
  - `_layout_node` chooses `{` for w >= h*2 (horizontal), `[` otherwise (vertical)
  - 2 panes: single split in appropriate direction
  - 3+ panes: recursive split with alternating axis

## Reporting

```
WINDOW RESIZE REBALANCE TEST RESULTS
=====================================

## Part 1: window-size=smallest
Base session has smallest: [PASS/FAIL]
Grouped session has smallest: [PASS/FAIL]
Global hook exists: [PASS/FAIL]

## Part 2: Landscape Layout (200x50) -- via resize-window
Panes are side-by-side: [PASS/FAIL]
  Pane positions: <list pane_left values>
user_modified still false: [PASS/FAIL]

## Part 3: Portrait Layout (80x120) -- via resize-window
Panes are stacked vertically: [PASS/FAIL]
  Pane positions: <list pane_top values>

## Part 4: Client-Driven Resize -- via refresh-client -C (KEY TEST)
Portrait via refresh-client auto-rebalanced: [PASS/FAIL]
  Pane positions after refresh-client -C 80,120: <list pane_top values>
Landscape via refresh-client auto-rebalanced: [PASS/FAIL]
  Pane positions after refresh-client -C 200,50: <list pane_left values>
THIS TESTS THE REAL SCENARIO (moving terminal between monitors).
If this fails but Parts 2-3 pass, the hook name is wrong.

## Part 5: Mobile Mode on Narrow
Mobile detected at 80 cols: [PASS/FAIL]
Active pane zoomed: [PASS/FAIL]
Desktop mode restored at 200 cols: [PASS/FAIL]
Zoom off after widen: [PASS/FAIL]

## Part 6: Manual Rebalance
pm rebalance works after resize: [PASS/FAIL]

## Part 7: TUI Responsiveness
pm tui view works: [PASS/FAIL]
Refresh works: [PASS/FAIL]

## Part 8: Restore
Manual window-size cleared: [PASS/FAIL]
  `tmux set-window-option -u` removed "window-size manual"
Original size restored: [PASS/FAIL]
  Method: resize-window -A / explicit dimensions
Final state matches original: [PASS/FAIL]

## Issues Found
<list any bugs, unexpected behavior, or timing issues>

## Notes
Original window size: <W>x<H>
Number of panes: <N>
Auto-rebalance fired: [Yes/No/Unknown]
Hook timing: <observed delay between resize and layout change>

OVERALL: [PASS/FAIL]
```
