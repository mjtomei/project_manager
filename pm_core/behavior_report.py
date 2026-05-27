"""All-PR behavior dashboard (pr-8e693f6).

Per-PR ``report.html`` is **agent-written** as a deliverable of the sign-off
prompt extension (pr-2d5f712's ``generate_signoff_prompt`` — see the "Write
the sign-off report (deliverable)" section there). Captures are heterogeneous
enough that the same semantic pass that produces the routing verdict is the
only sensible producer of the per-behavior framing. This module owns the one
deterministic surface: the **all-PR dashboard**.

The dashboard is a static ``index.html`` at the captures root
(``~/.pm/sessions/<tag>/captures/index.html``) that opens over ``file://``.
Per PR it reads one **sidecar** file the agent wrote alongside its report:

    ~/.pm/sessions/<tag>/captures/<pr_id>/report.json

This sidecar is the dashboard's *only* contract for sign-off-derived content
— the dashboard never interprets captures. PR runtime state (status, merged,
title, display_id) is read fresh from ``project.yaml`` at
dashboard-generation time, **not** from the sidecar; the sidecar carries only
fields the sign-off agent produced. Schema (frozen):

    {
      "pr_id":              str,                          # pm canonical id
      "verdict":            "SIGNOFF_MERGE" | ... | null,
      "next_hop":           "ready_to_merge"|"qa"|"review"|"impl"|"blocked",
      "tally":              {"PASS": int, "NEEDS_WORK": int,
                             "INPUT_REQUIRED": int, "pending": int},
      "bugs_fixed_in_loop": int,
      "spec_clarifications":int,
      "generated_at":       str,                          # ISO 8601 UTC
      "report_html":        str,                          # relative to sidecar
    }

When a sidecar is missing the row shows an explicit empty state with a
**regenerate** command — plain ``pm pr signoff <pr_id>``. Manual sign-off is
recommendation-only (the manual-never-acts invariant established in #225),
so re-running is safe; no separate "write-only" mode is needed.

Icons / colours / status labels come from #225's single sources so the
dashboard matches the TUI tech tree and ``pm pr list`` exactly:
``signoff.SIGNOFF_VERDICT_ICONS`` + ``SIGNOFF_VERDICT_STYLES`` and
``helpers.PR_STATUS_ICONS``. Plan grouping + plan-notes pass-through are
read straight from ``project.yaml``.
"""

from __future__ import annotations

import html
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote

_log = logging.getLogger("pm.behavior_report")

# Map Rich style strings (``signoff.SIGNOFF_VERDICT_STYLES``, e.g. "bold green")
# to CSS colours so the HTML verdict markers match the TUI colours.
_RICH_COLOR_CSS = {
    "green":   "#1a7f37",
    "magenta": "#8250df",
    "cyan":    "#1b7c83",
    "yellow":  "#9a6700",
    "red":     "#cf222e",
}

# QA verdict tally labels (kept in lifecycle order for stable rendering).
_TALLY_KEYS = ("PASS", "NEEDS_WORK", "INPUT_REQUIRED", "pending")


# ---------------------------------------------------------------------------
# Sidecar reading
# ---------------------------------------------------------------------------

@dataclass
class _DashRow:
    pr_id: str
    display_id: str
    title: str
    status: str
    merged: bool
    has_sidecar: bool
    sidecar_path: Optional[Path]
    report_html_rel: Optional[str]   # relative to the dashboard
    verdict: str                     # SIGNOFF_* or ""
    next_hop: str
    tally: dict
    bugs_fixed_in_loop: int
    spec_clarifications: int


def _load_sidecar(path: Path) -> Optional[dict]:
    """Read and lightly validate a ``report.json`` sidecar.

    Tolerates extra keys; misses for required keys land as falsy defaults so a
    partially-written sidecar still renders informatively (rather than crashing
    the whole dashboard).
    """
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _log.warning("Unreadable sidecar at %s: %s", path, exc)
        return None
    return data if isinstance(data, dict) else None


def _normalize_notes(raw) -> list[str]:
    """Coerce a plan ``notes`` field into a list of text strings (forward-
    compatible with pr-ff9b728's plan-notes shape — list of dicts, list of
    strings, or a single string)."""
    if not raw:
        return []
    if isinstance(raw, str):
        return [raw]
    out: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            text = item.get("text")
            if text:
                out.append(str(text))
        elif item:
            out.append(str(item))
    return out


