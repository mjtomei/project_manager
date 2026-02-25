"""Auto-start mode: automatically start ready PRs and optionally review loops.

When enabled, after each sync cycle detects merged PRs, the auto-start
logic checks for newly ready PRs (pending, all deps merged) that are in
the transitive dependency tree of the target PR, and kicks them off
without changing TUI focus.

State is purely in-memory (on the app object) — it is lost on TUI
restart.  Toggle via TUI key ``A`` (sets selected PR as target) or
command bar: ``autostart``.
"""

import secrets
import sys
from pathlib import Path

from pm_core.paths import configure_logger
from pm_core import store, graph
from pm_core.tui._shell import _run_shell_async

_log = configure_logger("pm.tui.auto_start")


def is_enabled(app) -> bool:
    """Check if auto-start mode is active."""
    return bool(app._auto_start)


def get_target(app) -> str | None:
    """Get the auto-start target PR (or None)."""
    return app._auto_start_target


def get_transcript_dir(app) -> Path | None:
    """Return the transcript directory for the current auto-start run, or None."""
    run_id = app._auto_start_run_id
    if not run_id or not app._root:
        return None
    return app._root / "transcripts" / run_id


def _finalize_all_transcripts(app) -> None:
    """Finalize all transcript symlinks in the current run directory."""
    tdir = get_transcript_dir(app)
    if not tdir or not tdir.is_dir():
        return
    from pm_core.claude_launcher import finalize_transcript
    for p in tdir.iterdir():
        if p.is_symlink() and p.suffix == ".jsonl":
            finalize_transcript(p)


def _transitive_deps(prs: list[dict], target_id: str) -> set[str]:
    """Return the set of all PR IDs that ``target_id`` transitively depends on."""
    pr_map = {pr["id"]: pr for pr in prs}
    deps = set()
    stack = [target_id]
    while stack:
        pr_id = stack.pop()
        pr = pr_map.get(pr_id)
        if not pr:
            continue
        for dep_id in pr.get("depends_on") or []:
            if dep_id not in deps:
                deps.add(dep_id)
                stack.append(dep_id)
    return deps


def _disable(app) -> None:
    """Disable auto-start mode (in-memory only)."""
    _finalize_all_transcripts(app)
    # Stop the monitor loop if it's running
    from pm_core.tui import monitor_ui
    if monitor_ui.is_running(app):
        monitor_ui.stop_monitor(app)
    app._auto_start = False
    app._auto_start_target = None
    app._auto_start_run_id = None
    app._update_display()


async def toggle(app, selected_pr_id: str | None = None) -> None:
    """Toggle auto-start mode.

    - If auto-start is OFF: turn it ON with the selected PR as target,
      then immediately start any ready PRs in the target's dep tree.
    - If auto-start is ON: turn it OFF.
    """
    if not app._auto_start:
        # Turn ON — always set target to selected PR
        app._auto_start = True
        if selected_pr_id:
            app._auto_start_target = selected_pr_id
            app.log_message(f"Auto-start: ON → {selected_pr_id}")
        else:
            app.log_message("Auto-start: ON (no target — all ready PRs)")
        # Generate run ID and create transcript directory
        target_tag = selected_pr_id or "all"
        run_id = f"autostart-{target_tag}-{secrets.token_hex(4)}"
        app._auto_start_run_id = run_id
        if app._root:
            tdir = app._root / "transcripts" / run_id
            tdir.mkdir(parents=True, exist_ok=True)
            _log.info("auto_start: created transcript dir %s", tdir)
        _log.info("auto_start: enabled target=%s run_id=%s",
                  app._auto_start_target, run_id)
        app._update_display()
        # Start the autonomous monitor alongside auto-start
        from pm_core.tui import monitor_ui
        if not monitor_ui.is_running(app):
            monitor_ui.start_monitor(app, transcript_dir=str(tdir) if tdir else None)
        # Immediately start any ready PRs
        await check_and_start(app)
    else:
        # Turn OFF
        _disable(app)
        app.log_message("Auto-start: OFF")
        _log.info("auto_start: disabled")


def set_target(app, pr_id: str | None) -> None:
    """Set or clear the auto-start target PR."""
    if pr_id:
        app._auto_start_target = pr_id
        app.log_message(f"Auto-start target: {pr_id}")
    else:
        app._auto_start_target = None
        app.log_message("Auto-start target cleared")


