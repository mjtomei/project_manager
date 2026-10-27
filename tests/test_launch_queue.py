"""Tests for pm_core.launch_queue."""

import contextlib
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core.launch_queue import (
    enqueue,
    try_acquire,
    enqueue_and_try_acquire,
    dequeue,
    get_queue_status,
    get_queue_policy,
    governor_lock,
    keepalive,
    keepalive_during,
    try_acquire_detailed,
    GovernorLockTimeout,
    _INSTANCE,
    _WAITING_TTL,
    _ACQUIRED_TTL,
    _sort_queue,
    _clean_stale,
    _proc_start_time,
    _load_queue,
    _save_queue,
    VALID_POLICIES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _patch_home(tmp_path):
    """Patch pm_home to use a temp directory."""
    return patch("pm_core.launch_queue.pm_home", return_value=tmp_path)


def _patch_governor_inactive():
    """Patch get_memory_target to return None (governor inactive)."""
    return patch("pm_core.memory_governor.get_memory_target", return_value=None)


@contextlib.contextmanager
def _patch_governor_active(target_mb=48 * 1024, current_mb=30 * 1024,
                           projection_mb=8 * 1024, *, running=(),
                           error=""):
    """Context manager patching an active governor.

    *current_mb* is the committed usage the snapshot reports, *running*
    the names of running pm containers, *error* a measurement failure.
    *projection_mb* is a number or a ``ctype -> MB`` callable.
    """
    from pm_core.memory_governor import MemorySnapshot

    def _snap(stats=None):
        return MemorySnapshot(target_mb=target_mb, scope="pm",
                              used_mb=None if error else current_mb,
                              measured_mb=None if error else current_mb,
                              running_names=set(running), error=error)

    def _proj(ctype, stats=None):
        return projection_mb(ctype) if callable(projection_mb) else projection_mb

    with patch("pm_core.memory_governor.get_memory_target",
               return_value=target_mb), \
         patch("pm_core.memory_governor.take_snapshot", side_effect=_snap), \
         patch("pm_core.memory_governor.project_memory", side_effect=_proj), \
         patch("pm_core.memory_governor.load_stats", return_value={}):
        yield


# ---------------------------------------------------------------------------
# governor_lock
# ---------------------------------------------------------------------------

class TestGovernorLock:
    def test_lock_acquires_and_releases(self, tmp_path):
        with _patch_home(tmp_path):
            with governor_lock() as acquired:
                assert acquired is True
                # Lock file should exist
                assert (tmp_path / "governor.lock").exists()

    def test_lock_timeout_raises(self, tmp_path):
        """A busy lock raises instead of letting the caller proceed unlocked."""
        import fcntl

        with _patch_home(tmp_path):
            lock_path = tmp_path / "governor.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            # Hold the lock from another fd
            blocker = open(lock_path, "w")
            fcntl.flock(blocker, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with pytest.raises(GovernorLockTimeout):
                    with governor_lock(timeout=0.1):
                        pytest.fail("entered the critical section unlocked")
            finally:
                blocker.close()


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

    def test_wrong_typed_entries_are_dropped(self, tmp_path):
        """A hand-edited file must not raise in every admission."""
        now = time.time()
        good = {"id": "ok", "pid": os.getpid(), "status": "waiting",
                "enqueued_at": now, "heartbeat_at": now}
        bad = [
            {"id": "x1", "pid": "abc", "status": "waiting",
             "enqueued_at": "x", "heartbeat_at": "x"},
            {"id": "x2", "pid": True},
            {"id": "x3", "pid": 1, "acquired_at": [1]},
            {"id": "x4", "status": 3},
            {"id": 5},
        ]
        with _patch_home(tmp_path):
            (tmp_path / "launch-queue.json").write_text(json.dumps(
                {"entries": bad + [good], "last_served_qa_run": 7}))
            q = _load_queue()
            assert [e["id"] for e in q["entries"]] == ["ok"]
            assert q["last_served_qa_run"] is None

    def test_wrong_typed_entry_does_not_break_admission(self, tmp_path):
        with _patch_home(tmp_path), _patch_governor_inactive():
            (tmp_path / "launch-queue.json").write_text(json.dumps(
                {"entries": [{"id": "x1", "pid": "abc", "status": "waiting",
                              "enqueued_at": "x", "heartbeat_at": "x"}]}))
            eid, acquired, reason = enqueue_and_try_acquire("impl")
            assert acquired and reason == ""
            ids = [e["id"] for e in json.loads(
                (tmp_path / "launch-queue.json").read_text())["entries"]]
            assert ids == [eid]


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
            enqueue("impl", count=1)

            # impl sorts first and reserves its 8G: 30 + 8 + 8 = 46 <= 48,
            # so qa still fits behind it.
            qa_granted = try_acquire(qa_ids)
            assert len(qa_granted) == 1

    def test_priority_holds_back_when_only_one_fits(self, tmp_path):
        """Room for one: the waiting impl is served before an earlier qa."""
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 36 * 1024, 8 * 1024), \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="priority-drain"):
            qa_ids = enqueue("qa_scenario", qa_run_id="run-1", count=1)
            enqueue("impl", count=1)
            result = try_acquire_detailed(qa_ids)
            assert result.granted == []
            assert "target" in result.reason

    def test_skip_entries_that_dont_fit(self, tmp_path):
        """E17: entries that don't fit should be skipped, not block the queue."""
        # impl needs 16G, qa needs 4G, target 48G, used 36G
        # headroom = 12G: impl doesn't fit but qa does
        with _patch_home(tmp_path), \
             _patch_governor_active(
                 48 * 1024, 36 * 1024,
                 lambda t: 16 * 1024 if t == "impl" else 4 * 1024), \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="fifo"):
            enqueue("impl", count=1)
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
            eid, acquired, reason = enqueue_and_try_acquire("impl")
            assert acquired is True
            assert eid and reason == ""

    def test_within_budget(self, tmp_path):
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 30 * 1024, 8 * 1024), \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="fifo"):
            eid, acquired, _ = enqueue_and_try_acquire("impl")
            assert acquired is True

    def test_over_budget(self, tmp_path):
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 44 * 1024, 8 * 1024), \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="fifo"):
            eid, acquired, reason = enqueue_and_try_acquire("impl")
            assert acquired is False
            assert "projected" in reason and "target" in reason
            # Entry should be in queue as waiting
            q = _load_queue()
            assert any(e["id"] == eid and e["status"] == "waiting"
                       for e in q["entries"])

    def test_priority_respects_higher_waiting(self, tmp_path):
        """In priority mode, don't jump ahead of higher-priority entries."""
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 36 * 1024, 8 * 1024), \
             patch("pm_core.launch_queue.get_queue_policy",
                   return_value="priority-drain"):
            # Enqueue impl (higher priority) first; room for only one.
            enqueue("impl", count=1)
            qa_eid, acquired, _ = enqueue_and_try_acquire("qa_scenario")
            # impl is waiting with higher priority — qa should not jump
            assert acquired is False

    def test_key_reuses_entry(self, tmp_path):
        """Repeated attempts for one container don't pile up entries."""
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 44 * 1024, 8 * 1024):
            a, ok_a, _ = enqueue_and_try_acquire("impl", key="pm-t-impl-pr-1")
            b, ok_b, _ = enqueue_and_try_acquire("impl", key="pm-t-impl-pr-1")
            assert a == b and not ok_a and not ok_b
            assert len(_load_queue()["entries"]) == 1

    def test_leftover_own_grant_is_readmitted(self, tmp_path):
        """Regression: a grant left behind by a dequeue that hit a busy
        lock made the next launch of the same container refuse with an
        empty reason (and dequeue the entry under it)."""
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 30 * 1024, 8 * 1024):
            a, ok_a, _ = enqueue_and_try_acquire("impl", key="pm-t-impl-pr-1")
            assert ok_a  # ...and the dequeue after launch never happened
            b, ok_b, reason = enqueue_and_try_acquire("impl", key="pm-t-impl-pr-1")
            assert (b, ok_b, reason) == (a, True, "")
            assert len(_load_queue()["entries"]) == 1
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 44 * 1024, 8 * 1024):
            _, ok_c, reason = enqueue_and_try_acquire("impl", key="pm-t-impl-pr-1")
            assert not ok_c and "target" in reason

    def test_lock_busy_refuses(self, tmp_path):
        with _patch_home(tmp_path), \
             patch("pm_core.launch_queue.governor_lock",
                   side_effect=GovernorLockTimeout("busy")):
            eid, acquired, reason = enqueue_and_try_acquire("impl")
        assert (eid, acquired) == (None, False)
        assert "busy" in reason


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

    def test_omits_entries_of_dead_owner(self, tmp_path):
        """A SIGKILLed process's entries don't count as queue depth."""
        with _patch_home(tmp_path):
            enqueue("impl")
            data = _load_queue()
            data["entries"].append({
                "id": "dead", "pid": 999999999, "container_type": "qa_scenario",
                "status": "waiting", "enqueued_at": time.time(),
                "heartbeat_at": time.time(),
            })
            _save_queue(data)
            status = get_queue_status()
            assert [e["container_type"] for e in status["entries"]] == ["impl"]
            # Display only: the file is pruned by the next locked walk.
            assert len(_load_queue()["entries"]) == 2

    def test_display_filter_does_not_log_removal(self, tmp_path):
        """Only a real prune logs "Removing stale queue entry"."""
        with _patch_home(tmp_path):
            _save_queue({"entries": [{
                "id": "dead", "pid": 999999999, "container_type": "qa_scenario",
                "status": "waiting", "enqueued_at": time.time(),
                "heartbeat_at": time.time(),
            }], "last_served_qa_run": None})
            with patch("pm_core.launch_queue._log") as log:
                assert get_queue_status()["entries"] == []
            assert not any("Removing stale queue entry" in c.args[0]
                           for c in log.info.call_args_list)


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


