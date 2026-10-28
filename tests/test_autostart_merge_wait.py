"""Dependency-wide merge wait for auto-start (pr-e69afc4).

``pm autostart add <final> --wait-for-merge`` keeps the final PR as the only
target but holds it and every transitive prerequisite for a manual merge.
Covers the single effective-hold path (``autostart_state.merge_holds`` /
``auto_start.merge_hold``), its use by the merge decision, the sign-off
driver and status, target lifecycle (remove / policy change / graph change /
restart), contradictory flags, and an end-to-end diamond scenario driven
through the command queue handler and the scheduler.

The repo has no pytest-asyncio plugin: async bodies run via ``asyncio.run``.
"""

import asyncio
import json
import os
import shlex
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pm_core import autostart_state as st
from pm_core import store
from pm_core.autostart_state import POLICY_AUTO, POLICY_WAIT
from pm_core.tui import auto_start, signoff_ui
from pm_core.tui import review_loop_ui

from tests.test_autostart_multi_target import FakeApp, _pr


@pytest.fixture(autouse=True)
def _quiet_watcher():
    with patch("pm_core.tui.watcher_ui.is_running", return_value=False), \
         patch("pm_core.runtime_state.get_action_state", return_value={}):
        yield


_SIGNED = {"verdict": "SIGNOFF_MERGE", "sha": "head", "origin": "auto-sequence",
           # Integration-aware approval (pr-ac10f03): bound to the base too.
           "integration": {"head": "head", "status": "up_to_date", "base_branch": "master",
                "target_repo": "/repo", "base_sha": "base", "candidate_tree": "tree"}}


def _signed(pid, **kw):
    return _pr(pid, status="sign_off", workdir=f"/w/{pid}",
               signoff=dict(_SIGNED), **kw)


def _app(prs, tmp_path, targets=(), wait=()):
    """Enabled app; *targets* plain auto-merge, *wait* wait-for-merge."""
    app = FakeApp(prs, root=tmp_path)
    recs = {t: st.make_target_record("test") for t in targets}
    for t in wait:
        recs[t] = {**st.make_target_record("test"), st.WAIT_KEY: True}
    app._auto_start_targets = recs
    app._auto_start = bool(recs)
    app._auto_start_run_id = "run"
    return app


def _merge(app, pr_id):
    with patch.object(review_loop_ui, "_attempt_merge",
                      return_value=True) as am, \
         patch("pm_core.signoff.head_sha", return_value="head"), \
         patch.object(signoff_ui, "start_signoff") as ss:
        review_loop_ui._maybe_auto_merge(app, pr_id)
    am.start_signoff = ss
    return am


# Diamond: a, b ready; c ← a; d ← a, b; f ← c, d.  x unrelated.
def _diamond(**status):
    prs = [_pr("a"), _pr("b"), _pr("c", deps=["a"]),
           _pr("d", deps=["a", "b"]), _pr("f", deps=["c", "d"]), _pr("x")]
    for p in prs:
        if p["id"] in status:
            p["status"] = status[p["id"]]
    return prs


# ---------------------------------------------------------------------------
# Pure policy path
# ---------------------------------------------------------------------------

class TestMergeHolds:
    def test_wait_target_holds_whole_closure_only(self):
        prs = _diamond()
        holds = st.merge_holds(prs, {"f": {st.WAIT_KEY: True}})
        assert set(holds) == {"a", "b", "c", "d", "f"}
        assert holds["a"] == {"targets": ["f"]}
        assert st.effective_policy("a", holds) == POLICY_WAIT
        assert st.effective_policy("x", holds) == POLICY_AUTO

    def test_plain_auto_target_holds_nothing(self):
        holds = st.merge_holds(_diamond(), {"f": {}})
        assert holds == {}
        assert st.effective_policy("f", holds) == POLICY_AUTO

    def test_wait_hold_text_names_the_target(self):
        holds = st.merge_holds(_diamond(), {"f": {st.WAIT_KEY: True}})
        assert st.held_by_text(holds["a"]) == "wait-for-merge ← f"
        assert st.held_by_text(None) == ""

    def test_shared_dep_lists_every_wait_target(self):
        prs = _diamond() + [_pr("g", deps=["a"])]
        holds = st.merge_holds(prs, {"f": {st.WAIT_KEY: True},
                                     "g": {st.WAIT_KEY: True}})
        assert holds["a"]["targets"] == ["f", "g"]

    def test_merged_closure_members_not_held(self):
        holds = st.merge_holds(_diamond(a="merged", b="closed"),
                               {"f": {st.WAIT_KEY: True}})
        assert set(holds) == {"c", "d", "f"}

    def test_target_policy(self):
        assert st.target_policy({st.WAIT_KEY: True}) == POLICY_WAIT
        assert st.target_policy({}) == POLICY_AUTO
        assert st.target_policy(None) == POLICY_AUTO


