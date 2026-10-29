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
  finish needs the status handle too;
- readiness polls (pm session, web-ui server) carry a deadline and an
  actionable failure instead of hanging forever, the pm-session poll waits on
  the computed session rather than any ``pm-`` session (which would also
  match this recipe's own ``pm-recorder``), and the web-UI step refuses a
  port something already answers on (that server would satisfy the poll and
  the driver would record the wrong app);
- two runs on one tmux server must not read each other's evidence: the
  transcript pipe is per-pane and a later one replaces it, so the tmux recipe
  claims the capture directory in a session option — before attaching the
  pipe, so the read/write gap does not cover the takeover it guards — and
  refuses a session recording a different directory, or a directory another
  live session records into; a finished run releases the claim, and the claim
  is compared as a canonical directory rather than as the text typed (step 0
  accepts `~/cap`, and a quoted `~` never expands, so one directory spelled
  two ways was two claims), and a session holding no claim must not be read as
  claiming the worker's cwd (``cd ""`` stays put, so normalizing an empty
  answer made every other session look like it recorded into the directory the
  step was pasted from);
- the render steps delete this run's outputs before rendering, so a failed
  ``agg``/``ffmpeg``/transcode ends with no video instead of the previous
  run's mp4 (which the manifest would present as this run's evidence); the
  web-UI driver's trace, screenshots and DOM dump are cleared the same way,
  and the web-UI finalize step refuses to run at all with no ``CAPDIR``
  rather than aim its cleanup and ffmpeg at the filesystem root;
