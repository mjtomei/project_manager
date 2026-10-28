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
- `recorder.status`, `recorder-stderr.log` (and `recorder-pane.log` when a
  wait gives up) — the capture flow's diagnostics: asciinema's own exit
  status, its error output, and the pane's last screen. They are failure
  evidence rather than capture artifacts; mention whichever exist in the
  manifest's `## Files` section.
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

Step 0 of the capture flow clears the recorder session and the files an
earlier run left behind, then creates the capture directory with
`mkdir -p <capture-dir>`. All of them matter. A leftover `pm-recorder`
session makes step 3's `new-session` fail with "duplicate session", and the
readiness wait below would then pass on the *previous* run's attach
client. `asciinema rec` reports "asciicast saved" and exits 0 even when the
directory does not exist, so a missing `mkdir` looks like a successful
capture that wrote nothing. A leftover cast is worse in the other
direction: without `--overwrite`, `asciinema rec` aborts with "recording
already exists" and the recorder dies before it draws, so the run fails at
the readiness wait — loudly, but for a reason unrelated to the scenario,
and with the earlier run's cast still on disk for the render step to pick
up if the worker overrides that failure. The transcript is appended to, so
a stale `transcript.log` would silently mix an earlier run into this run's
evidence. `recorder.status` holds this run's recorder exit status (step 5);
a leftover one would let a recorder that was torn down before it finished
pass that check. `recorder-stderr.log` and `recorder-pane.log` are this
run's failure evidence — asciinema's own diagnostics, and the pane's last
screen when a wait gives up — so an earlier run's copies go too.

```
# 0. Clear what an earlier run left behind before anything writes into it:
#    the recorder session, the capture directory, and the files in it.
tmux kill-session -t pm-recorder 2>/dev/null || true
# A capture directory that cannot be created must stop the run here. Every
# later step writes into it, and their failures read as something else: the
# transcript pipe cannot redirect, asciinema cannot write its cast, and the
# recorder dies before it draws — so the run ends with "recorder exited
# before it drew" naming a cast and a stderr log that do not exist.
mkdir -p <capture-dir> || {
    echo "could not create <capture-dir> — check the path and its" \
        "permissions" >&2
    exit 1
}
rm -f <capture-dir>/recording.cast <capture-dir>/transcript.log \
      <capture-dir>/recorder.status <capture-dir>/recorder-stderr.log \
      <capture-dir>/recorder-pane.log
# Failure paths below tear the recorder session down, so each one saves the
# pane's last screen into the capture dir first — otherwise the messages that
# point at the pane point at evidence that no longer exists. The save is
# written out at each site rather than defined as a function here: step 5 is
# pasted on its own (a scenario that needs interactive driving is not one
# paste), and a function defined in this block does not exist in that shell.

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
        echo "pm session $TARGET did not appear within 60s — 'pm session' was" \
            "backgrounded with its output discarded, so run it in a tmux pane" \
            "(it attaches) to see why; check 'pm' is on PATH too" >&2
        exit 1
    fi
    sleep 0.2
done

# 2. Stream the home pane's scrollback to transcript.log. No -o: that only
#    opens a pipe when none is attached, so a pipe left behind by an aborted
#    earlier run would make this a silent no-op and no transcript.log would
#    ever be written. Without it the pipe is replaced (and the old one
#    closed), so this step is idempotent. The attach itself can fail (the
#    pane is gone, or tmux cannot spawn the command) and would otherwise be
#    silent until the empty transcript is found at the end.
tmux pipe-pane -t "$TARGET:0.0" "cat >> <capture-dir>/transcript.log" || {
    echo "could not stream $TARGET:0.0 to <capture-dir>/transcript.log —" \
        "check that pane exists" >&2
    exit 1
}

# 3. Start the recorder session — a separate session on the same
#    tmux server whose pane runs asciinema wrapping `tmux attach -t
#    $TARGET`. tmux sizes the session group to the smallest attached
#    client, so set -x and -y large enough to render the TUI legibly
#    (the cast inherits this size). 200x50 fits a typical desktop
#    layout; bump them up if your scenario needs more room.
#    The pane command also records asciinema's *own* exit status once it
#    returns: step 5 needs it to tell a finished recording from a recorder
#    that was killed, and `test -s` on the cast cannot. `\$?` is escaped so
#    the pane's shell expands it, not this one. asciinema's stderr goes to a
#    file for the same reason: its own errors (an unwritable cast path, a
#    bad option) are what a failed run needs, and every failure path below
#    tears the pane down. The attach's own errors still go through the pty
#    and stay visible in the pane and the cast.
tmux new-session -d -s pm-recorder -x 200 -y 50 \
    "asciinema rec --quiet <capture-dir>/recording.cast \
        -c 'tmux attach -t $TARGET' 2> <capture-dir>/recorder-stderr.log; \
        echo \$? > <capture-dir>/recorder.status" || {
    # tmux could not create the session at all (server gone or refusing,
    # a duplicate session left by a concurrent run, a bad option): the pane
    # command never ran, so the readiness wait below would report "recorder
    # exited before it drew" and point at a cast and stderr log that were
    # never written. Say what actually happened instead.
    echo "could not start the recorder session — see tmux's error above" >&2
    tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
    exit 1
}
# Wait (bounded) for the recorder to draw: the detach key in step 5 (and
# every key sent below) is lost if the attach client has not started yet.
# A recorder that *exits* here cannot have recorded the TUI — the
# attach failed — so that is a failure, not a recording that finished
# early: the cast it leaves holds asciinema's error, not the session, and
# treating it as done would report a useless capture as success.
deadline=$(( $(date +%s) + 30 ))
while :; do
    if ! tmux has-session -t pm-recorder 2>/dev/null; then
        echo "recorder exited before it drew — see the cast and" \
            "<capture-dir>/recorder-stderr.log" >&2
        tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
        exit 1
    fi
    tmux capture-pane -p -t pm-recorder 2>/dev/null \
        | grep -q '[^[:space:]]' && break
    if [ "$(date +%s)" -ge "$deadline" ]; then
        tmux capture-pane -p -t pm-recorder \
            > <capture-dir>/recorder-pane.log 2>/dev/null || true
        echo "recorder did not come up within 30s — the pane is saved in" \
            "<capture-dir>/recorder-pane.log, asciinema's own error (if any)" \
            "in recorder-stderr.log" >&2
        tmux kill-session -t pm-recorder 2>/dev/null
        tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
        exit 1
    fi
    sleep 0.2
