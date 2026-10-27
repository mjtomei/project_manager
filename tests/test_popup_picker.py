"""Tests for the action-based popup PR picker logic."""

from unittest.mock import patch, MagicMock

import pytest

from pm_core.cli.session import (
    _actions_for_status,
    _status_phase,
    _current_window_pr_id,
    _strip_action_window_prefix,
    _build_picker_lines,
    _build_nav_entries,
    _find_pr_for_window_id,
    _no_actions_notice,
    _run_picker_command,
    _ALL_ACTIONS,
)


def _pr(pr_id, status="in_progress", title="Test PR", gh_pr_number=None):
    pr = {"id": pr_id, "status": status, "title": title}
    if gh_pr_number is not None:
        pr["gh_pr_number"] = gh_pr_number
    return pr


class TestActionsForStatus:
    def test_all_actions_for_non_terminal(self):
        """Every non-terminal status returns the full action list."""
        for status in ("pending", "in_progress", "in_review", "qa", "sign_off"):
            actions = _actions_for_status(status)
            labels = [a[0] for a in actions]
            assert labels == ["start", "edit", "review", "qa", "signoff", "merge"]

    def test_merged_has_no_actions(self):
        assert _actions_for_status("merged") == []

    def test_closed_has_no_actions(self):
        assert _actions_for_status("closed") == []

    def test_unknown_status_returns_all_actions(self):
        """Non-terminal unknown statuses still get all actions."""
        labels = [a[0] for a in _actions_for_status("bogus")]
        assert labels == ["start", "edit", "review", "qa", "signoff", "merge"]

    def test_qa_command_routes_through_tui(self):
        actions = _actions_for_status("in_progress")
        qa_cmd = next(cmd for label, cmd in actions if label == "qa")
        assert qa_cmd.startswith("tui:")

    def test_zz_d_chord_routes_review_loop_through_tui(self):
        from pm_core.cli.session import _MODIFIED_ACTION_CMDS
        rl_cmd = _MODIFIED_ACTION_CMDS[("zz", "review")]
        assert rl_cmd.startswith("tui:review-loop")

    def test_z_i_chord_routes_fresh_signoff(self):
        """`z i` in the popup picker must launch a fresh sign-off run."""
        from pm_core.cli.session import _MODIFIED_ACTION_CMDS
        signoff_cmd = _MODIFIED_ACTION_CMDS[("z", "signoff")]
        assert signoff_cmd == "pr signoff --fresh {pr_id}"

    def test_z_chord_expect_list_includes_signoff_key(self):
        """Regression: the inline ``expect`` list for the z chord state must
        include the single-key shortcut for every z-keyed action — otherwise
        fzf swallows the keypress and the chord silently no-ops (the bug that
        existed when sign-off was added to _MODIFIED_ACTION_CMDS but not to
        the chord's expect list)."""
        import inspect
        from pm_core.cli import session
        # Grab the picker function's source and assert the z chord block
        # accepts 'i' (the single-key shortcut for 'signoff').
        src = inspect.getsource(session)
        # The z chord state block lists its accepted keys inline.
        marker = 'elif chord_state == "z":'
        idx = src.find(marker)
        assert idx >= 0, "z chord state block not found"
        # Look in the next ~600 chars for the expect-list assignment.
        block = src[idx:idx + 600]
        assert '"i"' in block, (
            "z chord state must include 'i' in its expect list; without it "
            "`z i` (fresh sign-off) is silently swallowed by fzf")

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

    def test_sign_off_phase_is_signoff(self):
        assert _status_phase("sign_off") == "signoff"

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

    def test_signoff_window(self):
        assert _current_window_pr_id("signoff-#158") == "#158"

    def test_non_pr_window(self):
        assert _current_window_pr_id("tui") is None

    def test_pr_nnn_format(self):
        assert _current_window_pr_id("pr-001") == "pr-001"

    def test_review_pr_nnn(self):
        assert _current_window_pr_id("review-pr-001") == "pr-001"


