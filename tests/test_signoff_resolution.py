"""Metadata-only integration conflicts are resolved at sign-off (pr-5cee3d5).

Real git repositories + real project.yaml throughout.  PR #250's trigger —
master and a feature branch independently appending records — must resolve by
stable record id, keep every record, allow the unaffected review/QA evidence
to be reused explicitly, and still require a fresh sign-off report tied to
the exact resolved candidate.  Real field, deletion/edit and ambiguity
conflicts are never silently resolved, and the merge step only publishes the
approved candidate.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pm_core import integration, prompt_gen, signoff, store
from pm_core.cli import pr as pr_mod
from pm_core.signoff import (SIGNOFF_BLOCKED, SIGNOFF_IMPL, SIGNOFF_MERGE,
                             SIGNOFF_REVIEW)

PR = "pr-200"
BRANCH = "pm/pr-200"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["/usr/bin/git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(cwd: Path, name: str, text: str, msg: str) -> str:
    (cwd / name).write_text(text)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


def project_doc(repo: Path, prs: list[dict] | None = None) -> dict:
    return {
        "project": {"name": "p", "repo": str(repo), "base_branch": "master",
                    "backend": "local"},
        "prs": prs if prs is not None else [
            {"id": "pr-100", "title": "Base one", "branch": "pm/base",
             "status": "merged"},
            {"id": PR, "title": "Feature", "branch": BRANCH,
             "status": "sign_off"},
        ],
        "plans": [],
    }


def append_records(pm_dir: Path, repo: Path, ids: list[str],
                   status: str = "pending") -> None:
    data = store.load(pm_dir)
    for rec_id in ids:
        data["prs"].append({"id": rec_id, "title": f"Record {rec_id}",
                            "branch": f"pm/{rec_id}", "status": status})
    store.save(data, pm_dir)


def pr_ids(pm_dir: Path) -> list[str]:
    return [p["id"] for p in store.load(pm_dir)["prs"]]


@pytest.fixture
def w(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}.items():
        monkeypatch.setenv(k, v)
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    base_pm = repo / "pm"
    base_pm.mkdir()
    store.save(project_doc(repo), base_pm)
    (repo / "keep.txt").write_text("keep\n")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")

    wd = tmp_path / "home" / ".pm" / "workdirs" / "proj" / PR
    git(tmp_path, "clone", "-q", str(repo), str(wd))
    git(wd, "checkout", "-q", "-b", BRANCH)
    head = commit(wd, "feature.txt", "feature\n", "feature")

    state = tmp_path / "state"
    state.mkdir()
    store.save(project_doc(repo, prs=[
        {"id": PR, "title": "Feature", "branch": BRANCH,
         "status": "sign_off", "workdir": str(wd)},
    ]), state)
    croot = tmp_path / "captures"
    tdir = tmp_path / "tdir"
    tdir.mkdir()
    with patch("pm_core.paths.captures_root", return_value=croot):
        yield SimpleNamespace(repo=repo, wd=wd, pm_dir=state, head=head,
                              croot=croot, tdir=tdir, tmp=tmp_path,
                              base_pm=base_pm)


def pr_entry(w) -> dict:
    return store.get_pr(store.load(w.pm_dir), PR)


def write_report(w, rec: dict, verdict: str = SIGNOFF_MERGE, *,
                 candidate: bool = True, evidence: bool = True,
                 reason: bool = True, head: str | None = None,
                 base: str | None = None) -> None:
    (w.croot / PR).mkdir(parents=True, exist_ok=True)
    extra = ""
    if candidate:
        extra += (f'<meta name="pm-signoff-candidate" '
                  f'content="{rec.get("candidate_tree") or ""}">')
    if evidence:
        extra += ('<meta name="pm-signoff-evidence" '
                  'content="review@aaaaaaa,qa@bbbbbbb">')
    if reason:
        extra += ('<meta name="pm-signoff-evidence-reason" '
                  'content="only independent project.yaml records changed">')
    (w.croot / PR / "report.html").write_text(
        f'<html><head><meta name="pm-signoff-verdict" content="{verdict}">'
        f'<meta name="pm-signoff-head" content="{head or rec.get("head")}">'
        f'<meta name="pm-signoff-base" content="{base or rec.get("base_sha")}">'
        f'{extra}</head><body/></html>')


def record_merge(w, rec: dict) -> None:
    write_report(w, rec)
    signoff.record_signoff_verdict(
        w.pm_dir, PR, SIGNOFF_MERGE, rec["head"], "manual",
        integration=integration.binding(rec))


def merge(w, *extra):
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"), \
         patch.object(pr_mod, "trigger_tui_restart"), \
         patch.object(pr_mod, "_launch_merge_window") as launch, \
         patch.object(pr_mod, "_finalize_merge") as finalize:
        result = CliRunner().invoke(pr_mod.pr, ["merge", *extra, PR])
    return result, launch.call_args_list, finalize.called


# --- resolver unit coverage -------------------------------------------------

BASE_YAML = """project:
  name: p
