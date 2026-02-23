"""Plans pane widget for the TUI."""

from textual.widget import Widget
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from rich.console import RenderableType

from pm_core.tui import item_message

PlanSelected, PlanActivated = item_message("Plan", "plan_id")


class PlanAction(Message):
    """Fired when a plan action shortcut is pressed."""
    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__()


class PlansPane(Widget):
    """Scrollable list of plans with descriptions and action shortcuts."""

    can_focus = True

    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._plans: list[dict] = []

    def _truncate(self, text: str, max_width: int) -> str:
        """Truncate text to max_width, adding ellipsis if needed."""
        if len(text) <= max_width:
            return text
        return text[: max_width - 1] + "\u2026"

    def update_plans(self, plans: list[dict]) -> None:
        """Update the plans data and refresh.

        Each dict should have: {id, name, file, status, intro, pr_count}
        """
        self._plans = plans
        # Clamp selected index
        if self._plans:
            if self.selected_index >= len(self._plans):
                self.selected_index = len(self._plans) - 1
        else:
            self.selected_index = 0
        self.refresh()

    @property
    def selected_plan_id(self) -> str | None:
        if not self._plans:
            return None
        if self.selected_index >= len(self._plans):
            return None
        return self._plans[self.selected_index]["id"]

    def render(self) -> RenderableType:
        output = Text()

        # Content width: widget width minus CSS padding (2 each side)
        content_width = (self.size.width - 4) if self.size.width > 8 else 60

        if not self._plans:
            output.append("No plans yet. Press ", style="dim")
            output.append("a", style="bold")
            output.append(" to add one.\n", style="dim")
        else:
            for i, plan in enumerate(self._plans):
                is_selected = (i == self.selected_index)
                plan_id = plan.get("id", "???")
                name = plan.get("name", "Untitled")
                status = plan.get("status", "draft")
                pr_count = plan.get("pr_count", 0)
                intro = plan.get("intro", "")

                # Selection arrow
                if is_selected:
                    output.append("▶ ", style="bold cyan")
                else:
                    output.append("  ")

                # Plan ID and name — truncate to fit one line
                suffix = f"  [{status}]"
                if pr_count:
                    suffix += f"  {pr_count} PR{'s' if pr_count != 1 else ''}"
                header = f"{plan_id}: {name}"
                header = self._truncate(header, content_width - 2 - len(suffix))
                output.append(header, style="bold cyan" if is_selected else "")
                output.append(suffix, style="dim")
                output.append("\n")

                # Show intro text indented — truncate to prevent wrapping
                if intro:
                    for line in intro.split("\n"):
                        line = line.strip()
                        if line:
                            line = self._truncate(line, content_width - 4)
                            output.append(f"    {line}\n", style="dim italic" if not is_selected else "italic")
                output.append("\n")

        # Footer with shortcuts — standard flow
        output.append("\n")
        output.append("  a", style="bold")
        output.append("=add  ", style="dim")
        output.append("v", style="bold")
        output.append("=view  ", style="dim")
        output.append("w", style="bold")
        output.append("=breakdown  ", style="dim")
        output.append("c", style="bold")
        output.append("=review  ", style="dim")
        output.append("l", style="bold")
        output.append("=load  ", style="dim")
        output.append("e", style="bold")
        output.append("=edit  ", style="dim")
        output.append("D", style="bold")
        output.append("=deps  ", style="dim")
        output.append("p", style="bold")
        output.append("=back\n", style="dim")

        return output

    def _entry_lines(self, plan: dict) -> int:
        """Return the number of rendered lines for a plan entry."""
        intro = plan.get("intro", "")
        intro_lines = sum(1 for line in intro.split("\n") if line.strip()) if intro else 0
        return 1 + intro_lines + 1  # header + intro lines + blank

    def _scroll_selected_into_view(self) -> None:
        """Scroll the parent container to keep the selected plan visible."""
        if not self._plans or not self.parent:
            return
        container = self.parent
        y_top = sum(self._entry_lines(p) for p in self._plans[: self.selected_index])
        h = self._entry_lines(self._plans[self.selected_index])
        viewport_h = container.size.height
        scroll_y = round(container.scroll_y)
        y_bottom = y_top + h
        if y_bottom > scroll_y + viewport_h:
            new_y = min(y_top, y_bottom - viewport_h)
        elif y_top < scroll_y:
            new_y = y_top
        else:
            return  # already visible
        container.scroll_to(y=new_y, animate=False, force=True)

    # Map keys to PlanAction strings — keep in sync with on_plan_action in app.py
    _KEY_ACTIONS: dict[str, str] = {
        "a": "add",
        "w": "breakdown",
        "D": "deps",
        "l": "load",
        "v": "view",
        "e": "edit",
        "c": "review",
    }

    def on_key(self, event) -> None:
        if not self.has_focus:
            return

        if event.key in ("up", "k"):
            if self._plans and self.selected_index > 0:
                self.selected_index -= 1
                self.refresh()
                self._scroll_selected_into_view()
                self.post_message(PlanSelected(self.selected_plan_id))
            event.stop()
        elif event.key in ("down", "j"):
            if self._plans and self.selected_index < len(self._plans) - 1:
                self.selected_index += 1
                self.refresh()
                self._scroll_selected_into_view()
                self.post_message(PlanSelected(self.selected_plan_id))
            event.stop()
        elif event.key == "enter":
            if self.selected_plan_id:
                self.post_message(PlanActivated(self.selected_plan_id))
            event.stop()
        elif event.key in self._KEY_ACTIONS:
            self.post_message(PlanAction(self._KEY_ACTIONS[event.key]))
            event.stop()
