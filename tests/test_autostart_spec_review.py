"""Spec-review pauses for auto-start (pr-3ae2fc3).

``pm autostart add <final> --review-specs`` pauses the target and every
transitive prerequisite for human approval of the implementation spec and
again of the QA spec.  Covers the derived requirement
(``autostart_state.spec_review_holds`` / ``auto_start.spec_review_required``),
the connection of inline spec generation to ``spec_pending``
(``hold_spec_if_due`` / ``sync_spec_reviews`` and the QA planner gate),
approval recording + agent notification, target lifecycle (repeated adds,
removal, restart), status/popup/tree/picker visibility, and an end-to-end
dependency chain driven through the CLI, the scheduler and
``pm pr spec-approve``.

The repo has no pytest-asyncio plugin: async bodies run via ``asyncio.run``.
"""

import asyncio
import json
import os
import shlex
import time
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from pm_core import autostart_state as st
from pm_core import qa_loop, spec_gen, store
from pm_core.autostart_state import POLICY_WAIT, REVIEW_KEY
from pm_core.tui import auto_start, review_loop_ui, signoff_ui

from tests.test_autostart_merge_wait import DiskApp as _DiskApp, _SIGNED, _set
from tests.test_autostart_multi_target import FakeApp, _pr


@pytest.fixture(autouse=True)
def _quiet_watcher():
    with patch("pm_core.tui.watcher_ui.is_running", return_value=False), \
         patch("pm_core.runtime_state.get_action_state", return_value={}), \
         patch("pm_core.spec_gen.get_global_setting_value",
               return_value="prompt"):
        yield


class DiskApp(_DiskApp):
    """``_load_state`` also hands over the pending-spec map, like
    ``TechTreeApp._load_state`` (approval-triggered scheduler passes)."""

    def _load_state(self):
        prs = (self._data or {}).get("prs") or []
        old = {p.get("id"): p.get("status") for p in prs}
        old_deps = {p.get("id"): list(p.get("depends_on") or []) for p in prs}
        old_spec = {p.get("id"): bool(p.get("spec_pending")) for p in prs}
        self._data = store.load(self._root)
        auto_start.on_state_loaded(self, old, old_deps, old_spec)


def _row_label(line: str) -> str:
    """Action label of a picker row (past the ●/○ indicator column)."""
    return line.replace("●", " ").replace("○", " ").split()[0]


def _write_spec(workdir, pr_id, phase, text="# spec\n\nbody"):
    p = workdir / "pm" / "specs" / pr_id / f"{phase}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _app(prs, root, targets=None):
    """Enabled FakeApp; *targets* maps id → record overrides."""
    app = FakeApp(prs, root=root)
    app._auto_start_targets = {
        t: {**st.make_target_record("test"), **(rec or {})}
        for t, rec in (targets or {}).items()}
    app._auto_start = bool(app._auto_start_targets)
    app._auto_start_run_id = "run"
    return app


def _disk(tmp_path, prs):
    root = tmp_path / "pm"
    root.mkdir()
    store.save({"project": {"name": "t", "repo": "/r", "base_branch": "master"},
                "prs": prs}, root)
    return root


# ---------------------------------------------------------------------------
# Pure derivation
# ---------------------------------------------------------------------------

class TestSpecReviewHolds:
    PRS = [_pr("a"), _pr("b", deps=["a"]), _pr("c", deps=["a"]), _pr("x")]

    def test_closure_of_review_targets_only(self):
        out = st.spec_review_holds(self.PRS, {"b": {REVIEW_KEY: True},
                                              "c": {}})
        assert out == {"a": ["b"], "b": ["b"]}

    def test_shared_dep_lists_every_review_target(self):
        out = st.spec_review_holds(self.PRS, {"b": {REVIEW_KEY: True},
                                              "c": {REVIEW_KEY: True}})
        assert out["a"] == ["b", "c"]

    def test_merged_members_skipped(self):
        prs = [_pr("a", status="merged"), _pr("b", deps=["a"])]
        assert st.spec_review_holds(prs, {"b": {REVIEW_KEY: True}}) == {
            "b": ["b"]}

    def test_breadcrumb_roundtrip_keeps_option(self):
        recs = {"b": {**st.make_target_record("cli"), REVIEW_KEY: True,
                      st.WAIT_KEY: True}}
        data = {"targets": st.targets_to_breadcrumb(recs), "all_mode": False}
        targets, _, _ = st.targets_from_breadcrumb(json.loads(json.dumps(data)))
        assert targets["b"][REVIEW_KEY] is True
        assert targets["b"][st.WAIT_KEY] is True


