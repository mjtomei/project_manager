"""Regression test for the concurrent review-window launch race (QA scenario 4
of pr-8409c64).

Two ``pm pr review --fresh`` launches firing at nearly the same instant for the
same PR both performed a non-atomic *find window -> kill if fresh -> create*
sequence, both observed "no window", and both created one — leaving a duplicate
``review-<display_id>`` tmux window.  A duplicate makes
``select-window -t sess:review-<id>`` ambiguous (it fails), so the popup
spinner's focus switch silently no-ops.

The fix wraps that sequence in :func:`_review_window_launch_lock`, an
``fcntl.flock`` keyed by (session, window_name), so concurrent launches
serialise and the second supersedes the first rather than racing.

This test asserts the lock provides cross-holder mutual exclusion: two threads
each entering the context manager for the same (session, window) never overlap.
"""

import threading
import time

from pm_core.cli.pr import _review_window_launch_lock


def test_launch_lock_serialises_same_window(tmp_path, monkeypatch):
    # Point pm_home at a temp dir so the lock file lands there.
    import pm_core.paths as paths_mod
    monkeypatch.setattr(paths_mod, "pm_home", lambda: tmp_path)

    overlap = {"max_concurrent": 0, "current": 0}
    lock = threading.Lock()

    def worker():
        with _review_window_launch_lock("pm-sess", "review-pr-001"):
            with lock:
                overlap["current"] += 1
                overlap["max_concurrent"] = max(
                    overlap["max_concurrent"], overlap["current"])
            # Hold the critical section briefly so an unserialised peer
            # would be observed running concurrently.
            time.sleep(0.2)
            with lock:
                overlap["current"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(2)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.monotonic() - t0

    # Mutual exclusion: never more than one holder at a time.
    assert overlap["max_concurrent"] == 1
    # Serialised, not parallel: two 0.2s holds run back-to-back (~0.4s),
    # not overlapped (~0.2s).
    assert elapsed >= 0.38


def test_launch_lock_distinct_windows_do_not_block(tmp_path, monkeypatch):
    """Different windows use different lock files → no serialisation."""
    import pm_core.paths as paths_mod
    monkeypatch.setattr(paths_mod, "pm_home", lambda: tmp_path)

    overlap = {"max_concurrent": 0, "current": 0}
    lock = threading.Lock()

    def worker(win):
        with _review_window_launch_lock("pm-sess", win):
            with lock:
                overlap["current"] += 1
                overlap["max_concurrent"] = max(
                    overlap["max_concurrent"], overlap["current"])
            time.sleep(0.2)
            with lock:
                overlap["current"] -= 1

    threads = [
        threading.Thread(target=worker, args=("review-pr-001",)),
        threading.Thread(target=worker, args=("review-pr-002",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Distinct windows can hold their locks concurrently.
    assert overlap["max_concurrent"] == 2
