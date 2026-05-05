---
title: CLI Recording
description: Capture an asciinema replay of one or more CLI commands
tags: [artifact, cli, recording]
---

## When to use

A scenario demonstrates a command-line interaction — argument
handling, stdout/stderr, multi-step CLI sequences — that's worth
showing as an animation rather than a static log. Use this recipe
when there's no TUI involved; for tmux-hosted TUIs, use
`tmux-screen-recording.md`.

## What this recipe produces

Write into `pm/qa/captures/<pr-id>/<short-name>/`:

- `recording.cast` — asciinema replay (`asciinema play recording.cast`).
- `manifest.md` — frontmatter + prose: workdir, the exact command(s)
  recorded, what the recording demonstrates, pre/post-fix state if
  relevant.
- (optional) `transcript.log` — plain-text version, if a reviewer
  can't run asciinema.

## Capture

### One command, end-to-end

```
asciinema rec pm/qa/captures/<pr-id>/<short-name>/recording.cast \
    -c '<the-cli-command-with-args>'
```

The recording starts when the command starts, stops when it exits.
Cleanest shape — no shell prompt noise.

### Multiple commands, manually driven

```
asciinema rec pm/qa/captures/<pr-id>/<short-name>/recording.cast -c bash
# at the prompt: type each command, then `exit` to stop
```

Fine when a human is at a terminal. The recording will include the
shell prompt and any typing pauses.

### Multiple commands, scripted

```
asciinema rec pm/qa/captures/<pr-id>/<short-name>/recording.cast \
    -c 'bash -c "set -x; cmd-one; cmd-two; cmd-three"'
```

`set -x` echoes each command before it runs so a reviewer can read
along. No shell prompt, no manual driving.

### No-TTY environments (e.g. automated agents)

Same workaround as the tmux-screen-recording recipe: asciinema needs
a TTY, so run it inside a tmux pane (which has one). Unlike a TUI
capture, you do **not** need a `tmux attach` — the pane itself is
where the CLI runs.

```
# 1. Scaffold tmux on its own socket and open one pane.
tmux -L scaffold new-session -d -s rec -x 100 -y 30

# 2. Start asciinema in the pane, wrapping whichever command form
#    fits from above (one command, bash + manual, or bash -c script).
tmux -L scaffold send-keys -t rec:0.0 \
    "asciinema rec --quiet --overwrite <capture-dir>/recording.cast \
        -c '<command-to-record>'" Enter

# 3. If you wrapped `bash`, drive it from outside via tmux send-keys
#    on the same scaffold socket; if you wrapped a single command or
#    a `bash -c` script, just wait for it to finish.

# 4. Stop: have the recorded process exit (it'll flush the cast),
#    or `pkill -TERM -f 'asciinema rec.*<capture-dir>'`.
tmux -L scaffold kill-server   # cleanup
```

If `asciinema` isn't installed and can't be installed, fall back to
appending `| tee transcript.log` to the command line — you lose
animation but keep the output. Note the fallback in the manifest.

## Manifest format

```
---
pr: <pr-id>
workdir: <absolute path>
captured_at: <ISO date>
recipe: pm/qa/artifacts/cli-recording.md
---

## Commands

```
<copy-pasteable command(s) recorded>
```

## What this demonstrates

<one paragraph: which behavior is shown, what to look for in playback>

## Pre-fix vs post-fix

<which state the capture is from; if both, name both files>
```

## Reviewing

```
asciinema play recording.cast
asciinema play -i 0.3 recording.cast   # cap idle gaps for skimming
```
