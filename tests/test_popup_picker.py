"""Tests for the popup PR window picker logic."""

from pm_core.cli.session import (
    _group_windows_by_pr,
    _current_window_pr_id,
    _format_picker_lines,
)


def _win(name, index="0", win_id="@1"):
    return {"name": name, "index": index, "id": win_id}


class TestGroupWindowsByPr:
    def test_groups_impl_window(self):
        windows = [_win("#158", "1")]
        groups = _group_windows_by_pr(windows)
        assert "#158" in groups
        assert "impl" in groups["#158"]

    def test_groups_review_window(self):
        windows = [_win("review-#158", "2")]
        groups = _group_windows_by_pr(windows)
        assert "#158" in groups
        assert "review" in groups["#158"]

    def test_groups_merge_window(self):
        windows = [_win("merge-#158", "3")]
        groups = _group_windows_by_pr(windows)
        assert "#158" in groups
        assert "merge" in groups["#158"]

    def test_groups_qa_main_window(self):
        windows = [_win("qa-#158", "4")]
        groups = _group_windows_by_pr(windows)
        assert "#158" in groups
        assert "qa" in groups["#158"]

    def test_groups_qa_scenario_window(self):
        windows = [_win("qa-#158-s1", "5")]
        groups = _group_windows_by_pr(windows)
        assert "#158" in groups
        assert "qa-s1" in groups["#158"]

    def test_groups_pr_nnn_format(self):
        windows = [_win("pr-001", "1"), _win("review-pr-001", "2")]
        groups = _group_windows_by_pr(windows)
        assert "pr-001" in groups
        assert "impl" in groups["pr-001"]
        assert "review" in groups["pr-001"]

    def test_excludes_non_pr_windows(self):
        windows = [_win("tui", "0"), _win("notes", "1"), _win("#158", "2")]
        groups = _group_windows_by_pr(windows)
        assert len(groups) == 1
        assert "#158" in groups

    def test_multiple_prs(self):
        windows = [
            _win("#158", "1"), _win("review-#158", "2"),
            _win("#160", "3"), _win("qa-#160", "4"),
        ]
        groups = _group_windows_by_pr(windows)
        assert len(groups) == 2
        assert "#158" in groups
        assert "#160" in groups

    def test_empty_window_list(self):
        assert _group_windows_by_pr([]) == {}


class TestCurrentWindowPrId:
    def test_impl_window(self):
        assert _current_window_pr_id("#158") == "#158"

    def test_review_window(self):
        assert _current_window_pr_id("review-#158") == "#158"

    def test_qa_window(self):
        assert _current_window_pr_id("qa-#158") == "#158"

    def test_qa_scenario_window(self):
        assert _current_window_pr_id("qa-#158-s2") == "#158"

    def test_merge_window(self):
        assert _current_window_pr_id("merge-#158") == "#158"

    def test_non_pr_window(self):
        assert _current_window_pr_id("tui") is None

    def test_pr_nnn_format(self):
        assert _current_window_pr_id("pr-001") == "pr-001"

    def test_review_pr_nnn(self):
        assert _current_window_pr_id("review-pr-001") == "pr-001"


class TestFormatPickerLines:
    def test_basic_layout(self):
        groups = {"#158": {"impl": _win("#158", "1")}}
        lines = _format_picker_lines(groups, None)
        displays = [d for d, _ in lines]
        assert any("#158" in d for d in displays)

    def test_current_pr_sorted_first(self):
        groups = {
            "#160": {"impl": _win("#160", "2")},
            "#158": {"impl": _win("#158", "1")},
        }
        lines = _format_picker_lines(groups, "#158")
        # First line should be the header for #158
        assert "#158" in lines[0][0]

    def test_qa_scenarios_collapsed(self):
        groups = {
            "#158": {
                "impl": _win("#158", "1"),
                "qa": _win("qa-#158", "2"),
                "qa-s1": _win("qa-#158-s1", "3"),
                "qa-s2": _win("qa-#158-s2", "4"),
            }
        }
        lines = _format_picker_lines(groups, None, expand_qa=False)
        displays = [d for d, _ in lines]
        # Should have a collapse marker
        assert any("[+]" in d for d in displays)
        # Should NOT show individual scenario windows
        assert not any("qa-#158-s1" in d for d in displays)

    def test_qa_scenarios_expanded(self):
        groups = {
            "#158": {
                "impl": _win("#158", "1"),
                "qa-s1": _win("qa-#158-s1", "3"),
                "qa-s2": _win("qa-#158-s2", "4"),
            }
        }
        lines = _format_picker_lines(groups, None, expand_qa=True)
        displays = [d for d, _ in lines]
        assert any("s1" in d for d in displays)
        assert any("s2" in d for d in displays)

    def test_selectable_lines_have_indices(self):
        groups = {"#158": {"impl": _win("#158", "1"), "review": _win("review-#158", "2")}}
        lines = _format_picker_lines(groups, None)
        selectable = [(d, idx) for d, idx in lines if idx and idx != "expand"]
        assert len(selectable) == 2
        assert all(idx for _, idx in selectable)
