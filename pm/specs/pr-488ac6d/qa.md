# pr-488ac6d — QA spec: TUI auto-sequence must hand QA PASS to sign-off

Code under test: branch `pm/pr-488ac6d-bug-tui-auto-sequence-skips-sign-off-after-qa-pass`
at **1c162a86** or later. QA run 2 added: c762e3d5 (CLI qa-run-bg drops
its resume snapshot after finishing — no stale "press i" after a CLI
SIGNOFF_REQA bounce), a1d4324b ("signoff: launching router" logged only on a
real launch, not on backoff-skipped polls), b8e97482 (after Ctrl+R + re-arm
mints a new autostart run dir, the live stamped router run is adopted into
it, then recorded if stamp==HEAD or retired as stale), 1c162a86 (a hung
`pm pr signoff` launch is killed at its 300 s timeout so it stops holding the
launch lock). Since 210a2efa, QA run 1 added: 0ff2be65 (sign-off
verdict bound to the HEAD its router launched on — R9b), 6c81d3cb (O ready
line logged force+hold so it is visible on the TUI log line), 687bca6b +
272ed914 (TUI QA-resume scan skips QA runs owned by another live process,
with a pid-reuse guard — R15). Earlier baseline was **210a2efa** (post-review: shared merge-gate helper, *asynchronous*
`pm pr signoff` launch worker, in-flight de-dupe, per-tick reload skip,
skip_qa reason). The implementation captures under `impl/{pre,post}-fix`
predate the async-launch review rounds — **workers must validate against
210a2efa themselves** (`git log -1` in the clone they install from must
show 1c162a86 or a descendant) and must observe the real background
launch, not reuse those captures.

## What changed (user-visible)

* TUI auto-start (`O` = stop before merge, `A` = auto-merge) used to treat a
  QA PASS as "ready to merge": `O` printed a green "ready to merge" line with
  the PR still `qa` and no sign-off; `A` called `pm pr merge`, hit the
  sign-off gate and then mis-tracked the refusal as a merge conflict.
* Now a QA PASS (or, with `skip_qa`, a review PASS) moves the PR to
  `sign_off`, launches the sign-off router window **in the background**
  (`pm pr signoff --background --transcript <run>/signoff-<pr>.jsonl`), reads
  its verdict, records it against the current HEAD (origin `auto-sequence`),
  and routes it:
  * `SIGNOFF_MERGE` → `O`: "✓ <pr> signed off (SIGNOFF_MERGE @ <sha8>) —
    ready to merge … press 'g'"; `A`: merges.
  * `SIGNOFF_REQA` → back to `qa`, QA loop restarted.
  * `SIGNOFF_REVIEW` → back to `in_review`, review loop restarted.
  * `SIGNOFF_IMPL` → back to `in_progress`, impl window relaunched fresh.
  * `SIGNOFF_BLOCKED` → stays `sign_off`, red sticky "needs a human decision"
    line, never merges.
* `pm pr signoff` accepts `in_review` PRs when `project.skip_qa` is true.
* `pm autostart status` / runs popup (`a`) reasons updated (see R9).
* CLI `pm pr auto-sequence` refactored onto the same sign-off state machine;
  its output is meant to be unchanged.

## Setup (all scenarios)

Follow `pm/qa/instructions/tui-manual-test.md`:
1. Install pm from the PR clone (editable; `export PYTHONPATH=<clone>`;
   `pm which` shows the clone). Confirm HEAD is 1c162a86 or later. (There is no `pm pr show`;
   read status/workdir from `pm pr list` and project.yaml.)
2. Throwaway git project, `pm init --backend local --no-import`, add PRs with
   `pm pr add`. Give each PR a real commit on its branch once its workdir
   exists (the impl stage) so merges and HEAD shas are meaningful.
3. Start `pm session`; drive everything through the TUI keys / `pm autostart`
   / `pm pr` commands run in a pane of the *test* tmux session.
