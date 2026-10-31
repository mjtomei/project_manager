"""A review PASS reached while project.yaml cannot be loaded still hands
the PR to QA once the file loads (RQ37).

Live (S45 final story 4, af12945d): G's self-driving (zz t) review loop
passed while a merge left plans that do not validate.  _maybe_start_qa's
in_review -> qa write failed, it logged "Error: Plan plan-child references
non-existent parent 'plan-base'" and returned, and nothing retried: G sat
at in_review with its zz t loop silently gone (7+ min observed).
"""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from pm_core import store
from pm_core.review_loop import ReviewLoopState
from pm_core.tui import review_loop_ui
from tests.test_auto_start_qa import _make_app

PR = {"id": "pr-001", "title": "T", "branch": "b", "status": "in_review",
      "notes": []}


def _write(path, text):
    if path.exists():
        path.chmod(0o644)  # store.save leaves it read-only
    path.write_text(text)


def _break(pm_dir, kind):
    path = pm_dir / "project.yaml"
    good = path.read_text()
    path.chmod(0o644)
    if kind == "conflict_markers":
        path.write_text(good + "<<<<<<< HEAD\nx: 1\n=======\nx: 2\n>>>>>>> b\n")
    elif kind == "invalid_plans":
        d = yaml.safe_load(good)
        d["plans"] = [{"id": "plan-child", "name": "c", "file": "plans/c.md",
                       "status": "draft", "parent": "plan-base"}]
        path.write_text(yaml.safe_dump(d))
    else:
        path.unlink()
    return good


def _self_driving_app(tmp_path):
    app = _make_app(tmp_path, prs=[dict(PR, workdir=str(tmp_path / "wd"))],
                    auto_start=False)
    app._self_driving_qa = {"pr-001": {"pass_count": 0, "required_passes": 2}}
    return app


def _status(app):
    return store.get_pr(store.load(app._root), "pr-001")["status"]


@pytest.mark.parametrize("kind", ["conflict_markers", "invalid_plans",
                                  "missing_file"])
def test_review_pass_waits_and_starts_qa_once_the_file_loads(
        tmp_path, kind):
    app = _self_driving_app(tmp_path)
    good = _break(app._root, kind)
    # (The module logger does not propagate (configure_logger), so caplog
    # saw its records only when an earlier test had reset that: patched.)
    with patch("pm_core.tui.qa_loop_ui.start_qa") as start, \
            patch.object(review_loop_ui, "_log") as log:
        for _ in range(3):  # three poll ticks while the file is broken
            review_loop_ui._start_qa_after_review(app, "pr-001")
        warned = [c.args[0] % c.args[1:] for c in log.warning.call_args_list]
        assert len(warned) == 1, warned  # S45 live: one per tick
        start.assert_not_called()
        assert "pr-001" in app._pending_auto_qa
        waits = [c.args[0] for c in app.log_message.call_args_list
                 if "waiting for project.yaml" in c.args[0]]
        assert len(waits) == 1  # once per reason, not every tick

        _write(app._root / "project.yaml", good)
        review_loop_ui._start_qa_after_review(app, "pr-001")
    start.assert_called_once_with(
        app, "pr-001", lock_timeout=0.0)  # store.NO_WAIT: retried per tick (RQ38)
    assert _status(app) == "qa"
    assert app._pending_auto_qa == {}


def test_poll_tick_retries_a_pending_hand_off(tmp_path):
    """The one-shot "loop done" handling hands off once; the poll timer
    must retry it after the file loads (it is not newly done any more)."""
    app = _self_driving_app(tmp_path)
    app._impl_poll_counter = 1
    app._watcher_manager.is_any_running.return_value = False
    state = ReviewLoopState(pr_id="pr-001")
    state.running = False
    state.latest_verdict = "PASS"
    state.iteration = 1
    app._review_loops = {"pr-001": state}
    good = _break(app._root, "invalid_plans")
    with patch("pm_core.tui.qa_loop_ui.start_qa") as start, \
            patch("pm_core.tui.qa_loop_ui.poll_qa_state"), \
            patch("pm_core.tui.watcher_ui.poll_watcher_state"), \
            patch.object(review_loop_ui, "_refresh_tech_tree"):
        review_loop_ui._poll_loop_state_inner(app)   # loop done, file broken
        start.assert_not_called()
        _write(app._root / "project.yaml", good)
        review_loop_ui._poll_loop_state_inner(app)   # next tick
    start.assert_called_once_with(
        app, "pr-001", lock_timeout=0.0)  # store.NO_WAIT: retried per tick (RQ38)
    assert _status(app) == "qa"


