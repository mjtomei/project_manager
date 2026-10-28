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

Lifetime: each socket directory carries an ``owner.json`` (session, PR,
workdir and runtime domain) written before its daemon starts.  A shared
proxy is released — socket, directory, discovery link and start lock — only
once the runtime reports no container, in any pm process and any state,
still mounting it, checked under the PR's cross-process proxy lock that a
launching container holds until it exists (:func:`release_proxy_decision`).
In-process references only say that *this* process still has users.  A
per-container proxy is released with its container.

Protocol (newline-delimited JSON over Unix socket):
  Request:  {"cmd": "push|fetch|pull|ls-remote", "args": ["origin", "branch"],
             "workdir": "/host/path/to/clone"}
  Response: {"exit_code": 0, "stdout": "...", "stderr": "..."}

Legacy requests without ``cmd`` are treated as push (backward compat).
``"workdir"`` is optional; omitting it falls back to ``self.workdir``.
"""

import contextlib
import contextvars
import errno
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from pm_core.container import ContainerError
from pm_core.git_ops import NO_HOOKS_ARGS
from pm_core.paths import configure_logger

_log = configure_logger("pm.push_proxy")

_SOCKET_DIR_PREFIX = "pm-push-proxy-"
_CONTAINER_SOCKET_DIR = "/run/pm-push-proxy"
_CONTAINER_SOCKET_PATH = f"{_CONTAINER_SOCKET_DIR}/push.sock"
_METADATA_NAME = "proxy.json"
# Who may release a socket directory: session/PR (empty for per-container
# proxies), workdir and runtime domain.  Written by the starter before the
# daemon exists; read by cleanup in any pm process.
_OWNER_FILE = "owner.json"
# A real sidecar is a few hundred bytes; anything larger is not ours.
_METADATA_MAX_BYTES = 64 * 1024

# Neutralise repo-configured hooks on every host-side git invocation the proxy
# makes. The workdir is container-writable, so ``.git/hooks/pre-push`` (or
# ``core.hooksPath``) is container-authored code that would otherwise run on
# the host — the same escape ``--upload-pack``/``--exec`` are blocked for.
# Shared with pm's own workdir git calls (:data:`git_ops.NO_HOOKS_ARGS`).
_NO_HOOKS = list(NO_HOOKS_ARGS)


class PushProxyError(ContainerError):
    """The push proxy could not be started or made ready.

    A :class:`ContainerError`, so launch and cleanup paths that classify
    container failures (and keep them retryable) treat it like any other.
    """


class PushProxyConflict(PushProxyError):
    """A live proxy serves a different workdir or allowed branch."""


# Push options that publish more than the single allowed branch.
# ``--branches`` is git's alias of ``--all``.
_BROAD_PUSH_OPTIONS = ("--all", "--branches", "--mirror", "--tags")


def _long_option_match(arg: str, options: tuple[str, ...]) -> str | None:
    """Return the long option in *options* that git would read *arg* as.

    git's option parser accepts any unambiguous prefix of a long option,
    with or without ``=value``: ``--mir`` is ``--mirror``.  Checking exact
    spellings only is therefore not enough to keep an option out.  An
    ambiguous prefix (``--a`` for ``--all``/``--atomic``) also matches —
    git would refuse it anyway, so treating it as the option fails closed.
    Short options and the bare ``--`` separator never match.
    """
    name = arg.split("=", 1)[0]
    if len(name) <= 2 or not name.startswith("--"):
        return None
    return next((opt for opt in options if opt.startswith(name)), None)


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
    from pm_core.container import _file_lock
    key = hashlib.sha256(os.path.realpath(socket_path).encode()).hexdigest()
    with _file_lock(f"proxy-socket-{key}", timeout=10) as locked:
        if not locked:
            raise ContainerError(f"Push proxy socket lifecycle lock unavailable: {socket_path}")
        yield


def _socket_identity(path: str) -> tuple[int, int, int] | None:
    """The published socket generation at *path* (inode alone can be reused)."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino, st.st_ctime_ns)


def _metadata_path(sock_path: str) -> str:
    """Sidecar describing which workdir/branch a socket's daemon serves."""
    return os.path.join(os.path.dirname(sock_path), _METADATA_NAME)


