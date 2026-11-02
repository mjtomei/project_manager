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
            if category == "regression":
                click.echo("  (none — author one with "
                           "'pm qa author-regression <name>')")
            else:
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
    caring whether it runs on the host or inside a container. The mount
    is only used for the PR named by ``PM_CAPTURES_PR``; with that marker
    absent or naming a different PR, the container-local ``~/.pm`` path
    is printed instead (fail closed — see :func:`pm_core.paths.captures_dir`).
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
            "Error: cannot resolve captures dir: no session tag (not "
            "inside a git repo?) and no /pm-captures mount owned by this "
            "PR (PM_CAPTURES_PR)",
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


# Environment variables that point a ``pm`` command at a particular project or
# session.  A regression session inheriting them (e.g. ``PM_PROJECT`` set by
# the TUI command bar) would aim the disposable test project's ``pm`` commands
# at the user's project, so they are dropped from its environment.
#
# The tmux ones matter for a run launched from a pane of the user's pm session
# (TUI Enter, ``pm qa launch``, a pane shell): pm resolves "the current pm
# session" from ``$TMUX_PANE`` before the cwd, so a ``pm session`` started in
# the test's own project would reuse, rebalance and try to attach the user's
# session instead of creating the test's (QA S12, R28).  ``PM_IN_TMUX_SESSION``
# makes commands such as ``pm pr merge`` open windows in that session, and
# ``PM_POPUP_SESSION`` names it when the run is started from a popup.
# ``PM_SHARE_MODE`` comes from a ``pm session --global``/``--group`` session:
# ``get_session_tag`` mixes it into every project's hash, so ``pm tui view``
# (and other cwd lookups) in the test's own project would miss that
# project's session and fall back to the user's TUI (QA S16, R7/R34).  Host
# mode still shares the user's tmux server (``PM_TMUX_SOCKET`` is kept); the
# session's own pm commands just behave as they do outside tmux.  Without
# ``TMUX`` a plain ``tmux`` command ignores that socket and reaches the
# default server, so the prompt names the socket (``tmux_socket``).
_REGRESSION_SCRUBBED_ENV = ("PM_PROJECT", "PM_SESSION", "TMUX", "TMUX_PANE",
                            "PM_POPUP_SESSION", "PM_IN_TMUX_SESSION",
                            "PM_SHARE_MODE")

# Push URL given to a regression clone's ``origin``.  The QA scenario clone
# helper points ``origin`` at the real upstream, and on the host (container
# mode off) the user's git credentials work there, so a stray ``git push``
# from the session would publish the clone's base branch.  A path that does
# not exist makes it fail instead ("does not appear to be a git repository").
# This guards against an accidental push; the container is the boundary.
_REGRESSION_NO_PUSH_URL = "/regression-runs-never-push"


def _discard_unlaunched_run(qa_workdir: Path,
                            run_captures: Path | None = None) -> None:
    """Remove what a regression run that never launched created.

    Drops the run's own workdir and, when given, its captures dir and the
    test's dir if that was its first run.  Only empty captures dirs are
    removed (``rmdir``), so no evidence is lost; the dir exists then only
    because container creation made it for its mount.
    """
    import shutil
    shutil.rmtree(qa_workdir, ignore_errors=True)
    if run_captures is None:
        return
    for d in (run_captures, run_captures.parent):
        try:
            d.rmdir()
        except OSError:
            break


def _install_regression_recipes(items: list[dict], scratch_path: Path,
                                subdir: str, scratch_in: str
                                ) -> list[tuple[str, str]]:
    """Copy library recipes into the run's scratch dir.

    Same ``qa-instructions`` / ``qa-artifacts`` layout the QA scenario path
    installs into, so a container session can read them.  Returns
    ``(agent-visible path, title)`` per recipe.
    """
    import shutil
    dest_dir = scratch_path / subdir
    installed: list[tuple[str, str]] = []
    for item in items:
        src = Path(item["path"])
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_dir / src.name)
        installed.append((f"{scratch_in}/{subdir}/{src.name}",
                          item.get("title", "")))
    return installed


@qa.command("regression")
@click.argument("test_id")
@click.option("--file-prs", "file_prs", is_flag=True, default=False,
              help="File PRs (--plan bugs, --plan improvements) for any findings")
@click.option("--file-bugs", "file_prs", is_flag=True, default=False, hidden=True)
@click.option("--branch", "-b", default=None,
              help="Branch to clone for the run (default: the project's "
                   "base branch)")
@click.option("--session", "-s", default=None, hidden=True,
              help="Ignored: a regression run never targets a pm session")
