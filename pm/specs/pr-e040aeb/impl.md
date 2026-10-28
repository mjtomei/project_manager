# pr-e040aeb — native retry of a failed authorized review launch

Bug: after a verdict is collected, the native review loop launches the next
iteration.  That launch first closes the historical review window and then
removes/re-creates the review container.  If the teardown/setup fails, the
`pm pr review` child exits non-zero before the new session produces a
transcript.  `run_review_loop_sync` treats that as a terminal `ERROR`, and the
auto-start scheduler then skips the PR forever because `app._review_loops` still
holds a (non-running) entry.  The target stays stopped until a shepherd sends
`review-loop start` by hand.

This change gives the native loop a bounded, observable, serialized retry of a
*genuinely failed authorized review launch*, preserving loop history and every
piece of surrounding state, and leaves an explicit retryable failure (never a
fabricated agent verdict) when retries are exhausted.

## Requirements (grounded in code)

1. **Classify launch failures instead of ending the loop immediately**
   (`pm_core/review_loop.py`).
   - `_launch_review_window` (the parent-side subprocess runner) already raises
     `RuntimeError` on a non-zero `pm pr review` child.  Introduce
     `ReviewLaunchError(RuntimeError)` carrying `returncode`, `stderr`,
     `stdout`, `artifact`, `retryable`, `reason`; raise it for:
     - child exit non-zero (container teardown/setup failure, route down, …),
     - `subprocess.TimeoutExpired` (the 120 s launch timeout),
     - "review window not found after launch",
     - "transcript symlink exists but no session id / no transcript produced".
   - Do **not** retry a `PaneKilledError` (cancellation / window closure), a
     real agent verdict, or a workspace-trust/permission hold.
   - `ReviewHoldError` classifies a trust/permission/auth hold; `ReviewClosedError`
     classifies a PR that merged/closed while retrying.

2. **Bounded retry inside the loop** (`run_review_loop_sync`).
   - Before *every* attempt (including the first after a failure) run
     `_discover_iteration(...)`.
   - Retry the *same* iteration number (`state.iteration` is not advanced again)
     with exponential backoff `5 s` then `10 s` (`REVIEW_LAUNCH_BACKOFF_BASE`
     doubled per attempt, capped at 60 s), up to
     `REVIEW_LAUNCH_MAX_ATTEMPTS = 3` attempts.  The sleep is chunked
     (≤0.25 s) and checks `state.stop_requested` and PR terminal status, so
     cancellation is prompt and the TUI event loop is never blocked (the retry
     runs on the loop's existing background thread).
   - The attempt budget and next-retry deadline persist on `ReviewLoopState`
     (`launch_attempts`, `retry_iteration`, `next_retry_at`,
     `last_launch_error`, `last_launch_artifact`, `launch_retryable`) so a
     merge-restart resume continues the same episode instead of restarting it.

3. **Rediscover before each retry** (`_discover_iteration`).
   - Recover this iteration's transcript symlink and session id, and look for
     the live review window/pane (prefer the pane whose start command carries a
     `--session-id`, via `pane_transcript_path`, falling back to the shared
     first-pane helper).
   - Outcomes:
     - `verdict` — the failed attempt recovered (or another driver finished):
       adopt the transcript's verdict, do not launch.
     - `adopt` — a live pane whose session matches this iteration, or another
       driver's live review session (no other *loop* owner): poll it instead of
       launching a duplicate.
     - `other_owner` — another native loop (different `loop_id`) holds the
       launch lease: bow out rather than duplicate/supersede it.
     - `pending` — a pane exists but has not exposed its session yet: bounded
       grace, then re-discover.
     - `launch` — nothing live (or only the historical window): launch
       `--fresh` as today.
   - A pane matching the *historical* iteration's session (`state.last_session_id`
     or a lower-numbered transcript) is not adopted; it is replaced by the fresh
     launch, preserving the existing semantics.
   - Another driver's live session is adopted (and its landed verdict read)
     only once *this* loop has launched the iteration (`allow_recovery`); on
     the first attempt an unknown pane is the historical window and is
     replaced.
   - There is no `hold` discovery kind: a workspace-trust/permission prompt is
     detected while polling (`WorkspacePromptWatch` → `WorkspaceTrustBlocked`)
     and converted to `ReviewHoldError` → `HOLD` on both the launch and adopt
     paths.  (Review 385e i2 removed the never-produced kind and its dead
     handlers.)

4. **Serialize retry ownership across drivers and restarts**
   (`pm_core/runtime_state.py`, `pm_core/cli/pr.py`).
   - Add an owner lease to the existing per-PR `runtime_state` action
     (`claim_action_lease` / `release_action_lease` / `get_action_lease`), using
     the same flock-protected read-modify-write.
   - The native loop claims `owner = "loop:<loop_id>"` before each launch and
     refreshes it (every ~30 s) while polling, so a long review keeps ownership.
     A loop whose claim is lost (superseded by `zz d` / another loop) stops
     instead of relaunching over the new owner.  The lease is released when the
     loop completes.
   - `pm pr auto-sequence` checks the lease before launching a review iteration
     in its `in_review` branch; a live `loop:` lease means the native loop owns
     the launch, so the tick reports `running: review` and does not start a
     duplicate.  A dead TUI leaves the lease to expire (TTL 180 s); the TUI
     mount sweep (`sweep_stale_states`) clears it on restart.

5. **Observability: artifact + concise UI error**
   - Write a complete launch artifact for every failed attempt under
     `<transcript_dir>/launch-artifacts/`:
     timestamp, PR/iteration/loop id/attempt, exact command, return code, full
     stdout and **full stderr** (no truncation), plus a copy of the failed
     attempt's prompt file (`<workdir>/pm/prompts/pm_prompt_<sid>.txt`) when it
     exists.  The artifact path is included in the error and persisted.
   - Keep the UI error concise (last meaningful stderr line, capped ~300 chars)
     and include the artifact path.  `runtime_state` records `verdict`,
     `retryable`, `attempts`, `error`, `artifact`, `retry_ready_at`; the TUI log
     announces each retry and the terminal failure; `pm autostart status` /
     the runs popup show `review launch failed (retryable): … [artifact: …]`
     (the bracketed suffix only when the concise error does not already name
     the artifact).
   - New loop outcomes (never agent verdicts): `LAUNCH_FAILED`, `HOLD`,
     `CLOSED`.  `history` gains **no** entry for a failed launch.

6. **Do not strand an auto-start target after exhaustion**
   (`pm_core/tui/auto_start.py`, `pm_core/tui/review_loop_ui.py`).
   - `_auto_start_review_loops` may re-arm a non-running loop whose last outcome
     was a *retryable* launch failure, after `retry_ready_at` (60 s), by calling
     `_start_loop(..., resume_state=state)` — history and iteration numbering
     are preserved and only the un-completed iteration is retried.
   - Cap consecutive re-arm episodes (5); after that the explicit retryable
     failure stays (manual `review-loop start` or a new loop resets it).
     Cancellation (`KILLED`), holds, closures and non-retryable errors never
     re-arm.  Re-arming only happens for a PR in auto-start scope: a loop for
     a PR outside the target set (e.g. a manual loop on an unscoped PR) keeps
     its explicit failure for the user.
   - `_poll_loop_state_inner` schedules one timer for the cooldown so the
     re-arm happens without waiting for an unrelated event.

7. **Preserve everything the retry must not disturb.**
   - The retry reuses the same `pm pr review --fresh --review-loop
     --review-iteration N --review-loop-id L --transcript T` command, so the
     complete prompt, source snapshot, dirty metadata, stashes, captures mount,
     and assigned provider/model/effort are exactly what the child computes for
     the PR; the retry never runs `git clean`/`stash` and never touches
     `stop_before_merge` / merge holds.  It only replaces the PR's own review
     window (never QA/discussion windows) and never re-runs a completed
     iteration.

## Implicit requirements

- `ReviewLoopState` is the unit of persistence; the breadcrumb
  (`autostart-resume.json`) must round-trip the new retry fields and the last
  adopted pane/session so a merge-restart resume both continues the bounded
  budget and can tell the historical window from a live attempt.
