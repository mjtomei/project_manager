"""QA instruction library CLI commands."""

import os
import subprocess
from pathlib import Path

import click

from pm_core.cli.helpers import state_root
from pm_core.cli import cli


@cli.group()
def qa():
    """Manage QA instructions and regression tests."""


@qa.command("list")
def qa_list():
    """List QA instructions and regression tests by category."""
    from pm_core import qa_instructions

    root = state_root()
    all_items = qa_instructions.list_all(root)

    for category, label in [("instructions", "Instructions"),
                            ("regression", "Regression Tests")]:
        items = all_items[category]
        click.echo(f"\n{label} ({len(items)}):")
        if not items:
            click.echo("  (none)")
        for item in items:
            desc = f" — {item['description']}" if item["description"] else ""
            click.echo(f"  {item['id']}: {item['title']}{desc}")
    click.echo()


@qa.command("show")
@click.argument("instruction_id")
@click.option("--category", "-c", default=None,
              help="Category: instructions or regression (auto-detected)")
def qa_show(instruction_id: str, category: str | None):
    """Print the full content of a QA instruction."""
    from pm_core import qa_instructions

    root = state_root()

    # Auto-detect category if not specified
    if category is None:
        item = qa_instructions.get_instruction(root, instruction_id, "instructions")
        if item is None:
            item = qa_instructions.get_instruction(root, instruction_id, "regression")
    else:
        item = qa_instructions.get_instruction(root, instruction_id, category)

    if item is None:
        click.echo(f"Instruction not found: {instruction_id}", err=True)
        raise SystemExit(1)

    click.echo(f"# {item['title']}")
    if item["description"]:
        click.echo(f"{item['description']}")
    click.echo(f"[{item['path']}]\n")
    click.echo(item["body"])


@qa.command("add")
@click.argument("name")
def qa_add(name: str):
    """Create a new QA instruction and open it in $EDITOR."""
    from pm_core import qa_instructions

    root = state_root()
    d = qa_instructions.instructions_dir(root)

    # Sanitize name to filename
    file_id = name.lower().replace(" ", "-")
    # Remove non-alphanumeric chars except hyphens
    file_id = "".join(c for c in file_id if c.isalnum() or c == "-")
    filepath = d / f"{file_id}.md"

    if filepath.exists():
        click.echo(f"Instruction already exists: {filepath}", err=True)
        raise SystemExit(1)

    # Create template
    title = name.replace("-", " ").title()
    filepath.write_text(f"""\
---
title: {title}
description:
tags: []
---
## Setup

## Test Steps

## Expected Behavior

## Reporting
""")

    click.echo(f"Created: {filepath}")

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, str(filepath)])


@qa.command("edit")
@click.argument("instruction_id")
@click.option("--category", "-c", default=None,
              help="Category: instructions or regression (auto-detected)")
def qa_edit(instruction_id: str, category: str | None):
    """Edit a QA instruction in $EDITOR."""
    from pm_core import qa_instructions

    root = state_root()

    if category is None:
        item = qa_instructions.get_instruction(root, instruction_id, "instructions")
        if item is None:
            item = qa_instructions.get_instruction(root, instruction_id, "regression")
    else:
        item = qa_instructions.get_instruction(root, instruction_id, category)

    if item is None:
        click.echo(f"Instruction not found: {instruction_id}", err=True)
        raise SystemExit(1)

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, item["path"]])


