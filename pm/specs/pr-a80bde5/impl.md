# pr-a80bde5 — review INPUT_REQUIRED stays visible after recovery

## Background: where the wait state lives

There is one source of truth for "the review loop is waiting on a human":
`ReviewLoopState.input_required` (`pm_core/review_loop.py`).  Every surface
reads it:

- `pm autostart status --json/text` → cmd-queue → `auto_start.collect_status_inputs`
  → `autostart_state.review_progress_input` → `_derive` (`autostart_state.py`)
  → `state=waiting, reason="review INPUT_REQUIRED (iteration N)"`,
  `review.input_required=true`.
- TUI runs view (`screens.AutoRunsScreen`) renders the same `build_status`.
- TUI tech-tree marker (`tech_tree._get_loop_marker`) → red `⏸N`, and the
  sticky log line in `review_loop_ui._poll_loop_state_inner`.
- Breadcrumb (`auto_start.save_breadcrumb` / `consume_breadcrumb`) serialises
  it across merge-triggered TUI restarts.

So if the flag is wrong in the loop's state, the CLI, the TUI and the scheduler
are all wrong together.  The fix belongs in the loop's state, not in formatting.

## Root causes found

1. **Restart during an INPUT_REQUIRED wait leaves the flag latched for good.**
   `run_review_loop_sync` sets `input_required=True` before the follow-up wait
   and clears it only when that wait returns.  On INPUT_REQUIRED the iteration's
   history entry has already been appended, so the breadcrumb saves
   `history[-1] = (N, INPUT_REQUIRED)`, `input_required=True`.  On restore,
   `adopt = state.iteration > last_done` is False, so the resumed loop
   **launches iteration N+1 with `--fresh`**: it kills the pane where the
   human question was pending, and nothing ever resets `input_required`.  Every
   later iteration then reports `review INPUT_REQUIRED (iteration N+k)` while the
   reviewer is working.  This matches the incident: the reason carried an advancing
   iteration number, and supervised autostart restarts the TUI on every sibling merge.
2. **The answered follow-up still shows as waiting.**  After the user answers in
   the pane, the reviewer may work for a long time (run tests, commit fixes)
   before it emits the follow-up verdict.  `input_required` stays True for that
   whole time, which gives a false red marker even with no restart.
3. **A repeated, genuine INPUT_REQUIRED is auto-converted to NEEDS_WORK.**
   `# Treat repeated INPUT_REQUIRED as NEEDS_WORK` makes the loop launch a
   fresh iteration, which kills the pane and drops the second question.  The loop
   also cannot tell a re-read of the *same* INPUT_REQUIRED turn (e.g. a second
   idle hook event for the unchanged turn — fake-claude refreshes idle every ~2 s)
   from a new one.  So a stale re-read also auto-answers the human.

## Requirements

R1. **New iteration owns the work.**  When the review loop launches a new
    iteration (`_run_claude_review`) or adopts an in-flight non-INPUT_REQUIRED
    iteration (`_adopt_in_flight_review`), `state.input_required` is False.
    (`review_loop.run_review_loop_sync`.)

R2. **Restart/adoption of an INPUT_REQUIRED wait.**  A resumed state whose
    `history[-1]` is `(state.iteration, INPUT_REQUIRED)` is a wait that was in
    progress at the restart.  The loop must not relaunch.  It re-enters the
    follow-up wait on the live review pane, using the saved transcript dir.  Its
    initial waiting/answered state comes from the transcript (R4), not from the
    breadcrumb flag.  If there is no live pane or no transcript, nobody can answer
    any more: clear `input_required` and continue as before, launching the next
    iteration.

R3. **Answered wait clears.**  While waiting for the follow-up, a *human prompt*
    appended to the iteration's transcript after the INPUT_REQUIRED turn means
    the native flow has resumed.  `state.input_required` becomes False and
    status reports `running` with a reason that says the follow-up is running.
    It becomes True again if the reviewer goes idle (idle_prompt hook newer than
    that prompt) without a PASS/NEEDS_WORK verdict.  That includes a genuine
    repeated INPUT_REQUIRED, or an idle turn with no verdict, which is a question
    in prose.

R4. **What counts as a human response** (`verdict_transcript`): a JSONL record
    with `"type":"user"` whose `message.content` is a string or contains a
    non-`tool_result` block, and which is not `isMeta`, `isSidechain`,
    `isCompactSummary`, or a local slash-command echo (`<command-name>`,
    `<local-command-stdout>`).  Tool results and assistant output never count, so
    arbitrary tool output is never treated as an answer.  Detection is driven by the
    transcript and hook events, with no timer.

