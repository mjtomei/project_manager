"""Pane launch, kill, rebalance, and related operations for the TUI.

All functions take the app instance as the first parameter so they can
access app state and call app methods (log_message, push_screen, etc.).
"""

import os
import shlex
import subprocess
from pathlib import Path

from pm_core.paths import configure_logger, command_log_file
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core import store, guide, notes
from pm_core.tui.screens import ConnectScreen

_log = configure_logger("pm.tui.pane_ops")

# Guide steps that indicate setup is still in progress
GUIDE_SETUP_STEPS = {"no_project", "initialized", "has_plan_draft", "has_plan_prs", "needs_deps_review"}


def _run_shell(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a shell command with logging."""
    cmd_str = shlex.join(cmd) if isinstance(cmd, list) else cmd
    _log.info("shell: %s", cmd_str)
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        stderr = getattr(result, 'stderr', '')
        if stderr:
            _log.debug("shell failed (rc=%d): %s", result.returncode, stderr[:200])
    return result


# ---------------------------------------------------------------------------
# Core pane infrastructure
# ---------------------------------------------------------------------------

def get_session_and_window(app) -> tuple[str, str] | None:
    """Get tmux session name and window ID. Returns None if not in tmux."""
    if not tmux_mod.in_tmux():
        app.log_message("Not in tmux. Use 'pm session' to start a tmux session.")
        return None
    session = tmux_mod.get_session_name()
    window = tmux_mod.get_window_id(session)
    return session, window


def launch_pane(app, cmd: str, role: str) -> None:
    """Launch a wrapped pane, register it, and rebalance.

    If a pane with this role already exists and is alive, focuses it instead
    of creating a duplicate.
    """
    info = get_session_and_window(app)
    if not info:
        return
    session, window = info
    _log.info("launch_pane: session=%s window=%s role=%s", session, window, role)

    # Check if a pane with this role already exists
    existing_pane = pane_layout.find_live_pane_by_role(session, role)
    _log.info("launch_pane: find_live_pane_by_role returned %s", existing_pane)
    if existing_pane:
        _log.info("pane with role=%s already exists: %s, focusing", role, existing_pane)
        tmux_mod.select_pane_smart(existing_pane, session, window)
        app.log_message(f"Focused existing {role} pane")
        return

    data = pane_layout.load_registry(session)
    gen = data.get("generation", "0")
    escaped = cmd.replace("'", "'\\''")
    wrap = f"bash -c 'trap \"pm _pane-exited {session} {window} {gen} $TMUX_PANE\" EXIT; {escaped}'"
    try:
        pane_id = tmux_mod.split_pane(session, "h", wrap)
        pane_layout.register_pane(session, window, pane_id, role, cmd)
        pane_layout.rebalance(session, window)
        tmux_mod.select_pane_smart(pane_id, session, window)
        app.log_message(f"Launched {role} pane")
        _log.info("launched pane: role=%s id=%s", role, pane_id)
    except Exception as e:
        _log.exception("failed to launch %s pane", role)
        app.log_message(f"Error: {e}")


def rebalance(app) -> None:
    """Rebalance pane layout."""
    _log.info("rebalance")
    info = get_session_and_window(app)
    if not info:
        return
    session, window = info
    data = pane_layout.load_registry(session)
    data["user_modified"] = False
    pane_layout.save_registry(session, data)
    pane_layout.rebalance(session, window)
    app.log_message("Layout rebalanced")


def find_editor() -> str:
    """Find the user's preferred editor."""
    return os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))


# ---------------------------------------------------------------------------
# PR editing actions
# ---------------------------------------------------------------------------

def edit_plan(app) -> None:
    """Edit the selected PR in an interactive editor."""
    from pm_core.tui.tech_tree import TechTree
    _log.info("edit_plan")
    tree = app.query_one("#tech-tree", TechTree)
    pr_id = tree.selected_pr_id
    if not pr_id:
        app.log_message("No PR selected")
        return
    launch_pane(app, f"pm pr edit {pr_id}", "pr-edit")


