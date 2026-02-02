"""Pre-partition files into obvious groups before metric-based clustering."""

from collections import defaultdict
from pathlib import PurePosixPath

from pm_core.cluster.chunks import Chunk

# Extensions/names for docs
_DOC_EXTS = {".md", ".txt", ".tex", ".rst", ".adoc"}

# Extensions/names for config
_CONFIG_EXTS = {".toml", ".yaml", ".yml", ".json", ".cfg", ".ini"}
_CONFIG_NAMES = {
    ".gitignore", ".gitattributes", ".editorconfig", ".prettierrc",
    "makefile", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "pyproject.toml", "setup.cfg", "setup.py", "install.sh",
    "license", "licence",
}


def classify_file(rel_path: str) -> str:
    """Classify a file path as 'docs', 'config', or 'code'."""
    p = PurePosixPath(rel_path)
    name_lower = p.name.lower()
    ext = p.suffix.lower()

    # Exact name matches for config
    if name_lower in _CONFIG_NAMES:
        return "config"

    # Extension-based
    if ext in _DOC_EXTS:
        return "docs"
    if ext in _CONFIG_EXTS:
        return "config"

    return "code"


def _top_level_dir(rel_path: str) -> str:
    """Return the first path component, or '' for root-level files."""
    parts = PurePosixPath(rel_path).parts
    if len(parts) <= 1:
        return ""
    return parts[0]


def _has_cross_imports(chunks_a: list[Chunk], chunks_b: list[Chunk]) -> bool:
    """Check if any chunk in group A imports something from group B or vice versa.

    Uses a simple heuristic: check if any import string contains a top-level
    directory or module name from the other group.
    """
    # Collect module prefixes from each group
    dirs_a: set[str] = set()
    dirs_b: set[str] = set()
    for c in chunks_a:
        tld = _top_level_dir(str(c.path))
        if tld:
            dirs_a.add(tld)
            # Also add dotted form for Python imports
            dirs_a.add(tld.replace("-", "_"))
    for c in chunks_b:
        tld = _top_level_dir(str(c.path))
        if tld:
            dirs_b.add(tld)
            dirs_b.add(tld.replace("-", "_"))

    # Check if A imports from B
    for c in chunks_a:
        for imp in c.imports:
            root_mod = imp.split(".")[0]
            if root_mod in dirs_b:
                return True

    # Check if B imports from A
    for c in chunks_b:
        for imp in c.imports:
            root_mod = imp.split(".")[0]
            if root_mod in dirs_a:
                return True

    return False


def pre_partition(chunks: list[Chunk]) -> dict[str, list[Chunk]]:
    """Split chunks into named partitions before clustering.

    Returns a dict mapping partition name to list of chunks.
    Small partitions (<=3 file-level chunks) are kept as-is — the caller
    should skip agglomerative clustering for them and treat them as a
    single cluster.
    """
    # Step 1: classify by file type
    by_category: dict[str, list[Chunk]] = defaultdict(list)
    for c in chunks:
        if c.kind == "directory":
            # Directory chunks go with their category based on contents
            continue
        cat = classify_file(str(c.path))
        by_category[cat].append(c)

    partitions: dict[str, list[Chunk]] = {}

    # Docs and config: each becomes one partition (no further splitting)
    for cat in ("docs", "config"):
        if by_category[cat]:
            partitions[cat] = by_category[cat]

    # Step 2: split code by top-level directory, then check cross-imports
    code_chunks = by_category.get("code", [])
    if not code_chunks:
        return partitions

    by_tld: dict[str, list[Chunk]] = defaultdict(list)
    for c in code_chunks:
        tld = _top_level_dir(str(c.path))
        by_tld[tld].append(c)

    # Step 3: merge TLDs that have cross-imports
    tld_names = list(by_tld.keys())
    # Use union-find to group connected TLDs
    parent: dict[str, str] = {t: t for t in tld_names}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx

    for i, a in enumerate(tld_names):
        for b in tld_names[i + 1:]:
            if _has_cross_imports(by_tld[a], by_tld[b]):
                union(a, b)

    # Group TLDs by their root
    groups: dict[str, list[str]] = defaultdict(list)
    for t in tld_names:
        groups[find(t)].append(t)

    for root_tld, members in groups.items():
        if len(members) == 1 and members[0]:
            name = f"code/{members[0]}"
        elif len(members) == 1 and members[0] == "":
            name = "code/root"
        else:
            # Multiple TLDs merged — use the root name or join them
            named = [m or "root" for m in members]
            name = "code/" + "+".join(sorted(named))

        combined: list[Chunk] = []
        for m in members:
            combined.extend(by_tld[m])
        partitions[name] = combined

    return partitions
