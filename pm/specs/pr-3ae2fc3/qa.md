# QA spec — pr-3ae2fc3: Add spec-review pauses to autostart

## 1. Requirements (Given / When / Then)

### Adding and listing the option
- **R1** Given a pm session with the TUI running and a chain A ← B ← C (C depends on B, B on A),
  when the user runs `pm autostart add C --review-specs --wait-for-merge`,
  then the command reports C added with both wait-for-merge and review-specs.
  `pm autostart list` shows C as `wait-for-merge +review-specs`, and `list --json` has `review_specs: true`.
- **R2** Given the same session, when the user types `autostart add C --review-specs` in the TUI command bar,
  then the log confirmation names review-specs, and command-bar `autostart list` shows `(review-specs)` next to C.
- **R3** Given C is already a review-specs target, when the user re-adds C with no flags,
  then it reports `unchanged` and review-specs is kept. Re-adding with `--no-review-specs`
  reports `options_changed` (was review-specs). Re-adding with `--auto-merge --review-specs`
  over a different policy reports `policy_changed`, and the change carries review_specs.
- **R4** Given any session, when the user passes both `--review-specs` and `--no-review-specs`,
  then the command is rejected as conflicting flags and the target set is unchanged.

### Impl-spec pause
- **R5** Given a review-specs target whose prerequisite A is pending, when A becomes ready,
  then A is launched with a review-mode spec prompt. When A's session writes its impl spec in the
  workdir, A is marked `spec_pending: impl`. When the agent then goes idle, A is NOT moved to review.
- **R6** Given A is paused on its impl spec, when the user looks at the surfaces, then:
  - the tree node shows `S impl`;
  - the PR Actions popup (prefix+P) shows `[spec review]` on the **start** row, even when A has
    no tmux window yet (held before launch);
  - the `a` runs popup and `pm autostart status` show A waiting with the reason
    "impl spec awaiting approval — V or pm pr spec-approve A", a `spec review: impl` label and the spec path;
  - `status --json` runs[A].spec_review has phase=impl, path, approve="pm pr spec-approve A" and key="V".
- **R7** Given A is paused on its impl spec, when the user approves it (`pm pr spec-approve A` with
  the editor left unchanged, or `V` in the TUI), then `spec_pending` clears and A records
  `spec_approved.impl`. The waiting impl pane receives a "spec ... was approved via pm" message,
  the S marker disappears, and once A goes idle again the chain continues (review → QA).
- **R8** Given A is paused, when the user approves with edits (the editor changes the text), then the
  edited text is written to the spec file that `pm pr spec A` reads (the workdir copy) and the resume
  message says "approved with edits". If A had no workdir yet (already-present spec, R12), the edited
  approved text is the one the fresh workdir and the impl prompt see after A starts, not the committed copy.
- **R9** Given A is paused, when the user empties the spec in the editor (reject), then the spec is
  regenerated in review mode and A stays paused with `S impl`. It does not advance.

### QA-spec pause
- **R10** Given a review-specs PR in QA with a QA spec present and unapproved, when the QA loop
  reaches planning, then no scenario windows launch and the PR is `spec_pending: qa`. The tree shows
  `S qa` even while the planner spinner is live, the PR Actions popup marks the **qa** row
  `[spec review]`, and status says "QA spec awaiting approval … (scenarios launch after approval)".
- **R11** Given the QA spec is pending, when the user approves it, then the planner pane gets the
  approval message (asking it to re-emit the plan), and scenarios launch after that. When the approval
  includes edits, the message also asks the planner to commit and push the edited spec.

### Already-present spec / no rewind
- **R12** Given a pending PR whose impl spec already exists (for example committed under `pm/specs/<pr>/impl.md`)
  with no approval record, when it becomes a review-specs target and is ready, then it is NOT
  started and is shown waiting on "impl spec awaiting approval". After approval it starts on the
  next scheduler pass without another user action.
- **R13** Given a PR that is already in_review / qa past planning / merged, when it is brought under
  `--review-specs`, then completed phases are not revisited (no impl pause on an in_review PR).

### Shared deps, removal, persistence
- **R14** Given targets T1 (`--review-specs`) and T2 (plain) that share prerequisite S, then S requires
  review (status `[review-specs ← T1]`), and T2's private prerequisites do not.
- **R15** Given S has an impl spec waiting for approval, when T1 is removed or re-added with
  `--no-review-specs`, then S's pending spec is still pending (not approved). Later specs on S are not gated.
- **R16** Given a chain paused on a spec, when idle polling runs for several minutes, or the TUI restarts
  through the breadcrumb path (`pm tui restart --breadcrumb`, or the merge-triggered restart), then the target
  record keeps review_specs and the PR stays paused with the same surfaces. A plain Ctrl+R or a session
  relaunch starts auto-start OFF by design (existing behaviour). The pending spec_pending record still
  survives, so the PR is still not advanced or relaunched.
- **R17** Given `--review-specs --wait-for-merge`, then merge holds and spec pauses both appear in labels,
  and approving a spec does not release the merge hold. The manual merge (`g` / `pm pr merge`) is still required.
- **R18** Given default auto-start (no `--review-specs`, spec-mode prompt), then PRs start, go idle
  → review → QA exactly as before, with no S markers and no `review_specs` labels in status.

## 2. Setup
- Install pm from this branch (`./install.sh --local` or venv + `PYTHONPATH` per `tui-manual-test.md`).
  Create a throwaway git project with `pm init --backend local --no-import`, add a dependency chain
  with `pm pr add … --depends-on`, and start `pm session` (detached).
