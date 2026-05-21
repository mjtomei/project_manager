"""Tests for the QA instruction library."""

import pytest
from pathlib import Path

from pm_core.qa_instructions import (
    _parse_frontmatter,
    _list_dir,
    list_instructions,
    list_regression_tests,
    list_mocks,
    list_artifacts,
    list_all,
    get_instruction,
    get_mock,
    instruction_summary_for_prompt,
    mocks_for_prompt,
    resolve_instruction_ref,
    qa_dir,
    instructions_dir,
    regression_dir,
    mocks_dir,
    artifacts_dir,
)


class TestParseFrontmatter:
    def test_valid_frontmatter(self):
        content = "---\ntitle: My Test\ndescription: A test\n---\nBody here"
        meta, body = _parse_frontmatter(content)
        assert meta["title"] == "My Test"
        assert meta["description"] == "A test"
        assert body == "Body here"

    def test_no_frontmatter(self):
        content = "Just plain text"
        meta, body = _parse_frontmatter(content)
        assert meta == {}
        assert body == "Just plain text"

    def test_no_closing_delimiter(self):
        content = "---\ntitle: Incomplete\nNo closing"
        meta, body = _parse_frontmatter(content)
        assert meta == {}
        assert body == content

    def test_invalid_yaml(self):
        content = "---\n[invalid yaml:\n---\nBody"
        meta, body = _parse_frontmatter(content)
        assert meta == {}
        assert body == "Body"

    def test_non_dict_yaml(self):
        content = "---\n- list item\n---\nBody"
        meta, body = _parse_frontmatter(content)
        assert meta == {}
        assert body == "Body"

    def test_empty_frontmatter(self):
        content = "---\n---\nBody"
        meta, body = _parse_frontmatter(content)
        assert meta == {}
        assert body == "Body"

    def test_frontmatter_with_tags(self):
        content = "---\ntitle: Test\ntags: [ui, pane]\n---\nBody"
        meta, body = _parse_frontmatter(content)
        assert meta["tags"] == ["ui", "pane"]


class TestListDir:
    def test_empty_dir(self, tmp_path):
        assert _list_dir(tmp_path) == []

    def test_nonexistent_dir(self, tmp_path):
        assert _list_dir(tmp_path / "nonexistent") == []

    def test_lists_md_files(self, tmp_path):
        (tmp_path / "test-one.md").write_text(
            "---\ntitle: Test One\ndescription: First test\n---\nBody"
        )
        (tmp_path / "test-two.md").write_text("No frontmatter")
        (tmp_path / "not-md.txt").write_text("Ignored")

        result = _list_dir(tmp_path)
        assert len(result) == 2
        assert result[0]["id"] == "test-one"
        assert result[0]["title"] == "Test One"
        assert result[0]["description"] == "First test"
        # test-two has no frontmatter, title derived from filename
        assert result[1]["id"] == "test-two"
        assert result[1]["title"] == "Test Two"
        assert result[1]["description"] == ""


class TestListInstructionsAndRegression:
    def test_list_instructions(self, tmp_path):
        d = tmp_path / "qa" / "instructions"
        d.mkdir(parents=True)
        (d / "foo.md").write_text("---\ntitle: Foo\n---\nContent")
        result = list_instructions(tmp_path)
        assert len(result) == 1
        assert result[0]["id"] == "foo"

    def test_list_regression(self, tmp_path):
        d = tmp_path / "qa" / "regression"
        d.mkdir(parents=True)
        (d / "bar.md").write_text("---\ntitle: Bar\n---\nContent")
        result = list_regression_tests(tmp_path)
        assert len(result) == 1
        assert result[0]["id"] == "bar"

    def test_list_all(self, tmp_path):
        inst_dir = tmp_path / "qa" / "instructions"
        inst_dir.mkdir(parents=True)
        (inst_dir / "foo.md").write_text("---\ntitle: Foo\n---\n")
        reg_dir = tmp_path / "qa" / "regression"
        reg_dir.mkdir(parents=True)
        (reg_dir / "bar.md").write_text("---\ntitle: Bar\n---\n")
        art_dir = tmp_path / "qa" / "artifacts"
        art_dir.mkdir(parents=True)
        (art_dir / "rec.md").write_text("---\ntitle: Rec\n---\n")
        result = list_all(tmp_path)
        assert len(result["instructions"]) == 1
        assert len(result["regression"]) == 1
        assert len(result["artifacts"]) == 1

    def test_list_artifacts(self, tmp_path):
        d = tmp_path / "qa" / "artifacts"
        d.mkdir(parents=True)
        (d / "rec.md").write_text("---\ntitle: Rec\n---\nbody")
        result = list_artifacts(tmp_path)
        assert len(result) == 1
        assert result[0]["id"] == "rec"

    def test_artifacts_dir_creates_on_access(self, tmp_path):
        d = artifacts_dir(tmp_path)
        assert d.is_dir()
        assert d == tmp_path / "qa" / "artifacts"


