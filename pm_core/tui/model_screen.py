"""``o``: view and apply model / provider / effort settings.

Two views of one modal screen:

* the selected PR's roles: the effective model, effort and command of each
  role and which setting decided it; Enter picks a model or provider for
  the PR (first row: every role) or one role, ``e`` cycles the effort;
* the project: the same per role for project.yaml's ``model_config``,
  plus every configured provider with its route status.

``p`` switches between them.  Writes go through ``store.locked_update``
(pm_core.model_settings does the edit), so a busy project.yaml is reported
on the screen and nothing is half-written.  Providers themselves are
created and edited with ``pm provider`` (the screen names the command).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label

from pm_core import store
from pm_core.model_config import EFFORT_LEVELS
from pm_core.paths import configure_logger

_log = configure_logger("pm.tui.model_screen")

ALL_ROLES = "(all roles)"
CLEAR = "(clear)"
_EFFORT_CYCLE = (None, *EFFORT_LEVELS)


def escape(text: str) -> str:
    """Escape every ``[`` for Label markup.  rich's and textual's escape()
    skip brackets that start uppercase, and textual reads ``[OK]`` or
    ``[Done]`` as a tag and drops it.  Textual takes only the backslash
    right before a ``[`` as an escape; a trailing one gets a space so it
    cannot escape a closing tag that follows."""
    text = text.replace("[", "\\[")
    return text + " " if text.endswith("\\") else text


def model_choices(data: dict) -> list[str]:
    """Values offered by the picker: clear, every configured provider, then
    the plain model names already used in this project."""
    from pm_core.providers import list_providers
    choices = [CLEAR]
    choices += [f"provider:{p.name}" for p in list_providers()]
    seen = set(choices)
    used = []
    mc = ((data or {}).get("project") or {}).get("model_config")
    if isinstance(mc, dict) and isinstance(mc.get("session_models"), dict):
        used += list(mc["session_models"].values())
    for pr in (data or {}).get("prs") or []:
        if isinstance(pr, dict):
            used.append(pr.get("model"))
            if isinstance(pr.get("session_models"), dict):
                used += list(pr["session_models"].values())
    for value in used:
        if isinstance(value, str) and value.strip() and value not in seen:
            seen.add(value)
            choices.append(value)
    return choices


def next_effort(current: str | None) -> str | None:
    """The effort after *current* in (none, low, medium, high)."""
    try:
        i = _EFFORT_CYCLE.index(current)
    except ValueError:
        i = 0
    return _EFFORT_CYCLE[(i + 1) % len(_EFFORT_CYCLE)]


class ModelSettingsScreen(ModalScreen):
    """Per-role model settings of a PR or of the project."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
    ]

    CSS = """
    ModelSettingsScreen {
        align: center middle;
    }
    #model-container {
        width: auto;
        min-width: 60;
        max-width: 96%;
        height: auto;
        overflow-x: auto;
        max-height: 90%;
        background: $surface;
        border: solid $primary;
        padding: 1 2;
    }
    #model-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #model-status {
        margin-top: 1;
    }
    """

    def __init__(self, root, pr_id: str | None):
        super().__init__()
        self._root = root
        self._pr_id = pr_id
        self._project_view = pr_id is None
        self._selected = 0
        self._choosing: list[str] | None = None  # picker options when open
        self._choice = 0
        self._status = ""
        self._data: dict = {}
        # Provider lines (with a TCP check per router), built once per
        # screen rather than on every keypress or save (saves change
        # project.yaml, not providers.yaml).
        self._provider_cache: list[str] | None = None

    # -- data ---------------------------------------------------------

    def _load(self) -> None:
        try:
            self._data = store.load(self._root)
        except Exception as exc:  # unreadable project.yaml: say so
            self._data = {}
            self._status = f"[red]Cannot read project.yaml: {exc}[/]"

    def _pr(self) -> dict | None:
        if self._project_view or not self._pr_id:
            return None
        return store.get_pr(self._data, self._pr_id)

    def _rows(self):
        from pm_core import model_settings
        pr = self._pr()
        if not self._project_view and pr is None:
            return []
        return model_settings.role_rows(self._data, pr)

    def _targets(self) -> list[str | None]:
        """Selectable rows: None = every role (PR view only).  The roles
        _rows lists, without resolving them (called on every key)."""
        from pm_core.model_config import PR_SESSION_TYPES, SESSION_TYPES
        if self._project_view:
            return list(SESSION_TYPES)
        return [None, *(PR_SESSION_TYPES if self._pr() is not None else ())]

    # -- rendering ----------------------------------------------------

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="model-container"):
            yield Label("", id="model-title")
            yield Label("", id="model-body")
            yield Label("", id="model-status")

    def on_mount(self) -> None:
        self._load()
        self._refresh()

    def _refresh(self) -> None:
        title = ("Project model settings" if self._project_view
                 else f"Model settings for {self._pr_id}")
        self.query_one("#model-title", Label).update(title)
        lines: list[str] = []
        if self._choosing is not None:
            target = self._targets()[self._selected] or ALL_ROLES
            lines.append(f"Choose the model for {target}:")
            for i, value in enumerate(self._choosing):
                pointer = "▸ " if i == self._choice else "  "
                lines.append(pointer + escape(value))
            lines.append("")
            lines.append("[dim]Other model names: 'pm pr model set <pr> "
                         "<model>' or 'pm model set <type> <model> "
                         "--project'.  New providers: 'pm provider add'.[/]")
            lines.append("[dim]↑↓ choose  Enter apply  Esc back[/]")
        else:
            lines += self._table_lines()
            lines.append("")
            lines.append("[dim]↑↓ row  Enter set model  e cycle effort  "
                         f"p {'PR' if self._project_view else 'project'} view"
                         "  Esc close[/]")
        self.query_one("#model-body", Label).update("\n".join(lines))
        self.query_one("#model-status", Label).update(self._status)

    def _table_lines(self) -> list[str]:
        from pm_core import model_settings
        rows = self._rows()
        if not rows:
            return [f"[red]PR {escape(str(self._pr_id))} not found[/]"]
        lines = []
        pr = self._pr()
        offset = 0
        if pr is not None:
            offset = 1
            pointer = "▸ " if self._selected == 0 else "  "
            lines.append(
                f"{pointer}{ALL_ROLES}: model "
                f"{escape(str(pr.get('model') or '-'))}, effort "
                f"{escape(str(pr.get('effort') or '-'))}")
        table = model_settings.format_rows(rows)
        lines.append("  " + escape(table[0]))
        for i, line in enumerate(table[1:1 + len(rows)]):
            pointer = "▸ " if self._selected == i + offset else "  "
            lines.append(pointer + escape(line))
        for line in table[1 + len(rows):]:
            lines.append("[red]" + escape(line) + "[/]")
        if self._project_view:
            if self._provider_cache is None:
                self._provider_cache = self._provider_lines()
            lines.append("")
            lines += self._provider_cache
        return lines

    def _provider_lines(self) -> list[str]:
        from pm_core import worker_route
        from pm_core.model_config import ModelResolution
        from pm_core.providers import (
            get_default_provider, invalid_provider_entries, list_providers,
            providers_file_problem,
        )
        lines = ["Providers (~/.pm/providers.yaml; edit with 'pm provider "
                 "edit', details with 'pm provider show'):"]
        default = get_default_provider()
        for p in list_providers():
            mark = " (default)" if p.name == default else ""
            desc = f"  {p.name}{mark}  type={p.type}"
            if p.model:
                desc += f"  model={p.model}"
            if p.effort:
                desc += f"  effort={p.effort}"
            if p.launcher:
                desc += f"  command={p.launcher}"
            if p.type == "router":
                st = worker_route.check_route(
                    ModelResolution(provider=p.name))
                desc += "  [OK]" if st.ok else f"  [UNAVAILABLE: {st.problem}]"
            lines.append(escape(desc))
        for name, problem in invalid_provider_entries().items():
            lines.append(escape(f"  {name}  INVALID ENTRY: {problem}"))
        if (problem := providers_file_problem()):
            lines.append(escape(f"  NOT READ: {problem}"))
        return lines

    # -- input --------------------------------------------------------

    def on_key(self, event) -> None:
        key = event.key
        handled = True
        if self._choosing is not None:
            if key in ("up", "k"):
                self._choice = max(0, self._choice - 1)
            elif key in ("down", "j"):
                self._choice = min(len(self._choosing) - 1, self._choice + 1)
            elif key == "enter":
                value = self._choosing[self._choice]
                self._choosing = None
                self._apply("model", None if value == CLEAR else value)
            else:
                handled = False
        else:
            n = len(self._targets())
            if key in ("up", "k"):
                self._selected = max(0, self._selected - 1)
            elif key in ("down", "j"):
                self._selected = min(max(n - 1, 0), self._selected + 1)
            elif key == "enter" and n:
                self._choosing = model_choices(self._data)
                self._choice = 0
                self._status = ""
            elif key == "e" and n:
                self._apply("effort", next_effort(self._current_effort()))
            elif key == "p" and self._pr_id:
                self._project_view = not self._project_view
                self._selected = 0
                self._status = ""
            else:
                handled = False
        if handled:
            self._refresh()
            event.prevent_default()
            event.stop()

    def action_back(self) -> None:
        if self._choosing is not None:
            self._choosing = None
            self._refresh()
        else:
            self.dismiss(None)

    def _current_effort(self) -> str | None:
        """The effort the selected row itself sets (not the effective one)."""
        target = self._targets()[self._selected]
        if self._project_view:
            mc = ((self._data.get("project") or {}).get("model_config")
                  or {})
            efforts = mc.get("session_effort") if isinstance(mc, dict) else None
            return (efforts or {}).get(target) if isinstance(efforts, dict) else None
        pr = self._pr() or {}
        if target is None:
            return pr.get("effort")
        efforts = pr.get("session_effort")
        return efforts.get(target) if isinstance(efforts, dict) else None

    def _apply(self, kind: str, value: str | None) -> None:
        from pm_core import model_settings
        target = self._targets()[self._selected]
        if kind == "model" and value is not None:
            problem = model_settings.check_model_value(value)
            if problem:
                self._status = f"[red]{escape(problem)}[/]"
                return
        pr_id, project_view = self._pr_id, self._project_view

        def edit(data):
            if project_view:
                model_settings.set_project_value(data, kind, target, value)
                return
            pr = store.get_pr(data, pr_id)
            if pr is None:
                raise ValueError(f"PR {pr_id} not found")
            model_settings.set_pr_value(pr, kind, value,
                                        [target] if target else None)

        try:
            store.locked_update(self._root, edit)
        except (store.StoreLockTimeout, store.ProjectYamlParseError,
                ValueError) as exc:
            self._status = f"[red]Not saved: {escape(str(exc))}[/]"
            return
        scope = target or ALL_ROLES
        where = "project" if project_view else pr_id
        shown = value if value is not None else "cleared"
        self._status = (f"[green]{where}: {kind} for {scope} -> "
                        f"{escape(shown)}[/] [dim](new launches use it)[/]")
        _log.info("model settings: %s %s %s -> %s", where, scope, kind, shown)
        self._load()
        app = self.app
        try:
            from pm_core.tui.qa_loop_ui import _reload_tree
            _reload_tree(app)
        except Exception:
            _log.exception("model settings: tree reload failed")
