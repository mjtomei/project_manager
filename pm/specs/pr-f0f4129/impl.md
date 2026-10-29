# Spec: check base integration before review iterations and QA (pr-f0f4129)

## Problem

Sign-off already owns integration (`pm_core/integration.py`, `pr-ac10f03`):
before approving it fetches the configured base, computes the merge with the
PR HEAD in an isolated candidate, and routes a conflicted candidate back to
implementation. That check runs **last** — after review and QA have already
done their work — so a base conflict discovered there throws away a completed
review + QA cycle.

This PR adds the same check **before the downstream writers start**:

1. before starting review (first iteration),
2. before moving to another review iteration (after `NEEDS_WORK`),
3. before starting QA (planning phase).

A conflict at any of those points does **not** launch the reviewer/planner.
It records the exact PR HEAD/base pair, conflict paths/reason and the stage
the PR was headed to, then hands the PR to implementation once to
merge/reconcile the base. A clean integration simply continues the intended
phase (no reset). A failed fetch/probe is a retryable failure — never a
conflict and never an approval. Sign-off remains the final
integrated-candidate authority.

This is deliberately different from #246/pr-62fdd54 (which synchronizes a PR
workdir to its own upstream before QA planning): this check is about the
**configured base** and happens at the review/QA **transition** points.

## Design

New module `pm_core/base_check.py` wraps the existing integration primitive:

* `integration.run_check` / `integration.check_integration` — fetch into
  pm-owned refs and compute the candidate without touching the PR workdir,
  index or branch. Reused unchanged.
* A compact durable return record `pr["base_return"]` (separate from
  `pr["signoff_return"]`, because this is not a sign-off decision), plus a
  `pr["base_check"]` decision/retry record and a PR note.
* A launch claim + `awaiting` handshake modelled on
  `signoff.build_return_record` / `claim_return_launch` /
  `clear_return_awaiting`, so exactly one driver owns the implementation
  relaunch and a restart/stale callback cannot start a second writer.

Choke points (one per writer):

| Transition | Choke point | Covers |
|---|---|---|
| Review start / next iteration | `cli/pr.py::pr_review` (before the status write / `_launch_review_window`) | TUI review loop (`review_loop._launch_review_window` runs `pm pr review`), TUI `zz d`/`z d` one-shot, CLI `pm pr review`, CLI auto-sequence iterations (gated in the tick, then `--skip-base-check`) |
| QA start | `qa_loop.py::run_qa_sync` (after the workdir is ensured, before the QA workdir/windows/planner) | TUI `start_qa` (thread), `pm pr qa-run-bg`, auto-start scheduler |
| Impl→review handoff after a return | `tui/review_loop_ui._poll_impl_idle` + `cli/pr.py::pr_auto_sequence` in_progress branch | TUI and CLI/background drivers |

Resumed paths: a breadcrumb-restored review loop gates its next iteration
through `pr_review`; an in-flight iteration is adopted without a gate (it is
already running). A resumed QA run (`resume_qa_sync`) continues the phase it
already started; if the PR was bounced before the restart, the resume scan
already drops it because the status is no longer `qa`.

## 1. Requirements (grounded)

- **R1 — Gate API.** `pm_core/base_check.py` exposes
  `gate(root, pr_id, stage, *, data=None, iteration=None, transcript=None)`
  returning a `GateResult` with `decision` ∈ {`proceed`, `conflict`,
  `wait`, `retry`, `skipped`}, the integration `status`, `head`, `base_sha`,
  `conflicts`, `error`, `returned`, `already_returned`, `launched`, `reason`,
  and the full record. `stage` ∈ {`review`, `review_iteration`, `qa`}.
  It uses `integration.check_integration` (so `pr["integration"]` and
  `$CAP/integration.json` are recorded) and never mutates the product
  workdir/index/refs (only pm-owned `refs/pm/integration/*`).
