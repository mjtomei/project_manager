"""Local HTTP server for the all-PR behavior dashboard.

Builds the dashboard HTML on every ``/`` request so liveness is dynamic —
a new ``report.html`` shows up on the next page load with no regeneration
step. Per-PR ``report.html`` and its evidence siblings are served straight
from ``<captures>/<pr_id>/...``.

Bound to ``127.0.0.1`` by default. Foreground / blocking; Ctrl-C shuts the
server down cleanly. Stdlib only — no extra deps.
"""

from __future__ import annotations

import http.server
import logging
import os
import re
import sys
import threading
from pathlib import Path

_log = logging.getLogger("pm.dashboard_server")

DEFAULT_PORT = 8765
DEFAULT_BIND = "127.0.0.1"

# Single byte range: "bytes=start-end", "bytes=start-", or "bytes=-suffix".
_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_COPY_CHUNK = 64 * 1024


def _make_handler(pm_root: Path, captures_root_dir: Path):
    """Return a request handler subclass bound to *pm_root* and *captures_root_dir*.

    The handler renders ``/`` (and ``/index.html``) dynamically from
    ``behavior_report.gather_dashboard_rows`` + ``render_dashboard_html``;
    everything else is served by ``SimpleHTTPRequestHandler`` rooted at
    ``captures_root_dir`` so per-PR reports and their evidence siblings
    resolve naturally.
    """
    captures_str = str(captures_root_dir)

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=captures_str, **kwargs)

        def _serve_dashboard(self) -> None:
            from pm_core import behavior_report, store
            try:
                data = store.load(pm_root)
                rows = behavior_report.gather_dashboard_rows(
                    data, captures_root_dir)
                page_html = behavior_report.render_dashboard_html(rows)
            except Exception as exc:  # noqa: BLE001
                _log.exception("failed to build dashboard")
                self.send_error(500, f"build dashboard: {exc}")
                return
            body = page_html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 — stdlib hook name
            # Strip query string for routing; leave the fallback handler
            # to resolve real paths.
            path = self.path.split("?", 1)[0]
            if path in ("", "/", "/index.html"):
                self._serve_dashboard()
                return
            if self.headers.get("Range") and self._serve_range():
                return
            super().do_GET()

        def end_headers(self):
            # Advertise range support on static-file responses so players
            # (Safari <video> in particular) know they can seek/stream.
            if getattr(self, "_ranges_ok", False):
                self.send_header("Accept-Ranges", "bytes")
            super().end_headers()

        def send_head(self):
            self._ranges_ok = True
            try:
                return super().send_head()
            finally:
                self._ranges_ok = False

        def _serve_range(self) -> bool:
            """Serve a single-byte-range request (RFC 9110 §14).

            Safari refuses to stream ``<video>`` from a server that answers
            Range requests with a 200 full body. Returns True when the
            request was handled (206 or 416); False falls through to the
            base full-file handler (which is a valid way to ignore an
            unsupported/multi-part Range).
            """
            m = _RANGE_RE.match(self.headers.get("Range", "").strip())
            if not m:
                return False
            fs_path = self.translate_path(self.path.split("?", 1)[0])
            if not os.path.isfile(fs_path):
                return False
            try:
                f = open(fs_path, "rb")
            except OSError:
                return False
            with f:
                size = os.fstat(f.fileno()).st_size
                start_s, end_s = m.groups()
                if start_s:
                    start = int(start_s)
                    end = int(end_s) if end_s else size - 1
                elif end_s:  # suffix range: last N bytes
                    start = max(0, size - int(end_s))
                    end = size - 1
                else:
                    return False
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return True
                end = min(end, size - 1)
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", self.guess_type(fs_path))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header(
                    "Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
                self.end_headers()
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(_COPY_CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            return True

        def log_message(self, format, *args):  # noqa: A002 — stdlib hook name
            _log.info("%s %s", self.address_string(), format % args)

    return _Handler


class _QuietDisconnectServer(http.server.ThreadingHTTPServer):
    """ThreadingHTTPServer that doesn't traceback on client disconnects.

    Video players abort in-flight responses as a matter of course — Safari
    issues a burst of Range requests while scrubbing and drops the ones it
    no longer needs — so a mid-write ``BrokenPipeError`` /
    ``ConnectionResetError`` is normal operation, not an error worth a
    console traceback per request.
    """

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            _log.debug("client %s disconnected mid-response", client_address)
            return
        super().handle_error(request, client_address)


def serve(*, pm_root: Path, captures_root_dir: Path,
          host: str = DEFAULT_BIND, port: int = DEFAULT_PORT,
          open_browser: bool = False) -> None:
    """Start the dashboard server and block until interrupted.

    Args:
        pm_root: Path to the pm state root (``state_root()``).
        captures_root_dir: Captures root directory served as static files
            (typically ``~/.pm/sessions/<tag>/captures/``).
        host: Bind address. Defaults to loopback; pass an explicit value to
            expose on a non-loopback interface.
        port: TCP port. ``0`` lets the OS pick a free port.
        open_browser: When True, launch the user's browser at the served URL
            once the server is listening.
    """
    handler_cls = _make_handler(pm_root, captures_root_dir)
    try:
        httpd = _QuietDisconnectServer((host, port), handler_cls)
    except OSError as exc:
        # Most commonly "address already in use" when a dashboard is already
        # running on this port — surface a one-line hint instead of a traceback.
        raise SystemExit(
            f"pm dashboard: cannot bind {host}:{port} "
            f"({exc.strerror or exc}). Is a dashboard already running? "
            f"Pass --port 0 to pick a free port, or --port N for another."
        )
    actual_host, actual_port = httpd.server_address[:2]
    url = f"http://{actual_host}:{actual_port}/"
    print(f"pm dashboard: serving at {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Thread(
            target=_open_url_after_listen, args=(url,), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\npm dashboard: shutting down")
    finally:
        httpd.server_close()


def _open_url_after_listen(url: str) -> None:
    """Open *url* in the user's browser; runs on a daemon thread."""
    import webbrowser
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        _log.warning("could not open a browser; open %s manually", url)
