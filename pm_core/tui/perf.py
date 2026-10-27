"""Opt-in keystroke-latency instrumentation for the TUI.

Enable by launching the TUI with ``PM_PERF_DEBUG=1`` in the environment.  When
enabled it:

* times each keystroke end-to-end (key press → post-refresh callback, i.e. the
  felt latency) with a breakdown of the phases handled in our own code
  (``on_key`` body, scroll, band cull) versus the remaining time spent inside
  Textual (compositor / message pump);
* surfaces that timing live in the TUI log line for slow keys; and
* lowers ``loop.slow_callback_duration`` so asyncio logs *which* callback blocked
  the event loop.

Everything is written to ``<debug_dir>/<session>-perf.log``.  Threshold in ms
is configurable via ``PM_PERF_DEBUG_MS`` (default 50).  When ``PM_PERF_DEBUG``
is unset, all hooks are no-ops with negligible overhead.
"""

import logging
import os

ENABLED = bool(os.environ.get("PM_PERF_DEBUG"))
THRESHOLD_MS = float(os.environ.get("PM_PERF_DEBUG_MS", "50"))

_logger: logging.Logger | None = None


def _get_logger(session: str | None = None) -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    from pm_core.paths import debug_dir
    log = logging.getLogger("pm.perf")
    log.setLevel(logging.INFO)
    log.propagate = False
    if not log.handlers:
        path = debug_dir() / f"{session or 'pm'}-perf.log"
        handler = logging.FileHandler(path)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(handler)
    _logger = log
    return log


def setup_event_loop(session: str | None = None) -> None:
    """Enable asyncio slow-callback logging routed into the perf log."""
    if not ENABLED:
        return
    log = _get_logger(session)
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        loop.slow_callback_duration = THRESHOLD_MS / 1000.0
        alog = logging.getLogger("asyncio")
        alog.setLevel(logging.WARNING)
        for handler in log.handlers:
            if handler not in alog.handlers:
                alog.addHandler(handler)
        log.info("perf enabled: threshold=%.0fms slow_callback_duration=%.3fs "
                 "session=%s", THRESHOLD_MS, loop.slow_callback_duration, session)
    except Exception as exc:  # pragma: no cover - defensive
        log.info("perf setup failed: %s", exc)


def log(message: str) -> None:
    """Write a line to the perf log (no-op unless enabled)."""
    if ENABLED:
        _get_logger().info(message)
