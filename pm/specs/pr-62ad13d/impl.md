# Implementation Spec — pr-62ad13d

Make `pm pr close` a non-destructive lifecycle action: retain the registry
entry, the remote branch, and the local workdir.

## 1. Requirements (grounded in the codebase)

### R1 — Default close sets `status: closed` and preserves the record

- Current code: `pm_core/cli/pr.py:3426` `pr_close()`. Lines 3477-3487 drop the
  entry (`data["prs"] = [p for p in ... if p["id"] != target_id]`) and reassign
  `project.active_pr`.
- New behaviour: inside `store.locked_update(root, apply)`, fetch the PR with
  `store.get_pr(data, pr_id)` (fresh on-disk state, not the pre-lock snapshot),
  set `pr["status"] = "closed"`, and call `_record_status_timestamp(pr, "closed")`
  (`pm_core/cli/helpers.py:446`). Every other key — `title`, `description`,
  `notes`, `depends_on`, `branch`, `workdir`, `plan`, `gh_pr`, `gh_pr_number`,
  `created_at`, `started_at`, `reviewed_at`, `signed_off_at`, `merged_at`,
  sign-off/merge-evidence fields — is left untouched.
- `_record_status_timestamp` is extended with a `closed` branch that sets
  `closed_at` (mirrors `merged_at`). `updated_at` is always set. No other
  timestamp is touched. The helper also *owns the field's history*: an
  explicit transition to any other status drops `closed_at`, and a transition
  into `closed` only stamps it when the caller's `previous_status` is not
  already `closed` (review b320 i1) — so the field can never name a status
  the PR is not in, and a repeat close/restatement never rewrites the closure
  time.

### R2 — Close the GitHub PR; never delete a branch

- Current code: `gh_ops.close_pr(gh_pr_number, delete_branch=not keep_branch)`
  (`pm_core/cli/pr.py:3457`); `pm_core/gh_ops.py:303` appends `--delete-branch`
  when true.
- New: call `gh_ops.close_pr(gh_pr_number)` (default `delete_branch=False`).
  `gh_ops.close_pr` keeps its parameter for other callers/tests; `pm pr close`
  never passes it.
- Preserve the existing failure tolerance: `SystemExit` raised by `_check_gh`
  (gh missing/unauthenticated) and any other exception are caught, reported as
  warnings, and do **not** abort the local status change.
- No `gh` call when `gh_pr_number` is absent, when `--keep-github` is given, or
  when the local status is already `merged` (a merged GitHub PR cannot be
  closed; see A5).

### R3 — Preserve the workdir and every file in it

- Delete the `shutil.rmtree(workdir)` block (`pm_core/cli/pr.py:3471-3475`).
- No `git clean`, `git reset`, stash/drop, or other filesystem cleanup as a
  side effect of close. `shutil` stays imported for unrelated call sites
  (`pr.py:1031`, `pr.py:1060`, `pr.py:3163`).
- A `workdir` reference that points at a missing path is preserved verbatim.

### R4 — Cleanup remains a separate, explicit operation

Audit of close-adjacent teardown paths (all stay explicit / merged-only):

- `pm pr cleanup` (`pm_core/cli/pr.py:3168`) — explicit; unchanged.
- `pm pr cleanup --resources` → `pr_cleanup.cleanup_pr_resources`
  (`pm_core/pr_cleanup.py:36`) — explicit; unchanged.
- TUI `Y` cleanup (`pm_core/tui/pr_view.py:515`) — explicit key; unchanged.
- `_kill_merged_pr_windows` (`pm_core/tui/sync.py:50`) — fires only for
  `merged_prs` from sync, never for `closed`.  (pr-3d1fa55's
  `_reclaim_terminal_pr_windows` would extend this to `closed`; see A4.)
- `_finalize_merge` (`pm_core/cli/pr.py:1919`) — merge path only.
- `pm_core/tui/auto_start.py` target pruning removes *targets* for terminal
  PRs; it does not delete branches/workdirs.

No new hook, delayed deletion, or fallback is added. The close command itself
must not kill tmux windows/containers either (that is `--resources`).

### R5 — Explicit registry-only removal

Add `--remove` to `pm pr close`:

- Behaviour: close the GitHub PR according to `--keep-github` (skipped when the
  local status is `merged`), then delete the registry entry *instead of*
  recording the closure — no `status`/`closed_at` write on a record that no
  longer exists.
- Never deletes the branch, the workdir, or any file; never the default; never
  implied by another flag.
- When the PR is already `merged`, `--remove` skips the GitHub call (nothing to
  close) and only deletes the record.
