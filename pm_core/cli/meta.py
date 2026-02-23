"""Meta command for the pm CLI.

Registers the ``meta`` command for working on pm itself.
"""

import os
import subprocess
from pathlib import Path

import click

from pm_core import store, git_ops
from pm_core import tmux as tmux_mod
from pm_core.claude_launcher import find_claude, build_claude_shell_cmd

from pm_core.cli import cli
from pm_core.cli.helpers import (
    _get_pm_session,
    _get_session_name_for_cwd,
)


PM_REPO_URL = "https://github.com/mjtomei/project_manager.git"


@cli.command("meta")
@click.argument("task", default="")
@click.option("--branch", "-b", default=None, help="Branch name (auto-generated if not specified)")
@click.option("--tag", "-t", default=None, help="Start from a specific tag instead of master")
def meta_cmd(task: str, branch: str | None, tag: str | None):
    """Work on pm itself — opens Claude session targeting the pm codebase.

    Clones the pm repo from GitHub, pulls the latest master (or a specific tag),
    creates a feature branch, and launches Claude with context about pm's
    architecture and how to test changes.

    Examples:
        pm meta "Add a graph zoom feature"
        pm meta --branch fix-window-detection
        pm meta --tag v1.0.0 "Backport a fix"
    """
    import re
    from datetime import datetime

    # Handle "pm meta cd" — open shell in meta workdir
    if task == "cd":
        work_path = _meta_workdir()
        if not work_path.is_dir():
            click.echo(f"Meta workdir does not exist: {work_path}", err=True)
            click.echo("Run 'pm meta' first to create it.", err=True)
            raise SystemExit(1)
        shell = os.environ.get("SHELL", "/bin/sh")
        click.echo(f"Entering meta workdir")
        click.echo(f"  {work_path}")
        click.echo(f"Type 'exit' to return.")
        os.chdir(work_path)
        os.execvp(shell, [shell])

    # Detect current installation for context
    install_info = _detect_pm_install()

    # Generate branch name first (determines workdir name)
    if not branch:
        if task:
            # Slugify the task description
            slug = re.sub(r'[^a-z0-9]+', '-', task.lower())[:40].strip('-')
            branch = f"meta/{slug}"
        else:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            branch = f"meta/session-{timestamp}"

    # Reuse the pm session's tag - ties meta work to the session you're in
    # This prevents multiple agents working on the same running session
    pm_session_name = _get_session_name_for_cwd()  # e.g., "pm-omerta_node-7112c169"
    session_tag = pm_session_name.removeprefix("pm-")  # e.g., "omerta_node-7112c169"

    # Workdir uses same tag as session
    from pm_core.paths import workdirs_base
    work_path = workdirs_base() / f"meta-{session_tag}"

    if not work_path.exists():
        click.echo(f"Cloning pm from {PM_REPO_URL}...")
        work_path.parent.mkdir(parents=True, exist_ok=True)
        git_ops.clone(PM_REPO_URL, work_path)

        # Determine base ref
        if tag:
            base_ref = tag
        else:
            base_ref = "master"

        # Checkout base and create branch
        if tag:
            click.echo(f"Checking out tag {tag}...")
            git_ops.run_git("checkout", tag, cwd=work_path, check=True)
        else:
            click.echo(f"Checking out {base_ref}...")
            git_ops.run_git("checkout", base_ref, cwd=work_path, check=True)
            click.echo(f"Pulling latest {base_ref}...")
            git_ops.pull_rebase(work_path)

        click.echo(f"Creating branch {branch} from {base_ref}...")
        git_ops.checkout_branch(work_path, branch, create=True)
    else:
        click.echo(f"Using existing workdir: {work_path}")

        # Check if workdir has in-progress work (dirty files or on a meta branch)
        status = git_ops.run_git("status", "--porcelain", cwd=work_path, check=False)
        current_branch = git_ops.run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=work_path, check=False)
        current_branch_name = current_branch.stdout.strip()
        has_dirty_files = bool(status.stdout.strip())
        on_meta_branch = current_branch_name.startswith("meta/")

        if has_dirty_files or on_meta_branch:
            # Resume existing session — don't reset the workdir
            click.echo(f"Resuming in-progress work on branch {current_branch_name}")
            if has_dirty_files:
                click.echo("(workdir has uncommitted changes)")
            branch = current_branch_name
            base_ref = "master"
        else:
            # Clean workdir — safe to update and create new branch
            click.echo("Fetching latest from origin...")
            git_ops.run_git("fetch", "origin", cwd=work_path, check=False)

            if tag:
                base_ref = tag
            else:
                base_ref = "master"

            if tag:
                click.echo(f"Checking out tag {tag}...")
                git_ops.run_git("checkout", tag, cwd=work_path, check=True)
            else:
                click.echo(f"Checking out {base_ref}...")
                git_ops.run_git("checkout", base_ref, cwd=work_path, check=True)
                click.echo(f"Pulling latest {base_ref}...")
                git_ops.pull_rebase(work_path)

            click.echo(f"Creating branch {branch} from {base_ref}...")
            git_ops.checkout_branch(work_path, branch, create=True)

    # Determine pm session name for TUI targeting
    pm_session = _get_pm_session()

    # Build the prompt
    prompt = _build_meta_prompt(task, work_path, install_info, branch, base_ref, session_tag, session_name=pm_session)

    # Check for existing window
    window_name = "meta"
    if pm_session:
        if tmux_mod.session_exists(pm_session):
            existing = tmux_mod.find_window_by_name(pm_session, window_name)
            if existing:
                tmux_mod.select_window(pm_session, existing["index"])
                click.echo(f"Switched to existing window '{window_name}'")
                return

    # Launch Claude
    claude = find_claude()
    if not claude:
        click.echo("Claude CLI not found.", err=True)
        click.echo("\nPrompt:")
        click.echo("-" * 60)
        click.echo(prompt)
        raise SystemExit(1)

    # Set active override so the wrapper uses this workdir's pm_core
    from pm_core.paths import set_override_path
    set_override_path(session_tag, work_path)
    click.echo(f"Set session override: ~/.pm/sessions/{session_tag}/override")

    # Build command with cleanup on exit
    claude_cmd = build_claude_shell_cmd(prompt=prompt, session_tag=session_tag)
    clear_cmd = f"rm -rf ~/.pm/sessions/{session_tag}"
    cmd = f"{claude_cmd} ; {clear_cmd}"

    # Try to launch in tmux (reuse pm_session from above)
    if pm_session:
        if tmux_mod.session_exists(pm_session):
            try:
                tmux_mod.new_window(pm_session, window_name, cmd, str(work_path))
                win = tmux_mod.find_window_by_name(pm_session, window_name)
                if win:
                    tmux_mod.set_shared_window_size(pm_session, win["id"])
                click.echo(f"Launched meta session in window '{window_name}'")
                return
            except Exception as e:
                click.echo(f"Failed to create tmux window: {e}", err=True)

    # Fallback: launch interactively
    click.echo("Launching Claude...")
    result = subprocess.run(f"cd '{work_path}' && {cmd}", shell=True)
    # The clear_cmd in the shell command handles cleanup
    raise SystemExit(result.returncode)


