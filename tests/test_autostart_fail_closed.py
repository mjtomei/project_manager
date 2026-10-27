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
        self.log_kwargs: list[dict] = []
        self.launched: list[str] = []
        self.workers: list = []

    def log_message(self, msg, **kw):
        self.logs.append(msg)
        self.log_kwargs.append(dict(kw))

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

    @pytest.mark.parametrize("entries", [
        ["pr-a", "pr-a"],
        ["pr-a", {"pr_id": "pr-a", "wait_for_merge": True}],
        [{"pr_id": "pr-a"}, {"pr_id": "pr-a"}],
    ])
    def test_duplicate_targets_reject_whole_set(self, entries):
        """First-wins could silently drop the other record's merge gate."""
        result = st.targets_from_breadcrumb(
            {"auto_start": True, "targets": entries})
        assert result.targets == {} and result.error
        assert "duplicate" in result.error

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

    @pytest.mark.parametrize("bad", ["yes", 1, 0, None, []])
    def test_non_boolean_all_mode_rejected(self, bad):
        """A truthy-or-ambiguous all-mode flag is never narrowed into a
        restore: the shape must be unambiguous."""
        result = st.targets_from_breadcrumb(
            {"all_mode": bad, "targets": [{"pr_id": "pr-a"}]})
        assert result.targets == {} and result.error
        assert "all_mode" in result.error

    @pytest.mark.parametrize("bad", [5, [], {}, True])
    def test_non_string_run_id_rejected(self, bad):
        result = st.targets_from_breadcrumb({"run_id": bad})
        assert result.targets == {} and result.error

    def test_auto_start_true_without_any_target_key_is_targetless(self):
        """``auto_start`` with neither ``targets`` nor ``target`` is the
        incident's legacy shape: it must never become all-mode."""
        result = st.targets_from_breadcrumb({"auto_start": True})
        assert result.targets == {} and result.error
        assert "no target" in result.error

    def test_target_null_alone_is_off_without_error(self):
        """``target: null`` with no autostart request is no saved state.

        (The pre-multi-target writer emitted ``target: null`` for all-mode,
        always alongside ``auto_start: true``/``run_id`` — that shape is
        rejected as targetless above.  On its own there is nothing to
        restore and nothing to diagnose.)"""
        result = st.targets_from_breadcrumb({"target": None})
        assert result.targets == {} and result.error is None

    def test_legacy_target_without_auto_start_still_migrates(self):
        """Older breadcrumbs implied auto-start from ``target`` alone."""
        result = st.targets_from_breadcrumb({"target": "pr-a"})
        assert list(result.targets) == ["pr-a"]
        assert result.migrated is True and result.error is None


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
        # What ``pm autostart status --json`` would report after the restore.
        status = auto_start.build_status(app)
        assert status["mode"] == "off"
        assert status["targets"] == [] and status["runs"] == []
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
        autostart resumes and auto-merges without holds.  Safe non-autostart
        state (review-loop progress) is still restored."""
        app = FakeApp([_pr("pr-a", status="qa")], tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True,
            "targets": [{"pr_id": "pr-a"}],
            "stop_before_merge": {"pr-a": "yes"},
            "review_loops": {"pr-a": {"iteration": 2, "history": []}},
        })
        _consume(app, tmp_path)
        assert app._auto_start is False
        assert app.launched == []
        assert any("stop_before_merge" in m for m in app.logs)
        # Autostart is off, so restored loop state cannot merge anything.
        assert app._review_loops["pr-a"].iteration == 2

    @pytest.mark.parametrize("marks", [
        [" pr-a"],          # padded: would never match the real id
        ["pr-a "],
        ["pr\ta"],
        ["pr-a", "pr-b", ""],
    ])
    def test_invalid_stop_mark_id_keeps_autostart_off(self, tmp_path, marks):
        """An id that cannot match a PR would silently lose its hold."""
        app = FakeApp([_pr("pr-a"), _pr("pr-b")], tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True,
            "targets": [{"pr_id": "pr-a"}, {"pr_id": "pr-b"}],
            "stop_before_merge": marks,
        })
        _consume(app, tmp_path)
        assert app._auto_start is False
        assert app._auto_start_targets == {}
        assert app.launched == []
        assert any("stop_before_merge" in m for m in app.logs)

    def test_corrupt_json_clears_pre_existing_scope(self, tmp_path):
        """A corrupt file must fail closed even if this app somehow already
        had autostart state: the rejected restore never leaves a scope live."""
        app = FakeApp([_pr("pr-a")], tmp_path)
        app._auto_start = True
        app._auto_start_targets = {"pr-a": {}}
        app._auto_start_run_id = "stale"
        _write_breadcrumb(tmp_path, "{not json")
        _consume(app, tmp_path)
        assert app._auto_start is False
        assert app._auto_start_targets == {}
        assert app._auto_start_run_id is None
        assert auto_start.managed_ids(app) == set()
        assert _rejected_files(tmp_path)

    def test_targets_without_loaded_prs_remain_off(self, tmp_path):
        """Saved targets that cannot be validated (no project PRs loaded)
        must not be restored."""
        app = FakeApp([], tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True, "targets": [{"pr_id": "pr-a"}], "run_id": "r"})
        _consume(app, tmp_path)
        assert app._auto_start is False
        assert auto_start.get_targets(app) == []
        assert app.launched == []
        assert any("no project PRs" in m for m in app.logs)
        assert _rejected_files(tmp_path)

    def test_valid_stop_marks_restored_even_when_targets_rejected(self, tmp_path):
        """A valid merge-gate set is evidence worth keeping even when the
        target parse fails (the rejected state still cannot merge)."""
        app = FakeApp([_pr("pr-a")], tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True, "all_mode": True,
            "targets": [{"pr_id": "pr-a"}],
            "stop_before_merge": ["pr-a"],
        })
        _consume(app, tmp_path)
        assert app._auto_start is False
        assert app._stop_before_merge == {"pr-a"}
        assert any("all-mode" in m for m in app.logs)

    def test_malformed_review_loop_history_does_not_abort_restore(self, tmp_path):
        """A malformed history entry must not raise out of startup; the loop
        state is restored with the entries that are well formed."""
        app = FakeApp([_pr("pr-a", status="in_review", workdir="/tmp/wd")],
                      tmp_path)
        _write_breadcrumb(tmp_path, {
            "review_loops": {"pr-a": {
                "iteration": 2,
                "history": [
                    ["not", "a", "dict"],
                    {"iteration": 1, "verdict": "PASS"},
                    {"verdict": "missing iteration"},
                ],
            }},
        })
        with patch("pm_core.tui.review_loop_ui._start_loop") as start_loop:
            _consume(app, tmp_path)
        rstate = app._review_loops["pr-a"]
        assert rstate.iteration == 2
        assert [(h.iteration, h.verdict) for h in rstate.history] == [
            (1, "PASS")]
        start_loop.assert_called_once()

    def test_rejection_diagnostic_not_replaced_by_loop_summary(self, tmp_path):
        """The actionable "auto-start remains off" line must stay on the log
        line; the informational loop-resume summary must not paint over it."""
        app = FakeApp([_pr("pr-a", status="in_review", workdir="/tmp/wd")],
                      tmp_path)
        _write_breadcrumb(tmp_path, {
            "auto_start": True, "all_mode": True,
            "targets": [{"pr_id": "pr-a"}],
            "review_loops": {"pr-a": {"iteration": 1, "history": []}},
        })
        with patch("pm_core.tui.review_loop_ui._start_loop"):
            _consume(app, tmp_path)
        assert any("remains off" in m for m in app.logs)
        summary = [kw for msg, kw in zip(app.logs, app.log_kwargs)
                   if msg == "Resumed review loop state after restart"]
        assert summary and summary[-1].get("sticky", 0) == 0


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

    def test_save_while_off_writes_no_autostart_fields(self, tmp_path):
        """Restarting with auto-start off must not persist a targetless or
        wildcard record for the next startup to interpret."""
        app = FakeApp([_pr("pr-a")], tmp_path)
        app._auto_start = False
        app._stop_before_merge = {"pr-a"}
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
            (tmp_path / "merge-restart").touch()
            auto_start.save_breadcrumb(app)
        data = json.loads((tmp_path / "autostart-resume.json").read_text())
        assert "auto_start" not in data
        assert "targets" not in data
        assert "all_mode" not in data
        assert data["stop_before_merge"] == ["pr-a"]

        fresh = FakeApp([_pr("pr-a")], tmp_path)
        _consume(fresh, tmp_path)
        assert fresh._auto_start is False
        assert fresh.launched == []
        assert "pr-a" in fresh._stop_before_merge

    def test_save_enabled_with_no_targets_writes_no_autostart_fields(self, tmp_path):
        """The impossible-through-the-API enabled/empty state must not write
        an ambiguous record either."""
        app = FakeApp([_pr("pr-a")], tmp_path)
        app._auto_start = True
        app._auto_start_targets = {}
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
            (tmp_path / "merge-restart").touch()
            auto_start.save_breadcrumb(app)
        assert not (tmp_path / "autostart-resume.json").exists()

    def test_mixed_policies_roundtrip_exactly(self, tmp_path):
        """Save→consume reproduces the same targets, order and holds."""
        prs = [_pr("pr-a"), _pr("pr-b")]
        app = FakeApp(prs, tmp_path)
        app._auto_start = True
        app._auto_start_targets = {
            "pr-b": {**st.make_target_record("key:O"), st.WAIT_KEY: True},
            "pr-a": st.make_target_record("cli"),
        }
        app._auto_start_run_id = "run"
        app._stop_before_merge = {"pr-a"}
        with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
            (tmp_path / "merge-restart").touch()
            auto_start.save_breadcrumb(app)

        fresh = FakeApp(prs, tmp_path)
        _consume(fresh, tmp_path)
        assert auto_start.get_targets(fresh) == ["pr-b", "pr-a"]
        assert fresh._auto_start_targets["pr-b"][st.WAIT_KEY] is True
        assert st.WAIT_KEY not in fresh._auto_start_targets["pr-a"]
        assert fresh._auto_start_run_id == "run"
        assert "pr-a" in fresh._stop_before_merge


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
        # ``all`` was the last verb; a bare-token check would miss it.
        assert " all" not in auto_start.USAGE

    def test_status_mode_is_never_all(self):
        s = st.build_status({"prs": [_pr("pr-a")], "targets": {},
                             "enabled": True, "all_mode": True})
        assert s["mode"] == "off" and s["targets"] == [] and s["runs"] == []

    def test_status_off_when_disabled_even_with_targets(self):
        """A stale ``enabled``/``targets`` combination cannot report an
        active scope while auto-start is off."""
        s = st.build_status({"prs": [_pr("pr-a")],
                             "targets": {"pr-a": {}}, "enabled": False})
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

    def test_auto_start_watcher_with_no_targets_is_observation_only(self):
        """The real watcher path (a TUI/resumed auto-start watcher with no
        targets) must carry the fail-closed scope block, not the general
        "fix what you can" instructions."""
        from pm_core.watchers.auto_start_watcher import AutoStartWatcher
        w = AutoStartWatcher(pm_root=str(Path("/tmp")))
        assert w.auto_start_targets == []
        with patch("pm_core.store.load", return_value=self.DATA):
            prompt = w.generate_prompt(1)
        assert "no PR is managed" in prompt
        assert "Observation and reporting only" in prompt
