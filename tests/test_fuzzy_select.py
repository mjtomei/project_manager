"""Tests for fuzzy matching and ranked selection."""

from pm_core.tui.fuzzy_select import score_pr, score_plan, fuzzy_match_prs, fuzzy_match_plans


def _make_pr(pr_id, title="", description="", plan="", gh_pr_number=None):
    pr = {"id": pr_id, "title": title, "description": description}
    if plan:
        pr["plan"] = plan
    if gh_pr_number is not None:
        pr["gh_pr_number"] = gh_pr_number
    return pr


def _make_plan(plan_id, name=""):
    return {"id": plan_id, "name": name}


class TestScorePr:
    def test_exact_id_match(self):
        pr = _make_pr("pr-942aa21", title="Add spec runner")
        assert score_pr(pr, "pr-942aa21", {}) == 1000

    def test_display_id_match(self):
        pr = _make_pr("pr-001", gh_pr_number=125)
        assert score_pr(pr, "#125", {}) == 1000

    def test_id_prefix(self):
        pr = _make_pr("pr-942aa21", title="Something")
        score = score_pr(pr, "pr-942", {})
        assert score == 500

    def test_title_substring(self):
        pr = _make_pr("pr-001", title="Add spec runner")
        score = score_pr(pr, "spec", {})
        assert score == 200

    def test_description_substring(self):
        pr = _make_pr("pr-001", description="Implements the spec runner feature")
        score = score_pr(pr, "spec", {})
        assert score == 100

    def test_plan_name_substring(self):
        pr = _make_pr("pr-001", plan="plan-001")
        plan_map = {"plan-001": {"name": "Watchers and observers"}}
        score = score_pr(pr, "watch", plan_map)
        assert score == 50

    def test_multiple_fields_combine(self):
        pr = _make_pr("pr-001", title="Add spec runner", description="spec implementation")
        score = score_pr(pr, "spec", {})
        # title (200) + description (100) = 300
        assert score == 300

    def test_no_match(self):
        pr = _make_pr("pr-001", title="Something else")
        assert score_pr(pr, "zzzzz", {}) == 0

    def test_case_insensitive(self):
        pr = _make_pr("pr-001", title="Add Spec Runner")
        assert score_pr(pr, "spec", {}) > 0
        assert score_pr(pr, "SPEC", {}) > 0


class TestScorePlan:
    def test_exact_id(self):
        plan = _make_plan("plan-001", "Watchers")
        assert score_plan(plan, "plan-001") == 1000

    def test_id_prefix(self):
        plan = _make_plan("plan-001", "Watchers")
        assert score_plan(plan, "plan-0") == 500

    def test_name_substring(self):
        plan = _make_plan("plan-001", "Watchers and observers")
        assert score_plan(plan, "watch") == 200

    def test_no_match(self):
        plan = _make_plan("plan-001", "Watchers")
        assert score_plan(plan, "zzz") == 0


class TestFuzzyMatchPrs:
    def test_basic_ranking(self):
        prs = [
            _make_pr("pr-001", title="First PR"),
            _make_pr("pr-942aa21", title="Add spec runner"),
            _make_pr("pr-003", title="Spec utilities", description="spec helpers"),
        ]
        results = fuzzy_match_prs(prs, "spec", {})
        # pr-003 has title+description match (300), pr-942aa21 has title match (200)
        assert len(results) == 2
        assert results[0]["id"] == "pr-003"
        assert results[1]["id"] == "pr-942aa21"

    def test_exact_id_wins(self):
        prs = [
            _make_pr("pr-001", title="spec related"),
            _make_pr("pr-942aa21", title="Add spec runner"),
        ]
        results = fuzzy_match_prs(prs, "pr-942aa21", {})
        assert results[0]["id"] == "pr-942aa21"

    def test_cursor_proximity_tiebreak(self):
        prs = [
            _make_pr("pr-001", title="Fix bug A"),
            _make_pr("pr-002", title="Fix bug B"),
            _make_pr("pr-003", title="Fix bug C"),
        ]
        # All match "Fix bug" with same score (200); cursor at index 2
        results = fuzzy_match_prs(prs, "Fix bug", {}, cursor_index=2)
        assert results[0]["id"] == "pr-003"  # closest to cursor

    def test_empty_results(self):
        prs = [_make_pr("pr-001", title="Something")]
        results = fuzzy_match_prs(prs, "zzzzz", {})
        assert results == []

    def test_display_id_match(self):
        prs = [
            _make_pr("pr-001", title="First", gh_pr_number=125),
            _make_pr("pr-002", title="Second", gh_pr_number=200),
        ]
        results = fuzzy_match_prs(prs, "#125", {})
        assert len(results) == 1
        assert results[0]["id"] == "pr-001"

    def test_plan_name_match(self):
        prs = [
            _make_pr("pr-001", title="First", plan="plan-001"),
            _make_pr("pr-002", title="Second"),
        ]
        plan_map = {"plan-001": {"name": "Watchers"}}
        results = fuzzy_match_prs(prs, "watch", plan_map)
        assert len(results) == 1
        assert results[0]["id"] == "pr-001"


class TestFuzzyMatchPlans:
    def test_basic_ranking(self):
        plans = [
            _make_plan("plan-001", "TUI improvements"),
            _make_plan("plan-002", "Watchers and observers"),
        ]
        results = fuzzy_match_plans(plans, "watch")
        assert len(results) == 1
        assert results[0]["id"] == "plan-002"

    def test_exact_id_wins(self):
        plans = [
            _make_plan("plan-001", "Something with plan-002 reference"),
            _make_plan("plan-002", "Watchers"),
        ]
        results = fuzzy_match_plans(plans, "plan-002")
        assert results[0]["id"] == "plan-002"

    def test_empty_results(self):
        plans = [_make_plan("plan-001", "Watchers")]
        results = fuzzy_match_plans(plans, "zzz")
        assert results == []
