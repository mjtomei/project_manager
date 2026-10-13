# pr-488ac6d — TUI auto-sequence: QA PASS must hand off to sign-off

## Root cause (grounded)

`pm_core/tui/qa_loop_ui.py::_on_qa_complete` handles a QA PASS for an in-scope
PR by logging "QA PASS … — ready to merge" and calling `_trigger_auto_merge` →
`pm_core/tui/review_loop_ui.py::_maybe_auto_merge`.  `_maybe_auto_merge` checks
`app._stop_before_merge` first (O policy) and returns with the green
"✓ <pr> ready to merge (press 'g')" line, or (A policy) calls `_attempt_merge`
→ `pm pr merge`.  Nothing in the TUI ever moves the PR `qa → sign_off`,
launches the sign-off router, reads its verdict or records it.  So:

* O: PR stays `status=qa`, `signoff=None`, but the log claims ready-to-merge.
* A: `pm pr merge` hits the #226 sign-off gate (`cli/pr.py` "no sign-off
  verdict recorded yet"), `_attempt_merge` returns False and
  `_maybe_auto_merge` adds the PR to `app._pending_merge_prs` — i.e. it is
  tracked as a merge *conflict* waiting for a resolve window that never opens.
* skip_qa=true takes the same `_maybe_auto_merge` path from
  `_maybe_start_qa`, so it has the same defect (reported as broader than
  skip_qa: reproduced with skip_qa=false via the QA path).

The CLI driver (`pm pr auto-sequence`, `cli/pr.py::pr_auto_sequence`) already
has the full state machine: `qa`+QA PASS → `sign_off` + launch router;
`sign_off` → adopt fresh record / retire+relaunch stale run / read transcript
verdict and record it (origin auto-sequence) / relaunch a dead window /
`decide_signoff_hop` + `apply_signoff_hop` → ready_to_merge | blocked | qa |
review | impl.

## Requirements

R1. **Shared sign-off step core.**  Extract the `sign_off` branch decision
logic of `pr_auto_sequence` into `pm_core/signoff.py::step_signoff(root,
pr_entry, session, tdir, …)` returning a `SignoffStep(action, hop, verdict,
stale)` where `action ∈ {"launch", "running", "hop"}`.  It performs the
state-side effects exactly as today (adopt fresh record; stale record →
retire window+transcript and clear record → launch; transcript verdict →
`record_signoff_verdict(origin="auto-sequence", sha=current HEAD)`; no verdict
→ launch if the window is gone else running; verdict → decide+apply hop;
bounce → retire window+transcript).  Launching stays with the caller.  The
helpers it needs (`signoff_transcript_verdict`, `signoff_window_pane`,
`retire_signoff_run`) move into `signoff.py`; the CLI keeps
`_check_signoff_verdict` / `_signoff_window_pane` / `_retire_signoff_window`
as thin delegates and passes them in so existing patch points keep working.
`pr_auto_sequence` output strings are unchanged.

