"""Watcher CLI commands.

Provides ``pm watcher`` as a command group with subcommands:

- ``pm watcher`` (bare) — runs a blocking watcher loop (legacy behavior)
- ``pm watcher start [TYPE]`` — start a watcher by type
- ``pm watcher stop [TYPE]`` — stop a running watcher
- ``pm watcher list`` — list all registered watcher types and status
- ``pm watcher supervisor start`` — launch supervisor watcher(s)
- ``pm watcher supervisor stop`` — stop supervisor watcher(s)
- ``pm watcher supervisor log`` — view supervisor feedback history

Internal mode (``pm watcher --iteration N``) creates a single tmux
window for the given iteration (called by the watcher loop engine).

Internal mode (``pm watcher supervisor-iter``) creates a single
supervisor tmux window for one iteration.
"""

import secrets
from datetime import datetime

import click

from pm_core import store, prompt_gen
from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import build_claude_shell_cmd, finalize_transcript
from pm_core.watchers.auto_start_watcher import AutoStartWatcher

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

    watcher = AutoStartWatcher(pm_root=str(root))
    watcher.state.iteration_wait = wait

    # Create transcript directory
    tdir = root / "transcripts" / f"watcher-{secrets.token_hex(4)}"
    tdir.mkdir(parents=True, exist_ok=True)

    def _on_iteration(s) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        click.echo(f"[{ts}] Iteration {s.iteration}: {s.latest_verdict}")

    click.echo(f"Starting watcher loop (wait={wait}s, max={max_iterations or 'unlimited'}) ...")
    click.echo(f"Transcripts: {tdir}")
    click.echo("Press Ctrl+C to stop.\n")

    try:
        watcher.run_sync(
            on_iteration=_on_iteration,
            max_iterations=max_iterations,
            transcript_dir=str(tdir),
        )
    except KeyboardInterrupt:
        watcher.state.stop_requested = True
        click.echo("\nStopping watcher loop...")

    # Finalize transcript symlinks
    from pathlib import Path
    for p in Path(tdir).iterdir():
        if p.is_symlink() and p.suffix == ".jsonl":
            finalize_transcript(p)

    click.echo(
        f"\nWatcher finished: {watcher.state.iteration} iteration(s), "
        f"last verdict: {watcher.state.latest_verdict}"
    )


@cli.group("watcher", invoke_without_command=True)
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
@click.pass_context
def watcher_cmd(ctx, iteration: int | None, loop_id: str | None,
                transcript: str | None, wait: int, max_iterations: int,
                auto_start_target: str | None, meta_pm_root: str | None):
    """Manage watchers.

    With no subcommand, starts a blocking watcher loop that periodically
    checks project health and prints verdicts to the terminal.

    \b
    Subcommands:
      start [TYPE]   Start a watcher (default: auto-start)
      stop [TYPE]    Stop a running watcher
      list           List watcher types and status

    \b
    Options (blocking mode):
      --wait             Seconds between iterations (default: 120)
      --max-iterations   Stop after N iterations (default: unlimited)

    \b
    Examples:
      pm watcher                          # run blocking loop
      pm watcher --wait 60                # check every 60 seconds
      pm watcher start                    # start auto-start watcher
      pm watcher list                     # list available types
    """
    if ctx.invoked_subcommand is not None:
        return

    if iteration is not None:
        # Internal mode: create a single tmux window for this iteration
        _create_watcher_window(iteration, loop_id or "", transcript,
                               auto_start_target=auto_start_target,
                               meta_pm_root=meta_pm_root)
    else:
        # User mode: run the full blocking loop
        _run_user_watcher_loop(wait, max_iterations)


@watcher_cmd.command("start")
@click.argument("watcher_type", default="auto-start")
@click.option("--wait", default=None, type=int,
              help="Seconds between iterations (overrides default)")
def watcher_start(watcher_type: str, wait: int | None):
    """Start a watcher by type.

    \b
    Available types:
      auto-start   Monitor auto-start sessions for issues (default)
    """
    from pm_core.watchers import get_watcher_class, list_watcher_types

    cls = get_watcher_class(watcher_type)
    if not cls:
        types = [t["type"] for t in list_watcher_types()]
        click.echo(f"Unknown watcher type: {watcher_type}", err=True)
        click.echo(f"Available types: {', '.join(types)}", err=True)
        raise SystemExit(1)

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Watcher requires tmux.", err=True)
        raise SystemExit(1)

    root = state_root()
    pm_root = str(root)

    watcher = cls(pm_root=pm_root)
    if wait is not None:
        watcher.state.iteration_wait = wait

    # Create transcript directory
    tdir = root / "transcripts" / f"{watcher_type}-{secrets.token_hex(4)}"
    tdir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Starting {watcher.DISPLAY_NAME} ...")
    click.echo(f"Transcripts: {tdir}")
    click.echo("Press Ctrl+C to stop.\n")

    def _on_iter(s):
        ts = datetime.now().strftime("%H:%M:%S")
        click.echo(f"[{ts}] Iteration {s.iteration}: {s.latest_verdict}")

    try:
        watcher.run_sync(
            on_iteration=_on_iter,
            transcript_dir=str(tdir),
        )
    except KeyboardInterrupt:
        watcher.state.stop_requested = True
        click.echo("\nStopping...")

    click.echo(
        f"\n{watcher.DISPLAY_NAME} finished: {watcher.state.iteration} iteration(s), "
        f"last verdict: {watcher.state.latest_verdict}"
    )


