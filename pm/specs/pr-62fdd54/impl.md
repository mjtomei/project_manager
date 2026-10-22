# pr-62fdd54 — Synchronize the PR branch before QA planning; recover stale handoffs

## Background (code paths)

- `pm_core/qa_loop.py:run_qa_sync` — Phase 1 (planning) launches Scenario 0
  and the planner in the canonical PR workdir (`pr["workdir"]`), records
  `pre_plan_head`, polls for the plan, then Phase 1.25 calls
  `_publish_planner_head(workdir, branch)` which fast-forward-pushes the
  planner's head and raises `PlannerHandoffError` ("is behind" / "diverged
  from") when the upstream branch is not an ancestor of the planner head.
  `state.planner_head` is then pinned for every scenario clone
  (`create_scenario_workdir(expected_head=...)`, tmux and container launch).
- `_execute_and_finalize` runs `_run_qa_finalize_pane`, the only step that
  imports QA-worker pushes into the PR workdir.  Interrupted / INPUT_REQUIRED
  runs (no scenarios, handoff failure, trust block, stop) skip it, so the
  PR workdir stays at an older local head while workers' fixes sit on the
  upstream.  The next QA run plans against that stale tree and
  `_publish_planner_head` refuses the handoff only *after* a full planning
  session (observed twice on #234).
- Routing: the TUI (`tui/qa_loop_ui._on_qa_complete`) and auto-sequence
  (`cli/pr.py` `status == "qa"`, reads `overall` from the latest
  `qa_status.json`) route NEEDS_WORK → `in_review` + review loop, and park
  on INPUT_REQUIRED.  The review prompt (`prompt_gen.generate_review_prompt`)
  step 1 for remote backends is "Pull the latest changes for `<branch>`…
  Resolve any merge conflicts" — the native agent reconciliation route.
- Sign-off evidence is HEAD-bound (`signoff.fresh_recorded_verdict`) and can
  be explicitly retired with `signoff.invalidate_signoff(root, pr_id, reason)`.

## Requirements

R1. **Refresh before planning.** In `run_qa_sync`'s planning phase, after
    stale scenario windows / orphaned QA containers are cleaned up (so the
    previous run's workers are no longer writing) and before Scenario 0 or
    the planner is launched, a new helper `_sync_pr_branch(workdir, branch)`
    queries the real upstream (`push_proxy.resolve_real_origin`), fetches
    the PR branch's objects (FETCH_HEAD only; no local ref moves except
    the fast-forward below) and classifies local `refs/heads/<branch>` (L)
    vs upstream (U).  Local-only repos (no real upstream) and an absent
    upstream branch are no-ops.  The planner prompt and command are built
    after the sync (they used to be built before stale-window cleanup), so
    nothing the planner is given predates it.

R2. **Behind-only fast-forwards automatically.** L ancestor of U →
    `git merge --ff-only U` in the workdir (the branch is checked out).
    Git's own checks preserve dirty files (it refuses when a local change
    or untracked file would be overwritten).  A refusal becomes a specific
    INPUT_REQUIRED hold quoting git's message and the paths, nothing
    changed.  Up-to-date and local-ahead (U ancestor of L, e.g. earlier
    unpushed planner-only commits) proceed unchanged — the existing
    publish step pushes local-ahead commits fast-forward.

R3. **Diverged → native review route, never force/reset.** Neither is an
    ancestor of the other: no merge/reset/push by pm.  The QA run ends
    before planning with verdict NEEDS_WORK and an `_error` naming both
    heads, the counts of local-only/upstream-only commits, and the
    reconciliation instruction (merge the upstream into the PR branch
    preserving both histories, no force-push/reset; then review).  The
    existing NEEDS_WORK routing sends the PR to review, whose step 1 pulls
    and resolves conflicts.  Conflicting and non-conflicting divergence
    take the same route.  The `_error` is what `_record_qa_note` writes to
    the PR note the review session reads.

