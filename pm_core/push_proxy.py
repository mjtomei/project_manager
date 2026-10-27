"""Host-side git remote proxy for containerised sessions.

Containers must not hold git credentials directly.  Each container gets a
proxy socket mounted into it.  A git wrapper inside the container intercepts
remote-interacting commands (``push``, ``fetch``, ``pull``, ``ls-remote``)
and forwards them to the proxy.

The proxy:
  1. Validates push targets against the allowed branch for that container
  2. Executes the real git command on the host (where credentials live)
  3. Rejects local-path origins (fail-closed) and broad push flags
  4. Streams back exit code, stdout, and stderr transparently

One proxy serves exactly one host workdir.  Shared proxies are keyed by
``(session_tag, pr_id, workdir_token)`` so an implementation container and
each QA scenario container on the same PR get their own socket even though
they target the same branch.  Each container's git wrapper includes its
host-side clone path in the request as ``"workdir"``; the proxy accepts it
only when it matches the proxy's own workdir and falls back to
``self.workdir`` for legacy requests that omit the field.  A request naming
another clone is rejected explicitly — a failed push must never silently
run against a different workdir.

Protocol (newline-delimited JSON over Unix socket):
  Request:  {"cmd": "push|fetch|pull|ls-remote", "args": ["origin", "branch"],
             "workdir": "/host/path/to/clone"}
  Response: {"exit_code": 0, "stdout": "...", "stderr": "..."}

Legacy requests without ``cmd`` are treated as push (backward compat).
``"workdir"`` is optional; omitting it falls back to ``self.workdir``.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.push_proxy")

_SOCKET_DIR_PREFIX = "pm-push-proxy-"
_CONTAINER_SOCKET_DIR = "/run/pm-push-proxy"
_CONTAINER_SOCKET_PATH = f"{_CONTAINER_SOCKET_DIR}/push.sock"
_METADATA_NAME = "proxy.json"


class PushProxyError(RuntimeError):
    """The push proxy could not be started or made ready."""


class PushProxyConflict(PushProxyError):
    """A live proxy serves a different workdir or allowed branch."""


def _resolve_local_remote_url(workdir: str, remote: str = "origin") -> str | None:
    """If *remote* in *workdir* points to a local directory, return its path.

    Returns ``None`` if the remote is a real URL (http, ssh, git://, etc.)
    or if the remote doesn't exist.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote],
            cwd=workdir, capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return None
        url = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    # Real remote URLs have a scheme or use scp-style syntax (user@host:path)
    if "://" in url or ("@" in url and ":" in url.split("@", 1)[1]):
        return None

    # Resolve relative paths against workdir
    p = Path(url) if Path(url).is_absolute() else Path(workdir) / url
    try:
        resolved = str(p.resolve())
    except (OSError, ValueError):
        return None
    if Path(resolved).is_dir():
        return resolved
    return None


def resolve_real_origin(repo_path: str, remote: str = "origin") -> str | None:
    """Walk the remote chain to find the real (non-local) origin URL.

    Starting from *repo_path*, if ``remote`` points to a local directory,
    follow that directory's ``remote`` in turn, until we find a URL that
    is a real remote (http, ssh, etc.) or we run out of chain.

    Returns the real URL, or ``None`` if the chain ends at a local path
    (i.e. the repo is truly local-only).
    """
    workdir = repo_path
    seen: set[str] = set()
    while workdir not in seen:
        seen.add(workdir)
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", remote],
                cwd=workdir, capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None
            url = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

        local = _resolve_local_remote_url(workdir, remote)
        if local is None:
            # This is a real remote URL
            return url
        # Follow the chain
        workdir = local
    return None


def _metadata_path(sock_path: str) -> str:
    """Sidecar describing which workdir/branch a socket's daemon serves."""
    return os.path.join(os.path.dirname(sock_path), _METADATA_NAME)


def _write_metadata(sock_path: str, workdir: str,
                    allowed_branch: str) -> None:
    """Atomically record the daemon's workdir/branch next to its socket.

    Best-effort: a read-only socket directory must not stop the proxy.
    """
    path = _metadata_path(sock_path)
    tmp = f"{path}.{os.getpid()}.tmp"
    payload = {
        "workdir": os.path.realpath(workdir),
        "allowed_branch": allowed_branch,
        "pid": os.getpid(),
    }
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except OSError:
        _log.warning("Push proxy: could not write metadata %s", path,
                     exc_info=True)
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _read_metadata(sock_path: str) -> dict | None:
    """Return the sidecar metadata for *sock_path*, or None if unreadable."""
    try:
        with open(_metadata_path(sock_path), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class PushProxy:
    """A single-client push proxy daemon for one container.

    Args:
        socket_path: Host path for the Unix socket.
        workdir: Host path to the git working directory.
        allowed_branch: The only branch pushes are allowed to target.
    """

    def __init__(self, socket_path: str, workdir: str,
                 allowed_branch: str) -> None:
        self.socket_path = socket_path
        self.workdir = workdir
        self.allowed_branch = allowed_branch
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._sock_ino: int | None = None

    def start(self) -> bool:
        """Start the proxy in a background daemon thread.

        Returns ``False`` when a live proxy already owns the socket path;
        in that case this instance does not bind, does not replace the
        existing socket, and must not unlink it on ``stop()``.
        """
        # Ensure parent directory exists
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)

        # Never steal a live socket.  Two daemons racing to unlink→bind is
        # how a proxy for one workdir used to replace another's.
        if os.path.exists(self.socket_path) and proxy_is_alive(self.socket_path):
            _log.warning("Push proxy socket already served; not replacing: %s",
                         self.socket_path)
            return False

        # Clean up stale socket (docker may have created a directory here)
        try:
            os.unlink(self.socket_path)
        except IsADirectoryError:
            import shutil
            shutil.rmtree(self.socket_path, ignore_errors=True)
        except FileNotFoundError:
            pass

        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(self.socket_path)
        # Make socket world-writable so the container user can connect
        os.chmod(self.socket_path, 0o777)
        try:
            self._sock_ino = os.stat(self.socket_path).st_ino
        except OSError:
            self._sock_ino = None
        # Record the served workdir/branch so start_push_proxy can refuse a
        # mismatched reuse instead of silently replacing this daemon.
        _write_metadata(self.socket_path, self.workdir, self.allowed_branch)
        self._server_socket.listen(1)
        self._server_socket.settimeout(2.0)

        self._thread = threading.Thread(
            target=self._serve_loop, daemon=True,
            name=f"push-proxy-{Path(self.socket_path).stem}",
        )
        self._thread.start()
        _log.info("Push proxy started: socket=%s workdir=%s branch=%s",
                  self.socket_path, self.workdir, self.allowed_branch)
        return True

    def _owns_socket_path(self) -> bool:
        """True while the socket file at our path is still the one we bound.

        A daemon that lost its path to another daemon must not unlink the
        replacement's socket or metadata.
        """
        if self._sock_ino is None:
            # We could not stat our own socket at bind time; nothing better
            # to compare against, so keep the historical cleanup behaviour.
            return True
        try:
            return os.stat(self.socket_path).st_ino == self._sock_ino
        except FileNotFoundError:
            return True  # already gone — the unlink below is a no-op
        except OSError:
            return False

    def socket_is_current(self) -> bool:
        """True while the socket at our path is still the one we bound.

        Unlike :meth:`_owns_socket_path` this treats a missing file as "not
        current", which is what the serve and main loops need: both must
        stop when the path is gone *or* has been rebound by another daemon.
        """
        if self._sock_ino is None:
            # Could not stat our own socket at bind time — fall back to the
            # plain existence check the daemon used before inode tracking.
            return os.path.exists(self.socket_path)
        try:
            return os.stat(self.socket_path).st_ino == self._sock_ino
        except OSError:
            return False

    def stop(self) -> None:
        """Stop the proxy and clean up the socket."""
        if self._server_socket is None:
            # start() returned False — another daemon owns this socket.
            return
        self._stop.set()
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        if not self._owns_socket_path():
            _log.info("Push proxy socket replaced by another daemon; "
                      "leaving it in place: %s", self.socket_path)
            return
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        try:
            os.unlink(_metadata_path(self.socket_path))
        except FileNotFoundError:
            pass
        _log.info("Push proxy stopped: %s", self.socket_path)

    def _serve_loop(self) -> None:
        """Accept connections and handle push requests."""
        while not self._stop.is_set():
            # Exit if the socket was removed or replaced by another daemon
            # (different inode).  Checking existence alone would let an
            # orphaned daemon keep running after its path was rebound.
            if not self.socket_is_current():
                _log.info("Push proxy socket removed or replaced, exiting: %s",
                          self.socket_path)
                break
            try:
                conn, _ = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                self._handle_connection(conn)
            except Exception:
                _log.warning("Push proxy: error handling connection",
                             exc_info=True)
            finally:
                conn.close()

    def _handle_connection(self, conn: socket.socket) -> None:
        """Handle a single proxy request (push, fetch, pull, ls-remote)."""
        conn.settimeout(30.0)
        data = b""
        max_request_size = 64 * 1024  # 64 KiB — more than enough for args
        while not data.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > max_request_size:
                response = {"exit_code": 1, "stdout": "",
                            "stderr": "git-proxy: request too large\n"}
                conn.sendall((json.dumps(response) + "\n").encode())
                return

        if not data:
            return

        try:
            request = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            response = {"exit_code": 1, "stdout": "",
                        "stderr": "git-proxy: invalid request format\n"}
            conn.sendall((json.dumps(response) + "\n").encode())
            return

        args = request.get("args", [])
        if (not isinstance(args, list)
                or not all(isinstance(a, str) for a in args)):
            response = {"exit_code": 1, "stdout": "",
                        "stderr": "git-proxy: 'args' must be a list of strings\n"}
            conn.sendall((json.dumps(response) + "\n").encode())
            return

        # Caller's host-side workdir (optional — omitted by legacy wrappers).
        # Each proxy serves exactly one workdir, so a request may only name
        # this proxy's own workdir.  Anything else is rejected explicitly:
        # a failed push must never silently run against another clone.
        # A non-string is always an error, including falsy ones like ``[]``
        # or ``0`` — those must not slip through as "field absent".
        raw_workdir = request.get("workdir")
        if raw_workdir is not None and not isinstance(raw_workdir, str):
            conn.sendall((json.dumps(
                {"exit_code": 1, "stdout": "",
                 "stderr": "git-proxy: 'workdir' must be a string\n"}) + "\n"
            ).encode())
            return
        # An empty string is treated the same as an omitted field.
        caller_workdir: str | None = raw_workdir or None
        if caller_workdir is not None:
            try:
                matches = (os.path.realpath(caller_workdir)
                           == os.path.realpath(self.workdir))
            except (OSError, ValueError):
                matches = False
            if not matches:
                msg = (
                    f"git-proxy: rejected — request workdir "
                    f"'{caller_workdir}' does not match this proxy's "
                    f"workdir '{self.workdir}' (each workdir gets its own "
                    f"proxy)\n"
                )
                _log.warning("Proxy rejected foreign workdir: %s (own=%s)",
                             caller_workdir, self.workdir)
                conn.sendall((json.dumps(
                    {"exit_code": 1, "stdout": "", "stderr": msg}) + "\n"
                ).encode())
                return
            if not os.path.isdir(caller_workdir):
                msg = (
                    f"git-proxy: rejected — request workdir "
                    f"'{caller_workdir}' does not exist on the host\n"
                )
                _log.warning("Proxy rejected missing workdir: %s",
                             caller_workdir)
                conn.sendall((json.dumps(
                    {"exit_code": 1, "stdout": "", "stderr": msg}) + "\n"
                ).encode())
                return

        # Dispatch based on cmd (default "push" for backward compat)
        cmd = request.get("cmd", "push")
        if cmd == "push":
            response = self._execute_push(args, caller_workdir=caller_workdir)
        elif cmd in ("fetch", "pull", "ls-remote"):
            response = self._execute_read_cmd(cmd, args,
                                              caller_workdir=caller_workdir)
        else:
            response = {"exit_code": 1, "stdout": "",
                        "stderr": f"git-proxy: unknown command '{cmd}'\n"}
        conn.sendall((json.dumps(response) + "\n").encode())

    @staticmethod
    def _check_dangerous_flags(args: list[str], cmd_name: str) -> dict | None:
        """Reject flags that could execute arbitrary programs on the host.

        ``--upload-pack``, ``--receive-pack``, and ``--exec`` tell git to
        invoke a user-specified program.  A container could write a script
        to /workspace (bind-mounted rw) and reference it here to escape
        the container sandbox.  Block these unconditionally.

        Returns an error response dict if a dangerous flag is found, or
        None if args are safe.
        """
        for arg in args:
            # Match both --flag=value and --flag (next arg is value)
            stripped = arg.split("=", 1)[0] if "=" in arg else arg
            if stripped in ("--upload-pack", "--receive-pack", "--exec"):
                msg = (f"git-proxy: rejected — '{stripped}' is not allowed "
                       f"in {cmd_name} (security restriction)\n")
                _log.warning("Proxy rejected dangerous flag: %s in %s",
                             stripped, cmd_name)
                return {"exit_code": 1, "stdout": "", "stderr": msg}
        return None

    def _execute_push(self, push_args: list[str],
                      caller_workdir: str | None = None) -> dict:
        """Validate the branch and execute git push on the host."""
        # Reject flags that could execute arbitrary programs on the host
        danger = self._check_dangerous_flags(push_args, "push")
        if danger:
            return danger

        # Reject broad-push flags that bypass branch restrictions
        broad_flags = {"--all", "--mirror", "--tags"}
        for arg in push_args:
            if arg in broad_flags:
                msg = (f"push-proxy: rejected — '{arg}' is not allowed, "
                       f"only single-branch push to '{self.allowed_branch}'\n")
                _log.warning("Push rejected: broad flag %s", arg)
                return {"exit_code": 1, "stdout": "", "stderr": msg}

        # Determine the target branch from the push args
        target_branch = self._extract_target_branch(
            push_args, workdir=caller_workdir or self.workdir)

        if target_branch is None:
            msg = ("push-proxy: rejected — could not determine target branch "
                   f"(only '{self.allowed_branch}' is allowed)\n")
            _log.warning("Push rejected: could not determine target branch")
            return {"exit_code": 1, "stdout": "", "stderr": msg}

        if target_branch != self.allowed_branch:
            msg = (f"push-proxy: rejected — pushing to '{target_branch}' "
                   f"is not allowed, only '{self.allowed_branch}'\n")
            _log.warning("Push rejected: target=%s allowed=%s",
                         target_branch, self.allowed_branch)
            return {"exit_code": 1, "stdout": "", "stderr": msg}

        # Scenario clones have `origin` rewritten to the real upstream
        # URL at clone time, so push runs directly from the caller's
        # clone.  Local-path origins are explicitly rejected: the old
        # fetch-into-target fallback advanced the target's branch ref
        # without touching its worktree, which silently desynced any
        # later commit made there.  Refuse instead of corrupting state.
        workdir = caller_workdir or self.workdir
        remote = self._extract_remote_name(push_args)
        local_target = _resolve_local_remote_url(workdir, remote)

        if local_target is not None:
            msg = (
                f"push-proxy: rejected — caller's '{remote}' resolves to a "
                f"local path ({local_target}). Scenario clones must have "
                f"`origin` set to the real upstream URL before pushing "
                f"(create_scenario_workdir runs `git remote set-url origin "
                f"<real-url>` after the local clone).\n"
            )
            _log.warning("Push rejected: local-path origin %s -> %s",
                         remote, local_target)
            return {"exit_code": 1, "stdout": "", "stderr": msg}

        return self._local_push(push_args, caller_workdir=workdir)

    def _local_push(self, push_args: list[str],
                    caller_workdir: str | None = None) -> dict:
        """Execute the validated push from the caller's clone.

        Scenario clones have ``origin`` set to the real upstream URL,
        so the proxy just runs the literal push from the caller's clone
        — the upstream resolves on its own.  All security checks
        (allowed branch, dangerous flags) ran in ``_execute_push``
        before this is called.
        """
        source = caller_workdir or self.workdir
        cmd = ["git", "-C", source, "push"] + push_args
        _log.info("Push proxy push: %s", cmd)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": 1, "stdout": "",
                    "stderr": "git-proxy: push timed out after 120s\n"}
        except Exception as exc:
            return {"exit_code": 1, "stdout": "",
                    "stderr": f"git-proxy: push failed: {exc}\n"}

    def _execute_read_cmd(self, git_cmd: str, args: list[str],
                          caller_workdir: str | None = None) -> dict:
        """Execute a read-only git remote command (fetch, pull, ls-remote).

        These run from the caller's workdir with no branch restriction.
        The caller's origin already points at the real upstream URL
        (set up at scenario clone time), so the proxy just runs the
        literal args — no remote-chain walking needed.

        Falls back to self.workdir for legacy requests without a workdir field.
        """
        # Reject flags that could execute arbitrary programs on the host
        danger = self._check_dangerous_flags(args, git_cmd)
        if danger:
            return danger

        workdir = caller_workdir or self.workdir
        cmd = ["git", git_cmd] + args
        _log.info("Git proxy executing read cmd: %s (in %s)", cmd, workdir)
        try:
            result = subprocess.run(
                cmd, cwd=workdir,
                capture_output=True, text=True, timeout=120,
            )
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": 1, "stdout": "",
                    "stderr": f"git-proxy: git {git_cmd} timed out after 120s\n"}
        except Exception as exc:
            return {"exit_code": 1, "stdout": "",
                    "stderr": f"git-proxy: {exc}\n"}

    @staticmethod
    def _extract_remote_name(push_args: list[str]) -> str:
        """Extract the remote name from git push arguments (default 'origin')."""
        skip_next = False
        for arg in push_args:
            if skip_next:
                skip_next = False
                continue
            if arg.startswith("-"):
                if arg in ("--repo", "--push-option", "-o",
                           "--receive-pack", "--exec"):
                    skip_next = True
                continue
            # First positional arg is the remote name
            return arg
        return "origin"

    def _extract_target_branch(self, push_args: list[str],
                               workdir: str | None = None) -> str | None:
        """Extract the target branch from git push arguments.

        Returns the branch name, or None if it can't be determined
        (in which case we fall back to current branch check).
        Uses *workdir* (or self.workdir) for HEAD resolution.
        """
        # Skip flags, first positional is remote, second is refspec
        positional: list[str] = []
        skip_next = False
        for arg in push_args:
            if skip_next:
                skip_next = False
                continue
            if arg.startswith("-"):
                # Flags that consume the next arg
                if arg in ("--repo", "--push-option", "-o",
                           "--receive-pack", "--exec"):
                    skip_next = True
                continue
            positional.append(arg)

        if len(positional) >= 2:
            # Reject multiple refspecs — only single-branch push is allowed.
            # git push origin branch1 branch2 would push both; we must not
            # validate only the first and let the rest through.
            if len(positional) > 2:
                return None
            refspec = positional[1]
            # refspec can be "branch", "src:dst", "refs/heads/branch", etc.
            if ":" in refspec:
                dst = refspec.split(":", 1)[1]
            else:
                dst = refspec
            # Strip leading '+' (force-push marker)
            if dst.startswith("+"):
                dst = dst[1:]
            # Strip refs/heads/ prefix
            if dst.startswith("refs/heads/"):
                dst = dst[len("refs/heads/"):]
            # Resolve symbolic refs like HEAD to actual branch name
            _wd = workdir or self.workdir
            if dst == "HEAD":
                try:
                    result = subprocess.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=_wd, capture_output=True, text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        dst = result.stdout.strip()
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    return None
            return dst if dst else None

        # No explicit refspec — check what branch HEAD is on
        _wd = workdir or self.workdir
        if not positional or len(positional) == 1:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=_wd, capture_output=True, text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return result.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        return None


