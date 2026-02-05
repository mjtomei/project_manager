"""Launch claude CLI sessions."""

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pm_core.paths import configure_logger
_log = configure_logger("pm.claude_launcher", "claude_launcher.log")

SESSION_REGISTRY = ".pm-sessions.json"


def _registry_path(pm_root: Path) -> Path:
    return pm_root / SESSION_REGISTRY


def load_session(root: Path, key: str) -> str | None:
    """Load a session ID from the registry, or None if not found."""
    path = _registry_path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return None
        entry = data.get(key)
        if entry and isinstance(entry, dict):
            return entry.get("session_id")
    except (json.JSONDecodeError, OSError):
        pass
    return None


def save_session(root: Path, key: str, session_id: str) -> None:
    """Save a session ID to the registry."""
    path = _registry_path(root)
    data = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                data = loaded
        except (json.JSONDecodeError, OSError):
            pass
    data[key] = {
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2) + "\n")


def clear_session(root: Path, key: str) -> None:
    """Remove a stored session from the registry."""
    path = _registry_path(root)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if key in data:
        del data[key]
        path.write_text(json.dumps(data, indent=2) + "\n")


def _parse_session_id(stderr_text: str) -> str | None:
    """Parse session_id from claude CLI verbose stderr output."""
    for line in stderr_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and "session_id" in obj:
                return obj["session_id"]
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def find_claude() -> str | None:
    """Return path to claude CLI, or None if not found."""
    return shutil.which("claude")


def _skip_permissions() -> bool:
    """Check if skip-permissions is enabled for current session.

    Looks for ~/.pm/sessions/{session}/dangerously-skip-permissions file.
    Falls back to CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS env var for compatibility.
    """
    from pm_core.paths import skip_permissions_enabled
    if skip_permissions_enabled():
        return True
    # Fallback to env var for backwards compatibility
    return os.environ.get("CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS") == "true"


def find_editor() -> str:
    """Return the user's preferred editor."""
    editor = os.environ.get("EDITOR")
    if editor:
        return editor
    for candidate in ("vim", "vi", "nano"):
        if shutil.which(candidate):
            return candidate
    return "vi"


def launch_claude(prompt: str, session_key: str, pm_root: Path,
                  cwd: str | None = None, resume: bool = True) -> int:
    """Run claude interactively with a prompt. Returns exit code.

    Attempts to resume a previous session if one exists for session_key.
    If no session exists, generates a new UUID and passes it via --session-id
    so we can resume later.
    """
    import uuid

    claude = find_claude()
    if not claude:
        raise FileNotFoundError("claude CLI not found. Install it first.")

    # Try to resume existing session, or generate new session ID
    session_id = None
    is_resuming = False
    if resume:
        session_id = load_session(pm_root, session_key)
        if session_id:
            is_resuming = True

    # If no existing session, generate a new UUID
    if not session_id:
        session_id = str(uuid.uuid4())
        # Save immediately so we have it even if claude crashes
        save_session(pm_root, session_key, session_id)
        _log.info("Generated new session_id=%s for key=%s", session_id, session_key)

    cmd = [claude]
    if _skip_permissions():
        cmd.append("--dangerously-skip-permissions")
    if is_resuming:
        cmd.extend(["--resume", session_id])
        # Don't pass prompt when resuming - Claude already has the conversation
    else:
        cmd.extend(["--session-id", session_id])
        cmd.append(prompt)

    _log.info("launch_claude: %s (cwd=%s, session_key=%s, session_id=%s)",
              cmd[:2], cwd, session_key, session_id[:8] + "...")

    result = subprocess.run(cmd, cwd=cwd)
    returncode = result.returncode

    # If session failed (possibly invalid/corrupted), try with fresh session
    if returncode != 0 and resume:
        _log.warning("Session failed (rc=%d), retrying with fresh session", returncode)
        session_id = str(uuid.uuid4())
        save_session(pm_root, session_key, session_id)
        cmd = [claude]
        if _skip_permissions():
            cmd.append("--dangerously-skip-permissions")
        cmd.extend(["--session-id", session_id])
        cmd.append(prompt)
        result = subprocess.run(cmd, cwd=cwd)
        returncode = result.returncode

    return returncode


def launch_claude_print(prompt: str, cwd: str | None = None,
                        message: str = "Claude is working") -> str:
    """Run claude -p (non-interactive print mode). Returns stdout.

    Shows a spinner on stderr while waiting for Claude to finish.
    """
    import sys
    import threading
    import time
    import itertools

    claude = find_claude()
    if not claude:
        raise FileNotFoundError("claude CLI not found. Install it first.")
    cmd = [claude]
    if _skip_permissions():
        cmd.append("--dangerously-skip-permissions")
    cmd.extend(["-p", prompt])

    done = threading.Event()

    def _spinner():
        frames = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        while not done.is_set():
            frame = next(frames)
            sys.stderr.write(f"\r{frame} {message}...")
            sys.stderr.flush()
            done.wait(0.1)
        sys.stderr.write("\r" + " " * (len(message) + 6) + "\r")
        sys.stderr.flush()

    spinner_thread = threading.Thread(target=_spinner, daemon=True)
    spinner_thread.start()

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    finally:
        done.set()
        spinner_thread.join()

    return result.stdout


def launch_claude_in_tmux(pane_target: str, prompt: str, cwd: str | None = None) -> None:
    """Send a claude command to a tmux pane."""
    from pm_core.tmux import send_keys
    escaped = prompt.replace("'", "'\\''")
    skip_flag = " --dangerously-skip-permissions" if _skip_permissions() else ""
    cmd = f"claude{skip_flag} '{escaped}'"
    if cwd:
        cmd = f"cd '{cwd}' && {cmd}"
    send_keys(pane_target, cmd)


def launch_bridge_in_tmux(prompt: str | None, cwd: str, session_name: str) -> str:
    """Launch a bridge in a tmux pane. Returns the socket path."""
    import uuid
    from pm_core.tmux import split_pane_background

    socket_path = f"/tmp/pm-bridge-{uuid.uuid4().hex[:12]}.sock"
    bridge_cmd = f"python3 -m pm_core.bridge {socket_path} --cwd '{cwd}'"
    if prompt:
        escaped = prompt.replace("'", "'\\''")
        bridge_cmd += f" --prompt '{escaped}'"

    split_pane_background(session_name, "v", bridge_cmd)
    return socket_path


def launch_claude_print_background(prompt: str, cwd: str | None = None, callback=None) -> None:
    """Run claude -p in a background thread. Calls callback(stdout, stderr, returncode) when done."""
    import threading

    def _run():
        claude = find_claude()
        if not claude:
            if callback:
                callback("", "claude CLI not found", 1)
            return
        cmd = [claude]
        if _skip_permissions():
            cmd.append("--dangerously-skip-permissions")
        cmd.extend(["-p", prompt])
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if callback:
            callback(result.stdout, result.stderr, result.returncode)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