class TestStripActionWindowPrefix:
    """Fallback for ids the window-name grammar cannot read (e.g. ``_``)."""

    @pytest.mark.parametrize("window,expected", [
        ("review-pr-a_b", "pr-a_b"),
        ("qa-pr-a_b", "pr-a_b"),
        ("signoff-pr-a_b", "pr-a_b"),
        ("merge-pr-a_b", "pr-a_b"),
        ("pr-a_b", "pr-a_b"),
        ("tui", "tui"),
        # Never strip a scenario-like suffix: an id ending in -s1 is legal.
        ("qa-pr-a-s1", "pr-a-s1"),
    ])
    def test_strips_only_the_action_prefix(self, window, expected):
        assert _strip_action_window_prefix(window) == expected

    def test_bare_prefix_is_not_emptied(self):
        assert _strip_action_window_prefix("review-") == "review-"


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

    def test_only_window_actions_get_rows(self):
        # start / review / qa / signoff / merge each have their own window
        # and should appear; edit and review-loop are shortcut-only.
        prs = [_pr("pr-001", "pending", "New PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158")
        action_lines = [d for d, cmd, _ in lines if cmd]
        assert len(action_lines) == 5
        assert any("start" in d for d in action_lines)
        assert any("review" in d and "review-loop" not in d
                   for d in action_lines)
        assert any("qa" in d for d in action_lines)
        assert any("signoff" in d for d in action_lines)
        assert any("merge" in d for d in action_lines)
        # edit and review-loop are not list rows
        assert not any(d.strip().startswith("edit") for d in action_lines)
        assert not any("review-loop" in d for d in action_lines)

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


class TestPerSessionWindowIndicator:
    """●/○ markers for which session is viewing each action's window."""

    # Window-id map for an in_progress PR displayed as #158.
    NAME_TO_WID = {
        "#158": "@1",
        "review-#158": "@2",
        "qa-#158": "@3",
        "merge-#158": "@4",
        "tui": "@9",
    }

    def _rows(self, **kw):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(
            prs, "#158", name_to_wid=self.NAME_TO_WID, **kw)
        return {
            # key each action row by its label
            ("qa" if "qa" in d and "review" not in d
             else "review" if "review" in d and "review-loop" not in d
             else "signoff" if "signoff" in d
             else "merge" if "merge" in d
             else "start"): d
            for d, cmd, _ in lines if cmd
        }

    def test_caller_active_window_gets_filled_dot(self):
        rows = self._rows(caller_wid="@1", other_wids=set())
        assert "●" in rows["start"]
        assert "○" not in rows["start"]
        # No other session → everything else blank.
        assert "●" not in rows["review"] and "○" not in rows["review"]
        assert "●" not in rows["qa"] and "○" not in rows["qa"]

    def test_other_session_active_window_gets_open_circle(self):
        rows = self._rows(caller_wid="@1", other_wids={"@2"})
        assert "●" in rows["start"]
        assert "○" in rows["review"]
        assert "●" not in rows["review"]

    def test_caller_and_other_on_same_window_shows_filled_dot(self):
        # Same window active in caller AND another session → ● wins.
        rows = self._rows(caller_wid="@1", other_wids={"@1"})
        assert "●" in rows["start"]
        assert "○" not in rows["start"]

    def test_unselected_window_is_blank(self):
        rows = self._rows(caller_wid="@1", other_wids={"@2"})
        # merge window (@4) is selected by nobody.
        assert "●" not in rows["merge"]
        assert "○" not in rows["merge"]

    def test_caller_on_non_pr_window_no_filled_dot(self):
        # Caller sitting on the tui window → no action row is ●.
        rows = self._rows(caller_wid="@9", other_wids={"@3"})
        assert all("●" not in d for d in rows.values())
        assert "○" in rows["qa"]

    def test_qa_scenario_window_prefix_match(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        name_to_wid = {"#158": "@1", "qa-#158-s1": "@7"}
        lines = _build_picker_lines(
            prs, "#158", name_to_wid=name_to_wid,
            caller_wid="@1", other_wids={"@7"})
        qa_line = next(d for d, cmd, _ in lines
                       if cmd and "qa" in d and "review" not in d)
        assert "○" in qa_line

    def test_falls_back_to_phase_without_window_map(self):
        # No name_to_wid → legacy phase dot on the status's phase row.
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158")
        start_line = next(d for d, cmd, _ in lines if cmd and "start" in d)
        assert "●" in start_line

    def test_open_tag_still_works_with_window_map(self):
        prs = [_pr("pr-001", "in_progress", "My PR", gh_pr_number=158)]
        lines = _build_picker_lines(
            prs, "#158", open_windows={"#158", "review-#158"},
            name_to_wid=self.NAME_TO_WID, caller_wid="@1", other_wids=set())
        review_line = next(d for d, cmd, _ in lines
                           if cmd and "review" in d and "review-loop" not in d)
        assert "[open]" in review_line


class TestSessionActiveWindows:
    """_session_active_windows builds the per-session active-window map."""

    def test_builds_map_over_group_skipping_unattached(self):
        from pm_core.cli.session import _session_active_windows

        with patch("pm_core.cli.session.tmux_mod") as tmux:
            tmux.attached_group_active_windows.return_value = {
                "base~1": "@2", "base~2": "@5"}
            result = _session_active_windows("base")

        assert result == {"base~1": "@2", "base~2": "@5"}
        tmux.attached_group_active_windows.assert_called_once_with("base")


class TestPickerMergeDispatch:
    def test_merge_action_passes_resolve_window(self):
        """Picker merge entry must pass --resolve-window so conflicts launch
        a Claude resolution window, matching the TUI's behavior in
        pm_core/tui/pr_view.py."""
        merge_cmd = next(cmd for label, cmd in _ALL_ACTIONS if label == "merge")
        assert "--resolve-window" in merge_cmd
        assert "{pr_id}" in merge_cmd

    def test_run_picker_command_surfaces_stderr_on_failure(self):
        """Direct-CLI dispatch from the popup must capture stderr and
        re-emit it on non-zero exit so the user sees the failure
        instead of an empty popup."""
        fake_result = MagicMock(returncode=1, stdout="", stderr="boom: branch protected")
        with patch("pm_core.cli.session.subprocess.run", return_value=fake_result) as run_mock, \
             patch("pm_core.cli.session._wait_dismiss") as wait_mock, \
             patch("pm_core.cli.session.click.echo") as echo_mock:
            _run_picker_command("pr merge --resolve-window pr-123", "sess")

        assert run_mock.called
        # stderr must be captured (capture_output or stderr=PIPE)
        kwargs = run_mock.call_args.kwargs
        assert kwargs.get("capture_output") or kwargs.get("stderr") is not None
        # Some echo call must include the captured stderr text
        echoed = " ".join(
            str(c.args[0]) if c.args else "" for c in echo_mock.call_args_list
        )
        assert "boom: branch protected" in echoed
        assert wait_mock.called

    def test_run_picker_command_surfaces_stdout_on_success(self):
        """A successful direct dispatch re-emits the command's stdout.

        `pr review` on a QA/sign-off PR prints its inspection notice there,
        so the picker must not swallow it."""
        fake_result = MagicMock(
            returncode=0,
            stdout="PR #42 is in QA — opened review window 'review-#42' "
                   "without changing status.\n",
            stderr="")
        with patch("pm_core.cli.session.subprocess.run",
                   return_value=fake_result), \
             patch("pm_core.cli.session.click.echo") as echo_mock:
            _run_picker_command("pr review pr-123", "sess")
        echoed = " ".join(
            str(c.args[0]) if c.args else "" for c in echo_mock.call_args_list
        )
        assert "without changing status" in echoed

    def test_run_picker_command_silent_on_success(self):
        """Successful direct-CLI dispatch should not block waiting for a
        keypress (popup closes promptly)."""
        fake_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("pm_core.cli.session.subprocess.run", return_value=fake_result), \
             patch("pm_core.cli.session._wait_dismiss") as wait_mock:
            _run_picker_command("pr start pr-123", "sess")
        assert not wait_mock.called

    def test_run_picker_command_runs_as_invoking_session(self):
        """Direct dispatch runs the invoking session's pm (not the cwd's);
        the popup's exported PM_POPUP_SESSION reaches it unchanged."""
        from pm_core.cli.session import _session_pm_argv
        fake_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("pm_core.cli.session.subprocess.run",
                   return_value=fake_result) as run_mock:
            _run_picker_command("pr review pr-123", "proj~7")
        assert run_mock.call_args[0][0] == _session_pm_argv(
            "proj~7", ["pr", "review", "pr-123"])
        assert "env" not in run_mock.call_args.kwargs


class TestFindPrForWindowId:
    def test_matches_display_id(self):
        prs = [_pr("pr-001", gh_pr_number=12)]
        assert _find_pr_for_window_id(prs, "#12") is prs[0]

    def test_local_id_window_after_gh_number_assigned(self):
        """Window named pr-001 before the GitHub PR existed still resolves
        once the PR's display id becomes #12."""
        prs = [_pr("pr-001", gh_pr_number=12)]
        assert _find_pr_for_window_id(prs, "pr-001") is prs[0]

    def test_gh_number_as_string(self):
        prs = [_pr("pr-001", gh_pr_number="12")]
        assert _find_pr_for_window_id(prs, "#12") is prs[0]

    def test_gh_number_lost_is_unresolvable(self):
        """Window #193 whose PR lost gh_pr_number can't be matched."""
        prs = [_pr("pr-f5b7eef")]
        assert _find_pr_for_window_id(prs, "#193") is None

    def test_empty(self):
        assert _find_pr_for_window_id([_pr("pr-001")], "") is None


class TestBuildNavEntries:
    @pytest.mark.parametrize("window, expected", [
        ("qa-pr-a-s1", ["pr-a"]),
        ("qa-pr-a-custom-suffix", ["pr-a"]),
        ("qa-pr-a", ["pr-a"]),
        ("qa-pr-ab-s1", []),
        ("review-pr-a-s1", []),
        ("qa-#12-s1", ["#12"]),
    ])
    def test_qa_suffix_index_preserves_matching(self, window, expected):
        prs = [_pr("pr-a"), _pr("pr-b", gh_pr_number=12)]
        nav, _, _ = _build_nav_entries(prs, None, {window})
        assert nav == expected

    def test_non_pr_window_skips_merged(self):
        prs = [_pr("pr-a", status="merged", gh_pr_number=238),
               _pr("pr-b", status="in_review", gh_pr_number=240),
               _pr("pr-c", status="closed", gh_pr_number=241),
               _pr("pr-d", status="qa", gh_pr_number=242)]
        wins = {"#238", "review-#238", "#240", "qa-#241", "qa-#242-s1"}
        nav, by_disp, home = _build_nav_entries(prs, None, wins)
        assert nav == ["#240", "#242"]
        assert home is None
        assert by_disp["#240"] is prs[1]

    def test_merged_home_pr_kept_at_its_position(self):
        prs = [_pr("pr-b", status="in_review", gh_pr_number=240),
               _pr("pr-a", status="merged", gh_pr_number=238),
               _pr("pr-d", status="qa", gh_pr_number=242)]
        wins = {"#238", "#240", "#242"}
        nav, by_disp, home = _build_nav_entries(prs, "#238", wins)
        assert nav == ["#240", "#238", "#242"]
        assert home == "#238"
        assert by_disp["#238"] is prs[1]

    def test_home_canonicalized_from_local_id_window(self):
        prs = [_pr("pr-001", status="in_review", gh_pr_number=12)]
        nav, by_disp, home = _build_nav_entries(prs, "pr-001", {"pr-001"})
        assert nav == ["#12"]
        assert home == "#12"

    def test_window_named_by_local_id_counts_as_open(self):
        prs = [_pr("pr-001", status="in_review", gh_pr_number=12)]
        nav, _, _ = _build_nav_entries(prs, None, {"review-pr-001"})
        assert nav == ["#12"]

    def test_unresolvable_home_kept_first(self):
        prs = [_pr("pr-f5b7eef", status="in_review"),
               _pr("pr-b", status="in_review", gh_pr_number=240)]
        nav, by_disp, home = _build_nav_entries(prs, "#193", {"#193", "#240"})
        assert nav == ["#193", "#240"]
        assert home == "#193"
        assert "#193" not in by_disp

    def test_no_duplicate_when_home_has_windows(self):
        prs = [_pr("pr-a", status="in_review", gh_pr_number=5)]
        nav, _, _ = _build_nav_entries(prs, "#5", {"#5", "review-#5"})
        assert nav == ["#5"]


class TestBuildNavEntriesRejection:
    """A rejected snapshot must name the entry to repair.

    The picker fails closed on any malformed entry, so the message is the
    user's only clue in a large project.
    """

    def test_bad_id_names_entry_and_ids(self):
        prs = [_pr("pr-ok"), _pr("pr-a b", gh_pr_number=12)]
        with pytest.raises(ValueError) as exc:
            _build_nav_entries(prs, None, set())
        msg = str(exc.value)
        assert "command-safe string id" in msg
        assert "entry #2" in msg
        assert "id='pr-a b'" in msg
        assert "gh_pr_number=12" in msg

    def test_bad_status_names_entry(self):
        prs = [_pr("pr-ok"), _pr("pr-a", status="merg")]
        with pytest.raises(ValueError) as exc:
            _build_nav_entries(prs, None, set())
        msg = str(exc.value)
        assert "valid status" in msg
        assert "entry #2" in msg
        assert "status='merg'" in msg

    @pytest.mark.parametrize("status", [["in_review"], {"state": "qa"}])
    def test_unhashable_status_names_entry(self, status):
        """A YAML list/mapping status must raise the entry-naming ValueError,
        not TypeError: unhashable type (the set membership test hashes it)."""
        prs = [_pr("pr-ok"), _pr("pr-a", status=status)]
        with pytest.raises(ValueError) as exc:
            _build_nav_entries(prs, None, set())
        msg = str(exc.value)
        assert "valid status" in msg
        assert "entry #2" in msg
        assert f"status={status!r}" in msg

    @pytest.mark.parametrize("status", [["in_review"], {"state": "qa"}])
    def test_unhashable_status_popup_error_names_entry(
            self, tmp_path, monkeypatch, capsys, status):
        prs = [_pr("pr-ok"), _pr("pr-a", status=status)]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-ok"], "pr-ok", [])
        out = capsys.readouterr().out
        assert "Could not load PR actions" in out
        assert "entry #2" in out
        assert "unhashable" not in out
        assert not fzf.calls
        run_cmd.assert_not_called()

    def test_non_mapping_entry_names_its_type(self):
        with pytest.raises(ValueError) as exc:
            _build_nav_entries(["pr-a"], None, set())
        msg = str(exc.value)
        assert "entry #1" in msg
        assert "not a mapping: str" in msg

    def test_control_characters_stay_escaped(self):
        prs = [_pr("pr-a", gh_pr_number="12\x00")]
        with pytest.raises(ValueError) as exc:
            _build_nav_entries(prs, None, set())
        msg = str(exc.value)
        assert "printable display id" in msg
        assert "entry #1" in msg
        assert "\x00" not in msg
        assert "\\x00" in msg

    def test_ambiguous_display_names_both_sides(self):
        prs = [_pr("pr-a", gh_pr_number=12), _pr("pr-b", gh_pr_number=12)]
        with pytest.raises(ValueError) as exc:
            _build_nav_entries(prs, None, set())
        msg = str(exc.value)
        assert "ambiguous local or display ids" in msg
        assert "entry #2" in msg
        assert "collides with an earlier entry" in msg

    def test_popup_prints_the_rejected_entry(self, tmp_path, monkeypatch, capsys):
        prs = [_pr("pr-ok"), _pr("pr-b", status="merg")]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-ok"], "pr-ok", [])
        out = capsys.readouterr().out
        assert "Could not load PR actions" in out
        assert "entry #2" in out
        assert "status='merg'" in out
        assert not fzf.calls
        run_cmd.assert_not_called()


class TestNoActionsNotice:
    def test_merged(self):
        assert _no_actions_notice("#238", _pr("pr-a", status="merged")) == \
            "No actions — PR is merged."

    def test_closed(self):
        assert _no_actions_notice("#9", _pr("pr-a", status="closed")) == \
            "No actions — PR is closed."

    def test_lookup_failure_does_not_claim_merged(self):
        msg = _no_actions_notice("#193", None)
        assert msg == "Could not load actions for #193."
        assert "merged" not in msg


class _FakeFzf:
    """Scripted stand-in for the picker's fzf subprocess.

    Each entry in ``script`` is ``(returncode, stdout)`` for one fzf
    launch; every launch's argv and stdin are recorded.
    """

    def __init__(self, script, on_launch=None):
        self.script = list(script)
        self.calls: list[dict] = []
        self.on_launch = on_launch

    def __call__(self, cmd, **kwargs):
        fake = self

        class _Proc:
            def communicate(self, input=None):
                fake.calls.append({"cmd": cmd, "input": input})
                if fake.on_launch:
                    fake.on_launch(len(fake.calls))
                rc, out = fake.script.pop(0)
                self.returncode = rc
                return out, ""
        return _Proc()


def _header(call):
    return next(a for a in call["cmd"] if a.startswith("--header="))[len("--header="):]


def _expect(call):
    for a in call["cmd"]:
        if a.startswith("--expect="):
            return a[len("--expect="):].split(",")
    return []


def _run_picker(tmp_path, monkeypatch, prs, windows, window_name, script,
                on_launch=None, has_fzf=True, load_project=None):
    """Drive popup_picker_cmd end to end with a fake fzf.

    ``prs`` is re-read on every project.yaml load, so a test can mutate it
    from ``on_launch(n)`` (called before the n-th fzf launch returns) to
    simulate a PR being merged while the popup is open.
    """
    from pm_core.cli import session as sess

    reg = tmp_path / "registry.json"
    reg.write_text("{}")
    monkeypatch.setenv("PM_PROJECT", str(tmp_path))
    monkeypatch.setenv(sess.tmux_mod.POPUP_SESSION_ENV, "pm-x")
    fzf = _FakeFzf(script, on_launch)
    run_cmd = MagicMock()
    with patch.object(sess.pane_registry, "registry_path", return_value=reg), \
         patch.object(sess, "_resolve_root_from_session", return_value=tmp_path), \
         patch.object(sess.store, "load",
                      side_effect=load_project or (
                          lambda *a, **k: {"prs": [dict(p) for p in prs]})), \
         patch.object(sess.tmux_mod, "list_windows",
                      return_value=[{"name": n, "id": f"@{i}"}
                                    for i, n in enumerate(windows)]), \
         patch.object(sess, "_session_active_windows", return_value={}), \
         patch.object(sess, "_fzf_supports_no_input", return_value=True), \
         patch.object(sess, "_wait_dismiss"), \
         patch.object(sess, "_run_picker_command", run_cmd), \
         patch("shutil.which", return_value="/usr/bin/fzf" if has_fzf else None), \
         patch.object(sess.subprocess, "Popen", fzf):
        try:
            sess.popup_picker_cmd.callback("pm-x", window_name)
        except SystemExit:
            pass
    return fzf, run_cmd


class TestPopupPickerNoActions:
    PRS = [
        {"id": "pr-m", "status": "merged", "title": "Merged",
         "gh_pr_number": 238},
        {"id": "pr-r", "status": "in_review", "title": "Review",
         "gh_pr_number": 240},
        {"id": "pr-q", "status": "qa", "title": "QA", "gh_pr_number": 242},
    ]
    WINDOWS = ["tui", "#238", "review-#238", "#240", "qa-#242"]

    def test_non_pr_window_lands_on_active_pr(self, tmp_path, monkeypatch):
        """Opened from a non-PR window, merged #238 (with stale windows) is
        skipped: the picker lands on #240 and offers its actions."""
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self.PRS, self.WINDOWS, "tui",
            [(0, "s\n")])
        first = fzf.calls[0]
        assert _header(first).startswith("PR Actions — #240  (1/2)")
        assert "No actions" not in first["input"]
        run_cmd.assert_called_once()
        assert "pr-r" in run_cmd.call_args.args[0]

    def test_only_merged_windows_from_non_pr_window(self, tmp_path, monkeypatch, capsys):
        """Only merged PRs have windows and the popup is opened from a
        non-PR window: nothing to navigate to, so say so without fzf."""
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self.PRS[:1], ["tui", "#238"], "tui", [])
        assert fzf.calls == []
        assert "No active PR windows open." in capsys.readouterr().out
        run_cmd.assert_not_called()

    def test_merged_home_pr_shows_notice_and_navigates(self, tmp_path, monkeypatch):
        """Opened from merged #238's own window: show it with a scoped
        notice, keep nav keys working, and allow actions on the next PR."""
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self.PRS, self.WINDOWS, "#238",
            [(0, "l\n"), (0, "s\n")])
        first, second = fzf.calls
        assert _header(first).startswith("PR Actions — #238  (1/3)")
        assert "No actions — PR is merged." in first["input"]
        assert "merged or closed" not in first["input"]
        # Action keys aren't accepted for the merged PR; nav keys are.
        exp = _expect(first)
        assert "l" in exp and "h" in exp and "0" in exp
        assert not ({"s", "e", "d", "t", "i", "g", "z"} & set(exp))
        assert "enter:ignore" in next(a for a in first["cmd"]
                                      if a.startswith("--bind="))
        assert "s=start" not in _header(first)
        # After l: next PR with its actions and full key set.
        assert _header(second).startswith("PR Actions — #240  (2/3)")
        assert "s" in _expect(second)
        run_cmd.assert_called_once()
        assert "pr-r" in run_cmd.call_args.args[0]

    def test_unresolvable_window_reports_lookup_failure(self, tmp_path, monkeypatch):
        """Window #193 whose PR has no gh_pr_number in project.yaml: don't
        claim it's merged, log a warning, and let the user navigate away."""
        prs = [{"id": "pr-f5b7eef", "status": "in_review", "title": "x"},
               {"id": "pr-r", "status": "in_review", "title": "Review",
                "gh_pr_number": 240}]
        with patch("pm_core.cli.session._log") as log:
            fzf, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["#193", "#240"], "#193",
                [(0, "l\n"), (130, "")])
        first, second = fzf.calls
        assert "Could not load actions for #193." in first["input"]
        assert "merged" not in first["input"]
        log.warning.assert_called_once()
        fmt, *args = log.warning.call_args.args
        warning = fmt % tuple(args)
        assert "no actions for '#193'" in warning
        assert f"root={tmp_path}" in warning
        assert "('pr-f5b7eef', 'pr-f5b7eef')" in warning
        assert "('pr-r', '#240')" in warning
        assert "ids_omitted=0" in warning
        assert _header(second).startswith("PR Actions — #240")
        run_cmd.assert_not_called()

    def test_lookup_warning_bounds_known_id_sample(self, tmp_path, monkeypatch):
        prs = [_pr(f"pr-{i}", gh_pr_number=i + 1) for i in range(25)]
        with patch("pm_core.cli.session._log") as log:
            _, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["#193"], "#193", [(130, "")])
        log.warning.assert_called_once()
        fmt, *args = log.warning.call_args.args
        warning = fmt % tuple(args)
        assert "prs_loaded=25" in warning
        assert "('pr-19', '#20')" in warning
        assert "('pr-20', '#21')" not in warning
        assert "ids_omitted=5" in warning
        run_cmd.assert_not_called()

    def test_single_actionless_pr_does_not_exit_on_keypress(self, tmp_path, monkeypatch):
        """Only PR is merged: no accept keys at all, Enter is ignored, and
        only q/Esc (fzf abort) closes the popup."""
        prs = [self.PRS[0]]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#238"], "#238", [(130, "")])
        (call,) = fzf.calls
        # Only (unadvertised) nav keys are accepted — no action keys.
        assert set(_expect(call)) == {"h", "l", "left", "right", "0"}
        assert "h/l" not in _header(call)
        assert "enter:ignore" in next(a for a in call["cmd"]
                                      if a.startswith("--bind="))
        run_cmd.assert_not_called()

    def test_local_id_window_resolves_to_display_id(self, tmp_path, monkeypatch):
        """Window named pr-r (before #240 existed) resolves to #240's actions."""
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self.PRS, ["pr-r"], "pr-r", [(0, "s\n")])
        assert _header(fzf.calls[0]).startswith("PR Actions — #240")
        assert "pr-r" in run_cmd.call_args.args[0]

    def test_legacy_numeric_local_id_window_pins_home(self, tmp_path, monkeypatch):
        """A PR whose local id is the legacy numeric string `12` has a window
        named `12`, which the window-name grammar cannot read.  The snapshot
        match must still anchor home, or the picker opens on another PR."""
        prs = [_pr("pr-c", status="in_review"), _pr("12", status="in_progress")]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-c", "12"], "12", [(0, "s\n")])
        assert _header(fzf.calls[0]).startswith("PR Actions — 12  (2/2)")
        run_cmd.assert_called_once_with("pr start 12", "pm-x")

    def test_scenario_suffix_like_local_id_window_pins_its_own_pr(
            self, tmp_path, monkeypatch):
        """A local id ending in -s<N> is legal, and its window is named by that
        id.  The grammar would strip the suffix and resolve pr-a instead, so an
        exact snapshot match must win and dispatch for pr-a-s1."""
        prs = [_pr("pr-a", status="in_review"), _pr("pr-a-s1", status="in_progress")]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a", "pr-a-s1"], "pr-a-s1",
            [(0, "s\n")])
        assert _header(fzf.calls[0]).startswith("PR Actions — pr-a-s1  (2/2)")
        run_cmd.assert_called_once_with("pr start pr-a-s1", "pm-x")

    def test_prefixed_window_pins_home_for_unreadable_local_id(
            self, tmp_path, monkeypatch):
        """A prefixed window anchors on a local id the grammar cannot read.

        ``review-pr-a_b`` names pr-a_b, but ``_current_window_pr_id`` only
        accepts ``pr-<alnum>``, so without the prefix-stripped snapshot match
        the picker opens on the first live PR instead of the invoking one.
        """
        prs = [_pr("pr-x", status="in_review"),
               _pr("pr-a_b", status="in_review")]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-x", "review-pr-a_b"],
            "review-pr-a_b", [(0, "s\n")])
        assert _header(fzf.calls[0]).startswith("PR Actions — pr-a_b  (2/2)")
        run_cmd.assert_called_once_with("pr start pr-a_b", "pm-x")

    def test_prefixed_window_still_prefers_exact_scenario_suffixed_id(
            self, tmp_path, monkeypatch):
        """``qa-pr-a-s1`` must resolve to the PR whose id is literally
        ``pr-a-s1``, not to pr-a via the grammar's scenario-suffix strip."""
        prs = [_pr("pr-a", status="in_review"),
               _pr("pr-a-s1", status="in_progress")]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a", "qa-pr-a-s1"],
            "qa-pr-a-s1", [(0, "s\n")])
        assert _header(fzf.calls[0]).startswith("PR Actions — pr-a-s1  (2/2)")
        run_cmd.assert_called_once_with("pr start pr-a-s1", "pm-x")


