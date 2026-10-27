"""One manual autostart policy: wait_for_merge everywhere (pr-25f4038).

Covers the removal of ``stop_before_merge`` as a distinct state: default CLI
and command-bar adds, the O key, the deprecated ``--stop-before-merge``
alias, breadcrumb/legacy-record migration, and the resulting holds.
"""

import asyncio
import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pm_core import autostart_state as st
from pm_core import store
from pm_core.autostart_state import POLICY_AUTO, POLICY_WAIT
from pm_core.tui import auto_start

from tests.test_autostart_multi_target import FakeApp, _pr


def _prs():
    return [_pr("a"), _pr("f", deps=["a"])]


def _enabled(prs=None):
    app = FakeApp(prs or _prs())
    app._auto_start = True
    app._auto_start_run_id = "run"
    return app


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def test_default_add_selects_wait_for_merge():
    app = _enabled()
    res = auto_start.add_targets(app, ["f"])
    assert res["ok"]
    assert auto_start.target_policy(app, "f") == POLICY_WAIT
    assert auto_start.policy_for(app, "a") == POLICY_WAIT
    assert auto_start.merge_hold(app, "a") == {"targets": ["f"]}


def test_command_bar_default_add_selects_wait_for_merge():
    app = _enabled()
    assert auto_start.handle_command(app, ["add", "f"])["ok"]
    assert auto_start.target_policy(app, "f") == POLICY_WAIT
    assert auto_start.policy_for(app, "a") == POLICY_WAIT


def test_O_selects_wait_for_merge():
    app = _enabled()
    asyncio.run(auto_start.auto_sequence_for_pr(app, "f"))
    assert auto_start.target_policy(app, "f") == POLICY_WAIT
    assert auto_start.merge_hold(app, "a") == {"targets": ["f"]}
    assert any("will wait for merge" in m for m in app.logs)


def test_A_still_selects_auto_merge():
    app = _enabled()
    asyncio.run(auto_start.toggle(app, "f"))
    assert auto_start.target_policy(app, "f") == POLICY_AUTO
    assert auto_start.merge_hold(app, "a") is None


def test_legacy_policy_value_is_a_wait_alias():
    app = _enabled()
    res = auto_start.add_targets(app, ["f"], policy="stop_before_merge")
    assert res["ok"]
    assert res["changes"][0]["policy"] == POLICY_WAIT
    assert auto_start.merge_hold(app, "a") == {"targets": ["f"]}


def test_legacy_default_policy_is_a_wait_alias():
    app = _enabled()
    res = auto_start.add_targets(app, ["f"], default_policy="stop_before_merge")
    assert res["ok"]
    assert res["changes"][0]["policy"] == POLICY_WAIT
    assert auto_start.merge_hold(app, "a") == {"targets": ["f"]}


def test_unknown_default_policy_is_rejected_not_auto_merged():
    """A bad *default* must not fall through to the no-flag branch and
    silently drop the manual gate on a new target."""
    app = _enabled()
    res = auto_start.add_targets(app, ["f"], default_policy="something_new")
    assert res["ok"] is False and res["error"] == "usage"
    assert auto_start.get_targets(app) == []


def test_legacy_stop_flag_is_a_wait_alias():
    app = _enabled()
    assert auto_start.handle_command(
        app, ["add", "f", "--stop-before-merge"])["ok"]
    assert auto_start.target_policy(app, "f") == POLICY_WAIT
    assert auto_start.merge_hold(app, "a") == {"targets": ["f"]}


def test_legacy_stop_flag_does_not_conflict_with_wait():
    app = _enabled()
    res = auto_start.handle_command(
        app, ["add", "f", "--stop-before-merge", "--wait-for-merge"])
    assert res["ok"]
    assert auto_start.target_policy(app, "f") == POLICY_WAIT


def test_legacy_stop_flag_conflicts_with_auto():
    app = _enabled()
    res = auto_start.handle_command(
        app, ["add", "f", "--stop-before-merge", "--auto-merge"])
    assert res["ok"] is False and res["error"] == "conflicting_flags"
    assert auto_start.get_targets(app) == []


def test_cli_legacy_flag_sends_wait_to_owner(tmp_path, monkeypatch):
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    store.save({"project": {"name": "t", "repo": "/r",
                            "base_branch": "master"},
                "prs": _prs()}, pm_dir)
    monkeypatch.setattr("pm_core.cli.autostart.state_root", lambda: pm_dir)
    from pm_core.cli import cli
    reply = {"ok": True, "changes": [{"pr_id": "f", "action": "added",
                                      "policy": POLICY_WAIT}],
             "status": {"mode": "targets", "targets": [{"pr_id": "f"}]}}
    with patch("pm_core.cli.autostart._request", return_value=reply) as req:
        res = CliRunner().invoke(cli, [
            "autostart", "add", "f", "--stop-before-merge", "-s", "pm-x"])
    assert res.exit_code == 0, res.output
    # The deprecated alias is translated to the canonical manual flag.
    assert req.call_args.args[1] == ["add", "f", "--wait-for-merge"]


