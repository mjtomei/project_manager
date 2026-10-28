"""log_message: sticky messages hide plain ones, but not forced ones.

QA repro (pr-0b87a97 s3): ``pm autostart remove X`` landed while the
sticky "Review loop done … PASS" message was up, so the TUI never showed
"Auto-start: removed X (1 remaining)".
"""

import time
import pytest
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
    app._clear_log_message = (
        lambda seq=None: ProjectManagerApp._clear_log_message(app, seq=seq))
    app.clear_log_message_later = (
        lambda delay: ProjectManagerApp.clear_log_message_later(app, delay))
    return app, shown


def _log(app, msg, **kw):
    ProjectManagerApp.log_message(app, msg, **kw)


@pytest.mark.parametrize("verdict, expected", [
    ("PASS", "(1/2 consecutive) — restarting QA"),
    ("NEEDS_WORK", "returning to review"),
])
def test_qa_confirmation_visible_over_sticky_review(verdict, expected):
    from pm_core.qa_loop import QALoopState
    from pm_core.tui import qa_loop_ui

    app, shown = _stub_app()
    app._root = None
    app._review_loops = {}
    app._self_driving_qa = {"pr-001": {"pass_count": 0, "required_passes": 2}}
    _log(app, "Review loop done for pr-other: PASS", sticky=10)
    state = QALoopState(pr_id="pr-001", latest_verdict=verdict)

    def followup(*args):
        app.log_message("Starting follow-up")

    with patch.object(qa_loop_ui, "_record_qa_note"), \
         patch.object(qa_loop_ui, "_transition_pr_status"), \
         patch.object(qa_loop_ui, "start_qa", side_effect=followup), \
         patch.object(qa_loop_ui, "_start_self_driving_review", side_effect=followup):
        qa_loop_ui._on_qa_complete(app, state)

    assert expected in shown[-1]
    assert app._log_hold_until > time.monotonic()
    app._log_hold_until = 0.0  # the three-second confirmation hold expires
    app._flush_held_log_message()
    assert shown[-1] == " Starting follow-up"


def test_qa_loop_start_visible_during_autostart_confirmation():
    from pm_core.tui import qa_loop_ui

    app, shown = _stub_app()
    app._root = "/unused"
    app._qa_loops = {}
    app._self_driving_qa = {}
    _log(app, "Auto-start: already off", force=True, hold=3)
    with patch.object(qa_loop_ui.store, "load", return_value={}), \
         patch.object(qa_loop_ui.store, "get_pr", return_value={"id": "pr-001"}), \
         patch.object(qa_loop_ui, "_enter_qa_status", return_value=True), \
         patch.object(qa_loop_ui, "_ensure_poll_timer"), \
         patch.object(qa_loop_ui, "_get_qa_pass_count", return_value=3), \
         patch.object(qa_loop_ui, "start_qa_background"):
        qa_loop_ui.start_or_stop_qa_loop(app, "pr-001")
    assert "3 passes required" in shown[-1]
    _log(app, "Planning QA scenarios...")
    assert "3 passes required" in shown[-1]


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
    app._auto_start_targets = {"pr-x": {"wait_for_merge": True},
                               "pr-y": {"wait_for_merge": True}}
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


# QA s22 (pr-0b87a97): a "Selected: X" deferred by a confirmation hold
# was flushed when the hold ended, wiping the newer forced answer to a
# command-bar `autostart list` / bare `autostart` typed inside the hold.

def test_newer_forced_message_drops_older_deferred_one():
    app, shown = _stub_app()
    _log(app, "Auto-start: targets += pr-x (1 total)", force=True, hold=3)
    _log(app, "Selected: pr-y")  # deferred by the hold
    _log(app, "Auto-start targets: pr-x (stop)", force=True)
    app._log_hold_until = 0.0  # hold expires
    for cb in app.timers:
        cb()
    assert shown[-1] == " Auto-start targets: pr-x (stop)"


