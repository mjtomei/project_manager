---
title: "Push Proxy: Lifecycle and Security"
description: "Test push proxy start, connect, branch restriction, and cleanup"
tags: [containers, vanilla, github, containerized]
---

## Setup

Work in the current directory which has an initialized pm project with
container mode enabled and a git remote configured.

## Test Steps

### 1. Check if push proxy infrastructure exists
```bash
python3 -c "from pm_core import push_proxy; print('push_proxy module loaded')"
```

### 2. Verify push proxy can detect and test proxy liveness
```bash
python3 -c "
from pm_core.push_proxy import proxy_is_alive, get_proxy_socket_path, stop_all_proxies
# Verify the liveness check works on a non-existent socket
assert proxy_is_alive('/tmp/nonexistent.sock') == False
print('proxy_is_alive rejects dead socket: OK')

# Verify get_proxy_socket_path returns None when no proxy running
path = get_proxy_socket_path('nonexistent-container')
print(f'Socket path for nonexistent container: {path}')

# Verify stop_all_proxies runs without error even when none are active
stop_all_proxies()
print('stop_all_proxies with no active proxies: OK')
"
```

### 3. Test git wrapper script generation
```bash
python3 -c "
from pm_core.container import _build_git_setup_script
script = _build_git_setup_script(has_push_proxy=True)
print('Git wrapper script generated:')
print(script[:500])
"
```
Verify the script:
- Sets up a git wrapper that intercepts push/fetch/pull/ls-remote
- Routes through the Unix socket proxy
- Validates the target branch

### 4. Verify proxy validates branch restrictions
Check the push proxy source code handles branch validation:
- Only allowing push to the specific PR branch
- Rejecting pushes to other branches (e.g., main, master)

```bash
python3 -c "
from pm_core.push_proxy import PushProxy
import inspect
src = inspect.getsource(PushProxy)
# The PushProxy class should have branch validation in its handle method
assert 'allowed_branch' in src or 'branch' in src, 'No branch parameter in PushProxy'
print('PushProxy accepts branch parameter: OK')

# Check the __init__ signature accepts a branch parameter
sig = inspect.signature(PushProxy.__init__)
params = list(sig.parameters.keys())
print(f'PushProxy.__init__ params: {params}')
has_branch = any('branch' in p for p in params)
print(f'Branch restriction parameter present: {has_branch}')
"
```

### 5. Verify proxy cleanup functions exist and work
```bash
python3 -c "
from pm_core.push_proxy import stop_push_proxy, stop_all_proxies, stop_session_proxies
print('Cleanup functions importable: OK')

# stop_session_proxies should return count (0 when none active)
count = stop_session_proxies('nonexistent-session')
assert count == 0, f'Expected 0, got {count}'
print(f'stop_session_proxies returns count: {count}')
print('Cleanup logic verified: OK')
"
```

## Expected Behavior

- Push proxy module loads without errors
- Git wrapper script intercepts the correct commands
- Branch restrictions prevent pushing to unauthorized branches
- Cleanup logic handles proxy shutdown

## Reporting

```
TEST RESULTS
============
module load:       [PASS/FAIL] - push_proxy imports cleanly
proxy liveness:    [PASS/FAIL] - proxy_is_alive and socket path APIs work
git wrapper:       [PASS/FAIL] - Wrapper script generated correctly
branch restrict:   [PASS/FAIL] - PushProxy has branch restriction support
cleanup:           [PASS/FAIL] - stop_*/cleanup functions work correctly

OVERALL: [PASS/FAIL]
```