def _shown(call):
    """(header PR position line, notice-or-first row) for one fzf launch."""
    return _header(call).splitlines()[0]


class TestPopupPickerEmptyProject:
    """An explicit `prs: []` is a valid empty project: the list collapses to
    the pinned home and nothing is dispatchable."""

    def test_empty_project_names_home_window(self, tmp_path, monkeypatch):
        """With no PR entries left, the collapsed home row names the invoking
        window id (there is no PR entry to supply a display id) rather than
        the retained local id."""
        prs = [_pr("pr-a", status="in_review", gh_pr_number=12),
               _pr("pr-b", status="qa")]

        def on_launch(n):
            if n == 1:
                prs.clear()

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#12", "pr-b"], "#12",
            [(0, "l\n"), (130, "")], on_launch=on_launch)
        collapsed = fzf.calls[1]
        assert _header(collapsed).splitlines() == ["PR Actions — #12", "q/Esc: quit"]
        assert "Could not load actions for #12." in collapsed["input"]
        assert "Could not load actions for pr-a." not in collapsed["input"]
        # `d` is not in the collapsed expect set: no second action runs.
        assert "d" not in _expect(collapsed)
        assert run_cmd.call_count == 0

    def test_empty_project_from_review_window_names_pr_id(self, tmp_path, monkeypatch):
        """The collapsed home names the PR id taken from the invoking window.

        A review/qa window is named ``review-#12``/``qa-#12-s1``; the
        collapsed notice must read ``#12``, not the raw tmux window name.
        """
        prs = [_pr("pr-a", status="in_review", gh_pr_number=12)]

        def on_launch(n):
            if n == 1:
                prs.clear()

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["review-#12"], "review-#12",
            [(0, "l\n"), (130, "")], on_launch=on_launch)
        collapsed = fzf.calls[1]
        assert _header(collapsed).splitlines() == ["PR Actions — #12", "q/Esc: quit"]
        assert "Could not load actions for #12." in collapsed["input"]
        assert "review-#12" not in collapsed["input"]
        assert run_cmd.call_count == 0

    def test_action_refused_after_collapse_names_home_window(
            self, tmp_path, monkeypatch):
        """Pressing an action key when `prs: []` lands on disk must refuse the
        action and name the collapsed home the same way the header does.

        The dispatch-refusal branch used to pass the retained local id to
        ``_no_actions_notice``, so the header read ``#12`` while the notice
        read ``pr-a`` (and the log line read ``#12``).
        """
        prs = [_pr("pr-a", status="in_review", gh_pr_number=12)]

        def on_launch(n):
            if n == 1:
                prs.clear()

        with patch("pm_core.cli.session._log") as log:
            fzf, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["#12"], "#12",
                [(0, "s\n"), (130, "")], on_launch=on_launch)
        refused = fzf.calls[1]
        assert _header(refused).splitlines() == ["PR Actions — #12", "q/Esc: quit"]
        assert "Could not load actions for #12." in refused["input"]
        assert "Could not load actions for pr-a." not in refused["input"]
        run_cmd.assert_not_called()
        # The diagnostics log agrees with what is on screen.
        warnings = [c.args[0] % tuple(c.args[1:])
                    for c in log.warning.call_args_list]
        assert any("no actions for '#12'" in w for w in warnings)
        assert not any("no actions for 'pr-a'" in w for w in warnings)

    def test_action_refused_after_collapse_names_home_window_no_fzf(
            self, tmp_path, monkeypatch, capsys):
        """Same refusal through the numbered fallback, which prints `lines`."""
        prs = [_pr("pr-a", status="in_review", gh_pr_number=12)]

        def choose(prompt):
            prs.clear()
            return "s"

        with patch("builtins.input", side_effect=choose):
            _, run_cmd = _run_picker(tmp_path, monkeypatch, prs, ["#12"],
                                     "#12", [], has_fzf=False)
        out = capsys.readouterr().out
        assert "Could not load actions for #12." in out
        assert "Could not load actions for pr-a." not in out
        run_cmd.assert_not_called()


