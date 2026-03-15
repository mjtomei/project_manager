---
title: "Watcher: List Types and Status"
description: "Test watcher list, type registry, and basic status"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.

## Test Steps

### 1. List watcher types
```bash
pm watcher list
```
Verify it shows available watcher types (at minimum "auto-start").

### 2. Verify watcher registry
```bash
python3 -c "
from pm_core.watchers import list_watcher_types, get_watcher_class
types = list_watcher_types()
print(f'Registered watcher types: {types}')
for t in types:
    cls = get_watcher_class(t)
    print(f'  {t}: {cls.DISPLAY_NAME} (interval={cls.DEFAULT_INTERVAL}s)')
"
```
Verify each type has a display name and default interval.

### 3. Verify watcher state tracking
```bash
python3 -c "
from pm_core.watcher_manager import WatcherManager
from pm_core.watchers.auto_start_watcher import AutoStartWatcher
mgr = WatcherManager()
w = AutoStartWatcher(pm_root=None)
mgr.register(w)
state = mgr.get_state(w.watcher_id)
print(f'Watcher ID: {w.watcher_id}')
print(f'Type: {state.watcher_type}')
print(f'Running: {state.running}')
print(f'Iteration: {state.iteration}')
mgr.unregister(w.watcher_id)
print('Registered and unregistered successfully')
"
```

### 4. Verify watcher manager operations
```bash
python3 -c "
from pm_core.watcher_manager import WatcherManager
mgr = WatcherManager()
watchers = mgr.list_watchers()
print(f'Listed watchers: {len(watchers)}')
print(f'Any running: {mgr.is_any_running()}')
print(f'Any input required: {mgr.any_input_required()}')
"
```

## Expected Behavior

- `pm watcher list` shows all registered types
- Watcher classes have correct metadata
- WatcherManager can register/unregister watchers
- State tracking works for non-running watchers

## Reporting

```
TEST RESULTS
============
watcher list:      [PASS/FAIL] - Types listed correctly
registry:          [PASS/FAIL] - Classes have metadata
state tracking:    [PASS/FAIL] - Register/unregister works
manager ops:       [PASS/FAIL] - List/status operations work

OVERALL: [PASS/FAIL]
```
