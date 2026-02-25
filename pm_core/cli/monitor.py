"""Monitor CLI command.

Launches the autonomous monitor in one of two modes:

- **User mode** (``pm monitor``): runs a full blocking monitor loop that
  prints iteration verdicts to the terminal.
- **Internal mode** (``pm monitor --iteration N``): creates a single tmux
  window for the given iteration (called by the monitor loop engine).
"""

import secrets
from datetime import datetime

import click

from pm_core import store, prompt_gen
from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import build_claude_shell_cmd, finalize_transcript
from pm_core.monitor_loop import (
    MONITOR_WINDOW_NAME,
    MonitorLoopState,
    run_monitor_loop_sync,
)

from pm_core.cli import cli
from pm_core.cli.helpers import _get_pm_session, state_root


def _run_user_monitor_loop(wait: int, max_iterations: int) -> None:
    """Run the monitor loop directly from the CLI (blocking)."""
    root = state_root()

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Monitor requires tmux.", err=True)
        raise SystemExit(1)

    pm_session = _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        click.echo(f"Monitor: tmux session '{pm_session}' not found.", err=True)
        raise SystemExit(1)

    state = MonitorLoopState(iteration_wait=wait)

    # Create transcript directory
    tdir = root / "transcripts" / f"monitor-{secrets.token_hex(4)}"
    tdir.mkdir(parents=True, exist_ok=True)

    def _on_iteration(s: MonitorLoopState) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        click.echo(f"[{ts}] Iteration {s.iteration}: {s.latest_verdict}")

    click.echo(f"Starting monitor loop (wait={wait}s, max={max_iterations or 'unlimited'}) ...")
    click.echo(f"Transcripts: {tdir}")
    click.echo("Press Ctrl+C to stop.\n")

    try:
        run_monitor_loop_sync(
            state,
            str(root),
            on_iteration=_on_iteration,
            max_iterations=max_iterations,
            transcript_dir=str(tdir),
        )
    except KeyboardInterrupt:
        state.stop_requested = True
        click.echo("\nStopping monitor loop...")

    # Finalize transcript symlinks
    from pathlib import Path
    for p in Path(tdir).iterdir():
        if p.is_symlink() and p.suffix == ".jsonl":
            finalize_transcript(p)

    click.echo(
        f"\nMonitor finished: {state.iteration} iteration(s), "
        f"last verdict: {state.latest_verdict}"
    )


@cli.command("monitor")
@click.option("--iteration", default=None, type=int, help="Monitor loop iteration number (internal)")
@click.option("--loop-id", default=None, help="Unique monitor loop identifier (internal)")
@click.option("--transcript", default=None, hidden=True,
              help="Path to save Claude transcript symlink")
@click.option("--wait", default=120, type=int, help="Seconds between iterations")
@click.option("--max-iterations", default=0, type=int,
              help="Maximum iterations (0 = unlimited)")
@click.option("--auto-start-target", default=None, hidden=True,
              help="Auto-start target PR ID (passed by monitor loop engine)")
def monitor_cmd(iteration: int | None, loop_id: str | None,
                transcript: str | None, wait: int, max_iterations: int,
                auto_start_target: str | None):
    """Run the autonomous monitor loop.

    With no arguments, starts a blocking monitor loop that periodically
    checks project health and prints verdicts to the terminal.

    \b
    Options:
      --wait             Seconds between iterations (default: 120)
      --max-iterations   Stop after N iterations (default: unlimited)

    \b
    Examples:
      pm monitor                          # run with defaults
      pm monitor --wait 60                # check every 60 seconds
      pm monitor --wait 60 --max-iterations 5
    """
    if iteration is not None:
        # Internal mode: create a single tmux window for this iteration
        _create_monitor_window(iteration, loop_id or "", transcript,
                               auto_start_target=auto_start_target)
    else:
        # User mode: run the full blocking loop
        _run_user_monitor_loop(wait, max_iterations)


def _create_monitor_window(iteration: int, loop_id: str,
                           transcript: str | None,
                           auto_start_target: str | None = None) -> None:
    """Create (or recreate) the monitor tmux window for one iteration."""
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
        auto_start_target=auto_start_target,
    )

    # Determine a working directory -- use the repo root (parent of pm/ dir)
    repo_dir = str(root.parent) if store.is_internal_pm_dir(root) else str(root)

    claude_cmd = build_claude_shell_cmd(
        prompt=monitor_prompt,
        transcript=transcript,
        cwd=repo_dir,
    )

    # Kill existing monitor window and recreate (fresh each iteration).
    # Track which sessions were watching the old window so we can switch
    # them to the new one (same pattern as review windows).
    sessions_watching: list[str] = []
    existing = tmux_mod.find_window_by_name(pm_session, MONITOR_WINDOW_NAME)
    if existing:
        sessions_watching = tmux_mod.sessions_on_window(
            pm_session, existing["id"])
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

    # Switch sessions that were watching the old monitor window to the new one
    if sessions_watching:
        tmux_mod.switch_sessions_to_window(
            sessions_watching, pm_session, MONITOR_WINDOW_NAME)