R2. **TUI sign-off driver** — new `pm_core/tui/signoff_ui.py`:
  * `start_signoff(app, pr_id)`: for an auto-start-enabled, in-scope PR in
    `qa` (or `in_review` when `project.skip_qa`), transition it to `sign_off`
    (guarded, `_record_status_timestamp`), reload, log the hand-off, then
    run one `step`.
  * `step(app, pr_id)`: for an in-scope `sign_off` PR, call
    `signoff.step_signoff` with the TUI transcript dir
    (`auto_start.get_transcript_dir(app)`, file `signoff-<pr>.jsonl`) and
    act:
      - `launch` → `pm pr signoff --background --transcript <tdir>/signoff-<pr>.jsonl <pr>`
        (background: never steals focus).  Run as an async worker
        subprocess (argv list, like `auto_start._start_pr_quiet`), never the
        synchronous `pr_view.run_command` — that blocks the event loop and
        kills launches slower than 30 s (container start).  Failures are
        logged; the 60 s relaunch backoff covers the window not being up
        yet, and a launch still in flight is never stacked with a second one.
      - `running` → nothing.
      - hop `ready_to_merge` (fresh SIGNOFF_MERGE on current HEAD) →
        `_maybe_auto_merge` (O: stop with the ready line; A: merge).
      - hop `blocked` (SIGNOFF_BLOCKED, the human route) → red sticky log,
        PR stays `sign_off`, nothing else.
      - hop `qa` (SIGNOFF_REQA) → drop stale `_qa_loops` entry + the
        runtime_state QA record, `qa_loop_ui.start_qa`.
      - hop `review` (SIGNOFF_REVIEW) → drop stale `_review_loops` entry,
        start a fresh TUI review loop (`review_loop_ui._start_loop`).
      - hop `impl` (SIGNOFF_IMPL) → drop stale `_review_loops` entry,
        `pm pr start --fresh --background` (relaunch the agent; impl-idle
        poller then drives review as usual).
  * `advance_all(app, prs)`: scheduler pass over in-scope PRs — `sign_off`
    PRs → `step`; `qa` PRs with no `_qa_loops` entry whose recorded
    runtime_state QA verdict is PASS → `start_signoff` (restart / missed
    callback catch-up; replaces the pr-0b87a97 PASS hold as the forward
    path).  Called from `auto_start.check_and_start` and from the 1 s poll
    timer every 5th tick (with `_poll_impl_idle`) so verdicts are picked up
    promptly.

R3. **QA PASS wiring.**  `_on_qa_complete` PASS (legacy auto-start path and
self-driving `zz t` once required passes are reached, both only when in
scope) calls `_trigger_signoff` → `signoff_ui.start_signoff` and logs
"QA PASS for <pr> — handing off to sign-off" instead of "ready to merge".
Out of scope: message says "press i to sign off".

R4. **Merge gate in `_maybe_auto_merge`.**  Before the stop-before-merge
check and before any `pm pr merge`, require that the exact `pm pr merge`
gate passes — `signoff.merge_gate_refusal(pr, head_sha(workdir))` is None
(fresh SIGNOFF_MERGE, plus the report.html hash of a manual approval).  The
CLI merge gate calls the same helper.  A signed-off `sign_off` PR the gate
still refuses (report changed since a manual approval) gets a one-time
yellow log with the gate's reason, never a merge attempt.  If
absent: PR in `qa`/`in_review` → `signoff_ui.start_signoff` (covers
skip_qa's review-PASS call); PR in `sign_off` → no-op (driver owns it).  O
then reports "✓ <pr> signed off (SIGNOFF_MERGE @ <sha>) — ready to merge
(press 'g')" only after a fresh SIGNOFF_MERGE.  A merges only then.  If a
merge attempt fails and the gate no longer holds (HEAD moved / report
changed mid-merge), do **not** add to `_pending_merge_prs` (it is not a
conflict) — log it.

R5. **No repeat actions.**  The poller re-evaluates every 5 s; terminal
outcomes (ready_to_merge, blocked) act once per `(verdict, sha, policy)`
(`app._signoff_acted`).  A policy flip (O→A) re-acts; a new HEAD re-acts.
PRs in `_pending_merge_prs` are skipped (merge-conflict tracking owns them).

R6. **Status reasons** (`autostart_state._derive`, per the pr-0b87a97 note):
qa PASS / skip_qa reason → "…; awaiting sign-off (hand-off on next scheduler
pass)"; auto-policy signed-off → "…; auto-merge pending"; sign_off without
verdict and no window → "sign-off window gone; relaunches on next scheduler
pass"; stale → "…stale (HEAD moved); sign-off relaunches against current HEAD".

R7. **`pm pr signoff` accepts `in_review` when `project.skip_qa`** (there is
no QA stage to come from); otherwise unchanged.