- `project.active_pr` is reassigned exactly as today when it pointed at the
  removed PR: first remaining non-terminal PR, else `None`.
- Help text documents it as registry-only.
- Output names the resources that survived (`Kept: branch '...', workdir
  '...'`, only the ones the entry actually had) and, when a workdir is
  retained, says it is no longer tracked by pm — `pm pr cleanup` resolves the
  registry entry, so it cannot reach that directory any more (review c02f
  i14).

### R6 — `--keep-github` kept; `--keep-branch` deprecated no-op

- `--keep-github` keeps its meaning: do not touch the GitHub PR.
- `--keep-branch` is accepted (no error, no removal of the option) and is a
  no-op; branch retention is unconditional. Help text says so explicitly
  ("Deprecated no-op: close never deletes branches").

### R7 — Warn about dependents; never auto-satisfy

- After the status write, compute dependents: entries whose `depends_on`
  contains the closed id and whose own status is not `merged`/`closed`.
- Print a warning (stderr) naming them, e.g.
  `Warning: 2 dependent PR(s) remain blocked by #163: pr-002 (B), pr-003 (C)`.
  With `--remove` the warning instead says the dependents depend on the
  *removed* record (their `depends_on` now names a PR that does not exist), so
  the message must not imply a `closed` status is what blocks them.
- On the default close, follow the warning with a one-line hint naming the two
  ways out (only `merged` satisfies a dependency, so the block is permanent
  until the user acts): reopen the closed PR, or drop it from the dependents'
  `depends_on` with `pm pr edit <id> --depends-on ""`.  With `--remove` the
  hint names only the dependency drop — re-adding mints a new id, so the old
  reference would stay dangling (review c02f i14).
- Do not change dependent statuses, do not add the closed id to any "merged"
  set, do not remove it from `depends_on`.
- `graph.ready_prs` (`pm_core/graph.py:40`) only treats *merged* dependencies
  as satisfied, so closed dependencies keep dependents blocked — no code change
  needed. `autostart_state._derive` (`pm_core/autostart_state.py:426`) reports
  `closed` as done, and `tui/auto_start.py:491` rejects terminal targets.

### R8 — Closed PRs cannot be started (or merged) again

- Auto-start: `graph.ready_prs` only selects `pending` PRs; `auto_start` also
  refuses terminal targets. No change needed.
- `pm pr auto-sequence` (the driver a watcher session ticks) reports `merged`
  and returns today.  `closed` must do the same: report the status and stop
  (exit 0), instead of falling through to `unknown status: closed` (exit 2),
  which a driving session reads as a broken PR (review 8820 i1).
- Manual `pm pr start`: only `merged` is refused today (`pm_core/cli/pr.py:938`).
  Add a `closed` guard next to it: refuse with exit 1 and point at
  `pm pr edit <id> --status pending` to reopen deliberately.
- Manual `pm pr merge` (added in review iteration c02f i2): a closed PR must not
  be publishable either — merging rewrites the closure into `merged` and erases
  the reason the PR was retired. The guard sits *after* the
  `--no-signoff-check` / `--propagation-only` recovery branch so recovering a
  merge that is already published still works if the record was closed
  meanwhile. This matters more now than before the PR: the retained workdir
  means `_infer_pr_id`'s cwd match can resolve a closed PR for an id-less
  `pm pr merge` (its cwd step ignores the status filter).

### R9 — Terminal statuses are durable across GitHub sync

- `pr_sync.sync_from_github` (`pm_core/pr_sync.py:367`) maps an OPEN GitHub PR
  to `in_progress`/`in_review`. That would silently un-close a PR closed with
  `--keep-github` (or when the `gh` call failed), losing the historical record.
- Mirror the existing `qa`/`sign_off` preservation: when GitHub reports OPEN
  and the local status is `closed`, skip the PR (keep `closed`).
- `merged` is terminal in the same way (review c02f i8, incidental fix): a
  local merge record must not be rewritten to `in_review`/`in_progress` by
  GitHub OPEN (the merge landed outside GitHub) nor to `closed` by GitHub
  CLOSED. Either rewrite erases `merged_at`/merge evidence and re-blocks the
  dependents the merge satisfied. The docstring states the rule.
- The same rule must hold inside the locked apply, not only against the
  pre-lock snapshot: `sync_from_github` computes `status_updates` before taking
  the store lock, so a `pm pr close` (or `pm pr merge`) landing during the
  GitHub round-trip would otherwise be overwritten. Both the `save_state`
  apply in `sync_from_github` and the TUI's `startup_github_sync` apply skip a
  status update when the fresh entry is already `merged`/`closed` (a discovered
  `merged` still finalizes — GitHub is authoritative about a merge).
