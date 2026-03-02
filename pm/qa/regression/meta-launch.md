---
title: Meta Session Launch
description: Test m key launches meta pane with correct role and context
---
You are testing the meta session launch feature in the pm TUI. Your goal is
to verify that pressing 'm' launches a meta-development session for working
on the pm tool itself.

## Background

The 'm' key triggers action_launch_meta() which runs `pm meta` as a synchronous
command via _run_command("meta"). The meta command:
1. Detects the pm installation (finds the pm source code directory)
2. Builds a meta prompt describing the pm tool's architecture
3. Creates or finds a workdir for meta development
4. Launches Claude in a new pane with the meta prompt and appropriate context

The meta session is designed for self-referential development -- working on the
project manager tool itself from within the project manager TUI.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (m=meta)
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
5. Run `pm tui view` to verify TUI is running

### Part 1: Launch Meta Session

1. Send meta key:
   - `pm tui send m`
   - Wait 2 seconds (meta needs time to detect pm install and set up)

2. Check log line:
   - `pm tui view`
   - The log line should show "> meta" (the command being run)
   - After completion, it may show output from the meta command

3. Check for new pane:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"`
   - Compare with initial count -- should have one more pane
   - The new pane should be running Claude or a shell with Claude

4. Check pane registry (multi-window format):
   - `cat ~/.pm/pane-registry/<base>.json`
   - Registry uses `{"windows": {"@ID": {"panes": [...]}}}` format
   - Look in the current window's panes for a pane with role "meta" or related
   - Note: The meta command uses _run_command which is synchronous,
     so the pane may be registered differently than _launch_pane panes

### Part 2: Verify Meta Pane Content

1. Identify the new pane ID from the pane list comparison
2. Capture its content:
   - `tmux capture-pane -t <pane_id> -p`
   - Look for Claude startup indicators or meta prompt content
   - The pane should show signs of a Claude session starting

3. Check that the meta session has appropriate context:
   - The prompt should reference the pm tool
   - There may be file paths to pm source code visible

### Part 3: TUI Responsiveness After Meta Launch

1. Verify TUI is still responsive:
   - `pm tui view` -- should render without errors
   - Try navigating: `pm tui send Down` then `pm tui send Up`
   - TUI should still respond to keypresses

### Part 4: Duplicate Meta Launch

1. With meta pane already running, press 'm' again:
   - `pm tui send m`
   - Wait 2 seconds
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"`
   - Check if a second meta pane was created or if the existing one was focused
   - Note the behavior (this tests deduplication for meta sessions)

### Part 5: Cleanup

1. If a meta pane was created, you can leave it running -- the user may want it
2. Alternatively, to clean up:
   - Find the meta pane ID from the registry or pane list
   - `tmux kill-pane -t <pane_id>`
   - Wait 1 second
   - Verify the TUI is still running: `pm tui view`
   - Check registry was updated: `cat ~/.pm/pane-registry/<base>.json`

## Expected Behavior

From pm_core/tui/app.py action_launch_meta():
- Calls _run_command("meta") which runs `pm meta` synchronously
- The meta command finds the pm installation, builds a prompt, and launches Claude
- A new pane is created in the tmux session
- The TUI shows "> meta" in the log line while running

From pm_core/cli/ meta command:
- _detect_pm_install() finds the pm source code
- _build_meta_prompt() creates a comprehensive prompt about pm architecture
- _meta_workdir() creates/finds a working directory
- Launches Claude with --session-id for resumable sessions

## Reporting

```
META SESSION LAUNCH TEST RESULTS
==================================

## Part 1: Launch Meta Session
'm' key triggered meta: [PASS/FAIL]
Log line showed "> meta": [PASS/FAIL]
New pane created: [PASS/FAIL]
  Initial pane count: <N>
  After meta count: <N>
Pane registry updated: [PASS/FAIL]
  Role: <role found or "not registered">

## Part 2: Meta Pane Content
Claude session starting: [PASS/FAIL/Unclear]
Meta context visible: [PASS/FAIL/Unclear]
  Content observed: <brief description>

## Part 3: TUI Responsiveness
TUI responds after meta launch: [PASS/FAIL]
Navigation still works: [PASS/FAIL]

## Part 4: Duplicate Launch
Behavior on second 'm': <description>
Duplicate pane created: [Yes/No]

## Part 5: Cleanup
Meta pane state: <running/killed/left running>
TUI responsive after cleanup: [PASS/FAIL]

## Issues Found
<list any bugs, errors, or unexpected behavior>

OVERALL: [PASS/FAIL]
```
