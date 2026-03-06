"""Tests for pm_core.spec_gen — spec generation for PR phases."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from pm_core import spec_gen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_data(pr_overrides=None):
    """Build a minimal project data dict with one PR."""
    pr = {
        "id": "pr-abc1234",
        "title": "Add widget feature",
        "description": "Add a new widget to the dashboard.",
        "status": "in_progress",
        "workdir": "/tmp/test-workdir",
    }
    if pr_overrides:
        pr.update(pr_overrides)
    return {
        "project": {"name": "test", "repo": "test-repo", "base_branch": "master"},
        "prs": [pr],
    }


# ---------------------------------------------------------------------------
# get_spec / set_spec
# ---------------------------------------------------------------------------

class TestGetSetSpec:
    def test_get_spec_empty(self):
        pr = {"id": "pr-1"}
        assert spec_gen.get_spec(pr, "impl") is None

    def test_set_and_get_spec(self):
        pr = {"id": "pr-1"}
        spec_gen.set_spec(pr, "impl", "some spec content")
        assert spec_gen.get_spec(pr, "impl") == "some spec content"
        assert pr["spec_impl"] == "some spec content"

    def test_all_phases(self):
        pr = {"id": "pr-1"}
        for phase in spec_gen.PHASES:
            spec_gen.set_spec(pr, phase, f"spec for {phase}")
            assert spec_gen.get_spec(pr, phase) == f"spec for {phase}"

    def test_invalid_phase(self):
        pr = {"id": "pr-1"}
        assert spec_gen.get_spec(pr, "invalid") is None
        # set_spec with invalid phase is a no-op
        spec_gen.set_spec(pr, "invalid", "test")
        assert "spec_invalid" not in pr


# ---------------------------------------------------------------------------
# get_spec_mode / pr_spec_mode
# ---------------------------------------------------------------------------

class TestSpecMode:
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_default_mode(self, mock_setting):
        assert spec_gen.get_spec_mode() == "prompt"

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="auto")
    def test_auto_mode(self, mock_setting):
        assert spec_gen.get_spec_mode() == "auto"

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="review")
    def test_review_mode(self, mock_setting):
        assert spec_gen.get_spec_mode() == "review"

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="invalid")
    def test_invalid_falls_back_to_prompt(self, mock_setting):
        assert spec_gen.get_spec_mode() == "prompt"

    @patch("pm_core.spec_gen.get_spec_mode", return_value="prompt")
    def test_pr_review_spec_overrides(self, mock_mode):
        pr = {"id": "pr-1", "review_spec": True}
        assert spec_gen.pr_spec_mode(pr) == "review"

    @patch("pm_core.spec_gen.get_spec_mode", return_value="auto")
    def test_pr_without_review_spec_uses_global(self, mock_mode):
        pr = {"id": "pr-1"}
        assert spec_gen.pr_spec_mode(pr) == "auto"


# ---------------------------------------------------------------------------
# generate_spec
# ---------------------------------------------------------------------------

class TestGenerateSpec:
    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_basic_generation(self, mock_setting, mock_claude):
        mock_claude.return_value = "## Requirements\n- Add widget\n"
        data = _make_data()

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl")

        assert spec == "## Requirements\n- Add widget"
        assert not needs_review
        mock_claude.assert_called_once()
        # Spec should be saved on PR
        pr = data["prs"][0]
        assert pr["spec_impl"] == "## Requirements\n- Add widget"

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_uses_existing_spec(self, mock_setting, mock_claude):
        data = _make_data({"spec_impl": "existing spec"})

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl")

        assert spec == "existing spec"
        assert not needs_review
        mock_claude.assert_not_called()

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_force_regenerate(self, mock_setting, mock_claude):
        mock_claude.return_value = "new spec"
        data = _make_data({"spec_impl": "existing spec"})

        spec, needs_review = spec_gen.generate_spec(
            data, "pr-abc1234", "impl", force=True,
        )

        assert spec == "new spec"
        mock_claude.assert_called_once()

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="review")
    def test_review_mode_needs_review(self, mock_setting, mock_claude):
        mock_claude.return_value = "some spec"
        data = _make_data()

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl")

        assert needs_review

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_prompt_mode_ambiguity_flag(self, mock_setting, mock_claude):
        mock_claude.return_value = "spec\nAMBIGUITY_FLAG\nWhat should X be?"
        data = _make_data()

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl")

        assert needs_review
        assert "AMBIGUITY_FLAG" in spec

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="auto")
    def test_auto_mode_no_review(self, mock_setting, mock_claude):
        mock_claude.return_value = "spec\nAMBIGUITY_FLAG\nQuestion?"
        data = _make_data()

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl")

        assert not needs_review

    def test_invalid_phase_raises(self):
        data = _make_data()
        with pytest.raises(ValueError, match="Invalid phase"):
            spec_gen.generate_spec(data, "pr-abc1234", "invalid")

    def test_missing_pr_raises(self):
        data = _make_data()
        with pytest.raises(ValueError, match="not found"):
            spec_gen.generate_spec(data, "pr-nonexistent", "impl")

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_saves_to_root(self, mock_setting, mock_claude, tmp_path):
        mock_claude.return_value = "test spec"
        data = _make_data()

        # Write initial project.yaml
        import yaml
        (tmp_path / "project.yaml").write_text(yaml.dump(data))

        spec_gen.generate_spec(data, "pr-abc1234", "impl", root=tmp_path)

        # Verify save was called (data was modified in place)
        assert data["prs"][0]["spec_impl"] == "test spec"


# ---------------------------------------------------------------------------
# format_spec_for_prompt
# ---------------------------------------------------------------------------

class TestFormatSpecForPrompt:
    def test_no_spec(self):
        pr = {"id": "pr-1"}
        assert spec_gen.format_spec_for_prompt(pr, "impl") == ""

    def test_with_spec(self):
        pr = {"id": "pr-1", "spec_impl": "## Requirements\n- Do X"}
        result = spec_gen.format_spec_for_prompt(pr, "impl")
        assert "Implementation Spec" in result
        assert "## Requirements" in result
        assert "Do X" in result

    def test_review_phase_label(self):
        pr = {"id": "pr-1", "spec_review": "Check Y"}
        result = spec_gen.format_spec_for_prompt(pr, "review")
        assert "Review Spec" in result

    def test_qa_phase_label(self):
        pr = {"id": "pr-1", "spec_qa": "Test Z"}
        result = spec_gen.format_spec_for_prompt(pr, "qa")
        assert "QA Spec" in result


# ---------------------------------------------------------------------------
# _build_spec_prompt
# ---------------------------------------------------------------------------

class TestBuildSpecPrompt:
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_impl_prompt_includes_description(self, mock_setting):
        data = _make_data()
        pr = data["prs"][0]
        prompt = spec_gen._build_spec_prompt(data, pr, "impl")
        assert "Add a new widget" in prompt
        assert "implementation spec" in prompt

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_review_prompt_includes_impl_spec(self, mock_setting):
        data = _make_data({"spec_impl": "impl requirements here"})
        pr = data["prs"][0]
        prompt = spec_gen._build_spec_prompt(data, pr, "review")
        assert "impl requirements here" in prompt
        assert "review spec" in prompt

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_qa_prompt_includes_both_prior_specs(self, mock_setting):
        data = _make_data({
            "spec_impl": "impl spec",
            "spec_review": "review spec",
        })
        pr = data["prs"][0]
        prompt = spec_gen._build_spec_prompt(data, pr, "qa")
        assert "impl spec" in prompt
        assert "review spec" in prompt
        assert "QA spec" in prompt

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="review")
    def test_review_mode_ambiguity_instruction(self, mock_setting):
        data = _make_data()
        pr = data["prs"][0]
        prompt = spec_gen._build_spec_prompt(data, pr, "impl")
        assert "reviewed by the user" in prompt

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_prompt_mode_ambiguity_flag_instruction(self, mock_setting):
        data = _make_data()
        pr = data["prs"][0]
        prompt = spec_gen._build_spec_prompt(data, pr, "impl")
        assert "AMBIGUITY_FLAG" in prompt