# ---------------------------------------------------------------------------
# Target lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_add_wait_sets_record_flag(self, tmp_path):
        app = _app(_diamond(), tmp_path)
        res = auto_start.add_targets(app, ["f"], policy=POLICY_WAIT)
        assert res["changes"] == [{"pr_id": "f", "action": "added",
                                   "policy": POLICY_WAIT}]
        assert auto_start.get_targets(app) == ["f"]  # deps not targets
        assert app._auto_start_targets["f"][st.WAIT_KEY] is True
        for pid in "abcdf":
            assert auto_start.policy_for(app, pid) == POLICY_WAIT
        assert auto_start.policy_for(app, "x") == POLICY_AUTO
        assert any("wait-for-merge" in m for m in app.logs)

    def test_policy_established_before_scheduler_pass(self, tmp_path):
        """The hold exists when the queued check_and_start runs."""
        app = _app(_diamond(), tmp_path)
        seen = {}

        def capture(coro, *a, **kw):
            seen["hold"] = auto_start.merge_hold(app, "a")
            coro.close()
        app.run_worker = capture
        auto_start.add_targets(app, ["f"], policy=POLICY_WAIT)
        assert seen["hold"] == {"targets": ["f"]}

    def test_readd_without_flag_preserves_wait(self, tmp_path):
        app = _app(_diamond(), tmp_path, wait=["f"])
        res = auto_start.add_targets(app, ["f"], policy=None)
        assert res["changes"][0]["action"] == "unchanged"
        assert res["changes"][0]["policy"] == POLICY_WAIT
        assert auto_start.target_policy(app, "f") == POLICY_WAIT

    def test_policy_change_releases_its_holds(self, tmp_path):
        app = _app(_diamond(), tmp_path, wait=["f"])
        res = auto_start.add_targets(app, ["f"], policy=POLICY_AUTO)
        assert res["changes"][0] == {"pr_id": "f", "action": "policy_changed",
                                     "policy": POLICY_AUTO,
                                     "previous_policy": POLICY_WAIT}
        assert res["released"] == ["a", "b", "c", "d", "f"]
        assert auto_start.merge_holds(app) == {}
        assert any("released merge hold on a, b, c, d, f" in m for m in app.logs)

    def test_wait_to_auto_releases_whole_closure(self, tmp_path):
        app = _app(_diamond(), tmp_path, wait=["f"])
        res = auto_start.add_targets(app, ["f"], policy=POLICY_AUTO)
        assert res["released"] == ["a", "b", "c", "d", "f"]
        assert auto_start.merge_holds(app) == {}
        assert st.WAIT_KEY not in app._auto_start_targets["f"]

    def test_auto_to_wait_sets_flag(self, tmp_path):
        app = _app(_diamond(), tmp_path, targets=["f"])
        auto_start.add_targets(app, ["f"], policy=POLICY_WAIT)
        assert auto_start.target_policy(app, "f") == POLICY_WAIT
        assert app._auto_start_targets["f"][st.WAIT_KEY] is True

    def test_policy_change_keeps_other_target_holds(self, tmp_path):
        prs = _diamond() + [_pr("g", deps=["a"])]
        app = _app(prs, tmp_path, wait=["f", "g"])
        res = auto_start.add_targets(app, ["f"], policy=POLICY_AUTO)
        assert res["released"] == ["b", "c", "d", "f"]
        holds = auto_start.merge_holds(app)
        assert holds["a"] == {"targets": ["g"]}   # shared dep still held
        assert "b" not in holds and "c" not in holds and "d" not in holds

    def test_remove_releases_only_its_holds(self, tmp_path):
        prs = _diamond() + [_pr("g", deps=["a"])]
        app = _app(prs, tmp_path, wait=["f", "g"])
        res = auto_start.remove_targets(app, ["f"])
        # a stays held by g.
        assert res["released"] == ["b", "c", "d", "f"]
        holds = auto_start.merge_holds(app)
        assert holds["a"] == {"targets": ["g"]}
        assert "d" not in holds

    def test_removed_target_stays_held_while_another_wait_target_needs_it(
            self, tmp_path):
        """A target that is itself a prerequisite of another wait target:
        removing it releases only its own holds — the other target's hold
        and scope survive."""
        prs = [_pr("g"), _pr("f", deps=["g"])]
        app = _app(prs, tmp_path, wait=["f", "g"])
        res = auto_start.remove_targets(app, ["g"])
        assert res["changes"] == [{"pr_id": "g", "action": "removed"}]
        assert "released" not in res          # nothing stopped being held
        assert auto_start.in_scope(app, "g")  # still in f's closure
        assert auto_start.merge_hold(app, "g") == {"targets": ["f"]}
        assert auto_start.target_policy(app, "g") == POLICY_AUTO  # not a target

    def test_remove_does_not_report_merged_deps_released(self, tmp_path):
        app = _app(_diamond(a="merged", b="merged"), tmp_path, wait=["f"])
        res = auto_start.remove_targets(app, ["f"])
        assert res["released"] == ["c", "d", "f"]

    def test_remove_last_wait_target_releases_all(self, tmp_path):
        app = _app(_diamond(), tmp_path, wait=["f"])
        auto_start.remove_targets(app, ["f"])
        assert app._auto_start is False
        assert auto_start.merge_holds(app) == {}

    def test_mixed_policy_shared_dep(self, tmp_path):
        """A dep shared by an auto-merge target and a wait target is held;
        an unrelated auto target keeps auto-merge."""
        prs = _diamond() + [_pr("h", deps=["b"])]
        app = _app(prs, tmp_path, targets=["h", "x"], wait=["f"])
        assert auto_start.policy_for(app, "b") == POLICY_WAIT
        assert auto_start.policy_for(app, "h") == POLICY_AUTO
        assert auto_start.policy_for(app, "x") == POLICY_AUTO

    def test_graph_change_holds_new_dep_and_releases_dropped(self, tmp_path):
        prs = _diamond()
        app = _app(prs, tmp_path, wait=["f"])
        assert auto_start.merge_hold(app, "x") is None
        prs[4]["depends_on"] = ["c", "d", "x"]  # new prerequisite
        assert auto_start.merge_hold(app, "x")["targets"] == ["f"]
        prs[4]["depends_on"] = ["c"]  # d (and b) no longer needed
        assert auto_start.merge_hold(app, "d") is None
        assert auto_start.merge_hold(app, "b") is None
        assert auto_start.merge_hold(app, "a")["targets"] == ["f"]

    def test_breadcrumb_round_trip_keeps_wait(self, tmp_path):
        app = _app(_diamond(), tmp_path, wait=["f"])
        app._watcher_manager.is_any_running.return_value = False
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
            (tmp_path / "merge-restart").touch()
            auto_start.save_breadcrumb(app)
            fresh = FakeApp(_diamond(), root=tmp_path)
            with patch.object(auto_start, "_adopt_live_qa"), \
                 patch.object(auto_start, "check_and_start"):
                asyncio.run(auto_start.consume_breadcrumb(fresh))
        assert auto_start.target_policy(fresh, "f") == POLICY_WAIT
        assert auto_start.merge_hold(fresh, "b") == {"targets": ["f"]}
        assert fresh._auto_start_targets["f"][st.WAIT_KEY] is True


