"""Click CLI definitions for pm."""

import json
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path

import click

from pm_core import store, graph, git_ops, prompt_gen, notes
from pm_core import pr_sync as pr_sync_mod

# Set up logging to file for debugging
_log_dir = Path.home() / ".pm-pane-registry"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_handler = logging.FileHandler(_log_dir / "cli.log")
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
_log = logging.getLogger("pm.cli")
_log.addHandler(_log_handler)
_log.setLevel(logging.DEBUG)
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


def _pr_id_num(pr_id: str) -> int:
    """Extract numeric part from pr-NNN id for sorting."""
    # pr-001 → 1, pr-010 → 10
    parts = pr_id.split("-")
    try:
        return int(parts[1])
    except (IndexError, ValueError):
        return 0


def _pr_display_id(pr: dict) -> str:
    """Display ID for a PR: prefer GitHub #N, fall back to local pr-NNN."""
    gh = pr.get("gh_pr_number")
    return f"#{gh}" if gh else pr["id"]


def save_and_push(data: dict, root: Path, message: str = "pm: update state") -> None:
    """Save state. Use 'pm push' to commit and share changes."""
    store.save(data, root)


def trigger_tui_refresh() -> None:
    """Send refresh key to TUI pane in the pm session for the current directory."""
    try:
        if not tmux_mod.has_tmux():
            return
        # Use _find_tui_pane which correctly matches session by cwd
        tui_pane, session = _find_tui_pane()
        if tui_pane and session:
            tmux_mod.send_keys_literal(tui_pane, "r")
            _log.debug("Sent refresh to TUI pane %s in session %s", tui_pane, session)
    except Exception as e:
        _log.debug("Could not trigger TUI refresh: %s", e)


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
            remotes = git_ops.list_remotes(cwd)
            if remotes:
                # Use backend_override hint if available for better selection
                selection = git_ops.select_remote(remotes, preferred_backend=backend_override)
                if "selected" in selection and selection["selected"]:
                    _, repo_url = selection["selected"]
                elif "ambiguous" in selection:
                    # Let user choose from ambiguous remotes
                    click.echo("Multiple git remotes found:")
                    for i, (name, url) in enumerate(selection["ambiguous"], 1):
                        click.echo(f"  {i}. {name}: {url}")
                    click.echo()
                    choice = click.prompt(
                        "Choose a remote",
                        type=click.IntRange(1, len(selection["ambiguous"])),
                        default=1,
                    )
                    _, repo_url = selection["ambiguous"][choice - 1]
                else:
                    # No remotes selected - use local path
                    repo_url = str(cwd)
            else:
                # No remotes - use local path
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

    # Import existing GitHub PRs if using the GitHub backend
    if backend == "github":
        _import_github_prs(root, data)

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
    trigger_tui_refresh()

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


def _import_github_prs(root: Path, data: dict) -> None:
    """Import existing GitHub PRs into yaml during init."""
    from pm_core import gh_ops

    # Determine repo directory for gh CLI
    if store.is_internal_pm_dir(root):
        repo_dir = str(root.parent)
    else:
        repo_url = data["project"].get("repo", "")
        if repo_url and Path(repo_url).is_dir():
            repo_dir = repo_url
        else:
            repo_dir = str(Path.cwd())

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
        is_draft = gh_pr.get("isDraft", False)
        gh_s = gh_pr.get("state", "OPEN")

        if gh_s == "MERGED":
            status = "merged"
        elif gh_s == "CLOSED":
            status = "closed"
        elif gh_s == "OPEN":
            status = "in_progress" if is_draft else "in_review"
        else:
            status = "pending"

        existing_ids = {p["id"] for p in data["prs"]}
        pr_id = f"pr-{number:03d}"
        if pr_id in existing_ids:
            pr_id = store.next_pr_id(data)

        entry = {
            "id": pr_id,
            "plan": None,
            "title": title,
            "branch": branch,
            "status": status,
            "depends_on": [],
            "description": gh_pr.get("body", "") or "",
            "agent_machine": None,
            "gh_pr": gh_pr.get("url", ""),
            "gh_pr_number": number,
        }
        data["prs"].append(entry)
        imported += 1
        click.echo(f"  + {pr_id}: {title} [{status}] (#{number})")

    if imported:
        store.save(data, root)
        click.echo(f"  Imported {imported} PR(s) from GitHub.")


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
        "gh_pr_number": None,
    }

    if data.get("prs") is None:
        data["prs"] = []
    data["prs"].append(entry)
    data["project"]["active_pr"] = pr_id

    save_and_push(data, root, f"pm: add {pr_id}")
    click.echo(f"Created {_pr_display_id(entry)}: {title} (now active)")
    click.echo(f"  branch: {branch}")
    if deps:
        click.echo(f"  depends_on: {', '.join(deps)}")
    if entry.get("gh_pr"):
        click.echo(f"  draft PR: {entry['gh_pr']}")
    trigger_tui_refresh()


@pr.command("edit")
@click.argument("pr_id")
@click.option("--title", default=None, help="New title")
@click.option("--depends-on", "depends_on", default=None, help="Comma-separated PR IDs (replaces existing)")
@click.option("--description", "desc", default=None, help="New description")
@click.option("--status", default=None, type=click.Choice(["pending", "in_progress", "in_review", "merged", "closed"]),
              help="New status (pending, in_progress, in_review, merged, closed)")