async def check_and_start(app) -> None:
    """Check for ready PRs and auto-start those needed for the target.

    Called after sync detects merged PRs. When a target is set, only
    starts ready PRs that are transitive dependencies of the target (or
    the target itself). Without a target, starts all ready PRs.

    Also starts review loops for in_review PRs that don't have one
    running.
    """
    if not is_enabled(app):
        return
    if not app._root:
        return

    prs = app._data.get("prs") or []
    target = get_target(app)

    # Disable auto-start if the target PR has been merged
    if target:
        target_pr = store.get_pr(app._data, target)
        if target_pr and target_pr.get("status") == "merged":
            _log.info("auto_start: target %s merged, disabling", target)
            app.log_message(f"Auto-start: target {target} merged, disabling")
            _disable(app)
            return

    ready = graph.ready_prs(prs)
    if ready:
        # Compute which PRs are relevant for the target
        if target:
            allowed = _transitive_deps(prs, target)
            allowed.add(target)  # the target itself is also eligible
        else:
            allowed = None  # no target = start everything

        for pr in ready:
            pr_id = pr["id"]

            # Skip PRs outside the target's dependency tree
            if allowed is not None and pr_id not in allowed:
                continue

            # Skip if already has a workdir (was previously started)
            if pr.get("workdir"):
                continue

            _log.info("auto_start: starting ready PR %s", pr_id)
            app.log_message(f"Auto-start: starting {pr_id}")

            try:
                await _start_pr_quiet(app, pr_id)
            except Exception as e:
                _log.exception("auto_start: failed to start %s", pr_id)
                app.log_message(f"Auto-start error: {e}")
                continue

            # Once the target itself is started, stop starting more PRs.
            if target and pr_id == target:
                _log.info("auto_start: target PR %s started, awaiting merge", target)
                app.log_message(f"Auto-start: target {pr_id} started")
                break

        # Reload state after starting PRs
        app._load_state()
        prs = app._data.get("prs") or []

    # Also start review loops for in_review PRs without active loops
    _auto_start_review_loops(app, target, prs)


def _auto_start_review_loops(app, target: str | None = None,
                              prs: list[dict] | None = None) -> None:
    """Start review loops for in_review PRs that don't have one running.

    Only activates when auto-start mode is enabled. When a target is set,
    only starts loops for PRs in the target's dependency tree.
    """
    if not is_enabled(app):
        return

    if prs is None:
        prs = app._data.get("prs") or []

    # Scope to target's dependency tree if set
    if target:
        allowed = _transitive_deps(prs, target)
        allowed.add(target)
    else:
        allowed = None

    for pr in prs:
        if pr.get("status") != "in_review":
            continue
        pr_id = pr["id"]
        if allowed is not None and pr_id not in allowed:
            continue
        # Skip if a review loop is already running or completed for this PR
        loop = app._review_loops.get(pr_id)
        if loop:
            continue
        # Skip if no workdir (shouldn't happen for in_review, but guard)
        if not pr.get("workdir"):
            continue

        _log.info("auto_start: starting review loop for %s", pr_id)
        app.log_message(f"Auto-start: review loop for {pr_id}")
        from pm_core.tui.review_loop_ui import _start_loop
        tdir = get_transcript_dir(app)
        _start_loop(app, pr_id, pr, stop_on_suggestions=False,
                     transcript_dir=str(tdir) if tdir else None)


async def _start_pr_quiet(app, pr_id: str) -> None:
    """Start a PR without changing TUI focus.

    Runs ``pm pr start --background <pr_id>`` as a subprocess. The
    ``--background`` flag tells ``pr start`` to create the tmux window
    without switching focus.  Unlike the interactive start_pr in pr_view,
    this doesn't use the inflight guard or spinner since auto-start can
    overlap with user actions.
    """
    import asyncio

    cmd = [sys.executable, "-m", "pm_core.wrapper", "pr", "start", "--background"]
    tdir = get_transcript_dir(app)
    if tdir:
        cmd.extend(["--transcript", str(tdir / f"impl-{pr_id}.jsonl")])
    cmd.append(pr_id)
    cwd = str(app._root) if app._root else None

    proc = await _run_shell_async(
        cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

    if proc.returncode != 0:
        stderr_text = stderr.decode() if stderr else ""
        _log.warning("auto_start: pm pr start %s failed: %s", pr_id, stderr_text[:200])
    else:
        _log.info("auto_start: pm pr start %s succeeded", pr_id)