- `pr_sync.sync_prs` (TUI/`pm pr sync`) already ignores non-active statuses;
  unchanged.

### R10 — Help and docs consistency

- `pm_core/cli/__init__.py:617`: update the one-line help to describe the new
  behaviour.
- `pm/qa/regression/command-dedup.md` uses `pm pr close` to delete dummy PRs;
  switch those cleanup steps (and the tool list line) to `pm pr close <id>
  --remove`.
- `pm/qa/regression/multi-window-registry.md` cleanup steps use
  `pm pr close <id> --keep-branch`; the flag remains valid but the entry now
  persists — update to `pm pr close <id> --remove` where the PR must disappear.

### R11 — Regression coverage (`tests/test_pr_close.py`)

All tests use disposable tmp projects and the fake GitHub transport
(`FakeGitHubBackend`, `tests/conftest.py:34/50`); no real PRs, branches, or
workdirs are touched.

1. Default close: exit 0; entry retained; `status == "closed"`;
   `closed_at` set; `updated_at` changed; every other field deep-equal to the
   pre-close entry (notes, `depends_on`, description, branch, workdir, plan,
   gh fields, prior timestamps).
2. GitHub: `backend.calls` contains `["pr","close","42"]` and no
   `--delete-branch`; fake PR state `CLOSED`; with a git-backed fake the
   branch still exists in `backend.git_repo`.  The fake now *emulates*
   `--delete-branch` (it deletes the head branch in the backing repo, review
   c02f i14), so "the branch still exists" is a real assertion rather than a
   vacuous one — a caller that passed the flag would fail it.
3. Workdir: tracked modification, untracked file, ignored file, and a
   `captures/` fixture are byte-identical after close (snapshot hashes).
4. `--keep-github`: no `pr close` call recorded; local status `closed`.
5. `--keep-branch`: accepted; no branch deletion; entry retained.
6. No `gh_pr_number`: no gh call; status `closed`.
7. Absent workdir path: close succeeds; `workdir` reference preserved.
8. Repeat close: exit 0; entry still present; status `closed`; notes not
   duplicated; the GitHub close is re-attempted (so a failed one can be
   retried) while `closed_at` is preserved — review c02f i12,
   `test_repeat_close_retries_the_github_close`.
9. `--remove`: entry gone; workdir and branch intact; `active_pr` reassigned.
10. Dependents: warning names the dependent(s); dependent status unchanged
    (not merged, not started); `ready_prs` still excludes it.  The default
    close also prints the two-ways-out hint (reopen / drop the dependency) —
    review c02f i14, `test_dependents_are_warned_but_not_unblocked`.
11. GitHub failure (`simulate_*` / exception / `SystemExit`): exit 0, warning
    printed, status `closed`, entry + workdir intact.
12. `pm pr start <closed>`: refused with exit 1.
13. `sync_from_github` with GitHub OPEN and local `closed`: status stays
    `closed`.
14. `pm pr merge <closed>`: refused with exit 1 (`reopen` in the message);
    nothing published; status and workdir intact.
15. `pm pr merge <closed> --propagation-only`: recovery still runs (R8
    ordering).
16. Concurrent `--remove` between load and lock: exit 0, entry stays gone, no
    exception, and the command does not claim it removed the record.
17. `pm pr add` of a title+description that matches a retained `closed` entry:
    the duplicate message names the closed status and the reopen command
    (`pm pr edit <id> --status pending`).
18. `active_pr` (A2): a default close moves it off the now-closed entry to the
    first remaining non-terminal PR, becomes `None` when no non-terminal PR
    remains, and closing a PR never moves a pointer that names a different PR
    (`test_default_close_clears_active_pr_when_nothing_remains`, review c02f
    i12).
19. `--remove` on a `merged` PR leaves the GitHub PR alone (a merged GitHub PR
    cannot be closed) and reports the *local* record — "left unchanged (the PR
    is recorded as merged)" — instead of claiming it was left "open", and
    without asserting a GitHub state no call verified.
20. `--keep-github` reports the GitHub PR as "unchanged", never as "open"
    (its GitHub state may be closed or merged), and wins over the merged
    wording on `--remove` (review c02f i7).
21. `--remove` dependent warning says the dependents reference the removed
    record; their status/`depends_on` are untouched and `ready_prs` stays
    empty.