4. Use fake-claude (`pm fake-claude config set`) so every Claude session is
   deterministic. Baseline config:
   ```json
   {"_all": {},
    "review": {"verdicts": ["PASS"]},
    "qa_planning": {"verdicts": ["QA_PLAN"], "body": "SCENARIO 1: s\nFOCUS: f\nINSTRUCTION: none\nSTEPS:\n  GIVEN a\n  WHEN b\n  THEN c"},
    "qa_concretize": {"verdicts": ["REFINED_STEPS"]},
    "qa_scenario": {"verdicts": ["PASS"]},
    "qa_verification": {"verdicts": ["VERIFIED"]},
    "qa_finalize": {"verdicts": ["FINALIZE_DONE"]},
    "signoff": {"verdicts": ["SIGNOFF_MERGE"]}}
   ```
   The `signoff` cursor persists across launches per session, so a scripted
   list (e.g. `["SIGNOFF_REQA","SIGNOFF_MERGE"]`) yields one verdict per
   router launch. Use `{"verdict": "...", "delay": N}` entries when a
   scenario needs the router window to stay up for a while.
5. Artifacts: tmux pane transcript + asciinema of the TUI
   (`tmux-screen-recording.md`) and CLI recordings of `pm autostart status`,
   `pm pr show`, `pm pr merge`/`pm pr signoff` commands (`cli-recording.md`).
   Also save `pm/project.yaml` snapshots showing `status` and the `signoff`
   record (`verdict`, `sha`, `origin`) at each key point.

## Requirements (Given / When / Then)

R1. Bug repro — O stops only after sign-off. Given an auto-start target with
`O` policy, `skip_qa` false, fake review PASS / QA PASS / SIGNOFF_MERGE;
When the sequence runs from pending; Then: after QA PASS the log says
"QA PASS for <pr> — handing off to sign-off" and "Auto-start: <pr> →
sign-off" (never "ready to merge" at that moment); the PR shows `sign_off`;
a `signoff-…` tmux window appears without stealing focus from the TUI;
after the router prints SIGNOFF_MERGE the PR record has
`signoff.verdict=SIGNOFF_MERGE`, `sha`=branch HEAD, `origin=auto-sequence`;
only then the log shows "✓ <pr> signed off (SIGNOFF_MERGE @ <sha8>) — ready
to merge … press 'g'"; the PR is NOT merged; `pm autostart status` reason
reads "signed off (fresh SIGNOFF_MERGE); stop-before-merge — press g".

R2. No repetition. Given R1's end state; When the TUI keeps running ≥ 60 s
(12+ scheduler polls); Then the ready line appears exactly once, no second
sign-off window opens, the TUI stays responsive (keys navigate normally).

R3. Manual merge after O. Given R1's end state; When the user presses `g`;
Then the merge succeeds through the normal gate (no `--no-signoff-check`)
and the PR becomes `merged`.

R4. A merges only after sign-off. Given an `A` target (optionally with a
dependent PR also in scope); When the sequence runs; Then the PR passes
through `sign_off`, "Auto-merge: <pr> signed off, merging" appears only
after the SIGNOFF_MERGE record exists, the PR becomes `merged`, the
dependent starts, and there is no merge-conflict / resolve window and no
"no sign-off verdict recorded yet" error anywhere in the log.

R5. Policy flip. Given an `O` PR already signed off (R1 end state); When the
user switches it to `A`; Then on a following scheduler pass it merges
(once), without re-running sign-off.

R6. Bounce routes. Given a target with `signoff` scripted
`["SIGNOFF_REQA","SIGNOFF_REVIEW","SIGNOFF_MERGE"]`; When the sequence runs;
Then: first verdict → "Sign-off routed <pr> back to QA (SIGNOFF_REQA)", PR
`qa`, a new QA run starts (not an instant re-hand-off from the old PASS),
the old sign-off window is gone; second → "…back to review
(SIGNOFF_REVIEW)", PR `in_review`, a fresh review loop runs, then QA again;
third → normal SIGNOFF_MERGE finish per policy. Each bounce clears the
previous `signoff` record; captures/report files are not deleted.

R7. Impl bounce and BLOCKED. Given a target with `signoff` scripted
`["SIGNOFF_IMPL","SIGNOFF_BLOCKED"]` and `A` policy; When the sequence runs;
Then IMPL → "…back to implementation (SIGNOFF_IMPL)", PR `in_progress`, the
impl window is relaunched (fresh), and the PR later re-enters review → QA →
sign-off; BLOCKED → red sticky "Sign-off BLOCKED for <pr> — needs a human
decision", PR stays `sign_off`, no merge attempt even under `A`,
`pm autostart status` reports it blocked/paused, and the line is not
repeated every poll.