class TestStatus:
    def _status(self, prs, targets, **inp):
        return st.build_status({"prs": prs, "targets": targets, **inp})

    def test_pending_impl_spec_reason_and_fields(self):
        prs = [_pr("a", status="in_progress",
                   spec_pending={"phase": "impl", "generated_at": "t0"}),
               _pr("b", deps=["a"])]
        s = self._status(prs, {"b": {REVIEW_KEY: True}},
                         spec_reviews={"a": {"path": "/w/a/pm/specs/a/impl.md"}})
        run = {r["pr_id"]: r for r in s["runs"]}["a"]
        assert run["state"] == "waiting"
        assert run["reason"].startswith("impl spec awaiting approval")
        assert "pm pr spec-approve a" in run["reason"]
        assert run["spec_review"] == {
            "phase": "impl", "path": "/w/a/pm/specs/a/impl.md",
            "generated_at": "t0", "approve": "pm pr spec-approve a",
            "key": "V"}
        assert run["review_specs"] is True and run["review_specs_by"] == ["b"]
        assert s["targets"][0]["review_specs"] is True
        text = st.format_text(s)
        assert "[review-specs ← b; spec review: impl]" in text
        assert "spec=/w/a/pm/specs/a/impl.md" in text
        assert "◎ b [stop-before-merge; review-specs]" not in text  # auto
        assert "◎ b [review-specs]" in text

    def test_pending_qa_spec_outranks_running_planner(self):
        prs = [_pr("a", status="qa", workdir="/w/a",
                   spec_pending={"phase": "qa"})]
        s = self._status(prs, {"a": {REVIEW_KEY: True}},
                         qa_loops={"a": {"running": True, "planning": True}})
        run = s["runs"][0]
        assert run["phase"] == "qa" and run["state"] == "waiting"
        assert run["reason"].startswith("QA spec awaiting approval")
        assert "scenarios launch after approval" in run["reason"]

    def test_pending_pr_with_impl_spec_waits(self):
        prs = [_pr("a", spec_pending={"phase": "impl"})]
        run = self._status(prs, {"a": {}})["runs"][0]
        assert (run["phase"], run["state"]) == ("pending", "waiting")
        # Explicit/global review mode without the option is still reported.
        assert run["review_specs"] is False

    def test_default_targets_unchanged(self):
        s = self._status([_pr("a")], {"a": {}})
        run = s["runs"][0]
        assert run["spec_review"] is None and run["review_specs"] is False
        assert "review" not in st.format_text(s).split("—")[0].split("a", 1)[1]

    def test_review_mode_pr_label(self):
        s = self._status([_pr("a")], {"a": {}}, spec_review_modes={"a"})
        rows = st.status_rows(s)
        assert st.review_labels(rows[0]) == ["review-spec"]


# ---------------------------------------------------------------------------
# spec_gen pieces
# ---------------------------------------------------------------------------

