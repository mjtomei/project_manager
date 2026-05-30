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
import threading
from pathlib import Path

_log = logging.getLogger("pm.dashboard_server")

DEFAULT_PORT = 8765
DEFAULT_BIND = "127.0.0.1"


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
            super().do_GET()

        def log_message(self, format, *args):  # noqa: A002 — stdlib hook name
            _log.info("%s %s", self.address_string(), format % args)

    return _Handler


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
    httpd = http.server.ThreadingHTTPServer((host, port), handler_cls)
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
