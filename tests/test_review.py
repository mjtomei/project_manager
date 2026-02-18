"""Tests for pm_core.review — post-step review logic."""

from pathlib import Path

from pm_core.review import (
    _parse_verdict,
    build_fix_prompt,
    _write_review_file,
    list_pending_reviews,
    parse_review_file,
    REVIEW_PROMPTS,
)


# ---------------------------------------------------------------------------
# _parse_verdict
# ---------------------------------------------------------------------------

class TestParseVerdict:
    def test_pass_at_start(self):
        assert _parse_verdict("PASS — looks good") == "PASS"

    def test_needs_fix_at_start(self):
        assert _parse_verdict("NEEDS_FIX — missing section") == "NEEDS_FIX"

    def test_pass_after_preamble(self):
        text = "Here is my analysis:\nPASS\nAll good."
        assert _parse_verdict(text) == "PASS"

    def test_needs_fix_after_preamble(self):
        text = "Reviewing...\nNEEDS_FIX\nMissing tests."
        assert _parse_verdict(text) == "NEEDS_FIX"

    def test_empty_output_is_pass(self):
        assert _parse_verdict("") == "PASS"

    def test_whitespace_only_is_pass(self):
        assert _parse_verdict("   \n  \n") == "PASS"

    def test_no_verdict_defaults_to_needs_fix(self):
        assert _parse_verdict("Some random output without a verdict") == "NEEDS_FIX"

    def test_pass_with_leading_whitespace(self):
        assert _parse_verdict("  PASS: everything ok") == "PASS"


# ---------------------------------------------------------------------------
# build_fix_prompt
# ---------------------------------------------------------------------------

class TestBuildFixPrompt:
    def test_contains_step_name(self):
        result = build_fix_prompt("plan-add", "ctx", "findings")
        assert "plan-add" in result

    def test_contains_original_context(self):
        result = build_fix_prompt("s", "my original context", "f")
        assert "my original context" in result

    def test_contains_findings(self):
        result = build_fix_prompt("s", "c", "missing tests section")
        assert "missing tests section" in result

    def test_format_structure(self):
        result = build_fix_prompt("plan-deps", "ctx", "findings")
        assert "Original context:" in result
        assert "Issues found:" in result
        assert 'Fixing issues from the "plan-deps" review.' in result


# ---------------------------------------------------------------------------
# _write_review_file
# ---------------------------------------------------------------------------

class TestWriteReviewFile:
    def test_creates_file(self, tmp_path):
        path = _write_review_file(tmp_path, "plan-add", "NEEDS_FIX", "bad stuff")
        assert path.exists()
        content = path.read_text()
        assert "Step: plan-add" in content
        assert "Status: NEEDS_FIX" in content
        assert "bad stuff" in content

    def test_file_in_reviews_dir(self, tmp_path):
        path = _write_review_file(tmp_path, "test-step", "PASS", "all good")
        assert path.parent.name == "reviews"
        assert path.parent.parent == tmp_path

    def test_slug_replaces_spaces(self, tmp_path):
        path = _write_review_file(tmp_path, "plan add step", "PASS", "ok")
        assert "plan-add-step" in path.name

    def test_contains_fix_command(self, tmp_path):
        path = _write_review_file(tmp_path, "plan-add", "NEEDS_FIX", "issues")
        content = path.read_text()
        assert "pm plan fix --review" in content


# ---------------------------------------------------------------------------
# list_pending_reviews
# ---------------------------------------------------------------------------

class TestListPendingReviews:
    def test_no_reviews_dir(self, tmp_path):
        assert list_pending_reviews(tmp_path) == []

    def test_empty_reviews_dir(self, tmp_path):
        (tmp_path / "reviews").mkdir()
        assert list_pending_reviews(tmp_path) == []

    def test_finds_needs_fix(self, tmp_path):
        _write_review_file(tmp_path, "step1", "NEEDS_FIX", "problem")
        result = list_pending_reviews(tmp_path)
        assert len(result) == 1
        assert "step1" in result[0]["filename"]

    def test_ignores_pass(self, tmp_path):
        _write_review_file(tmp_path, "step1", "PASS", "ok")
        assert list_pending_reviews(tmp_path) == []

    def test_multiple_reviews(self, tmp_path):
        _write_review_file(tmp_path, "step1", "NEEDS_FIX", "problem 1")
        _write_review_file(tmp_path, "step2", "NEEDS_FIX", "problem 2")
        _write_review_file(tmp_path, "step3", "PASS", "ok")
        result = list_pending_reviews(tmp_path)
        assert len(result) == 2

    def test_ignores_non_txt(self, tmp_path):
        reviews = tmp_path / "reviews"
        reviews.mkdir()
        (reviews / "notes.md").write_text("Status: NEEDS_FIX\nstuff")
        assert list_pending_reviews(tmp_path) == []


# ---------------------------------------------------------------------------
# parse_review_file
# ---------------------------------------------------------------------------

class TestParseReviewFile:
    def test_parses_full_file(self, tmp_path):
        path = _write_review_file(tmp_path, "plan-add", "NEEDS_FIX", "missing tests")
        result = parse_review_file(path)
        assert result["step"] == "plan-add"
        assert result["status"] == "NEEDS_FIX"
        assert "missing tests" in result["findings"]
        assert "pm plan fix" in result["fix_cmd"]
        assert result["raw"] == path.read_text()

    def test_parses_pass_file(self, tmp_path):
        path = _write_review_file(tmp_path, "plan-deps", "PASS", "all good")
        result = parse_review_file(path)
        assert result["step"] == "plan-deps"
        assert result["status"] == "PASS"

    def test_minimal_file(self, tmp_path):
        f = tmp_path / "minimal.txt"
        f.write_text("Step: test\nStatus: PASS\n")
        result = parse_review_file(f)
        assert result["step"] == "test"
        assert result["status"] == "PASS"
        assert result["findings"] == ""
        assert result["fix_cmd"] == ""


# ---------------------------------------------------------------------------
# REVIEW_PROMPTS
# ---------------------------------------------------------------------------

class TestReviewPrompts:
    def test_all_keys_present(self):
        expected_keys = {"plan-add", "plan-breakdown", "plan-deps",
                         "plan-load", "plan-import", "plan-review"}
        assert set(REVIEW_PROMPTS.keys()) == expected_keys

    def test_all_values_are_strings(self):
        for key, val in REVIEW_PROMPTS.items():
            assert isinstance(val, str), f"REVIEW_PROMPTS[{key!r}] is not a string"
