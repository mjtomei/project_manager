"""TUI regression tests executed by Claude.

These tests use Claude as the test executor, leveraging the pm tui commands
and tmux control to verify TUI behavior.
"""

PANE_LAYOUT_REFRESH_TEST = """\
You are testing the pm TUI pane layout refresh behavior. Your goal is to verify
that when panes are killed and relaunched, the layout is properly refreshed.

## Background

The pm TUI manages a tmux session with multiple panes (TUI, notes, guide, etc.).
When a pane is killed and relaunched, the layout should automatically rebalance.
There have been bugs where:
- Killing a pane leaves a gap or unbalanced layout
- Relaunching a pane from the TUI doesn't trigger rebalance
- The pane registry gets out of sync with actual tmux panes

## Available Tools

You have access to these commands:
- `pm tui view` - See current TUI state (also adds to legacy history)
- `pm tui send <keys>` - Send keystrokes to TUI (g=guide, n=notes, r=refresh, x=dismiss)
- `pm tui frames` - View automatically captured frames (captured on every UI change)
- `pm tui frames --all` - View all captured frames
- `pm tui capture --frame-rate N --buffer-size N` - Configure capture settings
- `pm tui clear-frames` - Clear captured frames
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"` - List panes with sizes
- `tmux kill-pane -t <pane_id>` - Kill a specific pane
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry

## Test Procedure

1. First, record the original state:
   - Run `pm tui clear-frames` to start with empty frame buffer
   - Run `pm tui view` to see the TUI
   - Run `tmux list-panes` to see all panes and their sizes
   - Check the pane registry - note the pane order (by "order" field)
   - SAVE THIS STATE - you must restore it at the end

2. Example scenarios, test as many as you think are useful:

   a) Kill guide pane via tmux, relaunch via TUI 'g' key:
      - Note current pane IDs and sizes
      - Find the guide pane ID from registry
      - Kill it with `tmux kill-pane -t <id>`
      - Wait 1 second, check layout
      - Press 'g' in TUI to relaunch guide
      - Verify layout rebalances (panes should have similar sizes)

   b) Kill notes pane, relaunch via TUI 'n' key:
      - Similar to above but for notes pane

   c) Kill a pane and check registry cleanup:
      - Kill a pane
      - Verify registry no longer contains that pane ID
      - Verify TUI still works (press 'r' to refresh)

3. For each scenario, verify:
   - Pane registry matches actual tmux panes
   - Layout is reasonably balanced (no tiny or huge panes)
   - TUI remains responsive
   - Check `pm tui frames` to see captured state changes during the test

4. RESTORE ORIGINAL STATE:
   - Kill and relaunch panes in the correct order to restore original pane order
   - For example, if you tested guide then notes, you need to:
     * Kill the notes pane you created
     * Kill the guide pane you created
     * Relaunch notes first (press 'n')
     * Relaunch guide second (press 'g')
   - This ensures the registry order matches the original
   - Verify final state matches original state

## Expected Behavior

From pm_core/pane_layout.py, the expected behavior is:
- When a pane exits, the EXIT trap calls `pm _pane-exited` which unregisters the pane
- The `rebalance()` function should be called to redistribute space
- The TUI's `_launch_pane()` method registers new panes and calls rebalance

## Reporting

After running your tests, report your findings in this format:

```
TEST RESULTS
============
Scenario A: [PASS/FAIL] - <brief description>
Scenario B: [PASS/FAIL] - <brief description>

Details:
<any issues found or notable observations>

OVERALL: [PASS/FAIL]
```

Use PASS if behavior matches expected, FAIL if there are bugs or unexpected behavior.
"""


CLUSTER_SESSION_RESUME_TEST = """\
You are testing the pm cluster explore session resume functionality. Your goal is
to verify that Claude sessions are properly saved and resumed when restarting
cluster explore.

## Background

The pm cluster explore command uses Claude's session management. When you:
1. Start cluster explore, a UUID is generated and saved to .pm-sessions.json
2. Exit and restart cluster explore, it should resume with --resume <session_id>
3. Using --fresh flag should start a fresh session

This test uses cluster explore instead of guide because:
- Guide advances through steps, making resume testing unreliable
- Cluster explore has a stable session key (cluster:explore) that doesn't change

## Available Tools

- `pm tui view` - See current TUI state
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `tmux split-window -t <session> -h -c <dir>` - Create a new pane
- `tmux send-keys -t <pane_id> <command> Enter` - Send command to pane
- `tmux capture-pane -t <pane_id> -p` - Capture pane content
- `tmux kill-pane -t <pane_id>` - Kill a pane
- `cat pm/.pm-sessions.json` - View session registry
- `ps aux | grep "claude.*resume\\|claude.*session-id"` - Check claude process flags

## Test Procedure

1. Check current state:
   - View pm/.pm-sessions.json to see saved sessions
   - Note if cluster:explore session already exists

2. Test session creation:
   - Create a new tmux pane for testing
   - Run `pm cluster explore --fresh` to start a fresh session
   - Wait for Claude to start (about 10 seconds)
   - Check .pm-sessions.json - should have new cluster:explore entry
   - Note the session_id
   - Send a memorable message to Claude, e.g.: "Remember this secret: PURPLE-TIGER-99"
   - Wait for Claude to acknowledge (should say something like "I'll remember...")

3. Test session resume:
   - Kill the pane with `tmux kill-pane -t <pane_id>`
   - Create a new pane
   - Run `pm cluster explore` (WITHOUT --fresh flag)
   - Check if --resume flag is being used: `ps aux | grep "claude.*resume"`
   - The process should show: `claude --resume <session_id>`
   - Wait for Claude to start
   - Ask "What is the secret I asked you to remember?"
   - Claude should respond with the secret phrase (e.g., "PURPLE-TIGER-99")

4. Verify conversation context:
   - The previous conversation should be visible in the pane
   - Claude should remember information from before the kill

## Expected Behavior

From pm_core/claude_launcher.py launch_claude():
- If session exists in registry, uses --resume <session_id>
- If no session, generates UUID and uses --session-id <uuid>
- Saves session_id to registry immediately

## Reporting

```
TEST RESULTS
============
Session creation: [PASS/FAIL]
  - Session ID saved to .pm-sessions.json: Y/N
  - Claude acknowledged secret phrase: Y/N

Session resume: [PASS/FAIL]
  - Process uses --resume flag: Y/N
  - Previous conversation visible: Y/N
  - Claude remembers secret phrase: Y/N

Details:
<findings, including session ID and any errors>

OVERALL: [PASS/FAIL]
```
"""


GUIDE_PROGRESS_WIDGET_TEST = """\
You are testing the GuideProgress widget in the pm TUI. Your goal is to verify
that the widget correctly displays step progress indicators as the user moves
through the guide workflow.

## Background

The TUI displays a GuideProgress widget during the setup steps (no_project through
ready_to_work). This widget shows:
- A list of numbered steps with descriptions
- Markers indicating status: checkmark for completed, arrow for current, circle for future
- The current step highlighted

The frame capture system automatically records TUI state on every change, so you
can verify the widget updated correctly by examining captured frames.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (g=guide, n=notes, r=refresh, x=dismiss)
- `pm tui frames` - View recently captured frames (shows last 5)
- `pm tui frames --all` - View all captured frames
- `pm tui frames -n 10` - View last 10 frames
- `pm tui clear-frames` - Clear captured frames (useful to start fresh)
- `pm tui capture --frame-rate 1` - Ensure all changes are captured

## Test Procedure

1. SETUP: Clear frames to start fresh
   - Run `pm tui clear-frames`
   - Run `pm tui view` to see initial state
   - Verify you see the GuideProgress widget (should show "Guide Workflow" header)

2. VERIFY INITIAL STATE:
   - The current step should have a right-pointing arrow marker (unicode U+25B6)
   - Previous steps should have checkmarks (U+2713)
   - Future steps should have empty circles (U+25CB)
   - Check `pm tui frames` to see the captured initial frame

3. TEST STEP TRANSITION (if possible):
   - If the guide is on step 1 (no_project), you can complete it by ensuring
     a pm directory with project.yaml exists
   - Press 'r' to refresh the TUI
   - Check frames to see if the widget updated:
     * Previous step should now show checkmark
     * New current step should show arrow
   - Run `pm tui frames -n 3` to compare before/after states

4. TEST DISMISS AND RESTORE:
   - Press 'x' to dismiss the guide view
   - Verify TUI switches to tech tree view
   - Press 'g' to launch guide pane
   - Verify guide progress widget is still visible (or explain if behavior differs)

5. VERIFY FRAME CAPTURE TRIGGERS:
   - Each state change should have triggered a frame capture
   - Run `pm tui frames --all` and check the "trigger" field in each frame
   - Expected triggers: "mount", "show_guide_view:*", "guide_step:*", etc.

## Expected Behavior

From pm_core/tui/guide_progress.py:
- INTERACTIVE_STEPS excludes terminal states (all_in_progress, all_done)
- MARKER_COMPLETED = checkmark, MARKER_CURRENT = arrow, MARKER_FUTURE = circle
- Widget updates via update_step() method which triggers refresh()

From pm_core/tui/app.py:
- GuideProgress widget is in #guide-progress-container
- Shown when state is in GUIDE_SETUP_STEPS and not dismissed
- Frame capture triggers on guide step changes via watcher

## Reporting

After running your tests, report your findings in this format:

```
TEST RESULTS
============
Initial display: [PASS/FAIL] - Widget shows correct markers
Step transition: [PASS/FAIL] - Markers update on step change (or N/A if couldn't test)
Dismiss/restore: [PASS/FAIL] - View switching works correctly
Frame capture: [PASS/FAIL] - Changes are captured with correct triggers

Details:
<observations about widget behavior, any issues found>

Frame Analysis:
<summary of captured frames and what they show>

OVERALL: [PASS/FAIL]
```
"""


TUI_RESTART_PANE_DEDUP_TEST = """\
You are testing that restarting the TUI does not create duplicate panes. Your goal
is to verify that when the TUI restarts (e.g., via 'R' key or crash recovery), it
reuses existing panes rather than launching new ones.

## Background

The TUI auto-launches certain panes (like guide) when conditions are met. There's a
bug where restarting the TUI while guide is running causes a SECOND guide pane to
be created, leaving the user with duplicate panes.

The fix should:
- Check if a pane for the task already exists before launching
- If it exists, switch focus to it instead of creating a new one
- Use the same task identification as session resume (pane registry role field)

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes (R=restart, g=guide, n=notes, x=dismiss)
- `pm tui frames` - View captured frames (automatically recorded on UI changes)
- `pm tui frames --all` - View all captured frames
- `pm tui clear-frames` - Clear frame buffer to start fresh
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_title}"` - List panes
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `tmux display-message -p "#{session_name}"` - Get current session name

## Test Procedure

### Scenario A: Restart TUI while guide is running

1. SETUP:
   - Run `pm tui clear-frames` to start with empty frame buffer
   - Run `pm tui view` to verify TUI is running
   - Get session name: `tmux display-message -p "#{session_name}"`
   - Check pane registry: `cat ~/.pm/pane-registry/<session>.json`
   - Count panes with role "guide" - should be 0 or 1
   - List all panes: `tmux list-panes -t <session> -F "#{pane_id}"`
   - Record initial pane count

2. LAUNCH GUIDE (if not running):
   - Press 'g' to launch guide pane
   - Wait 2 seconds for guide to start
   - Check registry again - should have exactly 1 guide pane
   - Record pane count (should be initial + 1 if guide wasn't running)

3. RESTART TUI:
   - Press 'R' to restart the TUI
   - Wait 2 seconds for TUI to restart
   - Check registry - should still have exactly 1 guide pane (NOT 2)
   - Count panes - should be same as before restart
   - If there are 2 guide panes, the test FAILS

4. VERIFY:
   - Run `pm tui view` - TUI should be responsive
   - The original guide pane should still be there
   - No duplicate guide panes should exist
   - Run `pm tui frames --all` to see state transitions during restart
   - Frame triggers should show "mount" after restart, content should be consistent

### Scenario B: Restart TUI after guide is done

1. SETUP (skip if guide is already done):
   - This scenario tests behavior when guide workflow is complete
   - If you can't complete the guide, note this as N/A

2. RESTART TUI:
   - Press 'R' to restart
   - Wait 2 seconds
   - Run `pm tui view`

3. VERIFY:
   - TUI should show normal tech tree view (not guide progress)
   - No new guide pane should be auto-launched
   - Check registry for guide panes - should be 0

### Scenario C: Manual guide launch deduplication

1. With guide already running (from Scenario A):
   - Press 'g' to try launching guide again
   - This should NOT create a second guide pane
   - Instead, it should focus the existing guide pane (or do nothing)

2. VERIFY:
   - Check registry - still exactly 1 guide pane
   - Pane count unchanged

## Expected Behavior

The TUI should:
1. Before launching a pane, check if one with that role already exists in registry
2. If it exists and the pane is still alive, focus it instead of creating new
3. Only create a new pane if none exists or the existing one is dead

## Reporting

```
TEST RESULTS
============
Scenario A (restart with guide): [PASS/FAIL] - <pane count before/after>
Scenario B (restart after done): [PASS/FAIL or N/A] - <description>
Scenario C (manual dedup): [PASS/FAIL] - <guide pane count>

Details:
<observations, pane counts, any duplicate panes found>

Registry states:
<before restart>
<after restart>

OVERALL: [PASS/FAIL]
```
"""


