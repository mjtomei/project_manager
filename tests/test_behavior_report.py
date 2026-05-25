"""Tests for the sign-off behavior report + dashboard (pr-8e693f6)."""

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

import pm_core.behavior_report as br
from pm_core.cli.pr import pr_report, pr_dashboard


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _data():
    return {
        "plans": [
            {"id": "plan-x", "name": "Regression loop", "status": "active",
             "notes": [{"text": "watcher continuity"}]},
        ],
        "prs": [
            {"id": "pr-aaa", "title": "Add thing", "status": "qa",
             "plan": "plan-x", "gh_pr_number": 42,
             "description": "desc line one\ndesc line two",
             "notes": [{"text": "handoff one"}, {"text": "handoff two"}]},
            {"id": "pr-bbb", "title": "No captures", "status": "pending",
             "plan": "plan-x"},
            {"id": "pr-ccc", "title": "Merged one", "status": "merged",
             "merged_at": "2026-01-01T00:00:00Z"},
        ],
    }


def _seed_captures(root: Path, pr_id: str = "pr-aaa") -> Path:
    cap = root / pr_id
    sc1 = cap / "scenarios" / "1"
    sc1.mkdir(parents=True)
    (sc1 / "scenario.json").write_text(json.dumps({
        "index": 1, "title": "Login flow", "focus": "auth",
        "steps": "GIVEN: a logged-out user\nWHEN: submit creds\n"
                 "THEN: dashboard shows",
        "verdict": "PASS", "reason": "all good"}))
    (sc1 / "rec.webm").write_bytes(b"\x00" * 2048)
    (sc1 / "shot.png").write_bytes(b"\x00" * 500)
    (sc1 / "out.txt").write_text("hello log")
    return cap


# ---------------------------------------------------------------------------
# Per-PR report
# ---------------------------------------------------------------------------

def test_per_pr_report_bdd_shape(tmp_path):
    cap = _seed_captures(tmp_path)
    rd = br.gather_pr_report_data(_data(), "pr-aaa", cap)
    h = br.render_pr_report_html(rd)

    # Given/When/Then rendered
    assert "<b>Given</b>" in h and "<b>When</b>" in h and "<b>Then</b>" in h
    # Verdict + reason
    assert "PASS" in h and "all good" in h
    # Display id, recommendation derived
    assert "#42" in h
    assert "ready for sign-off" in h.lower()
    assert "derived from verdicts" in h
    # Reachable context: description, PR notes, plan notes
    assert "desc line one" in h
    assert "handoff one" in h and "handoff two" in h
    assert "watcher continuity" in h


def test_per_pr_report_evidence_inline_and_relative(tmp_path):
    cap = _seed_captures(tmp_path)
    rd = br.gather_pr_report_data(_data(), "pr-aaa", cap)
    h = br.render_pr_report_html(rd)

    # webm → <video> with relative src; png → <img>; txt inlined
    assert '<video controls' in h
    assert 'src="scenarios/1/rec.webm"' in h
    assert '<img' in h and 'scenarios/1/shot.png' in h
    assert "hello log" in h
    # No absolute paths leaked into links
    assert str(tmp_path) not in h


def test_html_escaping(tmp_path):
    data = _data()
    data["prs"][0]["description"] = "<script>alert(1)</script>"
    data["prs"][0]["title"] = "<b>bad</b>"
    cap = tmp_path / "pr-aaa"
    cap.mkdir()
    rd = br.gather_pr_report_data(data, "pr-aaa", cap)
    h = br.render_pr_report_html(rd)
    assert "<script>alert" not in h
    assert "&lt;script&gt;" in h
    assert "<b>bad</b>" not in h


def test_legacy_verdict_md_fallback(tmp_path):
    cap = tmp_path / "pr-aaa"
    sc = cap / "scenarios" / "2"
    sc.mkdir(parents=True)
    (sc / "verdict.md").write_text(
        "# Scenario 2: Logout\n\nNEEDS_WORK\n\nbutton missing")
    rd = br.gather_pr_report_data(_data(), "pr-aaa", cap)
    assert len(rd.behaviors) == 1
    b = rd.behaviors[0]
    assert b.title == "Logout"
    assert b.verdict == "NEEDS_WORK"
    assert "button missing" in b.reason
    h = br.render_pr_report_html(rd)
    assert "Steps not recorded" in h  # steps unavailable in legacy format


def test_no_captures_still_renders(tmp_path):
    cap = tmp_path / "pr-bbb"  # never created
    rd = br.gather_pr_report_data(_data(), "pr-bbb", cap)
    h = br.render_pr_report_html(rd)
    assert "No recorded behaviors yet" in h
    # Recommendation routes to qa when nothing recorded
    assert rd.next_hop == "qa"


