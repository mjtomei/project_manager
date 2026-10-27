# pr-2e06289 — TUI background GitHub sync must verify sign-off integrity

## Summary

`pm_core/tui/sync.py` finalizes a merge that GitHub reports as MERGED without
checking that what landed is the signed-off candidate. `pm pr merge`
(`pm_core/cli/pr.py::_verify_github_merge`, added by pr-ac10f03) does the
check, and its `--no-signoff-check` recovery path records
`pr["merge_integrity"]` + a PR note when GitHub published another head/base/
tree — but the 300 s background sync (`do_normal_sync` →
`pr_sync.sync_prs`) and the startup/`pm pr sync-github` path
(`pr_sync.sync_from_github`) bypass it. Repro: approve a PR, push an
unreviewed commit to its branch on the remote, merge on GitHub, wait for the
sync tick → PR is `merged`, no `merge_integrity`, no note.

Fix: extract the verification core out of `cli/pr.py` into a shared module
and route every sync-detected merge of a PR holding a *bound* `SIGNOFF_MERGE`
through it. A mismatch is recorded on the PR (`merge_integrity` + one note)
exactly as `_verify_github_merge` does, from the same lock/save path that
applies the merged status.

## 1. Requirements (grounded)

### R1 — Sync-detected merges are verified against the bound approval

- `pr_sync.sync_prs` (`pm_core/pr_sync.py:145`) iterates GitHub-backend PRs in
  `in_review`/`in_progress`/`qa`/`sign_off` and marks them `merged` when
  `backend.is_merged()` (→ `gh_ops.is_pr_merged`, `pm_core/backend.py:86`)
  returns true. For each such PR that holds a **bound** `SIGNOFF_MERGE`
  (`pr["signoff"]["verdict"] == SIGNOFF_MERGE`, `sha`, and
  `integration["base_sha"]`), run the same verification `pm pr merge` runs:
  fetch the base from the target repo, find the merge commit of the approved
  head in `base_sha..tip`, and compare its first parent to the signed-off
  base and its tree to `integration["candidate_tree"]`.
- `pr_sync.sync_from_github` (`pm_core/pr_sync.py:263`) transitions a PR to
  `merged` from `gh_ops.get_pr_state` (`state == MERGED` / `mergedAt`). Do the
  same verification on that transition.
- `pm pr sync` (`pm_core/cli/pr.py:2858`) has its own duplicate detection loop
  (it does not call `sync_prs`); apply the same verification there so the
  documented "merge on GitHub, then run `pm pr sync`" flow is covered too.

### R2 — One shared verification core, same evidence

- New `pm_core/merge_integrity.py` owns the logic currently in
  `cli/pr.py::_verify_github_merge` (`pm_core/cli/pr.py:2519`):
  - `approved_candidate(pr_entry)` → `(head, bound)` only when the record is a
    `SIGNOFF_MERGE` with `sha` and `integration.base_sha` (the same guard
    `_recover_completed_merge` uses, `cli/pr.py:2650`), else `None`.
  - `verify_github_merge(pr_id, workdir, target_repo, base_branch, base_sha,
    head, bound)` → a `MergeVerification` (`problem`, `merge_sha`, `error`),
    performing only git reads (`integration.fetch_base`, `git log --merges`,
    `integration.is_ancestor`). No store writes, no output.
  - `verify_detected_merge(root, data, pr_entry, workdir, base_branch)` →
    `MergeVerification | None` (None = no bound approval): resolves
    `target_repo` via `integration.target_for` and calls the above.
  - `apply_to_pr(pr, verification)` takes the `MergeVerification` and is a
    no-op for `None` (no bound approval), `ok`, or `error` (could not verify);
    a definite problem sets
    `pr["merge_integrity"] = {"problem": problem, "merge_sha": merge_sha}` and
    appends the `Merge integrity: <problem>.` note once (same text/id scheme
    as today). Taking the verification keeps every call site to one line and
    in one place decides what counts as evidence.
