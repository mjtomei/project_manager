---
title: CLI Recording
description: Capture an asciinema replay of one or more CLI commands
---

## When to use

A scenario demonstrates a command-line interaction — argument
handling, stdout/stderr, multi-step CLI sequences — and you want
unambiguous evidence of what happened, consumable by humans (replay)
and downstream agents (parse the cast). Use this recipe
when there's no TUI involved; for tmux-hosted TUIs, use
`tmux-screen-recording.md`.

## What this recipe produces

Write into `<capture-dir>/<short-name>/` (the scenario prompt
substitutes the actual captures directory for `<capture-dir>`):

- `recording.cast` — asciinema replay (`asciinema play recording.cast`).
- `recording.mp4` — H.264 video rendered from the cast (**required**).
  This is the embeddable view: the sign-off HTML report shows it inline
  via a plain `<video controls>` element — native pause / scrub, no
  player library, works offline. H.264/mp4 plays everywhere including
  iOS Safari (VP8/VP9 webm does not decode on iOS). The `.cast` stays
  as the small, exact-replay/grep source.
- `manifest.md` — frontmatter + prose: workdir, the exact command(s)
  recorded, what the recording demonstrates, pre/post-fix state if
  relevant. Include a `## Files` section listing every non-default
  file the capture produced with a one-line description each.

## Capture

Before any of the forms below, create the capture directory and clear an
earlier run's cast:

```
mkdir -p <capture-dir>/<short-name>
rm -f <capture-dir>/<short-name>/recording.cast
```

`asciinema rec` reports "asciicast saved" and exits 0 even when the
directory does not exist, so a missing `mkdir` looks like a successful
capture that wrote nothing — and a leftover cast is worse: without
`--overwrite` the recorder aborts on it, and the render step rewrites the
`.mp4` from whatever cast is on disk, so a run that recorded nothing would
still produce a fresh-looking video of the *previous* run. The no-TTY
scaffold repeats both steps, and also clears a `rec` session an earlier run
left behind: a leftover one makes `new-session` fail with "duplicate
session: rec" and the readiness wait would then pass on the previous run's
recorder.

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
# 1. Scaffold tmux on its own socket and start the recorder as the pane's
#    command, so the pane's lifetime *is* the recording's lifetime: when
#    asciinema exits, the session ends and step 4's wait can see it. The
#    capture subdirectory has to exist (and hold no earlier cast) before
#    asciinema writes into it. Clear a leftover `rec` session from an
#    aborted run first — `new-session` fails with "duplicate session: rec"
#    while it exists — with `kill-session`, not `kill-server`: killing the
#    server and reconnecting immediately races its exit ("server exited
#    unexpectedly"). <command-to-record> sits inside single quotes that are
#    themselves inside the outer double-quoted argument, so a command with
#    quotes of its own has to be escaped to survive both layers: for the
#    `bash -c` form above, paste
#        -c 'bash -c \"set -x; cmd-one; cmd-two\"'
#    and note the outer shell expands `$` in it before asciinema sees it.
#    Pasting the double-quoted form unescaped ends the outer string, so
#    asciinema gets a broken command, exits, and step 4 reports "asciinema
#    wrote no cast".
tmux -L scaffold kill-session -t rec 2>/dev/null || true
mkdir -p <capture-dir>/<short-name>
rm -f <capture-dir>/<short-name>/recording.cast
tmux -L scaffold new-session -d -s rec -x 100 -y 30 \
    "asciinema rec --quiet --overwrite <capture-dir>/<short-name>/recording.cast \
        -c '<command-to-record>'"

# 2. Wait (bounded) for the recorder to start before any keys go in:
#    keystrokes sent before asciinema has attached to the pane are silently
#    lost, so an immediate `exit` leaves it recording. The cast is the
#    handle — asciinema writes its header the moment it starts recording, so
#    a non-empty cast means the pty is live and keys will land. Pane content
#    is *not* a readiness signal here: a command that prints nothing for a
#    while (a long run, a quiet `-q` command) is recording fine with a blank
#    pane. A quick one-shot command can finish first — then the session is
#    already gone and there is nothing left to drive.
deadline=$(( $(date +%s) + 30 ))
until [ -s <capture-dir>/<short-name>/recording.cast ] ||
      ! tmux -L scaffold has-session -t rec 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "recorder did not start within 30s — check the pane with" \
            "'tmux -L scaffold capture-pane -p -t rec'" >&2
        tmux -L scaffold kill-server 2>/dev/null
        exit 1
    fi
    sleep 0.2
done

# 3. Drive the recorded command from outside on the same scaffold socket,
#    e.g.:
#      tmux -L scaffold send-keys -t rec:0.0 'pm --version' Enter
#      tmux -L scaffold send-keys -t rec:0.0 'exit' Enter
#    An interactive `bash` needs that final `exit` — it is what ends the
#    recording. Ctrl-C is forwarded to the recorded command, not to
#    asciinema, so it does not stop the recording, and tearing the pane
#    down first can leave a truncated cast. A single command or a
#    `bash -c` script needs no driving at all.

