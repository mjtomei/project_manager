# QA spec: check base integration before review iterations and QA (pr-f0f4129)

Grounded in `pm/specs/pr-f0f4129/impl.md`, the PR diff (`pm_core/base_check.py`,
`pm_core/cli/pr.py`, `pm_core/qa_loop.py`, `pm_core/review_loop.py`,
`pm_core/prompt_gen.py`, `pm_core/autostart_state.py`, `pm_core/tui/*`) and the
PR notes (review be50 i1/i2 hardening on top of the merged master).

## 0. What the fix is (the bug this QA must prove gone)

Before this PR the only integration check ran at **sign-off**, i.e. after a
full review cycle and a full QA cycle. A PR whose HEAD conflicted with the
moved configured base therefore burned a reviewer run and a QA planner run
before anyone noticed, and sign-off then bounced it back to implementation.

After this PR the same check (the existing `integration` primitive: fetch the
base into pm-owned refs, merge in an isolated candidate, never touch the PR
workdir) runs as a **pre-flight gate** at three transition points:

1. before starting review (first iteration),
2. before starting another review iteration (loop / auto-sequence tick),
3. before starting QA planning.

A conflict does not launch the reviewer/planner. It records the exact
`(PR HEAD, base sha)` pair, the conflicting paths and the stage the PR was
headed to, notes it on the PR, moves the PR back to `in_progress` and hands
it to implementation **once**. A clean base simply continues the intended
phase. A fetch/probe failure is a retryable failure — never a conflict, never
an approval.

The user-visible assertion of the fix is therefore: **the reviewer/planner
never starts and no review iteration is recorded when the base conflicts**,
while a clean base still starts the writer exactly as before.

## 1. Requirements (user stories)

Each story is GIVEN / WHEN / THEN. `PR` means a PR in a throwaway pm project
(local backend) whose workdir has its own commit; `base` is the project's
configured base branch (`master` in the main repo).

### R1 — A real conflict stops review before the reviewer starts
- **R1.1** GIVEN a PR in `in_progress` whose workdir commit and the base
  branch both changed the same lines of one file (a real `git` conflict),
  WHEN the user asks for a review (`pm pr review <id>`), THEN
  - the command prints a `base_conflict:` line naming the conflict and a
    "review not started — returned to implementation" line, and exits
    non-zero (exit 3);
  - **no reviewer window is created** (no `review-<pr>` tmux window) and no
    review iteration transcript (`review-<pr>-i1.jsonl`) is produced;
  - the PR is `in_progress` again, with a `## Base integration return`
    section in `pm pr show` carrying verdict `BASE_CONFLICT`, stage
    `review`, the exact PR HEAD sha, the base branch and the fetched base
    sha, attempt 1, `awaiting: impl`, and the conflicting path;
  - the PR carries exactly one new note naming the pair, the conflicting
    path(s) and a pointer to the full integration record, and
    `$CAP/integration.json` (via `pm qa captures-path <id>`) holds the full
    record with `status: conflict` and the conflicting paths;
  - an implementation session is launched for the PR and the instructions it
    receives include the "Returned to implementation: base integration
    conflict" block (pair, conflicting paths, reconcile/merge/test/commit/push
    instructions, "never push or merge into the base branch");
  - the gate mutated nothing in the PR workdir: same branch, same HEAD, same
    index, same uncommitted edits, same stashes, no `MERGE_HEAD`, no conflict
    markers.

- **R1.2** GIVEN the same conflict was just returned (R1.1), WHEN the user
  asks for review again without changing anything, THEN the command again
  refuses (exit 3, "implementation rework pending"), no second note is added,
  no second implementation session is launched, and no second return episode
  is recorded — the PR is not bounced twice for the same unchanged pair.

- **R1.3** GIVEN a second PR in the same project whose HEAD merges cleanly
  with the (moved) base, WHEN the user asks for review, THEN the review
  starts exactly as before: status `in_review`, a review window opens, no
  `base_return` is recorded, and no review/QA reset is triggered (the PR is
  not re-run from an earlier phase).

