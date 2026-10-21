# pr-e69afc4 — Dependency-wide merge wait for auto-start (impl spec)

## Background (current code)

- Targets live in `app._auto_start_targets` (`{pr_id: record}`, record =
  `{added_at, source}`) — `pm_core/tui/auto_start.py`.
- Per-PR merge holds live in `app._stop_before_merge` (a set). A target's
  policy is *derived* from membership (`auto_start.policy_for`). Removing a
  target keeps its stop mark (`remove_targets`); `check_and_start` prunes
  merged PRs from the set.
- Merge decision: `review_loop_ui._maybe_auto_merge` — sign-off gate first
  (`_signoff_gate` / `signoff.merge_gate_refusal`), then
  `pr_id in app._stop_before_merge` → "ready to merge — press g", else
  `_attempt_merge`.
- Sign-off driver `signoff_ui.step` de-dupes terminal hops with key
  `(verdict, sha, auto_start.policy_for(app, pr_id))` and calls
  `_maybe_auto_merge` on `ready_to_merge`.
- Status: `autostart_state.build_status` (pure, inputs from
  `auto_start.collect_status_inputs`) → `status_rows` / `format_text` (CLI)
  and `screens.AutoRunsScreen` (TUI popup `a`). `_policy(pr_id, stop)` is
  the only policy derivation there.
- CLI `pm autostart add` (`pm_core/cli/autostart.py`) sends
  `autostart add IDS [--stop-before-merge|--auto-merge] --reply ID` through
  the session command queue to `auto_start.handle_command`. Both policy
  options share one click dest (last one silently wins).
- Restart: `save_breadcrumb` writes `targets` (full records) + sorted
  `stop_before_merge`; `consume_breadcrumb` restores both, then
  `check_and_start`.
- Manual merge (`g` → `pm pr merge --resolve-window`, or CLI `pm pr merge`)
  finalises `status: merged` in project.yaml and calls
  `trigger_tui_refresh()` → `TechTreeApp._load_state` →
  `auto_start.on_state_loaded(app, old_statuses)` → `check_and_start` when an
  in-scope PR newly became merged/closed. This is the "existing merged-state
  reload trigger" to reuse.

## 1. Requirements (grounded)

R1. **New policy `wait_for_merge`** (`autostart_state.POLICY_WAIT`). CLI:
`pm autostart add <final-pr> --wait-for-merge`; command bar / queue:
`autostart add X --wait-for-merge`. Stored on the *target record* as
`"wait_for_merge": True` — only the named PR(s) become targets; the closure
is not turned into targets.

R2. **Single effective-hold path.** Add pure
`autostart_state.merge_holds(prs, targets, stop) -> {pr_id: {"explicit":
bool, "targets": [wait-target ids]}}` and `effective_policy(pr_id, holds)`.
A PR is held iff it is in `_stop_before_merge` (explicit per-PR hold) or it
is in the closure (`closure()`, target included) of any *active* target
whose record has `wait_for_merge`; merged/closed closure members are not
held (nothing to merge, and they must not show up as "released").
`auto_start.merge_hold(app, pr_id)` and
`auto_start.policy_for(app, pr_id)` (effective) wrap it with live app state;
these are used by:
  - `review_loop_ui._maybe_auto_merge` (merge decision; replaces the raw
    `_stop_before_merge` membership test),
  - `signoff_ui.step` de-dupe key (so a released hold re-acts and merges),
  - `collect_status_inputs` → `build_status` (status/popup/CLI), including
    the "blocked on X (…)" reason of pending dependents.
  A new `auto_start.target_policy(app, pr_id)` returns a target's *own*
  configured policy (wait if the record flag is set, else stop if in the
  set, else auto) for listing/changes.

R3. **Normal pipeline, then wait.** Nothing in impl/review/QA/sign-off
changes. After the sign-off gate passes (fresh `SIGNOFF_MERGE` on current
HEAD) a wait-held PR is not merged; the log shows
`✓ <pr> signed off … — waiting for manual merge (wait-for-merge: <targets>) —
press 'g' to merge`, and status reason reads
`signed off (fresh SIGNOFF_MERGE); waiting for manual merge (held by <T>) —
press g`.

R4. **Manual merge advances.** A manual merge of a held PR is observed via
the existing reload trigger (`on_state_loaded` → `check_and_start`), which
starts newly-ready dependents in scope. No new trigger; no new MERGED-message
bookkeeping.

R5. **Policy established before work.** `add_targets` applies the record
flag/stop set before `_sync_enabled` and before the `check_and_start` worker
is queued; the CLI sends the policy in the same `add` command.

R6. **Shared deps / mixed policies.** Any active wait target whose closure
contains the PR, or an explicit mark, prevents auto-merge. Explicit stop
still wins over auto targets (unchanged). Unrelated targets (closure
disjoint) keep their policy.

