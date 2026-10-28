"""Regression tests for the recording-recipe completion rules.

pr-b19db15 kept only the recipe bugs that any worker following the recipe
hits, regardless of how it waits for a background job:

- the capture directory is created before ``asciinema`` writes into it
  (it prints "asciicast saved" and exits 0 while writing nothing);
- a cast from an earlier run is removed before recording, so the render
  step cannot turn a failed recording into a fresh-looking video of the
  previous run (the tmux transcript, which is appended to, is cleared too);
- the no-TTY scaffold writes the cast where the render step reads it;
- keys are not sent before the recorder has drawn (they are silently lost);
- the recorder is stopped by ending the recorded command and awaited with a
  bound, and the cast is checked non-empty;
- readiness polls (pm session, web-ui server) carry a deadline and an
  actionable failure instead of hanging forever, and the pm-session poll
  waits on the computed session rather than any ``pm-`` session (which would
  also match this recipe's own ``pm-recorder``).
"""

import re
import shutil
import subprocess
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
        does not exist. It has to be in the runnable block, not just in the
        prose: a worker that pastes the block skips prose-only steps.
        """
        text = _recipe_text(name)
        intro = text.split("## Capture", 1)[1].split("```", 1)[0]
        assert "mkdir -p <capture-dir>" in intro, (
            f"{name}: capture section never creates the capture directory")
        block = _scaffold_block(text)
        mkdir = block.find("mkdir -p <capture-dir>")
        assert mkdir != -1, (
            f"{name}: the runnable scaffold never creates the capture dir")
        assert mkdir < block.index("asciinema rec"), (
            f"{name}: the capture dir is created only after recording starts")

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
        block = _scaffold_block(_recipe_text(name))
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

    @pytest.mark.parametrize("name", RECIPES)
    def test_recorder_is_ready_before_keys_are_sent(self, name):
        """Keystrokes sent before the recorder draws are silently dropped.

        Driving the recorded shell (or detaching the recorder) right after
        ``new-session`` races asciinema's startup: the keys vanish, the
        recording keeps running, and the only symptom is a stop-step
        timeout. A bounded readiness wait on the pane's content removes the
        race without polling a process name.
        """
        block = _scaffold_block(_recipe_text(name))
        ready = block.find("capture-pane")
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
        """
        block = _scaffold_block(_recipe_text(name))
        stop = block[block.index("asciinema rec"):]
        assert "has-session" in stop, (
            f"{name}: stop step does not wait for the recorder to exit")
        assert "deadline" in stop, f"{name}: recorder wait is unbounded"
        assert "test -s" in stop, f"{name}: the cast is never checked"

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

    def test_cli_scaffold_writes_the_cast_beside_the_render(self):
        """The scaffold must write the cast where the render step reads it.

        Every other form in the recipe (and the render block) uses
        ``<capture-dir>/<short-name>/recording.cast``.  A scaffold writing
        ``<capture-dir>/recording.cast`` renders nothing — or an older file
        — while looking successful.
        """
        block = _scaffold_block(_recipe_text("cli-recording.md"))
        assert "<capture-dir>/<short-name>/recording.cast" in block


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
    if probe_bound:
        line = text[idx:text.index("\n", idx)]
        assert probe_bound in line, (
            f"{name}: readiness probe is unbounded (no {probe_bound})")
