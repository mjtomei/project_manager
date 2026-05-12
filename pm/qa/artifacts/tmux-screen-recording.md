---
title: tmux Screen Recording
description: Capture a tmux pane transcript and an asciinema replay
---

## When to use

A scenario produces behavior worth confirming end-to-end — a TUI
interaction, a CLI session, an interactive flow — and you want
unambiguous evidence of what happened, consumable by humans (replay)
and downstream agents (parse the transcript or cast).

## What this recipe produces

For each capture, write three files into
`pm/qa/captures/<pr-id>/<short-name>/`:

- `transcript.log` — plain-text scrollback of the pane (**required** —
  the load-bearing artifact for grep/diff and for consumers without
  asciinema).
- `recording.cast` — asciinema replay (**required** when `asciinema`
  is available).
- `manifest.md` — frontmatter + short prose: workdir path the capture
  came from, the exact commands that produced it, the pre-fix/post-fix
  state demonstrated, and any external setup the recording assumes.
  Include a `## Files` section listing every non-default file the
  capture produced with a one-line description each.

## Capture

The recorder lives in its own tmux session and wraps `tmux attach`
into the target session. You drive the target from outside via
`tmux send-keys` (or `pm tui send`); the recording captures the
attach client's render, so every keystroke's effect on the TUI
appears in the cast just as if a human had typed into an attached
client.

```
# 1. Start the target session running the program under test (your
#    TUI, your CLI, whatever the scenario exercises).
tmux new-session -d -s target -x 80 -y 24 '<command-under-test>'

# 2. Start a recorder session whose only job is to run asciinema
#    wrapping `tmux attach` into the target. Same tmux server is fine
#    — recorder and target are different sessions, so the attach
#    isn't recursive.
mkdir -p pm/qa/captures/<pr-id>/<short-name>
tmux new-session -d -s recorder -x 80 -y 24 \
    "asciinema rec --quiet pm/qa/captures/<pr-id>/<short-name>/recording.cast \
        -c 'tmux attach -t target'"

# 3. Drive the target from outside. Keys reach the program via the
#    same tmux server; the recorder's attach client renders the
#    redraws and asciinema records them.
tmux send-keys -t target "j" Enter
# ...

# 4. End the recording: cause the target to exit (or detach the
#    recorder's attach client with C-b d). The attach exits, the
#    recorded command exits, asciinema flushes the cast.
tmux send-keys -t target C-d

# 5. Capture the plain-text transcript alongside (pipe-pane is the
#    cheapest way; run it from step 1 if you want the full session).
tmux pipe-pane -t target -o \
    'cat >> pm/qa/captures/<pr-id>/<short-name>/transcript.log'
```

If `asciinema` isn't installed and can't be installed, or the
recorder session can't be created in this environment, note it in
the manifest and skip the `.cast` — `transcript.log` is the
minimum bar. **Do not** wrap `tmux capture-pane` with `asciinema rec -c`
as a fallback: that records a one-shot static snapshot of the final
buffer, not the interaction, and a stub cast is worse than no cast.

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

## Files

- `transcript.log` — <one-line description>
- `recording.cast` — <one-line description>
- `<any extra file>` — <one-line description>
```

## Reviewing

Reviewers replay with `asciinema play <file>.cast` or read
`transcript.log` directly. The manifest tells them what they're looking
at without re-deriving it from code.
