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

    def start(self) -> None:
        """Start the proxy in a background daemon thread."""
        # Ensure parent directory exists
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)
        # Clean up stale socket
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(self.socket_path)
        # Make socket world-writable so the container user can connect
        os.chmod(self.socket_path, 0o777)
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
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        _log.info("Push proxy stopped: %s", self.socket_path)

    def _serve_loop(self) -> None:
        """Accept connections and handle push requests."""
        while not self._stop.is_set():
            # If the socket file was removed externally (e.g. container
            # cleanup in tmux), exit the loop so the thread terminates.
            if not os.path.exists(self.socket_path):
                _log.info("Push proxy socket removed, exiting: %s",
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

        # Check if origin is a local path.  QA clones should have their
        # origin set to the real remote at clone time, but local-only repos
        # (no upstream) still have a local-path origin.  For those, we
        # can't ``git push`` (fails with receive.denyCurrentBranch on
        # non-bare repos), so we fetch from the clone into the target repo
        # instead — the proxy can see both paths on the host.
        workdir = caller_workdir or self.workdir
        remote = self._extract_remote_name(push_args)
        local_target = _resolve_local_remote_url(workdir, remote)

        if local_target is not None:
            return self._local_push(local_target, target_branch,
                                    caller_workdir=workdir)

        cmd = ["git", "push"] + push_args
        _log.info("Push proxy executing: %s (in %s)", cmd, workdir)
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
                    "stderr": "push-proxy: git push timed out after 120s\n"}
        except Exception as exc:
            return {"exit_code": 1, "stdout": "",
                    "stderr": f"push-proxy: {exc}\n"}

    def _local_push(self, target_repo: str, branch: str,
                    caller_workdir: str | None = None) -> dict:
        """Push to a local repo, then forward to the real upstream if any.

        ``git push`` to a non-bare repo with the branch checked out fails
        with ``receive.denyCurrentBranch``.  Instead, we:
          1. ``git fetch <clone> <branch>:<branch>`` from the target side
             to update the local PR workdir's branch ref
          2. Forward to the real upstream (if the target repo has one)
             so the remote stays in sync
        """
        # Step 1: Update the local target repo's branch ref
        # --update-head-ok is needed because the target repo typically has
        # this branch checked out, and git refuses to fetch into a checked-out
        # branch without it.
        source = caller_workdir or self.workdir

        # Prefer the explicit branch ref; fall back to HEAD when the source
        # clone doesn't have a local branch by that name (e.g. legacy requests
        # where self.workdir is on a differently-named default branch).
        src_ref = f"refs/heads/{branch}"
        try:
            _check = subprocess.run(
                ["git", "rev-parse", "--verify", src_ref],
                cwd=source, capture_output=True, timeout=5,
            )
            if _check.returncode != 0:
                src_ref = "HEAD"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            src_ref = "HEAD"

        refspec = f"{src_ref}:refs/heads/{branch}"
        cmd = ["git", "-C", target_repo, "fetch", "--update-head-ok",
               source, refspec]
        _log.info("Push proxy local push (step 1 — update local): %s", cmd)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            return {"exit_code": 1, "stdout": "",
                    "stderr": "git-proxy: local push timed out after 120s\n"}
        except Exception as exc:
            return {"exit_code": 1, "stdout": "",
                    "stderr": f"git-proxy: local push failed: {exc}\n"}

        if result.returncode != 0:
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        _log.info("Local push succeeded: %s → %s (%s)",
                  source, target_repo, branch)

        # Step 2: Forward to real upstream if the target repo has one
        real_url = resolve_real_origin(target_repo)
        if real_url:
            fwd_cmd = ["git", "push", "origin", branch]
            _log.info("Push proxy forwarding to upstream: %s (from %s)",
                      fwd_cmd, target_repo)
            try:
                fwd = subprocess.run(
                    fwd_cmd, cwd=target_repo,
                    capture_output=True, text=True, timeout=120,
                )
                # Combine output from both steps
                return {
                    "exit_code": fwd.returncode,
                    "stdout": result.stdout + fwd.stdout,
                    "stderr": result.stderr + fwd.stderr,
                }
            except subprocess.TimeoutExpired:
                return {"exit_code": 1, "stdout": result.stdout,
                        "stderr": result.stderr +
                        "git-proxy: upstream push timed out after 120s\n"}
            except Exception as exc:
                return {"exit_code": 1, "stdout": result.stdout,
                        "stderr": result.stderr +
                        f"git-proxy: upstream push failed: {exc}\n"}

        # No real upstream — local-only repo, local update is sufficient
        return {
            "exit_code": 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def _execute_read_cmd(self, git_cmd: str, args: list[str],
                          caller_workdir: str | None = None) -> dict:
        """Execute a read-only git remote command (fetch, pull, ls-remote).

        These run directly from the caller's workdir with no branch
        restriction — containers have full read access to the remote.
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

        # Reuse if an existing proxy is alive on this socket
        if os.path.exists(sock_path) and proxy_is_alive(sock_path):
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
        try:
            os.unlink(sock_path)
        except IsADirectoryError:
            import shutil
            shutil.rmtree(sock_path, ignore_errors=True)
        except FileNotFoundError:
            pass

        _start_proxy_subprocess(sock_path, workdir, allowed_branch)

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


def stop_push_proxy(container_name: str) -> None:
    """Stop and clean up the push proxy for a container.

    For shared proxies the proxy is only stopped when the last container
    referencing it is removed.
    """
    with _proxy_lock:
        key = _container_to_proxy_key.pop(container_name, None)
        if key is None:
            return

        # Shared proxy path — decrement refcount
        if key in _proxy_refs:
            refs = _proxy_refs[key]
            refs.discard(container_name)
            if refs:
                return  # Other containers still using this proxy
            del _proxy_refs[key]

        _active_proxies.pop(key, None)

    # Derive the socket path from the key and remove it to stop the
    # subprocess proxy (the __main__ loop exits when socket disappears).
    if "\0" in key:
        # Shared proxy key: "session_tag\0pr_id"
        stag, pid = key.split("\0", 1)
        sock_dir = _shared_sock_dir_path(stag, pid)
        sock_path = os.path.join(sock_dir, "push.sock")
    else:
        # Legacy key = container_name
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


def cleanup_stale_proxy_dirs(session_tag: str) -> int:
    """Remove proxy socket directories whose proxy process is dead.

    Scans ``/tmp/pm-push-proxy-{session_tag}-*`` (both real directories and
    symlinks created by :func:`_shared_sock_dir`) and checks each socket for
    liveness.  Entries with dead or missing sockets are removed via
    :func:`_kill_proxy_socket`, which correctly resolves symlinks so both
    the symlink and the underlying hashed directory are cleaned up.

    Returns the number of entries removed.
    """
    import glob
    import tempfile

    pattern = os.path.join(tempfile.gettempdir(),
                           f"{_SOCKET_DIR_PREFIX}{session_tag}-*")
    count = 0
    for entry in glob.glob(pattern):
        if not os.path.isdir(entry):  # follows symlinks
            continue
        sock_path = os.path.join(entry, "push.sock")
        if not proxy_is_alive(sock_path):
            _kill_proxy_socket(sock_path)
            count += 1

    if count:
        _log.info("Cleaned up %d stale proxy dir(s) for session %s",
                  count, session_tag)
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
        if not os.path.exists(_sock):
            break
        _stop.wait(2.0)
    proxy.stop()