def test_message_deferred_after_forced_one_still_flushes():
    app, shown = _stub_app()
    _log(app, "Auto-start: targets += pr-x (1 total)", force=True, hold=3)
    _log(app, "Auto-start targets: pr-x (stop)", force=True)
    _log(app, "Selected: pr-y")  # newer than the forced message
    app._log_hold_until = 0.0
    for cb in app.timers:
        cb()
    assert shown[-1] == " Selected: pr-y"


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
    assert shown[-1] == " Auto-start: targets += pr-x (1 total)"
    app._log_hold_until = 0.0  # first hold expires
    app.timers[0]()  # → the queued second confirmation, with its own hold
    assert shown[-1] == " Auto-start: targets += pr-y (2 total)"
    app.timers[0]()  # the first hold's timer again: second hold still active
    assert shown[-1] == " Auto-start: targets += pr-y (2 total)"
    app._log_hold_until = 0.0
    app.timers[1]()
    assert shown[-1] == " chatter"


def test_autostart_add_and_all_confirmations_hold():
    app = MagicMock()
    app._auto_start_targets = {}
    app._auto_start_all = False
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
                      ("_review_loops", {}),
                      ("_qa_loops", {}), ("_self_driving_qa", {}),
                      ("_pending_merge_prs", set()),
                      ("_merge_input_required_prs", set()),
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


# QA s13 (pr-0b87a97): ``g`` on a wait-for-merge target — the merge's
# own reload pruned the target and logged "target Y merged — removed", but
# the "Merging Y..." spinner (0.1s ticks) and the merge's result line
# overwrote it before it painted.

def test_merged_target_message_survives_merge_spinner():
    app, shown = _stub_app()
    app._auto_start_targets = {"pr-y": {"wait_for_merge": True},
                               "pr-t": {"wait_for_merge": True}}
    app._auto_start_all = False
    _log(app, "⠋ Merging pr-y...", capture=False)
    with patch.object(auto_start, "_sync_enabled"):
        auto_start._prune_completed_targets(
            app, [{"id": "pr-y", "status": "merged"},
                  {"id": "pr-t", "status": "qa"}])
    _log(app, "⠙ Merging pr-y...", capture=False)
    _log(app, "⏳ pr-z: Independent Z")  # merge's last stdout line
    assert shown[-1] == " Auto-start: target pr-y merged — removed (1 remaining)"
    app._log_hold_until = 0.0  # hold expires
    for cb in app.timers:
        cb()
    assert shown[-1] == " ⏳ pr-z: Independent Z"


def test_last_merged_target_one_line_with_off():
    # A separate "all targets complete — OFF" line overwrote the merged
    # line in the same frame; the last completion is now one message.
    app, shown = _stub_app()
    app._auto_start_targets = {"pr-y": {"wait_for_merge": True}}
    app._auto_start_all = False
    with patch.object(auto_start, "_disable") as disable:
        auto_start._prune_completed_targets(
            app, [{"id": "pr-y", "status": "merged"}])
    disable.assert_called_once()
    _log(app, "⠙ Merging pr-y...", capture=False)
    assert shown == [" Auto-start: target pr-y merged — removed "
                     "(all targets complete — auto-start OFF)"]


# QA s18 (pr-0b87a97): ``pm autostart remove Y2`` racing a TUI ``g`` merge
# painted "Auto-start: removed …" for ~0.1s before the "⠙ Merging …"
# spinner frame overwrote it.

def test_autostart_remove_and_clear_confirmations_hold():
    app = MagicMock()
    app._auto_start_targets = {"pr-x": {"wait_for_merge": True},
                               "pr-y": {"wait_for_merge": True}}
    app._auto_start_all = False
    app._data = {"prs": [{"id": "pr-x"}, {"id": "pr-y"}]}
    with patch.object(auto_start, "_sync_enabled"), \
            patch.object(auto_start, "is_enabled", return_value=True), \
            patch.object(auto_start, "_disable"):
        auto_start.remove_targets(app, ["pr-x"])
        auto_start.remove_targets(app, ["pr-x"])  # now not a target
        auto_start.clear_targets(app)
    for needle in ("removed pr-x", "pr-x not a target", "Auto-start: OFF"):
        calls = [c for c in app.log_message.call_args_list
                 if needle in c.args[0]]
        assert calls and calls[0].kwargs.get("hold", 0) > 0, needle
        assert calls[0].kwargs.get("force") is True, needle


