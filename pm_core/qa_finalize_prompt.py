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
- PR workdir (the user's local clone): `{pr_workdir}`
- Overall QA verdict: **{overall_verdict}**

Scenarios that ran:
{scenario_lines}

## Your job

Two things, in order. Do them yourself with shell commands; report a
clear summary at the end.

### 1. Verify scenario pushes reached `origin/{branch}`

For each scenario worktree above (skip ones with no path):

- `cd <worktree>`
- `git status -s` — anything uncommitted? Any unstaged capture files
  under `pm/qa/captures/`? If so, the scenario didn't follow through;
  commit it (`qa: capture for scenario <n>`) and push.
- `git fetch origin {branch}` then
  `git log origin/{branch}..HEAD --oneline` — anything unpushed?
  Push it. If push is rejected, `git pull --rebase origin {branch}`
  and retry once. Surface persistent failures rather than masking them
  (we have a known history of push-proxy bugs; this pane is the
  safety net).

### 2. Fast-forward the PR workdir

- `cd {pr_workdir}`
- `git fetch origin {branch}`
- `git status -s` — if dirty, `git stash push -u -m "qa-finalize"`
  before merging; pop it back when done. The expectation is that the
  workdir is clean or only has changes unrelated to QA, so a stash
  round-trip is safe. If the pop conflicts (rare), leave the stash
  on the stack and report it so the user can resolve manually.
- `git merge --ff-only origin/{branch}`. If the merge isn't
  fast-forwardable (history diverged), report that and stop —
  pop the stash before exiting.

## Output

End with a structured summary, one line per check, e.g.:

```
[scenario 1] clean, up-to-date with origin/{branch}
[scenario 2] pushed 1 missing commit
[scenario 3] FAILED to push (rebase rejected) — investigate push proxy
[workdir] fast-forwarded 4 commits
```

If a stash was used: `[workdir] stashed N files, fast-forwarded, popped`.
If the stash pop conflicted: `[workdir] stashed but pop conflicted — stash left on stack, resolve manually`.
If a scenario worktree didn't exist on disk anymore: `[scenario n] worktree gone, skipped`.
"""