### R2 — The handoff is inspectable and durable
- **R2.1** GIVEN a PR with an open base return, WHEN the user inspects it
  (`pm pr show <id>`) from a fresh shell, THEN the "Base integration return"
  block shows the verdict, stage, HEAD, base branch/sha, target, attempt,
  reason and awaiting state, plus the conflict path list and the
  `integration.json` pointer — the record survives process restarts because
  it lives in `pm/project.yaml`.
- **R2.2** GIVEN a returned PR, WHEN the auto-start status view is opened in
  the TUI, THEN the PR's reason reads as base rework ("relaunching
  implementation" while the relaunch is pending, "implementation reconciling
  the base" once it launched) rather than the misleading "impl idle; review
  transition pending".

### R3 — The review loop treats the gate as routing, not failure
- **R3.1** GIVEN a PR in `in_progress` with a conflicting base and a running
  TUI review loop, WHEN the loop's iteration tries to start, THEN no
  reviewer window opens, the loop stops with a base-conflict verdict (the
  tree marker shows the loop's base-conflict icon, not an error/timeout
  marker), and **no iteration is recorded** in the loop history.
- **R3.2** GIVEN a review loop that was bounced at iteration 1 and whose
  implementation later reconciles the base, WHEN the loop resumes, THEN the
  next iteration continues the existing numbering (iteration 2, a new
  `review-<pr>-i2.jsonl`) and the earlier iteration's transcript is still
  present — evidence is appended to, never overwritten.
- **R3.3** GIVEN a PR with an open base return (in `in_progress`), WHEN the
  user starts a review by hand in the TUI, THEN no reviewer window opens,
  the refusal is logged/visible, and the PR stays `in_progress` (a raced
  `in_review` status is repaired, never left as `in_review` with no
  reviewer).

### R4 — QA never starts the planner on a conflicting base
- **R4.1** GIVEN a PR that has finished review and whose HEAD conflicts with
  the base, WHEN QA is started (`pm pr qa-run-bg <id>` or the TUI QA start),
  THEN no QA workdir, Scenario 0 or planner window is created, the PR is
  `in_progress` with a base return (stage `qa`), the run reports that it was
  not started because of the base conflict, and any QA artifacts from an
  earlier run are untouched.
- **R4.2** GIVEN the same project, a PR with a clean base, WHEN QA is
  started, THEN QA runs exactly as before (QA workdir and planner window
  created, status `qa`) and no base return is recorded.
- **R4.3** GIVEN an open base return on a PR, WHEN the user starts QA in the
  TUI, THEN QA does not start and the PR is not left in `qa`.

### R5 — Implementation completion must be genuine
- **R5.1** GIVEN a returned PR whose implementation session merged the latest
  base, resolved the conflict, committed and is idle, WHEN the handoff check
  runs (TUI idle poll or a `pm pr auto-sequence` tick), THEN the PR resolves
  the return and advances to review (`in_review`, a reviewer window for the
  next iteration), with the resolved record kept on the PR.
- **R5.2** GIVEN the same returned PR where the implementation session is
  idle but has **not** changed anything (a background test/edit turn: dirty
  tracked tree, or no commit at all), WHEN the handoff check runs, THEN the
  PR does **not** advance — the status stays `in_progress` and the CLI tick
  reports `running: implementation (<reason>)` — and no reviewer is started
  beside the implementation window.
- **R5.3** GIVEN the returned PR with untracked fixtures/drafts and a stash
  in the workdir (but no tracked edits and no git operation in progress),
  WHEN the implementation commits its reconciliation, THEN the untracked
  files and the stash are still there afterwards, and they did not by
  themselves block completion.

