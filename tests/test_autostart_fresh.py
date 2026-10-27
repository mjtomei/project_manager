"""Explicit fresh autostart (``z O``/``z A`` / ``pm autostart fresh``).

A reviewed PR is returned to implementation after user feedback: the live
implementation session is adopted, obsolete review/QA/sign-off state is
retired, and auto-start waits for the current implementation turn before
starting exactly one fresh review.

The repo has no pytest-asyncio plugin: async bodies run via ``asyncio.run``.
"""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pm_core import autostart_state as st
from pm_core import store
from pm_core.autostart_state import FRESH_KEY, POLICY_STOP
from pm_core.qa_loop import QALoopState
from pm_core.review_loop import ReviewLoopState
from pm_core.tui import autostart_fresh
from pm_core.tui import auto_start


OLD = "2026-01-01T00:00:00+00:00"


def _pr(pid="pr-a", status="in_review", **extra):
    d = {"id": pid, "title": f"T {pid}", "branch": f"b-{pid}",
         "status": status, "depends_on": [], "notes": [],
         "workdir": f"/tmp/wd-{pid}", "started_at": OLD}
    d.update(extra)
    return d


class FakeApp:
    def __init__(self, prs, root=None):
        self._data = {"project": {"name": "t", "repo": "/r",
                                  "base_branch": "master"}, "prs": prs}
        self._root = root
        self._auto_start = False
        self._auto_start_targets = {}
        self._auto_start_all = False
        self._auto_start_run_id = None
        self._auto_start_launching = set()
        self._stop_before_merge = set()
        self._review_loops = {}
        self._qa_loops = {}
        self._self_driving_qa = {}
        self._pending_merge_prs = set()
        self._merge_input_required_prs = set()
        self._session_name = None
        self._pane_idle_tracker = None
        self._review_loop_timer = None
        self._watcher_manager = MagicMock()
        self._watcher_manager.find_by_type.return_value = None
        self.logs = []
        self.workers = []

    def log_message(self, msg, **kw):
        self.logs.append(msg)

    def _update_display(self):
        pass

    def _load_state(self):
        pass

    def set_interval(self, *a, **kw):
        return MagicMock()

    def run_worker(self, coro, *a, **kw):
        self.workers.append(coro)
        if asyncio.iscoroutine(coro):
            coro.close()


@pytest.fixture
def project(tmp_path):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    wd = tmp_path / "wd"
    wd.mkdir()
    store.save({"project": {"name": "t", "repo": "/r",
                            "base_branch": "master"},
                "prs": [_pr(workdir=str(wd))]}, pm_dir)
    return pm_dir


# ---------------------------------------------------------------------------
# Atomic reset
# ---------------------------------------------------------------------------

