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

## Relevant code (verified)

- `pm_core/cli/pr.py`
  - `_stash_for_merge(cwd, pr_display_id="", lock_tui=True)` (≈2265) — computes
    dirty files via `_dirty_file_paths`, sets TUI merge-lock if pm/ files are
    dirty, runs `git stash push --include-untracked -m "pm: auto-stash for merge"`.
    Returns `{has_pm, count, lock_tui}` or `None` (nothing dirty / stash failed).
  - `_unstash_after_merge(cwd, info)` (≈2298) — `git stash pop`; on rc!=0 just
    echoes a warning and returns False. **This is the corruption + leak site.**
  - Three call sites, all passing the **main repo dir** or the **PR workdir** as
    `cwd`:
    1. `_pull_after_merge` (≈1589/1597/1611) — ff-merge `origin/base` into the
       main repo dir (its `pm/project.yaml` IS the live `state_root()` file →
       the catastrophic case).
    2. `_pull_from_workdir` (≈1685/1692/1706) — local backend ff-merge into main
       repo dir (same live file).
    3. `pr_merge` workdir merge (≈1928/1933/1949/1973) — `checkout base` + merge
       in the PR's workdir clone.
  - `_finalize_merge(root, pr_entry, pr_id, …)` (1411) — sets `status="merged"` +
    `merged_at` via `store.locked_update`; runs AFTER a successful pull. Its
    `store.load` is what blows up on a corrupt file → symptom 1's stuck PR.
  - `_dirty_file_paths(cwd)` (2250), `_is_dirty_overlap_error(result)` (2244),
    `_launch_merge_window(data, pr_entry, error_output, …)` (1447).
- `pm_core/store.py`
  - `load(root, validate=True)` (101) — `yaml.load`; wraps `yaml.YAMLError` as
    `ProjectYamlParseError(f"project.yaml is not valid YAML: {e}")`. No
    conflict-marker awareness → cryptic scanner traceback.
  - `locked_update(root, fn, validate=True, timeout=2.0)` (284) — exclusive
    advisory lock, re-reads fresh disk state under the lock, applies `fn`, saves.
    This is the structured, serialized write path the fix should route through.
  - `save(data, root)` (188) — atomic write + chmod read-only.
- `pm_core/git_ops.py: run_git(*args, cwd=None, check=True)` (81).

## 1. Requirements (grounded)

R1. **No conflict markers in `project.yaml`, ever.** The merge flow must never
    leave `<<<<<<<`/`=======`/`>>>>>>>` in `pm/project.yaml`. Reconcile the
    concurrent `project.yaml` edits *structurally* instead of via text stash/pop.

R2. **No leaked stash.** After a merge (success or handled failure), no
    `pm: auto-stash for merge` stash remains.

R3. **`store.load` conflict-marker guard.** When `project.yaml` does contain git
    conflict markers (from any source / pre-existing corruption), `store.load`
    must raise `ProjectYamlParseError` with a clear message naming the file, the
    offending line number, and remediation — not a raw YAML scanner error.

R4. **Merged PR ends `status="merged"` with `merged_at` set.** Because the git
    merge succeeds, the bookkeeping finalize must complete (it currently dies on
    the corrupt load). With R1 satisfied, `_finalize_merge`'s `store.load`
    succeeds and the PR is finalized.

R5. **Stash-pop conflict launches a resolution session** (PR-note 3). If a
    `git stash pop` of *non-project.yaml* files genuinely conflicts, launch a
    `_launch_merge_window` (matching the real-merge-conflict paths) instead of
    only printing a warning — and still never leave `project.yaml` corrupt or a
    stash leaked.

R6. **Tests** simulating concurrent `project.yaml` edits across a merge assert:
    (a) `project.yaml` stays valid YAML, (b) no conflict markers are ever
    written, (c) no stash is left behind, (d) the merged PR ends `status=merged`
    with `merged_at` set.

## 2. Design

### 2a. `store.py`: conflict-marker guard (R3)

Add a module helper and call it from `load()`:

```python
_CONFLICT_MARKER_PREFIXES = ("<<<<<<< ", "||||||| ", ">>>>>>> ")

def find_conflict_markers(text: str) -> list[tuple[int, str]]:
    """Return (1-based line no, marker line) for git conflict markers."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if line.startswith(_CONFLICT_MARKER_PREFIXES) or line.rstrip() == "=======":
            hits.append((i, line))
    return hits
```

