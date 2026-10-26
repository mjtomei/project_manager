"""An owner release recorded without a runtime identity is a diagnostic.

Such a record can never authorize removal in any runtime (``_current_release_records``
excludes it) and full passes deliberately preserve unknown domains, so
``pm container reap`` can never clear it.  ``pm container status`` must not
present it as a retryable cleanup failure.
"""

import click
from click.testing import CliRunner

from pm_core import container_reaper as reaper
from pm_core.cli import container as cli_container

UNKNOWN = "pm-demo-impl-pr-aaaa"
KNOWN = "pm-demo-review-pr-bbbb"


def test_pending_failures_marks_unknown_domain_release(monkeypatch):
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    reaper._record_release(UNKNOWN, "id-u", "generation", "pane-exit")

    failure = reaper.pending_failures()[UNKNOWN]
    assert failure["unverifiable_release"] is True
    assert not failure.get("owner_release")
    assert "diagnostic" in failure["error"]
    # It never becomes cleanup authority.
    assert reaper.pending_releases() == {}


def _status(monkeypatch, failures):
    monkeypatch.setattr(reaper, "last_state", lambda: {})
    monkeypatch.setattr(reaper, "unavailable_runtime_diagnostics", lambda: [])
    monkeypatch.setattr(reaper, "retained_names", lambda: [])
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    monkeypatch.setattr(reaper, "is_retained", lambda name, cid="": False)
    monkeypatch.setattr(reaper, "pending_failures", lambda: dict(failures))
    cmd = click.Command("s", callback=cli_container._echo_reaper_state)
    return CliRunner().invoke(cmd, []).output


def test_unverifiable_release_is_not_a_retryable_failure(monkeypatch):
    out = _status(monkeypatch, {
        UNKNOWN: {"id": "id-u", "owner_release": False,
                  "unverifiable_release": True,
                  "error": "owner release was recorded without a runtime identity; "
                           "kept as a diagnostic only"},
        KNOWN: {"id": "id-k", "owner_release": True,
                "error": "owner release pending; retry with pm container reap"},
    })
    assert "Cleanup failures (1)" in out
    failures = out.split("Cleanup failures", 1)[1]
    assert UNKNOWN not in failures
    assert KNOWN in failures
    assert "Unverifiable release records" in out
    diagnostic = out.split("Unverifiable release records", 1)[1].split("Cleanup failures")[0]
    assert UNKNOWN in diagnostic and "id-u" in diagnostic
    assert KNOWN not in diagnostic


def test_only_unverifiable_records_omit_the_failure_heading(monkeypatch):
    out = _status(monkeypatch, {
        UNKNOWN: {"id": "id-u", "owner_release": False,
                  "unverifiable_release": True,
                  "error": "owner release was recorded without a runtime identity; "
                           "kept as a diagnostic only"},
    })
    assert "Cleanup failures" not in out
    assert "Unverifiable release records" in out
