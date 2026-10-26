# pr-5cee3d5 — QA spec: resolve integration conflicts at sign-off, reuse evidence

Scope: the user-visible sign-off integration flow — `pm pr signoff integrate`,
the sign-off launch (`pm pr signoff`), the sign-off record/approval
(`pm pr signoff record`), the merge gate and publication (`pm pr merge`), and
the TUI sign-off/merge surfaces. The change replaces "a metadata-only
`pm/project.yaml` conflict can only route SIGNOFF_IMPL" with: resolve it by
record id in an isolated candidate, apply it to the PR branch, let the agent
choose the return stage (impl/review/QA/merge-only), and require an explicit
reuse statement before a merge-only approval of a resolved or
behaviourally-changed base.

## Setup (cross-cutting, as user steps)

1. Install this PR's pm (`pip install -e .` or `./install.sh --local`), point
   `PYTHONPATH` at the checkout, and confirm `pm which` names it.
2. Create a throwaway git project (`git init`), `pm init --backend local
   --no-import`, and add one PR (`pm pr add "..."`) — note its id/branch.
3. Create the PR branch in the main repo with the PR's own changes (code
   files plus appended `pm/project.yaml` records/notes), then create the PR's
   workdir the way pm normally does (start the PR, or provision the workdir
   clone on the branch and let pm record it). The main repo's `master` is the
   integration target for the local backend.
4. On `master`, commit the "colleague" side: other independent PR records /
   notes appended to `pm/project.yaml`, and optionally behavioural config
   changes (`model_config`, statuses, `depends_on`, `pyproject.toml`,
   `.github/workflows/...`).
5. Record review/QA evidence for the PR's pre-merge revision (run the review
   and QA loops with the bundled fake, or place the evidence files under
   `~/.pm/workdirs/qa/<pr>-*/`), so the sign-off report can reuse it.
6. A session tag must resolve (run from the project git repo) so captures
   land under `~/.pm/sessions/<tag>/captures/<pr>/` (`$CAP/<pr>/`):
   `integration.json`, `integration-resolution.diff`, `report.html`.
7. Where a scenario needs the sign-off agent's decision, act as that agent:
   read the captures/diff, write `report.html` with the `pm-signoff-*` meta
   tags, then run `pm pr signoff record`. With fake-claude configured for the
   `signoff` session type, `pm pr signoff` can also be driven end to end.

Reproduction traps (from the prior QA runs — avoid rediscovering them):
- Local backend: put the real git binary ahead of any QA wrapper in `PATH`
  (`export PATH=/usr/bin:/usr/local/bin:/bin:/usr/sbin:/sbin`), or the fetch
  fails with "does not appear to be a git repository" and the record gets
  `base_sha: null`.
- Building the #250 shape: `pm pr add` on both sides leaves `project.active_pr`
  different, which the resolver correctly reports as a real conflict. Run
  `pm pr select <target-pr>` on each side before committing. Also sync the PR
  branch with master before committing the branch-side record, because
  `pm pr start` records the workdir state after cloning.
- Use `--record` when the scenario needs `integration.json` and the resolution
  delta on the PR/captures; a plain check after `--apply` prints only
  "up to date". The read-only check still writes the delta its output names.
- Drive loops/verdicts with the fake-claude stand-in (see the TUI instruction)
  so a scenario never waits on a real model.

## Requirements (Given / When / Then)

### R1. Metadata-only conflict is resolved by record id, visibly and read-only
GIVEN a PR in `sign_off` whose branch and `master` each independently appended
distinct PR records (and notes) to `pm/project.yaml`, with no other conflict.
WHEN the user runs `pm pr signoff integrate <pr>`.
THEN the result is `resolved` (not `conflict`), the summary names
`pm/project.yaml` and how many records came from the PR vs the base, the
output lists each added/merged record id and the resolution delta file (the
candidate tree is recorded on the PR/captures by `--record` and named by the
sign-off prompt), and the PR workdir's HEAD/branch/index and unrelated files
are unchanged (the check is read-only).

