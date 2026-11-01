# Merge-authority assessment — rendered example

**Canonical text: [impl.md § P3](../impl.md#p3-merge-authority-assessor-new) (P3a and P3b).** Generated from the same template; rendered here as P3b for a real candidate: **#182 / pr-f01eabb** "TUI: animate spinner for PRs in QA status" — merge `cb7b147a`, base `5827560a`, head `dc400942`, merge tree `d5cc4d69` (the real merge, used as the candidate a sign-off would have approved). Guidance state: `mg-2` approved, `mg-3` saved but not approved ([notes-and-records.md](../examples/notes-and-records.md)). If anything here differs from impl.md, impl.md is the proposal.

## 1. Rendered prompt (P3b)

````text
You are the **merge-authority assessor** for PR pr-f01eabb (#182) in project "project-manager".

This PR has already passed review, QA and sign-off for the exact candidate below, and it is
on an automatic merge path. Before pm merges it without the owner, you decide one thing:
**does the owner's guidance let this candidate merge automatically, or must it wait for the
owner?** You are not judging quality or correctness, and you change nothing.

## The candidate

- PR: pr-f01eabb (#182) https://github.com/mjtomei/project_manager/pull/182
- PR HEAD:        dc400942cbd08b7d75385255455685cbe581925a
- Target:         master @ 5827560a148b16341ed550f902c3c209cb1ed932
- Candidate tree: d5cc4d697142e18318fc38788b8a866e8cdc26ec  (what merging publishes)

Changed paths, base → candidate (computed by pm; `$CAP/merge-authority/1/name-status.txt`):

```
A	pm/specs/pr-f01eabb/impl.md
A	pm/specs/pr-f01eabb/qa.md
M	pm_core/tui/qa_loop_ui.py
M	pm_core/tui/tech_tree.py
A	tests/test_tech_tree_qa_spinner.py
5 files changed, 371 insertions(+)
```

The full diff is `$CAP/merge-authority/1/candidate.diff`. Read all of it. You may also run
read-only git commands in the PR workdir, e.g.
`git diff 5827560a148b16341ed550f902c3c209cb1ed932 d5cc4d697142e18318fc38788b8a866e8cdc26ec -- <path>`
or `git show d5cc4d697142e18318fc38788b8a866e8cdc26ec:<path>`.

## Owner guidance — approved (mg-2, approved 2026-11-03 14:31 UTC)

### Merge authority
Owner review required — the whole PR waits if any change touches:
- containerization [owner] — container images, isolation, mounts, and what runs inside a container vs. on the host [confirmed]
- security [owner] — credentials and keys, auth and trust boundaries, push/proxy scope, how pm reads review/QA/sign-off verdicts or approvals, and anything that could cause a critical incident: credential exposure; code from a container or PR workdir running on the host; rewriting or deleting shared branches; silent loss or reversion of work; corruption of project state or evidence; unreviewed code reaching the base branch; actions landing on an unrelated process or session [confirmed]
- prompts [owner] — text pm sends to agents, including session notes, and how prompts are composed or delivered [confirmed]
- pm/project.yaml registry entries or PR notes, plan text, or a PR's own spec/QA files, which later sessions read — unclear whether these are prompts [inferred]
May merge automatically with a heads-up:
- less impactful fixes and feature PRs [owner]
"Feature" or "bug fix" is not by itself a reason to require or bypass approval. [owner]
When unsure: wait for the owner. [confirmed]
Always hold paths: Dockerfile, install.sh, pm_core/container.py, pm_core/cli/container.py, pm_core/push_proxy.py, pm_core/workspace_trust.py, pm_core/providers.py, pm_core/prompt_gen.py, pm_core/*_prompts.py, pm_core/*_prompt.py, pm_core/prompt_bounds.py, pm_core/qa_instructions.py, pm_core/spec_gen.py, pm_core/guide.py, pm/notes.txt, pm_core/notes.py, pm_core/owner_guidance.py, pm_core/merge_authority.py [confirmed]
Heads-up: immediate [confirmed]

## Owner guidance — saved since approval, NOT yet approved (mg-3)

The owner's current text differs from the approved text. Apply **both**: the candidate may
merge automatically only if the approved text AND this text both allow it. (An unapproved edit
can make pm more careful, never less.)

### Merge authority
Owner review required — the whole PR waits if any change touches:
- containerization [owner] — container images, isolation, mounts, and what runs inside a container vs. on the host [confirmed]
- security [owner] — credentials and keys, auth and trust boundaries, push/proxy scope, how pm reads review/QA/sign-off verdicts or approvals, and anything that could cause a critical incident: credential exposure; code from a container or PR workdir running on the host; rewriting or deleting shared branches; silent loss or reversion of work; corruption of project state or evidence; unreviewed code reaching the base branch; actions landing on an unrelated process or session [confirmed]
- prompts [owner] — text pm sends to agents, including session notes, and how prompts are composed or delivered [confirmed]
- plan text under pm/plans/, which later sessions read — unclear whether this is prompts [inferred]
May merge automatically with a heads-up:
- less impactful fixes and feature PRs [owner]
- a PR's own files under pm/specs/<its id>/ and its own registry entry and notes in pm/project.yaml — these are its records, not prompts [owner]
"Feature" or "bug fix" is not by itself a reason to require or bypass approval. [owner]
When unsure: wait for the owner. [confirmed]
Always hold paths: Dockerfile, install.sh, pm_core/container.py, pm_core/cli/container.py, pm_core/push_proxy.py, pm_core/workspace_trust.py, pm_core/providers.py, pm_core/prompt_gen.py, pm_core/*_prompts.py, pm_core/*_prompt.py, pm_core/prompt_bounds.py, pm_core/qa_instructions.py, pm_core/spec_gen.py, pm_core/guide.py, pm/notes.txt, pm_core/notes.py, pm_core/owner_guidance.py, pm_core/merge_authority.py [confirmed]
Heads-up: immediate [confirmed]

## What pm already checked

- Always-hold paths: no changed path matches (approved and current lists).
- Policy edit: the candidate does not change the Owner Guidance section of pm/notes.txt or the
  owner_guidance record in pm/project.yaml.
- Review PASS, QA PASS and a fresh SIGNOFF_MERGE are recorded for this exact candidate.
These checks are deliberately narrow. They do not mean the PR is low-impact.

## How to decide

1. Read the whole diff — code, tests, docs, specs, registry and notes edits, generated files.
   Incidental edits count as much as the main change.
2. Judge each change by what it does, not by its file name, the PR title, commit messages or
   comments in the diff that describe it. Those are claims; the code is the evidence.
   Look for effects outside obvious places, for example: a path or environment change that
   alters what a container mounts or where code runs (containerization); a change to how
   approvals, verdicts or credentials are read, stored or passed (security); a CLI, launcher
   or template change that alters what text reaches an agent or how it is delivered (prompts).
3. For each change, name the guidance line that covers it. Quote the line.
4. If any change falls under an "Owner review required" line in either text, the whole PR waits.
5. If you cannot tell whether a change falls under a hold line, or no line clearly covers it,
   list it as uncertain — the PR waits.
6. `[inferred]` hold lines count. `[inferred]` permission lines do not grant anything.
7. Decide AUTO_MERGE_ALLOWED only if every change is clearly covered by a "May merge
   automatically" line in both texts and none falls under a hold line.
8. Do not read the PR description, PR notes, sign-off report or other sessions' output for
   this decision, and do not ask anyone. Do not run commands that change files, branches,
   the registry, or PR state. Never run `pm pr merge`.

## Output

Write `$CAP/merge-authority/1/result.json`:

```json
{
  "schema": "pm.merge_authority/1",
  "pr_id": "pr-f01eabb",
  "head": "dc400942cbd08b7d75385255455685cbe581925a",
  "base_sha": "5827560a148b16341ed550f902c3c209cb1ed932",
  "candidate_tree": "d5cc4d697142e18318fc38788b8a866e8cdc26ec",
  "guidance": {"approved_rev": "mg-2", "current_rev": "mg-3"},
  "decision": "AUTO_MERGE_ALLOWED or OWNER_APPROVAL_REQUIRED",
  "rule": "the guidance line that decided it, quoted, with which text it came from",
  "changes": [{"path": "...", "covered_by": "quoted guidance line", "hold": true, "what": "one line: what this change does"}],
  "uncertain": [{"path": "...", "question": "what you could not decide"}],
  "rationale": "two or three sentences a reviewer can check against the diff",
  "impact": "one line: the user-visible effect of merging, for the owner's heads-up"
}
```

Then end your response with exactly one of these on its own line:

AUTO_MERGE_ALLOWED
OWNER_APPROVAL_REQUIRED
````

## 2. Expected results for this candidate

### Under `mg-2` approved + `mg-3` unapproved (the render above)

```json
{
  "schema": "pm.merge_authority/1",
  "pr_id": "pr-f01eabb",
  "head": "dc400942cbd08b7d75385255455685cbe581925a",
  "base_sha": "5827560a148b16341ed550f902c3c209cb1ed932",
  "candidate_tree": "d5cc4d697142e18318fc38788b8a866e8cdc26ec",
  "guidance": {"approved_rev": "mg-2", "current_rev": "mg-3"},
  "decision": "OWNER_APPROVAL_REQUIRED",
  "rule": "approved mg-2: \"pm/project.yaml registry entries or PR notes, plan text, or a PR's own spec/QA files, which later sessions read — unclear whether these are prompts [inferred]\"",
  "changes": [
    {"path": "pm_core/tui/tech_tree.py", "covered_by": "less impactful fixes and feature PRs [owner]", "hold": false, "what": "adds qa_pane_state() and shows a spinner or ⏸ on qa-status rows"},
    {"path": "pm_core/tui/qa_loop_ui.py", "covered_by": "less impactful fixes and feature PRs [owner]", "hold": false, "what": "registers QA scenario panes with the idle tracker while QA polls; unregisters them when done"},
    {"path": "tests/test_tech_tree_qa_spinner.py", "covered_by": "less impactful fixes and feature PRs [owner]", "hold": false, "what": "new tests for the QA spinner"},
    {"path": "pm/specs/pr-f01eabb/impl.md", "covered_by": "approved mg-2 [inferred] hold on a PR's own spec/QA files (current mg-3 would permit them)", "hold": true, "what": "the PR's own implementation spec"},
    {"path": "pm/specs/pr-f01eabb/qa.md", "covered_by": "same as impl.md", "hold": true, "what": "the PR's own QA spec"}
  ],
  "uncertain": [],
  "rationale": "The code changes are display-only TUI state for QA rows, plus tests. The PR also adds its own spec files, which the approved text still holds (inferred, unanswered when approved). The owner's newer text permits them but is not approved, so the two texts do not both allow the merge.",
  "impact": "QA rows in the TUI tech tree show a spinner while scenarios run and ⏸ when one waits for input."
}
```

pm records `OWNER_APPROVAL_REQUIRED`; the TUI log shows:

```
✓ pr-f01eabb signed off (SIGNOFF_MERGE @ dc400942) — waiting for owner (owner guidance mg-2: a PR's own spec/QA files [inferred]; your newer guidance mg-3 would allow it once approved) — g to merge, N for guidance
```

### After the owner runs `pm guidance approve` (`mg-3` approved)

The decision is stale (approved revision changed); pm launches attempt 2 with **P3a** (no unapproved block). Expected result (binding fields as above, `"guidance": {"approved_rev": "mg-3"}`):

```json
{
  "decision": "AUTO_MERGE_ALLOWED",
  "rule": "approved mg-3: \"less impactful fixes and feature PRs [owner]\" and \"a PR's own files under pm/specs/<its id>/ and its own registry entry and notes in pm/project.yaml — these are its records, not prompts [owner]\"",
  "uncertain": [],
  "rationale": "All code changes are display-only TUI rendering and tests; the remaining files are the PR's own spec records, which mg-3 permits. Nothing touches containers, credentials, verdict or approval reading, or prompt text.",
  "impact": "QA rows in the TUI tech tree show a spinner while scenarios run and ⏸ when one waits for input."
}
```

pm then runs `pm pr merge --unattended pr-f01eabb`; the record and heads-up are in [decisions-and-notices.md §1](../examples/decisions-and-notices.md).

## 3. pm-side validation of a result (not prompt text)

- Binding fields must equal the request; otherwise the attempt is invalid.
- `decision` must be one of the two values and match the verdict line.
- `AUTO_MERGE_ALLOWED` with any `changes[].hold == true` or a non-empty `uncertain` → recorded as `OWNER_APPROVAL_REQUIRED`, rule `assessor result inconsistent`, and logged.
- Missing or invalid file → one relaunch (attempt 2); a second failure → floor rule `assessment-unavailable`.
- `changes` is stored in `project.yaml` truncated to 20 entries with a pointer to `result.json`; `rationale` and `impact` are stored whole.
