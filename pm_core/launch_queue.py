"""Cross-process launch queue with fairness policies.

Serialises memory governor operations across multiple pm processes via
``fcntl.flock`` and provides a global launch queue so that concurrent
QA runs share memory fairly.

Queue file: ``~/.pm/launch-queue.json``
Lock file:  ``~/.pm/governor.lock``

Queue policy (``pm container set system-memory-queue-policy``):
  fifo                 — strict time ordering, no type priority
  priority-drain       — impl > review > qa; drain one QA run before next
  priority-round-robin — impl > review > qa; alternate between QA runs
"""

import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from pm_core.paths import configure_logger, pm_home, get_global_setting_value

_log = configure_logger("pm.launch_queue")

_QUEUE_FILE = "launch-queue.json"
_LOCK_FILE = "governor.lock"
_DEFAULT_LOCK_TIMEOUT = 10.0

# Type priority for priority modes (lower = higher priority)
_TYPE_PRIORITY = {
    "impl": 0,
    "review": 1,
    "qa_scenario": 2,
    "qa_planner": 2,
}

VALID_POLICIES = ("fifo", "priority-drain", "priority-round-robin")


# ---------------------------------------------------------------------------
# Cross-process file lock
# ---------------------------------------------------------------------------

@contextmanager
def governor_lock(timeout: float = _DEFAULT_LOCK_TIMEOUT):
    """Acquire an exclusive cross-process lock on ``~/.pm/governor.lock``.

    Uses ``fcntl.flock`` following the same pattern as
    ``pane_registry.locked_read_modify_write``.  The lock serialises all
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


# ---------------------------------------------------------------------------
# Queue file I/O
# ---------------------------------------------------------------------------

def _queue_path() -> Path:
    return pm_home() / _QUEUE_FILE


def _load_queue() -> dict:
    """Load queue from disk.  Returns empty structure on missing/corrupt file."""
    path = _queue_path()
    if not path.exists():
        return {"entries": [], "last_served_qa_run": None}
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return {"entries": [], "last_served_qa_run": None}
        data.setdefault("entries", [])
        data.setdefault("last_served_qa_run", None)
        return data
    except (json.JSONDecodeError, OSError) as e:
        _log.warning("Failed to load queue file %s: %s", path, e)
        return {"entries": [], "last_served_qa_run": None}


def _save_queue(data: dict) -> None:
    """Write queue atomically (temp + rename)."""
    path = _queue_path()
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(path)
    except OSError as e:
        _log.warning("Failed to save queue file %s: %s", path, e)


# ---------------------------------------------------------------------------
# Queue policy
# ---------------------------------------------------------------------------

def get_queue_policy() -> str:
    """Read the queue policy setting.  Default: fifo."""
    raw = get_global_setting_value(
        "container-system-memory-queue-policy", "fifo")
    if raw in VALID_POLICIES:
        return raw
    _log.warning("Invalid queue policy %r — using fifo", raw)
    return "fifo"


# ---------------------------------------------------------------------------
# Stale entry cleanup
# ---------------------------------------------------------------------------

def _is_pid_alive(pid: int) -> bool:
    """Check if a process is still alive."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _clean_stale(entries: list[dict]) -> list[dict]:
    """Remove entries from dead processes."""
    alive = []
    for entry in entries:
        pid = entry.get("pid")
        if pid is not None and not _is_pid_alive(pid):
            _log.info("Removing stale queue entry %s (pid %d dead)",
                      entry.get("id", "?"), pid)
            continue
        alive.append(entry)
    return alive


# ---------------------------------------------------------------------------
# Policy sorting
# ---------------------------------------------------------------------------

def _sort_queue(entries: list[dict], policy: str,
                last_served_qa_run: str | None) -> list[dict]:
    """Sort queue entries according to the active policy."""
    if policy == "fifo":
        return sorted(entries, key=lambda e: e.get("enqueued_at", 0))

    # Priority modes: split into non-QA and QA
    non_qa = [e for e in entries
              if _TYPE_PRIORITY.get(e.get("container_type", ""), 2) < 2]
    qa = [e for e in entries
          if _TYPE_PRIORITY.get(e.get("container_type", ""), 2) >= 2]

    # Sort non-QA by (priority, enqueue time)
    non_qa.sort(key=lambda e: (
        _TYPE_PRIORITY.get(e.get("container_type", ""), 2),
        e.get("enqueued_at", 0),
    ))

    if policy == "priority-drain":
        qa = _sort_qa_drain(qa)
    elif policy == "priority-round-robin":
        qa = _sort_qa_round_robin(qa, last_served_qa_run)

    return non_qa + qa


