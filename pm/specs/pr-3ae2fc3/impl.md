# Implementation spec — pr-3ae2fc3: Add spec-review pauses to autostart

## 1. Requirements

### R1. Target option `--review-specs`
- `pm autostart add <ids> --review-specs` (`pm_core/cli/autostart.py:autostart_add`) and the
  command bar `autostart add <ids> --review-specs` (`pm_core/tui/auto_start.py:handle_command`)
  set a boolean `review_specs` on the target record (`autostart_state.REVIEW_KEY = "review_specs"`),
  like `wait_for_merge` (`WAIT_KEY`). Composes with any one merge-policy flag
  (`--wait-for-merge`, `--auto-merge`, `--stop-before-merge`); it is not a policy and never conflicts.
- `--no-review-specs` clears it on a re-add. Re-adding without either flag keeps the current
  value (same rule as policies). `--review-specs` together with `--no-review-specs` → `conflicting_flags`, nothing changes.
- `add_targets(..., review_specs: bool | None)` reports the change. A re-add that flips only the
  option is `options_changed`; flipping both policy and option is `policy_changed` (with
  `previous_policy`). Each change entry carries `review_specs`.
- Target listings: `pm autostart list` (text `+review-specs`, JSON `review_specs`), command-bar
  `autostart list` (`_list_summary`: `(review-specs)`), status `targets[].review_specs`,
  `_print_changes` and the "targets +=" confirmation.
- Restart: the flag rides on the target record, which `targets_to_breadcrumb` /
  `targets_from_breadcrumb` already round-trip; nothing else needs persisting.

### R2. Derived review requirement (no global change)
- `autostart_state.spec_review_holds(prs, targets) -> {pr_id: [target ids]}`: the union of the
  closures (target included, merged/closed excluded) of every active target with
  `review_specs`. This is the same shape as `merge_holds`, so shared prerequisites need review when
  *any* active target asks for it, and removing a target releases only what that target caused.
- `auto_start.spec_review_required(app, pr_id)`: true when auto-start is enabled, *pr_id* is in scope, and
  (it is in `spec_review_holds` **or** `spec_gen.pr_spec_mode(pr) == "review"`). The second clause covers explicit per-PR
  `review_spec: true` and the global `spec-mode=review`. Neither `review_spec` nor the
  global setting is ever written.
- `spec_gen.pr_spec_mode(pr, review=False)`: `review=True` forces `"review"`. This is threaded through
  `spec_generation_preamble(pr, phase, root, review_gate=False)`, `_build_spec_prompt` and
  `generate_spec(..., review=False)`. All of these default to the current behaviour.
  `format_spec_for_prompt` is deliberately unchanged: under the gate an existing spec is always
  approved before its step runs, so a review-mode "ask for approval" note would stall the agent.

### R3. Inline spec → `spec_pending`
- New `spec_gen` helpers:
  - `spec_location(pr, phase) -> Path | None`: the file `get_spec` reads (the workdir copy first, then the root).
  - `is_spec_approved(pr, phase)`: checks `pr["spec_approved"][phase]`.
  - `needs_spec_approval(pr, phase)`: true when the spec exists, has no approval record, and no spec is pending.
  - `mark_spec_pending(root, pr_id, phase, source="autostart")`: under the lock, sets
    `spec_pending = {phase, generated_at, review: True, source}`. It returns False when a pending
    spec already exists, so it never overwrites one.
- `approve_spec` now also records `spec_approved[phase] = <iso>`. This is needed so that later QA runs and
  sign-off bounces do not ask again.
  `generate_spec` drops that phase's record when it writes new content (e.g.
  `pm pr spec --regenerate`), so a regenerated spec is reviewed again under the gate.
- Concurrent approve / regenerate / reject: `approve_spec(..., reviewed_text=)` records the approval only
  if, under the lock, the PR still has the pending record and spec text the reviewer saw (else
  `spec-approve` prints `No pending spec review for <id>.` or, when the text changed, refuses with exit 1).
  `generate_spec` writes under the lock and raises `SpecApprovedMeanwhile` (regenerate/reject exit 1,
  approved spec kept) when an approval landed after it loaded. The approval message is sent by
  `notify_spec_approved_if_current` under the lock, only while the approval still stands for that text.