class TestGetInstruction:
    def test_found(self, tmp_path):
        d = tmp_path / "qa" / "instructions"
        d.mkdir(parents=True)
        (d / "login.md").write_text(
            "---\ntitle: Login Flow\ndescription: Test login\n---\n## Steps\n1. Go"
        )
        item = get_instruction(tmp_path, "login")
        assert item is not None
        assert item["title"] == "Login Flow"
        assert "## Steps" in item["body"]

    def test_not_found(self, tmp_path):
        (tmp_path / "qa" / "instructions").mkdir(parents=True)
        assert get_instruction(tmp_path, "nonexistent") is None

    def test_regression_category(self, tmp_path):
        d = tmp_path / "qa" / "regression"
        d.mkdir(parents=True)
        (d / "reg-test.md").write_text("---\ntitle: Reg Test\n---\nBody")
        item = get_instruction(tmp_path, "reg-test", category="regression")
        assert item is not None
        assert item["title"] == "Reg Test"

    def test_artifacts_category(self, tmp_path):
        d = tmp_path / "qa" / "artifacts"
        d.mkdir(parents=True)
        (d / "rec.md").write_text("---\ntitle: Rec\n---\nBody")
        item = get_instruction(tmp_path, "rec", category="artifacts")
        assert item is not None
        assert item["title"] == "Rec"


class TestInstructionSummaryForPrompt:
    def test_empty_library(self, tmp_path):
        (tmp_path / "qa" / "instructions").mkdir(parents=True)
        (tmp_path / "qa" / "regression").mkdir(parents=True)
        result = instruction_summary_for_prompt(tmp_path)
        assert "No QA instructions" in result

    def test_with_items(self, tmp_path):
        d = tmp_path / "qa" / "instructions"
        d.mkdir(parents=True)
        (d / "test.md").write_text(
            "---\ntitle: My Test\ndescription: Checks things\n---\n"
        )
        (tmp_path / "qa" / "regression").mkdir(parents=True)
        result = instruction_summary_for_prompt(tmp_path)
        assert "My Test" in result
        assert "Checks things" in result

    def test_artifacts_section_rendered(self, tmp_path):
        inst = tmp_path / "qa" / "instructions"
        inst.mkdir(parents=True)
        (inst / "i.md").write_text("---\ntitle: Inst\n---\n")
        art = tmp_path / "qa" / "artifacts"
        art.mkdir(parents=True)
        (art / "rec.md").write_text(
            "---\ntitle: Recording\ndescription: capture\n---\n")
        result = instruction_summary_for_prompt(tmp_path)
        assert "Artifact Recipes" in result
        assert "Recording" in result


def _setup_library(tmp_path: Path) -> Path:
    """Create a minimal instruction library under tmp_path/qa/."""
    qa_root = tmp_path / "qa"
    instr_dir = qa_root / "instructions"
    instr_dir.mkdir(parents=True)
    (instr_dir / "tui-manual-test.md").write_text("# TUI\n")
    (instr_dir / "login-flow.md").write_text("# Login\n")

    reg_dir = qa_root / "regression"
    reg_dir.mkdir(parents=True)
    (reg_dir / "crash-on-startup.md").write_text("# Crash\n")

    art_dir = qa_root / "artifacts"
    art_dir.mkdir(parents=True)
    (art_dir / "tmux-recording.md").write_text("# Recording\n")
    return tmp_path


