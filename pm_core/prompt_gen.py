"""Claude prompt generation for PR work sessions."""

from pm_core import store, notes
from pm_core.backend import get_backend
from pm_core.paths import get_global_setting
from pm_core.spec_gen import (format_spec_for_prompt, spec_generation_preamble,
                               get_spec_mocks_section)


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


def _format_pr_notes(pr: dict, workdir: str | None = None) -> str:
    """Format PR notes as a markdown section, or empty string if none.

    Merges notes from the main project.yaml and the workdir project.yaml
    (if present).  Deduplicates by note ID, preferring whichever copy has
    the later ``last_edited`` timestamp.  The merged list is sorted by
    ``created_at``.
    """
    main_notes = list(pr.get("notes") or [])

    # Collect notes from the workdir project.yaml, if available.
    workdir_notes: list[dict] = []
    if workdir:
        try:
            wd_root = store.find_project_root(start=workdir)
            wd_data = store.load(wd_root, validate=False)
            wd_pr = store.get_pr(wd_data, pr["id"])
            if wd_pr:
                workdir_notes = list(wd_pr.get("notes") or [])
        except Exception:
            pass  # graceful degradation — use main notes only

    # Merge: index by note ID, prefer later last_edited on collision.
    merged: dict[str, dict] = {}
    for n in main_notes + workdir_notes:
        nid = n.get("id")
        if nid is None:
            # Notes without an ID can't be deduped; give them a unique key.
            merged[id(n)] = n
            continue
        existing = merged.get(nid)
        if existing is None:
            merged[nid] = n
        else:
            new_ts = n.get("last_edited") or n.get("created_at", "")
            old_ts = existing.get("last_edited") or existing.get("created_at", "")
            if new_ts > old_ts:
                merged[nid] = n

    all_notes = sorted(merged.values(), key=lambda n: n.get("created_at", ""))
    if not all_notes:
        return ""
    note_lines = []
    for n in all_notes:
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
    general_notes_block = ""
    impl_specific_block = ""
    root = None
    try:
        root = store.find_project_root()
        general_notes_block, impl_specific_block = notes.notes_for_prompt(root, "impl")
    except FileNotFoundError:
        pass

    tui_block = tui_section(session_name) if session_name else ""

    # Include PR notes (addendums added after work began)
    pr_notes_block = _format_pr_notes(pr, workdir=pr.get("workdir"))

    beginner_block = _beginner_addendum()
    cleanup_block = _auto_cleanup_addendum()

    # Include implementation spec if already generated, or preamble to generate one
    impl_spec_block = format_spec_for_prompt(pr, "impl")
    impl_spec_preamble = spec_generation_preamble(pr, "impl", root=root)

    prompt = f"""You're working on PR {pr_id}: "{title}"

This session is managed by `pm`. Run `pm help` to see available commands.

## Context
{f'Part of plan "{plan["name"]}" ({plan["id"]}).' if plan else 'Standalone PR (not part of a plan).'}
{deps_section}

## Task
{description}
{pr_notes_block}{impl_spec_block}{impl_spec_preamble}
## Tips
- This session may be resuming after a restart. Check `git status` and `git log` to see if previous work exists on this branch — if so, continue from there. The directory may contain uncommitted implementation work from a previous session.
- Before referencing existing code (imports, function calls, class usage), read the source to verify the interface.
- This workdir is a clone managed by pm. The base pm state (project.yaml, PR status) lives in a separate directory and is not automatically synced with this clone. Commands like `pm pr start` and `pm pr review` should be run from the base directory, not here — your session for {pr_id} is already running.
{_remote_sync_tip(data, branch)}
{_base_branch_sync_tip(data, base_branch)}

## Workflow
{instructions}
{tui_block}{general_notes_block}{impl_specific_block}{beginner_block}{cleanup_block}"""
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

    # Include session notes if available
    general_notes_block = ""
    review_specific_block = ""
    try:
        root = store.find_project_root()
        general_notes_block, review_specific_block = notes.notes_for_prompt(root, "review")
    except FileNotFoundError:
        pass

    # Include PR notes (addendums)
    pr_notes_block = _format_pr_notes(pr, workdir=pr.get("workdir"))

    # Backend-appropriate diff and sync commands
    backend_name = data.get("project", {}).get("backend", "vanilla")
    branch = pr.get("branch", f"pm/{pr_id}")
    if backend_name == "local":
        diff_cmd = f"git diff {base_branch}...HEAD"
        pull_step = ""
    else:
        diff_cmd = f"git diff origin/{base_branch}...HEAD"
        pull_step = (
            f"1. Pull the latest changes from remote: `git pull origin {branch}`. "
            f"Resolve any merge conflicts before continuing.\n"
        )

    # Renumber steps based on whether pull step is present
    n = 2 if pull_step else 1

    # Include implementation spec in review prompt for context.
    # If no spec exists, warn the reviewer — the implementation session
    # should have generated one in Step 0.
    impl_spec_block = format_spec_for_prompt(pr, "impl")
    if not impl_spec_block:
        impl_spec_block = """
## Implementation Spec — MISSING

No implementation spec was generated for this PR.  The implementation session
should have produced one as Step 0.  Without a spec, the reviewer cannot
verify that the implementation matches an agreed-upon set of requirements.

**Action**: If the implementation is otherwise sound, generate the spec now
with `pm pr spec {pr_id} impl` so it is available for QA.  If the
implementation has significant gaps, consider requesting re-implementation
with spec generation enabled.
""".replace("{pr_id}", pr_id)

    prompt = f"""You are reviewing PR {pr_id}: "{title}"

## Task
Review the code changes in this PR for quality, correctness, and architectural fit.

## Description
{description}
{pr_notes_block}{impl_spec_block}{plan_context}{tui_block}{general_notes_block}
## Steps
{pull_step}{n}. Run `{diff_cmd}` to see all changes
{n+1}. **Generic checks** — things any codebase should get right:
   - Excessive file/function length, duplicated code, dead or unnecessary code, potential bugs, security issues, confusing code that lacks comments, sufficient test coverage
{n+2}. **Project-specific checks** — does the change fit this codebase?
   - Convention consistency, architectural patterns
   - Search for similar code elsewhere in the repo — flag opportunities for shared helpers or reuse
{n+3}. **Architectural review** — does the implementation approach make sense?
   - Were the PR's goals achieved in a reasonable way, or is there a simpler/better design?
   - If plan context is listed above, check whether choices in this PR make any of those sibling PRs harder to implement. Are there data models, interfaces, or patterns introduced here that will need awkward workarounds later?
   - Run `pm pr list` to see all PRs and plans for the repo. If any other plans or standalone PRs touch related areas, consider whether this PR's approach conflicts with or complicates them.
   - Consider likely future changes beyond the current PR list — does this PR paint the codebase into a corner or leave good extension points?
{n+4}. Output per-file notes: **filename** — GOOD / FIX / RETHINK
{n+5}. End with an overall verdict on its own line — one of:
   - **PASS** — No changes needed. The code is ready to merge as-is.
   - **PASS_WITH_SUGGESTIONS** — Only non-blocking suggestions remain (style nits, minor refactors, optional improvements). The PR could merge now, but would benefit from small tweaks. List suggestions clearly.
   - **NEEDS_WORK** — Blocking issues found (bugs, missing error handling, architectural problems, test gaps). Separate code-quality fixes from architectural concerns.
   - **INPUT_REQUIRED** — Reserved for genuine ambiguities in the PR spec or architectural decisions that need human judgment. Do NOT use this for manual testing — QA handles testing separately. Include specific questions that need the user's decision."""

    base = prompt.strip()
    base += review_specific_block
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