# ---------------------------------------------------------------------------
# Proxy lifecycle helpers (used by container.py)
# ---------------------------------------------------------------------------

# Track running proxies so they can be cleaned up.
#
# Two keying schemes coexist:
#   1. Per-container (legacy): key = container_name
#   2. Shared per (session, PR, workdir): key =
#      "{session_tag}\0{pr_id}\0{workdir_token}"
#      Multiple containers on the same host workdir reference the same
#      proxy via _proxy_refs.  Containers on different workdirs (impl vs a
#      QA scenario clone) get separate proxies so one can never replace or
#      unlink the other's socket.
_active_proxies: dict[str, str] = {}  # key -> socket path
_proxy_lock = threading.Lock()

# For shared proxies: which containers reference each proxy key
_proxy_refs: dict[str, set[str]] = {}
# Reverse lookup: container_name -> proxy key
_container_to_proxy_key: dict[str, str] = {}


def _add_proxy_ref(container_name: str, key: str) -> None:
    """Record that *container_name* uses the proxy for *key*.

    Caller must hold ``_proxy_lock``.  The ref set is *added to*, never
    replaced: a respawned daemon must keep the other containers that share
    the same workdir.  A container references only one proxy at a time, so
    a previous reference under a different key is dropped rather than
    pinned forever (the old daemon itself is left for session teardown,
    like any other unreferenced proxy).
    """
    old = _container_to_proxy_key.get(container_name)
    if old is not None and old != key:
        old_refs = _proxy_refs.get(old)
        if old_refs is not None:
            old_refs.discard(container_name)
            if not old_refs:
                del _proxy_refs[old]
    _proxy_refs.setdefault(key, set()).add(container_name)
    _container_to_proxy_key[container_name] = key


