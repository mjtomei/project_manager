"""Bulk cleanup and background reconciliation share durable outcome state."""

import contextlib
import fcntl
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from pm_core import container as cm, container_reaper as reaper


def test_outcome_merge_holds_cross_process_lock(monkeypatch):
    def record(*args):
        with cm._lock_path("reaper-state").open("a") as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
        raise AssertionError("state merge ran without its lock")
    monkeypatch.setattr(reaper, "_record_locked", record)
    reaper._record(reaper.Outcome(), reaper.Scope(), "test")


def test_concurrent_outcomes_preserve_each_failure():
    def record(index):
        name = f"pm-test-{index}"
        reaper._record(reaper.Outcome(failures={name: "rm failed"}),
                       reaper.Scope(names={name}), "test")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(record, range(12)))
    assert set(reaper.pending_failures()) == {f"pm-test-{i}" for i in range(12)}


def test_bulk_outcome_does_not_clear_unattempted_proxy_sweep():
    reaper._record(reaper.Outcome(failures={"push proxy sweep": "inventory unavailable"}),
                   reaper.Scope(), "periodic")
    reaper._record(reaper.Outcome(removed=["pm-test"]),
                   reaper.Scope(names={"pm-test"}), "explicit-cleanup")
    assert "push proxy sweep" in reaper.pending_failures()
    # A pass that never enumerated the proxies cannot clear its failure...
    reaper._record(reaper.Outcome(), reaper.Scope(), "periodic")
    assert "push proxy sweep" in reaper.pending_failures()
    # ...only a completed full sweep can.
    reaper._record(reaper.Outcome(proxy_sweep_ran=True), reaper.Scope(), "periodic")
    assert not reaper.pending_failures()


def test_old_inventory_preserves_newer_bulk_failure(monkeypatch):
    monkeypatch.setattr(reaper.time, "time", lambda: 20.5)
    latest = reaper.Outcome(
        failures={"pm-test": "new allocation removal failed"},
        decisions=[reaper.Decision(reaper.ContainerInfo("pm-test", id="new"),
                                   "remove", "explicit cleanup")])
    reaper._record(latest, reaper.Scope(names={"pm-test"}), "explicit-cleanup")
    # The automatic inventory predates both the allocation and its failed cleanup.
    reaper._record(reaper.Outcome(), reaper.Scope(), "periodic",
                   inventory=set(), observed_at=20.1)
    assert reaper.pending_failures()["pm-test"]["id"] == "new"
    old = reaper.Outcome(
        failures={"pm-test": "old allocation failed"},
        decisions=[reaper.Decision(reaper.ContainerInfo("pm-test", id="old"),
                                   "remove", "no owner")])
    reaper._record(old, reaper.Scope(), "periodic",
                   inventory={"pm-test"}, observed_at=20.1)
    assert reaper.pending_failures()["pm-test"]["id"] == "new"
    reaper._record(reaper.Outcome(), reaper.Scope(), "periodic",
                   inventory=set(), observed_at=21)
    assert not reaper.pending_failures()


def test_outcome_write_failure_is_visible(monkeypatch):
    monkeypatch.setattr(reaper.os, "replace", Mock(side_effect=OSError("disk full")))
    outcome = reaper.Outcome(removed=["pm-test"])
    reaper._record(outcome, reaper.Scope(names={"pm-test"}), "explicit-cleanup")
    assert outcome.removed == ["pm-test"]
    assert "disk full" in outcome.failures["cleanup state"]


def test_unavailable_state_lock_is_visible(monkeypatch):
    @contextlib.contextmanager
    def unavailable(*args, **kwargs):
        yield False
    monkeypatch.setattr(cm, "_file_lock", unavailable)
    record = Mock()
    monkeypatch.setattr(reaper, "_record_locked", record)
    outcome = reaper.Outcome()
    reaper._record(outcome, reaper.Scope(), "test")
    assert "lock unavailable" in outcome.failures["cleanup state"]
    record.assert_not_called()


def test_sweep_flag_follows_what_the_sweep_reported(monkeypatch):
    """Only a pass that actually listed the proxies clears a sweep failure.

    ``_release_unused_proxies`` probes the runtime identity itself, so a
    second probe in ``_run`` could disagree with it and clear a whole-sweep
    failure for a sweep that never ran.
    """
    monkeypatch.setattr(reaper, "list_containers", lambda: [])
    monkeypatch.setattr(cm, "running_container_count", lambda: 0)
    monkeypatch.setattr(cm, "keyring_summary", lambda: "")
    monkeypatch.setattr(reaper, "_record", lambda out, *a, **k: None)
    # The identity probe succeeds, but this pass never enumerated the proxies.
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: {"runtime": "test"})
    monkeypatch.setattr(reaper, "_release_unused_proxies",
                        lambda scope, failures, checked=None: ([], False))
    out = reaper._run(reaper.Scope(), dry_run=False, reason="manual")
    assert out.proxy_sweep_ran is False
    monkeypatch.setattr(reaper, "_release_unused_proxies",
                        lambda scope, failures, checked=None: ([], True))
    out = reaper._run(reaper.Scope(), dry_run=False, reason="manual")
    assert out.proxy_sweep_ran is True


def test_release_unused_proxies_reports_whether_it_enumerated(monkeypatch):
    """An unknown runtime identity means no proxy was listed, not 'swept'."""
    from pm_core import push_proxy
    monkeypatch.setattr(push_proxy, "retry_unshared_releases",
                        lambda scope, failures: [])
    listed = []
    monkeypatch.setattr(push_proxy, "list_shared_proxies",
                        lambda: listed.append(1) or [])
    monkeypatch.setattr(push_proxy, "runtime_domain", lambda: None)
    assert reaper._release_unused_proxies(reaper.Scope(), {}) == ([], False)
    assert not listed
    monkeypatch.setattr(push_proxy, "runtime_domain", lambda: {"runtime": "test"})
    assert reaper._release_unused_proxies(reaper.Scope(), {}) == ([], True)
    assert listed