class TestResolveInstructionRef:
    def test_exact_filename(self, tmp_path):
        pm = _setup_library(tmp_path)
        assert resolve_instruction_ref(pm, "tui-manual-test.md") == (
            "instructions", "tui-manual-test.md")

    def test_bare_stem(self, tmp_path):
        pm = _setup_library(tmp_path)
        assert resolve_instruction_ref(pm, "tui-manual-test") == (
            "instructions", "tui-manual-test.md")

    def test_with_directory_prefix(self, tmp_path):
        pm = _setup_library(tmp_path)
        result = resolve_instruction_ref(pm, "instructions/tui-manual-test.md")
        assert result == ("instructions", "tui-manual-test.md")

    def test_regression_category(self, tmp_path):
        pm = _setup_library(tmp_path)
        assert resolve_instruction_ref(pm, "crash-on-startup.md") == (
            "regression", "crash-on-startup.md")

    def test_case_insensitive(self, tmp_path):
        pm = _setup_library(tmp_path)
        assert resolve_instruction_ref(pm, "TUI-MANUAL-TEST.MD") == (
            "instructions", "tui-manual-test.md")

    def test_fuzzy_match(self, tmp_path):
        pm = _setup_library(tmp_path)
        result = resolve_instruction_ref(pm, "tui-manual-tst.md")
        assert result is not None
        assert result[1] == "tui-manual-test.md"

    def test_no_match(self, tmp_path):
        pm = _setup_library(tmp_path)
        assert resolve_instruction_ref(pm, "nonexistent-file.md") is None

    def test_artifacts_category(self, tmp_path):
        pm = _setup_library(tmp_path)
        assert resolve_instruction_ref(pm, "tmux-recording.md") == (
            "artifacts", "tmux-recording.md")

    def test_strips_quotes(self, tmp_path):
        pm = _setup_library(tmp_path)
        assert resolve_instruction_ref(pm, '"tui-manual-test.md"') == (
            "instructions", "tui-manual-test.md")

    def test_absolute_path(self, tmp_path):
        pm = _setup_library(tmp_path)
        result = resolve_instruction_ref(
            pm, "/home/user/pm/qa/instructions/login-flow.md")
        assert result == ("instructions", "login-flow.md")


# ---------------------------------------------------------------------------
# Mocks library
# ---------------------------------------------------------------------------

def _write_mock(pm_root: Path, mock_id: str, title: str,
                description: str = "", body: str = "") -> None:
    d = mocks_dir(pm_root)
    content = f"---\ntitle: {title}\ndescription: {description}\ntags: []\n---\n{body}"
    (d / f"{mock_id}.md").write_text(content)


class TestListMocks:
    def test_empty_directory(self, tmp_path):
        pm = tmp_path / "pm"
        pm.mkdir()
        assert list_mocks(pm) == []

    def test_lists_mock_files(self, tmp_path):
        pm = tmp_path / "pm"
        pm.mkdir()
        _write_mock(pm, "claude-session", "Claude Session Mock", "Mocks the Claude API")
        _write_mock(pm, "git-ops", "Git Ops Mock", "Mocks git operations")
        mocks = list_mocks(pm)
        assert len(mocks) == 2
        ids = {m["id"] for m in mocks}
        assert ids == {"claude-session", "git-ops"}

    def test_list_all_includes_mocks(self, tmp_path):
        pm = tmp_path / "pm"
        pm.mkdir()
        _write_mock(pm, "tmux-mock", "Tmux Mock")
        all_items = list_all(pm)
        assert "mocks" in all_items
        assert len(all_items["mocks"]) == 1


class TestGetMock:
    def test_returns_none_for_missing(self, tmp_path):
        pm = tmp_path / "pm"
        pm.mkdir()
        assert get_mock(pm, "nonexistent") is None

    def test_returns_mock_with_body(self, tmp_path):
        pm = tmp_path / "pm"
        pm.mkdir()
        _write_mock(pm, "claude-session", "Claude Session Mock",
                    "Mocks the Claude API",
                    "## Contract\nSimulates Claude sessions.\n")
        mock = get_mock(pm, "claude-session")
        assert mock is not None
        assert mock["id"] == "claude-session"
        assert mock["title"] == "Claude Session Mock"
        assert mock["description"] == "Mocks the Claude API"
        assert "Contract" in mock["body"]
        assert mock["path"].endswith("claude-session.md")


class TestMocksForPrompt:
    def test_empty_library_returns_empty_string(self, tmp_path):
        pm = tmp_path / "pm"
        pm.mkdir()
        assert mocks_for_prompt(pm) == ""

    def test_includes_all_mocks(self, tmp_path):
        pm = tmp_path / "pm"
        pm.mkdir()
        _write_mock(pm, "claude-session", "Claude Session Mock",
                    body="## Contract\nFakeClaudeSession\n")
        _write_mock(pm, "git-ops", "Git Ops Mock",
                    body="## Contract\nFakeGitOps\n")
        result = mocks_for_prompt(pm)
        assert "Claude Session Mock" in result
        assert "Git Ops Mock" in result
        assert "FakeClaudeSession" in result
        assert "FakeGitOps" in result

    def test_prompt_block_has_mocks_heading(self, tmp_path):
        pm = tmp_path / "pm"
        pm.mkdir()
        _write_mock(pm, "tmux-mock", "Tmux Mock", body="## Contract\nFakeTmux\n")
        result = mocks_for_prompt(pm)
        assert result.startswith("## Mocks")
        assert "do not devise your own" in result

    def test_description_included_when_present(self, tmp_path):
        pm = tmp_path / "pm"
        pm.mkdir()
        _write_mock(pm, "tmux-mock", "Tmux Mock", description="Simulates tmux panes")
        result = mocks_for_prompt(pm)
        assert "Simulates tmux panes" in result