4. If you have a genuine question requiring human judgment (**INPUT_REQUIRED**):
   - Reserved for genuine ambiguities in the PR spec or architectural decisions that need human judgment
   - Do NOT use this for manual testing — QA handles testing separately
   - Include specific questions that need the user's decision
   - Output: **INPUT_REQUIRED** — the user will respond directly in this pane

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


def _remote_sync_tip(data: dict, branch: str) -> str:
    """Return a tip about pulling from remote, or empty string for local backend."""
    backend_name = data.get("project", {}).get("backend", "vanilla")
    if backend_name == "local":
        return ""
    return (
        f"- Pull from remote before starting work to pick up changes from "
        f"other sessions or machines: `git pull origin {branch}`. "
        f"If there are merge conflicts, resolve them before continuing."
    )


def _base_branch_sync_tip(data: dict, base_branch: str) -> str:
    """Return a tip about pulling the base branch, or empty string for local backend."""
    backend_name = data.get("project", {}).get("backend", "vanilla")
    if backend_name == "local":
        return ""
    return (
        f"- Pull the latest `{base_branch}` and merge it into your branch so you're "
        f"building on up-to-date code: "
        f"`git fetch origin {base_branch} && git merge origin/{base_branch}`. "
        f"Resolve any conflicts before continuing."
    )


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
                          session_name: str | None = None,
                          pull_from_workdir: str | None = None,
                          pull_from_origin: bool = False) -> str:
    """Generate a Claude Code prompt for resolving a merge failure.

    Args:
        data: Project data dict.
        pr_id: The PR identifier.
        error_output: Verbatim error output from the failed merge attempt.
        session_name: If provided, include TUI interaction instructions.
        pull_from_workdir: When set, this is a pull-from-workdir failure
            (local backend).  The value is the workdir path that contains
            the already-merged base branch.  The merge window runs in the
            *repo dir* and needs to pull/integrate from the workdir.
        pull_from_origin: When True, this is a pull-from-origin failure
            (vanilla/github backend).  The merge window runs in the
            *repo dir* and needs to pull origin into the local checkout.
    """
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    branch = pr.get("branch", f"pm/{pr_id}")
    title = pr.get("title", "")
    workdir = pr.get("workdir", "")
    base_branch = data.get("project", {}).get("base_branch", "master")

    backend = data.get("project", {}).get("backend", "vanilla")
    repo_url = data.get("project", {}).get("repo", "")

    tui_block = tui_section(session_name) if session_name else ""
    beginner_block = _beginner_addendum()

    # Include session notes if available
    general_notes_block = ""
    merge_specific_block = ""
    try:
        root = store.find_project_root()
        general_notes_block, merge_specific_block = notes.notes_for_prompt(root, "merge")
    except FileNotFoundError:
        pass

    # --- Pull-from-workdir variant ---
    # When this is set, the merge window is running in the *repo dir* and
    # needs to integrate the already-merged base branch from the workdir.
    if pull_from_workdir:
        prompt = f"""You're updating the local repo after a successful merge of PR {pr_id}: "{title}"

The PR branch `{branch}` has already been merged into `{base_branch}` in the workdir,
but pulling that result into the main repo directory failed:

```
{error_output}
```

## Context

You are running in the **main repo directory** (not the PR workdir).
The workdir at `{pull_from_workdir}` has the correct merged `{base_branch}`.
This repo directory needs its `{base_branch}` updated to match the workdir's.

## Steps
1. Investigate the error above and fix whatever is blocking the update
   (e.g. stash uncommitted changes, resolve diverged branches)
2. Fetch and integrate `{base_branch}` from the workdir into this repo directory
3. Restore any stashed changes
4. Verify that `{base_branch}` now contains the merge commit from the workdir
5. End with a verdict on its own line — one of:
   - **MERGED** — The repo directory is updated. Everything is done.
   - **INPUT_REQUIRED** — You need human help to resolve this.

IMPORTANT: Always end your response with the verdict keyword on its own line — either **MERGED** or **INPUT_REQUIRED**.
{tui_block}{general_notes_block}{merge_specific_block}{beginner_block}"""
        return prompt.strip()

    # --- Pull-from-origin variant (vanilla/github) ---
    if pull_from_origin:
        prompt = f"""You're updating the local repo after a successful merge of PR {pr_id}: "{title}"

The PR branch `{branch}` has already been merged and pushed to origin,
but updating the local repo directory failed:

```
{error_output}
```

## Context

You are running in the **main repo directory** (`{repo_url}`), not the PR workdir.
Origin already has the correct merged `{base_branch}`.
This local checkout needs its `{base_branch}` updated to match origin.

## Steps
1. Investigate the error above and fix whatever is blocking the update
   (e.g. stash uncommitted changes, resolve diverged branches)
2. Pull `{base_branch}` from origin into this repo directory
3. Restore any stashed changes
4. Verify that `{base_branch}` is now up to date with origin
5. End with a verdict on its own line — one of:
   - **MERGED** — The repo directory is updated. Everything is done.
   - **INPUT_REQUIRED** — You need human help to resolve this.

IMPORTANT: Always end your response with the verdict keyword on its own line — either **MERGED** or **INPUT_REQUIRED**.
{tui_block}{general_notes_block}{merge_specific_block}{beginner_block}"""
        return prompt.strip()

    # --- Standard merge-conflict variant ---
    if backend == "local":
        backend_block = f"""
## Repository Setup (local backend)

This is a **local-only** git project — origin points to a local directory (`{repo_url}`),
not a remote server.  The origin repo is non-bare with `{base_branch}` checked out, so
pushing to origin will be rejected.

Resolve the conflict and commit the merge on `{base_branch}` in this workdir.
"""
    elif backend == "github":
        backend_block = f"""
## Repository Setup (GitHub backend)

This project is hosted on GitHub.

After resolving the conflict, push the merged `{base_branch}` to origin.
"""
    else:
        backend_block = f"""
## Repository Setup (vanilla git backend)

This project uses a remote git server.

After resolving the conflict, push the merged `{base_branch}` to origin.
"""

    if backend == "local":
        merged_desc = f"The conflict is resolved and the merge is committed on `{base_branch}` in this workdir."
        steps_block = f"""## Steps
1. Investigate the error and resolve the issue in the workdir
2. Complete the merge: ensure `{base_branch}` includes changes from `{branch}`
3. Run any relevant tests to verify the resolution
4. End with a verdict on its own line — one of:"""
    else:
        merged_desc = f"The conflict is resolved, merged, and pushed to origin."
        steps_block = f"""## Steps
1. Investigate the error and resolve the issue in the workdir
2. Complete the merge: ensure `{base_branch}` includes changes from `{branch}`
3. Run any relevant tests to verify the resolution
4. Push the merged `{base_branch}` to origin
5. End with a verdict on its own line — one of:"""

    prompt = f"""You're resolving a merge failure for PR {pr_id}: "{title}"

The merge of `{branch}` into `{base_branch}` failed with the following error:

```
{error_output}
```
{backend_block}
## Goal

Resolve the merge conflict so that `{base_branch}` contains the merged result of both branches.

{steps_block}
   - **MERGED** — {merged_desc}
   - **INPUT_REQUIRED** — You cannot resolve the conflict automatically and need human help.
     Describe what you need clearly: which files conflict, what the competing changes are,
     and what decision the user needs to make. The user will interact with you directly in
     this pane, and then you should resolve and provide a final **MERGED** verdict.

IMPORTANT: Do NOT report MERGED until ALL steps above are complete. Always end your response with the verdict keyword on its own line — either **MERGED** or **INPUT_REQUIRED**.
{tui_block}{general_notes_block}{merge_specific_block}{beginner_block}"""
    return prompt.strip()


