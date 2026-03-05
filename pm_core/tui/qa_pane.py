"""QA instructions pane widget for the TUI.

Replaces the old tests_pane.py.  Shows two sections with visual dividers:
1. QA Instructions — from pm/qa/instructions/
2. Regression Tests — from pm/qa/regression/
"""

from textual.message import Message
from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.console import RenderableType

from pm_core.tui import item_message

QAItemSelected, QAItemActivated = item_message("QAItem", "item_id")


class QAAction(Message):
    """Fired when a QA action shortcut is pressed (a=add, e=edit)."""
    def __init__(self, action: str, item_id: str | None = None) -> None:
        self.action = action
        self.item_id = item_id
        super().__init__()


class QAPane(Widget):
    """Scrollable list of QA instructions and regression tests."""

    can_focus = True

    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._items: list[dict] = []  # flat list with category markers

    def update_items(self, all_items: dict) -> None:
        """Update the items data and refresh.

        *all_items* should be {"instructions": [...], "regression": [...]}.
        """
        flat: list[dict] = []
        for category, label in [("instructions", "Instructions"),
                                ("regression", "Regression Tests")]:
            items = all_items.get(category, [])
            # Section header marker
            flat.append({"_section": label, "_count": len(items)})
            for item in items:
                flat.append({
                    **item,
                    "_category": category,
                    "_item_id": f"{category}:{item['id']}",
                })

        self._items = flat
        # Clamp selected index to selectable items
        self._clamp_index()
        self.refresh()

    def _selectable_indices(self) -> list[int]:
        """Return indices of selectable (non-header) items."""
        return [i for i, item in enumerate(self._items) if "_section" not in item]

    def _clamp_index(self) -> None:
        indices = self._selectable_indices()
        if not indices:
            self.selected_index = 0
            return
        if self.selected_index not in indices:
            # Find nearest selectable
            self.selected_index = indices[0]

    @property
    def selected_item_id(self) -> str | None:
        if not self._items:
            return None
        if self.selected_index >= len(self._items):
            return None
        item = self._items[self.selected_index]
        return item.get("_item_id")

    def _truncate(self, text: str, max_width: int) -> str:
        if len(text) <= max_width:
            return text
        return text[: max_width - 1] + "\u2026"

    def render(self) -> RenderableType:
        output = Text()
        content_width = (self.size.width - 4) if self.size.width > 8 else 60

        if not self._items:
            output.append("No QA items available.\n", style="dim")
        else:
            selectable = self._selectable_indices()
            for i, item in enumerate(self._items):
                if "_section" in item:
                    # Section header
                    label = item["_section"]
                    count = item["_count"]
                    output.append(f"\n  {label} ({count})\n", style="bold underline")
                    output.append("  " + "\u2500" * min(content_width - 2, 40) + "\n",
                                  style="dim")
                    continue

                is_selected = (i == self.selected_index)
                item_id = item.get("id", "???")
                title = item.get("title", "Untitled")
                description = item.get("description", "")

                if is_selected:
                    output.append("\u25b6 ", style="bold cyan")
                else:
                    output.append("  ")

                header = f"{item_id}: {title}"
                header = self._truncate(header, content_width - 2)
                output.append(header, style="bold cyan" if is_selected else "")
                output.append("\n")

                if description:
                    desc = self._truncate(description, content_width - 4)
                    output.append(f"    {desc}\n",
                                  style="dim italic" if not is_selected else "italic")
                output.append("\n")

        return output

    def _entry_lines(self, item: dict) -> int:
        if "_section" in item:
            return 3  # blank + header + divider
        return 3 if item.get("description") else 2

    def _scroll_selected_into_view(self) -> None:
        if not self._items or not self.parent:
            return
        container = self.parent
        y_top = sum(self._entry_lines(t) for t in self._items[: self.selected_index])
        h = self._entry_lines(self._items[self.selected_index])
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

        # 'a' (add) works even when the list is empty
        if event.key == "a":
            self.post_message(QAAction("add"))
            event.stop()
            return

        selectable = self._selectable_indices()
        if not selectable:
            return

        current_pos = selectable.index(self.selected_index) if self.selected_index in selectable else 0

        if event.key in ("up", "k"):
            if current_pos > 0:
                self.selected_index = selectable[current_pos - 1]
                self.refresh()
                self._scroll_selected_into_view()
                self.post_message(QAItemSelected(self.selected_item_id))
            event.stop()
        elif event.key in ("down", "j"):
            if current_pos < len(selectable) - 1:
                self.selected_index = selectable[current_pos + 1]
                self.refresh()
                self._scroll_selected_into_view()
                self.post_message(QAItemSelected(self.selected_item_id))
            event.stop()
        elif event.key == "enter":
            if self.selected_item_id:
                self.post_message(QAItemActivated(self.selected_item_id))
            event.stop()
        elif event.key == "e":
            self.post_message(QAAction("edit", self.selected_item_id))
            event.stop()
