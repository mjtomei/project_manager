"""Tests for the all-PR behavior dashboard + the sign-off prompt extension
(pr-8e693f6).

Per-PR ``report.html`` is agent-written (via the sign-off prompt's report
deliverable), so we test the prompt content. The dashboard is the only
deterministic surface, and we test that it reads the ``report.json`` sidecar.
"""

import json
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
        "plans": [
            {"id": "plan-x", "name": "Regression loop", "status": "active",
             "notes": [{"text": "watcher continuity"}]},
        ],
        "prs": [
            {"id": "pr-aaa", "title": "Add thing", "status": "sign_off",
             "plan": "plan-x", "gh_pr_number": 42,
             "description": "desc"},
            {"id": "pr-bbb", "title": "No sidecar PR", "status": "pending",
             "plan": "plan-x"},
            {"id": "pr-ccc", "title": "Merged one", "status": "merged",
             "merged_at": "2026-01-01T00:00:00Z"},
        ],
    }


def _write_sidecar(root: Path, pr_id: str, **overrides) -> Path:
    """Write a report.json sidecar with only sign-off-derived keys; *overrides*
    tweak keys (and may inject state-shaped fields to verify they're ignored)."""
    payload = {
        "pr_id": pr_id,
        "verdict": signoff.SIGNOFF_MERGE,
        "next_hop": "ready_to_merge",
        "tally": {"PASS": 3, "NEEDS_WORK": 0, "INPUT_REQUIRED": 0,
                  "pending": 0},
        "bugs_fixed_in_loop": 2,
        "spec_clarifications": 1,
        "generated_at": "2026-05-26T12:00:00Z",
        "report_html": "report.html",
    }
    payload.update(overrides)
    pdir = root / pr_id
    pdir.mkdir(parents=True, exist_ok=True)
    sidecar = pdir / "report.json"
    sidecar.write_text(json.dumps(payload, indent=2))
    return sidecar


# ---------------------------------------------------------------------------
# Sidecar reading
# ---------------------------------------------------------------------------

def test_sidecar_drives_dashboard_row(tmp_path):
    _write_sidecar(tmp_path, "pr-aaa")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.has_sidecar
    assert aaa.verdict == signoff.SIGNOFF_MERGE
    assert aaa.next_hop == "ready_to_merge"
    assert aaa.tally == {"PASS": 3, "NEEDS_WORK": 0,
                         "INPUT_REQUIRED": 0, "pending": 0}
    assert aaa.bugs_fixed_in_loop == 2
    assert aaa.spec_clarifications == 1
    assert aaa.report_html_rel == "pr-aaa/report.html"


def test_missing_sidecar_row_still_appears(tmp_path):
    """A PR without a sidecar still shows up — with an empty state."""
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    bbb = next(r for r in rows if r.pr_id == "pr-bbb")
    assert bbb.has_sidecar is False
    assert bbb.report_html_rel is None
    assert bbb.tally == {}
    assert bbb.verdict == ""


def test_unreadable_sidecar_falls_back(tmp_path):
    """Garbage in report.json falls back to the empty-state row."""
    (tmp_path / "pr-aaa").mkdir()
    (tmp_path / "pr-aaa" / "report.json").write_text("{not json")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.has_sidecar is False


def test_partial_sidecar_renders(tmp_path):
    """A sidecar missing optional keys still produces a row (no crash)."""
    (tmp_path / "pr-aaa").mkdir()
    (tmp_path / "pr-aaa" / "report.json").write_text(json.dumps({
        "pr_id": "pr-aaa"}))
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.has_sidecar
    assert aaa.tally == {"PASS": 0, "NEEDS_WORK": 0,
                         "INPUT_REQUIRED": 0, "pending": 0}
    assert aaa.bugs_fixed_in_loop == 0


# ---------------------------------------------------------------------------
# Sidecar contract: sign-off-derived ONLY (note-c3932ca)
# ---------------------------------------------------------------------------

