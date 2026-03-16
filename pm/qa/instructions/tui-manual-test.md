---
title: TUI Manual Testing
description: Test TUI changes against a throwaway project in the workdir
tags: [tui, manual]
---
## Environment

You are running inside a Docker container with the full project_manager
repository cloned at `/workspace`. The `pm` CLI and all of `pm_core` are
available — you just need to install into a venv first. `tmux` is
available for running sessions. You have everything needed to run the
full pm workflow end-to-end.

## Setup

1. Install pm into a virtual environment:
   ```
   python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
   pip install -e /workspace
   ```
2. Create a throwaway test project in `/tmp`:
   ```
   TEST_DIR=/tmp/pm-test-$(date +%s)
   mkdir -p "$TEST_DIR" && cd "$TEST_DIR"
   git init
   ```
3. Initialize pm and add PRs using the CLI. Choose whatever titles and
   dependency structure make sense for what you're testing — here's an
   example with four PRs and a dependency chain:
   ```
   cd "$TEST_DIR"
   pm init --backend local --no-import
   pm pr add "Add login feature"
   pm pr add "Fix database migration" --depends-on <id-from-first>
   pm pr add "Refactor auth module" --depends-on <id-from-first>,<id-from-second>
   pm pr add "Add unit tests"
   ```
   PR IDs are auto-generated hashes (e.g. `pr-a1b2c3d`) — note the ID
   printed by each `pm pr add` and use it in subsequent `--depends-on`
   flags. If you need a mix of PR statuses for the initial test fixture,
   you can edit `pm/project.yaml` directly to set `status` on individual
   PRs (e.g. `merged`, `in_review`). This is only for bootstrapping the
   test project — once setup is complete, do not edit `project.yaml` by
   hand. All subsequent changes should go through `pm` CLI or TUI
   commands so you are actually exercising the functionality under test.
4. Start a tmux server and launch the session. The `pm session` command
   tries to attach to the tmux session it creates, which fails without a
   TTY — but the session is still created and usable:
   ```
   tmux start-server
   cd "$TEST_DIR" && pm session 2>/dev/null || true
   ```

## Test Steps

Use `pm --help` and `pm <command> --help` for CLI usage. Press `?` in the TUI for keybindings.

For inspecting and interacting with the running session:
- `pm tui view` — capture current TUI framebuffer
- `tmux capture-pane -p -t <session>:<window>.<pane> -S -` — full scrollback
- `tmux send-keys -t <session>:<window>.<pane> "key" ""` — simulate input
- Run pm commands inside a pane in the test tmux session, not directly in your own session
