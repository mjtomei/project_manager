"""Shared shell helpers for the TUI modules."""

import shlex
import subprocess

from pm_core.paths import configure_logger

_log = configure_logger("pm.tui.shell")


def _run_shell(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a shell command with logging.

    Logs the command before execution and result after.
    Passes through all kwargs to subprocess.run.
    """
    cmd_str = shlex.join(cmd) if isinstance(cmd, list) else cmd
    _log.info("shell: %s", cmd_str)
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        stderr = getattr(result, 'stderr', '')
        if stderr:
            _log.debug("shell failed (rc=%d): %s", result.returncode, stderr[:200])
    return result


async def _run_shell_async(cmd: list[str], **kwargs):
    """Run a shell command asynchronously with logging.

    Returns the process object for awaiting.
    """
    import asyncio
    cmd_str = shlex.join(cmd) if isinstance(cmd, list) else cmd
    _log.info("shell async: %s", cmd_str)
    return await asyncio.create_subprocess_exec(*cmd, **kwargs)