22. Sync race (R9): `status_updates` computed from a stale snapshot do not
    overwrite a `closed` status written before the lock, in both
    `sync_from_github(save_state=True)` and the TUI `startup_github_sync`
    apply — while a merge discovered on GitHub still finalizes over the
    concurrently closed record (review c02f i7).
23. Malformed dependent (review c02f i6): a hand-edited `prs` entry with no
    `id` whose `depends_on` names the closed PR must not crash the dependent
    warning — it runs *after* the status write, so a `KeyError: 'id'` there
    would turn a persisted close into a traceback.  The scan iterates
    `usable_prs`, like every other id-indexing loop.  Covered for both the
    default close and `--remove`.
24. Repeat close of a legacy `closed` entry with no `closed_at` (review c02f
    i8): the entry keeps none — a repeat close moves `updated_at` only.
    `_record_status_timestamp` would otherwise stamp "now", inventing a
    closure time for a PR closed before the field existed (A6: only a *fresh*
    closure records one).  Covered by
    `test_repeat_close_does_not_invent_a_closure_time`.
25. `merged` durability in sync (review c02f i8, R9): GitHub OPEN does not
    reopen a locally `merged` PR and GitHub CLOSED does not rewrite it to
    `closed`; the locked apply also skips a stale update when the fresh entry
    is already `merged` (CLI `sync_from_github` and the TUI
    `startup_github_sync`).  Covered by
    `test_sync_from_github_does_not_reopen_a_merged_pr`,
    `test_sync_from_github_does_not_close_a_merged_pr`,
    `test_sync_from_github_keeps_a_concurrently_merged_pr`, and
    `test_tui_startup_github_sync_keeps_a_concurrently_merged_pr`.
26. Close touches nothing else (review c02f i9): every other PR record,
    `plans`, and every `project` setting except `active_pr` survive verbatim —
    covered by `test_default_close_leaves_unrelated_records_and_settings_alone`.
    The `merged`/`closed` pair is a single named constant
    (`pr_utils.TERMINAL_PR_STATES`) used by the new guards in `pr.py`,
    `pr_sync.py` and `tui/sync.py`, and by the `pm pr list --open` filter, so
    "terminal" cannot drift between the sync paths.
27. One terminal definition, everywhere (review c02f i10/i11): the
    pre-existing duplicates of the pair now derive from
    `pr_utils.TERMINAL_PR_STATES` too —
    `autostart_state.TERMINAL_STATUSES` (aliased; the scheduler/CLI/popup
    importers keep their name), `cli/session.py`'s `_TERMINAL_STATUSES`
    (a set copy), `qa_loop.py`'s four "abort QA against a terminal PR" guards,
    `home_window/pr_list.py`'s open-only filter, and the `qa`/`sign_off`
    preservation tuple in `pr_sync.sync_from_github`.  The two remaining
    literal checks in `pr.py` (`pr_review`, `pr_qa_run_bg`) use the constant
    as well, so no path can disagree about which statuses are terminal.
    `review_loop._pr_is_terminal` (the check that stops a review loop from
    resurrecting a retired PR) is the last one (review 8820 i1): it now uses
    the constant too, so the loop's "stop retrying" set cannot drift from the
    sync guards'.  No behavior change (same two statuses).
28. Cleanup after close (review c02f i10): `pm pr cleanup <id>` is the
    explicit workdir-removal step `pm pr close` points at, and `closed` is now
    its normal input — it no longer prints the "status is 'closed' (not
    merged)" warning.  The registry record survives with `workdir: null`.
    Covered by `test_cleanup_remains_the_explicit_way_to_drop_a_closed_workdir`.
29. Guard messages (review c02f i10): `pm pr merge <closed>` names the
    concrete reopen command (`pm pr edit <id> --status pending`), matching
    `pm pr start`, instead of the unhelpful `--status <status>` placeholder.
    `pm pr sync-github --help` documents that a locally merged/closed record
    is not reopened.
30. Bare `pm pr cleanup` (review c02f i12): with no id the command auto-selects
    the sole PR *with* a workdir among the terminal statuses.  It used to
    consider `merged` only, so the explicit step `pm pr close`'s help points at
    answered "No merged PRs with workdirs to clean up" right after a close.
    Both terminal statuses are now offered, and the no-match/multiple messages
    say "merged or closed".  Covered by
    `test_bare_cleanup_auto_selects_a_closed_workdir` and
    `test_bare_cleanup_reports_when_nothing_terminal_has_a_workdir` (both fail
    before the change).
