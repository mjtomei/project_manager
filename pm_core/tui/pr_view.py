"""PR actions, command execution, and tree filtering for the TUI.

All functions take the app instance as the first parameter so they can
access app state and call app methods (log_message, _load_state, etc.).
"""

import shlex
import sys

from pm_core.paths import configure_logger
from pm_core import store
from pm_core.tui._shell import _run_shell, _run_shell_async

_log = configure_logger("pm.tui.pr_view")

# PR command prefixes that require in-flight action guarding
PR_ACTION_PREFIXES = ("pr start", "pr review", "pr merge")


# ---------------------------------------------------------------------------
# Action guard
# ---------------------------------------------------------------------------

def guard_pr_action(app, action_desc: str) -> bool:
    """Check if a PR action is allowed (no conflicting action in-flight).

    Returns True if the action can proceed, False if blocked.
    Shows a status message when blocked.
    """
    if app._inflight_pr_action:
        _log.info("action blocked: %s (busy: %s)", action_desc, app._inflight_pr_action)
        app.log_message(f"Busy: {app._inflight_pr_action}", sticky=1.0)
        app.set_timer(1.0, app._clear_log_message)
        return False
    return True


# ---------------------------------------------------------------------------
# PR message handlers
# ---------------------------------------------------------------------------

def handle_pr_selected(app, pr_id: str) -> None:
    """Handle PR selection in the tech tree."""
    _log.debug("PR selected: %s", pr_id)
    app.log_message(f"Selected: {pr_id}")
    app.call_after_refresh(app._capture_frame, f"pr_selected:{pr_id}")

    # Persist selection so TUI restarts on this PR
    if app._data.get("project", {}).get("active_pr") != pr_id:
        app._data["project"]["active_pr"] = pr_id
        store.save(app._data, app._root)


# ---------------------------------------------------------------------------
# PR workflow actions
# ---------------------------------------------------------------------------

def start_pr(app) -> None:
    """Start working on the selected PR."""
    from pm_core.tui.tech_tree import TechTree
    from pm_core.paths import get_global_setting

    fresh = app._consume_z()
    tree = app.query_one("#tech-tree", TechTree)
    pr_id = tree.selected_pr_id
    _log.info("action: start_pr selected=%s fresh=%s", pr_id, fresh)
    if not pr_id:
        _log.info("action: start_pr - no PR selected")
        app.log_message("No PR selected")
        return

    # In beginner mode, block starting PRs with unmerged dependencies
    if get_global_setting("beginner-mode"):
        pr = store.get_pr(app._data, pr_id)
        if pr and pr.get("depends_on"):
            unmerged = []
            for dep_id in pr["depends_on"]:
                dep = store.get_pr(app._data, dep_id)
                if dep and dep.get("status") != "merged":
                    unmerged.append(f"{dep_id} ({dep.get('status', 'pending')})")
            if unmerged:
                app.log_error("Blocked", f"{pr_id} has unmerged deps: {', '.join(unmerged)}")
                return

    action_key = f"Starting {pr_id}" + (" (fresh)" if fresh else "")
    if not guard_pr_action(app, action_key):
        return
    app._inflight_pr_action = action_key
    cmd = f"pr start --fresh {pr_id}" if fresh else f"pr start {pr_id}"
    run_command(app, cmd, working_message=action_key, action_key=action_key)


def done_pr(app, fresh: bool = False) -> None:
    """Mark the selected PR as in_review and open a review window."""
    from pm_core.tui.tech_tree import TechTree

    tree = app.query_one("#tech-tree", TechTree)
    pr_id = tree.selected_pr_id
    _log.info("action: done_pr selected=%s fresh=%s", pr_id, fresh)
    if not pr_id:
        app.log_message("No PR selected")
        return
    action_key = f"Reviewing {pr_id}" + (" (fresh)" if fresh else "")
    if not guard_pr_action(app, action_key):
        return
    app._inflight_pr_action = action_key
    cmd = f"pr review --fresh {pr_id}" if fresh else f"pr review {pr_id}"
    run_command(app, cmd, working_message=action_key, action_key=action_key)


def merge_pr(app) -> None:
    """Merge the selected PR."""
    from pm_core.tui.tech_tree import TechTree

    tree = app.query_one("#tech-tree", TechTree)
    pr_id = tree.selected_pr_id
    _log.info("action: merge_pr selected=%s", pr_id)
    if not pr_id:
        app.log_message("No PR selected")
        return
    action_key = f"Merging {pr_id}"
    if not guard_pr_action(app, action_key):
        return
    app._inflight_pr_action = action_key
    run_command(app, f"pr merge --resolve-window {pr_id}", working_message=action_key, action_key=action_key)


