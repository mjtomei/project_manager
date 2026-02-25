"""Shared helpers for review_loop and monitor_loop.

Extracts functions that were duplicated between the two loop engines
so both can import from a single source.
"""

import time
from typing import Callable


def get_pm_session() -> str | None:
    """Get the pm tmux session name."""
    from pm_core.cli.helpers import _get_current_pm_session
    return _get_current_pm_session()


def find_claude_pane(session: str, window_name: str) -> str | None:
    """Find the Claude pane ID in a window (first pane)."""
    from pm_core import tmux as tmux_mod
    win = tmux_mod.find_window_by_name(session, window_name)
    if not win:
        return None
    panes = tmux_mod.get_pane_indices(session, win["index"])
    if panes:
        return panes[0][0]
    return None


def sleep_checking_pane(pane_id: str, seconds: float,
                        tick: float = 1.0,
                        stop_check: Callable[[], bool] | None = None) -> bool:
    """Sleep for *seconds*, checking pane liveness every tick.

    Returns True if the pane is still alive, False if it disappeared.
    If *stop_check* is provided, it is called each tick; if it returns
    True the sleep terminates early (returns True — pane still alive).
    """
    from pm_core import tmux as tmux_mod

    elapsed = 0.0
    while elapsed < seconds:
        time.sleep(tick)
        elapsed += tick
        if stop_check and stop_check():
            return True  # pane alive but stopping
        if not tmux_mod.pane_exists(pane_id):
            return False
    return True
