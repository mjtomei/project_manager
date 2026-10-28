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
  the run instead of passing on a truncated cast;
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
- the render steps name their renderer prerequisite: the QA image ships
  ``ffmpeg`` but not ``agg``, and the render now fails loudly, so the recipe
  carries the per-architecture release-binary install line;
- the CLI scaffold's ``<command-to-record>`` placeholder sits inside single
  quotes inside the outer double-quoted argument, so the recipe has to show
  the escaped form — pasting the plain ``bash -c "..."`` form ends the outer
  string and leaves asciinema with a broken command;
- the web-UI driver is an ES module and the image's Playwright is a *global*
  install advertised through ``NODE_PATH``, which ESM's resolver ignores, so
  the run block links a ``node_modules`` beside the driver (only when there is
  no local install) and stops at its own resolution check when the import
  still does not resolve.

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


def _stub_tool(bindir, name, body="exit 1\n"):
    path = bindir / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    return path


class TestRecipes:
    @pytest.mark.parametrize("name", RECIPES)
    def test_recipe_is_listed(self, name):
        ids = {item["id"] for item in list_artifacts(PM_ROOT)}
        assert Path(name).stem in ids

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

        stmt_start = block.index("tmux -L scaffold new-session")
        stmt = (block[stmt_start:block.index("\n\n", stmt_start)]
                .replace("<capture-dir>", str(tmp_path))
                .replace("<short-name>", "run")
                .replace("<command-to-record>", escaped))

        bindir = tmp_path / "bin"
        bindir.mkdir()
        tmux_argv = tmp_path / "tmux-argv"
        _stub_tool(bindir, "tmux",
                   f'printf "%s\\n" "$@" > "{tmux_argv}"\n')
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
        r = subprocess.run(["bash", "-c", stmt], env=env,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        recorder_cmd = tmux_argv.read_text().splitlines()[-1]

        asci_argv = tmp_path / "asciinema-argv"
        _stub_tool(bindir, "asciinema",
                   f'printf "%s\\n" "$@" > "{asci_argv}"\n')
        subprocess.run(["sh", "-c", recorder_cmd], env=env,
                       capture_output=True, text=True)
        argv = asci_argv.read_text().splitlines()
        assert argv[argv.index("-c") + 1] == 'bash -c "set -x; cmd-one; cmd-two"', (
            "cli-recording: the recorded command does not survive the "
            f"scaffold's quoting (asciinema got {argv!r})")

    def test_cli_scaffold_writes_the_cast_beside_the_render(self):
        """The scaffold must write the cast where the render step reads it.

        Every other form in the recipe (and the render block) uses
        ``<capture-dir>/<short-name>/recording.cast``.  A scaffold writing
        ``<capture-dir>/recording.cast`` renders nothing — or an older file
        — while looking successful.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        assert "<capture-dir>/<short-name>/recording.cast" in block


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


@pytest.mark.parametrize("name", RECIPES)
def test_render_documents_how_to_get_the_renderer(name):
    """The render step fails without `agg`, so the recipe has to say how to get it.

    The QA image ships `ffmpeg` but not `agg` (verified: `command -v agg`
    prints nothing in the pm-dev image), and the render block now exits 1
    rather than leave a missing or stale video. Without the install line the
    failure message ("check 'agg' is installed") sends the worker nowhere:
    the recipe never names a prerequisite, so the only remaining moves are to
    substitute a different renderer or to report the capture as impossible.
    The release-binary URL is the one verified against agg 1.9.0.
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
    assert re.search(r"^curl -fsSL", section, re.M), (
        f"{name}: the agg prerequisite is not a runnable install command")


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


def test_web_ui_finalize_refuses_an_unset_capdir(tmp_path):
    """The finalize step must not run its new `rm -f` against the filesystem root.

    Step 1's cleanup guards its screenshot glob with ``${CAPDIR:?}`` for
    exactly this reason, and the blocks are pasted separately, so a worker
    that runs step 3 in a fresh shell has no ``CAPDIR``: the ``rm -f`` then
    targets ``/recording.mp4`` and ffmpeg is handed ``/recording.webm``. The
    step stops with a message instead.
    """
    text = _recipe_text("web-ui-recording.md")
    finalize = text.split("### 3. Finalize", 1)[1].split("## Capture", 1)[0]
    block = re.findall(r"```[a-z]*\n(.*?)```", finalize, re.S)[0]

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
    text = _recipe_text("web-ui-recording.md")
    finalize = text.split("### 3. Finalize", 1)[1].split("## Capture", 1)[0]
    block = re.findall(r"```[a-z]*\n(.*?)```", finalize, re.S)[0]

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


def _run_driver_block(capdir, global_dir):
    """Run the recipe's own driver block against a fake Playwright install."""
    block = _web_ui_driver_block().replace("/usr/lib/node_modules",
                                           str(global_dir))
    env = dict(os.environ, CAPDIR=str(capdir), APP_URL="http://localhost:1")
    return subprocess.run(["bash"], input=block, env=env,
                          capture_output=True, text=True, timeout=120)


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


def _run_web_ui_start(mode, tmp_path):
    """Run the web-UI recipe's app-start block with stub pm/curl/my-app."""
    block = re.sub(r"\+\s*\d+\s*\)\)", "+ 2 ))", _web_ui_start_block())
    bindir = tmp_path / "bin"
    caps = tmp_path / "captures"
    for d in (bindir, caps):
        d.mkdir()
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
        assert not launched.exists(), (
            "the recipe started the app on a port another server holds")

    def test_a_server_that_never_answers_fails_at_the_deadline(self, tmp_path):
        r, launched = _run_web_ui_start("never", tmp_path)
        assert r.returncode != 0, (
            "a server that never answers was reported as started")
        assert "did not answer" in r.stderr, r.stderr


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
                     "dom.html", "*.png"):
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
    finalize = text.split("### 3. Finalize", 1)[1].split("## Capture", 1)[0]
    finalize_block = re.findall(r"```[a-z]*\n(.*?)```", finalize, re.S)[0]
    rm = finalize_block.index('rm -f "$CAPDIR/recording.mp4"')
    assert rm < finalize_block.index("\nffmpeg "), (
        "web-ui recipe only drops the old mp4 after the transcode")
    assert 'test -s "$CAPDIR/recording.mp4"' in finalize_block, (
        "web-ui recipe does not check that the transcode produced the mp4")


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
  has-session)  [ -f "$STATE/$(val -t "$@")" ] && exit 0 || exit 1 ;;
  kill-session) rm -f "$STATE/$(val -t "$@")"; exit 0 ;;
  kill-server)  rm -f "$STATE/rec" "$STATE/pm-recorder"; exit 0 ;;
  pipe-pane)
      s=$(val -t "$@")
      [ -f "$STATE/${s%%:*}" ] && exit 0
      echo "can't find session: $s" >&2; exit 1 ;;
  capture-pane) cat "$STATE/pane" 2>/dev/null; exit 0 ;;
  send-keys)
      s=$(val -t "$@")
      rm -f "$STATE/$s"
      [ "$STUB_MODE" = detachfail ] && exit 1
      exit 0 ;;
  new-session)
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
            printf 'TUI drawn\n' > "$STATE/pane" ;;
      esac
      [ "$STUB_MODE" = oneshot ] && ( sleep 0.3; rm -f "$STATE/$s" ) &
      exit 0 ;;
