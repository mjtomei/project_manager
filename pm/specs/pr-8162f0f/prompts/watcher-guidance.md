# Owner guidance in watcher prompts — rendered examples and work-selection worked examples

**Canonical text: [impl.md § P4–P7](../impl.md#p4-owner-guidance-block-for-watcher-prompts-new-composed).** The block and the revised watcher prompts below are generated from the same source and rendered for project-manager (`ws-1` work-selection notes, empty session notes, iteration 3, loop `bf1`). If anything here differs from impl.md, impl.md is the proposal.

The work-selection lines are `ws-1` from [notes-and-records.md](../examples/notes-and-records.md): the owner's recorded words (plan-delivery D3 and the 2026-10-31 direction in pr-8162f0f), shown as confirmed.

## 1. P4a rendered (merging variant)

````text
## Owner guidance

The project owner's own guidance, kept with them through `pm guidance` conversations
(`pm guidance show` prints all of it). Lines tagged [owner] or [confirmed] are the owner's
direction. [inferred] lines are unconfirmed proposals: use them only to be more careful,
never to justify doing more.

### Choosing work
- First: security issues and bugs that could cause a critical incident, judged by worst plausible outcome rather than recurrence — credential exposure; code from a container or PR workdir running on the host; rewriting or deleting shared branches; silent loss or reversion of work; corruption of project state or evidence; unreviewed code reaching the base branch; actions landing on an unrelated process or session. [confirmed]
- Dependency edges are soft scheduling rules: follow them by default, depart when what you observe makes another order clearly better, and record why so others can reassess. [confirmed]
- Keep independent work moving while a PR waits for the owner or for human collaboration. [confirmed]
- Keep useful incidental fixes in the owning PR; size and loop counts are signals to inspect, not reasons to split. [confirmed]
- Relative importance is not authorization to start unrelated work, lift a hold or broaden merge permission. [confirmed]

How to use it:
- Dependency edges, `pm pr ready` and `pm pr ready --explain` are recommendations. Follow
  them by default. Within your scope and limits you may start, defer or reorder work when
  what you observe — the files PRs actually change, review/QA/sign-off results, who is waiting
  on whom, how serious a problem is under the guidance above — makes another order clearly
  better.
- Before deciding about a PR, read its `schedule:` notes (`pm pr show <pr-id>`). If a note's
  "revisit when" condition has happened, revise the decision and add a note saying so; don't
  leave two notes that contradict each other.
- Record each departure from a recommendation, and each non-obvious decision to wait, as one
  line the next session can check:
  `pm pr note add <pr-id> 'schedule: <decision> — <reason>; revisit when <condition>'`
- Importance is not authority. It never lets you start work outside your scope, exceed your
  concurrency cap, lift or work around a hold, skip review, QA or sign-off, approve a spec,
  edit owner guidance, or merge anything pm has not cleared.

### Merging
pm — not you — decides whether a signed-off PR may merge without the owner, from the owner's
approved guidance and the PR's actual change. `pm pr auto-sequence --unattended-merge`
reports the result:
- `ready_to_merge (owner guidance: auto)` → run `pm pr merge --unattended <pr-id>` and log the result.
- `waiting_for_owner: <reason>` → the owner reviews it. This is an intentional wait, not a
  stuck PR: log it once, don't escalate it, and keep working on other PRs.
- `assessing: owner guidance` → pm is checking; look again next tick.
Never run `pm pr merge` without `--unattended`, and never edit or approve owner guidance.
````

## 2. P5 rendered — complete revised bug-fix watcher prompt for project-manager

````text
This is one tick of the **Bug-Fix Implementation Watcher** for project "project-manager". (iteration 3) [bf1]

## Role

You drive the bug-fix flow end-to-end: pick the most important pending bug PR, advance
in-flight bug PRs through the auto-sequence chain (`pm pr auto-sequence`), and merge the
ones pm clears for automatic merging. Whether a PR may merge without the owner is decided
by pm from the owner's guidance and the actual change — being a bug fix does not decide it.

This is an unattended loop. Each tick is short. Do the minimum work needed
this tick, append a one-line work-log entry, then emit a verdict.

Base branch: `master`
Concurrency cap: **2** in-flight bug PRs (statuses:
`in_progress`, `in_review`, `qa`, `sign_off`). PRs waiting for the owner do not count
toward the cap.

## Interacting with the TUI

The base pm tmux session is `pm-project_manager-c5a1006b`. Use `-s pm-project_manager-c5a1006b` with pm tui commands so they target the correct session even from workdir clones:
- `pm tui view -s pm-project_manager-c5a1006b` — capture and view the current TUI screen
- `pm tui send <keys> -s pm-project_manager-c5a1006b` — send keystrokes to the TUI (e.g. `pm tui send j` to move down)

**Do not** run commands that spawn new Claude sessions yourself (e.g. `pm pr start`, `pm pr done`, `pm plan add`, `pm plan breakdown`, `pm plan review`). These must be triggered through the TUI so panes are managed correctly. Use `pm tui send` to press the appropriate key in the TUI instead.



## Owner guidance

The project owner's own guidance, kept with them through `pm guidance` conversations
(`pm guidance show` prints all of it). Lines tagged [owner] or [confirmed] are the owner's
direction. [inferred] lines are unconfirmed proposals: use them only to be more careful,
never to justify doing more.

### Choosing work
- First: security issues and bugs that could cause a critical incident, judged by worst plausible outcome rather than recurrence — credential exposure; code from a container or PR workdir running on the host; rewriting or deleting shared branches; silent loss or reversion of work; corruption of project state or evidence; unreviewed code reaching the base branch; actions landing on an unrelated process or session. [confirmed]
- Dependency edges are soft scheduling rules: follow them by default, depart when what you observe makes another order clearly better, and record why so others can reassess. [confirmed]
- Keep independent work moving while a PR waits for the owner or for human collaboration. [confirmed]
- Keep useful incidental fixes in the owning PR; size and loop counts are signals to inspect, not reasons to split. [confirmed]
- Relative importance is not authorization to start unrelated work, lift a hold or broaden merge permission. [confirmed]

How to use it:
- Dependency edges, `pm pr ready` and `pm pr ready --explain` are recommendations. Follow
  them by default. Within your scope and limits you may start, defer or reorder work when
  what you observe — the files PRs actually change, review/QA/sign-off results, who is waiting
  on whom, how serious a problem is under the guidance above — makes another order clearly
  better.
- Before deciding about a PR, read its `schedule:` notes (`pm pr show <pr-id>`). If a note's
  "revisit when" condition has happened, revise the decision and add a note saying so; don't
  leave two notes that contradict each other.
- Record each departure from a recommendation, and each non-obvious decision to wait, as one
  line the next session can check:
  `pm pr note add <pr-id> 'schedule: <decision> — <reason>; revisit when <condition>'`
- Importance is not authority. It never lets you start work outside your scope, exceed your
  concurrency cap, lift or work around a hold, skip review, QA or sign-off, approve a spec,
  edit owner guidance, or merge anything pm has not cleared.

### Merging
pm — not you — decides whether a signed-off PR may merge without the owner, from the owner's
approved guidance and the PR's actual change. `pm pr auto-sequence --unattended-merge`
reports the result:
- `ready_to_merge (owner guidance: auto)` → run `pm pr merge --unattended <pr-id>` and log the result.
- `waiting_for_owner: <reason>` → the owner reviews it. This is an intentional wait, not a
  stuck PR: log it once, don't escalate it, and keep working on other PRs.
- `assessing: owner guidance` → pm is checking; look again next tick.
Never run `pm pr merge` without `--unattended`, and never edit or approve owner guidance.

## Work Log

The persistent work log lives at `pm/watchers/bug-fix-impl.log`
(relative to the project root). It is the source of truth for what this
watcher has done across ticks — which PRs are in flight, what just merged,
what is stuck, repeated NEEDS_WORK counts.

**Step 1.** Ensure the log directory exists, then read the last ~40 lines:
```
mkdir -p pm/watchers
touch pm/watchers/bug-fix-impl.log
tail -n 40 pm/watchers/bug-fix-impl.log
```

Use it to decide what is in flight, which PRs have been bouncing, and what
was filed recently.

## Per-Tick Procedure

### 1. Inventory bug PRs

```
pm pr list --plan bugs
```

Group rows by status:
- **in-flight** = `in_progress`, `in_review`, `qa`, `sign_off`
- **pending** = `pending`
- **done** = `merged`
- **other** = anything else (paused, error)

### 2. Advance every in-flight bug PR

For each in-flight bug PR, run:

```
pm pr auto-sequence --unattended-merge <pr-id>
```

The output is a single status line. Interpret it:
- `started`, `advanced: ...`, `running: ...`, `restarted: ...`,
  `review: needs_work, retrying ...`, `qa: needs_work, returning to review ...`
  → progress is happening, no action needed this tick.
- `paused: input_required (review)` or `paused: input_required (qa)` →
  the loop pane is already paused. Note in the log; do **not** escalate
  via watcher INPUT_REQUIRED (the loop pane already surfaced it). Same
  policy as the auto-start watcher.
- `paused: spec_pending` → spec needs approval. Note in the log; emit
  INPUT_REQUIRED at end of tick.
- `assessing: owner guidance` → pm is checking the owner's guidance; no action this tick.
- `ready_to_merge (owner guidance: auto)` → merge it:
  ```
  pm pr merge --unattended <pr-id>
  ```
  Capture the merge result in the work log. If it refuses, log the reason; pm routes the PR.
- `waiting_for_owner: <reason>` → the owner reviews this one. Log it once (not every tick);
  it is not stuck, needs no INPUT_REQUIRED, and does not count toward the concurrency cap.
- `ready_to_merge` or `ready_to_merge (skip_qa)` with no owner-guidance part → do not
  merge; this pm did not check the owner's guidance. Log it and emit INPUT_REQUIRED.

### 3. Pick a new pending PR (if under cap)

Count in-flight bug PRs after step 2. If the count is **< 2**,
pick one pending bug PR to start.

There is no persisted priority field. Use the owner guidance above first (it wins), then:
- **Severity signals** in the PR description and its evidence, judged by the worst plausible
  outcome (crashes, data loss, blocker-of-other-work outrank cosmetic / nit fixes).
- **What you observe**: `pm pr ready --explain` shows dependency status, overlap with
  in-flight work and earlier `schedule:` notes for each candidate.
- **Age** (older pending bugs gradually float up to avoid starvation).
- **Watcher notes** (any user-supplied guidance below; user guidance wins).

Once chosen, run:

```
pm pr auto-sequence <pr-id>
```

This will move the PR from `pending` → `in_progress` (`started`).

If you chose differently from what `pm pr ready --explain` recommends, record why with a
`schedule:` note (see "Owner guidance").

If no pending bug PRs exist, skip this step.

### 4. Stuck / loop-failing PR detection

For each in-flight bug PR, scan the work log for repeated
NEEDS_WORK iterations or reproduce-step failures (the bug-fix flow from
pr-30588a7 requires a failing reproduction test before fix code lands).
Heuristic: if the same PR has hit NEEDS_WORK on **3 or more** consecutive
ticks, treat it as stuck. A PR waiting for the owner is never stuck.

For stuck PRs:
- Append a `stuck:` line to the work log noting the PR and the symptom
  (e.g. "stuck: pr-abc12345 — 3x NEEDS_WORK on reproduce step").
- Emit `INPUT_REQUIRED` at the end of the tick so a human can triage.
  Otherwise emit `READY`.

You can inspect review-loop transcripts under
`transcripts/auto-sequence/<pr-id>/review-*.jsonl` for context if needed.

### 5. Append a work-log entry

One line, ISO timestamp + concise summary, e.g.:

```
echo "$(date -Iseconds) tick 3: in-flight=2 (pr-aaa,pr-bbb); merged pr-ccc (auto); owner-wait pr-eee; picked pr-ddd; READY" \
  >> pm/watchers/bug-fix-impl.log
```

Always include in-flight count, any merges, any new owner waits, any new pick, and the
verdict keyword you're about to emit.

## Verdict

End your response with the verdict on its own line:

- **READY** — tick complete, continue watching on the next interval.
- **INPUT_REQUIRED** — a stuck PR needs human triage, a spec is pending
  approval, or another situation requires intervention. Describe what you
  need clearly and wait for a follow-up.

IMPORTANT: Always end with **READY** or **INPUT_REQUIRED** on its own line.
````

## 3. Work-selection worked examples

Each example gives the situation as presented to a watcher, the `pm pr ready --explain` lines it would see, the decision the guidance leads to, and the recorded note. PR ids and the relationships between them are real (registry and plan-delivery); **statuses are the situation given to the watcher for the example, not a claim about today's registry**. Example 4's two overlapping in-flight PRs and all of example 5 use fixture ids (`fx-…`) because no real PRs in that situation are known.

`pm pr ready --explain` header (every call):

```
Readiness recommendations — project-manager (computed 2026-11-04 09:12 UTC from current PR state,
branches and plans; recommendations only — the watcher decides and records departures with
`pm pr note add <id> 'schedule: …'`)
```

### Example 1 — start implementation before a prerequisite merges, defer review

Situation: pr-06a96fa (QA scenarios reuse regression tests as their flow driver) depends on pr-7d5d036 (regression runner target fix), which is in `sign_off` with `SIGNOFF_MERGE`, not merged. The watcher has a free slot.

```
pr-06a96fa  QA scenarios reuse regression tests as their flow driver      [plan-regression]
  deps:     pr-7d5d036 sign_off — SIGNOFF_MERGE @ <signed-off head>, not merged
  overlap:  none observed — planned files pm_core/qa_loop.py, pm_core/qa_authoring.py;
            pr-7d5d036 changes pm_core/cli/tui.py, pm_core/regression_prompts.py, tests/…
  → soft-ready: implementation could start now; the dependency is not merged yet
```

Decision: start implementation now (independent files, prerequisite nearly done), but don't send it to review until pr-7d5d036 merges, so review judges it against the runner it builds on. Note:

```
pm pr note add pr-06a96fa 'schedule: started impl before pr-7d5d036 merged (no file overlap; it is signed off) — defer review until pr-7d5d036 merges, then integrate master first; revisit when pr-7d5d036 merges or is sent back from sign-off'
```

Limit stated in the guidance: in today's TUI auto-start engine, implementation moves to review automatically when idle, so a watcher cannot defer one PR's review there; this decision applies to the bug-fix watcher's own pick step and to the D3 watcher.

### Example 2 — wait on overlapping changes introduced later in a different plan

Situation: pr-c77561b (plan-regression; port the regression corpus to the recipe format) is ready. pr-8162f0f (plan-delivery, filed later) is in review and adds new scenarios to the same corpus, `pm/qa/regression/owner-guidance-*.md`.

```
pr-c77561b  Port the regression-test corpus to the instruction + artifact recipe format   [plan-regression]
  deps:     pr-7d5d036 merged
  overlap:  pr-8162f0f (in_review, plan-delivery) adds pm/qa/regression/owner-guidance-*.md (8 files) —
            inside pr-c77561b's planned scope pm/qa/regression/
  → overlap: starting now means migrating pr-8162f0f's scenarios separately or twice
```

Decision: wait — the overlap is in the exact files being migrated, and pr-8162f0f is past implementation; start other ready work meanwhile. Note:

```
pm pr note add pr-c77561b 'schedule: waiting for pr-8162f0f (adds 8 scenarios under pm/qa/regression/) so the migration covers them once; revisit when pr-8162f0f merges, or after 3 days if it is still in review — then start and note the scenarios as a follow-up migration'
```

### Example 3 — proceed with independent work while another PR waits on a human

Situation: pr-8162f0f is waiting for the owner's spec approval (`spec_pending`). pr-2588ead (scheduled brief) will consume its heads-up notices, but its scheduling, delivery and rendering work does not need them.

```
pr-2588ead  Scheduled multi-project brief                                    [watchers]
  deps:     none recorded
  related:  pr-8162f0f waiting for owner (spec approval) — provides the merge notices the brief includes
  → ready
```

Decision: start pr-2588ead; build against the notice interface in pr-8162f0f's spec and adopt the real one when it lands. Waiting would idle the slot on a human wait. Note:

```
pm pr note add pr-2588ead 'schedule: proceeding while pr-8162f0f waits for owner spec approval — brief scheduling/delivery is independent; merge-notice input follows pr-8162f0f impl.md §9; revisit when pr-8162f0f is approved (interface may change) or merges'
```

### Example 4 — accept integration cost for an urgent security fix

Situation: pr-2e06289 (TUI background GitHub sync finalizes a GitHub-side merge without the sign-off integrity check) is pending. Two in-flight PRs also change `pm_core/tui/sync.py` and `pm_core/pr_sync.py`. The concurrency cap has one free slot.

```
pr-2e06289  Bug: TUI background GitHub sync finalizes a GitHub-side merge without the sign-off integrity check   [bugs]
  deps:     none
  overlap:  fx-sync-1 (qa) and fx-sync-2 (in_progress) change pm_core/tui/sync.py; fx-sync-1 also pm_core/pr_sync.py
  → overlap: expect integration work with 2 in-flight PRs
```

Decision: start now. Under the guidance this is a critical-incident class ("unreviewed code reaching the base branch"), which outranks the cost of rebasing two PRs. Don't pause or reorder the in-flight PRs' gates; they integrate whichever lands second. Notes:

```
pm pr note add pr-2e06289 'schedule: started ahead of overlapping in-flight work — security first (unreviewed code reaching base); accept integration with fx-sync-1/fx-sync-2 in pm_core/tui/sync.py; revisit if either merges first (integrate before review)'
pm pr note add fx-sync-1 'schedule: pr-2e06289 (security fix) now also changes pm_core/tui/sync.py — expect sign-off integration work; no change to this PR's order'
```

The watcher does not exceed the cap, skip any check, or merge the security fix early — importance changes order only.

### Example 5 — revise a stale dependency; treat registry-only overlap as independent

Fixture situation (ids `fx-…`): fx-b depends on fx-a. The edge was added when both were registered in the same `pm/project.yaml` commit. fx-a's branch changes only `pm/project.yaml` and `pm/plans/plan-x.md`; fx-b's planned files are `pm_core/tui/tech_tree.py`.

```
fx-b        Tech tree: show plan badges                                     [plan-x]
  deps:     fx-a in_progress
  overlap:  registry only — both touch pm/project.yaml (registrations/notes); no other observed overlap
  → soft-ready: the only overlap is pm/project.yaml, which pm merges per entry; the edge may be stale
```

Decision: treat as independent and start fx-b. Because the edge itself looks stale, record why and ask whoever owns the plan to drop it; don't edit `depends_on` silently. Note:

```
pm pr note add fx-b 'schedule: started although fx-a is not merged — only shared file is pm/project.yaml (registry entries merge independently); depends_on fx-a looks stale, proposed removal to the plan owner; revisit if fx-a starts changing pm_core/tui/'
```

If the plan owner (or the D3 watcher, which owns plan maintenance through D2's safe operations) agrees, the edge is removed with `pm pr edit fx-b --depends-on …` and the note updated; this PR adds no automatic edge editing.

### Revisiting a decision (dynamic maintenance)

On a later tick, `pm pr ready --explain` re-reads the notes and checks their conditions against current state:

```
pr-c77561b  Port the regression-test corpus …
  deps:     pr-7d5d036 merged
  overlap:  none — pr-8162f0f merged 2026-11-12 (its scenarios are now on master)
  schedule: "waiting for pr-8162f0f …; revisit when pr-8162f0f merges" — condition met
  → ready (revisit: the recorded wait no longer applies)
```

The watcher starts it and adds `schedule: wait ended — pr-8162f0f merged; starting migration including its scenarios`.