# ---------------------------------------------------------------------------
# Fail-closed admission and reservation accounting
# ---------------------------------------------------------------------------

class TestFailClosed:
    def test_measurement_failure_grants_nothing(self, tmp_path):
        """Failed stats must not read as zero usage and admit the launch."""
        with _patch_home(tmp_path), \
             _patch_governor_active(error="podman stats failed (rc=125)"):
            ids = enqueue("qa_scenario", qa_run_id="run-1", count=2)
            result = try_acquire_detailed(ids)
        assert result.granted == []
        assert "memory measurement unavailable" in result.reason
        assert "rc=125" in result.reason

    def test_measurement_failure_refuses_fast_path(self, tmp_path):
        with _patch_home(tmp_path), _patch_governor_active(error="stats down"):
            _eid, acquired, reason = enqueue_and_try_acquire("impl")
        assert acquired is False
        assert "stats down" in reason

    def test_lock_busy_grants_nothing(self, tmp_path):
        with _patch_home(tmp_path), _patch_governor_inactive():
            ids = enqueue("qa_scenario", count=1)
        with _patch_home(tmp_path), \
             patch("pm_core.launch_queue.governor_lock",
                   side_effect=GovernorLockTimeout("lock busy")):
            result = try_acquire_detailed(ids)
        assert result.granted == []
        assert "lock busy" in result.reason

    def test_invalid_target_grants_nothing(self, tmp_path):
        from pm_core.memory_governor import GovernorConfigError
        with _patch_home(tmp_path), _patch_governor_inactive():
            ids = enqueue("qa_scenario", count=1)
        with _patch_home(tmp_path), \
             patch("pm_core.memory_governor.get_memory_target",
                   side_effect=GovernorConfigError("invalid target 'x'")):
            result = try_acquire_detailed(ids)
        assert result.granted == []
        assert "invalid target" in result.reason


