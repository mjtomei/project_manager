# pr-25f4038 — wait_for_merge as the only manual autostart merge policy

## Goal

Delete the `stop_before_merge` policy (a target-only manual hold) and make
`wait_for_merge` the single manual merge policy everywhere: scheduler, CLI,
command bar, `O` key, runs popup, help, status, breadcrumb/restart migration
and documentation. `auto_merge` remains the separate explicit opt-in.

Under `wait_for_merge`, a target **and every unmerged transitive
prerequisite** run implementation → review → required QA → fresh sign-off and
then wait for an explicit user merge (`g` / `pm pr merge`). Merging a
prerequisite starts newly unblocked dependents automatically, exactly once.
No pause-before-sign-off and no re-arming after each manual merge.

## Current code map (grounding)

| Concern | Location |
|---|---|
| Policy constants, holds, target policy, breadcrumb parse, status builder, labels | `pm_core/autostart_state.py` |
| Scheduler, target add/remove, `O`, breadcrumb save/consume, command handler | `pm_core/tui/auto_start.py` |
| `_stop_before_merge` app state | **removed** (was `pm_core/tui/app.py`; R1) |
| `O` binding | `pm_core/tui/app.py` (`Binding("O", "auto_sequence_pr")`, `action_auto_sequence_pr`) |
| Merge decision + hold message | `pm_core/tui/review_loop_ui.py` (`_maybe_auto_merge`) |
| Sign-off driver keys on effective policy | `pm_core/tui/signoff_ui.py` (`_acted` key) |
| CLI group / `add` flags / docs | `pm_core/cli/autostart.py` |
| `pm tui keys` help | `pm_core/cli/tui.py` |
| Help screen + runs popup empty text/policy styles | `pm_core/tui/screens.py` |
| README autostart section | `README.md` |
| Regression help checklist | `pm/qa/regression/help-keybindings.md` |
| Tests | `tests/test_autostart_single_manual_policy.py` (new), `test_autostart_merge_wait.py`, `test_autostart_multi_target.py`, `test_autostart_retarget_regression.py`, `test_log_message_force.py`, `test_log_pane_backlog.py`, `test_tui_signoff_handoff.py` |

Existing `wait_for_merge` machinery already provides the desired scheduler and
hold semantics (`merge_holds` closure derivation, `_maybe_auto_merge` hold
gate, status `held_by`). The change is to make it the *only* manual policy and
remove the parallel explicit-mark path.

## Requirements (grounded)

### R1 — One manual policy in the data model

- Remove `POLICY_STOP` and the `app._stop_before_merge` set.
- `autostart_state.POLICIES = (POLICY_AUTO, POLICY_WAIT)`.
- `POLICY_FLAGS = {POLICY_AUTO: "--auto-merge", POLICY_WAIT: "--wait-for-merge"}`.
- A target record's policy is now solely `WAIT_KEY` presence:
  `target_policy(record)` → `POLICY_WAIT` iff `record[WAIT_KEY]` truthy,
  else `POLICY_AUTO`.
- `merge_holds(prs, targets)` → only wait targets hold their unmerged,
  non-terminal closure. Remove the `stop` parameter and the
  `"explicit"` hold member.
- `effective_policy(pr_id, holds)` → `POLICY_WAIT` iff held, else `POLICY_AUTO`.
- `held_by_text` only renders `wait-for-merge ← T1, T2`.
- `build_status`/`collect_status_inputs` no longer emit `stop_before_merge`
  or `explicit_hold`.
- `_signed_off_reason`, `policy_labels`, `format_text` have no
  stop-before-merge branch.

### R2 — New selections are wait_for_merge

- `add_targets` default for a **new** target becomes `POLICY_WAIT`
  (`default_policy: str | None = POLICY_WAIT`). Re-adding an existing target
  with `policy=None` still keeps its current policy.
- `O` / `auto_sequence_for_pr` sets `policy=POLICY_WAIT` and logs
  `Auto-sequence armed for <pr> (will wait for merge)`.
- `A` / `toggle` still adds with `default_policy=None`, i.e. a new target is
  `auto_merge`; removing an existing target is unchanged.
- CLI `pm autostart add X` (no policy flag) results in `wait_for_merge`
  because it relies on the owner's new-target default; the CLI must not send
  an explicit flag on re-add (that would flip an existing auto-merge target).
- Command-bar `autostart add X` likewise defaults to wait.

### R3 — Legacy inputs are accepted as an alias, never a separate hold

- CLI `--stop-before-merge` is kept as a deprecated alias for
  `--wait-for-merge` (help text says so). It maps to `POLICY_WAIT` and the
  CLI sends the canonical `--wait-for-merge` to the owner.
- Command-bar `--stop-before-merge` maps to `POLICY_WAIT`.
- Combining `--stop-before-merge` with `--wait-for-merge` is the same policy
  (not a conflict); combining either with `--auto-merge` is rejected before
  any change.
- No code path may leave a target-only hold or drop the manual gate.

### R4 — Safe, idempotent migration of saved state

