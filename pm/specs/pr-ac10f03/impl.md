# pr-ac10f03 — Sign-off integrates latest base and routes rework before gated merge

## Summary of the design

Today sign-off (`pm_core/signoff.py`) records a routing verdict bound only to
the PR HEAD (`pr["signoff"] = {verdict, sha, ts, origin, report_hash?}`), and
`pm pr merge` (`pm_core/cli/pr.py:pr_merge`) does the actual integration at
publish time: it checks out the base in the PR workdir, merges the branch,
and on any conflict/push failure opens a Claude *merge-resolution window*
(`_launch_merge_window` / `prompt_gen.generate_merge_prompt`) whose agent
resolves the conflict and pushes the base (`MERGED` verdict), after which the
TUI re-runs the merge with `--propagation-only` (`review_loop_ui._finalize_detected_merge`)
— publishing code no one signed off on.

This PR moves integration into sign-off and turns merge into a pure publisher:

1. **Integration check (new `pm_core/integration.py`)** fetches the configured
   base (target repository + `project.base_branch`), and computes the merge of
   the PR HEAD with that fetched base revision in an **isolated candidate**
   (never the PR worktree, never the shared base). Result: `up_to_date`,
   `clean` (with candidate tree), `conflict` (with conflicting paths) or
   `error`. Recorded on `pr["integration"]` (compact) and in
   `$CAP/integration.json` (full context).
2. **Sign-off** runs the check at router launch, shows it in the prompt, gives
   the agent `pm pr signoff integrate <pr>` to re-check, and binds the
   recorded verdict to `(HEAD, target repo, base branch, base revision,
   candidate tree, status)`. pm enforces earliest-step routing (a conflicted
   integration can never be MERGE/REVIEW/REQA → IMPL) and persists a
   `pr["signoff_return"]` record (reason + revisions + conflicts) for the next
   agent. On a bounce with a clean-but-moved base pm merges the fetched base
   into the PR branch first, so review/QA revalidate the integrated code.
3. **Merge** (`pm pr merge`, all backends, all entry points) only publishes
   the exact approved candidate: it re-verifies the record, re-fetches the
   base, recomputes the candidate, builds the merge commit from the approved
   tree (`git commit-tree`), and publishes with a compare-and-swap on the base
   revision. Any mismatch refuses, invalidates the approval and returns the PR
   to sign-off. No conflict-resolution window is ever opened by the merge path;
   `--no-signoff-check` / `--propagation-only` only recover an already
   completed merge.

## 1. Requirements (grounded)

### R1 — Integrate-latest-base action, integration check before SIGNOFF_MERGE
- New module `pm_core/integration.py`:
  - `target_for(data, pr, root)` → `(target_repo, base_branch)`. `local`
    backend: the main repo dir (`cli.helpers._resolve_repo_dir` /
    `project.repo`); `vanilla`/`github`: the workdir's `origin` URL.
  - `fetch_base(workdir, target_repo, base_branch, backend)` → fetched base
    sha. Local: `git fetch <main repo> <base>` (FETCH_HEAD). Remote:
    `git fetch origin <base>` → `origin/<base>`. The fetched revision is pinned
    under `refs/pm/integration/base` in the workdir so the candidate objects
    stay reachable.
  - `compute_candidate(workdir, head, base_sha)` → `(status, tree,
    conflicts)`: `up_to_date` when `base_sha` is an ancestor of `head`
    (candidate tree = `head^{tree}`); otherwise merges in a **temporary
    detached worktree** (`git worktree add --detach`; git 2.34 in this
    environment has no `merge-tree --write-tree`; when git ≥ 2.38 the
    in-memory `merge-tree --write-tree` is used instead), `git merge
    --no-commit --no-ff base_sha` → `git write-tree` on success, conflicted
    paths (`git diff --name-only --diff-filter=U`) on failure; the worktree is
    always removed (`git worktree remove --force` + prune). The PR worktree,
    index and branch are never touched.
  - Overlap context: files changed on the base since the merge base, files
    changed by the PR since the merge base, their intersection.
  - `check_integration(root, pr_id, *, data=None)` runs the above, writes
    `pr["integration"]` (compact, lists truncated) via `store.locked_update`
    and `$CAP/integration.json` (full). Errors (no workdir, fetch failure,
    dirty-index-independent git errors) produce `status: "error"` with
    `error` text — never an exception into the caller's state machine.
  - `apply_integration(root, pr_id)` (used by pm on bounces, and by
    `pm pr signoff integrate --apply` for humans): only when status is `clean`
    and the workdir is on the PR branch with a clean tree and no merge in
    progress; `git merge --no-ff -m "Integrate <base>@<sha8> into <branch>"
    <base_sha>` in the PR workdir. Refuses otherwise with a reason (never a
    half-merge; a failed merge is aborted). Does not push (network stays out
    of the TUI poll); merge pushes the approved PR head itself where needed
    (R4).
