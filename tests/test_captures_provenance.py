"""Persisted QA evidence carries PR/run identity (pr-1ae1d2d).

A nested fake-Claude QA fixture inside an outer scenario container, or an
earlier implementation-verification run, used to be able to leave records in
the enclosing PR's ``captures/<pr>/scenarios/`` that were indistinguishable
from real QA coverage: ``scenario.json`` named no PR and no run, nothing
listed the scenarios the run owned, and orphan directories stayed in the
scenario namespace forever.

These tests pin the provenance contract: every orchestrator-written record
names its PR and QA run, each run publishes an authoritative manifest, and
the report / dashboard / merge gate bind to that run instead of trusting
"a directory exists".
"""

import json
from pathlib import Path
from unittest.mock import patch

from pm_core import behavior_report as br
from pm_core import captures, signoff


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _root(tmp_path: Path) -> Path:
    r = tmp_path / "cap"
    r.mkdir()
    return r


def _scenario_dir(root: Path, index: int, record: dict | None = None) -> Path:
    d = root / "scenarios" / str(index)
    d.mkdir(parents=True, exist_ok=True)
    (d / "verdict.md").write_text(f"# Scenario {index}\n", encoding="utf-8")
    if record is not None:
        (d / "scenario.json").write_text(json.dumps(record), encoding="utf-8")
    return d


def _status_file(tmp_path: Path, run_id: str, indices=(1,)) -> Path:
    p = tmp_path / "qa_status.json"
    p.write_text(json.dumps({
        "pr_id": "pr-x",
        "run_id": run_id,
        "overall": "PASS",
        "scenarios": [{"index": i, "title": f"t{i}", "verdict": "PASS"}
                      for i in indices],
    }), encoding="utf-8")
    return p


def _report(root: Path, pr_id: str, verdict: str | None = None,
            qa_run: str | None = None) -> Path:
    metas = ""
    if verdict:
        metas += f'<meta name="pm-signoff-verdict" content="{verdict}">'
    if qa_run:
        metas += f'<meta name="pm-signoff-qa-run" content="{qa_run}">'
    d = root / pr_id
    d.mkdir(parents=True, exist_ok=True)
    out = d / "report.html"
    out.write_text(
        f'<!DOCTYPE html><html><head>{metas}<title>r</title></head>'
        '<body>r</body></html>', encoding="utf-8")
    return out


def _dash_data():
    return {"prs": [{"id": "pr-aaa", "title": "T", "status": "sign_off"}]}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

def test_manifest_round_trip(tmp_path):
    root = _root(tmp_path)
    p = captures.write_manifest(
        root, pr_id="pr-x", run_id="run1",
        scenarios=[{"index": 1, "title": "one", "verdict": "PASS"}],
        overall="PASS")
    assert p == root / captures.MANIFEST_NAME
    m = captures.read_manifest(root, pr_id="pr-x")
    assert m["pr_id"] == "pr-x"
    assert m["run_id"] == "run1"
    assert m["overall"] == "PASS"
    assert m["scenarios"][0]["index"] == 1
    assert m["started_at"] and m["updated_at"]
    # Atomic write leaves no temp file behind.
    assert not list(root.glob("*.tmp"))


def test_manifest_for_another_pr_is_ignored(tmp_path):
    """A nested fixture can write a manifest into the wrong tree; readers
    validate the owner instead of trusting the filename."""
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-other", run_id="runZ", scenarios=[])
    assert captures.read_manifest(root, pr_id="pr-x") is None


def test_manifest_survives_foreign_overwrite_of_the_root_pointer(tmp_path):
    """A nested fixture writing its own manifest into the enclosing PR's
    captures must not destroy the enclosing run's authoritative membership:
    every run keeps a per-run copy under ``qa_runs/``."""
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id="run1",
                            scenarios=[{"index": 1, "title": "one"}])
    # The fixture overwrites the current-run pointer with its own manifest.
    captures.write_manifest(root, pr_id="pr-other", run_id="runZ",
                            scenarios=[{"index": 1, "title": "Smoke"}])

    m = captures.read_manifest(root, pr_id="pr-x")
    assert m is not None
    assert m["run_id"] == "run1"
    assert [s["index"] for s in m["scenarios"]] == [1]
    # A foreign manifest is never returned for this PR — even when the
    # caller asks for that run by id, the PR's own record wins.
    assert captures.read_manifest(
        root, pr_id="pr-x", run_id="runZ")["run_id"] == "run1"