def _write_metadata(sock_path: str, workdir: str,
                    allowed_branch: str) -> None:
    """Atomically record the daemon's workdir/branch next to its socket.

    Best-effort: a read-only socket directory must not stop the proxy.

    The temp file is created with ``mkstemp`` (``O_CREAT|O_EXCL`` and a
    random name) rather than at a predictable ``<pid>`` name: the socket
    directory is bind-mounted *writable* into the container, so a container
    could plant a symlink on a predictable temp name and have the daemon
    (running as the host user) write the sidecar — or, worse, ``os.replace``
    the symlink itself — into an arbitrary host file.
    """
    path = _metadata_path(sock_path)
    payload = {
        "workdir": os.path.realpath(workdir),
        "allowed_branch": allowed_branch,
        "pid": os.getpid(),
    }
    tmp: str | None = None
    try:
        fd, tmp = tempfile.mkstemp(
            prefix=_METADATA_NAME + ".", suffix=".tmp",
            dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
        tmp = None
    except OSError:
        _log.warning("Push proxy: could not write metadata %s", path,
                     exc_info=True)
    finally:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _read_metadata(sock_path: str) -> dict | None:
    """Return the sidecar metadata for *sock_path*, or None if unreadable.

    The socket directory is bind-mounted *writable* into the container, so
    the sidecar may be something a container planted: never follow a
    symlink (``O_NOFOLLOW``), and only read a regular file of bounded size
    (``O_NONBLOCK`` so a planted FIFO cannot block a proxy start that holds
    the directory's start lock).
    """
    try:
        fd = os.open(_metadata_path(sock_path),
                     os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > _METADATA_MAX_BYTES:
            return None
        with os.fdopen(fd, encoding="utf-8") as f:
            fd = -1  # fdopen owns it now
            data = json.loads(f.read(_METADATA_MAX_BYTES))
    except (OSError, ValueError):
        return None
    finally:
        if fd >= 0:
            os.close(fd)
    return data if isinstance(data, dict) else None


def _unlink_socket_file(path: str) -> bool:
    """Remove the socket file at *path*, tolerating what docker leaves behind.

    Docker creates a *directory* where a bind-mounted socket file should be
    (older pm versions mounted the socket itself), so a plain ``os.unlink``
    would raise ``IsADirectoryError`` and abort the caller.  A missing path
    is not an error.

    Returns True when the path is gone afterwards.  The socket directory is
    bind-mounted *writable* into the container, so a container can make the
    entry unremovable (a root-owned socket in a sticky directory, an
    immutable file, a chmod'd directory).  A bare ``OSError`` here used to
    escape both callers: a start surfaced it as "Is docker running?" and a
    teardown sweep aborted, leaving every other proxy of the session behind.
    The refusal is now reported instead — the start raises a
    :class:`PushProxyError` naming the path, and teardown leaves the entry
    for the next attempt.
    """
    try:
        os.unlink(path)
        return True
    except IsADirectoryError:
        shutil.rmtree(path, ignore_errors=True)
        return not os.path.lexists(path)
    except FileNotFoundError:
        return True
    except OSError as exc:
        _log.warning("Push proxy: could not remove socket file %s: %s",
                     path, exc)
        return False


class PushProxy:
    """A push proxy daemon for one host workdir.

    Every container whose clone is that workdir shares the daemon; a
    request naming any other clone is rejected (see the module docstring).

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
        # (st_dev, st_ino, st_ctime_ns) of the socket we bound: an inode alone
        # can be reused by a replacement bound after ours was unlinked.
        self._socket_identity: tuple[int, int, int] | None = None
        # True only once bind() succeeded.  A start() that raised before
        # that point owns no socket and must not unlink one on stop().
        self._bound = False

    def start(self) -> bool:
        """Start the proxy in a background daemon thread.

        Returns ``False`` when a live proxy already owns the socket path;
        in that case this instance does not bind, does not replace the
        existing socket, and must not unlink it on ``stop()``.
        """
        # Ensure parent directory exists
        Path(self.socket_path).parent.mkdir(parents=True, exist_ok=True)

        # Bind/unlink share a path-keyed lock with every other daemon and
        # stop path, so a delayed old shutdown cannot remove the socket a
        # replacement just bound.
        with _socket_lifecycle_lock(self.socket_path):
            # Never steal a live socket.  Two daemons racing to unlink→bind
            # is how a proxy for one workdir used to replace another's.
            if (os.path.exists(self.socket_path)
                    and proxy_is_alive(self.socket_path)):
                _log.warning("Push proxy socket already served; not "
                             "replacing: %s", self.socket_path)
                return False

            # Clean up stale socket (docker may have created a directory here)
            _unlink_socket_file(self.socket_path)

            self._server_socket = socket.socket(socket.AF_UNIX,
                                                socket.SOCK_STREAM)
            self._server_socket.bind(self.socket_path)
            self._bound = True
            # Make socket world-writable so the container user can connect
            os.chmod(self.socket_path, 0o777)
            self._socket_identity = _socket_identity(self.socket_path)
            # Record the served workdir/branch so start_push_proxy can refuse
            # a mismatched reuse instead of silently replacing this daemon.
            _write_metadata(self.socket_path, self.workdir,
                            self.allowed_branch)
            # A small backlog matters: the handler serves one request at a
            # time (a push can run for up to two minutes), and
            # ``proxy_is_alive`` probes connect without sending.  With a
            # backlog of 1 a single queued probe made the next connect block
            # until the 2 s timeout, so a *busy but live* proxy looked dead
            # and callers replaced it.
            self._server_socket.listen(16)
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
        if self._socket_identity is None:
            # We could not stat our own socket at bind time; nothing better
            # to compare against, so keep the historical cleanup behaviour.
            return True
        # Missing or unreadable compares unequal: do *not* treat "missing" as
        # permission to unlink.  A daemon exits when its socket was removed (a
            # shared stop unlinks it and keeps the directory), and a restart
            # for the same workdir can bind a fresh socket at the same path
            # in the window between this stat and the unlink that follows.
            # Reporting "not owned" leaves that replacement alone; anything
            # of ours is already gone, and the metadata sidecar is best-effort
            # (a later start rewrites it, session teardown removes it).
        return _socket_identity(self.socket_path) == self._socket_identity

    def socket_is_current(self) -> bool:
        """True while the socket at our path is still the one we bound.

        Unlike :meth:`_owns_socket_path` this treats a missing file as "not
        current", which is what the serve and main loops need: both must
        stop when the path is gone *or* has been rebound by another daemon.
        """
        if self._socket_identity is None:
            # Could not stat our own socket at bind time — fall back to the
            # plain existence check the daemon used before inode tracking.
            return os.path.exists(self.socket_path)
        return _socket_identity(self.socket_path) == self._socket_identity

    # The name the reaper-era daemon loop used for the same check.
    owns_socket = socket_is_current

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
        if not self._bound:
            # start() raised before binding (e.g. EADDRINUSE): we never
            # owned the path, so leave whatever is there alone.
            _log.info("Push proxy never bound; leaving %s in place",
                      self.socket_path)
            return
        with _socket_lifecycle_lock(self.socket_path):
            if not self._owns_socket_path():
                _log.info("Push proxy socket replaced or already removed; "
                          "leaving it in place: %s", self.socket_path)
                return
            # Same shapes as the other teardown paths (a directory left by
            # docker at a bind-mounted socket path must not raise here).
            _unlink_socket_file(self.socket_path)
        try:
            os.unlink(_metadata_path(self.socket_path))
        except OSError:
            # The socket directory is bind-mounted *writable* into the
            # container, so the sidecar name may be a directory (or an
            # unwritable entry) a container planted.  Leaving it behind is
            # harmless — a later start rewrites the sidecar best-effort —
            # and must not raise out of stop() the way a bare
            # ``os.unlink`` would (``_kill_proxy_socket`` ignores it too).
            pass
        _log.info("Push proxy stopped: %s", self.socket_path)

    def _retire_socket(self) -> None:
        """Unlink this daemon's published socket so a repair can replace it.

        Used when the acceptor can no longer serve (e.g. ``EMFILE``): leaving
        the bound socket in place would make ``proxy_is_alive`` keep reporting
        a healthy proxy while every client hangs on ``recv``.  Best effort —
        this runs on the daemon thread, so an unavailable lifecycle lock must
        not escape and kill it with a traceback.
        """
        try:
            with _socket_lifecycle_lock(self.socket_path):
                if not self.socket_is_current():
                    return  # a replacement already published its own socket
                try:
                    os.unlink(self.socket_path)
                except FileNotFoundError:
                    pass
                except OSError:
                    _log.warning("Push proxy could not retire %s",
                                 self.socket_path, exc_info=True)
        except Exception:
            _log.warning("Push proxy could not retire %s: lifecycle lock "
                         "unavailable", self.socket_path, exc_info=True)

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
            except OSError as exc:
                if self._stop.is_set():
                    break
                if exc.errno == errno.ECONNABORTED:
                    # A client aborted between poll and accept: recoverable.
                    continue
                # The acceptor can no longer serve (EMFILE/ENFILE/EBADF/...).
                # Retire the socket so readiness probes fail and the next
                # launch repairs it, instead of leaving a bound-but-dead
                # socket that reports healthy and hangs every client.
                _log.warning("Push proxy acceptor failed at %s: %s; retiring",
                             self.socket_path, exc)
                self._retire_socket()
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

        if not isinstance(request, dict):
            # Valid JSON but not an object: answer explicitly instead of
            # raising and dropping the connection with no response.
            response = {"exit_code": 1, "stdout": "",
                        "stderr": "git-proxy: request must be a JSON object\n"}
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

    # Long options git will resolve to a program-executing behaviour.
    _DANGEROUS_GIT_OPTIONS = ("--upload-pack", "--receive-pack", "--exec")

    @classmethod
    def _check_dangerous_flags(cls, args: list[str], cmd_name: str) -> dict | None:
        """Reject flags that could execute arbitrary programs on the host.

        ``--upload-pack``, ``--receive-pack``, and ``--exec`` tell git to
        invoke a user-specified program.  A container could write a script
        to /workspace (bind-mounted rw) and reference it here to escape
        the container sandbox.  Block these unconditionally.

        git's option parser accepts any unambiguous *prefix* of a long
        option, so ``--upl=/workspace/evil.sh`` (and even ``--e=``) is the
        same escape as ``--upload-pack=…`` and must be rejected too (see
        :func:`_long_option_match`).  ``--rec…``/``--ref…`` are not
        prefixes of ``--receive-pack``, so ordinary options still pass.

        Returns an error response dict if a dangerous flag is found, or
        None if args are safe.
        """
        for arg in args:
            # Match both --flag=value and --flag (next arg is value)
            matched = _long_option_match(arg, cls._DANGEROUS_GIT_OPTIONS)
            if matched is not None:
                stripped = arg.split("=", 1)[0]
                shown = (stripped if stripped == matched
                         else f"{stripped} (abbreviation of {matched})")
                msg = (f"git-proxy: rejected — '{shown}' is not allowed "
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

        # Reject broad-push flags that bypass branch restrictions, in any
        # spelling git accepts (``--mir``, ``--branches``, ``--tags=x``, …)
        for arg in push_args:
            matched = _long_option_match(arg, _BROAD_PUSH_OPTIONS)
            if matched is not None:
                shown = (arg if arg == matched
                         else f"{arg} (read by git as {matched})")
                msg = (f"push-proxy: rejected — '{shown}' is not allowed, "
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
        # The workdir is container-writable, and ``git push`` runs the
        # repo's pre-push hook — a container could drop
        # ``.git/hooks/pre-push`` and have it execute on the host, which is
        # exactly the sandbox escape ``_check_dangerous_flags`` exists to
        # block. Disable hooks (the command-line ``-c`` outranks the repo
        # config); the proxy needs none of them.
        cmd = ["git", "-C", source, *_NO_HOOKS, "push"] + push_args
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
        # ``git pull`` runs repo hooks (e.g. post-merge) from this
        # container-writable workdir; see ``_NO_HOOKS``.
        cmd = ["git", *_NO_HOOKS, git_cmd] + args
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
#
# _active_proxies holds *legacy* keys only; a shared proxy is tracked
# through _proxy_refs (whose keys are the registry of live shared proxies).
# Teardown therefore unions the two — do not treat _active_proxies alone as
# the complete set of running proxies.
_active_proxies: dict[str, str] = {}  # legacy key -> socket path
_proxy_lock = threading.Lock()

# For shared proxies: which containers reference each proxy key
_proxy_refs: dict[str, set[str]] = {}
# Reverse lookup: container_name -> proxy key
_container_to_proxy_key: dict[str, str] = {}


def _drop_old_ref(container_name: str, key: str) -> None:
    """Drop *container_name*'s reference to any proxy key other than *key*.

    Caller must hold ``_proxy_lock``.  A container references only one
    proxy at a time, so a previous reference is dropped rather than pinned
    forever (the old daemon itself is left for session teardown, like any
    other unreferenced proxy).
    """
    old = _container_to_proxy_key.get(container_name)
    if old is not None and old != key:
        old_refs = _proxy_refs.get(old)
        if old_refs is not None:
            old_refs.discard(container_name)
            if not old_refs:
                del _proxy_refs[old]


def _add_proxy_ref(container_name: str, key: str) -> None:
    """Record that *container_name* uses the shared proxy for *key*.

    Caller must hold ``_proxy_lock``.  The ref set is *added to*, never
    replaced: a respawned daemon must keep the other containers that share
    the same workdir.
    """
    _drop_old_ref(container_name, key)
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
    and a long-named symlink for discoverability/cleanup.  Call this under
    the socket directory's start lock (a start does), so a sweep cannot
    remove the link again between its creation and the proxy start; use
    ``_shared_sock_dir_path`` for read-only lookups.  A link found at the
    long name that does not resolve to this name's hashed directory is
    replaced (the link only, never its target), so a later registry-less
    teardown can still find the directory.  A non-directory entry squatting
    that name is removed when it is ours, for the same reason.

    Directory creation is best-effort here: ``_start_lock`` creates it
    for real (and reports an unusable name as a ``PushProxyError``) before
    this is called, and the discovery symlink is optional.
    """
    long_name = f"{session_tag}-{pr_id}-{workdir_token}"
    long_dir = f"/tmp/{_SOCKET_DIR_PREFIX}{long_name}"
    short_dir = _shared_sock_dir_path(session_tag, pr_id, workdir_token)

    if short_dir == long_dir:
        # Fits — no hash needed, no symlink needed
        return long_dir

    try:
        os.makedirs(short_dir, exist_ok=True)
    except OSError:
        # /tmp is world-writable: a regular file squatting on the directory
        # name makes makedirs fail.  The discovery symlink is optional, so
        # do not fail here — _start_lock reports the unusable directory as a
        # PushProxyError (a start) or skips it (teardown).
        return short_dir

    # Create long-named symlink for discoverability/cleanup.  Best effort:
    # a name too long for the filesystem (or an unwritable /tmp) must not
    # stop the proxy — session teardown also derives hashed directories
    # from the in-process registry.
    try:
        os.symlink(short_dir, long_dir)
    except FileExistsError:
        # A real directory squatting on the long name blocks the link.
        if os.path.isdir(long_dir) and not os.path.islink(long_dir):
            # /tmp is world-writable, so the path may belong to someone else.
            # A foreign directory is not ours to delete (and its entries
            # would not be removable anyway); the discovery link is optional,
            # so leave it and carry on with the hashed directory.
            try:
                ours = os.stat(long_dir).st_uid == os.getuid()
            except OSError:
                ours = False
            if not ours:
                _log.warning("Push proxy: refusing to replace a directory "
                             "owned by another user: %s", long_dir)
                return short_dir
            shutil.rmtree(long_dir, ignore_errors=True)
            try:
                os.symlink(short_dir, long_dir)
            except FileExistsError:
                pass  # race — another process created it
            except OSError:
                _log.warning("Push proxy: could not create discovery "
                             "symlink %s", long_dir, exc_info=True)
        elif _is_foreign_discovery_link(long_dir):
            # A link planted at our long name (or one left pointing at
            # another session's directory) would make a later process — one
            # with an empty registry — sweep the wrong directory and miss
            # ours.  Replace the link itself; its target is never touched.
            try:
                os.unlink(long_dir)
                os.symlink(short_dir, long_dir)
            except OSError:
                _log.warning("Push proxy: could not replace a discovery "
                             "link that points elsewhere: %s", long_dir,
                             exc_info=True)
        elif not os.path.islink(long_dir):
            # A regular file (or other non-directory entry) squatting the
            # long name.  Without the link, a *later* process — one with an
            # empty registry — cannot find the hashed directory to sweep, so
            # the proxy and its directory would leak past session teardown.
            # /tmp is world-writable, so only remove an entry that is ours;
            # a foreign one is left in place (the link is optional).
            try:
                ours = os.lstat(long_dir).st_uid == os.getuid()
            except OSError:
                ours = False
            if not ours:
                _log.warning("Push proxy: refusing to replace an entry owned "
                             "by another user: %s", long_dir)
                return short_dir
            try:
                os.unlink(long_dir)
                os.symlink(short_dir, long_dir)
            except OSError:
                _log.warning("Push proxy: could not replace a squatted "
                             "discovery name %s", long_dir, exc_info=True)
        # else: our own legitimate discovery link — nothing to do.
    except OSError:
        _log.warning("Push proxy: could not create discovery symlink %s",
                     long_dir, exc_info=True)
    return short_dir


def _discovery_target(link: str) -> str | None:
    """Return the directory a long-name discovery symlink must point at.

    When the readable socket directory name would exceed the Unix socket
    path limit, :func:`_shared_sock_dir` creates the hashed directory and
    a long-named symlink to it.  That link's only legitimate target is the
    hash of its *own* name, so a link pointing anywhere else was planted
    (``/tmp`` is world-writable) or belongs to something else.  Following
    it would let teardown stop — and delete the bind-mount directory of —
    *another* session's proxy.

    Returns ``None`` when *link* is not a symlink (nothing to verify).
    """
    if not os.path.islink(link):
        return None
    name = os.path.basename(link)
    if not name.startswith(_SOCKET_DIR_PREFIX):
        return None
    long_name = name[len(_SOCKET_DIR_PREFIX):]
    dir_hash = hashlib.sha256(long_name.encode()).hexdigest()[:16]
    return f"/tmp/{_SOCKET_DIR_PREFIX}{dir_hash}"


def _is_foreign_discovery_link(sock_dir: str) -> bool:
    """True when *sock_dir* is a discovery symlink pointing somewhere else.

    A legitimate discovery link resolves to the hashed directory derived
    from its own name; anything else must never be followed by teardown.
    """
    expected = _discovery_target(sock_dir)
    return (expected is not None
            and os.path.realpath(sock_dir) != os.path.realpath(expected))


def _drop_foreign_discovery_link(sock_dir: str) -> bool:
    """Unlink a discovery symlink that points somewhere other than its hash.

    Returns True when *sock_dir* was such a link.  Only the link itself is
    removed — its target is never touched (it may be another session's
    live proxy directory).
    """
    if not _is_foreign_discovery_link(sock_dir):
        return False
    _log.warning("Refusing to touch a discovery link that points elsewhere: "
                 "%s -> %s", sock_dir, os.path.realpath(sock_dir))
    try:
        os.unlink(sock_dir)
    except OSError:
        pass
    return True


# How many times _start_lock re-opens the lock file when the one it locked
# was unlinked/replaced between open() and flock().  Realistic churn is one
# or two attempts; the cap only bounds a pathological (or hostile) loop.
_LOCK_ATTEMPTS = 100

# How many times a start recreates a socket directory that a concurrent
# teardown removed between the makedirs and the usability check.  One retry
# covers the race; the cap only bounds a pathological (or hostile) loop.
_START_DIR_ATTEMPTS = 3


def _fd_is_path_file(fd: int, path: str) -> bool:
    """True when *path* still names the same file *fd* is open on.

    ``flock`` locks the *inode*, not the name: if a teardown unlinks (or
    another process replaces) the lock file between our ``open()`` and
    ``flock()``, the lock we hold is invisible to a process that creates a
    fresh file at the same path.  Comparing the inode closes that window.
    """
    try:
        st_fd = os.fstat(fd)
        st_path = os.stat(path)
    except OSError:
        return False
    return (st_fd.st_dev, st_fd.st_ino) == (st_path.st_dev, st_path.st_ino)


def _sock_dir_start_problem(sock_dir: str) -> str | None:
    """Return why *sock_dir* cannot host a proxy start, or None when it can.

    ``/tmp`` is world-writable, so another user can plant a symlink or a
    directory with a proxy-shaped name where the socket directory should
    be.  A start must refuse such a directory instead of following the
    link — which would delete ``push.sock`` and write ``proxy.json``
    inside whatever it points at — and instead of leaking a bare
    ``OSError`` from that unlink (``wrap_claude_cmd`` reports one as a
    container-runtime problem, hiding the real cause).

    Only starts are checked.  Teardown passes the long discovery symlink
    to :func:`_start_lock` on purpose and guards itself in
    :func:`_stop_socket_under_lock` / :func:`_kill_proxy_socket` /
    :func:`_remove_proxy_dirs` (which also verify that the link leads to
    its own hashed directory).
    """
    if os.path.islink(sock_dir):
        return "is a symlink"
    try:
        st = os.stat(sock_dir)
    except OSError as exc:
        return f"is unusable ({exc})"
    if st.st_uid != os.getuid():
        return "is owned by another user"
    if not os.access(sock_dir, os.W_OK | os.X_OK):
        return "is not writable"
    return None


@contextlib.contextmanager
def _start_lock(sock_dir: str, blocking: bool = True):
    """Serialise check-and-spawn across processes for one socket directory.

    The lock file sits *next to* the directory (not inside it) so it never
    keeps a bind-mounted directory from being removed at session teardown.

    Yields True when the lock was taken.  With ``blocking=False`` the lock
    is only attempted (``LOCK_NB``): on contention the context yields False
    immediately, so teardown can skip a directory that a proxy start is
    using right now instead of stalling behind it.

    A lock taken on a file that a teardown unlinked (or another process
    replaced) is discarded and retried against the current file, so two
    processes can never both believe they hold the lock.

    With ``blocking=True`` (a start) a directory that cannot safely hold a
    proxy — a symlink, or one owned by another user or unwritable — raises
    :class:`PushProxyError` (see :func:`_sock_dir_start_problem`).  With
    ``blocking=False`` (teardown) nothing is created: a directory that is
    already gone yields ``False`` instead of being resurrected.
    """
    if not blocking:
        # Teardown must never *create* what it is sweeping.  Every teardown
        # caller checks ``isdir`` first, so reaching this branch with a
        # missing directory means a sweep removed it in the window since.
        # ``makedirs`` here would resurrect an empty proxy directory (plus a
        # lock file) that nothing removes again until the next teardown — a
        # shared stop deliberately keeps its directory, so the stop would
        # leak state it never found.
        if not os.path.isdir(sock_dir):
            _log.info("Push proxy directory %s is gone or unusable; skipping",
                      sock_dir)
            yield False
            return
    else:
        # Create the directory and verify it can host a proxy.  A concurrent
        # teardown can rmtree the directory between the two steps —
        # ``_remove_proxy_dirs`` only takes the start lock we have not taken
        # yet — so recreate it and check again rather than fail a start that
        # the race, not the caller, broke.  An entry that still *exists* is a
        # real problem (planted symlink, foreign owner, unwritable) and is
        # refused.
        problem: str | None = None
        for _attempt in range(_START_DIR_ATTEMPTS):
            try:
                os.makedirs(sock_dir, exist_ok=True)
            except OSError as exc:
                # /tmp is world-writable: a regular file (or an unreadable
                # directory) squatting on the socket-directory name makes
                # makedirs fail.  A start must fail as a proxy error instead
                # of leaking a bare OSError (which wrap_claude_cmd would
                # blame on the runtime) — the same treatment as an unusable
                # lock file below.
                raise PushProxyError(
                    f"could not create push proxy directory {sock_dir}: "
                    f"{exc}") from exc
            problem = _sock_dir_start_problem(sock_dir)
            if problem is None or os.path.lexists(sock_dir):
                break
            _log.info("Push proxy directory %s vanished during start; "
                      "recreating", sock_dir)
        if problem is not None:
            # A symlink (or a foreign/unwritable directory) on the socket
            # directory name would send the unlink/bind/metadata write into
            # its target.  Refuse it as a proxy error, not a bare OSError.
            raise PushProxyError(
                f"push proxy directory {sock_dir} {problem}")
    lock_path = os.path.realpath(sock_dir) + ".lock"
    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    for _attempt in range(_LOCK_ATTEMPTS):
        try:
            # O_NOFOLLOW: our own lock files are always regular files, so a
            # symlink planted at this world-writable /tmp name must never be
            # followed — otherwise the daemon would flock (and, if the
            # target does not exist yet, create) a file at an arbitrary path
            # chosen by another user.
            fd = os.open(lock_path,
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            # /tmp is world-writable: another user can plant
            # ``pm-push-proxy-*.lock`` with a mode we cannot open (or as a
            # symlink).  Teardown must skip that directory instead of
            # aborting the whole sweep, and a start must fail as a proxy
            # error rather than leak a bare OSError (which wrap_claude_cmd
            # would blame on the runtime).
            if blocking:
                raise PushProxyError(
                    f"could not open push proxy start lock {lock_path}: "
                    f"{exc}") from exc
            _log.warning("Push proxy start lock %s is unusable (%s); "
                         "skipping", lock_path, exc)
            yield False
            return
        try:
            try:
                fcntl.flock(fd, flags)
            except BlockingIOError:
                yield False
                return
            except OSError as exc:
                # Same treatment for a lock we cannot take (e.g. EACCES on a
                # file another user opened): skip during teardown, fail
                # loudly during a start.
                if blocking:
                    raise PushProxyError(
                        f"could not lock push proxy start lock {lock_path}: "
                        f"{exc}") from exc
                _log.warning("Push proxy start lock %s is not lockable (%s); "
                             "skipping", lock_path, exc)
                yield False
                return
            if _fd_is_path_file(fd, lock_path):
                try:
                    yield True
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                return
            # The file we locked is gone or replaced — try the new one.
            _log.info("Push proxy start lock %s was replaced; retrying",
                      lock_path)
        finally:
            os.close(fd)

    if blocking:
        raise PushProxyError(
            f"could not acquire push proxy start lock {lock_path} "
            f"after {_LOCK_ATTEMPTS} attempts")
    yield False


def _clear_lock_file(path: str) -> None:
    """Unlink a start-lock file, unless a process is holding it right now.

    Deleting a lock file that another process has flocked would let a third
    process create a fresh one and bypass the cross-process serialisation
    in :func:`_start_lock`.  The inode check additionally covers a file
    that was replaced between our ``open()`` and ``flock()`` — that
    replacement is not ours to remove.

    A symlink at the lock path is never a lock file of ours, so the link
    itself is removed (the target is never opened or touched).
    """
    try:
        if os.path.islink(path):
            os.unlink(path)
            return
    except OSError:
        pass  # cannot remove it (sticky /tmp, another owner) — leave it
    try:
        # O_NOFOLLOW, matching _start_lock: never lock through a link.
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    except OSError:
        return
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return  # in use — its owner (or a later teardown) clears it
        if not _fd_is_path_file(fd, path):
            return  # replaced in the open→flock window — not ours
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
    ready within the wait window (or could not be spawned at all).  It never
    raises: a failure here is reported by the caller as a
    :class:`PushProxyError` naming the socket, so it is not mistaken for a
    container-runtime problem.
    """
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "pm_core.push_proxy",
             sock_path, workdir, allowed_branch],
            start_new_session=True,  # detach from parent process group
            # Redirect stdin too: when spawned from a tmux popup
            # (`display-popup -E pm _popup-cmd ...`), an inherited pty FD
            # keeps the popup overlay open for the lifetime of this daemon.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        _log.warning("Push proxy subprocess could not be spawned for %s "
                     "(workdir=%s): %s", sock_path, workdir, exc)
        return False

    # Wait for the socket to appear and become connectable.  Five seconds
    # covers a slow fork/import without leaving a broken container behind.
    # Bound by a real deadline: each probe can block for its 2 s connect
    # timeout, so a fixed iteration count would hold the caller's locks for
    # far longer than this reports.  A failed or interrupted launch must not
    # leave a detached child that can publish its socket after container and
    # proxy cleanup have already finished, so the child is reaped first.
    ready = False
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            # Check the child before the socket: a stale socket at the path
            # (repair path) could still answer while the freshly spawned
            # child already exited without publishing.
            if proc.poll() is not None:
                _log.warning("Push proxy subprocess (pid=%d) exited (rc=%s) "
                             "before publishing %s",
                             proc.pid, proc.returncode, sock_path)
                return False
            if os.path.exists(sock_path) and proxy_is_alive(sock_path):
                ready = True
                _log.info("Push proxy subprocess started: pid=%d socket=%s "
                          "workdir=%s branch=%s",
                          proc.pid, sock_path, workdir, allowed_branch)
                return True
            time.sleep(0.1)
        _log.warning("Push proxy subprocess (pid=%d) did not become ready "
                     "at %s within 5s", proc.pid, sock_path)
        return False
    finally:
        if not ready:
            _reap_child(proc)


def _reap_child(proc: subprocess.Popen) -> None:
    """Terminate (if still running) and wait for a proxy child that failed."""
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        else:
            proc.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        _log.warning("Push proxy subprocess (pid=%d) could not be reaped",
                     proc.pid, exc_info=True)


@contextlib.contextmanager
def _discard_if_unpublished(sock_dir: str, fresh: bool,
                            link: str | None = None):
    """Remove the socket directory a failed start created, under its lock.

    A start that fails before its daemon publishes (readiness timeout,
    owner record or stale-socket failure) would otherwise leave an empty
    directory, its owner record and start lock behind — nothing mounts a
    directory this start just created, so it is not anyone's to keep.  A
    directory that existed before (possibly mounted by a live container) is
    left alone.  The original failure is always re-raised.
    """
    try:
        yield
    except BaseException:
        if fresh:
            sock_path = os.path.join(sock_dir, "push.sock")
            try:
                if not proxy_is_alive(sock_path):
                    _kill_proxy_socket(sock_path, remove_dir=True,
                                       lock_held=True)
                    if (link and os.path.islink(link)
                            and not os.path.exists(link)):
                        os.unlink(link)
            except (OSError, ContainerError):
                _log.warning("Could not discard unpublished push proxy "
                             "directory %s", sock_dir, exc_info=True)
        raise


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
        # Pure path computation — nothing is created before the start lock.
        sock_dir = _shared_sock_dir_path(session_tag, pr_id, token)
        sock_path = os.path.join(sock_dir, "push.sock")

        # Serialise check-and-spawn across processes: two containers on the
        # same workdir must not race unlink→bind and kill each other.
        fresh = not os.path.lexists(sock_dir)
        long_link = f"/tmp/{_SOCKET_DIR_PREFIX}{session_tag}-{pr_id}-{token}"
        with _start_lock(sock_dir), \
                _discard_if_unpublished(sock_dir, fresh, long_link):
            # (Re)create the directory and its long-name discovery symlink
            # under the lock.  ``_start_lock`` made the directory; a sweep
            # that ran between the path computation above and this lock can
            # have removed both, and that link is the only way a *later*
            # process (empty in-process registry) finds a hashed directory
            # to sweep — losing it would leak a live proxy past teardown.
            sock_dir = _shared_sock_dir(session_tag, pr_id, token)
            sock_path = os.path.join(sock_dir, "push.sock")
            # A socket (live or dead) may still be mounted by another
            # runtime's containers, whose users this process cannot
            # inventory: never share, repair or re-own it.
            if not _owner_domain_matches(sock_dir):
                raise PushProxyError(
                    "Existing shared push proxy belongs to a different or "
                    "unverifiable runtime; refusing cross-runtime reuse")
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
            #
            # A dead socket can still carry the sidecar of the daemon that
            # used to own this path.  The key is a hash of the workdir, so a
            # recorded workdir that differs can only be a token collision:
            # refuse rather than silently re-point this key at another clone
            # (the check above only covers a *live* proxy).
            stale = _read_metadata(sock_path)
            if stale:
                stale_workdir = stale.get("workdir")
                if (stale_workdir
                        and os.path.realpath(str(stale_workdir))
                        != os.path.realpath(workdir)):
                    raise PushProxyConflict(
                        f"stale push proxy metadata at {sock_path} records "
                        f"workdir '{stale_workdir}', not requested "
                        f"'{workdir}' (workdir token collision)")
            with _socket_lifecycle_lock(sock_path):
                removed = _unlink_socket_file(sock_path)
            if not removed:
                # The stale entry cannot be removed, so the daemon could not
                # bind over it.  Fail as a proxy error naming the path
                # instead of letting the readiness wait time out (and
                # instead of leaking a bare OSError that wrap_claude_cmd
                # would blame on the container runtime).
                raise PushProxyError(
                    f"could not remove stale push proxy socket at {sock_path} "
                    f"(workdir={workdir})")

            # Publish ownership before the daemon exists, so a cleanup pass
            # can always map this directory back to its session/PR/runtime.
            _write_owner_file(sock_dir, session_tag, pr_id, workdir)
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
    # Use a deterministic path based on the container name so the
    # socket can be found after a TUI restart without a registry.
    sock_dir = os.path.join(tempfile.gettempdir(),
                            f"{_SOCKET_DIR_PREFIX}{container_name}")
    sock_path = os.path.join(sock_dir, "push.sock")
    # _start_lock creates the directory and reports an unusable name (a
    # squatted file, a symlink, another user's dir) as a PushProxyError.
    fresh = not os.path.lexists(sock_dir)
    with _start_lock(sock_dir), _discard_if_unpublished(sock_dir, fresh):
        if not _owner_domain_matches(sock_dir):
            raise PushProxyError(
                "Existing unshared push proxy belongs to a different or "
                "unverifiable runtime; refusing cross-runtime reuse")
        # A renamed allocation can still mount this name's directory; a
        # fresh start must not replace a socket another allocation uses.
        # (A directory with no socket or owner record was never published.)
        if ((os.path.lexists(sock_path)
             or os.path.lexists(os.path.join(sock_dir, _OWNER_FILE)))
                and unshared_proxy_in_use(sock_path)):
            raise PushProxyError(
                f"Push proxy directory for '{container_name}' is still "
                f"mounted by another allocation")
        # Remove stale socket before spawning (see above for why we handle
        # the directory-at-the-socket-path case).
        with _socket_lifecycle_lock(sock_path):
            removed = _unlink_socket_file(sock_path)
        if not removed:
            raise PushProxyError(
                f"could not remove stale push proxy socket at {sock_path} "
                f"(workdir={workdir})")

        _write_owner_file(sock_dir, "", "", workdir)
        if not _start_proxy_subprocess(sock_path, workdir, allowed_branch):
            raise PushProxyError(
                f"push proxy did not become ready at {sock_path} "
                f"(workdir={workdir}, branch={allowed_branch})")

        # Register while still holding the start lock: stop_push_proxy
        # re-checks this registry under the same lock before killing the
        # socket, so a concurrent stop must be able to see the proxy we
        # just spawned (the shared path registers under the lock too).
        with _proxy_lock:
            _drop_old_ref(container_name, container_name)
            _active_proxies[container_name] = sock_path
            _container_to_proxy_key[container_name] = container_name

    return sock_path


# While set, every proxy _kill_proxy_socket() stops is appended (by socket
# directory), so a caller removing containers can report the proxies that
# went with them (their release paths differ: unshared, shared, legacy).
stopped_proxy_sink: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "stopped_proxy_sink", default=None)


def _kill_proxy_socket(sock_path: str, remove_dir: bool = True,
                       lock_held: bool = False,
                       expected_identity: tuple[int, int, int] | None = None
                       ) -> bool:
    """Stop a subprocess proxy by removing its socket (triggers exit).

    With *expected_identity* only that captured socket generation is
    stopped: a replacement bound at the same path since is left alone (and
    reported as not stopped).  A socket that is already gone still has its
    ownership metadata retired — callers hold the launch/user guards.

    Returns True when the socket was stopped, False when the path was
    refused (a non-proxy directory, a foreign-owned directory, a discovery
    link that points elsewhere, or a socket file that cannot be removed —
    the daemon keeps serving it, so reporting a stop would be wrong).

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
    # A long-name discovery link must resolve to its own hashed directory:
    # following a planted one would stop *another* session's live proxy and
    # delete the directory its container bind-mounts.
    if _drop_foreign_discovery_link(sock_dir):
        return False
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
        return False
    try:
        if os.stat(real_dir).st_uid != os.getuid():
            # /tmp is world-writable: anyone can plant a directory with a
            # proxy-shaped name.  Leave it alone (its unlink would fail
            # with EPERM and abort the whole teardown sweep).
            _log.warning("Refusing to stop proxy in a directory owned by "
                         "another user: %s", real_dir)
            return False
    except OSError:
        pass  # already gone — the unlinks below are no-ops
    # Whether this call removed anything: a concurrent release of the same
    # proxy (two of its containers reaped in parallel) finds it gone and
    # must not report it stopped a second time.
    removed_any = False
    with _socket_lifecycle_lock(sock_path):
        if expected_identity is not None:
            current = _socket_identity(sock_path)
            if current is not None and current != expected_identity:
                return False
        existed = os.path.lexists(sock_path)
        # Docker creates a *directory* at a bind-mounted socket path that did
        # not exist (older pm versions mounted the socket file itself).  A
        # container can also make the entry unremovable; the helper reports
        # that instead of raising, so one bad directory cannot abort a sweep.
        stopped = _unlink_socket_file(sock_path)
        removed_any = existed and stopped
        # Metadata describes the daemon we just stopped, and the ownership
        # record says who may release it.  If the socket could not be removed
        # the daemon is still serving it, so keep both for a retry.  They are
        # retired under the same path lock, so a replacement cannot publish
        # between these operations.
        if stopped:
            for meta in (_METADATA_NAME, _OWNER_FILE):
                try:
                    os.unlink(os.path.join(real_dir, meta))
                    removed_any = True
                except OSError:
                    pass
    if not remove_dir:
        _report_stopped(sock_dir, removed_any)
        return stopped
    # Clean up the real directory and its start lock.  The rmdir can fail: a
    # container writes into the bind-mounted socket directory, and an
    # unremovable socket or sidecar stays behind too.
    try:
        os.rmdir(real_dir)
        removed_any = True
    except OSError:
        pass
    # Remove the long-name discovery link only when its directory is gone.
    # The link is how a later process with an empty in-process registry finds
    # the hashed directory to sweep, so unlinking it while the directory
    # survives would leak both past teardown — the same rule
    # _remove_proxy_dirs follows for a directory it keeps.
    if not os.path.lexists(real_dir) and os.path.islink(sock_dir):
        try:
            os.unlink(sock_dir)
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
    _report_stopped(sock_dir, removed_any)
    return stopped


def _report_stopped(sock_dir: str, removed_any: bool) -> None:
    sink = stopped_proxy_sink.get()
    if sink is not None and removed_any:
        sink.append(sock_dir)


def _legacy_shared_sock_dir_path(session_tag: str, pr_id: str) -> str:
    """Socket directory of a shared proxy from before workdir keying.

    Containers created then still mount it, so cleanup must keep finding
    (and releasing) these directories.  Pure computation.
    """
    long_name = f"{session_tag}-{pr_id}"
    long_dir = f"/tmp/{_SOCKET_DIR_PREFIX}{long_name}"
    if len(f"{long_dir}/push.sock") <= 107:
        return long_dir
    dir_hash = hashlib.sha256(long_name.encode()).hexdigest()[:16]
    return f"/tmp/{_SOCKET_DIR_PREFIX}{dir_hash}"


def _pr_dir_candidates(session_tag: str, pr_id: str) -> list[str]:
    """Socket directories a (session, PR) pair may own, found by name.

    Workdir-keyed directories with readable names, plus the pre-keying
    directory.  Hashed workdir-keyed directories have no readable name; they
    are found through their owner record (:func:`list_shared_proxies`).
    """
    base = f"/tmp/{_SOCKET_DIR_PREFIX}{glob.escape(session_tag)}-{glob.escape(pr_id)}"
    found = set(glob.glob(base + "-" + "[0-9a-f]" * 16))
    found.add(_legacy_shared_sock_dir_path(session_tag, pr_id))
    return sorted(found)


def _read_owner(sock_dir: str) -> tuple[str, dict | None]:
    """Read a socket directory's ownership record.

    Returns ``("missing", None)`` when there is none (a legacy directory),
    ``("invalid", None)`` when one exists but cannot be trusted, else
    ``("ok", record)``.  The directory is bind-mounted *writable* into
    containers, so — like :func:`_read_metadata` — never follow a symlink,
    never block on a planted FIFO, and only read a bounded regular file.
    An unreadable or malformed record is never reinterpreted as a missing
    legacy one.
    """
    path = os.path.join(sock_dir, _OWNER_FILE)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "invalid", None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > _METADATA_MAX_BYTES:
            return "invalid", None
        with os.fdopen(fd, encoding="utf-8") as f:
            fd = -1  # fdopen owns it now
            data = json.loads(f.read(_METADATA_MAX_BYTES))
    except (OSError, ValueError):
        return "invalid", None
    finally:
        if fd >= 0:
            os.close(fd)
    return ("ok", data) if isinstance(data, dict) else ("invalid", None)


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
    status, owner = _read_owner(sock_dir)
    if status == "missing":
        return True  # legacy direct lifecycle behavior
    if status != "ok":
        return False  # unreadable existing metadata is not proof of legacy ownership
    domain = owner.get("runtime_domain")
    if domain is None:
        return "runtime_domain" not in owner  # only pre-domain records are legacy
    from pm_core.container_reaper import _runtime_domain
    return domain == _runtime_domain()


def _write_owner_file(sock_dir: str, session_tag: str, pr_id: str,
                      workdir: str) -> None:
    """Record a proxy's runtime and, for shared proxies, its session/PR.

    Hashed socket dirs can't be mapped back to their tag/PR by name; the
    reaper reads this to decide whether any container still needs the proxy.
    Unshared proxies use empty session/PR fields and are not globally swept.
    The temp file comes from ``mkstemp`` (see :func:`_write_metadata` for
    why a predictable name in this container-writable directory is unsafe).
    """
    from pm_core.container_reaper import _runtime_domain
    domain = _runtime_domain()
    if domain is None:
        raise PushProxyError("Cannot record push proxy owner: runtime identity unavailable")
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(dir=sock_dir, prefix=".owner-")
        with os.fdopen(fd, "w") as stream:
            json.dump({"session_tag": session_tag, "pr_id": pr_id,
                       "workdir": workdir, "runtime_domain": domain}, stream)
        os.replace(temporary, Path(sock_dir, _OWNER_FILE))
        temporary = None
    except OSError as exc:
        raise PushProxyError(f"Cannot record push proxy owner in {sock_dir}: {exc}") from exc
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


_LEGACY_NAME_RE = re.compile(
    rf"{re.escape(_SOCKET_DIR_PREFIX)}(.+)-(pr-[0-9a-f]+)(?:-([0-9a-f]{{16}}))?$")


def list_shared_proxies() -> list[dict]:
    """Shared proxy socket dirs on disk.

    Each entry: ``session_tag``, ``pr_id``, ``token`` (the workdir token, or
    None for a directory from before workdir keying), ``sock_dir`` and
    ``sock_path`` (both resolved), ``link`` (the long discovery name, when
    the directory is hashed) and ``runtime_domain``.

    Entries whose owner can't be determined are skipped (left alone), as are
    planted discovery links, foreign-owned directories and directories whose
    location does not match the identity they claim.
    """
    out: list[dict] = []
    seen: set[str] = set()
    parent = os.path.realpath("/tmp")
    for d in sorted(glob.glob(f"/tmp/{_SOCKET_DIR_PREFIX}*")):
        if d.endswith(".lock") or _is_foreign_discovery_link(d):
            continue
        real = os.path.realpath(d)
        if real in seen or not os.path.isdir(real) or not _is_proxy_dir(real, parent):
            continue
        try:
            if os.stat(real).st_uid != os.getuid():
                continue
        except OSError:
            continue
        status, owner = _read_owner(real)
        if status == "invalid":
            # An unreadable or malformed record is not a missing legacy one:
            # fabricating an owner from the directory name would report (and
            # let a future caller act on) an identity nobody verified.
            continue
        if status == "missing":
            # Legacy dir without owner file: only the readable long name
            # (the dir itself, or the symlink to a hashed dir) says whose it
            # is.  A per-container proxy dir (``pm-push-proxy-<container
            # name>``, e.g. an untagged ``pm-impl-pr-…``) has the same shape
            # but serves only its own container — never treat it as shared.
            from pm_core.container import parse_container_name
            base = os.path.basename(d)
            owner = None
            if parse_container_name(base[len(_SOCKET_DIR_PREFIX):]) is None:
                m = _LEGACY_NAME_RE.match(base)
                if m:
                    owner = {"session_tag": m.group(1), "pr_id": m.group(2)}
        if not isinstance(owner, dict):
            continue
        tag, pr_id = owner.get("session_tag"), owner.get("pr_id")
        if not (isinstance(tag, str) and tag and isinstance(pr_id, str) and pr_id):
            continue
        # The directory must sit where its claimed identity puts it, so a
        # record copied (or planted) elsewhere cannot steer a release.
        token = None
        workdir = owner.get("workdir")
        if isinstance(workdir, str) and workdir:
            candidate = _workdir_token(workdir)
            if os.path.realpath(_shared_sock_dir_path(tag, pr_id, candidate)) == real:
                token = candidate
        if token is None and status == "missing":
            m = _LEGACY_NAME_RE.match(os.path.basename(d))
            if m and m.group(3) and os.path.realpath(
                    _shared_sock_dir_path(tag, pr_id, m.group(3))) == real:
                token = m.group(3)
        if token is None and os.path.realpath(
                _legacy_shared_sock_dir_path(tag, pr_id)) != real:
            continue
        link = None
        for candidate in (f"/tmp/{_SOCKET_DIR_PREFIX}{tag}-{pr_id}"
                          + (f"-{token}" if token else ""),):
            if os.path.islink(candidate) and os.path.realpath(candidate) == real:
                link = candidate
        seen.add(real)
        out.append({"session_tag": tag, "pr_id": pr_id, "token": token,
                    "sock_dir": real, "sock_path": os.path.join(real, "push.sock"),
                    "link": link, "runtime_domain": owner.get("runtime_domain")})
    return out


def proxy_key(proxy: dict) -> str:
    """Stable display/failure key for a :func:`list_shared_proxies` entry."""
    key = f"{proxy['session_tag']}/{proxy['pr_id']}"
    return f"{key}/{proxy['token']}" if proxy.get("token") else key


def proxy_key_dir(key: str) -> str | None:
    """Socket directory a :func:`proxy_key` names, or None for other keys.

    Pure computation, so it still answers after the directory is gone. A
    ``tag/pr`` key is from before workdir keying and names the legacy dir.
    """
    parts = key.split("/")
    if len(parts) == 3 and all(parts):
        return _shared_sock_dir_path(*parts)
    if len(parts) == 2 and all(parts):
        return _legacy_shared_sock_dir_path(*parts)
    return None


PROXY_RELEASED = "released"      # stopped (or already absent): nothing pending
PROXY_IN_USE = "in-use"          # a live container still needs it (definitive)
PROXY_UNAVAILABLE = "unavailable"  # runtime inventory unreadable: retry later
PROXY_UNDETERMINED = "undetermined"  # not evaluated: busy lock / foreign owner


def _socket_dir_mounts(info: dict) -> set[str]:
    return {os.path.realpath(mount.get("Source", ""))
            for mount in info.get("Mounts") or []
            if mount.get("Destination") == _CONTAINER_SOCKET_DIR}


def _inspect_batch(names: list[str]) -> list[dict] | None:
    """Inspect every one of *names* in a single runtime call.

    Returns None when the batch cannot be trusted (one of them vanished
    since the inventory, a malformed or incomplete answer); the caller then
    falls back to one inspect per name, which tells absence from failure.
    A timeout is raised: retrying name by name would only wait longer.
    """
    from pm_core import container as cm
    try:
        result = cm._run_runtime("inspect", *names, check=False, timeout=30)
        if result.returncode != 0:
            return None
        rows = json.loads(result.stdout)
    except (OSError, ValueError):
        return None
    if (not isinstance(rows, list) or len(rows) != len(names)
            or not all(isinstance(row, dict) for row in rows)):
        return None
    return rows


def _mounted_socket_dirs(names: set[str]) -> set[str] | None:
    """Real paths of the socket directories *names* bind-mount; None when unknown.

    Each workdir (every QA scenario clone) has its own socket directory, so
    a release checks directories against all of the PR's other containers.
    That runs under the PR's proxy lock, which launches and the other
    releases wait on: one batched inspect for the whole set (shared by every
    directory one decision evaluates) instead of one per container and
    directory keeps a large run-end release from queueing the lock past its
    timeout.
    """
    ordered = sorted(names)
    mounted: set[str] = set()
    try:
        rows = _inspect_batch(ordered) if len(ordered) > 1 else None
        if rows is not None:
            for info in rows:
                mounted |= _socket_dir_mounts(info)
            return mounted
        for name in ordered:
            try:
                info = _proxy_container_info(name)
            except ContainerError:
                return None
            if info is not None:  # None: removed since the inventory
                mounted |= _socket_dir_mounts(info)
    except subprocess.TimeoutExpired:
        return None
    except (AttributeError, TypeError):
        return None
    return mounted


def _release_shared_dir(proxy: dict, users: set[str], sibling_dirs: int,
                        mounted_dirs=None) -> str:
    """Release one shared socket directory unless a container still needs it.

    Caller holds the PR's cross-process proxy lock.  *users* are the PR's
    containers (any state).  When this is the PR's only socket directory
    every user mounts it, so any user keeps it; otherwise the users' actual
    mounts decide (an implementation container must not pin each QA clone's
    proxy, nor a QA clone the implementation proxy).  *mounted_dirs*
    returns those mounts (see :func:`_mounted_socket_dirs`), so one decision
    over several directories inspects the users once.
    """
    sock_dir, sock_path = proxy["sock_dir"], proxy["sock_path"]
    if not _owner_domain_matches(sock_dir):
        return PROXY_UNDETERMINED
    if users:
        if sibling_dirs <= 1:
            return PROXY_IN_USE
        mounted = (mounted_dirs() if mounted_dirs is not None
                   else _mounted_socket_dirs(users))
        if mounted is None:
            return PROXY_UNAVAILABLE
        if os.path.realpath(sock_dir) in mounted:
            return PROXY_IN_USE
    # The start lock keeps a concurrent start of this exact directory (which
    # may not have created its container yet) from losing its socket.
    with _start_lock(sock_dir, blocking=False) as locked:
        if not locked:
            return PROXY_UNDETERMINED
        tag, pr_id, token = proxy["session_tag"], proxy["pr_id"], proxy.get("token")
        key = (_shared_proxy_key(tag, pr_id, token) if token
               else f"{tag}\0{pr_id}")
        with _proxy_lock:
            for cname in _proxy_refs.pop(key, set()):
                _container_to_proxy_key.pop(cname, None)
            _active_proxies.pop(key, None)
        if not _kill_proxy_socket(sock_path, remove_dir=True, lock_held=True):
            # Keep the ownership record (the kill does) so the next pass
            # finds this proxy and retries; report it rather than claim a
            # release while the daemon still serves the socket.
            raise PushProxyError(f"could not remove push proxy socket {sock_path}")
        if os.path.isdir(sock_dir) and not os.path.islink(sock_dir):
            # A container can leave entries in the bind-mounted directory,
            # so the plain rmdir fails.  No container uses it any more (the
            # runtime said so under the PR's proxy lock), so remove it whole.
            shutil.rmtree(sock_dir, ignore_errors=True)
            if os.path.lexists(sock_dir):
                _log.warning("Proxy directory %s survived removal; keeping "
                             "its discovery link", sock_dir)
    link = proxy.get("link")
    if link and os.path.islink(link) and not os.path.lexists(sock_dir):
        try:
            os.unlink(link)
        except OSError:
            pass
    _log.info("Stopped unused shared push proxy for %s", proxy_key(proxy))
    return PROXY_RELEASED


def release_proxy_decision(session_tag: str, pr_id: str,
                           exclude: "set[str] | frozenset[str]" = frozenset(),
                           sock_dir: str | None = None) -> str:
    """Classify (and release when unused) a PR's shared proxies.

    With *sock_dir* only that socket directory is evaluated; otherwise every
    directory of the (session, PR) pair is, and the least settled answer is
    returned.  ``PROXY_IN_USE`` is a *definitive* answer from the runtime
    (any container, any state, any pm process), checked under the
    cross-process proxy lock that ``create_container`` holds from proxy
    start until its container exists — so a concurrent launch can't lose its
    proxy.  Only ``IN_USE`` and ``RELEASED`` say there is no pending work;
    ``UNAVAILABLE`` must stay retryable and ``UNDETERMINED`` (lock busy,
    foreign/unreadable owner record) is neither a release nor proof of use,
    so callers must not clear an earlier failure for it.
    """
    from pm_core import container as container_mod
    # A socket directory derived from a key is never legitimately a foreign
    # link: one planted in world-writable /tmp is unlinked (never followed).
    if sock_dir is not None and _drop_foreign_discovery_link(sock_dir):
        return PROXY_UNDETERMINED
    with container_mod.proxy_lock(session_tag, pr_id, timeout=30) as locked:
        if not locked:
            return PROXY_UNDETERMINED
        dirs = [p for p in list_shared_proxies()
                if p["session_tag"] == session_tag and p["pr_id"] == pr_id]
        targets = dirs
        if sock_dir is not None:
            real = os.path.realpath(sock_dir)
            targets = [p for p in dirs if p["sock_dir"] == real]
            if not targets and os.path.isdir(real):
                # A directory exists but this pass cannot attribute it (an
                # unreadable or foreign owner record): neither released nor
                # proof of use.
                return PROXY_UNDETERMINED
        if sock_dir is None:
            # A directory of this PR whose owner record is unreadable or
            # malformed is not listed; it is neither released nor proof of
            # use, so say so instead of reporting nothing left to do.
            listed = {p["sock_dir"] for p in dirs}
            if any(os.path.isdir(d) and not _is_foreign_discovery_link(d)
                   and os.path.realpath(d) not in listed
                   for d in _pr_dir_candidates(session_tag, pr_id)):
                if not targets:
                    return PROXY_UNDETERMINED
                unattributed = True
            else:
                unattributed = False
        else:
            unattributed = False
        if not targets:
            return PROXY_RELEASED
        users = container_mod.containers_for_pr(session_tag, pr_id)
        if users is None:
            return PROXY_UNAVAILABLE
        users = users - set(exclude)
        mounts: list = []

        def mounted_dirs() -> set[str] | None:
            if not mounts:
                mounts.append(_mounted_socket_dirs(users))
            return mounts[0]

        decisions = [_release_shared_dir(p, users, len(dirs), mounted_dirs)
                     for p in targets]
        if unattributed:
            decisions.append(PROXY_UNDETERMINED)
    for decision in (PROXY_UNAVAILABLE, PROXY_UNDETERMINED, PROXY_IN_USE):
        if decision in decisions:
            return decision
    return PROXY_RELEASED


def release_proxy_if_unused(session_tag: str, pr_id: str,
                            exclude: "set[str] | frozenset[str]" = frozenset(),
                            sock_dir: str | None = None) -> bool | None:
    """Stop the shared (session, PR) proxy if no container still uses it.

    Returns True when stopped, False when still in use (or this pass could not
    evaluate it: busy lock, foreign/unreadable owner record), None when the
    runtime couldn't be queried (nothing done).  See
    :func:`release_proxy_decision` for the exact classification.
    """
    decision = release_proxy_decision(session_tag, pr_id, exclude, sock_dir)
    if decision == PROXY_RELEASED:
        return True
    if decision == PROXY_UNAVAILABLE:
        return None
    return False


def _proxy_container_info(name: str) -> dict | None:
    """Read authoritative proxy mounts, distinguishing absence from failed inspection."""
    from pm_core import container as cm
    try:
        result = cm._run_runtime("inspect", name, check=False, timeout=10)
        if result.returncode != 0:
            if cm._container_absent(result.stderr or ""):
                return None
            raise ContainerError(f"Cannot inspect mounted push proxy for '{name}'")
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError("incomplete container mount inspection")
        return rows[0]
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError) as exc:
        raise ContainerError(f"Cannot inspect mounted push proxy for '{name}': {exc}") from exc


def validate_shared_proxy_mount(name: str, session_tag: str, pr_id: str,
                                workdir: str) -> None:
    """Do not repair an unrelated host socket while reusing an old allocation."""
    from pm_core import container as cm
    info = _proxy_container_info(name)
    try:
        if info is None:
            raise ValueError("container absent")
        labels = (info.get("Config") or {}).get("Labels") or {}
        if labels.get(cm.LABEL_MANAGED) == "1" and (
                labels.get(cm.LABEL_SESSION) != session_tag or labels.get(cm.LABEL_PR) != pr_id):
            raise ValueError("container belongs to a different session/PR")
        expected = os.path.realpath(
            _shared_sock_dir_path(session_tag, pr_id, _workdir_token(workdir)))
        mounts = [m for m in info.get("Mounts") or []
                  if m.get("Destination") == _CONTAINER_SOCKET_DIR]
        if len(mounts) == 1 and os.path.realpath(mounts[0].get("Source", "")) == \
                os.path.realpath(_legacy_shared_sock_dir_path(session_tag, pr_id)):
            # *name* is the immutable id; give the user a runnable command.
            current = str(info.get("Name") or name).lstrip("/")
            raise ValueError("it mounts a push proxy directory from before "
                             "workdir-keyed proxies; once no session uses it, "
                             f"remove it ('{cm._get_runtime()} rm -f {current}') "
                             "so the next launch recreates it")
        if len(mounts) != 1 or os.path.realpath(mounts[0].get("Source", "")) != expected:
            raise ValueError("shared socket directory is missing or belongs to another allocation")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContainerError(f"Cannot verify mounted push proxy for '{name}': {exc}") from exc


def mounted_unshared_proxy(name: str) -> tuple[str, str, str] | None:
    """Resolve the authoritative unshared mount, even when its socket is absent."""
    from pm_core import container as cm
    try:
        info = _proxy_container_info(name)
        if info is None:
            return None
        labels = (info.get("Config") or {}).get("Labels") or {}
        current_name = (info.get("Name") or name).lstrip("/")
        parsed = cm.parse_container_name(current_name)
        if labels.get(cm.LABEL_MANAGED) != "1" and parsed is None:
            return None
        managed = labels.get(cm.LABEL_MANAGED) == "1"
        session_tag = labels.get(cm.LABEL_SESSION) if managed else parsed.session_tag
        pr_id = labels.get(cm.LABEL_PR) if managed else parsed.pr_id()
        if session_tag and pr_id:
            return None  # shared sockets are released through runtime-user checks
        for mount in info.get("Mounts") or []:
            source = Path(mount.get("Source", ""))
            if (mount.get("Destination") != _CONTAINER_SOCKET_DIR
                    or not source.name.startswith(_SOCKET_DIR_PREFIX + cm.CONTAINER_PREFIX)):
                continue
            path = str(source / "push.sock")
            original_name = source.name[len(_SOCKET_DIR_PREFIX):]
            current_name = (info.get("Name") or name).lstrip("/")
            return original_name, path, current_name
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, AttributeError) as exc:
        raise ContainerError(f"Cannot inspect mounted push proxy for '{name}': {exc}") from exc
    return None


def capture_unshared_proxy(name: str) -> tuple[str, str, tuple[int, int, int], str] | None:
    """Capture the mounted socket generation before deleting its container."""
    mount = mounted_unshared_proxy(name)
    if mount is None:
        return None
    original, path, current = mount
    try:
        st = os.stat(path)
        identity = (st.st_dev, st.st_ino, st.st_ctime_ns)
    except FileNotFoundError:
        identity = (0, 0, 0)  # mount is authoritative even without a socket
    except OSError as exc:
        # An unverifiable socket generation cannot authorize cleanup. Defer
        # removal with a classified error (retried later) instead of unlinking
        # a socket we cannot identify or, worse, reporting success while
        # stranding the socket and its proxy daemon.
        raise ContainerError(
            f"Cannot capture the mounted push proxy generation at {path}: "
            f"{exc}") from exc
    return original, path, identity, current


def repair_unshared_proxy(name: str, workdir: str, allowed_branch: str) -> str:
    """Repair the socket actually mounted by an existing allocation."""
    from pm_core import container as cm
    mount = mounted_unshared_proxy(name)
    if mount is None:
        raise ContainerError(f"Cannot verify mounted push proxy for '{name}'")
    original, path, current = mount
    sock_dir = str(Path(path).parent)
    if not _owner_domain_matches(sock_dir):
        raise PushProxyError("Existing unshared push proxy belongs to a different or "
                             "unverifiable runtime; refusing cross-runtime reuse")
    guard = (cm.launch_lock(original, timeout=0) if original != current
             else contextlib.nullcontext(True))
    with guard as locked:
        if not locked:
            raise ContainerError(f"Push proxy owner '{original}' is being launched")
        with _start_lock(sock_dir):
            if not proxy_is_alive(path):
                if original != current and cm.current_container_id(original) != "":
                    raise ContainerError(f"Cannot repair another allocation's proxy '{original}'")
                _write_owner_file(sock_dir, "", "", workdir)
                if not _start_proxy_subprocess(path, workdir, allowed_branch):
                    raise PushProxyError(
                        f"push proxy did not become ready at {path} "
                        f"(workdir={workdir}, branch={allowed_branch})")
        return path


def _unshared_release_path(proxy) -> Path:
    from pm_core import container as cm, container_reaper
    key = hashlib.sha256(json.dumps(
        [container_reaper._runtime_domain(), proxy], sort_keys=True).encode()).hexdigest()
    return cm.container_state_dir() / "proxy-releases" / f"{key}.json"


def defer_unshared_release(proxy, name: str = "") -> Path:
    """Persist socket identity before attempting post-removal cleanup."""
    from pm_core import container as cm, container_reaper
    domain = container_reaper._runtime_domain()
    if domain is None:
        raise ContainerError("Cannot record unshared proxy release: runtime domain unknown; "
                             "preserving container for cleanup retry")
    path = _unshared_release_path(proxy)
    labels = {}
    if name:
        try:
            inspected = cm._run_runtime("inspect", name, check=False, timeout=10)
            if inspected.returncode != 0:
                raise ContainerError(f"Cannot record proxy ownership for '{name}'")
            rows = json.loads(inspected.stdout)
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise ValueError("incomplete container inspection")
            labels = (rows[0].get("Config") or {}).get("Labels") or {}
            if not isinstance(labels, dict):
                labels = {}
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError,
                AttributeError) as exc:
            # Callers expect ContainerError from a failed removal; a raw probe
            # timeout or malformed inspection would bypass their retry path.
            raise ContainerError(
                f"Cannot record proxy ownership for '{name}': {exc}") from exc
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".release-")
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump({"proxy": proxy, "runtime_domain": domain,
                           "session_tag": labels.get("pm.session_tag"),
                           "pr_id": labels.get("pm.pr_id")}, stream)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    except OSError as exc:
        # The record must exist before the container is deleted; a full or
        # unwritable state dir defers removal (preserving the allocation for a
        # retry) and must not escape as a raw OSError.
        raise ContainerError(
            f"Cannot record unshared proxy release: {exc}") from exc
    return path


