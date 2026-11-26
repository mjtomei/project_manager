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
    point. It pre-merges the registry, runs `git merge --ff-only`, stashes
    other files on dirty overlap, retries, restores, and then reaps. Both
    fast-forward sites use it:
    1. `_publish_local` (local backend). It fast-forwards the main repo's
       checked-out base to the approved merge commit.
    2. `_pull_after_merge` (github/vanilla, post-publish). It fast-forwards
       the main repo to `origin/<base>`. The fetch stays outside the lock.
  - `_stash_for_merge` / `_unstash_after_merge` stash and restore ordinary
    files (never the registry).
  - `_plan_registry` / `_apply_registry` / `_restore_registry` /
    `_stage_registry` handle the registry, structurally.
  - `_restore_merge_stash` pops by commit. `_reap_auto_stashes`,
    `_stash_already_applied` and `_registry_change_applied` handle
    leaked-stash reaping.
  - `_resolve_project_yaml_pop(cwd, ref)` is master's resolver, kept as the
    fallback.
  - `_dirty_file_paths` parses `status --porcelain -z -unormal`.
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
      then `git stash drop <ref>`"; a refused pop gets "nothing was lost;
      compare with the working tree, restore what is missing, then
      `git stash drop <ref>`" (not "pop it again": git may have applied
      part of it, review c6a2 i7). Leaving it is what keeps user changes
      safe.
    - Leaked `pm: auto-stash for merge` entries from earlier runs are reaped
      after a successful update, but only those whose changes are already in
      the working tree. Others are listed, never silently dropped. Other
      stashes (WIP, the user's own) are never touched. Reaping happens only
      in a repo that holds pm's registry, whose lock serializes every pm
      auto-stash push and pop. A standalone pm dir's target repo has no such
      lock, so its leaked stashes are left to the user (review c6a2 i5).

R3. **`store.load` conflict-marker guard.** A registry that contains markers
    raises `ProjectYamlParseError`. The message names the file, the first
    marker line and the remediation, instead of a raw YAML scanner error.

R4. **Merged PR ends `status="merged"` with `merged_at` set.** With R1 in
    place, the finalize after the update loads a valid registry.

R5. **Concurrent pm writers serialize against the update (#253 S74).** The
    registry lock is held across the whole fast-forward, not only around the
    stash path. This means a writer cannot:
    - interleave with the update;
    - save, after the update, a registry it loaded before it (a lost
      update of the merged-in records and notes);
    - have its `project.yaml.tmp` swept into a stash (`[Errno 2]` on its
      rename).

    Writers also find and pre-load the registry *before* taking the lock
    (`state_root()` + `store.load()`), so the live file must never be
    missing, half-written or reverted, even with the lock held. git's
    checkout unlinks and recreates files, so git must never rewrite it: the
    file is replaced only by atomic renames.

    If the lock stays busy (10 s), the checkout is left untouched and the
    update fails with the lock message (`_RegistryLockBusy`). The post-publish
    pull then exits 1 with a `--propagation-only` re-run hint and opens no
    recovery window: there is nothing to recover, and a session told to
    "stash and pull" would text-stash the registry. The lock is never
    held across a network call. The slow part (parsing and dumping a large
    registry) runs before the lock is taken.

R6. **No data loss on any failure path.** The live file always holds the
    full live state; it is never reverted. When the update fails, the exact
    live bytes and the original index entry (a staged hunk included) are
    restored. A crash mid-update leaves the merged live state in the
    worktree.

R7. **Tests.** Real-git tests simulate concurrent registry edits across a
    fast-forward. They assert:
    - (a) valid YAML;
    - (b) no markers ever;
    - (c) no stash left;
    - (d) the PR is finalized as merged with `merged_at` set.

    Further tests cover a concurrent writer thread, lock scope, busy lock,
    conflicted and refused pops, and reaping. They also check that git never
    rewrites the live file (same inode across every git step).

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
target = rev-parse target^{commit}             # one commit for plan and ff
head = rev-parse HEAD
plan = _plan_registry(repo, target)            # before the lock (slow part)
with store._lock(repo/pm, timeout=10):         # busy -> failed result, untouched
    if HEAD != head: plan = _plan_registry(repo, target)  # another update ran
    _apply_registry(repo, plan)                # atomic rename + stage target blob
    r = git merge --ff-only --no-autostash target  # keeps the registry entry
    if r failed with "would be overwritten":
        stage HEAD's registry entry            # stash must not carry it
        info = _stash_for_merge(repo)          # other files only
        stage the target's entry again
        if info:
            try:     r = git merge --ff-only --no-autostash target
            finally: restored = _unstash_after_merge(repo, info)
    finally: if r failed: _restore_registry(repo, plan)
    if r ok and restored and locked: _reap_auto_stashes(repo)  # under it
```

The plan runs before the lock and can take seconds on a large registry
(the pure-Python dump alone is ~3.7 s on this repo's), so two things can
change meanwhile (review c6a2 i2):
- **The target ref.** A concurrent fetch moves `origin/<base>`. The index
  is staged with the planned commit's blob, so the target is pinned to that
  commit up front. Otherwise the fast-forward goes to the newer commit and
  fails spuriously ("would be overwritten: pm/project.yaml").
- **HEAD.** Another update (a second merge) fast-forwards it first. The
  plan's merge base and the HEAD entry the auto-stash is taken against are
  then stale: the stash would carry a registry change, git would refuse its
  pop, and the user's other files would stay stashed. So the plan is redone
  under the lock when HEAD moved. That case is rare, and it costs about what
  any pm write costs.

The reaper runs under the lock too. Every pm auto-stash push and pop
happens under it, so a reaper outside it could treat another update's
in-flight auto-stash as an applied leftover. Two windows allow that: after
the stash is stored but before its files are reverted, and after the pop's
apply but before its drop. Dropping it there either loses that stash, or
shifts the positions so the pop's own `stash drop stash@{N}` removes a
different entry (e.g. the user's WIP). A repo without pm's registry (the
target repo of a standalone pm dir) takes no lock, so nothing serializes
pm's updates there, and the reaper does not run (review c6a2 i5).

`--no-autostash` overrides a user's `merge.autoStash=true`, which would
otherwise make git itself text-stash the swapped-in registry, reset it and
pop it back over the incoming one: conflict markers and a leaked stash, with
rc 0 (review c6a2 i1). It is passed only on git >= 2.27 (or an unknown
version): older git has neither the option nor `merge.autoStash`, and
rejects the unknown option, which would fail every fast-forward
(review c6a2 i4).

`_plan_registry` runs only when the target changes `pm/project.yaml`,
both HEAD and the target hold it, and the update is a real fast-forward
(HEAD is an ancestor of the target). When HEAD already contains the target
or has diverged, git leaves the file alone, and merging toward the target's
older blob would revert committed registry changes in the live state and
stage that older blob (review c6a2 i3). It needs a single stage-0 index entry
and HEAD, target and live registries that are valid, free of markers and
mappings (`_parse_registry`); otherwise it returns None and git treats the
file like any other. HEAD's and the target's registries are parsed once,
here, and kept in the plan (`merge_3way` never mutates its inputs).
- It computes `merge_3way(base=HEAD blob, ours=target blob, theirs=live)`.
- The new text is chosen as follows:
  - when the result equals the live dict: the live bytes;
  - when it equals the incoming dict: the target blob's bytes;
  - otherwise: `store.dump_text(merged)`, the exact text `store.save`
    writes.

`_apply_registry` (lock held):
1. Re-read the live text. If it changed since the plan, re-merge it.
   Only the live text is parsed then, so the lock hold stays at one parse
   (plus a dump when both sides changed), the same as any pm write.
2. Replace the file with one atomic rename (`store.save_text`).
3. `git update-index --cacheinfo <target mode>,<target blob>,pm/project.yaml`.

In git's two-way merge, an index entry that already equals the target is
kept, even with a dirty worktree (read-tree case 19). So the fast-forward
never unlinks or recreates the file. After it, HEAD and the index hold the
target and the worktree holds target + live state, uncommitted as before.
`_restore_registry` puts back the exact live bytes and the original index
entry. If that entry cannot be put back (another git process holds
`index.lock`, which usually failed the fast-forward too), the incoming blob
stays staged on the old HEAD and a later commit would commit it, so it
prints the `git update-index --cacheinfo` command that restores it
(review c6a2 i5).

`_stash_for_merge` (lock held) stashes only ordinary files:
1. Take the dirty paths (`-z`; `-unormal` overrides a user's
   `status.showUntrackedFiles=no`, which hid an untracked file that
   blocks the fast-forward; review c6a2 i6) and apply `_stashable_paths`.
   That drops
   `_NEVER_STASH_RELS` (the registry, `.lock`, `.tmp`) and expands a
   collapsed untracked `pm/`.
2. `git stash push --include-untracked -m "pm: auto-stash for merge" --
   :(literal)<p>...`.
3. Record the new `stash@{0}` commit. If the top did not change ("No local
   changes to save", rc 0), it is someone else's stash: treat that as a
   failed stash.
4. Raise the TUI overlay only when pm/ files are stashed.

`_unstash_after_merge` pops the stash by its commit (`_stash_ref`), not by
position:
- A clean pop prints "Restored N stashed file(s)".
- If the pop conflicts, it first tries master's
  `_resolve_project_yaml_pop(cwd, ref)`, which merges only real pm
  registries. A lock failure there counts as unresolved. Otherwise the
  stash is kept with a "resolve, then `git stash drop <ref>`" instruction.
- If git refuses the pop, the stash is kept ("Nothing was lost"). The
  message does not suggest popping it again: git >= 2.34 restores the
  tracked changes before it refuses an untracked file that now exists, and
  a failed drop comes after a full apply, so a second pop would refuse on
  the restored part. It says to compare the stash with the working tree
  (`git stash show -p`, `git show <ref>^3:<path>`), restore what is
  missing and drop it. Which files the pop restored cannot be read off by
  blob equality (a pop merges each change into the new HEAD), so the
  message does not list them (review c6a2 i7).

`_reap_auto_stashes` drops an entry whose message is exactly `pm: auto-stash
for merge` when its changes are already applied:
- tracked and untracked paths: the worktree blob equals the stash blob
  (`hash-object` vs `rev-parse`), and a path the stash deleted is absent.
  The tracked paths come from `diff --no-renames`: with rename detection
  a renamed file's old path was never checked (review c6a2 i6);
- `pm/project.yaml`: `merge_3way(stash^1, stash, current) == current`, i.e.
  every change the stash made is present or superseded in the live registry.
  This is checked last, and the live registry is loaded only if some
  candidate changed it. Only stashes from an older pm do, so the lock hold
  normally stays at a few git calls.

Entries are dropped highest index first, after re-checking that each ref
still names the same commit. Entries that are not applied are listed with
inspect/drop hints.

`_resolve_project_yaml_pop(cwd, ref="stash@{0}")` is master's resolver. It is
now parameterized by ref, and it merges only files whose two sides parse as
pm registries (they have a `project` key). A user's file that merely has the
name is left alone. pm's auto-stash never carries the repo's own registry,
so the resolver now only fires for a nested pm project's registry, whose
lock is a different one.

## 3. Implicit requirements

- **No self-deadlock.** Nothing inside the held region calls
  `locked_update` / `_lock` on the same root. `trigger_tui_merge_lock` only
  writes a marker file. The registry is written with an atomic rename, not
  through `locked_update`. `_resolve_project_yaml_pop` locks only the
  conflicted registry's own root, which is never `repo/pm` (see 2c).
- **Master's mocked tests keep passing.** The mocked `run_git` returns
  `"master"` for every `rev-parse`, and `stash pop` is still called as
  `("stash", "pop", ref)`. `test_fetches_and_fast_forwards_in_repo_dir` now
  normalizes the cwd type (str/Path), since the reaper runs in the repo dir
  too. It also mocks `origin/master^{commit}` to a sha and asserts the
  fast-forward goes to that pinned commit.
- **Paths are raw.** `-z` porcelain plus `:(literal)` pathspecs, so spaces,
  non-ASCII, quotes and glob characters survive.

## 4. Edge cases

- **The registry is the only dirty file** (the original incident): no git
  stash is created at all. The overlap is resolved structurally, and the
  first fast-forward succeeds.
- **The registry is clean but the target changes it:** it is still swapped
  in atomically (the target's bytes), so lock-free readers never see git
  rewrite it.
- **A writer races the update** (QA S3, S74): serialized by the lock. Its
  pre-lock read only ever sees a complete registry. The pathspec exclusion
  is a second guard.
- **A writer hammers the lock:** the merge's polling acquire can starve.
  After 10 s it fails safe and touches nothing.
- **Two updates of the same repo** (concurrent merges, a fetch during the
  plan): they serialize on the lock. The target is pinned, a moved HEAD
  triggers a re-plan, and reaping never sees the other update's in-flight
  auto-stash. If the other update got *past* this one's target, the re-plan
  finds no fast-forward and plans nothing ("Already up to date").
- **Stash-pop conflict in ordinary files:** the update has landed and the
  registry is reconciled and valid. The stash is kept with a drop
  instruction. No window opens (master no longer opens merge windows).
- **A pop git refuses** (e.g. an untracked stashed file now exists from the
  merge): the stash is kept, and the message names it. git >= 2.34 has
  already applied the tracked part then, so the message says to restore
  the rest by hand and drop it, not to pop again.
  This covers the rescope note's open item (2) for every file type; the
  registry can no longer be the cause.
- **Old leaked auto-stashes** (the main repo held 7): applied ones are
  reaped on the next successful update; the rest are listed.
- **The live registry is invalid or has markers:** it is left untouched and
  the update fails like any overlapping file.

## 5. Test plan (R7) — `tests/test_merge_stash.py`

- Guard: `find_conflict_markers` forms and benign values; the `load()`
  message; a missing file is still a `FileNotFoundError`.
- `_dirty_file_paths`: worktree-only change; raw paths and renames;
  untracked files despite `status.showUntrackedFiles=no`.
- `_persist_with_backoff`: retry-then-succeed; exhaustion.
- `_ff_with_autostash` on real git:
  - overlapping edits reconcile (live wins, merged-in note and field kept,
    no markers, no stash, HEAD == target, nothing staged);
  - finalize gives merged + `merged_at`;
  - other dirty and untracked files are stashed and restored (the stash
    path is asserted to run: the registry swap alone no longer blocks the
    fast-forward);
  - a fast-forward that fails after the swap and the stash restores the
    exact registry bytes and the index (the restore is asserted to run:
    a diverged base plans nothing since i3);
  - an index entry that cannot be restored (`index.lock` held) is reported
    with the command that restores it;
  - a stash failure, or an empty stash push, restores the registry and
    never pops the user's own stash;
  - git never rewrites the live registry (same inode across merge and
    stash push/pop);
  - a clean registry is updated without leaving a dirty tree;
  - a staged registry hunk survives an update that fails after the swap;
  - a writer that re-dirties the registry never enters the text stash;
  - an uncommitted `pm/` dir never stashes the registry;
  - a user's `merge.autoStash=true` never text-stashes the registry;
    `--no-autostash` is passed only on git >= 2.27 (or an unknown version);
  - a writer saving between the plan and the lock: its change, the local
    edit and the merged-in note survive, and only the live text is parsed
    under the lock;
  - the target ref moving while planning is ignored (pinned commit);
  - another update moving HEAD before the lock triggers a re-plan, and the
    stash still pops cleanly;
  - a target HEAD already contains leaves the registry and the index alone,
    also when another update moved HEAD past it during the plan.
- Locking:
  - the lock is held during every rewriting git step (first fast-forward
    included) and released afterwards;
  - reaping (`stash list` / `stash drop`) runs under the lock, and not at
    all in a repo without pm's registry;
  - a busy lock leaves the checkout untouched, and the post-publish pull
    then exits 1 without a recovery window (`test_pr_enhancements.py`);
  - a concurrent writer thread loses no notes (3 runs);
  - `pm project set` writes under the lock (it did an unlocked load +
    save, which could drop a merge's reconciled registry).
- Restore and reap:
  - a conflicted pop keeps the stash, leaves the registry valid and opens no
    window (the warning names a path with a space unsplit);
  - a refused pop keeps the stash intact, also under a user's
    `status.showUntrackedFiles=no`;
  - a partly applied pop (untracked collision; a failed drop) keeps the
    stash and never suggests popping it again;
  - reaping drops applied entries (files plus a structural registry case)
    and keeps a non-applied entry and WIP;
  - a leaked stashed rename is kept while its old path still exists.
- `_resolve_project_yaml_pop`: a registry conflict from a text stash is
  resolved; a non-registry `project.yaml` is left alone.
- Master's `tests/test_merge_publish.py` covers the full `pm pr merge` local
  flow, including `test_local_merge_keeps_live_state_and_branch_project_yaml_changes`.

Pre-fix evidence: 9 of the 16 fast-forward/lock/reap tests fail on master's
code (a shim drives master's inline sequence). The concurrent-writer test
fails there with "Your local changes … would be overwritten by merge".

CLI race evidence (#253 S74 story 1, disposable fixture; harness and
results in `$CAP/impl/s74-harness`, `$CAP/impl/s74-summary.md`):

| code | registry only | + dirty user files |
|---|---|---|
| master | 0/8 | 0/6 |
| fix | 12/12 | 8/8 |

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
