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
import yaml
from click.testing import CliRunner

from pm_core import integration, prompt_gen, signoff, store
from pm_core.cli import pr as pr_mod
from pm_core.signoff import (SIGNOFF_BLOCKED, SIGNOFF_IMPL, SIGNOFF_MERGE,
                             SIGNOFF_REQA, SIGNOFF_REVIEW)

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
                 reason: bool = True, checks: bool = False,
                 head: str | None = None,
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
    if checks:
        extra += ('<meta name="pm-signoff-checks" '
                  'content="ran the resolver tests against the merged tree">')
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


def test_id_list_absent_from_the_base_merges_like_an_empty_one():
    """A nested list the merge base never had still merges by record id."""
    base = "project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
    ours = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
            "  notes:\n  - id: note-a\n    text: branch\n")
    theirs = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
              "  notes:\n  - id: note-b\n    text: base\n")
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is not None, details
    assert "note-a" in merged and "note-b" in merged
    # The same id added on both sides with different content stays ambiguous.
    other = ours.replace("branch", "other")
    merged, details = integration.resolve_project_yaml(base, ours, other)
    assert merged is None
    assert any("added on both sides" in c for c in details["conflicts"])


def test_a_record_deleted_by_both_sides_is_removed():
    """Deleting the same record on both sides is agreement, not a conflict."""
    base = ("project:\n  name: p\nprs:\n"
            "- id: pr-1\n  status: pending\n"
            "- id: pr-2\n  status: pending\n")
    ours = ("project:\n  name: p\nprs:\n"
            "- id: pr-1\n  status: pending\n"
            "- id: pr-3\n  status: pending\n")
    theirs = ("project:\n  name: p\nprs:\n"
              "- id: pr-1\n  status: pending\n"
              "- id: pr-4\n  status: pending\n")
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is not None, details
    assert "pr-2" not in merged
    assert "pr-3" in merged and "pr-4" in merged


def test_preservation_catches_a_lost_record(monkeypatch):
    """The preservation net also covers id-keyed records, not only scalars."""
    base = ("project:\n  name: p\nprs:\n"
            "- id: pr-1\n  status: pending\n"
            "- id: pr-2\n  status: pending\n")
    ours = base.replace(
        "- id: pr-2\n  status: pending\n",
        "- id: pr-2\n  status: pending\n- id: pr-3\n  status: pending\n")
    theirs = base.replace(
        "- id: pr-2\n  status: pending\n",
        "- id: pr-2\n  status: pending\n- id: pr-4\n  status: pending\n")
    real = integration._merge_id_list

    def lossy(b, o, t, path, actions):
        value, conflicts = real(b, o, t, path, actions)
        if path == "prs" and value is not None:
            value = [e for e in value if e["id"] != "pr-3"]
        return value, conflicts

    monkeypatch.setattr(integration, "_merge_id_list", lossy)
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("PR branch record lost: prs[pr-3]" in c
               for c in details["conflicts"])


def test_resolved_text_uses_pm_writer_and_reparses():
    merged, _ = resolve("\n- id: pr-300\n  title: Feat\n  status: pending\n")
    assert merged.startswith(store._YAML_HEADER)
    data = yaml.safe_load(merged)
    assert [p["id"] for p in data["prs"]] == ["pr-100", "pr-200", "pr-300"]


# --- #250 end-to-end -------------------------------------------------------

def _status_conflict(w) -> dict:
    """Make the PR branch and the base change the same field differently."""
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    data = store.load(w.wd / "pm")
    store.get_pr(data, PR)["status"] = "qa"
    store.save(data, w.wd / "pm")
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature edits status")
    data = store.load(w.base_pm)
    store.get_pr(data, PR)["status"] = "merged"
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base edits status")
    return integration.check_integration(w.pm_dir, PR)


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
    # The full artifact must carry the digest of the resolution it records,
    # and the pointer to the delta it describes.
    artifact = json.loads((w.croot / PR / "integration.json").read_text())
    assert artifact.get("resolution_digest") == rec["resolution_digest"], (
        artifact.get("resolution_digest"), rec["resolution_digest"])
    assert artifact["resolution"]["diff_path"] == str(diff_path)

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


def test_notes_appended_to_the_same_record_on_both_sides_survive(w):
    """#250 also appends notes inside an existing PR record, not just PRs."""
    def add_note(pm_dir: Path, note_id: str, text: str) -> None:
        data = store.load(pm_dir)
        store.get_pr(data, PR)["notes"] = [{
            "id": note_id, "text": text,
            "created_at": "2026-01-01T00:00:00Z"}]
        store.save(data, pm_dir)

    add_note(w.wd / "pm", "note-branch", "from the branch")
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "branch note")
    original_head = git(w.wd, "rev-parse", "HEAD")
    add_note(w.base_pm, "note-base", "from the base")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base note")

    rec = integration.prepare(w.pm_dir, PR)
    assert rec["status"] == integration.UP_TO_DATE, rec
    entry = rec["resolution"]["paths"][0]
    # The nested ids are named with their list path: a notes-only resolution
    # must not look like "nothing happened".
    assert entry["added_ours"] == [f"prs[{PR}].notes:note-branch"]
    assert entry["added_theirs"] == [f"prs[{PR}].notes:note-base"]
    # The resolved summary counts the nested records, not just top-level PRs.
    assert "1 added from PR, 1 from base" in integration.summary(
        dict(rec, status=integration.RESOLVED))

    notes = [n["id"]
             for n in store.get_pr(store.load(w.wd / "pm"), PR)["notes"]]
    assert notes == ["note-branch", "note-base"]
    assert git(w.wd, "rev-parse", "HEAD^{tree}") == rec["candidate_tree"]
    assert rec["resolution"]["resolved_from"]["head"] == original_head

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert f"prs[{PR}].notes:note-branch" in text
    assert f"prs[{PR}].notes:note-base" in text


def test_notes_added_through_the_real_note_path_still_merge(w):
    """``pm pr note add`` also bumps ``updated_at`` (real path, #250).

    The previous test writes notes straight through ``store.save``; the
    command a session actually runs also rewrites ``updated_at`` via
    ``_record_status_timestamp``, so both sides change that bookkeeping field
    to different values.  That must not defeat the metadata resolution.
    """
    from pm_core.cli.helpers import _record_status_timestamp

    def add_note(pm_dir: Path, note_id: str, text: str) -> None:
        data = store.load(pm_dir)
        rec = store.get_pr(data, PR)
        rec.setdefault("notes", []).append({
            "id": note_id, "text": text,
            "created_at": "2026-01-01T00:00:00Z",
            "last_edited": "2026-01-01T00:00:00Z"})
        _record_status_timestamp(rec)
        store.save(data, pm_dir)

    add_note(w.wd / "pm", "note-branch", "from the branch")
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "branch note")
    original_head = git(w.wd, "rev-parse", "HEAD")
    add_note(w.base_pm, "note-base", "from the base")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base note")

    rec = integration.prepare(w.pm_dir, PR)
    assert rec["status"] == integration.UP_TO_DATE, rec
    notes = [n["id"]
             for n in store.get_pr(store.load(w.wd / "pm"), PR)["notes"]]
    assert notes == ["note-branch", "note-base"]
    assert git(w.wd, "rev-parse", "HEAD^{tree}") == rec["candidate_tree"]
    assert rec["resolution"]["resolved_from"]["head"] == original_head


def test_same_field_conflict_routes_to_impl_and_changes_nothing(w):
    rec = _status_conflict(w)
    head = git(w.wd, "rev-parse", "HEAD")
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


def test_a_targeted_checks_statement_satisfies_the_reuse_requirement(w):
    """The report may state targeted checks instead of reused evidence.

    The gate accepts either an explicit reuse statement (evidence + reason)
    or the checks the agent actually ran; a checks-only report is a recorded
    act, not an invented approval.
    """
    rec = _metadata_conflict(w)
    write_report(w, rec, evidence=False, reason=False, checks=True)
    assert signoff.approval_justification_problem(
        PR, pr_entry(w)["integration"], rec["head"]) is None
    # And it records as a valid approval (the gate agrees).
    signoff.record_signoff_verdict(
        w.pm_dir, PR, SIGNOFF_MERGE, rec["head"], "manual",
        integration=integration.binding(pr_entry(w)["integration"]))
    assert pr_entry(w)["signoff"]["evidence"]["checks"]
    assert signoff.merge_gate_refusal(pr_entry(w), rec["head"], "master") is None


def test_evidence_records_the_prior_decision_and_an_honest_review_revision(w):
    """R6 provenance: the block names the prior sign-off and never invents a
    review revision when QA committed code after the review ran."""
    rec = _metadata_conflict(w)
    write_report(w, rec, verdict=SIGNOFF_REVIEW)
    signoff.record_signoff_verdict(
        w.pm_dir, PR, SIGNOFF_REVIEW, rec["head"], "manual",
        integration=integration.binding(pr_entry(w)["integration"]))
    first = pr_entry(w)["signoff"]["evidence"]
    assert first["prior_signoff"] is None       # nothing preceded it
    assert first["required_return_stage"] == "review"

    qa_dir = w.tmp / "home" / ".pm" / "workdirs" / "qa" / f"{PR}-abcd"
    qa_dir.mkdir(parents=True)
    (qa_dir / "qa_status.json").write_text(json.dumps(
        {"pr_id": PR, "overall": "PASS", "scenarios": []}))
    (qa_dir / "qa_resume.json").write_text(json.dumps(
        {"planner_head": "f" * 40, "planner_code_changes": ["fix.py"]}))

    write_report(w, rec, verdict=SIGNOFF_MERGE)
    signoff.record_signoff_verdict(
        w.pm_dir, PR, SIGNOFF_MERGE, rec["head"], "manual",
        integration=integration.binding(pr_entry(w)["integration"]))
    ev = pr_entry(w)["signoff"]["evidence"]
    stored_integ = pr_entry(w)["integration"]
    assert ev["reviewed_head"] == rec["head"]
    assert ev["required_return_stage"] == "merge"
    # The block names the candidate the decision reviewed.
    assert ev["candidate_tree"] == stored_integ["candidate_tree"]
    resolved_from = rec["resolution"]["resolved_from"]
    assert ev["resolved_from"]["head"] == resolved_from["head"]
    assert ev["prior_signoff"]["verdict"] == SIGNOFF_REVIEW
    assert ev["prior_signoff"]["sha"] == rec["head"]
    assert ev["prior_signoff"]["origin"] == "manual"
    # QA recorded code changes, so pm does not claim the review saw that
    # revision — it says so instead of guessing.
    assert ev["review"]["sha"] is None
    assert ev["review"]["sha_source"] is None
    assert "does not record" in ev["review"]["note"]
    assert ev["qa"]["planner_head"] == "f" * 40
    assert ev["qa"]["planner_code_changes"] == ["fix.py"]


def test_evidence_does_not_attribute_another_revisions_candidate(w):
    """A decision recorded for a revision the stored check does not describe
    must not inherit that check's candidate tree or resolution.

    Otherwise the recorded provenance would claim pm confirmed a candidate
    for a HEAD it never checked.
    """
    rec = _metadata_conflict(w)
    stored = pr_entry(w)["integration"]
    assert stored["candidate_tree"] and stored["resolved_from"]
    assert stored["head"] == rec["head"]

    # A decision for another revision, recorded without an integration
    # binding (the stored check is not of that revision).
    signoff.record_signoff_verdict(w.pm_dir, PR, SIGNOFF_REVIEW, "a" * 40,
                                   "manual")
    ev = pr_entry(w)["signoff"]["evidence"]
    assert ev["reviewed_head"] == "a" * 40
    assert ev["candidate_tree"] is None
    assert ev["resolved_from"] is None


