"""Guided workflow — state detection + prompt composition for pm guide."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from pm_core import store, graph, notes
from pm_core.plan_parser import parse_plan_prs


STEP_ORDER = [
    "no_project",
    "initialized",
    "has_plan_draft",
    "has_plan_prs",
    "ready_to_work",
    "all_in_progress",
    "all_done",
]

STEP_DESCRIPTIONS = {
    "no_project": "Initialize the project",
    "initialized": "Create a plan",
    "has_plan_draft": "Break plan into PRs",
    "has_plan_prs": "Load PRs from plan",
    "ready_to_work": "Start working on PRs",
    "all_in_progress": "All PRs are in progress",
    "all_done": "All PRs are done",
}

# States where setup is still in progress (no PRs loaded yet)
SETUP_STATES = {"no_project", "initialized", "has_plan_draft", "has_plan_prs"}


def is_setup_state(state: str) -> bool:
    """Return True if state indicates setup is still in progress (no PRs)."""
    return state in SETUP_STATES


def detect_state(root: Optional[Path]) -> tuple[str, dict]:
    """Read project state and return (state_name, context).

    root is the PM directory (containing project.yaml), or None if not found.
    """
    # No project.yaml found
    if root is None:
        return "no_project", {}

    try:
        data = store.load(root)
    except FileNotFoundError:
        return "no_project", {}
    except Exception as exc:
        raise RuntimeError(f"Failed to load project data from {root}: {exc}") from exc

    plans = data.get("plans") or []
    prs = data.get("prs") or []

    # Has project but no plans and no PRs
    if not plans and not prs:
        return "initialized", {"data": data, "root": root}

    # Check if any plan has a ## PRs section (only when plans exist)
    has_pr_section = False
    plan_entry = None
    if plans:
        plan_entry = plans[0]  # Use first plan
        plan_path = root / plan_entry["file"]
        if plan_path.exists():
            content = plan_path.read_text()
            parsed = parse_plan_prs(content)
            if parsed:
                has_pr_section = True

    # Has plan but no ## PRs section and no PRs loaded yet
    if plans and not has_pr_section and not prs:
        return "has_plan_draft", {"data": data, "root": root, "plan": plan_entry}

    # Has ## PRs in plan file but no PRs loaded into project.yaml
    if has_pr_section and not prs:
        return "has_plan_prs", {"data": data, "root": root, "plan": plan_entry}

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


def run_non_interactive_step(state: str, ctx: dict, root: Path) -> bool:
    """Run a non-interactive step directly. Returns True if handled."""
    if state == "has_plan_prs":
        # Guard against duplicate runs — only load if no PRs exist yet
        data = ctx.get("data") or store.load(root)
        if data.get("prs"):
            return True
        plan_entry = ctx.get("plan", {})
        plan_id = plan_entry.get("id")
        cmd = ["pm", "plan", "load"]
        if plan_id:
            cmd.append(plan_id)
        subprocess.run(cmd, cwd=str(root))
        return True
    return False


def _status_line(label: str, state: str, done_after: set[str], current_idx: int, step_order: list[str]) -> str:
    """Build a single status checklist line for the setup prompt."""
    done_steps = set(step_order[:current_idx])
    is_done = bool(done_after & done_steps)
    if is_done:
        return f"- {label}: done"
    # Check if this is the current item
    for s in step_order:
        idx = step_order.index(s)
        if idx >= current_idx and s in done_after:
            # This item's trigger step is at or after current — it's next or pending
            break
    if not is_done and any(step_order.index(s) == current_idx for s in done_after if s in step_order):
        return f"- {label}: next"
    return f"- {label}: pending"


def build_setup_prompt(state: str, ctx: dict, root: Optional[Path],
                       session_name: str | None = None) -> str:
    """Build the setup prompt for guiding a user through project initialization.

    This is a single comprehensive prompt with a dynamic status section
    showing what's been done and what comes next.
    """
    try:
        current_idx = STEP_ORDER.index(state)
    except ValueError:
        current_idx = 0

    done_steps = set(STEP_ORDER[:current_idx])

    # Build status section
    checklist = [
        ("Project file", {"initialized", "has_plan_draft", "has_plan_prs"}),
        ("Plan file", {"has_plan_draft", "has_plan_prs"}),
        ("PRs loaded", {"has_plan_prs"}),
    ]

    status_lines = []
    found_next = False
    for label, done_after in checklist:
        is_done = bool(done_after & done_steps)
        if is_done:
            status_lines.append(f"- {label}: done")
        elif not found_next:
            found_next = True
            status_lines.append(f"- {label}: **next**")
        else:
            status_lines.append(f"- {label}: pending")

    status_section = "\n".join(status_lines)

    # Project info
    data = ctx.get("data", {})
    project = data.get("project", {})
    project_name = project.get("name", "unknown")
    repo = project.get("repo", "unknown")
    root_str = str(root) if root else "unknown"

    notes_block = ""
    if root:
        notes_block = notes.notes_section(root)

    tui_block = ""
    if session_name:
        from pm_core.prompt_gen import tui_section
        tui_block = tui_section(session_name)

    pane_id = os.environ.get("TMUX_PANE", "")

    return f"""\
