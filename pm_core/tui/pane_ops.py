"""Pane launch, kill, rebalance, and related operations for the TUI.

All functions take the app instance as the first parameter so they can
access app state and call app methods (log_message, push_screen, etc.).
"""

import os
import shlex
from pathlib import Path

from pm_core.paths import configure_logger, command_log_file
from pm_core import tmux as tmux_mod
from pm_core import pane_layout, pane_registry
from pm_core import store, guide, notes
from pm_core.prompt_gen import tui_section
from pm_core.tui._shell import _run_shell
from pm_core.tui.screens import ConnectScreen

_log = configure_logger("pm.tui.pane_ops")


_REGRESSION_FILING_ADDENDUM = """
## Filing Findings

This regression test runs unattended. If you discover something worth
fixing while running it, file it as a separate PR so it doesn't get lost
— this is independent of your PASS / NEEDS_WORK / INPUT_REQUIRED verdict
for the test itself.

- **Bug** (failing assertion, incorrect behavior, regression):
  ```
  pm pr add '<short imperative title>' --plan bugs --description \
'<location, repro, expected vs actual>'
  ```
- **Improvement** (UX/quality issue surfaced incidentally — not a bug,
  but something that would make the product better):
  ```
  pm pr add '<short imperative title>' --plan ux --description \
'<what you noticed and why it matters>'
  ```

Skim `pm pr list --plan bugs` (or `--plan ux`) first to avoid filing a
duplicate. Filing is a side effect — your verdict for this regression
test must still reflect only the test's own pass/fail state.
"""


# ---------------------------------------------------------------------------
# Registry healing
# ---------------------------------------------------------------------------

def heal_registry(session: str | None) -> None:
    """Fix pane registry discrepancies on TUI startup.

    Heals all windows: removes dead panes, cleans empty window entries,
    and ensures the TUI pane is registered in the current window.
    """
    if not session or not tmux_mod.in_tmux():
        return

    tui_pane_id = os.environ.get("TMUX_PANE")
    if not tui_pane_id:
        return

    try:
        window = tmux_mod.get_window_id(session)
        if not window:
            return

        # Query all tmux state OUTSIDE the lock to avoid holding it
        # during subprocess calls (per IR3).
        reg_snapshot = pane_registry.load_registry(session)
        window_live_ids: dict[str, set[str]] = {}
        for win_id in list(reg_snapshot.get("windows", {})):
            live_panes = tmux_mod.get_pane_indices(session, win_id)
            window_live_ids[win_id] = {pid for pid, _ in live_panes}

        # Also query current window's live panes for TUI re-registration
        if window not in window_live_ids:
            live_panes = tmux_mod.get_pane_indices(session, window)
            window_live_ids[window] = {pid for pid, _ in live_panes}

        def _heal(raw):
            data = pane_registry._prepare_registry_data(raw, session)
            changed = False

            # Heal every window: remove dead panes, drop empty windows
            for win_id in list(data.get("windows", {})):
                live_ids = window_live_ids.get(win_id, set())
                wdata = data["windows"][win_id]

                # If no live panes returned for this window, it's gone
                if not live_ids:
                    if wdata["panes"]:
                        _log.info("heal_registry: window %s has no live panes, removing", win_id)
                        del data["windows"][win_id]
                        changed = True
                    continue

                before = len(wdata["panes"])
                wdata["panes"] = [p for p in wdata["panes"] if p["id"] in live_ids]
                removed = before - len(wdata["panes"])
                if removed:
                    _log.info("heal_registry: removed %d dead pane(s) from window %s", removed, win_id)
                    changed = True

                # Drop empty window entry
                if not wdata["panes"]:
                    del data["windows"][win_id]
                    changed = True

            # Ensure TUI pane is registered in the current window
            cur_live_ids = window_live_ids.get(window, set())
            if tui_pane_id in cur_live_ids:
                wdata = pane_registry.get_window_data(data, window)
                if not any(p["id"] == tui_pane_id for p in wdata["panes"]):
                    wdata["panes"].insert(0, {
                        "id": tui_pane_id,
                        "role": "tui",
                        "order": 0,
                        "cmd": "tui",
                    })
                    _log.info("heal_registry: re-registered TUI pane %s in window %s",
                              tui_pane_id, window)
                    changed = True

            if changed:
                _log.info("heal_registry: saved corrected registry")
                return data
            _log.info("heal_registry: registry OK")
            return None  # no changes, skip write

        pane_registry.locked_read_modify_write(
            pane_registry.registry_path(session), _heal)
    except Exception:
        _log.exception("heal_registry failed")


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