- the render steps name their renderer prerequisite: ``agg`` may be missing
  (the image used for QA on 2026-10-27 did not have it, although the bundled
  Dockerfile now installs it), and the render fails loudly, so the recipe
  carries the per-architecture release-binary install line — guarded on
  ``command -v agg``, because re-downloading over a working binary can
  truncate it earlier on PATH;
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
  pointing at files that were never written), the web-UI driver block refuses
  a capture directory it cannot enter (``cd`` fails and the link lands in the
  worker's cwd), a web-UI start that never answers removes the pid it
  recorded so the teardown cannot signal a recycled one, and the web-UI
  finalize step names a missing ``ffmpeg`` instead of reporting it as a
  failed transcode of the driver's webm;
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
  died before the behaviour under test and the capture must be re-run.

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
        """
        text = _recipe_text(name)
        render = _render_block(name)
        cast_rel = re.search(r"^cast=(\S+)$", render, re.M).group(1)
        assert '"$cast.gif"' in render, (
            f"{name}: the render block no longer renders to `$cast.gif`; this "
            "test derives the intermediate's name from that expression")
        intermediate = cast_rel + ".gif"
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
        scaffold_rm = _statement(_scaffold_block(text), "rm -f ")
        assert "recording.mp4" in scaffold_rm, (
            f"{name}: the scaffold's own cleanup keeps an earlier run's "
            "recording.mp4")
        assert intermediate in scaffold_rm, (
            f"{name}: the scaffold's own cleanup keeps an earlier run's "
            f"{intermediate}")
        assert "recording.gif" not in rm + scaffold_rm, (
            f"{name}: the cleanup names `recording.gif`, which nothing writes "
            f"— the intermediate is `{intermediate}`")

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
         "kill-session -t pm-recorder", "new-session -d -s pm-recorder"),
        ("cli-recording.md", "kill-session -t rec", "new-session -d -s rec"),
    ])
    def test_stale_recorder_is_cleared_before_start(self, name, cleanup, start):
        """A leftover recorder from an earlier run must be cleared first.

        ``new-session`` fails with "duplicate session" while the previous
        run's recorder is still there, and the start check reports that as
        "could not start the recorder session", so a re-run would end before
        recording anything. (Before that check the run carried on, but not
        into a false pass: the tmux readiness wait took the *old* session's
        pane content as readiness and drove the previous run's attach client,
        while the CLI wait — which is on the cast file, and step 0 clears it —
        ran out its deadline against a ``rec`` session that never wrote a
        cast.) Clearing the session up front is what makes a re-run
        deterministic, and the start check is what makes the leftover loud if
        a concurrent run recreates it after the clear.

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
            kill_server = re.search(r"^[^#\n]*kill-server", block, re.M)
            assert kill_server and kill_server.start() > start_at, (
                "cli-recording: kill-server before new-session races the "
                "server's exit; clear the session instead")

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
        assert "! tmux has-session -t pm-recorder" in seg, (
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
        assert "! tmux has-session -t pm-recorder" in settle, (
            "tmux recipe does not re-check the recorder after it drew")
        assert "recorder exited before it drew" in settle
        assert "exit 1" in settle, (
            "a recorder that died after drawing is not reported as a failure")

    def test_tmux_recorder_dying_mid_scenario_fails(self):
        """A recorder gone before the detach did not finish the recording.

        The stop step's completion signal is the recorder session ending
        *after* the detach. The attach client follows the session, so it
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
                    block.index("tmux send-keys -t pm-recorder")]
        assert "! tmux has-session -t pm-recorder" in seg, (
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
        — go to stderr, and every failure path tears the pane down, so
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
            r"^status=\$\(cat (\S+) 2>/dev/null\) \|\| \{$", block, re.M)
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
        stale = block[block.index("rm -f "):block.index("new-session -d")]
        assert "recorder.status" in stale, (
            "cli-recording: an earlier run's recorder status survives, so a "
            "torn-down recorder can pass the status check")

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
            r"^status=\$\(cat (\S+) 2>/dev/null\) \|\| \{$", block, re.M)
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
        stale = block[block.index("rm -f "):block.index("new-session -d")]
        assert "recorder.status" in stale, (
            "tmux-screen-recording: an earlier run's recorder status survives, "
            "so a torn-down recorder can pass the status check")

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
        the cast, but asciinema's *own* startup errors go to stderr — and
        every failure path tears the recorder session down. The redirect puts
        them on disk; verified that it does not disturb the recording (the
        attach error is still drawn in the pane and recorded in the cast).
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
        _stub_tool(bindir, tool)
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
                ffmpeg_body=None, with_cast=True):
    """Run a recipe's render block against stubbed ``agg``/``ffprobe``/``ffmpeg``.

    Returns ``(proc, mp4_path, gif_path)``. The stubs are the real stage
    contracts: ``agg`` writes the gif, ``ffprobe`` reports dimensions then the
    codec, ``ffmpeg`` writes the mp4.
    """
    block = _render_block(name)
    cast_rel = re.search(r"^cast=(\S+)$", block, re.M).group(1)
    block = (block.replace("<capture-dir>", str(tmp_path))
                  .replace("<short-name>", "run"))
    cast = Path(cast_rel.replace("<capture-dir>", str(tmp_path))
                       .replace("<short-name>", "run"))
    cast.parent.mkdir(parents=True, exist_ok=True)
    if with_cast:
        cast.write_text('{"version": 2}\n')
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    _stub_tool(bindir, "agg", agg_body or (
        'for a in "$@"; do last=$a; done\nprintf gif > "$last"\n'))
    _stub_tool(bindir, "ffprobe", ffprobe_body or (
        'case "$*" in *width,height*) echo 640,480 ;; *) echo h264 ;; esac\n'))
    _stub_tool(bindir, "ffmpeg", ffmpeg_body or (
        'for a in "$@"; do last=$a; done\nprintf mp4 > "$last"\n'))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True)
    return r, cast.with_suffix(".mp4"), cast.with_name(cast.name + ".gif")


@pytest.mark.parametrize("name", RECIPES)
def test_failed_encode_does_not_leave_a_partial_mp4(name, tmp_path):
    """`test -s` on the mp4 is not proof the encode finished.

    Verified live with the recipe's own render block and real `ffmpeg`: a
    SIGKILLed encode leaves a **267,945-byte** mp4 (a SIGTERM one leaves
    119,704 bytes), so a render whose encoder failed exits 0 with a broken
    mp4 that the manifest and the report present as this run's recording —
    the same header-only-cast bug as the recorder step, one artifact over.
    The encoder's own exit status is the handle, and its partial output goes.
    """
    r, mp4, gif = _run_render(name, tmp_path, ffmpeg_body=(
        'for a in "$@"; do last=$a; done\nprintf partial > "$last"\nexit 1\n'))

    assert r.returncode != 0, (
        f"{name}: an encoder that failed on a partial mp4 was reported as a "
        "successful render")
    assert "render produced no mp4" in r.stderr, r.stderr
    assert "ffmpeg failed" in r.stderr, (
        f"{name}: the failure does not name the stage that broke: " + r.stderr)
    assert not mp4.exists(), (
        f"{name}: a failed encode left its partial mp4 as this run's video")
    assert not gif.exists()


@pytest.mark.parametrize("name", RECIPES)
def test_render_succeeds_with_a_playable_mp4(name, tmp_path):
    """The new checks must not reject a healthy render."""
    r, mp4, gif = _run_render(name, tmp_path)

    assert r.returncode == 0, r.stderr
    assert mp4.read_bytes() == b"mp4"
    assert not gif.exists(), "the intermediate gif is left behind"


def _run_render_without_ffmpeg(name, tmp_path):
    """Run a recipe's render block on a PATH that holds no ``ffmpeg``.

    A host may well have a real ``ffmpeg`` on ``PATH``, so the bindir carries
    the block's other tools (stubbed ``agg``/``ffprobe``, symlinked coreutils)
    and nothing else — the encoder has to be genuinely absent.
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
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _stub_tool(bindir, "agg", (
        'for a in "$@"; do last=$a; done\nprintf gif > "$last"\n'))
    _stub_tool(bindir, "ffprobe", (
        'case "$*" in *width,height*) echo 640,480 ;; *) echo h264 ;; esac\n'))
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
    """A missing ``ffmpeg`` is not a bad gif.

    The block checks the encoder's exit status (R12), so a host without
    ``ffmpeg`` reaches the shell's "ffmpeg: command not found" (status 127)
    and the block reports "ffmpeg failed on the gif" — sending the worker to
    inspect the cast and ``agg`` for a tool that is not installed. Verified
    against the pre-fix blocks: rc 1 with that message and no ``ffmpeg``
    anywhere on PATH. This is the misdiagnosis the web-UI finalize step got
    the same guard for (R22), in the recipes where a missing renderer is most
    likely (the QA image used on 2026-10-27 had no ``agg`` either).
    """
    r, mp4, gif = _run_render_without_ffmpeg(name, tmp_path)

    assert r.returncode != 0, r.stderr
    assert "ffmpeg is not installed" in r.stderr, (
        f"{name}: a missing encoder is not named: " + r.stderr)
    assert "ffmpeg failed on the gif" not in r.stderr, (
        f"{name}: a missing encoder is still reported as a bad gif: "
        + r.stderr)
    assert not gif.exists(), (
        f"{name}: the render ran agg before noticing the encoder was missing")
    assert not mp4.exists(), (
        f"{name}: a render that could not run left an mp4 behind")


@pytest.mark.parametrize("name", RECIPES)
def test_render_says_when_there_is_no_cast(name, tmp_path):
    """A missing cast is not an `agg` problem, and must not send the worker there.

    The CLI recipe documents a `tee transcript.log` fallback for a host with
    no asciinema, and that fallback writes no cast at all. The render step
    used to fail with "check 'agg' is installed and the cast is readable" for
    every failure, so a worker on that path went and installed a renderer it
    already had. The message has to name the actual state.
    """
    r, mp4, gif = _run_render(name, tmp_path, with_cast=False)

    assert r.returncode != 0, f"{name}: a render with no cast succeeded"
    assert "there is no cast to render" in r.stderr, r.stderr
    assert "is 'agg' installed" not in r.stderr, (
        f"{name}: the no-cast failure sends the worker to install a renderer")
    assert not mp4.exists()
    assert not gif.exists()


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
    assert "chmod +x" in section, (
        f"{name}: the downloaded agg binary is never made executable")
    assert install < section.index("agg --idle-time-limit"), (
        f"{name}: the agg install line comes after the render block")
    assert re.search(r"^\s*curl -fsSL", section, re.M), (
        f"{name}: the agg prerequisite is not a runnable install command")
    # The guard has to be in the runnable block, not only in the prose above
    # it: a worker pastes the block, so a prose-only rule is what made the
    # block replace a working `agg` (R16).
    install_block = _install_block(name)
    assert "command -v agg" in install_block, (
        f"{name}: the install block is not guarded on `command -v agg`, so a "
        "worker who pastes it on an image that already has agg re-downloads "
        "over the working binary")
    assert (install_block.index("command -v agg")
            < install_block.index("curl -fsSL")), (
        f"{name}: the agg install guard comes after the download")


def _install_block(name):
    """The fenced block that installs ``agg`` in the render section."""
    section = _recipe_text(name).split("## Render to video", 1)[1]
    for block in re.findall(r"```[a-z]*\n(.*?)```", section, re.S):
        if "agg-$(uname -m)" in block:
            return block
    raise AssertionError(f"{name}: no agg install block found")


def _run_install_block(name, tmp_path, curl_body=None, agg_present=False,
                       local_on_path=True):
    """Run the recipe's own ``agg`` install block against stub tools.

    ``agg_present`` seeds a working ``agg`` in ``~/.local/bin`` (ahead of the
    stub PATH, as on the image). ``curl_body`` replaces the stub ``curl``.
    ``local_on_path`` puts ``~/.local/bin`` on PATH (the image's layout); with
    it off, the block installs a binary nothing can run.
    Returns ``(proc, agg path, curl-called marker)``.
    """
    block = _install_block(name)
    home = tmp_path / "home"
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    agg = local / "agg"
    if agg_present:
        agg.write_text("#!/bin/sh\necho working\n")
        agg.chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    called = tmp_path / "curl-called"
    # The block's own tools, stubbed to the real ones by absolute path, so the
    # test's PATH cannot pick up a host `agg` and mask the guard.
    for tool in ("mkdir", "chmod", "uname", "rm"):
        real = shutil.which(tool)
        assert real, f"{tool} is required"
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
    r = subprocess.run([bash], input=block, env=env,
                       capture_output=True, text=True, timeout=60)
    return r, agg, called


@pytest.mark.parametrize("name", RECIPES)
@pytest.mark.parametrize("agg_present", [True, False])
def test_renderer_install_block_only_runs_when_agg_is_missing(name,
                                                              agg_present,
                                                              tmp_path):
    """Re-downloading over a working `agg` can destroy it.

    ``~/.local/bin`` comes first on the image's PATH, and ``curl -o`` writes
    in place: a transfer that fails partway leaves a truncated binary that
    shadows the image's working ``agg`` (verified: a dropped transfer replaced
    a working agg with a 500-byte file). The bundled Dockerfile installs
    ``agg``, so a worker pasting the remedy block on a current image would
    take that risk for nothing — the block is guarded on ``command -v agg``,
    matching the prose that says to install it only when that prints nothing.
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
def test_renderer_install_is_bounded_and_drops_a_partial_download(name,
                                                                  tmp_path):
    """The install download is the last unbounded request in the recipes.

    Every other request is bounded — the readiness polls per attempt, the
    Layer 2 route snapshots with ``--connect-timeout``/``--max-time`` —
    because one that accepts the connection and never answers hangs the
    worker. ``curl -o`` with no deadline is that wait one step earlier, and
    ``-o`` writes in place, so a transfer that dies mid-body leaves a partial
    file that would shadow the image's working ``agg`` on PATH. It has to be
    removed and the failure named.
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
    assert "could not download agg" in r.stderr, r.stderr


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


def test_web_ui_finalize_says_when_there_is_no_webm(tmp_path):
    """A missing webm is not an ffmpeg problem, and must not send the worker there.

    The driver block checks the driver's exit status (R18), but a driver that
    exits 0 without recording still writes no webm — ``recordVideo`` dropped
    while adapting it, or a ``video`` that came back null. The finalize step
    then handed ffmpeg a nonexistent input and reported "transcode produced no
    mp4 — ffmpeg failed on the driver's webm" (verified live), which points at
    the encoder: the same misdiagnosis R12 fixed for a missing cast. The stale
    mp4 must still go, so a failed run cannot present the previous run's video.
    """
    block = _web_ui_finalize_block()

    capdir = tmp_path / "cap"
    capdir.mkdir()
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
    the handle, and its partial output goes with it.
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
        "a failed transcode left its partial mp4 as this run's recording")


def test_web_ui_transcode_that_writes_nothing_leaves_no_mp4(tmp_path):
    """A renderer that reports success and writes nothing leaves no output.

    The exit status proves the encode ran; ``test -s`` catches the renderer
    that claims success and writes nothing (R12). Verified: that branch
    exited 1 but left a **0-byte** ``recording.mp4`` in the capture directory,
    which the manifest's ``## Files`` section could then list as this run's
    video — the recording recipes' ``render_fail`` removes the output for
    exactly this reason, so the two finalize paths disagreed. The webm stays,
    because a failed transcode is retried from it.
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
def test_web_ui_driver_block_refuses_a_missing_driver(tmp_path):
    """A driver that was never saved is not a driver that ran and failed.

    Step 2's prose says to save the skeleton as ``driver.mjs`` in the capture
    directory, and the block then runs ``node driver.mjs``. Without the file
    Node answers ``Cannot find module …/driver.mjs`` (exit 1, verified) and the
    run-failure message below calls that "the driver failed — this run's
    video, trace and screenshots are incomplete", so the worker debugs a
    driver that is simply absent (or was saved in the workdir instead of the
    capture directory). That is the same misdiagnosis as reporting a missing
    webm as an encoder failure. The block names the missing input instead.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()                    # empty: no driver.mjs was saved
    r = _run_driver_block(capdir, _fake_playwright(tmp_path / "global"))
    assert r.returncode != 0, "the block ran with no driver.mjs to run"
    assert "there is no driver.mjs" in r.stderr, (
        "a missing driver.mjs is not named: " + r.stderr)
    assert "the driver failed" not in r.stderr, (
        "a missing driver.mjs is reported as a driver that ran and failed, "
        "so the worker debugs a file that does not exist: " + r.stderr)
    assert "driver saw" not in r.stdout, r.stdout


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
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    stale = {"recording.mp4": "an earlier attempt's video\n",
             "recording.webm": "an earlier attempt\n",
             "trace.zip": "an earlier trace\n",
             "dom.html": "<html>an earlier dump</html>\n",
             "01-loaded.png": "an earlier screenshot\n"}
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
            "a retry that fails can be finalized as this run's recording")


