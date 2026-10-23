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

Once the cast exists, render a `.mp4` sibling so the recording embeds
in the sign-off HTML report as a `<video controls>` element. `agg`
renders the cast to frames (GIF), then `ffmpeg` encodes H.264 — there is
no single cast→video tool worth using (the dedicated ones are orders of
magnitude slower and fragile). The cast is the immutable source: never
edit or re-record it to fix a render.

```
# render_cast <cast>: <cast> -> sibling recording.mp4 (variable frame rate).
# Returns non-zero, and publishes no new recording.mp4, if any step fails
# (an older completed recording.mp4 is left as it was).
render_cast() {
    local cast=$1 gif="$1.gif" mp4="${1%.cast}.mp4"
    local part="$mp4.partial.mp4" vf gw gh n dur
    rm -f "$gif" "$part"
    agg --idle-time-limit 2 "$cast" "$gif" \
        || { echo "render_cast: agg failed for $cast" >&2; return 1; }
    # 2x nearest-neighbor upscale for crisp text — but only while the result
    # stays within iOS hardware-decode limits (4096x2304, H.264 level 5.1).
    # A terminal large enough to blow that budget is already crisp at native
    # size; then just round dimensions down to even (H.264 requires even).
    vf="scale=trunc(iw/2)*2:trunc(ih/2)*2"
    IFS=, read -r gw gh < <(ffprobe -v error -select_streams v:0 \
        -show_entries stream=width,height -of csv=p=0 "$gif")
    if [ -n "$gw" ] && [ -n "$gh" ] && \
       [ "$((gw * 2))" -le 4096 ] && [ "$((gh * 2))" -le 2304 ]; then
        vf="scale=iw*2:ih*2:flags=neighbor"
    fi
    # Hold the final screen: clone the last frame and place the clone at
    # the GIF's total duration (a VFR encode otherwise ends the video
    # when the last frame starts, dropping its hold).
    n=$(ffprobe -v error -count_packets -select_streams v:0 \
        -show_entries stream=nb_read_packets -of csv=p=0 "$gif")
    dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$gif")
    [ -n "$n" ] && [ -n "$dur" ] \
        || { echo "render_cast: cannot probe $gif" >&2; return 1; }
    vf="tpad=stop=1:stop_mode=clone,setpts='if(eq(N\,$n)\,$dur/TB\,PTS)',$vf"
    if ffmpeg -loglevel error -y -i "$gif" -vf "$vf" \
           -vsync vfr -enc_time_base 1/100 -video_track_timescale 100 \
           -c:v libx264 -profile:v high -level:v 5.1 -pix_fmt yuv420p \
           -crf 18 -movflags +faststart "$part" && [ -s "$part" ]; then
        mv -f "$part" "$mp4" && rm -f "$gif"
    else
        echo "render_cast: ffmpeg failed for $cast;" \
             "kept $gif (and any $part) for diagnosis" >&2
        return 1
    fi
}
render_cast "<capture-dir>/<short-name>/recording.cast" || echo "RENDER FAILED: do not publish this capture yet"
```

Notes:
- `--idle-time-limit 2` caps the long pauses a terminal session accumulates,
  dropping dead air without losing anything worth watching.
- **Variable frame rate.** agg already merges identical screens into one
  GIF frame with a long delay. `-vsync vfr` keeps those delays as frame
  durations instead of padding them out to a constant rate. That padding
  re-encoded thousands of identical frames: on 33-53 minute TUI casts the
  constant-rate encode ran for more than 10 minutes at about 900% CPU,
  while the VFR render finished in about 2 minutes. `-enc_time_base 1/100`
  and `-video_track_timescale 100` give the GIF's centisecond delays an
  exact timebase. Without them, the GIF's coarse frame rate becomes the
  timebase and VFR merges neighbouring frames. (`-vsync` is spelled
  `-fps_mode` in ffmpeg 5.1+, which still accepts `-vsync`.)
- **Check the render:** the cloned final frame starts at the GIF's
  duration, so the mp4 runs that long plus one frame tick (for example
  5.34 s for a 5.30 s GIF). Its frame count is the GIF's plus one:
  `ffprobe -v error -show_entries format=duration -of csv=p=0 recording.mp4`
  and `ffprobe -v error -count_packets -select_streams v:0 -show_entries
  stream=nb_read_packets -of csv=p=0 recording.mp4`.
- **Partial output is never published.** ffmpeg writes to
  `recording.mp4.partial.mp4`, which is renamed to `recording.mp4` only
  after a successful encode. The GIF is deleted only after that rename.
  An interrupted or failed render therefore publishes no new
  `recording.mp4`; an older completed `recording.mp4` from an earlier
  render stays in place (do not delete it). So neither the file
  existing nor the GIF disappearing shows that this render succeeded:
  check this `render_cast` call's return status. If you stop a render
  on purpose, stop the shell running `render_cast` before its `ffmpeg`
  child, so the cleanup step cannot run. Label any partial output you keep (for example
  `recording.mp4.INCOMPLETE-...`) and list it in the manifest.
- **Video time is compressed pause time, not wall time.** Each gap
  between cast output events is capped at 2 s, so to find the video
  frame for a wall-clock instant, sum `min(gap, 2)` over the output
  events up to that instant (cast timestamps are seconds from the
  header's `timestamp`). Extract the frame on display at video time `vt`
  with `ffmpeg -i recording.mp4 -vf "select='lte(t\,vt)'" -vsync 0
  -update 1 frame.png`, which keeps the last frame starting at or before
  `vt`. On a sparse VFR video, input seeking with `-ss vt` returns the
  NEXT frame instead. Check a key frame's text against the cast replayed
  to the same instant (for example with `pyte`) before citing it.
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
