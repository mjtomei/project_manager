---
pr: pr-6be8ee6
workdir: /workspace
test_project: /workspace/pm-test-1777985423
tmux_session: pm-pm-test-1777985423-f08371ae
captured_at: 2026-05-05
recipe: pm/qa/artifacts/tmux-screen-recording.md
---

## Commands

This run uses the **no-TTY workaround** added to the recipe in this PR:
asciinema runs *inside a tmux pane* (which has its own pty), driven by
`tmux send-keys` from the no-TTY Bash tool.

```
SESSION=pm-pm-test-1777985423-f08371ae
CAPDIR=pm/qa/captures/pr-6be8ee6/tui-walkthrough-v2

# 1. Open a fresh recorder pane in window 0
tmux split-window -t "$SESSION":0 -v
# (recorder lands at pane index 2 in this layout)

# 2. Set up env in the recorder pane and start asciinema
tmux send-keys -t "$SESSION":0.2 \
    "source /tmp/pm-venv/bin/activate && export PYTHONPATH=/workspace \
        && export PATH=\$HOME/.local/bin:\$PATH \
        && cd /workspace/pm-test-1777985423 && clear" Enter
tmux send-keys -t "$SESSION":0.2 \
    "asciinema rec --quiet --overwrite $CAPDIR/recording.cast -c bash" Enter

# 3. Drive pm CLI commands into the recorded shell
tmux send-keys -t "$SESSION":0.2 \
    "source /tmp/pm-venv/bin/activate && export PYTHONPATH=/workspace \
        && cd /workspace/pm-test-1777985423" Enter
tmux send-keys -t "$SESSION":0.2 "pm pr list" Enter
tmux send-keys -t "$SESSION":0.2 "pm pr note list pr-95325c4" Enter
tmux send-keys -t "$SESSION":0.2 \
    "pm pr note add pr-95325c4 'recorded via asciinema-in-tmux'" Enter
tmux send-keys -t "$SESSION":0.2 "pm pr note list pr-95325c4" Enter
tmux send-keys -t "$SESSION":0.2 "pm plan list" Enter

# 4. Stop: exit the inner bash; asciinema flushes the cast on EOF
tmux send-keys -t "$SESSION":0.2 "exit" Enter
```

## What this demonstrates

`recording.cast` is a real asciicast v2 recording: 20 events,
~23 seconds, valid timestamps. Replay with:

```
asciinema play recording.cast
```

The recording shows, in order:
- `pm pr list` — the four PRs in the test project with the dependency chain.
- `pm pr note list pr-95325c4` — one prior note from an earlier walkthrough.
- `pm pr note add pr-95325c4 'recorded via asciinema-in-tmux'` — adding a fresh note.
- `pm pr note list pr-95325c4` — confirms the new note appended.
- `pm plan list` — empty (test project has no plans).

`screens/00-tui-startup.txt` is a one-shot framebuffer of the TUI pane
captured via `pm tui view` for context — the recording itself does not
include the TUI window since the recorded shell is in a separate pane.

## Pre-fix vs post-fix

Post-fix only (this PR doesn't fix a regression — it adds plumbing).
The recording exists to prove the no-TTY workaround in the recipe
actually produces a valid `.cast` file from this environment.

## Why a fresh capture dir

The earlier `tui-walkthrough/` capture used the transcript-only
fallback because asciinema wasn't installed yet. Once installed, this
v2 capture exercised the asciinema-in-tmux path the recipe now
documents. Both directories are kept so a reviewer can compare the two
fallbacks the recipe describes.