def test_remove_confirmation_survives_merge_spinner():
    app, shown = _stub_app()
    _log(app, "⠋ Merging pr-d2...")
    _log(app, "Auto-start: removed pr-y2 (3 remaining)", force=True, hold=3)
    _log(app, "⠙ Merging pr-d2...")
    _log(app, "⏳ pr-y2: Y2")
    assert shown[-1] == " Auto-start: removed pr-y2 (3 remaining)"
    app._log_hold_until = 0.0  # hold expires
    for cb in app.timers:
        cb()
    assert shown[-1] == " ⏳ pr-y2: Y2"


# QA s23 (pr-0b87a97): ``pm autostart remove Z`` (not a target) racing a TUI
# ``g`` merge of target W painted "Auto-start: Z not a target" for ~0.1s:
# W's held "target W merged — removed" prune line replaced it at once,
# because a held message never waited for another hold to end.

def test_held_confirmation_not_replaced_by_next_held_line():
    app, shown = _stub_app()
    app._auto_start_targets = {"pr-w": {"wait_for_merge": True},
                               "pr-t": {"wait_for_merge": True}}
    app._auto_start_all = False
    _log(app, "⠋ Merging pr-w...", capture=False)
    _log(app, "Auto-start: pr-z not a target", force=True, hold=3)
    with patch.object(auto_start, "_sync_enabled"):
        auto_start._prune_completed_targets(
            app, [{"id": "pr-w", "status": "merged"},
                  {"id": "pr-t", "status": "qa"}])
    _log(app, "⠙ Merging pr-w...", capture=False)
    _log(app, "⏳ pr-z: Z")  # merge's last stdout line
    assert shown[-1] == " Auto-start: pr-z not a target"
    app._log_hold_until = 0.0  # not-a-target hold expires
    app.timers[0]()
    assert shown[-1] == (" Auto-start: target pr-w merged — removed "
                         "(1 remaining)")
    app._log_hold_until = 0.0  # merged-line hold expires
    app.timers[-1]()
    assert shown[-1] == " ⏳ pr-z: Z"


def test_queued_held_message_hidden_by_sticky_does_not_stall_queue():
    app, shown = _stub_app()
    _log(app, "Auto-start: targets += pr-x (1 total)", force=True, hold=3)
    _log(app, "unforced held", hold=3)  # queued
    _log(app, "Auto-start: removed pr-x (0 remaining)", force=True, hold=3)
    _log(app, "chatter")
    app._log_hold_until = 0.0
    app._log_sticky_until = time.monotonic() + 10  # a sticky took the line
    app.timers[0]()  # unforced queued one is hidden; the forced one shows
    assert shown[-1] == " Auto-start: removed pr-x (0 remaining)"
    app._log_sticky_until = 0.0
    app._log_hold_until = 0.0
    app.timers[-1]()
    assert shown[-1] == " chatter"


def test_held_queue_is_bounded():
    from pm_core.tui import app as app_mod
    app, shown = _stub_app()
    _log(app, "first", force=True, hold=3)
    for i in range(app_mod._LOG_HELD_QUEUE_MAX + 2):
        _log(app, f"queued {i}", force=True, hold=3)
    assert len(app._log_held_queue) == app_mod._LOG_HELD_QUEUE_MAX
    assert app._log_held_queue[-1][0] == (
        f"queued {app_mod._LOG_HELD_QUEUE_MAX + 1}")


# Integration of the s23 queue with s22's "newer shown message drops older
# deferred ones" (9caf9baf): flushing an older queued confirmation must not
# drop a message deferred after it, and an error's auto-clear timer must not
# blank a newer confirmation.

def test_flushed_older_confirmation_keeps_newer_deferred_message():
    app, shown = _stub_app()
    _log(app, "Auto-start: pr-z not a target", force=True, hold=3)
    _log(app, "Auto-start: target pr-w merged — removed (1 remaining)",
         force=True, hold=3)  # queued
    _log(app, "⏳ pr-z: Z")  # deferred; newer than the queued line
    app._log_hold_until = 0.0
    app.timers[0]()
    assert shown[-1] == " Auto-start: target pr-w merged — removed (1 remaining)"
    app._log_hold_until = 0.0
    app.timers[-1]()
    assert shown[-1] == " ⏳ pr-z: Z"


