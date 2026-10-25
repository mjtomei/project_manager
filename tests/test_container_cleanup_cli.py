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
