"""Pane pull/push operations for focus mode.

Provides functions to:
- Pull all panes from a command window into the TUI's main window
- Push pulled panes back to their original window
- Track which panes are currently pulled

Used by pr_view.py for start/review commands with the 'a' prefix key
or when focus-mode is globally enabled.
"""

import dataclasses
import os
import subprocess

from pm_core.paths import configure_logger, get_global_setting
from pm_core import tmux as tmux_mod
from pm_core import pane_registry, pane_layout

_log = configure_logger("pm.tui.pane_pull")


@dataclasses.dataclass
class PulledPaneInfo:
    """Tracks panes that were pulled from a command window into the main window."""
    pr_window_name: str        # Name of the original command window (e.g. "#42")
    pr_window_id: str          # Window ID of the command window (e.g. "@5")
    pulled_pane_ids: list      # Pane IDs moved to main window (may be multiple)
    dummy_pane_id: str         # Dummy shell left in the command window


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def should_pull(app, explicit_a: bool) -> bool:
    """Determine if pull mode should be active.

    Returns True if the user pressed the 'a' prefix or focus-mode is enabled.
    """
    return explicit_a or get_global_setting("focus-mode")


def is_pulled(app, window_name: str) -> bool:
    """Check if panes from the given window are currently pulled to main."""
    return window_name in getattr(app, "_pulled_panes", {})


def get_window_name_for_start(pr: dict) -> str:
    """Get the expected tmux window name for a PR's implementation window."""
    from pm_core.cli.helpers import _pr_display_id
    return _pr_display_id(pr)


def get_window_name_for_review(pr: dict) -> str:
    """Get the expected tmux window name for a PR's review window."""
    from pm_core.cli.helpers import _pr_display_id
    return f"review-{_pr_display_id(pr)}"


def get_window_name_for_merge(pr: dict) -> str:
    """Get the expected tmux window name for a PR's merge-resolution window."""
    from pm_core.cli.helpers import _pr_display_id
    return f"merge-{_pr_display_id(pr)}"


