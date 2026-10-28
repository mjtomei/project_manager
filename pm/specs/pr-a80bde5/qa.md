# pr-a80bde5 — QA spec: review INPUT_REQUIRED stays visible after recovery

Source of truth for the behaviour under test: `ReviewLoopState.input_required`
(`pm_core/review_loop.py`). Every user-visible surface reads it:

- `pm autostart status` (text) and `pm autostart status --json`
  (`pm.autostart.status/1`: `state`, `reason`, `review.input_required`,
  `review.follow_up`, `review.iteration`, `review.verdict`).
- The TUI runs popup (`a`) — same `build_status` payload.
- The tech-tree marker: red `⏸N` while waiting for a human, cyan `⟳N` while
  the loop is working, red `⏹N` when a stop is requested.
- The TUI log line `⏸ INPUT_REQUIRED for <pr>: interact with Claude in the
  review pane` (shown once per question).
- The breadcrumb (`~/.pm/breadcrumb.json`) that carries loop state across a
  merge-triggered TUI restart.

The PR fixes three defects: (1) a restart during an INPUT_REQUIRED wait
relaunched the next iteration with `--fresh` (killing the question pane) and
never cleared `input_required`, so later active iterations still reported
waiting; (2) an answered follow-up still displayed as waiting while Claude
worked; (3) a repeated genuine INPUT_REQUIRED was auto-converted to
NEEDS_WORK (and a stale re-read of the same turn was treated as a new
question / auto-answered the human).

The sign-off rework added a fourth, related guarantee: the follow-up verdict
is read task-scoped (`find_verdict_turn`), so a non-task wakeup turn landing
after the verdict (e.g. a `/loop` tick) can neither hide the verdict nor be
parsed as one; and a `type:"user"` record with no real human text (empty,
whitespace-only, harness-injected) never counts as the answer that clears a
wait.

Review 484e i1 added a fifth: the waiter reads the transcript once when the
wait starts, so a follow-up verdict that already landed — an answer and its
verdict during a TUI restart gap, or a follow-up `idle_prompt` event that was
lost or overwritten — resolves the wait without another hook event. Without
it a resumed loop can sit on "follow-up running" forever. The wait-start read
must never treat the INPUT_REQUIRED question itself as the follow-up.

## Setup (shared by all scenarios)

The tester works in a throwaway project inside the workdir (see
`tui-manual-test.md`):

1. Create a test project, `git init`, `pm init --backend local --no-import`.
2. Add at least one PR, start it (`pm pr start <id>`) so it has a workdir, and
   move it to `in_review` (`pm pr review <id> --no-window`, or the TUI flow).
3. Start the pm session (`pm session`) and add the PR as an auto-start target
   (`pm autostart add <id>`) so the TUI scheduler launches the review loop.
4. Configure the review session's Claude stand-in with
   `pm fake-claude config set` so the review pane reaches deterministic
   verdicts. The bundled fake emits one verdict per launch and then holds the
   pane open; to exercise the *follow-up* half of this PR (the human answer
   and the follow-up turn in the same pane) extend it, or use a small
   interactive stand-in modelled on it, that:
   - writes a Claude-format JSONL transcript for the pane's session id and
     emits `idle_prompt` hook events (the fake already does both), and
   - on a line typed into the pane, appends a `type:"user"` record for that
     line and then an assistant turn carrying the scripted follow-up verdict
     (and refreshes `idle_prompt`).

   This is the same shape the PR's own live captures used; it lets the tester
   act exactly as a user would — answer in the review pane — without a real
   model. Verdicts must be driven this way (transcript + hook), never by
   scraping or editing pane text.

Cross-cutting: after each action, observe the CLI (`pm autostart status` and
`--json`) and the TUI (runs popup, tech-tree marker, log line). Allow a couple
of seconds for the ~2 s transcript poll; do not rely on a fixed sleep as the
only evidence — assert on the reported state/reason, then re-read.

## Requirements

