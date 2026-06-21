"""All-PR behavior dashboard (pr-8e693f6).

Per-PR ``report.html`` is **agent-written** as a deliverable of the sign-off
prompt (``generate_signoff_prompt``). This module builds the all-PR index
HTML in-memory; ``pm_core.dashboard_server`` serves it over a localhost
HTTP server (`pm pr dashboard`), rebuilding on every ``/`` request so
liveness is dynamic.

The dashboard is intentionally minimal. One row per PR with:

  * pm canonical id + GitHub PR # (if any)
  * title (from ``project.yaml``)
  * link to the per-PR ``report.html`` (or a "no report yet" cell)
  * the sign-off verdict, read at request time from a single
    ``<meta name="pm-signoff-verdict" content="SIGNOFF_*">`` tag in
    ``report.html``'s ``<head>``

No JSON sidecar — the report itself is the canonical artifact and the only
piece of structured data the dashboard needs (the verdict keyword) is read
directly from it. PR runtime state (title) comes fresh from ``project.yaml``
at request time so it can't go stale.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from pathlib import Path
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
    report_html_rel: str | None      # path served by the dashboard server
    verdict: str             # SIGNOFF_* keyword or "" when no report / no tag
    mtime: float | None      # report.html mtime (unix ts); None when no report


# Match a single ``<meta ...>`` tag, then pull ``name`` and ``content`` out of
# it independently — the agent writes this HTML, so we don't assume a fixed
# attribute order (``content`` may precede ``name``).
_META_TAG_RE = re.compile(r'<meta\b[^>]*>', re.IGNORECASE)
_META_NAME_RE = re.compile(
    r'name\s*=\s*["\']pm-signoff-verdict["\']', re.IGNORECASE)
_META_CONTENT_RE = re.compile(
    r'content\s*=\s*["\']([A-Z_]+)["\']', re.IGNORECASE)


# Read only enough of the file to cover any plausible <head>. Reports embed
# the full diff inline, so they can run to many MB — but the verdict meta tag
# lives in <head>, near the top. Cap the read so the dashboard doesn't slurp a
# multi-MB body per PR on every request just to read one tag.
_HEAD_READ_CAP = 256 * 1024


def _extract_verdict(report_path: Path) -> str:
    """Read the sign-off verdict from a ``report.html``'s `<head>` meta tag.

    Returns the keyword (``SIGNOFF_MERGE`` etc.) or ``""`` when the file is
    missing, unreadable, or has no ``pm-signoff-verdict`` meta tag.
    """
    try:
        with report_path.open("r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(_HEAD_READ_CAP)
    except (OSError, ValueError):
        return ""
    # Only scan the <head> region — a verbatim verdict keyword in <body>
    # (e.g. inside the routing-definitions section a verbose report might
    # quote) would be a false match.
    head_end = text.lower().find("</head>")
    head = text if head_end < 0 else text[:head_end]
    for tag in _META_TAG_RE.findall(head):
        if _META_NAME_RE.search(tag):
            m = _META_CONTENT_RE.search(tag)
            return m.group(1).upper() if m else ""
    return ""


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
            try:
                mtime = report_path.stat().st_mtime
            except OSError:
                mtime = None
            rows.append(_DashRow(
                pr_id=pr_id, gh_label=gh_label, title=title,
                has_report=True, report_html_rel=f"{pr_id}/report.html",
                verdict=verdict, mtime=mtime,
            ))
        else:
            rows.append(_DashRow(
                pr_id=pr_id, gh_label=gh_label, title=title,
                has_report=False, report_html_rel=None, verdict="",
                mtime=None,
            ))
    # Default sort: most-recently-modified report first, then by pr_id for
    # stable ordering of the empty-state rows.
    rows.sort(key=lambda r: (-(r.mtime or 0), r.pr_id))
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


def _format_mtime(mtime: float | None) -> tuple[str, str]:
    """Return (display, tooltip) for a unix mtime.

    Display is a short relative string ("3m ago", "2h ago", "5d ago");
    tooltip is the absolute UTC timestamp. Both are empty when *mtime*
    is None (e.g. no report on disk).
    """
    if mtime is None:
        return ("—", "")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).timestamp()
    delta = max(0.0, now - mtime)
    abs_iso = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC")
    if delta < 60:
        rel = f"{int(delta)}s ago"
    elif delta < 3600:
        rel = f"{int(delta // 60)}m ago"
    elif delta < 86400:
        rel = f"{int(delta // 3600)}h ago"
    else:
        rel = f"{int(delta // 86400)}d ago"
    return (rel, abs_iso)


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
.pr-id { white-space: nowrap; font-family: ui-monospace, SFMono-Regular,
  Menlo, monospace; font-size: .85rem; }
.gh-id { color: #6a737d; margin-left: .35rem; }
.mtime { color: #57606a; white-space: nowrap; font-variant-numeric: tabular-nums; }
.controls { margin: .8rem 0 .4rem; display: flex; gap: .6rem; align-items: center; }
.controls input { padding: .35rem .55rem; border-radius: 5px;
  border: 1px solid rgba(127,127,127,.4); background: transparent;
  color: inherit; font-size: .9rem; min-width: 18rem; }
th[data-col] { cursor: pointer; user-select: none; }
th[data-col]:hover { background: rgba(127,127,127,.12); }
th.sort-asc::after { content: " ▲"; font-size: .75em; color: #6a737d; }
th.sort-desc::after { content: " ▼"; font-size: .75em; color: #6a737d; }
"""

