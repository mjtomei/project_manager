---
title: "PR Sync: State Synchronization"
description: "Test pm pr sync and sync-github for status reconciliation"
tags: [core, github]
---

## Setup

Work in the current directory which has an initialized pm project.
The `sync-github` tests require a GitHub backend; `sync` works on any backend.

## Test Steps

### 1. Check sync command exists
```bash
pm pr sync --help 2>&1 || echo "sync command not found"
```

### 2. Check sync-github command exists
```bash
pm pr sync-github --help 2>&1 || echo "sync-github command not found"
```

### 3. Run sync on current state
```bash
pm pr sync 2>&1
```
Record output — should report any PRs whose merged status was updated.

### 4. Verify sync is idempotent
```bash
pm pr sync 2>&1
```
Running sync again should produce the same state with no new changes.

### 5. Test sync-github (GitHub backend only)
```bash
python3 -c "
from pm_core.cli.helpers import state_root
from pm_core import store
root = state_root()
data = store.load(root)
backend = data.get('project', {}).get('backend', 'local')
print(f'Backend: {backend}')
if backend == 'github':
    print('GitHub backend detected — sync-github is applicable')
else:
    print('Non-GitHub backend — sync-github may be skipped')
"
```

If GitHub backend:
```bash
pm pr sync-github 2>&1
```

### 6. Verify state file unchanged by redundant sync
```bash
python3 -c "
from pm_core.cli.helpers import state_root
from pm_core import store
import hashlib

root = state_root()
path = root / 'project.yaml'
hash1 = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
print(f'State hash before sync: {hash1}')
"
```
```bash
pm pr sync 2>&1
```
```bash
python3 -c "
from pm_core.cli.helpers import state_root
import hashlib

root = state_root()
path = root / 'project.yaml'
hash2 = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
print(f'State hash after sync: {hash2}')
"
```

## Expected Behavior

- `pm pr sync` checks for merged PRs and updates status
- `pm pr sync-github` fetches PR status from GitHub API
- Both commands are idempotent — repeated runs don't corrupt state
- Non-GitHub backends gracefully handle sync-github (error or no-op)

## Reporting

```
TEST RESULTS
============
sync exists:       [PASS/FAIL] - pm pr sync command available
sync-github exists:[PASS/FAIL] - pm pr sync-github command available
sync runs:         [PASS/FAIL] - Sync executes without error
idempotent:        [PASS/FAIL] - Repeated sync is stable
github sync:       [PASS/FAIL] - GitHub sync works (or N/A if non-GitHub)
state stable:      [PASS/FAIL] - State file unchanged by redundant sync

OVERALL: [PASS/FAIL]
```