# ---------------------------------------------------------------------------
# Contradictory flags
# ---------------------------------------------------------------------------

class TestFlags:
    def test_handler_rejects_conflicting_policies(self, tmp_path):
        app = _app(_diamond(), tmp_path, targets=["x"])
        before = dict(app._auto_start_targets)
        res = auto_start.handle_command(
            app, ["add", "f", "--wait-for-merge", "--auto-merge"])
        assert res["ok"] is False and res["error"] == "conflicting_flags"
        assert dict(app._auto_start_targets) == before
        assert not app.workers

    def test_repeated_same_flag_is_fine(self, tmp_path):
        app = _app(_diamond(), tmp_path)
        res = auto_start.handle_command(
            app, ["add", "f", "--wait-for-merge", "--wait-for-merge"])
        assert res["ok"] is True
        assert auto_start.target_policy(app, "f") == POLICY_WAIT

    def test_policy_flag_on_remove_rejected(self, tmp_path):
        app = _app(_diamond(), tmp_path, wait=["f"])
        res = auto_start.handle_command(app, ["remove", "f", "--auto-merge"])
        assert res["ok"] is False and res["error"] == "usage"
        assert auto_start.get_targets(app) == ["f"]

    def test_unknown_id_with_wait_changes_nothing(self, tmp_path):
        app = _app(_diamond(), tmp_path)
        res = auto_start.handle_command(
            app, ["add", "f", "nope", "--wait-for-merge"])
        assert res["error"] == "unknown_pr"
        assert app._auto_start_targets == {}

    def test_cli_rejects_conflicting_flags_before_sending(self, tmp_path,
                                                          monkeypatch):
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        store.save({"project": {"name": "t", "repo": "/r",
                                "base_branch": "master"},
                    "prs": _diamond()}, pm_dir)
        monkeypatch.setattr("pm_core.cli.autostart.state_root", lambda: pm_dir)
        from pm_core.cli import cli
        with patch("pm_core.cli.autostart.trigger_tui_command") as trig:
            res = CliRunner().invoke(cli, [
                "autostart", "add", "f", "--stop-before-merge",
                "--auto-merge", "--json", "-s", "pm-x"])
        assert res.exit_code == 1
        out = json.loads(res.output)
        assert out["error"] == "conflicting_flags"
        assert "--wait-for-merge" in out["message"]
        assert "--auto-merge" in out["message"]
        trig.assert_not_called()

    def test_cli_list_names_only_other_holding_targets(self):
        from pm_core.cli import cli
        payload = {"ok": True, "status": {"mode": "targets", "targets": [
            {"pr_id": "f", "policy": "wait_for_merge",
             "held_by": ["f", "g"], "title": "F"},
            {"pr_id": "g", "policy": "wait_for_merge",
             "held_by": ["g"], "title": "G"},
        ]}}
        with patch("pm_core.cli.autostart._request", return_value=payload):
            res = CliRunner().invoke(cli, ["autostart", "list", "-s", "pm-x"])
        assert res.exit_code == 0, res.output
        assert "f  wait-for-merge (held by g)  F" in res.output
        assert "g  wait-for-merge  G" in res.output

    def test_cli_help_documents_wait(self):
        from pm_core.cli import cli
        res = CliRunner().invoke(cli, ["autostart", "add", "--help"])
        assert "--wait-for-merge" in res.output
        assert "pm autostart add pr-final --wait-for-merge" in res.output