def _workdir_token(workdir: str) -> str:
    """Stable short token identifying a host workdir (symlinks normalised)."""
    real = os.path.realpath(workdir)
    return hashlib.sha256(real.encode("utf-8")).hexdigest()[:16]


def _shared_proxy_key(session_tag: str, pr_id: str,
                      workdir_token: str) -> str:
    """Build the dict key for a shared proxy."""
    return f"{session_tag}\0{pr_id}\0{workdir_token}"


# Unix sockets have a max path length of 107 bytes (+ null terminator).
# With prefix "/tmp/pm-push-proxy-" (19) + "/push.sock" (10) = 29 overhead,
# the dir name portion must be ≤ 78 chars.  Long session tags easily
# exceed this, so we hash when necessary.
def _shared_sock_dir_path(session_tag: str, pr_id: str,
                          workdir_token: str) -> str:
    """Compute the socket directory path without creating anything on disk.

    Returns the short (hashed) path when the readable name would exceed
    the Unix socket 107-byte limit, or the readable path otherwise.
    Pure computation — no filesystem side effects.
    """
    long_name = f"{session_tag}-{pr_id}-{workdir_token}"
    long_dir = f"/tmp/{_SOCKET_DIR_PREFIX}{long_name}"
    sock_in_long = f"{long_dir}/push.sock"

    if len(sock_in_long) <= 107:
        return long_dir

    dir_hash = hashlib.sha256(long_name.encode()).hexdigest()[:16]
    return f"/tmp/{_SOCKET_DIR_PREFIX}{dir_hash}"


