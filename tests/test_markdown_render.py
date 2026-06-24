"""Tests for ``pm_core.markdown_render.render_markdown_body`` — the body-only
HTML fragment the sign-off agent embeds inline in ``report.html``.
"""

from __future__ import annotations

from click.testing import CliRunner

from pm_core import markdown_render
from pm_core.cli import cli


# ---------------------------------------------------------------------------
# render_markdown_body
# ---------------------------------------------------------------------------

def test_commonmark_basics_preserved():
    src = "# Heading\n\nA paragraph with **bold** and *italic*.\n\n- one\n- two\n"
    out = markdown_render.render_markdown_body(src)
    assert "<h1>Heading</h1>" in out
    assert "<strong>bold</strong>" in out
    assert "<em>italic</em>" in out
    assert "<ul>" in out
    assert "<li>one</li>" in out


def test_tables_extension_renders_table():
    src = (
        "| A | B |\n"
        "|---|---|\n"
        "| 1 | 2 |\n"
        "| 3 | 4 |\n"
    )
    out = markdown_render.render_markdown_body(src)
    assert "<table>" in out and "</table>" in out
    assert "<th>A</th>" in out
    assert "<td>1</td>" in out and "<td>4</td>" in out


def test_fenced_code_extension_preserves_block():
    src = "```python\ndef f(x):\n    return x + 1\n```\n"
    out = markdown_render.render_markdown_body(src)
    assert "<pre>" in out and "</pre>" in out
    assert "<code" in out
    assert "    return x + 1" in out


def test_raw_html_in_source_is_escaped_not_passed_through():
    # Evidence ``.md`` is untrusted data; a raw ``<script>`` written as inline
    # prose must be escaped (shown as literal text), never embedded as live
    # markup that would execute once the fragment lands in ``report.html``.
    src = "A line with <script>alert(1)</script> in prose.\n"
    out = markdown_render.render_markdown_body(src)
    assert "<script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_raw_html_escaped_while_extension_markup_preserved():
    # Escaping raw source HTML must not double-escape extension-generated
    # markup: the fenced block keeps its real <pre><code> tags while the
    # ``<script>`` inside it stays escaped content.
    src = "```html\n<script>alert(1)</script>\n```\n"
    out = markdown_render.render_markdown_body(src)
    assert '<pre><code class="language-html">' in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_markdown_link_with_javascript_scheme_is_neutralized():
    # python-markdown does not sanitize URI schemes, so a markdown-native link
    # (distinct from raw <a> HTML, which is escaped) with a ``javascript:``
    # target would otherwise emit a live, clickable XSS vector once the
    # fragment is embedded in ``report.html``.
    src = "[click me](javascript:alert(1))\n"
    out = markdown_render.render_markdown_body(src)
    assert "javascript:" not in out
    assert 'href="#"' in out
    assert ">click me</a>" in out


def test_markdown_image_with_dangerous_scheme_drops_src():
    src = "![x](javascript:alert(1))\n"
    out = markdown_render.render_markdown_body(src)
    assert "javascript:" not in out
    assert "src=" not in out  # the dangerous src is dropped entirely


def test_dangerous_schemes_with_whitespace_obfuscation_neutralized():
    # Browsers ignore embedded control chars / case when parsing the scheme,
    # so the sanitizer must too.
    for src in (
        "[a](JavaScript:alert(1))\n",
        "[b](java\tscript:alert(1))\n",
        "[c](vbscript:msgbox(1))\n",
        "[d](data:text/html,<script>alert(1)</script>)\n",
    ):
        out = markdown_render.render_markdown_body(src)
        assert "alert" not in out or 'href="#"' in out
        assert "javascript:" not in out.lower()
        assert "vbscript:" not in out.lower()
        assert "data:text/html" not in out.lower()


def test_safe_links_and_relative_paths_preserved():
    # The sanitizer must not break legitimate evidence links: relative paths,
    # fragments, and allowlisted schemes pass through unchanged.
    cases = {
        "[ok](https://example.com)\n": 'href="https://example.com"',
        "[rel](../scenarios/3/notes.md)\n": 'href="../scenarios/3/notes.md"',
        "[frag](#section)\n": 'href="#section"',
        "[mail](mailto:x@y.com)\n": 'href="mailto:x@y.com"',
        "![shot](images/shot.png)\n": 'src="images/shot.png"',
    }
    for src, expected in cases.items():
        assert expected in markdown_render.render_markdown_body(src)


def test_output_is_body_only_no_shell():
    # The fragment is embedded inside another HTML document (report.html),
    # so it must NOT carry a top-level doctype/html/head/body/style wrapper.
    out = markdown_render.render_markdown_body("# Hi\n\ntext\n")
    assert "<!DOCTYPE" not in out
    assert "<html" not in out
    assert "<head" not in out
    assert "<body" not in out
    assert "<style" not in out
    assert "<h1>Hi</h1>" in out


# ---------------------------------------------------------------------------
# `pm md-render` CLI
# ---------------------------------------------------------------------------

def test_cli_md_render_emits_body_only_html(tmp_path):
    md = tmp_path / "notes.md"
    md.write_text("# Hi\n\ntext with **bold**\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["md-render", str(md)])
    assert result.exit_code == 0, result.output
    assert "<h1>Hi</h1>" in result.output
    assert "<strong>bold</strong>" in result.output
    assert "<!DOCTYPE" not in result.output


def test_cli_md_render_missing_file_errors(tmp_path):
    result = CliRunner().invoke(cli, ["md-render", str(tmp_path / "nope.md")])
    assert result.exit_code != 0