class TestSpecGen:
    def test_mark_pending_needs_approval_and_approve_records(self, tmp_path):
        wd = tmp_path / "wd"
        root = _disk(tmp_path, [_pr("a", status="in_progress",
                                    workdir=str(wd))])
        pr = store.get_pr(store.load(root), "a")
        assert not spec_gen.needs_spec_approval(pr, "impl")  # no spec yet
        _write_spec(wd, "a", "impl")
        assert spec_gen.needs_spec_approval(pr, "impl")
        assert spec_gen.mark_spec_pending(root, "a", "impl", pr=pr)
        assert not spec_gen.mark_spec_pending(root, "a", "impl")  # no dup
        data = store.load(root)
        pend = store.get_pr(data, "a")["spec_pending"]
        assert pend["phase"] == "impl" and pend["review"] is True
        assert spec_gen.approve_spec(data, "a", root=root) == "impl"
        fresh = store.get_pr(store.load(root), "a")
        assert "spec_pending" not in fresh
        assert spec_gen.is_spec_approved(fresh, "impl")
        assert not spec_gen.needs_spec_approval(fresh, "impl")

    def test_edited_approval_updates_the_copy_get_spec_reads(self, tmp_path):
        wd = tmp_path / "wd"
        root = _disk(tmp_path, [_pr("a", status="in_progress", workdir=str(wd),
                                    spec_pending={"phase": "impl"})])
        path = _write_spec(wd, "a", "impl", "original")
        data = store.load(root)
        spec_gen.approve_spec(data, "a", root=root, edited_text="edited")
        assert path.read_text() == "edited"
        assert spec_gen.get_spec(store.get_pr(data, "a"), "impl") == "edited"

    def test_fresh_workdir_gets_spec_approved_before_start(self, tmp_path):
        """A spec approved with edits while the PR had no workdir lives in
        the uncommitted local pm/specs; seeding the fresh clone keeps the
        clone's committed copy from shadowing it.  A workdir copy that
        already differs from the committed one (branch content) is kept."""
        import subprocess

        def git(*args, cwd):
            subprocess.run(["git", *args], cwd=cwd, check=True,
                           capture_output=True)

        repo = tmp_path / "repo"
        root = repo / "pm"
        for pr_id in ("a", "b"):
            _write_spec(repo, pr_id, "impl", "committed")
        git("init", "-q", "-b", "master", cwd=repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
            "--allow-empty", "-m", "init", cwd=repo)
        git("add", "-A", cwd=repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
            "-m", "specs", cwd=repo)
        for pr_id in ("a", "b"):
            (root / "specs" / pr_id / "impl.md").write_text("approved")
        wd = tmp_path / "wd"
        git("clone", "-q", str(repo), str(wd), cwd=tmp_path)
        (wd / "pm/specs/b/impl.md").write_text("branch")

        assert spec_gen.seed_workdir_specs(root, "a", wd) == [
            wd / "pm/specs/a/impl.md"]
        assert spec_gen.seed_workdir_specs(root, "b", wd) == []
        assert spec_gen.get_spec({"id": "a", "workdir": str(wd)},
                                 "impl") == "approved"
        assert (wd / "pm/specs/b/impl.md").read_text() == "branch"

    def test_reject_keeps_gate_held_spec_pending(self, tmp_path):
        """Rejecting regenerates in review mode: the phase stays paused even
        though the PR's own mode (prompt) would clear it."""
        wd = tmp_path / "wd"
        root = _disk(tmp_path, [_pr("a", status="in_progress", workdir=str(wd),
                                    spec_pending={"phase": "impl",
                                                  "review": True})])
        _write_spec(wd, "a", "impl", "v1")
        with patch("pm_core.spec_gen.launch_claude_print", return_value="v2"):
            assert spec_gen.reject_spec(store.load(root), "a",
                                        feedback="more", root=root) == "impl"
        pr = store.get_pr(store.load(root), "a")
        assert pr["spec_pending"]["phase"] == "impl"
        assert pr["spec_pending"]["review"] is True
        assert spec_gen.get_spec(pr, "impl") == "v2"

    def test_regenerated_spec_needs_approval_again(self, tmp_path):
        """``pm pr spec --regenerate`` writes new content: the earlier
        approval no longer covers it (only that phase's record drops)."""
        wd = tmp_path / "wd"
        root = _disk(tmp_path, [_pr("a", status="in_progress", workdir=str(wd),
                                    spec_approved={"impl": "t0", "qa": "t1"})])
        _write_spec(wd, "a", "impl", "v1")
        assert not spec_gen.needs_spec_approval(
            store.get_pr(store.load(root), "a"), "impl")
        with patch("pm_core.spec_gen.launch_claude_print", return_value="v2"):
            spec_gen.generate_spec(store.load(root), "a", "impl", root=root,
                                   force=True)
        pr = store.get_pr(store.load(root), "a")
        assert pr["spec_approved"] == {"qa": "t1"}
        assert spec_gen.needs_spec_approval(pr, "impl")

    def test_cli_regenerate_refreshes_tui(self, tmp_path):
        """The TUI holds the PR in memory: without a refresh it keeps the
        dropped approval and never re-holds the step for review."""
        from pm_core.cli import cli
        wd = tmp_path / "wd"
        root = _disk(tmp_path, [_pr("a", status="in_progress", workdir=str(wd),
                                    spec_approved={"impl": "t0"})])
        _write_spec(wd, "a", "impl", "v1")
        with patch("pm_core.cli.pr.state_root", lambda: root), \
             patch("pm_core.spec_gen.launch_claude_print", return_value="v2"), \
             patch("pm_core.cli.pr.trigger_tui_refresh") as refresh:
            res = CliRunner().invoke(cli, ["pr", "spec", "a", "impl",
                                           "--regenerate"])
        assert res.exit_code == 0, res.output
        assert "v2" in res.output
        refresh.assert_called_once_with()
        assert "spec_approved" not in store.get_pr(store.load(root), "a")

    def test_review_gate_preamble_requires_pm_approval(self, tmp_path):
        pr = {"id": "pr-x", "title": "t"}
        plain = spec_gen.spec_generation_preamble(pr, "impl", root=tmp_path)
        gated = spec_gen.spec_generation_preamble(pr, "impl", root=tmp_path,
                                                  review_gate=True)
        assert "pm pr spec-approve" not in plain
        assert "Use your best judgement" in plain  # prompt mode unchanged
        assert "present a brief summary of the spec" in gated
        assert "pm pr spec-approve pr-x" in gated
        assert "do not\nstart the implementation work" in gated

    def test_notify_sends_to_impl_and_planner_panes(self):
        pr = {"id": "pr-x", "gh_pr_number": 7}
        with patch("pm_core.loop_shared.find_claude_pane",
                   side_effect=lambda s, w: f"%{w}") as find, \
             patch("pm_core.tmux.send_keys") as send:
            assert spec_gen.notify_spec_approved(pr, "impl", session="s")
            assert spec_gen.notify_spec_approved(pr, "qa", edited=True,
                                                 session="s")
        assert [c.args[1] for c in find.call_args_list] == ["#7", "qa-#7"]
        msgs = [c.args[1] for c in send.call_args_list if c.args[1]]
        assert "implementation spec (pm/specs/pr-x/impl.md) was approved" in msgs[0]
        assert "approved with edits" in msgs[1]
        assert "Commit and push the edited pm/specs/pr-x/qa.md" in msgs[1]
        assert "QA_PLAN_START" in msgs[1]
        assert "Commit and push" not in msgs[0]

    def test_notify_noop_without_window(self):
        with patch("pm_core.loop_shared.find_claude_pane", return_value=None), \
             patch("pm_core.tmux.send_keys") as send:
            assert not spec_gen.notify_spec_approved({"id": "a"}, "impl",
                                                     session="s")
        send.assert_not_called()


