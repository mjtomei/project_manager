"""Integration test for pm pr split-load on a local-backend project."""

import re
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from pm_core import store
from pm_core.cli import cli
from pm_core import spec_gen


def _write_manifest(tmp_path):
    spec_d = spec_gen.spec_dir(tmp_path, "pr-parent")
    spec_d.mkdir(parents=True, exist_ok=True)
    (spec_d / "split.md").write_text(
        "# Split for pr-parent\n"
        "\n"
        "## Child PRs\n"
        "\n"
        "### PR: Child One\n"
        "- **description**: first child\n"
        "- **branch**: pm/child-one\n"
        "\n"
        "### PR: Child Two\n"
        "- **description**: second child\n"
        "- **branch**: pm/child-two\n"
        "- **depends_on**: Child One\n"
    )


def _make_project(tmp_path):
    data = {
        "project": {
            "name": "test",
            "repo": str(tmp_path),
            "base_branch": "master",
            "backend": "local",
        },
        "plans": [],
        "prs": [
            {
                "id": "pr-parent",
                "plan": "plan-xyz",
                "title": "Parent PR",
                "branch": "pm/pr-parent",
                "status": "in_progress",
                "depends_on": [],
                "description": "parent",
                "workdir": str(tmp_path),
                "notes": [],
            }
        ],
    }
    store.save(data, tmp_path)


def test_split_load_creates_children_local_backend(tmp_path):
    _make_project(tmp_path)
    _write_manifest(tmp_path)

    fake_run_git = MagicMock(return_value=MagicMock(returncode=0, stderr=""))

    with patch("pm_core.cli.pr.git_ops.run_git", fake_run_git), \
         patch("pm_core.cli.pr.trigger_tui_refresh", lambda: None):
        runner = CliRunner()
        result = runner.invoke(cli, ["-C", str(tmp_path), "pr", "split-load", "pr-parent"])

    assert result.exit_code == 0, result.output
    assert "Found 2 child PRs" in result.output
    assert result.output.count("Created ") == 2
    assert "Loaded 2 child PRs" in result.output

    data2 = store.load(tmp_path)
    assert len(data2["prs"]) == 3

    by_title = {p["title"]: p for p in data2["prs"]}
    child_one = by_title["Child One"]
    child_two = by_title["Child Two"]

    id_re = re.compile(r"^pr-[0-9a-f]+$")
    assert id_re.match(child_one["id"])
    assert id_re.match(child_two["id"])
    assert child_one["id"] != "pr-parent"
    assert child_two["id"] != "pr-parent"
    assert child_one["id"] != child_two["id"]

    assert child_one["branch"] == "pm/child-one"
    assert child_two["branch"] == "pm/child-two"
    assert child_one["plan"] == "plan-xyz"
    assert child_two["plan"] == "plan-xyz"
    assert child_one["depends_on"] == []
    assert child_two["depends_on"] == [child_one["id"]]
    assert child_one["description"] == "first child"
    assert child_two["description"] == "second child"

    for call in fake_run_git.call_args_list:
        args = call.args
        assert not args or args[0] != "push"
