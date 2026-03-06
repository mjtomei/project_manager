"""Watcher CLI command.

Launches the autonomous watcher in one of two modes:

- **User mode** (``pm watcher``): runs a full blocking watcher loop that
  prints iteration verdicts to the terminal.
- **Internal mode** (``pm watcher --iteration N``): creates a single tmux
  window for the given iteration (called by the watcher loop engine).
"""

import secrets
from datetime import datetime

import click

from pm_core import store, prompt_gen
from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import build_claude_shell_cmd, finalize_transcript
from pm_core.watcher_loop import (
    WATCHER_WINDOW_NAME,
    WatcherLoopState,
    run_watcher_loop_sync,
)

from pm_core.paths import configure_logger
from pm_core.cli import cli
from pm_core.cli.helpers import _get_pm_session, state_root

_log = configure_logger("pm.cli.watcher")


def _run_user_watcher_loop(wait: int, max_iterations: int) -> None:
    """Run the watcher loop directly from the CLI (blocking)."""
    root = state_root()

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Watcher requires tmux.", err=True)
        raise SystemExit(1)

    pm_session = _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        click.echo(f"Watcher: tmux session '{pm_session}' not found.", err=True)
        raise SystemExit(1)

    state = WatcherLoopState(iteration_wait=wait)

    # Create transcript directory
    tdir = root / "transcripts" / f"watcher-{secrets.token_hex(4)}"
    tdir.mkdir(parents=True, exist_ok=True)

    def _on_iteration(s: WatcherLoopState) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        click.echo(f"[{ts}] Iteration {s.iteration}: {s.latest_verdict}")

    click.echo(f"Starting watcher loop (wait={wait}s, max={max_iterations or 'unlimited'}) ...")
    click.echo(f"Transcripts: {tdir}")
    click.echo("Press Ctrl+C to stop.\n")

    try:
        run_watcher_loop_sync(
            state,
            str(root),
            on_iteration=_on_iteration,
            max_iterations=max_iterations,
            transcript_dir=str(tdir),
        )
    except KeyboardInterrupt:
        state.stop_requested = True
        click.echo("\nStopping watcher loop...")

    # Finalize transcript symlinks
    from pathlib import Path
    for p in Path(tdir).iterdir():
        if p.is_symlink() and p.suffix == ".jsonl":
            finalize_transcript(p)

    click.echo(
        f"\nWatcher finished: {state.iteration} iteration(s), "
        f"last verdict: {state.latest_verdict}"
    )


@cli.command("watcher")
@click.option("--iteration", default=None, type=int, help="Watcher loop iteration number (internal)")
@click.option("--loop-id", default=None, help="Unique watcher loop identifier (internal)")
@click.option("--transcript", default=None, hidden=True,
              help="Path to save Claude transcript symlink")
@click.option("--wait", default=120, type=int, help="Seconds between iterations")
@click.option("--max-iterations", default=0, type=int,
              help="Maximum iterations (0 = unlimited)")
@click.option("--auto-start-target", default=None, hidden=True,
              help="Auto-start target PR ID (passed by watcher loop engine)")
@click.option("--meta-pm-root", default=None, hidden=True,
              help="Absolute path to meta workdir pm/ dir (passed by watcher loop engine)")
def watcher_cmd(iteration: int | None, loop_id: str | None,
                transcript: str | None, wait: int, max_iterations: int,
                auto_start_target: str | None, meta_pm_root: str | None):
    """Run the autonomous watcher loop.

    With no arguments, starts a blocking watcher loop that periodically
    checks project health and prints verdicts to the terminal.

    \b
    Options:
      --wait             Seconds between iterations (default: 120)
      --max-iterations   Stop after N iterations (default: unlimited)

    \b
    Examples:
      pm watcher                          # run with defaults
      pm watcher --wait 60                # check every 60 seconds
      pm watcher --wait 60 --max-iterations 5
    """
    if iteration is not None:
        # Internal mode: create a single tmux window for this iteration
        _create_watcher_window(iteration, loop_id or "", transcript,
                               auto_start_target=auto_start_target,
                               meta_pm_root=meta_pm_root)
    else:
        # User mode: run the full blocking loop
        _run_user_watcher_loop(wait, max_iterations)


def _create_watcher_window(iteration: int, loop_id: str,
                           transcript: str | None,
                           auto_start_target: str | None = None,
                           meta_pm_root: str | None = None) -> None:
    """Create (or recreate) the watcher tmux window for one iteration."""
    root = state_root()
    data = store.load(root)

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Watcher window requires tmux.", err=True)
        raise SystemExit(1)

    pm_session = _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        click.echo(f"Watcher: tmux session '{pm_session}' not found.", err=True)
        raise SystemExit(1)

    # Generate watcher prompt
    watcher_prompt = prompt_gen.generate_watcher_prompt(
        data, session_name=pm_session,
        iteration=iteration, loop_id=loop_id,
        auto_start_target=auto_start_target,
        meta_pm_root=meta_pm_root,
    )

    # Determine a working directory -- use the repo root (parent of pm/ dir)
    repo_dir = str(root.parent) if store.is_internal_pm_dir(root) else str(root)

    claude_cmd = build_claude_shell_cmd(
        prompt=watcher_prompt,
        transcript=transcript,
        cwd=repo_dir,
    )

    # Kill existing watcher window and recreate (fresh each iteration).
    # Track which sessions were watching the old window so we can switch
    # them to the new one (same pattern as review windows).
    sessions_watching: list[str] = []
    existing = tmux_mod.find_window_by_name(pm_session, WATCHER_WINDOW_NAME)
    _log.info("_create_watcher_window: iteration=%d pm_session=%s existing=%s",
               iteration, pm_session, existing)
    if existing:
        sessions_watching = tmux_mod.sessions_on_window(
            pm_session, existing["id"])
        _log.info("_create_watcher_window: sessions_watching=%s, killing old window %s",
                    sessions_watching, existing["id"])
        tmux_mod.kill_window(pm_session, existing["id"])

    # Create the watcher window without switching focus (background)
    try:
        tmux_mod.new_window_get_pane(
            pm_session, WATCHER_WINDOW_NAME, claude_cmd, repo_dir,
            switch=False,
        )
        new_win = tmux_mod.find_window_by_name(pm_session, WATCHER_WINDOW_NAME)
        _log.info("_create_watcher_window: new window created: %s", new_win)
        if new_win:
            tmux_mod.set_shared_window_size(pm_session, new_win["id"])
        click.echo(f"Watcher window launched (iteration {iteration})")
    except Exception as e:
        click.echo(f"Watcher: failed to create tmux window: {e}", err=True)
        raise SystemExit(1)

    # Switch sessions that were watching the old watcher window to the new one
    if sessions_watching:
        _log.info("_create_watcher_window: switching %s to new watcher window", sessions_watching)
        tmux_mod.switch_sessions_to_window(
            sessions_watching, pm_session, WATCHER_WINDOW_NAME)
    else:
        _log.info("_create_watcher_window: no sessions_watching, skipping switch")
