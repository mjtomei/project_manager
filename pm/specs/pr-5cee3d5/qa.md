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
8. For the GitHub-backend surfaces (R15): inside the project's pm session,
   seed a git-backed stand-in with `pm fake-github config set '<json>'`
   (`{"prs":[{"head":"<branch>","title":"...","files":{...}}]}`). It creates a
   real remote at `~/.pm/sessions/<tag>/fake-github/remote.git`; point the
   project at a clone of it and `pm init` with `--backend github` (or set
   `project.backend: github` and `project.repo` to that clone). Every `gh`
   call pm makes in that session — including a freshly spawned `pm pr ...` —
   is served by the fake. The stand-in's on-disk registry
   (`~/.pm/sessions/<tag>/fake-github/state.json`) holds a `prs` list with each
   PR's `state`; the git remote is an ordinary repo, so "a teammate merged on
   GitHub" is `git -C <remote.git> merge --no-ff <branch>` (after pushing any
   extra commit to `<branch>`) followed by flipping that PR's `state` to
   `MERGED` in `state.json`. That is exactly the merge the sync paths must
   detect; do not re-seed with `config set` for this (a re-seed adds a second
   PR record rather than transitioning the first).

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
- The branch now contains `master@89e3c501` (merged as b2d1a15c, after the
  earlier hand merge of `master@450a6362` as 363ec8b8). Both merges were made
  **by hand** (`git merge`, no pm `--apply`), so no applied-resolution record
  exists; a check reports `up to date` with an empty base diff and the
  base-interaction summary must be carried forward from the earlier conflict
  check (R7, `base_range_from`) or the evidence requirement silently
  disappears. That post-merge state still needs coverage.
- The `master@89e3c501` merge is the main new surface for scenarios 39+: master
  (pr-2e06289) moved the GitHub-merge verification out of `pm_core/cli/pr.py`
  into a new shared `pm_core/merge_integrity.py` (also called by the TUI
  background/startup sync and `pm pr sync`). The merge took master's structure
  and **ported this PR's hand-edited-state guards** into it, so the reconciled
  module — not the old inline copy — is what every publisher, recovery and
  sync path now runs (see R15). The rest of master's churn in the overlapping
  files (sign-off launch env plumbing, the `--wait-for-merge` autostart policy,
  push-proxy/container changes) came in with the same merge.
- Scenarios 13-17 PASSed at 481644d5 and QA 18-23 PASSed at 25fb1918 (the
  re-run pointer, `pm pr show` resolution rendering, the real #250 shape,
  bounded evidence, concurrent operators, hostile project.yaml). Scenarios
  27-32 PASSed at 91011ee4 (hand-reconciled integration, merged-base
  behaviours, concurrent operators, publication guards, the resolver at the
  user surface, the TUI decision surface). Scenario 28's one finding — a
  killed window lingering in the pane registry — was fixed in 9f930e5f.
- Since 91011ee4 the branch has gained ~40 review-loop commits that are the
  main new surface for scenarios 33+: the hand-edited-state contract across
  the readers and writers of `pm/project.yaml` (non-string
  description/workdir/signoff, scalar depends_on, malformed notes; the
  note/dependency *write* paths too), `pm pr note add/edit/delete` keeping
  note ids unique, `pm pr edit`'s lossless template round-trip (unicode,
  markdown headings, untouched and unrepresentable notes), the sign-off
  evidence block + approved base in `pm pr show`, the base-tag check on a
  MERGE approval, the apply candidate-tree equality guard and `_repo_lock`
  serialization, and carrying the base assessment across a failed re-check.
- The hand base merge above also brought the base's own behaviours into
  overlapping code (`pm_core/cli/pr.py`: the `pr_start` session-aware message
  and the `pr_qa_run_bg` runtime-state mirror; plus grouped-session window
  selection in `pm_core/tmux.py`, pane registration, and the TUI popup
  picker). `pm_core/cli/pr.py` is the one code file both sides changed and Git
  merged cleanly — exercise both sides' behaviour together, plus the PR's own
  sign-off code calling into the base's changed tmux/pane-registry helpers.
- Building the "base already merged by hand" fixture: record the conflicting
  check first (`--record` or a sign-off launch), then in the PR workdir
  `git fetch` and `git merge <base>` by hand keeping both sides' records and
  committing. Do **not** use `--apply` for this fixture — that records an
  applied resolution and exercises the other carry path (`_carry_forward`'s
  verified branch), not the hand-reconciled one.
- Use `--record` when the scenario needs `integration.json` and the resolution
  delta on the PR/captures; a plain check after `--apply` prints only
  "up to date". The read-only check still writes the delta its output names.
