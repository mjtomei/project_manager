"""Tests for pm_core.image_cache — the shared, read-only image cache.

The container runtime is faked: ``run`` records the prep container's
volume, ``exec`` of ``mkdir`` creates the matching host dirs, and the
``save | load`` stream is a pair of fake processes.  Real-runtime
qualification is recorded in pm/specs/pr-abc1124/qualification.md.
"""

import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from pm_core import image_cache
from pm_core.image_cache import ImageCacheError

IMAGE_ID = "sha256:" + "ab" * 32
KEY = ("ab" * 32)[:20]
_REAL_RT = image_cache._rt   # the `fake` fixture replaces it


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: h)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv(image_cache.MODE_ENV, "")
    return h


def _cp(rc=0, out="", err=""):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


class FakeRuntime:
    """Just enough of podman for a preparation."""

    def __init__(self, image_id=IMAGE_ID, tags=("localhost/pm-dev:latest",),
                 loaded_id=None, refs=(), present=True, fail=None):
        self.image_id = image_id
        self.tags = list(tags)
        self.loaded_id = loaded_id or image_id
        self.refs = set(refs)
        self.present = present
        # Image IDs `image inspect` reports with no tags (superseded by a
        # rebuild of their tag); those in `digested` keep a RepoDigest.
        self.untagged: set[str] = set()
        self.digested: set[str] = set()
        self.fail = fail or {}
        self.calls: list[tuple] = []
        self.volumes: dict[str, str] = {}   # container path -> host path
        self.stale: list[tuple[str, str]] = []  # (prep name, key)
        self.lock = threading.Lock()

    def __call__(self, *args, timeout=None, check=False):
        with self.lock:
            self.calls.append(args)
        head = args[0]
        if head in self.fail:
            return _cp(1, err=self.fail[head])
        if args[:2] == ("image", "inspect"):
            if args[2] in self.untagged:
                digests = ([f"docker.io/x@{args[2]}"]
                           if args[2] in self.digested else [])
                return _cp(out=json.dumps([{"Id": args[2], "RepoTags": [],
                                            "RepoDigests": digests}]))
            return _cp(out=json.dumps([{"Id": self.image_id,
                                        "RepoTags": self.tags}]))
        if args[:2] == ("image", "exists"):
            return _cp(0 if self.present else 1)
        if head == "run":
            v = args[args.index("-v") + 1]
            host, ctr = v.split(":")[:2]
            self.volumes[ctr] = host
            time.sleep(0.05)
            return _cp(out="cid\n")
        if head == "exec":
            argv = list(args[2:])
            if argv[:2] == ["mkdir", "-p"]:
                for p in argv[2:]:
                    Path(self._host(p)).mkdir(parents=True, exist_ok=True)
                return _cp()
            if argv[:1] == ["podman"] and "inspect" in argv:
                return _cp(out=json.dumps([{"Id": self.loaded_id,
                                            "RepoTags": self.tags[:1]}]))
            if argv[:2] == ["podman", "unshare"] and "du" in argv:
                return _cp(out=f"123456\t{argv[-1]}\n")
            return _cp()
        if head == "version":
            return _cp(out="3.4.4\n")
        if head == "ps":
            flt = args[args.index("--filter") + 1].split("=", 1)[1]
            if "=" in flt:  # label=<name>=<key>: names of matching preps
                label, key = flt.split("=", 1)
                return _cp(out="".join(f"{n}\n" for n, k in self.stale
                                       if k == key))
            rows = [{"Labels": {flt: k}} for k in sorted(self.refs)]
            return _cp(out=json.dumps(rows))
        if head == "unshare":
            import shutil
            shutil.rmtree(args[-1], ignore_errors=True)
            return _cp()
        return _cp()

    def _host(self, ctr_path):
        for ctr, host in self.volumes.items():
            if ctr_path == ctr or ctr_path.startswith(ctr + "/"):
                return host + ctr_path[len(ctr):]
        raise AssertionError(f"unmapped path {ctr_path}")

    def count(self, head):
        return sum(1 for c in self.calls if c[0] == head)


class FakeProc:
    def __init__(self, rc=0):
        self.rc = rc
        self.stdout = MagicMock()

    def wait(self, timeout=None):
        return self.rc

    def kill(self):
        pass


