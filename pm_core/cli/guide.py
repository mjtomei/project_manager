"""Guide commands for the pm CLI.

Registers the ``guide`` command and the ``notes`` command.
"""

import os
from pathlib import Path

import click

from pm_core import store, notes
from pm_core import tmux as tmux_mod
from pm_core import guide as guide_mod
from pm_core.claude_launcher import (
    find_claude, find_editor, launch_claude, load_session, save_session,
    clear_session, build_claude_shell_cmd,
)

from pm_core.cli import cli
from pm_core.cli.helpers import (
    _get_pm_session,
    state_root,
    trigger_tui_refresh,
)


def _in_pm_tmux_session() -> bool:
    """Check if we're in a tmux session created by pm (named pm-*)."""
    if not tmux_mod.in_tmux():
        return False
    session_name = tmux_mod.get_session_name()
    return session_name.startswith("pm-")


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

        if _in_pm_tmux_session():
            cmd = build_claude_shell_cmd(prompt=prompt)
            os.execvp("bash", ["bash", "-c", cmd])
        else:
            launch_claude(prompt)
    else:
        # Setup mode — no PRs yet
        prompt = guide_mod.build_setup_prompt(state, ctx, root, session_name=pm_session)

        claude = find_claude()
        if not claude:
            click.echo("\nClaude CLI not found. Copy-paste this prompt into Claude Code:\n")
            click.echo(f"---\n{prompt}\n---")
            return

        session_key = "guide:setup"

        if fresh and root:
            clear_session(root, session_key)

        if _in_pm_tmux_session():
            import uuid as uuid_mod

            # Get or create session ID for resume
            session_id = None
            is_resuming = False
            if root and not fresh:
                session_id = load_session(root, session_key)
                if session_id:
                    is_resuming = True

            save_cmd = ""
            if not session_id and root:
                session_id = str(uuid_mod.uuid4())
                save_cmd = f"pm _save-session '{session_key}' '{session_id}' '{root}' ; "

            claude_cmd = build_claude_shell_cmd(prompt=prompt, session_id=session_id, resume=is_resuming)

            # On failure (non-zero exit), clear the session so next launch starts fresh
            clear_cmd = f"pm _clear-session '{session_key}' '{root}'" if root else "true"
            cmd = f"{save_cmd}{claude_cmd} ; rc=$? ; if [ $rc -ne 0 ]; then {clear_cmd}; fi"

            os.execvp("bash", ["bash", "-c", cmd])
        else:
            launch_claude(prompt, session_key=session_key, pm_root=root, resume=not fresh)


@cli.command("notes")
@click.argument("notes_file", default=None, required=False)
@click.option("--disable-splash", is_flag=True, help="Disable the splash screen for this repo.")
def notes_cmd(notes_file: str | None, disable_splash: bool):
    """Open the session notes editor.

    Notes are organized into sections that target different prompts.
    All sections are shown in a single editable view; on save, content
    is routed to the appropriate backing files.

    Shows a welcome splash screen before opening the editor.
    Use --disable-splash to permanently disable it for this repo.
    """
    import subprocess
    import tempfile

    # Determine the pm root directory
    if notes_file is not None:
        pm_dir = Path(notes_file).parent
    else:
        try:
            pm_dir = state_root()
        except (FileNotFoundError, SystemExit):
            pm_dir = Path.cwd() / "pm"

    no_splash_marker = pm_dir / ".no-notes-splash"
    editor = find_editor()

    if disable_splash:
        no_splash_marker.touch()
        click.echo("Splash screen disabled for this repo.")
        return

    # Ensure files exist and gitignore is correct
    pm_dir.mkdir(parents=True, exist_ok=True)
    notes.ensure_notes_file(pm_dir)

    # Build composite template and write to temp file
    template = notes.build_edit_template(pm_dir)
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write(template)
        tmp_path = f.name

    try:
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

        # Open editor
        ret = subprocess.call([editor, tmp_path])
        if ret != 0:
            click.echo(f"Editor exited with code {ret}, changes not saved.", err=True)
            return

        # Parse edited template and save sections
        edited = Path(tmp_path).read_text()
        sections = notes.parse_edit_template(edited)
        notes.save_sections(pm_dir, sections)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
