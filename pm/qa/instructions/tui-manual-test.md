---
title: TUI Manual Testing
description: Test TUI changes against a throwaway project in /tmp
tags: [tui, manual]
---
## Setup

1. Install pm into a virtual environment:
   ```
   python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
   pip install -e /workspace   # or wherever the project_manager clone is in your workdir
   ```
2. Create a throwaway test project in `/tmp`:
   ```
   mkdir -p /tmp/pm-test-$(date +%s) && cd $_
   git init
   ```
3. Create a `pm/` directory with a `project.yaml` — see `pm/project.yaml` in the main repo for field format. Use `backend: local` to avoid needing GitHub. Include a mix of PR statuses and dependencies.
4. Set the override file at `~/.pm/sessions/$(pm session tag)/override` to point to the workdir. Run `pm session tag` from the `/tmp` directory you created.
5. `cd` into the repo and run `pm session &` (must be backgrounded — it will try to attach to a tmux session).

## Test Steps

Use `pm --help` and `pm <command> --help` for CLI usage. Press `?` in the TUI for keybindings.

For inspecting a running session from another terminal:
- `pm tui frame` — capture TUI framebuffer
- `tmux capture-pane -p -t <session>:<window>.<pane> -S -` — full scrollback
- `tmux send-keys -t <session>:<window>.<pane> "key" ""` — simulate input
- Don't run pm commands directly — run them inside a new pane inside the test tmux session (not your own session)