class TestPopupPickerMergedNavigation:
    """note-40057f4: moving to/from retained merged entries must never
    exit the picker, and live PRs stay reachable in both directions."""

    def _prs(self):
        return [
            {"id": "pr-ac10f03", "status": "merged", "title": "Merged",
             "gh_pr_number": 238},
            {"id": "pr-r", "status": "in_review", "title": "Review",
             "gh_pr_number": 240},
            {"id": "pr-q", "status": "qa", "title": "QA",
             "gh_pr_number": 242},
        ]

    WINDOWS = ["#238", "review-#238", "merge-#238", "#240", "qa-#242"]

    def test_from_live_pr_merged_never_listed(self, tmp_path, monkeypatch):
        """Opened from live #240 with #238's windows still open: l, l
        (wrap), h, 0 cycle only the live PRs; #238 never appears."""
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self._prs(), self.WINDOWS, "review-#240",
            [(0, "l\n"), (0, "l\n"), (0, "h\n"), (0, "0\n"), (130, "")])
        assert [_shown(c) for c in fzf.calls] == [
            "PR Actions — #240  (1/2)",
            "PR Actions — #242  (2/2)",
            "PR Actions — #240  (1/2)",
            "PR Actions — #242  (2/2)",
            "PR Actions — #240  (1/2)",
        ]
        assert not any("#238" in c["input"] for c in fzf.calls)
        run_cmd.assert_not_called()

    def test_from_merged_home_both_directions_and_back(self, tmp_path, monkeypatch):
        """Opened from #238's window: h wraps to #242, 0 returns to the
        merged home (notice, no actions), l reaches #240, which runs."""
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self._prs(), self.WINDOWS, "merge-#238",
            [(0, "h\n"), (0, "0\n"), (0, "l\n"), (0, "d\n")])
        assert [_shown(c) for c in fzf.calls] == [
            "PR Actions — #238  (1/3)",
            "PR Actions — #242  (3/3)",
            "PR Actions — #238  (1/3)",
            "PR Actions — #240  (2/3)",
        ]
        for i in (0, 2):
            assert "No actions — PR is merged." in fzf.calls[i]["input"]
            assert "d" not in _expect(fzf.calls[i])
        run_cmd.assert_called_once()
        assert run_cmd.call_args.args[0].endswith("pr-r") or \
            "pr-r" in run_cmd.call_args.args[0]

    def test_pr_merged_while_open_drops_from_nav(self, tmp_path, monkeypatch):
        """#242 merges while the popup sits on #240: the next l reloads and
        must not land on #242 or index past the shrunken list."""
        prs = self._prs()

        def on_launch(n):
            if n == 1:
                prs[2]["status"] = "merged"

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, self.WINDOWS, "review-#240",
            [(0, "l\n"), (130, "")], on_launch=on_launch)
        first, second = fzf.calls
        assert _shown(first) == "PR Actions — #240  (1/2)"
        # Only #240 is left: no position counter, no nav keys.
        assert _shown(second) == "PR Actions — #240"
        assert "No actions" not in second["input"]
        run_cmd.assert_not_called()

    def test_shown_pr_merged_before_action_is_not_dispatched(self, tmp_path, monkeypatch):
        """#240 merges while displayed: pressing s re-renders it with the
        merged notice (no command), then l moves to #242, which runs."""
        prs = self._prs()

        def on_launch(n):
            if n == 1:
                prs[1]["status"] = "merged"

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, self.WINDOWS, "review-#240",
            [(0, "s\n"), (0, "l\n"), (0, "s\n")], on_launch=on_launch)
        first, second, third = fzf.calls
        assert _shown(first) == "PR Actions — #240  (1/2)"
        assert _shown(second) == "PR Actions — #240  (1/2)"
        assert "No actions — PR is merged." in second["input"]
        assert "s" not in _expect(second)
        # #240 is the home PR (opened from its window), so it stays listed.
        assert _shown(third) == "PR Actions — #242  (2/2)"
        run_cmd.assert_called_once()
        assert "pr-q" in run_cmd.call_args.args[0]

    def test_chord_on_pr_merged_mid_chord_is_not_dispatched(self, tmp_path, monkeypatch):
        """z s (fresh start) on a PR merged after the chord began must not
        build a fresh-start command for the merged PR."""
        prs = self._prs()

        def on_launch(n):
            if n == 2:
                prs[1]["status"] = "merged"

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, self.WINDOWS, "review-#240",
            [(0, "z\n"), (0, "s\n"), (130, "")], on_launch=on_launch)
        assert "No actions — PR is merged." in fzf.calls[2]["input"]
        run_cmd.assert_not_called()

    def test_all_navigable_prs_merge_keeps_picker_open(self, tmp_path, monkeypatch):
        """Opened from a non-PR window; both live PRs merge.  Navigating
        keeps showing the current PR's notice instead of exiting."""
        prs = self._prs()

        def on_launch(n):
            if n == 1:
                prs[1]["status"] = "merged"
                prs[2]["status"] = "closed"

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, self.WINDOWS, "tui",
            [(0, "l\n"), (130, "")], on_launch=on_launch)
        assert _shown(fzf.calls[1]) == "PR Actions — #240"
        assert "No actions — PR is merged." in fzf.calls[1]["input"]
        run_cmd.assert_not_called()

    def test_gh_number_assigned_while_shown(self, tmp_path, monkeypatch):
        """#240 is shown as pr-r (no GitHub PR yet, windows named pr-r) and
        gets gh_pr_number while the popup is open: the reload must treat
        pr-r and #240 as one PR — no duplicate nav entry, no 'Could not
        load' — and dispatch its action."""
        prs = self._prs()
        prs[1].pop("gh_pr_number")

        def on_launch(n):
            if n == 1:
                prs[1]["gh_pr_number"] = 240

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["review-pr-r", "qa-#242"], "tui",
            [(0, "l\n"), (0, "h\n"), (0, "s\n")], on_launch=on_launch)
        assert [_shown(c) for c in fzf.calls] == [
            "PR Actions — pr-r  (1/2)",
            "PR Actions — #242  (2/2)",
            "PR Actions — #240  (1/2)",
        ]
        run_cmd.assert_called_once()
        assert "pr-r" in run_cmd.call_args.args[0]

    def test_gh_number_assigned_before_action(self, tmp_path, monkeypatch):
        """Same drift, but the first key is an action: the pre-dispatch
        reload re-resolves the PR under its new id and still runs it."""
        prs = self._prs()
        prs[1].pop("gh_pr_number")

        def on_launch(n):
            if n == 1:
                prs[1]["gh_pr_number"] = 240

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["review-pr-r", "qa-#242"], "tui",
            [(0, "s\n")], on_launch=on_launch)
        run_cmd.assert_called_once()
        assert "pr-r" in run_cmd.call_args.args[0]

    def test_merged_pr_reopened_while_alone_is_reachable(self, tmp_path, monkeypatch):
        """Both live PRs merge, collapsing the nav list to one entry; one is
        then reopened.  Nav keys still reload with a single entry, so the
        reopened PR comes back into reach (QA edge case E4)."""
        prs = self._prs()

        def on_launch(n):
            if n == 1:
                prs[1]["status"] = "merged"
                prs[2]["status"] = "closed"
            if n == 2:
                prs[2]["status"] = "qa"

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, self.WINDOWS, "tui",
            [(0, "l\n"), (0, "l\n"), (0, "t\n")], on_launch=on_launch)
        assert [_shown(c) for c in fzf.calls] == [
            "PR Actions — #240  (1/2)",
            "PR Actions — #240",
            # #240 itself is merged now, so only #242 remains.
            "PR Actions — #242",
        ]
        assert "l" in _expect(fzf.calls[1])
        run_cmd.assert_called_once()
        assert "pr-q" in run_cmd.call_args.args[0]