PANE_LAUNCH_DEDUP_TEST = """\
You are testing that the TUI pane launch commands don't create duplicate panes.
Your goal is to verify that pressing 'g' (guide), 'n' (notes), or other pane
launch keys when that pane is already open focuses the existing pane instead
of creating a new one.

## Background

The TUI has several keybindings that launch panes:
- 'g' - Launch guide pane
- 'n' - Launch notes pane

Previously, pressing these keys when the pane was already open would create
duplicate panes. The fix should detect existing panes and focus them instead.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames (automatically recorded on UI changes)
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer to start fresh
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `tmux display-message -p "#{session_name}"` - Get session name

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Record initial state:
   - `tmux list-panes -t <session> -F "#{pane_id}"` - count panes
   - `cat ~/.pm/pane-registry/<session>.json` - note registered panes

### Scenario A: Guide pane deduplication

1. If guide pane is NOT running:
   - Press 'g' to launch guide
   - Wait 2 seconds
   - Count panes - should be initial + 1
   - Check registry - should have 1 guide pane

2. With guide pane running:
   - Press 'g' again
   - Wait 1 second
   - Count panes - should be SAME as before (no new pane)
   - Check registry - should still have exactly 1 guide pane
   - The TUI log should say "Focused existing guide pane"

3. Press 'g' a third time:
   - Same verification - no new panes created

### Scenario B: Notes pane deduplication

1. If notes pane is NOT running:
   - Press 'n' to launch notes
   - Wait 1 second
   - Count panes and check registry

2. With notes pane running:
   - Press 'n' again
   - Wait 1 second
   - Count panes - should be SAME (no new pane)
   - Check registry - should still have exactly 1 notes pane

3. Press 'n' a third time:
   - Same verification

### Scenario C: Multiple rapid presses

1. With both guide and notes running, record pane count
2. Rapidly send multiple commands:
   - `pm tui send g`
   - `pm tui send n`
   - `pm tui send g`
   - `pm tui send n`
3. Wait 2 seconds
4. Count panes - should be SAME as before
5. Check registry - should still have exactly 1 of each role

### Scenario D: Focus switching

1. With guide and notes both running:
   - Note which pane is currently focused (use `tmux display-message -p "#{pane_id}"`)
   - Press 'g' - should focus guide pane
   - Check focused pane changed to guide
   - Press 'n' - should focus notes pane
   - Check focused pane changed to notes
   - Run `pm tui frames` to verify the TUI logged "Focused existing X pane" messages

### Scenario E: Command bar with status command

The TUI has a command bar (focused with '/') that can run pm commands.
Test that the command bar properly executes commands.

1. First, make sure TUI pane is focused (press Escape to unfocus command bar if needed)
2. Focus command bar: `pm tui send /`
3. Type status command: `pm tui send status`
4. Press Enter: `pm tui send Enter`
5. Wait 1 second
6. Check `pm tui view` - log line should show command output or status info
7. Pane count should be unchanged (status doesn't create panes)

### Scenario F: Command bar with sync command

Test another command bar command:

1. Focus TUI pane
2. `pm tui send /` to focus command bar
3. `pm tui send sync` to type sync command
4. `pm tui send Enter` to execute
5. Wait 2 seconds
6. Check `pm tui view` - should see sync result in log line
7. Pane count should be unchanged

### Scenario G: Command bar escape to cancel

Test that Escape cancels command input:

1. Focus command bar: `pm tui send /`
2. Type partial command: `pm tui send stat`
3. Press Escape: `pm tui send Escape`
4. Command bar should unfocus without executing
5. TUI should return to normal state

## Expected Behavior

From pm_core/tui/pane_ops.py launch_pane():
- Calls pane_registry.find_live_pane_by_role() to check for existing pane
- If found, calls tmux_mod.select_pane() to focus it
- Only creates new pane if no existing live pane found
- Logs "Focused existing {role} pane" when reusing

## Reporting

```
TEST RESULTS
============
Scenario A (guide dedup): [PASS/FAIL] - <pane counts: before/after 'g' presses>
Scenario B (notes dedup): [PASS/FAIL] - <pane counts: before/after 'n' presses>
Scenario C (rapid presses): [PASS/FAIL] - <pane count unchanged? Y/N>
Scenario D (focus switching): [PASS/FAIL] - <focus changed correctly? Y/N>
Scenario E (cmd bar status): [PASS/FAIL] - <status output visible? Y/N>
Scenario F (cmd bar sync): [PASS/FAIL] - <sync output visible? Y/N>
Scenario G (cmd bar escape): [PASS/FAIL] - <escape cancels input? Y/N>

Details:
<observations, any duplicate panes created, log messages seen>

Pane counts:
- Initial: <N>
- After guide launch: <N>
- After guide re-press: <N>
- After notes launch: <N>
- After notes re-press: <N>
- After rapid presses: <N>

Command bar tests:
- Command bar focused with '/': Y/N
- Status command output visible: Y/N
- Sync command output visible: Y/N
- Escape cancels without executing: Y/N

Frame analysis:
- Total frames captured: <N>
- Key triggers seen: <list of triggers from pm tui frames --all>
- "Focused existing" messages in log line: Y/N

OVERALL: [PASS/FAIL]
```
"""


PR_INTERACTION_TEST = """\
You are testing the PR interaction functionality in the pm TUI. Your goal is to verify
that users can navigate, select, and manage PRs through the tech tree interface.

## Background

The TUI displays PRs in a tech tree format. Users can:
- Navigate between PRs using arrow keys (Up/Down)
- Select a PR to see details (Enter)
- Start working on a PR ('s' key)
- Mark a PR as done ('d' key)
- Launch Claude with the PR prompt ('c' key)
- Edit the plan file ('e' key)

The tech tree shows PR status with visual indicators and dependency relationships.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames
- `pm tui clear-frames` - Clear frame buffer
- `cat pm/project.yaml` - View project config and PR list
- `pm pr list` - List all PRs with status

## Prerequisites

This test requires PRs to exist in the project. Check first:
1. Run `pm pr list` to see if PRs exist
2. If no PRs exist, note this and skip to the "No PRs" section

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start fresh
2. Run `pm pr list` to see available PRs
3. If in guide mode, press 'x' to dismiss and show the tech tree
4. Run `pm tui view` to see the tech tree

### Scenario A: PR Navigation

1. Starting position:
   - Run `pm tui view` and note which PR is currently selected (highlighted)
   - Note the total number of PRs visible

2. Navigate down:
   - `pm tui send Down`
   - Wait 1 second
   - `pm tui view` - selection should move to next PR
   - Check `pm tui frames` to see the state change

3. Navigate up:
   - `pm tui send Up`
   - Wait 1 second
   - `pm tui view` - selection should return to previous PR

4. Boundary testing:
   - Navigate to the first PR (multiple Up presses)
   - Press Up again - should stay at first PR (not wrap or error)
   - Navigate to last PR (multiple Down presses)
   - Press Down again - should stay at last PR

### Scenario B: PR Selection and Details

1. Select a PR:
   - Navigate to a PR
   - `pm tui send Enter` to activate/select it
   - `pm tui view` - detail panel should appear on the right
   - Note what information is shown in the detail panel

2. Detail panel contents (verify these are displayed):
   - PR ID
   - PR title/description
   - Status (pending/in_progress/done)
   - Dependencies (if any)
   - Branch name (if set)

3. Navigate while detail panel is open:
   - Press Up/Down to change selected PR
   - Detail panel should update to show new PR's info

### Scenario C: PR Status Changes

1. Start a PR:
   - Navigate to a PR with status "pending"
   - `pm tui send s` to start it
   - `pm tui view` - status should change to "in_progress"
   - Check the log line for confirmation message

2. Complete a PR:
   - With an "in_progress" PR selected
   - `pm tui send d` to mark done
   - `pm tui view` - status should change to "done"
   - Check the log line for confirmation

3. Dependency enforcement:
   - If a PR has unmet dependencies, starting it may warn or fail
   - Note any dependency-related behavior

### Scenario D: PR Actions

1. Launch Claude ('c'):
   - Select a PR
   - `pm tui send c`
   - This should open a new pane with Claude
   - Check `tmux list-panes` for new pane
   - Note: This may fail if not in tmux or Claude not installed

2. Edit plan ('e'):
   - Select a PR that has an associated plan
   - `pm tui send e`
   - Should open editor in a new pane
   - Check `tmux list-panes` for editor pane

### Scenario E: Command Bar PR Commands

1. Focus command bar:
   - `pm tui send /`
   - Command bar should be focused

2. Run pr list command:
   - `pm tui send "pr list"`
   - `pm tui send Enter`
   - Check log line for output

3. Run pr start via command bar:
   - `pm tui send /`
   - `pm tui send "pr start <pr-id>"` (use actual PR ID)
   - `pm tui send Enter`
   - Verify PR status changes

### No PRs Section

If no PRs exist in the project:
1. Verify the TUI shows an appropriate message ("No PRs defined" or similar)
2. Verify navigation keys don't cause errors
3. Verify PR action keys (s, d, p) handle the empty state gracefully
4. Note what the empty state looks like

## Expected Behavior

From pm_core/tui/app.py:
- TechTree widget handles PR display and navigation
- PRSelected message sent when PR is highlighted
- PRActivated message sent when PR is activated (Enter)
- action_start_pr() runs `pm pr start <id>`
- action_done_pr() runs `pm pr done <id>`
- action_launch_claude() opens Claude in new pane

## Reporting

```
PR INTERACTION TEST RESULTS
===========================

PRs Present: [Yes/No] - <count>
Guide Mode Dismissed: [Yes/No/N/A]

## Scenario A: Navigation
- Initial selection visible: [Yes/No]
- Down navigation works: [PASS/FAIL]
- Up navigation works: [PASS/FAIL]
- Boundary behavior correct: [PASS/FAIL]

## Scenario B: Selection/Details
- Enter shows detail panel: [PASS/FAIL]
- Detail panel shows PR info: [PASS/FAIL]
- Details update on navigation: [PASS/FAIL]

## Scenario C: Status Changes
- Start PR ('s'): [PASS/FAIL/SKIPPED] - <notes>
- Done PR ('d'): [PASS/FAIL/SKIPPED] - <notes>
- Dependency handling: <observations>

## Scenario D: Actions
- Launch Claude ('c'): [PASS/FAIL/SKIPPED] - <notes>
- Edit plan ('e'): [PASS/FAIL/SKIPPED] - <notes>

## Scenario E: Command Bar
- Command bar focus: [PASS/FAIL]
- pr list command: [PASS/FAIL]
- pr start command: [PASS/FAIL/SKIPPED]

## Frame Analysis
- Total frames captured: <N>
- Key state transitions observed: <list>

## Issues Found
<list any bugs, unexpected behavior, or UI issues>

## Notes
<any additional observations about PR interaction>

OVERALL: [PASS/FAIL]
```
"""


