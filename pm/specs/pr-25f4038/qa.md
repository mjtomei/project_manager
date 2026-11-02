# QA Spec: pr-25f4038 — wait_for_merge as the only manual autostart merge policy

## Nature of this PR

A **behaviour change + bug fix** in the auto-start scheduler. Before this PR
there were two manual-merge policies:

- `stop_before_merge` (the `O` key, the default for a new CLI target): hold
  **only the selected target**. Its prerequisites were still on the
  auto-merge path, so a prerequisite could merge itself before the user ever
  saw the target.
- `wait_for_merge`: hold the target **and its whole unmerged dependency
  closure**.

The PR removes `stop_before_merge` as a distinct state and makes
`wait_for_merge` the single manual policy everywhere — scheduler, CLI, TUI
command bar, `O`, runs popup, help, watcher prompts, status output,
breadcrumb/restart migration and docs. Explicit `auto_merge` (the `A` key /
`--auto-merge`) remains the separate opt-in automatic policy.

The **original bug**: arming a target with `O` (or a plain
`pm autostart add`) let the target's prerequisites auto-merge. The fix must
make the prerequisite wait too. At least one scenario below must reproduce
the user-visible trigger (arm a target whose prerequisite reaches sign-off)
and observe that the prerequisite does **not** merge on its own.

Affected surfaces, for orientation (not a test plan):

| Surface | Where the user sees it |
|---|---|
| Policy/hold computation | `pm autostart status`, runs popup |
| Target defaults / aliases | `pm autostart add`, command bar `autostart add` |
| `O` key | TUI log line, runs popup, `pm tui keys`, help |
| Merge decision | TUI log "signed off … waiting for manual merge … press g", `g` merge |
| Restart migration | TUI restart log + runs popup after `pm tui restart --breadcrumb` |
| Presentation | `?` help, `a` runs popup, `pm tui keys`, `pm autostart --help` |

The scheduler's wait-for-merge machinery itself is not new; this PR makes it
the only manual path and removes the parallel per-PR stop-mark path.

## 1. Requirements (Given / When / Then)

### R1 — A plain CLI add selects wait-for-merge
- **Given** a project with PRs `a` (prerequisite) and `f` (depends on `a`),
  and a running TUI that owns auto-start.
- **When** the user runs `pm autostart add f` with no policy flag.
- **Then** `pm autostart list` shows `f` as `wait-for-merge`, and
  `pm autostart status` shows `a` held by `f` (`wait-for-merge ← f`), not
  `auto-merge`.

### R2 — Re-adding an existing target without a flag keeps its policy
- **Given** `f` is an auto-merge target (added with `A` or `--auto-merge`).
- **When** the user runs `pm autostart add f` with no flag.
- **Then** `f` stays `auto-merge` (a plain add does not silently flip it to
  the manual policy).

### R3 — Explicit wait-for-merge selects the manual policy
- **Given** an existing auto-merge target `f`.
- **When** the user runs `pm autostart add f --wait-for-merge`.
- **Then** `f` becomes `wait-for-merge` and its prerequisite `a` becomes
  held.

### R4 — `--stop-before-merge` is a deprecated alias, never a target-only hold
- **Given** a project with chain `a ← f` and a running TUI.
- **When** the user runs `pm autostart add f --stop-before-merge`.
- **Then** the target is added/changed to `wait-for-merge` (not a separate
  "stop" state), `a` is held, and `pm autostart --help` presents
  `--stop-before-merge` only as a deprecated alias for `--wait-for-merge`.
- **And** combining `--stop-before-merge` with `--wait-for-merge` is
  accepted as the same policy (no conflict).

### R5 — Contradictory policy flags are rejected before any change
- **Given** a project with no targets and a running TUI.
- **When** the user runs `pm autostart add f --stop-before-merge --auto-merge`
  (or `--wait-for-merge --auto-merge`).
- **Then** the command fails with a conflict error and the target set is
  unchanged (nothing added).

### R6 — `O` selects wait-for-merge
- **Given** a TUI with the PR `f` selected and no targets.
- **When** the user presses `O`.
- **Then** the log says the auto-sequence is armed and **will wait for
  merge**; the runs popup (`a`) shows `f` as a `wait-for-merge` target and
  `a` as held by `f`. No "stop before merge" wording appears.