def view_plan(app) -> None:
    """Open the plan file associated with the selected PR in a pane."""
    from pm_core.tui.tech_tree import TechTree
    _log.info("view_plan")
    tree = app.query_one("#tech-tree", TechTree)
    pr_id = tree.selected_pr_id
    if not pr_id:
        app.log_message("No PR selected")
        return
    pr = store.get_pr(app._data, pr_id)
    plan = app._get_plan_for_pr(pr)
    if not plan:
        app.log_message("No plan associated with this PR")
        return
    plan_file = plan.get("file", "")
    if not plan_file or not app._root:
        app.log_message("Plan file not found")
        return
    plan_path = app._root / plan_file
    if not plan_path.exists():
        app.log_message(f"Plan file not found: {plan_path}")
        return
    launch_pane(app, f"less {plan_path}", "plan")


# ---------------------------------------------------------------------------
# Pane launch actions
# ---------------------------------------------------------------------------

def launch_notes(app) -> None:
    """Launch the notes editor in a pane."""
    _log.info("launch_notes")
    root = app._root or (Path.cwd() / "pm")
    notes_path = root / notes.NOTES_FILENAME
    launch_pane(app, f"pm notes {notes_path}", "notes")


def view_log(app) -> None:
    """View the TUI log file in a pane."""
    _log.info("view_log")
    log_path = command_log_file()
    if not log_path.exists():
        app.log_message("No log file yet.")
        return
    launch_pane(app, f"tail -f {log_path}", "log")


def launch_meta(app) -> None:
    """Launch a meta-development session to work on pm itself."""
    _log.info("launch_meta")
    app._run_command("meta")


def auto_launch_guide(app) -> None:
    """Auto-launch the guide pane."""
    _log.info("auto-launching guide pane")
    launch_pane(app, "pm guide", "guide")


def toggle_guide(app) -> None:
    """Toggle between guide progress view and tech tree view."""
    _log.info("toggle_guide dismissed=%s current_step=%s",
              app._guide_dismissed, app._current_guide_step)
    if app._guide_dismissed:
        # Restore guide view if we're in a guide setup step
        state, _ = guide.resolve_guide_step(app._root)
        if state in GUIDE_SETUP_STEPS:
            _log.info("toggle_guide - restoring guide view for step %s", state)
            app._guide_dismissed = False
            app._show_guide_view(state)
            launch_pane(app, "pm guide", "guide")
        else:
            # Not in guide setup steps, just launch the guide pane
            _log.info("toggle_guide - launching guide pane (not in setup steps)")
            launch_pane(app, "pm guide", "guide")
    elif app._current_guide_step is not None:
        # Guide view is showing, dismiss it
        _log.info("toggle_guide - dismissing guide from step %s", app._current_guide_step)
        app._guide_dismissed = True
        app._show_normal_view()
        app.log_message("Guide dismissed. Press 'g' to restore.")


def launch_claude(app) -> None:
    """Launch an interactive Claude session in the project directory."""
    from pm_core.claude_launcher import find_claude, build_claude_shell_cmd
    claude = find_claude()
    if not claude:
        app.log_message("Claude CLI not found")
        return

    sess = app._session_name or "default"
    pane_id = os.environ.get("TMUX_PANE", "")
    prompt = f"""\
## Session Context

You are running inside a pm (project manager) tmux session: {sess}
The TUI pane ID is: {pane_id}

pm is a CLI tool for managing Claude Code development sessions. You can use \
it to manage PRs, plans, and the TUI. Run `pm --help` for the full command list.

Common tasks:
- `pm pr list` — list PRs and their status
- `pm pr add <title>` — add a new PR
- `pm pr start <pr-id>` — start working on a PR
- `pm pr done <pr-id>` — mark a PR as ready for review
- `pm plan list` — list plans
- `pm tui view -s {sess}` — capture the current TUI screen
- `pm tui send <keys> -s {sess}` — send keys to the TUI

The user will tell you what they need."""

    cmd = build_claude_shell_cmd(prompt=prompt)
    launch_pane(app, cmd, "claude")


