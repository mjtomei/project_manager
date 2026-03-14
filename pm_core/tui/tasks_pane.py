"""Running tasks pane widget for the TUI.

Shows all active tasks detected from tmux windows in the current session,
grouped by type: Implementation, Review, QA, Watcher, Other.

Multi-window tasks (e.g. QA with scenario windows) are collapsed to a
single entry by default and can be expanded to reveal sub-windows.
"""

import re

from textual.widget import Widget
from textual.reactive import reactive
from textual.message import Message
from rich.text import Text
from rich.console import RenderableType

from pm_core.paths import configure_logger

_log = configure_logger("pm.tui.tasks_pane")

# Task type grouping order
TASK_GROUPS = [
    ("implementation", "Implementation"),
    ("review", "Review"),
    ("qa", "QA"),
    ("watcher", "Watcher"),
    ("other", "Other"),
]

SPINNER_FRAMES = "◐◓◑◒"

# Patterns for matching window names to task types and PR IDs.
# display_id is either #N (GitHub PR number) or pr-xxx (local ID).
_REVIEW_RE = re.compile(r"^review-(.+)$")
_MERGE_RE = re.compile(r"^merge-(.+)$")
_QA_MAIN_RE = re.compile(r"^qa-(.+?)(?:-s\d+)?$")
_QA_SCENARIO_RE = re.compile(r"^qa-(.+)-s(\d+)$")
_PR_DISPLAY_RE = re.compile(r"^#\d+$|^pr-.+$")
_WATCHER_NAMES = {"watcher", "auto-start"}


class TaskEntry:
    """A single task entry in the tasks pane."""

    __slots__ = (
        "task_type", "display_id", "pr_id", "pr_title", "pr_status",
        "window_name", "window_index", "sub_windows", "expanded",
        "loop_info", "verdict",
    )

    def __init__(
        self,
        task_type: str,
        display_id: str,
        window_name: str,
        window_index: str,
        *,
        pr_id: str = "",
        pr_title: str = "",
        pr_status: str = "",
        sub_windows: list[dict] | None = None,
        loop_info: str = "",
        verdict: str = "",
    ):
        self.task_type = task_type
        self.display_id = display_id
        self.pr_id = pr_id
        self.pr_title = pr_title
        self.pr_status = pr_status
        self.window_name = window_name
        self.window_index = window_index
        self.sub_windows = sub_windows or []
        self.expanded = False
        self.loop_info = loop_info
        self.verdict = verdict


class TaskSelected(Message):
    """Fired when a task is selected (cursor moved)."""
    def __init__(self, pr_id: str, window_name: str) -> None:
        self.pr_id = pr_id
        self.window_name = window_name
        super().__init__()


class TaskActivated(Message):
    """Fired when Enter is pressed on a task (switch to window)."""
    def __init__(self, window_name: str, window_index: str, pr_id: str = "") -> None:
        self.window_name = window_name
        self.window_index = window_index
        self.pr_id = pr_id
        super().__init__()


class TaskAction(Message):
    """Fired when a PR action shortcut is pressed in the tasks pane."""
    def __init__(self, action: str, pr_id: str = "") -> None:
        self.action = action
        self.pr_id = pr_id
        super().__init__()


