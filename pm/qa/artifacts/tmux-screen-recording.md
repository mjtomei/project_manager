---
title: tmux Screen Recording
description: Capture a tmux pane transcript and an asciinema replay of a pm TUI session
---

## When to use

A scenario produces behavior worth confirming end-to-end through the
pm TUI — a keybinding, a pane render, a flow you'd normally drive by
hand — and you want unambiguous evidence of what happened, consumable
by humans (replay) and downstream agents (parse the cast or the
pane scrollback).

## What this recipe produces

Written per capture into `<capture-dir>/` (a
subdirectory under the captures directory the scenario prompt
names):

- `transcript.log` — plain-text scrollback of the pane (comes free
  from the `pipe-pane` in the capture flow; handy for grep/diff).
- `recording.cast` — asciinema replay.
- `recording.mp4` — H.264 video rendered from the cast (**required**;
  plays everywhere including iOS Safari, unlike VP8/VP9 webm).
  The embeddable view: the sign-off HTML report shows it inline via a
  plain `<video controls>` element — native pause / scrub, no player
  library, works offline. The `.cast` stays as the small,
  exact-replay/grep source.
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
#    creates the project's pm session and then attaches; the attach
#    can stall when there's no tty (or when this recipe is itself
#    running inside another tmux pane), so background the sub-shell
#    — not `pm session` — and wait for the session to exist before
#    moving on. The subshell form keeps job-control noise out of the
#    recording.
( pm session >/dev/null 2>&1 ) &
until tmux ls 2>/dev/null | grep -q '^pm-'; do sleep 0.2; done
TARGET=$(pm session name)             # canonical pm session name

# 2. Stream the home pane's scrollback to transcript.log.
tmux pipe-pane -t "$TARGET:0.0" -o "cat >> <capture-dir>/transcript.log"

# 3. Start the recorder session — a separate session on the same
#    tmux server whose pane runs asciinema wrapping `tmux attach -t
#    $TARGET`. tmux sizes the session group to the smallest attached
#    client, so set -x and -y large enough to render the TUI legibly
#    (the cast inherits this size). 200x50 fits a typical desktop
#    layout; bump them up if your scenario needs more room.
tmux new-session -d -s pm-recorder -x 200 -y 50 \
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
    # A pane large enough to blow that budget is already crisp at native
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
render_cast "<capture-dir>/recording.cast" || echo "RENDER FAILED: do not publish this capture yet"
```

Notes:
- `--idle-time-limit 2` caps the long pauses a TUI session accumulates,
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
  guard matters: an unconditional 2x on a large pane produces a
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
- `recording.mp4` — <one-line description>
- `<any extra file>` — <one-line description>
```

## Reviewing

Reviewers replay with `asciinema play <file>.cast` or read
`transcript.log` directly. The manifest tells them what they're looking
at without re-deriving it from code.