def test_malformed_qa_evidence_does_not_crash_the_record(w):
    """A corrupt QA snapshot is reported, not raised out of sign-off."""
    qa_dir = w.tmp / "home" / ".pm" / "workdirs" / "qa" / f"{PR}-abcd"
    qa_dir.mkdir(parents=True)
    (qa_dir / "qa_status.json").write_text(json.dumps(["not", "a", "mapping"]))
    (qa_dir / "qa_resume.json").write_text(json.dumps(
        {"planner_head": "f" * 40, "planner_code_changes": 5}))

    evidence = signoff.qa_evidence(PR)
    assert evidence["overall"] is None
    assert evidence["planner_code_changes"] == []
    rec = integration.check_integration(w.pm_dir, PR)
    signoff.record_signoff_verdict(
        w.pm_dir, PR, SIGNOFF_REVIEW, rec["head"], "manual",
        integration=integration.binding(rec))
    assert pr_entry(w)["signoff"]["evidence"]["qa"]["planner_code_changes"] == []

    # An unparseable qa_status.json must not discard the revision the
    # sibling resume snapshot records: it is still the evidence's revision.
    (qa_dir / "qa_status.json").write_text("{not json")
    evidence = signoff.qa_evidence(PR)
    assert evidence["error"] == "unreadable"
    assert evidence["planner_head"] == "f" * 40
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(store.load(w.pm_dir), PR)
    assert f"qa@{'f' * 12}" in text


def test_malformed_qa_status_does_not_crash_the_signoff_prompt(w):
    """A valid-JSON non-mapping qa_status.json must not raise out of the prompt.

    The record path already treats such a file as malformed evidence; the
    sign-off prompt's QA block must do the same instead of calling ``.get``
    on a list.
    """
    qa_dir = w.tmp / "home" / ".pm" / "workdirs" / "qa" / f"{PR}-abcd"
    qa_dir.mkdir(parents=True)
    (qa_dir / "qa_status.json").write_text(json.dumps(["not", "a", "mapping"]))
    (qa_dir / "qa_resume.json").write_text(json.dumps(
        {"planner_head": "f" * 40, "planner_code_changes": []}))

    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(store.load(w.pm_dir), PR)
    assert "qa_status.json malformed" in text


def test_malformed_qa_resume_revision_does_not_crash_the_prompt(w):
    """A non-string ``planner_head`` is malformed evidence, not a revision.

    The evidence block and the prompt slice/print that value; an int (or a
    list) would raise out of the sign-off launch, which the QA contract
    forbids ("no crash from malformed evidence").
    """
    qa_dir = w.tmp / "home" / ".pm" / "workdirs" / "qa" / f"{PR}-abcd"
    qa_dir.mkdir(parents=True)
    (qa_dir / "qa_status.json").write_text(json.dumps({"overall": "PASS"}))
    (qa_dir / "qa_resume.json").write_text(json.dumps(
        {"planner_head": 123, "planner_code_changes": []}))

    evidence = signoff.qa_evidence(PR)
    assert evidence["planner_head"] is None
    rec = integration.check_integration(w.pm_dir, PR)
    signoff.record_signoff_verdict(
        w.pm_dir, PR, SIGNOFF_REVIEW, rec["head"], "manual",
        integration=integration.binding(rec))
    assert pr_entry(w)["signoff"]["evidence"]["qa"]["planner_head"] is None

    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(store.load(w.pm_dir), PR)
    assert "no recorded revision" in text
    assert "qa@123" not in text


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


def test_merge_gate_refuses_a_rechecked_record_for_another_head(w):
    """Defense in depth: the approval's HEAD must match the current record."""
    rec = _metadata_conflict(w)
    record_merge(w, rec)

    def _tamper(d):
        store.get_pr(d, PR)["integration"]["head"] = "f" * 40
    store.locked_update(w.pm_dir, _tamper)
    refusal = signoff.merge_gate_refusal(
        pr_entry(w), signoff.head_sha(str(w.wd)), "master")
    assert refusal and "another HEAD" in refusal


def test_merge_gate_refuses_a_clean_approval_without_the_evidence_statement(w):
    """A clean base change needs the statement even without a resolution."""
    data = store.load(w.base_pm)
    data["project"]["model_config"] = {"session_models": {"impl": "model-new"}}
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base changes model")

    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    assert rec["base_behavior_changes"]
    assert not (rec.get("resolution") or {}), "this case has no resolution"

    write_report(w, rec)
    signoff.record_signoff_verdict(
        w.pm_dir, PR, SIGNOFF_MERGE, rec["head"], "manual",
        integration=integration.binding(rec))
    assert signoff.merge_gate_refusal(pr_entry(w), rec["head"], "master") is None

    write_report(w, rec, evidence=False)
    refusal = signoff.merge_gate_refusal(pr_entry(w), rec["head"], "master")
    assert refusal and "behavioural changes" in refusal


def test_merge_gate_refuses_an_approval_bound_to_an_unapplied_resolution(w):
    """A bound resolution that was never applied cannot be published."""
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    head = git(w.wd, "rev-parse", "HEAD")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED
    assert not rec["resolution"].get("applied_merge_sha")

    # Record the approval directly (the manual/CLI paths refuse it): the gate
    # is the last line and must refuse it on its own.
    signoff.record_signoff_verdict(
        w.pm_dir, PR, SIGNOFF_MERGE, head, "manual",
        integration=integration.binding(rec))
    refusal = signoff.merge_gate_refusal(pr_entry(w), head, "master")
    assert refusal and "was not applied" in refusal


def test_merge_gate_refuses_an_approval_bound_to_unresolved_resolution(w):
    """An approval recorded against an ambiguous resolution never publishes."""
    head = git(w.wd, "rev-parse", "HEAD")
    resolution = {
        "paths": [{"path": "pm/project.yaml"}],
        "unresolved": [{"path": "pm/project.yaml",
                        "conflicts": ["ambiguous record"]}],
    }
    rec = {"status": integration.RESOLVED, "head": head,
           "base_branch": "master",
           "base_sha": git(w.repo, "rev-parse", "master"),
           "candidate_tree": git(w.wd, "rev-parse", "HEAD^{tree}"),
           "resolution": resolution,
           "resolution_digest": integration._resolution_digest(resolution)}

    def _set(d):
        store.get_pr(d, PR)["integration"] = integration.compact(rec)
    store.locked_update(w.pm_dir, _set)
    signoff.record_signoff_verdict(
        w.pm_dir, PR, SIGNOFF_MERGE, head, "manual",
        integration=integration.binding(rec))
    refusal = signoff.merge_gate_refusal(pr_entry(w), head, "master")
    assert refusal and "unresolved" in refusal


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
    # The artifact keeps the human-readable delta through a re-check.
    artifact = json.loads((w.croot / PR / "integration.json").read_text())
    assert "resolved" in artifact["resolution"]["diff"]


def test_a_concurrent_apply_does_not_overwrite_the_applied_record(
        w, monkeypatch):
    """The loser of two simultaneous ``--apply`` runs must not clobber the
    winner's applied record with its stale resolved check.

    Its apply fails with "PR HEAD moved"; recording that stale record would
    drop the applied revision and the resolution provenance (and a later
    ``--record`` could not restore them once the branch carries the base).
    """
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    stale_head = git(w.wd, "rev-parse", "HEAD")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")

    # Winner: applies the resolution and records the applied revision.
    won = integration.prepare(w.pm_dir, PR)
    assert won["status"] == integration.UP_TO_DATE
    applied = won["resolution"]["applied_merge_sha"]
    assert pr_entry(w)["integration"]["resolution"]["applied_merge_sha"] == \
        applied

    # Loser: its check ran before the winner applied, and its own apply now
    # finds the HEAD moved.
    stale = dict(won)
    stale.update(status=integration.RESOLVED, head=stale_head)
    stale.pop("resolution", None)
    stale.pop("resolution_digest", None)
    monkeypatch.setattr(integration, "check_integration",
                        lambda *a, **k: dict(stale))
    monkeypatch.setattr(integration, "apply_integration",
                        lambda *a, **k: (None, integration.HEAD_MOVED))

    lost = integration.prepare(w.pm_dir, PR)
    assert lost["status"] == integration.UP_TO_DATE, lost
    assert lost["head"] == git(w.wd, "rev-parse", "HEAD")
    assert lost["resolution"]["applied_merge_sha"] == applied
    assert not lost.get("apply_error")
    stored = pr_entry(w)["integration"]
    assert stored["status"] == integration.UP_TO_DATE
    assert stored["head"] == git(w.wd, "rev-parse", "HEAD")
    assert stored["resolution"]["applied_merge_sha"] == applied
    assert not stored.get("apply_error")


def test_record_check_carries_the_applied_resolution_under_the_lock(
        w, monkeypatch):
    """The carry-forward is decided on the state actually stored.

    A concurrent writer can store an applied record between this check's
    read and its write; the write must still carry that applied resolution
    (otherwise a plain up-to-date re-check would drop it).
    """
    rec = _metadata_conflict(w)
    applied = rec["resolution"]["applied_merge_sha"]
    real_load = store.load
    calls = {"n": 0}

    def stale_first_load(root, **kwargs):
        data = real_load(root, **kwargs)
        if calls["n"] == 0:
            # The pre-lock read predates the winner's write.
            p = store.get_pr(data, PR)
            if p is not None:
                p["integration"] = {
                    k: v for k, v in (p.get("integration") or {}).items()
                    if k != "resolution"}
        calls["n"] += 1
        return data

    monkeypatch.setattr(store, "load", stale_first_load)
    head = git(w.wd, "rev-parse", "HEAD")
    bare = {"status": integration.UP_TO_DATE, "head": head,
            "base_sha": rec["base_sha"], "base_branch": "master",
            "target_repo": str(w.repo),
            "candidate_tree": rec["candidate_tree"]}
    out = integration._record_check(w.pm_dir, PR, bare)
    assert out["resolution"]["applied_merge_sha"] == applied
    stored = pr_entry(w)["integration"]
    assert stored["head"] == head
    assert stored["resolution"]["applied_merge_sha"] == applied


def test_a_stale_check_does_not_replace_the_record_for_the_current_head(w):
    """A check that started before a concurrent apply reads the old HEAD but
    can finish after it; recording it would describe a revision the branch no
    longer has and drop the applied provenance."""
    rec = _metadata_conflict(w)
    applied = rec["resolution"]["applied_merge_sha"]
    old_head = rec["resolution"]["resolved_from"]["head"]
    assert old_head != rec["head"]
    stale = {"status": integration.RESOLVED, "head": old_head,
             "base_sha": rec["base_sha"], "base_branch": "master",
             "target_repo": str(w.repo),
             "candidate_tree": rec["candidate_tree"],
             "conflicts": ["pm/project.yaml"]}
    out = integration._record_check(w.pm_dir, PR, stale)
    assert out["head"] == rec["head"]
    stored = pr_entry(w)["integration"]
    assert stored["status"] == integration.UP_TO_DATE
    assert stored["head"] == rec["head"]
    assert stored["resolution"]["applied_merge_sha"] == applied


