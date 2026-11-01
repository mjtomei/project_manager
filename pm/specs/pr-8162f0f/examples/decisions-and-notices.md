# Decisions, CLI/TUI output and heads-up notices — examples

Back to [impl.md](../impl.md). Guidance revisions (`mg-1`…`mg-3`, `ws-1`, fixture-b `fb-1`) are the ones in [notes-and-records.md](notes-and-records.md); the assessor prompt is [impl.md § P3](../impl.md#p3-merge-authority-assessor-new).

**What is real and what is assumed.** Candidates are the **real merge diffs** of past PRs in this repository (merge commit, base and tree from `git`), treated as if each were waiting on an automatic path now. Classifications are the spec author's expected assessor output for those real diffs — the regression variant with the real assessor model checks them. Timestamps, approvals and attempt numbers are illustrative. Cases marked *fixture* use synthetic diffs in test repositories.

Output formats shown here (`pm guidance check`, TUI log lines, `pm autostart status` reasons, refusals) are proposals and part of what is being reviewed.

---

## 1. Low-impact change merges automatically after every check — #182 / pr-f01eabb

Preconditions on the path: review PASS, QA PASS, fresh `SIGNOFF_MERGE` bound to head `dc400942`, base `5827560a`, tree `d5cc4d69`; the PR is in an `auto_merge` target's closure; no `wait_for_merge` hold. Under `mg-2` (+ unapproved `mg-3`) it waited ([merge-assessment.md §2](../prompts/merge-assessment.md)); the owner then approved `mg-3`.

Each missing check blocks first and no assessment is launched (tests assert this): without review PASS the PR is still in review; without QA PASS it is in QA; with a stale sign-off the existing gate refuses (`recorded sign-off verdict SIGNOFF_MERGE is stale (HEAD moved since)`).

```
$ pm guidance check pr-f01eabb
pr-f01eabb (#182) "TUI: animate spinner for PRs in QA status"
  Decision:  AUTO_MERGE_ALLOWED (fresh)
  Rule:      approved mg-3: "less impactful fixes and feature PRs [owner]"; "a PR's own files under
             pm/specs/<its id>/ and its own registry entry and notes in pm/project.yaml — these are its
             records, not prompts [owner]"
  Changes:   pm_core/tui/tech_tree.py — spinner/⏸ on qa-status rows
             pm_core/tui/qa_loop_ui.py — QA scenario panes registered with the idle tracker while polling
             tests/test_tech_tree_qa_spinner.py — new tests
             pm/specs/pr-f01eabb/impl.md, qa.md — the PR's own specs
  Basis:     assessment 2 (authority-#182), guidance mg-3 (approved, current),
             candidate dc400942 + master@5827560a → tree d5cc4d69
  Rationale: All code changes are display-only TUI rendering and tests; the remaining files are the PR's
             own spec records, which mg-3 permits. Nothing touches containers, credentials, verdict or
             approval reading, or prompt text.
  Impact:    QA rows in the TUI tech tree show a spinner while scenarios run and ⏸ when one waits for input.
  Report:    ~/.pm/sessions/<tag>/captures/pr-f01eabb/report.html
  PR:        https://github.com/mjtomei/project_manager/pull/182
  Next:      auto-start will merge it (`pm pr merge --unattended pr-f01eabb`).
```

TUI log, in order:

```
15:05:40  Owner guidance mg-3 approved — re-checking 1 waiting PR (pr-f01eabb)
15:05:41  pr-f01eabb: assessing owner guidance (authority-#182, attempt 2)
15:07:58  pr-f01eabb: owner guidance allows automatic merge (mg-3: less impactful fixes and feature PRs)
15:08:03  Auto-merge: pr-f01eabb signed off, merging
15:08:41  ⓘ Heads-up — project-manager · #182 merged automatically (cb7b147a into master) · QA rows in the TUI tech tree show a spinner while scenarios run and ⏸ when one waits for input · rule: less impactful fixes and feature PRs · report: …/pr-f01eabb/report.html
```

Decision record on the PR (`project.yaml`):

```yaml
merge_authority:
  decision: AUTO_MERGE_ALLOWED
  rule: 'approved mg-3: "less impactful fixes and feature PRs [owner]"; "a PR''s own files under pm/specs/<its id>/ … [owner]"'
  changes:
  - 'pm_core/tui/tech_tree.py: spinner/⏸ on qa-status rows'
  - 'pm_core/tui/qa_loop_ui.py: QA scenario panes registered with the idle tracker while polling'
  - 'tests/test_tech_tree_qa_spinner.py: new tests'
  - 'pm/specs/pr-f01eabb/impl.md, qa.md: the PR''s own specs'
  rationale: All code changes are display-only TUI rendering and tests; the remaining files are the PR's own spec records, which mg-3 permits. Nothing touches containers, credentials, verdict or approval reading, or prompt text.
  impact: QA rows in the TUI tech tree show a spinner while scenarios run and ⏸ when one waits for input.
  basis: assessment
  bound:
    head: dc400942cbd08b7d75385255455685cbe581925a
    base_sha: 5827560a148b16341ed550f902c3c209cb1ed932
    candidate_tree: d5cc4d697142e18318fc38788b8a866e8cdc26ec
    base_branch: master
    target_repo: https://github.com/mjtomei/project_manager.git
    approved_rev: mg-3
    approved_sha256: a68e1a32f2d424bf28f053051a40b1d2b9261e62b3464256ba5f09a7600b7f22
    current_sha256: a68e1a32f2d424bf28f053051a40b1d2b9261e62b3464256ba5f09a7600b7f22
  decided_at: '2026-11-03T15:07:58Z'
  attempts: 2
  assessment: pr-f01eabb/merge-authority/2/result.json      # under the captures root
  report: pr-f01eabb/report.html
  link: https://github.com/mjtomei/project_manager/pull/182
  attempt:                                   # written by pm pr merge --unattended before publishing
    started_at: '2026-11-03T15:08:03Z'
    candidate_tree: d5cc4d697142e18318fc38788b8a866e8cdc26ec
  outcome:
    kind: auto-merged
    at: '2026-11-03T15:08:41Z'
    merge_sha: cb7b147ad9647fd8d2d421147f3cb8a6a576fbac
    base_branch: master
    detail: published and verified
  notice:
    id: mn-26c77ac5eb                         # sha1(repo_id, pr_id, merge_sha)[:10]
    state: shown
    created_at: '2026-11-03T15:08:41Z'
    shown_at: '2026-11-03T15:08:41Z'
    included_in: null                         # set by the scheduled brief (pr-2588ead)
    attempts: 0
    last_error: null
    text: 'project-manager · #182 merged automatically (cb7b147a into master) · QA rows in the TUI tech tree show a spinner while scenarios run and ⏸ when one waits for input · rule: less impactful fixes and feature PRs · report: pr-f01eabb/report.html · https://github.com/mjtomei/project_manager/pull/182'
  history:
  - {decision: OWNER_APPROVAL_REQUIRED, rule: 'approved mg-2 [inferred]: a PR''s own spec/QA files', approved_rev: mg-2, current_rev: mg-3, decided_at: '2026-11-03T14:58:10Z'}
```

```
$ pm guidance notices
Heads-ups — project-manager
mn-26c77ac5eb  2026-11-03 15:08  shown (TUI)  not yet in a brief
  #182 merged automatically (cb7b147a into master) — QA rows in the TUI tech tree show a spinner while
  scenarios run and ⏸ when one waits for input · rule: less impactful fixes and feature PRs
  report: ~/.pm/sessions/<tag>/captures/pr-f01eabb/report.html · https://github.com/mjtomei/project_manager/pull/182
```

What the scheduled brief (pr-2588ead) receives from `merge_authority.notices(data, state="pending-for-brief")` — data only; its layout is pr-2588ead's:

```json
[{"project": "project-manager", "repo_id": "828c8d0a91034cd541f443dd0aee62961e2af75a",
  "notice_id": "mn-26c77ac5eb", "pr_id": "pr-f01eabb", "display_id": "#182",
  "link": "https://github.com/mjtomei/project_manager/pull/182",
  "outcome": {"kind": "auto-merged", "merge_sha": "cb7b147ad9647fd8d2d421147f3cb8a6a576fbac", "base_branch": "master", "at": "2026-11-03T15:08:41Z"},
  "impact": "QA rows in the TUI tech tree show a spinner while scenarios run and ⏸ when one waits for input.",
  "rule": "less impactful fixes and feature PRs [owner]",
  "report": "pr-f01eabb/report.html"}]
```

After including it, the brief calls `mark_notice(root, "pr-f01eabb", "mn-26c77ac5eb", "included", brief_id=…)`; a second brief does not include it again. `waiting_for_owner(data)` gives the brief the list in §2–§7.

---

## 2. Containerization by effect, no container file changed — #264 / pr-1e9c117

Real merge `f1a3047a`. Changed: `pm/project.yaml`, `pm/specs/pr-1e9c117/impl.md`, `qa.md`, `pm_core/cli/qa.py`, `pm_core/paths.py`, `tests/test_captures_dir_mount.py`. No always-hold path matches, so the assessor runs.

```
$ pm guidance check pr-1e9c117
pr-1e9c117 (#264) "Bug: captures_dir() uses the /pm-captures mount for any PR when PM_CAPTURES_PR is unset …"
  Decision:  OWNER_APPROVAL_REQUIRED (fresh)
  Rule:      approved mg-3: "containerization [owner] — container images, isolation, mounts, and what runs
             inside a container vs. on the host [confirmed]"
  Changes:   pm_core/paths.py — changes when the container mount /pm-captures is used as the captures dir
             pm_core/cli/qa.py — passes the captures context for nested QA runs
             tests/…, pm/specs/pr-1e9c117/…, pm/project.yaml (its own entry)
  Basis:     assessment 1, guidance mg-3 (approved, current)
  Rationale: The change decides when code uses the container's /pm-captures mount versus a host path,
             i.e. how files cross the container boundary. That is containerization by effect even though
             no container module changed.
  Next:      waiting for you — merge it yourself (g / pm pr merge pr-1e9c117) or correct the guidance (N).
```

TUI: `✓ pr-1e9c117 signed off (SIGNOFF_MERGE @ <head>) — waiting for owner (owner guidance: containerization — paths.py mount selection) — g to merge, N for guidance`
`pm autostart status` reason column: `waiting for owner (owner guidance: containerization)`.

## 3. Security, deterministic — #273 / pr-294e53d

Real merge `7b3db760`. Changed: `pm/specs/pr-294e53d/impl.md`, `qa.md`, `pm_core/providers.py`, `tests/test_providers.py`. `pm_core/providers.py` matches an always-hold path, so **no assessor is launched**.

```
$ pm guidance check pr-294e53d
pr-294e53d (#273) "Bug: providers.yaml saves literal API keys …"
  Decision:  OWNER_APPROVAL_REQUIRED (fresh)
  Rule:      hold-path — pm_core/providers.py matches "Always hold paths" (mg-3)
  Basis:     floor (no assessment needed), guidance mg-3 (approved, current)
  Next:      waiting for you — merge it yourself (g / pm pr merge pr-294e53d) or correct the guidance (N).
```

## 4. Prompts, deterministic — #250 / pr-ace66e5

Real merge `211a6128`, 20 files. Always-hold matches: `pm_core/prompt_gen.py`, `pm_core/prompt_bounds.py`, `pm_core/notes.py`, `pm_core/guide.py`, `pm_core/qa_finalize_prompt.py` (`pm_core/*_prompt.py`), `pm_core/qa_instructions.py`, `pm_core/spec_gen.py`. Decision `OWNER_APPROVAL_REQUIRED`, rule `hold-path (7 paths) — prompts`, basis floor.

## 5. Mixed PR waits as a whole — #280 / pr-574e851

Real merge `903565d2`, 18 files. Most of the change is QA-loop and status code plus tests; `pm_core/container.py` and `pm_core/prompt_gen.py` match always-hold paths.

```
  Decision:  OWNER_APPROVAL_REQUIRED (fresh)
  Rule:      hold-path — pm_core/container.py (containerization), pm_core/prompt_gen.py (prompts)
  Changes:   2 of 18 changed files are in hold areas; the PR waits as a whole
  Basis:     floor
```

## 6. Security by effect — #263 / pr-c3bf868

Real merge `c42f81cf`, 19 files: new `pm_core/tui_pidfile.py`, `pm_core/cli/helpers.py`, `pm_core/tui/auto_start.py`, `pm_core/cli/autostart.py` and others; no always-hold path. Expected assessor result: `OWNER_APPROVAL_REQUIRED`, rule `security … anything that could cause a critical incident: … actions landing on an unrelated process or session`, rationale "rewrites how pm decides which TUI process receives IPC commands; a mistake sends actions to an unrelated process". The fix reduces that risk, but the guidance holds changes to the mechanism either way.

## 7. Uncertain classification — *fixture*

Fixture PR: adds a new third-party runtime dependency to `pyproject.toml` and uses it in a CLI formatter. No line covers dependency changes.

```json
{"decision": "OWNER_APPROVAL_REQUIRED",
 "rule": "When unsure: wait for the owner. [confirmed]",
 "uncertain": [{"path": "pyproject.toml", "question": "Adding a runtime dependency changes what code is installed and run; the guidance doesn't say whether that is security or a less impactful change."}],
 "rationale": "The formatter change is display-only, but the new dependency is not clearly covered by any line, so the PR waits."}
```

The feedback conversation offers to add a line for dependency changes; either answer is recorded with its provenance (the hold version applies at once, a permission waits for approval).

---

## 8. Stale decisions never authorize a different candidate

**New commit after the decision** (*fixture*): HEAD moves → the sign-off approval is stale first (existing gate); the guidance decision shows `stale (HEAD changed: dc400942 → 7a1e…)`, and nothing is assessed until sign-off approves the new HEAD.

**Base moves during publish** (*fixture*): `pm pr merge --unattended` re-fetches under the lock:

```
$ pm pr merge --unattended pr-f01eabb
Checking master of https://github.com/mjtomei/project_manager.git...
PR pr-f01eabb: master moved since sign-off (5827560a148b -> 9b02c4e1aa70). Returning to sign-off.
```

(The existing refusal; the guidance decision's binding is then stale too, and a new candidate is assessed after sign-off.)

**Guidance changes:**

```
$ pm guidance check pr-1e9c117
  Decision:  OWNER_APPROVAL_REQUIRED (stale — guidance changed: approved mg-3 → mg-4)
  Next:      will be re-checked on the next auto-start tick; a stale decision never authorizes a merge.
```

An unattended merge attempted with a stale `AUTO` decision (*fixture*, guidance edited between decision and merge):

```
$ pm pr merge --unattended pr-f01eabb
PR pr-f01eabb: the owner-guidance decision is stale (current guidance text changed since it was made:
a68e1a32f2d4 → 5c90d1b7e3f2). Not merging; it will be re-assessed.
```

## 9. Explicit `wait_for_merge` wins — *fixture* with #182's change

Guidance would allow it, but a `wait_for_merge` target's closure contains the PR. No assessor runs; the existing line is printed:

```
✓ pr-f01eabb signed off (SIGNOFF_MERGE @ dc400942) — waiting for manual merge (wait-for-merge: pr-8162f0f) — press 'g' to merge
```

`pm guidance check pr-f01eabb` → `Decision: not evaluated — held by wait-for-merge (pr-8162f0f); owner guidance applies only after holds clear`.

## 10. Attempted self-exemption — *fixture*

The PR's branch edits the `## Owner Guidance` section of `pm/notes.txt` (removes the prompts hold) and the `project.owner_guidance.merge_authority.approved` record in `pm/project.yaml` (pins the hash of its edited text), and changes a prompt file.

```
$ pm guidance check fx-self
  Decision:  OWNER_APPROVAL_REQUIRED (fresh)
  Rule:      policy-edit — the candidate changes the Owner Guidance section of pm/notes.txt and the
             owner_guidance record in pm/project.yaml. A PR cannot change the guidance that decides it.
  Basis:     floor
```

The same PR's implementation session tries to approve and to merge:

```
$ pm guidance approve
pm guidance approve: refused — run it from the project's main checkout; this is a PR workdir
(pm/pr-fx-self-…). Nothing was changed.
$ PM_AGENT_ROLE=impl pm pr merge fx-self
PR fx-self: merges run from an agent session are unattended merges and need a current owner-guidance
decision allowing it (current: OWNER_APPROVAL_REQUIRED — policy-edit). Not merging.
```

If the owner later merges that PR themselves, the pulled-in text differs from the approved hash, so the new text is inactive until the owner approves it (intersection rule).

## 11. Restart

**TUI killed while the assessor runs** (*fixture*): the auto-start breadcrumb restores the target; the sign-off driver re-enters the merge decision; pm finds the `authority-#182` window and its transcript in the run directory and adopts it (no second assessor). If the window is gone and there is no result file, attempt 2 is launched; after a second failure the decision is `assessment-unavailable` (waits for the owner).

**Killed between publish and recording the outcome** (*fixture*): on restart the PR shows `merged`, the decision is `AUTO` with an open `attempt` for the published candidate and no `outcome`. pm reconciles: `outcome.kind = auto-merged` (merge SHA read from the base), creates notice `mn-…` in state `pending`, and shows it once:

```
09:14:02  Recovered: pr-f01eabb was merged automatically before the restart; recording the outcome.
09:14:02  ⓘ Heads-up — project-manager · #182 merged automatically (cb7b147a into master) · …
```

A second restart finds the notice already `shown` and prints nothing new.

## 12. Heads-up delivery states and retries

| State | Meaning | Who moves it |
|---|---|---|
| `pending` | created after a verified publish; not displayed anywhere yet (e.g. merged by the bug-fix watcher while no TUI ran) | pm on publish / reconciliation |
| `shown` | displayed in the TUI log (once) and listed by `pm guidance notices` | TUI |
| `included` | taken by a scheduled brief (`included_in: <brief id>`) | pr-2588ead |
| `failed` | an external destination could not be reached; `attempts`, `last_error` kept; retried by its owner, never re-created | pr-2588ead (or a future destination) |

The notice id is derived from (repo, PR, merge SHA), so re-creating it after a crash updates the same record. `Heads-up: next brief` suppresses the immediate TUI line; until a brief exists it falls back to immediate display (A11).

## 13. Failed unattended merge — no merge notice

```
$ pm pr merge --unattended pr-1e9c117          # GitHub refuses the merge (fixture)
PR pr-1e9c117: GitHub did not merge it (required status check missing). Nothing was published.
```

Recorded `outcome: {kind: merge-failed, detail: "GitHub did not merge it (required status check missing)"}`; no notice; the brief lists it as an issue.

## 14. The owner merges a waiting PR

Owner presses `g` on pr-294e53d (manual path — no guidance check). After publish: `outcome: {kind: owner-merged, at: …, merge_sha: …}`; no automatic-merge notice; the brief can report "merged by you after waiting for review".

## 15. Two projects

See [notes-and-records.md §3](notes-and-records.md#3-the-same-kinds-of-change-under-both-projects): the same fixture diffs give different decisions under project-manager's `mg-3` and fixture-b's `fb-1`, and a change to one project's guidance leaves the other's decisions unchanged.
