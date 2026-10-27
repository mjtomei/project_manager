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
  different — that is pm's own TUI cursor, and the resolver now merges it to
  the **new base's** value instead of refusing (see R6). A branch that never
  ran pm (a hand-built fixture with no `active_pr` anywhere) therefore no
  longer reproduces the real shape; use pm on both sides, or set different
  cursors by hand. Also sync the PR branch with master before committing the
  branch-side record, because `pm pr start` records the workdir state after
  cloning.
- The branch now contains `master@211a6128` (merged as 7f603144) and the
  "behind master" warning in older notes no longer applies. Scenarios 13-17
  PASSed at 481644d5; since then the re-run pointer, the `pm pr show`
  resolution rendering and the `active_pr` merge landed, so those are the new
  surfaces to exercise (plus the prompt-bounding merge from #250).
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
`pm/project.yaml`. The merge is committed only if its tree equals the
recorded candidate tree; a different result (a merge driver, or a branch that
moved under the check) is aborted with a reason and nothing is committed.
Two applies racing on the same workdir are serialized: the branch gains one
merge commit, and the invocation that lost reports the branch's current
integrated state — not a merge failure — while keeping the applied
resolution visible.

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
not write. The CLI labels every path of a failed attempt as `attempted … NOT
resolved` (never `resolved`), and a resolution carried forward from an
earlier, already-applied merge is labelled as earlier/already applied — the
conflict the record now reports is a separate, current problem.

The one field-level exemption is pm's own UI state: `project.active_pr` is the
TUI's selected PR, rewritten by pm on every cursor move, so any branch where
someone used pm differs from the base there. Both sides changing it merges to
the new base's value (deterministically, and the branch value is not counted
as a lost change), the same class as the bookkeeping timestamps. That
exemption covers only that one path: a real `project` field changed on both
sides (e.g. `hide_merged`, `skip_qa`), a deleted-vs-edited `active_pr`, and
every real record field conflict still refuse.

### R7. A clean merge with behavioural base changes is not an exemption
GIVEN a base that merges cleanly but changed behaviour-relevant configuration
(`project.model_config`, `skip_qa`, PR `status`/`depends_on`/`model`, plan
status, `pyproject.toml`, CI workflow) since the PR branched.
WHEN the user runs the sign-off check and the agent writes a MERGE report
without an evidence/checks statement.
THEN the check reports `clean` plus the behavioural changes, the report is
refused at record time and the merge gate refuses without the statement; with
a targeted-checks or reuse statement the approval is accepted.

The same requirement survives the base moving *inside* the branch. Once a
clean base is merged by a bounce, or implementation reconciles a conflicted
base by hand, the next check's own base diff is empty (the base is an
ancestor of HEAD) — but the base's behaviour-relevant changes, the changed
file count and the overlap must still be shown, and the evidence/checks
statement still required, including after a later benign re-check replaces
the record. A summary pm could not compute is not an exemption either.

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
the PR diff include merged base commits. The review window's diff pane (and
the prompts that name the PR diff) use the exact base the branch contains —
the newest one when the branch carries more than one — so the pane's change
summary and full diff show only the PR's own changes, not the base merge.

### R10. A re-run after a refused merge says why it is running again
GIVEN a PR whose recorded SIGNOFF_MERGE approval the merge gate invalidated
because the base moved (the driver retires the record and relaunches
sign-off).
WHEN sign-off is launched again.
THEN the instructions pm hands the sign-off agent name the refusal reason, the
previous verdict and the revision it approved, and point at the previous
`$CAP/report.html` as readable and reusable — and that report is still on
disk, unchanged. The block is emitted only while the PR's own changes are
unchanged since that approval: pm may have merged the base into the branch
without that being PR work, so "unchanged" means the check head equals the
approved revision or the applied resolution's pre-apply head (with the applied
merge still the checked revision). Real PR work after the refusal, and an open
sign-off return (a bounce, which writes `signoff_return` and overwrites the
report), never emit it. A new recorded verdict clears the marker.

### R11. `pm pr show` is a complete reader for the resolution
GIVEN a PR with a recorded integration check — resolved and applied,
resolved but unapplied, attempted-and-unresolved, or a carried earlier
resolution.
WHEN the user runs `pm pr show <pr>` (the reader every abbreviated prompt
points at).
THEN the integration section names the candidate tree, per-path resolution
lines with the ids added from each side (saying how many the record omits),
the unresolved conflicts, the applied merge (or "not applied to the PR
branch"), the resolution digest, the delta file's basename, and a full-record
pointer that resolves to `integration.json`. The delta and the full record are
readable, the per-path labels match the outcome (`Resolved`,
`Resolution attempted (NOT resolved)`, `Resolved earlier (already applied)`),
and a hand-edited record (non-list overlap, non-mapping integration) reads as
absent instead of crashing the command.

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
- GIVEN both branches used pm, so `project.active_pr` differs on each side.
  WHEN the user resolves the integration. THEN the candidate carries the base's
  cursor value and the branch's value is not reported as a lost change.
- GIVEN a hand-edited `project.yaml` (the file people resolve by hand): a
  non-JSON value such as an unquoted date or a `!!set` in a carried list, a
  non-string path in a resolution entry, a numeric mapping key, or a duplicate
  id inside a nested list. WHEN the user checks, records, shows and merges.
  THEN each reads as absent or refuses readably — never a traceback, and never
  an integration check that silently records nothing (the evidence statement
  must still be required).
- GIVEN the recorded resolution delta file is unreadable (binary, or a path
  with a null byte). WHEN a later integration check or sign-off launch runs.
  THEN the provenance is still carried, the delta reads as absent, and the
  launch does not fail with a bare "Integration check failed".
- GIVEN an approval invalidated by the merge gate and a fresh sign-off run.
  WHEN the user reads the relaunched sign-off instructions, then adds a real
  PR commit and relaunches. THEN the first names the previous verdict/revision
  and the preserved report; the second no longer claims the PR is unchanged.

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
- Whether the "why sign-off is running again" pointer is assertable: it is
  prompt text, so capture the generated sign-off prompt artifact (a stub
  `claude` ahead on PATH that records its argv, as scenario 12 documented),
  and cross-check the user-visible consequences: the preserved
  `$CAP/report.html`, the invalidated/stale reason in `pm pr show` and the
  TUI, and the merge refusal.
