"""QA instruction library CLI commands."""

import os
import subprocess
from pathlib import Path

import click

from pm_core.cli.helpers import state_root
from pm_core.cli import cli


@cli.group()
def qa():
    """Manage QA instructions, regression tests, artifact recipes, and mocks."""


_QA_LIST_CATEGORIES = [
    ("instructions", "Instructions"),
    ("regression", "Regression Tests"),
    ("artifacts", "Artifact Recipes"),
]


def _resolve_qa_item(qa_instructions, root, instruction_id, category):
    """Resolve a QA item across categories, with optional category hint."""
    if category is not None:
        return qa_instructions.get_instruction(root, instruction_id, category)
    for cat, _ in _QA_LIST_CATEGORIES:
        item = qa_instructions.get_instruction(root, instruction_id, cat)
        if item is not None:
            return item
    return None


@qa.command("list")
def qa_list():
    """List QA instructions, regression tests, and artifact recipes."""
    from pm_core import qa_instructions

    root = state_root()
    all_items = qa_instructions.list_all(root)

    for category, label in _QA_LIST_CATEGORIES:
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
              help="Category: instructions, regression, or artifacts "
                   "(auto-detected)")
def qa_show(instruction_id: str, category: str | None):
    """Print the full content of a QA instruction or artifact recipe."""
    from pm_core import qa_instructions

    root = state_root()
    item = _resolve_qa_item(qa_instructions, root, instruction_id, category)

    if item is None:
        click.echo(f"QA item not found: {instruction_id}", err=True)
        raise SystemExit(1)

    click.echo(f"# {item['title']}")
    if item["description"]:
        click.echo(f"{item['description']}")
    click.echo(f"[{item['path']}]\n")
    click.echo(item["body"])


_ADD_TEMPLATES = {
    "instructions": """\
---
title: {title}
description:
---
## Setup

## Test Steps

## Expected Behavior

## Reporting
""",
    "regression": """\
---
title: {title}
description:
---
You are a careful tester. Bring up the surface this test exercises
(spawn a pane, start a server, invoke a CLI — whatever fits), drive
it through the scenarios below, and report results.

## Scenarios

- Scenario 1: <what to verify>

## Reporting

For each scenario, report PASS or FAIL with one line of evidence.
End with an overall PASS/FAIL.
""",
    "artifacts": """\
---
title: {title}
description:
---
## When to use

## What this recipe produces

## Capture

## Manifest format
""",
}


def _category_dir(qa_instructions, root, category):
    if category == "artifacts":
        return qa_instructions.artifacts_dir(root)
    if category == "regression":
        return qa_instructions.regression_dir(root)
    return qa_instructions.instructions_dir(root)


def _qa_add(name: str, category: str) -> None:
    """Shared implementation for add-instruction / add-regression / add-artifact."""
    from pm_core import qa_instructions

    root = state_root()
    d = _category_dir(qa_instructions, root, category)

    file_id = name.lower().replace(" ", "-")
    file_id = "".join(c for c in file_id if c.isalnum() or c == "-")
    filepath = d / f"{file_id}.md"

    if filepath.exists():
        click.echo(f"Already exists: {filepath}", err=True)
        raise SystemExit(1)

    title = name.replace("-", " ").title()
    filepath.write_text(_ADD_TEMPLATES[category].format(title=title))

    click.echo(f"Created: {filepath}")

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, str(filepath)])


@qa.command("add-instruction")
@click.argument("name")
def qa_add_instruction(name: str):
    """Create a new QA instruction in pm/qa/instructions/ and open in $EDITOR."""
    _qa_add(name, "instructions")


@qa.command("add-regression")
@click.argument("name")
def qa_add_regression(name: str):
    """Create a new regression test in pm/qa/regression/ and open in $EDITOR."""
    _qa_add(name, "regression")


@qa.command("add-artifact")
@click.argument("name")
def qa_add_artifact(name: str):
    """Create a new artifact recipe in pm/qa/artifacts/ and open in $EDITOR."""
    _qa_add(name, "artifacts")