def generate_watcher_prompt(data: dict, session_name: str | None = None,
                            iteration: int = 0, loop_id: str = "",
                            auto_start_target: str | None = None,
                            meta_pm_root: str | None = None) -> str:
    """Generate a Claude Code prompt for the autonomous watcher session.

    The watcher session observes auto-start and watches all active tmux
    windows for issues, attempting fixes when possible and surfacing
    problems that need human input.

    INPUT_REQUIRED semantics: the watcher uses INPUT_REQUIRED only for
    *project-wide* blockers (broken base branch, plan contradictions,
    infrastructure failures, or a genuinely stuck ``in_progress`` branch
    with no active review/QA loop).  If a branch is paused by its own
    review or QA loop's INPUT_REQUIRED, the watcher should note it in the
    summary but emit READY — the loop already handles that branch, and
    escalating would block all other branches unnecessarily.

    Args:
        data: Project data dict.
        session_name: If provided, include TUI interaction instructions.
        iteration: Current iteration number (1-based).
        loop_id: Short unique loop identifier.
        meta_pm_root: Absolute path to the meta workdir's ``pm/`` directory
            where bugs.md and improvements.md live.
        auto_start_target: The PR that auto-start is targeting. When set,
            the monitor should only intervene on PRs in this PR's
            transitive dependency fan-in.
    """
    if not meta_pm_root:
        meta_pm_root = "pm"  # fallback to relative path

    all_prs = data.get("prs") or []
    base_branch = data.get("project", {}).get("base_branch", "master")
    project_name = data.get("project", {}).get("name", "unknown")

    tui_block = tui_section(session_name) if session_name else ""

    # Include session notes if available
    general_notes_block = ""
    watcher_specific_block = ""
    try:
        root = store.find_project_root()
        general_notes_block, watcher_specific_block = notes.notes_for_prompt(root, "watcher")
    except FileNotFoundError:
        pass

    # Compute auto-start scope (dependency fan-in of the target)
    auto_start_scope_block = ""
    if auto_start_target:
        from pm_core.tui.auto_start import _transitive_deps
        managed_ids = _transitive_deps(all_prs, auto_start_target)
        managed_ids.add(auto_start_target)
        managed_list = ", ".join(sorted(managed_ids))

        auto_start_scope_block = f"""
### Auto-Start Scope

Auto-start target: **{auto_start_target}**
Managed PRs (target + its transitive dependencies): {managed_list}

**IMPORTANT**: Only PRs in the managed set above are part of the auto-start pipeline.
Other PRs may have active tmux windows from manual user activity -- do NOT attempt to
fix, restart, or interfere with those sessions. You may observe them for cross-session
conflict detection (e.g. overlapping file edits), but take no corrective action on
windows belonging to unmanaged PRs.
"""

    id_label = f" [{loop_id}]" if loop_id else ""
    iteration_label = f" (iteration {iteration}){id_label}" if iteration else id_label

    prompt = f"""This is a session for autonomous monitoring of project "{project_name}".{iteration_label}

## Role

It is running alongside auto-start. Your job is to observe
all active tmux windows, detect problems, fix what you can automatically, and
surface what needs human attention.

## Current Project State

Base branch: `{base_branch}`

Use these commands to inspect project state as needed:
- `pm pr list` -- list all PRs and their status
- `pm pr graph` -- show the PR dependency tree
- `pm plan list` -- list all plans
- `cat pm/project.yaml` -- full project state (PRs, plans, settings)
{tui_block}{general_notes_block}
## Your Responsibilities

### Auto-Start Overview

Auto-start manages the full PR lifecycle automatically. Understanding the
mechanics will help you distinguish normal operation from genuine problems.

**Lifecycle stages:**
- `pending` -- Waiting for dependencies to be merged. Auto-start picks up
  PRs whose dependencies are all `merged` and runs `pm pr start`.
- `in_progress` -- A Claude implementation session is running in a tmux window.
- `in_review` -- A review loop is running (iterates until PASS/PASS_WITH_SUGGESTIONS).
- `qa` -- QA testing is running. QA scenarios execute in parallel; if they find
  issues and commit fixes, the PR returns to `in_review` for another review cycle.
- `merged` -- PR merged to `{base_branch}`. Auto-start then checks for newly-unblocked dependents.

**How transitions work:**
- **pending -> in_progress**: Auto-start detects all deps are merged and launches
  an implementation window. This happens quickly after a dependency merges.
- **in_progress -> in_review**: The TUI polls the implementation pane every ~5 seconds,
  hashing the visible content. When the content stops changing for ~30 seconds, the TUI
  considers the implementation "idle" (done) and automatically transitions to `in_review`,
  launching a review loop. **This means there is a normal ~30 second delay between Claude
  finishing its work and the review starting.** During this window, the pane will appear
  idle but the transition has not happened yet -- this is expected, not a problem.
- **in_review -> qa**: When the review loop reaches a PASS or PASS_WITH_SUGGESTIONS
  verdict, auto-start transitions the PR to `qa` and launches QA scenarios.
- **qa -> merged**: When QA passes with no changes, auto-start runs `pm pr merge`.
  If QA finds issues or commits fixes, the PR returns to `in_review` for re-review.
- **in_review/qa -> merged (merge conflicts)**: If the merge has conflicts, a
  merge-resolution Claude window opens; once that finishes (also detected via idle
  polling), the merge is re-attempted.

Note: `d` in the TUI starts a single one-shot review. To start a review **loop** (which
auto-start uses), the TUI chord is `zzz d`. If you need to manually kick off a review
loop for a PR, use `pm tui send` to send `zzz d` while the PR is selected.

**Normal things that look like problems (but aren't):**
- An `in_progress` PR whose pane has been static for < 60 seconds -- idle detection
  hasn't fired yet, this is the normal transition window.
- A PR that just transitioned to `in_review` but has no review window yet -- the review
  loop is being launched, give it a few seconds.
- A review loop showing multiple iterations (⟳N in the TUI) -- this is normal, the loop
  iterates until PASS.

**Abnormal states that DO need attention:**
- PR stuck in `in_progress` with idle/dead implementation pane for several minutes
- PR in `in_review` with no active review loop and no recent review activity
- PR dependencies that are stuck, blocking downstream work
- Circular or broken dependency chains
- Implementation pane showing an error/crash rather than completed work

**States that are handled and do NOT need watcher INPUT_REQUIRED:**
- PR in `in_review` or `qa` whose review/QA loop pane ends with `INPUT_REQUIRED` — the
  loop is already pausing that branch and the user has been notified. Note it in your
  summary but emit **READY**, not INPUT_REQUIRED. Even if multiple branches are
  simultaneously paused by their own loops, each loop is handling its own branch; the
  watcher should still emit READY so other branches can continue.
  (Exception: the PR is `in_review` but has **no** active review loop window — that is
  the abnormal state above and does warrant attention.)
{auto_start_scope_block}
### 1. Scan Active Tmux Panes
You can use `tmux list-windows` and `tmux capture-pane` to inspect all active windows:
- Implementation windows (Sessions working on PRs)
- Review windows (Sessions reviewing PRs)
- Merge windows (Sessions resolving merge conflicts)
- The TUI itself

### 2. Auto-Fix Issues
Try to fix any issues you can without human guidance.

### 3. Surface Issues Needing Human Input
Distinguish between **project-wide blockers** and **branch-specific issues already handled**.

**Use INPUT_REQUIRED for project-wide blockers:**
- Broken base branch that affects all downstream work
- Plan contradictions or fundamental architectural issues
- Infrastructure failures (git remote unreachable, disk full, etc.)
- An `in_progress` branch that is genuinely stuck (idle/dead pane for several minutes)
  with no active review or QA loop handling it

**Use READY (not INPUT_REQUIRED) when a branch-specific issue is already handled:**
- If a branch's review loop or QA loop pane ends with `INPUT_REQUIRED` (at the time of
  your observation), that loop is already pausing the branch and notifying the user.
  The watcher escalating to INPUT_REQUIRED would block **all** branches unnecessarily.
  Instead, note the situation in your summary and emit READY.
- This applies even when multiple branches are simultaneously paused by their own loops.

To check whether a review or QA loop is waiting for input: capture the relevant tmux pane and see if its last meaningful output ends with `INPUT_REQUIRED`. If the loop pane ends with `INPUT_REQUIRED`, the loop is handling it. If the PR is `in_review` but has **no** active review loop window at all, that is a different (abnormal) state — see above.

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

Append findings to `{meta_pm_root}/bugs.md` and `{meta_pm_root}/improvements.md` using the plan-compatible PR format:

```
### PR: Short title describing the fix/improvement
- **description**: What needs to be done
- **tests**: Tests that reproduce the bug or verify the improvement
- **files**: Key files involved
```

These files are plans that the user can review and act on later via meta mode.
Do NOT launch `pm meta` or attempt to fix pm itself — just document what you find.

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
   - **READY** -- All issues handled (or no issues found). The monitor will wait and then run another iteration. This is also correct when some branches are individually paused by their own review/QA loops — those loops handle their branches; the watcher does not need to escalate.
   - **INPUT_REQUIRED** -- A **project-wide** blocker exists (broken base branch, plan contradiction, infrastructure failure) or a branch is genuinely stuck with no active review/QA loop handling it. Describe what you need clearly. The user will interact with you in this pane, and then you should provide a follow-up verdict (**READY** to continue monitoring).

IMPORTANT: Always end your response with the verdict keyword on its own line -- either **READY** or **INPUT_REQUIRED**.{watcher_specific_block}"""

    return prompt.strip()