In `load()`, read the file text once; if `find_conflict_markers(text)` is
non-empty, raise `ProjectYamlParseError` with the path, the first marker's line
number + content, and remediation ("contains git conflict markers from a failed
stash/merge … resolve the markers or restore from git, then re-run"). Otherwise
parse the same text (avoid a second read). The `=======` check requires the line
to be *exactly* seven equals (a YAML value/key is virtually never that), keeping
false positives effectively impossible.

This is defense-in-depth: with 2b the markers should never be written, but the
guard turns any residual/external corruption into an actionable message and is
the cheapest independent safety net.

### 2b. `store.py`: structured 3-way merge (R1)

Add `three_way_merge(base, ours, theirs)` to reconcile two divergent
`project.yaml` dicts against their common ancestor:

- **dicts**: per-key 3-way. For key `k` with values `b/o/t` (sentinel `MISSING`
  for absent):
  - `o == t` → take `o`.
  - `b == o` (only theirs changed) → take `t` (drop key if `t` MISSING).
  - `b == t` (only ours changed) → take `o` (drop key if `o` MISSING).
  - both changed & both dicts → recurse; both changed & both id-keyed lists →
    recurse the id-maps; otherwise **prefer `ours`** (the post-merge / committed
    authority). Document this leaf tie-break.
- **`prs` / `plans` lists** (lists of dicts with an `id`): treat as id-keyed
  ordered maps, 3-way merge the maps, rebuild the list preserving `ours` order
  then appending `theirs`-only entries. This correctly handles "origin merged a
  PR the local copy didn't know about", "local started a PR origin didn't have",
  and per-field changes on the same PR.
- other lists / scalars: leaf rule above.

This is the structured reconciliation the task's preferred direction calls for;
it runs in memory and the result is persisted under the store lock, so there is
never a text conflict.

### 2c. `pr.py`: keep `project.yaml` out of the text stash (R1, R2)

Rework `_stash_for_merge` / `_unstash_after_merge` so `project.yaml` is handled
structurally and never round-trips through `git stash`:

`_stash_for_merge(cwd, …)`:
1. `dirty = _dirty_file_paths(cwd)`; return `None` if empty (unchanged).
2. Find the project.yaml entry among dirty (`pm/project.yaml` or `project.yaml`).
3. If present:
   - `root_for_py = cwd/"pm"` if `pm/project.yaml`, else `cwd`.
   - `base = git show HEAD:<rel>` parsed as YAML (committed pre-merge state; `{}`
     if the show fails / file new).
   - `overlay = yaml.load(<current working file>)` (the local dirty bookkeeping).
   - `git checkout -- <rel>` to revert the file to HEAD so the pending
     checkout/merge can replace it freely and it is excluded from the stash.
   - Record `info["py"] = {"root", "rel", "base", "overlay"}`.
   - Recompute remaining dirty files.
4. Stash the **remaining** dirty files (`git stash push --include-untracked -m
   "pm: auto-stash for merge"`) only if any remain; record `info["stashed"]`.
   (project.yaml is now clean, so it is never in the stash.)
5. Return `info` whenever project.yaml was handled OR a stash was created (so the
   caller retries the merge and later calls `_unstash_after_merge`). Keep
   `has_pm`/`count`/`lock_tui` for the existing TUI merge-lock behavior.

`_unstash_after_merge(cwd, info, *, data=None, pr_entry=None, **window_kwargs)`:
1. If `info.get("stashed")`: `git stash pop`.
   - rc==0 → clean (git auto-drops the popped stash).
   - rc!=0 (conflict on the non-project.yaml files): never leave markers — these
     are genuine code conflicts. Launch `_launch_merge_window` when `data` and
     `pr_entry` are supplied (R5); leave the stash for the user to resolve in
     that window (do NOT reap it). Echo a clear message. Set `clean=False`.
2. If `info.get("py")`: re-apply structurally via `locked_update` on
   `info["py"]["root"]`:
   ```python
   def apply(d):
       merged = store.three_way_merge(py["base"], d, py["overlay"])
       d.clear(); d.update(merged)
   store.locked_update(py["root"], apply, validate=False)
   ```
   `locked_update` re-reads the freshly-merged on-disk `project.yaml` (`ours`)
   under the lock, so concurrent writes from other pm processes are respected,
   and writes valid YAML — no text conflict possible.
3. If the pop was clean (no outstanding conflict): reap leaked auto-stashes via
   `_reap_auto_stashes(cwd)` (R2) — drop only stashes whose message is exactly
   `pm: auto-stash for merge` (never other WIP stashes, to avoid data loss).
4. Restore TUI merge-lock as today; return `clean`.

`_reap_auto_stashes(cwd)`: `git stash list` → for each entry whose message is
`pm: auto-stash for merge`, `git stash drop <ref>` (drop highest-index first so
refs stay valid).

Thread `data` / `pr_entry` (+ the same merge-window kwargs each site already
builds) into the three `_unstash_after_merge` call sites so R5 can fire.

## 3. Implicit requirements

- **Right root for re-apply.** `info["py"]["root"]` must point at the dir
  actually containing the dirty `project.yaml` (main repo's `pm/` for sites 1–2,
  the workdir's `pm/` for site 3), independent of `state_root()`.
- **Locking discipline.** Re-apply goes through `locked_update` (no network under
  the lock); the structured merge is pure/in-memory.
- **Existing mocked tests keep passing.** `test_dirty_workdir_stashes_on_overlap`
  (dirty `some_file.py`, mocked git) must still see `stash push`+`stash pop`;
  since the dirty file isn't project.yaml, the new project.yaml branch is skipped
  and `_reap_auto_stashes`/conflict-detection git calls return rc0/empty under
  the existing catch-all mock. `test_local_merge_pulls_into_repo`,
  `test_dirty_workdir_proceeds_when_no_overlap` (clean / no-overlap) unaffected.
- **`git show HEAD:<rel>` quoting** uses the repo-relative path; on failure
  (untracked/new file) fall back to `base={}`.
- **`validate=False` on re-apply** avoids raising on a transient invalid
  cross-state; `_finalize_merge` re-validates on its own `locked_update`.

## 4. Edge cases

- **project.yaml is the *only* dirty file** (the real incident): after
  `git checkout -- <rel>` nothing remains to stash, so `info["stashed"]` is
  False and no git stash is created at all — the overlap is resolved purely
  structurally. Caller still retries the (now-clean) merge and re-applies.
- **Concurrent write between checkout and re-apply**: handled — `locked_update`
  re-reads `ours` from disk under the lock, then 3-way-merges, so the other
  process's write becomes `ours` and is preserved.
- **Reaping vs. a concurrent in-flight merge**: only `pm: auto-stash for merge`
  messages are reaped, and only after our own pop is clean. Two concurrent
  merges on the same working tree already serialize on the git index; the
  message is pm-internal so a surviving one is by definition leaked. Other WIP
  stashes (e.g. the 2-month-old refactor in the incident) are never auto-dropped.
- **Non-project.yaml stash-pop conflict** (rare for sites 1–2 which touch the
  base branch): R5 window launches; stash retained for manual resolution;
  project.yaml still reconciled structurally and uncorrupted.
- **Backwards-compat of `_unstash_after_merge` signature**: new params are
  keyword-only with defaults so any other caller (none found) still works.

## 5. Test plan (R6)

- `tests/test_store.py` (or `test_store_validation.py`): conflict-marker guard —
  a `project.yaml` containing markers raises `ProjectYamlParseError` mentioning
  the line number; `find_conflict_markers` unit cases incl. the exact-`=======`
  rule and a benign file with `===` inside a value not tripping it.
- `tests/test_store.py`: `three_way_merge` unit cases — scalar 3-way (only-ours,
  only-theirs, both/ours-wins), id-keyed `prs` merge (origin-only PR added,
  local-only PR kept, same-PR field merge incl. status advance).
- **Real-git integration** (`tests/test_pr_enhancements.py` or new
  `tests/test_merge_stash.py`): build a real repo with committed `project.yaml`;
  make the working tree dirty with a local `updated_at`; advance HEAD with a
  conflicting `updated_at` (simulating the merged-in change); run
  `_stash_for_merge` → ff/merge → simulate a concurrent on-disk write →
  `_unstash_after_merge`; assert (a) file parses, (b) no `<<<<<<<` markers,
  (c) `git stash list` empty. On **pre-fix** code this fails (markers + leaked
  stash). 
- **Finalize/flow** (R6d): assert that after a stash-pop reconciliation the
  subsequent `_finalize_merge`/`locked_update` load succeeds and yields
  `status="merged"` + `merged_at` set (a corrupt file would raise). Can be a
  focused test that seeds a reconciled file and runs `_finalize_merge`, plus the
  load-guard test proving the pre-fix corrupt file would have blocked it.

## 6. Ambiguities (resolved)

- **Leaf tie-break when both sides change the same scalar** → prefer `ours`
  (post-merge / committed state). Rationale: committed/merged data is the shared
  authority; the lost side is almost always a transient timestamp that the next
  `locked_update` re-asserts. Documented in `three_way_merge`.
- **How aggressively to reap stashes** → only `pm: auto-stash for merge`
  messages, never arbitrary WIP, to avoid the data-loss risk of dropping the
  incident's old refactor stash. Stale non-pm stashes are out of scope (left for
  a future `pm doctor`).
- **Scope of structural handling** → applied uniformly at all three call sites
  via the shared helpers (main repo dir and workdir clone), since both can leak a
  stash / corrupt their project.yaml.

No **[UNRESOLVED]** ambiguities.

## 7. Second failure class (pr-d887f4c / #210) — partial, scoped

PR-notes flag a related lock-contention class: `pr start` runs `gh pr create`
(irreversible) at `pr.py:943`, then persists `gh_pr_number` via
`store.locked_update` at `pr.py:967`. Under concurrent pm operations that
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