def test_signoff_json_overrides_derived(tmp_path):
    cap = _seed_captures(tmp_path)
    (cap / "signoff.json").write_text(json.dumps({
        "recommendation": "Router says merge.",
        "next_hop": "merge",
        "summary": "comprehensive review complete"}))
    rd = br.gather_pr_report_data(_data(), "pr-aaa", cap)
    assert rd.recommendation_source == "router"
    assert rd.recommendation == "Router says merge."
    assert rd.summary == "comprehensive review complete"
    h = br.render_pr_report_html(rd)
    assert "Router says merge." in h
    assert "derived from verdicts" not in h


def test_impl_evidence_section(tmp_path):
    cap = _seed_captures(tmp_path)
    impl = cap / "impl"
    impl.mkdir()
    (impl / "prefix.txt").write_text("repro before fix")
    rd = br.gather_pr_report_data(_data(), "pr-aaa", cap)
    assert any("prefix.txt" in e.name for e in rd.impl_evidence)
    h = br.render_pr_report_html(rd)
    assert "Implementation evidence" in h
    assert "repro before fix" in h


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_detect_missing_and_links(tmp_path):
    _seed_captures(tmp_path)
    (tmp_path / "pr-aaa" / "report.html").write_text("x")  # report exists
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)

    # Present report → live link
    assert 'href="pr-aaa/report.html"' in h
    # Missing report → no dead link, regenerate command surfaced
    assert "no report" in h
    assert "pm pr report pr-bbb" in h
    # Filtering controls + data attributes
    assert 'id="f-status"' in h and 'id="f-merged"' in h
    assert 'data-status="qa"' in h
    assert 'data-merged="1"' in h  # merged pr-ccc
    assert 'data-merged="0"' in h  # unmerged


def test_dashboard_groups_by_plan(tmp_path):
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert "Regression loop" in h     # plan group header
    assert "watcher continuity" in h  # plan notes shown
    assert "Unplanned" in h           # pr-ccc has no plan


def test_dashboard_summary_from_captures(tmp_path):
    _seed_captures(tmp_path)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert "1 PASS" in aaa.summary
    assert aaa.rec  # derived recommendation present


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_report_and_dashboard(tmp_path, monkeypatch):
    pm_root = tmp_path / "pm"
    pm_root.mkdir()
    caps = tmp_path / "captures"
    caps.mkdir()
    _seed_captures(caps)

    from pm_core import store
    store.save(_data(), pm_root)

    def fake_captures_dir(pr_id, session_tag=None, start_path=None):
        d = caps / pr_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def fake_captures_root(session_tag=None, start_path=None):
        return caps

    monkeypatch.setattr("pm_core.paths.captures_dir", fake_captures_dir)
    monkeypatch.setattr("pm_core.paths.captures_root", fake_captures_root)

    with patch("pm_core.cli.pr.state_root", return_value=pm_root):
        res = CliRunner().invoke(pr_report, ["pr-aaa"])
    assert res.exit_code == 0, res.output
    assert (caps / "pr-aaa" / "report.html").is_file()
    # Generating one report refreshes the dashboard
    assert (caps / "index.html").is_file()

    with patch("pm_core.cli.pr.state_root", return_value=pm_root):
        res = CliRunner().invoke(pr_dashboard, [])
    assert res.exit_code == 0, res.output
    assert (caps / "index.html").is_file()


def test_cli_report_all(tmp_path, monkeypatch):
    pm_root = tmp_path / "pm"
    pm_root.mkdir()
    caps = tmp_path / "captures"
    caps.mkdir()
    _seed_captures(caps)

    from pm_core import store
    store.save(_data(), pm_root)

    def fake_captures_dir(pr_id, session_tag=None, start_path=None):
        d = caps / pr_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    monkeypatch.setattr("pm_core.paths.captures_dir", fake_captures_dir)
    monkeypatch.setattr(
        "pm_core.paths.captures_root",
        lambda session_tag=None, start_path=None: caps)

    with patch("pm_core.cli.pr.state_root", return_value=pm_root):
        res = CliRunner().invoke(pr_report, ["--all"])
    assert res.exit_code == 0, res.output
    assert "Generated 3 report(s)." in res.output
    for pid in ("pr-aaa", "pr-bbb", "pr-ccc"):
        assert (caps / pid / "report.html").is_file()


def test_cli_report_unknown_pr(tmp_path, monkeypatch):
    pm_root = tmp_path / "pm"
    pm_root.mkdir()
    from pm_core import store
    store.save(_data(), pm_root)
    monkeypatch.setattr(
        "pm_core.paths.captures_root",
        lambda session_tag=None, start_path=None: tmp_path / "c")
    with patch("pm_core.cli.pr.state_root", return_value=pm_root):
        res = CliRunner().invoke(pr_report, ["pr-zzz"])
    assert res.exit_code != 0
    assert "not found" in res.output
