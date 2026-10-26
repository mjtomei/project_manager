"""Failure-boundary regressions for lifecycle setup and launcher integration."""
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pm_core import container as cm, container_reaper as reaper


@pytest.mark.parametrize("stderr", ["No such container: pm-x", "No such object: pm-x",
                                     "no container with name or ID pm-x found"])
def test_confirmed_absence_allows_fresh_create(monkeypatch, stderr):
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw:
                        subprocess.CompletedProcess(a, 1, "", stderr))
    assert cm.container_is_running("pm-x") is False


def test_running_inspect_error_does_not_recreate(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw:
                        subprocess.CompletedProcess(a, 125, "", "storage lock unavailable"))
    fresh = MagicMock()
    monkeypatch.setattr(cm, "_create_fresh", fresh)
    with pytest.raises(cm.ContainerError, match="storage lock unavailable"):
        cm.create_container("pm-t-impl-pr-aaaa", cm.ContainerConfig(), tmp_path)
    fresh.assert_not_called()


@pytest.mark.parametrize("alias", ["a" * 64, "a" * 12, "/pm-t-review-pr-aaaa"])
def test_restart_alias_uses_canonical_lock_and_generation(monkeypatch, alias):
    from click.testing import CliRunner
    from pm_core.cli import cli
    name = "pm-t-review-pr-aaaa"
    monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0,
                            '\"2026-10-26T00:00:00Z\"' if "{{json .State.StartedAt}}" in a
                            else "/" + name + "\n", ""))
    monkeypatch.setattr(cm, "pids_usage", lambda: {})
    monkeypatch.setattr(cm, "_wait_for_setup", lambda *a, **k: None)
    monkeypatch.setattr(cm, "_setup_complete", lambda n: True)
    result = CliRunner().invoke(cli, ["container", "restart", alias, "--force"])
    assert result.exit_code == 0, result.output
    assert cm._restart_generation_path(name).read_text().strip()
    assert cm._lock_path("container-" + name).exists()
    assert not cm._restart_generation_path(alias).exists()


def _fresh(monkeypatch, tmp_path, *, proxy=False, git_setup=""):
    calls = []
    monkeypatch.setattr(cm, "container_is_running", lambda n: False)
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    monkeypatch.setattr(cm, "image_exists", lambda *a: True)
    monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
    monkeypatch.setattr(cm, "_resolve_claude_binary", lambda: None)
    monkeypatch.setattr(cm, "_wait_for_setup", lambda n: None)
    monkeypatch.setattr(cm, "_post_setup", lambda *a: None)
    monkeypatch.setattr(cm, "_build_git_setup_script", lambda **kw: git_setup)
    removed = MagicMock()
    monkeypatch.setattr(cm, "remove_container", removed)

    def runtime(*a, **kw):
        calls.append(a)
        return subprocess.CompletedProcess(a, 0, "container-id\n", "")
    monkeypatch.setattr(cm, "_run_runtime", runtime)
    if proxy:
        from pm_core import push_proxy
        monkeypatch.setattr(push_proxy, "start_push_proxy", lambda *a, **kw: str(tmp_path / "dead.sock"))
        monkeypatch.setattr(push_proxy, "proxy_is_alive", lambda sock: False)
    return calls, removed


def test_fresh_proxy_must_accept_connections(monkeypatch, tmp_path):
    calls, removed = _fresh(monkeypatch, tmp_path, proxy=True)
    with pytest.raises(cm.ContainerLaunchError, match="not accepting connections") as error:
        cm.create_container("pm-t-impl-pr-aaaa", cm.ContainerConfig(), tmp_path,
                            allowed_push_branch="test")
    assert error.value.kind == "proxy"
    assert any(c[0] == "run" for c in calls)
    assert removed.call_count == 2  # stale name then partial allocation


def test_required_setup_failure_never_writes_readiness(monkeypatch, tmp_path):
    sentinel = tmp_path / "ready"
    monkeypatch.setattr(cm, "_READY_SENTINEL", str(sentinel))
    monkeypatch.setattr(cm, "_CONTAINER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cm, "_PID1_REAPER", ":")
    calls, _ = _fresh(monkeypatch, tmp_path, git_setup="false; printf 'must not continue'")
    cm.create_container("pm-t-impl-pr-aaaa", cm.ContainerConfig(), tmp_path)
    script = next(c[-1] for c in calls if c[0] == "run")
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode != 0
    assert not sentinel.exists()
    assert "must not continue" not in result.stdout


def test_inventory_failure_visible_in_tui(monkeypatch):
    from pm_core.tui.app import ProjectManagerApp
    messages = []
    app = SimpleNamespace(log_message=messages.append,
                          call_from_thread=lambda fn, msg: fn(msg))
    monkeypatch.setattr(cm, "is_container_mode_enabled", lambda: True)
    monkeypatch.setattr(reaper, "reconcile", lambda **kw:
                        kw["on_done"](reaper.Outcome(error="inventory unavailable")))
    ProjectManagerApp._kick_container_reconcile(app)
    assert "inventory unavailable" in messages[0]
    assert "pm container reap" in messages[0]


def test_qa_resume_preserves_release_identity():
    from pm_core import qa_loop
    scenario = qa_loop.QAScenario(index=1, title="one", focus="",
                                 container_name="pm-t-qa-pr-aaaa-L-s1",
                                 container_id="original", container_generation="g1")
    restored = qa_loop._scenario_from_resume_dict(qa_loop._scenario_to_resume_dict(scenario))
    assert (restored.container_id, restored.container_generation) == ("original", "g1")