_STUB_CURL = r"""
n=$(cat "$STUB_CURL_COUNT" 2>/dev/null || echo 0)
n=$((n + 1)); echo "$n" > "$STUB_CURL_COUNT"
case "$STUB_MODE" in
  inuse) exit 0 ;;
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
                      mkdir_body=None):
    """Run the web-UI recipe's app-start block with stub pm/curl/my-app.

    ``caps_is_file`` makes the captures path itself a regular file, so the
    block's ``mkdir -p`` cannot create the capture directory. ``pm_body``
    replaces the stub ``pm`` (which otherwise prints the captures root);
    ``mkdir_body`` replaces the stub ``mkdir``, so a case can watch what the
    block tries to create without creating it.
    """
    block = re.sub(r"\+\s*\d+\s*\)\)", "+ 2 ))", _web_ui_start_block())
    bindir = tmp_path / "bin"
    caps = tmp_path / "captures"
    bindir.mkdir(parents=True, exist_ok=True)
    if caps_is_file:
        caps.write_text("not a directory")
    else:
        caps.mkdir(parents=True, exist_ok=True)
    launched = tmp_path / "app-launched"
    _stub_tool(bindir, "pm", pm_body or f'echo "{caps}"\n')
    if mkdir_body is not None:
        _stub_tool(bindir, "mkdir", mkdir_body)
    _stub_tool(bindir, "curl", _STUB_CURL)
    _stub_tool(bindir, "my-app", f'touch "{launched}"\n')
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               STUB_MODE=mode, STUB_CURL_COUNT=str(tmp_path / "curl-count"))
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True, timeout=60)
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
    for artifact in ("*.webm", "recording.mp4", "trace.zip",
                     "dom.html", "http.log", "sse.log", "server.pid",
                     "*.png"):
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
    assert 'test -s "$CAPDIR/recording.mp4"' in finalize_block, (
        "web-ui recipe does not check that the transcode produced the mp4")


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
# picked up. A leading `=` forces an exact match; `has-session` and
# `pipe-pane` honour it, while `show-options`/`set-option` do not (verified:
# "no such session: =pm-test"). Echoes the resolved name, or fails.
resolve() {
    t=$1; exact=0
    case "$t" in =*) exact=1; t=${t#=} ;; esac
    [ -z "$t" ] && return 1
    [ -f "$STATE/$t" ] && { echo "$t"; return 0; }
    [ "$exact" = 1 ] && return 1
    for f in "$STATE"/*; do
        [ -e "$f" ] || continue
        b=${f##*/}
        case "$b" in pane|sends|pipeclaim|claim.*) continue ;; esac
        case "$b" in "$t"*) echo "$b"; return 0 ;; esac
    done
    return 1
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
      rm -f "$STATE/$r" "$STATE/claim.$r"; exit 0 ;;
  kill-server)  rm -f "$STATE/rec" "$STATE/pm-recorder" "$STATE/claim.rec" \
                     "$STATE/claim.pm-recorder"; exit 0 ;;
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
      if [ "$STUB_MODE" != notranscript ]; then
          case "$cmd" in
            *">>"*) out=${cmd#*>> }; out=${out%% *}
                    printf 'pane output\n' >> "$out" ;;
          esac
      fi
      exit 0 ;;
  capture-pane) cat "$STATE/pane" 2>/dev/null; exit 0 ;;
  # Session user options: the capture-dir claim step 2 writes and step 5
  # clears. Modelled on the real server (verified: `set-option -t S
  # @pm_capture_dir V`, `show-options -t S -v @pm_capture_dir`, and
  # `set-option -u` round-trip; a grouped session does not inherit it).
  show-options)
      s=$(val -t "$@")
      r=$(resolve "$s")
      case "$*" in
        *@pm_capture_dir*)
            [ -n "$r" ] && [ -f "$STATE/claim.$r" ] && {
                cat "$STATE/claim.$r"; exit 0; }
            exit 1 ;;
        # The server's prefix (step 5's detach key is this, not a literal
        # C-b). A real server always answers, C-b by default; STUB_PREFIX
        # models a ~/.tmux.conf that sets another one.
        *prefix*) printf '%s\n' "${STUB_PREFIX:-C-b}"; exit 0 ;;
      esac
      exit 0 ;;
  set-option)
      s=$(val -t "$@")
      r=$(resolve "$s")
      [ -z "$r" ] && { echo "no such session: $s" >&2; exit 1; }
      case " $* " in
        *" -u "*) rm -f "$STATE/claim.$r"; exit 0 ;;
      esac
      for a in "$@"; do v=$a; done
      printf '%s\n' "$v" > "$STATE/claim.$r"
      exit 0 ;;
  list-sessions)
      for f in "$STATE"/*; do
          [ -e "$f" ] || continue
          b=${f##*/}
          case "$b" in pane|sends|pipeclaim|claim.*) continue ;; esac
          echo "$b"
      done
      exit 0 ;;
  send-keys)
      s=$(val -t "$@")
      r=$(resolve "$s")
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
      rm -f "$STATE/$r"
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
      case "$STUB_MODE" in
        norec) : ;;
        dies)  rm -f "$STATE/$s" ;;
        failedattach)
            printf "can't find session: pm-test\n" > "$STATE/pane"
            ( sleep 0.02; rm -f "$STATE/$s" ) & ;;
        *)
            # `detachnocast`/`detachnostatus`: the recorder draws and the
            # detach ends it (the pm session survives, as it does in a real
            # finish), so step 5 reaches its own cast/status check — the two
            # branches after the claim is taken that no other mode reaches
            # with the session still there to hold the claim.
            [ "$STUB_MODE" = detachnocast ] || printf '{"version": 2}\n' > "$STUB_CAST"
            printf 'TUI drawn\n' > "$STATE/pane"
            if [ -n "$STUB_STATUS_FILE" ]; then
                case "$STUB_MODE" in
                  nostatus|detachnostatus) : ;;
                  badstatus|midbothbad|detachbothbad) printf '137\n' > "$STUB_STATUS_FILE" ;;
                  *)         printf '0\n' > "$STUB_STATUS_FILE" ;;
                esac
            fi ;;
      esac
      case "$STUB_MODE" in
        oneshot|badstatus|nostatus) ( sleep 0.3; rm -f "$STATE/$s" ) & ;;
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
        midadied) rm -f "$STATE/pm-recorder" "$STATE/claim.pm-recorder" ;;
        midboth|midbothbad)
            # A session ending takes its session options (the capture-dir
            # claim) with it, as real tmux does.
            rm -f "$STATE/pm-recorder" "$STATE/claim.pm-recorder" \
                  "$STATE/pm-test" "$STATE/claim.pm-test" ;;
      esac
      exit 0 ;;
esac
exit 0
"""


