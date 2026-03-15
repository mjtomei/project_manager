---
title: "TUI: Navigation, Keybindings, and Pane Management"
description: "Test TUI keybindings, pane management, tech tree rendering, and status updates"
tags: [core, local, vanilla, github, containerized, uncontainerized]
---

## Setup

Work in the current directory which has an initialized pm project.
A running pm TUI session is required for interactive tests (steps 4-6).

## Test Steps

### 1. Verify tui keys command
```bash
pm tui keys 2>&1
```
Confirm it lists keybindings including movement keys (j/k), action keys
(Enter, s, r, d, q), and any mode-specific bindings.

### 2. Verify TUI renderer exists
```bash
python3 -c "
from pm_core import tui
import inspect

# Check that the TUI module has core rendering functions
members = [m for m in dir(tui) if not m.startswith('_')]
print(f'TUI module exports: {len(members)}')
for m in sorted(members)[:20]:
    print(f'  {m}')
"
```

### 3. Test tech tree rendering
```bash
python3 -c "
from pm_core import store
from pm_core.cli.helpers import state_root

root = state_root()
data = store.load(root)
prs = data.get('prs', [])
print(f'PRs for tree rendering: {len(prs)}')

# Verify dependency data is available
for pr in prs[:5]:
    deps = pr.get('depends_on', [])
    print(f'  {pr[\"id\"]}: {len(deps)} deps')
print('Tech tree data: OK')
"
```

### 4. Verify tui view captures output
```bash
pm tui view 2>&1 | head -50
```
Should show the current TUI frame content, or an error if no session is running.

### 5. Verify tui send accepts keys
```bash
pm tui send --help 2>&1
```
Confirm it accepts KEYS argument and --session option.

### 6. Verify tui history tracking
```bash
pm tui history --frames 2 2>&1
```
Should show recent frames or indicate no history available.

### 7. Verify frame capture infrastructure
```bash
pm tui capture --help 2>&1
```
Confirm it accepts --frame-rate, --buffer-size, --session options.

### 8. Verify pane management
```bash
python3 -c "
from pm_core import tmux as tmux_mod
# Check pane management functions exist
assert hasattr(tmux_mod, 'new_window_get_pane'), 'Missing new_window_get_pane'
assert hasattr(tmux_mod, 'pane_exists'), 'Missing pane_exists'
assert hasattr(tmux_mod, 'capture_pane'), 'Missing capture_pane'
print('Pane management functions: OK')

# Check deduplication support
assert hasattr(tmux_mod, 'find_window_by_name') or hasattr(tmux_mod, 'list_windows'), \
    'Missing window lookup for dedup'
print('Window deduplication support: OK')
"
```

## Expected Behavior

- `pm tui keys` shows all available keybindings
- TUI renderer module is importable with rendering functions
- Tech tree can be built from PR dependency data
- `pm tui view` captures the current screen
- `pm tui send` relays keys to the TUI pane
- Frame history and capture are configurable
- Pane management supports creation, existence check, and deduplication

## Reporting

```
TEST RESULTS
============
tui keys:          [PASS/FAIL] - Keybindings listed
renderer:          [PASS/FAIL] - TUI module exports present
tech tree:         [PASS/FAIL] - Dependency graph builds correctly
tui view:          [PASS/FAIL] - Screen capture works
tui send:          [PASS/FAIL] - Key relay accepts input
tui history:       [PASS/FAIL] - Frame history accessible
frame capture:     [PASS/FAIL] - Capture configuration works
pane management:   [PASS/FAIL] - Create/check/dedup functions present

OVERALL: [PASS/FAIL]
```
