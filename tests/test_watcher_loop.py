"""Tests for watcher framework: BaseWatcher, WatcherManager, and compat layer."""

from unittest.mock import patch, MagicMock

import pytest

from pm_core.watcher_loop import (
    parse_watcher_verdict,
    run_watcher_loop_sync,
    start_watcher_loop_background,
    PaneKilledError,
    WatcherLoopState,
    VERDICT_READY,
    VERDICT_INPUT_REQUIRED,
    VERDICT_KILLED,
)
from pm_core.watcher_base import (
    WatcherIteration,
    WatcherState,
    BaseWatcher,
    _MAX_HISTORY,
)
from pm_core.loop_shared import (
    match_verdict,
    extract_verdict_from_content,
    build_prompt_verdict_lines as _build_prompt_verdict_lines,
    is_prompt_line as _is_prompt_line,
)

# Watcher-specific verdict functions using loop_shared directly
ALL_WATCHER_VERDICTS = (VERDICT_READY, VERDICT_INPUT_REQUIRED)
_WATCHER_KEYWORDS = ("INPUT_REQUIRED", "READY")


def _match_watcher_verdict(line):
    return match_verdict(line, ALL_WATCHER_VERDICTS)


def _extract_verdict_from_content(content, prompt_text="", exclude_verdicts=None):
    return extract_verdict_from_content(
        content, verdicts=ALL_WATCHER_VERDICTS, keywords=_WATCHER_KEYWORDS,
        prompt_text=prompt_text, exclude_verdicts=exclude_verdicts,
        log_prefix="test_watcher",
    )


# --- parse_watcher_verdict tests ---

class TestParseWatcherVerdict:
    def test_ready(self):
        assert parse_watcher_verdict("All clear.\n\n**READY**") == VERDICT_READY

    def test_ready_plain(self):
        assert parse_watcher_verdict("READY") == VERDICT_READY

    def test_input_required(self):
        output = "Need human help.\n\n**INPUT_REQUIRED**\n\nPlease check auth"
        assert parse_watcher_verdict(output) == VERDICT_INPUT_REQUIRED

    def test_input_required_plain(self):
        assert parse_watcher_verdict("INPUT_REQUIRED") == VERDICT_INPUT_REQUIRED

    def test_input_required_bold(self):
        assert parse_watcher_verdict("**INPUT_REQUIRED**") == VERDICT_INPUT_REQUIRED

    def test_empty_output_is_ready(self):
        """No verdict found defaults to READY (continue watching)."""
        assert parse_watcher_verdict("") == VERDICT_READY

    def test_no_verdict_defaults_to_ready(self):
        assert parse_watcher_verdict("Some watching output with no verdict") == VERDICT_READY

    def test_verdict_on_own_line_wins(self):
        output = "Initial: INPUT_REQUIRED\n\nREADY"
        assert parse_watcher_verdict(output) == VERDICT_READY


# --- _match_watcher_verdict false positive rejection tests ---

class TestMatchWatcherVerdictFalsePositives:
    def test_standalone_verdicts_match(self):
        assert _match_watcher_verdict("READY") == VERDICT_READY
        assert _match_watcher_verdict("INPUT_REQUIRED") == VERDICT_INPUT_REQUIRED

    def test_bold_verdicts_match(self):
        assert _match_watcher_verdict("**READY**") == VERDICT_READY
        assert _match_watcher_verdict("**INPUT_REQUIRED**") == VERDICT_INPUT_REQUIRED

    def test_whitespace_around_keyword(self):
        assert _match_watcher_verdict("  READY  ") == VERDICT_READY
        assert _match_watcher_verdict("  **INPUT_REQUIRED**  ") == VERDICT_INPUT_REQUIRED

    def test_any_extra_text_rejected(self):
        assert _match_watcher_verdict("Verdict: READY") is None
        assert _match_watcher_verdict("Status: INPUT_REQUIRED") is None
        assert _match_watcher_verdict("My verdict: **READY**") is None

    def test_descriptive_sentence(self):
        assert _match_watcher_verdict("The READY verdict means continue watching") is None
        assert _match_watcher_verdict("When INPUT_REQUIRED is returned, the loop pauses") is None

    def test_prompt_instruction_line_rejected(self):
        line = "IMPORTANT: Always end your response with the verdict keyword on its own line -- either **READY** or"
        assert _match_watcher_verdict(line) is None

    def test_tmux_wrapped_fragments_rejected(self):
        assert _match_watcher_verdict("READY)") is None
        assert _match_watcher_verdict("INPUT_REQUIRED)") is None
        assert _match_watcher_verdict("(READY,") is None

    def test_review_verdicts_not_matched(self):
        """Watcher should not match review loop verdicts."""
        assert _match_watcher_verdict("PASS") is None
        assert _match_watcher_verdict("NEEDS_WORK") is None
        assert _match_watcher_verdict("PASS_WITH_SUGGESTIONS") is None