# 4. Wait (bounded) for asciinema to exit — the pane *is* the recording, so
#    the session ending is the completion signal — then confirm the cast is
#    there and non-empty. For a one-shot command that legitimately runs
#    longer than the default bound, raise RECORDER_STOP_TIMEOUT (seconds):
#    prefix this block with RECORDER_STOP_TIMEOUT=120 (the variable does not
#    survive a separate shell invocation, so set it in the same call). The
#    bound is a hang detector, not a time limit on the recorded work, and
#    killing a healthy recording loses the evidence.
stop_timeout=${RECORDER_STOP_TIMEOUT:-30}
deadline=$(( $(date +%s) + stop_timeout ))
while tmux -L scaffold has-session -t rec 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "recorder did not exit within ${stop_timeout}s — for a longer" \
            "command set RECORDER_STOP_TIMEOUT; an interactive recording" \
            "needs 'exit' in the recorded shell (step 3); check the pane with" \
            "'tmux -L scaffold capture-pane -p -t rec'" >&2
        tmux -L scaffold kill-server 2>/dev/null
        exit 1
    fi
    sleep 0.2
done
test -s <capture-dir>/<short-name>/recording.cast || {
    echo "asciinema wrote no cast — check the pane output" >&2
    tmux -L scaffold kill-server 2>/dev/null   # do not leave `rec` behind
    exit 1
}
tmux -L scaffold kill-server 2>/dev/null || true   # cleanup
```

If `asciinema` isn't installed and can't be installed, fall back to
appending `| tee transcript.log` to the command line — you lose
animation but keep the output. Note the fallback in the manifest.

## Render to video

Once the cast exists, render a `.mp4` sibling so the recording embeds
in the sign-off HTML report as a `<video controls>` element. `agg`
renders the cast to frames (GIF), then `ffmpeg` encodes H.264 — there is
no single cast→video tool worth using (the dedicated ones are orders of
magnitude slower and fragile). The intermediate GIF is discarded.

Two tools do the two stages. The QA image ships `ffmpeg` but **not**
`agg`, and the block below fails instead of leaving a missing or stale
video — so install `agg` first when `command -v agg` prints nothing
(`~/.local/bin` is on `PATH` in the image; the asset is per architecture,
verified with agg 1.9.0):

```
curl -fsSL \
    https://github.com/asciinema/agg/releases/latest/download/agg-$(uname -m)-unknown-linux-gnu \
    -o ~/.local/bin/agg && chmod +x ~/.local/bin/agg
```

Don't substitute a different renderer: the mp4 is the required artifact.

```
cast=<capture-dir>/<short-name>/recording.cast
# Remove this run's outputs before rendering: a failed render (no `agg`, an
# unreadable cast, an ffmpeg error) then ends with *no* mp4, instead of
# leaving the previous run's video in the capture directory — which the
# manifest and the report would present as this run's evidence. The gif goes
# too, so a failed `agg` cannot fall back to encoding an earlier one.
rm -f "${cast%.cast}.mp4" "$cast.gif"
agg --idle-time-limit 2 "$cast" "$cast.gif"
# 2x nearest-neighbor upscale for crisp text — but only while the result
# stays within iOS hardware-decode limits (4096x2304, H.264 level 5.1).
# A terminal large enough to blow that budget is already crisp at native
# size; then just round dimensions down to even (H.264 requires even).
vf="scale=trunc(iw/2)*2:trunc(ih/2)*2"
IFS=, read -r gw gh < <(ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height -of csv=p=0 "$cast.gif")
if [ -n "$gw" ] && [ -n "$gh" ] && \
   [ "$((gw * 2))" -le 4096 ] && [ "$((gh * 2))" -le 2304 ]; then
    vf="scale=iw*2:ih*2:flags=neighbor"
fi
ffmpeg -y -i "$cast.gif" -vf "$vf" \
    -c:v libx264 -profile:v high -level:v 5.1 -pix_fmt yuv420p -crf 18 \
    -movflags +faststart "${cast%.cast}.mp4"
rm -f "$cast.gif"
# The mp4 is the required artifact: fail here, visibly, rather than leaving
# the caller to notice the video is missing (or stale) later.
test -s "${cast%.cast}.mp4" || {
    echo "render produced no mp4 — check 'agg' is installed and the cast is" \
        "readable" >&2
    exit 1
}
```

Notes:
- `--idle-time-limit 2` caps the long pauses a terminal session
  accumulates, dropping dead air without losing anything worth watching.
- H.264 + `yuv420p` is the only combination that decodes everywhere,
  including iOS Safari (VP8/VP9 webm and 4:4:4 chroma do not). 4:2:0
  chroma subsampling would blur colored terminal text at native size,
  so the nearest-neighbor upscale renders at 2x — crisp text, and the
  doubling guarantees the even dimensions H.264 requires. The size
  guard matters: an unconditional 2x on a large terminal produces a
  video past level 5.1 (e.g. 4276x2284), which desktop browsers play
  but iPhone/iPad hardware decoders silently refuse. `crf 18` is
  visually lossless for this content; favor
  quality — file size is not a concern. `-movflags +faststart` puts the
  moov atom up front so playback starts before the full download.
  A long, busy session may take several minutes to encode; that's
  expected and acceptable for a rare case.

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
- `recording.mp4` — <one-line description>
- `<any extra file>` — <one-line description>
```

## Reviewing

```
asciinema play recording.cast
asciinema play -i 0.3 recording.cast   # cap idle gaps for skimming
```
