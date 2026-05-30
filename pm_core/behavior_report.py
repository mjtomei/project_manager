"""All-PR behavior dashboard (pr-8e693f6).

Per-PR ``report.html`` is **agent-written** as a deliverable of the sign-off
prompt (``generate_signoff_prompt``). This module owns the one deterministic
surface: the **all-PR dashboard** ``index.html`` at the captures root
(``~/.pm/sessions/<tag>/captures/index.html``), opened over ``file://``.

The dashboard is intentionally minimal. One row per PR with:

  * pm canonical id + GitHub PR # (if any)
  * title (from ``project.yaml``)
  * link to the per-PR ``report.html`` (or a "no report yet" cell)
  * the sign-off verdict, read at generation time from a single
    ``<meta name="pm-signoff-verdict" content="SIGNOFF_*">`` tag in
    ``report.html``'s ``<head>``

No JSON sidecar — the report itself is the canonical artifact and the only
piece of structured data the dashboard needs (the verdict keyword) is read
directly from it. PR runtime state (title) comes fresh from ``project.yaml``
at generation time so it can't go stale.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

_log = logging.getLogger("pm.behavior_report")


# ---------------------------------------------------------------------------
# Report reading
# ---------------------------------------------------------------------------

@dataclass
class _DashRow:
    pr_id: str               # pm canonical id (pr-XXXXXXX)
    gh_label: str            # "#42" or "" when no GitHub PR
    title: str
    has_report: bool
    report_html_rel: Optional[str]   # relative to the dashboard index.html
    verdict: str             # SIGNOFF_* keyword or "" when no report / no tag


_VERDICT_META_RE = re.compile(
    r'<meta\s+[^>]*name=["\']pm-signoff-verdict["\']\s+[^>]*'
    r'content=["\']([A-Z_]+)["\']',
    re.IGNORECASE,
)


def _extract_verdict(report_path: Path) -> str:
    """Read the sign-off verdict from a ``report.html``'s `<head>` meta tag.

    Returns the keyword (``SIGNOFF_MERGE`` etc.) or ``""`` when the file is
    missing, unreadable, or has no ``pm-signoff-verdict`` meta tag.
    """
    try:
        text = report_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
    # Only scan the <head> region — a verbatim verdict keyword in <body>
    # (e.g. inside the routing-definitions section a verbose report might
    # quote) would be a false match.
    head_end = text.lower().find("</head>")
    head = text if head_end < 0 else text[:head_end]
    m = _VERDICT_META_RE.search(head)
    return m.group(1).upper() if m else ""


def gather_dashboard_rows(data: dict,
                          captures_root_dir: Path) -> list[_DashRow]:
    """Build one row per PR from ``project.yaml`` + per-PR ``report.html``."""
    rows: list[_DashRow] = []
    for pr in data.get("prs") or []:
        pr_id = pr["id"]
        gh = pr.get("gh_pr_number")
        gh_label = f"#{gh}" if gh else ""
        title = pr.get("title", pr_id)
        report_path = captures_root_dir / pr_id / "report.html"
        if report_path.is_file():
            verdict = _extract_verdict(report_path)
            rows.append(_DashRow(
                pr_id=pr_id, gh_label=gh_label, title=title,
                has_report=True, report_html_rel=f"{pr_id}/report.html",
                verdict=verdict,
            ))
        else:
            rows.append(_DashRow(
                pr_id=pr_id, gh_label=gh_label, title=title,
                has_report=False, report_html_rel=None, verdict="",
            ))
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_RICH_COLOR_CSS = {
    "green":   "#1a7f37",
    "magenta": "#8250df",
    "cyan":    "#1b7c83",
    "yellow":  "#9a6700",
    "red":     "#cf222e",
}


def _e(text) -> str:
    return html.escape("" if text is None else str(text))


def _href(rel: str) -> str:
    return html.escape(quote(rel), quote=True)


def _rich_style_to_css(style: str) -> str:
    for word in (style or "").split():
        if word in _RICH_COLOR_CSS:
            return _RICH_COLOR_CSS[word]
    return "#6e7781"


def _verdict_marker_html(verdict: str) -> str:
    if not verdict:
        return '<span class="muted">verdict unknown</span>'
    from pm_core.signoff import (
        SIGNOFF_VERDICT_ICONS, SIGNOFF_VERDICT_STYLES,
    )
    icon = SIGNOFF_VERDICT_ICONS.get(verdict, "")
    color = _rich_style_to_css(SIGNOFF_VERDICT_STYLES.get(verdict, ""))
    return (f'<span class="signoff-marker" style="color:{color}">'
            f'{_e(icon)} {_e(verdict)}</span>')


_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
  Helvetica, Arial, sans-serif; margin: 0 auto; padding: 0 1.25rem 4rem;
  max-width: 1000px; line-height: 1.5; color: #1b1f23; background: #fff; }
@media (prefers-color-scheme: dark) {
  body { color: #d8dde3; background: #0d1117; }
  a { color: #58a6ff; }
  th { background: #161b22; }
}
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 1.6rem; margin: 1.2rem 0 .4rem; }
.muted { color: #6a737d; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1rem; }
th, td { text-align: left; padding: .5rem .6rem; vertical-align: top;
  border-bottom: 1px solid rgba(127,127,127,.25); }
th { background: #f6f8fa; font-size: .85rem; }
.signoff-marker { font-weight: 600; white-space: nowrap; }
.missing { color: #9a6700; font-weight: 600; }
.regen code { background: rgba(127,127,127,.18); padding: .1rem .4rem;
  border-radius: 4px; font-size: .85rem; }
button.copy { font-size: .78rem; padding: .15rem .5rem; cursor: pointer;
  border: 1px solid rgba(127,127,127,.5); border-radius: 5px;
  background: transparent; color: inherit; }
.pr-id { white-space: nowrap; font-family: ui-monospace, SFMono-Regular,
  Menlo, monospace; font-size: .85rem; }
.gh-id { color: #6a737d; margin-left: .35rem; }
"""