def _shared_sock_dir(session_tag: str, pr_id: str,
                     workdir_token: str) -> str:
    """Build a socket directory path and create it on disk.

    Like :func:`_shared_sock_dir_path` but also creates the directory
    and a long-named symlink for discoverability/cleanup.  Use this
    when starting a proxy; use ``_shared_sock_dir_path`` for read-only
    lookups.
    """
    long_name = f"{session_tag}-{pr_id}-{workdir_token}"
    long_dir = f"/tmp/{_SOCKET_DIR_PREFIX}{long_name}"
    short_dir = _shared_sock_dir_path(session_tag, pr_id, workdir_token)

    if short_dir == long_dir:
        # Fits — no hash needed, no symlink needed
        return long_dir

    os.makedirs(short_dir, exist_ok=True)

    # Create long-named symlink for discoverability/cleanup
    try:
        os.symlink(short_dir, long_dir)
    except FileExistsError:
        # If it's a stale real directory, replace with symlink
        if os.path.isdir(long_dir) and not os.path.islink(long_dir):
            import shutil
            shutil.rmtree(long_dir, ignore_errors=True)
            try:
                os.symlink(short_dir, long_dir)
            except FileExistsError:
                pass  # race — another process created it
    return short_dir


@contextlib.contextmanager
def _start_lock(sock_dir: str, blocking: bool = True):
    """Serialise check-and-spawn across processes for one socket directory.

    The lock file sits *next to* the directory (not inside it) so it never
    keeps a bind-mounted directory from being removed at session teardown.

    Yields True when the lock was taken.  With ``blocking=False`` the lock
    is only attempted (``LOCK_NB``): on contention the context yields False
    immediately, so teardown can skip a directory that a proxy start is
    using right now instead of stalling behind it.
    """
    os.makedirs(sock_dir, exist_ok=True)
    lock_path = os.path.realpath(sock_dir) + ".lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        try:
            fcntl.flock(fd, flags)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _clear_lock_file(path: str) -> None:
    """Unlink a start-lock file, unless a process is holding it right now.

    Deleting a lock file that another process has flocked would let a third
    process create a fresh one and bypass the cross-process serialisation
    in :func:`_start_lock`.
    """
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return  # in use — its owner (or a later teardown) clears it
        try:
            os.unlink(path)
        except OSError:
            pass
    finally:
        os.close(fd)