def pr_edit(pr_id: str, title: str | None, depends_on: str | None, desc: str | None, status: str | None):
    """Edit an existing PR's title, description, dependencies, or status."""
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
    if status is not None:
        old_status = pr_entry.get("status", "pending")
        pr_entry["status"] = status
        changes.append(f"status: {old_status} → {status}")
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
        # No flags given — open in $EDITOR
        import tempfile
        editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))
        current_title = pr_entry.get("title", "")
        current_desc = pr_entry.get("description", "")
        current_deps = ", ".join(pr_entry.get("depends_on") or [])
        current_status = pr_entry.get("status", "pending")

        template = (
            f"# Editing {pr_id}\n"
            f"# Lines starting with # are ignored.\n"
            f"# Save and exit to apply changes. Exit without saving to cancel.\n"
            f"\n"
            f"title: {current_title}\n"
            f"status: {current_status}\n"
            f"depends_on: {current_deps}\n"
            f"\n"
            f"# Description (everything below this line):\n"
            f"{current_desc}\n"
        )

        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(template)
            tmp_path = f.name

        try:
            mtime_before = os.path.getmtime(tmp_path)
            ret = subprocess.call([editor, tmp_path])
            if ret != 0:
                click.echo("Editor exited with error. No changes made.", err=True)
                raise SystemExit(1)
            mtime_after = os.path.getmtime(tmp_path)
            if mtime_before == mtime_after:
                click.echo("No changes made.")
                raise SystemExit(0)

            with open(tmp_path) as f:
                raw = f.read()
        finally:
            os.unlink(tmp_path)

        # Parse the edited file
        desc_lines = []
        in_desc = False
        new_title = current_title
        new_status = current_status
        new_deps_str = current_deps
        for line in raw.splitlines():
            if line.startswith("#"):
                if "description" in line.lower() and "below" in line.lower():
                    in_desc = True
                continue
            if in_desc:
                desc_lines.append(line)
            elif line.startswith("title:"):
                new_title = line[len("title:"):].strip()
            elif line.startswith("status:"):
                new_status = line[len("status:"):].strip()
            elif line.startswith("depends_on:"):
                new_deps_str = line[len("depends_on:"):].strip()

        new_desc = "\n".join(desc_lines).strip()

        if new_title != current_title:
            pr_entry["title"] = new_title
            changes.append(f"title={new_title}")
        if new_desc != current_desc.strip():
            pr_entry["description"] = new_desc
            changes.append("description updated")
        if new_status != current_status:
            valid = {"pending", "in_progress", "in_review", "merged", "closed"}
            if new_status not in valid:
                click.echo(f"Invalid status '{new_status}'. Must be one of: {', '.join(sorted(valid))}", err=True)
                raise SystemExit(1)
            pr_entry["status"] = new_status
            changes.append(f"status: {current_status} → {new_status}")
        if new_deps_str != current_deps:
            if not new_deps_str:
                pr_entry["depends_on"] = []
                changes.append("depends_on cleared")
            else:
                deps = [d.strip() for d in new_deps_str.split(",")]
                existing_ids = {p["id"] for p in (data.get("prs") or [])}
                unknown = [d for d in deps if d not in existing_ids]
                if unknown:
                    click.echo(f"Unknown PR IDs: {', '.join(unknown)}", err=True)
                    raise SystemExit(1)
                pr_entry["depends_on"] = deps
                changes.append(f"depends_on={', '.join(deps)}")

        if not changes:
            click.echo("No changes made.")
            raise SystemExit(0)

    save_and_push(data, root, f"pm: edit {pr_id}")
    click.echo(f"Updated {pr_id}: {', '.join(changes)}")
    trigger_tui_refresh()


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
    trigger_tui_refresh()


@pr.command("list")
def pr_list():
    """List all PRs with status."""
    root = state_root()
    data = store.load(root)

    # Sync to detect merged PRs (if interval allows)
    data, result = pr_sync_mod.sync_prs_quiet(root, data)
    if result.synced and result.updated_count > 0:
        click.echo(f"Synced: {result.updated_count} PR(s) merged")
        store.save(data, root)

    prs = data.get("prs") or []
    if not prs:
        click.echo("No PRs.")
        return

    # Sort newest first (by gh_pr_number descending, then pr id descending)
    prs = sorted(prs, key=lambda p: (p.get("gh_pr_number") or _pr_id_num(p["id"])), reverse=True)

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
        click.echo(f"  {icon} {_pr_display_id(p)}: {p.get('title', '???')} [{p.get('status', '?')}]{dep_str}{machine_str}{active_str}")


@pr.command("graph")
def pr_graph():
    """Show static dependency graph."""
    root = state_root()
    data = store.load(root)

    # Sync to detect merged PRs (if interval allows)
    data, result = pr_sync_mod.sync_prs_quiet(root, data)
    if result.synced and result.updated_count > 0:
        click.echo(f"Synced: {result.updated_count} PR(s) merged")
        store.save(data, root)

    prs = data.get("prs") or []
    click.echo(graph.render_static_graph(prs))


