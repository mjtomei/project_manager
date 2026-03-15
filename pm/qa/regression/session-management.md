---
title: "Session Management: Tmux Setup and Teardown"
description: "Test tmux session creation, naming, multi-window management, and pane layout"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. Verify session name computation
```bash
pm session name 2>&1
```
Record the session name — should follow `pm-<project>-<hash>` pattern.

### 2. Verify session tag computation
```bash
pm session tag 2>&1
```
Record the session tag.

### 3. Test session name determinism
```bash
python3 -c "
name1 = '$(pm session name 2>&1)'
name2 = '$(pm session name 2>&1)'
assert name1 == name2, f'Session names differ: {name1} vs {name2}'
print(f'Session name is deterministic: {name1}')
"
```

### 4. Verify tmux module infrastructure
```bash
python3 -c "
from pm_core import tmux as tmux_mod

# Core session management
assert hasattr(tmux_mod, 'session_exists'), 'Missing session_exists'
assert hasattr(tmux_mod, 'in_tmux'), 'Missing in_tmux'
assert hasattr(tmux_mod, 'get_session_name'), 'Missing get_session_name'
print('Session management functions: OK')

# Window management
assert hasattr(tmux_mod, 'new_window'), 'Missing new_window'
assert hasattr(tmux_mod, 'new_window_get_pane'), 'Missing new_window_get_pane'
print('Window management functions: OK')

# Pane management
assert hasattr(tmux_mod, 'capture_pane'), 'Missing capture_pane'
assert hasattr(tmux_mod, 'pane_exists'), 'Missing pane_exists'
print('Pane management functions: OK')
"
```

### 5. Test multi-window listing
```bash
python3 -c "
from pm_core import tmux as tmux_mod
import subprocess

# List windows in current session (if any)
if tmux_mod.in_tmux():
    session = tmux_mod.get_session_name()
    result = subprocess.run(['tmux', 'list-windows', '-t', session, '-F', '#{window_name}'],
                           capture_output=True, text=True)
    windows = result.stdout.strip().split('\n') if result.stdout.strip() else []
    print(f'Windows in session {session}: {len(windows)}')
    for w in windows[:10]:
        print(f'  {w}')
else:
    print('Not in tmux — skipping window listing')
print('Multi-window management: OK')
"
```

### 6. Verify pane layout functions
```bash
python3 -c "
from pm_core import tmux as tmux_mod
import inspect

# Check for layout/rebalance support
src = inspect.getsource(tmux_mod)
has_layout = 'layout' in src.lower() or 'rebalance' in src.lower() or 'select-layout' in src
print(f'Layout management support: {has_layout}')

# Check for split-pane support
has_split = 'split' in src.lower()
print(f'Pane splitting support: {has_split}')
"
```

### 7. Verify session kill safety
```bash
pm session kill --help 2>&1
```
Confirm it shows help without actually killing anything.

## Expected Behavior

- Session names are deterministic (same project = same name)
- Session names follow `pm-<project>-<hash>` convention
- Tmux module provides session, window, and pane management functions
- Multi-window listing works within a session
- Layout management and pane splitting are supported
- Session kill is a safe operation with help text

## Reporting

```
TEST RESULTS
============
session name:      [PASS/FAIL] - Name computed and follows convention
session tag:       [PASS/FAIL] - Tag computed
deterministic:     [PASS/FAIL] - Same project gives same name
tmux module:       [PASS/FAIL] - All management functions present
multi-window:      [PASS/FAIL] - Window listing works
pane layout:       [PASS/FAIL] - Layout/split functions present
session kill:      [PASS/FAIL] - Kill help works safely

OVERALL: [PASS/FAIL]
```
