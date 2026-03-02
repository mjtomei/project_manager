---
title: TUI Log Viewer
description: Test L key opens log pane, verify content and pane lifecycle
---
You are testing the TUI log viewer feature in the pm TUI. Your goal is to
verify that pressing 'L' opens a log pane, the log shows recent TUI activity,
and the pane lifecycle works correctly (launch, focus, kill, relaunch).

## Background

The 'L' key triggers action_view_log() which:
1. Gets the command log file path from command_log_file() (located at
   ~/.pm/debug/{session-tag}.log)
2. If the file doesn't exist, shows "No log file yet." in the log line
3. If it exists, launches a pane running `tail -f <log_path>` with role "log"

The log file contains timestamped entries from all pm commands executed in this
session -- every pm CLI command logs its execution and result here.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (L=view log)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `cat ~/.pm/pane-registry/<base>.json` - View pane registry (multi-window format)
- `python3 -c "import json; d=json.load(open('<path>')); print(json.dumps(d, indent=2))"` - Pretty-print registry
- `tmux display-message -p "#{session_name}"` - Get session name
- `tmux capture-pane -t <pane_id> -p` - Capture content of a specific pane
- `tmux kill-pane -t <pane_id>` - Kill a specific pane

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Get base session name (strip ~N suffix if present)
4. Record initial state:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` -- count panes
   - `cat ~/.pm/pane-registry/<base>.json` -- note the "windows" dict and registered panes/roles
   - Check if a log pane already exists (role "log") in any window's panes
5. Run `pm tui view` to verify TUI is running

### Part 1: Launch Log Pane

1. Open the log viewer:
   - `pm tui send L`
   - Wait 2 seconds

2. Verify pane was created:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"`
   - Should have one more pane than before
   - The new pane should be running `tail` (visible in pane_current_command)

3. Check pane registry (multi-window format):
   - `cat ~/.pm/pane-registry/<base>.json`
   - Registry uses `{"windows": {"@ID": {"panes": [...]}}}` format
   - Should have a pane with role "log" in the current window's panes

4. Check TUI log line:
   - `pm tui view`
   - Should show "Launched log pane" or "Focused existing log pane"

### Part 2: Log Pane Content

1. Find the log pane ID from the pane list or registry
2. Capture its content:
   - `tmux capture-pane -t <pane_id> -p`
3. Verify the content:
   - Should show timestamped log entries (format: "HH:MM:SS LEVEL message")
   - Should contain entries from recent pm commands
   - Look for entries related to your test actions (tui view, tui send, etc.)
   - The log should be continuously updating (tail -f)

### Part 3: Log Updates in Real-Time

1. Trigger some TUI activity while the log pane is open:
   - `pm tui send r` (refresh -- this triggers a sync command)
   - Wait 2 seconds
2. Capture the log pane content again:
   - `tmux capture-pane -t <pane_id> -p`
   - New entries should have appeared for the refresh/sync operation
3. This verifies that `tail -f` is working and the log updates in real-time

### Part 4: Focus Existing Log Pane (Dedup)

1. With the log pane already running, press 'L' again:
   - `pm tui send L`
   - Wait 1 second
2. Check pane count:
   - `tmux list-panes -t <session> -F "#{pane_id}"`
   - Should be SAME as before (no new pane created)
3. Check registry:
   - `cat ~/.pm/pane-registry/<base>.json`
   - Should still have exactly ONE pane with role "log" across all windows
4. Check log line:
   - `pm tui view`
   - Should show "Focused existing log pane"

### Part 5: Kill and Relaunch

1. Find the log pane ID from the registry
2. Kill the log pane:
   - `tmux kill-pane -t <pane_id>`
   - Wait 2 seconds (allow pane-exited handler to run)

3. Verify cleanup:
   - `cat ~/.pm/pane-registry/<base>.json`
   - The log pane should be unregistered (role "log" gone from all windows)

4. Relaunch:
   - `pm tui send L`
   - Wait 2 seconds

5. Verify relaunch:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"`
   - A new log pane should exist
   - `cat ~/.pm/pane-registry/<base>.json` -- role "log" should be back in current window
   - The pane ID should be different from the killed one

### Part 6: Cleanup

1. Kill the log pane if you created one:
   - Find pane ID from registry
   - `tmux kill-pane -t <pane_id>`
   - Wait 1 second
2. Verify TUI is still responsive:
   - `pm tui view`
3. Verify final pane count matches initial count

## Expected Behavior

From pm_core/tui/app.py action_view_log():
- Gets log path from command_log_file() (pm_core.paths)
- If file doesn't exist: logs "No log file yet."
- If exists: calls _launch_pane(f"tail -f {log_path}", "log")

From _launch_pane():
- Checks for existing pane with role "log" via find_live_pane_by_role()
- If found: focuses it, logs "Focused existing log pane"
- If not found: creates new pane, registers with role "log"

Log file location: ~/.pm/debug/{session-tag}.log
Log format: "HH:MM:SS LEVEL message" (e.g., "14:23:01 INFO pm exit=0 ...")

## Reporting

```
TUI LOG VIEWER TEST RESULTS
=============================

## Part 1: Launch Log Pane
'L' key creates pane: [PASS/FAIL]
  Initial pane count: <N>
  After launch count: <N>
Pane running tail: [PASS/FAIL]
Registry has role "log": [PASS/FAIL]
Log line message: <message seen>

## Part 2: Log Content
Log entries visible: [PASS/FAIL]
Timestamp format correct: [PASS/FAIL]
Recent activity present: [PASS/FAIL]
  Sample entry: <one log line>

## Part 3: Real-Time Updates
New entries after refresh: [PASS/FAIL]
tail -f working: [PASS/FAIL]

## Part 4: Focus Dedup
Second 'L' reuses pane: [PASS/FAIL]
  Pane count unchanged: [Yes/No]
  "Focused existing" message: [Yes/No]

## Part 5: Kill and Relaunch
Kill removes from registry: [PASS/FAIL]
Relaunch creates new pane: [PASS/FAIL]
  New pane ID different: [Yes/No]
  Registry updated: [Yes/No]

## Part 6: Cleanup
Panes cleaned up: [PASS/FAIL]
TUI responsive: [PASS/FAIL]
Final pane count matches initial: [PASS/FAIL]

## Issues Found
<list any bugs, missing log entries, or unexpected behavior>

OVERALL: [PASS/FAIL]
```
