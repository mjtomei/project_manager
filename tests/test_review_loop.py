"""Tests for pm_core.review_loop and pm_core.prompt_gen review loop prompt."""

import threading
from unittest.mock import patch, MagicMock

import pytest

from pm_core.review_loop import (
    parse_review_verdict,
    should_stop,
    run_review_loop_sync,
    start_review_loop_background,
    ReviewLoopState,
    ReviewIteration,
    VERDICT_PASS,
    VERDICT_PASS_WITH_SUGGESTIONS,
    VERDICT_NEEDS_WORK,
)


# --- parse_review_verdict tests ---

class TestParseReviewVerdict:
    def test_pass(self):
        assert parse_review_verdict("Everything looks good.\n\n**PASS**") == VERDICT_PASS

    def test_pass_plain(self):
        assert parse_review_verdict("PASS") == VERDICT_PASS

    def test_pass_with_suggestions(self):
        output = "Minor style issues.\n\n**PASS_WITH_SUGGESTIONS**\n\n- Consider renaming foo"
        assert parse_review_verdict(output) == VERDICT_PASS_WITH_SUGGESTIONS

    def test_pass_with_suggestions_bold(self):
        assert parse_review_verdict("**PASS_WITH_SUGGESTIONS**") == VERDICT_PASS_WITH_SUGGESTIONS

    def test_needs_work(self):
        output = "Found bugs.\n\n**NEEDS_WORK**\n\n- Fix the null check"
        assert parse_review_verdict(output) == VERDICT_NEEDS_WORK

    def test_needs_work_plain(self):
        assert parse_review_verdict("NEEDS_WORK") == VERDICT_NEEDS_WORK

    def test_empty_output_is_pass(self):
        assert parse_review_verdict("") == VERDICT_PASS

    def test_no_verdict_defaults_to_needs_work(self):
        assert parse_review_verdict("This code has issues but no clear verdict") == VERDICT_NEEDS_WORK

    def test_pass_not_confused_with_suggestions(self):
        """A line with just PASS should not match PASS_WITH_SUGGESTIONS."""
        output = "All good.\n\nPASS"
        assert parse_review_verdict(output) == VERDICT_PASS

    def test_verdict_at_end_wins(self):
        """The verdict scanner works from the bottom."""
        output = "Initial: NEEDS_WORK\n\nAfter fixes: PASS"
        assert parse_review_verdict(output) == VERDICT_PASS

    def test_verdict_with_bold_markers(self):
        assert parse_review_verdict("Overall: **NEEDS_WORK**") == VERDICT_NEEDS_WORK


# --- should_stop tests ---

class TestShouldStop:
    def test_pass_always_stops(self):
        assert should_stop(VERDICT_PASS) is True
        assert should_stop(VERDICT_PASS, stop_on_suggestions=False) is True

    def test_suggestions_stops_by_default(self):
        assert should_stop(VERDICT_PASS_WITH_SUGGESTIONS) is True

    def test_suggestions_continues_when_configured(self):
        assert should_stop(VERDICT_PASS_WITH_SUGGESTIONS, stop_on_suggestions=False) is False

    def test_needs_work_never_stops(self):
        assert should_stop(VERDICT_NEEDS_WORK) is False
        assert should_stop(VERDICT_NEEDS_WORK, stop_on_suggestions=False) is False


# --- ReviewLoopState tests ---

class TestReviewLoopState:
    def test_defaults(self):
        state = ReviewLoopState(pr_id="pr-001")
        assert state.pr_id == "pr-001"
        assert state.running is False
        assert state.stop_requested is False
        assert state.iteration == 0
        assert state.latest_verdict == ""
        assert state.history == []
        assert state.stop_on_suggestions is True

    def test_strict_mode(self):
        state = ReviewLoopState(pr_id="pr-001", stop_on_suggestions=False)
        assert state.stop_on_suggestions is False


# --- run_review_loop_sync tests ---