def _sort_qa_drain(entries: list[dict]) -> list[dict]:
    """Group QA entries by run, order groups by earliest entry, concatenate."""
    groups: dict[str, list[dict]] = {}
    for e in entries:
        run_id = e.get("qa_run_id") or "__none__"
        groups.setdefault(run_id, []).append(e)

    # Sort entries within each group by enqueue time
    for group in groups.values():
        group.sort(key=lambda e: e.get("enqueued_at", 0))

    # Order groups by their earliest entry
    ordered_groups = sorted(
        groups.values(),
        key=lambda g: g[0].get("enqueued_at", 0),
    )

    result = []
    for group in ordered_groups:
        result.extend(group)
    return result


def _sort_qa_round_robin(entries: list[dict],
                         last_served: str | None) -> list[dict]:
    """Interleave QA entries across runs, starting after last_served."""
    groups: dict[str, list[dict]] = {}
    for e in entries:
        run_id = e.get("qa_run_id") or "__none__"
        groups.setdefault(run_id, []).append(e)

    # Sort entries within each group
    for group in groups.values():
        group.sort(key=lambda e: e.get("enqueued_at", 0))

    # Order group keys by earliest entry
    group_keys = sorted(
        groups.keys(),
        key=lambda k: groups[k][0].get("enqueued_at", 0),
    )

    # Rotate so we start after last_served
    if last_served and last_served in group_keys:
        idx = group_keys.index(last_served)
        group_keys = group_keys[idx + 1:] + group_keys[:idx + 1]

    # Interleave: take one from each group in order, repeat
    result = []
    while any(groups[k] for k in group_keys):
        for k in group_keys:
            if groups[k]:
                result.append(groups[k].pop(0))

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enqueue(container_type: str, qa_run_id: str | None = None,
            count: int = 1) -> list[str]:
    """Add entries to the launch queue.  Returns entry IDs.

    Must be called under ``governor_lock`` by the caller, or calls it
    internally if not already locked.
    """
    entries = []
    for _ in range(count):
        entry_id = uuid.uuid4().hex[:8]
        entries.append({
            "id": entry_id,
            "container_type": container_type,
            "pid": os.getpid(),
            "enqueued_at": time.time(),
            "qa_run_id": qa_run_id,
            "status": "waiting",
        })

    with governor_lock():
        queue = _load_queue()
        queue["entries"].extend(entries)
        _save_queue(queue)

    return [e["id"] for e in entries]