def test_newer_forced_message_drops_older_queued_confirmation():
    app, shown = _stub_app()
    _log(app, "Auto-start: targets += pr-x (1 total)", force=True, hold=3)
    _log(app, "Auto-start: targets += pr-y (2 total)", force=True, hold=3)
    _log(app, "Auto-start targets: pr-x, pr-y", force=True)  # cmd-bar answer
    app._log_hold_until = 0.0
    for cb in list(app.timers):
        cb()
    assert shown[-1] == " Auto-start targets: pr-x, pr-y"


def test_error_timeout_does_not_blank_newer_held_confirmation():
    app, shown = _stub_app()
    ProjectManagerApp.log_error(app, "Error:", "merge failed", timeout=5)
    clear_error = app.timers[-1]
    _log(app, "Auto-start: removed pr-y (1 remaining)", force=True, hold=3)
    clear_error()  # the error's 5s timer fires while the confirmation shows
    assert shown[-1] == " Auto-start: removed pr-y (1 remaining)"


def test_error_timeout_still_clears_its_own_error():
    app, shown = _stub_app()
    ProjectManagerApp.log_error(app, "Error:", "merge failed", timeout=5)
    app.timers[-1]()
    assert shown[-1] == ""
    assert app._log_sticky_until == 0.0


def test_error_expiring_behind_a_hold_is_not_shown_late():
    app, shown = _stub_app()
    _log(app, "Auto-start: targets += pr-x (1 total)", force=True, hold=3)
    ProjectManagerApp.log_error(app, "Error:", "stale", timeout=1)  # deferred
    app.timers[-1]()  # the error's timer fires before the hold ends
    app._log_hold_until = 0.0
    app.timers[0]()
    assert shown[-1] == " Auto-start: targets += pr-x (1 total)"


# Review 4be9 (pr-0b87a97): the manual-refresh / GitHub-sync clear timers
# blanked the line unconditionally, so a held prune line from the
# check_and_start that the refresh itself ran ("target W merged — removed")
# vanished after 1s, and "Refreshed" then painted when the hold ended.

def test_refresh_clear_timer_does_not_blank_held_prune_line():
    app, shown = _stub_app()
    _log(app, "Auto-start: target pr-w merged — removed (1 remaining)",
         force=True, hold=3)
    _log(app, "Refreshed")  # deferred by the hold
    app.clear_log_message_later(1.0)
    app.timers[-1]()  # the 1s refresh clear fires inside the hold
    assert shown[-1] == (" Auto-start: target pr-w merged — removed "
                         "(1 remaining)")
    app._log_hold_until = 0.0
    app.timers[0]()  # hold ends: the expired "Refreshed" is not shown late
    assert shown[-1] == (" Auto-start: target pr-w merged — removed "
                         "(1 remaining)")


def test_refresh_clear_timer_clears_its_own_message():
    app, shown = _stub_app()
    _log(app, "Refreshed")
    app.clear_log_message_later(1.0)
    app.timers[-1]()
    assert shown[-1] == ""


# Review 4be9 i2: the sync clear timers captured "the latest" message when
# scheduled — after an awaited check_and_start that is its held prune line,
# so the sync's own 1s/2s clear cut that 3s line short.  They are now bound
# to the sync's own message (log_message returns its arrival number).

_PRUNE = "Auto-start: target pr-w merged — removed (1 remaining)"


def _sync_app(tmp_path, backend):
    app, shown = _stub_app()
    app._root = tmp_path
    app._data = {"project": {"name": "p", "backend": backend},
                 "prs": [{"id": "pr-w", "status": "qa"}]}
    app._update_display = lambda: None
    app._update_status_bar = lambda **k: None
    app.clear_log_message_later = (
        lambda delay, **kw: ProjectManagerApp.clear_log_message_later(
            app, delay, **kw))
    app.delays = []

    def set_timer(delay, cb):
        app.delays.append(delay)
        app.timers.append(cb)
    app.set_timer = set_timer
    return app, shown