class TestReset:
    def test_rewinds_and_supersedes_old_evidence(self, project):
        pm_dir = project
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-a")
        pr["signoff"] = {"verdict": "SIGNOFF_MERGE", "sha": "abc", "ts": OLD}
        pr["signoff_return"] = {"verdict": "SIGNOFF_REVIEW", "hop": "review",
                                "awaiting": "review", "ts": OLD}
        store.save(data, pm_dir)

        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert out["ok"] and out["action"] == "fresh_reset"
        assert out["from_status"] == "in_review"

        pr = store.get_pr(store.load(pm_dir), "pr-a")
        assert pr["status"] == "in_progress"
        marker = st.fresh_marker(pr)
        assert marker["from_status"] == "in_review"
        assert marker["attempt"] == 1
        assert marker["awaiting_handoff"] is True
        assert marker["requested_at"]
        # The old approval is preserved but can never be adopted again.
        assert pr["signoff"]["invalidated"].startswith("superseded by fresh")
        assert pr["signoff_history"][0]["verdict"] == "SIGNOFF_MERGE"
        assert pr["signoff_history"][0]["superseded_reason"] == "fresh-autostart"
        # The open return no longer forces a --fresh impl relaunch.
        assert pr["signoff_return"]["resolved_at"]
        assert pr["signoff_return"]["awaiting"] is None
        # Existing implementation history is preserved.
        assert pr["started_at"] == OLD

        from pm_core.signoff import fresh_recorded_verdict, return_awaiting
        assert fresh_recorded_verdict(pr, "abc") is None
        assert return_awaiting(pr) is None

    def test_repeated_reset_while_waiting_is_idempotent(self, project):
        pm_dir = project
        first = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert first["action"] == "fresh_reset"
        marker = st.fresh_marker(store.get_pr(store.load(pm_dir), "pr-a"))

        second = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert second["ok"] and second["action"] == "already_waiting"
        pr = store.get_pr(store.load(pm_dir), "pr-a")
        assert st.fresh_marker(pr) == marker  # untouched

    def test_reset_after_new_review_starts_a_new_attempt(self, project):
        pm_dir = project
        autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        # Simulate the fresh review having started.
        data = store.load(pm_dir)
        pr = store.get_pr(data, "pr-a")
        pr["status"] = "in_review"
        store.save(data, pm_dir)

        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert out["ok"] and out["action"] == "fresh_reset"
        marker = st.fresh_marker(store.get_pr(store.load(pm_dir), "pr-a"))
        assert marker["attempt"] == 2
        assert marker["from_status"] == "in_review"

    def test_in_progress_without_marker_is_rejected(self, project):
        pm_dir = project
        data = store.load(pm_dir)
        store.get_pr(data, "pr-a")["status"] = "in_progress"
        store.save(data, pm_dir)
        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert not out["ok"] and out["error"] == "not_later_stage"

    def test_terminal_is_rejected(self, project):
        pm_dir = project
        data = store.load(pm_dir)
        store.get_pr(data, "pr-a")["status"] = "merged"
        store.save(data, pm_dir)
        out = autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        assert not out["ok"] and out["error"] == "terminal_pr"

    def test_unknown_is_rejected(self, project):
        out = autostart_fresh.reset_pr(project, "nope", "test")
        assert not out["ok"] and out["error"] == "unknown_pr"


# ---------------------------------------------------------------------------
# Handoff detection
# ---------------------------------------------------------------------------

def _transcript(tmp_path, records):
    sid = "12345678-1234-1234-1234-123456789abc"
    path = tmp_path / f"{sid}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def _complete():
    return {"type": "assistant",
            "message": {"role": "assistant",
                        "content": [{"type": "text", "text": "done"}],
                        "stop_reason": "end_turn"}}


def _busy():
    return {"type": "user", "message": {"role": "user", "content": "more"}}


class _Tracker:
    def __init__(self, path=None, idle=True, tracked=True, gone=False):
        self.path = path
        self.idle = idle
        self.tracked = tracked
        self.gone = gone

    def is_tracked(self, key):
        return self.tracked

    def get_transcript_path(self, key):
        return str(self.path) if self.path else None

    def is_idle(self, key):
        return self.idle

    def is_gone(self, key):
        return self.gone


def _marker_pr(requested_at):
    return {"id": "pr-a", "workdir": "/w",
            FRESH_KEY: {"requested_at": requested_at,
                        "awaiting_handoff": True}}


class TestHandoff:
    def test_complete_turn_at_reset_time_is_ready(self, tmp_path):
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        assert autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_busy_turn_is_not_ready_even_with_stale_idle(self, tmp_path):
        path = _transcript(tmp_path, [_busy()])
        pr = _marker_pr(st.now_iso())
        assert not autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_complete_turn_is_authoritative_over_a_stale_idle_flag(
            self, tmp_path):
        # The transcript's end-of-turn record is the handoff even when the
        # hook tracker's idle flag is stale/False (e.g. Stop written last).
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        assert autostart_fresh.handoff_ready(
            None, pr, _Tracker(path, idle=False))

    def test_old_hook_event_does_not_advance(self, tmp_path):
        path = _transcript(tmp_path, [_busy()])
        pr = _marker_pr(st.now_iso())
        old_event = {"event_type": "idle_prompt",
                     "timestamp": time.time() - 3600}
        with patch("pm_core.hook_events.read_event", return_value=old_event):
            assert not autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_new_hook_event_advances_even_if_transcript_lags(self, tmp_path):
        path = _transcript(tmp_path, [_busy()])
        pr = _marker_pr("2020-01-01T00:00:00Z")
        new_event = {"event_type": "idle_prompt",
                     "timestamp": time.time() + 10}
        with patch("pm_core.hook_events.read_event", return_value=new_event):
            assert autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_spec_pending_blocks_handoff(self, tmp_path):
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        pr["spec_pending"] = "impl"
        assert not autostart_fresh.handoff_ready(None, pr, _Tracker(path))

    def test_gone_pane_blocks_handoff(self, tmp_path):
        path = _transcript(tmp_path, [_complete()])
        pr = _marker_pr(st.now_iso())
        assert not autostart_fresh.handoff_ready(
            None, pr, _Tracker(path, gone=True))

    def test_consume_handoff_clears_marker(self, project):
        pm_dir = project
        autostart_fresh.reset_pr(pm_dir, "pr-a", "test")
        app = FakeApp([], pm_dir)
        autostart_fresh.consume_handoff(app, "pr-a")
        marker = st.fresh_marker(store.get_pr(store.load(pm_dir), "pr-a"))
        assert marker["awaiting_handoff"] is False
        assert marker["handoff_at"] and marker["review_started_at"]


