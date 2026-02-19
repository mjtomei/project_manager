"""Parse the ## PRs section from a plan file."""

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


def parse_plan_prs(text: str) -> list[dict]:
    """Parse structured PR entries from a plan file's ## PRs section.

    Expected format:
        ## PRs

        ### PR: Title here
        - **description**: ...
        - **tests**: ...
        - **files**: ...
        - **depends_on**: Other PR title

    Returns a list of dicts with keys: title, description, tests, files, depends_on.
    """
    # Find the ## PRs section
    prs_match = re.search(r'^## PRs\s*$', text, re.MULTILINE)
    if not prs_match:
        return []

    prs_text = text[prs_match.end():]

    # Stop at next ## heading (but not ###)
    next_section = re.search(r'^## [^#]', prs_text, re.MULTILINE)
    if next_section:
        prs_text = prs_text[:next_section.start()]

    # Split on ### PR: headings
    pr_blocks = re.split(r'^### PR:\s*', prs_text, flags=re.MULTILINE)

    results = []
    for block in pr_blocks:
        block = block.strip()
        if not block:
            continue

        # Remove --- separators
        block = re.sub(r'^\s*---\s*$', '', block, flags=re.MULTILINE).strip()

        # First line is the title
        lines = block.split('\n', 1)
        title = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""

        entry = {
            "title": title,
            "description": extract_field(body, "description"),
            "tests": extract_field(body, "tests"),
            "files": extract_field(body, "files"),
            "depends_on": extract_field(body, "depends_on"),
        }
        results.append(entry)

    return results


def extract_field(body: str, field: str) -> str:
    """Extract a **field**: value from the body text."""
    pattern = rf'^\s*-\s*\*\*{re.escape(field)}\*\*:\s*(.*?)$'
    match = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""
