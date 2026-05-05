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

If `asciinema` is not installed, note it in the manifest and skip the
`.cast` file — the transcript is the minimum bar.

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
