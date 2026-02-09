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
3. Using --new flag should start a fresh session

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
   - Run `pm cluster explore --new` to start a fresh session
   - Wait for Claude to start (about 10 seconds)
   - Check .pm-sessions.json - should have new cluster:explore entry
   - Note the session_id
   - Send a memorable message to Claude, e.g.: "Remember this secret: PURPLE-TIGER-99"
   - Wait for Claude to acknowledge (should say something like "I'll remember...")

3. Test session resume:
   - Kill the pane with `tmux kill-pane -t <pane_id>`
   - Create a new pane
   - Run `pm cluster explore` (WITHOUT --new flag)
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

From pm_core/tui/app.py _launch_pane():
- Calls pane_layout.find_live_pane_by_role() to check for existing pane
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
- Copy the PR prompt to clipboard ('p' key)
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

1. Copy prompt ('p'):
   - Select a PR
   - `pm tui send p`
   - Check log line - should say "Prompt copied to clipboard" or similar
   - (Cannot verify clipboard contents, just verify no error)

2. Launch Claude ('c'):
   - Select a PR
   - `pm tui send c`
   - This should open a new pane with Claude
   - Check `tmux list-panes` for new pane
   - Note: This may fail if not in tmux or Claude not installed

3. Edit plan ('e'):
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
- action_copy_prompt() copies prompt to clipboard
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
- Copy prompt ('p'): [PASS/FAIL] - <log message>
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
- PR Actions: s, S, d, c, p, e, v
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
     * S - Start fresh (no resume)
     * d - Mark PR as done
     * c - Launch Claude for PR
     * p - Copy prompt to clipboard
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

4. **p** (copy prompt):
   - `pm tui send p`
   - `pm tui view` → log line should show "Prompt for <id> copied" or clipboard error

5. **/** (command bar):
   - `pm tui send /`
   - `pm tui view` → command bar should be focused
   - `pm tui send Escape` → should unfocus command bar

6. **g** (toggle guide):
   - `pm tui send g`
   - Wait 1 second
   - `pm tui view` → should either show guide view or launch guide pane
   - If guide pane launched, verify via `tmux list-panes`
   - Press 'g' again if needed to return to tech tree

7. **n** (notes):
   - `pm tui send n`
   - Wait 1 second
   - `tmux list-panes` → should see a new notes pane
   - Check registry for role "notes"

8. **L** (view log):
   - `pm tui send L`
   - Wait 1 second
   - `tmux list-panes` → should see a new log pane
   - Check registry for role "log"

9. **r** (refresh):
   - `pm tui send r`
   - `pm tui view` → log line should show "Refreshing..." or sync result

10. **b** (rebalance):
    - `pm tui send b`
    - `pm tui view` → log line should show "Layout rebalanced"

11. **?** (help - test open/close cycle):
    - `pm tui send ?`
    - `pm tui view` → help screen should appear
    - `pm tui send ?` → pressing again should close it
    - `pm tui view` → verify back to normal view

12. **e** (edit PR):
    - `pm tui send e`
    - Wait 1 second
    - `tmux list-panes` → should see editor pane
    - Note: editor may open and close quickly if EDITOR is not set

### Part 3: Destructive Keys (observe only)

Do NOT press these, just verify they exist in help:
- **s** / **S** - Would start a PR (changes project state)
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
  p (copy prompt): [PASS/FAIL] - <log message>
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
  S (start fresh): [PRESENT/MISSING]
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
   - Kill the review pane after verifying

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
