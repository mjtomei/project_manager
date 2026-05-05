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
    assert "Reproduce" in p
    assert "Reconcile" in p
    assert "confirmed-overlap" in p


def test_impl_prompt_omits_bug_flow_for_feature_pr():
    data = _data({"id": "pr-y", "title": "Feature", "description": "do it"})
    p = prompt_gen.generate_prompt(data, "pr-y")
    assert "Bug Fix Flow" not in p


def test_review_prompt_includes_bug_checklist_for_bug_pr():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken"})
    r = prompt_gen.generate_review_prompt(data, "pr-x")
    assert "Bug Fix Review Checklist" in r
    assert "Reproduction artifact exists" in r


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
    assert "Confirm on pre-fix code" in p
    assert "git stash" in p


def test_bug_flow_warns_against_theory_only_repros():
    data = _data({"id": "pr-x", "title": "Bug", "plan": "bugs",
                  "description": "broken"})
    p = prompt_gen.generate_prompt(data, "pr-x")
    assert "not a theory" in p or "not a theory about what's wrong" in p
