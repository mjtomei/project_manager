# pr-6566901 QA spec — verdict-loop robustness: surface/retry when an expected verdict is never produced

## Summary of the change

Every loop that waits for an outcome from a Claude session (review loop,
watcher loop, and the QA loop's planner / refiner / scenario workers /
verifier / finalizer) used to block indefinitely when the session went idle
without emitting its expected verdict — a clarifying question, a provider
connection loss, a limit, or a completed result written as
`NEEDS_WORK — explanation` instead of a standalone keyword.

This PR adds one shared, bounded recovery to all of them:

* an idle turn without the expected outcome is counted, and the wait is
  bounded (default 3 recovery nudges, a 5 s settle window per nudge, a 1 h
  deadline from a nudge to the next turn);
* recovery sends the *same* session a short targeted request — "re-emit only
  your own standalone outcome" when the turn completed without a verdict, or
  "resume the same task" when the turn produced no output (provider error);
* if a newer turn lands during the settle window the nudge is deferred
  (never races a provider-native retry or queued user input); a hook refresh
  of the *same* turn counts against a separate bound;
* when the budget is spent the loop stops with a visible failure instead of
  hanging: `NO_VERDICT` for review/watcher (TUI `failed` state, autostart
  `failed`), `INPUT_REQUIRED` plus an actionable error for the QA planner and
  scenario workers, distinct reasons for the refiner/verifier, and
  `[finalize: NO_VERDICT]` for the finalizer.

Three new settings control it (`verdict-recovery-max-attempts`,
`verdict-recovery-settle-seconds`, `verdict-recovery-response-timeout`);
`verdict-recovery-max-attempts 0` restores the old unbounded wait.

## Setup (cross-cutting)

* Install pm from this branch (`./install.sh --local`, or the venv +
  `PYTHONPATH` override in `tui-manual-test.md`). `pm which` must print the
  clone, not `/opt/pm-src`.
* A throwaway git project: `pm init --backend local --no-import`, a few PRs,
  `pm session` started from it; a client attached to the pm session so the
  TUI (and its log line) can be captured.
* `pm fake-claude config set` drives every loop without real Claude. The
  per-type config is what a scenario tunes per role, e.g.

  ```json
  {"review": {"verdicts": []},
   "qa_planning": {"verdicts": ["QA_PLAN"]},
   "qa_concretize": {"verdicts": ["REFINED_STEPS"]},
   "qa_scenario": {"verdicts": ["PASS"]},
   "qa_verification": {"verdicts": ["VERIFIED"]},
   "qa_finalize": {"verdicts": ["FINALIZE_DONE"]}}
  ```

  An **explicit per-type entry with empty `verdicts`** is the way to make a
  verdict-producing role genuinely produce no verdict (`_all: {}` alone does
  *not* do it: a catch-all'd verdict-producing type is given its happy-path
  verdict). The fake writes its assistant turn to the JSONL transcript and
  keeps refreshing `idle_prompt` every ~2 s while it is held open, which is
  exactly the "session idled without its verdict" shape.