TECH_TREE_VISUAL_REVIEW_TEST = """\
You are reviewing the visual appearance of the pm TUI's tech tree (PR dependency graph).
Your goal is to identify any visual issues and suggest improvements to make the TUI
look better and be more usable.

## Background

The TUI displays a "tech tree" showing PRs and their dependencies. Each PR is shown
as a box with its ID, title, and status. Dependencies are shown with connecting lines.
There have been reports of:
- Boxes overlapping or clipping into each other
- Alignment issues with dependency lines
- Text truncation problems
- General visual polish issues

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes (arrow keys to navigate, Enter to select)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames
- `pm tui clear-frames` - Clear frame buffer

## Test Procedure

### Part 1: Initial Visual Assessment

1. Run `pm tui clear-frames` to start fresh
2. Run `pm tui view` to capture the current TUI state
3. Carefully examine the output and note:
   - Are there any PRs displayed? If not, note "No PRs to display"
   - If PRs are displayed, check for visual issues:
     * Do any boxes overlap or clip into each other?
     * Are the box borders complete and properly drawn?
     * Is text properly contained within boxes?
     * Are dependency lines (if any) properly aligned?
     * Is the spacing between elements consistent?
     * Is the overall layout balanced?

### Part 2: Navigation Testing (if PRs exist)

1. Try navigating with arrow keys:
   - `pm tui send Up` and `pm tui send Down` to move selection
   - After each, run `pm tui view` to see the updated state
2. Check if:
   - Selection highlighting is visible and clear
   - The display updates smoothly without visual artifacts
   - Selected item is clearly distinguishable from others

### Part 3: Different Terminal Widths (optional)

If you can resize or have info about terminal width:
1. Note the current width from the captured frame
2. Consider how the layout might look at different widths
3. Note any elements that might break at narrower widths

### Part 4: Aesthetic Review

Look at the TUI with a critical eye for design:
1. Color choices - are they readable and pleasant?
2. Use of Unicode characters - appropriate and rendering correctly?
3. Information density - too cluttered or too sparse?
4. Visual hierarchy - is it clear what's important?
5. Consistency - do similar elements look similar?

## What To Look For

Common visual issues in terminal UIs:
- Box-drawing characters not connecting properly (gaps or overlaps)
- ANSI color codes not being interpreted (showing as escape sequences)
- Unicode characters showing as boxes or question marks
- Text extending beyond its container
- Misaligned columns or rows
- Inconsistent padding or margins
- Hard-to-read color combinations (e.g., dark text on dark background)

## Reporting

Provide a detailed visual review:

```
TECH TREE VISUAL REVIEW
=======================

PRs Present: [Yes/No] - <count if yes>

## Visual Issues Found

### Critical (breaks usability)
<list any critical issues, or "None found">

### Moderate (noticeable but usable)
<list any moderate issues, or "None found">

### Minor (polish issues)
<list any minor issues, or "None found">

## Current Appearance

<Describe what you see - the overall layout, how PRs are displayed,
 what the tree structure looks like>

## Suggestions for Improvement

### High Priority
<suggestions that would significantly improve the experience>

### Nice to Have
<suggestions for visual polish>

## Screenshots/Frames

Key frames from `pm tui frames --all`:
<Note the frame numbers and what they show>

## Overall Assessment

Visual Quality: [Poor/Fair/Good/Excellent]
Usability: [Poor/Fair/Good/Excellent]

Summary:
<2-3 sentence summary of the TUI's visual state and top recommendations>
```

Be specific and constructive in your feedback. If you see overlapping boxes or other
issues, describe exactly where they occur and what they look like.
"""


HELP_SCREEN_AND_KEYBINDINGS_TEST = """\
You are testing the pm TUI help screen and verifying that every keybinding
documented in the help screen actually works. Your goal is to open the help
screen with '?', verify its contents, then systematically test each key.

## Background

The TUI has a help modal (HelpScreen) that opens when the user presses '?'.
It lists all available keybindings grouped by category:
- Tree Navigation: arrow keys, hjkl, Enter
- PR Actions: s, d, c, p, e, v
- Panes & Views: /, g, n, m, L, b
- Other: r, Ctrl+R, ?, q

Each key should produce a visible response - either a state change, a log
message, a new pane, or a modal. Keys that would be destructive (s=start PR,
d=done PR, q=quit) should be tested carefully to avoid changing project state.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `tmux display-message -p "#{session_name}"` - Get session name

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Run `pm tui view` to verify TUI is running and on the tech tree view
3. If in guide mode, press 'g' to dismiss and show the tech tree
4. Get session name: `tmux display-message -p "#{session_name}"`
5. Record initial pane count: `tmux list-panes -t <session> -F "#{pane_id}"`

### Part 1: Help Screen Content

1. Open help screen:
   - `pm tui send ?`
   - Wait 1 second
   - `pm tui view` to capture the help screen

2. Verify help screen contains ALL these keybindings:
   - Tree Navigation section:
     * Arrow keys / hjkl - Move selection
     * Enter - Show PR details
   - PR Actions section:
     * s - Start selected PR
     * z - Modifier: kill existing before next command
     * d - Mark PR as done
     * c - Launch Claude for PR
     * e - Edit selected PR
     * v - View plan file
   - Panes & Views section:
     * / - Open command bar
     * g - Toggle guide view
     * n - Open notes
     * m - Meta: work on pm itself
     * L - View TUI log
     * b - Rebalance panes
   - Other section:
     * r - Refresh / sync with GitHub
     * Ctrl+R - Restart TUI
     * ? - Show this help
     * q - Detach from session

3. Close help screen:
   - `pm tui send Escape`
   - `pm tui view` to verify help is dismissed

### Part 2: Safe Keybinding Tests

Test each key that is safe to press (won't change PR state or quit):

1. **Navigation keys** (test with frames):
   - `pm tui send Down` → selection should move down
   - `pm tui view` → verify selection changed
   - `pm tui send Up` → selection should move back
   - `pm tui send Right` → move to next column (if deps exist)
   - `pm tui send Left` → move back
   - `pm tui send j` → same as Down
   - `pm tui send k` → same as Up
   - `pm tui send l` → same as Right
   - `pm tui send h` → same as Left

2. **Enter** (show detail panel):
   - `pm tui send Enter`
   - `pm tui view` → detail panel should appear on right side
   - Verify it shows PR info (ID, title, status, plan context)

3. **v** (view plan):
   - `pm tui send v`
   - Wait 1 second
   - Check if a new pane opened with the plan file
   - `tmux list-panes` to verify pane count increased
   - Check pane registry for role "plan"

4. **/** (command bar):
   - `pm tui send /`
   - `pm tui view` → command bar should be focused
   - `pm tui send Escape` → should unfocus command bar

5. **g** (toggle guide):
   - `pm tui send g`
   - Wait 1 second
   - `pm tui view` → should either show guide view or launch guide pane
   - If guide pane launched, verify via `tmux list-panes`
   - Press 'g' again if needed to return to tech tree

6. **n** (notes):
   - `pm tui send n`
   - Wait 1 second
   - `tmux list-panes` → should see a new notes pane
   - Check registry for role "notes"

7. **L** (view log):
   - `pm tui send L`
   - Wait 1 second
   - `tmux list-panes` → should see a new log pane
   - Check registry for role "log"

8. **r** (refresh):
   - `pm tui send r`
   - `pm tui view` → log line should show "Refreshing..." or sync result

9. **b** (rebalance):
   - `pm tui send b`
   - `pm tui view` → log line should show "Layout rebalanced"

10. **?** (help - test open/close cycle):
    - `pm tui send ?`
    - `pm tui view` → help screen should appear
    - `pm tui send ?` → pressing again should close it
    - `pm tui view` → verify back to normal view

11. **e** (edit PR):
    - `pm tui send e`
    - Wait 1 second
    - `tmux list-panes` → should see editor pane
    - Note: editor may open and close quickly if EDITOR is not set

### Part 3: Destructive Keys (observe only)

Do NOT press these, just verify they exist in help:
- **s** - Would start a PR (changes project state)
- **d** - Would mark PR as done (changes project state)
- **c** - Would launch Claude (resource-intensive)
- **m** - Would launch meta session
- **q** - Would detach from tmux (ends test)
- **Ctrl+R** - Would restart TUI (disrupts test)

### Part 4: Cleanup

1. Kill any panes that were created during testing (notes, log, plan, etc.)
   - Use pane registry to find pane IDs
   - `tmux kill-pane -t <pane_id>` for each
2. Verify TUI is still responsive: `pm tui view`
3. Final pane count should match initial count

## Expected Behavior

- Help screen should be a modal overlay that lists ALL keybindings
- Each key should produce a visible effect (log message, pane, or state change)
- Keys should not error or crash when pressed with no PR selected
- Help screen should open/close cleanly with '?' or Escape

## Reporting

```
HELP SCREEN & KEYBINDINGS TEST
===============================

## Part 1: Help Screen Content
Help screen opens: [PASS/FAIL]
All keybindings documented: [PASS/FAIL]
  Missing keys (if any): <list>
  Extra/unexpected keys (if any): <list>
Help screen closes: [PASS/FAIL]

## Part 2: Keybinding Tests

Navigation:
  Down/j: [PASS/FAIL]
  Up/k: [PASS/FAIL]
  Right/l: [PASS/FAIL]
  Left/h: [PASS/FAIL]

PR Actions:
  Enter (detail panel): [PASS/FAIL] - <what detail panel shows>
  v (view plan): [PASS/FAIL] - <pane created? role correct?>
  e (edit PR): [PASS/FAIL] - <pane created?>

Panes & Views:
  / (command bar): [PASS/FAIL] - <focuses/unfocuses correctly?>
  g (guide): [PASS/FAIL] - <behavior observed>
  n (notes): [PASS/FAIL] - <pane created? role correct?>
  L (log): [PASS/FAIL] - <pane created? role correct?>
  r (refresh): [PASS/FAIL] - <log message>
  b (rebalance): [PASS/FAIL] - <log message>

Other:
  ? (help toggle): [PASS/FAIL] - <opens and closes cleanly?>

## Part 3: Destructive Keys
All documented in help: [PASS/FAIL]
  s (start PR): [PRESENT/MISSING]
  z (kill existing modifier): [PRESENT/MISSING]
  d (done PR): [PRESENT/MISSING]
  c (claude): [PRESENT/MISSING]
  m (meta): [PRESENT/MISSING]
  q (quit): [PRESENT/MISSING]
  Ctrl+R (restart): [PRESENT/MISSING]

## Part 4: Cleanup
Panes cleaned up: [PASS/FAIL]
TUI responsive after tests: [PASS/FAIL]

## Issues Found
<list any keybindings that don't work, produce errors, or behave unexpectedly>

## Frame Analysis
Total frames captured: <N>
Key state changes observed: <summary>

OVERALL: [PASS/FAIL]
```
"""