- `_adopt_in_flight_review` (restart handoff) must share the discovery logic so
  a resumed loop never polls the wrong session (today it polls its own symlink
  even when another owner's pane is live).
- `set_action_state` must keep merging (not clobber) the lease; the lease helper
  must be atomic and tolerant of a missing/corrupt runtime file.
- The TUI poll (1 s) is the only main-thread place that can log/schedule; retry
  notices and the re-arm timer go there, not in the loop thread.
- Status derivation must treat the new outcomes as failures with actionable
  reasons, not as `PASS`/`NEEDS_WORK`, and `_progress` must not show a stale
  iteration as if it succeeded.
- Existing tests that mock `_run_claude_review`, `_find_claude_pane`,
  `_launch_review_window` and `subprocess.run` must keep working: new
  parameters need defaults; discovery must fall back to `_find_claude_pane`
  when no window can be found.

## Ambiguities and resolutions

1. **Retry budget scope** — per failed launch episode (3 attempts) rather than a
   lifetime cap.  Persisted so a restart mid-backoff continues it.  Auto-start
   may open a new episode after a cooldown (bounded to 5 episodes); a manual
   loop gets one episode and an explicit retryable failure.
2. **Artifact location** — the per-run transcript dir (survives via the
   breadcrumb and is unique per auto-start/manual run), not the QA captures
   tree (captures are planner-only evidence).  Path is surfaced in the UI.
3. **Another driver's live review** — adopt its verdict/pane rather than kill
   it, unless another *native loop* owns the lease; this covers a sign-off route
   or `pm pr auto-sequence` racing a scheduled retry without duplicating work.
4. **Auth/route failures** — a workspace-trust/permission prompt is a hold (no
   retry); an API/auth error (`unauthorized`, `401`, `not logged in`) is
   non-retryable; a transient route/container failure is retryable.  The exact
   low-level teardown exception is unknown (the launch log was truncated), so
   classification is by symptom, not by a single exception type.
5. **Historical window identification** — use the last adopted session id
   (`ReviewLoopState.last_session_id` / `stale_session_id`) plus lower-numbered
   iteration transcripts; unknown panes fall back to today's `--fresh`
   replacement semantics.

No [UNRESOLVED] ambiguities.

## Edge cases / regressions to cover

- Failure before pane creation (container setup fails immediately).
- Old window removed, then container setup fails; retry must create a fresh
  window and succeed.
- A route/native recovery launches while a retry is scheduled: retry discovers
  and adopts, never launches a duplicate.
- TUI merge-restart during backoff: resumed loop continues the same budget and
  deadline, preserves history, and only retries the un-completed iteration.
- A healthy unrelated review continues unaffected (per-PR state only).
- Cancellation (`stop_requested`, `z d`, `zz d`) during backoff prevents the
  retry; the loop ends `KILLED`.
- Successful replacement executes the original complete task on the assigned
  provider and collects its own verdict (same iteration, loop id, transcript).
- PR merged/closed during backoff stops with an explicit `CLOSED` outcome.
- Trust/permission hold stops with `HOLD` (no retry).
- Exhaustion leaves `LAUNCH_FAILED` with `retryable=True`, full artifact, and no
  fabricated verdict / no history entry.
- Auto-start target is re-armed after the cooldown (not stranded), up to the
  episode cap; manual loops and `KILLED`/`HOLD` are not re-armed.
- `pm pr auto-sequence` does not launch over a live native-loop lease.

## Review iteration 1 (385e) — refinements

Findings from the first review pass, applied on top of the implementation:

1. **Stale transcript adoption (correctness fix).** Requirement 3's "recover
   this iteration's transcript symlink and session id" was unconditional, but
   the transcript dir outlives a loop (`manual-<token>` lives for the whole TUI
   session, and an auto-start run dir is reused across re-arms).  A *new* loop
   on the same PR therefore rediscovered the previous run's
   `review-<pr>-i<N>.jsonl` and adopted its verdict — a `PASS` from a run that
   had already finished — launching no review at all.  `_discover_iteration`
   now takes `allow_recovery`, and `_run_iteration_with_retry` passes it False
   until *this* loop has launched the iteration (`ReviewLoopState.iteration_attempted`,
   persisted in the breadcrumb; `launch_attempts > 0` also enables it for
   pre-existing breadcrumbs).  Recovery/adoption is unchanged after a genuine
   failed attempt, including across a re-arm.
2. **Retry notice gated on a real retry.** `launch_attempts` is 1 for a normal
   first launch, so the poll tick announced "Review launch retry … (attempt 1)"
   on every loop start (and again after each iteration whose attempt count had
   climbed).  The notice now requires `attempts > 1` *and* a recorded
   `last_launch_error`.
3. **Trust hold on the adopt path.** The adopt branch polls the pane directly,
   so a `WorkspaceTrustBlocked` there surfaced as `ERROR`; it is now converted
   to `ReviewHoldError` → `HOLD`, matching `_run_claude_review`.
4. **Re-arm cannot silently disarm.** `_start_loop` returns False when it bails
   (missing PR/workdir, no tmux, unusable transcript dir).  Auto-start clears
   the retry episode *before* starting the thread (it must not resume the spent
   budget), so it now restores the saved episode fields when the start does not
   happen, keeping the failure retryable instead of stranding the target.
5. **Cooldown timer is self-healing.** `_schedule_retry_rearm` was armed once;
   if that single timer fired before `retry_ready_at` (or the pass found the
   PR still cooling), nothing re-armed it and the target waited for an
   unrelated TUI event.  `_auto_start_review_loops` now keeps a timer armed for
   as long as the cooldown is running (never at the episode cap).
6. **Claim "fail open" is real.** `claim_action_lease` returns False both for
   "another loop owns it" and for "the runtime file could not be written"; the
   loop stood down for either, stranding the target on an unwritable state
   dir.  `_claim_launch` now stands down only when another live loop actually
   owns the lease.
7. **Failure artifacts carry the command.** The post-launch failures ("window
   not found", "no transcript session id") wrote `cmd: []`; they now record
   the launch command `_launch_review_window` returned, and `returncode: None`
   since no child exited non-zero.

## Review iteration 2 (385e) — refinements

Findings from the second review pass, applied on top of iteration 1:

1. **Another driver's live review is adopted on a retry (correctness fix).**
   Iteration 1's `allow_recovery` gate made the *first* attempt replace an
   unknown pane (correct), but it also left the retry path replacing one:
   after a launch failed *before* creating a transcript, `our_sid` is None and
   `_discover_iteration` fell through to `launch` even though this loop had
   launched the iteration — so a sign-off route (or another non-loop driver)
   racing a scheduled retry had its live review killed by the retry's
   `--fresh`.  When `allow_recovery` is true and a live pane's session is not
   historical, discovery now reads its verdict or adopts it for polling
   (regression "route/native recovery racing a scheduled retry").  The
   historical-window check is now meaningful instead of both branches
   returning `launch`.
2. **No `hold` discovery kind.** `AttemptDiscovery("hold")` was never produced,
   leaving three unreachable handlers.  Trust/permission holds are detected by
   the poller (`WorkspacePromptWatch` → `ReviewHoldError`) on both the launch
   and adopt paths; the dead kind and handlers were removed.
3. **Progress label is not a retry on the first attempt (UI fix).**
   `_progress` printed `review #N (launch retry 1)` for every running review
   because `launch_attempts` is 1 after a normal launch.  It now requires
   `attempts > 1`, matching the TUI notice's gate.
4. **Lease kept alive through INPUT_REQUIRED.** The follow-up wait could
   outlast the 180 s lease TTL, letting another driver treat the loop as dead.
   `_wait_for_follow_up_verdict` now refreshes the lease too, and a stopping
   loop (`stop_requested`) never refreshes it, so a superseding loop's claim
   cannot be stolen back by the loop it replaced.
5. **Trust hold on the restart handoff.** `_adopt_in_flight_review` (the
   breadcrumb-resume handoff) polls the pane directly, so a
   `WorkspaceTrustBlocked` there surfaced as a terminal `ERROR` (no re-arm).
   It now converts to `ReviewHoldError` → `HOLD`, matching every other adopt
   path.

## Review iteration 3 (385e) — refinements

Findings from the third review pass, applied on top of iteration 2:

1. **A failed launch must not adopt a previous run's transcript
   (correctness fix).** Iteration 1 gated transcript recovery on
   `allow_recovery`, but that flag turns on *after* this loop's first
   attempt fails — and a launch that fails before the child writes the
   symlink leaves the shared transcript dir's older
   `review-<pr>-i<N>.jsonl` in place.  The retry then read that earlier
   run's verdict (a `PASS`, for instance) and recorded it for an iteration
   that never ran: exactly the fabricated verdict requirement 1 forbids.
   `ReviewLoopState.stale_session_id` now snapshots the symlink's session
   id when the iteration's episode starts (persisted in the breadcrumb);
   `_discover_iteration` only treats the symlink as this attempt's when its
   session id differs, and `_is_historical_session` treats the stale id as
   historical so a live pane running it is replaced, not adopted.
   `tests/test_review_launch_retry.py::test_retry_never_adopts_a_previous_runs_transcript`
   covers it; `test_retry_adopts_a_verdict_that_landed_after_the_failure`
   now models a transcript created *by* the failed attempt.
2. **The retry notice is keyed per episode.** `_ui_notified_retry` was
   only reset when a loop (re)started, so a later iteration's attempt 2
   was swallowed as already-announced.  `_reset_launch_retry` (run after
   every successful iteration) clears it.
3. **Dead parameter removed.** `_retry_rearm_blocked(app, loop)` ignored
   `app`; it is now `_retry_rearm_blocked(loop)`.

Note (not changed): a child auth failure (`_looks_like_auth_failure`) is a
non-retryable `LAUNCH_FAILED`, not `HOLD`.  `HOLD` stays reserved for a
pane sitting at a workspace-trust/permission prompt (the launch succeeded);
an auth-rejected child never launched a session.

## Review iteration 4 (385e) — refinements

Findings from the fourth review pass, applied on top of iteration 3:

1. **A container "permission denied" is a retryable launch failure, not an
   auth hold.** `_AUTH_FAILURE_RE` matched `permission denied`, so a
   teardown/mount failure that reports it (a realistic podman/docker
   symptom) was classified non-retryable: the loop stopped after one attempt
   and auto-start did not re-arm — re-creating the stranded target this PR
   exists to fix.  The pattern now covers only real auth/trust symptoms
   (`unauthorized`, `not logged in`, `authentication failed`, `invalid api
   key`, `401`, `403`, `workspace trust`, `trust prompt`).
2. **A starting pane is not killed by a retry.** In the no-own-transcript
   branch, discovery only handled a pane that had already exposed a session
   id; a live pane with no session id yet (a just-started recovery or
   another driver's launch racing the retry) fell through to `launch` and
   was replaced by `--fresh`.  When `allow_recovery` is set it now returns
   `pending`, so the bounded grace applies here too; the first attempt of an
   iteration this loop has not launched still replaces the window.
3. **`_start_loop` marks the loop running synchronously.** The 1 s poll (and
   a second starter — the breadcrumb resume running right after
   `check_and_start` re-armed the same loop) could observe a non-running
   loop between `_start_loop` and the thread body, re-announcing a stale
   terminal verdict or starting a duplicate loop thread.  `state.running` is
   set before `start_review_loop_background`.
4. **Stale retry evidence is cleared on completion.** A loop that succeeded
   after a re-armed failure left the previous episode's `retryable` /
   `error` / `artifact` / `attempts` / `retry_ready_at` in `runtime_state`;
   the completion mirror now drops them for non-failure outcomes.
5. **CLOSED while waiting for another loop's lease.** If the PR merged while
   the loop waited out another loop's lease, it reported a non-retryable
   `LAUNCH_FAILED`; it now re-checks terminal status and reports `CLOSED`.
6. **`_reset_launch_retry` clears `retry_ready_at`** so a spent re-arm
   deadline cannot leak into the next episode (or the breadcrumb).
7. **A raising re-arm starter also restores the episode.** `_start_loop`
   returns False for its own bail-outs, but a raise (e.g. a missing project
   root) escaped with the retry episode already cleared, silently disarming
   the failure.  `_auto_start_review_loops` now treats a raise like a False
   return and restores the saved episode fields.

## Review iteration 5 (385e) — refinements

Findings from the fifth review pass, applied on top of iteration 4:

1. **A failed launch must not adopt the *historical pane's* verdict
   (correctness fix).** Iterations 1 and 3 stopped rediscovery from adopting
   a stale transcript *symlink*, but the same fabrication was still reachable
   through the live pane.  `build_claude_shell_cmd` writes the iteration's
   transcript symlink *before* the child removes the historical window and
   creates the new one, so a launch that fails after the symlink is written
   but before the window is replaced leaves a live pane running the
   *previous* iteration's session.  In the `our_sid` branch (our symlink is
   new, so `our_sid != stale_session_id`) `_discover_iteration` treated any
   other live session as "another driver's review" and returned its verdict —
   i.e. iteration N's `NEEDS_WORK`/`PASS` was recorded for iteration N+1,
   which never ran.  It now consults `_is_historical_session` there too and
   returns `launch`, replacing the stale window exactly as the no-`our_sid`
   branch already did.  Covered by
   `test_discovery_never_adopts_a_historical_pane_after_a_failed_attempt`
   and `test_retry_never_adopts_a_historical_panes_verdict` (both fail
   pre-fix).
2. **The `pending` grace is observable.** `AttemptDiscovery.reason` was set
   but never read; the retry's pending branch now logs it (and the
   "pane never exposed a session" replacement) instead of sleeping silently.
3. **A bare `401`/`403` token is not an auth failure.** `_AUTH_FAILURE_RE`
   still matched the HTTP codes anywhere in the child's stderr, so a 3-digit
   pid, id or port in a container teardown error (e.g. `process 403 exited`,
   `container pm-review-401 not found`) classified a transient failure as a
   non-retryable auth hold — the same re-stranding failure mode iteration 4
   fixed for `permission denied`.  The codes now only count with auth/HTTP
   context (`http`/`api`/`auth`/`status`/`response` within 20 chars, or
   `401 unauthorized` / `403 forbidden`); `forbidden` is matched directly.
   `test_bare_http_code_lookalikes_stay_retryable` covers both directions.
4. **Dead local removed.** `_start_loop`'s unused `mode_label` (pre-existing)
   is gone.

## Review iteration 6 (385e) — refinements

Findings from the sixth review pass, applied on top of iteration 5:

1. **The restart handoff shares the fabrication guard (correctness fix).**
   `_adopt_in_flight_review` called `_discover_iteration` with the default
   `allow_recovery=True`, bypassing iterations 1/3's gate.  A merge restart
   landing in the window between the iteration counter bump and the first
   launch attempt persists `iteration_attempted=False`; on resume the handoff
   could then adopt a previous run's `review-<pr>-i<N>.jsonl` verdict for an
   iteration this loop never ran.  It now passes
   `allow_recovery=iteration_attempted or launch_attempts > 0`, matching
   `_run_iteration_with_retry`.  Covered by
   `test_restart_handoff_does_not_adopt_a_transcript_this_loop_never_launched`.
2. **The handoff falls back to a relaunch when the transcript has no session
   id.** The iteration-2 refactor dropped the old `if not session_id: return
   None` guard, so an adopted transcript whose session id could not be
   recovered went on to `poll_for_verdict`, which raises — turning a
   recoverable race into a terminal `ERROR`.  It returns `None` (the loop
   relaunches) again.  Covered by
   `test_restart_handoff_relaunches_when_the_transcript_has_no_session`.
3. **The retry's adopt path re-reads a just-landed verdict.** The poller only
   wakes on idle events *newer* than its own start, so a verdict that landed
   between discovery and `_poll_for_verdict` would be waited on until the
   pane died.  Both adopt paths now share `_landed_verdict()` (idle event +
   transcript read) before polling; the restart handoff used to inline the
   same check.  Covered by
   `test_retry_adopt_reads_a_verdict_that_landed_before_the_poll`.
4. **Auth classification reads both streams.** `stderr or stdout` ignored a
   real auth error printed on stdout whenever stderr carried any warning, so
   an auth failure was retried (and re-armed) as transient.  The classifier
   now sees `stderr + "\n" + stdout`.  Covered by
   `test_auth_failure_reported_on_stdout_is_not_retryable`.
5. **`_wait_for_claim` claims the iteration it is retrying.** It used
   `state.iteration`; it now takes the iteration explicitly (the only caller
   passes the same value, but the lease metadata must name the iteration
   being launched, not whatever the shared state holds).
6. **A failed thread start no longer leaves the loop "running".**
   `_start_loop` set `state.running = True` before
   `start_review_loop_background`; if the thread could not start, the poller
   and the auto-start scheduler treated the dead loop as live forever.  The
   flag is cleared on the exception path.  Covered by
   `test_start_loop_clears_running_when_the_thread_cannot_start`.
7. **`_review_retry_timer` is declared on the app** (`App.__init__`), like
   `_review_loop_timer`, instead of being created lazily by `getattr`.
8. **An adopted session is remembered as historical (correctness fix).**
   `AttemptDiscovery` now carries the `session_id` its verdict/pane came from,
   and both callers record it on `ReviewLoopState.last_session_id`.  Without
   it, an iteration that adopted another driver's still-live pane (a sign-off
   route racing a retry) left the next iteration rediscovering the same idle
   pane: `_is_historical_session` did not know it, so the loop either adopted
   the same verdict again or waited on an idle event that would never come.
   Covered by `test_adopted_verdict_records_the_session_as_historical` and
   `test_discovery_treats_the_last_adopted_session_as_historical`.

