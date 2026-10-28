"""Unreadable owner records never authorize cross-runtime proxy changes."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from pm_core import container, container_reaper, push_proxy


@pytest.mark.parametrize("contents", ['{"runtime_domain":', '[]', 'null'])
def test_invalid_owner_preserves_proxy(tmp_path, monkeypatch, contents):
    owner = tmp_path / "owner.json"
    owner.write_text(contents)
    # The directory is found by name only: its owner record cannot be read,
    # so it is never listed as a releasable shared proxy.
    monkeypatch.setattr(push_proxy, "_pr_dir_candidates", lambda *a: [str(tmp_path)])
    # Scan only this directory, never the host's real /tmp proxy dirs.
    real_glob = push_proxy.glob.glob
    monkeypatch.setattr(push_proxy.glob, "glob", lambda pattern, *a, **k: (
        [str(tmp_path)] if pattern == f"/tmp/{push_proxy._SOCKET_DIR_PREFIX}*"
        else real_glob(pattern, *a, **k)))
    monkeypatch.setattr(push_proxy, "_is_proxy_dir", lambda *a: True)
    monkeypatch.setattr(container, "containers_for_pr", lambda *a: set())
    remove = Mock()
    monkeypatch.setattr(push_proxy, "_kill_proxy_socket", remove)
    assert not push_proxy._owner_domain_matches(str(tmp_path))
    assert push_proxy.list_shared_proxies() == []
    assert not push_proxy.release_proxy_if_unused("tag", "pr-aaaa")
    assert (push_proxy.release_proxy_decision("tag", "pr-aaaa")
            == push_proxy.PROXY_UNDETERMINED)
    remove.assert_not_called()
    assert owner.read_text() == contents


def test_unreadable_owner_is_not_legacy(tmp_path, monkeypatch):
    owner = tmp_path / "owner.json"
    owner.write_text("{}")
    owner.chmod(0)
    try:
        assert not push_proxy._owner_domain_matches(str(tmp_path))
    finally:
        owner.chmod(0o600)


def test_symlinked_owner_is_not_followed(tmp_path):
    """The socket directory is container-writable: a planted link is invalid."""
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps({"runtime_domain": None}))
    (tmp_path / "owner.json").symlink_to(target)
    assert push_proxy._read_owner(str(tmp_path)) == ("invalid", None)
    assert not push_proxy._owner_domain_matches(str(tmp_path))


def test_unknown_domain_cannot_publish_new_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(container_reaper, "_runtime_domain", lambda: None)
    with pytest.raises(container.ContainerError, match="runtime identity"):
        push_proxy._write_owner_file(str(tmp_path), "tag", "pr-aaaa", "/work")
    assert not (tmp_path / "owner.json").exists()


def test_explicit_unknown_domain_is_not_legacy(tmp_path):
    (tmp_path / "owner.json").write_text(json.dumps({"runtime_domain": None}))
    assert not push_proxy._owner_domain_matches(str(tmp_path))


def test_missing_owner_remains_legacy(tmp_path):
    assert push_proxy._owner_domain_matches(str(tmp_path))


def test_owner_publication_failure_preserves_previous_record(tmp_path, monkeypatch):
    owner = tmp_path / "owner.json"
    previous = json.dumps({"runtime_domain": {"runtime": "test", "id": "old"}})
    owner.write_text(previous)
    replace = Mock(side_effect=OSError("owner publication failed"))
    monkeypatch.setattr(push_proxy.os, "replace", replace)
    with pytest.raises(container.ContainerError, match="owner publication failed"):
        push_proxy._write_owner_file(str(tmp_path), "tag", "pr-aaaa", "/work")
    assert owner.read_text() == previous
    assert list(tmp_path.iterdir()) == [owner]


def test_owner_publication_precedes_proxy_start(tmp_path, monkeypatch):
    monkeypatch.setattr(push_proxy, "_shared_sock_dir", lambda *a: str(tmp_path))
    monkeypatch.setattr(push_proxy, "_write_owner_file",
                        Mock(side_effect=container.ContainerError("cannot record owner")))
    spawn = Mock()
    monkeypatch.setattr(push_proxy, "_start_proxy_subprocess", spawn)
    with pytest.raises(container.ContainerError, match="cannot record owner"):
        push_proxy.start_push_proxy("pm-tag-impl-pr-aaaa", "/work", "branch",
                                    session_tag="tag", pr_id="pr-aaaa")
    spawn.assert_not_called()


def test_malformed_owner_record_is_not_a_legacy_proxy(tmp_path, monkeypatch):
    """An unreadable/malformed record must not be reported as a legacy owner.

    Fabricating tag+PR from the directory name would let a later caller act
    on an identity nobody verified.
    """
    directory = tmp_path / "pm-push-proxy-tag-pr-aaaa"
    directory.mkdir()
    (directory / "owner.json").write_text("{")
    monkeypatch.setattr("glob.glob", lambda _pattern: [str(directory)])
    assert push_proxy.list_shared_proxies() == []
