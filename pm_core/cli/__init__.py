"""Click CLI definitions for pm.

This package was converted from a single cli.py module. The ``cli`` Click
group, ``main`` entry point, and core commands live here.  Shared helpers
(HelpGroup, state_root, etc.) are in ``cli.helpers``.

Command groups are split into submodules:
- cli.pr       — PR management commands
- cli.plan     — Plan management commands
- cli.session  — tmux session management and pane commands
- cli.tui      — TUI control and monitoring
- cli.guide    — Guided workflow and notes
- cli.meta     — Meta-development (working on pm itself)
- cli.cluster  — Codebase analysis and clustering
"""

from pathlib import Path

import click

from pm_core import store, git_ops, prompt_gen
from pm_core.backend import detect_backend

# Import helpers used directly in this module.  Submodules import from
# ``pm_core.cli.helpers`` directly rather than via re-export.
from pm_core.cli.helpers import (
    CONTEXT_SETTINGS,
    HelpGroup,
    _infer_pr_id,
    _pr_display_id,
    _resolve_pr_id,
    set_project_override,
    state_root,
)


@click.group(invoke_without_command=True, cls=HelpGroup, context_settings=CONTEXT_SETTINGS)
@click.option("-C", "project_dir", default=None, envvar="PM_PROJECT",
              help="Path to PM repo (or set PM_PROJECT env var)")
@click.pass_context
def cli(ctx, project_dir: str | None):
    """pm — Project Manager for Claude Code sessions."""
    if project_dir:
        set_project_override(Path(project_dir).resolve())
    if ctx.invoked_subcommand is None:
        # No subcommand: launch TUI if project found, else show help
        try:
            state_root()
            # Late import: tui_cmd is registered by cli/tui.py submodule
            from pm_core.cli.tui import tui_cmd
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
            branch_name = result.stdout.strip() if result.returncode == 0 else ""
            # "HEAD" means detached/bare repo — not a valid branch name
            if branch_name and branch_name != "HEAD":
                base_branch = branch_name
        if base_branch is None:
            base_branch = "master"

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
        from pm_core.cli.plan import _import_github_prs
        _import_github_prs(root, data)

    if no_import:
        click.echo("Run 'pm plan import' to bootstrap a PR graph from this repo.")
    else:
        from pm_core.cli.plan import _run_plan_import
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


@cli.command("which")
def which_cmd():
    """Print the path to the pm_core package being used."""
    import pm_core
    click.echo(pm_core.__path__[0])


@cli.command("set")
@click.argument("setting")
@click.argument("value")
def set_cmd(setting, value):
    """Configure a global pm setting.

    Boolean settings (on/off):

      hide-assist     Hide the Assist (H) key from the TUI status and footer bars

      hide-merged     Hide merged PRs in the TUI by default

      beginner-mode   Add helpful next-step guidance to all Claude sessions

      auto-cleanup    Suggest cleaning up old panes in Claude sessions

    Value settings:

      min-pane-width  Minimum characters per horizontal pane (default 100)
    """
    from pm_core.paths import set_global_setting, set_global_setting_value
    boolean_settings = {"hide-assist", "hide-merged", "beginner-mode", "auto-cleanup"}
    int_settings = {"min-pane-width"}
    known = boolean_settings | int_settings
    if setting not in known:
        click.echo(f"Unknown setting: {setting}", err=True)
        click.echo(f"Available: {', '.join(sorted(known))}", err=True)
        raise SystemExit(1)
    if setting in boolean_settings:
        if value not in ("on", "off"):
            click.echo(f"Setting '{setting}' takes 'on' or 'off'", err=True)
            raise SystemExit(1)
        set_global_setting(setting, value == "on")
    elif setting in int_settings:
        try:
            int(value)
        except ValueError:
            click.echo(f"Setting '{setting}' takes a number", err=True)
            raise SystemExit(1)
        set_global_setting_value(setting, value)
    click.echo(f"{setting} = {value}")


@cli.command("setting")
@click.argument("setting")
@click.argument("value")
@click.pass_context
def setting_cmd(ctx, setting, value):
    """Alias for 'pm set'. Configure a global pm setting."""
    ctx.invoke(set_cmd, setting=setting, value=value)


