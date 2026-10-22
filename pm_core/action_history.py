"""Durable, append-only per-PR journal of action attempts and timers.

``runtime_state`` mirrors only the *latest* state of each action and
forgets attempts (entries are overwritten, removed when a pane vanishes,
swept on TUI restart and deleted after merge).  This module records what
happened over time so ``pm pr history`` and the PR actions pane can show
past attempts, how long they took, and which timers PM is waiting on.

Storage: ``~/.pm/history/{pr_id}.jsonl`` — one JSON event per line,
appended with ``O_APPEND`` under an exclusive flock so concurrent writers
(TUI main thread, loop threads, ``qa-run-bg``, CLI) never interleave.
The file is never removed by PR cleanup, so history survives merge.

Event kinds (all carry ``v``, ``ts``, ``t``, ``pr_id``, ``kind``,
``owner``):

* ``attempt_start`` — ``attempt``, ``action``, optional ``parent``,
  ``loop_id``, ``iteration``, ``scenario``, ``retry``, ``label``,
  ``session_id``/``transcript``, ``resumed``/``adopted``.
* ``phase`` — ``attempt``, ``phase`` (see :data:`WAIT_PHASES` /
  :data:`EXEC_PHASES`), ``detail``.
* ``attempt_end`` — ``attempt``, ``outcome``, ``verdict``, ``detail``.
* ``timer_arm`` — ``timer``, ``purpose``, ``owner_action``,
  ``owner_attempt``, ``armed_t``, ``due_t`` (``None`` = indefinite hold),
  ``effect`` (``gate``: nothing happens at the due time, the timer only
  gates acceptance / relaunch; ``fires``: the owner acts at the due time),
  ``expected``.
* ``timer_clear`` — ``timer``, ``reason``.
* ``owner_exit`` — ``reason``: the owner stops here (an in-place restart),
  so readers bound its interrupted attempts by this moment.

Every writer is best-effort: failures are logged at debug level and
swallowed so timing instrumentation can never alter execution.  Time is
read only through :func:`now`, which tests replace via :func:`use_clock`.
"""

from __future__ import annotations

import contextlib
import fcntl
import heapq
import json
import os
import secrets
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from pm_core.paths import configure_logger, pm_home

_log = configure_logger("pm.action_history")

SCHEMA_VERSION = 1

# Rotate a journal to ``{pr}.1.jsonl`` (one generation) past this size.
MAX_JOURNAL_BYTES = 4 * 1024 * 1024

# Phases that count as waiting (PM or a human is the bottleneck) versus
# execution (an agent or PM itself is working).
WAIT_PHASES = ("queued", "backoff", "waiting_human")
EXEC_PHASES = ("launching", "planning", "agent", "verdict", "verifying")

OUTCOMES = ("done", "failed", "cancelled", "superseded", "interrupted",
            "vanished", "untracked")

_clock: Callable[[], float] = time.time


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def now() -> float:
    """Current wall-clock time (epoch seconds) from the module clock."""
    return _clock()


def set_clock(fn: Callable[[], float] | None) -> None:
    """Replace the module clock (``None`` restores ``time.time``)."""
    global _clock
    _clock = fn or time.time


@contextlib.contextmanager
def use_clock(fn: Callable[[], float]) -> Iterator[None]:
    """Temporarily replace the module clock (tests)."""
    prev = _clock
    set_clock(fn)
    try:
        yield
    finally:
        set_clock(prev)


def iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(t, timezone.utc).isoformat(
        timespec="seconds")


# ---------------------------------------------------------------------------
# Owner identity / liveness
# ---------------------------------------------------------------------------

_owner_cache: dict | None = None
# Loop threads and the TUI main thread may write their first event at the
# same time; without this each would create (and the later one would close)
# its own instance lock, making the earlier events' owner look dead.
_owner_mutex = threading.Lock()

# Attempts this process started and has not ended (attempt -> pr_id), so an
# in-place restart can journal when it stopped owning them.
_open_attempts: dict[str, str] = {}
_open_lock = threading.Lock()


