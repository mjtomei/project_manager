"""A QA run that finishes while project.yaml cannot be loaded keeps its
result (RQ37, S46).

The completion writes the lifecycle transition and the QA note to
project.yaml.  Processing it during a conflicted pull, a merge whose plans do
not validate, or a checkout that has the file unlinked only logged warnings,
and the resume snapshot was cleared right after: the PR stayed in ``qa`` with
no note and nothing retried.  A TUI started on such a file died at mount
(guide.detect_state re-raised the load error).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from pm_core import store
from pm_core.qa_loop import (QALoopState, VERDICT_NEEDS_WORK, VERDICT_PASS)

PLANS = ("plans:\n- id: plan-child\n  name: c\n  file: plans/c.md\n"
         "  status: draft\n  parent: plan-base\n")


def _make_app(tmp_path):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    data = {
        "project": {"name": "t", "repo": "/tmp/r", "base_branch": "master"},
        "plans": [],
        "prs": [{"id": "pr-001", "title": "T", "branch": "b",
                 "status": "qa", "notes": []}],
    }
    store.save(data, pm_dir)
    app = MagicMock()
    app._root = pm_dir
    app._data = data
    app._qa_loops = {}
    app._review_loops = {}
    app._self_driving_qa = {}
    app._pane_idle_tracker.tracked_keys.return_value = []
    return app


def _finished_run(app, tmp_path, verdict):
    wd = tmp_path / "qa-wd"
    wd.mkdir()
    (wd / "qa_resume.json").write_text(json.dumps({"pr_id": "pr-001"}))
    state = QALoopState(pr_id="pr-001")
    state.running = False
    state.latest_verdict = verdict
    state.qa_workdir = str(wd)
    app._qa_loops["pr-001"] = state
    return state, wd / "qa_resume.json"


def _write(f, text):
    if f.exists():
        f.chmod(0o644)  # store.save leaves it read-only
    f.write_text(text)


def _break(root, how):
    f = root / "project.yaml"
    text = f.read_text()
    if how == "conflict":
        _write(f, text.replace("  status: qa\n",
                                  "<<<<<<< HEAD\n  status: qa\n=======\n"
                                  "  status: in_review\n>>>>>>> theirs\n"))
    elif how == "invalid_plans":
        _write(f, text.replace("plans: []\n", PLANS))
    else:
        f.unlink()
    return text


def _poll(app, n):
    from pm_core.tui import qa_loop_ui
    with patch("pm_core.tui.qa_loop_ui._resume_incomplete_qa"), \
         patch("pm_core.runtime_state.set_action_state") as mirror, \
         patch("pm_core.tui.auto_start.is_enabled", return_value=False), \
         patch("pm_core.tui.auto_start.in_scope", return_value=False):
        for _ in range(n):
            qa_loop_ui.poll_qa_state(app)
    return mirror


def _pr(root):
    return store.get_pr(store.load(root), "pr-001")


def _logged(app, text):
    return [c.args[0] for c in app.log_message.call_args_list
            if text in c.args[0]]


@pytest.mark.parametrize("how", ["conflict", "invalid_plans", "missing"])
def test_needs_work_waits_for_the_file_and_is_recorded_once(tmp_path, how):
    app = _make_app(tmp_path)
    _state, snap = _finished_run(app, tmp_path, VERDICT_NEEDS_WORK)
    good = _break(app._root, how)

    mirror = _poll(app, 4)

    # Nothing claimed or lost while the file cannot be loaded.
    assert "pr-001" in app._qa_loops
    assert snap.exists()
    assert not _logged(app, "returning to review")
    assert len(_logged(app, "waiting for project.yaml")) == 1
    assert not mirror.called

    _write(app._root / "project.yaml", good)
    mirror = _poll(app, 3)

    pr = _pr(app._root)
    assert pr["status"] == "in_review"
    assert len([n for n in pr["notes"] if n["text"].startswith("QA ")]) == 1
    assert len(_logged(app, "returning to review")) == 1
    assert not snap.exists()
    assert "pr-001" not in app._qa_loops
    mirror.assert_called_with("pr-001", "qa", "done",
                              verdict=VERDICT_NEEDS_WORK)


def test_self_driving_pass_restarts_qa_only_once_the_file_loads(tmp_path):
    app = _make_app(tmp_path)
    app._self_driving_qa["pr-001"] = {"pass_count": 0, "required_passes": 2}
    _finished_run(app, tmp_path, VERDICT_PASS)
    good = _break(app._root, "conflict")

    with patch("pm_core.tui.qa_loop_ui.start_qa") as start:
        _poll(app, 3)
        assert not start.called
        assert app._self_driving_qa["pr-001"]["pass_count"] == 0
        _write(app._root / "project.yaml", good)
        _poll(app, 1)
    start.assert_called_once_with(app, "pr-001")
    assert app._self_driving_qa["pr-001"]["pass_count"] == 1
    assert len(_pr(app._root)["notes"]) == 1


def test_a_note_write_that_fails_after_the_check_is_retried(tmp_path):
    """The file can break between the load check and the note write."""
    from pm_core.tui import qa_loop_ui
    app = _make_app(tmp_path)
    _state, snap = _finished_run(app, tmp_path, VERDICT_PASS)
    real = qa_loop_ui._record_qa_note
    calls = []

    def flaky(a, s):
        calls.append(1)
        if len(calls) == 1:
            with patch("pm_core.store.locked_update",
                       side_effect=store.ProjectYamlParseError("broke")):
                return real(a, s)
        return real(a, s)

    with patch("pm_core.tui.qa_loop_ui._record_qa_note", side_effect=flaky):
        _poll(app, 1)
        assert snap.exists() and "pr-001" in app._qa_loops
        assert _pr(app._root)["notes"] == []
        _poll(app, 3)
    assert len(calls) == 2
    assert len(_pr(app._root)["notes"]) == 1
    assert not snap.exists()
    assert "pr-001" not in app._qa_loops


@pytest.mark.parametrize("how", ["conflict", "invalid_plans"])
def test_tui_started_on_an_unloadable_file_mounts(tmp_path, how):
    """No previous state to keep: show the empty tree instead of the guide,
    which re-loaded the file and raised RuntimeError at mount."""
    from pm_core.tui.app import ProjectManagerApp
    app = _make_app(tmp_path)
    good = _break(app._root, how)
    app._data = {}
    app._plans_visible = app._qa_visible = False
    loads = []

    def load_state():
        loads.append(1)
        ProjectManagerApp._load_state(app)
    app._load_state = load_state

    with patch("pm_core.tui.auto_start.on_state_loaded"):
        app._load_state()

    app._show_normal_view.assert_called_once()
    assert not app._show_guide_view.called
    assert app._data == {}
    assert "cannot be loaded" in app.log_message.call_args.args[0]
    # the tree says why it is empty (not "No PRs defined")
    tree = app.query_one.return_value
    assert "cannot be loaded" in tree.update_prs.call_args.kwargs["unavailable"]

    # Unchanged file: no reload; once it loads, the project is shown.
    ProjectManagerApp._retry_failed_load(app)
    assert len(loads) == 1
    _write(app._root / "project.yaml", good)
    with patch("pm_core.tui.auto_start.on_state_loaded"):
        ProjectManagerApp._retry_failed_load(app)
    assert len(loads) == 2
    assert _pr(app._root) == store.get_pr(app._data, "pr-001")
    assert app._load_error is None
    # the sticky "cannot be loaded" line goes once the file loads
    app._clear_log_message.assert_called_once_with()


# --- the file breaks after the load check (review of a9b966ec) -------------

def _fail_first_locked_update():
    """store.locked_update raising once, as if the file broke right after
    the completion's load check."""
    real = store.locked_update
    calls = []

    def upd(root, fn, *a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise store.ProjectYamlParseError("broke after the check")
        return real(root, fn, *a, **kw)
    return patch("pm_core.store.locked_update", side_effect=upd)


def test_self_driving_needs_work_race_starts_one_review_loop(tmp_path):
    """Transition write fails after the check: nothing follows (no message,
    no review loop); the retry records the result and starts exactly one
    review loop, and the tree is repainted at in_review."""
    app = _make_app(tmp_path)
    app._self_driving_qa["pr-001"] = {"pass_count": 1, "required_passes": 2}
    _state, snap = _finished_run(app, tmp_path, VERDICT_NEEDS_WORK)
    shown = []
    app._update_display.side_effect = lambda: shown.append(
        store.get_pr(app._data, "pr-001")["status"])

    with patch("pm_core.tui.review_loop_ui._start_loop") as loop, \
         patch("pm_core.tui.auto_start.get_transcript_dir", return_value=tmp_path):
        with _fail_first_locked_update():
            _poll(app, 1)
            assert not loop.called and snap.exists()
            assert not _logged(app, "returning to review")
            assert _pr(app._root)["status"] == "qa"
            _poll(app, 3)
    loop.assert_called_once()
    pr = _pr(app._root)
    assert pr["status"] == "in_review"
    assert len(pr["notes"]) == 1
    assert len(_logged(app, "returning to review")) == 1
    assert shown and shown[-1] == "in_review"
    assert app._self_driving_qa["pr-001"]["pass_count"] == 0
    assert not snap.exists() and "pr-001" not in app._qa_loops


def test_review_start_that_hits_the_failure_is_retried_once(tmp_path):
    """Writes succeed, then the review loop start meets the unloadable file:
    it is retried (one loop), the snapshot is kept until then."""
    from pm_core.tui import qa_loop_ui
    app = _make_app(tmp_path)
    app._self_driving_qa["pr-001"] = {"pass_count": 0, "required_passes": 2}
    _state, snap = _finished_run(app, tmp_path, VERDICT_NEEDS_WORK)
    starts = []

    def review(a, pr_id):
        starts.append(pr_id)
        return False if len(starts) == 1 else None

    with patch("pm_core.tui.qa_loop_ui._start_self_driving_review",
               side_effect=review):
        _poll(app, 1)
        assert snap.exists() and "pr-001" in app._qa_loops
        _poll(app, 3)
    assert starts == ["pr-001", "pr-001"]
    assert len(_pr(app._root)["notes"]) == 1
    assert len(_logged(app, "returning to review")) == 1
    assert not snap.exists() and "pr-001" not in app._qa_loops


def test_start_self_driving_review_reports_an_unloadable_file(tmp_path):
    from pm_core.tui.qa_loop_ui import _start_self_driving_review
    app = _make_app(tmp_path)
    _break(app._root, "invalid_plans")
    with patch("pm_core.tui.review_loop_ui._start_loop") as loop:
        assert _start_self_driving_review(app, "pr-001") is False
    assert not loop.called


def test_pass_below_count_note_race_restarts_qa_once(tmp_path):
    """The note write fails after the check: no restart yet; the retry
    records one note and restarts QA once (pass 1/2)."""
    app = _make_app(tmp_path)
    app._self_driving_qa["pr-001"] = {"pass_count": 0, "required_passes": 2}
    _finished_run(app, tmp_path, VERDICT_PASS)
    with patch("pm_core.tui.qa_loop_ui.start_qa") as start:
        with _fail_first_locked_update():
            _poll(app, 1)
            assert not start.called
            _poll(app, 1)
    start.assert_called_once_with(app, "pr-001")
    assert app._self_driving_qa["pr-001"]["pass_count"] == 1
    assert len(_pr(app._root)["notes"]) == 1
    assert len(_logged(app, "restarting QA")) == 1


def test_pass_below_count_restart_that_hits_the_failure_is_retried(tmp_path):
    """start_qa meets the unloadable file (returns False): the old run keeps
    its snapshot and retries; the successful restart replaces it in
    _qa_loops, the old snapshot is dropped and the new run is left alone."""
    app = _make_app(tmp_path)
    app._self_driving_qa["pr-001"] = {"pass_count": 0, "required_passes": 2}
    _old, snap = _finished_run(app, tmp_path, VERDICT_PASS)
    new = QALoopState(pr_id="pr-001")
    new.running = True
    calls = []

    def start(a, pr_id):
        calls.append(pr_id)
        if len(calls) == 1:
            return False
        a._qa_loops[pr_id] = new
        return True

    with patch("pm_core.tui.qa_loop_ui.start_qa", side_effect=start):
        _poll(app, 1)
        assert snap.exists() and app._qa_loops["pr-001"] is _old
        _poll(app, 1)
        assert app._qa_loops["pr-001"] is new
        _poll(app, 3)
    assert calls == ["pr-001", "pr-001"]
    assert app._qa_loops["pr-001"] is new
    assert not snap.exists()
    assert app._self_driving_qa["pr-001"]["pass_count"] == 1
    assert len(_pr(app._root)["notes"]) == 1


def test_tree_names_why_it_is_empty():
    from pm_core.tui.tech_tree import TechTree
    tree = TechTree.__new__(TechTree)
    tree._prs = []
    tree._unavailable = "project.yaml cannot be loaded: x — waiting for it to load"
    assert tree._empty_message() == tree._unavailable
    tree._unavailable = None
    assert tree._empty_message().startswith("No PRs defined")