- **R2 — Conflict return.** On `conflict`, `return_to_impl` writes
  `pr["base_return"]` = `{verdict: "BASE_CONFLICT", stage, iteration, head,
  base_sha, base_branch, target_repo, conflicts, conflicts_total, overlap,
  overlap_total, reason, attempt, ts, awaiting: "impl", launch_claim,
  resolved_at: None}` in the same `store.locked_update` that transitions
  `in_review`/`qa` → `in_progress` (a PR already `in_progress` keeps its
  status). The same update records a deduplicated PR note naming the pair,
  conflict paths (bounded, with `integration.integration_pointer`) and the
  intended stage. Then the winner calls `claim_impl_launch` (already held
  from the record) and `launch_impl` (`pm pr start --fresh --background
  --transcript <tdir>/impl-<pr>.jsonl`), so implementation gets the rework
  prompt block. The launch clears `awaiting` via `pr_start`. A conflict
  also retires the PR's review window (`_retire_review_window_for_return`),
  mirroring sign-off's bounce, so no reviewer writer is left behind; a
  refused/raced writer start normalizes the status back to `in_progress`
  (`ensure_impl_status`). A corrupt `base_return` (a string/list from a
  hand-edited yaml) is treated as "no previous return" rather than raising
  inside the locked update — otherwise the gate reports "the PR left the
  phase" and leaves it in review with an unreconcilable base.
- **R3 — No downstream writer on conflict.** `pr_review` prints a one-line
  stdout status and exits with code **3** (no status write, no review
  window) on `conflict`/`wait`. `run_qa_sync` sets
  `state.base_returned = True` / `base_return_reason` and returns before
  creating the QA workdir, Scenario 0, or the planner. The TUI drops the QA
  loop in `poll_qa_state` with a log line.
  The gate is a network round-trip inserted between the phase check and the
  status write / window creation, so both choke points re-check the PR is
  still eligible afterwards: `pr_review`'s `in_review` write refuses (no
  window) unless the PR is still in a pre-review status
  (`in_progress`/`in_review`) and has no open base return — so neither a
  concurrent merge/close, a concurrent `qa`/`sign_off` transition (exit 1),
  nor a conflict return another driver recorded inside the same fetch (exit
  3, the routing code `review_loop` maps to `VERDICT_BASE_CONFLICT`, since no
  reviewer ran; otherwise it would start a reviewer beside the rework that
  return just launched) is demoted back to `in_review`; and `run_qa_sync`
  re-checks `merged`/`closed` and an open base return after the gate.
  Neither may demote a finished PR or start a writer against it.
  The already-`in_review` branch of `pr_review` (the normal path for review
  iterations ≥ 2, which writes no status and therefore has no atomic guard)
  re-reads the PR after the gate too (`_review_post_gate_refusal`): an open
  return there exits **3** — the routing code `review_loop` maps to
  `VERDICT_BASE_CONFLICT`, so no iteration is recorded and the reviewer never
  starts beside the rework — and a PR that left the pre-review phase exits
  **1** with no window.
- **R4 — Clean integration continues.** `clean` / `up_to_date` / `in_base`
  resolve any open base return and let the caller proceed exactly as before.
  No review/QA reset, no status change, no re-run.
- **R5 — Retryable probe failures.** `error` (fetch/ls-remote/git failure)
  is recorded in `pr["base_check"]` with `retryable: True` and a
  `retry_after` backoff, logged once, and **never** bounces to
  implementation. At a writer launch the phase proceeds (the gate is a
  waste-avoidance pre-check, not the final authority — sign-off still
  checks); during the post-return completion check it means "not proven
  complete", so the handoff waits and retries. A corrupt non-dict
  `base_check` (hand-edited yaml) reads as "no record" rather than raising:
  an exception on that path makes the gate fail open (no return is ever
  recorded) and the completion check report "failed" on every poll, leaving
  the PR with an open return nobody can resolve.
