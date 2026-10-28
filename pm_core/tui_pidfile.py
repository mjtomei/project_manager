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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CAP_RELOAD = "sigusr1"
CAP_COMMAND = "sigusr2"

PIDFILE_VERSION = 1

# ``os.kill`` takes a C ``int``, so a corrupt pidfile holding a larger
# number raises ``OverflowError`` at signal time — out of the startup
# claim, the picker, and autostart — instead of being read as stale.
# No real PID comes close to this bound (``pid_t`` is a signed 32-bit int
# on every platform pm runs on).
_MAX_PID = 2 ** 31 - 1

# An empty pidfile is ambiguous — a peer may have created it with
# ``O_EXCL`` and not yet written its descriptor — so the claim waits this
# many short intervals for a peer to publish before treating it as stale.
_CLAIM_EMPTY_RETRIES = 2
_CLAIM_RETRY_S = 0.05
# Every unlink/takeover round costs one attempt.  The budget leaves room
# for those rounds *on top of* the empty-file waits, so an empty file is
# never unlinked early just because earlier rounds used up the attempts
# (the wait is keyed on the file being empty, not on the attempt number).
_CLAIM_MAX_ATTEMPTS = _CLAIM_EMPTY_RETRIES + 4

# argv element that identifies the TUI subcommand, plus the entry points
# that may run it: the console script ``pm``, or any ``pm_core`` module
# (``python -m pm_core`` / ``pm_core.cli`` / ``pm_core.wrapper``, and
# renames such as the planned ``pm_core.bootstrap``).  Matching any
# ``pm_core.*`` module keeps a future entry-point rename from turning a
# live TUI into "a different program", which would make callers delete
# its pidfile and silently disable IPC.  Matched as exact argv elements,
# never as substrings of the whole command line.
_TUI_ARG = "_tui"
_ENTRY_BASENAME = "pm"
_ENTRY_MODULE = "pm_core"


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


class TuiPidfileUnavailable(OSError):
    """The pidfile could not be taken over; run without external IPC.

    Raised when the claim gives up on a file that never named a live TUI
    (a stale one it could not unlink, or one a peer keeps recreating).
    That is *not* a conflict: refusing to start would take the whole TUI
    down for a pidfile problem (E13), so this is an ``OSError`` — the
    launcher and ``_install_reload_signal`` log it and continue without
    external IPC.
    """


# ---------------------------------------------------------------------------
# Parsing


