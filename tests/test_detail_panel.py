"""Tests for pm_core.tui.detail_panel — plan section extraction and PR display."""

from pathlib import Path
from unittest.mock import patch

from pm_core.tui.detail_panel import (
    _extract_plan_section,
    _pr_display_id,
    DetailPanel,
)
from pm_core.plan_parser import extract_field


# ---------------------------------------------------------------------------
# _extract_plan_section
# ---------------------------------------------------------------------------

SAMPLE_PLAN = """\
# Plan: Improve testing

## PRs

### PR: Add unit tests
- **description**: Add tests for low coverage modules
- **tests**: tests/test_graph.py, tests/test_review.py
- **files**: pm_core/graph.py, pm_core/review.py

### PR: Fix linting
- **description**: Fix all linting issues
- **tests**: none
- **files**: pm_core/lint.py
"""


class TestExtractPlanSection:
    def test_finds_matching_pr(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(SAMPLE_PLAN)
        result = _extract_plan_section(plan, "Add unit tests")
        assert result is not None
        assert "test_graph.py" in result["tests"]
        assert "graph.py" in result["files"]

    def test_finds_second_pr(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(SAMPLE_PLAN)
        result = _extract_plan_section(plan, "Fix linting")
        assert result is not None
        assert result["files"] == "pm_core/lint.py"

    def test_returns_none_for_unknown_pr(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text(SAMPLE_PLAN)
        assert _extract_plan_section(plan, "Does not exist") is None

    def test_returns_none_for_missing_file(self, tmp_path):
        assert _extract_plan_section(tmp_path / "nonexistent.md", "t") is None

    def test_returns_none_when_no_fields(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("### PR: Empty\nNo fields here.\n")
        assert _extract_plan_section(plan, "Empty") is None

    def test_pr_with_only_tests(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("### PR: Tests only\n- **tests**: test.py\n")
        result = _extract_plan_section(plan, "Tests only")
        assert result is not None
        assert result["tests"] == "test.py"
        assert result["files"] == ""

    def test_pr_with_only_files(self, tmp_path):
        plan = tmp_path / "plan.md"
        plan.write_text("### PR: Files only\n- **files**: src.py\n")
        result = _extract_plan_section(plan, "Files only")
        assert result is not None
        assert result["files"] == "src.py"


# ---------------------------------------------------------------------------
# _pr_display_id
# ---------------------------------------------------------------------------

class TestPrDisplayId:
    def test_github_pr_number(self):
        assert _pr_display_id({"id": "pr-abc", "gh_pr_number": 42}) == "#42"

    def test_local_id_fallback(self):
        assert _pr_display_id({"id": "pr-abc"}) == "pr-abc"

    def test_missing_both(self):
        assert _pr_display_id({}) == "???"

    def test_prefers_github(self):
        pr = {"id": "pr-abc", "gh_pr_number": 7}
        assert _pr_display_id(pr) == "#7"

    def test_gh_pr_number_none(self):
        """None gh_pr_number falls back to id."""
        assert _pr_display_id({"id": "pr-x", "gh_pr_number": None}) == "pr-x"

    def test_gh_pr_number_zero(self):
        """0 is falsy, so falls back to id."""
        assert _pr_display_id({"id": "pr-x", "gh_pr_number": 0}) == "pr-x"


# ---------------------------------------------------------------------------
# extract_field (imported from plan_parser, used by detail_panel)
# ---------------------------------------------------------------------------

class TestExtractFieldIntegration:
    def test_basic_extraction(self):
        body = "- **description**: Some description text"
        assert extract_field(body, "description") == "Some description text"

    def test_missing_field(self):
        assert extract_field("no match here", "tests") == ""

    def test_empty_body(self):
        assert extract_field("", "files") == ""


# ---------------------------------------------------------------------------
# DetailPanel.render
# ---------------------------------------------------------------------------

class TestDetailPanelRender:
    """Test the render method by replacing the reactive descriptor with a plain attribute.

    Textual's reactive descriptor requires DOMNode initialization (app context).
    We temporarily replace it with a property that reads from an instance variable.
    """

    def _make_panel(self, pr_data=None, all_prs=None, plan=None, project_root=None) -> DetailPanel:
        panel = DetailPanel.__new__(DetailPanel)
        panel._test_pr_data = pr_data
        panel._all_prs = all_prs or []
        panel._plan = plan
        panel._project_root = project_root
        return panel

    def _render(self, panel):
        """Call render with pr_data reactive replaced by a plain property."""
        with patch.object(type(panel), "pr_data",
                          new_callable=lambda: property(lambda self: self._test_pr_data)):
            return panel.render()

    def test_render_no_pr(self):
        panel = self._make_panel()
        result = self._render(panel)
        assert "Select a PR" in str(result.renderable)

    def test_render_basic_pr(self):
        panel = self._make_panel(pr_data={
            "id": "pr-abc",
            "title": "Fix bug",
            "status": "pending",
            "branch": "fix-bug",
        })
        result = self._render(panel)
        text = str(result.renderable)
        assert "Fix bug" in text
        assert "pending" in text
        assert "fix-bug" in text

    def test_render_with_github_number(self):
        panel = self._make_panel(pr_data={
            "id": "pr-abc",
            "gh_pr_number": 42,
            "title": "Feature",
            "status": "in_progress",
            "branch": "feat",
        })
        result = self._render(panel)
        assert "#42" in result.title

    def test_render_with_description(self):
        panel = self._make_panel(pr_data={
            "id": "pr-x",
            "title": "T",
            "status": "pending",
            "branch": "b",
            "description": "Detailed description here",
        })
        result = self._render(panel)
        text = str(result.renderable)
        assert "Detailed description here" in text
        assert "Description" in text

    def test_render_with_dependencies(self):
        all_prs = [{"id": "pr-dep", "title": "Dep PR", "status": "merged"}]
        panel = self._make_panel(
            pr_data={
                "id": "pr-x", "title": "T", "status": "pending",
                "branch": "b", "depends_on": ["pr-dep"],
            },
            all_prs=all_prs,
        )
        result = self._render(panel)
        text = str(result.renderable)
        assert "Dependencies" in text
        assert "Dep PR" in text

    def test_render_with_unknown_dependency(self):
        panel = self._make_panel(pr_data={
            "id": "pr-x", "title": "T", "status": "pending",
            "branch": "b", "depends_on": ["pr-missing"],
        })
        result = self._render(panel)
        text = str(result.renderable)
        assert "pr-missing" in text

    def test_render_with_plan(self):
        panel = self._make_panel(
            pr_data={
                "id": "pr-x", "title": "T", "status": "pending",
                "branch": "b", "plan": "plan-abc",
            },
            plan={"name": "My Plan", "file": "plan.md"},
        )
        result = self._render(panel)
        text = str(result.renderable)
        assert "plan-abc" in text
        assert "My Plan" in text

    def test_render_with_plan_no_name(self):
        panel = self._make_panel(
            pr_data={
                "id": "pr-x", "title": "T", "status": "pending",
                "branch": "b", "plan": "plan-abc",
            },
            plan={"file": "plan.md"},
        )
        result = self._render(panel)
        text = str(result.renderable)
        assert "plan-abc" in text

    def test_render_with_machine(self):
        panel = self._make_panel(pr_data={
            "id": "pr-x", "title": "T", "status": "pending",
            "branch": "b", "agent_machine": "laptop",
        })
        result = self._render(panel)
        assert "laptop" in str(result.renderable)

    def test_render_with_gh_pr_link(self):
        panel = self._make_panel(pr_data={
            "id": "pr-x", "title": "T", "status": "pending",
            "branch": "b", "gh_pr": "https://github.com/org/repo/pull/1",
        })
        result = self._render(panel)
        assert "github.com" in str(result.renderable)

    def test_render_with_plan_section(self, tmp_path):
        plan_file = tmp_path / "plan.md"
        plan_file.write_text("### PR: My Feature\n- **tests**: test_x.py\n- **files**: x.py\n")
        panel = self._make_panel(
            pr_data={
                "id": "pr-x", "title": "My Feature", "status": "pending",
                "branch": "b",
            },
            plan={"name": "Plan", "file": "plan.md"},
            project_root=tmp_path,
        )
        result = self._render(panel)
        text = str(result.renderable)
        assert "test_x.py" in text
        assert "x.py" in text
