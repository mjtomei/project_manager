"""Retention follows allocation IDs, including runtime renames."""
import subprocess
import time

import pytest

from pm_core import container, container_reaper as reaper


@pytest.mark.parametrize("legacy", [False, True])
def test_retention_follows_renamed_id_and_survives_pruning(monkeypatch, legacy):
    name, cid = "pm-tag-review-pr-aaaa", "retained-id"
    reaper.retain(name, container_id=cid)
    if legacy:
        import hashlib
        path = reaper._retention_path(name, cid)
        old_path = path.parent / (hashlib.sha256(f"{name}\0{cid}".encode()).hexdigest() + ".json")
        if old_path != path:
            path.rename(old_path)
    assert reaper.is_retained("archived-review", cid)
    reaper._prune_retain_markers({"archived-review": cid}, time.time() + 2)
    assert reaper.is_retained("archived-review", cid)
    assert not reaper.is_retained(name, "replacement-id")


def test_retention_isolated_when_runtime_stores_share_ids(monkeypatch):
    domain = {"runtime": "test", "id": "first"}
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: dict(domain))
    reaper.retain("pm-original", container_id="cloned-id")
    domain["id"] = "second"
    assert not reaper.is_retained("pm-original", "cloned-id")
    reaper.retain("pm-original", note="second", container_id="cloned-id")
    domain["id"] = "first"
    assert reaper.is_retained("archive", "cloned-id")
    records = [rec for _, rec in reaper._retention_records()]
    assert len(records) == 2


@pytest.mark.parametrize("managed", [True, False])
def test_canonical_name_accepts_renamed_managed_container(monkeypatch, managed):
    def runtime(*args, **kwargs):
        output = "/archive" if args[2] == "{{.Name}}" else ("1" if managed else "<no value>")
        return subprocess.CompletedProcess(args, 0, output, "")
    monkeypatch.setattr(container, "_run_runtime", runtime)
    if managed:
        assert container.canonical_container_name("cid") == "archive"
    else:
        with pytest.raises(container.ContainerError):
            container.canonical_container_name("cid")


def test_unknown_domain_preserves_retention(monkeypatch):
    reaper.retain("pm-original", container_id="retained-id")
    monkeypatch.setattr(reaper, "_runtime_domain", lambda: None)
    assert reaper.is_retained("archive", "retained-id")


def test_release_retention_by_renamed_allocation(monkeypatch):
    reaper.retain("pm-original", container_id="retained-id")
    monkeypatch.setattr(container, "current_container_id", lambda name: "retained-id")
    assert reaper.unretain("archive")
    assert not reaper.is_retained("archive", "retained-id")


def test_release_renamed_retention_ignores_stale_same_name(monkeypatch):
    reaper.retain("pm-original", container_id="retained-id")
    reaper.retain("pm-archive", container_id="deleted-id")
    monkeypatch.setattr(container, "current_container_id", lambda name: "retained-id")
    assert reaper.unretain("pm-archive")
    assert not reaper.is_retained("pm-archive", "retained-id")
