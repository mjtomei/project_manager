"""Textual TUI App for Project Manager."""

import json
import logging
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from pm_core.paths import configure_logger, debug_dir, command_log_file
_log = configure_logger("pm.tui")
_log_dir = debug_dir()


def _run_shell(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a shell command with logging.

    Logs the command before execution and result after.
    Passes through all kwargs to subprocess.run.
    """
    cmd_str = shlex.join(cmd) if isinstance(cmd, list) else cmd
    _log.info("shell: %s", cmd_str)
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        stderr = getattr(result, 'stderr', '')
        if stderr:
            _log.debug("shell failed (rc=%d): %s", result.returncode, stderr[:200])
    return result


async def _run_shell_async(cmd: list[str], **kwargs):
    """Run a shell command asynchronously with logging.

    Returns the process object for awaiting.
    """
    import asyncio
    cmd_str = shlex.join(cmd) if isinstance(cmd, list) else cmd
    _log.info("shell async: %s", cmd_str)
    return await asyncio.create_subprocess_exec(*cmd, **kwargs)


# Frame capture defaults
DEFAULT_FRAME_RATE = 1  # Record every change
DEFAULT_FRAME_BUFFER_SIZE = 100

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Header, Footer, Static, Label
from textual.screen import ModalScreen

from pm_core import store, graph as graph_mod, git_ops, notes, guide, pr_sync

from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core.tui.tech_tree import TechTree, PRSelected, PRActivated
from pm_core.tui.detail_panel import DetailPanel
from pm_core.tui.command_bar import CommandBar, CommandSubmitted
from pm_core.tui.guide_progress import GuideProgress
from pm_core.tui.plans_pane import PlansPane, PlanSelected, PlanActivated, PlanAction
from pm_core.tui.tests_pane import TestsPane, TestSelected, TestActivated
from pm_core.plan_parser import extract_plan_intro

# Guide steps that indicate setup is still in progress
GUIDE_SETUP_STEPS = {"no_project", "initialized", "has_plan_draft", "has_plan_prs", "needs_deps_review"}


class TreeScroll(ScrollableContainer, can_focus=False, can_focus_children=True):
    """Scrollable container for the tech tree."""

    DEFAULT_CSS = """
    TreeScroll {
        scrollbar-background: $surface-darken-1;
        scrollbar-color: $text-muted;
        scrollbar-color-hover: $text;
        scrollbar-color-active: $accent;
        scrollbar-size-vertical: 1;
    }
    """



class StatusBar(Static):
    """Top status bar showing project info and sync state."""

    def update_status(self, project_name: str, repo: str, sync_state: str,
                       pr_count: int = 0, filter_text: str = "") -> None:
        sync_icons = {
            "synced": "[green]synced[/green]",
            "pulling": "[yellow]pulling...[/yellow]",
            "no-op": "[dim]up to date[/dim]",
            "error": "[red]sync error[/red]",
        }
        sync_display = sync_icons.get(sync_state, f"[red]{sync_state}[/red]")
        from rich.markup import escape
        safe_repo = escape(repo)
        pr_info = f"[bold]{pr_count}[/bold] PRs" if pr_count else ""
        filter_display = f"    [dim]filter:[/dim] [italic]{filter_text}[/italic]" if filter_text else ""
        self.update(f" Project: [bold]{project_name}[/bold]    {pr_info}{filter_display}    repo: [cyan]{safe_repo}[/cyan]    {sync_display}")


class LogLine(Static):
    """Single-line log output above the command bar."""
    pass


class WelcomeScreen(ModalScreen):
    """Welcome popup shown when guide completes."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("enter", "dismiss", "Close"),
    ]

    CSS = """
    WelcomeScreen {
        align: center middle;
    }
    #welcome-container {
        width: 55;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $success;
        padding: 1 2;
    }
    #welcome-title {
        text-align: center;
        text-style: bold;
        color: $success;
        margin-bottom: 1;
    }
    .welcome-row {
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="welcome-container"):
            yield Label("Setup Complete!", id="welcome-title")
            yield Label("")
            yield Label("Your PRs are ready. Here's how to get started:", classes="welcome-row")
            yield Label("")
            yield Label("  [bold]↑↓←→[/] or [bold]jkl[/]  Navigate the PR tree", classes="welcome-row")
            yield Label("  [bold]s[/]  Start working on the selected PR", classes="welcome-row")
            yield Label("  [bold]c[/]  Launch Claude in a new pane", classes="welcome-row")
            yield Label("  [bold]e[/]  Edit PR details", classes="welcome-row")
            yield Label("  [bold]?[/]  Show all keyboard shortcuts", classes="welcome-row")
            yield Label("")
            yield Label("[dim]Press Enter or Esc to continue[/]", classes="welcome-row")

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class ConnectScreen(ModalScreen):
    """Modal popup showing the tmux connect command for shared sessions."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("c", "copy_and_dismiss", "Copy & close"),
    ]

    CSS = """
    ConnectScreen {
        align: center middle;
    }
    #connect-container {
        width: 70;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #connect-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #connect-command {
        margin: 1 0;
        padding: 1 2;
        background: $surface-darken-1;
        text-style: bold;
    }
    .connect-hint {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, command: str):
        super().__init__()
        self._command = command

    def compose(self) -> ComposeResult:
        with Vertical(id="connect-container"):
            yield Label("Connect Command", id="connect-title")
            yield Label(self._command, id="connect-command")
            yield Label("")
            yield Label("[dim]Press [bold]c[/bold] to copy to clipboard  |  [bold]Esc[/bold] to close[/]", classes="connect-hint")

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_copy_and_dismiss(self) -> None:
        copy_failed = False
        try:
            import pyperclip
            pyperclip.copy(self._command)
        except Exception:
            copy_failed = True
        self.app.pop_screen()
        if copy_failed:
            def _show_error() -> None:
                self.app.log_error(
                    "Copy failed:", "install xclip (apt install xclip) or xsel"
                )
            self.app.set_timer(0.1, _show_error)


class HelpScreen(ModalScreen):
    """Modal help screen showing available keybindings."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-container {
        width: 50;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #help-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    .help-section {
        margin-top: 1;
        text-style: bold;
        color: $primary;
    }
    .help-row {
        height: 1;
    }
    """

    def __init__(self, in_plans: bool = False, in_tests: bool = False):
        super().__init__()
        self._in_plans = in_plans
        self._in_tests = in_tests

    def compose(self) -> ComposeResult:
        with Vertical(id="help-container"):
            yield Label("Keyboard Shortcuts", id="help-title")
            if self._in_tests:
                yield Label("Test Navigation", classes="help-section")
                yield Label("  [bold]↑↓[/] or [bold]jk[/]  Move selection", classes="help-row")
                yield Label("  [bold]Enter[/]  Run selected test", classes="help-row")
                yield Label("  [bold]T[/]  Back to tree view", classes="help-row")
            elif self._in_plans:
                yield Label("Plan Navigation", classes="help-section")
                yield Label("  [bold]↑↓[/] or [bold]jk[/]  Move selection", classes="help-row")
                yield Label("  [bold]Enter/v[/]  View plan file", classes="help-row")
                yield Label("Plan Actions", classes="help-section")
                yield Label("  [bold]a[/]  Add a new plan", classes="help-row")
                yield Label("  [bold]e[/]  Edit plan file", classes="help-row")
                yield Label("  [bold]w[/]  Break plan into PRs", classes="help-row")
                yield Label("  [bold]c[/]  Review plan-PR consistency", classes="help-row")
                yield Label("  [bold]l[/]  Load PRs from plan", classes="help-row")
                yield Label("Cross-plan", classes="help-section")
                yield Label("  [bold]D[/]  Review PR dependencies", classes="help-row")
            else:
                yield Label("Tree Navigation", classes="help-section")
                yield Label("  [bold]↑↓←→[/] or [bold]jkl[/]  Move selection", classes="help-row")
                yield Label("  [bold]J/K[/]  Jump to next/prev plan", classes="help-row")
                yield Label("  [bold]H[/]  Hide/show plan group", classes="help-row")
                yield Label("  [bold]X[/]  Toggle merged PRs", classes="help-row")
                yield Label("  [bold]F[/]  Cycle status filter", classes="help-row")
                yield Label("  [bold]Enter[/]  Show PR details", classes="help-row")
                yield Label("PR Actions", classes="help-section")
                yield Label("  [bold]s[/]  Start selected PR", classes="help-row")
                yield Label("  [bold]S[/]  Start fresh (no resume)", classes="help-row")
                yield Label("  [bold]d[/]  Mark PR as done", classes="help-row")
                yield Label("  [bold]e[/]  Edit selected PR", classes="help-row")
                yield Label("  [bold]v[/]  View plan file", classes="help-row")
                yield Label("  [bold]M[/]  Move to plan", classes="help-row")
            yield Label("Panes & Views", classes="help-section")
            yield Label("  [bold]c[/]  Launch Claude session", classes="help-row")
            yield Label("  [bold]h[/]  Ask for help (beginner-friendly)", classes="help-row")
            yield Label("  [bold]/[/]  Open command bar", classes="help-row")
            yield Label("  [bold]g[/]  Toggle guide view", classes="help-row")
            yield Label("  [bold]n[/]  Open notes", classes="help-row")
            yield Label("  [bold]m[/]  Meta: work on pm itself", classes="help-row")
            yield Label("  [bold]L[/]  View TUI log", classes="help-row")
            yield Label("  [bold]P[/]  Toggle plans view", classes="help-row")
            yield Label("  [bold]T[/]  Toggle tests view", classes="help-row")
            yield Label("  [bold]b[/]  Rebalance panes", classes="help-row")
            yield Label("Other", classes="help-section")
            yield Label("  [bold]r[/]  Refresh / sync with GitHub", classes="help-row")
            yield Label("  [bold]C[/]  Show connect command (shared sessions)", classes="help-row")
            yield Label("  [bold]Ctrl+R[/]  Restart TUI", classes="help-row")
            yield Label("  [bold]?[/]  Show this help", classes="help-row")
            yield Label("  [bold]q[/]  Detach from session", classes="help-row")
            yield Label("")
            yield Label("[dim]Press Esc or ? to close[/]", classes="help-row")

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class PlanPickerScreen(ModalScreen):
    """Modal for picking a plan to assign to a PR."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    PlanPickerScreen {
        align: center middle;
    }
    #picker-container {
        width: 55;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #picker-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    .picker-row {
        height: 1;
    }
    #picker-input {
        display: none;
        margin-top: 1;
    }
    """

    def __init__(self, plans: list[dict], current_plan: str | None, pr_id: str):
        super().__init__()
        self._plans = plans
        self._current_plan = current_plan
        self._pr_id = pr_id
        self._selected = 0
        # Options: each plan + "No plan (standalone)" + "New plan..."
        self._options: list[tuple[str | None, str]] = []  # (plan_id_or_None, display_label)
        for p in plans:
            self._options.append((p["id"], f"{p['id']}: {p.get('name', '')}"))
        self._options.append(("_standalone", "No plan (standalone)"))
        self._options.append(("_new", "New plan..."))
        # Pre-select current plan
        for i, (pid, _) in enumerate(self._options):
            if pid == current_plan:
                self._selected = i
                break
        self._input_mode = False

    def compose(self) -> ComposeResult:
        from textual.widgets import Input
        with Vertical(id="picker-container"):
            yield Label(f"Move {self._pr_id} to plan:", id="picker-title")
            yield Label("", id="picker-options")
            yield Input(placeholder="Plan name", id="picker-input")
            yield Label("[dim]↑↓ navigate  Enter select  Esc cancel[/]", classes="picker-row")

    def on_mount(self) -> None:
        self._refresh_options()

    def _refresh_options(self) -> None:
        lines = []
        for i, (pid, label) in enumerate(self._options):
            is_current = (pid == self._current_plan) or (pid == "_standalone" and self._current_plan is None)
            marker = "●" if is_current else "○"
            pointer = "▸ " if i == self._selected else "  "
            style = "bold" if i == self._selected else ""
            lines.append(f"{pointer}{marker} {label}")
        options_label = self.query_one("#picker-options", Label)
        options_label.update("\n".join(lines))

    def on_key(self, event) -> None:
        if self._input_mode:
            return  # Let Input widget handle keys
        if event.key in ("up", "k"):
            self._selected = max(0, self._selected - 1)
            self._refresh_options()
            event.prevent_default()
            event.stop()
        elif event.key in ("down", "j"):
            self._selected = min(len(self._options) - 1, self._selected + 1)
            self._refresh_options()
            event.prevent_default()
            event.stop()
        elif event.key == "enter":
            pid, label = self._options[self._selected]
            if pid == "_new":
                self._enter_input_mode()
            else:
                self.dismiss(pid)
            event.prevent_default()
            event.stop()

    def _enter_input_mode(self) -> None:
        from textual.widgets import Input
        self._input_mode = True
        input_widget = self.query_one("#picker-input", Input)
        input_widget.styles.display = "block"
        input_widget.focus()

    def on_input_submitted(self, event) -> None:
        title = event.value.strip()
        if title:
            self.dismiss(("_new", title))
        else:
            self._input_mode = False
            event.input.styles.display = "none"

    def action_cancel(self) -> None:
        self.dismiss(None)


class PlanAddScreen(ModalScreen):
    """Modal for creating a new plan with name and optional description."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    PlanAddScreen {
        align: center middle;
    }
    #plan-add-container {
        width: 60;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #plan-add-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    .plan-add-label {
        margin-top: 1;
    }
    #plan-add-container Input {
        border: none;
        height: 1;
        padding: 0 1;
        background: #333333;
    }
    #plan-add-container Input:focus {
        background: #444444;
    }
    """

    def compose(self) -> ComposeResult:
        from textual.widgets import Input
        with Vertical(id="plan-add-container"):
            yield Label("New Plan", id="plan-add-title")
            yield Label("Name [dim](required)[/]", classes="plan-add-label")
            yield Input(placeholder="e.g. auth-refactor", id="plan-add-name")
            yield Label("Description [dim](optional)[/]", classes="plan-add-label")
            yield Input(placeholder="What should this plan accomplish?", id="plan-add-desc")
            yield Label("[dim]Tab between fields · Enter to create · Esc to cancel[/]")

    def on_mount(self) -> None:
        from textual.widgets import Input
        self.query_one("#plan-add-name", Input).focus()

    def on_input_submitted(self, event) -> None:
        from textual.widgets import Input
        name_input = self.query_one("#plan-add-name", Input)
        desc_input = self.query_one("#plan-add-desc", Input)
        if event.input is name_input:
            # Enter on name field: move to description
            desc_input.focus()
        elif event.input is desc_input:
            # Enter on description field: submit
            name = name_input.value.strip()
            if name:
                desc = desc_input.value.strip()
                self.dismiss((name, desc))

    def action_cancel(self) -> None:
        self.dismiss(None)


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
        layout: horizontal;
        height: 1fr;
    }
    #main-area.portrait {
        layout: vertical;
    }
    #tree-container {
        width: 2fr;
        height: 100%;
        overflow: auto auto;
    }
    #detail-container {
        width: 1fr;
        min-width: 35;
        max-width: 50;
        display: none;
        overflow-y: auto;
    }
    #detail-container.portrait {
        width: 100%;
        min-width: 0;
        max-width: 100%;
        height: 1fr;
        max-height: 40%;
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
    GuideProgress {
        height: auto;
        width: auto;
        padding: 1 2;
    }
    #guide-progress-container {
        width: 100%;
        height: 100%;
        display: none;
    }
    #plans-container {
        width: 100%;
        height: 100%;
        display: none;
        overflow: auto auto;
    }
    PlansPane {
        height: auto;
        width: auto;
        padding: 1 2;
    }
    #tests-container {
        width: 100%;
        height: 100%;
        display: none;
        overflow: auto auto;
    }
    TestsPane {
        height: auto;
        width: 1fr;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "start_pr", "Start PR", show=True),
        Binding("S", "start_pr_fresh", "Start Fresh", show=False),
        Binding("d", "done_pr", "Done PR", show=True),

        Binding("e", "edit_plan", "Edit PR", show=True),
        Binding("v", "view_plan", "View Plan", show=True),
        Binding("g", "toggle_guide", "Guide", show=True),
        Binding("n", "launch_notes", "Notes", show=True),
        Binding("m", "launch_meta", "Meta", show=True),
        Binding("L", "view_log", "Log", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("R", "reload", "Reload", show=False),
        Binding("b", "rebalance", "Rebalance", show=True),
        Binding("ctrl+r", "restart", "Restart", show=False),
        Binding("slash", "focus_command", "Command", show=True),
        Binding("escape", "unfocus_command", "Back", show=False),
        Binding("P", "toggle_plans", "Plans", show=True),
        Binding("T", "toggle_tests", "Tests", show=True),
        Binding("H", "hide_plan", "Hide Plan", show=False),
        Binding("M", "move_to_plan", "Move Plan", show=False),
        Binding("X", "toggle_merged", "Toggle Merged", show=False),
        Binding("F", "cycle_filter", "Filter", show=False),
        Binding("question_mark", "show_help", "Help", show=True),
        Binding("c", "launch_claude", "Claude", show=True),
        Binding("h", "launch_help_claude", "Assist", show=True),  # show toggled in __init__
        Binding("C", "show_connect", "Connect", show=False),
    ]

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Disable single-key shortcuts when command bar is focused or in guide mode."""
        if action in ("start_pr", "start_pr_fresh", "done_pr",
                       "edit_plan", "view_plan", "toggle_guide", "launch_notes",
                       "launch_meta", "launch_claude", "launch_help_claude",
                       "view_log", "refresh", "rebalance", "quit", "show_help",
                       "toggle_tests", "hide_plan", "move_to_plan", "toggle_merged", "cycle_filter"):
            cmd_bar = self.query_one("#command-bar", CommandBar)
            if cmd_bar.has_focus:
                _log.debug("check_action: blocked %s (command bar focused)", action)
                return False
        # Block PR actions when in guide mode or plans view (can't see the PR tree)
        if action in ("start_pr", "done_pr", "launch_claude", "edit_plan", "view_plan", "hide_plan", "move_to_plan", "toggle_merged", "cycle_filter"):
            if self._current_guide_step is not None:
                _log.debug("check_action: blocked %s (in guide mode)", action)
                return False
            if self._plans_visible:
                _log.debug("check_action: blocked %s (in plans view)", action)
                return False
            if self._tests_visible:
                _log.debug("check_action: blocked %s (in tests view)", action)
                return False
        return True

    def __init__(self):
        # Check global setting before super().__init__ processes bindings
        from pm_core.paths import get_global_setting
        if get_global_setting("hide-assist"):
            self.BINDINGS = [
                Binding(b.key, b.action, b.description,
                        show=False if b.action == "launch_help_claude" else b.show,
                        key_display=b.key_display, priority=b.priority)
                for b in self.BINDINGS
            ]
        super().__init__()
        self._data: dict = {}
        self._root: Path | None = None
        self._sync_timer: Timer | None = None
        self._detail_visible = False
        self._guide_auto_launched = False
        self._guide_dismissed = False
        self._current_guide_step: str | None = None
        self._welcome_shown = False
        self._plans_visible = False
        self._tests_visible = False
        # Frame capture state (always enabled)
        self._frame_rate: int = DEFAULT_FRAME_RATE
        self._frame_buffer_size: int = DEFAULT_FRAME_BUFFER_SIZE
        self._frame_buffer: list[dict] = []
        self._frame_change_count: int = 0
        self._last_frame_content: str | None = None
        self._session_name: str | None = None
        self._is_portrait: bool = False
        # In-flight PR action tracking (prevents concurrent/duplicate PR commands)
        self._inflight_pr_action: str | None = None

    # --- Frame capture methods ---

    def _get_capture_config_path(self) -> Path:
        """Get path to frame capture config file for this session."""
        session = self._session_name or "default"
        return _log_dir / f"{session}-capture.json"

    def _get_frames_path(self) -> Path:
        """Get path to captured frames file for this session."""
        session = self._session_name or "default"
        return _log_dir / f"{session}-frames.json"

    def _load_capture_config(self) -> None:
        """Load frame capture config from file (for dynamic updates)."""
        config_path = self._get_capture_config_path()
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                new_rate = config.get("frame_rate", DEFAULT_FRAME_RATE)
                new_size = config.get("buffer_size", DEFAULT_FRAME_BUFFER_SIZE)
                if new_rate != self._frame_rate or new_size != self._frame_buffer_size:
                    _log.debug("capture config updated: rate=%d, size=%d", new_rate, new_size)
                    self._frame_rate = new_rate
                    self._frame_buffer_size = new_size
                    # Trim buffer if size reduced
                    if len(self._frame_buffer) > self._frame_buffer_size:
                        self._frame_buffer = self._frame_buffer[-self._frame_buffer_size:]
                        self._save_frames()
            except (json.JSONDecodeError, OSError) as e:
                _log.warning("failed to load capture config: %s", e)

    def _capture_frame(self, trigger: str = "unknown") -> None:
        """Capture the current TUI frame if conditions are met.

        Args:
            trigger: Description of what triggered this capture (for debugging)
        """
        # Get current pane content via tmux
        if not tmux_mod.in_tmux():
            return

        try:
            pane_id = os.environ.get("TMUX_PANE", "")
            if not pane_id:
                return

            result = subprocess.run(
                tmux_mod._tmux_cmd("capture-pane", "-t", pane_id, "-p"),
                capture_output=True, text=True, timeout=5
            )
            content = result.stdout

            # Check if content actually changed
            if content == self._last_frame_content:
                return

            self._last_frame_content = content
            self._frame_change_count += 1

            # Only record every Nth change based on frame_rate
            if self._frame_change_count % self._frame_rate != 0:
                _log.debug("frame change %d skipped (rate=%d)",
                          self._frame_change_count, self._frame_rate)
                return

            # Add to buffer
            frame = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "change_number": self._frame_change_count,
                "trigger": trigger,
                "content": content,
            }
            self._frame_buffer.append(frame)

            # Trim buffer if needed
            if len(self._frame_buffer) > self._frame_buffer_size:
                self._frame_buffer = self._frame_buffer[-self._frame_buffer_size:]

            self._save_frames()
            _log.debug("frame %d captured (trigger=%s)", self._frame_change_count, trigger)

        except Exception as e:
            _log.warning("frame capture failed: %s", e)

    def _save_frames(self) -> None:
        """Save frame buffer to file."""
        try:
            frames_path = self._get_frames_path()
            frames_path.write_text(json.dumps({
                "frame_rate": self._frame_rate,
                "buffer_size": self._frame_buffer_size,
                "total_changes": self._frame_change_count,
                "frames": self._frame_buffer,
            }, indent=2))
        except OSError as e:
            _log.warning("failed to save frames: %s", e)

    def _on_guide_step_changed(self, step: str) -> None:
        """Called when guide progress step changes."""
        self.call_after_refresh(self._capture_frame, f"guide_step:{step}")

    def _on_tree_selection_changed(self, index: int) -> None:
        """Called when tech tree selection changes."""
        self.call_after_refresh(self._capture_frame, f"tree_selection:{index}")

    def _on_tree_prs_changed(self, prs: list) -> None:
        """Called when tech tree PR list changes."""
        self.call_after_refresh(self._capture_frame, f"tree_prs:{len(prs)}")

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        with Container(id="main-area"):
            with TreeScroll(id="tree-container"):
                yield TechTree(id="tech-tree")
            with Vertical(id="guide-progress-container"):
                yield GuideProgress(id="guide-progress")
            with Vertical(id="plans-container"):
                yield PlansPane(id="plans-pane")
            with Vertical(id="tests-container"):
                yield TestsPane(id="tests-pane")
            with Vertical(id="detail-container"):
                yield DetailPanel(id="detail-panel")
        yield LogLine(id="log-line")
        yield CommandBar(id="command-bar")

    def on_mount(self) -> None:
        _log.info("TUI mounted (cwd=%s)", Path.cwd())
        # Get session name for frame capture file naming
        if tmux_mod.in_tmux():
            try:
                result = _run_shell(
                    tmux_mod._tmux_cmd("display-message", "-p", "#{session_name}"),
                    capture_output=True, text=True, timeout=5
                )
                self._session_name = result.stdout.strip().split("~")[0]
            except Exception:
                pass
        # Load any existing capture config
        self._load_capture_config()
        # Set up watchers on child widgets for frame capture
        self._setup_frame_watchers()

        self._load_state()
        # Background sync interval: 5 minutes for automatic PR sync
        self._sync_timer = self.set_interval(300, self._background_sync)

        # Do a full GitHub sync on startup (non-blocking)
        self.run_worker(self._startup_github_sync())

        # Capture initial frame after state is loaded and rendered
        self.call_after_refresh(self._capture_frame, "mount")

        # Set initial layout orientation
        self._update_orientation()

    def on_resize(self) -> None:
        """Update layout orientation when terminal is resized."""
        self._update_orientation()

    def _update_orientation(self) -> None:
        """Switch main area between landscape/portrait based on terminal size."""
        # Textual char cells are ~2:1 aspect ratio, so compare width to height*2
        is_portrait = self.size.width < self.size.height * 2
        if is_portrait != self._is_portrait:
            self._is_portrait = is_portrait
            main_area = self.query_one("#main-area")
            detail = self.query_one("#detail-container")
            if is_portrait:
                main_area.add_class("portrait")
                detail.add_class("portrait")
            else:
                main_area.remove_class("portrait")
                detail.remove_class("portrait")
            _log.debug("orientation: %s (%dx%d)", "portrait" if is_portrait else "landscape",
                       self.size.width, self.size.height)

    def _setup_frame_watchers(self) -> None:
        """Set up watchers on child widgets to capture frames on change."""
        try:
            guide_widget = self.query_one("#guide-progress", GuideProgress)
            self.watch(guide_widget, "current_step", self._on_guide_step_changed)
        except Exception as e:
            _log.debug("could not watch guide-progress: %s", e)

        try:
            tree_widget = self.query_one("#tech-tree", TechTree)
            self.watch(tree_widget, "selected_index", self._on_tree_selection_changed)
            self.watch(tree_widget, "prs", self._on_tree_prs_changed)
        except Exception as e:
            _log.debug("could not watch tech-tree: %s", e)

    def _load_state(self) -> None:
        """Load project state from disk."""
        try:
            # Only search for root on first load; reuse existing root for refreshes
            if self._root is None:
                self._root = store.find_project_root()
                _log.info("found project root: %s", self._root)
            self._data = store.load(self._root)
            _log.debug("loaded state from %s, %d PRs",
                       self._root, len(self._data.get("prs") or []))
            self._update_display()
        except FileNotFoundError:
            _log.warning("no project.yaml found")
            self._root = None
            self._data = {}

        # Detect guide step and decide which view to show
        state, _ = guide.resolve_guide_step(self._root)
        if self._plans_visible:
            self._show_plans_view()
        elif self._tests_visible:
            self._show_tests_view()
        elif state in GUIDE_SETUP_STEPS and not self._guide_dismissed:
            self._show_guide_view(state)
        else:
            self._show_normal_view()

    def _show_guide_view(self, state: str) -> None:
        """Show the guide progress view during setup steps."""
        self._current_guide_step = state
        self._plans_visible = False
        self._tests_visible = False

        # Update guide progress widget
        guide_widget = self.query_one("#guide-progress", GuideProgress)
        guide_widget.update_step(state)

        # Show guide progress, hide tech tree, plans, and tests
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        tests_container = self.query_one("#tests-container")
        tree_container.styles.display = "none"
        guide_container.styles.display = "block"
        plans_container.styles.display = "none"
        tests_container.styles.display = "none"

        # Update status bar for guide mode
        status_bar = self.query_one("#status-bar", StatusBar)
        step_num = guide.step_number(state)
        total = len(GUIDE_SETUP_STEPS) + 1  # +1 for ready_to_work as the "done" state
        status_bar.update(f" [bold]pm Guide[/bold]    Step {step_num}/{total}: [cyan]{guide.STEP_DESCRIPTIONS.get(state, state)}[/cyan]    [dim]Press g to dismiss[/dim]")

        self.log_message(f"Guide step {step_num}/{total}: {guide.STEP_DESCRIPTIONS.get(state, state)}")

        # Auto-launch guide pane if in tmux and not already launched
        if not self._guide_auto_launched and tmux_mod.in_tmux():
            self._guide_auto_launched = True
            # Use call_later to launch after UI is ready
            self.call_later(self._auto_launch_guide)

        # Capture frame after view change (use call_after_refresh to ensure screen is updated)
        self.call_after_refresh(self._capture_frame, f"show_guide_view:{state}")

    def _auto_launch_guide(self) -> None:
        """Auto-launch the guide pane."""
        _log.info("auto-launching guide pane")
        self._launch_pane("pm guide", "guide")

    def _show_normal_view(self, from_guide: bool = False) -> None:
        """Show the normal tech tree view."""
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        tests_container = self.query_one("#tests-container")
        tree_container.styles.display = "block"
        guide_container.styles.display = "none"
        plans_container.styles.display = "none"
        tests_container.styles.display = "none"
        self._current_guide_step = None
        self._plans_visible = False
        self._tests_visible = False
        self.query_one("#tech-tree", TechTree).focus()
        # Capture frame after view change (use call_after_refresh to ensure screen is updated)
        self.call_after_refresh(self._capture_frame, "show_normal_view")
        # Show welcome popup when guide completes (only once)
        if from_guide and not self._welcome_shown:
            self._welcome_shown = True
            self.call_later(lambda: self.push_screen(WelcomeScreen()))

    def _update_display(self) -> None:
        """Refresh all widgets with current data."""
        if not self._data:
            return

        project = self._data.get("project", {})
        prs = self._data.get("prs") or []
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_status(
            project.get("name", "???"),
            project.get("repo", "???"),
            "synced",
            pr_count=len(prs),
        )

        tree = self.query_one("#tech-tree", TechTree)
        tree.update_plans(self._data.get("plans") or [])
        tree.update_prs(self._data.get("prs") or [])
        self._update_filter_status()

    async def _background_sync(self) -> None:
        """Pull latest state from git or check guide progress."""
        # Reload capture config in case it was updated via CLI
        self._load_capture_config()

        # If guide was dismissed, do normal sync
        if self._guide_dismissed:
            await self._do_normal_sync()
            return

        # Check current guide state
        try:
            self._root = store.find_project_root()
            self._data = store.load(self._root)
        except FileNotFoundError:
            self._root = None
            self._data = {}

        state, _ = guide.resolve_guide_step(self._root)

        # If we're in guide mode, check for state changes
        if self._current_guide_step is not None:
            if state not in GUIDE_SETUP_STEPS:
                # Guide is complete, switch to normal view
                if self._data:
                    self._update_display()
                self._show_normal_view(from_guide=True)
                self.log_message("Guide complete! Showing tech tree.")
            elif state != self._current_guide_step:
                # Step changed, update the guide view
                self._show_guide_view(state)
            return

        # Not in guide mode - do normal sync
        await self._do_normal_sync()

    async def _do_normal_sync(self, is_manual: bool = False) -> None:
        """Perform normal PR sync to detect merged PRs.

        Args:
            is_manual: True if triggered by user (r key), False for periodic background sync
        """
        if not self._root:
            return
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            project = self._data.get("project", {})
            prs = self._data.get("prs") or []
            status_bar.update_status(project.get("name", "???"), project.get("repo", "???"), "pulling", pr_count=len(prs))

            # Use shorter interval for manual refresh, longer for background
            min_interval = (
                pr_sync.MIN_SYNC_INTERVAL_SECONDS if is_manual
                else pr_sync.MIN_BACKGROUND_SYNC_INTERVAL_SECONDS
            )

            # Perform PR sync to detect merged PRs
            result = pr_sync.sync_prs(
                self._root,
                self._data,
                min_interval_seconds=min_interval,
            )

            # Reload data after sync
            self._data = store.load(self._root)
            self._update_display()

            prs = self._data.get("prs") or []

            # Determine sync status message
            if result.was_skipped:
                sync_status = "no-op"
                if is_manual:
                    self.log_message("Already up to date")
            elif result.error:
                # "No workdirs" is not really an error - just nothing to sync yet
                if "No workdirs" in result.error:
                    sync_status = "no-op"
                    _log.debug("PR sync: %s", result.error)
                else:
                    sync_status = "error"
                    _log.warning("PR sync error: %s", result.error)
                    self.log_message(f"Sync error: {result.error}")
            elif result.updated_count > 0:
                sync_status = "synced"
                self.log_message(f"Synced: {result.updated_count} PR(s) merged")
            else:
                sync_status = "synced"
                if is_manual:
                    self.log_message("Refreshed")

            status_bar.update_status(project.get("name", "???"), project.get("repo", "???"), sync_status, pr_count=len(prs))

            # Clear log message after 1 second for manual refresh
            if is_manual:
                self.set_timer(1.0, self._clear_log_message)
        except Exception as e:
            _log.exception("Sync error")
            self.log_message(f"Sync error: {e}")

    def log_message(self, msg: str, capture: bool = True) -> None:
        """Show a message in the log line."""
        try:
            log = self.query_one("#log-line", LogLine)
            log.update(f" {msg}")
        except Exception:
            pass
        if capture:
            truncated = msg[:60].replace("\n", " ")
            self.call_after_refresh(self._capture_frame, f"log_message:{truncated}")

    def log_error(self, title: str, detail: str = "", timeout: float = 5) -> None:
        """Show a red error in the log line that auto-clears.

        Args:
            title: Short error summary (shown in red bold).
            detail: Optional extra context (shown in normal style).
            timeout: Seconds before the message auto-clears.
        """
        msg = f"[red bold]{title}[/]"
        if detail:
            msg += f" {detail}"
        self.log_message(msg)
        self.set_timer(timeout, self._clear_log_message)

    def _clear_log_message(self) -> None:
        """Clear the log line message."""
        try:
            log = self.query_one("#log-line", LogLine)
            log.update("")
        except Exception:
            pass

    async def _startup_github_sync(self) -> None:
        """Perform a full GitHub API sync on startup.

        This fetches actual PR state from GitHub (merged, closed, draft status)
        rather than just checking git merge status.
        """
        if not self._root:
            return

        backend_name = self._data.get("project", {}).get("backend", "vanilla")
        if backend_name != "github":
            return

        try:
            self.log_message("Syncing with GitHub...")
            result = pr_sync.sync_from_github(self._root, self._data, save_state=True)

            if result.synced and result.updated_count > 0:
                # Reload data after sync
                self._data = store.load(self._root)
                self._update_display()
                self.log_message(f"GitHub sync: {result.updated_count} PR(s) updated")
            elif result.error:
                _log.warning("GitHub sync error: %s", result.error)
            else:
                self.log_message("GitHub sync: up to date")

            self.set_timer(2.0, self._clear_log_message)
        except Exception as e:
            _log.exception("GitHub sync error")
            self.log_message(f"GitHub sync error: {e}")
            self.set_timer(3.0, self._clear_log_message)

    # --- Message handlers ---

    def _get_plan_for_pr(self, pr: dict | None) -> dict | None:
        """Look up the plan entry for a PR, if any."""
        if not pr or not pr.get("plan"):
            return None
        return store.get_plan(self._data, pr["plan"])

    def on_prselected(self, message: PRSelected) -> None:
        _log.debug("PR selected: %s", message.pr_id)
        pr = store.get_pr(self._data, message.pr_id)
        plan = self._get_plan_for_pr(pr)
        detail = self.query_one("#detail-panel", DetailPanel)
        detail.update_pr(pr, self._data.get("prs"), plan=plan, project_root=self._root)
        self.log_message(f"Selected: {message.pr_id}")
        self.call_after_refresh(self._capture_frame, f"pr_selected:{message.pr_id}")

    def on_practivated(self, message: PRActivated) -> None:
        pr = store.get_pr(self._data, message.pr_id)
        plan = self._get_plan_for_pr(pr)
        detail = self.query_one("#detail-panel", DetailPanel)
        detail.update_pr(pr, self._data.get("prs"), plan=plan, project_root=self._root)
        container = self.query_one("#detail-container")
        container.styles.display = "block"
        self._detail_visible = True
        self.call_after_refresh(self._capture_frame, f"pr_activated:{message.pr_id}")

    # PR command prefixes that require in-flight action guarding
    _PR_ACTION_PREFIXES = ("pr start", "pr done")

    def on_command_submitted(self, message: CommandSubmitted) -> None:
        """Handle commands typed in the command bar."""
        _log.info("command submitted: %s", message.command)
        cmd = message.command.strip()

        # Guard PR action commands from the command bar too
        action_key = None
        for prefix in self._PR_ACTION_PREFIXES:
            if cmd.startswith(prefix):
                action_key = cmd
                if not self._guard_pr_action(action_key):
                    if self._plans_visible:
                        self.query_one("#plans-pane", PlansPane).focus()
                    else:
                        self.query_one("#tech-tree", TechTree).focus()
                    return
                self._inflight_pr_action = action_key
                break

        # Commands that launch interactive Claude sessions need a tmux pane
        parts = shlex.split(cmd)
        if len(parts) >= 3 and parts[0] == "plan" and parts[1] == "add":
            self._launch_pane(f"pm {cmd}", "plan-add")
            self._load_state()
        else:
            # Detect if this should run async (PR commands are long-running)
            working_message = None
            if cmd.startswith("pr start"):
                pr_id = parts[-1] if len(parts) >= 3 else "PR"
                working_message = f"Starting {pr_id}"
            elif cmd.startswith("pr done"):
                pr_id = parts[-1] if len(parts) >= 3 else "PR"
                working_message = f"Completing {pr_id}"

            self._run_command(cmd, working_message=working_message, action_key=action_key)
        if self._plans_visible:
            self.query_one("#plans-pane", PlansPane).focus()
        else:
            self.query_one("#tech-tree", TechTree).focus()

    def _run_command(self, cmd: str, working_message: str | None = None,
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
            self.run_worker(self._run_command_async(cmd, parts, working_message, action_key))
        else:
            # Run sync for quick commands
            self.log_message(f"> {cmd}")
            self._run_command_sync(parts)
            if action_key:
                self._inflight_pr_action = None

    def _run_command_sync(self, parts: list[str]) -> None:
        """Run a command synchronously (for quick operations)."""
        try:
            cmd = [sys.executable, "-m", "pm_core.wrapper"] + parts
            result = _run_shell(
                cmd,
                cwd=str(self._root) if self._root else None,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                _log.info("pm exit=%d stderr=%s",
                          result.returncode, result.stderr.strip()[:200])
            if result.stdout.strip():
                self.log_message(result.stdout.strip().split("\n")[-1])
            if result.returncode != 0 and result.stderr.strip():
                self.log_message(f"Error: {result.stderr.strip().split(chr(10))[-1]}")
        except Exception as e:
            _log.exception("command failed: %s", parts)
            self.log_message(f"Error: {e}")

        # Reload state
        self._load_state()

    async def _run_command_async(self, cmd: str, parts: list[str], working_message: str,
                                action_key: str | None = None) -> None:
        """Run a command asynchronously with animated spinner."""
        import asyncio
        import itertools

        cwd = str(self._root) if self._root else None
        full_cmd = [sys.executable, "-m", "pm_core.wrapper"] + list(parts)

        spinner_frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        spinner_running = True

        def update_spinner() -> None:
            if spinner_running:
                frame = next(spinner_frames)
                self.log_message(f"{frame} {working_message}...", capture=False)
                self.set_timer(0.1, update_spinner)

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
                self.log_message(stdout_text.strip().split("\n")[-1])
            elif proc.returncode == 0:
                self.log_message(f"✓ {working_message} done")
            if proc.returncode != 0 and stderr_text.strip():
                self.log_message(f"Error: {stderr_text.strip().split(chr(10))[-1]}")

        except asyncio.TimeoutError:
            spinner_running = False
            _log.exception("command timed out: %s", cmd)
            self.log_message(f"Error: Command timed out")
        except Exception as e:
            spinner_running = False
            _log.exception("command failed: %s", cmd)
            self.log_message(f"Error: {e}")
        finally:
            if action_key:
                self._inflight_pr_action = None

        # Reload state
        self._load_state()

    # --- Key actions ---

    def _guard_pr_action(self, action_desc: str) -> bool:
        """Check if a PR action is allowed (no conflicting action in-flight).

        Returns True if the action can proceed, False if blocked.
        Shows a status message when blocked.
        """
        if self._inflight_pr_action:
            _log.info("action blocked: %s (busy: %s)", action_desc, self._inflight_pr_action)
            self.log_message(f"Busy: {self._inflight_pr_action}")
            return False
        return True

    def action_start_pr(self) -> None:
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        _log.info("action: start_pr selected=%s", pr_id)
        if not pr_id:
            _log.info("action: start_pr - no PR selected")
            self.log_message("No PR selected")
            return
        action_key = f"Starting {pr_id}"
        if not self._guard_pr_action(action_key):
            return
        self._inflight_pr_action = action_key
        self._run_command(f"pr start {pr_id}", working_message=action_key, action_key=action_key)

    def action_start_pr_fresh(self) -> None:
        """Start PR with fresh Claude session (no resume)."""
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        _log.info("action: start_pr_fresh selected=%s", pr_id)
        if not pr_id:
            self.log_message("No PR selected")
            return
        action_key = f"Starting {pr_id} (fresh)"
        if not self._guard_pr_action(action_key):
            return
        self._inflight_pr_action = action_key
        self._run_command(f"pr start --new {pr_id}", working_message=action_key, action_key=action_key)

    def action_hide_plan(self) -> None:
        """Toggle hiding the selected PR's plan group.

        If selected on a hidden label: unhide that plan.
        If selected on a normal PR: hide its plan.
        If no selection: unhide all.
        """
        tree = self.query_one("#tech-tree", TechTree)

        # Check if selected node is a hidden label
        if tree.selected_is_hidden_label:
            plan_id = tree.get_selected_plan()
            if plan_id:
                tree._hidden_plans.discard(plan_id)
                tree._recompute()
                tree.refresh(layout=True)
                self.log_message(f"Showing: {tree.get_plan_display_name(plan_id)}")
            return

        plan_id = tree.get_selected_plan()
        if plan_id is None:
            # No selection (all hidden) — unhide all
            tree._hidden_plans.clear()
            tree._recompute()
            tree.refresh(layout=True)
            self.log_message("All plans visible")
            return
        if plan_id in tree._hidden_plans:
            tree._hidden_plans.discard(plan_id)
            tree._recompute()
            tree.refresh(layout=True)
            self.log_message(f"Showing: {tree.get_plan_display_name(plan_id)}")
        else:
            tree._hidden_plans.add(plan_id)
            tree._recompute()
            tree.refresh(layout=True)
            self.log_message(f"Hidden: {tree.get_plan_display_name(plan_id)}")

    def action_toggle_merged(self) -> None:
        """Toggle hiding/showing of merged PRs."""
        tree = self.query_one("#tech-tree", TechTree)
        tree._hide_merged = not tree._hide_merged
        tree._recompute()
        tree.refresh(layout=True)
        self._update_filter_status()
        if tree._hide_merged:
            self.log_message("Merged PRs hidden")
        else:
            self.log_message("Merged PRs shown")

    def action_cycle_filter(self) -> None:
        """Cycle through status filters: all → pending → in_progress → ..."""
        from pm_core.tui.tech_tree import STATUS_FILTER_CYCLE, STATUS_ICONS
        tree = self.query_one("#tech-tree", TechTree)
        current = tree._status_filter
        try:
            idx = STATUS_FILTER_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_idx = (idx + 1) % len(STATUS_FILTER_CYCLE)
        tree._status_filter = STATUS_FILTER_CYCLE[next_idx]
        tree._recompute()
        tree.refresh(layout=True)
        self._update_filter_status()
        if tree._status_filter:
            icon = STATUS_ICONS.get(tree._status_filter, "")
            self.log_message(f"Filter: {icon} {tree._status_filter}")
        else:
            self.log_message("Filter: all")

    def _update_filter_status(self) -> None:
        """Update the status bar to reflect active filters."""
        from pm_core.tui.tech_tree import STATUS_ICONS
        if not self._data:
            return
        tree = self.query_one("#tech-tree", TechTree)
        project = self._data.get("project", {})
        prs = self._data.get("prs") or []
        filter_text = ""
        if tree._status_filter:
            icon = STATUS_ICONS.get(tree._status_filter, "")
            filter_text = f"{icon} {tree._status_filter}"
        elif tree._hide_merged:
            filter_text = "hide merged"
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_status(
            project.get("name", "???"),
            project.get("repo", "???"),
            "synced",
            pr_count=len(prs),
            filter_text=filter_text,
        )

    def action_move_to_plan(self) -> None:
        """Open plan picker to move selected PR to a different plan."""
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if not pr_id:
            self.log_message("No PR selected")
            return
        pr = store.get_pr(self._data, pr_id)
        if not pr:
            self.log_message("PR not found")
            return
        plans = self._data.get("plans") or []
        current_plan = pr.get("plan") or None
        self.push_screen(
            PlanPickerScreen(plans, current_plan, pr_id),
            callback=lambda result: self._handle_plan_pick(pr_id, result),
        )

    def _handle_plan_pick(self, pr_id: str, result) -> None:
        """Handle the result from PlanPickerScreen."""
        if result is None:
            return  # Cancelled
        pr = store.get_pr(self._data, pr_id)
        if not pr:
            return

        if isinstance(result, tuple) and result[0] == "_new":
            # Create a new plan
            _, title = result
            plan_id = store.next_plan_id(self._data)
            plan_file = f"plans/{plan_id}.md"
            entry = {"id": plan_id, "name": title, "file": plan_file, "status": "draft"}
            if self._data.get("plans") is None:
                self._data["plans"] = []
            self._data["plans"].append(entry)
            # Create plan file
            if self._root:
                plan_path = self._root / plan_file
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                plan_path.write_text(f"# {title}\n\n<!-- Describe the plan here -->\n")
            pr["plan"] = plan_id
            store.save(self._data, self._root)
            self._load_state()
            self.log_message(f"Moved {pr_id} → {plan_id}: {title} (new)")
        elif result == "_standalone":
            # Remove plan assignment
            old_plan = pr.get("plan")
            if not old_plan:
                self.log_message("Already standalone")
                return
            pr.pop("plan", None)
            store.save(self._data, self._root)
            self._load_state()
            self.log_message(f"Moved {pr_id} → Standalone")
        elif isinstance(result, str):
            # Existing plan selected
            old_plan = pr.get("plan")
            if result == old_plan:
                self.log_message("Already in that plan")
                return
            pr["plan"] = result
            store.save(self._data, self._root)
            self._load_state()
            tree = self.query_one("#tech-tree", TechTree)
            display = tree.get_plan_display_name(result)
            self.log_message(f"Moved {pr_id} → {display}")

    def action_done_pr(self) -> None:
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        _log.info("action: done_pr selected=%s", pr_id)
        if not pr_id:
            self.log_message("No PR selected")
            return
        action_key = f"Completing {pr_id}"
        if not self._guard_pr_action(action_key):
            return
        self._inflight_pr_action = action_key
        self._run_command(f"pr done {pr_id}", working_message=action_key, action_key=action_key)


    def _get_pane_split_direction(self) -> str:
        """Return 'v' if pane is taller than wide, else 'h'."""
        pane_id = os.environ.get("TMUX_PANE", "")
        if not pane_id:
            return "h"
        result = _run_shell(
            tmux_mod._tmux_cmd("display", "-t", pane_id, "-p", "#{pane_width} #{pane_height}"),
            capture_output=True, text=True
        )
        parts = result.stdout.strip().split()
        if len(parts) == 2:
            width, height = int(parts[0]), int(parts[1])
            # Use vertical split if pane is taller than wide (accounting for ~2:1 char aspect ratio)
            if height > width // 2:
                return "v"
        return "h"

    def action_edit_plan(self) -> None:
        """Edit the selected PR in an interactive editor."""
        _log.info("action: edit_plan")
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if not pr_id:
            self.log_message("No PR selected")
            return
        self._launch_pane(f"pm pr edit {pr_id}", "pr-edit")

    def action_view_plan(self) -> None:
        """Open the plan file associated with the selected PR in a pane."""
        _log.info("action: view_plan")
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if not pr_id:
            self.log_message("No PR selected")
            return
        pr = store.get_pr(self._data, pr_id)
        plan = self._get_plan_for_pr(pr)
        if not plan:
            self.log_message("No plan associated with this PR")
            return
        plan_file = plan.get("file", "")
        if not plan_file or not self._root:
            self.log_message("Plan file not found")
            return
        plan_path = self._root / plan_file
        if not plan_path.exists():
            self.log_message(f"Plan file not found: {plan_path}")
            return
        self._launch_pane(f"less {plan_path}", "plan")

    def _get_session_and_window(self) -> tuple[str, str] | None:
        """Get tmux session name and window ID. Returns None if not in tmux."""
        if not tmux_mod.in_tmux():
            self.log_message("Not in tmux. Use 'pm session' to start a tmux session.")
            return None
        session = tmux_mod.get_session_name()
        window = tmux_mod.get_window_id(session)
        return session, window

    def _launch_pane(self, cmd: str, role: str) -> None:
        """Launch a wrapped pane, register it, and rebalance.

        If a pane with this role already exists and is alive, focuses it instead
        of creating a duplicate.
        """
        info = self._get_session_and_window()
        if not info:
            return
        session, window = info
        _log.info("_launch_pane: session=%s window=%s role=%s", session, window, role)

        # Check if a pane with this role already exists
        existing_pane = pane_layout.find_live_pane_by_role(session, role)
        _log.info("_launch_pane: find_live_pane_by_role returned %s", existing_pane)
        if existing_pane:
            _log.info("pane with role=%s already exists: %s, focusing", role, existing_pane)
            tmux_mod.select_pane_smart(existing_pane, session, window)
            self.log_message(f"Focused existing {role} pane")
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
            self.log_message(f"Launched {role} pane")
            _log.info("launched pane: role=%s id=%s", role, pane_id)
        except Exception as e:
            _log.exception("failed to launch %s pane", role)
            self.log_message(f"Error: {e}")

    def action_toggle_guide(self) -> None:
        """Toggle between guide progress view and tech tree view."""
        _log.info("action: toggle_guide dismissed=%s current_step=%s", self._guide_dismissed, self._current_guide_step)
        if self._guide_dismissed:
            # Restore guide view if we're in a guide setup step
            state, _ = guide.resolve_guide_step(self._root)
            if state in GUIDE_SETUP_STEPS:
                _log.info("action: toggle_guide - restoring guide view for step %s", state)
                self._guide_dismissed = False
                self._show_guide_view(state)
                self._launch_pane("pm guide", "guide")
            else:
                # Not in guide setup steps, just launch the guide pane
                _log.info("action: toggle_guide - launching guide pane (not in setup steps)")
                self._launch_pane("pm guide", "guide")
        elif self._current_guide_step is not None:
            # Guide view is showing, dismiss it
            _log.info("action: toggle_guide - dismissing guide from step %s", self._current_guide_step)
            self._guide_dismissed = True
            self._show_normal_view()
            self.log_message("Guide dismissed. Press 'g' to restore.")

    def action_launch_notes(self) -> None:
        _log.info("action: launch_notes")
        root = self._root or (Path.cwd() / "pm")
        notes_path = root / notes.NOTES_FILENAME
        self._launch_pane(f"pm notes {notes_path}", "notes")

    def action_view_log(self) -> None:
        """View the TUI log file in a pane."""
        _log.info("action: view_log")
        log_path = command_log_file()
        if not log_path.exists():
            self.log_message("No log file yet.")
            return
        self._launch_pane(f"tail -f {log_path}", "log")

    def action_launch_meta(self) -> None:
        """Launch a meta-development session to work on pm itself."""
        _log.info("action: launch_meta")
        self._run_command("meta")

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
        _log.info("action: refresh")
        self._load_state()
        if self._current_guide_step is not None:
            self.log_message(f"Refreshed - Guide step: {guide.STEP_DESCRIPTIONS.get(self._current_guide_step, self._current_guide_step)}")
        else:
            # Trigger PR sync on manual refresh (non-blocking)
            async def do_refresh():
                await self._do_normal_sync(is_manual=True)
            self.run_worker(do_refresh())
            self.log_message("Refreshing...")

    def action_reload(self) -> None:
        """Reload state from disk without triggering PR sync."""
        _log.info("action: reload (state only)")
        self._load_state()

    def action_restart(self) -> None:
        """Restart the TUI by exec'ing a fresh pm _tui process."""
        _log.info("action: restart")
        self.exit()
        import shutil
        pm = shutil.which("pm")
        if pm:
            os.execvp(pm, [pm, "_tui"])
        else:
            os.execvp(sys.executable, [sys.executable, "-m", "pm_core.cli", "_tui"])

    def action_focus_command(self) -> None:
        _log.debug("action: focus_command")
        cmd_bar = self.query_one("#command-bar", CommandBar)
        cmd_bar.focus()

    def action_unfocus_command(self) -> None:
        cmd_bar = self.query_one("#command-bar", CommandBar)
        if cmd_bar.has_focus:
            cmd_bar.value = ""
            if self._plans_visible:
                self.query_one("#plans-pane", PlansPane).focus()
            else:
                self.query_one("#tech-tree", TechTree).focus()

    def action_show_help(self) -> None:
        _log.debug("action: show_help")
        self.push_screen(HelpScreen(in_plans=self._plans_visible, in_tests=self._tests_visible))

    # --- Plans view ---

    def _show_plans_view(self) -> None:
        """Show the plans list view."""
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        tests_container = self.query_one("#tests-container")
        tree_container.styles.display = "none"
        guide_container.styles.display = "none"
        plans_container.styles.display = "block"
        tests_container.styles.display = "none"
        self._plans_visible = True
        self._tests_visible = False
        self._current_guide_step = None
        self._refresh_plans_pane()
        plans_pane = self.query_one("#plans-pane", PlansPane)
        plans_pane.focus()
        # Update status bar
        plans = self._data.get("plans") or []
        status_bar = self.query_one("#status-bar", StatusBar)
        project = self._data.get("project", {})
        prs = self._data.get("prs") or []
        status_bar.update(f" [bold]Plans[/bold]    {len(plans)} plan(s)    [dim]P=back to tree[/dim]")
        self.call_after_refresh(self._capture_frame, "show_plans_view")

    def _refresh_plans_pane(self) -> None:
        """Refresh the plans pane with current data."""
        plans = self._data.get("plans") or []
        prs = self._data.get("prs") or []
        enriched = []
        for plan in plans:
            plan_id = plan.get("id", "")
            pr_count = sum(1 for pr in prs if pr.get("plan") == plan_id)
            intro = ""
            plan_file = plan.get("file", "")
            if plan_file and self._root:
                plan_path = self._root / plan_file
                try:
                    text = plan_path.read_text()
                    intro = extract_plan_intro(text)
                except OSError:
                    pass
            enriched.append({
                "id": plan_id,
                "name": plan.get("name", ""),
                "file": plan.get("file", ""),
                "status": plan.get("status", "draft"),
                "intro": intro,
                "pr_count": pr_count,
            })
        plans_pane = self.query_one("#plans-pane", PlansPane)
        plans_pane.update_plans(enriched)

    def action_toggle_plans(self) -> None:
        """Toggle between plans view and tech tree view."""
        _log.info("action: toggle_plans visible=%s", self._plans_visible)
        if self._plans_visible:
            self._show_normal_view()
        else:
            self._show_plans_view()

    def on_plan_selected(self, message: PlanSelected) -> None:
        _log.debug("plan selected: %s", message.plan_id)

    def on_plan_activated(self, message: PlanActivated) -> None:
        """Open plan file in a pane."""
        _log.info("plan activated: %s", message.plan_id)
        plan = store.get_plan(self._data, message.plan_id)
        if not plan or not self._root:
            return
        plan_path = self._root / plan.get("file", "")
        if plan_path.exists():
            self._launch_pane(f"less {plan_path}", "plan")

    def on_plan_action(self, message: PlanAction) -> None:
        """Handle plan action shortcuts.

        Key → action mapping is defined in PlansPane._KEY_ACTIONS.
        """
        message.stop()
        plans_pane = self.query_one("#plans-pane", PlansPane)
        plan_id = plans_pane.selected_plan_id
        _log.info("plan action: %s (plan=%s)", message.action, plan_id)

        if message.action == "add":
            self.push_screen(PlanAddScreen(), callback=self._handle_plan_add)
        elif message.action == "view":
            if plan_id:
                plan = store.get_plan(self._data, plan_id)
                if plan and self._root:
                    plan_path = self._root / plan.get("file", "")
                    if plan_path.exists():
                        self._launch_pane(f"less {plan_path}", "plan")
        elif message.action == "edit":
            if plan_id:
                plan = store.get_plan(self._data, plan_id)
                if plan and self._root:
                    plan_path = self._root / plan.get("file", "")
                    if plan_path.exists():
                        editor = self._find_editor()
                        self._launch_pane(f"{editor} {plan_path}", "plan-edit")
        elif message.action == "breakdown":
            if plan_id:
                self._launch_pane(f"pm plan breakdown {plan_id}", "plan-breakdown")
        elif message.action == "deps":
            self._launch_pane("pm plan deps", "plan-deps")
        elif message.action == "load":
            if plan_id:
                self._launch_pane(f"pm plan load {plan_id}", "plan-load")
        elif message.action == "review":
            if plan_id:
                self._launch_pane(f"pm plan review {plan_id}", "plan-review")

    def _handle_plan_add(self, result: tuple[str, str] | None) -> None:
        """Handle result from PlanAddScreen modal."""
        if result is None:
            return
        name, description = result
        cmd = f"pm plan add {shlex.quote(name)}"
        if description:
            cmd += f" --description {shlex.quote(description)}"
        self._launch_pane(cmd, "plan-add")

    # --- Tests view ---

    def _show_tests_view(self) -> None:
        """Show the tests list view."""
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        tests_container = self.query_one("#tests-container")
        tree_container.styles.display = "none"
        guide_container.styles.display = "none"
        plans_container.styles.display = "none"
        tests_container.styles.display = "block"
        self._tests_visible = True
        self._plans_visible = False
        self._current_guide_step = None
        self._refresh_tests_pane()
        tests_pane = self.query_one("#tests-pane", TestsPane)
        tests_pane.focus()
        # Update status bar
        from pm_core import tui_tests
        tests = tui_tests.list_tests()
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update(f" [bold]Tests[/bold]    {len(tests)} test(s)    [dim]T=back to tree[/dim]")
        self.call_after_refresh(self._capture_frame, "show_tests_view")

    def _refresh_tests_pane(self) -> None:
        """Refresh the tests pane with current data."""
        from pm_core import tui_tests
        tests = tui_tests.list_tests()
        tests_pane = self.query_one("#tests-pane", TestsPane)
        tests_pane.update_tests(tests)

    def action_toggle_tests(self) -> None:
        """Toggle between tests view and tech tree view."""
        _log.info("action: toggle_tests visible=%s", self._tests_visible)
        if self._tests_visible:
            self._show_normal_view()
        else:
            self._show_tests_view()

    def on_test_selected(self, message: TestSelected) -> None:
        _log.debug("test selected: %s", message.test_id)

    def on_test_activated(self, message: TestActivated) -> None:
        """Launch Claude with the selected test prompt."""
        _log.info("test activated: %s", message.test_id)
        from pm_core import tui_tests
        from pm_core.claude_launcher import find_claude, build_claude_shell_cmd

        prompt = tui_tests.get_test_prompt(message.test_id)
        if not prompt:
            self.log_message(f"Test not found: {message.test_id}")
            return

        # Build session context (same pattern as cli.py tui_test command)
        sess = self._session_name or "default"
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
        self._launch_pane(cmd, "tui-test")

    def _find_editor(self) -> str:
        """Find the user's preferred editor."""
        return os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))

    def action_launch_claude(self) -> None:
        """Launch an interactive Claude session in the project directory."""
        from pm_core.claude_launcher import find_claude
        claude = find_claude()
        if not claude:
            self.log_message("Claude CLI not found")
            return

        sess = self._session_name or "default"
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

        cmd = claude
        if os.environ.get("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS") == "true":
            cmd += " --dangerously-skip-permissions"
        cmd += f" {shlex.quote(prompt)}"
        self._launch_pane(cmd, "claude")

    def action_launch_help_claude(self) -> None:
        """Launch a beginner-friendly Claude assistant for the current project."""
        from pm_core.claude_launcher import find_claude
        claude = find_claude()
        if not claude:
            self.log_message("Claude CLI not found")
            return

        sess = self._session_name or "default"
        project = self._data.get("project", {})
        project_name = project.get("name", "unknown")
        repo = project.get("repo", "unknown")
        prs = self._data.get("prs") or []

        plans = self._data.get("plans") or []

        # Build a summary of current PRs
        pr_lines = []
        for pr in prs:
            status = pr.get("status", "pending")
            title = pr.get("title", "???")
            pr_id = pr.get("id", "???")
            deps = pr.get("depends_on") or []
            dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
            pr_lines.append(f"  - {pr_id}: {title} [{status}]{dep_str}")
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

