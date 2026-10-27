"""Tests for pm_core.spec_gen — spec generation for PR phases."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

import yaml

from pm_core import spec_gen, store


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


def _save_to_disk(data, root):
    """Write project.yaml so locked_update can load it."""
    store.save(data, root)


def _make_spec_file(root, pr_id, phase, content):
    """Create a spec file under root/specs/ and return its path string."""
    d = root / "specs" / pr_id
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{phase}.md"
    f.write_text(content)
    return str(f)


# ---------------------------------------------------------------------------
# spec_file_path / spec_dir
# ---------------------------------------------------------------------------

class TestSpecFilePath:
    def test_derives_path(self, tmp_path):
        path = spec_gen.spec_file_path(tmp_path, "pr-123", "impl")
        assert path.name == "impl.md"
        assert "pr-123" in str(path)
        assert "specs" in str(path)
        assert str(tmp_path) in str(path)

    def test_qa_phase(self, tmp_path):
        path = spec_gen.spec_file_path(tmp_path, "pr-1", "qa")
        assert path.name == "qa.md"


# ---------------------------------------------------------------------------
# get_spec / set_spec (file-based)
# ---------------------------------------------------------------------------

class TestGetSetSpec:
    def test_get_spec_empty(self):
        pr = {"id": "pr-1"}
        assert spec_gen.get_spec(pr, "impl") is None

    def test_set_and_get_spec(self, tmp_path):
        """set_spec writes to workdir/pm/specs/, get_spec reads it back."""
        # root = workdir/pm/ so get_spec can find it via pr["workdir"]
        workdir = tmp_path
        root = workdir / "pm"
        pr = {"id": "pr-1", "workdir": str(workdir)}
        path = spec_gen.set_spec(pr, "impl", "some spec content", root=root)

        assert path is not None
        assert path.exists()
        assert path.read_text() == "some spec content"
        assert spec_gen.get_spec(pr, "impl") == "some spec content"

    def test_all_phases(self, tmp_path):
        workdir = tmp_path
        root = workdir / "pm"
        pr = {"id": "pr-1", "workdir": str(workdir)}
        for phase in spec_gen.PHASES:
            spec_gen.set_spec(pr, phase, f"spec for {phase}", root=root)
            assert spec_gen.get_spec(pr, phase) == f"spec for {phase}"

    def test_invalid_phase(self):
        pr = {"id": "pr-1"}
        assert spec_gen.get_spec(pr, "invalid") is None
        assert spec_gen.set_spec(pr, "invalid", "test") is None
        assert "spec_invalid" not in pr

    def test_get_spec_from_workdir(self, tmp_path):
        """get_spec finds spec in the PR's workdir pm/specs/ directory."""
        workdir = tmp_path
        spec_dir = workdir / "pm" / "specs" / "pr-1"
        spec_dir.mkdir(parents=True)
        (spec_dir / "impl.md").write_text("workdir spec")
        pr = {"id": "pr-1", "workdir": str(workdir)}
        assert spec_gen.get_spec(pr, "impl") == "workdir spec"

    def test_get_spec_missing_file(self):
        """get_spec returns None when no spec exists in workdir or local pm."""
        pr = {"id": "pr-1", "workdir": "/nonexistent/workdir"}
        assert spec_gen.get_spec(pr, "impl") is None

    def test_spec_stored_in_project_dir(self, tmp_path):
        """Specs are stored under the pm project directory, not ~/.pm."""
        pr = {"id": "pr-1"}
        path = spec_gen.set_spec(pr, "impl", "test content", root=tmp_path)
        assert str(path).startswith(str(tmp_path))
        assert "specs" in str(path)


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
    def test_basic_generation(self, mock_setting, mock_claude, tmp_path):
        mock_claude.return_value = "## Requirements\n- Add widget\n"
        data = _make_data()
        _save_to_disk(data, tmp_path)

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl",
                                                     root=tmp_path)

        assert spec == "## Requirements\n- Add widget"
        assert not needs_review
        mock_claude.assert_called_once()
        # Spec should be saved at the convention path
        assert (tmp_path / "specs" / "pr-abc1234" / "impl.md").exists()

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_uses_existing_spec(self, mock_setting, mock_claude, tmp_path):
        # Spec lives in workdir/pm/specs/ — get_spec finds it via pr["workdir"]
        spec_dir = tmp_path / "pm" / "specs" / "pr-abc1234"
        spec_dir.mkdir(parents=True)
        (spec_dir / "impl.md").write_text("existing spec")
        data = _make_data({"workdir": str(tmp_path)})

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl")

        assert spec == "existing spec"
        assert not needs_review
        mock_claude.assert_not_called()

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_force_regenerate(self, mock_setting, mock_claude, tmp_path):
        mock_claude.return_value = "new spec"
        spec_path = _make_spec_file(tmp_path, "pr-abc1234", "impl", "existing spec")
        data = _make_data({"workdir": str(tmp_path)})
        _save_to_disk(data, tmp_path)

        spec, needs_review = spec_gen.generate_spec(
            data, "pr-abc1234", "impl", root=tmp_path, force=True,
        )

        assert spec == "new spec"
        mock_claude.assert_called_once()

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="review")
    def test_review_mode_needs_review(self, mock_setting, mock_claude, tmp_path):
        mock_claude.return_value = "some spec"
        data = _make_data()
        _save_to_disk(data, tmp_path)

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl",
                                                     root=tmp_path)

        assert needs_review

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_prompt_mode_ambiguity_flag(self, mock_setting, mock_claude, tmp_path):
        mock_claude.return_value = "spec\nAMBIGUITY_FLAG\nWhat should X be?"
        data = _make_data()
        _save_to_disk(data, tmp_path)

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl",
                                                     root=tmp_path)

        assert needs_review
        assert "AMBIGUITY_FLAG" in spec

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="auto")
    def test_auto_mode_no_review(self, mock_setting, mock_claude, tmp_path):
        mock_claude.return_value = "spec\nAMBIGUITY_FLAG\nQuestion?"
        data = _make_data()
        _save_to_disk(data, tmp_path)

        spec, needs_review = spec_gen.generate_spec(data, "pr-abc1234", "impl",
                                                     root=tmp_path)

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
        _save_to_disk(data, tmp_path)

        spec_gen.generate_spec(data, "pr-abc1234", "impl", root=tmp_path)

        # Verify spec file was created at the convention path
        spec_path = tmp_path / "specs" / "pr-abc1234" / "impl.md"
        assert spec_path.exists()
        assert spec_path.read_text() == "test spec"


