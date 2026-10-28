# pr-e040aeb — QA spec: bounded retry of a failed review-iteration launch

Source of truth for behaviour: `pm/specs/pr-e040aeb/impl.md` (860 lines, incl.
every review iteration). This spec turns it into user-visible stories.

## What the user experiences

A review loop runs iterations. When an iteration produces `NEEDS_WORK`, the loop
launches the next iteration: it closes the historical review window, then
removes/re-creates the review container and starts a new Claude session. If that
launch fails (teardown error, container setup error, route down, timeout), the
old code ended the loop with a terminal `ERROR` and the auto-start target sat
stopped until a human sent `review-loop start` — the bug.

Now: the same iteration is retried up to 3 times with a 5 s then 10 s backoff,
rediscovering before each attempt; the failure is reported as an explicit
`LAUNCH_FAILED` (retryable) with a full launch artifact; auto-start re-arms the
target after a 60 s cooldown (max 5 episodes); and the retry never fabricates a
verdict, never duplicates another driver's launch, and never survives a
cancellation.

## Setup (cross-cutting)

Each scenario builds its own throwaway project (see `tui-manual-test.md`), with:

- `pm init --backend local --no-import`, 1–2 PRs, `pm pr start <id>` so each PR
  has a workdir and a branch.
- A **fake-claude** config for the session so review iterations produce
  deterministic verdicts without a real model:
  `pm fake-claude config set '{"_all": {}, "review": {"verdicts": ["NEEDS_WORK", "PASS"]}}'`
  (scripted per iteration; `delay` is supported per entry, e.g.
  `[{"verdict": "NEEDS_WORK", "delay": 20}, "PASS"]`, which the scenarios use to
  have time to break and repair the launch environment between iterations).
- The TUI started from the test project (`pm session`), auto-start target added
  where the scenario needs it (`pm autostart add <pr> --stop-before-merge`).
- The local-backend scaffold must be pushed and synced before `pm pr start`
  (`pm push` then `git merge pm/sync-*` in the main repo), or start fails with
  "not committed on master yet".
- The fake-claude stand-in and any broken runtime shim must be on the session
  PATH when `pm session` starts (the panes inherit it).
- Auto-start targets are TUI-process state, not project.yaml records: a TUI
  restart loses them, so re-add after restart when the scenario needs one.
- Launch artifacts live under `<project>/pm/transcripts/<run_id>/launch-artifacts/`
  (the `pm/` segment matters).
- `pm autostart status --json` emits `run_id`, `targets` and `runs` at the TOP
  level — read `.runs[0].review` and `.targets[0].state`, not `.status.*`.
- Backoff is 5 s then 10 s between the three attempts; the cooldown before
  auto-start re-arms is 60 s.

### Failure injection (user-level, no source edits)

The launch failure is induced the way a user's host would fail, not by mocking.

- **Primary — container runtime failure** (matches the reported symptom
  "fails while removing/replacing its container"): put a small `podman` (or
  `docker`) shim early on `PATH` that answers `info` with exit 0 (so
  `pm container enable` accepts it) and fails `run`/`create`; then
  `pm container enable`. Because container mode is a global setting read on
  every launch, `pm container disable` repairs the environment mid-backoff, and
  the very next attempt runs Claude on the host with fake-claude.
- **Classification text does NOT come from the shim's run/create stderr**: pm
  wraps any container-creation exception in a generic `ContainerError`
  ("Failed to create container … Is podman running?"), so a shim cannot select
  the wording the loop classifies. To inject classification text, give the shim
  an `image inspect` that exits 1 and set the image name via the normal surface:
  `pm container set image <text>`. The launch child then exits 1 with
  `Image <text> not found in podman. …`, which the loop does classify:
  - `permission denied:latest` → retryable (3 attempts);
  - `process 403 exited` → retryable (3 attempts);
  - `unauthorized:latest` → non-retryable (1 attempt).
- **HOLD — live-inducible** (the earlier spec said it was not): clear the
  fake-claude config, put a `claude` stand-in on the session PATH that prints
  the workspace-trust dialog and blocks, set
  `pm set trust-prompt-grace-seconds 10`, and disable container mode during the
  first backoff (watch `pm log` for "launch attempt 1/3 failed"). The retry
  then launches the stand-in and the loop reports a hold.
