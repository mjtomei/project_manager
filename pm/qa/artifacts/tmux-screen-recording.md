---
title: tmux Screen Recording
description: Capture a tmux pane transcript and an asciinema replay of a pm TUI session
---

## When to use

A scenario produces behavior worth confirming end-to-end through the
pm TUI — a keybinding, a pane render, a flow you'd normally drive by
hand — and you want unambiguous evidence of what happened, consumable
by humans (replay) and downstream agents (parse the transcript or
cast).

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

## Why two tmux sessions

`asciinema rec` needs a pty. The shell driving this recipe usually has
no tty (Claude's non-interactive Bash tool, CI runners, etc.), so
running asciinema there fails. Every tmux pane *does* have a pty, so
the workaround is to run asciinema inside a tmux pane.

That gives us two sessions, not one:

- **target session** — runs `pm tui` (or whichever pm command the
  scenario exercises). This is the thing being recorded.
- **recorder session** — runs `asciinema rec` wrapping
  `tmux attach -t <target>`. Its only job is to host the attach
  client whose render asciinema captures.

Why a *separate* session for the recorder? Because if the recorder
pane lives in the target session and you wrap `tmux attach -t <target>`
inside it, the attach client renders the whole target session —
including the recorder pane, which is showing the attach client, which
renders the recorder pane, and so on. asciinema records the runaway
nested redraw and you get tens of MB of noise.

Putting the recorder in its own session breaks the recursion: the
attach renders only the target session's panes, which doesn't contain
the recorder. A single tmux server is fine; the constraint is
different *sessions*, not different sockets.

## Capture

```
# 1. Start the target session running pm tui (or whichever pm command
#    the scenario drives). -d detaches so this shell returns.
tmux new-session -d -s pm-target -x 120 -y 40 'pm tui'

# 2. Stream the target pane's scrollback to transcript.log.
tmux pipe-pane -t pm-target -o "cat >> <capture-dir>/transcript.log"

# 3. Start a *separate* recorder session whose pane runs asciinema
#    wrapping `tmux attach -t pm-target`. Same tmux server, different
#    session — so the attach isn't recursive.
tmux new-session -d -s pm-recorder -x 120 -y 40 \
    "asciinema rec --quiet <capture-dir>/recording.cast \
        -c 'tmux attach -t pm-target'"

# 4. Drive the TUI from outside via pm tui send (or tmux send-keys
#    against pm-target). Keys reach pm tui via the same tmux server;
#    the recorder's attach client renders the redraws; asciinema
#    captures them.
pm tui send q -s pm-target            # navigate to the QA pane
pm tui send a -s pm-target            # open the picker
# ... and so on for the scenario steps ...

# 5. End the recording. Quit pm tui (or detach the recorder's attach
#    client). The attach exits, asciinema flushes the cast.
pm tui send :q -s pm-target           # or whichever quit command
tmux pipe-pane -t pm-target           # stop the transcript pipe
tmux kill-session -t pm-recorder 2>/dev/null
tmux kill-session -t pm-target 2>/dev/null
```

**Do not** wrap `tmux capture-pane` with `asciinema rec -c` as a
fallback: that records a one-shot static snapshot of the final
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