PLANS_PANE_TEST = """\
You are testing the Plans Pane feature in the pm TUI. Your goal is to verify
that pressing Shift+P toggles a plans view, that navigation works, and that
plan action shortcuts function correctly.

## Background

The TUI has a plans view (toggled with Shift+P) that replaces the tech tree
with a scrollable list of plans. Each plan shows its ID, name, status, PR count,
and intro text from the plan markdown file. The plans pane has its own keybindings
for plan operations (view, edit, add, review, deps, load).

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `tmux display-message -p "#{session_name}"` - Get session name

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Run `pm tui view` to verify TUI is running and showing the tech tree
3. If in guide mode, press 'g' to dismiss and show the tech tree
4. Get session name: `tmux display-message -p "#{session_name}"`
5. Record initial pane count: `tmux list-panes -t <session> -F "#{pane_id}"`

### Part 1: Toggle Plans View

1. Enter plans view:
   - `pm tui send P` (Shift+P)
   - Wait 1 second
   - `pm tui view` - should show plans list instead of tech tree
   - Verify you can see:
     * "Plans" header
     * Plan names (e.g., "Import from existing repo", "Multi-candidate test-driven code generation")
     * Plan status (e.g., "[draft]")
     * PR counts for each plan
     * Intro text from the plan files
     * Shortcut hints at the bottom (view, edit, add, review, deps, load, back)

2. Return to tree view:
   - `pm tui send P` (Shift+P again)
   - Wait 1 second
   - `pm tui view` - should show tech tree again with PRs
   - Verify plans view is gone

### Part 2: Navigation

1. Enter plans view again:
   - `pm tui send P`
   - Wait 1 second

2. Navigate between plans:
   - `pm tui view` - note which plan is selected (marked with arrow)
   - `pm tui send Down` - selection should move to next plan
   - `pm tui view` - verify selection changed
   - `pm tui send Up` - selection should move back
   - `pm tui view` - verify selection returned
   - Test j/k navigation:
     * `pm tui send j` - same as Down
     * `pm tui send k` - same as Up

3. Boundary testing:
   - Navigate to first plan (press Up/k multiple times)
   - Press Up again - should stay at first plan
   - Navigate to last plan (press Down/j multiple times)
   - Press Down again - should stay at last plan

### Part 3: Plan Actions

1. View plan file (Enter):
   - Select a plan
   - `pm tui send Enter`
   - Wait 1 second
   - `tmux list-panes` - should see a new pane (role "plan")
   - Check pane registry for role "plan"
   - Kill the plan pane after verifying

2. View plan file (v):
   - `pm tui send v`
   - Wait 1 second
   - `tmux list-panes` - should see a new plan pane
   - Kill the plan pane after verifying

3. Edit plan (e):
   - `pm tui send e`
   - Wait 1 second
   - `tmux list-panes` - should see editor pane (role "plan-edit")
   - Kill the editor pane after verifying

4. Add plan (a):
   - `pm tui send a`
   - `pm tui view` - command bar should be focused with "plan add " pre-filled
   - `pm tui send Escape` - cancel the command

5. Breakdown plan (w):
   - `pm tui send w`
   - Wait 2 seconds
   - `tmux list-panes` - should see a breakdown pane (role "plan-breakdown")
   - Kill the breakdown pane after verifying

6. Plan deps (D):
   - `pm tui send D`
   - Wait 2 seconds
   - `tmux list-panes` - should see a deps pane (role "plan-deps")
   - Kill the deps pane after verifying

### Part 4: Refresh Persistence

1. While in plans view:
   - `pm tui send r` to refresh
   - Wait 2 seconds
   - `pm tui view` - should STILL be in plans view (not tree)
   - Verify plan data is still displayed correctly

### Part 5: View Switching

1. From plans view, press P to return to tree:
   - `pm tui send P`
   - `pm tui view` - verify tree is shown

2. Press P to return to plans:
   - `pm tui send P`
   - `pm tui view` - verify plans shown again

3. From plans view, verify that PR action keys (s, d, p) are blocked:
   - These should not trigger PR actions since we're in plans view
   - Note: They may be consumed by the PlansPane's on_key handler
   - Check `pm tui view` log line for any unexpected messages

### Part 6: Help Screen

1. Return to tree view first:
   - `pm tui send P` (if in plans view)

2. Open help screen:
   - `pm tui send ?`
   - `pm tui view` - verify help screen shows
   - Verify "P" is listed under "Panes & Views" as "Toggle plans view"
   - `pm tui send Escape` to close help

### Part 7: Cleanup

1. Kill any panes created during testing
2. Return to tree view with P if in plans view
3. Verify TUI is responsive: `pm tui view`
4. Final pane count should match initial count

## Expected Behavior

- Shift+P toggles between plans view and tree view
- Plans view shows all plans with names, status, PR counts, and intro text
- Navigation keys (Up/Down, j/k) move selection between plans
- Enter and v open the plan file in a pane
- e opens the plan file in an editor
- a pre-fills the command bar with "plan add "
- w launches pm plan breakdown in a pane
- D launches pm plan deps in a pane
- l launches pm plan load in a pane
- Refresh (r) stays in plans view
- PR actions are blocked while in plans view

## Reporting

```
PLANS PANE TEST RESULTS
=======================

## Part 1: Toggle Plans View
Plans view opens: [PASS/FAIL]
  Plans visible: <list plan names seen>
  Status shown: [Yes/No]
  PR counts shown: [Yes/No]
  Intro text shown: [Yes/No]
  Shortcuts shown: [Yes/No]
Plans view closes: [PASS/FAIL]
  Tree restored: [Yes/No]

## Part 2: Navigation
Down/j navigation: [PASS/FAIL]
Up/k navigation: [PASS/FAIL]
Boundary behavior: [PASS/FAIL]

## Part 3: Plan Actions
Enter (view plan): [PASS/FAIL] - <pane created? role correct?>
v (view plan): [PASS/FAIL] - <pane created? role correct?>
e (edit plan): [PASS/FAIL] - <pane created? role correct?>
a (add plan): [PASS/FAIL] - <command bar pre-filled?>
w (review plan): [PASS/FAIL] - <pane created? role correct?>
D (plan deps): [PASS/FAIL] - <pane created? role correct?>

## Part 4: Refresh Persistence
Stays in plans view after refresh: [PASS/FAIL]
Data still displayed: [PASS/FAIL]

## Part 5: View Switching
Toggle back to tree: [PASS/FAIL]
Toggle back to plans: [PASS/FAIL]
PR actions blocked in plans view: [PASS/FAIL]

## Part 6: Help Screen
P listed in help: [PASS/FAIL]

## Part 7: Cleanup
Panes cleaned up: [PASS/FAIL]
TUI responsive: [PASS/FAIL]

## Issues Found
<list any bugs, unexpected behavior, or UI issues>

## Frame Analysis
Total frames captured: <N>
Key state changes: <summary>

OVERALL: [PASS/FAIL]
```
"""


MOBILE_MODE_TEST = """\
You are testing the mobile mode feature for the pm TUI. Mobile mode auto-zooms
the active pane when the terminal is narrow (< 120 columns) or when force-enabled,
making the tool usable on mobile devices and narrow SSH sessions.

## Background

The pm tool manages tmux sessions with multiple side-by-side panes. On small
terminals these panes become unusable. Mobile mode solves this by:
- Auto-detecting narrow terminals (< 120 cols)
- Supporting a force-mobile flag (`pm session mobile --force`)
- Auto-zooming the active pane on every pane switch
- Zooming the TUI on session start when mobile

Key implementation details:
- `pm _pane-switch <session> <direction>` — internal command that unzooms,
  switches pane, then re-zooms if mobile
- `pm session mobile` — show/toggle mobile mode status
- tmux prefix keys (o, Up, Down, Left, Right) are overridden to use `_pane-switch`
- Force flag stored at `~/.pm/pane-registry/<session>.mobile`
- TUI's `_launch_pane` uses `select_pane_smart` which zooms in mobile mode

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"` - List panes
- `tmux display -t <session> -p "#{window_width} #{window_zoomed_flag}"` - Window info
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `ls ~/.pm/pane-registry/<session>.mobile` - Check force-mobile flag
- `tmux display-message -p "#{session_name}"` - Get session name

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Record initial state:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"` - pane sizes
   - `tmux display -t <session> -p "#{window_width} #{window_zoomed_flag}"` - width and zoom
   - `ls ~/.pm/pane-registry/<session>.mobile 2>&1` - force flag status
4. Run `pm session mobile` to see current mobile status

### Part 1: Mobile Status Command

1. Run `pm session mobile` and verify output shows:
   - Session name
   - Mobile active: True/False
   - Force flag: True/False
   - Window width and threshold (120)

### Part 2: Force Mobile On

1. Enable force mobile:
   - `pm session mobile --force`
   - Verify output says "force-enabled"
   - `ls ~/.pm/pane-registry/<session>.mobile` - file should exist

2. Verify mobile status:
   - `pm session mobile` - should show "Mobile active: True", "Force flag: True"

3. Check zoom state on ALL windows:
   - List all windows: `tmux list-windows -t <session> -F "#{window_index} #{window_name}"`
   - For EACH window that has multiple panes, verify it is zoomed:
     `tmux display -t <session>:<window_index> -p "#{window_zoomed_flag}"` - should be "1"
   - Windows with only one pane can't be zoomed (that's expected)
   - The active pane in each multi-pane window should be the zoomed one

### Part 3: Pane Switching in Mobile Mode

1. Test prefix-o (next pane) via _pane-switch:
   - Record current active pane: `tmux display -t <session> -p "#{pane_id}"`
   - Run `pm _pane-switch <session> next`
   - Check active pane changed: `tmux display -t <session> -p "#{pane_id}"`
   - Check still zoomed: `tmux display -t <session> -p "#{window_zoomed_flag}"` → "1"

2. Test directional switching:
   - First unzoom to see all panes: `tmux resize-pane -t <session> -Z`
   - Record pane positions: `tmux list-panes -t <session> -F "#{pane_id} #{pane_left} #{pane_top}"`
   - Re-zoom: `tmux resize-pane -t <session> -Z`
   - Run `pm _pane-switch <session> -R` (move right)
   - Verify zoom is still on: `tmux display -t <session> -p "#{window_zoomed_flag}"` → "1"
   - Run `pm _pane-switch <session> -L` (move left)
   - Verify zoom is still on

3. Cycle through all panes:
   - Run `pm _pane-switch <session> next` several times
   - After each, verify zoom flag is "1"
   - After cycling back to start, verify we're on the original pane

### Part 4: TUI Pane Launch in Mobile Mode

1. With force-mobile still on:
   - `pm tui send n` to launch/focus notes pane
   - Wait 1 second
   - Check zoom: `tmux display -t <session> -p "#{window_zoomed_flag}"` → "1"
   - The notes pane should be zoomed (fully visible)

2. Focus back to TUI:
   - `pm _pane-switch <session> next` (or use direction to find TUI)
   - Check zoom still on
   - `pm tui view` - TUI should be visible and responsive

### Part 5: Rebalance in Mobile Mode

1. Run `pm tui send b` to trigger rebalance from TUI
   - Or run `pm rebalance` directly
   - After rebalance, active pane should still be zoomed
   - `tmux display -t <session> -p "#{window_zoomed_flag}"` → "1"

### Part 6: Force Mobile Off

1. Disable force mobile:
   - `pm session mobile --no-force`
   - Verify output says "force-disabled"
   - `ls ~/.pm/pane-registry/<session>.mobile 2>&1` - file should NOT exist

2. Check status:
   - `pm session mobile` - Force flag should be False
   - Mobile active depends on actual window width

3. Verify ALL windows are unzoomed:
   - List all windows: `tmux list-windows -t <session> -F "#{window_index} #{window_name}"`
   - For EACH window, verify it is NOT zoomed:
     `tmux display -t <session>:<window_index> -p "#{window_zoomed_flag}"` - should be "0"
   - All panes in multi-pane windows should be visible side-by-side

4. If window is narrow (< 120):
   - Mobile active should still be True (auto-detected)
   - Zoom behavior continues

### Part 7: Cleanup Verification

1. Verify that `pm session kill` would clean up the flag:
   - DON'T actually kill the session
   - Just verify the code path exists by checking:
     `ls ~/.pm/pane-registry/<session>.mobile 2>&1` - should not exist (we disabled it)

2. Restore original state:
   - If mobile was off at the start and is now off, nothing to do
   - Run `pm rebalance` to ensure clean layout
   - Verify all panes are visible: `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"`

## Expected Behavior

- `pm session mobile` shows status without changing anything
- `pm session mobile --force` enables force-mobile, triggers rebalance, zooms active pane on ALL windows
- `pm session mobile --no-force` disables force-mobile, unzooms ALL windows, triggers rebalance
- `pm _pane-switch` unzooms → switches pane → re-zooms (in mobile mode)
- `pm _pane-switch` just switches pane (in desktop mode, no zoom)
- TUI `_launch_pane` auto-zooms new/existing panes via `select_pane_smart`
- `rebalance()` zooms active pane after layout when mobile
- Force flag is at `~/.pm/pane-registry/<session>.mobile`
- Threshold is 120 columns

## Reporting

```
MOBILE MODE TEST RESULTS
========================

## Part 1: Status Command
pm session mobile output correct: [PASS/FAIL]
  Shows session name: [Yes/No]
  Shows mobile active: [Yes/No]
  Shows force flag: [Yes/No]
  Shows width and threshold: [Yes/No]

## Part 2: Force Mobile On
--force enables flag file: [PASS/FAIL]
Status shows force-enabled: [PASS/FAIL]
All multi-pane windows zoomed: [PASS/FAIL]

## Part 3: Pane Switching
_pane-switch next: [PASS/FAIL] - <pane changed? still zoomed?>
_pane-switch -R: [PASS/FAIL] - <still zoomed?>
_pane-switch -L: [PASS/FAIL] - <still zoomed?>
Full cycle returns to start: [PASS/FAIL]

## Part 4: TUI Pane Launch
Notes pane auto-zoomed: [PASS/FAIL]
Switch back to TUI works: [PASS/FAIL]

## Part 5: Rebalance
Rebalance preserves zoom: [PASS/FAIL]

## Part 6: Force Mobile Off
--no-force removes flag: [PASS/FAIL]
Status shows force-disabled: [PASS/FAIL]
All windows unzoomed: [PASS/FAIL]

## Part 7: Cleanup
Original state restored: [PASS/FAIL]

## Issues Found
<list any bugs, unexpected behavior>

## Notes
Window width during test: <N> columns
Threshold: 120 columns
Auto-mobile triggered: [Yes/No]

OVERALL: [PASS/FAIL]
```
"""


