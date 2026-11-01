# pr-b491378 — configurable trigger behavior (supplement to impl.md §2)

Status: **PROPOSED, not approved.** This file supplements `impl.md` §2 (trigger
and configuration) and §9 (validation). If the two ever disagree, `impl.md`
governs and this file is a defect.

## 1. The setting

| | |
|---|---|
| CLI | `pm project set checkpoint-after-qa-failures <N \| off>` |
| project.yaml key | `project.checkpoint_after_qa_failures` (integer) |
| Default (key absent) | **2** |
| Valid values | integer `0`–`20`; `off` is stored as `0` |
| Meaning of N ≥ 1 | a checkpoint becomes due when N completed QA runs that ended NEEDS_WORK have been recorded since the last completed (or owner-skipped) checkpoint |
| Meaning of 0 / off | threshold triggering is disabled for every PR in the project. Explicit early requests still work, and a checkpoint that is already due, running, waiting for input or blocked stays so (disabling never releases one silently) |
| Scope | project-wide. **No per-PR override is proposed** (open question Q3 in impl.md) |
| Where the effective value is shown | `pm project set list`; `pm pr checkpoint status <pr>`; the checkpoint prompt's "Why this checkpoint is running" line |

**Validation when set** (`pm project set`, exit 1 with no write on failure; the
write goes through `store.locked_update`, unlike today's boolean
`_set_project_bool` in `pm_core/cli/project.py:61-69`):

| Input | Result |
|---|---|
| `2`, `0`, `20` | stored as int |
| `off` | stored as `0` |
| `on` | rejected — "on" has no number; message names the default |
| `-1`, `21`, `2.5`, `two`, `` (empty) | rejected: `Setting 'checkpoint-after-qa-failures' takes a whole number from 0 to 20 (0 or 'off' disables; default 2)` |

The upper bound is proposed at 20 (open question Q4). It is above D3's planned
ten-bounce ceiling, so any valid value can still fire before that ceiling stops
a loop.

**Invalid stored value** (hand-edited project.yaml: `"two"`, `-3`, `2.5`,
`true`, a list): the effective value is the **default 2**. Disabling needs an
explicit `0`/`off`, so a typo never disables the safeguard. YAML booleans are
rejected even though Python's `bool` is an `int` subclass. Every reader goes
through one function that returns `(value, source, problem)`. The problem is
shown in `pm project set list`
(`checkpoint-after-qa-failures 2 (invalid project value 'two' ignored — using the default)`)
and `pm pr checkpoint status`, and logged once per TUI load. A launch is never
blocked because the value is malformed.

**Changing the value mid-PR:** pm reads the effective value each time it
evaluates the gate (before a review iteration starts). Counted runs are always
recorded, whatever the value, so changing it never loses history.

| Change | Effect |
|---|---|
| Lowered to ≤ current count | due at the next gate evaluation (the next review iteration start); a running review iteration is never interrupted |
| Raised above current count | nothing is due yet; an already-created pending checkpoint stays (it was due when created) |
| Set to 0 | no new threshold triggers; existing pending/blocked checkpoints and requests remain |
| Set back from 0 | the runs recorded while disabled count (the interval was never reset) |

Owner controls besides the setting (`pm pr checkpoint …`, run from the base pm
directory; agent prompts never mention `retry`/`skip`):

| Command | Who | Effect |
|---|---|---|
| `status <pr>` | anyone | effective threshold + source, counted runs in the interval, recently processed runs that did not count and why, open requests, pending checkpoint state/attempts, history |
| `request <pr> --reason TEXT` | owner or agent | records an early request (non-empty reason required); one open request is enough, later ones are appended to it |
| `retry <pr>` | owner | a `blocked` checkpoint gets a fresh attempt budget (evidence kept) |
| `skip <pr> --reason TEXT` | owner | resolves a due or blocked checkpoint without an assessment; recorded in history as `skipped` with the reason, plus a PR note; the interval restarts (open question Q2) |
| `record <pr>` | driver / watcher / owner | validates the assessment and records completion (what the review-loop driver calls on `CHECKPOINT_COMPLETE`) |

