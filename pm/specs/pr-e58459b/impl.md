# Spec: Auto-sequence chain — TUI keypress + programmatic CLI

## Context

The TUI already chains `start → review → QA → merge` via the `auto-start` mode
(toggled with `A` in `pm_core/tui/app.py`, implemented in
`pm_core/tui/auto_start.py`). The chain is event-driven via
`pm_core/tui/review_loop_ui._poll_impl_idle` (impl-idle → in_review),
`pm_core/tui/review_loop_ui._maybe_start_qa` (review PASS → QA), and
`pm_core/tui/qa_loop_ui._on_qa_complete` → `_trigger_auto_merge` (QA PASS →
merge).

This PR adds a per-PR "auto-sequence" flow that:
- runs the chain on a **single PR** (not its dep tree),
- **stops before merge** (leaves the PR ready-for-merge after QA PASS), and
- is invokable both from the TUI (keypress, human use) and from the CLI
  (`pm pr auto-sequence <id>`, watcher use).

## 1. Requirements

### R1. TUI keypress chains start → done → QA on a single PR, halting at pause conditions and stopping before merge.

- Add a new keybinding to `pm_core/tui/app.py` (`BINDINGS` list around l.123)
  and a corresponding `action_auto_sequence_pr` handler that delegates to a new
  function in `pm_core/tui/auto_start.py`.
- The new function enables the auto-start mode the same way `toggle()` does
  (sets `app._auto_start = True`, `app._auto_start_target = selected_pr_id`,
  generates a `_auto_start_run_id`, creates the transcript dir, calls
  `check_and_start`).
- It additionally registers the selected PR in a new
  `app._stop_before_merge: set[str]` so the merge step is suppressed when QA
  passes.

### R2. The chain halts at existing pause conditions.

The relevant pause points are already implemented and are reused unchanged:
- **idle-no-spec** — `_poll_impl_idle` in `review_loop_ui.py` resets the idle
  flag when `pr.spec_pending` is set (l.715–720); auto-review does not fire,
  so the chain pauses in `in_progress`.
- **review INPUT_REQUIRED** — `review_loop.run_review_loop_sync` sets
  `state.input_required = True` and waits for a follow-up verdict in the same
  pane (l.312–342). The chain pauses; `_maybe_start_qa` is not called.
- **QA INPUT_REQUIRED** — `qa_loop_ui._on_qa_complete` logs the pause and
  does not transition to merge (l.383–388).
- **merge** — suppressed for PRs in `app._stop_before_merge` (R1 hooks into
  `_maybe_auto_merge` in `review_loop_ui.py`).

### R3. Suppress the auto-merge step for auto-sequence PRs.

Modify `pm_core/tui/review_loop_ui._maybe_auto_merge` (entry point used by
both the review→merge skip-QA path and the QA→merge path via
`_trigger_auto_merge`) to short-circuit when the PR is in
`app._stop_before_merge`. Log a clear "ready to merge" message instead of
launching the merge window. Leave the PR's status at `qa` (or `in_review` if
`skip_qa` is set) so the user can finish the merge with `g` or `pm pr merge`.

### R4. `pm pr auto-sequence <pr_id>` CLI advances the chain non-interactively.

Add a new subcommand to `pm_core/cli/pr.py`. Each invocation examines the PR's
current state and advances it by **one phase** (idempotent, non-blocking):

- **pending** → invoke `pr_start` with `background=True` and a deterministic
  transcript path. Print `started`. Exit 0.
- **in_progress** → look for the impl tmux window/pane via
  `_pr_display_id`. If absent, re-launch via `pr_start --background` (window
  may have been killed); print `restarted`. Else use `PaneIdleTracker` to
  poll once for idle (registering the pane against the deterministic
  transcript path):
  - `pr.spec_pending` set → print `paused: spec_pending`. Exit 0.
  - idle → invoke `pr_review` with `background=True`. Print
    `advanced: in_review`. Exit 0.
  - not idle → print `running: implementation`. Exit 0.
- **in_review** → use `extract_verdict_from_transcript` against the latest
  review-iteration transcript:
  - `PASS` → if `skip_qa`, print `ready to merge` (R3) and stop. Else
    transition status to `qa` and start a QA loop via the CLI/background
    helper. Print `advanced: qa`. Exit 0.
  - `NEEDS_WORK` → relaunch a fresh review iteration (`pr_review --fresh
    --review-loop --review-iteration N+1`). Print `review: needs_work,
    retrying`. Exit 0.
  - `INPUT_REQUIRED` → print `paused: input_required`. Exit 0.
  - no verdict and review window absent → invoke `pr_review --background`
    to (re-)launch. Print `advanced: review_relaunched`.
  - no verdict and window present → print `running: review`. Exit 0.