def test_manifest_prefers_the_root_pointer_when_it_is_ours(tmp_path):
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id="run1", scenarios=[])
    captures.write_manifest(root, pr_id="pr-x", run_id="run2", scenarios=[])
    m = captures.read_manifest(root, pr_id="pr-x")
    assert m["run_id"] == "run2"


def test_manifest_preserves_started_at_across_updates(tmp_path):
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id="run1", scenarios=[])
    first = captures.read_manifest(root, pr_id="pr-x")
    captures.write_manifest(root, pr_id="pr-x", run_id="run1",
                            scenarios=[{"index": 1, "title": "one"}],
                            overall="PASS")
    second = captures.read_manifest(root, pr_id="pr-x")
    assert second["started_at"] == first["started_at"]
    assert len(second["scenarios"]) == 1


def test_manifest_survives_unreadable_file(tmp_path):
    root = _root(tmp_path)
    (root / captures.MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    assert captures.read_manifest(root, pr_id="pr-x") is None


# ---------------------------------------------------------------------------
# Per-scenario record
# ---------------------------------------------------------------------------

def test_write_scenario_record_stamps_identity(tmp_path):
    root = _root(tmp_path)
    captures.write_scenario_record(
        root, 3, {"index": 3, "title": "three", "verdict": "PASS"},
        pr_id="pr-x", run_id="run1")
    rec = json.loads(
        (root / "scenarios" / "3" / "scenario.json").read_text(encoding="utf-8"))
    assert rec["pr_id"] == "pr-x"
    assert rec["run_id"] == "run1"
    assert rec["schema"] == captures.SCHEMA
    assert rec["captured_at"]
    # Existing keys the sign-off agent reads are preserved.
    assert rec["index"] == 3
    assert rec["title"] == "three"
    assert rec["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def test_audit_classifies_scenario_dirs(tmp_path):
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id="run1",
                            scenarios=[{"index": 1, "title": "one"}])
    _scenario_dir(root, 1, {"index": 1, "pr_id": "pr-x", "run_id": "run1"})
    _scenario_dir(root, 2, {"index": 2, "pr_id": "pr-x", "run_id": "run0"})
    _scenario_dir(root, 3, {"index": 3, "pr_id": "pr-other", "run_id": "runZ"})
    _scenario_dir(root, 4)  # legacy / pre-fix record, no identity

    a = captures.audit(root, pr_id="pr-x", run_id="run1")
    assert [m["index"] for m in a.members] == [1]
    assert a.dirs[1].state == "current"
    assert a.dirs[2].state == "prior-run"
    assert a.dirs[3].state == "foreign"
    assert a.dirs[4].state == "unowned"
    assert a.orphans == [2, 3, 4]
    assert any("foreign" in x for x in a.anomalies)
    assert any("unowned" in x for x in a.anomalies)
    assert any("prior QA run" in x for x in a.anomalies)


def test_audit_flags_a_current_run_dir_missing_from_the_manifest(tmp_path):
    """A directory stamped with this run but absent from the manifest is an
    inconsistency worth naming — the manifest is the membership."""
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id="run1", scenarios=[])
    _scenario_dir(root, 5, {"index": 5, "pr_id": "pr-x", "run_id": "run1"})
    a = captures.audit(root, pr_id="pr-x", run_id="run1")
    assert a.orphans == [5]
    assert any("not in the current run's manifest" in x for x in a.anomalies)


def test_audit_without_manifest_reports_unbound_membership(tmp_path):
    root = _root(tmp_path)
    _scenario_dir(root, 1)
    a = captures.audit(root, pr_id="pr-x", run_id="run1")
    assert a.manifest is None
    assert a.members == []
    assert any("no qa_manifest" in x for x in a.anomalies)


def test_audit_flags_missing_evidence_for_a_manifest_member(tmp_path):
    """A scenario the run owns but whose directory is gone (overwritten and
    quarantined, or never captured) is missing evidence — not silent absence."""
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id="run1",
                            scenarios=[{"index": 1, "title": "one"},
                                       {"index": 2, "title": "two"}])
    _scenario_dir(root, 2, {"index": 2, "pr_id": "pr-x", "run_id": "run1"})
    a = captures.audit(root, pr_id="pr-x", run_id="run1")
    assert any("scenarios/1" in x and "evidence is missing" in x
               for x in a.anomalies)