# ---------------------------------------------------------------------------
# fresh_start orchestration
# ---------------------------------------------------------------------------

class TestFreshStart:
    def _app(self, project):
        app = FakeApp([_pr(workdir=str(project.parent / "wd"))], project)
        app._pane_idle_tracker = MagicMock()
        app._pane_idle_tracker.is_tracked.return_value = False
        return app

    def test_waits_when_turn_in_progress(self, project):
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs") as rev:
            out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert out["ok"] and out["handoff"]["pr-a"] == "waiting"
        rev.assert_not_called()
        assert "pr-a" in auto_start.get_targets(app)
        assert st.fresh_awaiting(store.get_pr(store.load(project), "pr-a"))
        assert any("waiting for the current implementation turn"
                   in line for line in app.logs)

    def test_complete_turn_starts_one_review(self, project):
        app = self._app(project)
        calls = []

        def fake_review(_app, pairs):
            calls.append(pairs)
            # The real helper transitions the PR before starting the loop.
            data = store.load(project)
            store.get_pr(data, "pr-a")["status"] = "in_review"
            store.save(data, project)

        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=True), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs",
                   side_effect=fake_review):
            out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert out["ok"] and out["handoff"]["pr-a"] == "review_started"
        assert len(calls) == 1
        assert calls[0][0][0] == "pr-a"

    def test_repeated_call_does_not_duplicate(self, project):
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs") as rev:
            first = autostart_fresh.fresh_start(app, ["pr-a"])
            second = autostart_fresh.fresh_start(app, ["pr-a"])
        assert first["changes"][0]["action"] == "fresh_reset"
        assert second["changes"][0]["action"] == "already_waiting"
        rev.assert_not_called()

    def test_merge_in_progress_is_refused(self, project):
        app = self._app(project)
        app._pending_merge_prs.add("pr-a")
        out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert not out["ok"] and out["error"] == "merge_in_progress"
        # Nothing changed.
        pr = store.get_pr(store.load(project), "pr-a")
        assert pr["status"] == "in_review"
        assert not auto_start.get_targets(app)

    def test_pending_pr_is_refused(self, project):
        app = self._app(project)
        data = store.load(project)
        store.get_pr(data, "pr-a")["status"] = "pending"
        store.save(data, project)
        out = autostart_fresh.fresh_start(app, ["pr-a"])
        assert not out["ok"] and out["error"] == "not_later_stage"

    def test_new_target_policies_match_the_z_keys(self, project):
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=st.POLICY_AUTO, source="key:zA")
        assert auto_start.target_policy(app, "pr-a") == st.POLICY_AUTO
        assert "pr-a" not in app._stop_before_merge

    def test_z_o_defaults_to_stop_before_merge(self, project):
        app = self._app(project)
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=st.POLICY_STOP, source="key:zO")
        assert auto_start.target_policy(app, "pr-a") == POLICY_STOP
        assert "pr-a" in app._stop_before_merge

    def test_existing_target_policy_is_preserved(self, project):
        app = self._app(project)
        app._auto_start_targets["pr-a"] = st.make_target_record("cli")
        app._auto_start = True
        app._stop_before_merge.discard("pr-a")
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=st.POLICY_AUTO)
        assert auto_start.target_policy(app, "pr-a") == st.POLICY_AUTO


# ---------------------------------------------------------------------------
# Restart recovery
# ---------------------------------------------------------------------------