_DASH_JS = """
function pmCopy(cmd, btn) {
  if (navigator.clipboard) navigator.clipboard.writeText(cmd);
  var old = btn.textContent; btn.textContent = 'copied';
  setTimeout(function(){ btn.textContent = old; }, 1200);
}
"""


def _regenerate_cell(pr_id: str) -> str:
    cmd = f"pm pr signoff {pr_id}"
    return (
        f'<span class="missing">no report yet</span> &middot; '
        f'<span class="regen"><code>{_e(cmd)}</code> '
        f'<button class="copy" type="button" '
        f'onclick="pmCopy(\'{_e(cmd)}\', this)">copy</button></span>')


def render_dashboard_html(data: dict, rows: list[_DashRow]) -> str:
    parts: list[str] = []
    parts.append('<!DOCTYPE html><html lang="en"><head>')
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, '
                 'initial-scale=1">')
    parts.append('<title>Behavior dashboard — all PRs</title>')
    parts.append(f'<style>{_CSS}</style></head><body>')
    parts.append('<h1>Behavior dashboard</h1>')
    parts.append('<p class="muted">One sign-off report per PR. Click a PR '
                 'to open its report.</p>')

    parts.append('<table>')
    parts.append('<thead><tr><th>PR</th><th>Title</th>'
                 '<th>Verdict</th><th>Report</th></tr></thead><tbody>')
    for r in rows:
        pr_cell = f'<span class="pr-id">{_e(r.pr_id)}</span>'
        if r.gh_label:
            pr_cell += f'<span class="gh-id">{_e(r.gh_label)}</span>'

        if r.has_report and r.report_html_rel:
            report_cell = f'<a href="{_href(r.report_html_rel)}">open report</a>'
            verdict_cell = _verdict_marker_html(r.verdict)
        else:
            report_cell = _regenerate_cell(r.pr_id)
            verdict_cell = '<span class="muted">—</span>'

        parts.append(
            '<tr>'
            f'<td>{pr_cell}</td>'
            f'<td>{_e(r.title)}</td>'
            f'<td>{verdict_cell}</td>'
            f'<td>{report_cell}</td></tr>')
    parts.append('</tbody></table>')

    parts.append(f'<script>{_DASH_JS}</script>')
    parts.append('</body></html>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public generation API
# ---------------------------------------------------------------------------

def generate_dashboard(root: Path, *, session_tag: str | None = None,
                       data: dict | None = None) -> Optional[Path]:
    """(Re)generate the all-PR behavior dashboard ``index.html``.

    Returns the written path, or ``None`` when the captures root can't be
    resolved (no session tag — e.g. not inside a git repo). For each PR the
    dashboard checks ``$CAP/<pr_id>/report.html``: if present, it links to
    the report and parses the routing verdict out of a ``pm-signoff-verdict``
    meta tag in ``<head>``; if absent, the row shows a "no report yet" cell
    with ``pm pr signoff <pr_id>`` as the regenerate command.
    """
    from pm_core import store
    from pm_core.paths import captures_root

    if data is None:
        data = store.load(root)
    croot = captures_root(session_tag=session_tag)
    if croot is None:
        _log.warning("Cannot resolve captures root (no session tag)")
        return None
    croot.mkdir(parents=True, exist_ok=True)
    rows = gather_dashboard_rows(data, croot)
    out_path = croot / "index.html"
    out_path.write_text(render_dashboard_html(data, rows), encoding="utf-8")
    return out_path