def test_audit_flags_manifest_run_mismatch(tmp_path):
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id="run1", scenarios=[])
    a = captures.audit(root, pr_id="pr-x", run_id="run2")
    assert a.manifest_run == "run1"
    assert any("run1" in x and "run2" in x for x in a.anomalies)


def test_audit_without_manifest_flags_run_stamped_records(tmp_path):
    """A record naming a run, with no manifest to bind it to a current run,
    is reported with the run it names — never silently treated as current."""
    root = _root(tmp_path)
    _scenario_dir(root, 1, {"index": 1, "pr_id": "pr-x", "run_id": "run9"})
    a = captures.audit(root, pr_id="pr-x", run_id="")
    assert a.dirs[1].state == "unowned"
    assert any("run9" in x for x in a.anomalies)


def test_audit_ignores_non_numeric_dirs(tmp_path):
    root = _root(tmp_path)
    (root / "scenarios" / captures.FOREIGN_DIR_NAME).mkdir(parents=True)
    a = captures.audit(root, pr_id="pr-x", run_id="run1")
    assert a.dirs == {}


# ---------------------------------------------------------------------------
# Quarantine
# ---------------------------------------------------------------------------

def test_quarantine_moves_only_foreign_records(tmp_path):
    root = _root(tmp_path)
    foreign = _scenario_dir(root, 3, {"index": 3, "pr_id": "pr-other"})
    prior = _scenario_dir(root, 2, {"index": 2, "pr_id": "pr-x",
                                    "run_id": "run0"})
    unowned = _scenario_dir(root, 4)

    moved = captures.quarantine_foreign(root, pr_id="pr-x", run_id="run1")

    assert [p.name for p in moved] == ["run1-3"]
    assert not foreign.exists()
    quarantined = root / "scenarios" / captures.FOREIGN_DIR_NAME / "run1-3"
    assert (quarantined / "verdict.md").is_file()
    # Same-PR history and legacy records are preserved in place.
    assert prior.is_dir()
    assert unowned.is_dir()


def test_quarantine_never_overwrites_an_existing_target(tmp_path):
    root = _root(tmp_path)
    (root / "scenarios" / captures.FOREIGN_DIR_NAME / "run1-3").mkdir(
        parents=True)
    _scenario_dir(root, 3, {"index": 3, "pr_id": "pr-other"})
    moved = captures.quarantine_foreign(root, pr_id="pr-x", run_id="run1")
    assert [p.name for p in moved] == ["run1-3-1"]


def test_quarantine_is_a_noop_without_foreign_records(tmp_path):
    root = _root(tmp_path)
    _scenario_dir(root, 1, {"index": 1, "pr_id": "pr-x", "run_id": "run1"})
    assert captures.quarantine_foreign(root, pr_id="pr-x", run_id="run1") == []


# ---------------------------------------------------------------------------
# QA loop writers
# ---------------------------------------------------------------------------

def test_persist_scenario_verdicts_stamps_pr_and_run(tmp_path, monkeypatch):
    from pm_core import paths, qa_loop
    root = _root(tmp_path)
    monkeypatch.setattr(paths, "captures_dir",
                        lambda *a, **k: root)
    state = qa_loop.QALoopState(pr_id="pr-x")
    state.loop_id = "run1"
    state.scenarios = [qa_loop.QAScenario(index=2, title="two",
                                          focus="f", steps="s")]
    state.scenario_verdicts = {2: "PASS"}
    state.scenario_verdict_reasons = {2: "looks good"}

    qa_loop._persist_scenario_verdicts(state, "")

    rec = json.loads(
        (root / "scenarios" / "2" / "scenario.json").read_text(encoding="utf-8"))
    assert rec["pr_id"] == "pr-x"
    assert rec["run_id"] == "run1"
    assert rec["verdict"] == "PASS"
    assert rec["reason"] == "looks good"
    assert (root / "scenarios" / "2" / "verdict.md").is_file()
    m = captures.read_manifest(root, pr_id="pr-x")
    assert m["run_id"] == "run1"
    assert [s["index"] for s in m["scenarios"]] == [2]
    assert m["scenarios"][0]["verdict"] == "PASS"


