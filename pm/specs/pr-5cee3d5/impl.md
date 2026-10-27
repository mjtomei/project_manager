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
  and a conflict; duplicate ids within one side are ambiguous and a conflict —
  including inside a nested list (e.g. two notes with one id), even when that
  list is taken wholesale because the other side did not touch it.
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
- **pm's own UI cursor is not a field conflict either.**
  `project.active_pr` is the TUI's selected PR: `pm_core.tui` persists it
  through the coalescing write queue on *every cursor move*, so any branch pm
  was used on carries a different value from the base. Verified against this
  repository's own merge with master, it was the **only** non-record conflict
  — refusing it defeated the whole point of the feature (independent record
  appends could never resolve on a branch anyone used pm on). Both sides
  changing it merges to the new base's value (the shared state; the branch's
  cursor belongs to its author and pm rewrites it on the next keystroke),
  deterministically, and the branch's value is not counted as a lost change.
  The exemption is that one path: every real `project` field (and a
  deletion-vs-edit of the cursor) still conflicts. UI *preferences* a person
  set deliberately (`project.hide_merged`) are not exempt.
- After merging, validate that **neither side lost a change**: for every leaf
  or id-entry where each side differs from base, the merged result must carry
  that side's value (or the same value both sides chose). Any violation fails
  the resolution.
- Validate the merged document's shape read-only: top-level mapping,
  `project` a mapping when present, `prs`/`plans` id-keyed with unique ids,
  valid PR statuses (`pr_utils.VALID_PR_STATES`), valid plan
  statuses/parents/no cycles. Invalid shape fails the resolution. Validation
  must *refuse* malformed values, never raise: a non-string status or plan
  parent (which cannot be a set member or be walked as a key) and a
  non-mapping `project` (which the serializer's `libyaml` lookup would
  otherwise dereference) are reported as problems so the caller gets a
  readable conflict instead of a resolver exception.
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
`compact()` keeps a bounded resolution summary, a `resolution_digest`
(sha256 over canonical resolution JSON) and, when there is an actual delta,
the `resolution.diff_path` pointer (the digest excludes the host-specific
path, so a re-compaction hashes identically; a failed attempt has nothing to
write, so it names no file). The full record (including the diff) goes to
`$CAP/<pr>/integration.json`; the human-readable delta goes to
`$CAP/<pr>/integration-resolution.diff`. The read-only
`pm pr signoff integrate` writes the same delta (it records nothing on the
PR) so the path it prints is inspectable.

`added_ours`/`added_theirs`/`merged_fields`/`removed` name nested-list ids
with their list path (`prs[pr-200].notes:note-1`), so a resolution that only
merged notes inside an existing record is visible instead of looking empty.
A one-sided *field* deletion is a merge, not a removed record: it does not
appear in `removed` (the delta shows it), which names whole records only.
`compact` keeps at most 20 ids per list and records the real length in
`<key>_total` (preserved across re-compaction so the digest stays stable);
the sign-off prompt and `pm pr signoff integrate` list a prefix and say
"… N more" from that total rather than dropping ids silently.
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

The summary is best-effort so it never fails the check (`base_behavior_error`
is recorded instead of raising). A failed summary is **not** an exemption: the
merge gate and the prompt treat `base_behavior_error` like a behavioural
change, so a MERGE still has to state the evidence reused or the targeted
checks run. Otherwise an unexpected raise would silently drop the requirement
that makes the agent weigh the new base. It must therefore survive the same
carry-forward the listed changes do: the post-apply re-check sees no base
diff (the base is inside HEAD now), so `prepare` copies the pre-apply
`base_behavior_error` onto the applied record, and a later benign re-check
carries it forward with the resolution (only when that check produced neither
changes nor a summary of its own).

