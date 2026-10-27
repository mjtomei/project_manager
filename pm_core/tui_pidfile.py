"""Versioned TUI pidfile and process-identity validation.

The TUI advertises itself for external IPC (SIGUSR1 reload, SIGUSR2
command queue) by writing ``~/.pm/tui-<session>.pid``.  Historically that
file held a bare PID, which made every caller unsafe in three ways:

1. **Version skew** — a long-running TUI started before a signal handler
   was added has no handler for the new signal; its default action
   terminates the process.  The pidfile now advertises *capabilities*
   (``caps``), and callers never send a signal the target did not
   advertise.
2. **Stale file** — a crashed/SIGKILL'd TUI leaves the file behind.
3. **PID reuse** — the dead TUI's PID may belong to an unrelated process
   by the time a caller signals it.  ``starttime`` (``/proc/<pid>/stat``
   field 22) pins the descriptor to one exact process; the command line
   is checked as a secondary signal.

Only ``pm_core.paths`` is imported lazily so this module stays free of
CLI/TUI imports and can be used from both.
"""

from __future__ import annotations

import json
import os
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CAP_RELOAD = "sigusr1"
CAP_COMMAND = "sigusr2"

PIDFILE_VERSION = 1

# argv element that identifies the TUI subcommand, plus the entry-point
# names that may run it (console script ``pm``; ``python -m
# pm_core.wrapper`` / ``pm_core`` / ``pm_core.cli``).  Matched as exact
# argv elements, never as substrings of the whole command line.
_TUI_ARG = "_tui"
_ENTRY_NAMES = frozenset({"pm", "pm_core", "pm_core.cli", "pm_core.wrapper"})


def pidfile_path(session: str) -> Path:
    """Path to the pidfile a TUI in *session* writes."""
    from pm_core.paths import pm_home
    return pm_home() / f"tui-{session.split('~')[0]}.pid"


def command_queue_path(session: str) -> Path:
    """Path to the per-session TUI command queue file."""
    from pm_core.paths import pm_home
    return pm_home() / f"tui-{session.split('~')[0]}.cmd-queue"


@dataclass(frozen=True)
class TuiPidfile:
    """A parsed pidfile descriptor."""

    pid: int
    caps: frozenset[str] = frozenset()
    started_at: str | None = None
    # Linux process start time (clock ticks since boot), None off-procfs.
    starttime: int | None = None
    session: str | None = None
    # True for a pre-upgrade bare-number pidfile.
    legacy: bool = False


class TuiPidfileConflict(RuntimeError):
    """A live TUI already owns the session's pidfile."""


# ---------------------------------------------------------------------------
# Parsing


def parse_pidfile(text: str | None) -> TuiPidfile | None:
    """Parse pidfile contents; ``None`` when missing/corrupt.

    A bare number is a legacy (pre-capability) pidfile.  The numeric
    pidfile and the SIGUSR1 handler shipped in the same change, so such a
    TUI is known to support ``sigusr1`` — but nothing else.
    """
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            pid = int(data.get("pid"))
        except (TypeError, ValueError):
            return None
        if pid <= 0:
            return None
        caps_raw = data.get("caps")
        caps = (frozenset(str(c) for c in caps_raw)
                if isinstance(caps_raw, list) else frozenset())
        starttime = data.get("starttime")
        if isinstance(starttime, str) and starttime.isdigit():
            starttime = int(starttime)
        elif not isinstance(starttime, int) or isinstance(starttime, bool):
            starttime = None
        started_at = data.get("started_at")
        if not isinstance(started_at, str):
            started_at = None
        session = data.get("session")
        if not isinstance(session, str):
            session = None
        return TuiPidfile(pid=pid, caps=caps, started_at=started_at,
                          starttime=starttime, session=session)
    try:
        pid = int(stripped)
    except ValueError:
        return None
    if pid <= 0:
        return None
    return TuiPidfile(pid=pid, caps=frozenset({CAP_RELOAD}), legacy=True)


