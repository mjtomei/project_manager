"""Running tasks pane widget for the TUI.

Shows all active tasks detected from tmux windows in the current session,
grouped by type: Implementation, Review, QA, Watcher, Other.

Multi-window tasks (like QA with scenario windows) are collapsed to a single
entry by default and can be expanded with space/right arrow.
"""

import re

from textual.widget import Widget
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from rich.console import RenderableType

from pm_core.paths import configure_logger

_log = configure_logger("pm.tui.tasks_pane")


class TaskWindowSwitch(Message):
    """Fired when the user wants to switch to a task's tmux window."""
    def __init__(self, window_name: str) -> None:
        self.window_name = window_name
        super().__init__()


# Task type grouping
GROUP_ORDER = ["Implementation", "Review", "QA", "Watcher", "Other"]

# Spinner frames for active tasks
_SPINNER = "◐◓◑◒"

# Window name patterns → (group, pr_display_id_extractor)
# Order matters: more specific patterns first
_WINDOW_PATTERNS = [
    # QA scenario windows: qa-#128-s1, qa-pr-001-s2
    (re.compile(r"^qa-(#\d+|pr-[a-z0-9]+)-s(\d+)$"), "QA", "sub"),
    # QA main windows: qa-#128, qa-pr-001
    (re.compile(r"^qa-(#\d+|pr-[a-z0-9]+)$"), "QA", "main"),
    # Review windows: review-#128, review-pr-001
    (re.compile(r"^review-(#\d+|pr-[a-z0-9]+)$"), "Review", "main"),
    # Merge windows: merge-#128, merge-pr-001
    (re.compile(r"^merge-(#\d+|pr-[a-z0-9]+)$"), "Review", "main"),
    # Watcher window
    (re.compile(r"^watcher$"), "Watcher", "main"),
    # Implementation windows: #128, pr-001
    (re.compile(r"^(#\d+|pr-[a-z0-9]+)$"), "Implementation", "main"),
]


def _classify_window(name: str) -> tuple[str, str, str, str | None]:
    """Classify a tmux window by name.

    Returns (group, pr_display_id, role, sub_id) where:
    - group: one of GROUP_ORDER
    - pr_display_id: e.g. "#128" or "pr-001" or "" for non-PR windows
    - role: "main" or "sub"
    - sub_id: scenario number for QA sub-windows, else None
    """
    for pattern, group, role in _WINDOW_PATTERNS:
        m = pattern.match(name)
        if m:
            pr_id = m.group(1) if m.lastindex and m.lastindex >= 1 else ""
            sub_id = m.group(2) if role == "sub" and m.lastindex and m.lastindex >= 2 else None
            # Watcher has no PR ID
            if group == "Watcher":
                pr_id = ""
            return group, pr_id, role, sub_id
    return "Other", "", "main", None


class TaskEntry:
    """Represents a task in the tasks pane."""

    def __init__(self, group: str, pr_display_id: str, main_window: str,
                 window_index: str):
        self.group = group
        self.pr_display_id = pr_display_id
        self.main_window = main_window
        self.window_index = window_index
        self.sub_windows: list[tuple[str, str, str]] = []  # (name, index, sub_id)
        self.expanded = False
        # PR data (populated by refresh)
        self.pr_title: str = ""
        self.pr_id: str = ""
        self.pr_status: str = ""
        # Loop state markers
        self.review_loop_marker: str = ""
        self.qa_loop_marker: str = ""


