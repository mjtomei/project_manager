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
  is available; for TUIs the timing is invaluable).
- `manifest.md` — frontmatter + short prose: workdir path the capture
  came from, the exact commands that produced it, the pre-fix/post-fix
  state demonstrated, and any external setup the recording assumes.
  Include a `## Files` section listing every non-default file the
  capture produced with a one-line description each (the manifest is
  the index a reader uses to find what they're looking at).

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

**What to record.** asciinema records whatever the wrapped command
draws to its stdout. To capture a TUI, the wrapped command must be the
program that renders the TUI — *not* a shell into which you'll type
later. For a tmux-hosted TUI, the right wrapper is usually
`tmux attach -t <session>`: asciinema records the attach client's
render of the TUI, while you (or an external script) drive input via
`tmux send-keys` / `pm tui send` against the same session. Wrapping
`bash` and then running CLI commands inside it produces a recording of
those CLI commands, not of the TUI.

> **Trap: don't `tmux attach` to a session from inside that session.**
> If your recorder pane lives in `<session>` and you wrap
> `tmux attach -t <session>`, the inner attach client renders all of
> `<session>` — including the recorder pane itself, which is showing
> the attach client, which renders the recorder pane, and so on.
> Every redraw fan-outs through that recursion and asciinema records
> every escape sequence; expect tens of MB of nested-render churn,
> not signal. Driver keystrokes (`pm tui send` to the TUI pane) can
> also surface in the recorder pane's scrollback as the inner client
> echoes them. **Run the recorder pane in a *different* tmux server**
> (separate `-L` socket or `tmux new-session -d -s rec-$$`) **when
> the wrapped command is `tmux attach` to your target session.** For
> non-attach wrappers — recording a CLI directly inside the recorder
> pane — staying in the same session is fine.

#### No-TTY environments (e.g. automated agents)

If you're running in a no-TTY environment — typical for Claude sessions
driving the recipe via a non-interactive Bash tool — `asciinema rec`
will refuse to start. Work around it by recording **inside a tmux
pane**, since each tmux pane is backed by its own pty. Mind the
self-attach trap above: pick the variant that fits.

**Variant A — wrapping `tmux attach` (TUI capture).** Run the recorder
in a *separate* tmux server so the inner attach isn't recursive:

```
# 1. Start a scratch tmux server on its own socket for the recorder.
tmux -L rec new-session -d -s recorder

# 2. Inside that recorder server, start asciinema wrapping a tmux
#    attach into the target session on the default socket.
tmux -L rec send-keys -t recorder:0 \
    "asciinema rec <capture-dir>/recording.cast \
        -c 'tmux attach -t <target-session>'" Enter

# 3. Drive the target session from outside (the same way you would
#    from anywhere) — keys reach the TUI pane via the default-socket
#    tmux, and the attach client in the recorder records the render.
pm tui send j -s <target-session>
# ... etc ...

# 4. End the recording by detaching the attach client (the recorder
#    pane's command exits and asciinema flushes the cast).
tmux -L rec send-keys -t recorder:0 'C-b d'
```

**Variant B — wrapping a non-attach command (CLI / scripted capture).**
Same session is fine; no recursion possible:

```
# 1. Open a fresh pane in the existing tmux session and start recording
tmux split-window -t <session>:<window>
tmux send-keys   -t <session>:<window>.<recorder-pane> \
    "asciinema rec <capture-dir>/recording.cast \
        -c '<command-to-record>'" Enter

# 2. Drive the recorded program from outside (no TTY needed for the driver)
#    — `tmux send-keys` to the recorder pane, or any IPC the program
#    exposes.

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

## Files

- `transcript.log` — <one-line description>
- `recording.cast` — <one-line description>
- `<any extra file>` — <one-line description>
```

When a single scenario captures **both** pre-fix and post-fix states
(it found and fixed a bug along the way), use sub-subdirs
`pre-fix/` and `post-fix/` under the scenario's capture dir, each
with its own `transcript.log` + `recording.cast` + `manifest.md`.
Cross-link them in the `## Files` section of each manifest.

## Reviewing a capture

Reviewers replay with `asciinema play <file>.cast` or read
`transcript.log` directly. The manifest tells them what they're looking
at without re-deriving it from code.
