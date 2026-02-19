"""Tree layout algorithm for the PR dependency graph.

Computes node positions (column, row), plan group ordering, and hidden
label placement.  The TechTree widget calls :func:`compute_tree_layout`
and uses the resulting :class:`TreeLayout` for rendering and navigation.
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

    row_assignments = _assign_rows(prs, pr_map, layers)

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
    for col, layer in enumerate(layers):
        for pr_id in sorted(layer, key=lambda x: row_assignments.get(x, 0)):
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


def _assign_rows(
    prs: list[dict],
    pr_map: dict[str, dict],
    layers: list[list[str]],
) -> dict[str, int]:
    """Assign a row to each PR node.

    Strategy: single-dependency edges should be horizontal when possible.
    Nodes with a single parent share the parent's row (first child) or get
    adjacent rows (subsequent children).
    """
    # Build reverse map: parent -> list of single-dep children
    single_dep_children: dict[str, list[str]] = {}
    for pr in prs:
        deps = pr.get("depends_on") or []
        if len(deps) == 1:
            parent = deps[0]
            if parent not in single_dep_children:
                single_dep_children[parent] = []
            single_dep_children[parent].append(pr["id"])

    row_assignments: dict[str, int] = {}

    # First column: stack, leaving gaps for multi-child parents
    if layers:
        current_row = 0
        for pr_id in sorted(layers[0]):
            row_assignments[pr_id] = current_row
            children = single_dep_children.get(pr_id, [])
            if len(children) > 1:
                current_row += len(children)
            else:
                current_row += 1

    # Subsequent columns
    for col in range(1, len(layers)):
        layer = layers[col]
        _assign_layer_rows(layer, pr_map, row_assignments, single_dep_children)

    return row_assignments


def _assign_layer_rows(
    layer: list[str],
    pr_map: dict[str, dict],
    row_assignments: dict[str, int],
    single_dep_children: dict[str, list[str]],
) -> None:
    """Assign rows for all nodes in a single layer (modifies *row_assignments*)."""
    # Categorize nodes
    single_dep: list[tuple[str, str, int]] = []  # (pr_id, parent_id, parent_row)
    multi_dep: list[tuple[str, float]] = []       # (pr_id, avg_row)
    no_dep: list[str] = []

    for pr_id in layer:
        pr = pr_map.get(pr_id)
        deps = (pr.get("depends_on") or []) if pr else []
        dep_rows = [(d, row_assignments[d]) for d in deps if d in row_assignments]
        if len(dep_rows) == 1:
            single_dep.append((pr_id, dep_rows[0][0], dep_rows[0][1]))
        elif dep_rows:
            avg = sum(r for _, r in dep_rows) / len(dep_rows)
            multi_dep.append((pr_id, avg))
        else:
            no_dep.append(pr_id)

    used_rows: set[int] = set()

    # Group single-dep nodes by parent
    by_parent: dict[str, list[tuple[str, int]]] = {}
    for pr_id, parent_id, parent_row in single_dep:
        if parent_id not in by_parent:
            by_parent[parent_id] = []
        by_parent[parent_id].append((pr_id, parent_row))

    # Assign single-dep: first child gets parent's row, extras get adjacent
    for parent_id, children in by_parent.items():
        children.sort(key=lambda x: x[0])
        base_row = children[0][1]
        for i, (pr_id, _) in enumerate(children):
            target_row = base_row + i
            row_assignments[pr_id] = target_row
            used_rows.add(target_row)

    # Assign multi-dep nodes
    multi_dep.sort(key=lambda x: (x[1], x[0]))
    for pr_id, pref in multi_dep:
        target = round(pref)
        while target in used_rows:
            target += 1
        row_assignments[pr_id] = target
        used_rows.add(target)

    # Assign no-dep nodes
    for pr_id in sorted(no_dep):
        target = 0
        while target in used_rows:
            target += 1
        row_assignments[pr_id] = target
        used_rows.add(target)


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
