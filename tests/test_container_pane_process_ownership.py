"""Pane start commands do not describe execs launched later by their shells."""
import subprocess
import sys
import pytest

from pm_core import container_reaper as reaper

NAME = "pm-project-a-qa-pr-1234567-loop-s1"
CID = "a" * 64


def _snapshot(monkeypatch, tmp_path, panes, processes, ps_rc=0):
    socket = tmp_path / "tmux.sock"
    socket.touch()
    server = reaper._server_for_socket(str(socket))

    def run(args, **kwargs):
        assert kwargs["timeout"] <= 5
        if args[0] == "tmux":
            return subprocess.CompletedProcess(args, 0, panes, "")
        assert args[0] == "ps"
        return subprocess.CompletedProcess(args, ps_rc, processes, "process query failed")

    monkeypatch.setattr(reaper.subprocess, "run", run)
    monkeypatch.setattr(reaper, "_servers_for", lambda _: [server])
    monkeypatch.setattr(reaper.container_mod, "activity_owner", lambda *a: False)
    return reaper.ContainerInfo(name=NAME, id=CID)


@pytest.mark.parametrize("target", [NAME, CID])
def test_exec_below_existing_shell_owns_pane(monkeypatch, tmp_path, target):
    info = _snapshot(monkeypatch, tmp_path,
                     "0\t%7\tpm-project-a\t100\tbash attach.sh\n",
                     f"100 1 Ss bash attach.sh\n101 100 S bash\n"
                     f"102 101 Sl /usr/bin/podman exec -it {target} sh\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == (["%7"], False)


@pytest.mark.parametrize("processes, rc", [
    ("", 1), ("not process data", 0), ("101 99 S bash\n", 0),
])
def test_unknown_process_tree_preserves_allocation(monkeypatch, tmp_path, processes, rc):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     processes, rc)
    assert reaper._owner_panes(info, reaper._PaneCache()) == ([], True)


def test_process_query_timeout_preserves_allocation(monkeypatch, tmp_path):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n", "")
    run = reaper.subprocess.run

    def timeout(args, **kwargs):
        if args[0] == "ps":
            raise subprocess.TimeoutExpired(args, 5)
        return run(args, **kwargs)

    monkeypatch.setattr(reaper.subprocess, "run", timeout)
    assert reaper._owner_panes(info, reaper._PaneCache()) == ([], True)


def test_unrelated_suffixed_and_zombie_processes_do_not_own(monkeypatch, tmp_path):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     f"100 1 Ss bash\n101 100 S podman exec {NAME}0 sh\n"
                     f"102 99 S podman exec {CID} sh\n103 100 Z podman exec {NAME} sh\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == ([], False)


def test_dead_panes_need_no_process_query(monkeypatch, tmp_path):
    info = _snapshot(monkeypatch, tmp_path, f"1\t%7\tpm-project-a\t100\t{NAME}\n", "", 1)
    assert reaper._owner_panes(info, reaper._PaneCache()) == ([], False)


@pytest.mark.parametrize("row", ["malformed", "0\t%7\tpm-x\tbad-pid\tbash"])
def test_incomplete_pane_rows_are_unknown(monkeypatch, tmp_path, row):
    info = _snapshot(monkeypatch, tmp_path, row + "\n", "100 1 Ss bash\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == ([], True)


def test_final_recheck_refreshes_process_tree(monkeypatch, tmp_path):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     "100 1 Ss bash\n")
    cache = reaper._PaneCache()
    assert reaper._owner_panes(info, cache) == ([], False)
    _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
              f"100 1 Ss bash\n101 100 S podman exec {CID} sh\n")
    assert reaper._owner_panes(info, cache, fresh=True) == (["%7"], False)


def test_real_shell_descendant_commands():
    # Real ps traversal, without creating a container or contacting a runtime.
    child = subprocess.Popen(
        ["bash", "-c", '"$@"; :', "script-wrapper", sys.executable,
         "-c", "import sys; print('ready', flush=True); sys.stdin.read()", CID],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        commands = reaper._pane_process_commands([child.pid])
        assert commands is not None
        assert any(CID in command for command in commands[child.pid][1:])
    finally:
        child.communicate(timeout=5)