def _after_fork_in_child() -> None:
    global _owner_mutex, _owner_lock_fd, _open_lock, _gate_lock, _beat_wake
    _owner_mutex = threading.Lock()  # a thread may have held it at fork()
    _open_lock = threading.Lock()
    _gate_lock = threading.Lock()
    _beat_wake = threading.Event()
    _open_attempts.clear()  # the parent's attempts, not the child's
    _gate_dues.clear()  # the parent's gates, not the child's
    # The inherited fd shares the parent's owner lock: holding it would keep
    # the parent looking alive after it exits.  The child takes its own
    # instance on its first write.
    if _owner_lock_fd is not None:
        try:
            os.close(_owner_lock_fd)
        except OSError:
            pass
        _owner_lock_fd = None


def _boot_id() -> str | None:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()[:8]
    except OSError:
        return None


def _proc_start(pid: int) -> str | None:
    """Kernel start time of *pid* (clock ticks since boot), or None."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # comm (field 2) may contain spaces/parens: split after the last ')'.
    try:
        fields = raw[raw.rindex(")") + 2:].split()
        if fields[0] == "Z":
            return None  # exited, not yet reaped: as good as gone
        return fields[19]  # field 22 overall
    except (ValueError, IndexError):
        return None


def _start_token(pid: int) -> str | None:
    start = _proc_start(pid)
    if start is None:
        return None
    return f"{_boot_id() or '?'}:{start}"


# Held (LOCK_SH) for the life of this process image.  Python opens files
# close-on-exec, so an in-place ``exec`` restart (the TUI's Ctrl+R keeps its
# pid and start time) releases it just like an exit or crash does.
_owner_lock_fd: int | None = None

os.register_at_fork(after_in_child=_after_fork_in_child)


def _owners_dir() -> Path:
    d = history_dir() / "owners"
    d.mkdir(parents=True, exist_ok=True)
    return d


# Released owner locks older than this are pruned (their attempts then fall
# back to the pid/start-token liveness check).
_OWNER_LOCK_RETENTION_S = 30 * 86400


@contextlib.contextmanager
def _probe_mutex() -> Iterator[None]:
    """Serialize liveness probes across processes.

    A probe takes an owner's lock exclusively for an instant, so two
    concurrent probes of the same dead owner would see each other's lock
    and report it alive.  Probes release that lock before leaving the
    mutex.  Owners never take this mutex.
    """
    try:
        fd = os.open(_owners_dir() / ".probe", os.O_RDWR | os.O_CREAT, 0o644)
    except OSError:
        yield  # unserialized probe beats none
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _prune_owner_locks() -> None:
    cutoff = time.time() - _OWNER_LOCK_RETENTION_S
    for path in _owners_dir().glob("*.lock"):
        try:
            if path.stat().st_mtime > cutoff:
                continue
            fd = os.open(path, os.O_RDWR)
        except OSError:
            continue
        try:
            with _probe_mutex():
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                path.unlink()
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(fd)


# How often a live owner touches its lock file.  The mtime it leaves
# behind tells readers how long a dead owner was alive (see
# owner_last_alive), e.g. whether a gate elapsed before the owner died.
_HEARTBEAT_S = 1.0

# Due times of the gates this process armed.  The heartbeat also fires just
# after each one, so a gate that ran out while its owner was alive reads
# elapsed after a crash (due <= last heartbeat) even when the owner died
# within _HEARTBEAT_S of the due time.
_gate_dues: list[float] = []
_gate_lock = threading.Lock()
_GATE_BEAT_LAG_S = 0.01
# Set when a gate is armed, so a sleeping heartbeat re-plans its next beat.
_beat_wake = threading.Event()


def _next_beat_wait(beat_t: float) -> float:
    with _gate_lock:
        while _gate_dues and _gate_dues[0] <= beat_t:
            heapq.heappop(_gate_dues)
        if not _gate_dues:
            return _HEARTBEAT_S
        return min(_HEARTBEAT_S,
                   _gate_dues[0] - beat_t + _GATE_BEAT_LAG_S)


def _heartbeat(fd: int) -> None:
    # Event.wait, not time.sleep: tests patch time.sleep (often to advance
    # a fake clock), and a background thread calling it would advance that
    # clock at random moments or spin on a no-op mock.
    while _owner_lock_fd == fd:
        beat_t = time.time()  # the mtime utime leaves is at least this
        try:
            os.utime(fd)
        except OSError:
            return
        _beat_wake.clear()
        _beat_wake.wait(_next_beat_wait(beat_t))


def _beat_after(due: float) -> None:
    if _owner_lock_fd is None:
        return
    with _gate_lock:
        heapq.heappush(_gate_dues, due)
    _beat_wake.set()


def _hold_owner_lock(instance: str) -> None:
    global _owner_lock_fd
    try:
        _prune_owner_locks()
        fd = os.open(_owners_dir() / f"{instance}.lock",
                     os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_SH)
        _owner_lock_fd = fd
        threading.Thread(target=_heartbeat, args=(fd,), daemon=True,
                         name="pm-owner-heartbeat").start()
    except Exception:
        _log.debug("action_history: owner lock failed", exc_info=True)


def owner_token() -> dict:
    """Identity of the current process image, used to judge liveness."""
    global _owner_cache
    pid = os.getpid()
    cache = _owner_cache
    if cache is None or cache.get("pid") != pid:
        with _owner_mutex:
            cache = _owner_cache
            if cache is None or cache.get("pid") != pid:
                instance = f"{pid}-{secrets.token_hex(4)}"
                _hold_owner_lock(instance)
                cache = {"pid": pid, "start": _start_token(pid),
                         "host": socket.gethostname(), "instance": instance}
                _owner_cache = cache
    return dict(cache)


def _instance_alive(instance: str) -> bool | None:
    try:
        fd = os.open(_owners_dir() / f"{instance}.lock", os.O_RDWR)
    except OSError:
        # Absent (pruned / never created), unreadable, or no owners dir
        # to create (read-only history dir): readers must not raise here.
        return None
    try:
        with _probe_mutex():
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
    except BlockingIOError:
        return True
    except OSError:
        return None
    finally:
        os.close(fd)
    return False


def owner_last_alive(owner: dict | None) -> float | None:
    """When the owner's lock heartbeat last fired (epoch seconds), or None.

    Only meaningful once the owner is gone: it then bounds the owner's
    death from below to within about ``_HEARTBEAT_S``.
    """
    if not isinstance(owner, dict) or not owner.get("instance"):
        return None
    try:
        return (_owners_dir() / f"{owner['instance']}.lock").stat().st_mtime
    except (OSError, TypeError):
        return None


def owner_alive(owner: dict | None) -> bool | None:
    """Whether the process image that wrote an event is still running.

    ``None`` when liveness cannot be judged (other host, no owner).  The
    owner's lock file decides when present (exits, crashes and in-place
    exec restarts all release it); otherwise a recycled pid is detected by
    comparing the recorded start token.
    """
    if not isinstance(owner, dict) or not owner.get("pid"):
        return None
    if owner.get("host") and owner.get("host") != socket.gethostname():
        return None
    if owner.get("instance"):
        alive = _instance_alive(owner["instance"])
        if alive is not None:
            return alive
    pid = int(owner["pid"])
    token = owner.get("start")
    if token is not None:
        cur = _start_token(pid)
        if cur is None:
            # /proc unreadable for that pid → gone (or no /proc at all).
            if not Path("/proc/self/stat").exists():
                return _kill0(pid)
            return False
        return cur == token
    return _kill0(pid)


def _kill0(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def history_dir() -> Path:
    d = pm_home() / "history"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Unwritable or not a directory: readers then find no journal and
        # writers fail inside their own guards, instead of every caller
        # (``pm pr history``, the popup badge) raising here.
        pass
    return d


def journal_path(pr_id: str) -> Path:
    safe = pr_id.replace("/", "_").replace("\\", "_")
    return history_dir() / f"{safe}.jsonl"


def _rotated_path(path: Path) -> Path:
    return path.with_name(path.stem + ".1.jsonl")


def new_attempt_id() -> str:
    return secrets.token_hex(6)


def record(pr_id: str, kind: str, **fields: Any) -> None:
    """Append one event to *pr_id*'s journal.  Never raises."""
    if not pr_id:
        return
    try:
        t = now()
        event = {"v": SCHEMA_VERSION, "ts": iso(t), "t": round(t, 3),
                 "pr_id": pr_id, "kind": kind, "owner": owner_token()}
        event.update({k: v for k, v in fields.items() if v is not None})
        line = json.dumps(event, sort_keys=True, default=str) + "\n"
        path = journal_path(pr_id)
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                # A crash mid-write can leave a partial last line with no
                # newline; start on a fresh line so this event isn't glued
                # onto it and lost with it.
                size = os.fstat(fd).st_size
                if size and os.pread(fd, 1, size - 1) != b"\n":
                    line = "\n" + line
                os.write(fd, line.encode())
                st = os.fstat(fd)
                # Only the writer holding the current file may rotate: one
                # that opened it just before another rotated would
                # otherwise replace the fresh generation over the old one.
                if (st.st_size > MAX_JOURNAL_BYTES
                        and os.stat(path).st_ino == st.st_ino):
                    os.replace(path, _rotated_path(path))
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    except Exception:
        _log.debug("action_history: record %s/%s failed", pr_id, kind,
                   exc_info=True)


