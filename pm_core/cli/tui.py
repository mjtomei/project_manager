"""TUI commands for the pm CLI.

Registers the ``tui`` group and all subcommands, plus the internal
``_tui`` launcher and frame/history helpers.
"""

import json
from pathlib import Path

import click

from pm_core import tmux as tmux_mod
from pm_core.paths import pane_registry_dir, debug_dir

from pm_core.cli import cli
from pm_core.cli.helpers import (
    _find_tui_pane,
    state_root,
)


@cli.command("_tui", hidden=True)
def tui_cmd():
    """Launch the interactive TUI (internal command)."""
    from pm_core.tui.app import ProjectManagerApp
    app = ProjectManagerApp()
    app.run()


@cli.group()
def tui():
    """Control and monitor the TUI from the command line."""
    pass


TUI_HISTORY_DIR = pane_registry_dir() / "tui-history"
TUI_MAX_FRAMES = 50


def _tui_history_file(session: str) -> Path:
    """Get the TUI history file for a specific session."""
    TUI_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return TUI_HISTORY_DIR / f"{session.split('~')[0]}.json"


def _capture_tui_frame(pane_id: str) -> str:
    """Capture the current TUI pane content."""
    import subprocess
    result = subprocess.run(
        tmux_mod._tmux_cmd("capture-pane", "-t", pane_id, "-p"),
        capture_output=True, text=True
    )
    return result.stdout


def _load_tui_history(session: str) -> list:
    """Load TUI frame history for a session."""
    history_file = _tui_history_file(session)
    if not history_file.exists():
        return []
    try:
        return json.loads(history_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_tui_history(session: str, history: list) -> None:
    """Save TUI frame history for a session."""
    history_file = _tui_history_file(session)
    history_file.write_text(json.dumps(history, indent=2))


def _add_frame_to_history(session: str, frame: str, pane_id: str) -> None:
    """Add a frame to history, keeping only the last N frames."""
    from datetime import datetime, timezone
    history = _load_tui_history(session)
    history.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pane_id": pane_id,
        "content": frame,
    })
    # Keep only last N frames
    if len(history) > TUI_MAX_FRAMES:
        history = history[-TUI_MAX_FRAMES:]
    _save_tui_history(session, history)


@tui.command("view")
@click.option("--no-history", is_flag=True, help="Don't add this frame to history")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_view(no_history: bool, session: str | None):
    """View current TUI output.

    Captures the current TUI pane content and displays it.
    Also adds the frame to history for later review (unless --no-history).
    """
    pane_id, sess = _find_tui_pane(session)
    if not pane_id:
        click.echo("No TUI pane found. Is there a pm tmux session running?", err=True)
        raise SystemExit(1)

    frame = _capture_tui_frame(pane_id)
    if not no_history:
        _add_frame_to_history(sess, frame, pane_id)

    click.echo(f"[Session: {sess}, Pane: {pane_id}]")
    click.echo(frame)


@tui.command("history")
@click.option("--frames", "-n", default=5, help="Number of frames to show")
@click.option("--all", "show_all", is_flag=True, help="Show all frames")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_history(frames: int, show_all: bool, session: str | None):
    """View recent TUI frames from history.

    Shows the last N captured frames with timestamps.
    """
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    history = _load_tui_history(sess)
    if not history:
        click.echo(f"No TUI history found for session {sess}.")
        return

    if show_all:
        frames = len(history)

    recent = history[-frames:]
    click.echo(f"[Session: {sess}]")
    for i, entry in enumerate(recent):
        timestamp = entry.get("timestamp", "unknown")
        content = entry.get("content", "")
        click.echo(f"{'=' * 60}")
        click.echo(f"Frame {len(history) - len(recent) + i + 1}/{len(history)} @ {timestamp}")
        click.echo(f"{'=' * 60}")
        click.echo(content)
        click.echo()


