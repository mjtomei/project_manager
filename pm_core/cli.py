"""Click CLI definitions for pm."""

import os
import platform
import shutil
from pathlib import Path

import click

from pm_core import store, graph, git_ops, prompt_gen
from pm_core.backend import detect_backend, get_backend


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
    """Save state and auto-commit/push."""
    store.save(data, root)
    git_ops.auto_commit_state(root, message)


@click.group()
@click.option("-C", "project_dir", default=None, envvar="PM_PROJECT",
              help="Path to PM repo (or set PM_PROJECT env var)")
def cli(project_dir: str | None):
    """pm — Project Manager for Claude Code sessions."""
    global _project_override
    if project_dir:
        _project_override = Path(project_dir).resolve()


@cli.command()
@click.argument("repo_url", metavar="TARGET_REPO_URL")
@click.option("--name", default=None, help="Project name (defaults to repo name)")
@click.option("--base-branch", default="main", help="Base branch of target repo")
@click.option("--dir", "directory", default=None, help="Directory for PM repo (default: <name>-pm)")
@click.option("--pm-remote", default=None, help="Git remote URL for the PM repo itself")
@click.option("--backend", "backend_override", default=None,
              type=click.Choice(["vanilla", "github"]),
              help="Hosting backend (auto-detected from URL if not set)")
def init(repo_url: str, name: str, base_branch: str, directory: str,
         pm_remote: str, backend_override: str):
    """Create a new PM repo for managing a target codebase.

    TARGET_REPO_URL is the codebase where code PRs will be opened.

    This creates a SEPARATE git repo for project management state
    (project.yaml, plans/). Only PMs touch this repo directly.
    Contributors interact via issues or in person.

    The hosting backend is auto-detected from the URL:
      - github.com URLs use the 'github' backend (gh CLI integration)
      - Everything else uses the 'vanilla' backend (pure git)

    \b
    Examples:
      pm init git@github.com:org/myapp.git
      pm init git@myhost.com:org/myapp.git --backend vanilla
      pm init git@github.com:org/myapp.git --dir ~/projects/myapp-pm
    """
    if name is None:
        name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")

    if directory is None:
        directory = f"{name}-pm"
    root = Path(directory).resolve()

    if (root / "project.yaml").exists():
        click.echo(f"PM repo already exists at {root}", err=True)
        raise SystemExit(1)

    backend = backend_override or detect_backend(repo_url)
    data = store.init_project(root, name, repo_url, base_branch, backend=backend)

    # Initialize PM repo as its own git repo
    if not git_ops.is_git_repo(root):
        git_ops.run_git("init", cwd=root, check=False)
        gitignore = root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("")
        git_ops.run_git("add", "-A", cwd=root, check=False)
        git_ops.run_git("commit", "-m", "pm: init project", cwd=root, check=False)

    if pm_remote:
        git_ops.run_git("remote", "add", "origin", pm_remote, cwd=root, check=False)
        click.echo(f"  pm remote: {pm_remote}")

    click.echo(f"Created PM repo at {root}")
    click.echo(f"  target repo: {repo_url}")
    click.echo(f"  base branch: {base_branch}")
    click.echo(f"  backend: {backend}")
    if not pm_remote:
        click.echo(f"\nTo share with other PMs, create a remote repo and run:")
        click.echo(f"  cd {root}")
        click.echo(f"  git remote add origin <your-pm-repo-url>")
        click.echo(f"  git push -u origin master")


# --- Plan commands ---

@cli.group()
def plan():
    """Manage plans."""
    pass


