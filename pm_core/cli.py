"""Click CLI definitions for pm."""

import os
import platform
import shutil
from pathlib import Path

import click

from pm_core import store, graph, git_ops, prompt_gen, notes
from pm_core.backend import detect_backend, get_backend
from pm_core.claude_launcher import find_claude, find_editor, launch_claude, launch_claude_print, clear_session
from pm_core import tmux as tmux_mod
from pm_core import pane_layout
from pm_core.plan_parser import parse_plan_prs
from pm_core import review as review_mod
from pm_core import guide as guide_mod


_project_override: Path | None = None


def _normalize_repo_url(url: str) -> str:
    """Normalize git remote URL for comparison.

    git@github.com:org/repo.git -> github.com/org/repo
    https://github.com/org/repo.git -> github.com/org/repo
    """
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    # SSH format: git@host:path
    if ":" in url and "@" in url.split(":")[0]:
        _, rest = url.split(":", 1)
        host = url.split("@")[1].split(":")[0]
        return f"{host}/{rest}"
    # HTTPS format
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


def _verify_pm_repo_matches_cwd(pm_root: Path) -> None:
    """Warn if the PM repo targets a different repo than the current git repo."""
    cwd = Path.cwd()
    if not git_ops.is_git_repo(cwd):
        return
    cwd_remote = git_ops.run_git("remote", "get-url", "origin", cwd=cwd, check=False)
    if cwd_remote.returncode != 0 or not cwd_remote.stdout.strip():
        return
    try:
        data = store.load(pm_root)
    except Exception:
        return
    pm_target = data.get("project", {}).get("repo", "")
    if not pm_target:
        return
    # If pm_target is a local path, check if cwd is that path
    pm_target_path = Path(pm_target)
    if pm_target_path.is_absolute() and pm_target_path.exists():
        try:
            if cwd.resolve() == pm_target_path.resolve():
                return
        except OSError:
            pass
    if _normalize_repo_url(cwd_remote.stdout.strip()) != _normalize_repo_url(pm_target):
        click.echo(
            f"Warning: PM repo targets {pm_target}\n"
            f"         but you're in a repo with remote {cwd_remote.stdout.strip()}\n",
            err=True,
        )


def state_root() -> Path:
    """Get the project root containing project.yaml."""
    if _project_override:
        _verify_pm_repo_matches_cwd(_project_override)
        return _project_override
    return store.find_project_root()


def load_and_sync() -> tuple[dict, Path]:
    """Load state, optionally syncing from git first."""
    root = state_root()
    git_ops.sync_state(root)
    return store.load(root), root


def save_and_push(data: dict, root: Path, message: str = "pm: update state") -> None:
    """Save state. Use 'pm push' to commit and share changes."""
    store.save(data, root)


def _workdirs_dir(data: dict) -> Path:
    """Return the workdirs base path for this project.

    Uses <name>-<repo_id[:8]> to avoid collisions between projects
    with the same name. repo_id is the root commit hash of the target
    repo, cached in project.yaml on first pr start.
    """
    project = data.get("project", {})
    name = project.get("name", "unknown")
    repo_id = project.get("repo_id")
    if repo_id:
        return Path.home() / ".pm-workdirs" / f"{name}-{repo_id[:8]}"
    return Path.home() / ".pm-workdirs" / name


def _resolve_repo_id(data: dict, workdir: Path, root: Path) -> None:
    """Resolve and cache the target repo's root commit hash."""
    if data.get("project", {}).get("repo_id"):
        return
    result = git_ops.run_git("rev-list", "--max-parents=0", "HEAD", cwd=workdir, check=False)
    if result.returncode == 0 and result.stdout.strip():
        data["project"]["repo_id"] = result.stdout.strip().splitlines()[0]
        save_and_push(data, root, "pm: cache repo_id")


def _infer_pr_id(data: dict, status_filter: tuple[str, ...] | None = None) -> str | None:
    """Try to infer a PR ID from context.

    1. If cwd matches a PR's workdir, use that PR.
    2. If there's an active PR (and it matches the status filter if given), use that.
    3. If exactly one PR matches the status filter, use that.
    """
    cwd = str(Path.cwd().resolve())
    prs = data.get("prs") or []

    # Check if cwd is inside a PR's workdir
    for pr in prs:
        wd = pr.get("workdir")
        if wd and cwd.startswith(str(Path(wd).resolve())):
            return pr["id"]

    # Check active PR
    active = data.get("project", {}).get("active_pr")
    if active:
        pr_entry = store.get_pr(data, active)
        if pr_entry:
            if status_filter is None or pr_entry.get("status") in status_filter:
                return active

    # Fall back to single-match on status
    if status_filter:
        matches = [p for p in prs if p.get("status") in status_filter]
        if len(matches) == 1:
            return matches[0]["id"]

    return None


@click.group(invoke_without_command=True)
@click.option("-C", "project_dir", default=None, envvar="PM_PROJECT",
              help="Path to PM repo (or set PM_PROJECT env var)")
@click.pass_context
def cli(ctx, project_dir: str | None):
    """pm — Project Manager for Claude Code sessions."""
    global _project_override
    if project_dir:
        _project_override = Path(project_dir).resolve()
    if ctx.invoked_subcommand is None:
        # No subcommand: launch TUI if project found, else show help
        try:
            state_root()
            ctx.invoke(tui_cmd)
        except (FileNotFoundError, SystemExit):
            ctx.invoke(help_cmd)


@cli.command()
@click.argument("repo_url", metavar="TARGET_REPO_URL", default=None, required=False)
@click.option("--name", default=None, help="Project name (defaults to repo name)")
@click.option("--base-branch", default=None, help="Base branch (auto-detected from cwd)")
@click.option("--dir", "directory", default=None,
              help="Directory for PM state (default: pm/ inside cwd)")
@click.option("--backend", "backend_override", default=None,
              type=click.Choice(["local", "vanilla", "github"]),
              help="Hosting backend (auto-detected from URL if not set)")
@click.option("--no-import", "no_import", is_flag=True, default=False,
              help="Skip the interactive repo import after init")
def init(repo_url: str | None, name: str, base_branch: str, directory: str,
         backend_override: str, no_import: bool):
    """Create a PM directory for managing a target codebase.

    TARGET_REPO_URL is the codebase where code PRs will be opened.
    If omitted, auto-detected from the current git repo's origin remote
    (or the local path if there's no remote).

    By default, creates a pm/ directory inside the current repo to hold
    project.yaml and plans/. Use --dir to place it elsewhere (which
    creates a standalone PM repo with its own git history).

    The hosting backend is auto-detected from the URL:
      - github.com URLs use the 'github' backend (gh CLI integration)
      - Other remote URLs use the 'vanilla' backend (git with remote)
      - Local paths use the 'local' backend (git, no remote)

    \b
    Examples:
      pm init                                        # auto-detect everything
      pm init git@github.com:org/myapp.git
      pm init git@myhost.com:org/myapp.git --backend vanilla
      pm init --dir ~/projects/myapp-pm
    """
    cwd = Path.cwd()

    # Auto-detect repo URL from cwd if not specified
    if repo_url is None:
        if git_ops.is_git_repo(cwd):
            result = git_ops.run_git("remote", "get-url", "origin", cwd=cwd, check=False)
            if result.returncode == 0 and result.stdout.strip():
                repo_url = result.stdout.strip()
            else:
                repo_url = str(cwd)
        else:
            click.echo("No TARGET_REPO_URL provided and not in a git repo.", err=True)
            raise SystemExit(1)

    if name is None:
        name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")

    if base_branch is None:
        if git_ops.is_git_repo(cwd):
            result = git_ops.run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd, check=False)
            if result.returncode == 0 and result.stdout.strip():
                base_branch = result.stdout.strip()
        if base_branch is None:
            base_branch = "main"

    if directory is None:
        directory = "pm"
    root = Path(directory).resolve()

    if (root / "project.yaml").exists():
        click.echo(f"PM directory already exists at {root}", err=True)
        click.echo(f"To start fresh, remove it: rm -rf {root}", err=True)
        raise SystemExit(1)

    backend = backend_override or detect_backend(repo_url)
    data = store.init_project(root, name, repo_url, base_branch, backend=backend)

    # Ensure notes.txt is gitignored (it's local/clone-specific)
    gitignore = root / ".gitignore"
    gitignore_content = gitignore.read_text() if gitignore.exists() else ""
    additions = []
    for fname in ("notes.txt", ".pm-sessions.json"):
        if fname not in gitignore_content:
            additions.append(fname)
    if additions:
        with open(gitignore, "a") as f:
            if gitignore_content and not gitignore_content.endswith("\n"):
                f.write("\n")
            f.write("\n".join(additions) + "\n")

    # For external dirs (--dir pointing outside a git repo), init as standalone git repo
    if not store.is_internal_pm_dir(root):
        if not git_ops.is_git_repo(root):
            git_ops.run_git("init", cwd=root, check=False)
            gitignore = root / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text("")
            git_ops.run_git("add", "-A", cwd=root, check=False)
            git_ops.run_git("commit", "-m", "pm: init project", cwd=root, check=False)

    click.echo(f"Created PM directory at {root}")
    click.echo(f"  target repo: {repo_url}")
    click.echo(f"  base branch: {base_branch}")
    click.echo(f"  backend: {backend}")
    click.echo()

    if no_import:
        click.echo("Run 'pm plan import' to bootstrap a PR graph from this repo.")
    else:
        _run_plan_import("Import from existing repo")


