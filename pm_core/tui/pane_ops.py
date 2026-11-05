"""Pane launch, kill, rebalance, and related operations for the TUI.

All functions take the app instance as the first parameter so they can
access app state and call app methods (log_message, push_screen, etc.).
"""

import os
import shlex
from pathlib import Path

from pm_core.paths import configure_logger, command_log_file, default_socket_path
from pm_core import tmux as tmux_mod
from pm_core import pane_layout, pane_registry
from pm_core import store, guide, notes
from pm_core.prompt_gen import tui_section
from pm_core.tui.screens import ConnectScreen

_log = configure_logger("pm.tui.pane_ops")

# Lines of existing log history the L pane shows before following.
LOG_PANE_BACKLOG_LINES = 500
# Recent auto-start confirmations ("log: Auto-start: targets += X", "Auto-
# sequence armed for X", "Auto-merge: ...") repeated below the backlog, so
# they are on screen when L opens even after busy debug output (and other
# status messages) pushed them hundreds of lines up into scrollback.
LOG_PANE_RECAP_LINES = 8
LOG_PANE_RECAP_PATTERN = r"\[tui\] log: Auto-(start|sequence|merge)"
# Opening L writes its own burst of debug lines (split, pane-opened hook,
# rebalance, "launched pane") right after the pane starts; in a half-width
# split each wraps to two rows, so following immediately pushed the recap
# header off the top before the user saw it.  Let that burst land first and
# print it above the recap.
LOG_PANE_SETTLE_SECONDS = 1.0




# ---------------------------------------------------------------------------
# Registry healing
# ---------------------------------------------------------------------------

def heal_registry(session: str | None) -> None:
    """Fix pane registry discrepancies on TUI startup.

    Heals all windows: removes dead panes, cleans empty window entries,
    and ensures the TUI pane is registered in the window it actually
    lives in.
    """
    if not session or not tmux_mod.in_tmux():
        return

    tui_pane_id = os.environ.get("TMUX_PANE")
    if not tui_pane_id:
        return

    try:
        # Resolve the window from our own pane, not from the session's
        # active window: with a second client attached elsewhere (or a TUI
        # started by hand in another window) those differ, and the TUI
        # would never re-register itself.  Every CLI that resolves the
        # session through _find_tui_pane (pm tui view, pm autostart, ...)
        # then cannot find a live TUI.
        window = (tmux_mod.pane_window_id(tui_pane_id)
                  or tmux_mod.get_window_id(session))
        if not window:
            return

        # Query all tmux state OUTSIDE the lock to avoid holding it
        # during subprocess calls (per IR3).
        reg_snapshot = pane_registry.load_registry(session)
        window_live_ids: dict[str, set[str]] = {}
        for win_id in list(reg_snapshot.get("windows", {})):
            live_panes = tmux_mod.get_pane_indices(session, win_id)
            window_live_ids[win_id] = {pid for pid, _ in live_panes}

        # Also query our own window's live panes for TUI re-registration
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
            if (tui_pane_id in cur_live_ids
                    and pane_registry.register_tui_pane(data, window,
                                                        tui_pane_id)):
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

def _pm_session_for(app, raw_session: str | None = None) -> str | None:
    """Return the pm base session this TUI belongs to, or ``None``.

    tmux reports the most recently created session of a shared window for a
    pane, so while a user's own view of the session exists
    (``tmux new-session -t pm-x -s myview``, S118/S121/S124) — or a grouped
    session ``pm-x~N`` was created — the raw ``get_session_name()`` is the
    view's / grouped session's name.  The pane registry, pidfile and layout
    files are keyed by the *base* session, so a pane launch or rebalance
    through the raw name registers it in a phantom registry (``myview.json``)
    and the TUI never sees its own pane.  ``app._session_name`` is the
    canonical base name (``_session_for_claim`` derives it from
    ``current_session_name()``, which resolves the session group); fall back
    to tmux only when the app has no session yet.
    """
    session = getattr(app, "_session_name", None)
    if isinstance(session, str) and session:
        return session
    if raw_session is None:
        try:
            raw_session = tmux_mod.get_session_name()
        except OSError:
            # tmux missing/unexecutable: no session can be resolved.
            return None
    if not raw_session:
        return None
    try:
        return pane_registry.pm_session_name(raw_session)
    except OSError:
        # Same degrade as ``pm_core.cli.helpers._pm_session_of``: without a
        # group query the plain base name is the best answer available.
        return pane_registry.base_session_name(raw_session)


