---
title: TUI Manual Testing
description: Test TUI changes against a throwaway project in the workdir
tags: [tui, manual]
---
## Setup

1. Install pm into a virtual environment:
   ```
   python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
   pip install -e /workspace   # or wherever the project_manager clone is in your workdir
   ```
2. Create a throwaway test project. Use your workdir if you have one (`/workspace`), otherwise use `/tmp`:
   ```
   TEST_DIR=${WORKDIR:-/tmp}/pm-test-$(date +%s)
   mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
   git init
   ```
3. Create a `pm/` directory with a `project.yaml` — see `pm/project.yaml` in the main repo for field format. Use `backend: local` to avoid needing GitHub. Include a mix of PR statuses and dependencies.
4. Set the override file at `~/.pm/sessions/$(pm session tag)/override` to point to the test directory. Run `pm session tag` from the directory you created, then write the path into the override file:
   ```
   TAG=$(cd "$TEST_DIR" && pm session tag)
   mkdir -p ~/.pm/sessions/$TAG
   echo "$TEST_DIR" > ~/.pm/sessions/$TAG/override
   ```
5. `cd` into the test directory and start the session. The `pm session` command creates a tmux session and then tries to attach to it. Since Claude Code's Bash tool has no TTY, the attach will fail — but the session is still created and usable. Ignore the attach error:
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
