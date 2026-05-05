"""Detached loop daemons for QA and review-loop coordinators.

QA and review-loop have a Python-side coordinator (background thread
driving multiple panes, polling verdicts, retrying scenarios, etc.)
that historically lived inside the TUI process.  Eliminating the
popup-cmd carve-out means CLI invocations of ``pr qa`` and
``pr review-loop start`` need to host that coordinator without the
TUI.  A short-lived CLI subprocess can't host a daemon thread that
outlives it, so we double-fork into a detached child that runs the
loop and writes runtime_state for external observers.

Lifecycle artefacts live under ``~/.pm/sessions/<tag>/loops/``:

* ``<pr-id>-<action>.pid``  - pid + loop_id + started_at, three lines
* ``<pr-id>-<action>.lock`` - flock used to serialize spawns
* ``<pr-id>-<action>.log``  - daemon stdio (rotated by user, not us)

Signal contract for stop:

* ``SIGTERM`` → request graceful drain (handler sets a stop flag, the
  loop checks it at its next checkpoint, finishes current iteration,
  writes terminal runtime_state, removes pidfile, exits).
* If still alive after 10s, sender escalates to ``SIGKILL``.  The
  next ``sweep_stale_pidfiles()`` clears the runtime_state entry and
  removes the pidfile.

This module provides the spawn / sweep / signal primitives.  Callers
hand it a ``loop_main`` callable that runs the actual coordinator in
the child.
"""

from __future__ import annotations

import errno
import fcntl
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pm_core import runtime_state
from pm_core.paths import configure_logger, sessions_dir

_log = configure_logger("pm.loop_daemon")

GRACEFUL_DRAIN_SECONDS = 10


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _session_tag(session: str) -> str:
    return session.removeprefix("pm-")


def transcript_dir(pm_root: Path, token: str | None = None) -> Path:
    """Return a transcript directory for a daemon-driven loop.

    Mirrors the layout used by ``auto_start.get_transcript_dir`` so the
    TUI can find produced transcripts under ``<pm_root>/transcripts/``.
    """
    import secrets as _secrets
    if token is None:
        token = _secrets.token_hex(3)
    d = pm_root / "transcripts" / f"manual-{token}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def loops_dir(session: str) -> Path:
    d = sessions_dir() / _session_tag(session) / "loops"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pidfile_path(session: str, pr_id: str, action: str) -> Path:
    return loops_dir(session) / f"{pr_id}-{action}.pid"


def lockfile_path(session: str, pr_id: str, action: str) -> Path:
    return loops_dir(session) / f"{pr_id}-{action}.lock"


def logfile_path(session: str, pr_id: str, action: str) -> Path:
    return loops_dir(session) / f"{pr_id}-{action}.log"


# ---------------------------------------------------------------------------
# Pidfile read/write
# ---------------------------------------------------------------------------

def read_pidfile(path: Path) -> tuple[int, str, str] | None:
    """Return (pid, loop_id, started_at) or None on missing/corrupt file."""
    try:
        text = path.read_text()
    except OSError:
        return None
    lines = text.strip().splitlines()
    if not lines:
        return None
    try:
        pid = int(lines[0].strip())
    except ValueError:
        return None
    loop_id = lines[1].strip() if len(lines) > 1 else ""
    started_at = lines[2].strip() if len(lines) > 2 else ""
    return pid, loop_id, started_at


def _write_pidfile(path: Path, pid: int, loop_id: str) -> None:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.write_text(f"{pid}\n{loop_id}\n{started}\n")


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as e:
        return e.errno == errno.EPERM
    return True


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------

