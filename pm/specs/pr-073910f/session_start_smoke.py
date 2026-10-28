"""Isolated smoke-test for _session_start's private-server path.

INCIDENT NOTE (2026-10-28): the first version of this script did NOT clear
the inherited TMUX/TMUX_PANE and used the real pm socket directory.  Running
it from inside the live pm session made `_session_start` adopt the live
session, see an empty (temporary-HOME) pane registry, and split a stray
`pm _tui` pane into the live main window.  The production guard added in
`_resolve_start_session_name` now ignores an ambient session this HOME does
not know about, and this script now clears every ambient tmux/pm variable
*before* importing pm_core and binds the whole run to a disposable socket
directory.

Never point this script at the live tmux server.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# --- Isolation, before any pm_core import ---------------------------------
for var in ("TMUX", "TMUX_PANE", "PM_TMUX_SOCKET", "PM_SHARE_MODE",
            "PM_IN_TMUX_SESSION", "PM_PROJECT", "PM_SESSION"):
    os.environ.pop(var, None)

home = tempfile.mkdtemp(prefix="pmsmoke-home-")
repo = tempfile.mkdtemp(prefix="pmsmoke-repo-", dir="/tmp")
sock_dir = tempfile.mkdtemp(prefix="pmsmoke-sock-", dir="/tmp")
os.environ["HOME"] = home
os.environ["EDITOR"] = "true"

WORK = sys.argv[1]
sys.path.insert(0, WORK)

from pm_core import paths
from pm_core import tmux as tm
from pm_core.cli import session as sess

# Dedicated, disposable socket directory (never /tmp/pm-sessions).
paths.SHARED_SOCKET_DIR = Path(sock_dir)
assert not tm.in_tmux(), "refusing to run with an ambient tmux session"

subprocess.run(["git", "init", "-q", repo], check=True)
os.chdir(repo)

# Keep the pane alive instead of launching the real TUI.
orig_create = tm.create_session
def create_session(name, cwd, cmd, socket_path=None, env=None):
    return orig_create(name, cwd, "sleep 300", socket_path=socket_path,
                       env=env)
tm.create_session = create_session
tm.attach = lambda *a, **k: None

sess._session_start()

sock = os.environ.get("PM_TMUX_SOCKET")
assert sock, "PM_TMUX_SOCKET was not exported"
assert Path(sock).parent == Path(sock_dir), (sock, sock_dir)
print("SOCKET:", sock)

name = sess._get_session_name_for_cwd()
print("SESSION:", name)

def run(*args):
    return subprocess.run(["tmux", "-S", sock, *args],
                          capture_output=True, text=True)

r = run("list-sessions", "-F", "#{session_name}")
print("SESSIONS:", r.stdout.split())
assert r.returncode == 0
assert name in r.stdout.split(), r.stdout
assert f"{name}~1" in r.stdout.split(), r.stdout

r = run("show-environment", "-t", name, "PM_TMUX_SOCKET")
print("SESSION ENV:", r.stdout.strip())
assert r.stdout.strip() == f"PM_TMUX_SOCKET={sock}", r.stdout

r = run("show-environment", "-g", "PM_TMUX_SOCKET")
print("GLOBAL ENV:", r.stdout.strip())
assert r.stdout.strip() == f"PM_TMUX_SOCKET={sock}", r.stdout

r = run("show-hooks", "-g")
assert "after-kill-pane" in r.stdout and "run-shell" in r.stdout, r.stdout
print("HOOKS: after-kill-pane present")

# The unique test session must not exist on the default server.
r = subprocess.run(["tmux", "has-session", "-t", name],
                   capture_output=True, text=True)
assert r.returncode != 0, "test session leaked onto the default server!"
print("DEFAULT SERVER: no such session (correct)")

# Cleanup: only our disposable server + temp dirs.
run("kill-server")
Path(sock).unlink(missing_ok=True)
assert not Path(sock).exists()
shutil.rmtree(sock_dir, ignore_errors=True)
shutil.rmtree(repo, ignore_errors=True)
shutil.rmtree(home, ignore_errors=True)
print("CLEANUP: disposable server/socket/dirs removed")
print("SMOKE OK")
