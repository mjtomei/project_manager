"""Automatic tmux pane layout management.

Computes and applies tmux layouts using a recursive binary split algorithm.
Newer panes get priority for larger areas. Handles pane lifecycle events
(opened, exited, closed) and mobile mode detection.

Registry I/O functions live in pm_core.pane_registry; they are re-exported
here for backward compatibility.
"""

import json
import subprocess
import time
from pathlib import Path

from pm_core.paths import configure_logger

# Re-export registry functions for backward compatibility — existing code
# that does ``from pm_core.pane_layout import load_registry`` etc. still works.
from pm_core.pane_registry import (  # noqa: F401
    base_session_name,
    registry_dir,
    registry_path,
    get_window_data,
    _iter_all_panes,
    load_registry,
    locked_read_modify_write,
    _prepare_registry_data,
    register_pane,
    unregister_pane,
    kill_and_unregister,
    find_live_pane_by_role,
    _reconcile_registry,
)

_logger = configure_logger("pm.pane_layout")

# Default mobile-mode width threshold. Overridable via
# `pm set mobile-width-threshold <value>`. Read through
# ``_get_mobile_width_threshold()`` — do not reference this constant
# directly (use the function so the global setting takes effect).
DEFAULT_MOBILE_WIDTH_THRESHOLD = 110

# Default minimum character width per horizontal pane column.
# Overridable via `pm set min-pane-width <value>`.
DEFAULT_MIN_PANE_WIDTH = 100


def _get_mobile_width_threshold() -> int:
    """Read mobile-width-threshold from global settings, or default."""
    from pm_core.paths import get_global_setting_value
    val = get_global_setting_value("mobile-width-threshold", "")
    try:
        return max(1, int(val))
    except ValueError:
        return DEFAULT_MOBILE_WIDTH_THRESHOLD


# Back-compat alias for callers that read the constant directly. New code
# should call ``_get_mobile_width_threshold()`` so the setting applies.
MOBILE_WIDTH_THRESHOLD = DEFAULT_MOBILE_WIDTH_THRESHOLD


def get_reliable_window_size(
    session: str, window: str, query_session: str | None = None,
) -> tuple[int, int]:
    """Return (width, height) for *window*, trying multiple sessions.

    Grouped tmux sessions share windows but only the session with an
    attached client reports a non-zero size.  For shared sessions with
    multiple clients, returns the *minimum* non-zero size across all
    attached sessions so that panes fit on the smallest monitor and
    everyone can see the full layout without scrolling.

    Fallback chain for finding a non-zero size:

    1. *query_session* (if given) — e.g. the session that triggered a
       resize hook.
    2. ``current_or_base_session(base)`` — the current pane's session
       or an attached grouped session.
    3. *session* itself.
    4. Every grouped session (``base~1``, ``base~2``, …).
    """
    from pm_core import tmux as tmux_mod

    base = base_session_name(session)

    # Build an ordered list of sessions to try, deduplicating.
    candidates: list[str] = []
    if query_session:
        candidates.append(query_session)
    best = tmux_mod.current_or_base_session(base)
    if best not in candidates:
        candidates.append(best)
    if session not in candidates:
        candidates.append(session)

    # Collect all grouped sessions for potential multi-client check.  The
    # group comes from tmux (``sessions_in_group``) so a user's own view
    # of the session counts too — its client constrains the layout — while
    # a *different* session whose name merely starts with ``base~`` (a repo
    # directory may contain ``~``) does not.
    grouped = [s for s in tmux_mod.sessions_in_group(base) if s != base]

    # If there are multiple grouped sessions (multi-client), find the
    # minimum non-zero size so panes fit on the smallest connected
    # monitor.  This ensures all clients can see the full layout.
    if grouped:
        min_w, min_h = 0, 0
        all_sessions = list(dict.fromkeys(candidates + [base] + grouped))
        for s in all_sessions:
            w, h = tmux_mod.get_window_size(s, window)
            if w > 0 and h > 0:
                min_w = w if min_w == 0 else min(min_w, w)
                min_h = h if min_h == 0 else min(min_h, h)
        if min_w > 0 and min_h > 0:
            return min_w, min_h

    # Single client: return first non-zero size
    for s in candidates:
        w, h = tmux_mod.get_window_size(s, window)
        if w > 0 and h > 0:
            return w, h

    # Last resort: walk all grouped sessions
    for gs in grouped:
        if gs in candidates:
            continue
        w, h = tmux_mod.get_window_size(gs, window)
        if w > 0 and h > 0:
            return w, h

    return 0, 0


