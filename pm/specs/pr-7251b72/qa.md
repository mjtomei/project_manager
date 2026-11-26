# QA Spec: Refuse pm pr start when PR is not committed on base branch

## Requirements

### R1 — Block `pm pr start` when PR is absent from committed project.yaml

**File:** `pm_core/cli/pr.py:842-867`

After resolving the PR ID and reading `base_branch`, the code runs
`git show {base_branch}:pm/project.yaml` (or `project.yaml` for standalone repos),
parses the output as YAML, and checks whether the target PR ID exists in the
committed `prs` list via `store.get_pr()`. If the PR is missing, it prints an
error to stderr and raises `SystemExit(1)`.

### R2 — Error message includes PR ID and base_branch name

The error message must be:
```
PR {pr_id} is not committed on {base_branch} yet. Run `pm push` to commit project state before starting.
```

### R3 — Allow `pm pr start` when PR is present in committed data

When the committed project.yaml contains the target PR, the check passes
silently and execution continues to the clone/workdir logic.

### R4 — Check placement: after status gates, before clone

The committed-state check runs after:
- PR ID resolution and `_require_pr()`
- `spec_pending` gate
- `in_progress` reuse logic
- `merged` rejection

And before:
- tmux fast-path check
- Clone / workdir creation

### R5 — Handle `git show` failures gracefully

If `git show` fails (returncode != 0), e.g. no commits or branch doesn't exist,
treat it as "PR not committed" and block with the same error message.

### R6 — Handle invalid YAML in committed project.yaml

If the committed file is valid in git but contains invalid YAML or is not a dict,
treat it as "PR not committed" and block with the same error message.

## Setup

- A temporary project directory with `pm/project.yaml` containing at least one PR
- Git initialized with at least one commit (for `git show` to work in the happy path)
- Mocked `git_ops.run_git` to control what `git show` returns
- The `tmp_start_project` pytest fixture (in `tests/test_pr_enhancements.py:1087-1112`)
  provides this setup

## Edge Cases

### E1 — PR added to working tree but not committed
`git show` returns a project.yaml without the PR. Expect: exit code 1, "not committed" in output.

### E2 — `git show` fails entirely (no commits, wrong branch, not a repo)
`git show` returns non-zero exit code. Expect: exit code 1, "not committed" in output.

### E3 — Committed project.yaml is invalid YAML
`git show` succeeds but stdout is malformed YAML. Expect: exit code 1, "not committed" in output.

### E4 — Committed project.yaml is valid YAML but not a dict (e.g. a list or string)
`yaml.safe_load` succeeds but returns a non-dict. Expect: exit code 1, "not committed" in output.
(This was fixed in commit dd6841e — the `not isinstance(committed_data, dict)` guard.)

### E5 — PR is committed and present
`git show` returns valid YAML with the PR in the `prs` list. Expect: check passes,
no "not committed" message, execution continues to clone.

### E6 — Internal PM dir (pm/ inside a repo) vs standalone
The code uses `store.is_internal_pm_dir(root)` to determine the git show path
(`pm/project.yaml` vs `project.yaml`) and repo root (`root.parent` vs `root`).
Both layouts must be exercised.

### E7 — `in_progress` PR with existing workdir
The committed-state check still runs (it's placed after the in_progress reuse
logic). This is harmless — the PR should already be committed if it was ever started.

### E8 — `yaml.safe_load` returns None (empty file)
The `or {}` fallback in `yaml.safe_load(committed_result.stdout) or {}` handles
this, producing an empty dict which has no `prs` key, so `get_pr` returns None.

### E9 — Spec-pending PR
The spec-pending gate runs before the committed-state check. A PR with
`spec_pending` set should be blocked by the spec gate, not the committed-state
check.

## Pass/Fail Criteria

**Pass:**
- All existing unit tests in `TestPrStartCommittedGate` pass (4 tests)
- The spec-gate test (`TestPrStartSpecGate.test_allows_start_when_no_spec_pending`)
  still works with the committed-state check present
- Error message contains the PR ID, base_branch name, and "not committed"
- Exit code is 1 when blocked, 0 (or continues to clone) when allowed
- No regressions in other `pr_start` behavior (tmux fast-path, workdir reuse, etc.)

**Fail:**
- Any of the above tests fail
- The committed-state check blocks a PR that IS committed
- The committed-state check allows a PR that is NOT committed
- A `git show` failure causes an unhandled exception instead of the clean error

## Ambiguities

### A1 — Should the check run for `in_progress` PRs reusing a workdir?

**Resolution:** Yes. The check runs unconditionally after status gates. For
`in_progress` PRs the workdir already exists, so the check is harmless — but it
ensures consistency. The code places the check after the reuse logic, so a reused
`in_progress` PR that somehow lost its committed state would still be caught.

### A2 — What ref to use: HEAD vs base_branch?

**Resolution:** Use `base_branch`. The clone checks out `base_branch`, so the
committed-state check must inspect the same ref to accurately predict what the
workdir will contain.

### A3 — Should the error go to stdout or stderr?

**Resolution:** stderr (`err=True` in the `click.echo` call). This matches the
convention used by other error messages in `pr_start` (spec gate, merged check, etc.).

## Mocks

### git_ops.run_git
**Contract:** Simulates `git show {base_branch}:pm/project.yaml` returning the
committed file content.
**Scripted responses:**
- **PR not committed:** `MagicMock(returncode=0, stdout="project:\n  name: test\nprs: []\n")` — valid YAML but no matching PR
- **git show fails:** `MagicMock(returncode=128, stdout="", stderr="fatal: not a git repo")` — simulates no commits or missing ref
- **Invalid YAML:** `MagicMock(returncode=0, stdout=": {invalid yaml\n  - [broken")` — malformed YAML
- **PR committed (happy path):** `MagicMock(returncode=0, stdout=yaml.dump({"project": {...}, "prs": [{"id": "pr-001", ...}]}))` — valid YAML with the target PR

**What remains unmocked:** `store.load()`, `store.save()`, `store.get_pr()` — these
operate on real temp-dir files via the `tmp_start_project` fixture.

### state_root
**Contract:** Returns the temp project's `pm/` directory path.
**Scripted response:** `return_value=tmp_start_project["pm_dir"]`

### _get_pm_session
**Contract:** Returns None to skip tmux fast-path logic.
**Scripted response:** `return_value=None`

### Clone-path mocks (happy path only)
When testing the happy path (PR is committed), additional mocks are needed to
prevent actual git clone operations:
- `git_ops.clone` — return None
- `git_ops.is_git_repo` — return False
- `git_ops.checkout_branch` — return None
- `git_ops.run_git` side_effect list for subsequent calls (rev-parse)
- `find_claude` — return None
- `save_and_push`, `trigger_tui_refresh`, `_resolve_repo_id` — no-ops
- `prompt_gen.generate_prompt` — return "prompt"
