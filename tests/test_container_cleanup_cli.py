"""User-facing cleanup diagnostics remain available during runtime failures."""

from unittest.mock import patch

from click.testing import CliRunner

from pm_core import container, container_reaper
from pm_core.cli import cli


def test_status_reports_pending_cleanup_when_runtime_unavailable():
    state = {"last_run": 1, "last_reason": "periodic", "last_summary": "failed 1"}
    with patch.object(container, "_runtime_available", return_value=False), \
         patch.object(container_reaper, "last_state", return_value=state), \
         patch.object(container_reaper, "pending_failures", return_value={
             "pm-review-pr-001": {"error": "runtime connection failed"}}), \
         patch.object(container_reaper, "retained_names", return_value=[]):
        result = CliRunner().invoke(cli, ["container", "status"])
    assert result.exit_code == 0, result.output
    assert "Runtime available: no" in result.output
    assert "runtime connection failed" in result.output
    assert "pm container reap" in result.output
    assert "Last cleanup:" in result.output


def test_status_keeps_scoped_failures_visible_during_runtime_outage(monkeypatch):
    domain = {"runtime": "docker", "daemon_id": "first"}
    monkeypatch.setattr(container_reaper, "_runtime_domain", lambda: domain)
    name = "pm-tag-review-pr-001"
    for daemon in ("first", "second"):
        domain = {"runtime": "docker", "daemon_id": daemon}
        container_reaper._record(
            container_reaper.Outcome(failures={name: f"{daemon} removal refused"}),
            container_reaper.Scope(), "test")
        container_reaper._record_release(name, daemon + "-id", "generation", "test")
    files = {path: path.read_bytes() for path in container.container_state_dir().rglob("*.json")}
    monkeypatch.setattr(container, "_runtime_available", lambda: False)
    monkeypatch.setattr(container_reaper, "retained_names", lambda: [])

    # A known domain still displays only its own outcomes.
    result = CliRunner().invoke(cli, ["container", "status"])
    assert result.exit_code == 0, result.output
    assert "second removal refused" in result.output
    assert "first removal refused" not in result.output

    domain = None
    result = CliRunner().invoke(cli, ["container", "status"])
    assert result.exit_code == 0, result.output
    assert "first removal refused" in result.output
    assert "second removal refused" in result.output
    assert "first-id" in result.output and "second-id" in result.output
    assert "runtime identity unavailable" in result.output
    assert "pm container reap" in result.output
    # Diagnostics never feed foreign records into cleanup authorization or writes.
    assert container_reaper.last_state() == {}
    assert container_reaper.pending_failures() == {}
    assert container_reaper._current_release_records() == []
    assert {path: path.read_bytes() for path in files} == files


def test_retain_release_reports_runtime_outage(monkeypatch):
    def unavailable(name):
        raise OSError("podman: No such file or directory")

    monkeypatch.setattr(container_reaper, "unretain", unavailable)
    result = CliRunner().invoke(cli, ["container", "retain", "pm-x", "--release"])
    assert result.exit_code == 1
    assert "Cannot release retention for pm-x" in result.output
    assert "No such file" in result.output


def test_retain_release_reports_unknown_runtime_identity(monkeypatch):
    """An unknown runtime identity must not claim the marker was absent."""
    monkeypatch.setattr(container_reaper, "_runtime_domain", lambda: None)
    marker = container.container_state_dir() / "retain" / "pm-x"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}")
    result = CliRunner().invoke(cli, ["container", "retain", "pm-x", "--release"])
    assert result.exit_code == 1, result.output
    assert "runtime identity is unavailable" in result.output
    assert "was not retained" not in result.output
    assert marker.exists(), "the marker must survive an unverified release"


def test_empty_reap_still_reports_recovery_counts():
    outcome = container_reaper.Outcome(
        scope="all pm containers", running_before=0, running_after=0,
        keyring_before="10/200", keyring_after="10/200")
    with patch.object(container_reaper, "reconcile", return_value=outcome):
        result = CliRunner().invoke(cli, ["container", "reap"])
    assert result.exit_code == 0, result.output
    assert "No pm containers in scope" in result.output
    assert "removed 0, kept 0, failed 0" in result.output
    assert "running 0 → 0" in result.output
    assert "keyring 10/200 → 10/200" in result.output
