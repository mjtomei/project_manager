"""Interactive debug sessions have ownership even without a tmux pane."""

import shlex
import subprocess
from unittest.mock import Mock

import pytest

from pm_core import container as cm, container_reaper as reaper, qa_loop, tmux


def test_interactive_exec_holds_activity_lock(monkeypatch):
    name = "pm-qa-debug-instr-1234"
    monkeypatch.setattr(cm, "current_container_id", lambda _: "cid")
    monkeypatch.setattr(cm, "cleanup_generation", lambda _: "generation")
    observed = []

    def execute(argv, **kwargs):
        observed.append(cm.activity_owner(name))
        assert kwargs["pass_fds"]
        assert argv == ["bash", "-c", "worker"]
        assert reaper.live_owner_panes(name)  # no runtime or tmux query needed
        return 7

    monkeypatch.setattr(cm.subprocess, "call", execute)
    assert cm.run_interactive_exec(name, "cid", "generation", str(cm.container_state_dir()),
                                   "worker", "podman") == 7
    assert observed == [True]
    assert not cm.activity_owner(name)


@pytest.mark.parametrize("cid,generation", [("replacement", "g"), ("cid", "new")])
def test_interactive_exec_refuses_changed_allocation(monkeypatch, cid, generation):
    monkeypatch.setattr(cm, "current_container_id", lambda _: cid)
    monkeypatch.setattr(cm, "cleanup_generation", lambda _: generation)
    execute = Mock()
    monkeypatch.setattr(cm.subprocess, "call", execute)
    with pytest.raises(cm.ContainerError):
        cm.run_interactive_exec("pm-qa-debug-instr-1234", "cid", "g",
                                str(cm.container_state_dir()), "worker", "podman")
    execute.assert_not_called()


def test_helpers_restore_runtime_selection(monkeypatch):
    """In-process callers must not keep the helper's pinned runtime.

    Both helpers normally run in their own short-lived interpreter, but tests
    and embedders call them in-process.  Leaving the module global overridden
    would silently pin every later runtime probe in that process.
    """
    original = cm._get_runtime
    monkeypatch.setattr(cm, "current_container_id", lambda _: "cid")
    monkeypatch.setattr(cm, "cleanup_generation", lambda _: "generation")
    monkeypatch.setattr(cm.subprocess, "call", lambda *a, **k: 0)
    cm.run_interactive_exec("pm-debug", "cid", "generation",
                            str(cm.container_state_dir()), "worker", "podman")
    assert cm._get_runtime is original

    monkeypatch.setattr(reaper, "release_containers",
                        lambda *a, **k: reaper.Outcome())
    cm.release_on_exit("pm-debug", "cid", "generation", "docker",
                       str(cm.container_state_dir()))
    assert cm._get_runtime is original


def test_failed_interactive_exec_restores_runtime_selection(monkeypatch):
    original = cm._get_runtime
    monkeypatch.setattr(cm, "current_container_id", lambda _: "replacement")
    monkeypatch.setattr(cm.subprocess, "call", Mock())
    with pytest.raises(cm.ContainerError):
        cm.run_interactive_exec("pm-debug", "cid", "generation",
                                str(cm.container_state_dir()), "worker", "podman")
    assert cm._get_runtime is original


def test_failed_attachment_does_not_discard_reused_generation(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda _: "cid")
    monkeypatch.setattr(cm, "cleanup_generation", lambda _: "new")
    remove = Mock()
    monkeypatch.setattr(cm, "remove_container", remove)
    assert not cm.discard_unowned_container("pm-debug", container_id="cid", generation="old")
    remove.assert_not_called()


def test_interactive_command_keeps_exit_release(monkeypatch):
    monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
    command = cm.build_exec_cmd("pm-debug", "worker", container_id="cid", interactive_owner=True)
    inner = shlex.split(command)[2]
    assert "run_interactive_exec" in inner
    assert "release_on_exit" in inner
    assert "trap " in inner


@pytest.mark.parametrize("returncode,stdout,expected", [
    (0, "pm-t:@1\npm-t~2:@2\npm-other:@3\n", {"@1", "@2"}),
    (1, "", None), (0, "malformed", None), (0, "", set()),
    # tmux rewrites a tab separator to '_' unless the client is UTF-8, so the
    # old tab-delimited output must be treated as malformed (fail closed).
    (0, "pm-t_@1\n", None),
])
def test_viewed_windows_fail_closed(monkeypatch, returncode, stdout, expected):
    monkeypatch.setattr(qa_loop.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, returncode, stdout, ""))
    assert qa_loop._viewed_window_ids("pm-t~1") == expected


@pytest.mark.parametrize("viewed,pane_window", [(None, "@1"), ({"@1"}, None)])
def test_unknown_viewed_window_preserves_qa_allocation(monkeypatch, viewed, pane_window):
    state = qa_loop.QALoopState(pr_id="pr-1234")
    state.scenarios = [qa_loop.QAScenario(index=1, title="one", focus="",
                       container_name="pm-t-qa-pr-1234-L-s1", container_id="cid", pane_id="%1")]
    monkeypatch.setattr(qa_loop, "_viewed_window_ids", lambda _: viewed)
    monkeypatch.setattr(tmux, "pane_window_id", lambda _: pane_window)
    release = Mock()
    monkeypatch.setattr(reaper, "release_containers", release)
    qa_loop._release_scenario_containers(state, "pm-t")
    release.assert_not_called()