class TestPopupPickerRefreshFailures:
    @pytest.mark.parametrize("bad_prs", [None, False, 0, "", {}, "missing"])
    @pytest.mark.parametrize("key", ["l", "d"])
    def test_invalid_pr_list_keeps_last_good_snapshot(
            self, tmp_path, monkeypatch, bad_prs, key):
        from pm_core.cli import session as sess

        prs = [_pr("pr-a"), _pr("pr-b")]
        snapshot = {"prs": prs}

        def on_launch(n):
            if n == 1:
                snapshot.clear()
                if bad_prs != "missing":
                    snapshot["prs"] = bad_prs
            elif n == 2:
                snapshot["prs"] = [dict(prs[0], status="merged"), prs[1]]

        with patch.object(sess, "_log") as log:
            fzf, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["pr-a", "pr-b"], "pr-a",
                [(0, f"{key}\n"), (0, "0\n"), (130, "")],
                on_launch=on_launch, load_project=lambda *a, **k: snapshot.copy())
        expected = "PR Actions — pr-b  (2/2)" if key == "l" else "PR Actions — pr-a  (1/2)"
        assert _shown(fzf.calls[1]) == expected
        if key == "d":
            assert "Could not refresh PR actions; no action was run." in fzf.calls[1]["input"]
        assert "No actions — PR is merged." in fzf.calls[2]["input"]
        assert any("refresh failed" in c.args[0] for c in log.warning.call_args_list)
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("snapshot", [{}, {"prs": None}, {"prs": False},
                                           {"prs": 0}, {"prs": ""}, {"prs": {}}])
    def test_invalid_initial_pr_list_waits_with_error(
            self, tmp_path, monkeypatch, capsys, snapshot):
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, [], [], "tui", [],
            load_project=lambda *a, **k: snapshot)
        assert "Could not load PR actions:" in capsys.readouterr().out
        assert not fzf.calls
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("has_fzf", [False, True])
    def test_failed_refresh_explains_refused_action(
            self, tmp_path, monkeypatch, capsys, has_fzf):
        prs = [_pr("pr-a")]
        loads = iter([{"prs": prs}, {"prs": False}])
        with patch("builtins.input", return_value="d"):
            fzf, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["pr-a"], "pr-a",
                [(0, "d\n"), (130, "")], has_fzf=has_fzf,
                load_project=lambda *a, **k: next(loads))
        shown = fzf.calls[-1]["input"] if has_fzf else capsys.readouterr().out
        assert "Could not refresh PR actions; no action was run." in shown
        # fzf stays open for a retry; the one-shot fallback must be reopened.
        retry = "retry." if has_fzf else "reopen the picker."
        assert f"Repair project.yaml and {retry}" in shown
        assert "without fzf" not in shown
        if has_fzf:
            # Each notice row must fit the 80-column popup (78 inner columns,
            # minus fzf's pointer/marker gutter) or fzf clips the instruction.
            rows = fzf.calls[-1]["input"].split("\n")
            assert len(rows) == 2
            assert all(len(r) <= 72 for r in rows)
        run_cmd.assert_not_called()

    def test_explicit_empty_pr_list_is_valid(self, tmp_path, monkeypatch, capsys):
        fzf, run_cmd = _run_picker(tmp_path, monkeypatch, [], [], "tui", [])
        assert "No active PR windows open." in capsys.readouterr().out
        assert not fzf.calls
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("bad_status", [None, "merg", ""])
    @pytest.mark.parametrize("key", ["s", "l"])
    def test_raw_invalid_status_is_not_normalized_into_actions(
            self, tmp_path, monkeypatch, bad_status, key):
        import yaml
        from pm_core.cli import session as sess

        prs = [_pr("pr-a"), _pr("pr-b")]
        path = tmp_path / "project.yaml"
        path.write_text(yaml.safe_dump({"prs": prs}))
        real_load = sess.store.load

        def on_launch(n):
            if n == 1:
                broken = dict(prs[0], status=bad_status)
                if bad_status is None:
                    broken.pop("status")
                path.write_text(yaml.safe_dump({"prs": [broken, prs[1]]}))
            elif n == 2:
                prs[0]["status"] = "merged"
                path.write_text(yaml.safe_dump({"prs": prs}))

        with patch.object(sess, "_log") as log:
            fzf, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["pr-a", "pr-b"], "pr-a",
                [(0, f"{key}\n"), (0, "0\n"), (130, "")],
                on_launch=on_launch, load_project=real_load)
        run_cmd.assert_not_called()
        assert any("refresh failed" in c.args[0]
                   for c in log.warning.call_args_list)
        assert "No actions — PR is merged." in fzf.calls[-1]["input"]

    @pytest.mark.parametrize("invalid", [
        {"status": "merg"}, {"status": None}, {"gh_pr_number": "12\x00"},
    ])
    def test_invalid_raw_initial_snapshot_reports_error_without_launch(
            self, tmp_path, monkeypatch, capsys, invalid):
        import yaml
        from pm_core.cli import session as sess

        prs = [dict(_pr("pr-a"), **invalid)]
        (tmp_path / "project.yaml").write_text(yaml.safe_dump({"prs": prs}))
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a"], "pr-a", [],
            load_project=sess.store.load)
        assert "Could not load PR actions:" in capsys.readouterr().out
        assert not fzf.calls
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("choice", ["1", "s"])
    def test_raw_invalid_status_blocks_fallback(
            self, tmp_path, monkeypatch, choice):
        import yaml
        from pm_core.cli import session as sess

        prs = [_pr("pr-a")]
        path = tmp_path / "project.yaml"
        path.write_text(yaml.safe_dump({"prs": prs}))

        def choose(prompt):
            path.write_text(yaml.safe_dump({"prs": [dict(prs[0], status="merg")]}))
            return choice

        with patch("builtins.input", side_effect=choose):
            _, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["pr-a"], "pr-a", [],
                has_fzf=False, load_project=sess.store.load)
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("bad_number", ["12\x00", "12\n13", "12\x1b[2J"])
    def test_control_character_display_id_rejects_snapshot(self, bad_number):
        with pytest.raises(ValueError, match="display id"):
            _build_nav_entries([_pr("pr-a", gh_pr_number=bad_number)],
                               "pr-a", {"pr-a"})

    def test_control_character_number_keeps_last_good_snapshot(
            self, tmp_path, monkeypatch):
        prs = [_pr("pr-a", gh_pr_number=12), _pr("pr-b")]

        def on_launch(n):
            if n == 1:
                prs[0]["gh_pr_number"] = "12\x00"
            elif n == 2:
                prs[0]["gh_pr_number"] = 12
                prs[0]["status"] = "merged"

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#12", "pr-b"], "pr-a",
            [(0, "s\n"), (0, "0\n"), (130, "")], on_launch=on_launch)
        assert "PR Actions — #12" in _header(fzf.calls[1])
        assert "No actions — PR is merged." in fzf.calls[-1]["input"]
        run_cmd.assert_not_called()

    def test_harness_restores_popup_environment(self, tmp_path):
        import os
        from pm_core.cli import session as sess

        before = os.environ.get(sess.tmux_mod.POPUP_SESSION_ENV)
        with pytest.MonkeyPatch.context() as mp:
            _run_picker(tmp_path, mp, [_pr("pr-a")], ["pr-a"], "pr-a",
                        [(130, "")])
        assert os.environ.get(sess.tmux_mod.POPUP_SESSION_ENV) == before

    @pytest.mark.parametrize("bad_id", [None, "", 123, ["pr-a"], "missing",
                                       "pr-a'", "pr-a b", "pr-a\n", "pr-a\\b"])
    @pytest.mark.parametrize("key", ["s", "0", "l"])
    def test_numbered_pr_with_invalid_local_id_keeps_snapshot(
            self, tmp_path, monkeypatch, bad_id, key):
        import yaml
        from pm_core.cli import session as sess

        prs = [_pr("pr-a", gh_pr_number=12), _pr("pr-b")]
        real_load = sess.store.load

        def on_launch(n):
            if n == 1:
                broken = dict(prs[0], id=bad_id)
                if bad_id == "missing":
                    broken.pop("id")
                (tmp_path / "project.yaml").write_text(
                    yaml.safe_dump({"prs": [broken, prs[1]]}))
                # The real loader accepts these ids; refresh must validate
                # them before replacing the last-good picker snapshot.
                prs[:] = real_load(tmp_path)["prs"]
            elif n == 2:
                prs[0] = _pr("pr-a", status="merged", gh_pr_number=12)

        with patch.object(sess, "_log") as log:
            fzf, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["#12", "pr-b"], "#12",
                [(0, f"{key}\n"), (0, "0\n"), (130, "")],
                on_launch=on_launch)
        assert len(fzf.calls) == 3
        assert "No actions — PR is merged." in fzf.calls[-1]["input"]
        assert any("refresh failed" in c.args[0]
                   for c in log.warning.call_args_list)
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("choice", ["1", "s"])
    def test_numbered_pr_missing_local_id_blocks_fallback(
            self, tmp_path, monkeypatch, choice):
        prs = [_pr("pr-a", gh_pr_number=12)]

        def choose(prompt):
            prs[0].pop("id")
            return choice

        with patch("builtins.input", side_effect=choose):
            _, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["#12"], "#12", [], has_fzf=False)
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("title", [None, 123, 0, False])
    def test_non_string_title_does_not_crash_navigation(self, tmp_path, monkeypatch, title):
        prs = [_pr("pr-a"), _pr("pr-b")]

        def on_launch(n):
            if n == 1:
                prs[1]["title"] = title

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a", "pr-b"], "tui",
            [(0, "l\n"), (0, "h\n"), (130, "")], on_launch=on_launch)
        assert [_shown(c) for c in fzf.calls] == [
            "PR Actions — pr-a  (1/2)",
            "PR Actions — pr-b  (2/2)",
            "PR Actions — pr-a  (1/2)",
        ]
        rendered_title = "" if title is None else str(title)
        assert fzf.calls[1]["input"].splitlines()[0] == (
            f"  pr-b  (in_progress)  {rendered_title}")
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("mode", ["shortcut", "enter", "fresh", "loop"])
    def test_failed_refresh_blocks_action_until_repaired(self, tmp_path, monkeypatch, mode):
        from pm_core.cli import session as sess

        prs = [_pr("pr-a")]
        prefix = [(0, "z\n")] * {"fresh": 1, "loop": 2}.get(mode, 0)
        if mode == "enter":
            rows = sess._build_picker_lines(prs, "pr-a", {"pr-a"})
            row = next(d for d, c, _ in rows if c == "pr start pr-a")
            selection = f"\n{row}\n"
        else:
            selection = "d\n"

        def on_launch(n):
            if n == len(prefix) + 1:
                prs[0]["status"] = "merged"
                prs.append({"status": "in_review"})
            elif n == len(prefix) + 2:
                prs.pop()

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a"], "pr-a",
            prefix + [(0, selection), (0, "s\n"), (130, "")], on_launch=on_launch)
        assert len(fzf.calls) == len(prefix) + 3
        assert "No actions — PR is merged." in fzf.calls[-1]["input"]
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("choice", ["1", "s"])
    def test_failed_refresh_blocks_fallback_action(self, tmp_path, monkeypatch, choice):
        prs = [_pr("pr-a")]

        def choose(prompt):
            prs[0]["status"] = "merged"
            prs.append({"status": "in_review"})
            return choice

        with patch("builtins.input", side_effect=choose):
            _, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["pr-a"], "pr-a", [], has_fzf=False)
        run_cmd.assert_not_called()

    def test_malformed_reload_keeps_complete_previous_state(self, tmp_path, monkeypatch):
        prs = [_pr("pr-a"), _pr("pr-b")]

        def on_launch(n):
            if n == 1:
                prs[0]["status"] = "merged"
                prs.append({"status": "in_review"})
            elif n == 2:
                prs.pop()

        with patch("pm_core.cli.session._log") as log:
            fzf, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["pr-a", "pr-b"], "tui",
                [(0, "l\n"), (0, "h\n"), (130, "")], on_launch=on_launch)
        assert [_shown(c) for c in fzf.calls] == [
            "PR Actions — pr-a  (1/2)",
            "PR Actions — pr-b  (2/2)",
            "PR Actions — pr-b",
        ]
        assert log.warning.called
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("direction, target", [("l", "pr-c"), ("h", "pr-a")])
    def test_removed_current_uses_renumbered_neighbor(self, tmp_path, monkeypatch,
                                                    direction, target):
        prs = [_pr("pr-a"), _pr("pr-b"), _pr("pr-c")]

        def on_launch(n):
            if n == 2:
                prs[1]["status"] = "closed"
                next(p for p in prs if p["id"] == target)["gh_pr_number"] = 12

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a", "pr-b", "pr-c"], "tui",
            [(0, "l\n"), (0, f"{direction}\n"), (130, "")], on_launch=on_launch)
        assert _shown(fzf.calls[1]) == "PR Actions — pr-b  (2/3)"
        assert _shown(fzf.calls[2]).startswith("PR Actions — #12 ")
        run_cmd.assert_not_called()


