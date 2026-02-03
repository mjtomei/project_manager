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
- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes to TUI (g=guide, n=notes, r=refresh, x=dismiss)
- `pm tui history` - See recent TUI frames
- `tmux list-panes -t <session> -F "#{pane_id} #{pane_width}x#{pane_height}"` - List panes with sizes
- `tmux kill-pane -t <pane_id>` - Kill a specific pane
- `cat ~/.pm-pane-registry/<session>.json` - View pane registry

## Test Procedure

1. First, understand the current state:
   - Run `pm tui view` to see the TUI
   - Run `tmux list-panes` to see all panes and their sizes
   - Check the pane registry to see what panes are registered

2. Test at least TWO of these scenarios (choose based on current state):

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

Begin testing now. Be thorough but efficient.
"""


GUIDE_SESSION_RESUME_TEST = """\
You are testing the pm guide session resume functionality. Your goal is to verify
that Claude sessions are properly saved and resumed when restarting guide.

## Background

The pm guide uses Claude's --session-id flag to enable session resume. When you:
1. Start a guide step, a UUID is generated and saved to .pm-sessions.json
2. Exit and restart guide, it should resume with --resume <session_id>
3. Using --new flag should start a fresh session

## Available Tools

- `pm tui view` - See current TUI state
- `pm tui send <keys>` - Send keystrokes (g=guide, x=dismiss)
- `cat pm/.pm-sessions.json` - View session registry
- `tmux capture-pane -t <pane_id> -p` - Capture any pane's content

## Test Procedure

1. Check current state:
   - View pm/.pm-sessions.json to see saved sessions
   - Note any guide:* session keys and their IDs

2. Test session creation:
   - If no guide session exists, press 'g' to launch guide
   - Wait for guide to start
   - Check .pm-sessions.json - should have new guide:<state> entry
   - Note the session_id

3. Test session resume:
   - Kill the guide pane
   - Press 'g' to relaunch
   - Check if --resume flag is being used (may need to check logs)
   - The session should continue, not restart

## Expected Behavior

From pm_core/cli.py _run_guide():
- If session exists in registry, uses --resume <session_id>
- If no session, generates UUID and uses --session-id <uuid>
- Saves session_id to registry via pm _save-session

## Reporting

```
TEST RESULTS
============
Session creation: [PASS/FAIL]
Session resume: [PASS/FAIL]

Details:
<findings>

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
        "name": "Guide Session Resume",
        "prompt": GUIDE_SESSION_RESUME_TEST,
        "description": "Test that guide sessions are saved and resumed correctly",
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
