"""Operation-local runtime identity reuse and side-effect-free owner probes."""

import contextvars
import fcntl
import threading
from concurrent.futures import ThreadPoolExecutor

from pm_core import container as cm
from pm_core import container_reaper as reaper
from pm_core import push_proxy


# conftest replaces this function to isolate ordinary lifecycle tests.
_real_domain = reaper._runtime_domain


def _domain_probe(monkeypatch, probe):
    monkeypatch.setattr(reaper, "_runtime_domain", _real_domain)
    monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
    monkeypatch.setattr(push_proxy, "runtime_domain", probe)


def test_scope_reuses_success_and_resets_between_operations(monkeypatch):
    calls = []

    def probe():
        calls.append(1)
        return {"runtime": "test", "id": len(calls)}

    _domain_probe(monkeypatch, probe)
    with reaper.runtime_domain_scope():
        assert reaper._runtime_domain()["id"] == 1
        with reaper.runtime_domain_scope():
            result = reaper._runtime_domain()
            result["id"] = "caller mutation"
        assert reaper._runtime_domain()["id"] == 1
    with reaper.runtime_domain_scope():
        assert reaper._runtime_domain()["id"] == 2
    assert len(calls) == 2


def test_unknown_domain_is_retried_within_operation(monkeypatch):
    values = iter([None, {"id": "recovered"}])
    _domain_probe(monkeypatch, lambda: next(values))
    with reaper.runtime_domain_scope():
        assert reaper._runtime_domain() is None
        assert reaper._runtime_domain() == {"id": "recovered"}
        assert reaper._runtime_domain() == {"id": "recovered"}


def test_endpoint_change_invalidates_operation_probe(monkeypatch):
    calls = []

    def probe():
        calls.append(1)
        return {"id": len(calls)}

    _domain_probe(monkeypatch, probe)
    with reaper.runtime_domain_scope():
        assert reaper._runtime_domain()["id"] == 1
        monkeypatch.setenv("CONTAINER_HOST", "ssh://another-store")
        assert reaper._runtime_domain()["id"] == 2
        assert reaper._runtime_domain()["id"] == 2


def test_parallel_operations_do_not_share_domains(monkeypatch):
    barrier = threading.Barrier(2)
    _domain_probe(monkeypatch, lambda: {"thread": threading.get_ident()})

    def operation():
        with reaper.runtime_domain_scope():
            first = reaper._runtime_domain()
            barrier.wait(timeout=5)
            assert reaper._runtime_domain() == first
            return first

    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = [pool.submit(operation) for _ in range(2)]
        assert one.result(timeout=10) != two.result(timeout=10)


def test_copied_worker_context_reuses_probe_without_mutating_parent(monkeypatch):
    calls = []

    def probe():
        calls.append(1)
        return {"id": len(calls)}

    _domain_probe(monkeypatch, probe)
    with reaper.runtime_domain_scope():
        assert reaper._runtime_domain() == {"id": 1}
        context = contextvars.copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(context.run, reaper._runtime_domain).result() == {"id": 1}
        assert reaper._runtime_domain() == {"id": 1}
    assert len(calls) == 1


def test_reconcile_propagates_domain_to_removal_workers(monkeypatch):
    calls = []

    def probe():
        calls.append(1)
        return {"id": len(calls)}

    _domain_probe(monkeypatch, probe)
    infos = [reaper.ContainerInfo(name=f"pm-impl-pr-{i}", id=str(i)) for i in range(3)]
    monkeypatch.setattr(reaper, "list_containers", lambda: infos)
    monkeypatch.setattr(reaper, "pending_failures", lambda: {})
    monkeypatch.setattr(reaper, "_current_release_records", lambda: [])

    def decide(info, *args):
        assert reaper._runtime_domain() == {"id": 1}
        return reaper.Decision(info, "remove", "unowned")

    def remove(*args):
        assert reaper._runtime_domain() == {"id": 1}
        return True, ""

    monkeypatch.setattr(reaper, "_decide", decide)
    monkeypatch.setattr(reaper, "_remove_checked", remove)
    monkeypatch.setattr(reaper, "_release_unused_proxies",
                        lambda scope, failures, checked=None: ([], True))
    monkeypatch.setattr(reaper, "_prune_releases", lambda *args: None)
    monkeypatch.setattr(reaper, "_record", lambda *args, **kwargs: None)
    monkeypatch.setattr(cm, "running_container_count", lambda: 0)
    monkeypatch.setattr(cm, "keyring_summary", lambda: "")
    out = reaper.reconcile(reaper.Scope(names={i.name for i in infos}))
    assert len(out.removed) == 3
    assert not out.failures
    assert not out.error
    assert len(calls) == 1


def test_create_uses_one_successful_domain_probe(monkeypatch, tmp_path):
    calls = []

    def probe():
        calls.append(1)
        return {"id": len(calls)}

    _domain_probe(monkeypatch, probe)
    monkeypatch.setattr(cm, "_ensure_reusable", lambda *args, **kwargs: "cid")
    monkeypatch.setattr(cm, "current_container_id", lambda _: "cid")
    monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
    identity = {}
    assert cm.create_container("pm-impl-pr-a", cm.ContainerConfig(), tmp_path,
                               allocation_identity=identity) == "cid"
    assert identity["generation"]
    assert len(calls) == 1


def test_proxy_owner_checks_reuse_operation_domain(monkeypatch, tmp_path):
    import json
    calls = []
    def probe():
        calls.append(1)
        return {"id": "runtime"}
    _domain_probe(monkeypatch, probe)
    (tmp_path / "owner.json").write_text(json.dumps({"runtime_domain": {"id": "runtime"}}))
    with reaper.runtime_domain_scope():
        assert reaper._runtime_domain() == {"id": "runtime"}
        assert push_proxy._owner_domain_matches(str(tmp_path))
        assert push_proxy._owner_domain_matches(str(tmp_path))
    assert len(calls) == 1
    assert push_proxy._owner_domain_matches(str(tmp_path))
    assert len(calls) == 2  # a later operation must re-probe


def test_activity_probe_does_not_create_files_or_directories(monkeypatch, tmp_path):
    state = tmp_path / "absent-state"
    monkeypatch.setenv("PM_CONTAINER_STATE_DIR", str(state))
    assert not cm.activity_owner("pm-qa-pr-a-loop-s1")
    assert not state.exists()


def test_activity_probe_preserves_existing_lock_inode():
    path = cm._lock_path("active-pm-qa-pr-a-loop-s1")
    path.parent.mkdir(parents=True)
    with path.open("a") as owner:
        inode = path.stat().st_ino
        fcntl.flock(owner, fcntl.LOCK_SH)
        assert cm.activity_owner("pm-qa-pr-a-loop-s1")
        assert path.stat().st_ino == inode
    assert not cm.activity_owner("pm-qa-pr-a-loop-s1")
    assert path.stat().st_ino == inode
