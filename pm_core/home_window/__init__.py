"""Home window — pluggable provider for the long-lived 'park here' tmux window.

The home window is a stable destination tmux switches to whenever pm
deliberately kills a window the user is currently focused on (merge
cleanup, picker --fresh, review-loop supersede, etc.).  Without this,
tmux falls back to the previous-window in the client's history, which
in multi-attached setups can yank focus into another client's view.

This package defines the seam:
- ``HomeWindowProvider`` — protocol providers implement.
- ``register`` / ``get_active_provider`` — module-level registry keyed
  by name, resolved via the ``home-window-provider`` global setting
  (default ``"pr-list"``).
- ``ensure_home_window`` — for callers doing batch kills that want the
  home window pre-created and want to park manually after all kills.
- ``park_if_on`` — for single-kill callsites: ensures + parks only if
  the calling client is currently focused on the soon-to-be-killed
  window so the post-kill landing is the home window instead of tmux's
  last-window.

The default ``pr-list`` provider lives in ``pm_core.home_window.pr_list``.
A future ``work-pane`` provider will register here without changing any
kill-window callsite.
"""

from __future__ import annotations

import logging
import sys
from typing import Protocol

from pm_core import tmux as tmux_mod
from pm_core.paths import get_global_setting_value


_log = logging.getLogger("pm.home_window")


class HomeWindowProvider(Protocol):
    name: str
    window_name: str

    def ensure_window(self, session: str) -> str:
        """Create the home window if needed; return its tmux window name."""

    def refresh(self, session: str) -> None:
        """Trigger an immediate re-render of the home window content."""


_REGISTRY: dict[str, HomeWindowProvider] = {}


def register(provider: HomeWindowProvider) -> None:
    _REGISTRY[provider.name] = provider


def get_active_provider() -> HomeWindowProvider:
    """Resolve the active provider from the ``home-window-provider`` setting.

    Falls back to ``pr-list`` with a warning if the setting names an
    unknown provider.
    """
    _ensure_default_registered()
    name = get_global_setting_value("home-window-provider", "pr-list") or "pr-list"
    provider = _REGISTRY.get(name)
    if provider is None:
        print(
            f"pm: unknown home-window-provider {name!r}, falling back to 'pr-list'",
            file=sys.stderr,
        )
        provider = _REGISTRY["pr-list"]
    return provider


def _ensure_default_registered() -> None:
    if "pr-list" not in _REGISTRY:
        from pm_core.home_window.pr_list import PrListProvider
        register(PrListProvider())


def ensure_home_window(session: str | None = None) -> str | None:
    """Ensure the home window exists and return its name.

    Intended for callers that want to do the focus check themselves and
    park manually after a batch of kills (see ``kill_pr_windows``).
    Most kill-window callsites should use ``park_if_on`` instead, which
    bundles the focus check + ensure + select in one call.

    Returns the home window name on success, or None on no-op (not in
    tmux, no session, provider failure).
    """
    if not tmux_mod.in_tmux():
        return None
    if not session:
        return None
    if not tmux_mod.session_exists(session):
        return None
    try:
        provider = get_active_provider()
        return provider.ensure_window(session)
    except Exception:
        _log.exception("ensure_home_window: provider.ensure_window failed")
        return None


def park_if_on(session: str | None, target_window_id: str | None) -> None:
    """If the caller's grouped session is on ``target_window_id``, park to home.

    Convenience for the kill-window pattern:

        park_if_on(session, win["id"])
        tmux.kill_window(session, win["id"])

    Resolves the active window of the calling client's grouped session;
    if it matches ``target_window_id`` we ensure the home window exists
    and switch to it before the kill.  Otherwise no-op (the kill won't
    yank the user's focus, so we shouldn't either).
    """
    if not tmux_mod.in_tmux() or not session or not target_window_id:
        return
    try:
        if not tmux_mod.session_exists(session):
            return
        cur = tmux_mod.get_window_id(session)
        if cur != target_window_id:
            return
        provider = get_active_provider()
        home = provider.ensure_window(session)
        tmux_mod.select_window(session, home)
    except Exception:
        _log.exception("park_if_on failed")


def park(session: str, home_window: str | None = None) -> None:
    """Switch the calling client's grouped session to the home window.

    Call this *after* killing the user's focused window so the post-kill
    landing is the home window (instead of tmux's previous-window).
    Scoped to the caller's grouped session via ``select_window``'s use
    of ``current_or_base_session``.
    """
    if not tmux_mod.in_tmux() or not session:
        return
    try:
        if home_window is None:
            provider = get_active_provider()
            home_window = provider.ensure_window(session)
        tmux_mod.select_window(session, home_window)
    except Exception:
        _log.exception("park: failed to switch to home window")