def test_a_pr_that_left_in_review_drops_the_pending_hand_off(tmp_path):
    app = _self_driving_app(tmp_path)
    app._pending_auto_qa = {"pr-001": ("transition", "project.yaml is not valid YAML")}
    data = store.load(app._root)
    store.get_pr(data, "pr-001")["status"] = "in_progress"
    store.save(data, app._root)
    with patch("pm_core.tui.qa_loop_ui.start_qa") as start:
        review_loop_ui._start_qa_after_review(app, "pr-001")
    start.assert_not_called()
    assert app._pending_auto_qa == {}


# --- the file breaks between the in_review -> qa write and the QA start ---

def _race_app(tmp_path, kind, *, auto_start=False):
    """App whose project.yaml breaks right after the status write (the
    reload that follows it), so the real start_qa then fails to load."""
    if auto_start:
        app = _make_app(tmp_path, prs=[dict(PR, workdir=str(tmp_path / "wd"))],
                        auto_start=True, target="pr-001")
    else:
        app = _self_driving_app(tmp_path)
    saved = {}

    def reload_breaks_file():
        if "good" not in saved:
            saved["good"] = _break(app._root, kind)
    app._load_state.side_effect = reload_breaks_file
    return app, saved


@pytest.mark.parametrize("kind", ["conflict_markers", "invalid_plans",
                                  "missing_file"])
def test_launch_lost_after_the_status_write_starts_once_the_file_loads(
        tmp_path, kind):
    app, saved = _race_app(tmp_path, kind)
    with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg, \
            patch("pm_core.signoff.clear_return_awaiting"):
        review_loop_ui._start_qa_after_review(app, "pr-001")
        bg.assert_not_called()                       # start_qa could not load
        assert app._pending_auto_qa["pr-001"][0] == "launch"
        review_loop_ui._start_qa_after_review(app, "pr-001")   # still broken
        bg.assert_not_called()
        _write(app._root / "project.yaml", saved["good"])
        assert _status(app) == "qa"                  # the write had landed
        review_loop_ui._start_qa_after_review(app, "pr-001")   # file loads
        review_loop_ui._start_qa_after_review(app, "pr-001")   # nothing left
    assert bg.call_count == 1
    assert app._pending_auto_qa == {}
    waits = [c.args[0] for c in app.log_message.call_args_list
             if "waiting for project.yaml" in c.args[0]]
    assert len(waits) == 1


def test_stopped_zz_t_loop_drops_a_pending_launch(tmp_path):
    app, saved = _race_app(tmp_path, "invalid_plans")
    with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg, \
            patch("pm_core.signoff.clear_return_awaiting"):
        review_loop_ui._start_qa_after_review(app, "pr-001")
        assert app._pending_auto_qa["pr-001"][0] == "launch"
        app._self_driving_qa.pop("pr-001")           # user stopped the loop
        _write(app._root / "project.yaml", saved["good"])
        review_loop_ui._start_qa_after_review(app, "pr-001")
    bg.assert_not_called()
    assert app._pending_auto_qa == {}


@pytest.mark.parametrize("change", ["auto_start_off", "target_removed"])
def test_auto_start_leaving_scope_drops_a_pending_launch(tmp_path, change):
    app, saved = _race_app(tmp_path, "conflict_markers", auto_start=True)
    with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg, \
            patch("pm_core.signoff.clear_return_awaiting"):
        review_loop_ui._start_qa_after_review(app, "pr-001")
        assert app._pending_auto_qa["pr-001"][0] == "launch"
        if change == "auto_start_off":
            app._auto_start = False
        else:
            app._auto_start_targets = {"pr-other": {}}
        _write(app._root / "project.yaml", saved["good"])
        review_loop_ui._start_qa_after_review(app, "pr-001")
    bg.assert_not_called()
    assert app._pending_auto_qa == {}


def test_auto_start_in_scope_launches_once_after_recovery(tmp_path):
    app, saved = _race_app(tmp_path, "missing_file", auto_start=True)
    with patch("pm_core.tui.qa_loop_ui.start_qa_background") as bg, \
            patch("pm_core.signoff.clear_return_awaiting"):
        review_loop_ui._start_qa_after_review(app, "pr-001")
        _write(app._root / "project.yaml", saved["good"])
        review_loop_ui._start_qa_after_review(app, "pr-001")
        review_loop_ui._start_qa_after_review(app, "pr-001")
    assert bg.call_count == 1