- `set_spec` writes to the workdir copy when that file exists. Otherwise an approve-with-edits or a
  reject regeneration lands in `<root>/specs` while `get_spec` keeps reading the stale workdir copy.
- Gate-aware review-mode preamble (`review_gate=True`): it keeps the existing review text and adds
  that approval is recorded only through `pm pr spec-approve <id>` / `V`. The agent must wait for the
  "spec approved" message before doing the work.
- `pm pr start --review-spec` (hidden) passes `review_gate` into `prompt_gen.generate_prompt`.
  `auto_start._start_pr_quiet` adds the flag when `spec_review_required`, and so does the TUI's manual
  start (`pr_view.start_pr`) and a command-bar `pr start <id>` (`pr_view._with_review_spec`) for an
  in-scope PR. Known gap (filed as pr-74c4182): the PR Actions picker's start row and a shell
  `pm pr start` don't add the flag, so the agent gets the plain spec prompt. The gate still holds the
  spec (`S impl`) and blocks the review transition until approval.
  `generate_qa_planner_prompt(..., review_gate=)` gets it from `QALoopState.spec_review`.

### R4. Pause points
- **Implementation (pending PR):** `check_and_start` calls `sync_spec_reviews(app, prs)` first. This
  marks pending any in-scope PR in `pending`/`in_progress` that requires review and has an
  unapproved impl spec. It then skips launching PRs with any `spec_pending` (normally `impl`), because `pm pr start`
  would refuse them anyway. The status reason is "impl spec awaiting approval".
- **Implementation (in_progress):** `_poll_impl_idle` runs the same per-PR check every tick for
  in-scope review-required in_progress PRs. This sets `S` as soon as the spec file appears. The existing
  `became_idle` + `spec_pending` → `mark_active` path then blocks the review transition, so an idle
  agent waiting for approval is not treated as finished implementation.
- **QA:** `QALoopState.spec_review` is set by `qa_loop_ui.start_qa` and refreshed each
  `poll_qa_state` tick from `spec_review_required`. In `run_qa_sync`'s planner poll,
  `_qa_spec_gate(state, pm_root)` is blocked when `spec_pending.phase == "qa"`, or when
  `state.spec_review` is set and the QA spec needs approval (in that case it marks the spec pending). While the gate is blocked:
  - A complete plan is *deferred*, not consumed.
  - The deadline keeps being extended so a slow human doesn't time out the planner.
  - `latest_output` names the pause.
  When the gate clears and the spec text is unchanged, the deferred plan is consumed. If the spec
  was edited, the loop waits for the planner to re-emit the plan; the resume message asks it to.
  If the planner pane has exited, the deferred plan is used. After the poll loop there is a second
  blocking wait before scenario launch, so a plan read on pane exit can't skip the gate.
- **QA (already-present spec):** `_auto_start_qa_loops` skips starting QA while `spec_pending`
  is `qa`. `sync_spec_reviews` marks an existing, unapproved QA spec pending for in-scope `qa`-status
  PRs only when no QA run is in progress past planning and no recorded verdict holds. This is
  the "don't rewind" rule.
- Gates check `spec_pending` itself, not the derived flag. Removing the target (or the option) therefore leaves a
  waiting spec waiting, and it still needs explicit approval.

### R5. Approval resumes the same flow
- `pm pr spec-approve` → `approve_spec` → `spec_gen.notify_spec_approved(pr, phase, edited)`.
  This sends a message with `tmux.send_keys` (plus an extra Enter, the qa_loop follow-up pattern) to the
  waiting agent pane: the impl window `<display_id>` for impl, the planner pane (first pane of `qa-<display_id>`) for QA.
  If no pane is found it does nothing.  For an edited QA spec the message also asks the
  planner to commit and push the edited file, since it already pushed the pre-approval copy.