31. Reopen clears the closure time (review c02f i13): `pm pr edit <id>
    --status pending` — the deliberate reopen path every guard message names —
    drops `closed_at`, so the field never describes a status the PR is not in
    and a later close records a fresh closure time.  Covered by
    `test_reopening_a_closed_pr_drops_the_closure_time`.  Enforced in
    `_record_status_timestamp` (review b320 i1), so *every* explicit status
    transition maintains the invariant rather than the two `pm pr edit` flag
    sites alone: the `$EDITOR` path (`_apply_pr_edit`) and the
    merge-discovered-on-GitHub sync paths (`pr_sync` snapshot + apply,
    TUI startup sync) drop a stale `closed_at` too, and re-stating `closed`
    on an already-closed record keeps the original closure time instead of
    stamping "now" (the A6 rule, now shared).  Covered by
    `test_editor_reopen_drops_the_closure_time`,
    `test_restating_closed_keeps_the_closure_time` and
    `test_merge_discovered_after_close_drops_the_closure_time` (all three
    fail on the previous head).  The helper's contract is also pinned
    directly in `tests/test_cli_helpers.py::TestRecordStatusTimestampClosedAt`
    (review e89f i1): fresh closure stamps, restating keeps, every other
    transition drops, an updated_at-only call leaves it alone, and
    `previous_status` is keyword-only so a positional slip cannot masquerade
    as a previous status.
32. Closing a never-started PR (review c02f i13): a `pending` PR with no
    workdir closes normally (status `closed`, `closed_at` set, `active_pr`
    becomes `None`), since the lifecycle action is about the record rather
    than a workdir having existed.  Covered by
    `test_close_a_pending_pr_records_a_closure`.
33. Close's runtime output (review c02f i13) names the two follow-up actions
    the command deliberately leaves to the user: `Reopen: pm pr edit <id>
    --status pending` and, when a workdir is retained, `Cleanup: pm pr
    cleanup <id> (--force discards uncommitted changes)`.  Pinned in
    `test_default_close_retains_entry_and_lifecycle_fields`.
34. Stale plan premise corrected (review c02f i13): the
    `pm/plans/plan-a35369f.md` item about rulesets blocking branch deletion
    assumed `pm pr close` runs `gh pr close --delete-branch`; a `note` bullet
    records that branch retention is now unconditional and only the
    `pm doctor`/status ruleset check and user docs remain.
35. `--remove` output accuracy (review c02f i14): the line names only the
    resources the entry actually had (`Kept: branch '...'`, plus `workdir
    '...'` when there is one) instead of always claiming "branch and workdir
    kept", and — because `pm pr cleanup` resolves the registry entry — says
    the retained workdir is no longer tracked by pm and must be deleted by
    hand.  Covered by `test_remove_deletes_only_the_registry_entry` and
    `test_remove_without_a_workdir_claims_only_the_branch`.
36. Incidental hardening (review c02f i14), same class as item 23:
    `pm pr cleanup --all` and `pm pr cleanup --prune` walked
    `data["prs"]` raw and indexed `p["id"]`, so a hand-edited entry without an
    `id` raised `KeyError` — for `--all` that happened *inside* the store lock,
    after the workdir had already been deleted.  Both now iterate
    `usable_prs`, like every other id-indexing loop (such an entry is skipped,
    not rewritten).  Covered by `test_cleanup_all_tolerates_a_malformed_entry`
    and `test_prune_tolerates_a_malformed_entry`.
37. `pm pr auto-sequence <closed>` (review 8820 i1): a terminal record reports
    its status and returns (exit 0) exactly like `merged`; it never falls
    through to `unknown status: closed` (exit 2) and never launches another
    phase, so a watcher tick cannot resurrect a PR the user retired.  Covered
    by `test_auto_sequence_reports_a_closed_pr_without_advancing_it` (fails on
    the previous head: exit 2 with "unknown status: closed").
38. `pm pr signoff <closed>` (review 8820 i1) names the deliberate reopen
    (`pm pr edit <id> --status pending`) like the `start`/`merge` guards,
    instead of the generic "sign-off runs after QA" complaint about a status
    the PR is not going to leave on its own.  Covered by
    `test_signoff_refuses_a_closed_pr_and_names_the_reopen`.
39. Close never tears down live resources (review 8820 i2, A4/R4): the
    command and everything it triggers reach none of
    `pr_cleanup.cleanup_pr_resources`, `tmux.kill_window`,
    `kill_pr_windows` or `container.cleanup_pr_containers` — for the
    default close *and* `--remove` — while the workdir survives.  Pinned by
    `test_close_does_not_tear_down_live_resources`.  The spies target the
    bindings the close path actually calls through (review e89f i3):
    `pm_core.cli.pr.kill_pr_windows` *and* `pm_core.cli.helpers.kill_pr_windows`
    — `pr.py` imports the name directly, so patching only the helpers module
    would miss a call from the close command — and the test ends with a
    positive control that fires every spy through its binding, so the empty
    call list is a real guarantee rather than a mis-targeted patch.
