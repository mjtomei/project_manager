"""Frame capture infrastructure for the TUI.

All functions take the app instance as the first parameter so they can
access app state (frame buffer, session name, etc.).
"""

import json
import os
import subprocess
from datetime import datetime, timezone

from pm_core.paths import configure_logger, debug_dir
from pm_core import tmux as tmux_mod
from pm_core.tui.guide_progress import GuideProgress

_log = configure_logger("pm.tui.frame_capture")
_log_dir = debug_dir()

# Frame capture defaults
DEFAULT_FRAME_RATE = 1  # Record every change
DEFAULT_FRAME_BUFFER_SIZE = 100


def get_capture_config_path(app) -> "Path":
    """Get path to frame capture config file for this session."""
    from pathlib import Path
    session = app._session_name or "default"
    return _log_dir / f"{session}-capture.json"


def get_frames_path(app) -> "Path":
    """Get path to captured frames file for this session."""
    session = app._session_name or "default"
    return _log_dir / f"{session}-frames.json"


def load_capture_config(app) -> None:
    """Load frame capture config from file (for dynamic updates)."""
    config_path = get_capture_config_path(app)
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            new_rate = config.get("frame_rate", DEFAULT_FRAME_RATE)
            new_size = config.get("buffer_size", DEFAULT_FRAME_BUFFER_SIZE)
            if new_rate != app._frame_rate or new_size != app._frame_buffer_size:
                _log.debug("capture config updated: rate=%d, size=%d", new_rate, new_size)
                app._frame_rate = new_rate
                app._frame_buffer_size = new_size
                # Trim buffer if size reduced
                if len(app._frame_buffer) > app._frame_buffer_size:
                    app._frame_buffer = app._frame_buffer[-app._frame_buffer_size:]
                    save_frames(app)
        except (json.JSONDecodeError, OSError) as e:
            _log.warning("failed to load capture config: %s", e)


def capture_frame(app, trigger: str = "unknown") -> None:
    """Capture the current TUI frame if conditions are met.

    Args:
        trigger: Description of what triggered this capture (for debugging)
    """
    # Get current pane content via tmux
    if not tmux_mod.in_tmux():
        return

    try:
        pane_id = os.environ.get("TMUX_PANE", "")
        if not pane_id:
            return

        result = subprocess.run(
            tmux_mod._tmux_cmd("capture-pane", "-t", pane_id, "-p"),
            capture_output=True, text=True, timeout=5
        )
        content = result.stdout

        # Check if content actually changed
        if content == app._last_frame_content:
            return

        app._last_frame_content = content
        app._frame_change_count += 1

        # Only record every Nth change based on frame_rate
        if app._frame_change_count % app._frame_rate != 0:
            _log.debug("frame change %d skipped (rate=%d)",
                      app._frame_change_count, app._frame_rate)
            return

        # Add to buffer
        frame = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "change_number": app._frame_change_count,
            "trigger": trigger,
            "content": content,
        }
        app._frame_buffer.append(frame)

        # Trim buffer if needed
        if len(app._frame_buffer) > app._frame_buffer_size:
            app._frame_buffer = app._frame_buffer[-app._frame_buffer_size:]

        save_frames(app)
        _log.debug("frame %d captured (trigger=%s)", app._frame_change_count, trigger)

    except Exception as e:
        _log.warning("frame capture failed: %s", e)


def save_frames(app) -> None:
    """Save frame buffer to file."""
    try:
        frames_path = get_frames_path(app)
        frames_path.write_text(json.dumps({
            "frame_rate": app._frame_rate,
            "buffer_size": app._frame_buffer_size,
            "total_changes": app._frame_change_count,
            "frames": app._frame_buffer,
        }, indent=2))
    except OSError as e:
        _log.warning("failed to save frames: %s", e)


def on_guide_step_changed(app, step: str) -> None:
    """Called when guide progress step changes."""
    app.call_after_refresh(app._capture_frame, f"guide_step:{step}")


def on_tree_selection_changed(app, index: int) -> None:
    """Called when tech tree selection changes."""
    app.call_after_refresh(app._capture_frame, f"tree_selection:{index}")


def on_tree_prs_changed(app, prs: list) -> None:
    """Called when tech tree PR list changes."""
    app.call_after_refresh(app._capture_frame, f"tree_prs:{len(prs)}")


def setup_frame_watchers(app) -> None:
    """Set up watchers on child widgets to capture frames on change."""
    try:
        guide_widget = app.query_one("#guide-progress", GuideProgress)
        app.watch(guide_widget, "current_step",
                  lambda step: on_guide_step_changed(app, step))
    except Exception as e:
        _log.debug("could not watch guide-progress: %s", e)

    try:
        from pm_core.tui.tech_tree import TechTree
        tree_widget = app.query_one("#tech-tree", TechTree)
        app.watch(tree_widget, "selected_index",
                  lambda index: on_tree_selection_changed(app, index))
        app.watch(tree_widget, "prs",
                  lambda prs: on_tree_prs_changed(app, prs))
    except Exception as e:
        _log.debug("could not watch tech-tree: %s", e)