def sweep_stale_pidfiles(session: str) -> int:
    """Remove pidfiles whose PID is no longer alive and clear runtime_state.

    Returns the number of stale entries cleared.  Safe to call from
    both the CLI handler (before checking liveness) and the TUI
    (on mount).
    """
    swept = 0
    try:
        d = loops_dir(session)
    except OSError:
        return 0
    for path in d.glob("*.pid"):
        info = read_pidfile(path)
        if info is None:
            try:
                path.unlink()
            except OSError:
                pass
            continue
        pid, _loop_id, _ = info
        if _is_alive(pid):
            continue
        # Dead PID — clear runtime_state and remove file.
        stem = path.stem  # "<pr-id>-<action>"
        # action is the last hyphenated suffix among known actions.
        for action in ("review-loop", "qa"):
            suffix = f"-{action}"
            if stem.endswith(suffix):
                pr_id = stem[: -len(suffix)]
                try:
                    runtime_state.clear_action(pr_id, action)
                except Exception:
                    _log.debug("sweep: clear_action failed", exc_info=True)
                break
        try:
            path.unlink()
        except OSError:
            pass
        swept += 1
    if swept:
        _log.info("sweep: cleared %d stale loop pidfile(s) in %s",
                  swept, session)
    return swept


def is_loop_alive(session: str, pr_id: str, action: str) -> bool:
    """True when a pidfile exists and its PID is live."""
    info = read_pidfile(pidfile_path(session, pr_id, action))
    if info is None:
        return False
    return _is_alive(info[0])


# ---------------------------------------------------------------------------
# Spawn
# ---------------------------------------------------------------------------

class LoopAlreadyRunning(RuntimeError):
    """Raised when spawn() finds an existing live daemon for the target."""


def spawn(
    *,
    session: str,
    pr_id: str,
    action: str,
    loop_id: str,
    loop_main: Callable[[], None],
) -> int:
    """Double-fork a detached daemon that runs *loop_main*.

    Returns the daemon's PID.  Raises :class:`LoopAlreadyRunning` if
    a live daemon is already registered for ``(pr_id, action)``.

    *loop_main* is called inside the child after ``setsid()``,
    pidfile write, and stdio redirection.  It should run the
    coordinator to completion.  Cleanup (pidfile removal, terminal
    runtime_state) is handled by the wrapper around *loop_main*.

    Window setup must happen in the *caller* before ``spawn()`` so
    errors surface to the user; the child only owns the loop itself.
    """
    sweep_stale_pidfiles(session)

    lockf = lockfile_path(session, pr_id, action)
    lockf.touch(exist_ok=True)
    with open(lockf, "r+") as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            if is_loop_alive(session, pr_id, action):
                raise LoopAlreadyRunning(
                    f"{action} daemon already running for {pr_id}"
                )

            log_path = logfile_path(session, pr_id, action)
            pid_path = pidfile_path(session, pr_id, action)

            # Pipe so the intermediate child can hand the daemon PID
            # back to the parent before the daemon finishes (the
            # daemon may complete and clean up its pidfile faster than
            # the parent can read it from disk).
            r_fd, w_fd = os.pipe()

            pid = os.fork()
            if pid > 0:
                # Parent
                os.close(w_fd)
                try:
                    raw = os.read(r_fd, 32).decode().strip()
                finally:
                    os.close(r_fd)
                try:
                    os.waitpid(pid, 0)
                except OSError:
                    pass
                try:
                    return int(raw) if raw else -1
                except ValueError:
                    return -1

            # Intermediate child
            os.close(r_fd)
            try:
                os.setsid()
            except OSError:
                pass
            pid2 = os.fork()
            if pid2 > 0:
                # Send daemon PID to parent and exit so the grandchild
                # reparents to init.
                try:
                    os.write(w_fd, f"{pid2}\n".encode())
                finally:
                    os.close(w_fd)
                os._exit(0)

            # Grandchild — the daemon.
            os.close(w_fd)
            # Drop the inherited lock fd so we don't carry an open
            # descriptor for the lockfile through the daemon's
            # lifetime.  The parent's `with` block still releases the
            # OFD-level flock when it exits, so this is purely an fd
            # hygiene fix.
            try:
                os.close(lock_fd.fileno())
            except OSError:
                pass
            _run_daemon(
                pid_path=pid_path,
                log_path=log_path,
                pr_id=pr_id,
                action=action,
                loop_id=loop_id,
                loop_main=loop_main,
            )
            os._exit(0)
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


