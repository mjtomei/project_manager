"""Cross-process launch queue with fairness policies.

Serialises memory governor admission across pm processes via
``fcntl.flock`` and keeps a global launch queue so concurrent pm sessions
(and concurrent QA runs) share the memory budget fairly.

Queue file: ``~/.pm/launch-queue.json``
Lock file:  ``~/.pm/governor.lock``

Queue policy (``pm container set system-memory-queue-policy``):
  fifo                 — strict time ordering, no type priority
  priority-drain       — impl > review > rest; drain one QA run before next
  priority-round-robin — impl > review > rest; alternate between QA runs

Safety rules:
  - The lock never degrades to "proceed unlocked": a timeout raises
    :class:`GovernorLockTimeout` and callers treat it as "not admitted".
  - Admission never treats an unmeasurable host as empty: a memory
    measurement failure grants nothing (see
    :func:`pm_core.memory_governor.take_snapshot`).
  - An acquired entry reserves its projected memory until the container it
    was granted for is visibly running (its real usage and remaining growth
    are then counted from runtime stats) or the entry is dequeued.
  - Entries are owned by a process *instance* (pid + start time + a nonce
    regenerated on every exec), so entries from a dead process, a recycled
    PID, or this process's own pre-restart incarnation are dropped.  Waiting
    entries must be kept alive by their owner's retries; an owner that stops
    retrying loses its entries after ``_WAITING_TTL`` seconds.
"""

import fcntl
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.paths import configure_logger, pm_home, get_global_setting_value

_log = configure_logger("pm.launch_queue")

_QUEUE_FILE = "launch-queue.json"
_LOCK_FILE = "governor.lock"
# Admission measures runtime stats while holding the lock (seconds).
_DEFAULT_LOCK_TIMEOUT = 30.0

# A waiting entry whose owner has not retried for this long is abandoned.
_WAITING_TTL = 300.0
# An acquired entry whose container never appeared is released after this.
_ACQUIRED_TTL = 1800.0
# How often keepalive_during renews entries (well under _WAITING_TTL).
_KEEPALIVE_INTERVAL = 15.0

# Identifies this process image.  ``pm`` restarts re-exec in place (same
# PID), so the PID alone cannot tell a live owner from its previous self.
_INSTANCE = uuid.uuid4().hex

# Type priority for priority modes (lower = higher priority)
_TYPE_PRIORITY = {
    "impl": 0,
    "review": 1,
    "signoff": 1,
}
_QA_PRIORITY = 2

VALID_POLICIES = ("fifo", "priority-drain", "priority-round-robin")


class GovernorLockTimeout(RuntimeError):
    """The cross-process governor lock could not be acquired in time."""


# ---------------------------------------------------------------------------
# Cross-process file lock
# ---------------------------------------------------------------------------

@contextmanager
def governor_lock(timeout: float = _DEFAULT_LOCK_TIMEOUT):
    """Hold an exclusive cross-process lock on ``~/.pm/governor.lock``.

    Serialises stats writes, admission decisions and queue mutations.
    Raises :class:`GovernorLockTimeout` when the lock cannot be taken
    within *timeout* seconds (or the lock file cannot be opened) — callers
    must treat that as "not admitted", never as permission to proceed.
    """
    lock_path = pm_home() / _LOCK_FILE
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = open(lock_path, "w")
    except OSError as e:
        raise GovernorLockTimeout(f"cannot open governor lock {lock_path}: {e}") from e
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise GovernorLockTimeout(
                        f"governor lock busy for {timeout:.0f}s ({lock_path})")
                time.sleep(0.01)
        yield True
    finally:
        lock_fd.close()  # closing fd releases the flock


# ---------------------------------------------------------------------------
# Queue file I/O
# ---------------------------------------------------------------------------

def _queue_path() -> Path:
    return pm_home() / _QUEUE_FILE


def _empty_queue() -> dict:
    return {"entries": [], "last_served_qa_run": None}


