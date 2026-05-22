---
title: TUI Manual Testing
description: Test TUI changes against a throwaway project in the workdir. Includes how to drive review/QA loops without real Claude using the bundled fake-claude stand-in (see "Driving Claude sessions with the fake").
---
## Setup

1. Install pm into a virtual environment:
   ```
   python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
   pip install -e .   # run from the project_manager clone
   ```
   The container sets `PYTHONPATH=/opt/pm-src` (master), shadowing the
   editable install. Override before launching the session:
   ```
   export PYTHONPATH=/workspace   # path to your editable clone
   ```
   Confirm with `pm which` — it should print your clone, not `/opt/pm-src`.
2. Create a throwaway test project. Use your workdir if you have one, otherwise `/tmp`, for example:
   ```
   TEST_DIR=<workdir>/pm-test-$(date +%s)
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

   **Testing container-mode features (nested podman):** if your test
   exercises pm's container mode — e.g. a container-mode QA loop, where the
   test project's pm launches scenario containers from *inside* the
   container this test session already runs in — you must opt the test
   project into nested podman. Add to its `pm/project.yaml` under the
   `project:` block:
   ```yaml
   project:
     nested_podman: true
   ```
   Without it, the inner `podman run` is launched without the
   nested-podman flags (notably `--uts=host`) and dies with
   `sethostname: Operation not permitted` before any scenario starts —
   because the surrounding container has no `CAP_SYS_ADMIN` and a seccomp
   filter that blocks `sethostname`. This is bootstrap-only project.yaml
   setup (same exception as the status edits above); enable container mode
   itself through the normal surface (`pm container enable`). The pm-dev
   image already ships the other nesting prerequisites (uidmap file caps,
   `/etc/subuid` for `pm`, fuse-overlayfs storage).
4. Start the session from the test directory. The `pm session` command creates a tmux session and then tries to attach to it. Since Claude Code's Bash tool has no TTY, the attach will fail — but the session is still created and usable. Ignore the attach error:
   ```
   cd "$TEST_DIR" && pm session 2>/dev/null || true
   ```

## Driving Claude sessions with the fake (no real API calls)

pm ships a scriptable Claude stand-in, **fake-claude**, so a scenario can drive
flows that normally spawn Claude — review loops, QA loops, watcher/impl panes —
without a real Claude binary or API calls. Use it whenever your scenario needs a
loop to reach a verdict deterministically (e.g. `NEEDS_WORK` then `PASS`)
instead of waiting on a real model.

To make a flow use the fake, write a config for the session with
`pm fake-claude config set` (validates and writes to
`~/.pm/sessions/<tag>/fake-claude`); with no config the flow uses real Claude.
Pass the JSON inline, with `--file`, or on stdin, and `--tag` to target a
session other than the current one:
```
pm fake-claude config set --file my-config.json      # current session
pm fake-claude config set < my-config.json
pm fake-claude config set '{"_all": {}, "review": {"verdicts": ["PASS"]}}'
pm fake-claude config show     # inspect; config clear removes it
```
The config maps each session type to the verdict(s) it should emit. Start from
the reference config at `tests/fixtures/fake_claude/example-config.json` (covers
the loop session types and all three verdict forms) and trim it to what your
scenario drives:
- weighted random — `{"verdicts": {"PASS": 100}}`
- scripted sequence — `{"verdicts": ["NEEDS_WORK", "PASS"]}` emits one verdict
  per loop iteration (clamps to the last when iterations run out)
- per-iteration overrides — list entries may be objects, e.g.
  `{"verdict": "READY", "delay": 1}`, layering `body`/`delay`/`preamble` over the
  type's defaults
- `_all: {}` makes every other session a no-verdict mock

`config set` rejects verdict/session-type pairings that aren't in the catalogue
(e.g. `PASS` on `qa_verification`) and writes nothing in that case.

## Test Steps

Use `pm --help` and `pm <command> --help` for CLI usage. Press `?` in the TUI for keybindings.

For inspecting a running session from another terminal:
- `pm tui view` — capture current TUI framebuffer
- `tmux capture-pane -p -t <session>:<window>.<pane> -S -` — full scrollback
- `tmux send-keys -t <session>:<window>.<pane> "key" ""` — simulate input
- Don't run pm commands directly — run them inside a new pane inside the test tmux session (not your own session)