## 2. What counts

Rule: **one count per QA run (`loop_id`) whose processed aggregate verdict is
NEEDS_WORK and which completed** — that is, it was not stopped, superseded,
discarded or cut off, and it is not a provider/setup stop. Recorded once, keyed
by `loop_id`, in the same `store.locked_update` as the run's QA note.

| Situation (source of the verdict) | Counts? | Why |
|---|---|---|
| Aggregate NEEDS_WORK from one or more scenario NEEDS_WORK verdicts (`qa_loop.py:6189-6205`) | **yes, once** | a completed failed QA round, however many scenarios failed |
| Aggregate NEEDS_WORK because a PASS failed verification more than `qa-verify-retries` times (`qa_loop.py:4616-4623`) | **yes** | QA judged the result insufficient |
| Aggregate NEEDS_WORK because the QA planner committed code changes (`planner_code_changes`) | **yes** | a useful fix still counts; it is not reclassified |
| Aggregate NEEDS_WORK because the PR head moved during an INPUT_REQUIRED wait (`input_wait_code_changes`) | **yes** (Q1 in impl.md) | the run completed NEEDS_WORK; the wait itself added nothing |
| Aggregate NEEDS_WORK with some scenarios unverdicted or infra-failed | **yes** | NEEDS_WORK wins in the aggregate; the infra part adds nothing |
| Aggregate INPUT_REQUIRED (held run, planner question, missing spec, trust block) | no | not a failed round |
| Held INPUT_REQUIRED run later reopened, with follow-up verdict NEEDS_WORK (same `loop_id`) | **yes, once**, when the follow-up completes | keyed by `loop_id`, so the INPUT_REQUIRED record and any re-processing add nothing |
| Aggregate PASS | no — and it does **not** reset the interval | only a completed checkpoint resets |
| `ERROR` (no session/workdir, container infrastructure failure, crashed thread) | no | infrastructure |
| Provider setup stop (`setup_stop`, empty verdict) | no | infrastructure |
| Scenario launch retries, relaunches, retry exhaustion (`_SCENARIO_MAX_RETRIES`; pr-1ab9075's `launch_retries`; pr-1139060's `launch failed:`) | no | they are inside one run; exhausted retries make the scenario INPUT_REQUIRED, never NEEDS_WORK |
| Run stopped by the user (`stop_requested`) even if a scenario said NEEDS_WORK | no (recorded as `stopped`) | incomplete; its NEEDS_WORK findings still go to review as today |
| Run superseded by `z t` / discarded | no | never processed (`qa_loop.py:1326`, `qa_loop_ui.py:261-279`) |
| Run cut off by a TUI restart, then resumed and completed | yes, once, at completion | same `loop_id` |
| `pm qa run <instruction>` (`cli-<pr>` loop ids) | no | not PR QA |
| Review iterations of any verdict | no | not QA |
| Sign-off verdicts (REQA/REVIEW/IMPL/BLOCKED) and sign-off approval waits | no | the REQA run they cause counts like any QA run |
| A completion processed twice (TUI restart replay, TUI + `pm pr auto-sequence`, duplicate handoff) | once | `loop_id` already present → no-op |

## 3. When the checkpoint runs, and what happens after

- **Due** = no checkpoint is currently pending, and either
  (threshold ≥ 1 and counted runs since the last completion ≥ threshold) or an
  open request exists. A pending checkpoint (due, running, input_required,
  interrupted, blocked) stays due until it completes or the owner skips it.
- **Evaluated** in the review child `pm pr review` immediately before it builds
  a review prompt. That is the one choke point for the TUI loop, `d`/`zz d`,
  auto-start, self-driving `zz t` and the CLI auto-sequence. It runs after
  #274's base-integration gate: a base conflict returns to implementation
  first, and the checkpoint runs at the next review start. It is not evaluated
  before QA, sign-off or merge, or before an implementation session (§2.4 of
  impl.md).
