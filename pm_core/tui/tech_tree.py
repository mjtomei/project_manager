"""Graph widget that renders PR nodes and edges in the TUI."""

from textual.widget import Widget
from textual.reactive import reactive
from textual.message import Message
from textual.geometry import Size
from rich.text import Text
from rich.style import Style
from rich.console import RenderableType

from pm_core import graph as graph_mod


STATUS_ICONS = {
    "pending": "○",
    "in_progress": "●",
    "in_review": "◎",
    "merged": "✓",
    "blocked": "✗",
}

STATUS_STYLES = {
    "pending": "white",
    "in_progress": "bold yellow",
    "in_review": "bold cyan",
    "merged": "bold green",
    "blocked": "bold red",
}

# Subtle background tints for status
STATUS_BG = {
    "pending": "",                # no background
    "in_progress": "on #333300",  # subtle yellow
    "in_review": "on #003333",    # subtle cyan
    "merged": "on #003300",       # subtle green
    "blocked": "on #330000",      # subtle red
}

# Node dimensions
NODE_W = 24
NODE_H = 5  # 5 lines: top border, id, title, status, bottom border
H_GAP = 6
V_GAP = 2


class PRSelected(Message):
    """Fired when a PR node is selected."""
    def __init__(self, pr_id: str) -> None:
        self.pr_id = pr_id
        super().__init__()


class PRActivated(Message):
    """Fired when Enter is pressed on a PR node."""
    def __init__(self, pr_id: str) -> None:
        self.pr_id = pr_id
        super().__init__()


