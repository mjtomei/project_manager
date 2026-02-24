"""Auto-start mode: automatically start ready PRs and optionally review loops.

When enabled, after each sync cycle detects merged PRs, the auto-start
logic checks for newly ready PRs (pending, all deps merged) that are in
the transitive dependency tree of the target PR, and kicks them off
without changing TUI focus.

Settings stored in project.yaml under ``project``:
  auto_start: true/false
  auto_start_target: <pr_id>   # the PR we're working towards

Toggle via TUI key ``A`` (sets selected PR as target) or command bar:
``autostart``.
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
    return bool(app._data.get("project", {}).get("auto_start"))


def get_target(app) -> str | None:
    """Get the auto-start target PR (or None)."""
    return app._data.get("project", {}).get("auto_start_target")


def get_transcript_dir(app) -> Path | None:
    """Return the transcript directory for the current auto-start run, or None."""
    run_id = app._data.get("project", {}).get("auto_start_run_id")
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


async def toggle(app, selected_pr_id: str | None = None) -> None:
    """Toggle auto-start mode.

    - If auto-start is OFF: turn it ON with the selected PR as target,
      then immediately start any ready PRs in the target's dep tree.
    - If auto-start is ON: turn it OFF.
    """
    project = app._data.setdefault("project", {})
    current = project.get("auto_start", False)

    if not current:
        # Turn ON — always set target to selected PR
        project["auto_start"] = True
        if selected_pr_id:
            project["auto_start_target"] = selected_pr_id
            app.log_message(f"Auto-start: ON → {selected_pr_id}")
        else:
            app.log_message("Auto-start: ON (no target — all ready PRs)")
        # Generate run ID and create transcript directory
        target_tag = selected_pr_id or "all"
        run_id = f"autostart-{target_tag}-{secrets.token_hex(4)}"
        project["auto_start_run_id"] = run_id
        if app._root:
            tdir = app._root / "transcripts" / run_id
            tdir.mkdir(parents=True, exist_ok=True)
            _log.info("auto_start: created transcript dir %s", tdir)
        store.save(app._data, app._root)
        _log.info("auto_start: enabled=%s target=%s run_id=%s",
                  project.get("auto_start"), project.get("auto_start_target"), run_id)
        app._update_display()
        # Immediately start any ready PRs
        await check_and_start(app)
    else:
        # Turn OFF — finalize all transcript symlinks
        _finalize_all_transcripts(app)
        project["auto_start"] = False
        project.pop("auto_start_target", None)
        project.pop("auto_start_run_id", None)
        app.log_message("Auto-start: OFF")
        store.save(app._data, app._root)
        _log.info("auto_start: disabled")
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
    """Check for ready PRs and auto-start those needed for the target.

    Called after sync detects merged PRs. When a target is set, only
    starts ready PRs that are transitive dependencies of the target (or
    the target itself). Without a target, starts all ready PRs.

    Also resumes review loops for in_review PRs that don't have one
    running (e.g. after a TUI restart).
    """
    if not is_enabled(app):
        return
    if not app._root:
        return

    prs = app._data.get("prs") or []
    target = get_target(app)

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
            # Auto-start stays enabled — it disables when the target is merged
            # (handled by _finalize_merge in pr.py).
            if target and pr_id == target:
                _log.info("auto_start: target PR %s started, awaiting merge", target)
                app.log_message(f"Auto-start: target {pr_id} started")
                break

        # Reload state after starting PRs
        app._load_state()
        prs = app._data.get("prs") or []

    # Always resume review loops for in_review PRs without active loops.
    # This handles TUI restarts where loop state was lost but PR state
    # is still in_review on disk.
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
