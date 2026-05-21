"""CLI for the adversarial-review walker.

Provides ``pm review ui [--port]`` to launch the walker web server. PR 1 will
extend this ``review`` group with ``pm review <target>`` (session launching);
this PR ships only the ``ui`` subcommand.
"""

from __future__ import annotations

import click

from pm_core.cli.helpers import state_root


@click.group("review")
def review():
    """Adversarial-review walker commands."""


@review.command("ui")
@click.option("--port", default=8765, show_default=True, help="Port to serve on.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind (local-only).")
def ui(port: int, host: str):
    """Launch the walker web server (dashboard + proposed-changes walker)."""
    import uvicorn

    from pm_core.review.ui.server import build_app

    pm_root = state_root()
    app = build_app(pm_root)
    click.echo(f"Walker UI for {pm_root} → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
