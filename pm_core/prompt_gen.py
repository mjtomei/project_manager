"""Claude prompt generation for PR work sessions."""

from pm_core import store, notes
from pm_core.backend import get_backend
from pm_core.paths import get_global_setting


def tui_section(session_name: str) -> str:
    """Build a TUI interaction section for prompts running in a tmux session.

    Used by prompt_gen internally and by other modules (guide, plan, meta)
    that construct prompts for Claude sessions running alongside the TUI.
    """
    return f"""
## Interacting with the TUI

The base pm tmux session is `{session_name}`. Use `-s {session_name}` with pm tui \
commands so they target the correct session even from workdir clones:
- `pm tui view -s {session_name}` — capture and view the current TUI screen
- `pm tui send <keys> -s {session_name}` — send keystrokes to the TUI (e.g. `pm tui send j` to move down)

**Do not** run commands that spawn new Claude sessions yourself (e.g. `pm pr start`, \
`pm pr done`, `pm plan add`, `pm plan breakdown`, `pm plan review`). These must be \
triggered through the TUI so panes are managed correctly. Use `pm tui send` to press \
the appropriate key in the TUI instead.
"""


def _format_pr_notes(pr: dict) -> str:
    """Format PR notes as a markdown section, or empty string if none."""
    pr_notes = pr.get("notes") or []
    if not pr_notes:
        return ""
    note_lines = []
    for n in pr_notes:
        ts = n.get("created_at", "")
        ts_str = f" ({ts})" if ts else ""
        note_lines.append(f"- {n['text']}{ts_str}")
    return f"\n## PR Notes\n" + "\n".join(note_lines) + "\n"


def generate_prompt(data: dict, pr_id: str, session_name: str | None = None) -> str:
    """Generate a Claude Code prompt for working on a PR.

    Args:
        data: Project data dict (from project.yaml).
        pr_id: The PR to generate a prompt for.
        session_name: If provided, include TUI interaction instructions
            targeting this tmux session.
    """
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
    base_branch = data.get("project", {}).get("base_branch", "master")

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

    tui_block = tui_section(session_name) if session_name else ""

    # Include PR notes (addendums added after work began)
    pr_notes_block = _format_pr_notes(pr)

    beginner_block = _beginner_addendum()
    cleanup_block = _auto_cleanup_addendum()

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
- This workdir is a clone managed by pm. The base pm state (project.yaml, PR status) lives in a separate directory and is not automatically synced with this clone. Commands like `pm pr start` and `pm pr review` should be run from the base directory, not here — your session for {pr_id} is already running.

## Workflow
{instructions}
{tui_block}{notes_block}{beginner_block}{cleanup_block}"""
    return prompt.strip()


def generate_review_prompt(data: dict, pr_id: str, session_name: str | None = None,
                           review_loop: bool = False,
                           review_iteration: int = 0,
                           review_loop_id: str = "") -> str:
    """Generate a Claude Code prompt for reviewing a completed PR.

    Args:
        data: Project data dict.
        pr_id: The PR identifier.
        session_name: If provided, include TUI interaction instructions.
        review_loop: When True, append fix/commit/push instructions for
            the automated review loop (``zz d`` / ``zzz d``).
        review_iteration: Current iteration number (1-based) for commit
            message tagging.  Only used when ``review_loop`` is True.
        review_loop_id: Short unique loop identifier for commit message
            tagging.  Only used when ``review_loop`` is True.
    """
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    title = pr.get("title", "")
    description = pr.get("description", "").strip()
    base_branch = data.get("project", {}).get("base_branch", "master")

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

    tui_block = tui_section(session_name) if session_name else ""

    # Include PR notes (addendums)
    pr_notes_block = _format_pr_notes(pr)

    # Backend-appropriate diff command
    backend_name = data.get("project", {}).get("backend", "vanilla")
    if backend_name == "local":
        diff_cmd = f"git diff {base_branch}...HEAD"
    else:
        diff_cmd = f"git diff origin/{base_branch}...HEAD"

    prompt = f"""You are reviewing PR {pr_id}: "{title}"

## Task
Review the code changes in this PR for quality, correctness, and architectural fit.

## Description
{description}
{pr_notes_block}{plan_context}{tui_block}
## Steps
1. Run `{diff_cmd}` to see all changes
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
6. End with an overall verdict on its own line — one of:
   - **PASS** — No changes needed. The code is ready to merge as-is.
   - **PASS_WITH_SUGGESTIONS** — Only non-blocking suggestions remain (style nits, minor refactors, optional improvements). The PR could merge now, but would benefit from small tweaks. List suggestions clearly.
   - **NEEDS_WORK** — Blocking issues found (bugs, missing error handling, architectural problems, test gaps). Separate code-quality fixes from architectural concerns.
   - **INPUT_REQUIRED** — The code looks correct but you cannot fully verify it without human-guided testing. Use this when the PR involves UI interactions, hardware-dependent behavior, environment-specific setup, or anything that requires a human to manually verify. Include specific, numbered test steps the user should perform. The user will interact with you directly in this pane to report test results, and then you should provide a final verdict."""

    base = prompt.strip()
    base += _beginner_addendum()
    if review_loop:
        base += _review_loop_addendum(pr.get("branch", ""), review_iteration,
                                      review_loop_id)
    return base


def _review_loop_addendum(branch: str, iteration: int = 0,
                          loop_id: str = "") -> str:
    """Return the review loop addendum text for fix/commit/push instructions."""
    id_label = f" [{loop_id}]" if loop_id else ""
    iteration_label = f" (iteration {iteration}){id_label}" if iteration else id_label
    id_part = f" {loop_id}" if loop_id else ""
    iter_part = f" i{iteration}" if iteration else ""
    commit_prefix = f"review-loop{id_part}{iter_part}: "
    return f"""