`autostart_state.targets_from_breadcrumb(data, prs=None)` normalises records
and folds the legacy fields:

- Legacy `stop_before_merge: [ids]`:
  - id already a target → force `WAIT_KEY` on its record;
  - id not a target → add it as a wait target (`source="legacy-stop"`),
    preserving standalone manual holds (and now holding its closure too);
  - terminal (`merged`/`closed`) ids are dropped (nothing left to merge);
  - missing ids are kept (fail closed; the scheduler's normal
    missing-target prune owns them later);
  - a wrongly typed field still yields the ids it plausibly names (a
    non-empty string, a mapping's keys), and unordered inputs (the old
    in-memory `set`, mapping keys) are sorted so the migrated target order
    is deterministic; a list/tuple keeps its recorded order.
- Legacy single-target breadcrumb (`target: X`, no stop list) cannot tell
  `O` from `A`; fail closed and migrate it to a `wait_for_merge` target.
- A bare-string entry in `targets` (no pm version wrote one) has an unknown
  policy; fail closed to `wait_for_merge` and report `migrated`.
- A list entry with no recoverable id (wrong type, an empty string, or a
  record missing `pr_id`) is dropped — there is nothing to hold — but still
  reports `migrated`, so the corrupt shape surfaces in the restart log.
- Current-format keys without a usable `targets` list (a non-list `targets`
  value, `targets: null`, or `all_mode` present with no `targets` key) are
  corrupt/mixed-version: drop the unusable list, honour only a literal
  `all_mode: true`, and never fall back to the legacy "all ready PRs"
  inference, so a bad breadcrumb cannot silently enable whole-backlog
  auto-merge. All three shapes are handled identically.
- `add_targets` runs *both* `policy` and `default_policy` through the legacy
  alias map and rejects an unknown value, so a bad default cannot fall
  through to the no-flag branch and drop a manual gate.
- Legacy record fields are normalised:
  - `wait_for_merge` truthy → `WAIT_KEY`; falsy → removed (and reported as a
    legacy field — current records never carry a falsy flag);
  - `policy` / `merge_policy` == `auto_merge`/`auto-merge` → no flag;
    anything else (`stop_before_merge`, `wait_for_merge`, unknown, empty,
    null) → fail closed (`WAIT_KEY`);
  - record-level `stop_before_merge` truthy → `WAIT_KEY`.
- `migrated` is True whenever any legacy shape/field was interpreted.
- Calling the parser twice on its own output is a no-op (idempotent).

`save_breadcrumb` stops writing `stop_before_merge`; `consume_breadcrumb`
stops restoring `_stop_before_merge` and uses the migrated target map.
`build_status` defensively folds a stale `stop_before_merge` input through
the same migration helper (fail closed) rather than ignoring it.

### R5 — Scheduler/merge semantics unchanged for wait targets

- Only `wait_for_merge` targets hold their closure; no other target or PR is
  held unless it is in an active wait target's closure.
- A shared prerequisite stays held while any active wait target needs it.
- Removing/changing one target releases only the holds it owns.
- Manual merge of a prerequisite still triggers `check_and_start`, starting
  newly ready dependents once.
- Fresh sign-off remains mandatory before any merge (existing gate).
- A wait target's PR is never auto-merged; a prerequisite is never
  auto-merged under the manual policy.
- Explicit `auto_merge` targets continue to auto-merge through the sign-off
  gate; a hold from a wait target still wins over an auto target.

### R6 — Consistent user-facing presentation

- `pm tui keys`: `O  Add selected PR as target, wait for merge (repeat: re-arm)`.
- Help screen: `O  Auto-start target (wait for merge)`.
- Runs popup empty state: `Add a target with O (wait for merge) or A on a PR, …`.
- `pm autostart --help` documents two policies: `wait-for-merge` (default)
  and `auto-merge`, with `--stop-before-merge` shown only as deprecated.
- Command-bar `USAGE`, handler docstring, `_list_summary` and confirmation
  labels no longer say "stop".
- README autostart section rewritten around one manual policy.
- `pm/qa/regression/help-keybindings.md` updated.
- `pm pr auto-sequence --help` no longer says "stopping before merge" (that
  driver reports `ready_to_merge` and never merges); `qa_loop_ui` and the
  sign-off hand-off tests describe O as waiting, not stopping.

### R7 — Preserve unrelated state

Source, dirty workdirs, running agents/windows, QA/evidence, model
assignments, spec-review settings and unrelated targets are untouched.
Migration never merges, never resumes held/completed QA, never launches a
duplicate session and never consumes a stale sign-off.

## Implicit requirements

- Every caller of the changed signatures must be updated:
  `autostart_state.merge_holds`, `target_policy`, `effective_policy`,
  `targets_from_breadcrumb`, `auto_start.merge_holds`/`target_policy`, and
  all tests/fakes that set `_stop_before_merge`.
- `app._stop_before_merge` must not be read via `getattr` anywhere; a stale
  attribute on old fakes must be harmless but unused.