- Reject (`pm pr spec-approve` with an emptied spec): `reject_spec` regenerates with
  `review=True` when the pending record has `review: True`. The spec therefore stays pending and the phase stays paused.
- `on_state_loaded` also receives the old `spec_pending` map. When an in-scope PR's pending spec clears,
  it schedules `check_and_start`. This starts a pending PR whose existing impl spec was just approved, or
  starts a QA run that was waiting.

### R6. Visibility
- `autostart_state._derive`: `spec_pending` (any status) → `waiting` with reason
  `"<impl|QA> spec awaiting approval — V or pm pr spec-approve <id>"`. This is checked before QA/review
  progress so a running planner can't hide it.
- Each run entry gains:
  - `spec_review: {phase, path, approve, key: "V", generated_at} | None`, built from inputs
    `spec_reviews` that `collect_status_inputs` gathers using `spec_location`.
  - `review_specs: bool` (required for this PR) and `review_specs_by: [targets]`.
  `format_text` adds `[review-specs]` / `[review-specs ← T]` labels and a `spec=<path>` suffix.
  The runs popup shows the same labels and the reason.
- Tree (`tech_tree.py`): when `spec_pending`, the marker is `S impl` or `S qa`. It replaces any loop
  marker, so a running QA planner's spinner can't hide it. The `_signature` includes the pending phase.
- PR Actions picker (`cli/session.py:_build_picker_lines`), added at the user's request: a
  `[spec review]` badge goes on the `start` row for a pending impl spec and on the `qa` row for a pending QA spec.
  The picker's h/l navigation (`_picker_nav_pr_ids`) also includes PRs with a pending spec, so a
  windowless impl-spec pause is reachable (QA S5).

## 2. Implicit Requirements
- Writes to `project.yaml` from the TUI use `store.locked_update`. In-memory `app._data` is updated
  to match so the tree and status reflect the change right away.
- Default auto-start (no option, `prompt` mode) must take no new paths that write state or
  change prompts.
- `is_spec_approved` keys only on recorded approval. Specs that predate this feature count as unapproved, which
  covers the "already-present unapproved spec" case. Completed phases are not revisited because
  impl is only checked in `pending`/`in_progress`, and QA only before planning completes.
- The breadcrumb restore runs `check_and_start`. `spec_pending` is on disk, so pauses survive restart. The
  QA loop's `spec_review` flag is refreshed from the restored targets on the next poll tick.

## 3. Ambiguities (resolved)
- **Approval channel:** only `V` / `pm pr spec-approve` count as approval. A chat "approved" doesn't
  clear the gate, as required ("explicit approval through the existing controls").
- **Explicit `review_spec: true` / global review mode inside auto-start, without `--review-specs`:**
  these get the same gate. Before this change the waiting agent was treated as idle and moved to review,
  which is the bug the description calls out. Outside auto-start nothing changes.
- **Turning the option off:** use `--no-review-specs` on a re-add, or remove the target. Specs that are already pending
  stay pending.
- **"Editing keeps the phase paused":** while the editor is open nothing advances. Saving an
  edited spec approves it, using the existing spec-approve semantics, and the resume message says it was edited.
  Rejecting regenerates and stays pending.
- **Approval records** are per phase with a timestamp, not a content hash. Agents legitimately refresh
  specs, and re-asking on every edit would stall the chain.

## 4. Edge Cases
- Shared dependency of a review target and a plain target: review is required. Removing the review target
  releases the requirement, but a spec already pending stays pending.
- An in_progress PR's window killed while its impl spec is pending: it is skipped (no relaunch loop),
  and the status names the pause.
- Merge holds (`wait_for_merge`, explicit stop marks) are independent and appear side by side
  in labels.
- `skip_qa` projects: the QA gate never applies.
- A QA NEEDS_WORK → re-QA cycle: the QA spec was approved on the first pass, so there is no second pause.
- `pm pr auto-sequence` (CLI) already reports `paused: spec_pending`; it is unchanged.
- The impl idle edge (`PaneIdleTracker.became_idle`) is consumed only for in-scope PRs, so an
  impl that went idle while its target was removed still advances after it is re-added (QA S9).
