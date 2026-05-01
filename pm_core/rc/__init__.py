"""Remote-control viewer/editor package.

Hosts a small FastAPI server (``pm_core.rc.server``) that serves a
mobile-friendly document viewer and exposes a JSON API consumed by the
``pm rc`` CLI subcommands defined in ``pm_core.cli.rc``.

This package is loaded only when the user runs ``pm rc start``; the
server's runtime dependencies (``fastapi``/``uvicorn``) are an optional
extra (``pip install 'pm[rc]'``) so they don't bloat the base install.
"""
