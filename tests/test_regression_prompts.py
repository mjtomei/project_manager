"""Tests for pm_core.regression_prompts (prompt assembly + launch helpers)."""

from pathlib import Path
from unittest.mock import patch

import pytest

import pm_core.container as container_mod
from pm_core.regression_prompts import (
    CONTAINER_REGISTRY_MOUNT,
    build_regression_test_prompt,
    regression_launch_cmd,
    regression_launch_problem,
)


def _prompt(**overrides):
    kw = dict(
        title="TUI startup smoke",
        body="check that the TUI renders.",
        workdir="/workspace",
        scratch_dir="/scratch",
        target="`master` (commit `abc123def456`)",
        in_container=True,
        setup_recipes=[("/scratch/qa-instructions/tui-manual-test.md",
                        "TUI Manual Testing")],
        capture_recipes=[("/scratch/qa-artifacts/cli-recording.md", "")],
        captures_dir="/pm-captures/smoke/20261101T000000Z-ab12",
        file_findings=False,
    )
    kw.update(overrides)
    return build_regression_test_prompt(**kw)


def test_basic_assembly_no_findings():
    out = _prompt()
    # The environment block replaces the old live-session targeting.
    assert "## Test Environment" in out
    assert "inside a pm QA container" in out
    assert "`/workspace`" in out and "`master` (commit `abc123def456`)" in out
    assert "`/scratch`" in out
    assert "disposable project" in out
    # Recipes the runner installed are named with their agent-visible paths.
    assert "## Recipes" in out
    assert ("`/scratch/qa-instructions/tui-manual-test.md`: TUI Manual "
            "Testing") in out
    assert "`/scratch/qa-artifacts/cli-recording.md`" in out
    # This run's capture dir, outside git.
    assert "## Captures" in out
    assert "/pm-captures/smoke/20261101T000000Z-ab12" in out
    assert "git add" in out
    # Test body interpolated.
    assert "## QA Regression Test: TUI startup smoke" in out
    assert "check that the TUI renders." in out
    # No findings addendum without file_findings.
    assert "Filing Findings" not in out


def test_prompt_never_targets_a_live_session():
    """The pre-fix prompt told Claude "You are testing against tmux session:
    <the user's pm session>" and listed commands to drive it.  Nothing in
    the new prompt names a session to drive."""
    out = _prompt(file_findings=True, registry="/pm-project")
    assert "Session Context" not in out
    assert "testing against tmux session" not in out
    assert "pane-registry" not in out
    assert "The TUI pane ID is" not in out


def test_host_mode_says_so():
    out = _prompt(in_container=False, workdir="/h/clone",
                  scratch_dir="/h/scratch")
    assert "on the host (container mode is off)" in out
    assert "`/h/clone`" in out


def test_empty_recipe_libraries_are_stated():
    out = _prompt(setup_recipes=[], capture_recipes=[])
    assert "(none in this project's library" in out


def test_file_findings_addendum_covers_bugs_and_improvements():
    out = _prompt(file_findings=True, registry=CONTAINER_REGISTRY_MOUNT)
    assert "## Filing Findings" in out
    # Every filing command names the project registry explicitly: a bare
    # `pm pr add` in the run's clone would be lost with the clone.
    assert "pm -C /pm-project pr add '<title>' --plan bugs" in out
    assert "pm -C /pm-project pr add '<title>' --plan improvements" in out
    assert "pm -C /pm-project pr list --plan bugs" in out
    assert "pm -C /pm-project pr note add" in out
    assert "\n- **Bug**: `pm pr add" not in out
    # Pointer-to-capture guidance present.
    assert "capture" in out.lower()
    # No-fixes-here prohibition preserved.
    assert "don't fix it here" in out
    # Verdict-vs-filing separation kept.
    assert "Filing is independent of your verdict" in out


def test_file_findings_requires_a_registry():
    with pytest.raises(ValueError):
        _prompt(file_findings=True, registry=None)


def test_launch_cmd_runs_pm_qa_regression_for_the_project(tmp_path):
    root = tmp_path / "my proj" / "pm"
    cmd = regression_launch_cmd(root, "auth-flow")
    assert cmd == (f"pm -C '{root}' qa regression auth-flow --file-prs")
    assert regression_launch_cmd(root, "x", file_findings=False).endswith(
        "qa regression x")


def _library(tmp_path: Path, *ids: str) -> Path:
    root = tmp_path / "pm"
    reg = root / "qa" / "regression"
    reg.mkdir(parents=True)
    for i in ids:
        (reg / f"{i}.md").write_text(f"---\ntitle: {i}\n---\nbody\n")
    return root


def test_launch_problem_reports_an_empty_library(tmp_path):
    root = _library(tmp_path)
    problem = regression_launch_problem(root, "init-empty")
    assert "No regression tests in the library" in problem
    assert "pm qa author-regression" in problem


def test_launch_problem_reports_an_unknown_id(tmp_path):
    root = _library(tmp_path, "auth-flow")
    problem = regression_launch_problem(root, "nope")
    assert problem.startswith("Unknown regression test: nope")


def test_launch_problem_rejects_ids_outside_the_library(tmp_path):
    """An id is a file stem in pm/qa/regression/: a relative path must not
    reach another category's file."""
    root = _library(tmp_path, "auth-flow")
    (root / "qa" / "instructions").mkdir()
    (root / "qa" / "instructions" / "setup.md").write_text(
        "---\ntitle: setup\n---\nbody\n")
    problem = regression_launch_problem(root, "../instructions/setup")
    assert problem.startswith("Unknown regression test")


def test_launch_problem_reports_an_unusable_container_runtime(tmp_path):
    root = _library(tmp_path, "auth-flow")
    with patch.object(container_mod, "is_container_mode_enabled",
                      return_value=True), \
            patch.object(container_mod, "_runtime_status",
                         return_value=(False, "runtime down")):
        problem = regression_launch_problem(root, "auth-flow")
    assert "no agent was launched on the host" in problem
    assert "runtime down" in problem


def test_launch_problem_none_when_launchable(tmp_path):
    root = _library(tmp_path, "auth-flow")
    with patch.object(container_mod, "is_container_mode_enabled",
                      return_value=False):
        assert regression_launch_problem(root, "auth-flow") is None
