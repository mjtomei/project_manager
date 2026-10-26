"""The last runtime removal and release pruning must use allocation identity."""

import subprocess
import time
from unittest.mock import MagicMock

import pytest

from pm_core import container as cm, container_reaper as reaper, push_proxy


NAME = "pm-repo-ab12-review-pr-aaaa"
CID = "a" * 64


@pytest.mark.parametrize("bulk", [False, True])
def test_replacement_after_final_check_survives_removal(monkeypatch, bulk):
    allocations = {CID: NAME}
    replacement_id = "b" * 64
    monkeypatch.setattr(cm, "current_container_id", lambda name: CID)
    monkeypatch.setattr(cm, "cleanup_generation", lambda name: "epoch")
    monkeypatch.setattr(reaper, "is_retained", lambda *a: False)
    monkeypatch.setattr(cm, "recent_launch", lambda *a: False)
    monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **k: ([], False))

    def capture(target):
        # External runtime operations do not acquire PM's launch lock. They
        # rename the captured allocation and take its old name after the
        # final ownership/identity check, immediately before runtime rm.
        allocations[CID] = "renamed-allocation"
        allocations[replacement_id] = NAME
        return None

    monkeypatch.setattr(push_proxy, "capture_unshared_proxy", capture)
    stop = MagicMock()
    monkeypatch.setattr(push_proxy, "stop_push_proxy", stop)

    def runtime(*args, **kwargs):
        if args[0] == "rm":
            target = args[2]
            for cid, name in list(allocations.items()):
                if target in (cid, name):
                    del allocations[cid]
            return subprocess.CompletedProcess(args, 0, "", "")
        assert args[0] == "inspect"
        target = args[1]
        if target in allocations or target in allocations.values():
            return subprocess.CompletedProcess(args, 0, "[]", "")
        return subprocess.CompletedProcess(args, 1, "", "Error: no such container")

    monkeypatch.setattr(cm, "_run_runtime", runtime)
    if bulk:
        assert cm._remove_captured_container(NAME, CID, "epoch")
    else:
        info = reaper.ContainerInfo(name=NAME, id=CID)
        assert reaper._remove_checked(reaper.Decision(info, "remove", "unowned"), reaper.Scope()) == (True, "")
    assert allocations == {replacement_id: NAME}


@pytest.mark.parametrize("replacement", [False, True])
def test_named_pass_preserves_release_for_renamed_allocation(monkeypatch, replacement):
    reaper._record_release(NAME, CID, "", "pane-exit")
    infos = [reaper.ContainerInfo(name="renamed-allocation", id=CID)]
    if replacement:
        infos.append(reaper.ContainerInfo(name=NAME, id="replacement-id", created=time.time()))
    monkeypatch.setattr(reaper, "list_containers", lambda: infos)
    scope = reaper.Scope(names={NAME})
    out = reaper.plan(scope)
    assert len(out.decisions) == int(replacement)
    reaper._prune_releases(out, scope, time.time() + 1)
    assert reaper.pending_releases()[NAME]["id"] == CID


def test_full_pass_prunes_confirmed_absent_release():
    reaper._record_release(NAME, CID, "epoch", "pane-exit")
    reaper._prune_releases(reaper.Outcome(), reaper.Scope(), time.time() + 1)
    assert reaper.pending_releases() == {}