- Drive loops/verdicts with the fake-claude stand-in (see the TUI instruction)
  so a scenario never waits on a real model.
- After scenarios 39-43, six more commits landed (review-loop 0c92 i1/i2 and
  7a43 i1, plus the scenario-40 sync fix): the hand-edited-state contract now
  also covers the recorded *verdict member* (a dict/list `verdict` reads as
  absent in `pm pr list`/`pm pr show`, the home-window PR list, the tech tree
  and the runs-popup status snapshot), the approval's `integration.target_repo`
  (a non-string is a different repository — a refusal, not a `Path(5)`
  traceback out of `pm pr merge`), `project.base_branch` at the review-window
  launch (a non-string falls back to the default branch instead of killing the
  window), and `pm pr list --timestamps` sorting a hand-edited unquoted date.
  Scenario 40's story 5(b) also produced a real fix: `pm pr sync` (and
  `pm_core/pr_sync.sync_prs`) now falls back to the project repo when every
  workdir is gone, so a deleted workdir can no longer turn a bad merge into a
  silent finalize.
- Fake-github harness facts (from scenarios 40/43): the stand-in's session tag
  derives from the git-root basename, so re-running a fixture in the same
  directory reuses the stand-in (and may already contain the PR head); use a
  fresh dir name per run or delete `~/.pm/sessions/<tag>`. The binding the
  check compares is `signoff.integration.candidate_tree`, not the top-level
  `pr["integration"]["candidate_tree"]`. With the TUI killed the tmux server is
  gone, so provision the workdir with `pm fake-claude config set '{"_all": {}}'`
  first. The local `master` must be an ancestor of the stand-in's base before
  `--propagation-only` can fast-forward.

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
the record. A summary pm could not compute is not an exemption either. The
carried summary lives on the *recorded* check (the sign-off launch, or
`pm pr signoff integrate --record`); a read-only preview writes no state and
therefore prints the bare `up to date` result — read `integration.json` or
the launch output for the carried evidence, and judge the exemption at the
merge gate, which reads the record.

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
- GIVEN a base the implementation merged by hand (pm could not apply the
  conflict, so no applied-resolution record exists). WHEN the user re-checks
  and launches sign-off. THEN the check reports `up to date` but still names
  the base-changes range, the changed-file count, the overlap and the
  behaviour-relevant changes, and a MERGE still requires the reuse/checks
  statement.
- GIVEN the branch and base both appended records and the base additionally
  changed a project-level behavioural setting inside the same conflicted
  `project.yaml`. WHEN the conflict is resolved. THEN the candidate carries
  the base's value for that setting, the resolution delta shows it, and it is
  listed among the base's behaviour-relevant changes.
- GIVEN a branch that contains the base (a hand merge). WHEN the user opens
  the review window or reads a prompt that names the PR diff. THEN the diff
  shows only the PR's own changes, not the base merge's files.
- GIVEN a resolved candidate and a PR branch that moved since the check (or a
  merge driver that changes the merge result). WHEN the user applies. THEN the
  apply aborts with a reason naming the mismatch, no merge commit is created,
  and the workdir HEAD/index is unchanged.
- GIVEN a transient base-fetch failure (an `error` check) after the branch
  already contains the base, followed by a successful re-check. WHEN the user
  launches sign-off. THEN the earlier base assessment (changed-file count,
  overlap, behaviour-relevant changes) is still carried and a MERGE still
  requires the reuse/checks statement — no silent exemption.
- GIVEN a base that changed 21-30 (or more) behaviour-relevant settings. WHEN
  the user launches sign-off. THEN the window opens and lists them with a
  "… N more" note instead of the launch failing.

### R12. PR metadata editing is lossless; note writes preserve hand-written state
GIVEN a PR whose title/description contain an apostrophe, `--`, a unicode dash
and markdown headings, and notes added through pm.
WHEN the user opens the PR in the edit template and saves without changing
anything.
THEN the stored title/description/notes are unchanged (no en-dash/em-dash
laundering, no "description updated"), every note keeps its id and
`created_at`, and `pm pr show` / `pm pr note list` show the same content.

GIVEN notes the template cannot render on one bullet line (a multi-line text, a
text ending in a timestamp-looking suffix, an empty text without `created_at`)
and a note member that is not a mapping.
WHEN the user edits one other note and saves, then runs `pm pr note add/edit/
delete`.
THEN each untouched/unrepresentable note survives exactly once (not dropped,
not duplicated as a fragment), malformed members are preserved verbatim, and no
command raises a traceback.