# ---------------------------------------------------------------------------
# Target lifecycle (CLI flags, command bar, repeated adds, removal)
# ---------------------------------------------------------------------------

class TestTargets:
    def test_add_with_option_composes_with_policy(self, tmp_path):
        app = _app([_pr("a"), _pr("b", deps=["a"])], tmp_path)
        res = auto_start.handle_command(
            app, ["add", "b", "--review-specs", "--wait-for-merge"])
        assert res["ok"]
        assert res["changes"] == [{"pr_id": "b", "action": "added",
                                   "policy": POLICY_WAIT,
                                   "review_specs": True}]
        assert app._auto_start_targets["b"][REVIEW_KEY] is True
        assert auto_start.spec_review_required(app, "a")
        assert any("b (wait-for-merge + deps, review-specs)" in m
                   for m in app.logs)

    def test_readd_keeps_flip_and_clear(self, tmp_path):
        app = _app([_pr("a")], tmp_path)
        auto_start.handle_command(app, ["add", "a", "--review-specs"])
        res = auto_start.handle_command(app, ["add", "a"])
        assert res["changes"][0]["action"] == "unchanged"
        assert res["changes"][0]["review_specs"] is True
        res = auto_start.handle_command(app, ["add", "a", "--no-review-specs"])
        assert res["changes"][0] == {
            "pr_id": "a", "action": "options_changed",
            "policy": "stop_before_merge", "review_specs": False,
            "previous_review_specs": True}
        assert not auto_start.spec_review_required(app, "a")

    def test_conflicting_review_flags_change_nothing(self, tmp_path):
        app = _app([_pr("a")], tmp_path)
        res = auto_start.handle_command(
            app, ["add", "a", "--review-specs", "--no-review-specs"])
        assert res["error"] == "conflicting_flags"
        assert auto_start.get_targets(app) == []

    @pytest.mark.parametrize("order", [
        ["--review-specs", "--no-review-specs"],
        ["--no-review-specs", "--review-specs"]])
    def test_cli_rejects_conflicting_review_flags_before_sending(
            self, tmp_path, monkeypatch, order):
        pm_dir = tmp_path / "pm"
        pm_dir.mkdir()
        store.save({"project": {"name": "t", "repo": "/r",
                                "base_branch": "master"},
                    "prs": [_pr("a")]}, pm_dir)
        monkeypatch.setattr("pm_core.cli.autostart.state_root", lambda: pm_dir)
        from pm_core.cli import cli
        with patch("pm_core.cli.autostart.trigger_tui_command") as trig:
            res = CliRunner().invoke(cli, [
                "autostart", "add", "a", *order, "--json", "-s", "pm-x"])
        assert res.exit_code == 1
        out = json.loads(res.output)
        assert out["error"] == "conflicting_flags"
        assert out["message"] == (
            "conflicting flags: --review-specs, --no-review-specs")
        trig.assert_not_called()

    def test_flag_rejected_off_add(self, tmp_path):
        app = _app([_pr("a")], tmp_path, {"a": {}})
        res = auto_start.handle_command(app, ["remove", "a", "--review-specs"])
        assert res["error"] == "usage"
        assert auto_start.get_targets(app) == ["a"]

    def test_list_summary_shows_option(self, tmp_path):
        app = _app([_pr("a"), _pr("b")], tmp_path,
                   {"a": {REVIEW_KEY: True}, "b": {}})
        app._stop_before_merge = {"a"}
        auto_start.handle_command(app, ["list"])
        assert app.logs[-1] == "Auto-start targets: a (stop, review-specs), b"

    def test_shared_dep_and_removal_never_approves(self, tmp_path):
        wd = tmp_path / "wa"
        root = _disk(tmp_path, [_pr("a", status="in_progress", workdir=str(wd)),
                                _pr("b", deps=["a"]), _pr("c", deps=["a"])])
        app = DiskApp(root)
        app._auto_start_targets = {"b": {REVIEW_KEY: True}, "c": {}}
        app._auto_start = True
        app._auto_start_run_id = "run"
        # Shared prerequisite: review applies because b asks for it.
        assert auto_start.spec_review_required(app, "a")
        _write_spec(wd, "a", "impl")
        pr_a = store.get_pr(app._data, "a")
        assert auto_start.hold_spec_if_due(app, pr_a)
        # Removing the review target releases the requirement …
        auto_start.remove_targets(app, ["b"])
        assert not auto_start.spec_review_required(app, "a")
        # … but the spec already waiting stays waiting.
        app._load_state()
        assert store.get_pr(app._data, "a")["spec_pending"]["phase"] == "impl"
        status = auto_start.build_status(app)
        run = {r["pr_id"]: r for r in status["runs"]}["a"]
        assert run["reason"].startswith("impl spec awaiting approval")

    def test_mid_impl_approval_replaces_awaiting_line(self, tmp_path):
        # An in_progress PR resumes in its pane on approval — no "starting"
        # line follows, so the reload must supersede "awaiting approval".
        wd = tmp_path / "wa"
        root = _disk(tmp_path, [_pr("a", status="in_progress",
                                    workdir=str(wd))])
        app = DiskApp(root)
        app._auto_start_targets = {"a": {REVIEW_KEY: True}}
        app._auto_start = True
        app._auto_start_run_id = "run"
        _write_spec(wd, "a", "impl")
        assert auto_start.hold_spec_if_due(app, store.get_pr(app._data, "a"))
        app._load_state()
        assert "awaiting approval" in app.logs[-1]
        spec_gen.approve_spec(store.load(root), "a", root=root)
        app._load_state()
        assert app.logs[-1] == "Auto-start: a spec approved — continuing"

    def test_explicit_review_spec_pr_gated_without_option(self, tmp_path):
        app = _app([_pr("a", review_spec=True), _pr("x", review_spec=True)],
                   tmp_path, {"a": {}})
        assert auto_start.spec_review_required(app, "a")
        assert not auto_start.spec_review_required(app, "x")  # out of scope