class TestResume:
    def test_resume_pending_readds_target_with_recorded_policy(self, project):
        # First attempt, then simulate a plain TUI restart (targets are
        # in-memory and lost).
        app = FakeApp(store.load(project)["prs"], project)
        app._pane_idle_tracker = MagicMock()
        with patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            autostart_fresh.fresh_start(
                app, ["pr-a"], policy=st.POLICY_AUTO, source="key:zA")

        restarted = FakeApp(store.load(project)["prs"], project)
        restarted._pane_idle_tracker = MagicMock()
        assert auto_start.get_targets(restarted) == []
        resumed = autostart_fresh.resume_pending(restarted)
        assert resumed == ["pr-a"]
        assert auto_start.target_policy(restarted, "pr-a") == st.POLICY_AUTO
        assert st.fresh_awaiting(
            store.get_pr(store.load(project), "pr-a"))

    def test_resume_skips_consumed_attempts(self, project):
        app = FakeApp(store.load(project)["prs"], project)
        autostart_fresh.reset_pr(project, "pr-a", "test")
        autostart_fresh.consume_handoff(app, "pr-a")
        restarted = FakeApp(store.load(project)["prs"], project)
        assert autostart_fresh.resume_pending(restarted) == []
        assert auto_start.get_targets(restarted) == []

    def test_resume_skips_advanced_prs(self, project):
        app = FakeApp(store.load(project)["prs"], project)
        autostart_fresh.reset_pr(project, "pr-a", "test")
        data = store.load(project)
        store.get_pr(data, "pr-a")["status"] = "in_review"
        store.save(data, project)
        restarted = FakeApp(store.load(project)["prs"], project)
        assert autostart_fresh.resume_pending(restarted) == []


# ---------------------------------------------------------------------------
# Retiring old in-memory state
# ---------------------------------------------------------------------------

class TestRetirement:
    def test_stale_loop_and_qa_are_dropped(self):
        app = FakeApp([_pr()])
        app._review_loops["pr-a"] = ReviewLoopState(
            pr_id="pr-a", running=False, latest_verdict="NEEDS_WORK")
        app._qa_loops["pr-a"] = QALoopState(pr_id="pr-a")
        app._self_driving_qa["pr-a"] = {"pass_count": 1}
        app._pending_merge_prs.add("pr-a")
        app._merge_input_required_prs.add("pr-a")

        written = {}
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state",
                   side_effect=lambda pid, action, state, **kw:
                   written.__setitem__(action, (state, kw))):
            autostart_fresh.retire_in_memory(app, _pr())

        assert "pr-a" not in app._review_loops
        assert "pr-a" not in app._qa_loops
        assert "pr-a" not in app._self_driving_qa
        assert "pr-a" not in app._pending_merge_prs
        assert "pr-a" not in app._merge_input_required_prs
        assert written["review-loop"][0] == "done"
        assert written["review-loop"][1]["verdict"] == "SUPERSEDED"
        assert written["review-loop"][1]["previous_verdict"] == "NEEDS_WORK"
        assert written["qa"][1]["verdict"] == "SUPERSEDED"

    def test_live_loop_is_stopped(self):
        app = FakeApp([_pr()])
        loop = ReviewLoopState(pr_id="pr-a", running=True)
        app._review_loops["pr-a"] = loop
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={}), \
             patch("pm_core.runtime_state.set_action_state"):
            autostart_fresh.retire_in_memory(app, _pr())
        assert loop.stop_requested


# ---------------------------------------------------------------------------
# Stale QA evidence
# ---------------------------------------------------------------------------

