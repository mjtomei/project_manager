"""Claude prompt generation for PR work sessions."""

from pm_core import store, notes
from pm_core.backend import get_backend


def generate_prompt(data: dict, pr_id: str) -> str:
    """Generate a Claude Code prompt for working on a PR."""
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    plan = store.get_plan(data, pr.get("plan", ""))
    plan_name = plan["name"] if plan else "Unknown"
    plan_id = plan["id"] if plan else "?"

    # Build dependency context
    dep_lines = []
    for dep_id in pr.get("depends_on") or []:
        dep_pr = store.get_pr(data, dep_id)
        if dep_pr:
            status = dep_pr.get("status", "unknown").upper()
            dep_lines.append(f"- {dep_id} ({dep_pr.get('title', '???')}) - {status}")

    deps_section = ""
    if dep_lines:
        deps_section = "It depends on:\n" + "\n".join(dep_lines)

    branch = pr.get("branch", f"pm/{pr_id}")
    title = pr.get("title", "")
    description = pr.get("description", "").strip()
    base_branch = data.get("project", {}).get("base_branch", "main")

    backend = get_backend(data)
    gh_pr_url = pr.get("gh_pr")  # URL of draft PR if created
    instructions = backend.pr_instructions(branch, title, base_branch, pr_id, gh_pr_url)

    # Include notes if available
    notes_block = ""
    try:
        root = store.find_project_root()
        notes_block = notes.notes_section(root)
    except FileNotFoundError:
        pass

    prompt = f"""You're working on PR {pr_id}: "{title}"

This session is managed by `pm`. Run `pm help` to see available commands.

## Context
Part of plan "{plan_name}" ({plan_id}).
{deps_section}

## Task
{description}

## Tips
- This session may be resuming after a restart. Check `git status` and `git log` to see if previous work exists on this branch — if so, continue from there.
- Before referencing existing code (imports, function calls, class usage), read the source to verify the interface.

## Workflow
{instructions}
{notes_block}"""
    return prompt.strip()
