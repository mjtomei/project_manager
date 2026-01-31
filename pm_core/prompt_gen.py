"""Claude prompt generation with guardrails."""

from pm_core import store


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

    prompt = f"""You are working on PR {pr_id}: "{title}"

## Context
This PR is part of the plan "{plan_name}" ({plan_id}).
{deps_section}

## Task
{description}

## Guardrails
- Write unit tests for every phase of your work. Do not defer testing.
- Before referencing any existing code (imports, function calls, class usage), read the actual source to verify it exists and has the expected interface. Do not assume.

## Instructions
- Work in the current directory (already on branch {branch})
- When done, commit your changes, push the branch, and create a PR:
  git push -u origin {branch}
  gh pr create --title "{title}" --base {base_branch}
- Then tell the human you're done so they can run: pm pr done {pr_id}
"""
    return prompt.strip()