@pr.command("ready")
def pr_ready():
    """List PRs ready to start (all deps merged)."""
    root = state_root()
    data = store.load(root)

    # Sync to detect merged PRs (if interval allows)
    data, result = pr_sync_mod.sync_prs_quiet(root, data)
    if result.synced and result.updated_count > 0:
        click.echo(f"Synced: {result.updated_count} PR(s) merged")
        store.save(data, root)

    prs = data.get("prs") or []
    ready = graph.ready_prs(prs)
    if not ready:
        click.echo("No PRs are ready to start.")
        return
    for p in ready:
        click.echo(f"  ⏳ {_pr_display_id(p)}: {p.get('title', '???')}")


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
                click.echo(f"Using active PR {_pr_display_id(active_entry)}: {active_entry.get('title', '???')}")

    if pr_id is None:
        prs = data.get("prs") or []
        ready = graph.ready_prs(prs)
        if len(ready) == 1:
            pr_id = ready[0]["id"]
            click.echo(f"Auto-selected {_pr_display_id(ready[0])}: {ready[0].get('title', '???')}")
        elif len(ready) == 0:
            click.echo("No PRs are ready to start.", err=True)
            raise SystemExit(1)
        else:
            click.echo("Multiple PRs are ready. Specify one:", err=True)
            for p in ready:
                click.echo(f"  {_pr_display_id(p)}: {p.get('title', '???')}", err=True)
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
        # If already in_progress, reuse existing workdir if available
        existing_workdir = pr_entry.get("workdir")
        if existing_workdir and Path(existing_workdir).exists():
            click.echo(f"PR {pr_id} is already in_progress, reusing existing workdir.")
            workdir = existing_workdir  # Set workdir so it gets used below
        else:
            click.echo(f"PR {pr_id} is already in_progress on {pr_entry.get('agent_machine', '???')}.", err=True)
            click.echo("No existing workdir found. Use 'pm prompt' to regenerate the prompt.", err=True)
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

    # For GitHub backend: push branch and create draft PR if not already set
    backend_name = data["project"].get("backend", "vanilla")
    if backend_name == "github" and not pr_entry.get("gh_pr_number"):
        base_branch = data["project"].get("base_branch", "main")
        title = pr_entry.get("title", pr_id)
        desc = pr_entry.get("description", "")

        # Create empty commit so the branch has something to push
        commit_msg = f"Start work on: {title}\n\nPR: {pr_id}"
        git_ops.run_git("commit", "--allow-empty", "-m", commit_msg, cwd=work_path)

        click.echo(f"Pushing branch {branch}...")
        push_result = git_ops.run_git("push", "-u", "origin", branch, cwd=work_path, check=False)
        if push_result.returncode != 0:
            click.echo(f"Warning: Failed to push branch: {push_result.stderr}", err=True)
        else:
            click.echo("Creating draft PR on GitHub...")
            from pm_core import gh_ops
            pr_info = gh_ops.create_draft_pr(str(work_path), title, base_branch, desc)
            if pr_info:
                pr_entry["gh_pr"] = pr_info["url"]
                pr_entry["gh_pr_number"] = pr_info["number"]
                click.echo(f"Draft PR created: {pr_info['url']}")
            else:
                click.echo("Warning: Failed to create draft PR.", err=True)

    # Update state
    pr_entry["status"] = "in_progress"
    pr_entry["agent_machine"] = platform.node()
    pr_entry["workdir"] = str(work_path)
    data["project"]["active_pr"] = pr_id
    save_and_push(data, root, f"pm: start {pr_id}")
    trigger_tui_refresh()

    click.echo(f"\nPR {_pr_display_id(pr_entry)} is now in_progress on {platform.node()}")
    click.echo(f"Work directory: {work_path}")

    prompt = prompt_gen.generate_prompt(data, pr_id)

    claude = find_claude()
    if not claude:
        click.echo(f"\n{'='*60}")
        click.echo("CLAUDE PROMPT:")
        click.echo(f"{'='*60}\n")
        click.echo(prompt)
        return

    # Try to launch in the pm tmux session
    if tmux_mod.has_tmux():
        pm_session = _get_session_name_for_cwd()
        if tmux_mod.session_exists(pm_session):
            window_name = _pr_display_id(pr_entry)
            escaped_prompt = prompt.replace("'", "'\\''")
            cmd = f"claude '{escaped_prompt}'"
            try:
                tmux_mod.new_window(pm_session, window_name, cmd, str(work_path))
                click.echo(f"Launched Claude in tmux window '{window_name}' (session: {pm_session})")
                return
            except Exception as e:
                click.echo(f"Failed to create tmux window: {e}", err=True)
                click.echo("Launching Claude in current terminal...")

    # Fall through: launch interactively in current terminal
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
                    click.echo(f"  {_pr_display_id(p)}: {p.get('title', '???')} ({p.get('agent_machine', '')})", err=True)
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

    # For GitHub backend: upgrade draft PR to ready for review
    backend_name = data["project"].get("backend", "vanilla")
    gh_pr_number = pr_entry.get("gh_pr_number")
    workdir = pr_entry.get("workdir")

    if backend_name == "github" and gh_pr_number and workdir:
        from pm_core import gh_ops
        click.echo(f"Marking PR #{gh_pr_number} as ready for review...")
        if gh_ops.mark_pr_ready(workdir, gh_pr_number):
            click.echo("Draft PR upgraded to ready for review.")
        else:
            click.echo("Warning: Failed to upgrade draft PR. It may already be ready or was closed.", err=True)

    pr_entry["status"] = "in_review"
    save_and_push(data, root, f"pm: done {pr_id}")
    click.echo(f"PR {_pr_display_id(pr_entry)} marked as in_review.")
    trigger_tui_refresh()


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
            click.echo(f"  ✅ {_pr_display_id(pr_entry)}: merged")
            updated += 1

    if updated:
        save_and_push(data, root, f"pm: sync - {updated} PRs merged")
        trigger_tui_refresh()
    else:
        click.echo("No new merges detected.")

    # Show newly unblocked PRs
    ready = graph.ready_prs(prs)
    if ready:
        click.echo("\nNewly ready PRs:")
        for p in ready:
            click.echo(f"  ⏳ {_pr_display_id(p)}: {p.get('title', '???')}")


@pr.command("sync-github")
def pr_sync_github():
    """Fetch and update PR statuses from GitHub.

    For each PR with a GitHub PR number, fetches the current state
    from GitHub and updates the local status accordingly:
    - MERGED → merged
    - CLOSED → closed (then auto-removed after 3 seconds)
    - OPEN + draft → in_progress
    - OPEN + ready → in_review
    """
    root = state_root()
    data = store.load(root)

    backend_name = data["project"].get("backend", "vanilla")
    if backend_name != "github":
        click.echo("This command only works with the GitHub backend.", err=True)
        raise SystemExit(1)

    # Use the shared sync function which handles auto-removal of closed PRs
    result = pr_sync_mod.sync_from_github(root, data, save_state=True)

    if result.error:
        click.echo(f"Error: {result.error}", err=True)
        raise SystemExit(1)

    if result.updated_count > 0:
        click.echo(f"Updated {result.updated_count} PR(s).")
        if result.merged_prs:
            click.echo(f"  Merged: {', '.join(result.merged_prs)}")
        if result.closed_prs:
            click.echo(f"  Closed: {', '.join(result.closed_prs)} (will be removed in 3s)")
        trigger_tui_refresh()
    else:
        click.echo("No status changes.")


