"""log_message: sticky messages hide plain ones, but not forced ones.

QA repro (pr-0b87a97 s3): ``pm autostart remove X`` landed while the
sticky "Review loop done … PASS" message was up, so the TUI never showed
"Auto-start: removed X (1 remaining)".
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pm_core.tui import auto_start
from pm_core.tui.app import ProjectManagerApp


def _stub_app():
    shown = []
    app = SimpleNamespace(
        _log_sticky_until=0.0,
        _log_hold_until=0.0,
        _log_held=None,
        timers=[],
        query_one=lambda *a, **k: SimpleNamespace(update=shown.append),
        call_after_refresh=lambda *a, **k: None,
        _capture_frame=None,
    )
    app.set_timer = lambda delay, cb: app.timers.append(cb)
    app.log_message = lambda msg, **kw: ProjectManagerApp.log_message(
        app, msg, **kw)
    app._flush_held_log_message = (
        lambda: ProjectManagerApp._flush_held_log_message(app))
    return app, shown


def _log(app, msg, **kw):
    ProjectManagerApp.log_message(app, msg, **kw)


def test_plain_message_dropped_while_sticky():
    app, shown = _stub_app()
    _log(app, "Review loop done: PASS", sticky=10)
    _log(app, "background chatter")
    assert shown == [" Review loop done: PASS"]


def test_forced_message_shown_without_extending_sticky():
    app, shown = _stub_app()
    _log(app, "Review loop done: PASS", sticky=10)
    until = app._log_sticky_until
    _log(app, "Auto-start: removed pr-x (1 remaining)", force=True)
    assert shown[-1] == " Auto-start: removed pr-x (1 remaining)"
    assert app._log_sticky_until == until
    assert until > time.monotonic()


def test_autostart_target_changes_are_forced():
    app = MagicMock()
    app._auto_start_targets = {"pr-x": {"policy": "stop_before_merge"},
                               "pr-y": {"policy": "stop_before_merge"}}
    app._auto_start_all = False
    app._data = {"prs": [{"id": "pr-x"}, {"id": "pr-y"}]}
    with patch.object(auto_start, "_sync_enabled"):
        auto_start.remove_targets(app, ["pr-x"])
    msg_calls = [c for c in app.log_message.call_args_list
                 if "removed pr-x" in c.args[0]]
    assert msg_calls and msg_calls[0].kwargs.get("force") is True


# QA s2 (pr-0b87a97): "Auto-start: targets += X" / "ON (all …)" were
# overwritten in the same frame by the "starting X" / "Review loop
# started" (sticky) messages they trigger, so they never painted.

def test_hold_defers_followups_including_sticky_then_flushes_latest():
    app, shown = _stub_app()
    _log(app, "Auto-start: targets += pr-x (1 total)", force=True, hold=3)
    _log(app, "Auto-start: starting pr-x")
    _log(app, "Review loop started for pr-x", sticky=3)
    assert shown == [" Auto-start: targets += pr-x (1 total)"]
    app._log_hold_until = 0.0  # hold expires
    for cb in app.timers:
        cb()
    assert shown[-1] == " Review loop started for pr-x"
    assert app._log_sticky_until > time.monotonic()  # its sticky applies


def test_forced_message_shown_during_hold():
    app, shown = _stub_app()
    _log(app, "Auto-start: targets += pr-x (1 total)", force=True, hold=3)
    _log(app, "Auto-start: removed pr-x (auto-start OFF)", force=True)
    assert shown[-1] == " Auto-start: removed pr-x (auto-start OFF)"


def test_hidden_hold_message_does_not_hold_the_line():
    app, shown = _stub_app()
    _log(app, "Review loop done: PASS", sticky=10)
    _log(app, "held but hidden by the sticky", hold=3)
    assert app._log_hold_until == 0.0 and not app.timers
    app._log_sticky_until = 0.0  # sticky expires
    _log(app, "next message")
    assert shown[-1] == " next message"


def test_newer_hold_not_cut_short_by_older_timer():
    app, shown = _stub_app()
    _log(app, "Auto-start: targets += pr-x (1 total)", force=True, hold=3)
    _log(app, "Auto-start: targets += pr-y (2 total)", force=True, hold=3)
    _log(app, "chatter")
    app.timers[0]()  # first hold's timer fires; second hold still active
    assert shown[-1] == " Auto-start: targets += pr-y (2 total)"


def test_autostart_add_and_all_confirmations_hold():
    app = MagicMock()
    app._auto_start_targets = {}
    app._auto_start_all = False
    app._stop_before_merge = set()
    app._data = {"prs": [{"id": "pr-x", "status": "pending"}]}
    with patch.object(auto_start, "_sync_enabled"), \
            patch.object(auto_start, "check_and_start", MagicMock()):
        auto_start.add_targets(app, ["pr-x"])
        auto_start.enable_all(app)
    for needle in ("targets += pr-x", "ON (all ready PRs"):
        calls = [c for c in app.log_message.call_args_list
                 if needle in c.args[0]]
        assert calls and calls[0].kwargs.get("hold", 0) > 0, needle


def test_command_bar_status_popup_returns_focus_to_tree():
    # ``autostart status`` pushes the runs popup while the command bar has
    # focus; the tree must still be refocused so Esc lands on it.
    from pm_core.tui import pr_view
    app = MagicMock()
    app.screen_stack = [MagicMock(), MagicMock()]  # popup pushed
    tree = MagicMock()
    app.query_one.return_value = tree
    with patch.object(auto_start, "handle_command") as hc:
        pr_view.handle_command_submitted(app, "autostart status")
    hc.assert_called_once_with(app, ["status"])
    tree.focus.assert_called_once()


def test_starting_message_deferred_by_confirmation_hold(tmp_path):
    import asyncio
    app, shown = _stub_app()
    app._data = {"project": {"name": "t", "repo": "/r",
                             "base_branch": "master"},
                 "prs": [{"id": "pr-x", "title": "X", "status": "pending",
                          "branch": "b", "depends_on": []}]}
    app._root = tmp_path
    for attr, val in (("_auto_start", False), ("_auto_start_targets", {}),
                      ("_auto_start_all", False), ("_auto_start_run_id", None),
                      ("_auto_start_launching", set()),
                      ("_stop_before_merge", set()), ("_review_loops", {}),
                      ("_qa_loops", {}), ("_self_driving_qa", {}),
                      ("_pending_merge_prs", set()),
                      ("_merge_input_required_prs", set()),
                      ("_merge_propagation_phase", set()),
                      ("_session_name", None)):
        setattr(app, attr, val)
    app._watcher_manager = MagicMock()
    app._watcher_manager.find_by_type.return_value = None
    app._pane_idle_tracker = MagicMock()
    app._pane_idle_tracker.is_tracked.return_value = False
    app._update_display = app._load_state = lambda: None
    app.run_worker = lambda coro, *a, **k: coro.close()

    async def _noop(*a, **k):
        return None

    auto_start.add_targets(app, ["pr-x"], default_policy=None,
                           source="key:A")
    with patch("pm_core.tui.watcher_ui.is_running", return_value=False), \
            patch.object(auto_start, "_start_pr_quiet", _noop):
        asyncio.run(auto_start.check_and_start(app))
    assert shown[-1] == " Auto-start: targets += pr-x (1 total)"
    assert app._log_held[0] == "Auto-start: starting pr-x"
