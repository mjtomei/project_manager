"""Regression tests for the shared wait-for-job.sh artifact helper.

Covers the pr-b19db15 failure modes:

- a completed renderer while a shell's command line contains the renderer
  pattern must not stall the wait (the self-matching ``pgrep -f`` bug);
- a renderer failure is a failure even when an artifact exists;
- a timeout is a failure and kills only the timed-out job;
- a signalled helper stops the job it started and says it was interrupted;
- a stale leftover artifact is not success;
- a persistent observer/reaper must not block a finite job;
- pipeline failure status is preserved;
- the recording recipes use the helper and state the completion rules.
"""

import os
import re
import shlex
import shutil
import signal
import subprocess
import textwrap
import time
from pathlib import Path

import pytest

from pm_core import prompt_gen
from pm_core.qa_instructions import list_artifacts
from pm_core.qa_loop import (
    QAScenario,
    _build_verification_prompt,
    _install_artifact_files,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PM_ROOT = REPO_ROOT / "pm"
ARTIFACTS = PM_ROOT / "qa" / "artifacts"
HELPER = ARTIFACTS / "wait-for-job.sh"
RECIPES = ["tmux-screen-recording.md", "cli-recording.md"]

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("timeout") is None,
    reason="bash and coreutils timeout are required",
)


def run_helper(args, env=None, timeout=60):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", str(HELPER), *args],
        capture_output=True, text=True, env=e, timeout=timeout,
    )


