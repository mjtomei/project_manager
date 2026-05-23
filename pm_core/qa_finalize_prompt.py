"""Prompt builder for the post-QA finalize pane.

When a QA loop completes, a finalize pane is spawned in the main QA
window. It runs a short Claude session whose job is:

- Confirm every scenario worktree is clean and pushed (belt-and-
  suspenders against push-proxy issues we've hit before).
- Fast-forward the user's local PR workdir to ``origin/<branch>`` so
  captures and any ``qa:`` fixes land in the workdir without manual
  ``git pull``.

Outputs a short structured report so the user sees what happened.
"""


def build_qa_finalize_prompt(
    *,
    pr_id: str,
    pr_title: str,
    branch: str,
    pr_workdir: str,
    scenario_worktrees: list[tuple[int, str | None, str | None]],
    overall_verdict: str,
) -> str:
    """Build the finalize pane's Claude prompt.

    *scenario_worktrees* is a list of ``(scenario_index, verdict,
    worktree_path)`` tuples for each scenario that ran. Either field
    can be ``None``.
    """
    if scenario_worktrees:
        scenario_lines = "\n".join(
            f"- Scenario {idx}: verdict={verdict or '?'}, worktree={path or '(none)'}"
            for idx, verdict, path in scenario_worktrees
        )
    else:
        scenario_lines = "- (no scenarios ran)"

    return f"""You are the post-QA finalize check for PR {pr_id} ({pr_title!r}).

## Context

- PR branch: `{branch}`
- PR workdir (the user's local clone of the PR branch): `{pr_workdir}`
- Overall QA verdict: **{overall_verdict}**

Scenarios that ran:
{scenario_lines}

## Goals

1. **Every scenario worktree's commits are on `origin/{branch}`.**
   Scenarios were instructed to push their captures and any `qa:`
   fixes via the push proxy. If a worktree has uncommitted captures or 
   unpushed commits, push them.

2. **The PR workdir is up to date with `origin/{branch}`.** Pull from origin
   and perform a merge if required. Block on any conflicts you aren't
   comfortable resolving yourself.


## Output

End with a short, structured summary — one line per scenario plus
one line for the workdir. Clear enough that a reader can see at a
glance whether everything landed and whether anything needs the
user's attention.

After the summary, on its own line, emit exactly one of:

- `FINALIZE_DONE` — both goals reached (or you reached them with a
  reasonable workaround).
- `FINALIZE_BLOCKED` — something prevented you from completing
  (persistent push failure, diverged history, etc.). 
"""
