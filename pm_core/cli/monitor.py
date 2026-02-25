"""Monitor CLI command.

Launches the autonomous monitor window in tmux with a Claude session
configured for project health monitoring.
"""

import click

from pm_core import store, prompt_gen
from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import build_claude_shell_cmd
from pm_core.monitor_loop import MONITOR_WINDOW_NAME

from pm_core.cli import cli
from pm_core.cli.helpers import _get_pm_session, state_root


@cli.command("monitor", hidden=True)
@click.option("--iteration", default=0, type=int, help="Monitor loop iteration number")
@click.option("--loop-id", default="", help="Unique monitor loop identifier")
@click.option("--transcript", default=None, hidden=True,
              help="Path to save Claude transcript symlink")
def monitor_cmd(iteration: int, loop_id: str, transcript: str | None):
    """Launch an autonomous monitor session in a tmux window.

    This command is called by the monitor loop engine to create (or
    recreate) the monitor tmux window for each iteration.  It is not
    intended to be called by users directly.
    """
    root = state_root()
    data = store.load(root)

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Monitor window requires tmux.", err=True)
        raise SystemExit(1)

    pm_session = _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        click.echo(f"Monitor: tmux session '{pm_session}' not found.", err=True)
        raise SystemExit(1)

    # Generate monitor prompt
    monitor_prompt = prompt_gen.generate_monitor_prompt(
        data, session_name=pm_session,
        iteration=iteration, loop_id=loop_id,
    )

    # Determine a working directory -- use the repo root (parent of pm/ dir)
    repo_dir = str(root.parent) if store.is_internal_pm_dir(root) else str(root)

    claude_cmd = build_claude_shell_cmd(
        prompt=monitor_prompt,
        transcript=transcript,
        cwd=repo_dir,
    )

    # Kill existing monitor window and recreate (fresh each iteration)
    existing = tmux_mod.find_window_by_name(pm_session, MONITOR_WINDOW_NAME)
    if existing:
        tmux_mod.kill_window(pm_session, existing["id"])

    # Create the monitor window without switching focus (background)
    try:
        tmux_mod.new_window_get_pane(
            pm_session, MONITOR_WINDOW_NAME, claude_cmd, repo_dir,
            switch=False,
        )
        click.echo(f"Monitor window launched (iteration {iteration})")
    except Exception as e:
        click.echo(f"Monitor: failed to create tmux window: {e}", err=True)
        raise SystemExit(1)
