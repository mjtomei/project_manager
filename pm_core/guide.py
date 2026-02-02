"""Guided workflow — state detection + prompt composition for pm guide."""

import json
import subprocess
from pathlib import Path
from typing import Optional

from pm_core import store, graph, notes
from pm_core.plan_parser import parse_plan_prs

GUIDE_STATE_FILE = ".guide-state"


STEP_ORDER = [
    "no_project",
    "initialized",
    "has_plan_draft",
    "has_plan_prs",
    "needs_deps_review",
    "ready_to_work",
    "all_in_progress",
    "all_done",
]

STEP_DESCRIPTIONS = {
    "no_project": "Initialize the project",
    "initialized": "Create a plan",
    "has_plan_draft": "Break plan into PRs",
    "has_plan_prs": "Load PRs from plan",
    "needs_deps_review": "Review PR dependencies",
    "ready_to_work": "Start working on PRs",
    "all_in_progress": "All PRs are in progress",
    "all_done": "All PRs are done",
}


def get_completed_step(root: Path) -> str | None:
    """Read the last completed step from .guide-state, or None if not tracked."""
    state_file = root / GUIDE_STATE_FILE
    if not state_file.exists():
        return None
    try:
        data = json.loads(state_file.read_text())
        return data.get("completed_step")
    except (json.JSONDecodeError, OSError):
        return None


def mark_step_completed(root: Path, state: str) -> None:
    """Write the completed step to .guide-state."""
    state_file = root / GUIDE_STATE_FILE
    state_file.write_text(json.dumps({"completed_step": state}) + "\n")

    # Ensure .guide-state is in .gitignore
    gitignore = root / ".gitignore"
    gitignore_content = gitignore.read_text() if gitignore.exists() else ""
    if GUIDE_STATE_FILE not in gitignore_content:
        with open(gitignore, "a") as f:
            if gitignore_content and not gitignore_content.endswith("\n"):
                f.write("\n")
            f.write(f"{GUIDE_STATE_FILE}\n")


def resolve_guide_step(root: Optional[Path]) -> tuple[str, dict]:
    """Detect state with completion tracking to avoid skipping steps.

    Compares artifact-based detection against the last completed step.
    If detection jumped ahead (e.g. plan file exists but step wasn't completed),
    falls back to the step after the last completed one.
    """
    detected_state, ctx = detect_state(root)
    if root is None:
        return detected_state, ctx

    completed = get_completed_step(root)
    if completed is None:
        return detected_state, ctx

    completed_idx = STEP_ORDER.index(completed) if completed in STEP_ORDER else -1
    detected_idx = STEP_ORDER.index(detected_state) if detected_state in STEP_ORDER else -1

    # If detection jumped ahead of what was completed, stay on next step
    next_step_idx = completed_idx + 1
    if detected_idx > next_step_idx and next_step_idx < len(STEP_ORDER):
        corrected = STEP_ORDER[next_step_idx]
        # Re-derive context for the corrected state
        return corrected, ctx

    return detected_state, ctx


def detect_state(root: Optional[Path]) -> tuple[str, dict]:
    """Read project state and return (state_name, context).

    root is the PM directory (containing project.yaml), or None if not found.
    """
    # No project.yaml found
    if root is None:
        return "no_project", {}

    try:
        data = store.load(root)
    except Exception:
        return "no_project", {}

    plans = data.get("plans") or []
    prs = data.get("prs") or []

    # Has project but no plans
    if not plans:
        return "initialized", {"data": data, "root": root}

    # Check if any plan has a ## PRs section
    has_pr_section = False
    plan_entry = plans[0]  # Use first plan
    plan_path = root / plan_entry["file"]
    if plan_path.exists():
        content = plan_path.read_text()
        parsed = parse_plan_prs(content)
        if parsed:
            has_pr_section = True

    # Has plan but no ## PRs section
    if not has_pr_section and not prs:
        return "has_plan_draft", {"data": data, "root": root, "plan": plan_entry}

    # Has ## PRs in plan file but no PRs loaded into project.yaml
    if has_pr_section and not prs:
        return "has_plan_prs", {"data": data, "root": root, "plan": plan_entry}

    # PRs exist — check deps review
    guide_deps_reviewed = data.get("project", {}).get("guide_deps_reviewed", False)
    if not guide_deps_reviewed:
        return "needs_deps_review", {"data": data, "root": root}

    # Check PR statuses
    statuses = [p.get("status", "pending") for p in prs]
    all_merged = all(s == "merged" for s in statuses)
    if all_merged:
        return "all_done", {"data": data, "root": root}

    ready = graph.ready_prs(prs)
    if ready:
        return "ready_to_work", {"data": data, "root": root, "ready": ready}

    # No ready PRs — everything is in progress/review/blocked
    return "all_in_progress", {"data": data, "root": root}


def step_number(state: str) -> int:
    """Return 1-based step number for a state."""
    try:
        return STEP_ORDER.index(state) + 1
    except ValueError:
        return 0