done
# Pane content alone does not prove the attach worked: a *failed* attach
# (`tmux attach` to a session that is not there) prints its own error —
# "can't find session: …" — into the pane and then exits, so the content
# check above can break on asciinema's error text and the cast check in
# step 5 then passes on a cast holding that error. The error is drawn
# milliseconds before the recorder exits, so confirm the recorder is still
# alive a moment later before treating the content as a drawn TUI.
sleep 0.3
if ! tmux has-session -t pm-recorder 2>/dev/null; then
    echo "recorder exited before it drew — see the cast and" \
        "<capture-dir>/recorder-stderr.log" >&2
    tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
    exit 1
fi

# 4. Drive the TUI from outside via pm tui send. Keys reach the TUI
#    via the same tmux server; the recorder's attach client renders
#    the redraws; asciinema captures them.
#    Driving steps are usually pasted into a fresh shell (a scenario's
#    commands are their own paste), where `$TARGET` from step 1 is gone. An
#    empty one is not harmless here: `pm tui send -s ""` falls back to
#    auto-detection — the cwd's session, then *any* pm session with a TUI —
#    so the keys can drive a different TUI than the one being recorded, with
#    no error at all and a cast that never showed the behaviour. Re-derive
#    the handle as step 5 does, and refuse an empty one.
TARGET=${TARGET:-$(pm session name)}
if [ -z "$TARGET" ]; then
    echo "TARGET is unset and 'pm session name' printed nothing — run this" \
        "step with pm on PATH, in the project directory" >&2
    exit 1
fi
#    Check each send. A `pm tui send` that fails means the TUI is gone, so
#    that step of the scenario never ran — and step 5 would then see the
#    recorder and the session both gone, call it a legitimate finish (it
#    cannot tell that apart from the scenario quitting pm itself), and pass
#    on a cast that stops before the behaviour under test. Re-run rather
#    than accept that capture. (The send that ends the session on purpose is
#    the one case where a failure is the quit racing the send; re-run rather
#    than guess.)
pm tui send q -s "$TARGET"            # e.g. navigate to the QA pane
pm tui send a -s "$TARGET"            # open the picker
# ... and so on for the scenario steps ...

