---
title: Command Deduplication
description: Test that PR actions block concurrent/duplicate execution
tags: [tui, local, vanilla, github, containerized, uncontainerized]
---
You are testing the pm TUI command deduplication behavior. Your goal is to verify
that PR action commands cannot be triggered concurrently, preventing race conditions.

## Background

The TUI allows keyboard shortcuts to trigger PR actions like "pr start" (s key) and
"pr review" (d key). Previously, pressing the same key rapidly or triggering conflicting
actions on different PRs could cause race conditions. The fix adds in-flight action
tracking: while one PR action runs, all other PR actions are blocked with a "Busy: ..."
message in the log line.

## Available Tools

You have access to these commands:
- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (s=start, d=review, g=merge, j/k=navigate)
- `pm tui frames` - View captured frames
- `pm tui clear-frames` - Clear captured frames
- `tmux list-panes -t <session>` - List panes
- `pm pr add <title>` - Create a dummy PR
- `pm pr close <pr_id>` - Remove a PR from project.yaml

## Test Procedure

### 1. Setup - Create dummy PRs

Create two temporary PRs for testing. These will be cleaned up at the end.

```
pm pr add "Dedup test PR alpha" --description "Temporary PR for dedup testing"
pm pr add "Dedup test PR beta" --description "Temporary PR for dedup testing"
```

Note the IDs assigned (e.g. pr-024, pr-025). Then refresh the TUI:
- `pm tui send r`
- Wait 1 second, then `pm tui view` to confirm the dummy PRs appear
- Navigate to select one of the dummy PRs (use j/k keys)
- Run `pm tui clear-frames` to start with a clean frame buffer

### 2. Test A - Rapid double-press of start key

- Navigate to the first dummy PR
- Send 's' key twice rapidly: `pm tui send s s`
- Wait 2 seconds, then check the TUI: `pm tui view`
- The log line should show "Busy: Starting <pr_id>" for the second press
- Only ONE pr start command should be running
- Check `pm tui frames` to see the sequence of states
- Verify a frame with trigger starting with `log_message:Busy:` was captured

### 3. Test B - Different action while start is running

- If a pr start is still running (spinner visible), send 'd' key
- The log line should show "Busy: Starting <pr_id>"
- The done action should be blocked
- Note: `pr review` now runs async with a spinner, making the dedup guard critical
  for preventing conflicts between concurrent start and review operations

### 4. Test C - Command bar PR action while action is running

- If a pr start is still running, open command bar with '/'
- Type "pr start <second-dummy-pr-id>" and press Enter
- Should show "Busy: ..." message
- Press Escape to dismiss the command bar

### 5. Test D - Non-PR actions are NOT blocked

- While a pr start is running, send 'r' (refresh)
- This should NOT be blocked -- refresh should work normally

### 6. Test E - Action allowed after completion

- Wait for the in-flight action to complete (spinner stops)
- Verify the log line shows completion (e.g., "✓ Starting <pr_id> done")
- Try pressing 'd' on the same PR
- It should work (no "Busy" message)

### 7. Test F - pr review dedup with start blocked

- Navigate to the first dummy PR
- Send 'd' key to start `pr review` (runs async with spinner)
- While the spinner is visible, rapidly press 's' to try starting the same PR
- The log line should show "Busy: Reviewing <pr_id>"
- The start action should be blocked
- Check `pm tui frames` for a frame with trigger starting with `log_message:Busy:`
- Wait for pr review to complete, then verify the PR status changed

### 8. Cleanup - Remove dummy PRs

IMPORTANT: Always run this step, even if tests fail.

```
pm pr close <first-dummy-pr-id>
pm pr close <second-dummy-pr-id>
```

Then refresh the TUI: `pm tui send r`
Verify the dummy PRs are gone: `pm tui view`

## Expected Behavior

- `_inflight_pr_action` is set when a PR action begins
- `_guard_pr_action()` blocks and shows "Busy: ..." if `_inflight_pr_action` is set
- The flag is cleared when the command completes (success or failure)
- Both keyboard shortcuts and command bar commands are guarded
- Non-PR commands (r=refresh, g=guide, n=notes) are NOT blocked

## Reporting

```
COMMAND DEDUP TEST RESULTS
==========================

Dummy PRs created: <pr_id_1>, <pr_id_2>

Test A - Rapid double-press: [PASS/FAIL]
  Second press blocked with Busy message: [Yes/No]
  Only one command executed: [Yes/No]

Test B - Different action during inflight: [PASS/FAIL]
  Action blocked with Busy message: [Yes/No]

Test C - Command bar guarded: [PASS/FAIL]
  Command bar PR action blocked: [Yes/No]

Test D - Non-PR actions not blocked: [PASS/FAIL]
  Refresh worked during inflight action: [Yes/No]

Test E - Action allowed after completion: [PASS/FAIL]
  New action works after previous completes: [Yes/No]

Test F - pr review dedup with start blocked: [PASS/FAIL]
  pr review runs async with spinner: [Yes/No]
  Start blocked with Busy message during review: [Yes/No]
  Busy message captured in frames (log_message:Busy:*): [Yes/No]

Cleanup: [PASS/FAIL]
  Dummy PRs removed: [Yes/No]
  TUI state clean: [Yes/No]

Issues Found:
<list any bugs or unexpected behavior>

OVERALL: [PASS/FAIL]
```
