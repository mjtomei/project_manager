"""Tests for `pm qa` CLI commands, focused on the artifacts category."""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from pm_core.cli.qa import qa_list, qa_show, qa_edit, qa_add


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


def test_qa_add_artifacts_category_creates_in_artifacts_dir(tmp_path):
    (tmp_path / "qa" / "artifacts").mkdir(parents=True)
    (tmp_path / "qa" / "instructions").mkdir(parents=True)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path), \
         patch("subprocess.run"):
        result = CliRunner().invoke(qa_add, ["My Recipe", "-c", "artifacts"])
    assert result.exit_code == 0
    assert (tmp_path / "qa" / "artifacts" / "my-recipe.md").exists()
    assert not (tmp_path / "qa" / "instructions" / "my-recipe.md").exists()


def test_qa_add_default_still_instructions(tmp_path):
    (tmp_path / "qa" / "artifacts").mkdir(parents=True)
    (tmp_path / "qa" / "instructions").mkdir(parents=True)
    with patch("pm_core.cli.qa.state_root", return_value=tmp_path), \
         patch("subprocess.run"):
        result = CliRunner().invoke(qa_add, ["My Test"])
    assert result.exit_code == 0
    assert (tmp_path / "qa" / "instructions" / "my-test.md").exists()