def launch_help_claude(app) -> None:
    """Launch a beginner-friendly Claude assistant for the current project."""
    from pm_core.claude_launcher import find_claude, build_claude_shell_cmd
    claude = find_claude()
    if not claude:
        app.log_message("Claude CLI not found")
        return

    sess = app._session_name or "default"
    project = app._data.get("project", {})
    project_name = project.get("name", "unknown")
    repo = project.get("repo", "unknown")
    prs = app._data.get("prs") or []

    plans = app._data.get("plans") or []

    # Build a summary of current PRs with workdir info
    pr_lines = []
    for pr in prs:
        status = pr.get("status", "pending")
        title = pr.get("title", "???")
        pr_id = pr.get("id", "???")
        deps = pr.get("depends_on") or []
        dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
        wd = pr.get("workdir", "")
        wd_str = ""
        if wd:
            wd_path = Path(wd)
            if wd_path.exists():
                wd_str = f" workdir: {wd}"
            else:
                wd_str = f" workdir: {wd} (MISSING)"
        pr_lines.append(f"  - {pr_id}: {title} [{status}]{dep_str}{wd_str}")
    pr_summary = "\n".join(pr_lines) if pr_lines else "  (no PRs yet)"

    # Build a summary of plans
    plan_lines = []
    for plan in plans:
        plan_id = plan.get("id", "???")
        title = plan.get("title", "???")
        plan_lines.append(f"  - {plan_id}: {title}")
    plan_summary = "\n".join(plan_lines) if plan_lines else "  (no plans yet)"

    prompt = f"""\
## You are helping someone who may be a novice programmer decide on their \
next step.

## Project Info

Project: {project_name}
Repository: {repo}
tmux session: {sess}

Current plans:
{plan_summary}

Current PRs:
{pr_summary}

## pm Project Lifecycle

pm organizes work in a structured lifecycle:

1. **Initialize** (`pm init`): Set up pm for a codebase. This creates a \
pm/ directory that tracks plans and PRs.

2. **Plan** (`pm plan add`): Write a high-level plan describing a feature \
or goal. Plans are markdown files that describe what to build and why.

3. **Break down** (`pm plan breakdown <plan-id>`): Turn a plan into \
concrete PRs — small, focused units of work. PRs can depend on each other, \
forming a dependency tree shown in the TUI.

4. **Work** (select a PR and press `s` in the TUI): Start a PR to open a \
Claude session focused on that task. Claude works in a dedicated branch \
and directory.

5. **Review** (press `d` in the TUI or `pm pr done <pr-id>`): Mark a PR \
as done. This pushes the branch and creates a GitHub pull request for review.

6. **Merge**: After review, PRs get merged. pm detects this automatically \
and updates the tree.

At any point the user might need to: add new plans, add or reorder PRs, \
check on in-progress work, or understand what to tackle next.

## Your Task

Before making any recommendations, check the project's current health:

1. Run `pm pr list --workdirs` to see all PRs with their workdir paths and \
git status (clean/dirty/missing)
2. Run `pm plan list` to see existing plans

Then assess:
- Are there workdirs with uncommitted changes for merged PRs? (work that might be lost)
- Are there in-progress PRs that could be resumed?
- Are there PRs in review that might need attention?
- Are there pending PRs whose dependencies are all met?
- Are there plans that haven't been broken down yet?
- Is the dependency tree healthy?

Based on what you find, give the user clear, simple recommendations for \
what to do next. Suggest one or two concrete actions, not an overwhelming list. \
Prefer finishing in-progress work over starting new work."""

    cmd = build_claude_shell_cmd(prompt=prompt)
    launch_pane(app, cmd, "assist")