R8. Manual approval & report-hash gate. Given R7's BLOCKED end state and a
`captures/<pr>/report.html` carrying `<meta name="pm-signoff-verdict"
content="SIGNOFF_MERGE">`; When the user runs `pm pr signoff record <pr>`;
Then the record becomes origin `manual` with a report hash and the `A`
driver merges on a later pass. Variant (fresh PR, `O` → then `A`): after
recording, edit report.html; Then the TUI logs one yellow "Not merging
<pr>: … report.html changed since the recorded approval …" and never calls
merge; `g` is also refused with the same reason.

R9. Stale HEAD. Given an `O` PR signed off at sha X; When the user commits a
new change on the PR branch (HEAD → Y); Then within a few polls the log says
"Sign-off for <pr> is stale (HEAD moved) — re-running", the old window is
retired, a new router window is launched, the new record has sha Y, and the
ready line is printed again with Y. `pm autostart status` shows "… stale
(HEAD moved); sign-off relaunches against current HEAD" while it is stale.
`g` before the new verdict is refused by the gate.

R9b. HEAD moves while the router is still running (before its first
verdict). Given an `O` (and separately an `A`) target whose sign-off router
was launched on HEAD X and is still in its fake `delay`; When the user
commits on the PR branch (HEAD → Y) before that router prints a verdict;
Then on the next scheduler pass the log says "Sign-off for <pr> is stale
(HEAD moved) — re-running", the old window is killed and one new router
window is launched on Y. The old run's verdict is never recorded: project.yaml
has no `signoff` record, there is no ready line, and for `A` no merge until
the new router's SIGNOFF_MERGE is recorded with sha Y. Only then does `O`
print its ready line `@ <Y8>` once, or `A` merge once. Each run is bound to
the HEAD it launched on (`<run>/signoff-<pr>.head` next to the transcript),
not to HEAD at verdict-read time. The same applies after a TUI restart that
reuses the running window: a run with no stamp, or one stamped with another
HEAD, is retired instead of being adopted.

R10. Window death & relaunch backoff. Given a PR in `sign_off` whose router
window is still running (long `delay`); When the user kills that window;
Then `pm autostart status` shows "no sign-off window; relaunches on next
scheduler pass" and a single new window appears within ~60 s (not one per
5 s poll); the verdict from the new window is recorded normally.

R11. Restart / late enable catch-up. Given a PR whose QA PASSed while it was
NOT an auto-start target (log: "QA PASS for <pr> — press i to sign off", PR
stays `qa`, no sign-off window); When the user then adds it as an `O`
target; Then the next scheduler pass hands it to sign-off and it finishes
like R1. Variant: quit and restart the TUI while a PR sits in `qa` with a
recorded PASS (or in `sign_off` mid-run) with auto-start re-armed; Then it is
picked up without re-running QA.

R12. Scope removal. Given a target in `sign_off` with the router running;
When the user removes it from auto-start (`pm autostart remove`); Then the
TUI stops acting on it (no recording, no hop, no merge), the window is left
alone, and `i` / `g` still work manually.

R13. skip_qa. Given `project.skip_qa: true` and an `O` target; When the
review loop PASSes; Then no QA runs, the PR goes `in_review → sign_off`, the
router runs and SIGNOFF_MERGE ends with the O ready line, which must be
visible on the TUI log line itself (not only in the `L` pane) even though it
lands within the 10 s "Review loop done" sticky; `pm autostart status` for a
skip_qa PR sitting in `qa` status says "skip_qa set; sign-off follows the
review PASS" (it is the qa-status row reason, not an in_review one). CLI: `pm pr signoff <pr>` on an `in_review` PR succeeds
(→ `sign_off`) with skip_qa true and is refused ("expected qa or sign_off")
with skip_qa false.

R14. CLI auto-sequence regression. Given a PR driven only by repeated
`pm pr auto-sequence <pr>` calls (no TUI auto-start) and fake verdicts;
When it reaches QA PASS and then sign-off; Then output lines are the same
shapes as on master (`sign_off …`, `ready_to_merge`, bounce lines), the
transcript lives under `transcripts/auto-sequence/<pr>`, and SIGNOFF_REQA
bounces once and then completes. (Known, tracked: its skip_qa branch still
prints `ready_to_merge (skip_qa)` without sign-off — pr-dd4f07b.)