def qa_regression(test_id: str, file_prs: bool, branch: str | None,
                  session: str | None):
    """Run a regression test from pm/qa/regression/ in an isolated QA run.

    The run gets its own QA workdir, created the same way as a QA
    scenario's: a fresh clone of the project (base branch unless --branch)
    and an empty scratch dir, plus copies of the project's setup recipes
    (pm/qa/instructions/) and capture recipes (pm/qa/artifacts/).  With
    container mode enabled the session runs in a QA container, and an
    unusable runtime stops the run; it never falls back to the host.  The
    test drives a disposable project it creates in the scratch dir, never
    your pm project or a running pm session.  Captures land under
    ~/.pm/sessions/<tag>/captures/regression/<test-id>/<run-id>/.

    Runs in the foreground.  The TUI and `pm qa launch regression:<id>` run
    this same command in a pane.  Use `pm qa list` to see available tests.
    """
    import secrets
    import time
    from pm_core import qa_instructions, qa_loop, store
    from pm_core import container as container_mod
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core.cli.helpers import _resolve_repo_dir
    from pm_core.paths import (CONTAINER_CAPTURES_MOUNT, captures_dir,
                               get_session_tag)
    from pm_core.regression_prompts import (
        CONTAINER_REGISTRY_MOUNT, build_regression_test_prompt,
        registry_mounts, regression_launch_problem,
    )

    if session:
        click.echo("Note: --session is ignored; a regression run never "
                   "targets a pm session.", err=True)

    try:
        root = state_root().resolve()
    except FileNotFoundError as exc:
        click.echo(str(exc) or "No pm project found.", err=True)
        raise SystemExit(1)

    # Unknown id / empty library / container mode enabled with an unusable
    # runtime: stop before any workdir, clone or container exists.
    problem = regression_launch_problem(root, test_id)
    if problem:
        click.echo(problem, err=True)
        raise SystemExit(1)
    item = qa_instructions.get_instruction(root, test_id, category="regression")
    title = item.get("title", test_id)
    use_containers = container_mod.is_container_mode_enabled()

    data = store.load(root)
    base_branch = (branch or data.get("project", {}).get("base_branch")
                   or "master")
    # The code repo the run clones: the parent of an in-repo pm/ dir, or,
    # for a standalone pm repo (`pm init --dir`, which holds only pm state),
    # the local checkout project.repo names.
    repo_root = _resolve_repo_dir(root, data)
    session_tag = (qa_loop.own_session_tag()
                   or get_session_tag(start_path=repo_root))
    captures_base = captures_dir("regression", session_tag=session_tag)
    if captures_base is None:
        click.echo("Cannot resolve a captures directory for this run: no "
                   "session tag (not inside a git repo?).", err=True)
        raise SystemExit(1)

    run_id = (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
              + f"-{secrets.token_hex(2)}")
    qa_workdir = qa_loop.create_qa_workdir(f"regression-{test_id}", run_id)
    try:
        clone_path, scratch_path = qa_loop.create_scenario_workdir(
            qa_workdir, 0, repo_root=repo_root,
            pr_id=f"regression-{test_id}", loop_id=run_id,
            branch=base_branch,
        )
        # A regression run never pushes; fetches still reach the upstream.
        subprocess.run(["git", "-C", str(clone_path), "remote", "set-url",
                        "--push", "origin", _REGRESSION_NO_PUSH_URL],
                       check=True, capture_output=True, text=True)
    except Exception as exc:
        # Nothing ran: drop this run's own, just-created workdir.
        _discard_unlaunched_run(qa_workdir)
        detail = (getattr(exc, "stderr", "") or "").strip()
        click.echo(f"Could not clone '{base_branch}' for the regression run: "
                   f"{exc}" + (f"\n{detail}" if detail else ""), err=True)
        raise SystemExit(1)

    rev = subprocess.run(["git", "-C", str(clone_path), "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    sha = rev.stdout.strip() if rev.returncode == 0 else ""
    target = (f"`{base_branch}` (commit `{sha[:12]}`)" if sha
              else f"`{base_branch}`")

    # Created once the session is ready to start (below), so a run that
    # never launched leaves nothing in the evidence store.
    run_captures = captures_base / test_id / run_id
    # The container's captures key: only this run's directory is mounted
    # (at /pm-captures, marked with this key), never captures/regression/
    # as a whole.  A session cannot touch other tests' or earlier runs'
    # evidence, and a nested regression run started inside the container
    # (a test of `pm qa regression` itself) gets no mount for its own
    # captures, since its key differs (fail closed, paths.captures_dir).
    captures_key = f"regression/{test_id}/{run_id}"
    if use_containers:
        wd_in = container_mod._CONTAINER_WORKDIR
        scratch_in = container_mod._CONTAINER_SCRATCH
        captures_in = CONTAINER_CAPTURES_MOUNT
        registry_in = CONTAINER_REGISTRY_MOUNT
    else:
        wd_in, scratch_in = str(clone_path), str(scratch_path)
        captures_in = str(run_captures)
        registry_in = str(root)

    env: dict[str, str] = {}
    cname = None
    try:
        # Inside the guarded block: a failed recipe copy is a run that
        # never launched, so it is cleaned up like one (below).
        prompt = build_regression_test_prompt(
            title=title,
            body=item.get("body", ""),
            workdir=wd_in,
            scratch_dir=scratch_in,
            target=target,
            in_container=use_containers,
            setup_recipes=_install_regression_recipes(
                qa_instructions.list_instructions(root), scratch_path,
                "qa-instructions", scratch_in),
            capture_recipes=_install_regression_recipes(
                qa_instructions.list_artifacts(root), scratch_path,
                "qa-artifacts", scratch_in),
            captures_dir=captures_in,
            file_findings=file_prs,
            registry=registry_in if file_prs else None,
            # Host mode keeps it (and drops TMUX): name it so the
            # session's plain tmux commands reach the same server as pm.
            tmux_socket=(None if use_containers
                         else os.environ.get("PM_TMUX_SOCKET")),
        )
        if use_containers:
            cname = container_mod.qa_container_name(
                f"regression-{test_id}", run_id, 0, session_tag=session_tag)
            # This run's captures dir mounts at /pm-captures (creating it
            # on the host).  No push proxy: a regression run never pushes.
            # The project's pm dir is mounted only when findings are filed:
            # read-write so filed PRs reach the real registry, with every
            # other entry in it overlaid read-only (registry_mounts).  No
            # other part of the project is mounted.
            reg_rw, reg_ro = (registry_mounts(root) if file_prs
                              else (None, None))
            container_mod.create_qa_container(
                name=cname,
                config=container_mod.load_container_config(),
                workdir=clone_path,
                scratch_path=scratch_path,
                allowed_push_branch=None,
                session_tag=session_tag,
                pr_id=captures_key,
                extra_rw_mounts=reg_rw,
                extra_ro_mounts=reg_ro or None,
            )
            claude_cmd = build_claude_shell_cmd(
                prompt=prompt, cwd=wd_in, write_dir=str(clone_path),
                session_type="qa_regression", session_tag=session_tag,
                container=True, env_out=env,
            )
            shell_cmd = container_mod.build_exec_cmd(
                cname, claude_cmd, cleanup=True, env=env)
            run_cwd = str(qa_workdir)
        else:
            shell_cmd = build_claude_shell_cmd(
                prompt=prompt, cwd=wd_in, session_type="qa_regression",
                session_tag=session_tag, env_out=env,
            )
            run_cwd = str(clone_path)
        # pm run from the clone uses this pm_core (as in QA scenarios).  Set
        # last, once the session is ready: it writes under ~/.pm/sessions/,
        # which a run that never launched must not leave behind.
        qa_loop._setup_clone_override(clone_path)
    except Exception as exc:
        # Container mode is an execution boundary: report the failure rather
        # than continuing on the host.  Release only this run's container.
        if cname:
            try:
                container_mod.remove_container(cname)
            except Exception:
                pass
            click.echo(
                "Container mode is enabled, but the regression container "
                f"could not be set up: {exc}\n\n"
                "No session was launched on the host.\n\n"
                + container_mod.container_retry_remedy(
                    "fix the container runtime/image (check 'pm container "
                    "status'), then retry"),
                err=True,
            )
        else:
            click.echo(f"Could not build the regression session: {exc}",
                       err=True)
        _discard_unlaunched_run(qa_workdir, run_captures)
        raise SystemExit(1)

    # In container mode this is the directory mounted at /pm-captures.
    run_captures.mkdir(parents=True, exist_ok=True)
    (run_captures / "prompt.md").write_text(prompt)

    click.echo(f"Running regression: {title}")
    click.echo(f"  Target:   {target.replace('`', '')} (clone {clone_path})")
    click.echo("  Runs in:  " + (f"container {cname}" if use_containers
                                  else "host (container mode is off)"))
    click.echo(f"  Captures: {run_captures}")
    click.echo("-" * 60)

    exec_env = {k: v for k, v in os.environ.items()
                if k not in _REGRESSION_SCRUBBED_ENV}
    exec_env.update(env)
    os.chdir(run_cwd)
    os.execvpe("bash", ["bash", "-c", shell_cmd], exec_env)


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

    loop_id = qa_loop.instruction_run_loop_id(pr_id)
    qa_workdir = qa_loop.create_qa_workdir(pr_id, loop_id)
    # The loop id is fixed, so an earlier run's start record is still here.
    # It names that run's process, long gone: auto-start would take this
    # run for nobody's and start full QA over it (S111).  This run writes
    # its own.
    (qa_workdir / "qa_run.json").unlink(missing_ok=True)

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
    # The resume snapshot is for a TUI to finish a run whose driver died.
    # Left behind, the TUI's resume scan recovered this one instruction's
    # verdict as the PR's QA result once this process exited, and handed
    # the PR to sign-off without full QA (S111).
    if state.latest_verdict:
        qa_loop.clear_resume_file(qa_workdir)

    verdict = state.latest_verdict or "UNKNOWN"
    detail = qa_loop.qa_error_detail(state)
    if detail:
        # A fail-closed launch (e.g. container mode enabled but its runtime
        # unusable) records the cause and the retry remedy in the run's
        # error; ``on_update`` above only prints the single-line progress
        # entry, which is not enough to act on.
        click.echo("", err=True)
        click.echo(detail, err=True)
    click.echo(f"\nResult: {verdict}")
    if verdict == "ERROR":
        # ERROR means the run never produced a result (e.g. a fail-closed
        # container launch), so report the failure in the exit code too:
        # a scripted caller must not read "Result: ERROR" as success.  A
        # scenario verdict (PASS / NEEDS_WORK / INPUT_REQUIRED) is a
        # completed run and keeps exiting 0.
        raise SystemExit(1)


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
    from pm_core.container import (
        is_container_mode_enabled, container_preflight_error,
        container_unavailable_message,
    )
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

    # Container mode is an execution boundary.  Resolve it before creating
    # any workdir/clone so an unusable runtime aborts here instead of
    # silently running the debug instruction on the host.
    use_containers = is_container_mode_enabled()
    if use_containers:
        _runtime_problem = container_preflight_error()
        if _runtime_problem:
            click.echo(container_unavailable_message(_runtime_problem),
                       err=True)
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

    env: dict[str, str] = {}
    if use_containers:
        config = container_mod.load_container_config()
        session_tag = session.removeprefix("pm-") if session else None
        cname = f"{container_mod.CONTAINER_PREFIX}qa-debug-{instruction_id}-{debug_id}"

        try:
            container_mod.create_qa_container(
                name=cname,
                config=config,
                workdir=clone_path,
                scratch_path=scratch_path,
                allowed_push_branch=base_branch,
                session_tag=session_tag,
            )
        except Exception as exc:
            # Container mode is an execution boundary: report the
            # infrastructure failure instead of dropping into the host
            # branch (or leaking a traceback) below.  Broader than
            # ContainerError on purpose: a runtime that dies between the
            # preflight above and this create (e.g. the binary disappearing)
            # surfaces as OSError, and the user should still get the cause
            # and the remedy rather than a traceback.  Release only this
            # attempt's own container (a setup timeout can leave a
            # half-configured one behind); nothing else is touched.
            try:
                container_mod.remove_container(cname)
            except Exception:
                pass
            click.echo(
                "Container mode is enabled, but the QA debug container "
                f"could not be created: {exc}\n\n"
                "No session was launched on the host.\n\n"
                + container_mod.container_retry_remedy(
                    "fix the container runtime/image (check 'pm container "
                    "status'), then retry"),
                err=True,
            )
            raise SystemExit(1)

        claude_cmd = build_claude_shell_cmd(
            prompt=prompt,
            cwd=container_mod._CONTAINER_WORKDIR,
            write_dir=str(clone_path),
            session_type="qa_author",
            env_out=env,
        )
        shell_cmd = container_mod.build_exec_cmd(
            cname, claude_cmd, cleanup=True, env=env)
        run_cwd = str(qa_workdir)
    else:
        shell_cmd = build_claude_shell_cmd(
            prompt=prompt,
            cwd=str(clone_path),
            session_type="qa_author",
            env_out=env,
        )
        run_cwd = str(clone_path)

    if foreground:
        click.echo(f"Debug: {item['title']}")
        click.echo(f"  Workdir: {qa_workdir}")
        os.chdir(run_cwd)
        os.execvpe("bash", ["bash", "-c", shell_cmd], {**os.environ, **env})
    else:
        window_problem = ""
        try:
            pane = tmux_mod.new_window_get_pane(
                session, window_name, shell_cmd,
                cwd=run_cwd, switch=False, env=env,
            )
        except Exception as exc:
            pane = None
            window_problem = str(exc) or exc.__class__.__name__
        if not pane:
            # Nothing runs in the workdir/clone (or in the container created
            # for it above): reporting "Launched" here would claim a session
            # that does not exist and leak the container.  Release only this
            # attempt's own container, never anything else.
            detail = f": {window_problem}" if window_problem else ""
            if use_containers:
                try:
                    container_mod.remove_container(cname)
                except Exception:
                    pass
            click.echo(
                "Could not create the QA debug window in tmux session "
                f"'{session}'{detail}. No debug session was launched"
                + (", and the container created for it was released."
                   if use_containers else "."),
                err=True,
            )
            click.echo(
                "Remedy: make sure the pm session is running "
                "('pm tui view'), then retry.", err=True)
            raise SystemExit(1)
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
    """Launch a QA instruction or regression test in a pane.

    Headless equivalent of the TUI's ``launch_qa_item`` — meant for
    watchers that need to spawn QA sessions without going through the TUI
    process.  An instruction gets a Claude pane aimed at this session; a
    regression test's pane runs ``pm qa regression <id> --file-prs``.

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
    if category == "regression":
        # The pane runs `pm qa regression`, the one regression launcher: an
        # isolated QA workdir (a QA container when container mode is
        # enabled) and a disposable test project, never this session.
        # Report what would stop it here (empty library, unknown id,
        # unusable container runtime), so the caller (the discovery
        # supervisor) sees the failure rather than a pane that exits at once.
        from pm_core.regression_prompts import regression_launch_problem
        problem = regression_launch_problem(root, qa_id)
        if problem:
            click.echo(problem, err=True)
            raise SystemExit(1)
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

    env: dict[str, str] = {}
    if category == "regression":
        # No session context: the pane runs the isolated launcher, whose
        # prompt never names this (or any) pm session.
        from pm_core.regression_prompts import regression_launch_cmd
        cmd = regression_launch_cmd(root, qa_id, file_findings=True)
    else:
        sess_label = os.environ.get("PM_SESSION") or session
        title = item.get("title", qa_id)
        body = item.get("body", "")
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
        cmd = build_claude_shell_cmd(prompt=full_prompt,
                                     session_type="qa_author", env_out=env)
    cwd = str(root.parent) if root.name == "pm" else str(root)

    if target_window:
        win = tmux_mod.find_window_by_name(session, target_window)
        if not win:
            click.echo(f"Target window not found: {target_window}", err=True)
            raise SystemExit(1)
        pane_id = tmux_mod.split_pane(session, "h", cmd, window=win["id"],
                                      env=env)
        click.echo(f"Launched {item_id} in window '{target_window}' (pane {pane_id})")
    else:
        window_name = f"qa-{qa_id}"
        tmux_mod.new_window(session, window_name, cmd, cwd=cwd, switch=False,
                            env=env)
        click.echo(f"Launched {item_id} in new window '{window_name}'")


@qa.command("standalone")
@click.argument("instruction_id")
def qa_standalone(instruction_id: str):
    """Run a QA instruction against the current codebase without a PR.

    Uses a generic prompt without PR-specific context.  Regression tests
    run with `pm qa regression <id>` instead, which isolates them from
    your project and pm session.
    """
    import time
    from pm_core import qa_instructions, store, prompt_gen
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core import tmux as tmux_mod

    root = state_root()

    # Find the instruction
    item = qa_instructions.get_instruction(root, instruction_id, "instructions")
    if item is None and qa_instructions.get_instruction(
            root, instruction_id, "regression") is not None:
        # This launcher runs on the host next to the live pm session, which
        # is exactly what a regression run must not do.
        click.echo(f"'{instruction_id}' is a regression test; run it with "
                   f"'pm qa regression {instruction_id}'.", err=True)
        raise SystemExit(1)
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

    env: dict[str, str] = {}
    cmd = build_claude_shell_cmd(prompt=prompt, cwd=workdir,
                                 session_type="qa_author", env_out=env)
    # Launch as tmux window if in a session, otherwise blocking
    session = tmux_mod.get_session_name() if tmux_mod.in_tmux() else None
    if session:
        window_name = f"qa-{instruction_id}"
        tmux_mod.new_window(session, window_name, cmd, cwd=workdir, env=env)
        click.echo(f"  Launched in tmux window: {window_name}")
    else:
        click.echo("  Running in foreground (no tmux session detected)")
        os.chdir(workdir)
        os.execvpe("bash", ["bash", "-c", cmd], {**os.environ, **env})


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
