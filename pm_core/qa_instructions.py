"""QA instruction library management.

Manages instruction files in pm/qa/instructions/ (reusable procedures),
pm/qa/regression/ (migrated TUI tests), and pm/qa/mocks/ (shared mock
definitions injected into every QA scenario prompt).  Files are markdown
with YAML frontmatter.
"""

from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# Directory helpers
# ---------------------------------------------------------------------------

def qa_dir(pm_root: Path) -> Path:
    """Return pm/qa/, creating it if needed."""
    d = pm_root / "qa"
    d.mkdir(parents=True, exist_ok=True)
    return d


def instructions_dir(pm_root: Path) -> Path:
    """Return pm/qa/instructions/."""
    d = qa_dir(pm_root) / "instructions"
    d.mkdir(exist_ok=True)
    return d


def regression_dir(pm_root: Path) -> Path:
    """Return pm/qa/regression/."""
    d = qa_dir(pm_root) / "regression"
    d.mkdir(exist_ok=True)
    return d


def mocks_dir(pm_root: Path) -> Path:
    """Return pm/qa/mocks/."""
    d = qa_dir(pm_root) / "mocks"
    d.mkdir(exist_ok=True)
    return d


def artifacts_dir(pm_root: Path) -> Path:
    """Return pm/qa/artifacts/.

    Holds recipes for capturing reviewable evidence — screen recordings,
    command logs, screenshots — that demonstrate either a bug or new PR
    behavior to a human reviewer.  The captures themselves land in
    pm/qa/captures/<pr-id>/ (a convention referenced from recipes, not
    enforced here).
    """
    d = qa_dir(pm_root) / "artifacts"
    d.mkdir(exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (metadata_dict, body_text).  If no frontmatter is found,
    metadata is empty and body is the full content.
    """
    if not content.startswith("---"):
        return {}, content

    # Find the closing ---
    end = content.find("---", 3)
    if end == -1:
        return {}, content

    fm_text = content[3:end].strip()
    body = content[end + 3:].lstrip("\n")

    try:
        meta = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError:
        meta = {}

    if not isinstance(meta, dict):
        meta = {}

    return meta, body


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------

def _list_dir(directory: Path) -> list[dict]:
    """List markdown files in *directory*, parsing frontmatter for each.

    Returns a list of dicts with keys: id, title, description, tags, path.
    """
    if not directory.is_dir():
        return []

    results = []
    for f in sorted(directory.glob("*.md")):
        content = f.read_text()
        meta, _ = _parse_frontmatter(content)
        file_id = f.stem  # filename without .md
        results.append({
            "id": file_id,
            "title": meta.get("title", file_id.replace("-", " ").title()),
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "path": str(f),
        })
    return results


def list_instructions(pm_root: Path) -> list[dict]:
    """List instruction files from pm/qa/instructions/."""
    return _list_dir(instructions_dir(pm_root))


def list_regression_tests(pm_root: Path) -> list[dict]:
    """List regression test files from pm/qa/regression/."""
    return _list_dir(regression_dir(pm_root))


def list_mocks(pm_root: Path) -> list[dict]:
    """List mock definition files from pm/qa/mocks/."""
    return _list_dir(mocks_dir(pm_root))


def list_artifacts(pm_root: Path) -> list[dict]:
    """List artifact-capture recipes from pm/qa/artifacts/."""
    return _list_dir(artifacts_dir(pm_root))


def list_all(pm_root: Path) -> dict:
    """Return all QA items by category."""
    return {
        "instructions": list_instructions(pm_root),
        "regression": list_regression_tests(pm_root),
        "mocks": list_mocks(pm_root),
        "artifacts": list_artifacts(pm_root),
    }


def resolve_instruction_ref(pm_root: Path, ref: str) -> tuple[str, str] | None:
    """Resolve a planner's instruction reference to (category, filename).

    The planner is asked to output just a filename like ``tui-manual-test.md``,
    but may produce variations: a bare stem (``tui-manual-test``), a relative
    path (``instructions/tui-manual-test.md``), an absolute path, or a
    slightly-wrong name.  This function tries progressively fuzzier matching
    across both instruction and regression directories.

    Returns ``("instructions", "tui-manual-test.md")`` on success, or
    ``None`` if nothing matches.
    """
    import difflib

    # Normalise: strip whitespace / quotes, extract basename
    ref = ref.strip().strip("'\"`")
    ref = Path(ref).name  # drop any directory components

    all_items = list_all(pm_root)
    # Build a flat lookup: filename -> category
    known: dict[str, str] = {}
    for category in ("instructions", "regression", "artifacts"):
        for item in all_items[category]:
            fname = Path(item["path"]).name
            known[fname] = category

    # Also build a stem -> filename lookup for bare-stem matching
    stem_to_fname: dict[str, str] = {}
    for fname in known:
        stem_to_fname[Path(fname).stem] = fname

    # Exact match on filename
    if ref in known:
        return (known[ref], ref)

    # Bare stem match (e.g. "tui-manual-test" -> "tui-manual-test.md")
    if ref in stem_to_fname:
        fname = stem_to_fname[ref]
        return (known[fname], fname)

    # Case-insensitive match
    ref_lower = ref.lower()
    for fname, cat in known.items():
        if fname.lower() == ref_lower:
            return (cat, fname)
    for stem, fname in stem_to_fname.items():
        if stem.lower() == ref_lower:
            return (known[fname], fname)

    # Fuzzy match — try against both filenames and stems
    candidates = list(known.keys()) + list(stem_to_fname.keys())
    matches = difflib.get_close_matches(ref, candidates, n=1, cutoff=0.7)
    if matches:
        hit = matches[0]
        fname = stem_to_fname.get(hit, hit)
        return (known[fname], fname)

    return None


# ---------------------------------------------------------------------------
# Single-item access
# ---------------------------------------------------------------------------

def get_instruction(pm_root: Path, instruction_id: str,
                    category: str = "instructions") -> dict | None:
    """Load a single instruction with full body content.

    Returns dict with keys: id, title, description, tags, path, body.
    Returns None if not found.
    """
    if category == "regression":
        base = regression_dir(pm_root)
    elif category == "artifacts":
        base = artifacts_dir(pm_root)
    else:
        base = instructions_dir(pm_root)

    f = base / f"{instruction_id}.md"
    if not f.exists():
        return None

    content = f.read_text()
    meta, body = _parse_frontmatter(content)
    return {
        "id": instruction_id,
        "title": meta.get("title", instruction_id.replace("-", " ").title()),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "path": str(f),
        "body": body,
    }


def get_mock(pm_root: Path, mock_id: str) -> dict | None:
    """Load a single mock definition with full body content.

    Returns dict with keys: id, title, description, tags, path, body.
    Returns None if not found.
    """
    f = mocks_dir(pm_root) / f"{mock_id}.md"
    if not f.exists():
        return None

    content = f.read_text()
    meta, body = _parse_frontmatter(content)
    return {
        "id": mock_id,
        "title": meta.get("title", mock_id.replace("-", " ").title()),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "path": str(f),
        "body": body,
    }


# ---------------------------------------------------------------------------
# Prompt helper
# ---------------------------------------------------------------------------

def instruction_summary_for_prompt(pm_root: Path,
                                   include_regression: bool = False) -> str:
    """Build a summary of instructions for prompts.

    Args:
        pm_root: Project root path.
        include_regression: If False, exclude regression tests from the summary.

    Returns titles + descriptions + file paths (the planner reads files
    itself when it needs the full content).
    """
    all_items = list_all(pm_root)
    categories = [("instructions", "Instructions")]
    if include_regression:
        categories.append(("regression", "Regression Tests"))
    categories.append(("artifacts", "Artifact Recipes"))

    lines: list[str] = []
    for category, label in categories:
        items = all_items[category]
        if not items:
            continue
        lines.append(f"### {label}")
        for item in items:
            desc = f" — {item['description']}" if item["description"] else ""
            filename = Path(item['path']).name
            lines.append(f"- **{item['title']}** (`{filename}`){desc}")
        lines.append("")

    if not lines:
        return "No QA instructions found."

    return "\n".join(lines)


def mocks_for_prompt(pm_root: Path) -> str:
    """Build the Mocks section for QA scenario prompts from pm/qa/mocks/.

    Returns a formatted markdown block ready for injection, or empty string
    if no mocks are defined.
    """
    mocks = list_mocks(pm_root)
    if not mocks:
        return ""

    lines: list[str] = [
        "## Mocks",
        "",
        "The following mock contracts are defined for this project.  Use these "
        "when writing or running QA scenarios — do not devise your own mocking "
        "strategy for dependencies listed here.",
        "",
    ]
    for mock in mocks:
        f = Path(mock["path"])
        content = f.read_text()
        _, body = _parse_frontmatter(content)
        desc = f" — {mock['description']}" if mock["description"] else ""
        lines.append(f"### {mock['title']}{desc}")
        lines.append("")
        lines.append(body.strip())
        lines.append("")

    return "\n".join(lines) + "\n"
