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
- `transcript.log` — plain-text output of the recorded command, written
  **only** by the `tee` fallback for a host without asciinema (that
  capture has no cast and no video).
- `recorder.status`, `recorder-stderr.log` (and `recorder-pane.log` when a
  wait gives up) — the no-TTY scaffold's diagnostics: asciinema's own exit
  status, its error output, and the pane's last screen. They are failure
  evidence rather than capture artifacts; mention whichever exist in the
  manifest's `## Files` section.
- `manifest.md` — frontmatter + prose: workdir, the exact command(s)
  recorded, what the recording demonstrates, pre/post-fix state if
  relevant. Include a `## Files` section listing every non-default
  file the capture produced with a one-line description each. A previous
  run's copy is cleared with the rest before recording, so the manifest in
  the directory is always this run's.

## Capture

Before any of the forms below, create the capture directory and clear what
an earlier run left in it — the cast, the transcript, the rendered video and
the recorder diagnostics:

```
# <capture-dir> has to be an absolute path (or start with ~/): the no-TTY
# scaffold's pane command and step 4's checks resolve it against whichever
# shell pasted them (step 4 is usually a fresh one), so a relative path only
# works while every paste shares one directory — otherwise the cast is written
# somewhere the stop step never looks, and it reports "asciinema wrote no
# cast" for a recording that finished. Stop here instead.
case "<capture-dir>" in
    /* | "~"/*) ;;
    *)  echo "<capture-dir> must be an absolute path (or start with ~/) —" \
            "the scaffold's pane command and step 4 resolve it against" \
            "whichever shell pasted them, so a relative path writes the cast" \
            "where the checks do not look" >&2
        exit 1 ;;
esac
# A capture directory that cannot be created must stop the run here: every
# form below writes into it, and asciinema reports "asciicast saved" and
# exits 0 even when it wrote nothing, so the failure would read as success.
mkdir -p <capture-dir>/<short-name> || {
    echo "could not create <capture-dir>/<short-name> — check the path and" \
        "its permissions" >&2
    exit 1
}
# An *existing* directory that cannot be written is the same state one shape
# over, and `mkdir -p` answers 0 for it: the clear below cannot remove the
# previous run's files, and every form then writes into a directory that
# cannot hold the capture (the simple forms abort on the uncleared cast —
# asciinema 2.1.0 answers "asciinema: <path> already exists, aborting" — and
# the no-TTY scaffold's pane redirect fails before asciinema runs — step 4
# then reports "asciinema wrote no cast" for a file that cannot exist,
# verified live with a mode-500 capture directory). Stop here instead.
[ -w <capture-dir>/<short-name> ] && [ -x <capture-dir>/<short-name> ] || {
    echo "capture directory <capture-dir>/<short-name> cannot be written —" \
        "check the path and its permissions" >&2
    exit 1
}
rm -f <capture-dir>/<short-name>/recording.cast \
      <capture-dir>/<short-name>/transcript.log \
      <capture-dir>/<short-name>/recording.mp4 \
      <capture-dir>/<short-name>/recording.cast.gif \
      <capture-dir>/<short-name>/recorder.status \
      <capture-dir>/<short-name>/recorder-stderr.log \
      <capture-dir>/<short-name>/recorder-pane.log \
      <capture-dir>/<short-name>/manifest.md
```