async def _prune_check_and_start(app):
    _log(app, _PRUNE, force=True, hold=3)


def _merge_all(root, fn):
    data = {"project": {}, "prs": [{"id": "pr-w", "status": "qa"}]}
    fn(data)
    return data


def test_github_sync_clear_does_not_cut_short_held_prune_line(tmp_path):
    import asyncio
    from pm_core import pr_sync
    from pm_core.tui import sync
    app, shown = _sync_app(tmp_path, "github")
    result = SimpleNamespace(synced=True, updated_count=1, error=None,
                             status_updates={"pr-w": "merged"})
    with patch.object(pr_sync, "sync_from_github", lambda *a, **k: result), \
            patch.object(sync.store, "locked_update", _merge_all), \
            patch.object(sync, "_kill_merged_pr_windows"), \
            patch.object(auto_start, "check_and_start",
                         _prune_check_and_start):
        asyncio.run(sync.startup_github_sync(app))
    assert shown[-1] == f" {_PRUNE}"
    assert app.delays == [3, 2.0]
    app.timers[-1]()  # the sync's 2s clear fires inside the 3s hold
    assert shown[-1] == f" {_PRUNE}"


def test_manual_refresh_clear_does_not_cut_short_held_prune_line(tmp_path):
    import asyncio
    from pm_core import pr_sync
    from pm_core.tui import sync
    app, shown = _sync_app(tmp_path, "vanilla")
    app.log_message("Refreshing...")
    result = SimpleNamespace(merged_prs=["pr-w"], was_skipped=False,
                             error="No workdirs", updated_count=0)
    with patch.object(pr_sync, "sync_prs", lambda *a, **k: result), \
            patch.object(sync.store, "locked_update", _merge_all), \
            patch.object(sync, "_kill_merged_pr_windows"), \
            patch.object(auto_start, "check_and_start",
                         _prune_check_and_start):
        asyncio.run(sync.do_normal_sync(app, is_manual=True))
    assert shown[-1] == f" {_PRUNE}"  # "Refreshed" waits behind the hold
    assert app.delays == [3, 1.0]
    app.timers[-1]()  # the 1s refresh clear fires inside the hold
    assert shown[-1] == f" {_PRUNE}"
    app._log_hold_until = 0.0
    app.timers[0]()  # hold ends: the expired "Refreshed" is not shown late
    assert shown[-1] == f" {_PRUNE}"


# Review 4be9 i3: the w/y prefix auto-cancel timers (2s) cleared the log
# line unconditionally, blanking a held confirmation from a CLI command
# that landed while the prefix hint was up.

def _prefix_app():
    app, shown = _stub_app()
    app._w_mode = True
    app._clear_prefix_hint = (
        lambda: ProjectManagerApp._clear_prefix_hint(app))
    app._prefix_hint_seq = app.log_message("[bold]w …[/]")
    return app, shown


def test_prefix_timeout_does_not_blank_newer_confirmation():
    app, shown = _prefix_app()
    _log(app, "Auto-start: removed pr-y (1 remaining)", force=True, hold=3)
    ProjectManagerApp._cancel_w_mode(app)  # the 2s w timer fires
    assert app._w_mode is False
    assert shown[-1] == " Auto-start: removed pr-y (1 remaining)"


def test_prefix_timeout_clears_its_own_hint():
    app, shown = _prefix_app()
    ProjectManagerApp._cancel_w_mode(app)
    assert shown[-1] == ""


# QA s1 (pr-f094946): ``L`` pressed as auto-QA started landed inside the
# sticky "Review loop done … PASS" window, so the log pane opened but the
# TUI never showed "Launched log pane".