# ---------------------------------------------------------------------------
# Merge decision + sign-off driver
# ---------------------------------------------------------------------------

class TestMergeDecision:
    def test_wait_held_dep_not_merged_shows_waiting(self, tmp_path):
        prs = [_signed("a"), _pr("f", deps=["a"])]
        app = _app(prs, tmp_path, wait=["f"])
        assert not _merge(app, "a").called
        assert any("a signed off" in m and "waiting for manual merge" in m
                   and "wait-for-merge: f" in m for m in app.logs)

    def test_wait_target_itself_not_merged(self, tmp_path):
        app = _app([_signed("f")], tmp_path, wait=["f"])
        assert not _merge(app, "f").called

    def test_auto_target_dep_merges_unless_held(self, tmp_path):
        prs = [_signed("a"), _pr("t", deps=["a"]), _signed("y")]
        app = _app(prs, tmp_path, targets=["t", "y"])
        assert _merge(app, "a").called
        assert _merge(app, "y").called

    def test_shared_dep_held_by_wait_even_with_auto_target(self, tmp_path):
        prs = [_signed("a"), _pr("t", deps=["a"]), _pr("f", deps=["a"])]
        app = _app(prs, tmp_path, targets=["t"], wait=["f"])
        assert not _merge(app, "a").called

    def test_stale_signoff_never_claims_waiting(self, tmp_path):
        """Fresh sign-off is still required: a held PR with a stale record
        is not reported as waiting for a manual merge."""
        prs = [_signed("a"), _pr("f", deps=["a"])]
        prs[0]["signoff"]["sha"] = "old"
        app = _app(prs, tmp_path, wait=["f"])
        assert not _merge(app, "a").called
        assert not any("waiting for manual merge" in m for m in app.logs)

    def test_qa_pr_hands_to_signoff_not_waiting(self, tmp_path):
        prs = [_pr("a", status="qa", workdir="/w/a"), _pr("f", deps=["a"])]
        app = _app(prs, tmp_path, wait=["f"])
        am = _merge(app, "a")
        assert not am.called
        am.start_signoff.assert_called_once_with(app, "a")

    def test_signoff_driver_reacts_when_hold_released(self, tmp_path):
        """Sign-off acts once per (verdict, sha, effective policy): a policy
        change that releases the hold re-runs the merge decision."""
        prs = [_signed("a"), _pr("f", deps=["a"])]
        app = _app(prs, tmp_path, wait=["f"])
        app._session_name = "s"
        from pm_core.signoff import SignoffStep
        calls = []
        with patch("pm_core.signoff.step_signoff",
                   return_value=SignoffStep("hop", hop="ready_to_merge",
                                            verdict="SIGNOFF_MERGE",
                                            sha="head")), \
             patch.object(signoff_ui, "_adopt_orphaned_run"), \
             patch("pm_core.tui.review_loop_ui._maybe_auto_merge",
                   side_effect=lambda a, p: calls.append(
                       auto_start.policy_for(a, p))):
            signoff_ui.step(app, "a", prs[0])
            signoff_ui.step(app, "a", prs[0])  # same key: no repeat
            auto_start.add_targets(app, ["f"], policy=POLICY_AUTO)
            signoff_ui.step(app, "a", prs[0])
        assert calls == [POLICY_WAIT, POLICY_AUTO]