- **Alternative — workdir unavailable**: move the PR's workdir aside before the
  next iteration launches (the child cannot create the review window and the
  loop raises "review window … not found after launch", also retryable).

## Requirements

### R1 — A failed next-iteration launch is retried, not terminal

GIVEN a review loop running iteration 1 of a PR (a review window is live and
iteration 1 has produced `NEEDS_WORK`), and the host's container runtime cannot
create a container.
WHEN the loop launches iteration 2,
THEN the launch fails after the historical window has been closed,
  the loop keeps the iteration number at 2,
  it logs a bounded retry (`attempt 1/3 failed … retrying in 5s`),
  and it does not end the loop with a terminal error.

GIVEN the same failure, and the runtime repaired before the next attempt,
WHEN the retry fires,
THEN a fresh review window is created for iteration 2,
  it runs the original complete review task on the assigned provider,
  collects its own verdict (e.g. `PASS`),
  and the loop finishes with that verdict and the PR advances to QA.

GIVEN the retry succeeded,
WHEN the user inspects the loop's history and iteration count,
THEN the history holds only the iterations that actually produced verdicts
  (iteration 1 `NEEDS_WORK`, iteration 2 `PASS`) — the failed launch adds no
  entry and no fabricated `PASS`/`NEEDS_WORK` for an iteration that never ran.

### R2 — The failed attempt is fully preserved in an artifact

GIVEN an attempt failed,
WHEN the user opens the artifact the UI names,
THEN it lives under `<project>/pm/transcripts/<run_id>/launch-artifacts/`,
  and contains timestamp, PR, iteration, loop id, attempt number, return code,
  the exact launch command, the complete (untruncated) stderr and stdout,
  and a copy of the failed attempt's prompt when one exists (skipped, with a
  reason, when the transcript symlink still names a previous run's session).

GIVEN the same failure,
WHEN the user looks at the TUI log / status surfaces,
THEN the message is a concise single-line error (last actionable line, ~300
  chars) plus the artifact path — not the full dump.

### R3 — Exhaustion is an explicit, retryable failure — never a verdict

GIVEN the launch keeps failing for a whole episode (3 attempts, 5 s then 10 s),
WHEN the last attempt fails,
THEN the loop ends with an explicit failed-launch outcome (`LAUNCH_FAILED`,
  retryable) and the PR stays in review (no QA started, no `PASS`/`NEEDS_WORK`
  recorded for that iteration),
  and the loop history gains no entry for it,
  and the TUI announces the failure with the error, the artifact path, and a
  statement about whether an automatic retry will happen.

### R4 — Status surfaces name the failure and the evidence

GIVEN the exhausted failure above,
WHEN the user runs `pm autostart status` (and `--json`) or opens the runs popup
  (`a`),
THEN the target is shown as failed (`phase: failed`, `state: review`) with
  `review launch failed (retryable): …` plus the artifact path exactly once
  (the concise error already names it; the status must not append it again),
  and the JSON entry carries retryable/attempts/error/artifact (top-level
  `runs[0].review`),
  and the session/action picker's review row shows a `[failed; retryable]` badge.

### R5 — Auto-start re-arms the target instead of stranding it

GIVEN an auto-start target whose review launch exhausted its retries,
WHEN the 60 s cooldown elapses with no human action,
THEN auto-start re-arms the same loop (resuming history and the un-completed
  iteration), a new review launch runs, and the target is no longer stopped;
  this repeats for at most 5 episodes and then the explicit failure stays.

GIVEN the same failure on a *manual* loop (or a PR outside the auto-start set),
WHEN the user waits past the cooldown,
THEN nothing re-arms it, and the notice says to run `review-loop start` rather
  than promising an automatic retry.

### R6 — Cancellation wins over the retry

GIVEN a loop backing off after a failed attempt,
WHEN the user cancels it from the review action's fresh mode (`z d`, which
  stops the loop and opens a fresh one-off review) or supersedes it with a new
  loop (`zz d`, the stop-then-start loop action),
THEN the old loop ends `KILLED` (not `LAUNCH_FAILED`), performs no further
  attempt, is not re-armed, and the new review window (fresh review or new
  loop) is the only one and survives.
  After the stop, `pm autostart status` reports `review loop ended KILLED`
  with no retry evidence: `retryable` false, `attempts` 0, empty `error` and
  `artifact` (a cancelled loop is not retryable).

### R7 — Concurrent drivers never duplicate or kill each other's launch

