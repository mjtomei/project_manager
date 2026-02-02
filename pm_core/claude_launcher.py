"""Launch claude CLI sessions."""

import os
import shutil
import subprocess


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


def launch_claude(prompt: str, cwd: str | None = None) -> int:
    """Run claude interactively with a prompt. Returns exit code."""
    claude = find_claude()
    if not claude:
        raise FileNotFoundError("claude CLI not found. Install it first.")
    cmd = [claude]
    if _skip_permissions():
        cmd.append("--dangerously-skip-permissions")
    cmd.append(prompt)
    result = subprocess.run(cmd, cwd=cwd)
    return result.returncode


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