- `cli/pr.py::_verify_github_merge` becomes a thin wrapper: call the shared
  verifier, then record via `store.locked_update` + `apply_to_pr` and print
  the existing `WARNING:` lines (byte-identical messages for the existing
  tests, `tests/test_merge_publish.py:592-684`).

### R3 — TUI applies integrity under the same lock as the status

- `pm_core/tui/sync.py` sync functions run in an executor thread with a deep
  copy and `save_state=False`; the thread must not write `project.yaml`.
  `pr_sync` therefore returns the verification on the result
  (`SyncResult.merge_integrity: dict[pr_id, MergeVerification]`) and the TUI
  applies it inside the existing `store.locked_update` callbacks:
  - `do_normal_sync::apply_merged` (status set to `merged`) — `sync.py:144`.
  - `startup_github_sync::apply_github` (`new_status == "merged"`) —
    `sync.py:268`.
- A recorded problem is also shown on the TUI log line
  (`Merge integrity: <problem>`, forced with a short hold so the following
  `Synced: N PR(s) merged` line does not paint over it). An unverifiable merge
  is logged (`_log.warning`), not recorded — matching today's CLI semantics.

### R4 — Never let verification break sync

- A verification failure (unreadable base, git error, unexpected exception)
  must not stop merge detection or raise out of `sync_prs`/
  `sync_from_github`/`do_normal_sync`. Wrap per-PR verification; record only
  definite mismatches; treat "could not verify" as a log-only outcome.

## 2. Implicit requirements

- **Only newly-detected merges are verified.** Sync loops only look at active
  statuses, so a PR finalized by `pm pr merge` (which already verified) is
  never re-verified. `do_normal_sync`'s extra `newly_merged` set (CLI merges
  observed via status change) must not be verified either.
- **Verification needs the bound record**, not merely a `SIGNOFF_MERGE`
  verdict: `base_sha` + `candidate_tree` are required to compare. A legacy
  HEAD-only approval cannot be checked the same way (see Ambiguities).
- **Idempotent evidence.** Re-detection must not append a second identical
  note (`store.generate_note_id` + text check, as today).
- **Same evidence shape** as `pm pr merge` recovery: `pr["merge_integrity"] =
  {"problem", "merge_sha"}` and a note whose text starts `Merge integrity:`.
- **Thread-safety.** The TUI's sync thread still performs only reads (git/gh);
  all `project.yaml` mutation happens in the main thread inside
  `store.locked_update`.
- **Workdir fallback.** When a PR has no usable workdir, verification uses the
  same directory the sync used to detect the merge (another PR's workdir or
  the project repo), exactly as `_recover_completed_merge` falls back
  (`cli/pr.py:2609-2628`).
- **No behavior change for non-GitHub backends** (they never auto-detect
  merges) and for PRs without a bound approval (status transition only, as
  today).

## 3. Ambiguities (resolved)

1. **Legacy `SIGNOFF_MERGE` without `integration` binding** — *resolved:* skip
   verification, matching `_recover_completed_merge` (which also only verifies
   bound approvals). Such a PR cannot be merged through pm anyway; the
   recorded binding is what makes comparison possible.
2. **Invalidated approval** (`signoff.invalidated` set) — *resolved:* still
   verify. The record retains the approved head/base/candidate, and comparing
   what landed against it is exactly the provenance the bug report wants.
   (Guard matches `_recover_completed_merge`, which ignores `invalidated`.)
3. **Scope: CLI sync too?** — *resolved:* yes. `pm pr sync` /
   `pm pr sync-github` are documented merge-detection entry points (the merge
   refusal message tells users to merge on GitHub then run `pm pr sync`), and
   leaving them unverified would keep the same silent-finalize hole.
4. **Where the TUI surfaces the problem** — *resolved:* the persistent record
   (`merge_integrity` + note) is authoritative; additionally show a held log
   line so the user sees it without opening the PR. "Could not verify" stays
   log-file-only to avoid noise on transient network failures.

