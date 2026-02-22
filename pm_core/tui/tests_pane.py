"""Tests pane widget for the TUI."""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.console import RenderableType

from pm_core.tui import item_message

TestSelected, TestActivated = item_message("Test", "test_id")


class TestsPane(Widget):
    """Scrollable list of TUI tests with descriptions."""

    can_focus = True

    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._tests: list[dict] = []

    def update_tests(self, tests: list[dict]) -> None:
        """Update the tests data and refresh.

        Each dict should have: {id, name, description}
        """
        self._tests = tests
        # Clamp selected index
        if self._tests:
            if self.selected_index >= len(self._tests):
                self.selected_index = len(self._tests) - 1
        else:
            self.selected_index = 0
        self.refresh()

    @property
    def selected_test_id(self) -> str | None:
        if not self._tests:
            return None
        if self.selected_index >= len(self._tests):
            return None
        return self._tests[self.selected_index]["id"]

    def _truncate(self, text: str, max_width: int) -> str:
        """Truncate text to max_width, adding ellipsis if needed."""
        if len(text) <= max_width:
            return text
        return text[: max_width - 1] + "\u2026"

    def render(self) -> RenderableType:
        output = Text()

        # Content width: widget width minus CSS padding (2 each side)
        content_width = (self.size.width - 4) if self.size.width > 8 else 60

        if not self._tests:
            output.append("No tests available.\n", style="dim")
        else:
            for i, test in enumerate(self._tests):
                is_selected = (i == self.selected_index)
                test_id = test.get("id", "???")
                name = test.get("name", "Untitled")
                description = test.get("description", "")

                # Selection arrow
                if is_selected:
                    output.append("\u25b6 ", style="bold cyan")
                else:
                    output.append("  ")

                # Test ID and name — truncate to fit one line
                header = f"{test_id}: {name}"
                header = self._truncate(header, content_width - 2)
                output.append(header, style="bold cyan" if is_selected else "")
                output.append("\n")

                # Description indented — truncate to prevent wrapping
                if description:
                    desc = self._truncate(description, content_width - 4)
                    output.append(f"    {desc}\n", style="dim italic" if not is_selected else "italic")
                output.append("\n")

        # Footer with shortcuts
        output.append("\n")
        output.append("  Enter", style="bold")
        output.append("=run  ", style="dim")
        output.append("T", style="bold")
        output.append("=back\n", style="dim")

        return output

    def _entry_lines(self, test: dict) -> int:
        """Return the number of rendered lines for a test entry."""
        return 3 if test.get("description") else 2  # header + optional desc + blank

    def _scroll_selected_into_view(self) -> None:
        """Scroll the parent container to keep the selected test visible."""
        if not self._tests or not self.parent:
            return
        container = self.parent
        y_top = sum(self._entry_lines(t) for t in self._tests[: self.selected_index])
        h = self._entry_lines(self._tests[self.selected_index])
        viewport_h = container.size.height
        scroll_y = round(container.scroll_y)
        y_bottom = y_top + h
        if y_bottom > scroll_y + viewport_h:
            new_y = min(y_top, y_bottom - viewport_h)
        elif y_top < scroll_y:
            new_y = y_top
        else:
            return
        container.scroll_to(y=new_y, animate=False, force=True)

    def on_key(self, event) -> None:
        if not self.has_focus:
            return

        if event.key in ("up", "k"):
            if self._tests and self.selected_index > 0:
                self.selected_index -= 1
                self.refresh()
                self._scroll_selected_into_view()
                self.post_message(TestSelected(self.selected_test_id))
            event.prevent_default()
        elif event.key in ("down", "j"):
            if self._tests and self.selected_index < len(self._tests) - 1:
                self.selected_index += 1
                self.refresh()
                self._scroll_selected_into_view()
                self.post_message(TestSelected(self.selected_test_id))
            event.prevent_default()
        elif event.key == "enter":
            if self.selected_test_id:
                self.post_message(TestActivated(self.selected_test_id))
            event.prevent_default()