def preferred_split_direction(session: str, window: str) -> str:
    """Return 'h' (left|right) or 'v' (top/bottom) based on window aspect ratio.

    Terminal characters are roughly 2x taller than wide, so a 100-col x 50-row
    window is roughly square in pixels.  We split horizontally when the window
    is physically wider than tall, vertically otherwise.
    """
    w, h = get_reliable_window_size(session, window)
    if w <= 0 or h <= 0:
        return "h"  # fallback
    # Same heuristic as _layout_node: physical_width ∝ w, physical_height ∝ h*2
    return "h" if w >= h * 2 else "v"


def _ensure_logging():
    """No-op for backward compatibility. Logging is now auto-configured."""
    pass


def mobile_flag_path(session: str) -> Path:
    """Return the path to the force-mobile flag file for a session."""
    return registry_dir() / f"{base_session_name(session)}.mobile"


def set_force_mobile(session: str, enabled: bool) -> None:
    """Set or clear the force-mobile flag for a session."""
    path = mobile_flag_path(session)
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        _logger.info("set_force_mobile: enabled for %s", session)
    else:
        path.unlink(missing_ok=True)
        _logger.info("set_force_mobile: disabled for %s", session)


def is_mobile(session: str, window: str = "0") -> bool:
    """Check if mobile mode is active (force flag or narrow terminal).

    With window-size=smallest, the window size reflects the smallest
    connected client, so we only need to check the current window size.
    """
    if mobile_flag_path(session).exists():
        _logger.info("is_mobile(%s, %s): True (force flag)", session, window)
        return True
    width, _ = get_reliable_window_size(session, window)
    return 0 < width < _get_mobile_width_threshold()


# --- Layout string generation ---

def _checksum(layout_body: str) -> str:
    """Compute tmux layout checksum (16-bit).

    tmux uses a simple 16-bit checksum (csum in layout_checksum()).
    Algorithm: for each char, csum = (csum >> 1) + ((csum & 1) << 15) + ord(char)
    Result is formatted as 4 hex digits.
    """
    csum = 0
    for ch in layout_body:
        csum = ((csum >> 1) + ((csum & 1) << 15) + ord(ch)) & 0xFFFF
    return f"{csum:04x}"


def _get_min_pane_width() -> int:
    """Read min-pane-width from global settings, or DEFAULT_MIN_PANE_WIDTH."""
    from pm_core.paths import get_global_setting_value
    val = get_global_setting_value("min-pane-width", "")
    try:
        return max(1, int(val))
    except ValueError:
        return DEFAULT_MIN_PANE_WIDTH