### R2. The resolved candidate is applied to the PR branch before sign-off
GIVEN the resolved check above.
WHEN the user runs `pm pr signoff integrate <pr> --apply` (or launches
`pm pr signoff <pr>`).
THEN the PR branch gains a merge commit containing the fetched base, the
record becomes up to date with the resolution provenance carried forward
(`applied_merge_sha`, the pre-apply head/base/merge-base, the resolution
digest), and every record from both sides is present in the branch's
`pm/project.yaml`.

### R3. All independent records survive publication
GIVEN the applied, resolved candidate.
WHEN the user approves it and runs `pm pr merge <pr>`.
THEN the merge publishes the exact approved candidate, the base branch's
`pm/project.yaml` contains all records/notes from both sides, and the PR is
marked merged.

### R4. A fresh, candidate-bound sign-off is still required
GIVEN a resolved and applied candidate with review/QA evidence from the
pre-merge revision.
WHEN the user writes a sign-off report without the candidate tag (or with the
wrong candidate) and records `SIGNOFF_MERGE`, or tries to merge without a new
sign-off record.
THEN `pm pr signoff record` refuses with a message naming the missing/incorrect
`pm-signoff-candidate` (and the evidence/checks statement), and `pm pr merge`
refuses without a fresh bound approval.

### R5. Explicit reuse is recorded and required
GIVEN a resolved/behaviourally-changed candidate and a report naming the
approved candidate tree, the reused stages/revisions (`pm-signoff-evidence` +
`pm-signoff-evidence-reason`) or targeted checks (`pm-signoff-checks`).
WHEN the user records `SIGNOFF_MERGE`.
THEN the approval is accepted and the PR's sign-off record shows the reviewed
head, the resolution's pre-apply revisions, the candidate tree, the QA
evidence revision/overall and (when inferable) the review revision, the prior
sign-off decision if any, the required return stage, and the reuse statement.
The recorded block attributes a candidate tree / resolution only when the
stored integration check describes the reviewed HEAD, and an applied
resolution's provenance survives a transient failed re-check (the record never
silently drops the explicit-reuse requirement).