def _wait_gone(pid, timeout=15):
    """Wait until *pid* is no longer live, or fail.

    A killed job is often reparented and left as an unreaped zombie for a
    while, and ``os.kill(pid, 0)`` succeeds for zombies — the same
    finished-but-unreaped distinction the helper itself makes. Treat a
    zombie as gone; only a running process counts as "still alive" here.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
                state = fh.read().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            state = ""
        if state == "Z":
            return
        time.sleep(0.1)
    raise AssertionError(f"process {pid} is still running")


def _kill_group(proc):
    """Terminate a spawned decoy process *and its children*.

    The decoys carry their pattern in argv, so they run under ``bash -c``;
    terminating only the wrapper would orphan the ``sleep`` inside it for
    the rest of the suite run.
    """
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        proc.terminate()
    proc.wait(timeout=5)


def _recipe_text(name):
    return (ARTIFACTS / name).read_text()


def _render_block(text):
    """Extract the fenced block under '## Render to video'."""
    section = text.split("## Render to video", 1)[1]
    m = re.search(r"```[a-z]*\n(.*?)```", section, re.S)
    assert m, "no fenced render block found"
    return m.group(1)


# ---------------------------------------------------------------------------
# Helper presence and usage
# ---------------------------------------------------------------------------

class TestHelperBasics:
    def test_helper_exists_and_is_executable(self):
        assert HELPER.is_file(), f"missing helper: {HELPER}"
        assert os.access(HELPER, os.X_OK), "helper is not executable"

    def test_helper_parses(self):
        r = subprocess.run(["bash", "-n", str(HELPER)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_help_lists_contract(self):
        r = run_helper(["--help"])
        assert r.returncode == 0
        assert "--timeout" in r.stdout
        assert "--artifact" in r.stdout
        assert "--validate" in r.stdout
        # The interrupt escalation bound is documented where users look.
        assert "WAIT_FOR_JOB_KILL_GRACE" in r.stdout

    @pytest.mark.parametrize("args", [
        ["--artifact", "/tmp/x"],                     # no --timeout
        ["--timeout", "5"],                           # no --artifact
        ["--timeout", "0", "--artifact", "/tmp/x",
         "-c", "true"],                               # non-positive timeout
        ["--timeout", "5", "--artifact", "/tmp/x"],   # no command
        ["--timeout", "5", "--artifact", "/tmp/x",
         "-c", "true", "extra"],                      # -c takes one string
        ["--timeout", "5", "--artifact", "/tmp/x",
         "--validate", "", "-c", "true"],             # empty validator
        ["--bogus"],                                  # unknown flag
    ])
    def test_usage_errors(self, args):
        r = run_helper(args)
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        assert "wait-for-job:" in r.stderr

    def test_does_not_poll_process_names(self):
        text = HELPER.read_text()
        # The anti-patterns appear only in comments/help; no invocation.
        assert not re.search(r"^\s*(pgrep|pkill)\b", text, re.M)
        # No bare `wait`: it blocks on every child, including a deliberately
        # persistent observer/reaper — every wait here names its PID.
        assert not re.search(r"^\s*wait\s*(2>\S+)?\s*$", text, re.M)
        assert 'wait "$job_pid"' in text
        assert "timeout" in text
        assert "pipefail" in text


# ---------------------------------------------------------------------------
# Success / failure / timeout
# ---------------------------------------------------------------------------

class TestWaitOutcomes:
    def test_success_with_fresh_artifact(self, tmp_path):
        art = tmp_path / "recording.mp4"
        r = run_helper(["--timeout", "10", "--artifact", str(art),
                        "-c", f"printf video > {shlex.quote(str(art))}"])
        assert r.returncode == 0, r.stderr
        assert art.read_text() == "video"
        assert "artifact fresh" in r.stdout

    def test_completed_renderer_while_shell_has_renderer_pattern(self, tmp_path):
        """The pr-b19db15 regression: the wait must not match itself.

        A decoy shell carries the renderer name in its command line and
        outlives the job.  A ``pgrep -f`` wait would match it (and the
        waiting shell), stall, and hit the timeout; the helper must return
        promptly after the job and leave the decoy alone.
        """
        art = tmp_path / "recording.mp4"
        decoy = subprocess.Popen(
            ["bash", "-c", "sleep 30; :", "agg-renderer"],
            start_new_session=True)
        try:
            started = time.monotonic()
            r = run_helper([
                "--timeout", "10", "--artifact", str(art),
                "-c", f"printf video > {shlex.quote(str(art))}",
            ])
            elapsed = time.monotonic() - started
            assert r.returncode == 0, r.stderr
            assert elapsed < 8, f"wait stalled for {elapsed:.1f}s"
            assert decoy.poll() is None, "helper killed an unrelated job"
        finally:
            _kill_group(decoy)

    def test_renderer_failure_with_artifact_present(self, tmp_path):
        art = tmp_path / "recording.mp4"
        r = run_helper([
            "--timeout", "10", "--artifact", str(art),
            "-c", f"printf video > {shlex.quote(str(art))}; exit 7",
        ])
        assert r.returncode == 1
        assert "exit status 7" in r.stderr
        assert art.exists()  # artifact is irrelevant; the status wins

    def test_signal_killed_job_is_failure(self, tmp_path):
        """A job killed by a signal reports that status as a failure."""
        art = tmp_path / "recording.mp4"
        r = run_helper([
            "--timeout", "10", "--artifact", str(art),
            "-c", f'printf video > {shlex.quote(str(art))}; kill -TERM $$',
        ])
        assert r.returncode == 1
        assert "exit status 143" in r.stderr

    def test_exit_125_is_not_blamed_on_timeout_alone(self, tmp_path):
        """A job's own exit 125 must not be reported as ``timeout`` failing.

        ``timeout`` passes the job's status through, so a command that
        legitimately exits 125 (``docker run`` on a daemon error) would be
        misdiagnosed as "timeout could not start the job" — sending the
        worker after a phantom ``timeout`` problem.  The diagnostic must name
        both possibilities.
        """
        art = tmp_path / "out.txt"
        r = run_helper([
            "--timeout", "10", "--artifact", str(art),
            "-c", f"printf v > {shlex.quote(str(art))}; exit 125",
        ])
        assert r.returncode == 1
        assert "125" in r.stderr
        assert "job itself returned 125" in r.stderr

    def test_early_exit_124_is_a_job_failure_not_a_timeout(self, tmp_path):
        """124/137 mean "timeout" only when the bound was actually reached.

        A job can legitimately exit 124 on its own; blaming the bound would
        send the worker after a timeout that never happened.
        """
        art = tmp_path / "out.txt"
        r = run_helper([
            "--timeout", "30", "--artifact", str(art),
            "-c", f"printf v > {shlex.quote(str(art))}; exit 124",
        ])
        assert r.returncode == 1
        assert "exit status 124" in r.stderr
        assert "exceeded" not in r.stderr

    def test_interrupted_wait_kills_the_job(self, tmp_path):
        """A signalled helper stops the job and reports the interruption.

        The bug report's supervisor killed the waiting shell while the
        renderer kept running.  The helper must not call that a *job*
        failure (the job did not fail), and must not leave the renderer
        behind to race a later run over the same artifact.
        """
        art = tmp_path / "recording.mp4"
        pid_file = tmp_path / "job.pid"
        proc = subprocess.Popen(
            ["bash", str(HELPER), "--timeout", "60", "--artifact", str(art),
             "-c", f'echo $$ > {shlex.quote(str(pid_file))}; sleep 30'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=os.environ.copy())
        try:
            deadline = time.monotonic() + 10
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert pid_file.exists(), "job never started"
            job_pid = int(pid_file.read_text().strip())
            proc.terminate()
            _, err = proc.communicate(timeout=20)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        assert proc.returncode == 130, err
        assert "interrupted" in err
        _wait_gone(job_pid)

    def test_interrupted_wait_kills_a_term_ignoring_job(self, tmp_path):
        """A job that ignores TERM must not stretch the interrupt path.

        A shell that traps/ignores TERM passes the ignored disposition on to
        its children, so a plain TERM leaves the whole group alive and the
        trap blocks in ``wait``.  Left to itself that ends only via
        ``timeout``'s own ``--kill-after`` grace (~10s here, and not honoured
        by every ``timeout`` implementation).  The helper must bound the
        interrupt itself.
        """
        art = tmp_path / "recording.mp4"
        pid_file = tmp_path / "job.pid"
        proc = subprocess.Popen(
            ["bash", str(HELPER), "--timeout", "120", "--artifact", str(art),
             "-c", f'trap "" TERM; echo $$ > {shlex.quote(str(pid_file))}; '
                    'sleep 60'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=dict(os.environ, WAIT_FOR_JOB_KILL_GRACE="1"))
        try:
            deadline = time.monotonic() + 10
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert pid_file.exists(), "job never started"
            job_pid = int(pid_file.read_text().strip())
            started = time.monotonic()
            proc.terminate()
            _, err = proc.communicate(timeout=30)
            elapsed = time.monotonic() - started
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        assert proc.returncode == 130, err
        assert "interrupted" in err
        # Bounded by KILL_GRACE (1s here), not by timeout's own --kill-after
        # grace, which costs ~10s for the same job.
        assert elapsed < 5, f"interrupt took {elapsed:.1f}s"
        _wait_gone(job_pid)

    def test_second_interrupt_does_not_abandon_cleanup(self, tmp_path):
        """A repeated signal must not kill the helper mid-cleanup.

        Once the interrupt handler starts it stops the job's group and waits
        for it, so further TERM/INT/HUP are ignored until that finishes.  If
        the handler restored the *default* disposition instead, a second
        Ctrl-C (or a supervisor's repeated kill) would terminate the helper
        before it reported the interruption, leaving the diagnostic unsaid
        and the cleanup to the escalator alone.
        """
        art = tmp_path / "recording.mp4"
        pid_file = tmp_path / "job.pid"
        proc = subprocess.Popen(
            ["bash", str(HELPER), "--timeout", "120", "--artifact", str(art),
             "-c", f'trap "" TERM; echo $$ > {shlex.quote(str(pid_file))}; '
                    'sleep 60'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=dict(os.environ, WAIT_FOR_JOB_KILL_GRACE="2"))
        try:
            deadline = time.monotonic() + 10
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert pid_file.exists(), "job never started"
            job_pid = int(pid_file.read_text().strip())
            proc.terminate()
            time.sleep(0.3)          # let the handler start its cleanup
            proc.terminate()         # and interrupt it again
            _, err = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        assert proc.returncode == 130, (proc.returncode, err)
        assert "interrupted" in err
        _wait_gone(job_pid)

    def test_interrupt_kills_a_term_ignoring_descendant(self, tmp_path):
        """Reaping the wrapper is not enough to end the job's group.

        ``timeout`` exits as soon as its *direct* child dies, so a
        descendant that ignores TERM (or was orphaned when its parent
        died) outlives the interrupt.  Cancelling the escalator on the
        wrapper's exit would leave that renderer running behind a killed
        wait, to race a later run over the same artifact.
        """
        art = tmp_path / "recording.mp4"
        pid_file = tmp_path / "grandchild.pid"
        proc = subprocess.Popen(
            ["bash", str(HELPER), "--timeout", "120", "--artifact", str(art),
             "-c", f'bash -c \'trap "" TERM; sleep 60\' & '
                   f'echo $! > {shlex.quote(str(pid_file))}; wait'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=dict(os.environ, WAIT_FOR_JOB_KILL_GRACE="1"))
        try:
            deadline = time.monotonic() + 10
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert pid_file.exists(), "grandchild never started"
            grandchild_pid = int(pid_file.read_text().strip())
            started = time.monotonic()
            proc.terminate()
            _, err = proc.communicate(timeout=30)
            elapsed = time.monotonic() - started
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        assert proc.returncode == 130, err
        assert "interrupted" in err
        assert elapsed < 5, f"interrupt took {elapsed:.1f}s"
        _wait_gone(grandchild_pid)

    def test_interrupt_during_validation_stops_the_validator(self, tmp_path):
        """An interrupt while `--validate` runs must stop the validator too.

        The renderer has already exited by then, so the only live work is the
        validator.  Left as a foreground child, bash would defer the trap
        until the validator finished — unbounded if the validator is what
        hung.
        """
        art = tmp_path / "recording.mp4"
        pid_file = tmp_path / "validate.pid"
        proc = subprocess.Popen(
            ["bash", str(HELPER), "--timeout", "120", "--artifact", str(art),
             "--validate",
             f'echo $$ > {shlex.quote(str(pid_file))}; sleep 30',
             "-c", f"printf video > {shlex.quote(str(art))}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=dict(os.environ, WAIT_FOR_JOB_KILL_GRACE="1"))
        try:
            deadline = time.monotonic() + 10
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            assert pid_file.exists(), "validator never started"
            validator_pid = int(pid_file.read_text().strip())
            started = time.monotonic()
            proc.terminate()
            _, err = proc.communicate(timeout=30)
            elapsed = time.monotonic() - started
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        assert proc.returncode == 130, err
        assert "interrupted" in err
        assert elapsed < 5, f"interrupt took {elapsed:.1f}s"
        _wait_gone(validator_pid)

    def test_timeout_is_failure(self, tmp_path):
        art = tmp_path / "recording.mp4"
        started = time.monotonic()
        r = run_helper([
            "--timeout", "1", "--artifact", str(art),
            "-c", f"sleep 20; printf video > {shlex.quote(str(art))}",
        ])
        elapsed = time.monotonic() - started
        assert r.returncode == 3
        assert "exceeded 1s" in r.stderr
        assert elapsed < 15, "timeout did not bound the wait"

    def test_timeout_leaves_unrelated_jobs_alone(self, tmp_path):
        art = tmp_path / "recording.mp4"
        unrelated = subprocess.Popen(["sleep", "30"])
        try:
            r = run_helper([
                "--timeout", "1", "--artifact", str(art),
                "-c", "sleep 20",
            ])
            assert r.returncode == 3
            assert unrelated.poll() is None, "timeout killed an unrelated job"
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_timeout_kills_the_job_itself(self, tmp_path):
        """The bound must actually end the job, not just stop waiting on it.

        A helper that returned while the renderer kept running would leave
        work behind and let a later run mistake the stale artifact for a
        fresh one.
        """
        art = tmp_path / "recording.mp4"
        pid_file = tmp_path / "job.pid"
        r = run_helper([
            "--timeout", "1", "--artifact", str(art),
            "-c", f'echo $$ > {shlex.quote(str(pid_file))}; sleep 30',
        ])
        assert r.returncode == 3
        _wait_gone(int(pid_file.read_text().strip()))

    def test_timeout_kills_a_term_ignoring_descendant(self, tmp_path):
        """A descendant that ignores TERM must not outlive the timeout.

        ``timeout`` sends the signal to the job's group but exits as soon
        as its direct child dies, so it never KILLs a grandchild that
        ignored TERM.  The helper owns that group and must finish it — a
        renderer left running here is the orphan the helper exists to
        prevent.
        """
        art = tmp_path / "recording.mp4"
        pid_file = tmp_path / "grandchild.pid"
        r = run_helper([
            "--timeout", "1", "--artifact", str(art),
            "-c", f'bash -c \'trap "" TERM; sleep 60\' & '
                  f'echo $! > {shlex.quote(str(pid_file))}; sleep 30',
        ])
        assert r.returncode == 3
        assert pid_file.exists(), "grandchild never started"
        _wait_gone(int(pid_file.read_text().strip()))

    def test_persistent_observer_does_not_block_finite_job(self, tmp_path):
        """A deliberately persistent observer/reaper must not stall the wait.

        This is the #249 S74 bare-``wait`` deadlock: wait only the captured
        finite job handle, not every child.
        """
        art = tmp_path / "snapshot.txt"
        observer = subprocess.Popen(
            ["bash", "-c", "sleep 30; :", "observer"],
            start_new_session=True)
        try:
            started = time.monotonic()
            r = run_helper([
                "--timeout", "10", "--artifact", str(art),
                "-c", f"printf snapshot > {shlex.quote(str(art))}",
            ])
            elapsed = time.monotonic() - started
            assert r.returncode == 0, r.stderr
            assert elapsed < 8
            assert observer.poll() is None
        finally:
            _kill_group(observer)

    def test_argv_form_runs_command(self, tmp_path):
        """The `-- CMD [ARG...]` form runs the command and checks its status."""
        art = tmp_path / "out.txt"
        r = run_helper([
            "--timeout", "10", "--artifact", str(art), "--",
            "sh", "-c", f"printf done > {shlex.quote(str(art))}",
        ])
        assert r.returncode == 0, r.stderr
        assert art.read_text() == "done"

    def test_argv_form_reports_failure(self, tmp_path):
        art = tmp_path / "out.txt"
        r = run_helper(["--timeout", "10", "--artifact", str(art), "--",
                        "sh", "-c", "exit 9"])
        assert r.returncode == 1
        assert "exit status 9" in r.stderr

    def test_unreaped_zombie_does_not_block(self, tmp_path):
        """A finished-but-unreaped child is not live work."""
        art = tmp_path / "out.txt"
        zombie = subprocess.Popen(["true"])  # exits; not reaped until below
        try:
            time.sleep(0.2)
            started = time.monotonic()
            r = run_helper([
                "--timeout", "10", "--artifact", str(art),
                "-c", f"printf done > {shlex.quote(str(art))}",
            ])
            elapsed = time.monotonic() - started
            assert r.returncode == 0, r.stderr
            assert elapsed < 8
        finally:
            zombie.wait(timeout=5)


# ---------------------------------------------------------------------------
# Artifact freshness / validation
# ---------------------------------------------------------------------------

class TestArtifactChecks:
    def test_stale_leftover_is_not_success(self, tmp_path):
        art = tmp_path / "recording.mp4"
        art.write_text("old render")
        old = time.time() - 3600
        os.utime(art, (old, old))
        r = run_helper(["--timeout", "10", "--artifact", str(art),
                        "-c", "true"])
        assert r.returncode == 4
        assert "stale" in r.stderr or "not rewritten" in r.stderr

    def test_missing_artifact_is_failure(self, tmp_path):
        art = tmp_path / "recording.mp4"
        r = run_helper(["--timeout", "10", "--artifact", str(art),
                        "-c", "true"])
        assert r.returncode == 4
        assert "missing" in r.stderr

    def test_empty_artifact_is_failure(self, tmp_path):
        art = tmp_path / "recording.mp4"
        r = run_helper([
            "--timeout", "10", "--artifact", str(art),
            "-c", f": > {shlex.quote(str(art))}",
        ])
        assert r.returncode == 4
        assert "empty" in r.stderr

    def test_directory_artifact_is_failure(self, tmp_path):
        art = tmp_path / "recording.mp4"
        art.mkdir()
        r = run_helper(["--timeout", "10", "--artifact", str(art),
                        "-c", "true"])
        assert r.returncode == 4
        assert "not a regular file" in r.stderr

    def test_validate_failure(self, tmp_path):
        art = tmp_path / "recording.mp4"
        r = run_helper([
            "--timeout", "10", "--artifact", str(art),
            "--validate", "false",
            "-c", f"printf video > {shlex.quote(str(art))}",
        ])
        assert r.returncode == 4
        assert "failed validation" in r.stderr

    def test_validate_success_receives_artifact(self, tmp_path):
        art = tmp_path / "recording.mp4"
        r = run_helper([
            "--timeout", "10", "--artifact", str(art),
            "--validate", 'test -s "$ARTIFACT"',
            "-c", f"printf video > {shlex.quote(str(art))}",
        ])
        assert r.returncode == 0, r.stderr

    def test_validate_is_bounded(self, tmp_path):
        """A hanging validator must not stall the helper forever.

        The helper's whole point is bounding waits; a validator that never
        returns (a stuck ffprobe on a corrupt or network-mounted file) would
        reintroduce the unbounded wait one step after the job.
        """
        art = tmp_path / "recording.mp4"
        started = time.monotonic()
        r = run_helper([
            "--timeout", "1", "--artifact", str(art),
            "--validate", "sleep 20",
            "-c", f"printf video > {shlex.quote(str(art))}",
        ])
        elapsed = time.monotonic() - started
        assert r.returncode == 4
        assert "validation" in r.stderr
        assert elapsed < 15, f"validation was not bounded ({elapsed:.1f}s)"

    def test_validate_pipeline_failure_is_preserved(self, tmp_path):
        """A failing stage in the validator pipeline is not masked."""
        art = tmp_path / "recording.mp4"
        r = run_helper([
            "--timeout", "10", "--artifact", str(art),
            "--validate", "false | true",
            "-c", f"printf video > {shlex.quote(str(art))}",
        ])
        assert r.returncode == 4
        assert "failed validation" in r.stderr


# ---------------------------------------------------------------------------
# Pipeline status
# ---------------------------------------------------------------------------

class TestPipelineStatus:
    def test_failed_pipeline_stage_is_not_masked(self, tmp_path):
        art = tmp_path / "out.txt"
        r = run_helper(
            ["--timeout", "10", "--artifact", str(art),
             "-c", 'printf x > "$ART"; false | true'],
            env={"ART": str(art)},
        )
        assert r.returncode == 1, "pipefail did not preserve the failure"
        assert "exit status 1" in r.stderr

    def test_successful_pipeline_passes(self, tmp_path):
        art = tmp_path / "out.txt"
        r = run_helper(
            ["--timeout", "10", "--artifact", str(art),
             "-c", 'printf x > "$ART"; printf hi | tail -1 >/dev/null'],
            env={"ART": str(art)},
        )
        assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------
# Recipe guidance
# ---------------------------------------------------------------------------

class TestRecipes:
    @pytest.mark.parametrize("name", RECIPES)
    def test_recipe_is_listed(self, name):
        ids = {item["id"] for item in list_artifacts(PM_ROOT)}
        assert Path(name).stem in ids

    @pytest.mark.parametrize("name", RECIPES)
    def test_render_uses_helper_with_bounds(self, name):
        text = _recipe_text(name)
        block = _render_block(text)
        assert "wait-for-job.sh" in block
        assert "--timeout" in block
        assert "--artifact" in block
        assert "--validate" in block
        assert "ffprobe" in block
        assert "set -e" in block

    @pytest.mark.parametrize("name", RECIPES)
    def test_render_block_parses(self, name):
        block = _render_block(_recipe_text(name))
        r = subprocess.run(["bash", "-n"], input=block,
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{name} render block:\n{r.stderr}\n{block}"

    @pytest.mark.parametrize("name", RECIPES)
    def test_recipe_states_completion_rules(self, name):
        text = _recipe_text(name)
        assert "pgrep" in text          # names the anti-pattern
        assert "bare `wait`" in text or "bare wait" in text
        assert "leftover" in text.lower()
        assert "ffprobe" in text

    @pytest.mark.parametrize("name,marker,probe_bound", [
        ("tmux-screen-recording.md", "until tmux ls", None),
        ("web-ui-recording.md", "until curl", "--max-time"),
    ])
    def test_readiness_waits_are_bounded(self, name, marker, probe_bound):
        """Readiness polls must have a deadline, not just a sleep loop.

        The recipes teach bounded waits; an `until ...; do sleep; done`
        with no deadline hangs the worker forever when the session or
        server never comes up.  The probe itself must be bounded too — a
        deadline is only consulted between attempts, so a single blocking
        call (curl with no timeout) stalls the loop regardless.
        """
        text = _recipe_text(name)
        idx = text.index(marker)
        window = text[max(0, idx - 700):idx + 700]
        assert "deadline" in window, f"{name}: unbounded readiness wait"
        assert "exit 1" in window, f"{name}: readiness wait has no failure path"
        if probe_bound:
            line = text[idx:text.index("\n", idx)]
            assert probe_bound in line, (
                f"{name}: readiness probe is unbounded (no {probe_bound})")

    def test_helper_is_loaded_beside_recipes(self, tmp_path):
        """_install_artifact_files copies *.sh helpers with the recipes."""
        pm_root = tmp_path / "pm"
        art_dir = pm_root / "qa" / "artifacts"
        art_dir.mkdir(parents=True)
        (art_dir / "recipe.md").write_text("---\ntitle: R\n---\nbody\n")
        (art_dir / "wait-for-job.sh").write_text("#!/bin/sh\nexit 0\n")
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        scenario = QAScenario(
            index=1, title="T", focus="f", steps="s",
            artifact_paths=["artifacts/recipe.md"],
        )
        _install_artifact_files(pm_root, scenario, scratch, str(scratch))
        copied = scratch / "qa-artifacts" / "wait-for-job.sh"
        assert copied.is_file()
        assert os.access(copied, os.X_OK)
        assert scenario.artifact_paths == [
            f"{scratch}/qa-artifacts/recipe.md"]


def _render_script(name):
    """Extract the helper's ``-c '...'`` render script from a recipe."""
    block = _render_block(_recipe_text(name))
    m = re.search(r"-c '\n(.*?)\n    '\s*$", block, re.S)
    assert m, f"{name}: no -c render script found"
    return textwrap.dedent(m.group(1))


class TestRenderScript:
    """The render script itself, driven with stub renderers.

    The script runs under ``set -e``, so a bare ``read`` from an ffprobe that
    produced no output would abort the render before ffmpeg — making the
    recipe's documented even-rounding fallback dead code.  An unreadable GIF
    should still reach ffmpeg with the safe default filter.
    """

    @pytest.mark.parametrize("name", RECIPES)
    def test_unreadable_gif_falls_back_to_even_rounding(self, name, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        ffmpeg_args = tmp_path / "ffmpeg.args"

        def stub(prog, body):
            p = bin_dir / prog
            p.write_text("#!/bin/sh\n" + body + "\n")
            p.chmod(0o755)

        stub("agg", ': > "$4"')          # writes the GIF it was asked for
        stub("ffprobe", "exit 1")        # fails and prints nothing
        stub("ffmpeg",
             'printf "%s\\n" "$@" > "$FFMPEG_ARGS"\n'
             'for last; do :; done\n: > "$last"')

        cast = tmp_path / "recording.cast"
        cast.write_text("cast")
        mp4 = tmp_path / "recording.mp4"
        env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ.get('PATH', '')}",
            FFMPEG_ARGS=str(ffmpeg_args),
            cast=str(cast), mp4=str(mp4),
        )
        r = subprocess.run(
            ["bash", "-o", "pipefail", "-c", _render_script(name)],
            capture_output=True, text=True, env=env, timeout=60,
        )
        assert r.returncode == 0, r.stderr
        assert "scale=trunc(iw/2)*2:trunc(ih/2)*2" in ffmpeg_args.read_text()
        assert mp4.exists()