esac
exit 0
"""

_STUB_PM = r"""
STATE="$STUB_STATE"
case "$1 $2" in
  "session name") echo pm-test ;;
  "session ")     exit 0 ;;
  "tui send")
      case "$STUB_MODE" in
        midadied) rm -f "$STATE/pm-recorder" ;;
        midboth)  rm -f "$STATE/pm-recorder" "$STATE/pm-test" ;;
      esac
      exit 0 ;;
esac
exit 0
"""


def _run_capture_block(name, mode, tmp_path, target=False):
    """Run a recipe's capture block against stub tmux/pm; return (proc, cast)."""
    capture = tmp_path / "cap"
    state = tmp_path / "state"
    bindir = tmp_path / "bin"
    for d in (capture, state, bindir):
        d.mkdir()
    _stub_tool(bindir, "tmux", _STUB_TMUX)
    _stub_tool(bindir, "pm", _STUB_PM)
    if target:
        (state / "pm-test").touch()
    raw = _scaffold_block(_recipe_text(name))
    # The CLI scaffold writes under <capture-dir>/<short-name>/, the tmux
    # recipe directly under <capture-dir>/.
    sub = ("run/" if "<short-name>/recording.cast" in raw else "")
    block = (raw.replace("<capture-dir>", str(capture))
                .replace("<short-name>", "run")
                .replace("<command-to-record>", "echo hi"))
    # Shorten every numeric deadline so the failing cases finish quickly; the
    # recipes' own bounds are asserted as text above. Matching the shape
    # (rather than the literal ``30``/``60``) keeps the cases fast when a
    # recipe's bound is retuned, instead of silently waiting it out.
    block = re.sub(r"\+\s*\d+\s*\)\)", "+ 2 ))", block)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               STUB_STATE=str(state), STUB_MODE=mode,
               STUB_CAST=str(capture / sub / "recording.cast"))
    r = subprocess.run(["bash"], input=block, env=env,
                       capture_output=True, text=True, timeout=120)
    return r, capture / sub / "recording.cast"


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
        assert not cast.exists()

    def test_cli_recorder_that_dies_without_a_cast_fails(self, tmp_path):
        """asciinema failing to start must not pass as a finished recording."""
        r, cast = _run_capture_block("cli-recording.md", "dies", tmp_path)
        assert r.returncode != 0, "a recorder that never ran was reported as success"
        assert "asciinema wrote no cast" in r.stderr, r.stderr
        assert not cast.exists()

    def test_tmux_recording_completes(self, tmp_path):
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "ok", tmp_path, target=True)
        assert r.returncode == 0, r.stderr
        assert cast.stat().st_size > 0, "the completed cast is missing"
        assert "can't find session" not in r.stderr, (
            "a clean run prints a tmux error while stopping the transcript pipe")

    def test_tmux_recorder_exiting_before_drawing_fails(self, tmp_path):
        r, cast = _run_capture_block(
            "tmux-screen-recording.md", "dies", tmp_path, target=True)
        assert r.returncode != 0, "a recorder that never drew was reported as success"
        assert "recorder exited before it drew" in r.stderr, r.stderr

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
