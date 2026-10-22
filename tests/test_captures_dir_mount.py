"""captures_dir only falls through to the container mount for its own PR."""

from pathlib import Path

from pm_core import paths


def _setup(tmp_path, monkeypatch, mount_pr):
    home = tmp_path / "home"
    mount = tmp_path / "pm-captures"
    mount.mkdir()
    monkeypatch.setattr(paths, "sessions_dir", lambda: home / "sessions")
    monkeypatch.setattr(paths, "CONTAINER_CAPTURES_MOUNT", str(mount))
    if mount_pr is None:
        monkeypatch.delenv(paths.CAPTURES_PR_ENV, raising=False)
    else:
        monkeypatch.setenv(paths.CAPTURES_PR_ENV, mount_pr)
    return home, mount


def test_mount_used_for_its_own_pr(tmp_path, monkeypatch):
    _, mount = _setup(tmp_path, monkeypatch, "pr-aaa")
    assert paths.captures_dir("pr-aaa", session_tag="t") == mount


def test_other_pr_in_container_does_not_write_into_mount(tmp_path, monkeypatch):
    # A nested throwaway pm project inside a scenario container.
    home, mount = _setup(tmp_path, monkeypatch, "pr-aaa")
    got = paths.captures_dir("pr-nested", session_tag="t")
    assert got == home / "sessions" / "t" / "captures" / "pr-nested"
    assert not any(mount.iterdir())


def test_mount_without_pr_env_keeps_old_behaviour(tmp_path, monkeypatch):
    _, mount = _setup(tmp_path, monkeypatch, None)
    assert paths.captures_dir("pr-any", session_tag="t") == mount