def read_events(pr_id: str) -> list[dict]:
    """All events for *pr_id*, oldest first.  Skips unreadable lines."""
    path = journal_path(pr_id)
    events: list[dict] = []
    for p in (_rotated_path(path), path):
        try:
            with open(p, "r") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    raw = f.read()
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and ev.get("kind"):
                events.append(ev)
    # Stable: file order breaks ties between equal timestamps.
    events.sort(key=lambda e: float(e.get("t") or 0))
    return events


def has_journal(pr_id: str) -> bool:
    path = journal_path(pr_id)
    return path.exists() or _rotated_path(path).exists()


# ---------------------------------------------------------------------------
# Attempt / timer helpers
# ---------------------------------------------------------------------------

def newest_open_attempt(pr_id: str, action: str) -> str | None:
    """Id of the newest *action* attempt, if it was started but never ended.

    ``None`` when the newest attempt has ended: an older attempt left open
    was abandoned (its owner exited), not the one still in flight.
    """
    newest: str | None = None
    ended: set[str] = set()
    for ev in read_events(pr_id):
        kind = ev.get("kind")
        if kind == "attempt_start" and ev.get("action") == action:
            newest = ev.get("attempt") or newest
        elif kind == "attempt_end":
            ended.add(ev.get("attempt"))
    return newest if newest and newest not in ended else None