R5. **Repeated genuine INPUT_REQUIRED stays visible.**  When an idle follow-up
    turn ends INPUT_REQUIRED *after* a human response, the loop records it
    (history/latest_verdict/on_iteration), sets `input_required=True`, re-arms
    the UI notification, and keeps waiting on the same pane.  It does not
    convert to NEEDS_WORK or relaunch.  An idle event whose latest assistant
    turn is the *same* unanswered INPUT_REQUIRED turn is ignored (stale re-read).

R6. **Status reason** (`autostart_state._derive`): while `review.running` and
    `verdict == INPUT_REQUIRED` and not `input_required`, the reason is
    `review iteration N (INPUT_REQUIRED answered; follow-up running)`,
    `state=running`.  An unresolved wait is unchanged:
    `waiting / review INPUT_REQUIRED (iteration N)`.

R7. **Agreement.**  Because the CLI, the TUI runs view, the tech-tree marker and the
    breadcrumb all read `ReviewLoopState.input_required`, R1–R5 make them agree.  No
    surface computes its own copy.

## Implicit requirements

- The follow-up wait still ends only on a hook-driven idle with a verdict in the
  latest assistant turn (`loop_shared` semantics).  Detecting a human response
  changes only the displayed wait state, never the verdict.
- The breadcrumb keeps writing `input_required`, which is used for the first paint
  before the resumed thread starts.  The resumed loop reconciles it at once (R2).
- Old breadcrumbs (`input_required=True` with `history[-1]=INPUT_REQUIRED`) take
  the same R2 path.
- Stop requests during the wait still exit cleanly with `input_required=False`.
- Pane death during the wait still ends the loop with KILLED.
- The waiter must poll the transcript at a short cadence (~2 s) so status is
  close to real time.  It reads incrementally (byte offset) so large transcripts
  are not re-read on every tick.

## Ambiguities (resolved)

- *Should the answered follow-up show as `running` or keep waiting until the next
  verdict?*  → `running`.  The task says a resolved wait must clear once the native
  flow has resumed, and a human prompt in the pane is exactly that.
- *Resume with no live pane.*  → Clear the flag and launch the next iteration
  (previous behaviour minus the stale flag).  Relaunching the *same* iteration
  would be equivalent, because the new review re-asks if the issue is still there.
- *Idle with no verdict after an answer.*  → Treat it as waiting again (R3), since the
  reviewer is idle at its prompt.  To avoid a race with an idle event emitted
  before the answer, the idle timestamp must be newer than the answer (record
  `timestamp`, else the detection time).
- *Scope vs pr-7b085a9.*  That PR covers the impl-pane `permission_prompt` /
  `PaneIdleTracker` path.  This PR does not touch `PaneIdleTracker`.
- *`pm pr auto-sequence`* reads verdicts straight from the latest iteration's
  transcript, so it already reports `running: review` once the reviewer is
  working.  Not changed.

## Edge cases

- Merge INPUT_REQUIRED (`_merge_input_required_prs`), spec-pending holds,
  stop-before-merge / wait-for-merge holds and QA INPUT_REQUIRED are separate
  paths and stay unchanged.
- Superseded loops (`_is_active_loop`) still skip runtime_state mirroring.
- A fast answer: the human prompt and the INPUT_REQUIRED/verdict turn can all
  land between two polls.  Ordering is taken from the transcript scan done just
  before each idle evaluation, so a repeated INPUT_REQUIRED after an answer is
  still seen as genuine.
- Answer and follow-up verdict both land during a TUI restart gap: Claude
  won't idle again, so the resumed waiter starts from the current idle event
  (not "newer than now") and accepts it when it is newer than the answer.
  (Added in review.)
- The back-scan only counts a human prompt found *after* the INPUT_REQUIRED
  record.  If that record can't be found, the wait stays unanswered, so the
  iteration's own review prompt is never taken as the answer.  (Added in
  review.)
- An in-flight iteration adopted at a restart that then ends INPUT_REQUIRED
  waits on the transcript it was launched under (the saved dir), not the
  resumed loop's new dir — manual loops get a fresh `manual-<token>` dir.
  (Added in review i3.)
- Transcript symlink slug mismatch: the response watch resolves the path with the
  same session-id fallback as `_read_transcript_text`.