# ---------------------------------------------------------------------------
# Tree filtering
# ---------------------------------------------------------------------------

def hide_plan(app) -> None:
    """Toggle hiding the selected PR's plan group."""
    from pm_core.tui.tech_tree import TechTree

    tree = app.query_one("#tech-tree", TechTree)

    # Check if selected node is a hidden label
    if tree.selected_is_hidden_label:
        plan_id = tree.get_selected_plan()
        if plan_id:
            tree._hidden_plans.discard(plan_id)
            tree._recompute()
            tree.refresh(layout=True)
            app.log_message(f"Showing: {tree.get_plan_display_name(plan_id)}")
        return

    plan_id = tree.get_selected_plan()
    if plan_id is None:
        # No selection (all hidden) — unhide all
        tree._hidden_plans.clear()
        tree._recompute()
        tree.refresh(layout=True)
        app.log_message("All plans visible")
        return
    if plan_id in tree._hidden_plans:
        tree._hidden_plans.discard(plan_id)
        tree._recompute()
        tree.refresh(layout=True)
        app.log_message(f"Showing: {tree.get_plan_display_name(plan_id)}")
    else:
        tree._hidden_plans.add(plan_id)
        tree._recompute()
        tree.refresh(layout=True)
        app.log_message(f"Hidden: {tree.get_plan_display_name(plan_id)}")


def toggle_merged(app) -> None:
    """Toggle hiding/showing of merged PRs and persist to project settings."""
    from pm_core.tui.tech_tree import TechTree

    tree = app.query_one("#tech-tree", TechTree)
    tree._hide_merged = not tree._hide_merged
    # Persist to project.yaml (per-project, overrides global)
    app._data.setdefault("project", {})["hide_merged"] = tree._hide_merged
    store.save(app._data, app._root)
    tree._recompute()
    tree.refresh(layout=True)
    app._update_filter_status()
    if tree._hide_merged:
        app.log_message("Merged PRs hidden")
    else:
        app.log_message("Merged PRs shown")


def cycle_sort(app) -> None:
    """Cycle through sort fields: updated -> created -> started -> reviewed -> merged."""
    from pm_core.tui.tech_tree import TechTree, SORT_FIELDS, SORT_FIELD_KEYS

    tree = app.query_one("#tech-tree", TechTree)
    current = tree._sort_field
    try:
        idx = SORT_FIELD_KEYS.index(current)
    except ValueError:
        idx = -1  # None (default) maps to before the first entry
    next_idx = (idx + 1) % len(SORT_FIELD_KEYS)
    tree._sort_field = SORT_FIELD_KEYS[next_idx]
    tree._recompute()
    tree.refresh(layout=True)
    app._update_filter_status()
    label = dict(SORT_FIELDS)[tree._sort_field]
    app.log_message(f"Sort: {label}")


def cycle_filter(app) -> None:
    """Cycle through status filters: all -> pending -> in_progress -> ..."""
    from pm_core.tui.tech_tree import TechTree, STATUS_FILTER_CYCLE, STATUS_ICONS

    tree = app.query_one("#tech-tree", TechTree)
    current = tree._status_filter
    try:
        idx = STATUS_FILTER_CYCLE.index(current)
    except ValueError:
        idx = 0
    next_idx = (idx + 1) % len(STATUS_FILTER_CYCLE)
    tree._status_filter = STATUS_FILTER_CYCLE[next_idx]
    tree._recompute()
    tree.refresh(layout=True)
    app._update_filter_status()
    if tree._status_filter:
        icon = STATUS_ICONS.get(tree._status_filter, "")
        app.log_message(f"Filter: {icon} {tree._status_filter}")
    else:
        app.log_message("Filter: all")


# ---------------------------------------------------------------------------
# Plan movement
# ---------------------------------------------------------------------------

def move_to_plan(app) -> None:
    """Open plan picker to move selected PR to a different plan."""
    from pm_core.tui.tech_tree import TechTree
    from pm_core.tui.screens import PlanPickerScreen

    tree = app.query_one("#tech-tree", TechTree)
    pr_id = tree.selected_pr_id
    if not pr_id:
        app.log_message("No PR selected")
        return
    pr = store.get_pr(app._data, pr_id)
    if not pr:
        app.log_message("PR not found")
        return
    plans = app._data.get("plans") or []
    current_plan = pr.get("plan") or None
    app.push_screen(
        PlanPickerScreen(plans, current_plan, pr_id),
        callback=lambda result: handle_plan_pick(app, pr_id, result),
    )


