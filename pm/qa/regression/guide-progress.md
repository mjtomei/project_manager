---
title: Guide Progress Widget
description: Test that guide progress widget displays correct step indicators
tags: [tui, local, vanilla, github, containerized, uncontainerized]
---
You are testing the GuideProgress widget in the pm TUI. Your goal is to verify
that the widget correctly displays step progress indicators as the user moves
through the guide workflow.

## Background

The TUI displays a GuideProgress widget during the setup steps (no_project through
ready_to_work). This widget shows:
- A list of numbered steps with descriptions
- Markers indicating status: checkmark for completed, arrow for current, circle for future
- The current step highlighted

The frame capture system automatically records TUI state on every change, so you
can verify the widget updated correctly by examining captured frames.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (g=guide, n=notes, r=refresh, x=dismiss)
- `pm tui frames` - View recently captured frames (shows last 5)
- `pm tui frames --all` - View all captured frames
- `pm tui frames -n 10` - View last 10 frames
- `pm tui clear-frames` - Clear captured frames (useful to start fresh)
- `pm tui capture --frame-rate 1` - Ensure all changes are captured

## Test Procedure

1. SETUP: Clear frames to start fresh
   - Run `pm tui clear-frames`
   - Run `pm tui view` to see initial state
   - Verify you see the GuideProgress widget (should show "Guide Workflow" header)

2. VERIFY INITIAL STATE:
   - The current step should have a right-pointing arrow marker (unicode U+25B6)
   - Previous steps should have checkmarks (U+2713)
   - Future steps should have empty circles (U+25CB)
   - Check `pm tui frames` to see the captured initial frame

3. TEST STEP TRANSITION (if possible):
   - If the guide is on step 1 (no_project), you can complete it by ensuring
     a pm directory with project.yaml exists
   - Press 'r' to refresh the TUI
   - Check frames to see if the widget updated:
     * Previous step should now show checkmark
     * New current step should show arrow
   - Run `pm tui frames -n 3` to compare before/after states

4. TEST DISMISS AND RESTORE:
   - Press 'x' to dismiss the guide view
   - Verify TUI switches to tech tree view
   - Press 'g' to launch guide pane
   - Verify guide progress widget is still visible (or explain if behavior differs)

5. VERIFY FRAME CAPTURE TRIGGERS:
   - Each state change should have triggered a frame capture
   - Run `pm tui frames --all` and check the "trigger" field in each frame
   - Expected triggers: "mount", "show_guide_view:*", "guide_step:*", etc.

## Expected Behavior

From pm_core/tui/guide_progress.py:
- INTERACTIVE_STEPS excludes terminal states (all_in_progress, all_done)
- MARKER_COMPLETED = checkmark, MARKER_CURRENT = arrow, MARKER_FUTURE = circle
- Widget updates via update_step() method which triggers refresh()

From pm_core/tui/app.py:
- GuideProgress widget is in #guide-progress-container
- Shown when no PRs exist (setup state)
- Frame capture triggers on guide step changes via watcher

## Reporting

After running your tests, report your findings in this format:

```
TEST RESULTS
============
Initial display: [PASS/FAIL] - Widget shows correct markers
Step transition: [PASS/FAIL] - Markers update on step change (or N/A if couldn't test)
Dismiss/restore: [PASS/FAIL] - View switching works correctly
Frame capture: [PASS/FAIL] - Changes are captured with correct triggers

Details:
<observations about widget behavior, any issues found>

Frame Analysis:
<summary of captured frames and what they show>

OVERALL: [PASS/FAIL]
```