def _parse_uint(value) -> int | None:
    """A non-negative integer from a pidfile field, or ``None``.

    Accepts an ``int`` or a decimal string; everything else (``bool``,
    ``float``, ``None``, a non-numeric string) is rejected rather than
    coerced.  ``str.isdecimal`` — not ``str.isdigit`` — is the gate: it
    is true for ``"²"``, which ``int()`` then refuses, and a corrupt
    pidfile must never raise out of the parser.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text.isdecimal():
            return None
        try:
            value = int(text)
        except ValueError:  # non-decimal digits int() still refuses
            return None
    if not isinstance(value, int) or value < 0:
        return None
    return value


def _parse_pid(value) -> int | None:
    """A usable PID from *value*, or ``None`` when it is not one."""
    pid = _parse_uint(value)
    if pid is None or not 1 <= pid <= _MAX_PID:
        return None
    return pid


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
        pid = _parse_pid(data.get("pid"))
        if pid is None:
            return None
        caps_raw = data.get("caps")
        caps = (frozenset(str(c) for c in caps_raw)
                if isinstance(caps_raw, list) else frozenset())
        starttime = _parse_uint(data.get("starttime"))
        started_at = data.get("started_at")
        if not isinstance(started_at, str):
            started_at = None
        session = data.get("session")
        if not isinstance(session, str):
            session = None
        return TuiPidfile(pid=pid, caps=caps, started_at=started_at,
                          starttime=starttime, session=session)
    pid = _parse_pid(stripped)
    if pid is None:
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
        # ``comm`` — the parenthesised process name — is 16 bytes chosen
        # by the process itself and may hold non-UTF-8 bytes; a recycled
        # PID is exactly the case where the file names an arbitrary
        # unrelated process.  A strict decode would raise
        # ``UnicodeDecodeError`` out of ``proc_starttime``/``is_zombie``
        # and therefore out of the startup claim, the picker and
        # autostart, so decode with replacement: only the state char and
        # the numeric fields after the final ``)`` are used, and those
        # are always ASCII.
        stat = Path(f"/proc/{pid}/stat").read_text(errors="replace")
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
    """argv of *pid* as a list, or ``None`` when it cannot be read.

    An *empty* argv is reported as ``[]``, not ``None``: a process can
    legitimately have no command line — a kernel thread (``mm == NULL``)
    or a zombie — and that is positive evidence that it is *not* a pm
    TUI.  ``None`` is reserved for "we cannot tell" (no procfs, or the
    read failed), which degrades the identity check to liveness.
    Conflating the two made a stale pidfile whose recycled PID belonged
    to such a process look like a live TUI: the startup claim refused to
    start (the exact failure this module exists to avoid) and callers
    would have signaled it.
    """
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return []
    return [part.decode("utf-8", "replace")
            for part in raw.rstrip(b"\0").split(b"\0")]


def _is_pm_entry_point(part: str) -> bool:
    """True when the argv element names the ``pm`` script or a pm_core module."""
    if Path(part).name == _ENTRY_BASENAME:
        return True
    return part == _ENTRY_MODULE or part.startswith(f"{_ENTRY_MODULE}.")


def cmdline_is_tui(parts: list[str]) -> bool:
    """True when *parts* is a pm TUI argv (``pm _tui`` and friends)."""
    if _TUI_ARG not in parts:
        return False
    return any(_is_pm_entry_point(part) for part in parts)


def pid_alive(pid: int) -> bool:
    """True when *pid* exists (a zombie counts as existing here).

    Total for any input: an out-of-range value (``os.kill`` raises
    ``OverflowError``, not ``OSError``) is reported as not alive rather
    than escaping into a caller.  ``parse_pidfile`` already bounds the
    pid, so this is defence in depth for direct callers.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, owned by someone else
    except (OSError, OverflowError, ValueError):
        return False
    return True


def identity_problem(desc: TuiPidfile) -> str | None:
    """Why *desc* does not name a live TUI, or ``None`` when it does.

    Checks, in order: liveness, zombie state, PID reuse via
    ``starttime``, and the command line.  Off-procfs platforms degrade
    to the liveness check (``starttime`` is absent and cmdline unknown).
    An empty argv (``[]``) is a *known* non-TUI, not "unknown" — see
    :func:`proc_cmdline`.
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


def _write_all(fd: int, data: bytes) -> None:
    """Write all of *data* to *fd*, tolerating short writes.

    A regular-file write is normally all-or-nothing, but the kernel is
    allowed to write fewer bytes than asked; treating that as success
    would leave a truncated descriptor that every caller reads as
    "unreadable pidfile" and unlinks.
    """
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write to TUI pidfile")
        view = view[written:]


def unlink_if_unchanged(path: Path, expected_text: str | None) -> bool:
    """Remove *path* only if it still holds *expected_text*.

    Callers validate a snapshot of the file and then remove it when it is
    stale; re-reading here avoids deleting a pidfile a new TUI wrote in
    between.  ``None`` means the caller's read found nothing usable
    (missing, or undecodable bytes); the file is then removed only if it
    is *still* unreadable, so a concurrent TUI's fresh descriptor is left
    alone.  (A file caught empty mid-claim is handled by
    :func:`claim_tui_pidfile`, which waits for the peer to publish rather
    than removing it.)
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

    def owned_by_other(self) -> bool:
        """True when the pidfile now names a different process.

        A successor TUI can only take the file over once this process
        looks stale, but if it did, the shared command queue belongs to
        it: shutting down must not delete a file the successor is using.
        An *empty* file counts as a successor too: it can only be there
        because someone else created it with ``O_EXCL`` between our
        release and this check (see ``claim_tui_pidfile``), and the queue
        it is about to use is the shared one.
        """
        raw = read_pidfile_text(self.path)
        if raw == "":
            return True
        desc = parse_pidfile(raw)
        return desc is not None and desc.pid != self.pid


