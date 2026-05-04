"""Resolve the tmux session a CLI command should target.

Used by commands that manage tmux windows (e.g. ``pr qa``,
``pr review-loop start``) and need to work both when invoked from
inside the pm session and from outside (watchers, automations, popup
subprocesses).

Resolution order:

1. ``--session <name>`` flag, if passed.
2. ``PM_SESSION`` environment variable.
3. In-tmux detection via :func:`pm_core.cli.helpers._get_pm_session`.

If none yield a session, the caller exits with a clear error.
"""

from __future__ import annotations

import os

import click

from pm_core import tmux as tmux_mod
from pm_core.cli.helpers import _get_pm_session


def resolve_target_session(explicit: str | None) -> str:
    """Return the tmux session name to operate against.

    Raises ``SystemExit(1)`` (via ``click.echo`` + ``raise``) when no
    session is resolvable.  Verifies the resulting session actually
    exists in tmux.
    """
    candidate = explicit or os.environ.get("PM_SESSION") or _get_pm_session()
    if not candidate:
        click.echo(
            "No tmux session resolved. Pass --session <name>, set "
            "PM_SESSION, or run from inside a pm tmux session.",
            err=True,
        )
        raise SystemExit(1)
    if not tmux_mod.has_tmux() or not tmux_mod.session_exists(candidate):
        click.echo(
            f"tmux session '{candidate}' does not exist.",
            err=True,
        )
        raise SystemExit(1)
    return candidate


def session_tag_from_name(session: str) -> str:
    """Strip the ``pm-`` prefix from a session name to get its tag."""
    return session.removeprefix("pm-")
