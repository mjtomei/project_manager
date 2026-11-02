"""Tests for popup-cmd Esc/Ctrl+C abort handling.

The popup spawns the user-typed pm command via `_run_with_abort_keys`,
which watches the popup pty for Esc / Ctrl+C and terminates the child.
Without this, long-running commands like `pr start <new-pr>` could not be
cancelled — the popup would just sit there until the subprocess finished
on its own.
"""

import os
import pty
import subprocess
import sys
import time

import pytest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _spawn_under_pty(target_script: str) -> tuple[int, int]:
    """Fork a child running *target_script* under a fresh pty.

    Returns ``(pid, master_fd)``.  The caller can write keystrokes to
    ``master_fd`` and waitpid on ``pid``.
    """
    pid, master = pty.fork()
    if pid == 0:
        # Child: run the script.
        env = dict(os.environ)
        env["PYTHONPATH"] = REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
        os.execvpe(sys.executable, [sys.executable, "-c", target_script], env)
    return pid, master


def _wait_with_timeout(pid: int, timeout: float) -> int | None:
    """Poll waitpid for up to *timeout* seconds. Returns exit status or None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        wpid, status = os.waitpid(pid, os.WNOHANG)
        if wpid != 0:
            return status
        time.sleep(0.05)
    return None


SLEEPER = (
    "import sys, time;"
    "sys.stdout.write('ready\\n'); sys.stdout.flush();"
    "time.sleep(60)"
)


def _harness(key: str) -> str:
    """Python source that calls _run_with_abort_keys on a long sleeper."""
    return (
        "import sys, os, time;"
        "from pm_core.cli.session import _run_with_abort_keys, _ABORTED_BY_USER;"
        f"rc = _run_with_abort_keys([sys.executable, '-c', {SLEEPER!r}]);"
        "print('RC=' + ('ABORT' if rc == _ABORTED_BY_USER else str(rc)));"
        "sys.stdout.flush()"
    )


@pytest.mark.parametrize("key,name", [(b"\x1b", "esc"), (b"\x03", "ctrl-c")])
def test_abort_key_terminates_child_and_signals_abort(key, name):
    pid, master = _spawn_under_pty(_harness(key))
    try:
        # Wait until the sleeper has printed 'ready' so we know the parent
        # is in its select loop.
        deadline = time.monotonic() + 10
        buf = b""
        while time.monotonic() < deadline and b"ready" not in buf:
            try:
                buf += os.read(master, 1024)
            except OSError:
                break
        assert b"ready" in buf, f"sleeper never started; got: {buf!r}"

        os.write(master, key)

        status = _wait_with_timeout(pid, timeout=10)
        assert status is not None, "parent did not exit after abort key"

        # Drain remaining output to confirm RC=ABORT.
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
        assert b"RC=ABORT" in buf, f"expected RC=ABORT, got: {buf!r}"
    finally:
        try:
            os.close(master)
        except OSError:
            pass
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass


def test_normal_exit_returns_child_returncode():
    """When the child exits on its own, abort path is not taken."""
    from pm_core.cli.session import _run_with_abort_keys, _ABORTED_BY_USER

    # Non-tty path: just delegates to subprocess.run.
    rc = _run_with_abort_keys([sys.executable, "-c", "import sys; sys.exit(7)"])
    assert rc == 7
    assert rc != _ABORTED_BY_USER