def claim_tui_pidfile(path: Path, session: str) -> TuiPidfileClaim:
    """Take exclusive ownership of *path* for the current process.

    Creation is ``O_CREAT|O_EXCL`` so two TUIs starting at once cannot
    both win.  An existing file is taken over only when it is stale
    (dead PID, zombie, reused PID, non-TUI command line) or names this
    very process (``exec`` restart).  An *empty* file is first given a
    moment to be filled in by a peer that is between its ``O_EXCL``
    create and its first write; only then is it treated as stale.  A live
    sibling TUI raises :class:`TuiPidfileConflict`; a file that never
    named a live TUI but could not be removed raises
    :class:`TuiPidfileUnavailable` (an ``OSError``), so the caller runs
    without external IPC instead of refusing to start.
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
    # Worst case: wait out a mid-claim peer, then unlink a stale file,
    # then create ours.  The empty-file waits get their own budget so
    # they cannot be consumed by earlier unlink rounds (see
    # ``_CLAIM_MAX_ATTEMPTS``).
    empty_waits = 0
    for _ in range(_CLAIM_MAX_ATTEMPTS):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            raw = read_pidfile_text(path)
            existing = parse_pidfile(raw)
            if existing is None:
                if raw == "" and empty_waits < _CLAIM_EMPTY_RETRIES:
                    # Empty is ambiguous: a peer may have created the file
                    # with O_EXCL and not written its descriptor yet.
                    # Give it a moment to publish, otherwise two racing
                    # TUIs could each take the file over and both run.
                    empty_waits += 1
                    time.sleep(_CLAIM_RETRY_S)
                    continue
                # Corrupt, undecodable, or an empty file nobody claimed:
                # stale.  Remove it (only if unchanged) and try again.
                unlink_if_unchanged(path, raw)
                continue
            if existing.pid == pid:
                # Same process (exec restart): refresh our descriptor.
                _atomic_write(path, claim.descriptor_text())
                return claim
            problem = identity_problem(existing)
            if problem is None:
                raise TuiPidfileConflict(
                    f"another TUI (pid {existing.pid}) already owns "
                    f"session {session!r} ({path}); refusing to start a "
                    f"second TUI — stop pid {existing.pid} if it is not "
                    f"visible"
                )
            unlink_if_unchanged(path, raw)
            continue
        data = claim.descriptor_text().encode()
        try:
            try:
                _write_all(fd, data)
            except OSError:
                # We created this file a moment ago and could not fill it
                # in.  Leaving it behind would make every caller report
                # "has not finished starting up" for as long as this TUI
                # runs, so remove it — but only while it still holds our
                # (empty or partial) bytes, never a successor's
                # descriptor.
                current = read_pidfile_text(path)
                if current is not None and data.startswith(current.encode()):
                    unlink_if_unchanged(path, current)
                raise
        finally:
            os.close(fd)
        return claim
    # Every exhaustion path is "the file never named a live TUI, but we
    # could not remove it" — a live sibling raises the conflict above on
    # the round that observes it.  Refusing to start would take the whole
    # TUI down for a pidfile problem, so degrade to running without
    # external IPC (E13); callers read the leftover file as stale.
    raise TuiPidfileUnavailable(
        f"could not take over TUI pidfile {path} for session {session!r}; "
        f"continuing without external IPC"
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
