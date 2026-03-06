"""Host-side git push proxy for containerised sessions.

Containers must not hold git credentials directly. Instead, each container
gets a dedicated push proxy — a small daemon running on the host that:

  1. Listens on a Unix socket (mounted into the container)
  2. Receives push requests from a lightweight git wrapper inside the container
  3. Validates the target branch against the allowed branch for that container
  4. Executes ``git push`` on the host (where credentials live)
  5. Streams back exit code, stdout, and stderr

One proxy per container — no shared state, no routing.  The proxy starts
when the container is created and is cleaned up when the container is removed.

Protocol (newline-delimited JSON over Unix socket):
  Request:  {"workdir": "/host/path", "args": ["origin", "branch"]}
  Response: {"exit_code": 0, "stdout": "...", "stderr": "..."}
"""

import json
import logging
import os
import socket
import subprocess
import threading
from pathlib import Path

_log = logging.getLogger("pm.push_proxy")

_SOCKET_DIR_PREFIX = "pm-push-proxy-"
_CONTAINER_SOCKET_PATH = "/run/pm-push-proxy.sock"


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
        """Handle a single push request."""
        conn.settimeout(30.0)
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk

        if not data:
            return

        try:
            request = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            response = {"exit_code": 1, "stdout": "",
                        "stderr": "push-proxy: invalid request format\n"}
            conn.sendall((json.dumps(response) + "\n").encode())
            return

        push_args = request.get("args", [])
        response = self._execute_push(push_args)
        conn.sendall((json.dumps(response) + "\n").encode())

    def _execute_push(self, push_args: list[str]) -> dict:
        """Validate the branch and execute git push on the host."""
        # Determine the target branch from the push args
        target_branch = self._extract_target_branch(push_args)

        if target_branch and target_branch != self.allowed_branch:
            msg = (f"push-proxy: rejected — pushing to '{target_branch}' "
                   f"is not allowed, only '{self.allowed_branch}'\n")
            _log.warning("Push rejected: target=%s allowed=%s",
                         target_branch, self.allowed_branch)
            return {"exit_code": 1, "stdout": "", "stderr": msg}

        cmd = ["git", "push"] + push_args
        _log.info("Push proxy executing: %s (in %s)", cmd, self.workdir)
        try:
            result = subprocess.run(
                cmd, cwd=self.workdir,
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

    def _extract_target_branch(self, push_args: list[str]) -> str | None:
        """Extract the target branch from git push arguments.

        Returns the branch name, or None if it can't be determined
        (in which case we fall back to current branch check).
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
                if arg in ("-u", "--set-upstream", "--repo",
                           "--push-option", "-o", "--receive-pack",
                           "--exec"):
                    skip_next = True
                continue
            positional.append(arg)

        if len(positional) >= 2:
            refspec = positional[1]
            # refspec can be "branch", "src:dst", "refs/heads/branch", etc.
            if ":" in refspec:
                dst = refspec.split(":", 1)[1]
            else:
                dst = refspec
            # Strip refs/heads/ prefix
            if dst.startswith("refs/heads/"):
                dst = dst[len("refs/heads/"):]
            return dst if dst else None

        # No explicit refspec — check what branch HEAD is on
        if not positional or len(positional) == 1:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=self.workdir, capture_output=True, text=True,
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

# Track running proxies so they can be cleaned up
_active_proxies: dict[str, PushProxy] = {}
_proxy_lock = threading.Lock()


def start_push_proxy(container_name: str, workdir: str,
                     allowed_branch: str) -> str:
    """Start a push proxy for a container.

    Args:
        container_name: Container name (used for socket naming).
        workdir: Host path to the git working directory.
        allowed_branch: Only allow pushes to this branch.

    Returns:
        Host path to the Unix socket (to be mounted into the container).
    """
    import tempfile
    sock_dir = tempfile.mkdtemp(prefix=_SOCKET_DIR_PREFIX)
    sock_path = os.path.join(sock_dir, "push.sock")

    proxy = PushProxy(sock_path, workdir, allowed_branch)
    proxy.start()

    with _proxy_lock:
        _active_proxies[container_name] = proxy

    return sock_path


def stop_push_proxy(container_name: str) -> None:
    """Stop and clean up the push proxy for a container."""
    with _proxy_lock:
        proxy = _active_proxies.pop(container_name, None)
    if proxy:
        sock_dir = str(Path(proxy.socket_path).parent)
        proxy.stop()
        # Clean up the temp directory
        try:
            os.rmdir(sock_dir)
        except OSError:
            pass


def stop_all_proxies() -> None:
    """Stop all running push proxies."""
    with _proxy_lock:
        names = list(_active_proxies.keys())
    for name in names:
        stop_push_proxy(name)


def container_socket_path() -> str:
    """Return the fixed socket path inside the container."""
    return _CONTAINER_SOCKET_PATH
