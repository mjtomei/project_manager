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
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Header, Footer, Static, Label
from textual.screen import ModalScreen

from pm_core import store, graph as graph_mod, git_ops, prompt_gen, notes, guide, pr_sync

from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core.tui.tech_tree import TechTree, PRSelected, PRActivated
from pm_core.tui.detail_panel import DetailPanel
from pm_core.tui.command_bar import CommandBar, CommandSubmitted
from pm_core.tui.guide_progress import GuideProgress
from pm_core.tui.plans_pane import PlansPane, PlanSelected, PlanActivated, PlanAction
from pm_core.plan_parser import extract_plan_intro

# Guide steps that indicate setup is still in progress
GUIDE_SETUP_STEPS = {"no_project", "initialized", "has_plan_draft", "has_plan_prs", "needs_deps_review"}


class StatusBar(Static):
    """Top status bar showing project info and sync state."""

    def update_status(self, project_name: str, repo: str, sync_state: str, pr_count: int = 0) -> None:
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
        self.update(f" Project: [bold]{project_name}[/bold]    {pr_info}    repo: [cyan]{safe_repo}[/cyan]    {sync_display}")


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
            yield Label("  [bold]↑↓←→[/] or [bold]hjkl[/]  Navigate the PR tree", classes="welcome-row")
            yield Label("  [bold]s[/]  Start working on the selected PR", classes="welcome-row")
            yield Label("  [bold]c[/]  Launch Claude in a new pane", classes="welcome-row")
            yield Label("  [bold]e[/]  Edit PR details", classes="welcome-row")
            yield Label("  [bold]?[/]  Show all keyboard shortcuts", classes="welcome-row")
            yield Label("")
            yield Label("[dim]Press Enter or Esc to continue[/]", classes="welcome-row")

    def action_dismiss(self) -> None:
        self.app.pop_screen()


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

    def __init__(self, in_plans: bool = False):
        super().__init__()
        self._in_plans = in_plans

    def compose(self) -> ComposeResult:
        with Vertical(id="help-container"):
            yield Label("Keyboard Shortcuts", id="help-title")
            if self._in_plans:
                yield Label("Plan Navigation", classes="help-section")
                yield Label("  [bold]↑↓[/] or [bold]jk[/]  Move selection", classes="help-row")
                yield Label("  [bold]Enter/v[/]  View plan file", classes="help-row")
                yield Label("Plan Actions", classes="help-section")
                yield Label("  [bold]a[/]  Add a new plan", classes="help-row")
                yield Label("  [bold]e[/]  Edit plan file", classes="help-row")
                yield Label("  [bold]w[/]  Break plan into PRs", classes="help-row")
                yield Label("  [bold]c[/]  Review plan-PR consistency", classes="help-row")
                yield Label("  [bold]D[/]  Review PR dependencies", classes="help-row")
                yield Label("  [bold]l[/]  Load PRs from plan", classes="help-row")
                yield Label("  [bold]P[/]  Back to tree view", classes="help-row")
            else:
                yield Label("Tree Navigation", classes="help-section")
                yield Label("  [bold]↑↓←→[/] or [bold]hjkl[/]  Move selection", classes="help-row")
                yield Label("  [bold]Enter[/]  Show PR details", classes="help-row")
                yield Label("PR Actions", classes="help-section")
                yield Label("  [bold]s[/]  Start selected PR", classes="help-row")
                yield Label("  [bold]S[/]  Start fresh (no resume)", classes="help-row")
                yield Label("  [bold]d[/]  Mark PR as done", classes="help-row")
                yield Label("  [bold]c[/]  Launch Claude for PR", classes="help-row")
                yield Label("  [bold]p[/]  Copy prompt to clipboard", classes="help-row")
                yield Label("  [bold]e[/]  Edit selected PR", classes="help-row")
                yield Label("  [bold]v[/]  View plan file", classes="help-row")
            yield Label("Panes & Views", classes="help-section")
            yield Label("  [bold]/[/]  Open command bar", classes="help-row")
            yield Label("  [bold]g[/]  Toggle guide view", classes="help-row")
            yield Label("  [bold]n[/]  Open notes", classes="help-row")
            yield Label("  [bold]m[/]  Meta: work on pm itself", classes="help-row")
            yield Label("  [bold]L[/]  View TUI log", classes="help-row")
            yield Label("  [bold]P[/]  Toggle plans view", classes="help-row")
            yield Label("  [bold]b[/]  Rebalance panes", classes="help-row")
            yield Label("Other", classes="help-section")
            yield Label("  [bold]r[/]  Refresh / sync with GitHub", classes="help-row")
            yield Label("  [bold]Ctrl+R[/]  Restart TUI", classes="help-row")
            yield Label("  [bold]?[/]  Show this help", classes="help-row")
            yield Label("  [bold]q[/]  Detach from session", classes="help-row")
            yield Label("")
            yield Label("[dim]Press Esc or ? to close[/]", classes="help-row")

    def action_dismiss(self) -> None:
        self.app.pop_screen()


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
        height: 100%;
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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "start_pr", "Start PR", show=True),
        Binding("S", "start_pr_fresh", "Start Fresh", show=False),
        Binding("d", "done_pr", "Done PR", show=True),
        Binding("p", "copy_prompt", "Copy Prompt", show=True),

        Binding("e", "edit_plan", "Edit PR", show=True),
        Binding("v", "view_plan", "View Plan", show=True),
        Binding("g", "toggle_guide", "Guide", show=True),
        Binding("n", "launch_notes", "Notes", show=True),
        Binding("m", "launch_meta", "Meta", show=True),
        Binding("L", "view_log", "Log", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("b", "rebalance", "Rebalance", show=True),
        Binding("ctrl+r", "restart", "Restart", show=False),
        Binding("slash", "focus_command", "Command", show=True),
        Binding("escape", "unfocus_command", "Back", show=False),
        Binding("P", "toggle_plans", "Plans", show=True),
        Binding("question_mark", "show_help", "Help", show=True),
    ]

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Disable single-key shortcuts when command bar is focused or in guide mode."""
        if action in ("start_pr", "start_pr_fresh", "done_pr", "copy_prompt",
                       "edit_plan", "view_plan", "toggle_guide", "launch_notes",
                       "launch_meta", "view_log", "refresh", "rebalance", "quit", "show_help"):
            cmd_bar = self.query_one("#command-bar", CommandBar)
            if cmd_bar.has_focus:
                _log.debug("check_action: blocked %s (command bar focused)", action)
                return False
        # Block PR actions when in guide mode or plans view (can't see the PR tree)
        if action in ("start_pr", "done_pr", "copy_prompt", "launch_claude", "edit_plan", "view_plan"):
            if self._current_guide_step is not None:
                _log.debug("check_action: blocked %s (in guide mode)", action)
                return False
            if self._plans_visible:
                _log.debug("check_action: blocked %s (in plans view)", action)
                return False
        return True

    def __init__(self):
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
        # Frame capture state (always enabled)
        self._frame_rate: int = DEFAULT_FRAME_RATE
        self._frame_buffer_size: int = DEFAULT_FRAME_BUFFER_SIZE
        self._frame_buffer: list[dict] = []
        self._frame_change_count: int = 0
        self._last_frame_content: str | None = None
        self._session_name: str | None = None

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
                ["tmux", "capture-pane", "-t", pane_id, "-p"],
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
        with Horizontal(id="main-area"):
            with Vertical(id="tree-container"):
                yield TechTree(id="tech-tree")
            with Vertical(id="guide-progress-container"):
                yield GuideProgress(id="guide-progress")
            with Vertical(id="plans-container"):
                yield PlansPane(id="plans-pane")
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
                    ["tmux", "display-message", "-p", "#{session_name}"],
                    capture_output=True, text=True, timeout=5
                )
                self._session_name = result.stdout.strip()
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
        elif state in GUIDE_SETUP_STEPS and not self._guide_dismissed:
            self._show_guide_view(state)
        else:
            self._show_normal_view()

    def _show_guide_view(self, state: str) -> None:
        """Show the guide progress view during setup steps."""
        self._current_guide_step = state
        self._plans_visible = False

        # Update guide progress widget
        guide_widget = self.query_one("#guide-progress", GuideProgress)
        guide_widget.update_step(state)

        # Show guide progress, hide tech tree and plans
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        tree_container.styles.display = "none"
        guide_container.styles.display = "block"
        plans_container.styles.display = "none"

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
        tree_container.styles.display = "block"
        guide_container.styles.display = "none"
        plans_container.styles.display = "none"
        self._current_guide_step = None
        self._plans_visible = False
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
        tree.update_prs(self._data.get("prs") or [])

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

    def log_message(self, msg: str) -> None:
        """Show a message in the log line."""
        try:
            log = self.query_one("#log-line", LogLine)
            log.update(f" {msg}")
        except Exception:
            pass

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

    def on_command_submitted(self, message: CommandSubmitted) -> None:
        """Handle commands typed in the command bar."""
        _log.info("command submitted: %s", message.command)
        self._run_command(message.command)
        tree = self.query_one("#tech-tree", TechTree)
        tree.focus()

    def _run_command(self, cmd: str, working_message: str | None = None) -> None:
        """Execute a pm sub-command.

        Args:
            cmd: The command to run (e.g., "pr start pr-001")
            working_message: Optional message to show while running (enables async mode)
        """
        parts = shlex.split(cmd)
        if not parts:
            return

        _log.info("running command: %s", parts)

        if working_message:
            # Run async with spinner
            self.run_worker(self._run_command_async(cmd, parts, working_message))
        else:
            # Run sync for quick commands
            self.log_message(f"> {cmd}")
            self._run_command_sync(parts)

    def _run_command_sync(self, parts: list[str]) -> None:
        """Run a command synchronously (for quick operations)."""
        try:
            cmd = [sys.executable, "-m", "pm_core"] + parts
            result = _run_shell(
                cmd,
                cwd=str(self._root) if self._root else None,
                capture_output=True,
                text=True,
                timeout=30,
            )
            _log.debug("pm exit=%d stdout=%r stderr=%r",
                       result.returncode, result.stdout[:200], result.stderr[:200])
            if result.stdout.strip():
                self.log_message(result.stdout.strip().split("\n")[-1])
            if result.returncode != 0 and result.stderr.strip():
                self.log_message(f"Error: {result.stderr.strip().split(chr(10))[-1]}")
        except Exception as e:
            _log.exception("command failed: %s", parts)
            self.log_message(f"Error: {e}")

        # Reload state
        self._load_state()

    async def _run_command_async(self, cmd: str, parts: list[str], working_message: str) -> None:
        """Run a command asynchronously with animated spinner."""
        import asyncio
        import itertools

        cwd = str(self._root) if self._root else None
        full_cmd = [sys.executable, "-m", "pm_core"] + list(parts)

        spinner_frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        spinner_running = True

        def update_spinner() -> None:
            if spinner_running:
                frame = next(spinner_frames)
                self.log_message(f"{frame} {working_message}...")
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

        # Reload state
        self._load_state()

    # --- Key actions ---

    def action_start_pr(self) -> None:
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        _log.info("action: start_pr selected=%s", pr_id)
        if pr_id:
            self._run_command(f"pr start {pr_id}", working_message=f"Starting {pr_id}")
        else:
            _log.info("action: start_pr - no PR selected")
            self.log_message("No PR selected")

    def action_start_pr_fresh(self) -> None:
        """Start PR with fresh Claude session (no resume)."""
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        _log.info("action: start_pr_fresh selected=%s", pr_id)
        if pr_id:
            self._run_command(f"pr start --new {pr_id}", working_message=f"Starting {pr_id} (fresh)")
        else:
            self.log_message("No PR selected")

    def action_done_pr(self) -> None:
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        _log.info("action: done_pr selected=%s", pr_id)
        if pr_id:
            self._run_command(f"pr done {pr_id}")
        else:
            self.log_message("No PR selected")

    def action_copy_prompt(self) -> None:
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        _log.info("action: copy_prompt selected=%s", pr_id)
        if not pr_id:
            self.log_message("No PR selected")
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

    def _get_pane_split_direction(self) -> str:
        """Return 'v' if pane is taller than wide, else 'h'."""
        pane_id = os.environ.get("TMUX_PANE", "")
        if not pane_id:
            return "h"
        result = _run_shell(
            ["tmux", "display", "-t", pane_id, "-p", "#{pane_width} #{pane_height}"],
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
        if not tmux_mod.in_tmux():
            self.log_message("Not in tmux. Use 'pm session' to start a tmux session.")
            return
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if not pr_id:
            self.log_message("No PR selected")
            return
        try:
            session_name = _run_shell(
                ["tmux", "display-message", "-p", "#{session_name}"],
                capture_output=True, text=True
            ).stdout.strip()
            direction = self._get_pane_split_direction()
            edit_cmd = f"pm pr edit {pr_id}"
            _log.info("launching editor: %s", edit_cmd)
            tmux_mod.split_pane(session_name, direction, edit_cmd)
            self.log_message(f"Editing {pr_id}")
        except Exception as e:
            self.log_message(f"Error: {e}")

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
            tmux_mod.select_pane(existing_pane)
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
            tmux_mod.select_pane(pane_id)
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
        self.log_message("Launched meta session for pm development")

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
            tree = self.query_one("#tech-tree", TechTree)
            tree.focus()

    def action_show_help(self) -> None:
        _log.debug("action: show_help")
        self.push_screen(HelpScreen(in_plans=self._plans_visible))

    # --- Plans view ---

    def _show_plans_view(self) -> None:
        """Show the plans list view."""
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        tree_container.styles.display = "none"
        guide_container.styles.display = "none"
        plans_container.styles.display = "block"
        self._plans_visible = True
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
        """Handle plan action shortcuts."""
        _log.info("plan action: %s", message.action)
        plans_pane = self.query_one("#plans-pane", PlansPane)
        plan_id = plans_pane.selected_plan_id

        if message.action == "add":
            cmd_bar = self.query_one("#command-bar", CommandBar)
            cmd_bar.value = "plan add "
            cmd_bar.focus()
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

    def _find_editor(self) -> str:
        """Find the user's preferred editor."""
        return os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))

    def action_quit(self) -> None:
        """Detach from tmux session instead of killing the TUI."""
        _log.info("action: quit")
        if tmux_mod.in_tmux():
            # Detach from tmux, leaving session running
            _run_shell(["tmux", "detach-client"], check=False)
        else:
            # Not in tmux, just exit normally
            self.exit()