- **qa** → check QA verdict via the QA status helper or transcript:
  - `PASS` → print `ready to merge` and stop (R3). Exit 0.
  - `NEEDS_WORK` → transition status to `in_review`, relaunch review.
    Print `qa: needs_work, returning to review`. Exit 0.
  - `INPUT_REQUIRED` → print `paused: input_required`. Exit 0.
  - running → print `running: qa`. Exit 0.
- **merged** → print `merged`. Exit 0.

The CLI does not require the TUI to be running. It does require a `pm` tmux
session for launching impl/review/QA windows (this matches the existing per-
phase commands).

### R5. Reuse per-phase flows.

The CLI invokes the existing `pr_start`, `pr_review` (with `--background`),
and the QA-loop launcher used by `start_qa` directly — no new orchestration
logic, just dispatch.

### R6. Tests.

- Unit test the CLI dispatch (with a mock PR and mocked `pr_start` /
  `pr_review` / QA launcher) covering each of the seven status branches.
- Existing review/QA/merge tests are not impacted.

## 2. Implicit Requirements

- **Deterministic transcript paths.** Without the TUI's run-id-scoped
  transcript dir, the CLI needs predictable transcript paths so successive
  ticks find the same files. Use
  `<pm_root>/transcripts/auto-sequence/<pr_id>/{impl,review-iN,qa}.jsonl`.
  The TUI keypress flow keeps the existing run-id-scoped path because it
  shares state with the rest of the auto-start session.
- **Iteration counter for review.** Successive review iterations need an
  incrementing index. Persist on the PR entry as `auto_seq_review_iter` (or
  recover by counting transcript files). Simpler: use a counter on the PR
  entry.
- **PaneIdleTracker requires a session_id.** The transcript symlink must
  resolve before registering. The CLI registers on each tick after the
  symlink has been written (i.e. only after `pm pr start` has run).
- **No persistence of `_stop_before_merge`** across TUI restarts. The
  breadcrumb mechanism (`save_breadcrumb` / `consume_breadcrumb`) is updated
  to round-trip the set so that a merge-restart doesn't accidentally
  auto-merge an auto-sequence PR.

## 3. Ambiguities (resolved)

- **Q: Is the CLI blocking (waits to next pause) or single-tick (advances one
  phase)?**
  Resolved as **single-tick / idempotent**: matches the framing "watcher
  sessions invoke each tick to advance a PR through the next phase". A
  blocking CLI would lock up the watcher pane while a review or QA run
  takes minutes.
- **Q: Which key to bind?**
  Resolved as `O` (Orchestrate / auto-sequence). Available; no conflict in
  `BINDINGS`. Marked `show=True` in the TUI footer.
- **Q: What if the user presses `O` again on the same PR?**
  Resolved: re-arms the auto-sequence — `_stop_before_merge` is a set, so
  re-adding is a no-op; auto-start is already on, so `toggle()` is not
  invoked again.
- **Q: How does the CLI decide whether QA was started by auto-sequence vs.
  by the TUI?**
  Resolved: the CLI does not care. It just inspects state and acts.
  Concurrent TUI activity simply means the chain may already have advanced
  and the next tick will reflect that.

## 4. Edge Cases

- **Watcher session interferes with TUI auto-start mode.** The TUI's auto-
  start machinery sets PR-level state on disk; the CLI also reads/writes
  state on disk. Both paths use `store.locked_update`, so transitions are
  serialised. No new locking needed.
- **PR has unmerged dependencies and CLI is invoked.** `pr_start` already
  exits non-zero with a clear message. The CLI surfaces this verbatim.
- **No `pm` tmux session.** `pr_start` / `pr_review` already error out.
  Surface the error.
- **Review window was killed manually mid-loop.** The CLI's "no verdict and
  window absent" branch re-launches. This is acceptable: the watcher
  recovers.
- **PR has `skip_qa` set.** The CLI's `in_review` PASS branch checks the
  project setting (matching `_maybe_start_qa`'s behaviour) and stops at
  ready-for-merge — i.e. `_stop_before_merge` semantics still hold.
- **Spec pending review (V key flow).** `pr_start` already blocks on this;
  the CLI surfaces the error. Auto-sequence cannot bypass spec approval.