def generate_review_loop_prompt(data: dict, pr_id: str) -> str:
    """Generate a review prompt for the automated review loop.

    Wraps the normal review prompt with instructions to implement fixes,
    commit, and push before reporting the verdict.  This is used by the
    review loop (``zz d`` / ``zzz d``) where Claude iterates until PASS.
    """
    return generate_review_prompt(data, pr_id, review_loop=True)


# ---------------------------------------------------------------------------
# QA prompts
# ---------------------------------------------------------------------------


def _worker_group_field(worker_count: int) -> str:
    """Return the GROUP field line for the planner output format."""
    if worker_count == 0:
        return ""
    if worker_count < 0:
        return "\nGROUP: <worker group number, starting from 1>"
    return f"\nGROUP: <worker group number, 1 to {worker_count}>"


def _worker_grouping_instructions(worker_count: int) -> str:
    """Return instructions for the planner to group scenarios into workers."""
    if worker_count == 0:
        return ""
    if worker_count < 0:
        # Planner decides grouping
        return """
## Worker Grouping

Scenarios will be batched into worker sessions.  Each worker executes its
assigned scenarios sequentially, sharing diff review and file loading.

Assign each scenario a GROUP number (starting from 1). Group scenarios that 
share functional area or related files together.
"""
    return f"""
## Worker Grouping

Scenarios will be batched into worker sessions.  Each worker executes its
assigned scenarios sequentially, sharing diff review and file loading.

Assign each scenario a GROUP number.  Use up to {worker_count} groups.
Group scenarios that share functional area or related files together.
"""