class TasksPane(Widget):
    """Scrollable list of running tasks grouped by type."""

    can_focus = True

    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._entries: list[TaskEntry] = []
        self._flat_items: list[dict] = []  # flattened for rendering
        self._animation_frame: int = 0

    def advance_animation(self) -> None:
        """Advance spinner animation frame."""
        self._animation_frame = (self._animation_frame + 1) % len(_SPINNER)

    def update_tasks(self, windows: list[dict], prs: list[dict],
                     review_loops: dict, qa_loops: dict,
                     watcher_infos: list[dict] | None = None) -> None:
        """Update the task list from tmux windows and PR data.

        Args:
            windows: list of {id, index, name} from tmux list_windows
            prs: list of PR dicts from project data
            review_loops: dict of pr_id -> ReviewLoopState
            qa_loops: dict of pr_id -> QALoopState
            watcher_infos: list of dicts from WatcherManager.list_watchers()
        """
        # Build PR lookup by display ID
        pr_by_display: dict[str, dict] = {}
        for pr in prs:
            gh = pr.get("gh_pr_number")
            did = f"#{gh}" if gh else pr["id"]
            pr_by_display[did] = pr

        # Preserve expansion state from existing entries so polls don't collapse them
        old_expanded: dict[str, bool] = {}
        for e in self._entries:
            old_key = f"{e.group}:{e.pr_display_id}" if e.pr_display_id else f"{e.group}:{e.main_window}"
            old_expanded[old_key] = e.expanded

        # Classify windows and group into tasks
        tasks_by_key: dict[str, TaskEntry] = {}  # key = "group:pr_display_id" or window name

        # Skip the TUI window (index 0 / name "main")
        skip_names = {"main"}

        for win in windows:
            name = win["name"]
            if name in skip_names:
                continue

            group, pr_did, role, sub_id = _classify_window(name)

            # Build a grouping key
            if pr_did:
                key = f"{group}:{pr_did}"
            else:
                key = f"{group}:{name}"

            if key not in tasks_by_key:
                entry = TaskEntry(group, pr_did, name, win["index"])
                # Restore expansion state from previous poll
                entry.expanded = old_expanded.get(key, False)
                # Look up PR data
                if pr_did and pr_did in pr_by_display:
                    pr = pr_by_display[pr_did]
                    entry.pr_title = pr.get("title", "")
                    entry.pr_id = pr.get("id", "")
                    entry.pr_status = pr.get("status", "")
                tasks_by_key[key] = entry
            else:
                entry = tasks_by_key[key]

            if role == "sub":
                entry.sub_windows.append((name, win["index"], sub_id or ""))
                # Sort sub-windows by sub_id
                entry.sub_windows.sort(key=lambda x: int(x[2]) if x[2].isdigit() else 0)
            elif role == "main" and entry.main_window != name:
                # Multiple main windows for same group/PR — treat extras as sub
                entry.sub_windows.append((name, win["index"], ""))

        # Populate loop markers
        for key, entry in tasks_by_key.items():
            if entry.pr_id:
                loop = review_loops.get(entry.pr_id)
                if loop and loop.running:
                    icon = _SPINNER[self._animation_frame]
                    marker = f"{icon}{loop.iteration}"
                    if loop.latest_verdict:
                        marker += f" {loop.latest_verdict[:4]}"
                    entry.review_loop_marker = marker
                elif loop and loop.latest_verdict:
                    entry.review_loop_marker = loop.latest_verdict

                qa = qa_loops.get(entry.pr_id)
                if qa and qa.running:
                    icon = _SPINNER[self._animation_frame]
                    entry.qa_loop_marker = f"{icon}{qa.iteration}"
                elif qa and qa.latest_verdict:
                    entry.qa_loop_marker = qa.latest_verdict

            if entry.group == "Watcher" and watcher_infos:
                for wi in watcher_infos:
                    if wi.get("window_name") == entry.main_window and wi.get("running"):
                        icon = _SPINNER[self._animation_frame]
                        entry.review_loop_marker = f"{icon} active"
                        if wi.get("input_required"):
                            entry.review_loop_marker = "INPUT_REQ"
                        break

        # Sort and flatten
        self._entries = sorted(tasks_by_key.values(),
                               key=lambda e: (GROUP_ORDER.index(e.group)
                                              if e.group in GROUP_ORDER else 99,
                                              e.pr_display_id))
        self._build_flat_items()

        # Clamp selection
        selectable = self._selectable_indices()
        if selectable and self.selected_index not in selectable:
            self.selected_index = selectable[0] if selectable else 0

        self.refresh(layout=True)

    def _build_flat_items(self) -> None:
        """Build flat item list for rendering (headers + entries + sub-entries)."""
        flat: list[dict] = []
        current_group = None

        for entry in self._entries:
            if entry.group != current_group:
                current_group = entry.group
                flat.append({"_header": current_group, "_count": sum(
                    1 for e in self._entries if e.group == current_group)})

            flat.append({"_entry": entry})

            if entry.expanded and entry.sub_windows:
                for sub_name, sub_index, sub_id in entry.sub_windows:
                    flat.append({"_sub": True, "_name": sub_name,
                                 "_index": sub_index, "_sub_id": sub_id,
                                 "_parent": entry})

        self._flat_items = flat

    def _selectable_indices(self) -> list[int]:
        """Return indices of selectable (non-header) items."""
        return [i for i, item in enumerate(self._flat_items)
                if "_header" not in item]

    @property
    def selected_entry(self) -> TaskEntry | None:
        """Get the currently selected task entry."""
        if not self._flat_items or self.selected_index >= len(self._flat_items):
            return None
        item = self._flat_items[self.selected_index]
        if "_entry" in item:
            return item["_entry"]
        if "_sub" in item:
            return item.get("_parent")
        return None

    @property
    def selected_pr_id(self) -> str | None:
        """Get the PR ID of the currently selected task."""
        entry = self.selected_entry
        return entry.pr_id if entry else None

    @property
    def selected_window_name(self) -> str | None:
        """Get the window name to switch to for the current selection."""
        if not self._flat_items or self.selected_index >= len(self._flat_items):
            return None
        item = self._flat_items[self.selected_index]
        if "_sub" in item:
            return item["_name"]
        if "_entry" in item:
            return item["_entry"].main_window
        return None

    def _truncate(self, text: str, max_width: int) -> str:
        if len(text) <= max_width:
            return text
        return text[:max_width - 1] + "\u2026"

    def render(self) -> RenderableType:
        output = Text()
        content_width = (self.size.width - 4) if self.size.width > 8 else 60

        if not self._flat_items:
            output.append("No running tasks.\n", style="dim")
            output.append("\n")
            output.append("  Start a PR with ", style="dim")
            output.append("s", style="bold")
            output.append(" or launch a review with ", style="dim")
            output.append("d", style="bold")
            output.append(".\n", style="dim")
            output.append("\n")
            output.append("  Enter", style="bold")
            output.append("=switch  ", style="dim")
            output.append("Space", style="bold")
            output.append("=expand  ", style="dim")
            output.append("T", style="bold")
            output.append("=back\n", style="dim")
            return output

        for i, item in enumerate(self._flat_items):
            if "_header" in item:
                label = item["_header"]
                count = item["_count"]
                output.append(f"\n  {label} ({count})\n", style="bold underline")
                output.append("  " + "\u2500" * min(content_width - 2, 40) + "\n",
                              style="dim")
                continue

            is_selected = (i == self.selected_index)

            if "_sub" in item:
                # Sub-window entry (indented)
                sub_name = item["_name"]
                sub_id = item.get("_sub_id", "")
                if is_selected:
                    output.append("  \u25b6 ", style="bold cyan")
                else:
                    output.append("    ")

                label = f"\u2514 {sub_name}"
                if sub_id:
                    label = f"\u2514 scenario {sub_id}"
                label = self._truncate(label, content_width - 6)
                output.append(label, style="bold cyan" if is_selected else "dim")
                output.append("\n")
                continue

            entry: TaskEntry = item["_entry"]

            # Selection indicator
            if is_selected:
                output.append("\u25b6 ", style="bold cyan")
            else:
                output.append("  ")

            # Expand/collapse indicator for multi-window tasks
            if entry.sub_windows:
                if entry.expanded:
                    output.append("\u25bc ", style="dim")  # ▼
                else:
                    output.append("\u25b8 ", style="dim")  # ▸
            else:
                output.append("  ")

            # Window name / PR info
            if entry.pr_display_id:
                header = entry.pr_display_id
                if entry.pr_title:
                    # 4 chars prefix (cursor+expand, both always 2 chars each) + 1 space + 1 buffer = 6
                    title_space = content_width - len(header) - 6
                    if title_space > 5:
                        title = self._truncate(entry.pr_title, title_space)
                        header += f" {title}"
                output.append(header, style="bold cyan" if is_selected else "bold")
            else:
                output.append(entry.main_window,
                              style="bold cyan" if is_selected else "bold")

            # Status / loop markers
            markers = []
            if entry.pr_status:
                status_icons = {
                    "pending": "\u25cb",      # ○
                    "in_progress": "\u25ce",   # ◎
                    "in_review": "\u25c9",     # ◉
                    "qa": "\u25cf",            # ●
                    "merged": "\u2713",        # ✓
                }
                icon = status_icons.get(entry.pr_status, "")
                markers.append(icon)
            if entry.review_loop_marker:
                markers.append(entry.review_loop_marker)
            if entry.qa_loop_marker:
                markers.append(f"QA:{entry.qa_loop_marker}")
            if entry.sub_windows and not entry.expanded:
                markers.append(f"+{len(entry.sub_windows)}")

            if markers:
                output.append("  " + " ".join(markers), style="dim")

            output.append("\n")

        # Footer
        output.append("\n")
        output.append("  Enter", style="bold")
        output.append("=switch  ", style="dim")
        output.append("Space", style="bold")
        output.append("=expand  ", style="dim")
        output.append("T", style="bold")
        output.append("=back\n", style="dim")

        return output

    def _entry_lines(self, item: dict) -> int:
        if "_header" in item:
            return 3  # blank + header + divider
        return 1  # each entry/sub is one line

    def get_content_height(self, container, viewport, width) -> int:
        """Return the total content height so Textual can size the widget correctly."""
        if not self._flat_items:
            return 4  # "No running tasks." message (~3 lines + padding)
        # Sum all entry lines plus 2 for the footer (blank + footer text)
        return sum(self._entry_lines(item) for item in self._flat_items) + 2

    def _scroll_selected_into_view(self) -> None:
        if not self._flat_items or not self.parent:
            return
        container = self.parent
        y_top = sum(self._entry_lines(t) for t in self._flat_items[:self.selected_index])
        h = self._entry_lines(self._flat_items[self.selected_index])
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

    def _group_boundaries(self) -> list[int]:
        """Return flat indices of the first selectable item in each group."""
        boundaries = []
        seen_groups = set()
        selectable = set(self._selectable_indices())
        for i, item in enumerate(self._flat_items):
            if "_header" in item:
                group = item["_header"]
                if group not in seen_groups:
                    seen_groups.add(group)
                    # Find the first selectable item after this header
                    for j in range(i + 1, len(self._flat_items)):
                        if j in selectable:
                            boundaries.append(j)
                            break
        return boundaries

    def on_key(self, event) -> None:
        if not self.has_focus:
            return

        selectable = self._selectable_indices()
        if not selectable:
            return

        current_pos = (selectable.index(self.selected_index)
                       if self.selected_index in selectable else 0)

        if event.key in ("up", "k"):
            if current_pos > 0:
                self.selected_index = selectable[current_pos - 1]
                self.refresh()
                self._scroll_selected_into_view()
            event.stop()

        elif event.key in ("down", "j"):
            if current_pos < len(selectable) - 1:
                self.selected_index = selectable[current_pos + 1]
                self.refresh()
                self._scroll_selected_into_view()
            event.stop()

        elif event.key == "J":
            # Jump to next group
            boundaries = self._group_boundaries()
            for b in boundaries:
                if b > self.selected_index:
                    self.selected_index = b
                    self.refresh()
                    self._scroll_selected_into_view()
                    break
            event.stop()

        elif event.key == "K":
            # Jump to previous group
            boundaries = self._group_boundaries()
            for b in reversed(boundaries):
                if b < self.selected_index:
                    self.selected_index = b
                    self.refresh()
                    self._scroll_selected_into_view()
                    break
            event.stop()

        elif event.key in ("space", "right", "l"):
            # Toggle expand/collapse
            entry = self.selected_entry
            if entry and entry.sub_windows:
                entry.expanded = not entry.expanded
                self._build_flat_items()
                self.refresh(layout=True)
            event.stop()

        elif event.key in ("left", "h"):
            # Collapse if expanded
            entry = self.selected_entry
            if entry and entry.expanded:
                entry.expanded = False
                self._build_flat_items()
                # Re-select the parent entry
                for idx, item in enumerate(self._flat_items):
                    if "_entry" in item and item["_entry"] is entry:
                        self.selected_index = idx
                        break
                self.refresh(layout=True)
            event.stop()

        elif event.key == "enter":
            window = self.selected_window_name
            if window:
                self.post_message(TaskWindowSwitch(window))
            event.stop()
