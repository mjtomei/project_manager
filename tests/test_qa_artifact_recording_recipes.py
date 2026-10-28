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
- a step that cannot do its job says so where it fails instead of being
  misdiagnosed downstream: an unusable capture directory and a failed
  ``new-session`` stop the run with their own message (otherwise the failure
  reads as "recorder exited before it drew" / "asciinema wrote no cast", both
  pointing at files that were never written), the web-UI driver block refuses
  a capture directory it cannot enter (``cd`` fails and the link lands in the
  worker's cwd), and a web-UI start that never answers removes the pid it
  recorded so the teardown cannot signal a recycled one.

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
        if "pipe-pane" in block:
            assert mkdir < block.index("pipe-pane"), (
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
        assert rm.start() < block.index("pipe-pane"), (
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

    def test_tmux_readiness_wait_targets_the_computed_session(self):
        """The pm-session poll must not match the recipe's own recorder.

        ``tmux ls | grep '^pm-'`` also matches ``pm-recorder`` — the session
        this very recipe creates — and any other project's pm session, so
        the wait can pass before the target exists and its failure path
        never fires. ``tmux has-session -t "$TARGET"`` is the actual
        handle; an empty target must be rejected first because
        ``tmux has-session -t ''`` succeeds.
        """
        block = _scaffold_block(_recipe_text("tmux-screen-recording.md"))
        assert 'has-session -t "$TARGET"' in block, (
            "tmux recipe does not wait on the computed session handle")
        assert "grep -q '^pm-'" not in block and "until tmux ls" not in block, (
            "tmux recipe still matches any pm- session (incl. pm-recorder)")
        target = block.index("TARGET=$(pm session name)")
        guard = block.index('[ -n "$TARGET" ]')
        wait = block.index('until tmux has-session -t "$TARGET"')
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
        run's recorder is still there — and the readiness wait then sees the
        *old* session, passes at once, and the worker drives the wrong
        attach client while the cast check fails later with a misleading
        message. Clearing it up front is what makes a re-run deterministic.

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
        assert 'tmux has-session -t "$TARGET"' in seg, (
            "tmux recipe cannot tell a recorder that died mid-scenario apart "
            "from one that ended because the session ended")
        assert "incomplete" in seg and "exit 1" in seg, (
            "a recorder that died mid-scenario is not reported as a failure")

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
        assert "deadline=$(( $(date +%s) + stop_timeout ))" in body, (
            "cli-recording: the stop deadline ignores RECORDER_STOP_TIMEOUT")
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
    for tool in ("mkdir", "chmod", "uname"):
        real = shutil.which(tool)
        assert real, f"{tool} is required"
        _stub_tool(bindir, tool, f'exec "{real}" "$@"\n')
    # The stub's PATH is the stub dir itself, so it may only use builtins.
    _stub_tool(bindir, "curl", f''': > "{called}"
for a in "$@"; do last=$a; done
printf '#!/bin/sh\\necho downloaded\\n' > "$last"
''')
    # `~/.local/bin` is on the image's PATH ahead of the system dirs, and the
    # stubs stand in for everything else, so no host `agg` can mask the guard.
    # `bash` itself is resolved before PATH is replaced.
    bash = shutil.which("bash")
    env = dict(os.environ, HOME=str(home), PATH=f"{local}:{bindir}")

    r = subprocess.run([bash], input=block, env=env,
                       capture_output=True, text=True)

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
    """Feed ``block`` to an interactive bash on a pty (``script``)."""
    if shutil.which("script") is None:
        pytest.skip("script(1) is required")
    return subprocess.run(["script", "-qec", "bash", "/dev/null"],
                          input=block, env=env, cwd=cwd,
                          capture_output=True, text=True, timeout=60)


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
    dangling ``node_modules`` in the capture directory.
    """
    capdir = tmp_path / "cap"
    capdir.mkdir()
    _write_driver(capdir)
    r = _run_driver_block(capdir, tmp_path / "missing-global-install")
    assert r.returncode != 0, (
        "the recipe ran driver.mjs although its own resolution check failed")
    assert "playwright does not resolve beside driver.mjs" in r.stderr, (
        "the resolution failure has no actionable message: " + r.stderr)
    assert "driver saw" not in r.stdout, (
        "the recipe ran the driver after its resolution check failed")
    assert not os.path.lexists(capdir / "node_modules"), (
        "web-ui recipe left a dangling node_modules beside the driver")


_STUB_CURL = r"""
n=$(cat "$STUB_CURL_COUNT" 2>/dev/null || echo 0)
n=$((n + 1)); echo "$n" > "$STUB_CURL_COUNT"
case "$STUB_MODE" in
  inuse) exit 0 ;;
  never) exit 7 ;;
esac
# Call 1 is the recipe's own "is the port free?" pre-check; the app answers
# from call 2 on.
[ "$n" -ge 2 ] && exit 0
exit 7
"""


def _web_ui_start_block():
    """The fenced block under ``### 1. Start the UI under test``."""
    text = _recipe_text("web-ui-recording.md")
    section = text.split("### 1. Start the UI under test", 1)[1].split(
        "### 2.", 1)[0]
    return re.findall(r"```bash\n(.*?)```", section, re.S)[0]


def _run_web_ui_start(mode, tmp_path, caps_is_file=False):
    """Run the web-UI recipe's app-start block with stub pm/curl/my-app.

    ``caps_is_file`` makes the captures path itself a regular file, so the
    block's ``mkdir -p`` cannot create the capture directory.
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
    _stub_tool(bindir, "pm", f'echo "{caps}"\n')
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

    def test_a_server_that_never_answers_fails_at_the_deadline(self, tmp_path):
        r, launched = _run_web_ui_start("never", tmp_path)
        assert r.returncode != 0, (
            "a server that never answers was reported as started")
        assert "did not answer" in r.stderr, r.stderr

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


def test_web_ui_clears_a_previous_video():
    """The web-UI capture must not transcode an earlier run's webm.

    Playwright's video only lands as ``recording.webm`` when the driver gets
    as far as renaming it, so a driver that fails leaves the *previous* run's
    webm in the capture directory — and the finalize step then produces a
    fresh-looking mp4 of that earlier run. Both the webm and the mp4 are
    cleared before the driver starts, and the mp4 again before the transcode
    (``ffmpeg`` leaves an existing output untouched when it fails).

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
                  if ln.startswith("rm -f") and "recording.webm" in ln), None)
    assert clear, (
        "web-ui recipe keeps an earlier run's webm/mp4, so a failed driver "
        "transcodes the previous run into this run's recording")
    for artifact in ("recording.webm", "recording.mp4", "trace.zip",
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
while [ "$1" = "-L" ]; do shift 2; done
sub=$1; shift
val() { f=$1; shift; while [ $# -gt 0 ]; do
          if [ "$1" = "$f" ]; then echo "$2"; return; fi; shift; done; }
case "$sub" in
  has-session)
      # Real tmux (3.2a, verified) *succeeds* for `-t ''` — the empty target
      # matches the current session. Modelling that is what makes an unset
      # $TARGET visible: the recipe's both-gone branch would fire on a
      # legitimate finish.
      s=$(val -t "$@")
      [ -z "$s" ] && exit 0
      [ -f "$STATE/$s" ] && exit 0 || exit 1 ;;
  kill-session) rm -f "$STATE/$(val -t "$@")"; exit 0 ;;
  kill-server)  rm -f "$STATE/rec" "$STATE/pm-recorder"; exit 0 ;;
  pipe-pane)
      s=$(val -t "$@")
      if [ ! -f "$STATE/${s%%:*}" ]; then
          echo "can't find session: $s" >&2; exit 1
      fi
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
  send-keys)
      s=$(val -t "$@")
      # `stuck`: the recorder never goes away, so a stop wait runs out.
      [ "$STUB_MODE" = stuck ] && exit 0
      rm -f "$STATE/$s"
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
            printf '{"version": 2}\n' > "$STUB_CAST"
            printf 'TUI drawn\n' > "$STATE/pane"
            if [ -n "$STUB_STATUS_FILE" ]; then
                case "$STUB_MODE" in
                  nostatus)  : ;;
                  badstatus|midbothbad) printf '137\n' > "$STUB_STATUS_FILE" ;;
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
      case "$STUB_MODE" in
        midadied) rm -f "$STATE/pm-recorder" ;;
        midboth|midbothbad)
            rm -f "$STATE/pm-recorder" "$STATE/pm-test" ;;
      esac
      exit 0 ;;