@pr.command("import-github")
@click.option("--state", "gh_state", default="all", help="GitHub PR state to import: open, closed, merged, all")
def pr_import_github(gh_state: str):
    """Import existing GitHub PRs into the project yaml.

    Fetches PRs from GitHub and creates yaml entries for any not already
    tracked. Matches existing entries by branch name or GH PR number.
    Skips PRs that are already in the yaml.

    \b
    Examples:
      pm pr import-github              # import all PRs
      pm pr import-github --state open # only open PRs
    """
    root = state_root()
    data = store.load(root)

    backend_name = data["project"].get("backend", "vanilla")
    if backend_name != "github":
        click.echo("This command only works with the GitHub backend.", err=True)
        raise SystemExit(1)

    # Determine repo directory for gh CLI
    if store.is_internal_pm_dir(root):
        repo_dir = str(root.parent)
    else:
        repo_url = data["project"].get("repo", "")
        if repo_url and Path(repo_url).is_dir():
            repo_dir = repo_url
        else:
            repo_dir = str(Path.cwd())

    from pm_core import gh_ops

    click.echo("Fetching PRs from GitHub...")
    gh_prs = gh_ops.list_prs(repo_dir, state=gh_state)
    if not gh_prs:
        click.echo("No PRs found on GitHub.")
        return

    # Build lookup of existing entries by branch and gh_pr_number
    existing_branches = {p.get("branch") for p in (data.get("prs") or [])}
    existing_gh_numbers = {p.get("gh_pr_number") for p in (data.get("prs") or []) if p.get("gh_pr_number")}

    if data.get("prs") is None:
        data["prs"] = []

    imported = 0
    skipped = 0
    for gh_pr in gh_prs:
        branch = gh_pr.get("headRefName", "")
        number = gh_pr.get("number")
        title = gh_pr.get("title", "")

        # Skip if already tracked
        if branch in existing_branches or number in existing_gh_numbers:
            skipped += 1
            continue

        # Map GitHub state to local status
        gh_s = gh_pr.get("state", "OPEN")
        is_draft = gh_pr.get("isDraft", False)
        if gh_s == "MERGED":
            status = "merged"
        elif gh_s == "CLOSED":
            status = "closed"
        elif gh_s == "OPEN":
            status = "in_progress" if is_draft else "in_review"
        else:
            status = "pending"

        # Generate a pr_id based on the GH PR number
        existing_ids = {p["id"] for p in data["prs"]}
        pr_id = f"pr-{number:03d}"
        if pr_id in existing_ids:
            pr_id = f"pr-{number:03d}-gh"
        if pr_id in existing_ids:
            # Fall back to sequential
            pr_id = store.next_pr_id(data)

        url = gh_pr.get("url", "")
        body = gh_pr.get("body", "") or ""

        entry = {
            "id": pr_id,
            "plan": None,
            "title": title,
            "branch": branch,
            "status": status,
            "depends_on": [],
            "description": body,
            "agent_machine": None,
            "gh_pr": url,
            "gh_pr_number": number,
        }
        data["prs"].append(entry)
        existing_ids.add(pr_id)
        existing_branches.add(branch)
        existing_gh_numbers.add(number)
        imported += 1
        click.echo(f"  + {pr_id}: {title} [{status}] (#{number})")

    if imported:
        save_and_push(data, root, "pm: import github PRs")
        click.echo(f"\nImported {imported} PR(s), skipped {skipped} already tracked.")
        trigger_tui_refresh()
    else:
        click.echo(f"No new PRs to import ({skipped} already tracked).")


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
                click.echo(f"  {_pr_display_id(p)}: {p.get('title', '???')}", err=True)
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
        trigger_tui_refresh()
    else:
        click.echo(f"No work directory found for {pr_id}.")


