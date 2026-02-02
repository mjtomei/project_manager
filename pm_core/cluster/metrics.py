"""Four similarity metrics for code chunk clustering."""

import subprocess
from collections import defaultdict
from pathlib import Path

from pm_core.cluster.chunks import Chunk


# ---------------------------------------------------------------------------
# 1. Structural proximity
# ---------------------------------------------------------------------------

def structural_proximity(a: Chunk, b: Chunk) -> float:
    """Score based on shared path components. Same file → 1.0."""
    a_parts = list(a.path.parts)
    b_parts = list(b.path.parts)
    common = 0
    for x, y in zip(a_parts, b_parts):
        if x == y:
            common += 1
        else:
            break
    max_len = max(len(a_parts), len(b_parts))
    if max_len == 0:
        return 0.0
    return common / max_len


# ---------------------------------------------------------------------------
# 2. Semantic similarity (Jaccard on filtered tokens)
# ---------------------------------------------------------------------------

def _build_stopwords(chunks: list[Chunk], threshold: float = 0.4) -> set[str]:
    """Tokens appearing in >threshold fraction of chunks are stopwords."""
    n = len(chunks)
    if n == 0:
        return set()
    counts: dict[str, int] = defaultdict(int)
    for c in chunks:
        for t in c.tokens:
            counts[t] += 1
    cutoff = threshold * n
    return {t for t, cnt in counts.items() if cnt > cutoff}


def semantic_similarity(a: Chunk, b: Chunk, stopwords: set[str]) -> float:
    """Jaccard similarity on token sets after removing stopwords."""
    ta = a.tokens - stopwords
    tb = b.tokens - stopwords
    if not ta and not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    if not union:
        return 0.0
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# 3. Co-change history
# ---------------------------------------------------------------------------

def build_cochange_matrix(repo_root: Path, max_commits: int = 500
                          ) -> dict[tuple[str, str], int]:
    """Count how often file pairs are changed in the same commit."""
    matrix: dict[tuple[str, str], int] = defaultdict(int)
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={max_commits}",
             "--name-only", "--pretty=format:---"],
            cwd=repo_root, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return matrix
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return matrix

    commits = result.stdout.split('---')
    for commit_block in commits:
        files = [f.strip() for f in commit_block.strip().split('\n') if f.strip()]
        if len(files) > 50:
            continue
        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                pair = tuple(sorted((files[i], files[j])))
                matrix[pair] += 1

    return matrix


def cochange_score(a: Chunk, b: Chunk, matrix: dict[tuple[str, str], int],
                   max_count: int) -> float:
    """Co-change score between two chunks (file-level)."""
    if max_count <= 0:
        return 0.0
    fa = str(a.path) if a.kind != "directory" else ""
    fb = str(b.path) if b.kind != "directory" else ""
    # For function/class chunks, use their file path
    if a.kind in ("function", "class"):
        fa = str(a.path)
    if b.kind in ("function", "class"):
        fb = str(b.path)
    if not fa or not fb or fa == fb:
        return 0.0
    pair = tuple(sorted((fa, fb)))
    count = matrix.get(pair, 0)
    return min(count / max_count, 1.0)


# ---------------------------------------------------------------------------
# 4. Call-graph proximity
# ---------------------------------------------------------------------------

def build_call_graph(chunks: list[Chunk]) -> dict[str, set[str]]:
    """Build directed adjacency list from chunk call targets.

    Resolves calls to chunk IDs by matching call names against chunk names.
    """
    # Build name -> chunk IDs index
    name_to_ids: dict[str, list[str]] = defaultdict(list)
    for c in chunks:
        if c.kind in ("function", "class"):
            name_to_ids[c.name].append(c.id)

    # Build file-local name index for self.method resolution
    file_names: dict[str, dict[str, str]] = defaultdict(dict)
    for c in chunks:
        if c.kind in ("function", "class"):
            file_names[str(c.path)][c.name] = c.id

    adjacency: dict[str, set[str]] = defaultdict(set)

    for chunk in chunks:
        if not chunk.calls:
            continue
        for call_name in chunk.calls:
            # Try file-local resolution first
            local_id = file_names.get(str(chunk.path), {}).get(call_name)
            if local_id and local_id != chunk.id:
                adjacency[chunk.id].add(local_id)
                continue
            # Try global resolution
            targets = name_to_ids.get(call_name, [])
            for tid in targets:
                if tid != chunk.id:
                    adjacency[chunk.id].add(tid)

    return dict(adjacency)


