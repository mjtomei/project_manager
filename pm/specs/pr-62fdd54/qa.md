# pr-62fdd54 — QA spec: synchronize the PR branch before QA planning

## Background — the surfaces a user drives

- **Starting QA.** The TUI `t` key on a PR (`z t` fresh start, `zz t` QA loop)
  runs the full QA loop: planning phase, then scenarios. `pm qa run
  <instruction> --pr <id>` runs a single pre-built scenario and has **no**
  planning phase. `pm pr auto-sequence <pr>` drives a PR forward by reading
  the latest `qa_status.json` `overall` verdict.
- **What the user sees.** The TUI message log (`QA [pr-…]: …`,
  `QA NEEDS_WORK … — returning to review`, `QA INPUT_REQUIRED … — paused for
  human input`), the PR status (`pm pr list`), the QA note recorded on the PR
  (`pm pr note list`), `qa_status.json` in
  `~/.pm/workdirs/qa/<pr-id>-<loop-id>/`, the QA / scenario tmux windows, and
  the PR workdir's git state.
- **The upstream.** The PR branch on the real remote, as resolved by
  `push_proxy.resolve_real_origin` (a URL with a scheme, e.g. `file:///…`).
  A local-only repo (origin is a plain directory, or no origin) has no
  upstream to reconcile against.