class TestNoRewind:
    def _hold(self, tmp_path, pr, **kw):
        wd = tmp_path / "w"
        pr["workdir"] = str(wd)
        root = _disk(tmp_path, [pr])
        _write_spec(wd, pr["id"], "impl")
        _write_spec(wd, pr["id"], "qa")
        app = DiskApp(root)
        app._auto_start_targets = {pr["id"]: {REVIEW_KEY: True}}
        app._auto_start = True
        for k, v in kw.items():
            setattr(app, k, v)
        auto_start.sync_spec_reviews(app)
        return store.get_pr(store.load(root), pr["id"]).get("spec_pending")

    def test_in_review_not_held(self, tmp_path):
        assert self._hold(tmp_path, _pr("a", status="in_review")) is None

    def test_qa_past_planning_not_held(self, tmp_path):
        loop = qa_loop.QALoopState(pr_id="a", running=True)
        loop.planning_phase = False
        assert self._hold(tmp_path, _pr("a", status="qa"),
                          _qa_loops={"a": loop}) is None

    def test_qa_with_recorded_pass_not_held(self, tmp_path):
        with patch.object(auto_start, "recorded_qa_verdict",
                          return_value="PASS"):
            assert self._hold(tmp_path, _pr("a", status="qa")) is None

    def test_qa_before_run_held(self, tmp_path):
        assert self._hold(tmp_path, _pr("a", status="qa"))["phase"] == "qa"

    def test_approved_spec_not_held_again(self, tmp_path):
        pr = _pr("a", status="in_progress",
                 spec_approved={"impl": "2026-10-21"})
        assert self._hold(tmp_path, pr) is None

    def test_default_autostart_never_holds(self, tmp_path):
        wd = tmp_path / "w"
        root = _disk(tmp_path, [_pr("a", workdir=str(wd))])
        _write_spec(wd, "a", "impl")
        app = DiskApp(root)
        app._auto_start_targets = {"a": {}}
        app._auto_start = True
        auto_start.sync_spec_reviews(app)
        assert "spec_pending" not in store.get_pr(store.load(root), "a")

    def test_scheduler_skips_any_pending_spec(self, tmp_path):
        # pm pr start refuses whatever phase is pending, so the scheduler
        # must not try (and log an error) on every pass.
        pr = _pr("a", spec_pending={"phase": "qa", "generated_at": "x"})
        root = _disk(tmp_path, [pr])
        app = DiskApp(root)
        app._auto_start_targets = {"a": {}}
        app._auto_start = True
        with patch.object(auto_start, "_start_pr_quiet") as start, \
             patch.object(auto_start, "_auto_start_review_loops"), \
             patch.object(auto_start, "_auto_start_qa_loops"), \
             patch.object(signoff_ui, "advance_all"):
            asyncio.run(auto_start.check_and_start(app))
        start.assert_not_called()


# ---------------------------------------------------------------------------
# QA scenario-launch gate
# ---------------------------------------------------------------------------