Not changed (documented residuals): `review_loop.py` is ~1360 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); the retry re-arm's `_progress` label can
show the previous episode's attempt count while the resumed loop runs.

## Review iteration 7 (385e) — refinements

Findings from the seventh review pass, applied on top of iteration 6:

1. **An adopted pane is polled without the startup grace (hang fix).** The
   retry's adopt path passed `grace_period=_VERDICT_GRACE_PERIOD` (20 s), but
   the adopted session was launched *before* the poll: the startup
   false-positive window the grace protects against has already passed.
   `poll_for_verdict` discards an idle event that arrives inside the grace and
   then waits for a *second* event, which an idle session never emits — so a
   review finishing shortly after adoption hung until its pane died.  The
   adopt path now uses the default (0), matching `_adopt_in_flight_review` and
   the `_landed_verdict` pre-check.  Covered by
   `test_retry_adopt_polls_without_the_startup_grace`.
2. **The terminal notice only promises a retry that will happen.** The
   LAUNCH_FAILED announcement said "Will retry automatically" for every
   retryable failure, including a manual loop, a PR outside the auto-start
   target set, auto-start disabled, and the episode cap — none of which
   re-arm.  `_retry_rearm_applies()` now backs both `_schedule_retry_rearm`
   and the message, which points at `review-loop start` when nothing will
   retry.  Covered by
   `test_launch_failure_notice_does_not_promise_a_retry_outside_auto_start`
   and `test_launch_failure_notice_promises_the_retry_for_an_auto_start_target`.