class TestRunReviewLoopSync:
    @patch("pm_core.review_loop._run_claude_review")
    def test_stops_on_pass(self, mock_review):
        mock_review.return_value = "All good.\n\n**PASS**"
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync("prompt", "/tmp", state)
        assert result.iteration == 1
        assert result.latest_verdict == VERDICT_PASS
        assert result.running is False
        assert len(result.history) == 1
        mock_review.assert_called_once()

    @patch("pm_core.review_loop._run_claude_review")
    def test_stops_on_suggestions_by_default(self, mock_review):
        mock_review.return_value = "Minor nits.\n\n**PASS_WITH_SUGGESTIONS**"
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync("prompt", "/tmp", state)
        assert result.iteration == 1
        assert result.latest_verdict == VERDICT_PASS_WITH_SUGGESTIONS
        assert result.running is False

    @patch("pm_core.review_loop._run_claude_review")
    def test_continues_past_suggestions_when_configured(self, mock_review):
        mock_review.side_effect = [
            "Minor nits.\n\n**PASS_WITH_SUGGESTIONS**",
            "All good.\n\n**PASS**",
        ]
        state = ReviewLoopState(pr_id="pr-001", stop_on_suggestions=False)
        result = run_review_loop_sync("prompt", "/tmp", state)
        assert result.iteration == 2
        assert result.latest_verdict == VERDICT_PASS
        assert len(result.history) == 2

    @patch("pm_core.review_loop._run_claude_review")
    def test_loops_on_needs_work(self, mock_review):
        mock_review.side_effect = [
            "Bugs found.\n\n**NEEDS_WORK**",
            "Still issues.\n\n**NEEDS_WORK**",
            "All good.\n\n**PASS**",
        ]
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync("prompt", "/tmp", state)
        assert result.iteration == 3
        assert result.latest_verdict == VERDICT_PASS
        assert len(result.history) == 3

    @patch("pm_core.review_loop._run_claude_review")
    def test_respects_max_iterations(self, mock_review):
        mock_review.return_value = "**NEEDS_WORK**"
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync("prompt", "/tmp", state, max_iterations=3)
        assert result.iteration == 3
        assert result.latest_verdict == VERDICT_NEEDS_WORK
        assert mock_review.call_count == 3

    @patch("pm_core.review_loop._run_claude_review")
    def test_stop_requested(self, mock_review):
        def side_effect(*args, **kwargs):
            # Simulate user requesting stop after first iteration
            state.stop_requested = True
            return "**NEEDS_WORK**"

        mock_review.side_effect = side_effect
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync("prompt", "/tmp", state)
        assert result.iteration == 1
        assert result.running is False

    @patch("pm_core.review_loop._run_claude_review")
    def test_calls_on_iteration_callback(self, mock_review):
        mock_review.return_value = "**PASS**"
        callback = MagicMock()
        state = ReviewLoopState(pr_id="pr-001")
        run_review_loop_sync("prompt", "/tmp", state, on_iteration=callback)
        callback.assert_called_once_with(state)

    @patch("pm_core.review_loop._run_claude_review")
    def test_handles_timeout(self, mock_review):
        import subprocess
        mock_review.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=600)
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync("prompt", "/tmp", state)
        assert result.latest_verdict == "TIMEOUT"
        assert result.running is False

    @patch("pm_core.review_loop._run_claude_review")
    def test_handles_exception(self, mock_review):
        mock_review.side_effect = RuntimeError("claude crashed")
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync("prompt", "/tmp", state)
        assert result.latest_verdict == "ERROR"
        assert result.running is False


class TestStartReviewLoopBackground:
    @patch("pm_core.review_loop._run_claude_review")
    def test_runs_in_background_thread(self, mock_review):
        mock_review.return_value = "**PASS**"
        state = ReviewLoopState(pr_id="pr-001")
        complete_callback = MagicMock()
        thread = start_review_loop_background(
            "prompt", "/tmp", state,
            on_complete=complete_callback,
        )
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert state.latest_verdict == VERDICT_PASS
        assert state.running is False
        complete_callback.assert_called_once_with(state)


# --- generate_review_loop_prompt tests ---

class TestGenerateReviewLoopPrompt:
    def _make_data(self):
        return {
            "project": {"name": "test", "repo": "test/repo", "base_branch": "main"},
            "prs": [
                {
                    "id": "pr-001",
                    "title": "Add feature",
                    "description": "Implement the feature",
                    "branch": "pm/pr-001-add-feature",
                    "status": "in_progress",
                },
            ],
        }

    def test_includes_review_loop_mode_section(self):
        from pm_core.prompt_gen import generate_review_loop_prompt
        data = self._make_data()
        prompt = generate_review_loop_prompt(data, "pr-001")
        assert "## Review Loop Mode" in prompt

    def test_includes_fix_commit_push_instructions(self):
        from pm_core.prompt_gen import generate_review_loop_prompt
        data = self._make_data()
        prompt = generate_review_loop_prompt(data, "pr-001")
        assert "Implement ALL the fixes" in prompt
        assert "git push" in prompt
        assert "commit" in prompt.lower()

    def test_includes_branch_in_push_command(self):
        from pm_core.prompt_gen import generate_review_loop_prompt
        data = self._make_data()
        prompt = generate_review_loop_prompt(data, "pr-001")
        assert "pm/pr-001-add-feature" in prompt

    def test_includes_all_three_verdicts(self):
        from pm_core.prompt_gen import generate_review_loop_prompt
        data = self._make_data()
        prompt = generate_review_loop_prompt(data, "pr-001")
        assert "PASS" in prompt
        assert "PASS_WITH_SUGGESTIONS" in prompt
        assert "NEEDS_WORK" in prompt

    def test_includes_base_review_content(self):
        from pm_core.prompt_gen import generate_review_loop_prompt
        data = self._make_data()
        prompt = generate_review_loop_prompt(data, "pr-001")
        # Should contain the base review prompt content
        assert "reviewing pr pr-001" in prompt.lower()
        assert "git diff" in prompt


# --- Multiple concurrent loops (state isolation) ---

class TestMultipleLoops:
    @patch("pm_core.review_loop._run_claude_review")
    def test_independent_states(self, mock_review):
        """Two loops for different PRs track state independently."""
        mock_review.return_value = "**PASS**"
        state_a = ReviewLoopState(pr_id="pr-001")
        state_b = ReviewLoopState(pr_id="pr-002", stop_on_suggestions=False)

        run_review_loop_sync("prompt-a", "/tmp/a", state_a)
        run_review_loop_sync("prompt-b", "/tmp/b", state_b)

        assert state_a.pr_id == "pr-001"
        assert state_b.pr_id == "pr-002"
        assert state_a.iteration == 1
        assert state_b.iteration == 1
        assert state_a.stop_on_suggestions is True
        assert state_b.stop_on_suggestions is False