class TestPopupPickerPresentation:
    def test_title_sanitization_only_visits_visible_prefix(self):
        class LargeTitle(str):
            def __str__(self):
                return self

            def __iter__(self):
                raise AssertionError("must truncate before iterating the title")

        title = LargeTitle("A\n" * 100000)
        rows = _build_picker_lines([_pr("pr-a", title=title)], "pr-a")
        assert rows[0][0].endswith("A " * 19 + "A…")

    @pytest.mark.parametrize("separator", ["\n", "\r", "\t", "\x00", "\x1b", chr(0x2028)])
    def test_title_stays_one_printable_row(self, tmp_path, monkeypatch, separator):
        prs = [_pr("pr-a", title=f"Title{separator}continued")]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a"], "pr-a", [(130, "")])
        rows = fzf.calls[0]["input"].splitlines()
        assert len(rows) == 6
        assert all(row.isprintable() for row in rows)
        assert "Title continued" in rows[0]
        run_cmd.assert_not_called()

    def test_multiline_title_cannot_add_an_action_row(self, tmp_path, monkeypatch):
        action_row = "    start              [open]"
        title = "Title\n" + action_row
        prs = [_pr("pr-a", title=title)]
        title_row = "  pr-a  (in_progress)  " + title.replace("\n", " ")
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a"], "pr-a",
            [(0, f"\n{title_row}\n"), (130, "")])
        # Only the real action row may carry this text in fzf's item stream.
        assert fzf.calls[0]["input"].splitlines().count(action_row) == 1
        assert fzf.calls[0]["input"].splitlines()[0] == title_row
        assert len(fzf.calls) == 2
        assert prs[0]["title"] == title
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("direction", ["h", "l"])
    def test_disjoint_navigation_refresh_uses_linear_identity_lookups(
            self, tmp_path, monkeypatch, direction):
        class CountedPR(dict):
            reads = 0

            def __getitem__(self, key):
                if key == "id":
                    type(self).reads += 1
                return super().__getitem__(key)

        size = 100
        prs = [_pr(f"pr-old{i}") for i in range(size)]
        replacement = [CountedPR(_pr(f"pr-new{i}")) for i in range(size)]
        windows = [p["id"] for p in prs + replacement]

        def on_launch(n):
            if n == 1:
                prs[:] = replacement
                CountedPR.reads = 0

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, windows, "tui",
            [(0, f"{direction}\n"), (130, "")], on_launch=on_launch,
            load_project=lambda *a, **k: {"prs": list(prs)})
        assert _shown(fzf.calls[1]) == "PR Actions — pr-new0  (1/100)"
        assert CountedPR.reads < 30 * size
        run_cmd.assert_not_called()


