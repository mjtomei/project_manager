"""Tests for pm_core.storage_reclaim — reclaiming scenario engine stores."""

import io
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from pm_core import storage_reclaim as sr


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: h)
    return h


def _store(d: Path, driver: str = "vfs", size: int = 4096) -> Path:
    (d / f"{driver}-layers").mkdir(parents=True)
    (d / f"{driver}-images").mkdir()
    (d / "storage.lock").write_text("")
    (d / driver / "layer1").mkdir(parents=True)
    (d / driver / "layer1" / "blob").write_bytes(b"x" * size)
    return d


def _archive(f: Path, oci: bool = False, size: int = 2 << 20) -> Path:
    f.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(f, "w") as tf:
        data = b"\0" * size
        ti = tarfile.TarInfo("abc/layer.tar")
        ti.size = len(data)
        tf.addfile(ti, io.BytesIO(data))
        for name in (["oci-layout", "index.json"] if oci else
                     ["manifest.json", "repositories"]):
            raw = b"{}"
            ti = tarfile.TarInfo(name)
            ti.size = len(raw)
            tf.addfile(ti, io.BytesIO(raw))
        if oci:
            ti = tarfile.TarInfo("manifest.json")
            ti.size = 2
            tf.addfile(ti, io.BytesIO(b"{}"))
    return f


class FakeRt:
    def __init__(self, mounts=(), fail=False):
        self.mounts = list(mounts)
        self.fail = fail

    def __call__(self, *args, timeout=None):
        if self.fail:
            return SimpleNamespace(returncode=125, stdout="", stderr="down")
        if args[0] == "ps":
            return SimpleNamespace(returncode=0,
                                   stdout="c1\n" if self.mounts else "",
                                   stderr="")
        if args[:2] == ("container", "inspect"):
            return SimpleNamespace(returncode=0,
                                   stdout="\n".join(self.mounts) + "\n",
                                   stderr="")
        raise AssertionError(args)


@pytest.fixture
def rt(monkeypatch):
    fake = FakeRt()
    monkeypatch.setattr(sr, "_rt", fake)
    monkeypatch.setattr(sr, "_runtime", lambda: "docker")  # plain rmtree
    return fake


def _run(home: Path, name: str, idx: int = 1, legacy: bool = False):
    run = home / ".pm" / "workdirs" / "qa" / name
    (run / f"s-{idx}" / "repo").mkdir(parents=True, exist_ok=True)
    if legacy:
        scratch = run / f"s-{idx}" / "scratch"
    else:
        scratch = home / ".pm" / "scratch" / "qa" / name / f"s-{idx}"
    scratch.mkdir(parents=True, exist_ok=True)
    return run, scratch


class TestDetection:
    def test_store_and_archives(self, tmp_path):
        root = tmp_path / "scratch"
        s1 = _store(root / "engines/w1/.local/share/containers/storage")
        s2 = _store(root / "home/.local/share/containers/storage", "overlay")
        a1 = _archive(root / "pm-dev.tar")
        a2 = _archive(root / "export" / "img.oci", oci=True)
        (root / "notes.md").write_text("investigation notes")
        (root / "proj" / ".git").mkdir(parents=True)
        plain = root / "plain.tar"
        with tarfile.open(plain, "w") as tf:
            data = b"y" * (2 << 20)
            ti = tarfile.TarInfo("data.bin")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        found = {(d.kind, d.path) for d in sr.find_disposables(root)}
        assert found == {("store", s1), ("store", s2),
                         ("archive", a1), ("archive", a2)}

    def test_does_not_descend_into_stores(self, tmp_path):
        s = _store(tmp_path / "st")
        _archive(s / "vfs" / "inner.tar")
        assert [d.path for d in sr.find_disposables(tmp_path)] == [s]

    def test_claimed_dir_counts_as_store(self, tmp_path):
        d = tmp_path / f"{sr.CLAIM_PREFIX}storage-123"
        (d / "half").mkdir(parents=True)
        assert [x.path for x in sr.find_disposables(tmp_path)] == [d]

    def test_root_store_is_never_returned(self, tmp_path):
        root = _store(tmp_path / "scratch")
        _archive(root / "pm-dev.tar")
        assert sr.find_disposables(root) == []


