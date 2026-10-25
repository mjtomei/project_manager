"""Host-side git remote proxy for containerised sessions.

Containers must not hold git credentials directly.  Each container gets a
proxy socket mounted into it.  A git wrapper inside the container intercepts
remote-interacting commands (``push``, ``fetch``, ``pull``, ``ls-remote``)
and forwards them to the proxy.

The proxy:
  1. Validates push targets against the allowed branch for that container
  2. Executes the real git command on the host (where credentials live)
  3. For local-path origins (``git clone --local`` clones), handles push
     via ``git fetch`` from the target side to avoid ``denyCurrentBranch``
  4. Streams back exit code, stdout, and stderr transparently

When multiple QA scenario containers share a proxy (same session + PR), each
container's git wrapper includes its host-side clone path in the request as
``"workdir"``.  The proxy uses this path as the source for push and the target
for fetch/pull, falling back to ``self.workdir`` for legacy requests that omit
the field.

Protocol (newline-delimited JSON over Unix socket):
  Request:  {"cmd": "push|fetch|pull|ls-remote", "args": ["origin", "branch"],
             "workdir": "/host/path/to/clone"}
  Response: {"exit_code": 0, "stdout": "...", "stderr": "..."}

Legacy requests without ``cmd`` are treated as push (backward compat).
``"workdir"`` is optional; omitting it falls back to ``self.workdir``.
"""

import contextlib
import hashlib
import json
import os
import socket
import subprocess
import threading
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.push_proxy")

_SOCKET_DIR_PREFIX = "pm-push-proxy-"
_CONTAINER_SOCKET_DIR = "/run/pm-push-proxy"
_CONTAINER_SOCKET_PATH = f"{_CONTAINER_SOCKET_DIR}/push.sock"


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


@contextlib.contextmanager
def _socket_lifecycle_lock(socket_path: str):
    """Serialize bind/unlink, including late shutdown in an old daemon."""
    from pm_core.container import ContainerError, _file_lock
    key = hashlib.sha256(os.path.realpath(socket_path).encode()).hexdigest()
    with _file_lock(f"proxy-socket-{key}", timeout=10) as locked:
        if not locked:
            raise ContainerError(f"Push proxy socket lifecycle lock unavailable: {socket_path}")
        yield


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
        self._socket_identity: tuple[int, int, int] | None = None

    def owns_socket(self) -> bool:
        """Whether the published pathname still addresses this daemon's socket."""
        try:
            current = os.stat(self.socket_path)
        except OSError:
            return False
        return self._socket_identity == (current.st_dev, current.st_ino, current.st_ctime_ns)

    def start(self) -> None:
        """Start the proxy in a background daemon thread."""
        with _socket_lifecycle_lock(self.socket_path):
            Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass

            self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server_socket.bind(self.socket_path)
            # Make socket world-writable so the container user can connect
            os.chmod(self.socket_path, 0o777)
            identity = os.stat(self.socket_path)
            self._socket_identity = (identity.st_dev, identity.st_ino, identity.st_ctime_ns)
            self._server_socket.listen(1)
            self._server_socket.settimeout(2.0)

        self._thread = threading.Thread(
            target=self._serve_loop, daemon=True,
            name=f"push-proxy-{Path(self.socket_path).stem}",
        )
        self._thread.start()
        _log.info("Push proxy started: socket=%s branch=%s",
                  self.socket_path, self.allowed_branch)

    def stop(self) -> None:
        """Stop the proxy and clean up the socket."""
        self._stop.set()
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        with _socket_lifecycle_lock(self.socket_path):
            if self.owns_socket():
                try:
                    os.unlink(self.socket_path)
                except FileNotFoundError:
                    pass
        _log.info("Push proxy stopped: %s", self.socket_path)

    def _serve_loop(self) -> None:
        """Accept connections and handle push requests."""
        while not self._stop.is_set():
            # A replacement can bind between polls without a missing-path
            # observation. Retire this daemon on identity change as well.
            if not self.owns_socket():
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
        # When present, used as the source for push and the target for
        # fetch/pull instead of self.workdir (which is only correct for the
        # first scenario that started the proxy).
        caller_workdir: str | None = request.get("workdir") or None

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
#   2. Shared per (session, branch): key = "{session_tag}\0{pr_id}"
#      Multiple containers reference the same proxy via _proxy_refs.
_active_proxies: dict[str, str] = {}  # key -> socket path
_proxy_lock = threading.Lock()