- **Runs as that review-loop iteration**: the same window, transcript naming
  and launch claim, with the checkpoint prompt instead of the review prompt.
  The verdicts it accepts are `CHECKPOINT_COMPLETE` and `INPUT_REQUIRED`;
  PASS/NEEDS_WORK are ignored for that iteration, and no verdict means the
  attempt was interrupted, not NEEDS_WORK.
- **Completes** only when pm validates the committed assessment file. pm then
  moves the covered runs and requests to history, resets the interval, writes
  the completion PR note, and the loop continues with an ordinary review
  iteration whose prompt carries the assessment (P2). The checkpoint iteration
  is neither a review PASS nor a review NEEDS_WORK.
- **Interrupted** (window gone or killed, no verdict, invalid assessment): the
  attempt is recorded with its transcript and error, and the next gate
  evaluation relaunches it with the resume block (P1). After **3** attempts it
  becomes `blocked`. The review loop stops with that outcome (auto-start does
  not relaunch it), a PR note is written, `pm pr auto-sequence` prints
  `paused: checkpoint_blocked (ckpt-<n>)`, and only owner `retry`/`skip`
  continues.

## 4. Validation matrix (the "Validation" paragraph of the PR description)

Each row is planned as an automated test on the durable record and gate
functions (unit level), plus an end-to-end FakeClaude/fake-GitHub scenario
where marked **E2E**.

| # | Given | When | Then |
|---|---|---|---|
| V1 | default config, fresh PR | first QA run completes NEEDS_WORK | count 1/2; the next review iteration is an ordinary review (no checkpoint) **E2E** |
| V2 | V1 | second QA run completes NEEDS_WORK | the next review start runs exactly one checkpoint (one window, one attempt, one `pending` record), then an ordinary review iteration with P2's block **E2E** |
| V3 | V2's checkpoint completed | two more completed NEEDS_WORK runs | a second checkpoint (`ckpt-2`) runs once, with ckpt-1 in "Earlier checkpoints" **E2E** |
| V4 | V2 before completion | a third NEEDS_WORK run somehow completes (e.g. a sign-off REQA raced) | it stays in the interval for ckpt-2; ckpt-1 covers only its two runs |
| V5 | threshold 3 | NW, NW | no checkpoint; NW #3 → due |
| V6 | threshold 1 | NW | due before the very next review |
| V7 | threshold 0 / `off` | 5 × NW | no threshold checkpoint; `status` shows 5 counted, threshold off; an explicit request still runs one |
| V8 | invalid values via CLI (`-1`, `21`, `2.5`, `two`, empty, `on`) | `pm project set …` | exit 1, file unchanged, message as §1 |
| V9 | hand-edited `"two"`, `true`, `-3` in project.yaml | 2 × NW | behaves as default 2; `pm project set list` and `status` show the problem; never disabled |
| V10 | one run with 7 failing scenarios | completes NW | count +1 (not +7) |
| V11 | scenario launch failures/retry exhaustion; ERROR run; setup stop; PASS run; INPUT_REQUIRED held run | each completes | no count; `status` lists each as not counted with its reason |
| V12 | held INPUT_REQUIRED run | follow-up verdict NEEDS_WORK lands; TUI restarts and replays the completion | count +1 exactly |
| V13 | user stops a run with a NEEDS_WORK scenario | completion processed | recorded `stopped`, not counted; review still receives the findings |
| V14 | checkpoint due | TUI loop and `pm pr auto-sequence` tick start review concurrently | one checkpoint window, one attempt (claim CAS), the other driver reports `running: checkpoint` **E2E** |
| V15 | checkpoint running | TUI restarts | the live window is adopted; no second attempt **E2E** |
| V16 | checkpoint running | window killed, no assessment | attempt 1 `interrupted`; attempt 2 launches with the resume block naming attempt 1's transcript and any draft; draft file untouched **E2E** |
| V17 | agent says CHECKPOINT_COMPLETE but the file is missing, uncommitted, for another checkpoint id, has bad front matter, or has `human_question: blocking` | driver validates | attempt `invalid` with the exact error; relaunch with the error in the resume block; PR does not advance |
| V18 | 3 failed attempts | next gate | `blocked`; review loop stops; auto-start does not relaunch; PR note; owner `retry` → attempt budget reset; owner `skip --reason` → history `skipped`, interval reset, review continues |
| V19 | checkpoint ends INPUT_REQUIRED | owner answers in the pane | the same session completes with `human_question: answered`; no advance before that; silence never completes it **E2E** |
| V20 | completed checkpoint with outcome `corrections` | next review iteration | P2 block present; the reviewer's fixes end NEEDS_WORK and another review follows; QA then runs as usual (no verdict shortcut) **E2E** |
| V21 | outcome `spec_change_proposal` on a `review_spec` PR | next iteration | spec file unchanged by the checkpoint; P2 tells the reviewer not to apply it; nothing is waived |
| V22 | outcome `breakup_referral` | — | no `pm pr split` runs, no PR is filed or started by pm itself; PR note records the referral for the owner |
| V23 | outcome `follow_up` with an existing matching PR | — | the agent adds a note to it instead of filing; a new one is filed pending and never started |
| V24 | dirty workdir, untracked drafts, stash, captures, earlier assessments | checkpoint runs and commits | all of them are byte-identical afterwards; the commit contains only the assessment path |
| V25 | open #274 base return / sign-off return | review start | base gate decides first; the sign-off route is unchanged; the checkpoint runs inside the review step that route chose |
| V26 | early request by a reviewer (from the workdir clone) and another by the owner (base) | next review start | one checkpoint covering both request ids; requests read from both project.yaml copies, deduplicated by id |

