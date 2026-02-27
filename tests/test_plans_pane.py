"""Tests for the plans pane, extract_plan_intro, and plan work prompt."""

import inspect
import re
from unittest.mock import patch
from pathlib import Path

import pytest
from rich.text import Text

from pm_core.plan_parser import extract_plan_intro
from pm_core.tui.plans_pane import PlansPane


class TestExtractPlanIntro:
    """Tests for extract_plan_intro."""

    def test_empty_text(self):
        assert extract_plan_intro("") == ""

    def test_title_only(self):
        assert extract_plan_intro("# My Plan") == ""

    def test_title_and_description(self):
        text = "# My Plan\n\nThis is the intro paragraph.\nSecond line."
        result = extract_plan_intro(text)
        assert result == "This is the intro paragraph.\nSecond line."

    def test_stops_at_h2(self):
        text = "# Title\n\nIntro text here.\n\n## Motivation\n\nMore text."
        result = extract_plan_intro(text)
        assert result == "Intro text here."
        assert "Motivation" not in result
        assert "More text" not in result

    def test_no_title(self):
        text = "Some text without a title.\n\n## Section\n\nBody."
        result = extract_plan_intro(text)
        assert result == "Some text without a title."

    def test_real_plan_format(self):
        text = (
            "# Multi-candidate test-driven code generation\n"
            "\n"
            "Improve local LLM coding performance by separating test generation from solution\n"
            "generation and selecting the best candidate via test pass rate.\n"
            "\n"
            "## Motivation\n"
            "\n"
            "Current coding agents use a single model.\n"
        )
        result = extract_plan_intro(text)
        assert "Improve local LLM" in result
        assert "test pass rate" in result
        assert "Motivation" not in result


class TestPlansPane:
    """Tests for the PlansPane widget."""

    def test_initializes_empty(self):
        pane = PlansPane()
        assert pane._plans == []
        assert pane.selected_index == 0

    def test_selected_plan_id_none_when_empty(self):
        pane = PlansPane()
        assert pane.selected_plan_id is None

    def test_update_plans(self):
        pane = PlansPane()
        plans = [
            {"id": "plan-001", "name": "First", "file": "f.md", "status": "draft", "intro": "", "pr_count": 3},
            {"id": "plan-002", "name": "Second", "file": "g.md", "status": "draft", "intro": "", "pr_count": 0},
        ]
        pane.update_plans(plans)
        assert len(pane._plans) == 2
        assert pane.selected_plan_id == "plan-001"

    def test_selected_plan_id_after_index_change(self):
        pane = PlansPane()
        plans = [
            {"id": "plan-001", "name": "First", "file": "f.md", "status": "draft", "intro": "", "pr_count": 0},
            {"id": "plan-002", "name": "Second", "file": "g.md", "status": "draft", "intro": "", "pr_count": 0},
        ]
        pane.update_plans(plans)
        pane.selected_index = 1
        assert pane.selected_plan_id == "plan-002"

    def test_index_clamped_on_shorter_list(self):
        pane = PlansPane()
        plans = [
            {"id": "plan-001", "name": "First", "file": "f.md", "status": "draft", "intro": "", "pr_count": 0},
            {"id": "plan-002", "name": "Second", "file": "g.md", "status": "draft", "intro": "", "pr_count": 0},
        ]
        pane.update_plans(plans)
        pane.selected_index = 1
        # Now update with shorter list
        pane.update_plans([plans[0]])
        assert pane.selected_index == 0

    def test_render_returns_text(self):
        pane = PlansPane()
        result = pane.render()
        assert isinstance(result, Text)

    def test_render_shows_empty_message(self):
        pane = PlansPane()
        result = pane.render()
        assert "No plans yet" in result.plain

    def test_render_shows_plan_names(self):
        pane = PlansPane()
        pane.update_plans([
            {"id": "plan-001", "name": "Import from repo", "file": "f.md", "status": "draft", "intro": "", "pr_count": 2},
        ])
        result = pane.render()
        text = result.plain
        assert "plan-001" in text
        assert "Import from repo" in text
        assert "draft" in text
        assert "2 PRs" in text

    def test_render_shows_intro(self):
        pane = PlansPane()
        pane.update_plans([
            {"id": "plan-001", "name": "Test", "file": "f.md", "status": "draft",
             "intro": "This is the intro text.", "pr_count": 0},
        ])
        result = pane.render()
        assert "This is the intro text." in result.plain

    def test_render_shows_shortcuts(self):
        pane = PlansPane()
        result = pane.render()
        text = result.plain
        assert "add" in text
        assert "breakdown" in text
        assert "review" in text
        assert "load" in text
        assert "edit" in text
        assert "back" in text

    def test_key_action_mapping(self):
        """Verify _KEY_ACTIONS maps keys to the correct action strings."""
        pane = PlansPane()
        expected = {
            "a": "add",
            "w": "work",
            "d": "breakdown",
            "D": "deps",
            "l": "load",
            "e": "edit",
            "c": "review",
        }
        assert pane._KEY_ACTIONS == expected

    def test_work_and_breakdown_keys(self):
        """Verify w→work and d→breakdown key mappings."""
        pane = PlansPane()
        assert pane._KEY_ACTIONS["w"] == "work"
        assert pane._KEY_ACTIONS["d"] == "breakdown"
        assert pane._KEY_ACTIONS["c"] == "review"

    def test_handler_routes_match_key_actions(self):
        """Verify handle_plan_action routes each action to the matching pm command.

        This catches swapped conditions like:
            elif action == "breakdown":
                launch_pane(app, "pm plan review ...", "plan-review")  # WRONG
        """
        from pm_core.tui.pane_ops import handle_plan_action
        src = inspect.getsource(handle_plan_action)
        # For pane-launching actions, verify the action check and the
        # command string use the SAME action word.
        for action in ("breakdown", "review"):
            # Find: action == "<action>" ... pm plan <action>
            pattern = rf'action\s*==\s*"{action}".*?launch_pane\(.*?pm plan {action}'
            assert re.search(pattern, src, re.DOTALL), (
                f"action '{action}' does not route to 'pm plan {action}' in handle_plan_action"
            )
        # work runs via _run_command (creates its own tmux window)
        pattern = r'action\s*==\s*"work".*?_run_command\(.*?plan work'
        assert re.search(pattern, src, re.DOTALL), (
            "action 'work' does not route to 'plan work' via _run_command in handle_plan_action"
        )
        # load runs inline (no pane) via _run_command
        pattern = r'action\s*==\s*"load".*?_run_command\(.*?plan load'
        assert re.search(pattern, src, re.DOTALL), (
            "action 'load' does not route to 'plan load' via _run_command in handle_plan_action"
        )

    def test_render_singular_pr(self):
        pane = PlansPane()
        pane.update_plans([
            {"id": "plan-001", "name": "Test", "file": "f.md", "status": "draft", "intro": "", "pr_count": 1},
        ])
        result = pane.render()
        assert "1 PR" in result.plain
        # Should NOT have "1 PRs"
        assert "1 PRs" not in result.plain


