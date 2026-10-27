"""Textual TUI App for Project Manager."""

import shlex
from pathlib import Path

from pm_core.paths import configure_logger
from pm_core.tui._shell import _run_shell

_log = configure_logger("pm.tui")

# Queued external commands last written this long before the TUI process
# started were left by one that died, not sent during a restart — drop
# rather than replay them.  Measured from process start, not drain time:
# the startup drain waits for the breadcrumb scheduler pass, which can take
# a while with several targets.
_STARTUP_QUEUE_MAX_AGE = 60

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
from pm_core.tui.qa_pane import QAPane, QAItemSelected, QAItemActivated, QAAction
from pm_core.plans.parser import extract_plan_intro

from pm_core.tui.widgets import TreeScroll, StatusBar, SessionBar, LogLine
from pm_core.tui.screens import (
    ConnectScreen, HelpScreen, MergeLockScreen, PlanPickerScreen, PlanAddScreen,
    QACreatePickerScreen,
)
from pm_core.tui import pane_ops
from pm_core.tui import frame_capture
from pm_core.tui.frame_capture import DEFAULT_FRAME_RATE, DEFAULT_FRAME_BUFFER_SIZE
from pm_core.tui import sync as sync_mod
from pm_core.tui import pr_view
from pm_core.tui import review_loop_ui


# Held confirmations queued behind the current hold (see log_message); more
# than this and the oldest is dropped from the line (it is still in ``L``).
_LOG_HELD_QUEUE_MAX = 3


def _record_log_message(app, msg: str, suppressed: bool) -> None:
    """Append a log-line message (markup stripped) to the command log."""
    try:
        from rich.text import Text
        plain = Text.from_markup(msg).plain
    except Exception:
        plain = msg
    plain = " ".join(plain.split())
    if not plain or plain == getattr(app, "_last_logged_message", None):
        return
    app._last_logged_message = plain
    _log.info("log: %s%s", plain, " (hidden by sticky message)" if suppressed else "")


# Keys whose action consumes the ``z`` prefix — the "kill existing before
# next" modifier (``z s``/``S`` start, ``z d`` review, ``z e``/``v`` plan
# panes, ``z n``/``L``/``m``/``H``/``c`` views, ``z t`` QA, ``z O``/``z A``
# auto-start).  Any other key press cancels a pending ``z`` so a stale
# prefix cannot turn a later plain ``A``/``O`` into its destructive
# fresh-autostart variant (or silently re-interpret another action).  The
# set must stay in sync with the ``_consume_z()`` callers.
_Z_PREFIX_KEYS = frozenset({
    "s", "S", "d", "e", "v", "n", "L", "m", "H", "c", "t", "A", "O",
})

