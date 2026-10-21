# pr-e69afc4 — Dependency-wide merge wait for auto-start (QA spec)

Surfaces under test: the `pm autostart` CLI (add/remove/list/status, text and
`--json`), the TUI command bar (`autostart …`), the TUI `O` / `A` keys, the
TUI runs popup (`a`), the TUI log line, manual merges (`g` in the TUI and
`pm pr merge`), graph edits (`pm pr edit --depends-on`) and the
breadcrumb restart (`pm tui restart --breadcrumb`).

## 1. Requirements

R1. Wait policy targets the final PR only.
- Given a running pm session with a dependency chain (diamond: A, B ready;
  C←A; D←A,B; F←C,D) and auto-start off,
- When the user runs `pm autostart add F --wait-for-merge`,
- Then the command reports `added: F (wait-for-merge)`, `pm autostart list`
  shows F as the only target with policy `wait-for-merge`, and A, B, C, D
  are not listed as targets.

R2. Policy is in place before work starts.
- Given R1's command was just issued,
- When the scheduler runs its first pass,
- Then only A and B start (C, D, F are pending/blocked), and
  `pm autostart status` already shows A–F labelled
  `[wait-for-merge ← F]` (F itself `[wait-for-merge]`), before any PR has
  signed off.

R3. Normal pipeline then wait.
- Given A is running under a wait-for-merge target,
- When A runs implementation → review → QA → sign-off and gets a fresh
  `SIGNOFF_MERGE`,
- Then A is NOT merged; the TUI log shows `✓ A signed off … — waiting for
  manual merge (wait-for-merge: F) — press 'g' to merge`; status/popup
  reason reads `signed off (fresh SIGNOFF_MERGE); waiting for manual merge
  (held by F) — press g`; A's project status stays unmerged.

R4. Manual merge advances the chain without another command.
- Given A and B are both signed off and waiting,
- When the user merges A manually (`g` or `pm pr merge A`),
- Then A becomes merged, the TUI reloads, and C starts automatically; D
  stays blocked with a reason naming B (`blocked on B (…, wait-for-merge ←
  F)`). When B is then merged, D starts. No `pm autostart` command is
  needed between merges.

R5. Final target completes.
- Given every prerequisite is merged and F has signed off and is waiting,
- When the user merges F,
- Then F is merged and the target is completed/pruned; auto-start reports
  off/no targets (or the target as completed) and nothing else starts.

R6. Shared dependencies with mixed policies.
- Given a wait target F whose closure contains X, and an `--auto-merge`
  target G that also depends on X, plus an unrelated `--auto-merge` target U,
- When X and U each reach fresh sign-off,
- Then X waits for manual merge (held by F) even though G is auto-merge; U
  auto-merges; status shows G `[auto-merge]`, X `[wait-for-merge ← F]`.

R7. Explicit per-PR stop preserved.
- Given `pm autostart add P --stop-before-merge` (no wait target),
- When P signs off,
- Then P stops with the `ready to merge (auto-sequence armed …)` line and
  its prerequisites still auto-merge (pre-existing behaviour unchanged).

R8. Removing / changing a wait target releases only inherited holds.
- Given wait target F holding X and Y, X also explicitly stopped, and Y
  also in the closure of a second wait target H,
- When the user runs `pm autostart remove F` (or re-adds F with
  `--auto-merge` / `--stop-before-merge`),
- Then the output prints `released merge hold: …` listing only PRs no longer
  held by anything; X keeps `[stop-before-merge]`, Y keeps
  `[wait-for-merge ← H]`; a previously parked signed-off PR whose hold is
  released now proceeds to auto-merge (if in scope of an auto target).

R9. Re-adding without a flag preserves policy.
- Given F is a wait-for-merge target,
- When the user runs `pm autostart add F` with no policy flag,
- Then F is reported `unchanged`/already a target and still
  `wait-for-merge`; no holds released.

R10. Contradictory flags rejected without partial change.
- Given any auto-start state,
- When the user passes two different policy flags (CLI or command bar),
- Then the command fails with `conflicting_flags` (CLI exit 1, JSON
  `error: conflicting_flags`), and `pm autostart list/status` are unchanged.
  Policy flags on `remove`/`list`/`status` are rejected as usage errors.

R11. Graph changes.
- Given wait target F,
- When the user adds a new unmerged prerequisite N to a PR in F's closure
  (`pm pr edit … --depends-on`),
- Then N appears in status as `[wait-for-merge ← F]` and is held when it
  signs off; removing the edge releases N (unless otherwise held).

