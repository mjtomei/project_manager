"""Multiple auto-start targets (pr-0b87a97).

Covers the explicit target collection owned by the TUI scheduler
(``pm_core.tui.auto_start``), the shared pure helpers/status builder
(``pm_core.autostart_state``), the ``pm autostart`` CLI over the session
command queue, the runs popup, and the merge-restart breadcrumb.

The repo has no pytest-asyncio plugin: async bodies run via ``asyncio.run``.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pm_core import autostart_state as st
from pm_core import store
from pm_core.autostart_state import POLICY_AUTO, POLICY_STOP
from pm_core.qa_loop import QALoopState, QAScenario
from pm_core.review_loop import ReviewLoopState
from pm_core.tui import auto_start


def _pr(pid, status="pending", deps=None, **extra):
    d = {"id": pid, "title": f"T {pid}", "branch": f"b-{pid}",
         "status": status, "depends_on": deps or [], "notes": []}
    d.update(extra)
    return d


class FakeApp:
    """Plain object (not MagicMock) so attribute typing is real."""

    def __init__(self, prs, root=None):
        self._data = {"project": {"name": "t", "repo": "/r",
                                  "base_branch": "master"},
                      "prs": prs}
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
        self._merge_propagation_phase = set()
        self._session_name = None
        self._watcher_manager = MagicMock()
        self._watcher_manager.find_by_type.return_value = None
        self._pane_idle_tracker = MagicMock()
        self._pane_idle_tracker.is_tracked.return_value = False
        self.logs: list[str] = []
        self.workers: list = []

    def log_message(self, msg, **kw):
        self.logs.append(msg)

    def _update_display(self):
        pass

    def _load_state(self):
        pass

    def run_worker(self, coro, *a, **kw):
        # Don't run follow-up scheduler passes implicitly; tests drive them.
        self.workers.append(coro)
        if asyncio.iscoroutine(coro):
            coro.close()


@pytest.fixture(autouse=True)
def _quiet_watcher():
    # Never consult the real ~/.pm/runtime from these tests.
    with patch("pm_core.tui.watcher_ui.is_running", return_value=False), \
         patch("pm_core.runtime_state.get_action_state", return_value={}):
        yield


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestClosures:
    PRS = [_pr("a"), _pr("b", deps=["a"]), _pr("c", deps=["a"]),
           _pr("d", deps=["b"]), _pr("x")]

    def test_union_of_closures(self):
        assert st.managed_ids(self.PRS, ["d", "c"]) == {"a", "b", "c", "d"}

    def test_empty_targets_manage_nothing(self):
        assert st.managed_ids(self.PRS, []) == set()

    def test_needed_by_shared_dep(self):
        nb = st.needed_by(self.PRS, ["d", "c"])
        assert nb["a"] == ["d", "c"]
        assert nb["b"] == ["d"]
        assert "x" not in nb


class TestBreadcrumbFormat:
    def test_roundtrip(self):
        targets = {"a": st.make_target_record("cli"),
                   "b": st.make_target_record("key:O")}
        data = {"auto_start": True,
                "targets": st.targets_to_breadcrumb(targets),
                "all_mode": False}
        got, all_mode, migrated = st.targets_from_breadcrumb(data)
        assert list(got) == ["a", "b"]
        assert got["b"]["source"] == "key:O"
        assert (all_mode, migrated) == (False, False)

    def test_legacy_single_target_migrates(self):
        got, all_mode, migrated = st.targets_from_breadcrumb(
            {"auto_start": True, "target": "pr-1", "run_id": "r"})
        assert list(got) == ["pr-1"] and not all_mode and migrated

    def test_legacy_targetless_is_explicit_all_mode(self):
        got, all_mode, migrated = st.targets_from_breadcrumb(
            {"auto_start": True, "target": None, "run_id": "r"})
        assert got == {} and all_mode and migrated

    def test_no_auto_start(self):
        assert st.targets_from_breadcrumb({"review_loops": {}}) == ({}, False, False)


# ---------------------------------------------------------------------------
# Target mutations
# ---------------------------------------------------------------------------

class TestAddRemove:
    def test_add_is_additive_and_idempotent(self):
        app = FakeApp([_pr("a"), _pr("b")])
        assert auto_start.add_targets(app, ["a"])["ok"]
        assert auto_start.add_targets(app, ["b"])["ok"]
        r = auto_start.add_targets(app, ["a"])
        assert r["changes"][0]["action"] == "unchanged"
        assert auto_start.get_targets(app) == ["a", "b"]
        assert app._auto_start is True
        assert not auto_start.is_all_mode(app)

    def test_default_policy_new_target_is_stop(self):
        app = FakeApp([_pr("a")])
        auto_start.add_targets(app, ["a"])
        assert auto_start.policy_for(app, "a") == POLICY_STOP

    def test_readd_without_flag_keeps_policy(self):
        app = FakeApp([_pr("a")])
        auto_start.add_targets(app, ["a"], policy=POLICY_AUTO)
        auto_start.add_targets(app, ["a"])
        assert auto_start.policy_for(app, "a") == POLICY_AUTO

    def test_auto_merge_flag_clears_stop(self):
        app = FakeApp([_pr("a")])
        auto_start.add_targets(app, ["a"])
        auto_start.add_targets(app, ["a"], policy=POLICY_AUTO)
        assert "a" not in app._stop_before_merge

    def test_unknown_id_rejects_whole_command(self):
        app = FakeApp([_pr("a")])
        r = auto_start.add_targets(app, ["a", "nope"])
        assert not r["ok"] and r["error"] == "unknown_pr"
        assert r["invalid"] == ["nope"]
        assert auto_start.get_targets(app) == []
        assert app._auto_start is False

    def test_merged_pr_rejected(self):
        app = FakeApp([_pr("a", status="merged")])
        r = auto_start.add_targets(app, ["a"])
        assert r["error"] == "terminal_pr"
        assert app._auto_start is False

    def test_resolves_github_number(self):
        app = FakeApp([_pr("pr-a", gh_pr_number=42)])
        auto_start.add_targets(app, ["#42"])
        assert auto_start.get_targets(app) == ["pr-a"]

    def test_remove_one_keeps_other(self):
        app = FakeApp([_pr("a"), _pr("b")])
        auto_start.add_targets(app, ["a", "b"])
        r = auto_start.remove_targets(app, ["a"])
        assert r["changes"] == [{"pr_id": "a", "action": "removed"}]
        assert auto_start.get_targets(app) == ["b"]
        assert app._auto_start is True

    def test_remove_non_target_and_unknown(self):
        app = FakeApp([_pr("a"), _pr("b")])
        auto_start.add_targets(app, ["a"])
        assert auto_start.remove_targets(app, ["b"])["changes"][0]["action"] == "not_target"
        r = auto_start.remove_targets(app, ["a", "zzz"])
        assert r["error"] == "unknown_pr"
        assert auto_start.get_targets(app) == ["a"]  # nothing changed

    def test_remove_last_turns_off_never_all(self):
        app = FakeApp([_pr("a"), _pr("x")])
        auto_start.add_targets(app, ["a"])
        auto_start.remove_targets(app, ["a"])
        assert app._auto_start is False
        assert auto_start.managed_ids(app) == set()
        assert not auto_start.in_scope(app, "x")

    def test_remove_keeps_stop_mark(self):
        app = FakeApp([_pr("a")])
        auto_start.add_targets(app, ["a"])
        auto_start.remove_targets(app, ["a"])
        assert "a" in app._stop_before_merge

    def test_remove_keeps_shared_dep_in_scope(self):
        app = FakeApp([_pr("d"), _pr("a", deps=["d"]), _pr("b", deps=["d"])])
        auto_start.add_targets(app, ["a", "b"])
        auto_start.remove_targets(app, ["a"])
        assert auto_start.in_scope(app, "d")
        assert not auto_start.in_scope(app, "a")

    def test_remove_never_kills_windows(self):
        app = FakeApp([_pr("a", status="in_progress")])
        auto_start.add_targets(app, ["a"])
        with patch("pm_core.tmux.kill_window") as kw, \
             patch("pm_core.tmux.kill_window_by_id", create=True) as kwid:
            auto_start.remove_targets(app, ["a"])
        kw.assert_not_called()
        kwid.assert_not_called()


class TestKeys:
    def test_O_twice_on_two_prs_keeps_both(self):
        app = FakeApp([_pr("a"), _pr("b")])
        asyncio.run(auto_start.auto_sequence_for_pr(app, "a"))
        asyncio.run(auto_start.auto_sequence_for_pr(app, "b"))
        asyncio.run(auto_start.auto_sequence_for_pr(app, "a"))  # re-arm
        assert auto_start.get_targets(app) == ["a", "b"]
        assert app._stop_before_merge == {"a", "b"}

    def test_A_adds_auto_merge_without_clearing_existing(self):
        app = FakeApp([_pr("a"), _pr("b")])
        asyncio.run(auto_start.auto_sequence_for_pr(app, "a"))
        asyncio.run(auto_start.toggle(app, "b"))
        assert auto_start.get_targets(app) == ["a", "b"]
        assert auto_start.policy_for(app, "b") == POLICY_AUTO
        assert auto_start.policy_for(app, "a") == POLICY_STOP

    def test_A_on_target_removes_only_it(self):
        app = FakeApp([_pr("a"), _pr("b")])
        auto_start.add_targets(app, ["a", "b"])
        asyncio.run(auto_start.toggle(app, "a"))
        assert auto_start.get_targets(app) == ["b"]

    def test_key_confirmations_are_forced(self):
        """O / A feedback must survive a concurrent background sticky
        message (e.g. "Review loop started"), so it is shown forced."""
        app = FakeApp([_pr("a"), _pr("b")])
        shown = []
        app.log_message = lambda msg, **kw: shown.append((msg, kw))
        asyncio.run(auto_start.auto_sequence_for_pr(app, "a"))
        armed = [kw for m, kw in shown if m.startswith("Auto-sequence armed for a")]
        assert armed and armed[0].get("force") is True
        shown.clear()
        asyncio.run(auto_start.toggle(app, "b"))
        added = [kw for m, kw in shown if "targets += b" in m]
        assert added and added[0].get("force") is True

    def test_A_without_selection_never_enables_backlog(self):
        app = FakeApp([_pr("a")])
        asyncio.run(auto_start.toggle(app, None))
        assert app._auto_start is False
        assert not auto_start.is_all_mode(app)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def _enabled_app(prs, targets, tmp_path, stop=()):
    app = FakeApp(prs, root=tmp_path)
    app._auto_start = True
    app._auto_start_targets = {t: st.make_target_record("test") for t in targets}
    app._auto_start_run_id = "run"
    app._stop_before_merge = set(stop)
    return app


class TestCheckAndStart:
    def test_two_independent_targets_both_launch(self, tmp_path):
        prs = [_pr("a"), _pr("b"), _pr("x")]
        app = _enabled_app(prs, ["a", "b"], tmp_path)
        started = []

        async def fake_start(_app, pr_id):
            started.append(pr_id)

        with patch.object(auto_start, "_start_pr_quiet", fake_start):
            asyncio.run(auto_start.check_and_start(app))
        assert sorted(started) == ["a", "b"]  # no break after first target

    def test_shared_dep_launches_once_across_concurrent_passes(self, tmp_path):
        prs = [_pr("d"), _pr("a", deps=["d"]), _pr("b", deps=["d"])]
        app = _enabled_app(prs, ["a", "b"], tmp_path)
        started = []

        async def slow_start(_app, pr_id):
            started.append(pr_id)
            await asyncio.sleep(0.05)

        async def two_passes():
            await asyncio.gather(auto_start.check_and_start(app),
                                 auto_start.check_and_start(app))

        with patch.object(auto_start, "_start_pr_quiet", slow_start):
            asyncio.run(two_passes())
        assert started == ["d"]  # a/b wait on d; d launched exactly once

    def test_removal_mid_pass_stops_later_launches(self, tmp_path):
        prs = [_pr("a"), _pr("b")]
        app = _enabled_app(prs, ["a", "b"], tmp_path)
        started = []

        async def start_then_remove(_app, pr_id):
            started.append(pr_id)
            if pr_id == "a":
                auto_start.remove_targets(app, ["b"])  # CLI lands mid-await

        with patch.object(auto_start, "_start_pr_quiet", start_then_remove):
            asyncio.run(auto_start.check_and_start(app))
        assert started == ["a"]

    def test_completion_removes_only_that_target(self, tmp_path):
        prs = [_pr("a", status="merged"), _pr("b", status="in_progress")]
        app = _enabled_app(prs, ["a", "b"], tmp_path)
        with patch.object(auto_start, "_start_pr_quiet"):
            asyncio.run(auto_start.check_and_start(app))
        assert auto_start.get_targets(app) == ["b"]
        assert app._auto_start is True
        assert any("target a merged" in m for m in app.logs)

    def test_last_completion_turns_off(self, tmp_path):
        prs = [_pr("a", status="merged"), _pr("x")]
        app = _enabled_app(prs, ["a"], tmp_path)
        with patch.object(auto_start, "_start_pr_quiet") as sp:
            asyncio.run(auto_start.check_and_start(app))
        sp.assert_not_called()
        assert app._auto_start is False
        assert not auto_start.is_all_mode(app)

    def test_empty_pr_data_does_not_prune_targets(self, tmp_path):
        """Unloaded/empty PR data must not read as "every target vanished"."""
        app = _enabled_app([], ["a", "b"], tmp_path)
        auto_start._prune_completed_targets(app, [])
        assert auto_start.get_targets(app) == ["a", "b"]
        assert app._auto_start is True

    def test_out_of_scope_not_started(self, tmp_path):
        prs = [_pr("a"), _pr("x")]
        app = _enabled_app(prs, ["a"], tmp_path)
        started = []

        async def fake_start(_app, pr_id):
            started.append(pr_id)

        with patch.object(auto_start, "_start_pr_quiet", fake_start):
            asyncio.run(auto_start.check_and_start(app))
        assert started == ["a"]

    def test_review_and_qa_loops_cover_both_targets(self, tmp_path):
        prs = [_pr("a", status="in_review", workdir="/w/a"),
               _pr("b", status="qa", workdir="/w/b"),
               _pr("x", status="in_review", workdir="/w/x")]
        app = _enabled_app(prs, ["a", "b"], tmp_path)
        with patch("pm_core.tui.review_loop_ui._start_loop") as sl, \
             patch("pm_core.tui.qa_loop_ui.start_qa") as sq:
            asyncio.run(auto_start.check_and_start(app))
        assert [c.args[1] for c in sl.call_args_list] == ["a"]
        assert [c.args[1] for c in sq.call_args_list] == ["b"]


class TestMergePolicy:
    def _run(self, app, pr_id):
        from pm_core.tui import review_loop_ui
        with patch.object(review_loop_ui, "_attempt_merge", return_value=True) as am:
            review_loop_ui._maybe_auto_merge(app, pr_id)
        return am

    def test_stop_target_not_merged_auto_target_merged(self, tmp_path):
        prs = [_pr("a", status="qa"), _pr("b", status="qa")]
        app = _enabled_app(prs, ["a", "b"], tmp_path, stop={"a"})
        assert not self._run(app, "a").called
        assert self._run(app, "b").called

    def test_stop_dep_wins_over_auto_target(self, tmp_path):
        prs = [_pr("d", status="qa"), _pr("t", deps=["d"])]
        app = _enabled_app(prs, ["t"], tmp_path, stop={"d"})
        assert not self._run(app, "d").called

    def test_out_of_scope_never_merged(self, tmp_path):
        prs = [_pr("a", status="qa"), _pr("x", status="qa")]
        app = _enabled_app(prs, ["a"], tmp_path)
        assert not self._run(app, "x").called


# ---------------------------------------------------------------------------
# Breadcrumb (merge-restart path)
# ---------------------------------------------------------------------------

class TestBreadcrumb:
    def test_save_and_consume_preserves_targets_and_policies(self, tmp_path):
        prs = [_pr("a"), _pr("b")]
        app = _enabled_app(prs, ["a", "b"], tmp_path, stop={"a"})
        app._watcher_manager.is_any_running.return_value = False
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
            (tmp_path / "merge-restart").touch()
            auto_start.save_breadcrumb(app)
            data = json.loads((tmp_path / "autostart-resume.json").read_text())
            assert [t["pr_id"] for t in data["targets"]] == ["a", "b"]

            fresh = FakeApp(prs, root=tmp_path)
            order = []
            with patch.object(auto_start, "_adopt_live_qa",
                              side_effect=lambda a: order.append("adopt")), \
                 patch.object(auto_start, "check_and_start",
                              side_effect=lambda a: order.append("cas")):
                asyncio.run(auto_start.consume_breadcrumb(fresh))
        assert auto_start.get_targets(fresh) == ["a", "b"]
        assert fresh._stop_before_merge == {"a"}
        assert fresh._auto_start is True and fresh._auto_start_run_id == "run"
        assert order == ["adopt", "cas"]  # adopt live QA before scheduling

    def test_consume_legacy_single_target(self, tmp_path):
        prs = [_pr("a")]
        (tmp_path / "autostart-resume.json").write_text(json.dumps(
            {"auto_start": True, "target": "a", "run_id": "old"}))
        fresh = FakeApp(prs, root=tmp_path)
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch.object(auto_start, "_adopt_live_qa"), \
             patch.object(auto_start, "check_and_start"):
            asyncio.run(auto_start.consume_breadcrumb(fresh))
        assert auto_start.get_targets(fresh) == ["a"]
        assert not auto_start.is_all_mode(fresh)
        assert any("migrated legacy" in m for m in fresh.logs)


class TestQAAdoption:
    def test_adopted_qa_loop_not_relaunched(self, tmp_path):
        prs = [_pr("a", status="qa", workdir="/w/a")]
        app = _enabled_app(prs, ["a"], tmp_path)

        def adopt(a):
            s = QALoopState(pr_id="a", running=True)
            a._qa_loops["a"] = s

        with patch("pm_core.tui.qa_loop_ui._resume_incomplete_qa", side_effect=adopt), \
             patch("pm_core.tui.qa_loop_ui.start_qa") as sq:
            auto_start._adopt_live_qa(app)
            asyncio.run(auto_start.check_and_start(app))
        sq.assert_not_called()


# ---------------------------------------------------------------------------
# Command handling + reply files
# ---------------------------------------------------------------------------

class TestHandleCommand:
    def test_reply_file_has_status(self, tmp_path):
        app = FakeApp([_pr("a"), _pr("b", deps=["a"])])
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
            auto_start.handle_command(app, ["add", "b", "--reply", "r1"])
            payload = json.loads((tmp_path / "autostart-replies" / "r1.json").read_text())
        assert payload["ok"]
        s = payload["status"]
        assert s["schema"] == st.SCHEMA and s["mode"] == "targets"
        assert [t["pr_id"] for t in s["targets"]] == ["b"]
        assert {r["pr_id"] for r in s["runs"]} == {"a", "b"}

    def test_bare_autostart_when_off_does_not_enable(self):
        app = FakeApp([_pr("a")])
        r = auto_start.handle_command(app, [])
        assert not r["ok"] and app._auto_start is False

    def test_target_without_id_is_usage_error(self):
        app = FakeApp([_pr("a")])
        auto_start.add_targets(app, ["a"])
        r = auto_start.handle_command(app, ["target"])
        assert r["error"] == "usage"
        assert auto_start.get_targets(app) == ["a"]

    def test_target_alias_is_additive(self):
        app = FakeApp([_pr("a"), _pr("b")])
        auto_start.handle_command(app, ["target", "a"])
        auto_start.handle_command(app, ["target", "b"])
        assert auto_start.get_targets(app) == ["a", "b"]

    def test_all_mode_is_explicit(self):
        app = FakeApp([_pr("a")])
        auto_start.handle_command(app, ["all"])
        assert auto_start.is_all_mode(app) and auto_start.managed_ids(app) is None

    def test_bad_reply_id_rejected(self, tmp_path):
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
            assert auto_start.write_reply("../evil", {}) is None

    def test_handler_exception_still_writes_error_reply(self, tmp_path):
        # Otherwise the CLI would wait out its timeout and misreport the
        # failure as owner_timeout.
        app = FakeApp([_pr("a")])
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
             patch.object(auto_start, "add_targets",
                          side_effect=RuntimeError("boom")):
            r = auto_start.handle_command(app, ["add", "a", "--reply", "r2"])
            payload = json.loads(
                (tmp_path / "autostart-replies" / "r2.json").read_text())
        assert r["error"] == "internal"
        assert not payload["ok"] and payload["error"] == "internal"
        assert "boom" in payload["message"]
        assert payload["status"]["mode"] == "off"

    def test_command_bar_list_logs_targets(self):
        app = FakeApp([_pr("a"), _pr("b")])
        auto_start.handle_command(app, ["add", "a"])
        auto_start.handle_command(app, ["add", "b", "--auto-merge"])
        auto_start.handle_command(app, ["list"])
        assert app.logs[-1] == "Auto-start targets: a (stop), b"

    def test_unknown_id_reload_flushes_write_queue_first(self, tmp_path):
        app = FakeApp([_pr("a")], root=tmp_path)
        calls = []
        app._write_queue = MagicMock()
        app._write_queue.flush_sync.side_effect = lambda: calls.append("flush")

        def fake_load(_root):
            calls.append("load")
            return app._data

        with patch("pm_core.tui.auto_start.store.load", side_effect=fake_load):
            r = auto_start.add_targets(app, ["nope"])
        assert r["error"] == "unknown_pr"
        assert calls == ["flush", "load"]


# ---------------------------------------------------------------------------
# Status derivation (live evidence, not registry status alone)
# ---------------------------------------------------------------------------

def _status(prs, targets, **inp):
    return st.build_status({"prs": prs, "targets": {t: {} for t in targets},
                            "enabled": bool(targets), **inp})


def _run(status, pr_id):
    return next(r for r in status["runs"] if r["pr_id"] == pr_id)


class TestBuildStatus:
    def test_empty_is_off_not_backlog(self):
        s = _status([_pr("a"), _pr("b")], [])
        assert s["mode"] == "off" and s["runs"] == [] and s["targets"] == []

    def test_shared_dep_listed_once_needed_by_both(self):
        prs = [_pr("d", status="in_progress"), _pr("a", deps=["d"]),
               _pr("b", deps=["d"])]
        s = _status(prs, ["a", "b"], windows={"d": "@1"})
        assert [r["pr_id"] for r in s["runs"]].count("d") == 1
        assert _run(s, "d")["needed_by"] == ["a", "b"]
        assert _run(s, "a")["state"] == "waiting"
        assert "blocked on d (in_progress)" in _run(s, "a")["reason"]
        rows = st.status_rows(s)
        dep_rows = [r for r in rows if r["pr_id"] == "d"]
        assert len(dep_rows) == 2 and dep_rows[0]["also"] == ["b"]

    def test_dep_that_is_also_a_target_not_listed_as_needing_itself(self):
        prs = [_pr("d", status="qa"), _pr("q", deps=["d"])]
        s = _status(prs, ["d", "q"])
        assert _run(s, "d")["needed_by"] == ["d", "q"]
        dep_rows = [r for r in st.status_rows(s)
                    if r["pr_id"] == "d" and r["kind"] == "dep"]
        assert len(dep_rows) == 1 and dep_rows[0]["also"] == []

    def test_review_pass_under_skip_qa_does_not_promise_qa(self):
        """skip_qa: after review PASS no QA runs, so the reason must point
        at sign-off, not "QA transition pending" (spec R10)."""
        rl = {"p": {"iteration": 1, "verdict": "PASS", "running": False,
                    "input_required": False}}
        prs = [_pr("p", status="in_review")]
        s = _status(prs, ["p"], review_loops=rl, skip_qa=True,
                    stop_before_merge={"p"})
        reason = _run(s, "p")["reason"]
        assert "QA" not in reason.replace("QA skipped", "")
        assert "QA skipped" in reason and "awaiting sign-off" in reason
        s = _status(prs, ["p"], review_loops=rl, skip_qa=True,
                    signoff={"p": {"verdict": "SIGNOFF_MERGE", "fresh": True}},
                    stop_before_merge={"p"})
        assert "press g" in _run(s, "p")["reason"]
        s = _status(prs, ["p"], review_loops=rl)
        assert _run(s, "p")["reason"] == "review passed; QA transition pending"

    def test_in_progress_without_window_is_paused(self):
        s = _status([_pr("a", status="in_progress")], ["a"])
        r = _run(s, "a")
        assert (r["phase"], r["state"]) == ("implementation", "paused")
        s = _status([_pr("a", status="in_progress")], ["a"], windows={"a": "@3"})
        r = _run(s, "a")
        assert r["state"] == "running" and r["window"] == {"name": "a", "id": "@3"}

    def test_review_progress(self):
        s = _status([_pr("a", status="in_review", gh_pr_number=7)], ["a"],
                    review_loops={"a": {"running": True, "iteration": 2,
                                        "verdict": "NEEDS_WORK"}},
                    windows={"review-#7": "@9"})
        r = _run(s, "a")
        assert r["state"] == "running" and r["review"]["iteration"] == 2
        assert "review iteration 2 (last NEEDS_WORK)" == r["reason"]
        assert r["window"]["name"] == "review-#7"

    def test_in_review_status_alone_is_not_running(self):
        r = _run(_status([_pr("a", status="in_review")], ["a"]), "a")
        assert r["state"] == "queued"

    def test_qa_scenario_progress(self):
        s = _status([_pr("a", status="qa")], ["a"],
                    qa_loops={"a": {"running": True, "planning": False,
                                    "total": 5, "done": 2,
                                    "counts": {"PASS": 2}}})
        r = _run(s, "a")
        assert r["reason"] == "scenario 2/5 done"
        assert st.status_rows(s)[0]["progress"] == "qa 2/5 PASS:2"

    def test_qa_progress_never_shows_stale_review_iteration(self):
        rl = {"a": {"running": False, "iteration": 1, "verdict": "PASS"}}
        planning = _status([_pr("a", status="qa")], ["a"], review_loops=rl,
                           qa_loops={"a": {"running": True, "planning": True}})
        assert st.status_rows(planning)[0]["progress"] == "qa planning"
        done = _status([_pr("a", status="qa")], ["a"], review_loops=rl,
                       qa_loops={"a": {"verdict": "PASS"}})
        assert st.status_rows(done)[0]["progress"] == "qa PASS"

    def test_qa_pass_awaits_signoff(self):
        r = _run(_status([_pr("a", status="qa")], ["a"],
                         qa_loops={"a": {"verdict": "PASS"}}), "a")
        assert r["state"] == "waiting" and "sign-off" in r["reason"]

    def test_merge_refused_by_signoff_gate(self):
        r = _run(_status([_pr("a", status="qa")], ["a"],
                         pending_merge={"a"}), "a")
        assert r["state"] == "waiting" and "sign-off gate" in r["reason"]

    def test_signoff_registry_status_alone_is_not_ready(self):
        r = _run(_status([_pr("a", status="sign_off")], ["a"]), "a")
        assert r["state"] == "paused" and r["phase"] == "sign_off"

    def test_signoff_fresh_merge_with_stop(self):
        r = _run(_status([_pr("a", status="sign_off")], ["a"],
                         stop_before_merge={"a"},
                         signoff={"a": {"verdict": "SIGNOFF_MERGE", "fresh": True}}),
                 "a")
        assert "stop-before-merge — press g" in r["reason"] and "fresh" in r["reason"]
        assert r["policy"] == POLICY_STOP

    def test_signoff_stale(self):
        r = _run(_status([_pr("a", status="sign_off")], ["a"],
                         signoff={"a": {"verdict": "SIGNOFF_MERGE", "fresh": False}}),
                 "a")
        assert "stale" in r["reason"]

    def test_dep_blocked_by_stop_before_merge_noted(self):
        prs = [_pr("d", status="sign_off"), _pr("t", deps=["d"])]
        r = _run(_status(prs, ["t"], stop_before_merge={"d"}), "t")
        assert "stop-before-merge" in r["reason"]

    def test_text_format_has_both_targets(self):
        prs = [_pr("a", status="in_progress"), _pr("b", status="in_review")]
        txt = st.format_text(_status(prs, ["a", "b"]))
        assert "◎ a" in txt and "◎ b" in txt


# ---------------------------------------------------------------------------
# CLI (over the session command queue)
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path, monkeypatch):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    store.save({"project": {"name": "t", "repo": "/r", "base_branch": "master"},
                "prs": [_pr("pr-a"), _pr("pr-b"), _pr("pr-m", status="merged")]},
               pm_dir)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pm_core.cli.autostart.state_root", lambda: pm_dir)
    monkeypatch.setattr("pm_core.cli.autostart.pm_home", lambda: home)
    return pm_dir, home


def _cli(args):
    from pm_core.cli import cli
    return CliRunner().invoke(cli, ["autostart", *args])


class TestCLI:
    def test_unknown_id_rejected_before_sending(self, project):
        with patch("pm_core.cli.autostart.trigger_tui_command") as trig:
            res = _cli(["add", "pr-a", "nope", "--json", "-s", "pm-x"])
        assert res.exit_code == 1
        assert json.loads(res.output)["error"] == "unknown_pr"
        trig.assert_not_called()

    def test_merged_rejected(self, project):
        with patch("pm_core.cli.autostart.trigger_tui_command") as trig:
            res = _cli(["add", "pr-m", "-s", "pm-x"])
        assert res.exit_code == 1 and "merged" in res.output
        trig.assert_not_called()

    def test_owner_unavailable(self, project, tmp_path):
        with patch("pm_core.cli.autostart._tui_pidfile_for_session",
                   return_value=tmp_path / "missing.pid"):
            res = _cli(["status", "--json", "-s", "pm-x"])
        assert res.exit_code == 2
        assert json.loads(res.output)["error"] == "owner_unavailable"

    def test_owner_timeout(self, project, tmp_path):
        pidfile = tmp_path / "tui.pid"
        import os
        pidfile.write_text(str(os.getpid()))
        with patch("pm_core.cli.autostart._tui_pidfile_for_session",
                   return_value=pidfile), \
             patch("pm_core.cli.autostart.trigger_tui_command", return_value=True):
            res = _cli(["list", "--json", "-s", "pm-x", "--timeout", "0.3"])
        assert res.exit_code == 2
        assert json.loads(res.output)["error"] == "owner_timeout"

    def test_list_json_carries_owner_error(self, project, tmp_path):
        import os
        pidfile = tmp_path / "tui.pid"
        pidfile.write_text(str(os.getpid()))
        err = {"ok": False, "error": "internal", "message": "boom",
               "changes": [], "status": None}
        with patch("pm_core.cli.autostart._tui_pidfile_for_session",
                   return_value=pidfile), \
             patch("pm_core.cli.autostart._request", return_value=err):
            res = _cli(["list", "--json", "-s", "pm-x"])
        assert res.exit_code == 1
        out = json.loads(res.output)
        assert (out["ok"], out["error"], out["message"]) == (False, "internal", "boom")

    @pytest.mark.parametrize("verb", ["status", "list"])
    def test_ok_reply_without_status_is_failure(self, project, tmp_path, verb):
        """build_status raising on the owner must not read as an empty
        success (``{}`` / no targets, exit 0)."""
        import os
        pidfile = tmp_path / "tui.pid"
        pidfile.write_text(str(os.getpid()))
        reply = {"ok": True, "changes": [], "status": None,
                 "message": "status failed: boom"}
        with patch("pm_core.cli.autostart._tui_pidfile_for_session",
                   return_value=pidfile), \
             patch("pm_core.cli.autostart._request", return_value=reply):
            res = _cli([verb, "--json", "-s", "pm-x"])
        assert res.exit_code == 1
        out = json.loads(res.output)
        assert out["error"] == "status_unavailable"
        assert "boom" in out["message"]

    def test_status_json_carries_owner_error(self, project, tmp_path):
        import os
        pidfile = tmp_path / "tui.pid"
        pidfile.write_text(str(os.getpid()))
        err = {"ok": False, "error": "internal", "message": "boom",
               "changes": [], "status": {"schema": "pm.autostart.status/1"}}
        with patch("pm_core.cli.autostart._tui_pidfile_for_session",
                   return_value=pidfile), \
             patch("pm_core.cli.autostart._request", return_value=err):
            res = _cli(["status", "--json", "-s", "pm-x"])
        assert res.exit_code == 1
        out = json.loads(res.output)
        assert (out["error"], out["message"]) == ("internal", "boom")

    def test_round_trip_through_tui_handler(self, project, tmp_path):
        """CLI → queue → TUI handle_command → reply file → CLI JSON."""
        pm_dir, home = project
        import os
        import shlex
        pidfile = tmp_path / "tui.pid"
        pidfile.write_text(str(os.getpid()))
        app = FakeApp(store.load(pm_dir)["prs"])
        sent = []

        def fake_trigger(session, cmd):
            sent.append(cmd)
            with patch("pm_core.tui.auto_start.pm_home", return_value=home):
                auto_start.handle_command(app, shlex.split(cmd)[1:])
            return True

        with patch("pm_core.cli.autostart._tui_pidfile_for_session",
                   return_value=pidfile), \
             patch("pm_core.cli.autostart.trigger_tui_command", fake_trigger):
            r1 = _cli(["add", "pr-a", "--json", "-s", "pm-x"])
            r2 = _cli(["add", "pr-b", "--auto-merge", "--json", "-s", "pm-x"])
            r3 = _cli(["status", "--json", "-s", "pm-x"])
            r4 = _cli(["remove", "pr-a", "-s", "pm-x"])
        assert r1.exit_code == 0, r1.output
        assert sent[1].startswith("autostart add pr-b --auto-merge --reply ")
        status = json.loads(r3.output)
        assert [(t["pr_id"], t["policy"]) for t in status["targets"]] == [
            ("pr-a", POLICY_STOP), ("pr-b", POLICY_AUTO)]
        assert "removed: pr-a" in r4.output
        assert auto_start.get_targets(app) == ["pr-b"]
        assert not list((home / "autostart-replies").glob("*.json"))


# ---------------------------------------------------------------------------
# Runs popup (Textual pilot)
# ---------------------------------------------------------------------------

def test_runs_popup_renders_targets_and_closes(tmp_path):
    from textual.app import App
    from textual.widgets import Static
    from pm_core.tui.screens import AutoRunsScreen

    prs = [_pr("d", status="in_progress"), _pr("a", deps=["d"]),
           _pr("b", status="qa")]

    class Host(App):
        def __init__(self):
            super().__init__()
            fake = _enabled_app(prs, ["a", "b"], tmp_path, stop={"a"})
            fake._qa_loops = {"b": QALoopState(pr_id="b", running=True,
                                               planning_phase=False,
                                               scenarios=[QAScenario(1, "s1", "", ""),
                                                          QAScenario(2, "s2", "", "")],
                                               scenario_verdicts={1: "PASS"})}
            for k, v in vars(fake).items():
                if k not in ("logs", "workers"):
                    setattr(self, k, v)
            self.logs = []

        def log_message(self, msg, **kw):
            self.logs.append(msg)

        restarted = 0

        def action_restart(self):
            self.restarted += 1

    async def body():
        app = Host()
        async with app.run_test(size=(140, 40)) as pilot:
            app.push_screen(AutoRunsScreen())
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, AutoRunsScreen)
            text = str(screen.query_one("#runs-body", Static).render())
            assert "◎ a" in text and "◎ b" in text
            assert "scenario 1/2 done" in text
            assert "stop-before-merge" in text
            # j moves selection; Enter on a run without window keeps popup open
            await pilot.press("j")
            await pilot.press("enter")
            assert isinstance(app.screen, AutoRunsScreen)
            assert any("No live window" in m for m in app.logs)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, AutoRunsScreen)
            # Ctrl+R (pm tui restart / merge restart) passes through the popup
            app.push_screen(AutoRunsScreen())
            await pilot.pause()
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert app.restarted == 1
            assert not isinstance(app.screen, AutoRunsScreen)

    asyncio.run(body())


def test_recorded_qa_verdict_used_when_loop_dropped(tmp_path):
    """A finished QA run leaves _qa_loops after one tick; the runtime_state
    verdict must still drive the reported state (not 'queued')."""
    app = _enabled_app([_pr("a", status="qa", workdir="/w/a")], ["a"], tmp_path)
    with patch("pm_core.runtime_state.get_action_state",
               return_value={"state": "done", "verdict": "PASS"}):
        s = auto_start.build_status(app)
    r = _run(s, "a")
    assert r["state"] == "waiting" and "awaiting sign-off" in r["reason"]
    assert r["qa"]["recorded"] is True


def test_qa_pass_with_fresh_signoff_reports_signed_off():
    r = _run(_status([_pr("a", status="qa")], ["a"], stop_before_merge={"a"},
                     qa_loops={"a": {"verdict": "PASS", "recorded": True}},
                     signoff={"a": {"verdict": "SIGNOFF_MERGE", "fresh": True}}),
             "a")
    assert r["state"] == "waiting" and "signed off" in r["reason"]



@pytest.mark.parametrize("recorded,relaunch", [
    ({"state": "done", "verdict": "PASS"}, False),
    ({"state": "done", "verdict": "INPUT_REQUIRED"}, False),
    ({"state": "done", "verdict": "NEEDS_WORK"}, True),
    ({"state": "running"}, True),
    ({}, True),
])
def test_finished_qa_not_relaunched_by_scheduler(tmp_path, recorded, relaunch):
    """Restart / extra scheduler passes must not re-run a QA run that
    already finished PASS (awaiting sign-off) or INPUT_REQUIRED."""
    app = _enabled_app([_pr("a", status="qa", workdir="/w/a")], ["a"], tmp_path)
    with patch("pm_core.runtime_state.get_action_state", return_value=recorded), \
         patch("pm_core.tui.qa_loop_ui.start_qa") as sq:
        auto_start._auto_start_qa_loops(app)
    assert sq.called is relaunch


class TestReloadTrigger:
    def test_manual_merge_seen_on_reload_kicks_scheduler(self, tmp_path):
        prs = [_pr("d", status="merged"), _pr("a", deps=["d"]), _pr("b")]
        app = _enabled_app(prs, ["a", "b"], tmp_path)
        auto_start.on_state_loaded(app, {"d": "qa", "a": "pending", "b": "pending"})
        assert len(app.workers) == 1

    def test_out_of_scope_merge_ignored(self, tmp_path):
        prs = [_pr("x", status="merged"), _pr("a")]
        app = _enabled_app(prs, ["a"], tmp_path)
        auto_start.on_state_loaded(app, {"x": "qa", "a": "pending"})
        assert app.workers == []

    def test_no_change_or_first_load_ignored(self, tmp_path):
        prs = [_pr("a", status="merged")]
        app = _enabled_app(prs, ["a"], tmp_path)
        auto_start.on_state_loaded(app, {"a": "merged"})
        auto_start.on_state_loaded(app, {})
        assert app.workers == []


class TestLogLineRecording:
    """Every log-line message also lands in the command log (``L``)."""

    def _app(self, sticky_until=0.0):
        from types import SimpleNamespace
        from pm_core.tui.app import ProjectManagerApp
        a = SimpleNamespace(_log_sticky_until=sticky_until)
        a.query_one = MagicMock(side_effect=Exception("no dom"))
        a.call_after_refresh = lambda *x, **k: None
        a._capture_frame = None
        return a, ProjectManagerApp.log_message

    def test_overwritten_and_hidden_messages_are_logged(self):
        import time
        app, log_message = self._app()
        with patch("pm_core.tui.app._log") as lg:
            log_message(app, "[green bold]QA PASS[/] for s — ready to merge")
            log_message(app, "Auto-merge: u review passed, merging")
            app._log_sticky_until = time.monotonic() + 60
            log_message(app, "Auto-sequence armed for d")  # hidden by sticky
            log_message(app, "Auto-sequence armed for d")  # dedup
        lines = [c.args[0] % c.args[1:] for c in lg.info.call_args_list]
        assert lines == [
            "log: QA PASS for s — ready to merge",
            "log: Auto-merge: u review passed, merging",
            "log: Auto-sequence armed for d (hidden by sticky message)",
        ]


class TestCursorFollowsActivePr:
    """The tree cursor follows active_pr changes, not every refresh, and
    never the scheduler's own background starts."""

    def _app(self):
        from types import SimpleNamespace
        from pm_core.tui.app import ProjectManagerApp
        a = SimpleNamespace(_followed_active_pr=None, _quiet_activations={})
        tree = MagicMock()
        follow = lambda pr: ProjectManagerApp._follow_active_pr(a, tree, pr)
        return a, tree, follow

    def test_refresh_does_not_snap_cursor_back(self):
        app, tree, follow = self._app()
        follow("a")
        tree.select_pr.assert_called_once_with("a")
        tree.select_pr.reset_mock()
        follow("a")  # reload / target change with unchanged active_pr
        tree.select_pr.assert_not_called()
        follow("b")  # pm pr select b
        tree.select_pr.assert_called_once_with("b")

    def test_scheduler_start_does_not_move_cursor(self):
        import time
        app, tree, follow = self._app()
        follow("a")
        tree.select_pr.reset_mock()
        app._quiet_activations["u"] = time.monotonic() + 60
        follow("u")  # auto-start's ``pr start --background u``
        tree.select_pr.assert_not_called()
        assert "u" not in app._quiet_activations

    def test_start_pr_quiet_marks_activation(self):
        app = FakeApp([_pr("u")])
        app._quiet_activations = {}

        class _P:
            returncode = 0

            async def communicate(self):
                return b"", b""

        async def fake_shell(*a, **k):
            return _P()

        with patch("pm_core.tui.auto_start._run_shell_async", fake_shell):
            asyncio.run(auto_start._start_pr_quiet(app, "u"))
        assert "u" in app._quiet_activations
