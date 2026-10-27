"""Fail-closed autostart: no wildcard/all-PR authority from any saved state.

Regression coverage for pr-049649a (incident 2026-10-27 18:52 UTC): a
breadcrumb whose ``targets`` was a mapping instead of a list fell through to
legacy targetless migration and became ``all_mode`` — wildcard authority that
started unrelated PRs and dropped per-target merge holds.

These tests use isolated fake apps, fake launches and fake merge callbacks;
nothing here starts or merges against a live PM project.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core import autostart_state as st
from pm_core.tui import auto_start


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pr(pid, status="pending", deps=None, **extra):
    d = {"id": pid, "title": f"T {pid}", "branch": f"b-{pid}",
         "status": status, "depends_on": deps or [], "notes": []}
    d.update(extra)
    return d


class FakeApp:
    """Plain object; no Textual app, no real tmux, no real scheduler."""

    def __init__(self, prs, root):
        self._data = {"project": {"name": "t", "repo": "/r",
                                  "base_branch": "master"}, "prs": prs}
        self._root = root
        self._auto_start = False
        self._auto_start_targets = {}
        self._auto_start_run_id = None
        self._auto_start_launching = set()
        self._stop_before_merge = set()
        self._review_loops = {}
        self._qa_loops = {}
        self._self_driving_qa = {}
        self._pending_merge_prs = set()
        self._merge_input_required_prs = set()
        self._session_name = None
        self._watcher_manager = MagicMock()
        self._watcher_manager.find_by_type.return_value = None
        self._watcher_manager.is_any_running.return_value = False
        self._pane_idle_tracker = MagicMock()
        self._pane_idle_tracker.is_tracked.return_value = False
        self.logs: list[str] = []
        self.launched: list[str] = []
        self.workers: list = []

    def log_message(self, msg, **kw):
        self.logs.append(msg)

    def _update_display(self):
        pass

    def _load_state(self):
        pass

    def run_worker(self, coro, *a, **kw):
        self.workers.append(coro)
        if asyncio.iscoroutine(coro):
            coro.close()


def _write_breadcrumb(root: Path, payload) -> Path:
    path = root / "autostart-resume.json"
    if isinstance(payload, str):
        path.write_text(payload)
    else:
        path.write_text(json.dumps(payload))
    return path


def _consume(app, root, *, start=None, check_and_start=True):
    """Run consume_breadcrumb with all external effects faked.

    Returns the launch recorder (defaults to ``app.launched``).
    """
    launched = start if start is not None else app.launched

    async def fake_start(a, pr_id, fresh=False):
        launched.append(pr_id)

    patches = [
        patch("pm_core.tui.auto_start.pm_home", return_value=root),
        patch.object(auto_start, "_adopt_live_qa"),
        patch.object(auto_start, "_start_pr_quiet", fake_start),
        patch("pm_core.tui.signoff_ui.advance_all"),
    ]
    if not check_and_start:
        cas = MagicMock()
        app._fake_check_and_start = cas
        patches.append(patch.object(auto_start, "check_and_start", cas))
    for p in patches:
        p.start()
    try:
        asyncio.run(auto_start.consume_breadcrumb(app))
    finally:
        for p in patches:
            p.stop()
    return launched


def _rejected_files(root: Path) -> list[Path]:
    return sorted(root.glob("autostart-resume.rejected-*.json"))


# ---------------------------------------------------------------------------
# Parser: fail closed, never wildcard
# ---------------------------------------------------------------------------

class TestBreadcrumbParserFailClosed:
    def test_incident_targets_mapping_is_rejected_not_all_mode(self):
        result = st.targets_from_breadcrumb({
            "auto_start": True,
            "all_mode": False,
            "targets": {"pr-a": {"source": "legacy-breadcrumb"}},
            "run_id": "incident",
        })
        assert result.targets == {}
        assert result.migrated is False
        assert result.error and "targets" in result.error

    @pytest.mark.parametrize("bad", ["pr-a", None, 7, True, {"pr-a": {}}])
    def test_targets_wrong_type_rejected(self, bad):
        result = st.targets_from_breadcrumb(
            {"auto_start": True, "targets": bad})
        assert result.targets == {} and result.error

    @pytest.mark.parametrize("bad_entry", [
        {},
        {"pr_id": ""},
        {"pr_id": 3},
        {"pr_id": "pr-a", "wait_for_merge": "yes"},
        {"pr_id": "pr-a", "added_at": 5},
        {"pr_id": "pr-a", "source": []},
        ["pr-a"],
        3,
    ])
    def test_malformed_target_record_rejects_whole_set(self, bad_entry):
        result = st.targets_from_breadcrumb({
            "auto_start": True,
            "targets": [{"pr_id": "pr-ok"}, bad_entry],
        })
        assert result.targets == {}, "a partial restore could widen authority"
        assert result.error

    def test_empty_targets_with_auto_start_request_is_rejected(self):
        result = st.targets_from_breadcrumb(
            {"auto_start": True, "targets": [], "run_id": "r"})
        assert result.targets == {} and result.error

    def test_empty_targets_without_request_is_off_not_error(self):
        result = st.targets_from_breadcrumb({"targets": []})
        assert result.targets == {} and result.error is None

    def test_all_mode_true_rejected_even_with_valid_targets(self):
        result = st.targets_from_breadcrumb({
            "auto_start": True, "all_mode": True,
            "targets": [{"pr_id": "pr-a"}],
        })
        assert result.targets == {}
        assert result.error and "all-mode" in result.error

    def test_legacy_targetless_auto_start_rejected(self):
        result = st.targets_from_breadcrumb(
            {"auto_start": True, "target": None, "run_id": "r"})
        assert result.targets == {} and result.error

    def test_legacy_run_id_without_target_rejected(self):
        result = st.targets_from_breadcrumb({"run_id": "r"})
        assert result.targets == {} and result.error

    def test_legacy_target_wrong_type_rejected(self):
        result = st.targets_from_breadcrumb(
            {"auto_start": True, "target": {"pr_id": "pr-a"}})
        assert result.targets == {} and result.error

    def test_legacy_single_target_migrates_exactly_one(self):
        result = st.targets_from_breadcrumb(
            {"auto_start": True, "target": "pr-a", "run_id": "r"})
        assert list(result.targets) == ["pr-a"]
        assert result.migrated is True and result.error is None

    def test_old_save_with_all_mode_false_is_accepted(self):
        """Breadcrumbs written by the previous release always carried
        ``all_mode: false``; that is still a valid explicit-target state."""
        result = st.targets_from_breadcrumb({
            "auto_start": True, "all_mode": False,
            "targets": [{"pr_id": "pr-a"}]})
        assert list(result.targets) == ["pr-a"] and result.error is None

    def test_valid_multi_target_roundtrip_preserves_records(self):
        targets = {"pr-a": st.make_target_record("key:O"),
                   "pr-b": {**st.make_target_record("cli"),
                            st.WAIT_KEY: True}}
        result = st.targets_from_breadcrumb({
            "auto_start": True,
            "targets": st.targets_to_breadcrumb(targets),
            "run_id": "r",
        })
        assert list(result.targets) == ["pr-a", "pr-b"]
        assert result.targets["pr-b"][st.WAIT_KEY] is True
        assert result.error is None and result.migrated is False

    def test_no_autostart_data_is_off_without_error(self):
        result = st.targets_from_breadcrumb({"review_loops": {}})
        assert result.targets == {} and result.error is None

    def test_wrong_typed_auto_start_rejected(self):
        result = st.targets_from_breadcrumb(
            {"auto_start": "false", "target": "pr-a"})
        assert result.targets == {} and result.error

    def test_explicit_auto_start_false_does_not_restore(self):
        result = st.targets_from_breadcrumb(
            {"auto_start": False, "target": "pr-a", "run_id": "r"})
        assert result.targets == {} and result.error is None


# ---------------------------------------------------------------------------
# consume_breadcrumb: remain OFF, diagnose, preserve evidence
# ---------------------------------------------------------------------------

class TestConsumeFailClosed:
    def test_incident_shape_never_enables_or_starts_unrelated(self, tmp_path):
        prs = [_pr("pr-a"), _pr("pr-unrelated")]
        app = FakeApp(prs, tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True, "all_mode": False,
            "targets": {"pr-a": {"wait_for_merge": True}},
            "run_id": "incident",
        })
        launched = _consume(app, tmp_path, check_and_start=False)
        app._fake_check_and_start.assert_not_called()
        assert app._auto_start is False
        assert auto_start.get_targets(app) == []
        assert auto_start.managed_ids(app) == set()
        assert auto_start.in_scope(app, "pr-unrelated") is False
        assert launched == []
        assert any("remains off" in m for m in app.logs)
        # Evidence is preserved, not silently deleted.
        assert not (tmp_path / "autostart-resume.json").exists()
        rejected = _rejected_files(tmp_path)
        assert len(rejected) == 1
        # Original bytes preserved verbatim for incident analysis.
        preserved = json.loads(rejected[0].read_text())
        assert preserved["targets"] == {"pr-a": {"wait_for_merge": True}}

    def test_corrupt_json_remains_off_and_quarantined(self, tmp_path):
        app = FakeApp([_pr("pr-a")], tmp_path)
        _write_breadcrumb(tmp_path, '{"auto_start": true, "targets": [')
        _consume(app, tmp_path)
        assert app._auto_start is False and app.launched == []
        assert _rejected_files(tmp_path)
        assert any("unreadable" in m.lower() or "remains off" in m
                   for m in app.logs)

    def test_valid_json_non_object_remains_off(self, tmp_path):
        app = FakeApp([_pr("pr-a")], tmp_path)
        _write_breadcrumb(tmp_path, '["pr-a"]')
        _consume(app, tmp_path)
        assert app._auto_start is False and app.launched == []
        assert _rejected_files(tmp_path)

    def test_all_mode_true_never_restores_targets(self, tmp_path):
        app = FakeApp([_pr("pr-a"), _pr("pr-b")], tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True, "all_mode": True,
            "targets": [{"pr_id": "pr-a"}], "run_id": "r",
        })
        _consume(app, tmp_path)
        assert app._auto_start is False
        assert auto_start.get_targets(app) == []
        assert app.launched == []
        assert any("all-mode" in m for m in app.logs)

    def test_legacy_targetless_never_becomes_all_mode(self, tmp_path):
        app = FakeApp([_pr("pr-a")], tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True, "target": None, "run_id": "legacy"})
        _consume(app, tmp_path)
        assert app._auto_start is False
        assert auto_start.managed_ids(app) == set()
        assert app.launched == []

    def test_legacy_single_target_migrates_exactly_and_schedules(self, tmp_path):
        prs = [_pr("pr-a"), _pr("pr-unrelated")]
        app = FakeApp(prs, tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True, "target": "pr-a", "run_id": "old"})
        _consume(app, tmp_path)
        assert auto_start.get_targets(app) == ["pr-a"]
        assert app.launched == ["pr-a"]
        assert "pr-unrelated" not in app.launched
        assert any("migrated legacy" in m for m in app.logs)

    def test_legacy_unknown_target_not_migrated(self, tmp_path):
        app = FakeApp([_pr("pr-a")], tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True, "target": "pr-gone", "run_id": "old"})
        _consume(app, tmp_path)
        assert app._auto_start is False
        assert auto_start.get_targets(app) == []
        assert app.launched == []
        assert any("not found" in m for m in app.logs)

    def test_valid_multi_target_restore_only_runs_closure(self, tmp_path):
        prs = [_pr("pr-dep", status="merged"), _pr("pr-a", deps=["pr-dep"]),
               _pr("pr-b"), _pr("pr-unrelated")]
        app = FakeApp(prs, tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True,
            "targets": [{"pr_id": "pr-a"}, {"pr_id": "pr-b"}],
            "run_id": "r",
        })
        _consume(app, tmp_path)
        assert auto_start.get_targets(app) == ["pr-a", "pr-b"]
        assert set(app.launched) == {"pr-a", "pr-b"}
        assert "pr-unrelated" not in app.launched

    def test_unmerged_dependency_launched_before_target(self, tmp_path):
        prs = [_pr("pr-dep"), _pr("pr-target", deps=["pr-dep"]),
               _pr("pr-unrelated")]
        app = FakeApp(prs, tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True,
            "targets": [{"pr_id": "pr-target"}],
            "run_id": "r",
        })
        _consume(app, tmp_path)
        assert set(app.launched) == {"pr-dep"}
        assert "pr-unrelated" not in app.launched

    def test_malformed_stop_marks_keep_autostart_off(self, tmp_path):
        """A malformed merge-gate set must not be silently dropped while
        autostart resumes and auto-merges without holds."""
        app = FakeApp([_pr("pr-a")], tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True,
            "targets": [{"pr_id": "pr-a"}],
            "stop_before_merge": {"pr-a": "yes"},
        })
        _consume(app, tmp_path)
        assert app._auto_start is False
        assert app.launched == []
        assert any("stop_before_merge" in m for m in app.logs)


class TestSaveNeverPersistsWildcard:
    def test_save_writes_targets_only(self, tmp_path):
        app = FakeApp([_pr("pr-a")], tmp_path)
        app._auto_start = True
        app._auto_start_targets = {"pr-a": st.make_target_record("test")}
        app._auto_start_run_id = "run"
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
            (tmp_path / "merge-restart").touch()
            auto_start.save_breadcrumb(app)
        data = json.loads((tmp_path / "autostart-resume.json").read_text())
        assert "all_mode" not in data
        assert [t["pr_id"] for t in data["targets"]] == ["pr-a"]


# ---------------------------------------------------------------------------
# Merge holds survive a restart
# ---------------------------------------------------------------------------

class TestRestoredMergeHolds:
    def _signed(self, pid, deps=None):
        return _pr(pid, status="sign_off", deps=deps,
                   workdir=None,
                   signoff={"verdict": "SIGNOFF_MERGE", "sha": "abc"})

    def test_wait_for_merge_target_holds_signed_off_dep(self, tmp_path):
        from pm_core.tui import review_loop_ui

        prs = [self._signed("pr-dep"), _pr("pr-final", deps=["pr-dep"])]
        app = FakeApp(prs, tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True,
            "targets": [{"pr_id": "pr-final", "wait_for_merge": True},
                        {"pr_id": "pr-dep"}],
            "run_id": "r",
        })
        _consume(app, tmp_path)
        assert app._auto_start is True
        # The restored record kept the wait flag (manual merge gate).
        assert app._auto_start_targets["pr-final"][st.WAIT_KEY] is True
        assert auto_start.merge_hold(app, "pr-dep") is not None

        with patch.object(review_loop_ui, "_signoff_gate",
                          return_value=("abc", None, prs[0])), \
             patch.object(review_loop_ui, "_attempt_merge") as merge:
            review_loop_ui._maybe_auto_merge(app, "pr-dep")
        merge.assert_not_called()

        # Removing the wait target releases exactly its hold.
        auto_start.remove_targets(app, ["pr-final"])
        with patch.object(review_loop_ui, "_signoff_gate",
                          return_value=("abc", None, prs[0])), \
             patch.object(review_loop_ui, "_attempt_merge",
                          return_value=True) as merge:
            review_loop_ui._maybe_auto_merge(app, "pr-dep")
        merge.assert_called_once()

    def test_unrelated_signed_off_pr_never_merges(self, tmp_path):
        from pm_core.tui import review_loop_ui

        prs = [self._signed("pr-a"), self._signed("pr-unrelated")]
        app = FakeApp(prs, tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True,
            "targets": [{"pr_id": "pr-a", "wait_for_merge": True}],
            "run_id": "r",
        })
        _consume(app, tmp_path)
        with patch.object(review_loop_ui, "_signoff_gate",
                          return_value=("abc", None, prs[1])), \
             patch.object(review_loop_ui, "_attempt_merge") as merge:
            review_loop_ui._maybe_auto_merge(app, "pr-unrelated")
        merge.assert_not_called()


# ---------------------------------------------------------------------------
# Command / IPC rejection
# ---------------------------------------------------------------------------

class TestAllModeCommandRejected:
    def test_command_bar_all_is_rejected(self):
        app = FakeApp([_pr("pr-a")], Path("/tmp"))
        result = auto_start.handle_command(app, ["all"])
        assert result["ok"] is False
        assert result["error"] == "all_mode_removed"
        assert "add" in result["message"]
        assert app._auto_start is False
        assert auto_start.get_targets(app) == []
        assert app.workers == []

    def test_usage_does_not_advertise_all(self):
        assert "all" not in auto_start.USAGE.split("|")

    def test_status_mode_is_never_all(self):
        s = st.build_status({"prs": [_pr("pr-a")], "targets": {},
                             "enabled": True, "all_mode": True})
        assert s["mode"] == "off" and s["targets"] == [] and s["runs"] == []

    def test_cli_all_subcommand_is_not_offered(self):
        from click.testing import CliRunner
        from pm_core.cli import cli
        res = CliRunner().invoke(cli, ["autostart", "all"])
        assert res.exit_code != 0
        assert "No such command" in res.output

    def test_status_label_never_says_all(self):
        from types import SimpleNamespace
        from pm_core.tui.app import ProjectManagerApp
        app = SimpleNamespace(_auto_start=True, _auto_start_targets={})
        assert ProjectManagerApp._auto_start_label(app) == ""

    def test_managed_ids_never_returns_none(self):
        app = FakeApp([_pr("pr-a")], Path("/tmp"))
        app._auto_start = True
        app._auto_start_targets = {}
        assert auto_start.managed_ids(app) == set()
        assert auto_start.in_scope(app, "pr-a") is False


# ---------------------------------------------------------------------------
# Scheduler / reload: no targetless fallback
# ---------------------------------------------------------------------------

class TestSchedulerNoTargetlessFallback:
    def test_enabled_with_no_targets_starts_nothing(self, tmp_path):
        app = FakeApp([_pr("pr-a")], tmp_path)
        app._auto_start = True
        app._auto_start_targets = {}

        async def fake_start(a, pr_id, fresh=False):
            a.launched.append(pr_id)

        with patch.object(auto_start, "_start_pr_quiet", fake_start), \
             patch("pm_core.tui.signoff_ui.advance_all"):
            asyncio.run(auto_start.check_and_start(app))
        assert app.launched == []
        assert auto_start.managed_ids(app) == set()

    def test_reload_with_no_targets_does_not_schedule(self, tmp_path):
        app = FakeApp([_pr("pr-a", status="merged")], tmp_path)
        app._auto_start = True
        app._auto_start_targets = {}
        auto_start.on_state_loaded(app, {"pr-a": "qa"})
        assert app.workers == []


# ---------------------------------------------------------------------------
# Watcher scope: empty target set is observation-only
# ---------------------------------------------------------------------------

class TestWatcherScopeFailClosed:
    DATA = {"project": {"name": "t", "repo": "r", "base_branch": "master"},
            "prs": [_pr("pr-a"), _pr("pr-b")]}

    def test_empty_targets_are_observation_only(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        prompt = generate_watcher_prompt(self.DATA, auto_start_targets=[])
        assert "Auto-Start Scope" in prompt
        assert "no PR is managed" in prompt
        assert "Do not start" in prompt

    def test_no_scope_argument_leaves_prompt_unchanged(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        prompt = generate_watcher_prompt(self.DATA)
        assert "Auto-Start Scope" not in prompt

    def test_explicit_targets_render_managed_set(self):
        from pm_core.prompt_gen import generate_watcher_prompt
        prompt = generate_watcher_prompt(
            self.DATA, auto_start_targets=["pr-b"])
        assert "Auto-start targets: **pr-b**" in prompt
        assert "Managed PRs (targets + their transitive dependencies): pr-b" \
            in prompt