class TestQASpecGate:
    def test_gate_marks_and_waits_for_approval(self, tmp_path):
        wd = tmp_path / "w"
        root = _disk(tmp_path, [_pr("a", status="qa", workdir=str(wd))])
        state = qa_loop.QALoopState(pr_id="a", spec_review=True)
        assert not qa_loop._qa_spec_gate(state, root)  # no spec yet
        _write_spec(wd, "a", "qa")
        assert qa_loop._qa_spec_gate(state, root)
        assert store.get_pr(store.load(root), "a")["spec_pending"]["phase"] == "qa"

        updates: list[str] = []
        sleeps = {"n": 0}

        def fake_sleep(_s):
            sleeps["n"] += 1
            if sleeps["n"] == 2:  # human approves during the wait
                spec_gen.approve_spec(store.load(root), "a", root=root)

        with patch("pm_core.qa_loop.time.sleep", fake_sleep):
            assert qa_loop._wait_for_qa_spec_approval(
                state, root, lambda: updates.append(state.latest_output))
        assert not state.spec_review_pending
        assert updates[0].startswith("QA spec awaiting approval")
        assert updates[-1] == "QA spec approved — continuing QA"

    def test_pending_blocks_even_without_option(self, tmp_path):
        """Removing the option mid-run never releases a waiting spec."""
        root = _disk(tmp_path, [_pr("a", status="qa",
                                    spec_pending={"phase": "qa"})])
        state = qa_loop.QALoopState(pr_id="a", spec_review=False)
        assert qa_loop._qa_spec_gate(state, root)

    def test_wait_stops_on_stop_request(self, tmp_path):
        root = _disk(tmp_path, [_pr("a", status="qa",
                                    spec_pending={"phase": "qa"})])
        state = qa_loop.QALoopState(pr_id="a", stop_requested=True)
        with patch("pm_core.qa_loop.time.sleep"):
            assert not qa_loop._wait_for_qa_spec_approval(state, root,
                                                          lambda: None)


# ---------------------------------------------------------------------------
# Tree marker + PR Actions picker
# ---------------------------------------------------------------------------

def test_picker_badges_waiting_step():
    from pm_core.cli.session import _build_picker_lines
    for phase, row in (("impl", "start"), ("qa", "qa")):
        prs = [{"id": "pr-1", "title": "T", "status": "in_progress",
                "gh_pr_number": 5, "spec_pending": {"phase": phase}}]
        with patch("pm_core.cli.session._format_action_status",
                   return_value=""):
            lines = [d for d, _, _ in _build_picker_lines(prs, "#5")]
        badged = [_row_label(d) for d in lines[1:] if "[spec review]" in d]
        assert badged == [row]


def test_picker_navigates_windowless_spec_pause():
    """An autostart impl-spec pause holds the PR before any window
    exists; the picker opened from the TUI window still reaches it."""
    from pm_core.cli.session import _picker_nav_pr_ids
    prs = [{"id": "pr-1", "title": "T", "status": "pending",
            "spec_pending": {"phase": "impl"}},
           {"id": "pr-2", "title": "U", "status": "pending"},
           {"id": "pr-3", "title": "W", "status": "in_progress"}]
    assert _picker_nav_pr_ids(prs, {"main", "pr-3"}, None) == ["pr-1", "pr-3"]
    assert _picker_nav_pr_ids(prs[1:2], {"main"}, None) == []


def test_tree_marker_names_phase_and_outranks_loop_marker():
    from tests.test_tech_tree_widgets import _TreeApp
    from pm_core.tui.tech_tree import PRNode
    from pm_core.review_loop import ReviewLoopState

    prs = [{"id": "pr-a", "title": "t", "status": "in_progress",
            "depends_on": [], "spec_pending": {"phase": "impl"}},
           {"id": "pr-b", "title": "t", "status": "qa", "depends_on": [],
            "workdir": "/w", "spec_pending": {"phase": "qa"}}]

    async def body():
        app = _TreeApp(prs)
        app._review_loops = {"pr-b": ReviewLoopState(pr_id="pr-b",
                                                     running=True)}
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            text = {n.pr_id: n.render().plain for n in app.query(PRNode)}
            assert "in_progress S impl" in text["pr-a"]
            assert "qa S qa" in text["pr-b"]
            assert "⟳" not in text["pr-b"]

    asyncio.run(body())


# ---------------------------------------------------------------------------
# End to end: a ← b chain through CLI, scheduler, restart and approvals
# ---------------------------------------------------------------------------

class _Proc:
    returncode = 0

    async def communicate(self):
        return b"", b""