def _meta_workdir() -> Path:
    """Return the meta workdir path for the current pm session."""
    from pm_core.paths import workdirs_base
    pm_session_name = _get_session_name_for_cwd()
    session_tag = pm_session_name.removeprefix("pm-")
    return workdirs_base() / f"meta-{session_tag}"


def _detect_pm_install() -> dict:
    """Detect how pm is installed and return info for reinstalling."""
    info = {
        "type": "unknown",
        "path": None,
        "editable": False,
        "test_command": "python3 -m pytest tests/ -x -q",
        "install_command": None,
    }

    try:
        import pm_core
        pm_path = Path(pm_core.__file__).parent.parent
        info["path"] = str(pm_path)

        # Check if it's an editable install
        site_packages = Path(pm_core.__file__).parent
        while site_packages.name != "site-packages" and site_packages != site_packages.parent:
            site_packages = site_packages.parent

        if site_packages.name != "site-packages":
            # Not in site-packages = probably editable or dev install
            info["editable"] = True
            info["type"] = "editable"
            info["install_command"] = f"pip install -e {pm_path}"
        else:
            info["type"] = "pip"
            info["install_command"] = f"pip install {pm_path}"

    except ImportError:
        pass

    return info


def _build_meta_prompt(task: str, work_path: Path, install_info: dict, branch_name: str, base_ref: str, session_tag: str, session_name: str | None = None) -> str:
    """Build prompt for meta-development session."""
    task_section = f"""
## Task

{task}

**First**: Search the codebase and git history to check if this has already been
implemented or if there's existing code that addresses this. Report your findings
before making any changes.
""" if task else """
## Task

You are ready to work on pm improvements. The user will describe what they want
to change. Before implementing, always check if the issue has already been
addressed in the codebase or git history or if there is any similar
functionality you can start from or code you can reuse.
"""

    return f"""\
You are working on `pm` — the project manager tool for Claude Code sessions.
This is a meta-development session: you're improving pm while it may be running.

## Codebase

Working directory: {work_path}
Branch: {branch_name}
Based on: {base_ref}
Repo: https://github.com/mjtomei/project_manager

The pm repository has already been cloned to the working directory above.
You are on the feature branch.

## Before starting

IMPORTANT: Before implementing changes, check if the issue has already been
addressed in the upstream repository:

1. Pull the latest: `git fetch origin && git log origin/{base_ref} --oneline -20`
2. Search for related commits: `git log --oneline --all --grep="<keyword>"`
3. Check open issues/PRs: `gh issue list` and `gh pr list`

If the fix already exists upstream, tell the user they can update their
installation instead of reimplementing.

## Key files

- pm_core/cli/ — CLI package (commands split into submodules: pr, plan, session, tui, guide, meta, cluster)
- pm_core/tui/app.py — TUI app core (Textual-based), with screens.py, widgets.py, pane_ops.py for extracted code
- pm_core/tui/tech_tree.py — PR dependency graph widget, with tree_layout.py for layout algorithm
- pm_core/tmux.py — Tmux session/window/pane management
- pm_core/pane_registry.py — Pane registry I/O (multi-window format)
- pm_core/pane_layout.py — Layout algorithm and rebalancing
- pm_core/store.py — YAML state management (project.yaml)
- pm_core/git_ops.py — Git operations, get_git_root, get_github_repo_name
- pm_core/guide.py — Guided workflow state machine
- pm_core/prompt_gen.py — Claude prompt generation
- pm_core/paths.py — Centralized path management (~/.pm/)

## Debugging the TUI

The TUI runs in a tmux session. You can interact with it programmatically.
{f"Target the base session with `-s {session_name}`:" if session_name else "Use these commands:"}

**Frame buffer** — The TUI captures frames on every UI change:
- `pm tui view{f" -s {session_name}" if session_name else ""}` — Capture and display current TUI state
- `pm tui frames` — View last 5 captured frames
- `pm tui frames --all` — View all captured frames with triggers
- `pm tui clear-frames` — Clear the frame buffer

**Sending keystrokes**:
- `pm tui send <keys>{f" -s {session_name}" if session_name else ""}` — Send keystrokes to the TUI (e.g., `pm tui send g` for guide)

**Tmux inspection**:
- `tmux list-panes -t <session> -F "#{{pane_id}} #{{pane_width}}x#{{pane_height}}"` — List panes
- `cat ~/.pm/pane-registry/<session>.json` — View pane registry (tracks pane roles/order)

**Debug logging** — Enable by creating `~/.pm/sessions/{session_tag}/debug`:
```bash
touch ~/.pm/sessions/{session_tag}/debug
```
Logs are written to `~/.pm/pane-registry/`:
- `tui.log` — TUI events and actions
- `cli.log` — CLI command execution
- `layout.log` — Pane layout rebalancing
- `claude_launcher.log` — Claude session launches

## Session override (how this session works)

**An override is already active for this session.** When `pm meta` launched,
it called `set_override_path("{session_tag}", "{work_path}")`, which wrote
this workdir's path to `~/.pm/sessions/{session_tag}/override`.

The pm wrapper (`pm_core/wrapper.py`) checks for this override on every
invocation.  Its priority order is:
1. **Session override** — reads `~/.pm/sessions/{{tag}}/override`, prepends
   that path to `sys.path`, and reloads `pm_core` from there
2. **Local pm_core** — if the cwd (or a parent) contains `pm_core/`, uses it
3. **Installed pm_core** — falls back to the pip-installed version

This means any changes you make to files in this workdir take effect
immediately for all `pm` commands run within this session's tmux environment.
The override file is automatically deleted when this Claude session exits.

## Prompt generation system

All Claude sessions launched by pm receive generated prompts from
`pm_core/prompt_gen.py`:

- **`generate_prompt(data, pr_id)`** — Work session prompt (used by `pm pr start`).
  Includes PR context, dependencies, task description, workflow instructions.
- **`generate_review_prompt(data, pr_id, ...)`** — Review session prompt (used by
  `pm pr done`).  Includes review checklist, plan context, and verdict instructions.
  When `review_loop=True`, appends fix/commit/push instructions for automated
  review iterations.
- **`_build_meta_prompt()`** — This prompt (used by `pm meta`).  Provides
  architecture info, override explanation, and testing instructions.

Prompts are passed to Claude via `pm_core/claude_launcher.py`, which handles
session resumption, `--session-id` management, and prompt file creation.

## Testing changes

1. Run tests:
```bash
python3 -m pytest tests/ -x -q
```

2. Test changes live — just run `pm` commands normally. They use this workdir's code.

3. For TUI changes, restart the TUI (`q` to detach, `pm session` to reattach).

**To install permanently** (make changes the default for all sessions):
```bash
./install.sh --local --force
```

## Contributing changes upstream

If the changes are improvements or bug fixes others would benefit from, they
can be contributed back to the main pm repository:

1. Commit the changes with a clear message
2. Push the branch: `git push -u origin {branch_name}`
3. Create a PR: `gh pr create --title "..." --body "..."`

The main pm repo is: https://github.com/mjtomei/project_manager
"""