def launch_pane(app, cmd: str, role: str, fresh: bool = False,
                target_window: str | None = None) -> None:
    """Launch a wrapped pane, register it, and rebalance.

    If a pane with this role already exists and is alive, focuses it instead
    of creating a duplicate. When fresh=True, kills the existing pane first.

    When *target_window* is provided, the pane is launched (and dedup'd) in
    that tmux window rather than the TUI's current window. Used by watchers
    that need to keep launched sessions alongside their own work log.
    """
    info = get_session_and_window(app)
    if not info:
        return
    session, current_window = info
    window = target_window if target_window is not None else current_window
    _log.info("launch_pane: session=%s window=%s role=%s fresh=%s", session, window, role, fresh)

    # Check if a pane with this role already exists
    existing_pane = pane_registry.find_live_pane_by_role(session, role, window=window)
    _log.info("launch_pane: find_live_pane_by_role returned %s", existing_pane)
    if existing_pane:
        if fresh:
            _log.info("pane with role=%s exists: %s, killing (fresh)", role, existing_pane)
            pane_registry.kill_and_unregister(session, existing_pane)
        else:
            _log.info("pane with role=%s already exists: %s, focusing", role, existing_pane)
            tmux_mod.select_pane_smart(existing_pane, session, window)
            app.log_message(f"Focused existing {role} pane")
            return

    data = pane_registry.load_registry(session)
    gen = data.get("generation", "0")
    escaped = cmd.replace("'", "'\\''")
    wrap = f"bash -c 'trap \"pm _pane-exited {session} {window} {gen} $TMUX_PANE\" EXIT; {escaped}'"
    try:
        direction = pane_layout.preferred_split_direction(session, window)
        pane_id = tmux_mod.split_pane(session, direction, wrap, window=window)
        pane_layout.register_and_rebalance(session, window, [(pane_id, role, cmd)])
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

    def _reset_user_modified(raw):
        data = pane_registry._prepare_registry_data(raw, session)
        wdata = pane_registry.get_window_data(data, window)
        wdata["user_modified"] = False
        return data

    pane_registry.locked_read_modify_write(
        pane_registry.registry_path(session), _reset_user_modified)
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
    fresh = app._consume_z()
    _log.info("edit_plan fresh=%s", fresh)
    tree = app.query_one("#tech-tree", TechTree)
    pr_id = tree.selected_pr_id
    if not pr_id:
        app.log_message("No PR selected")
        return
    launch_pane(app, f"pm pr edit {pr_id}", "pr-edit", fresh=fresh)


def view_plan(app) -> None:
    """Open the plan file associated with the selected PR in a pane."""
    from pm_core.tui.tech_tree import TechTree
    fresh = app._consume_z()
    _log.info("view_plan fresh=%s", fresh)
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
    launch_pane(app, f"less {plan_path}", "plan", fresh=fresh)


# ---------------------------------------------------------------------------
# Pane launch actions
# ---------------------------------------------------------------------------

def launch_notes(app) -> None:
    """Launch the notes editor in a pane."""
    fresh = app._consume_z()
    _log.info("launch_notes fresh=%s", fresh)
    launch_pane(app, "pm notes", "notes", fresh=fresh)


def view_log(app) -> None:
    """View the TUI log file in a pane."""
    fresh = app._consume_z()
    _log.info("view_log fresh=%s", fresh)
    log_path = command_log_file()
    if not log_path.exists():
        app.log_message("No log file yet.")
        return
    launch_pane(app, f"tail -f {log_path}", "log", fresh=fresh)


def launch_meta(app) -> None:
    """Launch a meta-development session to work on pm itself.

    Auto-loads any new PRs from bugs.md and improvements.md into the meta
    workdir's project.yaml before launching.
    """
    app._consume_z()  # consume but meta doesn't support --fresh
    _log.info("launch_meta")
    from pm_core.tui.watcher_ui import load_watcher_plan_prs
    created = load_watcher_plan_prs(app)
    if created:
        app.log_message(f"Loaded {created} PR{'s' if created != 1 else ''} from watcher plans")
    app._run_command("meta")


def launch_guide(app) -> None:
    """Launch the guide (setup or assist depending on project state)."""
    fresh = app._consume_z()
    _log.info("launch_guide fresh=%s", fresh)
    launch_pane(app, "pm guide", "guide", fresh=fresh)