def _start_proxy_subprocess(sock_path: str, workdir: str,
                            allowed_branch: str) -> bool:
    """Spawn a push proxy as an independent subprocess that outlives the caller.

    Returns True once the socket is connectable, False if it never became
    ready within the wait window.
    """
    import sys

    proc = subprocess.Popen(
        [sys.executable, "-m", "pm_core.push_proxy",
         sock_path, workdir, allowed_branch],
        start_new_session=True,  # detach from parent process group
        # Redirect stdin too: when spawned from a tmux popup (`display-popup
        # -E pm _popup-cmd ...`), an inherited pty FD keeps the popup
        # overlay open for the lifetime of this daemon.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for the socket to appear and become connectable.  Five seconds
    # covers a slow fork/import without leaving a broken container behind.
    for _ in range(50):
        if os.path.exists(sock_path) and proxy_is_alive(sock_path):
            _log.info("Push proxy subprocess started: pid=%d socket=%s "
                      "workdir=%s branch=%s",
                      proc.pid, sock_path, workdir, allowed_branch)
            return True
        time.sleep(0.1)
    _log.warning("Push proxy subprocess (pid=%d) did not become ready "
                 "at %s within 5s", proc.pid, sock_path)
    return False


def start_push_proxy(container_name: str, workdir: str,
                     allowed_branch: str,
                     session_tag: str | None = None,
                     pr_id: str | None = None) -> str:
    """Start a push proxy for a container.

    When *session_tag* and *pr_id* are both provided the proxy is shared
    per ``(session_tag, pr_id, workdir)``: the socket lives at a
    deterministic path
    ``/tmp/pm-push-proxy-{session_tag}-{pr_id}-{workdir_token}/push.sock``.
    Containers on the same host workdir reuse the existing proxy; a
    container on a different workdir (e.g. a QA scenario clone) gets its
    own.  A live proxy serving a different workdir/branch is never
    replaced — :class:`PushProxyConflict` is raised instead.

    Without *session_tag*/*pr_id* a per-container proxy with a
    deterministic temp directory is created (legacy behaviour).

    Args:
        container_name: Container name (used for reference tracking).
        workdir: Host path to the git working directory.
        allowed_branch: Only allow pushes to this branch.
        session_tag: Session tag for proxy sharing.
        pr_id: PR identifier for proxy sharing.

    Returns:
        Host path to the Unix socket (to be mounted into the container).

    Raises:
        PushProxyConflict: A live proxy at the target path serves a
            different workdir or allowed branch.
        PushProxyError: The daemon did not become ready.
    """
    shared = session_tag is not None and pr_id is not None

    if shared:
        token = _workdir_token(workdir)
        key = _shared_proxy_key(session_tag, pr_id, token)
        sock_dir = _shared_sock_dir(session_tag, pr_id, token)
        sock_path = os.path.join(sock_dir, "push.sock")

        # Serialise check-and-spawn across processes: two containers on the
        # same workdir must not race unlink→bind and kill each other.
        with _start_lock(sock_dir):
            # Reuse if an existing proxy is alive on this socket
            if os.path.exists(sock_path) and proxy_is_alive(sock_path):
                meta = _read_metadata(sock_path)
                if meta:
                    meta_workdir = meta.get("workdir")
                    meta_branch = meta.get("allowed_branch")
                    if (meta_workdir
                            and os.path.realpath(str(meta_workdir))
                            != os.path.realpath(workdir)):
                        raise PushProxyConflict(
                            f"live push proxy at {sock_path} serves workdir "
                            f"'{meta_workdir}', not requested '{workdir}'")
                    if meta_branch and meta_branch != allowed_branch:
                        raise PushProxyConflict(
                            f"live push proxy at {sock_path} allows branch "
                            f"'{meta_branch}', not requested "
                            f"'{allowed_branch}'")
                with _proxy_lock:
                    _add_proxy_ref(container_name, key)
                _log.info("Reusing live shared push proxy for %s "
                          "(container %s)", key, container_name)
                return sock_path

            # Socket missing or dead — spawn a new subprocess proxy *in the
            # same directory*.  Docker creates a *directory* when
            # bind-mounting a non-existent socket path, so handle both
            # files and directories left over from old runs.
            try:
                os.unlink(sock_path)
            except IsADirectoryError:
                import shutil
                shutil.rmtree(sock_path, ignore_errors=True)
            except FileNotFoundError:
                pass

            if not _start_proxy_subprocess(sock_path, workdir, allowed_branch):
                raise PushProxyError(
                    f"push proxy did not become ready at {sock_path} "
                    f"(workdir={workdir}, branch={allowed_branch})")

            with _proxy_lock:
                # Add, don't replace: other containers on this workdir keep
                # their reference to the proxy we just respawned.
                _add_proxy_ref(container_name, key)

            return sock_path

    # Legacy per-container proxy
    import tempfile
    # Use a deterministic path based on the container name so the
    # socket can be found after a TUI restart without a registry.
    sock_dir = os.path.join(tempfile.gettempdir(),
                            f"{_SOCKET_DIR_PREFIX}{container_name}")
    os.makedirs(sock_dir, exist_ok=True)
    sock_path = os.path.join(sock_dir, "push.sock")
    with _start_lock(sock_dir):
        # Remove stale socket before spawning (see above for why we handle
        # IsADirectoryError).
        try:
            os.unlink(sock_path)
        except IsADirectoryError:
            import shutil
            shutil.rmtree(sock_path, ignore_errors=True)
        except FileNotFoundError:
            pass

        if not _start_proxy_subprocess(sock_path, workdir, allowed_branch):
            raise PushProxyError(
                f"push proxy did not become ready at {sock_path} "
                f"(workdir={workdir}, branch={allowed_branch})")

    with _proxy_lock:
        _active_proxies[container_name] = sock_path
        _container_to_proxy_key[container_name] = container_name

    return sock_path


def _kill_proxy_socket(sock_path: str, remove_dir: bool = True,
                       lock_held: bool = False) -> None:
    """Stop a subprocess proxy by removing its socket (triggers exit).

    When *remove_dir* is False the socket directory is kept.  Shared
    proxies use that mode: a container may still bind-mount the
    directory, and deleting it would leave the container pointing at a
    dead inode (restarting the daemon alone cannot heal that).

    *lock_held* says the caller holds the directory's start lock, which
    makes clearing that lock file safe even though it is flocked.

    Callers reach this with paths built from a key (safe) and from a glob
    over ``/tmp`` (not safe): a planted ``/tmp/pm-push-proxy-…`` symlink
    would otherwise make teardown unlink ``push.sock``/``proxy.json``
    inside whatever directory it points at.  Only paths that resolve to a
    proxy socket directory directly under the glob's parent are touched;
    a foreign link is unlinked, its target is left alone.
    """
    sock_dir = str(Path(sock_path).parent)
    parent = os.path.realpath(os.path.dirname(sock_dir))
    # Resolve the real directory if sock_dir is a symlink
    real_dir = os.path.realpath(sock_dir)
    if not _is_proxy_dir(real_dir, parent):
        _log.warning("Refusing to stop proxy through non-proxy directory "
                     "%s -> %s", sock_dir, real_dir)
        if os.path.islink(sock_dir):
            try:
                os.unlink(sock_dir)
            except OSError:
                pass
        return
    try:
        if os.stat(real_dir).st_uid != os.getuid():
            # /tmp is world-writable: anyone can plant a directory with a
            # proxy-shaped name.  Leave it alone (its unlink would fail
            # with EPERM and abort the whole teardown sweep).
            _log.warning("Refusing to stop proxy in a directory owned by "
                         "another user: %s", real_dir)
            return
    except OSError:
        pass  # already gone — the unlinks below are no-ops
    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass
    except IsADirectoryError:
        # Docker creates a *directory* at a bind-mounted socket path that
        # did not exist (older pm versions mounted the socket file itself).
        import shutil
        shutil.rmtree(sock_path, ignore_errors=True)
    # Metadata describes the daemon we just stopped.
    try:
        os.unlink(os.path.join(real_dir, _METADATA_NAME))
    except OSError:
        pass
    if not remove_dir:
        return
    # Clean up the symlink if sock_dir is one
    if os.path.islink(sock_dir):
        try:
            os.unlink(sock_dir)
        except OSError:
            pass
    # Clean up the real directory and its start lock
    try:
        os.rmdir(real_dir)
    except OSError:
        pass
    if lock_held:
        # The caller holds this directory's start lock, so no other process
        # can be using it — unlinking it here is safe (and necessary: the
        # probe in _clear_lock_file would see our own lock and skip).
        try:
            os.unlink(real_dir + ".lock")
        except OSError:
            pass
    else:
        _clear_lock_file(real_dir + ".lock")


def stop_push_proxy(container_name: str) -> None:
    """Stop and clean up the push proxy for a container.

    For shared proxies the proxy is only stopped when the last container
    referencing it is removed, and the socket *directory* is kept so any
    container still bind-mounting it survives (a later start recreates the
    socket in place).  Session teardown removes the directories.
    """
    with _proxy_lock:
        key = _container_to_proxy_key.pop(container_name, None)
        if key is None:
            return

        shared = "\0" in key
        # Shared proxy path — decrement refcount
        if shared:
            refs = _proxy_refs.get(key)
            if refs is not None:
                refs.discard(container_name)
                if refs:
                    return  # Other containers still using this proxy
                del _proxy_refs[key]

        _active_proxies.pop(key, None)

    # Derive the socket path from the key and remove it to stop the
    # subprocess proxy (the __main__ loop exits when socket disappears).
    if shared:
        parts = key.split("\0")
        if len(parts) != 3:
            return  # malformed key — nothing safe to derive
        stag, pid, token = parts
        sock_dir = _shared_sock_dir_path(stag, pid, token)
        sock_path = os.path.join(sock_dir, "push.sock")
        _kill_proxy_socket(sock_path, remove_dir=False)
    else:
        # Legacy key = container_name
        import tempfile
        sock_path = os.path.join(tempfile.gettempdir(),
                                 f"{_SOCKET_DIR_PREFIX}{key}",
                                 "push.sock")
        _kill_proxy_socket(sock_path, remove_dir=True)


def _is_proxy_dir(path: str, parent: str) -> bool:
    """True when *path* is a proxy socket directory directly under *parent*.

    Guards the recursive delete in :func:`_remove_proxy_dirs`: ``/tmp`` is
    world-writable, so a planted ``/tmp/pm-push-proxy-…`` symlink must never
    make teardown delete an unrelated directory.
    """
    return (os.path.dirname(path) == parent
            and os.path.basename(path).startswith(_SOCKET_DIR_PREFIX))


def _remove_proxy_dirs(glob_pattern: str) -> None:
    """Remove socket directories (and symlinks/locks) matching *glob_pattern*.

    Only paths that resolve to a proxy socket directory are removed; a
    symlink pointing anywhere else is unlinked but its target is left alone.
    Directories owned by another user are left alone too — ``/tmp`` is
    world-writable, so anyone can create a matching name there.

    A directory whose proxy is alive, or whose start lock is held by a
    proxy start in flight, is left in place: removing it would delete a
    socket a container still bind-mounts.
    """
    import glob as _glob
    import shutil
    parent = os.path.dirname(glob_pattern)
    for path in _glob.glob(glob_pattern):
        if path.endswith(".lock"):
            continue
        real = os.path.realpath(path)
        if os.path.islink(path):
            try:
                os.unlink(path)
            except OSError:
                pass
        if not _is_proxy_dir(real, parent):
            _log.warning("Refusing to remove non-proxy directory %s -> %s",
                         path, real)
            continue
        try:
            if os.stat(real).st_uid != os.getuid():
                _log.warning("Refusing to remove proxy directory owned by "
                             "another user: %s", real)
                continue
        except FileNotFoundError:
            pass  # already gone — still clear a leftover lock below
        except OSError:
            continue
        if not os.path.isdir(real):
            _clear_lock_file(real + ".lock")
            continue
        with _start_lock(real, blocking=False) as locked:
            if not locked:
                _log.info("Proxy directory busy (start in flight); leaving "
                          "it in place: %s", real)
                continue
            if proxy_is_alive(os.path.join(real, "push.sock")):
                _log.info("Leaving live proxy directory in place: %s", real)
                continue
            shutil.rmtree(real, ignore_errors=True)
            # Safe: we hold the lock, so no other process is using it.
            try:
                os.unlink(real + ".lock")
            except OSError:
                pass
    for lock in _glob.glob(glob_pattern + ".lock"):
        _clear_lock_file(lock)


def stop_all_proxies() -> None:
    """Stop all running push proxies."""
    import glob as _glob
    with _proxy_lock:
        _active_proxies.clear()
        _proxy_refs.clear()
        _container_to_proxy_key.clear()

    # Kill all proxy sockets on disk
    for sock in _glob.glob(f"/tmp/{_SOCKET_DIR_PREFIX}*/push.sock"):
        _kill_proxy_socket(sock)
    _remove_proxy_dirs(f"/tmp/{_SOCKET_DIR_PREFIX}*")


def stop_session_proxies(session_tag: str) -> int:
    """Stop all push proxies belonging to a session.

    Returns the number of proxies stopped.
    """
    import glob as _glob
    prefix = f"{session_tag}\0"
    with _proxy_lock:
        keys_to_remove = {
            k for k in list(_active_proxies) + list(_proxy_refs)
            if k.startswith(prefix)
        }
        for k in keys_to_remove:
            _active_proxies.pop(k, None)
            for cname in _proxy_refs.pop(k, set()):
                _container_to_proxy_key.pop(cname, None)

    # Kill sockets matching the session tag.  Skip a directory whose start
    # lock is held: a container is creating that proxy right now, and the
    # dir sweep below will leave it for the next teardown.
    count = 0
    for sock in _glob.glob(f"/tmp/{_SOCKET_DIR_PREFIX}{session_tag}-*/push.sock"):
        with _start_lock(os.path.dirname(sock), blocking=False) as locked:
            if not locked:
                _log.info("Session proxy start in flight; not stopping: %s",
                          sock)
                continue
            _kill_proxy_socket(sock, lock_held=True)
            count += 1

    # Remove directories even when their socket was already stopped (shared
    # stops keep the directory for live container mounts).
    _remove_proxy_dirs(f"/tmp/{_SOCKET_DIR_PREFIX}{session_tag}-*")

    if count:
        _log.info("Stopped %d session proxy(ies) for %s", count, session_tag)
    return count


def proxy_is_alive(sock_path: str) -> bool:
    """Test whether a push proxy socket is actually accepting connections."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(sock_path)
        s.close()
        return True
    except (OSError, socket.timeout):
        return False


def get_proxy_socket_path(container_name: str,
                          session_tag: str | None = None,
                          pr_id: str | None = None,
                          workdir: str | None = None) -> str | None:
    """Return the host socket path for a container's push proxy, or None.

    Uses the deterministic path convention so this works even after a
    TUI restart (no in-memory state needed).  Always returns the real
    (resolved) path so callers can ``connect()`` without hitting the
    Unix socket 107-byte path limit.

    Pass *workdir* (with *session_tag* and *pr_id*) for the restart-safe
    lookup; without it the in-memory registry is consulted, which is
    enough within the process that started the proxy.
    """
    import tempfile

    def _resolve(path: str) -> str | None:
        """Return the realpath if the socket exists, else None."""
        if os.path.exists(path):
            return os.path.realpath(path)
        return None

    # Try shared proxy path first (session_tag + pr_id + workdir)
    if session_tag and pr_id and workdir:
        token = _workdir_token(workdir)
        shared_dir = _shared_sock_dir_path(session_tag, pr_id, token)
        result = _resolve(os.path.join(shared_dir, "push.sock"))
        if result:
            return result
        # Also check the long-named symlink path
        long_path = os.path.join(
            tempfile.gettempdir(),
            f"{_SOCKET_DIR_PREFIX}{session_tag}-{pr_id}-{token}",
            "push.sock",
        )
        result = _resolve(long_path)
        if result:
            return result

    # In-memory registry — derive the path from the key
    with _proxy_lock:
        key = _container_to_proxy_key.get(container_name)
    if key is not None:
        if "\0" in key:
            parts = key.split("\0")
            if len(parts) == 3:
                derived_dir = _shared_sock_dir_path(*parts)
                result = _resolve(os.path.join(derived_dir, "push.sock"))
                if result:
                    return result
        else:
            legacy = os.path.join(tempfile.gettempdir(),
                                  f"{_SOCKET_DIR_PREFIX}{key}",
                                  "push.sock")
            result = _resolve(legacy)
            if result:
                return result

    # Try legacy per-container path
    sock_path = os.path.join(tempfile.gettempdir(),
                             f"{_SOCKET_DIR_PREFIX}{container_name}",
                             "push.sock")
    return _resolve(sock_path)


def container_socket_path() -> str:
    """Return the fixed socket path inside the container."""
    return _CONTAINER_SOCKET_PATH


def _wait_for_socket_exit(proxy: PushProxy, stop_event: threading.Event,
                          interval: float = 2.0) -> None:
    """Block the daemon until its socket is removed/replaced or signalled.

    The serve thread exits on its own when the path is unlinked or rebound,
    but the process must exit too — otherwise a daemon whose socket another
    daemon took over lingers forever holding no socket at all.
    """
    while not stop_event.is_set():
        if not proxy.socket_is_current():
            break
        stop_event.wait(interval)


# ---------------------------------------------------------------------------
# Standalone entry point: python -m pm_core.push_proxy <sock> <workdir> <branch>
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys

    if len(_sys.argv) != 4:
        print(f"Usage: {_sys.argv[0]} <socket_path> <workdir> <allowed_branch>",
              file=_sys.stderr)
        _sys.exit(1)

    _sock, _workdir, _branch = _sys.argv[1], _sys.argv[2], _sys.argv[3]
    proxy = PushProxy(_sock, _workdir, _branch)
    if not proxy.start():
        # Another daemon already serves this socket; do not steal it.
        _sys.exit(0)

    # Block until the socket is removed/replaced or we get a signal
    import signal as _signal
    _stop = threading.Event()
    _signal.signal(_signal.SIGTERM, lambda *_: _stop.set())
    _signal.signal(_signal.SIGINT, lambda *_: _stop.set())
    _wait_for_socket_exit(proxy, _stop)
    proxy.stop()