40. Close preserves historical evidence beyond title/notes/deps (review 8820
    i2): a `signoff` record (verdict, sha, report hash, integration), a
    `merge_integrity` finding, `spec_pending` and the `qa` state survive
    verbatim.  Covered by
    `test_close_preserves_merge_and_signoff_evidence`.
41. Agent-facing lifecycle docs match the new state (review 8820 i2): the
    watcher prompt's lifecycle list (`prompt_gen.generate_watcher_prompt`)
    describes `closed` — retained as history, terminal like `merged`, never
    satisfying a dependency, with the reopen / drop-dependency ways out — so
    a watcher session cannot read a retired PR as "merge it to unblock".
42. `--remove` output names every resource it orphans (review e89f i2):
    `pm pr cleanup` and its `--resources` mode both resolve the registry
    entry, so after `--remove` the retained workdir *and* any live tmux
    window/container are unreachable through pm.  The note says so, and
    adapts to an entry with no workdir (naming only the live resources)
    instead of claiming a workdir it never had.  Covered by
    `test_remove_says_live_resources_are_no_longer_reachable` and
    `test_remove_without_a_workdir_claims_only_the_branch`.
43. `closed_at` is a lifecycle timestamp in the store backfill (review e89f
    i2): `_validate_pr_statuses` backfills `created_at`/`updated_at` from
    `started_at`/`reviewed_at`/`merged_at`, and now from `closed_at` too —
    closing is the last lifecycle event, so it outranks the mid-lifecycle
    timestamps for `updated_at`.  A hand-edited or imported `closed` entry
    that carries only `closed_at` therefore still sorts by its closure.
    Covered by `test_backfill_from_closed_at` and
    `test_backfill_from_closed_at_alone`.
44. `pm pr cleanup`'s "unexpected status" warning list derives from
    `pr_utils.TERMINAL_PR_STATES` (`("in_review", *TERMINAL_PR_STATES)`)
    instead of re-listing `merged`/`closed` (review e89f i2), so the
    single-definition claim in item 27 holds for that path too.  No behavior
    change.

Existing test `tests/test_pr_enhancements.py:746` (`TestGitHubCloseResilience`)
asserts the *old* destructive outcome (workdir removed, entry removed) and must
be rewritten to assert retention.

## 2. Implicit requirements

- **Lock discipline.** Status mutation happens inside `store.locked_update`
  using the freshly loaded entry; a concurrent `--remove` (entry gone) must not
  raise — re-check `store.get_pr` inside `apply` and no-op. The merged guard is
  re-checked inside `apply` too: a merge landing between the pre-lock load and
  the lock must not be rewritten to `closed` (the pre-lock refusal message is
  reused and the command exits 1).
- **TUI refresh.** Keep `trigger_tui_refresh()` so the TUI reloads; closed PRs
  are already hidden by default (`pm_core/tui/tree_layout.py:172`) and filtered
  from `pm pr list --open` (`pm_core/cli/pr.py:517`).
- **Schema.** `closed` is already a valid status (`pm_core/pr_utils.py:5`) and
  `store` does not validate per-field keys, so `closed_at` is safe.
- **Output stability.** Messages must not claim removal unless `--remove` is
  used; scripts/tests that grepped the old `Removed pr-001` line are updated.
  A concurrent removal is reported as "removed concurrently" for both the
  close and `--remove` paths — never as "Removed registry entry" when another
  process already did it.
- **Retained closed entries are duplicates.** `pm pr add` matches
  title+description against every entry, so a closed record now blocks
  re-adding the same PR.  The duplicate message therefore names the closed
  status and points at `pm pr edit <id> --status pending` (the deliberate
  reopen path) rather than leaving the add silently unfulfilled.
- **No new destructive fallback.** The close path performs no filesystem
  writes at all — the workdir is not even stat'ed any more; the "Kept:" line
  prints the retained references verbatim.
- **Concurrency/ordering.** The `gh` call stays outside the store lock
  (`store.locked_update` must not be held across network calls).
- **Merge/spec gates untouched.** Close never writes sign-off or merge fields;
  a merged PR cannot be closed without `--remove` (A5).

## 3. Ambiguities and resolutions