def test_prepare_records_the_recheck_once_with_the_resolution(w, monkeypatch):
    """The post-apply re-check is written once, already carrying the
    resolution.

    An intermediate record without the resolution would lose the applied
    provenance (and with it the explicit-reuse requirement) if pm died
    between the two writes.
    """
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")

    calls = []
    real = integration._record_check

    def spy(root, pr_id, record):
        # Keep the object: ``_record_check`` adds the digest it writes.
        calls.append(record)
        return real(root, pr_id, record)

    monkeypatch.setattr(integration, "_record_check", spy)
    rec = integration.prepare(w.pm_dir, PR)
    assert rec["status"] == integration.UP_TO_DATE
    assert [c["status"] for c in calls] == [integration.RESOLVED,
                                            integration.UP_TO_DATE]
    assert calls[-1]["resolution"]["applied_merge_sha"]
    assert calls[-1]["resolution_digest"] == rec["resolution_digest"]


def test_carry_forward_uses_the_checkout_the_check_used(w, monkeypatch):
    """A check from the current checkout (recorded workdir not visible) keeps
    the applied resolution instead of silently dropping its provenance."""
    rec = _metadata_conflict(w)

    def _drop_workdir(d):
        store.get_pr(d, PR)["workdir"] = "/nonexistent/pr-workdir"
    store.locked_update(w.pm_dir, _drop_workdir)
    monkeypatch.chdir(w.wd)
    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.UP_TO_DATE
    assert again["resolution_digest"] == rec["resolution_digest"]
    assert again["resolution"]["applied_merge_sha"] == \
        rec["resolution"]["applied_merge_sha"]


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


def test_approval_rejects_a_candidate_tag_too_short_to_identify_the_tree(w):
    rec = _metadata_conflict(w)
    (w.croot / PR).mkdir(parents=True, exist_ok=True)
    (w.croot / PR / "report.html").write_text(
        f'<html><head><meta name="pm-signoff-head" content="{rec["head"]}">'
        f'<meta name="pm-signoff-candidate" '
        f'content="{rec["candidate_tree"][:3]}">'
        '<meta name="pm-signoff-evidence" content="review@deadbee,qa@cafef00">'
        '<meta name="pm-signoff-evidence-reason" content="records only">'
        '</head><body/></html>')
    problem = signoff.approval_justification_problem(
        PR, pr_entry(w)["integration"], rec["head"])
    assert problem and "pm-signoff-candidate" in problem and "usable" in problem


def test_approval_rejects_a_candidate_tag_for_another_tree(w):
    """A long-enough tag that names a different tree is not the approval."""
    rec = _metadata_conflict(w)
    (w.croot / PR).mkdir(parents=True, exist_ok=True)
    (w.croot / PR / "report.html").write_text(
        f'<html><head><meta name="pm-signoff-head" content="{rec["head"]}">'
        f'<meta name="pm-signoff-candidate" content="{"z" * 40}">'
        '<meta name="pm-signoff-evidence" content="review@deadbee,qa@cafef00">'
        '<meta name="pm-signoff-evidence-reason" content="records only">'
        '</head><body/></html>')
    problem = signoff.approval_justification_problem(
        PR, pr_entry(w)["integration"], rec["head"])
    assert problem and "does not name the approved candidate" in problem


def test_justification_is_honest_when_the_check_lost_its_candidate(w):
    """A failed/superseded re-check cannot name the approved tree.

    The refusal must say pm cannot confirm the candidate — not blame the
    report for a tree the record no longer carries.
    """
    rec = _metadata_conflict(w)
    record_merge(w, rec)

    def _drop(d):
        integ = store.get_pr(d, PR)["integration"]
        integ.pop("candidate_tree", None)
        integ.pop("base_sha", None)
    store.locked_update(w.pm_dir, _drop)
    refusal = signoff.merge_gate_refusal(
        pr_entry(w), signoff.head_sha(str(w.wd)), "master")
    assert refusal and "does not record a candidate tree" in refusal


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


def test_summary_counts_records_beyond_the_bounded_id_lists():
    """The summary count comes from the per-path counts, not the capped ids."""
    entry = {"path": "pm/project.yaml",
             "added_ours": [f"pr-{i}" for i in range(20)],
             "records": {"prs": {"added_ours": 45, "added_theirs": 3,
                                 "changed": 0, "removed": 0}}}
    rec = {"status": integration.RESOLVED, "base_branch": "master",
           "base_sha": "a" * 40, "resolution": {"paths": [entry]}}
    summary = integration.summary(rec)
    assert "45 added from PR" in summary
    assert "3 from base" in summary


def test_compact_bounds_base_behavior_changes():
    """The behavioural summary is bounded in project.yaml like the rest."""
    record = {"status": integration.CLEAN, "base_sha": "a" * 40,
              "base_behavior_changes": [f"change {i}" for i in range(50)]}
    out = integration.compact(record)
    assert len(out["base_behavior_changes"]) == integration._BEHAVIOR_LIMIT
    assert out["base_behavior_count"] == 50


def test_recompacting_a_compact_record_keeps_the_base_file_count():
    """A bounce re-compacts the compact record (see _record_applied_integration).

    The full ``base_files`` list is gone there; resetting ``base_files_count``
    to 0 would tell the prompt the base changed nothing.
    """
    record = {"status": integration.RESOLVED, "base_sha": "a" * 40,
              "candidate_tree": "b" * 40, "base_files": ["x", "y"],
              "pr_files": [], "resolution": {"paths": []}}
    once = integration.compact(record)
    assert once["base_files_count"] == 2
    assert integration.compact(once)["base_files_count"] == 2


def test_recorded_evidence_lists_are_bounded(w):
    """The evidence block is rewritten into project.yaml: bound its lists."""
    rec = _metadata_conflict(w)
    (w.croot / PR).mkdir(parents=True, exist_ok=True)
    tokens = ",".join(f"review@{i:040x}" for i in range(50))
    (w.croot / PR / "report.html").write_text(
        f'<html><head><meta name="pm-signoff-head" content="{rec["head"]}">'
        f'<meta name="pm-signoff-evidence" content="{tokens}">'
        '<meta name="pm-signoff-evidence-reason" content="records only">'
        '</head><body/></html>')
    qa_dir = w.tmp / "home" / ".pm" / "workdirs" / "qa" / f"{PR}-abcd"
    qa_dir.mkdir(parents=True)
    (qa_dir / "qa_status.json").write_text(json.dumps({"overall": "PASS"}))
    (qa_dir / "qa_resume.json").write_text(json.dumps({
        "planner_head": rec["head"],
        "planner_code_changes": [f"f{i}.py" for i in range(50)]}))
    block = signoff._evidence_block(
        pr_entry(w), rec["head"], integration.binding(rec),
        verdict=SIGNOFF_MERGE)
    limit = signoff._EVIDENCE_LIST_LIMIT
    assert len(block["reused"]) == limit
    assert block["reused_total"] == 50
    assert len(block["qa"]["planner_code_changes"]) == limit
    assert block["qa"]["planner_code_changes_total"] == 50


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
    # Even a report that names everything cannot approve an unapplied merge.
    write_report(w, rec)
    problem = signoff.approval_justification_problem(
        PR, pr_entry(w)["integration"], head)
    assert problem and "not applied" in problem