# 5. End the recording by detaching the recorder's attach client.
#    The attach exits, the recorded command exits, asciinema flushes
#    the cast and the pane (started *as* the asciinema command) closes,
#    which ends the recorder session. Wait for that — it is the only
#    evidence the cast was flushed — instead of tearing the session
#    down underneath a still-running recorder.
#    First make sure there is a recorder left to detach. The attach client
#    follows the session, so it only exits on the detach, when the session
#    ends, or because it (or asciinema) died. If it is already gone while
#    the session it was attaching to is still there, it died mid-scenario:
#    the cast stops at that point and is a truncated recording, not a
#    finished one. `test -s` below cannot tell the difference, so fail here
#    instead of rendering a truncated cast as this run's evidence. A
#    recorder that ended because the session itself ended is a legitimate
#    finish — the wait below sees it. (Every pipe stop below is best-effort:
#    when the session is already gone the pipe is gone with it, and
#    `tmux pipe-pane` would otherwise print "can't find session: …" on a run
#    that succeeded.)
#    This step is pasted on its own whenever the scenario is driven
#    interactively, so re-derive the target session it was given in step 1
#    rather than acting on an empty one: `tmux has-session -t ''` *succeeds*,
#    which would turn the legitimate "the scenario ended the pm session"
#    finish below into "recorder exited while the TUI was still running", and
#    `pipe-pane -t ':0.0'` would stream whatever pane tmux picks as current.
TARGET=${TARGET:-$(pm session name)}
if [ -z "$TARGET" ]; then
    echo "TARGET is unset and 'pm session name' printed nothing — run this" \
        "step with pm on PATH, in the project directory" >&2
    exit 1
fi
if ! tmux has-session -t pm-recorder 2>/dev/null; then
    if tmux has-session -t "$TARGET" 2>/dev/null; then
        echo "recorder exited while the TUI was still running — the cast is" \
            "incomplete, not a finished recording" >&2
        tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
        exit 1
    fi
    # Both are gone: the session itself ended, which ended the attach and so
    # the recording. Nothing left to detach; the wait below is a no-op. That
    # explains why the recorder exited, not whether asciinema finished — the
    # status check below is what decides in this branch, because there is no
    # live session left as a witness.
else
    # The detach is the last handle that can race the recorder: if it died
    # between the check above and this key send, `send-keys` fails (the
    # session, or its pane, is gone), the wait below exits at once, and
    # `test -s` then passes on the truncated cast — a run reported as a
    # successful recording although it is not one. Treat the failed detach as
    # the same failure as above.
    tmux send-keys -t pm-recorder C-b d || {
        echo "recorder exited before the detach — the cast is incomplete," \
            "not a finished recording" >&2
        tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
        exit 1
    }
fi
deadline=$(( $(date +%s) + 30 ))
while tmux has-session -t pm-recorder 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        tmux capture-pane -p -t pm-recorder \
            > <capture-dir>/recorder-pane.log 2>/dev/null || true
        echo "recorder did not exit within 30s — the pane is saved in" \
            "<capture-dir>/recorder-pane.log" >&2
        tmux kill-session -t pm-recorder 2>/dev/null
        tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
        exit 1
    fi
    sleep 0.2
