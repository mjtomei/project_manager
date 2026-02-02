"""Textual TUI App for Project Manager."""

import logging
import os
import shlex
import subprocess
import sys
from pathlib import Path

_log_dir = Path.home() / ".pm-pane-registry"
_log_dir.mkdir(parents=True, exist_ok=True)
_handler = logging.FileHandler(_log_dir / "tui.log")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
_log = logging.getLogger("pm.tui")
_log.addHandler(_handler)
_log.setLevel(logging.DEBUG)

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Header, Footer, Static, Label

from pm_core import store, graph as graph_mod, git_ops, prompt_gen, notes
from pm_core.claude_launcher import find_claude, find_editor
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core.tui.tech_tree import TechTree, PRSelected, PRActivated
from pm_core.tui.detail_panel import DetailPanel
from pm_core.tui.command_bar import CommandBar, CommandSubmitted


class StatusBar(Static):
    """Top status bar showing project info and sync state."""

    def update_status(self, project_name: str, repo: str, sync_state: str) -> None:
        sync_icons = {"synced": "[green]synced[/green]", "pulling": "[yellow]pulling...[/yellow]"}
        sync_display = sync_icons.get(sync_state, f"[red]{sync_state}[/red]")
        from rich.markup import escape
        safe_repo = escape(repo)
        self.update(f" Project: [bold]{project_name}[/bold]    repo: [cyan]{safe_repo}[/cyan]    {sync_display}")


class LogLine(Static):
    """Single-line log output above the command bar."""
    pass