def generate_qa_planner_prompt(data: dict, pr_id: str,
                               session_name: str | None = None,
                               scenario_start: int = 1,
                               worker_count: int = 0) -> str:
    """Generate a prompt for the QA planning session.

    The planner analyzes the PR and the instruction library to generate
    a structured QA plan with test scenarios.

    When *worker_count* != 0, the prompt asks the planner to assign each
    scenario to a worker group.  -1 lets the planner decide how many groups;
    >0 fixes the number of groups.
    """
    from pm_core import qa_instructions

    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    title = pr.get("title", "")
    description = pr.get("description", "").strip()
    branch = pr.get("branch", f"pm/{pr_id}")
    workdir = pr.get("workdir", "")
    base_branch = data.get("project", {}).get("base_branch", "master")

    # Get instruction library summary, mocks library, and notes
    library_summary = "No instruction library found."
    mocks_summary = ""
    general_notes_block = ""
    qa_specific_block = ""
    root = None
    try:
        root = store.find_project_root()
        library_summary = qa_instructions.instruction_summary_for_prompt(root)
        mocks_list = qa_instructions.list_mocks(root)
        if mocks_list:
            mocks_lines = []
            for m in mocks_list:
                desc = f" — {m['description']}" if m["description"] else ""
                mocks_lines.append(f"- **{m['id']}**{desc}")
            mocks_summary = "\n".join(mocks_lines)
        general_notes_block, qa_specific_block = notes.notes_for_prompt(root, "qa")
    except FileNotFoundError:
        pass

    # Include PR notes (prior QA results, addendums)
    pr_notes_block = _format_pr_notes(pr, workdir=pr.get("workdir"))

    # Include QA spec if already generated, or preamble to generate one
    qa_spec_block = format_spec_for_prompt(pr, "qa")
    qa_spec_preamble = spec_generation_preamble(pr, "qa", root=root)

    mocks_library_section = ""
    if mocks_summary:
        mocks_library_section = f"""
## Mock Library

These shared mock definitions are available.  Reference them by ID in each
scenario's MOCKS field.  Each mock is injected into the scenario prompt so
all agents share the same contracts.

{mocks_summary}

If a scenario needs to mock an external dependency that is NOT listed above,
declare it as a NEW_MOCK before the scenarios so it can be generated first.
"""
    else:
        mocks_library_section = """
## Mock Library

No shared mocks are defined yet.  If any scenarios need to mock external
dependencies (Claude sessions, git operations, tmux, network calls, etc.),
declare them as NEW_MOCK blocks before the scenarios.
"""

    prompt = f"""You are a QA planner analyzing PR {pr_id}: "{title}"

## Task

Analyze this PR's changes and the available QA instruction library to generate
a structured test plan.  Your goal is to identify the most important scenarios
to verify this PR works correctly.

## PR Context

- **Title**: {title}
- **Description**: {description}
- **Branch**: {branch}
- **Base branch**: {base_branch}
- **Workdir**: {workdir}

Inspect the diff yourself — run `git diff {base_branch}...HEAD` in the workdir
to see what changed.  Read source files as needed to understand the context.
{pr_notes_block}{qa_spec_block}{qa_spec_preamble}
## QA Instruction Library

These are available QA instructions.  Reference any that are relevant to
this PR's changes.  You can read the full content of any instruction file
at the paths shown below.

{library_summary}

Instructions tell scenario agents how to set up a test environment.  Without
one, agents fall back to reading code and auto-passing.  Try to assign an instruction
to every scenario.
{mocks_library_section}
## Output Format

Your output is machine-parsed.  Use ALL CAPS markers exactly as shown.
Do NOT use markdown headings or code fences — output the plain-text markers
directly at the start of a line.

First declare any new mocks needed (omit this section if all needed mocks
already exist in the Mock Library above):

NEW_MOCK: <mock-id e.g. "claude-session">
DEPENDENCY: <the external system being mocked e.g. "Anthropic Claude API">
REASON: <why scenarios need this mocked rather than real>

Then list the scenarios:

QA_PLAN_START

SCENARIO {scenario_start}: <descriptive title for this scenario>
FOCUS: <what area or behavior to test>
INSTRUCTION: <filename from the library above, or "none" if no existing instruction applies>
MOCKS: <comma-separated mock IDs this scenario uses, or "none">{_worker_group_field(worker_count)}
STEPS: <concrete test steps to perform>

SCENARIO {scenario_start + 1}: <descriptive title for next scenario>
FOCUS: <what area or behavior to test>
INSTRUCTION: <filename or "none">
MOCKS: <mock IDs or "none">{_worker_group_field(worker_count)}
STEPS: <concrete test steps>

QA_PLAN_END

Number scenarios starting from {scenario_start}.

Include as many scenarios as required to fully exercise the functionality
of the PR.  Exercise the core functionality as well as any edge cases
that may expose bugs.
{_worker_grouping_instructions(worker_count)}
{general_notes_block}{qa_specific_block}"""
    return prompt.strip()


