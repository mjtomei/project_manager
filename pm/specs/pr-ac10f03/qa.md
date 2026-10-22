# QA spec — pr-ac10f03: Sign-off integrates latest base and routes rework before gated merge

Grounded in `pm/specs/pr-ac10f03/impl.md` and the diff (`pm_core/integration.py`,
`pm_core/signoff.py`, `pm_core/cli/pr.py` merge/publish/signoff commands,
`pm_core/tui/{auto_start,signoff_ui,review_loop_ui,qa_loop_ui,tech_tree}.py`,
`pm_core/cli/helpers.py` list rendering, `pm_core/prompt_gen.py`).

User-facing surfaces under test:
- CLI: `pm pr signoff integrate <pr> [--record] [--apply]`, `pm pr signoff record <pr>`,
  `pm pr merge [<pr>] [--no-signoff-check]`, `pm pr auto-sequence <pr>`,
  `pm pr list` (status + sign-off/return verdict icons), `pm pr note list`,
  `pm prompt <pr>`, `pm pr start`. There is no `pm pr show`: per-PR records
  (integration, signoff_return, merge_integrity) are read from `pm/project.yaml`.
- TUI: auto-start / auto-sequence driving start → review → QA → sign-off → merge,
  merge key (`g`) / command bar merge, merge hold (`O`), wait-for-merge, the
  tech-tree sign-off/return marker, log messages for stale / coerced / refused.
- Backends: `local`, `vanilla` (bare remote), `github` (via `pm fake-github`).
- Agent prompts: sign-off prompt "Integration" section; impl/review/QA prompts
  "Returned from sign-off" block.

## 1. Requirements (Given / When / Then)

### Integration check (isolated candidate)
- **R1.1** Given a PR in sign-off whose branch is up to date with master, When the
  user runs `pm pr signoff integrate <pr>`, Then it prints status `up_to_date`
  with the fetched base sha, exits 0, and the PR workdir's branch, HEAD, index
  and working tree are unchanged; `project.yaml` is unchanged (read-only default).
- **R1.2** Given master has advanced with non-overlapping commits since the PR
  branched, When the user runs the integrate check, Then status is `clean`, a
  candidate tree is reported, overlap lists are shown, exit 0, and the PR branch
  still points at the same HEAD (no merge commit created).
- **R1.3** Given master has a commit that edits the same lines as the PR, When the
  user runs the integrate check, Then status is `conflict`, the conflicting paths
  are listed, exit 1, and the PR workdir has no MERGE_HEAD, no conflict markers,
  and `git worktree list` shows no leftover temporary worktrees.
- **R1.4** Given the same, When the user runs `--record` from the base pm dir, Then
  `pm/project.yaml` carries the integration record (head, base sha,
  status, conflicts) and `$CAP/integration.json` exists with full context.
- **R1.5** Given a clean moved base, When the user runs `--apply`, Then a merge
  commit "Integrate master@<sha8> into <branch>" is added to the PR branch in the
  workdir, master itself is not changed, and nothing is pushed.
- **R1.6** Given a conflicting base, When the user runs `--apply`, Then nothing is
  merged into the PR branch (no half-merge) and the command exits 1.
- **R1.7** Given the repo has `rerere.enabled` (and `rerere.autoUpdate`) and the
  same conflict was once resolved by hand in a PR workdir (shared rr-cache),
  When the integrate check runs, Then it still reports `conflict` with the
  conflicting paths (the recorded resolution is not replayed into the
  candidate, and it is not reported as "candidate merge failed").
- **R1.8** Given several integration checks for PRs of one repo start at once
  right after master moves, Then all succeed (they serialize on
  `<git-common-dir>/pm-integration.lock`, each with its own fetch ref and a
  uniquely named temp worktree); none fails with ref-lock / bad-object /
  worktree-admin errors and no temp worktrees are left behind. If another
  holder keeps that lock past 300 s, the check proceeds unserialized with a
  "integration lock ... busy; proceeding" log warning rather than hanging.
  Lock handling is shared with the per-PR sign-off step lock
  (`store.bounded_flock`, review 6d73 i1).

