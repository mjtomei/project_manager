"""Claude prompt generation for PR work sessions."""

from pm_core import store, notes
from pm_core.backend import get_backend


def generate_prompt(data: dict, pr_id: str) -> str:
    """Generate a Claude Code prompt for working on a PR."""
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    plan_ref = pr.get("plan")
    plan = store.get_plan(data, plan_ref) if plan_ref else None

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

    # Include session notes if available
    notes_block = ""
    try:
        root = store.find_project_root()
        notes_block = notes.notes_section(root)
    except FileNotFoundError:
        pass

    # Include PR notes (addendums added after work began)
    pr_notes = pr.get("notes") or []
    pr_notes_block = ""
    if pr_notes:
        note_lines = []
        for n in pr_notes:
            ts = n.get("created_at", "")
            ts_str = f" ({ts})" if ts else ""
            note_lines.append(f"- {n['text']}{ts_str}")
        pr_notes_block = f"\n## PR Notes\n" + "\n".join(note_lines) + "\n"

    prompt = f"""You're working on PR {pr_id}: "{title}"

This session is managed by `pm`. Run `pm help` to see available commands.

## Context
{f'Part of plan "{plan["name"]}" ({plan["id"]}).' if plan else 'Standalone PR (not part of a plan).'}
{deps_section}

## Task
{description}
{pr_notes_block}
## Tips
- This session may be resuming after a restart. Check `git status` and `git log` to see if previous work exists on this branch — if so, continue from there.
- Before referencing existing code (imports, function calls, class usage), read the source to verify the interface.
- This workdir is a clone managed by pm. The base pm state (project.yaml, PR status) lives in a separate directory and is not automatically synced with this clone. Commands like `pm pr start` and `pm pr done` should be run from the base directory, not here — your session for {pr_id} is already running.

## Workflow
{instructions}
{notes_block}"""
    return prompt.strip()


def generate_review_prompt(data: dict, pr_id: str) -> str:
    """Generate a Claude Code prompt for reviewing a completed PR."""
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    title = pr.get("title", "")
    description = pr.get("description", "").strip()
    base_branch = data.get("project", {}).get("base_branch", "main")

    # Build plan and sibling PR context for architectural review
    plan_ref = pr.get("plan")
    plan = store.get_plan(data, plan_ref) if plan_ref else None
    all_prs = data.get("prs") or []

    plan_context = ""
    if plan:
        sibling_prs = [p for p in all_prs if p.get("plan") == plan_ref and p["id"] != pr_id]
        if sibling_prs:
            lines = []
            for p in sibling_prs:
                status = p.get("status", "pending")
                lines.append(f"- {p['id']}: {p.get('title', '???')} [{status}]")
            plan_context = f"""
## Plan Context
This PR is part of plan "{plan['name']}" ({plan['id']}). Other PRs in this plan:
{chr(10).join(lines)}
"""

    # Include PR notes (addendums)
    pr_notes = pr.get("notes") or []
    pr_notes_block = ""
    if pr_notes:
        note_lines = []
        for n in pr_notes:
            ts = n.get("created_at", "")
            ts_str = f" ({ts})" if ts else ""
            note_lines.append(f"- {n['text']}{ts_str}")
        pr_notes_block = f"\n## PR Notes\n" + "\n".join(note_lines) + "\n"

    prompt = f"""You are reviewing PR {pr_id}: "{title}"

## Task
Review the code changes in this PR for quality, correctness, and architectural fit.

## Description
{description}
{pr_notes_block}{plan_context}
## Steps
1. Run `git diff origin/{base_branch}...HEAD` to see all changes
2. **Generic checks** — things any codebase should get right:
   - Excessive file/function length, duplicated code, dead or unnecessary code, potential bugs, security issues, confusing code that lacks comments, sufficient test coverage
3. **Project-specific checks** — does the change fit this codebase?
   - Convention consistency, architectural patterns
   - Search for similar code elsewhere in the repo — flag opportunities for shared helpers or reuse
4. **Architectural review** — does the implementation approach make sense?
   - Were the PR's goals achieved in a reasonable way, or is there a simpler/better design?
   - If plan context is listed above, check whether choices in this PR make any of those sibling PRs harder to implement. Are there data models, interfaces, or patterns introduced here that will need awkward workarounds later?
   - Run `pm pr list` to see all PRs and plans for the repo. If any other plans or standalone PRs touch related areas, consider whether this PR's approach conflicts with or complicates them.
   - Consider likely future changes beyond the current PR list — does this PR paint the codebase into a corner or leave good extension points?
5. Output per-file notes: **filename** — GOOD / FIX / RETHINK
6. End with an overall verdict: **PASS** or **NEEDS_WORK**
   - If NEEDS_WORK, separate code-quality fixes from architectural concerns"""
    return prompt.strip()
