"""Explicit teardown reports partial failures and preserves reaper diagnostics."""

from unittest.mock import Mock

from click.testing import CliRunner

from pm_core import container as cm, container_reaper as reaper, pr_cleanup


NAME = "pm-demo-impl-pr-aaaa"
OTHER = "pm-demo-review-pr-aaaa"


def failed_removal(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda name: "id-" + name)
    def remove(name, **kwargs):
        if name == NAME:
            raise cm.ContainerError("runtime removal denied")
    monkeypatch.setattr(cm, "remove_container", remove)


def test_bulk_failure_persists_identity_without_force_authority(monkeypatch):
    failed_removal(monkeypatch)
    removed, failures = cm.remove_containers([NAME, OTHER])
    assert removed == [OTHER]
    assert failures == {NAME: "runtime removal denied"}
    pending = reaper.pending_failures()[NAME]
    assert pending["id"] == "id-" + NAME
    assert "runtime removal denied" in pending["error"]
    assert not pending.get("owner_release")
    assert not reaper.pending_releases()
    monkeypatch.setattr(cm, "remove_container", lambda *args, **kwargs: None)
    assert cm.remove_containers([NAME]) == ([NAME], {})
    assert NAME not in reaper.pending_failures()


def test_pr_resource_summary_includes_partial_failures(monkeypatch):
    failed_removal(monkeypatch)
    monkeypatch.setattr(reaper, "list_containers", lambda: [
        reaper.ContainerInfo(NAME, "id-" + NAME, session_tag=None, pr_id="pr-aaaa"),
        reaper.ContainerInfo(OTHER, "id-" + OTHER, session_tag=None, pr_id="pr-aaaa")])
    summary = pr_cleanup.cleanup_pr_resources(None, {"id": "pr-aaaa"})
    assert summary["containers"] == [OTHER]
    assert summary["container_failures"] == {NAME: "runtime removal denied"}
    text = pr_cleanup.format_summary(summary)
    assert "1 container cleanup failure" in text
    assert NAME in text and "runtime removal denied" in text


def test_pr_inventory_failure_is_visible(monkeypatch):
    monkeypatch.setattr(reaper, "list_containers", lambda: None)
    summary = pr_cleanup.cleanup_pr_resources(None, {"id": "pr-aaaa"})
    assert summary["container_failures"]
    assert "Cannot inventory" in pr_cleanup.format_summary(summary)


def test_session_cleanup_exports_failures(monkeypatch):
    failed_removal(monkeypatch)
    monkeypatch.setattr(reaper, "list_containers", lambda: [
        reaper.ContainerInfo(NAME, "id-" + NAME, session_tag="demo")])
    failures = {}
    assert cm.cleanup_session_containers("demo", failures=failures) == 0
    assert failures == {NAME: "runtime removal denied"}


def test_session_inventory_failure_is_visible(monkeypatch):
    monkeypatch.setattr(reaper, "list_containers", lambda: None)
    failures = {}
    assert cm.cleanup_session_containers("demo", failures=failures) == 0
    assert "inventory" in str(failures).lower()


def test_session_kill_reports_partial_failure(monkeypatch):
    import importlib
    cli = importlib.import_module("pm_core.cli.session")
    monkeypatch.delenv("PM_SHARE_MODE", raising=False)
    monkeypatch.setattr(cli, "_get_session_name_for_cwd", lambda: "pm-demo")
    monkeypatch.setattr(cli.tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(cli.tmux_mod, "session_exists", lambda *a, **kw: True)
    monkeypatch.setattr(cli.tmux_mod, "list_grouped_sessions", lambda *a, **kw: [])
    monkeypatch.setattr(cli.tmux_mod, "kill_session", Mock())
    monkeypatch.setattr(cli.pane_layout, "set_force_mobile", Mock())
    failed_removal(monkeypatch)
    monkeypatch.setattr(reaper, "list_containers", lambda: [
        reaper.ContainerInfo(NAME, "id-" + NAME, session_tag="demo")])
    from pm_core import push_proxy
    monkeypatch.setattr(push_proxy, "stop_session_proxies", lambda tag: 0)
    result = CliRunner().invoke(cli.session_kill, [])
    assert result.exit_code == 1, result.output
    assert "Killed session" in result.output
    assert NAME in result.output and "runtime removal denied" in result.output


def test_pr_cleanup_cli_reports_partial_failure(monkeypatch):
    import importlib
    cli = importlib.import_module("pm_core.cli.pr")
    monkeypatch.setattr(cli, "state_root", lambda: None)
    monkeypatch.setattr(cli.store, "load", lambda root: {})
    monkeypatch.setattr(cli, "_resolve_pr_id", lambda data, value: {"id": "pr-aaaa"})
    monkeypatch.setattr(cli, "trigger_tui_refresh", Mock())
    from pm_core import loop_shared
    monkeypatch.setattr(loop_shared, "get_pm_session", lambda: None)
    monkeypatch.setattr(pr_cleanup, "cleanup_pr_resources", lambda *a: {
        "windows": [], "containers": [OTHER], "registry_windows": [],
        "container_failures": {NAME: "runtime removal denied"}})
    result = CliRunner().invoke(cli.pr_cleanup, ["pr-aaaa", "--resources"])
    assert result.exit_code == 1, result.output
    assert NAME in result.output and "runtime removal denied" in result.output


def test_persistence_failure_is_returned(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda name: "id-" + name)
    monkeypatch.setattr(cm, "remove_container", lambda *args, **kwargs: None)
    monkeypatch.setattr(reaper, "_record", Mock(side_effect=OSError("state unavailable")))
    removed, failures = cm.remove_containers([NAME])
    assert removed == [NAME]
    assert "state unavailable" in str(failures)


def test_persistence_lock_failure_is_returned(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda name: "id-" + name)
    monkeypatch.setattr(cm, "remove_container", lambda *args, **kwargs: None)
    def cannot_record(out, *args, **kwargs):
        out.failures["cleanup state"] = "state lock unavailable"
    monkeypatch.setattr(reaper, "_record", cannot_record)
    removed, failures = cm.remove_containers([NAME])
    assert removed == [NAME]
    assert failures == {"cleanup state": "state lock unavailable"}


def test_identity_capture_failure_is_durable(monkeypatch):
    monkeypatch.setattr(cm, "current_container_id", lambda name: None)
    removed, failures = cm.remove_containers([NAME])
    assert not removed
    assert "identity unknown" in failures[NAME]
    assert "identity unknown" in reaper.pending_failures()[NAME]["error"]
    assert not reaper.pending_failures()[NAME].get("owner_release")


def test_empty_bulk_cleanup_leaves_last_outcome_unchanged(monkeypatch):
    record = Mock()
    monkeypatch.setattr(reaper, "_record", record)
    assert cm.remove_containers([]) == ([], {})
    record.assert_not_called()
