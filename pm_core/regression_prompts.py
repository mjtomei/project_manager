"""Prompts for the regression test runner (`pm qa regression`).

Mirrors `bug_fix_prompts.py` / `qa_authoring.py` — pulls the prompt
assembly out of the CLI surface so it lives next to the other session
prompts instead of inline in `pm_core/cli/tui.py`.
"""


_FILING_ADDENDUM = """

## Filing Findings

After completing all test scenarios, file a PR for each issue you
observed (do **not** attempt to fix them here — fixes belong in a
separate PR session):

- **Bug** (failing assertion, incorrect behavior, regression):
  ```
  pm pr add '<short imperative title>' --plan bugs \\
    --description '<location, repro, expected vs actual>'
  ```
- **Improvement** (UX/quality issue surfaced incidentally — not a bug,
  but something that would make the product better):
  ```
  pm pr add '<short imperative title>' --plan improvements \\
    --description '<what you noticed and why it matters>'
  ```

If a capture from this run under `pm/qa/captures/regression/...`
demonstrates the finding, point at the path in the description —
this applies to both bug and improvement filings.

Skim `pm pr list --plan bugs` (or `--plan improvements`) before
filing to avoid duplicates. After filing, list the new PRs in your
report under a "Filed PRs" section. If nothing was found, note "No
findings filed". Filing is a side effect — your verdict for this
regression test must still reflect only the test's own pass/fail
state.
"""


def build_regression_test_prompt(
    *,
    session: str,
    pane_id: str | None,
    title: str,
    body: str,
    file_findings: bool,
) -> str:
    """Assemble the full prompt the regression runner hands to Claude.

    Components, in order:
      - Session Context (which tmux session/pane to drive and how)
      - Captures (where to save artifacts and to commit them)
      - The test body itself (a free-form Claude prompt)
      - Optional Filing Findings addendum when ``file_findings`` is set
        (covers both bugs and improvements)
    """
    pane_line = f"\nThe TUI pane ID is: {pane_id}" if pane_id else ""
    addendum = _FILING_ADDENDUM if file_findings else ""
    return f"""\
## Session Context

You are testing against tmux session: {session}{pane_line}

To interact with this session, use commands like:
- pm tui view -s {session}
- pm tui send <keys> -s {session}
- tmux list-panes -t {session} -F "#{{pane_id}} #{{pane_width}}x#{{pane_height}} #{{pane_current_command}}"
- cat ~/.pm/pane-registry/{session}.json

## Captures

Any capture you produce should land under `pm/qa/captures/regression/<test-id>/<timestamp>/`
and be committed to git so future runs can diff against this one.

## QA Regression Test: {title}

{body}
{addendum}
"""