R1. **Genuine wait is visible.**
GIVEN an in_review PR whose review loop just recorded INPUT_REQUIRED and the
human has not answered.
WHEN the user runs `pm autostart status` and opens the TUI runs view.
THEN the PR shows `state=waiting`, reason `review INPUT_REQUIRED (iteration N)`,
`review.input_required=true`, `review.follow_up=false`; the tech-tree marker is
red `⏸N`; the TUI log shows the "interact with Claude in the review pane"
notice once; and the review pane still shows the question (it was not killed).

R2. **Answered wait clears while Claude works.**
GIVEN the same wait.
WHEN the user types an answer in the review pane and Claude starts working on
the follow-up without having emitted a new verdict yet.
THEN within a few seconds status shows `state=running`, reason
`review iteration N (INPUT_REQUIRED answered; follow-up running)`,
`review.input_required=false`, `review.follow_up=true`; the tech-tree marker is
the working `⟳N`, not red `⏸N`; no new review iteration was launched and the
pane was not restarted.

R3. **A later active iteration never reports the old wait (the reported bug).**
GIVEN the answered follow-up.
WHEN the follow-up ends NEEDS_WORK and iteration N+1 launches and is working.
THEN status shows `state=running`, reason `review iteration N+1 (last NEEDS_WORK)`,
`review.input_required=false`, `review.follow_up=false`, and no surface shows
`waiting` or an INPUT_REQUIRED reason for that PR; the tech-tree marker is cyan
`⟳N+1`. (Same expectation when the follow-up ends PASS and the loop completes
normally: no INPUT_REQUIRED anywhere.)

R4. **A repeated genuine INPUT_REQUIRED stays visible.**
GIVEN an answered follow-up.
WHEN Claude's follow-up turn itself ends INPUT_REQUIRED (a second real question).
THEN status returns to `state=waiting`, reason `review INPUT_REQUIRED (iteration N)`
(same iteration), `review.input_required=true`; the TUI notification is shown
again; the loop keeps waiting on the same pane (no relaunch, no `--fresh`, no
conversion to NEEDS_WORK), and the pane still shows the second question.

R5. **Stale/repeated idle and non-human records never change the wait.**
GIVEN a wait (answered or unanswered) in the review pane.
WHEN the stand-in refreshes `idle_prompt` for the turn already handled, or the
transcript gains harness records that are `type:"user"` but not human input
(system-reminder-only, `<task-notification>`, `/loop` or autonomous-loop tick,
scheduled-prompt firing, `[Request interrupted by user…]`, qa_loop verdict
nudge), or tool output contains words like `PASS`, `yes`, `INPUT_REQUIRED`.
THEN the reported state does not flip: an unanswered question stays `waiting`,
an answered one stays `running (… follow-up running)`, and the question is
recorded exactly once (no repeated notification, no repeated on-iteration
record, no busy loop). An empty/whitespace-only user record (the user pressed
Enter on an empty prompt) is not an answer either.

R5b. **The follow-up verdict survives a later non-task turn.**
GIVEN an answered follow-up whose verdict turn is PASS or NEEDS_WORK.
WHEN a non-task wakeup turn lands after it (a `/loop` or autonomous-loop tick,
a Monitor notification, a scheduled prompt) whose reply carries no verdict.
THEN the recorded verdict is still the one from the verdict turn: a PASS
follow-up stops the loop with verdict PASS (it does not relaunch with
NEEDS_WORK), and a NEEDS_WORK follow-up advances to the next iteration. The
question being answered never comes back as its own follow-up.

R6. **Prose question after an answer waits again.**
GIVEN an answered follow-up.
WHEN Claude goes idle after that answer without emitting a verdict (it asked
something in prose).
THEN status returns to `waiting` with the INPUT_REQUIRED reason, and answering
the prose question clears it again.

R7. **Restart/adoption during the wait keeps the question.**
GIVEN a review loop waiting on INPUT_REQUIRED and auto-start active.
WHEN the TUI is restarted with the merge-restart breadcrumb (`pm tui restart
--breadcrumb`, the same path a sibling merge triggers).
THEN the resumed loop re-adopts the live review pane instead of launching a new
iteration: the pane is not killed, the question is still on screen, status
still shows `waiting / review INPUT_REQUIRED (iteration N)`, and the iteration
number does not advance.

