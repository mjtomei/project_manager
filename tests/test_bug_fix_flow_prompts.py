"""Tests for the bug-fix flow prompt injections in pm_core/prompt_gen.py."""

from pm_core import prompt_gen


def _data(pr: dict, plans=None) -> dict:
    return {
        "project": {"base_branch": "master", "backend": "github"},
        "prs": [pr],
        "plans": plans or [],
    }


def test_is_bug_pr_detects_plan_bugs():
    assert prompt_gen._is_bug_pr({"plan": "bugs"})


def test_is_bug_pr_detects_type_bug():
    assert prompt_gen._is_bug_pr({"type": "bug"})


def test_is_bug_pr_false_for_feature():
    assert not prompt_gen._is_bug_pr({"plan": "feature-x"})
    assert not prompt_gen._is_bug_pr({})


def test_impl_prompt_includes_bug_fix_flow_for_bug_pr():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken"})
    p = prompt_gen.generate_prompt(data, "pr-x")
    assert "Bug Fix Flow" in p
    assert "Manual repro" in p
    assert "Write a failing test" in p
    assert "Verify with the test" in p
    assert "Verify manually" in p


def test_impl_prompt_omits_bug_flow_for_feature_pr():
    data = _data({"id": "pr-y", "title": "Feature", "description": "do it"})
    p = prompt_gen.generate_prompt(data, "pr-y")
    assert "Bug Fix Flow" not in p


def test_review_prompt_includes_bug_checklist_for_bug_pr():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken"})
    r = prompt_gen.generate_review_prompt(data, "pr-x")
    assert "Bug Fix Review Checklist" in r
    assert "manual-repro captures exist" in r


def test_review_prompt_omits_bug_checklist_for_feature_pr():
    data = _data({"id": "pr-y", "title": "Feature", "description": "do it"})
    r = prompt_gen.generate_review_prompt(data, "pr-y")
    assert "Bug Fix Review Checklist" not in r


def test_review_loop_prompt_inherits_bug_checklist():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken"})
    r = prompt_gen.generate_review_prompt(data, "pr-x", review_loop=True,
                                          review_iteration=1, review_loop_id="abcd")
    assert "Bug Fix Review Checklist" in r
    assert "Review Loop Mode" in r


def test_type_bug_field_also_triggers_flow():
    data = _data({"id": "pr-z", "title": "Bug2", "type": "bug",
                  "description": "broken"})
    p = prompt_gen.generate_prompt(data, "pr-z")
    assert "Bug Fix Flow" in p


def test_bug_flow_includes_pre_fix_repro_gate():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken"})
    p = prompt_gen.generate_prompt(data, "pr-x")
    assert "Manual repro on pre-fix code" in p


def test_bug_flow_warns_against_theory_only_repros():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken"})
    p = prompt_gen.generate_prompt(data, "pr-x")
    assert "not a theory" in p


def test_bug_flow_points_at_qa_dirs():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken"})
    p = prompt_gen.generate_prompt(data, "pr-x")
    assert "pm/qa/instructions/" in p
    assert "pm/qa/artifacts/" in p
    assert "pm/qa/captures/" in p


def test_bug_review_points_at_captures_dir():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken"})
    r = prompt_gen.generate_review_prompt(data, "pr-x")
    assert "pm/qa/captures/pr-x/impl/" in r
    assert "Pre-fix and post-fix" in r


def test_bug_flow_uses_gh_pr_number_for_captures_dir():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken", "gh_pr_number": 190})
    p = prompt_gen.generate_prompt(data, "pr-x")
    assert "pm/qa/captures/pr-190/impl/pre-fix/" in p
    assert "pm/qa/captures/pr-190/impl/post-fix/" in p
    # Must not leak the local id where the segment now applies
    assert "pm/qa/captures/pr-x/" not in p


def test_bug_review_uses_gh_pr_number_for_captures_dir():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken", "gh_pr_number": 190})
    r = prompt_gen.generate_review_prompt(data, "pr-x")
    assert "pm/qa/captures/pr-190/impl/" in r
    assert "pm/qa/captures/pr-x/" not in r