@watcher_cmd.command("stop")
@click.argument("watcher_type", default="auto-start")
def watcher_stop(watcher_type: str):
    """Stop a running watcher (for TUI-managed watchers, use the TUI)."""
    click.echo(
        f"To stop a watcher running in the TUI, press 'ws' in the TUI.\n"
        f"For CLI-started watchers, use Ctrl+C in the terminal."
    )


@watcher_cmd.command("list")
def watcher_list():
    """List all registered watcher types."""
    from pm_core.watchers import list_watcher_types

    types = list_watcher_types()
    if not types:
        click.echo("No watcher types registered.")
        return

    click.echo("Registered watcher types:\n")
    for t in types:
        click.echo(f"  {t['type']:<20} {t['display_name']}")
        click.echo(f"  {'':20} window: {t['window_name']}, "
                   f"interval: {t['default_interval']}s")
        click.echo()


# ---------------------------------------------------------------------------
# Supervisor subcommands
# ---------------------------------------------------------------------------

@watcher_cmd.group("supervisor", invoke_without_command=True)
@click.pass_context
def supervisor_cmd(ctx):
    """Manage supervisor watchers.

    Supervisor watchers run at high effort and monitor other running
    sessions, providing real-time coaching feedback.

    \b
    Subcommands:
      start   Launch supervisor watcher(s)
      stop    Stop running supervisors
      log     View supervisor feedback history
    """
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@supervisor_cmd.command("start")
@click.option("--target", default=None,
              help="Filter target sessions by window name substring")
@click.option("--count", default=1, type=int,
              help="Number of supervisor instances to launch")
@click.option("--wait", default=None, type=int,
              help="Seconds between iterations (overrides default)")
def supervisor_start(target: str | None, count: int, wait: int | None):
    """Launch supervisor watcher(s).

    \b
    Examples:
      pm watcher supervisor start                    # one supervisor, all targets
      pm watcher supervisor start --target pr-abc    # filter to specific PR
      pm watcher supervisor start --wait 120         # 2-minute iterations
    """
    from pm_core.watchers.supervisor_watcher import SupervisorWatcher

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Supervisor requires tmux.", err=True)
        raise SystemExit(1)

    # Running N > 1 supervisors requires launching multiple blocking run_sync()
    # loops concurrently (threads or subprocesses), which is not yet
    # implemented.  Each supervisor already gets a unique window name via
    # its watcher_id, so window conflicts are not the blocker.
    # TODO: launch N supervisor threads/processes to support --count > 1.
    if count > 1:
        click.echo(
            "Error: --count > 1 is not yet supported.  Launching multiple "
            "concurrent supervisors requires parallel execution (threads or "
            "subprocesses) which is not yet implemented.\n"
            "Run a single supervisor with a --target filter instead.",
            err=True,
        )
        raise SystemExit(1)

    root = state_root()
    pm_root = str(root)

    watcher = SupervisorWatcher(pm_root=pm_root, target_filter=target)
    if wait is not None:
        watcher.state.iteration_wait = wait

    tdir = root / "transcripts" / f"supervisor-{secrets.token_hex(4)}"
    tdir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Starting Supervisor (target={target or 'all'}) ...")
    click.echo(f"Transcripts: {tdir}")
    click.echo("Press Ctrl+C to stop.\n")

    def _on_iter(s):
        ts = datetime.now().strftime("%H:%M:%S")
        click.echo(f"[{ts}] Iteration {s.iteration}: {s.latest_verdict}")

    try:
        watcher.run_sync(
            on_iteration=_on_iter,
            transcript_dir=str(tdir),
        )
    except KeyboardInterrupt:
        watcher.state.stop_requested = True
        click.echo("\nStopping supervisor...")

    click.echo(
        f"\nSupervisor finished: {watcher.state.iteration} iteration(s), "
        f"last verdict: {watcher.state.latest_verdict}"
    )


@supervisor_cmd.command("stop")
def supervisor_stop():
    """Stop all running supervisor watchers."""
    click.echo(
        "To stop supervisors running in the TUI, press 'ws' in the TUI.\n"
        "For CLI-started supervisors, use Ctrl+C in the terminal."
    )


@supervisor_cmd.command("log")
@click.option("--target", default=None,
              help="Filter by target window name")
@click.option("--limit", default=50, type=int,
              help="Max entries to show")