# For shared proxies: which containers reference each proxy key
_proxy_refs: dict[str, set[str]] = {}
# Reverse lookup: container_name -> proxy key
_container_to_proxy_key: dict[str, str] = {}


def _shared_proxy_key(session_tag: str, pr_id: str) -> str:
    """Build the dict key for a shared proxy."""
    return f"{session_tag}\0{pr_id}"


# Unix sockets have a max path length of 107 bytes (+ null terminator).
# With prefix "/tmp/pm-push-proxy-" (19) + "/push.sock" (10) = 29 overhead,
# the dir name portion must be ≤ 78 chars.  Long session tags easily
# exceed this, so we hash when necessary.
def _shared_sock_dir_path(session_tag: str, pr_id: str) -> str:
    """Compute the socket directory path without creating anything on disk.

    Returns the short (hashed) path when the readable name would exceed
    the Unix socket 107-byte limit, or the readable path otherwise.
    Pure computation — no filesystem side effects.
    """
    long_name = f"{session_tag}-{pr_id}"
    long_dir = f"/tmp/{_SOCKET_DIR_PREFIX}{long_name}"
    sock_in_long = f"{long_dir}/push.sock"

    if len(sock_in_long) <= 107:
        return long_dir

    import hashlib
    dir_hash = hashlib.sha256(long_name.encode()).hexdigest()[:16]
    return f"/tmp/{_SOCKET_DIR_PREFIX}{dir_hash}"


def _shared_sock_dir(session_tag: str, pr_id: str) -> str:
    """Build a socket directory path and create it on disk.

    Like :func:`_shared_sock_dir_path` but also creates the directory
    and a long-named symlink for discoverability/cleanup.  Use this
    when starting a proxy; use ``_shared_sock_dir_path`` for read-only
    lookups.
    """
    long_name = f"{session_tag}-{pr_id}"
    long_dir = f"/tmp/{_SOCKET_DIR_PREFIX}{long_name}"
    short_dir = _shared_sock_dir_path(session_tag, pr_id)

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


def _start_proxy_subprocess(sock_path: str, workdir: str,
                            allowed_branch: str) -> None:
    """Spawn a push proxy as an independent subprocess that outlives the caller."""
    import sys
    import time

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

    # Wait briefly for the socket to appear and become connectable
    for _ in range(30):
        if os.path.exists(sock_path) and proxy_is_alive(sock_path):
            break
        time.sleep(0.1)
    else:
        _log.warning("Push proxy subprocess (pid=%d) did not become ready "
                     "at %s within 3s", proc.pid, sock_path)
    _log.info("Push proxy subprocess started: pid=%d socket=%s branch=%s",
              proc.pid, sock_path, allowed_branch)


def start_push_proxy(container_name: str, workdir: str,
                     allowed_branch: str,
                     session_tag: str | None = None,
                     pr_id: str | None = None) -> str:
    """Start a push proxy for a container.

    When *session_tag* and *pr_id* are both provided the proxy is shared:
    only one proxy runs per unique ``(session_tag, pr_id)`` pair and its
    socket lives at a deterministic path
    ``/tmp/pm-push-proxy-{session_tag}-{pr_id}/push.sock``.  Additional
    containers on the same branch reuse the existing proxy.

    Without *session_tag*/*pr_id* a per-container proxy with a random
    temp directory is created (legacy behaviour).

    Args:
        container_name: Container name (used for reference tracking).
        workdir: Host path to the git working directory.
        allowed_branch: Only allow pushes to this branch.
        session_tag: Session tag for proxy sharing.
        pr_id: PR identifier for proxy sharing.

    Returns:
        Host path to the Unix socket (to be mounted into the container).
    """
    shared = session_tag is not None and pr_id is not None

    if shared:
        key = _shared_proxy_key(session_tag, pr_id)
        sock_dir = _shared_sock_dir(session_tag, pr_id)
        sock_path = os.path.join(sock_dir, "push.sock")

        # A dead socket may still be mounted by another runtime's containers.
        # Do not overwrite its ownership record while repairing our own proxy.
        if not _owner_domain_matches(sock_dir):
            from pm_core.container import ContainerError
            raise ContainerError("Existing shared push proxy belongs to a different or "
                                 "unverifiable runtime; refusing cross-runtime reuse")
        # Reuse if an existing proxy is alive on this socket
        if os.path.exists(sock_path) and proxy_is_alive(sock_path):
            # Do not attribute an existing socket to this runtime: it may
            # have been started by a different daemon or rootless store.
            with _proxy_lock:
                _proxy_refs.setdefault(key, set()).add(container_name)
                _container_to_proxy_key[container_name] = key
            _log.info("Reusing live shared push proxy for %s (container %s)",
                      key, container_name)
            return sock_path

        # Socket missing or dead — spawn a new subprocess proxy
        os.makedirs(sock_dir, exist_ok=True)
        # Remove stale socket before spawning.  Docker creates a
        # *directory* when bind-mounting a non-existent socket path, so
        # handle both files and directories left over from old runs.
        with _socket_lifecycle_lock(sock_path):
            try:
                os.unlink(sock_path)
            except IsADirectoryError:
                import shutil
                shutil.rmtree(sock_path, ignore_errors=True)
            except FileNotFoundError:
                pass

        _start_proxy_subprocess(sock_path, workdir, allowed_branch)
        _write_owner_file(sock_dir, session_tag, pr_id, workdir)

        with _proxy_lock:
            _proxy_refs[key] = {container_name}
            _container_to_proxy_key[container_name] = key

        return sock_path

    # Legacy per-container proxy
    import tempfile
    # Use a deterministic path based on the container name so the
    # socket can be found after a TUI restart without a registry.
    sock_dir = os.path.join(tempfile.gettempdir(),
                            f"{_SOCKET_DIR_PREFIX}{container_name}")
    os.makedirs(sock_dir, exist_ok=True)
    sock_path = os.path.join(sock_dir, "push.sock")
    # Remove stale socket before spawning (see above for why we handle
    # IsADirectoryError).
    with _socket_lifecycle_lock(sock_path):
        try:
            os.unlink(sock_path)
        except IsADirectoryError:
            import shutil
            shutil.rmtree(sock_path, ignore_errors=True)
        except FileNotFoundError:
            pass

    _start_proxy_subprocess(sock_path, workdir, allowed_branch)

    with _proxy_lock:
        _active_proxies[container_name] = sock_path
        _container_to_proxy_key[container_name] = container_name

    return sock_path


