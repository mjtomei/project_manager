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

import re

# URI schemes safe to keep in ``href`` / ``src`` attributes. Everything with
# any other scheme (notably ``javascript:`` / ``vbscript:`` / ``data:``) is
# neutralised — see ``_is_safe_uri``. A relative URL / fragment / scheme-less
# path carries no scheme and is always allowed.
_SAFE_URI_SCHEMES = frozenset({
    "http", "https", "mailto", "ftp", "ftps", "tel", "file",
})

# A leading URI scheme: letters/digits/+/-/. up to the first ``:`` — but only
# when that ``:`` precedes any ``/`` ``?`` ``#`` (so ``path/to:thing`` and
# ``#frag`` parse as scheme-less, matching how browsers resolve the scheme).
_SCHEME_RE = re.compile(r'^([a-zA-Z][a-zA-Z0-9+.\-]*):')


def _is_safe_uri(uri: str) -> bool:
    """Return True when *uri* has no scheme or a scheme on the allowlist.

    Browsers ignore embedded ASCII whitespace / control characters when
    parsing a scheme (``java\\tscript:...`` still executes), so those are
    stripped before the scheme is read.
    """
    if not uri:
        return True
    stripped = re.sub(r'[\x00-\x20]+', '', uri)
    m = _SCHEME_RE.match(stripped)
    if not m:
        return True  # relative URL, fragment, or scheme-less path
    return m.group(1).lower() in _SAFE_URI_SCHEMES


def _sanitize_link_attrs(md) -> None:
    """Register a treeprocessor that neutralises dangerous ``href`` / ``src``.

    Raw HTML in the source is already escaped (the ``html``/``html_block``
    deregistration below), but markdown-native link/image syntax —
    ``[x](javascript:alert(1))`` / ``![](javascript:...)`` — still produces a
    live ``javascript:`` URI that python-markdown does not sanitise. Evidence
    ``.md`` is untrusted, so blank an unsafe ``a@href`` to ``#`` and drop an
    unsafe ``img@src`` entirely before the fragment is embedded in
    ``report.html``.
    """
    from markdown.treeprocessors import Treeprocessor

    class _SanitizeLinks(Treeprocessor):
        def run(self, root):
            for el in root.iter():
                if el.tag == "a" and "href" in el.attrib:
                    if not _is_safe_uri(el.attrib["href"]):
                        el.set("href", "#")
                elif el.tag == "img" and "src" in el.attrib:
                    if not _is_safe_uri(el.attrib["src"]):
                        el.attrib.pop("src", None)
            return root

    # Priority 0 runs after the built-in ``inline`` treeprocessor (priority 20)
    # has materialised links/images into the tree.
    md.treeprocessors.register(_SanitizeLinks(md), "pm_sanitize_links", 0)


def render_markdown_body(md_text: str) -> str:
    """Render markdown text to a body-only HTML fragment (no document shell).

    Returns the HTML emitted by ``python-markdown`` with the ``tables`` and
    ``fenced_code`` extensions enabled. The fragment is meant to be embedded
    inside another document (e.g. ``report.html``), so it carries no
    ``<html>``/``<head>``/``<style>`` wrapper — styling is inherited from
    the embedding page.

    Evidence ``.md`` files are untrusted data (QA scenario notes, captured
    logs), so anything that could execute once the fragment is embedded in
    ``report.html`` is neutralised:

    * Raw HTML the source happens to contain is escaped rather than passed
      through — a literal ``<script>`` tag shows as visible text, never runs.
      We do this surgically, deregistering python-markdown's raw-HTML
      preprocessor (``html_block``) and inline pattern (``html``) so the
      serializer escapes any ``<``/``>`` it would otherwise have stashed
      verbatim, leaving extension-generated markup (tables, fenced code)
      intact.
    * Markdown-native links/images with a dangerous URI scheme
      (``[x](javascript:...)`` / ``![](javascript:...)``) are sanitised by a
      treeprocessor (:func:`_sanitize_link_attrs`) — python-markdown does not
      filter URI schemes on its own.
    """
    import markdown

    md = markdown.Markdown(
        extensions=["tables", "fenced_code"],
        output_format="html5",
    )
    # Treat raw HTML in the source as literal text (escaped), not markup.
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    _sanitize_link_attrs(md)
    return md.convert(md_text)
