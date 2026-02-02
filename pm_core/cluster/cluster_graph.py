"""Weighted graph and agglomerative clustering."""

import heapq
from collections import defaultdict
from dataclasses import dataclass, field

from pm_core.cluster.chunks import Chunk


@dataclass
class Edge:
    a: str
    b: str
    weight: float
    breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class Cluster:
    id: str
    chunk_ids: set[str]
    name: str = ""
    description: str = ""


class _UnionFind:
    """Union-find for cluster membership tracking."""

    def __init__(self):
        self.parent: dict[str, str] = {}
        self.rank: dict[str, int] = {}

    def make_set(self, x: str):
        self.parent[x] = x
        self.rank[x] = 0

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: str, y: str) -> str:
        """Merge sets containing x and y. Returns new root."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return rx
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        return rx


def name_cluster(cluster: Cluster, chunks: dict[str, Chunk]) -> str:
    """Generate a descriptive name for a cluster.

    Uses common directory prefix + top 3 frequent tokens.
    """
    paths = []
    token_counts: dict[str, int] = defaultdict(int)
    for cid in cluster.chunk_ids:
        c = chunks.get(cid)
        if not c:
            continue
        paths.append(str(c.path))
        for t in c.tokens:
            token_counts[t] += 1

    # Common directory prefix
    if paths:
        prefix = _common_prefix(paths)
    else:
        prefix = ""

    # Top tokens (skip very short ones)
    top = sorted(
        ((t, cnt) for t, cnt in token_counts.items() if len(t) > 2),
        key=lambda x: -x[1],
    )[:3]
    token_str = ", ".join(t for t, _ in top)

    if prefix and token_str:
        return f"{prefix} ({token_str})"
    return prefix or token_str or f"cluster-{cluster.id}"


def _common_prefix(paths: list[str]) -> str:
    """Find common directory prefix of paths."""
    if not paths:
        return ""
    parts_list = [p.split('/') for p in paths]
    prefix = []
    for components in zip(*parts_list):
        if len(set(components)) == 1:
            prefix.append(components[0])
        else:
            break
    return '/'.join(prefix)


def agglomerative_cluster(chunks: list[Chunk],
                          edges: list[Edge],
                          threshold: float = 0.15) -> list[Cluster]:
    """Agglomerative clustering with average-linkage.

    Args:
        chunks: All code chunks.
        edges: Weighted edges between chunks.
        threshold: Minimum edge weight to merge clusters.

    Returns:
        List of Cluster objects.
    """
    chunk_map = {c.id: c for c in chunks}
    # Only cluster non-directory chunks
    active_ids = {c.id for c in chunks if c.kind in ("function", "class", "file")}

    if not active_ids:
        return []

    uf = _UnionFind()
    for cid in active_ids:
        uf.make_set(cid)

    # Cluster membership: root -> set of chunk IDs
    members: dict[str, set[str]] = {cid: {cid} for cid in active_ids}

    # Edge weight lookup for average-linkage
    edge_weights: dict[tuple[str, str], float] = {}
    for e in edges:
        if e.a in active_ids and e.b in active_ids:
            pair = tuple(sorted((e.a, e.b)))
            edge_weights[pair] = e.weight

    # Max-heap (negate for heapq)
    heap: list[tuple[float, str, str]] = []
    for (a, b), w in edge_weights.items():
        heapq.heappush(heap, (-w, a, b))

    cluster_counter = 0

    while heap:
        neg_w, a, b = heapq.heappop(heap)
        w = -neg_w

        if w < threshold:
            break

        ra = uf.find(a)
        rb = uf.find(b)
        if ra == rb:
            continue  # Already in same cluster

        # Verify weight is still current (average-linkage)
        actual_w = _average_linkage(members[ra], members[rb], edge_weights)
        if actual_w < threshold:
            continue
        # If actual weight differs significantly from heap weight, re-push
        if abs(actual_w - w) > 0.01:
            heapq.heappush(heap, (-actual_w, a, b))
            continue

        # Merge
        new_root = uf.union(ra, rb)
        merged = members[ra] | members[rb]
        if new_root == ra:
            del members[rb]
        else:
            del members[ra]
        members[new_root] = merged

        # Push edges to other clusters
        for other_root, other_members in members.items():
            if other_root == new_root:
                continue
            avg = _average_linkage(merged, other_members, edge_weights)
            if avg >= threshold:
                heapq.heappush(heap, (-avg, new_root, other_root))

    # Build final clusters
    clusters = []
    for root, chunk_ids in members.items():
        cluster_counter += 1
        cluster = Cluster(
            id=str(cluster_counter),
            chunk_ids=chunk_ids,
        )
        cluster.name = name_cluster(cluster, chunk_map)
        clusters.append(cluster)

    # Sort by size descending
    clusters.sort(key=lambda c: -len(c.chunk_ids))
    return clusters


def _average_linkage(group_a: set[str], group_b: set[str],
                     edge_weights: dict[tuple[str, str], float]) -> float:
    """Average pairwise edge weight between two groups."""
    total = 0.0
    count = 0
    for a in group_a:
        for b in group_b:
            pair = tuple(sorted((a, b)))
            total += edge_weights.get(pair, 0.0)
            count += 1
    if count == 0:
        return 0.0
    return total / count
