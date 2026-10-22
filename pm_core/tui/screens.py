"""Modal screens for Project Manager TUI."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.geometry import Region
from textual.widgets import Label, Static
from textual.screen import ModalScreen


class MergeLockScreen(ModalScreen):
    """Overlay shown while pm/ files are stashed during merge.

    Polls for the merge-lock marker file and auto-dismisses when it
    disappears, then triggers a state reload.  Users can press Escape
    to force-dismiss (removes the lock file) in case the merge process
    crashed.
    """

    BINDINGS = [
        Binding("escape", "force_dismiss", "Force close", show=False),
    ]

    CSS = """
    MergeLockScreen {
        align: center middle;
    }
    #merge-lock-container {
        width: 50;
        height: auto;
        background: $surface;
        border: solid $warning;
        padding: 1 2;
    }
    #merge-lock-title {
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }
    #merge-lock-msg {
        text-align: center;
    }
    #merge-lock-hint {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
        display: none;
    }
    """

    _DOT_FRAMES = ("", ".", "..", "...")
    _HINT_AFTER_TICKS = 34  # ~10 seconds at 0.3s interval

    def __init__(self, pr_display_id: str = ""):
        super().__init__()
        self._pr_display_id = pr_display_id
        self._dot_index = 0
        self._tick_count = 0

    @property
    def _prefix(self) -> str:
        if self._pr_display_id:
            return f"Merging {self._pr_display_id}, please wait"
        return "Merge in progress, please wait"

    def compose(self) -> ComposeResult:
        with Vertical(id="merge-lock-container"):
            yield Label("Merging...", id="merge-lock-title")
            yield Label(self._prefix + "...", id="merge-lock-msg")
            yield Label("[dim]Press Esc to force close[/]", id="merge-lock-hint")

    def on_mount(self) -> None:
        self.set_interval(0.3, self._tick)

    def _tick(self) -> None:
        """Advance the dot animation and check if the lock file was removed."""
        self._tick_count += 1
        self._dot_index = (self._dot_index + 1) % len(self._DOT_FRAMES)
        self.query_one("#merge-lock-msg", Label).update(
            self._prefix + self._DOT_FRAMES[self._dot_index]
        )

        # Show escape hint after ~10 seconds
        if self._tick_count == self._HINT_AFTER_TICKS:
            self.query_one("#merge-lock-hint", Label).styles.display = "block"

        from pm_core.paths import pm_home
        if not (pm_home() / "merge-lock").exists():
            self.dismiss()

    def action_force_dismiss(self) -> None:
        """Remove the lock file and dismiss — escape hatch for stale locks."""
        from pm_core.paths import pm_home
        lock = pm_home() / "merge-lock"
        lock.unlink(missing_ok=True)
        self.dismiss()


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
        Binding("h", "discuss", "Discuss"),
        Binding("j", "scroll_down", "Scroll down", show=False),
        Binding("k", "scroll_up", "Scroll up", show=False),
        Binding("J", "page_down", "Page down", show=False),
        Binding("K", "page_up", "Page up", show=False),
        Binding("down", "scroll_down", "Scroll down", show=False),
        Binding("up", "scroll_up", "Scroll up", show=False),
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

    def __init__(self, in_plans: bool = False, in_qa: bool = False):
        super().__init__()
        self._in_plans = in_plans
        self._in_qa = in_qa

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-container"):
            yield Label("Keyboard Shortcuts", id="help-title")
            if self._in_qa:
                yield Label("QA Navigation", classes="help-section")
                yield Label("  [bold]↑↓[/] or [bold]jk[/]  Move selection", classes="help-row")
                yield Label("  [bold]Enter[/]  Run selected item", classes="help-row")
                yield Label("  [bold]e[/]  Edit item", classes="help-row")
                yield Label("  [bold]a[/]  Add instruction", classes="help-row")
                yield Label("  [bold]q[/]  Back to tree view", classes="help-row")
            elif self._in_plans:
                yield Label("Plan Navigation", classes="help-section")
                yield Label("  [bold]↑↓[/] or [bold]jk[/]  Move selection", classes="help-row")
                yield Label("  [bold]Enter[/]  View plan file", classes="help-row")
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
                yield Label("  [bold]↑↓←→[/] or [bold]hjkl[/]  Move selection", classes="help-row")
                yield Label("  [bold]J/K[/]  Jump to next/prev plan", classes="help-row")
                yield Label("  [bold]x[/]  Hide/show plan group", classes="help-row")
                yield Label("  [bold]X[/]  Toggle merged PRs", classes="help-row")
                yield Label("  [bold]f[/]  Cycle status filter", classes="help-row")
                yield Label("  [bold]F[/]  Cycle sort field", classes="help-row")
                yield Label("PR Actions", classes="help-section")
                yield Label("  [bold]s[/]  Start selected PR", classes="help-row")
                yield Label("  [bold]d[/]  Review (zz d: loop)", classes="help-row")
                yield Label("  [bold]g[/]  Merge PR", classes="help-row")
                yield Label("  [bold]i[/]  Sign-off (router)", classes="help-row")
                yield Label("  [bold]e[/] / [bold]Enter[/]  Edit selected PR", classes="help-row")
                yield Label("  [bold]v[/]  View plan file", classes="help-row")
                yield Label("  [bold]M[/]  Move to plan", classes="help-row")
                yield Label("  [bold]O[/]  Auto-start target (stop before merge)", classes="help-row")
                yield Label("  [bold]A[/]  Toggle auto-merge target", classes="help-row")
                yield Label("  [bold]a[/]  Auto-start runs popup", classes="help-row")
                yield Label("  [bold]V[/]  Review oldest pending spec", classes="help-row")
                yield Label("  [bold]w[/]  Focus watcher window", classes="help-row")
            yield Label("Panes & Views", classes="help-section")
            if not self._in_plans:
                yield Label("  [bold]c[/]  Launch Claude session", classes="help-row")
            yield Label("  [bold]H[/]  Launch guide (setup or assist)", classes="help-row")
            yield Label("  [bold]/[/]  Open command bar", classes="help-row")
            yield Label("  [bold]n[/]  Open notes", classes="help-row")
            yield Label("  [bold]m[/]  Meta: work on pm itself", classes="help-row")
            yield Label("  [bold]L[/]  View TUI log", classes="help-row")
            yield Label("  [bold]p[/]  Toggle plans view", classes="help-row")
            yield Label("  [bold]t[/]  Start QA on selected PR", classes="help-row")
            yield Label("  [bold]q[/]  Toggle QA instructions", classes="help-row")
            yield Label("  [bold]b[/]  Rebalance panes", classes="help-row")
            yield Label("Companion Pane", classes="help-section")
            yield Label("  [bold]S[/]  Start PR with companion pane", classes="help-row")
            yield Label("  [bold]G[/]  Merge with companion pane", classes="help-row")
            yield Label("Other", classes="help-section")
            yield Label("  [bold]z[/]  Modifier: kill existing before next", classes="help-row")
            yield Label("  [bold]r[/]  Refresh / sync with GitHub", classes="help-row")
            yield Label("  [bold]C[/]  Show shared connect command", classes="help-row")
            yield Label("  [bold]Ctrl+R[/]  Restart TUI", classes="help-row")
            yield Label("  [bold]?[/]  Show this help", classes="help-row")
            yield Label("  [bold]ctrl+b d[/]  Detach from session", classes="help-row")
            yield Label("Tmux Prefix Bindings", classes="help-section")
            yield Label("  [bold]prefix P[/]  PR action picker popup (q/Esc to quit)", classes="help-row")
            yield Label("  [bold]prefix M[/]  pm command runner popup (Ctrl+C to quit)", classes="help-row")
            yield Label("  [bold]prefix R[/]  Rebalance panes", classes="help-row")
            yield Label("Review Loop", classes="help-section")
            yield Label("  [bold]zz d[/]  Start loop", classes="help-row")
            yield Label("  [bold]z d[/]   Kill loop, fresh review", classes="help-row")
            yield Label("QA Loop", classes="help-section")
            yield Label("  [bold]zz t[/]  Start QA loop", classes="help-row")
            yield Label("  [bold]z t[/]   Fresh start QA", classes="help-row")
            yield Label("")
            yield Label("[dim]Press Esc/? to close  |  h to discuss pm[/]", classes="help-row")

    def action_scroll_down(self) -> None:
        self.query_one("#help-container", VerticalScroll).scroll_down()

    def action_scroll_up(self) -> None:
        self.query_one("#help-container", VerticalScroll).scroll_up()

    def action_page_down(self) -> None:
        self.query_one("#help-container", VerticalScroll).scroll_page_down()

    def action_page_up(self) -> None:
        self.query_one("#help-container", VerticalScroll).scroll_page_up()

    def action_dismiss(self) -> None:
        self.app.pop_screen()

    def action_discuss(self) -> None:
        """Open a Claude pane to discuss the pm tool, then dismiss help."""
        self.app.pop_screen()
        from pm_core.tui import pane_ops
        pane_ops.launch_discuss(self.app)


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
    """

    def __init__(self, plans: list[dict], current_plan: str | None, pr_id: str):
        super().__init__()
        self._plans = plans
        self._current_plan = current_plan
        self._pr_id = pr_id
        self._selected = 0
        # Options: each plan + "No plan (standalone)"
        self._options: list[tuple[str | None, str]] = []  # (plan_id_or_None, display_label)
        for p in plans:
            self._options.append((p["id"], f"{p['id']}: {p.get('name', '')}"))
        self._options.append(("_standalone", "No plan (standalone)"))
        # Pre-select current plan
        for i, (pid, _) in enumerate(self._options):
            if pid == current_plan:
                self._selected = i
                break

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="picker-container"):
            yield Label(f"Move {self._pr_id} to plan:", id="picker-title")
            yield Label("", id="picker-options")
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
            self.dismiss(pid)
            event.prevent_default()
            event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)