# --- prompt verdict filtering tests ---

def _get_real_watcher_prompt() -> str:
    """Generate the actual watcher prompt from prompt_gen."""
    from pm_core.prompt_gen import generate_watcher_prompt
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
    return generate_watcher_prompt(data, iteration=1, loop_id="ab12")


from tests.conftest import simulate_terminal_wrap as _simulate_terminal_wrap


class TestExtractVerdictFromContent:
    def test_real_verdict_detected_without_prompt(self):
        content = "\n".join(["line"] * 40 + ["**READY**"])
        assert _extract_verdict_from_content(content) == VERDICT_READY

    def test_real_verdict_after_prompt(self):
        prompt = _get_real_watcher_prompt()
        content = prompt + "\n\n" + "\n".join(["watching text"] * 40) + "\n\n**READY**"
        assert _extract_verdict_from_content(content, prompt_text=prompt) == VERDICT_READY

    def test_input_required_after_prompt(self):
        prompt = _get_real_watcher_prompt()
        content = prompt + "\n\n" + "\n".join(["watching text"] * 40) + "\n\n**INPUT_REQUIRED**"
        assert _extract_verdict_from_content(content, prompt_text=prompt) == VERDICT_INPUT_REQUIRED

    def test_no_prompt_text_no_false_positive(self):
        prompt = _get_real_watcher_prompt()
        assert _extract_verdict_from_content(prompt) is None

    def test_raw_prompt_not_detected(self):
        prompt = _get_real_watcher_prompt()
        assert _extract_verdict_from_content(prompt, prompt_text=prompt) is None

    def test_terminal_wrapped_prompt_not_detected(self):
        prompt = _get_real_watcher_prompt()
        wrapped = _simulate_terminal_wrap(prompt, width=80)
        assert _extract_verdict_from_content(wrapped, prompt_text=prompt) is None

    def test_terminal_wrapped_prompt_narrow_not_detected(self):
        prompt = _get_real_watcher_prompt()
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
        prompt = _get_real_watcher_prompt()
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


class TestBuildPromptVerdictLines:
    def test_extracts_verdict_lines_from_real_prompt(self):
        prompt = _get_real_watcher_prompt()
        lines = _build_prompt_verdict_lines(prompt, _WATCHER_KEYWORDS)
        assert any("READY" in line for line in lines)
        assert any("INPUT_REQUIRED" in line for line in lines)
        assert len(lines) >= 3

    def test_empty_prompt(self):
        assert _build_prompt_verdict_lines("", _WATCHER_KEYWORDS) == set()


class TestIsPromptLine:
    def test_exact_match(self):
        prompt_lines = {"READY -- All issues handled (or no issues found)."}
        assert _is_prompt_line("READY -- All issues handled (or no issues found).", prompt_lines, _WATCHER_KEYWORDS) is True

    def test_standalone_verdict_not_prompt(self):
        prompt_lines = {"READY -- All issues handled (or no issues found)."}
        assert _is_prompt_line("READY", prompt_lines, _WATCHER_KEYWORDS) is False

    def test_standalone_input_required_not_prompt(self):
        prompt_lines = {"INPUT_REQUIRED -- You need human input."}
        assert _is_prompt_line("INPUT_REQUIRED", prompt_lines, _WATCHER_KEYWORDS) is False