class TestRecipeInvocation:
    """The fenced render block as a worker runs it, with stub renderers.

    ``TestRenderScript`` drives only the helper's ``-c`` script.  A quoting
    regression in the *invocation* itself — the exported ``$cast``/``$mp4``,
    the ``--validate`` pipeline, ``$RECIPE_DIR`` — would slip past it, so
    this runs the whole block the recipe tells a worker to paste.
    """

    def _run(self, name, tmp_path, *, agg_body=': > "$4"', codec="h264",
             ffmpeg_body='for last; do :; done\nprintf video > "$last"',
             pre_existing_mp4=False, recipe_dir=None):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        def stub(prog, body):
            p = bin_dir / prog
            p.write_text("#!/bin/sh\n" + body + "\n")
            p.chmod(0o755)

        stub("agg", agg_body)
        stub("ffprobe",
             f'case "$*" in *codec_name*) echo {codec} ;; '
             '*) echo "160,90" ;; esac')
        stub("ffmpeg", ffmpeg_body)

        # Both recipes spell the capture dir as a placeholder, and
        # cli-recording adds a per-capture subdirectory; give them real paths
        # so the block runs exactly as written.
        raw = _render_block(_recipe_text(name))
        cap_dir = tmp_path / "cap"
        block = raw.replace("<capture-dir>", str(cap_dir)).replace(
            "<short-name>", "run")
        cast_dir = cap_dir / "run" if "<short-name>" in raw else cap_dir
        cast_dir.mkdir(parents=True)
        (cast_dir / "recording.cast").write_text("cast")
        mp4 = cast_dir / "recording.mp4"
        if pre_existing_mp4:
            mp4.write_text("old render")
            old = time.time() - 3600
            os.utime(mp4, (old, old))
        env = dict(
            os.environ,
            PATH=f"{bin_dir}:{os.environ.get('PATH', '')}",
            RECIPE_DIR=str(ARTIFACTS if recipe_dir is None else recipe_dir),
        )
        r = subprocess.run(["bash", "-c", block], capture_output=True,
                           text=True, env=env, timeout=120)
        return r, mp4

    @pytest.mark.parametrize("name", RECIPES)
    def test_render_block_produces_a_validated_artifact(self, name, tmp_path):
        r, mp4 = self._run(name, tmp_path)
        assert r.returncode == 0, r.stderr
        assert "wait-for-job: ok" in r.stdout
        assert mp4.is_file() and mp4.stat().st_size

    @pytest.mark.parametrize("name", RECIPES)
    def test_render_failure_is_reported(self, name, tmp_path):
        r, _ = self._run(name, tmp_path, agg_body="exit 1")
        assert r.returncode == 1, r.stderr
        assert "job failed with exit status 1" in r.stderr

    @pytest.mark.parametrize("name", RECIPES)
    def test_wrong_codec_fails_validation(self, name, tmp_path):
        r, _ = self._run(name, tmp_path, codec="vp9")
        assert r.returncode == 4, r.stderr
        assert "failed validation" in r.stderr

    @pytest.mark.parametrize("name", RECIPES)
    def test_missing_helper_fails_with_an_actionable_message(self, name,
                                                             tmp_path):
        """A wrong RECIPE_DIR must fail loudly, not skip the render.

        The helper ships beside the recipe in the scenario's
        ``qa-artifacts/`` directory, so a worker that leaves ``RECIPE_DIR``
        at its default in a container where the repo root is not the cwd
        would otherwise get a bare "No such file or directory" — and the
        render would silently never run.
        """
        empty = tmp_path / "nowhere"
        empty.mkdir()
        r, mp4 = self._run(name, tmp_path, recipe_dir=str(empty))
        assert r.returncode == 1, r.stderr
        assert "wait-for-job.sh missing or not executable" in r.stderr
        assert "RECIPE_DIR" in r.stderr
        assert not mp4.exists()

    @pytest.mark.parametrize("name", RECIPES)
    def test_unrewritten_artifact_is_stale(self, name, tmp_path):
        """A leftover mp4 the render never rewrote is not a completed render."""
        r, _ = self._run(
            name, tmp_path, pre_existing_mp4=True,
            ffmpeg_body="exit 0",          # writes nothing
        )
        assert r.returncode == 4, r.stderr
        assert "stale" in r.stderr or "not rewritten" in r.stderr


