"""Tests for the action-based popup PR picker logic."""

from unittest.mock import patch, MagicMock

from pm_core.cli.session import (
    _actions_for_status,
    _status_phase,
    _current_window_pr_id,
    _build_picker_lines,
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
        for status in ("pending", "in_progress", "in_review", "qa"):
            actions = _actions_for_status(status)
            labels = [a[0] for a in actions]
            assert labels == ["start", "edit", "review", "qa", "merge"]

    def test_merged_has_no_actions(self):
        assert _actions_for_status("merged") == []

    def test_closed_has_no_actions(self):
        assert _actions_for_status("closed") == []

    def test_unknown_status_returns_all_actions(self):
        """Non-terminal unknown statuses still get all actions."""
        labels = [a[0] for a in _actions_for_status("bogus")]
        assert labels == ["start", "edit", "review", "qa", "merge"]

    def test_qa_command_routes_through_tui(self):
        actions = _actions_for_status("in_progress")
        qa_cmd = next(cmd for label, cmd in actions if label == "qa")
        assert qa_cmd.startswith("tui:")

    def test_zz_d_chord_routes_review_loop_through_tui(self):
        from pm_core.cli.session import _MODIFIED_ACTION_CMDS
        rl_cmd = _MODIFIED_ACTION_CMDS[("zz", "review")]
        assert rl_cmd.startswith("tui:review-loop")

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

    def test_only_window_actions_get_rows(self):
        # start / review / qa / merge each have their own window and
        # should appear; edit and review-loop are shortcut-only.
        prs = [_pr("pr-001", "pending", "New PR", gh_pr_number=158)]
        lines = _build_picker_lines(prs, "#158")
        action_lines = [d for d, cmd, _ in lines if cmd]
        assert len(action_lines) == 4
        assert any("start" in d for d in action_lines)
        assert any("review" in d and "review-loop" not in d
                   for d in action_lines)
        assert any("qa" in d for d in action_lines)
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

    def test_run_picker_command_silent_on_success(self):
        """Successful direct-CLI dispatch should not block waiting for a
        keypress (popup closes promptly)."""
        fake_result = MagicMock(returncode=0, stdout="", stderr="")
        with patch("pm_core.cli.session.subprocess.run", return_value=fake_result), \
             patch("pm_core.cli.session._wait_dismiss") as wait_mock:
            _run_picker_command("pr start pr-123", "sess")
        assert not wait_mock.called


class TestOpenPaneForPr:
    """Picker shortcuts c/i/Q open a split pane in the launching window."""

    def _patches(self):
        return (
            patch("pm_core.cli.session.tmux_mod.find_window_by_name",
                  return_value={"id": "@7", "index": "3", "name": "main"}),
            patch("pm_core.cli.session.tmux_mod.split_pane",
                  return_value="%42"),
            patch("pm_core.cli.session.pane_registry.register_pane"),
            patch("pm_core.cli.session._wait_dismiss"),
        )

    def test_shell_no_workdir_errors(self, tmp_path):
        from pm_core.cli.session import _open_pane_for_pr
        find, split, reg, dismiss = self._patches()
        with find, split as split_mock, reg, dismiss as dismiss_mock:
            _open_pane_for_pr("sess", "main",
                              {"id": "pr-001", "workdir": None},
                              "shell", tmp_path)
        assert not split_mock.called
        assert dismiss_mock.called

    def test_shell_with_workdir_splits_and_registers(self, tmp_path):
        from pm_core.cli.session import _open_pane_for_pr
        wd = tmp_path / "work"
        wd.mkdir()
        find, split, reg, dismiss = self._patches()
        with find, split as split_mock, reg as reg_mock, dismiss:
            _open_pane_for_pr("sess", "main",
                              {"id": "pr-001", "workdir": str(wd)},
                              "shell", tmp_path)
        assert split_mock.called
        assert split_mock.call_args.kwargs.get("window") == "main"
        cmd = split_mock.call_args.args[2]
        assert str(wd) in cmd
        assert reg_mock.called
        assert reg_mock.call_args.args[3] == "pr-shell"

    def test_impl_spec_missing_errors(self, tmp_path):
        from pm_core.cli.session import _open_pane_for_pr
        find, split, reg, dismiss = self._patches()
        with find, split as split_mock, reg, dismiss as dismiss_mock:
            _open_pane_for_pr("sess", "main", {"id": "pr-001"},
                              "impl-spec", tmp_path)
        assert not split_mock.called
        assert dismiss_mock.called

    def test_impl_spec_present_opens_pane(self, tmp_path):
        from pm_core.cli.session import _open_pane_for_pr
        spec_dir = tmp_path / "specs" / "pr-001"
        spec_dir.mkdir(parents=True)
        (spec_dir / "impl.md").write_text("# spec\n")
        find, split, reg, dismiss = self._patches()
        with find, split as split_mock, reg as reg_mock, dismiss:
            _open_pane_for_pr("sess", "main", {"id": "pr-001"},
                              "impl-spec", tmp_path)
        cmd = split_mock.call_args.args[2]
        assert "impl.md" in cmd
        assert "glow" in cmd
        assert reg_mock.call_args.args[3] == "pr-impl-spec"

    def test_qa_spec_prefers_workdir_copy(self, tmp_path):
        from pm_core.cli.session import _open_pane_for_pr
        canon = tmp_path / "specs" / "pr-001"
        canon.mkdir(parents=True)
        (canon / "qa.md").write_text("canonical\n")
        wd = tmp_path / "work"
        (wd / "pm" / "specs" / "pr-001").mkdir(parents=True)
        wd_spec = wd / "pm" / "specs" / "pr-001" / "qa.md"
        wd_spec.write_text("fresh\n")
        find, split, reg, dismiss = self._patches()
        with find, split as split_mock, reg, dismiss:
            _open_pane_for_pr("sess", "main",
                              {"id": "pr-001", "workdir": str(wd)},
                              "qa-spec", tmp_path)
        cmd = split_mock.call_args.args[2]
        assert str(wd_spec) in cmd

    def test_diff_no_workdir_errors(self, tmp_path):
        from pm_core.cli.session import _open_pane_for_pr
        find, split, reg, dismiss = self._patches()
        with find, split as split_mock, reg, dismiss as dismiss_mock:
            _open_pane_for_pr("sess", "main",
                              {"id": "pr-001", "workdir": None},
                              "diff", tmp_path,
                              data={"project": {"base_branch": "master"}})
        assert not split_mock.called
        assert dismiss_mock.called

    def test_diff_present_opens_pane(self, tmp_path):
        from pm_core.cli.session import _open_pane_for_pr
        wd = tmp_path / "work"
        wd.mkdir()
        find, split, reg, dismiss = self._patches()
        data = {"project": {"base_branch": "main", "backend": "github"}}
        with find, split as split_mock, reg as reg_mock, dismiss:
            _open_pane_for_pr("sess", "main",
                              {"id": "pr-001", "workdir": str(wd),
                               "title": "x"},
                              "diff", tmp_path, data=data)
        cmd = split_mock.call_args.args[2]
        assert "git --no-pager diff" in cmd
        assert "origin/main...HEAD" in cmd
        assert "less -R" in cmd
        assert reg_mock.call_args.args[3] == "pr-diff"

    def test_diff_local_backend_uses_bare_base(self, tmp_path):
        from pm_core.cli.session import _open_pane_for_pr
        wd = tmp_path / "work"
        wd.mkdir()
        find, split, reg, dismiss = self._patches()
        data = {"project": {"base_branch": "master", "backend": "local"}}
        with find, split as split_mock, reg, dismiss:
            _open_pane_for_pr("sess", "main",
                              {"id": "pr-001", "workdir": str(wd),
                               "title": "t"},
                              "diff", tmp_path, data=data)
        cmd = split_mock.call_args.args[2]
        assert "master...HEAD" in cmd
        assert "origin/master" not in cmd


class TestPrCliPaneCommands:
    """CLI parity for pr shell / view-spec / view-diff."""

    def test_view_spec_outside_tmux_prints_to_stdout(self, tmp_path, capsys):
        from pm_core.cli.pr import _open_pane_for_pr_cli
        spec_dir = tmp_path / "specs" / "pr-001"
        spec_dir.mkdir(parents=True)
        (spec_dir / "impl.md").write_text("# the spec\n")
        with patch("pm_core.cli.pr._get_pm_session", return_value=None):
            _open_pane_for_pr_cli({"id": "pr-001", "title": "t"},
                                  "impl-spec", {}, tmp_path)
        out = capsys.readouterr().out
        assert "# the spec" in out

    def test_view_spec_missing_errors(self, tmp_path):
        from pm_core.cli.pr import _open_pane_for_pr_cli
        with patch("pm_core.cli.pr._get_pm_session", return_value=None):
            try:
                _open_pane_for_pr_cli({"id": "pr-001"}, "impl-spec", {},
                                      tmp_path)
            except SystemExit as e:
                assert e.code == 1
            else:
                assert False, "expected SystemExit"

    def test_view_diff_outside_tmux_runs_subprocess(self, tmp_path):
        from pm_core.cli.pr import _open_pane_for_pr_cli
        wd = tmp_path / "work"
        wd.mkdir()
        data = {"project": {"base_branch": "main", "backend": "github"}}
        with patch("pm_core.cli.pr._get_pm_session", return_value=None), \
             patch("pm_core.cli.pr.subprocess.run") as run_mock:
            _open_pane_for_pr_cli({"id": "pr-001", "workdir": str(wd),
                                   "title": "x"},
                                  "diff", data, tmp_path)
        assert run_mock.called
        cmd = run_mock.call_args.args[0]
        assert cmd[0] == "/bin/bash"
        # No piping to less for stdout invocation.
        assert "less -R" not in cmd[2]
        assert "origin/main...HEAD" in cmd[2]

    def test_shell_in_pm_tmux_splits_pane(self, tmp_path):
        from pm_core.cli.pr import _open_pane_for_pr_cli
        wd = tmp_path / "work"
        wd.mkdir()
        with patch("pm_core.cli.pr._get_pm_session", return_value="pm-x"), \
             patch("pm_core.cli.pr.tmux_mod.in_tmux", return_value=True), \
             patch("pm_core.cli.pr.tmux_mod.session_exists", return_value=True), \
             patch("pm_core.cli.pr._current_tmux_window_id", return_value="@5"), \
             patch("pm_core.cli.pr.tmux_mod.split_pane",
                   return_value="%9") as split_mock, \
             patch("pm_core.cli.pr.pane_registry.register_pane") as reg_mock:
            _open_pane_for_pr_cli({"id": "pr-001", "workdir": str(wd)},
                                  "shell", {}, tmp_path)
        assert split_mock.called
        assert split_mock.call_args.kwargs.get("window") == "@5"
        assert str(wd) in split_mock.call_args.args[2]
        assert reg_mock.call_args.args[3] == "pr-shell"

    def test_build_diff_cmd_keep_pane_open_appends_exec_shell(self):
        from pm_core.cli.pr import _build_diff_cmd
        cmd = _build_diff_cmd("/tmp/wd", "#1", "title", "main", "github",
                              shell="/bin/zsh")
        assert cmd.endswith("; exec /bin/zsh")
        assert "| less -R" in cmd

    def test_build_diff_cmd_stdout_variant_no_less_no_exec(self):
        from pm_core.cli.pr import _build_diff_cmd
        cmd = _build_diff_cmd("/tmp/wd", "#1", "t", "main", "github",
                              pipe_to_less=False, keep_pane_open=False)
        assert "less" not in cmd
        assert "exec" not in cmd