class TestPlan:
    def test_finished_run_is_reclaimed_other_files_kept(self, home, rt):
        run, scratch = _run(home, "pr-1-aaa")
        (run / "qa_run.json").write_text(json.dumps(
            {"pr_id": "pr-1", "loop_id": "aaa", "ended_at": 1.0}))
        st = _store(scratch / "eng/.local/share/containers/storage")
        ar = _archive(scratch / "pm-dev.tar")
        (scratch / "draft.md").write_text("keep me")
        out = sr.reclaim("pr-1")
        assert {d.path for d in out.removed} == {st, ar}
        assert not st.exists() and not ar.exists()
        assert (scratch / "draft.md").read_text() == "keep me"
        assert (run / "s-1" / "repo").is_dir()
        rec = json.loads((scratch / sr.RECLAIM_RECORD).read_text())
        assert {r["kind"] for r in rec[0]["removed"]} == {"store", "archive"}

    def test_container_still_mounting_scratch_holds_it(self, home, rt):
        _, scratch = _run(home, "pr-1-bbb")
        st = _store(scratch / "eng")
        rt.mounts = [str(scratch), "/elsewhere"]
        out = sr.reclaim("pr-1")
        assert st.exists() and not out.removed
        assert "still mounts" in out.plans[0].held

    def test_parent_mount_holds_too(self, home, rt):
        _, scratch = _run(home, "pr-1-ccc")
        st = _store(scratch / "eng")
        rt.mounts = [str(scratch.parent)]
        sr.reclaim("pr-1")
        assert st.exists()

    def test_live_run_is_held(self, home, rt):
        run, scratch = _run(home, "pr-1-ddd")
        (run / "qa_run.json").write_text(json.dumps(
            {"pr_id": "pr-1", "loop_id": "ddd", "owner_pid": os.getpid()}))
        st = _store(scratch / "eng")
        out = sr.reclaim("pr-1")
        assert st.exists()
        assert "still being driven" in out.plans[0].held

    def test_resumable_run_is_held(self, home, rt):
        from pm_core import qa_loop
        run, scratch = _run(home, "pr-1-eee")
        (run / "qa_run.json").write_text(json.dumps(
            {"pr_id": "pr-1", "loop_id": "eee", "owner_pid": 999999999}))
        qa_loop._resume_file_path(run).write_text("{}")
        st = _store(scratch / "eng")
        sr.reclaim("pr-1")
        assert st.exists()

    def test_runtime_unavailable_removes_nothing(self, home, rt):
        _, scratch = _run(home, "pr-1-fff")
        st = _store(scratch / "eng")
        rt.fail = True
        out = sr.reclaim("pr-1")
        assert st.exists() and "could not list" in out.problem

    def test_dry_run(self, home, rt):
        _, scratch = _run(home, "pr-1-ggg")
        st = _store(scratch / "eng")
        out = sr.reclaim("pr-1", dry_run=True)
        assert st.exists() and not out.removed
        assert [d.path for d in out.plans[0].items] == [st]

    def test_scope_pr_and_excluded_run(self, home, rt):
        _, mine = _run(home, "pr-1-old")
        _, current = _run(home, "pr-1-new")
        _, other = _run(home, "pr-2-xyz")
        s_mine, s_cur, s_other = (_store(mine / "e"), _store(current / "e"),
                                  _store(other / "e"))
        sr.reclaim("pr-1", exclude_run="pr-1-new")
        assert not s_mine.exists()
        assert s_cur.exists() and s_other.exists()

    def test_scratch_that_is_itself_a_store_is_held(self, home, rt):
        """An engine run with --root on the scratch dir mixes its store
        with the scenario's own files: deleting the dir would take those
        too, so nothing in it is touched."""
        run, scratch = _run(home, "pr-1-root")
        (run / "qa_run.json").write_text(json.dumps(
            {"pr_id": "pr-1", "loop_id": "root", "ended_at": 1.0}))
        _store(scratch)
        (scratch / "draft.md").write_text("keep me")
        ar = _archive(scratch / "proj" / "img.tar")
        out = sr.reclaim("pr-1")
        assert "itself a container store" in out.plans[0].held
        assert out.removed == [] and out.failed == []
        assert scratch.is_dir() and (scratch / "storage.lock").exists()
        assert (scratch / "draft.md").read_text() == "keep me"
        assert ar.exists()

    def test_legacy_and_orphan_scratch(self, home, rt):
        _, legacy = _run(home, "pr-1-leg", legacy=True)
        orphan = home / ".pm" / "scratch" / "qa" / "pr-1-gone" / "s-3"
        orphan.mkdir(parents=True)
        s1, s2 = _store(legacy / "e"), _store(orphan / "e")
        sr.reclaim("pr-1")
        assert not s1.exists() and not s2.exists()

    def test_active_mount_under_store_holds(self, home, rt, tmp_path,
                                            monkeypatch):
        from pm_core import paths
        _, scratch = _run(home, "pr-1-mnt")
        st = _store(scratch / "eng")
        mi = tmp_path / "mountinfo"
        mi.write_text("1 0 0:1 / / rw - ext4 /dev/sda1 rw\n"
                      f"2 1 0:2 / {st}/vfs/x rw - fuse.fuse-overlayfs f rw\n")
        monkeypatch.setattr(paths, "_MOUNTINFO", str(mi))
        out = sr.reclaim("pr-1")
        assert st.exists() and "active mount" in out.plans[0].held

    def test_mount_in_another_namespace_holds(self, home, rt, tmp_path,
                                              monkeypatch):
        """A rootless engine mounts its containers' layers in its own mount
        namespace, invisible in /proc/self/mountinfo: every namespace a
        visible process is in is read — once, from whichever of its
        processes still has a readable table (43 has none here)."""
        from pm_core import paths
        _, scratch = _run(home, "pr-1-ns")
        st = _store(scratch / "eng")
        own = tmp_path / "self-mountinfo"
        own.write_text("1 0 0:1 / / rw - ext4 /dev/sda1 rw\n")
        monkeypatch.setattr(paths, "_MOUNTINFO", str(own))
        proc = tmp_path / "proc"
        for pid, ns in (("self", "mnt:[1]"), ("10", "mnt:[1]"),
                        ("42", "mnt:[2]"), ("43", "mnt:[2]")):
            (proc / pid / "ns").mkdir(parents=True)
            os.symlink(ns, proc / pid / "ns" / "mnt")
        (proc / "42" / "mountinfo").write_text(
            "1 0 0:1 / / rw - ext4 /dev/sda1 rw\n"
            f"9 1 0:9 / {st}/overlay/l1/merged rw - fuse.fuse-overlayfs "
            f"fuse-overlayfs rw\n")
        (proc / "notapid").mkdir()
        monkeypatch.setattr(sr, "_PROC", str(proc))
        points = sr._mount_points()
        assert f"{st}/overlay/l1/merged" in points
        out = sr.reclaim("pr-1")
        assert st.exists() and "active mount" in out.plans[0].held