R8. **Answer/follow-up across the restart gap are not lost.**
GIVEN the same restart.
WHEN the user answers after the restart, or the answer and the follow-up
verdict both land while the TUI is restarting.
THEN the resumed loop records the follow-up verdict and continues (next
iteration or completion); status reflects `running` with the correct reason;
nothing is lost or re-recorded.

R9. **No phantom wait when nobody can answer.**
GIVEN a restored wait whose review pane (or its transcript/session id) is gone,
or a loop that exits while waiting (stop requested, pane killed, unexpected
error).
WHEN status is read afterwards.
THEN the PR does not report `waiting / review INPUT_REQUIRED`: a stop shows the
loop stopped/paused, a dead pane shows `failed / review loop ended KILLED`, and
`review.input_required=false` in every case.

R10. **Old/latched breadcrumb state is reconciled.**
GIVEN a breadcrumb (or older saved state) with `input_required=true` and a
finished history (no pending INPUT_REQUIRED iteration).
WHEN the TUI restores and resumes the loop.
THEN the stale flag is cleared immediately and status never shows a wait nobody
asked for.

R11. **Unrelated holds are preserved (no auto-answering user decisions).**
GIVEN each of: a PR with a spec awaiting human input (`spec_pending`), a QA run
that ended INPUT_REQUIRED, and a signed-off PR held for manual merge.
WHEN status is read (before and after the review fix's paths run).
THEN each keeps its own unchanged reason/state (`spec generation awaiting
input`, `last QA run ended INPUT_REQUIRED (see QA note); press t / z t to
re-run QA`, `signed off (fresh SIGNOFF_MERGE); waiting for manual merge
(held by …) — press g`), and none is cleared or auto-answered by the
review-loop logic.

*Merge-window INPUT_REQUIRED is out of local-backend QA scope:* a local-backend
project never opens a `merge-<pr>` window (the window exists only for a failed
post-merge main-repo update on a remote backend), so `merge INPUT_REQUIRED —
answer in merge window` cannot be driven here. Covered by code inspection and
unit tests, not a QA scenario.

R12. **A verdict already in the transcript resolves the resumed wait.**
GIVEN a review loop waiting on INPUT_REQUIRED whose answer and follow-up
verdict (PASS or NEEDS_WORK) landed while the TUI was restarting, or whose
follow-up `idle_prompt` hook event was lost or overwritten by another event.
WHEN the resumed loop enters (or re-enters) the follow-up wait.
THEN it reads the transcript at wait start and returns the verdict turn's
verdict without waiting for another idle event: a NEEDS_WORK follow-up
launches iteration N+1, a PASS follow-up completes the loop, and status never
sits on `running / review iteration N (INPUT_REQUIRED answered; follow-up
running)` after the verdict has already landed. The wait-start read must not
return the INPUT_REQUIRED question itself as the follow-up (a genuine
unanswered wait stays `waiting`), and a non-task wakeup turn after the verdict
must not change which verdict is returned (→ R5b).

## Edge cases

E1. **Two surfaces queried at once agree.** While a transition is happening,
repeated `pm autostart status --json` (from two panes) and the TUI runs popup
must agree: `review.input_required` matches the displayed `state`/`reason`, and
text and JSON never disagree (no surface showing waiting while another shows
running, or vice versa).

E2. **Fast answer.** The human answer and the follow-up verdict land between
two transcript polls; ordering still comes from the transcript, so a genuine
second INPUT_REQUIRED after the answer is not mistaken for a stale re-read, and
a stale idle for the answered turn is not mistaken for a new question.

E3. **Adopted in-flight iteration.** At a restart the counter was bumped but the
iteration had not recorded a verdict; that in-flight iteration then ends
INPUT_REQUIRED and its follow-up must be read from the transcript it was
launched under (a manual loop may resume with a different transcript dir).

E4. **Stop during the wait.** Stopping the loop while it waits ends it cleanly;
the marker becomes `⏹N` then the finished-verdict marker, never a red `⏸N`.

E5. **Pane killed during the wait.** Closing the review window ends the loop
`KILLED`; status shows `failed`, not `waiting`.

E6. **Repeated answers.** Several human prompts in a row (no assistant turn
between) count as answers; the wait stays cleared and does not re-arm.

E7. **Notification re-arm.** After a second genuine question the TUI notice is
shown again (once), and after it is answered no further notice appears for that
turn. Note: the TUI drops a log message identical to the previous recorded one
(`pm_core/tui/app.py::_record_log_message`), so the *debug log* may show the
notice once even though `log_message` ran once per question — judge re-arm from
the visible notice/frame captures, not from a single debug-log line.

E8. **Empty or non-human user records.** An empty, null, whitespace-only or
tool_result `type:"user"` record arriving while the loop waits does not clear
`input_required` and does not become the follow-up. A pasted image (a real
non-text content block) still counts as a human answer.

E9. **Verdict turn vs transcript tail.** A `/loop` (or other non-task) wakeup
turn after the follow-up verdict must not change which verdict is recorded;
the wait state must also not re-arm for it.

E10. **Verdict at wait start with a lost hook event.** The `idle_prompt` event
is a single file per session, overwritten by each hook event. A restart can
leave it holding no follow-up idle (or another event type) while the answer
and verdict are already in the transcript. The resumed wait must resolve from
the transcript alone, and a still-unanswered wait must still wait rather than
being mistaken for an answered/completed one.

## Pass/Fail criteria

- PASS when every Then clause above is observed on the stated surfaces, with
  the JSON `review.input_required`/`review.follow_up`/`state`/`reason` matching
  the text rendering and the TUI, and the original bug (R3) does not reproduce.
- FAIL on any stale `waiting`/INPUT_REQUIRED while the reviewer is working, any
  cleared wait that nobody answered, any relaunch/`--fresh` that kills a
  pending question, any auto-conversion of a repeated INPUT_REQUIRED, any
  surface disagreement, any unrelated hold cleared, or a resumed wait that
  stays on `follow-up running` after its verdict is already in the transcript.
- Also FAIL if a PASS follow-up followed by a non-task wakeup turn (e.g. a
  `/loop` tick) is recorded as NEEDS_WORK or relaunches an iteration (R5b).
- The reproduction tests from the diff
  (`tests/test_review_input_required_state.py`: `TestLiveFlow`,
  `TestRestartAdoption` — including
  `test_follow_up_verdict_resolves_without_a_hook_event`,
  `test_follow_up_pass_survives_a_loop_tick_turn`,
  `test_record_with_no_text_is_not_an_answer`; `tests/test_review_loop.py::
  TestInputRequired`) may be run as supporting evidence, but the primary
  evidence is the user-facing behaviour above. The PR was reworked on top of
  master at review i3 / 3bf4 i1 and the waiter changed again at review 484e
  i1, so run these against the current HEAD.

## Ambiguities

Resolved:

- *Answered follow-up = `running`, not `waiting`.* The task says a resolved
  wait must clear once the native flow resumed; a human prompt in the pane is
  that moment. → R2.
- *A follow-up idle with no verdict after an answer is a question.* → R6.
- *Restart with no live pane/transcript* → nobody can answer; clear the flag
  and continue with the next iteration rather than reporting a wait. → R9.
- *Scope vs pr-7b085a9* (impl-pane `permission_prompt` / `PaneIdleTracker`):
  out of scope; not exercised here except as a regression that impl-pane
  statuses are unchanged.
- *Timer vs transcript:* the ~2 s poll only bounds latency; detection is
  transcript + hook driven. Tests assert state, not elapsed time.
- *Merge-window INPUT_REQUIRED is not drivable on a local backend* (no
  `merge-<pr>` window exists locally) → dropped from R11's drivable set; see
  the note under R11. (S6 refinement, 2026-10-28.)
- *A follow-up verdict is read task-scoped* (integration rework): a later
  `/loop`/non-task turn must not be parsed as the follow-up → R5b/E9.
- *An empty user record is not an answer* (3bf4 i1) → E8.
- *The waiter reads the transcript when the wait starts* (review 484e i1),
  not only on an `idle_prompt` event, so a restart that loses the event does
  not strand the loop → R12/E10.

No **[UNRESOLVED]** ambiguities.