- **A1 — What does `--remove` do about GitHub?** Resolved: `--remove` is
  registry-only *for local resources*. The GitHub PR is still closed according
  to `--keep-github` (so `pm pr close --remove` reproduces the old
  "close GitHub + forget the entry" flow, minus branch/workdir deletion).
  `--keep-github` takes precedence over every status-specific message: it
  always means "leave the GitHub PR alone" (a merged record cannot be closed,
  so the call is skipped either way). Documented in help text.
- **A2 — What happens to `project.active_pr` on default close?** Resolved: if
  it pointed at the closed PR, reassign to the first remaining non-terminal PR,
  else `None` (mirrors the old reassignment, without ever selecting a
  merged/closed entry). The closed entry itself keeps all its fields.
- **A3 — Add a `closed_at` timestamp?** Resolved: yes, set by
  `_record_status_timestamp(pr, "closed")`, mirroring `merged_at`. Not added to
  `_make_pr_entry` (no schema churn for other PRs).
- **A4 — Should close tear down tmux windows/containers?** Resolved: no.
  Those are live resources owned by explicit `pm pr cleanup --resources`
  (and by merge detection). Close must not silently remove anything.
  **Cross-PR interaction (review c02f i10, resolved in i13):** pr-3d1fa55
  (#217, in QA) adds `_reclaim_terminal_pr_windows` — a TUI sync sweep that
  tears down windows, containers and runtime state for *any* `merged`/`closed`
  PR. Once that lands, a locally closed PR's live windows are reclaimed on the
  next reload, i.e. the automatic cleanup this decision rules out. The user
  clarification on this PR ("any cleanup must remain a separate, explicitly
  requested operation; do not add an automatic cleanup fallback or delayed
  deletion triggered merely by closing") covers live resources as well as
  files, so `closed` must not authorize reclamation: #217 should limit the
  sweep to `merged` and leave a closed PR's windows to the explicit
  `pm pr cleanup --resources`. Two cross-PR notes state this on pr-3d1fa55
  (`note-fd141d0`, review c02f i10; `note-c48dda1`, review c02f i13 — the i13
  iteration summary mis-cited its id as `note-4fd0759`, review b320 i1); if
  #217's owner believes closed windows should be swept, that needs the user's
  explicit approval as an exception.
- **A5 — Close on a `merged` PR?** Resolved: refuse (exit 1) without
  `--remove`, because rewriting `merged` → `closed` erases merge history and
  merge-integrity evidence. With `--remove`, delete the registry record only
  (no GitHub call, no branch/workdir deletion). Message points at `--remove`.
- **A6 — Repeat close on an already `closed` PR?** Resolved: idempotent
  success. The entry stays `closed`; the GitHub close is re-attempted unless
  `--keep-github` (so a close whose `gh` call previously failed can be
  retried); `updated_at` is refreshed. The original `closed_at` is preserved
  (only a fresh closure — i.e. from a non-`closed` status — records a new one),
  so repeated close never rewrites closure history.  An entry that was already
  `closed` before `closed_at` existed stays without one: a repeat close must
  not stamp "now" and invent a closure time (review c02f i8).
- **A7 — Runtime notice for `--keep-branch`?** Resolved: none; the deprecation
  lives in `--help` (a runtime line would be noise in QA scripts that still
  pass the flag).

No **[UNRESOLVED]** ambiguities.

## 4. Edge cases

- **Entry vanishes between load and update** (concurrent `--remove`): the
  `apply` closure no-ops and sets `missing_at_lock`; the command exits 0 with
  a "removed concurrently; nothing to close/remove" message (covered by
  `test_close_noops_when_entry_removed_concurrently` and
  `test_remove_noops_when_entry_removed_concurrently`).
- **`gh` unavailable / unauthenticated**: `SystemExit` swallowed as today →
  warning, status still `closed`, nothing deleted.
- **GitHub says the PR is already closed/merged**: fake/real `gh` may exit
  non-zero; treated as a warning, local lifecycle still proceeds.
- **`--keep-github` then `pm pr sync-github`**: status stays `closed` (R9).
- **`--remove` on the active PR**: `active_pr` reassigned; TUI reloads.
- **Closed PR in a plan / dependency graph**: it keeps rendering as closed
  (hidden by default in the tree), dependents stay blocked and are warned
  about; nothing is auto-satisfied.
- **`pm pr merge` on a closed PR**: refused (R8) unless it is a
  `--no-signoff-check` / `--propagation-only` recovery of an already-published
  merge; `pm pr edit --status` is the deliberate reopen path.
- **`--remove` for a PR with a `merged` status**: record removed; GitHub,
  branch and workdir untouched.
- **`pr_id` given as `#N` or bare number**: `_require_pr` resolution unchanged.
- **Close while another process holds the store lock**: `StoreLockTimeout`
  propagates as today (no destructive partial state; the gh close may already
  have happened — acceptable, documented by ordering).
- **Workdir is a symlink or on another mount**: untouched (no rmtree).

## 5. Files to change

- `pm_core/cli/pr.py` — `pr_close` rewrite (`--remove`, warnings, messages),
  `pr_start` and `pr_merge` closed guards, a closed-duplicate hint in
  `pr_add` (retained closed entries now match its duplicate check), and
  `pr_edit` dropping `closed_at` on a deliberate reopen (review c02f i13),
  plus terminal-status reporting in `pr_auto_sequence` and a closed guard in
  `pr_signoff` (review 8820 i1).
- `pm/plans/plan-a35369f.md` — `note` bullet marking the branch-deletion
  premise of its ruleset item obsolete (review c02f i13).
- `pm_core/cli/helpers.py` — `_record_status_timestamp` `closed_at`, plus the
  `previous_status` parameter that makes the helper the single owner of the
  field's history (drop on leaving `closed`, keep on restating it; review
  b320 i1).
- `pm_core/pr_utils.py` — `TERMINAL_PR_STATES` (the `merged`/`closed` pair
  shared by the sync guards and the `pm pr list --open` filter).
- `pm_core/autostart_state.py`, `pm_core/cli/session.py`, `pm_core/qa_loop.py`,
  `pm_core/home_window/pr_list.py`, `pm_core/review_loop.py` — the
  pre-existing terminal-status duplicates derive from the `pr_utils` constant
  (review c02f i10/i11, review 8820 i1).
- `pm_core/cli/pr.py` — `pr_cleanup`'s "not merged" warning set also accepts
  `closed`, so following close's help to the explicit cleanup is not flagged
  as unexpected (review c02f i10), and its id-less auto-select offers the
  terminal statuses (`merged` or `closed`) rather than `merged` alone (review
  c02f i12); the warning set now derives from `TERMINAL_PR_STATES` (review
  e89f i2).
- `pm_core/store.py` — `_validate_pr_statuses` backfills `created_at`/
  `updated_at` from `closed_at` too (review e89f i2), so a retained `closed`
  record is treated as a lifecycle timestamp like `merged_at`.
- `pm_core/pr_sync.py` — keep local `closed` when GitHub reports OPEN, at
  snapshot time and again inside the locked apply.
- `pm_core/tui/sync.py` — the startup GitHub sync's apply applies the same
  closed-is-terminal guard.
- `pm_core/gh_ops.py` — docstring note only (no signature change).
- `pm_core/fake_github.py` — `_pr_close` emulates `--delete-branch` (deletes
  the head branch in the backing repo via the new
  `FakeGitHubRepo.delete_branch`) so branch retention is genuinely tested
  (review c02f i14).
- `pm_core/cli/__init__.py` — help line.
- `pm_core/prompt_gen.py` — the watcher prompt's lifecycle list gains a
  `closed` line (retained history, terminal, never satisfies a dependency) so
  a watcher session does not read a retired PR as one to merge (review 8820
  i2, R11 item 41).
- `pm/qa/regression/command-dedup.md`, `pm/qa/regression/multi-window-registry.md`
  — cleanup steps use `--remove`.
- `tests/test_pr_close.py` (new), `tests/test_pr_enhancements.py`
  (`TestGitHubCloseResilience` rewrite), `tests/test_sync_merge_integrity.py`
  (TUI startup-sync closed race), `tests/test_fake_github.py` (the
  `--delete-branch` emulation), `tests/test_store_validation.py`
  (`closed_at` lifecycle backfill, review e89f i2), and
  `tests/test_cli_helpers.py` (`TestRecordStatusTimestampClosedAt` — the
  helper's `closed_at` contract, review e89f i1).

## 6. Out of scope

- Real GitHub operations of any kind; all verification uses the fake backend.
- Reworking `pm pr cleanup`'s behaviour.  The only changes are accepting
  `closed` as a normal input (no "not merged" warning), offering it in the
  id-less auto-select, and skipping id-less entries in `--all`/`--prune` so a
  hand-edited record cannot raise `KeyError` (R11 item 36); the dirty-workdir
  guard, `--force`, `--all`, `--prune` and `--resources` are otherwise
  untouched, as are `pm pr merge`'s merge flow and the TUI cleanup keys.
- Branch deletion features (e.g. `gh pr close --delete-branch`) — removed from
  the close path entirely; no replacement command is added.