The post-apply re-check also sees an empty base diff of its own, so its
`base_files`/`overlap` would be empty and the sign-off prompt would stop
showing which files the base changed and which changed on both sides — the
interaction the agent must weigh (R3). `prepare` therefore carries the
pre-apply base file list (its count is what the prompt reports for the
base-changes range) and the overlap onto the applied record, and a later
re-check carries them forward with the resolution (the compact record keeps
the count when only `base_files_count` survives).

A **clean** base merged by a bounce (`_prepare_bounce` applies a `CLEAN`
record too) has no resolution to carry, yet it puts the base inside HEAD the
same way: the next check's `merge-base(HEAD, base)` is the base itself, so its
own base diff is empty. The same requirement therefore applies without a
resolution: `integration._carry_base_interaction` carries the earlier check's
`base_files`/`base_files_count`, `overlap`, `base_behavior_changes` (and
`base_behavior_error`) when the old record assessed the *same* base revision
and the branch now contains it (a check that still sees a base diff of its
own has a newer summary and keeps it). It also records the pre-merge merge
base as `base_range_from` (the recorded `merge_base` is the base itself now,
which would print as an empty range), so the sign-off prompt still names the
range the base brought; the prompt falls back to it only when the recorded
merge base equals the fetched base. The same carry applies when the stored
record's resolution attempt was **never applied** (a failed attempt, or a
resolved candidate a dirty workdir kept pm from applying) and the branch now
contains the same base: the sign-off return tells implementation to reconcile
the conflict by hand, so no check ever saw that base outside HEAD, and the
record still assessed it — `_carry_forward` falls back to
`_carry_base_interaction` when it could not carry an applied resolution. A
new attempt on the current check replaces it, as above.

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
   A check that could not resolve HEAD at all (a transient failure: a broken
   or replaced workdir) cannot prove the ancestry, but it carries the
   applied resolution anyway rather than losing it — the record is `error`
   (never mergeable), and a later successful check re-verifies the ancestry
   before any approval can bind to it.
   The merge itself is still blocked until a check can verify the candidate
   again.
   Concurrent applies cannot lose the applied record. When the apply loses the
   HEAD race (`HEAD_MOVED`/`HEAD_MOVED_APPLYING`), `prepare` re-checks the
   revision the branch now has (against the same base) and records that
   instead, so the loser never writes its stale `resolved` check over the
   winner's applied one. `_record_check` additionally refuses, inside the
   locked read-modify-write, to write a check computed before HEAD moved when
   the stored record already describes the branch's current revision
   (`_check_is_stale`, which resolves HEAD from the same fallback checkout as
   `_carry_forward`, so the container case is covered too) — the loser's
   record is then dropped, not written.
   The apply itself runs under the repository lock (`_repo_lock`), like the
   check's fetches and candidate worktrees: otherwise two applies (the
   sign-off launch, a `--apply`, a bounce) can both pass the HEAD check and
   enter `git merge` in the same workdir, where the loser's `merge --abort`
   discards the winner's in-progress merge and both report a confusing "merge
   failed". Serialized, the loser sees the winner's commit and returns
   `HEAD_MOVED`, which `prepare` re-checks and records.
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
tree. An apply that raises is recorded as the bounce's `apply_error` (the
same "never crash the driver/launch on an apply bug" contract
`integration.prepare` follows) instead of taking the tick down. When the
bounce is the first successful apply (sign-off launch could
not touch a dirty workdir), the applied record is persisted on the PR
(`up_to_date` at the merge commit, resolution bound) so a later check carries
the provenance forward instead of dropping it — and with it the explicit
reuse requirement. That write yields only to a concurrent record of a
different revision, except for a bare up-to-date check of the merge it just
made: that check describes the same revision but cannot know about the apply
(it carried from a record without `applied_merge_sha`), so letting it stand
would silently drop the provenance. The return record (`build_return_record`,
`format_signoff_return`) adds the resolution summary, `applied_merge_sha`,
the original `resolved_from` revisions and the base's `base_behavior_error`
(a summary pm could not compute is not evidence that the base is
behaviour-neutral), and the return text says so. A `HEAD_MOVED`/
`HEAD_MOVED_APPLYING` apply error is reported as a concurrent move of the
branch (the winner's merge is in it), not as "pm did not merge the base";
the prompt tells the next stage to verify the integrated result, not only
the PR's own diff. When the launch
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
  the review revision; a *malformed* (non-list) `planner_code_changes` is
  not proof that QA committed nothing, so it suppresses the inference
  instead of recording a review revision pm cannot confirm),
