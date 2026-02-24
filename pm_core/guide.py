"""Guided workflow — state detection + prompt composition for pm guide."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from pm_core import store, graph, notes
from pm_core.paths import get_global_setting, has_global_setting
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


def needs_guide(root: Optional[Path]) -> bool:
    """Return True if the guide should auto-launch (project is in setup).

    Used by session startup to decide whether to start the notes pane
    (skip it when the guide will auto-launch) and by the TUI to trigger
    the guide pane on first load.
    """
    state, _ = detect_state(root)
    return is_setup_state(state)


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


def _beginner_mode_guide_section() -> str:
    """Return the beginner mode section for the guide prompt.

    - Not yet configured: ask the user and offer to enable it.
    - Already enabled: explain what it does and confirm they want to keep it.
    - Explicitly disabled: omit entirely.
    """
    if not has_global_setting("beginner-mode"):
        # Never configured — offer to enable
        return (
            "After init, ask the user: \"Are you new to programming or this kind of workflow?\n"
            "I can enable beginner mode which adds extra guidance to every session.\"\n"
            "If they say yes (or seem unsure), run `pm setting beginner-mode on` and confirm\n"
            "it's enabled. Beginner mode adds step-by-step explanations and next-step\n"
            "recommendations to all Claude sessions. If they say no, run\n"
            "`pm setting beginner-mode off` so this question isn't asked again.\n\n"
        )
    if get_global_setting("beginner-mode"):
        # Currently enabled — confirm with user
        return (
            "Beginner mode is currently enabled. This adds step-by-step explanations\n"
            "and next-step recommendations to all Claude sessions. Let the user know\n"
            "it's on and ask if they'd like to keep it. If they want to disable it,\n"
            "run `pm setting beginner-mode off`.\n\n"
        )
    # Explicitly disabled — say nothing
    return ""


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

    return f"""\
You are guiding a user through setting up their project with `pm` (Project Manager for Claude Code).
You have access to the `pm` CLI — run `pm help` to see all commands.

## About you and pm

Start by briefly introducing yourself to the user. Tell them a bit about what
you are and what you can do in relation to this tool — for example, that you
can do many things only an expert programmer can normally do on a computer
(reading codebases, writing and debugging code, managing git branches and pull
requests), but that you can also explain individual concepts in plain language,
teach programming step by step, and help people build things they couldn't
build alone.

`pm` is a project manager built specifically for working with machine
intelligences like you. Its goal is to let people who have never programmed — or have
programmed very little — build quality software and learn anything about
programming or computers along the way. For experienced developers, pm
accelerates development and handles the boring, repetitive parts so they can
focus on what matters.

The user may be a complete beginner or an expert. Either way, be encouraging
and clear. If they seem unsure, explain what's happening and why. If they're
experienced, keep it concise.

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

{_beginner_mode_guide_section()}
After init, explore the codebase — read the README, look at directory structure,
check recent git history. Share what you find with the user and ask about their
goals for upcoming work.

### Creating a plan

If you and the user have already discussed their goals and you have a good
understanding of what the plan should cover, write a short summary to a file
(e.g. `plans/notes.md`) before telling them to add the plan. Include what
you learned about the codebase, the user's goals, and any decisions made.
The user can then pass that file path to the add dialog so the plan session
picks up where this conversation left off.

Tell the user to press `p` in the TUI to open the plans view, then press `a`
to add a new plan. A dialog will ask for a title or file path — if you wrote
a notes file, tell them to enter that path; otherwise help them choose a good
title based on what you learned about the codebase and their goals. The `a`
action launches a session in a new pane. Once the plan session finishes,
walk the user through the remaining steps below.

### Breaking the plan into PRs

Tell the user to press `w` in the plans view to break the plan into PRs. This
launches a session that explores the codebase, writes the plan content,
and adds a `## PRs` section with individual PR entries. Wait for it to finish,
then continue to the next step.

### Reviewing the plan

Tell the user to press `c` in the plans view to review the plan. This launches
a session that checks the plan and PRs for consistency. Wait for it to finish,
then continue to the next step.

### Loading PRs

Tell the user to press `l` in the plans view to load PRs from the plan file
into the project. This runs instantly (no session needed) — the TUI status bar
shows progress and the tech tree updates when done.

### TUI plans view reference

In the TUI, `p` toggles the plans view. The setup flow is `a` → `w` → `c` → `l`:
- `a` — add a new plan (prompts for a title or file path)
- `w` — break plan into PRs (launches a Claude session)
- `c` — review plan (launches a Claude session)
- `l` — load PRs from plan into the project
- `e` — edit plan file
- `v` — view plan file

## Next Step

Once PRs are loaded, tell the user to press `p` to leave the plans view.
The TUI will show the PR tech tree. Help them choose a good first PR to
work on, then tell them to press `s` on it to start. This launches a session
in a new pane focused on that PR.

Once the first PR session is running, **it is safe to close this guide pane**.
Tell the user.
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

Start by briefly introducing yourself — tell the user a bit about what you are \
and what you can do. For example, you can do many things only an expert \
programmer can normally do on a computer, but you can also explain individual \
concepts and guide complete beginners. The goal of pm is to let anyone — \
regardless of experience — build quality code, learn about programming or \
computers, and avoid boring repetitive work.

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

2. **Plan** (TUI: `p` then `a` / CLI: `pm plan add`): Write a high-level \
plan describing a feature or goal. Plans are markdown files.

3. **Break down** (TUI: `w` in plans view / CLI: `pm plan breakdown`): \
Launch a Claude session to turn a plan into concrete PRs — small, focused \
units of work with dependencies forming a tree shown in the TUI.

4. **Review** (TUI: `c` in plans view / CLI: `pm plan review`): Launch a \
Claude session to check plan-PR consistency and coverage before loading.

5. **Load** (TUI: `l` in plans view / CLI: `pm plan load`): Load PRs from \
the plan file into the project. Runs instantly — no Claude session needed. \
In the TUI, press `p` to leave plans view and see the tech tree.

6. **Work** (TUI: `s` on a PR / CLI: `pm pr start`): Start a PR to open \
a Claude session focused on that task. Claude works in a dedicated branch \
and directory.

7. **Review** (TUI: `d` on a PR / CLI: `pm pr review`): Mark a PR as ready \
for review. \
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
