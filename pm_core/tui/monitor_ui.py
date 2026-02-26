"""Monitor loop UI integration for the TUI.

Manages starting/stopping the autonomous monitor loop and updating
the TUI display.  The monitor runs alongside auto-start and watches
all active tmux panes for issues.

Only one monitor loop can run at a time (unlike review loops which
are per-PR).
"""

from pathlib import Path

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.monitor_loop import (
    MonitorLoopState,
    start_monitor_loop_background,
    VERDICT_READY,
    VERDICT_INPUT_REQUIRED,
)

_log = configure_logger("pm.tui.monitor_ui")

# Plan definitions for monitor-generated files
MONITOR_PLANS = {
    "bugs": {
        "name": "Bugs",
        "file": "bugs.md",
        "description": "# Bugs\n\nBugs discovered by the autonomous monitor.\n\n## PRs\n",
    },
    "improvements": {
        "name": "Improvements",
        "file": "improvements.md",
        "description": "# Improvements\n\nImprovements suggested by the autonomous monitor.\n\n## PRs\n",
    },
}


def ensure_monitor_plans(app) -> Path | None:
    """Create and register bugs.md and improvements.md as plans in the meta workdir.

    Returns the meta workdir's ``pm/`` root (where bugs.md lives), or None on error.
    """
    from pm_core.cli.meta import ensure_meta_workdir

    try:
        meta_workdir = ensure_meta_workdir()
    except Exception:
        _log.exception("monitor_ui: failed to ensure meta workdir")
        return None

    root = meta_workdir / "pm"
    if not root.is_dir():
        root.mkdir(parents=True, exist_ok=True)

    # Ensure project.yaml exists in meta workdir's pm/ dir
    project_yaml = root / "project.yaml"
    if not project_yaml.exists():
        store.save({"project": {"name": "pm-meta"}, "plans": [], "prs": []}, root)

    data = store.load(root)
    existing_plan_ids = {p["id"] for p in (data.get("plans") or [])}
    if data.get("plans") is None:
        data["plans"] = []

    changed = False
    for plan_id, info in MONITOR_PLANS.items():
        if plan_id in existing_plan_ids:
            continue
        data["plans"].append({
            "id": plan_id,
            "name": info["name"],
            "file": info["file"],
            "status": "draft",
        })
        plan_path = root / info["file"]
        if not plan_path.exists():
            plan_path.write_text(info["description"])
        changed = True
        _log.info("monitor_ui: created monitor plan %s (%s) in %s", plan_id, info["file"], root)

    if changed:
        from pm_core.cli.helpers import save_and_push
        save_and_push(data, root, "pm: register monitor plans")

    return root


def load_monitor_plan_prs(app) -> int:
    """Load PRs from bugs.md and improvements.md into the meta workdir's project.yaml.

    Returns the number of PRs created.
    """
    from pm_core.plan_parser import parse_plan_prs
    from pm_core.cli.helpers import _make_pr_entry, save_and_push
    from pm_core.cli.plan import _build_pr_description
    from pm_core.cli.meta import ensure_meta_workdir

    try:
        meta_workdir = ensure_meta_workdir()
    except Exception:
        _log.exception("monitor_ui: failed to ensure meta workdir for PR loading")
        return 0

    root = meta_workdir / "pm"
    if not root.is_dir():
        return 0

    data = store.load(root)
    if data.get("prs") is None:
        data["prs"] = []

    existing_ids = {p["id"] for p in data["prs"]}
    existing_titles = {p.get("title", ""): p["id"] for p in data["prs"]}
    total_created = 0

    for plan_id, info in MONITOR_PLANS.items():
        plan_path = root / info["file"]
        if not plan_path.exists():
            continue

        content = plan_path.read_text()
        prs = parse_plan_prs(content)
        if not prs:
            continue

        # Pre-compute IDs for new PRs
        title_to_id = {}
        for pr in prs:
            if pr["title"] in existing_titles:
                title_to_id[pr["title"]] = existing_titles[pr["title"]]
            else:
                pr_id = store.generate_pr_id(pr["title"], pr.get("description", ""), existing_ids)
                title_to_id[pr["title"]] = pr_id
                existing_ids.add(pr_id)

        for pr in prs:
            pr_id = title_to_id[pr["title"]]
            if pr["title"] in existing_titles:
                continue

            slug = store.slugify(pr["title"])
            branch = f"pm/{pr_id}-{slug}"
            desc = _build_pr_description(pr)

            entry = _make_pr_entry(pr_id, pr["title"], branch,
                                   plan=plan_id, description=desc)
            data["prs"].append(entry)
            existing_titles[pr["title"]] = pr_id
            total_created += 1
            _log.info("monitor_ui: loaded PR %s: %s (plan=%s) in %s", pr_id, pr["title"], plan_id, root)

    if total_created:
        save_and_push(data, root, "pm: load monitor plan PRs")

    return total_created


