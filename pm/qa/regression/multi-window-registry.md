---
title: Multi-Window Registry
description: Test multi-window pane registry, review window isolation, and heal on restart
tags: [tui, local, vanilla, github, containerized, uncontainerized]
---
You are testing the multi-window pane registry. Your goal is to verify that
the registry correctly tracks panes across multiple tmux windows (main TUI
window and review windows) without corruption.

## Background

The pane registry (`~/.pm/pane-registry/<session>.json`) was recently changed
from a single-window flat format to a multi-window format. Previously, opening
a review window would overwrite the main window's registry entry, causing
reconciliation to delete all main-window panes. The new format stores panes
per-window:

```json
{
  "session": "pm-test",
  "windows": {
    "@30": {"panes": [...], "user_modified": false},
    "@38": {"panes": [...], "user_modified": false}
  },
  "generation": "12345"
}
```

Key behaviors to verify:
- Each window's panes are stored under their own window ID key
- Opening a review window registers panes under the review window's ID
- Closing panes in one window doesn't affect another window's registry
- Old single-window format is auto-migrated on load
- Empty windows are cleaned up after all panes die

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"` - List panes in current window
- `tmux list-panes -t <session> -a -F "#{window_id} #{pane_id} #{pane_width}x#{pane_height}"` - All panes across all windows
- `tmux list-windows -t <session> -F "#{window_id} #{window_name} #{window_panes}"` - List windows
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `python3 -c "import json; d=json.load(open('<path>')); print(json.dumps(d, indent=2))"` - Pretty-print registry
- `tmux display-message -p "#{session_name}"` - Get session name
- `tmux display-message -p "#{window_id}"` - Get current window ID

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Get base session name (strip ~N suffix if present)
4. Get current window ID: `tmux display-message -p "#{window_id}"`
5. Record initial registry state:
   - `cat ~/.pm/pane-registry/<base>.json`
   - Note the "windows" dict structure
   - Note which window IDs have panes registered
6. Record initial pane/window state:
   - `tmux list-windows -t <session> -F "#{window_id} #{window_name} #{window_panes}"`
   - `tmux list-panes -t <session> -a -F "#{window_id} #{pane_id}"`
7. SAVE ALL of this state for restoration at end

### Part 1: Verify New Format

1. Read the registry file and verify it uses the multi-window format:
   - Should have a "windows" dict (NOT a flat "panes" list)
   - The main window ID should be a key in "windows"
   - Each window entry should have "panes" and "user_modified"
   - "generation" should be at the top level
   - There should NOT be a top-level "window", "panes", or "user_modified" field

2. Verify the TUI pane is registered in the correct window:
   - The current window ID should be a key in the registry
   - That window's "panes" should contain an entry with role "tui"

### Part 2: Main Window Pane Registration

1. Launch a notes pane (if not already running):
   - `pm tui send n`
   - Wait 2 seconds

2. Check registry:
   - `cat ~/.pm/pane-registry/<base>.json`
   - The notes pane should be registered under the SAME window as the TUI
   - There should NOT be a new window entry for notes

3. Launch a guide pane (if not already running):
   - `pm tui send g`
   - Wait 2 seconds

4. Check registry again:
   - All panes (tui, notes, guide) should be under the same window ID
   - No spurious window entries should have appeared

### Part 3: Review Window Registration

This is the critical test. Review windows used to corrupt the registry.
We create a dummy PR to test this -- no real PRs are needed.