def test_chain_pauses_at_both_spec_steps_end_to_end(tmp_path):
    """``pm autostart add b --review-specs --wait-for-merge`` over a ← b.

    a: starts, writes its impl spec inline → held; idle polling and a merge
    restart keep it paused; approval resumes the agent and the review
    transition.  Its QA planner writes the QA spec → scenario launch waits
    until approval.  b already has an unapproved impl spec: once a is
    manually merged (wait-for-merge hold) b does not start until approved.
    CLI status agrees with the TUI status throughout.
    """
    root = _disk(tmp_path, [_pr("a"), _pr("b", deps=["a"])])
    home = tmp_path / "home"
    home.mkdir()
    wa = tmp_path / "wa"
    # b's spec predates the option (e.g. `pm pr spec b impl`): unapproved.
    pre = root / "specs" / "b" / "impl.md"
    pre.parent.mkdir(parents=True)
    pre.write_text("# b impl spec")

    app = DiskApp(root)
    app._session_name = "s"
    tracker = MagicMock()
    tracker.is_tracked.return_value = True
    tracker.is_gone.return_value = False
    tracker.became_idle.return_value = True
    tracker.tracked_keys.return_value = []
    app._pane_idle_tracker = tracker
    launches: list[list[str]] = []  # every `pm pr start` invocation
    started: list[str] = []  # the ones that actually started a PR

    async def fake_shell(cmd, **kw):
        launches.append(list(cmd))
        pr_id = cmd[-1]
        # In-progress PRs are re-"ensured" (a no-op with a live window).
        if store.get_pr(store.load(root), pr_id)["status"] == "pending":
            started.append(pr_id)
            _set(root, pr_id, status="in_progress",
                 workdir=str(tmp_path / f"w{pr_id}"))
        return _Proc()

    pidfile = tmp_path / "tui.pid"
    pidfile.write_text(str(os.getpid()))
    notified: list[tuple] = []

    def fake_trigger(session, cmd):
        with patch("pm_core.tui.auto_start.pm_home", return_value=home):
            auto_start.handle_command(app, shlex.split(cmd)[1:])
        return True

    def cli_status():
        out = CliRunner().invoke(cli, ["autostart", "status", "--json",
                                       "-s", "pm-x"]).output
        return {r["pr_id"]: r for r in json.loads(out)["runs"]}

    def approve(pr_id):
        with patch("pm_core.cli.pr.state_root", lambda: root), \
             patch("click.edit", return_value=None), \
             patch("pm_core.spec_gen.notify_spec_approved",
                   side_effect=lambda pr, ph, edited=False: notified.append(
                       (pr["id"], ph, edited)) or True), \
             patch("pm_core.cli.pr.trigger_tui_refresh",
                   lambda: app._load_state()):
            res = CliRunner().invoke(cli, ["pr", "spec-approve", pr_id])
        assert res.exit_code == 0, res.output
        app.drain()

    def poll_idle():
        with patch("pm_core.tui.review_loop_ui._find_impl_pane",
                   return_value="%1"):
            review_loop_ui._poll_impl_idle(app)

    from pm_core.cli import cli
    with patch.object(auto_start, "_run_shell_async", fake_shell), \
         patch("pm_core.store.find_project_root", return_value=root), \
         patch("pm_core.signoff.head_sha", return_value="head"), \
         patch.object(signoff_ui, "_adopt_orphaned_run"), \
         patch.object(review_loop_ui, "_attempt_merge"), \
         patch.object(review_loop_ui, "_auto_review_idle_prs") as to_review, \
         patch("pm_core.tui.review_loop_ui._start_loop"), \
         patch("pm_core.tui.qa_loop_ui.start_qa") as start_qa, \
         patch("pm_core.cli.autostart.state_root", lambda: root), \
         patch("pm_core.cli.autostart.pm_home", lambda: home), \
         patch("pm_core.cli.autostart._tui_pidfile_for_session",
               return_value=pidfile), \
         patch("pm_core.cli.autostart.trigger_tui_command", fake_trigger):
        res = CliRunner().invoke(cli, ["autostart", "add", "b",
                                       "--review-specs", "--wait-for-merge",
                                       "-s", "pm-x"])
        assert res.exit_code == 0, res.output
        assert "added: b (wait-for-merge; review-specs)" in res.output
        listing = CliRunner().invoke(cli, ["autostart", "list", "--json",
                                           "-s", "pm-x"]).output
        assert json.loads(listing)["targets"][0]["review_specs"] is True
        app.drain()

        # a starts with the review-mode prompt; b is blocked on a.
        assert "--review-spec" in launches[-1]
        assert started == ["a"]

        # The impl session writes its spec inline and goes idle asking for
        # approval: held, never taken for finished implementation.
        _write_spec(wa, "a", "impl")
        app._load_state()
        poll_idle()
        assert store.get_pr(store.load(root), "a")["spec_pending"]["phase"] == "impl"
        tracker.mark_active.assert_called_with("a")
        poll_idle()  # idle polling keeps it paused
        to_review.assert_not_called()
        runs = cli_status()
        assert runs["a"]["spec_review"]["phase"] == "impl"
        assert runs["a"]["spec_review"]["path"].endswith("pm/specs/a/impl.md")
        assert runs["a"]["spec_review"]["approve"] == "pm pr spec-approve a"
        assert runs["a"]["held_by"] == ["b"]  # merge hold coexists
        tui = {r["pr_id"]: r for r in auto_start.build_status(app)["runs"]}
        assert tui["a"]["reason"] == runs["a"]["reason"]
        text = CliRunner().invoke(cli, ["autostart", "status",
                                        "-s", "pm-x"]).output
        assert "wait-for-merge ← b; review-specs ← b; spec review: impl" in text

        # Merge restart: the option and the pause survive; nothing relaunches.
        app._watcher_manager.is_any_running.return_value = False
        with patch("pm_core.tui.auto_start.pm_home", return_value=home):
            (home / "merge-restart").touch()
            auto_start.save_breadcrumb(app)
            restarted = DiskApp(root)
            restarted._session_name = "s"
            restarted._pane_idle_tracker = tracker
            asyncio.run(auto_start.consume_breadcrumb(restarted))
        app = restarted
        assert app._auto_start_targets["b"][REVIEW_KEY] is True
        assert started == ["a"]
        assert len(launches) == 1  # pending impl spec: window not re-ensured
        poll_idle()
        to_review.assert_not_called()

        # Explicit approval resumes the agent; the next idle reviews.
        approve("a")
        assert notified == [("a", "impl", False)]
        poll_idle()
        assert to_review.call_args.args[1][0][0] == "a"

        # QA: the planner writes the QA spec; scenario launch is held.
        _set(root, "a", status="qa")
        app._load_state()
        auto_start._auto_start_qa_loops(app)
        start_qa.assert_called_once()
        state = qa_loop.QALoopState(pr_id="a", running=True,
                                    spec_review=auto_start.spec_review_required(app, "a"))
        app._qa_loops["a"] = state
        _write_spec(wa, "a", "qa")
        assert qa_loop._qa_spec_gate(state, root)
        app._load_state()
        assert cli_status()["a"]["reason"].startswith("QA spec awaiting approval")
        from pm_core.cli.session import _build_picker_lines
        with patch("pm_core.cli.session._format_action_status",
                   return_value=""):
            rows = _build_picker_lines(app._data["prs"], "a")
        assert [_row_label(r[0]) for r in rows[1:]
                if "[spec review]" in r[0]] == ["qa"]
        assert qa_loop._qa_spec_gate(state, root)  # idle: still held
        approve("a")
        assert notified[-1] == ("a", "qa", False)
        assert not qa_loop._qa_spec_gate(state, root)

        # a signs off, waits for the manual merge, which unblocks b — but
        # b's already-present spec has not been approved: b waits.
        del app._qa_loops["a"]
        _set(root, "a", status="sign_off", signoff=dict(_SIGNED))
        app._load_state()
        app.queue.append(auto_start.check_and_start(app))
        app.drain()
        review_loop_ui._attempt_merge.assert_not_called()
        _set(root, "a", status="merged")
        app._load_state()
        app.drain()
        assert started == ["a"]
        b = store.get_pr(store.load(root), "b")
        assert b["spec_pending"]["phase"] == "impl"
        assert cli_status()["b"]["reason"].startswith("impl spec awaiting approval")
        approve("b")  # the approval itself starts b
        assert started == ["a", "b"]
        assert "--review-spec" in launches[-1]


