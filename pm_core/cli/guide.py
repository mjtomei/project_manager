"""Guide commands for the pm CLI.

Registers the ``guide`` command and the ``notes`` command.
"""

from pathlib import Path

import click

from pm_core import store, notes
from pm_core import guide as guide_mod
from pm_core.claude_launcher import find_claude, launch_claude
from pm_core.cli._window_launch import launch_claude_in_window

from pm_core.cli import cli
from pm_core.cli.helpers import (
    _get_pm_session,
    state_root,
    trigger_tui_refresh,
)


@cli.command("guide")
@click.option("--fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
def guide(fresh):
    """Guided workflow — launches setup or assist depending on project state."""
    _run_guide(fresh=fresh)


def _run_guide(fresh=False):
    # Detect state
    try:
        root = state_root()
    except (FileNotFoundError, SystemExit):
        root = None

    state, ctx = guide_mod.detect_state(root)
    root = ctx.get("root", root)

    # Loop: run non-interactive steps, re-detect
    while True:
        if state == "no_project" and root is None:
            # Need init — this is interactive, break to setup prompt
            break

        if state == "has_plan_prs":
            click.echo("Loading PRs from plan file...")
            guide_mod.run_non_interactive_step(state, ctx, root)
            state, ctx = guide_mod.detect_state(root)
            root = ctx.get("root", root)
            continue

        break

    # Determine session name for TUI targeting
    pm_session = _get_pm_session()

    # If PRs exist: assist prompt
    data = ctx.get("data", {})
    prs = data.get("prs") or []

    if prs:
        # Assist mode — PRs exist
        prompt = guide_mod.build_assist_prompt(data, root, session_name=pm_session)

        claude = find_claude()
        if not claude:
            click.echo("\nClaude CLI not found. Copy-paste this prompt into Claude Code:\n")
            click.echo(f"---\n{prompt}\n---")
            return

        if root is None:
            # No project yet — can't persist session. Launch inline.
            launch_claude(prompt)
            return
        launch_claude_in_window(
            "guide", prompt, cwd=str(root),
            session_key="guide:assist", pm_root=root, fresh=fresh,
        )
    else:
        # Setup mode — no PRs yet
        prompt = guide_mod.build_setup_prompt(state, ctx, root, session_name=pm_session)

        claude = find_claude()
        if not claude:
            click.echo("\nClaude CLI not found. Copy-paste this prompt into Claude Code:\n")
            click.echo(f"---\n{prompt}\n---")
            return

        if root is None:
            # No project yet — can't persist session. Launch inline.
            launch_claude(prompt)
            return
        launch_claude_in_window(
            "guide", prompt, cwd=str(root),
            session_key="guide:setup", pm_root=root, fresh=fresh,
        )


@cli.command("notes")
@click.argument("notes_file", default=None, required=False)
@click.option("--disable-splash", is_flag=True, help="Disable the splash screen for this repo.")
def notes_cmd(notes_file: str | None, disable_splash: bool):
    """Open the session notes editor.

    Notes are organized into sections that target different prompts.
    All sections are shown in a single editable view; on save, content
    is routed to the appropriate backing files.  Changes are persisted
    each time you save — you don't need to close the editor.

    Shows a welcome splash screen before opening the editor.
    Use --disable-splash to permanently disable it for this repo.
    """
    from pm_core.editor import run_watched_editor

    # Determine the pm root directory
    if notes_file is not None:
        pm_dir = Path(notes_file).parent
    else:
        try:
            pm_dir = state_root()
        except (FileNotFoundError, SystemExit):
            pm_dir = Path.cwd() / "pm"

    no_splash_marker = pm_dir / ".no-notes-splash"

    if disable_splash:
        no_splash_marker.touch()
        click.echo("Splash screen disabled for this repo.")
        return

    # Ensure files exist and gitignore is correct
    pm_dir.mkdir(parents=True, exist_ok=True)
    notes.ensure_notes_file(pm_dir)

    template = notes.build_edit_template(pm_dir)

    def on_save(content: str) -> None:
        sections = notes.parse_edit_template(content)
        notes.save_sections(pm_dir, sections)

    # Show splash if not disabled
    if not no_splash_marker.exists():
        import sys
        sys.stdout.write("\033[2J\033[H")  # clear + home
        sys.stdout.write(notes.NOTES_WELCOME)
        sys.stdout.flush()

        # Wait for a single keypress (raw mode)
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    ret, _ = run_watched_editor(template, on_save)
    if ret != 0:
        click.echo(f"Editor exited with code {ret}.", err=True)