def test_podman_delete_claims_then_removes_in_unshare(tmp_path, monkeypatch):
    st = _store(tmp_path / "storage")
    calls = []

    def fake_rt(*args, timeout=None):
        calls.append(args)
        import shutil
        shutil.move(args[-2], args[-1])
        shutil.rmtree(args[-1])
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(sr, "_rt", fake_rt)
    monkeypatch.setattr(sr, "_runtime", lambda: "podman")
    assert sr._delete(sr.Disposable(st, "store")) == ""
    (args,) = calls
    assert args[:3] == ("unshare", "sh", "-c")
    assert Path(args[-1]).name.startswith(sr.CLAIM_PREFIX)
    assert not st.exists()


def test_pr_cleanup_reclaims(monkeypatch):
    from pm_core import pr_cleanup
    seen = {}
    monkeypatch.setattr(pr_cleanup, "kill_pr_windows", lambda s, p: [])
    monkeypatch.setattr(pr_cleanup.container_mod, "cleanup_pr_containers",
                        lambda pr_id, session_tag=None: [])
    monkeypatch.setattr(sr, "reclaim",
                        lambda pr_id, **kw: seen.setdefault("sync", pr_id)
                        and sr.Outcome())
    monkeypatch.setattr(sr, "reclaim_in_background",
                        lambda pr_id, **kw: seen.setdefault("bg", pr_id))
    pr = {"id": "pr-9", "title": "t"}
    s = pr_cleanup.cleanup_pr_resources(None, pr)
    assert seen == {"bg": "pr-9"} and s["reclaimed"] == "background"
    s = pr_cleanup.cleanup_pr_resources(None, pr, wait_reclaim=True)
    assert seen["sync"] == "pr-9" and s["reclaimed"] == []