def _kill_proxy_socket(sock_path: str) -> None:
    """Stop a subprocess proxy by removing its socket (triggers exit) and clean up."""
    with _socket_lifecycle_lock(sock_path):
        sock_dir = str(Path(sock_path).parent)
        # Resolve the real directory if sock_dir is a symlink
        real_dir = os.path.realpath(sock_dir)
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass
        # Clean up the symlink if sock_dir is one
        if os.path.islink(sock_dir):
            try:
                os.unlink(sock_dir)
            except OSError:
                pass
        # Clean up the real directory
        try:
            os.rmdir(real_dir)
        except OSError:
            pass


_OWNER_FILE = "owner.json"


def runtime_domain() -> dict | None:
    """Identify the runtime storage this process can actually inventory.

    An empty inventory is meaningful only for proxies created in this domain.
    Legacy owners or unavailable runtime info must never authorize a sweep.
    """
    from pm_core import container as cm
    try:
        result = cm._run_runtime("info", "--format", "{{json .}}",
                                 check=False, timeout=10)
        if result.returncode != 0:
            return None
        info = json.loads(result.stdout)
        runtime = cm._get_runtime()
        if "podman" in runtime:
            store = info.get("store") or info.get("Store") or {}
            host = info.get("host") or info.get("Host") or {}
            graph = store.get("graphRoot") or store.get("GraphRoot")
            run = store.get("runRoot") or store.get("RunRoot")
            hostname = host.get("hostname") or host.get("Hostname")
            if not (graph and run and hostname):
                return None
            return {"runtime": "podman", "graph_root": graph, "run_root": run,
                    "hostname": hostname,
                    "endpoint": os.environ.get("CONTAINER_HOST", ""),
                    "connection": os.environ.get("CONTAINER_CONNECTION", "")}
        daemon = info.get("ID") or info.get("Id")
        return {"runtime": "docker", "daemon_id": daemon} if daemon else None
    except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError, TypeError):
        return None


def _owner_domain_matches(sock_dir: str) -> bool:
    """Known foreign domains cannot share or release one another's sockets."""
    try:
        owner = json.loads(Path(sock_dir, _OWNER_FILE).read_text())
    except (OSError, ValueError):
        return True  # legacy direct lifecycle behavior
    domain = owner.get("runtime_domain") if isinstance(owner, dict) else None
    if domain is None:
        return True
    return domain == runtime_domain()


