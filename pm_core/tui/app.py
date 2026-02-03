"""Textual TUI App for Project Manager."""

import json
import logging
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_log_dir = Path.home() / ".pm-pane-registry"
_log_dir.mkdir(parents=True, exist_ok=True)
_handler = logging.FileHandler(_log_dir / "tui.log")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
_log = logging.getLogger("pm.tui")
_log.addHandler(_handler)
_log.setLevel(logging.DEBUG)

# Frame capture defaults
DEFAULT_FRAME_RATE = 1  # Record every change
DEFAULT_FRAME_BUFFER_SIZE = 100

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Header, Footer, Static, Label

from pm_core import store, graph as graph_mod, git_ops, prompt_gen, notes, guide
from pm_core.claude_launcher import find_claude, find_editor
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core.tui.tech_tree import TechTree, PRSelected, PRActivated
from pm_core.tui.detail_panel import DetailPanel
from pm_core.tui.command_bar import CommandBar, CommandSubmitted
from pm_core.tui.guide_progress import GuideProgress

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
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "start_pr", "Start PR", show=True),
        Binding("d", "done_pr", "Done PR", show=True),
        Binding("p", "copy_prompt", "Copy Prompt", show=True),
        Binding("c", "launch_claude", "Claude", show=True),
        Binding("e", "edit_plan", "Edit Plan", show=True),
        Binding("g", "toggle_guide", "Guide", show=True),
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
                       "edit_plan", "toggle_guide", "launch_notes", "refresh",
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
        self._guide_auto_launched = False
        self._guide_dismissed = False
        self._current_guide_step: str | None = None
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
            with Vertical(id="detail-container"):
                yield DetailPanel(id="detail-panel")
        yield LogLine(id="log-line")
        yield CommandBar(id="command-bar")

    def on_mount(self) -> None:
        _log.info("TUI mounted")
        # Get session name for frame capture file naming
        if tmux_mod.in_tmux():
            try:
                result = subprocess.run(
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
        self._sync_timer = self.set_interval(30, self._background_sync)

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
            self._root = store.find_project_root()
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
        if state in GUIDE_SETUP_STEPS and not self._guide_dismissed:
            self._show_guide_view(state)
        else:
            self._show_normal_view()

    def _show_guide_view(self, state: str) -> None:
        """Show the guide progress view during setup steps."""
        self._current_guide_step = state

        # Update guide progress widget
        guide_widget = self.query_one("#guide-progress", GuideProgress)
        guide_widget.update_step(state)

        # Show guide progress, hide tech tree
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        tree_container.styles.display = "none"
        guide_container.styles.display = "block"

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

    def _show_normal_view(self) -> None:
        """Show the normal tech tree view."""
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        tree_container.styles.display = "block"
        guide_container.styles.display = "none"
        self._current_guide_step = None
        # Capture frame after view change (use call_after_refresh to ensure screen is updated)
        self.call_after_refresh(self._capture_frame, "show_normal_view")

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
                self._show_normal_view()
                self.log_message("Guide complete! Showing tech tree.")
            elif state != self._current_guide_step:
                # Step changed, update the guide view
                self._show_guide_view(state)
            return

        # Not in guide mode - do normal sync
        await self._do_normal_sync()

    async def _do_normal_sync(self) -> None:
        """Perform normal git sync."""
        if not self._root:
            return
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            project = self._data.get("project", {})
            prs = self._data.get("prs") or []
            status_bar.update_status(project.get("name", "???"), project.get("repo", "???"), "pulling", pr_count=len(prs))

            sync_status = git_ops.sync_state(self._root)
            self._data = store.load(self._root)
            self._update_display()

            prs = self._data.get("prs") or []
            status_bar.update_status(project.get("name", "???"), project.get("repo", "???"), sync_status, pr_count=len(prs))
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
        self.call_after_refresh(self._capture_frame, f"pr_selected:{message.pr_id}")

    def on_pr_activated(self, message: PRActivated) -> None:
        pr = store.get_pr(self._data, message.pr_id)
        detail = self.query_one("#detail-panel", DetailPanel)
        detail.update_pr(pr, self._data.get("prs"))
        container = self.query_one("#detail-container")
        container.styles.display = "block"
        self.call_after_refresh(self._capture_frame, f"pr_activated:{message.pr_id}")

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
        """Launch a wrapped pane, register it, and rebalance.

        If a pane with this role already exists and is alive, focuses it instead
        of creating a duplicate.
        """
        info = self._get_session_and_window()
        if not info:
            return
        session, window = info

        # Check if a pane with this role already exists
        existing_pane = pane_layout.find_live_pane_by_role(session, role)
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
        if self._current_guide_step is not None:
            self.log_message(f"Refreshed - Guide step: {guide.STEP_DESCRIPTIONS.get(self._current_guide_step, self._current_guide_step)}")
        else:
            self.log_message("Refreshed")

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
