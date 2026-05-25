# QA Spec: pr-ca6981c — pm merge's git stash/pop corrupts project.yaml + leaks stashes

## Context

`pm pr merge` reconciles uncommitted `pm/project.yaml` edits across a git merge.
Previously it used a *text* `git stash push` / `git stash pop`. When another pm
process mutated `project.yaml` between the stash and the pop (or the merged-in
branch touched the same line), the pop hit a 3-way text conflict and git wrote
raw conflict markers into `project.yaml`. Because `project.yaml` is the
lock-protected source of truth, this broke `store.load()` and every subsequent
pm command (`list`, `tui`, `sync`, `merge`) until hand-fixed.

The fix keeps `project.yaml` out of the text stash entirely: local edits + the
committed ancestor are captured as structured data, the file is reverted so the
merge replaces it cleanly, and the local edits are re-applied afterward via a
structured 3-way merge under the existing lock (`store.three_way_merge` inside
`store.locked_update`). Plus: leaked auto-stashes are reaped, `store.load` gets a
conflict-marker guard, a genuine non-project.yaml stash-pop conflict launches a
resolution window, and `pr start`'s gh_pr_number persist gets lock-contention
backoff.

## User-facing surfaces

- `pm pr merge <id>` — local backend merges branch→base in the PR workdir then
  propagates; github backend merges via `gh` then pulls into the repo dir. Both
  paths stash/reconcile dirty `project.yaml` and other dirty files.
- Any pm command that loads state (`pm pr list`, `pm pr show`, `pm tui`,
  `pm pr sync`) — exercises `store.load`'s conflict-marker guard and the
  preserved "no project" (FileNotFoundError) behavior.
- `pm pr start <id>` — github backend creates a draft PR then persists its
  number with lock-contention backoff.
- TUI / picker-driven merge — a merge action that hits a stash-pop conflict now
  launches a resolution window (driveable via the bundled fake-claude).

## Shared resources (concurrency inventory)

- `pm/project.yaml` + `project.yaml.lock` — read by every command, written under
  the advisory lock; concurrent edits across a merge are the root failure mode.
- The git stash stack in the repo / workdir — auto-stashes created, popped,
  reaped; pre-existing leaked auto-stashes and unrelated WIP stashes coexist.
- The TUI merge-lock marker — set while pm files are reverted, cleared after.
- The resolution merge window (tmux) launched on a genuine stash-pop conflict.

## 1. Requirements (Given / When / Then)

**R1 — Merge never corrupts project.yaml.**
Given a local-backend pm project with a PR in review, where both the merged-in
branch and the local working copy have divergent edits to `pm/project.yaml`,
When the user runs `pm pr merge <id>`, Then `pm/project.yaml` afterward is valid
YAML containing no git conflict markers (`<<<<<<<`/`=======`/`>>>>>>>`).

**R2 — Merge leaves no leaked auto-stash.**
Given the same merge as R1 (success path), When it completes, Then no
`pm: auto-stash for merge` entry remains in `git stash list`.

**R3 — Merged PR finalizes to status=merged with merged_at.**
Given the same merge as R1, When it completes, Then `pm pr show <id>` reports the
PR as `merged` with a non-null `merged_at` timestamp (it no longer sticks in
`in_review`).

**R4 — Both sides' bookkeeping survives the merge.**
Given the merged-in branch advanced one field of the PR record and the local
working copy changed a *different* field (and each side added a distinct PR
note), When the merge completes, Then the reconciled `project.yaml` retains both
field changes and both notes are present (notes are unioned, not clobbered).

**R5 — store.load reports conflict markers clearly.**
Given a `pm/project.yaml` that contains git conflict markers (e.g. from external
corruption), When the user runs any pm command that loads state (`pm pr list`),
Then the command fails with a clear message naming the file, the offending line
number, and remediation — not a raw YAML scanner traceback.

**R6 — "No project" behavior is preserved.**
Given a directory with no `pm/project.yaml`, When the user runs a pm command that
treats a missing file as "no project", Then it reports "no project" normally and
does not crash with a parse error (FileNotFoundError must not be wrapped).

**R7 — Leaked auto-stashes are reaped; unrelated WIP is preserved.**
Given a repo carrying a pre-existing `pm: auto-stash for merge` stash plus an
unrelated WIP stash, When a `pm pr merge` reconciliation runs to completion,
Then the auto-stash entries are dropped and the unrelated WIP stash remains.

