---
title: tmux Screen Recording
description: Capture a tmux pane transcript and an asciinema replay for review
tags: [artifact, tmux, recording]
---

## When to use

A scenario produces user-visible behavior a reviewer needs to see —
visual TUI changes, new CLI output, an interactive flow — and you can't
fully express it in a unit test.

## What this recipe produces

For each capture, write three files into
`pm/qa/captures/<pr-id>/<short-name>/`:

- `transcript.log` — plain-text scrollback of the pane.
- `recording.cast` — asciinema replay (optional but preferred for TUIs).
- `manifest.md` — frontmatter + short prose: workdir path the capture
  came from, the exact commands that produced it, the pre-fix/post-fix
  state demonstrated, and any external setup the recording assumes.

## Capture commands

### tmux pipe-pane (always available if you have tmux)

```
mkdir -p pm/qa/captures/<pr-id>/<short-name>
tmux pipe-pane -t <session>:<window>.<pane> -o \
    'cat >> pm/qa/captures/<pr-id>/<short-name>/transcript.log'
# ... reproduce the behavior in the pane ...
tmux pipe-pane -t <session>:<window>.<pane>      # stop piping
```

### asciinema (replayable)

```
asciinema rec pm/qa/captures/<pr-id>/<short-name>/recording.cast \
    -c '<command-or-shell-that-reproduces-the-behavior>'
```

`asciinema rec` requires a TTY. If your shell has one (you're running
this from a terminal), the line above is all you need.

#### No-TTY environments (e.g. automated agents)

If you're running in a no-TTY environment — typical for Claude sessions
driving the recipe via a non-interactive Bash tool — `asciinema rec`
will refuse to start. Work around it by recording **inside a tmux
pane**, since each tmux pane is backed by its own pty:

```
# 1. Open a fresh pane in the existing tmux session and start recording
tmux split-window -t <session>:<window>
tmux send-keys   -t <session>:<window>.<recorder-pane> \
    "asciinema rec <capture-dir>/recording.cast \
        -c '<command-to-record>'" Enter

# 2. Drive the recorded program from outside (no TTY needed for the driver)
#    For a TUI under tmux, this is `tmux send-keys` to the recorded pane,
#    or any equivalent IPC the program exposes.

# 3. End the recording: have the recorded command exit, e.g.
tmux send-keys -t <session>:<window>.<recorder-pane> "exit" Enter
# asciinema flushes recording.cast on the recorded process exiting.
```

If `asciinema` isn't installed and can't be installed, note it in the
manifest and skip the `.cast` file — the `transcript.log` from
`pipe-pane` is the minimum bar.

## Manifest format

```
---
pr: <pr-id>
workdir: <absolute path>
captured_at: <ISO date>
---

## Commands

```
<commands run, copy-pasteable>
```

## What this demonstrates

<one paragraph>

## Pre-fix vs post-fix

<note which state the capture is from; if both, name both files>
```

## Reviewing a capture

Reviewers replay with `asciinema play <file>.cast` or read
`transcript.log` directly. The manifest tells them what they're looking
at without re-deriving it from code.
