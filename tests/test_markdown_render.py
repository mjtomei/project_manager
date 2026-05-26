"""Tests for ``pm_core.markdown_render`` — the sign-off helper that pre-renders
linked ``.md`` evidence to a sibling ``.html`` (note-d01545e / note-8cfdf73).
"""

from __future__ import annotations

from pathlib import Path

from pm_core import markdown_render


# ---------------------------------------------------------------------------
# render_markdown_to_html
# ---------------------------------------------------------------------------

def test_commonmark_basics_preserved():
    src = "# Heading\n\nA paragraph with **bold** and *italic*.\n\n- one\n- two\n"
    out = markdown_render.render_markdown_to_html(src)
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
    out = markdown_render.render_markdown_to_html(src)
    assert "<table>" in out and "</table>" in out
    assert "<th>A</th>" in out
    assert "<td>1</td>" in out and "<td>4</td>" in out


def test_fenced_code_extension_preserves_block():
    src = "```python\ndef f(x):\n    return x + 1\n```\n"
    out = markdown_render.render_markdown_to_html(src)
    assert "<pre>" in out and "</pre>" in out
    assert "<code" in out
    # Indentation inside the fenced block should be preserved verbatim.
    assert "    return x + 1" in out


def test_output_is_a_well_formed_html_document():
    out = markdown_render.render_markdown_to_html("just text\n", title="hello")
    assert out.startswith("<!DOCTYPE html>")
    assert "<html" in out and "</html>" in out
    assert "<head>" in out and "</head>" in out
    assert "<body>" in out and "</body>" in out
    assert "<title>hello</title>" in out
    # Style shell is inlined so the page stays self-contained over file://.
    assert "<style>" in out and "</style>" in out


def test_title_is_html_escaped():
    out = markdown_render.render_markdown_to_html(
        "x", title="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


# ---------------------------------------------------------------------------
# render_md_file
# ---------------------------------------------------------------------------

def test_render_md_file_writes_sibling_html(tmp_path: Path):
    md = tmp_path / "notes.md"
    md.write_text("# Hi\n\ntext\n")
    out = markdown_render.render_md_file(md)
    assert out == tmp_path / "notes.md.html"
    assert out.exists()
    # Source .md is kept so it stays grep-/diff-able alongside the rendered HTML.
    assert md.exists()
    text = out.read_text()
    assert "<h1>Hi</h1>" in text
    assert text.startswith("<!DOCTYPE html>")


def test_render_md_file_is_idempotent(tmp_path: Path):
    md = tmp_path / "x.md"
    md.write_text("# A\n")
    a = markdown_render.render_md_file(md).read_text()
    md.write_text("# A\n")
    b = markdown_render.render_md_file(md).read_text()
    assert a == b


def test_render_md_file_honors_out_path(tmp_path: Path):
    md = tmp_path / "x.md"
    md.write_text("# A\n")
    out = tmp_path / "rendered" / "x.html"
    out.parent.mkdir()
    result = markdown_render.render_md_file(md, out_path=out)
    assert result == out
    assert "<h1>A</h1>" in out.read_text()
