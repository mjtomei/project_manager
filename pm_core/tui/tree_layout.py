"""Tree layout algorithm for the PR dependency graph.

Uses Sugiyama-style layered graph drawing to compute node positions with
minimal edge crossings and maximal horizontal (straight) edges:

1. **Layer assignment** (dependency depth) — via ``graph.compute_layers``
2. **Crossing minimization** — barycenter heuristic with alternating sweeps
3. **Coordinate assignment** — greedy row placement maximizing straight edges

The TechTree widget calls :func:`compute_tree_layout` and uses the resulting
:class:`TreeLayout` for rendering and navigation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pm_core import graph as graph_mod


@dataclass
class TreeLayout:
    """Result of a layout computation."""

    ordered_ids: list[str] = field(default_factory=list)
    node_positions: dict[str, tuple[int, int]] = field(default_factory=dict)
    plan_label_rows: dict[str, int] = field(default_factory=dict)
    hidden_plan_label_rows: dict[str, int] = field(default_factory=dict)
    hidden_label_ids: list[str] = field(default_factory=list)
    plan_group_order: list[str] = field(default_factory=list)


def compute_tree_layout(
    all_prs: list[dict],
    *,
    hidden_plans: set[str] | None = None,
    status_filter: str | None = None,
    hide_merged: bool = False,
    hide_closed: bool = True,
) -> TreeLayout:
    """Compute the full tree layout for a set of PRs.

    Args:
        all_prs: Complete (unfiltered) list of PR dicts.
        hidden_plans: Plan IDs whose PRs should be collapsed.
        status_filter: If set, show only PRs with this status.
        hide_merged: If True (and no status_filter), hide merged PRs.
        hide_closed: If True (and no status_filter), hide closed PRs.

    Returns:
        A :class:`TreeLayout` with positions and navigation order.
    """
    hidden_plans = hidden_plans or set()
    layout = TreeLayout()

    prs = list(all_prs)
    if not prs:
        return layout

    # Filter out hidden plan PRs
    if hidden_plans:
        prs = [p for p in prs if (p.get("plan") or "_standalone") not in hidden_plans]
        if not prs:
            return layout

    # Filter by status
    if status_filter:
        prs = [p for p in prs if p.get("status") == status_filter]
    else:
        if hide_merged:
            prs = [p for p in prs if p.get("status") != "merged"]
        if hide_closed:
            prs = [p for p in prs if p.get("status") != "closed"]

    if not prs:
        return layout

    pr_map = {pr["id"]: pr for pr in prs}
    layers = graph_mod.compute_layers(prs)

    # Build adjacency for layout (only visible nodes)
    pr_ids = set(pr_map.keys())
    parents_of: dict[str, list[str]] = {}
    children_of: dict[str, list[str]] = {}
    for pr in prs:
        node = pr["id"]
        parents_of[node] = [d for d in (pr.get("depends_on") or []) if d in pr_ids]
        children_of.setdefault(node, [])
        for d in parents_of[node]:
            children_of.setdefault(d, [])
            children_of[d].append(node)

    # Sugiyama phases
    layer_orders = _minimize_crossings(layers, parents_of, children_of,
                                       pr_map=pr_map)
    row_assignments = _assign_coordinates(layer_orders, parents_of, children_of)

    # Normalize rows so minimum is 0
    if row_assignments:
        min_row = min(row_assignments.values())
        if min_row != 0:
            for pr_id in row_assignments:
                row_assignments[pr_id] -= min_row

    # Group by plan and adjust rows
    plan_label_rows, plan_group_order = _apply_plan_grouping(
        prs, row_assignments
    )
    layout.plan_label_rows = plan_label_rows
    layout.plan_group_order = plan_group_order

    # Build final ordered_ids and node_positions from layers
    for col, layer_order in enumerate(layer_orders):
        for pr_id in sorted(layer_order, key=lambda x: row_assignments.get(x, 0)):
            layout.node_positions[pr_id] = (col, row_assignments[pr_id])
            layout.ordered_ids.append(pr_id)

    # Add hidden plan labels as navigable rows below visible content
    if hidden_plans:
        max_row = max(row_assignments.values()) if row_assignments else -1
        hidden_row = max_row + 2  # gap after visible content
        for plan_id in sorted(hidden_plans):
            virtual_id = f"_hidden:{plan_id}"
            layout.hidden_plan_label_rows[plan_id] = hidden_row
            layout.node_positions[virtual_id] = (0, hidden_row)
            layout.ordered_ids.append(virtual_id)
            layout.hidden_label_ids.append(virtual_id)
            hidden_row += 1

    return layout


# ---------------------------------------------------------------------------
# Sugiyama Phase 2: Crossing Minimization
# ---------------------------------------------------------------------------


def _activity_sort_key(pr_id: str, pr_map: dict[str, dict]) -> tuple:
    """Sort key for PRs: active statuses first, then by most recent activity.

    Order: in_progress > in_review > pending > merged > closed.
    Within each status group, sort by most recent timestamp (descending).
    """
    pr = pr_map.get(pr_id)
    if not pr:
        return (5, "", pr_id)

    status_priority = {
        "in_progress": 0,
        "in_review": 1,
        "pending": 2,
        "merged": 3,
        "closed": 4,
    }
    priority = status_priority.get(pr.get("status", "pending"), 5)

    # Use most recent timestamp for ordering within status group
    ts = (pr.get("merged_at") or pr.get("reviewed_at")
          or pr.get("started_at") or "")

    # Negate for descending order (most recent first) — ISO timestamps
    # sort lexicographically, so inverting gives descending order
    return (priority, "" if not ts else ts, pr_id)


def _minimize_crossings(
    layers: list[list[str]],
    parents_of: dict[str, list[str]],
    children_of: dict[str, list[str]],
    *,
    num_sweeps: int = 4,
    pr_map: dict[str, dict] | None = None,
) -> list[list[str]]:
    """Reorder nodes within layers to minimize edge crossings.

    Uses the barycenter heuristic with alternating forward/backward sweeps.
    Each forward sweep orders nodes by the average position of their parents;
    each backward sweep orders by the average position of their children.

    After each sweep, the crossing count is evaluated and the best ordering
    seen so far is retained.  This prevents oscillation where a backward
    sweep undoes a good forward ordering (or vice versa).
    """
    # Initial ordering: sort by activity/status when PR data is available,
    # otherwise fall back to alphabetical.  This gives the crossing
    # minimization a better starting point and ensures active PRs appear
    # at the top within each layer.
    if pr_map:
        layer_orders = [sorted(layer, key=lambda pid: _activity_sort_key(pid, pr_map))
                        for layer in layers]
    else:
        layer_orders = [sorted(layer) for layer in layers]
    if len(layer_orders) <= 1:
        return layer_orders

    # Position lookup: node → ordinal position in its layer
    pos: dict[str, float] = {}
    for layer in layer_orders:
        for i, node in enumerate(layer):
            pos[node] = float(i)

    # Track the best ordering seen across all sweeps
    best_crossings = _count_layer_crossings(layer_orders, parents_of)
    best_orders: list[list[str]] = [list(layer) for layer in layer_orders]

    for sweep in range(num_sweeps):
        if sweep % 2 == 0:
            # Forward pass: order each layer by parent positions
            for col in range(1, len(layer_orders)):
                _reorder_by_barycenter(layer_orders[col], pos, parents_of)
                for i, node in enumerate(layer_orders[col]):
                    pos[node] = float(i)
        else:
            # Backward pass: order each layer by child positions
            for col in range(len(layer_orders) - 2, -1, -1):
                _reorder_by_barycenter(layer_orders[col], pos, children_of)
                for i, node in enumerate(layer_orders[col]):
                    pos[node] = float(i)

        crossings = _count_layer_crossings(layer_orders, parents_of)
        if crossings < best_crossings:
            best_crossings = crossings
            best_orders = [list(layer) for layer in layer_orders]
            if crossings == 0:
                break  # can't do better

    # Restore the best ordering and rebuild positions
    if best_crossings < _count_layer_crossings(layer_orders, parents_of):
        layer_orders = best_orders

    return layer_orders


def _reorder_by_barycenter(
    layer: list[str],
    pos: dict[str, float],
    neighbors_of: dict[str, list[str]],
) -> None:
    """Sort *layer* in place by average position of connected neighbors."""

    def key(node: str) -> tuple[float, str]:
        neighbors = neighbors_of.get(node, [])
        nbr_pos = [pos[n] for n in neighbors if n in pos]
        bary = sum(nbr_pos) / len(nbr_pos) if nbr_pos else pos.get(node, 0.0)
        return (bary, node)  # tie-break by ID for determinism

    layer.sort(key=key)


def _count_layer_crossings(
    layer_orders: list[list[str]],
    parents_of: dict[str, list[str]],
) -> int:
    """Count edge crossings implied by the current layer orderings.

    Two edges (u→v) and (u'→v') between adjacent layers cross when the
    ordinal positions of their endpoints are inverted.
    """
    # Build ordinal position lookup
    ordinal: dict[str, int] = {}
    for layer in layer_orders:
        for i, node in enumerate(layer):
            ordinal[node] = i

    crossings = 0
    for col in range(1, len(layer_orders)):
        # Collect edges into this layer as (parent_ordinal, child_ordinal)
        edges: list[tuple[int, int]] = []
        for node in layer_orders[col]:
            for parent in parents_of.get(node, []):
                if parent in ordinal:
                    edges.append((ordinal[parent], ordinal[node]))
        # Count inversions
        for i in range(len(edges)):
            for j in range(i + 1, len(edges)):
                if (edges[i][0] - edges[j][0]) * (edges[i][1] - edges[j][1]) < 0:
                    crossings += 1

    return crossings


# ---------------------------------------------------------------------------
# Sugiyama Phase 3: Coordinate Assignment
# ---------------------------------------------------------------------------


def _assign_coordinates(
    layer_orders: list[list[str]],
    parents_of: dict[str, list[str]],
    children_of: dict[str, list[str]],
) -> dict[str, int]:
    """Assign row coordinates to maximize horizontal (straight) edges.

    Single-dependency nodes try to share their parent's row.  Multi-dependency
    nodes target the mean of their parents' rows.  Within-layer ordering from
    crossing minimization is preserved to maintain the crossing reduction.
    """
    row_assignments: dict[str, int] = {}
    if not layer_orders:
        return row_assignments

    # Layer 0: stack roots, leaving gaps for parents with multiple
    # single-dependency children (so those children can fan out adjacently).
    current_row = 0
    for node in layer_orders[0]:
        row_assignments[node] = current_row
        single_children = sum(
            1
            for c in children_of.get(node, [])
            if len(parents_of.get(c, [])) == 1
        )
        current_row += max(1, single_children)

    # Subsequent layers
    for col in range(1, len(layer_orders)):
        order = layer_orders[col]
        used_rows: set[int] = set()
        prev_row: int | None = None

        for node in order:
            parent_rows = sorted(
                row_assignments[p]
                for p in parents_of.get(node, [])
                if p in row_assignments
            )

            if len(parent_rows) == 1:
                ideal = parent_rows[0]
            elif parent_rows:
                ideal = round(sum(parent_rows) / len(parent_rows))
            else:
                ideal = (prev_row + 1) if prev_row is not None else 0

            # Maintain within-layer ordering (preserves crossing minimization)
            if prev_row is not None:
                ideal = max(ideal, prev_row + 1)

            # Avoid collisions within this layer
            while ideal in used_rows:
                ideal += 1

            row_assignments[node] = ideal
            used_rows.add(ideal)
            prev_row = ideal

    return row_assignments


# ---------------------------------------------------------------------------
# Plan Grouping (unchanged from original)
# ---------------------------------------------------------------------------


def _apply_plan_grouping(
    prs: list[dict],
    row_assignments: dict[str, int],
) -> tuple[dict[str, int], list[str]]:
    """Insert plan-label rows and reorder when 2+ plan groups exist.

    Modifies *row_assignments* in place and returns
    ``(plan_label_rows, plan_group_order)``.
    """
    plan_label_rows: dict[str, int] = {}
    plan_group_order: list[str] = []

    pr_map = {pr["id"]: pr for pr in prs}
    plan_groups: dict[str, list[str]] = {}
    for pr_id in row_assignments:
        pr = pr_map.get(pr_id)
        plan_id = (pr.get("plan") or "_standalone") if pr else "_standalone"
        if plan_id not in plan_groups:
            plan_groups[plan_id] = []
        plan_groups[plan_id].append(pr_id)

    if len(plan_groups) < 2:
        return plan_label_rows, plan_group_order

    # Named plans sorted by ID, standalone last
    group_order = sorted(k for k in plan_groups if k != "_standalone")
    if "_standalone" in plan_groups:
        group_order.append("_standalone")
    plan_group_order = list(group_order)

    current_row = 0
    for plan_id in group_order:
        group_pr_ids = plan_groups[plan_id]
        plan_label_rows[plan_id] = current_row
        current_row += 1  # label takes one row

        group_rows = sorted(set(row_assignments[pid] for pid in group_pr_ids))
        row_remap = {old_row: current_row + i for i, old_row in enumerate(group_rows)}
        for pid in group_pr_ids:
            row_assignments[pid] = row_remap[row_assignments[pid]]
        current_row += len(group_rows) + 1  # +1 gap between groups

    return plan_label_rows, plan_group_order