def _run_block(raw, mode, tmp_path, target=False, env_extra=None,
               sessions=(), files=None, state_files=None, capture=None,
               cwd=None, timeout=120):
    """Run one recipe block against stub tmux/pm; return (proc, cast path).

    ``raw`` is the block text as a worker pastes it, ``sessions`` the tmux
    sessions that already exist when it starts (a stop block runs against the
    sessions steps 1-3 left behind), ``files`` the capture-dir files and
    ``state_files`` the stub's own files (``pane``) to seed. ``capture``
    overrides the capture directory (a test that wants it unusable passes a
    path that cannot be created). ``cwd`` is the directory the block is pasted
    from — the recipes resolve some paths against it, so a case that depends
    on the worker's location has to say where that is.
    """
    state = tmp_path / "state"
    bindir = tmp_path / "bin"
    if capture is None:
        capture = tmp_path / "cap"
        capture.mkdir()
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
    for rel, content in (files or {}).items():
        p = capture / sub / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    # Shorten every numeric deadline so the failing cases finish quickly; the
    # recipes' own bounds are asserted as text above. Matching the shape
    # (rather than the literal ``30``/``60``) keeps the cases fast when a
    # recipe's bound is retuned, instead of silently waiting it out.
    block = re.sub(r"\+\s*\d+\s*\)\)", "+ 2 ))", block)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               STUB_STATE=str(state), STUB_MODE=mode,
               STUB_CAST=str(capture / sub / "recording.cast"),
               **(env_extra or {}))
    if "recorder.status" in raw:
        # The CLI scaffold's pane command records asciinema's own exit status;
        # the stub cannot run the pane command, so it writes the status the
        # recipe's step 4 reads.
        env["STUB_STATUS_FILE"] = str(capture / sub / "recorder.status")
    r = subprocess.run(["bash"], input=block, env=env, cwd=cwd,
                       capture_output=True, text=True, timeout=timeout)
    return r, capture / sub / "recording.cast"


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


