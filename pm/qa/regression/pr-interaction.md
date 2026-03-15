---
title: PR Interaction
description: Test PR navigation, selection, status changes, and actions
tags: [tui, local, vanilla, github, containerized, uncontainerized]
---
You are testing the PR interaction functionality in the pm TUI. Your goal is to verify
that users can navigate, select, and manage PRs through the tech tree interface.

## Background

The TUI displays PRs in a tech tree format. Users can:
- Navigate between PRs using arrow keys (Up/Down)
- Select a PR to see details (Enter)
- Start working on a PR ('s' key)
- Mark a PR as done ('d' key)
- Launch Claude with the PR prompt ('c' key)
- Edit the plan file ('e' key)

The tech tree shows PR status with visual indicators and dependency relationships.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames
- `pm tui clear-frames` - Clear frame buffer
- `cat pm/project.yaml` - View project config and PR list
- `pm pr list` - List all PRs with status

## Prerequisites

This test requires PRs to exist in the project. Check first:
1. Run `pm pr list` to see if PRs exist
2. If no PRs exist, note this and skip to the "No PRs" section

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start fresh
2. Run `pm pr list` to see available PRs
3. If in guide mode, press 'x' to dismiss and show the tech tree
4. Run `pm tui view` to see the tech tree

### Scenario A: PR Navigation

1. Starting position:
   - Run `pm tui view` and note which PR is currently selected (highlighted)
   - Note the total number of PRs visible

2. Navigate down:
   - `pm tui send Down`
   - Wait 1 second
   - `pm tui view` - selection should move to next PR
   - Check `pm tui frames` to see the state change

3. Navigate up:
   - `pm tui send Up`
   - Wait 1 second
   - `pm tui view` - selection should return to previous PR

4. Boundary testing:
   - Navigate to the first PR (multiple Up presses)
   - Press Up again - should stay at first PR (not wrap or error)
   - Navigate to last PR (multiple Down presses)
   - Press Down again - should stay at last PR

### Scenario B: PR Selection and Details

1. Select a PR:
   - Navigate to a PR
   - `pm tui send Enter` to activate/select it
   - `pm tui view` - detail panel should appear on the right
   - Note what information is shown in the detail panel

2. Detail panel contents (verify these are displayed):
   - PR ID
   - PR title/description
   - Status (pending/in_progress/done)
   - Dependencies (if any)
   - Branch name (if set)

3. Navigate while detail panel is open:
   - Press Up/Down to change selected PR
   - Detail panel should update to show new PR's info

### Scenario C: PR Status Changes

1. Start a PR:
   - Navigate to a PR with status "pending"
   - `pm tui send s` to start it
   - `pm tui view` - status should change to "in_progress"
   - Check the log line for confirmation message

2. Complete a PR:
   - With an "in_progress" PR selected
   - `pm tui send d` to mark done
   - `pm tui view` - status should change to "done"
   - Check the log line for confirmation

3. Dependency enforcement:
   - If a PR has unmet dependencies, starting it may warn or fail
   - Note any dependency-related behavior

### Scenario D: PR Actions

1. Launch Claude ('c'):
   - Select a PR
   - `pm tui send c`
   - This should open a new pane with Claude
   - Check `tmux list-panes` for new pane
   - Note: This may fail if not in tmux or Claude not installed

2. Edit plan ('e'):
   - Select a PR that has an associated plan
   - `pm tui send e`
   - Should open editor in a new pane
   - Check `tmux list-panes` for editor pane

### Scenario E: Command Bar PR Commands

1. Focus command bar:
   - `pm tui send /`
   - Command bar should be focused

2. Run pr list command:
   - `pm tui send "pr list"`
   - `pm tui send Enter`
   - Check log line for output

3. Run pr start via command bar:
   - `pm tui send /`
   - `pm tui send "pr start <pr-id>"` (use actual PR ID)
   - `pm tui send Enter`
   - Verify PR status changes

### No PRs Section

If no PRs exist in the project:
1. Verify the TUI shows an appropriate message ("No PRs defined" or similar)
2. Verify navigation keys don't cause errors
3. Verify PR action keys (s, d, p) handle the empty state gracefully
4. Note what the empty state looks like

## Expected Behavior

From pm_core/tui/app.py:
- TechTree widget handles PR display and navigation
- PRSelected message sent when PR is highlighted or activated (Enter)
- Enter triggers edit (same as 'e' key)
- action_start_pr() runs `pm pr start <id>`
- action_done_pr() runs `pm pr review <id>`
- action_launch_claude() opens Claude in new pane

## Reporting

```
PR INTERACTION TEST RESULTS
===========================

PRs Present: [Yes/No] - <count>
Guide Mode Dismissed: [Yes/No/N/A]

## Scenario A: Navigation
- Initial selection visible: [Yes/No]
- Down navigation works: [PASS/FAIL]
- Up navigation works: [PASS/FAIL]
- Boundary behavior correct: [PASS/FAIL]

## Scenario B: Selection/Details
- Enter shows detail panel: [PASS/FAIL]
- Detail panel shows PR info: [PASS/FAIL]
- Details update on navigation: [PASS/FAIL]

## Scenario C: Status Changes
- Start PR ('s'): [PASS/FAIL/SKIPPED] - <notes>
- Done PR ('d'): [PASS/FAIL/SKIPPED] - <notes>
- Dependency handling: <observations>

## Scenario D: Actions
- Launch Claude ('c'): [PASS/FAIL/SKIPPED] - <notes>
- Edit plan ('e'): [PASS/FAIL/SKIPPED] - <notes>

## Scenario E: Command Bar
- Command bar focus: [PASS/FAIL]
- pr list command: [PASS/FAIL]
- pr start command: [PASS/FAIL/SKIPPED]

## Frame Analysis
- Total frames captured: <N>
- Key state transitions observed: <list>

## Issues Found
<list any bugs, unexpected behavior, or UI issues>

## Notes
<any additional observations about PR interaction>

OVERALL: [PASS/FAIL]
```
