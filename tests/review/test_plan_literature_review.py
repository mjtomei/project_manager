from unittest.mock import patch

from click.testing import CliRunner

from pm_core import store
from pm_core.cli import cli
from pm_core.review import registry, paths


def _seed_plan_root(tmp_path):
    (tmp_path / "plans").mkdir(parents=True, exist_ok=True)
    (tmp_path / "plans" / "plan-1.md").write_text("# Plan One\n")
    data = {
        "project": {"name": "demo", "repo": "x", "base_branch": "master"},
        "plans": [{"id": "plan-1", "name": "One", "file": "plans/plan-1.md",
                   "status": "draft", "parent": None}],
        "prs": [],
    }
    store.save(data, tmp_path)
    return tmp_path


def test_literature_review_creates_review_for_plan(tmp_path):
    root = _seed_plan_root(tmp_path)
    runner = CliRunner()
    with patch("pm_core.cli.plan.state_root", return_value=root), \
         patch("pm_core.review.cli.launch_review_session") as launch:
        result = runner.invoke(cli, ["plan", "literature-review", "plan-1"])
    assert result.exit_code == 0, result.output
    # registry entry created with target-type plan and the plan file path
    entry = registry.get_review(store.load(root), "plan-1")
    assert entry["target-type"] == "plan"
    assert entry["target"] == "plans/plan-1.md"
    assert paths.state_path(root, "plan-1", create=False).exists()
    launch.assert_called_once()
    # role passed through
    assert launch.call_args.kwargs.get("role") == "literature-review"


def test_literature_review_resolves_plan_window(tmp_path):
    root = _seed_plan_root(tmp_path)
    runner = CliRunner()
    with patch("pm_core.cli.plan.state_root", return_value=root), \
         patch("pm_core.tmux.in_tmux", return_value=True), \
         patch("pm_core.tmux.get_session_name", return_value="sess"), \
         patch("pm_core.tmux.find_window_by_name", return_value={"id": "@7"}), \
         patch("pm_core.review.cli.launch_review_session") as launch:
        result = runner.invoke(cli, ["plan", "literature-review", "plan-1"])
    assert result.exit_code == 0, result.output
    assert launch.call_args.kwargs.get("target_window") == "@7"


def test_literature_review_missing_plan_errors(tmp_path):
    root = _seed_plan_root(tmp_path)
    runner = CliRunner()
    with patch("pm_core.cli.plan.state_root", return_value=root):
        result = runner.invoke(cli, ["plan", "literature-review", "nope"])
    assert result.exit_code != 0
    assert "not found" in result.output
