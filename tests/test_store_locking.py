"""Tests for advisory file locking in store.py."""

import multiprocessing
import os
import time
from pathlib import Path

import pytest
import yaml

from pm_core import store


@pytest.fixture
def project_dir(tmp_path):
    """Create a minimal project.yaml in a temp dir."""
    data = {
        "project": {"name": "test", "repo": "/tmp/repo", "base_branch": "main"},
        "plans": [],
        "prs": [],
    }
    path = tmp_path / "project.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f)
    return tmp_path


class TestLockedUpdate:
    """Tests for the locked_update() helper."""

    def test_basic_mutation(self, project_dir):
        """locked_update loads, mutates, and saves atomically."""
        def add_pr(data):
            data["prs"].append({"id": "pr-001", "title": "Test PR", "status": "pending"})

        result = store.locked_update(project_dir, add_pr)

        assert len(result["prs"]) == 1
        assert result["prs"][0]["id"] == "pr-001"

        # Verify it was saved to disk
        on_disk = store.load(project_dir)
        assert len(on_disk["prs"]) == 1
        assert on_disk["prs"][0]["id"] == "pr-001"

    def test_returns_updated_data(self, project_dir):
        """locked_update returns the data dict after mutation."""
        result = store.locked_update(
            project_dir,
            lambda d: d["project"].__setitem__("active_pr", "pr-001"),
        )
        assert result["project"]["active_pr"] == "pr-001"

    def test_loads_fresh_data(self, project_dir):
        """locked_update always loads fresh data from disk, not stale in-memory copy."""
        # Write directly to disk to simulate another process
        data = store.load(project_dir)
        data["prs"].append({"id": "pr-external", "title": "External", "status": "pending"})
        store.save(data, project_dir)

        # locked_update should see the external change
        def add_second(data):
            data["prs"].append({"id": "pr-002", "title": "Second", "status": "pending"})

        result = store.locked_update(project_dir, add_second)
        assert len(result["prs"]) == 2
        ids = {p["id"] for p in result["prs"]}
        assert "pr-external" in ids
        assert "pr-002" in ids

    def test_exception_in_fn_releases_lock(self, project_dir):
        """Lock is released even if the mutation function raises."""
        with pytest.raises(ValueError, match="boom"):
            store.locked_update(project_dir, lambda d: (_ for _ in ()).throw(ValueError("boom")))

        # Lock should be released — another locked_update should work
        store.locked_update(
            project_dir,
            lambda d: d["project"].__setitem__("active_pr", "pr-001"),
        )
        on_disk = store.load(project_dir)
        assert on_disk["project"]["active_pr"] == "pr-001"

    def test_exception_does_not_save(self, project_dir):
        """If fn raises, the data should NOT be saved to disk."""
        def bad_mutation(data):
            data["prs"].append({"id": "pr-bad", "title": "Bad"})
            raise RuntimeError("abort")

        with pytest.raises(RuntimeError, match="abort"):
            store.locked_update(project_dir, bad_mutation)

        on_disk = store.load(project_dir)
        assert len(on_disk["prs"]) == 0  # Nothing saved

    def test_lockfile_created(self, project_dir):
        """A .lock file is created during locking."""
        lock_path = project_dir / "project.yaml.lock"
        assert not lock_path.exists() or lock_path.stat().st_size == 0

        store.locked_update(project_dir, lambda d: None)
        # Lock file may exist after (we don't clean it up, just unlock)
        # The important thing is it doesn't prevent future operations
        store.locked_update(project_dir, lambda d: None)


class TestStoreLockTimeout:
    """Tests for lock timeout behavior."""

    def test_timeout_raises(self, project_dir):
        """Holding the lock causes a timeout for a second caller."""
        import fcntl

        lock_path = project_dir / "project.yaml.lock"
        # Hold the lock manually
        fd = open(lock_path, "w")
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with pytest.raises(store.StoreLockTimeout, match="Could not acquire lock"):
                store.locked_update(project_dir, lambda d: None, timeout=0.2)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

    def test_timeout_message_is_helpful(self, project_dir):
        """The timeout error message mentions the lockfile path."""
        import fcntl

        lock_path = project_dir / "project.yaml.lock"
        fd = open(lock_path, "w")
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with pytest.raises(store.StoreLockTimeout) as exc_info:
                store.locked_update(project_dir, lambda d: None, timeout=0.2)
            msg = str(exc_info.value)
            assert "project.yaml.lock" in msg
            assert "another pm process" in msg
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()


def _worker_locked_update(root_str, pr_id, result_dict):
    """Worker function for multiprocessing tests."""
    root = Path(root_str)
    try:
        def add_pr(data):
            data["prs"].append({"id": pr_id, "title": f"PR {pr_id}", "status": "pending"})

        store.locked_update(root, add_pr, timeout=5.0)
        result_dict[pr_id] = "ok"
    except Exception as e:
        result_dict[pr_id] = f"error: {e}"


class TestConcurrentAccess:
    """Tests for concurrent locked_update behavior."""

    def test_concurrent_updates_no_lost_writes(self, project_dir):
        """Two concurrent locked_updates should both succeed without lost writes."""
        manager = multiprocessing.Manager()
        results = manager.dict()

        p1 = multiprocessing.Process(
            target=_worker_locked_update,
            args=(str(project_dir), "pr-001", results),
        )
        p2 = multiprocessing.Process(
            target=_worker_locked_update,
            args=(str(project_dir), "pr-002", results),
        )

        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)

        assert results.get("pr-001") == "ok", f"Worker 1: {results.get('pr-001')}"
        assert results.get("pr-002") == "ok", f"Worker 2: {results.get('pr-002')}"

        # Both PRs should be in the final data
        data = store.load(project_dir)
        ids = {p["id"] for p in data["prs"]}
        assert "pr-001" in ids, f"pr-001 missing from {ids}"
        assert "pr-002" in ids, f"pr-002 missing from {ids}"

    def test_many_concurrent_updates(self, project_dir):
        """Many concurrent locked_updates should all succeed."""
        manager = multiprocessing.Manager()
        results = manager.dict()

        n = 5
        processes = []
        for i in range(n):
            p = multiprocessing.Process(
                target=_worker_locked_update,
                args=(str(project_dir), f"pr-{i:03d}", results),
            )
            processes.append(p)

        for p in processes:
            p.start()
        for p in processes:
            p.join(timeout=30)

        for i in range(n):
            pr_id = f"pr-{i:03d}"
            assert results.get(pr_id) == "ok", f"Worker {pr_id}: {results.get(pr_id)}"

        data = store.load(project_dir)
        ids = {p["id"] for p in data["prs"]}
        for i in range(n):
            assert f"pr-{i:03d}" in ids


class TestLockContextManager:
    """Tests for the _lock context manager directly."""

    def test_lock_basic(self, project_dir):
        """_lock context manager acquires and releases."""
        with store._lock(project_dir):
            # We have the lock — verify by trying non-blocking acquire
            import fcntl
            lock_path = project_dir / "project.yaml.lock"
            fd = open(lock_path, "w")
            try:
                with pytest.raises(OSError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                fd.close()

        # After context exit, lock should be released
        with store._lock(project_dir):
            pass  # Should not timeout
