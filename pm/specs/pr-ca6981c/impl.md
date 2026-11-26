# Spec: pr-ca6981c — pm merge's git stash/pop corrupts project.yaml + leaks stashes

## Problem summary

`pm pr merge` reconciles uncommitted `pm/project.yaml` edits across a git merge
using a **text** `git stash push` / `git stash pop`. When another pm process has
mutated `project.yaml` between the stash and the pop, the pop hits a 3-way text
conflict (typically a single `updated_at` line) and git writes raw conflict
markers into `project.yaml`:

```
<<<<<<< Updated upstream
  updated_at: '...02:44:25...'
=======
  updated_at: '...02:52:11...'
>>>>>>> Stashed changes
```

`project.yaml` is the lock-protected source of truth for all of pm, so this
breaks `store.load()` (`ProjectYamlParseError`) and every subsequent pm command
until hand-fixed. Three distinct symptoms, one root cause (using git's text
stash/merge to reconcile structured, lock-guarded data):

1. **CORRUPTION** — conflict markers land in `project.yaml`. Worse, the git
   merge itself *succeeded*, but `_finalize_merge` → `store.locked_update` →
   `store.load` then raises on the now-corrupt file, so the PR is left
   `in_review` with `merged_at=null` even though it merged.
2. **STASH LEAK** — a conflicted `git stash pop` does NOT drop the stash, and the
   flow never detects/resolves it, so `pm: auto-stash for merge` stashes pile up
   silently (the incident left 8).
3. **NO RESOLUTION SESSION** — `_unstash_after_merge` only echoes "Warning: stash
   pop had conflicts. Resolve manually." and returns False; unlike the real
   git-merge-conflict paths it never launches a `_launch_merge_window`, so a
   picker-driven merge that hits a pop conflict strands the user.