@pr.command("close")
@click.argument("pr_id", default=None, required=False)
@click.option("--keep-github", is_flag=True, help="Don't close the GitHub PR")
@click.option("--keep-branch", is_flag=True, help="Don't delete the remote branch")
def pr_close(pr_id: str | None, keep_github: bool, keep_branch: bool):
    """Close and remove a PR from the project.

    Removes the PR entry from project.yaml. By default also closes the
    GitHub PR and deletes the remote branch if they exist.

    If PR_ID is omitted, uses the active PR.
    """
    root = state_root()
    data = store.load(root)

    if pr_id is None:
        pr_id = data.get("project", {}).get("active_pr")
        if not pr_id:
            click.echo("No active PR. Specify a PR ID.", err=True)
            raise SystemExit(1)
        click.echo(f"Using active PR: {pr_id}")

    pr_entry = store.get_pr(data, pr_id)
    if not pr_entry:
        prs = data.get("prs") or []
        click.echo(f"PR {pr_id} not found.", err=True)
        if prs:
            click.echo(f"Available PRs: {', '.join(p['id'] for p in prs)}", err=True)
        raise SystemExit(1)

    # Close GitHub PR if exists
    gh_pr_number = pr_entry.get("gh_pr_number")
    if gh_pr_number and not keep_github:
        click.echo(f"Closing GitHub PR #{gh_pr_number}...")
        try:
            delete_flag = [] if keep_branch else ["--delete-branch"]
            result = subprocess.run(
                ["gh", "pr", "close", str(gh_pr_number), *delete_flag],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                click.echo(f"GitHub PR #{gh_pr_number} closed.")
            else:
                click.echo(f"Warning: Could not close GitHub PR: {result.stderr.strip()}", err=True)
        except Exception as e:
            click.echo(f"Warning: Could not close GitHub PR: {e}", err=True)

    # Remove workdir if exists
    workdir = pr_entry.get("workdir")
    if workdir and Path(workdir).exists():
        shutil.rmtree(workdir)
        click.echo(f"Removed workdir: {workdir}")

    # Remove PR from list
    prs = data.get("prs") or []
    data["prs"] = [p for p in prs if p["id"] != pr_id]

    # Update active_pr if needed
    if data.get("project", {}).get("active_pr") == pr_id:
        remaining = data.get("prs") or []
        data["project"]["active_pr"] = remaining[0]["id"] if remaining else None

    save_and_push(data, root, f"pm: close {pr_id}")
    click.echo(f"Removed {pr_id}: {pr_entry.get('title', '???')}")
    trigger_tui_refresh()


@cli.group(invoke_without_command=True)
@click.pass_context
def session(ctx):
    """Manage tmux sessions for pm.

    Without a subcommand, starts or attaches to the pm session.
    """
    if ctx.invoked_subcommand is not None:
        return
    _session_start()


def _session_start():
    """Start a tmux session with TUI + notes editor.

    If no project exists yet, starts pm guide instead of the TUI so
    the guided workflow can initialize the project inside tmux.
    """
    _log.info("session_cmd started")
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

    # Generate session name with path hash (uses helper to ensure consistency)
    # Use the repo directory (parent of pm/) as the working directory
    if root and store.is_internal_pm_dir(root):
        cwd = str(root.parent)
    else:
        cwd = str(root) if root else str(Path.cwd())
    session_name = _get_session_name_for_cwd()
    expected_root = root or (Path.cwd() / "pm")
    notes_path = expected_root / notes.NOTES_FILENAME

    _log.info("checking if session exists: %s", session_name)
    if tmux_mod.session_exists(session_name):
        # Check if the session has the expected panes
        live_panes = tmux_mod.get_pane_indices(session_name)
        registry = pane_layout.load_registry(session_name)
        registered_panes = registry.get("panes", [])

        # Find which registered panes are still alive
        live_pane_ids = {p[0] for p in live_panes}
        roles_alive = {p["role"] for p in registered_panes if p["id"] in live_pane_ids}

        _log.info("session exists: %s", session_name)
        _log.info("roles_alive: %s", roles_alive)

        # If TUI is missing, kill the broken session and let normal init recreate it
        if "tui" not in roles_alive:
            _log.info("TUI missing, killing broken session to recreate")
            click.echo(f"Session '{session_name}' is broken. Recreating...")
            tmux_mod.kill_session(session_name)
            # Fall through to normal creation code below
        else:
            _log.info("TUI present, just attaching")
            click.echo(f"Attaching to existing session '{session_name}'...")
            tmux_mod.attach(session_name)
            return

    _log.info("session does not exist or was killed, creating new session")
    editor = find_editor()

    # Clear stale pane registry and bump generation to invalidate old EXIT traps
    import time as _time
    generation = str(int(_time.time()))
    pane_layout.save_registry(session_name, {
        "session": session_name, "window": "0", "panes": [],
        "user_modified": False, "generation": generation,
    })

    # Always create session with TUI in the left pane
    _log.info("creating tmux session: %s cwd=%s", session_name, cwd)
    click.echo(f"Creating tmux session '{session_name}'...")
    tmux_mod.create_session(session_name, cwd, "pm _tui")

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
    _log.info("created tui_pane=%s window_id=%s", tui_pane, window_id)

    # Register TUI pane in layout registry
    pane_layout.register_pane(session_name, window_id, tui_pane, "tui", "pm _tui")

    def _wrap(cmd: str) -> str:
        """Wrap a pane command in bash with an EXIT trap for rebalancing."""
        escaped = cmd.replace("'", "'\\''")
        return (f"bash -c 'trap \"pm _pane-exited {session_name} {window_id} {generation} $TMUX_PANE\" EXIT; "
                f"{escaped}'")

    _log.info("has_project=%s, creating notes pane", has_project)
    if has_project:
        # Existing project: TUI (left) | notes editor (right)
        notes.ensure_notes_file(root)
        notes_pane = tmux_mod.split_pane(session_name, "h", _wrap(f"pm notes {notes_path}"))
        pane_layout.register_pane(session_name, window_id, notes_pane, "notes", "pm notes")
    else:
        # Setup: TUI (left) | notes (right)
        # The TUI will auto-launch the guide pane when it detects setup state
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        if not notes_path.exists():
            notes_path.write_text(notes.NOTES_WELCOME)
        notes_pane = tmux_mod.split_pane(session_name, "h", _wrap(f"pm notes {notes_path}"))
        pane_layout.register_pane(session_name, window_id, notes_pane, "notes", "pm notes")
    _log.info("created notes_pane=%s", notes_pane)

    # Apply initial balanced layout
    pane_layout.rebalance(session_name, window_id)
    _log.info("rebalanced layout, attaching to session")

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


@session.command("kill")
def session_kill():
    """Kill the pm tmux session for this project."""
    if not tmux_mod.has_tmux():
        click.echo("tmux is not installed.", err=True)
        raise SystemExit(1)

    session_name = _get_session_name_for_cwd()

    if not tmux_mod.session_exists(session_name):
        click.echo(f"No session '{session_name}' found.", err=True)
        raise SystemExit(1)

    tmux_mod.kill_session(session_name)
    click.echo(f"Killed session '{session_name}'.")


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


@cli.command("_tui", hidden=True)
def tui_cmd():
    """Launch the interactive TUI (internal command)."""
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

    Uses improved remote detection that prefers 'origin' but also considers
    other remotes when 'origin' doesn't exist.
    """
    cwd = Path.cwd()
    if not git_ops.is_git_repo(cwd):
        return None

    branch_result = git_ops.run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=cwd, check=False)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "main"

    remotes = git_ops.list_remotes(cwd)
    if not remotes:
        return {"url": None, "name": cwd.name, "branch": branch, "cwd": str(cwd), "type": "local"}

    # Select the best remote (prefers origin, then github.com URLs)
    selection = git_ops.select_remote(remotes, preferred_backend="github")
    if "selected" in selection and selection["selected"]:
        _, remote_url = selection["selected"]
    elif "ambiguous" in selection and selection["ambiguous"]:
        # For display purposes, just pick the first ambiguous option
        _, remote_url = selection["ambiguous"][0]
    else:
        return {"url": None, "name": cwd.name, "branch": branch, "cwd": str(cwd), "type": "local"}

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
        trigger_tui_refresh()

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

        session_name = tmux_mod.get_session_name()

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
    session_name = tmux_mod.get_session_name()
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

    # Bug fix: If started is None but pm dir exists, we're completing step 1
    # This happens when the guide started with no pm dir (root was None),
    # then pm init created the directory, and now we're completing.
    if started is None:
        # Check if detection shows we've moved past no_project
        detected, _ = guide_mod.detect_state(root)
        if detected != "no_project":
            # We've progressed, so no_project must have been the started step
            started = "no_project"
            guide_mod.mark_step_started(root, started)
        else:
            click.echo("No guide step has been started yet.", err=True)
            raise SystemExit(1)

    completed = guide_mod.get_completed_step(root)
    started_idx = guide_mod.STEP_ORDER.index(started) if started in guide_mod.STEP_ORDER else 0
    completed_idx = guide_mod.STEP_ORDER.index(completed) if completed in guide_mod.STEP_ORDER else -1

    if completed_idx >= started_idx:
        click.echo("Already completed.")
        return

    # Bug fix: Verify that detection shows progress before marking complete
    # This prevents marking a step complete when artifacts weren't created
    detected, _ = guide_mod.detect_state(root)
    detected_idx = guide_mod.STEP_ORDER.index(detected) if detected in guide_mod.STEP_ORDER else 0

    if detected_idx <= started_idx:
        # Detection hasn't moved forward - step isn't actually complete
        click.echo(f"Step not complete: detection still shows '{guide_mod.STEP_DESCRIPTIONS.get(detected, detected)}'")
        click.echo("Complete the step's tasks before running 'pm guide done'.")
        raise SystemExit(1)

    state = started
    guide_mod.mark_step_completed(root, state)
    desc = guide_mod.STEP_DESCRIPTIONS.get(state, state)
    click.echo(f"Step completed: {desc}")

    # Trigger TUI refresh so it picks up the step change immediately
    _refresh_tui_if_running()


def _refresh_tui_if_running():
    """Send refresh key to TUI pane if one is running."""
    import subprocess
    try:
        pane_id, _ = _find_tui_pane()
        if pane_id:
            subprocess.run(
                ["tmux", "send-keys", "-t", pane_id, "r"],
                capture_output=True,
                timeout=2,
            )
    except Exception:
        pass  # Best effort - don't fail if TUI isn't running


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
        # Bug fix: Track non-interactive steps like any other step
        if root:
            guide_mod.mark_step_started(root, state)
        guide_mod.run_non_interactive_step(state, ctx, root)
        if root:
            guide_mod.mark_step_completed(root, state)
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
        import uuid as uuid_mod
        escaped = prompt.replace("'", "'\\''")
        skip = " --dangerously-skip-permissions" if _skip_permissions() else ""

        # Get or create session ID
        session_id = None
        session_flag = ""
        if root and not fresh:
            session_id = load_session(root, session_key)
            if session_id:
                session_flag = f" --resume {session_id}"

        # If no existing session, generate new UUID and save it
        save_cmd = ""
        if not session_id and root:
            session_id = str(uuid_mod.uuid4())
            session_flag = f" --session-id {session_id}"
            save_cmd = f"pm _save-session '{session_key}' '{session_id}' '{root}' ; "

        # Include project path hash in loop guard to make it project-specific
        import hashlib
        project_hash = hashlib.md5(str(root).encode()).hexdigest()[:8] if root else "unknown"
        loop_guard = f"pm _loop-guard guide-{project_hash}-{state}"

        claude_cmd = f"claude{skip}{session_flag} '{escaped}'"

        if post_hook:
            post_cmd = f"pm guide done ; python -c \"from pm_core.guide import set_deps_reviewed; from pathlib import Path; set_deps_reviewed(Path('{root}'))\""
        else:
            post_cmd = "pm guide done"

        # Capture claude's exit code to handle session resume failures properly.
        # If claude fails (e.g., "No conversation found"), clear the stale session.
        # If claude succeeds, run post_cmd. Either way, continue to loop_guard.
        # This prevents infinite loops trying to resume non-existent sessions.
        clear_cmd = f"pm _clear-session '{session_key}' '{root}'" if root else "true"
        cmd = f"{save_cmd}{claude_cmd} ; claude_rc=$? ; if [ $claude_rc -ne 0 ]; then {clear_cmd}; else {post_cmd}; fi ; {loop_guard} && pm guide"

        # Log the full command for debugging
        import logging as _logging
        _log = _logging.getLogger("pm.guide")
        _log.info("guide chain: skip_permissions=%s env=%s", _skip_permissions(),
                   os.environ.get("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS"))
        _log.info("guide chain cmd: %s", cmd[:100] + "...")
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



@cli.command("_save-session", hidden=True)
@click.argument("session_key")
@click.argument("session_id")
@click.argument("pm_root")
def save_session_cmd(session_key: str, session_id: str, pm_root: str):
    """Internal: save a session ID to the registry."""
    from pm_core.claude_launcher import save_session
    try:
        save_session(Path(pm_root), session_key, session_id)
    except Exception:
        pass  # Best effort


@cli.command("_clear-session", hidden=True)
@click.argument("session_key")
@click.argument("pm_root")
def clear_session_cmd(session_key: str, pm_root: str):
    """Internal: clear a stale session from the registry.

    Called when claude --resume fails (e.g., session no longer exists).
    This prevents infinite loops trying to resume a non-existent session.
    """
    from pm_core.claude_launcher import clear_session
    try:
        clear_session(Path(pm_root), session_key)
        click.echo(f"Cleared stale session: {session_key}", err=True)
    except Exception:
        pass  # Best effort


@cli.command("_loop-guard", hidden=True)
@click.argument("loop_id")
def loop_guard_cmd(loop_id: str):
    """Internal: guard against rapid restart loops.

    Tracks timestamps of restarts. If 5 restarts happen in <30 seconds,
    exits with code 1 to break the loop. Always sleeps 5 seconds.
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

    # Keep only timestamps from the last 60 seconds
    timestamps = [t for t in timestamps if now - t < 60]
    timestamps.append(now)

    # Check for rapid restarts: 5+ restarts in <30 seconds
    if len(timestamps) >= 5:
        oldest_recent = timestamps[-5]
        if now - oldest_recent < 30:
            click.echo(f"Loop guard triggered: {len(timestamps)} restarts in {now - oldest_recent:.1f}s", err=True)
            click.echo("Breaking loop to prevent runaway restarts.", err=True)
            # Clear the timestamps so next manual run works
            loop_file.unlink(missing_ok=True)
            raise SystemExit(1)

    # Save updated timestamps
    import json
    loop_file.write_text(json.dumps(timestamps))

    # Sleep before allowing restart
    time.sleep(5)


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


@cli.group()
def tui():
    """Control and monitor the TUI from the command line."""
    pass


TUI_HISTORY_DIR = Path.home() / ".pm-pane-registry" / "tui-history"
TUI_MAX_FRAMES = 50


def _tui_history_file(session: str) -> Path:
    """Get the TUI history file for a specific session."""
    TUI_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return TUI_HISTORY_DIR / f"{session}.json"


def _get_session_name_for_path(path: str | Path, name: str | None = None) -> str:
    """Generate a pm session name for a specific path.

    Args:
        path: The directory path to hash
        name: Optional name prefix (defaults to directory name)
    """
    import hashlib
    path_str = str(path)
    if name is None:
        name = Path(path).name
    path_hash = hashlib.md5(path_str.encode()).hexdigest()[:8]
    return f"pm-{name}-{path_hash}"


def _get_session_name_for_cwd() -> str:
    """Generate the expected session name for the current working directory."""
    try:
        root = state_root()
        data = store.load(root)
        project_name = data.get("project", {}).get("name", "unknown")
        cwd = str(root)
    except (FileNotFoundError, SystemExit):
        project_name = Path.cwd().name
        cwd = str(Path.cwd())

    return _get_session_name_for_path(cwd, project_name)


def _find_tui_pane(session: str | None = None) -> tuple[str | None, str | None]:
    """Find the TUI pane in a pm session.

    Returns (pane_id, session_name) or (None, None) if not found.

    If session is provided, uses that. Otherwise:
    - If in a pm- tmux session, uses current session
    - Otherwise, tries to find session matching current directory
    - Falls back to searching for any pm- session with a TUI pane
    """
    import subprocess

    # If session specified, use it
    if session:
        data = pane_layout.load_registry(session)
        for pane in data.get("panes", []):
            if pane.get("role") == "tui":
                return pane.get("id"), session
        return None, None

    # If in a pm session, use current
    if tmux_mod.in_tmux():
        current_session = tmux_mod.get_session_name()
        if current_session.startswith("pm-"):
            data = pane_layout.load_registry(current_session)
            for pane in data.get("panes", []):
                if pane.get("role") == "tui":
                    return pane.get("id"), current_session

    # Try to find session matching current directory first
    expected_session = _get_session_name_for_cwd()
    if tmux_mod.session_exists(expected_session):
        data = pane_layout.load_registry(expected_session)
        for pane in data.get("panes", []):
            if pane.get("role") == "tui":
                return pane.get("id"), expected_session

    # Fall back to searching for any pm session with a TUI
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, None

    for sess in result.stdout.strip().splitlines():
        if sess.startswith("pm-"):
            data = pane_layout.load_registry(sess)
            for pane in data.get("panes", []):
                if pane.get("role") == "tui":
                    return pane.get("id"), sess

    return None, None


def _capture_tui_frame(pane_id: str) -> str:
    """Capture the current TUI pane content."""
    import subprocess
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", pane_id, "-p"],
        capture_output=True, text=True
    )
    return result.stdout