# ---------------------------------------------------------------------------
# Status (CLI text + popup rows)
# ---------------------------------------------------------------------------

class TestStatus:
    def _status(self, prs, tmp_path, **kw):
        app = _app(prs, tmp_path, **kw)
        with patch("pm_core.signoff.head_sha", return_value="head"):
            return auto_start.build_status(app)

    def test_runs_report_effective_policy_and_cause(self, tmp_path):
        prs = _diamond(a="sign_off", b="in_progress")
        prs[0]["signoff"] = dict(_SIGNED)
        prs[0]["workdir"] = "/w/a"
        status = self._status(prs, tmp_path, wait=["f"], targets=["x"])
        runs = {r["pr_id"]: r for r in status["runs"]}
        assert runs["a"]["policy"] == POLICY_WAIT
        assert runs["a"]["held_by"] == ["f"]
        assert "waiting for manual merge (held by f)" in runs["a"]["reason"]
        assert runs["x"]["policy"] == POLICY_AUTO and runs["x"]["held_by"] == []
        assert "wait-for-merge ← f" in runs["c"]["reason"]  # blocked on a
        tgt = {t["pr_id"]: t for t in status["targets"]}
        assert tgt["f"]["policy"] == POLICY_WAIT
        assert tgt["x"]["policy"] == POLICY_AUTO

    def test_text_and_rows_name_holding_target(self, tmp_path):
        prs = _diamond() + [_pr("h", deps=["b"])]
        status = self._status(prs, tmp_path, wait=["f"], targets=["h"])
        text = st.format_text(status)
        assert "◎ f [wait-for-merge]" in text
        assert "└ a [wait-for-merge ← f]" in text
        # h is an auto-merge target; its dep b is held by f.
        assert "◎ h " in text and "◎ h [" not in text
        rows = st.status_rows(status)
        labels = {(r["kind"], r["pr_id"]): st.policy_labels(r) for r in rows}
        assert labels[("target", "f")] == [("wait-for-merge", "wait")]
        assert labels[("dep", "b")] == [("wait-for-merge ← f", "wait")]
        assert labels[("target", "h")] == [("auto-merge", "auto")]

    def test_auto_target_inside_wait_closure_says_held(self, tmp_path):
        status = self._status(_diamond(), tmp_path, targets=["a"], wait=["f"])
        rows = st.status_rows(status)
        row = next(r for r in rows if r["kind"] == "target" and r["pr_id"] == "a")
        assert st.policy_labels(row) == [("auto-merge, held", "auto"),
                                         ("wait-for-merge ← f", "wait")]
        assert "◎ a [auto-merge, held; wait-for-merge ← f]" in \
            st.format_text(status)

    def test_target_row_without_run_still_names_wait(self):
        # A completed wait target has no run entry and holds nothing (its
        # closure is merged), but its header still names its policy.
        row = {"pr_id": "f", "kind": "target", "policy": st.POLICY_WAIT,
               "run": {"pr_id": "f", "policy": st.POLICY_AUTO, "held_by": []}}
        assert st.policy_labels(row) == [("wait-for-merge", "wait")]


