"""Tests for fuzzy matching and ranked selection."""

from pm_core.tui.fuzzy_select import (
    fuzzy_match_plans, fuzzy_match_prs, is_exact_pr_match, score_plan, score_pr,
)


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

    def test_bare_hash_is_exact(self):
        # Notes and commits quote a PR by its hash alone.
        pr = _make_pr("pr-942aa21", title="Something")
        assert is_exact_pr_match(pr, "942aa21")
        assert score_pr(pr, "942aa21", {}) == 1000

    def test_bare_hash_prefix(self):
        pr = _make_pr("pr-942aa21", title="Something")
        assert score_pr(pr, "942a", {}) == 500

    def test_short_bare_hash_is_not_an_id_prefix(self):
        # One- and two-character queries keep matching titles, not every PR
        # whose hash happens to start with them.
        pr = _make_pr("pr-942aa21", title="Something")
        assert score_pr(pr, "942", {}) == 0

    def test_legacy_numeric_id_has_no_hash_alias(self):
        # ``pr-001`` is a whole id, not a hash; only the raw id matches.
        pr = _make_pr("pr-001", title="Something")
        assert not is_exact_pr_match(pr, "001")
        assert score_pr(pr, "001", {}) == 0
        assert score_pr(pr, "pr-001", {}) == 1000

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


# ---------------------------------------------------------------------------
# Exact-id parity, robustness, tree-order tie-break, shared status-filter
# predicate.
# ---------------------------------------------------------------------------


class TestExactIdParity:
    """Queries that ``_resolve_pr_id`` resolves exactly stay exact."""

    def test_bare_number_is_exact_gh_match(self):
        pr = _make_pr("pr-001", gh_pr_number=136)
        assert is_exact_pr_match(pr, "136")
        assert score_pr(pr, "136", {}) == 1000

    def test_bare_number_is_not_a_display_prefix(self):
        pr = _make_pr("pr-001", gh_pr_number=136)
        assert score_pr(pr, "13", {}) == 0
        assert score_pr(pr, "#13", {}) == 500

    def test_raw_id_case_insensitive_exact(self):
        assert score_pr(_make_pr("pr-942aa21"), "PR-942AA21", {}) == 1000

    def test_exact_always_beats_every_non_exact_combination(self):
        named = _make_pr("pr-942aa21")
        mentions = _make_pr("pr-942aa21x", title="pr-942aa21",
                            description="see pr-942aa21", plan="pr-942aa21")
        plan_map = {"pr-942aa21": {"name": "pr-942aa21"}}
        assert score_pr(mentions, "pr-942aa21", plan_map) == 850
        ranked = fuzzy_match_prs([mentions, named], "pr-942aa21", plan_map)
        assert ranked[0]["id"] == "pr-942aa21"

    def test_bare_hash_beats_a_description_mention(self):
        # ``pr select 5f30bdf`` must not land on a PR that merely mentions
        # pr-5f30bdf in its description.
        named = _make_pr("pr-5f30bdf", title="Hardening")
        mentions = _make_pr("pr-3199f44", title="TUI at Textual 2.x",
                            description="regression from pr-5f30bdf")
        ranked = fuzzy_match_prs([mentions, named], "5f30bdf", {},
                                 cursor_index=0, positions={"pr-3199f44": 0})
        assert [p["id"] for p in ranked] == ["pr-5f30bdf", "pr-3199f44"]

    def test_resolve_pr_id_agreement(self):
        from pm_core.cli.helpers import _resolve_pr_id
        prs = [_make_pr("pr-a", title="136 things"),
               _make_pr("pr-b", gh_pr_number=136),
               _make_pr("pr-c", description="#136")]
        data = {"prs": prs}
        for q in ("136", "#136", "pr-b"):
            assert fuzzy_match_prs(prs, q, {})[0]["id"] == \
                _resolve_pr_id(data, q)["id"]

    def test_duplicate_gh_number_both_exact(self):
        prs = [_make_pr("pr-a", gh_pr_number=7), _make_pr("pr-b", gh_pr_number=7)]
        ranked = fuzzy_match_prs(prs, "#7", {}, cursor_index=5,
                                 positions={"pr-a": 0, "pr-b": 4})
        assert [p["id"] for p in ranked] == ["pr-b", "pr-a"]


