"""captures_dir only falls through to the container mount for its own PR.

The mount at ``/pm-captures`` is bind-mounted from one PR's host captures dir;
``container.create_container`` also exports ``PM_CAPTURES_PR`` naming that PR.
A process without a matching owner marker — most importantly a nested
throwaway pm project inside a scenario container whose environment lost the
marker — must never route its captures there. Fail closed: that is the
pr-1e9c117 incident, where a nested QA run wrote its own scenario
prompt/scenario/verdict files over the enclosing PR's evidence.
"""

from pm_core import paths


def _setup(tmp_path, monkeypatch, mount_pr, *, make_mount=True):
    home = tmp_path / "home"
    mount = tmp_path / "pm-captures"
    if make_mount:
        mount.mkdir()
    monkeypatch.setattr(paths, "sessions_dir", lambda: home / "sessions")
    monkeypatch.setattr(paths, "CONTAINER_CAPTURES_MOUNT", str(mount))
    if mount_pr is None:
        monkeypatch.delenv(paths.CAPTURES_PR_ENV, raising=False)
    else:
        monkeypatch.setenv(paths.CAPTURES_PR_ENV, mount_pr)
    return home, mount


def _host_captures(home, tag, pr_id):
    return home / "sessions" / tag / "captures" / pr_id


def test_mount_used_for_its_own_pr(tmp_path, monkeypatch):
    _, mount = _setup(tmp_path, monkeypatch, "pr-aaa")
    assert paths.captures_dir("pr-aaa", session_tag="t") == mount


def test_other_pr_in_container_does_not_write_into_mount(tmp_path, monkeypatch):
    # A nested throwaway pm project inside a scenario container.
    home, mount = _setup(tmp_path, monkeypatch, "pr-aaa")
    got = paths.captures_dir("pr-nested", session_tag="t")
    assert got == _host_captures(home, "t", "pr-nested")
    assert not any(mount.iterdir())


def test_mount_without_pr_env_fails_closed(tmp_path, monkeypatch):
    # The pr-1e9c117 incident: no owner marker must not grant the mount to
    # an arbitrary PR.
    home, mount = _setup(tmp_path, monkeypatch, None)
    got = paths.captures_dir("pr-any", session_tag="t")
    assert got == _host_captures(home, "t", "pr-any")
    assert not any(mount.iterdir())


def test_empty_pr_env_fails_closed(tmp_path, monkeypatch):
    home, mount = _setup(tmp_path, monkeypatch, "")
    got = paths.captures_dir("pr-any", session_tag="t")
    assert got == _host_captures(home, "t", "pr-any")
    assert not any(mount.iterdir())


def test_whitespace_pr_env_fails_closed(tmp_path, monkeypatch):
    home, mount = _setup(tmp_path, monkeypatch, "  \n")
    got = paths.captures_dir("pr-any", session_tag="t")
    assert got == _host_captures(home, "t", "pr-any")
    assert not any(mount.iterdir())


def test_owner_marker_is_stripped_for_comparison(tmp_path, monkeypatch):
    # `export PM_CAPTURES_PR=$(...)` can carry a trailing newline; that is
    # still the owning PR, not a mismatch.
    _, mount = _setup(tmp_path, monkeypatch, "pr-aaa\n")
    assert paths.captures_dir("pr-aaa", session_tag="t") == mount


def test_nested_throwaway_projects_get_separate_captures(tmp_path, monkeypatch):
    # Two nested throwaway projects inside the enclosing container: no owner
    # marker, different session tags and PRs. Each lands in its own captures
    # dir and the enclosing PR's mount is untouched.
    home, mount = _setup(tmp_path, monkeypatch, None)
    first = paths.captures_dir("pr-first", session_tag="nested-a")
    second = paths.captures_dir("pr-second", session_tag="nested-b")
    assert first == _host_captures(home, "nested-a", "pr-first")
    assert second == _host_captures(home, "nested-b", "pr-second")
    assert first != second
    assert first.is_dir() and second.is_dir()
    assert not any(mount.iterdir())


def test_unowned_mount_without_tag_returns_none(tmp_path, monkeypatch):
    # Fail closed even when no host path can be derived: None, never the
    # enclosing PR's mount.
    _, mount = _setup(tmp_path, monkeypatch, None)
    assert paths.captures_dir("pr-any", session_tag="") is None
    assert not any(mount.iterdir())


def test_mismatched_owner_without_tag_returns_none(tmp_path, monkeypatch):
    _, mount = _setup(tmp_path, monkeypatch, "pr-aaa")
    assert paths.captures_dir("pr-other", session_tag="") is None
    assert not any(mount.iterdir())


def test_host_fallback_without_mount_creates_dir(tmp_path, monkeypatch):
    # Host behaviour is unchanged: no mount, derive the tag, create the dir.
    home, _ = _setup(tmp_path, monkeypatch, None, make_mount=False)
    got = paths.captures_dir("pr-any", session_tag="t")
    assert got == _host_captures(home, "t", "pr-any")
    assert got.is_dir()


def test_existing_host_path_wins_over_own_mount(tmp_path, monkeypatch):
    # Precedence is unchanged: an existing host path (the host process's own
    # view) wins even when this process's marker names the mounted PR.
    home, mount = _setup(tmp_path, monkeypatch, "pr-aaa")
    host = _host_captures(home, "t", "pr-aaa")
    host.mkdir(parents=True)
    assert paths.captures_dir("pr-aaa", session_tag="t") == host
    assert not any(mount.iterdir())


def test_mount_missing_for_own_pr_falls_back_to_host(tmp_path, monkeypatch):
    home, _ = _setup(tmp_path, monkeypatch, "pr-aaa", make_mount=False)
    got = paths.captures_dir("pr-aaa", session_tag="t")
    assert got == _host_captures(home, "t", "pr-aaa")
    assert got.is_dir()
