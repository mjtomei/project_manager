# Spec: Review and QA agents file bugs for out-of-scope issues via `pm pr add`

## Requirements
1. Review prompt (`generate_review_prompt` in `pm_core/prompt_gen.py`) — instruct
   the reviewing agent that when it spots a bug, gap, or issue that is
   **out of scope for this PR**, it must file it with
   `pm pr add '<title>' --plan bugs --description '<details>'` instead of
   downgrading the PR's verdict for it.
2. Review-loop addendum (`_review_loop_addendum` in `pm_core/prompt_gen.py`) —
   reinforce the same: out-of-scope bugs do not block PASS, but must be filed.
3. QA planner prompt (`generate_qa_planner_prompt`) — when the planner notices
   pre-existing bugs while reading the diff, file via `pm pr add ... --plan bugs`.
4. QA scenario child prompt (`generate_qa_child_prompt`) — when a scenario hits
   a bug *not caused by this PR's changes*, file it with `pm pr add` and
   continue. The scenario verdict (PASS/NEEDS_WORK/INPUT_REQUIRED) reflects
   only this PR's behavior.
5. QA interactive prompt (`generate_qa_interactive_prompt`) — same guidance for
   Scenario 0.
6. Standalone QA prompt (`generate_standalone_qa_prompt`) — for completeness:
   if running against master and a side-issue is noticed, file via `pm pr add`.

## Implicit Requirements
- The `bugs` plan ID exists in `pm/project.yaml` (verified — `id: bugs`,
  `file: bugs.md`).
- Agents are launched with sufficient tool access to run shell commands
  (`pm pr add ...`). The pm flows typically run agents with
  `--dangerously-skip-permissions` (`_skip_permissions()` in
  `pm_core/claude_launcher.py`). No `allowed_tools` plumbing change required:
  these agents already run `git diff`, `pm pr list`, etc. via Bash — adding
  `pm pr add` is the same shape.
- Bug filing is a side effect, not a verdict change. Verdicts must still
  reflect the PR's own scope.

## Ambiguities (resolved)
- *Should the agent always file separately, or is one bullet in the review
  output enough?* → Always file via `pm pr add`. The review output is
  ephemeral; the bug plan is the durable record.
- *What goes in the title/description?* → Title is a short imperative
  ("Fix X in Y"); description includes location, repro, and why it's
  out-of-scope for the current PR. Phrased as guidance, not a rigid schema.
- *Use `--plan bugs` exactly?* → Yes. The plan ID is literally `bugs`.

## Edge Cases
- A judgment call between "in scope" and "out of scope" — guidance: if the
  problem exists on the base branch (or is unrelated to this PR's diff),
  it's out of scope.
- The `bugs` plan may not exist in some repos. We hard-code `--plan bugs`;
  if it doesn't exist, the command will fail with a friendly error and the
  agent can skip without affecting the verdict. Acceptable.
- Avoid duplicate filings — agents are told to skim `pm pr list` for an
  existing matching bug entry first.
