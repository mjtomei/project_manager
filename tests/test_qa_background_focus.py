"""Background (scheduler-driven) QA starts must not steal tmux focus.

pr-f094946: on first-time creation of the ``qa-<pr>`` window,
``run_qa_sync`` selected it unconditionally (unless a popup suppress flag
was set).  ``tmux.select_window`` targets the attached client's session,
so every auto-started QA run — auto-start, review PASS → QA, sign-off
REQA, self-driving restarts, ``pm pr qa-run-bg`` — pulled attached
clients off the TUI window.  Only user-initiated starts (``t``, ``z t``,
``zz t``) may select the window.
"""

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from pm_core import qa_loop, store
from pm_core.qa_loop import QALoopState


# ---------------------------------------------------------------------------
# run_qa_sync: first-time window creation
# ---------------------------------------------------------------------------

def _run_to_window_creation(tmp_path, monkeypatch, state, *,
                            existing_win=None, watchers=(),
                            suppress=False, planner_pane=None):
    """Drive run_qa_sync's planning phase up to the window-focus step.

    ``find_claude_pane`` returns None so the run stops right after the
    focus handling.  Returns the tmux / runtime_state mocks.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    pr = {"id": "pr-001", "title": "t", "branch": "pm/pr-001",
          "status": "qa", "workdir": str(workdir)}
    data = {"project": {"name": "p"}, "prs": [pr]}
    state.qa_workdir = str(tmp_path / "qa")

    mocks = {
        "select_window": MagicMock(),
        "switch_sessions_to_window": MagicMock(),
        "consume_suppress_switch": MagicMock(return_value=suppress),
    }
    resolution = MagicMock(model=None, provider=None, effort=None)
    patches = [
        patch("pm_core.qa_loop.get_pm_session", return_value="pm-test"),
        patch("pm_core.store.load", return_value=data),
        patch("pm_core.qa_loop._resolve_qa_model", return_value=resolution),
        patch("pm_core.qa_loop._next_scenario_offset", return_value=0),
        patch("pm_core.qa_loop._launch_scenario_0", return_value=None),
        patch("pm_core.qa_loop._write_status_file"),
        patch("pm_core.qa_loop._cleanup_stale_scenario_windows"),
        patch("pm_core.container.is_container_mode_enabled",
              return_value=False),
        patch("pm_core.prompt_gen.generate_qa_planner_prompt",
              return_value="prompt"),
        patch("pm_core.claude_launcher.build_claude_shell_cmd",
              return_value="planner-cmd"),
        patch("pm_core.tmux.find_window_by_name", return_value=existing_win),
        patch("pm_core.tmux.sessions_on_window", return_value=list(watchers)),
        patch("pm_core.tmux.new_window"),
        patch("pm_core.tmux.select_window", mocks["select_window"]),
        patch("pm_core.tmux.switch_sessions_to_window",
              mocks["switch_sessions_to_window"]),
        patch("pm_core.runtime_state.consume_suppress_switch",
              mocks["consume_suppress_switch"]),
        patch("pm_core.qa_loop.find_claude_pane", return_value=planner_pane),
        # Planner registration runs when a planner pane is found; keep it
        # off the real tmux server and registry.
        patch("pm_core.pane_registry.prune_dead_windows", return_value=[]),
        patch("pm_core.pane_registry.load_registry", return_value={"windows": {}}),
        patch("pm_core.qa_loop.time.sleep"),
    ]
    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        qa_loop.run_qa_sync(state, tmp_path / "pm", pr)
    # Sanity: the harness reached (and stopped at) the planner-pane lookup.
    assert state.latest_output == "Could not find planner pane"
    return mocks


class TestRunQaSyncWindowFocus:
    def test_planner_registered_before_polling(self, tmp_path, monkeypatch):
        class PollStarted(Exception):
            pass

        def start_poll(*args, **kwargs):
            register.assert_called_once_with(
                "pm-test", "@8", [("%9", "qa-planner", "planner")])
            raise PollStarted

        with patch("pm_core.tmux.pane_window_id", return_value="@8"), \
                patch("pm_core.pane_layout.register_and_rebalance") as register, \
                patch("pm_core.claude_launcher.WorkspacePromptWatch",
                      side_effect=start_poll):
            with pytest.raises(PollStarted):
                _run_to_window_creation(
                    tmp_path, monkeypatch, QALoopState(pr_id="pr-001"),
                    planner_pane="%9")

    @pytest.mark.parametrize("registered", [False, True])
    def test_status_split_registers_missing_planner_only(self, registered):
        registry = {"windows": {"@8": {"panes": (
            [{"id": "%9", "role": "qa-planner"}] if registered else [])}}}
        with patch("pm_core.tmux.split_pane_at", return_value="%10"), \
                patch("pm_core.tmux.pane_window_id", return_value="@8"), \
                patch("pm_core.pane_registry.prune_dead_windows",
                      return_value=[]), \
                patch("pm_core.pane_registry.load_registry", return_value=registry), \
                patch("pm_core.pane_layout.register_and_rebalance") as register:
            qa_loop._add_status_pane("pm-test", "%9", "/qa/status.json")
        panes = [pane for call in register.call_args_list for pane in call.args[2]]
        expected = [] if registered else [("%9", "qa-planner")]
        assert [(pane, role) for pane, role, _ in panes] == expected + [
            ("%10", "qa-status")]

    def test_planner_registration_is_idempotent(self, tmp_path, monkeypatch):
        from pm_core import pane_registry

        monkeypatch.setenv("HOME", str(tmp_path))
        with patch("pm_core.tmux.pane_window_id", return_value="@8"), \
                patch("pm_core.pane_registry.prune_dead_windows",
                      return_value=[]), \
                patch("pm_core.pane_layout.rebalance"):
            qa_loop._register_qa_planner("pm-test", "%9")
            qa_loop._register_qa_planner("pm-test", "%9")
        panes = pane_registry.load_registry("pm-test")["windows"]["@8"]["panes"]
        assert [(p["id"], p["role"]) for p in panes] == [("%9", "qa-planner")]

    def test_planner_registry_timeout_does_not_abort_polling(self, tmp_path, monkeypatch):
        class PollStarted(Exception):
            pass

        with patch("pm_core.tmux.pane_window_id", return_value="@8"), \
                patch("pm_core.pane_registry.load_registry", return_value={}), \
                patch("pm_core.pane_layout.register_and_rebalance",
                      side_effect=TimeoutError("registry lock held")), \
                patch("pm_core.claude_launcher.WorkspacePromptWatch",
                      side_effect=PollStarted):
            with pytest.raises(PollStarted):
                _run_to_window_creation(
                    tmp_path, monkeypatch, QALoopState(pr_id="pr-001"),
                    planner_pane="%9")

    def test_background_start_does_not_select_window(
            self, tmp_path, monkeypatch):
        """The repro: a default (scheduler-built) state must stay focus-safe."""
        mocks = _run_to_window_creation(
            tmp_path, monkeypatch, QALoopState(pr_id="pr-001"))
        mocks["select_window"].assert_not_called()

    def test_background_start_leaves_suppress_flag_for_user_start(
            self, tmp_path, monkeypatch):
        """The popup's suppress flag belongs to the user's queued start; a
        background launch must not consume it on that start's behalf."""
        mocks = _run_to_window_creation(
            tmp_path, monkeypatch, QALoopState(pr_id="pr-001"),
            suppress=True)
        mocks["consume_suppress_switch"].assert_not_called()

    def test_user_start_selects_new_window(self, tmp_path, monkeypatch):
        state = QALoopState(pr_id="pr-001", focus_on_create=True)
        mocks = _run_to_window_creation(tmp_path, monkeypatch, state)
        mocks["select_window"].assert_called_once_with(
            "pm-test", "qa-pr-001")

    def test_user_start_honours_popup_suppress_flag(
            self, tmp_path, monkeypatch):
        state = QALoopState(pr_id="pr-001", focus_on_create=True)
        mocks = _run_to_window_creation(
            tmp_path, monkeypatch, state, suppress=True)
        mocks["consume_suppress_switch"].assert_called_once_with(
            "pr-001", "qa")
        mocks["select_window"].assert_not_called()

    def test_background_replacement_keeps_watchers_on_qa(
            self, tmp_path, monkeypatch):
        """Clients already viewing the old QA window follow the replacement
        even for background restarts — that moves no one off the TUI."""
        mocks = _run_to_window_creation(
            tmp_path, monkeypatch, QALoopState(pr_id="pr-001"),
            existing_win={"id": "@5", "name": "qa-pr-001"},
            watchers=["pm-test~2"])
        mocks["switch_sessions_to_window"].assert_called_once_with(
            ["pm-test~2"], "pm-test", "qa-pr-001")
        mocks["select_window"].assert_not_called()