- **The defect being fixed.** A QA worker pushes fixes straight to the
  upstream; only the finalize pane of a *completed* QA run pulls them into
  the PR workdir. After an interrupted / INPUT_REQUIRED run the workdir is
  stale. The next QA run used to plan against that stale tree and then refuse
  the planner handoff *after* a full planning session, and restarting QA
  repeated it (#234).
- **The fix.** Before Scenario 0 / the planner launch (and after the previous
  run's scenario windows / containers are torn down), the run reconciles the
  PR workdir with the upstream: behind-only fast-forward; imported
  application code or diverged histories go back to review as NEEDS_WORK
  (retiring any recorded sign-off); anything unsafe becomes a specific
  INPUT_REQUIRED hold. It never merges divergent histories, resets or
  force-pushes. Every exit before scenarios writes an `overall` verdict.
- **Integration with master (post-QA merge).** The branch merged
  `master@89e3c501`. Master had moved the QA planner's command build to
  carry provider environment variables out-of-band
  (`build_claude_shell_cmd(..., env_out=…)` collects them and the tmux pane
  receives them via `env=`; they are never interpolated into the logged
  command string). This PR moved that build *after* the pre-planning sync,
  so the resolved build must keep the provider transport. A planner that
  starts without the configured provider env, or a secret that shows up in
  the visible command/log, is a regression of that integration.
- **Driver guard added after the first QA round.** `pm pr auto-sequence`
  used to launch a detached QA driver even with no pm tmux session; the
  driver exits "No pm session found" and writes no `qa_status.json`, so
  every tick re-launched it and reported `running: qa (launched)` forever.
  The `qa` branch now pauses with `paused: no pm tmux session`, matching the
  other status branches.

## Requirements

### R1 — A stale workdir is refreshed before anything reads it

**Given** a PR in review whose workdir sits at an older commit than the
upstream PR branch (a previous QA round's worker pushed a fix and the run
ended before finalizing), **when** the user starts QA from the TUI, **then**
the run reconciles the workdir with the upstream *before* the planner reads
anything: the planner is never handed the stale tree, and the user sees the
sync outcome in the TUI log (a fast-forward line, a route-to-review line, or
a hold).

**Given** the same stale workdir, **when** the user starts QA, **then** the
planner prompt/plan is generated only after the sync — the plan and every
scenario worker see the same, refreshed revision.

### R2 — Behind-only: fast-forward automatically

**Given** a workdir that is strictly behind the upstream (no local-only
commits), **when** QA starts, **then** the PR branch is fast-forwarded to the
upstream head (HEAD, index and worktree move together), the TUI log reports
the old → new head, and the run proceeds to plan against the new head.

**Given** an up-to-date workdir, **when** QA starts, **then** nothing in the
workdir changes and planning proceeds normally (no spurious hold, no new
bookkeeping record).

**Given** a workdir with local-only commits that the upstream already
contains (an earlier planner's unpublished commits), **when** QA starts,
**then** the run is left unchanged and the existing handoff publishes the
local head as before.

**Given** a local-only repo (no real upstream), **when** QA starts, **then**
there is no network work and the run proceeds (the local checkout state
holds still apply).

### R3 — pm/-only upstream changes are imported silently

**Given** a behind workdir whose upstream gained only `pm/` paths (QA notes,
specs, instructions) since the last round, **when** QA starts, **then** the
workdir fast-forwards, no review route is triggered, and planning proceeds
on the refreshed tree.

### R4 — Imported application code returns the PR to review and retires sign-off

**Given** a behind workdir whose upstream gained paths outside `pm/` (a QA
worker's code fix), **when** QA starts, **then** QA stops before planning
with NEEDS_WORK; the user sees the run returning to review; the QA note and
`qa_status.json` name the imported paths and say no review covered them; the
PR status becomes `in_review`; and any recorded sign-off verdict for the old
head is invalidated so it cannot be adopted for the imported code.

**Given** the same, **when** the run ends, **then** no planner session or
scenario worker ran against the imported code (the fix must be reviewed
first), and the workdir's branch now contains the imported commit (it was
fast-forwarded, not reset).

### R5 — Diverged histories go to review once, never force/reset

**Given** the workdir has local planner-only commits *and* the upstream has
a worker fix (neither an ancestor of the other), **when** QA starts, **then**
QA stops before planning with NEEDS_WORK; the message/note names both heads,
the counts of local-only and upstream-only commits, and the instruction to
merge the upstream into the PR branch keeping both histories and then review;
the PR goes back to `in_review`; and pm performed no merge, reset or push
(workdir branch, upstream branch and dirty state unchanged).

**Given** a divergence that was already routed to review once and the
reviewer did not reconcile it (same two heads), **when** QA starts again,
**then** the run holds INPUT_REQUIRED saying the branch is still diverged
after review, instead of bouncing QA→review→QA forever.

**Given** that routed divergence, **when** the reviewer actually merges the
upstream into the PR branch in the workdir and pushes, **then** the next QA
start syncs to the merged head, clears the divergence record, and plans
normally.

### R6 — Unsafe or unreconcilable workdirs hold with an actionable message

Each of the following stops QA before planning with INPUT_REQUIRED, changes
nothing, and leaves an `overall` verdict of INPUT_REQUIRED in
`qa_status.json`; the message names the concrete problem and the concrete
remedy:

- **Dirty conflict:** a tracked local edit that the incoming change would
  overwrite → the hold names the file and says the fast-forward was refused;
  the local edit survives byte-for-byte and the branch head does not move.
- **Untracked blocker:** an untracked file that the fast-forward would have
  to create → the hold says to move or remove it (git cannot stash untracked
  files) and the file survives.
- **Wrong checkout:** the workdir has another branch (or a detached HEAD)
  checked out, even when the branch itself is current → the hold names the
  checked-out ref and says to check out the PR branch.
- **Unfinished git operation:** the workdir is mid-merge / mid-rebase /
  mid-cherry-pick → the hold names the unfinished operation and says to
  finish or abort it (a stopped rebase detaches HEAD, so it must not merely
  say "check out the branch").
- **Unreachable upstream:** the remote cannot be listed or fetched → the
  hold says the upstream could not be refreshed and to restart QA once the
  remote is reachable.
- **Upstream moved during the sync:** the head classified by `ls-remote` is
  already gone by the fetch → the hold says the branch moved on while QA was
  synchronizing (not an empty git error) and to restart QA.
- **Dirty divergence:** the histories diverged *and* tracked files are
  modified → the hold names the uncommitted files, keeps the routed
  divergence record, and once the tree is clean the same heads hold rather
  than route to review again.

### R7 — Every early exit is visible to the drivers

**Given** any QA run that stops before launching scenarios (sync route, sync
hold, missing QA spec, refused planner handoff), **when** it ends, **then**
`qa_status.json` has an `overall` verdict and an error, the run is no longer
marked running, and `pm pr auto-sequence` reports the routed outcome
(`qa: needs_work, returning to review` / `paused: input_required (qa)`)
rather than `running: qa` forever.

**Given** a PR in `qa` and no pm tmux session running, **when** the user runs
`pm pr auto-sequence <pr>`, **then** it reports `paused: no pm tmux session`
and launches no detached QA driver (which would die immediately and write no
`qa_status.json`), instead of reporting `running: qa (launched)` every tick.

### R8 — The planner/worker revision stays pinned; the handoff guard stays

**Given** a successful sync, **when** planning completes, **then** the
revision the planner read is the revision every scenario clone is pinned to
and the run records it (`planning_base` in the resume snapshot, alongside
`planner_head`).

**Given** a worker pushes to the upstream *while* the planner is running,
**when** the handoff publishes, **then** the handoff still refuses
(INPUT_REQUIRED), no scenario worker launches, the upstream keeps the
worker's commit (nothing is overwritten), and the message names both the
restart-QA remedy and the manual "pull the PR branch in the workdir" remedy.

**Given** the single-scenario `pm qa run <instruction>` path (no planning
phase, so no pre-planning sync), **when** the workdir is behind or diverged
from the upstream, **then** the run ends INPUT_REQUIRED and its message names
the manual remedy that works for that command (pull / merge the upstream into
the PR branch in the workdir), not only "restart QA".

**Given** a QA run already executing scenarios, **when** the TUI restarts and
resumes it, **then** the pre-planning sync does not run again and the
scenarios keep testing the pinned revision.

### R9 — The post-sync planner launch keeps the provider transport

**Given** a project whose `qa_planning` session resolves to a configured
provider that needs environment variables (a provider entry with an API-key
env var in `~/.pm/providers.yaml`), **when** the user starts QA on a stale
workdir, **then** the planner pane starts with those provider environment
variables present in its process environment, the plan is produced against
the synced head, and the provider's secret values do not appear in the
visible command string, the pane's start command, or the pm log.

## Setup (user steps)

1. Install the PR's pm into a venv and confirm `pm which` points at it.
2. Create a throwaway project: a git repo with a little application code and
   a `pm/` directory, `pm init --backend local` (keep the bundled QA
   instruction library, or `pm qa add` one), and at least one PR.
3. Give the project a real upstream: a bare repo used as the PR branch's
   remote via a URL with a scheme (`file:///…`), so `resolve_real_origin`
   sees a real remote. Push the PR branch there.
4. Create the PR workdir the normal way (`pm pr start`, or let QA provision
   it), then put the PR in `in_review` (bootstrap-only edit of
   `project.yaml`, or a review pass) and record a sign-off where the story
   needs one.
5. Configure the fake Claude (`pm fake-claude config set`) for the session
   types the flow reaches (`qa_planning`, `qa_concretize`, `qa_scenario`,
   `qa_verification`, `qa_finalize`, `review`), with `_all: {}` for the rest.
6. Start the pm session and drive the TUI from a second pane; for CLI
   stories run `pm …` inside a pane of that session.
7. Simulate "a previous QA worker pushed" by committing in a second clone of
   the upstream and pushing to the bare repo — never by editing the PR
   workdir's branch, which is the thing under test.

## Edge cases

- Upstream branch absent or deleted → no-op sync; the handoff publishes it.
- A non-git workdir → no checkout hold; the planner handoff guard reports it.
- Two QA starts racing (auto-sequence tick spawning the detached QA driver
  plus a TUI start) on the same stale workdir → one fast-forwards, the other
  must not corrupt the workdir or silently plan a stale tree; the end state
  is the upstream head with one authoritative run.
- A worker pushing repeatedly while the sync runs → either a fast-forward
  that includes the final head or a "moved on while QA was synchronizing"
  hold; never a plan against a stale tree and never a lost push.
- A malformed `qa_branch_sync` value in `project.yaml` (hand-editable) →
  treated as absent; a divergence routes and rewrites a valid record instead
  of crashing planning.
- A planner that generates no QA spec → the spec gate ends INPUT_REQUIRED
  with `overall` written.

## Pass / fail criteria

A story passes when the observable outcome above is what the user sees, on
the surface named (TUI log/status/note/window, `qa_status.json`, `pm pr
auto-sequence` output, or the workdir/upstream git state). It fails when:

- QA plans against, or launches workers on, a tree that does not contain the
  upstream head the sync was supposed to bring in;
- pm merges, resets, force-pushes or discards local work (dirty files,
  untracked files, local-only commits) without the user doing it;
- a run that stopped before scenarios leaves `qa_status.json` without an
  `overall`, so a driver keeps reporting `running: qa`;
- imported application code reaches planning/sign-off while the old review
  or sign-off evidence stays adoptable;
- a hold message does not name a remedy the user can actually perform for
  the surface they are on;
- the planner starts without the configured provider environment after the
  sync, or a provider secret is printed into the command string / log;
- `pm pr auto-sequence` keeps reporting `running: qa` (or relaunching a
  doomed detached driver) when no pm session exists.

## Ambiguities (resolved)

1. **Diverged but a clean merge would be possible — should pm merge?** No.
   Only behind-only is automatic; divergence gets the review route, whose
   pull step performs the merge. Resolved from the PR description.
2. **What counts as "not covered by the prior review"?** Any non-`pm/` path
   imported by the fast-forward. There is no durable reviewed-sha record, so
   the classification is deliberately conservative.
3. **Dirty workdir + behind:** git's own fast-forward safety applies — it
   carries non-overlapping edits and refuses otherwise (→ hold). Dirty +
   diverged always holds (an agent merge in a dirty tree is unsafe).
4. **Imported code: plan first and fail later, or stop before planning?**
   Stop before planning — review may change the code, so a run against it is
   wasted and is not evidence.
5. **`pm qa run` has no planning phase, so no sync:** intentional. The
   shared handoff guard therefore must name a remedy that works without the
   sync.