def read_pidfile_text(path: Path) -> str | None:
    """Return the pidfile's raw text, or ``None`` if it can't be read.

    ``UnicodeDecodeError`` counts as unreadable: a truncated or
    half-written pidfile can hold arbitrary bytes, and that must never
    escape as an exception into the TUI startup claim or the picker.
    """
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def read_pidfile(path: Path) -> TuiPidfile | None:
    """Read and parse *path*; ``None`` when missing/corrupt."""
    return parse_pidfile(read_pidfile_text(path))


# ---------------------------------------------------------------------------
# Process identity


def _proc_stat_fields(pid: int) -> list[str] | None:
    """Fields of ``/proc/<pid>/stat`` after the parenthesised comm."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    _, sep, rest = stat.rpartition(")")
    if not sep:
        return None
    return rest.split()


def proc_starttime(pid: int) -> int | None:
    """Process start time (field 22), stable for the process lifetime."""
    fields = _proc_stat_fields(pid)
    if not fields or len(fields) < 20:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def is_zombie(pid: int) -> bool:
    """True when *pid* has exited but not been reaped.

    ``kill(pid, 0)`` succeeds on a zombie, so a dead TUI whose tmux server
    hasn't reaped it would otherwise look alive.
    """
    fields = _proc_stat_fields(pid)
    return bool(fields) and fields[0] == "Z"


def proc_cmdline(pid: int) -> list[str] | None:
    """argv of *pid* as a list, or ``None`` when procfs is unavailable."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return [part.decode("utf-8", "replace")
            for part in raw.rstrip(b"\0").split(b"\0")]


def cmdline_is_tui(parts: list[str]) -> bool:
    """True when *parts* is a pm TUI argv (``pm _tui`` and friends)."""
    if _TUI_ARG not in parts:
        return False
    return any(Path(part).name in _ENTRY_NAMES for part in parts)


def pid_alive(pid: int) -> bool:
    """True when *pid* exists (a zombie counts as existing here)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, owned by someone else
    except OSError:
        return False
    return True


def identity_problem(desc: TuiPidfile) -> str | None:
    """Why *desc* does not name a live TUI, or ``None`` when it does.

    Checks, in order: liveness, zombie state, PID reuse via
    ``starttime``, and the command line.  Off-procfs platforms degrade
    to the liveness check (``starttime`` is absent and cmdline unknown).
    """
    if not pid_alive(desc.pid):
        return "process is not running"
    if is_zombie(desc.pid):
        return "process is a zombie"
    live_starttime = proc_starttime(desc.pid)
    if (desc.starttime is not None and live_starttime is not None
            and desc.starttime != live_starttime):
        return "pid was reused by another process"
    parts = proc_cmdline(desc.pid)
    if parts is not None and not cmdline_is_tui(parts):
        return "pid belongs to a different program"
    return None


def open_pidfd(pid: int) -> int | None:
    """Open a pidfd naming *pid*'s current process.

    The fd refers to that one process for as long as it is held, so a
    later ``signal.pidfd_send_signal`` cannot be delivered to an
    unrelated process that recycled the PID.  Returns ``None`` when the
    kernel/Python lacks pidfd support.  Raises ``ProcessLookupError``
    when the process is gone.
    """
    opener = getattr(os, "pidfd_open", None)
    if opener is None:
        return None
    try:
        return opener(pid)
    except ProcessLookupError:
        raise
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Writing


def descriptor_text(pid: int, caps, session: str, started_at: str,
                    starttime: int | None) -> str:
    return json.dumps({
        "version": PIDFILE_VERSION,
        "pid": pid,
        "session": session,
        "started_at": started_at,
        "starttime": starttime,
        "caps": sorted(caps),
    }, separators=(",", ":"))


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def unlink_if_unchanged(path: Path, expected_text: str | None) -> bool:
    """Remove *path* only if it still holds *expected_text*.

    Callers validate a snapshot of the file and then remove it when it is
    stale; re-reading here avoids deleting a pidfile a new TUI wrote in
    between.  ``None`` means the caller's read found nothing usable
    (missing, or undecodable bytes); the file is then removed only if it
    is *still* unreadable, so a concurrent TUI's fresh descriptor — even
    one caught empty mid-claim — is left alone.
    """
    if read_pidfile_text(path) != expected_text:
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Startup claim


@dataclass
class TuiPidfileClaim:
    """Ownership of a session's pidfile by the current process."""

    path: Path
    session: str
    pid: int
    started_at: str
    starttime: int | None
    caps: frozenset[str] = field(default_factory=frozenset)

    def descriptor_text(self) -> str:
        return descriptor_text(self.pid, self.caps, self.session,
                               self.started_at, self.starttime)

    def publish(self, caps) -> None:
        """Advertise *caps*; called only once the handlers are installed."""
        self.caps = frozenset(caps)
        _atomic_write(self.path, self.descriptor_text())

    def release(self) -> None:
        """Remove the pidfile if it still describes this claim."""
        raw = read_pidfile_text(self.path)
        desc = parse_pidfile(raw)
        if desc is None or desc.pid != self.pid:
            return
        if (self.starttime is not None and desc.starttime is not None
                and desc.starttime != self.starttime):
            return
        unlink_if_unchanged(self.path, raw)


