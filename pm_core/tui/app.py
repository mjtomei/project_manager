"""Textual TUI App for Project Manager."""

import shlex
import subprocess
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Header, Footer, Static, Label

from pm_core import store, graph as graph_mod, git_ops, prompt_gen
from pm_core.tui.tech_tree import TechTree, PRSelected, PRActivated
from pm_core.tui.detail_panel import DetailPanel
from pm_core.tui.command_bar import CommandBar, CommandSubmitted


class StatusBar(Static):
    """Top status bar showing project info and sync state."""

    def update_status(self, project_name: str, repo: str, sync_state: str) -> None:
        sync_icons = {"synced": "[green]synced[/green]", "pulling": "[yellow]pulling...[/yellow]"}
        sync_display = sync_icons.get(sync_state, f"[red]{sync_state}[/red]")
        self.update(f" Project: [bold]{project_name}[/bold]    repo: [cyan]{repo}[/cyan]    [{sync_display}]")


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
    }
    LogLine {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    CommandBar {
        dock: bottom;
        height: 1;
    }
    TechTree {
        height: auto;
        width: auto;
        padding: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "start_pr", "Start PR", show=True),
        Binding("d", "done_pr", "Done PR", show=True),
        Binding("p", "copy_prompt", "Copy Prompt", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("slash", "focus_command", "Command", show=True),
    ]

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
        self._load_state()
        self._sync_timer = self.set_interval(30, self._background_sync)

    def _load_state(self) -> None:
        """Load project state from disk."""
        try:
            self._root = store.find_project_root()
            self._data = store.load(self._root)
            self._update_display()
        except FileNotFoundError:
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
        pr = store.get_pr(self._data, message.pr_id)
        detail = self.query_one("#detail-panel", DetailPanel)
        detail.update_pr(pr, self._data.get("prs"))
        self.log_message(f"Selected: {message.pr_id}")

    def on_pr_activated(self, message: PRActivated) -> None:
        pr = store.get_pr(self._data, message.pr_id)
        detail = self.query_one("#detail-panel", DetailPanel)
        detail.update_pr(pr, self._data.get("prs"))

    def on_command_submitted(self, message: CommandSubmitted) -> None:
        """Handle commands typed in the command bar."""
        self._run_command(message.command)
        tree = self.query_one("#tech-tree", TechTree)
        tree.focus()

    def _run_command(self, cmd: str) -> None:
        """Execute a pm sub-command."""
        parts = shlex.split(cmd)
        if not parts:
            return

        self.log_message(f"> {cmd}")

        try:
            # Run as subprocess so it goes through the full CLI
            result = subprocess.run(
                [sys.executable, "-m", "pm_core.cli"] + parts,
                cwd=str(self._root) if self._root else None,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                self.log_message(result.stdout.strip().split("\n")[-1])
            if result.returncode != 0 and result.stderr.strip():
                self.log_message(f"Error: {result.stderr.strip().split(chr(10))[-1]}")
        except Exception as e:
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

    def action_refresh(self) -> None:
        self._load_state()
        self.log_message("Refreshed")

    def action_focus_command(self) -> None:
        cmd_bar = self.query_one("#command-bar", CommandBar)
        cmd_bar.focus()
