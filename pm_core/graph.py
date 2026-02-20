"""Dependency graph logic, topological sort, ready detection."""

from collections import defaultdict, deque
from typing import Optional


def build_adjacency(prs: list[dict]) -> dict[str, list[str]]:
    """Build adjacency list: pr_id -> list of PRs that depend on it."""
    adj = defaultdict(list)
    for pr in prs:
        for dep in pr.get("depends_on") or []:
            adj[dep].append(pr["id"])
    return dict(adj)


def topological_sort(prs: list[dict]) -> list[str]:
    """Return PR ids in topological order (dependencies first)."""
    in_degree = {}
    adj = defaultdict(list)
    pr_ids = {pr["id"] for pr in prs}

    for pr_id in pr_ids:
        in_degree[pr_id] = 0

    for pr in prs:
        for dep in pr.get("depends_on") or []:
            if dep in pr_ids:
                adj[dep].append(pr["id"])
                in_degree[pr["id"]] = in_degree.get(pr["id"], 0) + 1

    queue = deque(pid for pid, deg in in_degree.items() if deg == 0)
    result = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for child in adj[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    return result


def ready_prs(prs: list[dict]) -> list[dict]:
    """Return PRs whose dependencies are all merged and status is pending."""
    merged = {pr["id"] for pr in prs if pr.get("status") == "merged"}
    result = []
    for pr in prs:
        if pr.get("status") != "pending":
            continue
        deps = pr.get("depends_on") or []
        if all(d in merged for d in deps):
            result.append(pr)
    return result


def blocked_prs(prs: list[dict]) -> list[dict]:
    """Return PRs that are blocked (have unmerged dependencies)."""
    merged = {pr["id"] for pr in prs if pr.get("status") == "merged"}
    result = []
    for pr in prs:
        deps = pr.get("depends_on") or []
        if deps and not all(d in merged for d in deps):
            if pr.get("status") in ("pending", "blocked"):
                result.append(pr)
    return result


def compute_layers(prs: list[dict]) -> list[list[str]]:
    """Group PRs into layers by dependency depth (for graph rendering).

    Layer 0 = no dependencies, layer 1 = depends only on layer 0, etc.
    """
    pr_map = {pr["id"]: pr for pr in prs}
    layers_map: dict[str, int] = {}

    def get_layer(pr_id: str) -> int:
        if pr_id in layers_map:
            return layers_map[pr_id]
        pr = pr_map.get(pr_id)
        if not pr:
            return -1
        deps = pr.get("depends_on") or []
        visible_dep_layers = [get_layer(d) for d in deps if d in pr_map]
        if not visible_dep_layers:
            layers_map[pr_id] = 0
            return 0
        layer = max(visible_dep_layers) + 1
        layers_map[pr_id] = layer
        return layer

    for pr in prs:
        get_layer(pr["id"])

    max_layer = max(layers_map.values()) if layers_map else 0
    layers = [[] for _ in range(max_layer + 1)]
    for pr_id, layer in layers_map.items():
        layers[layer].append(pr_id)
    return layers


def render_static_graph(prs: list[dict]) -> str:
    """Render a simple text-based graph for terminal output."""
    if not prs:
        return "No PRs defined."

    pr_map = {pr["id"]: pr for pr in prs}
    layers = compute_layers(prs)
    status_icons = {
        "pending": "⏳",
        "in_progress": "🔨",
        "in_review": "👀",
        "merged": "✅",
        "blocked": "🚫",
    }

    lines = []
    for layer_idx, layer in enumerate(layers):
        for pr_id in sorted(layer):
            pr = pr_map[pr_id]
            icon = status_icons.get(pr.get("status", "pending"), "?")
            deps = pr.get("depends_on") or []
            dep_str = f" <- [{', '.join(deps)}]" if deps else ""
            machine = pr.get("agent_machine")
            machine_str = f" ({machine})" if machine else ""
            lines.append(f"  {icon} {pr_id}: {pr.get('title', '???')}{dep_str}{machine_str}")
        if layer_idx < len(layers) - 1:
            lines.append("    │")
            lines.append("    ▼")
    return "\n".join(lines)