def retry_unshared_releases(scope, failures: dict[str, str]) -> list[str]:
    """Retry only captured, domain-bound releases; never sweep arbitrary sockets."""
    from pm_core import container as cm, container_reaper
    domain = container_reaper._runtime_domain()
    released = []
    if domain is None:
        return released
    for record in (cm.container_state_dir() / "proxy-releases").glob("*.json"):
        key = f"unshared {record.stem}"
        try:
            data = json.loads(record.read_text())
        except (OSError, ValueError) as exc:
            # A record we cannot parse names no allocation we could release.
            # Reporting it as a retryable failure would leave `pm container
            # reap` failing on every pass with no way to clear it.
            _log.warning("ignoring unreadable push-proxy release record %s: %s",
                         record, exc)
            continue
        proxy = data.get("proxy") if isinstance(data, dict) else None
        if not (isinstance(proxy, (list, tuple)) and len(proxy) == 4):
            _log.warning("ignoring malformed push-proxy release record %s", record)
            continue
        original, path, identity, current = proxy
        if not (isinstance(original, str) and isinstance(path, str)
                and isinstance(current, str)
                and isinstance(identity, (list, tuple)) and len(identity) == 3
                and all(isinstance(part, int) and not isinstance(part, bool)
                        for part in identity)):
            _log.warning("ignoring malformed push-proxy release record %s", record)
            continue
        try:
            if data.get("runtime_domain") != domain:
                continue
            parsed = cm.parse_container_name(original)
            if scope.names is not None and not {original, current} & scope.names:
                continue
            tag = data.get("session_tag") or (parsed.session_tag if parsed else None)
            pr_id = data.get("pr_id") or (parsed.pr_id() if parsed else None)
            if scope.session_tag and tag != scope.session_tag:
                continue
            if scope.pr_id and pr_id != scope.pr_id:
                continue
            with cm.launch_lock(current, timeout=0) as locked:
                if not locked:
                    failures[f"push proxy {key}"] = "unshared proxy cleanup deferred: owner lock busy"
                    continue
                # Even if the socket was replaced, never inspect/delete by a
                # stale name without checking the captured socket generation.
                current_identity = _socket_identity(path)
                # A missing socket does not retire owner.json. Retry the
                # guarded metadata cleanup too, rather than losing the request.
                same = current_identity is None or current_identity == tuple(identity)
                if same:
                    owner = cm.current_container_id(current)
                    if owner is None:
                        raise ContainerError("unshared proxy cleanup deferred: owner identity unknown")
                    # Reusing the captured name does not imply using this
                    # socket: a renamed replacement may mount a distinct proxy.
                    # The locked release helper checks actual mounted users.
                    if not release_captured_unshared_proxy((original, path, tuple(identity), current)):
                        failures[f"push proxy {key}"] = "unshared proxy cleanup deferred: another owner or launch remains"
                        continue
                record.unlink(missing_ok=True)
                released.append(key)
        except Exception as exc:
            failures[f"push proxy {key}"] = str(exc)
    return released