@pytest.fixture
def fake(home, monkeypatch):
    rt = FakeRuntime()
    monkeypatch.setattr(image_cache, "_rt", rt)
    monkeypatch.setattr(image_cache, "_runtime", lambda: "podman")
    monkeypatch.setattr("pm_core.container._nested_podman_run_args",
                        lambda: ["--device", "/dev/fuse", "--uts=host"])
    monkeypatch.setattr("pm_core.container.fit_subids", lambda *a: None)
    removed = []
    monkeypatch.setattr("pm_core.container.remove_container",
                        lambda n: removed.append(n))
    rt.removed = removed
    popens = []

    def _popen(argv, **kw):
        popens.append(argv)
        return FakeProc(rt.fail.get("popen:" + argv[1], 0))
    monkeypatch.setattr(image_cache.subprocess, "Popen", _popen)
    rt.popens = popens
    monkeypatch.setattr(
        "pm_core.container.load_container_config",
        lambda: SimpleNamespace(image="pm-dev:latest"))
    return rt


# ---------------------------------------------------------------------------
# Mode and roles
# ---------------------------------------------------------------------------

class TestMode:
    def test_default_is_auto(self, home):
        assert image_cache.mode() == "auto"

    def test_setting_and_env_override(self, home, monkeypatch):
        from pm_core.paths import set_global_setting_value
        set_global_setting_value(image_cache.MODE_SETTING, "off")
        assert image_cache.mode() == "off"
        monkeypatch.setenv(image_cache.MODE_ENV, "on")
        assert image_cache.mode() == "on"

    def test_unknown_value_falls_back_to_auto(self, home):
        from pm_core.paths import set_global_setting_value
        set_global_setting_value(image_cache.MODE_SETTING, "maybe")
        assert image_cache.mode() == "auto"


class TestProviderEnabled:
    @pytest.mark.parametrize("runtime,nested,mode,in_ctr,consumer,want", [
        ("podman", True, "auto", False, False, True),    # host default
        ("podman", True, "auto", True, False, False),    # inside a container
        ("podman", True, "on", True, False, True),       # forced
        ("podman", True, "off", False, False, False),
        ("podman", False, "on", False, False, False),    # no nested podman
        ("docker", True, "on", False, False, False),     # podman only
        ("podman", True, "on", True, True, False),       # never one level deeper
    ])
    def test_matrix(self, home, monkeypatch, runtime, nested, mode, in_ctr,
                    consumer, want):
        monkeypatch.setenv(image_cache.MODE_ENV, mode)
        monkeypatch.setattr(image_cache, "in_container", lambda: in_ctr)
        monkeypatch.setattr(image_cache, "is_consumer", lambda: consumer)
        assert image_cache.provider_enabled(runtime, nested) is want


def test_entry_key_rejects_garbage():
    assert image_cache.entry_key(IMAGE_ID) == KEY
    assert image_cache.entry_key("AB" * 32) == KEY
    with pytest.raises(ImageCacheError):
        image_cache.entry_key("sha256:xyz")


# ---------------------------------------------------------------------------
# Preparation
# ---------------------------------------------------------------------------