def _load_tui_history(session: str) -> list:
    """Load TUI frame history for a session."""
    history_file = _tui_history_file(session)
    if not history_file.exists():
        return []
    try:
        import json
        return json.loads(history_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_tui_history(session: str, history: list) -> None:
    """Save TUI frame history for a session."""
    import json
    history_file = _tui_history_file(session)
    history_file.write_text(json.dumps(history, indent=2))


def _add_frame_to_history(session: str, frame: str, pane_id: str) -> None:
    """Add a frame to history, keeping only the last N frames."""
    from datetime import datetime, timezone
    history = _load_tui_history(session)
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pane_id": pane_id,
        "content": frame,
    })
    # Keep only last N frames
    if len(history) > TUI_MAX_FRAMES:
        history = history[-TUI_MAX_FRAMES:]
    _save_tui_history(session, history)


@tui.command("view")
@click.option("--no-history", is_flag=True, help="Don't add this frame to history")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_view(no_history: bool, session: str | None):
    """View current TUI output.

    Captures the current TUI pane content and displays it.
    Also adds the frame to history for later review (unless --no-history).
    """
    pane_id, sess = _find_tui_pane(session)
    if not pane_id:
        click.echo("No TUI pane found. Is there a pm tmux session running?", err=True)
        raise SystemExit(1)

    frame = _capture_tui_frame(pane_id)
    if not no_history:
        _add_frame_to_history(sess, frame, pane_id)

    click.echo(f"[Session: {sess}, Pane: {pane_id}]")
    click.echo(frame)


