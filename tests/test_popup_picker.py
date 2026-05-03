"""Tests for the action-based popup PR picker logic."""

from pm_core.cli.session import (
    _actions_for_status,
    _status_phase,
    _current_window_pr_id,
    _build_picker_lines,
)


def _pr(pr_id, status="in_progress", title="Test PR", gh_pr_number=None):
    pr = {"id": pr_id, "status": status, "title": title}
    if gh_pr_number is not None:
        pr["gh_pr_number"] = gh_pr_number
    return pr


class TestActionsForStatus:
    def test_all_actions_for_non_terminal(self):
        """Every non-terminal status returns the full action list."""
        for status in ("pending", "in_progress", "in_review", "qa"):
            actions = _actions_for_status(status)
            labels = [a[0] for a in actions]
            assert labels == ["start", "review", "review-loop",
                              "qa", "merge"]

    def test_merged_has_no_actions(self):
        assert _actions_for_status("merged") == []

    def test_closed_has_no_actions(self):
        assert _actions_for_status("closed") == []

    def test_unknown_status_returns_all_actions(self):
        """Non-terminal unknown statuses still get all actions."""
        labels = [a[0] for a in _actions_for_status("bogus")]
        assert labels == ["start", "review", "review-loop",
                          "qa", "merge"]

    def test_qa_command_routes_through_tui(self):
        actions = _actions_for_status("in_progress")
        qa_cmd = next(cmd for label, cmd in actions if label == "qa")
        assert qa_cmd.startswith("tui:")

    def test_review_loop_routes_through_tui(self):
        actions = _actions_for_status("in_progress")
        rl_cmd = next(cmd for label, cmd in actions if label == "review-loop")
        assert rl_cmd.startswith("tui:")

    def test_start_is_direct_cli(self):
        actions = _actions_for_status("in_progress")
        start_cmd = next(cmd for label, cmd in actions if label == "start")
        assert not start_cmd.startswith("tui:")


class TestStatusPhase:
    def test_in_progress_phase_is_start(self):
        assert _status_phase("in_progress") == "start"

    def test_in_review_phase_is_review(self):
        assert _status_phase("in_review") == "review"

    def test_qa_phase_is_qa(self):
        assert _status_phase("qa") == "qa"

    def test_pending_has_no_phase(self):
        assert _status_phase("pending") is None

    def test_merged_has_no_phase(self):
        assert _status_phase("merged") is None


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


class TestBuildPickerLines:
    def test_basic_layout(self):
        prs = [_pr("pr-001", "in_progress", "My Feature", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158")
        displays = [d for d, _, _ in lines]
        assert any("#158" in d for d in displays)
        assert any("start" in d for d in displays)
        assert any("review" in d for d in displays)

    def test_no_current_pr_returns_empty(self):
        prs = [_pr("pr-001", "in_progress", "My Feature", gh_pr_number=158)]
        assert _build_picker_lines(prs, None) == []

    def test_only_current_pr_shown(self):
        prs = [
            _pr("pr-001", "in_progress", "First", gh_pr_number=158),
            _pr("pr-002", "pending", "Second", gh_pr_number=160),
        ]
        lines = _build_picker_lines(prs, "#158")
        displays = " ".join(d for d, _, _ in lines)
        assert "#158" in displays
        assert "#160" not in displays

    def test_merged_pr_returns_empty(self):
        prs = [_pr("pr-001", "merged", "Done PR", gh_pr_number=158)]
        assert _build_picker_lines(prs, "#158") == []

    def test_all_actions_shown_regardless_of_status(self):
        prs = [_pr("pr-001", "pending", "New PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158")
        action_lines = [d for d, cmd, _ in lines if cmd]
        assert len(action_lines) == 5
        assert any("start" in d for d in action_lines)
        assert any("merge" in d for d in action_lines)
        rl_lines = [d for d in action_lines if "review-loop" in d]
        assert len(rl_lines) == 1

    def test_phase_indicator_shown(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158")
        action_lines = [(d, cmd) for d, cmd, _ in lines if cmd]
        start_line = next(d for d, _ in action_lines if "start" in d)
        assert "●" in start_line
        review_line = next(d for d, _ in action_lines if "review" in d and "review-loop" not in d)
        assert "●" not in review_line

    def test_in_review_phase_indicator(self):
        prs = [_pr("pr-001", "in_review", "Ready PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158")
        action_lines = [(d, cmd) for d, cmd, _ in lines if cmd]
        review_line = next(d for d, _ in action_lines if "review" in d and "review-loop" not in d)
        assert "●" in review_line

    def test_commands_contain_pr_id(self):
        prs = [_pr("pr-001", "in_progress", "My PR")]
        lines = _build_picker_lines(prs, "pr-001")
        commands = [cmd for _, cmd, _ in lines if cmd]
        assert all("pr-001" in cmd for cmd in commands)

    def test_empty_prs(self):
        assert _build_picker_lines([], "#158") == []

    def test_header_lines_have_no_command(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158")
        headers = [(d, cmd) for d, cmd, _ in lines if not cmd]
        assert len(headers) == 1
        assert "#158" in headers[0][0]
        assert "in_progress" in headers[0][0]

    def test_long_title_truncated(self):
        long_title = "A" * 60
        prs = [_pr("pr-001", "pending", long_title)]
        lines = _build_picker_lines(prs, "pr-001")
        header = lines[0][0]
        assert "…" in header
        assert len(header) < 80

    def test_pr_display_id_without_gh_number(self):
        prs = [_pr("pr-001", "in_progress", "My PR")]
        lines = _build_picker_lines(prs, "pr-001")
        displays = [d for d, _, _ in lines]
        assert any("pr-001" in d for d in displays)

    def test_unmatched_pr_returns_empty(self):
        prs = [_pr("pr-001", "in_progress", "First", gh_pr_number=158)]
        assert _build_picker_lines(prs, "#999") == []

    def test_open_window_indicator_start(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158", open_windows={"#158", "tui"})
        start_line = next(d for d, cmd, _ in lines if cmd and "start" in d)
        assert "[open]" in start_line

    def test_open_window_indicator_review(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158", open_windows={"#158", "review-#158"})
        review_line = next(d for d, cmd, _ in lines
                          if cmd and "review" in d and "review-loop" not in d)
        assert "[open]" in review_line

    def test_open_window_indicator_qa_with_scenarios(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158", open_windows={"qa-#158-s1"})
        qa_line = next(d for d, cmd, _ in lines if cmd and "qa" in d and "review" not in d)
        assert "[open]" in qa_line

    def test_no_open_indicator_when_window_closed(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158", open_windows={"#158"})
        review_line = next(d for d, cmd, _ in lines
                          if cmd and "review" in d and "review-loop" not in d)
        assert "[open]" not in review_line

    def test_no_open_indicator_without_open_windows(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158")
        action_lines = [d for d, cmd, _ in lines if cmd]
        assert not any("[open]" in d for d in action_lines)

    def test_review_loop_never_has_open_indicator(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158", open_windows={"#158", "review-#158"})
        rl_lines = [d for d, cmd, _ in lines if cmd and "review-loop" in d]
        assert not any("[open]" in d for d in rl_lines)