@qa.command("run")
@click.argument("instruction_id")
@click.option("--pr", "pr_id", default=None, help="PR to run QA against")
def qa_run(instruction_id: str, pr_id: str | None):
    """Run a QA instruction against a PR.

    Creates a boilerplate single-scenario QA plan and runs it using the
    same child session infrastructure as the auto-start flow.
    """
    from pm_core import qa_instructions, store, qa_loop
    from pm_core.cli.helpers import _resolve_pr_id, _infer_pr_id

    root = state_root()

    # Find the instruction
    category = "instructions"
    item = qa_instructions.get_instruction(root, instruction_id, category)
    if item is None:
        category = "regression"
        item = qa_instructions.get_instruction(root, instruction_id, category)
    if item is None:
        click.echo(f"Instruction not found: {instruction_id}", err=True)
        raise SystemExit(1)

    data = store.load(root)

    # Resolve PR
    if pr_id is None:
        pr_id = _infer_pr_id(data)
    if pr_id is None:
        click.echo("No PR specified and no active PR found.", err=True)
        raise SystemExit(1)

    pr_data = _resolve_pr_id(data, pr_id)
    if not pr_data:
        click.echo(f"PR not found: {pr_id}", err=True)
        raise SystemExit(1)

    # Build a boilerplate single-scenario plan
    # instruction_path is relative to pm/qa/
    filename = Path(item["path"]).name
    instr_rel = f"{category}/{filename}"
    scenario = qa_loop.QAScenario(
        index=1,
        title=item["title"],
        focus=item["description"] or item["title"],
        instruction_path=instr_rel,
        steps=f"Follow the instruction file {filename}",
    )

    loop_id = f"cli-{pr_id}"
    qa_workdir = qa_loop.create_qa_workdir(pr_id, loop_id)

    state = qa_loop.QALoopState(
        pr_id=pr_id,
        loop_id=loop_id,
        scenarios=[scenario],
        planning_phase=False,
        qa_workdir=str(qa_workdir),
    )

    click.echo(f"Running QA: {item['title']} against {pr_id}")
    click.echo(f"  Workdir: {qa_workdir}")

    # Run synchronously
    def on_update(s):
        if s.latest_output:
            click.echo(f"  [{s.latest_verdict or '...'}] {s.latest_output}")

    state = qa_loop.run_qa_sync(state, root, pr_data, on_update, max_scenarios=1)

    verdict = state.latest_verdict or "UNKNOWN"
    click.echo(f"\nResult: {verdict}")


@qa.command("debug")
@click.argument("instruction_id")
@click.option("--branch", "-b", default=None,
              help="Branch to clone (default: project base branch)")
@click.option("--foreground", "-f", is_flag=True, default=False,
              help="Run in the current pane instead of a new window")
def qa_debug(instruction_id: str, branch: str | None, foreground: bool):
    """Launch an interactive session to verify a QA instruction works.

    Creates an environment identical to what QA scenario workers get
    (container if container mode is enabled, host otherwise) and drops
    you into a Claude session with the instruction loaded.  Use this to
    check that setup steps, commands, and expected outputs are correct
    before running real QA.
    """
    import secrets
    from pm_core import qa_instructions, store
    from pm_core import tmux as tmux_mod
    from pm_core.container import is_container_mode_enabled, _docker_available
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core.loop_shared import get_pm_session

    root = state_root()

    # Find the instruction
    item = qa_instructions.get_instruction(root, instruction_id, "instructions")
    if item is None:
        item = qa_instructions.get_instruction(root, instruction_id, "regression")
    if item is None:
        click.echo(f"Instruction not found: {instruction_id}", err=True)
        raise SystemExit(1)

    data = store.load(root)
    session = get_pm_session()
    if not session:
        click.echo("No pm session found. Run inside a pm tmux session.", err=True)
        raise SystemExit(1)

    # Create a workdir keyed to session + instruction (not PR)
    debug_id = secrets.token_hex(4)
    base_dir = Path(os.path.expanduser("~/.pm/workdirs/qa"))
    qa_workdir = base_dir / f"debug-{instruction_id}-{debug_id}"
    qa_workdir.mkdir(parents=True, exist_ok=True)

    # Build scenario workdir (clone + scratch)
    from pm_core.qa_loop import create_scenario_workdir

    # The repo root is the parent of the pm/ state directory
    repo_root = root.parent
    # Default to the current branch of the workdir (what the TUI session
    # is operating on), not the project base branch.
    if not branch:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(repo_root),
        )
        branch = result.stdout.strip() if result.returncode == 0 else "master"
    base_branch = branch
    clone_path, scratch_path = create_scenario_workdir(
        qa_workdir, scenario_index=0,
        repo_root=repo_root,
        pr_id=f"debug-{instruction_id}",
        loop_id=debug_id,
        branch=base_branch,
    )

    # Install instruction file into scratch
    filename = Path(item["path"]).name
    dest_dir = scratch_path / "qa-instructions"
    dest_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(item["path"], dest_dir / filename)

    use_containers = is_container_mode_enabled() and _docker_available()

    if use_containers:
        from pm_core import container as container_mod
        container_scratch = container_mod._CONTAINER_SCRATCH
        instr_path = f"{container_scratch}/qa-instructions/{filename}"
    else:
        instr_path = str(dest_dir / filename)

    prompt = f"""You are debugging a QA instruction to verify it works correctly.

## Task

Read the instruction file at: `{instr_path}`

Follow its Setup and Test Steps exactly as a QA scenario worker would.
Your goal is to verify that every step in the instruction is executable
in this environment and produces the expected results.

## Environment

You are in the same environment that QA scenario workers use.
- **Workdir**: {str(clone_path) if not use_containers else container_mod._CONTAINER_WORKDIR}
- **Scratch dir**: {str(scratch_path) if not use_containers else container_scratch}

## What to report

As you work through each step, note:
- Steps that work as described
- Steps that fail or need adjustment (missing tools, wrong paths, etc.)
- Steps that are ambiguous or impossible to execute
- Whether expected outputs match what actually happens

End with a summary of which steps work and which don't, then one of:
- **PASS** — All steps are executable and produce expected results
- **NEEDS_WORK** — Some steps need fixes (explain what)
- **INPUT_REQUIRED** — Cannot proceed without human guidance"""

    from pm_core.qa_loop import _setup_clone_override
    _setup_clone_override(clone_path)

    window_name = f"qa-debug-{instruction_id[:20]}"

    if use_containers:
        from pm_core import container as container_mod

        config = container_mod.load_container_config()
        session_tag = session.removeprefix("pm-") if session else None
        cname = f"{container_mod.CONTAINER_PREFIX}qa-debug-{instruction_id}-{debug_id}"

        container_mod.create_qa_container(
            name=cname,
            config=config,
            workdir=clone_path,
            scratch_path=scratch_path,
            allowed_push_branch=base_branch,
            session_tag=session_tag,
        )

        claude_cmd = build_claude_shell_cmd(
            prompt=prompt,
            cwd=container_mod._CONTAINER_WORKDIR,
        )
        shell_cmd = container_mod.build_exec_cmd(cname, claude_cmd, cleanup=True)
        run_cwd = str(qa_workdir)
    else:
        shell_cmd = build_claude_shell_cmd(
            prompt=prompt,
            cwd=str(clone_path),
        )
        run_cwd = str(clone_path)

    if foreground:
        click.echo(f"Debug: {item['title']}")
        click.echo(f"  Workdir: {qa_workdir}")
        os.chdir(run_cwd)
        os.execvp("bash", ["bash", "-c", shell_cmd])
    else:
        tmux_mod.new_window_get_pane(
            session, window_name, shell_cmd,
            cwd=run_cwd, switch=False,
        )
        click.echo(f"Launched debug session")
        click.echo(f"  Instruction: {item['title']}")
        click.echo(f"  Workdir: {qa_workdir}")
        click.echo(f"  Window: {window_name}")