COMMAND_DEDUP_TEST = """\
You are testing the pm TUI command deduplication behavior. Your goal is to verify
that PR action commands cannot be triggered concurrently, preventing race conditions.

## Background

The TUI allows keyboard shortcuts to trigger PR actions like "pr start" (s key) and
"pr done" (d key). Previously, pressing the same key rapidly or triggering conflicting
actions on different PRs could cause race conditions. The fix adds in-flight action
tracking: while one PR action runs, all other PR actions are blocked with a "Busy: ..."
message in the log line.

## Available Tools

You have access to these commands:
- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (s=start, d=done, j/k=navigate)
- `pm tui frames` - View captured frames
- `pm tui clear-frames` - Clear captured frames
- `tmux list-panes -t <session>` - List panes
- `pm pr add <title>` - Create a dummy PR
- `pm pr close <pr_id>` - Remove a PR from project.yaml

## Test Procedure

### 1. Setup - Create dummy PRs

Create two temporary PRs for testing. These will be cleaned up at the end.

```
pm pr add "Dedup test PR alpha" --description "Temporary PR for dedup testing"
pm pr add "Dedup test PR beta" --description "Temporary PR for dedup testing"
```

Note the IDs assigned (e.g. pr-024, pr-025). Then refresh the TUI:
- `pm tui send r`
- Wait 1 second, then `pm tui view` to confirm the dummy PRs appear
- Navigate to select one of the dummy PRs (use j/k keys)
- Run `pm tui clear-frames` to start with a clean frame buffer

### 2. Test A - Rapid double-press of start key

- Navigate to the first dummy PR
- Send 's' key twice rapidly: `pm tui send s s`
- Wait 2 seconds, then check the TUI: `pm tui view`
- The log line should show "Busy: Starting <pr_id>" for the second press
- Only ONE pr start command should be running
- Check `pm tui frames` to see the sequence of states
- Verify a frame with trigger starting with `log_message:Busy:` was captured

### 3. Test B - Different action while start is running

- If a pr start is still running (spinner visible), send 'd' key
- The log line should show "Busy: Starting <pr_id>"
- The done action should be blocked
- Note: `pr done` now runs async with a spinner, making the dedup guard critical
  for preventing conflicts between concurrent start and done operations

### 4. Test C - Command bar PR action while action is running

- If a pr start is still running, open command bar with '/'
- Type "pr start <second-dummy-pr-id>" and press Enter
- Should show "Busy: ..." message
- Press Escape to dismiss the command bar

### 5. Test D - Non-PR actions are NOT blocked

- While a pr start is running, send 'r' (refresh)
- This should NOT be blocked — refresh should work normally

### 6. Test E - Action allowed after completion

- Wait for the in-flight action to complete (spinner stops)
- Verify the log line shows completion (e.g., "✓ Starting <pr_id> done")
- Try pressing 'd' on the same PR
- It should work (no "Busy" message)

### 7. Test F - pr done dedup with start blocked

- Navigate to the first dummy PR
- Send 'd' key to start `pr done` (runs async with spinner)
- While the spinner is visible, rapidly press 's' to try starting the same PR
- The log line should show "Busy: Completing <pr_id>"
- The start action should be blocked
- Check `pm tui frames` for a frame with trigger starting with `log_message:Busy:`
- Wait for pr done to complete, then verify the PR status changed

### 8. Cleanup - Remove dummy PRs

IMPORTANT: Always run this step, even if tests fail.

```
pm pr close <first-dummy-pr-id>
pm pr close <second-dummy-pr-id>
```

Then refresh the TUI: `pm tui send r`
Verify the dummy PRs are gone: `pm tui view`

## Expected Behavior

- `_inflight_pr_action` is set when a PR action begins
- `_guard_pr_action()` blocks and shows "Busy: ..." if `_inflight_pr_action` is set
- The flag is cleared when the command completes (success or failure)
- Both keyboard shortcuts and command bar commands are guarded
- Non-PR commands (r=refresh, g=guide, n=notes) are NOT blocked

## Reporting

```
COMMAND DEDUP TEST RESULTS
==========================

Dummy PRs created: <pr_id_1>, <pr_id_2>

Test A - Rapid double-press: [PASS/FAIL]
  Second press blocked with Busy message: [Yes/No]
  Only one command executed: [Yes/No]

Test B - Different action during inflight: [PASS/FAIL]
  Action blocked with Busy message: [Yes/No]

Test C - Command bar guarded: [PASS/FAIL]
  Command bar PR action blocked: [Yes/No]

Test D - Non-PR actions not blocked: [PASS/FAIL]
  Refresh worked during inflight action: [Yes/No]

Test E - Action allowed after completion: [PASS/FAIL]
  New action works after previous completes: [Yes/No]

Test F - pr done dedup with start blocked: [PASS/FAIL]
  pr done runs async with spinner: [Yes/No]
  Start blocked with Busy message during done: [Yes/No]
  Busy message captured in frames (log_message:Busy:*): [Yes/No]

Cleanup: [PASS/FAIL]
  Dummy PRs removed: [Yes/No]
  TUI state clean: [Yes/No]

Issues Found:
<list any bugs or unexpected behavior>

OVERALL: [PASS/FAIL]
```
"""


WINDOW_RESIZE_REBALANCE_TEST = """\
You are testing that pane layout automatically rebalances when the terminal
window is resized — the core behavior of the window-size=latest grouped-session
fix (PR-023). The test manually resizes the tmux window to simulate portrait
and landscape aspect ratios, verifies the layout changes accordingly, and
restores the original size at the end.

## Background

When multiple terminals connect to the same pm session via grouped tmux
sessions (e.g. a landscape monitor and a portrait monitor), each terminal may
have different dimensions. With `window-size=latest`, the tmux window follows
the most recently active client's size. A global `window-resized` hook
triggers `pm _window-resized` which calls `rebalance()`, recomputing the
layout based on the new dimensions.

Key implementation details:
- `window-size=latest` is set on all sessions in the group
- Global `window-resized` hook fires `run-shell 'pm _window-resized'`
- `rebalance()` uses `w >= h * 2` to account for character aspect ratio (~2:1 h:w)
- `is_mobile()` triggers for terminals narrower than 120 columns
- Layout uses a recursive binary split: `{ }` for horizontal, `[ ]` for vertical

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI
- `pm tui frames` - View captured frames
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"` - Pane geometries
- `tmux display -t <session> -p "#{window_width} #{window_height}"` - Window size
- `tmux resize-window -t <session> -x <width> -y <height>` - Resize window manually
- `cat ~/.pm/pane-registry/<session>.json` - View pane registry
- `tmux display-message -p "#{session_name}"` - Get session name
- `tmux show-options -t <session> window-size` - Check window-size setting

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Get base session name (strip ~N suffix)
4. Record initial state — SAVE ALL OF THESE for restoration:
   - Window size: `tmux display -t <session> -p "#{window_width} #{window_height}"`
   - Pane geometries: `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - Pane registry: `cat ~/.pm/pane-registry/<base>.json`
   - Window-size option: `tmux show-options -t <session> window-size`
5. The session should have at least 2 panes for this test to be meaningful.
   If it doesn't, press 'n' to open notes pane.

### Part 1: Verify window-size=latest

1. Check the window-size setting:
   - `tmux show-options -t <base> window-size` - should show "latest"
   - If grouped sessions exist, check one: `tmux show-options -t <base>~1 window-size`
   - Both should show "latest"

2. Check the global window-resized hook:
   - `tmux show-hooks -g` - should include `window-resized[0] run-shell "pm _window-resized ..."`

### Part 2: Landscape Layout (wide terminal)

1. Resize window to a clear landscape aspect ratio:
   - `tmux resize-window -t <session> -x 200 -y 50`
   - Wait 1-2 seconds for the hook to fire and rebalance to complete

2. Verify layout is horizontal (side-by-side):
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - Panes should be arranged LEFT-RIGHT (different pane_left values, same pane_top = 0)
   - Each pane should be roughly half the window width (accounting for separator)

3. Verify pane registry is NOT marked user_modified:
   - `cat ~/.pm/pane-registry/<base>.json` - check "user_modified" is false

### Part 3: Portrait Layout (tall terminal)

1. Resize window to a clear portrait aspect ratio:
   - `tmux resize-window -t <session> -x 80 -y 120`
   - Wait 1-2 seconds for the hook to fire

2. Verify layout is vertical (stacked):
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - Panes should be arranged TOP-BOTTOM (different pane_top values, same pane_left = 0)
   - Each pane should be roughly half the window height

3. This is the core bug this PR fixes — a portrait terminal should get a
   vertical split, not be stuck with the landscape layout.

### Part 4: Client-Driven Resize (simulates moving to a different monitor)

This is the critical test. Parts 2-3 use `tmux resize-window` which is an
explicit command and fires `after-resize-window`. But when a user moves
their terminal to a different monitor, the resize comes from the client
(SIGWINCH), which only fires the `window-resized` hook. We must test this
path separately using `tmux refresh-client -C WxH`.

1. First, set the window back to a known landscape state:
   - `tmux resize-window -t <session> -x 200 -y 50`
   - Wait 1-2 seconds, verify panes are side-by-side

2. Now simulate moving to a portrait monitor via client resize:
   - `tmux refresh-client -C 80,120`
   - Wait 1-2 seconds for the `window-resized` hook to fire

3. Verify the layout auto-rebalanced to vertical (stacked):
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - Panes should be arranged TOP-BOTTOM (different pane_top values)
   - If panes are still side-by-side, the hook is NOT firing for client
     resizes — this is the bug that `window-resized` (not `after-resize-window`)
     was needed to fix

4. Simulate moving back to landscape monitor:
   - `tmux refresh-client -C 200,50`
   - Wait 1-2 seconds
   - Verify panes switched back to side-by-side

5. Reset client size to auto:
   - `tmux refresh-client -C ""`  (or omit -C to reset)
   - This clears the manual client size override

### Part 5: Mobile Mode Trigger on Narrow Resize

1. Resize window to narrow (mobile) width:
   - `tmux resize-window -t <session> -x 80 -y 24`
   - Wait 1-2 seconds

2. Check if mobile mode auto-detected:
   - `pm session mobile` - should show "Mobile active: True" (80 < 120 threshold)
   - Active pane should be zoomed: `tmux display -t <session> -p "#{window_zoomed_flag}"` → "1"

3. Resize back to desktop width:
   - `tmux resize-window -t <session> -x 200 -y 50`
   - Wait 1-2 seconds
   - `pm session mobile` - should show "Mobile active: False" (200 >= 120)
   - Zoom should be off (if no force flag): `tmux display -t <session> -p "#{window_zoomed_flag}"` → "0"

### Part 6: Manual Rebalance After Resize

1. Resize to an unusual aspect ratio:
   - `tmux resize-window -t <session> -x 160 -y 80`
   - Wait 1-2 seconds
   - Verify panes redistributed:
     `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height} #{pane_left},#{pane_top}"`
   - With 160x80 (landscape), panes should be side-by-side

2. Run manual rebalance and verify it works:
   - `pm rebalance`
   - Check panes again — layout should be consistent

### Part 7: TUI Responsiveness After Resize

1. Verify TUI is still responsive:
   - `pm tui view` - should render without errors
   - `pm tui send r` (refresh) - should work
   - `pm tui frames` - check recent frames show no errors

### Part 8: Restore Original Size

IMPORTANT: Always restore the window to its original size!

1. Resize back to the original dimensions recorded in Setup:
   - `tmux resize-window -t <session> -x <original_width> -y <original_height>`
   - Wait 1-2 seconds for rebalance

2. Clear the manual window-size override that `tmux resize-window -x -y` sets:
   - `tmux set-window-option -u -t <session> window-size`
   - Without this, the window stays in "manual" sizing mode and will NOT
     auto-resize to follow the attached client, even after `resize-window -A`.
   - Verify it's cleared: `tmux show-window-options -t <session>` should NOT
     show `window-size manual`.

3. Optionally, also run `tmux resize-window -t <session> -A` to snap the
   window size back to the largest attached client immediately.

4. Verify restoration:
   - Pane geometries should match the original state (or be close)
   - TUI should be responsive: `pm tui view`
   - Registry should still have user_modified=false

## Expected Behavior

- Landscape (physically wider): horizontal split `{left,right}` — panes side-by-side
- Portrait (physically taller): vertical split `[top,bottom]` — panes stacked
- The split compares `w >= h * 2` to account for character aspect ratio (~2:1 h:w)
- Narrow (< 120 cols): mobile mode triggers, active pane zooms
- `rebalance()` is called automatically after resize via tmux hook
- Multiple panes: recursive binary split alternates horizontal/vertical
- Layout computation from `pane_layout.py`:
  - `_layout_node` chooses `{` for w >= h*2 (horizontal), `[` otherwise (vertical)
  - 2 panes: single split in appropriate direction
  - 3+ panes: recursive split with alternating axis

## Reporting

```
WINDOW RESIZE REBALANCE TEST RESULTS
=====================================

## Part 1: window-size=latest
Base session has latest: [PASS/FAIL]
Grouped session has latest: [PASS/FAIL]
Global hook exists: [PASS/FAIL]

## Part 2: Landscape Layout (200x50) — via resize-window
Panes are side-by-side: [PASS/FAIL]
  Pane positions: <list pane_left values>
user_modified still false: [PASS/FAIL]

## Part 3: Portrait Layout (80x120) — via resize-window
Panes are stacked vertically: [PASS/FAIL]
  Pane positions: <list pane_top values>

## Part 4: Client-Driven Resize — via refresh-client -C (KEY TEST)
Portrait via refresh-client auto-rebalanced: [PASS/FAIL]
  Pane positions after refresh-client -C 80,120: <list pane_top values>
Landscape via refresh-client auto-rebalanced: [PASS/FAIL]
  Pane positions after refresh-client -C 200,50: <list pane_left values>
THIS TESTS THE REAL SCENARIO (moving terminal between monitors).
If this fails but Parts 2-3 pass, the hook name is wrong.

## Part 5: Mobile Mode on Narrow
Mobile detected at 80 cols: [PASS/FAIL]
Active pane zoomed: [PASS/FAIL]
Desktop mode restored at 200 cols: [PASS/FAIL]
Zoom off after widen: [PASS/FAIL]

## Part 6: Manual Rebalance
pm rebalance works after resize: [PASS/FAIL]

## Part 7: TUI Responsiveness
pm tui view works: [PASS/FAIL]
Refresh works: [PASS/FAIL]

## Part 8: Restore
Manual window-size cleared: [PASS/FAIL]
  `tmux set-window-option -u` removed "window-size manual"
Original size restored: [PASS/FAIL]
  Method: resize-window -A / explicit dimensions
Final state matches original: [PASS/FAIL]

## Issues Found
<list any bugs, unexpected behavior, or timing issues>

## Notes
Original window size: <W>x<H>
Number of panes: <N>
Auto-rebalance fired: [Yes/No/Unknown]
Hook timing: <observed delay between resize and layout change>

OVERALL: [PASS/FAIL]
```
"""