R8. **Tests**: TUI integration test driving a real project.yaml through
QA PASS → `sign_off` (+ launch command with transcript) → transcript
SIGNOFF_MERGE recorded at current HEAD → O stops with the ready line and no
`pm pr merge`; A calls `pm pr merge` exactly then; plus REQA/REVIEW/IMPL/
BLOCKED routing, stale-HEAD relaunch, gate-not-conflict, scope, dedupe.
Update existing tests whose expectations encoded the old shortcut.

## Implicit requirements

* Sign-off never merges itself and records are only written by the
  auto-sequence path (origin `auto-sequence`) or `pm pr signoff record`
  (manual).  The TUI driver is an auto-sequence driver, so it may record
  transcript verdicts — only for runs it launched (its own transcript path).
  A manually launched `i` window has no transcript in the TUI dir; it shows
  as "running" until the reviewer records approval, which is then adopted.
* Report evidence is untouched: retirement removes only the window and the
  TUI's transcript symlink; captures/report.html stay.
* `step` re-checks enabled + scope on every call (removal mid-flight).
* The launch command is the existing `pm pr signoff` so container mode,
  model resolution, pane registry and the launch lock are reused.
* After every status write the TUI reloads (`app._load_state()`).

## Ambiguities (resolved)

* "HUMAN route" — there is no SIGNOFF_HUMAN verdict; the human/escalation
  route is SIGNOFF_BLOCKED.  Preserved: PR stays in sign_off, log tells the
  user it needs a decision, no merge.
* skip_qa: the gate requires a sign-off, so skip_qa review PASS also routes to
  sign-off (from `in_review`, R7).  The CLI auto-sequence's skip_qa branch
  ("ready_to_merge (skip_qa)") is left as is — out of scope, noted.
* Transcript location: TUI uses its run dir (`get_transcript_dir`) like
  review/QA/merge; the CLI keeps `transcripts/auto-sequence/<pr>`.
* `A` on a PR already signed off (fresh SIGNOFF_MERGE) merges on the next
  scheduler pass — that is "A may merge only then".

## Edge cases

* TUI restart between QA PASS and hand-off: PR is `qa` with recorded PASS and
  no `_qa_loops` entry → `advance_all` hands off.
* Re-qa after REQA: runtime_state QA PASS record is cleared before `start_qa`
  so the catch-up path can't immediately re-hand-off.
* HEAD moves while in sign_off (stale fresh record) → retire + relaunch; a
  fresh SIGNOFF_MERGE recorded earlier no longer satisfies the gate.
* Sign-off window killed with no verdict → relaunched by the next pass.
* PR leaves scope / auto-start turned off → driver stops acting (window keeps
  running; `i`/`g` still work manually).
* `g` merge path is unchanged and already gated by `pm pr merge`.

## Verdict binding to the launched revision (QA s2 follow-up)

`step_signoff` used to record a transcript verdict with `sha` = HEAD at
verdict-*read* time. A commit that landed while the router was still running
(before its first verdict) was therefore stamped as reviewed, and the shared
gate let `A` merge unreviewed code. `launch_signoff_window` now writes
`<run>/signoff-<pr>.head` next to the `--transcript` symlink when it creates
a new window. It runs inside the per-PR launch lock. The existing-window fast
path does not restamp, because a reused run keeps the revision it launched
on. `step_signoff` retires the run and returns `launch(stale=True)` before
anything is recorded when that stamp differs from the current HEAD, or when a
transcript verdict exists without a stamp (e.g. a run started by an older
pm). This holds for both drivers (TUI scheduler and `pm pr auto-sequence`),
whether the run is still going or has finished, and across a TUI restart.
`retire_signoff_run` removes the stamp together with the transcript. With an
unknown HEAD (workdir missing) the old behaviour stays, so the forced stale
relaunch cannot loop. Tests: `test_verdict_from_run_launched_on_old_head_is_not_recorded[O|A]`,
`test_head_moved_before_verdict_retires_running_run`,
`test_restart_does_not_adopt_run_of_another_head`, CLI
`test_verdict_of_run_launched_on_old_head_not_recorded`, and the
`TestWindowLaunchWorkdir` stamp tests.
