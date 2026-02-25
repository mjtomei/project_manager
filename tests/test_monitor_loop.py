"""Tests for pm_core.monitor_loop and pm_core.prompt_gen monitor prompt."""

from unittest.mock import patch, MagicMock

import pytest

from pm_core.monitor_loop import (
    parse_monitor_verdict,
    run_monitor_loop_sync,
    start_monitor_loop_background,
    PaneKilledError,
    MonitorLoopState,
    MonitorIteration,
    _extract_verdict_from_content,
    _match_monitor_verdict,
    _MAX_HISTORY,
    VERDICT_READY,
    VERDICT_INPUT_REQUIRED,
    VERDICT_KILLED,
)
from pm_core.loop_shared import (
    build_prompt_verdict_lines as _build_prompt_verdict_lines,
    is_prompt_line as _is_prompt_line,
)


# --- parse_monitor_verdict tests ---

class TestParseMonitorVerdict:
    def test_ready(self):
        assert parse_monitor_verdict("All clear.\n\n**READY**") == VERDICT_READY

    def test_ready_plain(self):
        assert parse_monitor_verdict("READY") == VERDICT_READY

    def test_input_required(self):
        output = "Need human help.\n\n**INPUT_REQUIRED**\n\nPlease check auth"
        assert parse_monitor_verdict(output) == VERDICT_INPUT_REQUIRED

    def test_input_required_plain(self):
        assert parse_monitor_verdict("INPUT_REQUIRED") == VERDICT_INPUT_REQUIRED

    def test_input_required_bold(self):
        assert parse_monitor_verdict("**INPUT_REQUIRED**") == VERDICT_INPUT_REQUIRED

    def test_empty_output_is_ready(self):
        """No verdict found defaults to READY (continue monitoring)."""
        assert parse_monitor_verdict("") == VERDICT_READY

    def test_no_verdict_defaults_to_ready(self):
        assert parse_monitor_verdict("Some monitoring output with no verdict") == VERDICT_READY

    def test_verdict_on_own_line_wins(self):
        output = "Initial: INPUT_REQUIRED\n\nREADY"
        assert parse_monitor_verdict(output) == VERDICT_READY


# --- _match_monitor_verdict false positive rejection tests ---

class TestMatchMonitorVerdictFalsePositives:
    def test_standalone_verdicts_match(self):
        assert _match_monitor_verdict("READY") == VERDICT_READY
        assert _match_monitor_verdict("INPUT_REQUIRED") == VERDICT_INPUT_REQUIRED

    def test_bold_verdicts_match(self):
        assert _match_monitor_verdict("**READY**") == VERDICT_READY
        assert _match_monitor_verdict("**INPUT_REQUIRED**") == VERDICT_INPUT_REQUIRED

    def test_whitespace_around_keyword(self):
        assert _match_monitor_verdict("  READY  ") == VERDICT_READY
        assert _match_monitor_verdict("  **INPUT_REQUIRED**  ") == VERDICT_INPUT_REQUIRED

    def test_any_extra_text_rejected(self):
        assert _match_monitor_verdict("Verdict: READY") is None
        assert _match_monitor_verdict("Status: INPUT_REQUIRED") is None
        assert _match_monitor_verdict("My verdict: **READY**") is None

    def test_descriptive_sentence(self):
        assert _match_monitor_verdict("The READY verdict means continue monitoring") is None
        assert _match_monitor_verdict("When INPUT_REQUIRED is returned, the loop pauses") is None

    def test_prompt_instruction_line_rejected(self):
        line = "IMPORTANT: Always end your response with the verdict keyword on its own line -- either **READY** or"
        assert _match_monitor_verdict(line) is None

    def test_tmux_wrapped_fragments_rejected(self):
        assert _match_monitor_verdict("READY)") is None
        assert _match_monitor_verdict("INPUT_REQUIRED)") is None
        assert _match_monitor_verdict("(READY,") is None

    def test_review_verdicts_not_matched(self):
        """Monitor should not match review loop verdicts."""
        assert _match_monitor_verdict("PASS") is None
        assert _match_monitor_verdict("NEEDS_WORK") is None
        assert _match_monitor_verdict("PASS_WITH_SUGGESTIONS") is None


