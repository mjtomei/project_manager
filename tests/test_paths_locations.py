"""Configurable locations: NAS-capable workdirs/evidence, local-only scratch
and image cache (pm_core.paths) and their ``pm set`` surface."""

import os
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

    def test_locks_stay_local_when_workdirs_move(self, home, nas):
        """Cross-process workdir locks never follow the workdirs onto a
        NAS; unset, they stay where they always were."""
        default = home / ".pm" / "workdirs"
        assert paths.workdir_locks_dir() == default
        paths.set_global_setting_value("workdirs-dir", str(nas / "wd"))
        assert paths.workdirs_base() == nas / "wd"
        assert paths.workdir_locks_dir() == default
        assert not paths.is_network_filesystem(paths.workdir_locks_dir())

    def test_workdir_provisioning_lock_stays_local(self, home, nas,
                                                   monkeypatch):
        """_ensure_workdir's per-PR lock sits beside the project's workdirs
        by default and on local disk once workdirs-dir moves them."""
        import fcntl
        from pm_core.cli import helpers
        locked = []
        real_flock = fcntl.flock

        def spy(fd, op):
            if op == fcntl.LOCK_EX:
                locked.append(os.readlink(f"/proc/self/fd/{fd}"))
            return real_flock(fd, op)
        monkeypatch.setattr(fcntl, "flock", spy)
        monkeypatch.setattr(helpers, "_clone_workdir",
                            lambda data, pr, root: "/cloned")
        monkeypatch.setattr(helpers.store, "load", lambda root: {})
        data = {"project": {"name": "proj", "repo_id": "1234abcd99"}}
        assert helpers._ensure_workdir(data, {"id": "pr-1"}, home) == "/cloned"
        paths.set_global_setting_value("workdirs-dir", str(nas / "wd"))
        assert helpers._ensure_workdir(data, {"id": "pr-1"}, home) == "/cloned"
        assert locked == [
            str(home / ".pm" / "workdirs" / "proj-1234abcd" / ".workdir-pr-1.lock"),
            str(home / ".pm" / "workdirs" / "proj-1234abcd" / ".workdir-pr-1.lock"),
        ]
        assert (nas / "wd" / "proj-1234abcd").is_dir()
        assert not list((nas / "wd").rglob("*.lock"))

    def test_old_workdirs_root_stays_pm_created(self, home, nas):
        """Workdirs created before workdirs-dir moved are not migrated, so
        they keep counting as pm's own (workspace trust, PR clones)."""
        from pm_core import workspace_trust
        assert paths.workdirs_roots() == [home / ".pm" / "workdirs"]
        paths.set_global_setting_value("workdirs-dir", str(nas / "wd"))
        assert paths.workdirs_roots() == [nas / "wd", home / ".pm" / "workdirs"]
        old_clone = home / ".pm" / "workdirs" / "proj-1234" / "pm-pr-1"
        old_clone.mkdir(parents=True)
        assert workspace_trust.approved_path(old_clone)
        assert workspace_trust.approved_path(nas / "wd" / "proj-1234")

    def test_qa_runs_in_the_old_root_are_still_found(self, home, nas,
                                                     monkeypatch):
        """A QA run started before workdirs-dir moved stays in the old root
        (nothing is migrated).  Its status, run record, resume snapshot and
        scenario numbers are still found; new runs go to the new root."""
        import json
        from pm_core import qa_loop
        monkeypatch.setattr(qa_loop, "own_session_tag", lambda: None)
        monkeypatch.setattr(qa_loop, "get_pm_session", lambda: None)
        old_qa = home / ".pm" / "workdirs" / "qa"
        old_run = old_qa / "pr-1-aaa"
        (old_run / "s-3").mkdir(parents=True)
        (old_run / "qa_status.json").write_text('{"overall": "PASS"}')
        (old_run / qa_loop._RUN_RECORD).write_text(json.dumps(
            {"pr_id": "pr-1", "loop_id": "aaa", "owner_pid": 1}))
        paths.set_global_setting_value("workdirs-dir", str(nas / "wd"))

        assert paths.qa_workdirs_root() == nas / "wd" / "qa"
        assert paths.qa_workdirs_roots() == [nas / "wd" / "qa", old_qa]
        assert qa_loop.create_qa_workdir("pr-1", "bbb") == (
            nas / "wd" / "qa" / "pr-1-bbb")
        assert paths.latest_qa_status_path("pr-1") == (
            old_run / "qa_status.json")
        assert qa_loop._next_scenario_offset("pr-1", "bbb") == 3
        assert [wd for wd, _ in qa_loop._own_run_records("pr-1")] == [old_run]

        # An instruction run (`pm qa run`) driven from the old root is live.
        cli_run = old_qa / f"pr-1-{qa_loop.instruction_run_loop_id('pr-1')}"
        cli_run.mkdir()
        (cli_run / qa_loop._RUN_RECORD).write_text(json.dumps(
            {"pr_id": "pr-1", "owner_pid": 4242}))
        monkeypatch.setattr(qa_loop, "resume_owned_elsewhere",
                            lambda rec: rec.get("owner_pid") == 4242)
        assert qa_loop.instruction_run_live("pr-1")

    def test_captures_glob_follows_captures_dir(self, home, tmp_path):
        assert paths.captures_roots_glob() == "~/.pm/sessions/*/captures"
        ev = tmp_path / "my evidence"
        paths.set_global_setting_value("captures-dir", str(ev))
        assert paths.captures_roots_glob() == f"'{ev}'/*"
        from pm_core.prompt_gen import generate_discovery_supervisor_prompt
        out = generate_discovery_supervisor_prompt(
            {"project": {"name": "demo"}}, session_name="pm-s")
        assert (f"ls -t '{ev}'/*/regression/<id>/*/prompt.md 2>/dev/null"
                in out)

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