# --- WatcherLoopState tests ---

class TestWatcherLoopState:
    def test_defaults(self):
        state = WatcherLoopState()
        assert state.running is False
        assert state.stop_requested is False
        assert state.iteration == 0
        assert state.latest_verdict == ""
        assert state.latest_summary == ""
        assert state.history == []
        assert len(state.loop_id) == 4  # 2 bytes = 4 hex chars

    def test_unique_loop_ids(self):
        ids = {WatcherLoopState().loop_id for _ in range(10)}
        assert len(ids) == 10

    def test_input_required_defaults(self):
        state = WatcherLoopState()
        assert state.input_required is False


# --- WatcherState tests ---

class TestWatcherState:
    def test_defaults(self):
        state = WatcherState()
        assert state.running is False
        assert state.watcher_id == ""
        assert state.watcher_type == ""
        assert len(state.loop_id) == 4

    def test_with_type(self):
        state = WatcherState(watcher_type="auto-start", display_name="Auto-Start Watcher")
        assert state.watcher_type == "auto-start"
        assert state.display_name == "Auto-Start Watcher"


# --- BaseWatcher tests ---

class TestBaseWatcher:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseWatcher("/tmp")

    def test_subclass_with_required_methods(self):
        class TestWatcher(BaseWatcher):
            WATCHER_TYPE = "test"
            DISPLAY_NAME = "Test Watcher"
            WINDOW_NAME = "test-watcher"

            def generate_prompt(self, iteration):
                return f"Test prompt iteration {iteration}"

            def build_launch_cmd(self, iteration, transcript=None):
                return ["echo", "test"]

            def parse_verdict(self, output):
                return "READY"

        w = TestWatcher("/tmp")
        assert w.WATCHER_TYPE == "test"
        assert w.state.watcher_type == "test"
        assert w.state.running is False
        assert w.generate_prompt(1) == "Test prompt iteration 1"
        assert w.parse_verdict("anything") == "READY"

    @patch("pm_core.watcher_base.BaseWatcher._wait_for_follow_up")
    @patch("pm_core.watcher_base.BaseWatcher._run_iteration")
    def test_input_required_polls_for_follow_up(self, mock_iter, mock_follow_up):
        """INPUT_REQUIRED triggers follow-up polling and resumes on READY."""
        class FW(BaseWatcher):
            WATCHER_TYPE = "test"
            DISPLAY_NAME = "Test"
            WINDOW_NAME = "test"
            def generate_prompt(self, iteration): return ""
            def build_launch_cmd(self, iteration, transcript=None): return ["echo"]
            def parse_verdict(self, output):
                from pm_core.loop_shared import match_verdict
                for line in reversed(output.strip().splitlines()):
                    v = match_verdict(line.strip().strip("*").strip(), self.VERDICTS)
                    if v:
                        return v
                return "READY"

        mock_iter.return_value = "Need help.\n\n**INPUT_REQUIRED**\n\nCheck auth"
        mock_follow_up.return_value = "OK resolved.\n\n**READY**"

        w = FW("/tmp")
        w.state.iteration_wait = 0
        result = w.run_sync(max_iterations=1)

        assert result.latest_verdict == VERDICT_READY
        assert result.iteration == 1
        assert result.input_required is False
        mock_follow_up.assert_called_once()

    @patch("pm_core.watcher_base.BaseWatcher._wait_for_follow_up")
    @patch("pm_core.watcher_base.BaseWatcher._run_iteration")
    def test_input_required_repeated_becomes_ready(self, mock_iter, mock_follow_up):
        """Repeated INPUT_REQUIRED in follow-up is converted to READY."""
        class FW(BaseWatcher):
            WATCHER_TYPE = "test"
            DISPLAY_NAME = "Test"
            WINDOW_NAME = "test"
            def generate_prompt(self, iteration): return ""
            def build_launch_cmd(self, iteration, transcript=None): return ["echo"]
            def parse_verdict(self, output):
                from pm_core.loop_shared import match_verdict
                for line in reversed(output.strip().splitlines()):
                    v = match_verdict(line.strip().strip("*").strip(), self.VERDICTS)
                    if v:
                        return v
                return "READY"

        mock_iter.return_value = "**INPUT_REQUIRED**"
        mock_follow_up.return_value = "Still need help.\n\n**INPUT_REQUIRED**"

        w = FW("/tmp")
        w.state.iteration_wait = 0
        result = w.run_sync(max_iterations=1)

        assert result.latest_verdict == VERDICT_READY

    @patch("pm_core.watcher_base.BaseWatcher._wait_for_follow_up")
    @patch("pm_core.watcher_base.BaseWatcher._run_iteration")
    def test_input_required_pane_died(self, mock_iter, mock_follow_up):
        """Pane disappearing during INPUT_REQUIRED sets KILLED verdict."""
        class FW(BaseWatcher):
            WATCHER_TYPE = "test"
            DISPLAY_NAME = "Test"
            WINDOW_NAME = "test"
            def generate_prompt(self, iteration): return ""
            def build_launch_cmd(self, iteration, transcript=None): return ["echo"]
            def parse_verdict(self, output):
                from pm_core.loop_shared import match_verdict
                for line in reversed(output.strip().splitlines()):
                    v = match_verdict(line.strip().strip("*").strip(), self.VERDICTS)
                    if v:
                        return v
                return "READY"

        mock_iter.return_value = "**INPUT_REQUIRED**"
        mock_follow_up.return_value = None  # pane disappeared

        w = FW("/tmp")
        result = w.run_sync()

        assert result.latest_verdict == VERDICT_KILLED
        assert result.input_required is False
        assert result.running is False