- **R6 — Genuine implementation completion.** `impl_completion(root, pr_id,
  pr, *, idle_since)` returns `(complete, reason, resume_loop)` only when all
  hold: the return's `awaiting` is cleared (the fresh session launched); the
  pane is idle; the idle event is at least `IDLE_SETTLE_SECONDS` old (settle
  window so a background test/edits started just before the idle turn can
  surface); no merge/rebase/cherry-pick/revert is in progress; the tracked
  worktree is clean (`--untracked-files=no`, so fixtures/drafts/untracked
  files, and pm's own `project.yaml`/lock at the repo root or under `pm/` —
  matched as those exact paths, so a same-named file in another `pm/`
  directory is a real edit — are untouched and do not block);
  and a fresh integration check is no longer a conflict. Same
  `(head, base_sha)` as the return ⇒ wait; a moved pair that still conflicts
  ⇒ one more return (bounded); `clean`/`up_to_date` ⇒ resolve and complete.
  The idle evidence must also **postdate the relaunch** (`launched_at`,
  written by `clear_return_awaiting`): a killed session's last
  `idle_prompt` — still visible through a stale `impl-<pr>.jsonl` symlink in
  another driver's transcript dir — is not the rework session's turn, so the
  relaunch re-points those symlinks (`share_impl_transcript`) to keep the
  new session trackable. A superseding return (a moved base that still
  conflicts, including the capped `needs_human` one, which launches nothing
  itself) keeps the superseded episode's `launched_at`, so the guard keeps
  comparing against the session that actually ran instead of the new
  record's creation time — otherwise the previous session's idle turn could
  never satisfy it and a reconciled base would leave the handoff waiting
  forever. A fresh launch overwrites it.
  That call lives in `pm pr start` (the single
  implementation launcher) as well as in `launch_impl`, so a relaunch
  started by the TUI auto-start catch-up or a manual `pm pr start` also
  refreshes the CLI auto-sequence dir's link — otherwise that driver keeps
  reading the killed session's idle event and its handoff never advances.
  Only symlinks are re-pointed: a finalized transcript (a real file left by
  `finalize_transcript` when a run ends) is evidence, so it is kept beside
  the refreshed link (`<name>.finalized`) rather than deleted. The link
  comparison uses the *resolved* path as well as the literal one, so a
  transcript handed over relatively (`pm pr start --transcript
  transcripts/run/impl-<pr>.jsonl`) is never mistaken for another driver's
  stale copy and renamed out from under its own session. The target written
  into the refreshed links is normalized to an absolute path, so a
  relatively-spelled transcript (or a relative link target) does not become
  a dangling link in another driver's directory.
  A successful launch also clears a previous attempt's `apply_error`. An
  idle notification alone never qualifies: a
  missing idle timestamp (`idle_since is None`, e.g. the pane/tracker could
  not be read) is *no evidence* and must not skip the settle/relaunch
  guards. A null/corrupt `base_return` (hand-edited yaml) is treated as "no
  return"; the `resume_loop` read must not raise, because the outer guard
  would report that as a failed check on every poll. The TUI
  runs the network check in a worker thread (throttled to
  `BASE_CHECK_POLL_SECONDS`, keyed to the return episode *and* the idle
  event it was computed for — a later idle event invalidates the cached
  verdict); the CLI passes the tracker's idle timestamp so the same settle
  window applies.
- **R7 — Idempotent / single owner.** The return is created at most once per
  open episode and never twice for the same unresolved `(head, base_sha)`
  pair (second gate ⇒ `wait`, no new return, no launch). `launch_claim`
  (expiry `RETURN_LAUNCH_CLAIM_SECONDS`) + `claim_impl_launch` guarantee one
  implementation owner across the TUI scheduler, CLI ticks, review-loop
  subprocesses and restarts. Status guards (`in_progress`/`in_review`/`qa`
  only) make stale callbacks no-ops.