# ---------------------------------------------------------------------------
# Shared prompt guidance
# ---------------------------------------------------------------------------

def _data(pr):
    return {
        "project": {"base_branch": "master", "backend": "github"},
        "prs": [pr],
        "plans": [],
    }


class TestPromptGuidance:
    """The background-job block must reach every session that runs jobs."""

    MARKER = "## Background Jobs and Test Runs"

    def test_block_names_the_anti_patterns(self):
        block = prompt_gen._background_jobs_block()
        assert "pgrep -f" in block
        assert "bare `wait`" in block
        assert "pipefail" in block
        assert "wait-for-job.sh" in block

    def test_impl_and_review_prompts_carry_the_block(self):
        data = _data({"id": "pr-x", "title": "T", "plan": "bugs",
                      "description": "d"})
        assert self.MARKER in prompt_gen.generate_prompt(data, "pr-x")
        assert self.MARKER in prompt_gen.generate_review_prompt(data, "pr-x")
        assert self.MARKER in prompt_gen.generate_review_prompt(
            data, "pr-x", review_loop=True, review_iteration=1,
            review_loop_id="loop-x")

    def test_qa_child_prompt_carries_the_block_and_recipe_dir_hint(self):
        data = _data({"id": "pr-x", "title": "T", "description": "d"})
        scenario = QAScenario(
            index=1, title="T", focus="f", steps="s",
            artifact_paths=["/scratch/qa-artifacts/tmux-screen-recording.md"])
        prompt = prompt_gen.generate_qa_child_prompt(
            data, "pr-x", scenario, workdir="/tmp/w", session_name="s",
            scratch_dir="/tmp/scratch", captures_root="/caps")
        assert self.MARKER in prompt
        assert "RECIPE_DIR" in prompt
        assert "wait-for-job.sh" in prompt