def test_runs_popup_shows_wait_policy(tmp_path):
    from textual.app import App
    from textual.widgets import Static
    from pm_core.tui.screens import AutoRunsScreen

    prs = _diamond()

    class Host(App):
        def __init__(self):
            super().__init__()
            fake = _app(prs, tmp_path, wait=["f"])
            for k, v in vars(fake).items():
                if k not in ("logs", "workers"):
                    setattr(self, k, v)

        def log_message(self, msg, **kw):
            pass

    async def body():
        app = Host()
        async with app.run_test(size=(160, 50)) as pilot:
            app.push_screen(AutoRunsScreen())
            await pilot.pause()
            text = str(app.screen.query_one("#runs-body", Static).render())
            assert "◎ f [wait-for-merge]" in text
            assert "└ a [wait-for-merge ← f]" in text

    asyncio.run(body())


# ---------------------------------------------------------------------------
# End to end: diamond through the command queue + scheduler
# ---------------------------------------------------------------------------

class DiskApp(FakeApp):
    """FakeApp backed by a real project.yaml: ``_load_state`` re-reads disk
    and calls ``on_state_loaded`` like ``TechTreeApp._load_state``; workers
    are queued and drained by the test (the scheduler's own follow-ups)."""

    def __init__(self, root):
        super().__init__(store.load(root)["prs"], root=root)
        self._data = store.load(root)
        self.queue: list = []

    def _load_state(self):
        prs = (self._data or {}).get("prs") or []
        old = {p.get("id"): p.get("status") for p in prs}
        old_deps = {p.get("id"): list(p.get("depends_on") or []) for p in prs}
        self._data = store.load(self._root)
        auto_start.on_state_loaded(self, old, old_deps)

    def run_worker(self, coro, *a, **kw):
        self.queue.append(coro)

    def drain(self):
        while self.queue:
            asyncio.run(self.queue.pop(0))


def _set(root, pr_id, **fields):
    def apply(d):
        p = store.get_pr(d, pr_id)
        p.update(fields)
    store.locked_update(root, apply)