1. Run `pm pr list` to see the current state of all PRs
2. Run `pm plan list` to see existing plans
3. Look at the repository with `git log --oneline -10` and `ls` to \
understand what the codebase contains
4. Check git health with `git status` and `git stash list` to look for \
uncommitted changes, merge conflicts, or stashed work that was forgotten
5. Run `git branch -a` to check for leftover or orphaned branches
6. If anything looks off, run `git fsck --no-dangling` to verify repo integrity

Then assess:
- **Git health**: Are there uncommitted changes, unresolved merge conflicts, \
detached HEAD, stashed changes, or other signs the repo is in a weird state? \
If so, help the user fix these first before anything else.
- Are there plans that haven't been broken into PRs yet?
- Are there PRs that are blocked or stuck?
- Is the dependency tree healthy (no circular deps, reasonable ordering)?
- Are there PRs in progress that might need attention?
- If the project is brand new, help the user think about what to build first.

Based on what you find, give the user clear, simple recommendations for \
what to do next. Suggest one or two concrete actions, not an overwhelming list."""

        cmd = claude
        if os.environ.get("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS") == "true":
            cmd += " --dangerously-skip-permissions"
        cmd += f" {shlex.quote(prompt)}"
        self._launch_pane(cmd, "assist")

    def action_show_connect(self) -> None:
        """Show the tmux connect command for shared sessions."""
        socket_path = os.environ.get("PM_TMUX_SOCKET")
        if socket_path:
            command = f"tmux -S {socket_path} attach"
            self.push_screen(ConnectScreen(command))
        else:
            self.log_message("Not a shared session")
            self.set_timer(2, self._clear_log_message)

    def action_quit(self) -> None:
        """Detach from tmux session instead of killing the TUI."""
        _log.info("action: quit")
        if tmux_mod.in_tmux():
            # Detach from tmux, leaving session running
            _run_shell(tmux_mod._tmux_cmd("detach-client"), check=False)
        else:
            # Not in tmux, just exit normally
            self.exit()
