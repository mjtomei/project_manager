# Spec: durable owed-REQA recovery (pr-db3bf10)

## Goal

A sign-off `SIGNOFF_REQA` bounce leaves the PR at `qa` with
`signoff_return.awaiting == "qa"`: an **owed full QA re-run**. Today the only
thing that starts it is in-memory state in one TUI process (or auto-start), so
the obligation is lost when that process restarts, and nothing at all happens
with auto-start off. Make the obligation durable on disk and reconcile it
exactly once, independent of the global auto-start switch.

## Base-branch finding (material)

This workdir is based on the configured base `master`
(`pm/project.yaml:project.base_branch == "master"`, branch cut at
`89e3c501`; reflog confirms). The `defer_reqa_start` machinery named in the
bug (`pm_core/tui/review_loop_ui.py`, `pr-592e4bd` `c9ce4f6a` / QA S117) is
**not** on this base: `_pending_auto_qa`, `_reqa_waiting`,
`defer_reqa_start` and `qa_loop.run_driven_elsewhere` exist only on
`origin/pm/pr-592e4bd-...` (509 commits ahead, unmerged). What *is* on
`master` is the durable half the bug depends on:

- `pm_core/signoff.py:699-830` — `signoff_return` records with
  `awaiting`, `launch_claim`, `claim_return_launch`,
  `clear_return_awaiting`, `open_return`;
- `pm_core/tui/qa_loop_ui.py:108-166` — `start_qa` clears
  `awaiting: qa` when a run actually starts;
- `pm_core/tui/qa_loop_ui.py:407-520` — `_resume_incomplete_qa` restart scan;
- `pm_core/qa_loop.py:945-976` — `resume_owned_elsewhere` (live-owner test).

So on this base the fix is implemented in master's idiom, and it must also
carry the live-run guard that `c9ce4f6a` added on the other branch — without
it, the reconciler would start a TUI loop over a live `pm qa run` and kill
its windows as stale (the S117 duplicate), and the "deferred behind a live
run" case cannot exist at all. A cross-PR note records this for `#249`
(`pr-592e4bd`), whose merge will need to reconcile the two implementations.

## Requirements (grounded)

### R1 — The owed obligation is the persisted return record

An owed full QA is identified **only** by an open sign-off return whose
`awaiting` is `"qa"` on a PR whose status is still `qa`
(`signoff.return_awaiting`, `signoff.open_return`). A bare `qa` status, a
finished run's verdict, or a resolved/cancelled return is not authorization.
`start_qa` already clears `awaiting` (`qa_loop_ui.py:148-150`), so "the
obligation is consumed by an actual start" needs no new bookkeeping.

### R2 — A live run driven by another process is detected durably

New `pm_core/qa_loop.py`:

```python
_RUN_RECORD = "qa_run.json"                 # per QA workdir
def write_run_record(state) -> None         # pr_id, loop_id, session_tag,
                                            # started_at, owner_pid, owner_start
def read_run_record(qa_workdir) -> dict | None
def run_driven_elsewhere(pr_id) -> bool     # any <pr>-*/qa_run.json whose owner
                                            # is a live process (resume_owned_elsewhere)
```

`write_run_record` is called at the top of `run_qa_sync` (right after the QA
workdir is ensured, before planning) and in `resume_qa_sync`, so a run is
visible from its first seconds — earlier than its `qa_resume.json` snapshot
(first written in `_poll_tmux_verdicts`' tail, `qa_loop.py:4306`). The record
is kept after the run ends (a dead pid is not a driver; `owner_start` guards
pid reuse) — same shape as `c9ce4f6a`'s `qa_run.json`, which keeps the two
branches mergeable.

### R3 — Reconciliation independent of auto-start

New in `pm_core/tui/qa_loop_ui.py`:

```python
def owed_reqa_prs(app, prs=None) -> list[dict]
def start_owed_reqa(app, pr_id) -> bool   # claim, then start_qa (one winner)
def reconcile_owed_reqa(app, prs=None) -> None
def arm_owed_reqa(app) -> None            # mount: reconcile + arm the poll timer
```

`reconcile_owed_reqa` runs on the TUI's ~5 s cadence from `poll_qa_state`
(the same throttle as `_resume_incomplete_qa`) and once from
`App.on_mount` via `arm_owed_reqa`, and is **not** gated by
`auto_start.is_enabled` or `in_scope`. For each owed PR it starts the full
QA when:

1. no QA loop of this process is running for the PR
   (`app._qa_loops[pr_id].running`),
2. `run_driven_elsewhere(pr_id)` is false,
3. it wins the on-disk launch claim (R4).

Otherwise it leaves the obligation on disk and logs the deferral once per
return episode: `QA for <pr> starts once the QA run another process drives
ends` (the S127 wording), so the log is not a per-tick repeat.

### R4 — One owner across restarts, ticks and clients

`start_owed_reqa` claims the launch atomically before starting:

- `signoff.claim_return_launch(root, pr_id, hop, require_status=...)` gains an
  optional `require_status` argument so the claim and the "PR is still at
  `qa`" check are one `store.locked_update` (the existing impl/review callers
  are unchanged).