`asciinema rec` reports "asciicast saved" and exits 0 even when the
directory does not exist, so a missing `mkdir` looks like a successful
capture that wrote nothing. A directory that exists and cannot be written is
the same state one shape over: `mkdir -p` answers 0 for it, so the creation
guard passes, the clear cannot remove the previous run's files, and the
pane's redirect fails before asciinema runs — which step 4 reports as
"asciinema wrote no cast" for a file that cannot exist. Both blocks refuse it
where the path is known. A leftover cast is worse: without
`--overwrite` the recorder aborts on it, and the render step rewrites the
`.mp4` from whatever cast is on disk, so a run that recorded nothing would
still produce a fresh-looking video of the *previous* run. The no-TTY
scaffold repeats both steps, and also clears a `rec` session an earlier run
left behind: a leftover one makes `new-session` fail with "duplicate
session: rec" — the scaffold reports that as a start failure, instead of
spinning out its readiness wait against a `rec` session that never writes a
cast. This recipe's readiness handle is the cast file, not the pane (a quiet
command draws nothing), so — unlike the tmux recipe's pane-content wait — it
cannot pass on the previous run's recorder; it would just burn its deadline.
`recorder.status` holds this run's recorder exit status (step 4 of
the no-TTY scaffold); a leftover one would let a recorder that was torn down
before it finished pass that check. `recorder-stderr.log` and
`recorder-pane.log` are this run's failure evidence — asciinema's own
diagnostics, and the pane's last screen when a wait gives up — so an earlier
run's copies go with the rest; a stale one would be read as this run's
failure. The render outputs (`recording.mp4` and the intermediate
`recording.cast.gif` — the render block's `cast` variable is
`…/recording.cast` and it renders to `"$cast.gif"`, so the name carries the
`.cast` too) and the `tee` fallback's `transcript.log` go too: the
render step clears the video pair before it runs, but a capture that *fails*
exits before that step ever runs, so the previous run's video would
otherwise be the only recording in the capture directory — a stale artifact
the manifest and the report would present as this run's evidence. The
previous run's `manifest.md` goes with them for the same reason one level up:
it is the document that says what this capture is, so a re-run that fails
before the worker writes a new one would leave a manifest describing the
previous run and naming a cast and a video that were just deleted.

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
#    unexpectedly"). The socket *name* is shared by every run on this host,
#    so two CLI captures must not run at once: the later run's
#    `kill-session -t rec` ends the earlier run's recorder, and either run's
#    failure path kills the server under the other. Both then fail loudly (a
#    torn-down pane has no status file) rather than reading each other's
#    evidence, but both captures are lost — run them one after the other.
#    That shared name is why the clear comes *after* the absolute-path guard
#    and the `mkdir` below: a block that is about to refuse its own input must
#    not end a concurrent capture's recorder on its way out.
#    <command-to-record> sits inside single quotes that are
#    themselves inside the outer double-quoted argument, so a command with
#    quotes of its own has to be escaped to survive both layers: for the
#    `bash -c` form above, paste
#        -c 'bash -c \"set -x; cmd-one; cmd-two\"'
#    and note the outer shell expands `$` in it before asciinema sees it.
#    Pasting the double-quoted form unescaped ends the outer string, so
#    asciinema gets a broken command, exits, and step 4 reports "asciinema
#    wrote no cast".
#    A `'` inside the command needs `'\''` for the same reason: the single
#    quotes around it are ordinary characters by the time the pane's shell
#    parses the command, so an unescaped one ends it early. Verified: the
#    natural `-c 'pm pr note add pr-x 'a note''` leaves asciinema exiting 2
#    with no cast, while `-c 'pm pr note add pr-x '\''a note'\'''` records
#    the command as intended.
#    The pane command is `asciinema … 2> …/recorder-stderr.log; echo \$? >
#    …/recorder.status`: the shell that owns the pane records asciinema's
#    *own* exit status once it returns, which step 4 needs to tell a
#    finished recording from a recorder that was killed. `\$?` is escaped so
#    the pane's shell expands it, not this one. asciinema's stderr goes to
#    a file rather than the pane for the same reason: its own errors (a
#    broken `-c` command, an unwritable cast path) are what a failed run
#    needs, and every failure path below tears the pane down. The recorded
#    command's own stderr still goes to the pty and is recorded.
# <capture-dir> has to be an absolute path or start with ~/ (the preamble
# above explains why):
# the pane command below and step 4's checks resolve it against whichever
# shell pasted them, and this block is pasted whole by a worker who may never
# have pasted the preamble. Stop here instead of writing the cast somewhere
# step 4 does not look — and before the `rec` session is cleared below: that
# `kill-session` ends whatever capture is running on the host's shared socket,
# so a block refused for its path must not take a concurrent run's recorder
# down with it (the same "act only on a handle you have" rule as the rest of
# this recipe).
case "<capture-dir>" in
    /* | "~"/*) ;;
    *)  echo "<capture-dir> must be an absolute path (or start with ~/) —" \
            "the scaffold's pane command and step 4 resolve it against" \
            "whichever shell pasted them, so a relative path writes the cast" \
            "where the checks do not look" >&2
        exit 1 ;;
esac
# A capture directory that cannot be created must stop the run here: every
# form below writes into it, and asciinema reports "asciicast saved" and
# exits 0 even when it wrote nothing, so the failure would read as success.
mkdir -p <capture-dir>/<short-name> || {
    echo "could not create <capture-dir>/<short-name> — check the path and" \
        "its permissions" >&2
    exit 1
}
# An *existing* directory that cannot be written is the same state one shape
# over, and `mkdir -p` answers 0 for it: the pane command's `2> …` redirect
# fails before asciinema runs, the recorder dies, and step 4 reports
# "asciinema wrote no cast — see …/recorder-stderr.log" for a file that
# cannot exist (verified live: with a mode-500 capture directory the block
# exited 1 with that message and the directory stayed empty). Stop here
# instead — and before the shared `rec` session is cleared below, so a block
# refused for its path cannot end a concurrent capture's recorder.
[ -w <capture-dir>/<short-name> ] && [ -x <capture-dir>/<short-name> ] || {
    echo "capture directory <capture-dir>/<short-name> cannot be written —" \
        "the pane's cast and status redirects both write into it; check the" \
        "path and its permissions" >&2
    exit 1
}
# Clear the leftover `rec` session now that the path is known good (see the
# note above): `new-session` fails with "duplicate session: rec" while it
# exists. It goes *after* the `mkdir` above, not before it: the `scaffold`
# socket name is shared by every CLI capture on this host, so a block that is
# about to refuse a capture directory it cannot create would otherwise end a
# concurrent capture's recorder on its way out — that run then fails as
# "recorder status is missing", a failure it cannot connect to this block.
# (The absolute-path guard above comes first for the same reason.)
tmux -L scaffold kill-session -t rec 2>/dev/null || true
rm -f <capture-dir>/<short-name>/recording.cast \
      <capture-dir>/<short-name>/transcript.log \
      <capture-dir>/<short-name>/recording.mp4 \
      <capture-dir>/<short-name>/recording.cast.gif \
      <capture-dir>/<short-name>/recorder.status \
      <capture-dir>/<short-name>/recorder-stderr.log \
      <capture-dir>/<short-name>/recorder-pane.log \
      <capture-dir>/<short-name>/manifest.md
# The manifest goes with the rest: it is the document that says what this
# capture is (workdir, the recorded command, `## Files`), so a re-run that
# fails before a new one is written would leave the previous run's manifest
# describing a cast and a video this `rm` just deleted. The manifest and the
# directory disagreeing is the same stale-evidence bug as a leftover cast, in
# the document that interprets the rest.
# Failure paths below that tear the scaffold server down save the pane's last
# screen into the capture dir first — otherwise the messages that point at the
# pane point at evidence that no longer exists. The stop step's two failures
# are the exception: they leave the recorder running (the recording is what
# the worker retries the step against), and the timeout case saves the pane
# while it is still up. The save is written out at each site rather than
# defined as a function here: step 4 is
# pasted on its own for an interactive recording (step 3 is what drives the
# shell, so the block cannot run as one paste), and a function defined in this
# block does not exist in that shell.
tmux -L scaffold new-session -d -s rec -x 100 -y 30 \
    "asciinema rec --quiet --overwrite <capture-dir>/<short-name>/recording.cast \
        -c '<command-to-record>' 2> <capture-dir>/<short-name>/recorder-stderr.log; \
        echo \$? > <capture-dir>/<short-name>/recorder.status" || {
    # tmux could not create the session at all (server gone or refusing, a
    # duplicate session left by a concurrent run, a bad option): the pane
    # command never ran, so step 4 would report "asciinema wrote no cast" and
    # point at a stderr log that was never written. Say what actually
    # happened instead.
    echo "could not start the recorder session — see tmux's error above" >&2
    tmux -L scaffold kill-server 2>/dev/null
    exit 1
}

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
        tmux -L scaffold capture-pane -p -t rec \
            > <capture-dir>/<short-name>/recorder-pane.log 2>/dev/null || true
        echo "recorder did not start within 30s — the pane is saved in" \
            "<capture-dir>/<short-name>/recorder-pane.log, asciinema's own" \
            "error (if any) in recorder-stderr.log" >&2
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
#    Check each send: a `send-keys` that fails means the pane — and so the
#    recorded shell — is already gone, so that step of the scenario never
#    ran. Step 4 cannot tell: asciinema exits 0 whenever its command ends,
#    whether the shell was driven to `exit` or died first, so the cast
#    stops before the behaviour under test and still passes every check.
#    Re-run the capture rather than accept it.

# 4. Wait (bounded) for asciinema to exit — the pane *is* the recording, so
#    the session ending is the completion signal — then confirm the cast is
#    there and non-empty *and* that asciinema itself exited 0 (a killed
#    recorder leaves a header-only cast). For a one-shot command that
#    legitimately runs longer than the default bound, raise
#    RECORDER_STOP_TIMEOUT (seconds):
#    prefix this block with RECORDER_STOP_TIMEOUT=120 (the variable does not
#    survive a separate shell invocation, so set it in the same call). The
#    bound is a hang detector, not a time limit on the recorded work, and
#    killing a healthy recording loses the evidence — so neither failure
#    below (a mistyped value, or a bound that ran out on a long command)
#    tears the recorder down: the recording is exactly what the worker
#    re-runs this step against. Killing it here made the documented remedy
#    impossible: re-running with a larger bound then failed with "recorder
#    status is missing", because the previous run had already destroyed the
#    pane it was told to wait for (verified live: `sleep 6` recorded, stop
#    with RECORDER_STOP_TIMEOUT=1, re-run with 60 → the recording was gone).
stop_timeout=${RECORDER_STOP_TIMEOUT:-30}
# Validate the bound before the arithmetic that uses it. A non-numeric value
# (`2m`, `1.5h`) makes `$(( … ))` fail and leaves `deadline` empty — and in an
# *interactive* shell the block carries on past that error (only a scripted
# run exits), so the deadline check below is always false and the wait never
# ends: the unbounded wait this step exists to remove, reintroduced by a
# mistyped knob. `10#` keeps a leading zero from being read as octal.
case $stop_timeout in
    *[!0-9]*)
        echo "RECORDER_STOP_TIMEOUT must be whole seconds (got" \
            "'$stop_timeout'); the recording is still running — re-run this" \
            "step with a whole number of seconds, e.g." \
            "RECORDER_STOP_TIMEOUT=120" >&2
        exit 1 ;;
esac
deadline=$(( $(date +%s) + 10#$stop_timeout ))
while tmux -L scaffold has-session -t rec 2>/dev/null; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
        tmux -L scaffold capture-pane -p -t rec \
            > <capture-dir>/<short-name>/recorder-pane.log 2>/dev/null || true
        echo "recorder did not exit within ${stop_timeout}s — the recording" \
            "is still running: for a longer command re-run this step with a" \
            "larger RECORDER_STOP_TIMEOUT; an interactive recording needs" \
            "'exit' in the recorded shell (step 3); if it is stuck, 'tmux -L" \
            "scaffold kill-server' ends it and the capture must be" \
            "re-recorded; the pane is saved in" \
            "<capture-dir>/<short-name>/recorder-pane.log" >&2
        exit 1
    fi
    sleep 0.2
done
test -s <capture-dir>/<short-name>/recording.cast || {
    echo "asciinema wrote no cast — see" \
        "<capture-dir>/<short-name>/recorder-stderr.log" >&2
    tmux -L scaffold kill-server 2>/dev/null   # do not leave `rec` behind
    exit 1
}
# A non-empty cast is not proof the recording finished: an asciinema that
# was killed mid-recording leaves a cast holding only its header. Its own
# exit status is the handle. It is 0 when the recording ran to completion —
# the *recorded* command's status is not propagated, so a recording of a
# command that exits non-zero is still a finished recording — and non-zero
# when asciinema refused to start or was killed, in which case the cast
# stops wherever it stopped. A missing status file means the pane was torn
# down before asciinema returned, which is the same failure.
status=$(cat <capture-dir>/<short-name>/recorder.status 2>/dev/null) || {
    echo "recorder status is missing — the pane was torn down before" \
        "asciinema exited, so the cast is incomplete, not a finished" \
        "recording" >&2
    tmux -L scaffold kill-server 2>/dev/null
    exit 1
}
[ "$status" = 0 ] || {
    echo "asciinema exited $status — the cast is incomplete, not a finished" \
        "recording; see <capture-dir>/<short-name>/recorder-stderr.log" >&2
    tmux -L scaffold kill-server 2>/dev/null
    exit 1
}
tmux -L scaffold kill-server 2>/dev/null || true   # cleanup
```

If `asciinema` isn't installed and can't be installed, fall back to
appending `| tee <capture-dir>/<short-name>/transcript.log` to the command
line — you lose animation but keep the output, and it lands in the capture
directory with the rest of the evidence. A bare `| tee transcript.log`
writes into whatever directory the worker happens to be in, so the capture
would have no transcript at all while the manifest lists one. Note the
fallback in the manifest. That fallback writes no cast, so the render step
below has nothing to render and fails with "there is no cast to render"; a
capture taken this way has no video, so say so in the manifest rather than
presenting it as a complete recording.

## Render to video

Once the cast exists, render a `.mp4` sibling so the recording embeds
in the sign-off HTML report as a `<video controls>` element. `agg`
renders the cast to frames (GIF), then `ffmpeg` encodes H.264 — there is
no single cast→video tool worth using (the dedicated ones are orders of
magnitude slower and fragile). The cast is the immutable source: never
edit or re-record it to fix a render.

Two tools do the two stages. `ffmpeg` is in the QA image; `agg` may not be
(the image used for QA on 2026-10-27 did not have it, although the bundled
Dockerfile now installs it), and the block below fails instead of leaving a
missing or stale video — so install `agg` first when `agg --version` fails
(`~/.local/bin` is on `PATH` in the image; the install creates it if
it is missing, since `curl -o` cannot; the asset is per architecture, verified
with agg 1.9.0). The block is guarded on that check: a working `agg` answers
it, so pasting the block on an image that already has `agg`
does nothing — while a *truncated* binary, which `command -v agg` cannot see,
is replaced instead of leaving the render's "is 'agg' installed?" pointing at
a remedy that would do nothing. It stops when the binary it just installed
still does not resolve (`~/.local/bin` not on `PATH`) or still does not run,
instead of exiting 0 and leaving the render to ask the same question, which
sends the worker back to the same block. The render block
also checks that `ffmpeg` exists, because a missing encoder otherwise reads
as a bad gif:

```
# Install when agg is missing *or* the one on PATH does not run. The bundled
# Dockerfile installs it, so this block usually does nothing. Re-downloading
# over a *working* agg is not harmless: `~/.local/bin` comes first on PATH,
# and `curl -o` writes in place, so a transfer that fails partway leaves a
# truncated binary that shadows the image's working one (verified: a dropped
# transfer replaced a working agg with a 500-byte file). A *truncated* agg is
# the other half of that story, and the reason the guard is not
# `command -v agg`: it still resolves, so a resolvability guard skips the
# install, and the render's "agg failed on the cast — is 'agg' installed?"
# sends the worker back here, where nothing happens — a remedy that cannot
# work, in a loop. `agg --version` is the handle: a working agg answers 0
# (verified with agg 1.9.0), while a truncated or wrong-architecture binary
# fails to execute.
if ! agg --version >/dev/null 2>&1; then
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
    # The install's job is to make `agg` resolvable, not to leave a file on
    # disk. `~/.local/bin` is on PATH in the image, but where it is not, this
    # block would exit 0 with an `agg` nothing can run: the render then fails
    # with "agg failed on the cast — is 'agg' installed?", the worker pastes
    # this block again, it downloads again and exits 0 — a remedy that cannot
    # work, in a loop. Say so, and name the fix.
    command -v agg >/dev/null || {
        echo "installed ~/.local/bin/agg but 'agg' still does not resolve —" \
            "~/.local/bin is not on PATH; add it (export" \
            "PATH=\"\$HOME/.local/bin:\$PATH\") and re-run the render" >&2
        exit 1
    }
    # ... and to leave one that *runs*. A download that arrived truncated, or
    # for another architecture, resolves and still fails to execute: the block
    # would exit 0 with the render's "is 'agg' installed?" unchanged, the same
    # loop one shape further in. Name the binary to remove — it is not
    # necessarily the one just written, because `~/.local/bin` may sit after
    # another agg on PATH — and stop instead of reporting a successful install.
    agg --version >/dev/null 2>&1 || {
        echo "the agg on PATH ($(command -v agg)) does not run — remove it" \
            "('rm -f $(command -v agg)') and re-run the render; if the" \
            "download itself is broken, install agg by another means" >&2
        exit 1
    }
fi
```

Don't substitute a different renderer: the mp4 is the required artifact.

```
cast=<capture-dir>/<short-name>/recording.cast
# The cast's directory has to be there and writable before anything is
# removed or rendered. A missing one turns the cast check below into "the
# recording wrote nothing" for a path that is not there; an existing
# directory that cannot be written makes the `rm` fail silently and `agg` fail
# to write its gif, which the block reports as "agg failed on the cast — is
# 'agg' installed?" — a remedy that cannot work, because the renderer is
# installed and the directory is the problem. Verified live in this container
# with agg 1.9.0 and ffmpeg 4.4.2 and a mode-500 capture directory holding a
# cast: rc 1 with that message, the earlier run's `recording.mp4` surviving
# the failed `rm`, and the install block that message points at exiting 0
# without changing anything. Both checks run before the `rm`, so a
# refused block leaves the earlier run's outputs alone — the same rule the
# capture step's own directory guards follow.
cast_dir=${cast%/*}
[ -d "$cast_dir" ] || {
    echo "capture directory $cast_dir does not exist — create it and run the" \
        "capture step first" >&2
    exit 1
}
[ -w "$cast_dir" ] && [ -x "$cast_dir" ] || {
    echo "capture directory $cast_dir cannot be written — the render writes" \
        "the mp4 and the intermediate gif there; check the path and its" \
        "permissions" >&2
    exit 1
}
# Remove this run's outputs before rendering: a failed render (no `agg`, an
# unreadable cast, an ffmpeg error) then ends with *no* mp4, instead of
# leaving the previous run's video in the capture directory — which the
# manifest and the report would present as this run's evidence. The gif and
# the in-progress partial go too, so a failed `agg` cannot fall back to
# encoding an earlier one.
rm -f "${cast%.cast}.mp4" "$cast.gif" "${cast%.cast}.mp4.partial.mp4"
# One failure shape for the whole render, so the worker sees the same
# sentence whichever stage broke. A renderer that fails may still leave a
# partial output behind (verified: a killed `ffmpeg` leaves a non-empty mp4),
# so the partial file goes too — `test -s` alone would accept it.
render_fail() {
    rm -f "$cast.gif" "${cast%.cast}.mp4" "${cast%.cast}.mp4.partial.mp4"
    echo "render produced no mp4 — $*" >&2
    exit 1
}
# No cast means no video, and that is *not* an `agg` problem: say which it
# is, so the worker does not go install a renderer it already has. (The
# `tee transcript.log` fallback above produces no cast at all.)
[ -s "$cast" ] || render_fail \
    "there is no cast to render (the recording wrote nothing)"
# A missing encoder is not a bad gif either. Without this check the shell
# answers "ffmpeg: command not found" (status 127) and the encode below
# reports "ffmpeg failed on the gif", sending the worker to inspect the cast
# and `agg` for a tool that is simply not installed — the same misdiagnosis
# as reporting a missing cast as an `agg` problem, one tool over. (The web-UI
# recipe's finalize step guards this the same way.) Checked before the agg
# render so a missing encoder costs no encode.
command -v ffmpeg >/dev/null || {
    echo "ffmpeg is not installed — the render step needs it; install it" \
        "(e.g. 'apt-get install ffmpeg') and re-run this step" >&2
    exit 1
}
# render_cast <cast>: <cast> -> sibling recording.mp4 (variable frame rate).
# Returns non-zero, and publishes no new recording.mp4, if any step fails.
# The encode writes recording.mp4.partial.mp4 and renames it to
# recording.mp4 only after a successful encode, so a failed or interrupted
# render never publishes a partial video under the name the manifest
# presents. Each stage check below names the stage that broke, in one
# sentence, so the worker is not sent to the renderer for an encoder failure
# (or the other way round).
render_cast() {
    local cast=$1 gif="$1.gif" mp4="${1%.cast}.mp4"
    local part="$mp4.partial.mp4" vf gw gh n dur
    rm -f "$gif" "$part"
    agg --idle-time-limit 2 "$cast" "$gif" || {
        echo "agg failed on the cast — is 'agg' installed?" >&2
        return 1
    }
    # The gif is the *next* stage's input, so check it exists before handing it
    # to ffmpeg — the rule the cast check above applies one stage earlier. An
    # `agg` that reports success and writes nothing (or a 0-byte gif) otherwise
    # surfaces below as "ffmpeg failed on the gif", which sends the worker to
    # the encoder for a renderer that wrote nothing: the same misdiagnosis as
    # reporting a missing cast as an `agg` problem (verified with this block and
    # a stub `agg` that exits 0 without writing: the run said "ffmpeg failed on
    # the gif"). The `test -s` on the partial mp4 catches the same shape for
    # the encoder, one stage further on.
    [ -s "$gif" ] || {
        echo "agg wrote no gif (the renderer reported success and wrote" \
            "nothing)" >&2
        return 1
    }
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
        || { echo "cannot probe the gif $gif" >&2; return 1; }
    vf="tpad=stop=1:stop_mode=clone,setpts='if(eq(N\,$n)\,$dur/TB\,PTS)',$vf"
    if ! ffmpeg -nostdin -loglevel error -y -i "$gif" -vf "$vf" \
           -vsync vfr -enc_time_base 1/100 -video_track_timescale 100 \
           -c:v libx264 -profile:v high -level:v 5.1 -pix_fmt yuv420p \
           -crf 18 -movflags +faststart "$part"; then
        echo "ffmpeg failed on the gif" >&2
        return 1
    fi
    [ -s "$part" ] || { echo "ffmpeg wrote no mp4" >&2; return 1; }
    # Publish only after a complete encode. A failure to remove the
    # intermediate gif does not undo a published mp4 (render_fail would
    # delete it), so the mv is the step whose status matters here.
    mv -f "$part" "$mp4" || {
        echo "could not publish $mp4" >&2
        return 1
    }
    rm -f "$gif"
    return 0
}
render_cast "$cast" || render_fail \
    "the renderer's message above says which stage broke"
# The mp4 is the required artifact: fail here, visibly, rather than leaving
# the caller to notice the video is missing (or stale) later. The exit status
# above is what proves the encode ran; this catches a renderer that reports
# success and writes nothing.
test -s "${cast%.cast}.mp4" || render_fail "ffmpeg wrote no mp4"
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
- **Batches: ffmpeg never reads stdin.** Without `-nostdin`, ffmpeg reads
  its interactive keys from stdin, so a `find ... | while read c; do
  render_cast "$c"; done` loop loses characters of the next file names to
  it (seen in QA S46: `/pm-captures/...` became `m-captures/...`, then agg
  and rm were handed `-c`). Keep `-nostdin`, and give the loop its list
  another way (`mapfile -t casts < <(find ...)`) or run each call with
  `</dev/null`.
- **Partial output is never published.** ffmpeg writes to
  `recording.mp4.partial.mp4`, which is renamed to `recording.mp4` only
  after a successful encode; the GIF is deleted only after that rename.
  The render step also clears this run's outputs before it starts, and its
  failure path removes the gif and any partial, so a failed render leaves
  no `recording.mp4` at all — an earlier run's video cannot be presented
  as this run's evidence. So neither the file existing nor the GIF
  disappearing shows that this render succeeded: check this `render_cast`
  call's return status. If you stop a render on purpose, stop the shell
  running `render_cast` before its `ffmpeg` child, so the cleanup step
  cannot run. Label any partial output you keep (for example
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