R12. Restart restoration.
- Given a wait target mid-chain (some PRs merged, one waiting),
- When the user restarts the TUI with `pm tui restart --breadcrumb`,
- Then after restart `pm autostart list` still shows F `wait-for-merge`,
  the waiting PR is still held, and the next manual merge still advances
  the chain.

R13. Fresh sign-off still required.
- Given a held PR that signed off, then its branch HEAD moves (new commit),
- When the scheduler/sign-off driver runs,
- Then status shows the sign-off as stale; the PR does not claim "waiting
  for manual merge" until a fresh `SIGNOFF_MERGE` on the new HEAD;
  `pm pr merge` on it before re-sign-off is refused by the sign-off gate.

R14. TUI presentation.
- Given wait target F with held deps,
- When the user opens the runs popup (`a`),
- Then each row shows its effective policy label (`wait-for-merge`,
  `wait-for-merge ← F`, `stop-before-merge`, `auto-merge, held`) and the
  hold reason; the command-bar `autostart list` summary shows
  `F (wait-for-merge)`.

R15. Docs.
- When the user runs `pm autostart --help` / `pm autostart add --help` or
  reads README "Auto-start targets",
- Then `--wait-for-merge` and the single-final-target manual-merge
  progression are described.

## 2. Setup

- Install pm from this branch (`./install.sh --local` or venv editable,
  `PYTHONPATH` pointed at the clone; `pm which` confirms).
- Throwaway project per `tui-manual-test.md` (`pm init --backend local
  --no-import`), PRs with `--depends-on` forming a diamond A,B→C(A),D(A,B)→F
  (C,D); extras as scenarios need.
- `pm session` started in tmux; fake-claude configured so impl/review/QA/
  sign-off reach verdicts deterministically (review PASS, qa_* PASS/VERIFIED,
  signoff SIGNOFF_MERGE). Optionally `pm set skip-qa on` to shorten the
  pipeline (then sign-off follows review PASS).
- Manual merges via `g` in the TUI or `pm pr merge <id>` run from a pane in
  the test session.

## 3. Edge Cases

E1. Given two wait targets sharing dep X, when one is removed, then X stays
held by the other; removing both releases X.
E2. Given a dep that is itself an `--auto-merge` target inside a wait
target's closure, then its row shows `auto-merge, held` and it does not
auto-merge.
E3. Given `pm autostart add F --wait-for-merge` where F was previously a
stop target, then F's own stop mark is dropped and its policy is now
wait-for-merge (reported as policy change).
E4. Given `--wait-for-merge` repeated twice in one command, then accepted
(not a contradiction).
E5. Given an unknown or already-merged PR id together with a valid id and
`--wait-for-merge`, then the whole command is rejected and nothing changes.
E6. Given auto-start is cleared (`autostart clear`), then derived wait holds
vanish, explicit stop marks remain.
E7. Given two manual merges performed nearly simultaneously (A and B), then
C and D each start exactly once (no duplicate windows).
E8. Given the `O` key pressed on a wait target, then its policy changes
wait→stop and released deps are reported in the log.
E9. Given plain `pm tui restart` (no breadcrumb), then auto-start state is
not preserved (pre-existing behaviour; not a regression).
E10. Given a CLI `add --wait-for-merge` racing a command-bar / key policy
change, then each command gets its own reply and final state equals the
last applied command, with consistent list/status output.

## 4. Pass/Fail Criteria

Pass: every Then clause observable in CLI output / TUI screen / log line /
project status; no held PR is merged by the scheduler; every manual merge of
a held PR starts its newly-ready in-scope dependents without further
commands; rejections leave state byte-for-byte identical in `list --json`.
Fail: any held PR auto-merges; prerequisites of a wait target start/merge
without hold labels; a dependent fails to start after manual merge; a
released hold leaves a signed-off PR parked forever; a rejected command
partially changes state; policy lost across breadcrumb restart; stale
sign-off claims "waiting for manual merge".

## 5. Ambiguities (resolved)

- "Restart mechanism" = merge-restart breadcrumb, user-triggerable with
  `pm tui restart --breadcrumb`. Plain restart drops auto-start state by
  design.
- When a PR is both explicitly stopped and wait-held, its effective policy
  label is stop-before-merge and held_by still lists the wait target(s).
- "Waiting for manual merge" is shown via log line + status/popup reason; no
  new tech-tree marker.
- Manual merge via a conflict-resolution window's MERGED message is out of
  scope (pr-c50d365); scenarios use conflict-free merges.
- A `--auto-merge` target inside a wait closure is held (shared-dep rule).

No [UNRESOLVED] items.
