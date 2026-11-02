# QA Spec: pr-8efa789 — QA verdict detection misses the verdict when a `/loop` wakeup adds a no-verdict turn

## Scope (what actually shipped)

Verdict detection moved from "latest assistant turn only" to "the current
task scope", so a worker that emits a terminal verdict and is then woken by
a `/loop` tick or a Monitor `<task-notification>` — and answers with a
"nothing left to do" postscript — keeps its verdict. The user-visible
surfaces this touches:

1. **QA scenario verdicts** (`pm_core/qa_loop.py::_poll_tmux_verdicts` →
   `pm_core/verdict_transcript.find_verdict_turn`). The scenario's
   `verdict` in `qa_status.json` (the QA status dashboard, the TUI QA pane)
   and its `verdict_reason` are now taken from the *verdict turn*, not the
   transcript tail.
2. **Task-scoped scanning rules** (`pm_core/verdict_transcript.py`).
   Backward scan crosses non-task records (`isMeta` `/loop` ticks,
   `[SCHEDULED TASK - AUTOMATED FIRING …]` deliveries, `<task-notification>`,
   reminder-only records, tool results, compaction summaries, user-Esc
   `[Request interrupted by user…]`) and stops at a genuine task boundary
   (initial prompt, retry prompt, verifier feedback, `Stop hook feedback:`,
   any other user text). Only *visible* assistant text can carry a verdict —
   a keyword inside a thinking block or a `tool_use` input (a `grep`
   pattern, a file the agent wrote) is not a verdict.
3. **Verdict-turn text for downstream parsers** (`pm_core/loop_shared.py`,
   `pm_core/review_loop.py`). `poll_for_verdict`, the review loop's
   adopt-in-flight path, and the QA verifier now return the text of the
   turn that carried the verdict, so marker parsing (`REFINED_STEPS_*`,
   `FLAGGED_*`) and `Reason:` lines survive a postscript.
4. **Follow-up waiter baselines** (`wait_for_follow_up_verdict`). The
   waiter ignores the verdict that prompted the call (a `/loop` tick
   arriving while a human answers must not re-deliver the stale
   INPUT_REQUIRED and end the wait as NEEDS_WORK), accepts a caller-supplied
   baseline snapshotted before the caller prompts the pane (QA
   re-verification), and checks the transcript once before blocking so an
   answer that landed during the send/settle window is observed.
5. **Resume identity** (`qa_loop.py::_drop_foreign_verdicts`,
   `scenario_verdict_sources` in `qa_resume.json`). A restored verdict is
   trusted only when its recorded (pr_id, loop_id, scenario, session_id)
   still matches the current attempt; loop-derived verdicts (verification
   NEEDS_WORK, window-gone INPUT_REQUIRED) carry no source; snapshots
   written before sources existed stay trusted.
6. **Other consumers of the same extractor**: the TUI's review/merge
   verdict mirror (`tui/review_loop_ui.py`), the sign-off router
   (`signoff.signoff_transcript_verdict`), and `pm pr show`/auto-sequence
   (`cli/pr.py::_check_review_verdict`). These inherit the fix without
   their own code change.
7. **QA finalize verdict** (`_run_qa_finalize_pane` →
   `poll_for_verdict`), which shares the extractor and the same
   30 s grace window.

## Requirements (Given / When / Then)