def generate_qa_interactive_prompt(data: dict, pr_id: str,
                                   workdir: str,
                                   session_name: str | None = None,
                                   worktree_mode: bool = False,
                                   scratch_dir: str | None = None) -> str:
    """Generate a prompt for the interactive Scenario 0 session.

    Scenario 0 is a persistent interactive Claude session where the user
    can run manual tests alongside the automated QA scenarios.
    """
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    title = pr.get("title", "")
    branch = pr.get("branch", f"pm/{pr_id}")
    pr_workdir = pr.get("workdir", "")
    base_branch = data.get("project", {}).get("base_branch", "master")

    pr_notes_block = _format_pr_notes(pr, workdir=pr.get("workdir"))

    scratch_line = f"\n- **Scratch dir** (throwaway test projects): {scratch_dir}" if scratch_dir else ""
    if worktree_mode:
        workdir_block = f"""\
- **Your workdir** (isolated worktree): {workdir}{scratch_line}
- **PR workdir** (canonical source): {pr_workdir}"""
    else:
        workdir_block = f"""\
- **PR workdir** (source code): {pr_workdir}
- **Your workdir** (throwaway test projects): {workdir}"""

    tui_block = tui_section(session_name) if session_name else ""

    # Get instruction library summary for Scenario 0 (instructions only, not regression)
    instruction_library_block = ""
    try:
        root = store.find_project_root()
        from pm_core import qa_instructions
        library_summary = qa_instructions.instruction_summary_for_prompt(root)
        if library_summary and "No QA instructions" not in library_summary:
            instruction_library_block = f"""
## QA Instruction Library

The project has user-defined QA instructions and regression tests that the
automated scenarios may be running.  You can read any of these files to
understand what's being tested:

{library_summary}
"""
    except (FileNotFoundError, Exception):
        pass

    prompt = f"""You are in an interactive QA session (Scenario 0) for PR {pr_id}: "{title}"

## Context

- **PR**: {pr_id} — "{title}"
- **Branch**: {branch}
- **Base branch**: {base_branch}
{workdir_block}
{pr_notes_block}
## How QA Works

You are in Scenario 0 — an interactive session that runs alongside automated QA
scenarios.  Here's how the overall QA process works:

1. A **QA planner** analyzed the PR and generated test scenarios based on the
   PR's changes and the project's QA instruction library
2. Each scenario runs in its **own isolated clone** (parallel sessions in
   other tmux windows), with a specific focus area and test steps
3. Automated scenarios produce a **verdict** (PASS / NEEDS_WORK / INPUT_REQUIRED)
   when they finish — these are collected by the orchestrator
4. If a scenario finds issues and fixes them, it pushes directly to the PR branch
5. The overall QA result is aggregated from all scenario verdicts

You can see the other scenario windows in tmux (they're named qa-*-s1, qa-*-s2,
etc.).
{instruction_library_block}
## Your Role

This is an interactive session — you work with the user to manually test and
explore the PR's changes.

Help the user with whatever they need:
- Inspect code changes (`git diff {base_branch}...HEAD`)
- Run tests, build the project, try out features
- Debug issues found by automated scenarios
- Write and run ad-hoc test scripts in the scratch dir
- Read QA instruction files to understand what automated scenarios are testing

You do NOT need to produce a verdict.  This session stays open until QA
completes — take your time and be thorough.
{tui_block}"""
    return prompt.strip()