MULTI_WINDOW_REGISTRY_TEST = """\
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
We create a dummy PR to test this — no real PRs are needed.

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
     Find the project root first — look for project.yaml under the pm state
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
   - `pm pr done <dummy_pr_id>`
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
   - Check registry again — review window entry should be gone or have empty panes

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
   - Read registry — main window user_modified should be false again

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

### Part 6: Heal — Dead Pane and Window Removal

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

### Part 7: Heal — Missing TUI Pane

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
   - Run `pm pr list` — the "Registry review test" PR should be gone
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
- `_get_window_data()` creates a new window entry if absent
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

## Part 6: Heal — Dead Removal
Fake dead pane removed: [PASS/FAIL]
Fake dead window removed: [PASS/FAIL]
Real panes preserved: [PASS/FAIL]

## Part 7: Heal — Missing TUI
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
"""


DETAIL_PANEL_CONTENT_TEST = """\
You are testing the detail panel in the pm TUI. Your goal is to verify that
the detail panel shows correct PR information and updates when navigating
between PRs.

## Background

The TUI displays a tech tree of PRs on the left and an optional detail panel
on the right. When a PR is activated (Enter key), the detail panel appears
showing comprehensive information about the selected PR. When navigating
between PRs (Up/Down), the detail panel updates to show the newly selected
PR's info.

The detail panel (from pm_core/tui/detail_panel.py) displays:
- PR display ID (prefers GitHub PR number like #42 over local pr-NNN)
- PR title
- Status with icon (○ pending, ● in_progress, ◎ in_review, ✓ merged, ✗ closed/blocked)
- Git branch name (if set)
- Plan ID and name (if assigned to a plan)
- GitHub PR link (if available)
- Dependencies with their status icons and titles
- Description text
- Plan context: extracted "tests" and "files" sections from the plan markdown

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (Enter=activate, Up/Down=navigate)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer
- `pm pr list` - List all PRs with status

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Run `pm pr list` to see available PRs — note their IDs, titles, and statuses
3. Run `pm tui view` to verify TUI is running and showing the tech tree
4. If in guide mode, press 'x' to dismiss and show the tech tree

### Part 1: Activate Detail Panel

1. Navigate to the first PR:
   - `pm tui send Up` several times to reach the top
   - `pm tui view` - note which PR is selected

2. Open the detail panel:
   - `pm tui send Enter`
   - Wait 1 second
   - `pm tui view` - the detail panel should appear on the right side

3. Verify detail panel contents. Check that these fields are visible:
   - PR ID (e.g., "#42" or "pr-001")
   - PR title
   - Status with appropriate icon
   - Branch name (if the PR has one)
   - Plan name (if the PR belongs to a plan)
   - Dependencies (if any exist)
   - Description (if set)

4. Cross-reference with `pm pr list` output:
   - The status shown in the detail panel should match `pm pr list`
   - The title should match

### Part 2: Detail Panel Updates on Navigation

1. With the detail panel open, navigate to the next PR:
   - `pm tui send Down`
   - Wait 1 second
   - `pm tui view`

2. Verify the detail panel updated:
   - The PR ID should have changed to the newly selected PR
   - The title should match the new PR
   - Status icon should reflect the new PR's status

3. Navigate back up:
   - `pm tui send Up`
   - Wait 1 second
   - `pm tui view`
   - Detail panel should show the original PR's info again

4. Navigate through several PRs:
   - Move Down 3-4 times, checking the detail panel updates each time
   - Verify that each navigation updates the detail panel content

### Part 3: Plan Context Display

1. Find a PR that belongs to a plan:
   - Navigate through PRs looking for one that shows a "Plan:" field
   - If found, verify the plan name is displayed

2. Check for plan-extracted sections:
   - If the PR's plan markdown has a "tests" or "files" section for this PR,
     the detail panel should show those sections under "From plan:"
   - Note whether these sections appear (they depend on plan content)

### Part 4: Dependency Display

1. Find a PR with dependencies:
   - Navigate through PRs looking for one with "Dependencies:" or "Deps:" section
   - If found, verify each dependency shows:
     * Status icon (○, ●, ✓, etc.)
     * PR title or ID
   - Dependencies should be listed with their current status

### Part 5: Frame Analysis

1. Run `pm tui frames --all` to see all captured state changes
2. Look for frames triggered by:
   - "log_message:Selected: ..." - when PRs are selected during navigation
   - Navigation-related state changes
3. Verify frames show consistent detail panel state

## Expected Behavior

From pm_core/tui/detail_panel.py:
- `update_pr()` is called on both PRSelected and PRActivated messages
- PRActivated (Enter) makes the detail container visible (display: block)
- PRSelected (navigation) updates the content if already visible
- `_pr_display_id()` prefers `#<gh_pr_number>` over local `pr-NNN` ID
- `_extract_plan_section()` extracts tests/files from plan markdown for the PR
- STATUS_ICONS: pending=○, in_progress=●, in_review=◎, merged=✓, closed=✗, blocked=✗

## Reporting

```
DETAIL PANEL CONTENT TEST RESULTS
==================================

## Part 1: Activate Detail Panel
Detail panel opens on Enter: [PASS/FAIL]
Fields visible:
  PR ID: [PASS/FAIL] - <ID shown>
  Title: [PASS/FAIL] - <title shown>
  Status + icon: [PASS/FAIL] - <status shown>
  Branch: [PASS/FAIL/N/A] - <branch shown or N/A>
  Plan: [PASS/FAIL/N/A] - <plan shown or N/A>
  Dependencies: [PASS/FAIL/N/A] - <deps shown or N/A>
  Description: [PASS/FAIL/N/A] - <description shown or N/A>

## Part 2: Navigation Updates
Detail panel updates on Down: [PASS/FAIL]
  New PR ID shown: <ID>
Detail panel updates on Up: [PASS/FAIL]
  Original PR ID restored: <ID>
Multi-step navigation: [PASS/FAIL]
  All navigations updated panel: [Yes/No]

## Part 3: Plan Context
PR with plan found: [Yes/No]
Plan name displayed: [PASS/FAIL/N/A]
Plan tests/files sections: [PASS/FAIL/N/A]

## Part 4: Dependencies
PR with dependencies found: [Yes/No]
Dependencies listed with icons: [PASS/FAIL/N/A]
Dependency statuses correct: [PASS/FAIL/N/A]

## Part 5: Frame Analysis
Total frames captured: <N>
Selection triggers seen: [Yes/No]
Detail panel updates in frames: [Yes/No]

## Issues Found
<list any bugs, missing fields, or unexpected behavior>

OVERALL: [PASS/FAIL]
```
"""


