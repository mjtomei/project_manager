"""HTML behavior reports for sign-off (pr-8e693f6).

Two human-facing surfaces sharing one generator and storage layout:

* **Per-PR BDD report** — ``~/.pm/sessions/<tag>/captures/<pr_id>/report.html``.
  A self-contained HTML page written ALONGSIDE the captures it references
  (relative links, no copy), so it opens over ``file://`` with no server.
  BDD-shaped: per behavior the flow (Given/When/Then), the verdict + reason,
  the evidence inline/linked, plus a top-of-page status summary and the
  sign-off recommendation / next hop. Terminal panes can't show webm; this
  browser page is the sign-off surface.

* **All-PR dashboard** — ``~/.pm/sessions/<tag>/captures/index.html``. Lists
  every PR (grouped by plan) with a one-line behavior/status summary linking
  to its ``report.html``; client-side filtering by merged/unmerged and by
  status; detect-missing rows surface a regenerate command instead of a dead
  link.

Single source of truth with the sign-off step (pr-2d5f712 / pm_core/signoff.py):

* The recommendation / next-hop and the dashboard's per-PR verdict come from
  the router's recorded verdict ``pr['signoff'] = {verdict, sha, ts, origin}``
  (``signoff.latest_signoff_verdict`` + ``signoff.decide_signoff_hop``).
  ``SIGNOFF_MERGE`` is always a *ready_to_merge recommendation* — sign-off never
  merges; the plan auto-start watcher (pr-ff9b728) makes the merge/hold call.
  When no verdict is recorded yet we fall back to a derived heuristic, labelled.
* Verdict/status markers reuse ``signoff.SIGNOFF_VERDICT_ICONS`` /
  ``SIGNOFF_VERDICT_STYLES`` and ``helpers.PR_STATUS_ICONS`` so the HTML matches
  the TUI tech tree and ``pm pr list`` exactly — no marker is redefined here.

Forward-compatible with deps not merged yet:

* **pr-06a96fa** (the evidence model): evidence is discovered generically by
  walking the captures tree and classifying by extension, so new evidence
  kinds render without code changes here.
* **pr-ff9b728** (plan notes): read defensively — rendered when present,
  omitted cleanly when absent today.
"""

from __future__ import annotations

import html
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote

_log = logging.getLogger("pm.behavior_report")

# Canonical per-scenario QA verdicts (mirrors pm_core.qa_loop constants
# without importing the heavy module).
_PASS = "PASS"
_NEEDS_WORK = "NEEDS_WORK"
_INPUT_REQUIRED = "INPUT_REQUIRED"
_VERDICTS = (_PASS, _NEEDS_WORK, _INPUT_REQUIRED)

# Sign-off routing-verdict -> reviewer-facing recommendation. The hop token
# comes from signoff.decide_signoff_hop (single source of truth in #225 /
# pm_core/signoff.py); SIGNOFF_MERGE is always a ready_to_merge RECOMMENDATION
# — sign-off never merges; the plan auto-start watcher (pr-ff9b728) decides.
_SIGNOFF_HOP_TEXT = {
    "ready_to_merge": ("Ready to merge — sign-off recommends merge. Sign-off "
                       "never merges; the plan watcher makes the final "
                       "merge/hold call."),
    "qa": ("Re-QA — sign-off routed the PR back to QA (PASS-unverified or a "
           "misframed scenario)."),
    "review": ("Back to review — a code change happened during QA; "
               "re-validate through review and QA."),
    "impl": "Back to implementation — sign-off found a real gap.",
    "blocked": ("Blocked / escalated — sign-off held the PR (ambiguity, "
                "out-of-scope, or a blocking PR was filed)."),
}

# Map Rich style strings (signoff.SIGNOFF_VERDICT_STYLES, e.g. "bold green")
# to a CSS colour so the HTML verdict markers match the TUI / pm pr list.
_RICH_COLOR_CSS = {
    "green": "#1a7f37",
    "magenta": "#8250df",
    "cyan": "#1b7c83",
    "yellow": "#9a6700",
    "red": "#cf222e",
}

# Filenames inside a scenario dir that are metadata, not evidence.
_NON_EVIDENCE = {"verdict.md", "scenario.json"}