def handle_plan_pick(app, pr_id: str, result) -> None:
    """Handle the result from PlanPickerScreen."""
    from pm_core.tui.tech_tree import TechTree
    from pm_core.cli.helpers import _record_status_timestamp

    if result is None:
        return  # Cancelled
    pr = store.get_pr(app._data, pr_id)
    if not pr:
        return

    if isinstance(result, tuple) and result[0] == "_new":
        # Create a new plan
        _, title = result
        plan_id = store.next_plan_id(app._data)
        plan_file = f"plans/{plan_id}.md"
        entry = {"id": plan_id, "name": title, "file": plan_file, "status": "draft"}
        if app._data.get("plans") is None:
            app._data["plans"] = []
        app._data["plans"].append(entry)
        # Create plan file
        if app._root:
            plan_path = app._root / plan_file
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(f"# {title}\n\n<!-- Describe the plan here -->\n")
        pr["plan"] = plan_id
        _record_status_timestamp(pr)
        store.save(app._data, app._root)
        app._load_state()
        app.log_message(f"Moved {pr_id} → {plan_id}: {title} (new)")
    elif result == "_standalone":
        # Remove plan assignment
        old_plan = pr.get("plan")
        if not old_plan:
            app.log_message("Already standalone")
            return
        pr.pop("plan", None)
        _record_status_timestamp(pr)
        store.save(app._data, app._root)
        app._load_state()
        app.log_message(f"Moved {pr_id} → Standalone")
    elif isinstance(result, str):
        # Existing plan selected
        old_plan = pr.get("plan")
        if result == old_plan:
            app.log_message("Already in that plan")
            return
        pr["plan"] = result
        _record_status_timestamp(pr)
        store.save(app._data, app._root)
        app._load_state()
        tree = app.query_one("#tech-tree", TechTree)
        display = tree.get_plan_display_name(result)
        app.log_message(f"Moved {pr_id} → {display}")


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------

def handle_command_submitted(app, cmd: str) -> None:
    """Handle commands typed in the command bar."""
    from pm_core.tui.tech_tree import TechTree
    from pm_core.tui.plans_pane import PlansPane
    from pm_core.tui import pane_ops

    _log.info("command submitted: %s", cmd)
    cmd = cmd.strip()

    # Guard PR action commands from the command bar too
    action_key = None
    for prefix in PR_ACTION_PREFIXES:
        if cmd.startswith(prefix):
            action_key = cmd
            if not guard_pr_action(app, action_key):
                if app._plans_visible:
                    app.query_one("#plans-pane", PlansPane).focus()
                else:
                    app.query_one("#tech-tree", TechTree).focus()
                return
            app._inflight_pr_action = action_key
            break

    # Handle review loop commands
    parts = shlex.split(cmd)
    if cmd in ("review-loop", "review loop"):
        from pm_core.tui import review_loop_ui
        review_loop_ui.start_or_stop_loop(app, stop_on_suggestions=True)
        if app._plans_visible:
            app.query_one("#plans-pane", PlansPane).focus()
        else:
            app.query_one("#tech-tree", TechTree).focus()
        return
    if cmd in ("review-loop strict", "review loop strict"):
        from pm_core.tui import review_loop_ui
        review_loop_ui.start_or_stop_loop(app, stop_on_suggestions=False)
        if app._plans_visible:
            app.query_one("#plans-pane", PlansPane).focus()
        else:
            app.query_one("#tech-tree", TechTree).focus()
        return
    if cmd in ("review-loop stop", "review loop stop"):
        from pm_core.tui import review_loop_ui
        pr_id, _ = review_loop_ui._get_selected_pr(app)
        if pr_id:
            review_loop_ui.stop_loop_for_pr(app, pr_id)
        else:
            app.log_message("No PR selected")
        if app._plans_visible:
            app.query_one("#plans-pane", PlansPane).focus()
        else:
            app.query_one("#tech-tree", TechTree).focus()
        return

    # Handle auto-start commands
    if cmd in ("autostart", "auto-start", "auto start"):
        from pm_core.tui.auto_start import toggle
        app.run_worker(toggle(app))
        app.query_one("#tech-tree", TechTree).focus()
        return
    if cmd.startswith("autostart target") or cmd.startswith("auto-start target") or cmd.startswith("auto start target"):
        from pm_core.tui.auto_start import set_target
        target_pr = cmd.split("target", 1)[1].strip()
        set_target(app, target_pr if target_pr else None)
        app.query_one("#tech-tree", TechTree).focus()
        return

    # Commands that launch interactive Claude sessions need a tmux pane
    if len(parts) >= 3 and parts[0] == "plan" and parts[1] == "add":
        pane_ops.launch_pane(app, f"pm {cmd}", "plan-add")
        app._load_state()
    else:
        # Detect if this should run async (PR commands are long-running)
        working_message = None
        if cmd.startswith("pr start"):
            pr_id = parts[-1] if len(parts) >= 3 else "PR"
            working_message = f"Starting {pr_id}"
        elif cmd.startswith("pr review"):
            pr_id = parts[-1] if len(parts) >= 3 else "PR"
            working_message = f"Reviewing {pr_id}"

        run_command(app, cmd, working_message=working_message, action_key=action_key)
    if app._plans_visible:
        app.query_one("#plans-pane", PlansPane).focus()
    else:
        app.query_one("#tech-tree", TechTree).focus()