## Review Loop Mode{iteration_label}

This review is running in an automated loop.  After completing your review:

1. If you find issues (**NEEDS_WORK**):
   - Implement ALL the fixes you identified
   - Run any relevant tests to verify your fixes
   - Stage and commit your changes — prefix the message with `{commit_prefix}` (e.g. `{commit_prefix}fix null check, add tests`)
   - Push to the remote: `git push origin {branch}`
   - Then output your verdict: **NEEDS_WORK** with a summary of what you fixed and what may still need attention on the next iteration

2. If only non-blocking suggestions remain (**PASS_WITH_SUGGESTIONS**):
   - Implement the suggestions
   - If you made changes, commit (same `{commit_prefix}` prefix) and push
   - Output: **PASS_WITH_SUGGESTIONS** with a list of any remaining optional improvements you chose not to implement

3. If the code is ready to merge as-is (**PASS**):
   - Output: **PASS**

4. If you need the user to manually test something (**INPUT_REQUIRED**):
   - The code looks correct but requires human verification (e.g. UI behavior, environment-specific setup, hardware interaction, TUI keybindings)
   - List specific, numbered test steps the user should perform
   - Output: **INPUT_REQUIRED** — the user will respond directly in this pane with their test results
   - After receiving their feedback, provide a final verdict (PASS, PASS_WITH_SUGGESTIONS, or NEEDS_WORK)

IMPORTANT: Always end your response with the verdict keyword on its own line — one of **PASS**, **PASS_WITH_SUGGESTIONS**, **NEEDS_WORK**, or **INPUT_REQUIRED**."""


def _beginner_addendum() -> str:
    """Return beginner mode addendum if enabled, or empty string."""
    if not get_global_setting("beginner-mode"):
        return ""
    return """

## Beginner Guidance

The user has beginner mode enabled. Please:
- Explain what you're doing and why at each step
- After completing work, always recommend clear next steps
- Suggest which TUI key to press or CLI command to run next
- If something goes wrong, explain what happened in simple terms
- Avoid jargon without explanation
- When committing, explain what a commit is and why we push
"""


def _auto_cleanup_addendum() -> str:
    """Return auto-cleanup addendum if enabled, or empty string."""
    if not get_global_setting("auto-cleanup"):
        return ""
    return """

## Pane Cleanup

Auto-cleanup is enabled. After finishing your main work:
- Check for old or dead tmux panes that are no longer needed
- Suggest the user press `b` in the TUI to rebalance panes after closing panes
- Remind them they can run `pm pr cleanup <pr-id>` to remove merged PR workdirs
"""


def generate_merge_prompt(data: dict, pr_id: str, error_output: str,
                          session_name: str | None = None) -> str:
    """Generate a Claude Code prompt for resolving a merge failure.

    Args:
        data: Project data dict.
        pr_id: The PR identifier.
        error_output: Verbatim error output from the failed merge attempt.
        session_name: If provided, include TUI interaction instructions.
    """
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    branch = pr.get("branch", f"pm/{pr_id}")
    title = pr.get("title", "")
    base_branch = data.get("project", {}).get("base_branch", "master")

    tui_block = tui_section(session_name) if session_name else ""
    beginner_block = _beginner_addendum()

    prompt = f"""You're resolving a merge failure for PR {pr_id}: "{title}"

The merge of `{branch}` into `{base_branch}` failed with the following error:

```
{error_output}
```

