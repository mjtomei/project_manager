"""Tests for the all-PR behavior dashboard + the sign-off prompt extension
(pr-8e693f6).

Per-PR ``report.html`` is agent-written. The dashboard is the deterministic
surface: one row per PR with the title (from ``project.yaml``), a link to
``report.html``, and the sign-off verdict parsed straight out of a
``pm-signoff-verdict`` meta tag in that file's ``<head>``.
"""

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

import pm_core.behavior_report as br
from pm_core.cli.pr import pr_dashboard
from pm_core import signoff


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _data():
    return {
        "prs": [
            {"id": "pr-aaa", "title": "Add thing", "status": "sign_off",
             "gh_pr_number": 42, "description": "desc"},
            {"id": "pr-bbb", "title": "No report PR", "status": "pending"},
            {"id": "pr-ccc", "title": "Merged one", "status": "merged",
             "merged_at": "2026-01-01T00:00:00Z"},
        ],
    }


def _write_report(root: Path, pr_id: str, verdict: str | None) -> Path:
    """Write a minimal report.html with optional verdict meta tag."""
    head_meta = (f'<meta name="pm-signoff-verdict" content="{verdict}">'
                 if verdict else "")
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta charset="utf-8">'
        f'{head_meta}'
        '<title>report</title>'
        '</head><body><h1>report</h1></body></html>'
    )
    pdir = root / pr_id
    pdir.mkdir(parents=True, exist_ok=True)
    out = pdir / "report.html"
    out.write_text(html, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Row gathering
# ---------------------------------------------------------------------------

def test_report_drives_row_with_verdict_from_meta(tmp_path):
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.has_report
    assert aaa.report_html_rel == "pr-aaa/report.html"
    assert aaa.verdict == signoff.SIGNOFF_MERGE
    assert aaa.title == "Add thing"
    assert aaa.gh_label == "#42"


def test_missing_report_row_still_appears(tmp_path):
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    bbb = next(r for r in rows if r.pr_id == "pr-bbb")
    assert bbb.has_report is False
    assert bbb.report_html_rel is None
    assert bbb.verdict == ""
    assert bbb.gh_label == ""  # no gh_pr_number


def test_report_without_meta_yields_empty_verdict(tmp_path):
    _write_report(tmp_path, "pr-aaa", verdict=None)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.has_report
    assert aaa.verdict == ""


def test_meta_tag_in_body_ignored(tmp_path):
    """A verbatim verdict keyword (or even a meta) in <body> must NOT match —
    only the <head> meta tag is canonical."""
    pdir = tmp_path / "pr-aaa"
    pdir.mkdir(parents=True)
    (pdir / "report.html").write_text(
        '<!DOCTYPE html><html><head><title>x</title></head>'
        '<body>SIGNOFF_MERGE appears in body text\n'
        '<meta name="pm-signoff-verdict" content="SIGNOFF_MERGE">'
        '</body></html>',
        encoding="utf-8")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.verdict == ""


def test_pr_state_read_from_project_yaml(tmp_path):
    """Title comes from project.yaml — not from anything in the report."""
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    data = _data()
    rows = br.gather_dashboard_rows(data, tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.title == "Add thing"


# ---------------------------------------------------------------------------
# Dashboard rendering
# ---------------------------------------------------------------------------

def test_dashboard_links_to_agent_written_report(tmp_path):
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert 'href="pr-aaa/report.html"' in h


def test_dashboard_missing_state_uses_pm_pr_signoff(tmp_path):
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert "no report yet" in h
    assert "pm pr signoff pr-bbb" in h


def test_dashboard_renders_verdict_icon(tmp_path):
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert signoff.SIGNOFF_VERDICT_ICONS[signoff.SIGNOFF_MERGE] in h
    assert "SIGNOFF_MERGE" in h


def test_dashboard_shows_verdict_unknown_when_no_meta(tmp_path):
    _write_report(tmp_path, "pr-aaa", verdict=None)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert "verdict unknown" in h


def test_dashboard_shows_gh_id_when_present(tmp_path):
    _write_report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert "pr-aaa" in h
    assert "#42" in h


# ---------------------------------------------------------------------------
# Sign-off prompt extension
# ---------------------------------------------------------------------------

def test_signoff_prompt_includes_report_deliverable():
    from pm_core import prompt_gen
    p = prompt_gen.generate_signoff_prompt(
        _data(), "pr-aaa", session_name="pm-test")
    assert "report.html" in p
    # No JSON sidecar anymore — dashboard reads the verdict from report.html.
    assert "report.json" not in p
    # The verdict meta tag is the dashboard's only machine-readable contract.
    assert "pm-signoff-verdict" in p
    # PR bullet points still required in report.html
    assert "Bugs fixed by review and QA" in p
    assert "Spec ambiguities resolved" in p
    assert "unfamiliar" in p.lower()
    assert "SIGNOFF_VERDICT_ICONS" in p


def test_signoff_prompt_keeps_route_step_numbered_last():
    from pm_core import prompt_gen
    p = prompt_gen.generate_signoff_prompt(
        _data(), "pr-aaa", session_name="pm-test")
    assert "4. **Write the sign-off report" in p
    assert "5. **Route" in p


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_dashboard_generates_index(tmp_path, monkeypatch):
    pm_root = tmp_path / "pm"
    pm_root.mkdir()
    caps = tmp_path / "captures"
    caps.mkdir()
    _write_report(caps, "pr-aaa", signoff.SIGNOFF_MERGE)

    from pm_core import store
    store.save(_data(), pm_root)

    monkeypatch.setattr(
        "pm_core.paths.captures_root",
        lambda session_tag=None, start_path=None: caps)

    with patch("pm_core.cli.pr.state_root", return_value=pm_root):
        res = CliRunner().invoke(pr_dashboard, [])
    assert res.exit_code == 0, res.output
    out = (caps / "index.html").read_text()
    assert 'href="pr-aaa/report.html"' in out
    assert "pm pr signoff pr-bbb" in out


def test_pr_report_command_is_removed():
    import pm_core.cli.pr as pr_cli
    assert not hasattr(pr_cli, "pr_report")
