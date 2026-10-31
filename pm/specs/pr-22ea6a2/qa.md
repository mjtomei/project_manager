# QA Spec: pr-22ea6a2 — Resume autostart after user feedback in an existing implementation session

## Summary

The PR adds an explicit **fresh autostart** action — TUI `z a` (policy-preserving),
`z O` (wait-for-merge), `z A` (auto-merge), and the CLI `pm autostart fresh
PR_ID...` — which returns a reviewed PR (`in_review` / `qa` / `sign_off`) to
`in_progress`, retires the previous attempt's review-loop / QA / sign-off
ownership (keeping historical evidence), adopts the **existing** implementation
session without killing or relaunching it, waits for the current implementation
turn to complete, and then runs exactly one fresh review followed by the normal
QA → sign-off → merge-policy flow. Plain `autostart add` / `A` / `O` remain a
continuation from the current phase and must never rewind a PR.

*(Policy vocabulary after the 2026-10-29 master integration: master removed
`stop_before_merge`, so the single manual policy is `wait_for_merge` — the
same manual merge gate, which additionally holds the target's whole unmerged
dependency closure. `--stop-before-merge` survives only as a deprecated alias
for it. Scenarios below name `wait-for-merge`.)*

*(Requirements 35–40 and the matching edge cases were added after the
2026-10-29 `d9f2` iteration and the master integration: held-QA discard, the
old review loop's launch-lease release, the `in_progress` handoff gate, the
launch-pending reply, the mixed reset/already-waiting wording, and the
sign-off-return closure.)*

User-facing surfaces to exercise: the `pm autostart fresh` CLI (which reaches the
running TUI over the existing session command queue), the TUI key chords
(`z a` / `z O` / `z A`, plus plain `a` / `O` / `A` / `z`-prefix behaviour), the
`pm autostart status` / `pm autostart list` text and the `a` runs popup, the TUI
log line, `pm tui keys` / the in-TUI help screen, the TUI restart path, and the
on-disk state in the git-tracked `pm/project.yaml`.

## Requirements

### R1 — CLI fresh reset (from review, with a live implementation session)

1. GIVEN a PR that reached review and whose review loop was stopped (a stopped
   loop object exists) while its implementation pane is still open, and the
   implementation session is mid-turn (its reply is still streaming),
   WHEN the user runs `pm autostart fresh <pr>`,
   THEN the command prints a `fresh: <pr> (in_review → in_progress)` line, then
   the wait message ("waiting for the current implementation turn"), then the
   auto-start target line; the PR's status in `pm pr show` / `project.yaml` is
   `in_progress`; the PR is an auto-start target with the wait-for-merge
   policy; **no** review window has opened yet.

2. GIVEN the same reset has just been applied,
   WHEN the user looks at the implementation window,
   THEN it is the same window/pane as before (no second implementation window,
   the same Claude session, text typed but not submitted at the prompt is still
   there, scrollback/context intact), and the review loop that was stopped no
   longer blocks anything.

3. GIVEN a fresh attempt is waiting for a mid-turn implementation session,
   WHEN the implementation turn finishes,
   THEN exactly one review starts (one `review-<pr>` window, iteration 1), the
   PR moves to `in_review`, and no second review starts afterwards; the status
   row no longer says "waiting".

4. GIVEN the implementation turn had already finished before the user ran
   `pm autostart fresh`,
   WHEN the command returns,
   THEN the fresh review starts immediately (the CLI says the turn was complete
   and the review started) and still only one review runs.

5. GIVEN a PR in `qa` (or `sign_off`) rather than `in_review`,
   WHEN the user runs `pm autostart fresh <pr>`,
   THEN the reset is applied from that stage (the printed line names the real
   `from_status`), and the same wait → one-fresh-review behaviour follows.

### R2 — TUI chords and continuation semantics

6. GIVEN a PR in review is selected in the tech tree,
   WHEN the user presses `z a`,
   THEN the log line announces a fresh run returned to implementation after
   feedback, the PR row/status reason says it is waiting for the current
   implementation turn (with the reason), and the PR is `in_progress` with an
   auto-start target using wait-for-merge (manual merge).