# ---------------------------------------------------------------------------
# format_spec_for_prompt
# ---------------------------------------------------------------------------

class TestFormatSpecForPrompt:
    def test_no_spec(self):
        pr = {"id": "pr-1"}
        assert spec_gen.format_spec_for_prompt(pr, "impl") == ""

    def test_with_spec(self, tmp_path):
        spec_dir = tmp_path / "pm" / "specs" / "pr-1"
        spec_dir.mkdir(parents=True)
        (spec_dir / "impl.md").write_text("## Requirements\n- Do X")
        pr = {"id": "pr-1", "workdir": str(tmp_path)}
        result = spec_gen.format_spec_for_prompt(pr, "impl")
        assert "Implementation Spec" in result
        assert "## Requirements" in result
        assert "Do X" in result

    def test_qa_phase_label(self, tmp_path):
        spec_dir = tmp_path / "pm" / "specs" / "pr-1"
        spec_dir.mkdir(parents=True)
        (spec_dir / "qa.md").write_text("Test Z")
        pr = {"id": "pr-1", "workdir": str(tmp_path)}
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
    def test_qa_prompt_includes_impl_spec(self, mock_setting, tmp_path):
        spec_dir = tmp_path / "pm" / "specs" / "pr-abc1234"
        spec_dir.mkdir(parents=True)
        (spec_dir / "impl.md").write_text("impl spec")
        data = _make_data({"workdir": str(tmp_path)})
        pr = data["prs"][0]
        prompt = spec_gen._build_spec_prompt(data, pr, "qa")
        assert "impl spec" in prompt
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


# ---------------------------------------------------------------------------
# has_pending_spec / get_pending_spec_phase
# ---------------------------------------------------------------------------

class TestPendingSpec:
    def test_no_pending(self):
        pr = {"id": "pr-1"}
        assert not spec_gen.has_pending_spec(pr)
        assert spec_gen.get_pending_spec_phase(pr) is None

    def test_with_pending(self):
        pr = {"id": "pr-1", "spec_pending": {"phase": "impl", "generated_at": "2025-01-01"}}
        assert spec_gen.has_pending_spec(pr)
        assert spec_gen.get_pending_spec_phase(pr) == "impl"

    def test_invalid_pending_format(self):
        pr = {"id": "pr-1", "spec_pending": "invalid"}
        assert spec_gen.has_pending_spec(pr)  # truthy string
        assert spec_gen.get_pending_spec_phase(pr) is None  # not a dict


# ---------------------------------------------------------------------------
# approve_spec
# ---------------------------------------------------------------------------