# ---------------------------------------------------------------------------
# TUI entry points: which starts ask for focus
# ---------------------------------------------------------------------------

def _make_app(tmp_path, *, pr_status="qa"):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    data = {
        "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
        "prs": [{"id": "pr-001", "title": "T", "branch": "b",
                 "status": pr_status, "workdir": str(tmp_path / "wd"),
                 "notes": []}],
    }
    store.save(data, pm_dir)
    app = MagicMock()
    app._root = pm_dir
    app._data = data
    app._auto_start = True
    app._auto_start_targets = {}
    app._auto_start_all = True
    app._auto_start_run_id = None
    app._qa_loops = {}
    app._review_loops = {}
    app._self_driving_qa = {}
    return app


def _started_state(mock_bg) -> QALoopState:
    mock_bg.assert_called_once()
    return mock_bg.call_args.args[0]


class TestEntryPointFocus:
    def test_auto_start_qa_is_focus_safe(self, tmp_path):
        from pm_core.tui.auto_start import _auto_start_qa_loops
        app = _make_app(tmp_path)
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg:
            _auto_start_qa_loops(app)
        assert _started_state(bg).focus_on_create is False

    def test_review_pass_to_qa_is_focus_safe(self, tmp_path):
        from pm_core.tui.review_loop_ui import _maybe_start_qa
        app = _make_app(tmp_path, pr_status="in_review")
        app._load_state.side_effect = lambda: setattr(
            app, "_data", store.load(app._root))
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg:
            _maybe_start_qa(app, "pr-001")
        assert _started_state(bg).focus_on_create is False

    def test_internal_start_qa_defaults_focus_safe(self, tmp_path):
        """start_qa is the internal/scheduler entry (sign-off REQA hop,
        self-driving restart): focus-safe unless the caller opts in."""
        from pm_core.tui.qa_loop_ui import start_qa
        app = _make_app(tmp_path)
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg:
            start_qa(app, "pr-001")
        assert _started_state(bg).focus_on_create is False

    def test_t_without_window_requests_focus(self, tmp_path):
        from pm_core.tui.qa_loop_ui import focus_or_start_qa
        app = _make_app(tmp_path)
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg, \
             patch("pm_core.tui.qa_loop_ui.get_pm_session",
                   return_value="pm-test"), \
             patch("pm_core.tmux.find_window_by_name", return_value=None):
            focus_or_start_qa(app, "pr-001")
        assert _started_state(bg).focus_on_create is True

    @pytest.mark.parametrize("suppress", [False, True])
    def test_t_adopts_pending_background_start(self, tmp_path, monkeypatch, suppress):
        """An explicit t promotes the accepted run, without a duplicate worker.

        Popup dismissal must still suppress the eventual first-window select.
        """
        from pm_core.tui.qa_loop_ui import focus_or_start_qa
        app = _make_app(tmp_path)
        state = QALoopState(pr_id="pr-001", running=True)
        app._qa_loops["pr-001"] = state
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg, \
                patch("pm_core.tui.qa_loop_ui.get_pm_session", return_value="pm-test"), \
                patch("pm_core.tmux.find_window_by_name", return_value=None):
            focus_or_start_qa(app, "pr-001")
        bg.assert_not_called()
        assert app._qa_loops["pr-001"] is state
        assert state.focus_on_create is True
        mocks = _run_to_window_creation(
            tmp_path, monkeypatch, state, suppress=suppress)
        mocks["consume_suppress_switch"].assert_called_once_with("pr-001", "qa")
        if suppress:
            mocks["select_window"].assert_not_called()
        else:
            mocks["select_window"].assert_called_once_with("pm-test", "qa-pr-001")

    def test_background_dedup_keeps_existing_focus_intent(self, tmp_path):
        from pm_core.tui.qa_loop_ui import start_qa
        app = _make_app(tmp_path)
        state = QALoopState(pr_id="pr-001", running=True, focus_on_create=True)
        app._qa_loops["pr-001"] = state
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg:
            start_qa(app, "pr-001")
        bg.assert_not_called()
        assert state.focus_on_create is True

    def test_z_t_fresh_start_requests_focus(self, tmp_path):
        from pm_core.tui.qa_loop_ui import fresh_start_qa
        app = _make_app(tmp_path)
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg:
            fresh_start_qa(app, "pr-001")
        assert _started_state(bg).focus_on_create is True

    def test_zz_t_loop_start_requests_focus(self, tmp_path):
        from pm_core.tui.qa_loop_ui import start_or_stop_qa_loop
        app = _make_app(tmp_path)
        with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg, \
             patch("pm_core.tui.qa_loop_ui._get_qa_pass_count",
                   return_value=1):
            start_or_stop_qa_loop(app, "pr-001")
        assert _started_state(bg).focus_on_create is True