### R1 — QA scenario verdict survives a dynamic `/loop` wakeup
**Given** a QA run whose scenario worker emitted `INPUT_REQUIRED` on its own
line and then a dynamic `/loop` wakeup injected a tick and the worker
answered with a no-verdict postscript ("Scenario complete; verdict already
submitted … No further work to do — ending the loop") plus a stale task
list,
**When** the QA poller reads the worker's transcript for the first time
after the wakeup,
**Then** `qa_status.json` (and the QA status dashboard / TUI QA pane) shows
that scenario as `INPUT_REQUIRED`, not blank/pending.

### R2 — The reason comes from the verdict turn, not the postscript
**Given** the verdict turn contains `Reason: <sentence>` immediately before
the verdict and the postscript turn contains no reason (or a different
one),
**When** the scenario verdict is recorded,
**Then** the scenario's `verdict_reason` in `qa_status.json` and on the QA
status dashboard is the verdict turn's sentence.

### R3 — A Monitor / background-task postscript does not hide a PASS
**Given** a scenario worker that emitted `PASS`, then received a
`<task-notification>` Monitor event and appended a no-verdict summary
(the #249 S71 shape),
**When** the poller reads the transcript,
**Then** the scenario is `PASS` and goes through the normal verification
path — it is not left pending.

### R4 — A genuine new task supersedes the old verdict
**Given** a scenario worker that emitted a verdict and then received a real
new user task (a plain follow-up instruction, not a `/loop` tick) and
answered it with a different verdict,
**When** the poller reads the transcript for the first time,
**Then** the recorded verdict is the new task's verdict — the earlier
verdict is not resurrected.

### R5 — Only visible text can be a verdict
**Given** a scenario whose real verdict turn says `INPUT_REQUIRED`, followed
by a `/loop` wakeup whose postscript turn mentions `PASS` only inside a
thinking block or a tool call (e.g. a `grep` for the keyword) and whose
visible text has no verdict,
**When** the poller reads the transcript,
**Then** the scenario is `INPUT_REQUIRED` — no PASS is fabricated and no
verification is spawned for it.

### R6 — A user interruption is not a new task
**Given** a scenario worker that emitted `PASS` and the user then pressed
Esc (Claude Code writes `[Request interrupted by user]` / `… for tool
use`),
**When** the poller reads the transcript,
**Then** `PASS` is still recorded (the interruption record is transparent).

### R7 — Review loop verdict survives a wakeup postscript
**Given** a review-loop iteration whose worker emitted `PASS` and then a
`/loop` wakeup appended a no-verdict postscript before the loop's verdict
grace expired,
**When** the loop polls the review transcript,
**Then** the loop records `PASS` (log: "Review loop done … PASS"), the PR is
not bounced, and anything the loop parses from the verdict turn (markers,
reason) is intact.

### R8 — A wakeup during the INPUT_REQUIRED wait does not end the wait
**Given** a review loop whose worker emitted `INPUT_REQUIRED` and the loop is
waiting for the human's answer in the review pane,
**When** a `/loop` tick arrives (no new verdict) while the loop waits and
the human then answers with a verdict (`PASS`),
**Then** the tick alone does not end the wait and does not coerce the
verdict to `NEEDS_WORK`; the loop adopts the later `PASS` and finishes
`PASS`.

### R9 — PASS found across a wakeup is still independently verified
**Given** a QA scenario whose `PASS` is only found by scanning back across a
wakeup postscript,
**When** the QA loop records it,
**Then** the verifier pane still runs (the fix must not bypass
verification), and the scenario shows `PASS (verified)` once the verifier
returns `VERIFIED`.

### R10 — QA finalize verdict survives a wakeup postscript
**Given** the QA run reached its finalize pane, which emitted
`FINALIZE_DONE`, and a `/loop` wakeup appended a no-verdict postscript
before the finalize poll's grace expired,
**When** the run completes,
**Then** the QA completion message reports the finalize verdict
(`[finalize: FINALIZE_DONE]`) instead of finishing with no finalize result.

### R11 — A TUI restart keeps this attempt's verdicts and re-verifies nothing
**Given** a QA run in progress whose snapshot (`qa_resume.json`) records a
verified `PASS` for one scenario (with its source identity) and is still
waiting on another,
**When** the user restarts the TUI (`Ctrl+R`) and the restarted TUI resumes
the run,
**Then** the TUI logs that it is resuming QA, the recorded `PASS` (and its
reason) is preserved, its verification is not repeated, and the run
completes with the same overall verdict.

### R12 — A verdict from a superseded attempt is not trusted
**Given** a resume snapshot whose recorded verdict source no longer matches
the scenario's current attempt (different session id, loop id, or scenario
index),
**When** the state is rebuilt on resume,
**Then** that verdict, its reason, and its "verified" flag are dropped and
the scenario is polled from scratch — a historical `PASS` is never
resurrected and its verification is not inherited.

### R13 — Legacy snapshots stay trusted
**Given** a `qa_resume.json` written before `scenario_verdict_sources`
existed,
**When** the state is rebuilt,
**Then** its verdicts and verified flags are kept as before.

### R14 — The shipped reproduction tests pass
**Given** a checkout of the PR branch with dev dependencies installed,
**When** the shipped verdict/transcript regression tests are run,
**Then** the scenario-44 `/loop` replay yields `INPUT_REQUIRED` with its
`Reason:` and turn identity, the S71 Monitor replay yields `PASS`, the
barrier replays (verifier feedback, retry, new task) yield no verdict, the
follow-up-baseline tests pass, and the resume-identity tests pass.

## Setup (cross-cutting)

- Install the PR clone into a venv (`python3 -m venv`, `pip install -e .`)
  and make sure `PYTHONPATH` points at the clone, not `/opt/pm-src`
  (`pm which` confirms).
- Create a throwaway project (`pm init --backend local --no-import`), add at
  least one PR, and start the pm session (`pm session`).
- Give the PR a real workdir/branch (`pm pr start`) and move it to the
  state the scenario needs (`in_review` for the review loop, `qa` for a QA
  run) through pm commands / TUI keys — not by hand-editing
  `project.yaml`.
- Configure the bundled fake Claude for the session under test:
  `pm fake-claude config set --file <config>.json` (start from
  `tests/fixtures/fake_claude/example-config.json`). QA chain types:
  `qa_planning` → `QA_PLAN` (body lists the scenarios, one of which is a
  control), `qa_concretize` → `REFINED_STEPS`, `qa_scenario` → the verdict
  each scenario should emit, `qa_verification` → `VERIFIED`,
  `qa_finalize` → `FINALIZE_DONE`. Review loop: `review` → the verdict(s).
- **Reproducing the wakeup shape without a real model.** The scenario
  workers/loops are driven by fake-claude, which writes a realistic Claude
  Code JSONL transcript and keeps its pane open, re-emitting the
  `idle_prompt` hook every ~2 s. To reproduce "the runtime woke the worker
  after its verdict", append real Claude Code record shapes to that
  worker's transcript (the QA run's `qa_resume.json` names each
  `transcript_path`; the files are `~/.pm/workdirs/qa/<pr>-*/transcript-s<n>.jsonl`
  symlinks; review iterations are `review-<pr>-i<n>.jsonl` under the
  session's transcripts dir; the QA finalize transcript path is printed in
  the pm log):
  - a dynamic `/loop` tick: `{"type":"user","isMeta":true,"message":{…}}`
    whose text starts `# Autonomous loop tick …`, or a fixed-interval
    delivery starting `[SCHEDULED TASK - AUTOMATED FIRING OF A CONFIGURED
    PROMPT]`;
  - a Monitor event: a user record whose text starts `<task-notification>`;
  - the postscript: an assistant record with text content and no verdict
    line (optionally a thinking block / tool_use carrying the keyword);
  - a genuine new task: a plain user record with instruction text.
  Append them **before the verdict grace expires** (QA scenario/finalize
  and review loops all wait 30 s / 20 s before the first verdict scan), so
  the first scan sees the postscript. That grace is what makes the repro
  deterministic.