class TestApproveSpec:
    def test_approve_clears_pending(self, tmp_path):
        _make_spec_file(tmp_path, "pr-abc1234", "impl", "original spec")
        data = _make_data({
            "spec_pending": {"phase": "impl", "generated_at": "2025-01-01"},
        })

        phase = spec_gen.approve_spec(data, "pr-abc1234")
        assert phase == "impl"
        assert "spec_pending" not in data["prs"][0]

    def test_approve_with_edits(self, tmp_path):
        _make_spec_file(tmp_path, "pr-abc1234", "impl", "original spec")
        data = _make_data({
            "workdir": str(tmp_path),
            "spec_pending": {"phase": "impl", "generated_at": "2025-01-01"},
        })
        _save_to_disk(data, tmp_path)

        phase = spec_gen.approve_spec(data, "pr-abc1234", root=tmp_path,
                                       edited_text="edited spec")
        assert phase == "impl"
        # The file should be updated at the convention path
        spec_path = tmp_path / "specs" / "pr-abc1234" / "impl.md"
        assert spec_path.read_text() == "edited spec"
        assert "spec_pending" not in data["prs"][0]

    def test_approve_no_pending(self):
        data = _make_data()
        phase = spec_gen.approve_spec(data, "pr-abc1234")
        assert phase is None

    def test_approve_missing_pr(self):
        data = _make_data()
        phase = spec_gen.approve_spec(data, "pr-nonexistent")
        assert phase is None


# ---------------------------------------------------------------------------
# oldest_pending_spec_pr
# ---------------------------------------------------------------------------

class TestOldestPendingSpecPr:
    def test_no_pending(self):
        data = _make_data()
        assert spec_gen.oldest_pending_spec_pr(data) is None

    def test_single_pending(self):
        data = _make_data({
            "spec_pending": {"phase": "impl", "generated_at": "2025-01-01T00:00:00"},
        })
        assert spec_gen.oldest_pending_spec_pr(data) == "pr-abc1234"

    def test_multiple_pending_returns_oldest(self):
        data = {
            "project": {"name": "test", "repo": "test-repo", "base_branch": "master"},
            "prs": [
                {"id": "pr-1", "spec_pending": {"phase": "impl", "generated_at": "2025-01-02"}},
                {"id": "pr-2", "spec_pending": {"phase": "qa", "generated_at": "2025-01-01"}},
                {"id": "pr-3"},  # no pending
            ],
        }
        assert spec_gen.oldest_pending_spec_pr(data) == "pr-2"


# ---------------------------------------------------------------------------
# generate_spec sets spec_pending when review needed
# ---------------------------------------------------------------------------

class TestGenerateSpecPending:
    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="review")
    def test_review_mode_sets_pending(self, mock_setting, mock_claude, tmp_path):
        mock_claude.return_value = "some spec"
        data = _make_data()
        _save_to_disk(data, tmp_path)

        spec_gen.generate_spec(data, "pr-abc1234", "impl", root=tmp_path)

        pr = data["prs"][0]
        assert "spec_pending" in pr
        assert pr["spec_pending"]["phase"] == "impl"

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_no_pending_when_no_ambiguity(self, mock_setting, mock_claude, tmp_path):
        mock_claude.return_value = "clean spec"
        data = _make_data()
        _save_to_disk(data, tmp_path)

        spec_gen.generate_spec(data, "pr-abc1234", "impl", root=tmp_path)

        pr = data["prs"][0]
        assert "spec_pending" not in pr

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_ambiguity_sets_pending(self, mock_setting, mock_claude, tmp_path):
        mock_claude.return_value = "spec\nAMBIGUITY_FLAG\nQuestion?"
        data = _make_data()
        _save_to_disk(data, tmp_path)

        spec_gen.generate_spec(data, "pr-abc1234", "impl", root=tmp_path)

        pr = data["prs"][0]
        assert "spec_pending" in pr
        assert pr["spec_pending"]["phase"] == "impl"


# ---------------------------------------------------------------------------
# spec_generation_preamble
# ---------------------------------------------------------------------------