- CLI: `pm pr signoff integrate <pr_id> [--apply]` (new subcommand on the
  existing `_SignoffGroup`), prints a summary (status, base sha, conflicts,
  overlap) and exits 0 for `up_to_date`/`clean`, 1 for `conflict`/`error`.
- `signoff.launch_signoff_window` runs `check_integration` before building the
  prompt (only on the new-window path, alongside `stamp_signoff_launch`).
- `prompt_gen.generate_signoff_prompt` gains an **Integration** section: the
  target, fetched base revision, status, conflicts, overlapping files, the
  base delta command (`git log/diff <merge_base>..<base_sha>`), the re-check
  command, and the rule that SIGNOFF_MERGE certifies the PR **combined with
  that base**; conflicts require SIGNOFF_IMPL; semantic overlap needing
  verification picks REVIEW/REQA; report meta tags `pm-signoff-head`,
  `pm-signoff-base` and `pm-signoff-reason` are required. The prompt states
  the agent must not merge the base itself, push the base, or call any
  backend merge.

### R2 — Routing reuse, earliest step, persisted reason, automatic resumption
- Verdict vocabulary is unchanged (`SIGNOFF_MERGE/IMPL/REVIEW/REQA/BLOCKED`).
- `signoff.effective_verdict(verdict, integration, head)` (pure):
  - integration `conflict` and verdict ∈ {MERGE, REVIEW, REQA} → IMPL
    (reconciling is implementation work);
  - verdict MERGE and integration missing / `error` / for another HEAD →
    BLOCKED (approval impossible without a valid check; the human re-runs
    sign-off after fixing the environment);
  - otherwise unchanged. Coercions carry a reason.
- `step_signoff` records the *effective* verdict with the integration binding
  (R3). On a bounce hop pm (a) applies a clean integration into the PR branch
  when the base moved (`apply_integration`), then (b) transitions status and
  writes `pr["signoff_return"]` in the same locked update
  (`apply_signoff_hop(..., return_record=...)`):
  `{verdict, original_verdict?, coerced_reason?, hop, reason, reviewed_head,
  integration: {target_repo, base_branch, base_sha, status, conflicts,
  overlap}, applied: {from_head, merge_sha} | null, apply_error?, awaiting:
  <hop>, ts}`. *reason* comes from the report's `pm-signoff-reason` meta tag
  when the report's verdict meta matches the transcript verdict; otherwise
  "see report.html / PR notes".
- The next agent sees it: `prompt_gen.generate_prompt` (impl),
  `generate_review_prompt` and the QA planner prompt render a
  "Returned from sign-off" block via `signoff.format_signoff_return(pr)`;
  the sign-off prompt renders it as "Previous sign-off return" (provenance:
  `git log <reviewed_head>..HEAD` shows what changed since the last sign-off).
- **Automatic resumption across restarts / idle events** — `awaiting` is
  cleared only when the routed step actually launches a fresh session:
  `pr_start` (impl window launched), `_launch_review_window` (review window
  launched), QA start (`qa_loop_ui.start_qa`, `pr_qa_run_bg`). While set:
  - CLI `pm pr auto-sequence`: `in_progress` + awaiting impl → relaunch impl
    `--fresh` instead of advancing an idle (old) session to review;
    `in_review` + awaiting review → launch a new review iteration instead of
    adopting an older PASS transcript; `qa` + awaiting qa → launch QA instead
    of adopting an older `qa_status.json` PASS.
  - TUI: `auto_start.check_and_start` starts awaiting-impl PRs with
    `fresh=True`; `_poll_impl_idle` does not auto-review an awaiting-impl PR;
    `_auto_start_qa_loops` / `signoff_ui.advance_all` ignore a recorded QA PASS
    for an awaiting-qa PR.
- Merge never makes implementation changes (R4).

### R3 — Approval bound to PR HEAD + target + base revision + candidate
- `pr["signoff"]` gains `integration: {target_repo, base_branch, base_sha,
  candidate_tree, status}` copied from the integration record whose `head`
  equals the launched/current HEAD at record time.
- `fresh_recorded_verdict(pr, sha)` additionally returns None for
  (a) a record marked `invalidated` (by the merge gate, R4) and (b) a
  SIGNOFF_MERGE record without an integration binding (**legacy HEAD-only
  approval**) — the driver's existing stale path then retires the run and
  relaunches an integration-aware sign-off.
- HEAD changes made during sign-off (including `apply_integration` or an
  agent commit) keep the existing launch-stamp rule: a verdict from a run
  launched on another HEAD is retired, never recorded — except a **bounce**
  whose only HEAD movement is pm's own recorded integration apply (that
  happens after the verdict is read, inside the hop, so the run is already
  consumed).