GIVEN a note whose text the editor's ASCII substitution makes structural — a
continuation line starting with a unicode en dash (`– beta`, which the template
renders as a real `- beta` bullet) and a text ending in an en-dash timestamp
suffix (`2020–01–01T00:00:00Z`, which becomes a strippable timestamp) — with no
`created_at`.
WHEN the user opens the edit template and saves without changing anything.
THEN no note is created, dropped, truncated or given a new id: both notes
survive exactly as stored, and the command reports no changes.

GIVEN a PR.
WHEN the user adds the exact same note text twice, including two simultaneous
adds from separate terminals.
THEN the notes get distinct ids, `pm pr note list` shows both, `pm pr note
delete <one id>` removes only that one, and a later metadata-conflict
resolution still succeeds (the resolver refuses a duplicate id).

### R13. Hand-edited project.yaml is tolerated by every reader and prompt launch
GIVEN a PR with a non-string description (an unquoted date), a non-string
`workdir`, a scalar `depends_on`, a scalar `signoff` record, and a `notes` list
holding a non-mapping member.
WHEN the user runs `pm pr list`, `pm pr show`, `pm pr note list`, opens the TUI
home/tree, and launches sign-off (plus the impl/review prompts).
THEN each reads the bad values as absent (or `?` for a note), the tree does not
crash, and the session window opens instead of the launch failing.

GIVEN an integration record with a hand-edited shape (a non-mapping record, a
non-list overlap, a non-string resolution path, a malformed `unresolved`
value).
WHEN the user runs `pm pr show` and `pm pr merge`.
THEN the malformed parts read as absent, the per-path labels stay honest, and
the merge gate still requires the evidence statement — never a traceback.

GIVEN an integration record whose hand-edited `unresolved` is a *list* of
non-mappings (a list of strings, or of mappings with no string `path`).
WHEN a routine integration re-check rewrites the record, then the user runs
`pm pr show` and `pm pr merge`.
THEN the value survives the rewrite (the record still refuses), every recorded
path is labelled an attempt (never "resolved"), and no approval or merge is
granted.

GIVEN a `project.yaml` carrying a duplicate id inside a nested list, or a
duplicate note id hidden behind a malformed member.
WHEN the user runs `pm pr signoff integrate`.
THEN the result is `conflict` naming the duplicate, and no merge is applied.

### R14. The approval's provenance is visible and bound to the base it assessed
GIVEN an applied resolved candidate with a recorded MERGE approval.
WHEN the user runs `pm pr show`.
THEN the Sign-off section shows the verdict, approved head, approved base
(`branch@sha`), reviewed head, candidate tree, reused evidence with its reason
(or targeted checks) and required return stage, and the Integration section
names the candidate tree and the applied merge.

GIVEN a report that names the correct candidate but another base (or omits /
mistypes the candidate tag).
WHEN the user records MERGE or runs the merge.
THEN the record/merge is refused with a message naming the mismatch, and no
approval is written.

GIVEN a metadata conflict whose resolution failed or was superseded.
WHEN the user runs `pm pr signoff integrate --record`.
THEN `integration.json` names no delta file that was never written, the output
lists the unresolved conflicts, and `pm pr show` labels the attempt
`Resolution attempted (NOT resolved)`.

GIVEN a carried resolution whose delta file is unreadable (binary or a null
byte in the path).
WHEN the user launches sign-off.
THEN the launch succeeds, the provenance is still shown, and the delta reads as
absent — no bare "Integration check failed".

### R15. Every discovered or recovered merge is checked against the signed-off candidate
GIVEN a github-backend PR holding a bound `SIGNOFF_MERGE` (approved head,
signed-off base, candidate tree), and a merge that GitHub published from a
branch carrying a commit made after sign-off.
WHEN the user runs `pm pr sync` / `pm pr sync-github` (or the TUI's
startup/background sync discovers the merge), or recovers it with
`pm pr merge --propagation-only`.
THEN the PR is finalized as merged, a warning names the published merge, the
approved head it did not carry and the base branch, the PR records
`merge_integrity` with that problem, and a `Merge integrity: …` note appears
exactly once on the PR (a second sync or recovery adds no second note).
`pm pr note list` / `pm pr show` show the note.

GIVEN the same PR and a merge GitHub published of exactly the signed-off
candidate.
WHEN the user syncs or recovers.
THEN the PR is finalized as merged with no warning, no `merge_integrity`
record and no note.

GIVEN a PR merged on GitHub with no bound approval (no sign-off record, or a
legacy HEAD-only `SIGNOFF_MERGE`).
WHEN the user syncs or recovers.
THEN the PR is finalized as merged and nothing is recorded — there is no
candidate to compare against, and no invented mismatch.

