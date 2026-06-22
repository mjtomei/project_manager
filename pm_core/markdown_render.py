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

    Evidence ``.md`` files are untrusted data (QA scenario notes, captured
    logs), so raw HTML the source happens to contain is escaped rather than
    passed through: an evidence file with a literal ``<script>`` tag must show
    that tag as visible text, never execute it once the fragment is embedded
    in ``report.html``. We do this surgically — deregistering python-markdown's
    raw-HTML preprocessor (``html_block``) and inline pattern (``html``) so the
    serializer escapes any ``<``/``>`` it would otherwise have stashed verbatim
    — which leaves the extension-generated markup (tables, fenced code) intact.
    """
    import markdown

    md = markdown.Markdown(
        extensions=["tables", "fenced_code"],
        output_format="html5",
    )
    # Treat raw HTML in the source as literal text (escaped), not markup.
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    return md.convert(md_text)