# ---------------------------------------------------------------------------
# QA planner poll: a plan read while the QA spec awaits approval is deferred
# ---------------------------------------------------------------------------

def _plan_under_review(tmp_path, monkeypatch, *, edit_on_approval: bool):
    from tests import test_qa_planner_handoff as h

    flags = {"approved": False, "calls": 0}
    pending_seen: list[bool] = []
    real_set = qa_loop._set_spec_review_pending

    def gate(state, pm_root):
        return not flags["approved"]

    def spec_text(pr_id, pm_root):
        return "edited" if (flags["approved"] and edit_on_approval) else "v1"

    def wait(session_id, **kw):
        flags["calls"] += 1
        if flags["calls"] > 6:
            raise AssertionError("planner poll never finished")
        if flags["calls"] == 2:  # the human approves during the wait
            flags["approved"] = True
            return None
        return {"event_type": "idle_prompt", "timestamp": time.time()}

    def record(state, pending, notify):
        if state.spec_review_pending != pending:  # transitions only
            pending_seen.append(pending)
        real_set(state, pending, notify)

    state = h._run_planning(
        tmp_path, monkeypatch, pane_content="",
        transcript_turns=[("user", h.TEMPLATE_PROMPT),
                          ("assistant", h.FULL_PLAN)],
        extra_patches=(
            patch("pm_core.qa_loop._qa_spec_gate", side_effect=gate),
            patch("pm_core.qa_loop._qa_spec_text", side_effect=spec_text),
            patch("pm_core.qa_loop._set_spec_review_pending",
                  side_effect=record),
            patch("pm_core.hook_events.wait_for_event", side_effect=wait),
        ))
    return state, flags, pending_seen


def test_planner_plan_deferred_until_approval(tmp_path, monkeypatch):
    state, flags, pending = _plan_under_review(tmp_path, monkeypatch,
                                               edit_on_approval=False)
    assert pending == [True, False]
    # Approved unchanged: the deferred plan is consumed without a new idle.
    assert flags["calls"] == 2
    assert [s.index for s in state.scenarios] == [1, 2, 3, 4]


def test_planner_replans_after_edited_approval(tmp_path, monkeypatch):
    state, flags, pending = _plan_under_review(tmp_path, monkeypatch,
                                               edit_on_approval=True)
    assert pending == [True, False]
    # The edited spec discards the deferred plan: the next idle's (re-
    # emitted) plan is the one accepted.
    assert flags["calls"] == 3
    assert [s.index for s in state.scenarios] == [1, 2, 3, 4]
