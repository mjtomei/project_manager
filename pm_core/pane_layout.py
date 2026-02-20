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
    _get_window_data,
    _iter_all_panes,
    load_registry,
    save_registry,
    register_pane,
    unregister_pane,
    kill_and_unregister,
    find_live_pane_by_role,
    _reconcile_registry,
)

_logger = configure_logger("pm.pane_layout")

MOBILE_WIDTH_THRESHOLD = 120


def get_reliable_window_size(
    session: str, window: str, query_session: str | None = None,
) -> tuple[int, int]:
    """Return (width, height) for *window*, trying multiple sessions.

    Grouped tmux sessions share windows but only the session with an
    attached client reports a non-zero size.  This helper walks the
    fallback chain so every caller gets consistent behaviour:

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

    for s in candidates:
        w, h = tmux_mod.get_window_size(s, window)
        if w > 0 and h > 0:
            return w, h

    # Last resort: walk all grouped sessions
    for gs in tmux_mod.list_grouped_sessions(base):
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

    With window-size=latest, the window size reflects the most recently
    active client, so we only need to check the current window size.
    """
    if mobile_flag_path(session).exists():
        _logger.info("is_mobile(%s, %s): True (force flag)", session, window)
        return True
    width, _ = get_reliable_window_size(session, window)
    return 0 < width < MOBILE_WIDTH_THRESHOLD


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


def _layout_node(panes, x, y, w, h, force_axis=None):
    """Recursively build tmux layout string body.

    panes: list of pane indices (ints), ordered oldest→newest.
    force_axis: 'h' to force horizontal, 'v' to force vertical, None for auto.
    Returns the layout body string for this subtree.
    """
    if len(panes) == 1:
        return f"{w}x{h},{x},{y},{panes[0]}"

    # Split: older group gets fewer panes (left/top, smaller area),
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
    wdata = _get_window_data(data, window)
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
    if force_mobile or (0 < width < MOBILE_WIDTH_THRESHOLD):
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

    data = load_registry(session)
    wdata = _get_window_data(data, window)
    if wdata.get("user_modified"):
        return True

    panes = sorted(wdata["panes"], key=lambda p: p["order"])
    if len(panes) < 2:
        return False

    current = tmux_mod.get_pane_geometries(session, window)
    if not current:
        return False

    # Check pane count matches
    pane_indices = tmux_mod.get_pane_indices(session, window)
    id_to_index = {pid: idx for pid, idx in pane_indices}

    registered_live = [p for p in panes if p["id"] in id_to_index]
    if len(registered_live) != len(current):
        wdata["user_modified"] = True
        save_registry(session, data)
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

    wdata = _get_window_data(data, window)
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


def _respawn_tui(session: str, window: str) -> None:
    """Respawn the TUI pane in *window* after it was killed.

    If the window still exists (other panes remain), splits a new pane
    into it.  If the window is gone (TUI was the last pane), creates a
    new window so the session stays alive.
    """
    from pm_core import tmux as tmux_mod

    _logger.info("_respawn_tui: respawning TUI in %s:%s", session, window)
    try:
        # Check if the window still exists
        live_panes = tmux_mod.get_pane_indices(session, window)
        if live_panes:
            # Window exists — split into it
            target = f"{session}:{window}"
            pane_id = tmux_mod.split_pane(target, "h", "pm _tui")
        else:
            # Window is gone (TUI was the last pane) — create a new one
            _logger.info("_respawn_tui: window %s gone, creating new window", window)
            result = subprocess.run(
                tmux_mod._tmux_cmd("new-window", "-t", f"{session}:",
                                   "-P", "-F", "#{pane_id} #{window_id}",
                                   "pm _tui"),
                capture_output=True, text=True, check=True,
            )
            parts = result.stdout.strip().split()
            pane_id = parts[0]
            # Update window to the newly created one
            window = parts[1] if len(parts) > 1 else window
            # Switch the client to the new window so the user sees it
            qs = tmux_mod.current_or_base_session(base_session_name(session))
            subprocess.run(
                tmux_mod._tmux_cmd("select-window", "-t", f"{qs}:{window}"),
                capture_output=True,
            )

        # Register with lowest order so TUI sorts first (leftmost)
        data = load_registry(session)
        wdata = _get_window_data(data, window)
        min_order = min((p["order"] for p in wdata["panes"]), default=1) - 1
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
        save_registry(session, data)
        _logger.info("_respawn_tui: created pane %s in window %s order=%d",
                     pane_id, window, min_order)
    except Exception:
        _logger.exception("_respawn_tui: failed to respawn TUI")


def _process_registry_pane_closed(data: dict) -> None:
    """Reconcile one registry file after a pane-close event."""
    session = data.get("session", "")
    if not session:
        return

    for window_id, wdata in list(data.get("windows", {}).items()):
        # Snapshot TUI pane IDs before reconciliation removes them
        tui_ids = {p["id"] for p in wdata.get("panes", [])
                   if p.get("role") == "tui"}
        removed = _reconcile_registry(session, window_id)
        if removed:
            _logger.info("handle_any_pane_closed: session=%s window=%s removed=%s",
                         session, window_id, removed)
            # Always respawn TUI regardless of user_modified
            if tui_ids & set(removed):
                _logger.info("handle_any_pane_closed: TUI pane was killed, respawning")
                _respawn_tui(session, window_id)
                # _respawn_tui resets user_modified; always rebalance
                # after respawn so the new TUI pane is sized correctly.
                rebalance(session, window_id)
            elif not wdata.get("user_modified"):
                rebalance(session, window_id)


def handle_any_pane_closed() -> None:
    """Handle a pane-close event when we don't know which pane died.

    Called from global tmux hooks (after-kill-pane). Reconciles all
    registries and rebalances any that changed.  If the killed pane
    was the TUI, automatically respawns it.

    Processes the current session's registry first so the TUI respawns
    immediately rather than waiting for stale registries to reconcile.
    """
    _ensure_logging()
    _logger.info("handle_any_pane_closed called")

    # Process current session first for fast TUI respawn
    from pm_core import tmux as tmux_mod
    current_reg = None
    other_paths = []
    if tmux_mod.in_tmux():
        current_session = tmux_mod.get_session_name()
        current_reg = registry_path(current_session)

    for path in registry_dir().glob("*.json"):
        if current_reg and path == current_reg:
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, KeyError):
                continue
            _process_registry_pane_closed(data)
        else:
            other_paths.append(path)

    for path in other_paths:
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, KeyError):
            continue
        _process_registry_pane_closed(data)


def handle_pane_opened(session: str, window: str, pane_id: str) -> None:
    """Handle pane-opened event: if not in registry, mark per-window user_modified."""
    _ensure_logging()
    _logger.info("handle_pane_opened called: session=%s window=%s pane_id=%s",
                 session, window, pane_id)

    data = load_registry(session)
    wdata = _get_window_data(data, window)
    known_ids = {p["id"] for p in wdata["panes"]}
    if pane_id not in known_ids:
        _logger.info("handle_pane_opened: unknown pane %s in window %s, setting user_modified",
                     pane_id, window)
        wdata["user_modified"] = True
        save_registry(session, data)
