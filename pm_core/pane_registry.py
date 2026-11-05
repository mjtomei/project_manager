"""Pane registry file I/O.

Manages the per-session JSON registry that tracks pm-created tmux panes.
Each session has a registry file in ~/.pm/pane-registry/<session>.json
containing per-window pane IDs, roles, and ordering information.
"""

import contextlib
import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

from pm_core.paths import configure_logger

_logger = configure_logger("pm.pane_registry")


def _ensure_logging():
    """No-op for backward compatibility. Logging is now auto-configured."""
    pass


def base_session_name(session: str) -> str:
    """Strip grouped-session suffix (~N) to get the base session name.

    Delegates to :func:`pm_core.paths.base_session_name`, the one
    definition shared with the socket derivation: only a *numeric* suffix
    is a grouped session, so a name that itself contains ``~`` (a repo
    directory may) is not truncated.
    """
    from pm_core.paths import base_session_name as _base_session_name
    return _base_session_name(session)


def pm_session_name(session: str) -> str:
    """The pm session that tmux session *session* shows (base name).

    Like :func:`base_session_name`, but a user's own view grouped with a
    pm session under another name (``tmux new-session -t pm-x -s myview``)
    resolves through its group: tmux names that view in hooks and popups
    while its client is the most recently active one (S121).  The group is
    looked up by the full name first, so a view named like a pm session
    (``pm-laptop``) or containing ``~`` (``my~view``) also resolves (S124).
    """
    if not session:
        return session
    from pm_core import tmux as tmux_mod
    group = tmux_mod.session_group(session)
    if group.startswith("pm-"):
        return base_session_name(group)
    return base_session_name(session)


def registry_dir() -> Path:
    """Return the directory for pane registry files."""
    from pm_core.paths import pane_registry_dir
    return pane_registry_dir()


def registry_path(session: str) -> Path:
    """Return the registry file path for a session."""
    return registry_dir() / f"{base_session_name(session)}.json"