class TestRobustness:
    def test_none_fields(self):
        pr = {"id": "pr-001", "title": None, "description": None,
              "plan": None, "gh_pr_number": None}
        assert score_pr(pr, "x", {}) == 0
        assert score_pr(pr, "pr-0", {}) == 500

    def test_plan_with_none_name(self):
        pr = _make_pr("pr-001", plan="bugs")
        assert score_pr(pr, "bug", {"bugs": {"id": "bugs", "name": None}}) == 50
        assert score_plan({"id": "bugs", "name": None}, "bug") == 500

    def test_empty_or_blank_query_matches_nothing(self):
        prs = [_make_pr("pr-001", title="anything")]
        assert fuzzy_match_prs(prs, "", {}) == []
        assert fuzzy_match_prs(prs, "   ", {}) == []
        assert fuzzy_match_plans([_make_plan("p", "n")], " ") == []

    def test_inner_whitespace_collapsed(self):
        assert score_pr(_make_pr("pr-1", title="spec gen"), "spec   gen", {}) == 200

    def test_entries_without_id_and_duplicates_skipped(self):
        prs = [{"title": "spec"}, {"id": None, "title": "spec"}, "junk",
               _make_pr("pr-1", title="spec"), _make_pr("pr-1", title="other spec")]
        ranked = fuzzy_match_prs(prs, "spec", {})
        assert [p["id"] for p in ranked] == ["pr-1"]
        assert ranked[0]["title"] == "spec"

    def test_bool_gh_number_ignored(self):
        assert score_pr({"id": "pr-1", "gh_pr_number": True}, "1", {}) == 0


class TestTreeOrderTieBreak:
    def test_positions_override_list_order(self):
        prs = [_make_pr("pr-a", title="fix"), _make_pr("pr-b", title="fix"),
               _make_pr("pr-c", title="fix")]
        # Tree order differs from list order: c is next to the cursor.
        positions = {"pr-a": 9, "pr-b": 0, "pr-c": 4}
        ranked = fuzzy_match_prs(prs, "fix", {}, cursor_index=5,
                                 positions=positions)
        assert [p["id"] for p in ranked] == ["pr-c", "pr-a", "pr-b"]

    def test_unpositioned_sort_after_positioned(self):
        prs = [_make_pr("pr-hidden", title="fix"), _make_pr("pr-far", title="fix")]
        ranked = fuzzy_match_prs(prs, "fix", {}, cursor_index=0,
                                 positions={"pr-far": 50})
        assert [p["id"] for p in ranked] == ["pr-far", "pr-hidden"]

    def test_score_still_dominates_proximity(self):
        prs = [_make_pr("pr-a", title="spec"),
               _make_pr("pr-b", title="spec", description="spec")]
        ranked = fuzzy_match_prs(prs, "spec", {}, cursor_index=0,
                                 positions={"pr-a": 0, "pr-b": 99})
        assert ranked[0]["id"] == "pr-b"

    def test_plan_tiebreak_by_list_index_without_positions(self):
        plans = [_make_plan("a", "fix x"), _make_plan("b", "fix y"),
                 _make_plan("c", "fix z")]
        assert fuzzy_match_plans(plans, "fix", cursor_index=2)[0]["id"] == "c"
        assert fuzzy_match_plans(plans, "fix", cursor_index=0)[0]["id"] == "a"


class TestPassesStatusFilterParity:
    """The shared predicate must agree with compute_tree_layout."""

    def test_matches_layout_for_every_combination(self):
        from pm_core.tui.tree_layout import compute_tree_layout, passes_status_filter
        statuses = ["pending", "in_progress", "in_review", "qa", "merged", "closed"]
        prs = [{"id": f"pr-{s}", "status": s, "title": s} for s in statuses]
        for status_filter in (None, *statuses):
            for hide_merged in (False, True):
                for hide_closed in (False, True):
                    kw = dict(status_filter=status_filter,
                              hide_merged=hide_merged, hide_closed=hide_closed)
                    laid_out = set(compute_tree_layout(prs, **kw).ordered_ids)
                    passing = {p["id"] for p in prs if passes_status_filter(p, **kw)}
                    assert laid_out == passing, kw
