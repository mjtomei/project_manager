---
pr: pr-6be8ee6
workdir: /workspace
test_project: /workspace/pm-test-1777985423
tmux_session: pm-pm-test-1777985423-f08371ae
captured_at: 2026-05-05
recipe: pm/qa/artifacts/tmux-screen-recording.md
---

## Commands

This is the no-TTY workaround from the recipe, applied correctly: a
**scaffold tmux server on a separate socket** hosts the asciinema
recorder pane, and the recorded process is `tmux -L default attach`
into the actual pm session. Two separate tmux servers means no
self-attach loop.

```
PM_SESSION=pm-pm-test-1777985423-f08371ae
CAPDIR=pm/qa/captures/pr-6be8ee6/impl/tui-walkthrough-v3

# 1. Scaffold tmux on its own socket — its only job is to host a pty
#    that asciinema can record inside.
tmux -L scaffold new-session -d -s rec -x 100 -y 30

# 2. Start asciinema in the scaffold pane, recording a `tmux attach` to
#    the pm session on the *default* socket. -L default + unset TMUX so
#    the inner attach doesn't inherit the scaffold socket.
tmux -L scaffold send-keys -t rec:0.0 \
    "unset TMUX; asciinema rec --quiet --overwrite $CAPDIR/recording.cast \
        -c 'tmux -L default attach -t $PM_SESSION'" Enter

# 3. Make the TUI pane active and zoom it so the attach client renders
#    a clean, full-pane TUI.
tmux select-pane -t "$PM_SESSION":0.0
tmux resize-pane -t "$PM_SESSION":0.0 -Z

# 4. Drive the TUI from outside via pm tui send. These keystrokes go to
#    the TUI pane on the default socket; asciinema records the rendered
#    frames the attach client receives.
for k in j k j j k j; do pm tui send "$k" -s "$PM_SESSION"; sleep 0.4; done
pm tui send '/'      -s "$PM_SESSION"; sleep 0.5
pm tui send escape   -s "$PM_SESSION"; sleep 0.5

# 5. Stop: kill the asciinema rec process; it flushes the cast on SIGTERM.
pkill -TERM -f 'asciinema rec.*tui-walkthrough-v3' || true
```

## What this demonstrates

`recording.cast` is a real asciicast v2 file, 39 events, ~38 seconds,
containing the TUI's actual escape-sequence stream — text-positioning
codes, PR-card borders, the "Project: pm-test-1777985423    4 PRs"
header, the four PR boxes with selection moving as keys are sent.

Replay with:
```
asciinema play recording.cast
# faster:
asciinema play -i 0.3 recording.cast
```

`screens/00-tui-final.txt` is a one-shot framebuffer of the TUI pane
captured via `pm tui view` after the keystroke sequence finished, for
quick eyeballing without a player.

## Pre-fix vs post-fix

Post-fix only (this PR adds plumbing, doesn't fix a regression).

## Why a v3 directory

- `tui-walkthrough/` (v1): transcript-only fallback (asciinema not yet
  installed). Captured the TUI byte stream via `tmux pipe-pane`.
- (`tui-walkthrough-v2/` was deleted — it was a shell-session
  recording, not the TUI, so it didn't demonstrate what the recipe is
  meant for.)
- `tui-walkthrough-v3/` (this dir): real asciinema cast of the TUI,
  produced via the no-TTY workaround the recipe now documents.