def get_tui_window() -> str | None:
    """Get the window ID containing the TUI pane.

    Uses $TMUX_PANE to find the window reliably, even if the active
    window has been switched by a command like 'pr start'.
    """
    tui_pane = os.environ.get("TMUX_PANE")
    if not tui_pane:
        return None
    result = subprocess.run(
        tmux_mod._tmux_cmd("display-message", "-p", "-t", tui_pane, "#{window_id}"),
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


# ---------------------------------------------------------------------------
# Shared pull/push entry point (used by all window-creating commands)
# ---------------------------------------------------------------------------

def try_pull_or_push(app, window_name: str) -> str:
    """Handle pull mode for a window-creating command.

    Checks whether to pull, push back, or create-then-pull.
    Returns one of:
      "pulled"  — existing window was pulled to main (caller should return)
      "pushed"  — already-pulled pane was pushed back (caller should return)
      "proceed" — no existing window; caller should run the command,
                  using make_on_complete(app, window_name) as on_complete
    """
    # Toggle: if already pulled, push back
    if is_pulled(app, window_name):
        push_pane_back(app, window_name)
        return "pushed"

    # If window already exists, just pull (no new window needed)
    if app._session_name:
        existing = tmux_mod.find_window_by_name(app._session_name, window_name)
        if existing:
            pull_pane_from_window(app, window_name)
            return "pulled"

    return "proceed"


def make_on_complete(app, window_name: str):
    """Return an on_complete callback that pulls a window after creation."""
    return lambda: pull_pane_from_window(app, window_name)


# ---------------------------------------------------------------------------
# Pull: command window -> main window
# ---------------------------------------------------------------------------

def pull_pane_from_window(app, window_name: str) -> bool:
    """Pull all panes from a command window into the TUI's main window.

    1. Find the command window by name
    2. Get all panes in it
    3. Create a dummy shell pane to keep the window alive
    4. join_pane each pane into the main window
    5. Register, rebalance, and track

    Returns True on success, False on failure.
    """
    session = app._session_name
    if not session or not tmux_mod.in_tmux():
        app.log_message("Not in tmux")
        return False

    main_window = get_tui_window()
    if not main_window:
        _log.warning("pull_pane: could not determine TUI window")
        app.log_message("Could not determine TUI window")
        return False

    # Find the command window
    win = tmux_mod.find_window_by_name(session, window_name)
    if not win:
        _log.warning("pull_pane: window '%s' not found", window_name)
        app.log_message(f"Window '{window_name}' not found")
        return False

    pr_window_id = win["id"]
    pr_window_index = win["index"]

    # Get all panes in the command window
    panes = tmux_mod.get_pane_indices(session, pr_window_index)
    if not panes:
        _log.warning("pull_pane: no panes in window '%s'", window_name)
        return False

    pane_ids = [pid for pid, _ in panes]

    # Create a dummy shell BEFORE moving panes so the window survives.
    # Split off the first pane; the dummy stays behind.
    hint_key = window_name[0] if window_name else "s"
    dummy_msg = (
        "echo ''; "
        "echo '  Panes pulled to main window.'; "
        f"echo '  Press a+{hint_key} in the TUI to push back.'; "
        "echo ''; "
        "echo '  This placeholder keeps the window alive.'; "
        "echo '  Press Enter for a shell.'; "
        "read; exec $SHELL"
    )
    dummy_pane_id = tmux_mod.split_pane_at(
        pane_ids[0], "h", f"bash -c '{dummy_msg}'", background=True,
    )
    _log.info("pull_pane: created dummy %s in window '%s'", dummy_pane_id, window_name)

    # Move each original pane to the main window
    direction = pane_layout.preferred_split_direction(session, main_window)
    moved = []
    for pane_id in pane_ids:
        ok = tmux_mod.join_pane(pane_id, main_window, direction=direction,
                                background=True)
        if ok:
            moved.append(pane_id)
            # Register in the main window's pane registry
            pane_registry.register_pane(
                session, main_window, pane_id,
                f"pulled:{window_name}", "pulled-pane",
            )
            _log.info("pull_pane: moved %s to main window", pane_id)
        else:
            _log.error("pull_pane: join_pane failed for %s", pane_id)

    if not moved:
        # Clean up the dummy — no panes were moved so nothing to track
        if dummy_pane_id and tmux_mod.pane_exists(dummy_pane_id):
            subprocess.run(
                tmux_mod._tmux_cmd("kill-pane", "-t", dummy_pane_id),
                check=False,
            )
            _log.info("pull_pane: killed orphan dummy %s", dummy_pane_id)
        app.log_message("Failed to pull panes")
        return False

    # Reset user_modified and rebalance (standard pattern)
    data = pane_registry.load_registry(session)
    wdata = pane_registry.get_window_data(data, main_window)
    wdata["user_modified"] = False
    pane_registry.save_registry(session, data)
    pane_layout.rebalance(session, main_window)

    # Switch active window back to main and focus the first pulled pane
    tmux_mod.select_window(session, main_window)
    tmux_mod.select_pane_smart(moved[0], session, main_window)

    # Track the pull
    app._pulled_panes[window_name] = PulledPaneInfo(
        pr_window_name=window_name,
        pr_window_id=pr_window_id,
        pulled_pane_ids=moved,
        dummy_pane_id=dummy_pane_id,
    )

    _log.info("pull_pane: pulled %d pane(s) from '%s' to main window",
              len(moved), window_name)
    app.log_message(f"Pulled {window_name} to main window")
    return True


# ---------------------------------------------------------------------------
# Push: main window -> command window
# ---------------------------------------------------------------------------

def push_pane_back(app, window_name: str) -> bool:
    """Push pulled panes back to their original command window.

    1. Look up PulledPaneInfo
    2. Kill the dummy pane in the command window
    3. join_pane each pulled pane back to the command window
    4. Unregister from main window, rebalance
    5. Switch to the command window

    Returns True on success, False on failure.
    """
    pull_info = app._pulled_panes.get(window_name)
    if not pull_info:
        _log.warning("push_pane: no pull info for '%s'", window_name)
        return False

    session = app._session_name
    if not session or not tmux_mod.in_tmux():
        return False

    main_window = get_tui_window()

    # Verify the command window still exists
    win = tmux_mod.find_window_by_name(session, window_name)
    if not win:
        _log.warning("push_pane: window '%s' gone, cleaning up", window_name)
        _cleanup_pull(app, session, main_window, window_name, pull_info)
        app.log_message(f"Window '{window_name}' no longer exists")
        return False

    pr_window_index = win["index"]

    # Move each pulled pane back to the command window BEFORE killing the
    # dummy — the dummy is the only pane keeping the window alive.
    pushed = 0
    for pane_id in pull_info.pulled_pane_ids:
        if not tmux_mod.pane_exists(pane_id):
            _log.info("push_pane: pane %s is dead, skipping", pane_id)
            continue
        ok = tmux_mod.join_pane(pane_id, f"{session}:{pr_window_index}",
                                direction="h", background=True)
        if ok:
            pushed += 1
            _log.info("push_pane: moved %s back to '%s'", pane_id, window_name)
        else:
            _log.error("push_pane: join_pane back failed for %s", pane_id)

    # Now kill the dummy pane (no longer needed to keep the window alive)
    if tmux_mod.pane_exists(pull_info.dummy_pane_id):
        subprocess.run(
            tmux_mod._tmux_cmd("kill-pane", "-t", pull_info.dummy_pane_id),
            check=False,
        )
        _log.info("push_pane: killed dummy %s", pull_info.dummy_pane_id)

    # Cleanup main window registrations and rebalance
    _cleanup_pull(app, session, main_window, window_name, pull_info)

    # Switch to the command window
    tmux_mod.select_window(session, win["index"])

    _log.info("push_pane: pushed %d pane(s) back to '%s'", pushed, window_name)
    app.log_message(f"Pushed {window_name} back")
    return True


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def _cleanup_pull(app, session: str, main_window: str | None,
                  window_name: str, pull_info: PulledPaneInfo) -> None:
    """Unregister pulled panes from main window and rebalance."""
    for pane_id in pull_info.pulled_pane_ids:
        pane_registry.unregister_pane(session, pane_id)

    if main_window:
        data = pane_registry.load_registry(session)
        wdata = pane_registry.get_window_data(data, main_window)
        wdata["user_modified"] = False
        pane_registry.save_registry(session, data)
        pane_layout.rebalance(session, main_window)

    app._pulled_panes.pop(window_name, None)