class TestStaleQa:
    def test_pre_fresh_qa_pass_is_ignored(self):
        pr = {"id": "pr-a", FRESH_KEY: {"requested_at": st.now_iso(),
                                        "awaiting_handoff": False}}
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={"state": "done", "verdict": "PASS",
                                 "updated_at": OLD}):
            assert auto_start.recorded_qa_verdict("pr-a", pr) is None

    def test_qa_pass_after_fresh_is_kept(self):
        pr = {"id": "pr-a", FRESH_KEY: {"requested_at": OLD,
                                        "awaiting_handoff": False}}
        with patch("pm_core.runtime_state.get_action_state",
                   return_value={"state": "done", "verdict": "PASS",
                                 "updated_at": st.now_iso()}):
            assert auto_start.recorded_qa_verdict("pr-a", pr) == "PASS"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestStatus:
    def _status(self, pr, idle):
        return st.build_status({
            "prs": [pr], "targets": {"pr-a": st.make_target_record("test")},
            "enabled": True, "windows": {"#1": "%1"},
            "impl_idle": {"pr-a": idle} if idle else {},
        })

    def test_waiting_reason_names_the_implementation_turn(self):
        pr = _pr(status="in_progress", gh_pr_number=1,
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        run = self._status(pr, "active")["runs"][0]
        assert run["state"] == "waiting"
        assert "waiting for the current implementation turn" in run["reason"]

    def test_idle_reason_says_review_is_starting(self):
        pr = _pr(status="in_progress", gh_pr_number=1,
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": True}})
        run = self._status(pr, "idle")["runs"][0]
        assert "implementation turn complete" in run["reason"]

    def test_consumed_marker_shows_normal_implementation(self):
        pr = _pr(status="in_progress", gh_pr_number=1,
                 **{FRESH_KEY: {"requested_at": st.now_iso(),
                                "awaiting_handoff": False}})
        run = self._status(pr, "active")["runs"][0]
        assert run["reason"] == "implementing"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.fixture
def cli_project(tmp_path, monkeypatch):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    wd = tmp_path / "wd"
    wd.mkdir()
    store.save({"project": {"name": "t", "repo": "/r",
                            "base_branch": "master"},
                "prs": [_pr(workdir=str(wd)),
                        _pr("pr-m", status="merged")]}, pm_dir)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pm_core.cli.autostart.state_root", lambda: pm_dir)
    monkeypatch.setattr("pm_core.cli.autostart.pm_home", lambda: home)
    return pm_dir, home


def _cli(args):
    from pm_core.cli import cli
    return CliRunner().invoke(cli, ["autostart", *args])


class TestCli:
    def test_help_mentions_fresh(self):
        res = _cli(["--help"])
        assert res.exit_code == 0
        assert "fresh" in res.output

    def test_fresh_sends_the_verb(self, cli_project):
        sent = []

        def fake_trigger(session, cmd):
            sent.append(cmd)
            return True

        with patch("pm_core.cli.autostart.trigger_tui_command",
                   side_effect=fake_trigger), \
             patch("pm_core.cli.autostart._request",
                   return_value={"ok": True, "changes": [
                       {"pr_id": "pr-a", "action": "fresh_reset",
                        "from_status": "in_review"}],
                       "message": "Auto-start fresh: pr-a: waiting",
                       "status": {"mode": "targets", "targets": []}}):
            res = _cli(["fresh", "pr-a", "-s", "pm-x"])
        assert res.exit_code == 0, res.output
        assert "fresh: pr-a (in_review → in_progress)" in res.output

    def test_merged_rejected_before_sending(self, cli_project):
        with patch("pm_core.cli.autostart.trigger_tui_command") as trig:
            res = _cli(["fresh", "pr-m", "-s", "pm-x"])
        assert res.exit_code == 1 and "merged" in res.output
        trig.assert_not_called()

    def test_round_trip_through_tui_handler(self, cli_project):
        import os
        import shlex
        pm_dir, home = cli_project
        pidfile = pm_dir.parent / "tui.pid"
        pidfile.write_text(str(os.getpid()))
        app = FakeApp(store.load(pm_dir)["prs"], pm_dir)
        app._pane_idle_tracker = MagicMock()
        app._pane_idle_tracker.is_tracked.return_value = False
        seen = {}

        def fake_trigger(session, cmd):
            seen["cmd"] = cmd
            with patch("pm_core.tui.auto_start.pm_home",
                       return_value=home):
                seen["result"] = auto_start.handle_command(
                    app, shlex.split(cmd)[1:])
            return True

        with patch("pm_core.cli.autostart._tui_pidfile_for_session",
                   return_value=pidfile), \
             patch("pm_core.cli.autostart.trigger_tui_command",
                   side_effect=fake_trigger), \
             patch.object(autostart_fresh, "handoff_ready",
                          return_value=False), \
             patch("pm_core.tui.review_loop_ui._auto_review_idle_prs"):
            res = _cli(["fresh", "pr-a", "-s", "pm-x", "--json"])
        assert res.exit_code == 0, res.output
        assert seen["cmd"].startswith("autostart fresh pr-a --reply ")
        assert seen["result"]["ok"]
        assert seen["result"]["changes"][0]["action"] == "fresh_reset"
        out = json.loads(res.output)
        assert out["ok"] and out["handoff"]["pr-a"] == "waiting"