R7. **Lifecycle.**
  - New dependencies (graph edits) are held automatically — holds are
    derived from the current `depends_on` closure at decision time.
  - Restart: the flag rides on the target record that
    `targets_to_breadcrumb`/`targets_from_breadcrumb` already round-trip.
  - Removing a wait target or changing its policy releases only its derived
    holds; explicit `_stop_before_merge` marks and holds from other wait
    targets remain (derivation makes this automatic). The change result and
    log line list released PRs (`"released": [...]`).
  - Re-adding a target without a policy flag keeps its existing policy
    (record and stop-set untouched).
  - Setting a target's policy replaces its own previous policy: `--wait-for-
    merge` sets the flag and drops the target's own stop mark;
    `--stop-before-merge` clears the flag and adds the mark; `--auto-merge`
    clears both.

R8. **Contradictory flags rejected atomically.** More than one distinct
policy flag (`--stop-before-merge`, `--auto-merge`, `--wait-for-merge`) →
CLI exits 1 with `error: conflicting_flags` before sending anything;
`handle_command` returns the same error with no state change (guards
command-bar use). Policy flags on non-`add` verbs are rejected as `usage`
(previously silently ignored). Existing all-or-nothing id validation stays.

R9. **Presentation.** Status run entries gain `held_by` (wait targets that
hold it) and `explicit_hold` (bool); `policy` becomes the effective policy
(`stop_before_merge` > `wait_for_merge` > `auto_merge`). Target entries
report their own configured `policy` (may now be `wait_for_merge`) plus
`effective_policy`/`held_by`. One helper, `autostart_state.policy_labels`,
names a row's policy and hold causes for both `format_text` and the popup:
`[stop-before-merge]`, `[wait-for-merge]` (a wait target's own policy),
`[wait-for-merge ← T]` (held by other wait targets), and on target rows
`[auto-merge]` / `[auto-merge, held]` (text output omits the plain
`auto-merge` default). `_list_summary` and `pm autostart list` show the
three-valued target policy; `list` adds `(held by T)` naming only *other*
wait targets that hold the target. Schema stays
`pm.autostart.status/1` (additive fields).

R10. **Docs.** README "Auto-start targets" and `pm autostart --help`/`add
--help` document `pm autostart add <final> --wait-for-merge` and the manual
merge progression.

## 2. Implicit requirements

- The sign-off gate still precedes the hold check: a held PR without a fresh
  `SIGNOFF_MERGE` is handed to sign-off / left to the driver exactly as
  today and never claims "waiting for manual merge".
- `_maybe_auto_merge` still scopes to `in_scope`; holds only matter for
  in-scope PRs anyway (a wait target's closure is in scope by definition).
- `signoff_ui.step`'s key must change when a hold is released (wait→auto or
  target removal), else the PR stays parked forever after the policy
  change; using the effective policy satisfies this.
- When auto-start is disabled/cleared the targets map is empty so derived
  holds vanish; explicit marks remain (existing behaviour).
- The breadcrumb's legacy/string entries get no flag (default not-wait).
- The A key (`default_policy=None`) and O key (`POLICY_STOP`) keep working;
  O on a wait target is an explicit policy change wait→stop (reported).

## 3. Ambiguities (resolved)

- *Where to store the wait policy?* On the target record, not as copies in
  `_stop_before_merge` — copying into the set would make "release only
  inherited holds" impossible to distinguish from explicit marks.
- *Is the wait target itself held?* Yes ("the target and its transitive
  prerequisites").
- *Label when both explicit and wait apply?* Effective `policy` =
  `stop_before_merge` (explicit wins the label) and `held_by` still lists
  the wait targets, so both causes are visible.
- *Setting `--wait-for-merge` on a PR with its own stop mark* drops that
  mark (a target has one policy; `--auto-merge` already drops it). Marks on
  *other* PRs are untouched.
- *"Show waiting for manual merge"* = log line + status/popup reason; no
  new TUI tree marker.
- *Contradiction scope*: distinct policy flags in one command. Repeating the
  same flag is fine.
- *pr-c50d365 coordination*: the end-to-end test merges without a conflict
  window (status flipped to merged on disk, as `pm pr merge` does) and the
  scheduler advances only from the reloaded `merged` status. A conflict
  window's MERGED message for a manual `g` merge is not treated as
  completion here; that remains pr-c50d365. A note will be left on that PR.

No [UNRESOLVED] items.

## 4. Edge cases

- PR already in `_pending_merge_prs` (an auto-merge started before a wait
  target was added): the in-flight conflict resolution continues; the hold
  governs merge *decisions* not yet made. Documented, not changed.
- A dependency that is itself an `--auto-merge` target but inside a wait
  target's closure: held (shared-dep rule); status shows its own target
  policy auto and effective wait ← T.
- Two wait targets sharing a dep: removing one keeps the hold from the
  other; removing both releases it.
- Graph edit adding a new prerequisite to a wait target's closure: held from
  the next decision; removing a dependency edge releases the hold if no
  other cause.
- Final target merging: it's pruned from targets (existing), which releases
  nothing material (its closure is merged).
- `autostart all` mode has no targets → no derived holds (explicit marks
  only), unchanged.
- Restart with the wait target and partially merged chain: breadcrumb
  restores flag; `check_and_start` launches newly ready PRs.

## 5. Tests

New `tests/test_autostart_merge_wait.py`:
- pure `merge_holds` / `effective_policy` (explicit, wait, both, disjoint).
- add/re-add/policy change/remove: released lists, explicit marks kept,
  other target's holds kept, re-add without flag preserves.
- contradictory flags: handle_command + CLI (nothing sent, no state change);
  flags on remove rejected.
- `_maybe_auto_merge`: wait-held not merged with waiting line; stale
  sign-off → not "waiting"; mixed policies; release after policy change.
- signoff_ui.step key re-acts after policy change.
- graph change adds/removes hold; breadcrumb round trip keeps flag.
- status/format_text/popup rows show effective policy + held_by.
- Integration: diamond (a, b ready; c←a; d←a,b; f←c,d), CLI `add f
  --wait-for-merge` through the command-queue handler; scheduler starts a,b
  only; both signed off → waiting, not merged; manual merges via
  project.yaml + `_load_state` reload → `on_state_loaded` → c/d start
  without another autostart command; restart mid-chain preserves policy.
