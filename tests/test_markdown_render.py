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