- `qa` (latest `qa_status.json` `overall`, plus `planner_head` and
  `planner_code_changes` from its sibling `qa_resume.json`; malformed evidence
  is recorded as unreadable/absent, never raised — a non-string
  `planner_head` is no revision, so the block and the prompt do not slice it,
  and a non-list `planner_code_changes` carries a `planner_code_changes_error`
  marker; no host path is recorded — the block travels to master in the
  tracked project.yaml, where a per-host absolute path is dead weight),
- `prior_signoff` (previous record's sha/verdict/ts, if any),
- `required_return_stage` (the verdict mapped to its stage),
- agent-declared reuse from `report.html` meta tags (only trusted when the
  report's `pm-signoff-head` matches the reviewed head):
  `pm-signoff-evidence` (`stage@sha,…`), `pm-signoff-evidence-reason`,
  `pm-signoff-checks`, `pm-signoff-candidate`.
The block's `candidate_tree`/`resolved_from` come from the bound check or,
failing that, from the PR's stored check only when that check names the
reviewed HEAD — a check of another revision (or a failed one with no HEAD)
must not lend its candidate/resolution to this decision.
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
affected stage. A resolution the record carries but has *not* applied is
labelled "Not applied" even when pm recorded no apply error (a
`--record`-only check): the agent must not read a resolved candidate as
already integrated, because a MERGE is blocked until it is. A carried applied
resolution on a `conflict`/`error` record is labelled an *earlier*, already
applied resolution and the current problem is described as separate — "the
conflict above" on a `conflict` record, "the failed check above" on an
`error` record (it reports a failed check, not a conflict) — the same
qualification the CLI and the return text carry
(`integration.carried_applied_resolution`). The behaviour-change list's total
falls back to the stored list's length when `compact` kept 21-30 changes
without a `base_behavior_count` (indexing the absent key would crash the
prompt), and a recorded count *smaller* than the stored list (hand-edited, or
a count kept while the list shortened) is not allowed to hide entries the
20-line cap drops: the total is the larger of the count and the list, like the
return text (`format_signoff_return`) already computes. The pre-existing base-interaction guidance stays in step 0
(read the base diff, judge semantic overlap — the same behaviour/APIs/data/
tests changed on both sides — line/file counts alone are not the rule), and
the applied-resolution diff is described accurately: `git diff <old head>
HEAD` shows the whole base merge, not only the resolution (the delta file
lists just the resolution changes). The prompt's primary diff command names
the exact base revision the branch contains — an applied resolution or a
clean base merged by a bounce — instead of `origin/<base>`, which pm never
updates and which would list the merged base commits as PR changes; the
base-changes range is shown as the pre-apply range only while the base
inside HEAD is still the one the resolution applied (the recorded merge base
equals the checked base *and* `resolved_from.base_sha` does), and omitted
(rather than printed empty as "0 file(s)") when the base is inside HEAD with
no recorded pre-apply range. Once the base has moved on past an applied
resolution, the recorded merge base is the applied base, so the range starts
there — using the pre-apply merge base would list the commits the resolution
already merged as new base changes and disagree with the recorded file
count. The same holds when a *newer* base is merged by a bounce after the
resolution: the range starts at the applied base, not the resolution's
pre-apply merge base. The same exact-base
rule applies to the review and QA prompts' own diff command (and the QA
interactive prompt): once a bounce has integrated the base, diffing the
workdir's stale `<base>`/`origin/<base>` ref would list the merged base
commits as PR changes. The applied base is taken from the applied resolution,
a newer `up_to_date` check, or the merge a bounce recorded in
`signoff_return.applied` (a clean bounce leaves the pre-merge `clean` check
in place). The branch can contain more than one base revision (a resolution
applied at sign-off, then a newer base merged by a later bounce), so
`integration.contained_base(pr)` collects those candidates (only values that
look like git object names: the value is interpolated into a command the
agent is told to run, so a hand-edited shell fragment must not become the
diff ref), drops any HEAD does not contain, and keeps the newest by
ancestry — the last check's
recorded `merge_base` (which survives a later check replacing the
`up_to_date` record) is one candidate, but only when a base merge is known;
without one it is just the branch point and the usual base-branch diff
stays. A later bounce can replace `signoff_return` (and with it the
`applied` block that recorded the merge), so when the workdir is visible the
merge base is also recognised by ancestry: a base the branch merged sits on
a merge commit's non-first parent side and is absent from HEAD's
first-parent chain, while the branch point is on it. The same newest-base
rule drives the sign-off prompt's
"PR's own changes remain" line and the return text's `git diff <base> HEAD`
hint, and every other surface that tells an agent or a person to inspect the
PR's own diff — the review / QA-planner / QA-interactive prompts, the QA
*spec* prompt (`pm pr spec <pr> qa`, `spec_gen._build_spec_prompt`) and the
review window's diff pane (`_launch_review_window`) — names the exact base
the branch contains instead of the stale workdir ref. The pane's fallback ref
(`<base>` for the local backend, `origin/<base>` otherwise) is shell-quoted
like every other interpolated value: `base_branch` is project.yaml state, and
an unquoted value with shell metacharacters would run in the pane's shell.

**Why sign-off is running again.** When the merge gate refuses an approval
because the base moved (`invalidate_signoff`), the driver clears
`pr['signoff']` before relaunching, so the prompt builder cannot read the
reason (or the approved revision) from the record. The reason is therefore
also kept beside it as `pr['signoff_invalidated'] = {reason, at, verdict,
sha, base_sha}` (non-string revisions read as absent). A new verdict clears
it (`record_signoff_verdict`), so it only describes the current re-run.

The sign-off prompt then emits a "Why sign-off is running again" block —
naming the refusal reason, the previous verdict and the revision it approved,
and pointing at `$CAP/report.html` as reusable — **only** when the PR's own
changes are unchanged since that approval. The relaunch may apply the base
merge, which moves HEAD without being PR work, so "unchanged" means either
the current check's `head` equals the approved revision, or the applied
resolution's `resolved_from.head` does. Any commit the PR added since the
refusal leaves neither matching and the block is omitted. A verdict bounce is
a different episode (it writes `signoff_return`) and never emits this block:
the marker outlives the bounce (only a new verdict clears it), and the
bounce's own run overwrites `$CAP/report.html`, so while a sign-off return is
open the pointer is suppressed — the head test alone cannot tell that re-run
from the invalidation relaunch when the bounce added no PR work. The agent is
told to read the previous report *before* overwriting it and that a fresh
report bound to the new head/base/candidate is still required.

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
- an `in_base` record is exempt from the candidate-tree requirement: the
  approved head is already published, and the merge step's recovery path
  finalizes that merge. The exemption applies to resolved approvals too —
  `approval_justification_problem` returns no problem for an `in_base` record
  (there is no candidate left to name), so a resolved candidate whose head
  landed in the base is recovered rather than sent to a sign-off that can
  only block an `in_base` head;
- for a bound `resolution_digest`: the current record carries the same digest,
  `resolution.applied_merge_sha` is set, `resolution.unresolved` is empty, and
  the report justification of R6 is present. The digest is also recomputed
  from the current record's resolution and must agree with the stored value,
  so a resolution edited without its digest cannot ride an old approval;
- for `base_behavior_changes`: the report justification of R6 is present;
- for `base_behavior_error` (the summary failed): the same justification, so
  a check pm could not summarise cannot pass as behaviour-neutral.
`BINDING_KEYS` gains `resolution_digest`.
`_publish_candidate` recomputes the candidate with `resolve=False` and
refuses when the tree differs (now covering the resolved/applied head), so
the merge step can never introduce a new resolution. Base movement still
invalidates and returns to sign-off.

### R8. CLI / user-visible flow
`pm pr signoff integrate <pr>`:
- `--resolve/--no-resolve` (default resolve),
- prints the resolution summary, unresolved conflicts, applied merge and the
  delta file path; exits 1 on unresolved conflict/error. A path a failed
  attempt could not reconcile is labelled as an attempt (never "resolved"),
  in the CLI output and in the sign-off launch — the summary, the
  `unresolved:` line and the per-path line must agree. A resolution *carried
  forward* from an earlier applied merge (R4) is not an attempt at the
  current conflict: its paths were reconciled and applied, and the conflict
  the record now reports is elsewhere, so they are not labelled "attempted —
  NOT resolved", and the per-path line says "resolved earlier … (already
  applied)" (the sign-off launch, the prompt and the return text say the same:
  an earlier, already-applied resolution, with the current conflict separate);
