"""Tests for the action-based popup PR picker logic."""

from unittest.mock import patch, MagicMock

from pm_core.cli.session import (
    _actions_for_status,
    _status_phase,
    _current_window_pr_id,
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

        def fake_active(name):
            # base unattached → None; two grouped sessions attached.
            return {"base~1": "@2", "base~2": "@5"}.get(name)

        with patch("pm_core.cli.session.tmux_mod") as tmux:
            tmux.list_grouped_sessions.return_value = ["base~1", "base~2"]
            tmux.attached_active_window.side_effect = fake_active
            result = _session_active_windows("base")

        assert result == {"base~1": "@2", "base~2": "@5"}
        tmux.list_grouped_sessions.assert_called_once_with("base")


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
                on_launch=None):
    """Drive popup_picker_cmd end to end with a fake fzf.

    ``prs`` is re-read on every project.yaml load, so a test can mutate it
    from ``on_launch(n)`` (called before the n-th fzf launch returns) to
    simulate a PR being merged while the popup is open.
    """
    from pm_core.cli import session as sess

    reg = tmp_path / "registry.json"
    reg.write_text("{}")
    monkeypatch.setenv("PM_PROJECT", str(tmp_path))
    fzf = _FakeFzf(script, on_launch)
    run_cmd = MagicMock()
    with patch.object(sess.pane_registry, "registry_path", return_value=reg), \
         patch.object(sess, "_resolve_root_from_session", return_value=tmp_path), \
         patch.object(sess.store, "load",
                      side_effect=lambda *a, **k: {"prs": [dict(p) for p in prs]}), \
         patch.object(sess.tmux_mod, "list_windows",
                      return_value=[{"name": n, "id": f"@{i}"}
                                    for i, n in enumerate(windows)]), \
         patch.object(sess, "_session_active_windows", return_value={}), \
         patch.object(sess, "_fzf_supports_no_input", return_value=True), \
         patch.object(sess, "_wait_dismiss"), \
         patch.object(sess, "_run_picker_command", run_cmd), \
         patch("shutil.which", return_value="/usr/bin/fzf"), \
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

    def test_unresolvable_window_reports_lookup_failure(self, tmp_path, monkeypatch, caplog):
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
        assert log.warning.called
        assert _header(second).startswith("PR Actions — #240")
        run_cmd.assert_not_called()

    def test_single_actionless_pr_does_not_exit_on_keypress(self, tmp_path, monkeypatch):
        """Only PR is merged: no accept keys at all, Enter is ignored, and
        only q/Esc (fzf abort) closes the popup."""
        prs = [self.PRS[0]]
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, prs, ["#238"], "#238", [(130, "")])
        (call,) = fzf.calls
        assert not any(a.startswith("--expect") for a in call["cmd"])
        assert "enter:ignore" in next(a for a in call["cmd"]
                                      if a.startswith("--bind="))
        run_cmd.assert_not_called()

    def test_local_id_window_resolves_to_display_id(self, tmp_path, monkeypatch):
        """Window named pr-r (before #240 existed) resolves to #240's actions."""
        fzf, run_cmd = _run_picker(
            tmp_path, monkeypatch, self.PRS, ["pr-r"], "pr-r", [(0, "s\n")])
        assert _header(fzf.calls[0]).startswith("PR Actions — #240")
        assert "pr-r" in run_cmd.call_args.args[0]


def _shown(call):
    """(header PR position line, notice-or-first row) for one fzf launch."""
    return _header(call).splitlines()[0]


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
