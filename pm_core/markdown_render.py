"""Render a ``.md`` evidence file to a sibling ``.html`` for the sign-off
report.

The sign-off agent (see ``prompt_gen.generate_signoff_prompt``) embeds
evidence inline whenever the browser supports it. Markdown displays as raw
plaintext over ``file://`` in most browsers, so we pre-render each linked
``.md`` to a sibling ``.html`` at sign-off time and link to the rendered
file instead. The original ``.md`` stays on disk for grep / diff / archival.

CommonMark + tables + fenced code is enough for the evidence shapes we see
(QA scenario notes, review summaries) — keep the renderer dependency-light.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Optional


# Minimal style shell shared with the per-PR report.html look.
_MD_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
  Helvetica, Arial, sans-serif; margin: 0 auto; padding: 1.5rem 1.25rem 4rem;
  max-width: 900px; line-height: 1.55; color: #1b1f23; background: #fff; }
@media (prefers-color-scheme: dark) {
  body { color: #d8dde3; background: #0d1117; }
  a { color: #58a6ff; }
  pre, code { background: #161b22; }
  th { background: #161b22; }
  blockquote { border-left-color: #30363d; color: #8b949e; }
}
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
h1, h2, h3, h4 { line-height: 1.25; margin-top: 1.5em; }
h1 { font-size: 1.6rem; border-bottom: 1px solid rgba(127,127,127,.3);
  padding-bottom: .3rem; }
h2 { font-size: 1.25rem; border-bottom: 1px solid rgba(127,127,127,.2);
  padding-bottom: .2rem; }
pre { background: rgba(127,127,127,.12); padding: .75rem 1rem;
  border-radius: 6px; overflow-x: auto; font-size: .9rem; }
code { background: rgba(127,127,127,.12); padding: .1rem .35rem;
  border-radius: 4px; font-size: .92em; }
pre code { background: transparent; padding: 0; }
table { border-collapse: collapse; margin: .5rem 0 1rem; }
th, td { text-align: left; padding: .4rem .7rem;
  border: 1px solid rgba(127,127,127,.3); }
th { background: #f6f8fa; }
blockquote { margin: .5rem 0; padding: .2rem 1rem;
  border-left: 4px solid rgba(127,127,127,.4); color: #57606a; }
img { max-width: 100%; }
"""


def _shell(title: str, body_html: str) -> str:
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{html.escape(title)}</title>'
        f'<style>{_MD_CSS}</style>'
        '</head><body>'
        f'{body_html}'
        '</body></html>'
    )


def render_markdown_to_html(md_text: str, *, title: str = "") -> str:
    """Render markdown text to a complete, styled HTML document.

    CommonMark with the ``tables`` and ``fenced_code`` extensions enabled —
    enough for the evidence shapes the sign-off agent links to.
    """
    import markdown

    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code"],
        output_format="html5",
    )
    return _shell(title or "evidence", body)


def render_md_file(md_path: Path, *, out_path: Optional[Path] = None) -> Path:
    """Render ``md_path`` to a sibling ``.html`` and return the output path.

    The default output path is ``<md_path>.html`` (e.g. ``notes.md`` →
    ``notes.md.html``) so the original markdown stays discoverable next to
    its rendered companion. Pass ``out_path`` to override.

    Idempotent: re-running overwrites the output file.
    """
    md_path = Path(md_path)
    if out_path is None:
        out_path = md_path.with_suffix(md_path.suffix + ".html")
    text = md_path.read_text(encoding="utf-8")
    html_doc = render_markdown_to_html(text, title=md_path.name)
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path
