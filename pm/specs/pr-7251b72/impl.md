# Implementation Spec: Refuse pm pr start when PR is not committed on base branch

## Requirements

### R1 — Read committed project.yaml before cloning

**File:** `pm_core/cli/pr.py:734` (`pr_start`)

Before the clone step (~line 859), read the committed version of `project.yaml` from git using `git show HEAD:pm/project.yaml` (or `git show HEAD:project.yaml` for standalone PM repos). This must run from the git repo root of the source repo (i.e., `root.parent` for internal PM dirs, or `root` for standalone).

Use `git_ops.run_git("show", f"HEAD:{relative_path}", cwd=repo_root, check=False)` and parse the stdout as YAML.

### R2 — Check that the PR ID exists in committed data

**File:** `pm_core/cli/pr.py:734` (`pr_start`)

After reading the committed YAML, iterate its `prs` list and verify the target `pr_id` is present. This mirrors the logic in `store.get_pr()` but operates on the committed data dict, not the working-tree data.

### R3 — Emit a clear error and exit non-zero when PR is missing

**File:** `pm_core/cli/pr.py:734` (`pr_start`)

If the PR ID is not found in the committed data, print:
```
PR {pr_id} is not committed to {base_branch} yet. Run `pm push` to commit project state before starting.
```
Then `raise SystemExit(1)`.

### R4 — Placement: check must run after PR resolution but before clone

The check must happen after:
- PR ID resolution (lines 746-768) — so we know which PR to look for
- `_require_pr()` (line 770) — so we know the PR exists in the working tree
- Spec-pending gate (lines 778-788) — so we don't give a confusing "not committed" error when the real issue is a pending spec
- Status checks (in_progress reuse at line 790, merged check at line 800)

And before:
- The clone step (line 859) — which is the operation that would fail silently without the committed PR

The ideal insertion point is just before the tmux fast-path check at line 804, or just after the merged check at line 802.

---

## Implicit Requirements

### I1 — Handle both internal and standalone PM directory layouts

`state_root()` returns either a `pm/` subdirectory inside a repo (internal) or a standalone directory. The `git show` path must be:
- `pm/project.yaml` when `store.is_internal_pm_dir(root)` is True (repo root is `root.parent`)
- `project.yaml` when standalone (repo root is `root`)

### I2 — Handle git show failures gracefully

`git show HEAD:...` can fail if:
- No commits exist yet (fresh repo with no HEAD)
- The file doesn't exist in the committed tree (never been committed)

In both cases, the PR cannot be in committed state, so the check should treat failure as "PR not committed" and emit the error message.

### I3 — The check should not run when reusing an existing workdir

When `pr_entry.get("status") == "in_progress"` and the existing workdir still exists (line 790-795), the function reuses that workdir and doesn't clone. The committed-state check is only needed to prevent a fresh clone from missing the PR. However, even in the reuse case, the workdir was originally cloned from committed state, so the check is still valid and harmless — it should run unconditionally after PR resolution to catch all cases.

### I4 — Use base_branch, not HEAD, for the git show ref

The task description says `git show HEAD:pm/project.yaml`, but the clone uses `base_branch` (line 861). In practice HEAD should equal base_branch in the main repo. Using `HEAD` is simpler and more correct — if someone is on a different branch, HEAD reflects what would actually be cloned from `local_source`. Actually, the clone explicitly checks out `base_branch` (line 861: `git_ops.clone(local_source, tmp_path, branch=base_branch)`), so we should use `base_branch` as the ref to match what the clone will see.

**Resolution:** Use `{base_branch}:path` (e.g., `master:pm/project.yaml`) as the git show ref. This matches the branch the clone will check out and is more precise than HEAD.

---

## Ambiguities

### A1 — Should the check use HEAD or base_branch?

The task says `git show HEAD:pm/project.yaml` but the clone checks out `base_branch`.

**Resolution:** Use `base_branch` (e.g., `master`) as the ref. This matches what the workdir clone will contain. If the user committed to a feature branch but not to master, the clone from master would still miss the PR. Using `base_branch` gives an accurate check.

### A2 — Should the check be skipped for in_progress PRs that reuse existing workdirs?

When a PR is already `in_progress` with a valid workdir, no clone happens.

**Resolution:** Run the check unconditionally. Even for in_progress PRs, if the PR was somehow removed from the committed state, the user should know. The check is cheap and harmless in the reuse path.

### A3 — Error message: should it say `base_branch` name or just "git"?

The task example says "not committed to {base_branch}". 

**Resolution:** Include the branch name: `PR {pr_id} is not committed on {base_branch} yet. Run 'pm push' to commit project state before starting.` This helps the user understand exactly which branch needs the commit.

### A4 — Where to read base_branch from

`base_branch` is read from `data["project"].get("base_branch", "master")` at line 838, which is after our insertion point.

**Resolution:** Read `base_branch` earlier (just before the check), or move the check to after line 838. Since the check needs `base_branch`, place the check between line 838 and the workdir/clone logic starting at line 841.

---

## Edge Cases

### E1 — PR added but project.yaml never committed

If project.yaml has never been committed to git (e.g., brand-new repo with only staged/unstaged changes), `git show` fails. The check correctly treats this as "PR not committed" and blocks.

### E2 — PR committed on master but project.yaml modified locally with different PR list

The working-tree project.yaml might have additional PRs not yet committed. The check correctly catches this — only committed PRs can be started.

### E3 — Standalone PM repos vs internal pm/ subdirs

The git show path differs. `is_internal_pm_dir` determines the layout. Both paths must be tested.

### E4 — base_branch doesn't exist in local repo

If `base_branch` doesn't exist locally (e.g., never fetched), `git show {base_branch}:...` fails. Treat as "not committed" which is technically correct.

### E5 — YAML parse error in committed project.yaml

If the committed file contains invalid YAML, `yaml.safe_load` raises an exception. Treat this as "not committed" — the check should catch the exception and emit the standard error.