@plan.command("add")
@click.argument("name")
def plan_add(name: str):
    """Create a new plan."""
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

    # Create the plan markdown file
    plan_path = root / plan_file
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(f"# {name}\n\n<!-- Describe the plan here -->\n")

    save_and_push(data, root, f"pm: add plan {plan_id}")
    click.echo(f"Created plan {plan_id}: {name}")
    click.echo(f"  Edit: {plan_path}")


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
@click.argument("plan_id")
def plan_review(plan_id: str):
    """Output a prompt for Claude to break a plan into PRs."""
    root = state_root()
    data = store.load(root)
    plan_entry = store.get_plan(data, plan_id)
    if not plan_entry:
        click.echo(f"Plan {plan_id} not found.", err=True)
        raise SystemExit(1)

    plan_path = root / plan_entry["file"]
    if not plan_path.exists():
        click.echo(f"Plan file {plan_path} not found.", err=True)
        raise SystemExit(1)

    plan_content = plan_path.read_text()
    existing_prs = data.get("prs") or []
    existing_context = ""
    if existing_prs:
        existing_context = "\n\nExisting PRs:\n" + "\n".join(
            f"- {pr['id']}: {pr.get('title', '???')} [{pr.get('status', '?')}]"
            for pr in existing_prs
        )

    prompt = f"""Break the following plan into a set of PRs with dependencies.

Plan: {plan_entry['name']} ({plan_id})

{plan_content}
{existing_context}

Output the PRs as a YAML list in this exact format:

```yaml
prs:
  - title: "PR title"
    depends_on: []  # list of pr-IDs from above or empty
    description: |
      Detailed description of what this PR does...
```

Guidelines:
- Each PR should be a single, reviewable unit of work
- Order dependencies so PRs can be worked on in parallel where possible
- Keep PRs focused — prefer more small PRs over fewer large ones
"""
    click.echo(prompt)


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
    pr_id = store.next_pr_id(data)
    slug = store.slugify(title)
    branch = f"pm/{pr_id}-{slug}"

    deps = []
    if depends_on:
        deps = [d.strip() for d in depends_on.split(",")]

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

    save_and_push(data, root, f"pm: add {pr_id}")
    click.echo(f"Created {pr_id}: {title}")
    click.echo(f"  branch: {branch}")
    if deps:
        click.echo(f"  depends_on: {', '.join(deps)}")


@pr.command("list")
def pr_list():
    """List all PRs with status."""
    root = state_root()
    data = store.load(root)
    prs = data.get("prs") or []
    if not prs:
        click.echo("No PRs.")
        return

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
        click.echo(f"  {icon} {p['id']}: {p.get('title', '???')} [{p.get('status', '?')}]{dep_str}{machine_str}")


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
@click.argument("pr_id")
@click.option("--workdir", default=None, help="Custom work directory")
def pr_start(pr_id: str, workdir: str):
    """Start working on a PR: clone, branch, print prompt."""
    root = state_root()
    data = store.load(root)
    pr_entry = store.get_pr(data, pr_id)
    if not pr_entry:
        click.echo(f"PR {pr_id} not found.", err=True)
        raise SystemExit(1)

    repo_url = data["project"]["repo"]
    base_branch = data["project"].get("base_branch", "main")
    project_name = data["project"]["name"]

    if workdir:
        work_path = Path(workdir).resolve()
    else:
        work_path = Path.home() / ".pm-workdirs" / project_name / pr_id

    if work_path.exists():
        click.echo(f"Work directory already exists: {work_path}")
        click.echo("Updating branch...")
        git_ops.pull_rebase(work_path)
    else:
        click.echo(f"Cloning {repo_url} to {work_path}...")
        git_ops.clone(repo_url, work_path, branch=base_branch)

    branch = pr_entry.get("branch", f"pm/{pr_id}")
    click.echo(f"Checking out branch {branch}...")
    git_ops.checkout_branch(work_path, branch, create=True)

    # Update state
    pr_entry["status"] = "in_progress"
    pr_entry["agent_machine"] = platform.node()
    save_and_push(data, root, f"pm: start {pr_id}")

    click.echo(f"\nPR {pr_id} is now in_progress on {platform.node()}")
    click.echo(f"Work directory: {work_path}")
    click.echo(f"\n{'='*60}")
    click.echo("CLAUDE PROMPT:")
    click.echo(f"{'='*60}\n")
    click.echo(prompt_gen.generate_prompt(data, pr_id))


@pr.command("done")
@click.argument("pr_id")
def pr_done(pr_id: str):
    """Mark a PR as in_review."""
    root = state_root()
    data = store.load(root)
    pr_entry = store.get_pr(data, pr_id)
    if not pr_entry:
        click.echo(f"PR {pr_id} not found.", err=True)
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
    project_name = data["project"]["name"]
    base_branch = data["project"].get("base_branch", "main")
    prs = data.get("prs") or []
    backend = get_backend(data)
    updated = 0

    # Find any existing workdir to check merge status from
    workdirs_base = Path.home() / ".pm-workdirs" / project_name
    target_workdir = None
    if workdirs_base.exists():
        for d in workdirs_base.iterdir():
            if d.is_dir() and git_ops.is_git_repo(d):
                target_workdir = d
                break

    if not target_workdir:
        click.echo("No workdirs found. Run 'pm pr start' on a PR first.", err=True)
        raise SystemExit(1)

    for pr_entry in prs:
        if pr_entry.get("status") not in ("in_review", "in_progress"):
            continue
        branch = pr_entry.get("branch", "")

        if backend.is_merged(str(target_workdir), branch, base_branch):
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
@click.argument("pr_id")
def pr_cleanup(pr_id: str):
    """Remove work directory for a merged PR."""
    root = state_root()
    data = store.load(root)
    project_name = data["project"]["name"]
    work_path = Path.home() / ".pm-workdirs" / project_name / pr_id

    if work_path.exists():
        shutil.rmtree(work_path)
        click.echo(f"Removed {work_path}")
    else:
        click.echo(f"No work directory found at {work_path}")


