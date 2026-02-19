"""Guide commands for the pm CLI.

Registers the ``guide`` group, ``_run_guide``, and the ``notes`` command.
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
    _find_tui_pane,
    state_root,
    trigger_tui_refresh,
)


def _in_pm_tmux_session() -> bool:
    """Check if we're in a tmux session created by pm (named pm-*)."""
    if not tmux_mod.in_tmux():
        return False
    session_name = tmux_mod.get_session_name()
    return session_name.startswith("pm-")


@cli.group(invoke_without_command=True)
@click.option("--step", default=None, help="Force a specific workflow step")
@click.option("--fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
@click.pass_context
def guide(ctx, step, fresh):
    """Guided workflow — walks through init -> plan -> PRs -> start."""
    if ctx.invoked_subcommand is not None:
        return
    _run_guide(step, fresh=fresh)


@guide.command("done", hidden=True)
def guide_done_cmd():
    """Mark the current guide step as completed."""
    try:
        root = state_root()
    except (FileNotFoundError, SystemExit):
        root = None

    if root is None:
        click.echo("No project found.", err=True)
        raise SystemExit(1)

    started = guide_mod.get_started_step(root)

    # Bug fix: If started is None but pm dir exists, we're completing step 1
    # This happens when the guide started with no pm dir (root was None),
    # then pm init created the directory, and now we're completing.
    if started is None:
        # Check if detection shows we've moved past no_project
        detected, _ = guide_mod.detect_state(root)
        if detected != "no_project":
            # We've progressed, so no_project must have been the started step
            started = "no_project"
            guide_mod.mark_step_started(root, started)
        else:
            click.echo("No guide step has been started yet.", err=True)
            raise SystemExit(1)

    completed = guide_mod.get_completed_step(root)
    started_idx = guide_mod.STEP_ORDER.index(started) if started in guide_mod.STEP_ORDER else 0
    completed_idx = guide_mod.STEP_ORDER.index(completed) if completed in guide_mod.STEP_ORDER else -1

    if completed_idx >= started_idx:
        click.echo("Already completed.")
        return

    # Special handling: needs_deps_review step has no artifact - it's done when user says so
    # Set the flag before detection check so detection can move forward
    if started == "needs_deps_review":
        guide_mod.set_deps_reviewed(root)

    # Bug fix: Verify that detection shows progress before marking complete
    # This prevents marking a step complete when artifacts weren't created
    detected, _ = guide_mod.detect_state(root)
    detected_idx = guide_mod.STEP_ORDER.index(detected) if detected in guide_mod.STEP_ORDER else 0

    if detected_idx <= started_idx:
        # Detection hasn't moved forward - step isn't actually complete
        click.echo(f"Step not complete: detection still shows '{guide_mod.STEP_DESCRIPTIONS.get(detected, detected)}'")
        click.echo("Complete the step's tasks before running 'pm guide done'.")
        raise SystemExit(1)

    state = started
    guide_mod.mark_step_completed(root, state)
    desc = guide_mod.STEP_DESCRIPTIONS.get(state, state)
    click.echo(f"Step completed: {desc}")

    # Trigger TUI refresh so it picks up the step change immediately
    _refresh_tui_if_running()


def _refresh_tui_if_running():
    """Send reload key to TUI pane if one is running."""
    import subprocess
    try:
        pane_id, _ = _find_tui_pane()
        if pane_id:
            subprocess.run(
                tmux_mod._tmux_cmd("send-keys", "-t", pane_id, "R"),
                capture_output=True,
                timeout=2,
            )
    except Exception:
        pass  # Best effort - don't fail if TUI isn't running


def _run_guide(step, fresh=False):
    # Detect state
    try:
        root = state_root()
    except (FileNotFoundError, SystemExit):
        root = None

    if step:
        state = step
        ctx = {}
        if root:
            try:
                data = store.load(root)
                ctx = {"data": data, "root": root}
            except Exception:
                pass
    else:
        state, ctx = guide_mod.resolve_guide_step(root)

    root = ctx.get("root", root)

    # Terminal states
    if state == "all_done":
        if root:
            guide_mod.mark_step_started(root, state)
        click.echo("All PRs are merged. Project complete!")
        return

    if state == "all_in_progress":
        if root:
            guide_mod.mark_step_started(root, state)
        click.echo("All PRs are in progress or waiting for review.")
        click.echo("Run 'pm pr list' to see status, or 'pm pr sync' to check for merges.")
        return

    # Non-interactive steps
    if state == "has_plan_prs":
        click.echo("Loading PRs from plan file...")
        # Bug fix: Track non-interactive steps like any other step
        if root:
            guide_mod.mark_step_started(root, state)
        guide_mod.run_non_interactive_step(state, ctx, root)
        if root:
            guide_mod.mark_step_completed(root, state)
        # Auto-chain
        if _in_pm_tmux_session():
            os.execvp("pm", ["pm", "guide"])
        else:
            click.echo("\nNext: run 'pm guide' to continue.")
        return

    # Interactive steps
    prompt = guide_mod.build_guide_prompt(state, ctx, root)
    if prompt is None:
        click.echo(f"Unknown state: {state}")
        return

    step_desc = guide_mod.STEP_DESCRIPTIONS.get(state, state)
    n = guide_mod.step_number(state)
    click.echo(f"Step {n}: {step_desc}")

    if root:
        guide_mod.mark_step_started(root, state)

    claude = find_claude()
    if not claude:
        click.echo("\nClaude CLI not found. Copy-paste this prompt into Claude Code:\n")
        click.echo(f"---\n{prompt}\n---")
        return

    # After deps review, mark as reviewed before chaining
    post_hook = None
    if state == "needs_deps_review" and root:
        post_hook = lambda: guide_mod.set_deps_reviewed(root)

    session_key = f"guide:{state}"

    if fresh and root:
        clear_session(root, session_key)

    if _in_pm_tmux_session():
        import uuid as uuid_mod

        # Get or create session ID
        session_id = None
        is_resuming = False
        if root and not fresh:
            session_id = load_session(root, session_key)
            if session_id:
                is_resuming = True

        # If no existing session, generate new UUID and save it
        save_cmd = ""
        if not session_id and root:
            session_id = str(uuid_mod.uuid4())
            save_cmd = f"pm _save-session '{session_key}' '{session_id}' '{root}' ; "

        claude_cmd = build_claude_shell_cmd(prompt=prompt, session_id=session_id, resume=is_resuming)

        if post_hook:
            # Set deps reviewed BEFORE pm guide done, so detection shows progress
            post_cmd = f"python3 -c \"from pm_core.guide import set_deps_reviewed; from pathlib import Path; set_deps_reviewed(Path('{root}'))\" ; pm guide done"
        else:
            post_cmd = "pm guide done"

        # Simple exit behavior: mark done on success, clear session on failure, then exit.
        # User notices the pane closed and manually restarts if needed.
        clear_cmd = f"pm _clear-session '{session_key}' '{root}'" if root else "true"
        cmd = f"{save_cmd}{claude_cmd} ; claude_rc=$? ; if [ $claude_rc -ne 0 ]; then {clear_cmd}; else {post_cmd}; fi"

        os.execvp("bash", ["bash", "-c", cmd])
    else:
        launch_claude(prompt, session_key=session_key, pm_root=root, resume=not fresh)
        if post_hook:
            post_hook()
        # Print next step
        next_state, _ = guide_mod.detect_state(root)
        next_desc = guide_mod.STEP_DESCRIPTIONS.get(next_state, next_state)
        click.echo(f"\nNext step: {next_desc}")
        click.echo("Run 'pm guide' to continue.")


@cli.command("notes")
@click.argument("notes_file", default=None, required=False)
@click.option("--disable-splash", is_flag=True, help="Disable the splash screen for this repo.")
def notes_cmd(notes_file: str | None, disable_splash: bool):
    """Open the session notes file in your editor.

    Shows a welcome splash screen before opening the editor.
    Use --disable-splash to permanently disable it for this repo.
    """
    if notes_file is None:
        try:
            root = state_root()
        except (FileNotFoundError, SystemExit):
            root = Path.cwd() / "pm"
        notes_file = str(root / notes.NOTES_FILENAME)
    path = Path(notes_file)
    pm_dir = path.parent
    no_splash_marker = pm_dir / ".no-notes-splash"
    editor = find_editor()

    if disable_splash:
        no_splash_marker.touch()
        click.echo("Splash screen disabled for this repo.")
        return

    # Ensure file exists
    if not path.exists():
        pm_dir.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    # Skip splash if disabled
    if no_splash_marker.exists():
        os.execvp(editor, [editor, notes_file])

    # Show the welcome content as a splash screen
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

    os.execvp(editor, [editor, notes_file])