def test_launch_pane_confirmation_shown_while_sticky(monkeypatch):
    from pm_core.tui import pane_ops
    app, shown = _stub_app()
    _log(app, "Review loop done: PASS", sticky=10)
    monkeypatch.setattr(pane_ops, "get_session_and_window",
                        lambda a: ("sess", "@0"))
    monkeypatch.setattr(pane_ops.pane_registry, "find_live_pane_by_role",
                        lambda *a, **k: None)
    monkeypatch.setattr(pane_ops.pane_registry, "load_registry",
                        lambda s: {"generation": "1"})
    monkeypatch.setattr(pane_ops.pane_layout, "preferred_split_direction",
                        lambda *a: "h")
    monkeypatch.setattr(pane_ops.pane_layout, "register_and_rebalance",
                        lambda *a: None)
    monkeypatch.setattr(pane_ops.tmux_mod, "split_pane", lambda *a, **k: "%8")
    monkeypatch.setattr(pane_ops.tmux_mod, "select_pane_smart",
                        lambda *a: None)
    pane_ops.launch_pane(app, "tail -f log", "log")
    assert shown[-1] == " Launched log pane"
    monkeypatch.setattr(pane_ops.pane_registry, "find_live_pane_by_role",
                        lambda *a, **k: "%8")
    pane_ops.launch_pane(app, "tail -f log", "log")
    assert shown[-1] == " Focused existing log pane"


def test_new_plan_pane_confirmation_shown_while_sticky():
    from pm_core.tui import pane_ops

    app, shown = _stub_app()
    app._root = "/unused"
    _log(app, "Review loop done: PASS", sticky=10)
    with patch.object(pane_ops.tmux_mod, "in_tmux", return_value=True), \
         patch.object(pane_ops.tmux_mod, "get_session_name", return_value="sess"), \
         patch.object(pane_ops.tmux_mod, "find_window_by_name",
                      side_effect=[None, {"id": "@8"}]), \
         patch.object(pane_ops.tmux_mod, "new_window_get_pane", return_value="%8"), \
         patch.object(pane_ops, "_wrap_pane_cmd", return_value="wrapped"), \
         patch.object(pane_ops.pane_layout, "register_and_rebalance") as register, \
         patch.object(pane_ops, "_focus_plans_window") as focus:
        pane_ops._launch_in_plans_window(app, "plan-001", "less plan.md", "plan")

    register.assert_called_once_with(
        "sess", "@8", [("%8", "plan", "less plan.md")])
    focus.assert_called_once_with(app, "plan-001")
    assert shown[-1] == " Launched plan pane"


# QA s22 (pr-f094946): a user `t` landing in the gap where a background QA
# run is accepted but has no window yet answers "QA already running for X".
# Auto-start's "targets += X" confirmation holds the log line, so the answer
# was dropped and never painted.

def test_qa_already_running_visible_during_autostart_confirmation():
    from pm_core.tui import qa_loop_ui

    app, shown = _stub_app()
    app._root = "/unused"
    state = SimpleNamespace(running=True, focus_on_create=False)
    app._qa_loops = {"pr-001": state}
    _log(app, "Auto-start: targets += pr-001 (1 total)", force=True, hold=3)
    with patch.object(qa_loop_ui.store, "load", return_value={}), \
         patch.object(qa_loop_ui.store, "get_pr",
                      return_value={"id": "pr-001", "status": "qa"}):
        qa_loop_ui.start_qa(app, "pr-001", focus=True)
    assert shown[-1] == " QA already running for pr-001"
    assert state.focus_on_create is True


def test_focus_suppressed_answer_visible_over_sticky():
    from pm_core.tui import qa_loop_ui

    app, shown = _stub_app()
    app._root = "/unused"
    _log(app, "Auto-start: targets += pr-001 (1 total)", force=True, hold=3)
    with patch.object(qa_loop_ui.store, "load", return_value={}), \
         patch.object(qa_loop_ui.store, "get_pr",
                      return_value={"id": "pr-001", "status": "qa"}), \
         patch.object(qa_loop_ui, "get_pm_session", return_value="pm-x"), \
         patch("pm_core.tmux.find_window_by_name", return_value="@3"), \
         patch("pm_core.runtime_state.consume_suppress_switch",
               return_value=True):
        qa_loop_ui.focus_or_start_qa(app, "pr-001")
    assert shown[-1] == " QA window for pr-001 ready (focus suppressed)"