_VIDEO_EXT = {".webm", ".mp4", ".mov", ".ogg"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
_HTML_EXT = {".html", ".htm"}
_TEXT_EXT = {".txt", ".log", ".json", ".md", ".diff", ".patch", ".yaml",
             ".yml", ".csv"}

# Inline text/json evidence up to this size; larger files are linked.
_INLINE_TEXT_MAX = 16 * 1024


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Evidence:
    """A single evidence file referenced from a report."""
    rel: str          # POSIX path relative to the report's directory
    kind: str         # "video" | "image" | "html" | "text" | "other"
    name: str         # display name (path relative to the captures dir)
    size: int         # bytes
    inline_text: Optional[str] = None  # small text/json bodies, read at gather


@dataclass
class Behavior:
    """One QA scenario rendered as a behavior."""
    index: int
    title: str
    focus: str
    steps: str
    verdict: str      # normalized: PASS | NEEDS_WORK | INPUT_REQUIRED | ""
    reason: str
    evidence: list[Evidence] = field(default_factory=list)
    acceptance: list[str] = field(default_factory=list)  # THEN clauses


@dataclass
class ReportData:
    pr_id: str
    display_id: str
    title: str
    status: str
    merged: bool
    description: str
    notes: list[str]
    plan_id: Optional[str]
    plan_name: Optional[str]
    plan_notes: list[str]
    is_bug: bool
    behaviors: list[Behavior]
    impl_evidence: list[Evidence]
    review_evidence: list[Evidence]
    recommendation: str
    recommendation_source: str   # "router" | "derived"
    next_hop: str
    summary: str
    signoff_verdict: str         # SIGNOFF_* keyword from pr['signoff'], or ""
    signoff_stale: bool          # recorded verdict predates the current HEAD


# ---------------------------------------------------------------------------
# Gathering
# ---------------------------------------------------------------------------

def _normalize_notes(raw) -> list[str]:
    """Coerce a notes field into a list of text strings.

    PR notes are ``[{id, text, ...}]``. Plan notes (pr-ff9b728, not merged)
    may arrive as a list of dicts, a list of strings, or a single string —
    handle all defensively so we render whatever lands.
    """
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


def _norm_verdict(v: str) -> str:
    """Normalize a possibly-decorated verdict to a canonical keyword or ""."""
    if not v:
        return ""
    for cand in _VERDICTS:
        if cand in v:
            return cand
    return ""


def _extract_acceptance(steps: str) -> list[str]:
    """Pull the acceptance criteria (THEN clauses) out of free-form steps.

    The THEN of a Given/When/Then triple is the observable outcome the
    evidence must demonstrate — i.e. the step's acceptance criterion. We
    also collect AND/BUT lines and sub-bullets that follow a THEN (the
    concretizer emits "THEN ... / AND ..." and sub-bullets for multiple
    outcomes). Returns [] when steps aren't structured.
    """
    crit: list[str] = []
    capturing = False
    for line in steps.splitlines():
        s = line.strip()
        if not s:
            continue
        upper = s.upper()
        if upper.startswith("THEN:") or upper.startswith("THEN "):
            capturing = True
            rest = s[4:].lstrip(": ").strip()
            if rest:
                crit.append(rest)
        elif upper.startswith("GIVEN:") or upper.startswith("GIVEN ") or \
                upper.startswith("WHEN:") or upper.startswith("WHEN "):
            capturing = False
        elif capturing and (upper.startswith("AND") or upper.startswith("BUT")):
            kw = "AND" if upper.startswith("AND") else "BUT"
            rest = s[len(kw):].lstrip(": ").strip()
            if rest:
                crit.append(rest)
        elif capturing and s[:1] in "-*•":
            rest = s.lstrip("-*• ").strip()
            if rest:
                crit.append(rest)
    return crit


def _phase_of(rel: str) -> str:
    """Classify an evidence path as a bug-fix phase: pre / post / "".

    Matches a ``pre-fix`` / ``post-fix`` *directory* component (the layout
    bug_fix_prompts writes: ``impl/pre-fix/...`` and ``impl/post-fix/...``,
    and the same under ``scenarios/<n>/``). Tolerates ``pre_fix`` spelling;
    ignores the filename so an unrelated file like ``prefix.txt`` isn't
    misread.
    """
    parts = rel.split("/")[:-1]  # directory components only
    for seg in parts:
        norm = seg.lower().replace("_", "-")
        if norm == "pre-fix":
            return "pre"
        if norm == "post-fix":
            return "post"
    return ""


def _partition_phase(
        evidence: list[Evidence]) -> tuple[list[Evidence], list[Evidence],
                                           list[Evidence]]:
    """Split evidence into (pre-fix, post-fix, other) by path."""
    pre, post, other = [], [], []
    for e in evidence:
        ph = _phase_of(e.rel)
        (pre if ph == "pre" else post if ph == "post" else other).append(e)
    return pre, post, other


def _classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _HTML_EXT:
        return "html"
    if ext in _TEXT_EXT:
        return "text"
    return "other"


def _iter_evidence(scan_dir: Path, report_dir: Path,
                   captures_dir: Path) -> list[Evidence]:
    """Walk *scan_dir* recursively, classifying every file as evidence.

    Skips metadata files (verdict.md / scenario.json) and dotfiles. Paths
    are POSIX-relative to *report_dir* (where report.html lives) so links
    resolve over file://; display names are relative to *captures_dir*.
    """
    out: list[Evidence] = []
    if not scan_dir.is_dir():
        return out
    for p in sorted(scan_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.name in _NON_EVIDENCE or p.name.startswith("."):
            continue
        try:
            rel = os.path.relpath(p, report_dir)
            name = os.path.relpath(p, captures_dir)
            size = p.stat().st_size
        except OSError:
            continue
        kind = _classify(p)
        inline = None
        if kind == "text" and size <= _INLINE_TEXT_MAX:
            try:
                inline = p.read_text(errors="replace")
            except OSError:
                inline = None
        out.append(Evidence(
            rel=Path(rel).as_posix(),
            kind=kind,
            name=Path(name).as_posix(),
            size=size,
            inline_text=inline,
        ))
    return out


def _parse_verdict_md(text: str) -> tuple[str, str, str]:
    """Parse a legacy verdict.md → (title, verdict, reason).

    Format written by qa_loop ``_persist_scenario_verdicts``:
        # Scenario <n>: <title>

        <verdict>

        <reason...>
    """
    title = verdict = ""
    reason_lines: list[str] = []
    seen_verdict = False
    for line in text.splitlines():
        s = line.strip()
        if not title and s.startswith("#"):
            head = s.lstrip("#").strip()
            if ":" in head:
                title = head.split(":", 1)[1].strip()
            else:
                title = head
            continue
        if not s:
            continue
        if not seen_verdict:
            verdict = s
            seen_verdict = True
            continue
        reason_lines.append(line)
    return title, verdict, "\n".join(reason_lines).strip()


def _load_behavior(scenario_dir: Path, report_dir: Path,
                   captures_dir: Path) -> Optional[Behavior]:
    """Load one behavior from a ``scenarios/<n>/`` dir.

    Prefers the structured ``scenario.json`` (steps + focus); falls back to
    parsing ``verdict.md`` (steps then unavailable). Returns None when the
    dir holds neither.
    """
    try:
        index = int(scenario_dir.name)
    except (ValueError, TypeError):
        index = -1

    title = focus = steps = verdict = reason = ""
    sj = scenario_dir / "scenario.json"
    vmd = scenario_dir / "verdict.md"
    if sj.is_file():
        try:
            rec = json.loads(sj.read_text())
            index = int(rec.get("index", index))
            title = str(rec.get("title", "") or "")
            focus = str(rec.get("focus", "") or "")
            steps = str(rec.get("steps", "") or "")
            verdict = str(rec.get("verdict", "") or "")
            reason = str(rec.get("reason", "") or "")
        except (OSError, ValueError, TypeError):
            pass
    if (not title and not verdict) and vmd.is_file():
        try:
            title, verdict, reason = _parse_verdict_md(vmd.read_text())
        except OSError:
            pass

    if not title and not verdict and not sj.is_file() and not vmd.is_file():
        # No metadata at all — still surface the dir if it holds evidence.
        ev = _iter_evidence(scenario_dir, report_dir, captures_dir)
        if not ev:
            return None
        return Behavior(index=index, title=f"Scenario {index}", focus="",
                        steps="", verdict="", reason="", evidence=ev)

    return Behavior(
        index=index,
        title=title or f"Scenario {index}",
        focus=focus,
        steps=steps,
        verdict=_norm_verdict(verdict),
        reason=reason,
        evidence=_iter_evidence(scenario_dir, report_dir, captures_dir),
        acceptance=_extract_acceptance(steps),
    )


def _derive_recommendation(behaviors: list[Behavior]) -> tuple[str, str]:
    """Heuristic recommendation / next-hop from scenario verdicts.

    Fallback only — used when the sign-off router has not recorded a verdict
    on the PR yet (``pr['signoff']``). Returns (recommendation, next_hop).
    """
    verdicts = [b.verdict for b in behaviors if b.verdict]
    if not verdicts:
        return ("No recorded behaviors yet — run QA before sign-off.", "qa")
    if any(v == _INPUT_REQUIRED for v in verdicts):
        return ("Input required before sign-off — a human-guided step is "
                "pending.", "input_required")
    if any(v == _NEEDS_WORK for v in verdicts):
        return ("Needs work — at least one behavior did not pass; bounce back "
                "through review/QA.", "needs_work")
    if all(v == _PASS for v in verdicts):
        return ("All recorded behaviors PASS — ready for sign-off / merge.",
                "merge")
    return ("Behaviors incomplete — some verdicts are still pending.",
            "pending")


def _scenario_dirs(captures_dir: Path) -> list[Path]:
    sc = captures_dir / "scenarios"
    if not sc.is_dir():
        return []
    dirs = [d for d in sc.iterdir() if d.is_dir()]

    def _key(d: Path):
        try:
            return (0, int(d.name))
        except ValueError:
            return (1, d.name)
    return sorted(dirs, key=_key)


def gather_pr_report_data(data: dict, pr_id: str,
                          captures_dir: Path) -> ReportData:
    """Assemble everything the per-PR report renders.

    *data* is the loaded project.yaml dict; *captures_dir* is the PR's
    captures directory (where report.html will be written, and the report's
    relative-link base).
    """
    from pm_core import store
    from pm_core.bug_fix_prompts import _is_bug_pr

    pr = store.get_pr(data, pr_id) or {}
    gh = pr.get("gh_pr_number")
    display_id = f"#{gh}" if gh else pr_id

    plan_id = pr.get("plan")
    plan = store.get_plan(data, plan_id) if plan_id else None
    plan_name = plan.get("name") if plan else None
    plan_notes = _normalize_notes(plan.get("notes")) if plan else []

    behaviors: list[Behavior] = []
    for d in _scenario_dirs(captures_dir):
        b = _load_behavior(d, captures_dir, captures_dir)
        if b is not None:
            behaviors.append(b)

    impl_evidence = _iter_evidence(
        captures_dir / "impl", captures_dir, captures_dir)
    # Review captures are not written today; surface a review/ dir if a
    # future evidence model (pr-06a96fa / pr-2d5f712) lands one.
    review_evidence = _iter_evidence(
        captures_dir / "review", captures_dir, captures_dir)

    # Recommendation source priority: the sign-off router's recorded verdict
    # (pr['signoff'], written by pm_core/signoff.py) is authoritative; we only
    # fall back to a derived heuristic when no verdict has been recorded.
    from pm_core.signoff import (
        latest_signoff_verdict, decide_signoff_hop, head_sha,
    )
    signoff_verdict = latest_signoff_verdict(pr) or ""
    signoff_stale = False
    if signoff_verdict:
        hop = decide_signoff_hop(signoff_verdict)
        recommendation = _SIGNOFF_HOP_TEXT.get(
            hop, f"Sign-off verdict: {signoff_verdict}.")
        next_hop = hop
        rec_source = "router"
        # Best-effort staleness: was the verdict computed against the current
        # branch HEAD? (workdir may be gone — degrade silently.)
        try:
            record = (pr.get("signoff") or {})
            cur = head_sha(pr.get("workdir"))
            if record.get("sha") and cur and record["sha"] != cur:
                signoff_stale = True
        except Exception:
            signoff_stale = False
    else:
        recommendation, next_hop = _derive_recommendation(behaviors)
        rec_source = "derived"

    return ReportData(
        pr_id=pr_id,
        display_id=display_id,
        title=pr.get("title", pr_id),
        status=pr.get("status", "unknown"),
        merged=bool(pr.get("merged_at")),
        description=pr.get("description", "") or "",
        notes=_normalize_notes(pr.get("notes")),
        plan_id=plan_id,
        plan_name=plan_name,
        plan_notes=plan_notes,
        is_bug=_is_bug_pr(pr),
        behaviors=behaviors,
        impl_evidence=impl_evidence,
        review_evidence=review_evidence,
        recommendation=recommendation,
        recommendation_source=rec_source,
        next_hop=next_hop,
        summary="",
        signoff_verdict=signoff_verdict,
        signoff_stale=signoff_stale,
    )


# ---------------------------------------------------------------------------
# Rendering — shared
# ---------------------------------------------------------------------------

def _e(text) -> str:
    """HTML-escape any value to text content."""
    return html.escape("" if text is None else str(text))


def _href(rel: str) -> str:
    """URL-encode a relative path for an href/src attribute (keeps '/')."""
    return html.escape(quote(rel), quote=True)


def _verdict_class(v: str) -> str:
    return {
        _PASS: "v-pass",
        _NEEDS_WORK: "v-needswork",
        _INPUT_REQUIRED: "v-input",
    }.get(v, "v-pending")


def _verdict_label(v: str) -> str:
    return v if v else "pending"


def _status_icon(status: str) -> str:
    """The PR status icon, matching ``pm pr list`` / the TUI (single source)."""
    from pm_core.cli.helpers import PR_STATUS_ICONS
    return PR_STATUS_ICONS.get(status, "")


def _rich_style_to_css(style: str) -> str:
    """Map a Rich style string (e.g. "bold green") to a CSS colour."""
    for word in (style or "").split():
        if word in _RICH_COLOR_CSS:
            return _RICH_COLOR_CSS[word]
    return "#6e7781"


def _signoff_marker_html(verdict: str) -> str:
    """A coloured icon+label for a sign-off routing verdict.

    Reuses signoff.SIGNOFF_VERDICT_ICONS / SIGNOFF_VERDICT_STYLES (the single
    source of truth shared with the TUI tech tree and ``pm pr list``) so the
    HTML marker matches every other surface.
    """
    if not verdict:
        return ""
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
  Helvetica, Arial, sans-serif; margin: 0; padding: 0 1.25rem 4rem;
  line-height: 1.5; color: #1b1f23; background: #fff;
  max-width: 1000px; margin-left: auto; margin-right: auto; }
@media (prefers-color-scheme: dark) {
  body { color: #d8dde3; background: #0d1117; }
  a { color: #58a6ff; }
  .card, header.summary { background: #161b22; border-color: #30363d; }
  pre, code { background: #161b22; }
  .steps { background: #0b1622; }
  th { background: #161b22; }
}
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { font-size: 1.6rem; margin: 1.2rem 0 0.2rem; }
h2 { font-size: 1.25rem; margin: 2rem 0 0.6rem;
  border-bottom: 1px solid rgba(127,127,127,.3); padding-bottom: .2rem; }
h3 { font-size: 1.05rem; margin: .2rem 0; }
.muted { color: #6a737d; }
.crumbs { font-size: .85rem; margin: .8rem 0; }
header.summary { border: 1px solid #d0d7de; border-radius: 10px;
  padding: 1rem 1.2rem; margin: 1rem 0 1.5rem; background: #f6f8fa; }
.badges { margin: .4rem 0; }
.badge { display: inline-block; font-size: .78rem; font-weight: 600;
  padding: .12rem .55rem; border-radius: 999px; margin: .15rem .3rem .15rem 0;
  border: 1px solid transparent; }
.v-pass { background: #1a7f37; color: #fff; }
.v-needswork { background: #9a6700; color: #fff; }
.v-input { background: #cf222e; color: #fff; }
.v-pending { background: #6e7781; color: #fff; }
.status-pill { background: rgba(127,127,127,.18); color: inherit;
  border: 1px solid rgba(127,127,127,.4); }
.rec { font-size: 1.05rem; margin: .6rem 0 .2rem; }
.card { border: 1px solid #d0d7de; border-radius: 10px; padding: 1rem 1.2rem;
  margin: 1rem 0; background: #fafbfc; }
.behavior-head { display: flex; align-items: baseline; gap: .6rem;
  flex-wrap: wrap; }
.steps { background: #f0f6ff; border-radius: 6px; padding: .6rem .9rem;
  margin: .6rem 0; }
.gwt { margin: .15rem 0; }
.gwt b { display: inline-block; min-width: 4.2rem; }
pre { white-space: pre-wrap; word-wrap: break-word; background: #f6f8fa;
  padding: .7rem .9rem; border-radius: 6px; overflow-x: auto; font-size: .85rem; }
.evidence { margin: .6rem 0; }
.evidence figure { margin: .8rem 0; }
.evidence video, .evidence img { max-width: 100%; border-radius: 6px;
  border: 1px solid rgba(127,127,127,.3); }
figcaption { font-size: .8rem; color: #6a737d; margin-top: .2rem; }
details > summary { cursor: pointer; font-weight: 600; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { text-align: left; padding: .5rem .6rem;
  border-bottom: 1px solid rgba(127,127,127,.25); vertical-align: top; }
th { background: #f6f8fa; font-size: .85rem; }
.filters { margin: 1rem 0; display: flex; gap: 1.2rem; flex-wrap: wrap;
  align-items: center; font-size: .9rem; }
.filters label { margin-right: .4rem; }
.missing { color: #9a6700; font-weight: 600; }
.regen code { background: rgba(127,127,127,.18); padding: .1rem .4rem;
  border-radius: 4px; font-size: .85rem; }
button.copy { font-size: .78rem; padding: .15rem .5rem; cursor: pointer;
  border: 1px solid rgba(127,127,127,.5); border-radius: 5px;
  background: transparent; color: inherit; }
.notes li { margin: .25rem 0; }
.acceptance { margin: .3rem 0; padding-left: 1.2rem; }
.acceptance li { margin: .2rem 0; }
.beforeafter { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 720px) { .beforeafter { grid-template-columns: 1fr; } }
.phase { margin: 0; }
.phase-pre { border-left: 4px solid #cf222e; }
.phase-post { border-left: 4px solid #1a7f37; }
.signoff-marker { font-weight: 600; white-space: nowrap; }
"""


def _render_steps_html(steps: str) -> str:
    """Render free-form STEPS as Given/When/Then lines when recognizable."""
    if not steps.strip():
        return '<p class="muted">Steps not recorded.</p>'
    keywords = ("GIVEN", "WHEN", "THEN", "AND", "BUT")
    lines = steps.splitlines()
    structured = any(
        line.strip().upper().startswith(k + ":") or
        line.strip().upper().startswith(k + " ")
        for line in lines for k in keywords
    )
    if not structured:
        return f'<pre>{_e(steps)}</pre>'
    out = ['<div class="steps">']
    for line in lines:
        s = line.strip()
        if not s:
            continue
        upper = s.upper()
        kw = next((k for k in keywords
                   if upper.startswith(k + ":") or upper.startswith(k + " ")),
                  None)
        if kw:
            rest = s[len(kw):].lstrip(": ").strip()
            out.append(f'<div class="gwt"><b>{_e(kw.title())}</b> '
                       f'{_e(rest)}</div>')
        else:
            out.append(f'<div class="gwt" style="margin-left:4.2rem">'
                       f'{_e(s)}</div>')
    out.append('</div>')
    return "".join(out)


def _render_evidence_html(evidence: list[Evidence]) -> str:
    if not evidence:
        return '<p class="muted">No evidence captured.</p>'
    out = ['<div class="evidence">']
    for ev in evidence:
        href = _href(ev.rel)
        cap = (f'<figcaption><a href="{href}">{_e(ev.name)}</a> '
               f'<span class="muted">({_human_size(ev.size)})</span>'
               f'</figcaption>')
        if ev.kind == "video":
            out.append(
                f'<figure><video controls preload="metadata" '
                f'src="{href}"></video>{cap}</figure>')
        elif ev.kind == "image":
            out.append(
                f'<figure><img loading="lazy" src="{href}" '
                f'alt="{_e(ev.name)}">{cap}</figure>')
        elif ev.kind == "text" and ev.inline_text is not None:
            body = ev.inline_text
            out.append(
                f'<figure><details><summary>{_e(ev.name)} '
                f'<span class="muted">({_human_size(ev.size)})</span>'
                f'</summary><pre>{_e(body)}</pre></details>'
                f'<figcaption><a href="{href}">open file</a></figcaption>'
                f'</figure>')
        else:  # html, other, or oversized text → link
            label = ("open page" if ev.kind == "html" else "download")
            out.append(
                f'<figure><figcaption><a href="{href}">{_e(ev.name)}</a> '
                f'<span class="muted">({_human_size(ev.size)})</span> — '
                f'{label}</figcaption></figure>')
    out.append('</div>')
    return "".join(out)


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{int(n)} B"


def _notes_html(notes: list[str], empty: str) -> str:
    if not notes:
        return f'<p class="muted">{_e(empty)}</p>'
    items = "".join(f"<li>{_e(n)}</li>" for n in notes)
    return f'<ul class="notes">{items}</ul>'


def _acceptance_html(criteria: list[str], fallback: str = "") -> str:
    """Render a step's acceptance criteria as a checklist."""
    if not criteria:
        return (f'<p class="muted">{_e(fallback)}</p>' if fallback else "")
    items = "".join(f'<li>{_e(c)}</li>' for c in criteria)
    return f'<ul class="acceptance">{items}</ul>'


def _render_impl_step(rd: ReportData) -> str:
    """Render the implementation step (always present so impl/review/qa are
    uniform, per note-e1ff391).

    For bug fixes: the before/after — pre-fix = bug reproduced, post-fix =
    symptom gone — each paired with its acceptance criterion. Otherwise: the
    impl acceptance ("change implemented per the description") with a flat
    evidence block or an explicit empty state.
    """
    pre, post, other = _partition_phase(rd.impl_evidence)
    show_beforeafter = rd.is_bug or bool(pre) or bool(post)

    out: list[str] = ['<h2>Implementation</h2>']
    if show_beforeafter:
        out.append('<p class="muted">Bug fix — the before/after record: the '
                   'bug reproduced on pre-fix code, then gone on post-fix '
                   'code.</p>')
        out.append('<div class="beforeafter">')
        # Before (pre-fix)
        out.append('<section class="card phase phase-pre">')
        out.append('<h3>Before — pre-fix (bug reproduced)</h3>')
        out.append('<h4 style="margin:.4rem 0 .1rem">Acceptance</h4>')
        out.append('<ul class="acceptance"><li>The bug reproduces on '
                   'pre-fix code (symptom present).</li></ul>')
        out.append('<h4 style="margin:.4rem 0 .1rem">Evidence</h4>')
        out.append(_render_evidence_html(pre) if pre else
                   '<p class="missing">No pre-fix capture recorded — the '
                   'reproduction before/after is incomplete.</p>')
        out.append('</section>')
        # After (post-fix)
        out.append('<section class="card phase phase-post">')
        out.append('<h3>After — post-fix (symptom gone)</h3>')
        out.append('<h4 style="margin:.4rem 0 .1rem">Acceptance</h4>')
        out.append('<ul class="acceptance"><li>The symptom no longer '
                   'reproduces on post-fix code (fix verified).</li></ul>')
        out.append('<h4 style="margin:.4rem 0 .1rem">Evidence</h4>')
        out.append(_render_evidence_html(post) if post else
                   '<p class="missing">No post-fix capture recorded — the '
                   'reproduction before/after is incomplete.</p>')
        out.append('</section>')
        out.append('</div>')
        if other:
            out.append('<section class="card">')
            out.append('<h3>Other implementation evidence</h3>')
            out.append(_render_evidence_html(other))
            out.append('</section>')
    else:
        out.append('<section class="card">')
        out.append('<h4 style="margin:.2rem 0 .1rem">Acceptance</h4>')
        out.append('<ul class="acceptance"><li>The change is implemented and '
                   'self-verified per the PR description.</li></ul>')
        out.append('<h4 style="margin:.6rem 0 .1rem">Evidence</h4>')
        if rd.impl_evidence:
            out.append(_render_evidence_html(rd.impl_evidence))
        else:
            out.append('<p class="muted">No implementation captures '
                       'recorded.</p>')
        out.append('</section>')
    return "".join(out)


def _render_review_step(rd: ReportData) -> str:
    """Render the review step (always present, per note-e1ff391's impl/review/qa).

    Review doesn't write captures today, so this is forward-compatible: it
    surfaces a ``review/`` captures dir when one exists and otherwise shows
    the step's acceptance criterion with an explicit empty state — keeping
    review a visible step rather than collapsing the report onto QA.
    """
    out: list[str] = ['<h2>Review</h2>']
    out.append('<section class="card">')
    out.append('<h4 style="margin:.2rem 0 .1rem">Acceptance</h4>')
    out.append('<ul class="acceptance"><li>The diff passes review — approved '
               'with no blocking findings.</li></ul>')
    out.append('<h4 style="margin:.6rem 0 .1rem">Evidence</h4>')
    if rd.review_evidence:
        out.append(_render_evidence_html(rd.review_evidence))
    else:
        out.append('<p class="muted">No review captures recorded (review '
                   'verdicts are tracked on the PR; see the notes below).</p>')
    out.append('</section>')
    return "".join(out)


# ---------------------------------------------------------------------------
# Rendering — per-PR report
# ---------------------------------------------------------------------------

def render_pr_report_html(rd: ReportData) -> str:
    tally: dict[str, int] = {}
    for b in rd.behaviors:
        key = b.verdict or "pending"
        tally[key] = tally.get(key, 0) + 1

    status_icon = _status_icon(rd.status)
    status_prefix = f"{status_icon} " if status_icon else ""
    badges = [f'<span class="badge status-pill">{_e(status_prefix)}status: '
              f'{_e(rd.status)}</span>']
    if rd.merged:
        badges.append('<span class="badge status-pill">merged</span>')
    for v in (_PASS, _NEEDS_WORK, _INPUT_REQUIRED, "pending"):
        n = tally.get(v, 0)
        if n:
            badges.append(
                f'<span class="badge {_verdict_class(v if v != "pending" else "")}">'
                f'{_e(_verdict_label(v if v != "pending" else ""))}: {n}</span>')

    if rd.recommendation_source == "router":
        rec_note = ""
        if rd.signoff_stale:
            rec_note = (' <span class="muted">(this verdict predates the '
                        'latest code change — re-run sign-off)</span>')
    else:
        rec_note = (' <span class="muted">(derived from QA verdicts — no '
                    'sign-off verdict recorded yet)</span>')

    parts: list[str] = []
    parts.append("<!DOCTYPE html><html lang=\"en\"><head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, '
                 'initial-scale=1">')
    parts.append(f"<title>{_e(rd.display_id)} — behavior report</title>")
    parts.append(f"<style>{_CSS}</style></head><body>")

    parts.append('<div class="crumbs"><a href="../index.html">'
                 '&larr; All-PR behavior dashboard</a></div>')
    parts.append(f"<h1>{_e(rd.display_id)} — {_e(rd.title)}</h1>")

    parts.append('<header class="summary">')
    parts.append(f'<div class="badges">{"".join(badges)}</div>')
    if rd.signoff_verdict:
        parts.append(f'<div class="rec"><b>Sign-off verdict:</b> '
                     f'{_signoff_marker_html(rd.signoff_verdict)}</div>')
    parts.append(f'<div class="rec"><b>Recommendation:</b> '
                 f'{_e(rd.recommendation)}{rec_note}</div>')
    if rd.next_hop:
        parts.append(f'<div class="muted">Next hop: {_e(rd.next_hop)}</div>')
    if rd.summary:
        parts.append(f'<p>{_e(rd.summary)}</p>')
    parts.append('</header>')

    parts.append('<p class="muted">Each step below pairs its acceptance '
                 'criteria with the evidence that demonstrates them.</p>')

    # Steps in lifecycle order: impl -> review -> qa, each pairing its
    # acceptance criteria with the evidence that demonstrates them.
    parts.append(_render_impl_step(rd))
    parts.append(_render_review_step(rd))

    # QA step — one behavior per scenario, evidence against its criteria.
    parts.append('<h2>QA behaviors</h2>')
    if not rd.behaviors:
        parts.append('<p class="muted">No recorded behaviors yet. Run QA for '
                     'this PR, then regenerate this report.</p>')
    for b in rd.behaviors:
        parts.append('<section class="card">')
        parts.append('<div class="behavior-head">')
        parts.append(f'<h3>Behavior {b.index}: {_e(b.title)}</h3>')
        parts.append(f'<span class="badge {_verdict_class(b.verdict)}">'
                     f'{_e(_verdict_label(b.verdict))}</span>')
        parts.append('</div>')
        if b.focus:
            parts.append(f'<p class="muted">Focus: {_e(b.focus)}</p>')
        parts.append('<h4 style="margin:.6rem 0 .1rem">Flow</h4>')
        parts.append(_render_steps_html(b.steps))
        parts.append('<h4 style="margin:.6rem 0 .1rem">Acceptance criteria'
                     '</h4>')
        parts.append(_acceptance_html(
            b.acceptance,
            "Not separable from the steps above (no explicit THEN)."))
        if b.reason:
            parts.append(f'<p><b>Reason:</b> {_e(b.reason)}</p>')
        parts.append('<h4 style="margin:.6rem 0 .1rem">Evidence</h4>')
        # If a bug-fix scenario captured pre/post, show the before/after.
        bpre, bpost, bother = _partition_phase(b.evidence)
        if bpre or bpost:
            parts.append('<p class="muted">Before — pre-fix:</p>')
            parts.append(_render_evidence_html(bpre))
            parts.append('<p class="muted">After — post-fix:</p>')
            parts.append(_render_evidence_html(bpost))
            if bother:
                parts.append(_render_evidence_html(bother))
        else:
            parts.append(_render_evidence_html(b.evidence))
        parts.append('</section>')

    # Reachable context
    parts.append('<h2>Context for sign-off</h2>')
    parts.append('<section class="card">')
    parts.append('<h3>PR description</h3>')
    if rd.description.strip():
        parts.append(f'<pre>{_e(rd.description)}</pre>')
    else:
        parts.append('<p class="muted">No description.</p>')
    parts.append('<h3>PR notes</h3>')
    parts.append(_notes_html(rd.notes, "No PR notes."))
    if rd.plan_id:
        parts.append(f'<h3>Plan: {_e(rd.plan_name or rd.plan_id)}</h3>')
        parts.append(_notes_html(rd.plan_notes, "No plan notes."))
    parts.append('</section>')

    parts.append('</body></html>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Rendering — dashboard
# ---------------------------------------------------------------------------

@dataclass
class _DashRow:
    pr_id: str
    display_id: str
    title: str
    status: str
    merged: bool
    has_report: bool
    summary: str
    rec: str
    signoff_verdict: str  # SIGNOFF_* keyword (latest recorded), or ""


def _pr_capture_summary(pr: dict, captures_dir: Path) -> tuple[str, str]:
    """One-line (tally, recommendation) for a PR.

    The recommendation prefers the sign-off router's recorded verdict
    (``pr['signoff']``); the per-scenario tally comes from retained captures.
    """
    from pm_core.signoff import latest_signoff_verdict, decide_signoff_hop

    behaviors: list[Behavior] = []
    for d in _scenario_dirs(captures_dir):
        b = _load_behavior(d, captures_dir, captures_dir)
        if b is not None:
            behaviors.append(b)
    tally: dict[str, int] = {}
    for b in behaviors:
        tally[b.verdict or "pending"] = tally.get(b.verdict or "pending", 0) + 1
    bits = []
    for v in (_PASS, _NEEDS_WORK, _INPUT_REQUIRED, "pending"):
        if tally.get(v):
            bits.append(f"{tally[v]} {_verdict_label(v if v != 'pending' else '')}")
    tally_str = ", ".join(bits) if bits else "no behaviors recorded"

    verdict = latest_signoff_verdict(pr) or ""
    if verdict:
        rec = _SIGNOFF_HOP_TEXT.get(decide_signoff_hop(verdict),
                                    f"sign-off verdict: {verdict}")
    elif behaviors:
        rec = _derive_recommendation(behaviors)[0]
    else:
        rec = ""
    return (tally_str, rec)


def gather_dashboard_rows(data: dict,
                          captures_root_dir: Path) -> list[_DashRow]:
    from pm_core.signoff import latest_signoff_verdict

    rows: list[_DashRow] = []
    for pr in data.get("prs") or []:
        pr_id = pr["id"]
        gh = pr.get("gh_pr_number")
        cdir = captures_root_dir / pr_id
        has_report = (cdir / "report.html").is_file()
        summary, rec = _pr_capture_summary(pr, cdir)
        rows.append(_DashRow(
            pr_id=pr_id,
            display_id=f"#{gh}" if gh else pr_id,
            title=pr.get("title", pr_id),
            status=pr.get("status", "unknown"),
            merged=bool(pr.get("merged_at")),
            has_report=has_report,
            summary=summary,
            rec=rec,
            signoff_verdict=latest_signoff_verdict(pr) or "",
        ))
    return rows


_DASH_JS = """
function pmFilter() {
  var st = document.getElementById('f-status').value;
  var mg = document.getElementById('f-merged').value;
  var rows = document.querySelectorAll('tr[data-pr]');
  rows.forEach(function(r) {
    var okStatus = (st === 'all') || (r.dataset.status === st);
    var okMerged = (mg === 'all') ||
      (mg === 'merged' ? r.dataset.merged === '1'
                       : r.dataset.merged === '0');
    r.style.display = (okStatus && okMerged) ? '' : 'none';
  });
}
function pmCopy(cmd, btn) {
  navigator.clipboard && navigator.clipboard.writeText(cmd);
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


def render_dashboard_html(data: dict, rows: list[_DashRow]) -> str:
    statuses = sorted({r.status for r in rows})
    status_opts = "".join(
        f'<option value="{_e(s)}">{_e(s)}</option>' for s in statuses)

    # Group rows by plan, preserving plan order from project.yaml.
    plans = data.get("plans") or []
    plan_order = [p["id"] for p in plans]
    plan_by_id = {p["id"]: p for p in plans}
    pr_plan = {pr["id"]: pr.get("plan") for pr in (data.get("prs") or [])}

    groups: dict[Optional[str], list[_DashRow]] = {}
    for r in rows:
        groups.setdefault(pr_plan.get(r.pr_id), []).append(r)

    ordered_keys: list[Optional[str]] = [
        pid for pid in plan_order if pid in groups]
    ordered_keys += [k for k in groups
                     if k is not None and k not in plan_order]
    if None in groups:
        ordered_keys.append(None)

    parts: list[str] = []
    parts.append('<!DOCTYPE html><html lang="en"><head>')
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, '
                 'initial-scale=1">')
    parts.append('<title>Behavior dashboard — all PRs</title>')
    parts.append(f'<style>{_CSS}</style></head><body>')
    parts.append('<h1>Behavior dashboard</h1>')
    parts.append('<p class="muted">Every PR reviewed by behavior. '
                 'Click a PR to open its per-PR BDD report.</p>')

    parts.append('<div class="filters">')
    parts.append('<span><label for="f-status">Status</label>'
                 '<select id="f-status"><option value="all">all</option>'
                 f'{status_opts}</select></span>')
    parts.append('<span><label for="f-merged">Merged</label>'
                 '<select id="f-merged"><option value="all">all</option>'
                 '<option value="merged">merged</option>'
                 '<option value="unmerged">unmerged</option>'
                 '</select></span>')
    parts.append('</div>')

    for key in ordered_keys:
        grp = groups[key]
        if key is None:
            parts.append('<h2>Unplanned</h2>')
        else:
            plan = plan_by_id.get(key, {})
            parts.append(f'<h2>{_e(plan.get("name", key))}</h2>')
            plan_notes = _normalize_notes(plan.get("notes"))
            if plan_notes:
                parts.append(_notes_html(plan_notes, ""))
        parts.append('<table>')
        parts.append('<thead><tr><th>PR</th><th>Title</th><th>Status</th>'
                     '<th>Behaviors</th><th>Report</th></tr></thead><tbody>')
        for r in grp:
            href = _href(f"{r.pr_id}/report.html")
            if r.has_report:
                report_cell = f'<a href="{href}">open report</a>'
            else:
                cmd = f"pm pr report {r.pr_id}"
                report_cell = (
                    f'<span class="missing">no report</span> &middot; '
                    f'<span class="regen">regenerate: <code>{_e(cmd)}</code> '
                    f'<button class="copy" type="button" '
                    f'onclick="pmCopy(\'{_e(cmd)}\', this)">copy</button>'
                    f'</span>')
            summary = _e(r.summary)
            if r.rec:
                summary += f' <span class="muted">— {_e(r.rec)}</span>'
            # Status cell: status icon (matches pm pr list / TUI) + the
            # latest recorded sign-off verdict marker for sign_off PRs.
            s_icon = _status_icon(r.status)
            status_cell = f'{_e(s_icon)} {_e(r.status)}' if s_icon \
                else _e(r.status)
            if r.signoff_verdict:
                status_cell += f'<br>{_signoff_marker_html(r.signoff_verdict)}'
            parts.append(
                f'<tr data-pr="{_e(r.pr_id)}" data-status="{_e(r.status)}" '
                f'data-merged="{1 if r.merged else 0}">'
                f'<td>{_e(r.display_id)}</td>'
                f'<td>{_e(r.title)}</td>'
                f'<td>{status_cell}</td>'
                f'<td>{summary}</td>'
                f'<td>{report_cell}</td></tr>')
        parts.append('</tbody></table>')

    parts.append(f'<script>{_DASH_JS}</script>')
    parts.append('</body></html>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Public generation API
# ---------------------------------------------------------------------------

def generate_pr_report(root: Path, pr_id: str, *,
                       session_tag: str | None = None,
                       data: dict | None = None,
                       refresh_dashboard: bool = True) -> Optional[Path]:
    """Generate ``report.html`` for *pr_id* into its captures dir.

    Returns the written path, or None when the captures dir can't be
    resolved (no session tag). Unless *refresh_dashboard* is False, also
    refreshes the dashboard so the PR's "missing report" row flips to a
    live link (callers regenerating many reports pass False and rebuild the
    dashboard once at the end). Safe to call at sign-off time (pr-2d5f712)
    or by hand via ``pm pr report``.
    """
    from pm_core import store
    from pm_core.paths import captures_dir

    if data is None:
        data = store.load(root)
    cdir = captures_dir(pr_id, session_tag=session_tag)
    if cdir is None:
        _log.warning("Cannot resolve captures dir for %s (no session tag)",
                     pr_id)
        return None
    cdir.mkdir(parents=True, exist_ok=True)
    rd = gather_pr_report_data(data, pr_id, cdir)
    out_path = cdir / "report.html"
    out_path.write_text(render_pr_report_html(rd))
    # Keep the dashboard in sync (best effort).
    if refresh_dashboard:
        try:
            generate_dashboard(root, session_tag=session_tag, data=data)
        except Exception:
            _log.warning("dashboard refresh failed after %s report", pr_id,
                         exc_info=True)
    return out_path


def generate_dashboard(root: Path, *, session_tag: str | None = None,
                       data: dict | None = None) -> Optional[Path]:
    """Generate the all-PR dashboard ``index.html`` at the captures root.

    Returns the written path, or None when the captures root can't be
    resolved (no session tag).
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
    out_path.write_text(render_dashboard_html(data, rows))
    return out_path
