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


def get_started_step(root: Path) -> str | None:
    """Read the last started step from .guide-state, or None if not tracked."""
    state_file = root / GUIDE_STATE_FILE
    if not state_file.exists():
        return None
    try:
        data = json.loads(state_file.read_text())
        return data.get("started_step")
    except (json.JSONDecodeError, OSError):
        return None


def mark_step_started(root: Path, state: str) -> None:
    """Record which step is about to be launched."""
    state_file = root / GUIDE_STATE_FILE
    data = {}
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    data["started_step"] = state
    state_file.write_text(json.dumps(data) + "\n")


def mark_step_completed(root: Path, state: str) -> None:
    """Write the completed step to .guide-state."""
    state_file = root / GUIDE_STATE_FILE
    data = {}
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    data["completed_step"] = state
    state_file.write_text(json.dumps(data) + "\n")

    # Ensure guide files are in .gitignore
    gitignore = root / ".gitignore"
    gitignore_content = gitignore.read_text() if gitignore.exists() else ""
    additions = []
    for fname in (GUIDE_STATE_FILE, "guide-notes.md", ".pm-sessions.json"):
        if fname not in gitignore_content:
            additions.append(fname)
    if additions:
        suffix = ""
        if gitignore_content and not gitignore_content.endswith("\n"):
            suffix = "\n"
        suffix += "\n".join(additions) + "\n"
        gitignore.write_text(gitignore_content + suffix)


def resolve_guide_step(root: Optional[Path]) -> tuple[str, dict]:
    """Detect state with completion tracking to avoid skipping steps.

    Compares artifact-based detection against the last completed step.
    If detection jumped ahead (e.g. plan file exists but step wasn't completed),
    falls back to the step after the last completed one.

    Also uses started_step as a floor when completed_step is None - if a step
    was started but not completed (e.g. user killed the pane), we stay on that
    step rather than jumping ahead based on artifacts.
    """
    detected_state, ctx = detect_state(root)
    if root is None:
        return detected_state, ctx

    completed = get_completed_step(root)
    started = get_started_step(root)
    detected_idx = STEP_ORDER.index(detected_state) if detected_state in STEP_ORDER else -1

    # If no step completed but one was started, use started as the floor
    if completed is None and started is not None:
        started_idx = STEP_ORDER.index(started) if started in STEP_ORDER else -1
        if detected_idx > started_idx and started_idx >= 0:
            # Detection jumped ahead of the started step - stay on started
            _, fresh_ctx = detect_state(root)
            return started, fresh_ctx
        return detected_state, ctx

    if completed is None:
        return detected_state, ctx

    # Treat invalid completed_step as if it were None
    if completed not in STEP_ORDER:
        return detected_state, ctx

    completed_idx = STEP_ORDER.index(completed)

    # If detection jumped ahead of what was completed, advance to the
    # next uncompleted step.  But if a step was started (and not completed),
    # stay on that step — the user is still working on it.
    next_step_idx = completed_idx + 1
    if detected_idx > next_step_idx and next_step_idx < len(STEP_ORDER):
        # If a step has been started but not completed, stay on it
        if started is not None and started in STEP_ORDER:
            started_idx = STEP_ORDER.index(started)
            if started_idx > completed_idx:
                _, fresh_ctx = detect_state(root)
                return started, fresh_ctx
        corrected = STEP_ORDER[next_step_idx]
        # Re-derive context for the corrected state by re-detecting
        _, fresh_ctx = detect_state(root)
        return corrected, fresh_ctx

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
    except FileNotFoundError:
        return "no_project", {}
    except Exception as exc:
        raise RuntimeError(f"Failed to load project data from {root}: {exc}") from exc

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