- `start_qa` → `clear_return_awaiting` pops `awaiting` **and** the claim, so
  the winner's start consumes the obligation; losers see either a fresh
  claim (skip) or no `awaiting` (nothing owed).
- A claim whose launcher died expires after
  `signoff.RETURN_LAUNCH_CLAIM_SECONDS` (180 s); the 5 s reconciler takes
  over then, so a restart between the claim and the start cannot strand it.
- `qa` is **not** added to `signoff._CLAIMED_RETURN_HOPS`: the hop that
  defers must not hold a claim, or the reconciler would be blocked for up to
  180 s after the live run ends. Every *starter* claims instead.

### R5 — Every QA-start path honours the same owner

- `pm_core/tui/signoff_ui.py` `step()` qa hop: if `run_driven_elsewhere` →
  do not start, log the deferral, arm the poll timer (the record stays on
  disk); else `start_owed_reqa` instead of a raw `start_qa`.
- `pm_core/tui/auto_start.py` `_auto_start_qa_loops`: skip a PR whose run is
  driven elsewhere; route an owed REQA through `start_owed_reqa`.
- `pm_core/cli/pr.py` `pr_auto_sequence`: the `sign_off` → `qa` hop claims
  before `_launch_qa_detached` and defers (`sign_off: re-qa deferred: a QA
  run is in flight`) when a run is driven elsewhere; the `qa` branch does not
  launch a detached run over a live one.
- `pm_core/cli/pr.py` `pr_qa_run_bg` is unchanged: the tick that claims is the
  hop's driver, and `qa-run-bg`'s `clear_return_awaiting` releases the claim.

### R6 — A pre-return run's PASS does not supersede the owed re-run

`qa_loop_ui._on_qa_complete` (legacy PASS branch) must not hand the PR to
sign-off while `return_awaiting(pr) == "qa"`: that run verified the code
sign-off already judged. The owed run itself is unaffected — its start
cleared `awaiting` before it ran.

### R7 — Evidence is preserved

Nothing in this change deletes sources, dirty files, transcripts, captures,
recordings or drafts. Deferring is what keeps the live run's windows, panes
and transcripts alive (`start_qa`'s planning phase retires stale
`qa-<pr>`/`qa-<pr>-sN` windows, `qa_loop.py:_cleanup_stale_scenario_windows`).

### R8 — S127's assertion

The observable contract is: exactly one driver, exactly one routed full
re-run, no duplicate verifier/finalizer — not a particular cosmetic log line.
Recorded as a note on `pr-592e4bd` for the S127 scenario; this PR does not
edit that branch's captures or widen `#249` acceptance.

## Implicit requirements

- **I1** The reconciler must be cheap when nothing is owed: no project.yaml
  read and no workdir scan beyond one `glob` when no PR carries an open
  `awaiting: qa` return (`app._data` is a valid prefilter; the claim is the
  authority).  This holds for the mount hook too — both callers (mount, the
  sign-off hop) reload the state immediately before arming, so it reads no
  second copy of project.yaml.  After a start, the consumed obligation is
  also dropped from `app._data`, so the tick does not keep re-attempting the
  claim (a full read plus fsynced rewrite of project.yaml) until a reload.
- **I2** It must never start unrelated PRs: no autostart target is restored,
  no `in_scope` check is applied, and only R1-qualifying PRs are considered.
- **I3** It must be idempotent under repeated calls in one process (restart
  loops, several poll ticks) — the claim plus `awaiting` clearing provide it.
- **I4** `start_qa`'s existing behaviours must not regress: `focus=False` for
  scheduler-driven starts (never steal attached clients), the stale runtime
  PASS record drop, and `_ensure_poll_timer`.
- **I5** The mount hook must run after state is loaded and must not block the
  first frame (`start_qa` only spawns the background thread).

## Edge cases

- **Live run ends between the scan and the start**: `run_driven_elsewhere` is
  re-checked inside `start_owed_reqa` before claiming.
- **Run starts after the check** (a `pm qa run` launched in the same second):
  the run record is written at the top of `run_qa_sync`, so the next tick
  defers; the previous tick's start already consumed `awaiting`, so at most
  one TUI start exists. (Same exposure the S117 fix has.)
