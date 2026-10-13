"""L (view_log) must show recent log history, not just tail's default 10 lines.

Status-line messages are mirrored to the debug log as "log: ..." so a message
overwritten before it painted can be recovered with L; a bare ``tail -f``
starts at the last 10 lines, which the busy debug log pushes past in seconds.
Even with a 500-line backlog, an auto-start confirmation a minute old sits
hundreds of lines up (scrollback, not on screen), so the pane repeats the
last few "log: Auto-..." lines at the bottom before following.
"""

import subprocess
import time
from types import SimpleNamespace

from pm_core.tui import pane_ops


def test_view_log_launches_log_pane_command(tmp_path, monkeypatch):
    log = tmp_path / "tui.log"
    log.write_text("".join(f"line {i}\n" for i in range(50)))
    monkeypatch.setattr(pane_ops, "command_log_file", lambda: log)
    launched = []
    monkeypatch.setattr(pane_ops, "launch_pane",
                        lambda app, cmd, role, fresh=False: launched.append((cmd, role)))
    app = SimpleNamespace(_consume_z=lambda: False, log_message=lambda *a, **k: None)

    pane_ops.view_log(app)

    assert launched == [(pane_ops.log_pane_command(log), "log")]
    assert pane_ops.LOG_PANE_BACKLOG_LINES >= 100


def _run_pane(cmd: str) -> list[str]:
    """Run the pane command for ~1s (tail -f never exits) and return output."""
    proc = subprocess.Popen(["bash", "-c", cmd], stdout=subprocess.PIPE, text=True)
    try:
        out, _ = proc.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
    return out.splitlines()


def test_log_pane_shows_old_autostart_lines_at_bottom(tmp_path):
    log = tmp_path / "s 1.log"   # space: path must be quoted
    armed = ["01:00:00 INFO  [tui] log: Auto-sequence armed for pr-a (will stop before merge)",
             "01:00:09 INFO  [tui] log: Auto-sequence armed for pr-b (will stop before merge)"]
    lines = list(armed)
    # A minute of other activity: many status messages and debug noise.
    for i in range(700):
        lines.append(f"01:01:{i % 60:02d} INFO  [runtime_state] busy {i}")
        if i % 30 == 0:
            lines.append(f"01:01:{i % 60:02d} INFO  [tui] log: QA : Scenario {i} ready")
    log.write_text("\n".join(lines) + "\n")

    out = _run_pane(pane_ops.log_pane_command(log))

    # Backlog: the last 500 lines of history, then the recap at the bottom.
    assert out[:500] == lines[-500:]
    assert out[500:] == [
        "── recent auto-start messages ──",
        "01:00:00 log: Auto-sequence armed for pr-a (will stop before merge)",
        "01:00:09 log: Auto-sequence armed for pr-b (will stop before merge)",
        "── following log ──",
    ]


def test_log_pane_recap_keeps_last_autostart_lines(tmp_path):
    log = tmp_path / "tui.log"
    msgs = [f"01:00:{i:02d} INFO  [tui] log: Auto-start: targets += pr-{i} (stop)"
            for i in range(20)]
    log.write_text("\n".join(msgs + ["01:02:00 INFO  [tui] log: Review loop done"]) + "\n")

    out = _run_pane(pane_ops.log_pane_command(log))

    recap = out[out.index("── recent auto-start messages ──") + 1:
                out.index("── following log ──")]
    assert recap == [f"01:00:{i:02d} log: Auto-start: targets += pr-{i} (stop)"
                     for i in range(20 - pane_ops.LOG_PANE_RECAP_LINES, 20)]


def test_log_pane_follows_lines_appended_after_open(tmp_path):
    log = tmp_path / "tui.log"
    log.write_text("old 1\n01:00:00 INFO  [tui] log: Auto-start: removed pr-x\n")
    proc = subprocess.Popen(["bash", "-c", pane_ops.log_pane_command(log)],
                            stdout=subprocess.PIPE, text=True)
    time.sleep(0.4)
    with log.open("a") as fh:
        fh.write("new 1\n")
    time.sleep(1.5)
    proc.kill()
    out, _ = proc.communicate()
    assert out.splitlines() == [
        "old 1", "01:00:00 INFO  [tui] log: Auto-start: removed pr-x",
        "── recent auto-start messages ──", "01:00:00 log: Auto-start: removed pr-x",
        "── following log ──", "new 1"]