# --- WatcherManager tests ---

class TestWatcherManager:
    def _make_watcher(self, watcher_type="test"):
        class FakeWatcher(BaseWatcher):
            WATCHER_TYPE = watcher_type
            DISPLAY_NAME = f"Fake {watcher_type}"
            WINDOW_NAME = f"fake-{watcher_type}"

            def generate_prompt(self, iteration):
                return ""

            def build_launch_cmd(self, iteration, transcript=None):
                return ["echo"]

            def parse_verdict(self, output):
                return "READY"

        return FakeWatcher("/tmp")

    def test_register_and_list(self):
        from pm_core.watcher_manager import WatcherManager
        mgr = WatcherManager()
        w = self._make_watcher()
        mgr.register(w)
        watchers = mgr.list_watchers()
        assert len(watchers) == 1
        assert watchers[0]["type"] == "test"
        assert watchers[0]["running"] is False

    def test_find_by_type(self):
        from pm_core.watcher_manager import WatcherManager
        mgr = WatcherManager()
        w = self._make_watcher("auto-start")
        mgr.register(w)
        found = mgr.find_by_type("auto-start")
        assert found is w
        assert mgr.find_by_type("nonexistent") is None

    def test_unregister(self):
        from pm_core.watcher_manager import WatcherManager
        mgr = WatcherManager()
        w = self._make_watcher()
        mgr.register(w)
        mgr.unregister(w.state.watcher_id)
        assert mgr.list_watchers() == []

    def test_is_any_running(self):
        from pm_core.watcher_manager import WatcherManager
        mgr = WatcherManager()
        w = self._make_watcher()
        mgr.register(w)
        assert mgr.is_any_running() is False
        w.state.running = True
        assert mgr.is_any_running() is True

    def test_stop_all(self):
        from pm_core.watcher_manager import WatcherManager
        mgr = WatcherManager()
        w1 = self._make_watcher("a")
        w2 = self._make_watcher("b")
        w1.state.running = True
        w2.state.running = True
        mgr.register(w1)
        mgr.register(w2)
        mgr.stop_all()
        assert w1.state.stop_requested is True
        assert w2.state.stop_requested is True


# --- AutoStartWatcher tests ---

