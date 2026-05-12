---
pr: pr-6be8ee6
workdir: /tmp/pm-test-scenario34-1778627623
captured_at: 2026-05-12T23:13:00Z
---

## Commands

```
# Set up clone-shadow venv
python3 -m venv /tmp/pm-venv && source /tmp/pm-venv/bin/activate
pip install -e /workspace
export PYTHONPATH=/workspace
pm which   # /workspace/pm_core

# Fresh pm project
TEST_DIR=/tmp/pm-test-scenario34-1778627623
mkdir -p "$TEST_DIR" && cd "$TEST_DIR" && git init
pm init --backend local --no-import
pm pr add "Login feature"

# Pre-seed QA fixtures (1 instruction, 0 regressions, 2 artifacts)
mkdir -p pm/qa/{instructions,regression,artifacts}
# ...frontmatter md files for setup-env, login-cast, db-log...

# Start pm session, then drive from outside via tmux send-keys.
# Recording done via the tmux-screen-recording.md recipe:
# a separate `pm-recorder` tmux session runs
#   asciinema rec --quiet recording.cast -c 'tmux attach -t $TARGET'
# while a transcript pipe-pane streams the home pane's scrollback
# to transcript.log. Keys are sent with `tmux send-keys` to drive
# the QA pane (q), open the picker (a), cancel (Esc), submit empty,
# submit picker-test as Artifact recipe (Enter), then add a
# regression file on disk and refresh the pane.
```

See `/tmp/scenario34_drive.sh` for the full driver script used.

## What this demonstrates

End-to-end QA pane behavior for scenario 34:

1. The QA pane renders all three sections — `Instructions (1)`,
   `Regression Tests (0)`, `Artifact Recipes (2)` — with the empty
   regression header still shown. Status bar reads `3 item(s)`.
2. Pressing `a` opens the `QACreatePickerScreen` modal with a Name
   input and exactly three Kind options (`Instruction`, `Regression
   test`, `Artifact recipe`), pointer `▸` on the default
   `Instruction`. Hint line is present.
3. `Esc` cancels the modal cleanly; no new tmux windows or files.
4. Submitting Enter with a blank Name leaves the picker open (no
   crash, no launch).
5. Typing `picker-test`, pressing `↓ ↓`, then `Enter` launches a new
   tmux pane whose start command is
   `pm qa author-artifact picker-test` (verified separately;
   `tmux list-panes -F` showed `bash -c '...pm qa author-artifact
   picker-test'`).
6. Submitting with `Instruction` selected launches
   `pm qa author-instruction picker-test2` (verified separately).
7. Adding `pm/qa/regression/sample-regression.md` and re-entering
   the pane re-reads disk: `Regression Tests (1)` appears, status
   bar reads `4 item(s)`.
8. Running the regression launches `claude` with a prompt produced
   by `build_regression_test_prompt`. Captured pane-start command
   includes the tmux session name, the regression body text
   (`Regression body content.`), and a capture path under
   `pm/qa/captures/regression/<test-id>/<timestamp>/`.

## Files

- `recording.cast` — asciinema replay of the driven session
  (start: project init through QA pane re-render after adding the
  regression file). Replay with `asciinema play recording.cast`.
- `transcript.log` — full scrollback of the pm TUI pane, piped
  via `tmux pipe-pane` during the recording.
- `framebuffer-step5-qa-pane.txt` — `pm tui view` snapshot after
  pressing `q`, showing the three-section pane.
- `framebuffer-step7-picker-modal.txt` — `pm tui view` snapshot
  after pressing `a`, showing the picker modal.
- `framebuffer-step12-with-regression.txt` — `pm tui view` snapshot
  after adding the regression file and re-entering the pane.
- `prompt.md` — the QA scenario prompt (auto-saved by the runner).

## Notes

- Steps 10/11 (verifying the launched pane's start command for
  `author-artifact` and `author-instruction`) and step 13
  (verifying the regression prompt body) were verified during the
  scenario via `tmux list-panes -F '#{pane_id} #{pane_start_command}'`
  outside the recording window — the launched aux pane closes the
  recorder context for that frame, so the assertion lives in this
  manifest rather than in the cast.
