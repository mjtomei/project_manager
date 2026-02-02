"""Output formatters for clusters — plan markdown, JSON, and text."""

import json
from collections import defaultdict

from pm_core.cluster.chunks import Chunk
from pm_core.cluster.cluster_graph import Cluster


def clusters_to_plan_markdown(clusters: list[Cluster],
                              chunks: dict[str, Chunk]) -> str:
    """Convert clusters to plan markdown compatible with pm plan load.

    Each cluster becomes a ### PR: entry with files list and description.
    """
    lines = ["## PRs", ""]

    for i, cluster in enumerate(clusters):
        if not cluster.chunk_ids:
            continue

        title = cluster.name or f"Feature group {cluster.id}"
        files = _cluster_files(cluster, chunks)
        desc = _cluster_description(cluster, chunks)

        lines.append(f"### PR: {title}")
        lines.append(f"- **description**: {desc}")
        lines.append(f"- **tests**: Unit tests for {title}")
        lines.append(f"- **files**: {', '.join(files)}")
        lines.append(f"- **depends_on**: ")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def clusters_to_json(clusters: list[Cluster],
                     chunks: dict[str, Chunk]) -> str:
    """Convert clusters to JSON format."""
    result = []
    for cluster in clusters:
        files = _cluster_files(cluster, chunks)
        result.append({
            "id": cluster.id,
            "name": cluster.name,
            "description": _cluster_description(cluster, chunks),
            "chunk_count": len(cluster.chunk_ids),
            "files": files,
            "chunk_ids": sorted(cluster.chunk_ids),
        })
    return json.dumps(result, indent=2)


def clusters_to_text(clusters: list[Cluster],
                     chunks: dict[str, Chunk]) -> str:
    """Convert clusters to human-readable text summary."""
    lines = [f"Found {len(clusters)} clusters:", ""]

    for cluster in clusters:
        files = _cluster_files(cluster, chunks)
        lines.append(f"  [{cluster.id}] {cluster.name}")
        lines.append(f"       {len(cluster.chunk_ids)} chunks, {len(files)} files")
        for f in files[:10]:
            lines.append(f"         {f}")
        if len(files) > 10:
            lines.append(f"         ... and {len(files) - 10} more")
        lines.append("")

    return "\n".join(lines)


def _cluster_files(cluster: Cluster, chunks: dict[str, Chunk]) -> list[str]:
    """Get sorted unique file paths from a cluster's chunks."""
    files: set[str] = set()
    for cid in cluster.chunk_ids:
        c = chunks.get(cid)
        if c and c.kind in ("function", "class", "file"):
            files.add(str(c.path))
    return sorted(files)


def _cluster_description(cluster: Cluster, chunks: dict[str, Chunk]) -> str:
    """Generate a brief description of what a cluster contains."""
    kinds: dict[str, int] = defaultdict(int)
    for cid in cluster.chunk_ids:
        c = chunks.get(cid)
        if c:
            kinds[c.kind] += 1

    parts = []
    if kinds.get("class"):
        parts.append(f"{kinds['class']} classes")
    if kinds.get("function"):
        parts.append(f"{kinds['function']} functions")
    if kinds.get("file"):
        parts.append(f"{kinds['file']} files")

    files = _cluster_files(cluster, chunks)
    if files:
        dirs = set(str(chunks[cid].path.parent) for cid in cluster.chunk_ids
                    if cid in chunks and chunks[cid].kind != "directory")
        if len(dirs) == 1:
            parts.append(f"in {list(dirs)[0]}/")

    return "Contains " + ", ".join(parts) if parts else "Code cluster"