def _load_queue() -> dict:
    """Load queue from disk.  Returns empty structure on missing/corrupt file."""
    path = _queue_path()
    if not path.exists():
        return _empty_queue()
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        _log.warning("Failed to load queue file %s: %s", path, e)
        return _empty_queue()
    if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
        return _empty_queue()
    data.setdefault("entries", [])
    if not isinstance(data.get("last_served_qa_run"), str):
        data["last_served_qa_run"] = None
    entries = []
    for e in data["entries"]:
        if _valid_entry(e):
            entries.append(e)
        else:
            _log.warning("Dropping malformed queue entry %r", e)
    data["entries"] = entries
    return data


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _valid_entry(e) -> bool:
    """True when *e* has the field types the queue logic relies on."""
    if not isinstance(e, dict) or not e.get("id") or not isinstance(e["id"], str):
        return False
    pid = e.get("pid")
    if pid is not None and (not isinstance(pid, int) or isinstance(pid, bool)):
        return False
    for k in ("enqueued_at", "heartbeat_at", "acquired_at"):
        if e.get(k) is not None and not _is_number(e[k]):
            return False
    for k in ("status", "container_type", "key", "container_name",
              "qa_run_id", "instance", "pid_start"):
        if e.get(k) is not None and not isinstance(e[k], str):
            return False
    return True


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
# Ownership and stale entry cleanup
# ---------------------------------------------------------------------------