@qa.command("standalone")
@click.argument("instruction_id")
def qa_standalone(instruction_id: str):
    """Run a QA instruction against the current codebase without a PR.

    Uses a generic prompt without PR-specific context.  Useful for running
    regression tests against the master branch.
    """
    import time
    from pm_core import qa_instructions, store, prompt_gen
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core import tmux as tmux_mod

    root = state_root()

    # Find the instruction
    item = qa_instructions.get_instruction(root, instruction_id, "instructions")
    if item is None:
        item = qa_instructions.get_instruction(root, instruction_id, "regression")
    if item is None:
        click.echo(f"Instruction not found: {instruction_id}", err=True)
        raise SystemExit(1)

    data = store.load(root)
    session_name = os.environ.get("PM_SESSION") or "pm-standalone-qa"

    prompt = prompt_gen.generate_standalone_qa_prompt(
        data, instruction_id, session_name,
    )

    # Create workdir
    timestamp = int(time.time())
    workdir = os.path.expanduser(
        f"~/.pm/workdirs/qa/standalone-{instruction_id}-{timestamp}"
    )
    os.makedirs(workdir, exist_ok=True)

    click.echo(f"Running standalone QA: {item['title']}")
    click.echo(f"  Workdir: {workdir}")

    cmd = build_claude_shell_cmd(prompt=prompt)
    # Launch as tmux window if in a session, otherwise blocking
    session = tmux_mod.get_session_name() if tmux_mod.in_tmux() else None
    if session:
        window_name = f"qa-{instruction_id}"
        tmux_mod.new_window(session, window_name, cmd, cwd=workdir)
        click.echo(f"  Launched in tmux window: {window_name}")
    else:
        click.echo("  Running in foreground (no tmux session detected)")
        os.chdir(workdir)
        os.execvp("bash", ["bash", "-c", cmd])
