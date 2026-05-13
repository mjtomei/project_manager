---
title: CLI Recording
description: Capture an asciinema replay of one or more CLI commands
---

## When to use

A scenario demonstrates a command-line interaction — argument
handling, stdout/stderr, multi-step CLI sequences — and you want
unambiguous evidence of what happened, consumable by humans (replay)
and downstream agents (parse the cast or transcript). Use this recipe
when there's no TUI involved; for tmux-hosted TUIs, use
`tmux-screen-recording.md`.

## What this recipe produces

Write into `pm/qa/captures/<pr-id>/<short-name>/`:

- `recording.cast` — asciinema replay (`asciinema play recording.cast`).
- `transcript.log` — plain-text version of the same run (**required** —
  the load-bearing artifact for grep/diff and for consumers without
  asciinema; the cast is supplementary).
- `manifest.md` — frontmatter + prose: workdir, the exact command(s)
  recorded, what the recording demonstrates, pre/post-fix state if
  relevant. Include a `## Files` section listing every non-default
  file the capture produced with a one-line description each.

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

`set -x` echoes each command before it runs so the recording (and
any downstream parser) sees each command alongside its output. No
shell prompt, no manual driving.

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

#### Gotcha: `pm session` inside the recorded pane

If the scripted commands need to (re)start a pm tmux session — e.g.
to exercise the missing-session error path and then resume normal
flow — invoking `pm session` directly will hang the recording. `pm
session` creates the session and then tries to attach; attaching from
inside the scaffold pane stalls in a non-interactive context, and
`2>/dev/null || true` only swallows the error, not the wait.

Background the **sub-shell**, not `pm session` itself, so the attach
detaches from the script's control flow and a short wait closes the
race before the next command runs:

```
( pm session >/dev/null 2>&1 ) &
until tmux ls 2>/dev/null | grep -q '^pm-'; do sleep 0.2; done
```

`pm session &` (without the subshell) also unblocks the script but
leaves a foreground job-control marker in the recording; the subshell
form keeps the cast clean.

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

## Files

- `recording.cast` — <one-line description>
- `transcript.log` — <one-line description>
- `<any extra file>` — <one-line description>
```

## Reviewing

```
asciinema play recording.cast
asciinema play -i 0.3 recording.cast   # cap idle gaps for skimming
```