@cli.command("push")
def push_cmd():
    """Commit pm changes to a branch and optionally push/create a PR.

    Creates a pm/sync-<timestamp> branch with pm state changes committed.

    Backend behavior:
      local:   commits on branch locally (merge manually)
      vanilla: commits and pushes branch to remote
      github:  commits, pushes, and creates a PR via gh
    """
    root = state_root()
    data = store.load(root)
    backend = data.get("project", {}).get("backend", "vanilla")
    result = git_ops.push_pm_branch(root, backend=backend)

    if "error" in result:
        click.echo(result["error"], err=True)
        if "branch" not in result:
            raise SystemExit(1)

    if "branch" in result:
        click.echo(f"Created branch: {result['branch']}")
        if result.get("pr_url"):
            click.echo(f"PR created: {result['pr_url']}")
        elif result.get("pr_error"):
            click.echo(f"PR creation failed: {result['pr_error']}", err=True)
        elif result.get("push_error"):
            click.echo(f"Push failed: {result['push_error']}", err=True)
        elif backend == "vanilla":
            click.echo("Pushed branch to remote. Merge it to apply changes.")
        elif backend == "local":
            click.echo("Committed locally. Merge the branch to apply changes:")
            click.echo(f"  git merge {result['branch']}")


# --- Plan commands ---

@cli.group()
def plan():
    """Manage plans."""
    pass