- `--apply` applies a `CLEAN` or `RESOLVED` candidate (the existing clean
  behavior is preserved), including a `RESOLVED` check whose re-check in
  `prepare` comes back `CLEAN` because the base moved between the two checks.
  With resolution enabled it delegates to `prepare` directly (check -> apply ->
  re-check, recorded as one record) instead of running a separate check first,
  which fetched the base and merged the candidate a third time.
`--record` still records the check the verdict binds to.

`pm pr show <pr>` — the reader `integration_pointer` tells a session to run —
renders a resolved record: the candidate tree, the per-path resolution (which
records pm combined, added from each side, merged and removed, with a `… N
more` marker from the record's real total), the unresolved conflicts, the
applied merge, the resolution digest the approval binds to and the delta
file's basename. A resolved candidate must not be a dead end there (the
prompt's abbreviated lists point at this command).

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
   evidence instructions; `integrate` prints the resolution; after an applied
   resolution the prompt still lists the files changed on both sides and the
   base-changes file count (carried through the post-apply re-check and a
   later one). The same must hold after a **clean** base merged by a bounce:
   the next sign-off keeps the base's behaviour changes, the file count and
   the pre-merge base range (`base_range_from`), and the merge gate still
   requires the evidence statement; a newer base's own summary replaces the
   carried one. It must also hold when the stored attempt was never applied
   (a failed resolution, or a resolved candidate a dirty workdir kept pm from
   applying) and implementation reconciles the conflict by hand, so the next
   check sees the same base inside HEAD with no applied resolution: the file
   count, the overlap, the behaviour changes and the prompt's base range
   survive (and the gate still requires the statement when the base changed
   behaviour-relevant configuration). A **newer** base merged by a bounce
   after an applied resolution starts the base-changes range at the applied
   base (not the resolution's pre-apply merge base, which would re-list the
   already-merged commits and disagree with the file count). A resolution
   with more than 10 ids per list names the remainder ("… N more") in the
   prompt and in `integrate`, and every record revision that becomes a
   command the agent is told to run is a git object name: `contained_base`
   refuses anything else, and the sign-off prompt's base-range / applied-merge
   lines and the return text's `git diff <rev> HEAD` / `git merge <rev>`
   hints fall back (`<base>`, `<old head>`, the base branch) instead of
   interpolating a hand-edited fragment.
10. Notes appended to the same PR record on both sides (the merge base has no
    `notes` key) resolve, both notes survive, and the nested ids are named in
    the summary/prompt; the same id with different content is still ambiguous.
    Cover the *real* command path too: `_record_status_timestamp` bumps
    `updated_at` on both sides, which must not block the merge, while a real
    field conflict (e.g. both change `status` differently) still does. The
    same holds for the TUI's cursor: `project.active_pr` differs on every
    branch pm was used on, so a branch + base that each append records *and*
    each carry their own cursor still resolves and applies (the base's cursor
    wins, every record survives) — while a real `project` field changed
    differently on both sides, and a deleted-vs-edited cursor, are conflicts.
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
    Malformed values — a list/dict status or plan parent, a non-mapping
    `project`, and a base `project.yaml` with a non-string record id — are
    refused as readable conflicts rather than raising (and a malformed base
    entry must not silently drop the behaviour-change summary).
13. Apply/merge guards: a re-resolution whose blob differs from the recorded
    one is refused and the workdir left untouched (a hand-edited non-string
    `blob` reads as absent rather than raising out of the unattended apply);
    an apply that hits a
    conflict outside the recorded resolution aborts; a clean or re-resolved
    merge whose tree differs from the candidate is aborted before it is
    committed (the clean apply merges with `--no-commit` and verifies
    `write-tree` equals the candidate, so no destructive reset is needed and a
    record with no candidate tree is refused the same way); a HEAD moved
    under the apply is refused; an unresolved `RESOLVED` record is not
    mergeable (and never looks approved without its provenance); a changed
    (or digest-inconsistent) resolution invalidates the approval; an applied
    resolution's behavioural changes survive a benign re-check and a failed
    check keeps the bound resolution — including a check that could not
    resolve HEAD at all (a transient failure) and one recorded from the
    fallback checkout when the recorded workdir is not visible (the stale
    check is still recognised there, so a loser cannot overwrite the
    winner's applied record); a config-file base change (e.g.
    `pyproject.toml`) requires the same justification as `project.yaml`; the
    full `integration.json` record carries the digest of the resolution it
    describes; a failed behaviour summary still requires the justification
    (and the prompt says the summary failed), including across an applied
    resolution and a later benign re-check; a resolved approval whose head
    is already in the base is recovered, not refused for a missing candidate.
14. Malformed evidence and honest surfaces: a non-string `qa_resume.json`
    `planner_head` is recorded as no revision and does not crash the prompt,
    and a non-list `planner_code_changes` does not get a review revision
    inferred from it (the prompt says pm cannot tell whether QA committed
    changes);
    a `qa_status.json` that is valid JSON but not a mapping, and one whose
    `scenarios` member is not a list, are reported as malformed evidence
    instead of raising out of the sign-off prompt; a verdict recorded
    without a revision does not inherit a *headless* stored check's
    candidate/resolution; a `HEAD_MOVED` bounce apply is reported as a
    concurrent branch move, not as "pm did not merge the base";
    the `integrate` CLI (and the launch) label a failed attempt's paths as
    attempted, never resolved, while a resolution carried forward from an
    earlier applied merge is not labelled an attempt (the current conflict is
    separate) — in the CLI, the sign-off launch, the prompt and the return
    text; a resolved candidate pm has not applied says "Not applied" in the
    prompt even with no recorded apply error; the review, QA-planner,
    QA-interactive and QA-spec prompts, and the review window's diff pane,
    diff against the exact base the branch contains — the applied resolution,
    a newer `up_to_date` check, or the merge a clean bounce recorded — so the
    merged
    base commits never read as the PR's own changes; when the branch carries
    two bases (a resolution applied at sign-off, then a newer base merged by
    a later bounce), the review prompt, the sign-off prompt's "PR's own
    changes" line and the return text all name the *newest* one; a malformed
    `resolution` / `integration` / `signoff_return` / `signoff` value in the
    hand-editable project.yaml reads as absent across every surface
    (`resolution_of`, `resolution_entries`, `revision_of`, `_mapping`,
    `_as_list`): the sign-off and
    review prompts still render (no `AttributeError` out of prompt
    generation), a non-string `reviewed_head` in the return record is not
    sliced, `pm pr merge` refuses instead of raising (a non-mapping `signoff`
    record and a binding whose `base_sha`/`candidate_tree` is not a string are
    refusals, not `TypeError`s, and the router/driver reads the same
    mapping), `compact`/`_compact_resolution` drop non-mapping and non-string
    members, and `return_awaiting`/`open_return` still answer. A
    `resolution.paths`/`unresolved` value that is not a list (a hand-edited
    scalar) is no longer iterated at any reader (`resolution_entries`) — the
    prompt, the return text, the router, the merge gate, `summary`,
    `unresolved_paths`, the CLI and `_apply_resolution` all used to raise
    `TypeError` on it — while the "is this resolution unresolved?" checks
    stay conservative: a malformed value is still a refusal (it never grants
    a merge), and the message falls back to "unresolved conflicts recorded
    without details". A malformed member *inside* a well-formed entry (the
    four id lists, `records`, `path`/`resolver`/`blob`) reads as absent in the
    compact record instead of raising (`list(5)`) or splitting a string into
    characters (`list("abc")`). A `path` member that is not a string is not a
    path — and not a set member either: `unresolved_paths` collects only
    strings and the CLI / sign-off launch test membership on strings, so a
    hand-edited list/mapping `path` no longer raises `TypeError` (unhashable)
    out of `pm pr signoff integrate` and the launch. An unhashable
    `base_behavior_changes` member is carried, not dropped: the carry-forward
    de-duplicates order-preservingly and skips only the de-duplication for a
    value `dict.fromkeys` would have raised on (which took every integration
    check down, so the launch recorded nothing and the merge gate lost the
    evidence requirement). The same list can also carry a value YAML parses
    as a *non-JSON* type (an unquoted date, a `!!set`); writing the full
    record to `integration.json` renders it (`default=str`) instead of
    raising `TypeError` out of every check and the sign-off launch, which then
    reported only "Integration check failed" even though the state record had
    already been written. A non-string key inside a resolution's `records`
    map is not an action path and is dropped from the compact record (a
    mapping mixing YAML's int keys with pm's string paths made
    `_resolution_digest`'s `sort_keys` raise), and the digest itself
    normalises *every* mapping key to a string recursively, so the same mixed
    key inside a member the compact record carries as it is — `resolved_from`,
    an `unresolved` entry, a `records` value — is a stable hash instead of a
    `TypeError` out of `compact` (every recorded check, the sign-off launch)
    and out of the merge gate's digest comparison (`pm pr merge`). The
    normalisation leaves a well-formed resolution's digest byte-identical, so
    an approval already recorded against one stays valid. The
    delta pointer is one of those values: a non-string `resolution.diff_path`
    must not make `_carry_forward` call `Path(...)` on it (that raised out of
    every later integration check and the sign-off launch reported only
    "Integration check failed"), so it is dropped and the rest of the
    resolution's provenance is still carried. A *string* pointer is not
    enough to make the delta readable: a non-UTF-8 file raises
    `UnicodeDecodeError` and a null byte raises `ValueError` out of `open`
    (neither is an `OSError`), so reading the delta back tolerates both and
    the resolution is carried without it. A carry-forward
    of an already-bounded list also keeps its recorded total
    (`overlap_total`, `base_behavior_count`), so the prompt does not
    under-report "… N more" after the re-check. The sign-off launch stamp is
    another: `prepare` can return the *stored* record when a concurrent apply
    won, so `stamp_signoff_launch` receives a hand-editable `base_sha`; a
    non-string value stamps nothing instead of raising `TypeError` out of the
    launch before the sign-off window is created. The same stale record reaches
    the `integrate --apply` output, so the applied-merge line reads
    `base_sha` through `revision_of` (it printed with an empty revision
    instead of slicing an int). The GitHub recovery path
    (`pm pr merge --no-signoff-check` / `--propagation-only`) skips the merge
    gate, so it reads a non-string approved `sha`/`base_sha` as absent (no
    verification, not a crash) and `_verify_github_merge` renders every
    revision/tree through a short helper, so a hand-edited `candidate_tree`
    records the mismatch instead of raising `TypeError`.
    `pm pr show` — the reader `integration_pointer` tells a session to run —
    renders the overlap/conflict path lists through the same contract: a
    non-list `overlap`/`conflicts` (an int broke `len()`, a string was joined
    character by character) reads as absent instead of raising out of the
    command, and a list of non-strings renders through `str`. A non-mapping
    `integration` / `signoff_return` (or `applied` / the return's nested
    `integration`) is no record to print — `.get` on a scalar raised out of
    the command — so it reads as absent there too. The sign-off
    launch stamp is a sidecar file, not project.yaml, but the same rule
    applies to reading it: a non-UTF-8 stamp raises `UnicodeDecodeError` (a
    `ValueError`, not an `OSError`), so it reads as "no stamp" instead of
    taking every sign-off driver tick down. Two listings in the return text
    also name their real remainder instead of trimming silently: the
    behaviour-change line shows the first 10 and reports "… N more" from the
    record's total (`base_behavior_count` when `compact` bounded the stored
    list), and the coerced-conflict reason shows the first 5 and says
    "… N more".  ``build_return_record`` carries `base_behavior_count` beside
    its copy of the list (like `conflicts_total`/`overlap_total`), so the
    return block's marker reports the record's remainder and not just the
    bounded copy's.

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

