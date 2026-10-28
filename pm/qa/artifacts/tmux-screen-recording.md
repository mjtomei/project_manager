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

Step 0 of the capture flow runs `mkdir -p <capture-dir>` and clears the
files an earlier run left there. Both matter: `asciinema rec` reports
"asciicast saved" and exits 0 even when the directory does not exist, so a
missing `mkdir` looks like a successful capture that wrote nothing. A
leftover cast is worse in the other direction: without `--overwrite`,
`asciinema rec` aborts with "recording already exists", the recorder
session dies, and the render step then rewrites the `.mp4` from the *old*
cast — a failed recording that looks like a fresh capture. The transcript
is appended to, so a stale `transcript.log` would silently mix an earlier
run into this run's evidence.

```
# 0. Create the capture directory and clear what an earlier run left there
#    before anything writes into it.
mkdir -p <capture-dir>
rm -f <capture-dir>/recording.cast <capture-dir>/transcript.log

# 1. Start the canonical pm session. `pm session` (no subcommand)
#    creates the project's pm session and then attaches; the attach
#    can stall when there's no tty (or when this recipe is itself
#    running inside another tmux pane), so background the sub-shell
#    — not `pm session` — and wait for the session to exist before
#    moving on. The subshell form keeps job-control noise out of the
#    recording.
TARGET=$(pm session name)             # canonical pm session name
[ -n "$TARGET" ] || {
    echo "pm session name printed nothing — is pm on PATH?" >&2
    exit 1
}
( pm session >/dev/null 2>&1 ) &
# Bounded readiness wait on that exact session, not on any session whose
# name starts with pm-: this recipe's own pm-recorder session (and any
# other project's pm session) matches that, so the wait would pass before
# the target exists and the failure path below would never fire. An empty
# target would match too — `tmux has-session -t ''` succeeds — hence the
# guard above.
deadline=$(( $(date +%s) + 60 ))
until tmux has-session -t "$TARGET" 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "pm session $TARGET did not appear within 60s — check 'pm session' output" >&2
        exit 1
    fi
    sleep 0.2
done

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
# Wait (bounded) for the recorder to draw: the detach key in step 5 is
# lost if the attach client has not started yet. If the recorder exits
# first (the attach could not start), the session is already gone — step
# 5's cast check reports that, so this wait must not hang on it.
deadline=$(( $(date +%s) + 30 ))
until tmux capture-pane -p -t pm-recorder 2>/dev/null \
        | grep -q '[^[:space:]]' ||
      ! tmux has-session -t pm-recorder 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "recorder did not come up within 30s — check" \
            "'tmux capture-pane -p -t pm-recorder'" >&2
        tmux kill-session -t pm-recorder 2>/dev/null
        exit 1
    fi
    sleep 0.2
done

# 4. Drive the TUI from outside via pm tui send. Keys reach the TUI
#    via the same tmux server; the recorder's attach client renders
#    the redraws; asciinema captures them.
pm tui send q -s "$TARGET"            # e.g. navigate to the QA pane
pm tui send a -s "$TARGET"            # open the picker
# ... and so on for the scenario steps ...

# 5. End the recording by detaching the recorder's attach client.
#    The attach exits, the recorded command exits, asciinema flushes
#    the cast and the pane (started *as* the asciinema command) closes,
#    which ends the recorder session. Wait for that — it is the only
#    evidence the cast was flushed — instead of tearing the session
#    down underneath a still-running recorder.
tmux send-keys -t pm-recorder C-b d
deadline=$(( $(date +%s) + 30 ))
while tmux has-session -t pm-recorder 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        echo "recorder did not exit within 30s — check" \
            "'tmux capture-pane -p -t pm-recorder'" >&2
        tmux kill-session -t pm-recorder 2>/dev/null
        exit 1
    fi
    sleep 0.2
done
test -s <capture-dir>/recording.cast || {
    echo "asciinema wrote no cast — check the recorder pane" >&2
    exit 1
}
tmux pipe-pane -t "$TARGET:0.0"       # stop the transcript pipe
tmux kill-session -t pm-recorder 2>/dev/null || true   # already gone if it exited
```

## Render to video

Once the cast exists, render a `.mp4` sibling so the recording embeds
in the sign-off HTML report as a `<video controls>` element. `agg`
renders the cast to frames (GIF), then `ffmpeg` encodes H.264 — there is
no single cast→video tool worth using (the dedicated ones are orders of
magnitude slower and fragile). The intermediate GIF is discarded.

```
cast=<capture-dir>/recording.cast
agg --idle-time-limit 2 "$cast" "$cast.gif"
# 2x nearest-neighbor upscale for crisp text — but only while the result
# stays within iOS hardware-decode limits (4096x2304, H.264 level 5.1).
# A pane large enough to blow that budget is already crisp at native
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
```

Notes:
- `--idle-time-limit 2` caps the long pauses a TUI session accumulates,
  dropping dead air without losing anything worth watching.
- H.264 + `yuv420p` is the only combination that decodes everywhere,
  including iOS Safari (VP8/VP9 webm and 4:4:4 chroma do not). 4:2:0
  chroma subsampling would blur colored terminal text at native size,
  so the nearest-neighbor upscale renders at 2x — crisp text, and the
  doubling guarantees the even dimensions H.264 requires. The
  size guard matters: an unconditional 2x on a large pane produces a
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
