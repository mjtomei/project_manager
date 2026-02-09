"""Tests pane widget for the TUI."""

from textual.widget import Widget
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from rich.console import RenderableType


class TestSelected(Message):
    """Fired when a test is highlighted."""
    def __init__(self, test_id: str) -> None:
        self.test_id = test_id
        super().__init__()


class TestActivated(Message):
    """Fired when Enter is pressed on a test."""
    def __init__(self, test_id: str) -> None:
        self.test_id = test_id
        super().__init__()


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

    def _scroll_selected_into_view(self) -> None:
        """Scroll the parent container to keep the selected test visible."""
        if not self._tests:
            return
        # Each test entry is exactly 3 lines: header, description, blank
        y = self.selected_index * 3
        from textual.geometry import Region
        node_region = Region(0, y, self.size.width or 40, 3)
        if self.parent:
            self.parent.scroll_to_region(node_region)

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