def _run_daemon(
    *,
    pid_path: Path,
    log_path: Path,
    pr_id: str,
    action: str,
    loop_id: str,
    loop_main: Callable[[], None],
) -> None:
    """In the daemon child: redirect stdio, write pidfile, run, cleanup."""
    # Redirect stdio to log file.
    try:
        log_fd = os.open(str(log_path),
                          os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        os.dup2(log_fd, 0)
        os.dup2(log_fd, 1)
        os.dup2(log_fd, 2)
        if log_fd > 2:
            os.close(log_fd)
    except OSError:
        pass

    _write_pidfile(pid_path, os.getpid(), loop_id)

    # Stop flag set by SIGTERM/SIGINT.  The coordinator polls it via
    # :func:`stop_requested` at its checkpoints.
    _STOP_FLAG["set"] = False

    def _on_stop(signum, _frame):
        _STOP_FLAG["set"] = True
        _log.info("daemon[%s/%s]: received signal %d, draining",
                  pr_id, action, signum)

    signal.signal(signal.SIGTERM, _on_stop)
    signal.signal(signal.SIGINT, _on_stop)

    final_state = "failed"
    final_extras: dict = {}
    try:
        loop_main()
        final_state = "done"
    except SystemExit as e:
        if e.code in (0, None):
            final_state = "done"
        else:
            _log.warning("daemon[%s/%s]: SystemExit(%s)",
                         pr_id, action, e.code)
    except BaseException as e:
        _log.exception("daemon[%s/%s]: crashed: %s", pr_id, action, e)
        final_extras["error"] = str(e)[:200]
    finally:
        try:
            cur = runtime_state.get_action_state(pr_id, action) or {}
            keep = {k: cur.get(k) for k in ("verdict", "iteration", "loop_id")
                    if cur.get(k) is not None}
            keep.update(final_extras)
            runtime_state.set_action_state(pr_id, action, final_state, **keep)
        except Exception:
            _log.debug("daemon: terminal runtime_state write failed",
                       exc_info=True)
        try:
            pid_path.unlink()
        except OSError:
            pass


# Module-level dict so signal handlers can mutate without nonlocal gymnastics.
_STOP_FLAG: dict[str, bool] = {"set": False}


def stop_requested() -> bool:
    """Daemon's loop_main calls this at checkpoints to honor SIGTERM."""
    return bool(_STOP_FLAG.get("set"))


def bridge_stop_to_state(state, poll_interval: float = 0.5) -> None:
    """Spawn a daemon thread that sets ``state.stop_requested`` on SIGTERM.

    ``run_qa_sync`` / ``run_review_loop_sync`` check ``state.stop_requested``
    at iteration boundaries; the daemon's signal handler only flips
    :data:`_STOP_FLAG`.  Without a bridge, ``request_stop()`` always
    escalates to SIGKILL after the graceful-drain window because the
    coordinator never sees the request.  Call this once after
    constructing the loop's *state* object and before starting the
    coordinator.
    """
    import threading

    def _watch():
        while True:
            if stop_requested():
                try:
                    state.stop_requested = True
                except Exception:  # pragma: no cover - defensive
                    pass
                return
            time.sleep(poll_interval)

    threading.Thread(target=_watch, daemon=True).start()


# ---------------------------------------------------------------------------
# Stop signal (start-only in v1, but the helper is here for completeness)
# ---------------------------------------------------------------------------

def request_stop(session: str, pr_id: str, action: str,
                 graceful_seconds: float = GRACEFUL_DRAIN_SECONDS) -> bool:
    """Send SIGTERM, wait, escalate to SIGKILL if still alive.

    Returns True if the process is gone after the call.  Used by the
    eventual ``stop`` subcommand and by callers that need to clear a
    runaway daemon.  Safe no-op if no daemon is running.
    """
    info = read_pidfile(pidfile_path(session, pr_id, action))
    if info is None:
        return True
    pid = info[0]
    if not _is_alive(pid):
        sweep_stale_pidfiles(session)
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    deadline = time.time() + graceful_seconds
    while time.time() < deadline:
        if not _is_alive(pid):
            sweep_stale_pidfiles(session)
            return True
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    time.sleep(0.5)
    sweep_stale_pidfiles(session)
    return not _is_alive(pid)