@qa.command("captures-path")
@click.argument("pr_id")
def qa_captures_path(pr_id: str):
    """Print the host path of the captures directory for a PR.

    Captures (QA recordings, transcripts, bug-fix pre/post-fix
    artifacts, regression captures) live under
    ``~/.pm/sessions/<session-tag>/captures/<pr-id>/`` and are bind-
    mounted to ``/pm-captures`` inside scenario containers. Use this
    command to resolve the host path for tooling that needs to read
    captures (review sessions, sync to remote storage, etc.).

    Accepts the canonical pm PR id (``pr-NNN``), a GitHub PR number
    (``42``), or a #-prefixed GitHub number (``#42``) — same
    resolution as ``pm pr cd``.

    Inside a container the captures dir is bind-mounted at
    ``/pm-captures``; this command prints that path (because the
    host-side ``~/.pm`` location isn't visible from inside the
    container) so a session can resolve its own captures path without
    caring whether it runs on the host or inside a container.
    """
    from pm_core import store
    from pm_core.cli.helpers import _resolve_pr_id, state_root
    from pm_core.paths import captures_dir

    data = store.load(state_root())
    pr_entry = _resolve_pr_id(data, pr_id)
    if pr_entry is None:
        click.echo(f"PR '{pr_id}' not found.", err=True)
        raise click.exceptions.Exit(1)
    path = captures_dir(pr_entry["id"])
    if path is None:
        click.echo(
            "Error: cannot resolve session tag (not inside a git repo?)",
            err=True,
        )
        raise click.exceptions.Exit(1)
    click.echo(str(path))


def _author_path(category: str, name: str) -> Path:
    from pm_core import qa_instructions
    root = state_root()
    d = _category_dir(qa_instructions, root, category)
    file_id = "".join(c for c in name.lower().replace(" ", "-")
                      if c.isalnum() or c == "-")
    return d / f"{file_id}.md"


def _qa_author(name: str, category: str) -> None:
    """Launch a Claude session that walks the user through authoring."""
    from pm_core import qa_authoring
    from pm_core.claude_launcher import launch_claude

    target = _author_path(category, name)
    if target.exists():
        click.echo(f"Already exists: {target}", err=True)
        raise SystemExit(1)

    root = state_root()
    prompt = qa_authoring.build_authoring_prompt(name, category, target)
    rc = launch_claude(prompt, session_key=f"qa-author:{category}:{name}",
                       pm_root=root, resume=False, session_type="qa_author")
    raise SystemExit(rc)


@qa.command("author-instruction")
@click.argument("name")
def qa_author_instruction(name: str):
    """Author a new QA instruction with a guided Claude session."""
    _qa_author(name, "instructions")


@qa.command("author-regression")
@click.argument("name")
def qa_author_regression(name: str):
    """Author a new regression test with a guided Claude session."""
    _qa_author(name, "regression")


@qa.command("author-artifact")
@click.argument("name")
def qa_author_artifact(name: str):
    """Author a new artifact recipe with a guided Claude session."""
    _qa_author(name, "artifacts")


@qa.command("docs")
def qa_docs():
    """Print the QA library reference (schema, conventions, surfaces)."""
    from pm_core import qa_authoring
    click.echo(qa_authoring.qa_library_doc(), nl=False)


@qa.command("edit")
@click.argument("instruction_id")
@click.option("--category", "-c", default=None,
              help="Category: instructions, regression, or artifacts "
                   "(auto-detected)")
def qa_edit(instruction_id: str, category: str | None):
    """Edit a QA instruction or artifact recipe in $EDITOR."""
    from pm_core import qa_instructions

    root = state_root()
    item = _resolve_qa_item(qa_instructions, root, instruction_id, category)

    if item is None:
        click.echo(f"QA item not found: {instruction_id}", err=True)
        raise SystemExit(1)

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, item["path"]])


@qa.command("regression")
@click.argument("test_id")
@click.option("--session", "-s", default=None, help="Specify pm session name")
@click.option("--file-prs", "file_prs", is_flag=True, default=False,
              help="File PRs (--plan bugs, --plan improvements) for any findings")