class TestCaptureFlowExecution:
    """Run the capture block end to end against a stub tmux server."""

    def test_cli_recording_completes(self, tmp_path):
        r, cast = _run_capture_block("cli-recording.md", "oneshot", tmp_path)
        assert r.returncode == 0, r.stderr
        assert cast.stat().st_size > 0, "the completed cast is missing"

    def test_cli_recorder_that_never_writes_a_cast_fails(self, tmp_path):
        """A recorder that starts but records nothing is a failure, not a hang."""
        r, cast = _run_capture_block("cli-recording.md", "norec", tmp_path)
        assert r.returncode != 0, "an empty recording was reported as success"
        assert "did not start within" in r.stderr, r.stderr
        assert "recorder-pane.log" in r.stderr, (
            "the readiness failure does not say where the pane was saved: "
            + r.stderr)
        assert not cast.exists()

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
        """
        raw = _scaffold_block(_recipe_text(name))
        cast_rel = re.search(r"^cast=(\S+)$", _render_block(name), re.M).group(1)
        intermediate = Path(cast_rel).name + ".gif"
        r, cast = _run_block(
            raw, "norec", tmp_path, target=True,
            files={"recording.mp4": "previous run",
                   intermediate: "previous gif"})
        cap = cast.parent
        assert r.returncode != 0, r.stderr
        assert not (cap / "recording.mp4").exists(), (
            f"{name}: a failed capture left the previous run's recording.mp4 "
            "as this capture's only video")
        assert not (cap / intermediate).exists(), (
            f"{name}: a failed capture left the previous run's "
            f"{intermediate} (the intermediate the render block writes) "
            "behind")

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

    def test_tmux_recording_completes(self, tmp_path):
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "ok", tmp_path, target=True)
        assert r.returncode == 0, r.stderr
        assert cast.stat().st_size > 0, "the completed cast is missing"
        assert "can't find session" not in r.stderr, (
            "a clean run prints a tmux error while stopping the transcript pipe")

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

    @pytest.mark.parametrize("mode", [
        "pipefail",     # step 2 could not attach the transcript pipe
        "nostart",      # step 3 could not create the recorder session
        "norec",        # the recorder never drew
        "dies",         # the recorder exited before drawing
        "failedattach",  # the attach drew its own error and exited
        "stuck",        # the recorder never exited at the stop bound
        "notranscript",  # the pipe wrote nothing
        "midadied",     # the recorder died mid-scenario
        "detachfail",   # the recorder vanished before the detach key
        "midbothbad",   # killed recorder, target session gone too
    ])
    def test_a_failed_run_releases_its_capture_dir_claim(self, mode, tmp_path):
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
        """
        r, _cast = _run_capture_block(
            "tmux-screen-recording.md", mode, tmp_path, target=True)
        assert r.returncode != 0, (
            f"{mode}: the fixture was expected to fail the run")
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
