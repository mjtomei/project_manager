"""Auto-start mode: automatically start ready PRs and optionally review loops.

When enabled, after each sync cycle detects merged PRs, the auto-start
logic checks for newly ready PRs (pending, all deps merged) and kicks
them off without changing TUI focus.

Settings stored in project.yaml under ``project``:
  auto_start: true/false
  auto_start_target: <pr_id>   # optional — stop after this PR is started

Toggle via TUI key ``A`` or CLI ``pm set auto-start on/off``.
"""

import sys

from pm_core.paths import configure_logger
from pm_core import store, graph
from pm_core.tui._shell import _run_shell_async

_log = configure_logger("pm.tui.auto_start")


def is_enabled(app) -> bool:
    """Check if auto-start mode is active."""
    return bool(app._data.get("project", {}).get("auto_start"))


def get_target(app) -> str | None:
    """Get the auto-start target PR (or None)."""
    return app._data.get("project", {}).get("auto_start_target")


def toggle(app) -> None:
    """Toggle auto-start mode on/off and persist to project.yaml."""
    project = app._data.setdefault("project", {})
    current = project.get("auto_start", False)
    project["auto_start"] = not current
    store.save(app._data, app._root)
    state = "ON" if not current else "OFF"
    target = project.get("auto_start_target")
    msg = f"Auto-start: {state}"
    if not current and target:
        msg += f" (target: {target})"
    app.log_message(msg)
    _log.info("auto_start toggled: %s", state)
    app._update_display()


def set_target(app, pr_id: str | None) -> None:
    """Set or clear the auto-start target PR."""
    project = app._data.setdefault("project", {})
    if pr_id:
        project["auto_start_target"] = pr_id
        app.log_message(f"Auto-start target: {pr_id}")
    else:
        project.pop("auto_start_target", None)
        app.log_message("Auto-start target cleared")
    store.save(app._data, app._root)


async def check_and_start(app) -> None:
    """Check for ready PRs and auto-start them.

    Called after sync detects merged PRs. Starts ready PRs one at a
    time via ``pm pr start`` without changing TUI focus.
    """
    if not is_enabled(app):
        return
    if not app._root:
        return

    prs = app._data.get("prs") or []
    ready = graph.ready_prs(prs)
    if not ready:
        return

    target = get_target(app)
    target_reached = False

    for pr in ready:
        pr_id = pr["id"]

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

        # Check if we've reached the target
        if target and pr_id == target:
            target_reached = True
            _log.info("auto_start: reached target PR %s, stopping", target)
            app.log_message(f"Auto-start: reached target {pr_id}")
            break

    # Reload state after starting PRs
    app._load_state()

    if target_reached:
        # Disable auto-start after reaching target
        app._data.setdefault("project", {})["auto_start"] = False
        store.save(app._data, app._root)
        app.log_message("Auto-start: disabled (target reached)")


async def _start_pr_quiet(app, pr_id: str) -> None:
    """Start a PR without changing TUI focus.

    Runs ``pm pr start <pr_id>`` as a subprocess. Unlike the interactive
    start_pr in pr_view, this doesn't use the inflight guard or spinner
    since auto-start can overlap with user actions.
    """
    import asyncio

    cmd = [sys.executable, "-m", "pm_core.wrapper", "pr", "start", pr_id]
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