### Sign-off launch & routing
- **R2.1** Given a PR reaches sign-off (TUI auto-start or `pm pr auto-sequence`),
  When the sign-off window launches, Then an integration check is recorded for
  the current HEAD and the sign-off prompt contains an Integration section
  naming the target, base revision, status/conflicts, the re-check command and
  the rule that the agent must not merge/push the base itself.
- **R2.2** Given a conflicted integration, When the router emits SIGNOFF_MERGE,
  SIGNOFF_REVIEW or SIGNOFF_REQA, Then pm records SIGNOFF_IMPL (coerced, reason
  shown in TUI log / project.yaml `signoff_return`) and the PR goes back to `in_progress`.
- **R2.3** Given a clean, moved base, When the router emits SIGNOFF_REVIEW (or REQA),
  Then pm merges the base into the PR branch, the PR moves to `in_review` (or
  `qa`), a `signoff_return` record (verdict, hop, reason, reviewed head,
  integration, applied merge sha, awaiting=<hop>) is stored, and the next
  review/QA session prompt contains a "Returned from sign-off" block.
- **R2.3a** Given pm merged a clean moved base into the PR branch on a bounce,
  When the routed review/QA (or impl) session starts, Then its "Returned from
  sign-off" block names the merge commit and a `git diff <base_sha> HEAD`
  command; running that command in the workdir shows only the PR's own
  changes, while the prompt's usual `origin/<base>...HEAD` diff (stale workdir
  base ref) also lists the merged base commits (review 6d73 i1).
- **R2.4** Given an integration check that failed (fetch error / missing workdir),
  When the router emits SIGNOFF_MERGE, Then pm records SIGNOFF_BLOCKED with the
  error as reason and does not offer the PR as ready to merge.
- **R2.5** Given a returned PR, When the routed step relaunches, Then it is a
  *fresh* session (impl `--fresh`, new review iteration, new QA run) — an old
  idle impl session, an old review PASS transcript or an old `qa_status.json`
  PASS written before the return is never adopted — and `awaiting` clears once
  that step launches.
- **R2.6** Given the reworked PR passes review/QA again, When it returns to
  sign-off, Then a new sign-off run is launched (not the old verdict), and the
  new sign-off prompt shows "Previous sign-off return".

### Approval binding
- **R3.1** Given a SIGNOFF_MERGE recorded against HEAD H and base B, When HEAD
  changes (new commit) or base moves past B, Then `pm pr merge` refuses and the
  sign-off driver relaunches sign-off (TUI log: "stale (<reason>) — re-running").
- **R3.2** Given a legacy approval (SIGNOFF_MERGE without integration binding —
  e.g. a project.yaml from before this PR), When the user merges, Then the merge
  is refused and an integration-aware sign-off is re-run.