def _bfs_distances(start: str, adjacency: dict[str, set[str]],
                   max_depth: int = 5) -> dict[str, int]:
    """BFS from start, returning shortest distances up to max_depth."""
    distances: dict[str, int] = {}
    frontier = [start]
    depth = 0
    visited = {start}
    while frontier and depth < max_depth:
        depth += 1
        next_frontier = []
        for node in frontier:
            for neighbor in adjacency.get(node, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    distances[neighbor] = depth
                    next_frontier.append(neighbor)
        frontier = next_frontier
    return distances


def compute_call_distances(chunks: list[Chunk],
                           adjacency: dict[str, set[str]]
                           ) -> dict[tuple[str, str], int]:
    """Compute BFS shortest-path distances between all reachable chunk pairs."""
    distances: dict[tuple[str, str], int] = {}
    # Only BFS from chunks with outgoing calls
    sources = {c.id for c in chunks if c.calls}
    for src in sources:
        if src not in adjacency:
            continue
        dists = _bfs_distances(src, adjacency)
        for target, dist in dists.items():
            pair = (src, target)
            if pair not in distances or dist < distances[pair]:
                distances[pair] = dist
    return distances


def call_graph_score(a_id: str, b_id: str,
                     distances: dict[tuple[str, str], int]) -> float:
    """Score based on call-graph distance. Direct call → 0.5, unreachable → 0.0."""
    d = distances.get((a_id, b_id))
    d2 = distances.get((b_id, a_id))
    if d is None and d2 is None:
        return 0.0
    min_d = min(x for x in (d, d2) if x is not None)
    return 1.0 / (1 + min_d)


# ---------------------------------------------------------------------------
# Edge computation
# ---------------------------------------------------------------------------

def compute_edges(chunks: list[Chunk],
                  weights: dict[str, float] | None = None,
                  repo_root: Path | None = None,
                  max_commits: int = 500,
                  min_weight: float = 0.05) -> list:
    """Compute weighted edges between chunks.

    Args:
        chunks: List of code chunks.
        weights: Metric weights dict with keys: structural, semantic, cochange, callgraph.
        repo_root: Repository root for git operations. If None, co-change is skipped.
        max_commits: Max commits to scan for co-change.
        min_weight: Minimum combined weight to keep an edge.

    Returns:
        List of Edge objects.
    """
    from pm_core.cluster.cluster_graph import Edge

    if weights is None:
        weights = {"structural": 0.2, "semantic": 0.3, "cochange": 0.2, "callgraph": 0.3}

    chunk_map = {c.id: c for c in chunks}
    # Filter to function/class/file chunks for pairwise comparison (skip directories)
    scored_chunks = [c for c in chunks if c.kind in ("function", "class", "file")]

    # Pre-compute stopwords
    stopwords = _build_stopwords(scored_chunks)

    # Pre-compute co-change matrix
    cochange_matrix: dict[tuple[str, str], int] = {}
    max_cochange = 0
    if repo_root and weights.get("cochange", 0) > 0:
        cochange_matrix = build_cochange_matrix(repo_root, max_commits)
        if cochange_matrix:
            max_cochange = max(cochange_matrix.values())

    # Pre-compute call graph
    call_distances: dict[tuple[str, str], int] = {}
    if weights.get("callgraph", 0) > 0:
        adjacency = build_call_graph(chunks)
        call_distances = compute_call_distances(chunks, adjacency)

    # Build inverted index for token overlap
    token_to_chunks: dict[str, set[str]] = defaultdict(set)
    for c in scored_chunks:
        for t in (c.tokens - stopwords):
            token_to_chunks[t].add(c.id)

    # Build directory adjacency index
    dir_to_chunks: dict[str, set[str]] = defaultdict(set)
    for c in scored_chunks:
        dir_to_chunks[str(c.path.parent)].add(c.id)

    # Collect candidate pairs
    candidate_pairs: set[tuple[str, str]] = set()

    # Pairs sharing tokens
    for chunk_ids in token_to_chunks.values():
        ids = list(chunk_ids)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                candidate_pairs.add(tuple(sorted((ids[i], ids[j]))))

    # Pairs in same or adjacent directory
    dirs = list(dir_to_chunks.keys())
    for i, d1 in enumerate(dirs):
        for c1 in dir_to_chunks[d1]:
            for c2 in dir_to_chunks[d1]:
                if c1 < c2:
                    candidate_pairs.add((c1, c2))
        # Adjacent = parent/child
        for j in range(i + 1, len(dirs)):
            d2 = dirs[j]
            if d1.startswith(d2 + '/') or d2.startswith(d1 + '/') or d1 == d2:
                for c1 in dir_to_chunks[d1]:
                    for c2 in dir_to_chunks[d2]:
                        if c1 != c2:
                            candidate_pairs.add(tuple(sorted((c1, c2))))

    # Pairs connected by call graph
    for (a_id, b_id) in call_distances:
        pair = tuple(sorted((a_id, b_id)))
        candidate_pairs.add(pair)

    # Compute edges
    edges = []
    for a_id, b_id in candidate_pairs:
        a = chunk_map.get(a_id)
        b = chunk_map.get(b_id)
        if not a or not b:
            continue

        breakdown: dict[str, float] = {}
        total = 0.0

        if weights.get("structural", 0) > 0:
            s = structural_proximity(a, b)
            breakdown["structural"] = s
            total += weights["structural"] * s

        if weights.get("semantic", 0) > 0:
            s = semantic_similarity(a, b, stopwords)
            breakdown["semantic"] = s
            total += weights["semantic"] * s

        if weights.get("cochange", 0) > 0:
            s = cochange_score(a, b, cochange_matrix, max_cochange)
            breakdown["cochange"] = s
            total += weights["cochange"] * s

        if weights.get("callgraph", 0) > 0:
            s = call_graph_score(a_id, b_id, call_distances)
            breakdown["callgraph"] = s
            total += weights["callgraph"] * s

        if total >= min_weight:
            edges.append(Edge(a=a_id, b=b_id, weight=total, breakdown=breakdown))

    return edges