GIVEN a review loop owns the PR's launch (running or backing off),
WHEN `pm pr auto-sequence <pr>` is invoked repeatedly from another pane,
THEN it reports `running: review (owned by loop:…)`, launches nothing, and does
  not kill the loop's review window; the loop still produces exactly one verdict.

GIVEN two PRs with review loops, one failing and retrying,
WHEN both run concurrently,
THEN the healthy PR's review is unaffected and completes normally, and the two
  targets' statuses are reported independently.

### R8 — A TUI restart mid-episode preserves the episode

GIVEN a loop backing off (attempt 1 failed, ~10 s to go) and an auto-start
  breadcrumb written,
WHEN the TUI restarts,
THEN the loop resumes at the same iteration with its remaining attempt budget
  and deadline (it does not restart the 3-attempt budget, does not burn an
  episode, and is not re-armed as a fresh episode),
  and the retry then completes normally; history and the artifact path survive.

### R9 — Classification: transient retries, auth/trust does not

GIVEN a launch fails with a transient container/route error (including a
  "permission denied" teardown message),
WHEN the loop retries,
THEN it retries up to the budget and the target can still be re-armed.

GIVEN a launch fails with an auth symptom (`unauthorized`, `401 unauthorized`,
  `not logged in`, `invalid api key`) on either stream,
WHEN the loop handles it,
THEN it stops after one attempt, reports a non-retryable failure ("needs
  attention"), never re-arms, and still writes the artifact.

GIVEN a review pane sits at a workspace-trust/permission prompt,
WHEN the loop observes it,
THEN the outcome is a hold (`HOLD`) — not a launch failure, not retried — and
  the status reports `review held at a permission prompt: <prompt>` rather than
  an earlier attempt's launch error, with no stale artifact attached (neither
  in `pm autostart status` nor in the TUI's "Review loop done" notice), and the
  target is not re-armed after the cooldown.

## Edge cases

- Failure *before* any pane is created (container setup fails immediately):
  same retry, same artifact, same iteration number.
- Old window removed, then setup fails: the retry must create a fresh window
  and succeed (the R1 story).
- A route/native recovery or another driver's launch starts while a retry is
  scheduled: the retry discovers and adopts it (polls it) rather than launching
  a duplicate `--fresh` window.
- A failed launch leaves the previous iteration's window/transcript live: the
  retry must replace it and must never adopt its older verdict.
- A merge/close during the backoff stops the loop with an explicit closed
  outcome (not a retryable launch failure).
- PR merged while waiting out another loop's launch lease: closed, not failed.
- Exhaustion at the episode cap: the explicit retryable failure stays for a
  human, and nothing is scheduled.
- A second TUI on the same project must not launch a duplicate; it stands down
  and reports that another loop owns the launch.
- A sign-off REVIEW return pending at re-arm time: the re-arm yields so two
  `--fresh` launchers cannot kill each other.

## Pass / fail criteria

Pass = every THEN above is observable on the surface named, on a branch built
from this PR; the reproduction test
(`tests/test_review_loop.py::test_failed_launch_is_retried_not_terminal`, which
fails on the base tree) passes; and the targeted suites
(`tests/test_review_launch_retry.py`, `tests/test_review_loop.py`,
`tests/test_breadcrumb_review_loop.py`) pass.

Fail = a failed launch ends the loop with `ERROR`/a fabricated verdict; the
target stays stopped with no re-arm and no explanation; a retry adopts a
previous run's verdict or a previous window; the artifact is missing/truncated;
a cancellation is reported as a launch failure; two drivers produce two review
windows; or a healthy unrelated review is disturbed.

## Post-QA fixes to verify (f076 i1–i3, after the first QA run)

The first QA pass (scenarios 1–6) produced these fixes; scenarios must verify
them on the live surfaces, not just in tests:

1. The TUI retry notice for attempt N now reads
   `Review launch retry for <pr> (attempt N; attempt N-1 failed: …)` — the error
   is labelled as the previous attempt's, and no notice fires for attempt 1.
2. A TUI restart mid-retry no longer re-announces the persisted notice
   (`_ui_notified_retry` round-trips through the breadcrumb; cleared only at an
   episode boundary or an auto-start re-arm).
3. `pm autostart status` prints the artifact path once, not twice.
4. A HOLD's completion notice shows the trust/permission prompt and no
   `Artifact:` line; status says `review held at a permission prompt`.
5. A re-armed retry that is running shows `review iteration N`, not
   `review iteration N (last LAUNCH_FAILED)`.
6. A cancelled (KILLED) loop reports no retry evidence (`retryable`,
   `attempts`, `error`, `artifact` all cleared) — this was the one NEEDS_WORK
   finding of the first QA pass.
7. A retryable per-attempt `launch failed (rc=…)` logs at WARNING while the
   loop keeps retrying; ERROR is reserved for auth failures and for giving up.
8. The `pm session` review row's `[failed; retryable]` badge (previously
   untested).