- `pm pr signoff record` (manual approval) binds to `pr["integration"]` for
  the current HEAD and requires the report's `pm-signoff-head` /
  `pm-signoff-base` meta to match HEAD / the recorded base; a report without
  them is a legacy report → refused with "regenerate with an
  integration-aware sign-off".
- `merge_gate_refusal(pr, current_sha)` (record-only, no network; shared by
  CLI gate and TUI `_signoff_gate`) refuses: no/other verdict, stale HEAD,
  invalidated record, legacy record, integration status not
  `up_to_date`/`clean`, target branch ≠ configured base branch, changed
  report hash.

### R4 — Gate every merge entry point/backend; refuse stale; no bypass
- `pm pr merge` (used by TUI `g`, popup picker, command bar, auto-merge
  `_attempt_merge`, CLI) is the single publisher. After the record gate:
  1. per-repo publish lock (`workdirs_base()/.publish-<repo_id>.lock`) so pm
     publishers serialize across PRs;
  2. re-fetch base; `base_sha` must equal the approved one;
  3. recompute the candidate; it must be conflict-free with the approved
     tree;
  4. build the merge commit from the approved tree: `git commit-tree <tree>
     -p <base_sha> -p <head>` (no worktree merge, no conflict resolution
     possible);
  5. publish with CAS on the base revision:
     - **local**: fetch the merge commit (via `refs/pm/merge/<pr>` in the
       workdir) into the main repo; if the main repo isn't on the base branch
       `git update-ref refs/heads/<base> <merge> <base_sha>`; if it is, verify
       `HEAD == base_sha` then `merge --ff-only` (existing dirty-overlap
       stash/unstash kept). Then best-effort update the workdir's base ref.
     - **vanilla**: `git push origin <merge>:refs/heads/<base>
       --force-with-lease=refs/heads/<base>:<base_sha>` (atomic CAS on the
       remote; a racing base update rejects the push), then the existing
       `_pull_after_merge` into the main repo.
     - **github**: push the approved PR head to the PR branch if the remote
       branch is behind it (fast-forward only); `git ls-remote` base must still
       equal `base_sha`; `gh pr merge <n> --merge --match-head-commit <head>`;
       then post-verify that the merge commit's first parent is `base_sha` and
       its tree is the approved tree. GitHub's API offers no base-revision
       precondition, so a base update landing between the `ls-remote` check
       and GitHub's merge cannot be refused; it is detected, recorded on
       `pr["merge_integrity"]`, printed loudly and noted on the PR (see A3).
  6. Any refusal at 2/3/5 (before publication) → `invalidate_signoff(root,
     pr_id, reason)` marks the record invalidated and exits 1 with "returned
     to sign-off"; the sign-off driver (TUI/CLI) relaunches the router on the
     next tick. No merge window is launched.
- Merge-resolution windows: the conflict variant of
  `generate_merge_prompt` and every `_launch_merge_window` call on the
  publish path are removed. The only remaining merge window is the
  post-publish *pull-from-origin* recovery in the main repo
  (`_pull_after_merge`), whose prompt now forbids pushing the base / running
  a backend merge. `_sync_workdir_base`'s auto-merge on divergence
  (`_pull_from_workdir`) is replaced by the CAS refusal.
- `--no-signoff-check` and `--propagation-only` → recovery only: allowed
  only when the PR head is already contained in the published base (local:
  main repo base; vanilla: `origin/<base>` after fetch; github: GitHub
  reports MERGED or origin base contains the head). Then they pull/finalize.
  Otherwise refused ("only recovers an already-completed merge").
- TUI `_maybe_auto_merge`: a failed `_attempt_merge` is tracked as a pending
  merge only when a (post-publish recovery) merge window actually exists;
  a gate refusal logs the reason and leaves the sign-off driver to re-run.

### R5 — CLI/TUI consistency, restarts, duplicates, manual holds, #219
- Holds (`auto_start.merge_holds`: explicit O/CLI stop marks and
  `wait_for_merge` closures) are independent of the sign-off record, so they
  survive bounces, re-sign-off and invalidation; `_maybe_auto_merge` checks the
  hold on every MERGE (tests cover hold → bounce → re-sign → still held).
- Display: `latest_signoff_verdict` ignores invalidated records (sign_off row
  shows the spinner while the router re-runs); `format_pr_line` and the tech
  tree show the `signoff_return` verdict icon for a PR returned from sign-off
  while `awaiting` is set.
- `SignoffStep` gains `reason` so TUI/CLI log "stale (HEAD moved)" vs "base
  moved — re-running sign-off" consistently.
