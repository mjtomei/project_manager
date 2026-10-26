"""Exercise the generated EXIT trap across a restart using a shell runtime stub."""

import shlex
import subprocess
import time
from pathlib import Path

import pytest

from pm_core import container


@pytest.mark.parametrize("restart,retain", [(False, False), (True, False), (False, True)])
def test_delayed_exit_trap_preserves_restarted_container(tmp_path, monkeypatch, restart, retain):
    monkeypatch.setenv("PM_CONTAINER_STATE_DIR", str(tmp_path / "state"))
    runtime = tmp_path / "podman"
    entered, release, removed = (tmp_path / n for n in ("entered", "release", "removed"))
    name = "pm-t-review-pr-aaaa"
    from pm_core import container_reaper
    monkeypatch.setattr(container_reaper, "_runtime_domain", lambda: {
        "runtime": "podman", "graph_root": "test-graph", "run_root": "test-run",
        "hostname": "test-host", "endpoint": "", "connection": ""})
    monkeypatch.delenv("CONTAINER_HOST", raising=False)
    monkeypatch.delenv("CONTAINER_CONNECTION", raising=False)
    runtime.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = info ]; then printf '%s\\n' "
        "'{\"store\":{\"graphRoot\":\"test-graph\",\"runRoot\":\"test-run\"},"
        "\"host\":{\"hostname\":\"test-host\"}}'; fi\n"
        f'if [ "$1" = exec ]; then touch {shlex.quote(str(entered))}; '
        f'while [ ! -f {shlex.quote(str(release))} ]; do sleep 0.01; done; fi\n'
        f'if [ "$1" = rm ]; then printf "%s\\n" "$3" >> {shlex.quote(str(removed))}; fi\n'
        f'if [ "$1" = ps ] && [ ! -f {shlex.quote(str(removed))} ]; then printf "%s\\n" {name}; fi\n'
        f'if [ "$1" = inspect ]; then\n'
        f'  if [ -f {shlex.quote(str(removed))} ]; then printf "No such container\\n" >&2; exit 1; fi\n'
        '  if [ "$2" != "--format" ] && [ "$2" != "-f" ]; then printf \'[{"Config":{"Labels":{}}}]\\n\'; exit 0; fi\n'
        f'  case "$3" in *Id*State*) printf \'{name}\\texact-id\\ttrue\\trunning\\t{{}}\\n\';;\n'
        f'  *) printf "exact-id\\n";; esac\nfi\n')
    runtime.chmod(0o755)
    monkeypatch.setattr(container, "_get_runtime", lambda: str(runtime))
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    socket_dir = tmp_path / f"pm-push-proxy-{name}"
    socket_dir.mkdir()
    socket = socket_dir / "push.sock"
    socket.touch()
    command = container.build_exec_cmd(
        "pm-t-review-pr-aaaa", "worker", container_id="exact-id",
        proxy_socket_path=str(socket))
    proc = subprocess.Popen(["bash", "-c", command], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 5
        while not entered.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert entered.exists(), "generated command did not reach exec"
        if restart:
            monkeypatch.setattr(container, "current_container_id", lambda _: "exact-id")
            monkeypatch.setattr(container, "_run_runtime", lambda *a, **k:
                                subprocess.CompletedProcess(a, 0,
                                    '"2026-10-26T00:00:00Z"' if a[0] == "inspect" else "", ""))
            monkeypatch.setattr(container, "_wait_for_setup", lambda *a, **k: None)
            monkeypatch.setattr(container, "_setup_complete", lambda *a: True)
            container.restart_container("pm-t-review-pr-aaaa")
        if retain:
            from pm_core import container_reaper
            container_reaper.retain(name, container_id="exact-id")
        # The old exec/EXIT arrives after restart_container returned.
        release.touch()
        stdout, stderr = proc.communicate(timeout=5)
        assert proc.returncode == 0, (stdout, stderr)
        assert socket.exists() is (restart or retain)
        assert removed.exists() is not (restart or retain)
        if not restart and not retain:
            assert removed.read_text().strip() in (name, "exact-id")
    finally:
        # The interactive-owner child can outlive its shell on an assertion
        # failure. Release the stub before draining inherited output pipes.
        release.touch()
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=5)


def test_restart_refuses_if_cleanup_generation_cannot_be_written(tmp_path, monkeypatch):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("keep")
    monkeypatch.setenv("PM_CONTAINER_STATE_DIR", str(blocked))
    called = []
    monkeypatch.setattr(container, "_run_runtime", lambda *a, **k: called.append(a))
    with pytest.raises(container.ContainerError, match="Cannot protect"):
        container.restart_container("pm-t-review-pr-aaaa")
    assert called == []