class TestAutoStartWatcher:
    def test_basic_properties(self):
        from pm_core.watchers.auto_start_watcher import AutoStartWatcher
        w = AutoStartWatcher("/tmp")
        assert w.WATCHER_TYPE == "auto-start"
        assert w.DISPLAY_NAME == "Auto-Start Watcher"
        assert w.WINDOW_NAME == "watcher"
        assert w.DEFAULT_INTERVAL == 120

    def test_build_launch_cmd(self):
        from pm_core.watchers.auto_start_watcher import AutoStartWatcher
        w = AutoStartWatcher("/tmp", auto_start_target="pr-001")
        cmd = w.build_launch_cmd(3, transcript="/tmp/t.jsonl")
        assert "--iteration" in cmd
        assert "3" in cmd
        assert "--auto-start-target" in cmd
        assert "pr-001" in cmd
        assert "--transcript" in cmd

    def test_parse_verdict(self):
        from pm_core.watchers.auto_start_watcher import AutoStartWatcher
        w = AutoStartWatcher("/tmp")
        assert w.parse_verdict("All clear.\n\n**READY**") == "READY"
        assert w.parse_verdict("Need help.\n**INPUT_REQUIRED**") == "INPUT_REQUIRED"
        assert w.parse_verdict("No verdict here") == "READY"


# --- run_watcher_loop_sync compat tests ---

class TestRunWatcherLoopSync:
    @patch("pm_core.watcher_base.BaseWatcher._run_iteration")
    def test_stops_on_max_iterations(self, mock_iter):
        mock_iter.return_value = "All clear.\n\n**READY**"
        state = WatcherLoopState()
        state.iteration_wait = 0
        result = run_watcher_loop_sync(state, "/tmp", max_iterations=2)
        assert result.iteration == 2
        assert result.latest_verdict == VERDICT_READY
        assert result.running is False
        assert len(result.history) == 2

    @patch("pm_core.watcher_base.BaseWatcher._run_iteration")
    def test_pane_killed_stops_loop(self, mock_iter):
        mock_iter.side_effect = PaneKilledError("pane disappeared")
        state = WatcherLoopState()
        result = run_watcher_loop_sync(state, "/tmp")
        assert result.latest_verdict == VERDICT_KILLED
        assert result.running is False
        assert result.iteration == 1

    @patch("pm_core.watcher_base.BaseWatcher._run_iteration")
    def test_exception_stops_loop(self, mock_iter):
        mock_iter.side_effect = RuntimeError("setup failure")
        state = WatcherLoopState()
        result = run_watcher_loop_sync(state, "/tmp")
        assert result.latest_verdict == "ERROR"
        assert result.running is False

    @patch("pm_core.watcher_base.BaseWatcher._run_iteration")
    def test_calls_on_iteration_callback(self, mock_iter):
        mock_iter.return_value = "**READY**"
        callback = MagicMock()
        state = WatcherLoopState()
        state.iteration_wait = 0
        run_watcher_loop_sync(state, "/tmp", on_iteration=callback, max_iterations=1)
        callback.assert_called_once_with(state)

    @patch("pm_core.watcher_base.BaseWatcher._run_iteration")
    def test_history_capped(self, mock_iter):
        """History doesn't grow beyond _MAX_HISTORY entries."""
        mock_iter.return_value = "**READY**"
        state = WatcherLoopState()
        state.iteration_wait = 0
        run_watcher_loop_sync(state, "/tmp", max_iterations=_MAX_HISTORY + 10)
        assert len(state.history) <= _MAX_HISTORY


class TestStartWatcherLoopBackground:
    @patch("pm_core.watcher_base.BaseWatcher._run_iteration")
    def test_runs_in_background_thread(self, mock_iter):
        mock_iter.return_value = "**READY**"
        state = WatcherLoopState()
        state.iteration_wait = 0
        complete_callback = MagicMock()
        thread = start_watcher_loop_background(
            state, "/tmp",
            on_complete=complete_callback,
            max_iterations=1,
        )
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert state.latest_verdict == VERDICT_READY
        assert state.running is False
        complete_callback.assert_called_once_with(state)