def _write_owner_file(sock_dir: str, session_tag: str, pr_id: str,
                      workdir: str) -> None:
    """Record which (session, PR) a shared proxy dir serves.

    Hashed socket dirs can't be mapped back to their tag/PR by name; the
    reaper reads this to decide whether any container still needs the proxy.
    """
    try:
        Path(sock_dir, _OWNER_FILE).write_text(json.dumps(
            {"session_tag": session_tag, "pr_id": pr_id, "workdir": workdir,
             "runtime_domain": runtime_domain()}))
    except OSError:
        _log.debug("could not write proxy owner file in %s", sock_dir,
                   exc_info=True)


def list_shared_proxies() -> list[dict]:
    """Shared proxy socket dirs on disk: ``[{session_tag, pr_id, sock_path}]``.

    Entries whose owner can't be determined are skipped (left alone).
    """
    import glob as _glob
    import re
    out: list[dict] = []
    seen: set[str] = set()
    for d in sorted(_glob.glob(f"/tmp/{_SOCKET_DIR_PREFIX}*")):
        real = os.path.realpath(d)
        if real in seen or not os.path.isdir(real):
            continue
        owner = None
        try:
            owner = json.loads(Path(real, _OWNER_FILE).read_text())
        except (OSError, ValueError):
            # Legacy dir without owner file: only the readable long name
            # (the dir itself, or the symlink to a hashed dir) says whose it
            # is.  A per-container proxy dir (``pm-push-proxy-<container
            # name>``, e.g. an untagged ``pm-impl-pr-…``) has the same shape
            # but serves only its own container — never treat it as shared.
            from pm_core.container import parse_container_name
            base = os.path.basename(d)
            if parse_container_name(base[len(_SOCKET_DIR_PREFIX):]) is None:
                m = re.match(rf"{re.escape(_SOCKET_DIR_PREFIX)}(.+)-(pr-[0-9a-f]+)$",
                             base)
                if m:
                    owner = {"session_tag": m.group(1), "pr_id": m.group(2)}
        if not isinstance(owner, dict) or not owner.get("session_tag") or not owner.get("pr_id"):
            continue
        seen.add(real)
        out.append({"session_tag": owner["session_tag"],
                    "pr_id": owner["pr_id"],
                    "sock_path": os.path.join(real, "push.sock"),
                    "runtime_domain": owner.get("runtime_domain")})
    return out


def release_proxy_if_unused(session_tag: str, pr_id: str,
                            exclude: "set[str] | frozenset[str]" = frozenset()
                            ) -> bool | None:
    """Stop the shared (session, PR) proxy if no container still uses it.

    The decision comes from the container runtime (any container, any
    state, any pm process), checked under the cross-process proxy lock that
    ``create_container`` holds from proxy start until its container exists —
    so a concurrent launch can't lose its proxy.  Returns True when stopped,
    False when still in use (or the lock is busy), None when the runtime
    couldn't be queried (nothing done).
    """
    from pm_core import container as container_mod
    with container_mod.proxy_lock(session_tag, pr_id, timeout=30) as locked:
        if not locked:
            return False
        if not _owner_domain_matches(_shared_sock_dir_path(session_tag, pr_id)):
            return False
        users = container_mod.containers_for_pr(session_tag, pr_id)
        if users is None:
            return None
        if users - set(exclude):
            return False
        key = _shared_proxy_key(session_tag, pr_id)
        with _proxy_lock:
            for cname in _proxy_refs.pop(key, set()):
                _container_to_proxy_key.pop(cname, None)
            _active_proxies.pop(key, None)
        sock_dir = _shared_sock_dir_path(session_tag, pr_id)
        sock_path = os.path.join(sock_dir, "push.sock")
        existed = os.path.exists(sock_path) or os.path.isdir(sock_dir)
        try:
            os.unlink(os.path.join(os.path.realpath(sock_dir), _OWNER_FILE))
        except OSError:
            pass
        _kill_proxy_socket(sock_path)
        long_dir = f"/tmp/{_SOCKET_DIR_PREFIX}{session_tag}-{pr_id}"
        if os.path.islink(long_dir):
            try:
                os.unlink(long_dir)
            except OSError:
                pass
        if existed:
            _log.info("Stopped unused shared push proxy for %s/%s",
                      session_tag, pr_id)
        return existed


