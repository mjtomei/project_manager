# pr-5cee3d5 — Resolve integration conflicts at sign-off; reuse unaffected evidence

## Problem

Sign-off owns integration (`pm_core/integration.py`, pr-ac10f03). Its check
computes the merge of the PR HEAD with the fetched base in an isolated
candidate and records `up_to_date` / `clean` / `conflict` / `in_base` /
`error`. A `conflict` can only route `SIGNOFF_IMPL`
(`signoff.effective_verdict`), so even a metadata-only `pm/project.yaml`
conflict — two branches independently appending records — restarts
implementation, full review and full QA (PR #250).

The fix must make a *safe* structured resolution part of sign-off, expose its
provenance, let the sign-off agent decide the follow-up stage (impl / review /
qa / merge-only), and let evidence produced on the pre-merge revision be
reused explicitly when the agent judges it still covers the resolved
candidate. The merge step keeps publishing only the exact approved,
conflict-free candidate.

## Requirements (grounded)

### R1. Structured project.yaml resolution in an isolated candidate
`integration.compute_candidate(workdir, head, base_sha)` gains a resolution
attempt when the git merge conflicts **only** in files named `project.yaml`
(any directory, in practice `pm/project.yaml`). The resolution runs in a
throwaway detached worktree (`_worktree_merge_locked` family) — the PR
worktree, its index/branch, and the base are never touched.

New resolver `integration.resolve_project_yaml(base_text, ours_text,
theirs_text)`:
- Merge mappings recursively: a key/value changed on one side and untouched on
  the other is taken; both changed to the same value is taken; both changed
  differently is a **conflict** (never "theirs wins" as
  `store.merge_3way` does).
- Lists of id-keyed entries (`prs`, `plans`, and nested lists such as notes)
  merge by `id`: independent additions from both sides survive; an entry
  changed on one side only is taken; entries changed on both sides merge field
  by field; a field changed differently on both sides is a conflict; a record
  deleted on one side and edited on the other is a conflict; the same id added
  independently on both sides with different content is an ambiguous record
  and a conflict; duplicate ids within one side are ambiguous and a conflict.
  Ordering changes are preserved when only one side reordered; conflicting
  reorders are a conflict. A list absent from the merge base (a PR record
  that never had a `notes` key) merges like an empty one — independent
  additions survive and a same-id/different-content entry is still
  ambiguous.
- Non-id lists (`depends_on`, etc.) and scalars are atomic: both changed
  differently is a conflict.
- **Bookkeeping timestamps are not semantic fields.** `pm pr note add` and
  every status change call `_record_status_timestamp`, which rewrites
  `updated_at` (and the transition stamp) even when the rest of the record
  merges cleanly. Two branches that both touched the same record therefore
  change `updated_at` to different values on the real #250 note-add path. The
  resolver takes the later value for `created_at`, `updated_at`,
  `last_edited`, `started_at`, `reviewed_at`, `signed_off_at` and `merged_at`
  (non-string values keep the normal conflict rule) and the preservation
  check does not count the earlier timestamp as a lost change. Every other
  field still conflicts when both sides changed it differently.
- After merging, validate that **neither side lost a change**: for every leaf
  or id-entry where each side differs from base, the merged result must carry
  that side's value (or the same value both sides chose). Any violation fails
  the resolution.
- Validate the merged document's shape read-only: top-level mapping,
  `prs`/`plans` id-keyed with unique ids, valid PR statuses
  (`pr_utils.VALID_PR_STATES`), valid plan statuses/parents/no cycles. Invalid
  shape fails the resolution.
- Serialize with pm's writer (`store._YAML_HEADER` + `yaml.dump(...,
  Dumper=store._yaml_dumper(data), default_flow_style=False,
  sort_keys=False, allow_unicode=True)`) so output is deterministic and
  byte-identical to `store.save` for unchanged data.

If any resolver returns a conflict or fails validation, the candidate stays
`CONFLICT`; the partial resolution record is retained (visible, never silently
applied). Non-`project.yaml` conflicts are never resolved automatically.

### R2. Resolved candidate status + provenance
New status `integration.RESOLVED` added to `MERGEABLE`. `compute_candidate`
returns, for a successful resolution:
- `candidate_tree` (the fully merged tree, conflict-free),
- `resolution` = `{paths: [{path, resolver, added_ours, added_theirs,
  merged_fields, removed, records, blob}], unresolved: [], diff: <text>,
  base_tree, head_tree}`,
- `base_behavior_changes` (R3).
`compact()` keeps a bounded resolution summary and a `resolution_digest`
(sha256 over canonical resolution JSON). The full record (including the diff)
goes to `$CAP/<pr>/integration.json`; the human-readable delta goes to
`$CAP/<pr>/integration-resolution.diff`.

`added_ours`/`added_theirs`/`merged_fields`/`removed` name nested-list ids
with their list path (`prs[pr-200].notes:note-1`), so a resolution that only
merged notes inside an existing record is visible instead of looking empty.
`summary()` renders resolved candidates ("conflicts with master@… resolved by
record (N added from PR, M from base)", counting nested records) and failed
resolutions.

### R3. Do not exempt metadata; surface new-base interactions
`compute_candidate` computes `base_behavior_changes` for every check with a
non-empty base diff (clean merge included):
- for changed `project.yaml` files: diffs of `project.model_config`,
  `project.skip_qa`, `project.base_branch`, `project.backend`,
  `project.nested_podman`, `project.libyaml`, PR `status` / `depends_on` /
  `model` / `session_models` / `plan`, plan `status`;
- for changed dependency/config paths (`pyproject.toml`, `requirements*.txt`
  / `requirements*.in`, `setup.py`/`setup.cfg`, `package.json`, `Dockerfile`,
  `install.sh`, `Makefile`) and CI workflow files (`.github/workflows/`):
  the path with a one-line note.
Recorded (bounded) in the integration record and shown in the sign-off prompt
so the agent must weigh them even when Git reports a clean merge. PM does not
auto-approve or auto-reject on them — the agent decides and must say so.

### R4. Apply the resolved merge to the PR branch before sign-off runs
For the GitHub backend `gh pr merge` cannot merge a conflicted branch, and
sign-off's report/verdict must bind to a candidate that can actually be
published. So the sign-off launch
(`signoff.launch_signoff_window`) runs a new
`integration.prepare(root, pr_id)`:
1. `check_integration` (records the check; resolves metadata-only conflicts in
   the isolated candidate).
2. If status is `RESOLVED`, `apply_integration` merges the base into the PR
   branch and applies the same deterministic resolution to the conflicted
   `project.yaml` files (recomputing it from index stages), commits the merge,
   and verifies the resulting tree **equals** `candidate_tree` before
   committing; on any mismatch or remaining conflict it aborts the merge and
   restores the original HEAD. HEAD is re-verified immediately before the
   merge, and a branch that already carries the base (a concurrent apply won
   the race) is reported as the applied revision instead of being committed
   over or reset — `merge --abort` is used, never `reset --hard <checked
   head>`, so a concurrent commit is never discarded.
3. Re-runs the check against the **same** base revision (no second fetch, so
   a base that moves during the apply cannot make the record describe a
   different merge) and records it with the resolution provenance carried
   forward (`resolution.applied_merge_sha`,
   `resolution.resolved_from = {head, base_sha, merge_base, status}`,
   `resolution_digest`, and the pre-apply `base_behavior_changes`). The
   re-check is written **once**, already carrying the resolution (it is
   computed with `run_check` and persisted by a single `_record_check`): an
   intermediate record without the resolution would drop the applied
   provenance — and with it the explicit-reuse requirement — if pm died
   between the two writes. `resolved_from` is also kept at the top level of
   the record so the evidence block and the prompt read it directly.
   A later re-check carries the compact resolution (and those behavioural
   changes) forward whenever the applied merge is an ancestor of its HEAD —
   including a check that comes back `error`/`conflict` without a new
   resolution attempt — so a transient failure never loses what was applied.
   A check that *does* produce a new metadata-resolution attempt replaces it
   instead: that attempt describes the current base, and the merge is blocked
   either way (the changed digest / missing candidate tree makes the gate
   refuse). The ancestry is resolved from the same checkout the check used
   (the recorded workdir, or the current checkout when that path is not
   visible), so a check run from the fallback does not drop the provenance.
   The merge itself is still blocked until a check can verify the candidate
   again.
Dirty workdirs are never touched: apply refuses and the record keeps
`RESOLVED` with `apply_error`; a MERGE on it is blocked (R6).

`apply_integration` also handles `RESOLVED` for sign-off bounces (R5), and
refuses any record whose head no longer matches, whose workdir is not on the
PR branch, or that has a merge in progress.

### R5. Agent decides the return stage; bounces see integrated code
`effective_verdict` keeps conflicts → `IMPL` for unresolved candidates, and
allows MERGE / REVIEW / REQA for `RESOLVED` candidates that were applied.
`_prepare_bounce` integrates a `RESOLVED` record the same way it integrates a
`CLEAN` one (via `apply_integration`), so review/QA run on the integrated
tree. When the bounce is the first successful apply (sign-off launch could
not touch a dirty workdir), the applied record is persisted on the PR
(`up_to_date` at the merge commit, resolution bound) so a later check carries
the provenance forward instead of dropping it — and with it the explicit
reuse requirement. The return record (`build_return_record`,
`format_signoff_return`) adds the resolution summary, `applied_merge_sha`,
and the original `resolved_from` revisions; the prompt tells the next stage
to verify the integrated result, not only the PR's own diff. When the launch
`prepare` already applied the resolution (so the bounce has nothing left to
apply and no `applied` block), the return text also gives the corrected diff
command (`git diff <applied base> HEAD`) — the workdir's own base refs are
stale after the apply, so the usual `<base>...HEAD` diff would list the
merged base commits as PR changes.

### R6. Evidence provenance and explicit reuse
`record_signoff_verdict` gains an `evidence` block on `pr["signoff"]`:
- `reviewed_head` (the revision sign-off reviewed),
- `resolved_from` (the pre-resolution head/base/merge-base when applicable),
- `review` (recorded `reviewed_at`; when QA recorded `planner_head` and no
  `planner_code_changes`, that revision is recorded as the review's with
  `sha_source: inferred-from-qa` — otherwise pm states it does not record
  the review revision),
- `qa` (latest `qa_status.json` `overall`, plus `planner_head` and
  `planner_code_changes` from its sibling `qa_resume.json`),
- `prior_signoff` (previous record's sha/verdict/ts, if any),
- `required_return_stage` (the verdict mapped to its stage),
- agent-declared reuse from `report.html` meta tags (only trusted when the
  report's `pm-signoff-head` matches the reviewed head):
  `pm-signoff-evidence` (`stage@sha,…`), `pm-signoff-evidence-reason`,
  `pm-signoff-checks`, `pm-signoff-candidate`.
The block is rewritten into `project.yaml` on every record, so its lists
(`reused`, `planner_code_changes`) are bounded at 20 entries with a
`*_total` count when truncated.
`pr_signoff_record` and the auto-sequence driver refuse/coerce a `MERGE` when
the integration carries a `resolution` or `base_behavior_changes` but the
report does not state (a) the candidate tree (`pm-signoff-candidate`) for
resolved candidates and (b) which evidence is reused / which targeted checks
were run, with a reason. A resolved MERGE additionally requires
`resolution.applied_merge_sha`. `pm-signoff-candidate` must be at least 7
characters (like the head tag) — a short value could match almost any tree
as a prefix without identifying the approved one. This makes reuse an
explicit, recorded act instead of an invented approval.

The sign-off prompt (`_signoff_integration_block` + step 0 + report contract)
renders the resolution (paths, ids added/changed/removed, unresolved), the
delta file path, the applied merge, the base behavior changes, the available
evidence revisions, and instructions: metadata-only conflicts are not an
automatic exemption; state reuse or the targeted checks; choose the earliest
affected stage. The pre-existing base-interaction guidance stays in step 0
(read the base diff, judge semantic overlap — the same behaviour/APIs/data/
tests changed on both sides — line/file counts alone are not the rule), and
the applied-resolution diff is described accurately: `git diff <old head>
HEAD` shows the whole base merge, not only the resolution (the delta file
lists just the resolution changes). The prompt's primary diff command names
the exact base revision the branch contains — an applied resolution or a
clean base merged by a bounce — instead of `origin/<base>`, which pm never
updates and which would list the merged base commits as PR changes; the
base-changes range is shown as the pre-apply range for an applied
resolution, and omitted (rather than printed empty as "0 file(s)") when the
base is inside HEAD with no recorded pre-apply range.

### R7. Merge gate / publication identity
`merge_gate_refusal` additionally requires:
- the PR's current `integration` record, when present, still has the bound
  `head` and `candidate_tree` (a re-check that produced a different candidate
  invalidates the approval; a re-check that can no longer name a candidate
  tree — e.g. a failed fetch — cannot justify the approval, and the refusal
  says so instead of blaming report.html). An absent record is left to the
  bound approval: it is authoritative and publication revalidates it against
  a fresh fetch, so absence alone is not a refusal (the same reading the
  existing merge-gate tests encode);
- for a bound `resolution_digest`: the current record carries the same digest,
  `resolution.applied_merge_sha` is set, `resolution.unresolved` is empty, and
  the report justification of R6 is present. The digest is also recomputed
  from the current record's resolution and must agree with the stored value,
  so a resolution edited without its digest cannot ride an old approval;
- for `base_behavior_changes`: the report justification of R6 is present.
`BINDING_KEYS` gains `resolution_digest`.
`_publish_candidate` recomputes the candidate with `resolve=False` and
refuses when the tree differs (now covering the resolved/applied head), so
the merge step can never introduce a new resolution. Base movement still
invalidates and returns to sign-off.

### R8. CLI / user-visible flow
`pm pr signoff integrate <pr>`:
- `--resolve/--no-resolve` (default resolve),
- prints the resolution summary, unresolved conflicts, applied merge and the
  delta file path; exits 1 on unresolved conflict/error;
- `--apply` applies a `CLEAN` or `RESOLVED` candidate (the existing clean
  behavior is preserved), including a `RESOLVED` check whose re-check in
  `prepare` comes back `CLEAN` because the base moved between the two checks.
`--record` still records the check the verdict binds to.

### R9. Regression coverage
Real-git tests (new `tests/test_signoff_resolution.py` plus resolver unit
tests):
1. #250 reproduction: base and branch each append distinct PR entries (and
   notes) to `pm/project.yaml`; integration resolves; both/all records survive
   in the published merge tree; a bound sign-off with the required report tags
   merges; review/QA evidence revisions and reuse are recorded; a fresh
   sign-off is still required (no merge without a new record).
2. Same record/field conflict → `CONFLICT`, no resolution, MERGE coerced to
   IMPL.
3. Deletion vs edit → `CONFLICT`.
4. Non-project.yaml (code) conflict → `CONFLICT`, never auto-resolved.
5. Clean base change to `project.model_config` → `CLEAN` but
   `base_behavior_changes` non-empty and a MERGE requires the justification
   tags.
6. Stale candidate identity: base moved after approval → refused/invalidated;
   a re-check with a different candidate tree → refused.
7. Preservation: resolution never changes the PR workdir HEAD/branch/dirty
   files; captures/evidence files survive.
8. Bounce to REVIEW applies the resolution and the branch tree equals the
   candidate.
9. Prompt/CLI surfaces: sign-off prompt names the resolution, candidate,
   evidence instructions; `integrate` prints the resolution.
10. Notes appended to the same PR record on both sides (the merge base has no
    `notes` key) resolve, both notes survive, and the nested ids are named in
    the summary/prompt; the same id with different content is still ambiguous.
    Cover the *real* command path too: `_record_status_timestamp` bumps
    `updated_at` on both sides, which must not block the merge, while a real
    field conflict (e.g. both change `status` differently) still does.
11. Approval guards: a too-short or wrong `pm-signoff-candidate` is not
    accepted, an unapplied resolution cannot be justified, an approval bound
    to an unapplied or unresolved resolution is refused by the merge gate
    even when recorded directly, a re-checked record for another HEAD is
    refused, and a concurrent apply that already integrated the base is not
    committed over or reset away.
12. Resolver safety rails: conflicting reorders, field (scalar-key)
    deletion-vs-edit in both directions, a merged document with an invalid
    status or a plan cycle, a nested duplicate id, and a merge that loses a
    side's change (scalar or id-keyed record) are all refused (a one-sided
    field deletion is kept; a record both sides deleted is removed).
13. Apply/merge guards: a re-resolution whose blob differs from the recorded
    one is refused and the workdir left untouched; an apply that hits a
    conflict outside the recorded resolution aborts; a clean or re-resolved
    merge whose tree differs from the candidate is aborted; a HEAD moved
    under the apply is refused; an unresolved `RESOLVED` record is not
    mergeable (and never looks approved without its provenance); a changed
    (or digest-inconsistent) resolution invalidates the approval; an applied
    resolution's behavioural changes survive a benign re-check and a failed
    check keeps the bound resolution; a config-file base change (e.g.
    `pyproject.toml`) requires the same justification as `project.yaml`; the
    full `integration.json` record carries the digest of the resolution it
    describes.

## Implicit requirements

- **Determinism.** The resolver must produce the same bytes at check time and
  at apply/merge time, or the merge gate would refuse every resolved
  candidate. Hence: fixed merge order (base order, then ours-only additions,
  then theirs-only additions), pm's serializer, no timestamps in the
  serialized document.
- **Read-only check.** `run_check` must not write the PR worktree, index,
  branch, or base; only the explicit `apply_integration` step does.
- **Locking.** Resolution worktrees/fetches stay inside `_repo_lock`; the
  project.yaml record writes stay inside `store.locked_update`.
- **Backward compatibility.** `CLEAN`/`UP_TO_DATE` approvals without a report
  keep working; the new justification requirement only applies when the
  record carries a resolution or behavioral base changes.
- **Bounded output.** Resolution details/diffs are capped in `project.yaml`
  (`compact`) and in the artifacts; no full project.yaml copies in state.
- **Existing evidence untouched.** Captures, `qa_status.json`, `qa_resume.json`
  and prior `report.html` files are read, never rewritten.

## Edge cases

- `project.yaml` absent on one side (add/add or modify/delete): a missing
  base with two different added documents is ambiguous → conflict; a
  modify/delete is a deletion/edit conflict → conflict.
- YAML parse failure on any stage → conflict (no resolution).
- Duplicate ids / non-list / non-mapping documents → conflict.
- The resolution changes only `pm/project.yaml`; any other conflicted path
  aborts the attempt and keeps the original conflict list.
- Workdir dirty / detached HEAD / merge in progress → apply refused; record
  keeps `RESOLVED` + `apply_error`; MERGE blocked; a bounce records the error.
- Base moves between the applied resolution and the merge → merge gate /
  publish refuses, invalidates, returns to sign-off.
- Head moves (agent commits) after the applied resolution → stale approval;
  sign-off re-runs on the new head.
- A resolved candidate with an empty diff (both sides made the same change) is
  still recorded as resolved; the report requirement still applies because a
  conflict was reconciled.
- `store.merge_3way` (the live-state stash-pop path) is unchanged; the new
  resolver is integration-specific because its conflict policy differs.
- Bookkeeping timestamps (`updated_at`, `last_edited`, …) both bumped to
  different values merge to the later value; a non-timestamp value in one of
  those keys keeps the normal conflict rule.
- Old git (< 2.38) and new git both resolve; the worktree path is used for
  resolution regardless of `merge-tree`.

## Ambiguities resolved (no [UNRESOLVED] items)

- **Apply the resolution at sign-off vs only at merge.** Chosen: apply at
  sign-off (R4). GitHub's `gh pr merge` cannot merge a conflicted branch, and
  the approved candidate must be publishable. The check stays read-only; the
  apply is a separate, recorded step whose result is re-checked and bound.
- **Automatic resolution scope.** Chosen: only when *all* conflicts are
  `project.yaml`; mixed conflicts stay unresolved so no partial resolution is
  silently applied.
- **Enforcement of evidence reuse.** Chosen: a resolved (or behaviorally
  changed) MERGE requires an explicit report statement, enforced at record and
  merge-gate time; otherwise the agent may still route REVIEW/REQA/IMPL
  without one.
- **"Behavioral configuration" set.** Chosen: the explicit `project.yaml`
  keys/paths in R3; anything else is covered by the generic overlap listing
  and the agent's judgment.