### R6 — Exactly one implementation owner (concurrency / restart)
- **R6.1** GIVEN a returned PR, WHEN two drivers try at the same time to
  relaunch implementation (TUI auto-start / TUI idle poll and a
  `pm pr auto-sequence` tick, or a manual review trigger), THEN exactly one
  implementation session is launched, the other driver reports "running" and
  launches nothing, and no reviewer/QA writer runs beside it.
- **R6.2** GIVEN a return recorded just before the TUI restarts (the relaunch
  never happened), WHEN the TUI comes back (or the CLI tick runs), THEN the
  pending rework is launched once — an idle *old* session is never mistaken
  for finished work, and the handoff still advances after the rework.
- **R6.3** GIVEN a stale callback or a duplicate `pm pr review` arriving
  after the return, WHEN it runs, THEN it is a no-op: no second return, no
  second launch, no status demotion of a PR that has moved on.

### R7 — Base movement during the handoff
- **R7.1** GIVEN a returned PR and the base moving to a *still conflicting*
  revision while implementation reworks, WHEN the completion check runs,
  THEN one new return episode supersedes the open one (attempt incremented,
  new base sha recorded), exactly one implementation session is launched,
  and the PR is not duplicated into two episodes.
- **R7.2** GIVEN a returned PR and the base moving to a revision that merges
  cleanly, WHEN the completion check runs, THEN the return resolves and the
  phase continues (review/QA as intended) without a full reset.
- **R7.3** GIVEN repeated conflicts across moving bases, WHEN the return
  count for that base exceeds the cap, THEN the PR is marked as needing a
  human (the auto-start view shows it paused), no further implementation is
  launched automatically, and once a human reconciles the base the handoff
  still resolves instead of leaving the PR stuck.

### R8 — Probe failures are retryable, never a conflict and never an approval
- **R8.1** GIVEN the configured base cannot be fetched (target repo
  unreachable/removed), WHEN the user asks for review, THEN the review still
  starts (the gate is a waste-avoidance pre-check; sign-off remains the
  authority), a retryable base-check failure is reported, and no
  `base_return` is recorded.
- **R8.2** GIVEN an open base return and the base becoming unreachable,
  WHEN the completion check runs, THEN the PR does **not** complete (cannot
  prove clean), the status stays `in_progress`, and the check is retried with
  backoff rather than hammering the network or declaring success.
- **R8.3** GIVEN a PR in `sign_off` (or with an open sign-off return), WHEN
  the gate would run, THEN it stands aside: sign-off owns integration and its
  own routing still launches the review/implementation hop. No base return is
  recorded and no sign-off approval or merge gate is consumed.

### R9 — Nothing else is lost
- **R9.1** GIVEN a PR with prior review transcripts, QA captures, notes,
  a dirty workdir, stashes, fixtures and drafts, WHEN the gate bounces it and
  the rework completes, THEN all of that evidence is still present, the
  model routing/spec-review settings and manual merge gates are unchanged,
  and the PR is neither merged nor force-pushed.

## 2. Setup (cross-cutting, described as user steps)

- Build/install pm from this PR checkout (`./install.sh --local`, or a venv
  with `pip install -e .`); confirm `pm which` points at this checkout.
- **Test isolation is mandatory** (2026-10-29 incident): run the TUI in a
  dedicated tmux socket (`TMUX_TMPDIR` on a private dir) with `TMUX` /
  `TMUX_PANE` unset, and use isolated pm state/config paths. Never touch the
  user's real tmux server, its sessions, or shared `~/.pm` breadcrumbs; never
  "clean up" by killing a session the test did not create.
- One throwaway git project per scenario (`tui-manual-test.md`): `git init`,
  initial commit with a small source file (`app.py`), `pm init --backend
  local --no-import`, then `pm pr add`.
- Drive agent sessions with `pm fake-claude config set ...` (implementation,
  review verdicts, QA plan). The worker acts as the implementation agent by
  editing/committing in the PR workdir when a fake implementation turn is
  used; real Claude is not required.