def locked_read_modify_write(path: Path, modifier_fn, *, timeout: float = 5.0):
    """Read a JSON file, modify it, and write it back under an exclusive file lock.

    Acquires ``fcntl.flock`` on a sidecar ``{path}.lock`` file so that
    concurrent callers serialize their read-modify-write cycles.

    Args:
        path: Path to the JSON data file.
        modifier_fn: Called with the parsed JSON dict (or ``None`` if the file
            is missing / corrupt).  If it returns a ``dict``, the file is
            atomically rewritten; if it returns ``None``, the write is skipped.
        timeout: Seconds to wait for the lock before raising ``TimeoutError``.

    Returns:
        Whatever *modifier_fn* returns.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + timeout
    lock_fd = open(lock_path, "w")
    try:
        # Acquire exclusive lock with retry
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Could not acquire lock on {lock_path} within {timeout}s"
                    )
                time.sleep(0.01)

        # Read
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, ValueError):
                data = None
        else:
            data = None

        # Modify
        result = modifier_fn(data)

        # Write atomically (temp + fsync + rename)
        if result is not None:
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(result, indent=2) + "\n")
            fd = os.open(str(tmp), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            tmp.rename(path)
    finally:
        lock_fd.close()  # closing the fd releases the flock

    return result


@contextlib.contextmanager
def tui_respawn_lock(session: str, *, timeout: float = 10.0):
    """Hold the per-session lock under which a missing TUI is started.

    Two pm processes can find a session's TUI gone at the same moment: the
    ``after-kill-pane`` hook (``pm _pane-closed``) that respawns a killed
    TUI, and a ``pm session`` attach that checks for the TUI before it
    attaches.  Each used to look, see no TUI, and split a new one, so the
    session ran two TUIs until the second one's pidfile refusal (with a
    traceback in the debug log) — and when the attach looked just after
    the hook's split, it adopted the hook's pane and the hook then listed
    it a second time (QA scenario 42).  Both now look for a running TUI
    and start one while holding this lock, so the second of them sees the
    first one's TUI.

    The lock is a sidecar of the registry, ``<registry>.respawn.lock``,
    separate from the read-modify-write lock (``locked_read_modify_write``
    takes that one for every write the holder makes).  Yields whether the
    lock was taken.  It waits only while another holder has it
    (``store.bounded_flock``).  If it is still held after *timeout*
    seconds, or the file cannot be opened or locked at all, the caller goes
    ahead without it — the behaviour before the lock existed — rather than
    leave the session without a TUI.

    Like the registry, the lock lives in the user's own ``~/.pm``.  A user
    who joined someone else's shared session takes their own lock, not
    the owner's, so their ``pm session`` is not serialised with the
    owner's hook.  That race falls back on the TUI pidfile guard against a
    second TUI, as every race did before this lock.
    """
    from pm_core.store import bounded_flock

    path = registry_path(session)
    lock_path = path.with_suffix(path.suffix + ".respawn.lock")
    with contextlib.ExitStack() as stack:
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            locked = stack.enter_context(bounded_flock(lock_path, timeout))
        except OSError as e:
            _logger.warning("tui_respawn_lock: cannot lock %s (%s); going "
                            "ahead without it", lock_path, e)
            locked = False
        else:
            if not locked:
                _logger.warning("tui_respawn_lock: %s still held after "
                                "%.0fs; going ahead without it",
                                lock_path, timeout)
        yield locked


def get_window_data(data: dict, window: str) -> dict:
    """Return the window entry for *window*, creating it if absent."""
    windows = data.setdefault("windows", {})
    if window not in windows:
        windows[window] = {"panes": [], "user_modified": False}
    return windows[window]


def register_tui_pane(data: dict, window: str, pane_id: str) -> bool:
    """Record *pane_id* as the TUI of *window* unless it is listed there.

    Returns whether *data* changed.  The entry sorts first (order 0), the
    shape the TUI's own ``heal_registry`` writes; ``pm session`` adopting a
    TUI the registry does not list yet writes the same one, so whichever
    of the two runs second under the registry lock is a no-op.
    """
    wdata = get_window_data(data, window)
    if any(p["id"] == pane_id for p in wdata["panes"]):
        return False
    wdata["panes"].insert(0, {"id": pane_id, "role": "tui", "order": 0,
                              "cmd": "tui"})
    return True


def _iter_all_panes(data: dict):
    """Yield ``(window_id, pane_dict)`` across every window in the registry."""
    for window_id, wdata in data.get("windows", {}).items():
        for pane in wdata.get("panes", []):
            yield window_id, pane


def _prepare_registry_data(raw: dict | None, session: str) -> dict:
    """Turn raw JSON (or None) into a valid multi-window registry dict.

    Handles old-format migration and missing/corrupt files.
    """
    if raw is not None:
        # Migrate old flat format → multi-window
        if "panes" in raw and "windows" not in raw:
            window = raw.pop("window", "0")
            panes = raw.pop("panes", [])
            user_modified = raw.pop("user_modified", False)
            raw["windows"] = {
                window: {"panes": panes, "user_modified": user_modified},
            }
        return raw
    return {"session": session, "windows": {}, "generation": ""}


def load_registry(session: str) -> dict:
    """Load the pane registry for a session.

    Automatically migrates the old single-window format to the new
    multi-window format on read.
    """
    path = registry_path(session)
    if path.exists():
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, ValueError):
            raw = None
    else:
        raw = None
    return _prepare_registry_data(raw, session)


def _save_registry(session: str, data: dict) -> None:
    """Save the pane registry for a session (internal).

    Uses atomic write (temp file + fsync + rename) so concurrent readers
    never see a truncated or partially-written file.

    This is private — all mutations should go through
    ``locked_read_modify_write`` to prevent race conditions.
    """
    path = registry_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    fd = os.open(str(tmp), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    tmp.rename(path)


def register_pane(session: str, window: str, pane_id: str, role: str, cmd: str) -> None:
    """Register a new pane in the registry."""
    _ensure_logging()

    def modifier(raw):
        data = _prepare_registry_data(raw, session)
        wdata = get_window_data(data, window)
        order = max((p["order"] for p in wdata["panes"]), default=-1) + 1
        wdata["panes"].append({
            "id": pane_id,
            "role": role,
            "order": order,
            "cmd": cmd,
        })
        _logger.info("register_pane: %s role=%s window=%s order=%d (total=%d)",
                     pane_id, role, window, order, len(wdata["panes"]))
        return data

    locked_read_modify_write(registry_path(session), modifier)


def unregister_pane(session: str, pane_id: str) -> None:
    """Remove a pane from the registry (searches all windows)."""
    _ensure_logging()

    def modifier(raw):
        data = _prepare_registry_data(raw, session)
        found = False
        for window_id, wdata in data.get("windows", {}).items():
            before = len(wdata["panes"])
            wdata["panes"] = [p for p in wdata["panes"] if p["id"] != pane_id]
            if len(wdata["panes"]) < before:
                found = True
                _logger.info("unregister_pane: %s removed from window %s", pane_id, window_id)
        if not found:
            _logger.info("unregister_pane: %s not found in any window", pane_id)
        return data

    locked_read_modify_write(registry_path(session), modifier)


def unregister_windows(session: str, window_names: list[str]) -> list[str]:
    """Remove the given window entries from the registry. Returns names removed."""
    _ensure_logging()
    removed: list[str] = []

    def modifier(raw):
        data = _prepare_registry_data(raw, session)
        windows = data.get("windows", {})
        for name in window_names:
            if name in windows:
                del windows[name]
                removed.append(name)
                _logger.info("unregister_windows: removed window %s", name)
        return data

    locked_read_modify_write(registry_path(session), modifier)
    return removed


def prune_dead_windows(session: str) -> list[str]:
    """Remove registry entries for windows that no longer exist in *session*.

    Registration and layout only reconcile the window they touch, so a
    window killed while nothing was registering into it (for example the
    QA window an execution-only run leaves behind, killed before the next
    run) keeps its panes under a stale ``@id`` forever. Returns the removed
    window IDs.
    """
    _ensure_logging()
    from pm_core import tmux as tmux_mod

    # Query tmux OUTSIDE the lock, and never prune a session we cannot see:
    # an empty window list from a dead/absent session must not wipe the
    # registry.  A live session always has at least one window, so an empty
    # list here means the query itself failed (or the session died between
    # the two calls) — not that every registered window is gone.
    if not tmux_mod.session_exists(session):
        return []
    live_windows = {w["id"] for w in tmux_mod.list_windows(session)}
    if not live_windows:
        _logger.info("prune_dead_windows: no live windows for %s, skipping",
                     session)
        return []

    removed: list[str] = []

    def modifier(raw):
        data = _prepare_registry_data(raw, session)
        for window_id in list(data.get("windows", {})):
            if window_id not in live_windows:
                removed.append(window_id)
                del data["windows"][window_id]
        if not removed:
            return None  # no changes, skip write
        _logger.info("prune_dead_windows: removed %s from %s",
                     removed, session)
        return data

    locked_read_modify_write(registry_path(session), modifier)
    return removed


def kill_and_unregister(session: str, pane_id: str) -> None:
    """Kill a tmux pane and remove it from the registry."""
    from pm_core import tmux as tmux_mod
    subprocess.run(tmux_mod._tmux_cmd("kill-pane", "-t", pane_id), check=False)
    unregister_pane(session, pane_id)


def find_live_pane_by_role(session: str, role: str,
                           window: str | None = None) -> str | None:
    """Find a live pane with the given role, or None if not found.

    Checks both the registry and tmux to ensure the pane actually exists.
    When *window* is given, only that window is searched; otherwise all
    windows are searched.
    Returns the pane ID if found and alive, None otherwise.
    """
    _ensure_logging()
    from pm_core import tmux as tmux_mod

    data = load_registry(session)

    if window:
        windows_to_search = {window: get_window_data(data, window)}
    else:
        windows_to_search = data.get("windows", {})

    _logger.debug("find_live_pane_by_role: session=%s windows=%s role=%s",
                  session, list(windows_to_search), role)

    for win_id, wdata in windows_to_search.items():
        for pane in wdata.get("panes", []):
            if pane.get("role") == role:
                pane_id = pane.get("id")
                if pane_id:
                    live_panes = tmux_mod.get_pane_indices(session, win_id)
                    live_ids = {p[0] for p in live_panes}
                    _logger.debug("find_live_pane_by_role: window=%s live_ids=%s, checking %s",
                                  win_id, live_ids, pane_id)
                    if pane_id in live_ids:
                        _logger.info("find_live_pane_by_role: %s -> %s (alive in %s)",
                                     role, pane_id, win_id)
                        return pane_id
                    else:
                        _logger.info("find_live_pane_by_role: %s -> %s (dead in %s)",
                                     role, pane_id, win_id)
    _logger.info("find_live_pane_by_role: %s -> None", role)
    return None


def _reconcile_registry(session: str, window: str,
                        query_session: str | None = None) -> list[str]:
    """Remove registry panes that no longer exist in tmux. Returns removed IDs.

    Only reconciles the specified *window*.  If the window becomes empty
    its entry is removed from the registry.
    """
    _ensure_logging()
    from pm_core import tmux as tmux_mod

    qs = query_session or session

    # Query tmux state OUTSIDE the lock to avoid holding it during subprocess calls.
    live_panes = tmux_mod.get_pane_indices(qs, window)
    live_ids = {pid for pid, _ in live_panes}
    # Pre-check session existence when there are no live panes.
    session_alive = tmux_mod.session_exists(qs) if not live_ids else True

    removed: list[str] = []

    def modifier(raw):
        data = _prepare_registry_data(raw, session)
        wdata = get_window_data(data, window)

        # If we got zero live panes but the registry has panes, the window
        # may have been destroyed.  Only skip if the entire session is gone
        # (stale registry from a killed session).  If the session is still
        # alive the window was destroyed (last pane killed) and we should
        # report the panes as removed so callers can respawn the TUI.
        if not live_ids and wdata["panes"]:
            if not session_alive:
                _logger.info("reconcile: no live panes for %s:%s and session gone, skipping",
                             session, window)
                return None  # skip write
            _logger.info("reconcile: window %s gone but session %s alive, "
                         "reporting %d pane(s) as removed", window, session,
                         len(wdata["panes"]))

        surviving = []
        for p in wdata["panes"]:
            if p["id"] in live_ids:
                surviving.append(p)
            else:
                removed.append(p["id"])

        if not removed:
            _logger.debug("reconcile: all %d registry panes still alive in window %s",
                         len(wdata["panes"]), window)
            return None  # no changes, skip write

        wdata["panes"] = surviving
        # Remove empty window entry
        if not surviving:
            data["windows"].pop(window, None)
        _logger.info("reconcile: removed dead panes %s from window %s, %d remaining",
                     removed, window, len(surviving))
        return data

    locked_read_modify_write(registry_path(session), modifier)
    return removed
