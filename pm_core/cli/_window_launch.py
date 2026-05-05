"""Find-or-create-window helper for CLI commands that launch Claude.

When a CLI command is invoked from inside a pm tmux session (e.g. from the
command popup or a regular pane shell), we want it to switch to or create a
dedicated tmux window for the Claude session rather than launching Claude
inline in the calling pane. The reference pattern lives in
``pm_core/cli/pr.py:pr_start`` (lines 822-846 + 1021-1075). This module
extracts that pattern so plan/cluster/guide/etc. commands share one
implementation.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import click

from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import (
    build_claude_shell_cmd,
    clear_session,
    launch_claude,
    load_session,
    save_session,
)
from pm_core.cli.helpers import _get_pm_session


def launch_claude_in_window(
    window_name: str,
    prompt: str,
    cwd: str,
    session_key: str,
    pm_root: Path,
    *,
    fresh: bool = False,
    resume: bool = True,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> None:
    """Find-or-create a per-window Claude launch with inline fallback.

    1. If in a pm tmux session and ``window_name`` already exists: switch
       to it (or kill it first when ``fresh=True``, then fall through to
       create a fresh one).
    2. If in a pm tmux session but the window is missing: create a new
       tmux window running the Claude command (built via
       ``build_claude_shell_cmd`` so flags/skip-permissions stay
       consistent).
    3. Otherwise: fall back to inline ``launch_claude`` in the calling
       terminal.
    """
    pm_session = _get_pm_session()

    if pm_session and tmux_mod.session_exists(pm_session):
        existing = tmux_mod.find_window_by_name(pm_session, window_name)
        if existing:
            if fresh:
                tmux_mod.kill_window(pm_session, existing["id"])
                click.echo(f"Killed existing window '{window_name}'")
            else:
                tmux_mod.select_window(pm_session, existing["id"])
                click.echo(
                    f"Switched to existing window '{window_name}' "
                    f"(session: {pm_session})"
                )
                return

        # Build a session_id we can resume next time.
        session_id: str | None = None
        is_resuming = False
        if resume and not fresh:
            session_id = load_session(pm_root, session_key)
            if session_id:
                is_resuming = True
        if not session_id:
            session_id = str(uuid.uuid4())
            save_session(pm_root, session_key, session_id)

        cmd = build_claude_shell_cmd(
            prompt=prompt,
            session_id=session_id,
            resume=is_resuming,
            cwd=cwd,
            model=model,
            provider=provider,
            effort=effort,
        )

        try:
            tmux_mod.new_window(pm_session, window_name, cmd, cwd)
            win = tmux_mod.find_window_by_name(pm_session, window_name)
            if win:
                tmux_mod.set_shared_window_size(pm_session, win["id"])
            click.echo(
                f"Launched Claude in tmux window '{window_name}' "
                f"(session: {pm_session})"
            )
            return
        except Exception as e:
            click.echo(f"Failed to create tmux window: {e}", err=True)
            click.echo("Launching Claude in current terminal...")

    # Fallback: launch inline in the current terminal.
    if fresh:
        clear_session(pm_root, session_key)
    launch_claude(
        prompt,
        cwd=cwd,
        session_key=session_key,
        pm_root=pm_root,
        resume=resume and not fresh,
        provider=provider,
        model=model,
        effort=effort,
    )