class TestPopupPickerActiveWindows:
    def test_navigation_refreshes_selected_session_indicators(self, tmp_path, monkeypatch):
        from pm_core.cli import session as sess

        prs = [_pr("pr-a")]

        def on_launch(n):
            if n == 1:
                monkeypatch.setattr(sess, "_session_active_windows",
                                    lambda base: {"pm-other": "@1"})

        fzf, _ = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a", "review-pr-a"], "pr-a",
            [(0, "l\n"), (130, "")], on_launch=on_launch)
        assert "○ review" not in fzf.calls[0]["input"]
        assert "○ review" in fzf.calls[1]["input"]


class TestPopupPickerIdentity:
    @pytest.mark.parametrize("key", ["h", "l", "0"])
    @pytest.mark.parametrize("pending_action", [False, True])
    def test_terminal_collision_with_home_preserves_navigation_identity(
            self, tmp_path, monkeypatch, key, pending_action):
        prs = [_pr("pr-home", status="closed", gh_pr_number=13),
               _pr("pr-a", gh_pr_number=12), _pr("pr-c", gh_pr_number=14)]

        def on_launch(n):
            if n == 2:
                prs[0]["gh_pr_number"] = 12
                prs[1]["status"] = "merged"

        action = [(0, "d\n")] if pending_action else []
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-home", "#12", "#14"], "pr-home",
            [(0, "l\n")] + action + [(0, f"{key}\n"), (0, "0\n"),
                                     (0, "l\n"), (0, "d\n")],
            on_launch=on_launch)
        if pending_action:
            assert "No actions — PR is merged." in fzf.calls[2]["input"]
            assert "(2/3)" in _header(fzf.calls[2])
        destination = fzf.calls[2 + int(pending_action)]
        if key == "l":
            assert _shown(destination) == "PR Actions — #14  (2/2)"
        else:
            assert "No actions — PR is closed." in destination["input"]
        assert "No actions — PR is closed." in fzf.calls[-2]["input"]
        run_cmd.assert_called_once_with("pr review pr-c", "pm-x")

    def test_deleted_numeric_local_home_never_resolves_as_github_number(
            self, tmp_path, monkeypatch):
        prs = [_pr("12", gh_pr_number=13), _pr("pr-b", gh_pr_number=12)]

        def on_launch(n):
            if n == 1:
                prs.pop(0)

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#13", "#12"], "#13",
            [(0, "0\n"), (0, "d\n"), (0, "l\n"), (0, "d\n")],
            on_launch=on_launch)
        assert "Could not load actions for 12." in fzf.calls[1]["input"]
        assert "Could not load actions for 12." in fzf.calls[2]["input"]
        run_cmd.assert_called_once_with("pr review pr-b", "pm-x")

    @pytest.mark.parametrize("mode", ["shortcut", "enter", "fresh", "loop", "fallback"])
    @pytest.mark.parametrize("removed", [False, True])
    def test_reassigned_number_does_not_retarget_action(
            self, tmp_path, monkeypatch, mode, removed):
        from pm_core.cli import session as sess

        prs = [_pr("pr-a", gh_pr_number=12), _pr("pr-b")]
        prefix = [(0, "z\n")] * {"fresh": 1, "loop": 2}.get(mode, 0)
        row = next(d for d, c, _ in sess._build_picker_lines(prs, "#12")
                   if c == "pr review pr-a")

        def reassign():
            prs[0].pop("gh_pr_number")
            prs[1]["gh_pr_number"] = 12
            if removed:
                prs.pop(0)

        def on_launch(n):
            if n == len(prefix) + 1:
                reassign()

        def choose(prompt):
            reassign()
            return "d"

        selection = f"\n{row}\n" if mode == "enter" else "d\n"
        with patch("builtins.input", side_effect=choose):
            _, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["#12", "pr-b"], "#12",
                prefix + [(0, selection), (130, "")],
                on_launch=on_launch, has_fzf=mode != "fallback")
        if removed:
            run_cmd.assert_not_called()
        else:
            assert run_cmd.call_count == 1
            assert "pr-a" in run_cmd.call_args.args[0]
            assert "pr-b" not in run_cmd.call_args.args[0]

    @pytest.mark.parametrize("reassign", [False, True])
    def test_home_keeps_local_identity_when_number_removed(
            self, tmp_path, monkeypatch, reassign):
        prs = [_pr("pr-a", gh_pr_number=12), _pr("pr-b")]

        def on_launch(n):
            if n == 1:
                prs[0].pop("gh_pr_number")
                if reassign:
                    prs[1]["gh_pr_number"] = 12

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#12", "pr-b"], "#12",
            [(0, "0\n"), (0, "d\n")], on_launch=on_launch)
        assert _shown(fzf.calls[1]) == "PR Actions — pr-a  (1/2)"
        run_cmd.assert_called_once_with("pr review pr-a", "pm-x")

    @pytest.mark.parametrize("reassign", [False, True])
    @pytest.mark.parametrize("repair_key", ["0", "h", "l"])
    def test_repaired_home_keeps_local_identity(
            self, tmp_path, monkeypatch, reassign, repair_key):
        prs = [_pr("pr-a"), _pr("pr-b")]

        def on_launch(n):
            if n == 1:
                prs[0]["gh_pr_number"] = 12
            elif n == 2:
                prs[0].pop("gh_pr_number")
                if reassign:
                    prs[1]["gh_pr_number"] = 12

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#12", "pr-a", "pr-b"], "#12",
            [(0, f"{repair_key}\n"), (0, "0\n"), (0, "d\n"), (130, "")],
            on_launch=on_launch)
        assert "Could not load actions for #12." in fzf.calls[0]["input"]
        assert _shown(fzf.calls[2]) == "PR Actions — pr-a  (1/2)"
        run_cmd.assert_called_once_with("pr review pr-a", "pm-x")

    @pytest.mark.parametrize("direction", ["h", "l"])
    def test_navigation_steps_from_local_identity_after_number_reassignment(
            self, tmp_path, monkeypatch, direction):
        prs = [_pr("pr-a", gh_pr_number=12), _pr("pr-b"), _pr("pr-c")]

        def on_launch(n):
            if n == 1:
                prs[0].pop("gh_pr_number")
                prs[1]["gh_pr_number"] = 12

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["pr-a", "pr-b", "pr-c", "#12"], "tui",
            [(0, f"{direction}\n"), (0, "d\n")], on_launch=on_launch)
        target = "pr-b" if direction == "l" else "pr-c"
        run_cmd.assert_called_once_with(f"pr review {target}", "pm-x")

    @pytest.mark.parametrize("mode", ["shortcut", "enter", "fresh", "loop", "fallback"])
    @pytest.mark.parametrize("duplicate", ["display", "local"])
    def test_ambiguous_reload_refuses_pending_action(
            self, tmp_path, monkeypatch, mode, duplicate):
        from pm_core.cli import session as sess

        # B precedes A so a display-id lookup would choose the wrong PR.
        prs = [_pr("pr-b", gh_pr_number=13), _pr("pr-a", gh_pr_number=12)]
        prefix = [(0, "z\n")] * {"fresh": 1, "loop": 2}.get(mode, 0)
        row = next(d for d, c, _ in sess._build_picker_lines(prs, "#12")
                   if c == "pr review pr-a")

        def duplicate_identity():
            if duplicate == "display":
                prs[0]["gh_pr_number"] = "12"
            else:
                prs[0]["id"] = "pr-a"

        def on_launch(n):
            if n == len(prefix) + 1:
                duplicate_identity()

        def choose(prompt):
            duplicate_identity()
            return "d"

        selection = f"\n{row}\n" if mode == "enter" else "d\n"
        with patch("builtins.input", side_effect=choose):
            _, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["#13", "#12"], "#12",
                prefix + [(0, selection), (130, "")],
                on_launch=on_launch, has_fzf=mode != "fallback")
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("duplicate", ["display", "local"])
    def test_ambiguous_initial_snapshot_waits_for_dismissal(
            self, tmp_path, monkeypatch, capsys, duplicate):
        prs = [_pr("pr-b", gh_pr_number=13), _pr("pr-a", gh_pr_number=12)]
        prs[0]["gh_pr_number" if duplicate == "display" else "id"] = (
            "12" if duplicate == "display" else "pr-a")
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#13", "#12"], "#12", [(130, "")])
        assert "Could not load PR actions" in capsys.readouterr().out
        assert not fzf.calls
        run_cmd.assert_not_called()

    @pytest.mark.parametrize("statuses", [("merged", "closed"), ("closed", "merged")])
    def test_terminal_only_duplicate_numbers_do_not_block_live_prs(
            self, tmp_path, monkeypatch, statuses):
        prs = [_pr("pr-a", status=statuses[0], gh_pr_number=12),
               _pr("pr-b", status=statuses[1], gh_pr_number=12), _pr("pr-c")]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#12", "pr-c"], "#12",
            [(0, "l\n"), (0, "d\n")])
        assert "No actions — PR is" in fzf.calls[0]["input"]
        run_cmd.assert_called_once_with("pr review pr-c", "pm-x")

    @pytest.mark.parametrize("mode", ["shortcut", "enter", "fresh", "loop", "fallback", "h", "l"])
    def test_selected_terminal_duplicate_keeps_identity(
            self, tmp_path, monkeypatch, capsys, mode):
        from pm_core.cli import session as sess

        prs = [_pr("pr-b", status="closed", gh_pr_number=13),
               _pr("pr-a", gh_pr_number=12)]
        prefix = [(0, "z\n")] * {"fresh": 1, "loop": 2}.get(mode, 0)
        row = next(d for d, c, _ in sess._build_picker_lines(prs, "#12")
                   if c == "pr review pr-a")

        def make_terminal_duplicate():
            prs[0]["gh_pr_number"] = 12
            prs[1]["status"] = "merged"

        def on_launch(n):
            if n == len(prefix) + 1:
                make_terminal_duplicate()
            elif n == len(prefix) + 3:
                prs[1].pop("gh_pr_number")
                prs[1]["status"] = "in_review"

        def choose(prompt):
            make_terminal_duplicate()
            return "d"

        key = mode if mode in ("h", "l") else "d"
        selection = f"\n{row}\n" if mode == "enter" else f"{key}\n"
        script = prefix + [(0, selection), (0, "h\n"), (0, "l\n"),
                           (0, "d\n"), (130, "")]
        with patch("builtins.input", side_effect=choose):
            fzf, run_cmd = _run_picker(
                tmp_path, monkeypatch, prs, ["#12", "pr-a"], "tui", script,
                on_launch=on_launch, has_fzf=mode != "fallback")
        if mode == "fallback":
            assert "No actions — PR is merged." in capsys.readouterr().out
            run_cmd.assert_not_called()
        else:
            for call in fzf.calls[len(prefix) + 1:len(prefix) + 3]:
                assert "No actions — PR is merged." in call["input"]
                assert "s" not in _expect(call)
            run_cmd.assert_called_once_with("pr review pr-a", "pm-x")

    @pytest.mark.parametrize("statuses", [("merged", "in_review"), ("in_review", "merged")])
    def test_live_terminal_number_collision_is_rejected(
            self, tmp_path, monkeypatch, capsys, statuses):
        prs = [_pr("pr-a", status=statuses[0], gh_pr_number=12),
               _pr("pr-b", status=statuses[1], gh_pr_number=12)]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#12"], "#12", [(130, "")])
        assert "Could not load PR actions" in capsys.readouterr().out
        assert not fzf.calls
        run_cmd.assert_not_called()

    def test_duplicate_number_reload_keeps_snapshot_and_recovers(
            self, tmp_path, monkeypatch):
        prs = [_pr("pr-b", gh_pr_number=13), _pr("pr-a", gh_pr_number=12)]

        def on_launch(n):
            if n == 1:
                prs[0]["gh_pr_number"] = 12
            elif n == 2:
                prs[0]["gh_pr_number"] = 13

        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#13", "#12"], "#12",
            [(0, "l\n"), (0, "h\n"), (0, "d\n")], on_launch=on_launch)
        assert [_shown(c) for c in fzf.calls] == [
            "PR Actions — #12  (2/2)",
            "PR Actions — #13  (1/2)",
            "PR Actions — #12  (2/2)",
        ]
        run_cmd.assert_called_once_with("pr review pr-a", "pm-x")

    def test_parse_error_test_restores_popup_environment(self, tmp_path, monkeypatch, capsys):
        import os
        from pm_core.cli import session as sess

        monkeypatch.delenv(sess.tmux_mod.POPUP_SESSION_ENV, raising=False)
        with monkeypatch.context() as isolated:
            self.test_initial_parse_error_waits_for_dismissal(tmp_path, isolated, capsys)
        assert sess.tmux_mod.POPUP_SESSION_ENV not in os.environ

    def test_initial_parse_error_waits_for_dismissal(self, tmp_path, monkeypatch, capsys):
        from pm_core.cli import session as sess

        monkeypatch.setenv(sess.tmux_mod.POPUP_SESSION_ENV, "pm-x")
        reg = tmp_path / "registry.json"
        reg.write_text("{}")
        with patch.object(sess.pane_registry, "registry_path", return_value=reg), \
             patch.object(sess, "_resolve_root_from_session", return_value=tmp_path), \
             patch.object(sess.store, "load", side_effect=sess.store.ProjectYamlParseError("bad YAML")), \
             patch.object(sess, "_wait_dismiss") as dismiss:
            with pytest.raises(SystemExit) as exc:
                sess.popup_picker_cmd.callback("pm-x", "#12")
        assert exc.value.code == 1
        dismiss.assert_called_once()
        assert "Could not load PR actions: bad YAML" in capsys.readouterr().out

    @pytest.mark.parametrize("bad_id", [None, "", "pr-a'", "pr-a b"])
    def test_invalid_initial_id_shows_readable_error(
            self, tmp_path, monkeypatch, capsys, bad_id):
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, [_pr(bad_id, gh_pr_number=12)],
            ["#12"], "#12", [])
        assert "Could not load PR actions" in capsys.readouterr().out
        assert not fzf.calls
        run_cmd.assert_not_called()


