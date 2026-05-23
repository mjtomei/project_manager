"""Graph widget that renders PR nodes and edges in the TUI.

Compositional architecture (refactored from a single grid-rendering widget):

* :class:`TechTree` is a container.  It owns the layout, navigation and the
  public API, and on data change mounts child widgets.
* :class:`PRNode` is one widget per visible PR — a 5-line box.  Spinner ticks
  refresh only the handful of *active* nodes instead of the whole tree.
* :class:`PlanGroup` is a transparent full-size container per plan, holding its
  PR nodes and a :class:`PlanLabel`.  Collapse/expand is ``display`` toggling.
* :class:`EdgeCanvas` is a single lower-layer widget that draws the dependency
  arrows once and caches them, so spinner ticks never repaint edges.
"""

import time

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.cells import cell_len
from rich.console import RenderableType

from pm_core.tui import item_message, perf
from pm_core.tui.tree_layout import compute_tree_layout, SORT_FIELDS, SORT_FIELD_KEYS


STATUS_ICONS = {
    "pending": "○",
    "in_progress": "◎",
    "in_review": "◉",
    "qa": "●",
    "merged": "✓",
    "closed": "✗",
    "blocked": "✗",
}

VERDICT_MARKERS = {
    "PASS": "✓",
    "NEEDS_WORK": "✗",
    "KILLED": "☠",
    "TIMEOUT": "⏱",
    "ERROR": "!",
    "INPUT_REQUIRED": "⏸",
}

VERDICT_STYLES = {
    "PASS": "bold green",
    "NEEDS_WORK": "bold red",
    "KILLED": "bold red",
    "TIMEOUT": "bold red",
    "ERROR": "bold red",
    "INPUT_REQUIRED": "bold red",
}

SPINNER_FRAMES = "◐◓◑◒"


def qa_pane_state(tracker, pr_id: str) -> str:
    """Aggregate QA-pane activity for *pr_id* in the idle tracker.

    QA runs N parallel scenarios, each registered under a key
    ``qa:<pr_id>:s<index>``. Returns ``"waiting"`` if any pane is blocked
    on a permission prompt, ``"active"`` if any pane is tracked and
    neither idle nor waiting, otherwise ``"idle"`` (which also covers
    the no-tracked-keys case). Mirrors the ``in_progress``/``in_review``
    spinner precedence: waiting wins over active.
    """
    prefix = f"qa:{pr_id}:"
    keys = [k for k in tracker.tracked_keys() if k.startswith(prefix)]
    if not keys:
        return "idle"
    if any(tracker.is_waiting_for_input(k) for k in keys):
        return "waiting"
    if any(not tracker.is_idle(k) and not tracker.is_waiting_for_input(k)
           for k in keys):
        return "active"
    return "idle"

STATUS_STYLES = {
    "pending": "white",
    "in_progress": "bold yellow",
    "in_review": "bold cyan",
    "qa": "bold magenta",
    "merged": "bold green",
    "closed": "dim red",
    "blocked": "bold red",
}

# Subtle background tints for status
STATUS_BG = {
    "pending": "",                # no background
    "in_progress": "on #333300",  # subtle yellow
    "in_review": "on #003333",    # subtle cyan
    "qa": "on #330033",           # subtle magenta
    "merged": "on #003300",       # subtle green
    "closed": "on #220000",       # dim red
    "blocked": "on #330000",      # subtle red
}

# Status filter cycle order (None = show all)
STATUS_FILTER_CYCLE = [None, "pending", "in_progress", "in_review", "qa", "merged", "closed"]

# Node dimensions
NODE_W = 24
NODE_H = 5  # 5 lines: top border, id, title, status, bottom border
H_GAP = 6
V_GAP = 2


PRSelected, _PRActivated = item_message("PR", "pr_id")


def _node_y(row: int) -> int:
    """Pixel y of a node's top border given its grid *row*."""
    return row * (NODE_H + V_GAP) + 1


def compute_neighbors(
    ordered_ids: list[str],
    node_positions: dict[str, tuple[int, int]],
) -> dict[str, dict[str, str | None]]:
    """Precompute grid neighbors (up/down/left/right) for every node.

    Replaces the per-keystroke candidate-finding loops with a single pass.
    The directional preference rules match the previous ``on_key`` logic:

    * up/down  — prefer same column, then closest column, then closest row;
    * left/right — prefer same row, then the closest column / row.

    Returns ``{pr_id: {"up"|"down"|"left"|"right": neighbor_id_or_None}}``.
    Hidden virtual ids (``_hidden:``) participate via their ``(0, row)``
    positions, exactly as before.
    """
    neighbors: dict[str, dict[str, str | None]] = {}
    indexed = [(pid, node_positions[pid]) for pid in ordered_ids
               if pid in node_positions]

    for pid, (cur_col, cur_row) in indexed:
        nb: dict[str, str | None] = {"up": None, "down": None,
                                     "left": None, "right": None}

        # Up: nodes above (row < cur_row)
        up = [(p, c, r) for p, (c, r) in indexed if r < cur_row]
        if up:
            best = max(up, key=lambda t: (
                t[1] == cur_col,
                -abs(t[1] - cur_col),
                t[2],
            ))
            nb["up"] = best[0]

        # Down: nodes below (row > cur_row)
        down = [(p, c, r) for p, (c, r) in indexed if r > cur_row]
        if down:
            best = min(down, key=lambda t: (
                t[1] != cur_col,
                abs(t[1] - cur_col),
                t[2],
            ))
            nb["down"] = best[0]

        # Left: nodes in a column to the left (col < cur_col)
        left = [(p, c, r) for p, (c, r) in indexed if c < cur_col]
        if left:
            same_row = [t for t in left if t[2] == cur_row]
            if same_row:
                nb["left"] = max(same_row, key=lambda t: t[1])[0]
            else:
                nb["left"] = min(left, key=lambda t: (cur_col - t[1],
                                                      abs(t[2] - cur_row)))[0]

        # Right: nodes in a column to the right (col > cur_col)
        right = [(p, c, r) for p, (c, r) in indexed if c > cur_col]
        if right:
            same_row = [t for t in right if t[2] == cur_row]
            if same_row:
                nb["right"] = min(same_row, key=lambda t: t[1])[0]
            else:
                nb["right"] = min(right, key=lambda t: (t[1] - cur_col,
                                                        abs(t[2] - cur_row)))[0]

        neighbors[pid] = nb

    return neighbors


