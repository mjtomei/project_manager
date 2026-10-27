# pr-8efa789 — QA verdict detection misses verdict when `/loop` wakeup adds a no-verdict turn after it

## Context

QA scenario workers are polled by `pm_core.qa_loop._poll_tmux_verdicts`. On a fresh
`idle_prompt` hook event it calls
`pm_core.verdict_transcript.extract_verdict_from_transcript(transcript_path, ALL_VERDICTS)`
(`qa_loop.py:2994`). That extractor walks the JSONL transcript backward, enters the
**latest** assistant turn, stops at the first `type: "user"` record, and returns a
verdict only if that turn contains one.

A worker that scheduled a `/loop` (dynamic `ScheduleWakeup`) turn keeps running after
it emits its verdict. The wakeup injects a new user turn; the model answers with a
"nothing left to do" postscript (no verdict). The latest assistant turn then has no
verdict, so the extractor returns `None`, the scenario stays in `pending`, and the
verdict is never recorded — `qa_status.json` shows `"verdict": ""`. The same shape
happens when a Monitor / background-task notification (`<task-notification>`) arrives
after the verdict and the model appends a postscript turn (confirmed reproduction:
#249 S71).

Other consumers of the same extractor (`loop_shared.poll_for_verdict` →
review/watcher/finalize loops, `review_loop._adopt_in_flight_review`,
`tui/review_loop_ui`, `signoff`, `pm pr show`) share the same latest-turn blind spot.

## 1. Requirements (grounded in code)

### R1 — Preserve a verdict across non-task wakeup turns

`extract_verdict_from_transcript` must continue scanning older assistant turns when
the user records between the latest turn and the candidate verdict turn are
**non-task wakeups**, and return the verdict from that older turn.

Non-task wakeup user records (transparent — the scan continues past them):

- `isMeta: true` system-injected records. These cover dynamic `/loop` ticks
  (`# Autonomous loop tick (dynamic pacing)`, `# Autonomous loop check`), usage-limit
  continuations, image/context-usage/skill-directory notices, agent messages, and
  the `[Your previous response had no visible output…]` nudges. Exception:
  `Stop hook feedback:` is a **barrier** (a hook can inject new instructions).
- Fixed-interval `/loop` / cron deliveries, whose user text starts with
  `[SCHEDULED TASK - AUTOMATED FIRING OF A CONFIGURED PROMPT]` (the Claude Code
  scheduler marker) or `# /loop tick`.
- Autonomous-loop sentinels: `<<autonomous-loop>>`, `<<autonomous-loop-dynamic>>`,
  `<<loop.md>>`, `<<loop.md-dynamic>>`.
- `<task-notification>` blocks (Monitor events / background task completion).
- A `<system-reminder>`-only record (no text outside the reminder).
- Records with no text content (attachment-only records) and pure `tool_result`
  records (they belong to the same assistant tool-use turn, not a new task).
- The QA loop's own idle reminder
  (`Reminder: your verdict must appear alone on its own line…`), which is a nudge,
  not a new task.

Task boundaries (barrier — stop scanning; return `None` if no verdict was found in
the current task scope):

- Any other `type: "user"` record with text: the initial scenario prompt, a genuine
  follow-up task, a relaunch/retry prompt, and verifier feedback
  (`Your verdict was reviewed and flagged: …`).
- `Stop hook feedback:` records.

### R2 — Extract the reason from the verdict turn

`extract_verdict_reason_from_transcript` currently reads the latest assistant turn
via `read_latest_assistant_text`. When the verdict is found in an older turn it must
read the `Reason:` line from **that** turn, otherwise a postscript turn yields no
reason (or the wrong one). Add an optional `verdicts` argument so the function uses
the same turn-finding logic as the verdict extractor; `qa_loop` passes
`ALL_VERDICTS`.

### R3 — `poll_for_verdict` returns the verdict turn's text

`loop_shared.poll_for_verdict` and `wait_for_follow_up_verdict` currently return
`read_latest_assistant_text(...) or verdict`. When the verdict is in an older turn
that returns the postscript text, so callers that re-parse the returned text
(`review_loop.parse_review_verdict`, `qa_loop._extract_flagged_reason`,
`extract_between_markers` for concretization) see no verdict/markers. Return the
text of the turn that contained the verdict instead. Same for
`review_loop._adopt_in_flight_review` (`review_loop.py:254-256`).

### R4 — Genuine new work supersedes; no stale resurrection

A verdict recorded in an older turn must not survive a task barrier. Examples:

- Verifier feedback → `None` until the worker emits a new verdict (the QA loop then
  re-verifies the new PASS normally — independent verification is not bypassed).
- A relaunch/retry prompt (a new session/transcript, or the pr-6566901 retry prompt
  re-sent into the same session) → `None`.
- A genuine new user task → `None`.

### R5 — Scope the result identity to PR / run / scenario / attempt

The verdict hit carries its identity: the assistant record `uuid` (turn id),
`timestamp`, and line index, plus the QA-side identity
`(pr_id, loop_id, scenario.index, session_id)`.

- `QALoopState.scenario_verdict_sources: dict[int, dict]` stores the source for each
  recorded verdict and is persisted in `qa_resume.json`.
- `build_resume_state` drops a restored verdict (and its reason) when its stored
  source does not match the current `(pr_id, loop_id, scenario index, session_id)`.
  A snapshot written before this change has no sources and is trusted unchanged
  (backward compatible).
- Because each relaunch/attempt gets a fresh session + transcript, an old attempt's
  verdict cannot leak into a new attempt.

### R6 — Sticky in the QA poll loop; PASS still verified

Once `_poll_tmux_verdicts` records a verdict for a scenario it is removed from
`pending`, so later wakeups cannot clear it (existing behavior). The only clearing
path remains verifier feedback. A PASS found through the older-turn path goes
through the same verification branch as a latest-turn PASS
(`qa_loop.py:3037-3058`); `verified_scenarios` semantics are unchanged.

### R7 — Real transcript / monitor replay coverage

Add tests that replay real transcript shapes:

- The scenario-44 replay: verdict `INPUT_REQUIRED`, then a dynamic `/loop` tick
  (`isMeta`), then the real postscript text ("Scenario 44 is complete; verdict
  already submitted as INPUT_REQUIRED with captures pushed. No further work to
  do — ending the loop."). Expect `INPUT_REQUIRED` and its `Reason:`.
- The #249 S71 replay: verdict `PASS`, then a `<task-notification>` Monitor event,
  then a no-verdict postscript. Expect `PASS`.
- Barrier replays: verifier feedback, retry prompt, genuine new task → `None`.
- Latest verdict after a wakeup still wins.
- `poll_for_verdict` returns the verdict turn text.
- Resume identity mismatch drops a stale verdict; matching identity keeps it.

### R8 — Coordinate with pr-6566901

pr-6566901 owns "expected verdict never produced" (deadline/retry/surface). This PR
must not implement that behavior. It only makes detection wakeup-robust. The retry
prompt it sends is a plain user message → a barrier here, so a retry supersedes an
older verdict as intended.

## 2. Implicit requirements

- **Latest-turn semantics are unchanged** when the latest turn has a verdict or when
  the newest user record is a barrier. `tests/test_verdict_transcript.py::
  test_only_latest_turn_scanned` must keep returning `None`.
- **Tool-result records are not turn boundaries.** The current raw-text scan treats
  every `type: "user"` line as a boundary; the new scan must parse user lines to tell
  `tool_result` (transparent) from a prompt (barrier).
- **FakeClaude transcripts keep working.** `fake_claude._write_fake_transcript`
  writes a plain-text user prompt then the assistant turn; the prompt is a barrier
  and the assistant turn holds the verdict → unchanged result.
- **`read_latest_assistant_text` is untouched** for the QA planner
  (`_read_planner_plan`) and other latest-turn consumers.
- **Robustness of parsing.** A user line that is not valid JSON is treated as a
  barrier (fail closed). Meta/unknown record types (`permission-mode`,
  `last-prompt`, `attachment`, `system`, `file-history-snapshot`, …) are skipped
  without terminating the scan.
- **Performance.** The scan stays single-pass over the reversed lines and stops at
  the first barrier; no repeated full-file parses.
- **Status file.** `_write_status_file` is unchanged; the fix makes the existing
  `verdict` field get populated for the masked case.
- **Reason formatting.** `Reason:` extraction keeps the "last reason line in the
  turn" behavior (`_REASON_RE`).

## 3. Ambiguities (resolved)

1. **Is a fixed-interval `/loop` delivery (which re-sends the stored task prompt) a
   "genuine new task"?** Resolved: no. Claude Code prefixes it with
   `[SCHEDULED TASK - AUTOMATED FIRING OF A CONFIGURED PROMPT]`; it is an automated
   re-fire of the same task, not live user input. Treat it as transparent so the
   verdict stays sticky, matching the PR's "not be cleared by subsequent `/loop`
   wakeups". A live user prompt has no such marker and remains a barrier.
2. **Are `isMeta` records always non-task?** Resolved: yes except `Stop hook
   feedback:`, which can carry new instructions and is treated as a barrier.
3. **Should `<task-notification>` be transparent even if it reports a failure the
   worker must fix?** Resolved: yes for verdict stickiness. If the worker acts on it
   and emits a new verdict, the latest verdict wins; if it only posts a summary, the
   completed verdict is preserved. This matches the #249 S71 confirmed reproduction.
4. **Where does "attempt" identity come from?** Resolved: the scenario's current
   `session_id` + the run's `loop_id` + `pr_id` + scenario index. Each launch/relaunch
   creates a fresh UUID session and transcript symlink
   (`claude_launcher.build_claude_shell_cmd`), so this tuple changes per attempt.

No **[UNRESOLVED]** ambiguities.

## 4. Edge cases

- **Wakeup with no assistant response yet:** transcript ends on a transparent user
  record → scan continues to the previous verdict. Correct.
- **Barrier with no assistant response yet:** transcript ends on a genuine prompt →
  `None` (do not resurrect the pre-prompt verdict).
- **Verdict in a non-final text record of a multi-step turn:** the backward scan
  crosses `tool_result` records within the turn and finds it.
- **Multiple wakeups / postscripts:** any number of transparent turns are crossed;
  the first (newest) verdict found wins.
- **New verdict after a wakeup:** the newest assistant segment is checked first, so
  it overrides the older verdict.
- **Unreadable transcript / dangling symlink:** unchanged behavior (`""` → `None`),
  including the session-id glob fallback.
- **Resume from a pre-fix snapshot:** no `scenario_verdict_sources` key → verdicts
  are trusted as before.
- **Scenario with a recorded verdict and a changed session id on resume:** the stale
  verdict/reason is dropped so the new attempt is polled; a PASS is still subject to
  verification.
- **`extract_verdict_reason_from_transcript` without a verdict in scope:** returns
  `""` (unchanged contract).

## 5. Files

- `pm_core/verdict_transcript.py` — new `VerdictHit`, `find_verdict_turn`,
  wakeup classification; backward scan in `extract_verdict_from_transcript`;
  reason extraction from the verdict turn.
- `pm_core/loop_shared.py` — `poll_for_verdict` / `wait_for_follow_up_verdict`
  return the verdict turn text.
- `pm_core/qa_loop.py` — use `find_verdict_turn` for verdict + reason; record and
  persist `scenario_verdict_sources`; validate identity on resume.
- `pm_core/review_loop.py` — adopt-in-flight path returns the verdict turn text.
- `tests/test_verdict_transcript.py` — replay + barrier + identity tests.
- `tests/test_qa_loop.py` — `TestPollVerdictsAfterLoopWakeup` drives
  `_poll_tmux_verdicts` over the scenario-44 replay.
- `tests/test_qa_resume.py` — resume identity tests (the harness only supports
  the snapshot round-trip there, not a full resume run).

## 6. Post-implementation notes (review iterations)

These extend the requirements above; they are implemented and covered by tests.

- **Compaction summaries are transparent.** Claude Code injects a "This session is
  being continued…" record with `isCompactSummary: true` as a *plain* user record
  (not `isMeta`). It is harness-generated, so the scan crosses it rather than
  treating it as a task boundary; the pre-compaction turns stay in the file behind
  it. Verified against real transcripts.
- **`VerdictHit.text` is the whole turn, not just the text after the verdict.**
  Callers parse markers (`REFINED_STEPS_*`, `FLAGGED_*`) that can sit in an earlier
  record of the same turn, so the walk in `_turn_text` also collects the assistant
  text records *preceding* the verdict. Tool-result records inside the turn are
  crossed without resetting the collected text; only a genuine non-task wakeup
  record starts a new segment (text after it belongs to a later turn).
- **The reason is read from the hit, not from a second transcript read.**
  `extract_reason_from_text(hit.text)` is used by `qa_loop`; re-scanning the
  transcript between the verdict lookup and the reason lookup could land on a newer
  wakeup turn and report a different turn's reason.
- **Loop-derived verdicts carry no source.** When verification replaces the
  worker's verdict (NEEDS_WORK after exhausted verification, or INPUT_REQUIRED when
  the window vanishes mid-verification), `scenario_verdict_sources` is cleared for
  that scenario: the verdict no longer comes from a worker turn, so the resume
  identity check must not attribute it to a (possibly stale) session.
- **A multi-`<system-reminder>` record is transparent.** Every reminder block is
  stripped, not just one wrapper at each end; only text outside the reminders can
  make the record a task boundary. An unclosed reminder tag is left in place
  (fail closed).
- **`wait_for_follow_up_verdict` only accepts a *new* verdict (review i3).** Its
  callers (review/watcher INPUT_REQUIRED waits) want the worker's next turn, not the
  verdict that prompted the call. Because the task-scoped scan crosses non-task
  wakeups, a `/loop` tick or Monitor postscript arriving before the human answers
  would otherwise re-deliver the stale INPUT_REQUIRED and the caller would coerce it
  to NEEDS_WORK. The waiter snapshots the current verdict's `line_index` at call
  start and ignores hits at or before it; the transcript only grows, so a genuinely
  new verdict always sits later. `poll_for_verdict` keeps the unguarded scan because
  it must return a verdict emitted just before it is called.
- **A caller that prompts the pane passes the baseline itself (review i4).** The
  call-time snapshot is wrong for `qa_loop`'s re-verification: it sends the
  follow-up prompt into the verifier pane and only then waits (~2 s of send/settle),
  so a fast answer is already in the transcript when the waiter scans and the waiter
  would reject it as "the verdict that prompted the call" and block for a second
  verdict that never comes. `wait_for_follow_up_verdict` therefore takes an optional
  `baseline_line`; `_verify_single_scenario` snapshots `find_verdict_turn(...)`'s
  `line_index` *before* `send_keys` and passes it. Callers that wait on a human
  answering a question the pane already asked (review/watcher) omit it and keep the
  call-time snapshot.
- **The waiter checks the transcript before blocking (review 5e61 i2).** The i4
  baseline makes an answer that landed during the send/settle *acceptable*, but not
  *observed*: that answer's own `idle_prompt` fired before `wait_for_follow_up_verdict`
  set `hook_baseline`, and `hook_events.wait_for_event` only returns events with
  `timestamp > newer_than`, so the loop would never be woken by it and blocked until
  `stop_check`/pane death. The waiter now scans once *before* entering the event
  loop with the same `line_index > baseline_line` guard, which is a no-op for the
  human-answer callers (their baseline is the newest verdict at call time) and
  closes the i4 gap for `qa_loop`'s re-verification.
- **Only visible text can carry a verdict (review 5e61 i1).** The task-scoped scan
  reaches records the latest-turn scan never entered, and the verdict pattern is
  matched against the raw JSONL bytes — so a keyword that appears only inside a
  thinking block or a `tool_use` input (a `Grep` pattern for `INPUT_REQUIRED`, a
  file the agent wrote) was reported as the worker's verdict. A hit now requires
  the assistant record to carry `text` content *and* the keyword to occupy a whole
  line of that parsed text (`_text_line_is_verdict`); markdown emphasis/code
  markers around it are still tolerated. Corpus check over ~12.6k local
  transcripts: 21 such false positives before the gate, none after, and
  `VerdictHit.text` now always contains the verdict, so `poll_for_verdict`'s
  returned text cannot disagree with the detected verdict.