def test_status_file_carries_run_id(tmp_path):
    from pm_core import qa_loop
    p = tmp_path / "qa_status.json"
    qa_loop._write_status_file(p, "pr-x", [], {}, run_id="run1")
    assert json.loads(p.read_text())["run_id"] == "run1"


def test_status_file_omits_run_id_when_unknown(tmp_path):
    """Legacy callers pass no run id; the file keeps its old shape."""
    from pm_core import qa_loop
    p = tmp_path / "qa_status.json"
    qa_loop._write_status_file(p, "pr-x", [], {})
    assert "run_id" not in json.loads(p.read_text())


def _fixture_state(pr_id="pr-fixture", run_id="fixturerun"):
    from pm_core import qa_loop
    state = qa_loop.QALoopState(pr_id=pr_id)
    state.loop_id = run_id
    state.scenarios = [qa_loop.QAScenario(index=1, title="Smoke",
                                          focus="f", steps="s")]
    return state


def test_sync_never_quarantines_through_a_shared_mount(tmp_path, monkeypatch):
    """A nested pm project inside a scenario container resolves the enclosing
    PR's ``/pm-captures`` mount when ``PM_CAPTURES_PR`` is absent (a
    controller predating #264).  It must not move that PR's real evidence out
    of ``scenarios/`` — quarantine is a move, so it only runs on a tree that
    is provably ours."""
    from pm_core import paths, qa_loop
    mount = tmp_path / "pm-captures"
    mount.mkdir()
    captures.write_manifest(mount, pr_id="pr-outer", run_id="outerrun",
                            scenarios=[{"index": 1, "title": "one"}])
    _scenario_dir(mount, 1, {"index": 1, "pr_id": "pr-outer",
                             "run_id": "outerrun"})
    monkeypatch.setattr(paths, "CONTAINER_CAPTURES_MOUNT", str(mount))
    monkeypatch.delenv(paths.CAPTURES_PR_ENV, raising=False)
    monkeypatch.setattr(paths, "captures_dir", lambda *a, **k: mount)

    qa_loop._sync_captures_evidence(_fixture_state())

    assert (mount / "scenarios" / "1").is_dir()
    assert not (mount / "scenarios" / captures.FOREIGN_DIR_NAME).exists()
    # Publishing the fixture's manifest is recoverable: readers validate
    # ``pr_id`` and fall back to the per-run copy, so the enclosing PR's
    # membership is still bound to its own run.
    assert captures.read_manifest(mount, pr_id="pr-fixture")["run_id"] == "fixturerun"
    assert captures.read_manifest(mount, pr_id="pr-outer")["run_id"] == "outerrun"


def test_sync_quarantines_when_the_mount_belongs_to_this_pr(tmp_path,
                                                             monkeypatch):
    """The guard does not disable legitimate quarantine: a mount marked as
    ours is our captures tree, so foreign records there are moved."""
    from pm_core import paths, qa_loop
    mount = tmp_path / "pm-captures"
    mount.mkdir()
    _scenario_dir(mount, 3, {"index": 3, "pr_id": "pr-other",
                             "run_id": "otherrun"})
    monkeypatch.setattr(paths, "CONTAINER_CAPTURES_MOUNT", str(mount))
    monkeypatch.setenv(paths.CAPTURES_PR_ENV, "pr-fixture")
    monkeypatch.setattr(paths, "captures_dir", lambda *a, **k: mount)

    qa_loop._sync_captures_evidence(_fixture_state())

    assert not (mount / "scenarios" / "3").exists()
    assert (mount / "scenarios" / captures.FOREIGN_DIR_NAME / "fixturerun-3").is_dir()
    assert captures.read_manifest(mount, pr_id="pr-fixture")["run_id"] == "fixturerun"


# ---------------------------------------------------------------------------
# Sign-off prompt
# ---------------------------------------------------------------------------

def _prompt(tmp_path, monkeypatch, *, manifest_run="run1", status_run="run1"):
    from pm_core import paths, prompt_gen
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id=manifest_run,
                            scenarios=[{"index": 1, "title": "one",
                                        "verdict": "PASS"}])
    status = _status_file(tmp_path, status_run)
    monkeypatch.setattr(paths, "latest_qa_status_path", lambda pr_id: status)
    monkeypatch.setattr(paths, "captures_dir", lambda *a, **k: root)
    return root, prompt_gen


