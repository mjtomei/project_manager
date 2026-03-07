"""QA instruction library management.

Manages instruction files in pm/qa/instructions/ (reusable procedures) and
pm/qa/regression/ (migrated TUI tests).  Files are markdown with YAML
frontmatter.
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


def list_all(pm_root: Path) -> dict:
    """Return all QA items by category.

    Returns {"instructions": [...], "regression": [...]}.
    """
    return {
        "instructions": list_instructions(pm_root),
        "regression": list_regression_tests(pm_root),
    }


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


# ---------------------------------------------------------------------------
# Prompt helper
# ---------------------------------------------------------------------------

def instruction_summary_for_prompt(pm_root: Path,
                                   include_regression: bool = True) -> str:
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

    lines: list[str] = []
    for category, label in categories:
        items = all_items[category]
        if not items:
            continue
        lines.append(f"### {label}")
        for item in items:
            desc = f" — {item['description']}" if item["description"] else ""
            lines.append(f"- **{item['title']}** (`{item['path']}`){desc}")
        lines.append("")

    if not lines:
        return "No QA instructions found."

    return "\n".join(lines)
