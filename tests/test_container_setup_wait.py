"""Initial readiness wait: an exited startup command fails fast with its logs."""

import subprocess

import pytest

from pm_core import container as cm

IMPROPER = ("Error: can only create exec sessions on running containers: "
            "container state improper")


def _runtime(running: str):
    calls = []

    def runtime(*args, **kwargs):
        calls.append(args)
        if args[0] == "exec":
            return subprocess.CompletedProcess(args, 125, "", IMPROPER)
        if args[0] == "inspect":
            return subprocess.CompletedProcess(args, 0, running + "\n", "")
        if args[0] == "logs":
            return subprocess.CompletedProcess(
                args, 0, "", "error: could not lock config file /home/pm/.gitconfig: Is a directory")
        raise AssertionError(args)
    return runtime, calls


def test_exited_container_reported_with_podman3_wording_fails_with_logs(monkeypatch):
    runtime, calls = _runtime("false")
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    monkeypatch.setattr(cm.time, "sleep", lambda s: pytest.fail("polled an exited container"))
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._wait_for_setup("captured-id")
    assert error.value.kind == "runtime"
    assert "could not finish setup" in str(error.value)
    assert "/home/pm/.gitconfig: Is a directory" in str(error.value)
    assert ("logs", "--tail", "20", "captured-id") in calls


def test_running_container_with_unrecognised_probe_error_keeps_waiting(monkeypatch):
    runtime, calls = _runtime("true")
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    monkeypatch.setattr(cm, "_SETUP_TIMEOUT", 0.05)
    monkeypatch.setattr(cm, "_SETUP_POLL_INTERVAL", 0.01)
    with pytest.raises(cm.ContainerLaunchError) as error:
        cm._wait_for_setup("captured-id")
    assert error.value.kind == "timeout"
    assert not any(c[0] == "logs" for c in calls)