class TestSpecGenerationPreamble:
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="auto")
    def test_auto_mode_generates_preamble(self, mock_setting, tmp_path):
        """Auto mode generates single-session preamble with both phases."""
        pr = {"id": "pr-1"}
        result = spec_gen.spec_generation_preamble(pr, "impl", root=tmp_path)
        assert "How This Session Works" in result
        assert "Step 0" in result
        assert "best judgement" in result
        assert "Save the spec to" in result

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="prompt")
    def test_prompt_mode_generates_preamble(self, mock_setting, tmp_path):
        """Prompt mode generates preamble with unresolved-ambiguity guidance."""
        pr = {"id": "pr-1"}
        result = spec_gen.spec_generation_preamble(pr, "impl", root=tmp_path)
        assert "How This Session Works" in result
        assert "Step 0" in result
        assert "UNRESOLVED" in result
        assert "Save the spec to" in result

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="review")
    def test_review_mode_generates_preamble(self, mock_setting, tmp_path):
        """Review mode generates preamble with user-approval guidance."""
        pr = {"id": "pr-1"}
        result = spec_gen.spec_generation_preamble(pr, "impl", root=tmp_path)
        assert "How This Session Works" in result
        assert "Step 0" in result
        assert "approve" in result
        assert "Save the spec to" in result

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="auto")
    def test_existing_spec_returns_empty(self, mock_setting, tmp_path):
        spec_dir = tmp_path / "pm" / "specs" / "pr-1"
        spec_dir.mkdir(parents=True)
        (spec_dir / "impl.md").write_text("existing spec")
        pr = {"id": "pr-1", "workdir": str(tmp_path)}
        result = spec_gen.spec_generation_preamble(pr, "impl", root=tmp_path)
        assert result == ""

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="auto")
    def test_qa_preamble(self, mock_setting, tmp_path):
        pr = {"id": "pr-1"}
        result = spec_gen.spec_generation_preamble(pr, "qa", root=tmp_path)
        assert "QA" in result
        assert "Save the spec to" in result

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="auto")
    def test_auto_mode_documents_ambiguities(self, mock_setting, tmp_path):
        """Auto mode tells Claude to document resolved ambiguities."""
        pr = {"id": "pr-1"}
        result = spec_gen.spec_generation_preamble(pr, "impl", root=tmp_path)
        assert "Ambiguities" in result

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="auto")
    def test_preamble_includes_file_path(self, mock_setting, tmp_path):
        """Preamble tells Claude the exact file path to write to."""
        pr = {"id": "pr-1"}
        result = spec_gen.spec_generation_preamble(pr, "impl", root=tmp_path)
        assert "impl.md" in result
        assert "specs" in result
        # Path should be relative (works inside containers)
        assert "specs/pr-1/impl.md" in result

    @patch("pm_core.spec_gen.get_global_setting_value", return_value="auto")
    def test_preamble_path_in_project_dir(self, mock_setting, tmp_path):
        """Spec path in preamble should be in the pm project directory."""
        pr = {"id": "pr-xyz"}
        result = spec_gen.spec_generation_preamble(pr, "impl", root=tmp_path)
        # Path should be relative for container compatibility
        assert "specs/pr-xyz/impl.md" in result


# ---------------------------------------------------------------------------
# reject_spec
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# get_spec_mocks_section
# ---------------------------------------------------------------------------