# --- prompt verdict filtering tests ---

def _get_real_monitor_prompt() -> str:
    """Generate the actual monitor prompt from prompt_gen."""
    from pm_core.prompt_gen import generate_monitor_prompt
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
    return generate_monitor_prompt(data, iteration=1, loop_id="ab12")


def _simulate_terminal_wrap(text: str, width: int = 80) -> str:
    """Simulate how a terminal wraps long lines at a given column width."""
    out = []
    for line in text.splitlines():
        while len(line) > width:
            out.append(line[:width])
            line = line[width:]
        out.append(line)
    return "\n".join(out)


class TestExtractVerdictFromContent:
    def test_real_verdict_detected_without_prompt(self):
        content = "\n".join(["line"] * 40 + ["**READY**"])
        assert _extract_verdict_from_content(content) == VERDICT_READY

    def test_real_verdict_after_prompt(self):
        prompt = _get_real_monitor_prompt()
        content = prompt + "\n\n" + "\n".join(["monitoring text"] * 40) + "\n\n**READY**"
        assert _extract_verdict_from_content(content, prompt_text=prompt) == VERDICT_READY

    def test_input_required_after_prompt(self):
        prompt = _get_real_monitor_prompt()
        content = prompt + "\n\n" + "\n".join(["monitoring text"] * 40) + "\n\n**INPUT_REQUIRED**"
        assert _extract_verdict_from_content(content, prompt_text=prompt) == VERDICT_INPUT_REQUIRED

    def test_no_prompt_text_no_false_positive(self):
        prompt = _get_real_monitor_prompt()
        assert _extract_verdict_from_content(prompt) is None

    def test_raw_prompt_not_detected(self):
        prompt = _get_real_monitor_prompt()
        assert _extract_verdict_from_content(prompt, prompt_text=prompt) is None

    def test_terminal_wrapped_prompt_not_detected(self):
        prompt = _get_real_monitor_prompt()
        wrapped = _simulate_terminal_wrap(prompt, width=80)
        assert _extract_verdict_from_content(wrapped, prompt_text=prompt) is None

    def test_terminal_wrapped_prompt_narrow_not_detected(self):
        prompt = _get_real_monitor_prompt()
        wrapped = _simulate_terminal_wrap(prompt, width=60)
        assert _extract_verdict_from_content(wrapped, prompt_text=prompt) is None

    def test_exclude_verdicts(self):
        content = "\n".join(["line"] * 40 + ["**INPUT_REQUIRED**"])
        result = _extract_verdict_from_content(
            content, exclude_verdicts={VERDICT_INPUT_REQUIRED}
        )
        assert result is None

    def test_verdict_line_variations_from_prompt_all_filtered(self):
        """Every line in the prompt that contains a verdict keyword should be filtered."""
        prompt = _get_real_monitor_prompt()
        for line in prompt.splitlines():
            stripped = line.strip().strip("*").strip()
            if not stripped:
                continue
            has_verdict = any(v in stripped for v in ("READY", "INPUT_REQUIRED"))
            if not has_verdict:
                continue
            pane = "\n".join(["other text"] * 40 + [line])
            result = _extract_verdict_from_content(pane, prompt_text=prompt)
            assert result is None, (
                f"Prompt line falsely detected as {result}: [{line.strip()}]"
            )


# Monitor-specific keywords for shared helpers
_MONITOR_KEYWORDS = ("INPUT_REQUIRED", "READY")


class TestBuildPromptVerdictLines:
    def test_extracts_verdict_lines_from_real_prompt(self):
        prompt = _get_real_monitor_prompt()
        lines = _build_prompt_verdict_lines(prompt, _MONITOR_KEYWORDS)
        assert any("READY" in line for line in lines)
        assert any("INPUT_REQUIRED" in line for line in lines)
        assert len(lines) >= 3

    def test_empty_prompt(self):
        assert _build_prompt_verdict_lines("", _MONITOR_KEYWORDS) == set()


