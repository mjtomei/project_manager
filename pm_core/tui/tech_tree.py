"""Graph widget that renders PR nodes and edges in the TUI.

Compositional architecture: TechTree is a container that manages
individually-positioned PRNode widgets and a cached EdgeCanvas layer.
Spinner updates only refresh the 2-3 active nodes instead of
repainting the entire tree.
"""

from textual.widget import Widget
from textual.reactive import reactive
from rich.text import Text
from rich.console import RenderableType

from pm_core.tui import item_message
from pm_core.tui.tree_layout import compute_tree_layout, SORT_FIELDS, SORT_FIELD_KEYS
from pm_core.tui.pr_node import (
    PRNode,
    STATUS_ICONS, STATUS_STYLES, STATUS_BG, STATUS_FILTER_CYCLE,
    SPINNER_FRAMES, VERDICT_MARKERS, VERDICT_STYLES,
    NODE_W, NODE_H, H_GAP, V_GAP,
)
from pm_core.tui.edge_canvas import EdgeCanvas


PRSelected, _PRActivated = item_message("PR", "pr_id")


class TechTree(Widget, can_focus=True):
    """Renders the PR dependency graph as a navigable tech tree.

    Composes individual PRNode widgets (absolute-positioned) over a
    cached EdgeCanvas background layer.  Animation ticks only refresh
    the few nodes that have active spinners.
    """

    selected_index: reactive[int] = reactive(0)
    prs: reactive[list] = reactive(list, init=False)

    DEFAULT_CSS = """
    TechTree {
        height: auto;
        width: auto;
        padding: 1 2;
    }
    """

    def __init__(self, prs: list[dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._prs = prs or []
        self._ordered_ids: list[str] = []
        self._node_positions: dict[str, tuple[int, int]] = {}
        self._hidden_plans: set[str] = set()
        self._plan_map: dict[str, dict] = {}
        self._plan_label_rows: dict[str, int] = {}
        self._hidden_plan_label_rows: dict[str, int] = {}
        self._hidden_label_ids: list[str] = []
        self._plan_group_order: list[str] = []
        self._jump_plan_scroll: bool = False
        from pm_core.paths import get_global_setting
        self._hide_merged: bool = get_global_setting("hide-merged")
        self._hide_closed: bool = True
        self._status_filter: str | None = None
        self._sort_field: str | None = None
        self._anim_frame: int = 0
        # Widget references
        self._node_widgets: dict[str, PRNode] = {}
        self._edge_canvas: EdgeCanvas | None = None
        # Layout cache
        self._layout_cache_key: tuple | None = None
        # Neighbor map for keyboard navigation
        self._neighbors: dict[str, dict[str, str | None]] = {}

    def compose(self):
        yield EdgeCanvas(id="edge-canvas")

    def on_mount(self) -> None:
        self._edge_canvas = self.query_one("#edge-canvas", EdgeCanvas)
        self._edge_canvas.styles.position = "absolute"
        self.prs = self._prs
        self._recompute()

    def apply_project_settings(self, project: dict) -> None:
        if "hide_merged" in project:
            self._hide_merged = bool(project["hide_merged"])

    def update_prs(self, prs: list[dict]) -> None:
        self._prs = prs
        self.prs = prs
        self._recompute()
        self._rebuild_widgets()

    def select_pr(self, pr_id: str) -> None:
        if pr_id and pr_id in self._ordered_ids:
            idx = self._ordered_ids.index(pr_id)
            if idx != self.selected_index:
                self.selected_index = idx
                self._update_selection()
            self.call_after_refresh(self._scroll_selected_into_view)

    def update_plans(self, plans: list[dict]) -> None:
        self._plan_map = {p["id"]: p for p in plans if p.get("id")}

    def get_selected_plan(self) -> str | None:
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
        if plan_id == "_standalone":
            return "Standalone"
        plan = self._plan_map.get(plan_id)
        if plan and plan.get("name"):
            return f"{plan_id}: {plan['name']}"
        return plan_id

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
        if not self._ordered_ids:
            return False
        return self._ordered_ids[self.selected_index].startswith("_hidden:")

    def advance_animation(self) -> None:
        """Advance animation frame. Only refreshes nodes with active spinners."""
        self._anim_frame = (self._anim_frame + 1) % len(SPINNER_FRAMES)
        for node in self._node_widgets.values():
            node.advance_animation()

    # ------------------------------------------------------------------
    # Layout computation (with caching)
    # ------------------------------------------------------------------

    def _get_viewport_width(self) -> int | None:
        try:
            container = self.parent if self.parent else self
            vw = container.size.width if hasattr(container, "size") else 0
            if vw > 0:
                return vw
        except Exception:
            pass
        return None

    def _make_cache_key(self) -> tuple:
        """Build a hashable key from all inputs that affect layout."""
        pr_tuples = tuple(
            (pr["id"], pr.get("status"), pr.get("plan"),
             tuple(sorted(pr.get("depends_on") or [])))
            for pr in sorted(self._prs, key=lambda p: p["id"])
        )
        return (
            pr_tuples,
            frozenset(self._hidden_plans),
            self._status_filter,
            self._hide_merged,
            self._hide_closed,
            self._get_viewport_width(),
            self._sort_field,
        )

    def _recompute(self) -> None:
        """Recompute layout positions, using cache when possible."""
        cache_key = self._make_cache_key()
        if cache_key == self._layout_cache_key:
            return

        result = compute_tree_layout(
            self._prs,
            hidden_plans=self._hidden_plans,
            status_filter=self._status_filter,
            hide_merged=self._hide_merged,
            hide_closed=self._hide_closed,
            max_width=self._get_viewport_width(),
            sort_field=self._sort_field,
        )
        self._ordered_ids = result.ordered_ids
        self._node_positions = result.node_positions
        self._plan_label_rows = result.plan_label_rows
        self._hidden_plan_label_rows = result.hidden_plan_label_rows
        self._hidden_label_ids = result.hidden_label_ids
        self._plan_group_order = result.plan_group_order
        self._layout_cache_key = cache_key

        if self.selected_index >= len(self._ordered_ids):
            self.selected_index = max(0, len(self._ordered_ids) - 1)

        self._build_neighbor_map()

    # ------------------------------------------------------------------
    # Widget management
    # ------------------------------------------------------------------

    def _rebuild_widgets(self) -> None:
        """Sync PRNode widgets to match current layout positions."""
        if not self.is_mounted:
            return

        pr_map = {pr["id"]: pr for pr in self._prs}
        # Determine which PR IDs need visible node widgets
        visible_pr_ids = {
            pid for pid in self._node_positions
            if not pid.startswith("_hidden:")
        }

        # Remove widgets for PRs no longer visible
        to_remove = set(self._node_widgets.keys()) - visible_pr_ids
        for pid in to_remove:
            widget = self._node_widgets.pop(pid)
            widget.remove()

        # Add/update widgets for visible PRs
        for pid in visible_pr_ids:
            pr = pr_map.get(pid)
            if not pr:
                continue
            x, row = self._node_positions[pid]
            y = row * (NODE_H + V_GAP) + 1

            if pid in self._node_widgets:
                node = self._node_widgets[pid]
                node.update_pr(pr)
            else:
                node = PRNode(pr, id=f"pr-{pid}")
                node.styles.position = "absolute"
                self._node_widgets[pid] = node
                self.mount(node)

            node.styles.offset = (x, y)

        # Update selection state
        self._update_selection()

        # Update auto-start target
        self._update_auto_target()

        # Update edge canvas
        self._update_edge_canvas()

        # Refresh the whole tree for hidden labels (rendered in render())
        self.refresh(layout=True)

    def _update_selection(self) -> None:
        """Update selection highlight across node widgets."""
        selected_id = self._ordered_ids[self.selected_index] if self._ordered_ids else None
        for pid, node in self._node_widgets.items():
            node.set_selected(pid == selected_id)
        # Hidden label selection is handled in render()
        if selected_id and selected_id.startswith("_hidden:"):
            self.refresh()

    def _update_auto_target(self) -> None:
        """Update auto-start target marker on nodes."""
        try:
            from pm_core.tui import auto_start as _auto_start
            auto_start_enabled = _auto_start.is_enabled(self.app)
            auto_start_target = _auto_start.get_target(self.app) if auto_start_enabled else None
        except Exception:
            auto_start_target = None

        for pid, node in self._node_widgets.items():
            node.set_auto_target(pid == auto_start_target)

    def _update_edge_canvas(self) -> None:
        """Update the edge canvas with current edges and positions."""
        if not self._edge_canvas:
            return

        # Collect edges
        edges: list[tuple[str, str]] = []
        for pr in self._prs:
            for dep_id in pr.get("depends_on") or []:
                if dep_id in self._node_positions and pr["id"] in self._node_positions:
                    if not dep_id.startswith("_hidden:") and not pr["id"].startswith("_hidden:"):
                        edges.append((dep_id, pr["id"]))

        # Compute canvas dimensions
        real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
        if real_positions:
            max_x = max(x for x, r in real_positions.values())
            max_row = max(r for x, r in real_positions.values()) + 1
            canvas_w = max_x + NODE_W + 10
            canvas_h = max_row * (NODE_H + V_GAP) + 4 + NODE_H
        else:
            canvas_w = 40
            canvas_h = 10

        # Plan labels
        plan_labels = {
            plan_id: (label_row, self.get_plan_display_name(plan_id))
            for plan_id, label_row in self._plan_label_rows.items()
        }

        # Size and position edge canvas
        self._edge_canvas.styles.width = canvas_w
        self._edge_canvas.styles.height = canvas_h
        self._edge_canvas.styles.offset = (0, 0)

        self._edge_canvas.update_edges(edges, self._node_positions, canvas_w, canvas_h, plan_labels)

    # ------------------------------------------------------------------
    # Content sizing (for scrolling)
    # ------------------------------------------------------------------

    def get_content_width(self, container, viewport):
        if not self._node_positions:
            return 40
        real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
        if not real_positions:
            return 40
        max_x = max(x for x, r in real_positions.values())
        return max_x + NODE_W + 4

    def get_content_height(self, container, viewport, width):
        if not self._node_positions:
            return 10
        real_ids = [nid for nid in self._node_positions if not nid.startswith("_hidden:")]
        if not real_ids:
            return len(self._hidden_label_ids) + 4
        max_row = max(self._node_positions[nid][1] for nid in real_ids) + 1
        height = max_row * (NODE_H + V_GAP) + 4 + NODE_H
        if self._hidden_label_ids:
            height += 2 + len(self._hidden_label_ids)
        return height

    # ------------------------------------------------------------------
    # Rendering (only for empty states and hidden labels)
    # ------------------------------------------------------------------

    def render(self) -> RenderableType:
        if not self._prs:
            return Text("No PRs defined. Use 'pr add' to create PRs.", style="dim")

        if not self._ordered_ids and self._status_filter:
            return Text(f"No {self._status_filter} PRs. Press F to cycle filter.", style="dim")

        if not self._ordered_ids and self._hidden_plans:
            hidden_count = len(self._hidden_plans)
            return Text(f"All PRs hidden ({hidden_count} plan(s)). Press x to show all.", style="dim")

        visible_node_ids = [nid for nid in self._node_positions if not nid.startswith("_hidden:")]
        if not visible_node_ids and self._hidden_label_ids:
            return self._render_hidden_labels_only()

        # Render hidden plan labels below the grid (if any)
        if self._hidden_plan_label_rows:
            return self._render_hidden_labels_section()

        return Text("")

    def _render_hidden_labels_only(self) -> RenderableType:
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

    def _render_hidden_labels_section(self) -> RenderableType:
        """Render hidden labels positioned below the visible grid.

        Since PRNode widgets render on top via absolute positioning,
        this render output is only visible in the area below the nodes
        where hidden plan labels appear.
        """
        # Compute vertical offset (empty lines to push labels below the grid)
        real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
        if real_positions:
            max_row = max(r for x, r in real_positions.values()) + 1
            grid_h = max_row * (NODE_H + V_GAP) + 4 + NODE_H
        else:
            grid_h = 0

        output = Text()
        # Pad with newlines to position below the grid
        output.append("\n" * grid_h)
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

    # ------------------------------------------------------------------
    # Keyboard navigation
    # ------------------------------------------------------------------

    def _build_neighbor_map(self) -> None:
        """Build a neighbor map for O(1) keyboard navigation.

        For each node, computes the best up/down/left/right neighbor
        based on grid positions.
        """
        self._neighbors = {}
        if not self._ordered_ids:
            return

        ids_with_pos = [
            (i, pid, self._node_positions[pid])
            for i, pid in enumerate(self._ordered_ids)
            if pid in self._node_positions
        ]

        for idx, pid, (col, row) in ids_with_pos:
            neighbors: dict[str, str | None] = {"up": None, "down": None, "left": None, "right": None}

            best_up = None
            best_down = None
            best_left = None
            best_right = None

            for other_idx, other_pid, (other_col, other_row) in ids_with_pos:
                if other_pid == pid:
                    continue

                # Up: row above, prefer same column, then closest
                if other_row < row:
                    score = (other_col == col, -abs(other_col - col), other_row)
                    if best_up is None or score > best_up[0]:
                        best_up = (score, other_pid)

                # Down: row below, prefer same column, then closest
                if other_row > row:
                    score = (other_col == col, -abs(other_col - col), -other_row)
                    if best_down is None or score > best_down[0]:
                        best_down = (score, other_pid)

                # Left: column to the left, prefer same row
                if other_col < col:
                    if other_row == row:
                        score = (1, other_col)  # same row, rightmost
                    else:
                        score = (0, -abs(other_row - row), -(col - other_col))
                    if best_left is None or score > best_left[0]:
                        best_left = (score, other_pid)

                # Right: column to the right, prefer same row
                if other_col > col:
                    if other_row == row:
                        score = (1, -other_col)  # same row, leftmost
                    else:
                        score = (0, -abs(other_row - row), -(other_col - col))
                    if best_right is None or score > best_right[0]:
                        best_right = (score, other_pid)

            neighbors["up"] = best_up[1] if best_up else None
            neighbors["down"] = best_down[1] if best_down else None
            neighbors["left"] = best_left[1] if best_left else None
            neighbors["right"] = best_right[1] if best_right else None
            self._neighbors[pid] = neighbors

    def on_key(self, event) -> None:
        if not self.has_focus:
            return
        if not self._ordered_ids:
            return

        current_id = self._ordered_ids[self.selected_index]
        new_index = None

        direction_map = {
            "up": "up", "k": "up",
            "down": "down", "j": "down",
            "left": "left", "h": "left",
            "right": "right", "l": "right",
        }

        if event.key in direction_map:
            direction = direction_map[event.key]
            neighbor_id = self._neighbors.get(current_id, {}).get(direction)
            if neighbor_id and neighbor_id in self._ordered_ids:
                new_index = self._ordered_ids.index(neighbor_id)
            else:
                # At edge — scroll to reveal content
                edge_map = {"up": "top", "down": "bottom", "left": "left", "right": "right"}
                self._scroll_to_edge(edge_map[direction])
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
            self._update_selection()
            self.call_after_refresh(self._scroll_selected_into_view)

    # ------------------------------------------------------------------
    # Scrolling helpers
    # ------------------------------------------------------------------

    def _scroll_to_edge(self, direction: str) -> None:
        from textual.geometry import Region
        container = self.parent if self.parent else self
        if direction == "top":
            region = Region(0, 0, 1, 1)
        elif direction == "left":
            if hasattr(container, "scroll_x"):
                container.scroll_x = 0
            return
        elif direction == "right":
            real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
            if real_positions:
                max_x = max(x for x, r in real_positions.values())
                right_x = max_x + NODE_W + 4
                if hasattr(container, "scroll_x") and hasattr(container, "size"):
                    container.scroll_x = max(0, right_x - container.size.width)
            return
        else:
            real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
            max_row = max(r for x, r in real_positions.values()) if real_positions else 0
            y = (max_row + 1) * (NODE_H + V_GAP) + NODE_H
            if self._hidden_label_ids:
                y += 2 + len(self._hidden_label_ids)
            region = Region(0, y, 1, 1)
        container.scroll_to_region(region, animate=False, force=True)

    def _scroll_selected_into_view(self) -> None:
        if not self._ordered_ids:
            return
        pr_id = self._ordered_ids[self.selected_index]
        if pr_id not in self._node_positions:
            return

        from textual.geometry import Region, Spacing

        if self._jump_plan_scroll:
            self._jump_plan_scroll = False
            self._scroll_plan_label_to_top(pr_id)
            return

        if pr_id.startswith("_hidden:"):
            real_positions = {k: v for k, v in self._node_positions.items() if not k.startswith("_hidden:")}
            if real_positions:
                max_row = max(r for x, r in real_positions.values()) + 1
                grid_h = max_row * (NODE_H + V_GAP) + 4
            else:
                grid_h = 0
            label_index = self._hidden_label_ids.index(pr_id) if pr_id in self._hidden_label_ids else 0
            y = grid_h + 1 + label_index
            node_region = Region(0, y, 60, 1)
        else:
            x, row = self._node_positions[pr_id]
            y = row * (NODE_H + V_GAP) + 1
            bottom_padding = 4
            node_region = Region(x, y, NODE_W, NODE_H + V_GAP + bottom_padding)

        container = self.parent if self.parent else self
        container.scroll_to_region(
            node_region, animate=False, force=True,
            spacing=Spacing(top=1, bottom=2, left=0, right=0),
        )

        if not pr_id.startswith("_hidden:") and hasattr(container, "scroll_x"):
            vw = container.size.width if hasattr(container, "size") else 0
            if vw > 0:
                x, _ = self._node_positions[pr_id]
                node_right = x + NODE_W + 2
                if x < container.scroll_x:
                    container.scroll_x = max(0, x - 2)
                elif node_right > container.scroll_x + vw:
                    container.scroll_x = node_right - vw

    def _scroll_plan_label_to_top(self, pr_id: str) -> None:
        from textual.geometry import Region
        pr_map = {pr["id"]: pr for pr in self._prs}
        pr = pr_map.get(pr_id)
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

    # ------------------------------------------------------------------
    # Plan jump helpers
    # ------------------------------------------------------------------

    def _jump_plan_top(self) -> int | None:
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
        for i, pid in enumerate(self._ordered_ids):
            if pid.startswith("_hidden:"):
                continue
            pr = pr_map.get(pid)
            if pr and (pr.get("plan") or "_standalone") == current_plan:
                return i
        return None

    def _jump_plan_bottom(self) -> int | None:
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
        if not self._plan_group_order or len(self._plan_group_order) < 2:
            return None

        current_id = self._ordered_ids[self.selected_index]
        if current_id.startswith("_hidden:"):
            current_plan = current_id[len("_hidden:"):]
        else:
            pr_map = {pr["id"]: pr for pr in self._prs}
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
        pr_map = {pr["id"]: pr for pr in self._prs}
        for i, pid in enumerate(self._ordered_ids):
            if pid.startswith("_hidden:"):
                continue
            pr = pr_map.get(pid)
            if pr and (pr.get("plan") or "_standalone") == target_plan:
                return i
        return None