* **Timing note for scenario authors.** With the defaults (5 s settle vs. the
  fake's ~2 s refresh) the loop takes the *no-progress* path: each refresh is
  a deferral, and after the deferral bound the loop surfaces its terminal
  state without ever nudging. That is the PR's motivating repro and the
  fastest route to `NO_VERDICT` / `INPUT_REQUIRED`. Lowering
  `verdict-recovery-settle-seconds` below ~2 s makes the loop *nudge*
  instead; the fake then exits as soon as input arrives, so that run ends via
  pane death rather than exhaustion. Use the default settle when the
  expected observation is the terminal verdict, and a short settle only when
  the observation is the recovery request appearing in the pane.
* Loops are started from the TUI (`zz d` review loop, `t` QA run, `zz t` QA
  loop) or from the CLI (`pm watcher`, `pm qa run`, `pm autostart`), and pm
  commands are run inside a pane of the test tmux session.

## Requirements

**R1 — A review session that never emits a verdict must not hang the loop.**
Given a project whose review session produces output but no standalone
verdict, When the user starts the review loop and waits, Then the loop ends
on its own within a bounded time (no manual kill), the TUI log announces
`NO_VERDICT` for that PR together with the recovery explanation and the pm
log path, the tech tree / loop picker shows the loop as a failure rather than
a clean completion, the review pane is left open for inspection, and no
second review iteration is launched.

**R2 — Normal review runs are unaffected.**
Given a review session that emits `PASS` immediately (its only idle lands
inside the review grace window), When the user starts the review loop, Then
the verdict is accepted and the loop completes with `PASS` — no recovery
request is sent and no extra iteration runs. Likewise a review session that
takes a long time (e.g. a 45 s delayed `PASS`) is never nudged while it is
working, and its verdict is accepted when it arrives.

**R3 — Recovery asks for the agent's own outcome, not a replay of the task.**
Given a review session that has produced prose but no standalone verdict,
When the loop reaches a recovery point, Then the review pane receives a
short request to re-emit only the agent's own conclusion as one of the
allowed outcomes, alone on its own line, explicitly telling it not to redo
work or re-run tests; the original review prompt is not replayed, no verdict
is supplied or inferred, and prose that merely mentions an outcome is never
treated as a verdict (the run still ends `NO_VERDICT`, not `NEEDS_WORK`).

**R4 — A QA planner that never emits a complete plan surfaces an actionable
`INPUT_REQUIRED` instead of burning the run.**
Given a QA run whose planner idles without a complete `QA_PLAN` block, When
the user starts QA for that PR, Then planning ends on its own, the run stops
(no scenarios launched, no verification, no finalizer, PR not advanced), the
status pane / TUI log reports `INPUT_REQUIRED` with an error saying planning
did not produce a complete plan, naming the recovery detail and telling the
user the planner pane was left open and how to recover (re-emit the block or
restart QA).

**R5 — Scenario workers that never emit a verdict are retired, not waited on.**
Given a QA run whose scenario workers end their turns without a verdict,
When the run reaches the execution phase with more than one worker in
flight, Then each such worker is retired as `INPUT_REQUIRED` with a
per-scenario reason naming "worker produced no verdict (<reason>)" and its
own pane, the freed slots let the remaining work proceed, the run terminates
instead of hanging, the status pane shows the per-scenario verdicts, and the
PR is not reported as QA PASS. A run with normal workers still completes
`PASS` and proceeds to finalize, and a worker that legitimately answers
`INPUT_REQUIRED` is accepted as a verdict — it is not nudged or exhausted,
and QA waits for the human as before.

**R6 — The other QA roles surface a missing outcome distinctly.**
Given a QA run whose refiner / verifier / finalizer never produces its
outcome, When the run reaches that role, Then respectively: the scenario is
reported with a reason prefixed `no refiner outcome:` (not `refiner
rejected:`); verification fails with a `verifier produced no verdict:` reason
and blocks finalize; and the run's final output carries `[finalize:
NO_VERDICT]` with the PR left unmerged/unpushed. In every case the run ends
in bounded time with the role's pane left open.

**R7 — The recovery settings are user-visible, settable, and effective.**
Given a default install, When the user lists settings, Then the three
`verdict-recovery-*` keys appear with their defaults (3 attempts, 5 s settle,
3600 s response timeout); When the user sets a sub-second settle
(`0.5`) it is accepted, When the user sets a non-numeric or non-finite value
(`abc`, `inf`) it is rejected with a clear message and the stored value is
unchanged; When the user sets `verdict-recovery-max-attempts 0` and runs a
verdictless review loop, Then the loop keeps waiting (no `NO_VERDICT`
surfaced) until the user stops it, i.e. recovery is off.

**R8 — Non-TUI surfaces report `NO_VERDICT` as a failure.**
Given a watcher loop whose session never emits its watcher verdict, When the
user runs a single watcher iteration from the CLI, Then the command finishes
and reports `NO_VERDICT` as the last verdict instead of hanging. Given a
verdictless review loop for an autostart target, When it ends, Then
`pm autostart status` reports that PR's phase as failed (not waiting/paused)
and autostart does not advance the PR to its next phase.

**R9 — Teardown and concurrent runs stay clean.**
Given a loop sitting in a no-verdict episode, When the user stops that loop
(or the QA run), Then it stops promptly, the TUI log does not report a
worker/loop being retired as `INPUT_REQUIRED`/`NO_VERDICT` as a result of the
teardown, no recovery message is typed into a pane being torn down, and the
run can be restarted. Given two runs in flight at once (a stuck review loop
on one PR and a normal QA run on another), When the stuck one exhausts,
Then the other completes normally, both outcomes are visible in the TUI log,
and the tree shows one failed and one completed.

## Edge cases

* **Idle inside the grace window.** A verdict that arrives before the review
  grace (20 s) / QA grace (30 s) expires is still processed; the poller waits
  the grace out rather than dropping the event. Observable: a fast fake
  verdict completes the loop instead of stalling.
* **Long legitimate turn.** A session that is actively working emits no
  `idle_prompt`; it must not be nudged, and its late verdict is accepted.
* **Genuine `INPUT_REQUIRED`.** The `INPUT_REQUIRED` follow-up wait is
  human-driven and stays unbounded; a session that answers `INPUT_REQUIRED`
  is not nudged or exhausted.
* **Provider connection loss.** A turn that ends on a line-leading transport
  error is asked to *resume the same task*, not to emit an outcome; partial
  edits and queued input are preserved and completed work is not replayed.
  (Not deterministically drivable with the fake; note it in the report if a
  pane can be made to end on such a line.)
* **Pane death during recovery.** If the session's pane disappears mid-recovery
  the loop ends (pane-gone path) rather than hanging or raising.
* **A hook refresh of the same turn** must not extend the settle window
  forever: it counts against a deferral bound and ends in a bounded
  `no_progress` exhaustion. This is the fake's normal behaviour and the
  default-config path.
* **A newer turn during the settle window** (native retry / queued input)
  defers the nudge and resets the budget instead of racing it.
* **`max-attempts 0`** deliberately restores the old unbounded wait — that is
  the documented escape hatch, not a bug.
* **Finalize after a blocked verification** must not merge: a missing
  verifier outcome blocks finalize even when every scenario passed.

## Pass / Fail criteria

A scenario passes when every Then clause is observable in the captured
evidence (TUI framebuffer / pane scrollback / CLI output) and the runs
terminate without a manual kill. It fails if any loop hangs, if a missing
outcome is silently treated as a normal completion, if a verdict is inferred
from prose or supplied by the recovery message, if completed work is replayed
(a second review iteration, a re-run of finished tests), if a stop during
recovery records a spurious `INPUT_REQUIRED`/`NO_VERDICT`, or if a healthy
concurrent run is disturbed.

## Ambiguities resolved

1. **`_all: {}` vs. an explicit empty per-type entry.** `_all` alone no
   longer produces a verdictless verdict-producing session (it is given the
   happy-path verdict), so scenarios must use an explicit per-type entry with
   empty `verdicts` to create the hang shape.
2. **Is "re-send the original prompt" a replay?** No — in-tree callers send a
   short resume/outcome request; the original prompt stays in the session
   context. Scenarios therefore assert the *targeted* request, and that a
   full prompt replay does not appear in the pane.
3. **Fake exits when it receives a recovery nudge.** That is fake-specific
   (a real session answers). Such a run ends via pane death; scenarios that
   care about the terminal verdict use the default settle so the no-progress
   bound (no nudge) is what fires.
4. **`overall_timeout`** is a kwarg with no setting, so it is not
   user-testable; scenarios cover the settings-driven bounds instead.
5. **`verdict-recovery-max-attempts 0` hangs by design** — the legacy
   behaviour is intentionally retained and is asserted as "still waiting",
   not as a failure.