class TestEnsurePrepared:
    def test_cold_prepare_publishes_entry(self, fake, home):
        entry = image_cache.ensure_prepared("pm-dev:latest")
        root = home / ".pm" / "image-cache"
        assert entry.path == root / "entries" / KEY
        assert (entry.path / "store").is_dir()
        assert (entry.path / "probe").is_dir()
        meta = json.loads((entry.path / "entry.json").read_text())
        assert meta["image_id"] == IMAGE_ID
        assert meta["names"] == ["localhost/pm-dev:latest"]
        assert meta["store_bytes"] == 123456
        assert meta["format_version"] == image_cache.FORMAT_VERSION
        # No half-built dirs left behind.
        assert [p.name for p in (root / "entries").iterdir()] == [KEY]

    def test_prep_container_matches_consumers(self, fake, home):
        """Same user namespace + nested flags + mount path as consumers, so
        the store's ownership is what consumers' engines expect."""
        image_cache.ensure_prepared("pm-dev:latest")
        run = next(c for c in fake.calls if c[0] == "run")
        assert "--userns=keep-id" in run
        assert "--uts=host" in run and "/dev/fuse" in run
        v = run[run.index("-v") + 1]
        assert v.endswith(":" + image_cache.CONSUMER_MOUNT)
        assert f"{image_cache.PREP_LABEL}={KEY}" in run
        assert fake.removed and fake.removed[0].startswith(
            "pm-image-cache-prep-")

    def test_streams_save_into_load_without_an_archive(self, fake, home):
        image_cache.ensure_prepared("pm-dev:latest")
        save, load = fake.popens
        assert save == ["podman", "save", "pm-dev:latest"]
        assert load[:4] == ["podman", "exec", "-i", load[3]]
        assert load[-1] == "load"
        assert f"overlay.mount_program={image_cache.MOUNT_PROGRAM}" in load
        assert "--root" in load and image_cache.CONSUMER_STORE in load

    def test_probes_written_in_the_engine_namespace(self, fake, home):
        image_cache.ensure_prepared("pm-dev:latest")
        probe = next(c for c in fake.calls if c[0] == "exec"
                     and "unshare" in c and "sh" in c)
        script = probe[-1]
        assert "chown 0:0 uid0" in script and "chown 1:1 uid1" in script

    def test_every_host_tag_is_applied(self, fake, home):
        fake.tags = ["localhost/pm-dev:latest", "localhost/pm-dev:qa"]
        entry = image_cache.ensure_prepared("pm-dev:latest")
        tags = [c for c in fake.calls if c[0] == "exec" and "tag" in c]
        assert len(tags) == 1 and tags[0][-1] == "localhost/pm-dev:qa"
        assert entry.names == ["localhost/pm-dev:latest",
                               "localhost/pm-dev:qa"]

    def test_warm_path_prepares_nothing(self, fake, home):
        image_cache.ensure_prepared("pm-dev:latest")
        runs = fake.count("run")
        again = image_cache.ensure_prepared("pm-dev:latest")
        assert again.key == KEY
        assert fake.count("run") == runs
        assert len(fake.popens) == 2

    def test_new_image_version_gets_its_own_entry(self, fake, home):
        first = image_cache.ensure_prepared("pm-dev:latest")
        fake.image_id = fake.loaded_id = "sha256:" + "cd" * 32
        second = image_cache.ensure_prepared("pm-dev:latest")
        assert first.key != second.key
        assert first.path.is_dir() and second.path.is_dir()

    def test_concurrent_requests_prepare_once(self, fake, home):
        results, errors = [], []

        def go():
            try:
                results.append(image_cache.ensure_prepared("pm-dev:latest"))
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)
        threads = [threading.Thread(target=go) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert {r.key for r in results} == {KEY}
        assert fake.count("run") == 1

    def test_lock_timeout_is_actionable(self, fake, home, monkeypatch):
        from contextlib import contextmanager

        @contextmanager
        def never(path, timeout):
            yield False
        monkeypatch.setattr("pm_core.store.bounded_flock", never)
        with pytest.raises(ImageCacheError) as exc:
            image_cache.ensure_prepared("pm-dev:latest")
        assert "pm-image-cache-prep" in str(exc.value)
        assert f"pm set {image_cache.MODE_SETTING} off" in str(exc.value)

    def test_unwritable_cache_dir_is_actionable(self, fake, home, tmp_path):
        """image-cache-dir on a path pm cannot create (an SSD not mounted
        yet): the cache's own error naming the setting — not a bare
        PermissionError, which launchers report as 'is podman running?'."""
        from pm_core.paths import (IMAGE_CACHE_DIR_SETTING,
                                   set_global_setting_value)
        ro = tmp_path / "ro"
        ro.mkdir()
        set_global_setting_value(IMAGE_CACHE_DIR_SETTING, str(ro / "cache"))
        ro.chmod(0o555)
        try:
            if os.access(ro, os.W_OK):   # root ignores the mode
                pytest.skip("running with CAP_DAC_OVERRIDE")
            with pytest.raises(ImageCacheError) as exc:
                image_cache.ensure_prepared("pm-dev:latest")
        finally:
            ro.chmod(0o755)
        msg = str(exc.value)
        assert str(ro / "cache") in msg
        assert f"pm set {IMAGE_CACHE_DIR_SETTING} <path>" in msg
        assert f"pm set {image_cache.MODE_SETTING} off" in msg
        assert fake.count("run") == 0

    def test_failed_publish_is_actionable_and_leaves_nothing(
            self, fake, home, monkeypatch):
        real_rename = os.rename

        def rename(src, dst):
            if Path(dst).name == KEY:
                raise OSError(28, "No space left on device")
            return real_rename(src, dst)
        monkeypatch.setattr(image_cache.os, "rename", rename)
        with pytest.raises(ImageCacheError, match="No space left"):
            image_cache.ensure_prepared("pm-dev:latest")
        entries = home / ".pm" / "image-cache" / "entries"
        assert list(entries.iterdir()) == []
        assert fake.removed   # the prep container too

    def test_missing_image_is_actionable(self, fake, home):
        fake.fail["image"] = "no such image"
        with pytest.raises(ImageCacheError) as exc:
            image_cache.ensure_prepared("pm-dev:latest")
        assert "pm container build-base" in str(exc.value)

    def test_hung_runtime_step_is_an_image_cache_error(self, fake, home,
                                                       monkeypatch):
        """A hung podman step comes back as an actionable ImageCacheError
        (create_container turns it into ContainerError), not a raw
        TimeoutExpired, and the partial entry is removed."""
        import subprocess

        def run_runtime(*args, check=False, timeout=None):
            if args[0] == "run":
                raise subprocess.TimeoutExpired(["podman", *args], timeout)
            return fake(*args, timeout=timeout)
        monkeypatch.setattr(image_cache, "_rt", _REAL_RT)
        monkeypatch.setattr("pm_core.container._run_runtime", run_runtime)
        with pytest.raises(ImageCacheError, match="did not finish within"):
            image_cache.ensure_prepared("pm-dev:latest")
        entries = home / ".pm" / "image-cache" / "entries"
        assert list(entries.iterdir()) == []

    def test_missing_runtime_is_an_image_cache_error(self, fake, home,
                                                     monkeypatch):
        def run_runtime(*args, check=False, timeout=None):
            raise FileNotFoundError(2, "No such file or directory: 'podman'")
        monkeypatch.setattr(image_cache, "_rt", _REAL_RT)
        monkeypatch.setattr("pm_core.container._run_runtime", run_runtime)
        with pytest.raises(ImageCacheError, match="could not run podman"):
            image_cache.ensure_prepared("pm-dev:latest")
        # Eviction cannot tell what is referenced: nothing selected.
        assert image_cache.plan_gc()[1]

    def test_failed_load_cleans_up(self, fake, home):
        fake.fail["popen:exec"] = 125
        with pytest.raises(ImageCacheError) as exc:
            image_cache.ensure_prepared("pm-dev:latest")
        assert "load rc=125" in str(exc.value)
        entries = home / ".pm" / "image-cache" / "entries"
        assert list(entries.iterdir()) == []
        assert fake.removed  # prep container removed

    def test_killed_preparer_leftovers_are_cleared(self, fake, home):
        """A preparer killed mid-way leaves its prep container and dir; the
        next preparation (holding the key's lock) removes both."""
        root = image_cache.cache_root()
        leftover = root / "entries" / f".prep-{KEY}-4242-abcdef"
        (leftover / "store").mkdir(parents=True)
        fake.stale = [(f"pm-image-cache-prep-{KEY[:12]}-abcdef", KEY)]
        image_cache.ensure_prepared("pm-dev:latest")
        assert f"pm-image-cache-prep-{KEY[:12]}-abcdef" in fake.removed
        assert not leftover.exists()
        assert [p.name for p in (root / "entries").iterdir()] == [KEY]

    def test_id_mismatch_aborts(self, fake, home):
        fake.loaded_id = "sha256:" + "ef" * 32
        with pytest.raises(ImageCacheError, match="rebuilt during preparation"):
            image_cache.ensure_prepared("pm-dev:latest")
        assert list((home / ".pm" / "image-cache" / "entries").iterdir()) == []

    def test_cache_root_on_network_storage_is_refused(self, fake, home,
                                                      tmp_path, monkeypatch):
        from pm_core import paths
        nas = tmp_path / "nas"
        nas.mkdir()
        paths.set_global_setting_value("image-cache-dir", str(nas / "cache"))
        mi = tmp_path / "mountinfo"
        mi.write_text("1 0 0:1 / / rw - ext4 /dev/sda1 rw\n"
                      f"2 1 0:2 / {nas} rw - cifs //nas/share rw\n")
        monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
        with pytest.raises(ImageCacheError) as exc:
            image_cache.ensure_prepared("pm-dev:latest")
        assert "image-cache-dir" in str(exc.value)
        assert fake.count("run") == 0


# ---------------------------------------------------------------------------
# Eviction
# ---------------------------------------------------------------------------

def _publish(root: Path, key: str, image_id: str) -> Path:
    d = root / "entries" / key
    (d / "store").mkdir(parents=True)
    (d / "entry.json").write_text(json.dumps({
        "format_version": image_cache.FORMAT_VERSION, "key": key,
        "image_id": image_id, "names": []}))
    return d


class TestGc:
    def test_keeps_referenced_configured_and_present(self, fake, home):
        root = image_cache.cache_root()
        configured = _publish(root, KEY, IMAGE_ID)       # configured image
        used = _publish(root, "1" * 20, "sha256:" + "1" * 64)
        gone = _publish(root, "2" * 20, "sha256:" + "2" * 64)
        fake.refs = {"1" * 20}
        fake.present = False
        out = image_cache.gc()
        assert configured.exists() and used.exists()
        assert not gone.exists()
        assert [r for _, r in out["removed"]] == [
            "image no longer on the host, no consumers"]

    def test_present_image_kept_unless_all_unreferenced(self, fake, home):
        root = image_cache.cache_root()
        other = _publish(root, "3" * 20, "sha256:" + "3" * 64)
        fake.present = True
        image_cache.gc()
        assert other.exists()
        image_cache.gc(all_unreferenced=True)
        assert not other.exists()

    def test_superseded_image_is_evicted_unless_referenced(self, fake, home):
        """A rebuild of pm-dev:latest leaves the old image on the host,
        untagged, until the host's images are pruned (verified with podman
        3.4: `image exists` rc 0, RepoTags/RepoDigests empty).  Its entry
        goes once no container uses it; a referenced one stays."""
        root = image_cache.cache_root()
        old_id, used_id = "sha256:" + "7" * 64, "sha256:" + "8" * 64
        old = _publish(root, "7" * 20, old_id)
        used = _publish(root, "8" * 20, used_id)
        fake.untagged = {old_id, used_id}
        fake.refs = {"8" * 20}
        out = image_cache.gc()
        assert not old.exists() and used.exists()
        assert [r for _, r in out["removed"]] == [
            "image superseded (untagged on the host), no consumers"]

    def test_image_named_only_by_digest_is_kept(self, fake, home):
        """Pulled by digest: no tag, but a RepoDigest still selects it."""
        root = image_cache.cache_root()
        pinned_id = "sha256:" + "9" * 64
        pinned = _publish(root, "9" * 20, pinned_id)
        fake.untagged = fake.digested = {pinned_id}
        image_cache.gc()
        assert pinned.exists()

    def test_dry_run_and_runtime_failure_remove_nothing(self, fake, home):
        root = image_cache.cache_root()
        gone = _publish(root, "4" * 20, "sha256:" + "4" * 64)
        fake.present = False
        out = image_cache.gc(dry_run=True)
        assert gone.exists() and out["planned"]
        fake.fail["ps"] = "runtime down"
        out = image_cache.gc()
        assert gone.exists()
        assert "could not list" in out["problem"]

    def test_abandoned_prep_dirs(self, fake, home):
        root = image_cache.cache_root()
        old = root / "entries" / f".prep-{'5' * 20}-1-aa"
        fresh = root / "entries" / f".prep-{'6' * 20}-2-bb"
        old.mkdir()
        fresh.mkdir()
        past = time.time() - 2 * image_cache._ABANDONED_PREP_AGE
        os.utime(old, (past, past))
        image_cache.gc()
        assert not old.exists() and fresh.exists()


# ---------------------------------------------------------------------------
# Consumer side
# ---------------------------------------------------------------------------

class TestEngineConfig:
    def test_default_engine(self):
        files = image_cache.engine_config_text("/home/pm")
        assert set(files) == {"storage.conf"}
        text = files["storage.conf"]
        assert text.startswith(image_cache.ENGINE_CONFIG_MARK)
        assert 'graphroot = "/home/pm/.local/share/containers/storage"' in text
        assert f'additionalimagestores = ["{image_cache.CONSUMER_STORE}"]' in text
        assert f'mount_program = "{image_cache.MOUNT_PROGRAM}"' in text
        assert "runroot" not in text
        assert "vfs" not in text

    def test_isolated_engines_get_their_own_short_runtime_dirs(self):
        a = image_cache.engine_config_text("/scratch/engines/w1", isolated=True)
        b = image_cache.engine_config_text("/scratch/engines/w2", isolated=True)
        ra = [ln for ln in a["storage.conf"].splitlines() if "runroot" in ln][0]
        rb = [ln for ln in b["storage.conf"].splitlines() if "runroot" in ln][0]
        assert ra != rb
        # podman rejects runroots over 50 characters.
        assert len(ra.split('"')[1]) <= 50
        assert "tmp_dir" in a["containers.conf"]

    def test_setup_script_writes_the_files(self, tmp_path):
        import subprocess
        home = tmp_path / "pmhome"
        script = image_cache.consumer_setup_script(str(home))
        subprocess.run(["sh", "-c", script], check=True)
        written = (home / ".config/containers/storage.conf").read_text()
        assert written == image_cache.engine_config_text(str(home))["storage.conf"]


@pytest.fixture
def consumer(tmp_path, monkeypatch, home):
    """A fake consumer mount (entry.json + probes) at a temp path."""
    mount = tmp_path / "pm-image-cache"
    (mount / "store").mkdir(parents=True)
    (mount / "probe").mkdir()
    (mount / "entry.json").write_text(json.dumps({
        "key": KEY, "image_id": IMAGE_ID,
        "names": ["localhost/pm-dev:latest"]}))
    monkeypatch.setattr(image_cache, "CONSUMER_MOUNT", str(mount))
    monkeypatch.setattr(image_cache, "CONSUMER_STORE", str(mount / "store"))
    monkeypatch.setattr(image_cache, "overlay_support_problem", lambda: None)
    image_cache._checked_homes.clear()
    return mount


class TestWriteEngineConfig:
    def test_outside_a_consumer_writes_nothing(self, home):
        with pytest.raises(ImageCacheError, match="launched without it"):
            image_cache.write_engine_config(str(home))
        assert not (home / ".config").exists()

    def test_writes_isolated_config(self, consumer, tmp_path):
        eng = tmp_path / "w1"
        written = image_cache.write_engine_config(str(eng))
        assert set(written) == {"storage.conf", "containers.conf"}
        assert image_cache.engine_config_problem(str(eng)) is None

    def test_refuses_foreign_config_without_force(self, consumer, tmp_path):
        eng = tmp_path / "w2"
        cfg = eng / ".config" / "containers" / "storage.conf"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('[storage]\ndriver = "vfs"\n')
        with pytest.raises(ImageCacheError, match="--force"):
            image_cache.write_engine_config(str(eng))
        assert "vfs" in cfg.read_text()
        image_cache.write_engine_config(str(eng), force=True)
        assert "vfs" not in cfg.read_text()

    def test_foreign_containers_conf_names_the_tmp_dir_it_needs(
            self, consumer, tmp_path):
        # A scenario's own containers.conf (its network mode) has nothing
        # to do with the image store: the refusal says what this file
        # needs, and nothing is written over it.
        eng = tmp_path / "w4"
        cfg = eng / ".config" / "containers" / "containers.conf"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('[network]\nnetwork_backend = "cni"\n'
                       '[engine]\nnetwork_cmd_options = []\n')
        with pytest.raises(ImageCacheError) as exc:
            image_cache.write_engine_config(str(eng))
        msg = str(exc.value)
        tmp_dir = image_cache.engine_config_text(
            str(eng), isolated=True)["containers.conf"].split(
                'tmp_dir = "')[1].split('"')[0]
        assert f'tmp_dir = "{tmp_dir}"' in msg and "[engine]" in msg
        assert "--force" in msg
        assert "additionalimagestores" not in msg
        assert "network_backend" in cfg.read_text()
        assert not (cfg.parent / "storage.conf").exists()

    def test_refuses_a_fuse_graphroot(self, consumer, tmp_path, monkeypatch):
        from pm_core import paths
        mi = tmp_path / "mountinfo"
        mi.write_text("1 0 0:1 / / rw - fuse.fuse-overlayfs fuse-overlayfs rw\n")
        monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
        with pytest.raises(ImageCacheError, match="/scratch"):
            image_cache.write_engine_config(str(tmp_path / "w3"))


class TestEnsureConsumerEngine:
    def _unshare(self, monkeypatch, owners, rc=0):
        """Fake ``podman unshare stat -c '%n %u:%g' <probes>``: one line per
        probe argument, its owner taken from *owners* in order."""
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            out = "".join(f"{path} {ids}\n"
                          for path, ids in zip(argv[5:], owners))
            return _cp(rc, out=out)
        monkeypatch.setattr(image_cache.subprocess, "run", run)
        return calls

    def test_matching_probes_pass_once(self, consumer, tmp_path, monkeypatch):
        calls = self._unshare(monkeypatch, ["0:0", "1:1"])
        eng = str(tmp_path / "nested-home")
        image_cache.ensure_consumer_engine(eng)
        image_cache.ensure_consumer_engine(eng)
        assert len(calls) == 1
        assert (Path(eng) / ".config/containers/storage.conf").exists()

    def test_shifted_probes_fail_loudly(self, consumer, tmp_path, monkeypatch):
        """An entry mounted one keep-id level too deep reads 0:0 / 0:0 or
        65534 — never used with wrong ownership."""
        self._unshare(monkeypatch, ["0:0", "65534:65534"])
        with pytest.raises(ImageCacheError, match="another user-namespace "
                           "level .uid1 is 65534:65534, expected 1:1"):
            image_cache.ensure_consumer_engine(str(tmp_path / "h"))

    def test_unreadable_probes_are_an_actionable_error(self, consumer,
                                                       tmp_path, monkeypatch):
        """No podman (or a hung one) is a launch error naming the cause,
        not an uncaught OSError out of create_container."""
        def run(argv, **kw):
            raise FileNotFoundError(2, "No such file", "podman")
        monkeypatch.setattr(image_cache.subprocess, "run", run)
        with pytest.raises(ImageCacheError, match="could not run 'podman "
                           "unshare'"):
            image_cache.ensure_consumer_engine(str(tmp_path / "h4"))
        res = image_cache.consumer_check(home=str(tmp_path / "h4"))
        assert not res.ok
        assert any("could not run 'podman unshare'" in t
                   for t in res.problems())

    def test_existing_config_on_a_fuse_graphroot_fails_the_launch(
            self, consumer, tmp_path, monkeypatch):
        """The default engine's config always exists (create_container
        writes it), so the FUSE check must not depend on writing one: on a
        consumer's fuse-overlayfs root filesystem a nested launch would
        otherwise fail later with "executable file not found"."""
        from pm_core import paths
        calls = self._unshare(monkeypatch, ["0:0", "1:1"])
        eng = str(tmp_path / "default-home")
        (Path(eng) / ".config" / "containers").mkdir(parents=True)
        for fname, text in image_cache.engine_config_text(eng).items():
            (Path(eng) / ".config" / "containers" / fname).write_text(text)
        mi = tmp_path / "mountinfo"
        mi.write_text("1 0 0:1 / / rw - fuse.fuse-overlayfs fuse-overlayfs rw\n")
        monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
        with pytest.raises(ImageCacheError, match="FUSE filesystem .*/scratch"):
            image_cache.ensure_consumer_engine(eng)
        assert calls == [] and eng not in image_cache._checked_homes
        res = image_cache.consumer_check(home=eng)
        assert any("FUSE filesystem" in t for t in res.problems())

    def test_foreign_config_without_store_is_refused(self, consumer, tmp_path,
                                                     monkeypatch):
        self._unshare(monkeypatch, ["0:0", "1:1"])
        eng = tmp_path / "h2"
        cfg = eng / ".config" / "containers" / "storage.conf"
        cfg.parent.mkdir(parents=True)
        cfg.write_text('[storage]\ndriver = "overlay"\n')
        with pytest.raises(ImageCacheError, match="additionalimagestores") as exc:
            image_cache.ensure_consumer_engine(str(eng))
        # The foreign config may be deliberate: the cache can be turned off.
        assert f"pm set {image_cache.MODE_SETTING} off" in str(exc.value)
        assert "storage.conf" in cfg.name and "overlay" in cfg.read_text()


class TestStatusLine:
    """``pm container status``'s cache line — a lookup, never a prepare."""

    def test_provider_shows_the_configured_image_entry(self, fake, home,
                                                      monkeypatch):
        monkeypatch.setattr(image_cache, "in_container", lambda: False)
        line = image_cache.status_line("pm-dev:latest", "podman", True)
        assert line.startswith("auto — no entry for pm-dev:latest")
        assert "pm container cache prepare" in line
        _publish(image_cache.cache_root(), KEY, IMAGE_ID)
        line = image_cache.status_line("pm-dev:latest", "podman", True)
        assert line.startswith(f"auto — entry {KEY} for pm-dev:latest")
        assert fake.count("run") == 0 and not fake.popens

    def test_unavailable_image_is_reported(self, fake, home, monkeypatch):
        monkeypatch.setattr(image_cache, "in_container", lambda: False)
        fake.fail["image"] = "no such image"
        line = image_cache.status_line("pm-dev:latest", "podman", True)
        assert "not available" in line and "no such image" in line

    @pytest.mark.parametrize("mode,runtime,nested,in_ctr,want", [
        ("off", "podman", True, False, "off"),
        ("auto", "docker", True, False, "needs podman"),
        ("auto", "podman", False, False, "needs podman"),
        ("auto", "podman", True, True, "from inside a container"),
    ])
    def test_why_it_is_not_used(self, home, monkeypatch, mode, runtime,
                                nested, in_ctr, want):
        monkeypatch.setenv(image_cache.MODE_ENV, mode)
        monkeypatch.setattr(image_cache, "in_container", lambda: in_ctr)
        assert want in image_cache.status_line("pm-dev:latest", runtime,
                                               nested)

    def test_consumer_names_the_mounted_entry(self, consumer):
        line = image_cache.status_line("pm-dev:latest", "podman", True)
        assert line == f"auto (consumer of {KEY}: localhost/pm-dev:latest)"


def test_mount_options_reads_the_topmost_mount(consumer, tmp_path,
                                               monkeypatch):
    from pm_core import paths
    mi = tmp_path / "mountinfo"
    mi.write_text("1 0 0:1 / / rw - ext4 /dev/sda1 rw\n"
                  f"2 1 0:2 / {consumer} rw,relatime - ext4 /dev/sda1 rw\n"
                  f"3 2 0:2 / {consumer} ro,relatime - ext4 /dev/sda1 rw\n")
    monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
    assert image_cache._mount_options(str(consumer)) == "ro,relatime"
    assert image_cache._mount_options("/elsewhere") is None


def test_missing_in_consumer_message_names_the_cache(consumer):
    msg = image_cache.missing_in_consumer_message("pm-dev:other")
    assert "localhost/pm-dev:latest" in msg
    assert "does not build, pull or import" in msg
    assert "VFS" in msg and "host" in msg
    assert f"pm set {image_cache.MODE_SETTING} off" in msg
    # The host remedy must change what this container is launched from:
    # a relaunch mounts the entry of the host's configured image only, so
    # merely preparing another image there would change nothing here.
    assert "pm container set image pm-dev:other" in msg
    assert "cache prepare --image" not in msg


def test_missing_overlay_support_fails_the_nested_launch(consumer, tmp_path,
                                                        monkeypatch):
    monkeypatch.setattr(image_cache, "overlay_support_problem",
                        lambda: "overlay support is unavailable (/dev/fuse missing)")
    with pytest.raises(ImageCacheError, match="/dev/fuse"):
        image_cache.ensure_consumer_engine(str(tmp_path / "h3"))


def test_overlay_support_problem_names_what_is_missing(monkeypatch):
    real_exists = Path.exists
    monkeypatch.setattr(Path, "exists",
                        lambda self: False if str(self) == "/dev/fuse"
                        else real_exists(self))
    msg = image_cache.overlay_support_problem()
    assert msg and "/dev/fuse" in msg and "VFS" in msg


class TestCli:
    """``pm container cache …`` and ``pm container engine-setup``."""

    @pytest.fixture(autouse=True)
    def _not_a_consumer(self, tmp_path, monkeypatch):
        # Hermetic when the suite itself runs inside a cache consumer; the
        # `consumer` fixture, set up after this one, mounts a fake entry.
        monkeypatch.setattr(image_cache, "CONSUMER_MOUNT",
                            str(tmp_path / "no-cache-mounted"))

    def _invoke(self, *args):
        from click.testing import CliRunner
        from pm_core.cli import cli
        return CliRunner().invoke(cli, ["container", *args])

    def test_gc_dry_run_lists_without_removing(self, fake, home):
        root = image_cache.cache_root()
        gone = _publish(root, "2" * 20, "sha256:" + "2" * 64)
        fake.present = False
        r = self._invoke("cache", "gc", "--dry-run")
        assert r.exit_code == 0, r.output
        assert f"would remove: {gone} (image no longer on the host" in r.output
        assert gone.exists()
        r = self._invoke("cache", "gc")
        assert r.exit_code == 0, r.output
        assert f"removed: {gone}" in r.output and not gone.exists()
        assert "Nothing to remove." in self._invoke("cache", "gc").output

    def test_gc_with_runtime_down_removes_nothing(self, fake, home):
        root = image_cache.cache_root()
        gone = _publish(root, "2" * 20, "sha256:" + "2" * 64)
        fake.present = False
        fake.fail["ps"] = "cannot connect"
        r = self._invoke("cache", "gc")
        assert r.exit_code == 1
        assert "Nothing removed: the container runtime could not list" \
            in r.output
        assert gone.exists()

    def test_status_lists_entries_and_use(self, fake, home):
        root = image_cache.cache_root()
        _publish(root, KEY, IMAGE_ID)
        _publish(root, "1" * 20, "sha256:" + "1" * 64)
        fake.refs = {KEY}
        r = self._invoke("cache", "status")
        assert r.exit_code == 0, r.output
        assert f"Root: {root}" in r.output
        assert f"{KEY}" in r.output and "[in use]" in r.output
        assert "[unused]" in r.output

    def test_engine_setup_outside_a_consumer_fails(self, home):
        r = self._invoke("engine-setup")
        assert r.exit_code == 1
        assert "launched without it" in r.output
        assert not (home / ".config").exists()

    def test_prepare_refused_inside_a_consumer(self, consumer, fake):
        r = self._invoke("cache", "prepare")
        assert r.exit_code == 1
        assert "prepare entries on the host" in r.output
        assert fake.count("run") == 0

    def test_prepare_error_is_reported(self, fake, home):
        fake.fail["image"] = "no such image"
        r = self._invoke("cache", "prepare", "--image", "pm-dev:latest")
        assert r.exit_code == 1
        assert "pm container build-base" in r.output