@click.option("--file-bugs", "file_prs", is_flag=True, default=False, hidden=True)
def qa_regression(test_id: str, session: str | None, file_prs: bool):
    """Run a regression test from pm/qa/regression/.

    Each test is a Claude prompt; the runner assembles a Session
    Context, optional findings-filing addendum, and the test body, then
    launches Claude to exercise the project and report back.

    Use `pm qa list` to see available regression tests.
    """
    from pathlib import Path
    from pm_core import qa_instructions
    from pm_core.cli.helpers import _find_tui_pane
    from pm_core.regression_prompts import build_regression_test_prompt
    from pm_core.claude_launcher import launch_claude

    try:
        root = state_root()
    except FileNotFoundError:
        root = Path.home() / ".pm"

    item = qa_instructions.get_instruction(root, test_id, category="regression")
    if not item:
        click.echo(f"Unknown regression test: {test_id}", err=True)
        click.echo("Run 'pm qa list' to see available tests.")
        raise SystemExit(1)

    body = item.get("body", "")
    title = item.get("title", test_id)

    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found. Start one with 'pm session'.", err=True)
        raise SystemExit(1)

    full_prompt = build_regression_test_prompt(
        session=sess,
        pane_id=pane_id,
        title=title,
        body=body,
        file_findings=file_prs,
    )

    click.echo(f"Running regression: {title}")
    click.echo(f"Session: {sess}")
    click.echo("-" * 60)

    rc = launch_claude(full_prompt, session_key=f"qa-regression:{test_id}",
                       pm_root=root, cwd=None, resume=False,
                       session_type="qa_regression")
    raise SystemExit(rc)


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
    from pm_core.container import is_container_mode_enabled, _runtime_available
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

    use_containers = is_container_mode_enabled() and _runtime_available()

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
            write_dir=str(clone_path),
            session_type="qa_author",
        )
        shell_cmd = container_mod.build_exec_cmd(cname, claude_cmd, cleanup=True)
        run_cwd = str(qa_workdir)
    else:
        shell_cmd = build_claude_shell_cmd(
            prompt=prompt,
            cwd=str(clone_path),
            session_type="qa_author",
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


@qa.command("launch")
@click.argument("item_id")
@click.option("--target-window", default=None,
              help="tmux window to launch into (split as a new pane). "
                   "If omitted, opens a new window named after the item.")
def qa_launch(item_id: str, target_window: str | None):
    """Launch a QA instruction or regression test as a Claude pane.

    Headless equivalent of the TUI's ``launch_qa_item`` — meant for
    watchers that need to spawn QA sessions without going through the TUI
    process.

    *item_id* has the form ``category:id`` (e.g. ``regression:auth-flow``).
    """
    from pm_core import qa_instructions
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core import tmux as tmux_mod

    parts = item_id.split(":", 1)
    if len(parts) != 2:
        click.echo(f"Invalid QA item id (expected 'category:id'): {item_id}", err=True)
        raise SystemExit(1)
    category, qa_id = parts

    root = state_root()
    item = qa_instructions.get_instruction(root, qa_id, category=category)
    if item is None:
        click.echo(f"QA item not found: {item_id}", err=True)
        raise SystemExit(1)

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        click.echo("pm qa launch requires tmux.", err=True)
        raise SystemExit(1)

    session = tmux_mod.get_session_name()
    if not session:
        click.echo("No tmux session detected.", err=True)
        raise SystemExit(1)

    sess_label = os.environ.get("PM_SESSION") or session
    title = item.get("title", qa_id)
    body = item.get("body", "")

    if category == "regression":
        # Route regression launches through the unified builder so headless
        # and TUI launches produce identical prompts.
        from pm_core.regression_prompts import build_regression_test_prompt
        full_prompt = build_regression_test_prompt(
            session=sess_label,
            pane_id=None,
            title=title,
            body=body,
            file_findings=True,
        )
    else:
        full_prompt = f"""\
## Session Context

You are running a QA instruction against tmux session: {sess_label}

To interact with this session, use commands like:
- pm tui view -s {sess_label}
- pm tui send <keys> -s {sess_label}
- tmux list-panes -t {sess_label} -F "#{{pane_id}} #{{pane_width}}x#{{pane_height}} #{{pane_current_command}}"
- cat ~/.pm/pane-registry/{sess_label}.json

## QA Instruction: {title}

{body}
"""

    cmd = build_claude_shell_cmd(prompt=full_prompt, session_type="qa_author")
    cwd = str(root.parent) if root.name == "pm" else str(root)

    if target_window:
        win = tmux_mod.find_window_by_name(session, target_window)
        if not win:
            click.echo(f"Target window not found: {target_window}", err=True)
            raise SystemExit(1)
        pane_id = tmux_mod.split_pane(session, "h", cmd, window=win["id"])
        click.echo(f"Launched {item_id} in window '{target_window}' (pane {pane_id})")
    else:
        window_name = f"qa-{qa_id}"
        tmux_mod.new_window(session, window_name, cmd, cwd=cwd, switch=False)
        click.echo(f"Launched {item_id} in new window '{window_name}'")


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

    cmd = build_claude_shell_cmd(prompt=prompt, cwd=workdir, session_type="qa_author")
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


# ---------------------------------------------------------------------------
# pm qa mocks — shared mock definition library
# ---------------------------------------------------------------------------

@qa.group("mocks")
def qa_mocks():
    """Manage shared mock definitions (pm/qa/mocks/).

    Mocks defined here are injected into every QA scenario prompt so all
    parallel scenario agents use the same contracts rather than independently
    deciding how to simulate external dependencies (Claude sessions, git
    operations, tmux, etc.).
    """


@qa_mocks.command("list")
def qa_mocks_list():
    """List all shared mock definitions."""
    from pm_core import qa_instructions

    root = state_root()
    mocks = qa_instructions.list_mocks(root)

    if not mocks:
        click.echo("No mock definitions found in pm/qa/mocks/")
        click.echo("Use 'pm qa mocks add <name>' to create one.")
        return

    click.echo(f"\nMocks ({len(mocks)}):")
    for mock in mocks:
        desc = f" — {mock['description']}" if mock["description"] else ""
        click.echo(f"  {mock['id']}: {mock['title']}{desc}")
    click.echo()


@qa_mocks.command("show")
@click.argument("mock_id")
def qa_mocks_show(mock_id: str):
    """Print the full content of a mock definition."""
    from pm_core import qa_instructions

    root = state_root()
    mock = qa_instructions.get_mock(root, mock_id)

    if mock is None:
        click.echo(f"Mock not found: {mock_id}", err=True)
        raise SystemExit(1)

    click.echo(f"# {mock['title']}")
    if mock["description"]:
        click.echo(mock["description"])
    click.echo(f"[{mock['path']}]\n")
    click.echo(mock["body"])


@qa_mocks.command("add")
@click.argument("name")
def qa_mocks_add(name: str):
    """Create a new mock definition and open it in $EDITOR."""
    from pm_core import qa_instructions

    root = state_root()
    d = qa_instructions.mocks_dir(root)

    file_id = name.lower().replace(" ", "-")
    file_id = "".join(c for c in file_id if c.isalnum() or c == "-")
    filepath = d / f"{file_id}.md"

    if filepath.exists():
        click.echo(f"Mock already exists: {filepath}", err=True)
        raise SystemExit(1)

    title = name.replace("-", " ").title()
    filepath.write_text(f"""\
---
title: {title}
description:
tags: []
---
## Contract

What external dependency this mock simulates, and what behavior it stands
in for (e.g. "Claude API sessions — simulates a Claude session that returns
scripted responses without making real API calls").

## Scripted Responses

The responses or return values this mock should produce for common test
scenarios.  Be specific enough that scenario agents can implement the mock
consistently.

## What Remains Unmocked

What is still real (not mocked) even when this mock is active.
""")

    click.echo(f"Created: {filepath}")

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, str(filepath)])


@qa_mocks.command("edit")
@click.argument("mock_id")
def qa_mocks_edit(mock_id: str):
    """Edit a mock definition in $EDITOR."""
    from pm_core import qa_instructions

    root = state_root()
    mock = qa_instructions.get_mock(root, mock_id)

    if mock is None:
        click.echo(f"Mock not found: {mock_id}", err=True)
        raise SystemExit(1)

    editor = os.environ.get("EDITOR", "vim")
    subprocess.run([editor, mock["path"]])


@qa_mocks.command("prompt")
def qa_mocks_prompt():
    """Print the mocks block that gets injected into QA scenario prompts.

    Use this to verify what mock contracts scenario agents will see.
    """
    from pm_core import qa_instructions

    root = state_root()
    block = qa_instructions.mocks_for_prompt(root)

    if not block:
        click.echo("No mocks defined — scenario prompts will have no Mocks section.")
        click.echo("Use 'pm qa mocks add <name>' to define one.")
        return

    click.echo(block)
