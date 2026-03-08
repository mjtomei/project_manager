"""Tutorial commands for the pm CLI.

Registers the ``tutorial`` command that launches guided interactive tutorials
for tmux, TUI navigation, and git fundamentals.
"""

import os
import subprocess
import shutil

import click

from pm_core import tutorial as tutorial_mod
from pm_core.claude_launcher import find_claude, build_claude_shell_cmd

from pm_core.cli import cli


def _check_prereqs():
    """Check that required tools are available."""
    if not shutil.which("tmux"):
        click.echo("tmux is required for tutorials. Install it first.", err=True)
        raise SystemExit(1)
    if not find_claude():
        click.echo("Claude CLI is required for tutorials. Install it first.", err=True)
        raise SystemExit(1)


def _setup_tutorial_session(session_name: str, socket_path: str,
                            cwd: str | None = None) -> list[str]:
    """Create a tutorial tmux session with two horizontal panes.

    Kills any existing session with the same name, creates a new one,
    splits horizontally, and returns the list of pane IDs (left, right).
    """
    # Kill existing session
    subprocess.run(
        ["tmux", "-S", socket_path, "kill-session", "-t", session_name],
        capture_output=True,
    )

    # Create session
    cmd = ["tmux", "-S", socket_path, "new-session", "-d", "-s", session_name,
           "-n", "tutorial", "-x", "200", "-y", "50"]
    if cwd:
        cmd.extend(["-c", cwd])
    subprocess.run(cmd, check=True)

    # Split: left pane + right pane
    split_cmd = ["tmux", "-S", socket_path, "split-window", "-h", "-t",
                 f"{session_name}:tutorial"]
    if cwd:
        split_cmd.extend(["-c", cwd])
    subprocess.run(split_cmd, check=True)

    # Get pane IDs
    result = subprocess.run(
        ["tmux", "-S", socket_path, "list-panes", "-t",
         f"{session_name}:tutorial", "-F", "#{pane_id}"],
        capture_output=True, text=True,
    )
    return result.stdout.strip().splitlines()


def _send_keys(socket_path: str, pane_id: str, keys: str):
    """Send keys followed by Enter to a pane on the given socket."""
    subprocess.run(
        ["tmux", "-S", socket_path, "send-keys", "-t", pane_id, keys, "Enter"],
        check=True,
    )


def _attach_session(socket_path: str, session_name: str, *, replace_process: bool = True):
    """Attach to a tutorial tmux session.

    When *replace_process* is True (default), replaces the current process via
    ``execvp`` — suitable when this is the last action.  When False, uses
    ``subprocess.call`` so that control returns after the user detaches.
    """
    if replace_process:
        os.execvp("tmux", ["tmux", "-S", socket_path, "attach-session",
                            "-t", session_name])
    else:
        subprocess.call(["tmux", "-S", socket_path, "attach-session",
                         "-t", session_name])


def _print_progress():
    """Print current tutorial progress."""
    summary = tutorial_mod.get_completion_summary()
    click.echo("\nTutorial Progress")
    click.echo("=" * 40)
    icons = {"tmux": "Terminal", "tui": "Dashboard", "git": "Version Control"}
    for mod in tutorial_mod.MODULES:
        done, total = summary[mod]
        bar = "█" * done + "░" * (total - done)
        label = icons.get(mod, mod)
        status = " (complete)" if done == total else ""
        click.echo(f"  {label:20s} {bar} {done}/{total}{status}")
    click.echo()


@cli.command("tutorial")
@click.option("--module", "-m", type=click.Choice(["tmux", "tui", "git"]),
              default=None, help="Run a specific module")
@click.option("--reset", is_flag=True, default=False,
              help="Reset progress for the specified module (or all)")
@click.option("--status", is_flag=True, default=False,
              help="Show progress without launching")
def tutorial(module, reset, status):
    """Interactive guided tutorial for pm, tmux, and git.

    Launches a step-by-step tutorial with Claude as your guide.
    Three modules are available:

    \b
      tmux  — Learn tmux basics: panes, windows, scrolling
      tui   — Navigate the pm tech tree and dashboard
      git   — Git fundamentals with hands-on exercises

    Run all modules in sequence (default) or pick one with --module.

    \b
    Examples:
      pm tutorial                  # Run all modules
      pm tutorial -m tmux          # Just the tmux module
      pm tutorial --status         # Show progress
      pm tutorial --reset          # Reset all progress
      pm tutorial --reset -m git   # Reset just git module
    """
    if reset:
        tutorial_mod.reset_progress(module)
        if module:
            click.echo(f"Reset progress for {module} module.")
        else:
            click.echo("Reset all tutorial progress.")
        return

    if status:
        _print_progress()
        return

    _check_prereqs()

    if module:
        _run_module(module, replace_process=True)
    else:
        # Run all modules in sequence.  Use subprocess.call for attach so
        # that control returns here after each module (os.execvp would
        # replace the process and prevent advancing to the next module).
        remaining = [m for m in tutorial_mod.MODULES
                     if not tutorial_mod.is_module_complete(m)]
        for mod in remaining:
            _run_module(mod, replace_process=False)
            if not tutorial_mod.is_module_complete(mod):
                # User quit before completing — don't auto-advance
                break
        _print_progress()
        click.echo("Run 'pm tutorial --status' to check your progress anytime.")