# --- generate_plan_work_prompt tests ---

class TestGeneratePlanWorkPrompt:
    def _make_data(self):
        return {
            "project": {"name": "test", "repo": "test/repo", "base_branch": "master"},
            "prs": [
                {
                    "id": "pr-001",
                    "title": "Add feature",
                    "status": "in_progress",
                    "plan": "plan-001",
                    "depends_on": [],
                },
                {
                    "id": "pr-002",
                    "title": "Fix bug",
                    "status": "pending",
                    "plan": "other-plan",
                },
            ],
            "plans": [
                {
                    "id": "plan-001",
                    "name": "Test plan",
                    "file": "plans/plan-001.md",
                    "status": "active",
                },
            ],
        }

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_includes_plan_name(self, mock_root, mock_notes):
        mock_root.return_value = Path("/tmp/fake")
        from pm_core.prompt_gen import generate_plan_work_prompt
        data = self._make_data()
        prompt = generate_plan_work_prompt(data, "plan-001")
        assert 'plan-001' in prompt
        assert 'Test plan' in prompt

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_includes_plan_prs(self, mock_root, mock_notes):
        mock_root.return_value = Path("/tmp/fake")
        from pm_core.prompt_gen import generate_plan_work_prompt
        data = self._make_data()
        prompt = generate_plan_work_prompt(data, "plan-001")
        assert "pr-001" in prompt
        assert "Add feature" in prompt
        assert "[in_progress]" in prompt

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_includes_other_prs(self, mock_root, mock_notes):
        mock_root.return_value = Path("/tmp/fake")
        from pm_core.prompt_gen import generate_plan_work_prompt
        data = self._make_data()
        prompt = generate_plan_work_prompt(data, "plan-001")
        assert "## Other PRs" in prompt
        assert "pr-002" in prompt
        assert "Fix bug" in prompt

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_includes_available_commands(self, mock_root, mock_notes):
        mock_root.return_value = Path("/tmp/fake")
        from pm_core.prompt_gen import generate_plan_work_prompt
        data = self._make_data()
        prompt = generate_plan_work_prompt(data, "plan-001")
        assert "pm pr list" in prompt
        assert "pm plan list" in prompt
        assert "pm pr graph" in prompt
        assert "pm status" in prompt

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_includes_tui_section_when_session_provided(self, mock_root, mock_notes):
        mock_root.return_value = Path("/tmp/fake")
        from pm_core.prompt_gen import generate_plan_work_prompt
        data = self._make_data()
        prompt = generate_plan_work_prompt(data, "plan-001", session_name="pm-test")
        assert "pm tui view" in prompt
        assert "pm-test" in prompt

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_no_tui_section_without_session(self, mock_root, mock_notes):
        mock_root.return_value = Path("/tmp/fake")
        from pm_core.prompt_gen import generate_plan_work_prompt
        data = self._make_data()
        prompt = generate_plan_work_prompt(data, "plan-001")
        assert "pm tui view" not in prompt

    def test_raises_for_unknown_plan(self):
        from pm_core.prompt_gen import generate_plan_work_prompt
        data = self._make_data()
        with pytest.raises(ValueError, match="not found"):
            generate_plan_work_prompt(data, "nonexistent")

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_warns_against_spawning_sessions(self, mock_root, mock_notes):
        mock_root.return_value = Path("/tmp/fake")
        from pm_core.prompt_gen import generate_plan_work_prompt
        data = self._make_data()
        prompt = generate_plan_work_prompt(data, "plan-001")
        assert "Do not run commands that spawn new Claude sessions" in prompt

    @patch("pm_core.prompt_gen.notes.notes_section", return_value="")
    @patch("pm_core.prompt_gen.store.find_project_root")
    def test_ends_with_user_driven_message(self, mock_root, mock_notes):
        mock_root.return_value = Path("/tmp/fake")
        from pm_core.prompt_gen import generate_plan_work_prompt
        data = self._make_data()
        prompt = generate_plan_work_prompt(data, "plan-001")
        assert "The user will tell you what they need" in prompt