**Master integration (2026-11-26, merge 137acac0).** Master's pr-ac10f03
(#238) changed the merge flow under this spec:
- `pm pr merge` now only *publishes* a signed-off candidate. The worktree
  merge and its conflict windows are gone. Merge never launches a resolution
  session; the only window left is the post-publish main-repo recovery
  window.
- Master added `_resolve_project_yaml_pop` and `store.merge_3way`, a
  structural resolver for a conflicted pop in which live state wins.

This spec was rescoped to match (PR note "Rescope after pr-ac10f03"):
- Symptom 3 / old R5 (launch a window on a stash-pop conflict) is
  **dropped**.
- The branch's `three_way_merge` (ours wins) is **replaced** by master's
  `merge_3way`.
- The lock / `_NEVER_STASH` approach is **reconciled** with the resolver.
- The #253 S74 race (concurrent writers during publication) is now
  explicitly in scope.

## Relevant code (verified at 137acac0)

- `pm_core/cli/pr.py`. The stash helpers are in the "Stash-retry helpers for
  merge operations" section.
  - `_ff_with_autostash(repo_dir, target, pr_display_id)` is the single entry
    point. It runs `git merge --ff-only`, stashes on dirty overlap, retries,
    restores, and then reaps. Both fast-forward sites use it:
    1. `_publish_local` (local backend). It fast-forwards the main repo's
       checked-out base to the approved merge commit.
    2. `_pull_after_merge` (github/vanilla, post-publish). It fast-forwards
       the main repo to `origin/<base>`. The fetch stays outside the lock.
  - `_stash_for_merge` / `_unstash_after_merge` do the move-aside and the
    restore.
  - `_capture_registry` / `_reapply_registry` handle the registry,
    structurally.
  - `_restore_merge_stash` pops by commit. `_reap_auto_stashes`,
    `_stash_already_applied` and `_registry_change_applied` handle
    leaked-stash reaping.
  - `_resolve_project_yaml_pop(cwd, ref)` is master's resolver, kept as the
    fallback.
  - `_dirty_file_paths` parses `status --porcelain -z`.
  - `_persist_with_backoff` covers the pr start orphan class (§7).
- `pm_core/store.py`:
  - `find_conflict_markers` and the guard in `load()`. A missing file still
    raises master's `ProjectYamlMissingError`, which is a
    `FileNotFoundError`.
  - `merge_3way(base, ours, theirs)` is master's; *theirs* wins true
    conflicts.
  - `_lock(root, timeout)`, `locked_update` and `save` (atomic: tmp file +
    rename, chmod 444).

## 1. Requirements (grounded)

R1. **No conflict markers in `pm/project.yaml`, ever.** Concurrent registry
    edits across a merge are reconciled *structurally*. The registry never
    goes through git's text stash/pop.

R2. **No leaked stash.**
    - pm's own auto-stash is popped and dropped after the update.
    - If the pop conflicts, or git refuses it, the stash is **kept on
      purpose**, with explicit instructions: conflicted files get "resolve,
      then `git stash drop <ref>`"; a refused pop gets "nothing was lost,
      `git stash pop <ref>`". Leaving it is what keeps user changes safe.
    - Leaked `pm: auto-stash for merge` entries from earlier runs are reaped
      after a successful update, but only those whose changes are already in
      the working tree. Others are listed, never silently dropped. Other
      stashes (WIP, the user's own) are never touched.

R3. **`store.load` conflict-marker guard.** A registry that contains markers
    raises `ProjectYamlParseError`. The message names the file, the first
    marker line and the remediation, instead of a raw YAML scanner error.

R4. **Merged PR ends `status="merged"` with `merged_at` set.** With R1 in
    place, the finalize after the update loads a valid registry.

R5. **Concurrent pm writers serialize against the update (#253 S74).** The
    registry lock is held across the whole fast-forward, not only around the
    stash path. This means a writer cannot:
    - land between the revert and the re-apply;
    - save, after git rewrote the file, a registry it loaded before the
      rewrite (a lost update of the merged-in records and notes);
    - have its `project.yaml.tmp` swept into a stash (`[Errno 2]` on its
      rename).

    If the lock stays busy (10 s), the checkout is left untouched and the
    update fails with the lock message. The lock is never held across a
    network call.

R6. **No data loss on any failure path.** The live registry is copied into
    the git dir before it is reverted. It is restored byte-for-byte when the
    fast-forward or the stash fails. If the re-apply itself fails, the
    recovery copy is kept and its path printed.

R7. **Tests.** Real-git tests simulate concurrent registry edits across a
    fast-forward. They assert:
    - (a) valid YAML;
    - (b) no markers ever;
    - (c) no stash left;
    - (d) the PR is finalized as merged with `merged_at` set.

    Further tests cover a concurrent writer thread, lock scope, busy lock,
    conflicted and refused pops, reaping, and the recovery copy.

## 2. Design

### 2a. `store.py`: conflict-marker guard (R3)

`find_conflict_markers(text)` matches lines starting with `<<<<<<< `,
`||||||| ` or `>>>>>>> `, or a line that is exactly `=======`. Indented note
text that quotes markers does not match. `load()` reads the text once:

- a missing file raises `ProjectYamlMissingError` (master);
- any other `OSError` raises `ProjectYamlParseError`;
- markers raise `ProjectYamlParseError` with the line number and remediation;
- otherwise the text is parsed.

### 2b. Structural merge: master's `merge_3way` (R1)

One merge function. `merge_3way(base, ours=merged-in, theirs=live)`:

- live state wins true conflicts;
- merged-in committed changes are kept wherever live still has the
  ancestor's value;
- id-keyed lists (prs, plans, notes) merge per id.

These are the same roles master's resolver uses (base `stash^1`, ours `HEAD`,
theirs the stash). The branch's own `three_way_merge`, in which ours won, is
removed.

### 2c. `pr.py`: `_ff_with_autostash` (R1, R2, R5, R6)

```
reg_root = repo/pm if repo/pm/project.yaml exists
with store._lock(reg_root, timeout=10):       # busy -> failed result, untouched
    r = git merge --ff-only target
    if r failed with "would be overwritten":
        info = _stash_for_merge(repo)
        if info:
            try:     r = git merge --ff-only target
            finally: restored = _unstash_after_merge(repo, info)
if r ok and restored: _reap_auto_stashes(repo)  # read-only checks, after unlock
```

`_stash_for_merge`. The caller holds the lock.

1. Compute the dirty paths (`-z`). Raise the TUI merge-lock overlay if any
   `pm/` path is dirty.
2. Call `_capture_registry`. If `pm/project.yaml` is dirty, valid, free of
   markers and present in HEAD:
   - capture the live text and dict, plus `HEAD:pm/project.yaml` as the
     base;
   - write the recovery copy `<git-dir>/pm-premerge-project-<ts>-<pid>.yaml`;
   - run `git checkout HEAD -- pm/project.yaml`. Using HEAD (not the index)
     means a staged registry hunk cannot keep blocking; re-applied content
     ends up unstaged.

   Otherwise leave the registry alone, so the merge fails on it cleanly.
3. Stash the remaining dirty paths with `git stash push --include-untracked
   -m "pm: auto-stash for merge" -- :(literal)<p>...`. These are explicit
   pathspecs that exclude `pm/project.yaml`, `.lock` and `.tmp`
   (`_NEVER_STASH_RELS`). Record the stash's commit sha.
4. If the stash fails, restore the registry's exact bytes and return None.

`_unstash_after_merge`:
1. Re-apply the registry. Load the on-disk merged-in state under the held
   lock (it goes through the marker guard), then compute
   `merge_3way(base, merged_in, live)`.
   - If the result equals the live dict (nothing came in, e.g. the
     fast-forward failed), write the original bytes back. This avoids a
     re-dump that rewraps the file.
   - Otherwise `store.save` it and print `Merged pm/project.yaml (local pm
     state + merged changes).`
   - Delete the recovery copy on success.
2. Pop the stash by its commit (`_stash_ref`), not by position.
   - On a clean pop, print "Restored N stashed file(s)".
   - If the pop conflicts, try master's `_resolve_project_yaml_pop(cwd, ref)`
     first; it only merges real pm registries. Otherwise keep the stash with
     instructions.
   - If git refuses the pop, keep the stash ("Nothing was lost").
3. Remove the TUI overlay.

`_reap_auto_stashes` drops an entry whose message is exactly `pm: auto-stash
for merge` when its changes are already applied:
- tracked and untracked paths: the worktree blob equals the stash blob
  (`hash-object` vs `rev-parse`);
- `pm/project.yaml`: `merge_3way(stash^1, stash, current) == current`, i.e.
  every change the stash made is present or superseded in the live registry.

Entries are dropped highest index first, after re-checking that each ref
still names the same commit. Entries that are not applied are listed with
inspect/drop hints.

`_resolve_project_yaml_pop(cwd, ref="stash@{0}")` is master's resolver. It is
now parameterized by ref, and it merges only files whose two sides parse as
pm registries (they have a `project` key). A user's file that merely has the
name is left alone.

## 3. Implicit requirements

- **No self-deadlock.** Nothing inside the held region calls
  `locked_update` / `_lock` on the same root. `trigger_tui_merge_lock` only
  writes a marker file. The re-apply uses `load` + `save` directly.
- **Master's mocked tests keep passing.** The mocked `run_git` returns
  `"master"` for every `rev-parse`, and `stash pop` is still called as
  `("stash", "pop", ref)`. `test_fetches_and_fast_forwards_in_repo_dir` now
  normalizes the cwd type (str/Path), since the reaper runs in the repo dir
  too.
- **Paths are raw.** `-z` porcelain plus `:(literal)` pathspecs, so spaces,
  non-ASCII, quotes and glob characters survive.

## 4. Edge cases

- **The registry is the only dirty file** (the original incident): no git
  stash is created at all. The overlap is resolved structurally.
- **A writer races the revert** (QA S3) or the fast-forward (S74):
  serialized by the lock. The pathspec exclusion is a second guard.
- **A writer hammers the lock:** the merge's polling acquire can starve.
  After 10 s it fails safe and touches nothing.
- **Stash-pop conflict in ordinary files:** the update has landed and the
  registry is reconciled and valid. The stash is kept with a drop
  instruction. No window opens (master no longer opens merge windows).
- **A pop git refuses** (e.g. an untracked stashed file now exists from the
  merge): nothing is applied, the stash is kept, and the message names it.
  This covers the rescope note's open item (2) for every file type; the
  registry can no longer be the cause.
- **Old leaked auto-stashes** (the main repo held 7): applied ones are
  reaped on the next successful update; the rest are listed.
- **The live registry is invalid or has markers:** it is left untouched and
  the update fails like any overlapping file.

## 5. Test plan (R7) — `tests/test_merge_stash.py`

- Guard: `find_conflict_markers` forms and benign values; the `load()`
  message; a missing file is still a `FileNotFoundError`.
- `_dirty_file_paths`: worktree-only change; raw paths and renames.
- `_persist_with_backoff`: retry-then-succeed; exhaustion.
- `_ff_with_autostash` on real git:
  - overlapping edits reconcile (live wins, merged-in note and field kept,
    no markers, no stash, HEAD == target, no recovery copy, nothing staged);
  - finalize gives merged + `merged_at`;
  - other dirty and untracked files are stashed and restored;
  - a failed fast-forward restores the exact registry bytes;
  - a stash failure restores the registry;
  - the recovery copy exists until the re-apply;
  - a writer that re-dirties the registry never enters the text stash.
- Locking:
  - the lock is held during every rewriting git step (first fast-forward
    included) and released afterwards;
  - a busy lock leaves the checkout untouched;
  - a concurrent writer thread loses no notes (3 runs).
- Restore and reap:
  - a conflicted pop keeps the stash, leaves the registry valid and opens no
    window;
  - a refused pop keeps the stash intact;
  - reaping drops applied entries (files plus a structural registry case)
    and keeps a non-applied entry and WIP.
- `_resolve_project_yaml_pop`: a registry conflict from a text stash is
  resolved; a non-registry `project.yaml` is left alone.
- Master's `tests/test_merge_publish.py` covers the full `pm pr merge` local
  flow, including `test_local_merge_keeps_live_state_and_branch_project_yaml_changes`.

Pre-fix evidence: 9 of the 13 fast-forward/lock/reap tests fail on master's
code (a shim drives master's inline sequence). The concurrent-writer test
fails there with "Your local changes … would be overwritten by merge".

## 6. Ambiguities (resolved)

- **Tie-break on a scalar both sides changed:** live wins (master's
  `merge_3way`). This replaces the earlier "ours wins" choice. The #230 and
  #231 manual recoveries also kept local values such as `active_pr`.
- **How aggressively to reap:** only `pm: auto-stash for merge` entries, and
  only when already applied. An earlier draft dropped every auto-stash, which
  could lose a refused pop's unapplied changes.
- **Lock timeout behaviour:** fail safe without touching anything (no
  lock-free fallback). Reverting the registry under an open `pm edit` would
  let the editor's save clobber the merge.
- **Old R5 (resolution window on a stash-pop conflict):** dropped, following
  master's no-merge-window design (rescope note).

No **[UNRESOLVED]** ambiguities.

## 7. Second failure class (pr-d887f4c / #210) — partial, scoped

PR-notes flag a related lock-contention class: `pr start` runs `gh pr create`
(irreversible) in `pr_start`, then persists `gh_pr_number` via
`store.locked_update` afterwards. Under concurrent pm operations that
persist can hit the 2 s `StoreLockTimeout` and exit, orphaning the GitHub PR
(`gh_pr_number=None`). `create_draft_pr` idempotent recovery was already fixed
in a prior session.

Scoped fix here (the notes' "longer/backoff lock acquisition" direction):
`_persist_with_backoff(root, apply, attempts=5, timeout=5.0)` — retry the
persist with exponential backoff (0.2 s→2 s cap) so a transient contention
burst can't strand the just-created PR. Used in `pr_start` only when
`gh_pr_info` was created; the no-side-effect path keeps the default single
`locked_update`. Tested for retry-then-succeed and exhaustion.

**Still open (out of scope, larger):** create-after-reserve ordering so the
external PR is never created before a record exists, and branch-based orphan
reconciliation in `pm pr sync-github` (it currently matches by
`gh_pr_number`, so it can't backfill an orphan). Left for a follow-up.