class TestIsPromptLine:
    def test_exact_match(self):
        prompt_lines = {"READY -- All issues handled (or no issues found)."}
        assert _is_prompt_line("READY -- All issues handled (or no issues found).", prompt_lines, _MONITOR_KEYWORDS) is True

    def test_standalone_verdict_not_prompt(self):
        prompt_lines = {"READY -- All issues handled (or no issues found)."}
        assert _is_prompt_line("READY", prompt_lines, _MONITOR_KEYWORDS) is False

    def test_standalone_input_required_not_prompt(self):
        prompt_lines = {"INPUT_REQUIRED -- You need human input."}
        assert _is_prompt_line("INPUT_REQUIRED", prompt_lines, _MONITOR_KEYWORDS) is False


# --- MonitorLoopState tests ---

class TestMonitorLoopState:
    def test_defaults(self):
        state = MonitorLoopState()
        assert state.running is False
        assert state.stop_requested is False
        assert state.iteration == 0
        assert state.latest_verdict == ""
        assert state.latest_summary == ""
        assert state.history == []
        assert len(state.loop_id) == 4  # 2 bytes = 4 hex chars

    def test_unique_loop_ids(self):
        ids = {MonitorLoopState().loop_id for _ in range(10)}
        assert len(ids) == 10

    def test_input_required_defaults(self):
        state = MonitorLoopState()
        assert state.input_required is False


# --- run_monitor_loop_sync tests ---

class TestRunMonitorLoopSync:
    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_stops_on_max_iterations(self, mock_iter):
        mock_iter.return_value = "All clear.\n\n**READY**"
        state = MonitorLoopState()
        # Bypass the wait between iterations
        state.iteration_wait = 0
        result = run_monitor_loop_sync(state, "/tmp", max_iterations=2)
        assert result.iteration == 2
        assert result.latest_verdict == VERDICT_READY
        assert result.running is False
        assert len(result.history) == 2

    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_stop_requested(self, mock_iter):
        def side_effect(*args, **kwargs):
            state.stop_requested = True
            return "**READY**"

        mock_iter.side_effect = side_effect
        state = MonitorLoopState()
        state.iteration_wait = 0
        result = run_monitor_loop_sync(state, "/tmp")
        assert result.iteration == 1
        assert result.running is False

    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_pane_killed_stops_loop(self, mock_iter):
        mock_iter.side_effect = PaneKilledError("pane disappeared")
        state = MonitorLoopState()
        result = run_monitor_loop_sync(state, "/tmp")
        assert result.latest_verdict == VERDICT_KILLED
        assert result.running is False
        assert result.iteration == 1

    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_exception_stops_loop(self, mock_iter):
        mock_iter.side_effect = RuntimeError("setup failure")
        state = MonitorLoopState()
        result = run_monitor_loop_sync(state, "/tmp")
        assert result.latest_verdict == "ERROR"
        assert result.running is False

    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_calls_on_iteration_callback(self, mock_iter):
        mock_iter.return_value = "**READY**"
        callback = MagicMock()
        state = MonitorLoopState()
        state.iteration_wait = 0
        run_monitor_loop_sync(state, "/tmp", on_iteration=callback, max_iterations=1)
        callback.assert_called_once_with(state)

    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_history_capped(self, mock_iter):
        """History doesn't grow beyond _MAX_HISTORY entries."""
        mock_iter.return_value = "**READY**"
        state = MonitorLoopState()
        state.iteration_wait = 0
        run_monitor_loop_sync(state, "/tmp", max_iterations=_MAX_HISTORY + 10)
        assert len(state.history) <= _MAX_HISTORY

    @patch("pm_core.monitor_loop._wait_for_follow_up_verdict")
    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_input_required_polls_for_follow_up(self, mock_iter, mock_follow_up):
        mock_iter.return_value = "Need help.\n\n**INPUT_REQUIRED**\n\nCheck auth"
        mock_follow_up.return_value = "OK resolved.\n\n**READY**"

        state = MonitorLoopState()
        state.iteration_wait = 0
        result = run_monitor_loop_sync(state, "/tmp", max_iterations=1)

        assert result.latest_verdict == VERDICT_READY
        assert result.iteration == 1
        assert result.input_required is False
        mock_follow_up.assert_called_once()

    @patch("pm_core.monitor_loop._wait_for_follow_up_verdict")
    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_input_required_repeated_becomes_ready(self, mock_iter, mock_follow_up):
        """Repeated INPUT_REQUIRED in follow-up is treated as READY."""
        mock_iter.return_value = "**INPUT_REQUIRED**"
        mock_follow_up.return_value = "Still need help.\n\n**INPUT_REQUIRED**"

        state = MonitorLoopState()
        state.iteration_wait = 0
        result = run_monitor_loop_sync(state, "/tmp", max_iterations=1)

        # Repeated INPUT_REQUIRED is converted to READY
        assert result.latest_verdict == VERDICT_READY

    @patch("pm_core.monitor_loop._wait_for_follow_up_verdict")
    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_input_required_pane_died(self, mock_iter, mock_follow_up):
        mock_iter.return_value = "**INPUT_REQUIRED**"
        mock_follow_up.return_value = None  # pane disappeared

        state = MonitorLoopState()
        result = run_monitor_loop_sync(state, "/tmp")

        assert result.latest_verdict == VERDICT_KILLED
        assert result.input_required is False
        assert result.running is False


