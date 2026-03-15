---
title: Cluster Session Resume
description: Test that cluster explore sessions are saved and resumed correctly
tags: [core, local, vanilla, github, containerized, uncontainerized]
---
You are testing the pm cluster explore session resume functionality. Your goal is
to verify that Claude sessions are properly saved and resumed when restarting
cluster explore.

## Background

The pm cluster explore command uses Claude's session management. When you:
1. Start cluster explore, a UUID is generated and saved to .pm-sessions.json
2. Exit and restart cluster explore, it should resume with --resume <session_id>
3. Using --fresh flag should start a fresh session

This test uses cluster explore instead of guide because:
- Guide advances through steps, making resume testing unreliable
- Cluster explore has a stable session key (cluster:explore) that doesn't change

## Available Tools

- `pm tui view` - See current TUI state
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `tmux split-window -t <session> -h -c <dir>` - Create a new pane
- `tmux send-keys -t <pane_id> <command> Enter` - Send command to pane
- `tmux capture-pane -t <pane_id> -p` - Capture pane content
- `tmux kill-pane -t <pane_id>` - Kill a pane
- `cat pm/.pm-sessions.json` - View session registry
- `ps aux | grep "claude.*resume\\|claude.*session-id"` - Check claude process flags

## Test Procedure

1. Check current state:
   - View pm/.pm-sessions.json to see saved sessions
   - Note if cluster:explore session already exists

2. Test session creation:
   - Create a new tmux pane for testing
   - Run `pm cluster explore --fresh` to start a fresh session
   - Wait for Claude to start (about 10 seconds)
   - Check .pm-sessions.json - should have new cluster:explore entry
   - Note the session_id
   - Send a memorable message to Claude, e.g.: "Remember this secret: PURPLE-TIGER-99"
   - Wait for Claude to acknowledge (should say something like "I'll remember...")

3. Test session resume:
   - Kill the pane with `tmux kill-pane -t <pane_id>`
   - Create a new pane
   - Run `pm cluster explore` (WITHOUT --fresh flag)
   - Check if --resume flag is being used: `ps aux | grep "claude.*resume"`
   - The process should show: `claude --resume <session_id>`
   - Wait for Claude to start
   - Ask "What is the secret I asked you to remember?"
   - Claude should respond with the secret phrase (e.g., "PURPLE-TIGER-99")

4. Verify conversation context:
   - The previous conversation should be visible in the pane
   - Claude should remember information from before the kill

## Expected Behavior

From pm_core/claude_launcher.py launch_claude():
- If session exists in registry, uses --resume <session_id>
- If no session, generates UUID and uses --session-id <uuid>
- Saves session_id to registry immediately

## Reporting

```
TEST RESULTS
============
Session creation: [PASS/FAIL]
  - Session ID saved to .pm-sessions.json: Y/N
  - Claude acknowledged secret phrase: Y/N

Session resume: [PASS/FAIL]
  - Process uses --resume flag: Y/N
  - Previous conversation visible: Y/N
  - Claude remembers secret phrase: Y/N

Details:
<findings, including session ID and any errors>

OVERALL: [PASS/FAIL]
```