def gather_dashboard_rows(data: dict,
                          captures_root_dir: Path) -> list[_DashRow]:
    """Build one row per PR in project.yaml from its sidecar (or empty state).

    The dashboard is the source of truth for *which* PRs exist (so an
    unmerged PR with no sign-off pass yet still shows up); the sidecar is the
    source of truth for what's *in* a row when it exists.
    """
    rows: list[_DashRow] = []
    for pr in data.get("prs") or []:
        pr_id = pr["id"]
        gh = pr.get("gh_pr_number")
        default_display = f"#{gh}" if gh else pr_id
        sidecar = captures_root_dir / pr_id / "report.json"
        loaded = _load_sidecar(sidecar)
        # PR runtime state always comes from project.yaml — the sidecar
        # carries only sign-off-derived content (verdict, tally, loop counts,
        # ...) so it never goes stale relative to status / merged / title.
        display_id = default_display
        title = pr.get("title", pr_id)
        status = pr.get("status", "unknown")
        merged = bool(pr.get("merged_at"))
        if loaded is None:
            rows.append(_DashRow(
                pr_id=pr_id,
                display_id=display_id,
                title=title,
                status=status,
                merged=merged,
                has_sidecar=False,
                sidecar_path=None,
                report_html_rel=None,
                verdict="",
                next_hop="",
                tally={},
                bugs_fixed_in_loop=0,
                spec_clarifications=0,
            ))
            continue
        tally = loaded.get("tally") or {}
        report_html = str(loaded.get("report_html") or "report.html")
        rows.append(_DashRow(
            pr_id=pr_id,
            display_id=display_id,
            title=title,
            status=status,
            merged=merged,
            has_sidecar=True,
            sidecar_path=sidecar,
            report_html_rel=f"{pr_id}/{report_html}",
            verdict=str(loaded.get("verdict") or ""),
            next_hop=str(loaded.get("next_hop") or ""),
            tally={k: int(tally.get(k, 0) or 0) for k in _TALLY_KEYS},
            bugs_fixed_in_loop=int(loaded.get("bugs_fixed_in_loop") or 0),
            spec_clarifications=int(loaded.get("spec_clarifications") or 0),
        ))
    return rows


# ---------------------------------------------------------------------------
# Rendering helpers (HTML escaping, icons, styles)
# ---------------------------------------------------------------------------

def _e(text) -> str:
    """HTML-escape any value to text content."""
    return html.escape("" if text is None else str(text))


def _href(rel: str) -> str:
    """URL-encode a relative path for an href attribute (preserves '/')."""
    return html.escape(quote(rel), quote=True)


def _status_icon(status: str) -> str:
    """The PR status icon, matching ``pm pr list`` / the TUI (single source)."""
    from pm_core.cli.helpers import PR_STATUS_ICONS
    return PR_STATUS_ICONS.get(status, "")


def _rich_style_to_css(style: str) -> str:
    for word in (style or "").split():
        if word in _RICH_COLOR_CSS:
            return _RICH_COLOR_CSS[word]
    return "#6e7781"


def _signoff_marker_html(verdict: str) -> str:
    """Icon + label for a sign-off verdict, reusing #225's single sources."""
    if not verdict:
        return ""
    from pm_core.signoff import (
        SIGNOFF_VERDICT_ICONS, SIGNOFF_VERDICT_STYLES,
    )
    icon = SIGNOFF_VERDICT_ICONS.get(verdict, "")
    color = _rich_style_to_css(SIGNOFF_VERDICT_STYLES.get(verdict, ""))
    return (f'<span class="signoff-marker" style="color:{color}">'
            f'{_e(icon)} {_e(verdict)}</span>')


def _tally_html(tally: dict) -> str:
    if not tally:
        return '<span class="muted">no behaviors</span>'
    bits = []
    for k in _TALLY_KEYS:
        n = tally.get(k, 0)
        if n:
            cls = {
                "PASS": "v-pass",
                "NEEDS_WORK": "v-needswork",
                "INPUT_REQUIRED": "v-input",
            }.get(k, "v-pending")
            label = k if k != "pending" else "pending"
            bits.append(f'<span class="badge {cls}">{n} {_e(label)}</span>')
    return " ".join(bits) if bits else '<span class="muted">no behaviors</span>'


def _notes_html(notes: list[str]) -> str:
    if not notes:
        return ""
    items = "".join(f"<li>{_e(n)}</li>" for n in notes)
    return f'<ul class="notes">{items}</ul>'


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
  Helvetica, Arial, sans-serif; margin: 0 auto; padding: 0 1.25rem 4rem;
  max-width: 1100px; line-height: 1.5; color: #1b1f23; background: #fff; }