3. **Dead `last_pane_id` removed.** The field was written, persisted in the
   breadcrumb and never read: discovery identifies the historical window by
   *session* id (`last_session_id` / `stale_session_id`) and lower-numbered
   transcripts, never by pane id.

Not changed (documented residuals): `review_loop.py` is ~1390 lines; two
lease mechanisms coexist; the retry re-arm's `_progress` label can show the
previous episode's attempt count while the resumed loop runs; the launch
artifact's prompt copy can name the stale session's prompt when the failed
attempt died before rewriting the transcript symlink (the artifact records
that session id, so the mismatch is visible).

## Review iteration 8 (385e) — refinements

Findings from the eighth review pass, applied on top of iteration 7:

1. **A TUI restart mid-retry no longer resets the retry budget
   (correctness fix).** `consume_breadcrumb` restored loop state before
   `check_and_start` but resumed (started) the loops after it.  A re-armed
   loop keeps `latest_verdict == LAUNCH_FAILED` and `launch_retryable` while
   it runs, so a restored-but-not-yet-started loop looked exactly like a
   *completed* retryable failure: `_auto_start_review_loops` re-armed it,
   clearing `launch_attempts` (fresh 3-attempt budget), dropping the
   remaining backoff and burning one of the bounded episodes.  The resume now
   runs *before* the scheduler pass; `_start_loop` marks the loop running
   synchronously, so the pass skips it and the saved budget/deadline is
   honoured (requirement 2's "merge-restart resume continues the same
   episode").  Covered by
   `tests/test_breadcrumb_review_loop.py::TestConsumeBreadcrumbReviewLoops::
   test_restored_loop_is_running_before_the_scheduler_pass` (fails pre-fix).
2. **Cancellation while waiting for another loop's lease is KILLED, not
   LAUNCH_FAILED.** `_wait_for_claim` returns False both for "another loop
   still owns the lease" and for "the loop was cancelled while waiting"; the
   second surfaced as a non-retryable LAUNCH_FAILED ("needs attention")
   after a user stop.  It now raises `PaneKilledError` → `KILLED`, matching
   the other cancellation paths.  Covered by
   `test_cancellation_while_waiting_for_the_lease_is_killed` (fails
   pre-fix).
3. **A HOLD records the hold's own message.** `_on_complete_from_thread`
   wrote `last_launch_error or latest_output` for `HOLD`, so a hold that
   followed a retried attempt reported the earlier attempt's launch error in
   `pm autostart status` instead of the trust/permission prompt the loop is
   sitting at.  It now prefers `latest_output`.  Covered by
   `test_hold_records_the_hold_message_not_a_stale_launch_error` (fails
   pre-fix).
4. **Dead condition removed.** The retry notice also required
   `latest_verdict != VERDICT_PASS`; a loop stops on PASS, so a running
   retry never carries a PASS verdict — the condition was unreachable.
5. **Artifact header reports characters.** The stderr/stdout section headers
   said "bytes" while measuring `len()` of a decoded string.

Not changed (documented residuals): `review_loop.py` is ~1395 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); the retry re-arm's `_progress` label can
show the previous episode's attempt count while the resumed loop runs; the
launch artifact's prompt copy can name the stale session's prompt when the
failed attempt died before rewriting the transcript symlink.

## Review iteration 9 (385e) — refinements

Findings from the ninth review pass, applied on top of iteration 8:

1. **A HOLD names the hold prompt in the live status path too.**
   Iteration 8 made `_on_complete_from_thread` record `latest_output` for
   `HOLD` in `runtime_state`, but `pm autostart status` is built from the
   *live* loop state via `autostart_state.review_progress_input`, which still
   reported `last_launch_error`.  A hold that followed a retried attempt
   therefore showed the earlier attempt's launch error instead of the
   trust/permission prompt.  `review_progress_input` now prefers
   `latest_output` for `HOLD`, matching the mirror.  Covered by
   `test_autostart_status_reports_the_hold_prompt_not_a_stale_launch_error`.
2. **The restart-handoff adopt path owns the launch lease from its first
   poll.** `_adopt_in_flight_review` polls a live review without going
   through `_claim_launch`, and `_lease_keepalive` only refreshed after
   `_LEASE_REFRESH_SECONDS` (30 s), so for that window
   `review_loop_owns_launch()` reported no owner and another driver could
   launch over the adopted session.  The keepalive's first check now claims
   immediately (a stopping loop still never claims).  Covered by
   `test_lease_keepalive_claims_on_the_first_check`.
3. **The artifact no longer attaches a previous run's prompt.** The
   documented iteration-7 residual: a launch that died before the child
   rewrote the iteration's transcript symlink left the *previous* session in
   place, and the artifact copied that session's prompt file — evidence from
   the wrong attempt.  `stale_session_id` is now threaded into
   `_launch_review_window`/`_write_launch_artifact`; when the symlink still
   names it the artifact records `prompt: (skipped — …)` instead of a copy.
   Covered by `test_artifact_does_not_copy_a_stale_sessions_prompt`.
4. **A no-op lease mutate writes nothing.** `_locked_action_mutate` always
   wrote the action entry back with a fresh `updated_at`, so releasing a
   lease this owner never held created a `{updated_at}` stub (a phantom
   runs-popup entry) and a lost claim rewrote another loop's entry.  The
   write is skipped when the mutator changed nothing.  Covered by
   `test_release_without_a_matching_owner_leaves_no_stub_entry`.

Not changed (documented residuals): `review_loop.py` is ~1400 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); the retry re-arm's `_progress` label can
show the previous episode's attempt count while the resumed loop runs.
Discovery still adopts a transcript verdict without requiring an idle hook
event (`_verdict_output_if_present`); the extractor only matches a bare
verdict keyword on its own JSON-string-bounded line, so a mid-turn
fabrication would need the reviewer to emit a bare verdict line and keep
talking, and requiring an idle event would strand completed reviews on hosts
without hooks installed.

## Review iteration 10 (385e) — refinements

Findings from the tenth review pass, applied on top of iteration 9:

