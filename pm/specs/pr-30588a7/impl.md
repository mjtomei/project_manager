# Spec: Bug fix flow — reproduce with test, fix, verify

## Requirements

1. **Bug-PR detection** — Add a helper (e.g. `_is_bug_pr(pr)`) in
   `pm_core/prompt_gen.py` that returns True when the PR's `plan` field equals
   `"bugs"` OR the PR's `type` field equals `"bug"`. The helper centralizes the
   rule so impl/review/QA prompts stay in sync.

2. **Implementation prompt — bug-fix flow** — `generate_prompt` in
   `pm_core/prompt_gen.py` injects a "Bug Fix Flow" section when
   `_is_bug_pr(pr)` is True. The section enforces a reproduce → fix → verify →
   reconcile sequence:
     - **Reproduce**: write or identify a failing test demonstrating the bug.
       Prefer a Claude-guided integration test using the FakeClaudeSession
       harness when the bug involves Claude session behavior; otherwise a
       plain unit/integration test that fails for the right reason.
     - **Fix**: implement the smallest change that addresses the root cause.
     - **Verify**: re-run the test (and any related suite) to confirm the
       reproduction passes and nothing else regressed.
     - **Reconcile** (verification-only, at session end): scan PR notes on
       this PR for cross-references the discovery supervisor (`pr-271cb3a`)
       wrote linking overlapping bugs. For each linked bug, confirm whether
       it still reproduces; if it's also resolved, append a PR note marking
       the link **confirmed-overlap** (`pm pr note add <pr-id> 'confirmed-overlap: <other-pr-id>'`).
       If the agent independently noticed an overlap not in the supervisor's
       links, append a **noticed-overlap** pointer note.
       The block explicitly clarifies that this is a backstop — primary dedup
       happens file-time in the supervisor.

3. **Review prompt — reproduction-test gate** — `generate_review_prompt`
   adds a bug-specific check when `_is_bug_pr(pr)` is True: the reviewer must
   confirm a reproduction test exists in the diff (or, if the bug is
   genuinely untestable, that the PR explains why). Missing reproduction
   without justification is a **NEEDS_WORK**. The review-loop addendum is
   built on top of this block, so loop iterations inherit the gate.

4. **QA planner awareness** — `generate_qa_planner_prompt` notes when this
   PR is a bug fix and instructs the planner to include at least one
   scenario that asserts the original bug no longer reproduces (preferably
   tied to the reproduction test from the impl).

5. **QA scenario child awareness** — `generate_qa_child_prompt` references
   the bug-fix nature so the scenario agent knows the focus may be a
   regression check. No verdict-shape change.

## Implicit Requirements

- `_is_bug_pr` reads from the PR dict only — no project.yaml or store calls
  inside the helper, keeping it cheap and side-effect-free.
- The PR field `type` is **not yet a defined schema field**, but the helper
  reads it tolerantly (`pr.get("type") == "bug"`) so a future schema change
  needs no further code changes here. Today only `plan == "bugs"` triggers
  the flow.
- The reconcile block uses `pm pr note add`, an existing CLI subcommand
  (used elsewhere in the same module — see `_OUT_OF_SCOPE_BUGS_BLOCK`).
- The review prompt's reproduction-test gate is purely guidance text; no
  parser change. Reviewers continue to emit PASS/NEEDS_WORK/INPUT_REQUIRED.

## Ambiguities (resolved)

- *Where does the supervisor record cross-references?* → Per
  `plan-regression.md`, the supervisor (`pr-271cb3a`) hasn't been
  implemented yet, but the design states it owns "file-time dedup against
  open PRs and work-log". The most natural surface available today is PR
  notes on the bug PR. The reconcile prompt instructs the agent to scan
  PR notes for cross-references, which works whether the supervisor uses
  `pm pr note add` or a future structured field — the agent reads what's
  visible.
- *Should the impl prompt hard-require a Claude-guided test?* → No.
  Many bugs are not Claude-related. Phrase as "preferably" so the agent
  uses FakeClaudeSession when relevant and a plain test otherwise.
- *Should the reconcile run be skippable if the supervisor hasn't filed
  any cross-references?* → Yes. The block tells the agent to do nothing
  more than note "no cross-references found" if the PR has none.
- *Add a `type` field now?* → No. The task says "or a new type=bug field"
  as a forward-looking option. Reading `pr.get("type")` tolerantly is
  enough; introducing the schema field is out of scope for this PR.

## Edge Cases

- A bug PR with no notes and no supervisor cross-references — reconcile
  step is a no-op; the agent appends nothing.
- The reproduction test cannot be written (e.g. visual regression in a
  TUI) — the prompt allows the agent to substitute a manual repro
  description in PR notes plus a regression instruction file. Reviewer
  treats that as an acceptable substitute.
- Bug fixes that touch shared infra and cause sibling bug PRs to no longer
  reproduce — captured by the reconcile step's confirmed-overlap note,
  which downstream tooling (or a human) can use to close those PRs.
- The `bugs` plan name is hard-coded. Same precedent as `pr-539110b`'s
  `--plan bugs`. Acceptable.
- Non-bug PRs are unaffected — the bug-fix block is gated on
  `_is_bug_pr`. All existing prompts render unchanged for feature PRs.
