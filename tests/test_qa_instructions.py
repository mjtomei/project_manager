"""Tests for the QA instruction library."""

import pytest
from pathlib import Path

from pm_core.qa_instructions import (
    _parse_frontmatter,
    _list_dir,
    list_instructions,
    list_regression_tests,
    list_all,
    get_instruction,
    instruction_summary_for_prompt,
    qa_dir,
    instructions_dir,
    regression_dir,
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
        result = list_all(tmp_path)
        assert len(result["instructions"]) == 1
        assert len(result["regression"]) == 1


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