def start_attempt(pr_id: str, action: str, *, attempt: str | None = None,
                  **fields: Any) -> str:
    """Record an attempt start; returns its id (even if the write failed)."""
    attempt = attempt or new_attempt_id()
    record(pr_id, "attempt_start", attempt=attempt, action=action, **fields)
    if pr_id:
        with _open_lock:
            _open_attempts[attempt] = pr_id
    return attempt


def phase(pr_id: str, attempt: str | None, name: str,
          detail: str | None = None, **fields: Any) -> None:
    if not attempt:
        return
    record(pr_id, "phase", attempt=attempt, phase=name, detail=detail,
           **fields)


def end_attempt(pr_id: str, attempt: str | None, outcome: str, *,
                verdict: str | None = None, detail: str | None = None,
                **fields: Any) -> None:
    if not attempt:
        return
    record(pr_id, "attempt_end", attempt=attempt, outcome=outcome,
           verdict=verdict or None, detail=detail, **fields)
    with _open_lock:
        _open_attempts.pop(attempt, None)


def mark_owner_exit(reason: str = "restart") -> None:
    """Journal that this process stops now, in every PR it has open attempts.

    Called just before an in-place exec (TUI Ctrl+R), which keeps the pid
    but drops the owner lock.  Without it a reader can only bound an
    interrupted attempt by its own last event, so e.g. a QA scenario that
    ran for a while after its start reads "unknown" instead of ">Ns".
    Never raises.
    """
    with _open_lock:
        prs = sorted(set(_open_attempts.values()))
    for pr_id in prs:
        record(pr_id, "owner_exit", reason=reason)