1. Create a dummy PR and prepare it for review:
   ```
   pm pr add "Registry review test" --description "Temp PR for registry testing"
   ```
   - Note the PR ID from the output (e.g. pr-001 or similar)
   - Create a temp workdir with a git repo:
     ```
     mkdir -p /tmp/pm-registry-test-workdir
     cd /tmp/pm-registry-test-workdir && git init && git commit --allow-empty -m "init"
     ```
   - Edit project.yaml to make the dummy PR "active" with a workdir.
     Find the project root first -- look for project.yaml under the pm state
     directory (often the git root of the main repo, NOT the workdir):
     ```
     python3 -c "
     import yaml, pathlib
     for d in [pathlib.Path.home() / '.pm', pathlib.Path('.')]:
         for p in d.rglob('project.yaml'):
             data = yaml.safe_load(p.read_text())
             for pr in data.get('prs', []):
                 if pr.get('title') == 'Registry review test':
                     pr['status'] = 'active'
                     pr['workdir'] = '/tmp/pm-registry-test-workdir'
                     p.write_text(yaml.dump(data, default_flow_style=False))
                     print(f'Updated {p}: PR {pr[\"id\"]} set to active')
                     break
             break
     "
     ```
   - Refresh TUI: `pm tui send r`, wait 2 seconds

2. Trigger the review window:
   - `pm pr review <dummy_pr_id>`
   - Wait 3 seconds for review window to open
   - Verify a new window appeared:
     `tmux list-windows -t <session> -F "#{window_id} #{window_name}"`

3. Check registry after review window opens:
   - `cat ~/.pm/pane-registry/<base>.json`
   - There should now be TWO window entries in "windows"
   - The main window should still have its panes (tui, notes, guide)
   - The review window should have its own panes (review-claude, review-diff)
   - Neither window's panes should reference panes from the other

4. Verify main window panes are NOT corrupted:
   - `tmux list-panes -t <session>:<main_window> -F "#{pane_id}"`
   - Each pane listed should match the registry entry for that window
   - The TUI should still be responsive: `pm tui view`

5. Close the review window:
   - `tmux kill-window -t <session>:<review_window_id>`
   - Wait 1 second

6. Check registry after review window close:
   - `cat ~/.pm/pane-registry/<base>.json`
   - The review window entry may still be in the registry (until reconciliation)
   - The main window entry should be completely unaffected
   - Run `pm rebalance` to trigger reconciliation
   - Check registry again -- review window entry should be gone or have empty panes

7. Clean up the dummy PR:
   - `pm pr close <dummy_pr_id> --keep-branch`
   - `rm -rf /tmp/pm-registry-test-workdir`
   - Refresh TUI: `pm tui send r`, wait 1 second

### Part 4: Per-Window user_modified Isolation

1. Verify user_modified is per-window:
   - Read registry: `cat ~/.pm/pane-registry/<base>.json`
   - The main window should have "user_modified": false
   - Manually split a pane to trigger user_modified:
     `tmux split-window -t <session>:<main_window> -h`
   - Wait 1 second
   - The after-split-window hook should fire handle_pane_opened
   - Read registry again
   - The main window's "user_modified" should now be true
   - If a review window exists, its "user_modified" should still be false

2. Reset user_modified:
   - `pm tui send b` (rebalance) to clear user_modified and rebalance
   - Read registry -- main window user_modified should be false again

### Part 5: Cross-Window Pane Cleanup

1. Ensure at least 2 panes exist in the main window
2. Kill one non-TUI pane (e.g., notes):
   - Find the pane ID from registry
   - `tmux kill-pane -t <pane_id>`
   - Wait 2 seconds for EXIT trap and reconciliation

3. Check registry:
   - The killed pane should be removed from the main window
   - Other panes in the main window should be unaffected
   - Any other windows in the registry should be unaffected

### Part 6: Heal -- Dead Pane and Window Removal

Test that TUI restart heals registry corruption.

1. Inject corruptions into the registry:
   - Load the JSON, add a fake pane to the current window:
     `{"id": "%9999", "role": "fake-dead", "order": 99, "cmd": "echo dead"}`
   - Also add a fake dead window entry:
     `"@9999": {"panes": [{"id": "%8888", "role": "fake", "order": 0, "cmd": "fake"}], "user_modified": false}`
   - Write the modified JSON back to the registry file