STATUS_FILTER_MERGED_TOGGLE_TEST = """\
You are testing the status filter and merged toggle features in the pm TUI.
Your goal is to verify that the F key cycles through status filters and the
X key toggles merged PR visibility.

## Background

The TUI tech tree can be filtered by PR status:
- F key cycles through: all → pending → in_progress → in_review → merged → closed → all
- X key toggles hiding/showing merged PRs
- When a filter is active, only PRs matching that status are shown in the tree
- The status bar displays the current filter
- The log line shows a message on each filter change

Status icons used: ○ pending, ● in_progress, ◎ in_review, ✓ merged, ✗ closed

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (F=cycle filter, X=toggle merged)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer
- `pm pr list` - List all PRs with status

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Run `pm pr list` to inventory all PRs and their statuses
   - Count how many PRs exist in each status (pending, in_progress, in_review, merged, closed)
   - This is your reference for verifying filter results
3. Run `pm tui view` to verify TUI is running and showing the tech tree
4. If in guide mode, press 'x' to dismiss

### Part 1: Status Filter Cycling (F key)

1. Start state — no filter (all PRs shown):
   - `pm tui view` - count the total number of PR nodes visible
   - This should match the total from `pm pr list`

2. First press — filter to "pending":
   - `pm tui send F`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ○ pending"
   - Count visible PR nodes — should match your pending count from setup
   - If no pending PRs exist, the tree should be empty or show a message

3. Second press — filter to "in_progress":
   - `pm tui send F`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ● in_progress"
   - Count visible PR nodes — should match in_progress count

4. Third press — filter to "in_review":
   - `pm tui send F`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ◎ in_review"
   - Count visible PR nodes — should match in_review count

5. Fourth press — filter to "merged":
   - `pm tui send F`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ✓ merged"
   - Count visible PR nodes — should match merged count

6. Fifth press — filter to "closed":
   - `pm tui send F`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: ✗ closed"
   - Count visible PR nodes — should match closed count

7. Sixth press — back to "all":
   - `pm tui send F`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Filter: all"
   - All PRs should be visible again

### Part 2: Merged Toggle (X key)

1. Reset to show all (press F until "Filter: all" appears, or it already is)

2. First toggle — hide merged:
   - `pm tui send X`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Merged PRs hidden"
   - Count visible PR nodes — should be total minus merged count
   - No PR with status "merged" should be visible

3. Verify hidden PRs:
   - If you had any merged PRs in setup, they should be gone from the tree
   - Non-merged PRs should all still be visible

4. Second toggle — show merged:
   - `pm tui send X`
   - Wait 1 second
   - `pm tui view`
   - Log line should show "Merged PRs shown"
   - All PRs should be visible again

### Part 3: Filter and Merged Toggle Interaction

1. Hide merged PRs:
   - `pm tui send X` (should show "Merged PRs hidden")

2. Apply a status filter:
   - `pm tui send F` to filter to "pending"
   - `pm tui view`
   - Only pending PRs should show (merged toggle doesn't matter since
     we're filtering to pending specifically)

3. Cycle back to "all":
   - Press F until "Filter: all" appears
   - `pm tui view`
   - With no status filter but merged hidden, all non-merged PRs should show

4. Show merged again:
   - `pm tui send X` (should show "Merged PRs shown")
   - All PRs should be visible

### Part 4: Status Bar Filter Indicator

1. Apply a filter:
   - `pm tui send F`
   - `pm tui view`
   - Check the status bar (bottom of TUI) for a filter indicator
   - It should show something like "filter: ○ pending"

2. Reset filter:
   - Press F until back to "all"
   - Status bar filter indicator should disappear or show "all"

### Part 5: Frame Analysis

1. Run `pm tui frames --all` to see captured state changes
2. Look for frames triggered by:
   - "log_message:Filter: ..." — each F press should generate one
   - "log_message:Merged PRs hidden/shown" — each X press should generate one
3. Count the filter-related frames — should match the number of F/X presses

## Expected Behavior

From pm_core/tui/app.py action_cycle_filter():
- STATUS_FILTER_CYCLE = [None, "pending", "in_progress", "in_review", "merged", "closed"]
- Cycles through the list, wrapping around to None (all)
- Calls tree._recompute() and tree.refresh(layout=True) after each change
- Logs "Filter: {icon} {status}" or "Filter: all"

From pm_core/tui/app.py action_toggle_merged():
- Toggles tree._hide_merged boolean
- Calls tree._recompute() and tree.refresh(layout=True)
- Logs "Merged PRs hidden" or "Merged PRs shown"

From pm_core/tui/tech_tree.py _recompute():
- If _status_filter is set: filters PRs to only that status
- Elif _hide_merged is True: filters out PRs with status "merged"
- Note: status filter takes priority over merged toggle

## Reporting

```
STATUS FILTER & MERGED TOGGLE TEST RESULTS
============================================

PR inventory from pm pr list:
  Total: <N>
  pending: <N>
  in_progress: <N>
  in_review: <N>
  merged: <N>
  closed: <N>

## Part 1: Status Filter Cycling
Initial (all): [PASS/FAIL] - <visible count> PRs shown
Filter pending: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Filter in_progress: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Filter in_review: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Filter merged: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Filter closed: [PASS/FAIL] - <visible count> PRs (expected <N>)
  Log message: <message seen>
Back to all: [PASS/FAIL] - <visible count> PRs (expected <total>)
  Log message: <message seen>

## Part 2: Merged Toggle
Hide merged: [PASS/FAIL] - <visible count> PRs (expected <total - merged>)
  Log message: <message seen>
  Merged PRs gone: [Yes/No]
Show merged: [PASS/FAIL] - <visible count> PRs (expected <total>)
  Log message: <message seen>

## Part 3: Filter + Merged Interaction
Status filter overrides merged toggle: [PASS/FAIL]
All filter with merged hidden shows non-merged: [PASS/FAIL]

## Part 4: Status Bar Indicator
Filter shown in status bar: [PASS/FAIL]
Filter cleared when reset: [PASS/FAIL]

## Part 5: Frame Analysis
Total frames captured: <N>
Filter frames: <N> (expected ~8 for F presses + 2 for X presses)

## Issues Found
<list any bugs, incorrect counts, or unexpected behavior>

OVERALL: [PASS/FAIL]
```
"""


SYNC_REFRESH_TEST = """\
You are testing the sync/refresh functionality in the pm TUI. Your goal is
to verify that pressing 'r' triggers a sync operation, the log line updates
with sync results, and the tech tree reflects any status changes.

## Background

The TUI's 'r' key triggers a manual refresh that:
1. Immediately shows "Refreshing..." in the log line
2. Runs pr_sync.sync_prs() asynchronously to check for merged PRs on GitHub
3. Updates the log line with the result:
   - "Refreshed" if sync completed with no changes
   - "Synced: N PR(s) merged" if PRs were detected as merged
   - "Already up to date" if sync was skipped (too recent)
   - "Sync error: ..." if something went wrong
4. Reloads the project data and updates the tech tree display
5. The status bar shows "pulling" during sync, then "synced"/"no-op"/"error"

Sync has a minimum interval to avoid hammering GitHub — if you press 'r'
twice quickly, the second press may show "Already up to date".

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (r=refresh)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames with triggers
- `pm tui clear-frames` - Clear frame buffer
- `pm pr list` - List all PRs with status (to verify before/after)

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Run `pm pr list` to record current PR statuses — SAVE this as baseline
3. Run `pm tui view` to verify TUI is running
4. If in guide mode, press 'x' to dismiss

### Part 1: Basic Refresh

1. Trigger refresh:
   - `pm tui send r`
   - Immediately check: `pm tui view`
   - Log line should show "Refreshing..." (may be brief)

2. Wait for sync to complete:
   - Wait 3 seconds
   - `pm tui view`
   - Log line should show one of:
     * "Refreshed" — sync completed, no merged PRs found
     * "Synced: N PR(s) merged" — PRs were detected as merged
     * "Already up to date" — sync skipped (too recent)
     * "Sync error: ..." — something went wrong

3. Check the status bar:
   - Look at the status bar (bottom of TUI)
   - It should show a sync state: "synced", "no-op", or "error"

### Part 2: Status Bar Transition

1. Clear frames: `pm tui clear-frames`
2. Trigger refresh: `pm tui send r`
3. Quickly capture state: `pm tui view` (within 1 second)
   - Status bar may show "pulling" state during sync
4. Wait 3 seconds
5. `pm tui view` — status bar should show post-sync state
6. Check `pm tui frames --all`:
   - Look for frames showing the "Refreshing..." message
   - Look for frames showing the final result message
   - The status bar should transition through states

### Part 3: Rapid Double Refresh

1. Wait at least 10 seconds (to clear the minimum sync interval)
2. First refresh: `pm tui send r`
3. Wait 3 seconds for it to complete
4. Immediately second refresh: `pm tui send r`
5. Wait 2 seconds
6. `pm tui view`
   - Second refresh should either complete normally or show "Already up to date"
   - This tests the minimum interval throttling

### Part 4: PR Status Verification

1. Run `pm pr list` again after the refresh
2. Compare with the baseline from setup:
   - Are there any status changes? (e.g., PRs that went from in_progress to merged)
   - If changes occurred, verify the tech tree in `pm tui view` reflects them
3. If no changes occurred, that's also valid — note that sync found no updates

### Part 5: Refresh During Guide Mode

1. If the TUI has a guide step active:
   - Press 'r' to refresh
   - Log line should show "Refreshed - Guide step: <description>"
   - This is a different code path than the normal sync
2. If not in guide mode, skip this part (N/A)

### Part 6: Log Message Auto-Clear

1. After a manual refresh completes:
   - Note the log message shown
   - Wait 2 seconds
   - `pm tui view`
   - The log message should have auto-cleared (set_timer(1.0, _clear_log_message))
   - Log line should be empty or show a different message

## Expected Behavior

From pm_core/tui/app.py action_refresh():
- Calls _load_state() to reload from disk
- If in guide mode: logs "Refreshed - Guide step: ..." and returns
- If in normal mode: runs _do_normal_sync(is_manual=True) async, logs "Refreshing..."

From pm_core/tui/app.py _do_normal_sync():
- Calls pr_sync.sync_prs() with min_interval for manual refresh
- Updates status bar through: "pulling" → "synced"/"no-op"/"error"
- Log messages: "Refreshed", "Synced: N PR(s) merged", "Already up to date", "Sync error: ..."
- Auto-clears log message after 1 second for manual refresh

## Reporting

```
SYNC REFRESH TEST RESULTS
===========================

## Part 1: Basic Refresh
"Refreshing..." shown: [PASS/FAIL]
Final result message: [PASS/FAIL] - <message seen>
Status bar updated: [PASS/FAIL] - <state shown>

## Part 2: Status Bar Transition
"pulling" state observed: [PASS/FAIL/Not captured]
Post-sync state: [PASS/FAIL] - <state shown>
Frames captured during sync: <N>

## Part 3: Rapid Double Refresh
Second refresh handled: [PASS/FAIL]
  Result: <"Already up to date" or completed normally>

## Part 4: PR Status Verification
Baseline PR count: <N>
Post-sync PR count: <N>
Status changes detected: [Yes/No]
  Changes: <list any status changes>
Tech tree matches pr list: [PASS/FAIL]

## Part 5: Guide Mode Refresh
Guide mode active: [Yes/No]
Guide refresh message: [PASS/FAIL/N/A]

## Part 6: Log Auto-Clear
Log message auto-cleared: [PASS/FAIL]

## Issues Found
<list any bugs, timing issues, or unexpected behavior>

OVERALL: [PASS/FAIL]
```
"""


META_SESSION_LAUNCH_TEST = """\
You are testing the meta session launch feature in the pm TUI. Your goal is
to verify that pressing 'm' launches a meta-development session for working
on the pm tool itself.

## Background

The 'm' key triggers action_launch_meta() which runs `pm meta` as a synchronous
command via _run_command("meta"). The meta command:
1. Detects the pm installation (finds the pm source code directory)
2. Builds a meta prompt describing the pm tool's architecture
3. Creates or finds a workdir for meta development
4. Launches Claude in a new pane with the meta prompt and appropriate context

The meta session is designed for self-referential development — working on the
project manager tool itself from within the project manager TUI.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (m=meta)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `cat ~/.pm/pane-registry/<base>.json` - View pane registry (multi-window format)
- `python3 -c "import json; d=json.load(open('<path>')); print(json.dumps(d, indent=2))"` - Pretty-print registry
- `tmux display-message -p "#{session_name}"` - Get session name
- `tmux capture-pane -t <pane_id> -p` - Capture content of a specific pane
- `tmux kill-pane -t <pane_id>` - Kill a specific pane

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Get base session name (strip ~N suffix if present)
4. Record initial state:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` — count panes
   - `cat ~/.pm/pane-registry/<base>.json` — note the "windows" dict and registered panes/roles
5. Run `pm tui view` to verify TUI is running

### Part 1: Launch Meta Session

1. Send meta key:
   - `pm tui send m`
   - Wait 2 seconds (meta needs time to detect pm install and set up)

2. Check log line:
   - `pm tui view`
   - The log line should show "> meta" (the command being run)
   - After completion, it may show output from the meta command

3. Check for new pane:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"`
   - Compare with initial count — should have one more pane
   - The new pane should be running Claude or a shell with Claude

4. Check pane registry (multi-window format):
   - `cat ~/.pm/pane-registry/<base>.json`
   - Registry uses `{"windows": {"@ID": {"panes": [...]}}}` format
   - Look in the current window's panes for a pane with role "meta" or related
   - Note: The meta command uses _run_command which is synchronous,
     so the pane may be registered differently than _launch_pane panes

### Part 2: Verify Meta Pane Content

1. Identify the new pane ID from the pane list comparison
2. Capture its content:
   - `tmux capture-pane -t <pane_id> -p`
   - Look for Claude startup indicators or meta prompt content
   - The pane should show signs of a Claude session starting

3. Check that the meta session has appropriate context:
   - The prompt should reference the pm tool
   - There may be file paths to pm source code visible

### Part 3: TUI Responsiveness After Meta Launch

1. Verify TUI is still responsive:
   - `pm tui view` — should render without errors
   - Try navigating: `pm tui send Down` then `pm tui send Up`
   - TUI should still respond to keypresses

### Part 4: Duplicate Meta Launch

1. With meta pane already running, press 'm' again:
   - `pm tui send m`
   - Wait 2 seconds
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"`
   - Check if a second meta pane was created or if the existing one was focused
   - Note the behavior (this tests deduplication for meta sessions)

### Part 5: Cleanup

1. If a meta pane was created, you can leave it running — the user may want it
2. Alternatively, to clean up:
   - Find the meta pane ID from the registry or pane list
   - `tmux kill-pane -t <pane_id>`
   - Wait 1 second
   - Verify the TUI is still running: `pm tui view`
   - Check registry was updated: `cat ~/.pm/pane-registry/<base>.json`

## Expected Behavior

From pm_core/tui/app.py action_launch_meta():
- Calls _run_command("meta") which runs `pm meta` synchronously
- The meta command finds the pm installation, builds a prompt, and launches Claude
- A new pane is created in the tmux session
- The TUI shows "> meta" in the log line while running

From pm_core/cli/ meta command:
- _detect_pm_install() finds the pm source code
- _build_meta_prompt() creates a comprehensive prompt about pm architecture
- _meta_workdir() creates/finds a working directory
- Launches Claude with --session-id for resumable sessions

## Reporting

```
META SESSION LAUNCH TEST RESULTS
==================================

## Part 1: Launch Meta Session
'm' key triggered meta: [PASS/FAIL]
Log line showed "> meta": [PASS/FAIL]
New pane created: [PASS/FAIL]
  Initial pane count: <N>
  After meta count: <N>
Pane registry updated: [PASS/FAIL]
  Role: <role found or "not registered">

## Part 2: Meta Pane Content
Claude session starting: [PASS/FAIL/Unclear]
Meta context visible: [PASS/FAIL/Unclear]
  Content observed: <brief description>

## Part 3: TUI Responsiveness
TUI responds after meta launch: [PASS/FAIL]
Navigation still works: [PASS/FAIL]

## Part 4: Duplicate Launch
Behavior on second 'm': <description>
Duplicate pane created: [Yes/No]

## Part 5: Cleanup
Meta pane state: <running/killed/left running>
TUI responsive after cleanup: [PASS/FAIL]

## Issues Found
<list any bugs, errors, or unexpected behavior>

OVERALL: [PASS/FAIL]
```
"""