def launch_claude(app) -> None:
    """Launch an interactive Claude session in the project directory."""
    fresh = app._consume_z()
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

{tui_section(sess)}
## Read-only pm commands

These are safe to run directly — they only read state:
- `pm pr list` — list PRs and their status
- `pm plan list` — list plans
- `pm pr graph` — show the PR dependency tree

## Important: Use the TUI for actions that launch sessions

Do NOT run commands that launch new Claude sessions yourself (e.g. `pm pr start`, \
`pm pr done`, `pm plan add`, `pm plan breakdown`, `pm plan review`). These must be \
triggered through the TUI so that panes are managed correctly. Instead, tell the \
user which key to press in the TUI:
- `s` on a PR — start working on it
- `d` on a PR — mark it as done and start review
- `p` — toggle plans view, then `a`/`w`/`c`/`l` for plan actions

For plan management, recommend the user switch to the plans pane (`p` key) where \
they can use dedicated shortcuts rather than typing commands.

The user will tell you what they need."""

    cmd = build_claude_shell_cmd(prompt=prompt)
    launch_pane(app, cmd, "claude", fresh=fresh)


def launch_discuss(app) -> None:
    """Launch a Claude pane to discuss the pm tool and answer questions about it."""
    fresh = app._consume_z()
    _log.info("launch_discuss fresh=%s", fresh)
    from pm_core.claude_launcher import find_claude, build_claude_shell_cmd
    claude = find_claude()
    if not claude:
        app.log_message("Claude CLI not found")
        return

    prompt = """\
## You are helping someone learn about pm (project manager).

pm is a CLI tool and TUI for managing Claude Code development sessions. \
It organizes work into plans (high-level goals) and PRs (concrete units of work) \
with dependency tracking.

The user has questions about how pm works, its keyboard shortcuts, \
or what to do next.

Key concepts:
- **Plans**: High-level goals described in markdown files
- **PRs**: Concrete work items, organized in a dependency tree
- **TUI**: The interactive terminal UI showing the PR graph
- **Sessions**: tmux sessions with panes for Claude, editors, and more

Common keyboard shortcuts in the TUI:
- Arrow keys / hjkl: Navigate the PR tree
- s: Start working on a PR (launches Claude in a new window)
- d: Review PR (send for review)
- g: Merge PR
- e: Edit PR details
- c: Launch Claude session
- p: Toggle plans view
- ?: Show help
- /: Open command bar
- b: Rebalance panes
- q: Toggle QA instructions view
- t: Start QA on selected PR

Common commands:
- pm pr list: List all PRs
- pm pr start <id>: Start a PR
- pm pr review <id>: Send PR for review
- pm plan list: List plans
- pm plan add <name>: Add a new plan

Common problems:
- **Uppercase vs lowercase keys**: Some shortcuts require the Shift modifier. \
For example, `H` (Shift+h) launches the guide, while `h` navigates left. \
If a shortcut doesn't work, check whether it needs Shift. The help screen (?) \
shows which keys are uppercase.
- **Keys not working**: If key presses seem ignored, the command bar may be \
focused. Press Escape to return focus to the tree/plans view.
- **Pane layout looks wrong**: Press `b` to rebalance the pane layout.
- **Session seems stuck**: Press `Ctrl+R` to restart the TUI.

Ask the user what they'd like to know about."""

    cmd = build_claude_shell_cmd(prompt=prompt)
    launch_pane(app, cmd, "discuss", fresh=fresh)


def launch_watcher_review(app) -> None:
    """Launch a Claude session for chat-driven review of the watcher loops.

    Reads the three watcher work logs (discovery, bug-fix, improvement-fix)
    plus current PR/plan state, opens with a summary of recent activity,
    then is conversational. Read-mostly by default; write actions require
    explicit human confirmation.
    """
    fresh = app._consume_z()
    _log.info("launch_watcher_review fresh=%s", fresh)
    from pm_core.claude_launcher import find_claude, build_claude_shell_cmd
    from pm_core.prompt_gen import generate_watcher_review_prompt

    claude = find_claude()
    if not claude:
        app.log_message("Claude CLI not found")
        return

    # Resolve the meta workdir's pm/ root — that's where the watchers
    # actually write their logs (see generate_discovery_supervisor_prompt).
    # If it can't be ensured, fall back to the current project's pm/ dir
    # so the session still launches and reports missing logs gracefully.
    meta_pm_root: str | None = None
    try:
        from pm_core.cli.meta import ensure_meta_workdir
        meta_workdir = ensure_meta_workdir()
        meta_pm_root = str(meta_workdir / "pm")
    except Exception:
        _log.exception("launch_watcher_review: could not ensure meta workdir")
        if app._root:
            meta_pm_root = str(Path(app._root) / "pm")

    transcript_dir: str | None = None
    try:
        from pm_core.tui import auto_start
        tdir = auto_start.get_transcript_dir(app)
        if tdir:
            transcript_dir = str(tdir)
    except Exception:
        _log.exception("launch_watcher_review: could not resolve transcript dir")

    sess = app._session_name or "default"
    prompt = generate_watcher_review_prompt(
        session_name=sess,
        meta_pm_root=meta_pm_root,
        transcript_dir=transcript_dir,
    )

    cmd = build_claude_shell_cmd(prompt=prompt)
    launch_pane(app, cmd, "watcher-review", fresh=fresh)


