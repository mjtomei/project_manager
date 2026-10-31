# pr-f74988c — Auto-commit single PR row on `pm pr start`

## Requirements (grounded)

1. **Replace error path in `pm_core/cli/pr.py:871-885`**: when the PR is in
   working `project.yaml` but missing from `base_branch:project.yaml`, call a
   new helper instead of `click.echo(...) + raise SystemExit(1)`. Only fall
   through to that error if the helper returns failure. The "PR not in
   working yaml at all" branch (line 880-884) is unchanged.

2. **Helper lives in new `pm_core/store_commit.py`**, exposing
   `commit_pr_entry_on_base(repo_root, yaml_path, base_branch, pr_id, backend)
   -> tuple[bool, str | None]` returning (success, error_reason).

3. **Plan-not-yet-committed check**: if the working PR entry has a `plan`
   field referencing a `plan-NNN` id, that plan must already exist in
   `base_branch:project.yaml`'s `plans:` list. Otherwise return
   `(False, "plan <id> is not committed on <base>; run `pm push` to land it
   together with the PR row")`.

4. **Process-wide lock**: acquire `~/.pm/sessions/<tag>/yaml-commit.lock` via
   `fcntl.flock(fd, LOCK_EX)` blocking with a 30 s deadline (poll-NB +
   `time.sleep` so the deadline is honored, mirroring
   `pm_core/store.py:_lock`). Release on every exit path. The session tag
   comes from `pm_core.paths.get_session_tag()` / `session_dir()`.

5. **Re-read after lock**: re-run `git show base:yaml_path` inside the lock.
   If the PR row is now committed, return `(True, None)` with no further work.

6. **Synthetic content build**:
   - Load committed yaml (parsed with `yaml.safe_load`).
   - Load working yaml (`store.load(root)` is too strict — use plain
     `yaml.safe_load` so we don't validate other PRs).
   - Pull working PR entry by id.
   - Verify the working PR entry's `plan` reference is committed.
   - Build a copy of the committed yaml, append the PR entry to its `prs:`
     list (creating the list if absent).

7. **Diff verification (defense)**: serialize old vs new yaml, run a
   structural diff. Bail if any change other than "exactly one new entry
   appended to `prs`" is observed. Implementation: compare every top-level
   key besides `prs`, and the lengths/contents of `prs` minus the new entry.

8. **Commit on base via plumbing** (no checkout of working tree):
   - `git rev-parse <base>` → `base_commit`.
   - `git hash-object -w --stdin` (write blob).
   - In a temp `GIT_INDEX_FILE`: `git read-tree base_commit`,
     `git update-index --cacheinfo 100644,<blob>,<yaml_path>`,
     `git write-tree` → `tree`.
   - `git commit-tree tree -p base_commit -m "pm: add <pr_id> entry on <base>"`
     → `commit`.
   - `git update-ref refs/heads/<base> commit base_commit` (with the old-value
     sentinel — fails atomically if base advanced under us).
   - If the user's HEAD is on `<base>`, also update the *real* index (same
     `update-index --cacheinfo`) so `git status` doesn't show the PR row as
     "removed" relative to the new HEAD.

9. **Push**:
   - For `backend == "local"`: skip push.
   - Else: `git push origin <base>:<base>`. On non-zero, roll back local ref
     (`update-ref` back to `base_commit`) and the real-index update if
     applied, and return `(False, "push rejected by remote")`.

10. **base_branch advanced remotely while we held the lock**: best-effort
    `git fetch origin <base>` *before* building the commit, then check
    `git rev-parse origin/<base>` vs local — if remote is ahead, fast-forward
    local first, re-load committed yaml from the new tip (still inside the
    lock), and rebuild. If FF fails, return `(False, "base advanced
    non-fast-forward")`.

11. **Lock timeout**: return `(False, "timed out waiting on yaml-commit lock
    after 30s")` rather than hanging.

## Implicit requirements

- The yaml writer must produce byte-identical output to what `pm` would write
  on a normal save, otherwise unrelated noise leaks into the commit. Reuse
  `store._YAML_HEADER` and the same `yaml.dump(..., default_flow_style=False,
  sort_keys=False, allow_unicode=True)` arguments.
- The helper runs against the *base* repo (`root.parent` if internal else
  `root`) — same `repo_root` derivation already in pr.py:855-857.
- The helper must not touch the working tree's `project.yaml` file on disk.
- Don't acquire the project.yaml advisory lock (`store._lock`); we're not
  rewriting the working `project.yaml`. Concurrency on the synthetic-commit
  path is handled by the new yaml-commit lock alone.

## Ambiguities (resolved)

- **Branch name for the synthetic commit**: spec says "fresh branch from
  base_branch tip". I instead commit directly onto `base_branch` via
  `update-ref` (no intermediate branch). Rationale: the spec also says
  "fast-forward base_branch locally" after pushing, which implies the goal is
  for `base_branch` to point at the new commit. Using `update-ref` achieves
  the same end-state with no branch churn and is atomic via the
  old-value sentinel. The new commit's parent is exactly `base_commit`, so
  the result is a fast-forward push.

- **Helper signature**: spec suggests
  `commit_pr_entry_on_base(base_branch, pr_id) -> bool`. I add `repo_root`,
  `yaml_path`, and `backend` as parameters (all derivable at the call site,
  awkward to derive inside the helper) and widen the return to
  `(bool, str | None)` so the caller can surface a precise reason in the
  fallback error.

- **`pm pr start` calls `git_ops` with `cwd=repo_root` (a `str`)**: the new
  helper accepts either `str` or `Path` for parity.

## Edge cases

- Working yaml is newer / has additional PRs the user hasn't pushed: those
  are *not* included. The synthetic content is `committed_yaml +
  this_one_pr_entry`. Diff verification enforces this.
- PR entry has no `plan` field (free-floating PR): plan check is skipped.
- `prs:` key absent or `None` in committed yaml: treat as empty list, add
  the entry as the first one.
- Concurrent invocations for the *same* pr_id: second waiter, after acquiring
  the lock, re-reads base and finds the row already committed → returns
  `(True, None)` with no further work.
- Repo not git: shouldn't happen in practice (the call site already assumes
  git via `git show`), but defend with a guard returning `(False, "not a
  git repo")`.
- `base_branch` advanced locally while we held the lock (e.g., user pulled
  in another shell): the `update-ref` old-value sentinel makes the operation
  fail atomically; we surface `(False, "base advanced under us")`.
