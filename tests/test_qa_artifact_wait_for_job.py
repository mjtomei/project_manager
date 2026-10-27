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

    @pytest.mark.parametrize("args", [
        ["--artifact", "/tmp/x"],                     # no --timeout
        ["--timeout", "5"],                           # no --artifact
        ["--timeout", "0", "--artifact", "/tmp/x",
         "-c", "true"],                               # non-positive timeout
        ["--timeout", "5", "--artifact", "/tmp/x"],   # no command
        ["--timeout", "5", "--artifact", "/tmp/x",
         "-c", "true", "extra"],                      # -c takes one string
        ["--bogus"],                                  # unknown flag
    ])
    def test_usage_errors(self, args):
        r = run_helper(args)
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        assert "wait-for-job:" in r.stderr

    def test_does_not_poll_process_names(self):
        text = HELPER.read_text()
        # The anti-pattern appears only in comments/help; no invocation.
        assert not re.search(r"^\s*(pgrep|pkill)\b", text, re.M)
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
        by every ``timeout`` implementation), and a second Ctrl-C does
        nothing because the trap is cleared.  The helper must bound the
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
