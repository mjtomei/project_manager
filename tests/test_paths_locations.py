"""Configurable locations: NAS-capable workdirs/evidence, local-only scratch
and image cache (pm_core.paths) and their ``pm set`` surface."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from pm_core import paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: h)
    return h


@pytest.fixture
def nas(tmp_path, monkeypatch):
    """A directory the mount table says is NFS."""
    d = tmp_path / "nas"
    d.mkdir()
    mi = tmp_path / "mountinfo"
    mi.write_text("21 1 8:2 / / rw,relatime - ext4 /dev/nvme0n1p2 rw\n"
                  f"40 21 0:50 / {d} rw,relatime - nfs4 nas:/export rw\n")
    monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
    return d


class TestDefaults:
    def test_defaults_live_under_pm_home(self, home):
        assert paths.workdirs_base() == home / ".pm" / "workdirs"
        assert paths.qa_workdirs_root() == home / ".pm" / "workdirs" / "qa"
        assert paths.scratch_base() == home / ".pm" / "scratch"
        assert paths.captures_root("tag") == (home / ".pm" / "sessions"
                                              / "tag" / "captures")


class TestConfigured:
    def test_workdirs_and_captures_may_move(self, home, tmp_path, nas):
        paths.set_global_setting_value("workdirs-dir", str(nas / "wd"))
        paths.set_global_setting_value("captures-dir", str(nas / "ev"))
        assert paths.workdirs_base() == nas / "wd"
        assert paths.qa_workdirs_root() == nas / "wd" / "qa"
        assert paths.captures_root("tag") == nas / "ev" / "tag"
        assert paths.captures_dir("pr-1", session_tag="tag") == (
            nas / "ev" / "tag" / "pr-1")

    def test_scratch_stays_local_when_workdirs_move(self, home, nas):
        """The old scratch-under-workdir layout would have followed the
        workdirs onto the NAS; the new one does not."""
        paths.set_global_setting_value("workdirs-dir", str(nas / "wd"))
        run = paths.qa_workdirs_root() / "pr-1-abc"
        scratch = paths.scenario_scratch_dir(run, 2)
        assert scratch == home / ".pm" / "scratch" / "qa" / "pr-1-abc" / "s-2"
        assert not paths.is_network_filesystem(scratch)
        assert paths.is_network_filesystem(run)

    def test_legacy_scratch_kept_for_in_flight_runs(self, home, tmp_path):
        legacy = tmp_path / "run" / "s-1" / "scratch"
        legacy.mkdir(parents=True)
        assert paths.scenario_scratch_dir(tmp_path / "run", 1) == legacy

    def test_relative_value_is_taken_from_home(self, home):
        paths.set_global_setting_value("scratch-dir", "fast/scratch")
        assert paths.configured_dir("scratch-dir") == home / "fast" / "scratch"


class TestFilesystemType:
    def test_longest_mount_point_wins(self, tmp_path, nas):
        assert paths.filesystem_type(nas / "a" / "b") == "nfs4"
        assert paths.filesystem_type(tmp_path / "local") == "ext4"
        assert paths.is_network_filesystem(nas / "x")
        assert not paths.is_network_filesystem(tmp_path)

    def test_escaped_mount_points(self, tmp_path, monkeypatch):
        d = tmp_path / "my share"
        d.mkdir()
        esc = str(d).replace(" ", "\\040")
        mi = tmp_path / "mi"
        mi.write_text("1 0 0:1 / / rw - ext4 /dev/sda rw\n"
                      f"2 1 0:2 / {esc} rw - cifs //nas/s rw\n")
        monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
        assert paths.filesystem_type(d / "f") == "cifs"

    def test_fuse_network_types(self, tmp_path, monkeypatch):
        mi = tmp_path / "mi"
        mi.write_text(f"1 0 0:1 / / rw - fuse.sshfs host:/ rw\n")
        monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
        assert paths.is_network_filesystem(tmp_path)

    def test_local_fuse_overlay_is_not_network(self, tmp_path, monkeypatch):
        mi = tmp_path / "mi"
        mi.write_text("1 0 0:1 / / rw - fuse.fuse-overlayfs f rw\n")
        monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
        assert not paths.is_network_filesystem(tmp_path)

    def test_unreadable_mount_table(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "_MOUNTINFO", str(tmp_path / "missing"))
        assert paths.filesystem_type(tmp_path) is None
        paths.require_local_path(tmp_path, "x")  # no error

    def test_require_local_path_message(self, nas):
        with pytest.raises(paths.NonLocalPathError) as exc:
            paths.require_local_path(nas / "s", "QA scenario scratch",
                                     "scratch-dir")
        msg = str(exc.value)
        assert "nfs4" in msg and "pm set scratch-dir" in msg
        assert "workdirs-dir" in msg and "captures-dir" in msg


class TestPmSet:
    def _set(self, *args):
        from pm_core.cli import cli
        return CliRunner().invoke(cli, ["set", *args])

    def test_path_settings(self, home, tmp_path):
        r = self._set("scratch-dir", str(tmp_path / "fast"))
        assert r.exit_code == 0, r.output
        assert paths.scratch_base() == tmp_path / "fast"
        r = self._set("scratch-dir", "default")
        assert r.exit_code == 0, r.output
        assert paths.scratch_base() == home / ".pm" / "scratch"

    def test_relative_path_refused(self, home):
        r = self._set("workdirs-dir", "relative/path")
        assert r.exit_code == 1
        assert "absolute" in r.output

    def test_local_only_settings_refuse_network(self, home, nas):
        r = self._set("image-cache-dir", str(nas / "cache"))
        assert r.exit_code == 1
        assert "local disk" in r.output
        assert paths.configured_dir("image-cache-dir") is None
        r = self._set("workdirs-dir", str(nas / "wd"))
        assert r.exit_code == 0, r.output

    def test_image_cache_mode(self, home):
        assert self._set("container-image-cache", "off").exit_code == 0
        assert self._set("container-image-cache", "maybe").exit_code == 1
        listing = self._set("list").output
        assert "container-image-cache" in listing
        assert "scratch-dir" in listing
