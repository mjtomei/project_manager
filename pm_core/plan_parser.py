"""Parse structured sections (## PRs, ## Plans, ## Child PRs) from plan markdown files."""

import re


def extract_plan_intro(text: str) -> str:
    """Return everything before the first ## heading.

    Skips the first line if it starts with ``# `` (the plan title).
    """
    lines = text.split('\n')
    result = []
    skipped_title = False
    for line in lines:
        if not skipped_title and line.startswith('# '):
            skipped_title = True
            continue
        if line.startswith('## '):
            break
        result.append(line)
    return '\n'.join(result).strip()


def _parse_section(
    text: str, section: str, block_prefix: str, fields: list[str],
) -> list[dict]:
    """Parse a markdown section into a list of dicts.

    Finds ``## <section>``, splits on ``### <block_prefix>:`` headings,
    and extracts *title* plus each named field via ``extract_field()``.
    """
    header = re.search(rf'^## {re.escape(section)}\s*$', text, re.MULTILINE)
    if not header:
        return []

    section_text = text[header.end():]

    # Stop at next ## heading (but not ###)
    next_section = re.search(r'^## [^#]', section_text, re.MULTILINE)
    if next_section:
        section_text = section_text[:next_section.start()]

    blocks = re.split(
        rf'^### {re.escape(block_prefix)}:\s*', section_text, flags=re.MULTILINE,
    )

    results = []
    # blocks[0] is preamble text before the first ### heading — skip it
    for block in blocks[1:]:
        block = block.strip()
        if not block:
            continue

        # Remove --- separators
        block = re.sub(r'^\s*---\s*$', '', block, flags=re.MULTILINE).strip()

        # First line is the title
        lines = block.split('\n', 1)
        title = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""

        entry = {"title": title}
        for field in fields:
            entry[field] = extract_field(body, field)
        results.append(entry)

    return results


def parse_plan_prs(text: str) -> list[dict]:
    """Parse structured PR entries from a plan file's ## PRs section.

    Returns a list of dicts with keys: title, description, tests, files, depends_on.
    """
    return _parse_section(text, "PRs", "PR", [
        "description", "tests", "files", "depends_on",
    ])


def parse_plan_children(text: str) -> list[dict]:
    """Parse child plan entries from a plan file's ## Plans section.

    Returns a list of dicts with keys: title, summary, status, id.
    """
    return _parse_section(text, "Plans", "Plan", ["summary", "status", "id"])


def parse_split_prs(text: str) -> list[dict]:
    """Parse child PR entries from a split manifest's ## Child PRs section.

    Returns a list of dicts with keys: title, description, branch, depends_on.
    """
    return _parse_section(text, "Child PRs", "PR", [
        "description", "branch", "depends_on",
    ])


def extract_field(body: str, field: str) -> str:
    """Extract a **field**: value from the body text."""
    pattern = rf'^\s*-\s*\*\*{re.escape(field)}\*\*:[^\S\n]*(.*?)$'
    match = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""