- Save captures under the per-PR captures directory named in the worker
  prompt (artifact recipes explain the layout).

## Edge Cases / Failure Modes to Probe

- Verdict keyword only in a thinking block or a `tool_use` input (a `grep`
  pattern, a file the agent wrote) — must not be a verdict.
- Wakeup record with no assistant answer yet — the earlier verdict stands.
- New-task record with no answer yet — no verdict (do not resurrect).
- Several wakeups/postscripts in a row — the first (newest) verdict found
  wins, and any number of transparent turns are crossed.
- A newer verdict after a wakeup — it overrides the older one.
- Verifier feedback / retry prompt after a verdict — supersedes it, and a
  new `PASS` still gets verified.
- `[Request interrupted by user]` and compaction-summary records — no
  verdict lost, and a follow-up instruction after them is still a barrier.
- Missing / unreadable / dangling-symlink transcript — unchanged (no
  verdict, no crash).
- Resume snapshot with a mismatched source vs. a matching one vs. a legacy
  one.
- Concurrent actors on the same transcript: the QA poller, the QA status
  dashboard (2 s refresh of `qa_status.json`) and the TUI (loop status,
  resume scan) while wakeup records are appended — the recorded verdict and
  reason must be consistent and must not flap.
- Concurrent snapshot writers: the QA driver thread refreshing
  `qa_resume.json` every poll while a restarted TUI scans for snapshots to
  resume — the resume must not adopt a half-written snapshot or double-run
  the same scenario.

## Pass/Fail Criteria

A scenario passes when every Then clause is observable in the captured
evidence (status dashboard / `qa_status.json`, TUI log and panes, CLI
output, recorded transcript). A scenario fails when the wakeup postscript
still hides a verdict, a stale verdict is resurrected, a hidden keyword is
reported as a verdict, the reason comes from the wrong turn, a follow-up
wait ends on the prompting verdict, a matching verdict is lost across a TUI
restart, verification is skipped or duplicated, or the shipped reproduction
tests fail for a reason other than the documented pre-existing environment
failures (`test_hook_events` standalone receiver; `test_markdown_render`
missing markdown dependency).

## Ambiguities (resolved)

1. **How is a `/loop` wakeup reproduced in a container without a real
   model?** Resolved: drive the loop with fake-claude and append the real
   Claude Code record shapes to the worker's JSONL transcript inside the
   verdict grace window. The transcript is the production input the fix
   reads, so this exercises the real detection path; it does not import or
   call pm internals.
2. **Can the resume identity-drop path be reached by plain user actions?**
   Resolved: not deterministically — a verdict-recorded scenario is removed
   from `pending`, so a normal restart keeps a matching source. The
   user-visible restart behavior (R11) is scenario'd, and the mismatch
   rules (R12/R13) are asserted through the shipped snapshot-level tests
   (R14).
3. **Can the QA re-verification baseline (prompt → answer in the
   send/settle window) be driven end-to-end?** Resolved: no — fake-claude
   exits when input arrives on its pane, so it cannot answer a second
   prompt in a reused verifier pane. R9 covers the "verification still
   runs" half on the surface; the baseline itself is asserted by the
   shipped `test_follow_up_verdict_honors_a_pre_prompt_baseline` /
   `test_reverification_baselines_before_prompting_the_verifier` tests in
   R14.
4. **Is the sign-off router separately scenario'd?** Resolved: no. It
   shares the same extractor but is auto-start-only and polls on a short
   timer, so the pre-poll race is not deterministic; the review loop and
   QA finalize scenarios cover the same code path on surfaces that expose a
   verdict grace.
5. **A fixed-interval `/loop` delivery re-sends the task prompt — is that
   a new task?** Resolved: no (it carries the scheduler marker); a plain
   user instruction remains a barrier.

No **[UNRESOLVED]** ambiguities.