@tui.command("history")
@click.option("--frames", "-n", default=5, help="Number of frames to show")
@click.option("--all", "show_all", is_flag=True, help="Show all frames")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_history(frames: int, show_all: bool, session: str | None):
    """View recent TUI frames from history.

    Shows the last N captured frames with timestamps.
    """
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    history = _load_tui_history(sess)
    if not history:
        click.echo(f"No TUI history found for session {sess}.")
        return

    if show_all:
        frames = len(history)

    recent = history[-frames:]
    click.echo(f"[Session: {sess}]")
    for i, entry in enumerate(recent):
        timestamp = entry.get("timestamp", "unknown")
        content = entry.get("content", "")
        click.echo(f"{'=' * 60}")
        click.echo(f"Frame {len(history) - len(recent) + i + 1}/{len(history)} @ {timestamp}")
        click.echo(f"{'=' * 60}")
        click.echo(content)
        click.echo()


@tui.command("send")
@click.argument("keys")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_send(keys: str, session: str | None):
    """Send keys to the TUI.

    KEYS can be single characters, key names, or sequences:
      - Single keys: g, x, r, q
      - Special keys: Enter, Escape, Up, Down, Left, Right, Tab
      - Ctrl combinations: C-c, C-d
      - Sequences: "gr" sends 'g' then 'r'

    Examples:
      pm tui send g          # Press 'g' (launch guide)
      pm tui send x          # Press 'x' (dismiss guide)
      pm tui send r          # Press 'r' (refresh)
      pm tui send Enter      # Press Enter
      pm tui send C-c        # Press Ctrl+C
    """
    import subprocess
    pane_id, sess = _find_tui_pane(session)
    if not pane_id:
        click.echo("No TUI pane found. Is there a pm tmux session running?", err=True)
        raise SystemExit(1)

    subprocess.run(["tmux", "send-keys", "-t", pane_id, keys], check=True)
    click.echo(f"Sent keys '{keys}' to TUI pane {pane_id} (session: {sess})")


@tui.command("keys")
def tui_keys():
    """Show available TUI keybindings."""
    click.echo("""\
TUI Keybindings:

Navigation:
  Up/Down, j/k     Navigate PR list
  Enter            Select/expand PR

Actions:
  g                Launch guide pane
  n                Open notes
  c                Copy prompt to clipboard
  l                Launch Claude for selected PR
  r                Refresh state

Guide Mode:
  x                Dismiss guide view

General:
  q                Quit TUI
  ?                Show help
""")


@tui.command("clear-history")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_clear_history(session: str | None):
    """Clear the TUI frame history for a session."""
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    history_file = _tui_history_file(sess)
    if history_file.exists():
        history_file.unlink()
        click.echo(f"TUI history cleared for session {sess}.")
    else:
        click.echo(f"No history to clear for session {sess}.")


# --- Frame capture commands ---

def _capture_config_file(session: str) -> Path:
    """Get the capture config file path for a session."""
    return _log_dir / f"{session}-capture.json"


def _capture_frames_file(session: str) -> Path:
    """Get the captured frames file path for a session."""
    return _log_dir / f"{session}-frames.json"


@tui.command("capture")
@click.option("--frame-rate", "-r", type=int, default=None,
              help="Record every Nth change (1=all changes)")