class TestPopupPickerFallbackRefresh:
    @pytest.mark.parametrize("choice", ["1", "s", "d"])
    @pytest.mark.parametrize("status", ["merged", "closed"])
    def test_terminal_pr_not_dispatched(self, tmp_path, monkeypatch, capsys,
                                        choice, status):
        prs = [_pr("pr-a")]

        def choose(prompt):
            prs[0]["status"] = status
            return choice

        with patch("builtins.input", side_effect=choose):
            _, run_cmd = _run_picker(tmp_path, monkeypatch, prs, ["pr-a"],
                                     "pr-a", [], has_fzf=False)
        run_cmd.assert_not_called()
        assert f"No actions — PR is {status}." in capsys.readouterr().out

    @pytest.mark.parametrize("choice", ["1", "s"])
    def test_live_pr_still_dispatches(self, tmp_path, monkeypatch, choice):
        with patch("builtins.input", return_value=choice):
            _, run_cmd = _run_picker(tmp_path, monkeypatch, [_pr("pr-a")],
                                     ["pr-a"], "pr-a", [], has_fzf=False)
        run_cmd.assert_called_once_with("pr start pr-a", "pm-x")


class TestPopupPickerEnterSelection:
    PRS = [{"id": "pr-r", "status": "in_review", "title": "Review",
            "gh_pr_number": 240}]

    def test_enter_on_action_row_dispatches(self, tmp_path, monkeypatch):
        """fzf prints an empty --expect key line for Enter; the selected
        row on line 2 must be dispatched, not misread as the key."""
        from pm_core.cli import session as sess

        rows = sess._build_picker_lines(self.PRS, "#240", {"#240"})
        row = next(d for d, c, _ in rows if c and "start" in d)
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self.PRS, ["#240"], "#240",
            [(0, f"\n{row}\n")])
        run_cmd.assert_called_once()
        assert run_cmd.call_args.args[0] == next(c for d, c, _ in rows
                                                 if d == row)

    def test_enter_on_title_row_keeps_picker_open(self, tmp_path, monkeypatch):
        """fzf starts on the title row, which has no command: Enter there
        is a no-op and only q/Esc closes the popup."""
        from pm_core.cli import session as sess

        rows = sess._build_picker_lines(self.PRS, "#240", {"#240"})
        title = next(d for d, c, _ in rows if not c)
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self.PRS, ["#240"], "#240",
            [(0, f"\n{title}\n"), (130, "")])
        assert len(fzf.calls) == 2
        run_cmd.assert_not_called()


class TestPopupPickerTypeAhead:
    """A key typed while the picker reloads reaches fzf before its rows:
    fzf then exits 1 ("no match") but still prints the --expect key."""

    PRS = [
        {"id": "pr-r", "status": "in_review", "title": "Review",
         "gh_pr_number": 240},
        {"id": "pr-q", "status": "qa", "title": "QA", "gh_pr_number": 242},
    ]
    WINDOWS = ["#240", "qa-#242"]

    def test_fzf_waits_for_rows_and_keeps_frame(self, tmp_path, monkeypatch):
        fzf, _ = _run_picker(tmp_path, monkeypatch, self.PRS, self.WINDOWS,
                             "#240", [(130, "")])
        assert "--sync" in fzf.calls[0]["cmd"]
        # No empty popup flashed between relaunches on each nav key.
        assert "--no-clear" in fzf.calls[0]["cmd"]

    def test_no_match_exit_with_nav_key_navigates(self, tmp_path, monkeypatch):
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self.PRS, self.WINDOWS, "#240",
            [(1, "l\n"), (1, ""), (0, "h\n"), (130, "")])
        assert [_shown(c) for c in fzf.calls] == [
            "PR Actions — #240  (1/2)",
            "PR Actions — #242  (2/2)",
            "PR Actions — #242  (2/2)",
            "PR Actions — #240  (1/2)",
        ]
        run_cmd.assert_not_called()

    def test_screen_cleared_before_dispatch(self, tmp_path, monkeypatch, capsys):
        """The kept frame must not sit under the command's output/errors."""
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self.PRS, self.WINDOWS, "#240",
            [(0, "s\n")])
        run_cmd.assert_called_once()
        assert "\033[2J" in capsys.readouterr().out