def stop_push_proxy(container_name: str) -> None:
    """Stop and clean up the push proxy for a container.

    For shared proxies the proxy is only stopped when no container — in this
    process or any other — still uses it (see :func:`release_proxy_if_unused`).
    When the runtime can't be queried, keep the proxy for a later reconcile.
    """
    with _proxy_lock:
        key = _container_to_proxy_key.pop(container_name, None)
        local_refs_left = False
        if key is not None and key in _proxy_refs:
            refs = _proxy_refs[key]
            refs.discard(container_name)
            local_refs_left = bool(refs)

    if key is None:
        # Not started by this process — derive the shared key from the name.
        from pm_core.container import parse_container_name
        parsed = parse_container_name(container_name)
        pid = parsed.pr_id() if parsed else None
        if parsed and parsed.session_tag and pid:
            release_proxy_if_unused(parsed.session_tag, pid)
        # A per-container proxy (no session tag or PR, e.g. qa-debug or
        # legacy untagged containers) serves only this container.
        import tempfile
        own_sock = os.path.join(tempfile.gettempdir(),
                                f"{_SOCKET_DIR_PREFIX}{container_name}",
                                "push.sock")
        if os.path.exists(own_sock):
            _kill_proxy_socket(own_sock)
        return

    if "\0" in key:
        if local_refs_left:
            return  # this process still has a container on the proxy
        stag, pid = key.split("\0", 1)
        # Local references cannot prove that another process has no users.
        # Unknown runtime inventory leaves the shared proxy for a later pass.
        release_proxy_if_unused(stag, pid)
        return

    with _proxy_lock:
        _active_proxies.pop(key, None)

    # Legacy key = container_name: this proxy serves only this container.
    import tempfile
    sock_path = os.path.join(tempfile.gettempdir(),
                             f"{_SOCKET_DIR_PREFIX}{key}",
                             "push.sock")
    _kill_proxy_socket(sock_path)


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


def stop_session_proxies(session_tag: str) -> int:
    """Stop all push proxies belonging to a session.

    Returns the number of proxies stopped.
    """
    import glob as _glob
    prefix = f"{session_tag}\0"
    with _proxy_lock:
        keys_to_remove = [k for k in _active_proxies if k.startswith(prefix)]
        for k in keys_to_remove:
            _active_proxies.pop(k, None)
            for cname in _proxy_refs.pop(k, set()):
                _container_to_proxy_key.pop(cname, None)

    # Kill sockets matching the session tag
    count = 0
    for sock in _glob.glob(f"/tmp/{_SOCKET_DIR_PREFIX}{session_tag}-*/push.sock"):
        _kill_proxy_socket(sock)
        count += 1

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
                          pr_id: str | None = None) -> str | None:
    """Return the host socket path for a container's push proxy, or None.

    Uses the deterministic path convention so this works even after a
    TUI restart (no in-memory state needed).  Always returns the real
    (resolved) path so callers can ``connect()`` without hitting the
    Unix socket 107-byte path limit.
    """
    import tempfile

    def _resolve(path: str) -> str | None:
        """Return the realpath if the socket exists, else None."""
        if os.path.exists(path):
            return os.path.realpath(path)
        return None

    # Try shared proxy path first (session_tag + pr_id)
    if session_tag and pr_id:
        # Check via _shared_sock_dir_path (read-only, no side effects)
        shared_dir = _shared_sock_dir_path(session_tag, pr_id)
        result = _resolve(os.path.join(shared_dir, "push.sock"))
        if result:
            return result
        # Also check the long-named symlink path
        long_path = os.path.join(tempfile.gettempdir(),
                                 f"{_SOCKET_DIR_PREFIX}{session_tag}-{pr_id}",
                                 "push.sock")
        result = _resolve(long_path)
        if result:
            return result

    # Try legacy per-container path
    sock_path = os.path.join(tempfile.gettempdir(),
                             f"{_SOCKET_DIR_PREFIX}{container_name}",
                             "push.sock")
    result = _resolve(sock_path)
    if result:
        return result

    # Fall back to in-memory registry — derive path from the key
    with _proxy_lock:
        key = _container_to_proxy_key.get(container_name)
        if key is None:
            return None
    if "\0" in key:
        stag, pid = key.split("\0", 1)
        derived_dir = _shared_sock_dir_path(stag, pid)
        result = _resolve(os.path.join(derived_dir, "push.sock"))
        if result:
            return result
    return None


def container_socket_path() -> str:
    """Return the fixed socket path inside the container."""
    return _CONTAINER_SOCKET_PATH


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
    proxy.start()

    # Block until the socket is removed or we get a signal
    import signal as _signal
    _stop = threading.Event()
    _signal.signal(_signal.SIGTERM, lambda *_: _stop.set())
    _signal.signal(_signal.SIGINT, lambda *_: _stop.set())
    while not _stop.is_set():
        if not proxy.owns_socket():
            break
        _stop.wait(2.0)
    proxy.stop()