def test_cli_default_add_relies_on_owner_default(tmp_path, monkeypatch):
    """A plain add must not send a policy flag (re-add keeps the existing
    policy); the owner's new-target default is wait_for_merge."""
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    store.save({"project": {"name": "t", "repo": "/r",
                            "base_branch": "master"},
                "prs": _prs()}, pm_dir)
    monkeypatch.setattr("pm_core.cli.autostart.state_root", lambda: pm_dir)
    from pm_core.cli import cli
    with patch("pm_core.cli.autostart._request",
               return_value={"ok": True, "changes": [], "status": {}}) as req:
        CliRunner().invoke(cli, ["autostart", "add", "f", "-s", "pm-x"])
    assert req.call_args.args[1] == ["add", "f"]


# ---------------------------------------------------------------------------
# Breadcrumb / legacy record migration
# ---------------------------------------------------------------------------

def test_breadcrumb_legacy_stop_marks_become_wait_targets():
    prs = _prs() + [_pr("x")]
    data = {"auto_start": True, "run_id": "r",
            "targets": [{"pr_id": "f", "added_at": "t", "source": "key:A"}],
            "stop_before_merge": ["f", "x"]}
    targets, all_mode, migrated = st.targets_from_breadcrumb(data, prs)
    assert not all_mode and migrated
    assert list(targets) == ["f", "x"]
    assert targets["f"][st.WAIT_KEY] is True      # legacy stop target
    assert targets["x"][st.WAIT_KEY] is True      # standalone hold preserved
    assert targets["x"]["source"] == "legacy-stop"


def test_breadcrumb_legacy_stop_drops_terminal_ids():
    prs = [_pr("m", status="merged"), _pr("f")]
    data = {"auto_start": True, "targets": [{"pr_id": "f"}],
            "stop_before_merge": ["m", "f"]}
    targets, _all, _mig = st.targets_from_breadcrumb(data, prs)
    assert list(targets) == ["f"] and targets["f"][st.WAIT_KEY] is True


def test_breadcrumb_legacy_single_target_is_wait():
    targets, all_mode, migrated = st.targets_from_breadcrumb(
        {"auto_start": True, "target": "f", "run_id": "r"})
    assert list(targets) == ["f"] and not all_mode and migrated
    assert targets["f"][st.WAIT_KEY] is True


@pytest.mark.parametrize("record,wait", [
    ({"pr_id": "f", "policy": "stop_before_merge"}, True),
    ({"pr_id": "f", "policy": "wait_for_merge"}, True),
    ({"pr_id": "f", "policy": "auto_merge"}, False),
    ({"pr_id": "f", "policy": "auto-merge"}, False),
    ({"pr_id": "f", "policy": "something_new"}, True),   # fail closed
    ({"pr_id": "f", "policy": ""}, True),                # fail closed
    ({"pr_id": "f", "policy": None}, True),              # fail closed
    ({"pr_id": "f", "merge_policy": "stop_before_merge"}, True),
    ({"pr_id": "f", "wait_for_merge": False}, False),
    ({"pr_id": "f", "stop_before_merge": True}, True),
    ({"pr_id": "f"}, False),
])
def test_breadcrumb_record_fields_normalized(record, wait):
    targets, _all, _mig = st.targets_from_breadcrumb(
        {"auto_start": True, "targets": [record]})
    assert bool(targets["f"].get(st.WAIT_KEY)) is wait


def test_breadcrumb_record_migration_is_reported():
    """A legacy record field marks the breadcrumb migrated; a plain
    current-format record (auto target) does not."""
    _t, _a, migrated = st.targets_from_breadcrumb(
        {"auto_start": True,
         "targets": [{"pr_id": "f", "policy": "stop_before_merge"}]})
    assert migrated
    _t, _a, migrated = st.targets_from_breadcrumb(
        {"auto_start": True,
         "targets": [{"pr_id": "f", "added_at": "t", "source": "key:A"}]})
    assert not migrated
    _t, _a, migrated = st.targets_from_breadcrumb(
        {"auto_start": True,
         "targets": [{"pr_id": "f", "wait_for_merge": True}]})
    assert not migrated


def test_breadcrumb_stop_marks_dropped_when_auto_start_was_off():
    """A leftover mark cannot re-enable auto-start (and launch work) on its
    own; with auto-start off there is no scheduler/merge path to gate."""
    targets, all_mode, migrated = st.targets_from_breadcrumb(
        {"targets": [], "stop_before_merge": ["x"]})
    assert targets == {} and all_mode is False and migrated


def test_breadcrumb_string_target_is_a_legacy_shape():
    """No pm version wrote bare-string targets, so the policy is unknown:
    fail closed to wait-for-merge (as for ``target: X``) and report it."""
    targets, _all, migrated = st.targets_from_breadcrumb(
        {"auto_start": True, "targets": ["f"]})
    assert list(targets) == ["f"] and migrated
    assert targets["f"].get(st.WAIT_KEY) is True
    assert targets["f"]["source"] == "legacy-breadcrumb"


