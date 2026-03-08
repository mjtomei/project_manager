"""Cached edge rendering widget for the tech tree."""

from textual.widget import Widget
from rich.text import Text
from rich.console import RenderableType

from pm_core.tui.pr_node import NODE_W, NODE_H, V_GAP


class EdgeCanvas(Widget):
    """Renders dependency edges between PR nodes.

    Caches the rendered output and only redraws when edges or node
    positions actually change.
    """

    DEFAULT_CSS = """
    EdgeCanvas {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._edges: list[tuple[str, str]] = []
        self._node_positions: dict[str, tuple[int, int]] = {}
        self._canvas_w: int = 0
        self._canvas_h: int = 0
        self._plan_labels: dict[str, tuple[int, str]] = {}  # plan_id -> (label_row, display_name)
        self._cached_output: RenderableType | None = None
        self._dirty: bool = True

    def update_edges(
        self,
        edges: list[tuple[str, str]],
        node_positions: dict[str, tuple[int, int]],
        canvas_w: int,
        canvas_h: int,
        plan_labels: dict[str, tuple[int, str]] | None = None,
    ) -> None:
        """Update edge data. Only triggers redraw if data changed."""
        if (edges == self._edges
                and node_positions == self._node_positions
                and canvas_w == self._canvas_w
                and canvas_h == self._canvas_h
                and (plan_labels or {}) == self._plan_labels):
            return
        self._edges = edges
        self._node_positions = dict(node_positions)
        self._canvas_w = canvas_w
        self._canvas_h = canvas_h
        self._plan_labels = dict(plan_labels or {})
        self._dirty = True
        self.refresh()

    def render(self) -> RenderableType:
        if not self._dirty and self._cached_output is not None:
            return self._cached_output

        output = self._render_edges()
        self._cached_output = output
        self._dirty = False
        return output

    def _render_edges(self) -> RenderableType:
        if not self._edges and not self._plan_labels:
            return Text("")

        grid_h = max(self._canvas_h, 1)
        grid_w = max(self._canvas_w, 1)
        grid = [[" "] * grid_w for _ in range(grid_h)]
        style_grid = [[""] * grid_w for _ in range(grid_h)]

        def safe_write(y: int, x: int, char: str, style: str = "") -> None:
            if 0 <= y < grid_h and 0 <= x < grid_w:
                grid[y][x] = char
                style_grid[y][x] = style

        def node_pos(pr_id):
            x, row = self._node_positions[pr_id]
            y = row * (NODE_H + V_GAP) + 1
            return x, y

        # Pre-compute outgoing/incoming for fan-out offsets
        outgoing: dict[str, list[str]] = {}
        incoming: dict[str, list[str]] = {}
        for dep_id, pr_id in self._edges:
            outgoing.setdefault(dep_id, []).append(pr_id)
            incoming.setdefault(pr_id, []).append(dep_id)
        for src_id, dst_ids in outgoing.items():
            dst_ids.sort(key=lambda d: self._node_positions.get(d, (0, 0))[1])
        for dst_id, src_ids in incoming.items():
            src_ids.sort(key=lambda s: self._node_positions.get(s, (0, 0))[1])

        def _spread_offsets(n: int) -> list[int]:
            if n == 1:
                return [NODE_H // 2]
            if n == 2:
                return [1, NODE_H - 2]
            return [1 + round(i * (NODE_H - 3) / (n - 1)) for i in range(n)]

        exit_offsets: dict[str, dict[str, int]] = {}
        entry_offsets: dict[str, dict[str, int]] = {}
        for src_id, dst_ids in outgoing.items():
            offsets = _spread_offsets(len(dst_ids))
            exit_offsets[src_id] = {dst: offsets[i] for i, dst in enumerate(dst_ids)}
        for dst_id, src_ids in incoming.items():
            dst_row = self._node_positions.get(dst_id, (0, 0))[1]
            same_row: dict[str, int] = {}
            other_srcs: list[str] = []
            for src in src_ids:
                src_row = self._node_positions.get(src, (0, 0))[1]
                if src_row == dst_row and dst_id in exit_offsets.get(src, {}):
                    same_row[src] = exit_offsets[src][dst_id]
                else:
                    other_srcs.append(src)
            if not other_srcs:
                entry_offsets[dst_id] = dict(same_row)
            else:
                taken = set(same_row.values())
                all_offsets = _spread_offsets(len(src_ids))
                free_offsets = [o for o in all_offsets if o not in taken]
                if len(free_offsets) < len(other_srcs):
                    free_offsets = _spread_offsets(len(other_srcs))
                mapping = dict(same_row)
                for i, src in enumerate(other_srcs):
                    mapping[src] = free_offsets[i]
                entry_offsets[dst_id] = mapping

        # Channel tracking for vertical segments
        used_channels: dict[int, list[tuple[int, int]]] = {}

        def channel_free(x: int, y1: int, y2: int) -> bool:
            if x not in used_channels:
                return True
            min_y, max_y = min(y1, y2), max(y1, y2)
            for (a, b) in used_channels[x]:
                if not (max_y < a or min_y > b):
                    return False
            return True

        def mark_channel(x: int, y1: int, y2: int) -> None:
            if x not in used_channels:
                used_channels[x] = []
            used_channels[x].append((min(y1, y2), max(y1, y2)))

        # Sort edges by vertical distance (straight edges first)
        sorted_edges = sorted(self._edges, key=lambda e: (
            abs(self._node_positions.get(e[1], (0, 0))[1] - self._node_positions.get(e[0], (0, 0))[1]),
            self._node_positions.get(e[0], (0, 0))[0],
            self._node_positions.get(e[0], (0, 0))[1],
        ))

        for dep_id, pr_id in sorted_edges:
            if dep_id not in self._node_positions or pr_id not in self._node_positions:
                continue
            sx, sy = node_pos(dep_id)
            ex, ey = node_pos(pr_id)
            src_dy = exit_offsets.get(dep_id, {}).get(pr_id, NODE_H // 2)
            dst_dy = entry_offsets.get(pr_id, {}).get(dep_id, NODE_H // 2)
            src_y = sy + src_dy
            dst_y = ey + dst_dy
            arrow_start_x = sx + NODE_W
            arrow_end_x = ex - 1

            if arrow_end_x > arrow_start_x:
                if src_y == dst_y:
                    for x in range(arrow_start_x, arrow_end_x + 1):
                        safe_write(src_y, x, "─", "dim")
                    safe_write(src_y, arrow_end_x, "▶", "dim")
                else:
                    gap_start = arrow_start_x + 1
                    gap_end = arrow_end_x - 1
                    mid_x = gap_end
                    for test_x in range(gap_end, gap_start - 1, -1):
                        if channel_free(test_x, src_y, dst_y):
                            mid_x = test_x
                            break
                    mark_channel(mid_x, src_y, dst_y)

                    for x in range(arrow_start_x, mid_x + 1):
                        safe_write(src_y, x, "─", "dim")
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
                    for x in range(mid_x + 1, arrow_end_x + 1):
                        safe_write(dst_y, x, "─", "dim")
                    safe_write(dst_y, arrow_end_x, "▶", "dim")

        # Draw plan labels
        for plan_id, (label_row, display_name) in self._plan_labels.items():
            label_y = label_row * (NODE_H + V_GAP) + 1 + NODE_H // 2
            label_text = f" ── {display_name} "
            if len(label_text) < grid_w - 2:
                label_text += "─" * (grid_w - 2 - len(label_text))
            for dx, ch in enumerate(label_text):
                safe_write(label_y, dx, ch, "dim cyan")

        # Convert grid to Rich Text
        output = Text()
        for row_idx, row in enumerate(grid):
            line = Text()
            i = 0
            while i < len(row):
                ch = row[i]
                st = style_grid[row_idx][i]
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