- **R8 — Bounded loop.** A return records `attempt`; repeated conflicts for
  the same base across *moved* heads are capped at `MAX_RETURNS_PER_BASE`.
  Past the cap the return is marked `needs_human` and no further impl is
  auto-launched (the note says so), so a pathological loop cannot spin.
  The cap stops *automatic rework*, not recovery: the gate and
  `impl_completion` still re-run the integration check (never writing
  another episode or note while it conflicts), so a human who reconciles
  the base lets review/QA resume — matching the note's "a human must
  reconcile the base before review/QA resumes" instead of leaving the PR
  permanently stuck with no `pm` command to clear it. Because the capped
  record launches nothing, it carries the last relaunch's `launched_at`
  (R6) so `impl_completion` can accept the previous session's idle turn;
  without that the handoff would wait forever even after the base was
  reconciled by hand.
- **R9 — Sign-off ownership preserved.** The gate skips when the PR is
  `sign_off` or an open `signoff_return` exists (`open_return`): sign-off
  owns integration there, and a sign-off REVIEW/REQA hop must still launch.
  `pm pr merge` and its sign-off gate are untouched.
- **R10 — Preserve evidence.** Never delete review-loop history, iteration
  transcripts, QA captures, notes, `integration.json`, stashes or dirty
  files. `_start_loop` continues iteration numbering from the existing
  `review-<pr>-i<N>.jsonl` files (and carries over an in-memory completed
  state's history) so a resumed loop adds iteration N+1 instead of
  overwriting `-i1`. A `resume_loop` marker (set when the bounced review was
  a TUI loop) lets the TUI restart the loop after genuine completion even
  without auto-start.
- **R11 — Prompt context.** `prompt_gen` injects
  `base_check.format_return(pr)` next to `_signoff_return_block` in the impl,
  review and QA-planner prompts: pair, conflicts, pointer to the full
  record, and the reconcile-and-commit instructions. It renders only while
  the return is open.
- **R12 — Auto-sequence coverage.** `pr_auto_sequence` gates before every
  review-iteration launch (`NEEDS_WORK`, sign-off REVIEW catch-up, missing
  window), reports `base_conflict: ...` / `paused: base_check_error`, and
  gates the in_progress idle advance through `impl_completion` (reporting
  `running: implementation (<why>)`). It relaunches impl for a base
  `awaiting == "impl"` return via `claim_impl_launch`, mirroring the
  sign-off return catch-up. A hidden `--skip-base-check` flag on
  `pr_review` avoids a double fetch from this in-process path. Its `qa`
  branch refuses to advance a PR whose base return is still open (repairing
  a raced `in_progress`→`qa` transition) instead of trusting a stale
  `qa_status.json`, so a previous QA PASS cannot hand the PR to sign-off
  beside the rework. `pr qa-run-bg` refuses before its `in_review`→`qa`
  transition and repairs a raced status on that first guard too (its second,
  post-transition check is unreachable once the first fires).
- **R13 — TUI coverage.** `_start_loop`, `_auto_start_review_loops` and
  `_auto_start_qa_loops` refuse to start a writer while a base return is open
  (the refusal repairs a raced `in_review`/`qa` status back to `in_progress`
  — the handoff only polls `in_progress`, so leaving it would strand the
  rework); `start_qa` / `start_or_stop_qa_loop` refuse to start QA likewise;
  `_poll_impl_idle` evaluates `impl_completion` in a **thread worker**
  (fetch must not block the TUI event loop), logs a wait reason once (one
  INFO line per distinct completed verdict, so the 5 s poll does not spam
  the log), and advances only on a genuine completion. If the worker cannot
  be spawned the in-flight marker is cleared (the next tick reports the
  failure instead of "checking base integration" forever). A base return
  whose rework never launched is caught up from the idle poll regardless of
  auto-start (the launch claim keeps one owner; `check_and_start` only
  drives in-scope PRs, so a manual loop on a non-target PR would otherwise
  strand its rework). That catch-up is **retryable**, not one-shot: a claim
  still held (the gate's own `pm pr start` is running) or one released by a
  failed launch (`release_impl_claim` keeps `awaiting`) is re-attempted on a
  later tick, throttled to `BASE_LAUNCH_RETRY_SECONDS` because each attempt
  takes the project.yaml lock. The idle turn is therefore left unconsumed
  (`mark_active` is not called) for a base return — an idle old session emits
  no further hook event, so consuming it would leave the PR with no launcher
  and no completion check. A successful in-process relaunch reloads
  `app._data` (`_load_state`): `pm pr start` cleared `awaiting` on disk, and
  no CLI-subprocess reload (`trigger_tui_refresh` / `_run_command_async`)
  follows this launch, so without it the next idle tick re-enters the
  awaiting branch with the stale marker and never reaches the completion
  check.
  `_base_completion_tick` never reaches the git helpers with an empty cwd
  (they raise, inside the shared
  poll timer), and returns a plain "no project root" verdict instead of
  passing `None` to `store.load` before the project is loaded.
  `_resume_returned_loop` does not start a second loop when one
  is already running for the PR. `review_loop` maps exit code 3 to
  `VERDICT_BASE_CONFLICT` and stops the loop without recording an iteration;
  the icon/log path treats it as a clean completion (not ERROR).
- **R14 — Inspection.** `pm pr show` prints a `## Base integration return`
  section (verdict, stage, HEAD/base, attempt, reason, conflict paths,
  apply error) so the handoff is inspectable. `autostart_state._derive`
  reports the rework for an `in_progress` PR with an open return
  ("relaunching implementation" / "reconciling the base", `paused` when
  `needs_human`) instead of the misleading "impl idle; review transition
  pending".
- **R15 — Tests.** Real-git tests for each transition point, the unchanged
  pair, a moved base during the handoff, dirty workdir retention, fetch
  failure, concurrent gates / one owner, restart/late-callback idempotency,
  and a background-test idle that does not qualify as completion. Plus the
  hardening cases: a corrupt non-dict `base_return`, a relatively-spelled
  transcript in `share_impl_transcript`, a merge landing during the gate's
  fetch at the review and QA choke points, and a missing project root in the
  TUI completion tick.

## 2. Implicit requirements

- The check must run **without** mutating the PR worktree, its index, branch,
  stashes, or user base refs. `integration`'s isolated candidate already does
  this; the gate must not add a checkout/merge (only `launch_impl` touches
  the window, not the workdir; `pr_start` skips pull/checkout on a dirty
  workdir).
- `store.locked_update` must never be held across the fetch: the check runs
  first, then the return is written under the lock (same rule as
  `integration.check_integration` and `merge_integrity`).
- `pr_start` is the single implementation launcher: it preserves the model
  override, honors `spec_pending` (a pending spec makes the relaunch fail and
  the return stays `awaiting`, to be retried after approval), reuses the
  existing workdir and clears `awaiting` only on a successful launch.
- A conflict return must not consume or invalidate a `SIGNOFF_MERGE`
  approval, `skip_qa`, `wait_for_merge`, `report.html`, or the sign-off
  report hash.
- The gate must be cheap enough for the TUI: the completion check is
  throttled (`BASE_CHECK_POLL_SECONDS`), skipped while a check is in flight,
  and uses a `retry_after` backoff after probe errors.
- `run_qa_sync`'s existing early returns (merged/closed, spec gate) keep
  setting `state.running = False` and must keep working; the new gate runs
  after the workdir is resolved but before any window is created.
- CLI status lines are stable single-line contracts for watchers
  (`started`, `running: ...`, `advanced: ...`, `paused: ...`,
  `ready_to_merge`); the new lines follow that shape.

## 3. Ambiguities (resolved)

- **A1 — Proceed or block on a probe failure?** *Resolved: fail open at a
  writer launch, wait during completion.* The pre-check exists to avoid
  wasted work; blocking the pipeline on a transient network failure is worse
  than the status quo, and sign-off still performs the authoritative check.
  The failure is explicit (`base_check.retryable`, `retry_after`, log line)
  and never treated as clean or as a conflict. After a return, "cannot
  prove clean" is not "complete", so the handoff waits and retries.
- **A2 — What is "genuine" completion?** *Resolved:* the return's relaunch
  happened, the pane is idle past a settle window, the workdir has no
  in-progress git operation and no tracked edits, and the fresh integration
  check is not the same conflict. A background process with no observable
  effect (no workdir/HEAD/base change) is indistinguishable from a finished
  turn and is covered by the settle window; a background job that writes or
  commits is caught by the dirty-tree/pair checks.
- **A3 — Reuse `signoff_return` or a new record?** *Resolved: new
  `base_return`.* The sign-off record drives sign-off-only hops
  (`apply_signoff_hop` guards `status == sign_off`), and reusing it would
  make a pre-review check render as a sign-off decision and close a real
  sign-off return episode. The shapes and claim helpers are mirrored, not
  shared, and `pr_start` clears both.
- **A4 — Should a manual (non-auto-start) review loop resume after the
  rework?** *Resolved: yes, when the bounce came from a TUI review loop*
  (`resume_loop`, set from `--review-loop-id`). A one-shot `z d` stays
  manual. Auto-start/self-driving resume through the existing scheduler.
- **A5 — Apply the gate to `pm pr review --no-window`?** *Resolved: no.* It
  only transitions status; the caller's loop launches iteration 1 through
  `pr_review` (which gates), so gating here would double-fetch and could
  strand a status transition.

No unresolved ambiguities.

## 4. Edge cases

- PR already `in_progress` at the pre-review check (the normal first-review
  case): return keeps the status, relaunches the idle impl window fresh.
- Base moves between the check and the return, or during the rework: the
  completion check re-fetches the **latest** base; a new conflicting pair
  produces one new return (bounded), a clean one resolves.
- Base moves cleanly while review is mid-loop: the next iteration proceeds;
  no reset.
- Fetch target unreachable / repo missing / workdir not a git repo / no
  HEAD: `retry` (fail open), no bounce.
- `spec_pending` set when the return wants to relaunch impl: `pr_start`
  refuses; record `apply_error`, keep `awaiting`, retry later.
- TUI restart between the return and the relaunch: `check_and_start` /
  auto-sequence catch-up claim the expired launch (one winner); the resume
  scan drops a bounced QA snapshot because the status left `qa`.
- Stale review-loop callback / duplicate `pr_review`: `wait` (exit 3), no
  writer, no second return.
- Two concurrent gates (TUI + CLI): one `locked_update` wins; the loser
  sees the open return and does not launch.
- A sign-off REVIEW/REQA hop while a base return would otherwise be open:
  the gate skips, sign-off's own routing (and integration check) wins.
- `skip_qa` projects: review PASS still skips QA; the gate never runs for a
  phase that does not start.
- `in_base` (HEAD already contained in the base): treated as non-conflict;
  merge detection remains the sync paths' job.
- Very large conflict lists: bounded in `base_return` (like
  `integration.compact`) and the note; the full list stays in
  `integration.json`.
- `pm pr show` with a resolved return still prints it (history), with
  `resolved_at`.

## 5. Test plan (real git where it matters)

`tests/test_base_check.py` (new):
1. conflict at the review stage → `conflict`, status `in_progress`,
   `base_return` carries head/base/conflicts/stage, one note, impl launch
   attempted exactly once.
2. same pair gated again → `wait`, no second return, no launch.
3. clean / up_to_date → `proceed`, status unchanged, no return.
4. fetch failure → `retry`, `base_check.retryable`, no bounce.
5. moved base during the handoff → `impl_completion` completes and resolves;
   unchanged pair → not complete.
6. dirty workdir retained (untracked + tracked edit), no in-progress merge →
   not complete; workdir contents unchanged by the gate.
7. concurrent gates (two threads) → exactly one return/claim.
8. repeated conflicts on new heads → capped at `MAX_RETURNS_PER_BASE`,
   `needs_human`, no launch.
9. `format_return` renders the pair/paths/instructions only while open.
10. the `pm pr review` choke point: exit 3 with no status write and no
    review window; a clean base still launches the reviewer.
11. a malformed `attempt` in `base_return` still records the return.
12. `tracked_dirty` ignores only pm's exact state paths (`project.yaml` /
    its lock at the root or under `pm/`); a tracked `sub/pm/project.yaml`
    edit still blocks completion.
13. a corrupt non-dict `base_return` (a string) still records the return;
    `share_impl_transcript` leaves a relatively-spelled transcript in place.
14. a merge landing during the gate's fetch: `pm pr review` does not write
    `in_review` (exit 1, no window) and `run_qa_sync` does not create the QA
    workdir.
15. a capped (`needs_human`) return resolves through `impl_completion` from
    the previous session's idle turn once a human reconciles the base (no
    new launch), i.e. the superseded record keeps `launched_at`.