# ---------------------------------------------------------------------------
# Verifier guidance
# ---------------------------------------------------------------------------

class TestVerifierFreshness:
    def test_verification_prompt_requires_fresh_artifact(self):
        scenario = QAScenario(
            index=1, title="T", focus="f", steps="s",
            artifact_paths=["/scratch/qa-artifacts/tmux-screen-recording.md"],
        )
        prompt = _build_verification_prompt(
            scenario, "PASS", pane_output="output",
            captures_scenario_dir="/caps/pr-x/scenarios/1",
        )
        flat = " ".join(prompt.split())
        assert "this run" in flat
        assert "freshly written" in flat
        assert "stale" in flat.lower()

    def test_judgment_bullet_flags_stale_artifacts(self):
        """A stale leftover must be FLAGGED, not just discouraged in prose."""
        scenario = QAScenario(
            index=1, title="T", focus="f", steps="s",
            artifact_paths=["/scratch/qa-artifacts/tmux-screen-recording.md"],
        )
        prompt = _build_verification_prompt(
            scenario, "PASS", pane_output="output",
            captures_scenario_dir="/caps/pr-x/scenarios/1",
        )
        flat = " ".join(prompt.split())
        assert "**FLAGGED**" in flat
        bullet = flat.split("If any required artifact (Step 3)")[1]
        bullet = bullet.split("**FLAGGED**")[0]
        assert "stale" in bullet.lower(), bullet
        assert "invalid" in bullet.lower(), bullet

    def test_verified_requires_a_fresh_artifact(self):
        """The VERIFIED bullet must not read as presence-only."""
        scenario = QAScenario(
            index=1, title="T", focus="f", steps="s",
            artifact_paths=["/scratch/qa-artifacts/tmux-screen-recording.md"],
        )
        prompt = _build_verification_prompt(
            scenario, "PASS", pane_output="output",
            captures_scenario_dir="/caps/pr-x/scenarios/1",
        )
        flat = " ".join(prompt.split())
        assert "present and fresh" in flat
