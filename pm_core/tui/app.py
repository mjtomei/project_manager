"""Textual TUI App for Project Manager."""

from pathlib import Path

from pm_core.paths import configure_logger
from pm_core.tui._shell import _run_shell

_log = configure_logger("pm.tui")

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.timer import Timer

from pm_core import store, guide

from pm_core import tmux as tmux_mod
from pm_core.tui.tech_tree import TechTree, PRSelected
from pm_core.tui.command_bar import CommandBar, CommandSubmitted
from pm_core.tui.guide_progress import GuideProgress
from pm_core.tui.plans_pane import PlansPane, PlanSelected, PlanActivated, PlanAction
from pm_core.tui.tests_pane import TestsPane, TestSelected, TestActivated
from pm_core.plan_parser import extract_plan_intro

from pm_core.tui.widgets import TreeScroll, StatusBar, LogLine
from pm_core.tui.screens import (
    ConnectScreen, HelpScreen, PlanPickerScreen, PlanAddScreen,
)
from pm_core.tui import pane_ops
from pm_core.tui import frame_capture
from pm_core.tui.frame_capture import DEFAULT_FRAME_RATE, DEFAULT_FRAME_BUFFER_SIZE
from pm_core.tui import sync as sync_mod
from pm_core.tui import pr_view
from pm_core.tui import review_loop_ui


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
        width: 1fr;
        height: 100%;
        overflow: auto auto;
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
        width: 1fr;
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
        Binding("d", "done_pr", "Review", show=True),
        Binding("g", "merge_pr", "Merge", show=True),

        Binding("e", "edit_plan", "Edit PR", show=True),
        Binding("v", "view_plan", "View Plan", show=True),
        Binding("n", "launch_notes", "Notes", show=True),
        Binding("m", "launch_meta", "Meta", show=True),
        Binding("L", "view_log", "Log", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("R", "reload", "Reload", show=False),
        Binding("b", "rebalance", "Rebalance", show=True),
        Binding("ctrl+r", "restart", "Restart", show=False),
        Binding("slash", "focus_command", "Command", show=True),
        Binding("escape", "unfocus_command", "Back", show=False),
        Binding("p", "toggle_plans", "Plans", show=True),
        Binding("t", "toggle_tests", "Tests", show=True),
        Binding("x", "hide_plan", "Hide Plan", show=False),
        Binding("M", "move_to_plan", "Move Plan", show=False),
        Binding("X", "toggle_merged", "Toggle Merged", show=False),
        Binding("f", "cycle_filter", "Filter", show=False),
        Binding("question_mark", "show_help", "Help", show=True),
        Binding("c", "launch_claude", "Claude", show=True),
        Binding("H", "launch_guide", "Guide", show=True),
        Binding("C", "show_connect", "Connect", show=False),
        Binding("A", "toggle_auto_start", "Auto-start", show=False),
    ]

    def on_key(self, event) -> None:
        """Handle z modifier prefix key (supports z, zz, zzz)."""
        cmd_bar = self.query_one("#command-bar", CommandBar)
        if cmd_bar.has_focus:
            return
        if event.key == "z":
            if self._z_count >= 3:
                # zzz → cancel (toggle off)
                self._z_count = 0
                self._clear_log_message()
            else:
                self._z_count += 1
                self.log_message(f"[bold]{'z' * self._z_count} …[/]")
            event.prevent_default()
            event.stop()
        elif event.key == "escape" and self._z_count > 0:
            self._z_count = 0
            self._clear_log_message()
            # Don't prevent — let escape also do its normal thing

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Disable single-key shortcuts when command bar is focused or in guide mode."""
        if action in ("start_pr", "done_pr", "merge_pr",
                       "edit_plan", "view_plan", "launch_notes",
                       "launch_meta", "launch_claude", "launch_guide",
                       "view_log", "refresh", "rebalance", "quit", "show_help",
                       "toggle_plans", "toggle_tests", "hide_plan", "move_to_plan", "toggle_merged",
                       "cycle_filter", "toggle_auto_start"):
            cmd_bar = self.query_one("#command-bar", CommandBar)
            if cmd_bar.has_focus:
                _log.debug("check_action: blocked %s (command bar focused)", action)
                return False
        # Block PR actions when in guide mode or plans view (can't see the PR tree)
        if action in ("start_pr", "done_pr", "merge_pr", "launch_claude", "edit_plan", "view_plan", "hide_plan", "move_to_plan", "toggle_merged", "cycle_filter"):
            prs = self._data.get("prs") or []
            if not prs and self._current_guide_step is not None:
                _log.debug("check_action: blocked %s (in guide mode, no PRs)", action)
                return False
            if self._plans_visible:
                _log.debug("check_action: blocked %s (in plans view)", action)
                return False
            if self._tests_visible:
                _log.debug("check_action: blocked %s (in tests view)", action)
                return False
        return True

    def __init__(self):
        super().__init__()
        self._data: dict = {}
        self._root: Path | None = None
        self._sync_timer: Timer | None = None
        self._current_guide_step: str | None = None
        self._guide_auto_launched = False
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
        self._log_sticky_until: float = 0.0  # monotonic time until which log line is protected
        # z modifier key state (vim-style prefix, supports z/zz/zzz)
        self._z_count: int = 0
        # Review loop state: dict of pr_id -> ReviewLoopState (supports multiple)
        self._review_loops: dict = {}
        self._review_loop_timer: Timer | None = None
        # Pane idle tracker: detects when implementation windows go idle
        from pm_core.pane_idle import PaneIdleTracker
        self._pane_idle_tracker = PaneIdleTracker()
        # PRs awaiting merge-conflict resolution (tracked by _poll_impl_idle)
        self._pending_merge_prs: set[str] = set()
        # Animation frame counter for impl-pane idle polling throttle
        self._impl_poll_counter: int = 0
        # Auto-start state (purely in-memory, lost on TUI restart)
        self._auto_start: bool = False
        self._auto_start_target: str | None = None
        self._auto_start_run_id: str | None = None
        # Monitor loop state (purely in-memory, lost on TUI restart)
        self._monitor_state = None  # MonitorLoopState | None

    def _consume_z(self) -> int:
        """Atomically read and clear the z modifier count.

        Returns 0 (no z), 1 (z), 2 (zz), or 3 (zzz).
        Non-zero is truthy, so ``if app._consume_z():`` still works
        for callers that only care about "was z pressed".
        """
        count = self._z_count
        self._z_count = 0
        return count

    # --- Frame capture forwarder (called from ~15 sites) ---

    def _capture_frame(self, trigger: str = "unknown") -> None:
        frame_capture.capture_frame(self, trigger)

    # --- Command execution forwarder (called from pane_ops.py) ---

    def _run_command(self, cmd: str, working_message: str | None = None,
                     action_key: str | None = None) -> None:
        pr_view.run_command(self, cmd, working_message=working_message,
                            action_key=action_key)

    # --- Compose and lifecycle ---

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
        frame_capture.load_capture_config(self)
        # Set up watchers on child widgets for frame capture
        frame_capture.setup_frame_watchers(self)

        # Load state and render immediately so the TUI shows content fast.
        # Defer heavier operations (heal_registry, tmux bindings, GitHub
        # sync) to after the first frame.
        self._load_state()
        self._update_orientation()
        # Background sync interval: 5 minutes for automatic PR sync
        self._sync_timer = self.set_interval(300, self._background_sync)
        # Run heavier startup tasks (heal_registry, tmux bindings) in a
        # background thread so they don't block input processing.
        self.run_worker(self._deferred_startup(), exclusive=False)

    async def _deferred_startup(self) -> None:
        """Run heavier startup tasks in a background worker."""
        import asyncio
        # Run blocking subprocess work off the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._deferred_startup_sync)
        # These must run on the main thread (touch Textual state)
        self.run_worker(sync_mod.startup_github_sync(self))
        self._capture_frame("mount")

    def _deferred_startup_sync(self) -> None:
        """Blocking startup tasks run in a thread."""
        pane_ops.heal_registry(self._session_name)
        try:
            if self._session_name:
                from pm_core.cli.session import _register_tmux_bindings
                _register_tmux_bindings(self._session_name)
        except Exception:
            pass

    def on_resize(self) -> None:
        """Update layout orientation and recompute tree when terminal is resized."""
        self._update_orientation()
        # Defer recompute so container sizes have settled after the resize
        self.set_timer(0.1, self._recompute_tree_layout)

    def _recompute_tree_layout(self) -> None:
        """Recompute TechTree layout after a resize."""
        try:
            tree = self.query_one("#tech-tree", TechTree)
            if tree._prs:
                tree._recompute()
                tree.refresh(layout=True)
        except Exception:
            pass

    def _update_orientation(self) -> None:
        """Switch main area between landscape/portrait based on terminal size."""
        # Textual char cells are ~2:1 aspect ratio, so compare width to height*2
        is_portrait = self.size.width < self.size.height * 2
        if is_portrait != self._is_portrait:
            self._is_portrait = is_portrait
            main_area = self.query_one("#main-area")
            if is_portrait:
                main_area.add_class("portrait")
            else:
                main_area.remove_class("portrait")
            _log.debug("orientation: %s (%dx%d)", "portrait" if is_portrait else "landscape",
                       self.size.width, self.size.height)

    # --- State loading and view switching ---

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

        # Decide which view to show based on whether PRs exist
        prs = self._data.get("prs") or []
        if self._plans_visible:
            self._show_plans_view()
        elif self._tests_visible:
            self._show_tests_view()
        elif not prs:
            state, _ = guide.detect_state(self._root)
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
        desc = guide.STEP_DESCRIPTIONS.get(state, state)
        status_bar.update(f" [bold]pm Guide[/bold]    [cyan]{desc}[/cyan]    [dim]Guide running — Press H to restart[/dim]")

        self.log_message(f"Guide: {desc}")

        # Auto-launch guide pane on first startup when setup is incomplete.
        # launch_pane deduplicates if the pane is already running.
        if not self._guide_auto_launched and guide.needs_guide(self._root):
            self._guide_auto_launched = True
            pane_ops.launch_guide(self)

        # Capture frame after view change (use call_after_refresh to ensure screen is updated)
        self.call_after_refresh(self._capture_frame, f"show_guide_view:{state}")

    def _show_normal_view(self) -> None:
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

    # --- Log/status utilities ---

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
        else:
            hidden = []
            if tree._hide_merged:
                hidden.append("merged")
            if tree._hide_closed:
                hidden.append("closed")
            if hidden:
                filter_text = "hide " + "+".join(hidden)
        status_bar = self.query_one("#status-bar", StatusBar)
        monitor_status = ""
        if self._monitor_state and self._monitor_state.running:
            monitor_status = "input_required" if self._monitor_state.input_required else "running"
        status_bar.update_status(
            project.get("name", "???"),
            project.get("repo", "???"),
            sync_state,
            pr_count=len(prs),
            filter_text=filter_text,
            show_assist=not get_global_setting("hide-assist"),
            auto_start=self._auto_start,
            monitor_status=monitor_status,
        )

    def _update_display(self) -> None:
        """Refresh all widgets with current data."""
        if not self._data:
            return

        self._update_status_bar()

        tree = self.query_one("#tech-tree", TechTree)
        tree.apply_project_settings(self._data.get("project", {}))
        tree.update_plans(self._data.get("plans") or [])
        tree.update_prs(self._data.get("prs") or [])
        active_pr = self._data.get("project", {}).get("active_pr")
        if active_pr:
            tree.select_pr(active_pr)
        self._update_filter_status()

        # Start animation timer if there are active PRs
        from pm_core.tui.review_loop_ui import ensure_animation_timer
        ensure_animation_timer(self)

    def _update_filter_status(self) -> None:
        """Update the status bar to reflect active filters."""
        self._update_status_bar()

    def log_message(self, msg: str, capture: bool = True, sticky: float = 0) -> None:
        """Show a message in the log line."""
        import time as _time
        now = _time.monotonic()
        if sticky > 0:
            self._log_sticky_until = now + sticky
        elif now < self._log_sticky_until:
            return  # a sticky message is still showing
        try:
            log = self.query_one("#log-line", LogLine)
            log.update(f" {msg}")
        except Exception:
            pass
        if capture:
            truncated = msg[:60].replace("\n", " ")
            self.call_after_refresh(self._capture_frame, f"log_message:{truncated}")

    def log_error(self, title: str, detail: str = "", timeout: float = 5) -> None:
        """Show a red error in the log line that auto-clears."""
        msg = f"[red bold]{title}[/]"
        if detail:
            msg += f" {detail}"
        self.log_message(msg, sticky=timeout)
        self.set_timer(timeout, self._clear_log_message)

    def _clear_log_message(self) -> None:
        """Clear the log line message."""
        self._log_sticky_until = 0.0
        try:
            log = self.query_one("#log-line", LogLine)
            log.update("")
        except Exception:
            pass

    # --- Sync delegates (see tui/sync.py) ---

    async def _background_sync(self) -> None:
        await sync_mod.background_sync(self)

    async def _do_normal_sync(self, is_manual: bool = False) -> None:
        await sync_mod.do_normal_sync(self, is_manual=is_manual)

    # --- PR message handler delegates (see tui/pr_view.py) ---

    def _get_plan_for_pr(self, pr: dict | None) -> dict | None:
        """Look up the plan entry for a PR, if any."""
        if not pr or not pr.get("plan"):
            return None
        return store.get_plan(self._data, pr["plan"])

    def on_prselected(self, message: PRSelected) -> None:
        pr_view.handle_pr_selected(self, message.pr_id)

    def on_command_submitted(self, message: CommandSubmitted) -> None:
        pr_view.handle_command_submitted(self, message.command)

    # --- PR action delegates (see tui/pr_view.py) ---

    def action_start_pr(self) -> None:
        pr_view.start_pr(self)

    def action_done_pr(self) -> None:
        z = self._consume_z()
        if z == 0:
            # plain d = mark done (in_progress → in_review) + open review window
            pr_view.done_pr(self)
        elif z == 1:
            # z d = fresh done (kill existing review window), OR stop loop if running
            review_loop_ui.stop_loop_or_fresh_done(self)
        elif z == 2:
            # zz d = start review loop (stops on PASS or PASS_WITH_SUGGESTIONS),
            #        or stop loop if running
            review_loop_ui.start_or_stop_loop(self, stop_on_suggestions=True)
        else:
            # zzz d = start strict review loop (stops only on PASS),
            #         or stop loop if running
            review_loop_ui.start_or_stop_loop(self, stop_on_suggestions=False)

    def action_merge_pr(self) -> None:
        pr_view.merge_pr(self)

    def action_hide_plan(self) -> None:
        pr_view.hide_plan(self)

    def action_toggle_merged(self) -> None:
        pr_view.toggle_merged(self)

    def action_cycle_filter(self) -> None:
        pr_view.cycle_filter(self)

    def action_move_to_plan(self) -> None:
        pr_view.move_to_plan(self)

    # --- Pane operation delegates (see tui/pane_ops.py) ---

    def action_edit_plan(self) -> None:
        pane_ops.edit_plan(self)

    def action_view_plan(self) -> None:
        pane_ops.view_plan(self)

    def action_launch_notes(self) -> None:
        pane_ops.launch_notes(self)

    def action_view_log(self) -> None:
        pane_ops.view_log(self)

    def action_launch_meta(self) -> None:
        pane_ops.launch_meta(self)

    def action_rebalance(self) -> None:
        pane_ops.rebalance(self)

    def action_launch_claude(self) -> None:
        pane_ops.launch_claude(self)

    def action_launch_guide(self) -> None:
        pane_ops.launch_guide(self)

    def action_show_connect(self) -> None:
        pane_ops.show_connect(self)

    def action_toggle_auto_start(self) -> None:
        from pm_core.tui.auto_start import toggle
        tree = self.query_one("#tech-tree", TechTree)
        self.run_worker(toggle(self, selected_pr_id=tree.selected_pr_id))

    def action_quit(self) -> None:
        pane_ops.quit_app(self)

    def action_restart(self) -> None:
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
        status_bar.update(f" [bold]Plans[/bold]    {len(plans)} plan(s)    [dim]p=back to tree[/dim]")
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
            # When toggling off during setup, restore guide view
            prs = self._data.get("prs") or []
            if not prs:
                state, _ = guide.detect_state(self._root)
                self._show_guide_view(state)
            else:
                self._show_normal_view()
        else:
            self._show_plans_view()

    def on_plan_selected(self, message: PlanSelected) -> None:
        _log.debug("plan selected: %s", message.plan_id)

    def on_plan_activated(self, message: PlanActivated) -> None:
        """Open plan file in a pane."""
        pane_ops.launch_plan_activated(self, message.plan_id)

    def on_plan_action(self, message: PlanAction) -> None:
        """Handle plan action shortcuts."""
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
        status_bar.update(f" [bold]Tests[/bold]    {len(tests)} test(s)    [dim]t=back to tree[/dim]")
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