class TestInflightReservations:
    def test_acquired_entry_reserves_until_container_runs(self, tmp_path):
        """A grant reserves its projection until its container is visible."""
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 32 * 1024, 8 * 1024):
            first = enqueue("qa_scenario", qa_run_id="r", count=1,
                            keys=["r:s1"], container_names=["pm-qa-r-s1"])
            assert try_acquire(first) == first
            # 32 + 8 (reserved for s1) + 8 = 48: s2 just fits.
            second = enqueue("qa_scenario", qa_run_id="r", keys=["r:s2"],
                             container_names=["pm-qa-r-s2"])
            third = enqueue("qa_scenario", qa_run_id="r", keys=["r:s3"],
                            container_names=["pm-qa-r-s3"])
            assert try_acquire(second) == second
            assert try_acquire(third) == []

        # Once s1 and s2 run, the snapshot carries them (usage + growth),
        # so their entries stop reserving on top.
        with _patch_home(tmp_path), \
             _patch_governor_active(48 * 1024, 32 * 1024, 8 * 1024,
                                    running={"pm-qa-r-s1", "pm-qa-r-s2"}):
            assert try_acquire(third) == third


class TestOwnership:
    def _entry(self, **kw):
        base = {"id": "e1", "container_type": "qa_scenario",
                "status": "waiting", "enqueued_at": time.time(),
                "heartbeat_at": time.time()}
        base.update(kw)
        return base

    def test_previous_instance_of_this_pid_is_stale(self):
        """pm restarts re-exec in place: same PID, new instance."""
        e = self._entry(pid=os.getpid(), instance="old-instance")
        assert _clean_stale([e]) == []

    def test_current_instance_kept(self):
        e = self._entry(pid=os.getpid(), instance=_INSTANCE)
        assert _clean_stale([e]) == [e]

    def test_recycled_pid_is_stale(self):
        e = self._entry(pid=os.getppid(), pid_start="1")
        assert _clean_stale([e]) == []

    def test_unreaped_zombie_owner_is_stale(self):
        """A SIGKILLed owner its parent has not reaped yet is dead."""
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        try:
            deadline = time.time() + 5
            while (Path(f"/proc/{pid}/stat").read_text()
                   .rsplit(")", 1)[1].split()[0] != "Z"
                   and time.time() < deadline):
                time.sleep(0.01)
            e = self._entry(pid=pid, pid_start=_proc_start_time(pid))
            assert _clean_stale([e]) == []
        finally:
            os.waitpid(pid, 0)

    def test_waiting_without_heartbeat_expires(self):
        now = time.time()
        e = self._entry(pid=os.getpid(), instance=_INSTANCE,
                        heartbeat_at=now - _WAITING_TTL - 1)
        assert _clean_stale([e], now) == []

    def test_acquired_reservation_expires(self):
        now = time.time()
        e = self._entry(pid=os.getpid(), instance=_INSTANCE,
                        status="acquired", acquired_at=now - _ACQUIRED_TTL - 1)
        assert _clean_stale([e], now) == []

    def test_keepalive_renews_waiting_entry(self, tmp_path):
        with _patch_home(tmp_path):
            [eid] = enqueue("qa_scenario", qa_run_id="r", count=1)
            q = _load_queue()
            q["entries"][0]["heartbeat_at"] = time.time() - _WAITING_TTL + 5
            _save_queue(q)
            assert keepalive([eid])
            assert time.time() - _load_queue()["entries"][0]["heartbeat_at"] < 5

    def test_resumed_run_adopts_its_place_in_line(self, tmp_path):
        """After a restart (same PID, new instance) re-enqueueing under the
        same key adopts the old entry and keeps its enqueued_at."""
        with _patch_home(tmp_path):
            [first] = enqueue("qa_scenario", qa_run_id="r", keys=["r:s1"])
            q = _load_queue()
            q["entries"][0]["instance"] = "pre-restart"
            q["entries"][0]["enqueued_at"] = 1.0
            _save_queue(q)
            [again] = enqueue("qa_scenario", qa_run_id="r", keys=["r:s1"])
            entries = _load_queue()["entries"]
        assert again == first
        assert len(entries) == 1
        assert entries[0]["enqueued_at"] == 1.0
        assert entries[0]["instance"] == _INSTANCE

    def test_keepalive_during_renews_while_blocked(self, tmp_path):
        """A QA launch blocks on its refiners for minutes; the scenarios
        still waiting for memory must not expire meanwhile."""
        with _patch_home(tmp_path):
            [eid] = enqueue("qa_scenario", qa_run_id="r", count=1)
            q = _load_queue()
            q["entries"][0]["heartbeat_at"] = time.time() - _WAITING_TTL + 5
            _save_queue(q)
            with keepalive_during({eid}, interval=0.01):
                deadline = time.time() + 5
                while (time.time() - _load_queue()["entries"][0]["heartbeat_at"] > 5
                       and time.time() < deadline):
                    time.sleep(0.01)
            assert time.time() - _load_queue()["entries"][0]["heartbeat_at"] < 5

    def test_keepalive_during_nothing_to_renew(self):
        with patch("pm_core.launch_queue.keepalive") as ka, \
             patch("pm_core.launch_queue.threading.Thread") as thread:
            with keepalive_during(set(), interval=0.01):
                pass
        thread.assert_not_called()
        ka.assert_not_called()