### R6. Unsafe conflicts are never auto-resolved
GIVEN a conflict that is not a pair of independent additions — both sides
changed the same field of one record differently; one side deleted a record
the other edited; the same id was added on both sides with different content;
duplicate ids (including two records sharing an id inside a nested list, even
when that list is otherwise carried wholesale); a malformed record value (a
non-string status/parent, a record that is not a mapping); or a conflict
outside `project.yaml`.
WHEN the user runs `pm pr signoff integrate <pr>` (with or without `--apply`).
THEN the result is `conflict`, the resolution attempt (if any) is reported as
unresolved with the specific conflicts, no merge is applied, the workdir is
untouched, and a sign-off MERGE is coerced to `SIGNOFF_IMPL`. A malformed
value produces the same readable conflict rather than a traceback, and a
resolution pm could not reconcile is described as such ("pm could not
reconcile it", with the unresolved conflicts listed) — never as a successful
metadata resolution — and records no resolution delta path for a file it did
not write.

### R7. A clean merge with behavioural base changes is not an exemption
GIVEN a base that merges cleanly but changed behaviour-relevant configuration
(`project.model_config`, `skip_qa`, PR `status`/`depends_on`/`model`, plan
status, `pyproject.toml`, CI workflow) since the PR branched.
WHEN the user runs the sign-off check and the agent writes a MERGE report
without an evidence/checks statement.
THEN the check reports `clean` plus the behavioural changes, the report is
refused at record time and the merge gate refuses without the statement; with
a targeted-checks or reuse statement the approval is accepted.

### R8. A dirty workdir cannot be approved; a later bounce can apply it
GIVEN a resolved candidate and a PR workdir with uncommitted changes.
WHEN the user launches sign-off (or `--apply`).
THEN the resolution stays in the isolated candidate (`resolved` with a "not
applied" reason), the branch is untouched, and a MERGE is blocked with a
message telling the user to clean the workdir; after cleaning, a bounce to
review/QA applies the same resolution and the next stage is told to verify the
integrated result and diff against the applied base.

### R9. Preservation
GIVEN unrelated dirty/untracked files in the PR workdir or main repo and
existing captures/QA evidence.
WHEN the user resolves, applies and merges.
THEN those files and evidence files are preserved, and no stale base ref makes
the PR diff include merged base commits.

## Edge cases (Given / When / Then)

- GIVEN the base moved after the applied resolution but before merge. WHEN the
  user runs `pm pr merge`. THEN the merge is refused, the approval is
  invalidated, and the PR returns to sign-off (no new resolution in the merge
  step).
- GIVEN the agent committed to the PR branch after the applied resolution.
  WHEN the user merges. THEN the stale approval is refused and sign-off must
  re-run on the new head.
- GIVEN a re-check recorded another HEAD or another candidate tree. WHEN the
  user merges. THEN the gate refuses, naming the mismatch.
- GIVEN a re-check that failed and left no candidate tree. WHEN the user
  merges a clean approval. THEN the refusal says pm cannot confirm the
  candidate (not that report.html is at fault).
- GIVEN the approved head is already contained in the base (an interrupted
  publication). WHEN the user merges. THEN the recovery path finalizes it
  instead of returning to a blocked sign-off.
- GIVEN a report edited after approval. WHEN the user merges. THEN the
  content-hash check refuses.
- GIVEN both sides bumped only bookkeeping timestamps on a record they each
  edited. WHEN the check runs. THEN the record merges (later timestamp wins)
  and a real field conflict on the same record still refuses.
- GIVEN a `--no-resolve` check on a metadata conflict. WHEN it runs. THEN it
  reports a plain conflict and offers no resolution.
- GIVEN the same base change appears on both sides. WHEN resolved. THEN it is
  still recorded as a resolution (candidate required) even with an empty
  delta.
- GIVEN malformed `qa_status.json`. WHEN a sign-off verdict is recorded. THEN
  the record is written with whatever evidence is readable (including the
  revision from a valid `qa_resume.json`) and does not crash.
- GIVEN a base that changed 21-30 behaviour-relevant settings (or more). WHEN
  the user launches sign-off. THEN the sign-off window opens and the
  integration surface lists the changes (with a "… N more" note when the list
  is long) instead of the launch failing.
- GIVEN a metadata conflict whose resolution failed or was superseded. WHEN
  the user runs `pm pr signoff integrate --record`. THEN the recorded
  `integration.json` does not point at a delta file that was never written,
  and the output names the unresolved conflicts.

## Pass / Fail criteria

- Pass: every Then above is observable on the user surface (CLI output,
  project.yaml/sign-off record, captures, git history, TUI), unsafe conflicts
  are never silently resolved, a resolved/behaviourally-changed MERGE always
  carries an explicit reuse/checks statement bound to the reviewed head and
  candidate, and no step loses a record, a dirty file, or existing evidence.
- Fail: any conflict auto-resolved against policy, a merge without the
  required statement, a resolution applied that does not equal the recorded
  candidate, a stale base/head/candidate still merging, a lost record or
  evidence file, a merge step making a new resolution, or a crash from
  malformed evidence.

## Ambiguities resolved

- Whether a resolved candidate may be approved without another review/QA pass:
  yes, but only with an explicit reuse/checks statement; PM records the
  decision and the merge gate enforces it.
- Whether the review revision is always recorded: PM records it only when QA
  exercised that revision and committed nothing; otherwise it states it does
  not record the review revision (no invented provenance).
- Whether the sign-off prompt text is directly assertable: treat the prompt as
  internal; verify the decision surface it produces (the agent's report, the
  recorded evidence block, and the launch's integration/resolution output).
- Whether a metadata-only resolution should be applied by the merge step:
  no — it is applied at sign-off; the merge step recomputes without
  resolution and refuses a different candidate.
