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
  The provider-error match is line-leading only, so review prose discussing
  connection handling is not misclassified.
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

### R4 — Apply consistently across review, watcher, QA

All four poller families use one shared helper so behaviour cannot drift.

## Implicit requirements

* **Do not nudge a completed outcome.** Always try
  `extract_verdict_from_transcript` first; recovery only runs when it returns
  `None`. The check is repeated immediately before a nudge (`verdict_check`):
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
  native recovery when the transcript's latest assistant text actually
  changed; a *refresh* that re-announces the same turn (FakeClaude re-emits
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
        # "deferred"  — a newer *turn* landed (transcript changed); no nudge,
        #               budget reset.  A refresh of the same turn counts a
        #               deferral instead and exhausts with "no_progress".
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

`poll_for_verdict` grows the kwargs in R1 and, after a non-matching idle:

1. if `recovery` is disabled → old behaviour (continue);
2. `kind = recovery.classify(transcript)`;
3. settle via `hook_events.wait_for_event(..., timeout=settle, newer_than=ev_ts)`
   → if a new *turn* (transcript changed): update `hook_baseline`,
   `recovery.reset()`, continue; if only a hook refresh: count a deferral;
4. `recovery.handle(...)` → "nudged", continue; exhaustion raises; "stopped"
   returns `None`;
5. on `ev is None` (wait timeout) call `recovery.check_response()`.

`wait_for_follow_up_verdict` is **not** changed (human wait; see Ambiguities).

### Review loop (`pm_core/review_loop.py`)

* import `VerdictRecoveryExhausted`, `VERDICT_NO_VERDICT`;
* `_poll_for_verdict` passes recovery config (settings-driven defaults);
* `run_review_loop_sync` catches exhaustion around `_run_claude_review` /
  `_adopt_in_flight_review`, appends a `ReviewIteration` with verdict
  `NO_VERDICT`, calls `on_iteration`, breaks.

### Watcher loop (`pm_core/watcher_base.py`)

* `_poll_for_verdict` passes recovery config;
* `run_sync` catches exhaustion, records a `WatcherIteration` with
  `NO_VERDICT`, sets `latest_summary`, breaks.

### QA loop (`pm_core/qa_loop.py`)

* **finalize** — pass recovery config; catch exhaustion → return
  `"NO_VERDICT"`.
* **refiner** (`_concretize_scenario`) — pass a block outcome request;
  catch → `(None, "no refiner outcome: …")`; teach
  `_concretize_failure_label` to pass that prefix through unchanged.
* **verifier** (`_verify_single_scenario`) — pass recovery config; catch →
  `(False, "verifier produced no verdict: …", pane)`.
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
* **planner** — per-attempt `MissingOutputRecovery` with a `QA_PLAN_START/END`
  outcome request and a resume request; on exhaustion break out with
  `INPUT_REQUIRED` + `_error` (reusing the existing "plan incomplete" surface
  block). A `completed` result re-reads and accepts the plan. A stop request
  is honoured before `check_response`, so teardown never surfaces a spurious
  exhaustion. Keep `_PLANNER_TIMEOUT` as the outer deadline.

### Settings (all optional, defaulted)

| key | default | meaning |
| --- | --- | --- |
| `verdict-recovery-max-attempts` | `3` | nudges per session before exhaustion (integer; `<= 0` = off) |
| `verdict-recovery-settle-seconds` | `5` | wait for a newer idle before nudging (float) |
| `verdict-recovery-response-timeout` | `3600` | max seconds from nudge to next idle (float; `0` = off) |
| `qa-verdict-reminder-timeout` | unset | retained: overrides the settle interval for QA scenario workers |

`verdict-recovery-max-attempts` is registered in `_INT_SETTINGS`; the two
seconds-valued keys are in a new `_FLOAT_SETTINGS` table so sub-second
values (e.g. `0.5`) are accepted by `pm set`.

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
   an intentional human interaction, not a hung expected verdict.
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
  nudge would close its stdin) and `NO_VERDICT` is surfaced.
* **Grace periods** (`review 20s`, `QA 30s`) still gate verdict acceptance; a
  nudge sent before grace elapses is harmless (its turn produces a later
  event), but we only nudge on post-grace idles.
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

## Tests

* `tests/test_loop_recovery.py` (new): shared recovery unit tests —
  no-verdict nudge then success; exhaustion after N; no-output → resume
  message; output → outcome message that names no specific verdict; a
  genuine newer turn during settle defers and resets; a hook refresh of the
  same turn defers without resetting and exhausts with `no_progress`
  (including the `poll_for_verdict` and QA-tick-loop integration cases);
  a newer non-idle event (`Stop`) is not a new turn; overall timeout;
  response timeout; recovery disabled keeps legacy behaviour; `stop_check`
  during settle does not nudge; a verdict flushed during the settle window
  returns `"completed"` and is never nudged (unit, `poll_for_verdict`, and
  QA-tick-loop cases). Also holds the loop wiring tests below.
* `tests/test_loop_recovery.py` (review/watcher wiring): exhaustion →
  `NO_VERDICT`, history entry, callback fired; QA refiner label, verifier
  reason, finalize `NO_VERDICT`, scenario-worker exhaustion
  (`INPUT_REQUIRED` + reason, slot freed).
* `tests/test_qa_planner_handoff.py`: planner exhaustion surfaces
  `INPUT_REQUIRED` + error and stops planning.
* `tests/test_review_loop_terminal_state.py`: `NO_VERDICT` → `failed`.
* `tests/test_autostart_multi_target.py`: `NO_VERDICT` review loop → phase
  state `failed` in the status builder.
* Existing suite (4100+ tests) must stay green.