TUI_LOG_VIEWER_TEST = """\
You are testing the TUI log viewer feature in the pm TUI. Your goal is to
verify that pressing 'L' opens a log pane, the log shows recent TUI activity,
and the pane lifecycle works correctly (launch, focus, kill, relaunch).

## Background

The 'L' key triggers action_view_log() which:
1. Gets the command log file path from command_log_file() (located at
   ~/.pm/debug/{session-tag}.log)
2. If the file doesn't exist, shows "No log file yet." in the log line
3. If it exists, launches a pane running `tail -f <log_path>` with role "log"

The log file contains timestamped entries from all pm commands executed in this
session — every pm CLI command logs its execution and result here.

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (L=view log)
- `pm tui frames` - View captured frames
- `pm tui frames --all` - View all captured frames
- `pm tui clear-frames` - Clear frame buffer
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` - List panes
- `cat ~/.pm/pane-registry/<base>.json` - View pane registry (multi-window format)
- `python3 -c "import json; d=json.load(open('<path>')); print(json.dumps(d, indent=2))"` - Pretty-print registry
- `tmux display-message -p "#{session_name}"` - Get session name
- `tmux capture-pane -t <pane_id> -p` - Capture content of a specific pane
- `tmux kill-pane -t <pane_id>` - Kill a specific pane

## Test Procedure

### Setup

1. Run `pm tui clear-frames` to start with empty frame buffer
2. Get session name: `tmux display-message -p "#{session_name}"`
3. Get base session name (strip ~N suffix if present)
4. Record initial state:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"` — count panes
   - `cat ~/.pm/pane-registry/<base>.json` — note the "windows" dict and registered panes/roles
   - Check if a log pane already exists (role "log") in any window's panes
5. Run `pm tui view` to verify TUI is running

### Part 1: Launch Log Pane

1. Open the log viewer:
   - `pm tui send L`
   - Wait 2 seconds

2. Verify pane was created:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"`
   - Should have one more pane than before
   - The new pane should be running `tail` (visible in pane_current_command)

3. Check pane registry (multi-window format):
   - `cat ~/.pm/pane-registry/<base>.json`
   - Registry uses `{"windows": {"@ID": {"panes": [...]}}}` format
   - Should have a pane with role "log" in the current window's panes

4. Check TUI log line:
   - `pm tui view`
   - Should show "Launched log pane" or "Focused existing log pane"

### Part 2: Log Pane Content

1. Find the log pane ID from the pane list or registry
2. Capture its content:
   - `tmux capture-pane -t <pane_id> -p`
3. Verify the content:
   - Should show timestamped log entries (format: "HH:MM:SS LEVEL message")
   - Should contain entries from recent pm commands
   - Look for entries related to your test actions (tui view, tui send, etc.)
   - The log should be continuously updating (tail -f)

### Part 3: Log Updates in Real-Time

1. Trigger some TUI activity while the log pane is open:
   - `pm tui send r` (refresh — this triggers a sync command)
   - Wait 2 seconds
2. Capture the log pane content again:
   - `tmux capture-pane -t <pane_id> -p`
   - New entries should have appeared for the refresh/sync operation
3. This verifies that `tail -f` is working and the log updates in real-time

### Part 4: Focus Existing Log Pane (Dedup)

1. With the log pane already running, press 'L' again:
   - `pm tui send L`
   - Wait 1 second
2. Check pane count:
   - `tmux list-panes -t <session> -F "#{pane_id}"`
   - Should be SAME as before (no new pane created)
3. Check registry:
   - `cat ~/.pm/pane-registry/<base>.json`
   - Should still have exactly ONE pane with role "log" across all windows
4. Check log line:
   - `pm tui view`
   - Should show "Focused existing log pane"

### Part 5: Kill and Relaunch

1. Find the log pane ID from the registry
2. Kill the log pane:
   - `tmux kill-pane -t <pane_id>`
   - Wait 2 seconds (allow pane-exited handler to run)

3. Verify cleanup:
   - `cat ~/.pm/pane-registry/<base>.json`
   - The log pane should be unregistered (role "log" gone from all windows)

4. Relaunch:
   - `pm tui send L`
   - Wait 2 seconds

5. Verify relaunch:
   - `tmux list-panes -t <session> -F "#{pane_id} #{pane_current_command}"`
   - A new log pane should exist
   - `cat ~/.pm/pane-registry/<base>.json` — role "log" should be back in current window
   - The pane ID should be different from the killed one

### Part 6: Cleanup

1. Kill the log pane if you created one:
   - Find pane ID from registry
   - `tmux kill-pane -t <pane_id>`
   - Wait 1 second
2. Verify TUI is still responsive:
   - `pm tui view`
3. Verify final pane count matches initial count

## Expected Behavior

From pm_core/tui/app.py action_view_log():
- Gets log path from command_log_file() (pm_core.paths)
- If file doesn't exist: logs "No log file yet."
- If exists: calls _launch_pane(f"tail -f {log_path}", "log")

From _launch_pane():
- Checks for existing pane with role "log" via find_live_pane_by_role()
- If found: focuses it, logs "Focused existing log pane"
- If not found: creates new pane, registers with role "log"

Log file location: ~/.pm/debug/{session-tag}.log
Log format: "HH:MM:SS LEVEL message" (e.g., "14:23:01 INFO pm exit=0 ...")

## Reporting

```
TUI LOG VIEWER TEST RESULTS
=============================

## Part 1: Launch Log Pane
'L' key creates pane: [PASS/FAIL]
  Initial pane count: <N>
  After launch count: <N>
Pane running tail: [PASS/FAIL]
Registry has role "log": [PASS/FAIL]
Log line message: <message seen>

## Part 2: Log Content
Log entries visible: [PASS/FAIL]
Timestamp format correct: [PASS/FAIL]
Recent activity present: [PASS/FAIL]
  Sample entry: <one log line>

## Part 3: Real-Time Updates
New entries after refresh: [PASS/FAIL]
tail -f working: [PASS/FAIL]

## Part 4: Focus Dedup
Second 'L' reuses pane: [PASS/FAIL]
  Pane count unchanged: [Yes/No]
  "Focused existing" message: [Yes/No]

## Part 5: Kill and Relaunch
Kill removes from registry: [PASS/FAIL]
Relaunch creates new pane: [PASS/FAIL]
  New pane ID different: [Yes/No]
  Registry updated: [Yes/No]

## Part 6: Cleanup
Panes cleaned up: [PASS/FAIL]
TUI responsive: [PASS/FAIL]
Final pane count matches initial: [PASS/FAIL]

## Issues Found
<list any bugs, missing log entries, or unexpected behavior>

OVERALL: [PASS/FAIL]
```
"""


ALL_TESTS = {
    "pane-layout": {
        "name": "Pane Layout Refresh",
        "prompt": PANE_LAYOUT_REFRESH_TEST,
        "description": "Test that pane kill/relaunch properly refreshes layout",
    },
    "session-resume": {
        "name": "Cluster Session Resume",
        "prompt": CLUSTER_SESSION_RESUME_TEST,
        "description": "Test that cluster explore sessions are saved and resumed correctly",
    },
    "guide-progress": {
        "name": "Guide Progress Widget",
        "prompt": GUIDE_PROGRESS_WIDGET_TEST,
        "description": "Test that guide progress widget displays correct step indicators",
    },
    "restart-dedup": {
        "name": "TUI Restart Pane Deduplication",
        "prompt": TUI_RESTART_PANE_DEDUP_TEST,
        "description": "Test that restarting TUI doesn't create duplicate panes",
    },
    "launch-dedup": {
        "name": "Pane Launch Deduplication",
        "prompt": PANE_LAUNCH_DEDUP_TEST,
        "description": "Test that pane launch keys (g, n) don't create duplicates",
    },
    "tech-tree-visual": {
        "name": "Tech Tree Visual Review",
        "prompt": TECH_TREE_VISUAL_REVIEW_TEST,
        "description": "Review tech tree appearance for visual issues and improvements",
    },
    "pr-interaction": {
        "name": "PR Interaction",
        "prompt": PR_INTERACTION_TEST,
        "description": "Test PR navigation, selection, status changes, and actions",
    },
    "help-keybindings": {
        "name": "Help Screen & Keybindings",
        "prompt": HELP_SCREEN_AND_KEYBINDINGS_TEST,
        "description": "Open help screen with ? and verify all documented keybindings work",
    },
    "plans-pane": {
        "name": "Plans Pane",
        "prompt": PLANS_PANE_TEST,
        "description": "Test plans view toggle, navigation, actions, and refresh persistence",
    },
    "mobile-mode": {
        "name": "Mobile Mode",
        "prompt": MOBILE_MODE_TEST,
        "description": "Test mobile mode auto-zoom, force flag, pane switching, and status command",
    },
    "command-dedup": {
        "name": "Command Deduplication",
        "prompt": COMMAND_DEDUP_TEST,
        "description": "Test that PR actions block concurrent/duplicate execution",
    },
    "window-resize": {
        "name": "Window Resize Rebalance",
        "prompt": WINDOW_RESIZE_REBALANCE_TEST,
        "description": "Test that layout auto-rebalances on window resize (portrait vs landscape)",
    },
    "multi-window-registry": {
        "name": "Multi-Window Registry",
        "prompt": MULTI_WINDOW_REGISTRY_TEST,
        "description": "Test multi-window pane registry, review window isolation, and heal on restart",
    },
    "detail-panel": {
        "name": "Detail Panel Content",
        "prompt": DETAIL_PANEL_CONTENT_TEST,
        "description": "Verify detail panel shows correct PR info and updates on navigation",
    },
    "status-filter": {
        "name": "Status Filter & Merged Toggle",
        "prompt": STATUS_FILTER_MERGED_TOGGLE_TEST,
        "description": "Test F key status filter cycling and X key merged PR toggle",
    },
    "sync-refresh": {
        "name": "Sync Refresh",
        "prompt": SYNC_REFRESH_TEST,
        "description": "Test r key sync, log line updates, and PR status changes",
    },
    "meta-launch": {
        "name": "Meta Session Launch",
        "prompt": META_SESSION_LAUNCH_TEST,
        "description": "Test m key launches meta pane with correct role and context",
    },
    "log-viewer": {
        "name": "TUI Log Viewer",
        "prompt": TUI_LOG_VIEWER_TEST,
        "description": "Test L key opens log pane, verify content and pane lifecycle",
    },
}


def get_test_prompt(test_id: str) -> str | None:
    """Get the prompt for a specific test."""
    test = ALL_TESTS.get(test_id)
    if test:
        return test["prompt"]
    return None


def list_tests() -> list[dict]:
    """List all available tests."""
    return [
        {"id": k, "name": v["name"], "description": v["description"]}
        for k, v in ALL_TESTS.items()
    ]