esac
exit 0
"""


def _run_block(raw, mode, tmp_path, target=False, env_extra=None,
               sessions=(), files=None, state_files=None, capture=None):
    """Run one recipe block against stub tmux/pm; return (proc, cast path).

    ``raw`` is the block text as a worker pastes it, ``sessions`` the tmux
    sessions that already exist when it starts (a stop block runs against the
    sessions steps 1-3 left behind), ``files`` the capture-dir files and
    ``state_files`` the stub's own files (``pane``) to seed. ``capture``
    overrides the capture directory (a test that wants it unusable passes a
    path that cannot be created).
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
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True, timeout=120)
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

    def test_cli_stop_timeout_saves_the_pane(self, tmp_path):
        """A failing wait must leave the pane where its message says it is.

        Every failure path tears the scaffold server down, so a message that
        says "check the pane" points at evidence that no longer exists —
        verified live: the readiness timeout printed exactly that and the
        next line killed the server, after which ``capture-pane`` answered
        "no server running". The pane is saved before the teardown and the
        message names the file.
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
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        r, _cast = _run_block(
            _scaffold_block(_recipe_text(name)), "ok", tmp_path,
            target=True, capture=blocker / "cap")
        assert r.returncode != 0, (
            f"{name}: a capture directory that cannot be created was reported "
            "as a successful capture")
        assert "could not create" in r.stderr, r.stderr
        assert "exited before it drew" not in r.stderr and \
            "did not start within" not in r.stderr, (
            f"{name}: the unusable capture directory is reported as a "
            "recorder problem instead of the directory: " + r.stderr)


@pytest.mark.parametrize("name,marker,probe_bound", [
    ("tmux-screen-recording.md", 'until tmux has-session -t "$TARGET"', None),
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