@cli.command("status")
def status_cmd():
    """Show project status: active PR, counts by status."""
    root = state_root()
    data = store.load(root)
    project = data.get("project", {})
    prs = data.get("prs") or []
    plans = data.get("plans") or []

    click.echo(f"Project: {project.get('name', '???')}")
    click.echo(f"  repo: {project.get('repo', '???')}")
    click.echo(f"  base branch: {project.get('base_branch', 'master')}")
    click.echo(f"  backend: {project.get('backend', 'vanilla')}")
    click.echo()

    active_pr = project.get("active_pr")
    if active_pr:
        pr = store.get_pr(data, active_pr)
        if pr:
            click.echo(f"Active PR: {_pr_display_id(pr)} — {pr.get('title', '???')} [{pr.get('status', '?')}]")
        else:
            click.echo(f"Active PR: {active_pr} (not found)")
    else:
        click.echo("Active PR: none")

    # Count by status
    counts: dict[str, int] = {}
    for p in prs:
        s = p.get("status", "pending")
        counts[s] = counts.get(s, 0) + 1

    click.echo(f"\nPRs: {len(prs)} total")
    status_icons = {
        "pending": "⏳", "in_progress": "🔨", "in_review": "👀",
        "merged": "✅", "closed": "🚫",
    }
    for s in ("pending", "in_progress", "in_review", "merged", "closed"):
        if s in counts:
            click.echo(f"  {status_icons.get(s, '?')} {s}: {counts[s]}")

    if plans:
        click.echo(f"\nPlans: {len(plans)}")


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

    pr_entry = _resolve_pr_id(data, pr_id)
    if not pr_entry:
        prs = data.get("prs") or []
        click.echo(f"PR '{pr_id}' not found.", err=True)
        if prs:
            click.echo(f"Available PRs: {', '.join(_pr_display_id(p) for p in prs)}", err=True)
        raise SystemExit(1)

    click.echo(prompt_gen.generate_prompt(data, pr_entry["id"]))


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
    branch_name = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    branch = branch_name if branch_name and branch_name != "HEAD" else "master"

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

    lines = "\nGetting Started\n" + "=" * 60 + "\n\n"

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
  1. Start a session (recommended):
       pm session
     Starts a tmux session with TUI + notes editor.  A guide Claude session
     auto-launches to walk you through setup.

  Or use individual CLI commands:
     pm init                     Initialize pm/ directory
     pm plan add "name"          Add a plan (launches Claude)
     pm plan breakdown           Break plan into PRs (launches Claude)
     pm plan review              Review plan consistency (launches Claude)
     pm plan load                Load PRs from plan file

  In the TUI, press p to open the plans view.  Plan action keys:
     a=add  w=breakdown  c=review  l=load  e=edit  v=view

  Working with PRs:
     pm pr start                 Clone, branch, launch Claude session
     pm pr review                Mark PR as in_review, open review window
     pm pr sync                  Check for merges, unblock dependents
     pm push                     Commit and share pm/ changes

  Tip: Arguments in [brackets] are optional — pm infers them when possible."""

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
  pm status                     Show project status: active PR, counts by status
  pm push                       Commit pm/ changes to a branch and create PR
  pm session                    Start tmux session with TUI + notes editor
  pm plan add <name>            Add a plan and launch Claude to develop it
  pm plan list                  List plans
  pm plan breakdown [plan-id]   Launch Claude to break plan into PRs
  pm plan review [plan-id]      Launch Claude to review plan-PR consistency
  pm plan deps                  Launch Claude to review/fix PR dependencies
  pm plan load [plan-id]        Create PRs from plan file (non-interactive)
  pm plan import [--name NAME]  Bootstrap PR graph from existing repo (interactive)
  pm plan fixes                 List pending review files with fix commands
  pm plan fix --review <file>   Fix issues found by any review

  pm pr add <title>             Add a PR (becomes active) [--plan, --depends-on]
  pm pr edit <pr-id>            Edit PR title, description, or dependencies
  pm pr select <pr-id>          Set the active PR
  pm pr cd <pr-id>              Open a shell in a PR's workdir
  pm pr list                    List PRs with status (* = active)
  pm pr graph                   Show dependency tree
  pm pr ready                   Show PRs ready to start
  pm pr start [pr-id]           Clone, branch, launch Claude (tmux window or blocking)
  pm pr review [pr-id]          Mark PR as in_review, open review window
  pm pr sync                    Check for merged PRs
  pm pr sync-github             Fetch and update PR statuses from GitHub
  pm pr import-github           Import existing GitHub PRs into project yaml
  pm pr close [pr-id]           Close and remove a PR (also closes GitHub PR)
  pm pr cleanup [pr-id]         Remove workdir for merged PR
  pm pr note add <pr-id> <text>        Add a note to a PR
  pm pr note edit <pr-id> <id> <text>  Edit a note's text
  pm pr note list <pr-id>              List notes on a PR
  pm pr note delete <pr-id> <id>       Delete a note from a PR

  pm cluster auto               Discover feature clusters automatically
  pm cluster explore            Interactively explore code clusters with Claude

  pm bench models               List models on local inference backend
  pm bench exercises            List available benchmark exercises
  pm bench run <model>          Run benchmark with tournament selection

  pm guide                      Guided workflow (init → plan → PRs → start)
  pm notes                      Open session notes in editor
  pm prompt [pr-id]             Print Claude prompt for a PR
  pm tui                        Launch interactive dashboard
  pm meta [task]                Work on pm itself (meta-development session)
  pm monitor                    Run autonomous monitor loop (blocking)
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
# Import submodules to register their commands on ``cli``.
# This must be at the bottom of the file, after ``cli`` is defined.
# ---------------------------------------------------------------------------
from pm_core.cli import pr, plan, session, tui, guide, meta, cluster, bench, monitor  # noqa: E402, F401


def main():
    cli()