def test_diamond_wait_for_merge_end_to_end(tmp_path):
    root = tmp_path / "pm"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    store.save({"project": {"name": "t", "repo": "/r", "base_branch": "master"},
                "prs": _diamond()}, root)
    app = DiskApp(root)
    app._session_name = "s"
    started: list[str] = []
    merged_calls: list[str] = []

    async def fake_start(_app, pr_id, fresh=False):
        # Re-ensuring an in_progress PR's window is a no-op start.
        if store.get_pr(store.load(root), pr_id)["status"] == "pending":
            started.append(pr_id)
            _set(root, pr_id, status="in_progress", workdir=f"/w/{pr_id}")

    def sign_off(*ids):
        for pid in ids:
            _set(root, pid, status="sign_off", signoff=dict(_SIGNED))
        app._load_state()

    def manual_merge(pid):
        # What ``pm pr merge`` (g) finalises before trigger_tui_refresh().
        _set(root, pid, status="merged")
        app._load_state()  # SIGUSR1 reload → on_state_loaded
        app.drain()

    def scheduler_pass():
        app.queue.append(auto_start.check_and_start(app))
        app.drain()

    pidfile = tmp_path / "tui.pid"
    pidfile.write_text(str(os.getpid()))

    def fake_trigger(session, cmd):
        with patch("pm_core.tui.auto_start.pm_home", return_value=home):
            auto_start.handle_command(app, shlex.split(cmd)[1:])
        return True

    with patch.object(auto_start, "_start_pr_quiet", fake_start), \
         patch("pm_core.signoff.head_sha", return_value="head"), \
         patch.object(signoff_ui, "_adopt_orphaned_run"), \
         patch.object(review_loop_ui, "_attempt_merge",
                      side_effect=lambda a, p, **kw: merged_calls.append(p)), \
         patch("pm_core.tui.review_loop_ui._start_loop"), \
         patch("pm_core.tui.qa_loop_ui.start_qa"), \
         patch("pm_core.cli.autostart.state_root", lambda: root), \
         patch("pm_core.cli.autostart.pm_home", lambda: home), \
         patch("pm_core.cli.autostart._tui_pidfile_for_session",
               return_value=pidfile), \
         patch("pm_core.cli.autostart.trigger_tui_command", fake_trigger):
        from pm_core.cli import cli
        res = CliRunner().invoke(cli, ["autostart", "add", "f",
                                       "--wait-for-merge", "-s", "pm-x"])
        assert res.exit_code == 0, res.output
        assert "added: f (wait-for-merge)" in res.output
        assert auto_start.get_targets(app) == ["f"]
        app.drain()  # the add's scheduler pass
        assert sorted(started) == ["a", "b"]  # both initially ready

        # Both reach a fresh sign-off and wait; nothing auto-merges.
        sign_off("a", "b")
        scheduler_pass()
        assert merged_calls == []
        waiting = [m for m in app.logs if "waiting for manual merge" in m]
        assert any("✓ a signed off" in m for m in waiting)
        assert any("✓ b signed off" in m for m in waiting)
        status = json.loads(CliRunner().invoke(
            cli, ["autostart", "status", "--json", "-s", "pm-x"]).output)
        runs = {r["pr_id"]: r for r in status["runs"]}
        assert runs["a"]["held_by"] == ["f"]
        assert "waiting for manual merge" in runs["a"]["reason"]

        # Manual merge of a starts c (d still needs b) — no new command.
        manual_merge("a")
        assert sorted(started) == ["a", "b", "c"]
        manual_merge("b")
        assert sorted(started) == ["a", "b", "c", "d"]

        # Merge restart mid-chain: the wait policy survives.
        app._watcher_manager.is_any_running.return_value = False
        with patch("pm_core.tui.auto_start.pm_home", return_value=home):
            (home / "merge-restart").touch()
            auto_start.save_breadcrumb(app)
            restarted = DiskApp(root)
            restarted._session_name = "s"
            asyncio.run(auto_start.consume_breadcrumb(restarted))
        app = restarted
        assert auto_start.target_policy(app, "f") == POLICY_WAIT

        # Next stage: c, d sign off and wait; a stale sign-off on d is not
        # treated as merge-ready (fresh sign-off still required).
        _set(root, "d", status="sign_off",
             signoff={**_SIGNED, "sha": "old"})
        sign_off("c")
        with patch("pm_core.signoff.retire_signoff_run"), \
             patch.object(signoff_ui, "_launch") as relaunch:
            scheduler_pass()
        relaunch.assert_called_once()
        assert relaunch.call_args.args[1] == "d"
        assert merged_calls == []
        assert any("✓ c signed off" in m and "waiting for manual merge" in m
                   for m in app.logs)
        assert not any("✓ d signed off" in m for m in app.logs)
        sign_off("d")
        scheduler_pass()
        assert any("✓ d signed off" in m for m in app.logs)

        manual_merge("c")
        assert "f" not in started  # d still unmerged
        manual_merge("d")
        assert started[-1] == "f"

        sign_off("f")
        scheduler_pass()
        assert merged_calls == []
        assert any("✓ f signed off" in m and "waiting for manual merge" in m
                   for m in app.logs)
        manual_merge("f")
        assert auto_start.get_targets(app) == []
        assert app._auto_start is False
        assert "x" not in started  # unrelated PR never scheduled
