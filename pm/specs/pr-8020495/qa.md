# pr-8020495 — QA spec: PR action history and active timers

Surfaces under test: `pm pr history <pr> [--json]` (CLI), the History row /
`H` shortcut in the PR actions popup (`prefix+P`, `pm _popup-picker`), and the
durable per-PR journal `~/.pm/history/<pr>.jsonl` that review loops, QA runs,
sign-off, merge and the runtime mirror write to. Implementation details are in
`pm/specs/pr-8020495/impl.md`.

## 1. Requirements

### Nominal history

- **R1 — review loop history.** Given a PR whose review loop ran
  NEEDS_WORK → PASS (fake-claude), when the user runs `pm pr history <pr>`,
  then the "Attempts (newest first)" section shows a review-loop attempt with
  one child per iteration (`i1`, `i2`), each with start/end clock times,
  elapsed duration, outcome `done` and its verdict; the loop attempt ends
  `done` with verdict PASS.
- **R2 — JSON parity.** Given the same PR, when the user runs
  `pm pr history <pr> --json`, then the output is valid JSON with schema
  `pm.pr.history/1` whose `attempts`, `timers`, `holds`, `waiting_for` and
  `milestones` contain the same facts (attempt count, outcomes, verdicts,
  iteration numbers, durations) as the text output. An attempt row carries
  a `context` key only when its writer passed one (pr-291e891 will supply
  session/window/task; today no writer does, so it is absent, never null).
  `timers.recent` (max 20; text shows 10) orders resolved timers by
  resolution time and `lost` timers (no resolution time) by arming time,
  so a just-lost timer is not the first row truncated away.
- **R3 — live "what is PM waiting for".** Given a review iteration whose
  fake agent has emitted its verdict and the loop is inside the 20 s verdict
  grace, when the user runs `pm pr history`, then the "Now" section / the
  `Waiting for:` line distinguishes the state (agent working / agent turn
  finished, in grace with N s left / processing verdict / launching next
  iteration) and "Timers and holds" lists the verdict-grace timer with armed
  time, due time, remaining time and expected transition; a second invocation
  a few seconds later shows a smaller remaining time.
- **R4 — human hold has no countdown.** Given a review iteration returned
  INPUT_REQUIRED, when the user runs `pm pr history`, then a
  "review input required" hold is listed with no due time / no remaining
  countdown, the iteration shows a `waiting_human` phase counted as waiting
  (not execution) time, and `Waiting for:` begins with `human:`.
  *Live-test caveat:* fake-claude re-emits its idle hook every 2 s, so the
  review loop re-reads INPUT_REQUIRED and coerces it to NEEDS_WORK within
  ~0.2–2.2 s; the hold is only catchable by polling `pm pr history --json`
  every ~0.25 s, and the iteration then ends `done NEEDS_WORK`. Durable
  human holds are exercised through merge INPUT_REQUIRED, QA
  INPUT_REQUIRED and sign-off BLOCKED (R11/R12).