- Produce a **real** conflict: the PR workdir commits a change to a function
  in `app.py`; the main repo's base branch (`master`) gets a *different*
  change to the same lines and is committed there. `git merge` of the two
  must actually conflict (verify in a scratch clone before driving pm).
- Produce a **clean moved base**: a commit on `master` touching a file the PR
  did not touch.
- Keep the D3 watcher off; use the isolated socket's own pm session.

## 3. Edge cases

- **E1** Conflict at the first review, at a later review iteration, and at
  QA — all three transition points, each with a real git conflict.
- **E2** Same unchanged pair polled/gated repeatedly (manual retry, loop
  tick, restart) — one return, one launch, `wait` thereafter.
- **E3** Base moves *during* the handoff: still conflicting (supersede, one
  episode) and clean (resolve, continue).
- **E4** Base unreachable at a writer launch (fail open) and during the
  completion check (wait, retry with backoff).
- **E5** Two drivers at once (TUI auto-start/idle poll + CLI
  `pm pr auto-sequence` + a manual `d`) → one return, one implementation
  session, no concurrent writers.
- **E6** TUI restart between the return and the relaunch; a stale callback;
  a duplicate `pm pr review`.
- **E7** Implementation idle without work (background test, dirty tree, no
  commit) → not complete.
- **E8** Dirty workdir, untracked fixtures/drafts, stashes preserved through
  the bounce and the rework.
- **E9** PR in `sign_off` with an open sign-off return → gate stands aside.
- **E10** PR already merged/closed while the gate's fetch is in flight → no
  status demotion, no window.
- **E11** Capped returns (`needs_human`) after repeated moved-base conflicts,
  and recovery by hand once the base is reconciled.

## 4. Pass / fail criteria

**Pass** when every THEN above is observed on the real user surface: CLI
stdout/exit code, TUI render and tmux windows, `pm/project.yaml` records,
`pm pr show`, PR notes, `$CAP/integration.json`, the git state of the PR
workdir and the base repo.

**Fail** if any of:
- a reviewer/QA planner window or a review iteration is created on a
  conflicting base (the bug this PR fixes);
- a conflict is reported as clean, or a fetch failure is reported as a
  conflict/approval;
- the gate mutates the PR workdir (index, HEAD, branch, stashes, uncommitted
  edits), leaves `MERGE_HEAD`/conflict markers, or touches the base branch;
- two implementation sessions are launched for one return, or a reviewer/QA
  writer runs concurrently with the rework;
- an unchanged pair is bounced repeatedly (endless loop), or a moved-base
  conflict produces duplicate episodes;
- an idle-but-unfinished implementation (dirty tree, no commit, background
  test) is treated as complete;
- evidence (transcripts, QA captures, notes, dirty files, stashes,
  `integration.json`) is lost, a sign-off approval/merge gate is consumed, or
  the PR is merged/force-pushed by the gate.

## 5. Ambiguities (resolved)

- **A1** *Is a fetch failure a conflict?* No — retryable; at a writer launch
  the phase proceeds (sign-off remains the authority), during the completion
  check it means "not proven complete" and the handoff waits. (impl spec A1)
- **A2** *What counts as completed implementation?* Relaunch happened, pane
  idle past the settle window, no git operation in progress, no tracked
  edits, and a fresh check that is no longer the same conflict. A
  background job with no observable effect is covered by the settle window.
  (impl spec A2)
- **A3** *Does a clean moved base reset review/QA?* No — the intended phase
  continues; a conflict return is the only thing that changes the phase.
- **A4** *Is `pm pr review --no-window` gated?* No — it only transitions
  status; the caller's loop launches iteration 1 through the gated path.
- **A5** *Manual (non-auto-start) loop after the rework?* A loop that was
  bounced resumes (it recorded `resume_loop`); a one-shot manual review stays
  manual.

No **[UNRESOLVED]** ambiguities.