@click.option("--buffer-size", "-b", type=int, default=None,
              help="Max frames to keep in buffer")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_capture_config(frame_rate: int | None, buffer_size: int | None, session: str | None):
    """Configure frame capture settings.

    Frame capture is always enabled. Use this to adjust:
    - frame-rate: Record every Nth change (default: 1 = record all)
    - buffer-size: How many frames to keep (default: 100)

    The TUI will pick up config changes on its next sync cycle (~30s)
    or immediately if you press 'r' to refresh.

    Examples:
        pm tui capture --frame-rate 1 --buffer-size 200
        pm tui capture -r 5 -b 50
    """
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    config_file = _capture_config_file(sess)

    # Load existing config or defaults
    config = {"frame_rate": 1, "buffer_size": 100}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Update with provided values
    if frame_rate is not None:
        if frame_rate < 1:
            click.echo("frame-rate must be >= 1", err=True)
            raise SystemExit(1)
        config["frame_rate"] = frame_rate
    if buffer_size is not None:
        if buffer_size < 1:
            click.echo("buffer-size must be >= 1", err=True)
            raise SystemExit(1)
        config["buffer_size"] = buffer_size

    # Save config
    config_file.write_text(json.dumps(config, indent=2))
    click.echo(f"Capture config for session {sess}:")
    click.echo(f"  frame_rate:  {config['frame_rate']} (record every {config['frame_rate']} change(s))")
    click.echo(f"  buffer_size: {config['buffer_size']} frames")
    click.echo("\nTUI will pick up changes on next sync or press 'r' to refresh.")


@tui.command("frames")
@click.option("--count", "-n", type=int, default=5, help="Number of frames to show")
@click.option("--all", "show_all", is_flag=True, help="Show all frames")
@click.option("--session", "-s", default=None, help="Specify pm session name")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def tui_frames(count: int, show_all: bool, session: str | None, as_json: bool):
    """View captured TUI frames.

    Shows frames captured when the TUI changes (based on frame_rate setting).
    Each frame includes timestamp, trigger, and content.

    Examples:
        pm tui frames              # Show last 5 frames
        pm tui frames -n 20        # Show last 20 frames
        pm tui frames --all        # Show all frames
        pm tui frames --json       # Output as JSON for scripting
    """
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    frames_file = _capture_frames_file(sess)
    if not frames_file.exists():
        click.echo(f"No captured frames for session {sess}.")
        return

    try:
        data = json.loads(frames_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        click.echo(f"Error reading frames: {e}", err=True)
        raise SystemExit(1)

    frames = data.get("frames", [])
    if not frames:
        click.echo(f"No frames captured yet for session {sess}.")
        return

    if as_json:
        if show_all:
            click.echo(json.dumps(data, indent=2))
        else:
            output = {**data, "frames": frames[-count:]}
            click.echo(json.dumps(output, indent=2))
        return

    # Show summary
    click.echo(f"[Session: {sess}]")
    click.echo(f"Total changes: {data.get('total_changes', '?')}")
    click.echo(f"Frame rate: {data.get('frame_rate', '?')} | Buffer size: {data.get('buffer_size', '?')}")
    click.echo(f"Frames captured: {len(frames)}")
    click.echo()

    if show_all:
        count = len(frames)

    recent = frames[-count:]
    for i, frame in enumerate(recent):
        frame_num = len(frames) - len(recent) + i + 1
        timestamp = frame.get("timestamp", "unknown")
        trigger = frame.get("trigger", "unknown")
        change_num = frame.get("change_number", "?")
        content = frame.get("content", "")

        click.echo("=" * 60)
        click.echo(f"Frame {frame_num}/{len(frames)} | Change #{change_num} | {trigger}")
        click.echo(f"Time: {timestamp}")
        click.echo("=" * 60)
        click.echo(content)
        click.echo()


@tui.command("clear-frames")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_clear_frames(session: str | None):
    """Clear captured frames for a session."""
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    frames_file = _capture_frames_file(sess)
    if frames_file.exists():
        frames_file.unlink()
        click.echo(f"Captured frames cleared for session {sess}.")
    else:
        click.echo(f"No frames to clear for session {sess}.")


@tui.command("test")
@click.argument("test_id", required=False)
@click.option("--list", "list_tests_flag", is_flag=True, help="List available tests")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_test(test_id: str | None, list_tests_flag: bool, session: str | None):
    """Run TUI regression tests using Claude as the test executor.

    These tests launch Claude with a specific test prompt that instructs it
    to interact with the TUI and tmux, verify behavior, and report results.

    Examples:
        pm tui test --list              # List available tests
        pm tui test pane-layout         # Run pane layout test
        pm tui test session-resume      # Run session resume test
    """
    from pm_core import tui_tests

    if list_tests_flag:
        tests = tui_tests.list_tests()
        click.echo("Available TUI tests:\n")
        for t in tests:
            click.echo(f"  {t['id']:20} {t['name']}")
            click.echo(f"  {' '*20} {t['description']}\n")
        return

    if not test_id:
        click.echo("Usage: pm tui test <test_id>")
        click.echo("Run 'pm tui test --list' to see available tests.")
        raise SystemExit(1)

    prompt = tui_tests.get_test_prompt(test_id)
    if not prompt:
        click.echo(f"Unknown test: {test_id}", err=True)
        click.echo("Run 'pm tui test --list' to see available tests.")
        raise SystemExit(1)

    # Verify we have a TUI session
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found. Start one with 'pm session'.", err=True)
        raise SystemExit(1)

    # Add session context to the prompt
    full_prompt = f"""\
## Session Context

You are testing against tmux session: {sess}
The TUI pane ID is: {pane_id}

To interact with this session, use commands like:
- pm tui view -s {sess}
- pm tui send <keys> -s {sess}
- tmux list-panes -t {sess} -F "#{{pane_id}} #{{pane_width}}x#{{pane_height}} #{{pane_current_command}}"
- cat ~/.pm-pane-registry/{sess}.json

{prompt}
"""

    test_info = tui_tests.ALL_TESTS[test_id]
    click.echo(f"Running test: {test_info['name']}")
    click.echo(f"Session: {sess}")
    click.echo("-" * 60)

    # Launch Claude with the test prompt
    claude = find_claude()
    if not claude:
        click.echo("Claude CLI not found.", err=True)
        raise SystemExit(1)

    import subprocess
    cmd = [claude]
    if os.environ.get("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS") == "true":
        cmd.append("--dangerously-skip-permissions")
    cmd.append(full_prompt)

    result = subprocess.run(cmd)
    raise SystemExit(result.returncode)


def main():
    cli()