class TechTree(Widget):
    """Renders the PR dependency graph as a navigable tech tree."""

    can_focus = True

    selected_index: reactive[int] = reactive(0)
    prs: reactive[list] = reactive(list, init=False)

    def __init__(self, prs: list[dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._prs = prs or []
        self._ordered_ids: list[str] = []
        self._node_positions: dict[str, tuple[int, int]] = {}  # pr_id -> (col, row) in grid

    def on_mount(self) -> None:
        self.prs = self._prs
        self._recompute()

    def update_prs(self, prs: list[dict]) -> None:
        self._prs = prs
        self.prs = prs
        self._recompute()

    def _recompute(self) -> None:
        """Recompute layout positions."""
        prs = self._prs
        if not prs:
            self._ordered_ids = []
            self._node_positions = {}
            return

        layers = graph_mod.compute_layers(prs)
        self._ordered_ids = []
        self._node_positions = {}

        for col, layer in enumerate(layers):
            for row, pr_id in enumerate(sorted(layer)):
                self._node_positions[pr_id] = (col, row)
                self._ordered_ids.append(pr_id)

        if self.selected_index >= len(self._ordered_ids):
            self.selected_index = max(0, len(self._ordered_ids) - 1)

    @property
    def selected_pr_id(self) -> str | None:
        if not self._ordered_ids:
            return None
        return self._ordered_ids[self.selected_index]

    def get_content_width(self, container, viewport):
        if not self._node_positions:
            return 40
        max_col = max(c for c, r in self._node_positions.values()) + 1
        return max_col * (NODE_W + H_GAP) + 4

    def get_content_height(self, container, viewport, width):
        if not self._node_positions:
            return 10
        max_row = max(r for c, r in self._node_positions.values()) + 1
        return max_row * (NODE_H + V_GAP) + 2

    def render(self) -> RenderableType:
        if not self._prs:
            return Text("No PRs defined. Use 'pr add' to create PRs.", style="dim")

        pr_map = {pr["id"]: pr for pr in self._prs}
        lines: list[Text] = []

        # Compute grid dimensions
        max_col = max(c for c, r in self._node_positions.values()) + 1
        max_row = max(r for c, r in self._node_positions.values()) + 1

        total_h = max_row * (NODE_H + V_GAP)
        total_w = max_col * (NODE_W + H_GAP)

        # Build a character grid with increased margins to prevent overlapping
        grid = [[" "] * (total_w + 10) for _ in range(total_h + 4)]
        style_grid = [[""] * (total_w + 10) for _ in range(total_h + 4)]

        # Safe write helper to prevent out-of-bounds access
        def safe_write(y: int, x: int, char: str, style: str = "") -> None:
            if 0 <= y < len(grid) and 0 <= x < len(grid[0]):
                grid[y][x] = char
                style_grid[y][x] = style

        # Compute pixel positions
        def node_pos(pr_id):
            col, row = self._node_positions[pr_id]
            x = col * (NODE_W + H_GAP) + 2
            y = row * (NODE_H + V_GAP) + 1
            return x, y

        # Draw edges first
        for pr in self._prs:
            for dep_id in pr.get("depends_on") or []:
                if dep_id in self._node_positions and pr["id"] in self._node_positions:
                    sx, sy = node_pos(dep_id)
                    ex, ey = node_pos(pr["id"])
                    # Draw horizontal arrow from right of source to left of target
                    arrow_y = sy + NODE_H // 2
                    arrow_start_x = sx + NODE_W
                    arrow_end_x = ex - 1

                    if arrow_end_x > arrow_start_x:
                        for x in range(arrow_start_x, arrow_end_x + 1):
                            safe_write(arrow_y, x, "─", "dim")
                        safe_write(arrow_y, arrow_end_x, "▶", "dim")

        # Draw nodes
        for pr_id, (col, row) in self._node_positions.items():
            pr = pr_map.get(pr_id)
            if not pr:
                continue

            x, y = node_pos(pr_id)
            status = pr.get("status", "pending")
            icon = STATUS_ICONS.get(status, "?")
            is_selected = (self._ordered_ids[self.selected_index] == pr_id if self._ordered_ids else False)
            node_style = STATUS_STYLES.get(status, "white")
            bg_style = STATUS_BG.get(status, "")

            # Box characters - double-line for selected, single-line otherwise
            border = "bold white" if is_selected else "dim"
            if is_selected:
                top = "╔" + "═" * (NODE_W - 2) + "╗"
                bot = "╚" + "═" * (NODE_W - 2) + "╝"
                side = "║"
            else:
                top = "┌" + "─" * (NODE_W - 2) + "┐"
                bot = "└" + "─" * (NODE_W - 2) + "┘"
                side = "│"

            id_line = f"{side} {pr_id:<{NODE_W - 4}} {side}"
            title = pr.get("title", "???")
            max_title_len = NODE_W - 4
            if len(title) > max_title_len:
                title = title[:max_title_len - 1] + "…"  # Unicode ellipsis
            title_line = f"{side} {title:<{NODE_W - 4}} {side}"
            status_text = f"{icon} {status}"
            machine = pr.get("agent_machine")
            if machine:
                avail = NODE_W - 4 - len(status_text) - 1
                if avail > 3:
                    status_text += f" {machine[:avail]}"
            status_line = f"{side} {status_text:<{NODE_W - 4}} {side}"

            box_lines = [top, id_line, title_line, status_line, bot]
            for dy, bl in enumerate(box_lines):
                for dx, ch in enumerate(bl):
                    is_border = (dy == 0 or dy == len(box_lines) - 1
                                 or dx == 0 or dx == len(bl) - 1)
                    if is_selected:
                        if is_border:
                            style = "bold cyan"
                        else:
                            # Interior of selected box: node style + background
                            style = f"{node_style} {bg_style}".strip()
                    elif is_border:
                        style = border
                    else:
                        # Interior of unselected box: node style + background
                        style = f"{node_style} {bg_style}".strip()
                    safe_write(y + dy, x + dx, ch, style)

        # Convert grid to Rich Text
        output = Text()
        for row_idx, row in enumerate(grid):
            line = Text()
            i = 0
            while i < len(row):
                ch = row[i]
                st = style_grid[row_idx][i]
                # Batch same-style chars
                j = i + 1
                while j < len(row) and style_grid[row_idx][j] == st:
                    j += 1
                segment = "".join(row[i:j])
                if st:
                    line.append(segment, style=st)
                else:
                    line.append(segment)
                i = j
            output.append(line)
            output.append("\n")

        return output

    def on_key(self, event) -> None:
        if not self.has_focus:
            return
        if not self._ordered_ids:
            return

        current_id = self._ordered_ids[self.selected_index]
        current_pos = self._node_positions.get(current_id, (0, 0))
        cur_col, cur_row = current_pos

        new_index = None

        if event.key in ("up", "k"):
            # Move up in same column
            candidates = [(i, pid) for i, pid in enumerate(self._ordered_ids)
                          if self._node_positions[pid][0] == cur_col and self._node_positions[pid][1] < cur_row]
            if candidates:
                new_index = max(candidates, key=lambda x: self._node_positions[x[1]][1])[0]
        elif event.key in ("down", "j"):
            candidates = [(i, pid) for i, pid in enumerate(self._ordered_ids)
                          if self._node_positions[pid][0] == cur_col and self._node_positions[pid][1] > cur_row]
            if candidates:
                new_index = min(candidates, key=lambda x: self._node_positions[x[1]][1])[0]
        elif event.key in ("left", "h"):
            candidates = [(i, pid) for i, pid in enumerate(self._ordered_ids)
                          if self._node_positions[pid][0] < cur_col]
            if candidates:
                # Pick closest column, closest row
                new_index = min(candidates, key=lambda x: (cur_col - self._node_positions[x[1]][0],
                                                           abs(self._node_positions[x[1]][1] - cur_row)))[0]
        elif event.key in ("right", "l"):
            candidates = [(i, pid) for i, pid in enumerate(self._ordered_ids)
                          if self._node_positions[pid][0] > cur_col]
            if candidates:
                new_index = min(candidates, key=lambda x: (self._node_positions[x[1]][0] - cur_col,
                                                           abs(self._node_positions[x[1]][1] - cur_row)))[0]
        elif event.key == "enter":
            self.post_message(PRActivated(current_id))
            return

        if new_index is not None and new_index != self.selected_index:
            self.selected_index = new_index
            self.post_message(PRSelected(self._ordered_ids[new_index]))
            self.refresh()