- **PR leaves `qa`** (merged, closed, back to `sign_off`/`in_review`): the
  claim's `require_status="qa"` refuses; the reconciler skips.
- **Return resolved or cancelled** (`awaiting` cleared, `resolved_at` set,
  `open_return` None): nothing owed.
- **Repeated restarts**: first start clears `awaiting`; later processes find
  nothing. A restart inside the claim window waits out the claim (180 s) and
  then starts — never two starts.
- **Two TUIs / a grouped client**: only the claim winner starts.
- **PR with no workdir**: still reconciled (`run_qa_sync` provisions it via
  `_ensure_workdir`), and `arm_owed_reqa` arms the poll timer so the tick
  exists even when `ensure_animation_timer` skipped it.
- **QA already running in this TUI** (`app._qa_loops[pr_id].running`): skip
  silently (the user's `t`/`zz t` owns it).
- **`skip_qa` projects**: a REQA bounce is impossible (sign-off is only
  reachable through QA), so no special case.
- **Self-driving QA** (`zz t`): `start_or_stop_qa_loop` starts its run
  without going through `start_qa`, so it clears `awaiting` itself.  That
  loop *is* the full re-run the bounce asked for; leaving the record behind
  would make the reconciler start a second full run once the loop ends.
  (`z t` and plain `t` go through `start_qa`, which clears it.)

## Test plan

`tests/test_owed_reqa.py` (new) plus additions to
`tests/test_tui_signoff_handoff.py` and `tests/test_qa_resume.py`:

1. `run_driven_elsewhere`: live foreign owner (a `sleep` child) → True; own
   pid → False; dead pid → False; pid reuse (owner_start mismatch) → False;
   no record → False.
2. Deferred hop (auto-start on, live run) → no `start_qa`, record keeps
   `awaiting: qa`, deferral logged; restart into a fresh app with auto-start
   **off** → still deferred while live; run ends → exactly one start, second
   reconcile is a no-op.
3. Restart-only case: a background tick wrote `awaiting: qa`, auto-start off,
   no targets → reconcile starts once.
4. Bare `qa` status (no return record) → nothing.
5. Cancelled/resolved return, PR moved off `qa` → nothing.
6. Claim single-owner: a fresh foreign claim blocks; after
   `RETURN_LAUNCH_CLAIM_SECONDS` the reconciler takes over; two app
   instances → one start.
7. `_on_qa_complete` PASS while `awaiting: qa` → no sign-off hand-off.
8. `_auto_start_qa_loops` skips a driven-elsewhere PR and routes a REQA
   through the claim.
9. Wiring, not just the writer: `run_qa_sync` writes the run record before
   planning, and `resume_qa_sync` rewrites it for the new driver.
10. `arm_owed_reqa` (mount hook) arms the poll tick and starts the owed run;
    with nothing owed it starts nothing and reads no project.yaml.
11. A started obligation is dropped from `app._data` (no repeated claim
    attempts after the run ends), and `zz t` consumes it like `start_qa`.

## Manual verification

The impl container has no host pm state, tmux pm session or TUI (only
`/workspace`, `/opt/pm-src`, `/pm-captures`), so the end-to-end TUI repro is
QA's to run on the host. Shipped instead, and recorded with the
`cli-recording` recipe:

- `/pm-captures/impl/pre-fix/codified-repro/` — the tests against pre-fix
  code: `24 failed, 35 passed`, including
  `Expected 'start_qa' to be called once. Called 0 times.` for the repro.
- `/pm-captures/impl/post-fix/verify/` — the same tests plus the related
  suites against the fix: `294 passed`.

Host steps for QA: auto-start OFF, PR in `sign_off`, start
`pm qa run <instr> --pr <id>`, let sign-off record `SIGNOFF_REQA`, restart the
TUI before the CLI run exits. Expected: the restarted TUI logs
`Sign-off REQA for <pr> — QA starts once the QA run another process drives
ends` on its first tick, the live run is left alone, and when it ends exactly
one full QA starts (one `qa-<pr>` window set, one verifier, one finalizer, one
`qa_status.json`) — with no `t` press and with auto-start still off.

## Existing tests adjusted

- `tests/test_signoff_integration.py::test_tui_qa_pass_not_handed_to_signoff_while_reqa_awaits`
  — its `FakeApp` has no `project.yaml` to claim in, so the test now patches
  `signoff.claim_return_launch`; the assertion it exists for (the owed REQA
  run starts instead of the sign-off hand-off) is unchanged, and the claim
  itself is covered by `tests/test_owed_reqa.py`.
- `tests/test_owed_reqa.py` patches `qa_loop.run_driven_elsewhere` with
  `create=True` so the pre-fix run fails on the symptom rather than on a
  missing attribute.