def try_acquire(entry_ids: list[str]) -> list[str]:
    """Try to acquire entries from the queue.

    Under lock: clean stale entries, sort by policy, walk sorted order.
    Grant entries from ``entry_ids`` that are next in line AND fit in
    memory.  Returns list of granted entry IDs (may be empty).

    Accounts for already-acquired entries' projected memory.
    """
    from pm_core.memory_governor import (
        get_memory_target, get_current_used_mb, project_memory,
    )

    target = get_memory_target()
    if target is None:
        # Governor inactive — grant everything
        with governor_lock():
            queue = _load_queue()
            granted = []
            for entry in queue["entries"]:
                if entry["id"] in entry_ids and entry.get("status") == "waiting":
                    entry["status"] = "acquired"
                    granted.append(entry["id"])
            _save_queue(queue)
        return granted

    my_ids = set(entry_ids)

    with governor_lock():
        queue = _load_queue()
        queue["entries"] = _clean_stale(queue["entries"])

        policy = get_queue_policy()
        sorted_entries = _sort_queue(
            [e for e in queue["entries"] if e.get("status") == "waiting"],
            policy, queue.get("last_served_qa_run"),
        )

        # Current memory usage
        current = get_current_used_mb()
        if current is None:
            # Can't measure — grant all requested
            _log.warning("Cannot measure memory — granting all requested entries")
            granted = []
            for entry in queue["entries"]:
                if entry["id"] in my_ids and entry.get("status") == "waiting":
                    entry["status"] = "acquired"
                    granted.append(entry["id"])
            _save_queue(queue)
            return granted

        # Add projected memory for already-acquired entries
        used = current
        for entry in queue["entries"]:
            if entry.get("status") == "acquired":
                used += project_memory(entry.get("container_type", "qa_scenario"))

        granted = []
        # Walk sorted waiting entries
        for entry in sorted_entries:
            projected = project_memory(entry.get("container_type", "qa_scenario"))

            if entry["id"] in my_ids:
                if used + projected <= target:
                    # Grant it
                    used += projected
                    granted.append(entry["id"])
                    # Update in the actual queue
                    for qe in queue["entries"]:
                        if qe["id"] == entry["id"]:
                            qe["status"] = "acquired"
                            break
                    # Track last served QA run for round-robin
                    if entry.get("qa_run_id"):
                        queue["last_served_qa_run"] = entry["qa_run_id"]
                # If doesn't fit, skip but continue walking (E17)
            else:
                # Not ours — account for its projected memory (it may launch soon)
                used += projected

        _save_queue(queue)

    return granted


def enqueue_and_try_acquire(container_type: str,
                            qa_run_id: str | None = None,
                            ) -> tuple[str, bool]:
    """Atomic fast path for impl/review: enqueue 1 + immediate try.

    Returns ``(entry_id, acquired)``.  Single lock round-trip.
    """
    from pm_core.memory_governor import (
        get_memory_target, get_current_used_mb, project_memory,
    )

    entry_id = uuid.uuid4().hex[:8]
    entry = {
        "id": entry_id,
        "container_type": container_type,
        "pid": os.getpid(),
        "enqueued_at": time.time(),
        "qa_run_id": qa_run_id,
        "status": "waiting",
    }

    target = get_memory_target()
    if target is None:
        # Governor inactive — enqueue as acquired
        with governor_lock():
            queue = _load_queue()
            entry["status"] = "acquired"
            queue["entries"].append(entry)
            _save_queue(queue)
        return entry_id, True

    with governor_lock():
        queue = _load_queue()
        queue["entries"] = _clean_stale(queue["entries"])
        queue["entries"].append(entry)

        # Check if we can acquire immediately
        current = get_current_used_mb()
        if current is None:
            # Can't measure — allow
            entry["status"] = "acquired"
            _save_queue(queue)
            return entry_id, True

        # Sum acquired entries' projected memory
        used = current
        for qe in queue["entries"]:
            if qe.get("status") == "acquired":
                used += project_memory(qe.get("container_type", "qa_scenario"))

        projected = project_memory(container_type)

        # In priority modes, check if any higher-priority entries are waiting
        policy = get_queue_policy()
        if policy != "fifo":
            my_priority = _TYPE_PRIORITY.get(container_type, 2)
            for qe in queue["entries"]:
                if (qe["id"] != entry_id
                        and qe.get("status") == "waiting"
                        and _TYPE_PRIORITY.get(
                            qe.get("container_type", ""), 2) < my_priority):
                    # Higher priority entry waiting — don't jump queue
                    _save_queue(queue)
                    return entry_id, False

        if used + projected <= target:
            entry["status"] = "acquired"
            _save_queue(queue)
            return entry_id, True

        _save_queue(queue)
        return entry_id, False


def dequeue(entry_ids: list[str] | str) -> None:
    """Remove entries from the queue (post-launch cleanup, cancellation).

    Accepts a single ID or a list of IDs.
    """
    if isinstance(entry_ids, str):
        entry_ids = [entry_ids]
    ids_to_remove = set(entry_ids)

    with governor_lock():
        queue = _load_queue()
        queue["entries"] = [
            e for e in queue["entries"] if e["id"] not in ids_to_remove
        ]
        _save_queue(queue)


def get_queue_status() -> dict:
    """Read-only snapshot of the queue for status display.

    Returns the queue data without acquiring a lock (best-effort read).
    """
    return _load_queue()
