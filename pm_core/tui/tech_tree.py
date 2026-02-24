"""Graph widget that renders PR nodes and edges in the TUI."""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.console import RenderableType

from pm_core.tui import item_message
from pm_core.tui.tree_layout import compute_tree_layout


STATUS_ICONS = {
    "pending": "○",
    "in_progress": "●",
    "in_review": "◎",
    "merged": "✓",
    "closed": "✗",
    "blocked": "✗",
}

VERDICT_MARKERS = {
    "PASS": "✓",
    "PASS_WITH_SUGGESTIONS": "~",
    "NEEDS_WORK": "✗",
    "KILLED": "☠",
    "TIMEOUT": "⏱",
    "ERROR": "!",
    "INPUT_REQUIRED": "⏸",
}

VERDICT_STYLES = {
    "PASS": "bold green",
    "PASS_WITH_SUGGESTIONS": "bold yellow",
    "NEEDS_WORK": "bold red",
    "KILLED": "bold red",
    "TIMEOUT": "bold red",
    "ERROR": "bold red",
    "INPUT_REQUIRED": "bold red",
}

SPINNER_FRAMES = "◐◓◑◒"

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

# Status filter cycle order (None = show all)
STATUS_FILTER_CYCLE = [None, "pending", "in_progress", "in_review", "merged", "closed"]

# Node dimensions
NODE_W = 24
NODE_H = 5  # 5 lines: top border, id, title, status, bottom border
H_GAP = 6
V_GAP = 2


