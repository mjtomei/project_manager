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


@pytest.mark.parametrize("target", [NAME, CID, CID[:4], CID[:12], CID[:63]])
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


@pytest.mark.parametrize("command", [
    f"/usr/bin/python -m pm_core.wrapper container restart {NAME}",
    f"pm container retain {NAME}",
    f"bash -c pm container restart {NAME}",
    f"agent investigate container {CID}",
    f"podman inspect {NAME}",
    f"docker container inspect {CID}",
    f"podman inspect --format exec {NAME}",
])
def test_diagnostic_commands_do_not_claim_ownership(monkeypatch, tmp_path, command):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     f"100 1 Ss bash\n101 100 S {command}\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == ([], False)


@pytest.mark.parametrize("command", [
    f"/usr/bin/podman exec -it {NAME} sh",
    f"docker attach {CID}",
    f"docker container exec -it {CID} sh",
    f"docker exec -it -u pm {CID} sh",
    f"docker exec --user=1000:1000 {NAME} sh",
    f"podman exec --interactive --tty -- {NAME} sh",
    f"docker attach --no-stdin {CID}",
    f"podman --root /private/store exec -it {NAME} sh",
])
def test_runtime_clients_still_own_from_diagnostic_pane(monkeypatch, tmp_path, command):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     f"100 1 Ss bash\n101 100 S pm container restart {NAME}\n"
                     f"102 100 S {command}\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == (["%7"], False)


@pytest.mark.parametrize("client", [
    "podman exec", "podman exec -it", "podman exec --interactive --tty --",
    "docker container exec -it -u pm", "docker exec --user=1000:1000",
    "docker attach --no-stdin",
])
@pytest.mark.parametrize("target", [NAME, CID])
def test_runtime_payload_does_not_claim_another_container(monkeypatch, tmp_path, client, target):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     f"100 1 Ss bash\n101 100 S {client} other sh -c echo {target}\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == ([], False)
    info.name, info.id = "other", "b" * 64
    assert reaper._owner_panes(info, reaper._PaneCache()) == (["%7"], False)


@pytest.mark.parametrize("options", ["--workdir /path with spaces", "--unknown value"])
def test_ambiguous_exec_options_preserve_possible_owner(monkeypatch, tmp_path, options):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     f"100 1 Ss bash\n101 100 S podman exec {options} {NAME} sh\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == (["%7"], False)


def test_start_command_owner_is_preserved(monkeypatch, tmp_path):
    info = _snapshot(monkeypatch, tmp_path,
                     f"0\t%7\tpm-project-a\t100\tbash wrapper {NAME}\n",
                     "100 1 Ss bash\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == (["%7"], False)


@pytest.mark.parametrize("client", ["podman exec -it", "docker attach", "docker container exec -u pm",
                                    "podman --root /private/store exec -it"])
def test_short_id_attachment_protects_locked_removal(monkeypatch, tmp_path, client):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     f"100 1 Ss bash\n101 100 S {client} {CID[:12]} sh\n")
    monkeypatch.setattr(reaper.container_mod, "current_container_id", lambda _: CID)
    monkeypatch.setattr(reaper.container_mod, "recent_launch", lambda *a: False)
    removed = []
    monkeypatch.setattr(reaper.container_mod, "remove_container", lambda *a, **kw: removed.append(a))
    decision = reaper.Decision(info, "remove", "no owner at earlier inventory")
    ok, reason = reaper._remove_checked(decision, reaper.Scope())
    assert not ok and "attached concurrently" in reason
    assert removed == []


@pytest.mark.parametrize("command", [
    f"podman exec other sh -c echo {CID[:12]}",
    f"docker exec {'b' * 12} sh",
    f"podman inspect {CID[:12]}",
    f"agent explain {CID[:12]}",
    f"podman exec {CID[:12]}0 sh",
])
def test_short_id_nonowners_remain_unowned(monkeypatch, tmp_path, command):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     f"100 1 Ss bash\n101 100 S {command}\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == ([], False)


def test_ambiguous_short_id_keeps_each_matching_allocation(monkeypatch, tmp_path):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     f"100 1 Ss bash\n101 100 S docker attach {CID[:12]}\n")
    cache = reaper._PaneCache()
    assert reaper._owner_panes(info, cache) == (["%7"], False)
    info.name, info.id = "renamed-other", CID[:12] + "b" * 52
    assert reaper._owner_panes(info, cache) == (["%7"], False)


def test_short_id_is_visible_to_restart_owner_check(monkeypatch, tmp_path):
    info = _snapshot(monkeypatch, tmp_path, "0\t%7\tpm-project-a\t100\tbash\n",
                     f"100 1 Ss bash\n101 100 S podman exec -it {CID[:12]} sh\n")
    monkeypatch.setattr(reaper, "_inspect", lambda *a, **kw: [info])
    assert reaper.live_owner_panes(NAME, CID) == ["%7"]


def test_short_id_in_historical_shell_payload_is_not_attachment(monkeypatch, tmp_path):
    info = _snapshot(monkeypatch, tmp_path,
                     f"0\t%7\tpm-project-a\t100\tbash -c 'echo {CID[:12]}; bash'\n",
                     "100 1 Ss bash\n")
    assert reaper._owner_panes(info, reaper._PaneCache()) == ([], False)


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