1. **A retry must not adopt the window that was already open when the
   episode started (correctness fix — fabricated verdict).** Iterations 1,
   3 and 5 stopped rediscovery from adopting a stale *symlink* or a pane
   whose session was identifiable as historical (`last_session_id`,
   `stale_session_id`, a lower-numbered transcript).  Nothing identified a
   *pre-existing review window* for iteration 1 of a fresh loop: its
   transcript dir is new (no symlink) and there is no `last_session_id`, so
   a first attempt that fails **before** `--fresh` replaces the window
   (route down, workdir gone, a tmux error on the kill — the child returns
   before the kill or raises during it) left that window live, and the
   retry adopted its older review's verdict — e.g. `PASS` — for an
   iteration that never ran, with zero launches.  `ReviewLoopState`
   now snapshots `stale_pane_session_id` (the review window's session id)
   when the episode starts, `_is_historical_session` treats it as
   historical (so the window is replaced by the fresh launch), and the
   field round-trips through the breadcrumb so a restart mid-episode keeps
   the guard.  A session that appears *after* the episode started (a
   sign-off route or another driver racing the retry) still differs from
   the snapshot and is adopted — the iteration-2 regression is preserved.
   Covered by
   `test_retry_never_adopts_the_window_that_was_live_at_episode_start`
   (fails pre-fix: records the old `PASS` with no launch),
   `test_discovery_replaces_the_window_that_was_live_at_episode_start`, and
   `test_discovery_still_adopts_a_session_started_after_the_stale_one`;
   the breadcrumb round-trip tests cover persistence.
2. **`VERDICT_ERROR` used instead of the literal.** `review_loop_ui` still
   compared `latest_verdict` against `"ERROR"` while the new outcomes use
   the constants; the two failure tuples now use `VERDICT_ERROR`.

Not changed (documented residuals): `review_loop.py` is ~1470 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9).

## Review iteration 1 (0688) — refinements

Findings from the next review pass, applied on top of iteration 10:

1. **A completed iteration clears `iteration_attempted` (correctness fix —
   fabricated verdict).** Iteration 6 made the restart handoff share
   discovery's `allow_recovery` gate so a merge restart between the
   iteration-counter bump and the first launch cannot adopt a previous
   run's transcript.  That reasoning only held for a loop's *first*
   iteration: the flag starts out `False` there, but a finished iteration
   left it `True`.  `run_review_loop_sync` bumps `state.iteration` and only
   then does `_run_iteration_with_retry` re-snapshot the episode, so a
   merge restart landing in that window persisted `iteration_attempted=True`
   for the *new* iteration number; the resumed handoff then allowed
   recovery and adopted an earlier run's `review-<pr>-i<N>.jsonl` verdict
   (e.g. `PASS`) for an iteration this loop never launched.
   `_reset_launch_retry` (run when an iteration produces its verdict) now
   clears the flag, so the persisted state at the bump is `False` and the
   handoff relaunches.  A restart *during* an in-flight iteration still
   adopts it: the flag is set before the launch and only cleared once the
   iteration completes.  Covered by
   `test_restart_between_iterations_does_not_adopt_the_old_run` (fails
   pre-fix: the persisted flag is `True` for iteration 2).
2. **A HOLD drops the failed attempt's artifact and re-arm deadline.**
   `_on_complete_from_thread` already reported the hold's own prompt rather
   than an earlier attempt's launch error (iteration 8), but it kept that
   attempt's `artifact` and `retry_ready_at` in `runtime_state`, so
   `pm autostart status` could point a human at the wrong evidence for a
   hold.  Both fields are now dropped with the failure they belong to.

Not changed (documented residuals): `review_loop.py` is ~1480 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9);
`other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED` after
the bounded claim wait, so a second TUI driving the same PR reports
"needs attention" for a review another loop is actually running.

## Review iteration 2 (0688) — refinements

Findings from the next review pass, applied on top of iteration 1 (0688):

1. **An adopted iteration clears `iteration_attempted` too (correctness fix —
   fabricated verdict).** Iteration 1 (0688) cleared the flag inside
   `_run_iteration_with_retry` when an iteration produced its verdict, but
   the *restart handoff* path bypasses that function: `run_review_loop_sync`
   calls `_adopt_in_flight_review` directly, so a resumed loop that adopted
   its in-flight iteration left `iteration_attempted=True` and then bumped
   the counter.  A merge restart in that window persisted `True` for the
   *next* iteration number, and the resumed handoff — which passes
   `allow_recovery=iteration_attempted or launch_attempts > 0` — adopted an
   earlier run's `review-<pr>-i<N>.jsonl` verdict (e.g. `PASS`) for an
   iteration this loop never launched.  The adopt branch now calls
   `_reset_launch_retry(state)` when adoption succeeds (nothing to adopt
   still relaunches the same iteration with its episode intact).  Covered by
   `test_restart_after_an_adopted_iteration_does_not_adopt_the_old_run`
   (fails pre-fix: the flag persisted at the bump is `True`, and the next
   iteration adopts the old `PASS` instead of running its own review).
2. **A whitespace-only stderr no longer hides a stdout error.** The concise
   UI detail did `(stderr or stdout or "").strip()`; whitespace is truthy,
   so a child that wrote only whitespace to stderr reported "no output from
   the launch command" while the real error sat on stdout (and only in the
   artifact).  Each stream is stripped before the fallback.  Covered by
   `test_whitespace_only_stderr_falls_back_to_stdout` (fails pre-fix).

Not changed (documented residuals): `review_loop.py` is ~1490 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9);
`other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED` after
the bounded claim wait, so a second TUI driving the same PR reports
"needs attention" for a review another loop is actually running.

## Review iteration 3 (0688) — refinements

Findings from the next review pass, applied on top of iteration 2 (0688):

1. **A stopping loop cannot take (or re-take) the launch lease
   (correctness fix — re-stranded target).** `zz d` / `z d` release the old
   loop's lease and claim it for the replacement immediately, but the old
   thread could re-claim it in the window between its loop-top
   `stop_requested` check and the launch: `_claim_launch` did not look at
   `stop_requested`.  The old loop would then launch a fresh review window
   the user just asked to replace, while the new loop waited out its bounded
   claim and expired into a *non-retryable* `LAUNCH_FAILED` ("owned by
   another loop") — the stranded target this PR exists to prevent.
   `_claim_launch` now returns False for a stopping loop (so
   `_wait_for_claim` sees the cancellation and the caller raises
   `PaneKilledError` → `KILLED`), and the retry checks `stop_requested`
   once more right before launching (a stop can also land during the claim
   or discovery).  Covered by
   `test_stopping_loop_does_not_claim_the_launch_lease` and
   `test_stop_between_claim_and_launch_does_not_launch` (both fail
   pre-fix).
2. **A HOLD does not carry the failed attempt's artifact in the live status
   path.** Iterations 8/9 dropped the artifact from the runtime_state mirror
   and preferred `latest_output` for the error, but
   `autostart_state.review_progress_input` still reported
   `last_launch_artifact`, so `pm autostart status --json` attached the
   earlier attempt's evidence to a hold.  It now reports an empty artifact
   for `HOLD`, matching the mirror.
3. **Shared adopted-review polling.** The restart handoff
   (`_adopt_in_flight_review`) and the retry's adopt branch duplicated the
   same landed-verdict-then-poll logic (including the no-startup-grace and
   trust-hold conversion).  Both now call `_poll_adopted_review(...)`; the
   handoff additionally records the adopted transcript's session as
   `last_session_id` even when the verdict had already landed, so the next
   iteration replaces that still-live pane instead of re-adopting it.

Not changed (documented residuals): `review_loop.py` is ~1500 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9);
`other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED` after
the bounded claim wait, so a second TUI driving the same PR reports
"needs attention" for a review another loop is actually running.

## Review iteration 4 (0688) — refinements

Findings from the next review pass, applied on top of iteration 3 (0688):

1. **A stop that lands before the loop thread's first line is no longer
   discarded (correctness fix — cancellation).** Iteration 4 (385e) made
   `_start_loop` mark the loop running *synchronously* before
   `start_review_loop_background` (so a second starter cannot observe a
   non-running loop and launch a duplicate), which means `_stop_loop` /
   `z d` / `zz d` now accept a stop for the whole window between
   `thread.start()` and the thread body.  `run_review_loop_sync` then reset
   `state.stop_requested = False` unconditionally, so such a stop was
   swallowed: the TUI told the user "Review loop stopping", and the loop
   went on to create a review window (and its container) anyway.  The flag
   is owned by the caller now — `_start_loop` clears it for a resumed loop
   and a fresh state defaults to `False` — so `run_review_loop_sync` no
   longer resets it.  Covered by
   `test_stop_landing_before_the_thread_body_prevents_the_launch` (fails
   pre-fix: the launch runs to `max_iterations`).