7. GIVEN a PR in review is selected,
   WHEN the user presses plain `a`,
   THEN the auto-start runs popup opens and nothing about the PR changes.

8. GIVEN a PR in review is selected and is not an auto-start target,
   WHEN the user presses plain `A` (or plain `O`),
   THEN it only toggles/arms an auto-merge target (or a wait-for-merge
   sequence): the PR's status stays `in_review` and no fresh reset happens.

9. GIVEN nothing is selected,
   WHEN the user presses `z a` (or `z O` / `z A`),
   THEN the log says no PR is selected and nothing changes.

10. GIVEN a PR is already an auto-start target with the `wait_for_merge` policy,
    WHEN the user presses `z a`,
    THEN the fresh reset keeps that policy (the target is still listed as
    wait-for-merge, with its dependency-wide hold), while `z O` / `z A` force
    wait-for-merge / auto-merge on the same attempt.

11. GIVEN the user asks for keybinding help (`?` in the TUI and `pm tui keys`),
    WHEN they read it,
    THEN the fresh chords (`z a`, `z O`, `z A`) and the `autostart fresh` verb
    are documented, and plain `a` is still described as the runs popup.

### R3 — z-prefix safety

12. GIVEN the user pressed `z` and then a key that is not a z-action,
    WHEN they press plain `A` (or `O` / `a`),
    THEN the plain action runs (continuation), **not** the destructive fresh
    reset.

13. GIVEN the user pressed `z` and then waited longer than the chord window,
    WHEN they press `A` / `O` / `a`,
    THEN the plain action runs.

14. GIVEN the user presses `z` followed by `d`, `t`, `e`, `v`, `c`, `n`, `L`,
    `m`, `H`, `s`/`S`,
    THEN those chords keep their existing meanings (e.g. `z t` = QA, `z d` =
    stop-loop/open-fresh-review) — the prefix-cancellation change must not
    swallow them.

### R4 — Idempotency, repeated requests, continuation

15. GIVEN a fresh attempt is already waiting for its implementation turn,
    WHEN the user runs `pm autostart fresh <pr>` again,
    THEN the command reports "already waiting" (no second reset, the attempt is
    unchanged: no new status timestamp, same attempt number, still exactly one
    review later).

16. GIVEN a fresh attempt is waiting and the user repeats the request with an
    explicit policy (`z O` / `z A` / a CLI flag),
    THEN the same attempt is kept and only the recorded/armed merge policy is
    updated (visible in `pm autostart list` and after a TUI restart).

17. GIVEN a PR in `in_review` with a stopped review loop,
    WHEN the user runs plain `pm autostart add <pr>`,
    THEN the PR stays `in_review` (no rewind, no reset) — add is a continuation
    — and adding it again while a fresh attempt waits also changes nothing.

18. GIVEN the fresh review already started and the PR is back in `in_review`,
    WHEN the user runs `pm autostart fresh <pr>` again,
    THEN a new attempt starts (`from_status: in_review`) and one more fresh
    review runs after the next handoff.

