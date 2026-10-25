"""pr_view.run_command shows the command's output as text, not markup.

QA S53 story 3 (pr-592e4bd): ``i`` on a routed PR whose work sign-in had
expired painted "Error: … so /tmp/s53/creds/work-creds.json holds a valid
session …": the credentials path was ``/tmp/s53/creds[work]/work-creds.json``
and Rich read ``[work]`` as a style tag and dropped it.  The sign-off driver
and auto-start already escaped their copies of the same reason.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from rich.text import Text

from pm_core.tui import pr_view

REASON = ("work route 'claude-work' unavailable: account sign-in expired at "
          "2026-10-25 00:46 UTC. Remedy: sign in to that account again so "
          "/tmp/s53/creds[work]/work-creds.json holds a valid session; then "
          "launch the signoff session again")


def _app(tmp_path):
    logs = []
    app = SimpleNamespace(_root=tmp_path, _inflight_pr_action=None,
                          log_message=lambda msg, **kw: logs.append(msg),
                          set_timer=lambda *a, **k: None,
                          _load_state=lambda: None)
    return app, logs


def _plain(logs):
    return [Text.from_markup(m).plain for m in logs]


def test_sync_command_error_keeps_brackets(tmp_path):
    app, logs = _app(tmp_path)
    result = SimpleNamespace(returncode=1, stdout="PR [x] in [/tmp/a]\n",
                             stderr=f"Traceback ...\n{REASON}\n")
    with patch.object(pr_view, "_run_shell", return_value=result):
        pr_view._run_command_sync(app, ["pr", "signoff", "pr-x"])
    assert _plain(logs) == ["PR [x] in [/tmp/a]", f"Error: {REASON}"]


def test_async_command_error_keeps_brackets(tmp_path):
    app, logs = _app(tmp_path)

    class Proc:
        returncode = 1

        async def communicate(self):
            return b"Work directory: /tmp/w[work]\n", f"{REASON}\n".encode()

    async def fake_shell(*a, **k):
        return Proc()

    with patch.object(pr_view, "_run_shell_async", fake_shell):
        asyncio.run(pr_view._run_command_async(
            app, "pr signoff pr-x", ["pr", "signoff", "pr-x"], "Sign-off"))
    out = [p for p in _plain(logs) if "Sign-off..." not in p]
    assert out == ["Work directory: /tmp/w[work]", f"Error: {REASON}"]


def test_typed_command_echo_keeps_brackets(tmp_path):
    """The "> <cmd>" echo of a typed command is text as well: a note naming
    ``creds[work]`` lost ``[work]``, and a ``[/x]`` refused the line."""
    from textual.content import Content

    app, logs = _app(tmp_path)
    cmd = "pr note add pr-x 'see creds[work] and [/x]'"
    result = SimpleNamespace(returncode=0, stdout="", stderr="")
    with patch.object(pr_view, "_run_shell", return_value=result):
        pr_view.run_command(app, cmd)
    # The log line is a Textual widget: check with Textual's own parser.
    assert Content.from_markup(logs[0]).plain == f"> {cmd}"


def test_command_exception_keeps_brackets(tmp_path):
    app, logs = _app(tmp_path)

    async def fake_shell(*a, **k):
        raise OSError("cannot run [/usr/bin/python3]")

    with patch.object(pr_view, "_run_shell_async", fake_shell):
        asyncio.run(pr_view._run_command_async(
            app, "pr start pr-x", ["pr", "start", "pr-x"], "Starting"))
    assert _plain(logs)[-1] == "Error: cannot run [/usr/bin/python3]"
    with patch.object(pr_view, "_run_shell",
                      side_effect=OSError("cannot run [/x]")):
        pr_view._run_command_sync(app, ["pr", "start", "pr-x"])
    assert _plain(logs)[-1] == "Error: cannot run [/x]"