Not changed (documented residuals): `review_loop.py` is ~1500 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9);
`other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED` after
the bounded claim wait, so a second TUI driving the same PR reports
"needs attention" for a review another loop is actually running; the
runtime_state mirror of a *re-armed* loop keeps the previous episode's
`verdict`/`attempts` until the next iteration mirrors a new verdict, so
`pm autostart status` reports `review iteration N (last LAUNCH_FAILED)`
while the retry runs; `_interruptible_sleep` re-reads and re-validates the
~2 MB `project.yaml` every 2 s to notice a merge/close (≈3 % of a core
during a backoff, on the loop thread); `session._format_action_status`'s
new `[failed; retryable]` badge has no test (the function has none).

## Review iteration 5 (0688) — refinements

Findings from the next review pass, applied on top of iteration 4 (0688):

1. **The bounded claim wait stops when the PR closes (correctness fix —
   dead-PR launch).** `_wait_for_claim` only looked at `stop_requested`; a
   merge/close during the up-to-15 s wait for another loop's lease was
   noticed by `_interruptible_sleep` (which returns early) but ignored, so
   the wait kept polling the lease and — if the other loop released it —
   claimed it and went on to launch a review for a merged PR without
   re-checking terminal status.  It now re-checks `_pr_is_terminal` after
   each sleep and returns False, which the caller already maps to
   `ReviewClosedError` → `CLOSED`.  Covered by
   `test_claim_wait_stops_when_the_pr_closes` (fails pre-fix: it keeps
   claiming past the close).
2. **The starting-pane grace is per launch attempt.** `pending_checks`
   counted across the whole episode, so a pane that never exposed a session
   was replaced correctly on attempt 1 but a *starting* pane discovered
   before attempt 2 was replaced at once (the counter was already past the
   cap) instead of getting its own bounded grace — the pane could be our
   own just-started recovery or a racing driver's launch.  The counter now
   resets when an attempt is launched.  Covered by
   `test_pending_grace_is_per_launch_attempt` (fails pre-fix: attempt 2
   launches after a single pending check).
3. **The episode-reset lists cannot drift.** The start of a new iteration's
   episode and `_reset_launch_retry` each cleared the same five
   failed-attempt fields by hand; the episode start had already missed
   `retry_ready_at`.  Both now call `_clear_launch_failure`; the episode
   start also clears `retry_ready_at` (a no-op today, but it keeps the
   "fresh episode" invariant explicit).
4. **The `[failed; retryable]` badge has a test.**
   `test_action_status_badge_flags_a_retryable_launch_failure` covers the
   new `pm session` row badge (and that a HOLD is not flagged retryable),
   closing the test gap noted in iteration 4's residuals.

Not changed (documented residuals): `review_loop.py` is ~1520 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9);
`other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED` after
the bounded claim wait, so a second TUI driving the same PR reports
"needs attention" for a review another loop is actually running; the
runtime_state mirror of a *re-armed* loop keeps the previous episode's
`verdict`/`attempts` until the next iteration mirrors a new verdict, so
`pm autostart status` reports `review iteration N (last LAUNCH_FAILED)`
while the retry runs; `_interruptible_sleep` re-reads and re-validates the
~2 MB `project.yaml` every 2 s to notice a merge/close (≈3 % of a core
during a backoff, on the loop thread).

## Review iteration 6 (0688) — refinements

Findings from the next review pass, applied on top of iteration 5 (0688):

