"""Tests for pm_core.governor_lock."""

import multiprocessing
import time
from unittest.mock import patch

from pm_core.governor_lock import governor_lock


def _hold_lock(lock_path_parent, hold_seconds, ready_path):
    """Helper for cross-process test: acquire lock, mark ready, sleep."""
    from pathlib import Path
    with patch("pm_core.governor_lock.pm_home", return_value=Path(lock_path_parent)):
        with governor_lock(timeout=5.0) as acquired:
            assert acquired
            Path(ready_path).touch()
            time.sleep(hold_seconds)


class TestGovernorLock:
    def test_acquires_lock(self, tmp_path):
        with patch("pm_core.governor_lock.pm_home", return_value=tmp_path):
            with governor_lock(timeout=1.0) as acquired:
                assert acquired

    def test_creates_lock_file(self, tmp_path):
        with patch("pm_core.governor_lock.pm_home", return_value=tmp_path):
            with governor_lock(timeout=1.0):
                assert (tmp_path / "governor.lock").exists()

    def test_creates_parent_dir(self, tmp_path):
        nested = tmp_path / "nested" / "dir"
        with patch("pm_core.governor_lock.pm_home", return_value=nested):
            with governor_lock(timeout=1.0) as acquired:
                assert acquired
                assert nested.exists()

    def test_serialises_across_processes(self, tmp_path):
        ready = tmp_path / "ready"
        ctx = multiprocessing.get_context("fork")
        proc = ctx.Process(target=_hold_lock, args=(str(tmp_path), 1.0, str(ready)))
        proc.start()
        try:
            # Wait for child to acquire
            for _ in range(50):
                if ready.exists():
                    break
                time.sleep(0.05)
            assert ready.exists()

            # Now try to acquire with short timeout — child holds it
            t0 = time.monotonic()
            with patch("pm_core.governor_lock.pm_home", return_value=tmp_path):
                with governor_lock(timeout=0.2) as acquired:
                    elapsed = time.monotonic() - t0
                    # Either we waited until child released or timed out
                    # In either case at least 0.2s elapsed
                    assert elapsed >= 0.15
                    # Child should still be holding when we time out at 0.2s
                    # (child holds for 1.0s)
                    assert acquired is False
        finally:
            proc.join(timeout=3.0)

    def test_timeout_yields_unacquired(self, tmp_path):
        # Manually open the lock first
        import fcntl
        lock_path = tmp_path / "governor.lock"
        lock_path.touch()
        holder = open(lock_path, "w")
        fcntl.flock(holder, fcntl.LOCK_EX)
        try:
            with patch("pm_core.governor_lock.pm_home", return_value=tmp_path):
                with governor_lock(timeout=0.1) as acquired:
                    assert acquired is False
        finally:
            holder.close()
