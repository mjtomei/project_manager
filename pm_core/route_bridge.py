"""Unix-socket bridge from QA containers to a host-loopback model router.

QA containers run under slirp4netns, so the host router on
``127.0.0.1:<port>`` is unreachable from inside them, and publishing it on a
routable address would expose a credential-bearing endpoint.  Instead:

  host:       router.sock (0600, in a 0700 dir)  ->  127.0.0.1:<port>
  container:  127.0.0.1:<port>  ->  /run/pm-route/router.sock (bind mount)

so Claude inside the container uses the same ``ANTHROPIC_BASE_URL`` as on the
host.  Only processes that can open the socket (the user, and containers it
is mounted into) reach the router; nothing changes for other containers.

This module is stdlib-only because the ``ensure`` side runs inside the
container from ``/opt/pm-src``.

Run as a file in isolated mode (``python3 -I .../route_bridge.py``) so a
``pm_core`` in the caller's cwd cannot shadow this one:
  python3 -I route_bridge.py host <socket> <host> <port>
  python3 -I route_bridge.py ensure <socket> <port> [<route-name>]
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time

CONTAINER_SOCKET_DIR = "/run/pm-route"
SOCKET_NAME = "router.sock"

# Exit code from ``ensure`` when the route is unusable (claude never starts).
EXIT_ROUTE_UNAVAILABLE = 3

_BUF = 65536


def _pump(src: socket.socket, dst: socket.socket) -> None:
    try:
        while True:
            data = src.recv(_BUF)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        # Half-close so the peer sees EOF but can still send its reply.
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _splice(a: socket.socket, b: socket.socket) -> None:
    t = threading.Thread(target=_pump, args=(b, a), daemon=True)
    t.start()
    _pump(a, b)
    t.join()
    for s in (a, b):
        try:
            s.close()
        except OSError:
            pass


# Bounds only connection setup to the router.  Streams must have no
# timeout: a thinking model can pause far longer between chunks.
CONNECT_TIMEOUT = 10


def _connect_tcp(host: str, port: int) -> socket.socket:
    s = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
    s.settimeout(None)
    return s


def _connect_unix(path: str) -> socket.socket:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(CONNECT_TIMEOUT)
    s.connect(path)
    s.settimeout(None)
    return s


def _serve(listener: socket.socket, connect, still_wanted) -> None:
    """Accept on *listener*, splice each client with ``connect()``.

    Both spliced sockets are blocking with no timeout for the stream's
    lifetime; ``connect`` applies its own setup timeout only.
    """
    listener.settimeout(1.0)
    while still_wanted():
        try:
            client, _ = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        client.settimeout(None)

        def _handle(c=client):
            try:
                upstream = connect()
            except OSError:
                c.close()
                return
            _splice(c, upstream)

        threading.Thread(target=_handle, daemon=True).start()


def unix_connectable(path: str, timeout: float = 2.0) -> bool:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(path)
        s.close()
        return True
    except OSError:
        return False


def tcp_connectable(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Host side
# ---------------------------------------------------------------------------

def run_host_bridge(sock_path: str, host: str, port: int) -> None:
    """Serve *sock_path* -> host:port until the socket file is removed."""
    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old_umask = os.umask(0o177)
    try:
        listener.bind(sock_path)
    finally:
        os.umask(old_umask)
    os.chmod(sock_path, 0o600)
    listener.listen(64)
    ino = os.stat(sock_path).st_ino

    def _still_wanted() -> bool:
        # Exit when the socket is removed or replaced by a newer bridge.
        try:
            return os.stat(sock_path).st_ino == ino
        except OSError:
            return False

    _serve(listener, lambda: _connect_tcp(host, port), _still_wanted)
    listener.close()


# ---------------------------------------------------------------------------
# Container side
# ---------------------------------------------------------------------------

def _fail(msg: str) -> int:
    print(f"pm work route: {msg}", file=sys.stderr, flush=True)
    return EXIT_ROUTE_UNAVAILABLE


def ensure_container_forwarder(sock_path: str, port: int,
                               route: str = "") -> int:
    """Make 127.0.0.1:*port* reach the router through *sock_path*.

    Idempotent: returns 0 immediately when the port already answers (a
    forwarder from an earlier launch, or host networking where the port is
    the router itself).  Otherwise forks a detached forwarder and waits for
    it to listen.  Returns non-zero with a remedy on stderr when the route
    is unusable, so ``ensure && claude`` never starts Claude without it.
    """
    label = f" {route!r}" if route else ""
    remedy = ("Remedy: on the host run 'pm provider test "
              f"{route or '<route>'} --container' and fix what it reports; "
              "if the socket is not mounted in this container, restart QA "
              "(or remove the container and launch the session again) so "
              "the container is recreated with it.")
    if not os.path.exists(sock_path):
        return _fail(f"route{label} socket {sock_path} is not mounted in "
                     f"this container. {remedy}")
    if not unix_connectable(sock_path):
        return _fail(f"route{label} host bridge at {sock_path} is not "
                     f"accepting connections. {remedy}")
    if tcp_connectable("127.0.0.1", port, timeout=1.0):
        return 0

    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(64)
    except OSError as exc:
        return _fail(f"cannot listen on 127.0.0.1:{port} for route{label}: "
                     f"{exc}. {remedy}")

    pid = os.fork()
    if pid == 0:
        # Detached forwarder: new session, no inherited terminal, so the
        # ``exec -it`` pane is not held open by it.
        try:
            os.setsid()
            devnull = os.open(os.devnull, os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(devnull, fd)
            if os.fork() > 0:
                os._exit(0)

            # The socket file may be briefly absent while the host bridge
            # restarts; the mounted directory only goes with the container.
            sock_dir = os.path.dirname(sock_path)
            _serve(listener, lambda: _connect_unix(sock_path),
                   lambda: os.path.isdir(sock_dir))
        finally:
            os._exit(0)
    listener.close()
    os.waitpid(pid, 0)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if tcp_connectable("127.0.0.1", port, timeout=0.5):
            return 0
        time.sleep(0.05)
    return _fail(f"forwarder for route{label} did not start on "
                 f"127.0.0.1:{port}. {remedy}")


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[0] == "host":
        run_host_bridge(argv[1], argv[2], int(argv[3]))
        return 0
    if len(argv) in (3, 4) and argv[0] == "ensure":
        return ensure_container_forwarder(
            argv[1], int(argv[2]), argv[3] if len(argv) == 4 else "")
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
