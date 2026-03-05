"""QA instruction library CLI commands."""

import os
import subprocess

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
    item = qa_instructions.get_instruction(root, instruction_id, "instructions")
    if item is None:
        item = qa_instructions.get_instruction(root, instruction_id, "regression")
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
    scenario = qa_loop.QAScenario(
        index=1,
        title=item["title"],
        focus=item["description"] or item["title"],
        instruction_path=item["path"],
        steps=f"Follow the instruction at {item['path']}",
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
    if state.made_changes:
        click.echo("  Changes were committed during QA.")


@qa.group("container")
def qa_container():
    """Manage container isolation for Claude sessions.

    When enabled, all Claude sessions (implementation, review, QA, watcher)
    run inside Docker containers for isolation.  Only the Claude process
    itself runs in the container — companion panes and status panes remain
    on the host.
    """


@qa_container.command("status")
def qa_container_status():
    """Show current container isolation settings."""
    from pm_core.container import (
        is_container_mode_enabled, load_container_config, _docker_available,
    )

    enabled = is_container_mode_enabled()
    cfg = load_container_config()
    docker_ok = _docker_available()

    click.echo(f"Container mode:  {'enabled' if enabled else 'disabled'}")
    click.echo(f"Docker available: {'yes' if docker_ok else 'no'}")
    click.echo(f"Image:           {cfg.image}")
    click.echo(f"Memory limit:    {cfg.memory_limit}")
    click.echo(f"CPU limit:       {cfg.cpu_limit}")

    if enabled and not docker_ok:
        click.echo(
            "\nWarning: Container mode is enabled but Docker is not available.",
            err=True,
        )


@qa_container.command("enable")
def qa_container_enable():
    """Enable container isolation for Claude sessions."""
    from pm_core.paths import set_global_setting
    from pm_core.container import _docker_available

    if not _docker_available():
        click.echo("Error: Docker is not available. Install and start Docker first.",
                    err=True)
        raise SystemExit(1)

    set_global_setting("qa-container-enabled", True)
    click.echo("Container isolation enabled.")


@qa_container.command("disable")
def qa_container_disable():
    """Disable container isolation (run Claude directly on the host)."""
    from pm_core.paths import set_global_setting

    set_global_setting("qa-container-enabled", False)
    click.echo("Container isolation disabled.")


@qa_container.command("set")
@click.argument("key", type=click.Choice(["image", "memory-limit", "cpu-limit"]))
@click.argument("value")
def qa_container_set(key: str, value: str):
    """Set a container configuration value.

    Keys: image, memory-limit, cpu-limit
    """
    from pm_core.paths import set_global_setting_value

    setting_name = f"qa-container-{key}"
    set_global_setting_value(setting_name, value)
    click.echo(f"Set {key} = {value}")


@qa_container.command("cleanup")
@click.option("--pr", "pr_id", default=None, help="Filter by PR ID")
def qa_container_cleanup(pr_id: str | None):
    """Remove stale pm containers."""
    from pm_core.container import _run_docker, remove_container, CONTAINER_PREFIX

    result = _run_docker(
        "ps", "-a", "--filter", f"name={CONTAINER_PREFIX}",
        "--format", "{{.Names}}\t{{.Status}}",
        check=False, timeout=30,
    )
    if result.returncode != 0:
        click.echo("Failed to list containers.", err=True)
        raise SystemExit(1)

    lines = result.stdout.strip().splitlines()
    if not lines or not lines[0]:
        click.echo("No pm containers found.")
        return

    removed = 0
    for line in lines:
        parts = line.split("\t", 1)
        name = parts[0].strip()
        status = parts[1].strip() if len(parts) > 1 else ""
        if pr_id and pr_id not in name:
            continue
        click.echo(f"  Removing: {name} ({status})")
        remove_container(name)
        removed += 1

    click.echo(f"Removed {removed} container(s).")


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
