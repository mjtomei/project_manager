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

Write into `<capture-dir>/<short-name>/` (the scenario prompt
substitutes the actual captures directory for `<capture-dir>`):

- `recording.cast` — asciinema replay (`asciinema play recording.cast`).
- `recording.webm` — VP9 video rendered from the cast (**required**).
  This is the embeddable view: the sign-off HTML report shows it inline
  via a plain `<video controls>` element — native pause / scrub, no
  player library, works offline. The `.cast` stays as the small,
  exact-replay/grep source.
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
asciinema rec <capture-dir>/<short-name>/recording.cast \
    -c '<the-cli-command-with-args>'
```

The recording starts when the command starts, stops when it exits.
Cleanest shape — no shell prompt noise.

### Multiple commands, manually driven

```
asciinema rec <capture-dir>/<short-name>/recording.cast -c bash
# at the prompt: type each command, then `exit` to stop
```

Fine when a human is at a terminal. The recording will include the
shell prompt and any typing pauses.

### Multiple commands, scripted

```
asciinema rec <capture-dir>/<short-name>/recording.cast \
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

## Render to video

Once the cast exists, render a `.webm` sibling so the recording embeds
in the sign-off HTML report as a `<video controls>` element. `agg`
renders the cast to frames (GIF), then `ffmpeg` encodes VP9 — there is
no single cast→video tool worth using (the dedicated ones are orders of
magnitude slower and fragile). The intermediate GIF is discarded.

```
cast=<capture-dir>/<short-name>/recording.cast
agg --idle-time-limit 2 "$cast" "$cast.gif"
ffmpeg -y -i "$cast.gif" -c:v libvpx-vp9 -pix_fmt yuv444p \
    -row-mt 1 -deadline good -cpu-used 2 -b:v 0 -crf 20 \
    "${cast%.cast}.webm"
rm -f "$cast.gif"
```

Notes:
- `--idle-time-limit 2` caps the long pauses a terminal session
  accumulates, dropping dead air without losing anything worth watching.
- `yuv444p` keeps colored terminal text crisp (full-resolution chroma);
  `crf 20` is visually lossless for this content. File size is not a
  concern — the report is served locally over loopback — so favor
  quality. A long, busy session may take several minutes to encode;
  that's expected and acceptable for a rare case.

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
- `recording.webm` — <one-line description>
- `transcript.log` — <one-line description>
- `<any extra file>` — <one-line description>
```

## Reviewing

```
asciinema play recording.cast
asciinema play -i 0.3 recording.cast   # cap idle gaps for skimming
```