R15. QA-run ownership across drivers / restarts. Given a QA run started by
a `pm pr auto-sequence` process (CLI) while the TUI is running; Then the TUI
never resumes/duplicates it (one verifier and one finalize pane per
scenario, one "QA complete", no stale "QA PASS — press i" after the CLI has
bounced the PR). Given a QA run started by the TUI itself; When the TUI is
restarted (Ctrl+R / quit + `pm session`) mid-run; Then the TUI resumes its
own run and completes it. Given a CLI-owned run whose CLI process has
exited (killed) mid-run; Then the TUI is allowed to pick it up (the run is
not stranded).

## Concurrency (shared resources)

Shared resources touched by the diff: `pm/project.yaml` (locked_update from
TUI scheduler, sign-off CLI, router, merge, autostart control); the tmux
window `signoff-<pr>` in the session + the per-PR launch lock
`~/.pm/workdirs/.signoff-launch-<session>-<pr>.lock`; the run-dir transcript
symlink `signoff-<pr>.jsonl`; runtime_state QA records; the fake-claude
scripted cursor; `captures/<pr>/report.html`; the autostart control socket.

C1. Two targets at once. Given two independent PRs, one `O` and one `A`,
added together; When both reach QA PASS near-simultaneously; Then each gets
exactly one sign-off window, each record carries its own branch's sha, the
`A` one merges and the `O` one stops with its ready line, project.yaml
stays parseable with no lost status/note fields, and the TUI never freezes
while the two background launches run.

C2. Manual vs scheduler launch race. Given a target just entering `sign_off`;
When the user simultaneously runs `pm pr signoff <pr>` (and/or presses `i`)
from another pane; Then only one `signoff-<pr>` window exists, and the
verdict it emits is still picked up (if the scheduler's transcript isn't
attached, the user can `pm pr signoff record` and the driver adopts it).

C3. Status polling during transitions. While C1 runs, a background loop
calls `pm autostart status --json` every second; Then every response is
valid JSON with a sensible phase/reason for each PR and no errors.

C4. CLI driver beside TUI driver. While the TUI drives a target, run the
`pm pr auto-sequence` loop (R14) on a different, non-targeted PR in the same
project; Then both finish correctly and neither driver acts on the other's
PR.

## Edge cases

* E1 Launch failure: make `pm pr signoff` fail non-zero (removing the
  workdir / no tmux exit 0 and do NOT produce the red line; use
  `chmod 0444 ~/.pm/workdirs/.signoff-launch-<session>-<pr>.lock`) → red "Sign-off
  launch failed for <pr>: …" line, retried at most once per ~60 s, TUI
  responsive.
* E2 A merge refused mid-merge (HEAD moved between gate and merge): logs
  "Merge of <pr> refused by the sign-off gate" and is NOT tracked as a merge
  conflict (no resolve window, PR not shown as conflict). Best effort —
  timing dependent; record as not-driven if it can't be produced.
* E3 Self-driving `zz t` QA reaching required passes on an in-scope PR logs
  "(n/n consecutive) — handing off to sign-off"; out of scope logs "press i
  to sign off" and does nothing else.

## Pass / Fail criteria

Pass = every Then above (including R9b under both O and A) observed on screen/CLI/project.yaml at 1c162a86+,
with artifacts saved. Fail = any "ready to merge" claim or merge attempt
without a fresh SIGNOFF_MERGE on the current HEAD; a gate refusal tracked as
a merge conflict; duplicate sign-off windows; repeated per-poll log spam; a
bounce that loops; TUI freezing during the launch; lost project.yaml data.

Reporting rules (supervisor):
* Every bug found must end with a fix in this PR, an existing/new bug PR
  (`pm pr list --plan bugs` first; known: pr-dd4f07b CLI skip_qa, pr-5410ae4
  orphaned router window after run-dir change, pr-7c32e44 dep row says
  "merge attempt failed" after gate refusal, pr-8e60aa9 auto-sequence
  terminal-verdict advance) or an explicit unresolved verdict. "Nonblocking"
  is not a reason to leave a bug untracked.