16. a relatively-spelled transcript (direct path or relative link target)
    yields an absolute target in every refreshed link.
17. a `qa`/`sign_off` transition landing during the gate's fetch is not
    demoted to `in_review` (exit 1, no window).
18. a base conflict return another driver records during the gate's fetch:
    `pm pr review` does not write `in_review` (exit 3, no window) and the PR
    stays `in_progress` with the return open.
19. the same race at the QA choke point: `run_qa_sync` creates no QA workdir,
    reports `base_returned`, and leaves the PR `in_progress`.
20. the same race on the already-`in_review` branch (review iterations ≥ 2,
    which writes no status): `pm pr review --review-iteration 2` does not
    launch the reviewer, exits 3, and leaves the PR `in_progress` with the
    return open.
21. a corrupt non-dict `base_check` (a string, a list) reads as "no record":
    a conflict still records the return, and a probe failure still records
    its retry metadata (without the guard `_retry_open` raises, so the gate
    fails open and `impl_completion` never completes).

`tests/test_review_loop.py` additions: exit code 3 → `BaseConflictError` →
`VERDICT_BASE_CONFLICT`, no history entry, loop stops; `next_review_iteration`
continues numbering.

QA choke point (kept in `tests/test_base_check.py` next to the gate fixtures,
since each needs a real conflicting base): `run_qa_sync` conflict →
`base_returned`, status `in_progress`, no QA window/planner; clean →
unchanged flow; a merge landing during the gate's fetch aborts before the QA
workdir; a return landing during the fetch reports `base_returned`.