- Status JSON `policy` values become only `wait_for_merge` / `auto_merge`;
  the CLI list/status text and popup labels must agree.
- The sign-off driver's once-per-`(verdict, sha, policy)` key still changes
  when a policy flips (wait ↔ auto), so a released hold re-runs the merge
  decision exactly once.
- `check_and_start` no longer prunes merged ids from a stop set; wait holds
  are already derived from the current graph/status.
- Tests that assert the removed behaviour must be rewritten to assert the
  new single-policy behaviour, not merely deleted, so regressions are
  covered (default wait, O wait, legacy alias, breadcrumb migration,
  shared/diamond holds, removal releases, fresh sign-off, one-shot start).

## Ambiguities and resolutions

1. **What happens to a legacy stop mark on a PR that is not a target?**
   Resolved: migrate it to a `wait_for_merge` target. This preserves the
   manual hold (fail closed) and satisfies "must not preserve a separate
   target-only hold" / "including dependencies and shared targets".
2. **Legacy single-target breadcrumb (`target: X`) — was it O or A?**
   Resolved: cannot be distinguished; migrate to `wait_for_merge` so a
   restart can never silently turn a manual gate into an auto-merge.
3. **Should `--stop-before-merge` stay visible?**
   Resolved: keep it as a documented deprecated alias; it maps to wait and
   never creates a separate hold.
4. **Should `build_status` keep accepting `stop_before_merge`?**
   Resolved: yes, defensively, folding it through the migration helper so a
   stale caller cannot silently permit a merge. It is not a distinct state.
5. **What about legacy stop ids that are merged/closed?**
   Resolved: drop them; there is nothing left to hold or merge. Missing ids
   stay as targets (fail closed) and are pruned by the existing scheduler
   rule when the PR is genuinely gone.
6. **Legacy stop marks in a breadcrumb whose auto-start was off?**
   Resolved: drop them (still report `migrated`). Restoring them as targets
   would re-enable auto-start on restart and could launch work; with
   auto-start off there is no scheduler/merge path for a hold to gate.

No **[UNRESOLVED]** items.

## Integration with #260 / pr-22ea6a2 (`z a` fresh-autostart handoff)

That PR persists a manual-policy choice in its fresh marker
(`pr[FRESH_KEY]["policy"] = policy or POLICY_STOP`) and reads it back in
`resume_fresh` (`policy = ... or POLICY_STOP`, unknown → `POLICY_STOP`).
After this PR there is no `POLICY_STOP`: at integration map any persisted or
marker `stop_before_merge` value (and `z O` / `--stop-before-merge`) to
`POLICY_WAIT`, make `fresh_start` default to `POLICY_WAIT`, and fail closed
on an unknown marker policy instead of defaulting to the removed constant.
Preserve that PR's live-session adoption, new-handoff boundary and merge
gate. Do not edit its workdir or depend on unfinished code.

## Edge cases to cover

- O on a target twice: idempotent, still wait, scheduler still nudged.
- `pm autostart add X` default → wait; re-add without flag keeps an
  auto-merge target auto.
- `--stop-before-merge` alone → wait; with `--wait-for-merge` → wait;
  with `--auto-merge` → rejected before any mutation.
- Breadcrumb with `targets` + legacy `stop_before_merge`: stop ids already
  in targets become wait; standalone ids become wait targets; terminal ids
  dropped; unordered legacy inputs (set / mapping keys) migrate in sorted
  order; parse is idempotent.
- Legacy single-target breadcrumb → wait target, `migrated` log.
- Bare-string `targets` entry → wait target, `migrated` log.
- Mixed record `{"policy": "stop_before_merge"}` / `{"wait_for_merge":
  false}` normalisation.
- Shared prerequisite held by two wait targets; removing one keeps the hold
  and reports only the released subset.
- Diamond (`f ← c,d; c ← a; d ← a,b`): each PR signs off and waits; manual
  merges start each next stage exactly once; unrelated PR never scheduled.
- Policy change wait → auto releases the closure holds and lets the
  sign-off driver merge once; auto → wait re-holds.
- Stale sign-off never reported as ready/waiting for manual merge.
- Graph edit adds a new prerequisite to a wait target: it becomes held;
  removing the edge releases it.
- Dependency that is itself a target: removing it while another wait target
  needs it keeps it in scope/held.

## Verification plan

1. Pre-fix manual repro (captures): isolated fixture showing `pm autostart
   add` / O selecting `stop_before_merge` and a stop mark holding only the
   target (prerequisite auto-merges).
2. Failing regressions: new/updated tests asserting default wait, O wait,
   alias mapping, breadcrumb migration and shared/diamond semantics.
3. Fix the code paths above.
4. Focused suites: `tests/test_autostart_merge_wait.py`,
   `tests/test_autostart_multi_target.py`,
   `tests/test_autostart_retarget_regression.py`,
   `tests/test_log_message_force.py`, `tests/test_tui_signoff_handoff.py`;
   then the full suite once after final edits.
5. Post-fix manual capture of the same fixture showing one manual policy.