- **R5 — QA run with overlapping scenarios.** Given a QA run with 3
  scenarios launched together, when the user views history, then the QA run
  attempt has a planner child (label `qa planner`) and three scenario
  children (`qa s1`..`qa s3`) with their verdicts (a scenario attempt spans
  agent + verification; its end matches the TUI "Scenario N (…): PASS
  (verified)" line, after the shared 30 s verdict grace), and the run shows a scenario summary with
  scenario count, a wall-clock figure (union of execution intervals) and a
  sum labelled "not wall-clock"; the run's elapsed time is never the sum of
  scenario times.
- **R6 — queued and retried scenarios.** Given a QA concurrency cap lower
  than the scenario count, when history is viewed, then waiting scenarios show
  a `queued` phase counted as wait, then `launching` while the worker is
  prepared; once a dequeued worker runs, its row reads its own hook state
  (agent working / turn finished with the shared grace) like any other
  scenario, never stuck on "agent working" (058415a8). Given a scenario
  window that dies mid-run,
  when PM relaunches it, then the original scenario attempt ends `vanished`,
  a new attempt for the same scenario with `retry=1` (shown
  `qa sN retry 1`) appears whose leading
  `backoff` phase owns a "relaunch backoff" timer (armed/due/remaining while
  active, then listed under "Recent timers" as `fired`).
- **R7 — planner deadline.** Given the QA planner is still running, when the
  user views history, then an active "QA planner deadline" timer is shown
  with a due time ~60 min after the planner pane launched and expected
  transition "stop waiting for a plan → QA INPUT_REQUIRED"; once a plan is
  found it moves to "Recent timers" as `cancelled`. (The timer is armed at
  pane launch, so it is absent for the first ~2 s of the planner child.)
- **R8 — actions pane History row.** Given any PR, when the user opens the
  PR actions popup, then a `history` row is listed with a compact badge
  (`no history`, `N runs`, `hold: …`, `review-loop i2: turn done, 8s left`…);
  when the user selects it (or presses `H`), then the same text as
  `pm pr history` for that PR is shown in a pager inside the popup and `q`
  dismisses it. The badge follows the same human-first row as
  `Waiting for:`; its countdown is the row's own `fires` timer, or the
  verdict grace only once the agent's turn has finished — a working review
  iteration reads e.g. `review-loop i1: working` with no "Ns left", and a
  working QA scenario row shows no countdown either.
- **R9 — merged / closed PRs.** Given a PR that ran actions and was then
  merged (runtime state cleaned up, panes closed), when the user opens the
  actions popup, then only the History row is offered (not "No actions
  available"), and `pm pr history` still shows every attempt; any journaled
  hold still open shows as `released (PR merged)` — also when the TUI
  that armed it has exited or was killed before the history is read (never
  `lost (owner process exited)` on a merged/closed PR). A stale
  spec-awaiting-approval flag on a merged/closed PR is not shown as a hold.
- **R10 — sign-off router and throttle.** Given auto-start drives a PR into
  sign-off, when the router launches, then history shows a
  `signoff router` attempt and a 60 s relaunch-throttle timer (gate, id
  `signoff-throttle:<pr>`, one id per PR); when the router's verdict is
  routed the attempt ends with that verdict. A relaunch re-arms the same
  throttle id, so Recent timers keeps the earlier entry (`re-armed`, or
  `released at …` when a SIGNOFF_REVIEW hop released it) instead of
  dropping it. A BLOCKED hop does not release the throttle: once the router
  attempt ends it reads `cancelled (owner ended)`. A router run picked up
  across `pm tui restart --breadcrumb` keeps its attempt id, first reads
  `interrupted` (>Ns) and then `done <verdict>` flagged `(adopted)` in text
  and `"adopted": true` in JSON.
- **R11 — merge holds.** Given an auto-start / auto-sequence
  stop-before-merge hold (the PR signed off and waiting for the user to
  press `g`), then an indefinite hold is listed (no countdown) and
  `Waiting for: human: …`; when the merge completes, the hold is released.
  *Live-test caveat:* merge INPUT_REQUIRED is not drivable with
  fake-claude (merge sessions emit no verdicts), and a clean `g` merge
  journals no merge attempt; use the stop-before-merge hold. A merge
  completed by a Claude conflict-resolution window (MERGED verdict
  detected by the TUI) ends `done MERGED`, not `vanished` (impl E9);
  fake-claude cannot emit MERGED either, so this is unit-tested only.
- **R12 — derived holds.** Given a PR with a spec awaiting approval, QA
  ended INPUT_REQUIRED while status is `qa`, or sign-off BLOCKED, then a
  corresponding hold is shown without countdown even though nothing was
  journaled.

### Cancellation / restart

- **R13 — cancel.** Given a running review loop, when the user stops it
  from the TUI, then the loop attempt (and its open iteration) end
  `cancelled`, and any grace timer it owned is shown resolved
  (`cancelled`/`cancelled (owner ended)`), not active.
- **R14 — TUI restart.** Given a review loop or QA run in progress, when the
  user restarts the TUI in place (Ctrl+R / `pm tui restart`), then
  pre-restart open attempts are shown `interrupted` (owner exited / tui-mount)
  with an elapsed lower bound (`>Ns`, bounded by the owner's newest event;
  `restart_app` journals `owner_exit`), not `unknown`; their timers read
  `lost (owner process exited)` until a resumed owner re-arms the same timer
  id (QA grace `qa-grace:<loop_id>`), after which Recent timers lists the old
  entry as `re-armed`. Only `pm tui restart --breadcrumb` resumes a loop
  (plain Ctrl+R just sweeps). The resumed loop/QA run creates *new* attempts:
  a resumed review loop's parent is a new attempt (same loop id, not flagged)
  whose first child is `iN (adopted)` (adopted iterations arm no grace); a
  resumed QA run reads `qa (loop …) (resumed)` with plain `qa sN` children.
  No attempt id is reused and no pre-restart attempt is shown running.
  A restart within seconds of a scenario relaunch or dequeue resumes the
  live retry pane (no spurious `vanished` + duplicate worker in the resumed
  run; the cap still holds). A restart within seconds after a dequeued
  scenario's worker launched (the debug-log "Launched scenario N" line,
  ~15 s after "Launching queued scenario N") keeps verifications that
  landed during the dequeue, does not poll already-settled scenarios
  again (one `done PASS` per scenario, never "up to 3 at once" under cap
  2) and does not end QA ERROR. A restart *between* "Launching" and
  "Launched" is outside this fix (see pr-1b90b51).
- **R15 — hard-killed TUI.** Given a review loop running in a TUI that is
  SIGKILLed (no breadcrumb, so a new TUI does not resume it), when the user
  runs `pm pr history` before and after a new TUI mounts, then the killed
  loop and its iteration read `interrupted` (owner exited; end unknown
  before the new TUI's mount sweep), the `Now` runtime line marks the
  stale loop entry `(stale: owner exited)` instead of "loop running", and
  its grace timer reads `lost (owner process exited)`. A loop the user restarts
  afterwards is a new attempt. Concurrent readers never judge the dead
  owner alive (owner probes serialize; zombie pids count as dead).

## 2. Setup

- Follow `pm/qa/instructions/tui-manual-test.md`: venv + editable install
  (`./install.sh --local` if `pm` is missing), `PYTHONPATH` pointing at the
  clone, a throwaway git project with `pm init --backend local --no-import`,
  `pm session` in tmux.
- Use fake-claude for every Claude-backed session (`pm fake-claude config
  set …`). Use per-iteration `delay` entries to stretch a phase long enough
  to observe live timers (e.g. 20–40 s on a review iteration, on
  `qa_planning`, on `qa_scenario`).
- Use a scratch `HOME` (and `env -i`-style clean environment so
  `CLAUDECODE` / `PM_HOST_HOME` from the outer session do not leak) so
  `~/.pm/history/` starts empty. A dummy `claude` on PATH may be needed.
- `pm pr history` is run from a separate tmux pane/window of the test
  session (or from the shell with the test project as cwd).
- Controlled clocks: production timing has no clock override at the user
  surface; timing assertions are made by comparing the JSON's
  `generated_at` with `armed_at`/`due_at`/`remaining_s` across repeated
  invocations, with tolerances of a few seconds. Deterministic clock tests
  live in `tests/test_action_history.py` (run them as a smoke check).

## 3. Edge cases

- **E1 — no history.** Given a freshly added PR with no actions, when the
  user runs `pm pr history`, then the output says "No recorded action
  history…", lists milestones from project.yaml if any, `--json` has
  `attempts: []` and a `missing` note; the popup badge says `no history`.
  Given a PR whose journal starts more than 60 s after its `started_at`
  (e.g. started from the CLI, which journals nothing, and only later
  reviewed in the TUI), the history shows the recorded attempts plus the
  note "Actions before <time> were not recorded; earlier milestones come
  from project.yaml only."

- **E2 — unknown PR.** Given an id that is neither in project.yaml nor has a
  journal, the command prints the standard not-found error and exits
  non-zero. Given a PR removed from project.yaml whose journal survives, the
  command still shows its history. `#N` display ids resolve.
- **E3 — corrupted journal.** Given a journal with a truncated last line or
  garbage lines, history still renders the valid events (no traceback).
  A non-UTF-8 byte spoils only its own line (c57cdda4): text, `--json`,
  the popup badge/pager and sign-off routing (which looks up the newest
  open router attempt in the journal) keep working. A parseable line whose
  time fields are not numbers (e.g. `"t": "abc"`) is skipped like a
  garbage line, never a traceback (78c6edcd).
- **E4 — instrumentation must not change execution.** Given the history
  directory is unwritable (or the journal file is a directory), when the
  user runs a review loop / QA run, then the loop reaches the same verdicts
  and status transitions as normal; only history is missing.
- **E5 — 80 columns.** Text output and the pager view do not exceed 80
  columns at an 80-column terminal (phase breakdowns and timer lines wrap).
  Times are local `HH:MM:SS` on the reader's day, `MM-DD HH:MM:SS` on an
  earlier day of the same year, full `YYYY-MM-DD HH:MM:SS` in another
  year; an attempt's end carries a date only when it falls on another day
  than its start. Rows from an earlier day (the usual view of a merged
  PR) still fit 80 columns unwrapped, the Milestones line wraps
  between items, never inside one, and a Recent-timers row whose
  resolution time carries a full date wraps between its parts
  (`purpose: resolution` / `at …` / `(armed …)`) instead of exceeding 80
  columns. An attempt row with a dated start plus a flagged name (e.g.
  `signoff router (adopted)`, `review-loop (loop …) cancelled KILLED`)
  wraps its outcome onto a sub-indented line (3ccea259); hold/timer head
  rows (e.g. the derived sign-off BLOCKED hold) and free-text lines
  (title, `Waiting for:`, `Now` rows, the runtime line, attempt details,
  the missing-history `Note:`) word-wrap at 80 (e4d33439, 563c5618), so
  plain `pm pr history | cat` stays within 80 columns and matches the
  TTY output word for word.
- **E6 — overdue.** A `fires` timer past due whose owner is alive shows
  `overdue by Xs`, never negative remaining.
- **E7 — concurrent writers.** Two or more processes (TUI loop threads, a
  `qa-run-bg` process, CLI-launched actions, two loops on the same PR or on
  different PRs) appending to journals at once never interleave/torn lines,
  every attempt started is present with its own id, and concurrent
  `pm pr history --json` readers always get valid JSON.
- **E8 — rotation.** Given a journal near 4 MB, further writes rotate it to
  `<pr>.1.jsonl`; history still shows attempts from both generations.
  A reader racing a rotation never drops the generation just rotated
  (d88abd95): attempt counts read by concurrent pollers never dip.
- **E9 — superseded loop.** Given a review loop restarted while one is
  running, the old loop attempt ends `superseded`, not `done`.
  (The superseded loop's open iteration may first read `superseded`, then
  `cancelled KILLED` once the old loop thread sees its pane gone; either is
  acceptable, `done`/`running` is not.)
- **E10 — re-tracked impl pane (impl spec E8).** Given PM stops watching
  the impl pane while a review loop owns the PR and re-registers it when
  the loop ends, then history shows one `start` attempt continuing after a
  "not tracked" span (counted as neither exec nor wait), not an extra
  "start untracked" row per review loop. In `--json` the kept attempt
  lists the folded ids as `merged_ids`, so the runtime mirror's
  `attempt_id` for `start` always resolves to an attempt (b29bcdfa).
- **E10b — command-bar review.** A review started by typing
  `/pr review <pr>` in the TUI command bar is tracked and journaled like
  one started with `d` (76742637); history never says "No recorded
  action history" for a review that ran.
- **E11 — cleanup ends in-flight attempts.** Given an action is in flight
  (impl pane, review loop, merge pane), when `pm pr cleanup
  --resources`, TUI `Y`, `pm pr merge` or merge detection tears down the
  PR's resources (plain `pm pr cleanup` only removes the workdir), then those attempts end
  `interrupted` with reason "PR resources cleaned up"; none is shown
  running afterwards and the history survives.
- **E12 — short-lived CLI openers.** Given an attempt opened by a
  short-lived CLI process (e.g. the start mirror registered by
  `pm pr auto-sequence`) that the runtime mirror still tracks in flight,
  then history shows it running, not "interrupted — owner process exited".
- **E13 — Now line verdicts.** An in-flight runtime entry shows its stale
  verdict as `(last X)` (e.g. `review-loop=running (last NEEDS_WORK)`),
  never as if it were the running attempt's outcome. A finished entry
  keeps its own state while its pane stays open: after a plain review
  prints its verdict the line reads `review=done NEEDS_WORK`, not
  `review=idle (last NEEDS_WORK)` (a07a4d46).
- **E14 — history path not a directory.** If `~/.pm/history` is a regular
  file, `pm pr history` (text and `--json`) prints honest empty history and
  exits 0; loops are unaffected. The same holds for a read-only
  `~/.pm/history` that has no `owners/` subdirectory (the liveness probe
  falls back to the pid check, never tracebacks).
- **E16 — two projects, one HOME.** `~/.pm/history`, `~/.pm/runtime`
  and `~/.pm/workdirs/qa` are per-HOME. Given two project TUIs in one
  HOME, a restart (mount sweep) in one project never ends the other
  project's live runtime-mirrored attempts (runtime entries carry an
  owner; the sweep skips entries of other live owners), a TUI never
  deletes another session's `qa_resume.json` (so a SIGKILLed TUI's QA can
  still be resumed by its own respawned TUI), and a gate that already read
  `elapsed` before its owner died stays `elapsed` (owners heartbeat their
  lock once a second). Two projects with identically titled PRs share one
  PR id and journal — a known defect filed as pr-c64eb04, out of scope;
  use distinct titles.