# ---------------------------------------------------------------------------
# Edge layer
# ---------------------------------------------------------------------------


class EdgeCanvas(Widget):
    """Draws the dependency arrows on a cached, lower layer.

    The rendered :class:`~rich.text.Text` is built once per layout change and
    cached, so spinner ticks (which only touch :class:`PRNode` widgets) never
    repaint edges.
    """

    DEFAULT_CSS = """
    EdgeCanvas {
        position: absolute;
        offset: 0 0;
        layer: edges;
        background: transparent;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._cached: Text | None = None

    def set_data(
        self,
        prs: list[dict],
        node_positions: dict[str, tuple[int, int]],
        width: int,
        height: int,
        y_offset: int = 0,
    ) -> None:
        """Rebuild and cache the edge layer for a new (band-local) layout.

        *node_positions* should already be filtered to the nodes this canvas is
        responsible for.  *y_offset* is the pixel row of the band's top, so node
        pixel-y values become canvas-relative.
        """
        self.styles.width = width
        self.styles.height = height
        self._cached = self._build(prs, node_positions, width, height, y_offset)
        if self.is_mounted:
            self.refresh()

    def render(self) -> RenderableType:
        return self._cached if self._cached is not None else Text("")

    @staticmethod
    def _build(
        prs: list[dict],
        node_positions: dict[str, tuple[int, int]],
        width: int,
        height: int,
        y_offset: int = 0,
    ) -> Text:
        """Construct the arrow grid (ported from the old monolithic render)."""
        real_positions = {k: v for k, v in node_positions.items()
                          if not k.startswith("_hidden:")}
        if not real_positions:
            return Text("")

        grid_w = max(width, 1)
        grid_h = max(height, 1)
        grid = [[" "] * grid_w for _ in range(grid_h)]
        style_grid = [[""] * grid_w for _ in range(grid_h)]

        def safe_write(y: int, x: int, char: str, style: str = "") -> None:
            if 0 <= y < grid_h and 0 <= x < grid_w:
                grid[y][x] = char
                style_grid[y][x] = style

        def node_pos(pr_id):
            x, row = node_positions[pr_id]
            return x, _node_y(row) - y_offset

        # Collect edges where both endpoints are positioned
        edges = []
        for pr in prs:
            for dep_id in pr.get("depends_on") or []:
                if dep_id in node_positions and pr["id"] in node_positions:
                    edges.append((dep_id, pr["id"]))

        def edge_priority(edge):
            src_col, src_row = node_positions[edge[0]]
            dst_col, dst_row = node_positions[edge[1]]
            return (abs(dst_row - src_row), src_col, src_row)

        edges.sort(key=edge_priority)

        # Pre-compute exit/entry y-offsets so multiple connections on one node
        # fan out across its interior height instead of sharing the centre.
        outgoing: dict[str, list[str]] = {}
        incoming: dict[str, list[str]] = {}
        for dep_id, pr_id in edges:
            outgoing.setdefault(dep_id, []).append(pr_id)
            incoming.setdefault(pr_id, []).append(dep_id)
        for src_id, dst_ids in outgoing.items():
            dst_ids.sort(key=lambda d: node_positions[d][1])
        for dst_id, src_ids in incoming.items():
            src_ids.sort(key=lambda s: node_positions[s][1])

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
            same_row: dict[str, int] = {}
            other_srcs: list[str] = []
            dst_row = node_positions[dst_id][1]
            for src in src_ids:
                src_row = node_positions[src][1]
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

        for dep_id, pr_id in edges:
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

        return _grid_to_text(grid, style_grid)


def _grid_to_text(grid: list[list[str]], style_grid: list[list[str]]) -> Text:
    """Convert a character/style grid into a Rich :class:`Text`, batching runs."""
    output = Text()
    for row_idx, row in enumerate(grid):
        line = Text()
        i = 0
        while i < len(row):
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
        if row_idx < len(grid) - 1:
            output.append("\n")
    return output


# ---------------------------------------------------------------------------
# Plan label
# ---------------------------------------------------------------------------


class PlanLabel(Widget):
    """A plan group's ``── name ──`` rule, or a navigable hidden-plan label."""

    DEFAULT_CSS = """
    PlanLabel {
        position: absolute;
        layer: nodes;
        height: 1;
        background: transparent;
    }
    """

    def __init__(self, tree: "TechTree", text: str, x: int, y: int, width: int,
                 *, selectable_id: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self._tree = tree
        self._text = text
        self._pos = (x, y)
        self._selectable_id = selectable_id  # virtual id for hidden labels
        self.styles.width = max(width, len(text))

    def on_mount(self) -> None:
        self.styles.offset = self._pos

    def render(self) -> RenderableType:
        if self._selectable_id is not None:
            is_sel = self._tree.is_selected(self._selectable_id)
            style = "bold white" if is_sel else "dim"
            return Text(self._text, style=style)
        return Text(self._text, style="dim cyan")


# ---------------------------------------------------------------------------
# PR node
# ---------------------------------------------------------------------------


class PRNode(Widget):
    """A single PR rendered as a 5-line box, positioned absolutely.

    Reads live spinner / loop-marker state from the app on each render, so the
    poll timer can repaint just the active nodes.  Each node also knows its
    grid neighbors (``neighbor_up`` etc.) for keyboard navigation.
    """

    DEFAULT_CSS = """
    PRNode {
        position: absolute;
        layer: nodes;
        width: %d;
        height: %d;
    }
    """ % (NODE_W, NODE_H)

    def __init__(self, tree: "TechTree", pr: dict, x: int, y: int, **kwargs):
        super().__init__(**kwargs)
        self._tree = tree
        self._pr = pr
        self.pr_id = pr["id"]
        self._offset = (x, y)  # offset within the parent PlanGroup
        self.neighbor_up: str | None = None
        self.neighbor_down: str | None = None
        self.neighbor_left: str | None = None
        self.neighbor_right: str | None = None

    def on_mount(self) -> None:
        self.styles.offset = self._offset

    # -- live marker state ---------------------------------------------------

    def _get_loop_marker(self) -> tuple[str, str]:
        """Return ``(marker_text, marker_style)`` for review-loop/merge state."""
        try:
            loops = self.app._review_loops
            state = loops.get(self.pr_id)
            if state:
                if state.running:
                    spinner = SPINNER_FRAMES[self._tree._anim_frame % len(SPINNER_FRAMES)]
                    if state.input_required:
                        return (f"⏸{state.iteration}{spinner}", "bold red")
                    if state.stop_requested:
                        return (f"⏹{state.iteration}{spinner}", "bold red")
                    return (f"⟳{state.iteration}{spinner}", "bold cyan")
                if state.latest_verdict:
                    v = state.latest_verdict
                    marker = VERDICT_MARKERS.get(v, v[:4])
                    style = VERDICT_STYLES.get(v, "")
                    return (f"⟳{state.iteration}{marker}", style)
            merge_input = getattr(self.app, '_merge_input_required_prs', set())
            if self.pr_id in merge_input:
                spinner = SPINNER_FRAMES[self._tree._anim_frame % len(SPINNER_FRAMES)]
                return (f"⏸M{spinner}", "bold red")
        except Exception:
            pass
        return ("", "")

    def render(self) -> RenderableType:
        pr = self._pr
        pr_id = self.pr_id
        status = pr.get("status", "pending")
        icon = STATUS_ICONS.get(status, "?")
        is_selected = self._tree.is_selected(pr_id)
        node_style = STATUS_STYLES.get(status, "white")
        bg_style = STATUS_BG.get(status, "")

        # Auto-start target detection (for ◎ marker)
        try:
            from pm_core.tui import auto_start as _auto_start
            auto_start_enabled = _auto_start.is_enabled(self.app)
            auto_start_target = (_auto_start.get_target(self.app)
                                 if auto_start_enabled else None)
        except Exception:
            auto_start_enabled = False
            auto_start_target = None

        if is_selected:
            top = "╔" + "═" * (NODE_W - 2) + "╗"
            bot = "╚" + "═" * (NODE_W - 2) + "╝"
            side = "║"
        else:
            top = "┌" + "─" * (NODE_W - 2) + "┐"
            bot = "└" + "─" * (NODE_W - 2) + "┘"
            side = "│"
        border = "bold white" if is_selected else "dim"

        display_id = f"#{pr.get('gh_pr_number')}" if pr.get("gh_pr_number") else pr_id
        is_auto_target = (auto_start_enabled and auto_start_target == pr_id)
        max_id_len = NODE_W - 4
        truncated_id = ""
        if is_auto_target:
            truncated_id = display_id[:max_id_len - 2]
            id_content = f"{truncated_id} ◎"
        else:
            id_content = display_id[:max_id_len]
        id_line = f"{side} {id_content:<{max_id_len}} {side}"

        title = pr.get("title", "???")
        max_title_len = NODE_W - 4
        # Pad/truncate by display cell width (not char count) so double-width
        # cells (e.g. emoji) don't push the right border off the box.
        if cell_len(title) > max_title_len:
            while title and cell_len(title) > max_title_len - 1:
                title = title[:-1]
            title = title + "…"
        title_pad = NODE_W - 4 - cell_len(title)
        title_line = f"{side} {title}{' ' * max(0, title_pad)} {side}"

        status_text = f"{icon} {status}"
        loop_marker, loop_style = self._get_loop_marker()
        marker_offset = -1
        if loop_marker:
            marker_offset = 2 + len(status_text) + 1
            status_text += f" {loop_marker}"
        else:
            if status in ("in_progress", "in_review") and pr.get("workdir"):
                tracker = self.app._pane_idle_tracker
                if tracker.is_tracked(pr_id):
                    if tracker.is_waiting_for_input(pr_id):
                        marker_offset = 2 + len(status_text) + 1
                        loop_style = "bold yellow"
                        status_text += " ⏸"
                    elif not tracker.is_idle(pr_id):
                        spinner = SPINNER_FRAMES[self._tree._anim_frame % len(SPINNER_FRAMES)]
                        marker_offset = 2 + len(status_text) + 1
                        loop_style = "bold cyan"
                        status_text += f" {spinner}"
            elif status == "qa" and pr.get("workdir"):
                qa_state = qa_pane_state(self.app._pane_idle_tracker, pr_id)
                if qa_state == "waiting":
                    marker_offset = 2 + len(status_text) + 1
                    loop_style = "bold yellow"
                    status_text += " ⏸"
                elif qa_state == "active":
                    spinner = SPINNER_FRAMES[self._tree._anim_frame % len(SPINNER_FRAMES)]
                    marker_offset = 2 + len(status_text) + 1
                    loop_style = "bold cyan"
                    status_text += f" {spinner}"
        if pr.get("spec_pending") and not loop_marker:
            marker_offset = 2 + len(status_text) + 1
            loop_style = "bold yellow"
            status_text += " S"
        machine = pr.get("agent_machine")
        if machine:
            avail = NODE_W - 4 - cell_len(status_text) - 1
            if avail > 3:
                status_text += f" {machine[:avail]}"
        visual_w = cell_len(status_text)
        pad = NODE_W - 4 - visual_w
        status_line = f"{side} {status_text}{' ' * max(0, pad)} {side}"

        box_lines = [top, id_line, title_line, status_line, bot]
        grid = [[" "] * NODE_W for _ in range(NODE_H)]
        style_grid = [[""] * NODE_W for _ in range(NODE_H)]

        def safe_write(y: int, x: int, char: str, style: str = "") -> None:
            if 0 <= y < NODE_H and 0 <= x < NODE_W:
                grid[y][x] = char
                style_grid[y][x] = style

        for dy, bl in enumerate(box_lines):
            grid_dx = 0
            for char_idx, ch in enumerate(bl):
                is_border = (dy == 0 or dy == len(box_lines) - 1
                             or char_idx == 0 or char_idx == len(bl) - 1)
                if is_selected:
                    style = "bold cyan" if is_border else f"{node_style} {bg_style}".strip()
                elif is_border:
                    style = border
                else:
                    style = f"{node_style} {bg_style}".strip()
                safe_write(dy, grid_dx, ch, style)
                cw = cell_len(ch)
                for k in range(1, cw):
                    if 0 <= dy < NODE_H and 0 <= (grid_dx + k) < NODE_W:
                        grid[dy][grid_dx + k] = ""
                        style_grid[dy][grid_dx + k] = style
                grid_dx += cw

        if is_auto_target:
            target_dx = 2 + len(truncated_id) + 1
            if 0 <= target_dx < NODE_W:
                style_grid[1][target_dx] = f"bold magenta {bg_style}".strip()

        if marker_offset >= 0 and loop_style:
            marker_len = len(loop_marker) if loop_marker else 1
            for dx in range(marker_offset, marker_offset + marker_len):
                if 0 <= dx < NODE_W:
                    style_grid[3][dx] = f"{loop_style} {bg_style}".strip()

        return _grid_to_text(grid, style_grid)


# ---------------------------------------------------------------------------
# Plan group container
# ---------------------------------------------------------------------------


class PlanGroup(Widget):
    """A transparent container occupying one plan's row band.

    Holds that plan's PR nodes and label.  Collapse/expand is a ``display``
    toggle on this container.  Each group occupies a distinct (non-overlapping)
    vertical band, so children use band-relative offsets and groups never
    occlude one another in the compositor.
    """

    DEFAULT_CSS = """
    PlanGroup {
        position: absolute;
        background: transparent;
        layers: edges nodes;
    }
    """

    def __init__(self, plan_id: str, x: int, y: int, width: int, height: int,
                 *children, **kwargs):
        super().__init__(*children, **kwargs)
        self.plan_id = plan_id
        self._offset = (x, y)
        self._band_top = y               # viewport-culling extents (set in _rebuild)
        self._band_bottom = y + height
        self.styles.width = width
        self.styles.height = height

    def on_mount(self) -> None:
        self.styles.offset = self._offset


# ---------------------------------------------------------------------------
# Tech tree container
# ---------------------------------------------------------------------------


class TechTree(Widget):
    """Renders the PR dependency graph as a navigable tech tree."""

    can_focus = True

    DEFAULT_CSS = """
    TechTree {
        layers: edges nodes;
    }
    """

    selected_index: reactive[int] = reactive(0)

    def __init__(self, prs: list[dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._prs = prs or []
        self._ordered_ids: list[str] = []
        self._node_positions: dict[str, tuple[int, int]] = {}  # pr_id -> (x_char, row)
        self._hidden_plans: set[str] = set()       # plan IDs to hide ("_standalone" for null-plan PRs)
        self._plan_map: dict[str, dict] = {}       # plan_id -> plan dict (for name lookup)
        self._plan_label_rows: dict[str, int] = {} # plan_id -> row number for label
        self._hidden_plan_label_rows: dict[str, int] = {}  # hidden plan_id -> row for collapsed label
        self._hidden_label_ids: list[str] = []              # ["_hidden:plan-001", ...] for navigation
        self._plan_group_order: list[str] = []              # ordered plan_ids (visible groups)
        self._jump_plan_scroll: bool = False                  # flag: scroll plan label to top
        from pm_core.paths import get_global_setting
        self._hide_merged: bool = get_global_setting("hide-merged")  # toggle: hide merged PRs
        self._hide_closed: bool = True                            # toggle: hide closed PRs
        self._status_filter: str | None = None                    # filter to show only this status
        self._sort_field: str | None = None                       # sort field (None = updated_at default)
        self._anim_frame: int = 0                                  # animation frame counter

        # Child-widget bookkeeping
        self._pr_map: dict[str, dict] = {}            # id -> pr dict (rebuilt in _recompute)
        self._node_widgets: dict[str, PRNode] = {}
        self._label_widgets: dict[str, PlanLabel] = {}
        self._plan_groups: list[PlanGroup] = []      # for viewport culling
        self._neighbors: dict[str, dict[str, str | None]] = {}
        self._layout_sig: tuple | None = None
        self._cached_layout = None
        self._built: bool = False
        self._scroll_watch_installed: bool = False
        self._perf_phases: dict = {}  # populated only when perf.ENABLED

    def on_mount(self) -> None:
        self._recompute()
        self._install_scroll_cull()

    def _install_scroll_cull(self) -> None:
        """Watch the scroll container so off-screen plan bands can be culled.

        Hiding a band's ``PlanGroup`` removes its nodes from Textual's
        compositor pass, which otherwise reflows *every* mounted widget on each
        keystroke — the dominant nav cost with a large tree.  Driven by the
        scroller's ``scroll_y`` so it covers keyboard, mouse-wheel and
        programmatic scrolling alike.
        """
        scroller = self.parent
        if scroller is None or self._scroll_watch_installed:
            return
        try:
            self.watch(scroller, "scroll_y", self._cull_offscreen_bands, init=False)
            self._scroll_watch_installed = True
        except Exception:
            pass

    def apply_project_settings(self, project: dict) -> None:
        """Apply per-project display settings (overrides globals if present)."""
        if "hide_merged" in project:
            self._hide_merged = bool(project["hide_merged"])

    def update_prs(self, prs: list[dict]) -> None:
        self._prs = prs
        self._recompute()

    def select_pr(self, pr_id: str) -> None:
        """Move the cursor to the given PR if it exists in the tree."""
        if not pr_id:
            return
        if pr_id not in self._ordered_ids:
            # PR might be in a hidden/collapsed plan group — find and expand it
            pr_entry = self._pr_map.get(pr_id)
            if pr_entry:
                plan_id = pr_entry.get("plan") or "_standalone"
                if plan_id in self._hidden_plans:
                    self._hidden_plans.discard(plan_id)
                    self._recompute()
        if pr_id in self._ordered_ids:
            idx = self._ordered_ids.index(pr_id)
            if idx != self.selected_index:
                self.selected_index = idx
            # Always schedule the scroll callback after a refresh so
            # programmatic selection (e.g. from the command bar) scrolls
            # reliably.
            self.refresh()
            self.call_after_refresh(self._scroll_selected_into_view)

    def update_plans(self, plans: list[dict]) -> None:
        """Store plan name mapping for label rendering."""
        self._plan_map = {p["id"]: p for p in plans if p.get("id")}

    def get_selected_plan(self) -> str | None:
        """Returns plan ID (or '_standalone') of the currently selected node.

        For hidden labels, extracts the plan_id from the virtual ID.
        """
        if not self._ordered_ids:
            return None
        sel = self._ordered_ids[self.selected_index]
        if sel.startswith("_hidden:"):
            return sel[len("_hidden:"):]
        pr = self._pr_map.get(sel)
        if not pr:
            return None
        return pr.get("plan") or "_standalone"

    def get_plan_display_name(self, plan_id: str) -> str:
        """Returns label text like 'plan-001: Import from existing repo' or 'Standalone'."""
        if plan_id == "_standalone":
            return "Standalone"
        plan = self._plan_map.get(plan_id)
        if plan and plan.get("name"):
            return f"{plan_id}: {plan['name']}"
        return plan_id

    def _get_viewport_width(self) -> int | None:
        """Return viewport width in characters, or None if unknown."""
        try:
            container = self.parent if self.parent else self
            vw = container.size.width if hasattr(container, "size") else 0
            if vw > 0:
                return vw
        except Exception:
            pass
        return None

    # -- layout caching ------------------------------------------------------

    def _auto_start_sig(self) -> tuple:
        """Auto-start ``(enabled, target)`` — drives the ◎ marker on the target.

        The target is often a *pending* node (so it isn't covered by
        ``refresh_active_nodes``), and toggling auto-start changes no PR data,
        so this must be part of the layout signature for the marker to appear
        and clear when the user toggles auto-start or repoints the target.
        """
        try:
            from pm_core.tui import auto_start as _auto_start
            enabled = _auto_start.is_enabled(self.app)
            target = _auto_start.get_target(self.app) if enabled else None
            return (enabled, target)
        except Exception:
            return (False, None)

    def _signature(self) -> tuple:
        """A hashable signature of every input that affects layout or display.

        When unchanged across calls, ``_recompute`` skips the Sugiyama layout
        and the widget rebuild entirely.
        """
        pr_sig = tuple(
            (
                pr.get("id"),
                pr.get("status"),
                pr.get("title"),
                pr.get("plan"),
                pr.get("gh_pr_number"),
                bool(pr.get("spec_pending")),
                pr.get("agent_machine"),
                bool(pr.get("workdir")),
                tuple(pr.get("depends_on") or []),
                pr.get("updated_at"), pr.get("created_at"), pr.get("started_at"),
                pr.get("reviewed_at"), pr.get("merged_at"),
            )
            for pr in self._prs
        )
        return (
            frozenset(self._hidden_plans),
            self._status_filter,
            self._hide_merged,
            self._hide_closed,
            self._sort_field,
            self._get_viewport_width(),
            self._auto_start_sig(),
            pr_sig,
        )

    def _recompute(self) -> None:
        """Recompute layout positions, rebuilding child widgets if anything changed."""
        # Cached id->pr lookup reused by selection / navigation / refresh paths,
        # so they don't each rebuild a dict over all PRs on every keystroke.
        self._pr_map = {pr["id"]: pr for pr in self._prs}
        sig = self._signature()
        layout_changed = sig != self._layout_sig
        if layout_changed:
            self._cached_layout = compute_tree_layout(
                self._prs,
                hidden_plans=self._hidden_plans,
                status_filter=self._status_filter,
                hide_merged=self._hide_merged,
                hide_closed=self._hide_closed,
                max_width=self._get_viewport_width(),
                sort_field=self._sort_field,
            )
            self._layout_sig = sig

        result = self._cached_layout
        self._ordered_ids = result.ordered_ids
        self._node_positions = result.node_positions
        self._plan_label_rows = result.plan_label_rows
        self._hidden_plan_label_rows = result.hidden_plan_label_rows
        self._hidden_label_ids = result.hidden_label_ids
        self._plan_group_order = result.plan_group_order

        if self.selected_index >= len(self._ordered_ids):
            self.selected_index = max(0, len(self._ordered_ids) - 1)

        if layout_changed or not self._built:
            self._rebuild()
            # Only mark built once a real rebuild happened.  ``_rebuild`` bails
            # out when the widget isn't mounted yet; setting ``_built`` there
            # would make a later (post-mount) ``_recompute`` with unchanged data
            # skip the build entirely and leave the tree blank.
            if self.is_mounted:
                self._built = True

    # -- content sizing ------------------------------------------------------

    def _content_size(self) -> tuple[int, int]:
        """Return (width, height) of the full content area in characters."""
        real_positions = {k: v for k, v in self._node_positions.items()
                          if not k.startswith("_hidden:")}
        if not real_positions:
            width = 40
            height = (len(self._hidden_label_ids) + 4
                      if self._hidden_label_ids else 10)
            return width, height
        max_x = max(x for x, r in real_positions.values())
        width = max_x + NODE_W + 4
        max_row = max(r for x, r in real_positions.values()) + 1
        height = max_row * (NODE_H + V_GAP) + 4 + NODE_H
        if self._hidden_label_ids:
            height += 2 + len(self._hidden_label_ids)
        return width, height

    # -- widget construction -------------------------------------------------

    def is_selected(self, node_id: str) -> bool:
        """True if *node_id* is the currently selected entry."""
        if not self._ordered_ids:
            return False
        return self._ordered_ids[self.selected_index] == node_id

    def _empty_message(self) -> str | None:
        """Return an empty-state message, or None if there is content to draw."""
        if not self._prs:
            return "No PRs defined. Use 'pr add' to create PRs."
        if not self._ordered_ids and self._status_filter:
            return f"No {self._status_filter} PRs. Press F to cycle filter."
        if not self._ordered_ids and self._hidden_plans:
            hidden_count = len(self._hidden_plans)
            return f"All PRs hidden ({hidden_count} plan(s)). Press x to show all."
        return None

    def _rebuild(self) -> None:
        """Tear down and remount child widgets for the current layout."""
        if not self.is_mounted:
            return

        self.remove_children()
        self._node_widgets = {}
        self._label_widgets = {}
        self._plan_groups = []
        self._neighbors = {}

        msg = self._empty_message()
        if msg is not None:
            # Fill the scroll viewport rather than sizing to content: a plain
            # Widget does not auto-size to its children, so "auto" here collapses
            # the tree to 0x0 and the message never renders (blank grid).  A
            # percentage size gives the mounted Static a real region to draw in.
            self.styles.width = "100%"
            self.styles.height = "100%"
            from textual.widgets import Static
            self.mount(Static(Text(msg, style="dim")))
            return

        width, height = self._content_size()
        self.styles.width = width
        self.styles.height = height

        self._neighbors = compute_neighbors(self._ordered_ids, self._node_positions)

        new_widgets: list[Widget] = []

        # Real PR nodes only have visible boxes; hidden labels handled below.
        real_node_ids = [nid for nid in self._node_positions
                         if not nid.startswith("_hidden:")]

        pr_map = self._pr_map

        # Assign each node to a *band* — the contiguous row range owned by one
        # plan group.  The layout places every connected component (and thus
        # every dependency edge) entirely within one band, so a band's edges
        # never cross into another.  Group by band (not by ``pr["plan"]``,
        # which can differ when a PR depends across plans) so each PlanGroup's
        # own EdgeCanvas captures all of its edges.
        sorted_labels = sorted(self._plan_label_rows.items(), key=lambda kv: kv[1])

        def band_of(row: int) -> str:
            band = "_standalone"
            for plan_id, lrow in sorted_labels:
                if lrow <= row:
                    band = plan_id
                else:
                    break
            return band

        # Entry: (kind, payload, global_x, global_y, h)
        band_items: dict[str, list[tuple]] = {}
        for nid in real_node_ids:
            pr = pr_map.get(nid)
            if not pr:
                continue
            col, row = self._node_positions[nid]
            band = band_of(row) if sorted_labels else "_all"
            band_items.setdefault(band, []).append(
                ("node", pr, col, _node_y(row), NODE_H))

        for plan_id, label_row in self._plan_label_rows.items():
            label_y = label_row * (NODE_H + V_GAP) + 1 + NODE_H // 2
            label_text = f" ── {self.get_plan_display_name(plan_id)} "
            if len(label_text) < width - 2:
                label_text += "─" * (width - 2 - len(label_text))
            band_items.setdefault(plan_id, []).append(
                ("label", label_text, 0, label_y, 1))

        # Build one PlanGroup per band, offset to the band, children relative.
        for band_id, items in band_items.items():
            band_top = min(gy for _, _, _, gy, _ in items)
            band_bottom = max(gy + h for _, _, _, gy, h in items)
            band_h = band_bottom - band_top
            members: list[Widget] = []
            band_positions: dict[str, tuple[int, int]] = {}
            for kind, payload, gx, gy, _h in items:
                rel_y = gy - band_top
                if kind == "node":
                    node = PRNode(self, payload, gx, rel_y)
                    nid = payload["id"]
                    band_positions[nid] = self._node_positions[nid]
                    nb = self._neighbors.get(nid, {})
                    node.neighbor_up = nb.get("up")
                    node.neighbor_down = nb.get("down")
                    node.neighbor_left = nb.get("left")
                    node.neighbor_right = nb.get("right")
                    self._node_widgets[nid] = node
                    members.append(node)
                else:
                    members.append(PlanLabel(self, payload, gx, rel_y, width))
            # Band-local edge layer (lowest within the group).
            canvas = EdgeCanvas()
            canvas.set_data(self._prs, band_positions, width, band_h, band_top)
            plan_label = band_id if band_id != "_all" else (
                self._plan_group_order[0] if self._plan_group_order else "_standalone")
            group = PlanGroup(plan_label, 0, band_top, width, band_h,
                              canvas, *members)
            group._band_top = band_top
            group._band_bottom = band_bottom
            self._plan_groups.append(group)
            new_widgets.append(group)

        # Hidden plan labels appended below the grid (navigable, selectable)
        if self._hidden_label_ids:
            real_positions = {k: v for k, v in self._node_positions.items()
                              if not k.startswith("_hidden:")}
            if real_positions:
                max_row = max(r for x, r in real_positions.values()) + 1
                base_y = max_row * (NODE_H + V_GAP) + 4 + 1
            else:
                base_y = 1
            for i, virtual_id in enumerate(self._hidden_label_ids):
                plan_id = virtual_id[len("_hidden:"):]
                pr_count = sum(1 for pr in self._prs
                               if (pr.get("plan") or "_standalone") == plan_id)
                label_text = (f" ── {self.get_plan_display_name(plan_id)} "
                              f"(hidden, {pr_count} PR{'s' if pr_count != 1 else ''}) ──")
                label = PlanLabel(self, label_text, 0, base_y + i, width,
                                  selectable_id=virtual_id)
                self._label_widgets[virtual_id] = label
                new_widgets.append(label)

        self.mount_all(new_widgets)
        # Cull bands outside the viewport once the new widgets are laid out.
        self.call_after_refresh(self._cull_offscreen_bands)

    def _cull_offscreen_bands(self, *args) -> None:
        """Show only plan bands intersecting the viewport (+ a margin).

        Off-screen ``PlanGroup``s are hidden so Textual's compositor skips
        their nodes; this keeps per-keystroke cost proportional to *visible*
        nodes rather than the whole tree.  The tree's content size is fixed
        (set in ``_rebuild``), so hiding bands never changes the scroll extent.
        """
        if not self._plan_groups:
            return
        scroller = self.parent
        if scroller is None or not hasattr(scroller, "scroll_offset"):
            return
        try:
            top = scroller.scroll_offset.y
            vh = scroller.size.height
        except Exception:
            return
        if vh <= 0:
            return
        _t = time.perf_counter() if perf.ENABLED else 0.0
        margin = NODE_H + V_GAP  # one node-row of look-ahead on each side
        vtop = top - margin
        vbot = top + vh + margin
        for group in self._plan_groups:
            visible = not (group._band_bottom < vtop or group._band_top > vbot)
            if bool(group.display) != visible:
                group.display = visible
        if perf.ENABLED:
            self._perf_phases["cull"] = (time.perf_counter() - _t) * 1000

    # -- selection / animation ----------------------------------------------

    def watch_selected_index(self, old_index: int, new_index: int) -> None:
        """Refresh only the previously- and newly-selected node widgets."""
        for idx in (old_index, new_index):
            if 0 <= idx < len(self._ordered_ids):
                nid = self._ordered_ids[idx]
                w = self._node_widgets.get(nid) or self._label_widgets.get(nid)
                if w is not None:
                    try:
                        w.refresh()
                    except Exception:
                        pass

    def advance_animation(self) -> None:
        """Advance the animation frame counter (called by poll timer)."""
        self._anim_frame = (self._anim_frame + 1) % len(SPINNER_FRAMES)

    def _is_active_pr(self, pr: dict) -> bool:
        """True if *pr*'s node may be animating (spinner / loop / merge marker)."""
        pr_id = pr.get("id")
        if pr.get("status") in ("in_progress", "in_review", "qa") and pr.get("workdir"):
            return True
        try:
            if self.app._review_loops.get(pr_id):
                return True
            if pr_id in getattr(self.app, "_merge_input_required_prs", set()):
                return True
        except Exception:
            pass
        return False

    def refresh_active_nodes(self) -> None:
        """Repaint only the nodes whose markers/spinners may have changed."""
        pr_map = self._pr_map
        for nid, node in self._node_widgets.items():
            pr = pr_map.get(nid)
            if pr is not None and self._is_active_pr(pr):
                try:
                    node.refresh()
                except Exception:
                    pass

    @property
    def selected_pr_id(self) -> str | None:
        if not self._ordered_ids:
            return None
        sel = self._ordered_ids[self.selected_index]
        if sel.startswith("_hidden:"):
            return None
        return sel

    @property
    def selected_is_hidden_label(self) -> bool:
        """True if current selection is a hidden plan label."""
        if not self._ordered_ids:
            return False
        return self._ordered_ids[self.selected_index].startswith("_hidden:")

    # -- keyboard navigation -------------------------------------------------

    def on_key(self, event) -> None:
        if not perf.ENABLED:
            return self._on_key_impl(event)
        # Instrumented path: time the synchronous handler, then report the
        # full key->repaint latency once the deferred scroll/cull callbacks
        # (scheduled below) have run.
        self._perf_phases = {}
        t0 = time.perf_counter()
        self._on_key_impl(event)
        self._perf_phases["on_key"] = (time.perf_counter() - t0) * 1000
        self.call_after_refresh(self._perf_report_key, event.key, t0)

    def _perf_report_key(self, key: str, t0: float) -> None:
        total = (time.perf_counter() - t0) * 1000
        if total < perf.THRESHOLD_MS:
            return
        ph = self._perf_phases
        on_key = ph.get("on_key", 0.0)
        scroll = ph.get("scroll", 0.0)
        cull = ph.get("cull", 0.0)
        framework = total - on_key - scroll - cull
        vis = sum(1 for g in self._plan_groups if g.display)
        perf.log(f"key={key} total={total:.0f}ms on_key={on_key:.0f} "
                 f"scroll={scroll:.0f} cull={cull:.0f} framework~={framework:.0f} "
                 f"visible_bands={vis}/{len(self._plan_groups)} "
                 f"nodes={len(self._node_widgets)}")
        try:
            self.app.log_message(
                f"⏱ {key} {total:.0f}ms (scroll {scroll:.0f}, cull {cull:.0f}, "
                f"fw {framework:.0f})", sticky=4)
        except Exception:
            pass

    def _on_key_impl(self, event) -> None:
        if not self.has_focus:
            return
        if not self._ordered_ids:
            return

        current_id = self._ordered_ids[self.selected_index]
        nb = self._neighbors.get(current_id, {})

        new_index = None

        if event.key in ("up", "k"):
            target = nb.get("up")
            if target is not None:
                new_index = self._ordered_ids.index(target)
            else:
                self._scroll_to_edge("top")
        elif event.key in ("down", "j"):
            target = nb.get("down")
            if target is not None:
                new_index = self._ordered_ids.index(target)
            else:
                self._scroll_to_edge("bottom")
        elif event.key in ("left", "h"):
            target = nb.get("left")
            if target is not None:
                new_index = self._ordered_ids.index(target)
            else:
                self._scroll_to_edge("left")
        elif event.key in ("right", "l"):
            target = nb.get("right")
            if target is not None:
                new_index = self._ordered_ids.index(target)
            else:
                self._scroll_to_edge("right")
        elif event.key == "J":
            new_index = self._jump_plan(1)
            if new_index is not None:
                self._jump_plan_scroll = True
            else:
                new_index = self._jump_plan_bottom()
        elif event.key == "K":
            top_index = self._jump_plan_top()
            if top_index is not None and top_index != self.selected_index:
                new_index = top_index
                self._jump_plan_scroll = True
            else:
                new_index = self._jump_plan(-1)
                if new_index is not None:
                    self._jump_plan_scroll = True
        elif event.key == "enter":
            if not current_id.startswith("_hidden:"):
                self.post_message(PRSelected(current_id))
                self.app.action_edit_plan()
            return

        if new_index is not None and new_index != self.selected_index:
            self.selected_index = new_index
            new_id = self._ordered_ids[new_index]
            if not new_id.startswith("_hidden:"):
                self.post_message(PRSelected(new_id))
            # Scroll to keep the selected node visible (defer until layout is
            # up to date).
            self.call_after_refresh(self._scroll_selected_into_view)

    def _scroll_to_edge(self, direction: str) -> None:
        """Scroll to an edge of the content (top/bottom/left/right)."""
        from textual.geometry import Region
        container = self.parent if self.parent else self
        if direction == "top":
            region = Region(0, 0, 1, 1)
        elif direction == "left":
            if hasattr(container, "scroll_x"):
                container.scroll_x = 0
            return
        elif direction == "right":
            real_positions = {k: v for k, v in self._node_positions.items()
                              if not k.startswith("_hidden:")}
            if real_positions:
                max_x = max(x for x, r in real_positions.values())
                right_x = max_x + NODE_W + 4
                if hasattr(container, "scroll_x") and hasattr(container, "size"):
                    container.scroll_x = max(0, right_x - container.size.width)
            return
        else:
            real_positions = {k: v for k, v in self._node_positions.items()
                              if not k.startswith("_hidden:")}
            if real_positions:
                max_row = max(r for x, r in real_positions.values())
            else:
                max_row = 0
            y = (max_row + 1) * (NODE_H + V_GAP) + NODE_H
            if self._hidden_label_ids:
                y += 2 + len(self._hidden_label_ids)
            region = Region(0, y, 1, 1)
        container.scroll_to_region(region, animate=False, force=True)

    def _jump_plan_top(self) -> int | None:
        """Return the index of the first PR in the current plan group."""
        if not self._ordered_ids:
            return None
        pr_map = self._pr_map
        current_id = self._ordered_ids[self.selected_index]
        if current_id.startswith("_hidden:"):
            current_plan = current_id[len("_hidden:"):]
        else:
            pr = pr_map.get(current_id)
            current_plan = (pr.get("plan") or "_standalone") if pr else "_standalone"

        for i, pid in enumerate(self._ordered_ids):
            if pid.startswith("_hidden:"):
                continue
            pr = pr_map.get(pid)
            if pr and (pr.get("plan") or "_standalone") == current_plan:
                return i
        return None

    def _jump_plan_bottom(self) -> int | None:
        """Return the index of the bottom-most PR (greatest row) in the plan.

        Used when ``J`` is pressed on the last plan: advance to the visual
        bottom of the tree instead of dead-ending on a mid-plan root (the
        previous behavior returned the last *root* PR, which could sit above
        other nodes and leave ``J`` looking stuck).
        """
        if not self._ordered_ids:
            return None
        pr_map = self._pr_map
        current_id = self._ordered_ids[self.selected_index]
        if current_id.startswith("_hidden:"):
            current_plan = current_id[len("_hidden:"):]
        else:
            pr = pr_map.get(current_id)
            current_plan = (pr.get("plan") or "_standalone") if pr else "_standalone"

        best_i = None
        best_row = -1
        for i, pid in enumerate(self._ordered_ids):
            if pid.startswith("_hidden:"):
                continue
            pr = pr_map.get(pid)
            if pr and (pr.get("plan") or "_standalone") == current_plan:
                row = self._node_positions.get(pid, (0, 0))[1]
                if row >= best_row:
                    best_row = row
                    best_i = i
        return best_i

    def _jump_plan(self, direction: int) -> int | None:
        """Jump to the first PR of the next/previous plan group."""
        if not self._plan_group_order or len(self._plan_group_order) < 2:
            return None

        pr_map = self._pr_map
        current_id = self._ordered_ids[self.selected_index]
        if current_id.startswith("_hidden:"):
            current_plan = current_id[len("_hidden:"):]
        else:
            pr = pr_map.get(current_id)
            current_plan = (pr.get("plan") or "_standalone") if pr else "_standalone"

        try:
            plan_idx = self._plan_group_order.index(current_plan)
        except ValueError:
            plan_idx = 0

        target_idx = plan_idx + direction
        if target_idx < 0 or target_idx >= len(self._plan_group_order):
            return None

        target_plan = self._plan_group_order[target_idx]
        for i, pid in enumerate(self._ordered_ids):
            if pid.startswith("_hidden:"):
                continue
            pr = pr_map.get(pid)
            if pr and (pr.get("plan") or "_standalone") == target_plan:
                return i
        return None

    def _scroll_selected_into_view(self) -> None:
        if not perf.ENABLED:
            return self._scroll_selected_into_view_impl()
        _t = time.perf_counter()
        try:
            self._scroll_selected_into_view_impl()
        finally:
            self._perf_phases["scroll"] = (time.perf_counter() - _t) * 1000

    def _scroll_selected_into_view_impl(self) -> None:
        """Scroll the parent container to keep the selected node visible."""
        if not self._ordered_ids:
            return
        pr_id = self._ordered_ids[self.selected_index]
        if pr_id not in self._node_positions:
            return

        from textual.geometry import Region

        if self._jump_plan_scroll:
            self._jump_plan_scroll = False
            self._scroll_plan_label_to_top(pr_id)
            return

        if pr_id.startswith("_hidden:"):
            real_positions = {k: v for k, v in self._node_positions.items()
                              if not k.startswith("_hidden:")}
            if real_positions:
                max_row = max(r for x, r in real_positions.values()) + 1
                grid_h = max_row * (NODE_H + V_GAP) + 4
            else:
                grid_h = 0
            label_index = (self._hidden_label_ids.index(pr_id)
                           if pr_id in self._hidden_label_ids else 0)
            y = grid_h + 1 + label_index
            node_region = Region(0, y, 60, 1)
        else:
            x, row = self._node_positions[pr_id]
            y = _node_y(row)
            bottom_padding = 4
            node_region = Region(x, y, NODE_W, NODE_H + V_GAP + bottom_padding)

        container = self.parent if self.parent else self
        from textual.geometry import Spacing
        container.scroll_to_region(
            node_region, animate=False, force=True,
            spacing=Spacing(top=1, bottom=2, left=0, right=0),
        )

        if not pr_id.startswith("_hidden:") and hasattr(container, "scroll_x"):
            vw = container.size.width if hasattr(container, "size") else 0
            if vw > 0:
                node_right = x + NODE_W + 2
                if x < container.scroll_x:
                    container.scroll_x = max(0, x - 2)
                elif node_right > container.scroll_x + vw:
                    container.scroll_x = node_right - vw

    def _scroll_plan_label_to_top(self, pr_id: str) -> None:
        """Scroll so the plan label header for the given PR is at the top."""
        from textual.geometry import Region
        pr = self._pr_map.get(pr_id)
        if not pr:
            return
        plan_id = pr.get("plan") or "_standalone"
        label_row = self._plan_label_rows.get(plan_id)
        if label_row is None:
            self._jump_plan_scroll = False
            self._scroll_selected_into_view()
            return

        label_y = label_row * (NODE_H + V_GAP) + NODE_H // 2
        scroller = self.parent if self.parent else self
        viewport_h = scroller.size.height if hasattr(scroller, 'size') else 40
        region = Region(0, label_y, 1, viewport_h)
        scroller.scroll_to_region(region, animate=False, force=True)