# A pending ``z`` only applies to the next chord key.  Navigation keys are
# swallowed by the focused widget (the tech tree) before ``on_key`` sees
# them, so the set above cannot cancel the prefix for ``z`` + j/k/arrows.
# Expire it after a short window (the same 2 s the ``w``/``y`` prefixes use)
# so a forgotten prefix cannot arm a later destructive key.
_Z_PREFIX_TIMEOUT = 2.0


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
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    SessionBar {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
        display: none;
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
    #qa-container {
        width: 100%;
        height: 100%;
        display: none;
        overflow: auto auto;
    }
    QAPane {
        height: auto;
        width: 1fr;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("q", "toggle_qa", "QA"),
        Binding("s", "start_pr", "Start PR", show=True),
        Binding("S", "start_pr_companion", "Start+Companion", show=False),
        Binding("d", "review_pr", "Review", show=True),
        Binding("g", "merge_pr", "Merge", show=True),
        Binding("G", "merge_pr_companion", "Merge+Companion", show=False),

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
        Binding("t", "start_qa_on_pr", "QA Run", show=True),
        Binding("i", "signoff_pr", "Sign-off", show=True),
        Binding("x", "hide_plan", "Hide Plan", show=False),
        Binding("M", "move_to_plan", "Move Plan", show=False),
        Binding("X", "toggle_merged", "Toggle Merged", show=False),
        Binding("f", "cycle_filter", "Filter", show=False),
        Binding("F", "cycle_sort", "Sort", show=False),
        Binding("question_mark", "show_help", "Help", show=True),
        Binding("c", "launch_claude", "Claude", show=True),
        Binding("H", "launch_guide", "Guide", show=True),
        Binding("C", "show_connect", "Connect", show=False),
        Binding("A", "toggle_auto_start", "Auto-start", show=False),
        Binding("a", "show_auto_runs", "Runs", show=True),
        Binding("O", "auto_sequence_pr", "Auto-seq", show=True),
        Binding("w", "focus_watcher", "Watcher", show=False),
        Binding("V", "review_spec", "Review Spec", show=False),
        Binding("Y", "cleanup_pr", "Cleanup", show=True),
    ]

    def on_key(self, event) -> None:
        """Handle z and w modifier prefix keys.

        z supports z and zz modifiers for review/QA loop control.
        w is a prefix key for watcher commands: wf=focus, ww=list, ws=start/stop.

        Also buffers keystrokes when / was pressed but the command bar
        hasn't received focus yet (race condition fix).
        """
        cmd_bar = self.query_one("#command-bar", CommandBar)
        if cmd_bar.has_focus:
            return
        # When a modal/screen is on top of the default screen, let it handle
        # its own keys — App-level prefix keys (y/w/z) must not swallow them.
        if len(self.screen_stack) > 1:
            return
        # A pending ``z`` prefix only applies to the *next* key when that key
        # is one of the z-actions.  Without this, pressing ``z`` then a
        # non-z key leaves the count armed, so a later plain ``A`` would run
        # the destructive fresh autostart on the newly selected PR.  (Keys
        # the focused widget swallows — j/k/arrows — never reach here; the
        # chord-window timer covers those.)
        key = event.character or event.key
        if (self._z_count and key != "z"
                and key not in _Z_PREFIX_KEYS):
            self._z_count = 0
            self._stop_z_timer()
            self._clear_prefix_hint()
        # Buffer keystrokes between / press and command bar gaining focus
        if self._command_pending:
            if event.key == "escape":
                # Cancel: discard buffer and abort command mode
                self._command_pending = False
                self._command_buffer.clear()
            elif event.character and event.character.isprintable():
                self._command_buffer.append(event.character)
            event.prevent_default()
            event.stop()
            return
        # Handle w prefix mode: dispatch second key
        if self._w_mode:
            self._w_mode = False
            if self._w_cancel_timer:
                self._w_cancel_timer.stop()
                self._w_cancel_timer = None
            self._clear_prefix_hint()
            key = event.character or event.key
            if key == "w":
                self._action_watcher_list()
            elif key == "f":
                self._action_focus_watcher()
            elif key == "s":
                self._action_watcher_toggle()
            elif key == "r":
                self._action_watcher_review()
            else:
                self.log_message("[dim]w cancelled[/]")
            event.prevent_default()
            event.stop()
            return
        # y prefix mode: dispatch second key as cleanup-then-action
        if self._y_mode:
            self._y_mode = False
            if self._y_cancel_timer:
                self._y_cancel_timer.stop()
                self._y_cancel_timer = None
            self._clear_prefix_hint()
            key = event.character or event.key
            if key in ("s", "d", "t"):
                pr_view.cleanup_then_action(self, key)
            else:
                self.log_message("[dim]y cancelled[/]")
            event.prevent_default()
            event.stop()
            return
        if (event.key == "y" or event.character == "y"):
            if not self.check_action("cleanup_pr", ()):
                return
            self._y_mode = True
            self._z_count = 0
            self._prefix_hint_seq = self.log_message(
                "[bold]y …[/] [dim](cleanup-then: s=start d=review t=qa)[/]")
            self._y_cancel_timer = self.set_timer(2.0, self._cancel_y_mode)
            event.prevent_default()
            event.stop()
            return
        if event.key == "w" or event.character == "w":
            # Enter w prefix mode (check_action guard for command bar etc)
            if not self.check_action("focus_watcher", ()):
                return
            self._w_mode = True
            self._prefix_hint_seq = self.log_message(
                "[bold]w …[/] [dim](w=list f=focus s=start/stop r=review)[/]")
            # Auto-cancel after 2 seconds
            self._w_cancel_timer = self.set_timer(2.0, self._cancel_w_mode)
            event.prevent_default()
            event.stop()
            return
        if event.key == "z":
            if self._z_count >= 2:
                # zzz → cancel (toggle off).  Only z and zz are valid prefixes;
                # a third z resets.
                self._z_count = 0
                self._stop_z_timer()
                self._clear_prefix_hint()
            else:
                self._z_count += 1
                hint = ""
                if self._z_count == 1:
                    hint = (" [dim](d=review t=qa "
                            "O=fresh-stop A=fresh-auto)[/]")
                self._prefix_hint_seq = self.log_message(
                    f"[bold]{'z' * self._z_count} …[/]{hint}")
                self._stop_z_timer()
                self._z_cancel_timer = self.set_timer(
                    _Z_PREFIX_TIMEOUT, self._cancel_z_mode)
            event.prevent_default()
            event.stop()
        elif event.key == "escape" and (self._z_count > 0 or self._w_mode or self._y_mode):
            self._z_count = 0
            self._stop_z_timer()
            if self._w_mode:
                self._w_mode = False
                if self._w_cancel_timer:
                    self._w_cancel_timer.stop()
                    self._w_cancel_timer = None
            if self._y_mode:
                self._y_mode = False
                if self._y_cancel_timer:
                    self._y_cancel_timer.stop()
                    self._y_cancel_timer = None
            self._clear_prefix_hint()
            # Don't prevent — let escape also do its normal thing

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Disable single-key shortcuts when command bar is focused or in guide mode."""
        if action in ("start_pr", "start_pr_companion", "review_pr",
                       "merge_pr", "merge_pr_companion",
                       "edit_plan", "view_plan", "launch_notes",
                       "launch_meta", "launch_claude", "launch_guide",
                       "view_log", "refresh", "rebalance", "show_help",
                       "toggle_plans", "toggle_qa", "start_qa_on_pr", "hide_plan", "move_to_plan", "toggle_merged",
                       "cycle_filter", "cycle_sort", "toggle_auto_start", "auto_sequence_pr", "focus_watcher",
                       "review_spec", "cleanup_pr", "show_auto_runs"):
            cmd_bar = self.query_one("#command-bar", CommandBar)
            if cmd_bar.has_focus or self._command_pending:
                _log.debug("check_action: blocked %s (command bar focused/pending)", action)
                return False
        # Block PR actions when in guide mode or plans view (can't see the PR tree)
        if action in ("start_pr", "start_pr_companion", "review_pr", "merge_pr", "merge_pr_companion", "launch_claude", "edit_plan", "view_plan", "hide_plan", "move_to_plan", "toggle_merged", "cycle_filter", "cycle_sort", "start_qa_on_pr"):
            prs = self._data.get("prs") or []
            if not prs and self._current_guide_step is not None:
                _log.debug("check_action: blocked %s (in guide mode, no PRs)", action)
                return False
            if self._plans_visible:
                _log.debug("check_action: blocked %s (in plans view)", action)
                return False
            if self._qa_visible:
                _log.debug("check_action: blocked %s (in QA view)", action)
                return False
        return True

    def __init__(self):
        super().__init__()
        self._data: dict = {}
        self._root: Path | None = None
        # Coalescing write queue: decouples in-memory state from disk so
        # per-keypress mutations (e.g. active_pr) don't block the event loop.
        # Created on mount once the project root is known.
        self._write_queue: store.WriteQueue | None = None
        self._sync_timer: Timer | None = None
        self._current_guide_step: str | None = None
        self._guide_auto_launched = False
        self._plans_visible = False
        self._qa_visible = False
        # Frame capture state (always enabled)
        self._frame_rate: int = DEFAULT_FRAME_RATE
        self._frame_buffer_size: int = DEFAULT_FRAME_BUFFER_SIZE
        self._frame_buffer: list[dict] = []
        self._frame_change_count: int = 0
        self._last_frame_content: str | None = None
        self._session_name: str | None = None
        # External commands (SIGUSR2 queue) wait until startup has
        # restored breadcrumb state — see _drain_command_queue.
        self._cmd_queue_ready = False
        import time as _time
        self._started_wall: float = _time.time()
        self._is_portrait: bool = False
        # In-flight PR action tracking (prevents concurrent/duplicate PR commands)
        self._inflight_pr_action: str | None = None
        self._log_sticky_until: float = 0.0  # monotonic time until which log line is protected
        self._log_hold_until: float = 0.0  # see log_message(hold=)
        self._log_held: tuple | None = None  # latest message deferred by a hold
        self._log_held_queue: list = []  # held messages waiting for the line
        self._log_seq: int = 0  # arrival number of the latest log message
        self._log_shown_seq: int = 0  # arrival number of the one on the line
        # z modifier key state (vim-style prefix, supports z/zz)
        self._z_count: int = 0
        self._z_cancel_timer: Timer | None = None
        # Review loop state: dict of pr_id -> ReviewLoopState (supports multiple)
        self._review_loops: dict = {}
        self._review_loop_timer: Timer | None = None
        # Pane idle tracker: detects when implementation windows go idle
        from pm_core.pane_idle import PaneIdleTracker
        self._pane_idle_tracker = PaneIdleTracker()
        # PRs whose post-publish main-repo update window is open (tracked
        # by _poll_impl_idle; the merge itself never resolves conflicts)
        self._pending_merge_prs: set[str] = set()
        # Sign-off outcomes already acted on: {pr_id: (verdict, sha, policy)}
        # (signoff_ui — keeps the 5 s poll from repeating the ready line).
        self._signoff_acted: dict[str, tuple] = {}
        # PRs whose merge window needs human input (INPUT_REQUIRED verdict)
        self._merge_input_required_prs: set[str] = set()
        # Animation frame counter for impl-pane idle polling throttle
        self._impl_poll_counter: int = 0
        # Auto-start state (in-memory; preserved only via the merge-restart
        # breadcrumb).  ``_auto_start`` is derived: True iff there is at
        # least one target or the explicit whole-backlog mode is on.
        self._auto_start: bool = False
        # Ordered {pr_id: {"added_at", "source"[, "wait_for_merge"]}} — see
        # auto_start.add_targets (the flag holds the target's closure).
        self._auto_start_targets: dict[str, dict] = {}
        self._auto_start_all: bool = False
        self._auto_start_run_id: str | None = None
        # PR ids whose ``pm pr start`` is in flight (shared-dep launch guard
        # across concurrent check_and_start workers).
        self._auto_start_launching: set[str] = set()
        # active_pr the tree cursor last followed, and PRs the scheduler is
        # starting in the background (id -> monotonic expiry) whose
        # ``pr start`` activation must not move the user's cursor.
        self._followed_active_pr: str | None = None
        self._quiet_activations: dict[str, float] = {}
        # Explicit per-PR opt-out of auto-merge (O key / CLI default).
        # When a PR is in this set, _maybe_auto_merge stops at "ready to
        # merge" instead of launching the merge window.  Wait-for-merge
        # holds are derived separately (auto_start.merge_holds).
        self._stop_before_merge: set[str] = set()
        # Watcher framework manager (purely in-memory, lost on TUI restart)
        from pm_core.watcher_manager import WatcherManager
        self._watcher_manager = WatcherManager()
        # w prefix key state
        self._w_mode: bool = False
        self._w_cancel_timer = None
        # y prefix key state (cleanup-then-action)
        self._y_mode: bool = False
        self._y_cancel_timer = None
        # Arrival number of the z/w/y prefix hint on the log line
        self._prefix_hint_seq: int | None = None
        # QA loop state (purely in-memory)
        self._qa_loops: dict = {}
        # Self-driving QA state (zz t — tracks pass counts per PR)
        self._self_driving_qa: dict = {}
        # Command-input race condition fix: buffer keystrokes between / and focus
        self._command_pending: bool = False
        self._command_buffer: list[str] = []

    def _consume_z(self) -> int:
        """Atomically read and clear the z modifier count.

        Returns 0 (no z), 1 (z), or 2 (zz).
        Non-zero is truthy, so ``if app._consume_z():`` still works
        for callers that only care about "was z pressed".
        """
        count = self._z_count
        self._z_count = 0
        self._stop_z_timer()
        return count

    def _stop_z_timer(self) -> None:
        """Cancel the z prefix's chord-window timer, if one is armed."""
        if self._z_cancel_timer:
            self._z_cancel_timer.stop()
            self._z_cancel_timer = None

    def _cancel_z_mode(self) -> None:
        """Auto-cancel a pending z prefix after its chord window."""
        if self._z_count:
            self._z_count = 0
            self._clear_prefix_hint()

    # --- Frame capture forwarder (called from ~15 sites) ---

    def _capture_frame(self, trigger: str = "unknown") -> None:
        # Frame capture shells out to ``tmux capture-pane`` (subprocess, up to a
        # 5s timeout).  Run it off the event-loop thread so a momentarily busy
        # tmux server can't stall navigation — this was an intermittent
        # multi-second freeze on a single PR move.  A single-flight guard drops
        # overlapping captures (a move triggers two: the log_message and the
        # explicit pr_selected capture), which also throttles bursts.
        if not tmux_mod.in_tmux():
            return
        if getattr(self, "_capture_in_flight", False):
            return
        self._capture_in_flight = True

        def _work() -> None:
            try:
                frame_capture.capture_frame(self, trigger)
            finally:
                self._capture_in_flight = False

        try:
            self.run_worker(_work, thread=True, exclusive=False, group="frame-capture")
        except Exception:
            self._capture_in_flight = False
            frame_capture.capture_frame(self, trigger)

    # --- Command execution forwarder (called from pane_ops.py) ---

    def _run_command(self, cmd: str, working_message: str | None = None,
                     action_key: str | None = None) -> None:
        pr_view.run_command(self, cmd, working_message=working_message,
                            action_key=action_key)

    # --- Compose and lifecycle ---

    def compose(self) -> ComposeResult:
        yield StatusBar(id="status-bar")
        yield SessionBar(id="session-bar")
        with Container(id="main-area"):
            with TreeScroll(id="tree-container"):
                yield TechTree(id="tech-tree")
            with Vertical(id="guide-progress-container"):
                yield GuideProgress(id="guide-progress")
            with Vertical(id="plans-container"):
                yield PlansPane(id="plans-pane")
            with Vertical(id="qa-container"):
                yield QAPane(id="qa-pane")
        yield LogLine(id="log-line")
        yield CommandBar(id="command-bar")

    def on_mount(self) -> None:
        import os
        try:
            from pm_core.tui import auto_start as _auto_start
            trigger = ("merge_restart"
                       if _auto_start.has_merge_restart_marker()
                       else "initial")
        except Exception:
            trigger = "initial"
        _log.info("TUI mount: pid=%d cwd=%s trigger=%s",
                  os.getpid(), Path.cwd(), trigger)
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
        # Opt-in keystroke-latency instrumentation (PM_PERF_DEBUG=1).
        from pm_core.tui import perf
        perf.setup_event_loop(self._session_name)
        # External-reload IPC: write a pidfile and install a SIGUSR1 handler
        # so CLI commands can ask us to reload state without depending on
        # tmux send-keys (which gets eaten by whichever widget has focus).
        self._install_reload_signal()
        # Sweep stale runtime_state entries from the previous TUI
        # process — a freshly-started TUI doesn't own any pane or loop
        # recorded by an old one, so anything still flagged as
        # running/idle/queued is no longer live.  Action mirrors will
        # rewrite real entries as panes register and loops resume.
        try:
            from pm_core import runtime_state as _rs
            _rs.sweep_stale_states("tui-mount")
        except Exception:
            _log.debug("runtime_state sweep on mount failed", exc_info=True)
        # Load any existing capture config
        frame_capture.load_capture_config(self)
        # Set up watchers on child widgets for frame capture
        frame_capture.setup_frame_watchers(self)

        # Load state and render immediately so the TUI shows content fast.
        # Defer heavier operations (heal_registry, tmux bindings, GitHub
        # sync) to after the first frame.
        self._load_state()
        self._update_orientation()
        # Start the coalescing write queue now that the project root is known.
        # TUI mutations enqueue here instead of writing to disk inline.
        #
        # Debounce is set well above human navigation cadence so a nav burst
        # collapses to a single write.  The only enqueued mutations are
        # low-stakes UI state (selected PR, hide_merged toggle) already applied
        # to ``self._data`` in memory immediately, so disk only needs to catch
        # up once navigation settles.  At the default 0.1s, scrolling through a
        # large project.yaml fires a full read+dump of the whole file after
        # nearly every keystroke — wasteful disk/CPU churn (the dump itself runs
        # on a worker thread, so it does not block the UI).  ``flush_sync`` on
        # exit/restart still persists the final state, so a longer window only
        # risks losing the last selection on an unclean crash.
        if self._root is not None:
            self._write_queue = store.WriteQueue(self._root, debounce=1.5)
            self.run_worker(self._write_queue.run(), exclusive=False)
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
        # Resume auto-start if a breadcrumb was left by a merge-triggered restart
        from pm_core.tui import auto_start
        await auto_start.consume_breadcrumb(self)
        # An explicit fresh autostart (z O / z A) is a user request that must
        # survive a plain TUI restart: re-add its target from the PR marker.
        # ``resume_pending`` logs each resumed PR itself (through
        # ``add_targets``'s confirmation); an extra aggregate line here would
        # only duplicate it.
        from pm_core.tui import autostart_fresh
        autostart_fresh.resume_pending(self)
        # Now dispatch external commands, including any that arrived while
        # the previous process was exec'ing (signal lost) or before the
        # breadcrumb restore above (which would have overwritten them).
        self._cmd_queue_ready = True
        self._drain_command_queue(startup=True)
        # These must run on the main thread (touch Textual state)
        self.run_worker(sync_mod.startup_github_sync(self))
        self._capture_frame("mount")

    def _deferred_startup_sync(self) -> None:
        """Blocking startup tasks run in a thread."""
        # Clean up any stale merge-lock from a previous crash
        try:
            from pm_core.paths import pm_home
            lock = pm_home() / "merge-lock"
            if lock.exists():
                _log.warning("Removing stale merge-lock file on startup")
                lock.unlink(missing_ok=True)
        except Exception:
            pass
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
                # A reflow at the new width can push the selected node off-screen
                # (a dependency chain's depth fixes its column, so narrowing scrolls
                # deep nodes out horizontally). Re-scroll the selection into view so
                # it stays visible after the resize, matching the nav/selection paths.
                tree.call_after_refresh(tree._scroll_selected_into_view)
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
        # Persist any pending in-memory mutations (e.g. a still-debouncing
        # active_pr from a nav burst) BEFORE re-reading disk.  Otherwise a
        # reload — including the SIGUSR1 state-only reload that an external
        # ``pm pr edit`` triggers — would replace ``self._data`` with stale
        # on-disk state, clobbering the user's un-flushed navigation, while
        # the write queue later flushes the navigated value to disk and leaves
        # the display and ``project.yaml`` permanently out of sync.  Flushing
        # first means the reload re-reads (and re-applies) what the user
        # actually navigated to.  No-op when nothing is pending.
        wq = getattr(self, "_write_queue", None)
        if wq is not None:
            wq.flush_sync()
        old_statuses = {p.get("id"): p.get("status")
                        for p in (self._data or {}).get("prs") or []}
        old_deps = {p.get("id"): list(p.get("depends_on") or [])
                    for p in (self._data or {}).get("prs") or []}
        try:
            # Only search for root on first load; reuse existing root for refreshes
            if self._root is None:
                self._root = store.find_project_root()
                _log.info("found project root: %s", self._root)
            self._data = store.load(self._root)
            _log.debug("loaded state from %s, %d PRs",
                       self._root, len(self._data.get("prs") or []))
            self._update_display()
            # A merge done outside the auto-merge path (``g``, CLI, another
            # session) or a ``pm pr edit --depends-on`` is only seen here;
            # let the scheduler prune completed targets and start
            # newly-unblocked or newly-in-scope PRs.
            from pm_core.tui import auto_start as _auto_start
            _auto_start.on_state_loaded(self, old_statuses, old_deps)
        except FileNotFoundError:
            _log.warning("no project.yaml found")
            self._root = None
            self._data = {}
        except store.ProjectYamlParseError as e:
            _log.warning("corrupt project.yaml, keeping previous state: %s", e)

        # Decide which view to show based on whether PRs exist
        prs = self._data.get("prs") or []
        if self._plans_visible:
            self._show_plans_view()
        elif self._qa_visible:
            self._show_qa_view()
        elif not prs:
            state, _ = guide.detect_state(self._root)
            self._show_guide_view(state)
        else:
            self._show_normal_view()

    def _show_guide_view(self, state: str) -> None:
        """Show the guide progress view during setup steps."""
        self._current_guide_step = state
        self._plans_visible = False
        self._qa_visible = False

        # Update guide progress widget
        guide_widget = self.query_one("#guide-progress", GuideProgress)
        guide_widget.update_step(state)

        # Show guide progress, hide tech tree, plans, and QA
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        qa_container = self.query_one("#qa-container")
        tree_container.styles.display = "none"
        guide_container.styles.display = "block"
        plans_container.styles.display = "none"
        qa_container.styles.display = "none"

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

    def _focus_view_widget(self, widget) -> None:
        """Focus *widget* unless the user is typing in the command bar.

        The ``_show_*_view`` methods also run on every ``_load_state`` —
        background reloads (auto-start progress, auto-review's sync
        ``pr review``, an external ``pm pr edit`` SIGUSR1).  Stealing focus
        then sends the rest of a half-typed command to the tree as hotkeys
        (``t`` starts QA, Enter opens the edit pane) and strands the text.
        """
        if self._command_bar_in_use():
            return
        widget.focus()

    def _command_bar_in_use(self) -> bool:
        """True while the user is typing a command (or has pressed ``/``
        and the command bar is about to take focus)."""
        cmd_bar = self.query_one("#command-bar", CommandBar)
        return bool(cmd_bar.has_focus or self._command_pending)

    def _show_normal_view(self) -> None:
        """Show the normal tech tree view."""
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        qa_container = self.query_one("#qa-container")
        tree_container.styles.display = "block"
        guide_container.styles.display = "none"
        plans_container.styles.display = "none"
        qa_container.styles.display = "none"
        self._current_guide_step = None
        self._plans_visible = False
        self._qa_visible = False
        # Restore status bar to normal view
        self._update_status_bar()
        self._focus_view_widget(self.query_one("#tech-tree", TechTree))
        # Capture frame after view change (use call_after_refresh to ensure screen is updated)
        self.call_after_refresh(self._capture_frame, "show_normal_view")

    # --- Log/status utilities ---

    def _update_status_bar(self, sync_state: str = "synced") -> None:
        """Update the status bar with current project info and filter state."""
        from pm_core.tui.tech_tree import STATUS_ICONS, SORT_FIELDS
        from pm_core.paths import get_global_setting
        if not self._data:
            return
        # When a mode-specific view owns the status bar, don't overwrite it
        # with the project status. Re-render the mode's bar instead so that
        # refresh / background sync keeps counters in sync.
        if self._qa_visible:
            self._update_qa_status_bar()
            return
        if self._plans_visible:
            self._update_plans_status_bar()
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
        # Sort field label (shown separately from filter)
        sort_text = ""
        if tree._sort_field:
            sort_text = dict(SORT_FIELDS).get(tree._sort_field, tree._sort_field)
        status_bar = self.query_one("#status-bar", StatusBar)
        watcher_status = ""
        if self._watcher_manager.is_any_running():
            watcher_status = "input_required" if self._watcher_manager.any_input_required() else "running"
        status_bar.update_status(
            project.get("name", "???"),
            project.get("repo", "???"),
            sync_state,
            pr_count=len(prs),
            filter_text=filter_text,
            sort_text=sort_text,
            show_assist=not get_global_setting("hide-assist"),
            auto_start=self._auto_start,
            auto_label=self._auto_start_label(),
            watcher_status=watcher_status,
        )
        self.query_one("#session-bar", SessionBar).refresh_session_info()

    def _follow_active_pr(self, tree, active_pr: str | None) -> None:
        """Move the tree cursor to *active_pr* when it changes.

        Only on a change (``pm pr select`` etc.), not on every refresh —
        otherwise any reload or auto-start target change snaps the cursor
        off the PR the user is about to press O/A on.  Activations from the
        auto-start scheduler's own background starts are skipped.
        """
        if not active_pr or active_pr == self._followed_active_pr:
            return
        self._followed_active_pr = active_pr
        import time as _time
        quiet_until = self._quiet_activations.pop(active_pr, 0.0)
        if quiet_until < _time.monotonic():
            tree.select_pr(active_pr)

    def _update_display(self) -> None:
        """Refresh all widgets with current data."""
        if not self._data:
            return

        self._update_status_bar()

        tree = self.query_one("#tech-tree", TechTree)
        tree.apply_project_settings(self._data.get("project", {}))
        tree.update_plans(self._data.get("plans") or [])
        tree.update_prs(self._data.get("prs") or [])
        self._follow_active_pr(tree, self._data.get("project", {}).get("active_pr"))
        self._update_filter_status()

        # Start animation timer if there are active PRs
        from pm_core.tui.review_loop_ui import ensure_animation_timer
        ensure_animation_timer(self)

    def _update_filter_status(self) -> None:
        """Update the status bar to reflect active filters."""
        self._update_status_bar()

    def log_message(self, msg: str, capture: bool = True, sticky: float = 0,
                    force: bool = False, hold: float = 0,
                    _seq: int | None = None) -> int:
        """Show a message in the log line; returns its arrival number.

        A non-sticky message is dropped while a sticky one is showing,
        unless *force* (used for confirmations the user must see, e.g. a
        CLI ``autostart remove``); forcing doesn't extend the sticky window.
        A forced hold replaces the old sticky protection with its own hold,
        so deferred progress can resume when that confirmation ends.

        *hold* keeps this message up for that many seconds against the
        follow-on messages it triggers in the same frame (e.g. auto-start's
        "starting <pr>" / "Review loop started" right after "targets +=").
        Unforced messages arriving during a hold — sticky ones included —
        are deferred, and the latest is shown when the hold ends. Another
        held message arriving during a hold is queued and shown (with its
        own hold) when the current hold ends, so back-to-back confirmations
        (e.g. a CLI "not a target" and a merged target's prune line) are
        each readable instead of the newer one replacing the older at once.

        Messages are numbered as they arrive (*_seq* is passed back only
        when a deferred or queued message is replayed). A replay never
        paints over a message that arrived after it: once a newer message
        is shown, older deferred/queued ones are dropped (they are still
        in ``L``).
        """
        import time as _time
        now = _time.monotonic()
        replay = _seq is not None
        if not replay:
            _seq = self._log_seq = getattr(self, "_log_seq", 0) + 1
        held = hold <= 0 and now < self._log_hold_until and not force
        suppressed = held or (
            sticky <= 0 and now < self._log_sticky_until and not force)
        # The log line holds one message and is overwritten (often within
        # the same tick), so also record every message in the command log
        # that ``L`` tails — otherwise status updates are lost unseen.
        if not replay:
            _record_log_message(self, msg, suppressed)
        if hold > 0 and now < self._log_hold_until:
            queue = getattr(self, "_log_held_queue", None)
            if queue is None:
                queue = self._log_held_queue = []
            if len(queue) >= _LOG_HELD_QUEUE_MAX:
                queue.pop(0)  # still in the L log; keep the newest
            queue.append((msg, capture, sticky, force, hold, _seq))
            return _seq
        if held:
            self._log_held = (msg, capture, sticky, _seq)
            return _seq
        if sticky > 0:
            self._log_sticky_until = now + sticky
        elif suppressed:
            return _seq  # a sticky message is still showing
        # Anything deferred or queued before this message is older than it;
        # flushing it when the hold ends would overwrite this newer one.
        # Only those: a replayed older message keeps newer deferred ones.
        self._log_shown_seq = _seq
        if self._log_held and self._log_held[-1] < _seq:
            self._log_held = None
        queue = getattr(self, "_log_held_queue", None)
        if queue:
            queue[:] = [q for q in queue if q[-1] > _seq]
        if hold > 0:
            # A forced hold replaces the old sticky line and its protection;
            # otherwise its deferred follow-up is dropped when the hold ends.
            if force and sticky <= 0:
                self._log_sticky_until = 0.0
            # Only a message that is actually shown holds the line.
            self._log_hold_until = now + hold
            self.set_timer(hold, self._flush_held_log_message)
        try:
            log = self.query_one("#log-line", LogLine)
            log.update(f" {msg}")
        except Exception:
            pass
        if capture:
            truncated = msg[:60].replace("\n", " ")
            self.call_after_refresh(self._capture_frame, f"log_message:{truncated}")
        return _seq

    def _flush_held_log_message(self) -> None:
        """Show what a ``log_message`` hold kept back: queued held
        confirmations first (oldest first), then the latest deferred
        message."""
        import time as _time
        if _time.monotonic() < self._log_hold_until:
            return  # a newer hold is active; its own timer flushes
        queue = getattr(self, "_log_held_queue", None)
        while queue:
            msg, capture, sticky, force, hold, seq = queue.pop(0)
            self.log_message(msg, capture=capture, sticky=sticky,
                             force=force, hold=hold, _seq=seq)
            if _time.monotonic() < self._log_hold_until:
                return  # shown and holding; its own timer flushes the rest
        held, self._log_held = self._log_held, None
        if held and held[-1] > getattr(self, "_log_shown_seq", 0):
            msg, capture, sticky, seq = held
            self.log_message(msg, capture=capture, sticky=sticky, _seq=seq)

    def log_error(self, title: str, detail: str = "", timeout: float = 5) -> None:
        """Show a red error in the log line that auto-clears."""
        msg = f"[red bold]{title}[/]"
        if detail:
            msg += f" {detail}"
        self.log_message(msg, sticky=timeout)
        self.clear_log_message_later(timeout)

    def clear_log_message_later(self, delay: float,
                                seq: int | None = None) -> None:
        """Clear a log-line message after *delay* seconds.

        Only that message — *seq* (as returned by ``log_message``), else the
        latest one: if a newer one (e.g. a held auto-start confirmation
        forced past it) has the line by then, it stays.
        """
        if seq is None:
            seq = getattr(self, "_log_seq", 0)
        self.set_timer(delay, lambda: self._clear_log_message(seq=seq))

    def _clear_log_message(self, seq: int | None = None) -> None:
        """Clear the log line message.

        With *seq*, only if that message is still the one on the line (or
        is still waiting behind a hold — then it is dropped instead).
        """
        if seq is not None:
            if self._log_held and self._log_held[-1] == seq:
                self._log_held = None  # expired before it was shown
                return
            if getattr(self, "_log_shown_seq", 0) != seq:
                return  # a newer message has the line
        self._log_sticky_until = 0.0
        try:
            log = self.query_one("#log-line", LogLine)
            log.update("")
        except Exception:
            pass

    # --- Sync delegates (see tui/sync.py) ---

    async def _background_sync(self) -> None:
        try:
            await sync_mod.background_sync(self)
        except SystemExit as e:
            import traceback
            _log.error("_background_sync raised SystemExit(%s):\n%s", e.code, traceback.format_exc())
        except BaseException as e:
            import traceback
            _log.error("_background_sync raised %s:\n%s", type(e).__name__, traceback.format_exc())
            raise

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

    def action_start_pr_companion(self) -> None:
        pr_view.start_pr(self, companion=True)

    def action_review_pr(self) -> None:
        z = self._consume_z()
        if z == 0:
            # plain d = mark in_review and open review window
            pr_view.review_pr(self)
        elif z == 1:
            # z d = kill any running loop and open a fresh review window
            review_loop_ui.stop_loop_or_fresh_review(self)
        else:
            # zz d = start a fresh review loop (supersedes any running)
            review_loop_ui.start_or_stop_loop(self)

    def action_merge_pr(self) -> None:
        pr_view.merge_pr(self)

    def action_signoff_pr(self) -> None:
        pr_view.signoff_pr(self)

    def action_merge_pr_companion(self) -> None:
        pr_view.merge_pr(self, companion=True)

    def action_hide_plan(self) -> None:
        pr_view.hide_plan(self)

    def action_toggle_merged(self) -> None:
        pr_view.toggle_merged(self)

    def action_cycle_filter(self) -> None:
        pr_view.cycle_filter(self)

    def action_cycle_sort(self) -> None:
        pr_view.cycle_sort(self)

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
        # ``A`` toggles an auto-merge target (continuation from the current
        # phase); ``z A`` is the explicit fresh-autostart variant: a
        # later-stage PR returns to implementation after feedback, keeps its
        # live session, and waits for the current implementation turn before
        # one fresh review.
        z = self._consume_z()
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if z:
            from pm_core.tui import autostart_fresh
            from pm_core.autostart_state import POLICY_AUTO
            if not pr_id:
                self.log_message(
                    "No PR selected (z A = fresh autostart, auto-merge)")
                return
            try:
                result = autostart_fresh.fresh_start(
                    self, [pr_id], policy=POLICY_AUTO, source="key:zA")
            except Exception as e:  # never let a key handler traceback
                _log.exception("z A fresh autostart failed for %s", pr_id)
                self.log_message(f"Auto-start fresh failed: {e}", force=True)
                return
            if not result.get("ok"):
                self.log_message(
                    f"Auto-start: {result.get('message')}", force=True)
            return
        from pm_core.tui.auto_start import toggle
        self.run_worker(toggle(self, selected_pr_id=pr_id))

    def _auto_start_label(self) -> str:
        """Status-bar suffix: ``×N`` for several targets, ``all`` for backlog."""
        from pm_core.tui import auto_start as _auto_start
        if not self._auto_start:
            return ""
        if _auto_start.is_all_mode(self):
            return "all"
        n = len(_auto_start.get_targets(self))
        return f"×{n}" if n > 1 else ""

    def action_show_auto_runs(self) -> None:
        from pm_core.tui import auto_start as _auto_start
        _auto_start.open_runs_popup(self)

    def action_auto_sequence_pr(self) -> None:
        # ``O`` arms a stop-before-merge auto-sequence target (continuation
        # from the current phase); ``z O`` is the explicit fresh-autostart
        # variant with the same stop-before-merge policy.
        z = self._consume_z()
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if not pr_id:
            if z:
                self.log_message(
                    "No PR selected (z O = fresh autostart, stop before merge)")
            else:
                self.log_message("No PR selected")
            return
        if z:
            from pm_core.tui import autostart_fresh
            from pm_core.autostart_state import POLICY_STOP
            try:
                result = autostart_fresh.fresh_start(
                    self, [pr_id], policy=POLICY_STOP, source="key:zO")
            except Exception as e:  # never let a key handler traceback
                _log.exception("z O fresh autostart failed for %s", pr_id)
                self.log_message(f"Auto-start fresh failed: {e}", force=True)
                return
            if not result.get("ok"):
                self.log_message(
                    f"Auto-start: {result.get('message')}", force=True)
            return
        from pm_core.tui.auto_start import auto_sequence_for_pr
        self.run_worker(auto_sequence_for_pr(self, pr_id))

    def _clear_prefix_hint(self) -> None:
        """Clear the z/w/y prefix hint — only it: a message that arrived
        after it (e.g. a held auto-start confirmation from a CLI command
        during the 2s prefix window) keeps the line."""
        self._clear_log_message(seq=self._prefix_hint_seq)

    def _cancel_w_mode(self) -> None:
        """Auto-cancel w prefix mode after timeout."""
        if self._w_mode:
            self._w_mode = False
            self._clear_prefix_hint()

    def _cancel_y_mode(self) -> None:
        """Auto-cancel y prefix mode after timeout."""
        if self._y_mode:
            self._y_mode = False
            self._clear_prefix_hint()

    def action_cleanup_pr(self) -> None:
        pr_view.cleanup_pr(self)

    def _action_focus_watcher(self) -> None:
        """Focus the watcher window (wf key chord)."""
        _log.info("action: focus_watcher")
        from pm_core.tui import watcher_ui

        session = self._session_name
        if not session:
            self.log_message("No tmux session found")
            return

        # Try to find and focus any running watcher's window
        watchers = self._watcher_manager.list_watchers()
        for w in watchers:
            win = tmux_mod.find_window_by_name(session, w["window_name"])
            if win:
                tmux_mod.select_window(session, w["window_name"])
                return

        # Check if a watcher is running but between iterations
        if self._watcher_manager.is_any_running():
            self.log_message("Watcher is between iterations — window will appear shortly")
            return

        # No watcher running — start one
        self._action_watcher_toggle()

    def _action_watcher_list(self) -> None:
        """Show list of all watchers and their status (ww key chord)."""
        _log.info("action: watcher_list")
        watchers = self._watcher_manager.list_watchers()

        if not watchers:
            self.log_message("[dim]No watchers registered. Press ws to start one.[/]")
            return

        lines = []
        for w in watchers:
            status = "[green]running[/]" if w["running"] else "[dim]stopped[/]"
            if w.get("input_required"):
                status = "[red bold]INPUT_REQUIRED[/]"
            verdict = w.get("verdict", "")
            iter_info = f"i{w['iteration']}" if w["iteration"] else ""
            lines.append(
                f"  {w['display_name']}: {status}"
                + (f" {verdict}" if verdict else "")
                + (f" ({iter_info})" if iter_info else "")
            )
        msg = "[bold]Watchers:[/]\n" + "\n".join(lines)
        self.log_message(msg, sticky=5)

    def _action_watcher_toggle(self) -> None:
        """Start or stop the auto-start watcher (ws key chord)."""
        _log.info("action: watcher_toggle")
        from pm_core.tui import watcher_ui

        # Check if auto-start watcher is running
        manager_watcher = self._watcher_manager.find_by_type("auto-start")

        if manager_watcher and manager_watcher.state.running:
            watcher_ui.stop_watcher(self)
            return

        # Start watcher
        from pm_core.tui import auto_start
        meta_root = watcher_ui.ensure_watcher_plans(self)
        tdir = auto_start.get_transcript_dir(self)
        watcher_ui.start_watcher(
            self,
            transcript_dir=str(tdir) if tdir else None,
            meta_pm_root=str(meta_root) if meta_root else None,
        )

    def _action_watcher_review(self) -> None:
        """Launch the watcher review session (wr key chord)."""
        _log.info("action: watcher_review")
        pane_ops.launch_watcher_review(self)

    def action_review_spec(self) -> None:
        """Open the oldest pending spec for review (V key)."""
        from pm_core import spec_gen
        _log.info("action: review_spec")

        pr_id = spec_gen.oldest_pending_spec_pr(self._data)
        if not pr_id:
            self.log_message("No specs pending review")
            return

        pr = store.get_pr(self._data, pr_id)
        if not pr:
            self.log_message(f"PR {pr_id} not found")
            return

        phase = spec_gen.get_pending_spec_phase(pr)
        if not phase:
            self.log_message(f"No pending spec for {pr_id}")
            return

        # Select this PR in the tree
        tree = self.query_one("#tech-tree", TechTree)
        tree.select_pr(pr_id)

        # Launch spec-approve in a pane
        pane_ops.launch_pane(self, f"pm pr spec-approve {pr_id}",
                             "spec-review", fresh=True)
        self.log_message(f"Reviewing {phase} spec for {pr_id}")

    def action_quit(self) -> None:
        pane_ops.quit_app(self)

    def action_restart(self) -> None:
        from pm_core.tui import auto_start
        if auto_start.has_merge_restart_marker():
            auto_start.save_breadcrumb(self)
            _log.info("action_restart: reason=merge_restart_marker")
        else:
            _log.info("action_restart: reason=user")
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

    def _reload_pidfile(self) -> Path | None:
        """Path to this app's reload pidfile, keyed by tmux session name."""
        if not self._session_name:
            return None
        from pm_core.paths import pm_home
        return pm_home() / f"tui-{self._session_name}.pid"

    def _command_queue_file(self) -> Path | None:
        """Path to this app's external command queue, keyed by session name."""
        if not self._session_name:
            return None
        from pm_core.paths import pm_home
        return pm_home() / f"tui-{self._session_name}.cmd-queue"

    def _install_reload_signal(self) -> None:
        """Write pidfile and register signal handlers.

        SIGUSR1 → ``action_reload`` (state-only reload).
        SIGUSR2 → drain the per-session command queue file and dispatch
        each line through ``handle_command_submitted`` (same path as the
        in-TUI ``/`` command bar).  Lets external processes (popup
        picker, CLI helpers) submit commands without depending on
        focus-sensitive ``tmux send-keys`` timing.
        """
        import os
        import signal
        import asyncio
        pidfile = self._reload_pidfile()
        if pidfile is None:
            _log.debug("No session name yet, skipping signal-handler install")
            return
        try:
            pidfile.write_text(str(os.getpid()))
        except OSError as e:
            _log.debug("Could not write TUI pidfile %s: %s", pidfile, e)
            return
        # Pre-create the command queue file so external writers can
        # always open it for append without a race.  Open for append
        # rather than touch: the startup drain judges staleness by mtime.
        queue = self._command_queue_file()
        if queue is not None:
            try:
                with open(queue, "a"):
                    pass
            except OSError as e:
                _log.debug("Could not create TUI command queue %s: %s",
                           queue, e)
        try:
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(signal.SIGUSR1, self.action_reload)
            loop.add_signal_handler(signal.SIGUSR2, self._drain_command_queue)
            _log.info("Installed SIGUSR1 reload + SIGUSR2 cmd-queue handlers"
                      " (pidfile=%s, queue=%s)", pidfile, queue)
        except (NotImplementedError, RuntimeError) as e:
            # add_signal_handler isn't available on Windows; not relevant
            # for our tmux flow but log so it's visible if it ever fires.
            _log.debug("Could not install signal handlers: %s", e)

    def _drain_command_queue(self, startup: bool = False) -> None:
        """Read pending commands from the queue file and dispatch them.

        Each non-empty line is a command identical to what the in-TUI
        ``/`` command bar would submit.  We dispatch via the same
        ``handle_command_submitted`` path so behavior matches exactly.
        Commands are processed in FIFO order; the queue is truncated
        after a successful read.

        Until startup has restored state (``_cmd_queue_ready``) lines are
        left in the file; the *startup* drain then dispatches them unless
        the queue is stale (left behind by a TUI that died long ago).
        """
        from pm_core.tui import pr_view
        if not self._cmd_queue_ready:
            _log.info("queue dispatch: deferred until startup completes")
            return
        queue = self._command_queue_file()
        if queue is None or not queue.exists():
            return
        import fcntl
        import time as _time
        try:
            started = getattr(self, "_started_wall", None) or _time.time()
            stale = (startup and started - queue.stat().st_mtime
                     > _STARTUP_QUEUE_MAX_AGE)
        except OSError:
            stale = False
        try:
            # Take the same exclusive flock the appender uses around
            # write+signal so a racing append can't slip a line in
            # between our read and truncate (which would silently drop
            # it — the appender's later SIGUSR2 would then drain an
            # empty file).
            with open(queue, "r+") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    content = f.read()
                    f.seek(0)
                    f.truncate()
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError as e:
            _log.debug("Could not read TUI command queue %s: %s", queue, e)
            return
        if stale and content.strip():
            _log.warning("queue dispatch: discarding stale queued commands "
                         "on startup: %r", content.splitlines())
            return
        # Queued commands come from outside (``pm autostart``, the picker)
        # and their command-bar branches refocus the tree.  If the user is
        # typing a command of their own, hand focus back afterwards so the
        # rest of it isn't delivered to the tree as hotkeys.
        typing = self._command_bar_in_use()
        for line in content.splitlines():
            cmd = line.strip()
            if not cmd:
                continue
            _log.info("queue dispatch: cmd=%r", cmd)
            try:
                pr_view.handle_command_submitted(self, cmd)
                _log.info("queue dispatch: cmd=%r result=ok", cmd)
            except Exception:
                _log.exception("queue dispatch: cmd=%r result=exc", cmd)
        if typing and content.strip():
            # focus() is deferred (call_later), so this lands after any
            # tree.focus() the dispatched commands queued.
            self.query_one("#command-bar", CommandBar).focus()

    def on_unmount(self) -> None:
        """Clean up the reload pidfile and command queue on shutdown."""
        _log.info("TUI unmount: session=%s", self._session_name)
        # Flush any pending writes before the process goes away.
        if self._write_queue is not None:
            self._write_queue.flush_sync()
        for path in (self._reload_pidfile(), self._command_queue_file()):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError as e:
                    _log.debug("Could not remove TUI file %s: %s", path, e)

    def action_reload(self) -> None:
        """Reload state from disk without triggering PR sync.

        If a merge-lock marker exists, shows a MergeLockScreen overlay
        instead of reloading (pm/ files may be temporarily stashed).
        """
        from pm_core.paths import pm_home
        lock = pm_home() / "merge-lock"
        if lock.exists():
            # Show overlay if not already showing one
            if not any(isinstance(s, MergeLockScreen) for s in self.screen_stack):
                pr_id = ""
                try:
                    pr_id = lock.read_text().strip()
                except Exception:
                    pass
                _log.info("merge-lock detected for %s, showing overlay", pr_id)
                self.push_screen(MergeLockScreen(pr_id),
                                 callback=lambda _: self._load_state())
            return
        _log.info("action: reload (state only)")
        self._load_state()

    def action_focus_command(self) -> None:
        _log.debug("action: focus_command")
        self._command_pending = True
        self._command_buffer.clear()
        cmd_bar = self.query_one("#command-bar", CommandBar)
        cmd_bar.focus()

    def action_unfocus_command(self) -> None:
        self._command_pending = False
        self._command_buffer.clear()
        cmd_bar = self.query_one("#command-bar", CommandBar)
        if cmd_bar.has_focus:
            cmd_bar.value = ""
            if self._plans_visible:
                self.query_one("#plans-pane", PlansPane).focus()
            elif self._qa_visible:
                self.query_one("#qa-pane", QAPane).focus()
            else:
                self.query_one("#tech-tree", TechTree).focus()

    def action_show_help(self) -> None:
        _log.debug("action: show_help")
        self.push_screen(HelpScreen(in_plans=self._plans_visible, in_qa=self._qa_visible))

    # --- Plans view ---

    def _show_plans_view(self) -> None:
        """Show the plans list view."""
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        qa_container = self.query_one("#qa-container")
        tree_container.styles.display = "none"
        guide_container.styles.display = "none"
        plans_container.styles.display = "block"
        qa_container.styles.display = "none"
        self._plans_visible = True
        self._qa_visible = False
        self._current_guide_step = None
        self._refresh_plans_pane()
        plans_pane = self.query_one("#plans-pane", PlansPane)
        self._focus_view_widget(plans_pane)
        self._update_plans_status_bar()
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

    # --- QA view ---

    def _show_qa_view(self) -> None:
        """Show the QA instructions list view."""
        tree_container = self.query_one("#tree-container")
        guide_container = self.query_one("#guide-progress-container")
        plans_container = self.query_one("#plans-container")
        qa_container = self.query_one("#qa-container")
        tree_container.styles.display = "none"
        guide_container.styles.display = "none"
        plans_container.styles.display = "none"
        qa_container.styles.display = "block"
        self._qa_visible = True
        self._plans_visible = False
        self._current_guide_step = None
        self._refresh_qa_pane()
        qa_pane = self.query_one("#qa-pane", QAPane)
        self._focus_view_widget(qa_pane)
        self._update_qa_status_bar()
        self.call_after_refresh(self._capture_frame, "show_qa_view")

    def _update_qa_status_bar(self) -> None:
        from pm_core import qa_instructions
        if self._root:
            all_items = qa_instructions.list_all(self._root)
            total = (len(all_items.get("instructions", []))
                     + len(all_items.get("regression", []))
                     + len(all_items.get("artifacts", [])))
        else:
            total = 0
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update(f" [bold]QA[/bold]    {total} item(s)    [dim]Enter=run  e=edit  d=debug  a=add  q=back[/dim]")

    def _update_plans_status_bar(self) -> None:
        plans = (self._data or {}).get("plans") or []
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update(f" [bold]Plans[/bold]    {len(plans)} plan(s)    [dim]p=back to tree[/dim]")

    def _refresh_qa_pane(self) -> None:
        """Refresh the QA pane with current data."""
        from pm_core import qa_instructions
        if self._root:
            all_items = qa_instructions.list_all(self._root)
        else:
            all_items = {"instructions": [], "regression": [], "artifacts": []}
        qa_pane = self.query_one("#qa-pane", QAPane)
        qa_pane.update_items(all_items)

    def action_toggle_qa(self) -> None:
        """Toggle QA instructions pane."""
        _log.info("action: toggle_qa visible=%s", self._qa_visible)
        if self._qa_visible:
            self._show_normal_view()
        else:
            self._show_qa_view()

    def action_start_qa_on_pr(self) -> None:
        """Start QA on the selected PR.

        Keybinding variants:
          t      — one-shot QA run (or focus existing window)
          z t    — fresh start (stop running QA, kill old windows, restart)
          zz t   — start/stop QA loop
        """
        from pm_core.tui import qa_loop_ui
        tree = self.query_one("#tech-tree", TechTree)
        pr_id = tree.selected_pr_id
        if not pr_id:
            self.log_message("No PR selected")
            return
        z = self._consume_z()
        if z == 0:
            qa_loop_ui.focus_or_start_qa(self, pr_id)
        elif z == 1:
            qa_loop_ui.fresh_start_qa(self, pr_id)
        else:
            qa_loop_ui.start_or_stop_qa_loop(self, pr_id)

    def on_qaitem_selected(self, message: QAItemSelected) -> None:
        _log.debug("qa item selected: %s", message.item_id)

    def on_qaitem_activated(self, message: QAItemActivated) -> None:
        """Launch QA item (instruction or regression test)."""
        pane_ops.launch_qa_item(self, message.item_id)

    def on_qaaction(self, message: QAAction) -> None:
        """Handle QA pane action shortcuts (add, edit)."""
        message.stop()
        _log.info("qa action: %s (item=%s)", message.action, message.item_id)
        if message.action == "add":
            self.push_screen(
                QACreatePickerScreen(),
                callback=lambda r: self._on_qa_create_picker(r),
            )
        elif message.action == "edit":
            if message.item_id:
                parts = message.item_id.split(":", 1)
                if len(parts) == 2:
                    category, qa_id = parts
                    pane_ops.launch_pane(
                        self, f"pm qa edit {qa_id} --category {category}", "qa-edit"
                    )
            else:
                self.log_message("No QA item selected")
        elif message.action == "debug":
            if message.item_id:
                parts = message.item_id.split(":", 1)
                if len(parts) == 2:
                    _category, qa_id = parts
                    pane_ops.launch_pane(
                        self, f"pm qa debug --foreground {qa_id}", "qa-debug"
                    )
            else:
                self.log_message("No QA item selected")

    def _on_qa_create_picker(self, result) -> None:
        """Callback for QACreatePickerScreen.

        result is None on cancel, or (category, mode, name) on confirm.
        Maps the (category, mode) pair to the matching pm qa subcommand.
        """
        if not result:
            return
        category, mode, name = result
        # category: "instructions" / "regression" / "artifacts"
        # mode:     always "author" — the TUI picker only exposes the
        #           guided authoring flow; use `pm qa add-*` from the
        #           CLI for the scaffold-stub flow.
        suffix = {
            "instructions": "instruction",
            "regression":   "regression",
            "artifacts":    "artifact",
        }[category]
        cmd = f"pm qa {mode}-{suffix} {shlex.quote(name)}"
        pane_ops.launch_pane(self, cmd, f"qa-{mode}")

