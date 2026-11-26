"""Configurable locations: NAS-capable workdirs/evidence, local-only scratch
and image cache (pm_core.paths) and their ``pm set`` surface."""

import os

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

    def test_scenario_scratch_stays_trusted(self, home, tmp_path):
        """Scratch used to live inside the QA workdir, which is pm-created
        and trusted; moving it out must not drop that trust (a host-mode
        scenario's test project there would stall at the prompt).  Its
        siblings under the scratch root stay untrusted."""
        from pm_core import workspace_trust
        run = paths.qa_workdirs_root() / "pr-1-abc"
        proj = paths.scenario_scratch_dir(run, 1) / "test-proj"
        proj.mkdir(parents=True)
        assert workspace_trust.approved_path(proj)
        paths.set_global_setting_value("scratch-dir", str(tmp_path / "fast"))
        moved = paths.scenario_scratch_dir(run, 2) / "test-proj"
        assert moved.parent.parent.parent.parent == tmp_path / "fast"
        moved.mkdir(parents=True)
        assert workspace_trust.approved_path(moved)
        # Scenario 1 began before the move: still trusted where it is.
        assert workspace_trust.approved_path(proj)
        other = tmp_path / "fast" / "not-qa"
        other.mkdir()
        assert not workspace_trust.approved_path(other)

    def test_scratch_dir_move_keeps_existing_scenarios_scratch(
            self, home, tmp_path, monkeypatch):
        """Scenario scratch is recomputed, not recorded, so a scratch-dir
        change mid-run must not move a running scenario's scratch: its
        relaunched container would mount (and its prompt name) an empty or
        missing dir.  New scenarios go to the new root; reclaim sees both."""
        from pm_core import storage_reclaim as sr
        run = paths.qa_workdirs_root() / "pr-1-abc"
        old = paths.scenario_scratch_dir(run, 1)
        old.mkdir(parents=True)
        assert paths.qa_scratch_roots() == [home / ".pm" / "scratch" / "qa"]
        paths.set_global_setting_value("scratch-dir", str(tmp_path / "fast"))
        assert paths.qa_scratch_roots() == [tmp_path / "fast" / "qa",
                                            home / ".pm" / "scratch" / "qa"]
        assert paths.scenario_scratch_dir(run, 1) == old
        new = paths.scenario_scratch_dir(run, 2)
        assert new == tmp_path / "fast" / "qa" / "pr-1-abc" / "s-2"
        new.mkdir(parents=True)
        monkeypatch.setattr(sr, "container_mount_sources", lambda: [])
        assert {str(sc) for _, sc in sr.scenario_scratch_dirs("pr-1")} == {
            str(old), str(new)}

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
        assert paths.captures_roots_globs() == ["~/.pm/sessions/*/captures"]
        ev = tmp_path / "my evidence"
        paths.set_global_setting_value("captures-dir", str(ev))
        # The default stays listed: runs begun before the move are there.
        assert paths.captures_roots_globs() == [
            f"'{ev}'/*", "~/.pm/sessions/*/captures"]
        from pm_core.prompt_gen import generate_discovery_supervisor_prompt
        out = generate_discovery_supervisor_prompt(
            {"project": {"name": "demo"}}, session_name="pm-s")
        assert (f"ls -t '{ev}'/*/regression/<id>/*/prompt.md "
                f"~/.pm/sessions/*/captures/regression/<id>/*/prompt.md "
                f"2>/dev/null" in out)

    def test_existing_evidence_is_found_after_captures_dir_moves(
            self, home, nas):
        """Evidence from before captures-dir moved is not migrated: a PR
        that has it keeps using that dir (writers, mounts and host readers
        agree), while a PR without captures starts in the new location."""
        old_root = home / ".pm" / "sessions" / "tag" / "captures"
        (old_root / "pr-old").mkdir(parents=True)
        (old_root / "pr-old" / "report.html").write_text("<html>old</html>")
        paths.set_global_setting_value("captures-dir", str(nas / "ev"))

        assert paths.captures_root("tag") == nas / "ev" / "tag"
        assert paths.captures_roots("tag") == [nas / "ev" / "tag", old_root]
        for resolve in (paths.captures_dir, paths.host_pr_captures_dir):
            assert resolve("pr-old", session_tag="tag") == old_root / "pr-old"
        assert paths.host_pr_captures_dir("pr-new", session_tag="tag") == (
            nas / "ev" / "tag" / "pr-new")
        assert paths.captures_dir("pr-new", session_tag="tag") == (
            nas / "ev" / "tag" / "pr-new")
        # Once the new location holds the PR's dir (moved by hand), it wins.
        (nas / "ev" / "tag" / "pr-old").mkdir()
        assert paths.host_pr_captures_dir("pr-old", session_tag="tag") == (
            nas / "ev" / "tag" / "pr-old")

        # Unset: one root, as before.
        paths.set_global_setting_value("captures-dir", "")
        assert paths.captures_roots("tag") == [old_root]

    def test_recorded_signoff_survives_a_captures_dir_move(self, home, nas,
                                                           monkeypatch):
        """The merge gate re-hashes report.html; after captures-dir moved
        it must still find the approved report, not refuse the merge with
        "report.html changed"."""
        import hashlib
        from pm_core import integration, signoff
        old = home / ".pm" / "sessions" / "tag" / "captures" / "pr-1"
        old.mkdir(parents=True)
        report = old / "report.html"
        report.write_text('<meta name="pm-signoff-verdict" '
                          'content="SIGNOFF_MERGE">')
        monkeypatch.setattr(paths, "_resolve_session_tag",
                            lambda start_path=None: "tag")
        bound = {"head": "HEAD", "base_branch": "master", "base_sha": "B",
                 "candidate_tree": "T", "status": integration.CLEAN}
        pr = {"id": "pr-1", "signoff": {
            "verdict": signoff.SIGNOFF_MERGE, "sha": "HEAD", "ts": "now",
            "origin": "manual", "integration": bound,
            "report_hash": hashlib.sha256(report.read_bytes()).hexdigest()}}
        assert signoff.merge_gate_refusal(pr, "HEAD", "master") is None

        paths.set_global_setting_value("captures-dir", str(nas / "ev"))
        assert signoff.merge_gate_refusal(pr, "HEAD", "master") is None
        assert signoff.report_meta("pr-1") == {"verdict": "SIGNOFF_MERGE"}
        assert integration.integration_json_path("pr-1") == (
            old / "integration.json")
        # An edit is still caught in the old location.
        report.write_text("<html>edited</html>")
        assert "changed since" in signoff.merge_gate_refusal(
            pr, "HEAD", "master")

    def test_dashboard_serves_reports_from_the_old_root(self, tmp_path):
        """The dashboard lists and serves a PR's report from the first
        captures root that holds it."""
        import http.server
        import threading
        import urllib.request
        from pm_core import behavior_report, dashboard_server
        new_root, old_root = tmp_path / "new", tmp_path / "old"
        (new_root / "pr-b").mkdir(parents=True)
        (new_root / "pr-b" / "report.html").write_text("new-b")
        (old_root / "pr-a").mkdir(parents=True)
        (old_root / "pr-a" / "report.html").write_text("old-a")
        (old_root / "pr-a" / "clip.txt").write_text("evidence")
        data = {"prs": [{"id": "pr-a"}, {"id": "pr-b"}, {"id": "pr-c"}]}
        rows = {r.pr_id: r for r in behavior_report.gather_dashboard_rows(
            data, new_root, [old_root])}
        assert rows["pr-a"].has_report and rows["pr-b"].has_report
        assert not rows["pr-c"].has_report

        handler = dashboard_server._make_handler(tmp_path, new_root,
                                                 [old_root])
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            def get(path):
                with urllib.request.urlopen(base + path, timeout=5) as r:
                    return r.read().decode()
            assert get("/pr-a/report.html") == "old-a"
            assert get("/pr-a/clip.txt") == "evidence"
            assert get("/pr-b/report.html") == "new-b"
            with pytest.raises(urllib.error.HTTPError):
                get("/pr-c/report.html")
            # '..' cannot climb out of the roots through the fallback.
            with pytest.raises(urllib.error.HTTPError):
                get("/../old/pr-a/report.html")
        finally:
            httpd.shutdown()
            httpd.server_close()

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
        mi.write_text("1 0 0:1 / / rw - fuse.sshfs host:/ rw\n")
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

    def test_read_mountinfo_fields(self, tmp_path, monkeypatch):
        """The one mountinfo parser (filesystem type, the cache's read-only
        check and reclaim's mount scan all use it): optional fields before
        the separator, escapes, short or separator-less lines."""
        odd = tmp_path / "odd"
        odd.mkdir()
        odd_real = os.path.realpath(odd)
        mi = tmp_path / "mi"
        mi.write_text(
            "1 0 0:1 / / rw,relatime shared:1 master:2 - ext4 /dev/sda rw\n"
            "2 1 0:2 / /var/lib/a\\040b ro,relatime - fuse.x f rw\n"
            "garbage line\n"
            f"3 1 0:3 / {odd_real} rw\n")
        monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
        M = paths.MountEntry
        assert paths.read_mountinfo() == [
            M("/", "rw,relatime", "ext4"),
            M("/var/lib/a b", "ro,relatime", "fuse.x"),
            M(odd_real, "rw", "")]
        assert paths.read_mountinfo(str(tmp_path / "missing")) is None
        # A line without a filesystem type never decides one.
        assert paths.filesystem_type(odd / "x") == "ext4"

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
        assert r.output.strip() == "scratch-dir = ~/.pm/scratch (default)"
        assert paths.scratch_base() == home / ".pm" / "scratch"

    def test_listing_marks_default_locations_once(self, home, tmp_path):
        listing = self._set("list").output.splitlines()
        line = next(ln for ln in listing if ln.split()[0] == "scratch-dir")
        assert line.split()[1:] == ["~/.pm/scratch", "(default)"]
        assert self._set("scratch-dir", str(tmp_path / "fast")).exit_code == 0
        listing = self._set("list").output.splitlines()
        line = next(ln for ln in listing if ln.split()[0] == "scratch-dir")
        assert line.split()[1:] == [str(tmp_path / "fast")]

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