# --- generate_watcher_prompt tests ---

class TestGenerateWatcherPrompt:
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
        from pm_core.prompt_gen import generate_watcher_prompt
        data = self._make_data()
        prompt = generate_watcher_prompt(data)
        assert "## Role" in prompt
        assert "autonomous monitoring" in prompt

    def test_includes_pr_inspection_commands(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        data = self._make_data()
        prompt = generate_watcher_prompt(data)
        assert "pm pr list" in prompt
        assert "pm pr graph" in prompt

    def test_includes_plan_inspection_commands(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        data = self._make_data()
        prompt = generate_watcher_prompt(data)
        assert "pm plan list" in prompt
        assert "cat pm/project.yaml" in prompt

    def test_includes_verdicts(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        data = self._make_data()
        prompt = generate_watcher_prompt(data)
        assert "**READY**" in prompt
        assert "**INPUT_REQUIRED**" in prompt

    def test_includes_iteration_label(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        data = self._make_data()
        prompt = generate_watcher_prompt(data, iteration=3, loop_id="ab12")
        assert "(iteration 3)" in prompt
        assert "[ab12]" in prompt

    def test_includes_responsibilities(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        data = self._make_data()
        prompt = generate_watcher_prompt(data)
        assert "Scan Active Tmux Panes" in prompt
        assert "Auto-Fix Issues" in prompt
        assert "Surface Issues Needing Human Input" in prompt
        assert "Project Health Monitoring" in prompt
        assert "Master Branch Health Check" in prompt
        assert "pm Tool Self-Monitoring" in prompt

    def test_includes_tui_section_when_session_provided(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        data = self._make_data()
        prompt = generate_watcher_prompt(data, session_name="pm-test-session")
        assert "pm tui view" in prompt
        assert "pm-test-session" in prompt

    def test_no_tui_section_without_session(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        data = self._make_data()
        prompt = generate_watcher_prompt(data)
        assert "pm tui view" not in prompt


# --- CLI routing tests ---

class TestWatcherCLI:
    """Test pm watcher CLI routing between user and internal modes."""

    @patch("pm_core.cli.watcher._run_user_watcher_loop")
    def test_no_iteration_runs_user_loop(self, mock_user_loop):
        from click.testing import CliRunner
        from pm_core.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["watcher"])
        mock_user_loop.assert_called_once_with(120, 0)

    @patch("pm_core.cli.watcher._run_user_watcher_loop")
    def test_custom_wait_and_max(self, mock_user_loop):
        from click.testing import CliRunner
        from pm_core.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["watcher", "--wait", "60", "--max-iterations", "5"])
        mock_user_loop.assert_called_once_with(60, 5)

    @patch("pm_core.cli.watcher._create_watcher_window")
    def test_iteration_provided_creates_window(self, mock_create):
        from click.testing import CliRunner
        from pm_core.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["watcher", "--iteration", "3"])
        mock_create.assert_called_once_with(3, "", None, auto_start_target=None, meta_pm_root=None)

    def test_list_subcommand(self):
        from click.testing import CliRunner
        from pm_core.cli import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["watcher", "list"])
        assert result.exit_code == 0
        assert "auto-start" in result.output
        assert "Auto-Start Watcher" in result.output


# --- Watcher registry tests ---

class TestWatcherRegistry:
    def test_auto_start_registered(self):
        from pm_core.watchers import WATCHER_REGISTRY, get_watcher_class
        assert "auto-start" in WATCHER_REGISTRY
        cls = get_watcher_class("auto-start")
        assert cls is not None
        assert cls.WATCHER_TYPE == "auto-start"

    def test_list_watcher_types(self):
        from pm_core.watchers import list_watcher_types
        types = list_watcher_types()
        assert len(types) >= 1
        assert any(t["type"] == "auto-start" for t in types)

    def test_unknown_type_returns_none(self):
        from pm_core.watchers import get_watcher_class
        assert get_watcher_class("nonexistent") is None
