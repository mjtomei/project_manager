"""Modal screens for Project Manager TUI."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Label
from textual.screen import ModalScreen


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
    """Modal help screen with two pages: keybindings and command reference.

    Press ``?`` to open (keybindings page).  Press ``h``/``H`` inside
    the help screen to toggle to the CLI command reference.
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("h", "toggle_commands", "Commands", show=False),
        Binding("H", "toggle_commands", "Commands", show=False),
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
    #commands-container {
        width: 70;
        height: auto;
        max-height: 80%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
        display: none;
    }
    #help-title, #commands-title {
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
        self._showing_commands = False

    def compose(self) -> ComposeResult:
        # Page 1: Keybindings
        with VerticalScroll(id="help-container"):
            yield Label("Keyboard Shortcuts", id="help-title")
            if self._in_tests:
                yield Label("Test Navigation", classes="help-section")
                yield Label("  [bold]↑↓[/] or [bold]jk[/]  Move selection", classes="help-row")
                yield Label("  [bold]Enter[/]  Run selected test", classes="help-row")
                yield Label("  [bold]T[/]  Back to tree view", classes="help-row")
            elif self._in_plans:
                yield Label("Plan Navigation", classes="help-section")
                yield Label("  [bold]↑↓[/] or [bold]jk[/]  Move selection", classes="help-row")
                yield Label("  [bold]Enter[/]  View plan file", classes="help-row")
                yield Label("Plan Actions", classes="help-section")
                yield Label("  [bold]a[/]  Add a new plan", classes="help-row")
                yield Label("  [bold]v[/]  View plan file in pane", classes="help-row")
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
                yield Label("  [bold]F[/]  Cycle status filter", classes="help-row")
                yield Label("  [bold]Enter[/]  Edit selected PR", classes="help-row")
                yield Label("PR Actions", classes="help-section")
                yield Label("  [bold]s[/]  Start selected PR", classes="help-row")
                yield Label("  [bold]d[/]  Mark PR as done", classes="help-row")
                yield Label("  [bold]e[/]  Edit selected PR", classes="help-row")
                yield Label("  [bold]v[/]  View plan file", classes="help-row")
                yield Label("  [bold]M[/]  Move to plan", classes="help-row")
            yield Label("Panes & Views", classes="help-section")
            if not self._in_plans:
                yield Label("  [bold]c[/]  Launch Claude session", classes="help-row")
            yield Label("  [bold]H[/]  Launch guide (setup or assist)", classes="help-row")
            yield Label("  [bold]/[/]  Open command bar", classes="help-row")
            yield Label("  [bold]n[/]  Open notes", classes="help-row")
            yield Label("  [bold]m[/]  Meta: work on pm itself", classes="help-row")
            yield Label("  [bold]L[/]  View TUI log", classes="help-row")
            yield Label("  [bold]P[/]  Toggle plans view", classes="help-row")
            yield Label("  [bold]T[/]  Toggle tests view", classes="help-row")
            yield Label("  [bold]b[/]  Rebalance panes", classes="help-row")
            yield Label("Other", classes="help-section")
            yield Label("  [bold]z[/]  Modifier: kill existing before next", classes="help-row")
            yield Label("  [bold]r[/]  Refresh / sync with GitHub", classes="help-row")
            yield Label("  [bold]C[/]  Show connect command (shared sessions)", classes="help-row")
            yield Label("  [bold]Ctrl+R[/]  Restart TUI", classes="help-row")
            yield Label("  [bold]?[/]  Show this help", classes="help-row")
            yield Label("  [bold]q[/]  Detach from session", classes="help-row")
            yield Label("Review Loop", classes="help-section")
            yield Label("  [bold]zz d[/]  Start loop (stops on PASS/suggestions)", classes="help-row")
            yield Label("  [bold]zzz d[/]  Start strict loop (PASS only)", classes="help-row")
            yield Label("  [bold]z d[/]  Stop loop / fresh done", classes="help-row")
            yield Label("")
            yield Label("[dim]Press [bold]h[/bold] for command reference  |  Esc/q to close[/]", classes="help-row")
        # Page 2: Command reference (hidden by default)
        with VerticalScroll(id="commands-container"):
            yield Label("Command Reference", id="commands-title")
            from pm_core.cli import HELP_TEXT
            for line in HELP_TEXT.splitlines():
                yield Label(line or " ", classes="help-row")
            yield Label("")
            yield Label("[dim]Press [bold]h[/bold] for keybindings  |  Esc/q to close[/]", classes="help-row")

    def action_toggle_commands(self) -> None:
        """Toggle between keybindings page and command reference page."""
        help_c = self.query_one("#help-container")
        cmds_c = self.query_one("#commands-container")
        self._showing_commands = not self._showing_commands
        if self._showing_commands:
            help_c.styles.display = "none"
            cmds_c.styles.display = "block"
        else:
            help_c.styles.display = "block"
            cmds_c.styles.display = "none"

    def action_scroll_down(self) -> None:
        self._active_scroll().scroll_down()

    def action_scroll_up(self) -> None:
        self._active_scroll().scroll_up()

    def action_page_down(self) -> None:
        self._active_scroll().scroll_page_down()

    def action_page_up(self) -> None:
        self._active_scroll().scroll_page_up()

    def _active_scroll(self) -> VerticalScroll:
        cid = "#commands-container" if self._showing_commands else "#help-container"
        return self.query_one(cid, VerticalScroll)

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
        with VerticalScroll(id="picker-container"):
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