def launch_test(app, test_id: str) -> None:
    """Launch Claude with a TUI test prompt."""
    from pm_core import tui_tests
    from pm_core.claude_launcher import find_claude, build_claude_shell_cmd

    prompt = tui_tests.get_test_prompt(test_id)
    if not prompt:
        app.log_message(f"Test not found: {test_id}")
        return

    # Build session context (same pattern as cli.py tui_test command)
    sess = app._session_name or "default"
    pane_id = os.environ.get("TMUX_PANE", "")
    full_prompt = f"""\
## Session Context

You are testing against tmux session: {sess}
The TUI pane ID is: {pane_id}

To interact with this session, use commands like:
- pm tui view -s {sess}
- pm tui send <keys> -s {sess}
- tmux list-panes -t {sess} -F "#{{pane_id}} #{{pane_width}}x#{{pane_height}} #{{pane_current_command}}"
- cat ~/.pm-pane-registry/{sess}.json

{prompt}
"""

    cmd = build_claude_shell_cmd(prompt=full_prompt)
    launch_pane(app, cmd, "tui-test")


# ---------------------------------------------------------------------------
# Plan and test pane actions
# ---------------------------------------------------------------------------

def handle_plan_action(app, action: str, plan_id: str | None) -> None:
    """Handle plan action shortcuts that involve pane operations."""
    if action == "view":
        if plan_id:
            plan = store.get_plan(app._data, plan_id)
            if plan and app._root:
                plan_path = app._root / plan.get("file", "")
                if plan_path.exists():
                    launch_pane(app, f"less {plan_path}", "plan")
    elif action == "edit":
        if plan_id:
            plan = store.get_plan(app._data, plan_id)
            if plan and app._root:
                plan_path = app._root / plan.get("file", "")
                if plan_path.exists():
                    editor = find_editor()
                    launch_pane(app, f"{editor} {plan_path}", "plan-edit")
    elif action == "breakdown":
        if plan_id:
            launch_pane(app, f"pm plan breakdown {plan_id}", "plan-breakdown")
    elif action == "deps":
        launch_pane(app, "pm plan deps", "plan-deps")
    elif action == "load":
        if plan_id:
            launch_pane(app, f"pm plan load {plan_id}", "plan-load")
    elif action == "review":
        if plan_id:
            launch_pane(app, f"pm plan review {plan_id}", "plan-review")


def handle_plan_add(app, result: tuple[str, str] | None) -> None:
    """Handle result from PlanAddScreen modal."""
    if result is None:
        return
    name, description = result
    cmd = f"pm plan add {shlex.quote(name)}"
    if description:
        cmd += f" --description {shlex.quote(description)}"
    launch_pane(app, cmd, "plan-add")


def launch_plan_activated(app, plan_id: str) -> None:
    """Open a plan file in a pane (triggered by plan activation)."""
    _log.info("plan activated: %s", plan_id)
    plan = store.get_plan(app._data, plan_id)
    if not plan or not app._root:
        return
    plan_path = app._root / plan.get("file", "")
    if plan_path.exists():
        launch_pane(app, f"less {plan_path}", "plan")


# ---------------------------------------------------------------------------
# Connect and quit
# ---------------------------------------------------------------------------

def show_connect(app) -> None:
    """Show the tmux connect command for shared sessions."""
    socket_path = os.environ.get("PM_TMUX_SOCKET")
    if socket_path:
        command = f"tmux -S {socket_path} attach"
        app.push_screen(ConnectScreen(command))
    else:
        app.log_message("Not a shared session")
        app.set_timer(2, app._clear_log_message)


def quit_app(app) -> None:
    """Detach from tmux session instead of killing the TUI."""
    _log.info("quit_app")
    if tmux_mod.in_tmux():
        # Detach from tmux, leaving session running
        _run_shell(tmux_mod._tmux_cmd("detach-client"), check=False)
    else:
        # Not in tmux, just exit normally
        app.exit()


def restart_app(app) -> None:
    """Restart the TUI by exec'ing a fresh pm _tui process."""
    import sys
    import shutil
    _log.info("restart_app")
    app.exit()
    pm = shutil.which("pm")
    if pm:
        os.execvp(pm, [pm, "_tui"])
    else:
        os.execvp(sys.executable, [sys.executable, "-m", "pm_core.cli", "_tui"])
