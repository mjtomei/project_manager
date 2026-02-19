"""Tests for pm_core.review — post-step review logic."""

from pathlib import Path
from unittest.mock import patch, MagicMock

from pm_core.review import (
    _parse_verdict,
    build_fix_prompt,
    _write_review_file,
    list_pending_reviews,
    parse_review_file,
    review_step,
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


# ---------------------------------------------------------------------------
# review_step
# ---------------------------------------------------------------------------

class TestReviewStep:
    @patch("pm_core.review.find_claude", return_value=None)
    def test_returns_early_when_no_claude(self, mock_fc, tmp_path):
        """Line 116-117: returns immediately if claude not found."""
        review_step("plan-add", "ctx", "prompt", tmp_path)
        # No error, just returns

    @patch("pm_core.review.launch_claude_print_background")
    @patch("pm_core.review.find_claude", return_value="/usr/bin/claude")
    def test_launches_background_review(self, mock_fc, mock_launch, tmp_path):
        """Line 169: launches claude in background with callback."""
        review_step("plan-add", "ctx", "check prompt", tmp_path)
        mock_launch.assert_called_once()
        assert mock_launch.call_args[0][0] == "check prompt"
        assert mock_launch.call_args[1]["callback"] is not None

    @patch("pm_core.review.launch_claude_print_background")
    @patch("pm_core.review.find_claude", return_value="/usr/bin/claude")
    def test_callback_pass_not_in_tmux(self, mock_fc, mock_launch, tmp_path):
        """PASS verdict without tmux just returns."""
        review_step("plan-add", "ctx", "check", tmp_path)
        callback = mock_launch.call_args[1]["callback"]
        # Simulate PASS verdict, not in tmux
        with patch("pm_core.review.tmux_mod") as mock_tmux:
            mock_tmux.in_tmux.return_value = False
            callback("PASS — looks good", "", 0)
        # No review file should be written
        assert not (tmp_path / "reviews").exists() or \
               len(list((tmp_path / "reviews").iterdir())) == 0

    @patch("pm_core.review.launch_claude_print_background")
    @patch("pm_core.review.find_claude", return_value="/usr/bin/claude")
    def test_callback_empty_output(self, mock_fc, mock_launch, tmp_path):
        """Empty output should return without action."""
        review_step("plan-add", "ctx", "check", tmp_path)
        callback = mock_launch.call_args[1]["callback"]
        callback("", "", 0)
        # No review file
        assert not (tmp_path / "reviews").exists()

    @patch("pm_core.review.launch_claude_print_background")
    @patch("pm_core.review.find_claude", return_value="/usr/bin/claude")
    def test_callback_needs_fix_not_in_tmux(self, mock_fc, mock_launch, tmp_path, capsys):
        """NEEDS_FIX verdict outside tmux prints to stderr."""
        review_step("plan-add", "ctx", "check", tmp_path)
        callback = mock_launch.call_args[1]["callback"]
        with patch("pm_core.review.tmux_mod") as mock_tmux:
            mock_tmux.in_tmux.return_value = False
            callback("NEEDS_FIX — missing tests", "", 0)
        # Review file should be created
        reviews = list((tmp_path / "reviews").iterdir())
        assert len(reviews) == 1
        assert "NEEDS_FIX" in reviews[0].read_text()
        # Should print to stderr
        captured = capsys.readouterr()
        assert "NEEDS_FIX" in captured.err

    @patch("subprocess.run")
    @patch("pm_core.review.launch_claude_print_background")
    @patch("pm_core.review.find_claude", return_value="/usr/bin/claude")
    def test_callback_needs_fix_in_tmux(self, mock_fc, mock_launch, mock_sp_run, tmp_path):
        """NEEDS_FIX verdict in tmux opens a pane."""
        review_step("plan-add", "ctx", "check", tmp_path)
        callback = mock_launch.call_args[1]["callback"]
        mock_sp_run.return_value = MagicMock(stdout="main-session")
        with patch("pm_core.review.tmux_mod") as mock_tmux:
            mock_tmux.in_tmux.return_value = True
            mock_tmux._tmux_cmd.return_value = ["tmux", "display-message", "-p", "#{session_name}"]
            callback("NEEDS_FIX — missing tests", "", 0)
        mock_tmux.split_pane_background.assert_called_once()

    @patch("subprocess.run")
    @patch("pm_core.review.launch_claude_print_background")
    @patch("pm_core.review.find_claude", return_value="/usr/bin/claude")
    def test_callback_pass_in_tmux(self, mock_fc, mock_launch, mock_sp_run, tmp_path):
        """PASS verdict in tmux opens a pane with PASS message."""
        review_step("plan-add", "ctx", "check", tmp_path)
        callback = mock_launch.call_args[1]["callback"]
        mock_sp_run.return_value = MagicMock(stdout="main-session")
        with patch("pm_core.review.tmux_mod") as mock_tmux:
            mock_tmux.in_tmux.return_value = True
            mock_tmux._tmux_cmd.return_value = ["tmux", "display-message", "-p", "#{session_name}"]
            callback("PASS — all good", "", 0)
        mock_tmux.split_pane_background.assert_called_once()
        pane_cmd = mock_tmux.split_pane_background.call_args[0][2]
        assert "PASS" in pane_cmd

    @patch("pm_core.review.launch_claude_print_background")
    @patch("pm_core.review.find_claude", return_value="/usr/bin/claude")
    def test_callback_needs_fix_tmux_exception_fallback(self, mock_fc, mock_launch, tmp_path, capsys):
        """When tmux fails, falls back to stderr."""
        review_step("plan-add", "ctx", "check", tmp_path)
        callback = mock_launch.call_args[1]["callback"]
        with patch("pm_core.review.tmux_mod") as mock_tmux:
            mock_tmux.in_tmux.return_value = True
            mock_tmux._tmux_cmd.side_effect = Exception("tmux not available")
            callback("NEEDS_FIX — problem", "", 0)
        captured = capsys.readouterr()
        assert "NEEDS_FIX" in captured.err