- #219 (pr-8d8b360): its backend direction fix (merge base INTO the PR branch,
  GitHub stays the merger) is subsumed — pm now never asks an agent to merge
  at publish time; conflicts return through sign-off → impl, whose agent
  merges the base into the PR branch. Leave a PR note on pr-8d8b360.
- Post-merge metadata/checkout recovery (`_pull_after_merge`, the
  pull-from-origin window, `--propagation-only` after a verified merge,
  `pr_sync` detection) stays separate and never publishes code.

## 2. Implicit requirements
- The integration check must not disturb a running agent in the PR workdir:
  temp worktrees live outside the workdir (`workdirs_base()/.integration/…`),
  only refs under `refs/pm/` are written, and `git worktree prune` cleans up.
- Container mode: the router agent runs `pm pr signoff integrate` inside the
  container; the check must work there too (it only needs the workdir git
  repo + origin/main-repo access). If it fails in-container, the launch-time
  host check remains authoritative.
- The candidate must be deterministic between sign-off and merge: same
  machine, same git, same strategy (ort). The gate recomputes and compares
  trees rather than trusting stored state.
- `apply_signoff_hop` must stay idempotent under duplicate ticks: the status
  guard (`status == sign_off`) also guards the return record and the
  integration apply (apply only when HEAD still equals the reviewed head).
- `pm pr merge`'s existing same-PR lock and "already merged" short-circuit
  are kept; the new publish lock is taken after it (lock order: PR → repo).
- Existing test patch points (`_check_signoff_verdict`, `_signoff_window_pane`,
  `_retire_signoff_window`, `head_sha`) keep working.
- QA/regression instructions and fake backends: `FakeGitHub` must honor
  `--match-head-commit` and expose the merge commit so the github path is
  testable.

## 3. Ambiguities (resolved)
- **A1 "Integrate into the PR branch or an isolated candidate"** — both: the
  check always uses an isolated candidate (no HEAD change, so an unchanged
  PR HEAD with a moved base can be approved without new commits); pm merges
  the base into the PR branch only on a bounce (so the revalidating step sees
  the integrated code) and only when clean. Conflicted merges are left to the
  implementation agent with full context — pm never leaves a half-merge.
- **A2 Who resolves conflicts** — the implementation step (SIGNOFF_IMPL),
  never the merge command or the sign-off agent.
- **A3 GitHub base race** — GitHub cannot CAS the base on merge. Resolution:
  narrow the window (ls-remote immediately before `gh pr merge`
  `--match-head-commit`), serialize pm publishers, and detect afterwards
  (first parent/tree check); a detected race is recorded
  (`merge_integrity`), printed, and noted on the PR rather than silently
  accepted. Local and vanilla are true CAS.
- **A4 Base freshness while held** — the merge gate is authoritative (it
  fetches); the driver does not poll the remote every tick. A held PR whose
  base moves is re-signed when the merge is attempted (g / auto-merge), which
  invalidates and re-runs sign-off automatically; the hold still applies to
  the new approval.
- **A5 Integration check failure** (network, missing workdir) — MERGE is
  coerced to BLOCKED with the error as reason; bounce verdicts proceed.
- **A6 Legacy records** — non-MERGE legacy records are still adopted (they
  only route back); legacy MERGE approvals are not.
- **A7 Evidence provenance** — review/QA evidence is kept; the sign-off
  prompt shows the previous return record and the integration apply commit so
  the agent makes an explicit evidence-freshness decision. Mechanically
  re-validating unrelated scenarios is not forced.

No [UNRESOLVED] ambiguities.

## 4. Edge cases
- Base unchanged since PR branched (`up_to_date`): candidate tree = HEAD
  tree; merge commit identical in content to the old `merge --no-ff`.
- Base moved, clean, MERGE: approval bound to the separate candidate; merge
  publishes `commit-tree(candidate, base, head)`.
- Base moves after approval (other PR merged): merge refuses before publish,
  invalidates, sign-off re-runs; with O/wait-for-merge the PR is held again
  after the new MERGE.
- Base moves during publication: local/vanilla CAS rejects → invalidate +
  return; github → A3.
- PR HEAD moves after approval: existing stale path + gate refusal; github
  `--match-head-commit` covers a push to the remote branch after validation.
- Dirty workdir / merge in progress on a bounce: no apply; return record says
  why; the next agent merges.
- TUI restart between hop and relaunch: `awaiting` drives a fresh launch;
  old idle sessions / old PASS transcripts / old qa_status PASS are not
  adopted.
- Duplicate ticks: status guard + `_launching` / sign-off inflight sets.
- A merge window left from an old version for an `in_review` PR: its
  `MERGED` verdict now leads to `--propagation-only`, which only finalizes if
  the head is actually in the published base.
- `skip_qa` projects: sign-off follows review; REQA on such a project still
  transitions to `qa` (existing behavior) — unchanged.