## Integration with master: prompt bounding (pr-ace66e5, merged as #250)

The base this PR integrates contains pr-ace66e5, which bounds accumulating
prompt lists. Both behaviours are kept; neither side's intent is dropped.

- `pm_core/integration.py` gains master's `omitted_path_count` and
  `integration_pointer` alongside this PR's `resolution_diff_path`. The pointer
  is a *runtime-resolved* reference (`$(pm qa captures-path <pr>)/integration.json`
  or `pm pr show <pr>`), never a host path, so it survives the container
  boundary.
- The sign-off integration block (`prompt_gen._signoff_integration_block`) and
  the sign-off return (`signoff.format_signoff_return`) render the
  overlap/conflict path lists through `bounded_join` with
  `INTEGRATION_MAX_PATHS` / `INTEGRATION_LIST_BUDGET` and an omission marker
  that reports the *record's* remainder (`omitted_path_count` over
  `overlap_total` / `conflicts_total`). The `isinstance` list guards from R9
  are kept in front of every listing: a hand-edited non-list value is not
  evidence of a clean record and must not be iterated as characters.
- `signoff.build_return_record` carries `conflicts_total` / `overlap_total`
  into the return's `integration` block, together with this PR's `resolution`
  and `base_behavior_changes`.
- The base-range line in the sign-off block keeps this PR's
  `base_range_from` / contained-base logic (the range starts at the applied
  base once the base is inside HEAD); master's simpler `merge_base` line is
  not used.
- `prompt_gen._signoff_qa_scenarios_parts` returns a `(head, listing)` tuple on
  master; this PR's non-dict `qa_status.json` guard is re-applied in tuple
  form (`("…malformed…", "")`) so malformed evidence is reported instead of
  raising `AttributeError`.
- The sign-off prompt still goes through `_assemble` / `fit_prompt`, and only
  enumerations are abbreviated (never instructions). This PR's new prompt
  content is accumulation and stays bounded: the resolution `paths` list has
  one entry per auto-resolved *file* (in practice a single
  `pm/project.yaml`) with each id list capped at 10 in the prompt, the
  behaviour list is capped at 20 with an `… N more` line, and the evidence
  block is a fixed few lines. Worst-case size therefore stays well inside
  `PROMPT_ARG_LIMIT`; if a large PR pushes the whole prompt over anyway, the
  launcher's file-backed delivery still carries every instruction intact.
