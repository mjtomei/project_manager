# pr-6566901 — Verdict-loop robustness: surface/retry when an expected verdict is never produced

## Problem restated in code

`pm_core/loop_shared.poll_for_verdict()` (`pm_core/loop_shared.py:108`) is a
`while True:` loop whose only exits are:

* `stop_check()` / pane disappeared → returns `None`,
* a matching verdict in the latest assistant turn → returns the assistant text.

Everything else — notably an `idle_prompt` hook event with **no** matching
verdict — falls through to the next iteration. There is no attempt counter and
no deadline, so a session that ends a turn without the expected outcome spins
forever. The same shape exists in three other pollers that do not use
`poll_for_verdict`:

* the QA planner loop in `run_qa_sync` (`pm_core/qa_loop.py:3790-3900`) — bounded
  only by `_PLANNER_TIMEOUT = 60 * 60`, and it never asks the planner to
  re-emit a missing plan;
* the QA scenario worker loop `_poll_tmux_verdicts` (`pm_core/qa_loop.py:2590`)
  — bounded only by pane death; an alive-but-verdictless worker hangs QA
  forever (an optional, off-by-default reminder exists at `qa_loop.py:2998`);
* `wait_for_follow_up_verdict` (`pm_core/loop_shared.py:207`) — intentional
  human wait after `INPUT_REQUIRED`; left unbounded (see Ambiguities).

`poll_for_verdict` call sites:

| Caller | File:line | Verdicts |
| --- | --- | --- |
| review loop | `pm_core/review_loop.py:150` (wrapper), `:208`, `:258` | `PASS/NEEDS_WORK/INPUT_REQUIRED` |
| watcher base | `pm_core/watcher_base.py:158`, used at `:210` | watcher `VERDICTS` |
| QA finalize | `pm_core/qa_loop.py:713` | `FINALIZE_DONE/FINALIZE_BLOCKED` |
| QA concretize (refiner) | `pm_core/qa_loop.py:1713` | `REFINED_STEPS_END/REFINER_REJECT_END` |
| QA verification | `pm_core/qa_loop.py:3441` | `VERIFIED/FLAGGED_END` |

The QA planner has its own hook loop; `_poll_tmux_verdicts` has its own
`idle_prompt` gate. `verdict_transcript.extract_verdict_from_transcript` is
deliberately strict (keyword alone on a line) and stays that way.

The scans themselves go through `verdict_transcript.find_verdict_turn`
(task-scoped, from pr-8efa789): it returns a `VerdictHit` (verdict, turn
text, turn id/timestamp/line index) and ignores verdicts from an earlier
task, so a `/loop` wakeup or Monitor postscript after the verdict does not
hide it and a superseded turn's verdict is never re-consumed.
`extract_verdict_from_transcript` remains the strict string wrapper. Every
recovery `verdict_check` and last-chance re-scan uses `find_verdict_turn`
so "is there an outcome?" and "what is the outcome?" can never disagree.

## Requirements (grounded)

### R1 — Bound the wait in `poll_for_verdict`

Add to `poll_for_verdict` (`pm_core/loop_shared.py`):

* `max_missing: int | None = None` — number of `idle_prompt` turns **without** a
  matching verdict that are tolerated before giving up. `None` reads the
  global setting (default `3`); `<= 0` disables recovery (legacy behaviour).
* `overall_timeout: float | None = None` — optional wall-clock deadline for the
  whole poll. On expiry raise `VerdictRecoveryExhausted`.
* `response_timeout: float | None = None` — optional deadline for the *next*
  hook event after a recovery nudge. Only armed once a nudge has been sent, so
  a long first turn is never cut short. Default from setting (`3600`s); `<= 0`
  disables.

On exhaustion raise a new exception rather than returning `None` (which callers
already interpret as "pane died/stopped"):

```python
class VerdictRecoveryExhausted(RuntimeError):
    attempts: int
    last_output: str
    reason: str            # "no_output" | "no_verdict" | "no_progress"
                           # | "overall_timeout" | "no_response"
    session_id: str
    pane_id: str
    verdicts: tuple[str, ...]
```

The message names the session, the expected outcomes, the attempt count, the
last-turn classification, and the pane left open for inspection so the TUI
can surface it verbatim.

### R2 — Retry with targeted recovery messages