class TestStartMonitorLoopBackground:
    @patch("pm_core.monitor_loop._run_monitor_iteration")
    def test_runs_in_background_thread(self, mock_iter):
        mock_iter.return_value = "**READY**"
        state = MonitorLoopState()
        state.iteration_wait = 0
        complete_callback = MagicMock()
        thread = start_monitor_loop_background(
            state, "/tmp",
            on_complete=complete_callback,
            max_iterations=1,
        )
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert state.latest_verdict == VERDICT_READY
        assert state.running is False
        complete_callback.assert_called_once_with(state)


# --- generate_monitor_prompt tests ---

class TestGenerateMonitorPrompt:
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
            "plans": [
                {
                    "id": "plan-001",
                    "name": "Test plan",
                    "status": "active",
                },
            ],
        }

    def test_includes_role_section(self):
        from pm_core.prompt_gen import generate_monitor_prompt
        data = self._make_data()
        prompt = generate_monitor_prompt(data)
        assert "## Role" in prompt
        assert "watchdog session" in prompt

    def test_includes_pr_summary(self):
        from pm_core.prompt_gen import generate_monitor_prompt
        data = self._make_data()
        prompt = generate_monitor_prompt(data)
        assert "pr-001" in prompt
        assert "Add feature" in prompt

    def test_includes_plan_summary(self):
        from pm_core.prompt_gen import generate_monitor_prompt
        data = self._make_data()
        prompt = generate_monitor_prompt(data)
        assert "plan-001" in prompt
        assert "Test plan" in prompt

    def test_includes_verdicts(self):
        from pm_core.prompt_gen import generate_monitor_prompt
        data = self._make_data()
        prompt = generate_monitor_prompt(data)
        assert "**READY**" in prompt
        assert "**INPUT_REQUIRED**" in prompt

    def test_includes_iteration_label(self):
        from pm_core.prompt_gen import generate_monitor_prompt
        data = self._make_data()
        prompt = generate_monitor_prompt(data, iteration=3, loop_id="ab12")
        assert "(iteration 3)" in prompt
        assert "[ab12]" in prompt

    def test_includes_responsibilities(self):
        from pm_core.prompt_gen import generate_monitor_prompt
        data = self._make_data()
        prompt = generate_monitor_prompt(data)
        assert "Scan Active Tmux Panes" in prompt
        assert "Auto-Fix Issues" in prompt
        assert "Surface Issues Needing Human Input" in prompt
        assert "Project Health Monitoring" in prompt
        assert "Cross-Session Conflict Detection" in prompt
        assert "Master Branch Health Check" in prompt
        assert "pm Tool Self-Monitoring" in prompt

    def test_includes_tui_section_when_session_provided(self):
        from pm_core.prompt_gen import generate_monitor_prompt
        data = self._make_data()
        prompt = generate_monitor_prompt(data, session_name="pm-test-session")
        assert "pm tui view" in prompt
        assert "pm-test-session" in prompt

    def test_no_tui_section_without_session(self):
        from pm_core.prompt_gen import generate_monitor_prompt
        data = self._make_data()
        prompt = generate_monitor_prompt(data)
        assert "pm tui view" not in prompt
