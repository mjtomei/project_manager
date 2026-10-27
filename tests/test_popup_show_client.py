"""prefix+P / prefix+M popups act on the client that pressed the key.

``_popup-show`` runs from ``run-shell`` and popup commands run in a popup;
neither has a pane, so bare tmux queries resolve to the most recently
active client.  With two clients at once, both popups landed on the same
client, and a picker action in one client switched the other client's
window.  The bindings now pass the pressing client and session,
``_popup-show`` targets them explicitly, and the popup dispatchers export
the session for ``tmux.get_session_name``.
"""

import subprocess
from unittest import mock

from click.testing import CliRunner

from pm_core import tmux as tmux_mod
from pm_core.cli import session as session_mod
from pm_core.cli.session import _bind_popups, popup_cmd_cmd, popup_show_cmd

CLIENT = "/dev/pts/7"
SESSION = "pm-demo-c5a1006b~1"


def _fake_tmux(calls):
    def run(cmd, **kwargs):
        calls.append(cmd)
        out = ""
        if "display-message" in cmd:
            fmt = cmd[-1]
            out = {"#{window_width}": "160\n",
                   "#{pane_current_path}": "/work/pr-a\n",
                   "#{window_name}": "pr-a$b\n"}.get(fmt, "")
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    return run


def _invoke(args):
    calls = []
    with mock.patch.object(session_mod.subprocess, "run", _fake_tmux(calls)), \
         mock.patch.object(session_mod.pane_layout,
                           "_get_mobile_width_threshold", return_value=110):
        result = CliRunner().invoke(popup_show_cmd, args)
    assert result.exit_code == 0, result.output
    return calls


def test_bindings_pass_pressing_client_and_session():
    calls = []
    with mock.patch.object(session_mod.subprocess, "run", _fake_tmux(calls)):
        _bind_popups()
    shell_cmds = [c[-1] for c in calls]
    assert ("pm _popup-show picker #{q:client_name} #{q:session_name}"
            in shell_cmds)
    assert "pm _popup-show cmd #{q:client_name} #{q:session_name}" in shell_cmds


def test_popup_targets_pressing_client_and_session_window():
    calls = _invoke(["picker", CLIENT, SESSION])
    queries = [c for c in calls if "display-message" in c]
    assert queries and all(f"={SESSION}:" in c for c in queries)
    popup = next(c for c in calls if "display-popup" in c)
    assert popup[popup.index("-c") + 1] == CLIENT
    assert popup[popup.index("-t") + 1] == f"={SESSION}:"
    assert popup[popup.index("-d") + 1] == "/work/pr-a"
    body = popup[-1]
    # S and W are pinned to the pressing client's session/window rather
    # than re-queried from inside the popup.
    assert "S='pm-demo-c5a1006b~1';" in body
    assert "W='pr-a$b';" in body
    assert "display-message" not in body


def test_popup_without_client_args_keeps_old_resolution():
    calls = _invoke(["cmd"])
    popup = next(c for c in calls if "display-popup" in c)
    assert "-c" not in popup and "-t" not in popup
    assert popup[-1] == session_mod._POPUP_CMD_BODY


def test_get_session_name_uses_popup_session_without_pane(monkeypatch):
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv(tmux_mod.POPUP_SESSION_ENV, SESSION)
    alive = subprocess.CompletedProcess([], 0, stdout="")
    with mock.patch.object(tmux_mod, "_run", return_value=alive) as run:
        assert tmux_mod.get_session_name() == SESSION
    # Only the has-session liveness check; no current-client query.
    run.assert_called_once()
    assert "has-session" in run.call_args[0][0]


def test_get_session_name_prefers_pane(monkeypatch):
    monkeypatch.setenv("TMUX_PANE", "%5")
    monkeypatch.setenv(tmux_mod.POPUP_SESSION_ENV, SESSION)
    done = subprocess.CompletedProcess([], 0, stdout="pm-demo-c5a1006b~3\n")
    with mock.patch.object(tmux_mod, "_run", return_value=done) as run:
        assert tmux_mod.get_session_name() == "pm-demo-c5a1006b~3"
    assert "%5" in run.call_args[0][0]


def test_popup_cmd_exports_session(tmp_path, monkeypatch):
    # setenv (not delenv) so monkeypatch removes the exported value after.
    monkeypatch.setenv(tmux_mod.POPUP_SESSION_ENV, "stale")
    reg = tmp_path / "reg.json"
    reg.write_text("{}")
    monkeypatch.setattr(session_mod.pane_registry, "registry_path",
                        lambda base: reg)
    monkeypatch.setattr(session_mod, "_resolve_root_from_session",
                        lambda s: None)
    # Empty input closes the runner right after the export.
    CliRunner().invoke(popup_cmd_cmd, [SESSION], input="\n")
    assert session_mod.os.environ[tmux_mod.POPUP_SESSION_ENV] == SESSION


def test_popup_pins_session_when_window_query_fails():
    """A failed #{window_name} query still pins S; W falls back to a query."""
    calls = []
    inner = _fake_tmux(calls)

    def run(cmd, **kwargs):
        if "#{window_name}" in cmd:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        return inner(cmd, **kwargs)

    with mock.patch.object(session_mod.subprocess, "run", run), \
         mock.patch.object(session_mod.pane_layout,
                           "_get_mobile_width_threshold", return_value=110):
        result = CliRunner().invoke(popup_show_cmd, ["picker", CLIENT, SESSION])
    assert result.exit_code == 0, result.output
    body = next(c for c in calls if "display-popup" in c)[-1]
    assert "S='pm-demo-c5a1006b~1';" in body
    assert session_mod._POPUP_BODY_W in body


def test_failure_handler_reports_status_and_waits_under_posix_sh():
    """tmux 3.2 runs popup bodies with /bin/sh (dash on Debian/Ubuntu).

    bash's ``read -n 1 -s -p`` made dash exit at once, so the popup closed
    before the failure could be read, and ``$?`` was read after an echo
    had reset it to 0.
    """
    body = "sh -c 'exit 3'" + session_mod._POPUP_FAILURE_HANDLER + "; echo AFTER"
    proc = subprocess.run(["/bin/sh", "-c", body], input="x", text=True,
                          capture_output=True, timeout=10)
    assert "pm popup failed (exit 3)." in proc.stdout
    assert "Press any key to close..." in proc.stdout
    assert "Illegal option" not in proc.stderr
    # The single key was consumed by the wait before the body continued.
    assert proc.stdout.rstrip().endswith("AFTER")


def test_failure_handler_skipped_on_success():
    body = "true" + session_mod._POPUP_FAILURE_HANDLER
    proc = subprocess.run(["/bin/sh", "-c", body], input="", text=True,
                          capture_output=True, timeout=10)
    assert proc.stdout == ""