### R7 — A prerequisite never auto-merges under the manual policy (original bug)
- **Given** a chain `a ← f`, auto-start on with `f` armed as a
  wait-for-merge target (`O` or a plain CLI add), and `a` advancing to a
  fresh sign-off (`SIGNOFF_MERGE` on the current HEAD).
- **When** the scheduler's merge decision runs for `a`.
- **Then** `a` is **not** merged: its status stays unmerged and the TUI log
  reports "waiting for manual merge (wait-for-merge: f) — press 'g' to
  merge". This is the regression that must not reproduce.

### R8 — Fresh sign-off still gates every merge
- **Given** a wait target's prerequisite `a` that has reached sign-off but
  whose recorded approval is stale (HEAD moved / no fresh `SIGNOFF_MERGE`).
- **When** the merge decision runs for `a`.
- **Then** `a` neither merges nor claims to be waiting for a manual merge; it
  is routed back through the sign-off step and only a fresh approval reaches
  the manual-merge wait.

### R9 — The target itself waits for a manual merge
- **Given** a wait target `f` whose prerequisites have all merged and which
  itself has a fresh sign-off.
- **When** the merge decision runs for `f`.
- **Then** `f` waits for an explicit user merge (no pause before sign-off,
  no re-arming needed after the prerequisite's merge).

### R10 — Merging a prerequisite starts the next stage exactly once
- **Given** chain `a ← f` with `f` a wait target and `a` waiting for manual
  merge.
- **When** the user merges `a` (the `g` key or `pm pr merge a`).
- **Then** `f`'s implementation is scheduled/started automatically exactly
  once — one implementation window for `f`, no duplicate launch — and no
  other PR is started.

### R11 — Shared prerequisites stay held while any wait target needs them
- **Given** two wait targets `f` and `g` that share prerequisite `a`.
- **When** `a` reaches a fresh sign-off.
- **Then** `a` is held and the status names both holders
  (`wait-for-merge ← f, g`); `a` does not merge.

### R12 — Removing one target releases only the holds it owns
- **Given** two wait targets `f` and `g` sharing `a`, with `a` held by both.
- **When** the user removes `f` (`pm autostart remove f` or the `A` toggle).
- **Then** `a` remains held and in scope because `g` still needs it; the
  removal output reports only what `f` itself released, and `g`'s target,
  window and policy are untouched.

### R13 — Removing a target that is itself another target's prerequisite
- **Given** wait targets `a` and `f` where `f` depends on `a` (so `a` is both
  a target and a prerequisite).
- **When** the user removes `a` as a target.
- **Then** `a` remains in scope and held because `f` still needs it; the
  hold/scope from `f` survives.

### R14 — Dependency edits change holds
- **Given** a wait target `f` that currently does not depend on `b`.
- **When** the user adds the dependency (`pm pr edit f --depends-on ...b`).
- **Then** `b` becomes held by `f` (visible in `pm autostart status`).
- **When** the user removes that dependency again.
- **Then** `b` is released.

### R15 — Legacy saved state migrates fail-closed on restart
- **Given** a TUI restarted with a saved breadcrumb written by the previous
  release — e.g. `targets: [{pr_id: f}]` plus
  `stop_before_merge: ["f", "x"]`.
- **When** the TUI restarts (merge-restart / `pm tui restart --breadcrumb`).
- **Then**:
  - `f` (previously a stop-marked target) comes back as `wait-for-merge`;
  - `x` (a stop mark on a non-target) comes back as a standalone
    `wait-for-merge` target so its manual hold is preserved;
  - the restart log reports the breadcrumb was migrated;
  - no PR is merged, no held/completed QA is resumed, and no duplicate
    session is launched by the migration itself.

### R16 — Legacy single-target breadcrumb migrates to wait, not auto
- **Given** a breadcrumb in the old single-target shape (`target: f`,
  `auto_start: true`, no target list).
- **When** the TUI restarts and consumes it.
- **Then** `f` comes back as a `wait-for-merge` target (an old `O` cannot be
  distinguished from an old `A`, so it fails closed), and the migration is
  reported.

### R17 — Corrupt/mixed-version breadcrumbs cannot enable whole-backlog merge
- **Given** a breadcrumb carrying current-format keys but no usable target
  list (e.g. `targets: null`, a non-list `targets`, or `all_mode` present
  with no `targets`).
- **When** the TUI restarts and consumes it.
- **Then** the unusable list is dropped, only a literal `all_mode: true`
  enables backlog mode, no legacy "all ready PRs" inference happens, the
  migration is reported, and no backlog PR is scheduled or merged.
- **And** a bare-string or otherwise id-less target entry is dropped/reported
  rather than silently auto-merging anything.

### R18 — Migration is idempotent and drops nothing live
- **Given** a breadcrumb migrated once and then saved again by the new TUI.
- **When** the TUI is restarted a second time.
- **Then** the target set, policies and order are unchanged (no second
  migration, no policy drift), and already-merged/closed legacy ids stay
  dropped.

### R19 — Explicit auto-merge is preserved
- **Given** an auto-merge target `g` (added with `A` or `--auto-merge`) whose
  dependency closure is otherwise unheld.
- **When** `g` reaches a fresh sign-off.
- **Then** `g` merges automatically through the sign-off gate without the
  user pressing `g`.

### R20 — A wait hold wins over an auto target; changing policy releases it
- **Given** a wait target `f` and an auto target `g` sharing prerequisite
  `a`.
- **When** `a` signs off.
- **Then** `a` is held (the wait hold wins) and does not auto-merge for `g`.
- **When** the user changes `f` to auto (`pm autostart add f --auto-merge`).
- **Then** `f`'s holds are released, and `a` (now unheld) merges through the
  sign-off gate exactly once.

### R21 — One manual policy is presented consistently
- **Given** a running TUI with no targets.
- **When** the user opens the runs popup (`a`), the help screen (`?`), reads
  `pm tui keys`, and opens `pm autostart --help`.
- **Then** each surface describes exactly one manual policy (`O` waits for
  merge; `--wait-for-merge` is the default; `--stop-before-merge` only as a
  deprecated alias), and no surface offers or mentions "stop before merge"
  as a choice.

### R22 — Command-bar adds default to wait and report wait
- **Given** a running TUI.
- **When** the user types `autostart add f` in the command bar (and
  `autostart add f --stop-before-merge`).
- **Then** both result in `f` being `wait-for-merge`, and the confirmation /
  list summary names `wait-for-merge` (never "stop").

### R23 — Concurrent callers converge on the single policy
- **Given** a running TUI that owns the target set and two PRs `f` and `g`
  that share prerequisite `a`.
- **When** two `pm autostart add` commands are issued at the same time (one
  with the deprecated alias, one plain), or `O` is pressed twice in quick
  succession on `f`.
- **Then** every add is applied, each target ends `wait-for-merge`, `a` is
  held once and names both holders where applicable, and no duplicate
  implementation window is launched.

## 2. Setup

All scenarios start from a throwaway project, never the pm repo itself.

1. Install the branch under test in a venv and make sure `PYTHONPATH`
   points at the editable clone (the container sets `PYTHONPATH=/opt/pm-src`
   which shadows it — override it). Confirm with `pm which`.
2. `mkdir` a fresh test dir, `git init`, then `pm init --backend local
   --no-import`.
3. Create PRs with `pm pr add` and `--depends-on`, e.g. a chain `a ← f` or a
   diamond `f ← c,d; c ← a; d ← a,b`, plus at least one unrelated PR `u` to
   prove it is never scheduled. Note the generated ids.
4. Start the session (`pm session`, ignore the attach failure — no TTY) so a
   TUI owns auto-start. Drive the TUI with `pm tui send`, `pm tui view`,
   `pm tui frames`.
5. For flows that must reach a verdict without a real model, configure
   `fake-claude` for the session: review/QA `PASS`, sign-off `SIGNOFF_MERGE`,
   `_all: {}` for everything else. Use
   `tests/fixtures/fake_claude/example-config.json` as the starting point.
6. For migration scenarios, obtain a *legacy* breadcrumb either by running
   the base commit (master) against the same fixture and letting it write
   `~/.pm/autostart-resume.json`, or by writing the documented legacy shape
   of that file. Restart the PR build's TUI (`pm tui restart --breadcrumb`)
   to consume it. The breadcrumb is not `project.yaml`; hand-editing it to
   simulate an older release is the intended upgrade path.
7. Bootstrap-only project edits (initial PR statuses) are allowed before the
   scenario begins; after that, drive everything through `pm`/TUI.

## 3. Edge cases

- **O twice / rapid O** on the same PR: still one target, still wait, the
  scheduler is nudged, no duplicate window.
- **Plain re-add of an auto target**: policy unchanged (stays auto).
- **Legacy stop mark on a target vs a non-target**: target gains the wait
  flag; non-target becomes a standalone wait target.
- **Legacy stop mark on a merged/closed PR**: dropped (nothing to hold).
- **Legacy stop marks with auto-start off**: dropped; they must not
  re-enable auto-start or launch work.
- **Legacy stop field with an odd type** (a bare string, a mapping/set):
  still yields the ids it plausibly names, migrated in deterministic order.
- **Record-level legacy fields**: `policy: stop_before_merge`,
  `merge_policy`, unknown/empty policy values, `wait_for_merge: false`,
  record `stop_before_merge: true` — all normalise to wait or auto exactly as
  documented, never silently enabling a merge.
- **Empty-string / id-less target entries** in a saved breadcrumb: dropped
  and reported, not turned into a phantom target.
- **Diamond dependencies**: each PR signs off and waits; each manual merge
  starts the next stage exactly once; the unrelated PR never starts.
- **Policy flip wait → auto and auto → wait** releases / re-applies holds
  and runs the merge decision exactly once per change.
- **Stale sign-off** is never reported as ready/waiting for merge.
- **Unknown PR id** on add/remove: rejected before any change.
- **Removing the last target** turns auto-start off (mode `off`) without
  killing running windows.

## 4. Pass / fail criteria

A scenario passes when every Then clause is observed on the user's surface
(TUI pane/log/popup, command output, project state, capture artifacts) and
the captures named in the plan exist and are playable.

A scenario fails when any of these is observed:

- any user-facing surface still offers or reports `stop-before-merge` as a
  distinct policy/state (a deprecated **alias** in `--help` is allowed);
- a prerequisite of a wait target auto-merges, or the target-only hold bug
  reproduces (a prerequisite merging while the user never pressed `g`);
- a merge happens without a fresh `SIGNOFF_MERGE`, or a migration merges a
  PR / resumes held QA / launches a duplicate session / consumes a stale
  sign-off;
- a shared prerequisite is released while another active wait target still
  needs it, or removing one target kills another target's work;
- a corrupt/legacy breadcrumb enables whole-backlog auto-merge or drops a
  manual gate;
- a manual merge of a prerequisite fails to start the newly unblocked
  dependent, or starts it more than once;
- explicit auto-merge stops working, or a wait hold fails to override an
  auto target.

## 5. Ambiguities and resolutions

1. **A legacy stop mark on a PR that was never a target.** Resolved: it
   becomes a standalone `wait_for_merge` target, preserving the manual hold
   (fail closed) — never a target-only hold and never silently auto-merged.
2. **Was a legacy single-target breadcrumb an `O` or an `A`?** Resolved:
   indistinguishable, so it migrates to `wait_for_merge` so a restart can
   never silently turn a manual gate into an auto-merge.
3. **Should `--stop-before-merge` disappear?** Resolved: keep it as a
   documented deprecated alias that maps to wait; it must never create a
   separate target-only hold.
4. **Legacy stop ids for merged/closed PRs.** Resolved: dropped.
5. **Legacy stop marks saved while auto-start was off.** Resolved: dropped;
   restoring them as targets would re-enable auto-start and could launch
   work.
6. **`build_status` receiving a stale `stop_before_merge` input.** Resolved:
   fold it through the same fail-closed migration, so an old caller cannot
   silently permit a merge.
7. **Which "waiting" wording is expected.** Resolved: any wording that
   presents one manual policy ("wait for merge" / "waiting for manual
   merge") is acceptable; the removed "stop before merge" wording must be
   absent. Scenarios assert the presence of the wait wording and the absence
   of a stop *choice*, not exact strings.

No **[UNRESOLVED]** items.
