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


@qa.command("regression")
@click.option("--max-parallel", "-p", default=4, show_default=True,
              help="Max scenarios running concurrently.")
@click.option("--timeout", "-t", default=1800, show_default=True,
              help="Per-scenario timeout in seconds.")
@click.option("--filter", "filter_tags", multiple=True,
              help="Only run scenarios with these tags (repeatable).")
def qa_regression(max_parallel: int, timeout: int, filter_tags: tuple):
    """Run all regression tests with parallel execution and verdict collection.

    Launches each regression test as a Claude session in its own tmux window,
    polls for verdicts (PASS/NEEDS_WORK/INPUT_REQUIRED), and produces a
    summary report.  Windows stay open after completion for inspection.

    Examples:
        pm qa regression
        pm qa regression --max-parallel 2 --filter tui
        pm qa regression --timeout 600
    """
    from pm_core import regression, tmux as tmux_mod

    root = state_root()

    # Determine tmux session
    session = None
    if tmux_mod.in_tmux():
        session = tmux_mod.get_session_name()
    if not session:
        session = os.environ.get("PM_SESSION")
    if not session:
        click.echo("Not in a tmux session. Run from inside pm session or set PM_SESSION.",
                    err=True)
        raise SystemExit(1)

    tags = list(filter_tags) if filter_tags else None
    scenarios = regression.load_regression_scenarios(root, tags)
    if not scenarios:
        click.echo("No regression tests found"
                    + (f" matching tags: {', '.join(filter_tags)}" if tags else "")
                    + ".")
        return

    click.echo(f"Running {len(scenarios)} regression tests (max {max_parallel} parallel)")
    for s in scenarios:
        click.echo(f"  - {s.id}: {s.title}")
    click.echo()

    def on_update(state):
        done = len(state.results)
        total = len(state.scenarios)
        active = len(state.active)
        pending = len(state.pending)
        if done > 0:
            latest = state.results[-1]
            click.echo(f"  [{done}/{total}] {latest.scenario_id}: {latest.verdict}"
                       f" ({latest.duration_secs:.0f}s)"
                       f"  [active={active} pending={pending}]")

    state = regression.run_regression(
        pm_root=root,
        session=session,
        max_parallel=max_parallel,
        timeout=timeout,
        on_update=on_update,
        session_name=session,
        scenarios=scenarios,
    )

    click.echo()
    click.echo(regression.format_summary(state))

    # Print report location
    report_dir = os.path.expanduser(f"~/.pm/workdirs/regression/{state.run_id}")
    click.echo(f"\nReport: {report_dir}/report.txt")


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