2. Verify corruptions in registry: `cat ~/.pm/pane-registry/<base>.json`
3. Restart TUI to trigger _heal_registry:
   - `pm tui send C-r` (Ctrl+R is restart; plain R is reload which won't heal)
   - Wait 3 seconds
4. Check registry: `cat ~/.pm/pane-registry/<base>.json`
   - Fake dead pane (%9999) should be GONE
   - Fake dead window (@9999) should be GONE
   - All real panes still registered
   - TUI pane still registered
5. Verify TUI: `pm tui view`

### Part 7: Heal -- Missing TUI Pane

1. Remove the TUI pane entry from the registry:
   - Load the JSON, remove the entry with role "tui" from current window's panes
   - Write modified JSON back
2. Verify TUI pane is missing from registry
3. Restart TUI: `pm tui send C-r`, wait 3 seconds
4. Check registry:
   - TUI pane re-registered in current window
   - Should have role "tui" and order 0
5. Verify TUI: `pm tui view`

### Part 8: Restore Original State

IMPORTANT: Always restore the original state!

1. Ensure the dummy PR from Part 3 was cleaned up:
   - Run `pm pr list` -- the "Registry review test" PR should be gone
   - If it still exists: `pm pr close <id> --keep-branch`
   - `rm -rf /tmp/pm-registry-test-workdir`
2. Kill any extra panes/windows created during testing
3. Relaunch panes that were present at the start:
   - If notes was running, press 'n'
   - If guide was running, press 'g'
4. Run `pm rebalance` to clean up layout
5. Verify final registry matches the initial window structure
6. `pm tui view` to verify TUI is responsive

## Expected Behavior

From pm_core/pane_layout.py:
- `load_registry()` auto-migrates old format (flat "panes") to new format ("windows" dict)
- `register_pane()` stores panes under `data["windows"][window]`
- `unregister_pane()` searches all windows for the pane ID
- `_reconcile_registry()` only reconciles the specified window; removes empty windows
- `get_window_data()` creates a new window entry if absent
- `_iter_all_panes()` yields panes from all windows

From pm_core/tui/pane_ops.py _heal_registry():
- Iterates all windows in data["windows"]
- For each window, queries tmux for live panes
- Removes dead panes and empty windows
- Ensures TUI pane registered in current window
- Saves only if changes made

From pm_core/cli/:
- `_launch_review_window()` registers panes under the review window's ID
- Session init creates `{"session":..., "windows":{}, "generation":...}`
- `_find_tui_pane()` searches across all windows

## Reporting

```
MULTI-WINDOW REGISTRY TEST RESULTS
====================================

## Part 1: New Format Verification
Registry uses "windows" dict: [PASS/FAIL]
TUI pane in correct window: [PASS/FAIL]
No stale top-level fields: [PASS/FAIL]

## Part 2: Main Window Registration
Notes registers in same window as TUI: [PASS/FAIL]
Guide registers in same window as TUI: [PASS/FAIL]
No spurious window entries: [PASS/FAIL]

## Part 3: Review Window (KEY TEST)
Dummy PR created and set to active: [PASS/FAIL]
Review window gets own registry entry: [PASS/FAIL]
Review panes registered (review-claude, review-diff): [PASS/FAIL]
Main window panes preserved: [PASS/FAIL]
Review window cleanup after kill: [PASS/FAIL]
Dummy PR cleaned up: [PASS/FAIL]

## Part 4: Per-Window user_modified
user_modified set only on affected window: [PASS/FAIL]
Rebalance clears user_modified: [PASS/FAIL]

## Part 5: Cross-Window Cleanup
Killed pane removed from correct window: [PASS/FAIL]
Other windows unaffected: [PASS/FAIL]

## Part 6: Heal -- Dead Removal
Fake dead pane removed: [PASS/FAIL]
Fake dead window removed: [PASS/FAIL]
Real panes preserved: [PASS/FAIL]

## Part 7: Heal -- Missing TUI
TUI pane re-registered: [PASS/FAIL]

## Part 8: Restore
Original state restored: [PASS/FAIL]
TUI responsive: [PASS/FAIL]

## Registry Snapshots
Initial:
<paste>

After review window open (Part 3):
<paste>

After heal (Part 6):
<paste>

## Issues Found
<list any bugs, unexpected behavior>

OVERALL: [PASS/FAIL]
```
