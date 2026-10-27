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
