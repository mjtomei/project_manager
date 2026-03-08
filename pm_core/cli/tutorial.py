"""Tutorial commands for the pm CLI.

Registers the ``tutorial`` command that launches guided interactive tutorials
for tmux, TUI navigation, and git fundamentals.
"""

import os
import subprocess
import shutil

import click

from pm_core import tmux as tmux_mod
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
        _run_module(module)
    else:
        # Run all modules in sequence
        for mod in tutorial_mod.MODULES:
            if not tutorial_mod.is_module_complete(mod):
                _run_module(mod)
                if not tutorial_mod.is_module_complete(mod):
                    # User quit before completing — don't auto-advance
                    break
        _print_progress()
        click.echo("Run 'pm tutorial --status' to check your progress anytime.")


def _run_module(module: str):
    """Launch a specific tutorial module."""
    dispatch = {
        "tmux": _run_tmux_module,
        "tui": _run_tui_module,
        "git": _run_git_module,
    }
    runner = dispatch.get(module)
    if runner:
        runner()


def _run_tmux_module():
    """Run the tmux basics tutorial module."""
    click.echo("Setting up tmux tutorial...")

    # Initialize progress for this module if needed
    step = tutorial_mod.get_current_step("tmux")
    if step is None:
        # Already complete
        click.echo("Tmux module already complete! Use --reset -m tmux to restart.")
        return

    # Set up the tutorial tmux session
    socket_path = tutorial_mod.setup_tmux_session()
    session_name = "pm-tutorial-tmux"

    # Build Claude prompt and launch in the left pane
    prompt = tutorial_mod.build_tmux_claude_prompt()
    claude_cmd = build_claude_shell_cmd(prompt=prompt)

    # Get the first pane (left side) and send Claude to it
    result = subprocess.run(
        ["tmux", "-S", socket_path, "list-panes", "-t",
         f"{session_name}:tutorial", "-F", "#{pane_id}"],
        capture_output=True, text=True,
    )
    panes = result.stdout.strip().splitlines()
    if len(panes) >= 1:
        # Send Claude command to the first (left) pane
        subprocess.run(
            ["tmux", "-S", socket_path, "send-keys", "-t", panes[0],
             claude_cmd, "Enter"],
            check=True,
        )

    # Put a welcome message in the right pane
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
        subprocess.run(
            ["tmux", "-S", socket_path, "send-keys", "-t", panes[1],
             welcome, "Enter"],
            check=True,
        )

    click.echo(f"Tutorial session ready on socket: {socket_path}")
    click.echo("Attaching to tmux tutorial session...")
    click.echo("(Detach with Ctrl+b then d to exit)")
    click.echo()

    # Attach to the session
    os.execvp("tmux", ["tmux", "-S", socket_path, "attach-session",
                        "-t", session_name])


def _run_tui_module():
    """Run the TUI navigation tutorial module."""
    click.echo("Setting up TUI tutorial...")

    step = tutorial_mod.get_current_step("tui")
    if step is None:
        click.echo("TUI module already complete! Use --reset -m tui to restart.")
        return

    # Create example project
    project_dir = tutorial_mod.setup_tui_project()

    # Create a tmux session with Claude guidance pane + TUI pane
    session_name = "pm-tutorial-tui"
    socket_path = str(tutorial_mod.TUTORIAL_DIR / "tutorial-tui.sock")

    # Kill existing session
    subprocess.run(
        ["tmux", "-S", socket_path, "kill-session", "-t", session_name],
        capture_output=True,
    )

    # Create session — left pane will be Claude
    subprocess.run(
        ["tmux", "-S", socket_path, "new-session", "-d", "-s", session_name,
         "-n", "tutorial", "-x", "200", "-y", "50"],
        check=True,
    )

    # Split: left = Claude, right = TUI + shell
    subprocess.run(
        ["tmux", "-S", socket_path, "split-window", "-h", "-t",
         f"{session_name}:tutorial", "-c", str(project_dir)],
        check=True,
    )

    # Get pane IDs
    result = subprocess.run(
        ["tmux", "-S", socket_path, "list-panes", "-t",
         f"{session_name}:tutorial", "-F", "#{pane_id}"],
        capture_output=True, text=True,
    )
    panes = result.stdout.strip().splitlines()

    # Launch Claude in left pane
    prompt = tutorial_mod.build_tui_claude_prompt(project_dir)
    claude_cmd = build_claude_shell_cmd(prompt=prompt)
    if len(panes) >= 1:
        subprocess.run(
            ["tmux", "-S", socket_path, "send-keys", "-t", panes[0],
             claude_cmd, "Enter"],
            check=True,
        )

    # Launch TUI in right pane (pointing at tutorial project)
    if len(panes) >= 2:
        tui_cmd = f"PM_PROJECT='{project_dir}' pm _tui"
        subprocess.run(
            ["tmux", "-S", socket_path, "send-keys", "-t", panes[1],
             tui_cmd, "Enter"],
            check=True,
        )

    click.echo("TUI tutorial session ready.")
    click.echo("Attaching... (Detach with Ctrl+b then d)")
    click.echo()

    os.execvp("tmux", ["tmux", "-S", socket_path, "attach-session",
                        "-t", session_name])


def _run_git_module():
    """Run the git fundamentals tutorial module."""
    click.echo("Setting up git tutorial...")

    step = tutorial_mod.get_current_step("git")
    if step is None:
        click.echo("Git module already complete! Use --reset -m git to restart.")
        return

    # Create practice repo
    repo_dir = tutorial_mod.setup_git_practice_repo()

    # Create tmux session
    session_name = "pm-tutorial-git"
    socket_path = str(tutorial_mod.TUTORIAL_DIR / "tutorial-git.sock")

    # Kill existing session
    subprocess.run(
        ["tmux", "-S", socket_path, "kill-session", "-t", session_name],
        capture_output=True,
    )

    # Create session
    subprocess.run(
        ["tmux", "-S", socket_path, "new-session", "-d", "-s", session_name,
         "-n", "tutorial", "-x", "200", "-y", "50", "-c", str(repo_dir)],
        check=True,
    )

    # Split: left = Claude guidance, right = command line
    subprocess.run(
        ["tmux", "-S", socket_path, "split-window", "-h", "-t",
         f"{session_name}:tutorial", "-c", str(repo_dir)],
        check=True,
    )

    # Get pane IDs
    result = subprocess.run(
        ["tmux", "-S", socket_path, "list-panes", "-t",
         f"{session_name}:tutorial", "-F", "#{pane_id}"],
        capture_output=True, text=True,
    )
    panes = result.stdout.strip().splitlines()

    # Launch Claude in left pane
    prompt = tutorial_mod.build_git_claude_prompt(repo_dir)
    claude_cmd = build_claude_shell_cmd(prompt=prompt)
    if len(panes) >= 1:
        subprocess.run(
            ["tmux", "-S", socket_path, "send-keys", "-t", panes[0],
             claude_cmd, "Enter"],
            check=True,
        )

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
        subprocess.run(
            ["tmux", "-S", socket_path, "send-keys", "-t", panes[1],
             welcome, "Enter"],
            check=True,
        )

    click.echo("Git tutorial session ready.")
    click.echo("Attaching... (Detach with Ctrl+b then d)")
    click.echo()

    os.execvp("tmux", ["tmux", "-S", socket_path, "attach-session",
                        "-t", session_name])