def _run_module(module: str, *, replace_process: bool = True):
    """Launch a specific tutorial module."""
    dispatch = {
        "tmux": _run_tmux_module,
        "tui": _run_tui_module,
        "git": _run_git_module,
    }
    runner = dispatch.get(module)
    if runner:
        runner(replace_process=replace_process)


def _run_tmux_module(*, replace_process: bool = True):
    """Run the tmux basics tutorial module."""
    click.echo("Setting up tmux tutorial...")

    if tutorial_mod.is_module_complete("tmux"):
        click.echo("Tmux module already complete! Use --reset -m tmux to restart.")
        return

    # setup_tmux_session creates session, splits, sets hooks, returns socket_path
    socket_path = tutorial_mod.setup_tmux_session()
    session_name = "pm-tutorial-tmux"

    # Get pane IDs from the already-created session
    result = subprocess.run(
        ["tmux", "-S", socket_path, "list-panes", "-t",
         f"{session_name}:tutorial", "-F", "#{pane_id}"],
        capture_output=True, text=True,
    )
    panes = result.stdout.strip().splitlines()

    # Launch Claude in the left pane
    prompt = tutorial_mod.build_tmux_claude_prompt()
    claude_cmd = build_claude_shell_cmd(prompt=prompt)
    if len(panes) >= 1:
        _send_keys(socket_path, panes[0], claude_cmd)

    # Welcome message in the right pane
    if len(panes) >= 2:
        welcome = (
            "echo '=== tmux Tutorial Playground ==='; "
            "echo ''; "
            "echo 'This is your practice pane.'; "
            "echo 'Follow the instructions in the Claude pane (left).'; "
            "echo ''; "
            "echo 'Mouse mode is ON — you can click to switch panes.'; "
            "echo ''"
        )
        _send_keys(socket_path, panes[1], welcome)

    click.echo("Attaching to tmux tutorial session...")
    click.echo("(Detach with Ctrl+b then d to exit)")
    click.echo()

    _attach_session(socket_path, session_name, replace_process=replace_process)


def _run_tui_module(*, replace_process: bool = True):
    """Run the TUI navigation tutorial module."""
    click.echo("Setting up TUI tutorial...")

    if tutorial_mod.is_module_complete("tui"):
        click.echo("TUI module already complete! Use --reset -m tui to restart.")
        return

    project_dir = tutorial_mod.setup_tui_project()

    session_name = "pm-tutorial-tui"
    socket_path = str(tutorial_mod.TUTORIAL_DIR / "tutorial-tui.sock")

    panes = _setup_tutorial_session(session_name, socket_path, cwd=str(project_dir))

    # Launch Claude in left pane
    prompt = tutorial_mod.build_tui_claude_prompt(project_dir)
    claude_cmd = build_claude_shell_cmd(prompt=prompt)
    if len(panes) >= 1:
        _send_keys(socket_path, panes[0], claude_cmd)

    # Launch TUI in right pane
    if len(panes) >= 2:
        tui_cmd = f"PM_PROJECT='{project_dir}' pm _tui"
        _send_keys(socket_path, panes[1], tui_cmd)

    click.echo("TUI tutorial session ready.")
    click.echo("Attaching... (Detach with Ctrl+b then d)")
    click.echo()

    _attach_session(socket_path, session_name, replace_process=replace_process)


def _run_git_module(*, replace_process: bool = True):
    """Run the git fundamentals tutorial module."""
    click.echo("Setting up git tutorial...")

    if tutorial_mod.is_module_complete("git"):
        click.echo("Git module already complete! Use --reset -m git to restart.")
        return

    repo_dir = tutorial_mod.setup_git_practice_repo()

    session_name = "pm-tutorial-git"
    socket_path = str(tutorial_mod.TUTORIAL_DIR / "tutorial-git.sock")

    panes = _setup_tutorial_session(session_name, socket_path, cwd=str(repo_dir))

    # Launch Claude in left pane
    prompt = tutorial_mod.build_git_claude_prompt(repo_dir)
    claude_cmd = build_claude_shell_cmd(prompt=prompt)
    if len(panes) >= 1:
        _send_keys(socket_path, panes[0], claude_cmd)

    # Welcome message in right pane
    if len(panes) >= 2:
        welcome = (
            f"cd '{repo_dir}' && "
            "echo '=== Git Tutorial Practice Repo ==='; "
            "echo ''; "
            "echo 'Run git commands here.'; "
            "echo 'Follow instructions from Claude (left pane).'; "
            "echo ''; "
            "git log --oneline; "
            "echo ''"
        )
        _send_keys(socket_path, panes[1], welcome)

    click.echo("Git tutorial session ready.")
    click.echo("Attaching... (Detach with Ctrl+b then d)")
    click.echo()

    _attach_session(socket_path, session_name, replace_process=replace_process)