def get_session_and_window(app) -> tuple[str, str] | None:
    """Get the pm session name and the viewing window ID.

    The session is the *base* pm session (registry files are keyed by it);
    the window is the current window of the tmux session that reports the
    pane (a grouped session or a user's view keeps its own current window,
    which is the one the user is looking at).  Returns None if not in tmux.
    """
    if not tmux_mod.in_tmux():
        app.log_message("Not in tmux. Use 'pm session' to start a tmux session.")
        return None
    raw_session = tmux_mod.get_session_name()
    session = _pm_session_for(app, raw_session) or raw_session
    window = tmux_mod.get_window_id(raw_session)
    return session, window


def launch_pane(app, cmd: str, role: str, fresh: bool = False,
                target_window: str | None = None,
                env: dict[str, str] | None = None) -> None:
    """Launch a wrapped pane, register it, and rebalance.

    If a pane with this role already exists and is alive, focuses it instead
    of creating a duplicate. When fresh=True, kills the existing pane first.

    When *target_window* is provided, the pane is launched (and dedup'd) in
    that tmux window rather than the TUI's current window. Used by watchers
    that need to keep launched sessions alongside their own work log.

    *env* carries provider values; they are exported into the new pane's
    environment through a private file, so the values never appear in the
    command string.
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
            app.log_message(f"Focused existing {role} pane", force=True)
            return

    data = pane_registry.load_registry(session)
    gen = data.get("generation", "0")
    wrap = tmux_mod.wrap_with_exit_trap(cmd, session, window, gen)
    try:
        direction = pane_layout.preferred_split_direction(session, window)
        pane_id = tmux_mod.split_pane(session, direction, wrap, window=window,
                                      env=env)
        pane_layout.register_and_rebalance(session, window, [(pane_id, role, cmd)])
        tmux_mod.select_pane_smart(pane_id, session, window)
        # Forced: this answers the user's key, which may land while a
        # sticky message (e.g. "Review loop done") holds the line.
        app.log_message(f"Launched {role} pane", force=True)
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
    launch_pane(app, log_pane_command(log_path), "log", fresh=fresh)


def log_pane_command(log_path) -> str:
    """Shell command for the L pane: backlog, auto-start recap, then follow.

    Plain ``tail -f`` shows only the last 10 lines; the debug log is busy
    (pane layout, review-loop polling), so an "Auto-sequence armed" line
    mirrored a minute earlier sits hundreds of lines up — in scrollback, not
    on screen.  Show the backlog, wait for the pane's own launch lines and
    print them, repeat the last few auto-start confirmations ("HH:MM:SS log:
    ...") at the bottom, then follow from the line count taken last, so
    nothing written in between is lost.  No ``exec``: launch_pane's EXIT
    trap must still run.
    """
    f = shlex.quote(str(log_path))
    pattern = shlex.quote(LOG_PANE_RECAP_PATTERN)
    return (
        f'n=$(wc -l < {f}); '
        f'head -n "$n" {f} | tail -n {LOG_PANE_BACKLOG_LINES}; '
        f'sleep {LOG_PANE_SETTLE_SECONDS}; '
        f'm=$(wc -l < {f}); '
        f'head -n "$m" {f} | tail -n "+$((n + 1))"; '
        f'echo "── recent auto-start messages ──"; '
        f'head -n "$m" {f} | grep -E {pattern} | tail -n {LOG_PANE_RECAP_LINES}'
        f' | sed "s/ [A-Z]* *\\[tui\\] log: / log: /"; '
        f'echo "── following log ──"; '
        f'tail -n "+$((m + 1))" -f {f}'
    )


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

    env: dict[str, str] = {}
    cmd = build_claude_shell_cmd(prompt=prompt, session_type="discuss",
                                 env_out=env)
    launch_pane(app, cmd, "claude", fresh=fresh, env=env)


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

    env: dict[str, str] = {}
    cmd = build_claude_shell_cmd(prompt=prompt, session_type="discuss",
                                 env_out=env)
    launch_pane(app, cmd, "discuss", fresh=fresh, env=env)


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

    env: dict[str, str] = {}
    cmd = build_claude_shell_cmd(prompt=prompt, session_type="watcher_review",
                                 env_out=env)
    launch_pane(app, cmd, "watcher-review", fresh=fresh, env=env)


async def _launch_regression_item(app, qa_id: str,
                                  target_window: str | None,
                                  cmd: str | None = None) -> None:
    """Run regression test *qa_id* in a pane, unless it cannot launch.

    Same launcher as the CLI and ``pm qa launch``: ``pm qa regression`` runs
    the test in an isolated QA workdir (a QA container when container mode
    is enabled) against a disposable test project, never this TUI's session.
    What would stop it is logged here instead of flashing by in a pane that
    exits at once.  The check runs off the event loop: with container mode
    enabled it asks the runtime (``<runtime> info``, up to 10 s).

    *cmd* replaces the default ``pm qa regression <id> --file-prs`` command
    (the command bar runs the options the user typed).
    """
    import asyncio
    from pm_core.regression_prompts import (regression_launch_cmd,
                                            regression_launch_problem)
    problem = await asyncio.to_thread(regression_launch_problem,
                                      app._root, qa_id)
    if problem:
        app.log_message(problem.splitlines()[0])
        _log.warning("regression launch refused: %s", problem)
        return
    launch_pane(app, cmd or regression_launch_cmd(app._root, qa_id),
                "qa-item", target_window=target_window)


def launch_regression_command(app, args: list[str]) -> None:
    """Run ``qa regression <args>`` typed in the command bar in a pane.

    The command runs the test's interactive session in the foreground, so it
    needs a pane: the command bar's captured subprocess would block the TUI
    until its timeout, then kill the session before its container cleanup
    trap runs.  Same pre-launch check as the QA pane's Enter.
    """
    import click
    from pm_core.cli.qa import qa_regression
    from pm_core.regression_prompts import regression_command

    if not app._root:
        app.log_message("No project root")
        return
    # Parsed by the command itself, so the test id is the one
    # `pm qa regression` will run, and a malformed command (no test id, an
    # unknown option, an option missing its value) is reported here instead
    # of in a pane that exits at once.  Without a help option: `--help`
    # would print to the TUI's own stdout.
    try:
        ctx = qa_regression.make_context("qa regression", list(args),
                                         help_option_names=[])
    except click.UsageError as exc:
        app.log_message(
            f"qa regression: {exc.format_message()} Usage: qa regression "
            "<test-id> [--file-prs] [--branch <b>]")
        return
    app.run_worker(_launch_regression_item(
        app, ctx.params["test_id"], None,
        cmd=regression_command(app._root, list(args))), exclusive=False)


def launch_qa_item(app, item_id: str, target_window: str | None = None) -> None:
    """Launch Claude with a QA instruction prompt, or run a regression test.

    *item_id* has the form ``category:id`` (e.g. ``instructions:login-flow``
    or ``regression:auth-flow``).  A regression item runs
    ``pm qa regression <id> --file-prs`` in the pane (an isolated run, see
    :mod:`pm_core.regression_prompts`).

    *target_window* optionally directs the launched pane into a specific
    tmux window. When omitted (e.g. the human Enter-key path from the QA
    pane), the pane opens in the TUI's current window.
    """
    from pm_core import qa_instructions
    from pm_core.claude_launcher import build_claude_shell_cmd

    if not app._root:
        app.log_message("No project root")
        return

    parts = item_id.split(":", 1)
    if len(parts) != 2:
        app.log_message(f"Invalid QA item id: {item_id}")
        return
    category, qa_id = parts

    if category == "regression":
        app.run_worker(_launch_regression_item(app, qa_id, target_window),
                       exclusive=False)
        return

    item = qa_instructions.get_instruction(app._root, qa_id, category=category)
    if not item:
        app.log_message(f"QA item not found: {item_id}")
        return

    sess = app._session_name or "default"
    pane_id = os.environ.get("TMUX_PANE", "")
    pane_line = f"\nThe TUI pane ID is: {pane_id}" if pane_id else ""
    body = item.get("body", "")
    title = item.get("title", qa_id)

    # Copyable example commands: the session name may contain a space
    # (it comes from the repo directory), so quote it as one shell word.
    # shlex.quote leaves ordinary names bare.
    q_sess = shlex.quote(sess)
    full_prompt = f"""\
## Session Context

You are running a QA instruction against tmux session: {sess}{pane_line}

To interact with this session, use commands like:
- pm tui view -s {q_sess}
- pm tui send <keys> -s {q_sess}
- tmux list-panes -t {q_sess} -F "#{{pane_id}} #{{pane_width}}x#{{pane_height}} #{{pane_current_command}}"
- cat ~/.pm/pane-registry/{q_sess}.json

## QA Instruction: {title}

{body}
"""

    env: dict[str, str] = {}
    cmd = build_claude_shell_cmd(prompt=full_prompt, session_type="qa_author",
                                 env_out=env)
    launch_pane(app, cmd, "qa-item", target_window=target_window, env=env)


# ---------------------------------------------------------------------------
# Plan and test pane actions
# ---------------------------------------------------------------------------

PLANS_WINDOW_FALLBACK = "plans"


def _plans_window_name(plan_id: str | None) -> str:
    """Per-plan tmux window name = the plan id itself.

    All actions for the same plan share one window (different panes by role);
    different plans get different windows. Cross-plan actions (deps, plan add)
    pass synthetic ids like ``plan-deps`` / ``plan-add-<uuid>`` so they ride
    the same machinery without colliding.
    """
    return plan_id or PLANS_WINDOW_FALLBACK


def _focus_plans_window(app, plan_id: str | None) -> None:
    """Switch the user's grouped session to the per-plan window."""
    if not tmux_mod.in_tmux():
        return
    try:
        # The pm base, not the view/grouped name tmux reports for the pane:
        # select_window resolves the attached client's session from the
        # group, which it can only do from a real session name.
        session = _pm_session_for(app)
        if session:
            tmux_mod.select_window(session, _plans_window_name(plan_id))
    except Exception:
        _log.exception("_focus_plans_window failed")


def _wrap_pane_cmd(session: str, window: str, cmd: str) -> str:
    """Wrap a pane command with the EXIT trap that notifies pm of pane death.

    Delegates to ``tmux.wrap_with_exit_trap``, which escapes the session
    name and window for the trap's double-quoted context (a repo directory
    may contain a space or shell metacharacters; review-loop b48f i17).
    """
    data = pane_registry.load_registry(session)
    gen = data.get("generation", "0")
    return tmux_mod.wrap_with_exit_trap(cmd, session, window, gen)


def _launch_in_plans_window(app, plan_id: str | None, cmd: str, role: str,
                            fresh: bool = False) -> None:
    """Launch a pane in the per-plan window and switch focus to it.

    If the window doesn't exist yet, creates it with the wrapped command as
    its sole pane (no placeholder shell). If it exists, defers to
    :func:`launch_pane` which dedups by role and splits.
    """
    if not tmux_mod.in_tmux():
        # Not in tmux: fall back to current-window launch.
        launch_pane(app, cmd, role, fresh=fresh)
        return
    try:
        # Base session: the registry and the EXIT trap are keyed by it, and
        # a view name (S118/S121/S124) would create a phantom registry.
        session = _pm_session_for(app)
    except Exception:
        _log.exception("_launch_in_plans_window: session resolution failed")
        launch_pane(app, cmd, role, fresh=fresh)
        return
    if not session:
        launch_pane(app, cmd, role, fresh=fresh)
        return

    name = _plans_window_name(plan_id)
    try:
        win = tmux_mod.find_window_by_name(session, name)
    except Exception:
        _log.exception("_launch_in_plans_window: find_window_by_name failed")
        win = None

    if win:
        launch_pane(app, cmd, role, fresh=fresh, target_window=win["id"])
        _focus_plans_window(app, plan_id)
        return

    # Window doesn't exist — create it with the real command as the sole pane.
    cwd = str(app._root) if app._root else "."
    wrapped = _wrap_pane_cmd(session, name, cmd)
    try:
        pane_id = tmux_mod.new_window_get_pane(
            session, name, wrapped, cwd=cwd, switch=False,
        )
        win = tmux_mod.find_window_by_name(session, name)
        if pane_id and win:
            pane_layout.register_and_rebalance(
                session, win["id"], [(pane_id, role, cmd)])
            app.log_message(f"Launched {role} pane", force=True)
            _log.info("launched pane in new window: role=%s id=%s window=%s",
                      role, pane_id, name)
        _focus_plans_window(app, plan_id)
    except Exception as e:
        _log.exception("failed to launch %s pane in new window", role)
        app.log_message(f"Error: {e}")


# Synthetic plan ids for cross-plan actions that aren't tied to one plan.
# These ride the same per-plan window machinery so each cross-plan action gets
# its own dedicated window instead of fighting over a single shared "plans".
_DEPS_PSEUDO_PLAN_ID = "plan-deps"


def handle_plan_action(app, action: str, plan_id: str | None) -> None:
    """Handle plan action shortcuts that involve pane operations."""
    if action == "edit":
        if plan_id:
            plan = store.get_plan(app._data, plan_id)
            if plan and app._root:
                plan_path = app._root / plan.get("file", "")
                if plan_path.exists():
                    editor = find_editor()
                    _launch_in_plans_window(app, plan_id, f"{editor} {plan_path}", "plan-edit")
    elif action == "breakdown":
        if plan_id:
            _launch_in_plans_window(app, plan_id, f"pm plan breakdown {plan_id}", "plan-breakdown")
    elif action == "deps":
        # Cross-plan action: use a dedicated 'plans-deps' window.
        _launch_in_plans_window(app, _DEPS_PSEUDO_PLAN_ID, "pm plan deps", "plan-deps")
    elif action == "load":
        if plan_id:
            app._run_command(f"plan load {plan_id}",
                             working_message="Loading PRs from plan")
    elif action == "review":
        if plan_id:
            _launch_in_plans_window(app, plan_id, f"pm plan review {plan_id}", "plan-review")


def handle_plan_add(app, result: tuple[str, str] | None) -> None:
    """Handle result from PlanAddScreen modal.

    The user enters a plan title or file path. The raw value is passed
    to ``pm plan add`` — the Claude session handles file resolution.
    """
    if result is None:
        return
    name, _description = result  # description is always empty now
    cmd = f"pm plan add {shlex.quote(name)}"
    # generate_plan_id is sha256(name + description) so the TUI and the
    # spawned `pm plan add` process produce the same id — the window we open
    # here will be the same one the plan's later actions (edit, breakdown,
    # review) target, instead of a one-shot 'plan-add-<uuid>' window.
    existing_ids = {p["id"] for p in (app._data.get("plans") or [])}
    plan_id = store.generate_plan_id(name, existing_ids)
    _launch_in_plans_window(app, plan_id, cmd, "plan-add")


def launch_plan_activated(app, plan_id: str) -> None:
    """Open a plan file in a pane (triggered by plan activation)."""
    _log.info("plan activated: %s", plan_id)
    plan = store.get_plan(app._data, plan_id)
    if not plan or not app._root:
        return
    plan_path = app._root / plan.get("file", "")
    if plan_path.exists():
        _launch_in_plans_window(app, plan_id, f"less {plan_path}", "plan")


# ---------------------------------------------------------------------------
# Connect and quit
# ---------------------------------------------------------------------------

def show_connect(app) -> None:
    """Show the tmux connect command for this session's server."""
    socket_path = os.environ.get("PM_TMUX_SOCKET")
    session = getattr(app, "_session_name", None)
    target = ""
    if not socket_path and session:
        # No socket in the environment: a legacy (pre-isolation) session on
        # the default server, or a TUI started outside tmux.  Ask tmux which
        # server actually hosts it, and name the session explicitly for the
        # default server: a bare `tmux attach` follows $TMUX (the wrong
        # server when pasted into another pm pane), and one default server
        # can host several legacy pm sessions.  The lookup requires a
        # socket this user owns: the printed command is pasted into a
        # shell, and a socket another user planted under this session's
        # deterministic name would attach them to that server (a joiner's
        # shared session always has PM_TMUX_SOCKET in its environment, so
        # it never reaches this branch).
        hosting, on_private = tmux_mod.find_session_server(session,
                                                           owned_only=True)
        if hosting is not None:
            socket_path = hosting
            target = "" if on_private else f" -t {shlex.quote(session)}"
    elif socket_path and session:
        # The rollout path exports the *default* server's socket for a
        # legacy session, so the branch above never runs for one.  Name the
        # session there for the same reason: attaching to the default
        # server without `-t` picks whichever legacy session tmux considers
        # current.
        if socket_path == str(default_socket_path()):
            target = f" -t {shlex.quote(session)}"
    if socket_path:
        # Quoted: the command is meant to be pasted into a shell, and a
        # session tag derived from a repo directory name may contain a
        # space.  Normal paths are unchanged (shlex.quote leaves them bare).
        command = f"tmux -S {shlex.quote(socket_path)} attach{target}"
    elif session:
        command = f"tmux attach -t {shlex.quote(session)}"
    else:
        app.log_message("Not in a pm session")
        app.clear_log_message_later(2)
        return
    app.push_screen(ConnectScreen(command))


def quit_app(app) -> None:
    """Detach from tmux session instead of killing the TUI."""
    _log.info("quit_app")
    if tmux_mod.in_tmux():
        # Detach only the client viewing this pane's window, leaving the
        # session running.  Never use bare `detach-client`: it targets the
        # server's most recently active client and once detached the user
        # from a different pm session (pr-073910f).
        if not tmux_mod.detach_current_client():
            _log.info("quit_app: no attached client to detach")
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
    # execvp replaces the process without firing on_unmount, so flush any
    # pending writes here or the final in-memory mutations would be lost.
    wq = getattr(app, "_write_queue", None)
    if wq is not None:
        wq.flush_sync()
    # Restore terminal state (raw mode, alt screen, etc.) before
    # replacing the process so the new TUI starts clean.
    try:
        app._driver.stop_application_mode()
    except Exception:
        pass  # new Textual app will reinitialize the terminal
    # The pidfile keeps naming this pid across the exec, so CLI helpers
    # keep sending SIGUSR1/SIGUSR2; until the new TUI installs its
    # handlers the default action would kill it.  SIG_IGN survives exec;
    # queued commands are dispatched by the new TUI's startup drain.
    import signal
    for sig in (signal.SIGUSR1, signal.SIGUSR2):
        try:
            signal.signal(sig, signal.SIG_IGN)
        except (ValueError, OSError):
            pass
    pm = shutil.which("pm")
    if pm:
        os.execvp(pm, [pm, "_tui"])
    else:
        os.execvp(sys.executable, [sys.executable, "-m", "pm_core.cli", "_tui"])
