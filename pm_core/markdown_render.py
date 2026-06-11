"""Render markdown evidence for the sign-off report.

The sign-off agent embeds evidence inline in ``report.html``. For ``.md``
evidence it shells out to ``pm md-render <path>`` to get a body-only HTML
fragment (no ``<html>``/``<head>``/``<style>`` shell) and drops it inside
a collapsed ``<details>`` block. Rendering happens at report-write time
so the embedded view never diverges from the source ``.md``.

CommonMark + tables + fenced code is enough for the evidence shapes we see
(QA scenario notes, review summaries) — keep the renderer dependency-light.
"""

from __future__ import annotations


def render_markdown_body(md_text: str) -> str:
    """Render markdown text to a body-only HTML fragment (no document shell).

    Returns the HTML emitted by ``python-markdown`` with the ``tables`` and
    ``fenced_code`` extensions enabled. The fragment is meant to be embedded
    inside another document (e.g. ``report.html``), so it carries no
    ``<html>``/``<head>``/``<style>`` wrapper — styling is inherited from
    the embedding page.
    """
    import markdown

    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code"],
        output_format="html5",
    )
