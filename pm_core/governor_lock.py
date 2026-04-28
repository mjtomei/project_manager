"""Cross-process governor lock.

Provides a single ``fcntl.flock``-backed context manager used by the
memory governor and the launch queue to serialise reads/writes of their
shared on-disk state across multiple pm processes.

Lock file: ``~/.pm/governor.lock``
"""

import fcntl
import time
from contextlib import contextmanager

from pm_core.paths import configure_logger, pm_home

_log = configure_logger("pm.governor_lock")

_LOCK_FILE = "governor.lock"
_DEFAULT_LOCK_TIMEOUT = 10.0


@contextmanager
def governor_lock(timeout: float = _DEFAULT_LOCK_TIMEOUT):
    """Acquire an exclusive cross-process lock on ``~/.pm/governor.lock``.

    Uses ``fcntl.flock`` following the same pattern as
    ``pane_registry.locked_read_modify_write``.  The lock serialises
    governor operations: stats file writes, gate checks, and queue
    mutations.

    On timeout, logs a warning and yields anyway (graceful degradation —
    better to allow a launch than to deadlock).
    """
    lock_path = pm_home() / _LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_fd = open(lock_path, "w")
    acquired = False
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    _log.warning(
                        "Could not acquire governor lock within %.1fs "
                        "— proceeding without lock", timeout)
                    break
                time.sleep(0.01)
        yield acquired
    finally:
        lock_fd.close()  # closing fd releases the flock