You are guiding a user through setting up their project with `pm` (Project Manager for Claude Code).
You have access to the `pm` CLI — run `pm help` to see all commands.

## Current Status
{status_section}

## Project
Name: {project_name}
Repo: {repo}
Root: {root_str}
{tui_block}
## Your Task

Walk the user through setting up their project. The status section above shows
what's already done and what comes next. Focus on the **next** item.

**IMPORTANT:** You are guiding the user, not doing everything yourself. After
init, direct the user to interact with the TUI to create plans and load PRs.
Do NOT run `pm plan add`, `pm plan breakdown`, or `pm plan load` yourself —
instead tell the user which keys to press in the TUI and what to expect.

### Initializing the project

If no project file exists yet, run `pm init --no-import` to initialize. This
auto-detects the repo from the current directory. Use --no-import because we'll
create a plan through the TUI.

After init, explore the codebase — read the README, look at directory structure,
check recent git history. Share what you find with the user and ask about their
goals for upcoming work.

### Creating a plan

Tell the user to press `P` in the TUI to open the plans view, then press `a`
to add a new plan. A dialog will ask for a name and description — help them
choose good values based on what you learned about the codebase and their goals.
The `a` action launches a Claude session in a new pane. Once it finishes, the
user can close that pane before moving on.

### Breaking the plan into PRs

Tell the user to press `w` in the plans view to break the plan into PRs. This
launches a Claude session that explores the codebase, writes the plan content,
and adds a `## PRs` section with individual PR entries. Once the breakdown
session finishes, the user can close that pane before moving on.

### Reviewing the plan

Tell the user to press `c` in the plans view to review the plan. This launches
a Claude session that checks the plan and PRs for consistency. Once the review
session finishes, the user can close that pane before moving on.

### Loading PRs

Tell the user to press `l` in the plans view to load PRs from the plan file
into the project. This runs quickly and does not launch a Claude session.

### TUI plans view reference

In the TUI, `P` toggles the plans view. The setup flow is `a` → `w` → `c` → `l`:
- `a` — add a new plan (prompts for name and description)
- `w` — break plan into PRs (launches a Claude session)
- `c` — review plan (launches a Claude session)
- `l` — load PRs from plan into the project
- `e` — edit plan file
- `v` — view plan file

## Next Step

