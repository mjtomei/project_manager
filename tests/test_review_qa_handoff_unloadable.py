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
def test_review_pass_waits_and_starts_qa_once_the_file_loads(tmp_path, kind):
    app = _self_driving_app(tmp_path)
    good = _break(app._root, kind)
    with patch("pm_core.tui.qa_loop_ui.start_qa") as start:
        review_loop_ui._start_qa_after_review(app, "pr-001")
        review_loop_ui._start_qa_after_review(app, "pr-001")  # next tick
        start.assert_not_called()
        assert "pr-001" in app._pending_auto_qa
        waits = [c.args[0] for c in app.log_message.call_args_list
                 if "waiting for project.yaml" in c.args[0]]
        assert len(waits) == 1  # once per reason, not every tick

        _write(app._root / "project.yaml", good)
        review_loop_ui._start_qa_after_review(app, "pr-001")
    start.assert_called_once_with(app, "pr-001")
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
    start.assert_called_once_with(app, "pr-001")
    assert _status(app) == "qa"


def test_a_pr_that_left_in_review_drops_the_pending_hand_off(tmp_path):
    app = _self_driving_app(tmp_path)
    app._pending_auto_qa = {"pr-001": "project.yaml is not valid YAML"}
    data = store.load(app._root)
    store.get_pr(data, "pr-001")["status"] = "in_progress"
    store.save(data, app._root)
    with patch("pm_core.tui.qa_loop_ui.start_qa") as start:
        review_loop_ui._start_qa_after_review(app, "pr-001")
    start.assert_not_called()
    assert app._pending_auto_qa == {}
