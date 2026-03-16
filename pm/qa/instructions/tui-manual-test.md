---
title: TUI Manual Testing
description: Test TUI changes against a throwaway project in the workdir
tags: [tui, manual]
---
## Setup

1. Install pm into a virtual environment:
   ```
   python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
   pip install -e .   # run from the project_manager clone
   ```
2. Create a throwaway test project. Use your workdir if you have one, otherwise `/tmp`:
   ```
   TEST_DIR=/tmp/pm-test-$(date +%s)
   mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
   git init
   ```
3. Create a `pm/` directory with a `project.yaml` — see `pm/project.yaml` in the main repo for field format. Use `backend: local` to avoid needing GitHub. Include a mix of PR statuses and dependencies.
4. Start the session from the test directory. The `pm session` command creates a tmux session and then tries to attach to it. Since Claude Code's Bash tool has no TTY, the attach will fail — but the session is still created and usable. Ignore the attach error:
   ```
   cd "$TEST_DIR" && pm session 2>/dev/null || true
   ```

## Test Steps

Use `pm --help` and `pm <command> --help` for CLI usage. Press `?` in the TUI for keybindings.

For inspecting a running session from another terminal:
- `pm tui view` — capture current TUI framebuffer
- `tmux capture-pane -p -t <session>:<window>.<pane> -S -` — full scrollback
- `tmux send-keys -t <session>:<window>.<pane> "key" ""` — simulate input
- Don't run pm commands directly — run them inside a new pane inside the test tmux session (not your own session)