@media (prefers-color-scheme: dark) {
  body { color: #d8dde3; background: #0d1117; }
  a { color: #58a6ff; }
  th { background: #161b22; }
  pre, code { background: #161b22; }
}
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 1.6rem; margin: 1.2rem 0 .4rem; }
h2 { font-size: 1.15rem; margin: 1.8rem 0 .4rem;
  border-bottom: 1px solid rgba(127,127,127,.3); padding-bottom: .2rem; }
.muted { color: #6a737d; }
.filters { margin: 1rem 0; display: flex; gap: 1.2rem; flex-wrap: wrap;
  font-size: .9rem; align-items: center; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1rem; }
th, td { text-align: left; padding: .5rem .6rem; vertical-align: top;
  border-bottom: 1px solid rgba(127,127,127,.25); }
th { background: #f6f8fa; font-size: .85rem; }
.badge { display: inline-block; font-size: .78rem; font-weight: 600;
  padding: .12rem .55rem; border-radius: 999px; margin: .1rem .2rem .1rem 0;
  border: 1px solid transparent; }
.v-pass { background: #1a7f37; color: #fff; }
.v-needswork { background: #9a6700; color: #fff; }
.v-input { background: #cf222e; color: #fff; }
.v-pending { background: #6e7781; color: #fff; }
.signoff-marker { font-weight: 600; white-space: nowrap; }
.missing { color: #9a6700; font-weight: 600; }
.regen code { background: rgba(127,127,127,.18); padding: .1rem .4rem;
  border-radius: 4px; font-size: .85rem; }
button.copy { font-size: .78rem; padding: .15rem .5rem; cursor: pointer;
  border: 1px solid rgba(127,127,127,.5); border-radius: 5px;
  background: transparent; color: inherit; }
.loopbadge { display: inline-block; font-size: .75rem; font-weight: 600;
  padding: .1rem .45rem; border-radius: 4px; margin-right: .3rem;
  background: rgba(130,80,223,.18); color: inherit;
  border: 1px solid rgba(130,80,223,.5); }
.notes { margin: .3rem 0 .8rem; padding-left: 1.2rem; }
.notes li { margin: .2rem 0; }
"""

_DASH_JS = """
function pmFilter() {
  var st = document.getElementById('f-status').value;
  var mg = document.getElementById('f-merged').value;
  document.querySelectorAll('tr[data-pr]').forEach(function(r) {
    var okS = (st === 'all') || (r.dataset.status === st);
    var okM = (mg === 'all')
      || (mg === 'merged'   && r.dataset.merged === '1')
      || (mg === 'unmerged' && r.dataset.merged === '0');
    r.style.display = (okS && okM) ? '' : 'none';
  });
  document.querySelectorAll('section[data-plan]').forEach(function(sec) {
    var anyVisible = Array.prototype.some.call(
      sec.querySelectorAll('tr[data-pr]'),
      function(r) { return r.style.display !== 'none'; });
    sec.style.display = anyVisible ? '' : 'none';
  });
}
function pmCopy(cmd, btn) {
  if (navigator.clipboard) navigator.clipboard.writeText(cmd);
  var old = btn.textContent; btn.textContent = 'copied';
  setTimeout(function(){ btn.textContent = old; }, 1200);
}
document.addEventListener('DOMContentLoaded', function () {
  var s = document.getElementById('f-status');
  var m = document.getElementById('f-merged');
  if (s) s.addEventListener('change', pmFilter);
  if (m) m.addEventListener('change', pmFilter);
});
"""


def _regenerate_cell(pr_id: str) -> str:
    cmd = f"pm pr signoff {pr_id}"
    return (
        f'<span class="missing">no report yet</span> &middot; '
        f'<span class="regen">regenerate: <code>{_e(cmd)}</code> '
        f'<button class="copy" type="button" '
        f'onclick="pmCopy(\'{_e(cmd)}\', this)">copy</button></span>')


def _loop_badges_html(r: _DashRow) -> str:
    """Small badges surfacing the sidecar's loop-discovery counts.

    Hidden when both counts are zero so a row without substantive loop work
    stays uncluttered.
    """
    parts = []
    if r.bugs_fixed_in_loop:
        parts.append(f'<span class="loopbadge" '
                     f'title="bugs fixed during the review/QA loop">'
                     f'🐞 {r.bugs_fixed_in_loop} fixed</span>')
    if r.spec_clarifications:
        parts.append(f'<span class="loopbadge" '
                     f'title="spec ambiguities resolved during the loop">'
                     f'❓ {r.spec_clarifications} clarified</span>')
    return "".join(parts)


def render_dashboard_html(data: dict, rows: list[_DashRow]) -> str:
    statuses = sorted({r.status for r in rows})
    status_opts = "".join(
        f'<option value="{_e(s)}">{_e(s)}</option>' for s in statuses)

    plans = data.get("plans") or []
    plan_order = [p["id"] for p in plans]
    plan_by_id = {p["id"]: p for p in plans}
    pr_plan = {pr["id"]: pr.get("plan") for pr in (data.get("prs") or [])}

    groups: dict[Optional[str], list[_DashRow]] = {}
    for r in rows:
        groups.setdefault(pr_plan.get(r.pr_id), []).append(r)
    ordered: list[Optional[str]] = [
        pid for pid in plan_order if pid in groups]
    ordered += [k for k in groups if k is not None and k not in plan_order]
    if None in groups:
        ordered.append(None)

    parts: list[str] = []
    parts.append('<!DOCTYPE html><html lang="en"><head>')
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, '
                 'initial-scale=1">')
    parts.append('<title>Behavior dashboard — all PRs</title>')
    parts.append(f'<style>{_CSS}</style></head><body>')
    parts.append('<h1>Behavior dashboard</h1>')
    parts.append('<p class="muted">One sign-off report per PR — written by '
                 'the sign-off agent (<code>pm pr signoff &lt;id&gt;</code>) '
                 'and indexed here. Click a PR to open its report.</p>')

    parts.append('<div class="filters">')
    parts.append('<span><label for="f-status">Status </label>'
                 '<select id="f-status"><option value="all">all</option>'
                 f'{status_opts}</select></span>')
    parts.append('<span><label for="f-merged">Merged </label>'
                 '<select id="f-merged"><option value="all">all</option>'
                 '<option value="merged">merged</option>'
                 '<option value="unmerged">unmerged</option>'
                 '</select></span>')
    parts.append('</div>')

    for key in ordered:
        grp = groups[key]
        parts.append(f'<section data-plan="{_e(str(key) if key else "_unplanned")}">')
        if key is None:
            parts.append('<h2>Unplanned</h2>')
        else:
            plan = plan_by_id.get(key, {})
            parts.append(f'<h2>{_e(plan.get("name", key))}</h2>')
            parts.append(_notes_html(_normalize_notes(plan.get("notes"))))
        parts.append('<table>')
        parts.append('<thead><tr><th>PR</th><th>Title</th><th>Status</th>'
                     '<th>Behaviors</th><th>Loop</th>'
                     '<th>Report</th></tr></thead><tbody>')
        for r in grp:
            # Status cell — status icon (matches pm pr list) + verdict marker.
            s_icon = _status_icon(r.status)
            status_cell = (f'{_e(s_icon)} {_e(r.status)}' if s_icon
                           else _e(r.status))
            if r.verdict:
                status_cell += f'<br>{_signoff_marker_html(r.verdict)}'

            if r.has_sidecar and r.report_html_rel:
                report_cell = f'<a href="{_href(r.report_html_rel)}">open report</a>'
                if r.next_hop:
                    report_cell += (f'<br><span class="muted">next: '
                                    f'{_e(r.next_hop)}</span>')
            else:
                report_cell = _regenerate_cell(r.pr_id)

            parts.append(
                f'<tr data-pr="{_e(r.pr_id)}" data-status="{_e(r.status)}" '
                f'data-merged="{1 if r.merged else 0}">'
                f'<td>{_e(r.display_id)}</td>'
                f'<td>{_e(r.title)}</td>'
                f'<td>{status_cell}</td>'
                f'<td>{_tally_html(r.tally)}</td>'
                f'<td>{_loop_badges_html(r)}</td>'
                f'<td>{report_cell}</td></tr>')
        parts.append('</tbody></table>')
        parts.append('</section>')

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
    resolved (no session tag — e.g. not inside a git repo). The dashboard reads
    one ``report.json`` sidecar per PR from
    ``~/.pm/sessions/<tag>/captures/<pr_id>/`` (written by the sign-off agent
    via the deliverable section of ``generate_signoff_prompt``); PRs without a
    sidecar render an explicit "no report yet" cell with
    ``pm pr signoff <pr_id>`` as the regenerate command.
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
