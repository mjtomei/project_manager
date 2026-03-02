"""Watched editor: open a temp file in $EDITOR with live save detection.

Provides ``run_watched_editor`` which opens a temp file, launches the
user's editor, and polls for changes in a background thread.  Each time
the file is saved the caller-supplied *on_save* callback fires so
changes can be persisted immediately — the user doesn't need to close
the editor to trigger a save.
"""

import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

from pm_core.claude_launcher import find_editor


def run_watched_editor(
    template: str,
    on_save: Callable[[str], None],
    suffix: str = ".md",
    *,
    _poll_interval: float = 1.0,
) -> tuple[int, bool]:
    """Open a temp file in ``$EDITOR``, calling *on_save* on every write.

    A daemon thread polls the file's mtime at *_poll_interval* seconds.
    When a change is detected the file is read and *on_save* is called
    with the full content.  A final poll runs after the editor exits so
    the last save is never missed.

    Args:
        template: Initial content written to the temp file.
        on_save: Called with file content on each detected save.
            Exceptions are silently caught so the editor is never
            interrupted.
        suffix: Temp file extension (default ``".md"``).
        _poll_interval: Seconds between mtime checks (default 1.0,
            exposed for tests).

    Returns:
        ``(exit_code, was_modified)`` — *was_modified* is ``True`` if
        the file was saved at least once after the editor opened.
    """
    editor = find_editor()

    with tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False) as f:
        f.write(template)
        tmp_path = f.name

    last_mtime = os.path.getmtime(tmp_path)
    modified = False
    stop = threading.Event()

    def _poll():
        nonlocal last_mtime, modified
        try:
            mtime = os.path.getmtime(tmp_path)
        except OSError:
            return
        if mtime == last_mtime:
            return
        last_mtime = mtime
        modified = True
        try:
            on_save(Path(tmp_path).read_text())
        except Exception:
            pass

    def _watcher():
        while not stop.is_set():
            _poll()
            stop.wait(_poll_interval)

    thread = threading.Thread(target=_watcher, daemon=True)
    thread.start()

    try:
        ret = subprocess.call([editor, tmp_path])
    finally:
        stop.set()
        thread.join(timeout=2)
        _poll()  # catch any final save
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return ret, modified