- Drive Claude with fake-claude (`_all: {}` for impl; `qa_planning` QA_PLAN, `qa_scenario` PASS,
  `review` PASS). The fake never writes spec files, so the tester plays the agent's
  role: write `pm/specs/<pr>/impl.md` (or `qa.md`) into the PR workdir once the session starts.
  Alternatively, pre-commit the spec under the project's `pm/specs/<pr>/` for the already-present path.
  Use a `delay` on the fake's QA_PLAN verdict so `qa.md` can be written before the plan is emitted.
- `pm pr spec-approve` opens `$EDITOR`. Set `EDITOR` to `true` (approve unchanged), to a script that
  edits the file (approve with edits), or to one that truncates it (reject).

## 3. Edge Cases
- **E1** Approving while the impl window has been killed → the approval succeeds, the notification is a no-op,
  and the scheduler relaunches the in_progress PR (no crash, no relaunch loop while pending).
- **E2** `pm pr spec-approve` on a PR with no pending spec → clear error, nothing changes.
- **E3** Regenerating an approved spec (`pm pr spec A --regenerate` or equivalent) drops the
  approval, so the gate asks again on the next step.
- **E4** `skip_qa` project → only the impl pause applies.
- **E5** QA NEEDS_WORK → re-QA → no second QA-spec pause (approval is per phase).
- **E6** Concurrent CLI adds/removes from two shells while the scheduler is polling and a
  spec-approve runs → project.yaml stays parseable, no lost `spec_pending` / `spec_approved` /
  target records, and every actor gets a reply (no timeouts on the autostart request channel).
- **E7** `pm pr start` (manual) on a PR with a pending spec → refuses, as before. Starting a PR that is in a
  review-specs closure manually from the TUI (`s`, or a typed command-bar `pr start <id>`, which gets
  `--review-spec` added) uses the same review-mode spec prompt, and its spec is held. Known gap (pr-74c4182, out of
  scope): the PR Actions picker start row and a shell `pm pr start` give the agent the plain spec prompt. The gate
  still holds the spec (`S impl`) and blocks the move to review until approval.
- **E8** `pm pr spec A --regenerate` refreshes the TUI, so an in_progress review-specs PR is held again
  within a poll or two without a manual reload.
- **E9** `pm autostart add X --review-specs --no-review-specs` fails with conflicting_flags from the CLI
  and from the command bar alike.
- **E10** Approving an empty pending QA spec ("Spec content is empty — nothing to review.") releases the planner
  gate, but QA then ends INPUT_REQUIRED "QA spec was not generated during planning". Scenarios never launch
  against an empty spec, and nothing hangs.
- **E11** `pm pr spec-approve` racing `pm pr spec --regenerate` on the same PR: only the record and text the reviewer
  saw are approved. An approval that lands mid-regeneration wins, and regenerate/reject exit 1 "approved while it was
  being regenerated". A losing concurrent approver prints "No pending spec review for X.". The agent pane gets the
  "approved" message only while the approval stands.
- **E12** A prerequisite whose impl goes idle while its target is removed (out of scope) still advances to review once
  the target is re-added. The idle edge is not consumed while out of scope.
- **E13** When the QA spec pause starts right after a review loop finishes, the TUI log bar shows the QA-spec pause
  message, not the "Review loop done" line.
- **E14** Review mode from the global `spec-mode review` setting or a per-PR `review_spec` gets the same pauses inside
  auto-start, labelled `review-spec`. Changing the global setting mid-run is picked up on the next poll. Turning
  review mode off (setting, target removal, `autostart clear`, auto-start off) never approves a spec that is already pending.
- **E15** Approving a spec right after it is held (before the TUI's next reload, for example a QA spec approved within a
  second of the planner gate holding it) is final. The TUI does not hold that phase again, and the PR does not show `S`
  for it again.

## 4. Pass / Fail Criteria
Pass: every Then above is observable on the named surface. CLI text and JSON agree with the
TUI tree, PR Actions popup and runs popup for the same PR at the same moment. No PR advances past a
pending spec without an explicit approve, and no pending spec is cleared except by approve.
Fail: any of the following.
- An idle waiting agent is moved to review.
- Scenarios launch while the QA spec is pending.
- A pending spec is silently approved by removing a target.
- A paused PR is relaunched in a loop.
- Status disagrees between CLI and TUI.
- Default auto-start behaviour changes.
- A crash or traceback appears in the TUI log.

## 5. Ambiguities (resolved)
- The fake Claude can't write specs. Testers writing the spec file into the workdir stand in for the
  agent's action. This is a legitimate user-equivalent stimulus, not a code-level shortcut.
- "Edit keeps the phase paused": while the editor is open nothing advances. Saving edits approves the spec
  (existing spec-approve semantics). Only emptying (reject) keeps it paused afterwards.
- PRs in review mode through their own `review_spec: true` or the global spec-mode get the same pauses inside
  auto-start, even without `--review-specs` (per the impl spec). Status labels them `review-spec`.
- `--no-review-specs` on an existing review-specs target reports `options_changed` (R3), not `unchanged`.
  `status --json` has no `"ok"` key (pre-existing schema). `list --json` does have one.
- Fake-claude test setup: give each throwaway project unique PR titles, because runtime state is keyed by PR id
  (pr-6176ec6). For one NEEDS_WORK re-QA run, use qa_scenario verdicts `["NEEDS_WORK","NEEDS_WORK","PASS"]`,
  because the interactive Scenario 0 window also consumes one. Name any recorder grouped tmux session in pm's
  `<session>~N` style (pr-095c51d).