* Verification must be independent (separate verifier), not self-graded.
* The final report must disclose that this validation was supervised and
  that manual outer trust prompts were resolved by the supervisor.
* Do not count a supervisor/hand-launched sign-off as automatic hand-off
  success: the auto hand-off has to be observed launching the window itself.

## Ambiguities (resolved)

* R9 "stale (HEAD moved)" status reason lasts only until the next scheduler
  pass (<=5 s); sample `pm autostart status` in a 1 s loop started before
  the commit.
* fake-claude scripted cursors are per session type and shared by the TUI
  and CLI drivers: run scripted multi-verdict sequences alone; use
  single-verdict configs when two drivers run concurrently.
* A user Ctrl+R restart leaves auto-start off; re-add targets after it.

* "HUMAN route": there is no SIGNOFF_HUMAN verdict; the human route is
  SIGNOFF_BLOCKED (stay in sign_off, sticky log, no merge).
* skip_qa: the TUI routes review PASS to sign-off (R13); the CLI
  auto-sequence skip_qa branch is out of scope (tracked in pr-dd4f07b).
* A manually launched `i` window has no transcript in the TUI run dir, so
  the driver shows it as running until `pm pr signoff record`; that is
  intended (pr-5410ae4 covers the different orphan-after-run-dir-change case).
* `test_hook_events::test_installer_writes_standalone_receiver` was reported
  failing by the implementer but passes in the planning environment
  (environment-dependent); not a finding for this PR.

## Scenario groups (compact index — use verbatim in every QA planning pass)

Three scenario groups cover every required story. Planners emit exactly
these three scenarios, numbered from the run's first scenario number, in
order A, B, C, with each STEPS line pointing back to this section. Each
group runs in its own container. All three use INSTRUCTION
`tui-manual-test.md` and ARTIFACT `tmux-screen-recording.md,
cli-recording.md`.

### Common setup (S0, every group)

* Install pm editable from the PR clone (`pip install -e`,
  `export PYTHONPATH=<clone>`). `pm which` must point at the clone, and
  `git log -1` in the clone must show 1c162a86 or a descendant. Use a
  private `TMUX_TMPDIR`, and put fake-claude first on PATH.
* Throwaway git project, `pm init --backend local --no-import`, one
  `pm pr add` per story PR, and a minimal `pm/specs/<id>/qa.md` per PR.
  Once a PR's workdir exists, make a real commit on its branch before
  it reaches sign_off (unless the story moves HEAD on purpose).
* `pm session`, then record the TUI through a grouped view with
  asciinema. Use a separate `cli` window in the test session for every
  pm command, and check focus on the main session.
* Evidence at each key point: `pm tui view`, the `L` log
  (`~/.pm/debug/<tag>.log`), `tmux list-windows` (window ids),
  `pm pr list`, `pm autostart status [--json]`, and read-only snapshots
  of `pm/project.yaml` (status, signoff verdict/sha/origin/report_hash).
  Save captures under the per-PR captures dir, with a manifest.
* Never edit project.yaml by hand after setup (the skip_qa toggle in
  Group C is setup). Never hand-launch sign-off in an auto hand-off
  story: the TUI has to be seen launching `signoff-<pr>` itself.
  fake-claude cursors are shared, so run multi-verdict scripts alone.
* Every failed Then ends in a fix in this PR (verdict NEEDS_WORK), a bug
  PR (`pm pr list --plan bugs` first; the known ones are listed under
  Reporting rules), or an explicit unresolved verdict.

### Group A — Hand-off, routing, approval and restart catch-up

Covers R1, R2, R3, R4, R5, R6, R7, R8, R11, E3, plus the bug-fix
reproduction suite.

* A0 Repro tests. In the clone, `pytest tests/test_tui_signoff_handoff.py
  tests/test_signoff.py tests/test_qa_resume.py -q` passes. Record the
  summary line.
* A1 (R1, R2, R3). Run an O target from pending with baseline fake
  verdicts (signoff `[{"verdict":"SIGNOFF_MERGE","delay":15}]`). Every
  Then of R1 must hold, and the ready line has to be visible on the TUI
  log line itself. Then R2: 60 s or more with no repeat line, the same
  window id, and j/k still navigating. Then R3: `g` merges through the
  normal gate.