- **R3.3** Given a sign-off report without `pm-signoff-head`/`pm-signoff-base` meta,
  When the user runs `pm pr signoff record`, Then it refuses ("regenerate with an
  integration-aware sign-off"); with matching meta it records origin=manual
  bound to the integration; a conflicted REVIEW/REQA report is recorded as IMPL.

### Gated merge (all entry points & backends)
- **R4.1** Given a fresh, integration-bound SIGNOFF_MERGE, When the user merges
  (CLI `pm pr merge`, TUI `g`, auto-merge), Then master gets a merge commit whose
  first parent is the approved base sha and whose tree equals the approved
  candidate; PR status becomes `merged`; dependents unblock.
- **R4.2** Given approval against base B and master moved to B' afterwards, When the
  user merges, Then output says "merge refused — … returned to sign-off", exit 1,
  master is untouched, the approval is marked invalidated (`pm pr list` no longer
  shows it as approved), and no merge-resolution Claude window opens.
- **R4.3** Given a merge in progress, When another actor updates master between the
  re-check and the publish, Then local (update-ref CAS / ff-only) and vanilla
  (`--force-with-lease`) refuse and return to sign-off; github records the
  integrity issue on `merge_integrity`, prints it loudly and adds a PR note.
- **R4.4** Given a PR without an approval, When the user runs
  `pm pr merge --no-signoff-check`, Then it refuses ("only recovers an
  already-completed merge"); Given the PR head is already in master, Then it
  finalizes (status merged) without publishing anything new.
- **R4.5** Given a github backend PR approved at head H, When the user merges, Then
  `gh pr merge --match-head-commit H` is used and the result is post-verified.
  `--no-signoff-check` recovery of a merge done on GitHub is also verified against
  the bound approval (WARNING + `merge_integrity` + PR note when it published
  unreviewed commits). The TUI background GitHub sync is not yet verified
  (tracked separately as pr-2e06289; out of scope).
- **R4.6** Given a merge that already published to the base but did not finalize
  (e.g. pm was killed after the publish), When the user re-runs `pm pr merge`,
  Then it finalizes via recovery (status merged) instead of invalidating the
  approval or sending the PR back to sign-off.

- **R4.7** Given the github backend and a remote PR branch carrying commits the
  approved workdir HEAD lacks (pushed by a teammate), When the user or
  auto-merge merges, Then it refuses ("remote PR branch has commits that were
  not signed off"), exit 1, *without* invalidating the approval — auto-merge
  does not loop sign-off runs on the same HEAD. Once those commits are pulled
  into the workdir, the moved HEAD makes the approval stale and a fresh
  sign-off runs.
- **R4.8** Given the github remote PR branch lags the approved head (pm's bounce
  integration merge is local only), When merging, Then pm pushes the approved
  head with a lease and runs `gh pr merge --match-head-commit`, retrying up to
  3 times (1/2/3 s) while GitHub still reports the old head, only after a push
  and only while the base is unchanged.
- **R4.9** Given two PRs of one repository are merged at the same time, Then the
  second publisher prints "Waiting for another merge into this repository to
  finish..." and then re-checks against the moved base (refuses and returns to
  sign-off if the first merge changed what it was approved against).
- **R4.10** Given a local-backend publish, When someone runs `git fetch` in the
  main repo during the publish (rewriting FETCH_HEAD), Then the publish still
  succeeds (pm verifies via a private `refs/pm/merge/<pr>` ref, deleted after).
- **R4.11** Given the main repo is reached through a different spelling of the
  same path (symlink, PR-workdir origin), When merging, Then the approval is
  not invalidated as "target repository changed" (no sign-off loop).
- **R4.12** Given a GitHub merge with an integrity problem, When recovery
  (`--no-signoff-check`, `--propagation-only`) re-runs verification several
  times, Then `merge_integrity` is kept and the PR note is added only once.

### Holds, status & restarts
- **R5.1** Given a PR with a manual merge hold (O) or `--wait-for-merge`, When
  sign-off returns it to impl and it later re-signs MERGE, Then it is still held
  (not auto-merged) until the user releases the hold.
- **R5.2** Given a PR returned from sign-off, When the user views `pm pr list` or the
  TUI tech tree, Then the return verdict icon is shown next to the status until
  the next sign-off decision; CLI and TUI agree.
- **R5.3** Given a sign-off return was recorded, When the TUI is killed and restarted
  before the routed step launched, Then the routed step launches exactly once
  (fresh), with no duplicate impl/review/QA windows.
- **R5.4** Given an IMPL or REVIEW return, When the TUI hop, a TUI restart catch-up
  and `pm pr auto-sequence` ticks race to relaunch the routed step, Then exactly
  one launcher wins (the hop records a launch claim atomically with the
  transition; catch-up paths claim first and skip when claimed); no launcher
  kills another's session. A QA (REQA) return takes no claim.
- **R5.4a** Given a TUI that skipped a return relaunch because the launch was
  claimed by a launcher that then died (e.g. TUI restarted right after its
  hop), When the 180 s claim expires, Then the TUI itself relaunches the
  routed step once without any further user/loop event.
- **R5.4b** Given a CLI `pm pr auto-sequence` tick is mid-step on a PR (holding
  the per-PR sign-off step lock, e.g. a slow git hook during the bounce's
  integration merge), Then the TUI stays responsive (waits at most ~2 s,
  treats the PR as "running") and the step is completed exactly once.
- **R5.5** Given the local backend with the main repo's base checked out and a
  PR branch that committed edits to `pm/project.yaml` (e.g. a cross-PR note),
  When the merge fast-forwards with uncommitted project.yaml state in the main
  repo, Then project.yaml ends with no conflict markers, live state wins, note
  ids from both sides are kept, and the PR is finalized as merged.

## 2. Setup
- Install pm from the PR clone (`./install.sh --local` or venv + `PYTHONPATH`, `pm which`).
- Throwaway git repo per scenario (tui-manual-test.md): `git init`, initial
  commit with a small source file (e.g. `app.py` with a few functions), `pm init
  --backend local --no-import` (or `vanilla` with a local bare repo as `origin`,
  or `github` with `pm fake-github config set`).
- Two overlapping PRs: PR A and PR B both edit the same function in `app.py`
  (conflict) and a third/alternate pair editing different files (clean moved base).
- Drive Claude sessions with `pm fake-claude config set` (signoff verdict
  sequences, review PASS, QA plan/scenario PASS); act as the "implementation
  agent" by committing in the workdir when a fake impl session is used. One
  scenario uses real Claude for impl + sign-off (the required real e2e run).
- Sign-off/merge are driven through TUI auto-start or repeated `pm pr auto-sequence`.
- Watcher off (do not start the D3 watcher).

## 3. Edge cases
- **E1** PR with no commits of its own (HEAD in base) → `in_base`; MERGE coerced to
  BLOCKED; `--no-signoff-check` finalizes.
- **E2** Bounce with dirty workdir or merge in progress → no apply; return record
  carries `apply_error`; next agent integrates.
- **E3** Duplicate ticks: two `pm pr auto-sequence` invocations or TUI + CLI at once
  → one hop, one return record, one launched session.
- **E4** Two PRs both approved against the same base merged concurrently → exactly
  one publishes; the other refuses, invalidates, re-signs, and merges later.
- **E5** Same PR merged twice concurrently → one merges, other prints "already merged".
- **E6** Integration check running while an agent is editing the workdir → the
  agent's uncommitted edits, index and branch untouched; no stray worktrees.
- **E7** Fetch failure (origin unreachable) → status `error`, integrate exits 1,
  MERGE → BLOCKED.
- **E8** Old merge window MERGED verdict for an unpublished PR → `--propagation-only`
  refuses; PR not marked merged.
- **E9** Report hash change after manual record → gate refuses.
- **E11** rerere replay into the candidate (R1.7); concurrent `git fetch` in the
  main repo during local publish (R4.10); symlinked main-repo path (R4.11).
- **E10** `pm pr start` re-launch on a workdir holding pm's unpushed integration
  merge → merge commit preserved (pull uses `--rebase=merges`).

## 4. Pass/Fail criteria
Pass: every Then above observed on the real surface (CLI output/exit code, TUI
render, tmux windows, git history of master and PR branch, project.yaml). Fail if any of: master/remote base receives a commit not equal to
`commit-tree(approved tree, approved base, approved head)`; a merge-resolution
Claude window opens on the publish path; a stale/legacy/invalidated approval
publishes; a PR is marked merged without its head in base; a hold is released by
re-sign-off; a returned step adopts pre-return evidence; duplicate windows for
one PR/step; an unexplained half-merge (MERGE_HEAD / conflict markers) left in a
workdir by pm; temp worktrees leaked.

## 5. Ambiguities (resolved)
- Real e2e run: done with real Claude for impl and sign-off router (the parts whose
  behavior is new); review/QA may use fake-claude PASS to keep it bounded. The
  watcher stays off.
- GitHub base race: detected afterward, not prevented (documented known limit);
  the test asserts detection + note, not refusal.
- A held PR whose base moves is re-signed only when a merge is attempted (gate
  fetches); the driver does not poll the remote — tests attempt the merge.
- `--companion` help and merge-window messages now describe only the post-publish
  repo-update recovery window (wording fixed in review b592 i5).
- Restarted TUI adopting an unverified `review-<pr>` pane is a known gap filed as
  pr-7e00786 — out of scope here.

- Run 3 (after review a52f i1–i8): R1.7, R4.7–R4.12, R5.4a/b added from those
  commits; prior runs' PASS areas are re-run as regression where those
  commits touched them.

- Run 4 (after review 6d73 i1): bounded_flock now backs the integration repo
  lock and the sign-off step lock, store.merge_3way backs the R5.5 project.yaml
  unstash, and R2.3a adds the integrated-diff hint. Those paths (R1.8, R5.4b,
  R5.5, R2.3) are re-run as regression together with the S16 fix (local
  integrate from a PR workdir with an unreachable origin errors, exit 1).

No [UNRESOLVED] ambiguities.
