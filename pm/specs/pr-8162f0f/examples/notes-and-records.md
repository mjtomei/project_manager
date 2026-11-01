# Persisted notes and records — examples

Back to [impl.md](../impl.md). Generated from the same texts as the prompt renderings, so the notes, hashes and revision ids here match [impl.md § Full prompts](../impl.md#full-prompts-for-approval) and the files under `prompts/`.

**What is real and what is assumed.** Owner *words* quoted below are the owner's recorded words (pr-8162f0f description; plan-delivery D3; the 2026-10-31 direction). Every `[confirmed]` tag and every confirmation, approval and timestamp is **assumed for illustration**: the real ones are recorded when the owner actually runs setup. `mg-3` depends on an answer the owner has not given; it is shown to illustrate a widening correction, not as a preference. Hashes are real sha256 values of the texts shown (stripped).

## 1. project-manager

### 1a. `pm/notes.txt` after setup (`mg-1`, `ws-1`)

Only the `## Owner Guidance` section is new; the existing QA note is untouched.

````text
## General

## Implementation

## Review

## QA

If you need to use the pm tool and are running in a container where it isn't availble, use ./install.sh --local from the pm repo directory.

## Merge

## Watcher

## Owner Guidance

### Merge authority
Owner review required — the whole PR waits if any change touches:
- containerization [owner] — container images, isolation, mounts, and what runs inside a container vs. on the host [confirmed]
- security [owner] — credentials and keys, auth and trust boundaries, push/proxy scope, and anything that could cause a critical incident: credential exposure; code from a container or PR workdir running on the host; rewriting or deleting shared branches; silent loss or reversion of work; corruption of project state or evidence; unreviewed code reaching the base branch; actions landing on an unrelated process or session [confirmed]
- prompts [owner] — text pm sends to agents, including session notes, and how prompts are composed or delivered [confirmed]
- how pm reads review/QA/sign-off verdicts or approvals — unclear whether this is security [inferred]
- pm/project.yaml registry entries or PR notes, plan text, or a PR's own spec/QA files, which later sessions read — unclear whether these are prompts [inferred]
May merge automatically with a heads-up:
- less impactful fixes and feature PRs [owner]
"Feature" or "bug fix" is not by itself a reason to require or bypass approval. [owner]
When unsure: wait for the owner. [confirmed]
Always hold paths: Dockerfile, install.sh, pm_core/container.py, pm_core/cli/container.py, pm_core/push_proxy.py, pm_core/workspace_trust.py, pm_core/providers.py, pm_core/prompt_gen.py, pm_core/*_prompts.py, pm_core/*_prompt.py, pm_core/prompt_bounds.py, pm_core/qa_instructions.py, pm_core/spec_gen.py, pm_core/guide.py, pm/notes.txt, pm_core/notes.py, pm_core/owner_guidance.py, pm_core/merge_authority.py [confirmed]
Heads-up: immediate [confirmed]

### Work selection
- First: security issues and bugs that could cause a critical incident, judged by worst plausible outcome rather than recurrence — credential exposure; code from a container or PR workdir running on the host; rewriting or deleting shared branches; silent loss or reversion of work; corruption of project state or evidence; unreviewed code reaching the base branch; actions landing on an unrelated process or session. [confirmed]
- Dependency edges are soft scheduling rules: follow them by default, depart when what you observe makes another order clearly better, and record why so others can reassess. [confirmed]
- Keep independent work moving while a PR waits for the owner or for human collaboration. [confirmed]
- Keep useful incidental fixes in the owning PR; size and loop counts are signals to inspect, not reasons to split. [confirmed]
- Relative importance is not authorization to start unrelated work, lift a hold or broaden merge permission. [confirmed]
````

### 1b. Revisions

| rev | part | source | authorization | effect | sha256 |
|---|---|---|---|---|---|
| mg-1 | merge | setup | owner-confirmed | initial; approved by owner → active | `e5ee32c81484` |
| ws-1 | work | setup | owner-confirmed | no approval needed | `b6c50d3b6853` |
| mg-2 | merge | feedback on pr-8efa789 | owner-confirmed | stricter → applied at once; later approved | `d86fd6ab325c` |
| mg-3 | merge | feedback on pr-f01eabb | owner-stated (conditional) | wider → inactive until approved | `a68e1a32f2d4` |

`mg-1` → `mg-2`:

````diff
--- before
+++ after
@@ -4 +4 @@
-- security [owner] — credentials and keys, auth and trust boundaries, push/proxy scope, and anything that could cause a critical incident: credential exposure; code from a container or PR workdir running on the host; rewriting or deleting shared branches; silent loss or reversion of work; corruption of project state or evidence; unreviewed code reaching the base branch; actions landing on an unrelated process or session [confirmed]
+- security [owner] — credentials and keys, auth and trust boundaries, push/proxy scope, how pm reads review/QA/sign-off verdicts or approvals, and anything that could cause a critical incident: credential exposure; code from a container or PR workdir running on the host; rewriting or deleting shared branches; silent loss or reversion of work; corruption of project state or evidence; unreviewed code reaching the base branch; actions landing on an unrelated process or session [confirmed]
@@ -6 +5,0 @@
-- how pm reads review/QA/sign-off verdicts or approvals — unclear whether this is security [inferred]
````

`mg-2` → `mg-3`:

````diff
--- before
+++ after
@@ -6 +6 @@
-- pm/project.yaml registry entries or PR notes, plan text, or a PR's own spec/QA files, which later sessions read — unclear whether these are prompts [inferred]
+- plan text under pm/plans/, which later sessions read — unclear whether this is prompts [inferred]
@@ -8,0 +9 @@
+- a PR's own files under pm/specs/<its id>/ and its own registry entry and notes in pm/project.yaml — these are its records, not prompts [owner]
````

Full `mg-3` text (the approved text in 1c):

````text
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
````

### 1c. `project.yaml` record after `mg-3` is approved

````yaml
project:
  name: project-manager
  # … existing project keys unchanged …
  owner_guidance:
    merge_authority:
      approved:
        rev: mg-3
        sha256: a68e1a32f2d424bf28f053051a40b1d2b9261e62b3464256ba5f09a7600b7f22
        approved_at: '2026-11-03T15:05:12Z'
        via: pm guidance approve
        text: |
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
      approvals:            # every approval, newest last (bounded to 20)
      - {rev: mg-1, sha256: e5ee32c814845c19…, at: '2026-11-03T14:02:40Z'}
      - {rev: mg-2, sha256: d86fd6ab325c9367…, at: '2026-11-03T14:31:07Z'}
      - {rev: mg-3, sha256: a68e1a32f2d424bf…, at: '2026-11-03T15:05:12Z'}
    revisions:              # append-only, last 20 per part (older: git history)
    - rev: mg-1
      part: merge_authority
      at: '2026-11-03T13:52:18Z'
      source: setup
      authorization: owner-confirmed
      summary: Initial merge guidance — containerization, security and prompts wait; two unclear areas wait until answered
      owner_words:
      - "any PR touching containerization, security, or prompts requires human review/approval before merge. Less impactful fixes and feature PRs may auto-merge under the owner's explicit policy, with a small heads-up. \"Feature\" or \"bug fix\" is not by itself a reason to require or bypass approval."
      session: owner_guidance:<session-id>
      previous_sha256: null
      sha256: e5ee32c814845c19dfc2f5d90b45ab85f4070686a3243cc15a380945443c248b
      previous_text: ''
    - rev: ws-1
      part: work_selection
      at: '2026-11-03T13:55:02Z'
      source: setup
      authorization: owner-confirmed
      summary: Work selection from recorded direction (plan-delivery D3; 2026-10-31 soft-dependency direction)
      owner_words: ["<the owner's confirmation in the setup conversation>"]
      session: owner_guidance:<session-id>
      previous_sha256: null
      sha256: b6c50d3b6853bf249d002de6bcf16a1b32937063fe5ef93a1bcecdf9626c4ed3
      previous_text: ''
    - rev: mg-2
      part: merge_authority
      at: '2026-11-03T14:25:31Z'
      source: feedback (pr-8efa789)
      authorization: owner-confirmed
      summary: Verdict/approval reading counts as security (narrowing)
      owner_words: ["<the owner's yes in the feedback conversation>"]
      session: owner_guidance:<session-id>
      previous_sha256: e5ee32c814845c19dfc2f5d90b45ab85f4070686a3243cc15a380945443c248b
      sha256: d86fd6ab325c936718b24b2d30a2a286d48a61821e99caf1fe40bc94fa6c447c
      previous_text: |
        ### Merge authority
        Owner review required — the whole PR waits if any change touches:
        - containerization [owner] — container images, isolation, mounts, and what runs inside a container vs. on the host [confirmed]
        - security [owner] — credentials and keys, auth and trust boundaries, push/proxy scope, and anything that could cause a critical incident: credential exposure; code from a container or PR workdir running on the host; rewriting or deleting shared branches; silent loss or reversion of work; corruption of project state or evidence; unreviewed code reaching the base branch; actions landing on an unrelated process or session [confirmed]
        - prompts [owner] — text pm sends to agents, including session notes, and how prompts are composed or delivered [confirmed]
        - how pm reads review/QA/sign-off verdicts or approvals — unclear whether this is security [inferred]
        - pm/project.yaml registry entries or PR notes, plan text, or a PR's own spec/QA files, which later sessions read — unclear whether these are prompts [inferred]
        May merge automatically with a heads-up:
        - less impactful fixes and feature PRs [owner]
        "Feature" or "bug fix" is not by itself a reason to require or bypass approval. [owner]
        When unsure: wait for the owner. [confirmed]
        Always hold paths: Dockerfile, install.sh, pm_core/container.py, pm_core/cli/container.py, pm_core/push_proxy.py, pm_core/workspace_trust.py, pm_core/providers.py, pm_core/prompt_gen.py, pm_core/*_prompts.py, pm_core/*_prompt.py, pm_core/prompt_bounds.py, pm_core/qa_instructions.py, pm_core/spec_gen.py, pm_core/guide.py, pm/notes.txt, pm_core/notes.py, pm_core/owner_guidance.py, pm_core/merge_authority.py [confirmed]
        Heads-up: immediate [confirmed]
    - rev: mg-3
      part: merge_authority
      at: '2026-11-03T14:52:44Z'
      source: feedback (pr-f01eabb)
      authorization: owner-stated
      summary: A PR's own spec files and registry entry are records, not prompts; plan text still unclear (widening — needs approval)
      owner_words: ["<conditional: the owner's answer, not on record>"]
      session: owner_guidance:<session-id>
      previous_sha256: d86fd6ab325c936718b24b2d30a2a286d48a61821e99caf1fe40bc94fa6c447c
      sha256: a68e1a32f2d424bf28f053051a40b1d2b9261e62b3464256ba5f09a7600b7f22
      previous_text: |
        <full text of mg-2, as above>
````

### 1d. CLI around approval, history, rollback and direct edits

Between saving `mg-3` and approving it:

````text
$ pm guidance show --part merge
Merge authority: ACTIVE WITH UNAPPROVED EDITS — approved mg-2; current text mg-3 is not approved
  Stricter parts of mg-3 apply now. Anything mg-3 allows that mg-2 does not stays held until you
  run `pm guidance approve`.
  Changes since approval:
    --- before
    +++ after
    @@ -6 +6 @@
    -- pm/project.yaml registry entries or PR notes, plan text, or a PR's own spec/QA files, which later sessions read — unclear whether these are prompts [inferred]
    +- plan text under pm/plans/, which later sessions read — unclear whether this is prompts [inferred]
    @@ -8,0 +9 @@
    +- a PR's own files under pm/specs/<its id>/ and its own registry entry and notes in pm/project.yaml — these are its records, not prompts [owner]

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
````

The owner approves (interactive terminal):

````text
$ pm guidance approve
Merge authority — project-manager
Approved now: mg-2 (d86fd6ab325c) · to approve: mg-3 (a68e1a32f2d4), saved 14:52 by feedback (owner-stated)

--- before
+++ after
@@ -6 +6 @@
-- pm/project.yaml registry entries or PR notes, plan text, or a PR's own spec/QA files, which later sessions read — unclear whether these are prompts [inferred]
+- plan text under pm/plans/, which later sessions read — unclear whether this is prompts [inferred]
@@ -8,0 +9 @@
+- a PR's own files under pm/specs/<its id>/ and its own registry entry and notes in pm/project.yaml — these are its records, not prompts [owner]

This lets more PRs merge without you (a hold was narrowed and a permission added).
Always-hold paths: unchanged.
Waiting PRs that will be re-checked after approval: pr-f01eabb (#182).
Approval applies only to automatic merges; review, QA, sign-off and holds still come first.

Type 'approve' to let this text authorize automatic merges: approve
Approved mg-3. pr-f01eabb will be re-assessed on the next auto-start tick.
````

An agent (or anything without a terminal) cannot:

````text
$ pm guidance approve            # run from an agent session (PM_AGENT_ROLE=owner_guidance)
pm guidance approve: only the project owner can approve merge guidance, from their own terminal or the TUI.
It cannot run inside an agent session or without an interactive terminal. Nothing was changed.
````

History:

````text
$ pm guidance history
Owner guidance history — project-manager
rev   part   when (UTC)        source                  authorization    sha256        status
mg-1  merge  2026-11-03 13:52  setup                   owner-confirmed  e5ee32c81484  approved 14:02
ws-1  work   2026-11-03 13:55  setup                   owner-confirmed  b6c50d3b6853  current
mg-2  merge  2026-11-03 14:25  feedback pr-8efa789     owner-confirmed  d86fd6ab325c  approved 14:31
mg-3  merge  2026-11-03 14:52  feedback pr-f01eabb     owner-stated     a68e1a32f2d4  approved 15:05 · current
Restore one with `pm guidance rollback <rev>`.
````

Rollback (example — not part of the main timeline):

````text
$ pm guidance rollback mg-2
Restored the text of mg-2 as mg-4 (merge authority). Approved text is still mg-3.
mg-4 is stricter than the approved text, so it applies now; run `pm guidance approve` to make it
the approved text (not required for it to take effect).
````

Direct edit kept and recorded (fixture case 2d in the feedback example):

````text
$ pm guidance show --part merge          # after the owner edited pm/notes.txt with `pm notes`
Recorded a direct edit as mg-5 (source: direct-edit; previous text kept for rollback).
Merge authority: ACTIVE WITH UNAPPROVED EDITS — approved mg-3; current text mg-5 is not approved
  Changes since approval:
    +- dependency or lockfile updates [owner]
  Stricter parts of mg-5 apply now.
````

## 2. fixture-b — a second project with different guidance

A test fixture project, not a real pm-managed project. To avoid inventing preferences, its owner statements are quoted from a published review policy: the Node.js collaborator guide ([source excerpt with hash and line numbers](sources/node-collaborator-guide-excerpt.md)). Its `pm/notes.txt` lives in its own repository; nothing is shared with project-manager.

````text
## Owner Guidance

### Merge authority
May merge automatically with a heads-up:
- focused changes that affect only documentation and/or the test suite [owner]
- changes that fix regressions [owner] — the regression fix and its tests only; anything else in the PR is judged on its own [confirmed]
Owner review required — the whole PR waits if any change:
- is backward-incompatible [owner] — e.g. removes or redefines API arguments, changes return values, adds or removes errors, alters the expected timing of an event or an API's side effects [confirmed]
- is anything not listed under "May merge automatically" [confirmed]
When unsure: wait for the owner. [confirmed]
````

sha256 `fac95c0cb390`. Where each line comes from:

| fixture-b line | Owner statement it comes from (verbatim, Node.js collaborator guide) | Locator |
|---|---|---|
| focused changes that affect only documentation and/or the test suite [owner] | "Focused changes that affect only documentation and/or the test suite" (listed as fast-trackable) | line 248, "Waiting for approvals" |
| changes that fix regressions [owner] | "Changes that fix regressions" | line 251, same section |
| is backward-incompatible [owner] — e.g. … [confirmed] | "At least two TSC voting members must approve backward-incompatible changes"; the examples list | lines 436–446, "Breaking changes" |
| is anything not listed under "May merge automatically" [confirmed] | "Before landing pull requests, allow 48 hours for input from other collaborators." (the default is to wait) | line 244 |

The two projects differ in shape, not just in areas: project-manager lets "less impactful fixes and feature PRs" merge by default and lists what waits; fixture-b lets only docs/tests and regression fixes merge and makes everything else wait.

## 3. The same kinds of change under both projects

Fixture diffs applied to each project's own fixture repository (the acceptance test "distinct policies for two projects"):

| Change (fixture diff) | project-manager (`mg-3`) | fixture-b (`fb-1`) |
|---|---|---|
| docs-only edit to `README.md` | AUTO — less impactful | AUTO — documentation only |
| new TUI/CLI display feature | AUTO — less impactful | WAITS — not listed |
| regression fix + its test, nothing else | AUTO — less impactful | AUTO — fixes a regression |
| regression fix + unrelated refactor | AUTO if the refactor is less impactful | WAITS — the refactor is judged on its own and is not listed |
| edit to a prompt template file | WAITS — prompts (and hold path) | WAITS — not listed |
| removes a public function argument | WAITS — not clearly "less impactful" → unsure | WAITS — backward-incompatible |
| test-only change | AUTO — less impactful | AUTO — test suite only |
| change to the project's guidance section | WAITS — policy edit (floor) | WAITS — policy edit (floor) |

A guidance change in one fixture project leaves the other's recorded decisions and `pm guidance show` output byte-identical (asserted).
