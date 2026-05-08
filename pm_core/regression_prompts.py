"""Prompts for the regression test runner (`pm tui test`).

Mirrors `bug_fix_prompts.py` / `qa_authoring.py` — pulls the prompt
assembly out of the CLI surface so it lives next to the other session
prompts instead of inline in `pm_core/cli/tui.py`.
"""


_BUG_FILING_ADDENDUM = """

## Bug Filing

After completing all test scenarios, file a PR for each bug or
unexpected behavior you observed (do **not** attempt to fix them
here — fixes belong in a separate bug-fix PR session):

1. Create a PR with `pm pr add --title "<short bug title>" --description "<what's wrong; concrete reproduction steps>" --plan bugs`.
2. The description must include concrete reproduction steps that a
   future session can follow. If a capture from this run demonstrates
   the bug, add a pointer to it (path under
   `pm/qa/captures/regression/...`) in the description.
3. Use clear, actionable titles.
4. After filing, list the new PRs in your report under a "Filed PRs"
   section.
5. If no bugs were found, note "No bugs found, no PRs filed".
"""


def build_regression_test_prompt(
    *,
    session: str,
    pane_id: str | None,
    title: str,
    body: str,
    file_bugs: bool,
) -> str:
    """Assemble the full prompt the regression runner hands to Claude.

    Components, in order:
      - Session Context (which tmux session/pane to drive and how)
      - Captures (where to save artifacts and to commit them)
      - The test body itself (a free-form Claude prompt)
      - Optional Bug Filing addendum when ``file_bugs`` is set
    """
    pane_line = f"\nThe TUI pane ID is: {pane_id}" if pane_id else ""
    bug_addendum = _BUG_FILING_ADDENDUM if file_bugs else ""
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
{bug_addendum}
"""