def generate_qa_child_prompt(data: dict, pr_id: str,
                             scenario, workdir: str,
                             session_name: str | None = None,
                             worktree_mode: bool = False,
                             scratch_dir: str | None = None) -> str:
    """Generate a prompt for a QA child session executing one scenario.

    Args:
        data: Project data dict.
        pr_id: PR identifier.
        scenario: QAScenario dataclass instance.
        workdir: Child scenario's own workdir (worktree in worktree_mode,
            or a plain directory otherwise).
        session_name: tmux session name.
        worktree_mode: When True, the child runs in an isolated clone of the
            repo and can commit/push fixes to the PR branch.
        scratch_dir: Path to a scratch directory for throwaway test projects.
    """
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    title = pr.get("title", "")
    branch = pr.get("branch", f"pm/{pr_id}")
    pr_workdir = pr.get("workdir", "")
    base_branch = data.get("project", {}).get("base_branch", "master")

    instruction_block = ""
    if scenario.instruction_path:
        # instruction_path is an absolute path from the agent's perspective
        # (set by _install_instruction_file during launch).
        instr_display = scenario.instruction_path
        instruction_block = f"""
## Instruction Reference

Test setup instructions are available at: `{instr_display}`

If a setup step fails or a required tool is unavailable, report
**INPUT_REQUIRED** with an explanation of what blocked you. 
"""

    # Include PR notes (prior QA results, addendums)
    pr_notes_block = _format_pr_notes(pr, workdir=pr.get("workdir"))

    # Include mocks section from QA spec so every scenario uses the same strategy
    mocks_block = get_spec_mocks_section(pr)

    # Workdir description and execution instructions differ by mode
    backend_name = data.get("project", {}).get("backend", "vanilla")
    has_remote = backend_name != "local"
    pull_step = (
        f"1. Pull the latest changes from remote: `git pull origin {branch}`. "
        f"Resolve any merge conflicts before continuing.\n"
    ) if has_remote else ""
    n = 2 if has_remote else 1  # first step number after optional pull

    scratch_line = f"\n- **Scratch dir** (throwaway test projects): {scratch_dir}" if scratch_dir else ""
    if worktree_mode:
        workdir_block = f"""\
- **Your workdir** (isolated clone): {workdir}{scratch_line}
- **PR workdir** (canonical source): {pr_workdir}"""
        execution_block = f"""\
{pull_step}{n}. Execute the test steps described above
{n+1}. If you find issues and can fix them:
   - Implement the fix in your workdir (your current directory)
   - Commit with message prefix `qa: `
   - Push: `git push origin {branch}`
   - If push fails (another scenario pushed first), pull and retry:
     `git pull --rebase origin {branch} && git push origin {branch}`
{n+2}. End with a verdict on its own line — one of:
   - **PASS** — Scenario passed, no issues found
   - **NEEDS_WORK** — Issues found and fixed (the fix is committed and pushed)
   - **INPUT_REQUIRED** — Issues found that you could not fix, or genuine ambiguity requiring human judgment"""
    else:
        workdir_block = f"""\
- **PR workdir** (source code): {pr_workdir}
- **Your workdir** (throwaway test projects): {workdir}"""
        execution_block = f"""\
{pull_step}{n}. Execute the test steps described above
{n+1}. If you find issues and can fix them:
   - Implement the fix in the PR workdir
   - Commit with message prefix `qa: `
   - Push: `git push origin {branch}`
{n+2}. End with a verdict on its own line — one of:
   - **PASS** — Scenario passed, no issues found
   - **NEEDS_WORK** — Issues found and fixed (the fix is committed and pushed)
   - **INPUT_REQUIRED** — Issues found that you could not fix, or genuine ambiguity requiring human judgment"""

    prompt = f"""You are running QA scenario {scenario.index}: "{scenario.title}"

## Context

- **PR**: {pr_id} — "{title}"
- **Branch**: {branch}
- **Base branch**: {base_branch}
{workdir_block}
{pr_notes_block}{mocks_block}
## How QA Works

You are in one of several QA scenarios running in parallel, each in its own
isolated clone.  An orchestrator is monitoring your tmux pane for your
final verdict.

## Important: When to use each verdict

- **PASS** — You executed the test steps AND they succeeded.  A PASS is
  only valid when you have **runtime evidence** (command output, observed
  behavior, test results) that the feature works.
- **NEEDS_WORK** — You executed the test steps and found concrete bugs or
  issues.
- **INPUT_REQUIRED** — You **could not execute** one or more test steps
  because of missing tools, unavailable commands, environment limitations,
  or ambiguity in the instructions.  **This is the correct verdict when
  your environment prevents you from testing** — do NOT substitute code
  reading or unit tests and claim PASS.  Explain what blocked you.

## Scenario

**Focus**: {scenario.focus}

**Steps**:
{scenario.steps}
{instruction_block}
## Execution

{execution_block}

IMPORTANT: Always end your response with the verdict keyword on its own line."""
    return prompt.strip()