The poller cannot blindly re-send a multi-KB original prompt through
`tmux send-keys` (embedded newlines submit partial input; the original prompt
is already in the session's context). Recovery therefore sends one short
message per missing-output turn, chosen by classifying the latest assistant
turn with `read_latest_assistant_text`:

* **`no_output`** — the turn has no assistant text, or it ended on a
  line-leading provider/transport error (`API Error: Connection lost`,
  `Request failed: network error`, `Error: socket hang up`, …): send a
  *resume* request — "resume the same task in this session from where you
  left off; keep partial edits/evidence/queued input; do not restart
  completed work or repeat completed tests." If the caller supplies
  `retry_prompt`, send that instead (this is the configurable "re-send the
  original prompt" knob; the callers in this PR use the safe resume message).
  The provider-error match is line-leading and applies only to the turn's
  *final* non-empty line, so review prose discussing connection handling — or
  a completed review quoting an error line in its findings — is not
  misclassified.
* **`no_verdict`** — the turn has text but no standalone outcome (the audited
  `NEEDS_WORK — explanation` shape): send an *outcome* request that asks only
  for the agent's own standalone conclusion, e.g. "Re-emit only your own
  conclusion from the work already completed: exactly one of PASS, NEEDS_WORK,
  INPUT_REQUIRED, alone on its own line. Do not redo work, re-run tests, or
  restate evidence. If you have not finished, continue the task instead."
  It lists the allowed vocabulary but **never supplies or infers a verdict**
  and never restores permissive matching.

Callers may override either message (`resume_request`, `outcome_request`) —
the planner/refiner use block-marker variants (`QA_PLAN_START…END`,
`REFINED_STEPS_START…END`).

### R3 — Surface exhaustion instead of hanging

New terminal verdict `NO_VERDICT = "NO_VERDICT"` (exported from
`loop_shared`). Each loop catches `VerdictRecoveryExhausted`:

* review loop: records the iteration in history, sets
  `latest_verdict = NO_VERDICT`, `latest_output = str(exc)`, stops.
* watcher loop: same, with `latest_summary`.
* QA planner: sets `latest_verdict = INPUT_REQUIRED` and a specific `_error`
  ("planner produced no complete plan after N recovery attempts…"), surfaces
  the status pane (existing path).
* QA scenario worker: marks the scenario `INPUT_REQUIRED` with a specific
  `scenario_verdict_reasons` entry, frees the slot.
* QA refiner: returns a distinct `reject_reason` prefixed
  `no refiner outcome: …` (not mislabelled "refiner rejected").
* QA verifier: returns `passed=False` with the exhaustion detail appended to
  the reason (already blocks finalize).
* QA finalize: returns `"NO_VERDICT"`, surfaced as `[finalize: NO_VERDICT]`.

TUI wiring: `NO_VERDICT` icons/styles in `review_loop_ui`, `watcher_ui`,
`tech_tree`; review loop maps `NO_VERDICT` to runtime state `failed` (same as
`ERROR`/`KILLED`) and logs a sticky message with the error text and log path.
Both the review-loop and watcher stop lines escape the error text before it
reaches the Rich-markup log line (the text is arbitrary — exception messages,
agent output — and an unescaped `[...]` would be parsed as a style tag and
dropped from the log line). The QA status dashboard colours the QA-side
terminal verdicts (`qa_status._VERDICT_COLORS`), including the `STOPPED`
teardown state — dim like the other non-results (`queued`, `interactive`),
so a cancelled run's `Overall:` line cannot read as a renderer gap.

### R4 — Apply consistently across review, watcher, QA

All four poller families use one shared helper so behaviour cannot drift.

## Implicit requirements

* **Do not nudge a completed outcome.** Always try the transcript scan
  (`find_verdict_turn`, via `extract_verdict_from_transcript`) first;
  recovery only runs when it returns `None`. The check is repeated
  immediately before a nudge (`verdict_check`):
  the idle hook can fire before the transcript write lands (or a completed
  turn can land during the settle window), and recovery must return
  `"completed"` rather than ask a finished session to re-emit its outcome.
  This is the coordination point with pr-8efa789 (post-verdict wakeup
  ownership): a completed verdict is never treated as absent.
* **Never duplicate a native/provider recovery.** Before sending a nudge, wait
  up to `recovery_settle` seconds (default `5`) for a *newer* `idle_prompt`.
  If one arrives, reset the attempt counter and process the new turn instead of
  nudging. In tick-based loops, re-read the hook event and defer if its
  timestamp advanced. This is the 242-S40 race (`02:54:31Z`) guard.
  **Deferral must itself be bounded.** A newer `idle_prompt` only counts as
  native recovery when the transcript's latest assistant text changed
  **during the settle window** — i.e. the re-read taken after the wait
  differs from the text observed just before it. (Comparing against the
  text of recovery's *previous decision* instead is wrong: the poller may
  already be deciding about a turn recovery has not seen, and then a refresh
  of *that* turn would reset both the attempt budget and the deferral count,
  letting the loop defer forever without nudging or exhausting.) A *refresh*
  that re-announces the same turn (FakeClaude re-emits
  `idle_prompt` every 2s while held open) is counted against
  `max_deferrals` (default `10`, derived in `MissingOutputRecovery`) and then
  raises `VerdictRecoveryExhausted(reason="no_progress")`. Without this the
  settle window can be pushed forward forever and the poller hangs — the very
  bug this PR fixes. In the QA tick loop the settle window is measured from
  when the no-verdict episode began, not from the latest event timestamp, for
  the same reason. The tick loop also evaluates the settle/nudge on **every**
  tick while an episode is open, not only when a *fresh* event passes the
  turn-boundary gate: the realistic shape is one `idle_prompt` per turn, so a
  worker that ends its turn without a verdict and then waits for input emits
  no further event and would otherwise never be nudged at all.
* **Preserve attempt identity and partial work.** Recovery happens in the
  *same* pane/session; no relaunch, no transcript rewrite, no replayed tests.
* **Not missing-output failures:** active tool/monitor progress (no
  `idle_prompt` fires), permission/login holds (`permission_prompt` is a
  different event), genuine `INPUT_REQUIRED` verdicts (matched), and the
  `INPUT_REQUIRED` follow-up wait (human-driven). None of these may be nudged
  or counted.
* **Strict matching stays strict.** No change to
  `extract_verdict_from_transcript` or `match_verdict`.
* **Settings must be readable/listed.** Add the new keys to the `pm config`
  registry (`pm_core/cli/__init__.py` `_GLOBAL_SETTINGS`-style tables and help).
* **Backwards compatible signatures.** New `poll_for_verdict` kwargs are
  keyword-only with defaults; existing callers/tests keep working.
* **Thread safety.** Recovery state is per-poll; no shared globals. The QA
  tick loop keeps per-scenario counters in local dicts.

## Design

### Shared machinery (`pm_core/loop_shared.py`)

```
VERDICT_NO_VERDICT = "NO_VERDICT"

class VerdictRecoveryExhausted(RuntimeError): ...

def build_outcome_request(verdicts) -> str
def build_resume_request() -> str
def build_block_outcome_request(blocks: tuple[tuple[str,str], ...]) -> str
def build_block_resume_request(blocks: tuple[tuple[str,str], ...]) -> str

class MissingOutputRecovery:
    """Per-session attempt bookkeeping + message delivery."""
    def __init__(self, *, session_id, pane_id, verdicts, send,
                 max_attempts, settle_seconds, response_timeout,
                 max_deferrals=None, resume_request=None,
                 outcome_request=None, log_prefix=...)
    def reset(self) -> None                     # newer activity → attempts = 0
    def classify(self, transcript_path) -> str  # "no_output" | "no_verdict"
    def handle(self, transcript_path, ev_ts, *,
               wait_for_newer=None, stop_check=None,
               verdict_check=None) -> RecoveryResult
        # "deferred"  — a newer *turn* landed (transcript text changed during
        #               the settle wait); no nudge, budget reset.  A refresh of
        #               the turn being decided counts a deferral instead and
        #               exhausts with "no_progress".
        # "completed" — verdict_check found the expected outcome just before
        #               the nudge (transcript write raced the idle hook);
        #               no nudge; the caller records it
        # "nudged"    — recovery message sent, attempt counted
        # "stopped"   — stop_check fired during settle; caller returns
        # raises VerdictRecoveryExhausted when attempts/deferrals exceed max
    def check_response(self) -> None            # raises after response_timeout
```

For tick-based loops (`wait_for_newer` omitted) the settle check is a
non-blocking `hook_events.read_event` that counts **only** a newer
`idle_prompt` — matching the blocking `wait_for_event` filter. A newer
`Stop` / `permission_prompt` write is not a turn boundary and must not defer
(or close) a no-verdict episode.

`max_deferrals` is bounded by default (`DEFAULT_MAX_DEFERRALS = 10`); passing
`None` uses that default and passing `<= 0` disables the bound entirely (only
safe when a caller knows hook refreshes terminate). The count is
**consecutive**: it restarts whenever a nudge is sent (or a genuinely newer
turn is seen), so a session that answers every nudge cannot later be retired
with `no_progress` for a handful of refreshes spread across many turns.
`retry_prompt` / `resume_request` are delivered through `tmux send-keys`, so
embedded newlines would submit partial input. The tracker therefore enforces
the single-line invariant itself (`MissingOutputRecovery._message`): a
multi-line or padded request is collapsed with `" ".join(msg.split())` and
logged, and an *empty* request falls back to the built-in wording rather
than pressing Enter on whatever is already in the session's input box (a
queued user draft). This makes the `retry_prompt` knob — which by definition
carries an original, multi-line prompt — safe to use; the in-tree callers
still pass the short single-line resume/outcome requests.

`poll_for_verdict` grows the kwargs in R1 and, after a non-matching idle:

1. if `recovery` is disabled → old behaviour (continue);
2. `recovery.handle(transcript, ev_ts, wait_for_newer=…, stop_check=…,
   verdict_check=…)` — the settle window and the classification both live
   *inside* `handle`, which either:
   * defers on a newer *turn* (transcript changed): the poller updates
     `hook_baseline` and processes that event next (budget reset);
   * returns "completed" (the verdict landed during the settle): the poller
     re-scans and returns it;
   * returns "stopped" (stop_check fired): the poller returns `None`;
   * nudges: the poller waits for the next idle;
   exhaustion raises `VerdictRecoveryExhausted`;
3. on `ev is None` (wait timeout) call `recovery.check_response()`.

Both deadline raises (the `overall_timeout` check and `check_response`) run
one last transcript scan first and return a verdict found there.  A deadline
can expire on the tick the transcript is flushed — its `idle_prompt` may be
missed, or predate the poller's hook baseline in the re-check case — and
reporting that turn as absent would be the "completed result treated as
absent" failure.  It is the same last-chance re-scan the QA tick loop does in
`_retire_if_exhausted`.

`wait_for_follow_up_verdict` is **not** changed (human wait; see Ambiguities).
Its one machine-driven caller — the QA verifier's re-check follow-up — was
switched to `poll_for_verdict` so that wait is bounded too (see the QA loop
verifier bullet).

For tick-based loops the tracker is handed the hook timestamp it has already
accounted for (the episode's opening event, then the last deferred event),
never the event just read: `_newer_event` compares against that value, so
passing the current event would make every refresh look like "no new event"
and the worker would be nudged instead of exhausting with `no_progress`. The
QA tick loop keeps that per-scenario value in `_recovery_ev_ts` and drops it
alongside the episode/settle state on nudge, verdict, exhaustion and relaunch.

### Review loop (`pm_core/review_loop.py`)

* import `VerdictRecoveryExhausted`, `VERDICT_NO_VERDICT`;
* `_poll_for_verdict` relies on the settings-driven defaults (it passes no
  recovery kwargs);
* `run_review_loop_sync` catches exhaustion around `_run_claude_review` /
  `_adopt_in_flight_review`, appends a `ReviewIteration` with verdict
  `NO_VERDICT`, calls `on_iteration`, breaks. A stop that landed while
  `handle` was deciding (`state.stop_requested` set inside the catch) is
  teardown, not a missing verdict: it breaks like the stop check at the top
  of the loop, recording no `NO_VERDICT` iteration. The poller's
  `stop_check` is the launch-lease keepalive, which deliberately never stops
  the poll (`_lease_keepalive` always returns False), so this catch is what
  covers a stop racing the exhaustion decision.

### Watcher loop (`pm_core/watcher_base.py`)

* `_poll_for_verdict` relies on the settings-driven defaults (it passes
  `stop_check` but no recovery kwargs);
* `run_sync` catches exhaustion, records a `WatcherIteration` with
  `NO_VERDICT`, sets `latest_summary`, breaks. A stop that landed while
  `handle` was deciding (`stop_requested` set inside the catch) is teardown,
  not a missing verdict: it mirrors the `PaneKilledError` stop convention
  (`KILLED`) instead of recording `NO_VERDICT`.

### QA loop (`pm_core/qa_loop.py`)

* **finalize** — relies on the settings-driven defaults; catch exhaustion →
  return `"NO_VERDICT"`. A stop that landed while `handle` was deciding
  (`stop_check()` true inside the catch) is teardown, not a missing outcome:
  it returns `None` (the unfinalized result), like the `not content` path, so
  a user-stopped run never surfaces `[finalize: NO_VERDICT]`.
* **refiner** (`_concretize_scenario`) — pass a block outcome request and
  the caller's `stop_check`; catch → `(None, "no refiner outcome: …")`; teach
  `_concretize_failure_label` to pass that prefix through unchanged.  The
  concretizer is the last poller that could turn a user stop into a
  missing-outcome failure: the poll is given `stop_check` (so a stopping run
  never nudges the refiner session), and an exhaustion that lands while
  stopping returns `(None, None)` — teardown, not a refiner failure — so no
  per-scenario INPUT_REQUIRED reason is recorded.  `_concretize_and_launch`
  (both the tmux and container launchers) returns before the concretizer
  runs and again before the worker is split when `state.stop_requested`, so
  a stop during concretization leaves the scenario unverdicted and the run
  ends in the `STOPPED` teardown rather than spawning a worker.
* **verifier** (`_verify_single_scenario`) — pass verifier-specific
  outcome/resume requests (`VERIFIED` / the `FLAGGED_START…FLAGGED_END`
  block, hoisted to module constants); catch →
  `(False, "verifier produced no verdict: …", pane)`. The **re-verification
  follow-up** (the same pane asked for a new outcome after the scenario was
  re-evaluated) uses the shared `poll_for_verdict` for the same bounded
  recovery, not `wait_for_follow_up_verdict`: that helper is the *human*
  `INPUT_REQUIRED` wait and stays unbounded, but this follow-up is
  machine-driven and a verifier that idled without `VERIFIED`/`FLAGGED`
  there hung QA forever (the class this PR targets).
* **scenario workers** (`_poll_tmux_verdicts`) — per-scenario
  `MissingOutputRecovery`; a fresh `idle_prompt` with no verdict opens a
  no-verdict episode whose settle window is measured from *episode start*
  (not the latest event), and the settle/nudge is evaluated on every tick
  while the episode is open. On exhaustion the scenario is marked
  `INPUT_REQUIRED` with a reason of the form
  `"worker produced no verdict (<reason>): …"` (`str(exc)` already carries the
  attempt/deferral count, so no separate "after N attempt(s)" prefix),
  `pending` is discarded and the slot freed. The retirement is surfaced
  like every other `INPUT_REQUIRED` transition in the loop — a
  `state.latest_output` line ("Scenario N (title): INPUT_REQUIRED (worker
  produced no verdict: <reason>)") plus `_notify()`, so the TUI log names
  it rather than leaving it only in the status pane. The legacy
  `qa-verdict-reminder-timeout` path is replaced by this bounded recovery
  (setting retained but now only tunes the settle interval). A `deferred`
  result restarts the settle window rather than closing the episode; a
  `completed` result records the verdict that landed during the settle.
  The per-scenario bookkeeping lives in `_recoveries` / `_no_verdict_since`
  / `_recovery_ev_ts` and is always cleared through `_close_episode`
  (episode only, keeping the attempt budget) or `_drop_recovery` (all
  three) so the three dicts cannot drift apart. The post-nudge
  `check_response()` runs *after* the fresh-event/verdict scan and is
  skipped when a verdict was found: a verdict that lands on the very tick
  the response deadline expires must be recorded, not retired as
  `no_response` (the "completed result treated as absent" failure). Both
  `check_response()` and the settle/nudge block are skipped while the run
  is stopping (`state.stop_requested`): a stop is set from the TUI thread
  and can land between two ticks, after the `while` condition was
  evaluated, so without the guard a worker being torn down would be
  retired as `no_response` (or `no_progress` — `handle`'s deferral bound
  is checked before its own `stop_check`) with a reason that is persisted
  into the resume snapshot. The guard is a snapshot taken just before the
  check, so both `except VerdictRecoveryExhausted` handlers *also* re-check
  `state.stop_requested` before retiring: a stop can land while `handle`
  is deciding (its deferral bound is checked before its own `stop_check`,
  and the tick loop's settle read is non-blocking), and teardown must not
  persist an `INPUT_REQUIRED` reason. Those handlers additionally re-scan
  the transcript before retiring: the scan at the idle event races
  the transcript write and `handle`'s `no_progress` bound is checked before
  its own `verdict_check`, so an outcome that landed as the deadline
  expired must be recorded rather than retired as `no_response` /
  `no_progress` (the "completed result treated as absent" failure). Both
  exhaustion sites share `_retire_if_exhausted` (teardown guard + re-scan
  + retire + slot bookkeeping) so the two paths cannot drift apart; it
  returns the verdict that landed during the deadline, which the caller
  then records normally. The planner honours `stop_requested` the same way
  before its `check_response`.
* **planner** — per-attempt `MissingOutputRecovery` with a `QA_PLAN_START/END`
  outcome request and a resume request; on exhaustion break out with
  `INPUT_REQUIRED` + `_error` (reusing the existing "plan incomplete" surface
  block, and naming the validator's last rejection when the planner did emit
  a block that could not be consumed). The *nudge* names that rejection too
  (the outcome request is a callable reading the current `plan_problem`,
  collapsed to one line): a generic "re-emit your completed result" invites
  the same malformed block again, so a plan `qa_plan_problem` refused (e.g.
  non-contiguous numbering) must be told what was wrong. The request still
  supplies or infers no plan. A `completed` result re-reads and
  accepts the plan. A stop request is honoured before `check_response`, and
  both `except VerdictRecoveryExhausted` handlers (the `check_response` one
  and the `handle` one) re-check `state.stop_requested` before setting
  `planner_exhausted`: `handle`'s deferral bound runs *before* its own
  `stop_check`, so a stop set from the TUI thread while it decides can
  surface as a spurious exhaustion. Without the re-check that would end a
  user-stopped run with `INPUT_REQUIRED` + a QA note (the bug the `STOPPED`
  path fixes), so it falls through to the clean `STOPPED` teardown instead.
  Keep `_PLANNER_TIMEOUT` as the outer deadline.
  A stop before any plan was accepted ends the run in the terminal
  `STOPPED` state (`latest_output = "QA stopped during planning"`): the
  no-scenarios path would otherwise report `INPUT_REQUIRED` with "Planner
  produced no parseable scenarios" and record a QA note, turning a user
  stop into a missing-plan failure. `qa_loop_ui` logs `QA stopped for <pr>
  — no verdict recorded` and skips both the lifecycle transition and the
  QA note for it. `STOPPED` is not in `ALL_VERDICTS`: nothing about the PR
  was determined, so it must never parse as a result.
* **The same contract covers a stop during execution** — the tick loop's
  stop guards keep a worker from being *retired* while the run is torn down,
  but the aggregation in `_execute_and_finalize` still saw its scenarios as
  unverdicted and reported `INPUT_REQUIRED` ("Execution worker one: ?") with
  a QA note, i.e. a user stop surfaced as a missing-outcome failure one
  phase later. A stop that leaves *every* scenario unverdicted (and no
  `_error` / `planner_code_changes`) now ends in `STOPPED`
  (`latest_output = "QA stopped during execution"`), skips the finalize pane
  (there is nothing to reconcile, and spawning one only logs "pane vanished
  or stop_check fired"), and therefore records no QA note and does not
  transition the PR. A stop *after* some scenarios reported keeps the
  `INPUT_REQUIRED` coverage warning: real verdicts were recorded, so the run
  is not "nothing determined" (and an incomplete run must still never be
  reported as `PASS`). Regression tests:
  `TestStoppedRunAggregation::test_stop_before_any_verdict_is_stopped_not_input_required`
  and `::test_stopped_before_any_verdict_skips_the_finalizer`; the partial
  case stays pinned by `::test_missing_verdict_is_input_required`.
  **A stop before the workers exist is the same teardown.** The launch skips
  a stopping run, so its scenarios have no window; `_poll_tmux_verdicts`
  would otherwise retire each one as `INPUT_REQUIRED` ("worker window never
  created (launch failed)") and fill open slots by launching queued workers.
  Both defeat `stopped_clean` (a launch-failure verdict is still a verdict),
  so a run stopped between "plan parsed" and "workers launched" surfaced a
  missing-outcome failure and recorded a QA note. `_poll_tmux_verdicts` now
  returns immediately when the run is already stopping, and
  `_launch_next_queued` refuses to launch while stopping. Regression tests:
  `TestStoppedRunBeforeLaunch` (no verdict recorded, no queued launch, the
  aggregation still ends `STOPPED`).
* **A stop during finalize is the same teardown** — the finalize pane is the
  run's last step (it confirms the scenario pushes and reconciles the PR
  workdir), so a stop that lands while it is polling means the run never
  produced its outcome. `_run_qa_finalize_pane` already returns `None` on a
  stop instead of `[finalize: NO_VERDICT]`, but the pre-finalize aggregate was
  written and reported as-is: a run whose scenarios had all passed logged
  `QA complete: PASS` / `QA PASS` and recorded a `QA PASS: …` note for a run
  the user cancelled. When the stop left the finalize verdict `None` and the
  pre-finalize aggregate was `PASS`, the run now ends in `STOPPED`
  (`latest_output = "QA stopped during finalize"`), the status file is
  rewritten so the status pane shows `Overall: STOPPED`, and the TUI records
  no QA note and makes no lifecycle transition. Only a `PASS` is converted:
  a `NEEDS_WORK` / `INPUT_REQUIRED` finding stays reported (the run did
  determine something about the PR), and a finalize that already produced
  `FINALIZE_DONE` keeps its `PASS`. Regression tests:
  `::test_stop_during_finalize_is_stopped_not_pass`,
  `::test_stop_during_finalize_keeps_a_needs_work_finding` and
  `::test_completed_finalize_then_stop_stays_pass`.
* **A user stop survives a TUI restart** — the same teardown contract, one
  process later. `qa_resume.json` did not carry `stop_requested`, so a
  restart that re-adopted an in-flight run resumed *collecting* verdicts for
  a run the user had stopped; and because `_execute_and_finalize` writes
  `overall` *before* the blocking finalize pane, a stop that landed while
  that pane polled left its pre-finalize `PASS` on disk, so the TUI's
  "completed during downtime" path recorded a QA PASS (note + lifecycle
  hand-off) for a cancelled run. `_write_resume_file` now persists
  `stop_requested` and `build_resume_state` restores it, so a re-spawned
  loop ends in the same clean teardown. For the completed-snapshot path,
  `qa_loop.recovered_overall_verdict()` applies the live `stopped_in_finalize`
  rule (PASS + stop + no finalize outcome → `STOPPED`, everything else keeps
  its recorded verdict) and `qa_loop.set_status_overall()` rewrites only the
  `overall` field so the status pane agrees while the scenario table and any
  error block are preserved. Regression tests:
  `tests/test_qa_resume.py::test_resume_roundtrip_preserves_a_user_stop`,
  `::test_resume_stop_during_finalize_reports_stopped`,
  `::test_resume_completed_finalize_then_stop_keeps_pass` and
  `::test_resume_stopped_incomplete_run_respawns_and_stays_stopped`.
* **Persist the stop when it is requested** — the pre-finalize snapshot is
  written *before* the finalize pane blocks, so a stop that lands during the
  poll is not in it; a restart in that window still recovered the pre-stop
  `PASS`. `qa_loop.mark_stop_requested(state)` now flips `stop_requested` in
  the existing snapshot (a read-modify-write under `_RESUME_WRITE_LOCK`,
  preserving every other field) the moment the user stops, from
  `qa_loop_ui.stop_qa` and `start_or_stop_qa_loop`. The daemon's later writes
  carry it too (`_write_resume_file` reads `state.stop_requested`).
  Regression tests:
  `tests/test_qa_resume.py::test_mark_stop_requested_persists_without_losing_fields`,
  `::test_mark_stop_requested_without_snapshot_is_a_noop` and
  `::test_stop_during_finalize_poll_recovers_stopped`.
* **A recovered verdict is mirrored into runtime_state** — a run recovered by
  the "completed during downtime" path is not tracked in `app._qa_loops`, so
  the live completion mirror in `poll_qa_state` never records its verdict.
  `_resume_incomplete_qa` now writes it (`set_action_state(pr, "qa", "done",
  verdict=...)`) just as the live path does. Without it `recorded_qa_verdict`
  returned `None` and `_auto_start_qa_loops` relaunched QA for a recovered
  `STOPPED` run — undoing the user's stop one restart later — and the popup
  lost its `[done VERDICT]` for the other recovered verdicts. The mirror is
  written inside the recovery scan (while `Path.home()` is the test's) and
  only for a run not already tracked or owned elsewhere (the scan's existing
  skip guards), so it cannot clobber a newer live run's record. Covered by
  the `::test_stop_during_finalize_poll_recovers_stopped` runtime_state
  assertion.
* **STOPPED is a hold verdict for auto-start** — `STOPPED` is recorded in
  runtime_state like any finished run (state `done`), so
  `auto_start.QA_HOLD_VERDICTS` must include it: otherwise
  `_auto_start_qa_loops` restarts QA on the next scheduler pass and silently
  undoes the user's stop (every stop used to end `INPUT_REQUIRED`, which
  held). `autostart_state._derive` reports it as `waiting` with "last QA run
  was stopped; press t / z t to re-run QA" — an explicit re-run (which
  overwrites the record) is the way back.
* **Queued scenarios stay on the dashboard during launch** — the
  launch-time status write inside `_launch_scenarios_in_tmux` /
  `_launch_scenarios_in_containers` runs while `state.scenarios` is
  temporarily narrowed to the launch batch, and it previously passed no
  `queued_scenarios` set. It therefore overwrote the correct initial
  `qa_status.json` with a rows-only-for-the-batch version, so scenarios
  still waiting on the concurrency cap showed as *pending* instead of
  *queued* (and disappeared from the status pane) until a later rewrite.
  Both launchers take `_status_scenarios` (the full list) and
  `_queued_indices` (the still-queued set) and pass them to
  `_write_status_file`; the initial launch in `run_qa_sync` and every
  queued relaunch in `_launch_next_queued` supply them. Regression tests:
  `TestQueuedScenariosStayVisible` in `tests/test_qa_loop.py`.
* **A replaced QA window belongs to the new run** — Phase 2 re-resolved the
  QA window by *name* (`_ensure_qa_main_pane` → `find_window_by_name`) to
  add the status pane. A run whose planner pane had died (its window killed
  by a `z t` / fresh start for the same PR) therefore found the
  *replacement* run's window under that name, split its planner pane and
  left the replacement showing the dead run's dashboard ("No parseable
  scenarios…") beside its own — three panes once the replacement finished.
  The window name is only adopted when this run's planner pane is still
  alive; if it is gone and a window with the name exists, the run keeps its
  own status file and logs that it is not adopting the replacement. A
  vanished window with the name free is still recreated (the execution-only
  restart path). The planner pane is therefore initialised to `None` before
  Phase 1: a run that skips planning entirely (`pm qa run <instruction>`
  builds its state with `planning_phase=False` and the scenario pre-loaded)
  never binds it, and Phase 2 must see "no planner pane" rather than an
  unbound local. Regression tests:
  `TestDeadRunDoesNotAdoptReplacementWindow` and
  `TestExecutionOnlyPhase2` in
  `tests/test_qa_planner_handoff.py`.

### Settings (all optional, defaulted)

| key | default | meaning |
| --- | --- | --- |
| `verdict-recovery-max-attempts` | `3` | nudges per session before exhaustion (integer; `<= 0` = off) |
| `verdict-recovery-settle-seconds` | `5` | wait for a newer idle before nudging (float) |
| `verdict-recovery-response-timeout` | `3600` | max seconds from nudge to next idle (float; `0` = off) |
| `qa-verdict-reminder-timeout` | unset | retained: overrides the settle interval for QA scenario workers |

`verdict-recovery-max-attempts` is registered in `_INT_SETTINGS`; the two
seconds-valued keys are in a new `_FLOAT_SETTINGS` table so sub-second
values (e.g. `0.5`) are accepted by `pm set`. Non-finite values (`nan`,
`inf`) are rejected by `pm set` and ignored (default used) when read from a
hand-edited settings file — `inf` as a settle window would otherwise be
unbounded.

## Ambiguities and resolutions

1. **"Re-send the original prompt" vs. the audit's "resume the SAME
   task/session" and "do not replay completed tests".** Resolved: recovery
   sends a short targeted resume/outcome request in the same session. A
   `retry_prompt` kwarg lets a caller re-send an original prompt verbatim when
   that is genuinely safe; the audited paths (completed review, planner,
   refiner, finalize) use the targeted messages. The original prompt remains
   in the session context, so the task is retried without duplicating work.
2. **Is `NEEDS_WORK — explanation` a verdict?** No — the strict matcher stays
   strict. It is a *completed result needing format repair*, so we ask only
   for the agent's own standalone outcome. We never parse the prose into a
   verdict.
3. **Should the `INPUT_REQUIRED` follow-up wait be bounded?** No. The audit
   lists genuine `INPUT_REQUIRED` as not a missing-output failure; that wait is
   an intentional human interaction, not a hung expected verdict. The shared
   `wait_for_follow_up_verdict` stays unbounded, but its *machine-driven* user
   (the QA verifier's re-check follow-up, which asks the verifier for a new
   `VERIFIED`/`FLAGGED` outcome) is a hung expected verdict and now goes
   through `poll_for_verdict`'s bounded recovery instead.
4. **New verdict string vs. reusing `ERROR`.** Resolved: add `NO_VERDICT`
   (distinct from launch/runtime `ERROR`) so the failure mode is visible in the
   TUI, picker and logs, and so QA can assert on it.
5. **Default wall-clock deadline.** Resolved: max-idles is the primary bound
   (it is the actual bug); `overall_timeout` is available and off by default so
   long legitimate turns are never cut; the post-nudge `response_timeout`
   (1 h) covers a session that goes silent after a nudge.
6. **Detecting "queued input".** tmux offers no reliable "pending input"
   query. Resolved: the settle window + newer-hook-event check is the
   practical guard; a queued-but-unsubmitted user draft will itself produce the
   next idle event and reset the attempt counter. Documented residual.

## Edge cases

* **Fake sessions** (`pm_core/fake_claude.py`) refresh `idle_prompt` while
  held open. They write their verdict transcript before the first event, so
  the first idle still matches. A deliberately verdictless fake now exhausts
  (bounded, instead of hanging) — implemented via the content-aware deferral
  bound: a refresh that does not change the transcript counts against
  `max_deferrals` and raises `no_progress`, so the fake is never nudged (a
  nudge would close its stdin) and `NO_VERDICT` is surfaced. This holds for
  both `poll_for_verdict` (blocking settle) and the QA tick loop (which
  passes the previously handled event timestamp, see Design).
* **Autostart** treats a `NO_VERDICT` review-loop verdict as `failed`
  (`pm_core/autostart_state.py`), like `ERROR`/`KILLED`.
* **Grace periods** (`review 20s`, `QA 30s`) still gate verdict acceptance, so
  we only nudge on post-grace idles. An idle that arrives *inside* the grace
  window is not discarded: the poller waits out the remaining grace (honouring
  `stop_check`, pane death and `overall_timeout`) and then processes that same
  event — verdict scan, then bounded recovery. Discarding it (the old
  behaviour) advanced the hook baseline, so a session whose only idle landed
  early (a fast verdict or an immediate provider error) left the poller
  waiting for a turn that never came: the very hang recovery exists to
  prevent. Verdicts come from the transcript's latest assistant turn, so an
  early idle is a real turn boundary rather than the pane echoing the prompt
  (the original reason for the grace). The QA tick loop already behaved this
  way (`in_grace` skips the tick without advancing its hook baseline).
* **Panes that die after a nudge** → `pane_exists` returns `None` as today.
* **Multiple markers** (refiner emits both blocks) — rejection precedence is
  unchanged; recovery only fires when neither END marker matched.
* **`stop_check` during settle** → `wait_for_event` returns `None`; the poller
  re-checks `stop_check` before nudging and returns `None`.
* **Transcript missing/unreadable** → `classify` treats it as `no_output`
  (resume), which is the safer request.
* **A session that never idles again is not bounded by default.** Recovery is
  driven by `idle_prompt` events, so a poller that starts while its session is
  *already* idle (review-loop adoption after a TUI restart, `_adopt_in_flight_review`)
  waits for the next turn boundary; if none comes, it waits until the pane
  dies or `stop_check` fires. `overall_timeout` is the opt-in bound. Nudging on
  the pre-existing idle event instead was rejected: a session that had already
  started its next turn would receive queued input, which the audit lists as
  something recovery must not do.
* **`VerdictRecoveryExhausted` is a `RuntimeError`** so any caller that has not
  been updated still fails loudly (generic `except Exception` handlers set
  `ERROR`) rather than hanging.

## Integration with master (2026-10-29)

`origin/master` at `4a74d88085edffcc300cb21f31777a798d647782` was merged
into this branch. The conflict resolution keeps both sides' behaviour:

* **Verdict scanning.** Master replaced the scenario/finalize scans with
  `find_verdict_turn` (task-scoped, `VerdictHit`, pr-8efa789). Recovery
  integrated onto that primitive: the tick loop's fresh-event scan,
  `verdict_check`, the "completed during settle" re-scan and
  `_retire_if_exhausted` all use `find_verdict_turn`; a hit is recorded
  through master's `_accept_hit`, which also clears the recovery episode
  (`_drop_recovery`). `poll_for_verdict`'s `verdict_check` and its
  "completed" return use it too and return the verdict turn's text.
* **INPUT_REQUIRED follow-up (pr-2c67d50).** Master's `waiting_for_input` /
  `_accept_hit` / `_poll_waiting` / `_hold_for_follow_up` machinery is kept.
  A scenario in `waiting_for_input` is user-bound, not a missing output: it
  is excluded from `pending` (`_needs_polling`) and is never nudged.
  Accepting any verdict (including `INPUT_REQUIRED`) closes its recovery
  episode.
* **Review launch retry / hold (pr-e040aeb).** `ReviewClosedError`,
  `ReviewHoldError`, `ReviewLaunchError` handlers and their TUI text
  (`LAUNCH_FAILED`, `HOLD`, artifact/retry hints) are kept alongside
  `VerdictRecoveryExhausted`; `_format_completion_message` gained the
  retry/artifact branches and takes the app for the auto-start re-arm hint.
* **QA finalize hold loop.** Master's `while True:` hold/reopen structure is
  kept and the STOPPED teardown is layered onto it: `stopped_clean` (no
  scenario outcome) skips the finalize pane, `stopped_in_finalize` converts
  a pre-finalize `PASS` to `STOPPED` and rewrites the status file, and
  `input_wait_code_changes` routes a head that moved during an input wait
  back to review. A held (restored) run still skips the duplicate finalize.
* **Verifier re-check.** The re-verification follow-up uses
  `poll_for_verdict` (bounded recovery) with verifier-specific requests, not
  the unbounded human `wait_for_follow_up_verdict`. Master's
  `baseline_line` snapshot *is* still needed, and is kept: the follow-up is
  sent before the poll starts, so the verifier can answer during the
  send/settle window and its `idle_prompt` then predates the poller's hook
  baseline — the event loop would never see it and the re-check would block
  until the response timeout (the hang class this PR targets). `poll_for_verdict`
  therefore grew an optional `baseline_line` kwarg: when set it scans the
  transcript once before blocking and returns a verdict *newer* than the
  snapshot, and every later scan (`_scan`) filters out the prompting verdict
  at or below the baseline. `find_verdict_turn` is task-scoped, but a
  follow-up the transcript does not record as a task boundary would
  otherwise let the prompting verdict be returned as the answer. The test
  asserts the contract (the poller is used, `baseline_line` is passed, and an
  answer already in the transcript is returned).
* **Project registry.** `pm/project.yaml` conflicts were resolved as a union
  of both sides' PR entries and notes (518 PRs, no duplicate ids, no lost
  notes); `active_pr` takes master's value.

## Tests

* `tests/test_loop_recovery.py` (new): shared recovery unit tests —
  no-verdict nudge then success; exhaustion after N; no-output → resume
  message; output → outcome message that names no specific verdict; every
  built request (outcome / resume / both block variants / the verifier's
  two) is a single `tmux send-keys` line (a newline would submit partial
  input); a caller-supplied multi-line `retry_prompt` is collapsed to one
  line, and an empty request falls back to the default wording (an empty
  send would press Enter on a queued draft); a provider error is only
  recognised on the turn's final line (a
  quoted error line among findings is `no_verdict`); a
  genuine newer turn during settle defers and resets; a hook refresh of the
  same turn defers without resetting and exhausts with `no_progress`
  (including the `poll_for_verdict` and QA-tick-loop integration cases); a
  refresh that follows a *new* turn the poller is already deciding about
  still does not reset the nudge budget; `retry_prompt` reaches the session
  through `poll_for_verdict` (the "re-send the original prompt" knob);
  a newer non-idle event (`Stop`) is not a new turn; overall timeout;
  response timeout; a verdict already in the transcript is returned when
  either deadline expires (rather than reported absent); recovery disabled
  keeps legacy behaviour; an idle inside
  the grace window is processed rather than dropped (the poller would
  otherwise wait for a turn that never comes); `stop_check`
  during settle does not nudge; the deferral budget is *consecutive* (a
  nudge restarts it, so an answered session is not later retired with
  `no_progress`); a verdict flushed during the settle window
  returns `"completed"` and is never nudged (unit, `poll_for_verdict`, and
  QA-tick-loop cases); `baseline_line` returns an answer already in the
  transcript (the re-check's send/settle race) and never returns the
  prompting verdict at or below the baseline. Also holds the loop wiring
  tests below.
* `tests/test_loop_recovery.py` (review/watcher wiring): exhaustion →
  `NO_VERDICT`, history entry, callback fired; QA refiner label (and
  `(None, None)` — not a `no refiner outcome` reason — when the stop lands
  inside recovery, with the poll itself given the stop check), verifier
  reason (initial poll and the machine-driven re-check follow-up, which must
  call the shared poller — with `baseline_line` — rather than the unbounded
  human wait), finalize
  `NO_VERDICT` (and `None` — not `NO_VERDICT` — when the stop lands inside
  recovery), scenario-worker exhaustion
  (`INPUT_REQUIRED` + reason, slot freed); a verdict landing on the tick the
  post-nudge response deadline expires is recorded, not retired as
  `no_response`, and one that lands *after* that tick's scan is found by the
  exhaustion re-scan; a *nudged* worker that answers with its verdict on the
  next turn has it recorded with only that one nudge rather than being
  retired — the tick loop's "retried, then succeeded" path; a stop
  that lands between ticks does not retire a
  worker as `no_response`, and a stop set *inside* `handle` (after the
  `stopping` snapshot) does not retire it either (both are
  spurious-exhaustion guards during teardown); a review/watcher stop that
  lands inside `handle` does not record `NO_VERDICT` (the review loop keeps
  its prior verdict, the watcher records the `KILLED` stop convention).
* `tests/test_qa_planner_handoff.py`: a stop that lands inside `handle`
  ends the run in `STOPPED` (clean teardown), not `INPUT_REQUIRED`; planner
  exhaustion surfaces
  `INPUT_REQUIRED` + error and stops planning; exhaustion after a malformed
  block names the validator's rejection (e.g. non-contiguous numbering) in
  `_error`, and the recovery *nudge* for that block names it too (single
  line, still no plan supplied); a plan written while recovery
  settles (the idle-hook/transcript-write race) is accepted from the settle
  re-read rather than being asked for again; a planner that answers the
  nudge with its complete block on the next turn is accepted with exactly
  one nudge (the planner's "retried, then succeeded" path).
* `tests/test_review_loop_terminal_state.py`: `NO_VERDICT` → `failed`; the
  completion log line keeps a bracketed error detail intact (escaped for Rich
  markup) for both `NO_VERDICT` and `ERROR`, and omits the error block for a
  clean verdict.
* `tests/test_autostart_multi_target.py`: `NO_VERDICT` review loop → phase
  state `failed` in the status builder; a recorded `STOPPED` QA run is a
  hold verdict (the scheduler does not relaunch it) and reports as
  `waiting` with the manual re-run hint.
* `tests/test_loop_recovery.py` (settings): the three keys are settable and
  listed through `pm set` (including a sub-second float), non-numeric values
  are rejected, a negative settle clamps to 0, and corrupt stored values fall
  back to the defaults. The retained `qa-verdict-reminder-timeout` override
  of the QA scenario-worker settle interval is covered end to end (a 1 s
  override nudges within a couple of ticks even when the shared settle is
  100 s).
* `tests/test_qa_loop.py`: `TestQueuedScenariosStayVisible` — the
  launch-time status write keeps the still-queued rows (verdict "queued")
  and receives the full scenario list plus the queued set.
* Existing suite (4100+ tests) must stay green.
