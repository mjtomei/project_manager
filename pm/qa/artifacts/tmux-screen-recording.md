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

Three files per capture:

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

`asciinema rec` needs a pty and the shell driving this recipe has
none, so we run asciinema inside a tmux pane (panes have ptys). We
also need two separate tmux sessions: a **target** session running
the pm TUI, and a **recorder** session whose pane wraps
`tmux attach -t <target>` under asciinema. If the recorder lived
inside the target session, the attach client would render the
recorder pane rendering the attach client rendering the recorder
pane — endless recursion and a useless cast. Different sessions on
the same tmux server is enough to break that recursion.

```
# 1. Start the canonical pm session. `pm session` (no subcommand)
#    creates the project's pm session and attaches; with no tty the
#    attach fails noisily but the session is created either way, so
#    swallow the output.
pm session >/dev/null 2>&1 || true
TARGET=$(pm session name)             # canonical pm session name

# 2. Stream the home pane's scrollback to transcript.log.
tmux pipe-pane -t "$TARGET:0.0" -o "cat >> <capture-dir>/transcript.log"

# 3. Start the recorder session — a separate session on the same
#    tmux server whose pane runs asciinema wrapping `tmux attach -t
#    $TARGET`.
tmux new-session -d -s pm-recorder \
    "asciinema rec --quiet <capture-dir>/recording.cast \
        -c 'tmux attach -t $TARGET'"

# 4. Drive the TUI from outside via pm tui send. Keys reach the TUI
#    via the same tmux server; the recorder's attach client renders
#    the redraws; asciinema captures them.
pm tui send q -s "$TARGET"            # e.g. navigate to the QA pane
pm tui send a -s "$TARGET"            # open the picker
# ... and so on for the scenario steps ...

# 5. End the recording by detaching the recorder's attach client.
#    The attach exits, the recorded command exits, asciinema flushes
#    the cast.
tmux send-keys -t pm-recorder C-b d
tmux pipe-pane -t "$TARGET:0.0"       # stop the transcript pipe
tmux kill-session -t pm-recorder 2>/dev/null
```

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
