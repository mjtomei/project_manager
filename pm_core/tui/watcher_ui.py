"""Watcher loop UI integration for the TUI.

Manages starting/stopping watchers and updating the TUI display
via the WatcherManager framework.

Watchers can run independently of auto-start mode.
"""

from pathlib import Path

from pm_core.paths import configure_logger
from pm_core import store

_log = configure_logger("pm.tui.watcher_ui")

# Plan definitions for watcher-generated files
WATCHER_PLANS = {
    "bugs": {
        "name": "Bugs",
        "file": "bugs.md",
        "description": "# Bugs\n\nBugs discovered by the autonomous watcher.\n\n## PRs\n",
    },
    "improvements": {
        "name": "Improvements",
        "file": "improvements.md",
        "description": "# Improvements\n\nImprovements suggested by the autonomous watcher.\n\n## PRs\n",
    },
}


def ensure_watcher_plans(app) -> Path | None:
    """Create and register bugs.md and improvements.md as plans in the meta workdir.

    Returns the meta workdir's ``pm/`` root (where bugs.md lives), or None on error.
    """
    from pm_core.cli.meta import ensure_meta_workdir

    try:
        meta_workdir = ensure_meta_workdir()
    except Exception:
        _log.exception("watcher_ui: failed to ensure meta workdir")
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
    for plan_id, info in WATCHER_PLANS.items():
        if plan_id in existing_plan_ids:
            continue
        data["plans"].append(store.make_plan_entry(plan_id, info["name"], info["file"]))
        plan_path = root / info["file"]
        if not plan_path.exists():
            plan_path.write_text(info["description"])
        changed = True
        _log.info("watcher_ui: created watcher plan %s (%s) in %s", plan_id, info["file"], root)

    if changed:
        from pm_core.cli.helpers import save_and_push
        save_and_push(data, root, "pm: register watcher plans")

    return root


def load_watcher_plan_prs(app) -> int:
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
        _log.exception("watcher_ui: failed to ensure meta workdir for PR loading")
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

    for plan_id, info in WATCHER_PLANS.items():
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
            _log.info("watcher_ui: loaded PR %s: %s (plan=%s) in %s", pr_id, pr["title"], plan_id, root)

    if total_created:
        save_and_push(data, root, "pm: load watcher plan PRs")

    return total_created


# Icons for watcher verdicts (used in log line)
WATCHER_VERDICT_ICONS = {
    "READY": "[green bold]OK READY[/]",
    "INPUT_REQUIRED": "[red bold]!! INPUT_REQUIRED[/]",
    "KILLED": "[red bold]X KILLED[/]",
    "ERROR": "[red bold]! ERROR[/]",
    "": "[dim]--[/]",
}


# ---------------------------------------------------------------------------
# Start / stop
# ---------------------------------------------------------------------------

def start_watcher(app, transcript_dir: str | None = None,
                   meta_pm_root: str | None = None,
                   watcher_type: str = "auto-start") -> None:
    """Start a watcher via the WatcherManager."""
    from pm_core import tmux as tmux_mod

    if not tmux_mod.in_tmux():
        app.log_message("Watcher requires tmux.")
        return

    manager = app._watcher_manager
    existing = manager.find_by_type(watcher_type)
    if existing and existing.state.running:
        app.log_message(f"Watcher '{watcher_type}' is already running.")
        return

    # Create and register a new watcher instance
    from pm_core.watchers import get_watcher_class
    cls = get_watcher_class(watcher_type)
    if not cls:
        app.log_message(f"Unknown watcher type: {watcher_type}")
        return

    pm_root = str(store.find_project_root())
    kwargs = {}
    if watcher_type == "auto-start":
        kwargs["auto_start_target"] = getattr(app, '_auto_start_target', None)
        kwargs["meta_pm_root"] = meta_pm_root
    watcher = cls(pm_root=pm_root, **kwargs)
    manager.register(watcher)

    _log.info("watcher_ui: starting watcher: %s (id=%s)",
              watcher_type, watcher.state.watcher_id)
    app.log_message(
        f"[bold]{watcher.DISPLAY_NAME} started[/] -- watching for issues",
        sticky=3,
    )

    # Ensure the poll timer is running
    from pm_core.tui.review_loop_ui import _ensure_poll_timer
    _ensure_poll_timer(app)

    manager.start(
        watcher.state.watcher_id,
        on_iteration=lambda s: _on_iteration_from_thread(app, s),
        on_complete=lambda s: _on_complete_from_thread(app, s),
        transcript_dir=transcript_dir,
    )


def stop_watcher(app, watcher_type: str = "auto-start") -> None:
    """Request graceful stop of a watcher."""
    manager = app._watcher_manager
    watcher = manager.find_by_type(watcher_type)
    if watcher and watcher.state.running:
        _log.info("watcher_ui: stopping watcher: %s", watcher_type)
        manager.stop(watcher.state.watcher_id)
        app.log_message(
            f"[bold]{watcher.DISPLAY_NAME} stopping[/] (finishing current iteration)..."
        )
        return

    app.log_message("No watcher running.")


def is_running(app, watcher_type: str = "auto-start") -> bool:
    """Check if a watcher is running."""
    manager = app._watcher_manager
    state = manager.find_state_by_type(watcher_type)
    return bool(state and state.running)


# ---------------------------------------------------------------------------
# Background thread callbacks
# ---------------------------------------------------------------------------

def _on_iteration_from_thread(app, state) -> None:
    """Called from the background thread after each iteration."""
    _log.info("watcher_ui: iteration %d verdict=%s",
              state.iteration, state.latest_verdict)


def _on_complete_from_thread(app, state) -> None:
    """Called from the background thread when the loop finishes."""
    _log.info("watcher_ui: loop complete -- verdict=%s iterations=%d",
              state.latest_verdict, state.iteration)

    # Finalize transcripts
    tdir = getattr(state, '_transcript_dir', None)
    if tdir:
        from pathlib import Path
        from pm_core.claude_launcher import finalize_transcript
        tdir_path = Path(tdir)
        if tdir_path.is_dir():
            for p in tdir_path.iterdir():
                if p.is_symlink() and p.suffix == ".jsonl":
                    finalize_transcript(p)


# ---------------------------------------------------------------------------
# Poll timer integration (called from _poll_loop_state)
# ---------------------------------------------------------------------------

def poll_watcher_state(app) -> None:
    """Check watcher state and notify user as needed.

    Called from the shared 1-second poll timer in review_loop_ui.
    """
    manager = app._watcher_manager
    for info in manager.list_watchers():
        watcher = manager.get_watcher(info["id"])
        if not watcher:
            continue
        s = watcher.state
        if s.running:
            if s.input_required and not s._ui_notified_input:
                s._ui_notified_input = True
                app.log_message(
                    f"[red bold]!! {watcher.DISPLAY_NAME} INPUT_REQUIRED[/]: "
                    "check the watcher pane for details",
                    sticky=30,
                )
        elif not s._ui_notified_done and s.iteration > 0:
            s._ui_notified_done = True
            verdict_icon = WATCHER_VERDICT_ICONS.get(
                s.latest_verdict, s.latest_verdict)
            msg = (
                f"{watcher.DISPLAY_NAME} stopped: {verdict_icon} "
                f"({s.iteration} iteration{'s' if s.iteration != 1 else ''})"
            )
            if s.latest_verdict == "ERROR" and s.latest_summary:
                err_text = s.latest_summary[:300]
                msg += f"\n  Error: {err_text}"
                from pm_core.paths import command_log_file
                msg += f"\n  See log: {command_log_file()}"
            app.log_message(msg, sticky=10)
