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
record, no busy loop).

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
that ended INPUT_REQUIRED, a merge window INPUT_REQUIRED, and a signed-off PR
held for manual merge.
WHEN status is read (before and after the review fix's paths run).
THEN each keeps its own unchanged reason/state (`spec generation awaiting
input`, `QA INPUT_REQUIRED — answer in QA window`, `merge INPUT_REQUIRED —
answer in merge window`, `waiting for manual merge … press g`), and none is
cleared or auto-answered by the review-loop logic.

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
turn.

## Pass/Fail criteria

- PASS when every Then clause above is observed on the stated surfaces, with
  the JSON `review.input_required`/`review.follow_up`/`state`/`reason` matching
  the text rendering and the TUI, and the original bug (R3) does not reproduce.
- FAIL on any stale `waiting`/INPUT_REQUIRED while the reviewer is working, any
  cleared wait that nobody answered, any relaunch/`--fresh` that kills a
  pending question, any auto-conversion of a repeated INPUT_REQUIRED, any
  surface disagreement, or any unrelated hold cleared.
- The reproduction tests from the diff
  (`tests/test_review_input_required_state.py`: `TestLiveFlow`,
  `TestRestartAdoption`; `tests/test_review_loop.py::TestInputRequired`) may be
  run as supporting evidence, but the primary evidence is the user-facing
  behaviour above.

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

No **[UNRESOLVED]** ambiguities.