@plan.command("add")
@click.argument("name")
@click.option("--new", "fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
def plan_add(name: str, fresh: bool):
    """Create a new plan and launch Claude to develop it."""
    root = state_root()
    data = store.load(root)
    plan_id = store.next_plan_id(data)
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
    plan_path.write_text(f"# {name}\n\n<!-- Describe the plan here -->\n")

    # Ensure notes file exists
    notes.ensure_notes_file(root)

    save_and_push(data, root, f"pm: add plan {plan_id}")
    click.echo(f"Created plan {plan_id}: {name}")
    click.echo(f"  Plan file: {plan_path}")

    notes_block = notes.notes_section(root)
    prompt = f"""\
Your goal: Help me develop a plan called "{name}" and write it to {plan_path}.

This session is managed by `pm` (project manager for Claude Code). You have access
to the `pm` CLI tool — run `pm help` to see available commands.

The plan file is at: {plan_path}

Ask me what this plan should accomplish. I'll describe it at a high level and
we'll iterate until the plan is clear and complete. Then write the final plan
to the file above as structured markdown.

The plan needs to be detailed enough that the next step (`pm plan review`) can
break it into individual PRs. Include scope, goals, key design decisions, and
any constraints.
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


@plan.command("review")
@click.argument("plan_id", default=None, required=False)
@click.option("--prs", "initial_prs", default=None, help="Seed the conversation with an initial PR list")
@click.option("--new", "fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
def plan_review(plan_id: str | None, initial_prs: str | None, fresh: bool):
    """Launch Claude to break a plan into PRs (written to plan file).

    If PLAN_ID is omitted, auto-selects when there's exactly one plan.
    """
    root = state_root()
    data = store.load(root)

    if plan_id is None:
        plans = data.get("plans") or []
        if len(plans) == 1:
            plan_id = plans[0]["id"]
        elif len(plans) == 0:
            click.echo("No plans. Create one with: pm plan add <name>", err=True)
            raise SystemExit(1)
        else:
            click.echo("Multiple plans. Specify one:", err=True)
            for p in plans:
                click.echo(f"  {p['id']}: {p['name']}", err=True)
            raise SystemExit(1)

    plan_entry = store.get_plan(data, plan_id)
    if not plan_entry:
        plans = data.get("plans") or []
        click.echo(f"Plan {plan_id} not found.", err=True)
        if plans:
            click.echo(f"Available plans: {', '.join(p['id'] for p in plans)}", err=True)
        raise SystemExit(1)

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
write them to the plan file so they can be loaded with `pm plan load`.

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

After writing, the user can run `pm plan load` to create all PRs at once.
{notes_block}"""

    claude = find_claude()
    if claude:
        session_key = f"plan:review:{plan_id}"
        if fresh:
            clear_session(root, session_key)
        click.echo(f"Launching Claude to review plan {plan_id}...")
        launch_claude(prompt, session_key=session_key, pm_root=root, resume=not fresh)
        # Background review
        check_prompt = review_mod.REVIEW_PROMPTS["plan-review"].format(path=plan_path)
        click.echo("Reviewing results... (background)")
        review_mod.review_step("plan review", f"Break plan {plan_id} into PRs", check_prompt, root)
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
        pr_lines.append(f"  {p['id']}: {p.get('title', '???')} [{p.get('status', '?')}]{dep_str}{desc_str}")

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

    if plan_id is None:
        plans = data.get("plans") or []
        if len(plans) == 1:
            plan_id = plans[0]["id"]
        elif len(plans) == 0:
            click.echo("No plans. Create one with: pm plan add <name>", err=True)
            raise SystemExit(1)
        else:
            click.echo("Multiple plans. Specify one:", err=True)
            for p in plans:
                click.echo(f"  {p['id']}: {p['name']}", err=True)
            raise SystemExit(1)

    plan_entry = store.get_plan(data, plan_id)
    if not plan_entry:
        click.echo(f"Plan {plan_id} not found.", err=True)
        raise SystemExit(1)

    plan_path = root / plan_entry["file"]
    if not plan_path.exists():
        click.echo(f"Plan file {plan_path} not found.", err=True)
        raise SystemExit(1)

    plan_content = plan_path.read_text()
    prs = parse_plan_prs(plan_content)

    if not prs:
        click.echo("No PRs found in plan file. Run 'pm plan review' first to add a ## PRs section.", err=True)
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

    # Build depends_on edit commands (second pass, referencing PR IDs)
    # We know the current next_pr_id, so we can predict IDs
    existing_prs = data.get("prs") or []
    if existing_prs:
        import re
        nums = [int(m.group(1)) for p in existing_prs if (m := re.match(r"pr-(\d+)", p["id"]))]
        next_num = max(nums) + 1 if nums else 1
    else:
        next_num = 1

    title_to_predicted_id = {}
    for i, pr in enumerate(prs):
        title_to_predicted_id[pr["title"]] = f"pr-{next_num + i:03d}"

    dep_commands = []
    for pr in prs:
        if pr["depends_on"]:
            pr_id = title_to_predicted_id[pr["title"]]
            dep_title = pr["depends_on"].strip()
            if dep_title in title_to_predicted_id:
                dep_id = title_to_predicted_id[dep_title]
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
        output = launch_claude_print(prompt, cwd=str(root))
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


@plan.command("add-fix")
@click.option("--review", "review_path", required=True, help="Path to review file")
def plan_add_fix(review_path: str):
    """Fix issues found by plan add review."""
    _run_fix_command("plan add", review_path)


@plan.command("review-fix")
@click.option("--review", "review_path", required=True, help="Path to review file")
def plan_review_fix(review_path: str):
    """Fix issues found by plan review review."""
    _run_fix_command("plan review", review_path)


@plan.command("deps-fix")
@click.option("--review", "review_path", required=True, help="Path to review file")
def plan_deps_fix(review_path: str):
    """Fix issues found by plan deps review."""
    _run_fix_command("plan deps", review_path)


@plan.command("load-fix")
@click.option("--review", "review_path", required=True, help="Path to review file")
def plan_load_fix(review_path: str):
    """Fix issues found by plan load review."""
    _run_fix_command("plan load", review_path)


def _run_plan_import(name: str):
    """Core logic for plan import — used by both `plan import` and `init`."""
    root = state_root()
    data = store.load(root)
    plan_id = store.next_plan_id(data)
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

Phase 2 — Discuss with me (do NOT skip this):
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

Once written, tell the user to run `pm plan load {plan_id}` to create all
the PRs in the project.
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


@plan.command("import-fix")
@click.option("--review", "review_path", required=True, help="Path to review file")
def plan_import_fix(review_path: str):
    """Fix issues found by plan import review."""
    _run_fix_command("plan import", review_path)


# --- PR commands ---

@cli.group()
def pr():
    """Manage PRs."""
    pass


@pr.command("add")
@click.argument("title")
@click.option("--plan", "plan_id", default=None, help="Associated plan ID")
@click.option("--depends-on", "depends_on", default=None, help="Comma-separated PR IDs")
@click.option("--description", "desc", default="", help="PR description")
def pr_add(title: str, plan_id: str, depends_on: str, desc: str):
    """Add a new PR to the project."""
    root = state_root()
    data = store.load(root)

    # Auto-select plan if there's exactly one
    if plan_id is None:
        plans = data.get("plans") or []
        if len(plans) == 1:
            plan_id = plans[0]["id"]

    pr_id = store.next_pr_id(data)
    slug = store.slugify(title)
    branch = f"pm/{pr_id}-{slug}"

    deps = []
    if depends_on:
        deps = [d.strip() for d in depends_on.split(",")]
        existing_ids = {p["id"] for p in (data.get("prs") or [])}
        unknown = [d for d in deps if d not in existing_ids]
        if unknown:
            click.echo(f"Unknown PR IDs in --depends-on: {', '.join(unknown)}", err=True)
            if existing_ids:
                click.echo(f"Available PRs: {', '.join(sorted(existing_ids))}", err=True)
            raise SystemExit(1)

    entry = {
        "id": pr_id,
        "plan": plan_id,
        "title": title,
        "branch": branch,
        "status": "pending",
        "depends_on": deps,
        "description": desc,
        "agent_machine": None,
        "gh_pr": None,
    }
    if data.get("prs") is None:
        data["prs"] = []
    data["prs"].append(entry)
    data["project"]["active_pr"] = pr_id

    save_and_push(data, root, f"pm: add {pr_id}")
    click.echo(f"Created {pr_id}: {title} (now active)")
    click.echo(f"  branch: {branch}")
    if deps:
        click.echo(f"  depends_on: {', '.join(deps)}")


@pr.command("edit")
@click.argument("pr_id")
@click.option("--title", default=None, help="New title")
@click.option("--depends-on", "depends_on", default=None, help="Comma-separated PR IDs (replaces existing)")
@click.option("--description", "desc", default=None, help="New description")
def pr_edit(pr_id: str, title: str | None, depends_on: str | None, desc: str | None):
    """Edit an existing PR's title, description, or dependencies."""
    root = state_root()
    data = store.load(root)
    pr_entry = store.get_pr(data, pr_id)
    if not pr_entry:
        prs = data.get("prs") or []
        click.echo(f"PR {pr_id} not found.", err=True)
        if prs:
            click.echo(f"Available PRs: {', '.join(p['id'] for p in prs)}", err=True)
        raise SystemExit(1)

    changes = []
    if title is not None:
        pr_entry["title"] = title
        changes.append(f"title={title}")
    if desc is not None:
        pr_entry["description"] = desc
        changes.append("description updated")
    if depends_on is not None:
        if depends_on == "":
            pr_entry["depends_on"] = []
            changes.append("depends_on cleared")
        else:
            deps = [d.strip() for d in depends_on.split(",")]
            existing_ids = {p["id"] for p in (data.get("prs") or [])}
            unknown = [d for d in deps if d not in existing_ids]
            if unknown:
                click.echo(f"Unknown PR IDs: {', '.join(unknown)}", err=True)
                raise SystemExit(1)
            pr_entry["depends_on"] = deps
            changes.append(f"depends_on={', '.join(deps)}")

    if not changes:
        click.echo("Nothing to change. Use --title, --depends-on, or --description.", err=True)
        raise SystemExit(1)

    save_and_push(data, root, f"pm: edit {pr_id}")
    click.echo(f"Updated {pr_id}: {', '.join(changes)}")


@pr.command("select")
@click.argument("pr_id")
def pr_select(pr_id: str):
    """Set the active PR.

    The active PR is used as the default when commands like pm pr start,
    pm pr done, pm prompt, etc. are run without specifying a PR ID.
    """
    root = state_root()
    data = store.load(root)
    pr_entry = store.get_pr(data, pr_id)
    if not pr_entry:
        prs = data.get("prs") or []
        click.echo(f"PR {pr_id} not found.", err=True)
        if prs:
            click.echo(f"Available PRs: {', '.join(p['id'] for p in prs)}", err=True)
        raise SystemExit(1)

    data["project"]["active_pr"] = pr_id
    save_and_push(data, root)
    click.echo(f"Active PR: {pr_id} ({pr_entry.get('title', '???')})")


@pr.command("list")
def pr_list():
    """List all PRs with status."""
    root = state_root()
    data = store.load(root)
    prs = data.get("prs") or []
    if not prs:
        click.echo("No PRs.")
        return

    active_pr = data.get("project", {}).get("active_pr")
    status_icons = {
        "pending": "⏳",
        "in_progress": "🔨",
        "in_review": "👀",
        "merged": "✅",
        "blocked": "🚫",
    }
    for p in prs:
        icon = status_icons.get(p.get("status", "pending"), "?")
        deps = p.get("depends_on") or []
        dep_str = f" <- [{', '.join(deps)}]" if deps else ""
        machine = p.get("agent_machine")
        machine_str = f" ({machine})" if machine else ""
        active_str = " *" if p["id"] == active_pr else ""
        click.echo(f"  {icon} {p['id']}: {p.get('title', '???')} [{p.get('status', '?')}]{dep_str}{machine_str}{active_str}")


@pr.command("graph")
def pr_graph():
    """Show static dependency graph."""
    root = state_root()
    data = store.load(root)
    prs = data.get("prs") or []
    click.echo(graph.render_static_graph(prs))


@pr.command("ready")
def pr_ready():
    """List PRs ready to start (all deps merged)."""
    root = state_root()
    data = store.load(root)
    prs = data.get("prs") or []
    ready = graph.ready_prs(prs)
    if not ready:
        click.echo("No PRs are ready to start.")
        return
    for p in ready:
        click.echo(f"  ⏳ {p['id']}: {p.get('title', '???')}")


@pr.command("start")
@click.argument("pr_id", default=None, required=False)
@click.option("--workdir", default=None, help="Custom work directory")
@click.option("--new", "fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
def pr_start(pr_id: str | None, workdir: str, fresh: bool):
    """Start working on a PR: clone, branch, print prompt.

    If PR_ID is omitted, uses the active PR if it's pending/ready, or
    auto-selects the next ready PR (when there's exactly one).
    """
    root = state_root()
    data = store.load(root)

    if pr_id is None:
        # Try active PR first
        active = data.get("project", {}).get("active_pr")
        if active:
            active_entry = store.get_pr(data, active)
            if active_entry and active_entry.get("status") == "pending":
                pr_id = active
                click.echo(f"Using active PR {pr_id}: {active_entry.get('title', '???')}")

    if pr_id is None:
        prs = data.get("prs") or []
        ready = graph.ready_prs(prs)
        if len(ready) == 1:
            pr_id = ready[0]["id"]
            click.echo(f"Auto-selected {pr_id}: {ready[0].get('title', '???')}")
        elif len(ready) == 0:
            click.echo("No PRs are ready to start.", err=True)
            raise SystemExit(1)
        else:
            click.echo("Multiple PRs are ready. Specify one:", err=True)
            for p in ready:
                click.echo(f"  {p['id']}: {p.get('title', '???')}", err=True)
            raise SystemExit(1)

    pr_entry = store.get_pr(data, pr_id)
    if not pr_entry:
        prs = data.get("prs") or []
        click.echo(f"PR {pr_id} not found.", err=True)
        if prs:
            click.echo(f"Available PRs: {', '.join(p['id'] for p in prs)}", err=True)
        else:
            click.echo("No PRs exist. Create one with: pm pr add <title>", err=True)
        raise SystemExit(1)

    if pr_entry.get("status") == "in_progress":
        click.echo(f"PR {pr_id} is already in_progress on {pr_entry.get('agent_machine', '???')}.", err=True)
        click.echo("Use --workdir to reuse the existing workdir, or 'pm prompt' to regenerate the prompt.", err=True)
        raise SystemExit(1)

    if pr_entry.get("status") == "merged":
        click.echo(f"PR {pr_id} is already merged.", err=True)
        raise SystemExit(1)

    repo_url = data["project"]["repo"]
    base_branch = data["project"].get("base_branch", "main")
    branch = pr_entry.get("branch", f"pm/{pr_id}")

    if workdir:
        work_path = Path(workdir).resolve()
    else:
        # Check if we already have a workdir for this PR
        existing_workdir = pr_entry.get("workdir")
        if existing_workdir and Path(existing_workdir).exists():
            work_path = Path(existing_workdir)
        else:
            # Need to clone first, then figure out the final path
            # Clone to a temp location under the project dir
            project_dir = _workdirs_dir(data)
            project_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = project_dir / f".tmp-{pr_id}"
            if tmp_path.exists():
                shutil.rmtree(tmp_path)
            click.echo(f"Cloning {repo_url}...")
            git_ops.clone(repo_url, tmp_path, branch=base_branch)

            # Cache repo_id now that we have a clone
            _resolve_repo_id(data, tmp_path, root)

            # Get the base commit hash for the branch directory name
            base_hash = git_ops.run_git(
                "rev-parse", "--short=8", "HEAD", cwd=tmp_path, check=False
            ).stdout.strip()

            # Final path: <project_dir>/<branch_slug>-<base_hash>
            # Re-resolve project_dir since _resolve_repo_id may have updated data
            branch_slug = store.slugify(branch.replace("/", "-"))
            dir_name = f"{branch_slug}-{base_hash}" if base_hash else branch_slug
            final_project_dir = _workdirs_dir(data)
            final_project_dir.mkdir(parents=True, exist_ok=True)
            work_path = final_project_dir / dir_name

            if work_path.exists():
                shutil.rmtree(tmp_path)
            else:
                shutil.move(str(tmp_path), str(work_path))

    if work_path.exists() and git_ops.is_git_repo(work_path):
        click.echo(f"Updating {work_path}...")
        git_ops.pull_rebase(work_path)

    click.echo(f"Checking out branch {branch}...")
    git_ops.checkout_branch(work_path, branch, create=True)

    # Update state
    pr_entry["status"] = "in_progress"
    pr_entry["agent_machine"] = platform.node()
    pr_entry["workdir"] = str(work_path)
    data["project"]["active_pr"] = pr_id
    save_and_push(data, root, f"pm: start {pr_id}")

    click.echo(f"\nPR {pr_id} is now in_progress on {platform.node()}")
    click.echo(f"Work directory: {work_path}")

    prompt = prompt_gen.generate_prompt(data, pr_id)

    claude = find_claude()
    if not claude:
        click.echo(f"\n{'='*60}")
        click.echo("CLAUDE PROMPT:")
        click.echo(f"{'='*60}\n")
        click.echo(prompt)
        return

    if tmux_mod.in_tmux():
        # Create a new tmux window for this PR
        pr_title = pr_entry.get("title", pr_id)
        window_name = store.slugify(pr_title)[:20]
        escaped_prompt = prompt.replace("'", "'\\''")
        cmd = f"claude '{escaped_prompt}'"
        try:
            session = os.environ.get("TMUX", "").split(",")[-1] if os.environ.get("TMUX") else ""
            # Get current session name
            import subprocess
            session_name = subprocess.run(
                ["tmux", "display-message", "-p", "#{session_name}"],
                capture_output=True, text=True
            ).stdout.strip()
            tmux_mod.new_window(session_name, window_name, cmd, str(work_path))
            click.echo(f"Launched Claude in tmux window '{window_name}'")
        except Exception as e:
            click.echo(f"Failed to create tmux window: {e}", err=True)
            click.echo("Launching Claude in current terminal...")
            session_key = f"pr:start:{pr_id}"
            if fresh:
                clear_session(root, session_key)
            launch_claude(prompt, cwd=str(work_path), session_key=session_key, pm_root=root, resume=not fresh)
    else:
        session_key = f"pr:start:{pr_id}"
        if fresh:
            clear_session(root, session_key)
        click.echo("Launching Claude...")
        launch_claude(prompt, cwd=str(work_path), session_key=session_key, pm_root=root, resume=not fresh)


@pr.command("done")
@click.argument("pr_id", default=None, required=False)
def pr_done(pr_id: str | None):
    """Mark a PR as in_review.

    If PR_ID is omitted, infers from cwd (if inside a workdir) or
    auto-selects when there's exactly one in_progress PR.
    """
    root = state_root()
    data = store.load(root)

    if pr_id is None:
        pr_id = _infer_pr_id(data, status_filter=("in_progress",))
        if pr_id is None:
            prs = data.get("prs") or []
            in_progress = [p for p in prs if p.get("status") == "in_progress"]
            if len(in_progress) == 0:
                click.echo("No in_progress PRs to mark done.", err=True)
            else:
                click.echo("Multiple in_progress PRs. Specify one:", err=True)
                for p in in_progress:
                    click.echo(f"  {p['id']}: {p.get('title', '???')} ({p.get('agent_machine', '')})", err=True)
            raise SystemExit(1)
        click.echo(f"Auto-selected {pr_id}")

    pr_entry = store.get_pr(data, pr_id)
    if not pr_entry:
        prs = data.get("prs") or []
        click.echo(f"PR {pr_id} not found.", err=True)
        if prs:
            click.echo(f"Available PRs: {', '.join(p['id'] for p in prs)}", err=True)
        raise SystemExit(1)

    if pr_entry.get("status") == "merged":
        click.echo(f"PR {pr_id} is already merged.", err=True)
        raise SystemExit(1)
    if pr_entry.get("status") == "in_review":
        click.echo(f"PR {pr_id} is already in_review.", err=True)
        raise SystemExit(1)
    if pr_entry.get("status") == "pending":
        click.echo(f"PR {pr_id} is pending — start it first with: pm pr start {pr_id}", err=True)
        raise SystemExit(1)

    pr_entry["status"] = "in_review"
    save_and_push(data, root, f"pm: done {pr_id}")
    click.echo(f"PR {pr_id} marked as in_review.")


@pr.command("sync")
def pr_sync():
    """Check for merged PRs and unblock dependents.

    Uses the configured backend (vanilla or github) to detect merges.
    Needs at least one workdir to exist (created by 'pm pr start').
    """
    root = state_root()
    data = store.load(root)
    base_branch = data["project"].get("base_branch", "main")
    prs = data.get("prs") or []
    backend = get_backend(data)
    updated = 0

    # Find any existing workdir to check merge status from
    target_workdir = None
    for p in prs:
        wd = p.get("workdir")
        if wd and Path(wd).exists() and git_ops.is_git_repo(wd):
            target_workdir = wd
            break
    if not target_workdir:
        workdirs_base = _workdirs_dir(data)
        if workdirs_base.exists():
            for d in workdirs_base.iterdir():
                if d.is_dir() and git_ops.is_git_repo(d):
                    target_workdir = str(d)
                    break

    if not target_workdir:
        click.echo("No workdirs found. Run 'pm pr start' on a PR first.", err=True)
        raise SystemExit(1)

    for pr_entry in prs:
        if pr_entry.get("status") not in ("in_review", "in_progress"):
            continue
        branch = pr_entry.get("branch", "")
        # Prefer PR's own workdir if it exists
        wd = pr_entry.get("workdir")
        check_dir = wd if (wd and Path(wd).exists()) else target_workdir

        if backend.is_merged(str(check_dir), branch, base_branch):
            pr_entry["status"] = "merged"
            click.echo(f"  ✅ {pr_entry['id']}: merged")
            updated += 1

    if updated:
        save_and_push(data, root, f"pm: sync - {updated} PRs merged")
    else:
        click.echo("No new merges detected.")

    # Show newly unblocked PRs
    ready = graph.ready_prs(prs)
    if ready:
        click.echo("\nNewly ready PRs:")
        for p in ready:
            click.echo(f"  ⏳ {p['id']}: {p.get('title', '???')}")


@pr.command("cleanup")
@click.argument("pr_id", default=None, required=False)
def pr_cleanup(pr_id: str | None):
    """Remove work directory for a merged PR.

    If PR_ID is omitted, auto-selects when there's exactly one merged PR
    with a workdir.
    """
    root = state_root()
    data = store.load(root)

    if pr_id is None:
        prs = data.get("prs") or []
        with_workdir = [p for p in prs if p.get("status") == "merged" and p.get("workdir")
                        and Path(p["workdir"]).exists()]
        if len(with_workdir) == 1:
            pr_id = with_workdir[0]["id"]
            click.echo(f"Auto-selected {pr_id}")
        elif len(with_workdir) == 0:
            click.echo("No merged PRs with workdirs to clean up.", err=True)
            raise SystemExit(1)
        else:
            click.echo("Multiple merged PRs have workdirs. Specify one:", err=True)
            for p in with_workdir:
                click.echo(f"  {p['id']}: {p.get('title', '???')}", err=True)
            raise SystemExit(1)

    pr_entry = store.get_pr(data, pr_id)
    if not pr_entry:
        prs = data.get("prs") or []
        click.echo(f"PR {pr_id} not found.", err=True)
        if prs:
            click.echo(f"Available PRs: {', '.join(p['id'] for p in prs)}", err=True)
        raise SystemExit(1)

    if pr_entry.get("status") not in ("merged", "in_review"):
        click.echo(f"Warning: {pr_id} status is '{pr_entry.get('status')}' (not merged).", err=True)
        click.echo("Cleaning up anyway.", err=True)

    work_path = None
    if pr_entry.get("workdir"):
        work_path = Path(pr_entry["workdir"])

    if work_path and work_path.exists():
        shutil.rmtree(work_path)
        click.echo(f"Removed {work_path}")
        pr_entry["workdir"] = None
        save_and_push(data, root, f"pm: cleanup {pr_id}")
    else:
        click.echo(f"No work directory found for {pr_id}.")


@cli.command("session")
def session_cmd():
    """Start a tmux session with TUI + notes editor.

    If no project exists yet, starts pm guide instead of the TUI so
    the guided workflow can initialize the project inside tmux.
    """
    if not tmux_mod.has_tmux():
        click.echo("tmux is required for 'pm session'. Install it first.", err=True)
        raise SystemExit(1)

    # Check if project exists
    try:
        root = state_root()
        data = store.load(root)
        has_project = True
    except (FileNotFoundError, SystemExit):
        root = None
        data = None
        has_project = False

    if has_project:
        project_name = data.get("project", {}).get("name", "unknown")
    else:
        # Derive session name from cwd
        project_name = Path.cwd().name

    session_name = f"pm-{project_name}"

    if tmux_mod.session_exists(session_name):
        click.echo(f"Attaching to existing session '{session_name}'...")
        tmux_mod.attach(session_name)
        return

    cwd = str(root) if root else str(Path.cwd())
    expected_root = root or (Path.cwd() / "pm")
    notes_path = expected_root / notes.NOTES_FILENAME
    editor = find_editor()

    # Clear stale pane registry and bump generation to invalidate old EXIT traps
    import time as _time
    generation = str(int(_time.time()))
    pane_layout.save_registry(session_name, {
        "session": session_name, "window": "0", "panes": [],
        "user_modified": False, "generation": generation,
    })

    # Always create session with TUI in the left pane
    click.echo(f"Creating tmux session '{session_name}'...")
    tmux_mod.create_session(session_name, cwd, "pm tui")

    # Forward key environment variables into the tmux session
    import subprocess as _sp
    for env_key in ("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS", "PM_PROJECT", "EDITOR", "PATH"):
        val = os.environ.get(env_key)
        if val:
            _sp.run(["tmux", "set-environment", "-t", session_name, env_key, val], check=False)

    # Get the TUI pane ID and window ID
    tui_pane = _sp.run(
        ["tmux", "list-panes", "-t", session_name, "-F", "#{pane_id}"],
        capture_output=True, text=True,
    ).stdout.strip().splitlines()[0]
    window_id = tmux_mod.get_window_id(session_name)

    # Register TUI pane in layout registry
    pane_layout.register_pane(session_name, window_id, tui_pane, "tui", "pm tui")

    def _wrap(cmd: str) -> str:
        """Wrap a pane command in bash with an EXIT trap for rebalancing."""
        escaped = cmd.replace("'", "'\\''")
        return (f"bash -c 'trap \"pm _pane-exited {session_name} {window_id} {generation} $TMUX_PANE\" EXIT; "
                f"{escaped}'")

    if has_project:
        # Existing project: TUI (left) | notes editor (right)
        notes.ensure_notes_file(root)
        notes_pane = tmux_mod.split_pane(session_name, "h", _wrap(f"pm notes {notes_path}"))
        pane_layout.register_pane(session_name, window_id, notes_pane, "notes", "pm notes")
    else:
        # Setup: TUI (top-left) | guide (right, focused)
        #         notes (bottom-left) |
        # Register notes before guide so guide (newest) gets the largest area
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        if not notes_path.exists():
            notes_path.write_text(notes.NOTES_WELCOME)
        notes_pane = tmux_mod.split_pane_at(tui_pane, "v", _wrap(f"pm notes {notes_path}"), background=True)
        pane_layout.register_pane(session_name, window_id, notes_pane, "notes", "pm notes")
        guide_pane = tmux_mod.split_pane(session_name, "h", _wrap("pm guide"))
        pane_layout.register_pane(session_name, window_id, guide_pane, "guide", "pm guide")

    # Apply initial balanced layout
    pane_layout.rebalance(session_name, window_id)

    if not has_project:
        tmux_mod.select_pane(guide_pane)

    # Bind prefix-R to rebalance in this session
    import subprocess as _sp
    _sp.run(["tmux", "bind-key", "-T", "prefix", "R",
             "run-shell", "pm rebalance"], check=False)

    # Global hook for kill-pane detection. The after-kill-pane hook
    # doesn't know which pane was killed, so _pane-closed reconciles
    # all registries against live tmux panes.
    _sp.run(["tmux", "set-hook", "-g", "after-kill-pane",
             "run-shell", "pm _pane-closed"], check=False)

    tmux_mod.attach(session_name)


@cli.command("prompt")
@click.argument("pr_id", default=None, required=False)
def prompt(pr_id: str | None):
    """Generate Claude prompt for a PR.

    If PR_ID is omitted, uses the active PR, infers from cwd, or
    auto-selects when there's exactly one in_progress PR.
    """
    root = state_root()
    data = store.load(root)

    if pr_id is None:
        # For prompt, try active PR regardless of status, then fall back to in_progress
        pr_id = _infer_pr_id(data)
        if pr_id is None:
            pr_id = _infer_pr_id(data, status_filter=("in_progress",))
        if pr_id is None:
            prs = data.get("prs") or []
            click.echo("No active or in_progress PR. Specify a PR ID.", err=True)
            if prs:
                click.echo(f"Available PRs: {', '.join(p['id'] for p in prs)}", err=True)
            raise SystemExit(1)

    pr_entry = store.get_pr(data, pr_id)
    if not pr_entry:
        prs = data.get("prs") or []
        click.echo(f"PR {pr_id} not found.", err=True)
        if prs:
            click.echo(f"Available PRs: {', '.join(p['id'] for p in prs)}", err=True)
        raise SystemExit(1)

    click.echo(prompt_gen.generate_prompt(data, pr_id))


@cli.command("tui")
def tui_cmd():
    """Launch the interactive TUI."""
    from pm_core.tui.app import ProjectManagerApp
    app = ProjectManagerApp()
    app.run()


@cli.command("_check", hidden=True)
def check_cmd():
    """Check if a PM repo is reachable (used by the bash entrypoint)."""
    try:
        state_root()
    except FileNotFoundError:
        raise SystemExit(1)


def _detect_git_repo() -> dict | None:
    """Detect the git state of cwd. Returns None if not a git repo.

    Return dict has 'type' key:
      - 'local': git repo with no remote
      - 'github': git repo with a github.com remote
      - 'vanilla': git repo with a non-GitHub remote
    """
    cwd = Path.cwd()
    if not git_ops.is_git_repo(cwd):
        return None

    branch_result = git_ops.run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd, check=False)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

    result = git_ops.run_git("remote", "get-url", "origin", cwd=cwd, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return {"url": None, "name": cwd.name, "branch": branch, "cwd": str(cwd), "type": "local"}

    remote_url = result.stdout.strip()
    name = remote_url.rstrip("/").split("/")[-1].replace(".git", "")
    backend_type = detect_backend(remote_url)
    return {"url": remote_url, "name": name, "branch": branch, "cwd": str(cwd), "type": backend_type}


def _getting_started_text() -> str:
    """Build a cohesive getting-started block, with repo-specific info if available."""
    repo_info = _detect_git_repo()

    lines = "\nGETTING STARTED\n"

    if repo_info:
        name = repo_info["name"]
        branch = repo_info["branch"]
        repo_type = repo_info["type"]

        if repo_type == "local":
            lines += f"  Detected local git repo '{name}' (branch: {branch}, no remote)\n\n"
        else:
            url = repo_info["url"]
            lines += f"  Detected repo: {name}\n"
            lines += f"    remote:  {url}\n"
            lines += f"    branch:  {branch}\n"
            lines += f"    backend: {repo_type}\n\n"

        if repo_type == "github":
            lines += "  Make sure 'gh' is installed and authenticated: gh auth status\n\n"
        elif repo_type == "vanilla":
            lines += "  The vanilla backend will be auto-selected (pure git, no gh CLI required).\n\n"

    lines += """\
  1. Initialize and import (from your target repo):
       pm init
     Sets up pm/ and launches Claude to analyze the repo, discuss with you,
     and write a PR graph to a plan file.

  2. Load PRs from the plan file into pm:
       pm plan load
     Parses the ## PRs section and creates the PRs non-interactively.

  Or start from scratch instead:
     pm init --no-import
     pm plan add "Add authentication"
     pm plan review

  5. Review and finalize dependencies:
       pm plan deps
     Launches Claude to check for missing or wrong dependencies.

  6. See what's ready to work on:
       pm pr ready

  7. Start a PR (clones, branches, launches Claude in tmux window or terminal):
       pm pr start

  8. When Claude is done, mark it:
       pm pr done

  9. Commit and share pm/ changes:
       pm push

  10. Check for merges and unblock dependents:
       pm pr sync

  Tip: 'pm session' starts a tmux session with TUI + notes editor.
  Arguments in [brackets] are optional — pm infers them when possible."""

    if repo_info and repo_info["name"]:
        lines += f"""

  Or use a standalone PM repo:
    pm init --dir /path/to/{repo_info['name']}-pm"""

    return lines


HELP_TEXT = """\
pm — Project Manager for Claude Code sessions

Manages a graph of PRs derived from plans, orchestrates parallel Claude Code
sessions, and provides an interactive terminal dashboard.

COMMANDS
  pm init [target-repo-url]     Create pm/ directory (auto-detects repo from cwd)
  pm push                       Commit pm/ changes to a branch and create PR
  pm session                    Start tmux session with TUI + notes editor
  pm plan add <name>            Add a plan and launch Claude to develop it
  pm plan list                  List plans
  pm plan review [plan-id]      Launch Claude to break plan into PRs
  pm plan deps                  Launch Claude to review/fix PR dependencies
  pm plan load [plan-id]        Create PRs from plan file (non-interactive)
  pm plan import [--name NAME]  Bootstrap PR graph from existing repo (interactive)
  pm plan fixes                 List pending review files with fix commands
  pm plan add-fix --review <f>  Fix issues from plan add review
  pm plan review-fix --review   Fix issues from plan review review
  pm plan deps-fix --review     Fix issues from plan deps review
  pm plan load-fix --review     Fix issues from plan load review
  pm plan import-fix --review   Fix issues from plan import review

  pm pr add <title>             Add a PR (becomes active) [--plan, --depends-on]
  pm pr edit <pr-id>            Edit PR title, description, or dependencies
  pm pr select <pr-id>          Set the active PR
  pm pr list                    List PRs with status (* = active)
  pm pr graph                   Show dependency tree
  pm pr ready                   Show PRs ready to start
  pm pr start [pr-id]           Clone, branch, launch Claude (tmux window or blocking)
  pm pr done [pr-id]            Mark PR as in_review
  pm pr sync                    Check for merged PRs
  pm pr cleanup [pr-id]         Remove workdir for merged PR

  pm cluster auto               Discover feature clusters automatically
  pm cluster explore            Interactively explore code clusters with Claude

  pm guide                      Guided workflow (init → plan → PRs → start)
  pm prompt [pr-id]             Print Claude prompt for a PR
  pm tui                        Launch interactive dashboard
  pm getting-started            Show getting started guide

OPTIONS
  -C <path>                     Path to PM directory (or set PM_PROJECT env var)
  --backend local|vanilla|github  Override auto-detected backend at init time

BACKENDS
  local     Local git only, no remote. 'pm push' commits on a branch locally.
  vanilla   Git with a remote. 'pm push' creates a branch and pushes it.
  github    Uses gh CLI for PR creation and merge detection. Auto-selected for
            github.com URLs.

NOTES
  By default, pm/ lives inside your target repo. Mutations only write files;
  use 'pm push' to commit and share changes.
  Notes in pm/notes.txt are included in all generated prompts.\
"""


@cli.command("help")
def help_cmd():
    """Show help and getting started guide."""
    click.echo(HELP_TEXT)

    # Show getting started only if pm/ hasn't been initialized
    try:
        state_root()
    except FileNotFoundError:
        click.echo(_getting_started_text())
        click.echo("\n  Run 'pm getting-started' to show this guide again.")


@cli.command("getting-started")
def getting_started_cmd():
    """Show getting started guide (always shown, even if pm/ exists)."""
    click.echo(_getting_started_text())


# ---------------------------------------------------------------------------
# cluster group
# ---------------------------------------------------------------------------

@cli.group()
def cluster():
    """Analyze codebase structure and discover feature clusters."""
    pass


@cluster.command("auto")
@click.option("--threshold", default=0.15, type=float, help="Merge threshold (0.0–1.0)")
@click.option("--max-commits", default=500, type=int, help="Max commits for co-change analysis")
@click.option("--weights", default=None, type=str,
              help="Metric weights: structural=0.2,semantic=0.3,cochange=0.2,callgraph=0.3")
@click.option("--output", "output_fmt", default="text", type=click.Choice(["plan", "json", "text"]),
              help="Output format")
def cluster_auto(threshold, max_commits, weights, output_fmt):
    """Discover feature clusters automatically."""
    from pm_core.cluster import extract_chunks, compute_edges, agglomerative_cluster, pre_partition
    from pm_core.cluster import clusters_to_plan_markdown, clusters_to_json, clusters_to_text
    from pm_core.cluster.cluster_graph import Cluster

    root = state_root()
    data = store.load(root)
    project = data.get("project", {})

    # Determine repo root
    if store.is_internal_pm_dir(root):
        repo_root = root.parent
    else:
        repo_url = project.get("repo", "")
        if repo_url and Path(repo_url).is_dir():
            repo_root = Path(repo_url)
        else:
            repo_root = Path.cwd()

    # Parse weights
    w = {"structural": 0.2, "semantic": 0.3, "cochange": 0.2, "callgraph": 0.3}
    if weights:
        for pair in weights.split(","):
            k, v = pair.split("=")
            w[k.strip()] = float(v.strip())

    click.echo(f"Extracting chunks from {repo_root} ...")
    chunks = extract_chunks(repo_root)
    click.echo(f"  {len(chunks)} chunks extracted")

    click.echo("Pre-partitioning ...")
    partitions = pre_partition(chunks)
    click.echo(f"  {len(partitions)} partitions: {', '.join(partitions.keys())}")

    clusters = []
    cluster_id = 0
    for part_name, part_chunks in partitions.items():
        file_count = sum(1 for c in part_chunks if c.kind in ("function", "class", "file"))
        if file_count <= 3:
            # Small partition — single cluster, no need for metric computation
            cluster_id += 1
            clusters.append(Cluster(
                id=str(cluster_id),
                chunk_ids={c.id for c in part_chunks if c.kind in ("function", "class", "file")},
                name=part_name,
            ))
            click.echo(f"  [{part_name}] {file_count} chunks → 1 cluster (small partition)")
            continue

        click.echo(f"  [{part_name}] computing edges for {len(part_chunks)} chunks ...")
        part_edges = compute_edges(part_chunks, weights=w, repo_root=repo_root, max_commits=max_commits)
        part_clusters = agglomerative_cluster(part_chunks, part_edges, threshold=threshold)
        # Re-number cluster IDs to be globally unique
        for c in part_clusters:
            cluster_id += 1
            c.id = str(cluster_id)
            c.name = f"{part_name}: {c.name}" if c.name else part_name
        clusters.extend(part_clusters)
        click.echo(f"  [{part_name}] {len(part_edges)} edges → {len(part_clusters)} clusters")

    click.echo(f"  {len(clusters)} clusters found")

    chunk_map = {c.id: c for c in chunks}

    if output_fmt == "text":
        click.echo("")
        click.echo(clusters_to_text(clusters, chunk_map))
    elif output_fmt == "json":
        click.echo(clusters_to_json(clusters, chunk_map))
    elif output_fmt == "plan":
        md = clusters_to_plan_markdown(clusters, chunk_map)
        plan_id = store.next_plan_id(data)
        plan_name = f"cluster-{plan_id}"
        plan_file = f"plans/{plan_name}.md"
        plan_path = root / plan_file
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(md)

        plans = data.setdefault("plans", [])
        plans.append({"id": plan_id, "name": plan_name, "file": plan_file, "status": "draft"})
        save_and_push(data, root, f"pm: cluster auto → {plan_id}")

        click.echo(f"Plan written to {plan_path}")
        click.echo(f"  Plan ID: {plan_id}")
        click.echo(f"  Load PRs with: pm plan load {plan_id}")


@cluster.command("explore")
@click.option("--bridged", is_flag=True, default=False,
              help="Launch in a bridge pane (for agent orchestration)")
@click.option("--new", "fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
def cluster_explore(bridged, fresh):
    """Interactively explore code clusters with Claude."""
    import tempfile
    from pm_core.cluster import extract_chunks, compute_edges, agglomerative_cluster, pre_partition
    from pm_core.cluster import clusters_to_text
    from pm_core.cluster.cluster_graph import Cluster

    root = state_root()
    data = store.load(root)

    if store.is_internal_pm_dir(root):
        repo_root = root.parent
    else:
        repo_url = data.get("project", {}).get("repo", "")
        if repo_url and Path(repo_url).is_dir():
            repo_root = Path(repo_url)
        else:
            repo_root = Path.cwd()

    click.echo("Extracting chunks ...")
    chunks = extract_chunks(repo_root)
    click.echo(f"  {len(chunks)} chunks")

    click.echo("Pre-partitioning ...")
    partitions = pre_partition(chunks)
    click.echo(f"  {len(partitions)} partitions: {', '.join(partitions.keys())}")

    w = {"structural": 0.25, "semantic": 0.25, "cochange": 0.25, "callgraph": 0.25}
    clusters = []
    cluster_id = 0
    for part_name, part_chunks in partitions.items():
        file_count = sum(1 for c in part_chunks if c.kind in ("function", "class", "file"))
        if file_count <= 3:
            cluster_id += 1
            clusters.append(Cluster(
                id=str(cluster_id),
                chunk_ids={c.id for c in part_chunks if c.kind in ("function", "class", "file")},
                name=part_name,
            ))
            continue
        part_edges = compute_edges(part_chunks, weights=w, repo_root=repo_root)
        part_clusters = agglomerative_cluster(part_chunks, part_edges, threshold=0.15)
        for c in part_clusters:
            cluster_id += 1
            c.id = str(cluster_id)
            c.name = f"{part_name}: {c.name}" if c.name else part_name
        clusters.extend(part_clusters)

    chunk_map = {c.id: c for c in chunks}
    summary = clusters_to_text(clusters, chunk_map)

    # Write summary to temp file for Claude context
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, prefix='pm-cluster-') as f:
        f.write(summary)
        f.write("\n\n--- Cluster Data ---\n")
        f.write(f"Total chunks: {len(chunks)}\n")
        f.write(f"Partitions: {len(partitions)} ({', '.join(partitions.keys())})\n")
        f.write(f"Clusters: {len(clusters)}\n")
        f.write(f"Threshold: 0.15\n")
        f.write(f"Weights: {w}\n")
        tmp_path = f.name

    prompt = (
        f"Your goal: Help the user refine code clusters into a plan they're happy with, "
        f"then create it using `pm cluster auto --output plan`.\n\n"
        f"This session is managed by `pm` (project manager for Claude Code). You have access "
        f"to the `pm` CLI tool — run `pm help` to see available commands.\n\n"
        f"I've analyzed the codebase and found {len(clusters)} code clusters. "
        f"The cluster summary is in {tmp_path}. Read it to understand the current groupings.\n\n"
        f"Discuss the clusters with the user. You can suggest:\n"
        f"- Adjusting the threshold (current: 0.15, higher = fewer larger clusters)\n"
        f"- Changing metric weights (structural, semantic, cochange, callgraph)\n"
        f"- Splitting or merging specific clusters\n\n"
        f"Re-run `pm cluster auto` with different parameters to iterate. When the user "
        f"is happy, run `pm cluster auto --output plan` to create the plan, then "
        f"`pm plan load` to create the PRs."
    )

    claude = find_claude()
    if not claude:
        click.echo("Claude CLI not found. Install it to use interactive explore.", err=True)
        click.echo(f"\nCluster summary written to: {tmp_path}")
        raise SystemExit(1)

    if bridged:
        import time
        from pm_core.claude_launcher import launch_bridge_in_tmux

        if not tmux_mod.in_tmux():
            click.echo("--bridged requires running inside tmux.", err=True)
            raise SystemExit(1)

        import subprocess as _sp
        session_name = _sp.run(
            ["tmux", "display-message", "-p", "#{session_name}"],
            capture_output=True, text=True,
        ).stdout.strip()

        socket_path = launch_bridge_in_tmux(prompt, cwd=str(repo_root), session_name=session_name)

        # Wait for socket to appear
        for _ in range(50):
            if os.path.exists(socket_path):
                break
            time.sleep(0.1)
        else:
            click.echo(f"Timed out waiting for bridge socket: {socket_path}", err=True)
            raise SystemExit(1)

        click.echo(f"Bridge socket: {socket_path}")
        return

    session_key = "cluster:explore"
    if fresh:
        clear_session(root, session_key)
    launch_claude(prompt, cwd=str(repo_root), session_key=session_key, pm_root=root, resume=not fresh)


def _in_pm_tmux_session() -> bool:
    """Check if we're in a tmux session created by pm (named pm-*)."""
    if not tmux_mod.in_tmux():
        return False
    import subprocess as _sp
    result = _sp.run(
        ["tmux", "display-message", "-p", "#{session_name}"],
        capture_output=True, text=True,
    )
    session_name = result.stdout.strip()
    return session_name.startswith("pm-")


@cli.group(invoke_without_command=True)
@click.option("--step", default=None, help="Force a specific workflow step")
@click.option("--new", "fresh", is_flag=True, default=False, help="Start a fresh session (don't resume)")
@click.pass_context
def guide(ctx, step, fresh):
    """Guided workflow — walks through init -> plan -> PRs -> start."""
    if ctx.invoked_subcommand is not None:
        return
    _run_guide(step, fresh=fresh)


@guide.command("done", hidden=True)
def guide_done_cmd():
    """Mark the current guide step as completed."""
    try:
        root = state_root()
    except (FileNotFoundError, SystemExit):
        root = None

    if root is None:
        click.echo("No project found.", err=True)
        raise SystemExit(1)

    started = guide_mod.get_started_step(root)
    if started is None:
        click.echo("No guide step has been started yet.", err=True)
        raise SystemExit(1)

    completed = guide_mod.get_completed_step(root)
    started_idx = guide_mod.STEP_ORDER.index(started) if started in guide_mod.STEP_ORDER else 0
    completed_idx = guide_mod.STEP_ORDER.index(completed) if completed in guide_mod.STEP_ORDER else -1

    if completed_idx >= started_idx:
        click.echo("Already completed.")
        return

    state = started
    guide_mod.mark_step_completed(root, state)
    desc = guide_mod.STEP_DESCRIPTIONS.get(state, state)
    click.echo(f"Step completed: {desc}")


def _run_guide(step, fresh=False):
    from pm_core.claude_launcher import find_claude, _skip_permissions, load_session, save_session

    # Detect state
    try:
        root = state_root()
    except (FileNotFoundError, SystemExit):
        root = None

    if step:
        state = step
        ctx = {}
        if root:
            try:
                data = store.load(root)
                ctx = {"data": data, "root": root}
            except Exception:
                pass
    else:
        state, ctx = guide_mod.resolve_guide_step(root)

    root = ctx.get("root", root)

    # Terminal states
    if state == "all_done":
        if root:
            guide_mod.mark_step_started(root, state)
        click.echo("All PRs are merged. Project complete!")
        return

    if state == "all_in_progress":
        if root:
            guide_mod.mark_step_started(root, state)
        click.echo("All PRs are in progress or waiting for review.")
        click.echo("Run 'pm pr list' to see status, or 'pm pr sync' to check for merges.")
        return

    # Non-interactive steps
    if state == "has_plan_prs":
        click.echo("Loading PRs from plan file...")
        guide_mod.run_non_interactive_step(state, ctx, root)
        # Auto-chain
        if _in_pm_tmux_session():
            os.execvp("pm", ["pm", "guide"])
        else:
            click.echo("\nNext: run 'pm guide' to continue.")
        return

    # Interactive steps
    prompt = guide_mod.build_guide_prompt(state, ctx, root)
    if prompt is None:
        click.echo(f"Unknown state: {state}")
        return

    step_desc = guide_mod.STEP_DESCRIPTIONS.get(state, state)
    n = guide_mod.step_number(state)
    click.echo(f"Step {n}: {step_desc}")

    if root:
        guide_mod.mark_step_started(root, state)

    claude = find_claude()
    if not claude:
        click.echo("\nClaude CLI not found. Copy-paste this prompt into Claude Code:\n")
        click.echo(f"---\n{prompt}\n---")
        return

    # After deps review, mark as reviewed before chaining
    post_hook = None
    if state == "needs_deps_review" and root:
        post_hook = lambda: guide_mod.set_deps_reviewed(root)

    session_key = f"guide:{state}"

    if fresh and root:
        clear_session(root, session_key)

    if _in_pm_tmux_session():
        escaped = prompt.replace("'", "'\\''")
        skip = " --dangerously-skip-permissions" if _skip_permissions() else ""
        resume_flag = ""
        if root and not fresh:
            resume_id = load_session(root, session_key)
            if resume_id:
                resume_flag = f" --resume {resume_id}"

        # Build command chain with:
        # 1. Capture stderr to temp file while showing on terminal (via tee)
        # 2. Extract session_id after claude exits
        # 3. Loop guard before restarting
        stderr_file = f"/tmp/pm-claude-stderr-$$.log"
        extract_cmd = f"pm _extract-session '{session_key}' {stderr_file} '{root}'"
        cleanup_cmd = f"rm -f {stderr_file}"
        loop_guard = f"pm _loop-guard guide-{state}"

        claude_cmd = f"claude --verbose{skip}{resume_flag} '{escaped}' 2> >(tee {stderr_file} >&2)"

        if post_hook:
            post_cmd = f"pm guide done ; python -c \"from pm_core.guide import set_deps_reviewed; from pathlib import Path; set_deps_reviewed(Path('{root}'))\""
        else:
            post_cmd = "pm guide done"

        cmd = f"{claude_cmd} ; {extract_cmd} ; {cleanup_cmd} ; {post_cmd} ; {loop_guard} && pm guide"

        # Log the full command for debugging
        import logging as _logging
        _log = _logging.getLogger("pm.guide")
        _log.info("guide chain: skip_permissions=%s env=%s", _skip_permissions(),
                   os.environ.get("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS"))
        _log.info("guide chain cmd: %s", cmd[:100] + "...")
        # Also print to stderr so it's visible in the pane
        import sys
        print(f"[pm guide] skip_permissions={_skip_permissions()} flag='{skip.strip()}'", file=sys.stderr)
        os.execvp("bash", ["bash", "-c", cmd])
    else:
        launch_claude(prompt, session_key=session_key, pm_root=root, resume=not fresh)
        if post_hook:
            post_hook()
        # Print next step
        next_state, _ = guide_mod.detect_state(root)
        next_desc = guide_mod.STEP_DESCRIPTIONS.get(next_state, next_state)
        click.echo(f"\nNext step: {next_desc}")
        click.echo("Run 'pm guide' to continue.")


@cli.command("notes")
@click.argument("notes_file", default=None, required=False)
@click.option("--disable-splash", is_flag=True, help="Disable the splash screen for this repo.")
def notes_cmd(notes_file: str | None, disable_splash: bool):
    """Open the session notes file in your editor.

    Shows a welcome splash screen before opening the editor.
    Use --disable-splash to permanently disable it for this repo.
    """
    if notes_file is None:
        try:
            root = state_root()
        except (FileNotFoundError, SystemExit):
            root = Path.cwd() / "pm"
        notes_file = str(root / notes.NOTES_FILENAME)
    path = Path(notes_file)
    pm_dir = path.parent
    no_splash_marker = pm_dir / ".no-notes-splash"
    editor = find_editor()

    if disable_splash:
        no_splash_marker.touch()
        click.echo("Splash screen disabled for this repo.")
        return

    # Ensure file exists
    if not path.exists():
        pm_dir.mkdir(parents=True, exist_ok=True)
        path.write_text("")

    # Skip splash if disabled
    if no_splash_marker.exists():
        os.execvp(editor, [editor, notes_file])

    # Show the welcome content as a splash screen
    import sys
    sys.stdout.write("\033[2J\033[H")  # clear + home
    sys.stdout.write(notes.NOTES_WELCOME)
    sys.stdout.flush()

    # Wait for a single keypress (raw mode)
    import tty
    import termios
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    os.execvp(editor, [editor, notes_file])



@cli.command("_extract-session", hidden=True)
@click.argument("session_key")
@click.argument("stderr_file")
@click.argument("pm_root")
def extract_session_cmd(session_key: str, stderr_file: str, pm_root: str):
    """Internal: extract session_id from stderr file and save to registry."""
    from pm_core.claude_launcher import _parse_session_id, save_session
    stderr_path = Path(stderr_file)
    if not stderr_path.exists():
        return
    try:
        stderr_text = stderr_path.read_text()
        sid = _parse_session_id(stderr_text)
        if sid:
            save_session(Path(pm_root), session_key, sid)
    except Exception:
        pass  # Best effort


@cli.command("_loop-guard", hidden=True)
@click.argument("loop_id")
def loop_guard_cmd(loop_id: str):
    """Internal: guard against rapid restart loops.

    Tracks timestamps of restarts. If 5 restarts happen in <7 seconds,
    exits with code 1 to break the loop. Always sleeps 1 second.
    """
    import time
    loop_file = Path.home() / ".pm-pane-registry" / f"loop-{loop_id}.json"
    loop_file.parent.mkdir(parents=True, exist_ok=True)

    now = time.time()
    timestamps = []

    if loop_file.exists():
        try:
            import json
            timestamps = json.loads(loop_file.read_text())
            if not isinstance(timestamps, list):
                timestamps = []
        except Exception:
            timestamps = []

    # Keep only timestamps from the last 10 seconds
    timestamps = [t for t in timestamps if now - t < 10]
    timestamps.append(now)

    # Check for rapid restarts: 5+ restarts in <7 seconds
    if len(timestamps) >= 5:
        oldest_recent = timestamps[-5]
        if now - oldest_recent < 7:
            click.echo(f"Loop guard triggered: {len(timestamps)} restarts in {now - oldest_recent:.1f}s", err=True)
            click.echo("Breaking loop to prevent runaway restarts.", err=True)
            # Clear the timestamps so next manual run works
            loop_file.unlink(missing_ok=True)
            raise SystemExit(1)

    # Save updated timestamps
    import json
    loop_file.write_text(json.dumps(timestamps))

    # Sleep before allowing restart
    time.sleep(1)


@cli.command("_pane-exited", hidden=True)
@click.argument("session")
@click.argument("window")
@click.argument("generation")
@click.argument("pane_id", default="")
def pane_exited_cmd(session: str, window: str, generation: str, pane_id: str):
    """Internal: handle pane exit — unregister and rebalance."""
    pane_layout.handle_pane_exited(session, window, generation, pane_id)


@cli.command("_pane-closed", hidden=True)
def pane_closed_cmd():
    """Internal: handle pane close from global tmux hook."""
    pane_layout.handle_any_pane_closed()


@cli.command("_pane-opened", hidden=True)
@click.argument("session")
@click.argument("window")
@click.argument("pane_id")
def pane_opened_cmd(session: str, window: str, pane_id: str):
    """Internal: handle tmux after-split-window hook."""
    pane_layout.handle_pane_opened(session, window, pane_id)


@cli.command("rebalance")
def rebalance_cmd():
    """Re-enable auto-balanced layout and rebalance panes.

    Use this after manually resizing panes to switch back to
    automatic layout management.
    """
    if not tmux_mod.in_tmux():
        click.echo("Must be run from within a tmux session.", err=True)
        raise SystemExit(1)

    session = tmux_mod.get_session_name()
    window = tmux_mod.get_window_id(session)

    data = pane_layout.load_registry(session)
    if not data["panes"]:
        click.echo("No panes registered for this session.", err=True)
        raise SystemExit(1)

    data["user_modified"] = False
    pane_layout.save_registry(session, data)

    pane_layout.rebalance(session, window)
    click.echo("Layout rebalanced.")


def main():
    cli()
