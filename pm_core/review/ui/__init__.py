"""Walker web UI for the augmented adversarial-review cycle.

A FastAPI single-file server (`server.py`) plus Jinja2 templates and a
vanilla-JS/CSS frontend. Renders the per-review dashboard and the
proposed-changes walker, enforces the lock state, watches each review's
markdown surfaces via ``watchdog``, and pushes filesystem changes to
clients over a single ``/events`` SSE endpoint.
"""