def build_guide_prompt(state: str, ctx: dict, root: Optional[Path]) -> Optional[str]:
    """Build combined manager + step prompt for the given state.

    Returns None for non-interactive steps or terminal states.
    """
    step_instructions = _step_instructions(state, ctx, root)
    if step_instructions is None:
        return None

    state_desc = STEP_DESCRIPTIONS.get(state, state)
    n = step_number(state)
    total = len([s for s in STEP_ORDER if s not in ("all_in_progress", "all_done")])

    notes_block = ""
    if root:
        notes_block = notes.notes_section(root)

    return f"""\
You are managing the guided workflow for `pm` (Project Manager for Claude Code).
You have access to the `pm` CLI — run `pm help` to see all commands.

Current state: {state_desc}
Step {n} of {total} in the setup workflow.

{step_instructions}
{notes_block}
IMPORTANT — When this step is complete and the user is satisfied:
- Confirm what was accomplished
- Run `pm guide done` to record completion
- Then exit the session (Ctrl+C or /exit)
- The workflow will automatically continue with the next step."""


def _step_instructions(state: str, ctx: dict, root: Optional[Path]) -> Optional[str]:
    """Return step-specific instructions, or None for non-interactive steps."""

    if state == "no_project":
        return """\
Run `pm init` to initialize the project. This will auto-detect the repo from
the current directory.

After init completes, discuss the repository with the user:
- What is this project about?
- What are the goals for the upcoming work?
- Any important context or constraints?

This conversation will help inform the plan in the next step."""

    if state == "initialized":
        plan_path = "<will be created>"
        if root:
            plan_path = str(root / "plans" / "plan-001.md")
        return f"""\
Create a plan for this project. Run:

  pm plan add "main"

This creates plan file at {plan_path} and launches a planning session.

Discuss with the user what work needs to be done. Write a detailed plan to the
plan file. The plan needs enough detail that the next step can break it into
individual PRs.

Include scope, goals, key design decisions, and any constraints."""

    if state == "has_plan_draft":
        plan_entry = ctx.get("plan", {})
        plan_path = root / plan_entry["file"] if root and plan_entry.get("file") else "???"
        return f"""\
The plan exists but hasn't been broken into PRs yet.

Read the plan file at: {plan_path}

Propose a set of PRs that implement this plan. Discuss the breakdown with the
user — ask about anything ambiguous (scope, ordering, parallelism).

Once agreed, write a "## PRs" section to the plan file with this format:

### PR: <title>
- **description**: What this PR does
- **tests**: Expected unit tests
- **files**: Expected file modifications
- **depends_on**: <title of dependency PR, or empty>

Separate PR entries with --- lines.

Guidelines:
- Prefer more small PRs over fewer large ones
- Order them so independent PRs can be worked on in parallel
- Only add depends_on when there's a real ordering constraint"""

    if state == "has_plan_prs":
        # Non-interactive
        return None

    if state == "needs_deps_review":
        data = ctx.get("data", {})
        prs = data.get("prs") or []
        pr_lines = []
        for p in prs:
            deps = p.get("depends_on") or []
            dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
            desc = p.get("description", "")
            desc_str = f" — {desc}" if desc else ""
            pr_lines.append(f"  {p['id']}: {p.get('title', '???')} [{p.get('status', '?')}]{dep_str}{desc_str}")
        pr_list_str = "\n".join(pr_lines)

        return f"""\
Review the dependency graph between PRs and fix any issues.

Check for:
1. Missing dependencies — if PR B can't start until PR A is done, add it
2. Wrong dependencies — if a dependency isn't actually needed, remove it
3. Circular dependencies — flag any cycles

PRs:
{pr_list_str}

Discuss any proposed changes with the user before applying them.

When the user agrees, run `pm pr edit` commands to apply fixes:
  pm pr edit pr-001 --depends-on pr-002,pr-003
  pm pr edit pr-004 --depends-on ""

After applying changes, run `pm pr graph` to show the final dependency tree."""

    if state == "ready_to_work":
        ready = ctx.get("ready", [])
        ready_lines = "\n".join(f"  {p['id']}: {p.get('title', '???')}" for p in ready)
        return f"""\
The project is set up and PRs are ready to work on!

Ready PRs:
{ready_lines}

To start working on a PR, run:
  pm pr start [pr-id]

This will clone the repo, create a branch, and launch Claude to implement the PR.

You can also run `pm pr graph` to see the full dependency tree, or `pm pr list`
to see all PRs with status.

Explain the next steps to the user and offer to start the first ready PR."""

    return None


def run_non_interactive_step(state: str, ctx: dict, root: Path) -> bool:
    """Run a non-interactive step directly. Returns True if handled."""
    if state == "has_plan_prs":
        plan_entry = ctx.get("plan", {})
        plan_id = plan_entry.get("id")
        cmd = ["pm", "plan", "load"]
        if plan_id:
            cmd.append(plan_id)
        subprocess.run(cmd, cwd=str(root))
        return True
    return False


def set_deps_reviewed(root: Path) -> None:
    """Mark deps as reviewed in project.yaml."""
    data = store.load(root)
    data["project"]["guide_deps_reviewed"] = True
    store.save(data, root)
