---
title: Plans Pane
description: Test plans view toggle, navigation, actions, and refresh persistence
---
You are testing the Plans Pane feature in the pm TUI. Your goal is to verify
that pressing p toggles a plans view, that navigation works, and that
plan action shortcuts function correctly.

## Background

The TUI has a plans view (toggled with p) that replaces the tech tree
with a scrollable list of plans. Each plan shows its ID, name, status, PR count,
and intro text from the plan markdown file. The plans pane has its own keybindings
for plan operations (view, edit, add, review, deps, load).

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
2. Run `pm tui view` to verify TUI is running and showing the tech tree
3. If in guide mode, press 'g' to dismiss and show the tech tree
4. Get session name: `tmux display-message -p "#{session_name}"`
5. Record initial pane count: `tmux list-panes -t <session> -F "#{pane_id}"`

### Part 1: Toggle Plans View

1. Enter plans view:
   - `pm tui send p`
   - Wait 1 second
   - `pm tui view` - should show plans list instead of tech tree
   - Verify you can see:
     * "Plans" header
     * Plan names (e.g., "Import from existing repo", "Multi-candidate test-driven code generation")
     * Plan status (e.g., "[draft]")
     * PR counts for each plan
     * Intro text from the plan files
     * Shortcut hints at the bottom (view, edit, add, review, deps, load, back)

2. Return to tree view:
   - `pm tui send p`
   - Wait 1 second
   - `pm tui view` - should show tech tree again with PRs
   - Verify plans view is gone

### Part 2: Navigation

1. Enter plans view again:
   - `pm tui send p`
   - Wait 1 second

2. Navigate between plans:
   - `pm tui view` - note which plan is selected (marked with arrow)
   - `pm tui send Down` - selection should move to next plan
   - `pm tui view` - verify selection changed
   - `pm tui send Up` - selection should move back
   - `pm tui view` - verify selection returned
   - Test j/k navigation:
     * `pm tui send j` - same as Down
     * `pm tui send k` - same as Up

3. Boundary testing:
   - Navigate to first plan (press Up/k multiple times)
   - Press Up again - should stay at first plan
   - Navigate to last plan (press Down/j multiple times)
   - Press Down again - should stay at last plan

### Part 3: Plan Actions

1. View plan file (Enter):
   - Select a plan
   - `pm tui send Enter`
   - Wait 1 second
   - `tmux list-panes` - should see a new pane (role "plan")
   - Check pane registry for role "plan"
   - Kill the plan pane after verifying

2. View plan file (v):
   - `pm tui send v`
   - Wait 1 second
   - `tmux list-panes` - should see a new plan pane
   - Kill the plan pane after verifying

3. Edit plan (e):
   - `pm tui send e`
   - Wait 1 second
   - `tmux list-panes` - should see editor pane (role "plan-edit")
   - Kill the editor pane after verifying

4. Add plan (a):
   - `pm tui send a`
   - `pm tui view` - command bar should be focused with "plan add " pre-filled
   - `pm tui send Escape` - cancel the command

5. Breakdown plan (w):
   - `pm tui send w`
   - Wait 2 seconds
   - `tmux list-panes` - should see a breakdown pane (role "plan-breakdown")
   - Kill the breakdown pane after verifying

6. Plan deps (D):
   - `pm tui send D`
   - Wait 2 seconds
   - `tmux list-panes` - should see a deps pane (role "plan-deps")
   - Kill the deps pane after verifying

### Part 4: Refresh Persistence

1. While in plans view:
   - `pm tui send r` to refresh
   - Wait 2 seconds
   - `pm tui view` - should STILL be in plans view (not tree)
   - Verify plan data is still displayed correctly

### Part 5: View Switching

1. From plans view, press p to return to tree:
   - `pm tui send p`
   - `pm tui view` - verify tree is shown

2. Press p to return to plans:
   - `pm tui send p`
   - `pm tui view` - verify plans shown again

3. From plans view, verify that PR action keys (s, d, p) are blocked:
   - These should not trigger PR actions since we're in plans view
   - Note: They may be consumed by the PlansPane's on_key handler
   - Check `pm tui view` log line for any unexpected messages

### Part 6: Help Screen

1. Return to tree view first:
   - `pm tui send p` (if in plans view)

2. Open help screen:
   - `pm tui send ?`
   - `pm tui view` - verify help screen shows
   - Verify "p" is listed under "Panes & Views" as "Toggle plans view"
   - `pm tui send Escape` to close help

### Part 7: Cleanup

1. Kill any panes created during testing
2. Return to tree view with p if in plans view
3. Verify TUI is responsive: `pm tui view`
4. Final pane count should match initial count

## Expected Behavior

- p toggles between plans view and tree view
- Plans view shows all plans with names, status, PR counts, and intro text
- Navigation keys (Up/Down, j/k) move selection between plans
- Enter and v open the plan file in a pane
- e opens the plan file in an editor
- a pre-fills the command bar with "plan add "
- w launches pm plan breakdown in a pane
- D launches pm plan deps in a pane
- l runs pm plan load as an inline command (no pane)
- Refresh (r) stays in plans view
- PR actions are blocked while in plans view

## Reporting

```
PLANS PANE TEST RESULTS
=======================

## Part 1: Toggle Plans View
Plans view opens: [PASS/FAIL]
  Plans visible: <list plan names seen>
  Status shown: [Yes/No]
  PR counts shown: [Yes/No]
  Intro text shown: [Yes/No]
  Shortcuts shown: [Yes/No]
Plans view closes: [PASS/FAIL]
  Tree restored: [Yes/No]

## Part 2: Navigation
Down/j navigation: [PASS/FAIL]
Up/k navigation: [PASS/FAIL]
Boundary behavior: [PASS/FAIL]

## Part 3: Plan Actions
Enter (view plan): [PASS/FAIL] - <pane created? role correct?>
v (view plan): [PASS/FAIL] - <pane created? role correct?>
e (edit plan): [PASS/FAIL] - <pane created? role correct?>
a (add plan): [PASS/FAIL] - <command bar pre-filled?>
w (review plan): [PASS/FAIL] - <pane created? role correct?>
D (plan deps): [PASS/FAIL] - <pane created? role correct?>

## Part 4: Refresh Persistence
Stays in plans view after refresh: [PASS/FAIL]
Data still displayed: [PASS/FAIL]

## Part 5: View Switching
Toggle back to tree: [PASS/FAIL]
Toggle back to plans: [PASS/FAIL]
PR actions blocked in plans view: [PASS/FAIL]

## Part 6: Help Screen
P listed in help: [PASS/FAIL]

## Part 7: Cleanup
Panes cleaned up: [PASS/FAIL]
TUI responsive: [PASS/FAIL]

## Issues Found
<list any bugs, unexpected behavior, or UI issues>

## Frame Analysis
Total frames captured: <N>
Key state changes: <summary>

OVERALL: [PASS/FAIL]
```