def test_signoff_qa_block_names_the_run_and_manifest(tmp_path, monkeypatch):
    _, prompt_gen = _prompt(tmp_path, monkeypatch)
    head, _listing = prompt_gen._signoff_qa_scenarios_parts("pr-x")
    assert "QA run: `run1`" in head
    assert "qa_manifest.json" in head


def test_signoff_qa_block_ignores_the_interactive_scenario(tmp_path,
                                                           monkeypatch):
    """Scenario 0 (the interactive window) stays in ``qa_status.json`` but is
    deliberately not a manifest member — comparing the two listings verbatim
    would warn about a membership disagreement on every normal run."""
    from pm_core import paths, prompt_gen
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id="run1",
                            scenarios=[{"index": 1, "title": "one"}])
    status = tmp_path / "qa_status.json"
    status.write_text(json.dumps({
        "pr_id": "pr-x", "run_id": "run1", "overall": "PASS",
        "scenarios": [{"index": 0, "title": "Interactive",
                       "verdict": "interactive"},
                      {"index": 1, "title": "one", "verdict": "PASS"}],
    }), encoding="utf-8")
    monkeypatch.setattr(paths, "latest_qa_status_path", lambda pr_id: status)
    monkeypatch.setattr(paths, "captures_dir", lambda *a, **k: root)
    head, _listing = prompt_gen._signoff_qa_scenarios_parts("pr-x")
    assert "QA run: `run1`" in head
    assert "disagree" not in head


def test_signoff_qa_block_warns_when_status_run_differs(tmp_path, monkeypatch):
    _, prompt_gen = _prompt(tmp_path, monkeypatch,
                            manifest_run="run1", status_run="run2")
    head, _listing = prompt_gen._signoff_qa_scenarios_parts("pr-x")
    assert "run1" in head and "run2" in head
    assert "Warning" in head


def test_signoff_qa_block_says_membership_unbound_without_manifest(
        tmp_path, monkeypatch):
    from pm_core import paths, prompt_gen
    status = _status_file(tmp_path, "run1")
    monkeypatch.setattr(paths, "latest_qa_status_path", lambda pr_id: status)
    monkeypatch.setattr(paths, "captures_dir", lambda *a, **k: None)
    head, _listing = prompt_gen._signoff_qa_scenarios_parts("pr-x")
    assert "not run-bound" in head


def test_signoff_prompt_requires_report_bound_to_the_qa_run(tmp_path,
                                                            monkeypatch):
    from pm_core import paths, prompt_gen
    monkeypatch.setattr(paths, "latest_qa_status_path", lambda pr_id: None)
    monkeypatch.setattr(paths, "captures_dir", lambda *a, **k: None)
    p = prompt_gen.generate_signoff_prompt(_dash_data(), "pr-aaa")
    flat = " ".join(p.split())
    assert "pm-signoff-qa-run" in flat
    assert "qa_manifest.json" in flat
    # The checklist tells the session to ignore directories outside the run.
    assert "must not be cited as coverage" in flat


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_flags_report_bound_to_another_run(tmp_path):
    captures.write_manifest(tmp_path / "pr-aaa", pr_id="pr-aaa",
                            run_id="run2", scenarios=[])
    _report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE, qa_run="run1")
    rows = br.gather_dashboard_rows(_dash_data(), tmp_path)
    row = next(r for r in rows if r.pr_id == "pr-aaa")
    assert row.qa_run == "run1"
    assert row.qa_run_stale is True
    assert "QA run changed" in br.render_dashboard_html(rows)


def test_dashboard_row_not_stale_when_run_matches(tmp_path):
    captures.write_manifest(tmp_path / "pr-aaa", pr_id="pr-aaa",
                            run_id="run1", scenarios=[])
    _report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE, qa_run="run1")
    rows = br.gather_dashboard_rows(_dash_data(), tmp_path)
    row = next(r for r in rows if r.pr_id == "pr-aaa")
    assert row.qa_run == "run1"
    assert row.qa_run_stale is False
    assert "QA run changed" not in br.render_dashboard_html(rows)