## Ambiguities resolved

1. **"Automatic retry" wording** — the notice promises an automatic retry only
   where auto-start will actually re-arm (in-scope target, enabled, under the
   episode cap); otherwise it points at `review-loop start`. Asserted as R5.
2. **How to induce the failure** — the low-level teardown exception is
   unconfirmed in the bug report, so scenarios induce a *symptom* (broken
   container runtime / unavailable workdir), which is exactly how the code
   classifies failures.
3. **HOLD reproduction** — superseded by QA scenario 6: a hold IS live-inducible
   (see "HOLD — live-inducible" under Failure injection). The fake-claude
   stand-in never renders the trust dialog, so the scenario swaps in a `claude`
   stand-in for the retry attempt. If a worker still cannot induce it, it must
   cite `tests/test_workspace_trust.py` and the status-rendering tests rather
   than fail the story.
4. **"Another loop owns the launch"** — a second TUI is expected to report a
   non-retryable stand-down (documented residual), not to adopt the first
   loop's review. Scenarios assert the first loop is unharmed; the second TUI's
   own message is recorded as evidence, not asserted as a pass condition.

## Post-QA fixes to verify (1fc4 i1–i2, after the second QA run)

The second QA pass (scenarios 7–11) produced these fixes; scenarios must verify
them on the live surfaces, not just in tests:

1. **Child stderr is escaped before it enters a Rich-markup log line.** The TUI
   retry notice and the failed-completion notice interpolate the launch child's
   own stderr into a Rich-markup log line. A bracketed token (`[podman]`) was
   swallowed and an unbalanced tag (`[/tmp/pm-review]`) raised `MarkupError`,
   which `log_message` drops — so the concise error silently vanished exactly
   when the child's text was interesting. Both notices now escape the stderr
   and the artifact path; the text must render verbatim and the artifact must
   keep the exact stderr.
2. **A resume that cannot start must not strand the target.** After a
   breadcrumb restart, `consume_breadcrumb` restores the saved loop and calls
   `_start_loop`, which returns False when it cannot start (missing workdir, no
   tmux, unusable transcript dir). The resume used to announce "Review loop
   resumed …" anyway and leave a non-running loop entry, and
   `_auto_start_review_loops` skips a PR whose entry is non-running and not a
   retryable launch failure — the stranded target this PR removes, reached
   through a failed resume. The resume now logs honestly, drops the restored
   entry so the scheduler starts a fresh loop, and treats a raising starter the
   same way (it must not take the TUI mount down).
3. **A lease claimed after a stop is handed straight back.** The lease
   keepalive checked `stop_requested` before claiming but the claim is not
   atomic with that check; a supersede (`z d` / `zz d`) landing in between let
   the old loop re-take the lease the replacement needs, and the new loop's
   bounded claim wait expired into a non-retryable `LAUNCH_FAILED`. The
   keepalive now releases the lease when a stop landed during the claim.

New regression tests (fail on the pre-fix tree):
`tests/test_breadcrumb_review_loop.py::test_a_resume_that_cannot_start_drops_the_phantom_loop`,
`tests/test_breadcrumb_review_loop.py::test_a_raising_resume_is_treated_like_a_refusal`,
`tests/test_review_launch_retry.py::test_lease_keepalive_releases_a_lease_claimed_after_a_stop`,
`tests/test_review_launch_retry.py::test_retry_notice_shows_bracketed_child_stderr_verbatim`,
`tests/test_review_launch_retry.py::test_launch_failed_notice_shows_an_unbalanced_tag_in_stderr`.

Also re-verify on the live surface the earlier `f076 i1` item 2: a TUI restart
mid-retry must not re-announce a retry notice the user already saw
(`_ui_notified_retry` round-trips through the breadcrumb).
