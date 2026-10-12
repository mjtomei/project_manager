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
        query_one=lambda *a, **k: SimpleNamespace(update=shown.append),
        call_after_refresh=lambda *a, **k: None,
        _capture_frame=None,
    )
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