## 5. Replay over real history (proxy, not a test)

`tools/trace_registry.py` replays the counting rule over the `QA <VERDICT>:`
notes, the only durable per-run history today (full output:
[`trace-registry-output.txt`](trace-registry-output.txt)). Old notes cannot
distinguish stopped runs, and CLI-driven runs left no note, so this is an
approximation.

| Threshold | Checkpoints that would have run | PRs affected |
|---|---|---|
| 1 | 51 | 28 |
| **2 (default)** | **17** | **13** |
| 3 | 6 | 5 |

The registry has 142 noted QA runs, 51 of them NEEDS_WORK, across 51 PRs. At
the default, the three evidence PRs trigger as follows:

- **pr-f38005f** — NW (d8d59509) → IR (not counted) → NW (bdca2401) → **ckpt-1 due** → NW (1fd1b3ae) → NW (c31d04be) → **ckpt-2 due**. This is V1–V3 on real data: the first failure does not trigger, the second triggers once, and two more after completion trigger again.
- **pr-8e693f6** — NW → NW → **ckpt-1 due** (2026-05-26T13:25Z) → IR → IR → PASS → NW → NW → **ckpt-2** → PASS, PASS → NW → NW → **ckpt-3** → PASS, PASS. The PASS runs in between do not reset the interval.
- **pr-2d5f712** — NW → NW → **ckpt-1 due** → NW (1/2) → PASS → PASS. No second checkpoint.

**Hindsight (not evidence the checkpoints had).** For pr-f38005f, after the
point where ckpt-1 would have run, review loop 4b3b spent eight iterations
(4205c741 … faf814e9, 2026-04-09 21:45–23:03Z) adding StoreLockTimeout /
ProjectYamlParseError handling one call site at a time. Master later added a
coalescing TUI write queue (2a654cca, 2026-05-21). For pr-8e693f6, the
`report.json` sidecar was dropped in fca8c07d on 2026-05-30, and impl.md
records the reason ("the earlier `report.json` sidecar duplicated
`project.yaml` / QA-status"); the QA spec was later rewritten because it "had
drifted badly" (note-1f565ff). These are consistent with the illustrative
assessments in `examples/`. They do not prove a checkpoint would have found
the same things, and D9 is where that benefit has to be measured.