def test_sidecar_absent_row_has_no_verdict(tmp_path):
    """pr['signoff'] is NOT a fallback for the dashboard verdict.

    The dashboard renders sidecar-only — when no report.json is present, the
    row's verdict stays empty even if the PR carries a recorded sign-off
    verdict in project.yaml. (pm pr list / the TUI tree still surface it; the
    dashboard intentionally diverges.)
    """
    data = _data()
    for pr in data["prs"]:
        if pr["id"] == "pr-aaa":
            pr["signoff"] = {"verdict": signoff.SIGNOFF_IMPL,
                             "sha": "deadbeef", "ts": "2026-05-26T00:00:00Z",
                             "origin": "manual"}
    rows = br.gather_dashboard_rows(data, tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.has_sidecar is False
    assert aaa.verdict == ""


def test_pr_state_read_from_project_yaml_not_sidecar(tmp_path):
    """State-shaped fields in the sidecar are ignored — project.yaml wins.

    Locks in the rule that the sidecar carries only sign-off-derived content:
    title / status / merged / display_id come from project.yaml every time
    the dashboard is generated, so a stale sidecar can't lie about them.
    """
    _write_sidecar(tmp_path, "pr-aaa",
                   title="STALE TITLE FROM SIDECAR",
                   status="STALE_STATUS",
                   merged=True,
                   display_id="#999")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    # project.yaml values (from _data()) win:
    assert aaa.title == "Add thing"
    assert aaa.status == "sign_off"
    assert aaa.merged is False           # no merged_at in _data()
    assert aaa.display_id == "#42"       # from gh_pr_number


def test_sidecar_verdict_wins_over_pr_signoff(tmp_path):
    """Sidecar verdict is authoritative; pr['signoff'] is never consulted."""
    data = _data()
    for pr in data["prs"]:
        if pr["id"] == "pr-aaa":
            pr["signoff"] = {"verdict": signoff.SIGNOFF_IMPL,
                             "sha": "deadbeef", "ts": "2026-05-26T00:00:00Z",
                             "origin": "manual"}
    _write_sidecar(tmp_path, "pr-aaa", verdict=signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(data, tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    assert aaa.verdict == signoff.SIGNOFF_MERGE


# ---------------------------------------------------------------------------
# Dashboard rendering
# ---------------------------------------------------------------------------

def test_dashboard_links_to_agent_written_report(tmp_path):
    _write_sidecar(tmp_path, "pr-aaa")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    # Live link to the agent's report.html for the PR with a sidecar
    assert 'href="pr-aaa/report.html"' in h
    # And the next-hop framing from the sidecar
    assert "next: ready_to_merge" in h


def test_dashboard_missing_state_uses_pm_pr_signoff(tmp_path):
    """Detect-missing rows surface `pm pr signoff <id>`, not the old report cmd."""
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert "no report yet" in h
    assert "pm pr signoff pr-bbb" in h
    # The retired `pm pr report` command must not be advertised anywhere.
    assert "pm pr report" not in h


def test_dashboard_reuses_signoff_icons_and_status_icons(tmp_path):
    """Verdict + status markers match signoff.py and helpers.PR_STATUS_ICONS."""
    from pm_core.cli.helpers import PR_STATUS_ICONS
    _write_sidecar(tmp_path, "pr-aaa")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert PR_STATUS_ICONS["sign_off"] in h
    assert signoff.SIGNOFF_VERDICT_ICONS[signoff.SIGNOFF_MERGE] in h


def test_dashboard_loop_badges_from_sidecar(tmp_path):
    """bugs_fixed_in_loop / spec_clarifications surface as badges."""
    _write_sidecar(tmp_path, "pr-aaa", bugs_fixed_in_loop=3,
                   spec_clarifications=2)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert "3 fixed" in h
    assert "2 clarified" in h


def test_dashboard_loop_badges_hidden_when_zero(tmp_path):
    _write_sidecar(tmp_path, "pr-aaa", bugs_fixed_in_loop=0,
                   spec_clarifications=0)
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert "fixed" not in h or "🐞" not in h
    assert "clarified" not in h


def test_dashboard_filters_and_groups_by_plan(tmp_path):
    _write_sidecar(tmp_path, "pr-aaa")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    h = br.render_dashboard_html(_data(), rows)
    assert 'id="f-status"' in h and 'id="f-merged"' in h
    assert 'data-status="sign_off"' in h
    assert 'data-merged="1"' in h and 'data-merged="0"' in h
    # Plan grouping + plan notes pass-through
    assert "Regression loop" in h
    assert "watcher continuity" in h
    assert "Unplanned" in h


def test_dashboard_never_interprets_captures(tmp_path):
    """Captures dir contents must NOT affect the dashboard — only the sidecar."""
    pdir = tmp_path / "pr-aaa"
    sc = pdir / "scenarios" / "1"
    sc.mkdir(parents=True)
    (sc / "verdict.md").write_text("# Scenario 1: x\n\nPASS\n")
    (sc / "rec.webm").write_bytes(b"\x00")
    rows = br.gather_dashboard_rows(_data(), tmp_path)
    aaa = next(r for r in rows if r.pr_id == "pr-aaa")
    # No sidecar => empty state, even though captures exist
    assert aaa.has_sidecar is False
    assert aaa.tally == {}


# ---------------------------------------------------------------------------
# Sign-off prompt extension — the per-PR report's actual producer
# ---------------------------------------------------------------------------

def test_signoff_prompt_includes_report_deliverable(tmp_path):
    """The extended prompt instructs the agent to write report.html + json."""
    from pm_core import prompt_gen
    data = _data()
    # The prompt builder reads PR fields and the plan — minimal seed is fine.
    p = prompt_gen.generate_signoff_prompt(
        data, "pr-aaa", session_name="pm-test", origin="manual")
    # Both deliverables explicitly required
    assert "report.html" in p and "report.json" in p
    # Top-of-page summary section
    assert "Bugs fixed by review and QA" in p
    assert "Spec ambiguities resolved" in p
    # Sidecar schema keys called out
    for key in ("bugs_fixed_in_loop", "spec_clarifications",
                "tally", "next_hop", "report_html", "generated_at"):
        assert key in p, f"sidecar key missing from prompt: {key}"
    # Audience guidance for the bulleted summary
    assert "UNFAMILIAR" in p
    # Reuses #225's single sources for icons/styles
    assert "SIGNOFF_VERDICT_ICONS" in p


def test_signoff_prompt_keeps_route_step_numbered_last():
    """Adding the report step must not duplicate the routing step number."""
    from pm_core import prompt_gen
    p = prompt_gen.generate_signoff_prompt(
        _data(), "pr-aaa", session_name="pm-test", origin="manual")
    # New ordering: 5. report, 6. record verdict, 7. route
    assert "5. **Write the sign-off report" in p
    assert "6. **Record your verdict" in p
    assert "7. **Route" in p


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_dashboard_generates_index(tmp_path, monkeypatch):
    pm_root = tmp_path / "pm"
    pm_root.mkdir()
    caps = tmp_path / "captures"
    caps.mkdir()
    _write_sidecar(caps, "pr-aaa")

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
    assert "pm pr signoff pr-bbb" in out  # missing-state regenerate cmd


def test_pr_report_command_is_removed():
    """The retired `pm pr report` command must not be registered anymore."""
    import pm_core.cli.pr as pr_cli
    assert not hasattr(pr_cli, "pr_report")
