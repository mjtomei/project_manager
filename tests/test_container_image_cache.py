"""create_container wiring of the shared image cache, and the subuid fit."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core import container as container_mod
from pm_core import image_cache
from pm_core.container import ContainerConfig, ContainerError, create_container
from pm_core.image_cache import CacheEntry, ImageCacheError


def _entry(tmp_path):
    return CacheEntry(key="k" * 20, path=tmp_path / "entries" / ("k" * 20),
                      meta={"image_id": "sha256:" + "a" * 64,
                            "names": ["localhost/pm-dev:latest"]})


@pytest.fixture
def podman_nested():
    with patch("pm_core.container.container_is_running", return_value=False), \
         patch("pm_core.container._get_runtime", return_value="podman"), \
         patch("pm_core.container._nested_podman_enabled", return_value=True), \
         patch("pm_core.container._nested_podman_run_args",
               return_value=["--uts=host"]), \
         patch("pm_core.container.image_exists", return_value=True), \
         patch("pm_core.container.remove_container"), \
         patch("pm_core.container._run_runtime") as rt, \
         patch.object(Path, "is_dir", return_value=False):
        rt.return_value = MagicMock(stdout="id\n", returncode=0)
        yield rt


def _run_args(rt):
    return next(c.args for c in rt.call_args_list if c.args[0] == "run")


class TestProvider:
    def test_mounts_entry_read_only_and_writes_engine_config(
            self, podman_nested, tmp_path, monkeypatch):
        monkeypatch.setenv(image_cache.MODE_ENV, "on")
        monkeypatch.setattr(image_cache, "is_consumer", lambda: False)
        entry = _entry(tmp_path)
        with patch.object(image_cache, "ensure_prepared",
                          return_value=entry) as prep:
            create_container("c1", ContainerConfig(), Path("/w"))
        prep.assert_called_once_with(ContainerConfig().image)
        args = _run_args(podman_nested)
        assert f"{entry.path}:{image_cache.CONSUMER_MOUNT}:ro" in args
        assert f"{image_cache.CACHE_LABEL}={entry.key}" in args
        setup = args[-1]
        assert ".config/containers" in setup
        assert "additionalimagestores" in setup
        assert image_cache.CONSUMER_STORE in setup

    def test_cache_failure_fails_the_launch(self, podman_nested, monkeypatch):
        """No launch without the cache, no VFS, no host fallback."""
        monkeypatch.setenv(image_cache.MODE_ENV, "on")
        monkeypatch.setattr(image_cache, "is_consumer", lambda: False)
        with patch.object(image_cache, "ensure_prepared",
                          side_effect=ImageCacheError("load rc=125")):
            with pytest.raises(ContainerError) as exc:
                create_container("c2", ContainerConfig(), Path("/w"))
        msg = str(exc.value)
        assert "load rc=125" in msg
        assert "pm container cache prepare" in msg
        assert f"pm set {image_cache.MODE_SETTING} off" in msg
        assert not any(c.args[0] == "run"
                       for c in podman_nested.call_args_list)

    @pytest.mark.parametrize("cause,shown", [
        ("run 'pm set container-image-cache off'",
         "run 'pm set container-image-cache off'.\n\nTo retry"),
        ("load rc=125.", "load rc=125.\n\nTo retry"),
    ])
    def test_cause_ends_as_a_sentence(self, podman_nested, monkeypatch,
                                      cause, shown):
        monkeypatch.setenv(image_cache.MODE_ENV, "on")
        monkeypatch.setattr(image_cache, "is_consumer", lambda: False)
        with patch.object(image_cache, "ensure_prepared",
                          side_effect=ImageCacheError(cause)):
            with pytest.raises(ContainerError) as exc:
                create_container("c2", ContainerConfig(), Path("/w"))
        assert f"Cause: {shown}" in str(exc.value)

    def test_off_launches_without_cache(self, podman_nested, monkeypatch):
        monkeypatch.setenv(image_cache.MODE_ENV, "off")
        with patch.object(image_cache, "ensure_prepared") as prep:
            create_container("c3", ContainerConfig(), Path("/w"))
        prep.assert_not_called()
        args = _run_args(podman_nested)
        assert not any(image_cache.CONSUMER_MOUNT in a for a in args)

    def test_nested_containers_get_the_subuid_fit(self, podman_nested,
                                                  monkeypatch):
        monkeypatch.setenv(image_cache.MODE_ENV, "off")
        create_container("c4", ContainerConfig(), Path("/w"))
        fits = [c.args for c in podman_nested.call_args_list
                if c.args[:3] == ("exec", "--user", "0")
                and "fit-subids" in c.args]
        assert len(fits) == 1


class TestConsumer:
    """A pm inside a cache consumer launching its own containers."""

    def test_missing_image_is_an_error_not_a_build(self, monkeypatch):
        monkeypatch.setenv(image_cache.MODE_ENV, "auto")
        monkeypatch.setattr(image_cache, "is_consumer", lambda: True)
        monkeypatch.setattr(image_cache, "ensure_consumer_engine",
                            lambda *a: None)
        monkeypatch.setattr(image_cache, "read_consumer_entry",
                            lambda: {"names": ["localhost/pm-dev:latest"]})
        with patch("pm_core.container.container_is_running", return_value=False), \
             patch("pm_core.container._get_runtime", return_value="podman"), \
             patch("pm_core.container._nested_podman_enabled", return_value=True), \
             patch("pm_core.container.remove_container"), \
             patch("pm_core.container.image_exists", return_value=False), \
             patch("pm_core.container.build_image") as build, \
             patch("pm_core.container._run_runtime") as rt:
            with pytest.raises(ContainerError) as exc:
                create_container("c5", ContainerConfig(), Path("/w"))
        build.assert_not_called()
        assert not rt.called
        assert "localhost/pm-dev:latest" in str(exc.value)

    def test_consumer_launch_reuses_cache_without_preparing(
            self, podman_nested, monkeypatch):
        monkeypatch.setenv(image_cache.MODE_ENV, "on")
        monkeypatch.setattr(image_cache, "is_consumer", lambda: True)
        ensured = []
        monkeypatch.setattr(image_cache, "ensure_consumer_engine",
                            lambda *a: ensured.append(True))
        with patch.object(image_cache, "ensure_prepared") as prep, \
             patch("pm_core.container.build_image") as build:
            create_container("c6", ContainerConfig(), Path("/w"))
        prep.assert_not_called()
        build.assert_not_called()
        assert ensured
        # The entry is not passed one keep-id level deeper.
        args = _run_args(podman_nested)
        assert not any(image_cache.CONSUMER_MOUNT in a for a in args)

    def test_incompatible_cache_fails_the_nested_launch(self, monkeypatch):
        monkeypatch.setenv(image_cache.MODE_ENV, "auto")
        monkeypatch.setattr(image_cache, "is_consumer", lambda: True)

        def bad(*a):
            raise ImageCacheError("prepared for engines at another level")
        monkeypatch.setattr(image_cache, "ensure_consumer_engine", bad)
        with patch("pm_core.container.container_is_running", return_value=False), \
             patch("pm_core.container._get_runtime", return_value="podman"), \
             patch("pm_core.container.remove_container"), \
             patch("pm_core.container._run_runtime") as rt:
            with pytest.raises(ContainerError, match="another level"):
                create_container("c7", ContainerConfig(), Path("/w"))
        assert not rt.called


# ---------------------------------------------------------------------------
# _FIT_SUBID_SCRIPT
# ---------------------------------------------------------------------------

def _fit(tmp_path, uid_map: str, subuid: str, uid=1000, user="pm"):
    """Run the script's fit() against sample files; return its output."""
    script = container_mod._FIT_SUBID_SCRIPT
    fn = script[:script.index("u=$(id")]
    (tmp_path / "map").write_text(uid_map)
    (tmp_path / "subuid").write_text(subuid)
    r = subprocess.run(
        ["sh", "-c", fn + f'fit "$1" "$2" {uid} {user}', "x",
         str(tmp_path / "map"), str(tmp_path / "subuid")],
        capture_output=True, text=True, check=True)
    return r.stdout


def test_fit_keeps_ranges_of_a_host_launched_container(tmp_path):
    host_map = ("         0          1       1000\n"
                "      1000          0          1\n"
                "      1001       1001      64536\n")
    assert _fit(tmp_path, host_map, "pm:1:999\npm:1001:64535\n") == ""


def test_fit_splits_ranges_in_a_container_launched_from_a_container(tmp_path):
    nested_map = ("         0          1        999\n"
                  "       999       1000          1\n"
                  "      1000          0          1\n"
                  "      1001       1001      64534\n")
    out = _fit(tmp_path, nested_map, "pm:1:999\npm:1001:64535\n")
    assert out.splitlines() == ["pm:1:998", "pm:999:1", "pm:1001:64534"]


def test_fit_never_hands_out_root_or_the_users_own_id(tmp_path):
    out = _fit(tmp_path, "0 0 65536\n", "")
    assert out.splitlines() == ["pm:1:999", "pm:1001:64535"]
