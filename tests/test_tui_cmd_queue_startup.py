"""External command queue across TUI restarts (QA pr-0b87a97 s5).

Commands queued while the TUI restarts must neither be dispatched before
the breadcrumb restore (which would overwrite their effect) nor sit in the
queue until some later, unrelated SIGUSR2 replays them.
"""

import os
import signal
import time
from unittest.mock import MagicMock, patch

import pytest

from pm_core.tui.app import ProjectManagerApp, _STARTUP_QUEUE_MAX_AGE


def _app(tmp_path):
    app = ProjectManagerApp.__new__(ProjectManagerApp)
    app._session_name = "pm-test"
    app._cmd_queue_ready = False
    queue = tmp_path / "tui-pm-test.cmd-queue"
    app._command_queue_file = lambda: queue
    return app, queue


def test_drain_deferred_until_startup_ready(tmp_path):
    app, queue = _app(tmp_path)
    queue.write_text("autostart add pr-z --reply r1\n")
    with patch("pm_core.tui.pr_view.handle_command_submitted") as handle:
        app._drain_command_queue()
    handle.assert_not_called()
    assert queue.read_text() == "autostart add pr-z --reply r1\n"


def test_startup_drain_dispatches_queued_commands_in_order(tmp_path):
    app, queue = _app(tmp_path)
    queue.write_text("autostart status --reply r1\nautostart add pr-z --reply r2\n")
    app._cmd_queue_ready = True
    with patch("pm_core.tui.pr_view.handle_command_submitted") as handle:
        app._drain_command_queue(startup=True)
    assert [c.args[1] for c in handle.call_args_list] == [
        "autostart status --reply r1", "autostart add pr-z --reply r2"]
    assert queue.read_text() == ""


def test_startup_drain_discards_stale_queue(tmp_path):
    app, queue = _app(tmp_path)
    queue.write_text("autostart add pr-z --reply r1\n")
    old = time.time() - _STARTUP_QUEUE_MAX_AGE - 5
    os.utime(queue, (old, old))
    app._cmd_queue_ready = True
    with patch("pm_core.tui.pr_view.handle_command_submitted") as handle:
        app._drain_command_queue(startup=True)
    handle.assert_not_called()
    assert queue.read_text() == ""


def test_restart_app_ignores_ipc_signals_across_exec():
    """A SIGUSR2 landing between execvp and the new TUI's handler install
    must not kill the TUI (default action is terminate)."""
    from pm_core.tui import pane_ops

    seen = {}

    def fake_exec(*_a):
        seen["usr1"] = signal.getsignal(signal.SIGUSR1)
        seen["usr2"] = signal.getsignal(signal.SIGUSR2)
        raise SystemExit

    prev = {s: signal.getsignal(s) for s in (signal.SIGUSR1, signal.SIGUSR2)}
    try:
        with patch("os.execvp", side_effect=fake_exec):
            with pytest.raises(SystemExit):
                pane_ops.restart_app(MagicMock())
    finally:
        for s, h in prev.items():
            signal.signal(s, h)
    assert seen == {"usr1": signal.SIG_IGN, "usr2": signal.SIG_IGN}