class PlanAddScreen(ModalScreen):
    """Modal for creating a new plan — accepts a title or file path."""

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
            yield Label("Title or file path [dim](required)[/]", classes="plan-add-label")
            yield Input(placeholder="e.g. auth-refactor or plans/auth.md", id="plan-add-name")
            yield Label("[dim]Enter to create · Esc to cancel[/]")

    def on_mount(self) -> None:
        from textual.widgets import Input
        self.query_one("#plan-add-name", Input).focus()

    def on_input_submitted(self, event) -> None:
        from textual.widgets import Input
        name_input = self.query_one("#plan-add-name", Input)
        name = name_input.value.strip()
        if name:
            self.dismiss((name, ""))

    def action_cancel(self) -> None:
        self.dismiss(None)


class QACreatePickerScreen(ModalScreen):
    """Modal for picking which kind of QA file to author.

    Returns ``(category, mode, name)`` on confirm, where category is one
    of ``"instructions" / "regression" / "artifacts"``, mode is always
    ``"author"`` (guided Claude session — the TUI does not expose the
    scaffold-stub flow; use ``pm qa add-*`` from the CLI for that), and
    name is the file name the user typed. Returns ``None`` on cancel.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    QACreatePickerScreen {
        align: center middle;
    }
    #qa-create-container {
        width: 60;
        height: auto;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #qa-create-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    .qa-create-label {
        margin-top: 1;
    }
    #qa-create-container Input {
        border: none;
        height: 1;
        padding: 0 1;
        background: #333333;
    }
    #qa-create-container Input:focus {
        background: #444444;
    }
    """

    _OPTIONS = [
        ("instructions", "author", "Instruction"),
        ("regression",   "author", "Regression test"),
        ("artifacts",    "author", "Artifact recipe"),
    ]

    def __init__(self):
        super().__init__()
        self._selected = 0

    def compose(self) -> ComposeResult:
        from textual.widgets import Input
        with Vertical(id="qa-create-container"):
            yield Label("Create QA file", id="qa-create-title")
            yield Label("Name", classes="qa-create-label")
            yield Input(placeholder="e.g. login-flow-setup", id="qa-create-name")
            yield Label("Kind", classes="qa-create-label")
            yield Label("", id="qa-create-options")
            yield Label(
                "[dim]↑↓ change kind · Enter create · Esc cancel[/]",
                classes="qa-create-label",
            )

    def on_mount(self) -> None:
        from textual.widgets import Input
        self._refresh_options()
        self.query_one("#qa-create-name", Input).focus()

    def _refresh_options(self) -> None:
        lines = []
        for i, (_cat, _mode, label) in enumerate(self._OPTIONS):
            pointer = "▸ " if i == self._selected else "  "
            lines.append(f"{pointer}{label}")
        self.query_one("#qa-create-options", Label).update("\n".join(lines))

    def on_key(self, event) -> None:
        # Arrow keys move the radio selection even while the Input is focused.
        if event.key in ("up",):
            self._selected = max(0, self._selected - 1)
            self._refresh_options()
            event.prevent_default()
            event.stop()
        elif event.key in ("down",):
            self._selected = min(len(self._OPTIONS) - 1, self._selected + 1)
            self._refresh_options()
            event.prevent_default()
            event.stop()

    def on_input_submitted(self, event) -> None:
        from textual.widgets import Input
        name = self.query_one("#qa-create-name", Input).value.strip()
        if not name:
            return
        category, mode, _label = self._OPTIONS[self._selected]
        self.dismiss((category, mode, name))

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmCleanupScreen(ModalScreen):
    """Confirm tearing down all live resources for a PR."""

    BINDINGS = [
        Binding("y", "confirm", "Yes", show=False),
        Binding("n", "cancel", "No", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    CSS = """
    ConfirmCleanupScreen {
        align: center middle;
    }
    #cleanup-container {
        width: 60;
        height: auto;
        background: $surface;
        border: solid $warning;
        padding: 1 2;
    }
    #cleanup-title {
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }
    .cleanup-line {
        margin-left: 2;
    }
    #cleanup-hint {
        text-align: center;
        margin-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, pr_display_id: str):
        super().__init__()
        self._pr_display_id = pr_display_id

    def compose(self) -> ComposeResult:
        with Vertical(id="cleanup-container"):
            yield Label(f"Clean up {self._pr_display_id}?", id="cleanup-title")
            yield Label("This will remove:")
            yield Label("• tmux windows (impl, review, merge, QA)", classes="cleanup-line")
            yield Label("• docker containers (all QA scenarios)", classes="cleanup-line")
            yield Label("• pane registry entries", classes="cleanup-line")
            yield Label("• push-proxy sockets", classes="cleanup-line")
            yield Label("[bold]y[/] confirm  [bold]n[/]/[bold]Esc[/] cancel", id="cleanup-hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class AutoRunsScreen(ModalScreen):
    """Live view of the auto-start target set and its runs (key ``a``).

    Renders ``auto_start.build_status(app)`` — the same
    ``pm.autostart.status/1`` dict that ``pm autostart status --json``
    returns — with the CLI report's layout (``autostart_view``: rows from
    ``autostart_state.status_rows``, wrapped to at most 99 columns, human
    waits in red).  Refreshes every 2s while open; Enter/f focuses the
    selected run's tmux window.
    """

    REFRESH_SECONDS = 2.0

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close", show=False),
        Binding("a", "close", "Close", show=False),
        Binding("j", "move(1)", "Down", show=False),
        Binding("k", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("up", "move(-1)", "Up", show=False),
        Binding("enter", "focus_run", "Focus window"),
        Binding("f", "focus_run", "Focus window", show=False),
        Binding("r", "refresh_runs", "Refresh"),
        # The popup may stay open indefinitely; it must not swallow the
        # Ctrl+R that `pm tui restart` / merge-triggered restarts send.
        Binding("ctrl+r", "restart_app", "Restart", show=False),
    ]

    # 99 report columns + 2 selection gutter + 1 scrollbar + padding/border.
    CSS = """
    AutoRunsScreen {
        align: center middle;
    }
    #runs-container {
        width: 106;
        max-width: 95%;
        height: auto;
        max-height: 85%;
        background: $surface;
        border: solid $primary;
        padding: 0 1;
        scrollbar-gutter: stable;
        scrollbar-size-vertical: 1;
    }
    #runs-body {
        width: 100%;
    }
    #runs-footer {
        color: $text-muted;
    }
    """

    # Selection gutter ("▶ ") in front of every row line.
    _GUTTER = 2

    _HINTS = ["j/k select", "Enter/f focus window", "r refresh",
              "Esc/q/a close", "refreshes every 2s"]

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[dict] = []
        self._status: dict = {}
        self._selected = 0
        self._selected_key: tuple | None = None
        self._timer = None
        # (row key, message) shown on the selected row's detail line.
        self._notice: tuple | None = None
        self._width = 0  # report width the body was last rendered at

    def compose(self) -> ComposeResult:
        container = VerticalScroll(id="runs-container")
        # Not focusable: a focused scroll container claims ↑/↓ for
        # scrolling once the rows overflow, so they would stop moving the
        # selection.  The selected row is scrolled into view instead.
        container.can_focus = False
        with container:
            yield Static("Auto-start runs", id="runs-title")
            yield Static("", id="runs-body")
            # Wrapped by _render_rows (no line starts with "·").
            yield Static(" · ".join(self._HINTS), id="runs-footer")

    def on_mount(self) -> None:
        self.action_refresh_runs()
        self._timer = self.set_interval(self.REFRESH_SECONDS,
                                        self.action_refresh_runs)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def on_resize(self, _event) -> None:
        if self._status:
            self._render_rows()

    @staticmethod
    def _row_key(rows: list[dict], idx: int) -> tuple | None:
        """(owning target, pr_id) — a shared dep appears once per target."""
        if not (0 <= idx < len(rows)):
            return None
        owner = None
        for r in rows[:idx + 1]:
            if r["kind"] in ("target", "run"):
                owner = r["pr_id"]
        return (owner, rows[idx]["pr_id"])

    def action_refresh_runs(self) -> None:
        from pm_core.tui import auto_start as _auto_start
        from pm_core.autostart_state import status_rows
        try:
            self._status = _auto_start.build_status(self.app)
        except Exception as e:  # never let a refresh tick kill the popup
            # Text, not markup: the exception text may contain brackets.
            from rich.text import Text
            self.query_one("#runs-body", Static).update(
                Text(f"status failed: {e}", style="red"))
            return
        self._rows = status_rows(self._status)
        # Keep the same run selected across refreshes when it still exists.
        if self._selected_key is not None:
            for i in range(len(self._rows)):
                if self._row_key(self._rows, i) == self._selected_key:
                    self._selected = i
                    break
        self._selected = max(0, min(self._selected, len(self._rows) - 1))
        self._selected_key = self._row_key(self._rows, self._selected)
        self._render_rows()

    def _report_width(self) -> int:
        """Columns available to the report (without the selection gutter):
        the body's laid-out width, or before layout the container's CSS
        width estimated from the screen; at most 99."""
        from pm_core.autostart_view import MAX_WIDTH
        width = self.query_one("#runs-body", Static).content_region.width
        if width <= 0:
            # width: 106 / max-width 95%, minus border, padding, scrollbar.
            width = min(106, int(self.app.size.width * 0.95)) - 5
        return max(20, min(MAX_WIDTH, width - self._GUTTER))

    def _render_rows(self) -> None:
        from rich.text import Text
        from pm_core import autostart_view as view
        st = self._status
        mode = st.get("mode", "off")
        width = self._report_width()
        self._width = width
        # The header has no selection gutter, but still stays within 99.
        title = Text("\n").join(
            view.to_rich(ln) for ln in view.header_lines(
                st, min(view.MAX_WIDTH, width + self._GUTTER),
                "Auto-start runs"))
        self.query_one("#runs-title", Static).update(title)
        self.query_one("#runs-footer", Static).update("\n".join(
            view.plain(ln) for ln in view.hint_lines(
                self._HINTS, width + self._GUTTER)))

        body = Text()
        body_widget = self.query_one("#runs-body", Static)
        row_texts: list[list[Text]] = []
        if mode == "off" or not self._rows:
            if mode == "off":
                body.append("No auto-start targets (auto-start off).\n", style="bold")
            else:
                body.append("No active runs.\n", style="bold")
            body.append("Add a target with O (stop before merge) or A on a PR,\n"
                        "or `pm autostart add PR_ID`.", style="dim")
            body_widget.update(body)
            return
        grouped = mode == "targets"
        names = view.display_names(st)
        for i, row in enumerate(self._rows):
            r = row["run"]
            sel = i == self._selected
            notice = None
            if sel and self._notice and self._notice[0] == self._selected_key:
                if r.get("window"):
                    # A refresh found a window since: the notice is stale.
                    self._notice = None
                else:
                    notice = self._notice[1]
            texts = []
            for n, ln in enumerate(view.row_lines(row, width, grouped=grouped,
                                                   notice=notice, names=names)):
                # A gray bar, not reverse: reverse would invert the red
                # attention label and reason on the selected row.
                line = Text("▶ " if sel and n == 0 else "  ",
                            style="on #444444" if sel else "")
                line.append_text(view.to_rich(ln))
                texts.append(line)
            for t in texts:
                if body:
                    body.append("\n")
                body.append_text(t)
            row_texts.append(texts)
        body_widget.update(body)
        # After the refresh: the body's width and the container's scrollable
        # height are only known once the new content has been laid out.
        self.call_after_refresh(self._scroll_selected_into_view, row_texts,
                                self._selected)

    def _scroll_selected_into_view(self, row_texts: list[list], selected: int
                                   ) -> None:
        """Scroll the container so row *selected* (a list of line Texts) is
        visible.  Re-renders first if the laid-out width differs from the
        width the rows were wrapped to (e.g. the first paint)."""
        if self._report_width() != self._width:
            self._render_rows()
            return
        if not (0 <= selected < len(row_texts)):
            return
        body = self.query_one("#runs-body", Static)
        width = body.content_region.width
        if width <= 0:
            return

        def height(lines) -> int:
            return sum(len(t.wrap(self.app.console, width)) for t in lines)

        top = body.virtual_region.y + sum(
            height(lines) for lines in row_texts[:selected])
        h = height(row_texts[selected])
        if selected == 0:  # keep the title in view at the top
            top, h = 0, top + h
        self.query_one("#runs-container", VerticalScroll).scroll_to_region(
            Region(0, top, 1, h), animate=False, immediate=True)

    def action_move(self, delta: int) -> None:
        if not self._rows:
            return
        self._selected = max(0, min(len(self._rows) - 1, self._selected + delta))
        self._selected_key = self._row_key(self._rows, self._selected)
        self._notice = None
        self._render_rows()

    def action_focus_run(self) -> None:
        if not (0 <= self._selected < len(self._rows)):
            return
        run = self._rows[self._selected]["run"]
        win = run.get("window")
        if not win:
            msg = f"No live window for {run['pr_id']}"
            self.app.log_message(msg)
            # On a short terminal the popup covers the app's log line, so
            # also show the notice on the selected row (always in view).
            self._notice = (self._selected_key, msg)
            self._render_rows()
            return
        session = getattr(self.app, "_session_name", None)
        self.action_close()
        if session:
            from pm_core import tmux as tmux_mod
            tmux_mod.select_window(session, win["id"])

    def action_restart_app(self) -> None:
        self.action_close()
        self.app.action_restart()

    def action_close(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.app.pop_screen()