R4. **Imported application code invalidates old review/sign-off.**  When
    the fast-forward brings in paths outside `pm/` (same classification as
    `_planner_code_changes`), the run ends before planning with
    NEEDS_WORK (route to review, then QA again), listing the paths and
    the L..U range, and `signoff.invalidate_signoff` retires any recorded
    sign-off verdict.  pm/-only imports (QA notes, specs, instructions)
    proceed to planning on the refreshed tree.

R5. **Specific actionable holds** (INPUT_REQUIRED, no planning) for:
    fetch/ls-remote failure; workdir not on the PR branch (HEAD detached or
    another branch); an unfinished merge/rebase/cherry-pick in the workdir;
    ff refused (R2); dirty tracked files while diverged; and a divergence
    (same L and U) that was already routed to review once and not
    reconciled (prevents an endless QA→review→QA loop when the reviewer
    does not merge).  The last one is detected via a small record on the
    PR (`pr["qa_branch_sync"] = {local, upstream, at}`) written when R3
    routes.

R6. **Early exits are visible to every driver.** Each sync exit writes
    `qa_status.json` with `overall` and `error` (auto-sequence reads only
    `overall`), sets `state.running = False`, `planning_phase = False`,
    and notifies.  The existing Phase 1.25 handoff-failure exit did not
    write `overall`, leaving auto-sequence reporting "running: qa" forever
    — fix it the same way.

R7. **Planner/worker revision consistency.** `pre_plan_head` is taken after
    the sync, so it is the revision the planner reads (recorded as
    `state.planning_base`, logged and persisted in the resume file), and
    `_planner_code_changes` stays planner-only.  The existing guard in
    `_publish_planner_head` + `expected_head` stays: if the upstream moves
    during planning (a lost/active writer, pr-3201ea8) the handoff still
    refuses and no worker launches.  Its "behind" message changes from
    "Pull the PR branch … and restart QA" to say the upstream moved while
    planning and that restarting QA refreshes the workdir automatically;
    "diverged" says restarting QA routes the divergence to review.

R8. **Gates preserved.** No pm-initiated merge to the base branch, no
    change to merge policy / wait-for-merge / spec gates; routing uses the
    existing qa→in_review NEEDS_WORK path only.

## Implicit requirements

- The sync must not run on QA resume (`resume_qa_sync`): scenarios are
  already pinned and running.
- The sync only runs when there's a planning phase (`state.planning_phase
  and not state.scenarios`) and `branch` is set.
- Network ops use `_git_capture` timeouts; failures never raise out of
  `run_qa_sync`.
- The ff is done with the branch checked out in the workdir, so `HEAD`,
  index and worktree move together (no `update-ref` behind the worktree).

## Ambiguities (resolved)

1. *Diverged but merge would be clean — should pm merge itself?*  No: the
   task says only behind-only fast-forwards automatically; divergence gets
   an agent route.  Review's own pull step does the merge.
2. *What counts as "not covered by the prior review"?*  There is no
   durable reviewed-sha record; the PR workdir head is what review last
   saw (review runs and commits there).  Any non-`pm/` path in `git diff
   L U` counts — conservative: a master merge pushed from elsewhere also
   sends the PR back to review.
3. *Dirty workdir + behind:* ff with git's safety (preserves non-overlapping
   edits); overlapping → hold.  Dirty + diverged → hold (an agent merge in
   a dirty tree is unsafe).
4. *Imported code: plan anyway and force NEEDS_WORK at the end, or stop
   before planning?*  Stop before planning — review may change the code,
   so a plan/worker run against it would be wasted and is not evidence.

## Edge cases

- Upstream changes between sync and handoff → existing PlannerHandoffError
  hold (R7); next QA run re-syncs, so planning never repeats against a
  known-stale tree.
- Workers killed by stale-window cleanup may have unpushed work — that
  is pr-3201ea8 (ownership); the sync only sees what reached the upstream
  and must not hide it (it reports L/U shas in logs).
- Upstream branch deleted/absent → proceed; publish pushes it.
- Local backend (`resolve_real_origin` → None) → sync is a no-op.
- `pm/`-only upstream commits (e.g. old workers' `qa:` notes) → ff and plan.