_DASH_JS = """
function pmFilter() {
  var q = (document.getElementById('q').value || '').toLowerCase();
  document.querySelectorAll('tbody tr').forEach(function(r) {
    r.style.display = !q || r.textContent.toLowerCase().indexOf(q) >= 0 ? '' : 'none';
  });
}
function pmSort(col) {
  var tbody = document.querySelector('tbody');
  var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
  var cur = tbody.dataset.sort || '';
  var asc = cur !== col + '-asc';
  function keyFor(r) {
    var c = r.children[col];
    var v = c.dataset.sort;
    if (v === undefined || v === null || v === '') v = c.textContent.trim();
    var n = parseFloat(v);
    return isNaN(n) ? v.toLowerCase() : n;
  }
  rows.sort(function(a, b) {
    var ka = keyFor(a), kb = keyFor(b);
    if (ka === kb) return 0;
    return (asc ? 1 : -1) * (ka > kb ? 1 : -1);
  });
  rows.forEach(function(r) { tbody.appendChild(r); });
  tbody.dataset.sort = col + (asc ? '-asc' : '-desc');
  document.querySelectorAll('th[data-col]').forEach(function(th) {
    th.classList.remove('sort-asc', 'sort-desc');
    if (parseInt(th.dataset.col) === col) {
      th.classList.add(asc ? 'sort-asc' : 'sort-desc');
    }
  });
}
"""


def _regenerate_cell(pr_id: str) -> str:
    return '<span class="missing">no report yet</span>'


def render_dashboard_html(rows: list[_DashRow]) -> str:
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
    parts.append(
        '<div class="controls">'
        '<input id="q" type="search" placeholder="Filter (PR id, title, verdict, …)" '
        'oninput="pmFilter()" autocomplete="off">'
        '</div>')

    parts.append('<table>')
    parts.append(
        '<thead><tr>'
        '<th data-col="0" onclick="pmSort(0)">PR</th>'
        '<th data-col="1" onclick="pmSort(1)">Title</th>'
        '<th data-col="2" class="sort-desc" onclick="pmSort(2)">Last modified</th>'
        '<th data-col="3" onclick="pmSort(3)">Verdict</th>'
        '<th data-col="4" onclick="pmSort(4)">Report</th>'
        '</tr></thead><tbody data-sort="2-desc">')
    for r in rows:
        pr_cell = f'<span class="pr-id">{_e(r.pr_id)}</span>'
        if r.gh_label:
            pr_cell += f'<span class="gh-id">{_e(r.gh_label)}</span>'

        rel, abs_ts = _format_mtime(r.mtime)
        mtime_sort = f'{r.mtime:.0f}' if r.mtime is not None else "0"
        mtime_cell = (f'<span class="mtime" title="{_e(abs_ts)}">{_e(rel)}</span>'
                      if r.mtime is not None
                      else '<span class="muted">—</span>')

        if r.has_report and r.report_html_rel:
            report_cell = f'<a href="{_href(r.report_html_rel)}">open report</a>'
            verdict_cell = _verdict_marker_html(r.verdict)
        else:
            report_cell = _regenerate_cell(r.pr_id)
            verdict_cell = '<span class="muted">—</span>'
        verdict_sort = r.verdict or "~"  # empty verdicts sort last in ASC

        parts.append(
            '<tr>'
            f'<td>{pr_cell}</td>'
            f'<td>{_e(r.title)}</td>'
            f'<td data-sort="{mtime_sort}">{mtime_cell}</td>'
            f'<td data-sort="{_e(verdict_sort)}">{verdict_cell}</td>'
            f'<td>{report_cell}</td></tr>')
    parts.append('</tbody></table>')

    parts.append(f'<script>{_DASH_JS}</script>')
    parts.append('</body></html>')
    return "".join(parts)


