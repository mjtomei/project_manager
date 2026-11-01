"""Regression tests for the recording-recipe completion rules.

pr-b19db15 kept only the recipe bugs that any worker following the recipe
hits, regardless of how it waits for a background job:

- the capture directory is created before ``asciinema`` writes into it
  (it prints "asciicast saved" and exits 0 while writing nothing);
- a cast from an earlier run is removed before recording, so the render
  step cannot turn a failed recording into a fresh-looking video of the
  previous run (the tmux transcript, which is appended to, is cleared too);
- the no-TTY scaffold writes the cast where the render step reads it;
- a recorder session left by an aborted run is cleared before starting a new
  one (with ``kill-session``, not ``kill-server``, which races the server's
  exit), and the tmux transcript pipe is reattachable so a leftover pipe
  cannot silently swallow the new log;
- keys are not sent before the recorder is up (they are silently lost); the
  tmux recipe waits on pane content, while the CLI scaffold waits on the cast
  file — a quiet command draws nothing but is recording, and a tmux recorder
  that exits before drawing (or that draws its own attach error and then
  exits) is a failure rather than an early finish;
- the recorder is stopped by ending the recorded command and awaited with a
  bound, and the cast is checked non-empty; the CLI scaffold's bound is
  raisable (`RECORDER_STOP_TIMEOUT`) so a legitimately long one-shot command
  is not killed at the deadline, and a tmux recorder that is already gone by
  the detach (or that dies in the gap before the detach key is sent) fails
  the run instead of passing on a truncated cast. A non-empty cast is not
  proof of a finished recording — an asciinema killed mid-recording leaves a
  header-only cast — so both recipes have the pane's shell record asciinema's
  own exit status and fail on a missing or non-zero one. In the tmux recipe
  the target session is a witness only while it is alive, so the both-gone
  finish needs the status handle too — and that handle is only worth anything
  if the earlier run's status file is cleared first: otherwise a run whose
  pane was torn down before asciinema returned reads the previous run's ``0``
  and reports a recording that never finished as a finished one. The
  *completion handle* is the recorder pane's death (``#{pane_dead}``), not
  only its session's end: a server with ``set -g remain-on-exit on`` — a
  common way to keep a crashed pane visible, and what this project's own QA
  notes prescribe — keeps the session after its only pane's command returns,
  so a healthy recording's stop wait ran out its bound and reported "the
  detach key did not end it … incomplete" (and a failed attach's dead pane
  passed the settle check as a drawn TUI). Both recipes read the pane's own
  state for liveness and for the wait, and the session's absence remains the
  other half of the answer;
- readiness polls (pm session, web-ui server) carry a deadline and an
  actionable failure instead of hanging forever, the pm-session poll waits on
  the computed session rather than any ``pm-`` session (which would also
  match this recipe's own ``pm-recorder``), and the web-UI step refuses a
  port something already answers on (that server would satisfy the poll and
  the driver would record the wrong app) — *any* HTTP answer counts, a 404 at
  ``/`` included, so that pre-check is plain ``curl``: with ``-f`` a live app
  that 404s is reported as a failed check, a cause its port cannot have;
- two runs on one tmux server must not read each other's evidence: the
  transcript pipe is per-pane and a later one replaces it, so the tmux recipe
  claims the capture directory in a session option — before attaching the
  pipe, so the read/write gap does not cover the takeover it guards — and
  refuses a session recording a different directory, or a directory another
  live session records into; a finished run releases the claim, and every
  claim handle names the session exactly (``-t "=$TARGET:0.0"``), because a
  plain target is prefix-matched when the target has ended — the write then
  succeeds on a grouped ``<base>~N`` session and the "could not claim … the
  session went away" guard never fires; the claim
  is compared as a canonical directory rather than as the text typed (step 0
  accepts `~/cap`, and a quoted `~` never expands, so one directory spelled
  two ways was two claims), and a session holding no claim must not be read as
  claiming the worker's cwd (``cd ""`` stays put, so normalizing an empty
  answer made every other session look like it recorded into the directory the
  step was pasted from);
- a restart is not a fresh start: step 3 requires the transcript pipe step 2
  attached, because every failure path in the flow stops it — a restart
  pasted after a failure otherwise starts a recorder with no pipe, the
  transcript stops growing at the failure, and step 5's ``test -s`` passes on
  the replaced attempt's bytes (the stale-evidence shape the rest of this
  file is about). ``#{pane_pipe}`` is the handle, and the refusal names step
  2, which re-takes the claim the failure released and appends to the same
  transcript;
- the render steps delete this run's outputs before rendering, so a failed
  ``agg``/``ffmpeg``/transcode ends with no video instead of the previous
  run's mp4 (which the manifest would present as this run's evidence); the
  web-UI driver's trace, screenshots and DOM dump are cleared the same way,
  and the web-UI finalize step refuses to run at all with no ``CAPDIR``
  rather than aim its cleanup and ffmpeg at the filesystem root; every
  stage-input check is ``test -s``, because an artifact that exists but is
  empty is not an input the next stage can use (a 0-byte cast, gif or webm
  must be named as the stage that wrote nothing, not blamed on the stage
  after it), and the final mp4 check rejects an encoder that reports success
  and writes nothing; the publish is checked too — an empty encode is never
  renamed onto the final name, and a rename that leaves no published mp4 is
  a failure instead of a render of nothing (in the web-UI finalize it would
  otherwise run its last ``rm`` and destroy the only copy of the webm);
- the mp4 is the artifact the recipes promise because it plays everywhere:
  the encode forces ``libx264``/``yuv420p`` with ``+faststart`` — without the
  pixel format libx264 picks 4:4:4 for a GIF's pal8 input and the block's own
  ``-profile:v high`` refuses it, so the render fails reporting "ffmpeg
  failed on the gif" for an option the block itself dropped — and the 2x
  nearest-neighbor upscale is bounded by the iOS level-5.1 budget
  (4096x2304): a larger pane is rendered at native size instead of doubled
  past the limit iPhone/iPad hardware decoders silently refuse. Both were
  unproven: dropping the pixel format, ``+faststart``, the size guard or the
  upscale each left the whole file green;
- the render steps name their renderer prerequisite: ``agg`` may be missing
  (the image used for QA on 2026-10-27 did not have it, although the bundled
  Dockerfile now installs it), and the render fails loudly, so the recipe
  carries the per-architecture release-binary install line — guarded on
  ``agg --version``, which only a binary that actually *runs* answers: a
  working ``agg`` leaves the block a no-op (re-downloading over it can
  truncate it earlier on PATH), while a truncated one that still resolves —
  ``command -v agg`` answers that file — is replaced instead of leaving the
  render's "is 'agg' installed?" pointing at a remedy that does nothing;
- the CLI scaffold's ``<command-to-record>`` placeholder sits inside single
  quotes inside the outer double-quoted argument, so the recipe has to show
  the escaped form — pasting the plain ``bash -c "..."`` form ends the outer
  string and leaves asciinema with a broken command;
- the web-UI driver is an ES module and the image's Playwright is a *global*
  install advertised through ``NODE_PATH``, which ESM's resolver ignores, so
  the run block links a ``node_modules`` beside the driver (only when there is
  no local install) and stops at its own resolution check when the import
  still does not resolve;
- the web-UI driver's own exit status is the capture's completion handle: the
  driver block stops on a failed driver instead of letting the finalize step
  transcode whatever is on disk, and it clears this attempt's outputs first
  because that block is pasted on its own when a driver is retried — including
  an earlier attempt's already-finalized ``recording.mp4``, which a failed
  retry would otherwise leave as the manifest's only video. Every ``*.webm``
  is cleared, not only ``recording.webm``: a driver killed before
  the rename leaves Playwright's auto-named ``page@<hash>.webm``, which is a
  valid, playable partial recording;
- a step that cannot do its job says so where it fails instead of being
  misdiagnosed downstream: an unusable capture directory and a failed
  ``new-session`` stop the run with their own message (otherwise the failure
  reads as "recorder exited before it drew" / "asciinema wrote no cast", both
  pointing at files that were never written). The capture-directory guard
  tests both permission bits — a directory with the write bit and no *search*
  bit (mode 600) is the same unusable state and ``[ -w ]`` alone cannot see
  it, so every writability case runs in both shapes — and a render that stops
  after its own cleanup has removed the previous run's video and gif, even on
  the one path that exits without ``render_fail`` (a missing encoder). The
  tmux recipe's step 2 — the paste-alone re-attach — refuses a relative
  ``<capture-dir>`` because its
  claim is canonicalized while the pipe's command runs in the pm session's
  directory (the transcript lands nowhere the end-of-run check looks), and
  every other paste-alone step that resolves ``<capture-dir>`` for itself
  refuses one too: the tmux recipe's steps 3, 4 and 5 and the CLI scaffold's
  step 4 are each pasted into a fresh shell (the stop step "is usually a
  fresh one"), so a relative path wrote the cast where the recorder ran and
  the checks read somewhere else — a finished recording reported as
  "asciinema wrote no cast" / "recorder status is missing or empty", the
  driving step's pane save failing where its message pointed, and the CLI
  stop step killing the scaffold server that held the recording. The
  *usability* half is the same rule one shape over: an absolute path that is
  not there (step 0 never ran for it, a typo, a wrong ``<short-name>``) is a
  directory the run never used, so the same four steps refuse one before any
  tmux call — step 3 (which writes the cast, the stderr log and the status)
  on both permission bits, the read-only steps on ``-d`` and ``-x`` (a mode
  600 directory has no search bit, so its cast cannot be opened by name).
  Verified live in this container on tmux 3.2a and asciinema 2.1.0: step 3
  with a missing directory reported "recorder exited before it drew" for two
  files that cannot exist, step 5 detached a *live* recorder and then
  reported "asciinema wrote no cast" with a complete cast (status ``0``) one
  directory over, and the CLI step 4 reported the same and killed the
  scaffold server. Step 3 also asserts the *target session* exactly, like
  step 2: pasted on its own with only a grouped ``pm-test~1`` on the server,
  the recorder's exact attach failed, and the step reported "recorder exited
  before it drew" for a target that was never there, naming a 0-byte stderr
  log. The web-UI driver block refuses
  a capture directory that is missing or cannot be written or entered — its
  existence and permission checks run before its ``cd``, because a directory
  that exists and cannot be searched failed that ``cd`` and was reported as
  missing — so the link cannot land in the worker's cwd, a web-UI start that
  never answers removes the pid it
  recorded so the teardown cannot signal a recycled one, and the web-UI
  finalize step names a missing ``ffmpeg`` instead of reporting it as a
  failed transcode of the driver's webm; both recording recipes' render blocks
  refuse a missing or unwritable capture directory where they write, instead
  of reporting an unwritable one as "agg failed on the cast — is 'agg'
  installed?" (a remedy that runs and changes nothing) or a path that is not
  there as "the recording wrote nothing"; and a failure that *writes* has to
  say whether the write landed: the read-only steps' pane saves report "could
  not be saved" when the capture directory refuses the redirect, instead of
  naming a ``recorder-pane.log`` that does not exist (the state their
  ``-d``/``-x`` guard deliberately allows, R84), and so do the two *readiness*
  timeouts, whose save runs a whole bound after the step's own writability
  guard — a directory that became read-only, a full disk, or a recorder whose
  pane went away makes that redirect fail too, and the branch then kills the
  pane it claimed to have saved (R87/R93); and the CLI stop bound
  rejects a ``RECORDER_STOP_TIMEOUT`` too long for the 64-bit deadline
  arithmetic instead of letting the wrap remove the bound (R87);
- an input that exists but is empty is not an input, and that holds for the
  web-UI driver too: the driver block's "is ``driver.mjs`` here" check is
  ``-s``, not ``-f``, because an empty file is a *valid* ES module —
  ``node driver.mjs`` exits 0 having run nothing, so the block reports
  success and the finalize step then blames the driver's ``recordVideo``
  option with a re-run that passes again; the same rule governs the two
  *completion* handles, and both now have a case: the tmux recipe's
  ``test -s`` on ``transcript.log`` (a ``pipe-pane`` that opened the file
  but wrote nothing is not a transcript) and the web-UI finalize's
  "already finalized" state, which is a *non-empty* mp4 (an empty file is
  not a published video, and the step must not exit 0 presenting it as
  one);
- a remedy that runs but cannot work says so: the ``agg`` install stops when
  the binary it just downloaded still does not resolve (``~/.local/bin`` not
  on ``PATH``), instead of exiting 0 and sending the worker back to the same
  block from the render's "is 'agg' installed?", and the web-UI start block
  refuses a captures path it could not resolve rather than turning the empty
  answer into ``/scenarios/1/web-ui`` at the filesystem root;
- a scenario-driving step checks its own sends: the tmux recipe's example
  ``pm tui send`` lines are guarded (a mid-sequence failure was invisible,
  because the block's status is its last command's), and the CLI scaffold —
  which has no witness at all, since asciinema exits 0 whenever its recorded
  command ends — says that a failed ``send-keys`` means the recorded shell
  died before the behaviour under test and the capture must be re-run;
- a request that has no deadline cannot report a diagnosis: the web-UI port
  pre-check bounds each attempt because curl has no default deadline for a
  server that accepted the connection and never answers, so without its
  ``--max-time`` the "exit 28" branch is unreachable and the step blocks
  instead (the unbounded wait this PR removes everywhere else), and the
  protocol layer's route snapshots carry ``-w``'s status line, the only
  record of what each route answered — a 500, or ``[HTTP 000]`` for a route
  that timed out — which no case exercised; and a retry's
  cleanup takes the manifest with the outputs it presents, so a driver retried
  after an earlier attempt was finalized cannot fail and leave a manifest
  naming the video the cleanup deleted; and the web-UI start hands the app its
  own log: the app outlives the block, so a block whose output is a pipe (a
  captured step, ``bash < block | tee …``) did not return until the app
  exited — which only the teardown does — and the startup output the readiness
  failure pointed at was written nowhere. The launch redirects to ``app.log``
  and closes the block's stdin, the failure names the log, and step 1 clears a
  previous run's copy like the rest. Closing the app's stdin is the
  *interactive paste's* half — job control is on there, so a background app
  that reads the terminal eats the rest of the pasted block — while a
  ``bash < block`` run already gets ``/dev/null`` from bash itself; the case
  runs with ``set -m`` so it models the paste;
- every ending path ends the recorder it started, and the cleanup is a
  guarantee of its own: the CLI scaffold's ``kill-server`` on its readiness
  timeout, its three stop-path failures and its success, and the tmux
  recipe's ``kill-session`` in both timeout branches, at the end of a
  successful run, and in every failure branch that ends after the recorder's
  pane returned (a recorder that died before drawing, died mid-scenario,
  failed the detach, or finished with no cast, no status or no transcript).
  ``remain-on-exit on`` keeps the session after its pane returns — the state
  a successful run ends in, and the state every one of those failure branches
  ends in — so the pane's death does not remove it. Deleting any of those
  eight original statements left the whole file green until the two cleanup
  cases were added (review loop 928f i33, R98); the failure branches were
  still missed because the cleanup cases covered only the success and timeout
  paths, so a failed run left a dead ``pm-recorder`` behind until review loop
  928f i34 (R99) extended the same case to them;
- a clean status is not proof that the *stop step* ended the recording:
  asciinema's status is 0 whenever the recording ran to completion, and any
  detach ends it that way (the prefix pressed in the recorder pane, ``pm
  session --disconnect-others``, a supervisor detaching clients), leaving a
  cast that stops where the scenario was — the same state a re-paste of the
  tmux stop step legitimately sees, so the status alone cannot tell them
  apart. The capture-directory claim is the in-progress handle: a capture
  holds it from step 2 until the stop step's last statement releases it, so
  a re-paste finds it clear and a recorder that ended under a claim that is
  still set is failed with a message that names the early detach (review
  loop 928f i35, R100).

The capture flow's readiness and stop logic is also *executed* against stub
``tmux``/``pm`` (``TestCaptureFlowExecution``), because its failure modes are
silent: a wait that ends badly looks like a finished recording.
"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from pm_core.qa_instructions import list_artifacts

REPO_ROOT = Path(__file__).resolve().parents[1]
PM_ROOT = REPO_ROOT / "pm"
ARTIFACTS = PM_ROOT / "qa" / "artifacts"
RECIPES = ["tmux-screen-recording.md", "cli-recording.md"]

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash is required")

# A capture directory that exists and cannot be written into comes in two
# permission shapes, and every recipe guard tests both permission bits for
# that reason: mode 500 (`r-x------`) has no write bit, while mode 600
# (`rw-------`) *has* the write bit and no search bit — creating, reading or
# `cd`-ing into it still fails, and `[ -w ]` alone cannot see it. The guards
# are `[ -w … ] && [ -x … ]`; running each writability case in both shapes is
# what keeps the `-x` half from being the untested one (removing it left the
# whole file green: mode 500 is refused by `-w` either way).
UNWRITABLE_MODES = pytest.mark.parametrize(
    "capdir_mode", [0o500, 0o600], ids=["no-write-bit", "no-search-bit"])


def _recipe_text(name):
    return (ARTIFACTS / name).read_text()


def _scaffold_block(text):
    """The capture-section fenced block that starts the recorder.

    Identified by ``new-session`` so it is the block a worker actually pastes
    for the no-TTY path, not one of the shorter command-form examples.
    """
    section = text.split("## Capture", 1)[1].split("## Render to video", 1)[0]
    for block in re.findall(r"```[a-z]*\n(.*?)```", section, re.S):
        if "new-session" in block:
            return block
    raise AssertionError("no recorder scaffold block found")


def _render_block(name):
    """The fenced block under ``## Render to video`` that renders the cast.

    Selected by its own content (``agg --idle-time-limit``), not by position:
    the section also documents the renderer prerequisite, which is itself a
    fenced block.
    """
    section = _recipe_text(name).split("## Render to video", 1)[1]
    for block in re.findall(r"```[a-z]*\n(.*?)```", section, re.S):
        if "agg --idle-time-limit" in block:
            return block
    raise AssertionError(f"{name}: no render block found")


def _statement(block, start_marker):
    """One shell statement from ``block``, joining its backslash continuations.

    The scaffold statements span several lines, and what follows them is not
    always a blank line, so the end is the first line without a trailing
    backslash. A statement that opens a ``{`` brace group (the recorder start,
    which reports a failed ``new-session``) carries on to its closing ``}``.
    """
    lines = []
    rest = iter(block[block.index(start_marker):].splitlines())
    for line in rest:
        lines.append(line)
        if not line.rstrip().endswith("\\"):
            break
    if lines[-1].rstrip().endswith("{"):
        for line in rest:
            lines.append(line)
            if line.strip() == "}":
                break
    return "\n".join(lines)


def _stub_tool(bindir, name, body="exit 1\n"):
    path = bindir / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


def _expand_tilde(path, home):
    """Resolve a leading ``~`` the way the block's own shell does.

    The recipes accept a ``~/…`` capture directory, and their shells expand
    it. A stub receives its paths through variables, where a tilde is *not*
    expanded (``out='~/cap/x'; cat >> "$out"`` writes to a literal ``~``
    directory), so a case that runs a block with ``~/cap`` has to give the
    stub and this helper's own file operations the expanded spelling while
    the block text keeps what a worker typed.
    """
    s = str(path)
    if home and (s == "~" or s.startswith("~/")):
        return Path(str(home) + s[1:])
    return Path(s)


def _drive_recorder_statement(stmt, tmp_path, env_extra=None, asci_body=None):
    """Run a scaffold's recorder statement, then its pane command.

    ``stmt`` is the recipe's own ``tmux ... new-session`` statement. A stub
    ``tmux`` captures the argv, so the last argument is the command tmux runs
    with ``sh -c``; that command is then run against a stub ``asciinema`` that
    records its argv and exits 7 (``asci_body`` overrides that stub, e.g. to
    make asciinema write to stderr). Returns ``(pane command, asciinema argv
    path)`` so a caller can assert on either layer.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    tmux_argv = tmp_path / "tmux-argv"
    asci_argv = tmp_path / "asciinema-argv"
    _stub_tool(bindir, "tmux", f'printf "%s\\n" "$@" > "{tmux_argv}"\n')
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               **(env_extra or {}))
    r = subprocess.run(["bash", "-c", stmt], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    recorder_cmd = tmux_argv.read_text().splitlines()[-1]
    _stub_tool(bindir, "asciinema", asci_body or (
        f'printf "%s\\n" "$@" > "{asci_argv}"\nexit 7\n'))
    subprocess.run(["sh", "-c", recorder_cmd], env=env,
                   capture_output=True, text=True)
    return recorder_cmd, asci_argv


class TestRecipes:
    @pytest.mark.parametrize("name", RECIPES)
    def test_recipe_is_listed(self, name):
        ids = {item["id"] for item in list_artifacts(PM_ROOT)}
        assert Path(name).stem in ids

    @pytest.mark.parametrize("name", RECIPES + ["web-ui-recording.md"])
    def test_manifest_example_names_the_recipe(self, name):
        """Every recipe's manifest template carries the shared `recipe:` field.

        ``pm_core/docs/qa_library.md`` documents the manifest convention with
        ``recipe: pm/qa/artifacts/<recipe-filename>.md``, and the CLI and
        web-UI templates carry it — the tmux template did not, so a worker
        copying that example writes a manifest that does not say which recipe
        produced the capture. The field is how a reviewer (or a later agent)
        knows which flow to follow when replaying the evidence.
        """
        section = _recipe_text(name).split("## Manifest format", 1)[1]
        assert f"recipe: pm/qa/artifacts/{name}" in section, (
            f"{name}: the manifest template omits the recipe field the shared "
            "convention (pm_core/docs/qa_library.md) documents")

    @pytest.mark.parametrize("name", RECIPES)
    def test_recipe_lists_its_diagnostic_files(self, name):
        """The flow writes diagnostics the produced-files list never names.

        Both capture flows write ``recorder.status`` and
        ``recorder-stderr.log`` into the capture directory (and
        ``recorder-pane.log`` when a wait gives up), while the recipe's
        manifest section asks for "every non-default file the capture
        produced". A worker reading only the produced-files list does not
        know they exist, so the manifest's ``## Files`` section and the
        directory disagree — the "promised artifact never documented" class
        this recipe keeps hitting.
        """
        section = _recipe_text(name).split(
            "## What this recipe produces", 1)[1].split("## Capture", 1)[0]
        for fname in ("recorder.status", "recorder-stderr.log",
                      "recorder-pane.log"):
            assert fname in section, (
                f"{name}: the produced-files list never names {fname}, which "
                "the capture flow writes into the capture directory")

    @pytest.mark.parametrize("name", RECIPES)
    def test_produced_files_list_names_the_render_partials(self, name):
        """A killed render leaves two files the produced-files list never named.

        ``render_cast`` encodes to ``recording.mp4.partial.mp4`` and renames it
        onto ``recording.mp4`` only after a complete encode, and deletes the
        intermediate ``recording.cast.gif`` only after that rename. A render
        killed while ``ffmpeg`` runs (the worker or its session torn down)
        reaches no cleanup at all, so both stay in the capture directory —
        verified in this container with the recipes' own render blocks and a
        stub encoder: after SIGKILL of the render shell the directory holds
        ``recording.cast``, ``recording.cast.gif`` and
        ``recording.mp4.partial.mp4``.

        Step 0 clears both names before the next capture and the render notes
        tell the worker to label and list a partial it keeps, but the
        produced-files list and the manifest's ``## Files`` example named
        neither — so a worker building the manifest from them leaves out
        files the directory holds, and the partial is the one that looks like
        this run's video. The web-UI recipe names its equivalent partial for
        exactly this reason (R62/R66); this is the same list, one render step
        over. The names are derived from the render block, like the step-0
        cleanup case: ``$cast.gif`` and ``$mp4.partial.mp4`` are what the
        block actually writes.
        """
        text = _recipe_text(name)
        cast_rel = re.search(r"^cast=(\S+)$", _render_block(name),
                             re.M).group(1)
        intermediate = Path(cast_rel).name + ".gif"          # "$cast.gif"
        partial = Path(cast_rel).stem + ".mp4.partial.mp4"   # "$mp4.partial.mp4"
        produced = text.split("## What this recipe produces", 1)[1].split(
            "## Capture", 1)[0]
        manifest = text.split("## Manifest format", 1)[1].split(
            "## Reviewing", 1)[0]
        for fname in (partial, intermediate):
            assert fname in produced, (
                f"{name}: the produced-files list never names {fname}, which a "
                "render killed mid-encode leaves in the capture directory")
            assert fname in manifest, (
                f"{name}: the manifest's `## Files` example does not name "
                f"{fname}, so a worker copying it leaves out a file the "
                "capture directory holds")

    @pytest.mark.parametrize("name", RECIPES)
    def test_capture_section_creates_the_capture_dir(self, name):
        """The capture dir must be created before asciinema writes into it.

        ``asciinema rec`` prints "asciicast saved" and exits 0 when the
        parent directory is missing — it writes nothing — so a recipe that
        only names the path produces a capture that looks successful and
        does not exist. It has to be in a runnable block, not just in the
        prose: a worker that pastes a block skips prose-only steps. Both
        recipes put it in the *first* block of the capture section, so every
        form below it (the CLI one-command and ``bash -c`` forms included)
        is preceded by it.
        """
        text = _recipe_text(name)
        section = text.split("## Capture", 1)[1].split("## Render to video", 1)[0]
        first_block = re.findall(r"```[a-z]*\n(.*?)```", section, re.S)[0]
        assert "mkdir -p <capture-dir>" in first_block, (
            f"{name}: the first runnable capture block does not create the "
            "capture directory")
        block = _scaffold_block(text)
        mkdir = block.find("mkdir -p <capture-dir>")
        assert mkdir != -1, (
            f"{name}: the runnable scaffold never creates the capture dir")
        assert mkdir < block.index("asciinema rec"), (
            f"{name}: the capture dir is created only after recording starts")
        # The command, not the bare word: the recipe's prose and failure
        # messages mention "pipe-pane" too.
        if "tmux pipe-pane" in block:
            assert mkdir < block.index("tmux pipe-pane"), (
                f"{name}: the capture dir is created after the transcript "
                "pipe opens, so the transcript is lost")

    @pytest.mark.parametrize("name", RECIPES)
    def test_capture_section_removes_a_stale_cast(self, name):
        """An earlier run's cast must not be rendered as this run's capture.

        The render step rewrites the ``.mp4`` from whatever cast is on disk,
        so a recording that silently wrote nothing (``asciinema`` exits 0
        after "asciicast saved" even with no directory; without
        ``--overwrite`` it aborts on an existing file) would still produce a
        *fresh* mp4 — of the previous run. Deleting the cast first is what
        makes a failed recording fail the render instead.
        """
        text = _recipe_text(name)
        section = text.split("## Capture", 1)[1].split("## Render to video", 1)[0]
        first_block = re.findall(r"```[a-z]*\n(.*?)```", section, re.S)[0]
        assert re.search(r"^rm -f [^\n]*recording\.cast", first_block, re.M), (
            f"{name}: the first runnable capture block keeps an earlier cast, "
            "so a form below it can render the previous run")
        block = _scaffold_block(text)
        rm = re.search(r"^rm -f [^\n]*recording\.cast", block, re.M)
        assert rm, f"{name}: scaffold never removes an earlier cast"
        start = block.index("asciinema rec")
        assert rm.start() < start, (
            f"{name}: the stale cast is removed only after the recorder starts")

    def test_tmux_capture_section_removes_a_stale_transcript(self):
        """The transcript is appended to, so an earlier run's log would mix in.

        ``tmux pipe-pane ... "cat >> transcript.log"`` appends: re-running
        the recipe in the same capture directory leaves a log holding both
        runs, so a recording that produced nothing still has a transcript
        that looks like this run's evidence.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        rm = re.search(r"^rm -f [^\n]*transcript\.log", block, re.M)
        assert rm, "tmux recipe never removes an earlier transcript.log"
        assert rm.start() < block.index("tmux pipe-pane"), (
            "the stale transcript is removed only after the pipe is attached")

    @pytest.mark.parametrize("name", RECIPES)
    def test_capture_block_clears_a_stale_failure_log(self, name):
        """An earlier run's failure evidence must not be read as this run's.

        ``recorder-stderr.log`` is written by the pane command and
        ``recorder-pane.log`` by a failing wait, so a run that failed before
        either could be written would leave the previous run's reason on disk
        — the same stale-artifact bug as the cast, one file over.
        """
        block = _scaffold_block(_recipe_text(name))
        rm = _statement(block, "rm -f ")
        for artifact in ("recorder-stderr.log", "recorder-pane.log"):
            assert artifact in rm, (
                f"{name}: an earlier run's {artifact} survives, so a run that "
                "never wrote one can present the previous run's failure as "
                "its own")

    @pytest.mark.parametrize("name", RECIPES)
    def test_capture_section_clears_the_previous_video(self, name):
        """A failed capture must not leave the previous run's mp4 in place.

        The render step clears ``recording.mp4`` and its intermediate gif
        before rendering, but a capture that *fails* exits before that step
        ever runs — so without this the capture directory keeps the earlier
        run's video, and the manifest and the sign-off report present it as
        this run's recording. That is the same stale-evidence bug as a
        leftover cast, one step earlier (the web-UI recipe clears its mp4 in
        step 1 for exactly this reason).

        The gif's name is *derived from the render block*, not written out
        here: the block holds the cast in ``cast=<capture-dir>/…/recording.cast``
        and renders to ``"$cast.gif"``, so the intermediate is
        ``recording.cast.gif`` — a cleanup (and a test) naming
        ``recording.gif`` removes and checks a file nothing ever writes, and
        the earlier run's real intermediate survives. That is what the
        pre-fix recipes did.

        The interrupted render's partial goes with them. ``render_cast``
        encodes to ``"$part"`` (``$mp4.partial.mp4``) and renames it only
        after a successful encode, so a render killed before that rename
        leaves ``recording.mp4.partial.mp4`` behind and no failure path of
        that render ever runs; a later capture that fails before its own
        render would present the earlier partial as this run's evidence.
        """
        text = _recipe_text(name)
        render = _render_block(name)
        cast_rel = re.search(r"^cast=(\S+)$", render, re.M).group(1)
        assert '"$cast.gif"' in render, (
            f"{name}: the render block no longer renders to `$cast.gif`; this "
            "test derives the intermediate's name from that expression")
        assert '"$mp4.partial.mp4"' in render, (
            f"{name}: the render block no longer encodes to `$mp4.partial.mp4`; "
            "this test derives the partial's name from that expression")
        intermediate = cast_rel + ".gif"
        partial = Path(cast_rel).stem + ".mp4.partial.mp4"
        section = text.split("## Capture", 1)[1].split("## Render to video", 1)[0]
        first_block = re.findall(r"```[a-z]*\n(.*?)```", section, re.S)[0]
        rm = _statement(first_block, "rm -f ")
        assert "recording.mp4" in rm, (
            f"{name}: the first capture block keeps an earlier run's "
            "recording.mp4, so a capture that fails before the render step "
            "leaves the previous run's video as this run's")
        assert intermediate in rm, (
            f"{name}: the first capture block keeps an earlier run's "
            f"{intermediate} (the file the render block actually writes), so "
            "a capture that fails before the render step leaves the previous "
            "run's video as this run's")
        assert partial in rm, (
            f"{name}: the first capture block keeps an interrupted render's "
            f"{partial}, so a later capture that fails before its own render "
            "presents the earlier partial as this run's evidence")
        scaffold_rm = _statement(_scaffold_block(text), "rm -f ")
        assert "recording.mp4" in scaffold_rm, (
            f"{name}: the scaffold's own cleanup keeps an earlier run's "
            "recording.mp4")
        assert intermediate in scaffold_rm, (
            f"{name}: the scaffold's own cleanup keeps an earlier run's "
            f"{intermediate}")
        assert partial in scaffold_rm, (
            f"{name}: the scaffold's own cleanup keeps an interrupted "
            f"render's {partial}")
        assert "recording.gif" not in rm + scaffold_rm, (
            f"{name}: the cleanup names `recording.gif`, which nothing writes "
            f"— the intermediate is `{intermediate}`")

    @pytest.mark.parametrize("name", RECIPES)
    def test_capture_section_clears_the_previous_manifest(self, name):
        """The manifest is the one produced file the cleanup did not clear.

        It is the document that says what the capture is — workdir, the
        commands, the ``## Files`` list — so a re-run that fails before the
        worker writes a new one leaves the previous run's manifest in the
        capture directory describing a cast and a video that the step-0
        ``rm`` has just deleted. A manifest that disagrees with the directory
        is the same "stale evidence presented as this run's" bug as a leftover
        cast, in the file that interprets all the rest (and the QA report
        enumerates the capture directory). Every other artifact is cleared
        here already; ``driver.mjs`` in the web-UI recipe is the counterpart
        that is deliberately kept, because it is the run's input, not its
        evidence.
        """
        text = _recipe_text(name)
        section = text.split("## Capture", 1)[1].split("## Render to video", 1)[0]
        first_block = re.findall(r"```[a-z]*\n(.*?)```", section, re.S)[0]
        assert "manifest.md" in _statement(first_block, "rm -f "), (
            f"{name}: the first capture block keeps an earlier run's "
            "manifest.md, so a re-run that fails before a new one is written "
            "leaves a manifest describing the previous run")
        assert "manifest.md" in _statement(_scaffold_block(text), "rm -f "), (
            f"{name}: the scaffold's own cleanup keeps an earlier run's "
            "manifest.md, so a scaffold-only paste has the same hole")

    def test_cli_capture_section_clears_a_stale_transcript(self):
        """The `tee` fallback's transcript must not survive into a later run.

        ``tee`` truncates, so a fallback run does not append — but a run that
        takes the cast path writes no transcript at all, and the produced-files
        list names ``transcript.log``, so the earlier fallback run's output
        would be presented as this run's. The tmux recipe clears its
        transcript for the same reason (there it is appended to).
        """
        text = _recipe_text("cli-recording.md")
        section = text.split("## Capture", 1)[1].split("## Render to video", 1)[0]
        first_block = re.findall(r"```[a-z]*\n(.*?)```", section, re.S)[0]
        assert "transcript.log" in _statement(first_block, "rm -f "), (
            "cli-recording: the first capture block keeps an earlier run's "
            "transcript.log, which the produced-files list names")
        assert "transcript.log" in _statement(_scaffold_block(text), "rm -f "), (
            "cli-recording: the scaffold keeps an earlier run's transcript.log")

    def test_tmux_readiness_wait_targets_the_computed_session(self):
        """The pm-session poll must not match the recipe's own recorder.

        ``tmux ls | grep '^pm-'`` also matches ``pm-recorder`` — the session
        this very recipe creates — and any other project's pm session, so
        the wait can pass before the target exists and its failure path
        never fires. ``tmux has-session -t "=$TARGET"`` is the actual
        handle; an empty target must be rejected first because
        ``tmux has-session -t ''`` succeeds, and the `=` is what makes the
        handle exact — a bare name is prefix-matched, so it would also pass
        on pm's grouped ``<base>~N`` session.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        assert 'has-session -t "=$TARGET"' in block, (
            "tmux recipe does not wait on the exact computed session handle")
        assert 'has-session -t "$TARGET"' not in block, (
            "tmux recipe targets the session by bare name, which tmux "
            "prefix-matches (it matches pm's grouped <base>~N session)")
        assert "grep -q '^pm-'" not in block and "until tmux ls" not in block, (
            "tmux recipe still matches any pm- session (incl. pm-recorder)")
        target = block.index("TARGET=$(pm session name)")
        guard = block.index('[ -n "$TARGET" ]')
        wait = block.index('until tmux has-session -t "=$TARGET"')
        assert target < guard < wait, (
            "the empty-TARGET guard must come before the has-session wait")

    def test_tmux_pm_session_failure_names_evidence_that_exists(self):
        """The readiness failure must not point at output the block discarded.

        Step 1 backgrounds ``pm session`` with ``>/dev/null 2>&1``, so
        "check 'pm session' output" sends the worker to output that was
        thrown away — the same class as the failure messages that named a
        recorder pane the next line destroyed. The message has to say the
        output was discarded and name a form the worker can actually read.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        assert "pm session >/dev/null 2>&1" in block, (
            "the readiness failure's remedy assumes 'pm session' output is "
            "still available")
        idx = block.index("did not appear within")
        window = block[max(0, idx - 200):idx + 300]
        assert "discarded" in window, (
            "tmux recipe tells the worker to check 'pm session' output "
            "although step 1 redirected that output to /dev/null: " + window)

    @pytest.mark.parametrize("name,cleanup,start", [
        ("tmux-screen-recording.md",
         'kill-session -t "=pm-recorder"', "new-session -d -s pm-recorder"),
        ("cli-recording.md", "kill-session -t rec", "new-session -d -s rec"),
    ])
    def test_stale_recorder_is_cleared_before_start(self, name, cleanup, start):
        """A leftover recorder from an earlier run must be cleared first.

        ``new-session`` fails with "duplicate session" while the previous
        run's recorder is still there, so a leftover has to be cleared (the
        CLI scaffold's ``kill-session``) or refused (the tmux recipe's step
        3, which stops at "a recorder is already running on this server …"
        and names step 5 while the recorder's *pane* is still running); a
        duplicate that appears in the gap before
        ``new-session`` is reported as "could not start the recorder
        session", and either way a re-run ends before recording anything.
        (Before that check the run carried on, but not into a false pass: the
        tmux readiness wait took the *old* session's pane content as
        readiness and drove the previous run's attach client, while the CLI
        wait — which is on the cast file, and step 0 clears it — ran out its
        deadline against a ``rec`` session that never wrote a cast.) Clearing
        the session up front (or refusing the live one) is what makes a
        re-run deterministic, and the start check is what makes a duplicate
        loud if a concurrent run recreates it after the clear.

        The CLI scaffold clears the *session*, not the server: killing a
        server and reconnecting a few milliseconds later races its exit and
        fails with "server exited unexpectedly" (reproduced ~7 times in 40
        tight iterations), so `kill-server` belongs only in the teardown
        paths.
        """
        block = _scaffold_block(_recipe_text(name))
        assert cleanup in block, f"{name}: no stale recorder cleanup"
        start_at = block.index(start)
        assert block.index(cleanup) < start_at, (
            f"{name}: the stale recorder is cleared only after starting a new one")
        if cleanup == "kill-session -t rec":
            # An executed `kill-server`, not the remedy the refusal messages
            # name in prose (which sits before the start too).
            kill_server = re.search(r"^\s*tmux\b[^\n]*kill-server", block, re.M)
            assert kill_server and kill_server.start() > start_at, (
                "cli-recording: kill-server before new-session races the "
                "server's exit; clear the session instead")

    def test_step_three_clears_the_previous_attempt_before_it_starts(self):
        """The recorder-start step is also the restart step, so it clears.

        Step 3 is pasted on its own to restart a recorder, and the attempt
        being replaced left its cast, its status and its stderr log in the
        capture directory (step 0 clears them only for a fresh run). The
        order matters: a recorder whose *pane* is still running owns the cast
        it is writing, so the step refuses it first, and only then clears the
        replaced attempt's files — before `new-session`, because
        `asciinema rec` refuses an existing cast. A leftover whose pane has
        returned is cleared instead of refused (R96).
        """
        block = _step_three_block()
        start = block.index("tmux new-session -d -s pm-recorder")
        refuse = block.index('if tmux has-session -t "=pm-recorder"')
        pipe = block.index("pane_pipe")
        clear = block.index("rm -f <capture-dir>/recording.cast")
        assert refuse < pipe < clear < start, (
            "step 3 must refuse a live recorder before it clears anything, "
            "refuse a restart without step 2's transcript pipe before it "
            "clears anything, and clear the replaced attempt before it "
            "starts a new one")
        cleared = set(block[clear:start].replace("\\", " ").split())
        for name in ("recording.cast", "recorder.status",
                     "recorder-stderr.log", "recorder-pane.log",
                     "recording.mp4", "recording.cast.gif",
                     "recording.mp4.partial.mp4", "manifest.md"):
            # Exact names, not substrings: `recording.mp4` must not be
            # satisfied by `recording.mp4.partial.mp4`.
            assert f"<capture-dir>/{name}" in cleared, (
                f"step 3 does not clear {name} before it starts a recorder, "
                "so the restart inherits the attempt it replaces")

    def test_tmux_session_handles_are_exact(self):
        """Every session target needs tmux's ``=``, not a bare name.

        A bare name is *prefix*-matched when no session has the whole name
        (verified on tmux 3.2a), and the tmux server this recipe runs on is
        the one pm uses: pm's sessions are ``pm-<repo>-<hash>``, so a project
        whose repo name starts with ``recorder`` has a session a bare
        ``pm-recorder`` target matches. Step 0's clear runs on every capture,
        when no exact recorder exists — verified live: the recipe's own step 0
        killed a ``pm-recorder-abc123`` session (standing in for another
        project's pm TUI session, or this capture's own target when the repo
        is named ``recorder``) and took the server down with it, silently
        (``2>/dev/null``, ``|| true``). The other handles are the same class:
        with this run's recorder gone, a prefix session would satisfy the
        readiness check (its pane read as "the TUI drew"), receive the detach
        key, and be killed at the stop timeout. ``capture-pane`` and
        ``send-keys`` only honour ``=`` with an explicit pane spec (verified:
        ``-t "=pm-recorder"`` answers "can't find pane" while
        ``-t "=pm-recorder:0.0"`` resolves). The attach is the handle that
        actually records: bare, it lands on a grouped ``<base>~N`` session
        when the target has ended, and the run reports that as success.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        for bare in ("has-session -t pm-recorder",
                     "capture-pane -p -t pm-recorder",
                     "send-keys -t pm-recorder",
                     "kill-session -t pm-recorder",
                     "attach -t $TARGET",
                     'pipe-pane -t "$TARGET',
                     'show-options -t "$TARGET',
                     'set-option -t "$TARGET',
                     'set-option -u -t "$TARGET'):
            assert bare not in block, (
                f"tmux recipe targets a session with a bare name ({bare!r}), "
                "which tmux prefix-matches — it would act on another session "
                "(pm's pm-recorder-<hash>, or a grouped <base>~N)")
        for exact in ('has-session -t "=pm-recorder"',
                      'capture-pane -p -t "=pm-recorder:0.0"',
                      'send-keys -t "=pm-recorder:0.0"',
                      'kill-session -t "=pm-recorder"',
                      "attach -t =$TARGET",
                      'pipe-pane -t "=$TARGET:0.0"',
                      'show-options -t "=$TARGET:0.0"',
                      'set-option -t "=$TARGET:0.0" @pm_capture_dir',
                      'set-option -u -t "=$TARGET:0.0" @pm_capture_dir'):
            assert exact in block, (
                f"tmux recipe does not use the exact session handle {exact!r}")

    def test_transcript_pipe_can_be_reattached(self):
        """``pipe-pane -o`` is a silent no-op while a pipe is already attached.

        A pipe left behind by an aborted run would make step 2 do nothing,
        so ``transcript.log`` is never written and the capture silently
        loses its transcript while the cast check still passes. Without
        ``-o`` the pipe is replaced (and the old one closed), which is what
        a re-run wants.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        pipe = re.search(
            r"^tmux pipe-pane[^\n]*transcript\.log[^\n]*$", block, re.M)
        assert pipe, "tmux recipe never streams the transcript"
        assert " -o " not in pipe.group(0), (
            "tmux recipe attaches the transcript pipe with -o: a leftover "
            "pipe from an earlier run silently prevents transcript.log")

    def test_tmux_transcript_is_required_and_checked(self):
        """The transcript is a promised artifact, so a run without one fails.

        ``-o`` was only one way for the transcript to go missing: the attach
        itself can fail (the pane is gone, tmux cannot spawn the command) and
        ``pipe-pane`` can accept the attach while nothing is ever written. In
        both cases ``transcript.log`` is missing or empty while the cast check
        passes — the manifest then lists a transcript this run never produced,
        the same "the promised artifact is not there" bug as rendering a stale
        cast. The attach's failure is reported where it happens, and the file
        is checked before the run is declared finished.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        assert re.search(r"transcript\.log\" \|\| \{", block), (
            "tmux recipe ignores a failed pipe-pane, so the transcript is "
            "lost silently")
        assert "could not stream" in block, (
            "a failed transcript pipe has no actionable message")
        assert "test -s <capture-dir>/transcript.log" in block, (
            "tmux recipe never checks that this run wrote a transcript")

    def test_tmux_recorder_exiting_before_it_draws_fails(self):
        """A recorder that exits before drawing recorded nothing.

        The pane is started *as* the asciinema command, so a session that
        vanishes during the readiness wait means the attach never ran. The
        cast it leaves holds asciinema's error rather than the TUI, so
        carrying on would drive keys into nothing and then report a useless
        capture as a successful recording.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        seg = block[block.index("new-session -d -s pm-recorder"):
                    block.index("pm tui send")]
        assert '! tmux has-session -t "=pm-recorder"' in seg, (
            "tmux recipe does not notice a recorder that exits before drawing")
        assert "recorder exited before it drew" in seg
        assert "exit 1" in seg, "a dead recorder is not reported as a failure"

    def test_tmux_failed_attach_error_text_is_not_readiness(self):
        """A failed attach draws its error into the pane before it exits.

        ``tmux attach`` to a session that is not there prints "can't find
        session: …" into the recorder pane and then exits, so the
        pane-content readiness check can break on *asciinema's own error
        text* rather than a drawn TUI — and step 5's cast check then passes
        on a cast that holds that error, reporting a useless capture as
        success. Verified live: the error is drawn ~50-75 ms after
        ``new-session`` and the session is gone ~25 ms later, so a tight poll
        takes it as readiness in 15 of 15 runs (the recipe's own 0.2 s
        cadence usually misses the window, which is why the failure is
        timing-dependent rather than frequent). The recipe has to confirm
        the recorder is still alive a moment after the content appears.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        seg = block[block.index("new-session -d -s pm-recorder"):
                    block.index("pm tui send")]
        loop_end = seg.index("\ndone\n", seg.index("recorder did not come up"))
        settle = seg[loop_end:]
        assert re.search(r"^sleep ", settle, re.M), (
            "tmux recipe treats the first pane content as a drawn TUI with no "
            "settle window, so a failed attach's error text passes readiness")
        assert '! tmux has-session -t "=pm-recorder"' in settle, (
            "tmux recipe does not re-check the recorder after it drew")
        assert "recorder exited before it drew" in settle
        assert "exit 1" in settle, (
            "a recorder that died after drawing is not reported as a failure")

    def test_tmux_recorder_dying_mid_scenario_fails(self):
        """A recorder gone before the detach did not finish the recording.

        The stop step's completion signal is the recorder *pane* ending
        *after* the detach (the session's end is its usual consequence; a
        server with `remain-on-exit` keeps it, which is why the step reads
        `#{pane_dead}` too). The attach client follows the session, so it
        exits only on the detach, when the session ends, or because it (or
        asciinema) died. A recorder that is already gone while the session it
        was attaching to is still there therefore died mid-scenario: the cast
        stops wherever it stopped, and the ``test -s`` check below would pass
        on that truncated cast and report the run as a successful recording.
        A recorder that ended because the session ended is a legitimate
        finish, so the recipe has to tell the two apart.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        seg = block[block.index("# 5."):
                    block.index('tmux send-keys -t "=pm-recorder:0.0"')]
        assert '! tmux has-session -t "=pm-recorder"' in seg, (
            "tmux recipe detaches without noticing that the recorder is "
            "already gone, so a truncated cast passes the `test -s` check")
        assert 'tmux has-session -t "=$TARGET"' in seg, (
            "tmux recipe cannot tell a recorder that died mid-scenario apart "
            "from one that ended because the session ended (and a bare name "
            "is prefix-matched, so pm's grouped <base>~N session would stand "
            "in for the target)")
        assert "incomplete" in seg and "exit 1" in seg, (
            "a recorder that died mid-scenario is not reported as a failure")

    def test_tmux_driving_step_warns_about_a_failed_send(self):
        """A failed ``pm tui send`` leaves a cast that never showed the behaviour.

        Step 5 treats "recorder gone *and* target gone" as a legitimate finish
        (the attach client follows the session out), so a TUI that dies
        mid-scenario — a crash, not the scenario quitting pm — ends in exactly
        that state and the run passes on a cast that stops before the behaviour
        under test. Only the driving step can tell the two apart, because its
        own ``pm tui send`` is the thing that failed, and the example lines the
        recipe hands the worker are unchecked. The recipe has to say so.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        seg = block[block.index("# 4."):block.index("# 5.")]
        assert "pm tui send" in seg
        assert "`pm tui send` that fails" in seg, (
            "the driving step does not warn that a failed pm tui send means "
            "the scenario never ran, so the both-gone finish in step 5 passes "
            "a capture that never showed the behaviour: " + seg)

    def test_cli_driving_step_warns_about_a_failed_send(self):
        """The CLI pane has no witness, so a dead recorded shell looks finished.

        The tmux recipe's driving step warns that a failed send means the
        scenario never ran (step 5 cannot tell a crashed TUI from the scenario
        quitting pm). The CLI scaffold has the same hole and no step-5 witness
        at all: asciinema exits 0 whenever its recorded command ends, whether
        the shell was driven to ``exit`` or died first, so a cast that stops
        before the behaviour under test passes every check. Its driving step
        is prose (the worker types its own sends), so the warning has to be
        there.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        seg = block[block.index("# 3. Drive"):block.index("# 4. Wait")]
        assert "send-keys" in seg
        assert "Check each send" in seg, (
            "the CLI driving step does not say to check its sends: " + seg)
        assert "asciinema exits 0" in seg, (
            "the warning does not say why step 4 cannot catch a dead shell "
            "(asciinema's status is 0 either way): " + seg)
        assert "Re-run" in seg, (
            "the CLI driving step does not say what to do about it: " + seg)

    def test_tmux_recorder_readiness_is_bounded(self):
        """The recorder readiness wait needs its own deadline.

        The pm-session poll earlier in the block also sets ``deadline``, so
        finding the word anywhere in the block would pass even with the
        recorder wait unbounded. Anchor on the recorder loop: a recorder that
        never draws has to fail with its own message rather than hang.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        seg = block[block.index("new-session -d -s pm-recorder"):
                    block.index("pm tui send")]
        loop_start = seg.index("while :; do")
        loop = seg[loop_start:seg.index("\ndone\n", loop_start)]
        assert "deadline" in loop, "tmux recorder readiness wait is unbounded"
        assert "did not come up within" in loop, (
            "tmux recorder readiness wait has no actionable timeout message")
        assert "exit 1" in loop, "the readiness timeout does not fail the run"

    @pytest.mark.parametrize("name", RECIPES)
    def test_scaffold_block_parses(self, name):
        """The no-TTY scaffold must be runnable shell, not just prose."""
        block = (_scaffold_block(_recipe_text(name))
                 .replace("<capture-dir>", "/tmp/cap")
                 .replace("<short-name>", "run")
                 .replace("<command-to-record>", "true"))
        r = subprocess.run(["bash", "-n"], input=block,
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{name} scaffold block:\n{r.stderr}\n{block}"

    @pytest.mark.parametrize("name,ready_marker", [
        # The tmux recorder must have *drawn* before keys are sent: the pane
        # is the attach client, and the cast exists before it renders.
        ("tmux-screen-recording.md", "capture-pane"),
        # The CLI pane is the recording itself, and asciinema writes the
        # cast header as soon as it starts — that, not pane content, is the
        # handle (a quiet command draws nothing but records fine).
        ("cli-recording.md", "recording.cast ]"),
    ])
    def test_recorder_is_ready_before_keys_are_sent(self, name, ready_marker):
        """Keystrokes sent before the recorder is up are silently dropped.

        Driving the recorded shell (or detaching the recorder) right after
        ``new-session`` races asciinema's startup: the keys vanish, the
        recording keeps running, and the only symptom is a stop-step
        timeout. A bounded readiness wait on the recorder's own handle
        removes the race without polling a process name.
        """
        block = _scaffold_block(_recipe_text(name))
        ready = block.find(ready_marker)
        assert ready != -1, f"{name}: no recorder readiness wait"
        first_key = min(
            i for i in (block.find("send-keys"), block.find("pm tui send"))
            if i != -1)
        assert ready < first_key, (
            f"{name}: keys are sent before the recorder readiness wait")
        assert "deadline" in block[:first_key], (
            f"{name}: readiness wait is unbounded")

    @pytest.mark.parametrize("name", RECIPES)
    def test_recorder_stop_is_bounded_and_cast_is_checked(self, name):
        """The stop step must wait on the recorder, not just kill the pane.

        Tearing the pane down under a still-running recorder can truncate
        the cast, and nothing else in the recipe proves the recording
        finished. ``has-session`` is the recorder's real handle (the pane is
        started *as* the asciinema command), so the wait is bounded and
        name-free.

        Anchored on the *last* ``while ... has-session ... done`` loop: the
        readiness wait earlier in the block is also a ``has-session`` poll,
        so a looser assertion would still pass with the stop wait deleted.
        """
        block = _scaffold_block(_recipe_text(name))
        waits = list(re.finditer(
            r"^while .*has-session[^\n]*; do$", block, re.M))
        assert waits, f"{name}: stop step does not wait for the recorder to exit"
        stop = block[waits[-1].start():]
        body = stop[:stop.index("\ndone")]
        assert "deadline" in body, f"{name}: recorder wait is unbounded"
        assert "exit 1" in body, f"{name}: recorder wait has no failure path"
        assert "test -s" in stop[len(body):], (
            f"{name}: the cast is not checked after the recorder exits")

    def test_cli_stop_ends_the_recorded_shell(self):
        """Ctrl-C reaches the *recorded* command, not asciinema.

        With ``-c bash`` the recorded command is bash, so a Ctrl-C at the
        pane is swallowed by it and the recording keeps running; the
        interactive form has to be ended with ``exit``.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        assert re.search(r"send-keys[^\n]*'exit' Enter", block), (
            "cli-recording: an interactive `bash` recording needs `exit`")
        assert "does not stop the recording" in block, (
            "cli-recording: must say Ctrl-C does not stop the recording")

    def test_cli_readiness_waits_on_the_cast_not_pane_content(self):
        """A quiet command records fine while drawing nothing.

        ``asciinema`` writes the cast header the moment it starts, so a
        non-empty cast is the recorder's own handle; pane content is a proxy
        that only appears once the *recorded command* prints something.
        Reproduced against the previous recipe: ``-c 'sleep 45'`` failed
        with "recorder did not come up within 30s" after 30 s, and the
        failure path killed a healthy recording whose cast already held the
        header.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        seg = block[block.index("# 2."):block.index("# 3.")]
        until = re.search(r"^until .*?; do$", seg, re.M | re.S)
        assert until, "cli-recording: no recorder readiness wait"
        assert "recording.cast" in until.group(0), (
            "cli-recording: readiness wait does not use the cast as its handle")
        assert "capture-pane" not in until.group(0), (
            "cli-recording: pane content is not a readiness signal — a quiet "
            "command records with a blank pane")
        assert "has-session" in until.group(0), (
            "cli-recording: a recorder that exits (one-shot command finished, "
            "or asciinema failed) must end the wait")

    def test_cli_stop_bound_is_raisable_for_a_long_command(self):
        """The stop bound is a hang detector, not a limit on the recorded work.

        A one-shot command legitimately runs as long as it runs, so a fixed
        30 s bound kills healthy recordings — reproduced: ``-c 'echo
        started; sleep 45'`` failed with "recorder did not exit within 30s"
        and left a cast holding only its header. The bound stays, as a
        raisable knob with an actionable message.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        assert "stop_timeout=${RECORDER_STOP_TIMEOUT:-" in block, (
            "cli-recording: the stop bound cannot be raised for a long command")
        stop = block[block.index("stop_timeout="):]
        body = stop[:stop.index("\ndone")]
        assert "deadline=$(( $(date +%s) + 10#$stop_timeout ))" in body, (
            "cli-recording: the stop deadline ignores RECORDER_STOP_TIMEOUT "
            "(or reads a leading zero as octal)")
        assert "RECORDER_STOP_TIMEOUT" in body, (
            "cli-recording: the stop failure does not say how to raise the bound")

    def test_cli_scaffold_documents_the_escaped_command_form(self, tmp_path):
        """``<command-to-record>`` needs escaping to survive both quote layers.

        The placeholder sits inside single quotes that are themselves inside
        the outer double-quoted argument, so the ``bash -c "..."`` form from
        the command-form examples cannot be pasted as-is: its first ``"``
        ends the outer string and the shell splits the command into stray
        words (verified live — the recorder exits immediately and the block
        fails with "asciinema wrote no cast"). The recipe therefore has to
        show the escaped form. This test drives the recipe's own documented
        example through the real statement: the ``tmux`` argument is captured
        by a stub, then run the way tmux runs it (``sh -c``) against a stub
        ``asciinema``, so the ``-c`` value has to arrive intact.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        line = next((ln[ln.index("-c 'bash -c \\\""):].strip()
                     for ln in block.splitlines()
                     if "-c 'bash -c \\\"" in ln), None)
        assert line, (
            "cli-recording: the scaffold does not show the escaped "
            "`-c 'bash -c \\\"...\\\"'` form, so the documented way to paste "
            "the `bash -c` command breaks the outer quoting")
        escaped = line[len("-c '"):-1]

        stmt = (_statement(block, "tmux -L scaffold new-session")
                .replace("<capture-dir>", str(tmp_path))
                .replace("<short-name>", "run")
                .replace("<command-to-record>", escaped))
        (tmp_path / "run").mkdir()   # the pane command writes its status here

        _, asci_argv = _drive_recorder_statement(stmt, tmp_path)
        argv = asci_argv.read_text().splitlines()
        assert argv[argv.index("-c") + 1] == 'bash -c "set -x; cmd-one; cmd-two"', (
            "cli-recording: the recorded command does not survive the "
            f"scaffold's quoting (asciinema got {argv!r})")

    def test_cli_single_quoted_command_survives_the_scaffold(self, tmp_path):
        """A `'` in the command needs ``'\\''``, like the `"` layer above.

        The single quotes around ``<command-to-record>`` are ordinary
        characters by the time the pane's shell parses the command, so an
        unescaped ``'`` ends it early — verified live: the natural
        ``-c 'pm pr note add pr-x 'a note''`` leaves asciinema exiting 2
        ("expected one argument") with no cast. Recording a command with a
        quoted argument is routine in QA (notes, paths), so the recipe has to
        document the escape; this drives the documented form through the
        recipe's own statement and asserts asciinema receives the command
        intact.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        assert r"'\''" in block, (
            "cli-recording: the scaffold does not document the `'\\''` "
            "escape, so a command with a quoted argument silently breaks the "
            "pane command")
        (tmp_path / "run").mkdir()
        cmd = r"pm pr note add pr-x '\''a note'\''"
        stmt = (_statement(block, "tmux -L scaffold new-session")
                .replace("<capture-dir>", str(tmp_path))
                .replace("<short-name>", "run")
                .replace("<command-to-record>", cmd))
        _, asci_argv = _drive_recorder_statement(stmt, tmp_path)
        argv = asci_argv.read_text().splitlines()
        assert argv[argv.index("-c") + 1] == "pm pr note add pr-x 'a note'", (
            "cli-recording: a single-quoted argument does not survive the "
            f"scaffold's quoting (asciinema got {argv!r})")

    def test_cli_scaffold_saves_asciinemas_own_stderr(self, tmp_path):
        """asciinema's own error must land on disk, not only in the pane.

        Its startup errors — a broken ``-c`` command, an unwritable cast path
        — go to stderr, and the failure paths tear the pane down (the stop
        step's retryable failures are the exception, and they leave it up
        with a message saying so), so
        without the redirect the worker is told the recording failed and has
        nothing left to read.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        (tmp_path / "run").mkdir()
        stmt = (_statement(block, "tmux -L scaffold new-session")
                .replace("<capture-dir>", str(tmp_path))
                .replace("<short-name>", "run")
                .replace("<command-to-record>", "true"))
        _drive_recorder_statement(
            stmt, tmp_path,
            asci_body='echo "asciinema rec: error: expected one argument" >&2\n'
                      'exit 2\n')
        log = tmp_path / "run" / "recorder-stderr.log"
        assert log.exists(), (
            "cli-recording: asciinema's stderr is not saved, so a failed "
            "recorder leaves no reason on disk")
        assert "expected one argument" in log.read_text(), log.read_text()

    def test_cli_scaffold_writes_the_cast_beside_the_render(self):
        """The scaffold must write the cast where the render step reads it.

        Every other form in the recipe (and the render block) uses
        ``<capture-dir>/<short-name>/recording.cast``.  A scaffold writing
        ``<capture-dir>/recording.cast`` renders nothing — or an older file
        — while looking successful.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        assert "<capture-dir>/<short-name>/recording.cast" in block

    def test_cli_scaffold_checks_asciinemas_own_exit_status(self):
        """A non-empty cast does not prove the recorder finished.

        An asciinema killed mid-recording leaves a cast holding only its
        header, and ``test -s`` passes on it — reproduced live: a 60 s
        one-shot recording whose asciinema was SIGKILLed after 1 s made the
        previous scaffold print success on a 117-byte cast. asciinema's own
        exit status is the handle, so the pane's shell has to record it after
        asciinema returns and step 4 has to fail on a missing or non-zero
        one. The file the pane command writes and the file step 4 reads have
        to be the same one, and it has to be cleared with the stale cast.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        write = re.search(r"^[^#\n]*echo \\\$\? > (\S+)", block, re.M)
        assert write, (
            "cli-recording: the pane command does not record asciinema's "
            "exit status, so a killed recorder passes on its header-only cast")
        status_path = write.group(1).rstrip('"')
        read = re.search(
            r"^status=\$\(cat (\S+) 2>/dev/null\)\n"
            r"\[ -n \"\$status\" \] \|\| \{$", block, re.M)
        assert read, (
            "cli-recording: step 4 does not read the recorder's exit status")
        assert read.group(1) == status_path, (
            "cli-recording: step 4 reads " + read.group(1) + " but the pane "
            "command writes " + status_path)
        assert '[ "$status" = 0 ]' in block, (
            "cli-recording: a non-zero recorder status is not treated as a "
            "failed recording")
        assert "incomplete" in block, (
            "cli-recording: the status failure does not say the cast is "
            "incomplete")
        # The cleanup has to remove the *derived* path, and the assertion has
        # to look at the `rm` statement rather than at everything between it
        # and `new-session`: that range can also hold prose mentioning the
        # status file (it does in the tmux recipe), so a substring search over
        # the range is satisfied by a comment even after the real cleanup has
        # dropped the file — which is how the tmux recipe's clear stayed
        # unguarded while this file was green.
        rm = _statement(block, "rm -f ")
        assert status_path in rm, (
            "cli-recording: the pane command writes " + status_path + " but "
            "the stale cleanup does not remove it, so a recorder torn down "
            "before it finished reads the earlier run's status and passes")

    def test_cli_scaffold_records_the_recorders_exit_status(self, tmp_path):
        """The status echo has to reach the *pane's* shell, and land on disk.

        The pane command is an argument to ``tmux new-session``, which tmux
        runs with ``sh -c``, so the status echo has to survive this shell's
        own double-quote expansion (``\\$?``) and then be expanded by the
        pane's shell. Run the recipe's own statement against a stub tmux and
        then run the captured pane command with a stub ``asciinema`` that
        exits 7: the status file has to hold 7.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        (tmp_path / "run").mkdir()
        stmt = (_statement(block, "tmux -L scaffold new-session")
                .replace("<capture-dir>", str(tmp_path))
                .replace("<short-name>", "run")
                .replace("<command-to-record>", "true"))
        recorder_cmd, _ = _drive_recorder_statement(stmt, tmp_path)
        assert "$?" in recorder_cmd, (
            "cli-recording: the recorder command's `$?` was expanded by this "
            "shell, so the pane would record an earlier command's status "
            f"(got {recorder_cmd!r})")
        assert (tmp_path / "run" / "recorder.status").read_text().strip() == "7", (
            "cli-recording: asciinema's exit status does not reach the file "
            "step 4 reads")

    def test_tmux_scaffold_checks_asciinemas_own_exit_status(self):
        """The tmux completion check must survive a killed recorder too.

        The tmux recipe's witness that the recording finished is the target
        session: a recorder that is gone while the session lives died
        mid-scenario. When the session ended *too*, no witness is left and
        ``test -s`` decides alone — the CLI pane's position exactly — so a
        recorder killed just before (or during) a session teardown would pass
        on its header-only cast. asciinema's own exit status is the handle, so
        the pane's shell records it and step 5 fails on a missing or non-zero
        one. The file the pane command writes and the file step 5 reads have
        to be the same one, and it has to be cleared with the stale cast.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        write = re.search(r"^[^#\n]*echo \\\$\? > (\S+)", block, re.M)
        assert write, (
            "tmux-screen-recording: the pane command does not record "
            "asciinema's exit status, so a recorder killed while the target "
            "session also ended passes on its header-only cast")
        status_path = write.group(1).rstrip('"')
        read = re.search(
            r"^status=\$\(cat (\S+) 2>/dev/null\)\n"
            r"\[ -n \"\$status\" \] \|\| \{$", block, re.M)
        assert read, (
            "tmux-screen-recording: step 5 does not read the recorder's exit "
            "status")
        assert read.group(1) == status_path, (
            "tmux-screen-recording: step 5 reads " + read.group(1) + " but "
            "the pane command writes " + status_path)
        assert '[ "$status" = 0 ]' in block, (
            "tmux-screen-recording: a non-zero recorder status is not treated "
            "as a failed recording")
        assert "incomplete" in block, (
            "tmux-screen-recording: the status failure does not say the cast "
            "is incomplete")
        # Same as the CLI case: the `rm` statement, not everything up to
        # `new-session`. The range here contains step 1's comment
        # "(verified live — rc 0, cast, `recorder.status` 0, transcript, …)",
        # so the substring was satisfied by that comment and the clear itself
        # was unguarded: deleting it left the whole file green (178 passed)
        # and a recorder torn down before it finished passed on the earlier
        # run's status (verified in the harness — mode `detachnostatus` plus a
        # seeded `recorder.status` of 0 exits 0 without the clear).
        rm = _statement(block, "rm -f ")
        assert status_path in rm, (
            "tmux-screen-recording: the pane command writes " + status_path +
            " but the stale cleanup does not remove it, so a recorder torn "
            "down before it finished reads the earlier run's status and "
            "passes")

    def test_tmux_scaffold_records_the_recorders_exit_status(self, tmp_path):
        """The status echo has to reach the *pane's* shell, and land on disk.

        Same two quote layers as the CLI scaffold: the pane command is an
        argument to ``tmux new-session``, which tmux runs with ``sh -c``, so
        the status echo has to survive this shell's own expansion (``\\$?``)
        while ``$TARGET`` is expanded here as intended. Run the recipe's own
        statement against a stub tmux, then run the captured pane command with
        a stub ``asciinema`` that exits 7: the status file has to hold 7.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        cap = tmp_path / "cap"
        cap.mkdir()
        stmt = (_statement(block, "tmux new-session -d -s pm-recorder")
                .replace("<capture-dir>", str(cap)))
        recorder_cmd, _ = _drive_recorder_statement(
            stmt, tmp_path, {"TARGET": "pm-test"})
        assert "$?" in recorder_cmd, (
            "tmux-screen-recording: the recorder command's `$?` was expanded "
            "by this shell, so the pane would record an earlier command's "
            f"status (got {recorder_cmd!r})")
        assert "pm-test" in recorder_cmd, (
            "tmux-screen-recording: $TARGET no longer expands in the pane "
            f"command (got {recorder_cmd!r})")
        assert (cap / "recorder.status").read_text().strip() == "7", (
            "tmux-screen-recording: asciinema's exit status does not reach the "
            "file step 5 reads")

    def test_tmux_scaffold_saves_asciinemas_own_stderr(self, tmp_path):
        """The recorder's own error has to survive the pane it was printed in.

        The attach's errors travel through the pty and stay in the pane and
        the cast, but asciinema's *own* startup errors go to stderr — and the
        failure paths that act on the recorder tear the session down (the
        capture-directory guards refuse before they act on anything). The
        redirect puts them on disk; verified that it does not disturb the
        recording (the attach error is still drawn in the pane and recorded in
        the cast).
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        cap = tmp_path / "cap"
        cap.mkdir()
        stmt = (_statement(block, "tmux new-session -d -s pm-recorder")
                .replace("<capture-dir>", str(cap)))
        _drive_recorder_statement(
            stmt, tmp_path, {"TARGET": "pm-test"},
            asci_body='echo "asciinema rec: error: recording already exists" >&2\n'
                      'exit 2\n')
        log = cap / "recorder-stderr.log"
        assert log.exists(), (
            "tmux-screen-recording: asciinema's stderr is not saved, so a "
            "failed recorder leaves no reason on disk")
        assert "recording already exists" in log.read_text(), log.read_text()


@pytest.mark.parametrize("name", RECIPES)
def test_failed_render_leaves_no_video(name, tmp_path):
    """A failed render must not leave the previous run's mp4 behind.

    ``ffmpeg`` does not touch an existing output when it fails (verified: a
    missing input leaves the old mp4 byte-for-byte), so without clearing the
    outputs first, a render that failed — no ``agg`` installed, an unreadable
    cast — still ends with a ``recording.mp4`` in the capture directory. The
    manifest and the sign-off report then present the *previous* run's video
    as this run's evidence, which is the same class of bug as rendering a
    stale cast. The stale gif matters too: a failed ``agg`` would otherwise
    let ``ffmpeg`` encode an earlier run's gif.
    """
    block = _render_block(name)
    cast_rel = re.search(r"^cast=(\S+)$", block, re.M).group(1)
    block = (block.replace("<capture-dir>", str(tmp_path))
                  .replace("<short-name>", "run"))
    cast = Path(cast_rel.replace("<capture-dir>", str(tmp_path))
                       .replace("<short-name>", "run"))
    cast.parent.mkdir(parents=True, exist_ok=True)
    cast.write_text('{"version": 2}\n')
    mp4 = cast.with_suffix(".mp4")
    mp4.write_bytes(b"previous run's video")
    gif = cast.with_name(cast.name + ".gif")
    gif.write_bytes(b"previous run's gif")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("agg", "ffprobe", "ffmpeg"):
        # The render block checks each tool where it is used: `agg --version`
        # (the renderer guard) and `command -v` for the encoder/prober. The
        # stubs answer those the way the real tools do, so the block reaches
        # the render and fails there.
        body = ("case \"$*\" in *--version*) exit 0 ;; esac\nexit 1\n"
                if tool == "agg" else "exit 1\n")
        _stub_tool(bindir, tool, body)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        f"{name}: a failed render exits 0, so the worker's next step looks "
        "like it has a video")
    assert "render produced no mp4" in r.stderr, (
        f"{name}: a failed render does not say what went wrong")
    assert not mp4.exists(), (
        f"{name}: a failed render left the previous run's recording.mp4 in "
        "place, so the capture looks successful with a stale video")
    assert not gif.exists(), (
        f"{name}: a failed render left the previous run's gif in place")


def _run_render(name, tmp_path, agg_body=None, ffprobe_body=None,
                ffmpeg_body=None, with_cast=True, cast_body=None,
                capture=None, capdir_mode=None, create_capture_dir=True,
                mv_body=None, home=None, direct=False, seed=None):
    """Run a recipe's render block against stubbed ``agg``/``ffprobe``/``ffmpeg``.

    Returns ``(proc, mp4_path, gif_path)``. The stubs are the real stage
    contracts: ``agg`` writes the gif, ``ffprobe`` reports dimensions then the
    codec, ``ffmpeg`` writes the mp4. ``cast_body`` writes the cast's contents
    (``""`` is the 0-byte cast a recording that wrote nothing leaves, which the
    block's ``test -s`` is there for); ``with_cast=False`` leaves no file.
    ``capture`` is the directory substituted for ``<capture-dir>`` (default
    ``tmp_path``). ``capdir_mode`` pre-creates the cast's directory with that
    mode, so a case can model a capture directory that exists and cannot be
    written (the mode is restored before the run returns);
    ``create_capture_dir=False`` leaves the directory absent, so a case can
    model a path that is not there. ``mv_body`` stubs ``mv``, which the render
    uses only to publish the finished mp4, so a case can model a rename that
    fails. ``home`` is the ``HOME`` the block runs with, and the directory a
    ``~/…`` capture path is expanded against for this helper's own file
    operations (the block text keeps the tilde spelling, which the block's
    shell expands).

    ``direct=True`` runs the block's own ``render_cast`` the way the Notes'
    batch loop does — the function is called on its own, so the block's
    top-level pre-render ``rm`` and its ``render_fail`` wrapper never run and
    the function's exit status is the script's. ``seed`` writes extra files
    (name -> bytes) into the cast's directory before the run, for a case that
    needs a previous render's outputs in place.
    """
    capture = tmp_path if capture is None else capture
    block = _render_block(name)
    cast_rel = re.search(r"^cast=(\S+)$", block, re.M).group(1)
    block = (block.replace("<capture-dir>", str(capture))
                  .replace("<short-name>", "run"))
    cast = _expand_tilde(Path(cast_rel.replace("<capture-dir>", str(capture))
                                     .replace("<short-name>", "run")), home)
    if direct:
        # The documented batch entry point: ``render_cast "$c"`` per cast.
        # Drop the block's own pre-render ``rm`` (a batch caller never runs
        # it) and its ``render_fail`` wrapper, and leave the function call as
        # the last command so its status is the script's.
        lines = [ln for ln in block.splitlines()
                 if not ln.startswith('rm -f "${cast%.cast}.mp4"')]
        for i, ln in enumerate(lines):
            if ln.startswith('render_cast "$cast" || render_fail'):
                lines[i] = 'render_cast "$cast"'
                del lines[i + 1]
                break
        else:
            raise AssertionError(f"{name}: no render_cast call found")
        block = "\n".join(lines) + "\n"
    if create_capture_dir:
        cast.parent.mkdir(parents=True, exist_ok=True)
        if with_cast:
            cast.write_text(cast_body if cast_body is not None
                            else '{"version": 2}\n')
        for fname, data in (seed or {}).items():
            (cast.parent / fname).write_bytes(data)
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    _stub_tool(bindir, "agg", agg_body or (
        # The render block's renderer guard runs `agg --version` first, so the
        # stub has to answer it the way a working agg does; only the render
        # call writes the gif.
        'case "$*" in *--version*) exit 0 ;; esac\n'
        'for a in "$@"; do last=$a; done\nprintf gif > "$last"\n'))
    # Model real ffprobe's answers *per query*: the render reads the gif's
    # dimensions, then its packet count and its duration, and the final-frame
    # hold is built from the last two. A stub that answered one value for
    # every query ("h264") is not a shape the tool can produce — the probe
    # check now requires numbers there (a truncated gif gets "N/A"), so the
    # stub answers each query the way the real tool does.
    _stub_tool(bindir, "ffprobe", ffprobe_body or (
        'case "$*" in\n'
        '  *width,height*) echo 640,480 ;;\n'
        '  *nb_read_packets*) echo 6 ;;\n'
        '  *format=duration*) echo 0.60 ;;\n'
        '  *) echo h264 ;;\n'
        'esac\n'))
    _stub_tool(bindir, "ffmpeg", ffmpeg_body or (
        'for a in "$@"; do last=$a; done\nprintf mp4 > "$last"\n'))
    if mv_body is not None:
        _stub_tool(bindir, "mv", mv_body)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    if home is not None:
        env["HOME"] = str(home)
    if capdir_mode is not None:
        cast.parent.chmod(capdir_mode)
    try:
        r = subprocess.run(["bash"], input=block, env=env,
                           capture_output=True, text=True)
    finally:
        if capdir_mode is not None and cast.parent.exists():
            cast.parent.chmod(0o700)
    return r, cast.with_suffix(".mp4"), cast.with_name(cast.name + ".gif")


@pytest.mark.parametrize("name", RECIPES)
@UNWRITABLE_MODES
def test_render_refuses_a_capture_dir_it_cannot_write(name, tmp_path,
                                                      capdir_mode):
    """An unwritable capture directory is not a broken renderer.

    The render block writes the intermediate gif and the mp4 into the
    capture directory, and it was the one block that writes there without the
    writability guard the capture steps carry: with a mode-500 directory
    holding a cast, the `rm` fails silently, `agg` cannot create its gif, and
    the block reports "agg failed on the cast — is 'agg' installed?" — a
    remedy that cannot work, because the renderer is installed and the
    directory is the problem (verified live in this container with agg 1.9.0
    and ffmpeg 4.4.2: rc 1 with that message, and the install block that
    message points at exits 0 without changing anything). The block has to
    name the directory where it fails, before it removes anything.

    The second shape is a directory with the write bit and no *search* bit
    (mode 600): `[ -w ]` answers 0 for it, so the guard's `[ -x ]` half is
    what refuses it — without that half the block runs on and reports "there
    is no cast to render (the recording wrote nothing)" for a cast that is
    right there (verified live).
    """
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        pytest.skip("root bypasses the directory permission bits")
    r, mp4, gif = _run_render(name, tmp_path, capture=tmp_path / "cap",
                              capdir_mode=capdir_mode)

    assert r.returncode != 0, (
        f"{name}: a render into an unwritable capture directory exited 0")
    assert "cannot be written" in r.stderr, r.stderr
    assert "is 'agg' installed" not in r.stderr, (
        f"{name}: an unwritable capture directory is reported as a broken "
        "renderer, so the worker is sent to the agg install block, which "
        "runs and changes nothing: " + r.stderr)
    assert str(mp4.parent) in r.stderr, (
        f"{name}: the refusal does not name the capture directory: "
        + r.stderr)
    assert not mp4.exists() and not gif.exists(), (
        f"{name}: the refused render wrote outputs into a directory it had "
        "just refused")


@pytest.mark.parametrize("name", RECIPES)
def test_render_names_a_missing_capture_dir(name, tmp_path):
    """A path that is not there is not a recording that wrote nothing.

    The block's cast check says "there is no cast to render (the recording
    wrote nothing)" — right for a directory that exists and holds no cast,
    wrong for a capture directory that does not exist at all (a mistyped or
    unsubstituted path), where it sends the worker to re-record into a
    directory nothing created. The web-UI finalize block guards the same
    state with "capture directory … does not exist".
    """
    r, mp4, gif = _run_render(name, tmp_path, capture=tmp_path / "cap",
                              create_capture_dir=False)

    assert r.returncode != 0, (
        f"{name}: a render against a missing capture directory exited 0")
    assert "does not exist" in r.stderr, r.stderr
    assert "the recording wrote nothing" not in r.stderr, (
        f"{name}: a missing capture directory is reported as a recording "
        "that wrote nothing: " + r.stderr)
    assert str(mp4.parent) in r.stderr, (
        f"{name}: the refusal does not name the capture directory: "
        + r.stderr)
    assert not mp4.parent.exists(), (
        f"{name}: the refused render created the capture directory")


@pytest.mark.parametrize("name", RECIPES)
def test_render_refuses_a_relative_capture_dir(name, tmp_path):
    """The render block is pasted on its own, so its path is a handle too.

    Every capture step refuses a relative ``<capture-dir>`` because each paste
    resolves it against its own shell, and the tmux step-0 prose says the rule
    covers "every ``test -s`` below" — but the render block, which is pasted
    after the capture (and on its own, "once the cast exists"), never carried
    the guard. Verified with the recipes' own blocks: with
    ``<capture-dir>=relcap`` pasted from a directory holding a previous run's
    ``relcap[/<short-name>]/recording.cast``, the block exits **0** and
    publishes that stale cast as this run's ``recording.mp4``; pasted from a
    directory where the relative path does not exist, it reports "the
    recording wrote nothing" for a recording that wrote one, one directory
    over. The block has to refuse the path where the capture steps do, before
    it removes or renders anything.
    """
    bash = shutil.which("bash")
    assert bash, "bash is required"
    block = _render_block(name)
    cast_rel = re.search(r"^cast=(\S+)$", block, re.M).group(1)
    block = (block.replace("<capture-dir>", "relcap")
                  .replace("<short-name>", "run"))
    # The stale cast sits where the relative path resolves: against the
    # directory the block is pasted from.
    work = tmp_path / "work"
    work.mkdir()
    cast = Path(cast_rel.replace("<capture-dir>", "relcap")
                       .replace("<short-name>", "run"))
    stale = work / cast
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text('{"version": 2}\n')
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_tool(bindir, "agg", (
        'for a in "$@"; do last=$a; done\nprintf gif > "$last"\n'))
    _stub_tool(bindir, "ffprobe", (
        'case "$*" in\n'
        '  *width,height*) echo 640,480 ;;\n'
        '  *nb_read_packets*) echo 6 ;;\n'
        '  *format=duration*) echo 0.60 ;;\n'
        '  *) echo h264 ;;\n'
        'esac\n'))
    _stub_tool(bindir, "ffmpeg", (
        'for a in "$@"; do last=$a; done\nprintf mp4 > "$last"\n'))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")

    r = subprocess.run([bash], input=block, env=env, cwd=str(work),
                       capture_output=True, text=True, timeout=60)

    assert r.returncode != 0, (
        f"{name}: the render block accepted a relative capture directory and "
        "rendered whatever cast was in the pasting shell's directory")
    assert "must be an absolute path" in r.stderr, (
        f"{name}: the relative capture directory is not named: " + r.stderr)
    assert not stale.with_suffix(".mp4").exists(), (
        f"{name}: the refused render published the stale cast's video")
    assert not stale.with_name(stale.name + ".gif").exists(), (
        f"{name}: the refused render ran the renderer")


@pytest.mark.parametrize("name", RECIPES)
def test_render_accepts_a_tilde_capture_dir(name, tmp_path):
    """The render block's guard accepts the documented ``~/`` spelling.

    The block is pasted on its own and carries its own absolute-path guard,
    whose message says "absolute path (or start with ~/)". Only the refusal
    half had a case: narrowing this guard's pattern to ``/*`` left the whole
    file green (262 passed) and the block then refused a documented-valid
    path. ``cast=~/…`` expands the tilde in the block's own assignment, so
    the render writes under ``$HOME``.
    """
    home = tmp_path / "home"
    home.mkdir()
    r, mp4, gif = _run_render(name, tmp_path, capture=Path("~/cap"), home=home)

    assert r.returncode == 0, r.stderr
    assert "must be an absolute path" not in r.stderr, (
        f"{name}: a ~/ capture dir was refused: " + r.stderr)
    assert mp4.read_bytes() == b"mp4", (
        f"{name}: the render did not publish its mp4 under $HOME")
    assert str(mp4).startswith(str(home)), (
        f"{name}: the render wrote outside the directory ~/ names: "
        + str(mp4))


@pytest.mark.parametrize("name", RECIPES)
def test_failed_encode_does_not_leave_a_partial_mp4(name, tmp_path):
    """`test -s` on the mp4 is not proof the encode finished.

    Verified live with the recipe's own render block and real `ffmpeg`: a
    SIGKILLed encode leaves a **267,945-byte** mp4 (a SIGTERM one leaves
    119,704 bytes), so a render whose encoder failed exits 0 with a broken
    mp4 that the manifest and the report present as this run's recording —
    the same header-only-cast bug as the recorder step, one artifact over.
    The encoder's own exit status is the handle, and its partial output goes.
    ``render_cast`` writes that output to ``recording.mp4.partial.mp4``, so
    the file this case has to see removed is the *partial* — the render's
    failure path (``render_fail``) is the only thing that removes it, and
    without that removal the interrupted video stays in the capture
    directory beside no mp4 at all.
    """
    r, mp4, gif = _run_render(name, tmp_path, ffmpeg_body=(
        'for a in "$@"; do last=$a; done\nprintf partial > "$last"\nexit 1\n'))
    partial = Path(str(mp4) + ".partial.mp4")

    assert r.returncode != 0, (
        f"{name}: an encoder that failed on a partial mp4 was reported as a "
        "successful render")
    assert "render produced no mp4" in r.stderr, r.stderr
    assert "ffmpeg failed" in r.stderr, (
        f"{name}: the failure does not name the stage that broke: " + r.stderr)
    assert not mp4.exists(), (
        f"{name}: a failed encode left its partial mp4 as this run's video")
    assert not partial.exists(), (
        f"{name}: a failed encode left {partial.name} behind, so an "
        "interrupted render's video survives as this run's evidence")
    assert not gif.exists()


@pytest.mark.parametrize("name", RECIPES)
def test_render_succeeds_with_a_playable_mp4(name, tmp_path):
    """The new checks must not reject a healthy render."""
    r, mp4, gif = _run_render(name, tmp_path)

    assert r.returncode == 0, r.stderr
    assert mp4.read_bytes() == b"mp4"
    assert not gif.exists(), "the intermediate gif is left behind"


@pytest.mark.parametrize("name", RECIPES)
def test_render_publishes_through_a_partial_name(name, tmp_path):
    """A render is published by a rename, not by encoding to the final name.

    ``render_cast`` writes ``recording.mp4.partial.mp4`` and renames it to
    ``recording.mp4`` only after a successful encode, so a render stopped on
    purpose or killed before that rename cannot leave a partial video under
    the name the manifest presents (that is the guarantee the step-0 cleanup
    and ``render_fail``'s partial removal exist for). Nothing pinned it: the
    failed-encode case is cleaned up by ``render_fail`` either way, so
    encoding straight to ``recording.mp4`` left the whole file green while
    an interrupted render would publish its partial.
    """
    out = tmp_path / "ffmpeg-output"
    r, mp4, gif = _run_render(name, tmp_path, ffmpeg_body=(
        'for a in "$@"; do last=$a; done\n'
        f'printf "%s" "$last" > "{out}"\n'
        'printf mp4 > "$last"\n'))
    partial = Path(str(mp4) + ".partial.mp4")

    assert r.returncode == 0, r.stderr
    assert out.read_text() == str(partial), (
        f"{name}: the encoder wrote to {out.read_text()}, not to the partial "
        "name, so an interrupted render publishes a partial video under the "
        "name the manifest presents")
    assert mp4.read_bytes() == b"mp4"
    assert not partial.exists(), (
        f"{name}: a successful render left its partial beside the published "
        "mp4")


def _run_render_without(name, tmp_path, missing="ffmpeg"):
    """Run a recipe's render block on a PATH that holds no ``missing`` tool.

    A host may well have a real ``ffmpeg``/``ffprobe``/``agg`` on ``PATH``, so
    the bindir carries the block's other tools (a stubbed ``agg`` that answers
    the renderer guard, and the tool that is present, symlinked coreutils) and
    nothing else — the missing one has to be genuinely absent (``missing`` is
    ``ffmpeg``, ``ffprobe`` or ``agg``). The capture directory is seeded with
    a *previous* run's ``recording.mp4``, ``recording.cast.gif`` and
    interrupted ``recording.mp4.partial.mp4``, because a stop at any of the
    three tool guards is a render failure that does not go through
    ``render_fail``: only the block's own pre-render ``rm`` keeps that path
    from leaving the earlier run's video behind (verified live: with the
    ``rm`` removed the block exits 1 with the same message and all three
    files survive).
    """
    bash = shutil.which("bash")
    block = _render_block(name)
    cast_rel = re.search(r"^cast=(\S+)$", block, re.M).group(1)
    block = (block.replace("<capture-dir>", str(tmp_path))
                  .replace("<short-name>", "run"))
    cast = Path(cast_rel.replace("<capture-dir>", str(tmp_path))
                       .replace("<short-name>", "run"))
    cast.parent.mkdir(parents=True, exist_ok=True)
    cast.write_text('{"version": 2}\n')
    cast.with_suffix(".mp4").write_bytes(b"previous run's video")
    cast.with_name(cast.name + ".gif").write_bytes(b"previous run's gif")
    # The interrupted render's partial is the third output the pre-render `rm`
    # owns (see the docstring): a render killed before the rename leaves it.
    cast.with_suffix(".mp4.partial.mp4").write_bytes(b"previous partial")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_tool(bindir, "agg", (
        # The render block's renderer guard runs `agg --version` first.
        'case "$*" in *--version*) exit 0 ;; esac\n'
        'for a in "$@"; do last=$a; done\nprintf gif > "$last"\n'))
    if missing == "agg":
        (bindir / "agg").unlink()
    if missing != "ffprobe":
        _stub_tool(bindir, "ffprobe", (
            'case "$*" in *width,height*) echo 640,480 ;;\n'
            '  *nb_read_packets*) echo 6 ;;\n'
            '  *format=duration*) echo 0.60 ;;\n'
            '  *) echo h264 ;;\n'
            'esac\n'))
    if missing != "ffmpeg":
        _stub_tool(bindir, "ffmpeg", (
            'for a in "$@"; do last=$a; done\nprintf mp4 > "$last"\n'))
    for tool in ("rm", "cat", "sh", "date", "uname", "mkdir", "chmod"):
        for d in ("/bin", "/usr/bin"):
            if (Path(d) / tool).exists():
                os.symlink(str(Path(d) / tool), bindir / tool)
                break
    env = dict(os.environ, PATH=str(bindir))
    r = subprocess.run([bash], input=block, env=env,
                       capture_output=True, text=True)
    return r, cast.with_suffix(".mp4"), cast.with_name(cast.name + ".gif")


@pytest.mark.parametrize("name", RECIPES)
def test_render_names_a_missing_encoder(name, tmp_path):
    """A missing ``ffmpeg`` is not a bad gif, and it still leaves no video.

    The block checks the encoder's exit status (R12), so a host without
    ``ffmpeg`` reaches the shell's "ffmpeg: command not found" (status 127)
    and the block reports "ffmpeg failed on the gif" — sending the worker to
    inspect the cast and ``agg`` for a tool that is not installed. Verified
    against the pre-fix blocks: rc 1 with that message and no ``ffmpeg``
    anywhere on PATH. This is the misdiagnosis the web-UI finalize step got
    the same guard for (R22), in the recipes where a missing renderer is most
    likely (the QA image used on 2026-10-27 had no ``agg`` either).

    This stop is also the one render failure that does not go through
    ``render_fail`` (it exits before ``agg`` runs), so the block's own
    pre-render ``rm`` is the only thing that removes a *previous* run's
    ``recording.mp4``, gif and interrupted partial here: without it the block
    exits 1 with the same message and leaves all three in the capture
    directory, where the manifest and the report present them as this run's
    evidence (verified live). The seeded files below are what pins that
    ordering.
    """
    r, mp4, gif = _run_render_without(name, tmp_path, missing="ffmpeg")
    partial = Path(str(mp4) + ".partial.mp4")

    assert r.returncode != 0, r.stderr
    assert "ffmpeg is not installed" in r.stderr, (
        f"{name}: a missing encoder is not named: " + r.stderr)
    assert "ffmpeg failed on the gif" not in r.stderr, (
        f"{name}: a missing encoder is still reported as a bad gif: "
        + r.stderr)
    assert not gif.exists(), (
        f"{name}: the render left a gif behind — either it ran agg before "
        "noticing the encoder was missing, or it kept the previous run's gif")
    assert not mp4.exists(), (
        f"{name}: a render that could not run left the previous run's "
        "recording.mp4 behind, so the capture looks successful with a stale "
        "video")
    assert not partial.exists(), (
        f"{name}: a render that could not run left an interrupted render's "
        f"{partial.name} behind, so the capture looks like a render in "
        "progress")


@pytest.mark.parametrize("name", RECIPES)
def test_render_names_a_missing_prober(name, tmp_path):
    """A missing ``ffprobe`` is not an unreadable gif.

    The block guards the encoder because a missing tool otherwise reads as a
    bad *input*, and ``ffprobe`` is used even earlier: it measures the gif's
    dimensions and builds the final-frame hold from its packet count and
    duration. Without a guard, a host with ``ffmpeg`` but no ``ffprobe``
    answers "ffprobe: command not found" three times and then reports
    "cannot probe the gif <path>" — the gif blamed for a tool that is not
    installed, the same misdiagnosis the encoder guard exists to prevent, one
    tool over (verified against the pre-fix blocks: rc 1 with that message
    and no ``ffprobe`` anywhere on ``PATH``). ``ffprobe`` ships with ffmpeg in
    the usual packages, but a hand-built or trimmed encoder need not include
    it, and the block has to say which of the two is missing.

    Like the missing-encoder stop, this one runs after the pre-render ``rm``
    and before ``agg``: the seeded previous run's mp4, gif and partial must be
    gone, not left for the manifest to present as this run's evidence.
    """
    r, mp4, gif = _run_render_without(name, tmp_path, missing="ffprobe")
    partial = Path(str(mp4) + ".partial.mp4")

    assert r.returncode != 0, r.stderr
    assert "ffprobe is not installed" in r.stderr, (
        f"{name}: a missing prober is not named: " + r.stderr)
    assert "cannot probe the gif" not in r.stderr, (
        f"{name}: a missing prober is still reported as an unreadable gif: "
        + r.stderr)
    assert "ffprobe: command not found" not in r.stderr, (
        f"{name}: the block ran ffprobe before noticing it was missing, so "
        "the worker sees the shell's error instead of the recipe's: "
        + r.stderr)
    assert not gif.exists(), (
        f"{name}: the render ran agg although the prober was missing")
    assert not mp4.exists(), (
        f"{name}: a render that could not run left the previous run's "
        "recording.mp4 behind, so the capture looks successful with a stale "
        "video")
    assert not partial.exists(), (
        f"{name}: a render that could not run left an interrupted render's "
        f"{partial.name} behind, so the capture looks like a render in "
        "progress")


@pytest.mark.parametrize("name", RECIPES)
def test_render_names_a_missing_renderer(name, tmp_path):
    """A missing ``agg`` is not a cast agg could not read.

    The block checked the encoder and the prober but never the renderer: a
    host with no ``agg`` reached ``render_cast``, the shell answered "agg:
    command not found", and the block reported "agg failed on the cast — is
    'agg' installed?" — the right question, but asked *after* the pre-render
    ``rm`` and with no check to back it. The install block is a separate
    paste, so the render block is the last place the absence can be named
    where it happens (verified with the recipes' own blocks and no ``agg`` on
    ``PATH``: the pre-fix block exits 1 with the cast question).
    """
    r, mp4, gif = _run_render_without(name, tmp_path, missing="agg")
    partial = Path(str(mp4) + ".partial.mp4")

    assert r.returncode != 0, r.stderr
    assert "agg is not installed" in r.stderr, (
        f"{name}: a missing renderer is not named: " + r.stderr)
    assert "is 'agg' installed" not in r.stderr, (
        f"{name}: a missing renderer is reported as a cast agg could not "
        "read: " + r.stderr)
    assert not mp4.exists(), (
        f"{name}: a render that could not run left the previous run's "
        "recording.mp4 behind, so the capture looks successful with a stale "
        "video")
    assert not gif.exists(), (
        f"{name}: the render left the previous run's gif behind")
    assert not partial.exists(), (
        f"{name}: a render that could not run left an interrupted render's "
        f"{partial.name} behind")


@pytest.mark.parametrize("name", RECIPES)
def test_render_names_a_renderer_that_does_not_run(name, tmp_path):
    """A truncated ``agg`` resolves, so the render must check that it runs.

    ``command -v agg`` answers a truncated or wrong-architecture binary, so
    a resolvability guard would pass and the invocation would fail to
    execute — reported by the block as a cast agg could not read. The
    install block's own handle is ``agg --version`` (a working agg answers 0,
    a broken one fails to execute), and the render block has to ask the same
    question before it renders: this case seeds an ``agg`` that exits 1 for
    every call, the shape a truncated binary has (verified with the
    recipes' own blocks: the pre-fix block reported the cast question).
    """
    r, mp4, gif = _run_render(name, tmp_path, agg_body="exit 1\n")
    partial = Path(str(mp4) + ".partial.mp4")

    assert r.returncode != 0, r.stderr
    assert "the agg on PATH" in r.stderr and "does not run" in r.stderr, (
        f"{name}: a renderer that resolves and cannot execute is not named: "
        + r.stderr)
    assert "is 'agg' installed" not in r.stderr, (
        f"{name}: a renderer that cannot execute is reported as a cast it "
        "could not read: " + r.stderr)
    assert not mp4.exists() and not gif.exists() and not partial.exists(), (
        f"{name}: a renderer that cannot run left an output behind")


@pytest.mark.parametrize("name", RECIPES)
def test_render_names_a_cast_the_renderer_cannot_read(name, tmp_path):
    """A renderer that runs and fails names the cast, not the installation.

    With ``agg`` installed and running (the guard passes), a render failure
    is the input's: a cast agg cannot parse, a full disk. The block's old
    message asked "is 'agg' installed?", whose remedy is the install block —
    which does nothing for a renderer that works, so the worker re-runs the
    install, then the render, and sees the same question: a remedy that
    cannot work, in a loop (verified in this container with agg 1.9.0 and a
    non-asciicast cast: the install block exits 0 without touching anything
    and the second render repeats the message).
    """
    r, mp4, gif = _run_render(name, tmp_path, agg_body=(
        'case "$*" in *--version*) exit 0 ;; esac\nexit 1\n'))
    cast = mp4.with_suffix(".cast")
    partial = Path(str(mp4) + ".partial.mp4")

    assert r.returncode != 0, r.stderr
    assert "agg failed on the cast" in r.stderr, r.stderr
    assert str(cast) in r.stderr, (
        f"{name}: the failure does not name the cast agg could not read: "
        + r.stderr)
    assert "is 'agg' installed" not in r.stderr, (
        f"{name}: a renderer that runs is still reported as an installation "
        "question, whose remedy exits 0 for a working renderer: " + r.stderr)
    assert "render produced no mp4" in r.stderr, (
        f"{name}: the render failure does not end in the block's own "
        "sentence: " + r.stderr)
    assert not mp4.exists() and not gif.exists() and not partial.exists(), (
        f"{name}: a failed render left an output behind")


@pytest.mark.parametrize("name", RECIPES)
@pytest.mark.parametrize("agg_shape", ["absent", "empty"],
                         ids=["no-file", "0-byte-file"])
def test_render_names_a_renderer_that_writes_no_gif(name, tmp_path, agg_shape):
    """A gif that was never written is not an ffmpeg failure.

    ``agg``'s own exit status is the handle for a render that failed, but a
    renderer can also report success and write nothing — the shape the final
    ``test -s`` on the mp4 guards for the encoder. The gif is the *next*
    stage's input, so without its own check that case surfaces as "ffmpeg
    failed on the gif" and sends the worker to the encoder for a renderer
    that wrote nothing (verified with the recipes' own blocks and a stub
    ``agg`` that exits 0 without writing: both printed exactly that). The
    same misdiagnosis as reporting a missing cast as an ``agg`` problem, and
    as the web-UI finalize step's missing webm (R19), one stage over.

    Both shapes of "wrote nothing" are exercised, because they are different
    code paths for the check: no file at all, and the **0-byte** gif the
    block's own comment names ("or a 0-byte gif"). Only the first was
    modelled, so weakening the check from ``-s`` to ``-e`` left the whole
    file green — and a 0-byte gif then reached real ffmpeg, which answers
    "Invalid data found when processing input" and the run reports "ffmpeg
    failed on the gif" (verified with the recipes' own blocks and real
    ffmpeg 4.4.2: the empty-file case is exactly the misdiagnosis the check
    exists to prevent).
    """
    # Model ffmpeg's real contract: it fails on a missing input *and* on an
    # empty one. The default stub writes its output unconditionally, which
    # would hide the misdiagnosis behind a successful-looking encode.
    ffmpeg_body = (
        'in=; out=\n'
        'while [ $# -gt 0 ]; do\n'
        '  case "$1" in -i) in=$2; shift 2 ;; *) out=$1; shift ;; esac\n'
        'done\n'
        '[ -f "$in" ] || { echo "ffmpeg: $in: No such file or directory" >&2; '
        'exit 1; }\n'
        '[ -s "$in" ] || { echo "ffmpeg: $in: Invalid data found when '
        'processing input" >&2; exit 1; }\n'
        'printf mp4 > "$out"\n')
    agg_body = ("exit 0\n" if agg_shape == "absent" else
                # Answer the renderer guard's `--version` first, as a real
                # agg does; the render call is what writes the empty gif.
                'case "$*" in *--version*) exit 0 ;; esac\n'
                'for a in "$@"; do last=$a; done\n: > "$last"\nexit 0\n')
    r, mp4, gif = _run_render(name, tmp_path, agg_body=agg_body,
                              ffmpeg_body=ffmpeg_body)

    assert r.returncode != 0, (
        f"{name}: a render whose renderer wrote no gif was reported as a "
        "successful render")
    assert "render produced no mp4" in r.stderr, r.stderr
    assert "agg wrote no gif" in r.stderr, (
        f"{name}: the failure does not name the renderer that wrote nothing: "
        + r.stderr)
    assert "ffmpeg failed" not in r.stderr, (
        f"{name}: a gif that was never written is reported as an ffmpeg "
        "failure: " + r.stderr)
    assert not mp4.exists()
    assert not gif.exists()


@pytest.mark.parametrize("name", RECIPES)
@pytest.mark.parametrize("probe_shape", ["no-answer", "not-a-number"])
def test_render_names_a_gif_it_cannot_probe(name, tmp_path, probe_shape):
    """A gif the block cannot read is not an encoder failure.

    ``render_cast`` reads the gif's frame count and duration to build the
    final-frame hold. An unreadable gif (agg wrote it, ffprobe cannot parse
    it) leaves both empty, the filter expression becomes malformed, and
    ffmpeg rejects it — so the run reports "ffmpeg failed on the gif" and
    sends the worker to the encoder for an input nothing can read. The probe
    check names the file where it fails, and no case exercised it (the
    ``ffprobe`` stub answers every query).

    A non-empty answer is not a value, and that was the other half: real
    ffprobe *opens* a truncated gif and answers **"N/A"** — with status 0 —
    for the packet count and the duration (verified in this container with
    ffprobe 4.4.2 and a 200-byte prefix of a valid gif: both printed "N/A",
    rc 0, while the dimensions still came from the intact header). The
    check's original `[ -n "$n" ] && [ -n "$dur" ]` passed that through, the
    setpts expression became `if(eq(N\\,N/A)\\,N/A/TB\\,PTS)`, and the block
    printed "ffmpeg failed on the gif" — the exact misdiagnosis it exists to
    prevent. The default ffmpeg stub accepts any filter, so the pre-fix block
    even exited **0** on that gif; with real ffmpeg it failed while parsing
    the expression, not on the input.
    """
    if probe_shape == "no-answer":
        ffprobe_body = "exit 0\n"
    else:
        # What real ffprobe answers for a gif it can open but not read.
        ffprobe_body = (
            'case "$*" in\n'
            '  *width,height*) echo 640,480 ;;\n'
            '  *) echo N/A ;;\n'
            'esac\n')
    r, mp4, gif = _run_render(name, tmp_path, ffprobe_body=ffprobe_body)

    assert r.returncode != 0, (
        f"{name}: a render whose gif could not be probed was reported as a "
        "successful render")
    assert "cannot probe the gif" in r.stderr, (
        f"{name}: the failure does not name the gif that could not be read: "
        + r.stderr)
    assert "ffmpeg failed on the gif" not in r.stderr, (
        f"{name}: a gif nothing could probe is reported as an encoder "
        "failure: " + r.stderr)
    assert not mp4.exists()
    assert not gif.exists()


@pytest.mark.parametrize("name", RECIPES)
def test_render_names_a_publish_that_failed(name, tmp_path):
    """A rename that fails is not an encoder that wrote nothing.

    The encode succeeds and the mp4 is written to its partial name; publishing
    it is the rename. If that rename fails (the directory went read-only, the
    disk filled), the render must say so — the block's final ``test -s`` on
    the mp4 would otherwise report "ffmpeg wrote no mp4" for an encode that
    ran and wrote a complete video, sending the worker back to the encoder.
    No case exercised the rename's own failure path.
    """
    r, mp4, gif = _run_render(name, tmp_path, mv_body="exit 1\n")

    assert r.returncode != 0, (
        f"{name}: a render whose publish failed was reported as a successful "
        "render")
    assert "could not publish" in r.stderr, (
        f"{name}: the failure does not name the step that broke: " + r.stderr)
    assert "ffmpeg wrote no mp4" not in r.stderr, (
        f"{name}: a failed rename is reported as an encoder that wrote "
        "nothing: " + r.stderr)
    assert not mp4.exists()
    assert not gif.exists()
    assert not Path(str(mp4) + ".partial.mp4").exists()


@pytest.mark.parametrize("name", RECIPES)
@pytest.mark.parametrize("cast_shape", ["absent", "empty"],
                         ids=["no-file", "0-byte-file"])
def test_render_says_when_there_is_no_cast(name, tmp_path, cast_shape):
    """A missing cast is not an `agg` problem, and must not send the worker there.

    The CLI recipe documents a `tee transcript.log` fallback for a host with
    no asciinema, and that fallback writes no cast at all. The render step
    used to fail with "check 'agg' is installed and the cast is readable" for
    every failure, so a worker on that path went and installed a renderer it
    already had. The message has to name the actual state.

    The check is ``test -s``, and its message says "the recording wrote
    nothing" — so the 0-byte cast is one of the states it is for, and only the
    absent file was modelled. Weakened to ``-e`` the file stayed green, and
    the empty cast reached real ``agg`` 1.9.0, which answers "Error: empty
    file" and the run reports "agg failed on the cast — is 'agg' installed?"
    (verified with the recipes' own blocks) — the same misdiagnosis for a
    recording that wrote nothing.
    """
    r, mp4, gif = _run_render(
        name, tmp_path,
        with_cast=cast_shape != "absent",
        cast_body="" if cast_shape == "empty" else None)

    assert r.returncode != 0, f"{name}: a render with no cast succeeded"
    assert "there is no cast to render" in r.stderr, r.stderr
    assert "is 'agg' installed" not in r.stderr, (
        f"{name}: the no-cast failure sends the worker to install a renderer")
    assert not mp4.exists()
    assert not gif.exists()


@pytest.mark.parametrize("name", RECIPES)
def test_render_names_an_encoder_that_writes_no_mp4(name, tmp_path):
    """A renderer that reports success and writes nothing is a failure.

    The block checks ``agg``'s and ``ffmpeg``'s exit statuses, and the mp4
    last: the status proves the encode ran, and ``test -s`` catches an encoder
    that exits 0 and writes nothing. That final check had no case at all for
    either recording recipe (deleting it left the whole file green), and the
    false success it guards is real: with the recipe's own block, a stub
    ``ffmpeg`` that exits 0 after creating its output leaves a **0-byte**
    ``recording.mp4`` and the block exits **0** — an empty video the manifest
    and the report present as this run's recording. The web-UI finalize step
    has the same check and its own case
    (``test_web_ui_transcode_that_writes_nothing_leaves_no_mp4``); this is the
    recording recipes' counterpart.

    There are *two* ``test -s`` checks with that message — ``render_cast``'s
    own ``[ -s "$part" ]`` (before the partial is renamed, so an empty video
    is never published even for a moment) and the block's backstop on the
    published mp4. Either alone makes this case pass, so neither is pinned by
    its assertions: deleting the inner one leaves the file green because the
    backstop catches the empty video, and deleting the backstop leaves it
    green because the inner check catches it (verified: both mutations gave
    266 passed). The ``mv`` stub below logs its invocation, which tells the
    two apart — the empty output must never reach the publish at all. The
    backstop has its own case,
    ``test_render_names_a_publish_that_left_no_mp4``.
    """
    mv_log = tmp_path / "mv-invoked"
    r, mp4, gif = _run_render(name, tmp_path, ffmpeg_body=(
        'for a in "$@"; do last=$a; done\n: > "$last"\nexit 0\n'),
        mv_body=f'printf called > "{mv_log}"\nexit 0\n')

    assert r.returncode != 0, (
        f"{name}: a render whose encoder wrote no mp4 was reported as a "
        "successful render")
    assert "render produced no mp4" in r.stderr, r.stderr
    assert "ffmpeg wrote no mp4" in r.stderr, (
        f"{name}: the failure does not name the stage that wrote nothing: "
        + r.stderr)
    assert not mp4.exists(), (
        f"{name}: the empty mp4 is left behind for the manifest to present as "
        "this run's video")
    assert not gif.exists()
    assert not mv_log.exists(), (
        f"{name}: the encoder's empty output was renamed onto the published "
        "name, so a render stopped between the rename and the block's final "
        "check leaves an empty recording.mp4 the manifest presents as this "
        "run's video")


@pytest.mark.parametrize("name", RECIPES)
def test_render_names_a_publish_that_left_no_mp4(name, tmp_path):
    """A rename that reports success but publishes nothing is a failure.

    ``render_cast`` returns 0 once its ``mv`` succeeds, so the block's own
    ``test -s`` on the published mp4 is the only thing between that return
    and "this render succeeded": the file can be gone again by the time the
    block looks (a concurrent cleanup, a tmp cleaner, a rename that crossed a
    filesystem boundary and left nothing behind). Without that backstop the
    block exits 0 with no video at all — a completed-looking render of
    nothing.

    No case pinned it: the encoder-writes-nothing case above is caught by
    ``render_cast``'s own ``[ -s "$part" ]`` first, and deleting the backstop
    left the whole file green (verified: 266 passed for both recipes). The
    ``mv`` stub below reports success without moving anything — the effect
    the backstop exists for — and leaves the partial in place, so the
    assertion that it is gone is ``render_fail``'s removal.
    """
    r, mp4, gif = _run_render(name, tmp_path, mv_body='exit 0\n')
    partial = Path(str(mp4) + ".partial.mp4")

    assert r.returncode != 0, (
        f"{name}: a publish that left no mp4 was reported as a successful "
        "render")
    assert "render produced no mp4" in r.stderr, r.stderr
    assert "ffmpeg wrote no mp4" in r.stderr, (
        f"{name}: the failure does not name the missing published video: "
        + r.stderr)
    assert not mp4.exists(), (
        f"{name}: the failed publish left recording.mp4 for the manifest to "
        "present as this run's video")
    assert not partial.exists(), (
        f"{name}: the failed publish left the partial behind, so a later "
        "attempt resumes into it")
    assert not gif.exists()


@pytest.mark.parametrize("name", RECIPES)
def test_render_cast_alone_does_not_publish_a_stale_partial(name, tmp_path):
    """The batch entry point carries its own cleanup, and it had no case.

    The Notes document calling ``render_cast`` directly in a loop (``mapfile
    -t casts < <(find ...); for c in "${casts[@]}"; do render_cast "$c";
    done``), and in that form the block's top-level pre-render ``rm`` never
    runs: the function's own ``rm -f "$gif" "$part"`` is the only thing that
    clears a previous render's intermediate. A render killed while ``ffmpeg``
    ran reaches no cleanup, so its ``recording.mp4.partial.mp4`` survives; a
    later call for that cast then finds it, and if the encoder reports
    success and writes nothing — the state ``[ -s "$part" ]`` exists for —
    the stale partial satisfies the check and is renamed onto
    ``recording.mp4``. Verified in this container with the recipe's own
    function: the batch call exits **0** and publishes the previous render's
    bytes as this run's video when the pre-rm is dropped, and exits 1 with
    "ffmpeg wrote no mp4" and publishes nothing with it in place.

    Every other case runs the whole block, whose own ``rm`` masks this one, so
    deleting the function's ``rm`` left the file green (300 passed).
    """
    r, mp4, _gif = _run_render(
        name, tmp_path, direct=True,
        seed={"recording.cast.gif": b"a previous render's gif",
              "recording.mp4.partial.mp4":
                  b"a previous render's partial video"},
        ffmpeg_body='exit 0\n')      # reports success, writes nothing

    assert r.returncode != 0, (
        f"{name}: a batch render with a previous render's partial in place "
        "and an encoder that wrote nothing was reported as a successful "
        "render")
    assert "ffmpeg wrote no mp4" in r.stderr, r.stderr
    assert not mp4.exists(), (
        f"{name}: the previous render's partial was published as this run's "
        "video")


@pytest.mark.parametrize("name", RECIPES)
def test_render_documents_how_to_get_the_renderer(name):
    """The render step fails without `agg`, so the recipe has to say how to get it.

    `agg` may be missing (the image used for QA on 2026-10-27 did not have it,
    although the bundled Dockerfile now installs it), and the render block
    exits 1 rather than leave a missing or stale video. Without the install
    line the failure message ("check 'agg' is installed") sends the worker
    nowhere: the recipe never names a prerequisite, so the only remaining
    moves are to substitute a different renderer or to report the capture as
    impossible. The release-binary URL is the one verified against agg 1.9.0.
    """
    text = _recipe_text(name)
    section = text.split("## Render to video", 1)[1]
    install = section.find("agg-$(uname -m)-unknown-linux-gnu")
    assert install != -1, (
        f"{name}: the render section never says how to install 'agg', so a "
        "worker whose image lacks it has no remedy for the render failure")
    assert 'chmod 755 "$agg_tmp"' in section, (
        f"{name}: the downloaded agg binary is never made executable")
    assert install < section.index("agg --idle-time-limit"), (
        f"{name}: the agg install line comes after the render block")
    assert re.search(r"^\s*curl -fsSL", section, re.M), (
        f"{name}: the agg prerequisite is not a runnable install command")
    # The guard has to be in the runnable block, not only in the prose above
    # it: a worker pastes the block, so a prose-only rule is what made the
    # block replace a working `agg` (R16).
    install_block = _install_block(name)
    assert "agg --version" in install_block, (
        f"{name}: the install block is not guarded on a check that the agg on "
        "PATH runs, so a truncated agg (the shape an interrupted download "
        "leaves) resolves, the block does nothing, and the render's "
        "\"is 'agg' installed?\" remedy is inert")
    assert (install_block.index("agg --version")
            < install_block.index("curl -fsSL")), (
        f"{name}: the agg install guard comes after the download")


@pytest.mark.parametrize("name", RECIPES)
def test_render_keeps_the_vfr_and_nostdin_encode(name):
    """The encode's load-bearing options are part of the shipped block.

    The render notes tell a worker to keep these, and dropping any of them is
    silent: ``-nostdin`` keeps a batch loop's file names out of ffmpeg's
    interactive stdin (QA S46 lost characters of the next path to it), and
    ``-vsync vfr`` with the centisecond timebase keeps the GIF's frame delays
    as durations instead of padding them out to a constant rate (a sparse TUI
    cast took more than 10 minutes at ~900% CPU that way, against about 2
    minutes). No case pinned them, so a block that lost them stayed green.
    """
    block = _render_block(name)
    for option in ("-nostdin", "-vsync vfr", "-enc_time_base 1/100",
                   "-video_track_timescale 100"):
        assert option in block, (
            f"{name}: the render block no longer carries `{option}`, which "
            "the render notes tell a worker to keep")


@pytest.mark.parametrize("name", RECIPES)
def test_render_holds_the_final_frame_at_the_gifs_duration(name, tmp_path):
    """The last screen is held for its GIF delay, not dropped at its start.

    ``render_cast`` clones the final GIF frame (``tpad=stop=1:stop_mode=clone``)
    and places the clone at the GIF's own duration (the ``setpts`` expression
    built from the probed packet count and duration). Without it a VFR encode
    ends when the last frame *starts*, so the final screen — usually the state
    the scenario exists to show — is not in the video, and the recipe's own
    "Check the render" note (the mp4 runs the GIF's duration plus one frame
    tick; its frame count is the GIF's plus one) no longer describes the
    output a worker is told to verify. Deleting the whole expression left the
    file green (248 passed), so no case pinned it.
    """
    args_file = tmp_path / "ffmpeg-args"
    r, mp4, gif = _run_render(name, tmp_path, ffmpeg_body=(
        f'printf "%s\\n" "$@" > "{args_file}"\n'
        'for a in "$@"; do last=$a; done\nprintf mp4 > "$last"\n'))

    assert r.returncode == 0, r.stderr
    argv = args_file.read_text().splitlines()
    vf = argv[argv.index("-vf") + 1]
    assert "tpad=stop=1:stop_mode=clone" in vf, (
        f"{name}: the encode does not clone the final frame, so a VFR render "
        f"ends when the last frame starts and the final screen is missing "
        f"from the video: {vf}")
    assert "setpts=" in vf and "eq(N\\,6)" in vf and "0.60/TB" in vf, (
        f"{name}: the held frame is not placed at the gif's probed duration "
        f"(the stub answers 6 packets, 0.60 s): {vf}")


def _render_ffmpeg_argv(name, tmp_path, ffprobe_body=None):
    """Run a recipe's render block, returning the encode's ``ffmpeg`` argv.

    ``_run_render`` stubs ``ffmpeg`` with a body that writes the mp4, so a
    case that inspects the command needs the stub to record its argv first.
    The block's own success is asserted, because the options under test are
    what make the real encode work at all.
    """
    args_file = tmp_path / "ffmpeg-args"
    r, mp4, gif = _run_render(name, tmp_path, ffprobe_body=ffprobe_body,
                              ffmpeg_body=(
                                  f'printf "%s\\n" "$@" > "{args_file}"\n'
                                  'for a in "$@"; do last=$a; done\n'
                                  'printf mp4 > "$last"\n'))
    assert r.returncode == 0, r.stderr
    return args_file.read_text().splitlines()


@pytest.mark.parametrize("name", RECIPES)
@pytest.mark.parametrize("dims,upscaled", [
    ((640, 480), True),
    ((2048, 1152), True),
    ((2000, 1200), False),
    ((3000, 1000), False),
    ((3000, 2000), False),
], ids=["small", "at-the-ios-budget", "past-the-height-budget",
        "past-the-width-budget", "past-both-budgets"])
def test_render_chooses_its_scale_filter_by_the_gifs_size(name, tmp_path, dims,
                                                          upscaled):
    """The 2x upscale is bounded by the iOS hardware-decode budget.

    The render notes say the nearest-neighbor doubling is what keeps colored
    terminal text crisp at native size (4:2:0 chroma subsampling would blur
    it), but only while the result stays inside 4096x2304 (H.264 level 5.1):
    "an unconditional 2x on a large pane produces a video past level 5.1
    (e.g. 4276x2284), which desktop browsers play but iPhone/iPad hardware
    decoders silently refuse." Neither half had a case, and both breaks are
    silent: deleting the size guard left the whole file green (269 passed),
    as did replacing the upscale with a plain ``scale=iw:ih``. Verified with
    real ffmpeg 4.4.2 on a 2100x1200 gif: the guard's fallback encodes
    2100x1200, while the unconditional 2x writes a 4200x2400 stream labelled
    level 5.1 — the unplayable-on-iOS artifact the guard exists to prevent.
    The at-the-budget case pins the comparison as inclusive: exactly
    2048x1152 doubles to 4096x2304, which is still decodable.

    The guard is *two* bounds — ``gw * 2 <= 4096`` and ``gh * 2 <= 2304`` —
    and the original three cases moved them together: every gif past the
    budget was past both, so dropping either half alone left the whole file
    green (280 passed, verified in this container). A tall gif that fits the
    width budget (2000x1200, the shape a long terminal pane produces) then
    doubled to 4000x2400, and a wide one that fits the height budget
    (3000x1000) doubled to 6000x2000 — each over level 5.1's frame-size
    limit in the dimension the surviving half does not measure, and still
    labelled 5.1. Verified with the recipe's own block
    and real ffprobe/ffmpeg 4.4.2 on real GIFs: the shipped block encodes
    2000x1200 and 3000x1000, the block with the height bound deleted encodes
    4000x2400, and the one with the width bound deleted encodes 6000x2000.
    The two separating cases pin one half each; the both-past case pins the
    guard as a whole.
    """
    w, h = dims
    argv = _render_ffmpeg_argv(name, tmp_path, ffprobe_body=(
        'case "$*" in\n'
        f'  *width,height*) echo {w},{h} ;;\n'
        '  *nb_read_packets*) echo 6 ;;\n'
        '  *format=duration*) echo 0.60 ;;\n'
        '  *) echo h264 ;;\n'
        'esac\n'))
    vf = argv[argv.index("-vf") + 1]

    if upscaled:
        assert "scale=iw*2:ih*2:flags=neighbor" in vf, (
            f"{name}: a {w}x{h} gif is not doubled, so the video's terminal "
            f"text is blurred by 4:2:0 chroma subsampling: {vf}")
    else:
        assert "scale=trunc(iw/2)*2:trunc(ih/2)*2" in vf, (
            f"{name}: a {w}x{h} gif is not rendered at its native size, so "
            f"the doubled video is past the iOS decode budget: {vf}")
        assert "iw*2" not in vf, (
            f"{name}: a {w}x{h} gif is still doubled to {w * 2}x{h * 2}, past "
            f"the 4096x2304 level-5.1 budget iPhone/iPad refuse: {vf}")


@pytest.mark.parametrize("name", RECIPES)
def test_render_encodes_h264_that_plays_everywhere(name, tmp_path):
    """The encode's compatibility options are load-bearing, not style.

    The mp4 is the required artifact because "H.264 + yuv420p is the only
    combination that decodes everywhere, including iOS Safari", and
    ``-movflags +faststart`` puts the moov atom up front so playback starts
    before the download. No case pinned any of the three options: dropping
    ``-pix_fmt yuv420p``, ``-movflags +faststart`` or the ``libx264`` codec
    each left the whole file green (269 passed, verified). The pixel format
    is the sharp one — libx264 picks 4:4:4 for a GIF's pal8 input, and the
    block's own ``-profile:v high`` then refuses it: verified with the
    recipe's block and real ffmpeg 4.4.2, the render printed "high profile
    doesn't support 4:4:4" and the block reported "ffmpeg failed on the
    gif", blaming the input for an option the block itself dropped. The stub
    encoder cannot see any of that, so the argv is what the case has to read.
    """
    argv = _render_ffmpeg_argv(name, tmp_path)

    def value(flag):
        assert flag in argv, (
            f"{name}: the encode no longer passes {flag}, so the mp4 is not "
            f"the artifact the recipe promises: {argv}")
        return argv[argv.index(flag) + 1]

    assert value("-c:v") == "libx264", argv
    assert value("-pix_fmt") == "yuv420p", (
        f"{name}: the encode no longer forces yuv420p; libx264 picks 4:4:4 "
        f"for the gif and the high profile refuses it: {argv}")
    assert value("-movflags") == "+faststart", argv


def _install_block(name):
    """The fenced block that installs ``agg`` in the render section."""
    section = _recipe_text(name).split("## Render to video", 1)[1]
    for block in re.findall(r"```[a-z]*\n(.*?)```", section, re.S):
        if "agg-$(uname -m)" in block:
            return block
    raise AssertionError(f"{name}: no agg install block found")


def _run_install_block(name, tmp_path, curl_body=None, agg_present=False,
                       agg_body=None, local_on_path=True,
                       hold_agg_open=False, fail_tool=None):
    """Run the recipe's own ``agg`` install block against stub tools.

    ``agg_present`` seeds an ``agg`` in ``~/.local/bin`` (ahead of the stub
    PATH, as on the image); ``agg_body`` is its body, working by default, so a
    case can seed the truncated binary an interrupted download leaves.
    ``curl_body`` replaces the stub ``curl``. ``local_on_path`` puts
    ``~/.local/bin`` on PATH (the image's layout); with it off, the block
    installs a binary nothing can run. ``hold_agg_open`` starts a second
    process that holds the seeded ``agg`` open for writing for the whole run —
    the other worker's in-place download — so a case can exercise what happens
    when this block, or a render, executes a file that is being written.
    ``fail_tool`` makes one of the install's own tools (``mktemp``, ``chmod``
    or ``mv``) fail, so a case can drive each step of the temp-file-and-rename
    install where it breaks.
    Returns ``(proc, agg path, curl-called marker)``.
    """
    block = _install_block(name)
    home = tmp_path / "home"
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    agg = local / "agg"
    if agg_present:
        agg.write_text(agg_body or "#!/bin/sh\necho working\n")
        agg.chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "curl-called"
    # The block's own tools, stubbed to the real ones by absolute path, so the
    # test's PATH cannot pick up a host `agg` and mask the guard. `mktemp` and
    # `mv` are the atomic install's (temp file + rename) and are required even
    # when the case never reaches them.
    for tool in ("mkdir", "chmod", "uname", "rm", "mktemp", "mv"):
        real = shutil.which(tool)
        assert real, f"{tool} is required"
        if tool == fail_tool:
            _stub_tool(bindir, tool)          # exit 1: this step breaks
        else:
            _stub_tool(bindir, tool, f'exec "{real}" "$@"\n')
    # The stub's PATH is the stub dir itself, so it may only use builtins.
    _stub_tool(bindir, "curl", curl_body or f''': > "{called}"
for a in "$@"; do last=$a; done
printf '#!/bin/sh\\necho downloaded\\n' > "$last"
''')
    # `~/.local/bin` is on the image's PATH ahead of the system dirs, and the
    # stubs stand in for everything else, so no host `agg` can mask the guard.
    # `bash` itself is resolved before PATH is replaced.
    bash = shutil.which("bash")
    path = f"{local}:{bindir}" if local_on_path else str(bindir)
    env = dict(os.environ, HOME=str(home), PATH=path)
    if hold_agg_open:
        # A second worker's in-place `curl -o ~/.local/bin/agg`, still
        # running: it holds the shared path open for writing while this
        # block runs. The seeded file must exist for the holder to open it.
        assert agg_present, "hold_agg_open needs the seeded agg"
        ready = tmp_path / "holder-ready"
        holder = subprocess.Popen(
            ["bash", "-c", f'exec 3>>"{agg}"; : > "{ready}"; sleep 30'])
        try:
            deadline = time.time() + 5
            while not ready.exists() and time.time() < deadline:
                time.sleep(0.02)
            assert ready.exists(), "the concurrent-writer fixture never started"
            r = subprocess.run([bash], input=block, env=env,
                               capture_output=True, text=True, timeout=60)
        finally:
            holder.kill()
            holder.wait()
        return r, agg, called
    r = subprocess.run([bash], input=block, env=env,
                       capture_output=True, text=True, timeout=60)
    return r, agg, called


@pytest.mark.parametrize("name", RECIPES)
@pytest.mark.parametrize("agg_present", [True, False])
def test_renderer_install_block_only_runs_when_agg_is_missing(name,
                                                              agg_present,
                                                              tmp_path):
    """A working `agg` is left alone instead of re-downloaded over.

    The block's job is to make ``agg`` run, not to replace one that does: a
    download is a network dependency the render does not need, and an in-place
    transfer that failed partway would leave a truncated binary that shadows
    the image's working ``agg`` (verified: a dropped transfer replaced a
    working agg with a 500-byte file — the block now installs through a temp
    file and a rename, so its own transfer cannot shadow anything, but the
    guard still keeps a working binary from depending on the network). The
    bundled Dockerfile installs ``agg``, so a worker pasting the remedy block
    on a current image would take that risk for nothing — the block is
    guarded on a check a working ``agg`` passes (``agg --version``), matching
    the prose that says to install it only when that fails.
    This runs the recipe's own block both ways against a stub ``curl``.
    """
    r, agg, called = _run_install_block(name, tmp_path, agg_present=agg_present)

    assert r.returncode == 0, r.stderr
    if agg_present:
        assert not called.exists(), (
            f"{name}: the install block downloaded over a working agg, and a "
            "failed transfer would leave a truncated binary earlier on PATH")
        assert agg.read_text() == "#!/bin/sh\necho working\n", (
            f"{name}: the install block replaced the existing agg")
    else:
        assert called.exists(), (
            f"{name}: the install block did nothing although agg is missing")
        assert agg.read_text() == "#!/bin/sh\necho downloaded\n", agg.read_text()
        assert os.access(agg, os.X_OK), (
            f"{name}: the downloaded agg is never made executable")


@pytest.mark.parametrize("name", RECIPES)
def test_renderer_install_replaces_an_agg_that_does_not_run(name, tmp_path):
    """A truncated `agg` resolves, so a resolvability guard makes it permanent.

    The recipe's own comment records the shape: a dropped transfer replaced a
    working ``agg`` with a 500-byte file earlier on PATH. ``command -v agg``
    answers that file, so a guard on resolvability skips the install — and the
    render then fails with "agg failed on the cast — is 'agg' installed?",
    whose remedy is this very block: a remedy that cannot work, in a loop (the
    shape R31 fixed for the binary that does not resolve, one step over).
    ``agg --version`` is the handle: a working agg answers 0, a truncated or
    wrong-architecture one fails to execute.
    """
    r, agg, called = _run_install_block(
        name, tmp_path, agg_present=True,
        agg_body="#!/bin/sh\nexit 126\n")     # resolves, does not run

    assert called.exists(), (
        f"{name}: the install block skipped a resolvable agg that does not "
        "run, so the render's 'is agg installed?' remedy is inert")
    assert agg.read_text() == "#!/bin/sh\necho downloaded\n", (
        f"{name}: the install block did not replace the broken agg: "
        + agg.read_text())
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("name", RECIPES)
def test_renderer_install_names_an_agg_that_still_does_not_run(name, tmp_path):
    """An install that leaves a resolvable but broken agg must not pass.

    The download can arrive truncated or for another architecture: the file
    resolves on PATH, so the resolvability check passes, and it exits 126
    when run. The block would then exit 0 with the render's "is 'agg'
    installed?" unchanged — the same loop its resolvability check exists to
    stop, one shape further in. It has to name the binary and stop.
    """
    r, agg, called = _run_install_block(
        name, tmp_path,
        curl_body=f''': > "{tmp_path / "curl-called"}"
for a in "$@"; do last=$a; done
printf '#!/bin/sh\\nexit 126\\n' > "$last"
''')

    assert called.exists(), "the fixture did not run the install"
    assert r.returncode != 0, (
        f"{name}: the install block exited 0 although the agg it left does "
        "not run, so the render sends the worker back to the same block")
    assert "does not run" in r.stderr, r.stderr
    assert str(agg) in r.stderr, (
        f"{name}: the failure does not name the agg to remove: " + r.stderr)


@pytest.mark.parametrize("name", RECIPES)
def test_renderer_install_is_bounded_and_drops_a_partial_download(name,
                                                                  tmp_path):
    """The install download is the last unbounded request in the recipes.

    Every other request is bounded — the readiness polls per attempt, the
    Layer 2 route snapshots with ``--connect-timeout``/``--max-time`` —
    because one that accepts the connection and never answers hangs the
    worker. ``curl`` with no deadline is that wait one step earlier, and a
    transfer that dies mid-body leaves a partial file behind. Since R72 the
    download goes to a per-process temp file rather than in place, so the
    partial can no longer shadow the image's working ``agg`` on PATH — but it
    is still this block's litter, and the block's own failure path is the
    only thing that removes it (deleting that ``rm -f "$agg_tmp"`` left the
    whole file green, verified). It has to be removed and the failure named.
    """
    block = _install_block(name)
    assert "--connect-timeout" in block and "--max-time" in block, (
        f"{name}: the agg install download has no deadline: " + block)

    # A transfer that dies mid-body: curl exits 18 and leaves a partial file.
    r, agg, _called = _run_install_block(
        name, tmp_path,
        curl_body='for a in "$@"; do last=$a; done\n'
                  'printf "partial" > "$last"\nexit 18\n')

    assert r.returncode != 0, (
        f"{name}: a failed agg download was reported as a successful install")
    assert not agg.exists(), (
        f"{name}: a failed download left a partial agg earlier on PATH than "
        "the image's working binary")
    assert not list(agg.parent.glob("agg.tmp.*")), (
        f"{name}: a failed download left its temp file behind in "
        "~/.local/bin — the block's failure path is what removes it")
    assert "could not download agg" in r.stderr, r.stderr


@pytest.mark.parametrize("name", RECIPES)
def test_renderer_install_survives_a_concurrent_in_place_download(name,
                                                                  tmp_path):
    """Two workers sharing one HOME must not execute a download in progress.

    QA S22 (2026-10-28) observed the shape with two workers sharing one HOME:
    both pass the ``agg --version`` guard, both run the install, and with
    ``curl -o ~/.local/bin/agg`` writing in place one transfer is still open
    for writing when the other worker's render — or its own post-install
    check — executes that path. The exec fails with ETXTBSY ("Text file
    busy"), the block reports "the agg on PATH (...) does not run — remove it
    and re-run the render", and the render reports "agg failed on the cast —
    is 'agg' installed?": the wrong cause in both, with a remedy that deletes
    the binary the other worker just finished installing (verified in this
    container against the pre-fix block and the pre-fix render block). The
    download now goes to a private ``mktemp`` file and is renamed into place,
    so a reader sees either the previous binary or the complete new one.
    This case holds the shared path open for writing for the whole run; the
    block must still install and report success, and leave no temp file.
    """
    r, agg, called = _run_install_block(
        name, tmp_path, agg_present=True, hold_agg_open=True)

    assert called.exists(), "the fixture did not run the install"
    assert r.returncode == 0, (
        f"{name}: the install failed although the only thing wrong was "
        "another worker's in-place download holding the shared path open "
        "(the wrong-cause ETXTBSY failure): " + r.stderr)
    assert "does not run" not in r.stderr, r.stderr
    assert agg.read_text() == "#!/bin/sh\necho downloaded\n", agg.read_text()
    assert not list(agg.parent.glob("agg.tmp.*")), (
        f"{name}: the install left a temp file beside the installed agg")


@pytest.mark.parametrize("name", RECIPES)
def test_renderer_install_names_an_agg_it_cannot_resolve(name, tmp_path):
    """An install that leaves ``agg`` off PATH must not report success.

    ``~/.local/bin`` is on PATH in the image, but where it is not the block
    downloads ``agg`` and exits 0 with a binary nothing can run: the render
    then fails with "agg failed on the cast — is 'agg' installed?", the worker
    pastes this block again, it downloads again and exits 0 — a remedy that
    cannot work, in a loop. The block's job is to make ``agg`` *resolvable*,
    so it has to say when the file it wrote still is not.
    """
    r, agg, called = _run_install_block(name, tmp_path, local_on_path=False)

    assert called.exists(), "the fixture did not run the install"
    assert agg.exists(), "the fixture installed no agg to fail on"
    assert r.returncode != 0, (
        f"{name}: the install block exited 0 while `agg` still does not "
        "resolve on PATH, so the render sends the worker back to the same "
        "block")
    assert "does not resolve" in r.stderr, r.stderr
    assert "~/.local/bin" in r.stderr and "PATH" in r.stderr, (
        f"{name}: the failure does not name the directory to put on PATH: "
        + r.stderr)


@pytest.mark.parametrize("name", RECIPES)
@pytest.mark.parametrize("fail_tool,message,downloaded", [
    ("mktemp", "could not create a temporary file", False),
    ("chmod", "could not make the downloaded agg executable", True),
    ("mv", "could not install the downloaded agg", True),
], ids=["no-temp-file", "chmod-fails", "rename-fails"])
def test_renderer_install_names_the_step_that_failed(name, fail_tool, message,
                                                     downloaded, tmp_path):
    """Every step of the temp-file install fails in its own words.

    R72 moved the download to a per-process ``mktemp`` file that is chmodded
    and renamed into place, and R74 pinned the download branch's
    ``rm -f "$agg_tmp"``. The install's other three failure paths had no case
    at all: removing all three guards left the whole file green (284 passed,
    verified in this container). They are load-bearing, not decoration.

    Without the ``mktemp`` guard the block runs on with an empty ``agg_tmp``
    and reports "could not download agg" for a download that never started;
    without the ``chmod`` guard it renames a non-executable file into place
    and reports "the agg on PATH (…) does not run — remove it", whose remedy
    deletes a binary that was never the problem; without the rename guard it
    reports "installed ~/.local/bin/agg but 'agg' still does not resolve" for
    an install whose rename failed — each a failure naming a cause the step
    cannot have, the class this PR is about. Each branch also removes only
    its own temp, so a failed install leaves neither a stray ``agg.tmp.…``
    nor a damaged binary: the seeded ``agg`` resolves and does not run, so
    the block is entered (a working one is left alone by design), and the
    case requires it to come out byte-for-byte unchanged. ``downloaded`` says
    whether the step under test runs before or after the transfer, so the
    case also pins that a missing temp file stops the block before it starts
    a download it cannot write into.
    """
    broken = "#!/bin/sh\nexit 126\n"
    r, agg, called = _run_install_block(
        name, tmp_path, agg_present=True, agg_body=broken,
        fail_tool=fail_tool)

    assert called.exists() == downloaded, (
        f"{name}: the `{fail_tool}` failure came "
        f"{'after' if downloaded else 'before'} the download, as expected")
    assert r.returncode != 0, (
        f"{name}: the install block exited 0 although `{fail_tool}` failed, "
        "so a failed install is reported as a successful one")
    assert message in r.stderr, r.stderr
    assert agg.read_text() == broken, (
        f"{name}: a failed install overwrote or removed the agg that was "
        "already there: " + agg.read_text())
    assert not list(agg.parent.glob("agg.tmp.*")), (
        f"{name}: the failed `{fail_tool}` path left its temp file in "
        "~/.local/bin")


def test_cli_tee_fallback_writes_the_transcript_into_the_capture_dir():
    """The no-asciinema fallback must put its transcript where the capture is.

    The fallback is ``| tee transcript.log`` — a relative path, so the file
    lands in whatever directory the worker happens to be in (the PR workdir,
    say) while the manifest lists a transcript the capture directory does not
    hold. That is the same "a promised artifact is written somewhere the
    capture does not look" bug as the no-TTY scaffold's cast path (R5), one
    file over: the worker follows the recipe and the capture still has no
    transcript. The produced-files list has to name the file too, because it
    is the only artifact that fallback produces.
    """
    text = _recipe_text("cli-recording.md")
    fallback = text[text.index("If `asciinema` isn't installed"):]
    assert "tee <capture-dir>/<short-name>/transcript.log" in fallback, (
        "the tee fallback writes a relative transcript.log into the worker's "
        "cwd, so the capture directory has no transcript")
    produced = text.split("## What this recipe produces", 1)[1].split(
        "## Capture", 1)[0]
    assert "transcript.log" in produced, (
        "the produced-files list never names the fallback's transcript.log, "
        "so the manifest and the capture directory disagree")


def test_cli_stop_failure_names_the_interactive_remedy():
    """The stop failure must not send an interactive recording to the wrong fix.

    The block is pasted as one unit, and step 3 (driving the shell) is
    comments, so a worker that pastes it whole for the ``-c bash`` form waits
    out the stop bound with the shell still at its prompt. The message used to
    offer only ``RECORDER_STOP_TIMEOUT`` — raising it for an interactive
    recording just makes the same failure slower. It has to name the actual
    remedy: ``exit`` in the recorded shell.
    """
    block = _scaffold_block(_recipe_text("cli-recording.md"))
    stop = block[block.index("stop_timeout="):]
    body = stop[:stop.index("\ndone")]
    assert "interactive" in body and "'exit'" in body, (
        "cli-recording: the stop timeout does not name the interactive "
        "remedy ('exit' in the recorded shell), so raising "
        "RECORDER_STOP_TIMEOUT is the only fix it suggests")


def _web_ui_finalize_block():
    """The fenced block under ``### 3. Finalize`` (the transcode step)."""
    text = _recipe_text("web-ui-recording.md")
    finalize = text.split("### 3. Finalize", 1)[1].split("## Capture", 1)[0]
    return re.findall(r"```[a-z]*\n(.*?)```", finalize, re.S)[0]


def test_web_ui_finalize_refuses_an_unset_capdir(tmp_path):
    """The finalize step must not run its new `rm -f` against the filesystem root.

    Step 1's cleanup guards its screenshot glob with ``${CAPDIR:?}`` for
    exactly this reason, and the blocks are pasted separately, so a worker
    that runs step 3 in a fresh shell has no ``CAPDIR``: the ``rm -f`` then
    targets ``/recording.mp4`` and ffmpeg is handed ``/recording.webm``. The
    step stops with a message instead.
    """
    block = _web_ui_finalize_block()

    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "ffmpeg-called"
    _stub_tool(bindir, "ffmpeg", f'touch "{called}"\n')
    env = {k: v for k, v in os.environ.items() if k != "CAPDIR"}
    env["PATH"] = f"{bindir}:{os.environ['PATH']}"
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        "web-ui recipe's finalize step ran with no CAPDIR")
    assert "CAPDIR" in r.stderr, (
        "the finalize step does not say that CAPDIR is missing: " + r.stderr)
    assert not called.exists(), (
        "the finalize step ran ffmpeg with an unset CAPDIR, so it read and "
        "wrote paths at the filesystem root")


def test_web_ui_finalize_refuses_a_missing_capture_dir(tmp_path):
    """A set-but-missing CAPDIR is not "the driver wrote no video".

    The driver and Layer 2 blocks both stop on a directory they cannot enter
    (R15), but the finalize block guarded only an *unset* CAPDIR: pasted with
    a wrong or un-created path it reported "there is no webm to transcode —
    the driver wrote no video; re-run step 2", sending the worker to re-drive
    a UI for a directory that is simply not there (verified: the pre-fix
    block exits 1 with that message). The same guard one block over is what
    makes every step's failure name its own cause.
    """
    missing = tmp_path / "does-not-exist"
    block = _web_ui_finalize_block()

    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "ffmpeg-called"
    _stub_tool(bindir, "ffmpeg", f'touch "{called}"\n')
    env = dict(os.environ, CAPDIR=str(missing),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        "the finalize step ran against a capture directory that is not there")
    assert "does not exist" in r.stderr, (
        "a missing capture directory is not named: " + r.stderr)
    assert "there is no webm to transcode" not in r.stderr, (
        "a missing capture directory is reported as a driver that recorded "
        "nothing: " + r.stderr)
    assert not called.exists(), "the finalize step ran ffmpeg anyway"


@UNWRITABLE_MODES
def test_web_ui_finalize_refuses_a_capture_dir_it_cannot_write(tmp_path,
                                                                capdir_mode):
    """An unwritable capture directory is reported as a failed transcode.

    The directory exists, so the block's own checks pass and ffmpeg runs; its
    output cannot be created, and the block exits 1 with "transcode produced
    no mp4 — …" — blaming the encoder and the recording for a permissions
    problem, with no remedy that can work (verified live with a mode-500
    capture directory and a webm in place: "ffmpeg failed on the driver's
    webm" with a real encoder, "ffmpeg wrote nothing" with a stub that exits
    0). The same guard the missing-directory case added, one shape over.

    Mode 600 (write bit, no search bit) is the other shape: `[ -w ]` passes
    and only the guard's `[ -x ]` half refuses it, because the block cannot
    reach the webm or create the mp4 inside it either.
    """
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        pytest.skip("root bypasses the directory permission bits")
    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "ffmpeg-called"
    _stub_tool(bindir, "ffmpeg", f'touch "{called}"\n')
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    capdir.chmod(capdir_mode)
    try:
        r = subprocess.run(["bash"], input=_web_ui_finalize_block(), env=env,
                           capture_output=True, text=True)
    finally:
        capdir.chmod(0o700)

    assert r.returncode != 0, (
        "the finalize step ran into a capture directory nothing can be "
        "written into")
    assert "cannot be written" in r.stderr, r.stderr
    assert "transcode produced no mp4" not in r.stderr, (
        "an unwritable capture directory is reported as a failed transcode "
        "of the driver's webm: " + r.stderr)
    assert not called.exists(), "the finalize step ran ffmpeg anyway"


def test_web_ui_finalize_transcodes_when_capdir_is_set(tmp_path):
    """The guard must not break the step it protects."""
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # A real transcode stand-in: writes the mp4 the step checks for.
    _stub_tool(bindir, "ffmpeg",
               'for a in "$@"; do last=$a; done\nprintf mp4 > "$last"\n')
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode == 0, r.stderr
    assert (capdir / "recording.mp4").read_bytes() == b"mp4"
    assert not (capdir / "recording.webm").exists(), (
        "the finalize step keeps the webm although the mp4 exists")


def test_web_ui_finalize_pasted_twice_keeps_the_published_video(tmp_path):
    """A repeated finalize is a check, not a re-encode.

    The step publishes ``recording.mp4`` and then removes ``recording.webm``,
    the source, so a second paste has nothing to transcode. Without a guard it
    removed the *published* mp4 first and then reported "there is no webm to
    transcode — the driver wrote no video; re-run step 2 and check the
    driver's recordVideo option": a cause the driver does not have, and a
    remedy that throws a finished capture away. Verified in this container
    with the recipe's own block and real ffmpeg 4.4.2 — after the first
    finalize the directory held only a 13,917-byte ``recording.mp4``, and the
    second paste left it **empty** and exited 1 with that message. Every block
    in this recipe is pasted on its own, and a resumed session (or a worker
    checking its work) pastes this one again; the tmux recipe's step 5 handles
    the same state after its own detach.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.mp4").write_bytes(b"published")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "ffmpeg-called"
    _stub_tool(bindir, "ffmpeg", f'touch "{called}"\n')
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=_web_ui_finalize_block(), env=env,
                       capture_output=True, text=True)

    assert r.returncode == 0, (
        "a finalize pasted after a successful finalize failed: " + r.stderr)
    assert "already finalized" in r.stderr, r.stderr
    assert "the driver wrote no video" not in r.stderr, (
        "a finished capture is reported as a driver that recorded nothing: "
        + r.stderr)
    assert (capdir / "recording.mp4").read_bytes() == b"published", (
        "the second paste destroyed the published recording")
    assert not called.exists(), "the second paste ran ffmpeg"


def test_web_ui_finalize_does_not_treat_an_empty_mp4_as_published(tmp_path):
    """An empty mp4 is not this step's own finished state.

    The "already finalized" branch exists for a second paste of the step: an
    mp4 with no webm and no partial can only be a finalize's output, because
    step 1's and step 2's cleanups both remove ``recording.mp4``. The check
    is ``test -s``, so a 0-byte file is *not* that state — an empty output is
    exactly what the step's own ``[ -s partial ]`` check keeps off the
    published name. Mutating it to ``-e`` left the whole file green: the
    block would report a capture holding an empty file as "already
    finalized", exit 0 and present it as the run's video, the same
    "an artifact that exists but is empty is not an artifact" gap R46/R80
    closed for the stage inputs.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.mp4").write_bytes(b"")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "ffmpeg-called"
    _stub_tool(bindir, "ffmpeg", f'touch "{called}"\n')
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=_web_ui_finalize_block(), env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        "a capture holding only an empty mp4 was reported as finalized")
    assert "already finalized" not in r.stderr, r.stderr
    assert "there is no webm to transcode" in r.stderr, r.stderr
    assert not called.exists(), (
        "the finalize step ran ffmpeg with no webm to read")
    assert not (capdir / "recording.mp4").exists(), (
        "the failed step left the empty mp4 as this run's recording")


def test_web_ui_finalize_never_consumes_the_script_on_stdin(tmp_path):
    """The finalize ffmpeg must not read the worker's stdin.

    Recipe blocks are run by feeding them to bash on stdin — this module's
    execution cases do, and a worker scripting a capture or an automated
    agent executing one does the same (`bash < block`), the shape the
    recording recipes' render note describes for a batch loop (QA S46, where
    ffmpeg ate characters of the loop's next input). An ffmpeg allowed to
    read stdin consumes the bytes that follow it, so bash then executes a
    mangled line: verified with the recipe's own block and ffmpeg 4.4.2 fed
    on stdin, ffmpeg ate the first two bytes of the next line (`#T` of the
    comment block) and bash answered "bash: line 83: he: command not found"
    (the one-byte stub below leaves `The` and answers "The: command not
    found"); a longer encode or a batch loop loses more. On a terminal the
    same read is a false success: `q` makes ffmpeg exit 0 after writing a
    container with no frames (262 bytes, verified), which the step's `test -s`
    accepts, and the step then deletes the webm — the only copy of the
    recording.

    The recording recipes' `render_cast` passes `-nostdin` for exactly this
    reason (`test_render_keeps_the_vfr_and_nostdin_encode`); the finalize step
    was the one render call without it. The stub models real ffmpeg's stdin
    behaviour — it reads (and so consumes) one byte unless `-nostdin` is
    given — and the block is fed on stdin, as a scripted worker feeds it.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_tool(bindir, "ffmpeg", (
        'nostdin=0\n'
        'for a in "$@"; do [ "$a" = "-nostdin" ] && nostdin=1; last=$a; done\n'
        'if [ "$nostdin" = 0 ]; then head -c 1 >/dev/null 2>&1 || true; fi\n'
        'printf mp4 > "$last"\n'))
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert "command not found" not in r.stderr, (
        "the finalize step's ffmpeg read the script after it, so bash ran a "
        "mangled line: " + r.stderr)
    assert r.returncode == 0, r.stderr
    assert (capdir / "recording.mp4").read_bytes() == b"mp4", (
        "the finalize step did not produce its mp4")
    assert not (capdir / "recording.webm").exists(), (
        "the finalize step kept the webm although the mp4 exists")


def test_web_ui_finalize_encodes_h264_that_plays_everywhere(tmp_path):
    """The finalize's compatibility options have no case either.

    The recipe's whole reason for transcoding is that Playwright records VP8
    webm, which "does not decode on iOS", so the step promises "H.264 mp4 so
    it plays everywhere including iOS Safari" — that is ``libx264`` with
    ``yuv420p`` and ``-movflags +faststart``. Dropping ``-pix_fmt yuv420p``
    or ``-movflags +faststart`` from this block left the whole file green
    (269 passed, verified), and the execution cases above cannot see it: the
    stub encoder accepts whatever it is handed. The argv is the handle.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    args_file = tmp_path / "ffmpeg-args"
    _stub_tool(bindir, "ffmpeg", (
        f'printf "%s\\n" "$@" > "{args_file}"\n'
        'for a in "$@"; do last=$a; done\nprintf mp4 > "$last"\n'))
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode == 0, r.stderr
    argv = args_file.read_text().splitlines()

    def value(flag):
        assert flag in argv, (
            f"the finalize step no longer passes {flag}, so the mp4 is not "
            f"the artifact the recipe promises: {argv}")
        return argv[argv.index(flag) + 1]

    assert value("-c:v") == "libx264", argv
    assert value("-pix_fmt") == "yuv420p", (
        f"the finalize step no longer forces yuv420p, the pixel format the "
        f"recipe says iOS Safari requires: {argv}")
    assert value("-movflags") == "+faststart", argv


@pytest.mark.parametrize("webm_shape", ["absent", "empty"],
                         ids=["no-file", "0-byte-file"])
def test_web_ui_finalize_says_when_there_is_no_webm(tmp_path, webm_shape):
    """A missing webm is not an ffmpeg problem, and must not send the worker there.

    The driver block checks the driver's exit status (R18), but a driver that
    exits 0 without recording still writes no webm — ``recordVideo`` dropped
    while adapting it, or a ``video`` that came back null. The finalize step
    then handed ffmpeg a nonexistent input and reported "transcode produced no
    mp4 — ffmpeg failed on the driver's webm" (verified live), which points at
    the encoder: the same misdiagnosis R12 fixed for a missing cast. The stale
    mp4 must still go, so a failed run cannot present the previous run's video.

    The check is ``test -s``, so a **0-byte** webm is one of the states it is
    for, and only the absent file was modelled — the same gap the recording
    recipes' cast and gif checks had. Weakened to ``-e`` the file stayed
    green, and real ffmpeg answers "EBML header parsing failed … Invalid data
    found when processing input" for the empty file, which the step reports as
    a failed transcode of the driver's webm.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    if webm_shape == "empty":
        (capdir / "recording.webm").write_bytes(b"")
        # The failing step still drops the earlier attempt's mp4 — the stale
        # rule this case has always pinned. The *no-file* shape seeds none:
        # step 1's and step 2's cleanups remove it, so "no webm, no partial,
        # an mp4 here" is the finalize's own finished state and is reported
        # as "already finalized" instead
        # (test_web_ui_finalize_pasted_twice_keeps_the_published_video).
        (capdir / "recording.mp4").write_bytes(b"an earlier run's video")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "ffmpeg-called"
    _stub_tool(bindir, "ffmpeg", f'touch "{called}"\n')
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, "a transcode with no webm was reported as success"
    assert "there is no webm to transcode" in r.stderr, r.stderr
    assert "ffmpeg failed" not in r.stderr, (
        "the no-webm failure blames the encoder: " + r.stderr)
    assert not called.exists(), (
        "the finalize step ran ffmpeg with no webm to read")
    assert not (capdir / "recording.mp4").exists(), (
        "the no-webm failure left the previous run's mp4 as this run's "
        "recording")


def test_web_ui_finalize_names_a_killed_drivers_partial(tmp_path):
    """A killed driver's auto-named partial is not "the driver wrote no video".

    Playwright names its video ``page@<hash>.webm`` and the driver renames it
    onto ``recording.webm`` only after a complete walk-through, so a driver
    killed before that rename (a supervisor, an OOM kill, or the worker's
    session torn down while it ran) leaves the partial and no
    ``recording.webm``. The finalize step's no-webm branch reported that state
    as "the driver wrote no video; re-run step 2 and check the driver's
    recordVideo option" — a cause the capture directory contradicts, and a
    remedy aimed at a driver option that was never the problem (the driver
    recorded; it was killed). It is also the state a worker reaches without
    any step-2 message: a torn-down session never runs the driver block's own
    failure path, so the worker resumes at step 3.

    Verified in this container with the recipe's own block: with only
    ``page@b87f….webm`` in the capture directory the shipped step printed
    "there is no webm to transcode — the driver wrote no video; re-run step 2
    and check the driver's recordVideo option". The step names the partial
    where it is, and still refuses to publish it.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    partial = capdir / "page@0123456789abcdef.webm"
    partial.write_bytes(b"a killed driver's partial recording")
    (capdir / "recording.mp4").write_bytes(b"an earlier run's video")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "ffmpeg-called"
    _stub_tool(bindir, "ffmpeg", f'touch "{called}"\n')
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, "a capture with no recording.webm passed"
    assert "page@0123456789abcdef.webm" in r.stderr, (
        "the failure does not name the partial the driver left: " + r.stderr)
    assert "killed before it" in r.stderr, (
        "the failure does not say the driver was killed before the rename: "
        + r.stderr)
    assert "recordVideo" not in r.stderr, (
        "the failure sends the worker to the driver's recordVideo option for "
        "a driver that recorded and was killed: " + r.stderr)
    assert not called.exists(), (
        "the finalize step ran ffmpeg with no recording.webm to read")
    assert not (capdir / "recording.mp4").exists(), (
        "the no-webm failure left the previous run's mp4 as this run's "
        "recording")
    assert partial.exists(), (
        "the finalize step removed the killed driver's partial, which the "
        "produced-files list tells the worker to mention")


def test_web_ui_finalize_names_a_missing_encoder(tmp_path):
    """A missing `ffmpeg` is not a failed transcode of the driver's webm.

    The finalize step checked the webm (R19) and ffmpeg's exit status (R12),
    but never that the encoder exists, and the recipe never named it as a
    prerequisite. Verified: with no ``ffmpeg`` on ``PATH`` the shell answers
    "ffmpeg: command not found" (status 127) and the block reports
    "transcode produced no mp4 — ffmpeg failed on the driver's webm" — an
    encoder/browser misdiagnosis for a tool that is simply not installed, the
    same shape as the missing-cast/missing-webm messages the recipe now gets
    right. The block names the cause, keeps the webm (so the transcode can be
    retried once ffmpeg is installed) and still drops the stale mp4.
    """
    block = _web_ui_finalize_block()
    tooling = _recipe_text("web-ui-recording.md").split("## Tooling", 1)[1]
    tooling = tooling.split("## What this recipe produces", 1)[0]
    assert "ffmpeg" in tooling, (
        "the recipe does not name the encoder the finalize step needs")

    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    (capdir / "recording.mp4").write_bytes(b"an earlier run's video")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # Only what the block needs before the transcode; no ffmpeg anywhere.
    (bindir / "rm").symlink_to("/bin/rm")
    env = {"CAPDIR": str(capdir), "PATH": str(bindir)}
    r = subprocess.run(["/bin/bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, "a finalize step with no encoder succeeded"
    assert "ffmpeg is not installed" in r.stderr, r.stderr
    assert "ffmpeg failed on the driver's webm" not in r.stderr, (
        "a missing encoder is reported as a failed transcode of the driver's "
        "webm: " + r.stderr)
    assert (capdir / "recording.webm").exists(), (
        "the webm was dropped although nothing was transcoded")
    assert not (capdir / "recording.mp4").exists(), (
        "the failure left the previous run's mp4 as this run's recording")


def test_web_ui_failed_transcode_leaves_no_partial_mp4(tmp_path):
    """`test -s` on the mp4 is not proof the transcode finished.

    Verified with real ``ffmpeg``: killing an encode mid-flight leaves a
    *non-empty* output (267,945 bytes on SIGKILL, 119,704 on SIGTERM, neither
    a playable video), so the finalize step's file check alone reports a
    successful transcode for a video the report cannot play — the
    header-only-cast bug again, one artifact over. ffmpeg's own exit status is
    the handle, and its partial output goes with it. The encode writes
    ``recording.mp4.partial.mp4`` and renames it only on success (R66), so the
    file this case has to see removed is the *partial* — checking
    ``recording.mp4`` alone is vacuous, because no failure path of the block
    ever writes that name.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_tool(bindir, "ffmpeg",
               'for a in "$@"; do last=$a; done\nprintf partial > "$last"\nexit 1\n')
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        "a failed transcode that left a partial mp4 was reported as success")
    assert "transcode produced no mp4" in r.stderr, r.stderr
    assert not (capdir / "recording.mp4").exists(), (
        "a failed transcode published its partial mp4 as this run's "
        "recording")
    assert not (capdir / "recording.mp4.partial.mp4").exists(), (
        "a failed transcode left its partial output behind, so an "
        "interrupted encode's video survives as this run's evidence")


def test_web_ui_finalize_publishes_through_a_partial_name(tmp_path):
    """An interrupted transcode must not publish under the final name.

    The exit-status check catches an ffmpeg that *fails*, but not one the
    worker's shell no longer lives to see: a finalize killed while ffmpeg ran
    (the worker timed out, its session ended, the container was stopped) runs
    no cleanup at all. Writing straight to ``recording.mp4`` then leaves a
    non-empty partial — verified here with a stub that writes the output and
    SIGKILLs the block's shell — under the exact name the manifest and the
    report present as this run's video. The recording recipes' ``render_cast``
    publishes through ``recording.mp4.partial.mp4`` and renames only after a
    complete encode for this reason; the finalize step was the one render call
    that published directly.

    The partial is named in the produced-files list and the manifest example
    (``test_web_ui_produced_files_list_names_the_files_a_failed_run_keeps``),
    and both step 1's and step 2's cleanups clear it.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # Write the output the way real ffmpeg does, then kill the shell that
    # would have checked its status — the shape no in-block cleanup can run.
    # The shell's pid comes from a launcher that `exec`s bash, so the stub
    # cannot signal the wrong process (the test runner) if bash ever execs
    # its child instead of forking.
    pidfile = tmp_path / "block-shell.pid"
    _stub_tool(bindir, "ffmpeg",
               'for a in "$@"; do last=$a; done\n'
               'printf partial > "$last"\n'
               'kill -9 "$(cat "$BLOCK_PID_FILE")"\n')
    launcher = tmp_path / "launch-block.sh"
    launcher.write_text('#!/bin/sh\necho $$ > "$BLOCK_PID_FILE"\nexec bash\n')
    launcher.chmod(0o755)
    env = dict(os.environ, CAPDIR=str(capdir),
               BLOCK_PID_FILE=str(pidfile),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run([str(launcher)], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        "the block exited 0 although its shell was killed mid-transcode")
    assert not (capdir / "recording.mp4").exists(), (
        "a finalize killed mid-transcode published its partial mp4 under "
        "recording.mp4, the name the manifest and the report present as this "
        "run's video")
    assert (capdir / "recording.mp4.partial.mp4").exists(), (
        "the interrupted transcode left nothing under the partial name, so "
        "the recipe's produced-files list cannot explain what it leaves")
    assert (capdir / "recording.webm").exists(), (
        "the interrupted finalize dropped the webm, the only complete "
        "recording")


def test_web_ui_finalize_names_a_publish_that_failed(tmp_path):
    """A rename that fails is not a bad transcode.

    The encode writes ``recording.mp4.partial.mp4`` and publishes it by
    renaming onto ``recording.mp4`` (R66). The rename is what makes the
    partial this run's video: if it fails (the directory went away, a
    filesystem error), the partial must not be left looking like a finished
    recording, and the worker has to be told the publish failed rather than
    that ffmpeg wrote nothing. The recording recipes' ``render_cast`` has the
    same guard and a case (``test_render_names_a_publish_that_failed``); the
    finalize step's guard had none — with it removed the block still exits 1,
    but at the final ``test -s`` ("the published mp4 is not there") with the
    partial left behind.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_tool(bindir, "ffmpeg",
               'for a in "$@"; do last=$a; done\nprintf mp4 > "$last"\n')
    _stub_tool(bindir, "mv", 'exit 1\n')
    (bindir / "rm").symlink_to("/bin/rm")
    env = {"CAPDIR": str(capdir), "PATH": str(bindir)}
    r = subprocess.run(["/bin/bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, "a failed publish was reported as success"
    assert "could not publish" in r.stderr, r.stderr
    assert "transcode produced no mp4" not in r.stderr, (
        "a failed rename is reported as an encoder failure: " + r.stderr)
    assert not (capdir / "recording.mp4").exists()
    assert not (capdir / "recording.mp4.partial.mp4").exists(), (
        "a failed publish left the partial beside no mp4, so the produced-"
        "files list explains it as an interrupted encode's output")
    assert (capdir / "recording.webm").exists(), (
        "the webm was dropped although nothing was published")


def test_web_ui_finalize_names_a_publish_that_left_no_mp4(tmp_path):
    """A rename that reports success but publishes nothing must not lose the webm.

    The finalize step's last check is the published mp4 itself: the rename
    reports success, so nothing else notices that the file is not there (a
    concurrent cleanup, a tmp cleaner, a rename that crossed a filesystem
    boundary and left nothing). Without that backstop the block runs its final
    ``rm -f recording.webm`` and exits 0 — a failed publish reported as a
    successful capture that also destroys the only copy of the driver's video,
    the same "a false success that destroys the source" shape as the
    ``-nostdin`` bug (R63). The check was pinned only as *text*
    (``test_web_ui_clears_a_previous_video``); no case made it fire, so the
    removal above went unseen by every behavioral case.

    The ``mv`` stub reports success without moving anything — the effect the
    backstop exists for.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_tool(bindir, "ffmpeg",
               'for a in "$@"; do last=$a; done\nprintf mp4 > "$last"\n')
    _stub_tool(bindir, "mv", 'exit 0\n')
    (bindir / "rm").symlink_to("/bin/rm")
    env = {"CAPDIR": str(capdir), "PATH": str(bindir)}
    r = subprocess.run(["/bin/bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        "a publish that left no mp4 was reported as success, and the step "
        "then deleted the webm — the only copy of the recording")
    assert "the published mp4 is not there" in r.stderr, r.stderr
    assert "ffmpeg failed" not in r.stderr, (
        "a publish that left nothing is reported as an encoder failure: "
        + r.stderr)
    assert not (capdir / "recording.mp4").exists()
    assert (capdir / "recording.webm").exists(), (
        "the finalize dropped the webm although it published no mp4")


def test_web_ui_transcode_that_writes_nothing_leaves_no_mp4(tmp_path):
    """A renderer that reports success and writes nothing leaves no output.

    The exit status proves the encode ran; ``test -s`` catches the renderer
    that claims success and writes nothing (R12). Verified: that branch
    exited 1 but left a **0-byte** ``recording.mp4`` in the capture directory,
    which the manifest's ``## Files`` section could then list as this run's
    video — the recording recipes' ``render_fail`` removes the output for
    exactly this reason, so the two finalize paths disagreed. The webm stays,
    because a failed transcode is retried from it. Since the encode publishes
    through ``recording.mp4.partial.mp4`` (R66), the empty file the branch
    has to remove is the *partial*: ``recording.mp4`` is not a name any
    failure path writes, so asserting only that one cannot see the empty
    output the branch exists to drop.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
    (capdir / "recording.webm").write_bytes(b"webm")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_tool(bindir, "ffmpeg",
               'for a in "$@"; do last=$a; done\n: > "$last"\n')
    env = dict(os.environ, CAPDIR=str(capdir),
               PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        "a transcode that wrote an empty mp4 was reported as success")
    assert "ffmpeg wrote nothing" in r.stderr, r.stderr
    assert not (capdir / "recording.mp4").exists(), (
        "the transcode failure left an empty mp4, which the manifest could "
        "present as this run's video")
    assert not (capdir / "recording.mp4.partial.mp4").exists(), (
        "the transcode failure left an empty partial mp4, which the "
        "produced-files list explains only as an interrupted encode's "
        "output")
    assert (capdir / "recording.webm").exists(), (
        "the finalize step dropped the webm, so a failed transcode cannot be "
        "retried without re-driving the UI")


def _web_ui_capdir(tmp_path):
    """The capture dir the stubbed step-1 block resolves for itself."""
    return tmp_path / "captures" / "scenarios" / "1" / "web-ui"


def _web_ui_teardown_block():
    text = _recipe_text("web-ui-recording.md")
    section = text.split("### Teardown", 1)[1].split("## Manifest", 1)[0]
    return re.findall(r"```[a-z]*\n(.*?)```", section, re.S)[0]


def test_web_ui_start_records_the_server_pid(tmp_path):
    """The app outlives step 1's shell, so the pid has to outlive it too.

    Every block in this recipe is pasted into a fresh shell and the app is
    backgrounded, so ``$SERVER_PID`` no longer exists when the teardown runs
    (verified: the teardown refused and the app kept holding the port). Step
    1 writes the pid beside the capture for the teardown to read.
    """
    r, _launched = _run_web_ui_start("ok", tmp_path)

    assert r.returncode == 0, r.stderr
    pidfile = _web_ui_capdir(tmp_path) / "server.pid"
    assert pidfile.exists(), (
        "step 1 never recorded the app's pid, so a fresh-shell teardown has "
        "no handle to stop")
    assert pidfile.read_text().strip().isdigit(), pidfile.read_text()


def test_web_ui_start_clears_a_previous_manifest(tmp_path):
    """Step 1 must not leave the previous run's manifest describing this run.

    The manifest is the document that says what the capture is (workdir, the
    app URL, ``## Files``). Seeded with the previous run's copy, a start step
    that does not clear it leaves the directory holding a manifest whose file
    list names the video, trace and logs this same step just deleted — the
    manifest-and-directory disagreement the produced-files rules exist to
    prevent, in the file that interprets the rest. ``driver.mjs`` is the one
    file the cleanup keeps on purpose: it is the run's input, not its
    evidence.
    """
    capdir = _web_ui_capdir(tmp_path)
    capdir.mkdir(parents=True)
    (capdir / "manifest.md").write_text("previous run's manifest\n")

    r, _launched = _run_web_ui_start("ok", tmp_path)

    assert r.returncode == 0, r.stderr
    assert not (capdir / "manifest.md").exists(), (
        "step 1 kept the previous run's manifest.md, so a run that fails "
        "before the worker writes a new one leaves a manifest describing the "
        "previous run and naming files this step deleted")


def test_web_ui_start_clears_a_stale_server_pid(tmp_path):
    """A stale pid would let the teardown signal whatever reused it."""
    capdir = _web_ui_capdir(tmp_path)
    capdir.mkdir(parents=True)
    (capdir / "server.pid").write_text("999999\n")

    r, _launched = _run_web_ui_start("ok", tmp_path)

    assert r.returncode == 0, r.stderr
    assert (capdir / "server.pid").read_text().strip() != "999999", (
        "step 1 kept a previous run's server.pid, so the teardown would "
        "signal a recycled pid")


def test_a_refused_start_clears_the_previous_pid(tmp_path):
    """The cleanup runs *before* the port pre-check, and the refusal relies on it.

    Step 1 clears the previous run's outputs before it probes the port, and
    the busy-port refusal says so: "Its pid is no longer in server.pid (this
    step cleared it)". The cleanup's *list* is pinned as text
    (``test_web_ui_clears_a_previous_video``), but nothing observed the
    refusal path — moving the whole ``rm`` below the pre-check left the file
    green (204 passed). A start refused for a busy port then leaves the
    previous run's ``server.pid`` in place: it is the handle the recipe's
    teardown reads, so a worker who runs the teardown next signals whatever
    process has since reused that pid — while the message that sent them there
    says the file is gone. The success path cannot see this: its own
    ``printf`` overwrites the pid.
    """
    capdir = _web_ui_capdir(tmp_path)
    capdir.mkdir(parents=True)
    (capdir / "server.pid").write_text("999999\n")

    r, launched = _run_web_ui_start("inuse", tmp_path)

    assert r.returncode != 0, r.stderr
    assert "already answers" in r.stderr, r.stderr
    assert not launched.exists(), (
        "the recipe started the app on a port another server holds")
    assert not (capdir / "server.pid").exists(), (
        "the refused start left the previous run's server.pid in place, so "
        "the teardown can signal a recycled pid although the refusal message "
        "says this step cleared it")


def test_web_ui_teardown_uses_the_pid_step_one_recorded(tmp_path):
    """The teardown has to stop *this* run's app from a fresh shell.

    Verified: pasted into a fresh shell the block refused with "SERVER_PID is
    unset — run the teardown in the shell that started the app", and the app
    kept holding the port — while re-running step 1 is not a remedy, because
    that app answers the port pre-check the block itself added. The pid step 1
    records is the handle that survives the shell boundary.
    """
    app = subprocess.Popen(["sleep", "300"])
    try:
        capdir = tmp_path / "cap"
        capdir.mkdir()
        (capdir / "server.pid").write_text(f"{app.pid}\n")
        env = {k: v for k, v in os.environ.items() if k != "SERVER_PID"}
        env["CAPDIR"] = str(capdir)

        r = subprocess.run(["bash"], input=_web_ui_teardown_block(), env=env,
                           capture_output=True, text=True, timeout=30)

        assert r.returncode == 0, r.stderr
        app.wait(timeout=10)   # TimeoutExpired == the app is still running
        assert not (capdir / "server.pid").exists(), (
            "the teardown left the pid file behind, so a second run would "
            "signal a recycled pid")
    finally:
        if app.poll() is None:
            app.kill()
            app.wait()


def test_web_ui_teardown_refuses_an_unset_server_pid(tmp_path):
    """`kill ""` is a silent no-op, so the app keeps holding the port.

    With neither ``SERVER_PID`` nor a recorded pid the teardown must stop with
    that reason: ``kill "" 2>/dev/null || true`` does nothing at all, the app
    keeps running and holding the port, and the next run's port pre-check
    refuses with "something already answers" — a failure the worker cannot
    connect to its own missed teardown. Same rule as the finalize and driver
    blocks: a step that cannot do its job says so. With no ``CAPDIR`` there is
    no pid file to read either, so the block stops before aiming a path at the
    filesystem root.
    """
    block = _web_ui_teardown_block()
    capdir = tmp_path / "cap"
    capdir.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "SERVER_PID"}
    env["CAPDIR"] = str(capdir)

    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        "the teardown ran with no SERVER_PID and silently did nothing")
    assert "SERVER_PID" in r.stderr, r.stderr

    env.pop("CAPDIR")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)

    assert r.returncode != 0, (
        "the teardown ran with no CAPDIR, so it read a pid file at the root")
    assert "CAPDIR" in r.stderr, r.stderr


def _run_in_interactive_shell(block, env, cwd=None):
    """Feed ``block`` to an interactive bash on a pty (``script``).

    The pty transcript is decoded leniently: readline redraws the line as the
    block arrives, and a redraw can interleave a control sequence inside a
    multi-byte character (the recipe text is full of em dashes), which strict
    UTF-8 decoding rejects. That is an artifact of the pty echo, not of the
    block — the assertions below only look for ASCII words and file effects —
    so a decode error must not fail the run.
    """
    if shutil.which("script") is None:
        pytest.skip("script(1) is required")
    return subprocess.run(["script", "-qec", "bash", "/dev/null"],
                          input=block, env=env, cwd=cwd,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def test_web_ui_finalize_guard_stops_an_interactive_paste(tmp_path):
    """`${VAR:?}` aborts only its own command in an interactive shell.

    Verified in a real interactive bash: `: "${CAPDIR:?…}"` prints the error
    and *the next line still runs*, so the `rm -f "$CAPDIR/recording.mp4"`
    below it aimed at `/recording.mp4`. The guard only stopped a scripted
    run, not the paste-into-a-shell form the recipe is written for. The block
    therefore has to stop itself (`if … exit 1`), which is what this drives.
    """
    block = _web_ui_finalize_block()

    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "ffmpeg-called"
    _stub_tool(bindir, "ffmpeg", f'touch "{called}"\n')
    env = {k: v for k, v in os.environ.items() if k != "CAPDIR"}
    env["PATH"] = f"{bindir}:{os.environ['PATH']}"

    r = _run_in_interactive_shell(block, env)

    assert "CAPDIR" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert not called.exists(), (
        "an interactive paste ran ffmpeg with an unset CAPDIR: the `:?` guard "
        "aborted its own command but the next line still ran")


def test_web_ui_driver_guard_stops_an_interactive_paste(tmp_path):
    """Same interactive-shell hole in the driver block's guard.

    With `CAPDIR` unset, an interactive paste that carries on past the guard
    reaches `cd ""` (which succeeds and stays put) and the conditional link,
    creating ``node_modules`` in the worker's cwd — the filesystem side effect
    the guard exists to prevent.
    """
    block = _web_ui_driver_block().replace("/usr/lib/node_modules",
                                           str(_fake_playwright(tmp_path / "global")))
    work = tmp_path / "cwd"
    work.mkdir()
    # The worker's own directory holds a `driver.mjs` (the recipe's own
    # misdiagnosis for this case is "saved in the workdir instead of the
    # capture directory"), so the block's `[ -f driver.mjs ]` check cannot
    # stop it before the link. Without the file the check would fire first and
    # the `node_modules` assertion below could not fail even with the guard
    # removed — it would be proving the missing-driver check, not the guard.
    _write_driver(work)
    env = {k: v for k, v in os.environ.items()
           if k not in ("CAPDIR", "APP_URL")}

    r = _run_in_interactive_shell(block, env, cwd=work)

    assert "CAPDIR" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert not os.path.lexists(work / "node_modules"), (
        "an interactive paste linked node_modules into the worker's cwd")


def _web_ui_driver_block():
    """The fenced block that runs ``driver.mjs``."""
    text = _recipe_text("web-ui-recording.md")
    for block in re.findall(r"```bash\n(.*?)```", text, re.S):
        if "node driver.mjs" in block:
            return block
    raise AssertionError("web-ui recipe has no block that runs driver.mjs")


def _fake_playwright(root):
    """A fake global Playwright install rooted at ``root`` (``root/playwright``)."""
    pkg = root / "playwright"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(
        '{"name": "playwright", "type": "module", "exports": "./index.js"}\n')
    (pkg / "index.js").write_text("export const chromium = {stub: true};\n")
    return root


def _write_driver(capdir):
    (capdir / "driver.mjs").write_text(
        'import { chromium } from "playwright";\n'
        'console.log("driver saw", typeof chromium);\n')


def _run_driver_block(capdir, global_dir, app_url="http://localhost:1"):
    """Run the recipe's own driver block against a fake Playwright install.

    ``app_url=None`` leaves ``APP_URL`` unset, the way a fresh shell has it.
    """
    block = _web_ui_driver_block().replace("/usr/lib/node_modules",
                                           str(global_dir))
    env = dict(os.environ, CAPDIR=str(capdir), APP_URL=app_url)
    if app_url is None:
        env.pop("APP_URL")
    return subprocess.run(["bash"], input=block, env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_block_refuses_an_unset_capdir(tmp_path):
    """``cd ""`` silently stays put, so the link lands in the worker's cwd.

    Verified: with ``CAPDIR`` unset, ``cd "$CAPDIR"`` returns 0 and leaves the
    shell where it was, so the block creates ``node_modules`` — a link to the
    image's global install — in that directory (the PR workdir, say), the
    resolution check then passes on that stray link, and the driver fails
    with a bare "Cannot find module …/driver.mjs". The finalize step refuses
    an unset ``CAPDIR`` for the same reason; the driver block has to as well.
    """
    global_dir = _fake_playwright(tmp_path / "global")
    block = _web_ui_driver_block().replace("/usr/lib/node_modules",
                                           str(global_dir))
    work = tmp_path / "cwd"
    work.mkdir()
    # A `driver.mjs` in the worker's own directory, as above: without it the
    # block's `[ -f driver.mjs ]` check stops it before the link, and the
    # `node_modules` assertion below would pass even with the CAPDIR guard
    # removed.
    _write_driver(work)
    env = {k: v for k, v in os.environ.items()
           if k not in ("CAPDIR", "APP_URL")}
    r = subprocess.run(["bash"], input=block, env=env, cwd=work,
                       capture_output=True, text=True, timeout=120)

    assert r.returncode != 0, "the driver block ran with no CAPDIR"
    assert "CAPDIR" in r.stderr, r.stderr
    assert "playwright ok" not in r.stdout, (
        "the block passed its resolution check on a link it created in the "
        "wrong directory: " + r.stdout)
    assert not os.path.lexists(work / "node_modules"), (
        "the block created a node_modules link in the worker's cwd")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_block_refuses_a_missing_capture_dir(tmp_path):
    """A set-but-missing ``CAPDIR`` is the same hole as an unset one.

    ``cd "$CAPDIR"`` fails and the shell stays in the worker's cwd, so the
    link and the resolution check run *there* and pass, and the driver then
    dies with a bare "Cannot find module …/driver.mjs". Verified: with
    ``CAPDIR`` pointing at a path that does not exist, the previous block
    created ``node_modules`` in the cwd and printed "playwright ok". The
    block has to stop on the directory it cannot enter.
    """
    global_dir = _fake_playwright(tmp_path / "global")
    block = _web_ui_driver_block().replace("/usr/lib/node_modules",
                                           str(global_dir))
    work = tmp_path / "cwd"
    work.mkdir()
    env = dict(os.environ, CAPDIR=str(tmp_path / "missing-cap"),
               APP_URL="http://localhost:1")
    r = subprocess.run(["bash"], input=block, env=env, cwd=work,
                       capture_output=True, text=True, timeout=120)

    assert r.returncode != 0, (
        "the driver block ran with a capture directory that does not exist")
    assert "does not exist" in r.stderr, r.stderr
    assert "playwright ok" not in r.stdout, (
        "the block passed its resolution check on a link it created in the "
        "worker's cwd: " + r.stdout)
    assert not os.path.lexists(work / "node_modules"), (
        "the block created a node_modules link in the worker's cwd")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
@UNWRITABLE_MODES
def test_web_ui_driver_block_refuses_a_capture_dir_it_cannot_write(tmp_path,
                                                                   capdir_mode):
    """An unwritable capture directory is reported as Playwright not resolving.

    The directory exists, so the block's ``cd`` succeeds and the link is
    attempted: ``ln`` answers "Permission denied", the resolution check then
    reports "playwright does not resolve beside driver.mjs" and tells the
    worker to run that same link again — a remedy that cannot work, the shape
    R31/R32 fixed for the ``agg`` install and the nested ``node_modules`` —
    while the driver's own outputs have nowhere to go. Verified live with a
    mode-500 capture directory: the pre-fix block exits 1 with the Playwright
    message and ``ln``'s "Permission denied" above it.

    Mode 600 (write bit, no search bit) is the shape only the guard's
    ``-x`` half can see: the ``cd`` into it fails too, so without that half
    the block reports the directory as "could not be entered — it may have
    been removed" instead of naming the permission problem.
    """
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        pytest.skip("root bypasses the directory permission bits")
    global_dir = _fake_playwright(tmp_path / "global")
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    capdir.chmod(capdir_mode)
    try:
        r = _run_driver_block(capdir, global_dir)
    finally:
        capdir.chmod(0o700)

    assert r.returncode != 0, (
        "the driver block ran into a capture directory nothing can be "
        "written into")
    assert "cannot be written" in r.stderr, r.stderr
    assert "playwright does not resolve" not in r.stderr, (
        "an unwritable capture directory is reported as Playwright not "
        "resolving, with a link command that fails the same way: " + r.stderr)
    assert "playwright ok" not in r.stdout, (
        "the block passed its resolution check although it could not link: "
        + r.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_block_refuses_a_capture_dir_it_cannot_enter(tmp_path):
    """A directory that cannot be entered is not a directory that is missing.

    The block's existence and permission checks used to sit *after* its
    ``cd``, so a capture directory that exists and cannot be searched (mode
    400, say) failed the ``cd`` and was reported as "does not exist — create
    it and run step 1": the worker is sent to create a directory that is
    already there and to re-run the step that created it, with bash's own
    "Permission denied" as the only clue. Verified live: pre-fix the block
    exits 1 with that message for a mode-400 directory, while the finalize
    and Layer 2 blocks — which never ``cd`` — name the same directory
    "cannot be written". Both checks now run before the ``cd``, so an
    existing directory is always named as the directory it is.
    """
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        pytest.skip("root can enter a mode-400 directory")
    global_dir = _fake_playwright(tmp_path / "global")
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    capdir.chmod(0o400)
    try:
        r = _run_driver_block(capdir, global_dir)
    finally:
        capdir.chmod(0o700)

    assert r.returncode != 0, (
        "the driver block ran into a capture directory it cannot enter")
    assert "cannot be written" in r.stderr, (
        "a capture directory that exists but cannot be entered is not named "
        "as the directory it is: " + r.stderr)
    assert "does not exist" not in r.stderr, (
        "an existing capture directory is reported as missing, so the worker "
        "is sent to create a directory that is there and re-run the step "
        "that created it: " + r.stderr)
    assert "playwright ok" not in r.stdout, (
        "the block passed its resolution check in a directory it cannot "
        "enter: " + r.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_block_refuses_an_unset_app_url(tmp_path):
    """An unset APP_URL is not "the default app" — the driver has a fallback.

    ``driver.mjs`` reads ``process.env.APP_URL || 'http://localhost:8000'``,
    so with ``CAPDIR`` exported but ``APP_URL`` missing the block links,
    resolves, and drives whatever answers on port 8000: a capture of another
    app presented as this run's evidence — the same "the wait matched the
    wrong handle" class as the busy-port pre-check in step 1. The guard names
    both variables for that reason.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    r = _run_driver_block(capdir, _fake_playwright(tmp_path / "global"),
                          app_url=None)
    assert r.returncode != 0, (
        "the driver block ran with no APP_URL, so the driver fell back to "
        "http://localhost:8000")
    assert "APP_URL" in r.stderr, r.stderr
    assert "driver saw" not in r.stdout, (
        "the block ran the driver with no APP_URL: " + r.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_resolves_playwright_beside_it(tmp_path):
    """The driver is an ES module, and ESM ignores the image's ``NODE_PATH``.

    The QA image installs Playwright globally under ``/usr/lib/node_modules``
    and exports ``NODE_PATH`` for it, but Node's *ES module* resolver ignores
    ``NODE_PATH``: the recipe's ``driver.mjs`` (``import { chromium } from
    'playwright'``) fails at startup with ``ERR_MODULE_NOT_FOUND: Cannot find
    package 'playwright'`` (verified in the QA image), so a worker that
    follows the recipe gets no capture at all. A ``node_modules`` beside the
    driver resolves the package, so the run block has to create one before
    running the driver.
    """
    text = _recipe_text("web-ui-recording.md")
    tooling = text.split("## Tooling", 1)[1].split(
        "## What this recipe produces", 1)[0]
    assert "ERR_MODULE_NOT_FOUND" in text, (
        "web-ui recipe does not name the ESM resolution failure a worker hits")
    assert "NODE_PATH" in tooling, (
        "web-ui recipe does not explain why the image's global Playwright "
        "does not resolve for an ES module")
    block = _web_ui_driver_block()
    link = block.find("ln -sfn")
    assert link != -1 and "node_modules" in block[link:link + 60], (
        "web-ui recipe runs driver.mjs without a node_modules beside it")
    assert link < block.index('APP_URL="$APP_URL" node driver.mjs'), (
        "web-ui recipe links node_modules only after running the driver")

    # Drive the block the way a worker does: a fake "global" Playwright
    # install (a sibling of the link target), a driver that imports it, and
    # the recipe's own link + run lines. The import only resolves through the
    # link, so a regression here fails the driver exactly as the image does.
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    r = _run_driver_block(capdir, _fake_playwright(tmp_path / "global"))
    assert r.returncode == 0, f"{block}\n{r.stderr}"
    assert "playwright ok" in r.stdout, (
        "web-ui recipe's resolution check does not run: " + r.stdout + r.stderr)
    assert "driver saw object" in r.stdout, (
        "web-ui recipe runs driver.mjs without a resolvable playwright: "
        + r.stdout + r.stderr)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_does_not_clobber_a_local_install(tmp_path):
    """The recipe offers the image's global install *or* a local one.

    The link has to be conditional. With ``node_modules`` already a real
    directory (a worker ran ``npm i playwright`` as the recipe's "elsewhere"
    line says), an unconditional ``ln -sfn /usr/lib/node_modules
    node_modules`` creates ``node_modules/node_modules`` — junk in the capture
    directory, and with no global install a dangling link *inside* the
    worker's own install. With no install at all it leaves a dangling
    ``node_modules`` beside the driver, which then breaks that same
    ``npm i playwright`` fallback.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    _fake_playwright(capdir / "node_modules")   # the worker's local install
    r = _run_driver_block(capdir, tmp_path / "no-global-install")
    assert r.returncode == 0, r.stderr
    assert "driver saw object" in r.stdout, (
        "web-ui recipe breaks a local Playwright install: " + r.stdout + r.stderr)
    entries = sorted(p.name for p in (capdir / "node_modules").iterdir())
    assert entries == ["playwright"], (
        "web-ui recipe linked the global install *inside* the worker's local "
        f"node_modules ({entries})")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_links_only_when_playwright_is_there(tmp_path):
    """A global ``node_modules`` without the package must not become the link.

    The image's layout is ``/usr/lib/node_modules/playwright``. Testing only
    the parent directory links a directory that cannot resolve the package: the
    block then stops at its own check and tells the worker to create that same
    link again (a remedy that cannot work), and the stray ``node_modules``
    makes a later ``npm i playwright`` install into the global directory
    instead of the capture directory.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    global_dir = tmp_path / "global"
    global_dir.mkdir()      # the directory exists; the playwright package does not
    r = _run_driver_block(capdir, global_dir)
    assert r.returncode != 0, (
        "the block ran the driver without a resolvable playwright")
    assert "playwright does not resolve beside driver.mjs" in r.stderr, r.stderr
    # The link is only a remedy when the global install holds the package;
    # offering it unconditionally (as the block used to) sends a worker on a
    # host without one to a fix that cannot work.
    assert f"{global_dir}/playwright exists" in r.stderr, (
        "the resolution failure presents the global link as the fix without "
        "checking that it holds playwright, so a worker without a global "
        "install is sent to a remedy that cannot work: " + r.stderr)
    assert "npm i playwright" in r.stderr, (
        "the resolution failure names no remedy that works without a global "
        "install: " + r.stderr)
    assert not os.path.lexists(capdir / "node_modules"), (
        "the block linked a global node_modules that does not hold playwright, "
        "so the remedy it prints cannot work and a later `npm i playwright` "
        "lands in the global install")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_stops_when_playwright_does_not_resolve(tmp_path):
    """The resolution check has to gate the driver, not just print.

    Without the gate the worker sees the same ``ERR_MODULE_NOT_FOUND`` twice
    (once from the check, once from the driver) and no statement of what to
    do; and with no global install an unconditional link would leave a
    dangling ``node_modules`` in the capture directory. The step is pasted on
    its own when a driver is retried, so the earlier attempt's outputs have to
    go even on *this* failure path — otherwise the finalize step can transcode
    the previous attempt's complete webm into "this run's" recording.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    stale = {"recording.webm": "an earlier attempt\n", "trace.zip": "trace\n"}
    for name, content in stale.items():
        (capdir / name).write_text(content)
    r = _run_driver_block(capdir, tmp_path / "missing-global-install")
    assert r.returncode != 0, (
        "the recipe ran driver.mjs although its own resolution check failed")
    assert "playwright does not resolve beside driver.mjs" in r.stderr, (
        "the resolution failure has no actionable message: " + r.stderr)
    assert "driver saw" not in r.stdout, (
        "the recipe ran the driver after its resolution check failed")
    assert not os.path.lexists(capdir / "node_modules"), (
        "web-ui recipe left a dangling node_modules beside the driver")
    for name in stale:
        assert not (capdir / name).exists(), (
            f"the resolution failure left an earlier attempt's {name} for the "
            "finalize step to present as this run's evidence")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
@pytest.mark.parametrize("driver_shape", ["absent", "empty"],
                         ids=["no-file", "0-byte-file"])
def test_web_ui_driver_block_refuses_a_missing_driver(tmp_path, driver_shape):
    """A driver that was never saved is not a driver that ran and failed.

    Step 2's prose says to save the skeleton as ``driver.mjs`` in the capture
    directory, and the block then runs ``node driver.mjs``. Without the file
    Node answers ``Cannot find module …/driver.mjs`` (exit 1, verified) and the
    run-failure message below calls that "the driver failed — this run's
    video, trace and screenshots are incomplete", so the worker debugs a
    driver that is simply absent (or was saved in the workdir instead of the
    capture directory). That is the same misdiagnosis as reporting a missing
    webm as an encoder failure. The block names the missing input instead.

    Both shapes of "there is nothing to run" are exercised, because they take
    different paths through the check: no file at all, and the **0-byte**
    ``driver.mjs`` a failed save leaves behind. Only the first was modelled,
    so ``-f`` passed the second — and an empty file is a *valid* ES module:
    ``node driver.mjs`` exits 0 having run nothing (verified), the block
    reports success, and the finalize step then says "the driver wrote no
    video; re-run step 2 and check the driver's recordVideo option" — a
    remedy that cannot work, because step 2 passes again. The check is ``-s``
    for that reason, the rule every stage-input check in the recording
    recipes' render blocks follows (an artifact that exists but is empty is
    not an input).

    The check also has to sit *after* the block's attempt cleanup, because a
    retry pasted with the driver saved in the workdir is a step-2 failure path
    like any other and R21 requires every one of them to leave no earlier
    attempt's artifact. Moving the check above the ``rm`` left the whole file
    green (247 passed) and the earlier attempt's complete
    ``recording.mp4``/``recording.webm``/trace/screenshots/manifest in place —
    the recording the finalize step would then present as this run's, and a
    manifest naming the files that were supposed to be gone (verified live
    with the recipe's own block: pre-fix rc 1 with all eight files still in
    the capture directory, post-fix the directory holds nothing).
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()                    # no driver.mjs was saved
    if driver_shape == "empty":
        (capdir / "driver.mjs").write_text("")
    stale = {"recording.mp4": "an earlier attempt's video\n",
             "recording.webm": "an earlier attempt\n",
             "page@0123456789abcdef.webm": "an earlier auto-named video\n",
             "trace.zip": "an earlier trace\n",
             "dom.html": "<html>an earlier dump</html>\n",
             "01-loaded.png": "an earlier screenshot\n",
             "http.log": "an earlier protocol snapshot\n",
             "sse.log": "data: an earlier attempt\n",
             "manifest.md": "## Files\n- `recording.mp4` — an earlier attempt\n"}
    for name, content in stale.items():
        (capdir / name).write_text(content)
    r = _run_driver_block(capdir, _fake_playwright(tmp_path / "global"))
    assert r.returncode != 0, (
        "the block ran with no driver.mjs to run"
        if driver_shape == "absent" else
        "an empty driver.mjs is a valid ES module, so `node` exits 0 having "
        "run nothing and the block reports success: " + r.stdout)
    assert "there is no driver.mjs" in r.stderr, (
        "a missing driver.mjs is not named: " + r.stderr)
    assert "the driver failed" not in r.stderr, (
        "a missing driver.mjs is reported as a driver that ran and failed, "
        "so the worker debugs a file that does not exist: " + r.stderr)
    assert "driver saw" not in r.stdout, r.stdout
    for name in stale:
        assert not (capdir / name).exists(), (
            f"the block refused a missing driver.mjs but left an earlier "
            f"attempt's {name} behind, so a later finalize presents the "
            "earlier attempt's recording as this run's")


def test_web_ui_driver_block_names_a_missing_node(tmp_path):
    """Without ``node`` the block blames Playwright and offers dead remedies.

    The block's only tools are ``node`` and (when it links) ``ln``. Verified
    with a PATH that has no ``node``: the import check failed and the block
    printed "playwright does not resolve beside driver.mjs", offering the
    global link and ``npm i playwright`` — both of which need the runtime that
    is missing, so the worker repeats a remedy that cannot work (the shape
    R31/R32 fixed for the ``agg`` install and the nested ``node_modules``).
    It also created the ``node_modules`` link on the way. A missing
    prerequisite has to be named where it is missing, and nothing should be
    created for a run that cannot happen.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    # A PATH with the shell and the block's other external tools, but no node.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in ("bash", "rm", "ln", "cat", "sleep"):
        src = shutil.which(tool)
        if src:
            (bindir / tool).symlink_to(src)
    env = {"PATH": str(bindir), "CAPDIR": str(capdir),
           "APP_URL": "http://localhost:1", "HOME": str(tmp_path)}

    r = subprocess.run(["bash"], input=_web_ui_driver_block(), env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, (
        "the driver block reported success with no node to run the driver")
    assert "node is not installed" in r.stderr, (
        "a missing node is not named: " + r.stderr)
    assert "playwright does not resolve" not in r.stderr, (
        "a missing node is reported as a Playwright resolution failure, and "
        "every remedy that message offers needs node: " + r.stderr)
    assert not os.path.lexists(capdir / "node_modules"), (
        "the block linked node_modules for a run that cannot happen")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_remedy_handles_an_existing_node_modules(tmp_path):
    """The offered link must work when a broken ``node_modules`` is in the way.

    The link is guarded on ``[ ! -e node_modules ]`` (a local install must not
    be clobbered), so a *partial* ``npm i playwright`` — a ``node_modules``
    that does not hold the package — is left alone and the resolution check
    fails. The failure then offered ``ln -sfn … node_modules``, which creates
    ``node_modules/node_modules`` and still answers ``ERR_MODULE_NOT_FOUND``
    (verified): a remedy that cannot work, in the same block R17 fixed for the
    no-global-install case. The message has to say to remove it first.
    """
    global_dir = _fake_playwright(tmp_path / "global")
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    (capdir / "node_modules").mkdir()      # a partial install: no playwright
    block = _web_ui_driver_block().replace("/usr/lib/node_modules",
                                           str(global_dir))
    env = dict(os.environ, CAPDIR=str(capdir), APP_URL="http://localhost:1")

    r = subprocess.run(["bash"], input=block, env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode != 0, (
        "the block ran the driver on a node_modules that cannot resolve it")
    assert "playwright does not resolve beside driver.mjs" in r.stderr, r.stderr
    assert "rm -rf node_modules" in r.stderr, (
        "the failure offers a link that nests inside the existing "
        "node_modules, so repeating it cannot resolve: " + r.stderr)
    assert "driver saw" not in r.stdout, r.stdout

    # The remedy the message names has to work. Remove the broken install, take
    # the link the guard would have created, and re-run the block.
    subprocess.run(["rm", "-rf", str(capdir / "node_modules")], check=True)
    os.symlink(str(global_dir), capdir / "node_modules")
    r = subprocess.run(["bash"], input=block, env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.returncode == 0, (
        "the remedy the message names does not resolve Playwright: "
        + r.stdout + r.stderr)
    assert "driver saw object" in r.stdout, r.stdout + r.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required")
def test_web_ui_driver_failure_is_reported_and_clears_stale_outputs(tmp_path):
    """A failed driver must name itself and leave no earlier attempt's video.

    Step 2 is pasted on its own whenever a driver is adapted and retried, so
    the *previous* attempt's outputs are still in the capture directory. The
    block used to end on ``node driver.mjs`` with no check: a retry that
    failed part-way left the earlier attempt's complete webm in place, and the
    finalize step transcoded it into "this run's" recording — a successful
    transcode of an incomplete run. Without a stale webm the failure surfaced
    one block later as "ffmpeg failed on the driver's webm", which sends the
    worker to the encoder instead of the driver. The earlier attempt's
    ``recording.mp4`` goes too: an attempt that already reached the finalize
    step leaves the primary artifact, and a retry that fails would otherwise
    end with that video as the only recording the manifest can present as
    this run's (the finalize step clears it only when it runs).

    The manifest goes with them, for the reason step 1 clears it (R47): it is
    the document that says what this capture is, and an attempt that already
    reached the finalize step leaves one whose ``## Files`` names the
    ``recording.mp4`` this cleanup just deleted. A retry that then fails ends
    with a manifest describing files that are gone — the manifest and the
    directory disagreeing, in the one file a reviewer reads to interpret the
    rest. Verified with the recipe's own block and a driver that throws: the
    pre-fix block exits 1 leaving only ``driver.mjs``, ``node_modules`` and
    the earlier attempt's manifest, whose ``## Files`` names the deleted mp4;
    with the manifest in the cleanup the directory holds only the input and
    the link.

    The Layer 2 protocol logs go too (R53): an attempt that already ran the
    protocol layer leaves ``http.log``/``sse.log``, which the manifest's
    ``## Files`` names as this capture's evidence. A retry drives the UI
    again, and the protocol layer is *supplementary* — a worker may not
    re-run it — so without this clear the retried capture presents the
    earlier attempt's route snapshots and event stream as this run's. Step 1
    clears them for a fresh run for exactly that reason (R18); this covers
    the step-2-only retry the block exists for.

    Playwright's auto-named ``page@<hash>.webm`` is in the set too, for the
    reason step 1 globs ``*.webm`` rather than ``recording.webm``: a driver
    killed before the rename leaves that name instead, and it is a valid,
    playable partial recording. Narrowing this block's ``./*.webm`` glob to
    ``./recording.webm`` left the whole file green (247 passed) while the
    earlier attempt's auto-named video survived the failed retry.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    stale = {"recording.mp4": "an earlier attempt's video\n",
             "recording.webm": "an earlier attempt\n",
             # Playwright's auto-named video: the driver renames it onto
             # recording.webm only after a complete walk-through, so a killed
             # driver leaves this name instead. Narrowing the cleanup's
             # `./*.webm` glob to `./recording.webm` left the whole file green
             # (247 passed) and kept this file — a valid, playable partial
             # recording (verified live: ffprobe reports a duration for a
             # SIGKILLed driver's page@<hash>.webm) — for the retried capture
             # to present as its own.
             "page@0123456789abcdef.webm": "an earlier attempt's auto-named video\n",
             "trace.zip": "an earlier trace\n",
             "dom.html": "<html>an earlier dump</html>\n",
             "01-loaded.png": "an earlier screenshot\n",
             "http.log": "===== GET / =====\nan earlier attempt\n",
             "sse.log": "data: an earlier attempt\n",
             "manifest.md": "## Files\n- `recording.mp4` — the walk-through\n"}
    for name, content in stale.items():
        (capdir / name).write_text(content)
    # The driver resolves Playwright, then fails the way a bad locator does.
    (capdir / "driver.mjs").write_text(
        'import { chromium } from "playwright";\n'
        'console.log("driver saw", typeof chromium);\n'
        'throw new Error("locator timeout");\n')
    r = _run_driver_block(capdir, _fake_playwright(tmp_path / "global"))

    assert r.returncode != 0, "a failed driver was reported as a success"
    assert "the driver failed" in r.stderr, (
        "the driver's failure has no message of its own, so it surfaces later "
        "as an ffmpeg error: " + r.stderr)
    for name in stale:
        assert not (capdir / name).exists(), (
            f"the driver block left an earlier attempt's {name} in place, so "
            "a retry that fails presents the earlier attempt's evidence as "
            "this run's")


_STUB_CURL = r"""
n=$(cat "$STUB_CURL_COUNT" 2>/dev/null || echo 0)
n=$((n + 1)); echo "$n" > "$STUB_CURL_COUNT"
# The argv of each call, so a case can see the bounds the block passes. The
# stub answers with exit codes only: it cannot show that a call *would* hang
# without its deadline, and the pre-check's `--max-time` is what makes curl
# answer 28 for a listener that never replies.
[ -n "${STUB_CURL_LOG:-}" ] && printf '%s\n' "$*" >> "$STUB_CURL_LOG"
case "$STUB_MODE" in
  inuse) exit 0 ;;
  # `inuse404`: a previous run's app still holds the port and answers 404 at
  # "/" (an app whose UI lives at a subpath). *Any* HTTP answer means the port
  # is taken, which is why the pre-check uses plain `curl`: with `-f` this
  # call exits 22 instead, and the block reports "could not check … exit 22"
  # — a cause the port cannot have, for a server that plainly answered (the
  # shape R23 fixed for the readiness poll, one call earlier).
  inuse404)
      case " $* " in *" -f "*|*" -sf "*|*" -fs "*) exit 22 ;; esac
      exit 0 ;;
  never) exit 7 ;;
  # `hung`: something accepts the connection and never answers, so curl exits
  # 28 (its own timeout) on every call — the port pre-check's "not free" case
  # that is *not* an HTTP answer.
  hung) exit 28 ;;
esac
# Call 1 is the recipe's own "is the port free?" pre-check; the app answers
# from call 2 on.
[ "$n" -ge 2 ] || exit 7
# `http404`: the app is up but every route — "/" included — is a 404, so
# `curl -f` exits 22 while plain curl exits 0. Readiness has to mean "the
# server answers", the same definition the port pre-check uses.
if [ "$STUB_MODE" = http404 ]; then
    case " $* " in
      *" -f "*|*" -sf "*|*" -fs "*) exit 22 ;;
    esac
fi
exit 0
"""


def _web_ui_start_block():
    """The fenced block under ``### 1. Start the UI under test``."""
    text = _recipe_text("web-ui-recording.md")
    section = text.split("### 1. Start the UI under test", 1)[1].split(
        "### 2.", 1)[0]
    return re.findall(r"```bash\n(.*?)```", section, re.S)[0]


def _run_web_ui_start(mode, tmp_path, caps_is_file=False, pm_body=None,
                      mkdir_body=None, capdir_mode=None, app_body=None,
                      job_control=False):
    """Run the web-UI recipe's app-start block with stub pm/curl/my-app.

    ``caps_is_file`` makes the captures path itself a regular file, so the
    block's ``mkdir -p`` cannot create the capture directory. ``pm_body``
    replaces the stub ``pm`` (which otherwise prints the captures root);
    ``mkdir_body`` replaces the stub ``mkdir``, so a case can watch what the
    block tries to create without creating it. ``capdir_mode`` pre-creates the
    block's own capture directory with that mode, so a case can model one that
    exists and cannot be written (``mkdir -p`` answers 0 for it); the mode is
    restored before the run returns. ``app_body`` replaces the stub app (which
    otherwise touches ``app-launched`` and exits), for a case that needs the
    app to print or to stay up after the block returns. ``job_control``
    prepends ``set -m``, which reproduces the interactive paste the recipe is
    written for: with job control on, an asynchronous command inherits the
    shell's input instead of being handed ``/dev/null`` by bash (verified).
    """
    block = re.sub(r"\+\s*\d+\s*\)\)", "+ 2 ))", _web_ui_start_block())
    if job_control:
        block = "set -m\n" + block
    bindir = tmp_path / "bin"
    caps = tmp_path / "captures"
    bindir.mkdir(parents=True, exist_ok=True)
    if caps_is_file:
        caps.write_text("not a directory")
    else:
        caps.mkdir(parents=True, exist_ok=True)
    capdir = caps / "scenarios" / "1" / "web-ui"
    if capdir_mode is not None:
        capdir.mkdir(parents=True)
    launched = tmp_path / "app-launched"
    _stub_tool(bindir, "pm", pm_body or f'echo "{caps}"\n')
    if mkdir_body is not None:
        _stub_tool(bindir, "mkdir", mkdir_body)
    _stub_tool(bindir, "curl", _STUB_CURL)
    _stub_tool(bindir, "my-app", app_body or f'touch "{launched}"\n')
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               STUB_MODE=mode, STUB_CURL_COUNT=str(tmp_path / "curl-count"),
               STUB_CURL_LOG=str(tmp_path / "curl-log"))
    if capdir_mode is not None:
        capdir.chmod(capdir_mode)
    try:
        r = subprocess.run(["bash"], input=block, env=env,
                           capture_output=True, text=True, timeout=60)
    finally:
        if capdir_mode is not None:
            capdir.chmod(0o700)
    return r, launched


class TestWebUiStartExecution:
    """The app-start block: the port pre-check and the bounded readiness wait."""

    def test_start_block_completes(self, tmp_path):
        r, launched = _run_web_ui_start("ok", tmp_path)
        assert r.returncode == 0, r.stderr
        deadline = time.time() + 5
        while not launched.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert launched.exists(), "the recipe never launched the app"

    def test_a_port_already_answering_is_refused(self, tmp_path):
        """A server already on the port would satisfy the readiness wait.

        The app then never binds it, the poll passes against the *other*
        server, and the driver records that app while this run produced
        nothing — a capture of the wrong build presented as this run's
        evidence (the same "a wait matched the wrong handle" class as the
        pm-session poll). The recipe fails fast instead.
        """
        r, launched = _run_web_ui_start("inuse", tmp_path)
        assert r.returncode != 0, (
            "a port held by another server was accepted as this run's app")
        assert "already answers" in r.stderr, (
            "the recipe does not say why it refused the port: " + r.stderr)
        assert "ss -ltnp" in r.stderr and "server.pid" in r.stderr, (
            "the refusal points at a remedy that cannot work: the cleanup "
            "just deleted server.pid (so the teardown has no pid to read) "
            "and the answering server may not be this capture's, so the "
            "message has to name the manual pid hunt: " + r.stderr)
        assert not launched.exists(), (
            "the recipe started the app on a port another server holds")

    def test_a_port_that_answers_404_is_refused_as_taken(self, tmp_path):
        """Any HTTP answer means the port is taken, including a 404 at ``/``.

        The pre-check is plain ``curl`` on purpose (its own comment says so):
        an app whose UI lives at a subpath answers 404 at ``/`` and is
        perfectly alive, and the readiness poll below accepts exactly that
        shape (R23). With ``-f`` the pre-check exits 22 for it and the block
        takes its *other* failure branch — "could not check … (exit 22; …
        something may be listening without answering, the URL may be wrong,
        or curl may not be installed)" — a cause this port cannot have,
        because it answered. Verified live with real curl and a server that
        answers 404 at ``/``: plain curl exits 0, ``curl -f`` exits 22. The
        block still refuses either way, so the mutation left the whole file
        green (298 passed, verified); the refusal's *reason* is what is
        pinned here.
        """
        r, launched = _run_web_ui_start("inuse404", tmp_path)
        assert r.returncode != 0, (
            "a port held by a server that answers 404 at / was accepted as "
            "this run's app")
        assert "already answers" in r.stderr, (
            "the refusal does not name the cause: the port answered, so "
            "something is already there: " + r.stderr)
        assert "could not check" not in r.stderr, (
            "a port that answered 404 is reported as a failed check, whose "
            "remedies (wrong URL, missing curl, a listener that never "
            "answers) cannot apply: " + r.stderr)
        assert "ss -ltnp" in r.stderr, (
            "the refusal names no way to find the listener: " + r.stderr)
        assert not launched.exists(), (
            "the recipe started the app on a port another server holds")

    def test_a_port_that_accepts_but_never_answers_is_refused(self, tmp_path):
        """curl exit 28 is not a free port, and the app cannot bind it.

        The pre-check treated every curl failure as "free", but only
        "connection refused" (7) means that: a listener that accepts the
        connection and never answers times curl out (28), and a previous
        run's hung server would satisfy the readiness wait as soon as it did.
        Verified live with a socket that accepts and never replies: the
        pre-check passed, the app's own "Address already in use" was lost,
        and the block reported "app did not answer … check its startup
        output" after the full deadline and killed the app it had started —
        the misdiagnosis class the recipe removes elsewhere.
        """
        r, launched = _run_web_ui_start("hung", tmp_path)
        assert r.returncode != 0, (
            "a port that accepts and never answers was treated as free")
        assert "could not check" in r.stderr, (
            "the refusal does not name the check that failed: " + r.stderr)
        assert "exit 28" in r.stderr, (
            "the refusal does not say how curl failed: " + r.stderr)
        assert "ss -ltnp" in r.stderr, (
            "the refusal names no way to find the listener: " + r.stderr)
        assert not launched.exists(), (
            "the recipe started the app on a port it could not bind, so the "
            "failure surfaces later as 'app did not answer'")

    def test_a_server_that_never_answers_fails_at_the_deadline(self, tmp_path):
        r, launched = _run_web_ui_start("never", tmp_path)
        assert r.returncode != 0, (
            "a server that never answers was reported as started")
        assert "did not answer" in r.stderr, r.stderr
        # The message points the worker at the app's startup output, so that
        # output has to be a file the worker can read.
        assert "app.log" in r.stderr, (
            "the readiness failure does not name the app's startup log: "
            + r.stderr)
        assert (_web_ui_capdir(tmp_path) / "app.log").exists(), (
            "the readiness failure names app.log but the app's output was "
            "not written there")

    def test_web_ui_start_does_not_wait_for_the_app(self, tmp_path):
        """The block must return while the app it started is still running.

        The app outlives step 1's shell on purpose, so a block that hands it
        the shell's stdout/stderr only reaches EOF when the app exits — and
        the app is stopped by the *teardown*, a later paste. A worker
        capturing the step (``bash < block | tee …``, or any harness that
        reads the block's output through a pipe) therefore blocks inside
        step 1 for as long as the app runs. Verified in this container
        against the pre-fix block: piped into ``cat`` it was still running at
        10 s with the app asleep, and the capture directory held only
        ``server.pid``. The launch writes the app's output to ``app.log``, so
        the block returns as soon as the server answers.
        """
        started = time.time()
        r, _launched = _run_web_ui_start("ok", tmp_path, app_body=(
            'echo "app: starting"\n'
            'exec sleep 6\n'))
        elapsed = time.time() - started
        # The stub app is asleep on purpose; stop the one the block started.
        pidfile = _web_ui_capdir(tmp_path) / "server.pid"
        if pidfile.exists():
            try:
                os.kill(int(pidfile.read_text().strip()), 15)
            except (ValueError, ProcessLookupError, PermissionError):
                pass

        assert r.returncode == 0, r.stderr
        assert elapsed < 3, (
            f"the start block did not return while the app was still running "
            f"({elapsed:.1f}s): a captured/piped step waits for the app, "
            "which only the teardown stops")

    def test_web_ui_start_keeps_the_app_off_the_blocks_stdin(self, tmp_path):
        """A background app that reads the terminal eats the rest of the paste.

        The launch redirects the app's stdin from ``/dev/null``, and the case
        the redirect is for is the *interactive* paste: job control is on
        there, so an asynchronous command inherits the terminal's input, and
        an app that reads it consumes the rest of the pasted block — the
        readiness wait and the ``server.pid`` write below never run (verified
        in this container with job control on: the stub app's stdin read 200
        bytes of the block's remaining text; with the redirect it reads
        nothing). A ``bash < block`` run does not need the redirect — with
        job control off bash itself assigns ``/dev/null`` to an asynchronous
        command, verified with the redirect removed — so the ``set -m`` here
        models the paste case the recipe is written for, not that one.
        """
        seen = tmp_path / "app-stdin"
        r, _launched = _run_web_ui_start(
            "ok", tmp_path, job_control=True,
            app_body=f'head -c 200 > "{seen}" 2>/dev/null || true\n')

        assert r.returncode == 0, r.stderr
        assert seen.exists(), "the stub app never ran"
        captured = seen.read_text()
        assert captured == "", (
            "the app inherited the block's stdin and read the rest of the "
            "pasted block: " + repr(captured[:120]))

    def test_web_ui_start_saves_the_apps_startup_output(self, tmp_path):
        """The app's output goes to ``app.log``, where the failure points.

        The readiness failure says the app's startup output is in
        ``$CAPDIR/app.log``; the launch has to put it there. A shell's own
        "command not found" for an ``APP_START`` that does not exist lands
        there too, because the redirection applies to the command — the
        startup output is the first thing a failed start has to show, and
        nothing else writes it down.
        """
        r, _launched = _run_web_ui_start("ok", tmp_path, app_body=(
            'echo "app: listening on 8000"\n'))
        log = _web_ui_capdir(tmp_path) / "app.log"

        assert r.returncode == 0, r.stderr
        deadline = time.time() + 5
        while time.time() < deadline and (
                not log.exists() or "listening" not in log.read_text()):
            time.sleep(0.05)
        assert log.exists(), (
            "the start block wrote no app.log, so the readiness failure "
            "points at a file that does not exist")
        assert "app: listening on 8000" in log.read_text(), (
            "the app's startup output did not land in app.log: "
            + log.read_text())

    def test_a_refused_start_clears_the_previous_app_log(self, tmp_path):
        """A refused start must not leave the previous run's startup output.

        Step 1 clears the previous run's evidence before it probes the port,
        and the readiness failure points the worker at ``app.log``. A start
        refused for a busy port never launches the app, so without the log in
        that cleanup the worker reads the *previous* run's startup output as
        this run's — the stale-evidence class the rest of the cleanup exists
        for.
        """
        capdir = _web_ui_capdir(tmp_path)
        capdir.mkdir(parents=True)
        (capdir / "app.log").write_text("previous run: listening on 8000\n")

        r, launched = _run_web_ui_start("inuse", tmp_path)

        assert r.returncode != 0, r.stderr
        assert "already answers" in r.stderr, r.stderr
        assert not launched.exists(), (
            "the recipe started the app on a port another server holds")
        assert not (capdir / "app.log").exists(), (
            "the refused start left the previous run's app.log in place, and "
            "the readiness failure points the worker at it")

    def test_the_port_pre_check_is_bounded(self, tmp_path):
        """The pre-check's own bounds are what make its exit-28 branch exist.

        The readiness poll bounds each attempt because a deadline is only
        consulted between attempts (``test_readiness_waits_are_bounded``), and
        the port pre-check above it is a *single* request: curl has no default
        deadline for a server that accepted the connection and never answers,
        so an unbounded probe blocks the step instead of answering 28, and the
        "could not check … exit 28" diagnosis R27 added is unreachable — the
        unbounded wait this recipe removes everywhere else, in the block that
        runs before every capture. Verified live against a socket that accepts
        and never replies: the shipped probe exits 1 in 5.0 s with that
        message, and the same block with the flags removed is still blocked in
        curl at 20 s.

        No case could see it: the stub curl answers 28 by mode, whatever its
        arguments, so dropping the flags left the whole file green (200
        passed). The stub now records each call's argv, and the first call is
        the pre-check.
        """
        r, _launched = _run_web_ui_start("hung", tmp_path)
        assert r.returncode != 0, r.stderr
        calls = (tmp_path / "curl-log").read_text().splitlines()
        assert calls, "the start block made no curl call at all"
        precheck = calls[0]
        assert "--max-time" in precheck, (
            "the port pre-check has no deadline, so a listener that accepts "
            "and never answers blocks the step instead of answering 28: "
            + precheck)
        assert "--connect-timeout" in precheck, (
            "the port pre-check has no connect deadline: " + precheck)

    def test_an_app_that_answers_404_at_root_is_ready(self, tmp_path):
        """Readiness means "the server answers", not "the root returns 2xx".

        The port pre-check above uses curl *without* ``-f`` on purpose — any
        HTTP answer means the port is taken — but the readiness poll used
        ``-sf``, so an app whose UI lives at a subpath (404 at "/") was
        reported as "app did not answer on …" after the full deadline, and
        the healthy server this block had just started was killed (verified:
        ``curl -sf`` exits 22 on that app, plain ``curl`` exits 0). A
        misdiagnosis of a working app, in the same block that refuses a port
        something else answers on.
        """
        r, launched = _run_web_ui_start("http404", tmp_path)
        assert r.returncode == 0, (
            "an app that answers 404 at '/' was reported as not answering: "
            + r.stderr)
        deadline = time.time() + 5
        while not launched.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert launched.exists(), "the recipe never launched the app"

    def test_a_failed_start_removes_the_pid_it_recorded(self, tmp_path):
        """The dead app's pid must not outlive it in ``server.pid``.

        The readiness failure kills the app, and the teardown falls back to
        the recorded pid. Leaving it there means the teardown can signal a
        recycled pid — the exact reason step 1 clears a stale ``server.pid``
        before writing a new one (verified: the pre-fix block left the dead
        pid in place).
        """
        r, _launched = _run_web_ui_start("never", tmp_path)
        assert r.returncode != 0, r.stderr
        assert not (_web_ui_capdir(tmp_path) / "server.pid").exists(), (
            "the failed start left a dead app's pid in server.pid, so the "
            "teardown could signal a recycled pid")

    def test_an_unusable_capture_dir_stops_the_start(self, tmp_path):
        """The capture dir cannot be created, and the block still exits 0.

        Every later step writes into ``$CAPDIR`` (the pid file, the Layer 2
        redirects, the driver's outputs). Verified: with the captures path a
        regular file, the pre-fix block reported success, launched the app
        and wrote no pid file — the "silent success while writing nothing"
        class the Layer 2 and finalize guards were added for.
        """
        r, launched = _run_web_ui_start("ok", tmp_path, caps_is_file=True)
        assert r.returncode != 0, (
            "a capture directory that cannot be created was reported as a "
            "successful start")
        assert "could not create" in r.stderr, r.stderr
        assert not launched.exists(), (
            "the app was started although the capture directory does not "
            "exist, so its outputs have nowhere to go")

    @UNWRITABLE_MODES
    def test_an_unwritable_capture_dir_stops_the_start(self, tmp_path,
                                                       capdir_mode):
        """`mkdir -p` answers 0 for a capture directory that cannot be written.

        Every later write into it fails as something else: the clear leaves
        the previous run's mp4/webm/manifest/screenshots in place,
        ``server.pid`` cannot be written (so the teardown later refuses for a
        missing pid), the driver's link fails with "Permission denied" and is
        reported as "playwright does not resolve" — a remedy that cannot work
        — and the Layer 2 block exits 0 having written neither log. Verified
        live with a mode-500 capture directory: the pre-fix block exits 0,
        launches the app and writes no pid file. Stop where the directory is
        established, as both recording recipes do.

        Mode 600 (write bit, no search bit) is the shape only the guard's
        ``-x`` half can see: the block otherwise starts the app, writes no
        pid file, and exits 0 exactly as it does for mode 500.
        """
        if not hasattr(os, "geteuid") or os.geteuid() == 0:
            pytest.skip("root bypasses the directory permission bits")
        r, launched = _run_web_ui_start("ok", tmp_path,
                                        capdir_mode=capdir_mode)

        assert r.returncode != 0, (
            "a capture directory that cannot be written was reported as a "
            "successful start")
        assert "cannot be written" in r.stderr, r.stderr
        assert not launched.exists(), (
            "the app was started although nothing can be written into the "
            "capture directory")

    @pytest.mark.parametrize("pm_body", [
        # The real command's failure shape: the error on stderr, exit 1,
        # nothing on stdout (verified: "PR 'pr-xxxxxxx' not found." for an
        # unsubstituted id; "No project.yaml found" when the step is pasted
        # outside the project).
        'echo "PR \'pr-xxxxxxx\' not found." >&2\nexit 1\n',
        # A command that succeeds and prints nothing is the same empty answer.
        "exit 0\n",
    ])
    def test_web_ui_start_refuses_a_captures_path_it_cannot_resolve(
            self, pm_body, tmp_path):
        """An unresolvable captures path must not become ``/scenarios/…``.

        ``CAPDIR="$(pm qa captures-path "$PR_ID")/scenarios/1/web-ui"`` with
        an empty answer is ``/scenarios/1/web-ui`` — the *filesystem root* —
        and the block's ``mkdir -p`` creates it when the worker is root (QA
        container workers are). The whole capture then lands outside the
        per-PR captures directory while every later check passes on those
        files, and the manifest points at a directory the report never reads.
        Verified with real ``pm``: an unsubstituted ``PR_ID`` prints its error
        on stderr, exits 1 and leaves stdout empty, so the pre-fix block ran
        ``mkdir -p /scenarios/1/web-ui`` (as a non-root user that failed and
        was reported as "could not create … check the path and its
        permissions" — a misdiagnosis of a path that was never resolved).
        """
        mklog = tmp_path / "mkdir-calls"
        r, launched = _run_web_ui_start(
            "ok", tmp_path, pm_body=pm_body,
            # Watch what the block would create, without creating it.
            mkdir_body=f'printf "%s\\n" "$*" >> "{mklog}"\nexit 1\n')

        assert r.returncode != 0, (
            "the start block ran on with a captures path it could not "
            "resolve, so the capture lands at the filesystem root")
        assert "could not resolve the captures directory" in r.stderr, (
            r.stderr)
        assert "pm qa captures-path" in r.stderr, (
            "the failure does not name the command to run: " + r.stderr)
        assert not launched.exists(), (
            "the app was started although the capture directory was never "
            "resolved")
        assert not mklog.exists(), (
            "the block created (or tried to create) a directory from an "
            "empty captures-path answer: " + mklog.read_text())


def test_web_ui_clears_a_previous_video():
    """The web-UI capture must not transcode an earlier run's webm.

    Playwright's video only lands as ``recording.webm`` when the driver gets
    as far as renaming it, so a driver that fails leaves the *previous* run's
    webm in the capture directory — and the finalize step then produces a
    fresh-looking mp4 of that earlier run. Both the webm and the mp4 are
    cleared before the driver starts, and the mp4 again before the transcode
    (``ffmpeg`` leaves an existing output untouched when it fails).

    The glob is ``*.webm``, not ``recording.webm``: a driver killed before the
    rename (Playwright gone, so nothing finalizes or renames) leaves its
    auto-named ``page@<hash>.webm`` instead, and that file is a valid, playable
    partial recording (verified with ffprobe) that no other step clears.

    The driver's other outputs are cleared with them: a driver that dies at
    the first locator writes no trace, screenshots or DOM dump, so without
    this the earlier run's files stay in the capture directory and the
    manifest lists them as this run's evidence — the same stale-artifact bug
    as the webm, one artifact class over.
    """
    text = _recipe_text("web-ui-recording.md")
    capture = text.split("### 1. Start the UI under test", 1)[1].split(
        "### 2.", 1)[0]
    # Join backslash-continued lines so the cleanup is one logical command.
    joined = re.sub(r"\\\n\s*", " ", capture)
    clear = next((ln for ln in joined.splitlines()
                  if ln.startswith("rm -f") and "*.webm" in ln), None)
    assert clear, (
        "web-ui recipe keeps an earlier run's webm/mp4, so a failed driver "
        "transcodes the previous run into this run's recording")
    for artifact in ("*.webm", "recording.mp4", "recording.mp4.partial.mp4",
                     "trace.zip", "dom.html", "http.log", "sse.log",
                     "server.pid", "app.log", "manifest.md", "*.png"):
        assert artifact in clear, (
            f"web-ui recipe leaves a previous run's {artifact} in place, so a "
            "failed driver presents the earlier run's evidence as this run's")
    assert joined.index(clear) < joined.index('$APP_START --port'), (
        "web-ui recipe clears the previous run's outputs only after the app "
        "and driver have started")
    assert '"${CAPDIR:?}"/*.png' in clear, (
        "web-ui recipe globs \"$CAPDIR\"/*.png without the `${CAPDIR:?}` "
        "guard: with CAPDIR unset the glob expands against the filesystem "
        "root, so the cleanup would target every PNG there")
    assert '"${CAPDIR:?}"/*.webm' in clear, (
        "web-ui recipe globs \"$CAPDIR\"/*.webm without the `${CAPDIR:?}` "
        "guard: with CAPDIR unset the glob expands against the filesystem "
        "root")
    finalize_block = _web_ui_finalize_block()
    rm = finalize_block.index('rm -f "$CAPDIR/recording.mp4"')
    assert rm < finalize_block.index("\nffmpeg "), (
        "web-ui recipe only drops the old mp4 after the transcode")
    assert ('rm -f "$CAPDIR/recording.mp4" '
            '"$CAPDIR/recording.mp4.partial.mp4"') in finalize_block, (
        "web-ui recipe does not clear an interrupted transcode's partial "
        "before it starts, so the next attempt resumes into it")
    assert ('mv -f "$CAPDIR/recording.mp4.partial.mp4" '
            '"$CAPDIR/recording.mp4"') in finalize_block, (
        "web-ui recipe publishes the transcode under the final name without "
        "a rename, so an interrupted encode leaves a partial mp4 as this "
        "run's recording")
    assert 'test -s "$CAPDIR/recording.mp4"' in finalize_block, (
        "web-ui recipe does not check that the transcode produced the mp4")
    # Step 2's attempt cleanup (a driver retried alone) must clear the
    # partial too, for the same reason step 1 does.
    attempt = text.split("### 2. Drive Chromium", 1)[1].split("### 3.", 1)[0]
    attempt_joined = re.sub(r"\\\n\s*", " ", attempt)
    attempt_rm = next((ln for ln in attempt_joined.splitlines()
                       if ln.startswith("rm -f") and "./*.webm" in ln), None)
    assert attempt_rm and "./recording.mp4.partial.mp4" in attempt_rm, (
        "web-ui step 2's retry cleanup keeps an interrupted transcode's "
        "partial, so a retried attempt that fails presents it as this run's "
        "recording")


def _web_ui_layer2_block():
    """The fenced block under ``## Capture — Layer 2`` (the protocol logs)."""
    text = _recipe_text("web-ui-recording.md")
    section = text.split("## Capture — Layer 2: protocol capture", 1)[1]
    section = section.split("### Teardown", 1)[0]
    return re.findall(r"```[a-z]*\n(.*?)```", section, re.S)[0]


def test_web_ui_produced_files_list_names_the_playwright_link():
    """Step 2 leaves a ``node_modules`` link in the capture directory.

    The link is what makes the driver's bare ``import 'playwright'`` resolve
    (Node's ES-module resolver ignores ``NODE_PATH``), and it stays beside the
    capture, while the recipe's manifest section asks for "every file above".
    A worker reading only the produced-files list does not know it is there,
    so the manifest and the directory disagree — the same class as the
    recording recipes' diagnostics list (R17).
    """
    text = _recipe_text("web-ui-recording.md")
    section = text.split("## What this recipe produces", 1)[1]
    assert "node_modules" in section.split("## Capture", 1)[0], (
        "the produced-files list never names the node_modules link step 2 "
        "creates in the capture directory")
    manifest = text.split("## Manifest format", 1)[1].split("## Reviewing", 1)[0]
    assert "node_modules" in manifest, (
        "the manifest's `## Files` example does not name the node_modules link")


def test_web_ui_produced_files_list_names_the_files_a_failed_run_keeps():
    """The files the flow leaves in the capture directory were not all listed.

    ``server.pid`` is written by step 1 and removed by the teardown, so it is
    present exactly when a run stopped before the teardown — a failed driver,
    which step 2 tells the worker not to finalize, is the ordinary case.
    ``recording.webm`` is kept deliberately when the transcode fails, so the
    step can be retried without re-driving the UI. ``page@<hash>.webm`` is
    Playwright's auto-named video: the driver renames it onto
    ``recording.webm`` only after a complete walk-through, so a driver killed
    before the rename leaves it behind — a valid, playable *partial*
    recording (verified live in this container: SIGKILLing a recording driver
    leaves ``page@b87f….webm``, which ffprobe reports as 3.12 s), and the
    finalize step transcodes only ``recording.webm``, so nothing else ever
    removes or explains it. ``recording.mp4.partial.mp4`` is the finalize
    step's in-progress output: it is renamed onto ``recording.mp4`` only after
    a complete encode, so a step killed mid-encode (the shell gone, so no
    cleanup runs) leaves it behind while no mp4 exists — the file the next
    reader must not mistake for this run's video, and therefore one the
    manifest has to name when it is there. ``app.log`` is step 1's launch
    output: the readiness failure points the worker at it, and it is present
    for the whole run, so both lists have to name it (R83). The recipe's
    manifest section asks
    for "every file above", and the recording recipes' lists already name
    their failure evidence (R17), so a worker following this list leaves them
    out of ``## Files`` while the capture directory holds them — the same
    "the manifest and the directory disagree" class, one file over.

    The manifest's own ``## Files`` example has to name them too, not only the
    produced-files list: that example is what a worker copies into the
    manifest, and the ``node_modules`` line is pinned in both places for the
    same reason (``test_web_ui_produced_files_list_names_the_playwright_link``)
    — the example listed it while these were still missing.
    """
    text = _recipe_text("web-ui-recording.md")
    produced = text.split("## What this recipe produces", 1)[1].split(
        "## Capture", 1)[0]
    manifest = text.split("## Manifest format", 1)[1].split(
        "## Reviewing", 1)[0]
    # The manifest's `## Commands` block already mentions `recording.webm` in
    # its ffmpeg line, and the prose above the template mentions a "`## Files`
    # section", so the example's *file list* — the indented heading — is what
    # has to name it.
    files = manifest.split("\n    ## Files", 1)[1]
    for fname in ("server.pid", "recording.webm", "page@<hash>.webm",
                  "recording.mp4.partial.mp4", "app.log"):
        assert fname in produced, (
            "the produced-files list never names " + fname + ", which the "
            "flow leaves in the capture directory (a run stopped before the "
            "teardown; a failed transcode; a driver killed before the "
            "rename), so the manifest's `## Files` section and the directory "
            "disagree")
        assert fname in files, (
            "the manifest's `## Files` example does not name " + fname + ", "
            "although the produced-files list says to mention it when it "
            "survives — a worker copying the example leaves it out while the "
            "capture directory holds it")


def test_web_ui_layer2_block_refuses_an_unset_capdir(tmp_path):
    """The protocol block is pasted alone too, and its redirects are raw paths.

    Verified: with ``CAPDIR`` unset the block redirects to ``/http.log`` and
    ``/sse.log`` — into the filesystem root when the worker is root,
    "Permission denied" otherwise — and *still exits 0*, so a run with no
    protocol capture reads as a success. The same guard the driver, finalize
    and teardown blocks carry belongs here, before the first redirect.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "curl-called"
    _stub_tool(bindir, "curl", f'touch "{called}"\n')
    env = {k: v for k, v in os.environ.items()
           if k not in ("CAPDIR", "APP_URL")}
    env["PATH"] = f"{bindir}:{os.environ['PATH']}"

    r = subprocess.run(["bash"], input=_web_ui_layer2_block(), env=env,
                       capture_output=True, text=True, timeout=60)

    assert r.returncode != 0, (
        "the protocol block ran with no CAPDIR and reported success")
    assert "CAPDIR" in r.stderr, r.stderr
    assert not called.exists(), (
        "the protocol block ran curl with an unset CAPDIR, so its redirects "
        "aimed at the filesystem root")


def test_web_ui_layer2_block_refuses_a_missing_capture_dir(tmp_path):
    """A set-but-missing ``CAPDIR`` is the same silent success, one step on.

    Both redirects fail, so neither ``curl`` runs, and the block's last
    command succeeds — verified: the previous block exits 0 while writing no
    protocol capture at all. The guard has to cover the directory, not only
    the variable.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "curl-called"
    _stub_tool(bindir, "curl", f'touch "{called}"\n')
    env = dict(os.environ, CAPDIR=str(tmp_path / "missing-cap"),
               APP_URL="http://localhost:1",
               PATH=f"{bindir}:{os.environ['PATH']}")

    r = subprocess.run(["bash"], input=_web_ui_layer2_block(), env=env,
                       capture_output=True, text=True, timeout=60)

    assert r.returncode != 0, (
        "the protocol block ran with a capture directory that does not exist "
        "and reported success")
    assert "does not exist" in r.stderr, r.stderr
    assert not called.exists(), (
        "the protocol block ran curl with nowhere to write its logs")


@UNWRITABLE_MODES
def test_web_ui_layer2_block_refuses_a_capture_dir_it_cannot_write(
        tmp_path, capdir_mode):
    """The existence guard cannot see this one, and the block exits 0.

    The directory is there, so ``[ -d "$CAPDIR" ]`` passes, but neither
    redirect can be opened: neither curl runs, and the block's last command
    (``kill … || true``) succeeds — verified live with a mode-500 capture
    directory: rc 0, no ``http.log``, no ``sse.log``. That is exactly the "a
    run with no protocol capture reads as success" failure this block's guard
    exists for, one shape over. Mode 600 is the shape only the guard's
    ``-x`` half can see, for the same reason.
    """
    if not hasattr(os, "geteuid") or os.geteuid() == 0:
        pytest.skip("root bypasses the directory permission bits")
    capdir = tmp_path / "cap"
    capdir.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "curl-called"
    _stub_tool(bindir, "curl", f'touch "{called}"\n')
    env = dict(os.environ, CAPDIR=str(capdir), APP_URL="http://localhost:1",
               PATH=f"{bindir}:{os.environ['PATH']}")
    capdir.chmod(capdir_mode)
    try:
        r = subprocess.run(["bash"], input=_web_ui_layer2_block(), env=env,
                           capture_output=True, text=True, timeout=60)
    finally:
        capdir.chmod(0o700)

    assert r.returncode != 0, (
        "the protocol block reported success while writing neither log into "
        "a capture directory nothing can be written into")
    assert "cannot be written" in r.stderr, r.stderr
    assert not called.exists(), (
        "the protocol block ran curl with nowhere to write its logs")


def test_web_ui_layer2_block_names_a_missing_curl(tmp_path):
    """The protocol block's only tool is curl, and a missing one is silent.

    Both redirects still open: the shell's own "curl: command not found" lands
    in each log, neither request runs, and the block's last command (``kill …
    || true``) succeeds — verified with no curl on PATH: the block exits **0**
    with ``http.log`` and ``sse.log`` holding only that error text. That is
    the "a run with no protocol capture reads as success" state the CAPDIR and
    directory guards above exist for, one tool over. Step 1 already treats a
    missing curl as a hard failure (its port pre-check answers 127 and names
    it), but every block in this recipe is pasted into a fresh shell, so this
    one has to say it where it fails — the same rule as the ``node`` and
    ``ffmpeg`` guards in the driver and finalize steps.

    The PATH holds no curl at all (the block's tools are builtins), so the
    case cannot pass on a host that happens to have one.
    """
    bash = shutil.which("bash")
    assert bash, "bash is required"
    capdir = tmp_path / "cap"
    capdir.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # The block needs nothing but shell builtins once the guard fires; the
    # symlinks keep the *pre-fix* block able to run to its exit-0 end (it
    # reaches `sleep 2` and the SSE reader), which is what makes this a
    # before/after case rather than a missing-tool text match.
    for tool in ("sleep", "cat"):
        for d in ("/bin", "/usr/bin"):
            if (Path(d) / tool).exists():
                os.symlink(str(Path(d) / tool), bindir / tool)
                break
    env = {"CAPDIR": str(capdir), "APP_URL": "http://localhost:1",
           "PATH": str(bindir)}

    r = subprocess.run([bash], input=_web_ui_layer2_block(), env=env,
                       capture_output=True, text=True, timeout=60)

    assert r.returncode != 0, (
        "the protocol block ran with no curl on PATH and reported success, "
        "so a run with no protocol capture reads as a finished one")
    assert "curl" in r.stderr, (
        "the protocol block did not name the tool it cannot run: " + r.stderr)
    assert not (capdir / "http.log").exists(), (
        "the block wrote an http.log holding only curl's absence")
    assert not (capdir / "sse.log").exists(), (
        "the block wrote an sse.log holding only curl's absence")


def test_web_ui_layer2_route_snapshots_are_bounded():
    """A route that accepts but never answers must not hang the protocol block.

    Step 1's readiness poll bounds each attempt (``--connect-timeout 2
    --max-time 5``) because a deadline is only consulted *between* attempts;
    the protocol block's per-route ``curl`` had no bound at all, so a route
    that stalled blocked the worker forever — the unbounded-wait class this
    PR bounds everywhere else. A timed-out route is recorded in ``http.log``
    as curl's own error with status ``000``, which is that route's evidence.
    """
    block = _web_ui_layer2_block()
    loop = block[block.index("for route in"):block.index("\n} > ")]
    assert "--max-time" in loop and "--connect-timeout" in loop, (
        "the protocol block's route snapshots are unbounded: " + loop)
    # The SSE reader is the block's other request, and it is an *unbounded*
    # stream (`curl -N`): the `kill` after the trigger is best-effort
    # (`2>/dev/null || true`), so without its own deadline a failed kill
    # leaves an orphan curl writing into `sse.log` for the rest of the
    # session — the same unbounded request the route snapshots were bounded
    # for, one line over.
    sse = next(ln for ln in block.splitlines()
               if ln.lstrip().startswith("curl") and "-N" in ln)
    assert "--max-time" in sse, (
        "the SSE reader is unbounded, so a failed kill leaves it running: "
        + sse)


def test_web_ui_layer2_route_snapshots_record_the_status(tmp_path):
    """Each route's snapshot has to carry curl's status code.

    The block's own prose says ``-w`` "records the status line per route", and
    that "a timed-out route is recorded in the log as curl's own error with
    status 000 — that is the evidence for that route". Both claims depend on
    the ``-w`` format argument, and no case exercised it: dropping the line
    left the whole file green (**298 passed**, verified) while ``http.log``
    then holds the route bodies with no status at all — a reviewer cannot
    tell a 200 from a 500, and a route that timed out leaves only curl's
    error line, not the ``[HTTP 000]`` marker the prose promises. Verified
    live with real curl 7.81 against a socket that accepts and never answers:
    with ``-w`` the route writes ``[HTTP 000]`` beside "Operation timed
    out", without it only the error.

    The block is *run* with a logging stub ``curl``, so the case sees the
    argv each route request is given rather than the recipe's text — the
    same shape as the port pre-check's bound case.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "curl-argv"
    _stub_tool(bindir, "curl",
               f'printf "%s\\n" "$*" >> "{log}"\necho "HTTP 200"\n')
    env = dict(os.environ, CAPDIR=str(capdir), APP_URL="http://localhost:1",
               PATH=f"{bindir}:{os.environ['PATH']}")

    r = subprocess.run(["bash"], input=_web_ui_layer2_block(), env=env,
                       capture_output=True, text=True, timeout=60)

    assert r.returncode == 0, r.stderr
    block = _web_ui_layer2_block()
    routes = re.findall(r'"(/[^"]*)"',
                        block.split("for route in", 1)[1].split("; do", 1)[0])
    assert routes, "the protocol block snapshots no routes"
    calls = log.read_text().splitlines()
    for route in routes:
        url = f"http://localhost:1{route}"
        call = next((ln for ln in calls if ln.rstrip().endswith(url)), None)
        assert call, (
            f"the protocol block never snapshotted {route}: "
            + log.read_text())
        assert "-w" in call and "%{http_code}" in call, (
            f"the {route} snapshot does not record the status line, so "
            "http.log cannot show what the route answered: " + call)
        assert "[HTTP " in call, (
            f"the {route} snapshot's status line has no [HTTP NNN] marker, so "
            "http.log cannot show what the route answered: " + call)


def test_web_ui_layer2_stops_the_sse_reader_it_started(tmp_path):
    """The protocol block's last act is to stop the reader it started.

    ``curl -N`` is an open stream: the block backgrounds it, triggers the
    change, and stops it — "then stop the reader", as its own comment says.
    ``--max-time`` bounds a *failed* stop, so dropping the ``kill`` leaves the
    suite green (verified: 228 passed with the line removed) while the block
    returns with the reader still writing into ``sse.log``: the capture the
    block hands back is not the capture it produced, and a reader started
    again by the next attempt appends to a log this run never closed. The
    stub below traps ``TERM`` and records that it arrived, so the case sees
    the stop itself rather than the text of the line.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stopped = tmp_path / "sse-reader-stopped"
    _stub_tool(bindir, "curl", f"""\
case " $* " in
  *" -N "*)
      trap 'echo stopped > "{stopped}"; exit 0' TERM
      i=0
      while [ "$i" -lt 100 ]; do sleep 0.1; i=$((i+1)); done
      exit 0 ;;
esac
echo "HTTP 200"
""")
    env = dict(os.environ, CAPDIR=str(capdir), APP_URL="http://localhost:1",
               PATH=f"{bindir}:{os.environ['PATH']}")

    r = subprocess.run(["bash"], input=_web_ui_layer2_block(), env=env,
                       capture_output=True, text=True, timeout=60)

    assert r.returncode == 0, r.stderr
    deadline = time.time() + 5
    while not stopped.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert stopped.exists(), (
        "the protocol block returned with the SSE reader it started still "
        "running, so sse.log keeps growing after the block says the capture "
        "is done")


def test_web_ui_layer2_block_writes_both_logs(tmp_path):
    """The guard must not break the step it protects."""
    capdir = tmp_path / "cap"
    capdir.mkdir()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_tool(bindir, "curl", 'echo "HTTP 200"\n')
    env = dict(os.environ, CAPDIR=str(capdir), APP_URL="http://localhost:1",
               PATH=f"{bindir}:{os.environ['PATH']}")

    r = subprocess.run(["bash"], input=_web_ui_layer2_block(), env=env,
                       capture_output=True, text=True, timeout=60)

    assert r.returncode == 0, r.stderr
    assert "GET /" in (capdir / "http.log").read_text(), (
        "the protocol block wrote no route snapshots")
    assert (capdir / "sse.log").exists(), (
        "the protocol block wrote no SSE transcript")



# ---------------------------------------------------------------------------
# Capture-flow execution
# ---------------------------------------------------------------------------
#
# The capture flow's failure modes are silent — a wait that ends badly looks
# like a finished recording — and every regression found in this recipe so far
# (a failed attach's error text counted as a drawn TUI; a recorder that died
# mid-scenario passing on a truncated cast) was *behavioural*: the text
# assertions above described the flow correctly while it still did the wrong
# thing. These cases run the fenced block a worker pastes against stub
# ``tmux``/``pm``, so the readiness and stop logic is exercised rather than
# matched.

_STUB_TMUX = r"""
STATE="$STUB_STATE"
# Optional call log. A block that refuses its own input must not act on a
# handle shared with concurrent runs (the recorder session), so some cases
# assert on the calls the block made — or made none.
[ -n "${STUB_TMUX_LOG:-}" ] && printf '%s\n' "$*" >> "$STUB_TMUX_LOG"
while [ "$1" = "-L" ]; do shift 2; done
sub=$1; shift
val() { f=$1; shift; while [ $# -gt 0 ]; do
          if [ "$1" = "$f" ]; then echo "$2"; return; fi; shift; done; }
# Session-target resolution, the way real tmux does it (3.2a, verified): an
# exact name wins, and when no session has the whole name the target is
# matched by *prefix* — `has-session -t pm-test` exits 0 with only
# `pm-test~1` on the server, which is how pm's grouped `base~N` sessions get
# picked up. A leading `=` forces an exact match; a *bare* `=pm-test` target is
# refused by `show-options`/`set-option` (verified: "no such session:
# =pm-test"), but the `=pm-test:0.0` pane form they also accept is exact
# (verified: it answers "no such session" with only the grouped session on the
# server), so those two strip the pane spec like the pane-target commands do.
# Echoes the resolved name, or fails.
resolve() {
    t=$1; exact=0
    case "$t" in =*) exact=1; t=${t#=} ;; esac
    [ -z "$t" ] && return 1
    [ -f "$STATE/$t" ] && { echo "$t"; return 0; }
    [ "$exact" = 1 ] && return 1
    for f in "$STATE"/*; do
        [ -e "$f" ] || continue
        b=${f##*/}
        case "$b" in pane|sends|pipeclaim|claim.*|pipe.*|dead.*|roexit.*|rejected.*) continue ;; esac
        case "$b" in "$t"*) echo "$b"; return 0 ;; esac
    done
    return 1
}
# The pane's command returned. With `remain-on-exit on` (`STUB_REMAIN`) the
# server keeps the session and marks the pane dead — real tmux 3.2a: the
# session stays, `has-session` succeeds, `capture-pane` still answers and
# `#{pane_dead}` is 1 (verified) — so the session's existence is *not* the
# completion signal. Without it the pane's death ends the session.
pane_exit() {
    if [ -n "${STUB_REMAIN:-}" ] && [ -f "$STATE/roexit.$1" ]; then
        : > "$STATE/dead.$1"
    else
        rm -f "$STATE/$1" "$STATE/claim.$1" "$STATE/pipe.$1" \
              "$STATE/dead.$1" "$STATE/roexit.$1" "$STATE/rejected.$1"
    fi
}
case "$sub" in
  has-session)
      # Real tmux (3.2a, verified) *succeeds* for `-t ''` — the empty target
      # matches the current session. Modelling that is what makes an unset
      # $TARGET visible: the recipe's both-gone branch would fire on a
      # legitimate finish.
      s=$(val -t "$@")
      [ -z "$s" ] && exit 0
      resolve "$s" >/dev/null && exit 0 || exit 1 ;;
  kill-session)
      s=$(val -t "$@")
      r=$(resolve "$s") || exit 0
      # A session ending takes its pipe with it.
      rm -f "$STATE/$r" "$STATE/claim.$r" "$STATE/pipe.$r" \
            "$STATE/dead.$r" "$STATE/roexit.$r" "$STATE/rejected.$r"; exit 0 ;;
  kill-server)  rm -f "$STATE/rec" "$STATE/pm-recorder" "$STATE/claim.rec" \
                     "$STATE/claim.pm-recorder" "$STATE/pipe.rec" \
                     "$STATE/pipe.pm-recorder" "$STATE/dead.rec" \
                     "$STATE/dead.pm-recorder" "$STATE/roexit.rec" \
                     "$STATE/roexit.pm-recorder" "$STATE/rejected.rec" \
                     "$STATE/rejected.pm-recorder"; exit 0 ;;
  pipe-pane)
      s=$(val -t "$@")
      r=$(resolve "${s%%:*}")
      if [ -z "$r" ]; then
          echo "can't find session: $s" >&2; exit 1
      fi
      # Record the session claim *as the pipe is attached*: the recipe has to
      # take the capture-directory claim before this call, or a second run can
      # pass the same check and take the pipe over in the gap.
      cat "$STATE/claim.$r" 2>/dev/null > "$STATE/pipeclaim" || true
      # `pipefail`: the attach itself fails. `notranscript`: the attach is
      # accepted but nothing is ever written, which only the end-of-run check
      # can catch.
      if [ "$STUB_MODE" = pipefail ]; then
          echo "can't find pane: $s" >&2; exit 1
      fi
      for a in "$@"; do cmd=$a; done
      # Track the pane's pipe for `display-message #{pane_pipe}`: the attach
      # carries its command (`cat >> …/transcript.log`), a stop does not
      # (`pipe-pane -t S`). A failed attach (above) leaves no pipe behind, and
      # the recipe's step 3 refuses a restart without one.
      case "$cmd" in
        *">>"*) touch "$STATE/pipe.$r" ;;
        *)      rm -f "$STATE/pipe.$r" ;;
      esac
      if [ "$STUB_MODE" != notranscript ]; then
          case "$cmd" in
            *">>"*) out=${cmd#*>> }; out=${out%% *}
                    # The recipe's pipe command may name the capture
                    # directory as ``~/…`` (a documented spelling); the real
                    # pane shell expands that, so model it here rather than
                    # writing into a literal ``~`` directory.
                    case "$out" in "~/"*) out="$HOME/${out#"~/"}";; esac
                    # `emptytranscript`: the pipe is attached and its command
                    # opens the file, but the pane emits nothing — a 0-byte
                    # transcript. That is the state the recipe's `test -s`
                    # check exists for (the file exists, so `-e` passes), and
                    # it is what a real `pipe-pane` leaves on an idle pane.
                    if [ "$STUB_MODE" = emptytranscript ]; then
                        : > "$out"
                    else
                        printf 'pane output\n' >> "$out"
                    fi ;;
          esac
      fi
      exit 0 ;;
  capture-pane)
      # Resolve the target the way real tmux does, and fail once the session
      # is gone (verified on 3.2a: `capture-pane -p -t "=pm-recorder:0.0"`
      # answers "can't find session: pm-recorder" after the recorder is
      # killed). Ignoring the target would let a recipe save the pane *after*
      # its teardown and still write content into `recorder-pane.log` — the
      # save-before-teardown ordering every failure message depends on
      # (R11/R13) would be unprovable, and a worker would be pointed at an
      # empty file.
      s=$(val -t "$@")
      r=$(resolve "${s%%:*}")
      if [ -z "$r" ]; then
          echo "can't find session: $s" >&2; exit 1
      fi
      # `nopane`: the session is there but its pane is not (a window that went
      # away, or the full-disk/read-only state's write failure): real tmux
      # answers "can't find window: 0" and fails, so a failing wait's pane save
      # cannot land.
      if [ "$STUB_MODE" = nopane ]; then
          echo "can't find window: 0" >&2; exit 1
      fi
      cat "$STATE/pane" 2>/dev/null; exit 0 ;;
  display-message)
      # `#{pane_pipe}` is the recipe's handle for "step 2's transcript pipe is
      # attached" (verified on tmux 3.2a: 1 while a pipe is attached, 0 when
      # none is). The target carries a pane spec, which real tmux resolves
      # against the session part — same as `pipe-pane` above.
      s=$(val -t "$@")
      r=$(resolve "${s%%:*}")
      [ -z "$r" ] && { echo "can't find session: $s" >&2; exit 1; }
      case "$*" in
        *pane_pipe*)
            [ -f "$STATE/pipe.$r" ] && { echo 1; exit 0; }
            echo 0; exit 0 ;;
        # The pane's command has returned. Real tmux (3.2a, verified) answers 1
        # for a pane kept by `remain-on-exit` and 0 while it runs; the session
        # is still there in the first case, which is why the recipes cannot use
        # `has-session` alone.
        *pane_dead*)
            [ -f "$STATE/dead.$r" ] && { echo 1; exit 0; }
            echo 0; exit 0 ;;
      esac
      exit 0 ;;
  # Session user options: the capture-dir claim step 2 writes and step 5
  # clears. Modelled on the real server (verified: `set-option -t S
  # @pm_capture_dir V`, `show-options -t S -v @pm_capture_dir`, and
  # `set-option -u` round-trip; a grouped session does not inherit it).
  show-options)
      s=$(val -t "$@")
      r=$(resolve "${s%%:*}")
      case "$*" in
        *@pm_capture_dir*)
            [ -n "$r" ] && [ -f "$STATE/claim.$r" ] && {
                cat "$STATE/claim.$r"; exit 0; }
            exit 1 ;;
        # The rejection step 5 sets when it refuses a capture (and step 2
        # clears for a new one): the state a failed paste leaves must not be
        # read as a finished recording by the next paste.
        *@pm_capture_rejected*)
            [ -n "$r" ] && [ -f "$STATE/rejected.$r" ] && {
                cat "$STATE/rejected.$r"; exit 0; }
            exit 1 ;;
        # The server's prefix (step 5's detach key is this, not a literal
        # C-b). A real server always answers, C-b by default; STUB_PREFIX
        # models a ~/.tmux.conf that sets another one.
        *prefix*) printf '%s\n' "${STUB_PREFIX:-C-b}"; exit 0 ;;
      esac
      exit 0 ;;
  set-option)
      s=$(val -t "$@")
      # `claimgap`: the target ends between step 2's exact-session assert and
      # the claim write, and pm's grouped `pm-test~1` session is left behind —
      # the shape a *bare* set-option target prefix-matches. Real tmux (3.2a,
      # verified) writes the option on the grouped session and exits 0, so the
      # step's guard cannot fire; the `=pm-test:0.0` form is exact and answers
      # "no such session". `claimgone` is the other half: no session matches
      # the prefix, so even a bare write fails.
      if [ "$STUB_MODE" = claimgap ]; then
          rm -f "$STATE/pm-test" "$STATE/claim.pm-test"
          touch "$STATE/pm-test~1"
      fi
      r=$(resolve "${s%%:*}")
      [ -z "$r" ] && { echo "no such session: $s" >&2; exit 1; }
      # The rejection mark step 5 sets and step 2 clears, beside the claim.
      case " $* " in
        *@pm_capture_rejected*)
            case " $* " in
              *" -u "*) rm -f "$STATE/rejected.$r"; exit 0 ;;
            esac
            printf '1\n' > "$STATE/rejected.$r"; exit 0 ;;
      esac
      case " $* " in
        *" -u "*) rm -f "$STATE/claim.$r"; exit 0 ;;
      esac
      # `claimgone`: the target session ends between step 2's exact-session
      # assert and the claim write, so the claim cannot be taken although the
      # assert just passed. The step has to say so where it fails; without its
      # guard it runs on into the pipe attach, which reports "could not
      # stream … — check that pane exists" for a session that went away.
      if [ "$STUB_MODE" = claimgone ]; then
          rm -f "$STATE/$r" "$STATE/claim.$r"
          echo "no such session: $s" >&2
          exit 1
      fi
      for a in "$@"; do v=$a; done
      printf '%s\n' "$v" > "$STATE/claim.$r"
      # `pipegap`: the target session ends in the gap between step 2's
      # exact-session assert and the pipe attach, and a grouped `<base>~1`
      # session (pm creates one per extra co-viewing client) is left behind.
      # That is the state a *bare* pipe target prefix-matches: real tmux
      # (3.2a, verified) answers "can't find session: pm-test" for
      # `pipe-pane -t '=pm-test:0.0'` and attaches to `pm-test~1` for
      # `-t pm-test:0.0`, so a bare handle streams another session's output
      # into this run's transcript and the run then exits 0.
      if [ "$STUB_MODE" = pipegap ]; then
          rm -f "$STATE/pm-test" "$STATE/claim.pm-test"
          touch "$STATE/pm-test~1"
      fi
      exit 0 ;;
  list-sessions)
      for f in "$STATE"/*; do
          [ -e "$f" ] || continue
          b=${f##*/}
          case "$b" in pane|sends|pipeclaim|claim.*|pipe.*|rejected.*) continue ;; esac
          echo "$b"
      done
      exit 0 ;;
  send-keys)
      # The target may carry a pane spec (`=pm-recorder:0.0`), which real tmux
      # resolves against the session part — same as `pipe-pane` above.
      s=$(val -t "$@")
      r=$(resolve "${s%%:*}")
      [ -z "$r" ] && exit 0
      # `stuck`: the recorder never goes away, so a stop wait runs out.
      [ "$STUB_MODE" = stuck ] && exit 0
      # `prefix`: only the server's own prefix followed by `d` reaches the
      # attach client and ends the recording. Anything else is ordinary input
      # to the attached TUI (verified live on a server with `prefix C-\`: the
      # recorder stayed up and the pane showed the keys). The last two
      # arguments are the prefix and `d`.
      if [ "$STUB_MODE" = prefix ]; then
          last2=""; last1=""
          for a in "$@"; do last2=$last1; last1=$a; done
          [ "$last2" = "${STUB_PREFIX:-C-b}" ] || exit 0
      fi
      # A pane whose command has returned receives nothing, but real tmux
      # (3.2a, verified) still accepts the keys and returns 0 — so a recipe
      # that treats the send as its handle sees a success. `remain-on-exit`
      # is what leaves such a pane in place.
      [ -f "$STATE/dead.$r" ] && exit 0
      pane_exit "$r"
      # `detachboth`/`detachbothbad`: the detach races the pm session's own
      # end. The attach followed the session out, so the recorder is already
      # gone when the key is sent (`send-keys` fails) and the session it was
      # attaching to is gone too — the legitimate "the scenario ended the pm
      # session" finish, a moment later than the both-gone branch sees it.
      # The session's death takes its claim with it.
      case "$STUB_MODE" in
        detachboth|detachbothbad)
            rm -f "$STATE/pm-test" "$STATE/claim.pm-test"; exit 1 ;;
      esac
      [ "$STUB_MODE" = detachfail ] && exit 1
      exit 0 ;;
  new-session)
      # `nostart`: tmux cannot create the session at all (server gone or
      # refusing, a duplicate session from a concurrent run). The pane command
      # never runs, so the readiness/stop checks must not be reached — the
      # recipe has to report the start failure, not "the recorder exited".
      if [ "$STUB_MODE" = nostart ]; then
          echo "tmux: error connecting to /tmp/tmux-1000/default" >&2
          exit 1
      fi
      s=$(val -s "$@")
      touch "$STATE/$s"
      # `remain-on-exit on` is a server-wide window option in the user's
      # ~/.tmux.conf, so every pane this server creates inherits it.
      [ -n "${STUB_REMAIN:-}" ] && : > "$STATE/roexit.$s"
      case "$STUB_MODE" in
        # `nopane`: the session exists but its pane does not, so the failing
        # wait's pane save cannot land (see `capture-pane`).
        norec|nopane) : ;;
        dies)  pane_exit "$s" ;;
        failedattach)
            printf "can't find session: pm-test\n" > "$STATE/pane"
            ( sleep 0.02; pane_exit "$s" ) & ;;
        *)
            # `detachnocast`/`detachnostatus`: the recorder draws and the
            # detach ends it (the pm session survives, as it does in a real
            # finish), so step 5 reaches its own cast/status check — the two
            # branches after the claim is taken that no other mode reaches
            # with the session still there to hold the claim.
            # `emptycast`: the recorder reports success (the status below is
            # 0) but its cast is 0 bytes — the state the recipes' `test -s`
            # cast check exists for, and one an existence check cannot see.
            case "$STUB_MODE" in
              detachnocast) : ;;
              emptycast)    : > "$STUB_CAST" ;;
              *)            printf '{"version": 2}\n' > "$STUB_CAST" ;;
            esac
            printf 'TUI drawn\n' > "$STATE/pane"
            if [ -n "$STUB_STATUS_FILE" ]; then
                case "$STUB_MODE" in
                  # `midadied`: the recorder session is killed during step 4,
                  # so the pane's shell dies before asciinema returns and the
                  # status is never written (verified on tmux 3.2a: a
                  # `kill-session` left no recorder.status). Writing one here
                  # would model a killed recorder that still reported a clean
                  # exit — a state step 5 is right to read as a finish.
                  nostatus|detachnostatus|midadied|remaindied) : ;;
                  # `emptystatus`: the pane's shell opened the status file and
                  # was killed (or could not write) before the status landed —
                  # a 0-byte file, which is not an exit status.
                  emptystatus) : > "$STUB_STATUS_FILE" ;;
                  badstatus|midbothbad|detachbothbad) printf '137\n' > "$STUB_STATUS_FILE" ;;
                  *)         printf '0\n' > "$STUB_STATUS_FILE" ;;
                esac
            fi ;;
      esac
      case "$STUB_MODE" in
        oneshot|badstatus|nostatus) ( sleep 0.3; pane_exit "$s" ) & ;;
        # The CLI scaffold's pane *is* the recording, so its session ends when
        # the one-shot command ends; the tmux recipe's recorder must stay up
        # until the detach ends it, so `emptystatus`/`emptycast` only end the
        # scaffold's own `rec` session.
        emptystatus|emptycast) [ "$s" = rec ] && ( sleep 0.3; pane_exit "$s" ) & ;;
      esac
      exit 0 ;;
esac
exit 0
"""

_STUB_PM = r"""
STATE="$STUB_STATE"
case "$1 $2" in
  "session name") echo "${STUB_PM_NAME-pm-test}" ;;
  "session ")     exit 0 ;;
  "tui send")
      [ -n "$STUB_PM_SEND_LOG" ] && printf '%s\n' "$*" >> "$STUB_PM_SEND_LOG"
      # `sendfail`: the *first* send fails and later ones succeed — the
      # mid-scenario failure whose exit status the block's own (last command)
      # status would otherwise hide.
      if [ "$STUB_MODE" = sendfail ]; then
          n=$(cat "$STATE/sends" 2>/dev/null || echo 0)
          n=$((n + 1)); echo "$n" > "$STATE/sends"
          if [ "$n" = 1 ]; then
              echo "No TUI pane found. Is there a pm tmux session running?" >&2
              exit 1
          fi
      fi
      case "$STUB_MODE" in
        midadied) rm -f "$STATE/pm-recorder" "$STATE/claim.pm-recorder" \
                       "$STATE/rejected.pm-recorder" ;;
        # `remaindied`: the recorder died mid-scenario (asciinema was killed)
        # but the server keeps the session because `remain-on-exit on` is set —
        # a dead pane, no status file, and a `has-session` that still answers.
        remaindied) : > "$STATE/dead.pm-recorder" ;;
        midboth|midbothbad)
            # A session ending takes its session options (the capture-dir
            # claim) with it, as real tmux does.
            rm -f "$STATE/pm-recorder" "$STATE/claim.pm-recorder" \
                  "$STATE/pm-test" "$STATE/claim.pm-test" \
                  "$STATE/rejected.pm-recorder" "$STATE/rejected.pm-test" ;;
      esac
      exit 0 ;;
esac
exit 0
"""


def _run_block(raw, mode, tmp_path, target=False, env_extra=None,
               sessions=(), files=None, state_files=None, capture=None,
               cwd=None, timeout=120, reuse=False):
    """Run one recipe block against stub tmux/pm; return (proc, cast path).

    ``raw`` is the block text as a worker pastes it, ``sessions`` the tmux
    sessions that already exist when it starts (a stop block runs against the
    sessions steps 1-3 left behind), ``files`` the capture-dir files and
    ``state_files`` the stub's own files (``pane``) to seed. ``capture``
    overrides the capture directory (a test that wants it unusable passes a
    path that cannot be created). ``cwd`` is the directory the block is pasted
    from — the recipes resolve some paths against it, so a case that depends
    on the worker's location has to say where that is. ``reuse`` runs a second
    block against the state the first one left — the same server, the same
    session options and the same capture directory — which is how a second
    paste of a step is modelled; the caller passes ``capture`` and seeds
    nothing, because the first run's sessions, claim and rejection mark are
    what the case is about.
    """
    state = tmp_path / "state"
    bindir = tmp_path / "bin"
    if capture is None:
        capture = tmp_path / "cap"
        if not reuse:
            capture.mkdir()
    if not reuse:
        for d in (state, bindir):
            d.mkdir()
        _stub_tool(bindir, "tmux", _STUB_TMUX)
        _stub_tool(bindir, "pm", _STUB_PM)
        if target:
            (state / "pm-test").touch()
        for s in sessions:
            (state / s).touch()
    for rel, content in (state_files or {}).items():
        (state / rel).write_text(content)
    # The CLI scaffold writes under <capture-dir>/<short-name>/, the tmux
    # recipe directly under <capture-dir>/.
    sub = ("run/" if "<short-name>/recording.cast" in raw else "")
    block = (raw.replace("<capture-dir>", str(capture))
                .replace("<short-name>", "run")
                .replace("<command-to-record>", "echo hi"))
    # A ``~/…`` capture directory is expanded by the block's own shell, but
    # the stub receives its paths through variables, where a tilde is not
    # expanded — so the stub and this helper's file operations need the
    # expanded spelling while the block text keeps what a worker typed.
    home = (env_extra or {}).get("HOME")
    stub_capture = _expand_tilde(capture, home)
    for rel, content in (files or {}).items():
        p = stub_capture / sub / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    # Shorten every numeric deadline so the failing cases finish quickly.
    # Matching the shape (rather than the literal ``30``/``60``) keeps the
    # cases fast when a recipe's bound is retuned, instead of silently waiting
    # it out — which is why the *value* of a bound is pinned separately, by
    # ``test_every_deadline_is_a_real_bound_and_its_message_agrees``: no
    # execution case can see it here.
    block = re.sub(r"\+\s*\d+\s*\)\)", "+ 2 ))", block)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               STUB_STATE=str(state), STUB_MODE=mode,
               STUB_CAST=str(stub_capture / sub / "recording.cast"),
               **(env_extra or {}))
    if "recorder.status" in raw:
        # The CLI scaffold's pane command records asciinema's own exit status;
        # the stub cannot run the pane command, so it writes the status the
        # recipe's step 4 reads.
        env["STUB_STATUS_FILE"] = str(stub_capture / sub / "recorder.status")
    r = subprocess.run(["bash"], input=block, env=env, cwd=cwd,
                       capture_output=True, text=True, timeout=timeout)
    return r, stub_capture / sub / "recording.cast"


def _run_capture_block(name, mode, tmp_path, target=False, env_extra=None):
    """Run a recipe's whole capture block against stub tmux/pm."""
    return _run_block(_scaffold_block(_recipe_text(name)), mode, tmp_path,
                      target=target, env_extra=env_extra)


# The block a worker pastes on its own to end the recording: step 4 of the
# CLI scaffold (step 3 is what drives an interactive shell, so that block
# cannot run as one paste) and step 5 of the tmux recipe (the scenario's
# ``pm tui send`` calls sit between it and the recorder start).
_STOP_MARKERS = {
    "cli-recording.md": "# 4. Wait (bounded) for asciinema to exit",
    "tmux-screen-recording.md": "# 5. End the recording",
}


def _stop_block(name):
    raw = _scaffold_block(_recipe_text(name))
    return raw[raw.index(_STOP_MARKERS[name]):]


def _driving_block():
    """The tmux recipe's scenario-driving step (``# 4.`` … ``# 5.``).

    A scenario supplies its own driving commands, so this is the shape a
    worker pastes on its own — with no ``$TARGET`` from step 1.
    """
    raw = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
    return raw[raw.index("# 4."):raw.index("# 5.")]


def _step_two_block():
    """The tmux recipe's transcript-pipe step (``# 2.`` … ``# 3.``).

    Pasted on its own when a run re-attaches its transcript to the same
    session, which is also when an empty ``$TARGET`` would resolve to whatever
    session tmux treats as current.
    """
    raw = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
    return raw[raw.index("# 2."):raw.index("# 3.")]


def _step_three_block():
    """The tmux recipe's recorder-start step (``# 3.`` … ``# 4.``).

    Pasted on its own when a run restarts its recorder, which is the same
    paste-alone case steps 2, 4 and 5 re-derive ``$TARGET`` for.
    """
    raw = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
    return raw[raw.index("# 3."):raw.index("# 4.")]


def _step_zero_block():
    """The tmux recipe's create-and-clear step (``# 0.`` … ``# 1.``).

    The block that owns the capture directory: it creates it, refuses one it
    cannot write, and clears the shared recorder session and the previous
    run's files.
    """
    raw = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
    return raw[:raw.index("# 1. Start")]


def _cli_preamble_block():
    """The CLI recipe's capture-section preamble (create and clear the dir).

    The first fenced block under ``## Capture``: the one a worker following the
    recipe top-down pastes before any of the recording forms. The no-TTY
    scaffold repeats its steps for a worker who pastes the scaffold whole, so
    the preamble carries its own copy of the guards.
    """
    section = _recipe_text("cli-recording.md").split(
        "## Capture", 1)[1].split("## Render to video", 1)[0]
    return re.findall(r"```[a-z]*\n(.*?)```", section, re.S)[0]


class TestCaptureFlowExecution:
    """Run the capture block end to end against a stub tmux server."""

    def test_cli_recording_completes(self, tmp_path):
        r, cast = _run_capture_block("cli-recording.md", "oneshot", tmp_path)
        assert r.returncode == 0, r.stderr
        assert cast.stat().st_size > 0, "the completed cast is missing"

    def test_cli_recording_completes_with_remain_on_exit(self, tmp_path):
        """A session kept alive by remain-on-exit must not look like a recorder.

        `set -g remain-on-exit on` (a common way to keep a crashed pane
        visible — this project's own QA notes prescribe it) keeps the `rec`
        session after its only pane's command returns. The stop wait's
        `has-session` handle then never ends: a finished one-shot recording
        ran out the bound and was reported as "the recording is still
        running", with a retry that fails the same way. The pane's death
        (`#{pane_dead}`) is the completion signal; the session ending is only
        its usual consequence.
        """
        r, cast = _run_capture_block(
            "cli-recording.md", "oneshot", tmp_path,
            env_extra={"STUB_REMAIN": "1"})
        assert r.returncode == 0, (
            "a finished recording was reported as still running because the "
            "session outlived its pane: " + r.stderr)
        assert cast.stat().st_size > 0, "the completed cast is missing"

    @pytest.mark.parametrize("mode,message", [
        ("oneshot", None),
        ("norec", "did not start within"),
        ("emptycast", "asciinema wrote no cast"),
        ("nostatus", "recorder status is missing"),
        ("badstatus", "asciinema exited 137"),
    ], ids=["success", "readiness-timeout", "no-cast", "no-status",
            "bad-status"])
    def test_cli_run_leaves_no_scaffold_session_behind(self, mode, message,
                                                       tmp_path):
        """Every exit path has to end the `rec` session it started.

        The scaffold runs on the host-shared ``-L scaffold`` socket, and
        ``remain-on-exit on`` — which this project's own QA notes prescribe —
        keeps ``rec`` after its only pane's command returns. Each failure
        branch therefore ends the server it started (the cast-missing one
        says "do not leave `rec` behind"), and the success path does the same
        as its last statement. No case observed any of it: deleting the
        success-path ``kill-server``, the readiness-timeout one, or either
        stop-path one left the whole file green (351 passed, verified by
        mutation), so a run that failed or finished could leave the scaffold
        session on the host for the next capture to clear. ``STUB_REMAIN`` is
        what makes the session outlive its pane; without it the stub's pane
        death removes the session and the assertion could not see the
        cleanup.
        """
        r, _cast = _run_capture_block(
            "cli-recording.md", mode, tmp_path,
            env_extra={"STUB_REMAIN": "1"})
        if message is None:
            assert r.returncode == 0, r.stderr
        else:
            assert r.returncode != 0, r.stderr
            assert message in r.stderr, (
                f"{mode}: the run failed somewhere other than the branch "
                "under test, so its cleanup line is not exercised: "
                + r.stderr)
        assert not (tmp_path / "state" / "rec").exists(), (
            f"{mode}: the run left the scaffold's `rec` session behind, so "
            "the host-shared socket carries a dead recorder into the next "
            "capture")

    def test_cli_recorder_dying_with_remain_on_exit_ends_the_readiness_wait(
            self, tmp_path):
        """A dead pane ends the readiness wait, even when its session lingers.

        Step 2's wait is the cast *or* the session ending, and `set -g
        remain-on-exit on` keeps the session after its only pane's command
        returns. A recorder that died at startup (asciinema refused to start,
        a broken `-c` command) therefore left the wait polling a live session
        with no cast: it burned the whole readiness bound and reported
        "recorder did not start within 30s" — a start timeout for a recorder
        that started and exited, while asciinema's own error sat in the
        `recorder-stderr.log` both messages point at. The pane's state
        (`#{pane_dead}`) is the handle step 4's stop wait already reads; with
        it, step 4 names the missing cast, which is the actual failure.
        """
        r, cast = _run_capture_block(
            "cli-recording.md", "dies", tmp_path,
            env_extra={"STUB_REMAIN": "1"})
        assert r.returncode != 0, "a dead recorder was reported as a start"
        assert "asciinema wrote no cast" in r.stderr, (
            "a recorder that started and died is reported as one that never "
            "started: " + r.stderr)
        assert "did not start within" not in r.stderr, (
            "the readiness wait ran out its bound on a recorder that had "
            "already exited: " + r.stderr)
        assert not cast.exists()

    def test_cli_recorder_that_never_writes_a_cast_fails(self, tmp_path):
        """A recorder that starts but records nothing is a failure, not a hang.

        The message names the pane the failing wait saved, so the file has to
        be there with what the recorder drew — the rule the tmux recipe's
        readiness-timeout case pins. Nothing asserted the save itself: the
        message text was pinned, so deleting the ``capture-pane`` line left
        the whole file green (211 passed) and the message then pointed at a
        file nothing writes.
        """
        r, cast = _run_block(
            _scaffold_block(_recipe_text("cli-recording.md")), "norec",
            tmp_path, state_files={"pane": "recorder output\n"})
        assert r.returncode != 0, "an empty recording was reported as success"
        assert "did not start within" in r.stderr, r.stderr
        assert "recorder-pane.log" in r.stderr, (
            "the readiness failure does not say where the pane was saved: "
            + r.stderr)
        assert not cast.exists()
        log = cast.parent / "recorder-pane.log"
        assert log.exists(), "the failing wait left no pane evidence"
        assert "recorder output" in log.read_text(), (
            "the saved pane does not hold what the recorder drew")

    def test_cli_readiness_timeout_names_a_pane_it_could_not_save(self, tmp_path):
        """The CLI readiness save must not claim a file nothing wrote.

        Same state as the tmux case, one recipe over: the block's own
        capture-directory guard passed when it ran, and the timeout branch
        writes the pane a whole bound later. The ``|| true`` save made the
        message's "the pane is saved in …" unconditional (R87 fixed the stop
        timeout this way; this is the readiness branch beside it).
        """
        r, cast = _run_block(
            _scaffold_block(_recipe_text("cli-recording.md")), "nopane",
            tmp_path, state_files={"pane": "recorder output\n"})
        assert r.returncode != 0, r.stderr
        assert "did not start within" in r.stderr, r.stderr
        assert "could not be saved" in r.stderr, (
            "the readiness failure claims a save that did not land: "
            + r.stderr)
        assert "is saved in" not in r.stderr, (
            "the readiness failure claims the pane was saved: " + r.stderr)
        # The redirect creates the file before `capture-pane` fails, so it can
        # be there — but it holds nothing, which is what "could not be saved"
        # says.
        log = cast.parent / "recorder-pane.log"
        assert not log.exists() or log.stat().st_size == 0, (
            "the failing wait saved pane content it said it could not save")

    @pytest.mark.parametrize("name", RECIPES)
    def test_a_failed_capture_leaves_no_previous_video(self, name, tmp_path):
        """A capture that fails must not leave the earlier run's video.

        The render step clears the video pair before rendering, but a capture
        that fails exits before that step ever runs. Verified with the pre-fix
        blocks: an earlier ``recording.mp4`` and intermediate gif seeded in
        the capture directory survived the failed run, so the directory held
        no cast at all but still held a video the manifest and the report
        would present as this run's recording — the stale-cast bug one step
        earlier.

        The gif seeded here is the one the render block *writes*
        (``$cast.gif`` → ``recording.cast.gif``). The pre-fix cleanup named
        ``recording.gif``, so seeding that name proved nothing: the run
        cleared a file nothing writes and left the real intermediate behind
        (verified live in this container).

        The interrupted render's partial (``recording.mp4.partial.mp4``) is
        seeded with them for the same reason: ``render_cast`` renames it only
        after a successful encode, so a render killed before the rename
        leaves it in the capture directory, and this is the one path that
        clears it before a later capture fails.
        """
        raw = _scaffold_block(_recipe_text(name))
        cast_rel = re.search(r"^cast=(\S+)$", _render_block(name), re.M).group(1)
        intermediate = Path(cast_rel).name + ".gif"
        partial = Path(cast_rel).stem + ".mp4.partial.mp4"
        r, cast = _run_block(
            raw, "norec", tmp_path, target=True,
            files={"recording.mp4": "previous run",
                   intermediate: "previous gif",
                   partial: "previous partial"})
        cap = cast.parent
        assert r.returncode != 0, r.stderr
        assert not (cap / "recording.mp4").exists(), (
            f"{name}: a failed capture left the previous run's recording.mp4 "
            "as this capture's only video")
        assert not (cap / intermediate).exists(), (
            f"{name}: a failed capture left the previous run's "
            f"{intermediate} (the intermediate the render block writes) "
            "behind")
        assert not (cap / partial).exists(), (
            f"{name}: a failed capture left an interrupted render's "
            f"{partial} behind, so a later capture presents it as this run's "
            "evidence")

    @pytest.mark.parametrize("name", RECIPES)
    def test_a_failed_capture_leaves_no_previous_manifest(self, name, tmp_path):
        """The stale manifest is what makes the stale files look deliberate.

        Seeded with the previous run's ``manifest.md`` and a previous video,
        and forced to fail at the recorder, the directory ends with the video
        gone (step 0) — but before this case's fix the previous run's manifest
        was still there, its ``## Files`` section naming the cast and the mp4
        that had just been deleted. That is the manifest-and-directory
        disagreement the produced-files rules exist to prevent, in the one
        file a reviewer reads to interpret the rest.
        """
        raw = _scaffold_block(_recipe_text(name))
        r, cast = _run_block(
            raw, "norec", tmp_path, target=True,
            files={"manifest.md": "previous run's manifest\n",
                   "recording.mp4": "previous video"})
        assert r.returncode != 0, r.stderr
        cap = cast.parent
        assert not (cap / "recording.mp4").exists(), (
            f"{name}: the fixture did not exercise the stale-video cleanup")
        assert not (cap / "manifest.md").exists(), (
            f"{name}: a failed capture left the previous run's manifest.md in "
            "the capture directory, where it describes a run whose cast and "
            "video this run just deleted")

    def test_cli_failed_capture_leaves_no_previous_transcript(self, tmp_path):
        """The `tee` fallback's transcript must not outlive a later run.

        ``tee`` truncates, so the fallback itself never appends — but a run
        that takes the cast path writes no transcript at all, and the
        produced-files list names ``transcript.log``, so the earlier fallback
        run's output would be read as this run's. The tmux recipe clears its
        transcript in step 0 for the same reason.
        """
        raw = _scaffold_block(_recipe_text("cli-recording.md"))
        r, cast = _run_block(raw, "norec", tmp_path,
                             files={"transcript.log": "previous transcript"})
        assert r.returncode != 0, r.stderr
        assert not (cast.parent / "transcript.log").exists(), (
            "a failed cli capture left the previous run's transcript.log, "
            "which the produced-files list names")

    def test_cli_stop_timeout_saves_the_pane(self, tmp_path):
        """A failing wait must leave the pane where its message says it is.

        Failure paths that tear the scaffold server down do so after saving
        the pane, so a message that says "check the pane" does not point at
        evidence that no longer exists — verified live: the readiness timeout
        printed exactly that and the next line killed the server, after which
        ``capture-pane`` answered "no server running". The pane is saved
        before any teardown and the message names the file.
        """
        r, cast = _run_capture_block(
            "cli-recording.md", "stuck", tmp_path,
            env_extra={"RECORDER_STOP_TIMEOUT": "2"})
        assert r.returncode != 0, r.stderr
        assert "did not exit within" in r.stderr, r.stderr
        assert "recorder-pane.log" in r.stderr, (
            "the stop failure does not say where the pane was saved: "
            + r.stderr)
        log = cast.parent / "recorder-pane.log"
        assert log.exists(), "the failing wait left no pane evidence"
        assert "TUI drawn" in log.read_text(), (
            "the saved pane does not hold what the recorder drew")

    def test_cli_stop_timeout_leaves_the_recording_for_a_retry(self, tmp_path):
        """The timeout must not destroy the recording its remedy retries.

        The bound is a hang detector, not a time limit on the recorded work
        (the step says so), and its message tells the worker to re-run with a
        larger ``RECORDER_STOP_TIMEOUT``. The block used to kill the scaffold
        server on the way out, so that remedy could not work: verified live
        with a one-shot ``sleep 6`` recorded and ``RECORDER_STOP_TIMEOUT=1``,
        the timeout killed the pane, and the re-run with 60 answered
        "recorder status is missing" — the recording was gone. The recorder
        has to survive the timeout so the step can be re-run against it.
        """
        r, cast = _run_block(
            _stop_block("cli-recording.md"), "stuck", tmp_path,
            sessions=("rec",),
            files={"recording.cast": '{"version": 2}\n'},
            state_files={"pane": "TUI drawn\n"},
            env_extra={"RECORDER_STOP_TIMEOUT": "2"})
        assert r.returncode != 0, r.stderr
        assert "still running" in r.stderr, (
            "the timeout does not say the recording survived: " + r.stderr)
        assert (tmp_path / "state" / "rec").exists(), (
            "the stop timeout killed the recording it tells the worker to "
            "re-run this step against")
        assert (cast.parent / "recorder-pane.log").exists()

    def test_cli_stop_timeout_names_a_pane_it_could_not_save(self, tmp_path):
        """A save the directory refuses must not be reported as saved.

        Step 4's guard requires ``-d``/``-x`` but not ``-w`` — a capture
        directory that became read-only must not refuse a finish that can
        still be validated (R84) — and the timeout path saves the pane into
        that directory. With a mode-500 directory the redirect fails, so no
        ``recorder-pane.log`` exists; the shipped message still said "the pane
        is saved in …", a failure pointing at evidence that does not exist
        (verified in this container: the shell answered "Permission denied",
        the file was absent, and the message named it as saved).
        """
        if not hasattr(os, "geteuid") or os.geteuid() == 0:
            pytest.skip("root bypasses the directory permission bits")
        cap = tmp_path / "cap"
        run = cap / "run"
        run.mkdir(parents=True)
        run.chmod(0o500)
        try:
            r, _cast = _run_block(
                _stop_block("cli-recording.md"), "stuck", tmp_path,
                sessions=("rec",), capture=cap,
                env_extra={"RECORDER_STOP_TIMEOUT": "2"})
        finally:
            run.chmod(0o700)
        assert r.returncode != 0, r.stderr
        assert "did not exit within" in r.stderr, r.stderr
        assert "could not be saved" in r.stderr, (
            "the timeout does not say the pane save failed: " + r.stderr)
        assert "the pane is saved" not in r.stderr, (
            "the timeout claims the pane was saved although the capture "
            "directory refused the write: " + r.stderr)
        assert "recorder-pane.log" in r.stderr, r.stderr
        assert not (run / "recorder-pane.log").exists(), (
            "the read-only capture directory somehow holds the pane log")

    def test_cli_mistyped_bound_leaves_the_recording_for_a_retry(self, tmp_path):
        """A typo in the bound is not a reason to destroy the recording.

        Same remedy, same failure: the validation branch killed the scaffold
        server and then said "e.g. RECORDER_STOP_TIMEOUT=120", so the re-run
        it asked for met a torn-down pane. Nothing has been waited on yet at
        that point, so the recording is intact and the corrected value can be
        applied to it.
        """
        r, _cast = _run_block(
            _stop_block("cli-recording.md"), "stuck", tmp_path,
            sessions=("rec",),
            files={"recording.cast": '{"version": 2}\n'},
            env_extra={"RECORDER_STOP_TIMEOUT": "2m"}, timeout=20)
        assert r.returncode != 0, r.stderr
        assert "RECORDER_STOP_TIMEOUT must be whole seconds" in r.stderr, (
            "the bad bound is not named: " + r.stderr)
        assert "still running" in r.stderr, (
            "the refusal does not say the recording survived: " + r.stderr)
        assert (tmp_path / "state" / "rec").exists(), (
            "a mistyped bound killed the recording the corrected value was "
            "meant to be applied to")

    def test_cli_stop_refuses_a_bound_too_large_to_represent(self, tmp_path):
        """A whole number that wraps is not a bound either.

        The digit check rejects ``2m``, but bash's arithmetic is 64-bit: a
        value with more than 18 digits wraps, and the wrap can land on a
        deadline far in the future. Verified in this container with the stub
        harness: the shipped block was still waiting at 8 s with
        ``RECORDER_STOP_TIMEOUT=99999999999999999999`` — the unbounded wait
        R21 removed, reintroduced by a value the validation accepts. The step
        must refuse it and leave the recording running for the corrected
        retry.
        """
        try:
            r, _cast = _run_block(
                _stop_block("cli-recording.md"), "stuck", tmp_path,
                sessions=("rec",),
                files={"recording.cast": '{"version": 2}\n'},
                env_extra={
                    "RECORDER_STOP_TIMEOUT": "99999999999999999999"},
                timeout=20)
        except subprocess.TimeoutExpired:
            pytest.fail("the stop block hung on an overflowing "
                        "RECORDER_STOP_TIMEOUT instead of failing")
        assert r.returncode != 0, r.stderr
        assert "RECORDER_STOP_TIMEOUT is too large" in r.stderr, (
            "the unrepresentable bound is not named: " + r.stderr)
        assert "still running" in r.stderr, (
            "the refusal does not say the recording survived: " + r.stderr)
        assert (tmp_path / "state" / "rec").exists(), (
            "an overflowing bound killed the recording the corrected value "
            "was meant to be applied to")

    def test_cli_stop_refuses_a_non_numeric_timeout(self, tmp_path):
        """A mistyped RECORDER_STOP_TIMEOUT must fail, not remove the bound.

        Verified in a real interactive bash: `$(( … + 2m ))` fails, leaves
        `deadline` empty, and the shell *carries on* (only a scripted run
        exits on that error), so the deadline check below is always false and
        the stop wait never ends — the unbounded wait this step exists to
        remove, reintroduced by the knob the recipe tells workers to raise.
        The block has to validate the value and say what is wrong.
        """
        try:
            r, _cast = _run_block(
                _stop_block("cli-recording.md"), "stuck", tmp_path,
                sessions=("rec",),
                files={"recording.cast": '{"version": 2}\n'},
                state_files={"pane": "TUI drawn\n"},
                env_extra={"RECORDER_STOP_TIMEOUT": "2m"}, timeout=20)
        except subprocess.TimeoutExpired:
            pytest.fail("the stop block hung on a non-numeric "
                        "RECORDER_STOP_TIMEOUT instead of failing")
        assert r.returncode != 0, (
            "the stop block accepted a non-numeric RECORDER_STOP_TIMEOUT")
        assert "RECORDER_STOP_TIMEOUT must be whole seconds" in r.stderr, (
            "the bad bound is not named: " + r.stderr)

    def test_cli_recorder_that_dies_without_a_cast_fails(self, tmp_path):
        """asciinema failing to start must not pass as a finished recording."""
        r, cast = _run_capture_block("cli-recording.md", "dies", tmp_path)
        assert r.returncode != 0, "a recorder that never ran was reported as success"
        assert "asciinema wrote no cast" in r.stderr, r.stderr
        assert not cast.exists()

    def test_cli_recorder_killed_mid_recording_fails(self, tmp_path):
        """A killed recorder leaves a non-empty cast; `test -s` cannot tell.

        Reproduced live: a one-shot recording whose asciinema was SIGKILLed
        1 s into a 60 s command left a 117-byte cast (header only) and the
        previous scaffold reported success. asciinema's own exit status is
        the only handle the CLI pane has — the tmux recipe has the target
        session as its witness, this one does not — so a non-zero status has
        to fail the run even though the cast looks fine.
        """
        r, cast = _run_capture_block("cli-recording.md", "badstatus", tmp_path)
        assert cast.stat().st_size > 0, (
            "the fixture did not reproduce the false-success precondition "
            "(a non-empty cast from a killed recorder)")
        assert r.returncode != 0, (
            "a recorder that was killed mid-recording was reported as a "
            "successful recording")
        assert "incomplete" in r.stderr, r.stderr
        assert "137" in r.stderr, (
            "the failure does not say how the recorder ended: " + r.stderr)

    @pytest.mark.parametrize("name", RECIPES)
    def test_a_zero_byte_cast_is_not_a_recording(self, name, tmp_path):
        """The cast check is `test -s`, and an existence check cannot tell.

        A recorder can report success — asciinema's own exit status is 0, so
        the status check below passes — and still leave no usable cast: the
        header write can fail (a full disk, or a cast path that became
        unwritable after the recorder started) while the status lands. Both
        recipes guard that with `test -s`, and nothing exercised the
        difference: weakening it to `test -e` left the whole file green (305
        passed, verified by mutation), so a 0-byte cast would have been
        accepted and the run reported as a finished recording with no replay
        in it. The same "an artifact that exists but is empty is not an
        input" rule the cast/gif/webm checks follow.
        """
        r, cast = _run_capture_block(name, "emptycast", tmp_path, target=True)
        assert cast.exists() and cast.stat().st_size == 0, (
            "the fixture did not produce the 0-byte cast the check is for")
        assert r.returncode != 0, (
            f"{name}: a 0-byte cast was reported as a finished recording")
        assert "asciinema wrote no cast" in r.stderr, r.stderr

    def test_cli_missing_recorder_status_fails(self, tmp_path):
        """No status file means the pane died before asciinema returned.

        The pane's shell writes the status after asciinema exits, so a file
        that was never written means the pane (or the whole server) was torn
        down underneath a live recorder — the recording did not finish, and
        the header-only cast must not be reported as one.
        """
        r, cast = _run_capture_block("cli-recording.md", "nostatus", tmp_path)
        assert cast.stat().st_size > 0, "the fixture left no cast to misread"
        assert r.returncode != 0, (
            "a recording with no completion signal was reported as a success")
        assert "incomplete" in r.stderr, r.stderr

    @pytest.mark.parametrize("name,mode", [
        ("tmux-screen-recording.md", "detachnostatus"),
        ("cli-recording.md", "nostatus"),
    ])
    def test_a_stale_recorder_status_is_not_read_as_this_runs(self, name, mode,
                                                              tmp_path):
        """An earlier run's recorder status must not pass the exit-status check.

        The status file is asciinema's *own* exit status, and the completion
        check fails on a *missing* one — so a run whose pane was torn down
        before asciinema returned is only distinguishable from a finished
        recording if the earlier run's file is gone. That is why step 0 clears
        it, and why the check is worthless without the clear: seed the
        previous run's ``0``, run the recipe's own block with a recorder that
        never writes one, and the run must fail "recorder status is missing".

        Without the clear the seeded file survives and the check reads the
        previous run's 0, so the run exits 0 — a completed-looking recording
        of nothing, the same false pass as a stale cast one file over
        (verified in this harness: mode ``detachnostatus``/``nostatus`` with a
        seeded ``recorder.status`` of 0 exits 0 against the recipe with that
        one ``rm`` argument removed, and 1 with it). Both modes end the
        recording legitimately — the detach in the tmux recipe, the one-shot
        command in the CLI — so the run reaches the status check rather than
        failing earlier for an unrelated reason.
        """
        raw = _scaffold_block(_recipe_text(name))
        r, _cast = _run_block(raw, mode, tmp_path, target=True,
                              files={"recorder.status": "0\n"})
        assert r.returncode != 0, (
            f"{name}: the run passed on the earlier run's recorder.status, so "
            "a recorder torn down before asciinema returned was reported as a "
            "finished recording: " + r.stderr)
        assert "recorder status is missing" in r.stderr, (
            f"{name}: the run failed for another reason: " + r.stderr)

    @pytest.mark.parametrize("name", RECIPES)
    def test_an_empty_recorder_status_is_not_an_exit_status(self, name,
                                                            tmp_path):
        """A 0-byte status file holds no status, so it is not one to report.

        The status file is the completion handle, and the pane's shell writes
        it as ``echo $? > recorder.status``: the redirect creates (truncates)
        the file when the shell runs that statement, and the status lands a
        moment later. A kill in that window (a concurrent capture's step 0
        ending this recorder, a supervisor, an OOM kill) — or a write that
        cannot complete, e.g. a full disk — leaves a **0-byte** file. The
        check read it with ``cat``, which answers 0 for an empty file, so the
        ``[ "$status" = 0 ]`` comparison fired and the run printed
        ``asciinema exited  — the cast is incomplete``: an exit status the
        file does not hold, for exactly the state the missing-file branch
        exists to name. Verified in this container: the recipe's own pane
        command under a write limit leaves a 0-byte ``recorder.status``, and
        the status check on that file prints that message. The empty shape is
        the "an artifact that exists but is empty is not an input" rule the
        cast/gif/webm/driver checks already follow.

        Both recipes reach the status check: the tmux recipe's detach ends
        its recorder, and the CLI's one-shot command ends its session, so the
        run fails on the status rather than earlier for an unrelated reason.
        """
        raw = _scaffold_block(_recipe_text(name))
        r, _cast = _run_block(raw, "emptystatus", tmp_path, target=True)
        assert r.returncode != 0, (
            f"{name}: a recording whose status file holds no status passed")
        assert "recorder status is missing" in r.stderr, (
            f"{name}: an empty status file is not reported as a missing "
            "status, so the worker is told an exit status the file does not "
            "hold: " + r.stderr)
        assert "asciinema exited" not in r.stderr, (
            f"{name}: the failure names an exit status it does not have: "
            + r.stderr)

    def test_tmux_recording_completes(self, tmp_path):
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "ok", tmp_path, target=True)
        assert r.returncode == 0, r.stderr
        assert cast.stat().st_size > 0, "the completed cast is missing"
        assert "can't find session" not in r.stderr, (
            "a clean run prints a tmux error while stopping the transcript pipe")

    def test_tmux_recording_completes_with_remain_on_exit(self, tmp_path):
        """A session kept alive by remain-on-exit must not look like a recorder.

        `set -g remain-on-exit on` (a common way to keep a crashed pane
        visible — this project's own QA notes prescribe it) keeps the recorder
        session after the detach ends its only pane's command. Step 5's wait
        is `has-session`, which then never ends: a complete recording (cast
        flushed, status 0, transcript written) was killed at the 30 s bound
        and reported as "the detach key did not end it ... incomplete". The
        pane's death (`#{pane_dead}`) is the flush signal; the session ending
        is only its usual consequence.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "ok", tmp_path, target=True,
            env_extra={"STUB_REMAIN": "1"})
        assert r.returncode == 0, (
            "a finished recording was killed at the stop bound because the "
            "session outlived its pane: " + r.stderr)
        assert cast.stat().st_size > 0, "the completed cast is missing"

    @pytest.mark.parametrize("mode,message", [
        ("ok", None),
        ("norec", "did not come up within"),
        ("stuck", "did not exit within"),
        ("dies", "recorder exited before it drew"),
        ("nostatus", "recorder exited before it drew"),
        ("remaindied", "recorder exited while the TUI was still running"),
        ("emptycast", "asciinema wrote no cast"),
        ("detachnostatus", "recorder status is missing"),
        ("detachbothbad", "asciinema exited 137"),
        ("detachfail", "recorder exited before the detach"),
        ("emptytranscript", "transcript.log is empty"),
    ], ids=["success", "readiness-timeout", "stop-timeout",
            "recorder-died-before-drawing", "recorder-exited-at-start",
            "recorder-died-mid-scenario", "no-cast", "no-status",
            "bad-status", "detach-failed", "no-transcript"])
    def test_tmux_run_leaves_no_recorder_session_behind(self, mode, message,
                                                        tmp_path):
        """A run that ends must not leave its recorder session on the server.

        ``pm-recorder`` is the one name every capture on a server shares, and
        ``remain-on-exit on`` keeps the session after its only pane's command
        returns — exactly the state a successful run ends in, the state both
        timeout branches end in (a recorder that never drew, a detach that
        never ended it), and the state every failure branch ends in, because
        the pane has returned (a recorder that died at startup, died
        mid-scenario, or finished with no cast, no status or no transcript).
        Step 5's last statement removes it ("already gone if it exited") and
        the timeout branches kill the session they started; the *failure*
        branches originally did not, so a failed run left a dead
        ``pm-recorder`` for the next capture to clear (the leftover state R96
        exists to handle). ``STUB_REMAIN`` is what leaves the session after
        its pane in every mode, so the assertion can see the cleanup.
        """
        env = {"STUB_REMAIN": "1"}
        r, _cast = _run_capture_block(
            "tmux-screen-recording.md", mode, tmp_path, target=True,
            env_extra=env)
        if message is None:
            assert r.returncode == 0, r.stderr
        else:
            assert r.returncode != 0, r.stderr
            assert message in r.stderr, (
                f"{mode}: the run failed somewhere other than the branch "
                "under test, so its cleanup line is not exercised: "
                + r.stderr)
        assert not (tmp_path / "state" / "pm-recorder").exists(), (
            f"{mode}: the run left its pm-recorder session on the server, "
            "so the next capture finds a recorder it never started")

    def test_tmux_failed_attach_with_remain_on_exit_is_not_readiness(
            self, tmp_path):
        """A dead pane is not a drawn TUI, even when its session lingers.

        A failed attach draws its own error and exits ~25 ms later. The
        settle check exists to keep that error text from counting as
        readiness, and it asks `has-session` — which `remain-on-exit on` keeps
        true after the pane's command returns. The dead pane then passed the
        settle check, step 4's sends were accepted by a pane that no longer
        exists, and step 5 ran out its bound. The pane's own state
        (`#{pane_dead}`) is the handle; without it the error cast was one
        step from being reported as this run's recording.
        """
        r, _ = _run_capture_block(
            "tmux-screen-recording.md", "failedattach", tmp_path, target=True,
            env_extra={"STUB_REMAIN": "1"})
        assert r.returncode != 0, r.stderr
        assert "recorder exited before it drew" in r.stderr, (
            "a failed attach whose session was kept alive by remain-on-exit "
            "was not named as a recorder that never drew: " + r.stderr)

    def test_tmux_recorder_dying_with_remain_on_exit_names_the_right_cause(
            self, tmp_path):
        """A dead recorder is "exited while the TUI was still running".

        Step 5's first branch tells a recorder that died mid-scenario from one
        whose recording already ended by asking `has-session`, and
        `remain-on-exit on` keeps that answer true for a pane whose command
        has returned. The step then sent the detach into a dead pane (which
        real tmux accepts and returns 0 for) and ran out its bound, reporting
        "the detach key did not end it" for a recorder that had already died —
        the wrong cause, on a failure that is otherwise correct.
        """
        r, _ = _run_capture_block(
            "tmux-screen-recording.md", "remaindied", tmp_path, target=True,
            env_extra={"STUB_REMAIN": "1"})
        assert r.returncode != 0, r.stderr
        assert "recorder exited while the TUI was still running" in r.stderr, (
            "a recorder that died mid-scenario was reported as one the detach "
            "could not end: " + r.stderr)

    def test_tmux_recorder_dying_before_drawing_with_remain_on_exit_fails(
            self, tmp_path):
        """The readiness loop's own pane check has to stand on its own.

        A recorder that dies before drawing leaves a dead pane and, with
        `remain-on-exit on`, a session that `has-session` still answers for.
        The settle check below reads the pane too, but it runs only after
        pane *content* appears — which a recorder that died before drawing
        never writes. Without the loop's own `#{pane_dead}` half the run
        burns the whole readiness bound and reports "recorder did not come up
        within 30s" for a recorder that started and exited, instead of the
        "recorder exited before it drew" the same state gets on a server
        without that option.
        """
        r, _ = _run_capture_block(
            "tmux-screen-recording.md", "dies", tmp_path, target=True,
            env_extra={"STUB_REMAIN": "1"})
        assert r.returncode != 0, r.stderr
        assert "recorder exited before it drew" in r.stderr, (
            "a recorder that died before drawing was reported as one that "
            "never came up: " + r.stderr)
        assert "did not come up within" not in r.stderr, (
            "the readiness loop ran out its bound on a dead pane whose "
            "session remain-on-exit kept: " + r.stderr)

    def test_step_one_refuses_an_empty_target(self, tmp_path):
        """`pm session name` printing nothing must stop step 1, not the wait.

        Step 1's readiness wait is ``has-session -t "=$TARGET"``, and with an
        empty target that is ``-t "="`` — which can never match — so the run
        would burn the whole deadline and report "pm session  did not appear
        within 60s" for a `pm` that is not on PATH (or a `pm session name`
        that failed). Steps 2, 4 and 5 each refuse an empty target, and their
        guards are execution-tested; step 1's identical guard had no case, so
        deleting it left the file green and turned a precise, immediate
        failure into a slow one that names an empty session.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "ok", tmp_path,
            env_extra={"STUB_PM_NAME": ""})
        assert r.returncode != 0, (
            "step 1 ran with no target session, so its wait polls `-t \"=\"` "
            "until the deadline")
        assert "pm session name printed nothing" in r.stderr, r.stderr
        assert "did not appear within" not in r.stderr, (
            "an empty target is reported as a pm session that never started "
            "instead of as a `pm session name` that printed nothing: "
            + r.stderr)
        assert not cast.exists()

    def test_tmux_readiness_wait_requires_the_exact_session(self, tmp_path):
        """``has-session -t <name>`` is not exact: tmux falls back to a prefix.

        Verified on tmux 3.2a: with only ``pm-test~1`` on the server,
        ``has-session -t pm-test`` exits 0. pm creates exactly those sessions —
        a grouped ``<base>~1``/``~2`` per extra co-viewing client — so the
        readiness wait passed on the grouped session while ``pm session`` had
        not created the target at all. The run then recorded that session,
        exited 0 and reported a capture of a session pm never started
        (verified live: rc 0, cast, ``recorder.status`` 0, transcript, with
        ``pm-test~1`` the only session on the server), and the step-1 failure
        path could not fire. The wait has to ask for the exact session.
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")), "ok",
            tmp_path, sessions=("pm-test~1",))
        assert r.returncode != 0, (
            "the readiness wait passed on the grouped session pm-test~1 while "
            "the target session did not exist, so the run recorded and "
            "reported a session pm never created")
        assert "did not appear within" in r.stderr, r.stderr

    def test_step_two_refuses_a_target_that_is_not_an_exact_session(
            self, tmp_path):
        """A bare target is prefix-matched, so a missing one is not a no-op.

        Step 2 reads and writes the capture-directory claim on ``$TARGET``.
        With only ``pm-test~1`` on the server, a bare ``-t pm-test`` resolved
        to the grouped session (verified on tmux 3.2a), so the claim landed
        there — and once the real session exists, exact match wins and that
        claim is invisible, which is the two-runs-one-directory collision the
        claim exists to prevent. ``show-options``/``set-option`` do not accept
        ``=``, so the step asserts the exact session first.
        """
        r, _cast = _run_block(_step_two_block(), "ok", tmp_path,
                              sessions=("pm-test~1",))
        assert r.returncode != 0, (
            "step 2 claimed a capture directory on the grouped session "
            "pm-test~1 while the target session did not exist")
        assert "no session named exactly" in r.stderr, r.stderr
        assert not (tmp_path / "state" / "claim.pm-test~1").exists(), (
            "step 2 wrote its claim on the prefix-matched grouped session")

    @pytest.mark.parametrize("shape,capdir_mode", [
        ("missing", None),
        ("read-only", 0o500),
        ("read-only", 0o600),
    ], ids=["missing", "no-write-bit", "no-search-bit"])
    def test_step_two_refuses_a_capture_dir_it_cannot_write(
            self, shape, capdir_mode, tmp_path):
        """A claim on a directory nothing can be written into is not a capture.

        Step 2 is pasted on its own when a run re-attaches its transcript, and
        step 0's creation guard does not cover it: a path that is not there
        (a typo in a fresh paste) or a directory that exists and cannot be
        written (``mkdir -p`` answers 0 for it) passed the block, which then
        took the claim and attached a pipe that wrote nothing. The run dies
        two steps later as "recorder exited before it drew — see the cast and
        <capture-dir>/recorder-stderr.log", naming two files that cannot exist
        (verified live on tmux 3.2a: step 2 exited 0 with the claim on the
        session and no transcript written, and step 3 printed exactly that
        message with the cast, the stderr log and the status file all absent).
        Refuse it here, before the claim: a claim on an unusable directory is
        a collision the next attempt has to clear by hand.

        The directory that exists and cannot be written comes in two
        permission shapes: mode 500 has no write bit, and mode 600 has the
        write bit and no search bit — only the guard's ``-x`` half sees the
        second, and without it the claim is taken and the pipe attached
        exactly as for a usable directory.
        """
        capture = tmp_path / "missing" / "cap"
        if shape == "read-only":
            if not hasattr(os, "geteuid") or os.geteuid() == 0:
                pytest.skip("root bypasses the directory permission bits")
            capture = tmp_path / "cap"
            capture.mkdir()
            capture.chmod(capdir_mode)
        try:
            r, _cast = _run_block(_step_two_block(), "ok", tmp_path,
                                  target=True, capture=capture)
        finally:
            if capture.exists():
                capture.chmod(0o700)
        assert r.returncode != 0, (
            f"{shape}: step 2 claimed a capture directory nothing can be "
            "written into")
        assert "cannot be written" in r.stderr, r.stderr
        assert str(capture) in r.stderr, (
            "the refusal does not name the capture directory: " + r.stderr)
        assert not (tmp_path / "state" / "claim.pm-test").exists(), (
            f"{shape}: the refused step took the capture-directory claim")
        assert not (tmp_path / "state" / "pipeclaim").exists(), (
            f"{shape}: the refused step attached the transcript pipe")

    @pytest.mark.parametrize("file_mode,message", [
        (0o755, "is not a directory"),
        (0o644, "cannot be written"),
    ], ids=["executable-file", "plain-file"])
    def test_step_two_refuses_a_capture_path_that_is_not_a_directory(
            self, file_mode, message, tmp_path):
        """Step 2's guards are writability, not "is a directory".

        `<capture-dir>` is normally a directory step 0 created, but this step
        is pasted on its own when a run re-attaches its transcript, and its
        guards are ``[ -w ]`` and ``[ -x ]`` — both true for an *executable*
        regular file. A path naming one passed them, the canonicalising ``cd``
        failed, and the run went on with the capture-dir claim taken on the
        file and the transcript pipe attached; the pipe's redirect cannot
        work, so step 5 reported "transcript.log is empty — the pipe-pane
        stream never wrote to it" for a path that is not a directory
        (verified live on tmux 3.2a: step 2 exited 0 with the claim on the
        file and no transcript written). Every other capture-directory guard
        refuses such a path before it acts on it — step 0's ``mkdir -p``, the
        render block's ``[ -d "$cast_dir" ]``, and the web-UI blocks' ``-d``
        — and this is the one pasted alone. A plain (non-executable) file is
        refused by the ``-x`` half already; the executable shape is the one
        that ran on.
        """
        capture = tmp_path / "capfile"
        capture.write_text("not a directory\n")
        capture.chmod(file_mode)
        r, _cast = _run_block(_step_two_block(), "ok", tmp_path, target=True,
                              capture=capture)
        assert r.returncode != 0, (
            f"mode {file_mode:o}: step 2 accepted a capture path that is not "
            "a directory")
        assert message in r.stderr, r.stderr
        assert str(capture) in r.stderr, (
            "the refusal does not name the capture path: " + r.stderr)
        assert not (tmp_path / "state" / "claim.pm-test").exists(), (
            f"mode {file_mode:o}: the refused step took the capture-dir claim")
        assert not (tmp_path / "state" / "pipeclaim").exists(), (
            f"mode {file_mode:o}: the refused step attached the transcript "
            "pipe")

    def test_step_two_refuses_a_relative_capture_dir(self, tmp_path):
        """Step 2's pipe runs in the pm session's directory, not the worker's.

        Step 2 is pasted on its own when a run re-attaches its transcript, and
        the absolute-path guard lived only in step 0. A relative
        ``<capture-dir>`` that exists beside the worker passed the writability
        check, the claim was taken on the worker's canonical absolute path, and
        the pipe's command then ran in the *pm session's* directory, where the
        relative path may not exist at all — verified live on tmux 3.2a: step 2
        exited 0 with the claim on ``…/worker/relcap`` while the session's
        shell answered "cannot create relcap/transcript.log: Directory
        nonexistent". The run then had no transcript anywhere, and step 5
        reported "transcript.log is empty — the pipe-pane stream never wrote to
        it" for a pipe that never had a writable target — the exact failure
        step 0's guard exists to prevent, in the paste a run uses to re-attach.
        Refuse the path before the claim is taken.
        """
        worker = tmp_path / "worker"
        (worker / "relcap").mkdir(parents=True)
        block = _step_two_block().replace("<capture-dir>", "relcap")
        r, _cast = _run_block(block, "ok", tmp_path, target=True,
                              cwd=str(worker))
        assert r.returncode != 0, (
            "step 2 accepted a relative capture directory, so its claim and "
            "the transcript pipe resolve against different directories")
        assert "must be an absolute path" in r.stderr, r.stderr
        assert not (tmp_path / "state" / "claim.pm-test").exists(), (
            "the refused step took the capture-directory claim")
        assert not (tmp_path / "state" / "pipeclaim").exists(), (
            "the refused step attached the transcript pipe")

    def test_step_three_refuses_a_relative_capture_dir(self, tmp_path):
        """Step 3 is pasted alone, and the recorder writes through the path.

        Step 3 re-derives ``$TARGET`` because it is pasted on its own when a
        run restarts its recorder (R82), and the capture directory is the
        other handle that paste resolves for itself: the pane command writes
        the cast, asciinema's stderr log and the status through
        ``<capture-dir>``, and the *stop* step is "usually a fresh shell". A
        relative path therefore writes the recording into the directory step
        3 was pasted from while step 5 reads another, and the run ends with
        "asciinema wrote no cast" for a recording that finished — the exact
        failure step 0's guard exists to prevent, in the paste a run uses to
        restart its recorder. Verified live in this container with the
        recipe's own steps on tmux 3.2a and asciinema 2.1.0: step 3 pasted
        from ``worker/`` with ``relcap`` wrote a 2,676-byte cast and the
        stderr log into ``worker/relcap``, and step 5 pasted from another
        directory with the same relative path exited 1 with "asciinema wrote
        no cast" while the same block with the absolute path exited 0.
        Refuse the path before the recorder session is created.
        """
        calls = tmp_path / "tmux-calls"
        block = _step_three_block().replace("<capture-dir>", "relcap")
        r, _cast = _run_block(
            block, "ok", tmp_path, target=True, capture=Path("relcap"),
            cwd=str(tmp_path), env_extra={"STUB_TMUX_LOG": str(calls)})

        assert r.returncode != 0, (
            "step 3 accepted a relative capture directory, so the recorder "
            "writes the cast where the stop step does not look")
        assert "must be an absolute path" in r.stderr, r.stderr
        assert not calls.exists(), (
            "a step that could not use its capture directory acted on the "
            "recorder session anyway: "
            + (calls.read_text() if calls.exists() else ""))

    def test_tmux_driving_step_refuses_a_relative_capture_dir(self, tmp_path):
        """Step 4's failure path saves the pane into ``<capture-dir>``.

        The driving step is pasted into a fresh shell for every scenario, and
        its ``send_failed`` path saves the recorder pane into the capture
        directory before tearing the recorder down. With a relative path the
        save resolves against that fresh shell, so it either lands somewhere
        the message does not name or fails outright while the message still
        points at ``<capture-dir>/recorder-pane.log`` — verified live in this
        container: pasted from a directory with no ``relcap/``, the save
        answered "relcap/recorder-pane.log: No such file or directory" and
        the failure tore the recorder down anyway. Refuse the path before any
        send, so the block neither drives a TUI nor acts on the recorder it
        cannot report on.
        """
        sends = tmp_path / "sends"
        calls = tmp_path / "tmux-calls"
        block = _driving_block().replace("<capture-dir>", "relcap")
        r, _cast = _run_block(
            block, "ok", tmp_path, target=True, sessions=("pm-recorder",),
            capture=Path("relcap"), cwd=str(tmp_path),
            env_extra={"STUB_TMUX_LOG": str(calls),
                       "STUB_PM_SEND_LOG": str(sends)})

        assert r.returncode != 0, (
            "the driving step accepted a relative capture directory")
        assert "must be an absolute path" in r.stderr, r.stderr
        assert not sends.exists(), (
            "the driving step sent keys before refusing its capture "
            "directory: " + (sends.read_text() if sends.exists() else ""))
        assert not calls.exists(), (
            "a step that could not report on the recorder acted on it "
            "anyway: " + (calls.read_text() if calls.exists() else ""))

    def test_tmux_stop_block_refuses_a_relative_capture_dir(self, tmp_path):
        """Step 5 reads the completion evidence from ``<capture-dir>``.

        The stop step is pasted on its own whenever the scenario is driven
        interactively, and "usually" into a fresh shell, where a relative
        path resolves against that shell rather than the directory the
        recorder wrote into. Verified live in this container with the
        recipe's own step 5 on tmux 3.2a and asciinema 2.1.0: a complete
        recording (2,695-byte cast, status ``0``, transcript) sat in the
        capture directory, and step 5 pasted from another directory with the
        same relative path exited 1 with "asciinema wrote no cast" — a
        finished recording reported as a missing one, the class this recipe
        removes everywhere else. Refuse the path before the recorder is
        detached.
        """
        calls = tmp_path / "tmux-calls"
        block = _stop_block("tmux-screen-recording.md").replace(
            "<capture-dir>", "relcap")
        r, _cast = _run_block(
            block, "ok", tmp_path, target=True, sessions=("pm-recorder",),
            capture=Path("relcap"), cwd=str(tmp_path),
            env_extra={"STUB_TMUX_LOG": str(calls)})

        assert r.returncode != 0, (
            "the stop step accepted a relative capture directory, so it read "
            "a directory the recorder never wrote into")
        assert "must be an absolute path" in r.stderr, r.stderr
        assert not calls.exists(), (
            "a step refused for its capture directory detached the recorder "
            "and stopped the pipe anyway: "
            + (calls.read_text() if calls.exists() else ""))
        assert (tmp_path / "state" / "pm-recorder").exists(), (
            "the refused stop step ended the recorder it could not check")

    def test_cli_stop_block_refuses_a_relative_capture_dir(self, tmp_path):
        """The CLI stop step is a paste of its own, and it kills the server.

        Step 4 is pasted on its own for an interactive recording (step 3 is
        what drives the shell, so the scaffold cannot run as one paste), and
        it reads the cast and the recorder's status from ``<capture-dir>``.
        With a relative path the checks read a directory the recorder never
        wrote into, report "asciinema wrote no cast" for a recording that
        finished, and then ``kill-server`` the scaffold that holds it —
        verified live in this container with the recipe's own scaffold on
        tmux 3.2a and asciinema 2.1.0: the absolute capture directory held
        the cast and status ``0`` while step 4 pasted from another directory
        with a relative path exited 1 with that message and no ``rec``
        session left. Refuse the path before the wait or any tmux call.
        """
        calls = tmp_path / "tmux-calls"
        block = _stop_block("cli-recording.md").replace("<capture-dir>",
                                                        "relcap")
        r, _cast = _run_block(
            block, "ok", tmp_path, capture=Path("relcap"), cwd=str(tmp_path),
            env_extra={"STUB_TMUX_LOG": str(calls)})

        assert r.returncode != 0, (
            "the CLI stop step accepted a relative capture directory")
        assert "must be an absolute path" in r.stderr, r.stderr
        assert "kill-server" not in (
            calls.read_text() if calls.exists() else ""), (
            "the refused stop step killed the scaffold server that holds the "
            "recording: " + (calls.read_text() if calls.exists() else ""))

    # The absolute-path guard only proves the *form* of <capture-dir>. A
    # paste-alone step given an absolute path that is not there (step 0 never
    # ran for it, a typo, a wrong <short-name>) reads or writes a directory
    # the run never used, and the failure surfaces as a different problem.
    # These cases pin the usability half on the four paste-alone steps that
    # resolve the path for themselves.
    @pytest.mark.parametrize(
        "shape", ["missing", 0o500, 0o600],
        ids=["missing", "no-write-bit", "no-search-bit"])
    def test_step_three_refuses_a_capture_dir_it_cannot_use(
            self, tmp_path, shape):
        """Step 3 writes the recording through ``<capture-dir>``.

        The pane command writes the cast, asciinema's stderr log and the
        status into the directory, and step 3 is pasted on its own when a run
        restarts its recorder. With a path that is not there, or one that
        cannot be written, those redirects fail before asciinema runs, the
        pane exits, and the readiness wait reports "recorder exited before it
        drew — see the cast and <capture-dir>/recorder-stderr.log", naming
        two files that cannot exist (verified live in this container on tmux
        3.2a: step 3 alone with a missing capture directory printed exactly
        that). Refuse it before the session is created, and make no tmux call
        at all — the recorder session name is shared with concurrent runs.
        Mode 500 (no write bit) and mode 600 (write bit, no search bit) are
        the two unusable shapes; the guard needs both ``-w`` and ``-x``.
        """
        capture = tmp_path / "cap"
        if shape != "missing":
            if not hasattr(os, "geteuid") or os.geteuid() == 0:
                pytest.skip("root bypasses the directory permission bits")
            capture.mkdir()
            capture.chmod(shape)
        calls = tmp_path / "tmux-calls"
        try:
            r, _cast = _run_block(
                _step_three_block(), "ok", tmp_path, target=True,
                capture=capture, env_extra={"STUB_TMUX_LOG": str(calls)})
        finally:
            if shape != "missing":
                capture.chmod(0o700)

        assert r.returncode != 0, (
            "step 3 started a recorder that writes the cast, its stderr log "
            "and its status into a capture directory it cannot use")
        assert "missing or cannot be written" in r.stderr, r.stderr
        assert "recorder exited before it drew" not in r.stderr, (
            "the refused step reported the recorder failure its guard "
            "exists to prevent: " + r.stderr)
        assert not calls.exists(), (
            "a step that could not use its capture directory acted on the "
            "recorder session anyway: "
            + (calls.read_text() if calls.exists() else ""))

    def test_tmux_driving_step_refuses_a_missing_capture_dir(self, tmp_path):
        """Step 4's failure path saves the pane into ``<capture-dir>``.

        The save is `capture-pane … > <capture-dir>/recorder-pane.log
        2>/dev/null || true`, so with a path that is not there it writes
        nothing while the failure message still points at that file — and a
        wrong path here is the earliest sign that the worker's capture
        directory is not the one the run used, which the stop step pasted
        with the same path then reports as a missing recording. Refuse it
        before any send, so the block neither drives a TUI nor acts on a
        recorder it cannot report on.
        """
        sends = tmp_path / "sends"
        calls = tmp_path / "tmux-calls"
        r, _cast = _run_block(
            _driving_block(), "ok", tmp_path, target=True,
            sessions=("pm-recorder",), capture=tmp_path / "missing",
            env_extra={"STUB_TMUX_LOG": str(calls),
                       "STUB_PM_SEND_LOG": str(sends)})

        assert r.returncode != 0, (
            "the driving step accepted a capture directory that does not "
            "exist, so its failure path would save the pane nowhere")
        assert "missing or cannot be read" in r.stderr, r.stderr
        assert not sends.exists(), (
            "the driving step sent keys before refusing its capture "
            "directory: " + (sends.read_text() if sends.exists() else ""))
        assert not calls.exists(), (
            "a step that could not report on the recorder acted on it "
            "anyway: " + (calls.read_text() if calls.exists() else ""))

    @pytest.mark.parametrize(
        "shape", ["missing", 0o600], ids=["missing", "no-search-bit"])
    def test_tmux_stop_block_refuses_a_capture_dir_it_cannot_read(
            self, tmp_path, shape):
        """Step 5 reads the completion evidence, and it detaches the recorder.

        With a path that is not there the checks read a directory the
        recorder never wrote into while the detach still runs — so a *live*
        recording is ended and the run reports "asciinema wrote no cast" for
        a cast that exists one directory over. Verified live in this
        container on tmux 3.2a and asciinema 2.1.0: step 5 pasted with a
        missing absolute path detached the recorder, exited 1 with that
        message, and left a complete cast (2.7 KB, status ``0``) in the
        real capture directory. Mode 600 is the same state for a reader (no
        search bit), which is why the guard tests ``-x`` too. Refuse it
        before the recorder is detached.
        """
        capture = tmp_path / "cap"
        if shape != "missing":
            if not hasattr(os, "geteuid") or os.geteuid() == 0:
                pytest.skip("root bypasses the directory permission bits")
            capture.mkdir()
            capture.chmod(shape)
        calls = tmp_path / "tmux-calls"
        try:
            r, _cast = _run_block(
                _stop_block("tmux-screen-recording.md"), "ok", tmp_path,
                target=True, sessions=("pm-recorder",), capture=capture,
                env_extra={"STUB_TMUX_LOG": str(calls)})
        finally:
            if shape != "missing":
                capture.chmod(0o700)

        assert r.returncode != 0, (
            "the stop step accepted a capture directory it cannot read, so "
            "it would report a finished recording as a missing one")
        assert "missing or cannot be read" in r.stderr, r.stderr
        assert "asciinema wrote no cast" not in r.stderr, (
            "the refused step blamed the recorder for a capture directory "
            "it could not read: " + r.stderr)
        assert not calls.exists(), (
            "a step refused for its capture directory detached the recorder "
            "and stopped the pipe anyway: "
            + (calls.read_text() if calls.exists() else ""))
        assert (tmp_path / "state" / "pm-recorder").exists(), (
            "the refused stop step ended the recorder it could not check")

    @pytest.mark.parametrize(
        "shape", ["missing", 0o600], ids=["missing", "no-search-bit"])
    def test_cli_stop_block_refuses_a_capture_dir_it_cannot_read(
            self, tmp_path, shape):
        """The CLI stop step reads the evidence, and it kills the server.

        With a path that is not there (or one that cannot be searched) the
        checks read a directory the recorder never wrote into, report
        "asciinema wrote no cast" for a recording that finished, and then
        ``kill-server`` the scaffold that holds it. Verified live in this
        container on tmux 3.2a and asciinema 2.1.0: step 4 pasted with a
        missing absolute path exited 1 with that message and killed the
        server, while the real capture directory held the cast and status
        ``0``. Refuse it before the wait or any tmux call.
        """
        capture = tmp_path / "cap"
        target = capture / "run"
        if shape != "missing":
            if not hasattr(os, "geteuid") or os.geteuid() == 0:
                pytest.skip("root bypasses the directory permission bits")
            target.mkdir(parents=True)
            target.chmod(shape)
        calls = tmp_path / "tmux-calls"
        try:
            r, _cast = _run_block(
                _stop_block("cli-recording.md"), "ok", tmp_path,
                capture=capture, env_extra={"STUB_TMUX_LOG": str(calls)})
        finally:
            if shape != "missing":
                target.chmod(0o700)

        assert r.returncode != 0, (
            "the CLI stop step accepted a capture directory it cannot read")
        assert "missing or cannot be read" in r.stderr, r.stderr
        assert "asciinema wrote no cast" not in r.stderr, (
            "the refused step blamed the recorder for a capture directory "
            "it could not read: " + r.stderr)
        assert "kill-server" not in (
            calls.read_text() if calls.exists() else ""), (
            "the refused stop step killed the scaffold server that holds the "
            "recording: " + (calls.read_text() if calls.exists() else ""))

    @pytest.mark.parametrize("name", RECIPES)
    @UNWRITABLE_MODES
    def test_a_capture_dir_that_cannot_be_written_stops_the_run(
            self, name, capdir_mode, tmp_path):
        """`mkdir -p` answers 0 for an existing directory that is not writable.

        Every later write into it fails as something else: the tmux recipe's
        pipe writes nothing and the recorder's redirects fail before
        asciinema runs, so the run ends as "recorder exited before it drew —
        see the cast and …/recorder-stderr.log"; the CLI scaffold's pane
        redirect fails the same way and step 4 says "asciinema wrote no cast —
        see …/recorder-stderr.log". Both messages name files that cannot exist
        (verified live with a mode-500 capture directory in each recipe: rc 1
        with that message, and the directory empty). The block must refuse the
        directory where it creates it — and before it clears the recorder
        session shared with concurrent runs, so a refused block makes no tmux
        call at all.

        Mode 600 (write bit, no search bit) is the shape only the guard's
        ``-x`` half sees. Without that half the block runs on, clears the
        shared recorder session first, and then exits 1 on `rm`'s own
        "Permission denied" — a block that refused its own path *after*
        ending a concurrent capture's recorder, which is exactly what the
        clear-after-the-guard ordering exists to prevent.
        """
        if not hasattr(os, "geteuid") or os.geteuid() == 0:
            pytest.skip("root bypasses the directory permission bits")
        capture = tmp_path / "cap"
        capture.mkdir()
        # The CLI scaffold writes under <capture-dir>/<short-name>/.
        target = capture
        if name == "cli-recording.md":
            target = capture / "run"
            target.mkdir()
        target.chmod(capdir_mode)
        calls = tmp_path / "tmux-calls.log"
        try:
            r, _cast = _run_block(
                _scaffold_block(_recipe_text(name)), "ok", tmp_path,
                capture=capture, env_extra={"STUB_TMUX_LOG": str(calls)})
        finally:
            target.chmod(0o700)
        assert r.returncode != 0, (
            f"{name}: an unwritable capture directory was reported as a "
            "successful start")
        assert "cannot be written" in r.stderr, r.stderr
        assert not calls.exists(), (
            f"{name}: the block acted on a tmux handle (the recorder session "
            "shared with concurrent runs) for a capture directory it then "
            "refused")

    @UNWRITABLE_MODES
    def test_cli_preamble_refuses_a_capture_dir_it_cannot_write(
            self, tmp_path, capdir_mode):
        """The preamble's own copy of the guard covers the simple forms too.

        It clears the previous run's files before any recording form, and a
        clear that cannot write leaves the earlier cast in place — which the
        simple `asciinema rec` form (no ``--overwrite``) then aborts on it
        ("asciinema: <path> already exists, aborting" on 2.1.0), a cause the
        worker cannot connect to the path. The preamble refuses the directory
        instead. Mode 600 (write bit, no search bit) is the shape only the
        guard's ``-x`` half can see.
        """
        if not hasattr(os, "geteuid") or os.geteuid() == 0:
            pytest.skip("root bypasses the directory permission bits")
        capture = tmp_path / "cap"
        (capture / "run").mkdir(parents=True)
        (capture / "run").chmod(capdir_mode)
        try:
            r, _cast = _run_block(
                _cli_preamble_block(), "ok", tmp_path, capture=capture)
        finally:
            (capture / "run").chmod(0o700)
        assert r.returncode != 0, (
            "the preamble cleared a capture directory nothing can be written "
            "into")
        assert "cannot be written" in r.stderr, r.stderr
        assert str(capture / "run") in r.stderr, (
            "the refusal does not name the capture directory: " + r.stderr)

    @pytest.mark.parametrize("name", RECIPES)
    def test_a_tilde_capture_dir_is_accepted(self, name, tmp_path):
        """`~/…` is a documented spelling, and only the refusal half had a case.

        Both recipes' guards accept a ``<capture-dir>`` that starts with
        ``~/`` — the prose says so, and step 2's claim comparison exists to
        make ``~/cap`` and its absolute spelling one claim. Every case that
        ran a guard used an absolute path, so narrowing the pattern to ``/*``
        left the whole file green (211 passed) and the block then refused a
        documented-valid path with "must be an absolute path". Run the block
        that owns the guard — the tmux recipe's step 0, the CLI preamble —
        with ``~/cap`` and require it to create the directory under ``$HOME``.
        """
        home = tmp_path / "home"
        home.mkdir()
        block = (_step_zero_block() if name == "tmux-screen-recording.md"
                 else _cli_preamble_block())
        r, _cast = _run_block(block, "ok", tmp_path, capture=Path("~/cap"),
                              env_extra={"HOME": str(home)})
        assert r.returncode == 0, (
            f"{name}: a ~/ capture dir was refused: " + r.stderr)
        assert "must be an absolute path" not in r.stderr, r.stderr
        assert (home / "cap").is_dir(), (
            f"{name}: the block did not create the capture directory under "
            "$HOME")

    def test_step_two_accepts_a_tilde_capture_dir(self, tmp_path):
        """The claim step's own guard accepts the documented ``~/`` spelling.

        Step 2 is a separate paste with its own absolute-path guard (R56), and
        its claim is canonicalized with ``pwd -P`` so ``~/cap`` and the
        absolute spelling are one claim.
        ``test_a_tilde_capture_dir_is_accepted`` runs only step 0 / the CLI
        preamble: narrowing step 2's pattern to ``/*`` left the whole file
        green (262 passed) and the block refused a documented-valid path. The
        pipe's command is a literal ``cat >> ~/…``,
        which the pane's shell expands (verified live on tmux 3.2a with a
        private server: the transcript is written under ``$HOME/cap``).
        """
        home = tmp_path / "home"
        (home / "cap").mkdir(parents=True)
        r, _cast = _run_block(_step_two_block(), "ok", tmp_path, target=True,
                              capture=Path("~/cap"),
                              env_extra={"HOME": str(home)})

        assert r.returncode == 0, (
            "step 2 refused a ~/ capture dir: " + r.stderr)
        assert "must be an absolute path" not in r.stderr, r.stderr
        claim = tmp_path / "state" / "claim.pm-test"
        assert claim.exists(), "step 2 took no claim on the capture directory"
        assert claim.read_text().strip() == str(home / "cap"), (
            "the claim is not the canonical directory the tilde spelling "
            "names: " + claim.read_text())
        assert (home / "cap" / "transcript.log").exists(), (
            "the transcript pipe did not write under $HOME")

    def test_cli_scaffold_accepts_a_tilde_capture_dir(self, tmp_path):
        """The no-TTY scaffold's guard accepts the documented ``~/`` spelling.

        The scaffold repeats the preamble's guard in the block a worker
        pastes whole (R34), and only the preamble's half had an acceptance
        case: narrowing the scaffold's pattern to ``/*`` left the whole file
        green (262 passed) and the block refused a documented-valid path
        before it created anything.
        """
        home = tmp_path / "home"
        home.mkdir()
        r, cast = _run_block(
            _scaffold_block(_recipe_text("cli-recording.md")), "oneshot",
            tmp_path, capture=Path("~/cap"), env_extra={"HOME": str(home)})

        assert r.returncode == 0, (
            "the CLI scaffold refused a ~/ capture dir: " + r.stderr)
        assert "must be an absolute path" not in r.stderr, r.stderr
        assert cast.stat().st_size > 0, (
            "the scaffold wrote no cast under $HOME")
        assert str(cast).startswith(str(home)), (
            "the scaffold wrote outside the directory ~/ names: " + str(cast))

    def test_step_zero_does_not_kill_a_pm_session_that_shares_the_prefix(
            self, tmp_path):
        """The recorder clear must not match another session by prefix.

        Step 0 clears a leftover recorder on every capture, and the server it
        runs on is pm's own: pm names sessions ``pm-<repo>-<hash>``, so a repo
        whose name starts with ``recorder`` has a session a bare
        ``pm-recorder`` target prefix-matches (verified on tmux 3.2a: a bare
        ``kill-session -t pm-recorder`` killed a ``pm-recorder-abc123``
        session). When the capture's own repo is named ``recorder`` that is
        the target session the scenario prepared; otherwise it is another
        project's TUI session — and ``2>/dev/null`` with ``|| true`` hides
        the kill. The clear has to name the exact session.
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")),
            "nostart", tmp_path, target=True,
            sessions=("pm-recorder-abc123",))
        assert r.returncode != 0, r.stderr
        assert "could not start the recorder session" in r.stderr, r.stderr
        assert (tmp_path / "state" / "pm-recorder-abc123").exists(), (
            "the capture's step 0 killed a session that merely starts with "
            "pm-recorder (a pm session for a repo named recorder-...), so it "
            "destroys another project's TUI session on every capture")

    def test_a_prefix_session_is_not_the_recorder(self, tmp_path):
        """A recorder that died must not be replaced by a prefix session.

        ``has-session -t pm-recorder`` prefix-matches when this run's recorder
        is gone, so a session named ``pm-recorder-<hash>`` (pm's name for a
        repo called ``recorder...``) satisfied the readiness check: its pane
        read as "the TUI drew", the detach key went into it, and the stop
        timeout killed it. The readiness and stop handles have to ask for the
        exact recorder session, so a dead recorder fails where it died.
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")),
            "failedattach", tmp_path, target=True,
            sessions=("pm-recorder-abc",))
        assert r.returncode != 0, r.stderr
        assert "recorder exited before it drew" in r.stderr, (
            "the readiness check took a prefix session for the recorder: "
            + r.stderr)
        assert (tmp_path / "state" / "pm-recorder-abc").exists(), (
            "the run drove and killed a session that merely starts with "
            "pm-recorder instead of failing on its own dead recorder")

    @pytest.mark.parametrize("name", RECIPES)
    def test_a_live_recorder_is_refused_not_cleared(self, name, tmp_path):
        """A live recorder is a capture in progress, not a leftover to clear.

        The recorder session is shared by every capture on its server (the
        tmux recipe's ``pm-recorder``) or host socket (the CLI scaffold's
        ``rec``), and both blocks used to clear it unconditionally. Two runs
        sharing one capture directory then collide silently: the later run's
        clear ends the earlier run's recorder, its own recorder writes the
        same cast and status, and the earlier run's stop step waits on the new
        session and reads the later run's files — both report success on one
        recording. Reproduced live with the CLI scaffold's own block (two
        scaffolds pasted 0.7 s apart into one capture directory, a stub
        ``asciinema`` that writes a cast and sleeps): both exited 0 with the
        second run's cast and status in the directory.

        The block has to refuse while the recorder's *pane* is running, and
        clear only a dead-pane leftover (``remain-on-exit on`` keeps the
        session after its only pane's command returns). The refusal runs
        before the file clear, so the other run's evidence survives.
        """
        calls = tmp_path / "tmux-calls.log"
        tmux = name == "tmux-screen-recording.md"
        block = (_step_zero_block() if tmux
                 else _scaffold_block(_recipe_text(name)))
        session = "pm-recorder" if tmux else "rec"
        r, cast = _run_block(
            block, "ok", tmp_path, target=True, sessions=(session,),
            files={"recording.cast": '{"version": 2}\n',
                   "recorder.status": "0\n"},
            env_extra={"STUB_TMUX_LOG": str(calls)})

        assert r.returncode != 0, (
            f"{name}: a live recorder was cleared instead of refused, so the "
            "capture it belongs to loses its evidence")
        assert "already running" in r.stderr, r.stderr
        assert (tmp_path / "state" / session).exists(), (
            f"{name}: the block ended a recorder another capture is running")
        calls_text = calls.read_text() if calls.exists() else ""
        assert "kill-session" not in calls_text and \
            "kill-server" not in calls_text, (
                f"{name}: the refused block acted on the live recorder: "
                + calls_text)
        assert cast.read_text() == '{"version": 2}\n', (
            f"{name}: the refused block cleared the live capture's cast")

    @pytest.mark.parametrize("name", RECIPES)
    def test_a_dead_recorder_leftover_is_cleared(self, name, tmp_path):
        """A recorder whose pane has returned writes nothing; clear it.

        ``remain-on-exit on`` keeps the session after its only pane's command
        returns, and ``new-session`` then fails with "duplicate session" while
        it exists. The live-recorder refusal must not refuse this one: the
        leftover is dead, so it is cleared and the run starts (step 0's clear
        takes the previous attempt's cast and status with it).
        """
        calls = tmp_path / "tmux-calls.log"
        tmux = name == "tmux-screen-recording.md"
        block = (_step_zero_block() if tmux
                 else _scaffold_block(_recipe_text(name)))
        session = "pm-recorder" if tmux else "rec"
        r, cast = _run_block(
            block, "oneshot", tmp_path, target=True,
            sessions=(session,), state_files={f"dead.{session}": ""},
            files={"recording.cast": '{"version": 2}\n',
                   "recorder.status": "0\n",
                   "transcript.log": "previous run\n"},
            env_extra={"STUB_REMAIN": "1", "STUB_TMUX_LOG": str(calls)})

        assert r.returncode == 0, (
            f"{name}: a dead-pane recorder leftover was refused: " + r.stderr)
        calls_text = calls.read_text()
        assert "kill-session" in calls_text, (
            f"{name}: the dead leftover was not cleared, so `new-session` "
            "would fail with a duplicate session")
        assert not (tmp_path / "state" / session).exists(), (
            f"{name}: the dead leftover was left behind")
        assert not (cast.parent / "transcript.log").exists(), (
            f"{name}: the run kept the previous attempt's transcript")
        if tmux:
            # Step 0 alone removes the stale cast; the CLI scaffold goes on to
            # record a new one.
            assert not cast.exists(), (
                f"{name}: step 0 kept the previous attempt's cast")
        else:
            assert cast.stat().st_size > 0, (
                f"{name}: the cleared run wrote no cast")

    def test_step_two_refuses_an_empty_target(self, tmp_path):
        """Pasted alone with no session name, step 2 must not guess a session.

        ``tmux -t ''`` resolves to whatever session tmux considers current, so
        an empty ``$TARGET`` would read the claim from — and attach the pipe
        to — another run's session. Steps 4 and 5 re-derive the handle for the
        same reason.
        """
        r, _cast = _run_block(_step_two_block(), "ok", tmp_path,
                              env_extra={"STUB_PM_NAME": ""})
        assert r.returncode != 0, (
            "step 2 ran with no target session instead of refusing")
        assert "TARGET is unset and 'pm session name' printed nothing" in (
            r.stderr), r.stderr

    def test_step_two_claims_the_capture_dir_on_the_session(self, tmp_path):
        """The claim is what the collision guards read; it has to be written.

        Step 2 records the capture directory in a session option, so the
        guard survives the separate pastes that follow. ``nostart`` fails the
        recorder start *after* step 2, which is the earliest point the claim
        can be observed — the stub records the claim it saw when the pipe was
        attached, because the failure path below releases the claim again.
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")),
            "nostart", tmp_path, target=True)
        assert r.returncode != 0, r.stderr
        seen = tmp_path / "state" / "pipeclaim"
        assert seen.read_text().strip() == str((tmp_path / "cap").resolve()), (
            "step 2 did not claim the capture directory before attaching the "
            "pipe")

    def test_a_claim_that_cannot_be_written_is_reported(self, tmp_path):
        """A claim that could not be taken must stop the step where it fails.

        Step 2's claim is the only thing that keeps a second capture from
        taking this run's transcript pipe over, and the exact-session assert
        just above it can be stale by the time the write lands. Without the
        guard the step runs on and attaches the pipe anyway; when the session
        went away the attach then fails as "could not stream … — check that
        pane exists", which names the wrong cause: it was the *session* that
        went away, so there is no pane to check. The stub's `claimgone` ends
        the session as the claim is written.
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")),
            "claimgone", tmp_path, target=True)
        assert r.returncode != 0, (
            "a run that could not take its capture-dir claim was reported as "
            "a success: " + r.stderr)
        assert "could not claim" in r.stderr, r.stderr
        assert "could not stream" not in r.stderr, (
            "the failed claim is reported as a failed pipe attach, so the "
            "worker is sent to look at a pane that never existed: "
            + r.stderr)

    def test_a_claim_written_to_a_prefix_session_is_reported(self, tmp_path):
        """`set-option` prefix-matches too, so the write needs the exact handle.

        The guard above reports a target that went away, and it depends on the
        write *failing* — which a plain `-t "$TARGET"` does not do. Real tmux
        (3.2a, verified on a private server: `set-option -t pm-test
        @pm_capture_dir /cap` with only `pm-test~1` present) exits **0** and
        writes the option on the grouped session; only the `=pm-test:0.0` pane
        form is exact, and it answers "no such session" in the same state. With
        the bare handle the guard never fires: the run goes on with its claim
        on the grouped session, where the exact read above can never see it
        (the collision guard is off), and it fails one step later as
        "could not stream … — check that pane exists" — a pane named for a
        session that went away, the same misdiagnosis `claimgone` covers for
        the shape where nothing matches the prefix. The grouped session's own
        claim must also survive: a bare write would overwrite it.
        """
        other = str((tmp_path / "other-cap").resolve())
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")),
            "claimgap", tmp_path, target=True,
            state_files={"claim.pm-test~1": other})
        assert r.returncode != 0, (
            "a run that could not take its capture-dir claim was reported as "
            "a success: " + r.stderr)
        assert "could not claim" in r.stderr, r.stderr
        assert "could not stream" not in r.stderr, (
            "the vanished session is reported as a failed pipe attach, so the "
            "worker is sent to check a pane that never existed: " + r.stderr)
        assert "already being recorded" not in r.stderr, (
            "the claim was read from the grouped session the target's prefix "
            "matched instead of from the target: " + r.stderr)
        assert (tmp_path / "state" / "claim.pm-test~1").read_text().strip() \
            == other, (
            "the claim write landed on the grouped session pm-test~1 (the "
            "prefix match), overwriting the claim another run holds there")

    def test_the_claim_is_released_only_after_the_pipe_is_stopped(self):
        """The cleanup order is a race guard, and it needs its own case.

        Step 5 releases the capture-directory claim *last*: a later run in the
        same session may record into another directory, and the instant the
        claim is released it can take it and attach its own pipe — which this
        run's pipe stop would then close, leaving that run with a transcript
        that stops growing while its stop step still passes (the takeover the
        claim exists to stop). Every cleanup that stops the pipe and releases
        the claim is ordered the same way, so pin the order at every release:
        only the recorder kill may sit between this run's pipe stop and the
        release. Reordering them leaves the whole file green (verified by
        mutation), because no case observes the order — the stub's claim
        state is the same either way. The one cleanup with no stop is step 2's
        own failed attach: there is no pipe to stop, and the release is that
        path's cleanup.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        stmts, cur = [], []
        for line in block.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            cur.append(s)
            if not s.endswith("\\"):
                stmts.append(" ".join(cur))
                cur = []
        releases = [i for i, st in enumerate(stmts)
                    if st.startswith(
                        'tmux set-option -u -t "=$TARGET:0.0" @pm_capture_dir')]
        assert releases, "the tmux recipe releases no capture-dir claim"
        stop = 'tmux pipe-pane -t "=$TARGET:0.0" 2>/dev/null'
        for i in releases:
            j = i - 1
            while (j >= 0
                   and stmts[j].startswith('tmux kill-session -t "=pm-recorder"')):
                j -= 1
            if j >= 0 and stmts[j].startswith(stop):
                continue
            previous = stmts[j] if j >= 0 else "<start of block>"
            assert j >= 0 and '"cat >>' in " ".join(stmts[max(0, j - 1):i + 1]), (
                "the claim release after %r is not preceded by this run's pipe "
                "stop, so a later run in the session can take the claim and "
                "have its pipe closed by this run's cleanup" % (previous,))

    @pytest.mark.parametrize("mode,message", [
        ("pipefail", "could not stream"),        # step 2 could not attach the pipe
        ("nostart", "could not start the recorder session"),  # step 3 start failed
        ("norec", "recorder did not come up"),   # the recorder never drew
        ("dies", "recorder exited before it drew"),  # it exited before drawing
        ("failedattach", "recorder exited before it drew"),  # drew its own error
        ("stuck", "recorder did not exit within"),  # never exited at the bound
        ("notranscript", "transcript.log is empty"),  # the pipe wrote nothing
        ("midadied", "recorder exited while the TUI was still running"),
        ("detachfail", "recorder exited before the detach"),
        ("midbothbad", "asciinema exited 137"),
    ])
    def test_a_failed_run_releases_its_capture_dir_claim(self, mode, message,
                                                         tmp_path):
        """A claim must not outlive a *failed* run either.

        The claim lives on the pm session, which usually survives a failed
        capture (the recorder and the pipe do not). Left behind, it refuses
        the next attempt in that session — into another capture directory —
        with "already being recorded into …", a collision that does not
        exist; and a *different* session recording that directory is refused
        as if this run were still going. Every failure path after the claim
        is taken therefore releases it, like the successful finish does. The
        pipe-attach failure (``pipefail``, step 2) is the earliest of those
        paths and is covered here too: its own release line was the only one
        no case exercised, so deleting it left every test green. A run killed
        outright (SIGKILL) leaves a claim no path can release, which is why
        both refusal messages name the manual clear.

        Each mode also has to *reach* its branch, and the message is how the
        case knows: if a fixture drifted to an earlier failure, the claim
        would still be released there and the assertion would pass while the
        branch under test — the one whose release line this case exists to
        pin — never ran (the same "fails for the wrong reason" hole the
        sibling ``test_step_five_failures_release_the_claim`` closes for the
        two cast/status branches).
        """
        r, _cast = _run_capture_block(
            "tmux-screen-recording.md", mode, tmp_path, target=True)
        assert r.returncode != 0, (
            f"{mode}: the fixture was expected to fail the run")
        assert message in r.stderr, (
            f"{mode}: the run failed somewhere other than the branch under "
            "test, so its claim release is not exercised: " + r.stderr)
        claim = tmp_path / "state" / "claim.pm-test"
        assert not claim.exists(), (
            f"{mode}: the failed run left its capture-dir claim on the "
            "session, so the next attempt in this session is refused by a "
            "capture that is no longer running")

    def test_step_two_claims_before_it_attaches_the_pipe(self, tmp_path):
        """The claim has to be taken *before* the pipe it is meant to guard.

        Step 2 reads the claim, writes it, and only then attaches the pipe.
        With the write *after* the pipe, two runs that both pass the read
        before either writes it both attach — and the second pipe replaces the
        first, the takeover the claim exists to stop (verified live, QA S24:
        the first run's transcript stops growing while its stop step still
        exits 0). Taking the claim first does not make the read/write atomic
        (tmux has no compare-and-set), but it keeps the race window off the
        pipe attachment itself.
        """
        r, _cast = _run_block(_step_two_block(), "ok", tmp_path, target=True)
        assert r.returncode == 0, r.stderr
        seen = tmp_path / "state" / "pipeclaim"
        assert seen.read_text().strip() == str((tmp_path / "cap").resolve()), (
            "step 2 attached the transcript pipe before claiming the capture "
            "directory, so a concurrent run can pass the same check and take "
            "the pipe over")

    def test_a_second_capture_dir_on_one_session_is_refused(self, tmp_path):
        """Two runs recording one pm session must not take each other's pipe.

        Verified live (QA S24): the second run's ``pipe-pane`` (no ``-o``)
        replaces the first's, so the first run's ``transcript.log`` stops
        growing while its stop step still exits 0 — a silent false pass on a
        transcript that is not the run's own. Step 2 claims the session for
        its capture directory and refuses a different one.
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")), "ok",
            tmp_path, target=True,
            state_files={"claim.pm-test":
                        str((tmp_path / "other-cap").resolve())})
        assert r.returncode != 0, "a second capture dir took over the session"
        assert "already being recorded into" in r.stderr, r.stderr

    def test_one_capture_dir_claimed_by_another_session_is_refused(self,
                                                                  tmp_path):
        """Two runs into one capture directory cannot be told apart.

        Verified live (QA S24): the second run's step 0 removes the first
        run's cast and transcript, then the first run's stop block detaches
        the *second* run's recorder and reads its status — exiting 0 on
        evidence that belongs to the other run. Step 2 refuses a directory
        another live pm session already records into.
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")), "ok",
            tmp_path, target=True,
            state_files={"pm-other": "",
                         "claim.pm-other": str((tmp_path / "cap").resolve())})
        assert r.returncode != 0, "a shared capture dir was recorded twice"
        assert "is already being recorded by pm session pm-other" in r.stderr, (
            r.stderr)

    def test_the_shared_dir_refusal_names_the_clear_that_works(self, tmp_path):
        """The refusal must offer a remedy for a claim that is already stale.

        A run killed outright (SIGKILL) leaves its claim behind — no failure
        path can run — and that claim refuses a *different* session recording
        the same directory. "End that capture" is then impossible advice: the
        capture already ended. The message has to name the command that clears
        the claim, on the session that holds it, like the same-session refusal
        does.
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")), "ok",
            tmp_path, target=True,
            state_files={"pm-other": "",
                         "claim.pm-other": str((tmp_path / "cap").resolve())})
        assert r.returncode != 0, r.stderr
        assert "tmux set-option -u -t pm-other @pm_capture_dir" in r.stderr, (
            "the shared-directory refusal does not say how to clear a stale "
            "claim, so a worker whose predecessor was killed has no remedy "
            "that works: " + r.stderr)

    def test_a_finished_run_releases_its_capture_dir_claim(self, tmp_path):
        """A claim must not outlive the run that made it.

        Otherwise the next capture in the same session — into a different
        directory — is refused by its own predecessor.
        """
        r, _cast = _run_capture_block(
            "tmux-screen-recording.md", "ok", tmp_path, target=True)
        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "state" / "claim.pm-test").exists(), (
            "the finished run left its capture-dir claim on the session")

    @pytest.mark.parametrize("mode,message", [
        # The two step-5 branches after the claim is taken that no other mode
        # reaches with the pm session still alive: the recorder draws and the
        # detach ends it, as in a real finish, but the cast (or the status)
        # was never written. The session survives, so a claim left behind
        # would refuse the next attempt in it.
        ("detachnocast", "asciinema wrote no cast"),
        ("detachnostatus", "recorder status is missing"),
    ])
    def test_step_five_failures_release_the_claim(self, mode, message,
                                                  tmp_path):
        """The cast/status branches must release the claim like the others.

        Every failure path after step 2 takes the claim releases it, or the
        next attempt in that session is refused by a capture that already
        ended. ``midbothbad`` covers the non-zero-status branch; these two
        cover the missing-cast and missing-status ones, which the recipe
        releases the same way.
        """
        r, _cast = _run_capture_block(
            "tmux-screen-recording.md", mode, tmp_path, target=True)
        assert r.returncode != 0, (
            f"{mode}: the fixture was expected to fail the run")
        assert message in r.stderr, (
            f"{mode}: the run failed somewhere other than the branch under "
            "test, so its claim release is not exercised: " + r.stderr)
        assert not (tmp_path / "state" / "claim.pm-test").exists(), (
            f"{mode}: the failed run left its capture-dir claim on the "
            "session, so the next attempt in this session is refused by a "
            "capture that is no longer running")

    def test_a_session_with_no_claim_is_not_a_collision(self, tmp_path):
        """A session holding no claim is not recording into the worker's cwd.

        `tmux show-options -v` answers nothing for a session that holds no
        claim, and `cd ""` succeeds and stays in the *current* directory — so
        normalizing the empty answer compared the pasting shell's cwd with the
        capture directory. Step 2 pasted from inside the capture directory
        then refused the run as "already being recorded by pm session …" for a
        capture that does not exist, and took no claim of its own. Verified
        live on tmux 3.2a: with another session holding no claim at all, step
        2 run from the capture directory exited 1 naming that session.
        """
        r, _cast = _run_block(_step_two_block(), "ok", tmp_path, target=True,
                              sessions=("pm-other",), cwd=tmp_path / "cap")
        assert r.returncode == 0, (
            "a session holding no claim was read as recording into the "
            "capture directory step 2 was pasted from: " + r.stderr)
        assert "already being recorded" not in r.stderr, r.stderr
        claim = tmp_path / "state" / "claim.pm-test"
        assert claim.exists(), (
            "the run took no claim of its own, so the refusal happened before "
            "step 2 claimed the directory")

    def test_a_shared_dir_is_recognized_through_a_tilde_spelling(self,
                                                                tmp_path):
        """One directory spelled two ways is still one directory.

        Step 0 accepts `~/cap` as well as an absolute path, and a quoted `~`
        is never expanded, so comparing the claim as text let a *different*
        session claim the same directory: both runs then write its cast and
        transcript and read each other's evidence (the collision the claim
        exists to stop). Verified live on tmux 3.2a: `~/capA` claimed on one
        session, `/home/<user>/capA` on another ran on (rc 0).
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")), "ok",
            tmp_path, target=True,
            env_extra={"HOME": str(tmp_path)},
            state_files={"pm-other": "", "claim.pm-other": "~/cap"})
        assert r.returncode != 0, (
            "a second session recorded the same capture directory through a "
            "`~/` spelling, so both runs read each other's evidence")
        assert ("is already being recorded by pm session pm-other"
                in r.stderr), r.stderr

    def test_a_retry_is_not_refused_by_its_own_tilde_claim(self, tmp_path):
        """The same run's own claim, in the other spelling, is not a collision.

        The mirror of the case above: the session already holds `~/cap` for
        the directory this run records into, and comparing the strings
        refused the retry with "already being recorded into ~/cap" — a
        collision that does not exist.
        """
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")), "ok",
            tmp_path, target=True,
            env_extra={"HOME": str(tmp_path)},
            state_files={"claim.pm-test": "~/cap"})
        assert r.returncode == 0, (
            "a retry in the same session was refused as a collision because "
            "its own claim was written with a `~/` spelling: " + r.stderr)

    def test_a_shared_dir_is_recognized_through_a_symlink(self, tmp_path):
        """`pwd -P` is the other half of the canonical claim, and it had no case.

        Step 2 compares the claim as a *directory*: `cd` + `pwd -P` collapses
        a trailing slash and a symlinked path, so a second session that reaches
        the capture directory through a symlink to it is still refused. The
        `~/` spelling is pinned above, but nothing exercised the symlink — the
        prose claims it, and replacing every `pwd -P` with `pwd` left the whole
        file green (verified, 201 passed). The two spellings then differ, both
        runs pass the collision check and write into one directory, reading
        each other's cast, status and transcript.
        """
        real = tmp_path / "real"
        (real / "cap").mkdir(parents=True)
        (tmp_path / "link").symlink_to(real)
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")), "ok",
            tmp_path, target=True, capture=tmp_path / "link" / "cap",
            state_files={"pm-other": "",
                         "claim.pm-other": str(real / "cap")})
        assert r.returncode != 0, (
            "a second session recorded the same capture directory through a "
            "symlinked spelling, so both runs read each other's evidence")
        assert ("is already being recorded by pm session pm-other"
                in r.stderr), r.stderr

    def test_a_retry_is_not_refused_through_a_symlink(self, tmp_path):
        """The mirror: the same run's own claim, reached through a symlink.

        With the claim stored as the real path and the retry pasted with the
        symlinked one, a text comparison refuses a retry that is not a
        collision (and, with the cross-session case above, the pair is what
        makes `pwd -P` load-bearing rather than incidental).
        """
        real = tmp_path / "real"
        (real / "cap").mkdir(parents=True)
        (tmp_path / "link").symlink_to(real)
        r, _cast = _run_block(
            _scaffold_block(_recipe_text("tmux-screen-recording.md")), "ok",
            tmp_path, target=True, capture=tmp_path / "link" / "cap",
            state_files={"claim.pm-test": str(real / "cap")})
        assert r.returncode == 0, (
            "a retry in the same session was refused as a collision because "
            "its own claim was written against the real path and the step was "
            "pasted with the symlinked one: " + r.stderr)

    def test_tmux_transcript_that_is_never_written_fails(self, tmp_path):
        """The pipe can accept the attach and still write nothing.

        ``transcript.log`` is one of the artifacts this recipe promises, and
        ``test -s`` on the cast cannot tell whether it was written. A run
        whose pipe never wrote anything has no transcript, so it must not be
        reported as a finished capture.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "notranscript", tmp_path, target=True)
        assert cast.stat().st_size > 0, "the fixture left no cast to misread"
        assert r.returncode != 0, (
            "a capture with no transcript was reported as a success")
        assert "transcript.log is empty" in r.stderr, r.stderr

    def test_tmux_empty_transcript_is_not_a_transcript(self, tmp_path):
        """A 0-byte transcript is a pipe that wrote nothing.

        ``tmux pipe-pane`` opens ``transcript.log`` as soon as its command
        starts, so a pane that emits nothing between the attach and the stop
        leaves an *empty* file rather than no file. The check is ``test -s``
        for exactly that state, but the only execution case modelled the
        missing file (``notranscript`` writes nothing at all): mutating the
        check to ``-e`` failed only the *text* assertion in
        ``test_tmux_transcript_is_required_and_checked``, which pins the
        spelling, not the behaviour — no case ran the block against a
        transcript that exists and is empty, and the run would then report a
        capture whose manifest lists a transcript this run never produced.
        That is the same gap R46/R80 closed for the cast, gif and webm
        checks, one artifact over.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "emptytranscript", tmp_path,
            target=True)
        assert cast.stat().st_size > 0, "the fixture left no cast to misread"
        assert (cast.parent / "transcript.log").exists(), (
            "the fixture wrote no transcript at all, so the case would pass "
            "on the missing-file branch")
        assert r.returncode != 0, (
            "a capture whose transcript is empty was reported as a success")
        assert "transcript.log is empty" in r.stderr, r.stderr

    def test_tmux_failed_transcript_pipe_is_reported(self, tmp_path):
        """A failed ``pipe-pane`` must say so where it happens.

        ``tmux pipe-pane`` returns non-zero when the pane is gone or the
        command cannot be spawned. Ignoring that leaves the rest of the
        recording to run and fail later with a message about the transcript
        that does not name the attach.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "pipefail", tmp_path, target=True)
        assert r.returncode != 0, (
            "a failed transcript pipe was ignored and the run continued")
        assert "could not stream" in r.stderr, r.stderr

    def test_the_transcript_pipe_targets_the_exact_session(self, tmp_path):
        """The pipe is a target handle too: a bare one streams another session.

        Step 2 asserts that ``$TARGET`` is an exact session and then attaches
        the transcript pipe. A target that ends in that gap is exactly the
        state a *bare* pipe target prefix-matches — pm leaves a grouped
        ``<base>~1`` session behind, and real tmux (3.2a, verified) answers
        "can't find session: pm-test" for ``pipe-pane -t '=pm-test:0.0'``
        while ``-t pm-test:0.0`` attaches to ``pm-test~1`` and the file grows.
        A bare handle therefore records a session pm never started as this
        run's transcript, and the rest of the flow then passes on it — the
        run exits 0 with a cast, a status and a transcript, none of which
        came from the target. The exact handle makes the attach fail where it
        happens, and the failure path releases the claim (R25's rule).
        """
        r, _cast = _run_capture_block(
            "tmux-screen-recording.md", "pipegap", tmp_path, target=True)
        assert r.returncode != 0, (
            "the transcript pipe attached to the grouped session the target "
            "left behind, so this run recorded a session it did not target "
            "and reported success: " + r.stderr)
        assert "could not stream" in r.stderr, r.stderr
        assert not (tmp_path / "cap" / "transcript.log").exists(), (
            "the pipe wrote a transcript after the target session was gone, "
            "so it streamed the grouped session instead")
        assert not (tmp_path / "state" / "claim.pm-test~1").exists(), (
            "the failed pipe left a capture-dir claim behind")

    def test_tmux_recorder_exiting_before_drawing_fails(self, tmp_path):
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "dies", tmp_path, target=True)
        assert r.returncode != 0, "a recorder that never drew was reported as success"
        assert "recorder exited before it drew" in r.stderr, r.stderr

    def test_tmux_readiness_timeout_saves_the_pane(self, tmp_path):
        """The readiness message must not point at the session it kills.

        The timeout branch kills ``pm-recorder`` and then told the worker to
        inspect it with ``capture-pane`` — verified live that the follow-up
        answers "no server running". The pane is saved first, and the message
        names the file.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "norec", tmp_path, target=True)
        assert r.returncode != 0, r.stderr
        assert "did not come up within" in r.stderr, r.stderr
        assert "recorder-pane.log" in r.stderr, (
            "the readiness failure does not say where the pane was saved: "
            + r.stderr)
        assert (cast.parent / "recorder-pane.log").exists(), (
            "the failing wait left no pane evidence")

    def test_tmux_readiness_timeout_names_a_pane_it_could_not_save(
            self, tmp_path):
        """The readiness message must not claim a save the pane refused.

        The save is a write, and the timeout branch runs a whole bound after
        the capture-directory guard: a directory that became read-only, a full
        disk, or a recorder whose pane went away in the gap makes the redirect
        fail. The message then said "the pane is saved in …" for a file
        nothing wrote — the rule R87 fixed at the other three pane saves, at
        the two sites it missed. The branch also kills the recorder, so the
        pane is gone by the time a worker could look.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "nopane", tmp_path, target=True)
        assert r.returncode != 0, r.stderr
        assert "did not come up within" in r.stderr, r.stderr
        assert "could not be saved" in r.stderr, (
            "the readiness failure claims a save that did not land: "
            + r.stderr)
        assert "is saved in" not in r.stderr, (
            "the readiness failure claims the pane was saved: " + r.stderr)
        # The redirect creates the file before `capture-pane` fails, so it can
        # be there — but it holds nothing, which is what "could not be saved"
        # says.
        log = cast.parent / "recorder-pane.log"
        assert not log.exists() or log.stat().st_size == 0, (
            "the failing wait saved pane content it said it could not save")

    def test_tmux_stop_timeout_saves_the_pane(self, tmp_path):
        """A stop timeout has to keep what the recorder last drew."""
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "stuck", tmp_path, target=True)
        assert r.returncode != 0, r.stderr
        assert "did not exit within" in r.stderr, r.stderr
        assert "recorder-pane.log" in r.stderr, r.stderr
        # This branch kills the recorder, so the cast stops where it stopped
        # and `recorder.status` is never written. Every other step-5 failure
        # says the recording is incomplete; this one used to leave a truncated
        # cast in the capture directory with no statement that it is truncated
        # — a worker could render it or list it as this run's evidence.
        assert "incomplete" in r.stderr, (
            "the stop timeout leaves a truncated cast behind but never says "
            "it is truncated, so the worker can present it as this run's "
            "recording: " + r.stderr)
        log = cast.parent / "recorder-pane.log"
        assert log.exists() and "TUI drawn" in log.read_text(), (
            "the stop failure did not save what the recorder drew")

    def test_tmux_stop_timeout_names_a_pane_it_could_not_save(self, tmp_path):
        """The stop timeout must not claim a save the directory refused.

        Step 5's guard requires ``-d``/``-x`` but not ``-w`` (a capture
        directory that became read-only must not refuse a finish that can
        still be validated, R84), and its timeout path saves the pane into
        that directory. With a mode-500 directory the redirect fails, so no
        ``recorder-pane.log`` exists; the shipped message still said "The pane
        is saved in …" (verified in this container: the shell answered
        "Permission denied", the file was absent, and the message named it as
        saved).
        """
        if not hasattr(os, "geteuid") or os.geteuid() == 0:
            pytest.skip("root bypasses the directory permission bits")
        cap = tmp_path / "cap"
        cap.mkdir()
        cap.chmod(0o500)
        try:
            r, _cast = _run_block(
                _stop_block("tmux-screen-recording.md"), "stuck", tmp_path,
                target=True, sessions=("pm-recorder",), capture=cap,
                state_files={"pane": "TUI drawn\n"})
        finally:
            cap.chmod(0o700)
        assert r.returncode != 0, r.stderr
        assert "did not exit within" in r.stderr, r.stderr
        assert "could not be saved" in r.stderr, (
            "the timeout does not say the pane save failed: " + r.stderr)
        assert "The pane is saved" not in r.stderr, (
            "the timeout claims the pane was saved although the capture "
            "directory refused the write: " + r.stderr)
        assert "recorder-pane.log" in r.stderr, r.stderr
        assert not (cap / "recorder-pane.log").exists(), (
            "the read-only capture directory somehow holds the pane log")

    def test_tmux_failed_attach_that_drew_its_error_fails(self, tmp_path):
        """The attach error text is content, so it must not count as readiness.

        ``tmux attach`` to a missing session prints "can't find session: …"
        into the recorder pane and exits a few milliseconds later; a content
        poll takes that as a drawn TUI. The settle re-check after the content
        appears is what turns it into a failure.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "failedattach", tmp_path, target=True)
        assert r.returncode != 0, (
            "a failed attach's error text was accepted as a drawn TUI")
        assert "recorder exited before it drew" in r.stderr, r.stderr

    def test_tmux_recorder_dying_mid_scenario_fails(self, tmp_path):
        """A truncated cast must not be reported as a finished recording."""
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "midadied", tmp_path, target=True)
        assert r.returncode != 0, (
            "a recorder that died mid-scenario passed on its truncated cast")
        assert "incomplete" in r.stderr, r.stderr

    def test_tmux_stop_step_pasted_twice_is_not_an_incomplete_recording(
            self, tmp_path):
        """A recorder that already ended cleanly is not a mid-scenario death.

        Step 5 is pasted on its own whenever the scenario is driven
        interactively, and a resumed session pastes it again. After a clean
        detach the recorder is gone, the TUI it attached to is still up, and
        ``recorder.status`` holds ``0`` — the shape a recorder killed
        mid-scenario leaves, except that a killed recorder's pane shell dies
        before writing the status (verified on tmux 3.2a: ``kill-session``
        left no ``recorder.status``, while the detach left ``0``). Judging by
        the session alone reported a *complete* recording as "the cast is
        incomplete, not a finished recording" and told the worker to
        re-record it, discarding a finished capture.

        The claim is clear here because the first paste released it as its
        last statement; that is the handle which keeps this acceptance from
        covering a detach that ended the recording early (see
        ``test_tmux_recorder_detached_from_outside_is_not_a_finished_recording``).
        """
        r, _cast = _run_block(
            _stop_block("tmux-screen-recording.md"), "ok", tmp_path,
            target=True,
            files={"recording.cast": '{"version": 2}\n',
                   "transcript.log": "pane output\n",
                   "recorder.status": "0\n"})
        assert r.returncode == 0, (
            "a finished recording was reported incomplete because step 5 was "
            "pasted twice: " + r.stderr)
        assert "incomplete" not in r.stderr, r.stderr

    def test_tmux_recorder_detached_from_outside_is_not_a_finished_recording(
            self, tmp_path):
        """A detach this step did not send ends the recording early.

        asciinema's status is 0 whenever the recording ran to completion, and
        *any* detach ends it that way: the prefix pressed in the recorder
        pane, `pm session --disconnect-others`, a supervisor detaching
        clients. The state is exactly the one the re-paste case above accepts
        (recorder gone, TUI alive, `recorder.status` 0), so the status alone
        cannot tell a finished capture from one that stopped where the
        scenario was — the completion check the PR exists to close.

        The capture-directory claim (step 2) is the handle that can: a capture
        in progress holds it, and step 5 releases it as its last statement, so
        a re-paste finds it clear. Verified live in this container on tmux
        3.2a + asciinema 2.1.0 with the recipe's own recorder and step-5
        block: a `C-b d` sent from outside left status 0, a non-empty cast,
        a non-empty transcript and the claim still set, and the pre-fix step 5
        exited 0 on it.
        """
        r, _cast = _run_block(
            _stop_block("tmux-screen-recording.md"), "ok", tmp_path,
            target=True,
            state_files={"claim.pm-test": str(tmp_path / "cap")},
            files={"recording.cast": '{"version": 2}\n',
                   "transcript.log": "pane output\n",
                   "recorder.status": "0\n"})
        assert r.returncode != 0, (
            "a recorder detached from outside passed as a finished "
            "recording: " + r.stderr)
        assert "still in progress" in r.stderr, (
            "the early end was not named as a capture still in progress: "
            + r.stderr)
        assert not (tmp_path / "state" / "claim.pm-test").exists(), (
            "the refusal left the claim behind, so the next attempt in this "
            "session is refused by a capture that is no longer running")

    def test_a_rejected_capture_is_not_a_finished_recording_on_a_repaste(
            self, tmp_path):
        """The state this step's own refusal leaves must not pass a second paste.

        The early-end refusal above releases the capture-dir claim (R25) and
        the status it read is 0, so the state it leaves — recorder gone, TUI
        alive, status 0, claim clear — is exactly the one the re-paste case
        accepts: the truncated cast the first paste rejected passed the second
        (verified in this container: after that refusal, the same block exited
        0 with no message). The rejection mark set on the session is the handle
        that survives the claim's release; step 2 clears it for a new capture.
        """
        cap = tmp_path / "cap"
        r, _cast = _run_block(
            _stop_block("tmux-screen-recording.md"), "ok", tmp_path,
            target=True,
            state_files={"claim.pm-test": str(cap)},
            files={"recording.cast": '{"version": 2}\n',
                   "transcript.log": "pane output\n",
                   "recorder.status": "0\n"})
        assert r.returncode != 0, (
            "the fixture was expected to refuse the capture")
        assert "still in progress" in r.stderr, r.stderr
        assert not (tmp_path / "state" / "claim.pm-test").exists(), (
            "the refusal left its claim behind (R25)")
        assert (tmp_path / "state" / "rejected.pm-test").exists(), (
            "the refusal did not mark the capture as rejected, so the state "
            "it leaves reads as a finished recording")

        r2, _ = _run_block(
            _stop_block("tmux-screen-recording.md"), "ok", tmp_path,
            target=True, capture=cap, reuse=True)
        assert r2.returncode != 0, (
            "a second paste of step 5 accepted the truncated cast the first "
            "paste rejected: " + r2.stderr)
        assert "rejected this capture" in r2.stderr, r2.stderr

    def test_clearing_the_rejection_lets_a_second_paste_accept(self, tmp_path):
        """The mark's remedy has to work: a complete recording is not lost.

        The one state the in-progress refusal cannot tell apart is a step 5
        killed after its checks, where the recording is complete. The message
        names the clear for that case; after it a second paste accepts the
        cast, so a complete recording is not discarded by the check that
        exists to protect it.
        """
        cap = tmp_path / "cap"
        r, _cast = _run_block(
            _stop_block("tmux-screen-recording.md"), "ok", tmp_path,
            target=True,
            state_files={"claim.pm-test": str(cap)},
            files={"recording.cast": '{"version": 2}\n',
                   "transcript.log": "pane output\n",
                   "recorder.status": "0\n"})
        assert r.returncode != 0, (
            "the fixture was expected to refuse the capture")
        assert (tmp_path / "state" / "rejected.pm-test").exists(), (
            "the refusal did not mark the capture as rejected, so there is no "
            "mark to clear")
        (tmp_path / "state" / "rejected.pm-test").unlink()
        r2, _ = _run_block(
            _stop_block("tmux-screen-recording.md"), "ok", tmp_path,
            target=True, capture=cap, reuse=True)
        assert r2.returncode == 0, (
            "clearing the rejection mark did not let a second paste accept "
            "the recording, so the documented remedy cannot work: "
            + r2.stderr)

    def test_step_two_clears_a_previous_rejection(self, tmp_path):
        """A re-record is not refused by the attempt it replaces.

        Step 5 marks a capture it rejects on the session, and step 2 takes the
        claim for the new attempt — so the mark has to go with it. Left
        behind, the re-record's own step 5 would refuse it for a capture that
        no longer exists, the stale-state shape the claim's release rules out.
        """
        r, _cast = _run_block(
            _step_two_block(), "ok", tmp_path, target=True,
            state_files={"rejected.pm-test": "1\n"})
        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "state" / "rejected.pm-test").exists(), (
            "step 2 took the claim but left the previous attempt's rejection "
            "mark, so this capture's step 5 refuses it")

    def test_tmux_detach_that_fails_is_not_a_finished_recording(self, tmp_path):
        """The detach itself is the last handle that can race the recorder.

        Step 5 checks the recorder is alive and then sends the detach. If the
        recorder dies in that gap, ``send-keys`` fails, the stop wait exits at
        once on the gone session, and ``test -s`` passes on the truncated cast
        — an incomplete recording reported as a successful one. The failed
        detach has to fail the run.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "detachfail", tmp_path, target=True)
        assert r.returncode != 0, (
            "a detach that failed because the recorder was already gone was "
            "reported as a finished recording")
        assert "incomplete" in r.stderr, r.stderr

    def test_tmux_detach_race_with_the_sessions_own_end_passes(self, tmp_path):
        """A quit that races the detach is not a truncated recording.

        The same failed ``send-keys`` has two causes. The one above is a
        recorder that died mid-scenario while the session it attached to is
        still there — a truncated cast. The other is the scenario ending the
        pm session itself, with the quit racing the key send: the attach
        followed the session out, so the recorder is already gone and the key
        has nowhere to go. That is exactly the "both gone" finish step 5
        accepts when it happens a moment earlier, and reporting it as "the
        cast is incomplete" fails a complete recording. The session is the
        witness — when it is gone too, asciinema's own status decides (0 for
        a recording that ran to completion).
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "detachboth", tmp_path, target=True)
        assert r.returncode == 0, (
            "a complete recording whose pm session ended as the detach was "
            "sent was reported as an incomplete one: " + r.stderr)
        assert cast.stat().st_size > 0

    def test_tmux_detach_race_still_fails_on_a_killed_recorder(self, tmp_path):
        """The widened branch must not pass a recorder that was killed.

        With the session gone as well there is no live witness, so the
        status handle is what decides — the same rule the both-gone branch
        already follows. A recorder killed as the session ended leaves 137,
        and the run must still fail rather than accept the truncated cast.
        """
        r, _cast = _run_capture_block(
            "tmux-screen-recording.md", "detachbothbad", tmp_path, target=True)
        assert r.returncode != 0, (
            "a killed recorder passed as a finished recording once the "
            "session was gone too")
        assert "incomplete" in r.stderr, r.stderr
        assert "137" in r.stderr, r.stderr

    def test_tmux_detach_uses_the_servers_prefix(self, tmp_path):
        """The detach key is the server's prefix, not a hard-coded ``C-b``.

        ``~/.tmux.conf`` may set another prefix (the dev container this recipe
        was exercised in sets ``C-\\``), and the attach client then treats
        ``C-b d`` as ordinary input to the TUI: verified live, the recorder
        stayed up, the pane showed the keys, and the stop wait ran out its
        bound and reported a timeout that named neither cause. Step 5 asks the
        server for its prefix and sends that. Against the pre-fix recipe (a
        literal ``C-b``) this run times out with the recorder still up.
        """
        r, _cast = _run_block(
            _stop_block("tmux-screen-recording.md"), "prefix", tmp_path,
            target=True, sessions=("pm-recorder",),
            files={"recording.cast": '{"version": 2}\n',
                   "recorder.status": "0\n",
                   "transcript.log": "pane output\n"},
            env_extra={"STUB_PREFIX": "C-a"})
        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "state" / "pm-recorder").exists(), (
            "the detach did not end the recorder: the key sent was not the "
            "prefix this server uses")
        assert "show-options -gv prefix" in _recipe_text(
            "tmux-screen-recording.md"), (
            "step 5 does not ask the server for its prefix")

    def test_tmux_recording_that_ends_with_the_session_passes(self, tmp_path):
        """Both gone before the detach is a legitimate finish, not a failure.

        The scenario ended the pm session itself, which ended the attach and
        so the recording. Failing here would reject a complete recording; and
        the pipe cleanup must not print an error for a session that is gone.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "midboth", tmp_path, target=True)
        assert r.returncode == 0, r.stderr
        assert cast.stat().st_size > 0
        assert "can't find session" not in r.stderr, r.stderr

    def test_tmux_recorder_killed_with_the_session_gone_fails(self, tmp_path):
        """A truncated cast must not pass just because the session ended too.

        "Recorder gone *and* target gone" is treated as a legitimate finish
        because the attach client follows the session — that explains why the
        recorder exited, not whether asciinema finished. A recorder that was
        killed mid-scenario and a session teardown (or a session that ended
        moments after the recorder died) leave the two indistinguishable to
        `test -s`: no witness is left, which is exactly the CLI pane's
        situation, and the header-only cast is reported as a successful
        recording. asciinema's own exit status is the handle that tells them
        apart.
        """
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "midbothbad", tmp_path, target=True)
        assert cast.stat().st_size > 0, "the fixture left no cast to misread"
        assert r.returncode != 0, (
            "a recorder that was killed mid-scenario was reported as a "
            "finished recording once the target session was gone as well")
        assert "incomplete" in r.stderr, r.stderr
        assert "137" in r.stderr, (
            "the failure does not say how the recorder ended: " + r.stderr)

    def test_tmux_driving_step_refuses_an_unresolvable_target(self, tmp_path):
        """``pm tui send -s ""`` auto-detects, so an unset target drives a guess.

        The driving steps are their own paste for a scenario, so ``$TARGET``
        from step 1 is gone. An empty one is not a harmless no-op: ``pm tui
        send -s ""`` falls back to the cwd's session and then to *any* pm
        session with a TUI, so the keys can drive a different TUI than the one
        being recorded — with no error at all, and a cast that never showed the
        behaviour. The step re-derives the handle as step 5 does, and refuses
        an empty one.
        """
        r, _cast = _run_block(_driving_block(), "ok", tmp_path,
                              env_extra={"STUB_PM_NAME": ""})
        assert r.returncode != 0, (
            "the driving step ran with no target session, so its sends would "
            "go to whatever session `pm tui send` auto-detects")
        assert "TARGET is unset" in r.stderr, r.stderr

    def test_tmux_driving_step_sends_to_the_derived_session(self, tmp_path):
        """The re-derivation has to produce the handle the sends carry."""
        log = tmp_path / "sends"
        r, _cast = _run_block(_driving_block(), "ok", tmp_path,
                              env_extra={"STUB_PM_SEND_LOG": str(log)})
        assert r.returncode == 0, r.stderr
        sends = log.read_text().splitlines()
        assert sends and all("-s pm-test" in line for line in sends), (
            "the driving step's sends do not carry the re-derived session: "
            + repr(sends))

    def test_tmux_driving_step_stops_when_a_send_fails(self, tmp_path):
        """A failed send is checked, not left for step 5 to misread.

        The prose above the example sends said to check them, but the lines
        themselves were unchecked, so a *mid-sequence* failure was invisible:
        the block's exit status is its last command's, so a first send that
        failed and a second that succeeded ended with rc 0 (verified against
        the pre-fix recipe, stub ``pm``: first send exits 1, second exits 0 →
        rc 0, only the stub's own stderr). The run then reached step 5, which
        sees the recorder and the session both gone, calls it a legitimate
        finish, and passes a cast that stops before the behaviour under test.
        The check has to be in the block, because the comment is not what a
        worker pastes.
        """
        log = tmp_path / "sends"
        r, _cast = _run_block(_driving_block(), "sendfail", tmp_path,
                              env_extra={"STUB_PM_SEND_LOG": str(log)})
        assert r.returncode != 0, (
            "the driving step ran on after a failed pm tui send, so a cast "
            "that never showed the behaviour can reach step 5 as a finish")
        assert "pm tui send failed" in r.stderr, r.stderr
        sends = log.read_text().splitlines()
        assert len(sends) == 1, (
            "the driving step sent more keys after a send had failed, so the "
            "scenario was driven against a dead or different TUI: "
            + repr(sends))

    def test_a_failed_send_tears_the_run_down(self, tmp_path):
        """The failed send ends the run, so it must not leave it recording.

        A failed ``pm tui send`` does not prove the pm session is gone: the
        pane is looked up in the pane registry, so a stale entry fails the
        send while the session — and with it the transcript pipe and the
        recorder, which follows the session — keeps running. Left alone, the
        recorder writes into a capture directory the worker is about to clear
        and re-record, and the claim on the session makes the next attempt
        look like a collision. The failure path saves the pane it destroys,
        tears the recorder down, stops the pipe and releases the claim, like
        every other failure path in this recipe.
        """
        r, cast = _run_block(
            _driving_block(), "sendfail", tmp_path, target=True,
            sessions=("pm-recorder",),
            state_files={"pane": "TUI drawn\n",
                         "claim.pm-test": str((tmp_path / "cap").resolve())})
        assert r.returncode != 0, r.stderr
        assert "pm tui send failed" in r.stderr, r.stderr
        state = tmp_path / "state"
        assert not (state / "pm-recorder").exists(), (
            "the failed send left the recorder running into the capture dir")
        assert not (state / "claim.pm-test").exists(), (
            "the failed send left the capture-dir claim on the session")
        log = cast.parent / "recorder-pane.log"
        assert log.exists() and "TUI drawn" in log.read_text(), (
            "the failure tore the recorder pane down without saving it")

    def test_tmux_driving_step_names_a_pane_it_could_not_save(self, tmp_path):
        """The failed-send message must not claim a save the directory refused.

        Step 4's directory guard requires ``-d``/``-x`` but not ``-w`` — a
        capture directory that became read-only must not refuse a finish that
        can still be validated (R84) — and its failure path saves the recorder
        pane into that directory. With a mode-500 directory the redirect
        fails, so no ``recorder-pane.log`` exists; the shipped message still
        said the pane "is saved in …" (verified in this container: the shell
        answered "Permission denied", the file was absent, and the message
        named it as saved).
        """
        if not hasattr(os, "geteuid") or os.geteuid() == 0:
            pytest.skip("root bypasses the directory permission bits")
        cap = tmp_path / "cap"
        cap.mkdir()
        cap.chmod(0o500)
        try:
            r, _cast = _run_block(
                _driving_block(), "sendfail", tmp_path, target=True,
                sessions=("pm-recorder",), capture=cap,
                state_files={"pane": "TUI drawn\n"})
        finally:
            cap.chmod(0o700)
        assert r.returncode != 0, r.stderr
        assert "pm tui send failed" in r.stderr, r.stderr
        assert "could not be saved" in r.stderr, (
            "the failed send does not say the pane save failed: " + r.stderr)
        assert "is saved in" not in r.stderr, (
            "the failed send claims the pane was saved although the capture "
            "directory refused the write: " + r.stderr)
        assert "recorder-pane.log" in r.stderr, r.stderr
        assert not (cap / "recorder-pane.log").exists(), (
            "the read-only capture directory somehow holds the pane log")

    @pytest.mark.parametrize("name", RECIPES)
    def test_stop_block_pasted_alone_saves_the_pane(self, name, tmp_path):
        """The stop step runs in a fresh shell, so its failure path must too.

        A scenario that needs interactive driving cannot paste the whole
        capture block (step 3 *is* the driving), so step 4/5 is pasted on its
        own. The pane save used to be a function defined back in the first
        block: verified that the fresh shell printed ``dump_pane: command not
        found`` and the timeout message named a ``recorder-pane.log`` that was
        never written — a failure message pointing at evidence that does not
        exist, which is the bug class this recipe keeps hitting.
        """
        sessions = ("rec",) if name.startswith("cli") else ("pm-recorder",)
        r, cast = _run_block(
            _stop_block(name), "stuck", tmp_path, target=True,
            sessions=sessions,
            files={"recording.cast": '{"version": 2}\n'},
            state_files={"pane": "TUI drawn\n"},
            env_extra={"RECORDER_STOP_TIMEOUT": "2"})
        assert r.returncode != 0, r.stderr
        assert "did not exit within" in r.stderr, r.stderr
        assert "command not found" not in r.stderr, (
            "the stop block depends on a shell function from an earlier "
            "paste: " + r.stderr)
        log = cast.parent / "recorder-pane.log"
        assert log.exists() and "TUI drawn" in log.read_text(), (
            "the stop failure names recorder-pane.log but nothing was saved "
            "there")

    def test_tmux_stop_block_rederives_the_target_session(self, tmp_path):
        """An empty target matches *every* session, so the both-gone branch lies.

        Step 5 is pasted on its own for a driven scenario, so ``$TARGET`` from
        step 1 is gone. Verified against real tmux 3.2a: ``has-session -t ''``
        succeeds, so the legitimate "the scenario ended the pm session" finish
        was reported as "recorder exited while the TUI was still running" —
        and ``pipe-pane -t ':0.0'`` would stream whatever pane tmux picks as
        current instead of the target's.
        """
        r, cast = _run_block(
            _stop_block("tmux-screen-recording.md"), "midboth", tmp_path,
            files={"recording.cast": '{"version": 2}\n',
                   "transcript.log": "pane output\n",
                   "recorder.status": "0\n"})
        assert cast.stat().st_size > 0, "the fixture left no cast to misread"
        assert r.returncode == 0, (
            "a legitimate finish was rejected because the stop block ran with "
            "an empty target: " + r.stderr)

    def test_tmux_stop_block_refuses_an_unresolvable_target(self, tmp_path):
        """With no target at all, say so instead of acting on an empty one."""
        r, _cast = _run_block(
            _stop_block("tmux-screen-recording.md"), "midboth", tmp_path,
            files={"recording.cast": '{"version": 2}\n',
                   "transcript.log": "pane output\n",
                   "recorder.status": "0\n"},
            env_extra={"STUB_PM_NAME": ""})
        assert r.returncode != 0, (
            "the stop block ran with no target session at all")
        assert "TARGET is unset" in r.stderr, r.stderr

    def test_step_three_rederives_the_target_session(self, tmp_path):
        """Step 3 is pasted alone too, so it must not act on an empty target.

        Step 3 was the one step that used ``$TARGET`` without re-deriving it
        (steps 2, 4 and 5 do, each because it is pasted on its own). An empty
        target is not a no-op there: the recorder's ``tmux attach -t =`` fails
        ("no mouse target", verified on tmux 3.2a), so the run dies at the
        readiness check as "recorder exited before it drew" for a target that
        was never set — and the failure paths' ``-t "=:0.0"`` is accepted by a
        real server and resolves to whatever session it treats as current
        (verified on 3.2a: ``pipe-pane -t '=:0.0'`` and
        ``set-option -u -t '=:0.0'`` both exit 0 on the current session), so a
        failed start could stop another run's transcript pipe and clear its
        capture-directory claim — the collision the claim exists to prevent.
        """
        calls = tmp_path / "tmux-calls"
        r, _cast = _run_block(
            _step_three_block(), "ok", tmp_path,
            env_extra={"STUB_PM_NAME": "", "STUB_TMUX_LOG": str(calls)})
        assert r.returncode != 0, (
            "step 3 ran with no target session at all")
        assert "TARGET is unset" in r.stderr, r.stderr
        assert not calls.exists(), (
            "a step that could not resolve its target acted on one anyway: "
            + (calls.read_text() if calls.exists() else ""))

        derived = tmp_path / "derived"
        derived.mkdir()
        calls.unlink(missing_ok=True)
        r, _cast = _run_block(
            _step_three_block(), "ok", derived, target=True,
            state_files={"pipe.pm-test": ""},
            env_extra={"STUB_TMUX_LOG": str(calls)})
        assert r.returncode == 0, r.stderr
        assert "=pm-test" in calls.read_text(), (
            "the recorder was not started against the re-derived target: "
            + calls.read_text())

    def test_step_three_refuses_a_target_that_is_not_an_exact_session(
            self, tmp_path):
        """A recorder restarted against a missing target dies on the attach.

        Step 3 is pasted on its own when a run restarts its recorder, which
        is why it re-derives ``$TARGET`` and refuses an empty one. A target
        that is set but not there is the same hole one shape over: with only
        a grouped ``pm-test~1`` session on the server (pm creates one per
        extra co-viewing client) the pane command's exact attach cannot land
        on it, so the recorder records "can't find session: pm-test" and
        exits before it draws — and the readiness wait reports "recorder
        exited before it drew — see the cast and
        <capture-dir>/recorder-stderr.log" for a target that is simply not
        there, naming a stderr log that is empty (verified live in this
        container on tmux 3.2a + asciinema 2.1.0: step 3 alone with only
        ``pm-test~1`` on the server wrote a 0-byte recorder-stderr.log and a
        168-byte cast holding only the attach error, then exited 1 with that
        message). Step 2 asserts the same handle before it reads the claim;
        step 3 has to refuse it before the recorder session is created.
        """
        r, _cast = _run_block(_step_three_block(), "ok", tmp_path,
                              sessions=("pm-test~1",))

        assert r.returncode != 0, (
            "step 3 started a recorder for a target session that does not "
            "exist exactly, so its attach could only fail")
        assert "no session named exactly" in r.stderr, r.stderr
        assert "recorder exited before it drew" not in r.stderr, (
            "the refused step blamed the recorder for a missing target: "
            + r.stderr)
        assert not (tmp_path / "state" / "pm-recorder").exists(), (
            "a step with no target session created the recorder anyway")

    def test_step_three_restart_clears_the_previous_attempt(self, tmp_path):
        """The restart step must not inherit the attempt it replaces.

        ``_step_three_block`` is pasted on its own to restart a recorder (the
        recipe says so), and the attempt being replaced left its cast, its
        status and its stderr log in the capture directory — step 0 clears
        them only for a fresh run. Verified live in this container on tmux
        3.2a + asciinema 2.1.0: step 3 alone with a previous attempt's cast
        exited 1 with "recorder exited before it drew" while
        ``recorder-stderr.log`` held "already exists, aborting" — the restart
        could not start at all. And with the cast out of the way the old
        ``recorder.status`` ``0`` survived the restart: killing the restarted
        recorder mid-scenario left the ``0``, and step 5 exited 0 on the cast
        it had written so far. Both files belong to the attempt being
        replaced, so the start clears them. The render outputs and the
        manifest go too (R97): the video was rendered from the cast this clear
        deletes, so a restart that fails before the render step would leave
        the previous attempt's mp4 (or its interrupted partial) as the only
        video in the directory, with a manifest naming files that are gone —
        the stale state step 0's own clear exists for, one paste over.
        """
        cap = tmp_path / "cap"
        r, cast = _run_block(
            _step_three_block(), "dies", tmp_path, target=True,
            state_files={"pipe.pm-test": ""},
            files={"recording.cast": "previous attempt cast\n",
                   "recorder.status": "0\n",
                   "recorder-stderr.log": "previous failure\n",
                   "recording.mp4": "previous video\n",
                   "recording.cast.gif": "previous gif\n",
                   "recording.mp4.partial.mp4": "previous partial\n",
                   "manifest.md": "previous manifest\n"})

        assert r.returncode != 0, r.stderr
        assert "recorder exited before it drew" in r.stderr, r.stderr
        assert not cast.exists(), (
            "the restart kept the previous attempt's cast, so asciinema "
            "refuses to start ('already exists, aborting')")
        assert not (cap / "recorder.status").exists(), (
            "the restart kept the previous attempt's recorder.status, so a "
            "recorder killed before writing its own reads as a clean finish")
        assert not (cap / "recorder-stderr.log").exists(), (
            "the restart kept the previous attempt's recorder-stderr.log, "
            "which the readiness failure names as this attempt's evidence")
        for name in ("recording.mp4", "recording.cast.gif",
                     "recording.mp4.partial.mp4", "manifest.md"):
            assert not (cap / name).exists(), (
                f"the restart kept the previous attempt's {name}, which the "
                "manifest would present as this attempt's evidence although "
                "the cast it came from was cleared")

    def test_a_restarted_recorder_killed_before_its_status_is_not_a_finish(
            self, tmp_path):
        """The status step 5 trusts has to belong to the attempt it judges.

        A restarted recorder that is killed before its pane shell writes the
        status leaves a partial cast and *no* status file. With the previous
        attempt's ``0`` still there, step 5's both-gone branch read it as a
        clean finish and exited 0 on the truncated cast (verified live in this
        container on tmux 3.2a + asciinema 2.1.0: after a clean first
        attempt, step 3 alone started a new recorder with the old ``0`` on
        disk; killing that recorder left the ``0``, and step 5 exited 0).
        Step 3 now clears it, so the same state is the missing-status failure
        it looks like.
        """
        cap = tmp_path / "cap"
        r, cast = _run_block(
            _step_three_block(), "dies", tmp_path, target=True,
            state_files={"pipe.pm-test": ""},
            files={"recording.cast": "previous attempt cast\n",
                   "recorder.status": "0\n"})
        assert r.returncode != 0, r.stderr
        # The restarted recorder wrote part of a cast and was killed before
        # its pane shell could write a status.
        cast.write_text('{"version": 2}\n')
        (cap / "transcript.log").write_text("pane output\n")

        second = tmp_path / "second"
        second.mkdir()
        r2, _ = _run_block(
            _stop_block("tmux-screen-recording.md"), "ok", second,
            target=True, sessions=("pm-test",), capture=cap)

        assert r2.returncode != 0, (
            "step 5 read the previous attempt's status as this attempt's "
            "clean finish: " + r2.stderr)
        assert "cast is incomplete" in r2.stderr, r2.stderr

    def test_step_three_refuses_a_live_recorder_without_clearing_its_evidence(
            self, tmp_path):
        """A live recorder owns the cast it is writing.

        Step 3 is pasted on its own, and a second paste while the recorder is
        still up (a worker checking its work) must not delete the evidence
        that recorder is producing. The refusal comes before the clear, so
        the live attempt's cast and status survive and the message names the
        step that ends the recorder.
        """
        cap = tmp_path / "cap"
        calls = tmp_path / "tmux-calls"
        r, cast = _run_block(
            _step_three_block(), "ok", tmp_path, target=True,
            sessions=("pm-recorder",),
            files={"recording.cast": "live attempt cast\n",
                   "recorder.status": "0\n"},
            env_extra={"STUB_TMUX_LOG": str(calls)})

        assert r.returncode != 0, (
            "step 3 started a second recorder beside a live one")
        assert "already running" in r.stderr, r.stderr
        assert "step 5" in r.stderr, (
            "the refusal does not name the step that ends the recorder: "
            + r.stderr)
        assert cast.read_text() == "live attempt cast\n", (
            "the refused restart cleared the live recorder's cast")
        assert (cap / "recorder.status").read_text() == "0\n", (
            "the refused restart cleared the live recorder's status")
        assert "new-session" not in calls.read_text(), (
            "a step that refused a live recorder still started a session: "
            + calls.read_text())

    def test_step_three_clears_a_leftover_recorder_whose_pane_has_returned(
            self, tmp_path):
        """A dead pane is not a running recorder (R96).

        With `set -g remain-on-exit on` — this project's own QA notes
        prescribe it for a shared pane — the recorder's session outlives its
        pane, so `has-session` alone read a leftover from a finished or
        abandoned run as a live recorder: the restart stopped at "a recorder
        is already running on this server" and named a kill-session remedy for
        a pane whose command had already returned (verified on tmux 3.2a: the
        session survives its pane and `#{pane_dead}` is 1). The pane's own
        state tells the two apart, and a dead leftover writes nothing, so the
        step clears it like step 0's — `new-session` fails with "duplicate
        session" while it exists — and starts the restart.
        """
        calls = tmp_path / "tmux-calls"
        r, _ = _run_block(
            _step_three_block(), "ok", tmp_path, target=True,
            sessions=("pm-recorder",),
            state_files={"dead.pm-recorder": "", "pipe.pm-test": ""},
            files={"recording.cast": "abandoned attempt cast\n",
                   "recorder.status": "0\n"},
            env_extra={"STUB_TMUX_LOG": str(calls), "STUB_REMAIN": "1"})

        assert r.returncode == 0, (
            "step 3 refused a leftover recorder whose pane had returned: "
            + r.stderr)
        assert "already running" not in r.stderr, r.stderr
        log = calls.read_text()
        assert "kill-session -t =pm-recorder" in log, (
            "step 3 did not clear the dead leftover session, so new-session "
            "would fail with a duplicate session: " + log)
        assert "new-session" in log, (
            "step 3 cleared the dead leftover but never started a recorder: "
            + log)

    def test_step_three_refuses_a_restart_without_the_transcript_pipe(
            self, tmp_path):
        """A restart is not a fresh start: step 2's pipe has to be there.

        Every failure path in the flow stops the transcript pipe, and step 5
        requires a non-empty transcript. A step-3 restart pasted after a
        failure therefore started a recorder with no pipe: the transcript
        stopped growing at the failure, and step 5's ``test -s`` passed on the
        replaced attempt's bytes — a completed recording reported against a
        transcript that does not cover it, the same stale-evidence shape as a
        leftover cast. ``#{pane_pipe}`` is the handle (1 while a pipe is
        attached, 0 otherwise, verified on tmux 3.2a), and the refusal names
        step 2, which re-takes the claim the failure released and appends to
        the same transcript.
        """
        cap = tmp_path / "cap"
        calls = tmp_path / "tmux-calls"
        r, cast = _run_block(
            _step_three_block(), "ok", tmp_path, target=True,
            files={"recording.cast": "previous attempt cast\n",
                   "recorder.status": "0\n"},
            env_extra={"STUB_TMUX_LOG": str(calls)})

        assert r.returncode != 0, (
            "step 3 started a recorder with no transcript pipe attached, so "
            "step 5 would pass on the replaced attempt's transcript")
        assert "no transcript pipe" in r.stderr, r.stderr
        assert "step 2" in r.stderr, (
            "the refusal does not name the step that re-attaches the pipe: "
            + r.stderr)
        assert "new-session" not in calls.read_text(), (
            "a step refused for a missing transcript pipe still started a "
            "recorder: " + calls.read_text())
        assert cast.read_text() == "previous attempt cast\n", (
            "the refused restart cleared the replaced attempt's cast")

    def test_a_restart_after_a_failure_cannot_pass_on_the_stale_transcript(
            self, tmp_path):
        """The pipe a failure stops is the one step 5's check depends on.

        Step 2 attaches the transcript pipe; every failure path in the flow
        stops it with ``tmux pipe-pane -t "=…:0.0"``. A step-3 restart pasted
        after that failure used to start a recorder with no pipe, so the
        transcript stopped at the failure and step 5's ``test -s`` passed on
        the bytes step 2 had written (verified with this harness before the
        guard: step 2, the failure paths' pipe stop, step 3 and step 5 exited
        0 on the unchanged transcript). The restart now refuses and names
        step 2.
        """
        scaffold = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        step2 = scaffold[scaffold.index("# 2."):scaffold.index("# 3.")]
        step3 = scaffold[scaffold.index("# 3."):scaffold.index("# 4.")]
        stop_pipe = 'tmux pipe-pane -t "=pm-test:0.0" 2>/dev/null || true\n'
        r, _cast = _run_block(step2 + stop_pipe + step3, "ok", tmp_path,
                              target=True)

        assert r.returncode != 0, (
            "a restart after a failure started a recorder with no transcript "
            "pipe, so step 5 would pass on the replaced attempt's bytes")
        assert "no transcript pipe" in r.stderr, r.stderr

    def test_reattaching_the_pipe_lets_the_restart_start(self, tmp_path):
        """The refusal names a remedy that works: step 2, then step 3.

        Every failure path stops the pipe and releases the claim, so step 2
        re-takes the claim and re-attaches the pipe (no ``-o``, so the
        stopped one is replaced, and ``>>`` so the transcript keeps the
        replaced attempt's output). Step 3 then sees ``#{pane_pipe}`` = 1 and
        starts the recorder — the restarted attempt's output lands in the
        file step 5 checks.
        """
        scaffold = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        step2 = scaffold[scaffold.index("# 2."):scaffold.index("# 3.")]
        step3 = scaffold[scaffold.index("# 3."):scaffold.index("# 4.")]
        failure_cleanup = (
            'tmux pipe-pane -t "=pm-test:0.0" 2>/dev/null || true\n'
            'tmux set-option -u -t "=pm-test:0.0" @pm_capture_dir '
            '2>/dev/null || true\n')
        calls = tmp_path / "tmux-calls"
        r, _cast = _run_block(step2 + failure_cleanup + step2 + step3, "ok",
                              tmp_path, target=True,
                              env_extra={"STUB_TMUX_LOG": str(calls)})

        assert r.returncode == 0, (
            "the restart the refusal points at (step 2, then step 3) did not "
            "start: " + r.stderr)
        assert "new-session" in calls.read_text(), calls.read_text()
        assert (tmp_path / "cap" / "transcript.log").read_text() == (
            "pane output\npane output\n"), (
            "step 2 did not append to the same transcript, so the restarted "
            "attempt's output would not land in the file step 5 checks")

    @pytest.mark.parametrize("name", RECIPES)
    def test_recorder_session_that_never_starts_is_reported(self, name,
                                                            tmp_path):
        """A failed ``new-session`` is not "the recorder exited".

        Verified with real tmux 3.2a: when the session cannot be created at
        all (the server is gone or refusing — ``tmux new-session`` against a
        missing ``TMUX_TMPDIR`` reports "server exited unexpectedly" — or a
        concurrent run already holds the name, "duplicate session"), the pane
        command never runs. The recipe used to ignore the failure and let the
        readiness/stop checks diagnose it, ending with "recorder exited before
        it drew" / "asciinema wrote no cast" and pointing at a cast and a
        ``recorder-stderr.log`` that were never written. The start has to be
        checked, and the failure named.
        """
        r, cast = _run_capture_block(name, "nostart", tmp_path, target=True)
        assert r.returncode != 0, (
            f"{name}: a recorder session that was never created was reported "
            "as a successful capture")
        assert "could not start the recorder session" in r.stderr, r.stderr
        assert "exited before it drew" not in r.stderr and \
            "wrote no cast" not in r.stderr, (
            f"{name}: the start failure is reported as a recorder that ran "
            "and died, so the worker looks for evidence that does not exist: "
            + r.stderr)
        assert not cast.exists()

    @pytest.mark.parametrize("name", RECIPES)
    def test_capture_dir_that_cannot_be_created_is_reported(self, name,
                                                            tmp_path):
        """An unusable capture directory must be named where it fails.

        Every later step writes into it, and their failures read as something
        else: the transcript redirect and the cast write fail, the recorder
        dies, and the run ends with "recorder exited before it drew" (tmux) or
        the readiness timeout (CLI) — pointing at files that do not exist.
        Verified: with ``<capture-dir>`` under a regular file, the pre-fix
        blocks report the downstream symptom, not the directory.

        The refusal also has to happen *before* the block touches the recorder
        session it shares with concurrent runs: both recipes clear
        ``pm-recorder`` / ``rec`` (one name per server, one socket name per
        host), and that clear used to run first. Verified live on a private
        tmux server: with a concurrent capture's recorder up, a block pasted
        with an uncreatable capture directory killed it and then refused, so
        that run failed as "recorder exited while the TUI was still running" /
        "recorder status is missing" — a failure it could not connect to this
        block. The clear now follows the ``mkdir`` (and the absolute-path
        guard), so a refused block makes no tmux call at all.
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        calls = tmp_path / "tmux-calls"
        r, _cast = _run_block(
            _scaffold_block(_recipe_text(name)), "ok", tmp_path,
            target=True, capture=blocker / "cap",
            env_extra={"STUB_TMUX_LOG": str(calls)})
        assert r.returncode != 0, (
            f"{name}: a capture directory that cannot be created was reported "
            "as a successful capture")
        assert "could not create" in r.stderr, r.stderr
        assert "exited before it drew" not in r.stderr and \
            "did not start within" not in r.stderr, (
            f"{name}: the unusable capture directory is reported as a "
            "recorder problem instead of the directory: " + r.stderr)
        calls_text = calls.read_text() if calls.exists() else ""
        assert "kill-session" not in calls_text, (
            f"{name}: the block cleared the shared recorder session before "
            "refusing a capture directory it cannot create, so a worker "
            "pasting an unusable path kills a concurrent capture's recorder: "
            + calls_text)

    def test_cli_preamble_refuses_an_uncreatable_capture_dir(self, tmp_path):
        """The preamble is a paste of its own, and its `mkdir` has to refuse too.

        ``cli-recording.md`` opens the Capture section with a block that
        creates and clears the capture directory "before any of the forms
        below", and the no-TTY scaffold repeats it for a worker who pastes the
        scaffold whole. ``test_capture_dir_that_cannot_be_created_is_reported``
        runs the *scaffold*, so weakening the preamble's guard to ``|| true``
        left the whole file green — the preamble is the block a worker
        following the recipe top-down pastes, and without the guard the run
        goes on to fail as "asciinema wrote no cast" (the misdiagnosis R15
        fixed for the scaffold). Run the preamble itself: it must stop with
        "could not create" and create nothing.
        """
        preamble = _cli_preamble_block()
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        capture = blocker / "cap"
        block = (preamble.replace("<capture-dir>", str(capture))
                          .replace("<short-name>", "run"))
        bindir = tmp_path / "bin"
        bindir.mkdir()
        _stub_tool(bindir, "tmux", "exit 1\n")
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
        r = subprocess.run(["bash"], input=block, env=env,
                           capture_output=True, text=True, timeout=60)

        assert r.returncode != 0, (
            "the preamble accepted a capture directory it cannot create, so "
            "every form below records into a path that is not there")
        assert "could not create" in r.stderr, r.stderr
        assert not capture.exists()

    def test_cli_preamble_refuses_a_relative_capture_dir(self, tmp_path):
        """The preamble's own copy of the path guard had no case.

        ``test_capture_dir_must_be_absolute`` runs each recipe's *scaffold*, so
        the CLI preamble — the first block under ``## Capture``, and the block
        a worker following the recipe top-down pastes before any of the
        recording forms — was never run with a relative ``<capture-dir>``.
        Deleting its ``case`` guard left the whole file green (verified, 201
        passed), and the preamble then ran on and exited 0 with
        ``relcap/run`` created and cleared in the worker's cwd: the exact
        "writes where the checks never look" state the guard exists for, in
        the paste that precedes every form (the scaffold's own copy refuses
        the path, but only after this block has already written into it).
        """
        block = (_cli_preamble_block()
                 .replace("<capture-dir>", "relcap")
                 .replace("<short-name>", "run"))
        bindir = tmp_path / "bin"
        bindir.mkdir()
        _stub_tool(bindir, "tmux", "exit 1\n")
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
        r = subprocess.run(["bash"], input=block, env=env, cwd=str(tmp_path),
                           capture_output=True, text=True, timeout=60)

        assert r.returncode != 0, (
            "the preamble accepted a relative capture directory, so every "
            "form below records into a path each paste resolves for itself")
        assert "must be an absolute path" in r.stderr, r.stderr
        assert not (tmp_path / "relcap").exists(), (
            "the preamble created a relative capture directory before "
            "refusing it, so it wrote and cleared files in the worker's cwd")

    @pytest.mark.parametrize("name", RECIPES)
    def test_capture_dir_must_be_absolute(self, name, tmp_path):
        """A relative capture dir writes the promised files where nothing looks.

        The steps are pasted into separate shells, and tmux runs the
        transcript pipe's command in the *pm session's* directory rather than
        the shell that pasted it (verified: ``pipe-pane`` from /tmp/b with
        ``cat >> rel.log`` wrote /tmp/a/rel.log). So a relative
        ``<capture-dir>`` puts the transcript (tmux) or the cast (CLI, whose
        pane command and step 4 checks each resolve against their own paste)
        somewhere the end-of-run checks never look, and the run fails as
        "transcript.log is empty" / "asciinema wrote no cast" for a recording
        that finished. Verified live in the tmux recipe: the stop step pasted
        from another directory answered "asciinema wrote no cast" while the
        cast sat in the worker's directory. Step 0 refuses the path instead.
        """
        raw = _scaffold_block(_recipe_text(name))
        block = (raw.replace("<capture-dir>", "relcap")
                    .replace("<short-name>", "run")
                    .replace("<command-to-record>", "echo hi"))
        state = tmp_path / "state"
        bindir = tmp_path / "bin"
        state.mkdir()
        bindir.mkdir()
        _stub_tool(bindir, "tmux", _STUB_TMUX)
        _stub_tool(bindir, "pm", _STUB_PM)
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                   STUB_STATE=str(state), STUB_MODE="ok",
                   STUB_CAST=str(tmp_path / "relcap" / "run"
                                 / "recording.cast"))
        r = subprocess.run(["bash"], input=block, env=env,
                           capture_output=True, text=True, timeout=60,
                           cwd=str(tmp_path))
        assert r.returncode != 0, (
            f"{name}: a relative capture directory was accepted, so the "
            "capture's files land wherever each paste happens to run")
        assert "must be an absolute path" in r.stderr, (
            f"{name}: the relative capture directory is not named: "
            + r.stderr)
        assert not (tmp_path / "relcap").exists(), (
            f"{name}: the block wrote into a relative capture directory "
            "before refusing it")

    def test_cli_refused_capture_dir_does_not_kill_a_recorder(self, tmp_path):
        """A refused block must not take a concurrent capture's recorder down.

        The scaffold's ``-L scaffold`` socket *name* is shared by every CLI
        capture on the host (the step-1 note says so), which is why the block
        clears the leftover ``rec`` session with ``kill-session``. That clear
        ran *before* the absolute-path guard, so a worker who pasted the
        scaffold with an unsubstituted or relative ``<capture-dir>`` — the
        exact mistake the guard exists for — ended a concurrent run's recorder
        on its way out; that run then failed as "recorder status is missing",
        a failure it could not connect to this block. The guard runs first
        now, as step 0 of the tmux recipe already did.
        """
        block = (_scaffold_block(_recipe_text("cli-recording.md"))
                 .replace("<capture-dir>", "relcap")
                 .replace("<short-name>", "run")
                 .replace("<command-to-record>", "echo hi"))
        bindir = tmp_path / "bin"
        bindir.mkdir()
        calls = tmp_path / "tmux-calls"
        # Log every tmux call instead of running it: the point is whether the
        # block touches the shared `rec` session at all.
        _stub_tool(bindir, "tmux", f'printf "%s\\n" "$*" >> "{calls}"\n')
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
        r = subprocess.run(["bash"], input=block, env=env, cwd=str(tmp_path),
                           capture_output=True, text=True, timeout=60)

        assert r.returncode != 0, r.stderr
        assert "must be an absolute path" in r.stderr, r.stderr
        calls_text = calls.read_text() if calls.exists() else ""
        assert "kill-session" not in calls_text, (
            "the scaffold cleared the host-shared `rec` session before "
            "refusing a capture directory it never validated, so a worker "
            "pasting an unsubstituted path kills a concurrent capture's "
            "recorder: " + calls_text)


@pytest.mark.parametrize("name,marker,probe_bound", [
    ("tmux-screen-recording.md", 'until tmux has-session -t "=$TARGET"', None),
    ("web-ui-recording.md", "until curl", "--max-time"),
])
def test_readiness_waits_are_bounded(name, marker, probe_bound):
    """Readiness polls must have a deadline, not just a sleep loop.

    An ``until ...; do sleep; done`` with no deadline hangs the worker
    forever when the session or server never comes up.  The probe itself
    must be bounded too — a deadline is only consulted between attempts, so
    a single blocking call (curl with no timeout) stalls the loop
    regardless.
    """
    text = _recipe_text(name)
    assert marker in text, f"{name}: no readiness poll matching {marker!r}"
    idx = text.index(marker)
    window = text[max(0, idx - 700):idx + 700]
    assert "deadline" in window, f"{name}: unbounded readiness wait"
    assert "exit 1" in window, f"{name}: readiness wait has no failure path"
    if name == "web-ui-recording.md":
        assert 'kill "$SERVER_PID"' in window, (
            "web-ui recipe leaves the server it started running when the "
            "readiness wait fails")
    if probe_bound:
        line = text[idx:text.index("\n", idx)]
        assert probe_bound in line, (
            f"{name}: readiness probe is unbounded (no {probe_bound})")


@pytest.mark.parametrize("name", RECIPES + ["web-ui-recording.md"])
def test_every_deadline_is_a_real_bound_and_its_message_agrees(name):
    """The bound's *value* needs a guard the execution cases cannot give.

    ``_run_block`` rewrites every ``deadline=$(( … + N ))`` to two seconds so
    the failing cases finish quickly, so no execution case can see the value,
    and nothing else asserted one either — a recipe whose readiness deadline
    was retuned to 0 or 1 s would pass every test and then fail a healthy
    ``pm session``/app start on the first slow run. The message is the other
    half: a failure that says "within 30s" while the code waits 5 s sends the
    worker looking for a cause that is not there, the same "a message that
    disagrees with the code" class as the rest of this file.

    Pin both: every arithmetic bound is a plausible hang detector, and every
    "within Ns" the recipe prints is one of the numbers it actually waits.

    One bound is arithmetic but not a literal: the CLI scaffold's stop bound
    is ``deadline=$(( $(date +%s) + 10#$stop_timeout ))``, where
    ``stop_timeout`` falls back to ``${RECORDER_STOP_TIMEOUT:-30}``. The
    pattern below cannot see that value, so retuning the *default* to 0 or 1 s
    left the whole file green (266 passed, verified) while a healthy one-shot
    command that runs a few seconds was killed at the deadline — the exact
    regression the raisable bound exists to prevent (the recipe records a
    ``sleep 6`` recording lost to ``RECORDER_STOP_TIMEOUT=1``). Pin the
    default the same way as the literals.
    """
    text = _recipe_text(name)
    bounds = {int(n) for n in re.findall(
        r"deadline=\$\(\( \$\(date \+%s\) \+ (\d+) \)\)", text)}
    # The indirect stop bound's fallback is the number it really waits when a
    # worker does not raise it; a default of 0/1 s stops bounding anything.
    bounds |= {int(n) for n in re.findall(r"RECORDER_STOP_TIMEOUT:-(\d+)", text)}
    assert bounds, f"{name}: no bounded deadline found"
    for n in sorted(bounds):
        assert n >= 10, (
            f"{name}: a readiness/stop deadline of {n}s is too short to be a "
            "hang detector — a slow session or app start would fail a healthy "
            "run")
    stated = {int(n) for n in re.findall(r"within (\d+)s", text)}
    assert stated, f"{name}: no failure message states its bound"
    assert stated <= bounds, (
        f"{name}: a failure message states a bound the code does not use "
        f"(stated {sorted(stated)}s, arithmetic {sorted(bounds)}s)")
