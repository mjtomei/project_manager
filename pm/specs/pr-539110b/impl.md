# Spec: Review and QA agents file bugs for out-of-scope issues via `pm pr add`

## Requirements
1. Review prompt (`generate_review_prompt` in `pm_core/prompt_gen.py`) — instruct
   the reviewing agent that when it spots an out-of-scope bug it should either
   (a) fix it inline and record the fix with
   `pm pr note add <pr-id> '<summary>'`, or (b) file a separate bug PR with
   `pm pr add '<title>' --plan bugs --description '<details>'`. Skim
   `pm pr list --plan bugs` first to avoid duplicates.
2. Review-loop runs share #1's guidance: the block is appended to the base
   review prompt, so review-loop iterations inherit it without a separate
   addendum.
3. QA planner prompt (`generate_qa_planner_prompt`) — same guidance when the
   planner notices pre-existing bugs while reading the diff.
4. QA scenario child prompt (`generate_qa_child_prompt`) — same guidance when a
   scenario hits a bug *not caused by this PR's changes*. The scenario verdict
   (PASS/NEEDS_WORK/INPUT_REQUIRED) reflects only this PR's behavior.
5. ~~QA interactive prompt (`generate_qa_interactive_prompt`)~~ — intentionally
   omitted. Scenario 0 is an interactive session where the user is present and
   no verdict is produced; the user can file bugs directly without prompt
   guidance.
6. Standalone QA prompt (`generate_standalone_qa_prompt`) — same guidance for
   side-issues noticed while running against master.
7. `pm pr list --plan <plan-id>` filter — added to support the
   "skim for duplicates" step. Use `_standalone` to filter PRs with no plan.

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
