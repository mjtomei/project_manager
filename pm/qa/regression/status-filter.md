---
title: "Status Filter & Merged Toggle"
description: Test F key status filter cycling and X key merged PR toggle
tags: [tui, local, vanilla, github, containerized, uncontainerized]
---
You are testing the status filter and merged toggle features in the pm TUI.
Your goal is to verify that the F key cycles through status filters and the
X key toggles merged PR visibility.

## Background

The TUI tech tree can be filtered by PR status:
- F key cycles through: all -> pending -> in_progress -> in_review -> qa -> merged -> closed -> all
- X key toggles hiding/showing merged PRs
- When a filter is active, only PRs matching that status are shown in the tree
- The status bar displays the current filter
- The log line shows a message on each filter change

Status icons used: ○ pending, ● in_progress, ◎ in_review, 🧪 qa, ✓ merged, ✗ closed

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (F=cycle filter, X=toggle merged)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer
- `pm pr list` - List all PRs with status

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Run `pm pr list` to inventory all PRs and their statuses
   - Count how many PRs exist in each status (pending, in_progress, in_review, qa, merged, closed)
   - This is your reference for verifying filter results
3. Run `pm tui view` to verify TUI is running and showing the tech tree
4. If in guide mode, press 'x' to dismiss

### Part 1: Status Filter Cycling (f key)

1. Start state -- no filter (all PRs shown):
   - `pm tui view` - count the total number of PR nodes visible
   - This should match the total from `pm pr list`

2. First press -- filter to "pending":
   - `pm tui send f`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ○ pending"
   - Count visible PR nodes -- should match your pending count from setup
   - If no pending PRs exist, the tree should be empty or show a message

3. Second press -- filter to "in_progress":
   - `pm tui send f`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ● in_progress"
   - Count visible PR nodes -- should match in_progress count

4. Third press -- filter to "in_review":
   - `pm tui send f`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ◎ in_review"
   - Count visible PR nodes -- should match in_review count

5. Fourth press -- filter to "qa":
   - `pm tui send f`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: 🧪 qa"
   - Count visible PR nodes -- should match qa count

6. Fifth press -- filter to "merged":
   - `pm tui send f`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ✓ merged"
   - Count visible PR nodes -- should match merged count

7. Sixth press -- filter to "closed":
   - `pm tui send f`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ✗ closed"
   - Count visible PR nodes -- should match closed count

8. Seventh press -- back to "all":
   - `pm tui send f`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: all"
   - All PRs should be visible again

### Part 2: Merged Toggle (X key)

1. Reset to show all (press f until "Filter: all" appears, or it already is)

2. First toggle -- hide merged:
   - `pm tui send X`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Merged PRs hidden"
   - Count visible PR nodes -- should be total minus merged count
   - No PR with status "merged" should be visible

3. Verify hidden PRs:
   - If you had any merged PRs in setup, they should be gone from the tree
   - Non-merged PRs should all still be visible

4. Second toggle -- show merged:
   - `pm tui send X`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Merged PRs shown"
   - All PRs should be visible again

### Part 3: Filter and Merged Toggle Interaction

1. Hide merged PRs:
   - `pm tui send X` (should show "Merged PRs hidden")

2. Apply a status filter:
   - `pm tui send f` to filter to "pending"
   - `pm tui view`
   - Only pending PRs should show (merged toggle doesn't matter since
     we're filtering to pending specifically)

3. Cycle back to "all":
   - Press f until "Filter: all" appears
   - `pm tui view`
   - With no status filter but merged hidden, all non-merged PRs should show

4. Show merged again:
   - `pm tui send X` (should show "Merged PRs shown")
   - All PRs should be visible

### Part 4: Status Bar Filter Indicator

1. Apply a filter:
   - `pm tui send f`
   - `pm tui view`
   - Check the status bar (bottom of TUI) for a filter indicator
   - It should show something like "filter: ○ pending"

2. Reset filter:
   - Press F until back to "all"
   - Status bar filter indicator should disappear or show "all"

### Part 5: Frame Analysis

1. Run `pm tui frames --all` to see captured state changes
2. Look for frames triggered by:
   - "log_message:Filter: ..." -- each F press should generate one
   - "log_message:Merged PRs hidden/shown" -- each X press should generate one
3. Count the filter-related frames -- should match the number of F/X presses

## Expected Behavior

From pm_core/tui/app.py action_cycle_filter():
- STATUS_FILTER_CYCLE = [None, "pending", "in_progress", "in_review", "qa", "merged", "closed"]
- Cycles through the list, wrapping around to None (all)
- Calls tree._recompute() and tree.refresh(layout=True) after each change
- Logs "Filter: {icon} {status}" or "Filter: all"

From pm_core/tui/app.py action_toggle_merged():
- Toggles tree._hide_merged boolean
- Calls tree._recompute() and tree.refresh(layout=True)
- Logs "Merged PRs hidden" or "Merged PRs shown"

From pm_core/tui/tech_tree.py _recompute():
- If _status_filter is set: filters PRs to only that status
- Elif _hide_merged is True: filters out PRs with status "merged"
- Note: status filter takes priority over merged toggle

## Reporting

```
STATUS FILTER & MERGED TOGGLE TEST RESULTS
============================================

PR inventory from pm pr list:
  Total: <N>
  pending: <N>
  in_progress: <N>
  in_review: <N>
  qa: <N>
  merged: <N>
  closed: <N>

## Part 1: Status Filter Cycling
Initial (all): [PASS/FAIL] - <visible count> PRs shown
Filter pending: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Filter in_progress: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Filter in_review: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Filter qa: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Filter merged: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Filter closed: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Back to all: [PASS/FAIL] - <visible count> PRs (expected <total>)
  Log message: <message seen>

## Part 2: Merged Toggle
Hide merged: [PASS/FAIL] - <visible count> PRs (expected <total - merged>)
  Log message: <message seen>
  Merged PRs gone: [Yes/No]
Show merged: [PASS/FAIL] - <visible count> PRs (expected <total>)
  Log message: <message seen>

## Part 3: Filter + Merged Interaction
Status filter overrides merged toggle: [PASS/FAIL]
All filter with merged hidden shows non-merged: [PASS/FAIL]

## Part 4: Status Bar Indicator
Filter shown in status bar: [PASS/FAIL]
Filter cleared when reset: [PASS/FAIL]

## Part 5: Frame Analysis
Total frames captured: <N>
Filter frames: <N> (expected ~9 for F presses + 2 for X presses)

## Issues Found
<list any bugs, incorrect counts, or unexpected behavior>

OVERALL: [PASS/FAIL]
```