`tests/test_pr_auto_sequence.py` additions: NEEDS_WORK with conflict → no
review launch, `base_conflict` line; in_progress idle with an open unchanged
return → `running: implementation (...)`; resolved → `advanced: in_review`;
awaiting impl → relaunch catch-up; `qa-run-bg` repairs a raced status and
never flips it to `qa`.

`tests/test_pr.py` / prompt tests: `--no-window` still transitions without a
launch; the impl/review/QA prompts include the return block.

TUI: `_start_loop`/`start_qa`/`_auto_start_review_loops`/
`_auto_start_qa_loops` refuse with an open return (repairing a raced
status); `_poll_impl_idle` does not advance on a background-test idle
(settle/pair/dirty) and does advance after a genuine commit; a missing
workdir or project root never reaches the git helpers; `_resume_returned_loop`
never starts a second loop; `poll_qa_state` drops a returned run. The base
rework catch-up is retried: a held/released claim leaves the idle turn
unconsumed (no `mark_active`) and is re-attempted after
`BASE_LAUNCH_RETRY_SECONDS` (throttled, not once per poll tick), and a
successful in-process relaunch reloads `app._data` so the completion check is
reachable.

## 6. Out of scope

- Resolving conflicts automatically (pr-5cee3d5's evidence-reuse work may
  build on the preserved evidence; this PR only avoids the wasted cycle).
- Syncing a workdir to its own upstream before QA (pr-62fdd54).
- Changing the sign-off verdict router, the merge gate, or merge policy.
- The one remaining transcript overwrite outside `share_impl_transcript`:
  `claude_launcher.build_claude_shell_cmd` unlinks whatever already exists
  at the launch transcript path (including a finalized copy) before creating
  its symlink. That path is owned by pr-9ee4d64 (see the note left on it);
  this PR keeps the finalized copy safe only in the re-pointing path.