GIVEN the check cannot run — the base cannot be fetched or read, or the PR's
own workdir is gone.
WHEN the user syncs.
THEN the PR is still finalized as merged, a "could not verify" warning says
so, and nothing is recorded on the PR (unknown is not a mismatch). With the
workdir gone the check still runs from the directory the sync used (another
workdir, or the project repo), so a bad merge is still flagged.

GIVEN an approval whose stored state was edited by hand (a scalar `signoff`,
a non-string `sha`/`base_sha`/`candidate_tree`, a note member that is not a
mapping or whose id is a list).
WHEN the user syncs, recovers or publishes.
THEN the command completes without a traceback: the malformed approval reads
as absent (verification skipped), or the mismatch is recorded with the
unreadable value rendered as `?`; hand-written notes are preserved and the
warning note is still added once.

GIVEN a merge that is not in the base yet.
WHEN the user runs the recovery path (`--propagation-only` /
`--no-signoff-check`).
THEN it refuses, says the PR's HEAD is not in the base, and points back at
`pm pr signoff` → `pm pr merge`; nothing is finalized.

GIVEN every PR workdir is gone and the project repo is the only directory the
sync can use.
WHEN the user runs `pm pr sync` after a teammate merged on GitHub.
THEN the merge is still detected and checked against the signed-off candidate
from the project repo — a bad merge is warned about and recorded, a good one is
silent — instead of "No workdirs found" exiting 1.

### R16. Hand-edited members of the sign-off record and the launch state
GIVEN a PR whose recorded `signoff.verdict` was hand-edited to a mapping or a
list (a person editing `project.yaml` by hand).
WHEN the user runs `pm pr list` / `pm pr show`, opens the TUI home window and
tech tree, and opens the runs/status popup.
THEN every surface renders the PR without a traceback, shows no sign-off
verdict (no icon, no decision), and the status snapshot says no verdict rather
than routing the mapping as a stale decision. A real string verdict still
shows its icon and routes normally.

GIVEN an approval whose `integration.target_repo` was hand-edited to a
non-string.
WHEN the user runs `pm pr merge`.
THEN the merge is refused readably as a target-repository change, the PR
returns to sign-off, and nothing is published — never a traceback out of the
command.

GIVEN `project.base_branch` hand-edited to a non-string.
WHEN the user launches the review window (local backend).
THEN the window opens, the diff pane uses the default base, and the pane shows
only the PR's own changes.

GIVEN `project.base_branch` hand-edited to a non-string (an int, or an empty
string) on a PR whose branch does not already contain a base.
WHEN the user runs `pm pr spec <pr> qa` (or inspects the QA spec prompt it
builds).
THEN the diff instruction names the default base (`git diff master...HEAD`),
not the hand-edited value — the same fallback the review window's diff pane
uses — and no command interpolates the malformed value.

GIVEN PRs whose `updated_at` was hand-edited to a YAML date (an unquoted date)
alongside PRs with pm's ISO strings.
WHEN the user runs `pm pr list --timestamps`.
THEN both rows render, newest first, without a comparison error.

GIVEN a sign-off return whose integration snapshot has a null (or non-string)
`base_branch` and no usable `base_sha`.
WHEN the routed step's prompt is built.
THEN the "Reconcile it in this branch" instruction says `git merge <base>`, not
`git merge None` (or a mapping's repr), and a real branch name is still named
as before.

GIVEN a conflicted integration whose `base_branch` was hand-edited to a
non-string.
WHEN sign-off routes a MERGE/REVIEW/REQA verdict to implementation.
THEN the recorded coercion reason says `merging ?@<sha>`, never the malformed
value, and the return text carries it verbatim.

GIVEN the stored `integration.base_sha` hand-edited to a non-string (an int, a
mapping, a list, a boolean) on a PR whose apply loses a race and `prepare`
re-checks the revision the branch now has.
WHEN sign-off launches (`pm pr signoff`, or `pm pr signoff integrate --apply`).
THEN the re-check names the base it actually fetched (the ordinary fetch runs)
and records its real status — never a `TypeError` out of the check.

GIVEN a PR whose `title` was hand-edited to a non-string (an int, a mapping, a
list, a boolean) or to text spanning two lines.
WHEN the user opens it in the edit template and saves without changing
anything.
THEN the stored title is unchanged (not rewritten as a string, not truncated
to its first line), the command reports no changes, and a save that *does*
edit the title still applies the new value.

GIVEN an `integration.resolution.unresolved` entry whose `conflicts` is
missing, `null` or an empty list.
WHEN the user runs `pm pr signoff integrate`, `pm pr show`, launches sign-off,
or a verdict is coerced to `SIGNOFF_IMPL`.
THEN every surface names the entry's file and says "unresolved conflicts
recorded without details" — never the literal `None` — and the sign-off
prompt's target/head lines show `?` for an absent value rather than `None`.

GIVEN `pm/project.yaml` carrying an unquoted `.nan` (which YAML parses to
`float('nan')`) on a record the PR branch and the new base both leave
untouched, alongside independent record additions on each side.
WHEN the integration check resolves the metadata conflict.
THEN the document resolves and both sides' additions survive (an identical
`.nan` is not a change); a `.nan` changed to a different value is still a
conflict.

