"""Plan commands for the pm CLI.

Registers the ``plan`` group and all subcommands on the top-level ``cli`` group.
Also contains _import_github_prs and _run_plan_import used by init.
"""

from pathlib import Path

import click

from pm_core import store, notes
from pm_core.plan_parser import parse_plan_prs
from pm_core import review as review_mod
from pm_core.claude_launcher import find_claude, launch_claude, launch_claude_print, clear_session

from pm_core.cli import cli
from pm_core.cli.helpers import (
    _auto_select_plan,
    _gh_state_to_status,
    _make_pr_entry,
    _pr_display_id,
    _require_plan,
    _resolve_repo_dir,
    save_and_push,
    state_root,
    trigger_tui_refresh,
)


# --- Plan commands ---

@cli.group()
def plan():
    """Manage plans."""
    pass


@plan.command("add")
@click.argument("name")
@click.option("--description", default="", help="Description of what the plan should accomplish")
@click.option("--fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
def plan_add(name: str, description: str, fresh: bool):
    """Create a new plan and launch Claude to develop it."""
    root = state_root()
    data = store.load(root)
    existing_ids = {p["id"] for p in (data.get("plans") or [])}
    plan_id = store.generate_plan_id(name, existing_ids, description=description)
    plan_file = f"plans/{plan_id}.md"

    entry = {
        "id": plan_id,
        "name": name,
        "file": plan_file,
        "status": "draft",
    }
    if data.get("plans") is None:
        data["plans"] = []
    data["plans"].append(entry)

    # Create the plan file
    plan_path = root / plan_file
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    if description:
        plan_path.write_text(f"# {name}\n\n{description}\n")
    else:
        plan_path.write_text(f"# {name}\n\n<!-- Describe the plan here -->\n")

    # Ensure notes file exists
    notes.ensure_notes_file(root)

    save_and_push(data, root, f"pm: add plan {plan_id}")
    click.echo(f"Created plan {plan_id}: {name}")
    click.echo(f"  Plan file: {plan_path}")
    trigger_tui_refresh()

    notes_block = notes.notes_section(root)
    desc_block = ""
    if description:
        desc_block = f"""
The user has provided this description of what the plan should accomplish:

> {description}

Use this as a starting point — confirm your understanding, ask clarifying questions
if needed, then develop the full plan.
"""
    else:
        desc_block = """
Ask me what this plan should accomplish. I'll describe it at a high level and
we'll iterate until the plan is clear and complete. Then write the final plan
to the file above as structured markdown.
"""
    prompt = f"""\
Your goal: Help me develop a plan called "{name}" and write it to {plan_path}.

This session is managed by `pm` (project manager for Claude Code). You have access
to the `pm` CLI tool — run `pm help` to see available commands.

The plan file is at: {plan_path}
{desc_block}
The plan needs to include scope, goals, key design decisions, and any constraints.

Once the plan is solid, break it down into a "## PRs" section with individual PRs
in this format:

### PR: <title>
- **description**: What this PR does
- **tests**: Expected unit tests
- **files**: Expected file modifications
- **depends_on**: <title of dependency PR, or empty>

Separate PR entries with --- lines. Prefer more small PRs over fewer large ones.
Order them so independent PRs can be worked on in parallel. Only add depends_on
when there's a real ordering constraint.

After writing the PRs section, tell the user to run `pm plan review {plan_id}`
(key: c in the plans pane) to check consistency and coverage before loading.
{notes_block}"""

    claude = find_claude()
    if claude:
        session_key = f"plan:add:{plan_id}"
        if fresh:
            clear_session(root, session_key)
        click.echo("Launching Claude...")
        launch_claude(prompt, session_key=session_key, pm_root=root, resume=not fresh)
        # Background review
        check_prompt = review_mod.REVIEW_PROMPTS["plan-add"].format(path=plan_path)
        click.echo("Reviewing results... (background)")
        review_mod.review_step("plan add", f'Develop plan "{name}"', check_prompt, root)
    else:
        click.echo()
        click.echo("Claude CLI not found. Copy-paste this prompt into Claude Code:")
        click.echo()
        click.echo(f"---\n{prompt}\n---")


@plan.command("list")
def plan_list():
    """List all plans."""
    root = state_root()
    data = store.load(root)
    plans = data.get("plans") or []
    if not plans:
        click.echo("No plans.")
        return
    for p in plans:
        click.echo(f"  {p['id']}: {p['name']} [{p.get('status', 'draft')}]")


@plan.command("breakdown")
@click.argument("plan_id", default=None, required=False)
@click.option("--prs", "initial_prs", default=None, help="Seed the conversation with an initial PR list")
@click.option("--fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
def plan_breakdown(plan_id: str | None, initial_prs: str | None, fresh: bool):
    """Launch Claude to break a plan into PRs (written to plan file).

    If PLAN_ID is omitted, auto-selects when there's exactly one plan.
    """
    root = state_root()
    data = store.load(root)

    plan_id = _auto_select_plan(data, plan_id)
    plan_entry = _require_plan(data, plan_id)

    plan_path = root / plan_entry["file"]
    if not plan_path.exists():
        click.echo(f"Plan file {plan_path} not found.", err=True)
        raise SystemExit(1)

    existing_prs = data.get("prs") or []
    existing_context = ""
    if existing_prs:
        existing_context = "\nExisting PRs in this project:\n" + "\n".join(
            f"  {pr['id']}: {pr.get('title', '???')} [{pr.get('status', '?')}]"
            + (f" (depends on: {', '.join(pr.get('depends_on') or [])})" if pr.get("depends_on") else "")
            for pr in existing_prs
        )

    initial_context = ""
    if initial_prs:
        initial_context = f"\nInitial PR ideas from the user:\n{initial_prs}\n"

    notes_block = notes.notes_section(root)

    prompt = f"""\
Your goal: Break the plan into a list of PRs that the user is happy with, then
write them to the plan file so they can be reviewed with `pm plan review`.

This session is managed by `pm` (project manager for Claude Code). You have access
to the `pm` CLI tool — run `pm help` to see available commands.

Read the plan file at: {plan_path}

Propose a set of PRs that implement this plan. Discuss the breakdown with the
user — ask about anything ambiguous (scope of individual PRs, ordering
preferences, what can be parallelized). Iterate until the user is comfortable
with the list.

Once agreed, write a "## PRs" section to the plan file with this format:

### PR: <title>
- **description**: What this PR does
- **tests**: Expected unit tests
- **files**: Expected file modifications
- **depends_on**: <title of dependency PR, or empty>

Separate PR entries with --- lines.
{existing_context}{initial_context}
Guidelines:
- Prefer more small PRs over fewer large ones
- Order them so independent PRs can be worked on in parallel
- Only add depends_on when there's a real ordering constraint
- Write the ## PRs section directly into the plan file at {plan_path}

After writing, tell the user to run `pm plan review {plan_id}` (key: c in the
plans pane) to check consistency and coverage before loading PRs.
{notes_block}"""

    claude = find_claude()
    if claude:
        session_key = f"plan:breakdown:{plan_id}"
        if fresh:
            clear_session(root, session_key)
        click.echo(f"Launching Claude to break down plan {plan_id}...")
        launch_claude(prompt, session_key=session_key, pm_root=root, resume=not fresh)
        # Background review
        check_prompt = review_mod.REVIEW_PROMPTS["plan-breakdown"].format(path=plan_path)
        click.echo("Reviewing results... (background)")
        review_mod.review_step("plan breakdown", f"Break plan {plan_id} into PRs", check_prompt, root)
    else:
        click.echo()
        click.echo("Claude CLI not found. Copy-paste this prompt into Claude Code:")
        click.echo()
        click.echo(f"---\n{prompt}\n---")


@plan.command("review")
@click.argument("plan_id", default=None, required=False)
@click.option("--fresh", is_flag=True, default=False, help="Start a fresh session")
def plan_review(plan_id: str | None, fresh: bool):
    """Launch Claude to review plan-PR consistency."""
    root = state_root()
    data = store.load(root)

    plan_id = _auto_select_plan(data, plan_id)
    plan_entry = _require_plan(data, plan_id)

    plan_path = root / plan_entry["file"]
    if not plan_path.exists():
        click.echo(f"Plan file {plan_path} not found.", err=True)
        raise SystemExit(1)

    # Build PR list for this plan
    all_prs = data.get("prs") or []
    plan_prs = [pr for pr in all_prs if pr.get("plan") == plan_id]
    other_prs = [pr for pr in all_prs if pr.get("plan") != plan_id]

    def _format_pr(pr):
        deps = pr.get("depends_on") or []
        dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
        desc = pr.get("description", "")
        desc_str = f"\n    description: {desc}" if desc else ""
        tests = pr.get("tests", "")
        tests_str = f"\n    tests: {tests}" if tests else ""
        files = pr.get("files", "")
        files_str = f"\n    files: {files}" if files else ""
        status = pr.get("status", "pending")
        gh_num = pr.get("gh_pr_number")
        gh_str = f"\n    github: PR #{gh_num}" if gh_num else ""
        branch = pr.get("branch")
        branch_str = f"\n    branch: {branch}" if branch else ""
        workdir = pr.get("workdir")
        workdir_str = f"\n    workdir: {workdir}" if workdir else ""
        return f"  {pr['id']}: {pr.get('title', '???')} [{status}]{dep_str}{gh_str}{branch_str}{workdir_str}{desc_str}{tests_str}{files_str}"

    pr_list = "\n".join(_format_pr(pr) for pr in plan_prs) if plan_prs else "(no PRs linked to this plan)"

    other_prs_context = ""
    if other_prs:
        other_prs_context = "\nPRs from other plans (for cross-plan reference):\n" + "\n".join(
            f"  {pr['id']}: {pr.get('title', '???')} [{pr.get('status', '?')}] (plan: {pr.get('plan', '?')})"
            for pr in other_prs
        ) + "\n"

    notes_block = notes.notes_section(root)

    if plan_prs:
        # Post-load: PRs exist in project.yaml — review with progress awareness
        prompt = f"""\
Your goal: Review the plan's progress, iterate on both the plan and its PRs,
and help the user understand where things stand.

This session is managed by `pm` (project manager for Claude Code). You have
access to the `pm` CLI tool — run `pm help` to see available commands.

Read the plan file at: {plan_path}

PRs belonging to this plan:
{pr_list}

{other_prs_context}\
First, assess progress:
- How many PRs are done (merged/in_review) vs remaining (pending/in_progress)?
- Check the github PR, branch, or workdir listed in each PR's yaml to verify
  actual implementation state.
- Are there any blockers — PRs whose dependencies aren't met yet?
- Summarize the current state concisely for the user.

Then check for issues:

1. COVERAGE — Does every feature in the plan have at least one PR? Are there
   new requirements or scope changes that need additional PRs?

2. CONSISTENCY — Do PR descriptions still match the plan? Are depends_on
   references correct? Verify actual changed files against each PR's
   description using the github PR, branch, or workdir in the yaml.
   The current working tree may not reflect PR branch changes.

3. ITERATION — Based on what's been completed so far, does the plan need
   updating? Do remaining PR descriptions need refinement based on what
   was learned from completed PRs?

For any issues found, you can propose a fix. Fixes can be applied as follows:
- For PR changes: use `pm pr edit <id> --description "..." --title "..."`
- For plan updates: edit the plan file directly at {plan_path}
- To add new PRs: use `pm pr add`

After fixing, summarize what was changed.
{notes_block}"""
    else:
        # Pre-load: no PRs in project.yaml yet — review the plan file's PR section
        prompt = f"""\
Your goal: Review the plan and its PRs for consistency, coverage, and
self-containment before they are loaded. Identify gaps and fix them.

This session is managed by `pm` (project manager for Claude Code). You have
access to the `pm` CLI tool — run `pm help` to see available commands.

Read the plan file at: {plan_path}

The plan file should contain a "## PRs" section with proposed PRs. No PRs
have been loaded into the project yet.

{other_prs_context}\
Check the following:

1. COVERAGE — Does every feature, behavior, or capability described in the
   plan have at least one PR responsible for it? List any gaps.

2. SELF-CONTAINMENT — Can an agent pick up any single PR and understand what
   to build without reading the entire plan? Each PR description should include:
   - What the PR does and why (not just "implement X")
   - Which files to modify or create
   - What tests to write
   - How it relates to its dependencies (what it receives from them)
   - Reference to the plan file for broader context

3. CONSISTENCY — Do PR descriptions match the plan? Are depends_on
   references correct? Are file paths plausible? For each file path
   mentioned in a PR's **files** field, check whether it already exists
   in the repo (ls or find the file). If it exists, the PR should modify
   it; if it doesn't, the PR should create it. Flag paths that look wrong
   (typos, wrong directory, missing extension).

For each issue found, propose a fix. When the user agrees, apply fixes
by editing the plan file directly at {plan_path}.

After fixing, summarize what was changed. Then tell the user to run
`pm plan load {plan_id}` (key: l in the plans pane) to create the PRs.
{notes_block}"""

    claude = find_claude()
    if claude:
        session_key = f"plan:review:{plan_id}"
        # Post-load reviews always start fresh — state changes between reviews
        if fresh or plan_prs:
            clear_session(root, session_key)
        click.echo(f"Launching Claude to review plan {plan_id}...")
        launch_claude(prompt, session_key=session_key, pm_root=root, resume=not fresh and not plan_prs)
        # Background review
        check_prompt = review_mod.REVIEW_PROMPTS["plan-review"].format(path=plan_path)
        click.echo("Reviewing results... (background)")
        review_mod.review_step("plan review", f"Review plan {plan_id} consistency", check_prompt, root)
    else:
        click.echo()
        click.echo("Claude CLI not found. Copy-paste this prompt into Claude Code:")
        click.echo()
        click.echo(f"---\n{prompt}\n---")


@plan.command("deps")
def plan_deps():
    """Launch Claude to review or fix PR dependencies."""
    root = state_root()
    data = store.load(root)
    prs = data.get("prs") or []

    if not prs:
        click.echo("No PRs. Add PRs first with: pm pr add <title>", err=True)
        raise SystemExit(1)

    pr_lines = []
    for p in prs:
        deps = p.get("depends_on") or []
        dep_str = f" (depends on: {', '.join(deps)})" if deps else ""
        desc = p.get("description", "")
        desc_str = f" — {desc}" if desc else ""
        pr_lines.append(f"  {_pr_display_id(p)}: {p.get('title', '???')} [{p.get('status', '?')}]{dep_str}{desc_str}")

    pr_list_str = "\n".join(pr_lines)

    # Include plan context if available
    plan_context = ""
    plans = data.get("plans") or []
    for plan_entry in plans:
        plan_path = root / plan_entry["file"]
        if plan_path.exists():
            plan_context += f"\nPlan: {plan_entry['name']} ({plan_entry['id']})\n"
            plan_context += plan_path.read_text() + "\n"

    notes_block = notes.notes_section(root)

    prompt = f"""\
Your goal: Review and fix the dependency graph between PRs, then run the
`pm pr edit` commands to apply the corrections.

This session is managed by `pm` (project manager for Claude Code). You have access
to the `pm` CLI tool — run `pm help` to see available commands.

Check these PRs for dependency issues:

1. Missing dependencies — if PR B can't start until PR A is done, add it
2. Wrong dependencies — if a dependency isn't actually needed, remove it
3. Circular dependencies — flag any cycles

PRs:
{pr_list_str}
{plan_context}
Discuss any proposed changes with the user before applying them.

When the user agrees, run the `pm pr edit` commands yourself to apply fixes:

  pm pr edit pr-001 --depends-on pr-002,pr-003
  pm pr edit pr-004 --depends-on pr-001

If a PR should have NO dependencies, use:

  pm pr edit pr-005 --depends-on ""

After applying changes, run `pm pr graph` to show the user the final
dependency tree.
{notes_block}"""

    claude = find_claude()
    if claude:
        click.echo("Launching Claude to review dependencies...")
        launch_claude(prompt, session_key="plan:deps", pm_root=root)
        # Background review
        check_prompt = review_mod.REVIEW_PROMPTS["plan-deps"]
        click.echo("Reviewing results... (background)")
        review_mod.review_step("plan deps", "Review/fix PR dependencies", check_prompt, root)
    else:
        click.echo()
        click.echo("Claude CLI not found. Copy-paste this prompt into Claude Code:")
        click.echo()
        click.echo(f"---\n{prompt}\n---")


@plan.command("load")
@click.argument("plan_id", default=None, required=False)
def plan_load(plan_id: str | None):
    """Parse PRs from plan file and create them via Claude (non-interactive).

    Reads the ## PRs section from the plan file, generates pm pr add commands,
    and launches Claude in print mode to execute them.
    """
    root = state_root()
    data = store.load(root)

    plan_id = _auto_select_plan(data, plan_id)
    plan_entry = _require_plan(data, plan_id)

    plan_path = root / plan_entry["file"]
    if not plan_path.exists():
        click.echo(f"Plan file {plan_path} not found.", err=True)
        raise SystemExit(1)

    plan_content = plan_path.read_text()
    prs = parse_plan_prs(plan_content)

    if not prs:
        click.echo("No PRs found in plan file. Run 'pm plan breakdown' first to add a ## PRs section.", err=True)
        raise SystemExit(1)

    click.echo(f"Found {len(prs)} PRs in plan file:")

    # Build title -> index map for resolving depends_on references
    title_order = {pr["title"]: i for i, pr in enumerate(prs)}

    # Generate pm pr add commands
    commands = []
    for pr in prs:
        cmd = f'pm pr add "{pr["title"]}" --plan {plan_id}'
        if pr["description"]:
            desc_escaped = pr["description"].replace('"', '\\"')
            cmd += f' --description "{desc_escaped}"'
        # depends_on references titles; we'll resolve after all are created
        # For now, skip depends_on in the add commands and do a second pass
        commands.append(cmd)
        click.echo(f"  - {pr['title']}")

    # Compute the PR IDs that will be assigned when the add commands run.
    # This is safe because hash-based IDs are deterministic from title+desc,
    # and we have the exact title+desc that the add commands will use.
    existing_ids = {p["id"] for p in (data.get("prs") or [])}
    title_to_id = {}
    for pr in prs:
        pr_id = store.generate_pr_id(pr["title"], pr.get("description", ""), existing_ids)
        title_to_id[pr["title"]] = pr_id
        existing_ids.add(pr_id)

    dep_commands = []
    for pr in prs:
        if pr["depends_on"]:
            pr_id = title_to_id[pr["title"]]
            dep_title = pr["depends_on"].strip()
            if dep_title in title_to_id:
                dep_id = title_to_id[dep_title]
                dep_commands.append(f'pm pr edit {pr_id} --depends-on {dep_id}')

    all_commands = commands + dep_commands

    click.echo()
    prompt = "Your goal: Create all the PRs from the plan by running these pm commands.\n\n"
    prompt += "This session is managed by `pm` (project manager for Claude Code). "
    prompt += "Run these commands in order using your Bash tool:\n\n"
    prompt += "\n".join(all_commands)
    prompt += "\n\nAfter running all commands, run `pm pr list` and `pm pr graph` to "
    prompt += "show the user what was created."

    claude = find_claude()
    if claude:
        click.echo("Launching Claude to create PRs...")
        output = launch_claude_print(prompt, cwd=str(root), message="Creating PRs from plan")
        click.echo(output)
        # Background review
        check_prompt = review_mod.REVIEW_PROMPTS["plan-load"].format(path=plan_path)
        click.echo("Reviewing results... (background)")
        review_mod.review_step("plan load", f"Create PRs from plan {plan_id}", check_prompt, root)
    else:
        click.echo()
        click.echo("Claude CLI not found. Run these commands manually:")
        click.echo()
        for cmd in all_commands:
            click.echo(f"  {cmd}")


@plan.command("fixes")
def plan_fixes():
    """List pending review files with fix commands."""
    root = state_root()
    pending = review_mod.list_pending_reviews(root)
    if not pending:
        click.echo("No pending reviews.")
        return
    for r in pending:
        click.echo(f"  {r['filename']}")
        if r["fix_cmd"]:
            click.echo(f"    Run: {r['fix_cmd']}")
        click.echo()


def _run_fix_command(step_name: str, review_path_str: str):
    """Common logic for all fix subcommands."""
    review_path = Path(review_path_str)
    if not review_path.exists():
        click.echo(f"Review file not found: {review_path}", err=True)
        raise SystemExit(1)

    root = state_root()
    parsed = review_mod.parse_review_file(review_path)

    # Build context from current state
    data = store.load(root)
    plans = data.get("plans") or []
    context_parts = []
    for p in plans:
        pp = root / p["file"]
        if pp.exists():
            context_parts.append(f"Plan {p['id']} ({p['name']}):\n{pp.read_text()}")

    original_context = "\n".join(context_parts) if context_parts else "No plan files found."
    prompt = review_mod.build_fix_prompt(step_name, original_context, parsed["findings"])

    notes_block = notes.notes_section(root)
    if notes_block:
        prompt += f"\n{notes_block}"

    claude = find_claude()
    if claude:
        # Use review file path as unique key component
        review_key = review_path.stem  # e.g. "plan-add-20240101-120000"
        session_key = f"fix:{step_name.replace(' ', '-')}:{review_key}"
        click.echo(f"Launching Claude to fix issues from review...")
        launch_claude(prompt, session_key=session_key, pm_root=root)
    else:
        click.echo("Claude CLI not found. Copy-paste this prompt:")
        click.echo(f"---\n{prompt}\n---")


@plan.command("fix")
@click.option("--review", "review_path", required=True, help="Path to review file")
def plan_fix(review_path: str):
    """Fix issues found by a review.

    Reads the step name from the review file, so a single command
    works for any review (plan add, breakdown, deps, load, import).
    """
    parsed = review_mod.parse_review_file(Path(review_path))
    step_name = parsed.get("step", "")
    if not step_name:
        click.echo("Could not determine step from review file.", err=True)
        raise SystemExit(1)
    _run_fix_command(step_name, review_path)


def _import_github_prs(root: Path, data: dict) -> None:
    """Import existing GitHub PRs into yaml during init."""
    from pm_core import gh_ops

    repo_dir = str(_resolve_repo_dir(root, data))

    click.echo("Checking for existing GitHub PRs...")
    try:
        gh_prs = gh_ops.list_prs(repo_dir, state="open")
    except SystemExit:
        click.echo("  Skipping PR import (gh CLI not available).")
        return

    if not gh_prs:
        click.echo("  No open PRs found.")
        return

    if data.get("prs") is None:
        data["prs"] = []

    imported = 0
    for gh_pr in gh_prs:
        branch = gh_pr.get("headRefName", "")
        number = gh_pr.get("number")
        title = gh_pr.get("title", "")
        status = _gh_state_to_status(gh_pr.get("state", "OPEN"), gh_pr.get("isDraft", False))

        existing_ids = {p["id"] for p in data["prs"]}
        desc = gh_pr.get("body", "") or ""
        pr_id = store.generate_pr_id(title, desc, existing_ids)

        entry = _make_pr_entry(pr_id, title, branch, status=status,
                               description=desc, gh_pr=gh_pr.get("url", ""),
                               gh_pr_number=number)
        data["prs"].append(entry)
        existing_ids.add(pr_id)
        imported += 1
        click.echo(f"  + {pr_id}: {title} [{status}] (#{number})")

    if imported:
        store.save(data, root)
        click.echo(f"  Imported {imported} PR(s) from GitHub.")


def _run_plan_import(name: str):
    """Core logic for plan import — used by both `plan import` and `init`."""
    root = state_root()
    data = store.load(root)
    existing_ids = {p["id"] for p in (data.get("plans") or [])}
    plan_id = store.generate_plan_id(name, existing_ids)
    plan_file = f"plans/{plan_id}.md"

    entry = {
        "id": plan_id,
        "name": name,
        "file": plan_file,
        "status": "draft",
    }
    if data.get("plans") is None:
        data["plans"] = []
    data["plans"].append(entry)

    # Create the plan file
    plan_path = root / plan_file
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(f"# {name}\n\n")

    # Ensure notes file exists
    notes.ensure_notes_file(root)

    save_and_push(data, root, f"pm: add plan {plan_id}")
    click.echo(f"Created plan {plan_id}: {name}")
    click.echo(f"  Plan file: {plan_path}")
    trigger_tui_refresh()

    notes_block = notes.notes_section(root)

    prompt = f"""\
Your goal: Analyze this repository, discuss what you find with the user, and
write a PR graph to the plan file. After agreement, the user will run
`pm plan load` to import everything into the project.

This session is managed by `pm` (project manager for Claude Code). You have access
to the `pm` CLI tool — run `pm help` to see available commands.

The plan file is at: {plan_path}

Phase 1 — Gather data (do this before talking to me):
- If `gh` CLI is available: run `gh pr list --state all --limit 200 --json number,title,state,headRefName,body,mergedAt` and `gh issue list --state all --limit 200 --json number,title,state,body,labels`
- Run `git log --oneline -50` to see recent commit history
- Read the codebase structure (ls key directories, read READMEs)
- If gh is not available, skip PR/issue steps and work from git log and code only.

Phase 2 — Discuss with me:
- Summarize what you found: major components, existing PRs, open issues
- Ask which areas I care about tracking vs ignoring
- Ask whether old merged work should appear in the graph or only future work
- For large commits that look like they should have been multiple PRs,
  ask whether I want them broken down retroactively or just noted
- For open issues, ask which ones to turn into PR entries and how to prioritize
- Ask about any ambiguous dependency relationships or groupings
- Ask any other questions where my preference matters

Phase 3 — Write the plan file (only after we've agreed):
Write a ## PRs section to {plan_path} with entries in this format:

### PR: <title>
- **description**: What this PR does
- **tests**: Expected tests
- **files**: Key files involved
- **depends_on**: <title of dependency PR, or empty>
- **status**: merged | open | proposed

Use "merged" for done work, "open" for existing open PRs, "proposed" for
new recommended work. For merged/open PRs reference the original number
(e.g. "Original: #42"). Group related PRs together with dependencies
flowing top to bottom.

Phase 4 — Verify file references (do this immediately after writing):
Re-read the plan file you just wrote. For every path listed in a **files**
field, verify the file actually exists in the repo (use ls or read). If a
path is wrong, find the correct path and update the plan file. Report any
corrections you made.

Once verified, the next step is `pm plan load {plan_id}` to create the PRs.
{notes_block}"""

    claude = find_claude()
    if claude:
        session_key = f"plan:import:{plan_id}"
        click.echo("Launching Claude...")
        launch_claude(prompt, session_key=session_key, pm_root=root)
        # Background review
        check_prompt = review_mod.REVIEW_PROMPTS["plan-import"].format(path=plan_path)
        click.echo("Reviewing results... (background)")
        review_mod.review_step("plan import", f'Import PR graph for "{name}"', check_prompt, root)
    else:
        click.echo()
        click.echo("Claude CLI not found. Copy-paste this prompt into Claude Code:")
        click.echo()
        click.echo(f"---\n{prompt}\n---")


@plan.command("import")
@click.option("--name", default="Import from existing repo", help="Plan name")
def plan_import(name: str):
    """Analyze existing repo and bootstrap a PR graph interactively.

    Launches Claude to gather data from PRs, issues, git history, and code,
    then discuss findings with you before writing a PR graph to a plan file.
    """
    _run_plan_import(name)