class TestGetSpecMocksSection:
    def _make_pr_with_qa_spec(self, tmp_path, spec_content):
        """Create a PR dict with a QA spec file at the workdir path."""
        spec_dir = tmp_path / "pm" / "specs" / "pr-1"
        spec_dir.mkdir(parents=True)
        (spec_dir / "qa.md").write_text(spec_content)
        return {"id": "pr-1", "workdir": str(tmp_path)}

    def test_no_qa_spec_returns_empty(self):
        pr = {"id": "pr-1"}
        assert spec_gen.get_spec_mocks_section(pr) == ""

    def test_spec_without_mocks_section(self, tmp_path):
        pr = self._make_pr_with_qa_spec(tmp_path, "## Requirements\n- Test X\n\n## Edge Cases\n- Timeout")
        assert spec_gen.get_spec_mocks_section(pr) == ""

    def test_mocks_section_extracted(self, tmp_path):
        spec = (
            "## Requirements\n- Test X\n\n"
            "## Mocks\n"
            "- Claude sessions: use FakeClaudeSession returning fixed output\n"
            "- git operations: real (not mocked)\n\n"
            "## Edge Cases\n- Timeout"
        )
        pr = self._make_pr_with_qa_spec(tmp_path, spec)
        result = spec_gen.get_spec_mocks_section(pr)
        assert "Mocks" in result
        assert "FakeClaudeSession" in result
        assert "git operations" in result
        # The next section heading should not be included
        assert "Edge Cases" not in result
        # The wrapper text should be present
        assert "do not devise your own" in result

    def test_mocks_as_last_section(self, tmp_path):
        """Mocks section at end of spec (no following ## heading)."""
        spec = (
            "## Requirements\n- Test X\n\n"
            "## Mocks\n"
            "- tmux: mock via FakeTmux\n"
        )
        pr = self._make_pr_with_qa_spec(tmp_path, spec)
        result = spec_gen.get_spec_mocks_section(pr)
        assert "FakeTmux" in result

    def test_mocks_heading_case_insensitive(self, tmp_path):
        spec = "## MOCKS\n- Claude: FakeClaudeSession\n"
        pr = self._make_pr_with_qa_spec(tmp_path, spec)
        result = spec_gen.get_spec_mocks_section(pr)
        assert "FakeClaudeSession" in result

    def test_mocks_heading_with_subtitle(self, tmp_path):
        """## Mocks section with subtitle text still detected."""
        spec = "## Mocks and Dependencies\n- git: real\n"
        pr = self._make_pr_with_qa_spec(tmp_path, spec)
        result = spec_gen.get_spec_mocks_section(pr)
        assert "git: real" in result

    def test_empty_mocks_section_returns_empty(self, tmp_path):
        spec = "## Mocks\n\n## Edge Cases\n- Timeout"
        pr = self._make_pr_with_qa_spec(tmp_path, spec)
        assert spec_gen.get_spec_mocks_section(pr) == ""

    def test_mocks_heading_not_included_in_output(self, tmp_path):
        """The original heading line is stripped; wrapper provides its own."""
        spec = "## Mocks\n- Claude: mock\n"
        pr = self._make_pr_with_qa_spec(tmp_path, spec)
        result = spec_gen.get_spec_mocks_section(pr)
        # Should have exactly one ## Mocks heading (from the wrapper), not two
        assert result.count("## Mocks") == 1

    @patch("pm_core.spec_gen.store.find_project_root")
    def test_library_takes_precedence_over_spec(self, mock_root, tmp_path):
        """pm/qa/mocks/ library is used instead of spec_qa when it has content."""
        from pm_core import qa_instructions

        pm_root = tmp_path / "pm"
        pm_root.mkdir()
        mock_root.return_value = pm_root

        # Write a library mock
        mocks_d = qa_instructions.mocks_dir(pm_root)
        (mocks_d / "claude-session.md").write_text(
            "---\ntitle: Claude Session Mock\ndescription:\ntags: []\n---\n"
            "## Contract\nLibraryMockContent\n"
        )

        # Also create a spec_qa with its own mocks section
        spec = "## Mocks\n- SpecMockContent\n"
        pr = self._make_pr_with_qa_spec(tmp_path, spec)

        result = spec_gen.get_spec_mocks_section(pr)
        assert "LibraryMockContent" in result
        assert "SpecMockContent" not in result


class TestRejectSpec:
    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="review")
    def test_reject_keeps_spec_pending(self, mock_setting, mock_claude, tmp_path):
        """Rejecting a spec regenerates it and keeps spec_pending set."""
        mock_claude.return_value = "regenerated spec content"
        data = _make_data({
            "spec_pending": {"phase": "impl", "generated_at": "2025-01-01"},
        })
        _save_to_disk(data, tmp_path)

        phase = spec_gen.reject_spec(data, "pr-abc1234", root=tmp_path)

        assert phase == "impl"
        pr = data["prs"][0]
        # spec_pending should still be set (blocking gate stays active)
        assert "spec_pending" in pr
        assert pr["spec_pending"]["phase"] == "impl"

    @patch("pm_core.spec_gen.launch_claude_print")
    @patch("pm_core.spec_gen.get_global_setting_value", return_value="review")
    def test_reject_with_feedback_temporarily_updates_description(
        self, mock_setting, mock_claude, tmp_path
    ):
        """Feedback is appended to description during regen, then restored."""
        captured_prompts = []

        def capture_prompt(prompt, **kwargs):
            captured_prompts.append(prompt)
            return "regenerated spec"

        mock_claude.side_effect = capture_prompt
        data = _make_data({
            "description": "Original description.",
            "spec_pending": {"phase": "impl", "generated_at": "2025-01-01"},
        })
        _save_to_disk(data, tmp_path)

        spec_gen.reject_spec(
            data, "pr-abc1234", feedback="Make it shorter", root=tmp_path
        )

        # After rejection, description should be restored
        pr = data["prs"][0]
        assert pr["description"] == "Original description."
        # Feedback should have been present during prompt generation
        assert any("Make it shorter" in p for p in captured_prompts)

    def test_reject_no_pending_returns_none(self):
        """reject_spec returns None when no spec is pending."""
        data = _make_data()
        result = spec_gen.reject_spec(data, "pr-abc1234")
        assert result is None

    def test_reject_nonexistent_pr_returns_none(self):
        """reject_spec returns None for unknown PR IDs."""
        data = _make_data()
        result = spec_gen.reject_spec(data, "pr-nonexistent")
        assert result is None
