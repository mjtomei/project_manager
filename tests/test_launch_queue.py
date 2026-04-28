"""Tests for pm_core.launch_queue."""

import contextlib
import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.launch_queue import (
    enqueue,
    try_acquire,
    enqueue_and_try_acquire,
    dequeue,
    get_queue_status,
    get_queue_policy,
    _sort_queue,
    _sort_qa_drain,
    _sort_qa_round_robin,
    _clean_stale,
    _load_queue,
    _save_queue,
    VALID_POLICIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _patch_home(tmp_path):
    """Patch pm_home in both launch_queue and governor_lock modules."""
    with patch("pm_core.launch_queue.pm_home", return_value=tmp_path), \
         patch("pm_core.governor_lock.pm_home", return_value=tmp_path):
        yield


def _patch_governor_inactive():
    """Patch get_memory_target to return None (governor inactive)."""
    return patch("pm_core.memory_governor.get_memory_target", return_value=None)


@contextlib.contextmanager
def _patch_governor_active(target_mb=48 * 1024, current_mb=30 * 1024,
                           projection_mb=8 * 1024):
    """Context manager patching an active governor."""
    with patch("pm_core.memory_governor.get_memory_target",
               return_value=target_mb), \
         patch("pm_core.memory_governor.get_current_used_mb",
               return_value=current_mb), \
         patch("pm_core.memory_governor.project_memory",
               return_value=projection_mb):
        yield


# ---------------------------------------------------------------------------
# Queue I/O
# ---------------------------------------------------------------------------

class TestQueueIO:
    def test_load_empty(self, tmp_path):
        with _patch_home(tmp_path):
            q = _load_queue()
            assert q == {"entries": [], "last_served_qa_run": None}

    def test_save_and_load(self, tmp_path):
        with _patch_home(tmp_path):
            data = {
                "entries": [{"id": "abc", "container_type": "impl"}],
                "last_served_qa_run": "run-1",
            }
            _save_queue(data)
            loaded = _load_queue()
            assert loaded["entries"][0]["id"] == "abc"
            assert loaded["last_served_qa_run"] == "run-1"

    def test_corrupt_file(self, tmp_path):
        with _patch_home(tmp_path):
            (tmp_path / "launch-queue.json").write_text("{{not json")
            q = _load_queue()
            assert q["entries"] == []


# ---------------------------------------------------------------------------
# Stale cleanup
# ---------------------------------------------------------------------------

class TestStaleCleanup:
    def test_removes_dead_pid(self):
        entries = [
            {"id": "a", "pid": 999999999, "container_type": "impl"},
            {"id": "b", "pid": os.getpid(), "container_type": "review"},
        ]
        result = _clean_stale(entries)
        assert len(result) == 1
        assert result[0]["id"] == "b"

    def test_keeps_alive_pid(self):
        entries = [{"id": "a", "pid": os.getpid(), "container_type": "impl"}]
        result = _clean_stale(entries)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Policy sorting
# ---------------------------------------------------------------------------

class TestPolicySorting:
    def _make_entry(self, id, ctype, enqueued_at, qa_run_id=None, status="waiting"):
        return {
            "id": id,
            "container_type": ctype,
            "enqueued_at": enqueued_at,
            "qa_run_id": qa_run_id,
            "status": status,
            "pid": os.getpid(),
        }

    def test_fifo_sorts_by_time(self):
        entries = [
            self._make_entry("c", "qa_scenario", 3.0, "run-1"),
            self._make_entry("a", "impl", 1.0),
            self._make_entry("b", "review", 2.0),
        ]
        result = _sort_queue(entries, "fifo", None)
        assert [e["id"] for e in result] == ["a", "b", "c"]

    def test_priority_drain_type_ordering(self):
        entries = [
            self._make_entry("qa1", "qa_scenario", 1.0, "run-1"),
            self._make_entry("impl1", "impl", 2.0),
            self._make_entry("rev1", "review", 3.0),
        ]
        result = _sort_queue(entries, "priority-drain", None)
        # impl first, review second, qa last
        assert [e["id"] for e in result] == ["impl1", "rev1", "qa1"]

    def test_priority_drain_qa_grouping(self):
        entries = [
            self._make_entry("a1", "qa_scenario", 1.0, "run-a"),
            self._make_entry("b1", "qa_scenario", 2.0, "run-b"),
            self._make_entry("a2", "qa_scenario", 3.0, "run-a"),
            self._make_entry("b2", "qa_scenario", 4.0, "run-b"),
        ]
        result = _sort_queue(entries, "priority-drain", None)
        # run-a started first, so all of run-a, then all of run-b
        assert [e["id"] for e in result] == ["a1", "a2", "b1", "b2"]

    def test_priority_round_robin(self):
        entries = [
            self._make_entry("a1", "qa_scenario", 1.0, "run-a"),
            self._make_entry("b1", "qa_scenario", 2.0, "run-b"),
            self._make_entry("a2", "qa_scenario", 3.0, "run-a"),
            self._make_entry("b2", "qa_scenario", 4.0, "run-b"),
        ]
        result = _sort_queue(entries, "priority-round-robin", None)
        # Interleave: a1, b1, a2, b2
        assert [e["id"] for e in result] == ["a1", "b1", "a2", "b2"]

    def test_round_robin_resumes_after_last_served(self):
        entries = [
            self._make_entry("a1", "qa_scenario", 1.0, "run-a"),
            self._make_entry("b1", "qa_scenario", 2.0, "run-b"),
            self._make_entry("a2", "qa_scenario", 3.0, "run-a"),
            self._make_entry("b2", "qa_scenario", 4.0, "run-b"),
        ]
        # Last served was run-a, so start from run-b
        result = _sort_queue(entries, "priority-round-robin", "run-a")
        assert [e["id"] for e in result] == ["b1", "a1", "b2", "a2"]


# ---------------------------------------------------------------------------
# Enqueue / dequeue
# ---------------------------------------------------------------------------

class TestEnqueue:
    def test_enqueue_single(self, tmp_path):
        with _patch_home(tmp_path):
            ids = enqueue("impl")
            assert len(ids) == 1
            q = _load_queue()
            assert len(q["entries"]) == 1
            assert q["entries"][0]["container_type"] == "impl"
            assert q["entries"][0]["pid"] == os.getpid()

    def test_enqueue_batch(self, tmp_path):
        with _patch_home(tmp_path):
            ids = enqueue("qa_scenario", qa_run_id="run-1", count=5)
            assert len(ids) == 5
            q = _load_queue()
            assert len(q["entries"]) == 5
            assert all(e["qa_run_id"] == "run-1" for e in q["entries"])

    def test_dequeue_removes_entries(self, tmp_path):
        with _patch_home(tmp_path):
            ids = enqueue("impl", count=3)
            dequeue(ids[:2])
            q = _load_queue()
            assert len(q["entries"]) == 1
            assert q["entries"][0]["id"] == ids[2]

    def test_dequeue_single_string(self, tmp_path):
        with _patch_home(tmp_path):
            ids = enqueue("impl")
            dequeue(ids[0])  # pass string, not list
            q = _load_queue()
            assert len(q["entries"]) == 0


# ---------------------------------------------------------------------------
# try_acquire
# ---------------------------------------------------------------------------

class TestTryAcquire:
    def test_governor_inactive_grants_all(self, tmp_path):
        with _patch_home(tmp_path), _patch_governor_inactive():
            ids = enqueue("qa_scenario", qa_run_id="run-1", count=3)
            granted = try_acquire(ids)
            assert set(granted) == set(ids)

    def test_grants_within_budget(self, tmp_path):
        # 30G used + 8G projected = 38G <= 48G target
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 30 * 1024, 8 * 1024):
            ids = enqueue("qa_scenario", qa_run_id="run-1", count=1)
            granted = try_acquire(ids)
            assert len(granted) == 1

    def test_denies_over_budget(self, tmp_path):
        # 44G used + 8G projected = 52G > 48G target
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 44 * 1024, 8 * 1024):
            ids = enqueue("qa_scenario", qa_run_id="run-1", count=1)
            granted = try_acquire(ids)
            assert len(granted) == 0

    def test_partial_grant(self, tmp_path):
        # 30G used, 8G each, target 48G: headroom 18G, can fit 2
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 30 * 1024, 8 * 1024):
            ids = enqueue("qa_scenario", qa_run_id="run-1", count=5)
            granted = try_acquire(ids)
            assert len(granted) == 2

    def test_accounts_for_acquired_entries(self, tmp_path):
        """Already-acquired entries reduce available headroom."""
        # 30G used, 8G each, target 48G: headroom 18G
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 30 * 1024, 8 * 1024):
            ids1 = enqueue("qa_scenario", qa_run_id="run-1", count=2)
            # Acquire the first batch
            granted1 = try_acquire(ids1)
            assert len(granted1) == 2  # 30 + 2*8 = 46 <= 48

            # Now enqueue more — only 2G headroom left, not enough for 8G
            ids2 = enqueue("qa_scenario", qa_run_id="run-1", count=1)
            granted2 = try_acquire(ids2)
            assert len(granted2) == 0

    def test_respects_priority_ordering(self, tmp_path):
        """In priority mode, lower-priority entries wait for higher-priority."""
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 30 * 1024, 8 * 1024), \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="priority-drain"):
            # Enqueue qa first, then impl
            qa_ids = enqueue("qa_scenario", qa_run_id="run-1", count=1)
            impl_ids = enqueue("impl", count=1)

            # Try acquiring qa — impl has higher priority and is waiting,
            # but qa was enqueued first. In priority mode, qa still gets
            # served because impl is a different entry in try_acquire's walk.
            # The impl entry adds its projected memory to `used`.
            qa_granted = try_acquire(qa_ids)
            # 30G + 8G (impl projected) + 8G (qa) = 46G <= 48G — fits
            assert len(qa_granted) == 1

    def test_skip_entries_that_dont_fit(self, tmp_path):
        """E17: entries that don't fit should be skipped, not block the queue."""
        # impl needs 16G, qa needs 4G, target 48G, used 36G
        # headroom = 12G: impl doesn't fit but qa does
        with _patch_home(tmp_path), \
             patch("pm_core.memory_governor.get_memory_target",
                   return_value=48 * 1024), \
             patch("pm_core.memory_governor.get_current_used_mb",
                   return_value=36 * 1024), \
             patch("pm_core.memory_governor.project_memory") as mock_proj, \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="fifo"):
            mock_proj.side_effect = lambda t: 16 * 1024 if t == "impl" else 4 * 1024
            impl_ids = enqueue("impl", count=1)
            qa_ids = enqueue("qa_scenario", qa_run_id="run-1", count=1)

            qa_granted = try_acquire(qa_ids)
            # impl doesn't fit (36+16=52 > 48), so its projected memory
            # is NOT counted (E17).  qa fits: 36+4=40 <= 48.
            assert len(qa_granted) == 1


