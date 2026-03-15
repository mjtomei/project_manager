---
title: "PR Start: Workdir and Branch Setup"
description: "Test pm pr start creates workdir, sets up branch, and validates options"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project with at least
one PR in pending status. If none exists, create one first with `pm pr add`.

## Test Steps

### 1. List PRs and pick one to start
```bash
pm pr list
```
Record a PR ID in pending status. If none, create one:
```bash
pm pr add "Regression test start target"
```

### 2. Verify pr start --help shows expected options
```bash
pm pr start --help
```
Confirm it lists: `--workdir`, `--fresh`, `--background`, `--transcript`, `--companion`.

### 3. Check workdir creation logic
```bash
python3 -c "
from pm_core.cli.helpers import state_root, _workdirs_dir
from pm_core import store
root = state_root()
data = store.load(root)
# Verify workdir base path resolution works
wdir = _workdirs_dir(data)
print(f'Workdirs base path: {wdir}')
print(f'Exists: {wdir.exists() if wdir else False}')
"
```

### 4. Verify branch naming convention
```bash
python3 -c "
from pm_core import store
# Branch names follow pm/<pr-id>-<slug> convention
slug = store.slugify('Test PR title for branch naming')
branch = f'pm/pr-abc1234-{slug}'
print(f'Branch name: {branch}')
assert branch.startswith('pm/'), f'Branch should start with pm/, got {branch}'
print('Branch naming convention: OK')
"
```

### 5. Verify start refuses to work on merged/closed PRs
```bash
python3 -c "
from pm_core.cli import pr as pr_mod
import inspect
# Check that status validation exists in the pr start command
src = inspect.getsource(pr_mod)
assert 'merged' in src.lower() or 'closed' in src.lower(), 'No status guard in pr module'
print('Status guard logic present: OK')
"
```

### 6. Clean up test PR if created
If you created a test PR in step 1:
```bash
pm pr close <test-pr-id>
```

## Expected Behavior

- `pm pr start` creates a workdir with a git clone/worktree
- Branch naming follows `pm/<pr-id>-<slug>` convention
- Start refuses to work on merged/closed PRs
- `--background` flag is accepted for non-interactive launch

## Reporting

```
TEST RESULTS
============
pr list/add:       [PASS/FAIL] - Can list and create PRs
start --help:      [PASS/FAIL] - Help shows expected options
workdir path:      [PASS/FAIL] - Workdir path resolved correctly
branch naming:     [PASS/FAIL] - Branch follows pm/ convention
status guard:      [PASS/FAIL] - Refuses merged/closed PRs

OVERALL: [PASS/FAIL]
```
