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
    "closed": "✗",
    "blocked": "✗",
}

STATUS_STYLES = {
    "pending": "white",
    "in_progress": "bold yellow",
    "in_review": "bold cyan",
    "merged": "bold green",
    "closed": "dim red",
    "blocked": "bold red",
}

# Subtle background tints for status
STATUS_BG = {
    "pending": "",                # no background
    "in_progress": "on #333300",  # subtle yellow
    "in_review": "on #003333",    # subtle cyan
    "merged": "on #003300",       # subtle green
    "closed": "on #220000",       # dim red
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
        self.refresh(layout=True)

    def _recompute(self) -> None:
        """Recompute layout positions with smart row assignment."""
        prs = self._prs
        if not prs:
            self._ordered_ids = []
            self._node_positions = {}
            return

        pr_map = {pr["id"]: pr for pr in prs}
        layers = graph_mod.compute_layers(prs)
        self._ordered_ids = []
        self._node_positions = {}

        # Assign rows to minimize edge crossings and keep connected nodes aligned
        row_assignments: dict[str, int] = {}

        for col, layer in enumerate(layers):
            if col == 0:
                # First column: just stack them
                for row, pr_id in enumerate(sorted(layer)):
                    row_assignments[pr_id] = row
            else:
                # For subsequent columns, try to align with dependencies
                # Calculate preferred row for each node based on its dependencies
                preferred_rows: list[tuple[str, float]] = []
                for pr_id in layer:
                    pr = pr_map.get(pr_id)
                    deps = (pr.get("depends_on") or []) if pr else []
                    dep_rows = [row_assignments[d] for d in deps if d in row_assignments]
                    if dep_rows:
                        # Prefer the median row of dependencies
                        preferred = sum(dep_rows) / len(dep_rows)
                    else:
                        preferred = 0
                    preferred_rows.append((pr_id, preferred))

                # Sort by preferred row to assign in order
                preferred_rows.sort(key=lambda x: (x[1], x[0]))

                # Assign rows, avoiding collisions
                used_rows: set[int] = set()
                for pr_id, pref in preferred_rows:
                    # Find closest available row to preferred
                    target = round(pref)
                    if target not in used_rows:
                        row_assignments[pr_id] = target
                        used_rows.add(target)
                    else:
                        # Search outward for an available row
                        for offset in range(1, len(layer) + 10):
                            if target + offset not in used_rows:
                                row_assignments[pr_id] = target + offset
                                used_rows.add(target + offset)
                                break
                            if target - offset >= 0 and target - offset not in used_rows:
                                row_assignments[pr_id] = target - offset
                                used_rows.add(target - offset)
                                break

        # Compact row numbers to eliminate gaps
        all_rows = sorted(set(row_assignments.values()))
        row_remap = {old: new for new, old in enumerate(all_rows)}
        for pr_id in row_assignments:
            row_assignments[pr_id] = row_remap[row_assignments[pr_id]]

        # Build final positions
        for col, layer in enumerate(layers):
            for pr_id in sorted(layer, key=lambda x: row_assignments.get(x, 0)):
                self._node_positions[pr_id] = (col, row_assignments[pr_id])
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

        # Collect all edges and sort by vertical distance (straight edges first)
        edges = []
        for pr in self._prs:
            for dep_id in pr.get("depends_on") or []:
                if dep_id in self._node_positions and pr["id"] in self._node_positions:
                    edges.append((dep_id, pr["id"]))

        # Sort edges: horizontal (same row) first, then by vertical distance
        def edge_priority(edge):
            src_col, src_row = self._node_positions[edge[0]]
            dst_col, dst_row = self._node_positions[edge[1]]
            return (abs(dst_row - src_row), src_col, src_row)

        edges.sort(key=edge_priority)

        # Track used vertical channel positions to avoid overlap
        # Key: x position, Value: set of y ranges that are used
        used_channels: dict[int, list[tuple[int, int]]] = {}

        def channel_free(x: int, y1: int, y2: int) -> bool:
            if x not in used_channels:
                return True
            min_y, max_y = min(y1, y2), max(y1, y2)
            for (a, b) in used_channels[x]:
                if not (max_y < a or min_y > b):  # ranges overlap
                    return False
            return True

        def mark_channel(x: int, y1: int, y2: int) -> None:
            if x not in used_channels:
                used_channels[x] = []
            used_channels[x].append((min(y1, y2), max(y1, y2)))

        # Draw edges
        for dep_id, pr_id in edges:
            sx, sy = node_pos(dep_id)
            ex, ey = node_pos(pr_id)
            src_y = sy + NODE_H // 2
            dst_y = ey + NODE_H // 2
            arrow_start_x = sx + NODE_W
            arrow_end_x = ex - 1

            if arrow_end_x > arrow_start_x:
                if src_y == dst_y:
                    # Simple horizontal arrow
                    for x in range(arrow_start_x, arrow_end_x + 1):
                        safe_write(src_y, x, "─", "dim")
                    safe_write(src_y, arrow_end_x, "▶", "dim")
                else:
                    # Find a free vertical channel in the gap
                    gap_start = arrow_start_x + 1
                    gap_end = arrow_end_x - 1
                    mid_x = gap_start + (gap_end - gap_start) // 2

                    # Try to find an unused channel position
                    for offset in range(0, (gap_end - gap_start) // 2 + 1):
                        test_x = mid_x + offset
                        if gap_start <= test_x <= gap_end and channel_free(test_x, src_y, dst_y):
                            mid_x = test_x
                            break
                        test_x = mid_x - offset
                        if gap_start <= test_x <= gap_end and channel_free(test_x, src_y, dst_y):
                            mid_x = test_x
                            break

                    mark_channel(mid_x, src_y, dst_y)

                    # Horizontal from source to midpoint
                    for x in range(arrow_start_x, mid_x + 1):
                        safe_write(src_y, x, "─", "dim")
                    # Vertical segment
                    if dst_y > src_y:
                        safe_write(src_y, mid_x, "┐", "dim")
                        for y in range(src_y + 1, dst_y):
                            safe_write(y, mid_x, "│", "dim")
                        safe_write(dst_y, mid_x, "└", "dim")
                    else:
                        safe_write(src_y, mid_x, "┘", "dim")
                        for y in range(dst_y + 1, src_y):
                            safe_write(y, mid_x, "│", "dim")
                        safe_write(dst_y, mid_x, "┌", "dim")
                    # Horizontal from midpoint to target
                    for x in range(mid_x + 1, arrow_end_x + 1):
                        safe_write(dst_y, x, "─", "dim")
                    safe_write(dst_y, arrow_end_x, "▶", "dim")

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

            display_id = f"#{pr.get('gh_pr_number')}" if pr.get("gh_pr_number") else pr_id
            id_line = f"{side} {display_id:<{NODE_W - 4}} {side}"
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
            # Scroll to keep selected node visible
            self._scroll_selected_into_view()

    def _scroll_selected_into_view(self) -> None:
        """Scroll the parent container to keep the selected node visible."""
        if not self._ordered_ids:
            return
        pr_id = self._ordered_ids[self.selected_index]
        if pr_id not in self._node_positions:
            return

        col, row = self._node_positions[pr_id]
        # Calculate pixel position of the node
        x = col * (NODE_W + H_GAP) + 2
        y = row * (NODE_H + V_GAP) + 1

        # Create a region for the node and scroll it into view
        # The scrollable container is the parent, so scroll there
        from textual.geometry import Region
        node_region = Region(x, y, NODE_W, NODE_H)
        if self.parent:
            self.parent.scroll_to_region(node_region)
        else:
            self.scroll_to_region(node_region)
