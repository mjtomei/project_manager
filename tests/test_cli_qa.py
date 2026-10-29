"""Tests for `pm qa` CLI commands, focused on the artifacts category."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from pm_core.cli.qa import (
    qa_list, qa_show, qa_edit, qa_add_instruction, qa_add_artifact,
    qa_add_regression, qa_regression, qa_docs,
)


def _seed(pm_root: Path) -> None:
    inst = pm_root / "qa" / "instructions"
    inst.mkdir(parents=True)
    (inst / "login.md").write_text(
        "---\ntitle: Login\ndescription: log in\n---\nbody")

    art = pm_root / "qa" / "artifacts"
    art.mkdir(parents=True)
    (art / "tmux-rec.md").write_text(
        "---\ntitle: Tmux Rec\ndescription: capture\n---\nbody")


def test_qa_list_shows_artifacts(tmp_path):
    _seed(tmp_path)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path):
        result = CliRunner().invoke(qa_list, [])
    assert result.exit_code == 0
    assert "Instructions" in result.output
    assert "Regression Tests" in result.output
    assert "Artifact Recipes" in result.output
    assert "tmux-rec" in result.output


def test_qa_show_auto_detects_artifact(tmp_path):
    _seed(tmp_path)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path):
        result = CliRunner().invoke(qa_show, ["tmux-rec"])
    assert result.exit_code == 0
    assert "Tmux Rec" in result.output


def test_qa_show_explicit_artifacts_category(tmp_path):
    _seed(tmp_path)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path):
        result = CliRunner().invoke(qa_show, ["tmux-rec", "-c", "artifacts"])
    assert result.exit_code == 0
    assert "Tmux Rec" in result.output


def test_qa_edit_resolves_artifact(tmp_path):
    _seed(tmp_path)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path), \
         patch("subprocess.run") as mock_run:
        result = CliRunner().invoke(qa_edit, ["tmux-rec"])
    assert result.exit_code == 0
    # subprocess.run was called with the artifact's path
    args = mock_run.call_args.args[0]
    assert str(tmp_path / "qa" / "artifacts" / "tmux-rec.md") in args


def test_qa_add_artifact_creates_in_artifacts_dir(tmp_path):
    (tmp_path / "qa" / "artifacts").mkdir(parents=True)
    (tmp_path / "qa" / "instructions").mkdir(parents=True)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path), \
         patch("subprocess.run"):
        result = CliRunner().invoke(qa_add_artifact, ["My Recipe"])
    assert result.exit_code == 0
    assert (tmp_path / "qa" / "artifacts" / "my-recipe.md").exists()
    assert not (tmp_path / "qa" / "instructions" / "my-recipe.md").exists()


def test_qa_docs_prints_reference():
    result = CliRunner().invoke(qa_docs, [])
    assert result.exit_code == 0
    # Spot-check the doc actually loaded
    assert "pm QA library" in result.output
    assert "pm/qa/instructions/" in result.output
    assert "pm/qa/artifacts/" in result.output
    assert "Manifest" in result.output


def test_authoring_prompt_includes_doc_and_target_path(tmp_path):
    from pm_core import qa_authoring
    target = tmp_path / "qa" / "artifacts" / "demo.md"
    prompt = qa_authoring.build_authoring_prompt("demo", "artifacts", target)
    assert str(target) in prompt
    assert "artifact recipe" in prompt
    # Ground-truth section embedded
    assert "## File format" in prompt or "pm QA library" in prompt


def _seed_regression(pm_root: Path) -> None:
    reg = pm_root / "qa" / "regression"
    reg.mkdir(parents=True)
    (reg / "reg-test.md").write_text(
        "---\ntitle: Reg Test\ndescription: smoke\n---\nrun the thing")


def test_qa_regression_reports_a_missing_session(tmp_path):
    """No resolvable pm session at all: nothing to drive, nothing launched."""
    _seed_regression(tmp_path)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path), \
         patch("pm_core.cli.helpers._find_live_tui_pane",
               return_value=(None, None)), \
         patch("pm_core.claude_launcher.launch_claude") as launch:
        result = CliRunner().invoke(qa_regression, ["reg-test"])
    assert result.exit_code == 1
    assert "No pm tmux session found" in result.output
    launch.assert_not_called()


def test_qa_regression_requires_a_live_tui_pane(tmp_path):
    """The runner drives the TUI, so a dead recorded pane is not a target.

    ``_find_live_tui_pane`` reports the session name even when the TUI
    pane is gone (history/frames callers need that); launching a runner
    against it would fail on the first ``pm tui send``.
    """
    _seed_regression(tmp_path)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path), \
         patch("pm_core.cli.helpers._find_live_tui_pane",
               return_value=(None, "pm-stale")), \
         patch("pm_core.claude_launcher.launch_claude") as launch:
        result = CliRunner().invoke(qa_regression, ["reg-test"])
    assert result.exit_code == 1
    assert "No TUI pane found in session 'pm-stale'." in result.output
    launch.assert_not_called()


def test_qa_regression_launches_with_the_live_pane(tmp_path):
    _seed_regression(tmp_path)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path), \
         patch("pm_core.cli.helpers._find_live_tui_pane",
               return_value=("%42", "pm-test")), \
         patch("pm_core.claude_launcher.launch_claude",
               return_value=0) as launch:
        result = CliRunner().invoke(qa_regression, ["reg-test"])
    assert result.exit_code == 0
    prompt = launch.call_args.args[0]
    # The prompt names the session and the live pane the runner must drive.
    assert "pm-test" in prompt
    assert "%42" in prompt
    assert launch.call_args.kwargs["session_key"] == "qa-regression:reg-test"


def test_qa_add_regression_creates_in_regression_dir(tmp_path):
    (tmp_path / "qa" / "artifacts").mkdir(parents=True)
    (tmp_path / "qa" / "instructions").mkdir(parents=True)
    (tmp_path / "qa" / "regression").mkdir(parents=True)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path), \
         patch("subprocess.run"):
        result = CliRunner().invoke(qa_add_regression, ["TUI startup smoke"])
    assert result.exit_code == 0
    assert (tmp_path / "qa" / "regression" / "tui-startup-smoke.md").exists()
    assert not (tmp_path / "qa" / "instructions" / "tui-startup-smoke.md").exists()


def test_authoring_prompt_supports_regression(tmp_path):
    from pm_core import qa_authoring
    target = tmp_path / "qa" / "regression" / "demo.md"
    prompt = qa_authoring.build_authoring_prompt("demo", "regression", target)
    assert str(target) in prompt
    assert "regression test" in prompt


def test_qa_add_instruction_creates_in_instructions_dir(tmp_path):
    (tmp_path / "qa" / "artifacts").mkdir(parents=True)
    (tmp_path / "qa" / "instructions").mkdir(parents=True)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path), \
         patch("subprocess.run"):
        result = CliRunner().invoke(qa_add_instruction, ["My Test"])
    assert result.exit_code == 0
    assert (tmp_path / "qa" / "instructions" / "my-test.md").exists()
    assert not (tmp_path / "qa" / "artifacts" / "my-test.md").exists()