# ---------------------------------------------------------------------------
# enqueue_and_try_acquire
# ---------------------------------------------------------------------------

class TestEnqueueAndTryAcquire:
    def test_governor_inactive(self, tmp_path):
        with _patch_home(tmp_path), _patch_governor_inactive():
            eid, acquired = enqueue_and_try_acquire("impl")
            assert acquired is True
            assert len(eid) == 8

    def test_within_budget(self, tmp_path):
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 30 * 1024, 8 * 1024), \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="fifo"):
            eid, acquired = enqueue_and_try_acquire("impl")
            assert acquired is True

    def test_over_budget(self, tmp_path):
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 44 * 1024, 8 * 1024), \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="fifo"):
            eid, acquired = enqueue_and_try_acquire("impl")
            assert acquired is False
            # Entry should be in queue as waiting
            q = _load_queue()
            assert any(e["id"] == eid and e["status"] == "waiting"
                       for e in q["entries"])

    def test_priority_respects_higher_waiting(self, tmp_path):
        """In priority mode, don't jump ahead of higher-priority entries."""
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 30 * 1024, 8 * 1024), \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="priority-drain"):
            # Enqueue impl (higher priority) first
            impl_ids = enqueue("impl", count=1)
            # Now try enqueue_and_try_acquire for qa (lower priority)
            qa_eid, acquired = enqueue_and_try_acquire("qa_scenario")
            # impl is waiting with higher priority — qa should not jump
            assert acquired is False


# ---------------------------------------------------------------------------
# get_queue_status
# ---------------------------------------------------------------------------

class TestGetQueueStatus:
    def test_returns_snapshot(self, tmp_path):
        with _patch_home(tmp_path):
            enqueue("impl", count=2)
            status = get_queue_status()
            assert len(status["entries"]) == 2

    def test_empty_when_no_file(self, tmp_path):
        with _patch_home(tmp_path):
            status = get_queue_status()
            assert status["entries"] == []


# ---------------------------------------------------------------------------
# Queue policy setting
# ---------------------------------------------------------------------------

class TestQueuePolicy:
    def test_default_fifo(self):
        with patch("pm_core.launch_queue.get_global_setting_value",
                   return_value=""):
            assert get_queue_policy() == "fifo"

    def test_valid_policies(self):
        for policy in VALID_POLICIES:
            with patch("pm_core.launch_queue.get_global_setting_value",
                       return_value=policy):
                assert get_queue_policy() == policy

    def test_invalid_falls_back_fifo(self):
        with patch("pm_core.launch_queue.get_global_setting_value",
                   return_value="invalid"):
            assert get_queue_policy() == "fifo"
