"""Launch claude CLI sessions."""

import json
import logging
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pm_core.paths import configure_logger, log_shell_command
_log = configure_logger("pm.claude_launcher")

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

    Looks for ~/.pm/sessions/{session-tag}/dangerously-skip-permissions
    file containing exactly 'true'.
    """
    from pm_core.paths import skip_permissions_enabled
    return skip_permissions_enabled()


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
    if cwd:
        cmd.extend(["--cwd", cwd])
    if is_resuming:
        cmd.extend(["--resume", session_id])
        # Don't pass prompt when resuming - Claude already has the conversation
    else:
        cmd.extend(["--session-id", session_id])
        cmd.append(prompt)

    _log.info("launch_claude: cmd=%s (cwd=%s, session_key=%s, session_id=%s)",
              cmd[:6], cwd, session_key, session_id[:8] + "...")

    log_shell_command(cmd, prefix="claude")
    result = subprocess.run(cmd, cwd=cwd)
    returncode = result.returncode
    if returncode != 0:
        log_shell_command(cmd, prefix="claude", returncode=returncode)

    # If session failed (possibly invalid/corrupted), try with fresh session
    if returncode != 0 and resume:
        _log.warning("Session failed (rc=%d), retrying with fresh session", returncode)
        session_id = str(uuid.uuid4())
        save_session(pm_root, session_key, session_id)
        cmd = [claude]
        if _skip_permissions():
            cmd.append("--dangerously-skip-permissions")
        if cwd:
            cmd.extend(["--cwd", cwd])
        cmd.extend(["--session-id", session_id])
        cmd.append(prompt)
        log_shell_command(cmd, prefix="claude")
        result = subprocess.run(cmd, cwd=cwd)
        returncode = result.returncode
        if returncode != 0:
            log_shell_command(cmd, prefix="claude", returncode=returncode)

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
        log_shell_command(cmd, prefix="claude-print")
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log_shell_command(cmd, prefix="claude-print", returncode=result.returncode)
    finally:
        done.set()
        spinner_thread.join()

    return result.stdout


def _claude_project_dir(cwd: str) -> Path:
    """Compute Claude's project directory for a given working directory.

    Claude Code stores transcripts in ~/.claude/projects/{mangled-path}/
    where the path has '/' replaced with '-' and '.' replaced with '-'.
    """
    mangled = cwd.replace("/", "-").replace(".", "-")
    return Path.home() / ".claude" / "projects" / mangled


def build_claude_shell_cmd(
    prompt: str | None = None,
    session_id: str | None = None,
    resume: bool = False,
    session_tag: str | None = None,
    transcript: str | None = None,
    cwd: str | None = None,
) -> str:
    """Build a claude shell command string with proper flags and logging.

    All code that launches claude as a shell string (tmux, execvp, etc.)
    should use this to ensure --dangerously-skip-permissions is respected
    and the command is logged.

    Args:
        prompt: The prompt to pass to claude (omitted when resuming)
        session_id: Session ID for --session-id or --resume
        resume: If True and session_id is set, use --resume instead of --session-id
        session_tag: Override session tag for skip-permissions check
        transcript: Path where the transcript symlink should be created.
            Requires ``cwd`` to compute Claude's native transcript location.
            Generates a UUID session ID and creates a symlink from
            ``transcript`` to Claude's native .jsonl file.
        cwd: Working directory for computing Claude's project dir (required
            when ``transcript`` is set).
    """
    # When transcript is requested, generate a UUID and create a symlink
    if transcript and cwd:
        sid = str(uuid.uuid4())
        session_id = sid
        resume = False
        claude_dir = _claude_project_dir(cwd)
        target = claude_dir / f"{sid}.jsonl"
        transcript_path = Path(transcript)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        # Remove stale symlink if present
        if transcript_path.is_symlink() or transcript_path.exists():
            transcript_path.unlink()
        transcript_path.symlink_to(target)
        _log.info("transcript: symlink %s -> %s", transcript_path, target)

    from pm_core.paths import skip_permissions_enabled
    skip = " --dangerously-skip-permissions" if skip_permissions_enabled(session_tag) else ""
    cmd = f"claude{skip}"

    if session_id:
        if resume:
            cmd += f" --resume {session_id}"
        else:
            cmd += f" --session-id {session_id}"

    if prompt and not resume:
        escaped = prompt.replace("'", "'\\''")
        cmd += f" '{escaped}'"

    log_shell_command(cmd, prefix="claude")
    return cmd


def finalize_transcript(transcript_path: Path) -> None:
    """Replace a transcript symlink with a copy of the target file.

    Called when a session finishes so the transcript is self-contained
    and survives Claude session pruning.  No-op if the path is not a
    symlink or the target doesn't exist.
    """
    if not transcript_path.is_symlink():
        return
    target = transcript_path.resolve()
    if target.exists():
        transcript_path.unlink()
        shutil.copy2(target, transcript_path)
        _log.info("transcript: finalized %s (copied from %s)", transcript_path, target)
    else:
        _log.debug("transcript: target %s does not exist, skipping finalize", target)


def launch_claude_in_tmux(pane_target: str, prompt: str, cwd: str | None = None) -> None:
    """Send a claude command to a tmux pane."""
    from pm_core.tmux import send_keys
    cmd = build_claude_shell_cmd(prompt=prompt)
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
        log_shell_command(cmd, prefix="claude-print")
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log_shell_command(cmd, prefix="claude-print", returncode=result.returncode)
        if callback:
            callback(result.stdout, result.stderr, result.returncode)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