* A2 (R4). An A target with a dependent PR also in scope. Each passes
  through sign_off, "Auto-merge: … signed off, merging" comes only after
  the record, both merge in order, and there is no conflict or resolve
  window and no "no sign-off verdict recorded yet".
* A3 (R5). An O target that is already signed off is switched to A with
  `pm autostart add --auto-merge`. It merges once, with no router re-run.
* A4 (R6). signoff scripted `["SIGNOFF_REQA","SIGNOFF_REVIEW",
  "SIGNOFF_MERGE"]`: every R6 Then. A fresh QA or review run follows
  each bounce, the old window is gone, the record is cleared, captures
  are kept, and nothing loops.
* A5 (R7, R8). signoff scripted `["SIGNOFF_IMPL","SIGNOFF_BLOCKED"]`
  under A. IMPL relaunches impl fresh. BLOCKED gives a single red sticky
  line, no merge, and a blocked status reason. Then R8: a manual
  `pm pr signoff record` with a report.html meta verdict gives origin
  manual and a report hash, and the A driver merges. Variant on a fresh
  PR: edit report.html after recording. The yellow "report.html changed"
  refusal appears once, and `g` is refused for the same reason.
* A6 (R11, E3). A PR whose QA PASSes outside auto-start logs "press i
  to sign off", including the `zz t` "(1/1 consecutive)" form, and no
  window opens. Arming it with O hands it to sign-off with no QA re-run.
  Restart variant: Ctrl+R while a PR sits in `qa` with a recorded PASS,
  and again while it is in `sign_off` mid-run with HEAD unchanged. After
  re-arming, each continues without re-running QA. The running window is
  adopted (same id, no "stale" line) and its verdict is recorded once.
  E3 in-scope: a `zz t` run that reaches its required passes on a target
  logs "(n/n consecutive) — handing off to sign-off".

### Group B — HEAD freshness and failure recovery

Covers R9, R9b, R10, R12, E1, E2.

* B1 (R9b, O and A at the same time). signoff
  `[{"verdict":"SIGNOFF_MERGE","delay":60}]`, with an O target and an A
  target started together and `pm autostart status --json` sampled every
  second. While both routers are still in their delay (before any
  verdict), commit on each branch (X → Y). Expected:
  * One "Sign-off for <pr> is stale (HEAD moved) — re-running" per PR.
  * The old window is killed and exactly one new window launches per
    PR, with a new id. `<run>/signoff-<pr>.head` holds Y.
  * Nothing is recorded, there is no ready line, and there is no merge
    or merge attempt until the new router's SIGNOFF_MERGE is recorded
    with sha Y.
  * Then O's ready line shows `@ <Y8>` once, and A merges once with the
    Y commit included.
  * Every status sample is valid JSON, and project.yaml loses no data.
* B2 (R9b restart). With an O target's router running on X (long
  delay), restart the TUI and commit X → Y right after issuing the
  restart, while the new TUI boots. Drive it twice: (a) `pm tui restart
  --breadcrumb` (keeps targets + run id); (b) Ctrl+R then re-arm (new
  autostart run dir; since b8e97482 the live run is adopted into it
  first). Either way the old run is retired with one "stale" line, not
  recorded, one new window launches on Y, and the final record carries
  sha Y with one ready line. A PR stuck on "sign-off review running"
  forever after (b) is a regression of b8e97482, not pr-5410ae4.
  Also check the `L` log shows "signoff: launching router" only for
  real launches (a1d4324b), never once per poll during backoff.
* B3 (R9). With an O target signed off at X and a 1 s status loop
  already running, commit (→ Y). Expected:
  * A "stale (HEAD moved) — re-running" line, the old window retired,
    and a new window launched without taking focus.
  * The status shows the stale reason.
  * `g` before the new verdict is refused by the gate.
  * The new record has sha Y, and the ready line `@ <Y8>` appears once.
* B4 (R10). signoff delay 120. Kill the running window. The status
  shows "no sign-off window; relaunches on next scheduler pass", one new
  window appears after about 60 s (never one per poll, never two at
  once), and its verdict is recorded normally.