Once PRs are loaded, tell the user to press `P` to leave the plans view.
The TUI will show the PR tech tree. They can press `s` on a PR to start
working on it.
{notes_block}"""


def build_assist_prompt(data: dict, root: Optional[Path],
                        session_name: str | None = None) -> str:
    """Build the assist prompt for helping users decide what to do next.

    Includes project context, PR list, lifecycle overview, and health-check task.
    """
    project = data.get("project", {})
    project_name = project.get("name", "unknown")
    repo = project.get("repo", "unknown")
    prs = data.get("prs") or []
    plans = data.get("plans") or []

    # Build PR summary
    pr_lines = []
    for pr in prs:
        status = pr.get("status", "pending")
        title = pr.get("title", "???")
        pr_id = pr.get("id", "???")
        deps = pr.get("depends_on") or []
        dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
        wd = pr.get("workdir", "")
        wd_str = ""
        if wd:
            wd_path = Path(wd)
            if wd_path.exists():
                wd_str = f" workdir: {wd}"
            else:
                wd_str = f" workdir: {wd} (MISSING)"
        pr_lines.append(f"  - {pr_id}: {title} [{status}]{dep_str}{wd_str}")
    pr_summary = "\n".join(pr_lines) if pr_lines else "  (no PRs yet)"

    # Build plan summary
    plan_lines = []
    for plan in plans:
        plan_id = plan.get("id", "???")
        title = plan.get("title", plan.get("name", "???"))
        plan_lines.append(f"  - {plan_id}: {title}")
    plan_summary = "\n".join(plan_lines) if plan_lines else "  (no plans yet)"

    pane_id = os.environ.get("TMUX_PANE", "")
    sess = session_name or "default"

    tui_block = ""
    if session_name:
        from pm_core.prompt_gen import tui_section
        tui_block = tui_section(session_name)

    notes_block = ""
    if root:
        notes_block = notes.notes_section(root)

    return f"""\
## You are helping someone who may be a novice programmer decide on their \
next step.

## Session Context

Project: {project_name}
Repository: {repo}
tmux session: {sess}
TUI pane ID: {pane_id}

{tui_block}
Current plans:
{plan_summary}

Current PRs:
{pr_summary}

## pm Project Lifecycle

pm organizes work in a structured lifecycle. Actions can be done through the \
TUI (key shortcuts) or CLI commands:

1. **Initialize** (`pm init` / guide auto-runs it): Set up pm for a \
codebase. Creates a pm/ directory that tracks plans and PRs.

2. **Plan** (TUI: `P` then `a` / CLI: `pm plan add`): Write a high-level \
plan describing a feature or goal. Plans are markdown files.

3. **Break down** (TUI: `w` in plans view / CLI: `pm plan breakdown`): \
Launch a Claude session to turn a plan into concrete PRs — small, focused \
units of work with dependencies forming a tree shown in the TUI.

4. **Review** (TUI: `c` in plans view / CLI: `pm plan review`): Launch a \
Claude session to check plan-PR consistency and coverage before loading.

5. **Load** (TUI: `l` in plans view / CLI: `pm plan load`): Load PRs from \
the plan file into the project. In the TUI, press `P` to leave plans view \
and see the tech tree.

6. **Work** (TUI: `s` on a PR / CLI: `pm pr start`): Start a PR to open \
a Claude session focused on that task. Claude works in a dedicated branch \
and directory.

7. **Done** (TUI: `d` on a PR / CLI: `pm pr done`): Mark a PR as done. \
This pushes the branch, creates a GitHub pull request, and opens a new \
tmux window with a Claude review session that checks the code.

8. **Merge**: After review, PRs get merged. pm detects this automatically \
and updates the tree.

At any point the user might need to: add new plans, add or reorder PRs, \
check on in-progress work, or understand what to tackle next.

## Your Task

Before making any recommendations, check the project's current health:

1. Run `pm pr list --workdirs` to see all PRs with their workdir paths and \
git status (clean/dirty/missing)
2. Run `pm plan list` to see existing plans

Then assess:
- Are there workdirs with uncommitted changes for merged PRs? (work that might be lost)
- Are there in-progress PRs that could be resumed?
- Are there PRs in review that might need attention?
- Are there pending PRs whose dependencies are all met?
- Are there plans that haven't been broken down yet?
- Is the dependency tree healthy?

Based on what you find, give the user clear, simple recommendations for \
what to do next. Suggest one or two concrete actions, not an overwhelming list. \
Prefer finishing in-progress work over starting new work.
{notes_block}"""
