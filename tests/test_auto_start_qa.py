"""Tests for review-to-QA auto-transition via auto-start.

Covers scenario 8 steps:
 - _auto_start_qa_loops detects PRs in "qa" status and starts QA
 - Target PR scoping (only starts QA for transitive deps of target)
 - Skips PRs already running QA or with existing verdicts
 - _maybe_start_qa transitions PR from in_review → qa when review passes
 - Race guard between poll_qa_state completion handler and auto-start
 - Auto-start disabled → no QA loops started
"""

import pytest
from unittest.mock import patch, MagicMock, call

from pm_core.qa_loop import QALoopState, VERDICT_PASS, VERDICT_NEEDS_WORK
from pm_core import store


def _make_app(tmp_path, *, prs=None, auto_start=True, target=None):
    """Create a mock TUI app with PRs on disk."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir(exist_ok=True)
    if prs is None:
        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "qa", "workdir": str(tmp_path / "wd"),
                "notes": []}]
    data = {
        "project": {"name": "test", "repo": "/tmp/r", "base_branch": "master"},
        "prs": prs,
    }
    store.save(data, pm_dir)

    app = MagicMock()
    app._root = pm_dir
    app._data = data
    app._auto_start = auto_start
    app._auto_start_targets = {target: {}} if target else {}
    app._auto_start_all = not target
    app._auto_start_run_id = None
    app._qa_loops = {}
    app._review_loops = {}
    app._self_driving_qa = {}
    return app


# ---------------------------------------------------------------------------
# _auto_start_qa_loops: basic detection
# ---------------------------------------------------------------------------

class TestAutoStartQALoopsDetection:
    """_auto_start_qa_loops detects PRs in 'qa' status and starts QA."""

    def test_starts_qa_for_qa_status_pr(self, tmp_path):
        """When auto-start is enabled and PR is in 'qa' status, starts QA."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_called_once_with(app, "pr-001")

    def test_skips_non_qa_status_prs(self, tmp_path):
        """PRs not in 'qa' status are not started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-001", "title": "T", "branch": "b",
             "status": "in_review", "workdir": str(tmp_path / "wd"), "notes": []},
            {"id": "pr-002", "title": "T2", "branch": "b2",
             "status": "in_progress", "workdir": str(tmp_path / "wd2"), "notes": []},
            {"id": "pr-003", "title": "T3", "branch": "b3",
             "status": "merged", "workdir": str(tmp_path / "wd3"), "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_disabled_auto_start_skips_all(self, tmp_path):
        """When auto-start is disabled, no QA loops are started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=False)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_skips_pr_without_workdir(self, tmp_path):
        """PRs in 'qa' status but without a workdir are skipped."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "qa", "workdir": "", "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_starts_multiple_qa_prs(self, tmp_path):
        """Multiple PRs in 'qa' status all get started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-001", "title": "T1", "branch": "b1",
             "status": "qa", "workdir": str(tmp_path / "wd1"), "notes": []},
            {"id": "pr-002", "title": "T2", "branch": "b2",
             "status": "qa", "workdir": str(tmp_path / "wd2"), "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        assert mock_start.call_count == 2
        mock_start.assert_any_call(app, "pr-001")
        mock_start.assert_any_call(app, "pr-002")


# ---------------------------------------------------------------------------
# Target PR scoping
# ---------------------------------------------------------------------------

class TestAutoStartQATargetScoping:
    """_auto_start_qa_loops respects target PR scoping."""

    def test_with_target_only_starts_deps(self, tmp_path):
        """When target is set, only starts QA for PRs in its dep tree."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-001", "title": "Dep", "branch": "b1",
             "status": "qa", "workdir": str(tmp_path / "wd1"),
             "depends_on": [], "notes": []},
            {"id": "pr-002", "title": "Target", "branch": "b2",
             "status": "qa", "workdir": str(tmp_path / "wd2"),
             "depends_on": ["pr-001"], "notes": []},
            {"id": "pr-003", "title": "Unrelated", "branch": "b3",
             "status": "qa", "workdir": str(tmp_path / "wd3"),
             "depends_on": [], "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-002")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)

        # pr-001 (dep of target) and pr-002 (target itself) should start
        # pr-003 (unrelated) should be skipped
        assert mock_start.call_count == 2
        started_ids = {c.args[1] for c in mock_start.call_args_list}
        assert started_ids == {"pr-001", "pr-002"}

    def test_without_target_starts_all_qa_prs(self, tmp_path):
        """Without a target, all qa-status PRs are started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-001", "title": "T1", "branch": "b1",
             "status": "qa", "workdir": str(tmp_path / "wd1"), "notes": []},
            {"id": "pr-002", "title": "T2", "branch": "b2",
             "status": "qa", "workdir": str(tmp_path / "wd2"), "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)

        assert mock_start.call_count == 2

    def test_transitive_deps_included(self, tmp_path):
        """Transitive deps (not just direct) of target are included."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        prs = [
            {"id": "pr-a", "title": "Root dep", "branch": "ba",
             "status": "qa", "workdir": str(tmp_path / "wda"),
             "depends_on": [], "notes": []},
            {"id": "pr-b", "title": "Mid dep", "branch": "bb",
             "status": "qa", "workdir": str(tmp_path / "wdb"),
             "depends_on": ["pr-a"], "notes": []},
            {"id": "pr-c", "title": "Target", "branch": "bc",
             "status": "qa", "workdir": str(tmp_path / "wdc"),
             "depends_on": ["pr-b"], "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-c")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app, prs=prs)

        # All three: pr-a (transitive), pr-b (direct dep), pr-c (target)
        assert mock_start.call_count == 3
        started_ids = {c.args[1] for c in mock_start.call_args_list}
        assert started_ids == {"pr-a", "pr-b", "pr-c"}


# ---------------------------------------------------------------------------
# Skip already running QA or existing verdicts
# ---------------------------------------------------------------------------

class TestAutoStartQASkipRunning:
    """_auto_start_qa_loops skips PRs already running QA or with verdicts."""

    def test_skips_running_qa(self, tmp_path):
        """PRs with a running QA loop are skipped."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)

        # Simulate running QA loop
        state = QALoopState(pr_id="pr-001")
        state.running = True
        app._qa_loops["pr-001"] = state

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_skips_completed_with_verdict(self, tmp_path):
        """PRs with a verdict (awaiting poll_qa_state processing) are skipped."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)

        # Simulate completed QA loop (not running, but has verdict)
        state = QALoopState(pr_id="pr-001")
        state.running = False
        state.latest_verdict = VERDICT_PASS
        app._qa_loops["pr-001"] = state

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_starts_qa_when_loop_entry_absent(self, tmp_path):
        """PR in 'qa' status with no loop entry gets started."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)
        # No entry in _qa_loops at all
        assert "pr-001" not in app._qa_loops

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_called_once_with(app, "pr-001")

    def test_starts_qa_when_old_loop_cleaned_up(self, tmp_path):
        """After poll_qa_state removes a completed loop, auto-start restarts."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)
        # Simulate that poll_qa_state already cleaned up the entry
        # (no entry in _qa_loops)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_called_once_with(app, "pr-001")


    def test_skips_run_driven_by_another_live_process(self, tmp_path,
                                                       monkeypatch):
        """A live ``pm pr qa-run-bg`` driver of this session (its start
        record names it) is not started over: a TUI loop would kill its
        windows as stale and QA the PR twice (RQ47 b)."""
        import json, subprocess
        from pm_core import qa_loop
        from pm_core.tui.auto_start import _auto_start_qa_loops

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(qa_loop, "get_pm_session", lambda: "pm-own")
        app = _make_app(tmp_path, auto_start=True)
        qa_wd = tmp_path / ".pm" / "workdirs" / "qa" / "pr-001-abc"
        qa_wd.mkdir(parents=True)
        driver = subprocess.Popen(["sleep", "30"])
        try:
            rec = {"pr_id": "pr-001", "loop_id": "abc", "session_tag": "own",
                   "started_at": 1.0, "owner_pid": driver.pid,
                   "owner_start": qa_loop._proc_start_time(driver.pid)}
            (qa_wd / "qa_run.json").write_text(json.dumps(rec))
            with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
                _auto_start_qa_loops(app)
            mock_start.assert_not_called()
        finally:
            driver.kill()
            driver.wait()
        # Once the driver is gone its record no longer holds the PR back.
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)
        mock_start.assert_called_once_with(app, "pr-001")

    def test_own_or_ownerless_run_record_does_not_block(self, tmp_path,
                                                        monkeypatch):
        """This process's own runs (a TUI restart execs in place) and records
        written before they named an owner do not count as another driver."""
        import json, os
        from pm_core import qa_loop
        from pm_core.tui.auto_start import _auto_start_qa_loops

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(qa_loop, "get_pm_session", lambda: "pm-own")
        app = _make_app(tmp_path, auto_start=True)
        qa_root = tmp_path / ".pm" / "workdirs" / "qa"
        for name, extra in (("pr-001-a", {"owner_pid": os.getpid()}),
                            ("pr-001-b", {})):
            (qa_root / name).mkdir(parents=True)
            (qa_root / name / "qa_run.json").write_text(json.dumps(
                {"pr_id": "pr-001", "session_tag": "own", "started_at": 1.0,
                 **extra}))
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)
        mock_start.assert_called_once_with(app, "pr-001")


class TestRunDrivenElsewhereRecheck:
    """S111: auto-start and the review -> QA hand-off leave a run another
    live process drives (a ``pm qa run`` the user started, a qa-run-bg
    driver) alone, and look again once it may be over: an instruction run
    ends without a PR verdict, so full QA is still due then."""

    @pytest.fixture
    def driver(self, tmp_path, monkeypatch):
        import json, subprocess
        from pm_core import qa_loop
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(qa_loop, "get_pm_session", lambda: "pm-own")
        qa_wd = tmp_path / ".pm" / "workdirs" / "qa" / "pr-001-cli-pr-001"
        qa_wd.mkdir(parents=True)
        proc = subprocess.Popen(["sleep", "30"])
        (qa_wd / "qa_run.json").write_text(json.dumps(
            {"pr_id": "pr-001", "loop_id": "cli-pr-001", "session_tag": "own",
             "started_at": 1.0, "owner_pid": proc.pid,
             "owner_start": qa_loop._proc_start_time(proc.pid)}))
        yield proc
        proc.kill()
        proc.wait()

    def _app(self, tmp_path, status):
        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": status, "workdir": str(tmp_path / "wd"),
                "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-001")
        app._driver_recheck = False
        return app

    def test_auto_start_pass_rechecks_while_the_run_lives(self, tmp_path,
                                                          driver):
        from pm_core.tui import auto_start
        app = self._app(tmp_path, "qa")
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            auto_start._auto_start_qa_loops(app)
            auto_start._auto_start_qa_loops(app)
        mock_start.assert_not_called()
        # One pending re-check, however many passes skipped the PR.
        app.set_timer.assert_called_once()
        delay, fire = app.set_timer.call_args.args
        assert delay == auto_start.DRIVER_RECHECK_SECONDS
        with patch.object(auto_start, "check_and_start", MagicMock()) as cas:
            fire()
        app.run_worker.assert_called_once_with(cas.return_value)
        assert app._driver_recheck is False
        # The run is over: the next pass starts full QA.
        driver.kill()
        driver.wait()
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            auto_start._auto_start_qa_loops(app)
        mock_start.assert_called_once_with(app, "pr-001")

    def test_review_pass_hand_off_leaves_the_run_alone(self, tmp_path,
                                                        driver):
        from pm_core.tui.review_loop_ui import _maybe_start_qa
        from pm_core import runtime_state
        app = self._app(tmp_path, "in_review")
        # An earlier QA run's PASS, from before this review.
        runtime_state.set_action_state("pr-001", "qa", "done", verdict="PASS")
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            assert _maybe_start_qa(app, "pr-001")[0] == "driven"
        mock_start.assert_not_called()
        # It must not read as this review's QA result (sign-off catch-up).
        assert runtime_state.get_action_state("pr-001", "qa") == {}
        assert store.get_pr(store.load(app._root), "pr-001")["status"] == "qa"

    def _hand_off(self, app):
        from pm_core.tui.review_loop_ui import (
            _pending_auto_qa, _start_qa_after_review)
        _start_qa_after_review(app, "pr-001")
        return _pending_auto_qa(app)

    def test_hand_off_keeps_a_live_drivers_running_entry(self, tmp_path,
                                                         driver):
        from pm_core import runtime_state
        app = self._app(tmp_path, "in_review")
        panes = {"s1": {"pane_id": "%1", "session_id": "x"}}
        runtime_state.set_action_state("pr-001", "qa", "running",
                                       panes=panes)
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            pending = self._hand_off(app)
        mock_start.assert_not_called()
        assert pending["pr-001"][0] == "driven"
        rec = runtime_state.get_action_state("pr-001", "qa")
        assert rec["state"] == "running" and rec["panes"] == panes

    def test_zz_t_hand_off_starts_qa_once_the_cli_run_ends(self, tmp_path,
                                                           driver):
        """Auto-start off: only the pending hand-off can start full QA
        after a ``pm qa run`` (no PR verdict) ends."""
        app = self._app(tmp_path, "in_review")
        app._auto_start = False
        app._self_driving_qa = {"pr-001": {"required_passes": 1}}
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            pending = self._hand_off(app)
            self._hand_off(app)  # a poll tick while the run lives
            mock_start.assert_not_called()
            assert pending["pr-001"][0] == "driven"
            driver.kill()
            driver.wait()
            self._hand_off(app)
        mock_start.assert_called_once()
        assert "pr-001" not in pending

    def test_hand_off_takes_the_drivers_verdict_as_its_qa(self, tmp_path,
                                                          driver):
        from pm_core import runtime_state
        app = self._app(tmp_path, "in_review")
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            pending = self._hand_off(app)
            assert pending["pr-001"][0] == "driven"
            # The qa-run-bg driver finishes and records its verdict.
            runtime_state.set_action_state("pr-001", "qa", "done",
                                           verdict="PASS")
            driver.kill()
            driver.wait()
            self._hand_off(app)
        mock_start.assert_not_called()
        assert "pr-001" not in pending
        assert runtime_state.get_action_state("pr-001", "qa")["verdict"] \
            == "PASS"


# ---------------------------------------------------------------------------
# Race guard: poll_qa_state vs auto-start
# ---------------------------------------------------------------------------

class TestRaceGuard:
    """Race guard prevents auto-start from restarting QA before poll_qa_state runs."""

    def test_race_window_protected_by_latest_verdict(self, tmp_path):
        """In the race window (running=False, verdict set, poll not yet run),
        auto-start must NOT restart QA."""
        from pm_core.tui.auto_start import _auto_start_qa_loops

        app = _make_app(tmp_path, auto_start=True)

        # This is the race window: QA thread finished (running=False),
        # verdict is set, but poll_qa_state hasn't processed it yet
        state = QALoopState(pr_id="pr-001")
        state.running = False
        state.latest_verdict = VERDICT_NEEDS_WORK
        state._ui_complete_notified = False  # poll hasn't run yet
        app._qa_loops["pr-001"] = state

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)

        mock_start.assert_not_called()

    def test_after_poll_cleanup_finished_pass_is_not_relaunched(self, tmp_path):
        """After poll_qa_state removes the loop entry, the PASS stays recorded
        in runtime_state, so auto-start does not re-run the finished QA (it
        awaits sign-off); once a new QA run is recorded it may restart."""
        from pm_core.tui.auto_start import _auto_start_qa_loops
        from pm_core.tui.qa_loop_ui import poll_qa_state

        app = _make_app(tmp_path, auto_start=True)

        # Set up a completed loop
        state = QALoopState(pr_id="pr-001")
        state.running = False
        state.latest_verdict = VERDICT_PASS
        state._ui_complete_notified = False
        app._qa_loops["pr-001"] = state

        # First poll: marks _ui_complete_notified, calls _on_qa_complete
        with patch("pm_core.tui.qa_loop_ui._on_qa_complete"):
            poll_qa_state(app)
        assert state._ui_complete_notified is True
        assert "pr-001" in app._qa_loops  # still present for one cycle

        # Second poll: removes the entry
        with patch("pm_core.tui.qa_loop_ui._on_qa_complete"):
            poll_qa_state(app)
        assert "pr-001" not in app._qa_loops

        # The finished PASS is not relaunched by the scheduler
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)
        mock_start.assert_not_called()

        # A newer QA run (e.g. started with 't') replaces the record
        from pm_core import runtime_state
        runtime_state.set_action_state("pr-001", "qa", "running")
        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _auto_start_qa_loops(app)
        mock_start.assert_called_once_with(app, "pr-001")


# ---------------------------------------------------------------------------
# _maybe_start_qa: review-to-QA transition
# ---------------------------------------------------------------------------

class TestMaybeStartQA:
    """_maybe_start_qa transitions PR from in_review → qa on review pass."""

    def test_transitions_pr_to_qa_status(self, tmp_path):
        """When review passes, PR status transitions from in_review to qa."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "in_review", "workdir": str(tmp_path / "wd"),
                "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-001")

        with patch("pm_core.tui.qa_loop_ui.start_qa"):
            _maybe_start_qa(app, "pr-001")

        # Verify the PR status changed on disk
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"

    def test_starts_qa_loop_after_transition(self, tmp_path):
        """After transitioning to qa, a QA loop is started."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "in_review", "workdir": str(tmp_path / "wd"),
                "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-001")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        mock_start.assert_called_once_with(
            app, "pr-001", lock_timeout=0.0)  # store.NO_WAIT: retried per tick (RQ38)

    def test_no_transition_when_auto_start_disabled(self, tmp_path):
        """Without auto-start (and no self-driving), no transition occurs."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "in_review", "workdir": str(tmp_path / "wd"),
                "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=False)

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        mock_start.assert_not_called()
        # PR should remain in_review
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_scoped_to_target_deps(self, tmp_path):
        """PR outside the target's dep tree is not transitioned."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [
            {"id": "pr-001", "title": "Unrelated", "branch": "b1",
             "status": "in_review", "workdir": str(tmp_path / "wd1"),
             "depends_on": [], "notes": []},
            {"id": "pr-002", "title": "Target", "branch": "b2",
             "status": "in_progress", "workdir": str(tmp_path / "wd2"),
             "depends_on": [], "notes": []},
        ]
        app = _make_app(tmp_path, prs=prs, auto_start=True, target="pr-002")

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        # pr-001 is not in pr-002's dep tree, so no transition
        mock_start.assert_not_called()
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "in_review"

    def test_self_driving_bypasses_auto_start_check(self, tmp_path):
        """In self-driving mode, _maybe_start_qa works even without auto-start."""
        from pm_core.tui.review_loop_ui import _maybe_start_qa

        prs = [{"id": "pr-001", "title": "T", "branch": "b",
                "status": "in_review", "workdir": str(tmp_path / "wd"),
                "notes": []}]
        app = _make_app(tmp_path, prs=prs, auto_start=False)
        # Set up self-driving state
        app._self_driving_qa = {"pr-001": {"strict": False, "pass_count": 0,
                                            "required_passes": 1}}

        with patch("pm_core.tui.qa_loop_ui.start_qa") as mock_start:
            _maybe_start_qa(app, "pr-001")

        mock_start.assert_called_once_with(
            app, "pr-001", lock_timeout=0.0)  # store.NO_WAIT: retried per tick (RQ38)
        data = store.load(app._root)
        pr = store.get_pr(data, "pr-001")
        assert pr["status"] == "qa"


# ---------------------------------------------------------------------------
# check_and_start integration: calls _auto_start_qa_loops
# ---------------------------------------------------------------------------

class TestCheckAndStartCallsQALoops:
    """check_and_start calls _auto_start_qa_loops after processing ready PRs."""

    def test_check_and_start_triggers_qa_loops(self, tmp_path):
        """check_and_start calls _auto_start_qa_loops at the end."""
        import asyncio
        from pm_core.tui.auto_start import check_and_start

        app = _make_app(tmp_path, auto_start=True)

        with patch("pm_core.tui.auto_start._auto_start_qa_loops") as mock_qa, \
             patch("pm_core.tui.auto_start._auto_start_review_loops"):
            asyncio.run(check_and_start(app))

        mock_qa.assert_called_once()