## Steps
1. Investigate the error and resolve the issue in the workdir
2. Run any relevant tests to verify the resolution
3. Stage and commit the fix
4. When done, output **MERGED** on its own line
{tui_block}{beginner_block}"""
    return prompt.strip()


def generate_monitor_prompt(data: dict, session_name: str | None = None,
                            iteration: int = 0, loop_id: str = "") -> str:
    """Generate a Claude Code prompt for the autonomous monitor session.

    The monitor session observes auto-start and watches all active tmux
    windows for issues, attempting fixes when possible and surfacing
    problems that need human input.

    Args:
        data: Project data dict.
        session_name: If provided, include TUI interaction instructions.
        iteration: Current iteration number (1-based).
        loop_id: Short unique loop identifier.
    """
    all_prs = data.get("prs") or []
    base_branch = data.get("project", {}).get("base_branch", "master")
    project_name = data.get("project", {}).get("name", "unknown")

    # Build PR status summary
    pr_lines = []
    for pr in all_prs:
        status = pr.get("status", "pending")
        deps = pr.get("depends_on") or []
        dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
        workdir = pr.get("workdir") or ""
        workdir_str = f" [workdir: {workdir}]" if workdir else ""
        pr_lines.append(f"- {pr['id']}: {pr.get('title', '???')} [{status}]{dep_str}{workdir_str}")
    pr_summary = "\n".join(pr_lines) if pr_lines else "No PRs defined."

    # Build plan summary
    plans = data.get("plans") or []
    plan_lines = []
    for plan in plans:
        plan_lines.append(f"- {plan['id']}: {plan.get('name', '???')} [{plan.get('status', 'draft')}]")
    plan_summary = "\n".join(plan_lines) if plan_lines else "No plans defined."

    tui_block = tui_section(session_name) if session_name else ""

    id_label = f" [{loop_id}]" if loop_id else ""
    iteration_label = f" (iteration {iteration}){id_label}" if iteration else id_label

    prompt = f"""This is a session for autonomous monitoring of project "{project_name}".{iteration_label}

## Role

It is running alongside auto-start. Your job is to observe
all active tmux windows, detect problems, fix what you can automatically, and
surface what needs human attention.

## Current Project State

Base branch: `{base_branch}`

### PRs
{pr_summary}

### Plans
{plan_summary}
{tui_block}
## Your Responsibilities

### Auto-Start Overview
The PR lifecycle which auto-start walks each PR through is:
- `pending` -- Waiting for dependencies to be merged
- `in_progress` -- Implementation is in progress
- `in_review` -- Review loop is running
- `merged` -- PR merged to {base_branch}

Abnormal states to watch for:
- PR stuck in `in_progress` with idle/dead implementation pane
- PR in `in_review` with no active review loop
- PR dependencies that are stuck, blocking downstream work
- Circular or broken dependency chains

### 1. Scan Active Tmux Panes
You can use `tmux list-windows` and `tmux capture-pane` to inspect all active windows:
- Implementation windows (Sessions working on PRs)
- Review windows (Sessions reviewing PRs)
- Merge windows (Sessions resolving merge conflicts)
- The TUI itself

### 2. Auto-Fix Issues
Try to fix any issues you can without human guidance.

### 3. Surface Issues Needing Human Input
Use the **INPUT_REQUIRED** verdict for anything you can't figure out yourself.

### 4. Project Health Monitoring
Look for patterns across PRs that might signal issues in a PR's plan.
Some examples:
- Recurring test failures (same test failing in multiple PRs)
- Dependency bottlenecks (one PR blocking many others)
- PRs taking unusually long or cycling through too many review iterations
- PRs whose scope has drifted from their description
- Suggest plan changes if warranted (splitting a PR, reordering deps, etc.)

You can review plans with 'pm plan' subcommands and see what plan a PR is associated with in the project.yaml or TUI itself.

### 5. Master Branch Health Check
Monitor `{base_branch}` for:
- Gaps in the plan from an architectural perspective
- Incorrect assumptions made during planning
- Issues that merged PRs may have introduced
- Whether the remaining PR plan still makes sense given what has been merged

### 6. pm Tool Self-Monitoring
While completing the above steps, watch for:
- Bugs in the pm tool itself (unexpected errors, wrong behavior)
- Potential improvements to the pm tool

Append bugs to `pm/bugs.txt` (create if needed) and improvements to `pm/improvements.txt`.
Writing to these files should not block your next iteration. Only use **INPUT_REQUIRED** if a bug is actively blocking progress and cannot be worked around.

## Debug Log

The pm debug log is at `~/.pm/debug/`. Use `tail` to inspect recent entries:
```
tail -100 ~/.pm/debug/*.log
```

## How to Inspect Panes

```bash
# List all windows in the pm session
tmux list-windows -t <session-name>

# Capture content of a specific pane
tmux capture-pane -p -t <pane-id>

# Capture with full scrollback
tmux capture-pane -p -t <pane-id> -S -

# List panes in a window
tmux list-panes -t <session>:<window>
```

## Iteration Protocol

1. Perform all monitoring checks described above
2. Take corrective actions for issues that don't need human input
3. Compile a brief summary of findings
4. End with a verdict on its own line:
   - **READY** -- All issues handled (or no issues found). The monitor will wait and then run another iteration.
   - **INPUT_REQUIRED** -- You need human input or want to surface an important finding. Describe what you need clearly. The user will interact with you in this pane, and then you should provide a follow-up verdict (**READY** to continue monitoring).

IMPORTANT: Always end your response with the verdict keyword on its own line -- either **READY** or **INPUT_REQUIRED**."""

    return prompt.strip()


def generate_review_loop_prompt(data: dict, pr_id: str) -> str:
    """Generate a review prompt for the automated review loop.

    Wraps the normal review prompt with instructions to implement fixes,
    commit, and push before reporting the verdict.  This is used by the
    review loop (``zz d`` / ``zzz d``) where Claude iterates until PASS.
    """
    return generate_review_prompt(data, pr_id, review_loop=True)
