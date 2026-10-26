"""Reproduce the override check/unlink race using the real PR251 handler.

Run from the PR251 checkout with its dependencies available. Only temporary
files are modified. The cat shim pauses after reading the old value, making
a possible reader/writer scheduling order deterministic.
"""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))
from pm_core.cli.meta import _build_meta_pane_cmd

with tempfile.TemporaryDirectory(prefix="pm251-guard-race-") as temporary:
    root = Path(temporary)
    session_dir = root / ".pm/sessions/isolated-test"
    session_dir.mkdir(parents=True)
    override = session_dir / "override"
    old_owner = root / "meta-root"
    new_owner = root / "foreign-root"
    override.write_text(str(old_owner) + "\n")
    (session_dir / "debug").write_text("keep\n")
    with patch("pathlib.Path.home", return_value=root):
        command = _build_meta_pane_cmd("true", "isolated-test", old_owner)

    binaries = root / "bin"
    binaries.mkdir()
    ready = root / "cat-read"
    release = root / "writer-done"
    cat = binaries / "cat"
    cat.write_text(
        '#!/bin/sh\n/bin/cat "$@"\n'
        + "/usr/bin/touch " + shlex.quote(str(ready)) + "\n"
        + "while [ ! -f " + shlex.quote(str(release))
        + " ]; do /bin/sleep 0.01; done\n"
    )
    cat.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = str(binaries) + ":/usr/bin:/bin"
    process = subprocess.Popen(
        ["/bin/sh", "-c", command], env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 8
        while not ready.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                break
            time.sleep(0.01)
        if not ready.exists():
            raise RuntimeError("Reader synchronization failed")
        override.write_text(str(new_owner) + "\n")
        release.touch()
        stdout, stderr = process.communicate(timeout=5)
        print(json.dumps({
            "foreign_override_survived": override.exists(),
            "debug_survived": (session_dir / "debug").exists(),
            "exit": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }, indent=2))
    finally:
        release.touch()
        if process.poll() is None:
            process.kill()
            process.wait()