def _max_horizontal_panes(w: int) -> int:
    """Return the max number of horizontal columns that fit in *w* chars.

    Each column must be at least min-pane-width characters wide (configurable
    via ``pm set min-pane-width <value>``, default 100).
    N columns require (N − 1) single-char tmux separators, so the
    constraint is: N * min_w + (N − 1) ≤ w, i.e.
    N ≤ (w + 1) / (min_w + 1).
    """
    min_w = _get_min_pane_width()
    return max(1, (w + 1) // (min_w + 1))


def _distribute_panes(panes: list[int], n_cols: int) -> list[list[int]]:
    """Distribute panes across *n_cols* columns, oldest sharing first.

    Returns a list of lists, one per column.  When there are more panes
    than columns, older panes share columns (stacked vertically) while
    newer panes get dedicated horizontal space.
    """
    if n_cols >= len(panes):
        return [[p] for p in panes]
    base, remainder = divmod(len(panes), n_cols)
    cols: list[list[int]] = []
    idx = 0
    for i in range(n_cols):
        size = base + (1 if i < remainder else 0)
        cols.append(panes[idx:idx + size])
        idx += size
    return cols


def _layout_columns(panes: list[int], x: int, y: int, w: int, h: int,
                    n_cols: int) -> str:
    """Lay out *panes* in *n_cols* equal-width horizontal columns.

    Panes are distributed across columns with older panes sharing columns
    first.  Within each multi-pane column, panes are split vertically.
    Extra pixels go to rightmost (newest) columns.
    """
    cols = _distribute_panes(panes, n_cols)
    separators = n_cols - 1
    usable_w = w - separators
    base_w, remainder = divmod(usable_w, n_cols)

    parts: list[str] = []
    cur_x = x
    for i, col_panes in enumerate(cols):
        # Extra pixels go to rightmost (newest) columns
        col_w = base_w + (1 if i >= n_cols - remainder else 0)
        col_w = max(1, col_w)
        if len(col_panes) == 1:
            parts.append(f"{col_w}x{h},{cur_x},{y},{col_panes[0]}")
        else:
            parts.append(
                _layout_node(col_panes, cur_x, y, col_w, h, force_axis='v'))
        cur_x += col_w + 1  # +1 for tmux separator

    return f"{w}x{h},{x},{y}{{{','.join(parts)}}}"


def _layout_node(panes, x, y, w, h, force_axis=None):
    """Recursively build tmux layout string body.

    panes: list of pane indices (ints), ordered oldest→newest.
    force_axis: 'h' to force horizontal, 'v' to force vertical, None for auto.
    Returns the layout body string for this subtree.
    """
    if len(panes) == 1:
        return f"{w}x{h},{x},{y},{panes[0]}"

    # At the top level (auto axis detection), use multi-column layout
    # when the terminal is wide enough for 3+ columns of MIN_PANE_WIDTH.
    if force_axis is None:
        n_cols = min(_max_horizontal_panes(w), len(panes))
        if n_cols > 2:
            return _layout_columns(panes, x, y, w, h, n_cols)

    # Binary split: older group gets fewer panes (left/top, smaller area),
    # newer group gets more space (right/bottom).
    mid = (len(panes) + 1) // 2
    older = panes[:mid]
    newer = panes[mid:]

    if force_axis == 'h':
        split_h = True
    elif force_axis == 'v':
        split_h = False
    else:
        # Terminal characters are roughly 2× taller than wide, so scale
        # the comparison to approximate physical aspect ratio.
        # physical_width ∝ w, physical_height ∝ h × 2
        split_h = w >= h * 2

    # Opposite axis for child groups so they don't keep splitting the same way
    child_axis = 'v' if split_h else 'h'

    if split_h:
        # Horizontal split (left | right) — older left, newer right
        # tmux uses { } for horizontal (left/right) splits
        # Even split — newer pane(s) have fewer in the group so each gets more space
        left_w = (w - 1) // 2
        right_w = w - left_w - 1
        left_w = max(1, left_w)
        right_w = max(1, right_w)
        left = _layout_node(older, x, y, left_w, h, child_axis if len(older) > 1 else None)
        right = _layout_node(newer, x + left_w + 1, y, right_w, h, child_axis if len(newer) > 1 else None)
        return f"{w}x{h},{x},{y}{{{left},{right}}}"
    else:
        # Vertical split (top / bottom) — older top, newer bottom
        # tmux uses [ ] for vertical (top/bottom) splits
        # Even split — newer pane(s) have fewer in the group so each gets more space
        top_h = (h - 1) // 2
        bot_h = h - top_h - 1
        top_h = max(1, top_h)
        bot_h = max(1, bot_h)
        top = _layout_node(older, x, y, w, top_h, child_axis if len(older) > 1 else None)
        bot = _layout_node(newer, x, y + top_h + 1, w, bot_h, child_axis if len(newer) > 1 else None)
        return f"{w}x{h},{x},{y}[{top},{bot}]"


def compute_layout(n_panes: int, width: int, height: int) -> str:
    """Return a tmux layout string for N panes.

    Panes are indexed 0..n_panes-1, with higher indices being newer
    and getting priority for larger areas.
    """
    if n_panes < 1:
        return ""
    pane_indices = list(range(n_panes))
    body = _layout_node(pane_indices, 0, 0, width, height)
    return f"{_checksum(body)},{body}"


def register_and_rebalance(
    session: str,
    window: str,
    panes: list[tuple[str, str, str]],
) -> None:
    """Register panes, reset user_modified, and rebalance.

    This is the canonical way to register newly-created panes.  The
    after-split-window hook fires handle_pane_opened which sets
    user_modified=True before the pane is in the registry; this function
    always resets that flag so rebalance() is not a no-op.

    Args:
        session: tmux session name.
        window:  tmux window ID.
        panes:   List of (pane_id, role, cmd) tuples to register.
    """
    from pm_core import pane_registry as _reg
    for pane_id, role, cmd in panes:
        _reg.register_pane(session, window, pane_id, role, cmd)

    def _reset_user_modified(raw):
        data = _reg._prepare_registry_data(raw, session)
        wdata = _reg.get_window_data(data, window)
        wdata["user_modified"] = False
        return data

    _reg.locked_read_modify_write(_reg.registry_path(session), _reset_user_modified)
    rebalance(session, window)


def rebalance(session: str, window: str, query_session: str | None = None) -> bool:
    """Load registry, compute layout, apply via tmux select-layout.

    Args:
        session: Base session name for registry lookup.
        window: Window ID or index.
        query_session: Session to use for tmux queries (e.g. the grouped
            session that triggered the resize). Falls back to session if
            not provided.

    Returns True if layout was applied, False otherwise.
    """
    _ensure_logging()
    from pm_core import tmux as tmux_mod

    # Use query_session for tmux operations (window size, pane list, layout).
    # This handles grouped sessions where the base session may not have
    # the same window set.
    qs = query_session or session

    # Clean stale entries before computing layout
    _reconcile_registry(session, window, query_session=qs)

    data = load_registry(session)
    wdata = get_window_data(data, window)
    if wdata.get("user_modified"):
        _logger.info("rebalance: skipping, user_modified=True for window %s", window)
        return False

    panes = sorted(wdata["panes"], key=lambda p: p["order"])
    if len(panes) < 1:
        _logger.info("rebalance: no panes in registry")
        return False

    width, height = get_reliable_window_size(session, window, query_session=qs)
    _logger.info("rebalance: window %s size=%dx%d, %d panes",
                 window, width, height, len(panes))
    if width <= 0 or height <= 0:
        _logger.warning("rebalance: invalid window size")
        return False

    # Get live pane IDs from tmux in their current tmux order
    pane_indices = tmux_mod.get_pane_indices(qs, window)
    live_ids = {pid for pid, _ in pane_indices}
    tmux_order = [pid for pid, _ in pane_indices]  # current tmux index order
    _logger.debug("rebalance: tmux pane order: %s", tmux_order)

    # Desired order: registered panes first (by order), then any
    # unregistered tmux panes appended at the end.  The layout string
    # MUST cover every live tmux pane or select-layout will reject it.
    desired_order = [p["id"] for p in panes if p["id"] in live_ids]
    registered_set = set(desired_order)
    for pid in tmux_order:
        if pid not in registered_set:
            desired_order.append(pid)
            _logger.debug("rebalance: including unregistered tmux pane %s", pid)

    if len(desired_order) < 1:
        _logger.warning("rebalance: no matching panes found")
        return False

    if len(desired_order) == 1:
        _logger.info("rebalance: only 1 pane, nothing to layout")
        return True

    _logger.info("rebalance: layout for %d panes (registered=%d, total_tmux=%d)",
                 len(desired_order), len(registered_set), len(tmux_order))

    # Reorder panes in tmux to match registry order using swap-pane.
    # tmux assigns layout positions by pane index order, so we need
    # the tmux order to match our desired order.
    current = list(tmux_order)
    for i, desired_id in enumerate(desired_order):
        if i >= len(current):
            break
        if current[i] != desired_id:
            # Find where desired_id currently is
            j = current.index(desired_id) if desired_id in current else -1
            if j > i:
                _logger.debug("rebalance: swapping %s (pos %d) with %s (pos %d)",
                              current[i], i, desired_id, j)
                tmux_mod.swap_pane(desired_id, current[i])
                current[i], current[j] = current[j], current[i]

    # Use simple sequential indices for the layout string since panes
    # are now in the correct tmux order
    pane_nums = [int(pid.lstrip("%")) for pid in desired_order]

    body = _layout_node(pane_nums, 0, 0, width, height)
    layout_str = f"{_checksum(body)},{body}"
    _logger.info("rebalance: applying layout: %s", layout_str)

    ok = tmux_mod.apply_layout(qs, window, layout_str)
    if not ok:
        _logger.warning("rebalance: apply_layout failed")
        return False

    # In mobile mode, zoom the active pane after layout.
    # Use already-computed width instead of re-querying via is_mobile(),
    # which might hit a different session/window and get a stale size.
    force_mobile = mobile_flag_path(session).exists()
    if force_mobile or (0 < width < _get_mobile_width_threshold()):
        result = subprocess.run(
            tmux_mod._tmux_cmd("display", "-t", f"{qs}:{window}", "-p", "#{pane_id}"),
            capture_output=True, text=True,
        )
        active_pane = result.stdout.strip()
        if active_pane:
            _logger.info("rebalance: mobile mode, zooming active pane %s", active_pane)
            tmux_mod.zoom_pane(active_pane)

    return True


def check_user_modified(session: str, window: str) -> bool:
    """Check if the user has manually modified the layout.

    Compares actual pane geometry against expected layout. If different,
    sets user_modified flag in the per-window registry entry.
    """
    from pm_core import tmux as tmux_mod
    from pm_core.pane_registry import locked_read_modify_write, _prepare_registry_data

    # Fast path: read-only check (unlocked, stale read is fine)
    data = load_registry(session)
    wdata = get_window_data(data, window)
    if wdata.get("user_modified"):
        return True

    panes = sorted(wdata["panes"], key=lambda p: p["order"])
    if len(panes) < 2:
        return False

    # Query tmux state outside the lock
    current = tmux_mod.get_pane_geometries(session, window)
    if not current:
        return False

    pane_indices = tmux_mod.get_pane_indices(session, window)
    id_to_index = {pid: idx for pid, idx in pane_indices}

    registered_live = [p for p in panes if p["id"] in id_to_index]
    if len(registered_live) != len(current):
        def _set_user_modified(raw):
            d = _prepare_registry_data(raw, session)
            wd = get_window_data(d, window)
            wd["user_modified"] = True
            return d

        locked_read_modify_write(registry_path(session), _set_user_modified)
        return True

    return False


def handle_pane_exited(session: str, window: str, generation: str,
                       pane_id: str = "") -> None:
    """Handle a pane-exited event from a bash EXIT trap.

    The generation arg is a timestamp from when the session was created.
    If it doesn't match the current registry generation, this is a stale
    trap from a previous session and we ignore it.
    pane_id is the $TMUX_PANE of the exiting pane (e.g. '%42').
    """
    _ensure_logging()
    _logger.info("handle_pane_exited called: session=%s window=%s gen=%s pane=%s",
                 session, window, generation, pane_id)

    data = load_registry(session)

    # Ignore stale traps from old sessions
    reg_gen = data.get("generation", "")
    if reg_gen and reg_gen != generation:
        _logger.info("handle_pane_exited: stale trap (gen %s != registry %s), ignoring",
                     generation, reg_gen)
        return

    wdata = get_window_data(data, window)
    if wdata.get("user_modified"):
        _logger.info("handle_pane_exited: user_modified for window %s, skipping", window)
        if pane_id:
            unregister_pane(session, pane_id)
        return

    # Directly unregister the pane that exited
    if pane_id:
        before_count = sum(len(w["panes"]) for w in data["windows"].values())
        unregister_pane(session, pane_id)
        data = load_registry(session)
        after_count = sum(len(w["panes"]) for w in data.get("windows", {}).values())
        if after_count == before_count:
            _logger.info("handle_pane_exited: pane %s was not in registry", pane_id)
            return
    else:
        _logger.info("handle_pane_exited: no pane_id, using reconciliation")
        time.sleep(0.5)
        removed = _reconcile_registry(session, window)
        if not removed:
            _logger.info("handle_pane_exited: no panes were removed from registry")
            return

    # The EXIT trap runs while the dying pane is still alive in tmux.
    # If we rebalance now, the layout includes the dying pane; when it
    # dies moments later tmux recalculates the layout and unzooms.
    # Fix: unzoom, switch focus away, then defer rebalance via a
    # detached background process that waits for the pane to die first.
    from pm_core import tmux as tmux_mod
    tmux_mod.unzoom_pane(session, window)
    if pane_id:
        # Focus the last active pane (the one the user was in before the
        # dying pane).  Fall back to next pane if there is no last pane.
        result = subprocess.run(
            tmux_mod._tmux_cmd("select-pane", "-t", f"{session}:{window}", "-l"),
            capture_output=True,
        )
        if result.returncode != 0:
            subprocess.run(
                tmux_mod._tmux_cmd("select-pane", "-t", f"{session}:{window}", "-t", ":.+"),
                check=False,
            )

    # Defer rebalance so it runs after the dying pane is gone.
    # start_new_session detaches the process from the dying pane's PTY.
    import sys
    _logger.info("handle_pane_exited: deferring rebalance for %s:%s",
                 session, window)
    subprocess.Popen(
        [sys.executable, "-c",
         "import time; time.sleep(0.3); "
         "from pm_core.pane_layout import rebalance; "
         f"rebalance({session!r}, {window!r})"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def tui_respawn_window(session: str, preferred: str | None = None) -> str | None:
    """Return the window a missing TUI of *session* is started in.

    *preferred* is the window the registry (or the hook's snapshot of it)
    listed the TUI in, and is used when given.  Otherwise the window named
    ``main`` — deliberately not the active window, which may be a QA or
    work window — and failing that the first window.  ``None`` when the
    session has no windows at all.

    The one definition of "where the TUI goes back", shared by
    ``pm session``'s attach (``cli.session._ensure_tui_running``) and the
    ``after-kill-pane`` hook (``_respawn_unlisted_tui``), so the two cannot
    start a respawned TUI in different places.
    """
    from pm_core import tmux as tmux_mod

    if preferred:
        return preferred
    main = tmux_mod.find_window_by_name(session, "main")
    if main:
        return main["id"]
    windows = tmux_mod.list_windows(session)
    return windows[0]["id"] if windows else None


def _respawn_tui(session: str, window: str, *, select: bool = True) -> str:
    """Respawn the TUI pane in *window* after it was killed.

    If the window still exists (other panes remain), splits a new pane
    into it.  If the window is gone (TUI was the last pane), creates a
    new window so the session stays alive.

    A new window is selected for the caller's client (``select_window``
    picks the client) unless *select* is false.  ``pm session`` passes
    false: run outside tmux it has no client of its own yet, so
    ``select_window`` fell back to the first *attached* grouped session
    and switched another user's client — a shared session's owner — to
    the new window, while the attach landed on whatever window its own
    grouped session showed (QA S45).  It selects the window in the
    grouped session it attaches instead.

    Returns the window ID the TUI was actually created in (may differ
    from *window* when a new window had to be created).

    The TUI starts in the directory the session was created in (the
    project's repo directory), not in tmux's default — the cwd of the
    client that ran the command.  The ``after-kill-pane`` hook runs this
    for whichever client killed the pane, so a ``tmux kill-pane`` typed in
    another project's directory used to start a TUI for *that* project in
    this session (its pidfile and registry), and one typed outside any
    project started the pm guide there (QA S42).

    Callers decide that the TUI is missing and call this while holding
    ``pane_registry.tui_respawn_lock``, so two of them never both start
    one.
    """
    from pm_core import tmux as tmux_mod

    _logger.info("_respawn_tui: respawning TUI in %s:%s", session, window)
    try:
        # Check if the window still exists
        live_panes = tmux_mod.get_pane_indices(session, window)
        if live_panes:
            # Window exists — split into it
            target = f"{session}:{window}"
            pane_id = tmux_mod.split_pane(
                target, "h", "pm _tui",
                start_dir_format=tmux_mod.SESSION_START_DIR)
        else:
            # Window is gone (TUI was the last pane) — create a new one
            _logger.info("_respawn_tui: window %s gone, creating new window", window)
            pane_id, window = tmux_mod.create_window(
                session, "pm _tui",
                start_dir_format=tmux_mod.SESSION_START_DIR)
            tmux_mod.set_shared_window_size(session, window)
            # Switch the client to the new window so the user sees it
            if select:
                tmux_mod.select_window(session, window)

        # Register with lowest order so TUI sorts first (leftmost)
        from pm_core.pane_registry import locked_read_modify_write, _prepare_registry_data

        def _insert_tui(raw):
            data = _prepare_registry_data(raw, session)
            wdata = get_window_data(data, window)
            # The new TUI may already be listed: it records itself once
            # mounted, and a `pm session` that ran without the respawn
            # lock may have adopted it.  List it once (QA S42).
            if not any(p["id"] == pane_id for p in wdata["panes"]):
                min_order = min((p["order"] for p in wdata["panes"]),
                                default=1) - 1
                wdata["panes"].insert(0, {
                    "id": pane_id,
                    "role": "tui",
                    "order": min_order,
                    "cmd": "pm _tui",
                })
            # Reset user_modified — same pattern as pane_ops.launch_pane()
            # and cli/pr.py review window (after-split-window hook may have
            # set it before panes are registered).  Caller rebalances.
            wdata["user_modified"] = False
            return data

        locked_read_modify_write(registry_path(session), _insert_tui)
        _logger.info("_respawn_tui: created pane %s in window %s", pane_id, window)
    except Exception:
        _logger.exception("_respawn_tui: failed to respawn TUI")
    return window


def _process_registry_pane_closed(data: dict) -> None:
    """Reconcile one registry file after a pane-close event."""
    session = data.get("session", "")
    if not session:
        return

    from pm_core.pane_registry import tui_respawn_lock

    to_rebalance: list[str] = []
    # Windows the registry listed a TUI in when this event was read.
    tui_windows: list[str] = []
    tui_handled = False
    # A `pm session` attach may find the TUI gone at this same moment and
    # respawn it; deciding under the lock it also holds means only one of
    # us starts a TUI (QA S42).  The lock is taken once for the whole
    # event, not once per registered window: this hook is a synchronous
    # run-shell, so the client that closed the pane is frozen while it
    # waits, and a stuck holder froze it for one full wait per window —
    # 30 s with the main window and two review windows (QA S47).
    with tui_respawn_lock(session) as locked:
        for window_id, wdata in list(data.get("windows", {}).items()):
            # Snapshot TUI pane IDs before reconciliation removes them
            tui_ids = {p["id"] for p in wdata.get("panes", [])
                       if p.get("role") == "tui"}
            if tui_ids:
                tui_windows.append(window_id)
            removed = _reconcile_registry(session, window_id)
            if not removed:
                continue
            _logger.info("handle_any_pane_closed: session=%s window=%s removed=%s",
                         session, window_id, removed)
            actual_window = None
            # Always respawn TUI regardless of user_modified
            if tui_ids & set(removed):
                tui_handled = True
                running = _running_tui_pane(session)
                if running:
                    _logger.info("handle_any_pane_closed: TUI pane was killed, "
                                 "but TUI pane %s is already running; not "
                                 "respawning", running)
                else:
                    _logger.info("handle_any_pane_closed: TUI pane was killed, respawning")
                    actual_window = _respawn_tui(session, window_id)
            if actual_window:
                # _respawn_tui resets user_modified; always rebalance
                # after respawn so the new TUI pane is sized correctly.
                # Use the actual window ID (may differ if a new window
                # was created because the TUI was the last pane).
                to_rebalance.append(actual_window)
            elif not wdata.get("user_modified"):
                to_rebalance.append(window_id)
        if locked and not tui_handled:
            actual_window = _respawn_unlisted_tui(session, tui_windows)
            if actual_window:
                to_rebalance.append(actual_window)
    # Layout work runs after the lock is released, as before.
    for window_id in dict.fromkeys(to_rebalance):
        rebalance(session, window_id)


def _respawn_unlisted_tui(session: str, tui_windows: list[str]) -> str | None:
    """Respawn a killed TUI whose registry entry another process removed.

    Every ``rebalance()`` reconciles the registry first, without the
    TUI-respawn lock: the background rebalance a ``pm session`` attach
    schedules, the ``window-resized`` hook, a pane's EXIT trap.  When one
    of them ran between the TUI's kill and this hook, it had already
    dropped the dead TUI's entry, so this hook's own reconcile removed
    nothing and the session was left with no TUI (QA S50: 2 of 4 rounds
    with the attach's Enter 0.60-0.65 s before the kill, 5 of 8 for the
    refiner; the entry was often gone before this hook even read the
    registry, so the hook's own snapshot did not list the TUI either).

    So, under the lock, a session whose registry now lists no TUI and
    that runs no ``pm _tui`` pane gets one, whoever removed the entry.  A
    TUI pane kept dead by ``remain-on-exit`` is still listed, and
    ``pm session`` leaves it alone too, so this does not start one beside
    it.  The TUI goes back into the window the registry listed it in when
    this event was read (*tui_windows*); with no such window it goes into
    ``main``, else the first window (``tui_respawn_window``, the same rule
    ``pm session``'s attach uses).

    Called only while this hook holds the lock: two hooks that both went
    ahead past a stuck holder would otherwise both find no TUI and both
    start one, where only the one whose reconcile removed the entry did.
    Returns the window the TUI was started in, or ``None``.
    """
    registry = load_registry(session)
    if any(p.get("role") == "tui" for _, p in _iter_all_panes(registry)):
        return None
    if _running_tui_pane(session):
        return None
    window = tui_respawn_window(session,
                                tui_windows[0] if tui_windows else None)
    if window is None:
        _logger.warning("handle_any_pane_closed: no TUI is running and "
                        "session %s has no windows; not respawning", session)
        return None
    _logger.info("handle_any_pane_closed: no TUI is running and none is "
                 "registered (its entry was already reconciled); "
                 "respawning in window %s", window)
    return _respawn_tui(session, window)


def _running_tui_pane(session: str) -> str | None:
    """Pane id of a running TUI of *session*, or ``None``.

    The same definition ``pm session`` adopts by (a live ``pm _tui`` pane
    of the session's group: ``cli.helpers._find_running_tui_pane``).
    """
    from pm_core.cli.helpers import _find_running_tui_pane
    running = _find_running_tui_pane(session)
    return running[0] if running else None


def handle_any_pane_closed(session: str = "") -> None:
    """Handle a pane-close event when we don't know which pane died.

    Called from global tmux hooks (after-kill-pane). Only processes the
    session's registry — the killed pane must belong to the session where
    the hook fired.  If the killed pane was the TUI, automatically
    respawns it.

    ``session`` is the session the hook fired in (``#{session_name}``).
    When it is empty the session is derived from ``$TMUX_PANE``, which can
    name a pane that is not on this server: the pane the hook reports has
    just been killed, and a server started from inside an ambient tmux
    inherits that tmux's pane id.  Either way ``display-message -t`` then
    returns an empty name and the killed TUI would never be respawned, so
    the hook's own session name is the reliable one.
    """
    _ensure_logging()
    _logger.info("handle_any_pane_closed called")

    from pm_core import tmux as tmux_mod
    if not tmux_mod.in_tmux():
        _logger.info("handle_any_pane_closed: not in tmux, skipping")
        return

    # A user's own grouped view (myview) shares the pm session's registry.
    from pm_core.pane_registry import pm_session_name
    current_session = pm_session_name(session or tmux_mod.get_session_name())
    reg_path = registry_path(current_session)
    if not reg_path.exists():
        _logger.info("handle_any_pane_closed: no registry for %s", current_session)
        return
    # The hooks are global on the server, so they also fire for a plain
    # session a user created beside the pm one (a scratch shell).  Such a
    # session is not pm's: a pane close in it must not reconcile a pm
    # registry or respawn a TUI into it.  Checked after the registry probe
    # so an unresolved session (empty name) still logs the same line.
    if not current_session.startswith("pm-"):
        _logger.info("handle_any_pane_closed: ignoring non-pm session %s",
                     current_session)
        return

    try:
        data = json.loads(reg_path.read_text())
    except (json.JSONDecodeError, KeyError):
        return
    _process_registry_pane_closed(data)


def handle_pane_opened(session: str, window: str, pane_id: str) -> None:
    """Handle pane-opened event: if not in registry, mark per-window user_modified.

    *session* is the name tmux reported for the hook.  It is resolved
    through its group first, so a user's own grouped view of a pm session
    (any name, S121) marks that session's registry; a session that does
    not resolve to a pm one is ignored (QA S58).
    """
    _ensure_logging()
    _logger.info("handle_pane_opened called: session=%s window=%s pane_id=%s",
                 session, window, pane_id)

    from pm_core.pane_registry import (locked_read_modify_write,
                                       pm_session_name,
                                       _prepare_registry_data)

    # A split in a plain session the user created on the same server must
    # not create a registry: the after-kill-pane hook keys on that file, and
    # with one present a later pane close there respawned a pm TUI into the
    # user's scratch session (QA S58).  A view grouped with a pm session
    # resolves through the group and shares that session's registry.
    resolved = pm_session_name(session)
    if not resolved.startswith("pm-"):
        _logger.info("handle_pane_opened: ignoring non-pm session %s", session)
        return

    def _mark_user_modified(raw):
        data = _prepare_registry_data(raw, resolved)
        wdata = get_window_data(data, window)
        known_ids = {p["id"] for p in wdata["panes"]}
        if pane_id not in known_ids:
            _logger.info("handle_pane_opened: unknown pane %s in window %s, setting user_modified",
                         pane_id, window)
            wdata["user_modified"] = True
            return data
        return None  # pane already known, skip write

    locked_read_modify_write(registry_path(resolved), _mark_user_modified)
