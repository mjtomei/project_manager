"""L (view_log) must show recent log history, not just tail's default 10 lines.

Status-line messages are mirrored to the debug log as "log: ..." so a message
overwritten before it painted can be recovered with L; a bare ``tail -f``
starts at the last 10 lines, which the busy debug log pushes past in seconds.
"""

from types import SimpleNamespace

from pm_core.tui import pane_ops


def test_view_log_tails_backlog(tmp_path, monkeypatch):
    log = tmp_path / "tui.log"
    log.write_text("".join(f"line {i}\n" for i in range(50)))
    monkeypatch.setattr(pane_ops, "command_log_file", lambda: log)
    launched = []
    monkeypatch.setattr(pane_ops, "launch_pane",
                        lambda app, cmd, role, fresh=False: launched.append((cmd, role)))
    app = SimpleNamespace(_consume_z=lambda: False, log_message=lambda *a, **k: None)

    pane_ops.view_log(app)

    assert launched == [
        (f"tail -n {pane_ops.LOG_PANE_BACKLOG_LINES} -f {log}", "log")]
    assert pane_ops.LOG_PANE_BACKLOG_LINES >= 100