def test_dashboard_legacy_report_without_qa_run_is_not_flagged(tmp_path):
    _report(tmp_path, "pr-aaa", signoff.SIGNOFF_MERGE)
    rows = br.gather_dashboard_rows(_dash_data(), tmp_path)
    row = next(r for r in rows if r.pr_id == "pr-aaa")
    assert row.qa_run == ""
    assert row.qa_run_stale is False


# ---------------------------------------------------------------------------
# Merge gate
# ---------------------------------------------------------------------------

def _merge_ready_pr(tmp_path):
    return {
        "id": "pr-001", "title": "T", "status": "sign_off",
        "branch": "pm/pr-001", "workdir": str(tmp_path / "wd"),
        "signoff": {
            "verdict": signoff.SIGNOFF_MERGE, "sha": "HEAD-SHA",
            "ts": "now", "origin": "manual",
            "integration": {
                "target_repo": "r", "base_branch": "master",
                "base_sha": "b" * 40, "candidate_tree": "c" * 40,
                "status": "clean",
            },
        },
    }


def test_merge_gate_refuses_report_bound_to_another_run(tmp_path):
    croot = tmp_path / "caps"
    prdir = croot / "pr-001"
    prdir.mkdir(parents=True)
    captures.write_manifest(prdir, pr_id="pr-001", run_id="run2",
                            scenarios=[])
    _report(croot, "pr-001", signoff.SIGNOFF_MERGE, qa_run="run1")
    with patch("pm_core.paths.captures_root", return_value=croot):
        why = signoff.merge_gate_refusal(_merge_ready_pr(tmp_path),
                                         "HEAD-SHA", "master")
    assert why is not None
    assert "QA run" in why
    assert "run1" in why and "run2" in why


def test_merge_gate_allows_report_without_qa_run_tag(tmp_path):
    """Legacy reports carry no run binding; no new hard requirement."""
    croot = tmp_path / "caps"
    prdir = croot / "pr-001"
    prdir.mkdir(parents=True)
    captures.write_manifest(prdir, pr_id="pr-001", run_id="run2",
                            scenarios=[])
    _report(croot, "pr-001", signoff.SIGNOFF_MERGE)
    with patch("pm_core.paths.captures_root", return_value=croot):
        why = signoff.merge_gate_refusal(_merge_ready_pr(tmp_path),
                                         "HEAD-SHA", "master")
    assert why is None


def test_merge_gate_allows_matching_qa_run(tmp_path):
    croot = tmp_path / "caps"
    prdir = croot / "pr-001"
    prdir.mkdir(parents=True)
    captures.write_manifest(prdir, pr_id="pr-001", run_id="run1",
                            scenarios=[])
    _report(croot, "pr-001", signoff.SIGNOFF_MERGE, qa_run="run1")
    with patch("pm_core.paths.captures_root", return_value=croot):
        why = signoff.merge_gate_refusal(_merge_ready_pr(tmp_path),
                                         "HEAD-SHA", "master")
    assert why is None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_qa_evidence_lists_members_and_anomalies(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from pm_core.cli.qa import qa_evidence
    root = _root(tmp_path)
    captures.write_manifest(root, pr_id="pr-x", run_id="run1",
                            scenarios=[{"index": 1, "title": "one",
                                        "verdict": "PASS"}],
                            overall="PASS")
    _scenario_dir(root, 1, {"index": 1, "pr_id": "pr-x", "run_id": "run1"})
    _scenario_dir(root, 6, {"index": 6, "pr_id": "pr-other"})
    data = {"prs": [{"id": "pr-x", "title": "T", "status": "sign_off"}]}
    monkeypatch.setattr("pm_core.paths.captures_dir", lambda *a, **k: root)
    monkeypatch.setattr("pm_core.paths.latest_qa_status_path",
                        lambda pr_id: None)
    monkeypatch.setattr("pm_core.cli.helpers.state_root",
                        lambda: tmp_path)
    monkeypatch.setattr("pm_core.store.load", lambda root: data)
    res = CliRunner().invoke(qa_evidence, ["pr-x"])
    assert res.exit_code == 0, res.output
    assert "run1" in res.output
    assert "Scenario 1" in res.output
    assert "foreign" in res.output