# Icons for monitor verdicts (used in log line)
MONITOR_VERDICT_ICONS = {
    VERDICT_READY: "[green bold]OK READY[/]",
    VERDICT_INPUT_REQUIRED: "[red bold]!! INPUT_REQUIRED[/]",
    "KILLED": "[red bold]X KILLED[/]",
    "ERROR": "[red bold]! ERROR[/]",
    "": "[dim]--[/]",
}


# ---------------------------------------------------------------------------
# Start / stop
# ---------------------------------------------------------------------------

def start_monitor(app, transcript_dir: str | None = None,
                   meta_pm_root: str | None = None) -> None:
    """Start the monitor loop."""
    from pm_core import tmux as tmux_mod

    if not tmux_mod.in_tmux():
        app.log_message("Monitor requires tmux.")
        return

    # Don't start if already running
    if app._monitor_state and app._monitor_state.running:
        app.log_message("Monitor is already running.")
        return

    pm_root = str(store.find_project_root())

    state = MonitorLoopState(
        auto_start_target=getattr(app, '_auto_start_target', None),
        meta_pm_root=meta_pm_root,
    )
    app._monitor_state = state

    _log.info("monitor_ui: starting monitor loop=%s", state.loop_id)
    app.log_message(
        "[bold]Monitor started[/] -- watching for issues",
        sticky=3,
    )

    # Ensure the poll timer is running (shared with review loops)
    from pm_core.tui.review_loop_ui import _ensure_poll_timer
    _ensure_poll_timer(app)

    start_monitor_loop_background(
        state=state,
        pm_root=pm_root,
        on_iteration=lambda s: _on_iteration_from_thread(app, s),
        on_complete=lambda s: _on_complete_from_thread(app, s),
        transcript_dir=transcript_dir,
    )


def stop_monitor(app) -> None:
    """Request graceful stop of the monitor loop."""
    state = app._monitor_state
    if not state or not state.running:
        app.log_message("No monitor loop running.")
        return

    _log.info("monitor_ui: stopping monitor loop")
    state.stop_requested = True
    app.log_message("[bold]Monitor stopping[/] (finishing current iteration)...")


def is_running(app) -> bool:
    """Check if the monitor loop is running."""
    state = app._monitor_state
    return bool(state and state.running)


# ---------------------------------------------------------------------------
# Background thread callbacks
# ---------------------------------------------------------------------------

def _on_iteration_from_thread(app, state: MonitorLoopState) -> None:
    """Called from the background thread after each iteration."""
    _log.info("monitor_ui: iteration %d verdict=%s",
              state.iteration, state.latest_verdict)


def _on_complete_from_thread(app, state: MonitorLoopState) -> None:
    """Called from the background thread when the loop finishes."""
    _log.info("monitor_ui: loop complete -- verdict=%s iterations=%d",
              state.latest_verdict, state.iteration)

    # Finalize transcripts
    tdir = getattr(state, '_transcript_dir', None)
    if tdir:
        from pathlib import Path
        from pm_core.claude_launcher import finalize_transcript
        tdir_path = Path(tdir)
        if tdir_path.is_dir():
            for p in tdir_path.iterdir():
                if (p.is_symlink() and p.suffix == ".jsonl"
                        and p.name.startswith("monitor-")):
                    finalize_transcript(p)


# ---------------------------------------------------------------------------
# Poll timer integration (called from _poll_loop_state)
# ---------------------------------------------------------------------------

def poll_monitor_state(app) -> None:
    """Check monitor state and notify user as needed.

    Called from the shared 1-second poll timer in review_loop_ui.
    """
    state = app._monitor_state
    if not state:
        return

    if state.running:
        # Notify when waiting for input
        if state.input_required and not state._ui_notified_input:
            state._ui_notified_input = True
            app.log_message(
                "[red bold]!! Monitor INPUT_REQUIRED[/]: "
                "check the monitor pane for details",
                sticky=30,
            )
    elif not state._ui_notified_done:
        state._ui_notified_done = True
        verdict_icon = MONITOR_VERDICT_ICONS.get(state.latest_verdict, state.latest_verdict)
        app.log_message(
            f"Monitor stopped: {verdict_icon} "
            f"({state.iteration} iteration{'s' if state.iteration != 1 else ''})",
            sticky=10,
        )