prs:
- id: pr-100
  title: Base one
  status: merged
- id: pr-200
  title: Feature
  status: sign_off
"""


def resolve(ours_extra: str = "", theirs_extra: str = ""):
    ours = BASE_YAML.rstrip() + ours_extra
    theirs = BASE_YAML.rstrip() + theirs_extra
    return integration.resolve_project_yaml(BASE_YAML, ours, theirs)


def test_independent_additions_from_both_sides_survive():
    merged, details = resolve(
        "\n- id: pr-300\n  title: Feat\n  status: pending\n",
        "\n- id: pr-250\n  title: Base\n  status: merged\n")
    assert merged is not None, details
    assert "pr-250" in merged and "pr-300" in merged
    actions = details["actions"]["prs"]
    assert actions["added"]["PR branch"] == ["pr-300"]
    assert actions["added"]["new base"] == ["pr-250"]


def test_same_record_field_conflict_is_refused():
    ours = BASE_YAML.replace("status: sign_off", "status: qa")
    theirs = BASE_YAML.replace("status: sign_off", "status: merged")
    merged, details = integration.resolve_project_yaml(
        BASE_YAML, ours, theirs)
    assert merged is None
    assert any("pr-200].status" in c for c in details["conflicts"])


def test_deletion_vs_edit_is_refused():
    ours = BASE_YAML.replace(
        "- id: pr-200\n  title: Feature\n  status: sign_off\n", "")
    theirs = BASE_YAML.replace("status: sign_off", "status: qa")
    merged, details = integration.resolve_project_yaml(
        BASE_YAML, ours, theirs)
    assert merged is None
    assert any("deleted on the PR branch" in c for c in details["conflicts"])


def test_same_id_added_differently_on_both_sides_is_ambiguous():
    merged, details = resolve(
        "\n- id: pr-900\n  title: One\n  status: pending\n",
        "\n- id: pr-900\n  title: Two\n  status: pending\n")
    assert merged is None
    assert any("added on both sides" in c for c in details["conflicts"])


def test_duplicate_ids_are_ambiguous():
    ours = BASE_YAML.rstrip() + "\n- id: pr-100\n  title: dup\n"
    merged, details = integration.resolve_project_yaml(BASE_YAML, ours,
                                                       BASE_YAML)
    assert merged is None
    assert any("duplicate record id" in c for c in details["conflicts"])


def test_non_string_record_id_is_a_conflict_not_a_crash():
    """A malformed id must fail the resolution, not raise out of it."""
    base = "project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
    ours = base + "- id: [1]\n  status: pending\n"
    theirs = base + "- id: pr-2\n  status: pending\n"
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert details.get("conflicts") or details.get("error")


def test_non_id_list_changed_on_both_sides_is_a_conflict():
    base = "project:\n  name: p\nprs:\n- id: pr-1\n  depends_on: []\n"
    ours = base.replace("depends_on: []", "depends_on: [pr-a]")
    theirs = base.replace("depends_on: []", "depends_on: [pr-b]")
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("changed differently" in c for c in details["conflicts"])


def test_one_sided_reorder_is_preserved():
    base = ("project:\n  name: p\nprs:\n"
            "- id: pr-1\n  status: pending\n"
            "- id: pr-2\n  status: pending\n")
    ours = ("project:\n  name: p\nprs:\n"
            "- id: pr-2\n  status: pending\n"
            "- id: pr-1\n  status: pending\n")
    merged, details = integration.resolve_project_yaml(base, ours, base)
    assert merged is not None, details
    assert merged.index("id: pr-2") < merged.index("id: pr-1")


def test_resolved_text_uses_pm_writer_and_reparses():
    merged, _ = resolve("\n- id: pr-300\n  title: Feat\n  status: pending\n")
    assert merged.startswith(store._YAML_HEADER)
    data = __import__("yaml").safe_load(merged)
    assert [p["id"] for p in data["prs"]] == ["pr-100", "pr-200", "pr-300"]


# --- #250 end-to-end -------------------------------------------------------

def _metadata_conflict(w, *, branch_ids=("pr-300", "pr-301"),
                       base_ids=("pr-250", "pr-251")) -> dict:
    append_records(w.wd / "pm", w.repo, list(branch_ids))
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    original_head = git(w.wd, "rev-parse", "HEAD")
    append_records(w.base_pm, w.repo, list(base_ids), status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    rec = integration.prepare(w.pm_dir, PR)
    rec["_original_head"] = original_head
    return rec


def test_250_metadata_conflict_resolves_and_all_records_survive(w):
    rec = _metadata_conflict(w)
    original_head = rec["_original_head"]

    assert rec["status"] == integration.UP_TO_DATE, rec
    resolution = rec["resolution"]
    assert resolution["applied_merge_sha"]
    assert resolution["resolved_from"]["head"] == original_head
    entry = resolution["paths"][0]
    assert entry["path"] == "pm/project.yaml"
    assert entry["added_ours"] == ["pr-300", "pr-301"]
    assert entry["added_theirs"] == ["pr-250", "pr-251"]
    # The branch now carries the resolved merge, and its tree is the
    # approved candidate exactly.
    assert git(w.wd, "rev-parse", "HEAD") == resolution["applied_merge_sha"]
    assert git(w.wd, "rev-parse", "HEAD^{tree}") == rec["candidate_tree"]
    assert sorted(pr_ids(w.wd / "pm")) == [
        "pr-100", PR, "pr-250", "pr-251", "pr-300", "pr-301"]
    # The isolated delta is inspectable.
    diff_path = Path(resolution["diff_path"])
    assert diff_path.is_file()
    assert "resolved" in diff_path.read_text()

    # QA evidence revision is captured from the QA run's resume snapshot.
    qa_dir = w.tmp / "home" / ".pm" / "workdirs" / "qa" / f"{PR}-abcd"
    qa_dir.mkdir(parents=True)
    (qa_dir / "qa_status.json").write_text(json.dumps(
        {"pr_id": PR, "overall": "PASS", "scenarios": []}))
    (qa_dir / "qa_resume.json").write_text(json.dumps(
        {"planner_head": original_head, "planner_code_changes": []}))

    # A fresh sign-off is still required: no approval -> merge refused.
    refusal = signoff.merge_gate_refusal(pr_entry(w), rec["head"], "master")
    assert refusal and "no sign-off verdict" in refusal
    result, _, finalized = merge(w)
    assert result.exit_code != 0 and not finalized

    # Approval without the explicit candidate/evidence statement is refused.
    write_report(w, rec, candidate=False)
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(pr_mod.pr, ["signoff", "record", PR])
    assert r.exit_code != 0 and "pm-signoff-candidate" in r.output

    record_merge(w, rec)
    p = pr_entry(w)
    assert p["signoff"]["integration"]["resolution_digest"] == \
        rec["resolution_digest"]
    evidence = p["signoff"]["evidence"]
    assert evidence["resolved_from"]["head"] == original_head
    assert evidence["qa"]["planner_head"] == original_head
    # QA recorded no code changes, so review saw the same revision.
    assert evidence["review"]["sha"] == original_head
    assert "qa@bbbbbbb" in evidence["reused"]
    assert evidence["reason"]
    assert evidence["required_return_stage"] == "merge"
    assert signoff.merge_gate_refusal(p, rec["head"], "master") is None

    result, windows, finalized = merge(w)
    assert result.exit_code == 0, result.output
    assert finalized and windows == []
    tip = git(w.repo, "rev-parse", "master")
    assert git(w.repo, "rev-parse", "master^{tree}") == rec["candidate_tree"]
    parents = git(w.repo, "rev-list", "--parents", "-n1", tip).split()[1:]
    assert parents == [rec["base_sha"], rec["head"]]
    assert sorted(pr_ids(w.repo / "pm")) == [
        "pr-100", PR, "pr-250", "pr-251", "pr-300", "pr-301"]
    # The PR workdir was not rewritten by the merge step.
    assert git(w.wd, "rev-parse", "HEAD") == rec["head"]


def test_same_field_conflict_routes_to_impl_and_changes_nothing(w):
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    data = store.load(w.wd / "pm")
    store.get_pr(data, PR)["status"] = "qa"
    store.save(data, w.wd / "pm")
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature edits status")
    head = git(w.wd, "rev-parse", "HEAD")

    data = store.load(w.base_pm)
    store.get_pr(data, PR)["status"] = "merged"
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base edits status")

    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CONFLICT
    assert rec["resolution"]["unresolved"]
    assert any("status" in c for c in rec["resolution"]["unresolved"][0]["conflicts"])
    assert git(w.wd, "rev-parse", "HEAD") == head      # untouched
    verdict, why = signoff.effective_verdict(
        SIGNOFF_MERGE, pr_entry(w)["integration"], head)
    assert verdict == SIGNOFF_IMPL and "conflicts" in why


def test_deletion_vs_edit_is_not_resolved(w):
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    data = store.load(w.base_pm)
    data["prs"] = [p for p in data["prs"] if p["id"] != PR]
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base deletes PR")

    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CONFLICT
    assert any("deleted" in c for c in
               rec["resolution"]["unresolved"][0]["conflicts"])


def test_code_conflict_is_never_auto_resolved(w):
    commit(w.wd, "shared.txt", "pr\n", "pr edits shared")
    commit(w.repo, "shared.txt", "base\nmore\n", "base edits shared")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CONFLICT
    assert rec["resolution"] is None
    assert "shared.txt" in rec["conflicts"]


def test_clean_base_behavior_change_requires_justification(w):
    data = store.load(w.base_pm)
    data["project"]["model_config"] = {
        "session_models": {"impl": "model-new"}}
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base changes model")

    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    assert any("model_config" in c for c in rec["base_behavior_changes"])
    head = rec["head"]

    # A report without the reuse/checks statement is not an approval.
    write_report(w, rec, evidence=False)
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(pr_mod.pr, ["signoff", "record", PR])
    assert r.exit_code != 0 and "pm-signoff-evidence" in r.output

    write_report(w, rec)
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(pr_mod.pr, ["signoff", "record", PR])
    assert r.exit_code == 0, r.output
    assert signoff.merge_gate_refusal(pr_entry(w), head, "master") is None


def test_behavioral_changes_are_focused_on_this_pr_and_its_dependencies(w):
    data = store.load(w.base_pm)
    data["prs"].append({"id": "pr-999", "title": "Other", "status": "merged"})
    store.get_pr(data, "pr-100")["status"] = "merged"
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base merges unrelated work")

    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    # Unrelated PR churn is not this PR's behavioural change.
    assert rec["base_behavior_changes"] == []

    def _dep(d):
        store.get_pr(d, PR)["depends_on"] = ["pr-100"]
    store.locked_update(w.pm_dir, _dep)
    data = store.load(w.base_pm)
    store.get_pr(data, "pr-100")["status"] = "closed"
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "dependency changes status")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    assert any("pr-100.status" in c for c in rec["base_behavior_changes"])


def test_resolved_approval_is_invalidated_when_the_base_moves(w):
    rec = _metadata_conflict(w)
    record_merge(w, rec)
    commit(w.repo, "late.txt", "late\n", "base moves after sign-off")

    result, _, finalized = merge(w)
    assert result.exit_code != 0
    assert "moved since sign-off" in result.output
    assert not finalized
    assert pr_entry(w)["signoff"]["invalidated"]


def test_resolved_approval_is_refused_when_the_recorded_candidate_changed(w):
    rec = _metadata_conflict(w)
    record_merge(w, rec)

    def _tamper(d):
        store.get_pr(d, PR)["integration"]["candidate_tree"] = "0" * 40
    store.locked_update(w.pm_dir, _tamper)
    refusal = signoff.merge_gate_refusal(
        pr_entry(w), signoff.head_sha(str(w.wd)), "master")
    assert refusal and "candidate changed" in refusal


def test_resolution_digest_survives_a_benign_recheck(w):
    """A re-check after the apply must not look like a changed resolution.

    The applied merge makes the branch up to date, so the re-check carries
    the *compact* resolution forward (``_record_check``).  The digest is
    computed over that same compact projection, so an approval recorded
    before the re-check stays valid.
    """
    rec = _metadata_conflict(w)
    record_merge(w, rec)

    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.UP_TO_DATE
    assert again["resolution_digest"] == rec["resolution_digest"]
    assert again["resolution"]["applied_merge_sha"] == \
        rec["resolution"]["applied_merge_sha"]
    assert signoff.merge_gate_refusal(
        pr_entry(w), again["head"], "master") is None


def test_approval_rejects_a_head_tag_too_short_to_identify_the_head(w):
    rec = _metadata_conflict(w)
    (w.croot / PR).mkdir(parents=True, exist_ok=True)
    (w.croot / PR / "report.html").write_text(
        '<html><head><meta name="pm-signoff-head" content="abc">'
        f'<meta name="pm-signoff-candidate" '
        f'content="{rec["candidate_tree"]}">'
        '<meta name="pm-signoff-checks" content="ran the resolver tests">'
        '<meta name="pm-signoff-evidence" content="review@deadbee,qa@cafef00">'
        '</head><body/></html>')
    problem = signoff.approval_justification_problem(
        PR, pr_entry(w)["integration"], rec["head"])
    assert problem and "pm-signoff-head" in problem
    # A tag that cannot identify the revision is not attributed as evidence.
    assert signoff._report_evidence(PR, rec["head"])["reused"] == []


def test_resolved_approval_is_stale_when_head_moves_after_the_apply(w):
    """A commit after the applied resolution needs a fresh sign-off."""
    rec = _metadata_conflict(w)
    record_merge(w, rec)
    commit(w.wd, "after.txt", "after\n", "commit after the resolution")
    moved = git(w.wd, "rev-parse", "HEAD")
    refusal = signoff.merge_gate_refusal(pr_entry(w), moved, "master")
    assert refusal and "stale" in refusal
    result, _, finalized = merge(w)
    assert result.exit_code != 0 and not finalized


def test_compact_resolution_bounds_records_and_is_idempotent():
    """Re-compacting a compact resolution is a fixed point (digest stable)."""
    records = {f"prs[pr-{i}].notes": {"added_ours": 1, "added_theirs": 0,
                                      "changed": 0, "removed": 0}
               for i in range(60)}
    resolution = {
        "resolver": "project-yaml-records/v1",
        "paths": [{"path": "pm/project.yaml", "records": records}],
        "unresolved": [{"path": "pm/project.yaml", "conflicts": ["c"]}] * 50,
    }
    compact = integration._compact_resolution(resolution)
    entry = compact["paths"][0]
    assert len(entry["records"]) == integration._YAML_LIST_LIMIT
    assert entry["records_total"] == 60
    assert compact["unresolved_total"] == 50
    assert integration._compact_resolution(compact) == compact
    assert integration._resolution_digest(resolution) == \
        integration._resolution_digest(compact)


def test_resolution_preserves_workdir_files_and_evidence(w):
    evidence_file = w.croot / PR / "scenarios" / "1" / "note.txt"
    evidence_file.parent.mkdir(parents=True)
    evidence_file.write_text("keep me\n")
    untracked = w.wd / "scratch.txt"
    untracked.write_text("local work\n")

    rec = _metadata_conflict(w)
    assert rec["status"] == integration.UP_TO_DATE
    assert evidence_file.read_text() == "keep me\n"
    assert untracked.read_text() == "local work\n"


def test_dirty_workdir_keeps_the_isolated_resolution_unapplied(w):
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    head = git(w.wd, "rev-parse", "HEAD")
    (w.wd / "keep.txt").write_text("uncommitted\n")

    rec = integration.prepare(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED
    assert rec.get("apply_error")
    assert not (rec.get("resolution") or {}).get("applied_merge_sha")
    assert git(w.wd, "rev-parse", "HEAD") == head
    assert (w.wd / "keep.txt").read_text() == "uncommitted\n"
    verdict, why = signoff.effective_verdict(
        SIGNOFF_MERGE, pr_entry(w)["integration"], head)
    assert verdict == SIGNOFF_BLOCKED and "could not be applied" in why


def test_bounce_to_review_applies_the_resolved_candidate(w):
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    original_head = git(w.wd, "rev-parse", "HEAD")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED

    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(transcript, git(w.wd, "rev-parse", "HEAD"),
                                 rec["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1",
        retire=lambda *a: None)
    assert res.hop == "review"
    p = pr_entry(w)
    ret = p["signoff_return"]
    assert ret["applied"]["from_head"] == original_head
    assert ret["integration"]["resolution"]["applied_merge_sha"] \
        == ret["applied"]["merge_sha"]
    assert git(w.wd, "rev-parse", "HEAD") == ret["applied"]["merge_sha"]
    assert git(w.wd, "rev-parse", "HEAD^{tree}") == rec["candidate_tree"]
    assert git(w.wd, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert "pm resolved the metadata conflict" in \
        signoff.format_signoff_return(p)


def test_driver_blocks_a_resolved_merge_without_the_evidence_statement(w):
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    rec = integration.prepare(w.pm_dir, PR)
    assert rec["status"] == integration.UP_TO_DATE
    merged = rec["resolution"]["applied_merge_sha"]

    write_report(w, rec, evidence=False)
    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(transcript, merged, rec["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_MERGE,
        window_pane=lambda s, p: "%1",
        retire=lambda *a: None)
    assert res.hop == "blocked"
    assert res.verdict == SIGNOFF_BLOCKED
    assert "pm-signoff-evidence" in res.coerced
    p = pr_entry(w)
    assert p["status"] == "sign_off"
    assert p["signoff"]["original_verdict"] == SIGNOFF_MERGE


# --- prompt + CLI surfaces --------------------------------------------------

def test_signoff_prompt_shows_the_resolution_and_evidence_contract(w):
    rec = _metadata_conflict(w)
    original_head = rec["resolution"]["resolved_from"]["head"]
    qa_dir = w.tmp / "home" / ".pm" / "workdirs" / "qa" / f"{PR}-abcd"
    qa_dir.mkdir(parents=True)
    (qa_dir / "qa_status.json").write_text(json.dumps(
        {"pr_id": PR, "overall": "PASS", "scenarios": []}))
    (qa_dir / "qa_resume.json").write_text(json.dumps(
        {"planner_head": original_head, "planner_code_changes": []}))

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert "Metadata conflict resolution (pm, by record id)" in text
    assert "added from the PR" in text and "pr-300" in text
    assert "added from the base" in text and "pr-250" in text
    assert "Applied to the PR branch" in text
    assert "pm-signoff-candidate" in text
    assert "pm-signoff-evidence" in text
    assert "metadata is not an automatic exemption" in text
    # The evidence revisions the reuse statement must name are surfaced.
    assert f"qa@{original_head[:12]}" in text
    assert f"review@{original_head[:12]}" in text


def test_integrate_cli_prints_the_resolution(w):
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")

    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(pr_mod.pr, ["signoff", "integrate", PR])
    assert r.exit_code == 0, r.output
    assert "resolved by record" in r.output
    assert "added from PR: pr-300" in r.output
    assert "added from base: pr-250" in r.output

    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(
            pr_mod.pr, ["signoff", "integrate", PR, "--no-resolve"])
    assert r.exit_code != 0
    assert "CONFLICTS" in r.output


def test_integrate_cli_apply_exits_nonzero_when_it_cannot_apply(w):
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    # A dirty workdir is never touched, so the resolution stays unapplied;
    # `--apply` asked for the merge and must not report success.
    (w.wd / "keep.txt").write_text("uncommitted\n")

    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(
            pr_mod.pr, ["signoff", "integrate", PR, "--apply"])
    assert r.exit_code != 0
    assert "not applied" in r.output
    assert not (pr_entry(w)["integration"].get("resolution") or {}).get(
        "applied_merge_sha")