**R8 — Genuine stash-pop conflict launches a resolution window.**
Given a local merge where a *non-project.yaml* file is dirty locally and the
merged-in branch changes the same file (so the stash pop will conflict), When
the user merges with resolution windows enabled, Then a resolution session is
launched framed as a stash-pop recovery (the merge itself succeeded; only
restoring the auto-stashed local edits conflicted), `project.yaml` is not
corrupted, and the conflicted stash is retained (not reaped) for resolution.

**R9 — pr start does not orphan a created PR under lock contention.**
Given a github-backend project where `project.yaml.lock` is contended at the
moment `pr start` tries to persist a just-created draft PR's number, When the
persist initially times out but the lock frees within the backoff window, Then
the gh_pr_number is recorded (the PR is not left orphaned with gh_pr_number=null
/ status in_progress).

## 2. Setup

- A throwaway git repo with a `pm/` dir and `project.yaml` (`backend: local` to
  avoid GitHub). See `tui-manual-test.md` for project scaffolding.
- At least one PR in `in_review` with a real workdir/branch so `pm pr merge` has
  something to merge.
- For divergence: commit a `project.yaml` change on the PR branch (or a second
  branch merged in) AND leave a differing uncommitted `project.yaml` edit in the
  working copy before merging.
- For R7: pre-seed the repo's stash stack with one `pm: auto-stash for merge`
  stash and one unrelated WIP stash.
- For R8/R9: the bundled fake-claude stand-in (R8 resolution window) and a
  fake-github / second concurrent writer (R9 lock contention).

## 3. Edge Cases / Failure Modes

- **Concurrent writer during merge:** Given a merge in progress while a second
  actor repeatedly writes `project.yaml` (e.g. `pm pr note add` in a loop),
  When the merge reconciles, Then no corruption, no leaked stash, and both the
  merge result and the concurrent writes survive; every pm command keeps working.
- **Benign `=` / `===` in YAML values:** Given a `project.yaml` whose values
  legitimately contain `=======`-like substrings (but not as a standalone
  marker line), When loaded, Then it loads fine (no false-positive guard trip).
- **Worktree-only dirty project.yaml:** Given `project.yaml` modified in the
  worktree only (porcelain ` M pm/project.yaml`, leading space), When a merge
  computes dirty paths, Then the path is detected intact (no off-by-one mangling
  to `m/project.yaml`) so the structural reconcile path actually engages.
- **Both non-project and project files dirty:** Given both `project.yaml` and an
  ordinary file dirty with no merge overlap on the ordinary file, When merging,
  Then the ordinary file is stashed and restored normally while project.yaml is
  reconciled structurally; nothing left behind.
- **Pre-existing corruption mid-session:** Given a running session whose
  project.yaml gets conflict markers, When the next command loads, Then the
  clear guard error appears (not a traceback), and after manual remediation
  commands work again.

## 4. Pass/Fail Criteria

PASS when, for the merge scenarios: `pm/project.yaml` is valid YAML with zero
conflict markers, `git stash list` shows no leftover `pm: auto-stash for merge`,
the PR reaches `status=merged` with `merged_at` set, both sides' bookkeeping is
retained, and pm commands continue to function after the merge. For the guard:
a clear file+line+remediation message (not a YAML scanner traceback) on a
corrupted file, and unchanged "no project" behavior on a missing file. For the
resolution window: a stash-pop-framed session launches and the stash is retained
without corruption. For pr start: gh_pr_number persists despite a transient lock
timeout.

FAIL on any conflict marker written to project.yaml, any leaked auto-stash, a PR
stuck in_review after a successful merge, a raw YAML traceback for corruption, a
crash on a missing project.yaml, a dropped concurrent note/field, or an orphaned
GitHub PR (created but unrecorded).

## 5. Ambiguities

- **Reproducing the *concurrent* race deterministically at the CLI level.** The
  original incident was a timing race between two sessions. Resolved: the same
  user-visible failure is reproduced structurally (incoming branch + local copy
  both edit project.yaml so the pop would conflict) AND additionally with a true
  concurrent writer scenario; both assert the same observable outcomes. No need
  to win a wall-clock race to exercise the fixed path.
- **R9 (pr start orphan) drivability.** This needs a github backend and lock
  contention timing; it is the secondary (partial) part of the PR. Resolved:
  drive it against fake-github with a concurrent lock holder if available;
  otherwise assert the observable outcome (PR number recorded, not orphaned)
  through whatever github surface the harness supports, and note any gap.
- **R8 resolution window without real Claude.** Resolved: use the bundled
  fake-claude stand-in (see `tui-manual-test.md`) to let the launched window
  reach a verdict deterministically; the observable check is that a stash-pop
  recovery session is launched and the stash/project.yaml invariants hold.
