"""Prompts for the regression test runner (`pm qa regression`).

Mirrors `bug_fix_prompts.py` / `qa_authoring.py` — pulls the prompt
assembly out of the CLI surface so it lives next to the other session
prompts instead of inline in `pm_core/cli/tui.py`.
"""


_FILING_ADDENDUM = """

## Filing Findings

For each issue you observed, file a PR — don't fix it here.

- **Bug**: `pm pr add '<title>' --plan bugs --description '<location, repro, expected vs actual>'`
- **Improvement**: `pm pr add '<title>' --plan improvements --description '<what you noticed and why>'`

If a capture from this run demonstrates the finding, point at its
path in the description.

Skim `pm pr list --plan bugs` / `--plan improvements` first. If a PR
for the same issue exists, append a note instead of filing a
duplicate: `pm pr note add <pr-id> '<short observation>; capture: <path>'`.

Filing is independent of your verdict for the test.
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

Captures live outside the project repo, under
`~/.pm/sessions/<session-tag>/captures/regression/<test-id>/<timestamp>/`
on the host. `pm qa captures-path` only knows PR ids — regression
captures don't have one, so resolve the path yourself (the session-tag
prefix is shared with any PR's captures dir if you need to derive it).
Captures are durable on the host but **not** committed to git — don't
`git add` them.

## QA Regression Test: {title}

{body}
{addendum}
"""
