"""`pm container status` lists only this runtime's retention markers.

Two rootless stores can share PM state (HOME, PM_CONTAINER_STATE_DIR). A
marker set in store B names a container store A does not have, so A's status
must not claim it is retained; with A's identity unknown it is shown with the
saved diagnostics. Cleanup keeps honouring every marker regardless.
"""
from click.testing import CliRunner

from pm_core import container, container_reaper as reaper
from pm_core.cli import cli

A = {"runtime": "podman", "graph_root": "/a/graph", "run_root": "/a/run"}
B = {"runtime": "podman", "graph_root": "/b/graph", "run_root": "/b/run"}


def _markers(monkeypatch):
    domain = {"cur": A}
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: domain["cur"] and dict(domain["cur"]))
    reaper.retain("pm-tag-impl-pr-a", container_id="id-a")
    domain["cur"] = B
    reaper.retain("pm-tag-review-pr-b", container_id="id-b")
    return domain


def _status(monkeypatch):
    monkeypatch.setattr(container, "_runtime_available", lambda: False)
    return CliRunner().invoke(cli, ["container", "status"]).output


def test_known_identity_lists_only_own_retention(monkeypatch):
    domain = _markers(monkeypatch)
    domain["cur"] = A
    assert reaper.local_retained_names() == ["pm-tag-impl-pr-a"]
    out = _status(monkeypatch)
    retained = [line for line in out.splitlines() if line.startswith("Retained:")]
    assert retained and "pm-tag-impl-pr-a" in retained[0]
    assert "pm-tag-review-pr-b" not in out
    # Display only: the other store's marker still protects its container.
    domain["cur"] = B
    assert reaper.is_retained("pm-tag-review-pr-b", "id-b")


def test_unknown_identity_shows_markers_only_as_diagnostics(monkeypatch):
    domain = _markers(monkeypatch)
    domain["cur"] = None
    assert reaper.local_retained_names() == []
    out = _status(monkeypatch)
    assert "Retained:" not in out
    diag = out.split("Saved cleanup diagnostics", 1)[1]
    assert "pm-tag-review-pr-b: retained (kept out of cleanup)" in diag
    assert "pm-tag-impl-pr-a: retained (kept out of cleanup)" in diag
    assert reaper.is_retained("pm-tag-review-pr-b")