done
test -s <capture-dir>/recording.cast || {
    echo "asciinema wrote no cast — see" \
        "<capture-dir>/recorder-stderr.log" >&2
    tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
    exit 1
}
# A non-empty cast is not proof the recording finished: an asciinema that was
# killed mid-recording leaves a cast holding only its header, and when the
# target session ended too there is no live session left to witness it — the
# same position the CLI scaffold's pane is in. asciinema's own exit status is
# the handle. It is 0 when the recording ran to completion — the *recorded*
# command's status is not propagated, so a recording of a command that exits
# non-zero (or an attach that ends because the session ended) is still a
# finished recording — and non-zero when asciinema refused to start or was
# killed, in which case the cast stops wherever it stopped. A missing status
# file means the pane was torn down before asciinema returned, which is the
# same failure.
status=$(cat <capture-dir>/recorder.status 2>/dev/null) || {
    echo "recorder status is missing — the pane was torn down before" \
        "asciinema exited, so the cast is incomplete, not a finished" \
        "recording" >&2
    tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
    exit 1
}
[ "$status" = 0 ] || {
    echo "asciinema exited $status — the cast is incomplete, not a finished" \
        "recording; see <capture-dir>/recorder-stderr.log" >&2
    tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
    exit 1
}
# The recipe promises a transcript as well as a cast, and the pipe can accept
# the attach and still write nothing (a pipe whose command never ran, or a
# pane that emitted nothing). An empty file here means this run has no
# transcript, whatever the cast looks like.
test -s <capture-dir>/transcript.log || {
    echo "transcript.log is empty — the pipe-pane stream never wrote to it," \
        "so this capture has no transcript" >&2
    tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
    exit 1
}
tmux pipe-pane -t "$TARGET:0.0" 2>/dev/null || true   # stop the pipe
tmux kill-session -t pm-recorder 2>/dev/null || true   # already gone if it exited
```

## Render to video

Once the cast exists, render a `.mp4` sibling so the recording embeds
in the sign-off HTML report as a `<video controls>` element. `agg`
renders the cast to frames (GIF), then `ffmpeg` encodes H.264 — there is
no single cast→video tool worth using (the dedicated ones are orders of
magnitude slower and fragile). The intermediate GIF is discarded.

Two tools do the two stages. `ffmpeg` is in the QA image; `agg` may not be
(the image used for QA on 2026-10-27 did not have it, although the bundled
Dockerfile now installs it), and the block below fails instead of leaving a
missing or stale video — so install `agg` first when `command -v agg` prints
nothing (`~/.local/bin` is on `PATH` in the image; the install creates it if
it is missing, since `curl -o` cannot; the asset is per architecture, verified
with agg 1.9.0). The block is guarded on `command -v agg` for that reason, so
pasting it on an image that already has `agg` does nothing:

```
# Install only when agg is missing. The bundled Dockerfile installs it, so
# this block usually does nothing. Re-downloading over an existing agg is
# not harmless: `~/.local/bin` comes first on PATH, and `curl -o` writes in
# place, so a transfer that fails partway leaves a truncated binary that
# shadows the image's working one (verified: a dropped transfer replaced a
# working agg with a 500-byte file).
if ! command -v agg >/dev/null; then
    mkdir -p ~/.local/bin
    # Bound the download like every other request in this recipe: a transfer
    # that stalls would otherwise hang the worker with no deadline, the same
    # unbounded wait the capture flow bounds everywhere else. `-o` writes in
    # place, so a failed or timed-out download leaves a partial file behind —
    # remove it rather than leave a broken `agg` earlier on PATH than the
    # image's working one.
    curl -fsSL --connect-timeout 5 --max-time 180 \
        https://github.com/asciinema/agg/releases/latest/download/agg-$(uname -m)-unknown-linux-gnu \
        -o ~/.local/bin/agg || {
        rm -f ~/.local/bin/agg
        echo "could not download agg — put a release binary on PATH and" \
            "re-run the render" >&2
        exit 1
    }
    chmod +x ~/.local/bin/agg
fi
```

Don't substitute a different renderer: the mp4 is the required artifact.

```
cast=<capture-dir>/recording.cast
# Remove this run's outputs before rendering: a failed render (no `agg`, an
# unreadable cast, an ffmpeg error) then ends with *no* mp4, instead of
# leaving the previous run's video in the capture directory — which the
# manifest and the report would present as this run's evidence. The gif goes
# too, so a failed `agg` cannot fall back to encoding an earlier one.
rm -f "${cast%.cast}.mp4" "$cast.gif"
# One failure shape for the whole render, so the worker sees the same
# sentence whichever stage broke. A renderer that fails may still leave a
# partial output behind (verified: a killed `ffmpeg` leaves a non-empty mp4),
# so the partial file goes too — `test -s` alone would accept it.
render_fail() {
    rm -f "$cast.gif" "${cast%.cast}.mp4"
    echo "render produced no mp4 — $*" >&2
    exit 1
}
# No cast means no video, and that is *not* an `agg` problem: say which it
# is, so the worker does not go install a renderer it already has.
[ -s "$cast" ] || render_fail \
    "there is no cast to render (the recording wrote nothing)"
agg --idle-time-limit 2 "$cast" "$cast.gif" || render_fail \
    "agg failed on the cast — is 'agg' installed?"
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
    -movflags +faststart "${cast%.cast}.mp4" || render_fail \
    "ffmpeg failed on the gif"
rm -f "$cast.gif"
# The mp4 is the required artifact: fail here, visibly, rather than leaving
# the caller to notice the video is missing (or stale) later. The exit status
# above is what proves the encode ran; this catches a renderer that reports
# success and writes nothing.
test -s "${cast%.cast}.mp4" || render_fail "ffmpeg wrote no mp4"
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