@tui.command("send")
@click.argument("keys")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_send(keys: str, session: str | None):
    """Send keys to the TUI.

    KEYS can be single characters, key names, or sequences:
      - Single keys: g, x, r, q
      - Special keys: Enter, Escape, Up, Down, Left, Right, Tab
      - Ctrl combinations: C-c, C-d
      - Sequences: "gr" sends 'g' then 'r'

    Examples:
      pm tui send g          # Press 'g' (launch guide)
      pm tui send x          # Press 'x' (dismiss guide)
      pm tui send r          # Press 'r' (refresh)
      pm tui send Enter      # Press Enter
      pm tui send C-c        # Press Ctrl+C
    """
    import subprocess
    pane_id, sess = _find_tui_pane(session)
    if not pane_id:
        click.echo("No TUI pane found. Is there a pm tmux session running?", err=True)
        raise SystemExit(1)

    subprocess.run(tmux_mod._tmux_cmd("send-keys", "-t", pane_id, keys), check=True)
    click.echo(f"Sent keys '{keys}' to TUI pane {pane_id} (session: {sess})")


@tui.command("keys")
def tui_keys():
    """Show available TUI keybindings."""
    click.echo("""\
TUI Keybindings:

Navigation:
  Up/Down, j/k     Navigate PR list
  Enter            Select/expand PR

Actions:
  g                Launch guide pane
  n                Open notes
  c                Launch Claude for selected PR
  r                Refresh state

Guide Mode:
  x                Dismiss guide view

General:
  q                Quit TUI
  ?                Show help
""")


@tui.command("restart")
@click.option("--breadcrumb", is_flag=True,
              help="Write merge-restart marker to preserve auto-start and review loop state")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_restart(breadcrumb: bool, session: str | None):
    """Restart the TUI.

    Sends Ctrl+R to the TUI pane. With --breadcrumb, writes a
    merge-restart marker so the TUI preserves auto-start and review loop
    state across the restart (same behavior as merge-triggered restarts).

    Examples:
        pm tui restart                  # Clean restart (no state preserved)
        pm tui restart --breadcrumb     # Restart preserving loop state
    """
    import subprocess

    pane_id, sess = _find_tui_pane(session)
    if not pane_id:
        click.echo("No TUI pane found. Is there a pm tmux session running?", err=True)
        raise SystemExit(1)

    if breadcrumb:
        from pm_core.paths import pm_home
        marker = pm_home() / "merge-restart"
        marker.touch()
        click.echo("Wrote merge-restart marker for state persistence")

    subprocess.run(tmux_mod._tmux_cmd("send-keys", "-t", pane_id, "C-r"), check=True)
    click.echo(f"Sent restart to TUI pane {pane_id} (session: {sess})")


@tui.command("clear-history")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_clear_history(session: str | None):
    """Clear the TUI frame history for a session."""
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    history_file = _tui_history_file(sess)
    if history_file.exists():
        history_file.unlink()
        click.echo(f"TUI history cleared for session {sess}.")
    else:
        click.echo(f"No history to clear for session {sess}.")


# --- Frame capture commands ---

_log_dir = debug_dir()


def _capture_config_file(session: str) -> Path:
    """Get the capture config file path for a session."""
    return _log_dir / f"{session}-capture.json"


def _capture_frames_file(session: str) -> Path:
    """Get the captured frames file path for a session."""
    return _log_dir / f"{session}-frames.json"


@tui.command("capture")
@click.option("--frame-rate", "-r", type=int, default=None,
              help="Record every Nth change (1=all changes)")
@click.option("--buffer-size", "-b", type=int, default=None,
              help="Max frames to keep in buffer")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_capture_config(frame_rate: int | None, buffer_size: int | None, session: str | None):
    """Configure frame capture settings.

    Frame capture is always enabled. Use this to adjust:
    - frame-rate: Record every Nth change (default: 1 = record all)
    - buffer-size: How many frames to keep (default: 100)

    The TUI will pick up config changes on its next sync cycle (~30s)
    or immediately if you press 'r' to refresh.

    Examples:
        pm tui capture --frame-rate 1 --buffer-size 200
        pm tui capture -r 5 -b 50
    """
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    config_file = _capture_config_file(sess)

    # Load existing config or defaults
    config = {"frame_rate": 1, "buffer_size": 100}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Update with provided values
    if frame_rate is not None:
        if frame_rate < 1:
            click.echo("frame-rate must be >= 1", err=True)
            raise SystemExit(1)
        config["frame_rate"] = frame_rate
    if buffer_size is not None:
        if buffer_size < 1:
            click.echo("buffer-size must be >= 1", err=True)
            raise SystemExit(1)
        config["buffer_size"] = buffer_size

    # Save config
    config_file.write_text(json.dumps(config, indent=2))
    click.echo(f"Capture config for session {sess}:")
    click.echo(f"  frame_rate:  {config['frame_rate']} (record every {config['frame_rate']} change(s))")
    click.echo(f"  buffer_size: {config['buffer_size']} frames")
    click.echo("\nTUI will pick up changes on next sync or press 'r' to refresh.")