@cli.command("prompt")
@click.argument("pr_id")
def prompt(pr_id: str):
    """Generate Claude prompt for a PR."""
    root = state_root()
    data = store.load(root)
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


def _repo_specific_guidance(repo_info: dict) -> str:
    """Generate repo-specific setup guidance based on detected git state."""
    name = repo_info["name"]
    branch = repo_info["branch"]
    repo_type = repo_info["type"]
    cwd = repo_info["cwd"]

    if repo_type == "local":
        return f"""
DETECTED: local git repo '{name}' (no remote)
  branch: {branch}

  You can still use pm for local project management.
  Point the target repo at this directory:

    pm init {cwd} --base-branch {branch}

  Or if a PM repo already exists elsewhere:

    export PM_PROJECT=/path/to/{name}-pm
"""

    url = repo_info["url"]
    pm_dir = Path(cwd).parent / f"{name}-pm"
    backend = repo_type  # 'github' or 'vanilla'

    lines = f"""
DETECTED REPO: {name}
  remote: {url}
  branch: {branch}
  backend: {backend}

  No PM repo found for this project. To set one up:

    pm init {url} --base-branch {branch}
    cd {pm_dir}
"""

    if backend == "github":
        lines += """
  The github backend will be auto-selected (uses gh CLI for PR management).
  Make sure 'gh' is installed and authenticated: gh auth status
"""
    else:
        lines += """
  The vanilla backend will be auto-selected (pure git, no external tools).
  Merge detection uses 'git branch --merged'. No gh CLI required.
"""

    lines += f"""  Or if a PM repo already exists elsewhere:

    export PM_PROJECT=/path/to/{name}-pm
"""
    return lines


HELP_TEXT = """\
pm — Project Manager for Claude Code sessions

Manages a graph of PRs derived from plans, orchestrates parallel Claude Code
sessions, and provides an interactive terminal dashboard.

GETTING STARTED
  1. Create a PM repo (separate from your target codebase):
       pm init <target-repo-url>

  2. Add a plan:
       pm plan add "Add authentication"

  3. Break the plan into PRs:
       pm pr add "Add user model" --plan plan-001
       pm pr add "Auth middleware" --plan plan-001 --depends-on pr-001

  4. See what's ready to work on:
       pm pr ready

  5. Start a PR (clones target repo, creates branch, prints Claude prompt):
       pm pr start pr-001

  6. When Claude is done, mark it:
       pm pr done pr-001

  7. Check for merges and unblock dependents:
       pm pr sync

COMMANDS
  pm init <target-repo-url>     Create a new PM repo
  pm plan add <name>            Add a plan
  pm plan list                  List plans
  pm plan review <plan-id>      Generate prompt to decompose plan into PRs

  pm pr add <title>             Add a PR  [--plan, --depends-on, --description]
  pm pr list                    List PRs with status
  pm pr graph                   Show dependency tree
  pm pr ready                   Show PRs ready to start
  pm pr start <pr-id>           Clone, branch, print Claude prompt
  pm pr done <pr-id>            Mark PR as in_review
  pm pr sync                    Check for merged PRs
  pm pr cleanup <pr-id>         Remove workdir for merged PR

  pm prompt <pr-id>             Print Claude prompt for a PR
  pm tui                        Launch interactive dashboard

OPTIONS
  -C <path>                     Path to PM repo (or set PM_PROJECT env var)
  --backend vanilla|github      Override auto-detected backend at init time

BACKENDS
  vanilla   Pure git. No external tools. Merge detection via git branch --merged.
  github    Uses gh CLI for PR creation and merge detection. Auto-selected for
            github.com URLs.

NOTES
  The PM repo is separate from the target codebase. Only PMs touch it.
  State is stored in project.yaml and plans/, auto-committed to git.\
"""


@cli.command("help")
def help_cmd():
    """Show help and getting started guide."""
    click.echo(HELP_TEXT)

    # Check if we're in a git repo without a PM repo
    try:
        state_root()
    except FileNotFoundError:
        repo_info = _detect_git_repo()
        if repo_info:
            click.echo(_repo_specific_guidance(repo_info))


def main():
    cli()
