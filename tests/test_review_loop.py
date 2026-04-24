"""Tests for pm_core.review_loop and pm_core.prompt_gen review loop prompt."""

from unittest.mock import patch, MagicMock

import pytest

from pm_core.review_loop import (
    parse_review_verdict,
    should_stop,
    run_review_loop_sync,
    start_review_loop_background,
    PaneKilledError,
    ReviewLoopState,
    ReviewIteration,
    _match_verdict,
    VERDICT_PASS,
    VERDICT_PASS_WITH_SUGGESTIONS,
    VERDICT_NEEDS_WORK,
    VERDICT_INPUT_REQUIRED,
    VERDICT_KILLED,
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

    def test_verdict_on_own_line_wins(self):
        """Only a keyword on its own line is detected."""
        output = "Initial: NEEDS_WORK\n\nPASS"
        assert parse_review_verdict(output) == VERDICT_PASS

    def test_verdict_with_bold_on_own_line(self):
        assert parse_review_verdict("Some text\n**NEEDS_WORK**") == VERDICT_NEEDS_WORK

    def test_inline_verdict_not_matched(self):
        """Verdict keywords in the middle of a sentence are ignored."""
        assert parse_review_verdict("Overall: **NEEDS_WORK**") == VERDICT_NEEDS_WORK  # fallback
        assert parse_review_verdict("Verdict: [PASS]") == VERDICT_NEEDS_WORK  # fallback

    def test_pass_fail_not_matched(self):
        """[PASS/FAIL] in diff output should not match as PASS verdict."""
        output = "2469 -OVERALL: [PASS/FAIL]\nsome other line"
        assert parse_review_verdict(output) == VERDICT_NEEDS_WORK

    def test_password_not_matched(self):
        """Words containing PASS like PASSWORD should not match."""
        output = "Check PASSWORD config\nNo verdict here"
        assert parse_review_verdict(output) == VERDICT_NEEDS_WORK

    def test_input_required(self):
        output = "Need human testing.\n\n**INPUT_REQUIRED**\n\n1. Test the TUI"
        assert parse_review_verdict(output) == VERDICT_INPUT_REQUIRED

    def test_input_required_plain(self):
        assert parse_review_verdict("INPUT_REQUIRED") == VERDICT_INPUT_REQUIRED

    def test_input_required_bold(self):
        assert parse_review_verdict("**INPUT_REQUIRED**") == VERDICT_INPUT_REQUIRED


# --- _match_verdict false positive rejection tests ---

class TestMatchVerdictFalsePositives:
    """Verify that _match_verdict only accepts the keyword on a line by itself."""

    def test_pr_title_with_input_required(self):
        assert _match_verdict("Add INPUT_REQUIRED verdict to review loop for human-guided testing") is None

    def test_pr_title_with_pass(self):
        assert _match_verdict("Add PASS verdict handling to the review loop") is None

    def test_pr_title_with_needs_work(self):
        assert _match_verdict("Fix NEEDS_WORK detection in review loop verdict parser") is None

    def test_pr_title_with_pass_with_suggestions(self):
        assert _match_verdict("Handle PASS_WITH_SUGGESTIONS in auto-merge logic") is None

    def test_pm_pr_list_table_row(self):
        assert _match_verdict("| pr-473ac84 | Add INPUT_REQUIRED verdict to review loop | merged |") is None

    def test_descriptive_sentence(self):
        assert _match_verdict("The PASS verdict means the code is ready to merge") is None
        assert _match_verdict("When NEEDS_WORK is returned, the loop continues with fixes") is None

    def test_standalone_verdicts_match(self):
        """Bare keyword on a line by itself."""
        assert _match_verdict("PASS") == VERDICT_PASS
        assert _match_verdict("NEEDS_WORK") == VERDICT_NEEDS_WORK
        assert _match_verdict("PASS_WITH_SUGGESTIONS") == VERDICT_PASS_WITH_SUGGESTIONS
        assert _match_verdict("INPUT_REQUIRED") == VERDICT_INPUT_REQUIRED

    def test_bold_verdicts_match(self):
        """Keyword wrapped in markdown bold."""
        assert _match_verdict("**PASS**") == VERDICT_PASS
        assert _match_verdict("**NEEDS_WORK**") == VERDICT_NEEDS_WORK
        assert _match_verdict("**INPUT_REQUIRED**") == VERDICT_INPUT_REQUIRED
        assert _match_verdict("**PASS_WITH_SUGGESTIONS**") == VERDICT_PASS_WITH_SUGGESTIONS

    def test_whitespace_around_keyword(self):
        """Leading/trailing whitespace should be stripped."""
        assert _match_verdict("  PASS  ") == VERDICT_PASS
        assert _match_verdict("  **NEEDS_WORK**  ") == VERDICT_NEEDS_WORK

    def test_any_extra_text_rejected(self):
        """Any text beyond the keyword itself is rejected."""
        assert _match_verdict("Verdict: PASS") is None
        assert _match_verdict("Final verdict: NEEDS_WORK") is None
        assert _match_verdict("My verdict: **PASS**") is None
        assert _match_verdict("Result: NEEDS_WORK.") is None
        assert _match_verdict("PASS (ok)") is None

    def test_tmux_wrapped_fragments_rejected(self):
        """Fragments from tmux line-wrapping are rejected."""
        assert _match_verdict("NEEDS_WORK)") is None
        assert _match_verdict("PASS)") is None
        assert _match_verdict("INPUT_REQUIRED)") is None
        assert _match_verdict("(PASS,") is None
        assert _match_verdict("NEEDS_WORK,") is None

    def test_prompt_instruction_line_rejected(self):
        line = "IMPORTANT: Always end your response with the verdict keyword on its own line — one of **PASS**, **PA"
        assert _match_verdict(line) is None


# --- prompt verdict filtering tests ---

def _get_real_prompt() -> str:
    """Generate the actual review prompt from prompt_gen, so tests adapt to prompt changes."""
    from pm_core.prompt_gen import generate_review_prompt
    data = {
        "project": {"name": "test", "repo": "test/repo", "base_branch": "master"},
        "prs": [{
            "id": "pr-001",
            "title": "Add feature",
            "description": "Implement the feature",
            "branch": "pm/pr-001-add-feature",
            "status": "in_progress",
        }],
    }
    return generate_review_prompt(data, "pr-001", review_loop=True,
                                  review_iteration=1, review_loop_id="ab12")


from tests.conftest import simulate_terminal_wrap as _simulate_terminal_wrap



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

    def test_input_required_never_stops(self):
        assert should_stop(VERDICT_INPUT_REQUIRED) is False
        assert should_stop(VERDICT_INPUT_REQUIRED, stop_on_suggestions=False) is False


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
        # loop_id is auto-generated
        assert len(state.loop_id) == 4  # 2 bytes = 4 hex chars

    def test_strict_mode(self):
        state = ReviewLoopState(pr_id="pr-001", stop_on_suggestions=False)
        assert state.stop_on_suggestions is False

    def test_unique_loop_ids(self):
        """Each state gets a unique loop_id."""
        ids = {ReviewLoopState(pr_id="pr-001").loop_id for _ in range(10)}
        # With 4 hex chars (65536 values), 10 should all be unique
        assert len(ids) == 10

    def test_input_required_defaults(self):
        state = ReviewLoopState(pr_id="pr-001")
        assert state.input_required is False


# --- Helper data for tests ---

_PR_DATA = {
    "id": "pr-001",
    "title": "Add feature",
    "branch": "pm/pr-001-add-feature",
    "status": "in_progress",
    "workdir": "/tmp/workdir",
}


# --- run_review_loop_sync tests ---

class TestRunReviewLoopSync:
    @patch("pm_core.review_loop._run_claude_review")
    def test_stops_on_pass(self, mock_review):
        mock_review.return_value = "All good.\n\n**PASS**"
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
        assert result.iteration == 1
        assert result.latest_verdict == VERDICT_PASS
        assert result.running is False
        assert len(result.history) == 1
        mock_review.assert_called_once()

    @patch("pm_core.review_loop._run_claude_review")
    def test_passes_iteration_and_loop_id(self, mock_review):
        """Iteration number and loop_id are forwarded to _run_claude_review."""
        mock_review.side_effect = [
            "Bugs.\n\n**NEEDS_WORK**",
            "All good.\n\n**PASS**",
        ]
        state = ReviewLoopState(pr_id="pr-001")
        run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
        # First call: iteration=1, second call: iteration=2
        calls = mock_review.call_args_list
        assert calls[0].kwargs["iteration"] == 1
        assert calls[0].kwargs["loop_id"] == state.loop_id
        assert calls[1].kwargs["iteration"] == 2
        assert calls[1].kwargs["loop_id"] == state.loop_id

    @patch("pm_core.review_loop._run_claude_review")
    def test_stops_on_suggestions_by_default(self, mock_review):
        mock_review.return_value = "Minor nits.\n\n**PASS_WITH_SUGGESTIONS**"
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
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
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
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
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
        assert result.iteration == 3
        assert result.latest_verdict == VERDICT_PASS
        assert len(result.history) == 3

    @patch("pm_core.review_loop._run_claude_review")
    def test_respects_max_iterations(self, mock_review):
        mock_review.return_value = "**NEEDS_WORK**"
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp", max_iterations=3)
        assert result.iteration == 3
        assert result.latest_verdict == VERDICT_NEEDS_WORK
        assert mock_review.call_count == 3

    @patch("pm_core.review_loop._run_claude_review")
    def test_stop_requested_after_iteration(self, mock_review):
        def side_effect(*args, **kwargs):
            # Simulate user requesting stop — _run_claude_review returns
            # a normal verdict, but stop_requested is checked after.
            state.stop_requested = True
            return "**NEEDS_WORK**"

        mock_review.side_effect = side_effect
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
        assert result.iteration == 1
        assert result.running is False

    @patch("pm_core.review_loop._run_claude_review")
    def test_stop_requested_completes_current_iteration(self, mock_review):
        """When stop is requested mid-iteration, the iteration still finishes
        and the verdict is recorded before the loop stops."""
        def side_effect(*args, **kwargs):
            state.stop_requested = True
            return "**NEEDS_WORK**"  # iteration completes normally

        mock_review.side_effect = side_effect
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
        assert result.iteration == 1
        assert result.running is False
        # Iteration completed and verdict was recorded
        assert len(result.history) == 1
        assert result.latest_verdict == VERDICT_NEEDS_WORK

    @patch("pm_core.review_loop._run_claude_review")
    def test_calls_on_iteration_callback(self, mock_review):
        mock_review.return_value = "**PASS**"
        callback = MagicMock()
        state = ReviewLoopState(pr_id="pr-001")
        run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp", on_iteration=callback)
        callback.assert_called_once_with(state)

    @patch("pm_core.review_loop._run_claude_review")
    def test_handles_exception(self, mock_review):
        mock_review.side_effect = RuntimeError("setup failure")
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
        assert result.latest_verdict == "ERROR"
        assert result.running is False

    @patch("pm_core.review_loop._run_claude_review")
    def test_pane_killed_stops_loop(self, mock_review):
        """When the pane is killed externally, loop stops with KILLED verdict."""
        mock_review.side_effect = PaneKilledError("pane disappeared")
        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")
        assert result.latest_verdict == VERDICT_KILLED
        assert result.running is False
        assert result.iteration == 1
        mock_review.assert_called_once()


class TestStartReviewLoopBackground:
    @patch("pm_core.review_loop._run_claude_review")
    def test_runs_in_background_thread(self, mock_review):
        mock_review.return_value = "**PASS**"
        state = ReviewLoopState(pr_id="pr-001")
        complete_callback = MagicMock()
        thread = start_review_loop_background(
            state, "/tmp", _PR_DATA, transcript_dir="/tmp",
            on_complete=complete_callback,
        )
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert state.latest_verdict == VERDICT_PASS
        assert state.running is False
        complete_callback.assert_called_once_with(state)


# --- generate_review_prompt with review_loop tests ---

class TestGenerateReviewPrompt:
    def _make_data(self):
        return {
            "project": {"name": "test", "repo": "test/repo", "base_branch": "master"},
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
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001", review_loop=True)
        assert "## Review Loop Mode" in prompt

    def test_no_review_loop_mode_by_default(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001")
        assert "## Review Loop Mode" not in prompt

    def test_includes_fix_commit_push_instructions(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001", review_loop=True)
        assert "Implement ALL the fixes" in prompt
        assert "git push" in prompt
        assert "commit" in prompt.lower()

    def test_includes_branch_in_push_command(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001", review_loop=True)
        assert "pm/pr-001-add-feature" in prompt

    def test_includes_all_three_verdicts(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001", review_loop=True)
        assert "PASS" in prompt
        assert "PASS_WITH_SUGGESTIONS" in prompt
        assert "NEEDS_WORK" in prompt

    def test_includes_base_review_content(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001", review_loop=True)
        # Should contain the base review prompt content
        assert "reviewing pr pr-001" in prompt.lower()
        assert "git diff" in prompt

    def test_includes_iteration_in_commit_prefix(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001", review_loop=True,
                                         review_iteration=3)
        assert "review-loop i3:" in prompt
        assert "(iteration 3)" in prompt

    def test_includes_loop_id_in_commit_prefix(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001", review_loop=True,
                                         review_iteration=2, review_loop_id="ab12")
        assert "review-loop ab12 i2:" in prompt
        assert "[ab12]" in prompt

    def test_loop_id_without_iteration(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001", review_loop=True,
                                         review_loop_id="ff00")
        assert "review-loop ff00:" in prompt

    def test_backward_compat_wrapper(self):
        """generate_review_loop_prompt still works as a wrapper."""
        from pm_core.prompt_gen import generate_review_loop_prompt, generate_review_prompt
        data = self._make_data()
        wrapper_result = generate_review_loop_prompt(data, "pr-001")
        direct_result = generate_review_prompt(data, "pr-001", review_loop=True)
        assert wrapper_result == direct_result


# --- Multiple concurrent loops (state isolation) ---

class TestMultipleLoops:
    @patch("pm_core.review_loop._run_claude_review")
    def test_independent_states(self, mock_review):
        """Two loops for different PRs track state independently."""
        mock_review.return_value = "**PASS**"
        state_a = ReviewLoopState(pr_id="pr-001")
        state_b = ReviewLoopState(pr_id="pr-002", stop_on_suggestions=False)

        pr_data_a = {"id": "pr-001", "branch": "pm/pr-001"}
        pr_data_b = {"id": "pr-002", "branch": "pm/pr-002"}

        run_review_loop_sync(state_a, "/tmp/a", pr_data_a, transcript_dir="/tmp/a")
        run_review_loop_sync(state_b, "/tmp/b", pr_data_b, transcript_dir="/tmp/b")

        assert state_a.pr_id == "pr-001"
        assert state_b.pr_id == "pr-002"
        assert state_a.iteration == 1
        assert state_b.iteration == 1
        assert state_a.stop_on_suggestions is True
        assert state_b.stop_on_suggestions is False
        # Each loop has a unique ID
        assert state_a.loop_id != state_b.loop_id


# --- INPUT_REQUIRED verdict tests ---

class TestInputRequired:
    @patch("pm_core.review_loop._wait_for_follow_up_verdict")
    @patch("pm_core.review_loop._run_claude_review")
    def test_input_required_polls_for_follow_up(self, mock_review, mock_follow_up):
        """Loop polls existing pane for follow-up verdict after INPUT_REQUIRED."""
        mock_review.return_value = "Need testing.\n\n**INPUT_REQUIRED**\n\n1. Test the button"
        mock_follow_up.return_value = "Tests passed.\n\n**PASS**"

        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")

        assert result.latest_verdict == VERDICT_PASS
        assert result.iteration == 1
        assert result.running is False
        assert result.input_required is False
        # The final history entry should reflect the follow-up verdict
        assert result.history[-1].verdict == VERDICT_PASS
        mock_follow_up.assert_called_once()

    @patch("pm_core.review_loop._wait_for_follow_up_verdict")
    @patch("pm_core.review_loop._run_claude_review")
    def test_input_required_follow_up_needs_work_continues(self, mock_review, mock_follow_up):
        """After follow-up NEEDS_WORK, loop continues to next iteration."""
        mock_review.side_effect = [
            "Need testing.\n\n**INPUT_REQUIRED**\n\n1. Test it",
            "All good.\n\n**PASS**",
        ]
        mock_follow_up.return_value = "Issues found after testing.\n\n**NEEDS_WORK**"

        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")

        # First iteration: INPUT_REQUIRED → NEEDS_WORK from follow-up
        # Second iteration: PASS from fresh review
        assert result.latest_verdict == VERDICT_PASS
        assert result.iteration == 2

    @patch("pm_core.review_loop._wait_for_follow_up_verdict")
    @patch("pm_core.review_loop._run_claude_review")
    def test_input_required_pane_died_during_wait(self, mock_review, mock_follow_up):
        """Pane dying during INPUT_REQUIRED wait causes loop to exit with KILLED."""
        mock_review.return_value = "**INPUT_REQUIRED**\n\n1. Test it"
        mock_follow_up.return_value = None  # pane disappeared

        state = ReviewLoopState(pr_id="pr-001")
        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")

        assert result.latest_verdict == VERDICT_KILLED
        assert result.input_required is False
        assert result.running is False

    @patch("pm_core.review_loop._wait_for_follow_up_verdict")
    @patch("pm_core.review_loop._run_claude_review")
    def test_input_required_stop_requested_during_wait(self, mock_review, mock_follow_up):
        """Stop request during INPUT_REQUIRED poll causes loop to exit."""
        mock_review.return_value = "**INPUT_REQUIRED**\n\n1. Test it"

        def side_effect(*args, **kwargs):
            # Simulate stop requested during polling
            state.stop_requested = True
            return None

        state = ReviewLoopState(pr_id="pr-001")
        mock_follow_up.side_effect = side_effect

        result = run_review_loop_sync(state, "/tmp", _PR_DATA, transcript_dir="/tmp")

        assert result.input_required is False
        assert result.running is False


class TestGenerateReviewPromptInputRequired:
    """Tests that the review prompt includes INPUT_REQUIRED instructions."""

    def _make_data(self):
        return {
            "project": {"name": "test", "repo": "test/repo", "base_branch": "master"},
            "prs": [{
                "id": "pr-001",
                "title": "Add feature",
                "description": "Implement the feature",
                "branch": "pm/pr-001-add-feature",
                "status": "in_progress",
            }],
        }

    def test_base_prompt_includes_input_required(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001")
        assert "INPUT_REQUIRED" in prompt
        assert "human judgment" in prompt

    def test_review_loop_prompt_includes_input_required(self):
        from pm_core.prompt_gen import generate_review_prompt
        data = self._make_data()
        prompt = generate_review_prompt(data, "pr-001", review_loop=True)
        assert "INPUT_REQUIRED" in prompt
        # Should explain that it's reserved for genuine ambiguities
        assert "human judgment" in prompt