def test_breadcrumb_parse_is_idempotent():
    data = {"auto_start": True, "targets": [{"pr_id": "f"}],
            "stop_before_merge": ["x"]}
    first, _a, _m = st.targets_from_breadcrumb(data)
    second, _a2, _m2 = st.targets_from_breadcrumb(
        {"auto_start": True,
         "targets": st.targets_to_breadcrumb(first)})
    assert first == second


def test_breadcrumb_malformed_targets_fails_closed():
    targets, all_mode, migrated = st.targets_from_breadcrumb(
        {"targets": {"f": {}}, "all_mode": True})
    assert targets == {} and all_mode is False and migrated


def test_breadcrumb_all_mode_must_be_literal_true():
    targets, all_mode, _mig = st.targets_from_breadcrumb(
        {"targets": [], "all_mode": "false", "stop_before_merge": ["a"]})
    assert targets == {} and all_mode is False


@pytest.mark.parametrize("data", [
    {"auto_start": True, "all_mode": False},
    {"auto_start": True, "all_mode": "false"},
    {"auto_start": True, "targets": None, "all_mode": False},
    {"auto_start": True, "targets": None},
])
def test_breadcrumb_current_keys_without_targets_fail_closed(data):
    """A mixed-version/corrupt breadcrumb carrying current-format keys but no
    usable target list must not fall back to the legacy "all ready PRs"
    inference (which would auto-merge the whole backlog)."""
    targets, all_mode, migrated = st.targets_from_breadcrumb(data)
    assert targets == {} and all_mode is False and migrated


def test_breadcrumb_explicit_all_mode_without_targets_is_honored():
    targets, all_mode, migrated = st.targets_from_breadcrumb(
        {"auto_start": True, "all_mode": True, "run_id": "r"})
    assert targets == {} and all_mode is True and migrated


def test_breadcrumb_stop_field_as_string_keeps_one_id():
    targets, _all, _mig = st.targets_from_breadcrumb(
        {"auto_start": True, "targets": [{"pr_id": "f"}],
         "stop_before_merge": "x"})
    assert list(targets) == ["f", "x"]
    assert targets["x"][st.WAIT_KEY] is True


def test_save_breadcrumb_never_writes_stop_field(tmp_path):
    app = _enabled()
    auto_start.add_targets(app, ["f"])
    app._watcher_manager.is_any_running.return_value = False
    with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path):
        (tmp_path / "merge-restart").touch()
        auto_start.save_breadcrumb(app)
        data = json.loads((tmp_path / "autostart-resume.json").read_text())
    assert "stop_before_merge" not in data
    assert data["targets"][0]["wait_for_merge"] is True


def test_consume_legacy_breadcrumb_preserves_standalone_hold(tmp_path):
    prs = _prs() + [_pr("x")]
    (tmp_path / "autostart-resume.json").write_text(json.dumps({
        "auto_start": True, "run_id": "r",
        "targets": [{"pr_id": "f"}],
        "stop_before_merge": ["x"]}))
    fresh = FakeApp(prs, root=tmp_path)
    with patch("pm_core.tui.auto_start.pm_home", return_value=tmp_path), \
         patch.object(auto_start, "_adopt_live_qa"), \
         patch.object(auto_start, "check_and_start"):
        asyncio.run(auto_start.consume_breadcrumb(fresh))
    assert auto_start.get_targets(fresh) == ["f", "x"]
    # f was a plain (A / auto-merge) target; only the legacy standalone stop
    # mark on x becomes a manual wait target.
    assert auto_start.target_policy(fresh, "f") == POLICY_AUTO
    assert auto_start.target_policy(fresh, "x") == POLICY_WAIT
    assert auto_start.merge_hold(fresh, "a") is None
    assert auto_start.merge_hold(fresh, "x") == {"targets": ["x"]}


# ---------------------------------------------------------------------------
# Status / presentation
# ---------------------------------------------------------------------------

def test_status_inputs_and_labels_have_no_stop_state():
    app = _enabled()
    auto_start.add_targets(app, ["f"])
    inp = auto_start.collect_status_inputs(app)
    assert "stop_before_merge" not in inp
    status = st.build_status(inp)
    run = next(r for r in status["runs"] if r["pr_id"] == "a")
    assert run["policy"] == POLICY_WAIT
    assert "explicit_hold" not in run
    assert all("stop" not in label for r in st.status_rows(status)
               for label, _kind in st.policy_labels(r))


def test_build_status_folds_stale_stop_input():
    """A stale caller passing the removed field must not silently allow a
    merge: the ids are interpreted as wait targets."""
    prs = _prs()
    status = st.build_status({"prs": prs, "targets": {}, "enabled": True,
                              "stop_before_merge": {"a"}})
    assert [t["pr_id"] for t in status["targets"]] == ["a"]
    assert status["targets"][0]["policy"] == POLICY_WAIT
    run = next(r for r in status["runs"] if r["pr_id"] == "a")
    assert run["policy"] == POLICY_WAIT