@tui.command("frames")
@click.option("--count", "-n", type=int, default=5, help="Number of frames to show")
@click.option("--all", "show_all", is_flag=True, help="Show all frames")
@click.option("--session", "-s", default=None, help="Specify pm session name")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def tui_frames(count: int, show_all: bool, session: str | None, as_json: bool):
    """View captured TUI frames.

    Shows frames captured when the TUI changes (based on frame_rate setting).
    Each frame includes timestamp, trigger, and content.

    Examples:
        pm tui frames              # Show last 5 frames
        pm tui frames -n 20        # Show last 20 frames
        pm tui frames --all        # Show all frames
        pm tui frames --json       # Output as JSON for scripting
    """
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    frames_file = _capture_frames_file(sess)
    if not frames_file.exists():
        click.echo(f"No captured frames for session {sess}.")
        return

    try:
        data = json.loads(frames_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        click.echo(f"Error reading frames: {e}", err=True)
        raise SystemExit(1)

    frames = data.get("frames", [])
    if not frames:
        click.echo(f"No frames captured yet for session {sess}.")
        return

    if as_json:
        if show_all:
            click.echo(json.dumps(data, indent=2))
        else:
            output = {**data, "frames": frames[-count:]}
            click.echo(json.dumps(output, indent=2))
        return

    # Show summary
    click.echo(f"[Session: {sess}]")
    click.echo(f"Total changes: {data.get('total_changes', '?')}")
    click.echo(f"Frame rate: {data.get('frame_rate', '?')} | Buffer size: {data.get('buffer_size', '?')}")
    click.echo(f"Frames captured: {len(frames)}")
    click.echo()

    if show_all:
        count = len(frames)

    recent = frames[-count:]
    for i, frame in enumerate(recent):
        frame_num = len(frames) - len(recent) + i + 1
        timestamp = frame.get("timestamp", "unknown")
        trigger = frame.get("trigger", "unknown")
        change_num = frame.get("change_number", "?")
        content = frame.get("content", "")

        click.echo("=" * 60)
        click.echo(f"Frame {frame_num}/{len(frames)} | Change #{change_num} | {trigger}")
        click.echo(f"Time: {timestamp}")
        click.echo("=" * 60)
        click.echo(content)
        click.echo()


@tui.command("clear-frames")
@click.option("--session", "-s", default=None, help="Specify pm session name")
def tui_clear_frames(session: str | None):
    """Clear captured frames for a session."""
    pane_id, sess = _find_tui_pane(session)
    if not sess:
        click.echo("No pm tmux session found.", err=True)
        raise SystemExit(1)

    frames_file = _capture_frames_file(sess)
    if frames_file.exists():
        frames_file.unlink()
        click.echo(f"Captured frames cleared for session {sess}.")
    else:
        click.echo(f"No frames to clear for session {sess}.")


@tui.command("test")
@click.argument("test_id", required=False)
@click.option("--list", "list_tests_flag", is_flag=True, help="List available tests")
@click.option("--session", "-s", default=None, help="Specify pm session name")
@click.option("--file-bugs", is_flag=True, default=False, help="Create PRs for any bugs found")
@click.option("--fix-bugs", is_flag=True, default=False, help="Fix bugs found during testing")
def tui_test(test_id: str | None, list_tests_flag: bool, session: str | None,
             file_bugs: bool, fix_bugs: bool):
    """Run TUI regression tests using Claude as the test executor.

    These tests launch Claude with a specific test prompt that instructs it
    to interact with the TUI and tmux, verify behavior, and report results.

    Examples:
        pm tui test --list              # List available tests
        pm tui test pane-layout         # Run pane layout test
        pm tui test session-resume      # Run session resume test
    """
    from pm_core import tui_tests

    if list_tests_flag:
        tests = tui_tests.list_tests()
        click.echo("Available TUI tests:\n")
        for t in tests:
            click.echo(f"  {t['id']:20} {t['name']}")
            click.echo(f"  {' '*20} {t['description']}\n")
        return

    if not test_id:
        click.echo("Usage: pm tui test <test_id>")
        click.echo("Run 'pm tui test --list' to see available tests.")
        raise SystemExit(1)

    test_info = tui_tests.ALL_TESTS.get(test_id)
    if not test_info:
        click.echo(f"Unknown test: {test_id}", err=True)
        click.echo("Run 'pm tui test --list' to see available tests.")
        raise SystemExit(1)

    prompt = test_info["prompt"]
    init_fn = test_info.get("init")
    cleanup_fn = test_info.get("cleanup")
    init_context = None
    cwd = None

    if init_fn:
        # Test provides its own setup (e.g. creating a git repo).
        # Claude will start the session itself during the test.
        click.echo(f"Running init for test: {test_info['name']}...")
        init_context = init_fn()
        sess = init_context["session_name"]
        pane_id = init_context.get("pane_id")
        cwd = init_context["cwd"]
        # Format placeholders into prompt
        prompt_ctx = init_context.get("prompt_context", {})
        prompt = prompt.format(**prompt_ctx)
    else:
        # Existing flow — find a running TUI session
        pane_id, sess = _find_tui_pane(session)
        if not sess:
            click.echo("No pm tmux session found. Start one with 'pm session'.", err=True)
            raise SystemExit(1)

    # Build bug-handling addendum
    bug_addendum = ""
    if file_bugs:
        bug_addendum = """

## Bug Filing

After completing all test scenarios, if you found ANY bugs or unexpected behavior:

1. For each bug, create a PR entry using: `pm pr add --title "<short bug title>" --description "<what's wrong and how to reproduce>" --plan plan-001`
2. Use clear, actionable titles like "Fix zoom not applied after rebalance in mobile mode"
3. Include reproduction steps in the description
4. After creating all bug PRs, list them in your report under a "Filed PRs" section
5. If no bugs were found, note "No bugs found, no PRs filed"
"""
    elif fix_bugs:
        bug_addendum = """

## Bug Fixing

After completing all test scenarios, if you found ANY bugs or unexpected behavior:

1. First, complete your full test report as described above
2. Then, for each bug you found, fix it:
   a. Identify the source file and the root cause
   b. Edit the file to fix the bug
   c. Re-run the relevant test scenario to verify the fix
   d. Note what you changed in a "Fixes Applied" section of your report
3. Work through bugs one at a time, verifying each fix before moving to the next
4. If a fix is unclear or risky, skip it and note why
5. After all fixes, run `python3 -m pytest tests/ -x -q` to check for regressions
6. If no bugs were found, note "No bugs found, no fixes needed"
"""

    # Add session context to the prompt
    pane_line = f"\nThe TUI pane ID is: {pane_id}" if pane_id else ""
    full_prompt = f"""\
## Session Context

You are testing against tmux session: {sess}{pane_line}

To interact with this session, use commands like:
- pm tui view -s {sess}
- pm tui send <keys> -s {sess}
- tmux list-panes -t {sess} -F "#{{pane_id}} #{{pane_width}}x#{{pane_height}} #{{pane_current_command}}"
- cat ~/.pm/pane-registry/{sess}.json

{prompt}
{bug_addendum}
"""

    click.echo(f"Running test: {test_info['name']}")
    click.echo(f"Session: {sess}")
    click.echo(f"Claude cwd: {cwd}")
    click.echo("-" * 60)

    # Launch Claude with the test prompt (no session resume for tests)
    from pm_core.claude_launcher import launch_claude
    try:
        root = state_root()
    except FileNotFoundError:
        root = Path.home() / ".pm"
    rc = 1
    try:
        rc = launch_claude(full_prompt, session_key=f"tui-test:{test_id}",
                           pm_root=root, cwd=cwd, resume=False)
    finally:
        if cleanup_fn and init_context:
            click.echo("Cleaning up test session...")
            cleanup_fn(init_context)
    raise SystemExit(rc)
