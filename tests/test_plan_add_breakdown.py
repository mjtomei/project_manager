"""plan add produces the PR breakdown; the separate breakdown step is gone.

pr-30888b1 folded `pm plan breakdown` (TUI key `w`) into `pm plan add`.  These
tests pin both halves: the plan add prompt carries the breakdown guidance, and
nothing in pm still offers the removed command, key, or review prompt.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from pm_core import guide, store
from pm_core.cli import cli
from pm_core.cli.plan import plan as plan_group
from pm_core.plans.review import REVIEW_PROMPTS
from pm_core.tui import pane_ops
from pm_core.tui.plans_pane import PlansPane


def _state(tmp_path: Path, prs: list[dict] | None = None,
           plan_body: str = "# Plan\n\n## PRs\n") -> Path:
    data = {"project": {"name": "test", "repo": "/tmp/fake",
                        "base_branch": "master"},
            "plans": [{"id": "pl-001", "name": "Plan",
                       "file": "plans/pl-001.md"}],
            "prs": prs or []}
    store.save(data, tmp_path)
    (tmp_path / "plans").mkdir(exist_ok=True)
    (tmp_path / "plans" / "pl-001.md").write_text(plan_body)
    return tmp_path


def _pr(i: int, **kw) -> dict:
    pr = {"id": f"pr-{i:03d}", "title": f"Existing PR {i}", "plan": "pl-001",
          "status": "pending", "depends_on": [], "description": "d",
          "branch": None, "workdir": None, "gh_pr_number": None, "notes": []}
    pr.update(kw)
    return pr


def _plan_add_prompt(root: Path, name: str = "New plan") -> str:
    with patch("pm_core.cli.plan.find_claude", return_value=None):
        result = CliRunner().invoke(cli, ["-C", str(root), "plan", "add", name])
    assert result.exit_code == 0, result.output
    return result.output


class TestBreakdownCommandRemoved:
    def test_breakdown_is_not_a_plan_subcommand(self):
        assert "breakdown" not in plan_group.commands

    def test_invoking_breakdown_fails(self, tmp_path):
        root = _state(tmp_path)
        result = CliRunner().invoke(
            cli, ["-C", str(root), "plan", "breakdown", "pl-001"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_breakdown_review_prompt_removed(self):
        assert "plan-breakdown" not in REVIEW_PROMPTS

    def test_plans_pane_has_no_breakdown_key(self):
        assert "w" not in PlansPane._KEY_ACTIONS
        assert "breakdown" not in PlansPane._KEY_ACTIONS.values()
        assert "breakdown" not in PlansPane().render().plain

    def test_breakdown_action_launches_nothing(self, tmp_path):
        app = MagicMock()
        app._root = tmp_path
        app._data = {"plans": [{"id": "pl-001", "file": "a.md"}]}
        with patch.object(pane_ops, "_launch_in_plans_window") as win, \
                patch.object(pane_ops, "launch_pane") as pane:
            pane_ops.handle_plan_action(app, "breakdown", "pl-001")
        win.assert_not_called()
        pane.assert_not_called()
        app._run_command.assert_not_called()

    def test_no_source_references_to_breakdown_step(self):
        """No help text, prompt, or key map still offers the removed step."""
        forbidden = ("plan breakdown", "plan-breakdown", "plan:breakdown",
                     "Break plan into PRs", "w=breakdown", "=breakdown  ")
        pkg = Path(__file__).resolve().parent.parent / "pm_core"
        hits = []
        for path in pkg.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                if needle in text:
                    hits.append(f"{path.relative_to(pkg)}: {needle!r}")
        assert not hits, hits


class TestPlanAddPromptIncludesBreakdown:
    def test_goal_covers_plan_and_prs(self, tmp_path):
        out = _plan_add_prompt(_state(tmp_path))
        assert "break it down into PRs" in out
        assert 'break it down into a "## PRs" section' in out

    def test_breakdown_discussion_and_format(self, tmp_path):
        out = _plan_add_prompt(_state(tmp_path))
        assert "Discuss the breakdown with the user" in out
        assert "If the source document already proposes PRs" in out
        for field in ("### PR: <title>", "- **description**:", "- **tests**:",
                      "- **files**:", "- **depends_on**:"):
            assert field in out, field
        assert "Separate PR entries with --- lines." in out
        assert "Prefer more small PRs over fewer large ones" in out
        assert "Only add depends_on when there's a real ordering constraint" in out
        assert "human-guided testing" in out  # _MANUAL_TESTING_GUIDANCE

    def test_closing_points_at_load_then_review(self, tmp_path):
        out = _plan_add_prompt(_state(tmp_path))
        data = store.load(tmp_path)
        new_id = [p["id"] for p in data["plans"] if p["id"] != "pl-001"][0]
        assert f"`pm plan load {new_id}`" in out
        assert f"`pm plan review {new_id}`" in out

    def test_no_existing_listing_on_empty_project(self, tmp_path):
        out = _plan_add_prompt(_state(tmp_path))
        assert "Existing PRs in this project" not in out
        assert "Separate PR entries with --- lines.\n\nGuidelines:" in out

    def test_existing_prs_listed_with_status_and_deps(self, tmp_path):
        prs = [_pr(1), _pr(2, status="merged", depends_on=["pr-001"])]
        out = _plan_add_prompt(_state(tmp_path, prs=prs))
        assert "Existing PRs in this project:" in out
        assert "  pr-001: Existing PR 1 [pending]" in out
        assert "  pr-002: Existing PR 2 [merged] (depends on: pr-001)" in out

    def test_existing_listing_is_bounded(self, tmp_path):
        prs = [_pr(i) for i in range(200)]
        out = _plan_add_prompt(_state(tmp_path, prs=prs))
        assert "  pr-039: Existing PR 39" in out
        assert "  pr-040: Existing PR 40" not in out
        assert "(+160 more; run `pm pr list` to see all PRs)" in out


class TestReviewCoversMissingBreakdown:
    def test_plan_add_check_requires_prs_section(self):
        check = REVIEW_PROMPTS["plan-add"]
        assert '"## PRs"' in check
        assert '"### PR:"' in check
        assert "substantive plan description" in check

    def test_preload_review_proposes_breakdown_when_missing(self, tmp_path):
        root = _state(tmp_path, plan_body="# Plan\n\nJust a draft.\n")
        with patch("pm_core.cli.plan.find_claude", return_value=None):
            result = CliRunner().invoke(
                cli, ["-C", str(root), "plan", "review", "pl-001"])
        assert result.exit_code == 0, result.output
        assert 'If the plan file has no "## PRs" section yet' in result.output
        assert "start by proposing a PR breakdown" in result.output


    def test_load_without_prs_points_at_review(self, tmp_path):
        """`plan load` on a plan with no ## PRs names the recovery path that
        keeps the plan id (`plan review`), not `plan add`, which mints a new
        plan and orphans the draft."""
        root = _state(tmp_path, plan_body="# Plan\n\nJust a draft.\n")
        result = CliRunner().invoke(
            cli, ["-C", str(root), "plan", "load", "pl-001"])
        assert result.exit_code != 0
        assert "No PRs found in plan file" in result.output
        assert "pm plan review pl-001" in result.output
        assert "plan add" not in result.output


class TestGuideHasNoBreakdownStep:
    def test_step_description(self):
        desc = guide.STEP_DESCRIPTIONS["has_plan_draft"]
        assert "Break plan into PRs" not in desc
        assert "PR breakdown" in desc

    def test_setup_prompt_flow(self, tmp_path):
        root = _state(tmp_path, plan_body="# Plan\n\nDraft.\n")
        state, ctx = guide.detect_state(root)
        assert state == "has_plan_draft"
        prompt = guide.build_setup_prompt(state, ctx, root)
        assert "`a` → `c` → `l`" in prompt
        assert "press `w`" not in prompt
        assert "`w` —" not in prompt
        assert "### If the plan has no PRs yet" in prompt
        assert "breaks it into PRs" in prompt