## 6. Review refinements (c703 i1/i2/i3)

These changed details of R2/R3 after the implementation landed; the
requirements above still hold.

- `merge_integrity.verify_detected_merge` never raises (single guard inside
  the shared module, not at each call site); `pr_sync` + `pm pr sync` call it
  directly.
- `cli/pr.py::_recover_completed_merge` reuses `approved_candidate`.
- `pm pr sync-github` prints the same `WARNING:` lines as `pm pr sync` (the
  record + note are authoritative either way).
- `git_detail` lives in `pm_core/git_ops.py` (it formats any failed git call,
  not only an integrity check) and is used by the publish path and the
  verifier.
- The "no merge commit of the approved head" problem text names the PR: the
  sync paths log it without `pm pr merge`'s "GitHub PR #N merged." context.
- The TUI sync worker thread now runs `integration.fetch_base` once per
  detected merge of a bound-approved PR (git fetch into the sync workdir,
  serialized by `<git-common-dir>/pm-integration.lock`, bounded at 300 s).
  PRs without a bound approval never fetch. Left for QA to exercise: a merge
  detected while another integration check holds that lock delays the
  background sync (status bar stays "pulling"); it does not block the UI.
- i3: the TUI's `getattr(result, "merge_integrity", ...)` default is kept (a
  stubbed `SyncResult` in `tests/test_log_message_force.py` has no such
  attribute) but moved behind one `_result_integrity` helper instead of three
  inline copies; `pm pr sync-github`'s could-not-verify warning names the PR
  like `pm pr sync` and the log line do; tests pin the held log line
  (`force=True`, `hold=_INTEGRITY_HOLD_SECONDS`) and cover `sync_prs`'s
  workdir-gone fallback (verification runs in the workdir the sync detected
  from). The verifier itself is unchanged: a fetched base that does not show
  the merge is still recorded as "did not publish the signed-off candidate"
  (the deliberate pr-ac10f03 semantics —
  `test_github_already_merged_elsewhere_is_still_verified`), so a stale local
  project repo used as the fetch source can produce that general problem.

No **[UNRESOLVED]** ambiguities.

## 4. Edge cases

- **Base fetch fails / no base revision / `git log` fails** → `error` set;
  log a warning, record nothing, still finalize the merge (today's
  `_verify_github_merge` behavior).
- **Approved head not on the base** (merged another head, or squash/rebase)
  → problem names the merge that published the branch when one contains the
  head, else "no merge commit of the approved head".
- **Base moved during publication** → problem names the actual first parent.
- **Tree differs** → problem names published vs approved tree.
- **Multiple merged PRs in one tick** → one `MergeVerification` per PR; each
  applied and logged independently.
- **PR workdir gone** → use the sync workdir; `target_for` falls back to
  `project.repo`.
- **Repeated detection** (status reverted, second sync) → `merge_integrity`
  overwritten with the same problem; note not duplicated.
- **Malformed PR entries** (`usable_prs`) → already skipped by the sync
  loops; verification never runs for them.
- **`save_state=False`** → result carries the verification; nothing is
  written by the sync thread.

## 5. Tests

New `tests/test_sync_merge_integrity.py`, real git + `fake_github_repo`
(reusing the `approve()` pattern from `tests/test_merge_publish.py`):

1. **Failing on pre-fix code:** bound `SIGNOFF_MERGE`, unreviewed commit
   pushed to the branch, merged on the remote, `sync_prs(force=True,
   save_state=False)` → `result.merge_integrity[PR].problem` mentions the
   unapproved merge (and with `save_state=True`, the stored PR carries
   `merge_integrity` + one note).
2. Approved candidate merged on the remote → no integrity recorded.
3. `sync_from_github` detects the same unapproved merge → integrity recorded.
4. TUI `do_normal_sync` applies `result.merge_integrity` to `app._data`
   inside the locked update and logs the warning (fake app).
5. Repeated detection notes the problem once.
6. Existing `tests/test_merge_publish.py` github tests still pass unchanged.