class TasksPane(Widget):
    """Scrollable list of running tasks grouped by type."""

    can_focus = True

    selected_index: reactive[int] = reactive(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Flat list for rendering: mix of section headers and task entries
        self._items: list[dict] = []
        # Raw task entries grouped by type
        self._tasks: list[TaskEntry] = []
        self._anim_frame: int = 0
        self._session_name: str = ""

    def advance_frame(self) -> None:
        """Advance the spinner animation frame."""
        self._anim_frame = (self._anim_frame + 1) % len(SPINNER_FRAMES)
        self.refresh()

    def update_tasks(self, windows: list[dict], prs: list[dict],
                     session_name: str,
                     review_loops: dict | None = None,
                     qa_loops: dict | None = None) -> None:
        """Rebuild the task list from tmux windows and PR data.

        Args:
            windows: list of {id, index, name} from tmux.list_windows()
            prs: list of PR dicts from app._data["prs"]
            session_name: tmux session name
            review_loops: dict of pr_id -> ReviewLoopState
            qa_loops: dict of pr_id -> QALoopState
        """
        self._session_name = session_name
        review_loops = review_loops or {}
        qa_loops = qa_loops or {}

        # Build PR lookup: display_id -> pr dict
        pr_by_display: dict[str, dict] = {}
        pr_by_id: dict[str, dict] = {}
        for pr in prs:
            gh = pr.get("gh_pr_number")
            did = f"#{gh}" if gh else pr["id"]
            pr_by_display[did] = pr
            pr_by_id[pr["id"]] = pr

        # Classify windows into task entries
        tasks_by_type: dict[str, list[TaskEntry]] = {k: [] for k, _ in TASK_GROUPS}
        # Track QA groups for collapsing: display_id -> list of (window, scenario_idx)
        qa_groups: dict[str, list[dict]] = {}

        skip_names = {"main"}  # skip the main/TUI window

        for win in windows:
            name = win["name"]
            if name in skip_names:
                continue

            # Review window
            m = _REVIEW_RE.match(name)
            if m:
                did = m.group(1)
                pr = pr_by_display.get(did)
                # Look up loop info
                loop_info = ""
                verdict = ""
                if pr:
                    state = review_loops.get(pr["id"])
                    if state:
                        loop_info = f"i{state.iteration}" if state.iteration else ""
                        verdict = state.latest_verdict or ""
                tasks_by_type["review"].append(TaskEntry(
                    "review", did, name, win["index"],
                    pr_id=pr["id"] if pr else "",
                    pr_title=pr.get("title", "") if pr else "",
                    pr_status=pr.get("status", "") if pr else "",
                    loop_info=loop_info,
                    verdict=verdict,
                ))
                continue

            # Merge window
            m = _MERGE_RE.match(name)
            if m:
                did = m.group(1)
                pr = pr_by_display.get(did)
                tasks_by_type["review"].append(TaskEntry(
                    "review", did, name, win["index"],
                    pr_id=pr["id"] if pr else "",
                    pr_title=pr.get("title", "") if pr else "",
                    pr_status=pr.get("status", "") if pr else "",
                    loop_info="merge",
                ))
                continue

            # QA scenario window
            m = _QA_SCENARIO_RE.match(name)
            if m:
                did = m.group(1)
                qa_groups.setdefault(did, []).append(win)
                continue

            # QA main window
            m = _QA_MAIN_RE.match(name)
            if m and not _QA_SCENARIO_RE.match(name):
                did = m.group(1)
                qa_groups.setdefault(did, []).insert(0, win)
                continue

            # Watcher windows
            if name in _WATCHER_NAMES or name.startswith("watcher"):
                tasks_by_type["watcher"].append(TaskEntry(
                    "watcher", name, name, win["index"],
                ))
                continue

            # Implementation window (bare display_id like #128 or pr-xxx)
            if _PR_DISPLAY_RE.match(name):
                pr = pr_by_display.get(name)
                tasks_by_type["implementation"].append(TaskEntry(
                    "implementation", name, name, win["index"],
                    pr_id=pr["id"] if pr else "",
                    pr_title=pr.get("title", "") if pr else "",
                    pr_status=pr.get("status", "") if pr else "",
                ))
                continue

            # Other windows (meta, notes, container-build, etc.)
            tasks_by_type["other"].append(TaskEntry(
                "other", name, name, win["index"],
            ))

        # Build QA task entries with sub-windows
        for did, wins in qa_groups.items():
            pr = pr_by_display.get(did)
            # Sort by name to get main window first, then scenarios in order
            main_win = wins[0]
            sub_wins = wins[1:] if len(wins) > 1 else []
            # Look up QA loop info
            loop_info = ""
            verdict = ""
            if pr:
                state = qa_loops.get(pr["id"])
                if state:
                    loop_info = f"i{state.iteration}" if hasattr(state, "iteration") and state.iteration else ""
                    verdict = state.latest_verdict if hasattr(state, "latest_verdict") else ""
            entry = TaskEntry(
                "qa", did, main_win["name"], main_win["index"],
                pr_id=pr["id"] if pr else "",
                pr_title=pr.get("title", "") if pr else "",
                pr_status=pr.get("status", "") if pr else "",
                sub_windows=[{"name": w["name"], "index": w["index"]} for w in sub_wins],
                loop_info=loop_info,
                verdict=verdict,
            )
            tasks_by_type["qa"].append(entry)

        # Build flat items list with section headers
        self._tasks = []
        flat: list[dict] = []
        for type_key, label in TASK_GROUPS:
            entries = tasks_by_type[type_key]
            if not entries:
                continue
            flat.append({"_section": label, "_count": len(entries)})
            for entry in entries:
                self._tasks.append(entry)
                flat.append({"_entry": entry, "_task_idx": len(self._tasks) - 1})
                # If expanded and has sub-windows, add them
                if entry.expanded and entry.sub_windows:
                    for sub in entry.sub_windows:
                        flat.append({
                            "_sub_window": True,
                            "_parent_entry": entry,
                            "_window_name": sub["name"],
                            "_window_index": sub["index"],
                        })

        self._items = flat
        self._clamp_index()
        self.refresh()

    def _rebuild_flat(self) -> None:
        """Rebuild flat items list from current tasks (after expand/collapse)."""
        flat: list[dict] = []
        task_idx = 0
        current_type = None
        for entry in self._tasks:
            if entry.task_type != current_type:
                current_type = entry.task_type
                label = dict(TASK_GROUPS).get(current_type, current_type)
                count = sum(1 for t in self._tasks if t.task_type == current_type)
                flat.append({"_section": label, "_count": count})
            flat.append({"_entry": entry, "_task_idx": task_idx})
            task_idx += 1
            if entry.expanded and entry.sub_windows:
                for sub in entry.sub_windows:
                    flat.append({
                        "_sub_window": True,
                        "_parent_entry": entry,
                        "_window_name": sub["name"],
                        "_window_index": sub["index"],
                    })
        self._items = flat
        self._clamp_index()

    def _selectable_indices(self) -> list[int]:
        """Return indices of selectable (non-header) items."""
        return [i for i, item in enumerate(self._items) if "_section" not in item]

    def _clamp_index(self) -> None:
        indices = self._selectable_indices()
        if not indices:
            self.selected_index = 0
            return
        if self.selected_index not in indices:
            self.selected_index = indices[0]

    def _section_start_indices(self) -> list[int]:
        """Return selectable indices that are the first item in each section."""
        result = []
        in_section = False
        for i, item in enumerate(self._items):
            if "_section" in item:
                in_section = True
                continue
            if in_section and "_section" not in item:
                result.append(i)
                in_section = False
        return result

    @property
    def selected_pr_id(self) -> str | None:
        """Return the PR ID of the currently selected task, if any."""
        if not self._items or self.selected_index >= len(self._items):
            return None
        item = self._items[self.selected_index]
        entry = item.get("_entry")
        if entry:
            return entry.pr_id or None
        parent = item.get("_parent_entry")
        if parent:
            return parent.pr_id or None
        return None

    @property
    def selected_window_name(self) -> str | None:
        """Return the window name of the currently selected item."""
        if not self._items or self.selected_index >= len(self._items):
            return None
        item = self._items[self.selected_index]
        entry = item.get("_entry")
        if entry:
            return entry.window_name
        if item.get("_sub_window"):
            return item["_window_name"]
        return None

    @property
    def selected_window_index(self) -> str | None:
        """Return the window index of the currently selected item."""
        if not self._items or self.selected_index >= len(self._items):
            return None
        item = self._items[self.selected_index]
        entry = item.get("_entry")
        if entry:
            return entry.window_index
        if item.get("_sub_window"):
            return item["_window_index"]
        return None

    def _truncate(self, text: str, max_width: int) -> str:
        if len(text) <= max_width:
            return text
        return text[: max_width - 1] + "\u2026"

    def render(self) -> RenderableType:
        output = Text()
        content_width = (self.size.width - 4) if self.size.width > 8 else 60

        if not self._items:
            output.append("No running tasks.\n", style="dim")
            output.append("\n")
            output.append("  Start a PR with ", style="dim")
            output.append("s", style="bold")
            output.append(" in the tech tree.\n", style="dim")
            return output

        selectable = self._selectable_indices()
        spinner = SPINNER_FRAMES[self._anim_frame % len(SPINNER_FRAMES)]

        for i, item in enumerate(self._items):
            if "_section" in item:
                label = item["_section"]
                count = item["_count"]
                output.append(f"\n  {label} ({count})\n", style="bold underline")
                output.append("  " + "\u2500" * min(content_width - 2, 40) + "\n",
                              style="dim")
                continue

            is_selected = (i == self.selected_index)

            if item.get("_sub_window"):
                # Sub-window entry (indented)
                win_name = item["_window_name"]
                if is_selected:
                    output.append("    \u25b6 ", style="bold cyan")
                else:
                    output.append("      ")
                output.append(win_name, style="bold cyan" if is_selected else "dim")
                output.append("\n")
                continue

            entry: TaskEntry = item["_entry"]

            # Selection arrow
            if is_selected:
                output.append("\u25b6 ", style="bold cyan")
            else:
                output.append("  ")

            # Task type icon and display ID
            type_icon = self._type_icon(entry.task_type)
            output.append(f"{type_icon} ", style=self._type_style(entry.task_type))
            output.append(entry.display_id,
                          style="bold cyan" if is_selected else "bold")

            # PR title (truncated)
            if entry.pr_title:
                remaining = content_width - 4 - len(entry.display_id) - 2
                if remaining > 10:
                    title = self._truncate(entry.pr_title, remaining)
                    output.append(f" {title}",
                                  style="cyan" if is_selected else "")

            # Status indicators
            status_parts = []
            if entry.loop_info:
                status_parts.append(entry.loop_info)
            if entry.verdict:
                status_parts.append(self._verdict_marker(entry.verdict))
            elif entry.task_type in ("implementation", "review", "qa"):
                status_parts.append(spinner)

            if entry.sub_windows:
                expand_icon = "\u25bc" if entry.expanded else "\u25b6"
                status_parts.append(f"{expand_icon}{len(entry.sub_windows)}w")

            if status_parts:
                output.append(" ")
                output.append(" ".join(status_parts),
                              style=self._verdict_style(entry.verdict) if entry.verdict else "dim")

            output.append("\n")

        # Footer
        output.append("\n")
        output.append("  Enter", style="bold")
        output.append("=switch  ", style="dim")
        output.append("Space", style="bold")
        output.append("=expand  ", style="dim")
        output.append("W", style="bold")
        output.append("=back\n", style="dim")

        return output

    @staticmethod
    def _type_icon(task_type: str) -> str:
        return {
            "implementation": "\u2692",  # ⚒
            "review": "\u2691",          # ⚑
            "qa": "\u2714",             # ✔
            "watcher": "\u25c9",        # ◉
            "other": "\u2022",          # •
        }.get(task_type, "\u2022")

    @staticmethod
    def _type_style(task_type: str) -> str:
        return {
            "implementation": "bold yellow",
            "review": "bold cyan",
            "qa": "bold magenta",
            "watcher": "bold green",
            "other": "dim",
        }.get(task_type, "")

    @staticmethod
    def _verdict_marker(verdict: str) -> str:
        return {
            "PASS": "\u2713",
            "PASS_WITH_SUGGESTIONS": "~",
            "NEEDS_WORK": "\u2717",
            "KILLED": "\u2620",
            "TIMEOUT": "\u23f1",
            "ERROR": "!",
            "INPUT_REQUIRED": "\u23f8",
        }.get(verdict, verdict)

    @staticmethod
    def _verdict_style(verdict: str) -> str:
        return {
            "PASS": "bold green",
            "PASS_WITH_SUGGESTIONS": "bold yellow",
            "NEEDS_WORK": "bold red",
            "KILLED": "bold red",
            "TIMEOUT": "bold red",
            "ERROR": "bold red",
            "INPUT_REQUIRED": "bold red",
        }.get(verdict, "dim")

    def _entry_lines(self, item: dict) -> int:
        if "_section" in item:
            return 3  # blank + header + divider
        if item.get("_sub_window"):
            return 1
        return 1

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

        selectable = self._selectable_indices()
        if not selectable and event.key not in ("W",):
            return

        current_pos = (
            selectable.index(self.selected_index)
            if selectable and self.selected_index in selectable
            else 0
        )

        if event.key in ("up", "k"):
            if selectable and current_pos > 0:
                self.selected_index = selectable[current_pos - 1]
                self.refresh()
                self._scroll_selected_into_view()
                self._post_selected()
            event.stop()

        elif event.key in ("down", "j"):
            if selectable and current_pos < len(selectable) - 1:
                self.selected_index = selectable[current_pos + 1]
                self.refresh()
                self._scroll_selected_into_view()
                self._post_selected()
            event.stop()

        elif event.key == "J":
            # Jump to next section
            section_starts = self._section_start_indices()
            for idx in section_starts:
                if idx > self.selected_index and idx in selectable:
                    self.selected_index = idx
                    self.refresh()
                    self._scroll_selected_into_view()
                    self._post_selected()
                    break
            event.stop()

        elif event.key == "K":
            # Jump to previous section
            section_starts = self._section_start_indices()
            for idx in reversed(section_starts):
                if idx < self.selected_index and idx in selectable:
                    self.selected_index = idx
                    self.refresh()
                    self._scroll_selected_into_view()
                    self._post_selected()
                    break
            event.stop()

        elif event.key == "enter":
            win_name = self.selected_window_name
            win_idx = self.selected_window_index
            if win_name and win_idx:
                self.post_message(TaskActivated(
                    win_name, win_idx, pr_id=self.selected_pr_id or "",
                ))
            event.stop()

        elif event.key in ("space", "right", "l"):
            # Toggle expand/collapse for multi-window tasks
            if self._items and self.selected_index < len(self._items):
                item = self._items[self.selected_index]
                entry = item.get("_entry")
                if entry and entry.sub_windows:
                    entry.expanded = not entry.expanded
                    self._rebuild_flat()
                    self.refresh()
            event.stop()

        elif event.key in ("left", "h"):
            # Collapse if on an expanded entry or its sub-window
            if self._items and self.selected_index < len(self._items):
                item = self._items[self.selected_index]
                entry = item.get("_entry")
                parent = item.get("_parent_entry")
                if entry and entry.expanded and entry.sub_windows:
                    entry.expanded = False
                    self._rebuild_flat()
                    self.refresh()
                elif parent and parent.expanded:
                    parent.expanded = False
                    self._rebuild_flat()
                    # Move selection to the parent entry
                    for idx, it in enumerate(self._items):
                        if it.get("_entry") is parent:
                            self.selected_index = idx
                            break
                    self.refresh()
            event.stop()

        # PR actions — delegate to app via TaskAction
        elif event.key == "s":
            if self.selected_pr_id:
                self.post_message(TaskAction("start", self.selected_pr_id))
            event.stop()
        elif event.key == "d":
            if self.selected_pr_id:
                self.post_message(TaskAction("review", self.selected_pr_id))
            event.stop()
        elif event.key == "g":
            if self.selected_pr_id:
                self.post_message(TaskAction("merge", self.selected_pr_id))
            event.stop()
        elif event.key == "t":
            if self.selected_pr_id:
                self.post_message(TaskAction("qa", self.selected_pr_id))
            event.stop()
        elif event.key == "e":
            if self.selected_pr_id:
                self.post_message(TaskAction("edit", self.selected_pr_id))
            event.stop()
        elif event.key == "v":
            if self.selected_pr_id:
                self.post_message(TaskAction("view_plan", self.selected_pr_id))
            event.stop()

    def _post_selected(self) -> None:
        pr_id = self.selected_pr_id or ""
        win_name = self.selected_window_name or ""
        self.post_message(TaskSelected(pr_id, win_name))
