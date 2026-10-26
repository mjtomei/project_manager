"""`pm container status` does not report a retained allocation's deferred owner release as a failure."""

from click.testing import CliRunner
import click

from pm_core import container_reaper as reaper
from pm_core.cli import container as cli_container

RETAINED = "pm-demo-review-pr-aaaa"
FAILED = "pm-demo-impl-pr-bbbb"


def _status(monkeypatch, retained_ids):
    monkeypatch.setattr(reaper, "last_state", lambda: {})
    monkeypatch.setattr(reaper, "unavailable_runtime_diagnostics", lambda: [])
    monkeypatch.setattr(reaper, "retained_names", lambda: [RETAINED])
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    monkeypatch.setattr(reaper, "pending_failures", lambda: {
        RETAINED: {"id": "id-r", "owner_release": True,
                   "error": "owner release pending; retry with pm container reap"},
        FAILED: {"id": "id-f", "owner_release": True,
                 "error": "owner release pending; retry with pm container reap"},
    })
    monkeypatch.setattr(reaper, "is_retained",
                        lambda name, cid="": (name, cid) in retained_ids)
    cmd = click.Command("s", callback=cli_container._echo_reaper_state)
    return CliRunner().invoke(cmd, []).output


def test_retained_owner_release_is_deferred_not_failed(monkeypatch):
    out = _status(monkeypatch, {(RETAINED, "id-r")})
    failures = out.split("Cleanup failures", 1)[1]
    assert RETAINED not in failures.split("Retained:")[0]
    assert "Cleanup failures (1)" in out and FAILED in failures
    assert "Released while retained" in out
    assert RETAINED in out.split("Released while retained", 1)[1].split("Cleanup failures")[0]


def test_replacement_under_retained_name_still_fails(monkeypatch):
    # Retention bound to a different id does not hide this allocation's failure.
    out = _status(monkeypatch, {(RETAINED, "id-other")})
    assert "Released while retained" not in out
    assert "Cleanup failures (2)" in out
