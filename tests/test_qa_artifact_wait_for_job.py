"""Regression tests for the shared wait-for-job.sh artifact helper.

Covers the pr-b19db15 failure modes:

- a completed renderer while a shell's command line contains the renderer
  pattern must not stall the wait (the self-matching ``pgrep -f`` bug);
- a renderer failure is a failure even when an artifact exists;
- a timeout is a failure and kills only the timed-out job;
- a stale leftover artifact is not success;
- a persistent observer/reaper must not block a finite job;
- pipeline failure status is preserved;
- the recording recipes use the helper and state the completion rules.
"""

import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest

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
            ["bash", "-c", "sleep 30; :", "agg-renderer"])
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
            decoy.terminate()
            decoy.wait(timeout=5)

    def test_renderer_failure_with_artifact_present(self, tmp_path):
        art = tmp_path / "recording.mp4"
        r = run_helper([
            "--timeout", "10", "--artifact", str(art),
            "-c", f"printf video > {shlex.quote(str(art))}; exit 7",
        ])
        assert r.returncode == 1
        assert "exit status 7" in r.stderr
        assert art.exists()  # artifact is irrelevant; the status wins

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

    def test_persistent_observer_does_not_block_finite_job(self, tmp_path):
        """A deliberately persistent observer/reaper must not stall the wait.

        This is the #249 S74 bare-``wait`` deadlock: wait only the captured
        finite job handle, not every child.
        """
        art = tmp_path / "snapshot.txt"
        observer = subprocess.Popen(
            ["bash", "-c", "sleep 30; :", "observer"])
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
            observer.terminate()
            observer.wait(timeout=5)

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