def _upcoming_steps_section(state: str) -> str:
    """Return a description of what comes after the current step."""
    interactive_steps = [s for s in STEP_ORDER if s not in ("all_in_progress", "all_done")]
    try:
        idx = interactive_steps.index(state)
    except ValueError:
        return ""
    remaining = interactive_steps[idx + 1:]
    if not remaining:
        return ""
    lines = []
    for s in remaining:
        desc = STEP_DESCRIPTIONS.get(s, s)
        lines.append(f"  - {desc}")
    return "\n## What comes next\n" + "\n".join(lines) + "\n\n(Each step runs in its own session — just focus on the current one.)\n"


def build_guide_prompt(state: str, ctx: dict, root: Optional[Path],
                       session_name: str | None = None) -> Optional[str]:
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

    guide_notes_block = ""
    if root:
        guide_notes_path = root / "guide-notes.md"
        if guide_notes_path.exists():
            content = guide_notes_path.read_text().strip()
            if content:
                guide_notes_block = f"\n## Context from previous steps\n{content}\n"

    upcoming_block = _upcoming_steps_section(state)

    tui_block = ""
    if session_name:
        from pm_core.prompt_gen import tui_section
        tui_block = tui_section(session_name)

    return f"""\
You are managing the guided workflow for `pm` (Project Manager for Claude Code).
You have access to the `pm` CLI — run `pm help` to see all commands.

Current state: {state_desc}
Step {n} of {total} in the setup workflow.

{step_instructions}
{tui_block}{notes_block}{guide_notes_block}{upcoming_block}
IMPORTANT — When this step is complete and the user is satisfied:
- Confirm what was accomplished
- Run `pm guide done` to record completion
- Then exit the session (Ctrl+C or /exit)
- The workflow will automatically continue with the next step."""


def _step_instructions(state: str, ctx: dict, root: Optional[Path]) -> Optional[str]:
    """Return step-specific instructions, or None for non-interactive steps."""

    if state == "no_project":
        return """\
Run `pm init --no-import` to initialize the project. This will auto-detect the
repo from the current directory. (Use --no-import because the guided workflow
handles plan creation in a later step.)

After init completes, explore the codebase yourself — read the README, look at
the directory structure, check recent git history. Build your own understanding
of the project, then share what you've found with the user and ask about their
goals for upcoming work. Use your judgment about what's worth asking vs. what
you can figure out from the code.

Before finishing, write a summary of the project context and the user's goals
to pm/guide-notes.md. This is critical — the next step runs in a new session
that won't have this conversation's context. This file is the only way to pass
information forward between guide steps."""

    if state == "initialized":
        plan_path = "<will be created>"
        if root:
            plan_path = str(root / "plans" / "plan-001.md")
        return f"""\
Create a plan for this project. Run:

  pm plan add "main"

This creates plan file at {plan_path} and launches a planning session.

Based on what you know about the codebase and the conversation so far, draft
a plan and write it to the plan file. Then walk the user through it and refine
based on their feedback. The plan needs enough detail that the next step can
break it into individual PRs.

Before finishing, update pm/guide-notes.md with any decisions or context from
this conversation that the next step will need."""

    if state == "has_plan_draft":
        plan_entry = ctx.get("plan", {})
        plan_path = root / plan_entry["file"] if root and plan_entry.get("file") else "???"
        return f"""\
The plan exists but hasn't been broken into PRs yet.

Read the plan file at: {plan_path}

Break the plan into PRs. Propose your best decomposition to the user, then
refine based on their feedback. When agreed, write a "## PRs" section to the
plan file with this format:

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
Review the dependency graph between PRs — look for missing dependencies,
unnecessary ones, and cycles. Read the plan file for context on what each
PR involves.

PRs:
{pr_list_str}

Present your analysis and proposed fixes to the user. Once agreed, apply
changes with `pm pr edit`:
  pm pr edit pr-001 --depends-on pr-002,pr-003
  pm pr edit pr-004 --depends-on ""

Run `pm pr graph` to show the final dependency tree. Once the user is happy
with the graph, this step is complete."""

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


def set_deps_reviewed(root: Path) -> None:
    """Mark deps as reviewed in project.yaml."""
    data = store.load(root)
    data["project"]["guide_deps_reviewed"] = True
    store.save(data, root)