def run_command(app, cmd: str, working_message: str | None = None,
                action_key: str | None = None) -> None:
    """Execute a pm sub-command.

    Args:
        cmd: The command to run (e.g., "pr start pr-001")
        working_message: Optional message to show while running (enables async mode)
        action_key: Optional key for in-flight tracking (set before calling this)
    """
    parts = shlex.split(cmd)
    if not parts:
        return

    _log.info("running command: %s", parts)

    if working_message:
        # Run async with spinner
        app.run_worker(_run_command_async(app, cmd, parts, working_message, action_key))
    else:
        # Run sync for quick commands
        app.log_message(f"> {cmd}")
        _run_command_sync(app, parts)
        if action_key:
            app._inflight_pr_action = None


def _run_command_sync(app, parts: list[str]) -> None:
    """Run a command synchronously (for quick operations)."""
    try:
        cmd = [sys.executable, "-m", "pm_core.wrapper"] + parts
        result = _run_shell(
            cmd,
            cwd=str(app._root) if app._root else None,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            _log.info("pm exit=%d stderr=%s",
                      result.returncode, result.stderr.strip()[:200])
        if result.stdout.strip():
            app.log_message(result.stdout.strip().split("\n")[-1])
        if result.returncode != 0 and result.stderr.strip():
            app.log_message(f"Error: {result.stderr.strip().split(chr(10))[-1]}")
    except Exception as e:
        _log.exception("command failed: %s", parts)
        app.log_message(f"Error: {e}")

    # Reload state
    app._load_state()


async def _run_command_async(app, cmd: str, parts: list[str], working_message: str,
                             action_key: str | None = None) -> None:
    """Run a command asynchronously with animated spinner."""
    import asyncio
    import itertools

    cwd = str(app._root) if app._root else None
    full_cmd = [sys.executable, "-m", "pm_core.wrapper"] + list(parts)

    spinner_frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    spinner_running = True

    def update_spinner() -> None:
        if spinner_running:
            frame = next(spinner_frames)
            app.log_message(f"{frame} {working_message}...", capture=False)
            app.set_timer(0.1, update_spinner)

    # Start spinner
    update_spinner()

    try:
        proc = await _run_shell_async(
            full_cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        spinner_running = False
        stdout_text = stdout.decode() if stdout else ""
        stderr_text = stderr.decode() if stderr else ""

        _log.debug("pm async exit=%d stdout=%r stderr=%r",
                   proc.returncode, stdout_text[:200], stderr_text[:200])

        if stdout_text.strip():
            app.log_message(stdout_text.strip().split("\n")[-1])
        elif proc.returncode == 0:
            app.log_message(f"✓ {working_message} done")
        if proc.returncode != 0 and stderr_text.strip():
            app.log_message(f"Error: {stderr_text.strip().split(chr(10))[-1]}")

    except asyncio.TimeoutError:
        spinner_running = False
        _log.exception("command timed out: %s", cmd)
        app.log_message("Error: Command timed out")
    except Exception as e:
        spinner_running = False
        _log.exception("command failed: %s", cmd)
        app.log_message(f"Error: {e}")
    finally:
        if action_key:
            app._inflight_pr_action = None

    # Reload state
    app._load_state()