GIVEN `qa_resume.json` whose `planner_code_changes` is a *present* `null`
(pm always writes the key as a list).
WHEN a sign-off verdict is recorded.
THEN the evidence block carries the `planner_code_changes_error` marker and no
review revision is inferred — while an *absent* key still allows the
documented inference.

## Edge cases (Given / When / Then)

- GIVEN a hand-edited non-string verdict and a clean integration check. WHEN the
  user launches sign-off. THEN the window opens and pm does not treat the
  malformed value as a prior decision (no invented prior verdict/revision).
- GIVEN an integration record whose `base_files_count` (or a resolution id
  count) was hand-edited to YAML `.inf` (an unquoted non-finite float). WHEN
  the user runs `pm pr signoff integrate`, `pm pr show`, or launches sign-off.
  THEN each renders the record with no count, exits 0, and never raises
  `OverflowError` (which is not a `ValueError`).
- GIVEN a PR's `integration.resolution` hand-edited with a YAML anchor that
  refers back to itself (`resolved_from: &r {self: *r}`), which `yaml.load`
  builds and `yaml.dump` round-trips. WHEN the user runs `pm pr show`,
  `pm pr signoff integrate --record`, launches sign-off, or runs `pm pr merge`
  (which recomputes the resolution digest). THEN each renders/hashes the
  record with a deterministic digest and exits without raising `RecursionError`
  out of `compact` or the digest comparison; a *shared* alias that is not a
  cycle still expands normally.
- GIVEN a `pm/project.yaml` whose merge base has `project: {1: a}` and one
  side changes that key's scalar kind (`true: a`, or `1.0: a`). WHEN the
  integration check resolves a metadata conflict. THEN a one-sided kind change
  is taken (that side wins), and both sides changing the same key to
  *different* kinds is refused as ambiguous ("changed scalar kind") — never
  silently resolved to one side. The same document with string keys is
  unaffected.
- GIVEN a conflicted `pm/project.yaml` that is *recursive* (a YAML alias
  referring back to itself, e.g. `project: &p {self: *p}`). WHEN the
  integration check runs. THEN the resolution is refused with a readable
  "the document is recursive" conflict (never a `RecursionError` traceback),
  and the sign-off launch reports the check instead of crashing.
- GIVEN a PR whose `workdir` is a *string path to a regular file* (a stale
  workdir replaced by a file), on a PR in `sign_off` with a recorded
  `SIGNOFF_MERGE`. WHEN the user runs `pm pr merge`, `pm pr signoff record`,
  `pm pr signoff`, or the driver ticks. THEN the workdir reads as absent (a
  refusal / re-provision), exits without a `NotADirectoryError`, and
  `pm pr list --workdirs`, `pm pr cleanup --prune` and `pm pr done` do not
  raise either.
- GIVEN `report.html` names a `pm-signoff-base` other than the base the
  recorded integration check assessed, while `pm-signoff-head` matches. WHEN
  the user runs `pm pr signoff record`. THEN the recorded `## Sign-off`
  evidence block carries no reused-evidence statement from that report (and
  `pm pr show` prints none) — a statement about another base is not this
  decision's; a report written for the checked base is still recorded.
- GIVEN a teammate pushed an unreviewed commit to the PR's remote branch after
  sign-off and merged on GitHub. WHEN the user runs `pm pr merge`. THEN
  publication is refused before anything is published, naming the remote head
  that was not signed off.
- GIVEN two syncs (or a sync and a recovery) run at once for the same detected
  merge. WHEN they finish. THEN the PR carries exactly one `merge_integrity`
  record and one integrity note, every other PR record is intact, and neither
  run reports a lost update.
- GIVEN a base that moved after a bad merge was detected. WHEN the user runs
  the recovery path again. THEN the mismatch is re-derived against the
  recorded approval (or reported as unverifiable), and no second note is
  added.

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