35. GIVEN a multi-PR request where one PR is reset and another is already
    waiting for its implementation turn,
    WHEN the user runs `pm autostart fresh <reset-pr> <waiting-pr>`,
    THEN each PR is named by what actually happened to it (one "returned to
    implementation", the other "already waiting") in the command output and in
    the TUI log line — the waiting PR is never claimed to have been reset.

### R5 — Downstream flow: QA, sign-off, manual merge gate, evidence

19. GIVEN a PR that already completed review → QA → sign-off once and is
    sitting at the manual merge gate (`SIGNOFF_MERGE`, wait-for-merge, not
    merged), with the user back in its implementation session,
    WHEN the user runs `pm autostart fresh <pr>`,
    THEN the reset is applied from `sign_off`, the old approval is archived in
    the PR's `signoff_history` and invalidated, and the previous QA PASS no
    longer suppresses or advances the new run.

20. GIVEN that reset,
    WHEN the new review passes,
    THEN a fresh QA run happens (the PR enters `qa` rather than jumping to
    sign-off), then a fresh sign-off run, and the PR stops at "ready to merge"
    without merging; the old QA note, captures, sign-off report and transcripts
    are still present.

21. GIVEN the fresh reset was applied,
    WHEN the user inspects the PR's `project.yaml` record,
    THEN the previous approval appears once in `signoff_history` with a
    superseded reason (a later repeat does not duplicate it), the sign-off
    record is marked invalidated, and an open sign-off "return" episode is
    closed so nothing relaunches the implementation session with `--fresh`.

36. GIVEN the previous QA run ended `INPUT_REQUIRED` and is *held* (its status
    row says the answer belongs in the scenario worker pane, still watching for
    a follow-up),
    WHEN the user answers in the implementation session instead and runs the
    fresh request,
    THEN the held run is discarded — no held QA row or window survives, its
    resume snapshot is cleared so a TUI restart cannot resurrect it, and the
    new attempt's QA starts its own fresh run after the new review.

37. GIVEN a sign-off run returned the PR to implementation and that return is
    still awaiting its fresh implementation launch,
    WHEN the user resumes the existing pane and runs the fresh request,
    THEN the return is closed/superseded and the scheduler does not relaunch
    the implementation session with `--fresh`: the same pane, session and
    scrollback continue, with no second implementation window.

### R6 — Rejections, validation, and edge states

22. GIVEN an unknown PR id / a merged (or closed) PR / a PR that is already
    `in_progress` without a fresh attempt / a PR in an earlier stage (e.g.
    `pending`) / a PR with no workdir,
    WHEN the user runs `pm autostart fresh` on it,
    THEN the command fails with a clear, stage-specific message (unknown id,
    already merged, "already in implementation; use autostart add", "fresh
    autostart applies to in_review / qa / sign_off", "has no implementation
    workdir"), exits non-zero, and changes nothing.

23. GIVEN one valid and one invalid PR id in the same command,
    WHEN the user runs `pm autostart fresh <valid> <invalid>`,
    THEN nothing is changed for either PR (all-or-nothing) and the error names
    the invalid id.

24. GIVEN a merge of the PR is actually in flight (pending merge / merge window
    waiting for input),
    WHEN the user requests a fresh reset,
    THEN it is refused with a merge-in-progress message and the PR's status is
    untouched.

25. GIVEN no pm TUI is running (or the TUI is unreachable),
    WHEN the user runs `pm autostart fresh <pr>`,
    THEN the command reports that the auto-start owner is unavailable and exits
    non-zero; the PR is unchanged.

26. GIVEN conflicting merge-policy flags,
    WHEN the user runs the command,
    THEN it is rejected before anything is sent to the TUI.

27. GIVEN a PR whose spec generation is still awaiting approval, or a PR whose
    implementation window is missing,
    WHEN the user runs `pm autostart fresh`,
    THEN the reset is accepted, the status row explains the wait ("spec
    generation awaiting input" / "implementation window missing; relaunching"),
    and no review starts until the blocking state clears.

38. GIVEN the implementation turn has already completed but the fresh review
    launch cannot start (e.g. the project store is locked by another command),
    WHEN the user reads the command reply / the status row,
    THEN the turn is reported as complete and the review launch as
    pending/retrying — not as "waiting for the implementation turn"; the
    attempt stays armed, retries at a bounded cadence, and starts exactly one
    review once the obstacle clears.

### R7 — Restart recovery

28. GIVEN a fresh attempt is waiting and the user restarts the TUI (the target
    set is in-memory only),
    WHEN the TUI comes back,
    THEN the PR is re-added as an auto-start target (the log says the fresh
    attempt was resumed, with its merge policy), the status row still says it is
    waiting for the current implementation turn (not "turn complete"), and the
    handoff still fires exactly one review.

29. GIVEN the implementation turn completed while no TUI was running,
    WHEN the TUI restarts,
    THEN the pending attempt is resumed and starts its one fresh review without
    another user action.

30. GIVEN a waiting attempt whose target the user removed,
    WHEN they look immediately,
    THEN no review starts (the target is gone) and the PR stays in
    implementation; after a TUI restart the attempt is re-added (documented
    limitation — this is expected, not a defect).

### R8 — Concurrent and overlapping use

31. GIVEN a PR in review,
    WHEN two `pm autostart fresh` commands for it run at the same time (two
    panes) or the CLI runs while the TUI user presses `z a`,
    THEN exactly one reset is applied, the other reports "already waiting", the
    PR record is consistent (one attempt), and still only one review starts.

32. GIVEN two different PRs are reset in one command (or concurrently from two
    panes),
    WHEN both complete,
    THEN both are `in_progress` with their own fresh attempts, no update is
    lost, and unrelated targets keep their own scheduling and policies.

33. GIVEN a review loop is actively running (not stopped) for the PR,
    WHEN the user requests a fresh reset,
    THEN the old loop is stopped and its review window closed, and the fresh
    review that follows is not clobbered or frozen by the old loop's late
    completion (it reaches its verdict normally).

34. GIVEN a QA run or a sign-off run is active for the PR,
    WHEN the user requests a fresh reset,
    THEN that run is stopped/retired (its window closed, its result marked
    superseded so it neither suppresses nor advances the new attempt) and the
    new attempt's QA / sign-off run happens after the new review.

39. GIVEN a review loop is actively running with an iteration in flight (it
    holds the cross-driver review launch lease),
    WHEN the user requests a fresh reset,
    THEN the old loop's lease is released with the reset, so the successor
    review starts promptly after the handoff and reaches its own verdict — it
    does not sit waiting on the old lease, stand down as superseded, or leave
    the PR in `in_review` with no review.

40. GIVEN a fresh attempt whose review has already started (the attempt was
    consumed) and the PR later returns to `in_progress` (e.g. a sign-off bounce
    whose relaunch has not happened yet),
    WHEN the implementation transcript still shows the old completed turn,
    THEN no second review is started over that old turn: the PR waits for a new
    implementation turn.

## Setup

Use the `tui-manual-test.md` instruction: editable install with
`PYTHONPATH` pointing at the clone, a throwaway git project, `pm init --backend
local --no-import`, PRs created with `pm pr add`, and `pm session` to create the
tmux session + TUI. Drive loop sessions with **fake-claude** configs
(`pm fake-claude config set`), starting from
`tests/fixtures/fake_claude/example-config.json`.

Feature-specific fixture notes:

- **Reaching `in_review` with a stopped review loop (the #250 shape):** start
  the implementation session (`pm pr start <pr>`, fake-claude `impl` entry),
  start a review loop from the TUI (`zz d`, or `d`), let iteration 1 run, then
  stop it with `z d` ("make this iteration the last one") so the PR stays
  `in_review` with a stopped loop object and the implementation window is still
  open.
- **A mid-turn implementation session:** configure the `impl` fake with extra
  output and inter-batch delay (e.g. `{"body_lines": 40, "body_delay": 1}`) so
  the pane is visibly still producing a reply (its transcript has no completed
  turn yet) when the fresh request is made; the turn then finishes on its own
  and the handoff must fire. Appending a `type: "user"` prompt record to the
  pane's native JSONL transcript is an acceptable alternative way to represent
  "the user's feedback turn is in flight"; to finish it, append the assistant
  reply record the CLI would write.
- **An already-completed turn:** let the fake `impl` session finish printing and
  settle before requesting fresh.
- **An interrupted turn (edge case):** the record Claude Code writes when the
  user presses Esc is a `type: "user"` record whose text starts with
  `[Request interrupted by user`. Add one with a timestamp before the fresh
  request (turn counts as finished) or after it (turn keeps waiting).
- **Full downstream chain:** fake verdicts for `review` (`PASS`), the QA types
  (`qa_planning` → `QA_PLAN`, `qa_concretize` → `REFINED_STEPS`, `qa_scenario` →
  `PASS`, `qa_verification` → `VERIFIED`, `qa_finalize` → `FINALIZE_DONE`) and
  `signoff` (`SIGNOFF_MERGE`). QA scenario 0 runs on the host by default; do not
  enable container mode unless needed.
- **Stale evidence:** complete one full pass to the manual merge gate first, so
  a QA `PASS` runtime record and a `SIGNOFF_MERGE` sign-off record exist before
  the fresh request.
- **Merge in flight:** leave a merge window open and waiting for input (e.g. two
  PRs conflicting on the same lines, merge the first, then start the second) or
  otherwise have the TUI report the merge as pending.
- **Status observation:** `pm autostart status` / `pm autostart list` from a pane
  inside the test tmux session, the `a` runs popup, and `pm pr show <pr>` /
  `pm/project.yaml` (read-only) for the record.
- **Held QA run:** configure the `qa_scenario` fake with an `INPUT_REQUIRED`
  verdict so the run finalizes and is *held* watching its scenario worker pane
  (the row reads "QA INPUT_REQUIRED — answer in the scenario worker pane").  The
  fake cannot answer the follow-up itself; the point of the story is that a
  fresh reset discards the held run rather than the follow-up succeeding.
- **Open sign-off return:** configure the `signoff` fake with `SIGNOFF_IMPL` and
  let the sign-off run bounce the PR to implementation, so
  `pr["signoff_return"]` is awaiting its fresh launch.  Resume the *existing*
  implementation pane instead of letting the scheduler relaunch it.
- **Permission prompt:** a real Claude client records a `permission_prompt`
  hook event; the same event can be written through the product's hook receiver
  to model "the session is sitting at a permission prompt" while the
  implementation transcript shows the turn still running.

## Edge Cases

- Implementation turn already complete at reset time → immediate review, still
  exactly one.
- Turn in flight at reset time → waits; a previous turn's idle hook must not
  advance it.
- Interrupted (Esc) turn before the request → handoff proceeds; after the
  request → keeps waiting.
- TUI restarted while waiting (new run dir, no `impl-<pr>.jsonl` symlink) → pane
  re-adopted from its own transcript; status stays accurate.
- Old stopped review loop / old QA `PASS` / old `SIGNOFF_MERGE` → retired,
  ignored, archived; nothing blocks or pre-approves the new attempt.
- Late callback from the old review loop after the reset → must not overwrite
  the new loop's state or freeze its transcript.
- Repeated fresh requests (same command twice, key then CLI, with and without a
  policy) → idempotent, one attempt.
- Fresh while a merge is in flight → refused, nothing changed.
- Multiple PRs in one command with one invalid → nothing changed.
- Fresh with the implementation window missing → accepted; the scheduler's
  relaunch creates it; the wait then applies to that session.
- Removing the target while waiting → no review; a TUI restart re-adds the
  attempt (documented limitation).
- Transcript tail shapes that must not read as "turn complete": a streamed
  thinking block (an assistant record with `stop_reason: null` and no text,
  which the real client leaves at the tail for tens of seconds), Claude Code
  `!` shell-command records (`<bash-input>` / `<bash-stdout>` /
  `<bash-stderr>`), and a record containing an unescaped U+2028/U+2029/U+0085
  inside a string (JSONL must be split on `\n` only).  Each of these at the
  tail must keep the status at "waiting for the current implementation turn".
- An interrupt marker (`[Request interrupted by user`) whose own timestamp is
  missing or unreadable → treated as still in progress (conservative), not as
  a completed turn.
- The "implementation window missing; relaunching" reason appears only while
  the pane is actually absent: the reset and the scheduler's in-progress
  relaunch can happen in the same scheduler pass, so immediately after the
  command the row normally already reads "waiting for the current
  implementation turn".  Check the missing-window reason by closing the
  implementation window while the attempt waits, and confirm it resolves on
  the next pass once the pane is recreated.
- A live permission prompt in the implementation window at reset time keeps its
  own status reason ("permission prompt in implementation window"); it is never
  reported as a completed turn, and the handoff waits for the answered turn.
- A per-run transcript path that exists but cannot be read (or a dangling link)
  falls back to the session's own transcript found by session id; the handoff
  still fires exactly once rather than stalling on an unreadable file.
- A held `INPUT_REQUIRED` QA run at reset time is discarded (row, window and
  resume snapshot); a TUI restart before the new review completes must not
  re-adopt it.
- A multi-PR fresh call that mixes a reset PR and an already-waiting PR names
  each group accurately in the reply and the TUI log.

## Pass/Fail Criteria

**Pass** when every observable in the Requirements holds:

- `pm autostart fresh` / `z a` return a later-stage PR to `in_progress` exactly
  once, keep the same implementation pane/process (no duplicate, no relaunch,
  drafts intact), and print/log the reset plus the wait reason.
- Exactly one fresh review starts after the handoff, from a busy turn, an
  already-complete turn, and after a TUI restart.
- Stale QA/sign-off evidence never advances or suppresses the new attempt; a
  fresh QA and sign-off run happen and the flow stops at the manual merge gate
  without merging.
- Historical evidence (sign-off history, QA note, captures, report, JSONL
  transcripts) is still present; only driver-side state is retired.
- Plain `add` / `A` / `O` and plain `a` never rewind a PR; a stale `z` prefix
  never arms the destructive reset.
- Rejections are clear, non-zero, and leave the project unchanged; concurrent
  and repeated requests produce one attempt and one review.
- Unrelated targets keep running with their own policies.

**Fail** when any of: the PR is not returned to `in_progress` (or is returned
without retiring the old loop/QA/sign-off state); the implementation session is
killed, duplicated, or relaunched with `--fresh`; the review starts before the
current turn ends, more than once, or never; a stale `PASS`/approval merges or
short-circuits the new attempt; historical evidence is deleted; plain `add` /
`A` / `O` rewinds a PR; a rejected request still mutates state; concurrent
requests produce two attempts or two reviews; unrelated targets are disturbed.

## Ambiguities

Resolved:

1. **`z a` vs `z O` / `z A`** — `z a` preserves an existing target's policy
   (including `wait_for_merge`) and defaults a new target to wait-for-merge;
   `z O` / `z A` force the policy. Plain `a` keeps opening the runs popup.
2. **Fresh on an `in_progress` PR without a fresh marker** — rejected
   (`not_later_stage`, "use autostart add"), not silently treated as a reset.
3. **Fresh on a PR that already moved back to `in_review` after a fresh review
   started** — treated as a new attempt (the user had more feedback).
4. **Missing implementation window** — allowed; the existing in-progress
   relaunch creates the session, then the wait applies.
5. **Removing the target while waiting** — the attempt is not cancelled; a TUI
   restart re-adds it (documented limitation, expected behaviour).
6. **Out-of-process QA driver finishing after the reset** — could still record a
   post-reset `PASS` (documented limitation; needs a per-run id). Not counted as
   a failure of this PR unless it is the TUI-driven flow.
7. **No TUI running** — `pm autostart fresh` is a session-queue command like
   `add`/`remove`; without an owner it exits with `owner_unavailable`.
8. **Status/list are owner-mediated too** — `pm autostart status` / `pm
   autostart list` are read over the same session command queue, so with no
   running TUI they exit 2 with `owner_unavailable` instead of printing an
   offline target list.  This matches the base behaviour of `add`/`remove`
   and is not a defect of this PR; observe status from a pane inside the test
   tmux session while the TUI runs.
9. **When the missing-window reason is observable** — the fresh reset and the
   `pm pr start --background` that recreates a missing pane happen in the same
   scheduler pass, so "implementation window missing; relaunching" is only
   visible while the pane is genuinely gone (or for a few seconds when a spec
   gate delays the relaunch), never as an immediate post-command state.

No unresolved ambiguities.