def launch_qa_item(app, item_id: str, target_window: str | None = None) -> None:
    """Launch Claude with a QA instruction prompt.

    *item_id* has the form ``category:id`` (e.g. ``instructions:login-flow``
    or ``regression:pane-layout``).

    *target_window* optionally directs the launched pane into a specific
    tmux window. When omitted (e.g. the human Enter-key path from the QA
    pane), the pane opens in the TUI's current window.
    """
    from pm_core import qa_instructions
    from pm_core.claude_launcher import find_claude, build_claude_shell_cmd

    if not app._root:
        app.log_message("No project root")
        return

    parts = item_id.split(":", 1)
    if len(parts) != 2:
        app.log_message(f"Invalid QA item id: {item_id}")
        return
    category, qa_id = parts

    item = qa_instructions.get_instruction(app._root, qa_id, category=category)
    if not item:
        app.log_message(f"QA item not found: {item_id}")
        return

    sess = app._session_name or "default"
    pane_id = os.environ.get("TMUX_PANE", "")
    pane_line = f"\nThe TUI pane ID is: {pane_id}" if pane_id else ""
    body = item.get("body", "")
    title = item.get("title", qa_id)

    full_prompt = f"""\
## Session Context

You are running a QA instruction against tmux session: {sess}{pane_line}

To interact with this session, use commands like:
- pm tui view -s {sess}
- pm tui send <keys> -s {sess}
- tmux list-panes -t {sess} -F "#{{pane_id}} #{{pane_width}}x#{{pane_height}} #{{pane_current_command}}"
- cat ~/.pm/pane-registry/{sess}.json

## QA Instruction: {title}

{body}
"""

    if category == "regression":
        full_prompt += _REGRESSION_FILING_ADDENDUM

    cmd = build_claude_shell_cmd(prompt=full_prompt)
    launch_pane(app, cmd, "qa-item", target_window=target_window)


# ---------------------------------------------------------------------------
# Plan and test pane actions
# ---------------------------------------------------------------------------

def handle_plan_action(app, action: str, plan_id: str | None) -> None:
    """Handle plan action shortcuts that involve pane operations."""
    if action == "edit":
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
            app._run_command(f"plan load {plan_id}",
                             working_message="Loading PRs from plan")
    elif action == "review":
        if plan_id:
            launch_pane(app, f"pm plan review {plan_id}", "plan-review")


def handle_plan_add(app, result: tuple[str, str] | None) -> None:
    """Handle result from PlanAddScreen modal.

    The user enters a plan title or file path. The raw value is passed
    to ``pm plan add`` — the Claude session handles file resolution.
    """
    if result is None:
        return
    name, _description = result  # description is always empty now
    cmd = f"pm plan add {shlex.quote(name)}"
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
    """Restart the TUI by exec'ing a fresh pm _tui process.

    Uses os.execvp directly (no app.exit()) so the process is replaced
    in-place and the tmux pane stays alive — otherwise the last pane in
    a window would die before the new process starts.
    """
    import sys
    import shutil
    _log.info("restart_app")
    # Restore terminal state (raw mode, alt screen, etc.) before
    # replacing the process so the new TUI starts clean.
    try:
        app._driver.stop_application_mode()
    except Exception:
        pass  # new Textual app will reinitialize the terminal
    pm = shutil.which("pm")
    if pm:
        os.execvp(pm, [pm, "_tui"])
    else:
        os.execvp(sys.executable, [sys.executable, "-m", "pm_core.cli", "_tui"])
