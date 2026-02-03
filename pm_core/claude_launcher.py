"""Launch claude CLI sessions."""

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

_log_dir = Path.home() / ".pm-pane-registry"
_log_dir.mkdir(parents=True, exist_ok=True)
_handler = logging.FileHandler(_log_dir / "claude_launcher.log")
_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
_log = logging.getLogger("pm.claude_launcher")
_log.addHandler(_handler)
_log.setLevel(logging.DEBUG)

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
    """Check if CLAUDE_DANGEROUSLY_SKIP_PERMISSIONS is set to 'true'."""
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
    Uses --verbose and captures stderr to a temp file to extract session_id
    for future resumption.
    """
    import tempfile

    claude = find_claude()
    if not claude:
        raise FileNotFoundError("claude CLI not found. Install it first.")

    # Try to resume existing session
    resume_id = None
    if resume:
        resume_id = load_session(pm_root, session_key)

    # Build base command
    base_args = ["--verbose"]
    if _skip_permissions():
        base_args.append("--dangerously-skip-permissions")

    # Create temp file for stderr capture
    # Use bash with tee to show stderr on terminal AND capture to file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False, prefix='pm-claude-') as f:
        stderr_file = f.name

    try:
        # Build command with stderr tee
        args_str = " ".join(base_args)
        if resume_id:
            args_str += f" --resume {resume_id}"
        escaped_prompt = prompt.replace("'", "'\\''")

        # Use bash to run claude with stderr going to both terminal and file
        bash_cmd = f"claude {args_str} '{escaped_prompt}' 2> >(tee '{stderr_file}' >&2)"

        _log.info("launch_claude: claude %s (cwd=%s, session_key=%s, resume_id=%s)",
                  args_str[:50], cwd, session_key, resume_id)

        result = subprocess.run(["bash", "-c", bash_cmd], cwd=cwd)
        returncode = result.returncode

        # Read captured stderr
        stderr_text = ""
        try:
            stderr_text = Path(stderr_file).read_text()
        except Exception as e:
            _log.debug("Failed to read stderr file: %s", e)

        # If resume failed, retry without --resume
        if resume_id and returncode != 0:
            _log.warning("Resume failed (rc=%d), retrying fresh", returncode)
            args_str = " ".join(base_args)
            bash_cmd = f"claude {args_str} '{escaped_prompt}' 2> >(tee '{stderr_file}' >&2)"
            result = subprocess.run(["bash", "-c", bash_cmd], cwd=cwd)
            returncode = result.returncode
            try:
                stderr_text = Path(stderr_file).read_text()
            except Exception:
                pass

        # Extract and save session_id
        sid = _parse_session_id(stderr_text)
        if sid:
            save_session(pm_root, session_key, sid)
            _log.info("Saved session_id=%s for key=%s", sid, session_key)
        else:
            _log.debug("No session_id found in stderr (%d bytes)", len(stderr_text))

    finally:
        # Clean up temp file
        try:
            Path(stderr_file).unlink(missing_ok=True)
        except Exception:
            pass

    return returncode


def launch_claude_print(prompt: str, cwd: str | None = None) -> str:
    """Run claude -p (non-interactive print mode). Returns stdout."""
    claude = find_claude()
    if not claude:
        raise FileNotFoundError("claude CLI not found. Install it first.")
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