def supervisor_log(target: str | None, limit: int):
    """View supervisor feedback history.

    \b
    Examples:
      pm watcher supervisor log                      # all feedback
      pm watcher supervisor log --target pr-abc      # filter by target
      pm watcher supervisor log --limit 10           # last 10 entries
    """
    from pm_core.supervisor_feedback import read_feedback_log, format_feedback_log

    entries = read_feedback_log(target_filter=target, limit=limit)
    click.echo(format_feedback_log(entries))


# ---------------------------------------------------------------------------
# Internal: supervisor-iter (creates tmux window for one supervisor iteration)
# ---------------------------------------------------------------------------

@watcher_cmd.command("supervisor-iter", hidden=True)
@click.option("--iteration", required=True, type=int)
@click.option("--loop-id", default="")
@click.option("--transcript", default=None)
@click.option("--target", default=None)
@click.option("--window-name", default=None,
              help="Tmux window name for this supervisor instance")
def supervisor_iter_cmd(iteration: int, loop_id: str,
                        transcript: str | None, target: str | None,
                        window_name: str | None):
    """Internal: create a supervisor tmux window for one iteration."""
    _create_supervisor_window(
        iteration, loop_id, transcript,
        target_filter=target, window_name=window_name,
    )


def _create_supervisor_window(iteration: int, loop_id: str,
                              transcript: str | None,
                              target_filter: str | None = None,
                              window_name: str | None = None) -> None:
    """Create the supervisor tmux window for one iteration."""
    from pm_core.watchers.supervisor_watcher import SupervisorWatcher

    root = state_root()
    data = store.load(root)

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("Supervisor window requires tmux.", err=True)
        raise SystemExit(1)

    pm_session = _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        click.echo(f"Supervisor: tmux session '{pm_session}' not found.", err=True)
        raise SystemExit(1)

    # Create a temporary supervisor instance to generate the prompt
    watcher = SupervisorWatcher(pm_root=str(root), target_filter=target_filter)
    supervisor_prompt = watcher.generate_prompt(iteration)

    # Determine working directory
    repo_dir = str(root.parent) if store.is_internal_pm_dir(root) else str(root)

    # Resolve model/provider — supervisor uses "supervisor" session type,
    # falling back to "watcher" if not configured.  Effort defaults to "high"
    # via DEFAULT_SESSION_EFFORT["supervisor"] in model_config.py.
    from pm_core.model_config import resolve_model_and_provider
    _resolution = resolve_model_and_provider("supervisor", project_data=data)

    claude_cmd = build_claude_shell_cmd(
        prompt=supervisor_prompt,
        transcript=transcript,
        cwd=repo_dir,
        model=_resolution.model,
        provider=_resolution.provider,
        effort=_resolution.effort,
    )

    # Use the caller-supplied window name (for per-instance uniqueness when
    # multiple supervisors run concurrently) or fall back to the class default.
    window_name = window_name or SupervisorWatcher.WINDOW_NAME

    # Kill existing supervisor window and recreate
    sessions_watching: list[str] = []
    existing = tmux_mod.find_window_by_name(pm_session, window_name)
    _log.info("_create_supervisor_window: iteration=%d existing=%s",
              iteration, existing)
    if existing:
        sessions_watching = tmux_mod.sessions_on_window(
            pm_session, existing["id"])
        tmux_mod.kill_window(pm_session, existing["id"])

    try:
        tmux_mod.new_window_get_pane(
            pm_session, window_name, claude_cmd, repo_dir,
            switch=False,
        )
        new_win = tmux_mod.find_window_by_name(pm_session, window_name)
        if new_win:
            tmux_mod.set_shared_window_size(pm_session, new_win["id"])
        click.echo(f"Supervisor window launched (iteration {iteration})")
    except Exception as e:
        click.echo(f"Supervisor: failed to create tmux window: {e}", err=True)
        raise SystemExit(1)

    if sessions_watching:
        tmux_mod.switch_sessions_to_window(
            sessions_watching, pm_session, window_name)


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

    # Resolve model/provider for watcher session
    from pm_core.model_config import resolve_model_and_provider
    _resolution = resolve_model_and_provider("watcher", project_data=data)

    claude_cmd = build_claude_shell_cmd(
        prompt=watcher_prompt,
        transcript=transcript,
        cwd=repo_dir,
        model=_resolution.model,
        provider=_resolution.provider,
        effort=_resolution.effort,
    )

    # Kill existing watcher window and recreate (fresh each iteration).
    # Track which sessions were watching the old window so we can switch
    # them to the new one (same pattern as review windows).
    sessions_watching: list[str] = []
    existing = tmux_mod.find_window_by_name(pm_session, AutoStartWatcher.WINDOW_NAME)
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
            pm_session, AutoStartWatcher.WINDOW_NAME, claude_cmd, repo_dir,
            switch=False,
        )
        new_win = tmux_mod.find_window_by_name(pm_session, AutoStartWatcher.WINDOW_NAME)
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
            sessions_watching, pm_session, AutoStartWatcher.WINDOW_NAME)
    else:
        _log.info("_create_watcher_window: no sessions_watching, skipping switch")