def test_an_already_integrated_branch_is_not_committed_over(w):
    """A concurrent apply that already merged the base is not reset away."""
    base_sha = git(w.repo, "rev-parse", "master")
    head = git(w.wd, "rev-parse", "HEAD")
    tree = git(w.wd, "rev-parse", "HEAD^{tree}")
    record = {"status": integration.RESOLVED, "head": head,
              "base_sha": base_sha, "candidate_tree": tree,
              "resolution": {"paths": [{"path": "pm/project.yaml"}]}}
    merged, err = integration._apply_resolution(
        record, str(w.wd), head, base_sha, "Integrate master")
    assert err is None, err
    assert merged == head
    assert git(w.wd, "rev-parse", "HEAD") == head
    assert git(w.wd, "rev-parse", "HEAD^{tree}") == tree


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
    # The next stage also sees the revisions the resolution combined.
    assert ret["integration"]["resolution"]["resolved_from"]["head"] \
        == original_head
    assert ret["integration"]["resolution"]["resolved_from"]["base_sha"] \
        == rec["base_sha"]
    assert git(w.wd, "rev-parse", "HEAD") == ret["applied"]["merge_sha"]
    assert git(w.wd, "rev-parse", "HEAD^{tree}") == rec["candidate_tree"]
    assert git(w.wd, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert "pm resolved the metadata conflict" in \
        signoff.format_signoff_return(p)


def test_a_review_bounce_after_the_launch_apply_gets_the_diff_hint(w):
    """``prepare`` applied the base at launch, so the bounce has nothing left
    to apply — but the routed step must still diff against the new base.

    The workdir's own base refs are stale after the apply, so the usual
    ``<base>...HEAD`` diff would list the merged base commits as PR changes.
    """
    rec = _metadata_conflict(w)
    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(transcript, rec["head"], rec["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res
    ret = pr_entry(w)["signoff_return"]
    assert not ret.get("applied")
    assert ret["integration"]["resolution"]["applied_merge_sha"]
    text = signoff.format_signoff_return(pr_entry(w))
    assert f"git diff {rec['base_sha'][:12]} HEAD" in text


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
    # The base-interaction judgment guidance stays in the prompt: it is why
    # sign-off reads the base diff at all.  Normalize the wrapping so the
    # assertion is about the instruction, not the line breaks.
    flat = " ".join(text.split())
    assert "judge whether it interacts" in flat
    assert "semantic overlap" in flat
    assert "Line/file counts alone are not the rule" in flat
    # The applied-resolution diff is described honestly: it shows the whole
    # base merge, not only the resolution.
    assert "shows exactly what the resolution added" not in text
    assert "whole base merge as applied" in text
    # The evidence revisions the reuse statement must name are surfaced.
    assert f"qa@{original_head[:12]}" in text
    assert f"review@{original_head[:12]}" in text


def test_signoff_prompt_diffs_against_the_applied_base(w):
    """After a launch apply the workdir's own base ref is stale.

    ``git diff master...HEAD`` would then list the merged base commits as PR
    changes, so the prompt's primary diff command must name the exact base
    revision the resolution was applied on.
    """
    rec = _metadata_conflict(w)
    # The workdir's own base ref still points at the pre-base commit.
    assert git(w.wd, "rev-parse", "master") != rec["base_sha"]

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert f"git diff {rec['base_sha'][:12]}...HEAD" in text
    assert "git diff master...HEAD" not in text
    # The base is inside HEAD now: never an empty `base..base` range that
    # claims the base changed nothing.
    assert "0 file(s)" not in text


def test_signoff_prompt_diffs_against_the_base_after_a_clean_bounce(w):
    """A clean base merged by a bounce is inside the branch too.

    The bounce applied the base, so the next sign-off's ``<base>...HEAD``
    diff against the workdir's stale base ref would list the merged base
    commits as PR changes.
    """
    commit(w.repo, "base.txt", "base\n", "base moves ahead")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(transcript, rec["head"], rec["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res

    # Sign-off re-runs after the review: prepare re-checks the integrated
    # branch (up to date) and the prompt must diff against the recorded base.
    again = integration.prepare(w.pm_dir, PR)
    assert again["status"] == integration.UP_TO_DATE
    assert again["base_sha"] == rec["base_sha"]
    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert f"git diff {again['base_sha'][:12]}...HEAD" in text
    assert "git diff master...HEAD" not in text


def test_signoff_prompt_falls_back_to_the_base_branch_for_an_unmerged_base(w):
    """A base that is not in the branch keeps the usual base-branch diff."""
    commit(w.repo, "base.txt", "base\n", "base moves ahead")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert "git diff master...HEAD" in text
    assert "0 file(s)" not in text


def test_prompt_base_range_after_the_base_moves_past_an_applied_resolution(w):
    """A later base move is not re-described as the whole pre-apply range.

    The applied resolution is carried forward, but the recorded merge base is
    now the applied base.  The "base changes" range must start there: using
    the pre-apply merge base would list the commits the resolution already
    merged as new base changes, and the recorded file count (computed over
    the current range) would no longer match.
    """
    rec = _metadata_conflict(w)
    applied_base = rec["base_sha"]
    pre_merge_base = rec["resolution"]["resolved_from"]["merge_base"]
    assert pre_merge_base != applied_base

    # The base moves on cleanly: nothing for the resolution to reconcile.
    commit(w.repo, "base_only.txt", "base\n", "base moves ahead")
    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.CLEAN, again
    assert again["merge_base"] == applied_base
    assert again["resolution"]["applied_merge_sha"]

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert (f"git log --oneline {applied_base[:12]}.."
            f"{again['base_sha'][:12]}") in text
    assert f"{pre_merge_base[:12]}.." not in text
    assert "(1 file(s))" in text


def test_review_and_qa_prompts_diff_against_the_applied_base(w):
    """Review/QA prompts must not list the merged base commits as PR changes.

    A resolved metadata conflict is applied at sign-off launch, so by the time
    review/QA run the branch already contains the base while the workdir's own
    base ref still points before it.  Their primary diff command must use the
    exact applied base, not the stale base branch.
    """
    rec = _metadata_conflict(w)
    applied_base = rec["resolution"]["resolved_from"]["base_sha"]
    assert applied_base == rec["base_sha"]
    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        review = prompt_gen.generate_review_prompt(data, PR)
        planner = prompt_gen.generate_qa_planner_prompt(data, PR)
    assert f"git diff {applied_base[:12]}...HEAD" in review
    assert "git diff master...HEAD" not in review
    assert f"git diff {applied_base[:12]}...HEAD" in planner
    assert "git diff master...HEAD" not in planner


def test_review_prompt_diffs_against_the_base_a_clean_bounce_merged(w):
    """A clean bounce leaves the CLEAN check, but the branch has the base.

    The applied merge is recorded only in the return record, so the review
    prompt must take its diff base from there instead of the stale branch ref.
    """
    commit(w.repo, "base.txt", "base\n", "base moves ahead")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(transcript, rec["head"], rec["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res
    ret = pr_entry(w)["signoff_return"]
    assert ret["applied"]["base_sha"] == rec["base_sha"]

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        review = prompt_gen.generate_review_prompt(data, PR)
    assert f"git diff {rec['base_sha'][:12]}...HEAD" in review
    assert "git diff master...HEAD" not in review


def test_review_prompt_diffs_against_the_newest_base_a_bounce_merged(w):
    """The branch can contain two bases; diff against the newest one.

    A metadata resolution applies base B1 at sign-off; later the base moves to
    B2 and a bounce merges B2 into the branch.  The carried resolution still
    names B1, so taking the applied resolution's base first would make the
    review prompt diff ``B1...HEAD`` and list B2's commits as the PR's own
    changes — contradicting the return block, which already names B2.
    """
    rec = _metadata_conflict(w)                      # applies base B1
    b1 = rec["base_sha"]
    assert rec["resolution"]["applied_merge_sha"]

    commit(w.repo, "base_only.txt", "base\n", "base moves ahead")
    b2 = git(w.repo, "rev-parse", "HEAD")
    assert b2 != b1
    clean = integration.check_integration(w.pm_dir, PR)
    assert clean["status"] == integration.CLEAN, clean

    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(transcript, clean["head"], clean["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res
    ret = pr_entry(w)["signoff_return"]
    assert ret["applied"]["base_sha"] == b2
    assert git(w.wd, "rev-parse", "HEAD") == ret["applied"]["merge_sha"]

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        review = prompt_gen.generate_review_prompt(data, PR)
    assert f"git diff {b2[:12]}...HEAD" in review
    assert f"git diff {b1[:12]}...HEAD" not in review
    assert "git diff master...HEAD" not in review


def test_signoff_prompt_names_the_newest_base_after_a_bounce_merged_it(w):
    """The resolution block's "PR's own changes" diff names the newest base.

    Same two-base situation as the review case: the applied resolution block
    must not point the agent at a diff that lists the newer base's commits as
    the PR's changes.
    """
    rec = _metadata_conflict(w)
    b1 = rec["base_sha"]
    commit(w.repo, "base_only.txt", "base\n", "base moves ahead")
    b2 = git(w.repo, "rev-parse", "HEAD")
    clean = integration.check_integration(w.pm_dir, PR)
    assert clean["status"] == integration.CLEAN, clean
    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(transcript, clean["head"], clean["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res

    again = integration.prepare(w.pm_dir, PR)
    assert again["status"] == integration.UP_TO_DATE, again
    assert again["base_sha"] == b2
    assert again["resolution"]["applied_merge_sha"]
    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert f"git diff {b2[:12]}...HEAD" in text
    assert f"git diff {b1[:12]}...HEAD" not in text


def test_signoff_prompt_names_a_merged_base_after_the_return_record_is_replaced(
        w):
    """A merged base stays the diff base after a later bounce replaced the
    return record that named it.

    A clean bounce merges base B1, recording it only in
    ``signoff_return.applied``.  A later QA bounce replaces that record (an
    up-to-date check applies nothing, so the new record carries no ``applied``
    block).  Once the base moves to B2, the last check's merge base (B1) is the
    newest base the branch contains; the sign-off prompt must diff against it
    rather than the workdir's stale ``master`` ref, which lists B1's commits as
    the PR's own changes.
    """
    commit(w.repo, "base_only.txt", "base\n", "base moves ahead")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN, rec
    b1 = rec["base_sha"]
    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(transcript, rec["head"], rec["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res
    assert pr_entry(w)["signoff_return"]["applied"]["base_sha"] == b1

    # Review finishes: the next sign-off check is up to date and routes QA,
    # replacing the return record with one that carries no ``applied`` block.
    head = git(w.wd, "rev-parse", "HEAD")
    up = integration.prepare(w.pm_dir, PR)
    assert up["status"] == integration.UP_TO_DATE, up

    def _to_qa(d):
        p = store.get_pr(d, PR)
        p["status"] = "sign_off"
        p["signoff_return"] = signoff.build_return_record(
            dict(p), SIGNOFF_REQA, "qa", reviewed_head=head)
    store.locked_update(w.pm_dir, _to_qa)
    assert not (pr_entry(w)["signoff_return"].get("applied"))

    # The base moves on; the next check is clean and names b1 as its merge
    # base — the newest base the branch already contains.
    commit(w.repo, "base_only2.txt", "base\n", "base moves again")
    again = integration.prepare(w.pm_dir, PR)
    assert again["status"] == integration.CLEAN, again
    assert again["merge_base"] == b1
    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
        review = prompt_gen.generate_review_prompt(data, PR)
    assert f"git diff {b1[:12]}...HEAD" in text
    assert "git diff master...HEAD" not in text
    # The review and QA prompts share the same diff base.
    assert f"git diff {b1[:12]}...HEAD" in review
    assert "git diff master...HEAD" not in review


def test_signoff_prompt_counts_behavior_changes_stored_without_a_total(w):
    """21-30 base behaviour changes are stored in full with no count key.

    ``compact`` records ``base_behavior_count`` only when it truncates the
    list (> ``_BEHAVIOR_LIMIT``), so the prompt must fall back to the stored
    list's length instead of indexing the absent key — that raised KeyError
    and blocked sign-off from launching on such a base.
    """
    integration.check_integration(w.pm_dir, PR)
    changes = [f"`pm/project.yaml`: change {i}" for i in range(25)]
    assert integration._BEHAVIOR_LIMIT > len(changes)   # not truncated

    def _store(d):
        integ = store.get_pr(d, PR)["integration"]
        integ["base_behavior_changes"] = changes
        integ.pop("base_behavior_count", None)
    store.locked_update(w.pm_dir, _store)
    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert "… 5 more" in text
    assert "change 19" in text          # the last one rendered in full
    assert "change 20" not in text      # beyond the 20-line cap


def test_merge_gate_refuses_a_clean_approval_whose_recheck_lost_the_candidate(
        w, monkeypatch):
    """A re-check that cannot name a candidate cannot justify the approval.

    This holds even without a resolution or behavioural base change: the
    gate must not pass an approval it cannot tie to the approved tree.
    """
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.UP_TO_DATE
    record_merge(w, rec)

    monkeypatch.setattr(integration, "fetch_base",
                        lambda *a, **k: (None, "network down"))
    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.ERROR
    assert not again.get("candidate_tree")
    refusal = signoff.merge_gate_refusal(
        pr_entry(w), signoff.head_sha(str(w.wd)), "master")
    assert refusal and "does not record a candidate tree" in refusal


def test_merge_gate_allows_recovery_when_the_head_is_already_in_the_base(w):
    """``in_base`` carries no candidate tree but is not a lost approval.

    The approved head is already published, so the merge step's recovery
    path finalizes that merge rather than returning to sign-off.
    """
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.UP_TO_DATE
    record_merge(w, rec)

    def _in_base(d):
        integ = store.get_pr(d, PR)["integration"]
        integ["status"] = integration.IN_BASE
        integ.pop("candidate_tree", None)
    store.locked_update(w.pm_dir, _in_base)
    assert signoff.merge_gate_refusal(
        pr_entry(w), signoff.head_sha(str(w.wd)), "master") is None


def test_merge_gate_allows_recovery_for_a_resolved_approval_already_in_base(w):
    """The same ``in_base`` recovery holds for a resolved (applied) approval.

    A resolved candidate is applied to the branch, so its head can be in the
    base after a partially completed publication just like a clean one.  The
    approval then has a resolution digest but the ``in_base`` record carries
    no candidate tree; requiring the candidate tag there would refuse a merge
    that already happened and send the PR to a sign-off that can only block an
    ``in_base`` head.
    """
    rec = _metadata_conflict(w)
    assert rec["status"] == integration.UP_TO_DATE
    assert rec["resolution"]["applied_merge_sha"]
    record_merge(w, rec)
    assert signoff.merge_gate_refusal(pr_entry(w), rec["head"], "master") is None

    def _in_base(d):
        integ = store.get_pr(d, PR)["integration"]
        integ["status"] = integration.IN_BASE
        integ.pop("candidate_tree", None)
    store.locked_update(w.pm_dir, _in_base)
    assert signoff.merge_gate_refusal(
        pr_entry(w), signoff.head_sha(str(w.wd)), "master") is None


def test_an_unsummarisable_base_change_still_requires_the_evidence_statement(
        w, monkeypatch):
    """A failed behaviour summary must not become an implicit exemption.

    ``compute_candidate`` swallows a summary failure so the check still runs;
    that must not read as "the base changes nothing".  A MERGE then requires
    the same explicit reuse/checks statement as a listed behavioural change,
    and the prompt says the summary failed instead of showing no changes.
    """
    data = store.load(w.base_pm)
    data["project"]["model_config"] = {"session_models": {"impl": "model-new"}}
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base changes model")

    def boom(*a, **k):
        raise RuntimeError("summary exploded")

    monkeypatch.setattr(integration, "base_behavior_changes", boom)
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    assert not rec["base_behavior_changes"]
    assert "summary exploded" in rec["base_behavior_error"]

    # Recording a MERGE without the statement is refused.
    write_report(w, rec, candidate=False, evidence=False, reason=False)
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(pr_mod.pr, ["signoff", "record", PR])
    assert r.exit_code != 0 and "pm-signoff-evidence" in r.output

    # The prompt tells the agent the summary failed rather than listing none.
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(store.load(w.pm_dir), PR)
    assert "could not summarise the base's behaviour-relevant changes" in text

    write_report(w, rec, candidate=False)
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(pr_mod.pr, ["signoff", "record", PR])
    assert r.exit_code == 0, r.output
    assert signoff.merge_gate_refusal(pr_entry(w), rec["head"], "master") is None


def test_a_failed_resolution_is_not_reported_as_resolved(w):
    """The retained attempt is visible, but never claimed as a resolution.

    A same-field conflict keeps a partial resolution record on the check; the
    sign-off return and the prompt must say pm could *not* reconcile it, or
    the next step would assume the metadata was already handled.
    """
    rec = _status_conflict(w)
    assert rec["status"] == integration.CONFLICT
    assert rec["resolution"]["unresolved"]
    # A failed attempt has no delta to point at: naming a file that was never
    # written would send the next step to an empty path.
    assert not (rec.get("resolution") or {}).get("diff_path")
    assert not (w.croot / PR / "integration-resolution.diff").exists()
    head = rec["head"]
    pr = dict(pr_entry(w))
    ret = signoff.build_return_record(pr, SIGNOFF_IMPL, "impl",
                                      reviewed_head=head)
    pr["signoff_return"] = ret
    text = signoff.format_signoff_return(pr)
    assert "pm could not resolve the metadata conflict" in text
    assert "pm resolved the metadata conflict" not in text
    assert "changed differently on both sides" in text

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        prompt = prompt_gen.generate_signoff_prompt(data, PR)
    assert "NOT resolved" in prompt
    assert "changed differently on both sides" in prompt
    assert "Metadata conflict resolution (pm, by record id)" not in prompt
    assert "Resolution delta" not in prompt


def test_signoff_prompt_survives_a_null_resolved_from_head(w):
    """A record without the resolved-from revision must not crash the prompt."""
    rec = _metadata_conflict(w)

    def _blank(d):
        integ = store.get_pr(d, PR)["integration"]
        resolution = dict(integ["resolution"])
        resolution["resolved_from"] = {
            "head": None, "base_sha": rec["base_sha"],
            "merge_base": rec.get("merge_base")}
        integ["resolution"] = resolution
        integ["resolved_from"] = resolution["resolved_from"]
        integ["resolution_digest"] = integration._resolution_digest(resolution)
    store.locked_update(w.pm_dir, _blank)

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert "Applied to the PR branch" in text
    assert "<old head>" in text


def test_integrate_cli_prints_the_resolution(w):
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")

    head_before = git(w.wd, "rev-parse", "HEAD")
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(pr_mod.pr, ["signoff", "integrate", PR])
    assert r.exit_code == 0, r.output
    assert "resolved by record" in r.output
    assert "added from PR: pr-300" in r.output
    assert "added from base: pr-250" in r.output
    # R1/R8: the read-only check names the delta file and leaves it on disk,
    # without recording the check on the PR or touching the workdir.
    diff_path = w.croot / PR / "integration-resolution.diff"
    assert diff_path.is_file()
    assert f"resolution delta: {diff_path}" in r.output
    assert "resolved" in diff_path.read_text()
    assert "integration" not in store.get_pr(store.load(w.pm_dir), PR)
    assert git(w.wd, "rev-parse", "HEAD") == head_before
    assert git(w.wd, "status", "--porcelain") == ""

    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(
            pr_mod.pr, ["signoff", "integrate", PR, "--no-resolve"])
    assert r.exit_code != 0
    assert "CONFLICTS" in r.output


def test_integrate_cli_never_calls_a_failed_resolution_resolved(w):
    """A retained attempt is reported as attempted, never as resolved.

    The summary and the unresolved line already say the conflict stands; the
    per-path line must agree, or a person reading the output would believe the
    metadata was reconciled when the merge is still blocked.
    """
    rec = _status_conflict(w)
    assert rec["status"] == integration.CONFLICT
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(pr_mod.pr, ["signoff", "integrate", PR])
    assert r.exit_code != 0
    assert "attempted: pm/project.yaml (by record id — NOT resolved)" in r.output
    assert "\n  resolved: pm/project.yaml" not in r.output
    assert "unresolved: pm/project.yaml" in r.output


def test_a_carried_applied_resolution_is_not_labelled_a_failed_attempt(w):
    """A resolution carried from an earlier applied merge is not an attempt.

    ``integration._carry_forward`` keeps an applied resolution on a later
    ``conflict``/``error`` record so its provenance (and the explicit-reuse
    requirement) survives.  The current conflict is then somewhere else (here
    a code file), so the per-path line must not claim pm failed to reconcile
    ``project.yaml`` — that would contradict the summary and send the agent to
    hand-merge a file that is not conflicted.
    """
    rec = _metadata_conflict(w)
    applied = rec["resolution"]["applied_merge_sha"]
    # The branch and a new base commit now conflict on code, not metadata.
    commit(w.wd, "shared.txt", "pr\n", "branch edits shared")
    commit(w.repo, "shared.txt", "base\nmore\n", "base edits shared")

    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.CONFLICT
    assert again["conflicts"] == ["shared.txt"]
    # The applied resolution is carried forward ...
    assert again["resolution"]["applied_merge_sha"] == applied
    # ... but it is not a failed attempt at the current conflict.
    assert integration.unresolved_paths(again) == set()

    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(
            pr_mod.pr, ["signoff", "integrate", PR, "--record"])
    assert r.exit_code != 0
    assert "conflicts: shared.txt" in r.output
    assert "NOT resolved" not in r.output
    # The path line says the resolution was already applied, not that it is
    # this check's resolution of the current conflict.
    assert ("resolved earlier: pm/project.yaml (by record id — already "
            "applied)") in r.output

    # The sign-off prompt names the current conflict and qualifies the earlier
    # resolution instead of presenting it as this check's outcome.
    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert "Conflicting paths: `shared.txt`" in text
    assert "already applied" in text
    assert "**Metadata conflict resolution (pm, by record id):**" not in text

    # The return text the routed step reads must not claim pm resolved *this*
    # conflict either (the same honesty the prompt and the CLI carry).
    head = git(w.wd, "rev-parse", "HEAD")
    ret = signoff.build_return_record(
        pr_entry(w), signoff.SIGNOFF_IMPL, "impl", reviewed_head=head)
    text = signoff.format_signoff_return(dict(pr_entry(w), signoff_return=ret))
    assert "Conflicting paths: `shared.txt`" in text
    assert "pm resolved an *earlier* metadata conflict" in text
    assert "pm resolved the metadata conflict by record id" not in text
    assert "Reconcile it in this branch" in text


def test_a_carried_resolution_on_an_error_record_is_not_called_a_conflict(w):
    """An ``error`` record reports a failed check, not a conflict.

    ``_carry_forward`` keeps an applied resolution on a later ``error`` record
    too (a transient fetch failure must not drop the applied provenance).  The
    prompt and the return text then qualify it as an earlier resolution, but
    must name the *current* problem correctly — there is no conflict above.
    """
    rec = _metadata_conflict(w)
    assert rec["resolution"]["applied_merge_sha"]

    def _error(d):
        integ = store.get_pr(d, PR)["integration"]
        integ["status"] = integration.ERROR
        integ["error"] = "fetch master failed: boom"
        integ["conflicts"] = []
        integ.pop("candidate_tree", None)
    store.locked_update(w.pm_dir, _error)

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert "the failed check above is separate" in text
    assert "the conflict above is separate" not in text

    head = git(w.wd, "rev-parse", "HEAD")
    ret = signoff.build_return_record(
        pr_entry(w), signoff.SIGNOFF_IMPL, "impl", reviewed_head=head)
    text = signoff.format_signoff_return(dict(pr_entry(w), signoff_return=ret))
    assert "already applied; the failed check above is separate" in text
    assert "the conflict above is separate" not in text


def test_return_text_names_the_newest_base_the_branch_contains(w):
    """The return text's diff hint names the newest base, not the resolution's.

    A resolution applies base B1; a later bounce merges B2 into the branch.
    When a subsequent conflict routes the PR back, the return text must not
    point at ``git diff B1 HEAD`` — that lists B2's commits as the PR's own
    changes.
    """
    rec = _metadata_conflict(w)                      # applies base B1
    b1 = rec["base_sha"]
    commit(w.repo, "base_only.txt", "base\n", "base moves ahead")
    b2 = git(w.repo, "rev-parse", "HEAD")
    assert b2 != b1
    clean = integration.check_integration(w.pm_dir, PR)
    assert clean["status"] == integration.CLEAN, clean
    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(transcript, clean["head"], clean["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res
    assert pr_entry(w)["signoff_return"]["applied"]["base_sha"] == b2

    # The next base conflicts on code: the record carries the applied
    # resolution but this bounce applies nothing.
    commit(w.wd, "shared.txt", "pr\n", "branch edits shared")
    commit(w.repo, "shared.txt", "base\n", "base edits shared")
    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.CONFLICT
    assert again["resolution"]["applied_merge_sha"]

    head = git(w.wd, "rev-parse", "HEAD")
    ret = signoff.build_return_record(
        pr_entry(w), SIGNOFF_IMPL, "impl", reviewed_head=head)
    text = signoff.format_signoff_return(dict(pr_entry(w), signoff_return=ret))
    assert f"git diff {b2[:12]} HEAD" in text
    assert f"git diff {b1[:12]} HEAD" not in text


def test_integrate_cli_apply_applies_a_clean_recheck_of_a_resolved_check(w):
    """`--apply` still applies when the base moved to a clean merge."""
    head, base, tree = "b" * 40, "a" * 40, "c" * 40
    resolved = {"status": integration.RESOLVED, "head": head, "base_sha": base,
                "base_branch": "master", "target_repo": "repo",
                "candidate_tree": tree, "conflicts": ["pm/project.yaml"],
                "resolution": {"paths": [{"path": "pm/project.yaml"}]}}
    clean = dict(resolved, status=integration.CLEAN, resolution=None)
    applied = {}

    def fake_apply(root, pr_id, rec=None, **kw):
        applied["status"] = rec["status"]
        return "d" * 40, None

    with patch.object(integration, "check_integration",
                      return_value=dict(resolved)), \
         patch.object(integration, "prepare", return_value=dict(clean)), \
         patch.object(integration, "apply_integration", side_effect=fake_apply), \
         patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(
            pr_mod.pr, ["signoff", "integrate", PR, "--apply"])
    assert r.exit_code == 0, r.output
    assert applied == {"status": integration.CLEAN}


def test_integrate_cli_apply_applies_a_resolved_candidate(w):
    """`--apply` on a metadata-only conflict applies and records the merge."""
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    head = git(w.wd, "rev-parse", "HEAD")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")

    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(
            pr_mod.pr, ["signoff", "integrate", PR, "--apply"])
    assert r.exit_code == 0, r.output
    # The applied re-check reads "up to date", but the resolution that was
    # applied is still printed (and recorded).
    assert "resolved: pm/project.yaml (by record id)" in r.output
    assert "added from PR: pr-300" in r.output
    assert "added from base: pr-250" in r.output
    rec = pr_entry(w)["integration"]
    assert rec["status"] == integration.UP_TO_DATE
    assert rec["resolution"]["applied_merge_sha"]
    assert rec["resolution"]["applied_merge_sha"] != head
    assert git(w.wd, "rev-parse", "HEAD") == rec["resolution"]["applied_merge_sha"]
    assert git(w.wd, "rev-parse", "HEAD^{tree}") == rec["candidate_tree"]
    assert sorted(pr_ids(w.wd / "pm")) == [
        "pr-100", PR, "pr-250", "pr-300"]


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


# --- resolver safety rails the merge gate depends on ------------------------

def test_conflicting_reorders_are_refused():
    """Both sides reordering the same records differently is ambiguous."""
    base = ("project:\n  name: p\nprs:\n"
            "- id: pr-1\n  status: pending\n"
            "- id: pr-2\n  status: pending\n"
            "- id: pr-3\n  status: pending\n")
    ours = ("project:\n  name: p\nprs:\n"
            "- id: pr-2\n  status: pending\n"
            "- id: pr-1\n  status: pending\n"
            "- id: pr-3\n  status: pending\n")
    theirs = ("project:\n  name: p\nprs:\n"
              "- id: pr-3\n  status: pending\n"
              "- id: pr-2\n  status: pending\n"
              "- id: pr-1\n  status: pending\n")
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("reordered" in c for c in details["conflicts"])


def test_field_deletion_vs_edit_is_refused_and_one_sided_deletion_is_kept():
    """A scalar key is a field: never silently pick a side, but honour a
    deletion the other side left alone."""
    base = ("project:\n  name: p\n  skip_qa: true\n"
            "prs:\n- id: pr-1\n  status: pending\n")
    ours = "project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
    theirs = ("project:\n  name: p\n  skip_qa: false\n"
              "prs:\n- id: pr-1\n  status: pending\n")

    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("skip_qa" in c and "deleted" in c
               for c in details["conflicts"])
    # The other direction is symmetric, and names the same conflict.
    merged, details = integration.resolve_project_yaml(base, theirs, ours)
    assert merged is None
    assert any("skip_qa" in c and "deleted on the new base" in c
               for c in details["conflicts"])
    # Deleting a field the other side did not touch is the PR's change.
    merged, details = integration.resolve_project_yaml(base, ours, base)
    assert merged is not None, details
    assert "skip_qa" not in merged


def test_invalid_merged_shape_is_refused():
    """A merge that produces an invalid project.yaml is not a resolution."""
    base = "project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
    ours = base.rstrip() + "\n- id: pr-2\n  status: not-a-status\n"
    theirs = base.rstrip() + "\n- id: pr-3\n  status: pending\n"
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("invalid status" in c for c in details["conflicts"])

    # A plan cycle that both sides carry is likewise not mergeable.
    base = ("project:\n  name: p\n"
            "prs:\n- id: pr-1\n  status: pending\n"
            "plans:\n"
            "- id: plan-a\n  status: active\n  parent: plan-b\n"
            "- id: plan-b\n  status: active\n  parent: plan-a\n")
    ours = base.replace(
        "- id: pr-1\n  status: pending\n",
        "- id: pr-1\n  status: pending\n- id: pr-2\n  status: pending\n")
    theirs = base.replace(
        "- id: pr-1\n  status: pending\n",
        "- id: pr-1\n  status: pending\n- id: pr-3\n  status: pending\n")
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("cycle" in c for c in details["conflicts"])


def test_nested_duplicate_ids_are_ambiguous():
    """A duplicate id inside a nested list (notes) is a conflict too."""
    base = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
            "  notes:\n  - id: note-1\n    text: a\n")
    ours = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
            "  notes:\n  - id: note-1\n    text: a\n"
            "  - id: note-1\n    text: dup\n")
    theirs = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
              "  notes:\n  - id: note-1\n    text: a\n"
              "  - id: note-2\n    text: b\n")
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("duplicate record id" in c for c in details["conflicts"])


def test_nested_duplicate_ids_are_refused_even_when_taken_wholesale():
    """A nested duplicate is refused even when the list is not merged.

    Both sides carrying the same duplicated note id, or one side adding such
    a list unchanged, would otherwise carry the ambiguity into the merged
    document unnoticed.  It must be refused like a top-level duplicate.
    """
    base = "project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
    dup = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
           "  notes:\n  - id: note-1\n    text: a\n"
           "  - id: note-1\n    text: a\n")
    # Identical on both sides; the file only conflicts on an unrelated PR.
    merged, details = integration.resolve_project_yaml(
        base, dup, dup + "- id: pr-9\n  status: pending\n")
    assert merged is None
    assert any("duplicate record id" in c for c in details["conflicts"])
    # Added by one side only (the other side has no notes).
    merged, details = integration.resolve_project_yaml(base, dup, base)
    assert merged is None
    assert any("duplicate record id" in c for c in details["conflicts"])


@pytest.mark.parametrize("base,ours,theirs,needle", [
    # A status that is a list/dict cannot be a set member: it must read as an
    # invalid status, not raise (the resolver's contract is a refusal).
    ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n",
     "project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
     "- id: pr-2\n  status: {a: b}\n",
     "project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n",
     "invalid status"),
    ("project:\n  name: p\nplans:\n- id: plan-1\n  status: draft\n",
     "project:\n  name: p\nplans:\n- id: plan-1\n  status: [a]\n",
     "project:\n  name: p\nplans:\n- id: plan-1\n  status: draft\n",
     "invalid status"),
    # A plan parent that is not a string is refused, not walked as a key.
    ("project:\n  name: p\nplans:\n- id: plan-1\n  status: draft\n",
     "project:\n  name: p\nplans:\n- id: plan-1\n  status: draft\n"
     "  parent: {x: 1}\n",
     "project:\n  name: p\nplans:\n- id: plan-1\n  status: draft\n",
     "invalid parent"),
    # A one-sided change to a non-mapping ``project`` must be refused before
    # the serializer reads ``project.libyaml``.
    ("project:\n  name: p\nprs: []\n",
     "project: oops\nprs: []\n",
     "project:\n  name: p\nprs: []\n",
     "project is not a mapping"),
    ("project:\n  name: p\nprs: []\n",
     "project:\n  name: p\nprs: []\n",
     "project:\n- a\n- b\nprs: []\n",
     "project is not a mapping"),
])
def test_malformed_documents_are_refused_not_raised(base, ours, theirs,
                                                    needle):
    """Malformed sides are a readable conflict, never an uncaught error."""
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None, details
    assert any(needle in c for c in details.get("conflicts") or []), details


def test_a_malformed_base_entry_does_not_drop_the_behaviour_summary(w):
    """A malformed record on the base must not suppress the base summary.

    ``compute_candidate`` swallows a summary failure into a log warning, so a
    raise here would silently drop the behaviour changes the sign-off agent
    has to assess (and, with them, the justification requirement).
    """
    path = w.base_pm / "project.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["project"]["model_config"] = {"review": "opus"}
    doc["prs"].append({"id": {"not": "a string"}, "status": "pending"})
    path.chmod(0o644)
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base malformed entry")

    rec = integration.check_integration(w.pm_dir, PR)
    assert rec.get("base_behavior_error") is None, rec
    assert any("model_config" in c for c in rec["base_behavior_changes"]), rec


def test_bookkeeping_timestamps_both_bumped_do_not_block_the_merge():
    """Real ``pm pr note add`` bumps ``updated_at`` on both sides.

    The timestamps are bookkeeping, not semantics: the record must still
    merge by id (the earlier value is not a lost change).
    """
    base = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
            "  updated_at: '2026-01-01T00:00:00Z'\n")
    ours = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
            "  updated_at: '2026-01-02T00:00:00Z'\n"
            "  notes:\n  - id: note-1\n    text: from branch\n")
    theirs = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: merged\n"
              "  updated_at: '2026-01-03T00:00:00Z'\n"
              "  notes:\n  - id: note-2\n    text: from base\n")
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is not None, details
    doc = yaml.safe_load(merged)
    rec = doc["prs"][0]
    assert rec["status"] == "merged"
    # The later bookkeeping value wins; both notes survive.
    assert rec["updated_at"] == "2026-01-03T00:00:00Z"
    assert [n["id"] for n in rec["notes"]] == ["note-1", "note-2"]


def test_bookkeeping_timestamp_merge_does_not_mask_a_real_conflict():
    """A field both sides changed differently is still a conflict."""
    base = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
            "  updated_at: '2026-01-01T00:00:00Z'\n")
    ours = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: qa\n"
            "  updated_at: '2026-01-02T00:00:00Z'\n")
    theirs = ("project:\n  name: p\nprs:\n- id: pr-1\n  status: merged\n"
              "  updated_at: '2026-01-03T00:00:00Z'\n")
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("status" in c and "changed differently" in c
               for c in details["conflicts"])


def test_a_non_string_bookkeeping_value_keeps_the_conflict_rule():
    """Only real timestamps are bookkeeping; a malformed value is a conflict."""
    base = "project:\n  name: p\nprs:\n- id: pr-1\n  updated_at: '2026-01-01'\n"
    ours = "project:\n  name: p\nprs:\n- id: pr-1\n  updated_at: {bad: 1}\n"
    theirs = "project:\n  name: p\nprs:\n- id: pr-1\n  updated_at: '2026-01-03'\n"
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("updated_at" in c for c in details["conflicts"])


def test_a_merge_that_loses_a_side_change_is_refused(monkeypatch):
    """The preservation check is the safety net under the merge rules.

    Force the merge to silently drop the PR branch's edit: the resolution
    must fail rather than publish a candidate that lost it.
    """
    base = "project:\n  name: p\nprs:\n- id: pr-1\n  status: pending\n"
    ours = base.replace("name: p", "name: ours")
    theirs = base.rstrip() + "\n- id: pr-2\n  status: pending\n"
    real = integration._merge_value

    def lossy(b, o, t, path, actions):
        value, conflicts = real(b, o, t, path, actions)
        if path == "project":
            return b, []        # pretend the PR branch's edit vanished
        return value, conflicts

    monkeypatch.setattr(integration, "_merge_value", lossy)
    merged, details = integration.resolve_project_yaml(base, ours, theirs)
    assert merged is None
    assert any("PR branch change not preserved" in c
               for c in details["conflicts"])


# --- apply / merge-gate guards ---------------------------------------------

def test_apply_refuses_a_non_deterministic_resolution(w):
    """The applied merge must reproduce the candidate exactly.

    A re-resolution whose blob differs from the recorded one (e.g. a resolver
    change, or a base that moved under the check) is refused and the workdir
    is left untouched.
    """
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    head = git(w.wd, "rev-parse", "HEAD")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")

    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED
    entry = dict(rec["resolution"]["paths"][0])
    entry["blob"] = "0" * 40
    tampered = dict(rec, resolution=dict(rec["resolution"], paths=[entry]))
    merged, err = integration.apply_integration(w.pm_dir, PR, tampered)
    assert merged is None and "not deterministic" in err
    assert git(w.wd, "rev-parse", "HEAD") == head
    assert git(w.wd, "status", "--porcelain") == ""
    assert "pr-250" not in (w.wd / "pm" / "project.yaml").read_text()


def test_apply_refuses_a_clean_merge_with_another_candidate_tree(w):
    """Even a conflict-free merge must reproduce the recorded candidate."""
    head = git(w.wd, "rev-parse", "HEAD")
    base = git(w.repo, "rev-parse", "master")
    record = {"status": integration.RESOLVED, "head": head, "base_sha": base,
              "candidate_tree": "0" * 40,
              "resolution": {"paths": [{"path": "pm/project.yaml"}]}}
    # Already up to date: nothing to undo, but the tree is not the candidate.
    merged, err = integration._apply_resolution(
        record, str(w.wd), head, base, "Integrate master")
    assert merged is None and "different tree" in err
    assert git(w.wd, "rev-parse", "HEAD") == head

    # A real (clean) merge is aborted when its tree is not the candidate.
    commit(w.repo, "base.txt", "base\n", "base moves ahead")
    git(w.wd, "fetch", "-q", "origin")
    base = git(w.wd, "rev-parse", "origin/master")
    merged, err = integration._apply_resolution(
        dict(record, base_sha=base), str(w.wd), head, base, "Integrate master")
    assert merged is None and "different tree" in err
    assert git(w.wd, "rev-parse", "HEAD") == head
    assert git(w.wd, "status", "--porcelain") == ""


def test_apply_refuses_a_resolved_merge_with_another_candidate_tree(w):
    """The re-applied resolution must reproduce the recorded candidate."""
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    head = git(w.wd, "rev-parse", "HEAD")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED

    merged, err = integration.apply_integration(
        w.pm_dir, PR, dict(rec, candidate_tree="0" * 40))
    assert merged is None and "different tree" in err
    assert git(w.wd, "rev-parse", "HEAD") == head
    assert git(w.wd, "status", "--porcelain") == ""


def test_apply_refuses_conflicts_outside_the_recorded_resolution(w):
    """The apply step never makes a new substantive conflict resolution."""
    commit(w.wd, "shared.txt", "pr\n", "pr edits shared")
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    commit(w.repo, "shared.txt", "base\nmore\n", "base edits shared")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")

    head = git(w.wd, "rev-parse", "HEAD")
    # The workdir must know the base commit (a sign-off check fetches it).
    git(w.wd, "fetch", "-q", "origin")
    base = git(w.wd, "rev-parse", "origin/master")
    record = {"status": integration.RESOLVED, "head": head, "base_sha": base,
              "base_branch": "master", "candidate_tree": "0" * 40,
              "resolution": {"paths": [{"path": "pm/project.yaml"}]}}
    merged, err = integration.apply_integration(w.pm_dir, PR, record)
    assert merged is None
    assert "unexpected conflict in shared.txt" in err
    assert git(w.wd, "rev-parse", "HEAD") == head
    assert git(w.wd, "status", "--porcelain") == ""


def test_apply_refuses_when_head_moved_under_the_resolution(w):
    """HEAD is re-verified immediately before touching the worktree."""
    head = git(w.wd, "rev-parse", "HEAD")
    base = git(w.repo, "rev-parse", "master")
    record = {"status": integration.RESOLVED, "head": "0" * 40,
              "base_sha": base, "candidate_tree": "0" * 40,
              "resolution": {"paths": []}}
    merged, err = integration._apply_resolution(
        record, str(w.wd), "0" * 40, base, "Integrate master")
    assert merged is None and "HEAD moved" in err
    assert git(w.wd, "rev-parse", "HEAD") == head


def test_apply_refuses_a_record_without_a_base_revision(w):
    """A partial record is refused, not crashed on.

    ``apply_integration`` runs unattended at sign-off launch and from
    ``--apply``; both promise a reason on failure, so a record that cannot
    name the base to merge must come back as an error, not a traceback.
    """
    head = git(w.wd, "rev-parse", "HEAD")
    merged, err = integration.apply_integration(
        w.pm_dir, PR, {"status": integration.CLEAN, "head": head})
    assert merged is None and "no base revision" in err
    assert git(w.wd, "rev-parse", "HEAD") == head
    assert git(w.wd, "status", "--porcelain") == ""


def test_effective_verdict_coerces_an_unresolved_resolved_merge():
    """A RESOLVED record that still carries unresolved entries is not safe."""
    head = "a" * 40
    rec = {"status": integration.RESOLVED, "head": head,
           "base_sha": "b" * 40, "candidate_tree": "c" * 40,
           "resolution": {"paths": [], "unresolved": [
               {"path": "pm/project.yaml", "conflicts": ["pr-1.status"]}]}}
    verdict, why = signoff.effective_verdict(SIGNOFF_MERGE, rec, head)
    assert verdict == SIGNOFF_IMPL and "could not resolve" in why
    assert signoff.effective_verdict(SIGNOFF_REVIEW, rec, head)[0] == \
        SIGNOFF_IMPL
    # BLOCKED/IMPL pass through: only the forward routes are coerced.
    assert signoff.effective_verdict(SIGNOFF_IMPL, rec, head) == \
        (SIGNOFF_IMPL, None)


def test_compute_candidate_never_approves_a_bare_tree(w, monkeypatch):
    """A tree without a conflict-free resolution record is not ``resolved``."""
    commit(w.repo, "base.txt", "base\n", "base moves ahead")
    head = git(w.wd, "rev-parse", "HEAD")
    base = git(w.repo, "rev-parse", "master")
    resolution = {"paths": [], "unresolved": [
        {"path": "pm/project.yaml", "conflicts": ["ambiguous record"]}]}
    monkeypatch.setattr(integration, "_git_version", lambda: (2, 30))
    monkeypatch.setattr(
        integration, "_worktree_merge",
        lambda *a, **k: ("f" * 40, ["pm/project.yaml"], None, resolution))
    rec = integration.compute_candidate(str(w.wd), head, base)
    assert rec["status"] == integration.CONFLICT
    assert rec["candidate_tree"] is None


def test_valid_for_rejects_an_unresolved_resolved_record():
    head, base, tree = "a" * 40, "b" * 40, "c" * 40
    ok = {"status": integration.RESOLVED, "head": head, "base_sha": base,
          "candidate_tree": tree, "resolution": {"paths": []}}
    assert integration.valid_for(ok, head)
    assert not integration.valid_for(
        dict(ok, resolution={"paths": [], "unresolved": [{"path": "x"}]}),
        head)
    assert not integration.valid_for(dict(ok, resolution=None), head)


def test_merge_gate_refuses_a_changed_resolution_digest(w):
    """A re-check that resolved differently invalidates the approval."""
    rec = _metadata_conflict(w)
    record_merge(w, rec)

    def _tamper(d):
        integ = store.get_pr(d, PR)["integration"]
        resolution = dict(integ["resolution"], applied_merge_sha="f" * 40)
        integ["resolution"] = resolution
        integ["resolution_digest"] = integration._resolution_digest(resolution)
    store.locked_update(w.pm_dir, _tamper)
    refusal = signoff.merge_gate_refusal(
        pr_entry(w), signoff.head_sha(str(w.wd)), "master")
    assert refusal and "metadata resolution changed" in refusal


def test_merge_gate_refuses_a_resolution_that_lost_its_digest(w):
    """A resolution edited without its digest is not the approved one."""
    rec = _metadata_conflict(w)
    record_merge(w, rec)

    def _tamper(d):
        store.get_pr(d, PR)["integration"]["resolution_digest"] = "0" * 64
    store.locked_update(w.pm_dir, _tamper)
    refusal = signoff.merge_gate_refusal(
        pr_entry(w), signoff.head_sha(str(w.wd)), "master")
    assert refusal and "does not match its digest" in refusal


def test_a_failed_recheck_keeps_the_applied_resolution(w, monkeypatch):
    """A transient check failure must not lose what was applied.

    The failed check cannot verify the candidate, so the merge is (rightly)
    blocked until a check succeeds again — but the recorded resolution stays
    bound, and the next successful check restores the approval.
    """
    rec = _metadata_conflict(w)
    record_merge(w, rec)

    real_fetch = integration.fetch_base
    monkeypatch.setattr(integration, "fetch_base",
                        lambda *a, **k: (None, "network down"))
    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.ERROR
    assert again["resolution"]["applied_merge_sha"] == \
        rec["resolution"]["applied_merge_sha"]
    assert again["resolution_digest"] == rec["resolution_digest"]

    # Only the fetch is restored; the fixture's environment stays patched.
    monkeypatch.setattr(integration, "fetch_base", real_fetch)
    ok = integration.check_integration(w.pm_dir, PR)
    assert ok["status"] == integration.UP_TO_DATE
    assert ok["candidate_tree"] == rec["candidate_tree"]
    refusal = signoff.merge_gate_refusal(pr_entry(w), ok["head"], "master")
    assert refusal is None, refusal


def test_behavior_changes_survive_a_benign_recheck(w):
    """An applied resolution's base interactions keep requiring a statement.

    After the apply the branch contains the base, so a re-check sees no base
    diff; the recorded behavioural changes must not silently disappear (that
    would let an unstated reuse pass the merge gate).
    """
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    data = store.load(w.base_pm)
    data["project"]["model_config"] = {"session_models": {"impl": "model-new"}}
    store.save(data, w.base_pm)
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records and model")

    rec = integration.prepare(w.pm_dir, PR)
    assert rec["status"] == integration.UP_TO_DATE
    assert rec["resolution"]["applied_merge_sha"]
    assert any("model_config" in c for c in rec["base_behavior_changes"])

    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.UP_TO_DATE
    assert any("model_config" in c for c in again["base_behavior_changes"])

    record_merge(w, again)
    assert signoff.merge_gate_refusal(
        pr_entry(w), again["head"], "master") is None
    # A report that no longer states the evidence re-blocks the merge.
    write_report(w, again, evidence=False)
    refusal = signoff.merge_gate_refusal(
        pr_entry(w), again["head"], "master")
    assert refusal and "evidence" in refusal


def test_a_failed_recheck_keeps_the_behavioural_changes(w, monkeypatch):
    """A clean base's behavioural changes survive a transient check failure.

    Without them the merge gate would no longer require the explicit
    evidence/checks statement the approval was asked for.
    """
    data = store.load(w.base_pm)
    data["project"]["model_config"] = {"session_models": {"impl": "model-new"}}
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base changes model")

    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    assert rec["base_behavior_changes"]
    record_merge(w, rec)

    monkeypatch.setattr(integration, "fetch_base",
                        lambda *a, **k: (None, "network down"))
    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.ERROR
    assert again["head"] == rec["head"]
    assert again["base_behavior_changes"] == rec["base_behavior_changes"]

    write_report(w, again, evidence=False)
    refusal = signoff.merge_gate_refusal(pr_entry(w), again["head"], "master")
    assert refusal and "behavioural changes" in refusal


def test_a_failed_recheck_keeps_a_failed_summary(w, monkeypatch):
    """A summary failure survives a transient re-check failure too.

    The failure is what makes the approval state its evidence; dropping it on
    a fetch error would let the next approval read as behaviour-neutral.
    """
    data = store.load(w.base_pm)
    data["project"]["model_config"] = {"session_models": {"impl": "model-new"}}
    store.save(data, w.base_pm)
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base changes model")

    def boom(*a, **k):
        raise RuntimeError("summary exploded")

    monkeypatch.setattr(integration, "base_behavior_changes", boom)
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["base_behavior_error"]
    record_merge(w, rec)

    monkeypatch.setattr(integration, "fetch_base",
                        lambda *a, **k: (None, "network down"))
    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.ERROR
    assert again["head"] == rec["head"]
    assert again["base_behavior_error"] == rec["base_behavior_error"]

    write_report(w, again, candidate=False, evidence=False, reason=False)
    refusal = signoff.merge_gate_refusal(pr_entry(w), again["head"], "master")
    assert refusal and "behavioural changes" in refusal


def test_an_applied_resolution_keeps_a_failed_behavior_summary(w, monkeypatch):
    """The post-apply re-check cannot re-summarise a base now inside HEAD.

    ``base_behavior_error`` is not an exemption: the merge gate requires the
    evidence statement for it.  Applying the resolution must carry it, or a
    resolved approval would silently need no statement at all — the re-check
    sees no base diff and produces neither changes nor an error.
    """
    def boom(*a, **k):
        raise RuntimeError("summary exploded")

    monkeypatch.setattr(integration, "base_behavior_changes", boom)
    rec = _metadata_conflict(w)
    assert rec["status"] == integration.UP_TO_DATE
    assert rec["resolution"]["applied_merge_sha"]
    assert "summary exploded" in (rec.get("base_behavior_error") or "")
    assert not rec.get("base_behavior_changes")

    # A benign re-check keeps it too (the record no longer has a base diff).
    again = integration.check_integration(w.pm_dir, PR)
    assert again["status"] == integration.UP_TO_DATE
    assert "summary exploded" in (again.get("base_behavior_error") or "")

    # Recording a MERGE without the statement is refused, exactly as for a
    # listed behavioural change.
    write_report(w, rec, evidence=False, reason=False)
    with patch.object(pr_mod, "state_root", return_value=w.pm_dir), \
         patch.object(pr_mod, "trigger_tui_refresh"):
        r = CliRunner().invoke(pr_mod.pr, ["signoff", "record", PR])
    assert r.exit_code != 0 and "pm-signoff-evidence" in r.output


def test_config_path_base_change_requires_justification(w):
    """Dependency/config files are behavioural too, not just project.yaml."""
    commit(w.repo, "pyproject.toml", "[project]\nname = 'p'\n",
           "base adds pyproject")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.CLEAN
    assert any("pyproject.toml" in c for c in rec["base_behavior_changes"])
    write_report(w, rec, evidence=False)
    problem = signoff.approval_justification_problem(
        PR, pr_entry(w)["integration"], rec["head"])
    assert problem and "evidence" in problem
    write_report(w, rec)
    assert signoff.approval_justification_problem(
        PR, pr_entry(w)["integration"], rec["head"]) is None


# --- the git >= 2.38 (merge-tree) path resolves through the worktree -------

def test_new_git_merge_tree_conflict_resolves_via_the_worktree(w, monkeypatch):
    """git >= 2.38 reports the conflict in memory; the resolution still runs
    in the isolated worktree and yields the same ``RESOLVED`` candidate."""
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    head = git(w.wd, "rev-parse", "HEAD")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    git(w.wd, "fetch", "-q", "origin")
    base = git(w.wd, "rev-parse", "origin/master")

    monkeypatch.setattr(integration, "_git_version", lambda: (2, 45))
    monkeypatch.setattr(integration, "_merge_tree",
                        lambda *a, **k: (None, ["pm/project.yaml"], None))
    rec = integration.compute_candidate(str(w.wd), head, base)
    assert rec["status"] == integration.RESOLVED, rec
    assert rec["candidate_tree"]
    assert rec["resolution"]["paths"][0]["path"] == "pm/project.yaml"
    assert not rec["resolution"]["unresolved"]
    # The check is read-only: the PR workdir's HEAD and records are untouched
    # (the base's pr-250 exists only in the isolated candidate).
    assert git(w.wd, "rev-parse", "HEAD") == head
    assert sorted(pr_ids(w.wd / "pm")) == ["pr-100", PR, "pr-300"]


def test_new_git_worktree_failure_is_a_conflict_with_provenance(w, monkeypatch):
    """A failed worktree resolution stays CONFLICT — never a bare tree."""
    commit(w.repo, "base.txt", "base\n", "base moves ahead")
    git(w.wd, "fetch", "-q", "origin")
    head = git(w.wd, "rev-parse", "HEAD")
    base = git(w.wd, "rev-parse", "origin/master")

    monkeypatch.setattr(integration, "_git_version", lambda: (2, 45))
    monkeypatch.setattr(integration, "_merge_tree",
                        lambda *a, **k: (None, ["pm/project.yaml"], None))
    monkeypatch.setattr(
        integration, "_worktree_merge",
        lambda *a, **k: (None, ["pm/project.yaml"],
                         "candidate worktree failed", None))
    rec = integration.compute_candidate(str(w.wd), head, base)
    assert rec["status"] == integration.CONFLICT
    assert rec["candidate_tree"] is None
    unresolved = rec["resolution"]["unresolved"]
    assert unresolved[0]["path"] == "pm/project.yaml"
    assert "candidate worktree failed" in unresolved[0]["conflicts"]


def test_new_git_non_metadata_conflict_is_never_resolved(w, monkeypatch):
    """Only a conflict confined to project.yaml triggers the worktree resolver."""
    commit(w.wd, "shared.txt", "pr\n", "pr edits shared")
    commit(w.repo, "shared.txt", "base\nmore\n", "base edits shared")
    git(w.wd, "fetch", "-q", "origin")
    head = git(w.wd, "rev-parse", "HEAD")
    base = git(w.wd, "rev-parse", "origin/master")
    called = []

    monkeypatch.setattr(integration, "_git_version", lambda: (2, 45))
    monkeypatch.setattr(integration, "_merge_tree",
                        lambda *a, **k: (None, ["shared.txt"], None))
    monkeypatch.setattr(
        integration, "_worktree_merge",
        lambda *a, **k: called.append(1) or (None, [], None, None))
    rec = integration.compute_candidate(str(w.wd), head, base)
    assert rec["status"] == integration.CONFLICT
    assert rec["resolution"] is None
    assert called == []


def test_a_bounce_that_applies_the_resolution_records_the_provenance(w):
    """A bounce can be the first successful apply (``prepare`` could not touch
    a dirty workdir).  The applied resolution must survive the next check, or
    the later approval would not need the explicit reuse statement."""
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    original_head = git(w.wd, "rev-parse", "HEAD")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED
    assert not rec["resolution"].get("applied_merge_sha")

    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(
        transcript, git(w.wd, "rev-parse", "HEAD"), rec["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res
    ret = pr_entry(w)["signoff_return"]
    applied_sha = ret["integration"]["resolution"]["applied_merge_sha"]
    assert applied_sha
    # The applied candidate is recorded on the PR, not only in the return.
    stored = pr_entry(w)["integration"]
    assert stored["status"] == integration.UP_TO_DATE
    assert stored["head"] == applied_sha
    assert stored["resolution"]["applied_merge_sha"] == applied_sha
    # The revisions the resolution combined stay visible at the top level,
    # where the evidence block and the prompt read them.
    assert stored["resolved_from"]["head"] == original_head
    assert stored["resolved_from"]["base_sha"] == rec["base_sha"]

    # The next sign-off check carries it forward instead of dropping it.
    again = integration.prepare(w.pm_dir, PR)
    assert again["status"] == integration.UP_TO_DATE
    assert again["resolution"]["applied_merge_sha"] == applied_sha
    assert again["resolution_digest"] == stored["resolution_digest"]
    # The explicit-reuse requirement still applies to an approval.
    assert signoff.approval_justification_problem(
        PR, pr_entry(w)["integration"], again["head"])


def test_a_bounce_that_applies_clears_a_stale_apply_error(w):
    """A successful bounce apply must not leave the old "not applied" claim.

    ``prepare`` at sign-off launch could not touch a dirty workdir, so the
    record carried ``apply_error``; the bounce then applied the resolution.
    The record must describe the applied merge, not the failed attempt.
    """
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    (w.wd / "keep.txt").write_text("uncommitted\n")

    rec = integration.prepare(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED
    assert rec.get("apply_error")

    # The workdir is clean again, so the bounce applies the resolution.
    (w.wd / "keep.txt").write_text("keep\n")
    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(
        transcript, git(w.wd, "rev-parse", "HEAD"), rec["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res
    stored = pr_entry(w)["integration"]
    assert stored["status"] == integration.UP_TO_DATE
    assert stored["resolution"]["applied_merge_sha"]
    assert "apply_error" not in stored


def test_a_bounce_keeps_the_provenance_when_a_check_recorded_the_merge(
        w, monkeypatch):
    """A concurrent check of the just-applied merge must not drop the
    resolution provenance.

    The window is between the apply and the bounce's record write: a check
    that reads the merge commit records a bare up-to-date record, and it
    cannot know about the apply (the record it carried from still said
    ``resolved``).  That record describes the same revision, so the bounce's
    record — same revision, with the provenance — must win; otherwise the
    applied resolution silently disappears and a later approval no longer
    needs the explicit-reuse statement.
    """
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED
    assert not rec["resolution"].get("applied_merge_sha")

    real_apply = integration.apply_integration

    def racing_apply(root, pr_id, record=None, **kw):
        merged, err = real_apply(root, pr_id, record, **kw)
        if merged:
            # Simulate a check that read the merge commit before this bounce
            # recorded the resolution.
            tree = git(w.wd, "rev-parse", "HEAD^{tree}")

            def _bare(d):
                p = store.get_pr(d, pr_id)
                p["integration"] = {
                    "head": merged, "status": integration.UP_TO_DATE,
                    "base_sha": (record or {}).get("base_sha"),
                    "candidate_tree": tree,
                }
            store.locked_update(root, _bare)
        return merged, err

    monkeypatch.setattr(integration, "apply_integration", racing_apply)
    transcript = signoff.signoff_transcript(w.tdir, PR)
    signoff.stamp_signoff_launch(
        transcript, git(w.wd, "rev-parse", "HEAD"), rec["base_sha"])
    res = signoff.step_signoff(
        w.pm_dir, pr_entry(w), session="s", tdir=w.tdir,
        read_verdict=lambda t, p: SIGNOFF_REVIEW,
        window_pane=lambda s, p: "%1", retire=lambda *a: None)
    assert res.hop == "review", res

    stored = pr_entry(w)["integration"]
    applied = stored["resolution"]["applied_merge_sha"]
    assert stored["status"] == integration.UP_TO_DATE
    assert stored["head"] == applied
    assert stored["resolution_digest"]
    # The next sign-off check carries it forward and still demands reuse.
    again = integration.prepare(w.pm_dir, PR)
    assert again["resolution"]["applied_merge_sha"] == applied
    assert signoff.approval_justification_problem(
        PR, pr_entry(w)["integration"], again["head"])


def test_a_bounce_does_not_overwrite_a_check_of_another_revision(w):
    """The same-revision exception is narrow: any other record wins."""
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")
    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED

    other = "c" * 40

    def _other(d):
        p = store.get_pr(d, PR)
        p["integration"] = {"head": other, "status": integration.UP_TO_DATE,
                            "candidate_tree": "d" * 40}
    store.locked_update(w.pm_dir, _other)
    signoff._record_applied_integration(
        w.pm_dir, PR, rec, rec["head"], "e" * 40)
    assert pr_entry(w)["integration"]["head"] == other


def test_the_prompt_says_a_resolution_was_not_applied(w):
    """A resolved candidate that pm has not applied must say so.

    ``pm pr signoff integrate --record`` resolves the conflict in the isolated
    candidate but applies nothing, so the record carries a resolution with no
    ``applied_merge_sha`` and no ``apply_error``.  The prompt must not read as
    if the branch were already integrated: a MERGE is blocked until it is.
    """
    append_records(w.wd / "pm", w.repo, ["pr-300"])
    git(w.wd, "add", ".")
    git(w.wd, "commit", "-q", "-m", "feature records")
    append_records(w.base_pm, w.repo, ["pr-250"], status="merged")
    git(w.repo, "add", ".")
    git(w.repo, "commit", "-q", "-m", "base records")

    rec = integration.check_integration(w.pm_dir, PR)
    assert rec["status"] == integration.RESOLVED
    assert not rec["resolution"].get("applied_merge_sha")
    assert not rec.get("apply_error")

    data = store.load(w.pm_dir)
    with patch("pm_core.prompt_gen.store.find_project_root",
               side_effect=FileNotFoundError):
        text = prompt_gen.generate_signoff_prompt(data, PR)
    assert "**Not applied**" in text
    assert "has not been applied yet" in text
    assert "Applied to the PR branch as" not in text