class ProjectManagerApp(App):
    """Interactive TUI for managing PR dependency graphs."""

    TITLE = "pm — Project Manager"

    CSS = """
    Screen {
        layout: vertical;
    }
    StatusBar {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
        margin-top: 1;
    }
    #main-area {
        height: 1fr;
    }
    #tree-container {
        width: 2fr;
        overflow: auto auto;
    }
    #detail-container {
        width: 1fr;
        min-width: 35;
        max-width: 50;
        display: none;
    }
    LogLine {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    CommandBar {
        dock: bottom;
        border: none;
        height: 1;
        margin-bottom: 1;
    }
    TechTree {
        height: auto;
        width: auto;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "start_pr", "Start PR", show=True),
        Binding("d", "done_pr", "Done PR", show=True),
        Binding("p", "copy_prompt", "Copy Prompt", show=True),
        Binding("c", "launch_claude", "Claude", show=True),
        Binding("e", "edit_plan", "Edit Plan", show=True),
        Binding("g", "launch_guide", "Guide", show=True),
        Binding("n", "launch_notes", "Notes", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("b", "rebalance", "Rebalance", show=True),
        Binding("ctrl+r", "restart", "Restart", show=False),
        Binding("slash", "focus_command", "Command", show=True),
        Binding("escape", "unfocus_command", "Back", show=False),
    ]

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Disable single-key shortcuts when command bar is focused."""
        if action in ("start_pr", "done_pr", "copy_prompt", "launch_claude",
                       "edit_plan", "launch_guide", "launch_notes", "refresh",
                       "rebalance", "quit"):
            cmd_bar = self.query_one("#command-bar", CommandBar)
            if cmd_bar.has_focus:
                _log.debug("check_action: blocked %s (command bar focused)", action)
                return False
        return True

    def __init__(self):
        super().__init__()
        self._data: dict = {}
        self._root: Path | None = None
        self._sync_timer: Timer | None = None
        self._detail_visible = False

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        with Horizontal(id="main-area"):
            with Vertical(id="tree-container"):
                yield TechTree(id="tech-tree")
            with Vertical(id="detail-container"):
                yield DetailPanel(id="detail-panel")
        yield LogLine(id="log-line")
        yield CommandBar(id="command-bar")

    def on_mount(self) -> None:
        _log.info("TUI mounted")
        self._load_state()
        self._sync_timer = self.set_interval(30, self._background_sync)

    def _load_state(self) -> None:
        """Load project state from disk."""
        try:
            self._root = store.find_project_root()
            self._data = store.load(self._root)
            _log.debug("loaded state from %s, %d PRs",
                       self._root, len(self._data.get("prs") or []))
            self._update_display()
        except FileNotFoundError:
            _log.warning("no project.yaml found")
            self.log_message("No project.yaml found. Run 'pm init' first.")

    def _update_display(self) -> None:
        """Refresh all widgets with current data."""
        if not self._data:
            return

        project = self._data.get("project", {})
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_status(
            project.get("name", "???"),
            project.get("repo", "???"),
            "synced",
        )

        tree = self.query_one("#tech-tree", TechTree)
        tree.update_prs(self._data.get("prs") or [])

    async def _background_sync(self) -> None:
        """Pull latest state from git."""
        if not self._root:
            return
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            project = self._data.get("project", {})
            status_bar.update_status(project.get("name", "???"), project.get("repo", "???"), "pulling")

            sync_status = git_ops.sync_state(self._root)
            self._data = store.load(self._root)
            self._update_display()

            status_bar.update_status(project.get("name", "???"), project.get("repo", "???"), sync_status)
        except Exception as e:
            self.log_message(f"Sync error: {e}")

    def log_message(self, msg: str) -> None:
        """Show a message in the log line."""
        try:
            log = self.query_one("#log-line", LogLine)
            log.update(f" {msg}")
        except Exception:
            pass

    # --- Message handlers ---

    def on_pr_selected(self, message: PRSelected) -> None:
        _log.debug("PR selected: %s", message.pr_id)
        pr = store.get_pr(self._data, message.pr_id)
        detail = self.query_one("#detail-panel", DetailPanel)
        detail.update_pr(pr, self._data.get("prs"))
        self.log_message(f"Selected: {message.pr_id}")

    def on_pr_activated(self, message: PRActivated) -> None:
        pr = store.get_pr(self._data, message.pr_id)
        detail = self.query_one("#detail-panel", DetailPanel)
        detail.update_pr(pr, self._data.get("prs"))
        container = self.query_one("#detail-container")
        container.styles.display = "block"

    def on_command_submitted(self, message: CommandSubmitted) -> None:
        """Handle commands typed in the command bar."""
        _log.info("command submitted: %s", message.command)
        self._run_command(message.command)
        tree = self.query_one("#tech-tree", TechTree)
        tree.focus()

    def _run_command(self, cmd: str) -> None:
        """Execute a pm sub-command."""
        parts = shlex.split(cmd)
        if not parts:
            return

        self.log_message(f"> {cmd}")
        _log.info("running command: %s", parts)

        try:
            # Run as subprocess so it goes through the full CLI
            result = subprocess.run(
                [sys.executable, "-m", "pm_core.cli"] + parts,
                cwd=str(self._root) if self._root else None,
                capture_output=True,
                text=True,
                timeout=30,
            )
            _log.debug("command exit=%d stdout=%r stderr=%r",
                       result.returncode, result.stdout[:200], result.stderr[:200])
            if result.stdout.strip():
                self.log_message(result.stdout.strip().split("\n")[-1])
            if result.returncode != 0 and result.stderr.strip():
                self.log_message(f"Error: {result.stderr.strip().split(chr(10))[-1]}")
        except Exception as e:
            _log.exception("command failed: %s", cmd)
            self.log_message(f"Error: {e}")

        # Reload state
        self._load_state()

    # --- Key actions ---

    def action_start_pr(self) -> None:
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if pr_id:
            self._run_command(f"pr start {pr_id}")

    def action_done_pr(self) -> None:
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if pr_id:
            self._run_command(f"pr done {pr_id}")

    def action_copy_prompt(self) -> None:
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if not pr_id:
            return
        try:
            prompt = prompt_gen.generate_prompt(self._data, pr_id)
            import pyperclip
            pyperclip.copy(prompt)
            self.log_message(f"Prompt for {pr_id} copied to clipboard")
        except ImportError:
            self.log_message("pyperclip not available — install it for clipboard support")
        except Exception as e:
            self.log_message(f"Clipboard error: {e}")

    def action_launch_claude(self) -> None:
        _log.info("action: launch_claude")
        if not tmux_mod.in_tmux():
            _log.warning("not in tmux")
            self.log_message("Not in tmux. Use 'pm session' to start a tmux session.")
            return
        if not find_claude():
            _log.warning("claude CLI not found")
            self.log_message("Claude CLI not found.")
            return
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if pr_id:
            try:
                prompt = prompt_gen.generate_prompt(self._data, pr_id)
                session_name = subprocess.run(
                    ["tmux", "display-message", "-p", "#{session_name}"],
                    capture_output=True, text=True
                ).stdout.strip()
                escaped = prompt.replace("'", "'\\''")
                tmux_mod.split_pane(session_name, "h", f"claude '{escaped}'")
                self.log_message(f"Launched Claude for {pr_id}")
            except Exception as e:
                self.log_message(f"Error: {e}")
        else:
            self.log_message("No PR selected")

    def action_edit_plan(self) -> None:
        _log.info("action: edit_plan")
        if not tmux_mod.in_tmux():
            self.log_message("Not in tmux. Use 'pm session' to start a tmux session.")
            return
        if not self._root:
            return
        # Find plan file for selected PR, or first plan
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        plan_path = None
        if pr_id:
            pr = store.get_pr(self._data, pr_id)
            if pr and pr.get("plan"):
                plan_entry = store.get_plan(self._data, pr["plan"])
                if plan_entry:
                    plan_path = self._root / plan_entry["file"]
        if not plan_path:
            plans = self._data.get("plans") or []
            if plans:
                plan_path = self._root / plans[0]["file"]
        if not plan_path or not plan_path.exists():
            self.log_message("No plan file found")
            return
        editor = find_editor()
        try:
            session_name = subprocess.run(
                ["tmux", "display-message", "-p", "#{session_name}"],
                capture_output=True, text=True
            ).stdout.strip()
            tmux_mod.split_pane(session_name, "h", f"{editor} {plan_path}")
            self.log_message(f"Opened {plan_path.name} in {editor}")
        except Exception as e:
            self.log_message(f"Error: {e}")

    def _get_session_and_window(self) -> tuple[str, str] | None:
        """Get tmux session name and window ID. Returns None if not in tmux."""
        if not tmux_mod.in_tmux():
            self.log_message("Not in tmux. Use 'pm session' to start a tmux session.")
            return None
        session = tmux_mod.get_session_name()
        window = tmux_mod.get_window_id(session)
        return session, window

    def _launch_pane(self, cmd: str, role: str) -> None:
        """Launch a wrapped pane, register it, and rebalance."""
        info = self._get_session_and_window()
        if not info:
            return
        session, window = info
        data = pane_layout.load_registry(session)
        gen = data.get("generation", "0")
        escaped = cmd.replace("'", "'\\''")
        wrap = f"bash -c 'trap \"pm _pane-exited {session} {window} {gen} $TMUX_PANE\" EXIT; {escaped}'"
        try:
            pane_id = tmux_mod.split_pane(session, "h", wrap)
            pane_layout.register_pane(session, window, pane_id, role, cmd)
            pane_layout.rebalance(session, window)
            tmux_mod.select_pane(pane_id)
            self.log_message(f"Launched {role} pane")
            _log.info("launched pane: role=%s id=%s", role, pane_id)
        except Exception as e:
            _log.exception("failed to launch %s pane", role)
            self.log_message(f"Error: {e}")

    def action_launch_guide(self) -> None:
        _log.info("action: launch_guide")
        self._launch_pane("pm guide", "guide")

    def action_launch_notes(self) -> None:
        _log.info("action: launch_notes")
        root = self._root or (Path.cwd() / "pm")
        notes_path = root / notes.NOTES_FILENAME
        self._launch_pane(f"pm notes {notes_path}", "notes")

    def action_rebalance(self) -> None:
        _log.info("action: rebalance")
        info = self._get_session_and_window()
        if not info:
            return
        session, window = info
        data = pane_layout.load_registry(session)
        data["user_modified"] = False
        pane_layout.save_registry(session, data)
        pane_layout.rebalance(session, window)
        self.log_message("Layout rebalanced")

    def action_refresh(self) -> None:
        self._load_state()
        self.log_message("Refreshed")

    def action_restart(self) -> None:
        """Restart the TUI by exec'ing a fresh pm tui process."""
        _log.info("action: restart")
        self.exit()
        import shutil
        pm = shutil.which("pm")
        if pm:
            os.execvp(pm, [pm, "tui"])
        else:
            os.execvp(sys.executable, [sys.executable, "-m", "pm_core.cli", "tui"])

    def action_focus_command(self) -> None:
        _log.debug("action: focus_command")
        cmd_bar = self.query_one("#command-bar", CommandBar)
        cmd_bar.focus()

    def action_unfocus_command(self) -> None:
        cmd_bar = self.query_one("#command-bar", CommandBar)
        if cmd_bar.has_focus:
            cmd_bar.value = ""
            tree = self.query_one("#tech-tree", TechTree)
            tree.focus()