def _proc_stat_fields(pid: int) -> list[str] | None:
    """Fields of ``/proc/<pid>/stat`` from field 3 (state) on, or None."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # comm (field 2) may contain spaces; split after its closing paren.
    return stat.rsplit(")", 1)[-1].split()


def _proc_start_time(pid: int) -> str | None:
    """Kernel start time of *pid* (clock ticks since boot), or None."""
    fields = _proc_stat_fields(pid)
    # starttime is field 22, i.e. index 19 counting from field 3.
    if not fields or len(fields) < 20:
        return None
    return fields[19]


def _is_pid_alive(pid: int) -> bool:
    """Check if a process is still alive.

    A zombie (killed but not yet reaped by its parent, e.g. a SIGKILLed TUI
    whose tmux server has not waited on it) still answers ``kill(pid, 0)``
    but can never renew or release its entries, so it counts as dead.
    """
    try:
        os.kill(pid, 0)
    except PermissionError:
        pass  # exists, owned by someone else
    except (OSError, ProcessLookupError):
        return False
    fields = _proc_stat_fields(pid)
    return not (fields and fields[0] in ("Z", "X"))


def _owner_fields() -> dict:
    pid = os.getpid()
    return {"pid": pid, "pid_start": _proc_start_time(pid),
            "instance": _INSTANCE}


def _is_mine(entry: dict) -> bool:
    return entry.get("pid") == os.getpid() and entry.get("instance") == _INSTANCE


def _stale_reason(entry: dict, now: float) -> str:
    """Why *entry* is stale, or "" when it is still owned."""
    pid = entry.get("pid")
    if pid is not None:
        if pid == os.getpid():
            if entry.get("instance") not in (None, _INSTANCE):
                return "owned by this process's pre-restart instance"
        elif not _is_pid_alive(pid):
            return f"pid {pid} dead"
        else:
            recorded = entry.get("pid_start")
            current = _proc_start_time(pid) if recorded else None
            if recorded and current and recorded != current:
                return f"pid {pid} recycled"
    status = entry.get("status")
    if status == "waiting":
        beat = entry.get("heartbeat_at") or entry.get("enqueued_at") or 0
        if now - beat > _WAITING_TTL:
            return "owner stopped retrying"
    elif status == "acquired":
        since = entry.get("acquired_at") or entry.get("enqueued_at") or 0
        if now - since > _ACQUIRED_TTL:
            return "acquired reservation expired"
    return ""


def _clean_stale(entries: list[dict], now: float | None = None) -> list[dict]:
    """Remove entries whose owner is gone or that have expired."""
    now = time.time() if now is None else now
    alive = []
    for entry in entries:
        why = _stale_reason(entry, now)
        if why:
            _log.info("Removing stale queue entry %s (%s)",
                      entry.get("id", "?"), why)
            continue
        alive.append(entry)
    return alive


# ---------------------------------------------------------------------------
# Policy sorting
# ---------------------------------------------------------------------------

def _priority(entry: dict) -> int:
    return _TYPE_PRIORITY.get(entry.get("container_type", ""), _QA_PRIORITY)


def _sort_queue(entries: list[dict], policy: str,
                last_served_qa_run: str | None) -> list[dict]:
    """Sort queue entries according to the active policy."""
    if policy == "fifo":
        return sorted(entries, key=lambda e: e.get("enqueued_at", 0))

    # Priority modes: split into non-QA and QA
    non_qa = [e for e in entries if _priority(e) < _QA_PRIORITY]
    qa = [e for e in entries if _priority(e) >= _QA_PRIORITY]

    non_qa.sort(key=lambda e: (_priority(e), e.get("enqueued_at", 0)))

    if policy == "priority-drain":
        qa = _sort_qa_drain(qa)
    elif policy == "priority-round-robin":
        qa = _sort_qa_round_robin(qa, last_served_qa_run)

    return non_qa + qa


def _group_by_run(entries: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for e in entries:
        groups.setdefault(e.get("qa_run_id") or "__none__", []).append(e)
    for group in groups.values():
        group.sort(key=lambda e: e.get("enqueued_at", 0))
    return groups


def _sort_qa_drain(entries: list[dict]) -> list[dict]:
    """Group QA entries by run, order groups by earliest entry, concatenate."""
    groups = _group_by_run(entries)
    ordered = sorted(groups.values(), key=lambda g: g[0].get("enqueued_at", 0))
    return [e for group in ordered for e in group]


def _sort_qa_round_robin(entries: list[dict],
                         last_served: str | None) -> list[dict]:
    """Interleave QA entries across runs, starting after last_served."""
    groups = _group_by_run(entries)
    group_keys = sorted(groups, key=lambda k: groups[k][0].get("enqueued_at", 0))

    # Rotate so we start after last_served
    if last_served and last_served in group_keys:
        idx = group_keys.index(last_served)
        group_keys = group_keys[idx + 1:] + group_keys[:idx + 1]

    result = []
    while any(groups[k] for k in group_keys):
        for k in group_keys:
            if groups[k]:
                result.append(groups[k].pop(0))
    return result


# ---------------------------------------------------------------------------
# Admission walk
# ---------------------------------------------------------------------------

@dataclass
class AcquireResult:
    """Outcome of an admission attempt."""
    granted: list[str] = field(default_factory=list)
    # Why (the first of) the requested entries was not granted; "" if all
    # were granted.
    reason: str = ""


def _reserved_mb(entry: dict, snapshot, projections: dict[str, int]) -> int:
    """Memory an acquired entry still reserves on top of runtime stats."""
    cname = entry.get("container_name")
    if cname and cname in snapshot.running_names:
        # The container is up: its usage and remaining growth to its
        # projection are already in the snapshot.
        return 0
    return projections[entry.get("container_type") or "other"]


def _admit_locked(queue: dict, my_ids: set[str]) -> AcquireResult:
    """Walk the queue and grant fitting entries in *my_ids*.  Lock held."""
    from pm_core import memory_governor as mg

    result = AcquireResult()
    waiting_mine = [e for e in queue["entries"]
                    if e["id"] in my_ids and e.get("status") == "waiting"]
    if not waiting_mine:
        return result

    try:
        target = mg.get_memory_target()
    except mg.GovernorConfigError as e:
        result.reason = str(e)
        return result
    if target is None:
        # Governor inactive — admit everything requested.
        for e in waiting_mine:
            e["status"] = "acquired"
            e["acquired_at"] = time.time()
            result.granted.append(e["id"])
        return result

    stats = mg.load_stats()
    snapshot = mg.take_snapshot(stats=stats)
    if snapshot.error:
        result.reason = f"memory measurement unavailable: {snapshot.error}"
        return result

    projections: dict[str, int] = {}
    for e in queue["entries"]:
        ctype = e.get("container_type") or "other"
        if ctype not in projections:
            projections[ctype] = mg.project_memory(ctype, stats=stats)

    inflight = sum(_reserved_mb(e, snapshot, projections)
                   for e in queue["entries"] if e.get("status") == "acquired")

    sorted_waiting = _sort_queue(
        [e for e in queue["entries"] if e.get("status") == "waiting"],
        get_queue_policy(), queue.get("last_served_qa_run"),
    )
    for entry in sorted_waiting:
        projected = projections[entry.get("container_type") or "other"]
        ok, why = mg.admit(snapshot, projected, inflight)
        if entry["id"] in my_ids:
            if ok:
                inflight += projected
                entry["status"] = "acquired"
                entry["acquired_at"] = time.time()
                result.granted.append(entry["id"])
                if entry.get("qa_run_id"):
                    queue["last_served_qa_run"] = entry["qa_run_id"]
            elif not result.reason:
                result.reason = why
        elif ok:
            # Someone else's entry that fits ahead of ours reserves its
            # share.  One that doesn't fit doesn't block smaller entries
            # behind it (E17).
            inflight += projected
    return result


def _refresh_heartbeats(queue: dict, ids: set[str], now: float) -> None:
    for e in queue["entries"]:
        if e["id"] in ids and _is_mine(e):
            e["heartbeat_at"] = now


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _upsert_locked(queue: dict, container_type: str, qa_run_id: str | None,
                   key: str | None, container_name: str | None,
                   now: float) -> str:
    """Add an entry, or adopt an existing entry with the same *key*.

    Adoption keeps the entry's place in line (``enqueued_at``) so a QA run
    resumed after a restart does not lose its fairness position.  An
    adopted grant is returned to waiting: asking again means the earlier
    launch is over (a dequeue that hit a busy lock) or its owner is gone,
    and the caller must be admitted afresh rather than told "not granted".
    """
    if key:
        for e in queue["entries"]:
            if e.get("key") == key:
                if e.get("status") == "acquired":
                    e["status"] = "waiting"
                    e.pop("acquired_at", None)
                e.update(_owner_fields())
                e["heartbeat_at"] = now
                e["container_type"] = container_type
                e["qa_run_id"] = qa_run_id
                e["container_name"] = container_name
                return e["id"]
    entry = {
        "id": uuid.uuid4().hex[:12],
        "container_type": container_type,
        "key": key,
        "container_name": container_name,
        "qa_run_id": qa_run_id,
        "enqueued_at": now,
        "heartbeat_at": now,
        "status": "waiting",
        **_owner_fields(),
    }
    queue["entries"].append(entry)
    return entry["id"]


def enqueue(container_type: str, qa_run_id: str | None = None,
            count: int = 1, *, keys: list[str] | None = None,
            container_names: list[str | None] | None = None) -> list[str]:
    """Add entries to the launch queue.  Returns entry IDs.

    *keys* (one per entry) make enqueue idempotent: an existing entry with
    the same key is adopted instead of duplicated.  *container_names* lets
    admission stop reserving an entry's memory once its container runs.

    Raises :class:`GovernorLockTimeout` if the lock is busy.
    """
    if keys is not None:
        count = len(keys)
    keys = keys or [None] * count
    names = container_names or [None] * count
    now = time.time()
    with governor_lock():
        queue = _load_queue()
        # Adopt before cleaning: a resumed QA run takes over its previous
        # owner's (possibly stale) entries and their place in line.
        ids = [_upsert_locked(queue, container_type, qa_run_id, k, n, now)
               for k, n in zip(keys, names)]
        queue["entries"] = _clean_stale(queue["entries"], now)
        _save_queue(queue)
    return ids


def try_acquire_detailed(entry_ids: list[str],
                         keepalive: list[str] | None = None) -> AcquireResult:
    """Try to admit *entry_ids*; also refresh *keepalive* entries' heartbeat.

    Under the lock: drop stale entries, then walk the queue in policy
    order granting requested entries that fit the memory budget (after
    the current measured usage, the remaining growth of running
    containers, and in-flight reservations).  A lock timeout or a failed
    measurement grants nothing and says why.
    """
    my_ids = set(entry_ids)
    now = time.time()
    try:
        with governor_lock():
            queue = _load_queue()
            queue["entries"] = _clean_stale(queue["entries"], now)
            _refresh_heartbeats(queue, my_ids | set(keepalive or ()), now)
            present = {e["id"] for e in queue["entries"]}
            result = _admit_locked(queue, my_ids)
            _save_queue(queue)
    except GovernorLockTimeout as e:
        return AcquireResult(reason=str(e))
    if not result.granted and not result.reason and not (my_ids & present):
        result.reason = "launch queue entry no longer present"
    if result.reason:
        _log.info("Launch queue: not admitted (%s)", result.reason)
    return result


def try_acquire(entry_ids: list[str],
                keepalive: list[str] | None = None) -> list[str]:
    """Like :func:`try_acquire_detailed` but return only the granted IDs."""
    return try_acquire_detailed(entry_ids, keepalive=keepalive).granted


def enqueue_and_try_acquire(container_type: str,
                            qa_run_id: str | None = None, *,
                            key: str | None = None,
                            container_name: str | None = None,
                            ) -> tuple[str | None, bool, str]:
    """Enqueue one entry and try to admit it, in one lock round-trip.

    Used for impl/review/signoff launches, which refuse instead of waiting.
    Returns ``(entry_id, acquired, reason)``; ``entry_id`` is None when the
    lock could not be taken.
    """
    now = time.time()
    try:
        with governor_lock():
            queue = _load_queue()
            entry_id = _upsert_locked(queue, container_type, qa_run_id,
                                      key, container_name, now)
            queue["entries"] = _clean_stale(queue["entries"], now)
            result = _admit_locked(queue, {entry_id})
            _save_queue(queue)
    except GovernorLockTimeout as e:
        return None, False, str(e)
    return entry_id, bool(result.granted), result.reason


def dequeue(entry_ids: list[str] | str) -> bool:
    """Remove entries from the queue (post-launch cleanup, cancellation).

    Accepts a single ID or a list of IDs.  Returns False if the lock was
    busy; the entries then expire on their own (waiting entries stop being
    kept alive, acquired ones stop reserving once their container runs).
    """
    if isinstance(entry_ids, str):
        entry_ids = [entry_ids]
    ids_to_remove = set(i for i in entry_ids if i)
    if not ids_to_remove:
        return True
    try:
        with governor_lock():
            queue = _load_queue()
            queue["entries"] = [
                e for e in queue["entries"] if e["id"] not in ids_to_remove
            ]
            _save_queue(queue)
    except GovernorLockTimeout as e:
        _log.warning("Could not dequeue %s: %s", sorted(ids_to_remove), e)
        return False
    return True


def dequeue_run(qa_run_id: str) -> bool:
    """Remove every entry of QA run *qa_run_id* (loop exit, stop, crash)."""
    try:
        with governor_lock():
            queue = _load_queue()
            kept = [e for e in queue["entries"]
                    if e.get("qa_run_id") != qa_run_id]
            if len(kept) != len(queue["entries"]):
                queue["entries"] = kept
                _save_queue(queue)
    except GovernorLockTimeout as e:
        _log.warning("Could not release queue entries of %s: %s", qa_run_id, e)
        return False
    return True


def keepalive(entry_ids: list[str]) -> bool:
    """Renew *entry_ids* so they keep their place while their owner waits.

    Returns False if the lock was busy (the next renewal will catch up).
    """
    ids = set(entry_ids)
    if not ids:
        return True
    now = time.time()
    try:
        with governor_lock():
            queue = _load_queue()
            queue["entries"] = _clean_stale(queue["entries"], now)
            _refresh_heartbeats(queue, ids, now)
            _save_queue(queue)
    except GovernorLockTimeout as e:
        _log.debug("Launch queue keepalive skipped: %s", e)
        return False
    return True


@contextmanager
def keepalive_during(entry_ids: set[str],
                     interval: float = _KEEPALIVE_INTERVAL):
    """Renew *entry_ids* from a daemon thread while the body runs.

    For owners that block longer than ``_WAITING_TTL`` and so cannot
    renew their waiting entries themselves — a QA launch waits for its
    refiners, which can take minutes.  *entry_ids* is read on every
    renewal, so the caller may keep it current.
    """
    if not entry_ids:
        yield
        return
    stop = threading.Event()

    def _beat() -> None:
        while not stop.wait(interval):
            keepalive(list(entry_ids))

    t = threading.Thread(target=_beat, daemon=True, name="pm-queue-keepalive")
    t.start()
    try:
        yield
    finally:
        stop.set()


def get_queue_status() -> dict:
    """Read-only snapshot of the queue for status display (no lock)."""
    return _load_queue()