def claim_tui_pidfile(path: Path, session: str) -> TuiPidfileClaim:
    """Take exclusive ownership of *path* for the current process.

    Creation is ``O_CREAT|O_EXCL`` so two TUIs starting at once cannot
    both win.  An existing file is taken over only when it is stale
    (dead PID, zombie, reused PID, non-TUI command line) or names this
    very process (``exec`` restart).  A live sibling TUI raises
    :class:`TuiPidfileConflict`.
    """
    pid = os.getpid()
    claim = TuiPidfileClaim(
        path=path,
        session=session,
        pid=pid,
        started_at=datetime.now(timezone.utc).isoformat(),
        starttime=proc_starttime(pid),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raw = read_pidfile_text(path)
            existing = parse_pidfile(raw)
            if existing is None:
                # Corrupt/empty.  On the first pass assume a stale file
                # from a crashed TUI; after that, a peer is mid-claim.
                if attempt == 0:
                    unlink_if_unchanged(path, raw)
                    continue
                raise TuiPidfileConflict(
                    f"another TUI is starting for session {session!r}; "
                    f"refusing to start a second TUI"
                )
            if existing.pid == pid:
                # Same process (exec restart): refresh our descriptor.
                _atomic_write(path, claim.descriptor_text())
                return claim
            problem = identity_problem(existing)
            if problem is None:
                raise TuiPidfileConflict(
                    f"another TUI (pid {existing.pid}) already owns "
                    f"session {session!r}; refusing to start a second TUI"
                )
            unlink_if_unchanged(path, raw)
            continue
        try:
            os.write(fd, claim.descriptor_text().encode())
        finally:
            os.close(fd)
        return claim
    raise TuiPidfileConflict(
        f"could not claim TUI pidfile {path} for session {session!r}"
    )


# ---------------------------------------------------------------------------
# Early signal protection


def _noop_handler(*_args) -> None:
    return None


def install_signal_guards() -> None:
    """Install no-op SIGUSR1/SIGUSR2 handlers.

    Called at the very start of ``pm _tui`` so a signal that lands before
    the real asyncio handlers exist cannot take the default-terminate
    action.  ``restart_app`` keeps ``SIG_IGN`` across ``exec`` for the
    same reason.
    """
    for name in ("SIGUSR1", "SIGUSR2"):
        sig = getattr(signal, name, None)
        if sig is None:  # not defined on Windows
            continue
        try:
            signal.signal(sig, _noop_handler)
        except (ValueError, OSError):
            pass
