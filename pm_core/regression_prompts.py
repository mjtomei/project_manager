"""Prompts and launch helpers for regression tests (`pm qa regression`).

Mirrors `bug_fix_prompts.py` / `qa_authoring.py` — pulls the prompt
assembly out of the CLI surface so it lives next to the other session
prompts instead of inline in `pm_core/cli/qa.py`.

A regression run never targets the user's own pm project or running pm
session.  `pm qa regression` prepares an isolated run the same way QA
scenarios are prepared (a fresh clone plus scratch dir, inside a QA container
when container mode is enabled) and the test drives a disposable project it
creates there with the project's setup recipes.  The TUI and
`pm qa launch regression:<id>` run that same command in a pane
(:func:`regression_launch_cmd`), so every surface produces the same run.
"""

import shlex
from pathlib import Path


# Where the project's pm state dir is mounted inside a regression container
# when findings filing is requested (``--file-prs``): the only part of the
# user's project the container can reach, so filed PRs land in the real
# registry instead of the run's disposable clone.
CONTAINER_REGISTRY_MOUNT = "/pm-project"


def _filing_addendum(registry: str) -> str:
    pm = f"pm -C {registry}"
    return f"""

## Filing Findings

For each issue you observed, file a PR — don't fix it here.

File against the project's registry at `{registry}`, always with
`-C {registry}`. A plain `pm pr add` here writes into this run's disposable
clone, and the filing is lost with it.

- **Bug**: `{pm} pr add '<title>' --plan bugs --description '<location, repro, expected vs actual>'`
- **Improvement**: `{pm} pr add '<title>' --plan improvements --description '<what you noticed and why>'`

If a capture from this run demonstrates the finding, point at its
path in the description.

Skim `{pm} pr list --plan bugs` / `--plan improvements` first. If a PR
for the same issue exists, append a note instead of filing a
duplicate: `{pm} pr note add <pr-id> '<short observation>; capture: <path>'`.

Filing is independent of your verdict for the test.
"""


def _recipe_lines(recipes: list[tuple[str, str]], empty: str) -> str:
    if not recipes:
        return f"- {empty}"
    return "\n".join(f"- `{path}`" + (f": {title}" if title else "")
                     for path, title in recipes)


def build_regression_test_prompt(
    *,
    title: str,
    body: str,
    workdir: str,
    scratch_dir: str,
    target: str,
    in_container: bool,
    setup_recipes: list[tuple[str, str]],
    capture_recipes: list[tuple[str, str]],
    captures_dir: str,
    file_findings: bool,
    registry: str | None = None,
) -> str:
    """Assemble the full prompt the regression runner hands to Claude.

    Components, in order:
      - Test Environment (the run's clone and scratch dir, and the rule that
        the target is a disposable project created there — never the user's
        project or pm session)
      - Recipes (``(agent-visible path, title)`` of each setup and capture
        recipe the runner copied into the scratch dir)
      - Captures (this run's capture directory, outside the repo)
      - The test body itself (a free-form Claude prompt)
      - Optional Filing Findings addendum when ``file_findings`` is set
        (covers both bugs and improvements); it needs *registry*, the
        agent-visible path of the project's pm state dir.

    *target* describes the clone (e.g. ``"`master` (commit `abc123`)"``); the
    paths are as the session sees them (``/workspace`` etc. in a container).
    """
    if file_findings and not registry:
        raise ValueError("file_findings requires the registry path")
    where = ("inside a pm QA container" if in_container
             else "on the host (container mode is off)")
    addendum = _filing_addendum(registry) if file_findings else ""
    setup = _recipe_lines(
        setup_recipes,
        "(none in this project's library — set the project up as the test "
        "below describes)")
    capture = _recipe_lines(
        capture_recipes,
        "(none in this project's library — record evidence as the test "
        "below describes)")
    return f"""\
## Test Environment

This regression test runs in an isolated environment created for this run,
{where}:

- **Workdir**: `{workdir}`. A fresh clone of the project at {target}.
- **Scratch dir**: `{scratch_dir}`. Create the disposable test project(s) here.

The test target is a disposable project that you create in the scratch dir
with a setup recipe, then drive and capture with the capture recipes. It is
never the user's own pm project or a pm/tmux session you did not start: run
`pm` from the disposable project, start any pm session you need from there,
pass that session's name explicitly to `pm tui` commands (`-s <session>`),
and leave every other session alone.

## Recipes

Setup recipes (create the disposable test project):
{setup}

Capture recipes (record what you drive):
{capture}

## Captures

Write this run's captures (recordings, transcripts, `manifest.md`) under:

    {captures_dir}

That directory is durable on the host and outside the project repo. Don't
`git add` captures.

## QA Regression Test: {title}

{body}
{addendum}
"""


def regression_launch_cmd(pm_root: Path, test_id: str,
                          file_findings: bool = True) -> str:
    """Shell command a pane runs to launch regression test *test_id*.

    The TUI and ``pm qa launch regression:<id>`` launch through
    ``pm qa regression`` instead of building their own prompt, so the
    isolated workdir/container setup lives in one place.  ``-C`` pins the
    project regardless of the pane's cwd.
    """
    cmd = (f"pm -C {shlex.quote(str(Path(pm_root).resolve()))} qa regression "
           f"{shlex.quote(test_id)}")
    if file_findings:
        cmd += " --file-prs"
    return cmd


def empty_library_message() -> str:
    return ("No regression tests in the library (pm/qa/regression/ is "
            "empty). Author one with 'pm qa author-regression <name>' or "
            "'pm qa add-regression <name>'.")


def regression_launch_problem(pm_root: Path, test_id: str) -> str | None:
    """Why regression test *test_id* cannot be launched, or None.

    Checked by the pane launchers before they spawn a pane, so an empty
    library, an unknown id or an unusable container runtime is reported to
    the caller instead of flashing by in a pane that exits at once.
    ``pm qa regression`` makes the same checks itself.
    """
    from pm_core import qa_instructions
    from pm_core.container import (container_preflight_error,
                                   container_unavailable_message)

    # Match against the listed library rather than probing for a file:
    # an id is a file stem in pm/qa/regression/, so a path such as
    # ``../instructions/<x>`` must not resolve to some other category's file.
    tests = qa_instructions.list_regression_tests(pm_root)
    if not tests:
        return empty_library_message()
    if test_id not in {t["id"] for t in tests}:
        return (f"Unknown regression test: {test_id}. "
                "Run 'pm qa list' to see available tests.")
    problem = container_preflight_error()
    if problem:
        return container_unavailable_message(problem)
    return None
