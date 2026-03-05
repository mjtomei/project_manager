---
title: Sync Refresh
description: Test r key sync, log line updates, and PR status changes
---
You are testing the sync/refresh functionality in the pm TUI. Your goal is
to verify that pressing 'r' triggers a sync operation, the log line updates
with sync results, and the tech tree reflects any status changes.

## Background

The TUI's 'r' key triggers a manual refresh that:
1. Immediately shows "Refreshing..." in the log line
2. Runs pr_sync.sync_prs() asynchronously to check for merged PRs on GitHub
3. Updates the log line with the result:
   - "Refreshed" if sync completed with no changes
   - "Synced: N PR(s) merged" if PRs were detected as merged
   - "Already up to date" if sync was skipped (too recent)
   - "Sync error: ..." if something went wrong
4. Reloads the project data and updates the tech tree display
5. The status bar shows "pulling" during sync, then "synced"/"no-op"/"error"

Sync has a minimum interval to avoid hammering GitHub -- if you press 'r'
twice quickly, the second press may show "Already up to date".

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (r=refresh)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer
- `pm pr list` - List all PRs with status (to verify before/after)

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Run `pm pr list` to record current PR statuses -- SAVE this as baseline
3. Run `pm tui view` to verify TUI is running
4. If in guide mode, press 'x' to dismiss

### Part 1: Basic Refresh

1. Trigger refresh:
   - `pm tui send r`
   - Immediately check: `pm tui view`
   - Log line should show "Refreshing..." (may be brief)

2. Wait for sync to complete:
   - Wait 3 seconds
   - `pm tui view`
   - Log line should show one of:
     * "Refreshed" -- sync completed, no merged PRs found
     * "Synced: N PR(s) merged" -- PRs were detected as merged
     * "Already up to date" -- sync skipped (too recent)
     * "Sync error: ..." -- something went wrong

3. Check the status bar:
   - Look at the status bar (bottom of TUI)
   - It should show a sync state: "synced", "no-op", or "error"

### Part 2: Status Bar Transition

1. Clear frames: `pm tui clear-frames`
2. Trigger refresh: `pm tui send r`
3. Quickly capture state: `pm tui view` (within 1 second)
   - Status bar may show "pulling" state during sync
4. Wait 3 seconds
5. `pm tui view` -- status bar should show post-sync state
6. Check `pm tui frames --all`:
   - Look for frames showing the "Refreshing..." message
   - Look for frames showing the final result message
   - The status bar should transition through states

### Part 3: Rapid Double Refresh

1. Wait at least 10 seconds (to clear the minimum sync interval)
2. First refresh: `pm tui send r`
3. Wait 3 seconds for it to complete
4. Immediately second refresh: `pm tui send r`
5. Wait 2 seconds
6. `pm tui view`
   - Second refresh should either complete normally or show "Already up to date"
   - This tests the minimum interval throttling

### Part 4: PR Status Verification

1. Run `pm pr list` again after the refresh
2. Compare with the baseline from setup:
   - Are there any status changes? (e.g., PRs that went from in_progress to merged)
   - If changes occurred, verify the tech tree in `pm tui view` reflects them
3. If no changes occurred, that's also valid -- note that sync found no updates

### Part 5: Refresh During Guide Mode

1. If the TUI has a guide step active:
   - Press 'r' to refresh
   - Log line should show "Refreshed - Guide step: <description>"
   - This is a different code path than the normal sync
2. If not in guide mode, skip this part (N/A)

### Part 6: Log Message Auto-Clear

1. After a manual refresh completes:
   - Note the log message shown
   - Wait 2 seconds
   - `pm tui view`
   - The log message should have auto-cleared (set_timer(1.0, _clear_log_message))
   - Log line should be empty or show a different message

## Expected Behavior

From pm_core/tui/app.py action_refresh():
- Calls _load_state() to reload from disk
- If in guide mode: logs "Refreshed - Guide step: ..." and returns
- If in normal mode: runs _do_normal_sync(is_manual=True) async, logs "Refreshing..."

From pm_core/tui/app.py _do_normal_sync():
- Calls pr_sync.sync_prs() with min_interval for manual refresh
- Updates status bar through: "pulling" -> "synced"/"no-op"/"error"
- Log messages: "Refreshed", "Synced: N PR(s) merged", "Already up to date", "Sync error: ..."
- Auto-clears log message after 1 second for manual refresh

## Reporting

```
SYNC REFRESH TEST RESULTS
===========================

## Part 1: Basic Refresh
"Refreshing..." shown: [PASS/FAIL]
Final result message: [PASS/FAIL] - <message seen>
Status bar updated: [PASS/FAIL] - <state shown>

## Part 2: Status Bar Transition
"pulling" state observed: [PASS/FAIL/Not captured]
Post-sync state: [PASS/FAIL] - <state shown>
Frames captured during sync: <N>

## Part 3: Rapid Double Refresh
Second refresh handled: [PASS/FAIL]
  Result: <"Already up to date" or completed normally>

## Part 4: PR Status Verification
Baseline PR count: <N>
Post-sync PR count: <N>
Status changes detected: [Yes/No]
  Changes: <list any status changes>
Tech tree matches pr list: [PASS/FAIL]

## Part 5: Guide Mode Refresh
Guide mode active: [Yes/No]
Guide refresh message: [PASS/FAIL/N/A]

## Part 6: Log Auto-Clear
Log message auto-cleared: [PASS/FAIL]

## Issues Found
<list any bugs, timing issues, or unexpected behavior>

OVERALL: [PASS/FAIL]
```