def generate_qa_worker_prompt(data: dict, pr_id: str,
                              scenarios: list,
                              worker_index: int,
                              workdir: str,
                              qa_workdir: str,
                              session_name: str | None = None,
                              worktree_mode: bool = False,
                              scratch_dir: str | None = None) -> str:
    """Generate a prompt for a batched QA worker session.

    A worker executes multiple scenarios sequentially in a single session,
    sharing diff review and file loading across scenarios.

    Args:
        data: Project data dict.
        pr_id: PR identifier.
        scenarios: List of QAScenario objects assigned to this worker.
        worker_index: 1-based worker index.
        workdir: Worker's workdir (clone path).
        qa_workdir: QA session workdir (for report files).
        session_name: tmux session name.
        worktree_mode: When True, the worker runs in an isolated clone.
        scratch_dir: Path to a scratch directory for throwaway test projects.
    """
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")

    title = pr.get("title", "")
    branch = pr.get("branch", f"pm/{pr_id}")
    pr_workdir = pr.get("workdir", "")
    base_branch = data.get("project", {}).get("base_branch", "master")

    # Include PR notes and mocks
    pr_notes_block = _format_pr_notes(pr, workdir=pr.get("workdir"))
    mocks_block = get_spec_mocks_section(pr)

    # Workdir description
    backend_name = data.get("project", {}).get("backend", "vanilla")
    has_remote = backend_name != "local"

    scratch_line = f"\n- **Scratch dir** (throwaway test projects): {scratch_dir}" if scratch_dir else ""
    if worktree_mode:
        workdir_block = f"""\
- **Your workdir** (isolated clone): {workdir}{scratch_line}
- **PR workdir** (canonical source): {pr_workdir}"""
    else:
        workdir_block = f"""\
- **PR workdir** (source code): {pr_workdir}
- **Your workdir** (throwaway test projects): {workdir}"""

    # Build scenario list
    scenario_blocks = []
    for sc in scenarios:
        report_path = f"{qa_workdir}/report-s{sc.index}.md"
        scenario_blocks.append(f"""### Scenario {sc.index}: {sc.title}

**Focus**: {sc.focus}

**Steps**:
{sc.steps}

**Report file**: `{report_path}`""")

    scenarios_text = "\n\n".join(scenario_blocks)
    scenario_indices = ", ".join(str(sc.index) for sc in scenarios)

    # Push instructions
    pull_step = (
        f"- Pull the latest changes: `git pull origin {branch}`. "
        f"Resolve any merge conflicts.\n"
    ) if has_remote else ""

    push_instructions = ""
    if worktree_mode:
        push_instructions = f"""- If you find and fix issues, commit with message prefix `qa: `
- Push: `git push origin {branch}`
- If push fails: `git pull --rebase origin {branch} && git push origin {branch}`"""

    prompt = f"""You are a QA worker (Worker {worker_index}) running {len(scenarios)} scenarios sequentially for PR {pr_id}: "{title}"

## Context

- **PR**: {pr_id} — "{title}"
- **Branch**: {branch}
- **Base branch**: {base_branch}
{workdir_block}
{pr_notes_block}{mocks_block}
## How This Works

You are a batched QA worker. You will execute {len(scenarios)} scenario(s) sequentially
(scenarios {scenario_indices}).  An orchestrator is monitoring your tmux pane.

**For each scenario:**
1. Review the diff and relevant files (you only need to do this thoroughly once —
   reuse your understanding across scenarios)
{pull_step}2. Execute the test steps described for that scenario
3. Write a per-scenario report file (path given per scenario below)
4. Output the scenario verdict in this exact format on its own line:
   `SCENARIO_<N>_VERDICT: <VERDICT>`
   where N is the scenario number and VERDICT is PASS, NEEDS_WORK, or INPUT_REQUIRED
5. **WAIT** — do not proceed to the next scenario until the orchestrator sends you
   a message saying "PROCEED TO SCENARIO <next>". This allows the orchestrator to
   verify your verdict and the user to review results.

## Important: When to use each verdict

- **PASS** — You executed the test steps AND they succeeded. A PASS is only valid
  when you have **runtime evidence** (command output, observed behavior, test results).
- **NEEDS_WORK** — You executed the test steps and found concrete bugs or issues.
{push_instructions}
- **INPUT_REQUIRED** — You could not execute one or more test steps because of
  missing tools, unavailable commands, environment limitations, or ambiguity.
  **Stop and wait for human input** — do NOT proceed to the next scenario.

## Report File Format

For each scenario, write a markdown report to the specified path BEFORE outputting
the verdict. Use this format:

```
# Scenario <N>: <title>

## Verdict: <PASS|NEEDS_WORK|INPUT_REQUIRED>

## Summary
<brief summary of what you tested and found>

## Details
<detailed findings, command outputs, issues discovered>
```

Write the report atomically: write to a `.tmp` file first, then rename it.

## Scenarios

{scenarios_text}

## Execution Order

Execute scenarios in this order: {scenario_indices}.
Start with Scenario {scenarios[0].index} now.

IMPORTANT: After each scenario's verdict, WAIT for the orchestrator to tell you
to proceed. Do not start the next scenario until instructed."""
    return prompt.strip()


def generate_standalone_qa_prompt(data: dict, instruction_id: str,
                                  session_name: str | None = None) -> str:
    """Generate a prompt for running QA against master without a PR.

    Args:
        data: Project data dict.
        instruction_id: ID of the instruction to run.
        session_name: tmux session name.
    """
    from pm_core import qa_instructions

    base_branch = data.get("project", {}).get("base_branch", "master")

    try:
        root = store.find_project_root()
        item = qa_instructions.get_instruction(root, instruction_id, "instructions")
        if item is None:
            item = qa_instructions.get_instruction(root, instruction_id, "regression")
    except FileNotFoundError:
        item = None

    instruction_block = ""
    if item:
        instruction_block = f"""
## Instruction

Read the full instruction at: `{item['path']}`
Follow its procedures.
"""

    repo_url = data.get("project", {}).get("repo", "")

    tui_block = tui_section(session_name) if session_name else ""

    prompt = f"""You are running a standalone QA session against the {base_branch} branch.

## Context

- **Repo**: {repo_url}
- **Branch**: {base_branch}
- **Instruction**: {instruction_id}

You are testing the current state of the codebase.
{instruction_block}{tui_block}
## Execution

1. Follow the instruction steps
2. Report your findings
3. End with a verdict on its own line — one of:
   - **PASS** — All checks passed
   - **NEEDS_WORK** — Issues found (describe them)
   - **INPUT_REQUIRED** — Need human input

IMPORTANT: Always end your response with the verdict keyword on its own line."""
    return prompt.strip()