1. **The auto-start re-arm yields to a pending sign-off REVIEW return
   (correctness fix — duplicate `--fresh` launchers).** Requirement 4
   ("serialize retry ownership across drivers") was only half applied: the
   *fresh-loop* path in `_auto_start_review_loops` takes the sign-off
   return's launch claim (`signoff.claim_return_launch`) before starting a
   loop, but the new *re-arm* branch did not.  A PR whose review loop
   exhausted its retries while a sign-off REVIEW return still awaited its
   launch could therefore get two `--fresh` launches at once — the re-armed
   loop's and the return's (from `pm pr auto-sequence` or the TUI return
   catch-up) — and each kills the window it finds, so they could kill each
   other's session.  Both paths now share
   `_yield_to_pending_review_return(app, pr_id)`: the first driver takes the
   claim and performs the launch (the re-armed loop's own launch satisfies
   the return, as the fresh path already relied on); a later driver leaves
   the launch alone, keeps the retryable failure intact (episode count and
   budget untouched) and arms `_recheck_after_claim` so an expired claim is
   taken over instead of stranding the target.  Covered by
   `test_auto_start_rearm_yields_to_a_pending_review_return` (fails pre-fix:
   the re-arm starts a loop and clears `launch_retryable` while another
   driver owns the return's launch).
2. **The episode-start pane snapshot has a test.**
   `_live_review_pane_session` (the iteration-10 guard's snapshot) was
   untested; `test_episode_start_snapshots_the_live_review_window` covers
   the resolved session and every total path (no pm session, no window, an
   unresolvable pane).

Not changed (documented residuals): `review_loop.py` is ~1530 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9);
`other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED` after
the bounded claim wait, so a second TUI driving the same PR reports
"needs attention" for a review another loop is actually running (a proper
`SUPERSEDED` outcome would touch the verdict constants, the tech-tree/popup
rendering and auto-start's re-arm gate, so it stays a follow-up); the
runtime_state mirror of a *re-armed* loop keeps the previous episode's
`verdict`/`attempts` until the next iteration mirrors a new verdict, so
`pm autostart status` reports `review iteration N (last LAUNCH_FAILED)`
while the retry runs; `_interruptible_sleep` re-reads and re-validates the
~2 MB `project.yaml` every 2 s to notice a merge/close (≈3 % of a core
during a backoff, on the loop thread).

## QA refinement (scenario 3) — cancelled-loop status

QA scenario 3 (cancel/supersede during the retry backoff) found that a loop
stopped by the user during the backoff ends `KILLED`, but the live status
input kept the earlier attempts' retry evidence: `pm autostart status --json`
reported `review.verdict: "KILLED"` with `retryable: true`, `attempts: 2`, and
a non-empty `error`/`artifact`.  Auto-start never re-arms a `KILLED` loop, so
`retryable: true` was wrong (the `runtime_state` mirror already drops these
fields for every non-`LAUNCH_FAILED` completion; `review_progress_input`
special-cased only `HOLD`).  `review_progress_input` now drops the retry
evidence once the loop has stopped with a non-`LAUNCH_FAILED` outcome, while a
loop still running its retry episode (no verdict yet, or a re-armed
`LAUNCH_FAILED` loop) keeps reporting it.  Covered by
`test_autostart_status_does_not_report_a_cancelled_loop_as_retryable` and
`test_autostart_status_keeps_the_retry_evidence_while_the_retry_runs`.

## Review iteration 7 (0688) — refinements

Findings from the next review pass, applied on top of iteration 6 (0688) and
the QA refinement above:

1. **The retry notice names the failure it is reporting.** The notice fired
   for attempt *N* carried the error recorded by attempt *N-1* unlabelled
   (`Review launch retry … (attempt 3): Review window launch failed …`), which
   reads as though the attempt now starting had failed — QA observed this on a
   healthy attempt 3 (`rc=0`).  It now says `attempt N; attempt N-1 failed:
   …`.  Covered by the strengthened
   `test_retry_notice_is_only_for_a_real_retry`.
2. **A restart mid-retry no longer re-announces the notice.** QA saw the
   resumed loop re-emit the persisted attempt-2 notice ~1 s after
   `Review loop resumed …`.  `_ui_notified_retry` is persisted in the
   breadcrumb and `_start_loop` no longer clears it on resume; the key is
   cleared where an episode actually starts — `_clear_launch_failure` (shared
   by `_reset_launch_retry` and the new-iteration episode start) and the
   auto-start re-arm (which also restores it when the start bails).  Covered
   by `test_round_trips_the_retry_notice_key`,
   `test_auto_start_rearm_clears_the_retry_notice_key` and
   `test_auto_start_rearm_restores_the_notice_key_when_it_cannot_start`.
3. **The status reason does not print the artifact path twice.** The concise
   launch error already ends with `(artifact: …)`; `_derive` appended
   `[artifact: …]` on top of it.  It now appends only when the error does not
   already name the artifact.  Covered by
   `test_autostart_status_does_not_repeat_the_artifact_path`.

Not changed (documented residuals): `review_loop.py` is ~1530 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9);
`other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED` after
the bounded claim wait; the runtime_state mirror of a *re-armed* loop keeps
the previous episode's `verdict`/`attempts` until the next iteration mirrors
a new verdict, so `pm autostart status` reports
`review iteration N (last LAUNCH_FAILED)` while the retry runs;
`_interruptible_sleep` re-reads and re-validates the ~2 MB `project.yaml`
every 2 s to notice a merge/close (≈3 % of a core during a backoff, on the
loop thread).

## Review iteration 8 (0688) — refinements

Findings from the next review pass, applied on top of iteration 7 (0688) and
the QA refinement above:

1. **A HOLD's completion notice no longer prints a failed attempt's
   artifact.** Iterations 8/9 (385e) and 1/3 (0688) stopped attaching the
   earlier failed attempt's `artifact`/`retry_ready_at` to a hold in the
   `runtime_state` mirror and in `autostart_state.review_progress_input`, but
   the TUI's "Review loop done" notice still appended
   `Artifact: <attempt-N artifact>` under a hold's trust/permission prompt
   (QA scenario 6 observed it).  The artifact line is now shown only for
   `LAUNCH_FAILED`, the outcome the artifact belongs to.  Covered by
   `test_hold_completion_notice_does_not_print_the_failed_attempts_artifact`
   (fails pre-fix) and `test_launch_failed_completion_notice_still_prints_its_artifact`.
2. **A running re-armed retry is not described by the previous episode's
   failure (closes a documented residual).** A re-armed loop keeps
   `latest_verdict == LAUNCH_FAILED` until the new iteration lands, so
   `_derive` reported `review iteration N (last LAUNCH_FAILED)` while the
   retry was running — QA observed the row in `pm autostart status`.  The
   running branch now suppresses the `(last …)` suffix for `LAUNCH_FAILED`
   only; a real previous verdict (`NEEDS_WORK`) still shows as useful
   context.  Covered by
   `test_running_rearmed_retry_does_not_report_the_old_failure_verdict`
   (fails pre-fix) and `test_running_review_still_reports_the_previous_iterations_verdict`.
3. **A retried launch failure logs a warning, not an error.** QA noted the
   per-attempt `launch failed (rc=…)` line at ERROR level for a failure the
   loop immediately retries.  `_launch_review_window` now logs at WARNING for
   a retryable (transient) failure and keeps ERROR for a non-retryable auth
   failure; the loop still logs ERROR when it gives up (`LAUNCH_FAILED`).
   Covered by `test_transient_launch_failure_logs_a_warning` and
   `test_auth_launch_failure_logs_an_error` (both fail pre-fix).

Not changed (documented residuals): `review_loop.py` is ~1540 lines (the
retry/discovery state machine would be worth its own module, but splitting it
mid-review is a large, risky refactor); two lease mechanisms coexist
(`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9 of
385e); `other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED`
after the bounded claim wait, so a second TUI driving the same PR reports
"needs attention" for a review another loop is running; the `runtime_state`
mirror of a re-armed loop keeps the previous episode's `verdict`/`attempts`
until the next iteration mirrors a new verdict (the live `pm autostart status`
path no longer shows it — see refinement 2 — and the runs popup reads
`runtime_state`); `_interruptible_sleep` re-reads and re-validates the ~2 MB
`project.yaml` every 2 s to notice a merge/close (≈3 % of a core during a
backoff, on the loop thread).

## Review iteration 9 (0688) — refinements

Findings from the next review pass, applied on top of iteration 8 (0688):

1. **One lease-release helper.** The supersede paths
   (`stop_loop_or_fresh_review`, `start_or_stop_loop`) and
   `_on_complete_from_thread` each carried their own copy of the same
   inline import + `release_action_lease` + `_log.debug` block.  All three
   now call `review_loop._release_lease(state)`, the helper the loop's own
   `finally` already uses, so the "only release a lease this owner still
   holds" rule lives in one place and cannot drift between paths.
2. **`VERDICT_ERROR` in the icon table.** `review_loop_ui.VERDICT_ICONS`
   still keyed the error icon on the `"ERROR"` literal while the rest of
   the module uses the constant (iteration 10 of 385e converted the
   comparisons).
3. **A HOLD is not described as a failed launch.** `_derive`'s HOLD branch
   said "review launch held: …", but a hold is the trust/permission prompt
   a *launched* review is sitting at — the launch itself succeeded.  It now
   reports "review held at a permission prompt: …", and the loop's log line
   matches.  Covered by the strengthened
   `test_autostart_status_reports_the_hold_prompt_not_a_stale_launch_error`.
4. **A cancelled loop drops its attempt count too.**
   `review_progress_input` dropped `retryable`/`error`/`artifact` for a loop
   stopped with a non-`LAUNCH_FAILED` outcome (the QA scenario-3 fix) but
   kept `attempts`, so `pm autostart status --json` reported
   `verdict: "KILLED", attempts: 2` while the `runtime_state` mirror drops
   `attempts` for the same completion.  The live path now drops it too.
   Covered by the strengthened
   `test_autostart_status_does_not_report_a_cancelled_loop_as_retryable`.

Not changed (documented residuals): `review_loop.py` is ~1540 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9 of
385e); `other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED`
after the bounded claim wait; the `runtime_state` mirror of a re-armed loop
keeps the previous episode's `verdict`/`attempts` until the next iteration
mirrors a new verdict (the runs popup reads `runtime_state`); a merge
restart during the post-exhaustion re-arm *cooldown* does not persist the
loop (`save_breadcrumb` only saves running loops), so auto-start starts a
fresh loop for the PR instead of continuing the episode — the review still
runs and no verdict is fabricated (the new loop snapshots the stale
symlink/pane), only the loop's history/iteration numbering restarts;
`_interruptible_sleep` re-reads and re-validates the ~2 MB `project.yaml`
every 2 s during a backoff.

## QA-driven fixes (scenarios 8 and 9)

Fixes applied from the live QA runs after iteration 9 (0688):

1. **A loop-driven window replacement is visible in the log (QA scenario 8,
   `b531c86b`).** `_launch_review_window` runs `pm pr review --fresh` as a
   child and discards its stdout on success, so the child's
   "Killed existing review window '<name>'" / "Switched to existing review
   window '<name>'" notices never reached the log — a loop-driven launch
   silently replaced a held or historical window with no trace.  `cli/pr.py`
   now mirrors both notices into the debug log (`_log.info`).  Log only;
   behaviour unchanged.
2. **Every retry attempt is announced (QA scenario 9, `7f38066a`).** The TUI
   retry notice was keyed on the observed `launch_attempts`, but an attempt
   that starts and dies inside one ~1 s poll tick is never observed, so an
   exhausted episode only ever showed "attempt 2; attempt 1 failed".  The
   notice now derives the *upcoming* attempt (`launch_attempts + 1`) while
   `next_retry_at` is still in the future (`_retry_backoff_pending`), so the
   final attempt is announced too, and each attempt is still announced
   exactly once across restarts and episodes.
3. **The auto-start re-arm announcement is visible (QA scenario 9,
   `7f38066a`).** "Auto-start: retrying review launch for <pr>" was logged but
   immediately replaced by `_start_loop`'s "Review loop resumed …" in the same
   tick; it now holds the log line for `CONFIRM_HOLD_SECONDS`, matching the
   "targets +=" confirmation.
4. **Test isolation (QA scenario 9, `7f38066a`).**
   `test_old_window_then_container_failure_retries_the_same_command` patches
   the process-wide `subprocess.run`, so running pytest inside a tmux pane let
   an ambient `tmux display-message` session-name lookup consume the "first
   call fails" slot.  The fake now only counts `--review-loop` launches.

## Review iteration 1 (1fc4) — refinements

1. **Child stderr is escaped before it enters a Rich-markup log line
   (correctness fix — the failure notice can vanish).** `app.log_message`
   renders through `LogLine(Static)`, i.e. Rich markup.  The new retry notice
   interpolated `last_launch_error` (the launch child's own stderr) and the
   completion notice interpolated `latest_output` unescaped, so a bracketed
   token in the child's stderr was mangled or the notice was dropped
   outright: `[podman]` is parsed as a style tag and swallowed, and an
   unbalanced tag such as `[/tmp/pm-review]` raises `MarkupError`, which
   `log_message`'s `try/except` swallows — the "concise error in the UI"
   requirement fails exactly when the failure text is interesting.  Both
   notices now `rich.markup.escape` the interpolated stderr and artifact path
   (the codebase convention: `qa_loop_ui` escapes `latest_output` the same
   way).  Covered by
   `test_retry_notice_shows_bracketed_child_stderr_verbatim` and
   `test_launch_failed_notice_shows_an_unbalanced_tag_in_stderr`, which render
   the message through `textual.content.Content.from_markup` and fail
   pre-fix.
2. **`VERDICT_KILLED` instead of the literal.** `review_loop_ui` still keyed
   `VERDICT_ICONS` on `"KILLED"` and compared `latest_verdict` against the
   literal in the failed-completion tuple; both use the constant now, like the
   rest of the module (iteration 9 of 0688 converted `VERDICT_ERROR`).

Not changed (documented residuals): `review_loop.py` is ~1540 lines; two
lease mechanisms coexist (`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9 of
385e); `other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED`
after the bounded claim wait; the `runtime_state` mirror of a re-armed loop
keeps the previous episode's `verdict`/`attempts` until the next iteration
mirrors a new verdict (the runs popup reads `runtime_state`); a merge
restart during the post-exhaustion re-arm *cooldown* does not persist the
loop (`save_breadcrumb` only saves running loops), so auto-start starts a
fresh loop for the PR instead of continuing the episode — the review still
runs and no verdict is fabricated (the new loop snapshots the stale
symlink/pane), only the loop's history/iteration numbering restarts;
`_interruptible_sleep` re-reads and re-validates the ~2 MB `project.yaml`
every 2 s during a backoff (`store.load` is dominated by the YAML parse, so
`validate=False` would not help); a stop that lands in the window between
`_start_loop` marking the loop running and the thread body breaks the loop
at its top without recording an outcome, so the previous episode's
`LAUNCH_FAILED` verdict (already made non-retryable by the re-arm) is what
`_on_complete_from_thread` mirrors — no re-arm happens, but
`pm autostart status` says "needs attention" for a loop the user stopped.
The same top-of-loop break on a fresh loop mirrors `state="done"`; both are
pre-existing "what does a stopped-before-iteration loop report" questions.

## Review iteration 2 (1fc4) — refinements

1. **A resume that cannot start no longer strands the target (correctness
   fix).** `consume_breadcrumb` restores the saved loop into
   `app._review_loops` *before* calling `_start_loop`, and `_start_loop`
   bails (returning False, with its own message) when the PR is missing, tmux
   is unavailable, the PR has no workdir, or the transcript dir cannot be
   created.  The restore path ignored that result: it announced "Review loop
   resumed for <pr>" anyway and left a **non-running** loop entry behind —
   and `_auto_start_review_loops` skips a PR whose entry is non-running and
   not a retryable launch failure, so the PR was stranded until a manual
   `review-loop start`: the exact symptom this PR exists to remove, reached
   through a failed resume instead of a failed launch.  The resume now logs
   honestly and drops the restored entry so the scheduler pass can start a
   fresh loop; a starter that *raises* (e.g. a missing project root) is
   treated the same way, so it cannot take the TUI mount down either — the
   same rule the auto-start re-arm path already follows.  Covered by
   `tests/test_breadcrumb_review_loop.py::TestConsumeBreadcrumbReviewLoops::
   test_a_resume_that_cannot_start_drops_the_phantom_loop` (fails pre-fix:
   the entry survives and the "resumed" notice is logged) and
   `test_a_raising_resume_is_treated_like_a_refusal` (pre-fix the exception
   escapes `consume_breadcrumb`).
2. **A stopping loop cannot re-take the launch lease while claiming
   (correctness fix — re-stranded target).** `_lease_keepalive._check` looked
   at `stop_requested` *before* claiming, and the claim is not atomic with
   that check: the supersede paths (`z d` / `zz d`) set `stop_requested` and
   release the old lease, so a claim already in flight re-took the lease the
   replacement needs.  The new loop's bounded claim wait then expires into a
   non-retryable `LAUNCH_FAILED` ("owned by another loop") — the same
   re-stranding iteration 3 of 0688 closed inside `_claim_launch`, which the
   keepalive path did not share.  The keepalive now hands the lease straight
   back (`_release_lease`) when a stop landed during the claim.  Covered by
   `test_lease_keepalive_releases_a_lease_claimed_after_a_stop` (fails
   pre-fix: the lease stays owned by the stopping loop).
3. **The launch lease is documented.** `runtime_state` documents its on-disk
   schema in the module docstring; the `lease` field and the
   `_locked_action_mutate` writer were undocumented, so a reader of the
   module (or a future writer) had no description of the one-owner claim.

Not changed (documented residuals, unchanged from iteration 1 unless noted):
`review_loop.py` is ~1550 lines; two lease mechanisms coexist
(`signoff.claim_return_launch` in project.yaml vs
`runtime_state.claim_action_lease`); discovery still adopts a transcript
verdict without requiring an idle hook event (rationale in iteration 9 of
385e); `other_owner` stand-down surfaces as a non-retryable `LAUNCH_FAILED`
after the bounded claim wait; the `runtime_state` mirror of a re-armed loop
keeps the previous episode's `verdict`/`attempts` until the next iteration
mirrors a new verdict — correction to iteration 1's wording: neither the
runs popup nor `pm autostart status` reads that mirror for a review loop
(the popup uses `collect_status_inputs`, i.e. live `review_progress_input`,
and the CLI status is answered by the TUI), so the staleness is only visible
to a reader of `~/.pm/runtime/<pr>.json` itself; a merge restart during the
post-exhaustion re-arm *cooldown* does not persist the loop
(`save_breadcrumb` only saves running loops), so auto-start starts a fresh
loop for the PR instead of continuing the episode — the review still runs
and no verdict is fabricated; `_interruptible_sleep` re-reads and
re-validates the ~2 MB `project.yaml` every 2 s during a backoff; a stop
that lands inside `_launch_review_window`'s `subprocess.run` (up to 120 s)
is not noticed until the child returns, so a superseded loop can create a
review window the replacement then replaces — the old loop's lease is
already released and it bows out at its next checkpoint, so the new loop is
unaffected.

## Integration with master (89e3c501)

Sign-off returned the PR as `SIGNOFF_IMPL` for integration only: the behaviour
was complete, reviewed and live-QA PASS, but merging master@89e3c501e08a
conflicted in `pm/project.yaml` and `pm_core/review_loop.py`.

1. **Master's verdict reader reaches every adopt/retry path (semantic
   resolution).** Master (pr-8efa789) switched `_adopt_in_flight_review` to
   `verdict_transcript.find_verdict_turn`, returning `hit.text or
   hit.verdict`, so a later `/loop` wakeup turn cannot hide the verdict from
   `parse_review_verdict`. This PR had moved that read into
   `_verdict_output_if_present`, the single verdict reader shared by
   `_landed_verdict` (hence `_poll_adopted_review`, retry discovery and the
   restart handoff). That helper now calls
   `find_verdict_turn(transcript, ALL_VERDICTS)` and returns
   `hit.text or hit.verdict`; the conflict's inline copy in
   `_adopt_in_flight_review` was dropped in favour of the shared
   `_poll_adopted_review`, so master's fix is not silently lost on the
   retry/adopt paths. Verified: master's only change to `review_loop.py`
   between the merge base and 89e3c501 was that switch.
2. **`stop_before_merge` removal.** Master (pr-25f4038) removed
   `app._stop_before_merge` / `POLICY_STOP`; the two stale
   `app._stop_before_merge = set()` lines in
   `tests/test_review_launch_retry.py` are gone and nothing in `pm_core/`
   references the attribute.
3. **`consume_breadcrumb` keeps both sides.** It still calls master's
   `autostart_state.targets_from_breadcrumb(data, prs)` (legacy
   `stop_before_merge` breadcrumbs migrate to wait targets, fail closed) and
   keeps this PR's ordering: restored review loops are resumed *before* the
   auto-start scheduler pass, so a re-armed loop's saved budget and remaining
   backoff survive a restart.
4. **`pm/project.yaml` (registry/notes 3-way).** Resolved by union: the later
   `updated_at` per entry, notes merged by id, and every entry added on either
   side retained (`pr-e040aeb` here; `pr-25f4038`, `pr-16e45ba` and seven
   others on master). Verified by parsing the merged file: 508 unique PR ids,
   no duplicates, `pr-e040aeb` byte-identical to this branch's entry,
   `pr-25f4038`/`pr-16e45ba` identical to master's, no master id missing, and
   the only differences from master are this branch's own cross-PR notes and
   their later `updated_at` stamps.