PRSelected, _PRActivated = item_message("PR", "pr_id")


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
        self._anim_frame: int = 0                                  # animation frame counter

    def on_mount(self) -> None:
        self.prs = self._prs
        self._recompute()

    def apply_project_settings(self, project: dict) -> None:
        """Apply per-project display settings (overrides globals if present)."""
        if "hide_merged" in project:
            self._hide_merged = bool(project["hide_merged"])

    def update_prs(self, prs: list[dict]) -> None:
        self._prs = prs
        self.prs = prs
        self._recompute()
        self.refresh(layout=True)

    def select_pr(self, pr_id: str) -> None:
        """Move the cursor to the given PR if it exists in the tree."""
        if pr_id and pr_id in self._ordered_ids:
            idx = self._ordered_ids.index(pr_id)
            if idx != self.selected_index:
                self.selected_index = idx
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
        pr_map = {pr["id"]: pr for pr in self._prs}
        pr = pr_map.get(sel)
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

    def _recompute(self) -> None:
        """Recompute layout positions using the tree_layout module."""
        result = compute_tree_layout(
            self._prs,
            hidden_plans=self._hidden_plans,
            status_filter=self._status_filter,
            hide_merged=self._hide_merged,
            hide_closed=self._hide_closed,
        )
        self._ordered_ids = result.ordered_ids
        self._node_positions = result.node_positions
        self._plan_label_rows = result.plan_label_rows
        self._hidden_plan_label_rows = result.hidden_plan_label_rows
        self._hidden_label_ids = result.hidden_label_ids
        self._plan_group_order = result.plan_group_order

        if self.selected_index >= len(self._ordered_ids):
            self.selected_index = max(0, len(self._ordered_ids) - 1)

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

    def advance_animation(self) -> None:
        """Advance the animation frame counter (called by poll timer)."""
        self._anim_frame = (self._anim_frame + 1) % len(SPINNER_FRAMES)

    def _get_loop_marker(self, pr_id: str) -> tuple[str, str]:
        """Return (marker_text, marker_style) for review loop state.

        Returns a tuple of (text, style) for the marker. Empty strings if no loop.
        """
        try:
            loops = self.app._review_loops
            state = loops.get(pr_id)
            if not state:
                return ("", "")
            if state.running:
                spinner = SPINNER_FRAMES[self._anim_frame % len(SPINNER_FRAMES)]
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
        except Exception:
            pass
        return ("", "")

    def get_content_width(self, container, viewport):
        if not self._node_positions:
            return 40
        real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
        if not real_positions:
            return 40
        max_col = max(c for c, r in real_positions.values()) + 1
        return max_col * (NODE_W + H_GAP) + 4

    def get_content_height(self, container, viewport, width):
        if not self._node_positions:
            return 10
        # Only count real node rows for grid height
        real_ids = [nid for nid in self._node_positions if not nid.startswith("_hidden:")]
        if not real_ids:
            # Only hidden labels — 1 line per label + padding
            return len(self._hidden_label_ids) + 4
        max_row = max(self._node_positions[nid][1] for nid in real_ids) + 1
        # Extra padding (NODE_H) so bottom node can scroll clear of status/command bars
        height = max_row * (NODE_H + V_GAP) + 4 + NODE_H
        # Add space for hidden labels (1 line each + gap)
        if self._hidden_label_ids:
            height += 2 + len(self._hidden_label_ids)
        return height

    def render(self) -> RenderableType:
        if not self._prs:
            return Text("No PRs defined. Use 'pr add' to create PRs.", style="dim")

        if not self._ordered_ids and self._status_filter:
            icon = STATUS_ICONS.get(self._status_filter, "?")
            return Text(f"No {self._status_filter} PRs. Press F to cycle filter.", style="dim")

        if not self._ordered_ids and self._hidden_plans:
            hidden_count = len(self._hidden_plans)
            return Text(f"All PRs hidden ({hidden_count} plan(s)). Press x to show all.", style="dim")

        # If only hidden labels exist (no visible PR nodes), render just the labels
        visible_node_ids = [nid for nid in self._node_positions if not nid.startswith("_hidden:")]
        if not visible_node_ids and self._hidden_label_ids:
            return self._render_hidden_labels_only()

        pr_map = {pr["id"]: pr for pr in self._prs}
        lines: list[Text] = []

        # Compute grid dimensions from real nodes only (not hidden labels)
        real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
        if not real_positions:
            return self._render_hidden_labels_only()
        max_col = max(c for c, r in real_positions.values()) + 1
        max_row = max(r for c, r in real_positions.values()) + 1

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

        # Pre-compute exit/entry y-offsets for each edge so that multiple
        # connections on the same node fan out across its interior height
        # instead of all sharing the center line.
        # Interior rows within a node: 1, 2, 3 (NODE_H=5: border,id,title,status,border)
        outgoing: dict[str, list[str]] = {}   # src_id -> [dst_ids] sorted by dst row
        incoming: dict[str, list[str]] = {}   # dst_id -> [src_ids] sorted by src row
        for dep_id, pr_id in edges:
            outgoing.setdefault(dep_id, []).append(pr_id)
            incoming.setdefault(pr_id, []).append(dep_id)
        # Sort each list by the connected node's row position
        for src_id, dst_ids in outgoing.items():
            dst_ids.sort(key=lambda d: self._node_positions[d][1])
        for dst_id, src_ids in incoming.items():
            src_ids.sort(key=lambda s: self._node_positions[s][1])

        def _spread_offsets(n: int) -> list[int]:
            """Distribute n connection points across interior rows 1..3."""
            if n == 1:
                return [NODE_H // 2]  # center (row 2)
            if n == 2:
                return [1, NODE_H - 2]  # top and bottom interior
            # n >= 3: spread evenly across rows 1..3
            return [1 + round(i * (NODE_H - 3) / (n - 1)) for i in range(n)]

        exit_offsets: dict[str, dict[str, int]] = {}   # src -> {dst -> y_offset}
        entry_offsets: dict[str, dict[str, int]] = {}   # dst -> {src -> y_offset}
        for src_id, dst_ids in outgoing.items():
            offsets = _spread_offsets(len(dst_ids))
            exit_offsets[src_id] = {dst: offsets[i] for i, dst in enumerate(dst_ids)}
        for dst_id, src_ids in incoming.items():
            # For same-row edges, match the entry offset to the exit offset
            # so the line is perfectly straight.  Spread the remaining
            # (non-same-row) sources across the leftover interior slots.
            same_row: dict[str, int] = {}   # src -> matched offset
            other_srcs: list[str] = []
            dst_row = self._node_positions[dst_id][1]
            for src in src_ids:
                src_row = self._node_positions[src][1]
                if src_row == dst_row and dst_id in exit_offsets.get(src, {}):
                    same_row[src] = exit_offsets[src][dst_id]
                else:
                    other_srcs.append(src)
            if not other_srcs:
                # All sources are same-row; just use matched offsets
                entry_offsets[dst_id] = dict(same_row)
            else:
                # Spread non-same-row sources across slots not taken by
                # same-row edges
                taken = set(same_row.values())
                all_offsets = _spread_offsets(len(src_ids))
                free_offsets = [o for o in all_offsets if o not in taken]
                # If not enough free slots, fall back to full spread
                if len(free_offsets) < len(other_srcs):
                    free_offsets = _spread_offsets(len(other_srcs))
                mapping = dict(same_row)
                for i, src in enumerate(other_srcs):
                    mapping[src] = free_offsets[i]
                entry_offsets[dst_id] = mapping

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
            src_dy = exit_offsets.get(dep_id, {}).get(pr_id, NODE_H // 2)
            dst_dy = entry_offsets.get(pr_id, {}).get(dep_id, NODE_H // 2)
            src_y = sy + src_dy
            dst_y = ey + dst_dy
            arrow_start_x = sx + NODE_W
            arrow_end_x = ex - 1

            if arrow_end_x > arrow_start_x:
                if src_y == dst_y:
                    # Simple horizontal arrow
                    for x in range(arrow_start_x, arrow_end_x + 1):
                        safe_write(src_y, x, "─", "dim")
                    safe_write(src_y, arrow_end_x, "▶", "dim")
                else:
                    # Find a free vertical channel in the gap.
                    # Search from the destination side inward so that
                    # nearer edges use outer channels and peel off
                    # without crossing farther edges' verticals.
                    gap_start = arrow_start_x + 1
                    gap_end = arrow_end_x - 1
                    mid_x = gap_end

                    for test_x in range(gap_end, gap_start - 1, -1):
                        if channel_free(test_x, src_y, dst_y):
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

        # Auto-start target detection (for ◎ marker)
        from pm_core.tui import auto_start as _auto_start
        auto_start_enabled = _auto_start.is_enabled(self.app)
        auto_start_target = _auto_start.get_target(self.app) if auto_start_enabled else None

        # Draw nodes (skip virtual hidden label IDs)
        for pr_id, (col, row) in self._node_positions.items():
            if pr_id.startswith("_hidden:"):
                continue
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
            # Mark the auto-start target PR
            is_auto_target = (auto_start_enabled and auto_start_target == pr_id)
            max_id_len = NODE_W - 4
            if is_auto_target:
                # Reserve 2 chars for " ◎"
                truncated_id = display_id[:max_id_len - 2]
                id_content = f"{truncated_id} ◎"
            else:
                id_content = display_id[:max_id_len]
            id_line = f"{side} {id_content:<{max_id_len}} {side}"
            title = pr.get("title", "???")
            max_title_len = NODE_W - 4
            if len(title) > max_title_len:
                title = title[:max_title_len - 1] + "…"  # Unicode ellipsis
            title_line = f"{side} {title:<{NODE_W - 4}} {side}"
            status_text = f"{icon} {status}"
            # Show review loop marker or verdict if a loop exists for this PR
            loop_marker, loop_style = self._get_loop_marker(pr_id)
            marker_offset = -1  # char offset within status_line where marker starts
            if loop_marker:
                marker_offset = 2 + len(status_text) + 1  # side + space + base text + space
                status_text += f" {loop_marker}"
            else:
                # Show activity spinner for in_progress/in_review PRs
                # (suppressed when the implementation pane is idle)
                if status in ("in_progress", "in_review") and pr.get("workdir"):
                    pane_idle = self.app._pane_idle_tracker.is_idle(pr_id)
                    if not pane_idle:
                        spinner = SPINNER_FRAMES[self._anim_frame % len(SPINNER_FRAMES)]
                        marker_offset = 2 + len(status_text) + 1
                        loop_style = "bold cyan"
                        status_text += f" {spinner}"
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

            # Apply colored style to auto-start target marker (◎) on id_line
            if is_auto_target:
                target_dx = 2 + len(truncated_id) + 1  # side + space + id + space
                id_dy = 1  # id_line is 2nd row (index 1) in box_lines
                if 0 <= (y + id_dy) < len(style_grid) and 0 <= (x + target_dx) < len(style_grid[0]):
                    style_grid[y + id_dy][x + target_dx] = f"bold magenta {bg_style}".strip()

            # Apply colored style to loop marker / spinner characters
            if marker_offset >= 0 and loop_style:
                status_dy = 3  # status_line is 4th row (index 3) in box_lines
                marker_len = len(loop_marker) if loop_marker else 1
                for dx in range(marker_offset, marker_offset + marker_len):
                    if 0 <= (y + status_dy) < len(style_grid) and 0 <= (x + dx) < len(style_grid[0]):
                        style_grid[y + status_dy][x + dx] = f"{loop_style} {bg_style}".strip()

        # Draw plan labels
        for plan_id, label_row in self._plan_label_rows.items():
            label_y = label_row * (NODE_H + V_GAP) + 1 + NODE_H // 2
            label_text = f" ── {self.get_plan_display_name(plan_id)} "
            grid_w = len(grid[0]) if grid else 0
            # Pad with ─ to fill width
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

        # Append hidden plan labels below the grid
        if self._hidden_plan_label_rows:
            output.append("\n")
            for plan_id in sorted(self._hidden_plan_label_rows):
                pr_count = sum(1 for pr in self._prs if (pr.get("plan") or "_standalone") == plan_id)
                label_text = f" ── {self.get_plan_display_name(plan_id)} (hidden, {pr_count} PR{'s' if pr_count != 1 else ''}) ──"
                virtual_id = f"_hidden:{plan_id}"
                is_selected = (self._ordered_ids[self.selected_index] == virtual_id if self._ordered_ids else False)
                style = "bold white" if is_selected else "dim"
                output.append(label_text, style=style)
                output.append("\n")

        return output

    def _render_hidden_labels_only(self) -> RenderableType:
        """Render only hidden plan labels when no visible PR nodes exist."""
        output = Text()
        for plan_id, label_row in self._hidden_plan_label_rows.items():
            pr_count = sum(1 for pr in self._prs if (pr.get("plan") or "_standalone") == plan_id)
            label_text = f" ── {self.get_plan_display_name(plan_id)} (hidden, {pr_count} PR{'s' if pr_count != 1 else ''}) ──"
            virtual_id = f"_hidden:{plan_id}"
            is_selected = (self._ordered_ids[self.selected_index] == virtual_id if self._ordered_ids else False)
            style = "bold white" if is_selected else "dim"
            output.append(label_text, style=style)
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
            # Move up: prefer same column, but allow other columns if none in same
            candidates = [(i, pid) for i, pid in enumerate(self._ordered_ids)
                          if self._node_positions[pid][1] < cur_row]
            if candidates:
                # Prioritize same column, then closest column, then closest row
                new_index = max(candidates, key=lambda x: (
                    self._node_positions[x[1]][0] == cur_col,  # same column first
                    -abs(self._node_positions[x[1]][0] - cur_col),  # then closest column
                    self._node_positions[x[1]][1]  # then highest row (closest to current)
                ))[0]
            else:
                # Already at top — scroll to reveal plan label header
                self._scroll_to_edge("top")
        elif event.key in ("down", "j"):
            candidates = [(i, pid) for i, pid in enumerate(self._ordered_ids)
                          if self._node_positions[pid][1] > cur_row]
            if candidates:
                # Prioritize same column, then closest column, then closest row
                new_index = min(candidates, key=lambda x: (
                    self._node_positions[x[1]][0] != cur_col,  # same column first (False < True)
                    abs(self._node_positions[x[1]][0] - cur_col),  # then closest column
                    self._node_positions[x[1]][1]  # then lowest row (closest to current)
                ))[0]
            else:
                # Already at bottom — scroll to reveal bottom content
                self._scroll_to_edge("bottom")
        elif event.key in ("left", "h"):
            # Move left: must be in a column to the left, prefer same row
            candidates = [(i, pid) for i, pid in enumerate(self._ordered_ids)
                          if self._node_positions[pid][0] < cur_col]
            if candidates:
                # Prefer same row, then closest row in closest column
                same_row = [(i, pid) for i, pid in candidates
                            if self._node_positions[pid][1] == cur_row]
                if same_row:
                    new_index = max(same_row, key=lambda x: self._node_positions[x[1]][0])[0]
                else:
                    new_index = min(candidates, key=lambda x: (cur_col - self._node_positions[x[1]][0],
                                                               abs(self._node_positions[x[1]][1] - cur_row)))[0]
        elif event.key in ("right", "l"):
            # Move right: must be in a column to the right, prefer same row
            candidates = [(i, pid) for i, pid in enumerate(self._ordered_ids)
                          if self._node_positions[pid][0] > cur_col]
            if candidates:
                # Prefer same row, then closest row in closest column
                same_row = [(i, pid) for i, pid in candidates
                            if self._node_positions[pid][1] == cur_row]
                if same_row:
                    new_index = min(same_row, key=lambda x: self._node_positions[x[1]][0])[0]
                else:
                    new_index = min(candidates, key=lambda x: (self._node_positions[x[1]][0] - cur_col,
                                                               abs(self._node_positions[x[1]][1] - cur_row)))[0]
        elif event.key == "J":
            # Jump to first PR of next plan group, or last PR if on bottom plan
            new_index = self._jump_plan(1)
            if new_index is None:
                # Already on bottom plan — jump to last PR
                new_index = self._jump_plan_bottom()
            if new_index is not None:
                self._jump_plan_scroll = True
        elif event.key == "K":
            # Jump to top of current plan first, then to previous plan
            top_index = self._jump_plan_top()
            if top_index is not None and top_index != self.selected_index:
                new_index = top_index
            else:
                new_index = self._jump_plan(-1)
            if new_index is not None:
                self._jump_plan_scroll = True
        elif event.key == "enter":
            if not current_id.startswith("_hidden:"):
                self.post_message(PRSelected(current_id))
                # Trigger edit action (same as 'e' key)
                self.app.action_edit_plan()
            return

        if new_index is not None and new_index != self.selected_index:
            self.selected_index = new_index
            new_id = self._ordered_ids[new_index]
            if not new_id.startswith("_hidden:"):
                self.post_message(PRSelected(new_id))
            self.refresh()
            # Scroll to keep selected node visible
            self._scroll_selected_into_view()

    def _scroll_to_edge(self, direction: str) -> None:
        """Scroll to the top or bottom edge of the content.

        For bottom: targets well past the last node so it clears the
        status/command bars that overlay the bottom of the viewport.
        """
        from textual.geometry import Region
        if direction == "top":
            region = Region(0, 0, 1, 1)
        else:
            # Target the very bottom of content with extra margin
            real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
            if real_positions:
                max_row = max(r for c, r in real_positions.values())
            else:
                max_row = 0
            # Position well past the last node's bottom border
            y = (max_row + 1) * (NODE_H + V_GAP) + NODE_H
            if self._hidden_label_ids:
                y += 2 + len(self._hidden_label_ids)
            region = Region(0, y, 1, 1)
        if self.parent:
            self.parent.scroll_to_region(region)
        else:
            self.scroll_to_region(region)

    def _jump_plan_top(self) -> int | None:
        """Return the index of the first PR in the current plan group.

        Returns:
            Index of the first PR in the current plan, or None if not applicable.
        """
        if not self._ordered_ids:
            return None

        current_id = self._ordered_ids[self.selected_index]
        if current_id.startswith("_hidden:"):
            current_plan = current_id[len("_hidden:"):]
        else:
            pr_map = {pr["id"]: pr for pr in self._prs}
            pr = pr_map.get(current_id)
            current_plan = (pr.get("plan") or "_standalone") if pr else "_standalone"

        # Find first PR in ordered_ids that belongs to current plan
        pr_map = {pr["id"]: pr for pr in self._prs}
        for i, pid in enumerate(self._ordered_ids):
            if pid.startswith("_hidden:"):
                continue
            pr = pr_map.get(pid)
            if pr and (pr.get("plan") or "_standalone") == current_plan:
                return i

        return None

    def _jump_plan_bottom(self) -> int | None:
        """Return the index of the last root PR (no dependencies) in the current plan.

        A root PR has no depends_on — it sits in the leftmost column.
        Returns the last such root in ordering (bottom of the TUI).

        Returns:
            Index of the last root PR in the current plan, or None.
        """
        if not self._ordered_ids:
            return None

        current_id = self._ordered_ids[self.selected_index]
        if current_id.startswith("_hidden:"):
            current_plan = current_id[len("_hidden:"):]
        else:
            pr_map = {pr["id"]: pr for pr in self._prs}
            pr = pr_map.get(current_id)
            current_plan = (pr.get("plan") or "_standalone") if pr else "_standalone"

        pr_map = {pr["id"]: pr for pr in self._prs}
        last_root = None
        for i, pid in enumerate(self._ordered_ids):
            if pid.startswith("_hidden:"):
                continue
            pr = pr_map.get(pid)
            if pr and (pr.get("plan") or "_standalone") == current_plan:
                if not pr.get("depends_on"):
                    last_root = i

        return last_root

    def _jump_plan(self, direction: int) -> int | None:
        """Jump to the first PR of the next/previous plan group.

        Args:
            direction: 1 for next plan, -1 for previous plan

        Returns:
            New index in _ordered_ids, or None if no jump possible.
        """
        if not self._plan_group_order or len(self._plan_group_order) < 2:
            return None

        # Determine current plan
        current_id = self._ordered_ids[self.selected_index]
        if current_id.startswith("_hidden:"):
            current_plan = current_id[len("_hidden:"):]
        else:
            pr_map = {pr["id"]: pr for pr in self._prs}
            pr = pr_map.get(current_id)
            current_plan = (pr.get("plan") or "_standalone") if pr else "_standalone"

        # Find current plan's position in group order
        try:
            plan_idx = self._plan_group_order.index(current_plan)
        except ValueError:
            plan_idx = 0

        # Compute target plan index
        target_idx = plan_idx + direction
        if target_idx < 0 or target_idx >= len(self._plan_group_order):
            return None

        target_plan = self._plan_group_order[target_idx]

        # Find first PR in ordered_ids that belongs to target plan
        pr_map = {pr["id"]: pr for pr in self._prs}
        for i, pid in enumerate(self._ordered_ids):
            if pid.startswith("_hidden:"):
                continue
            pr = pr_map.get(pid)
            if pr and (pr.get("plan") or "_standalone") == target_plan:
                return i

        return None

    def _scroll_selected_into_view(self) -> None:
        """Scroll the parent container to keep the selected node visible."""
        if not self._ordered_ids:
            return
        pr_id = self._ordered_ids[self.selected_index]
        if pr_id not in self._node_positions:
            return

        from textual.geometry import Region

        # When jumping between plans, scroll the plan label to the top
        if self._jump_plan_scroll:
            self._jump_plan_scroll = False
            self._scroll_plan_label_to_top(pr_id)
            return

        if pr_id.startswith("_hidden:"):
            # Hidden labels are appended after the grid as text lines.
            # Calculate their y position: grid height + gap + label index
            real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
            if real_positions:
                max_row = max(r for c, r in real_positions.values()) + 1
                grid_h = max_row * (NODE_H + V_GAP) + 4
            else:
                grid_h = 0
            label_index = self._hidden_label_ids.index(pr_id) if pr_id in self._hidden_label_ids else 0
            y = grid_h + 1 + label_index
            node_region = Region(0, y, 60, 1)
        else:
            col, row = self._node_positions[pr_id]
            x = col * (NODE_W + H_GAP) + 2
            y = row * (NODE_H + V_GAP) + 1
            # Extra height so the node doesn't end up flush against the
            # bottom edge where it gets obscured by the command bar.
            node_region = Region(x, y, NODE_W, NODE_H + V_GAP + 1)

        if self.parent:
            self.parent.scroll_to_region(node_region)
        else:
            self.scroll_to_region(node_region)

    def _scroll_plan_label_to_top(self, pr_id: str) -> None:
        """Scroll so the plan label header for the given PR is at the top of the viewport."""
        from textual.geometry import Region
        # Find the plan for this PR
        pr_map = {pr["id"]: pr for pr in self._prs}
        pr = pr_map.get(pr_id)
        if not pr:
            return
        plan_id = pr.get("plan") or "_standalone"
        label_row = self._plan_label_rows.get(plan_id)
        if label_row is None:
            # No plan label (single group) — just scroll to the PR
            self._jump_plan_scroll = False
            self._scroll_selected_into_view()
            return

        # Plan label is drawn at: label_row * (NODE_H + V_GAP) + 1 + NODE_H // 2
        # Subtract 1 so the dashes above the label text are visible
        label_y = label_row * (NODE_H + V_GAP) + NODE_H // 2
        # Use a region as tall as the viewport to force label to top
        scroller = self.parent if self.parent else self
        viewport_h = scroller.size.height if hasattr(scroller, 'size') else 40
        region = Region(0, label_y, 1, viewport_h)
        scroller.scroll_to_region(region)