def unshared_proxy_in_use(path: str) -> bool:
    """A renamed allocation may still mount another name's socket directory."""
    from pm_core import container as cm
    # Do not filter by source volume: Podman 3.x only promises volume names
    # and mount destinations, which can omit bind-mounted users of this path.
    try:
        listing = cm._run_runtime("ps", "-aq", check=False, timeout=30)
        if listing.returncode != 0:
            raise ContainerError("Cannot inventory mounted push proxy users")
        ids = listing.stdout.split()
        if not ids:
            return False
        inspected = cm._run_runtime("inspect", "--format", "{{json .Mounts}}",
                                    *ids, check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Removal callers expect ContainerError from a failed cleanup and retry
        # it; a raw probe timeout would escape after the container was already
        # removed and be reported as an unrelated failure.
        raise ContainerError(
            f"Cannot inventory mounted push proxy users: {exc}") from exc
    rows = inspected.stdout.splitlines()
    if inspected.returncode != 0 or len(rows) != len(ids):
        raise ContainerError("Cannot inspect mounted push proxy users")
    directory = os.path.realpath(str(Path(path).parent))
    try:
        for row in rows:
            mounts = json.loads(row)
            if mounts is None:
                # Go renders a container with no explicit mounts as ``null``
                # (Podman), not ``[]``. Treat it as empty rather than failing
                # the whole inventory — one such container would otherwise make
                # every unshared-proxy cleanup retry fail permanently.
                continue
            if not isinstance(mounts, list):
                raise ValueError("invalid mounts")
            if any(os.path.realpath(mount.get("Source", "")) == directory
                   for mount in mounts):
                return True
    except (ValueError, TypeError, AttributeError) as exc:
        raise ContainerError("Cannot inspect mounted push proxy users") from exc
    return False


def release_captured_unshared_proxy(
        proxy: tuple[str, str, tuple[int, int, int], str]) -> bool:
    """Release a captured mount without stealing its original name's proxy."""
    from pm_core import container as cm
    original_name, path, identity, current_name = proxy
    if not _owner_domain_matches(str(Path(path).parent)):
        return False

    def _kill() -> None:
        # The container was already removed, so a socket/owner-file failure
        # must stay a classified, retryable cleanup error (the durable release
        # record is preserved) rather than escape as a raw OSError that the
        # caller would report as a failed removal of a container that is gone.
        try:
            stopped = _kill_proxy_socket(path, expected_identity=identity)
        except OSError as exc:
            raise ContainerError(
                f"Cannot release push proxy socket at {path}: {exc}") from exc
        if not stopped and _socket_identity(path) == tuple(identity):
            # Still the captured socket: it could not be removed (a replaced
            # one is not ours and is correctly left alone).
            raise ContainerError(f"Cannot release push proxy socket at {path}")

    if original_name == current_name:
        # The caller already holds this allocation's launch lock. Its socket
        # may nevertheless remain mounted by a previously renamed allocation.
        if unshared_proxy_in_use(path):
            return False
        _kill()
        return True
    # Rename gives the old pathname a second potential owner. Serialize with
    # launch of the original name, and do not trust a socket captured after a
    # replacement has already published it. Never wait while holding the other
    # allocation's lock (two renamed allocations could otherwise deadlock).
    with cm.launch_lock(original_name, timeout=0) as locked:
        if not locked:
            return False
        current = cm.current_container_id(original_name)
        if current is None:
            raise ContainerError(f"Cannot verify proxy owner '{original_name}' after removal")
        # A separately created allocation can be renamed onto the original
        # name while mounting its own distinct proxy. The locked name check
        # excludes unknown identity; actual mounts decide whether this captured
        # directory still has users, including any original-name replacement.
        if unshared_proxy_in_use(path):
            return False
        _kill()
        return True


def forget_unshared_proxy(container_name: str, socket_path: str) -> None:
    """Drop local bookkeeping without touching an allocation's mounted socket."""
    with _proxy_lock:
        if (_container_to_proxy_key.get(container_name) == container_name
                and _active_proxies.get(container_name) == socket_path):
            _container_to_proxy_key.pop(container_name, None)
            _active_proxies.pop(container_name, None)


def _stop_unshared_proxy(container_name: str) -> None:
    """Stop a per-container proxy once no allocation still mounts it.

    A per-container proxy (no session tag or PR, e.g. qa-debug or legacy
    untagged containers) serves only its own container, but a renamed
    allocation may still mount this name's directory.
    """
    sock_dir = os.path.join(tempfile.gettempdir(),
                            f"{_SOCKET_DIR_PREFIX}{container_name}")
    sock_path = os.path.join(sock_dir, "push.sock")
    # A per-container socket directory is never legitimately a symlink, so
    # one planted at its name in world-writable /tmp must not be followed:
    # _start_lock would resolve it and create/lock ``<target>.lock`` at a
    # path another user chose.  Unlink the link (never its target).
    if _drop_foreign_discovery_link(sock_dir):
        return
    if not os.path.isdir(sock_dir) or os.path.islink(sock_dir):
        return  # nothing on disk left to stop
    # A concurrent start of this container's proxy owns the socket until it
    # releases the lock.
    with _start_lock(sock_dir, blocking=False) as locked:
        if not locked:
            return
        with _proxy_lock:
            if container_name in _container_to_proxy_key:
                return  # re-registered by a concurrent start
            _active_proxies.pop(container_name, None)
        if not _owner_domain_matches(sock_dir):
            return
        if ((os.path.lexists(sock_path)
             or os.path.lexists(os.path.join(sock_dir, _OWNER_FILE)))
                and unshared_proxy_in_use(sock_path)):
            return
        # lock_held=True: we own this directory's start lock, so the lock
        # file must be unlinked here (the LOCK_NB probe in _clear_lock_file
        # would see our own lock and skip it).
        _kill_proxy_socket(sock_path, remove_dir=True, lock_held=True)


def stop_push_proxy(container_name: str) -> None:
    """Stop and clean up the push proxy for a container.

    For shared proxies the proxy is only stopped when no container — in this
    process or any other — still uses its socket directory (see
    :func:`release_proxy_if_unused`); in-process references only say *this*
    process still has users.  When the runtime can't be queried, keep the
    proxy for a later reconcile.
    """
    with _proxy_lock:
        key = _container_to_proxy_key.pop(container_name, None)
        local_refs_left = False
        if key is not None and "\0" in key:
            refs = _proxy_refs.get(key)
            if refs is not None:
                refs.discard(container_name)
                local_refs_left = bool(refs)
                if not refs:
                    del _proxy_refs[key]

    if key is None:
        # Not started by this process — derive the shared key from the name.
        from pm_core.container import parse_container_name
        parsed = parse_container_name(container_name)
        pid = parsed.pr_id() if parsed else None
        if parsed and parsed.session_tag and pid:
            release_proxy_if_unused(parsed.session_tag, pid)
        _stop_unshared_proxy(container_name)
        return

    if "\0" in key:
        if local_refs_left:
            return  # this process still has a container on the proxy
        parts = key.split("\0")
        if len(parts) != 3:
            return  # malformed key — nothing safe to derive
        stag, pid, token = parts
        # Local references cannot prove that another process has no users.
        # Unknown runtime inventory leaves the shared proxy for a later pass.
        release_proxy_if_unused(stag, pid,
                                sock_dir=_shared_sock_dir_path(stag, pid, token))
        return

    # Legacy key = container_name: this proxy serves only this container.
    _stop_unshared_proxy(key)


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
    A long-name discovery symlink must also resolve to the hashed directory
    derived from its *own* name — a link pointing at another session's proxy
    directory is removed, never followed.  Directories owned by another user
    are left alone too — ``/tmp`` is world-writable, so anyone can create a
    matching name there.

    A directory whose proxy is alive, or whose start lock is held by a
    proxy start in flight, is left in place: removing it would delete a
    socket a container still bind-mounts.  Its long-name discovery symlink
    is kept too: that link is how a *later* process finds a hashed
    directory to sweep, so unlinking it while keeping the directory would
    leak the proxy past teardown after a restart.
    """
    # Resolve the parent too: on platforms where /tmp is a symlink (macOS:
    # /tmp -> /private/tmp) the literal glob parent never matches the
    # resolved entry path, so every directory would be refused and teardown
    # would leak them.  _kill_proxy_socket resolves both sides already.
    parent = os.path.realpath(os.path.dirname(glob_pattern))

    def _unlink_link(link: str) -> None:
        """Remove *link* itself when it is a symlink; never its target."""
        if not os.path.islink(link):
            return
        try:
            os.unlink(link)
        except OSError:
            pass

    def _unlink_stale_entry(entry: str) -> None:
        """Remove a non-directory entry squatting a proxy-shaped name.

        A symlink is removed (never its target, as above); a regular file is
        removed only when it is ours — ``/tmp`` is world-writable.  Leaving
        such a file behind keeps the long discovery name unusable forever,
        so a later registry-less sweep could not find the hashed directory
        (the leak this sweep exists to prevent).
        """
        if os.path.islink(entry):
            _unlink_link(entry)
            return
        try:
            st = os.lstat(entry)
        except OSError:
            return
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            return
        try:
            os.unlink(entry)
        except OSError:
            pass

    for path in glob.glob(glob_pattern):
        if path.endswith(".lock"):
            continue
        # A discovery link may only lead to its own hashed directory; a
        # planted one is removed (never followed) so the sweep cannot delete
        # another session's proxy directory.
        if _drop_foreign_discovery_link(path):
            continue
        real = os.path.realpath(path)
        if not _is_proxy_dir(real, parent):
            _log.warning("Refusing to remove non-proxy directory %s -> %s",
                         path, real)
            _unlink_link(path)
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
            _unlink_stale_entry(path)
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
            # rmtree is best-effort (a container can leave entries the host
            # cannot remove), so only drop the discovery link once the
            # directory is really gone — otherwise a later process with an
            # empty registry has no way to find the hashed directory.
            if os.path.lexists(real):
                _log.warning("Proxy directory %s survived removal; keeping "
                             "its discovery link", real)
            else:
                _unlink_link(path)
            # Safe: we hold the lock, so no other process is using it.
            try:
                os.unlink(real + ".lock")
            except OSError:
                pass
    for lock in glob.glob(glob_pattern + ".lock"):
        _clear_lock_file(lock)


def _stop_socket_under_lock(sock_path: str) -> bool:
    """Stop the proxy at *sock_path* unless its start is in flight.

    Returns True when the socket was stopped.  Taking the per-directory
    start lock keeps a sweep from killing a proxy that another process is
    creating right now (and from deleting a directory a container
    bind-mounts) — the S18 failure through the sweep.
    """
    sock_dir = os.path.dirname(sock_path)
    # Check the discovery link *before* taking a lock: resolving a planted
    # link would make us lock — and then stop — another session's proxy.
    if _drop_foreign_discovery_link(sock_dir):
        return False
    if not os.path.isdir(sock_dir):
        return False  # nothing on disk (registry entry already swept)
    with _start_lock(sock_dir, blocking=False) as locked:
        if not locked:
            _log.info("Proxy start in flight; not stopping: %s", sock_path)
            return False
        return _kill_proxy_socket(sock_path, lock_held=True)


def stop_all_proxies() -> None:
    """Stop all running push proxies."""
    with _proxy_lock:
        _active_proxies.clear()
        _proxy_refs.clear()
        _container_to_proxy_key.clear()

    # Kill all proxy sockets on disk
    for sock in sorted(glob.glob(f"/tmp/{_SOCKET_DIR_PREFIX}*/push.sock")):
        _stop_socket_under_lock(sock)
    _remove_proxy_dirs(f"/tmp/{_SOCKET_DIR_PREFIX}*")


def stop_session_proxies(session_tag: str) -> int:
    """Release unused shared proxies for this exact session/runtime.

    Session container removal can fail or race a new launch. Never unlink its
    sockets unconditionally afterwards; the locked runtime inventory is the
    authority, not the caller's earlier cleanup result or local references.
    Per-container proxies are released by their container's removal.

    Returns the number of proxies stopped.  A hashed socket directory is
    reachable through two spellings (its discovery link and the hashed
    path); :func:`list_shared_proxies` collapses them, so each is counted once.
    """
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

    # A long discovery name pointing anywhere but its own hashed directory
    # was planted (or is stale): unlink the link itself, never its target.
    # The tag is escaped: it may contain glob metacharacters.
    for path in glob.glob(f"/tmp/{_SOCKET_DIR_PREFIX}{glob.escape(session_tag)}-*"):
        _drop_foreign_discovery_link(path)

    from pm_core.container_reaper import _runtime_domain, runtime_domain_scope
    count = 0
    with runtime_domain_scope():
        domain = _runtime_domain()
        if domain is None:
            return 0
        for proxy in list_shared_proxies():
            # Unknown/legacy domains are preserved: this runtime's empty
            # inventory says nothing about another runtime's users.
            if (proxy["session_tag"] != session_tag
                    or proxy.get("runtime_domain") != domain):
                continue
            try:
                if release_proxy_if_unused(session_tag, proxy["pr_id"],
                                           sock_dir=proxy["sock_dir"]):
                    count += 1
            except ContainerError:
                _log.warning("Could not release session proxy %s",
                             proxy_key(proxy), exc_info=True)

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
    def _resolve(path: str) -> str | None:
        """Return the realpath if the socket exists, else None.

        A directory reached through a discovery symlink that points
        somewhere other than its own hash is ignored: a planted link must
        not make this lookup hand back *another* session's socket (the
        caller would then believe its own dead proxy is alive and skip the
        restart).
        """
        if _is_foreign_discovery_link(os.path.dirname(path)):
            return None
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

    # Install handlers before publishing a usable socket: callers may stop or
    # replace the daemon as soon as its readiness probe succeeds.
    import signal as _signal
    _stop = threading.Event()
    _signal.signal(_signal.SIGTERM, lambda *_: _stop.set())
    _signal.signal(_signal.SIGINT, lambda *_: _stop.set())
    if not proxy.start():
        # Another daemon already serves this socket; do not steal it.
        _sys.exit(0)

    # Block until the socket is removed/replaced or we get a signal
    _wait_for_socket_exit(proxy, _stop)
    proxy.stop()