* B5 (R12). An A target in sign_off with its router running is removed
  with `pm autostart remove`. The window is left alone and nothing is
  recorded, routed or merged. `i` switches to the window, and `g` is
  refused until a manual `pm pr signoff record`, after which `g` merges.
  It never merges on its own.
* B6 (E1). `chmod 0444` the PR's
  `~/.pm/workdirs/.signoff-launch-<session>-<pr>.lock`. A red "Sign-off
  launch failed for <pr>: …" line appears, retries come at most about
  once every 60 s for about 3 minutes, and the TUI stays responsive.
  After restoring 0644, one window launches, is recorded at HEAD, and
  the ready line appears once.
* B7 (E2). Hold `~/.pm/workdirs/.merge-<repo_id>-<pr>.lock` with flock
  while an A target's merge is pending, commit on its branch, then
  release. Expected:
  * "Merge of <pr> refused by the sign-off gate" is logged.
  * It is never tracked as a conflict: no resolve window, and no
    conflict phase in 1 s status samples.
  * Sign-off re-runs on the new HEAD and the PR merges once. If the
    timing cannot be produced, record E2 as not driven.

### Group C — skip_qa, CLI driver, concurrency and QA-run ownership

Covers R13, R14, R15, C1, C2, C3, C4.

* C-a (R13). `project.skip_qa: true`, with an O target. The review PASS
  leads to sign_off with no QA window or run dir, and the record is at
  HEAD with origin auto-sequence. The ready line is visible on the TUI
  log line even though it lands inside the "Review loop done" sticky,
  and it appears once. A skip_qa PR in `qa` status shows "skip_qa set;
  sign-off follows the review PASS" and starts no QA run.
  `pm pr signoff` on an in_review PR succeeds under skip_qa true. Under
  false it is refused with "expected qa or sign_off" and a non-zero
  exit, and the status is unchanged.
* C-b (R14, R15 CLI-owned). With the TUI open and signoff scripted
  `["SIGNOFF_REQA","SIGNOFF_MERGE"]`, drive one PR only by repeated
  `pm pr auto-sequence <pr>`. The line shapes match master (sign_off,
  `sign_off: re-qa`, a new QA dir, ready_to_merge, plus extra ticks with
  no new window). The first window is killed at the bounce, the final
  record is at HEAD, and transcripts sit under
  `transcripts/auto-sequence/<pr>`. The TUI never resumes the CLI's QA
  runs: one verifier pane and one finalize pane per run, one "QA
  complete", and no stale "press i" after the bounce.
* C-c (C1, C3). Run single-verdict configs alone. An O target and an
  A target are added together, and `pm autostart status --json` is
  polled every second throughout. Expected:
  * One window per PR, each record carrying its own sha.
  * A merges only after its record, with no resolve window. O's ready
    line is visible on screen, not overwritten by A's merge lines.
  * Keys render within about 1 s during the launches.
  * project.yaml stays parseable with notes and statuses intact.
  * Every status response is valid JSON with a sensible phase and
    reason, and no errors.
* C-d (C2). As a target flips to sign_off, run `pm pr signoff <pr>` in
  the CLI and press `i` at the same moment (retry on a spare PR if the
  timing misses). Expected:
  * Only one `signoff-<pr>` window ever exists.
  * The manual path reports switching to the existing window or a
    launch in flight.
  * The verdict is recorded, and a manual `record` is adopted if the
    transcript isn't attached.
  * The ready line appears once.
* C-e (C4). The TUI drives an A target while a CLI loop drives a
  different, non-targeted PR. Both finish correctly, and neither driver
  logs or acts on the other's PR. The CLI PR's QA has one verifier, one
  finalize and one completion, and each record sits at its own HEAD.
* C-f (R15 own run, TUI). With a delayed qa_scenario PASS, an O target's
  QA run is mid-scenario. Ctrl+R and re-arm. The TUI resumes its own run
  (no abandonment, no second run), it completes once, and the PR goes on
  to sign-off and the ready line.
* C-g (R15 dead CLI owner). Start `pm pr auto-sequence <pr>` until its
  QA run is in flight, kill that CLI process and its QA child, then arm
  the PR as an O target. Within a few passes the TUI recovers the run
  (resume, or a fresh run) with no duplicate panes, and the PR reaches
  QA PASS, the TUI-launched sign-off and the ready line. A PR stranded
  in `qa` is a finding.
