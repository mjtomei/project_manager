"""Textual TUI App for Project Manager."""

import json
import logging
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from pm_core.paths import configure_logger, debug_dir
from pm_core.tui._shell import _run_shell, _run_shell_async

_log = configure_logger("pm.tui")
_log_dir = debug_dir()


# Frame capture defaults
DEFAULT_FRAME_RATE = 1  # Record every change
DEFAULT_FRAME_BUFFER_SIZE = 100

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Label

from pm_core import store, graph as graph_mod, guide, pr_sync

from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core.tui.tech_tree import TechTree, PRSelected, PRActivated
from pm_core.tui.detail_panel import DetailPanel
from pm_core.tui.command_bar import CommandBar, CommandSubmitted
from pm_core.tui.guide_progress import GuideProgress
from pm_core.tui.plans_pane import PlansPane, PlanSelected, PlanActivated, PlanAction
from pm_core.tui.tests_pane import TestsPane, TestSelected, TestActivated
from pm_core.plan_parser import extract_plan_intro

# Import from new modules
from pm_core.tui.widgets import TreeScroll, StatusBar, LogLine
from pm_core.tui.screens import (
    WelcomeScreen, ConnectScreen, HelpScreen, PlanPickerScreen, PlanAddScreen,
)
from pm_core.tui import pane_ops
from pm_core.tui.pane_ops import GUIDE_SETUP_STEPS


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
        Binding("x", "hide_plan", "Hide Plan", show=False),
        Binding("M", "move_to_plan", "Move Plan", show=False),
        Binding("X", "toggle_merged", "Toggle Merged", show=False),
        Binding("F", "cycle_filter", "Filter", show=False),
        Binding("question_mark", "show_help", "Help", show=True),
        Binding("c", "launch_claude", "Claude", show=True),
        Binding("H", "launch_help_claude", "Assist", show=True),  # show toggled in __init__
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
            self.call_later(lambda: pane_ops.auto_launch_guide(self))

        # Capture frame after view change (use call_after_refresh to ensure screen is updated)
        self.call_after_refresh(self._capture_frame, f"show_guide_view:{state}")

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
        # Restore status bar to normal view
        self._update_status_bar()
        self.query_one("#tech-tree", TechTree).focus()
        # Capture frame after view change (use call_after_refresh to ensure screen is updated)
        self.call_after_refresh(self._capture_frame, "show_normal_view")
        # Show welcome popup when guide completes (only once)
        if from_guide and not self._welcome_shown:
            self._welcome_shown = True
            self.call_later(lambda: self.push_screen(WelcomeScreen()))

    def _update_status_bar(self, sync_state: str = "synced") -> None:
        """Update the status bar with current project info and filter state."""
        from pm_core.tui.tech_tree import STATUS_ICONS
        from pm_core.paths import get_global_setting
        if not self._data:
            return
        project = self._data.get("project", {})
        prs = self._data.get("prs") or []
        tree = self.query_one("#tech-tree", TechTree)
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
            sync_state,
            pr_count=len(prs),
            filter_text=filter_text,
            show_assist=not get_global_setting("hide-assist"),
        )

    def _update_display(self) -> None:
        """Refresh all widgets with current data."""
        if not self._data:
            return

        self._update_status_bar()

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
            pane_ops.launch_pane(self, f"pm {cmd}", "plan-add")
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
        """Toggle hiding the selected PR's plan group."""
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
        """Cycle through status filters: all -> pending -> in_progress -> ..."""
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
        self._update_status_bar()

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

    # --- Pane operation delegates (see tui/pane_ops.py) ---

    def action_edit_plan(self) -> None:
        """Edit the selected PR in an interactive editor."""
        pane_ops.edit_plan(self)

    def action_view_plan(self) -> None:
        """Open the plan file associated with the selected PR in a pane."""
        pane_ops.view_plan(self)

    def action_toggle_guide(self) -> None:
        """Toggle between guide progress view and tech tree view."""
        pane_ops.toggle_guide(self)

    def action_launch_notes(self) -> None:
        pane_ops.launch_notes(self)

    def action_view_log(self) -> None:
        """View the TUI log file in a pane."""
        pane_ops.view_log(self)

    def action_launch_meta(self) -> None:
        """Launch a meta-development session to work on pm itself."""
        pane_ops.launch_meta(self)

    def action_rebalance(self) -> None:
        pane_ops.rebalance(self)

    def action_launch_claude(self) -> None:
        """Launch an interactive Claude session in the project directory."""
        pane_ops.launch_claude(self)

    def action_launch_help_claude(self) -> None:
        """Launch a beginner-friendly Claude assistant for the current project."""
        pane_ops.launch_help_claude(self)

    def action_show_connect(self) -> None:
        """Show the tmux connect command for shared sessions."""
        pane_ops.show_connect(self)

    def action_quit(self) -> None:
        """Detach from tmux session instead of killing the TUI."""
        pane_ops.quit_app(self)

    def action_restart(self) -> None:
        """Restart the TUI by exec'ing a fresh pm _tui process."""
        pane_ops.restart_app(self)

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
        pane_ops.launch_plan_activated(self, message.plan_id)

    def on_plan_action(self, message: PlanAction) -> None:
        """Handle plan action shortcuts.

        Key -> action mapping is defined in PlansPane._KEY_ACTIONS.
        """
        message.stop()
        plans_pane = self.query_one("#plans-pane", PlansPane)
        plan_id = plans_pane.selected_plan_id
        _log.info("plan action: %s (plan=%s)", message.action, plan_id)

        if message.action == "add":
            self.push_screen(PlanAddScreen(), callback=lambda r: pane_ops.handle_plan_add(self, r))
        else:
            pane_ops.handle_plan_action(self, message.action, plan_id)

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
        pane_ops.launch_test(self, message.test_id)