- **E17 — many past owners.** Every TUI restart / CLI run is a journal
  owner; only owners with an open attempt or uncleared timer are probed,
  so `pm pr history` stays fast (≈ the same latency) on a PR whose journal
  has dozens of finished owners.
- **E15 — popup ergonomics.** At 80 columns the popup header wraps so the
  `H=history` hint is visible, Enter on any action row (including history)
  runs it, and the History pager wraps at word boundaries to the popup
  width and reads the session's project root (current status/milestones),
  not a workdir's stale project.yaml.

## 4. Pass / fail criteria

Pass: every Then above is observable on the CLI text, `--json`, and popup
pager, and the three agree for the same PR at the same moment (modulo the
seconds elapsed between invocations). Timers show armed/due/remaining with
remaining decreasing over time; holds show no countdown; concurrent
scenarios are never summed into the run's elapsed time; cancelled/
interrupted/vanished/superseded outcomes are distinct and correct; loops
behave identically with history broken.

Fail: tracebacks from `pm pr history` or the popup; missing/duplicated
attempts; an attempt shown "running" after its owner process exited or was
cancelled; active timers after their owner ended; negative remaining time;
history lost after merge; the popup showing different numbers from the CLI;
a loop whose verdict/status sequence changes when history is unwritable;
invalid JSON lines in the journal after concurrent writes.

## 5. Ambiguities (resolved)

- *Controlled clocks* — not user-reachable; covered by unit tests and by
  tolerance-based comparisons of live JSON output (see Setup). Date
  display (E5) is local time, so a reader can be put on "another day" by
  running `pm pr history` with a `TZ` whose local midnight falls between
  the attempts and now (e.g. a POSIX offset like `TZ='<X>-09:58'`), or
  with libfaketime (`faketime '+80 days'`) for the other-year form.
- *"Retries"* — QA scenario relaunches, sign-off relaunches, superseded
  review loops and repeated runs of the same action (impl spec A1). There is
  no review-loop retry/backoff in production code.
- *Approval waits* — spec approval, review/merge INPUT_REQUIRED, QA
  INPUT_REQUIRED, sign-off BLOCKED, auto-merge hold (impl spec R7/A2). Past
  spec-approval durations are not journaled and are not expected.
- *Even Realities interface* — not built yet; exposure is verified only via
  the shared action catalog driving the terminal popup.
- *Agent idle vs execution* — idle time inside an agent turn counts as
  execution (impl spec A3); only queued/backoff/human-hold phases are wait.