def arm_timer(pr_id: str, timer: str, *, purpose: str, owner_action: str,
              owner_attempt: str | None = None,
              duration: float | None = None, effect: str = "gate",
              expected: str = "", armed_t: float | None = None) -> None:
    """Record that a timer/hold was armed.

    *duration* ``None`` means an indefinite hold (no countdown).  Re-arming
    the same *timer* id replaces the earlier arm.
    """
    t = now() if armed_t is None else armed_t
    due = None if duration is None else round(t + float(duration), 3)
    record(pr_id, "timer_arm", timer=timer, purpose=purpose,
           owner_action=owner_action, owner_attempt=owner_attempt,
           armed_t=round(t, 3), due_t=due, effect=effect,
           expected=expected or None,
           indefinite=True if duration is None else None)
    if effect == "gate" and due is not None:
        _beat_after(due)


def clear_timer(pr_id: str, timer: str, reason: str = "cancelled") -> None:
    record(pr_id, "timer_clear", timer=timer, reason=reason)


# ---------------------------------------------------------------------------
# QA scenario observer
# ---------------------------------------------------------------------------

class ScenarioObserver:
    """Turn QA scenario bookkeeping into scenario attempts.

    ``qa_loop._poll_tmux_verdicts`` hands it read-only snapshots once per
    poll tick; the observer diffs them against the previous snapshot and
    journals starts, phase changes and ends.  It never mutates loop state.
    """

    def __init__(self, pr_id: str, parent: str | None, loop_id: str = "",
                 settled_before=()):
        self.pr_id = pr_id
        self.parent = parent
        self.loop_id = loop_id
        # scenario index -> {"attempt", "retry", "status"}
        self._open: dict[int, dict] = {}
        self._retries: dict[int, int] = {}
        self._seen: set[int] = set()
        # Scenarios whose window died and are between relaunches.
        self._dead: set[int] = set()
        # Scenarios that have had at least one journaled attempt.  A resumed
        # run's scenarios that settled before the restart had theirs in the
        # earlier run attempt.
        self._had_attempt: set[int] = set(settled_before)

    def _start(self, sc, status: str) -> str:
        idx = sc.index
        retry = self._retries.get(idx, 0)
        # A backoff attempt starts before its window exists: the scenario's
        # session is still the dead one, so the relaunch phase carries the
        # new session instead.
        live = status != "backoff"
        attempt = start_attempt(
            self.pr_id, "qa", parent=self.parent, loop_id=self.loop_id,
            scenario=idx, label=getattr(sc, "title", None) or None,
            retry=retry or None,
            session_id=(getattr(sc, "session_id", None) or None)
            if live else None,
            transcript=(getattr(sc, "transcript_path", None) or None)
            if live else None,
        )
        self._open[idx] = {"attempt": attempt, "status": status}
        self._had_attempt.add(idx)
        if status in ("queued", "backoff"):
            return attempt  # the caller records the wait phase
        phase(self.pr_id, attempt, "agent")
        return attempt

    def observe(self, scenarios, *, pending, verifying, queued,
                verdicts: dict) -> None:
        try:
            self._observe(scenarios, pending=set(pending),
                          verifying=set(verifying), queued=set(queued),
                          verdicts=dict(verdicts))
        except Exception:
            _log.debug("ScenarioObserver.observe failed", exc_info=True)

    def _observe(self, scenarios, *, pending, verifying, queued,
                 verdicts) -> None:
        for sc in scenarios:
            idx = sc.index
            if idx in verifying:
                status = "verifying"
            elif idx in pending:
                status = "running"
            elif idx in queued:
                status = "queued"
            elif idx in verdicts:
                status = "done"
            else:
                status = "unknown"
            first = idx not in self._seen
            self._seen.add(idx)
            if idx in self._dead:
                # Between relaunches; once retries are exhausted the loop
                # settles it without a worker, which ends the wait.
                if status == "done":
                    self._dead.discard(idx)
                continue
            cur = self._open.get(idx)
            if cur is None:
                if status in ("running", "verifying", "queued"):
                    attempt = self._start(sc, status)
                    if status == "queued":
                        phase(self.pr_id, attempt, "queued",
                              "waiting for a concurrency slot")
                    if status == "verifying":
                        phase(self.pr_id, attempt, "verifying")
                elif (status == "done" and not first
                      and idx not in self._had_attempt):
                    # Settled without ever being observed running (e.g.
                    # launch failure) — record a zero-length attempt.
                    a = start_attempt(self.pr_id, "qa", parent=self.parent,
                                      loop_id=self.loop_id, scenario=idx,
                                      label=getattr(sc, "title", None) or None)
                    end_attempt(self.pr_id, a, "done",
                                verdict=verdicts.get(idx))
                    self._had_attempt.add(idx)
                continue
            prev = cur["status"]
            if status == prev:
                continue
            attempt = cur["attempt"]
            if status == "verifying":
                phase(self.pr_id, attempt, "verifying",
                      f"{verdicts.get(idx) or 'PASS'} under verification")
            elif status == "running":
                phase(self.pr_id, attempt, "agent",
                      "re-evaluating after verification flag"
                      if prev == "verifying" else "launched")
            elif status == "done":
                end_attempt(self.pr_id, attempt, "done",
                            verdict=verdicts.get(idx))
                self._open.pop(idx, None)
                continue
            cur["status"] = status

    def launching(self, scenario) -> None:
        """A queued scenario got a slot and its worker is being prepared.

        Concretizing and creating the window block the poll loop, so the
        queued wait ends here rather than on the next tick.
        """
        try:
            cur = self._open.get(scenario.index)
            if cur and cur["status"] == "queued":
                phase(self.pr_id, cur["attempt"], "launching",
                      "slot free; preparing worker")
                cur["status"] = "launching"
        except Exception:
            _log.debug("ScenarioObserver.launching failed", exc_info=True)

    def relaunching(self, scenario, retry: int, backoff: float) -> None:
        """A scenario window died; the loop sleeps *backoff* then relaunches.

        The retry attempt starts now in a ``backoff`` phase, so the sleep
        counts as that attempt's wait rather than falling between attempts.
        """
        try:
            idx = scenario.index
            cur = self._open.pop(idx, None)
            if cur:
                end_attempt(self.pr_id, cur["attempt"], "vanished",
                            detail="scenario window died before a verdict")
            self._retries[idx] = retry
            self._dead.add(idx)
            attempt = self._start(scenario, "backoff")
            phase(self.pr_id, attempt, "backoff",
                  f"relaunch in {backoff:.0f}s (retry {retry})")
            arm_timer(self.pr_id, f"qa-backoff:{self.loop_id}:s{idx}",
                      purpose=f"scenario {idx} relaunch backoff "
                              f"(retry {retry})",
                      owner_action="qa", owner_attempt=attempt,
                      duration=backoff, effect="fires",
                      expected=f"relaunch scenario {idx} window")
        except Exception:
            _log.debug("ScenarioObserver.relaunching failed", exc_info=True)

    def relaunched(self, scenario, ok: bool) -> None:
        try:
            idx = scenario.index
            clear_timer(self.pr_id, f"qa-backoff:{self.loop_id}:s{idx}",
                        "fired")
            if idx not in self._open:
                self._start(scenario, "backoff")
            cur = self._open[idx]
            if ok:
                self._dead.discard(idx)
                phase(self.pr_id, cur["attempt"], "agent", "relaunched",
                      session_id=getattr(scenario, "session_id", None)
                      or None)
                cur["status"] = "running"
            else:
                self._open.pop(idx, None)
                end_attempt(self.pr_id, cur["attempt"], "failed",
                            detail="scenario window relaunch failed")
        except Exception:
            _log.debug("ScenarioObserver.relaunched failed", exc_info=True)

    def finish(self, *, stopped: bool) -> None:
        """End any attempt still open when the poll loop exits."""
        for idx, cur in list(self._open.items()):
            end_attempt(self.pr_id, cur["attempt"],
                        "cancelled" if stopped else "interrupted",
                        detail="QA stopped" if stopped
                        else "poll loop ended without a verdict")
            self._open.pop(idx, None)
