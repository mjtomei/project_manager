from unittest.mock import patch, MagicMock

import pytest

from pm_core import store
from pm_core.review import cli as review_cli
from pm_core.review import registry, paths


# --- artifact-id derivation -------------------------------------------------

def test_derive_artifact_id_file_keeps_extension():
    assert review_cli.derive_artifact_id("path/to/notes.md", "file") == "notes-md"


def test_derive_artifact_id_plan_uses_stem():
    assert review_cli.derive_artifact_id("pm/plans/plan-regression.md", "plan") == "plan-regression"


def test_derive_artifact_id_topic_slugified():
    assert review_cli.derive_artifact_id("Sycophancy Framing!", "topic") == "sycophancy-framing"


# --- target classification --------------------------------------------------

def test_resolve_target_type_plan_id_wins(tmp_path):
    data = {"plans": [{"id": "plan-x", "file": "plans/plan-x.md"}]}
    assert review_cli._resolve_target_type(data, "plan-x") == "plan"


def test_resolve_target_type_file(tmp_path, monkeypatch):
    f = tmp_path / "doc.md"
    f.write_text("x")
    monkeypatch.chdir(tmp_path)
    assert review_cli._resolve_target_type({}, "doc.md") == "file"


def test_resolve_target_type_topic():
    assert review_cli._resolve_target_type({}, "no such thing") == "topic"


# --- resume vs create vs archived ------------------------------------------

def _seed_root(tmp_path, reviews=None):
    data = {
        "project": {"name": "demo", "repo": "x", "base_branch": "master"},
        "plans": [],
        "prs": [],
    }
    if reviews is not None:
        data["reviews"] = reviews
    store.save(data, tmp_path)
    return tmp_path


def test_create_new_review_writes_entry_dir_and_state(tmp_path):
    root = _seed_root(tmp_path)
    with patch.object(review_cli, "launch_review_session") as launch:
        rid = review_cli.run_review("Some Topic", root=root, target_type="topic")
    assert rid == "some-topic"
    assert registry.get_review(store.load(root), "some-topic") is not None
    assert paths.dir_for(root, "some-topic", create=False).is_dir()
    assert paths.state_path(root, "some-topic", create=False).exists()
    launch.assert_called_once()


def test_resume_existing_active_review_no_new_entry(tmp_path):
    root = _seed_root(tmp_path, reviews=[
        {"id": "topic-x", "target": "topic x", "target-type": "topic", "status": "active"},
    ])
    with patch.object(review_cli, "launch_review_session") as launch:
        rid = review_cli.run_review("topic x", root=root, target_type="topic")
    assert rid == "topic-x"
    reviews = store.load(root)["reviews"]
    assert len([r for r in reviews if r["id"] == "topic-x"]) == 1
    launch.assert_called_once()


def test_archived_review_warns_and_does_not_launch(tmp_path, capsys):
    root = _seed_root(tmp_path, reviews=[
        {"id": "topic-x", "target": "topic x", "target-type": "topic", "status": "archived"},
    ])
    with patch.object(review_cli, "launch_review_session") as launch:
        rid = review_cli.run_review("topic x", root=root, target_type="topic")
    assert rid is None
    launch.assert_not_called()
    err = capsys.readouterr().err
    assert "archived" in err


# --- ui routing -------------------------------------------------------------

def test_review_ui_routes_to_server_not_target():
    from click.testing import CliRunner
    from pm_core.cli import cli
    runner = CliRunner()
    with patch.object(review_cli, "_run_ui_server") as ui, \
         patch.object(review_cli, "run_review") as run:
        result = runner.invoke(cli, ["review", "ui"])
    assert result.exit_code == 0
    ui.assert_called_once()
    run.assert_not_called()


def test_review_non_ui_target_calls_run_review(tmp_path):
    from click.testing import CliRunner
    from pm_core.cli import cli
    runner = CliRunner()
    with patch.object(review_cli, "_run_ui_server") as ui, \
         patch.object(review_cli, "run_review") as run, \
         patch("pm_core.store.find_project_root", return_value=tmp_path):
        result = runner.invoke(cli, ["review", "my-topic"])
    assert result.exit_code == 0
    ui.assert_not_called()
    run.assert_called_once()


# --- pane launch invokes tmux with the role --------------------------------

def test_launch_review_session_splits_pane_with_role(tmp_path):
    with patch("pm_core.tmux.in_tmux", return_value=True), \
         patch("pm_core.tmux.get_session_name", return_value="sess"), \
         patch("pm_core.tmux.get_window_id", return_value="@1"), \
         patch("pm_core.tmux.split_pane", return_value="%5") as split, \
         patch("pm_core.tmux.select_pane"), \
         patch("pm_core.pane_registry.register_pane") as reg, \
         patch("pm_core.pane_layout.preferred_split_direction", return_value="v"), \
         patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude"), \
         patch("pm_core.claude_launcher.build_claude_shell_cmd", return_value="claude ..."):
        review_cli.launch_review_session("PROMPT", cwd=str(tmp_path))
    split.assert_called_once()
    reg.assert_called_once()
    # role is the 4th positional arg of register_pane(session, window, pane_id, role, cmd)
    assert reg.call_args.args[3] == "literature-review"


def test_launch_review_session_targets_given_window(tmp_path):
    with patch("pm_core.tmux.in_tmux", return_value=True), \
         patch("pm_core.tmux.get_session_name", return_value="sess"), \
         patch("pm_core.tmux.split_pane", return_value="%5") as split, \
         patch("pm_core.tmux.select_pane"), \
         patch("pm_core.pane_registry.register_pane") as reg, \
         patch("pm_core.pane_layout.preferred_split_direction", return_value="v"), \
         patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude"), \
         patch("pm_core.claude_launcher.build_claude_shell_cmd", return_value="claude ..."):
        review_cli.launch_review_session("P", cwd=str(tmp_path), target_window="@9")
    # split targeted @9; register recorded the same window
    assert split.call_args.kwargs.get("window") == "@9"
    assert reg.call_args.args[1] == "@9"


def test_launch_review_session_foreground_when_not_in_tmux(tmp_path):
    with patch("pm_core.tmux.in_tmux", return_value=False), \
         patch("pm_core.claude_launcher.find_claude", return_value="/usr/bin/claude"), \
         patch("pm_core.claude_launcher.launch_claude") as fg:
        review_cli.launch_review_session("P", cwd=str(tmp_path))
    fg.assert_called_once()
