"""Reclaim disposable container storage left in QA scenario scratch.

Scenario agents run their own container engines (private graphroots) and
sometimes export images (``podman save``) under the scenario's scratch dir.
Those stores outlive the scenario: the audit that motivated the shared image
cache found 1.32 TB of them.  This module removes exactly two kinds of
thing from scenario scratch, and only when nothing can still need them:

* **container stores** — a directory holding ``storage.lock`` plus the
  containers/storage layout (``overlay-layers``, ``vfs-layers``,
  ``overlay-images``, ``vfs-images`` or ``libpod``);
* **image archives** — an uncompressed tar whose members include
  ``manifest.json`` plus ``repositories`` or ``oci-layout``/``index.json``
  (headers only are read).

Everything else in scratch — test projects, drafts, notes, recordings,
investigation artifacts — is kept, as are the checkout and the captures
(evidence) dir, which live elsewhere.

A scratch dir is **held**, and skipped whole, when:

* any existing container (running or stopped, retained or not) mounts it,
  a parent or a child of it — that is the lifecycle's own ownership signal;
* its QA run is live (run record without ``ended_at`` whose driver is
  alive) or resumable (a resume snapshot without ``ended_at``);
* the runtime cannot list containers (fail safe);
* a store has an active mount beneath it in any mount namespace pm can
  see (rootless engines mount their layers in their own namespace).

The callers are the existing lifecycle owners — PR cleanup (merged/closed
PRs, ``pm pr cleanup``), QA run start (earlier runs of the same PR) and
``pm container reclaim`` — so no new scheduler decides when this runs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.storage_reclaim")

RECLAIM_RECORD = ".pm-reclaim.json"
# A store being deleted is first renamed to this prefix, so a deletion cut
# short (process exit, crash) leaves a dir the next pass finishes instead
# of a half-deleted store nothing recognises any more.
CLAIM_PREFIX = ".pm-reclaiming-"
_STORE_MARKERS = ("overlay-layers", "vfs-layers", "overlay-images",
                  "vfs-images", "libpod")
_MIN_ARCHIVE_BYTES = 1 << 20
_MAX_TAR_MEMBERS = 50000


@dataclass
class Disposable:
    path: Path
    kind: str          # "store" | "archive"
    bytes: int | None = None


@dataclass
class ScratchPlan:
    scratch: Path
    run_dir: Path | None
    items: list[Disposable] = field(default_factory=list)
    held: str = ""     # why it is kept whole ("" = reclaimable)


@dataclass
class Outcome:
    plans: list[ScratchPlan] = field(default_factory=list)
    removed: list[Disposable] = field(default_factory=list)
    failed: list[tuple[Disposable, str]] = field(default_factory=list)
    problem: str = ""

    @property
    def removed_bytes(self) -> int:
        return sum(d.bytes or 0 for d in self.removed)

    def summary(self) -> str:
        held = [p for p in self.plans if p.held]
        todo = [d for p in self.plans if not p.held for d in p.items]
        parts = [f"{len(self.removed)} removed ({human_bytes(self.removed_bytes)})"]
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        pending = len(todo) - len(self.removed) - len(self.failed)
        if pending > 0:
            parts.append(f"{pending} planned")
        if held:
            parts.append(f"{len(held)} scratch dir(s) held")
        if self.problem:
            parts.append(f"skipped: {self.problem}")
        return ", ".join(parts)


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{n} B"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def is_container_store(d: Path) -> bool:
    if d.name.startswith(CLAIM_PREFIX):
        return True
    try:
        return ((d / "storage.lock").exists()
                and any((d / m).is_dir() for m in _STORE_MARKERS))
    except OSError:
        return False


def is_image_archive(f: Path) -> bool:
    """An uncompressed docker-archive / OCI-archive tar (headers only)."""
    try:
        if not f.is_file() or f.is_symlink() or f.stat().st_size < _MIN_ARCHIVE_BYTES:
            return False
        with tarfile.open(f, mode="r:") as tf:
            names: set[str] = set()
            for i, member in enumerate(tf):
                if i >= _MAX_TAR_MEMBERS:
                    break
                names.add(member.name.lstrip("./"))
                if "manifest.json" in names and (
                        "repositories" in names or "oci-layout" in names
                        or "index.json" in names):
                    return True
            return ("manifest.json" in names
                    and bool({"repositories", "oci-layout", "index.json"}
                             & names))
    except (OSError, tarfile.TarError, EOFError, ValueError):
        return False


def find_disposables(root: Path) -> list[Disposable]:
    """Container stores and image archives under *root* (not descending
    into stores; unreadable subtrees are skipped)."""
    out: list[Disposable] = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        d = Path(dirpath)
        if d != root and is_container_store(d):
            out.append(Disposable(d, "store"))
            dirnames[:] = []
            continue
        # Never follow symlinks out of scratch.
        dirnames[:] = [n for n in dirnames if not (d / n).is_symlink()]
        for fn in filenames:
            f = d / fn
            if fn.endswith((".tar", ".oci", ".docker")) or "." not in fn:
                if is_image_archive(f):
                    out.append(Disposable(f, "archive"))
    if is_container_store(root):
        out = [Disposable(root, "store")]
    return out


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def _runtime() -> str:
    from pm_core.container import _get_runtime
    return _get_runtime()


def _rt(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    from pm_core.container import _run_runtime
    return _run_runtime(*args, check=False, timeout=timeout)


def container_mount_sources() -> list[str] | None:
    """Host paths mounted into any existing container; None on error."""
    r = _rt("ps", "-a", "--format", "{{.Names}}", timeout=30)
    if r.returncode != 0:
        return None
    names = [n.strip() for n in (r.stdout or "").splitlines() if n.strip()]
    if not names:
        return []
    r = _rt("container", "inspect", "--format",
            '{{range .Mounts}}{{.Source}}{{"\\n"}}{{end}}', *names,
            timeout=60)
    if r.returncode != 0:
        # A container removed between ps and inspect: retry one by one.
        sources: list[str] = []
        for n in names:
            one = _rt("container", "inspect", "--format",
                      '{{range .Mounts}}{{.Source}}{{"\\n"}}{{end}}', n,
                      timeout=30)
            if one.returncode == 0:
                sources += one.stdout.splitlines()
            elif "no such" not in (one.stderr or "").lower():
                return None
        return [s.strip() for s in sources if s.strip()]
    return [s.strip() for s in (r.stdout or "").splitlines() if s.strip()]


def _related(a: str, b: str) -> bool:
    a, b = os.path.realpath(a), os.path.realpath(b)
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _run_held(run_dir: Path | None) -> str:
    if run_dir is None or not run_dir.is_dir():
        return ""
    from pm_core import qa_loop
    rec = qa_loop.read_run_record(run_dir)
    resumable = qa_loop._resume_file_path(run_dir).exists()
    if rec and not rec.get("ended_at"):
        pid = rec.get("owner_pid")
        if pid == os.getpid() or qa_loop.resume_owned_elsewhere(rec):
            return "its QA run is still being driven"
        if resumable:
            return "its QA run can still be resumed"
    elif resumable and not rec:
        return "its QA run can still be resumed"
    return ""


_PROC = "/proc"


def _mount_points() -> list[str]:
    """Mount points in every mount namespace visible from this process.

    A rootless engine mounts its containers' layers inside its own user +
    mount namespace (the pause process's), so a store with running
    containers shows no mounts in this process's ``/proc/self/mountinfo``.
    Read one ``mountinfo`` per distinct mount namespace among the visible
    processes; a namespace counts as read only once one of its tables was
    (a process can exit between the two reads).  A container's namespace
    lists container-internal paths, which never match a host scratch path;
    such containers hold their scratch through their own bind mounts
    (:func:`container_mount_sources`).
    """
    from pm_core import paths
    points: list[str] = []

    def read(table: str) -> bool:
        try:
            lines = Path(table).read_text().splitlines()
        except OSError:
            return False
        for line in lines:
            parts = line.split()
            if len(parts) > 4:
                points.append(paths._unescape_mount_path(parts[4]))
        return True

    read(paths._MOUNTINFO)
    seen: set[str] = set()
    try:
        seen.add(os.readlink(f"{_PROC}/self/ns/mnt"))
    except OSError:
        pass
    try:
        pids = [p for p in os.listdir(_PROC) if p.isdigit()]
    except OSError:
        pids = []
    for pid in pids:
        try:
            ns = os.readlink(f"{_PROC}/{pid}/ns/mnt")
        except OSError:
            continue
        if ns not in seen and read(f"{_PROC}/{pid}/mountinfo"):
            seen.add(ns)
    return points


def _mounts_under(path: Path, mount_points: list[str]) -> bool:
    real = os.path.realpath(path)
    return any(mp == real or mp.startswith(real + "/") for mp in mount_points)


def scenario_scratch_dirs(pr_id: str | None = None,
                          exclude_run: str | None = None
                          ) -> list[tuple[Path | None, Path]]:
    """(run dir, scratch dir) for every scenario of the matching QA runs.

    Covers the legacy ``<run>/s-N/scratch`` and the local
    ``<scratch>/qa/<run>/s-N`` layouts, including scratch whose run dir is
    already gone.  *exclude_run* is a run dir name (``<pr>-<loop>``).
    """
    from pm_core.paths import qa_workdirs_root, scratch_base
    pattern = f"{pr_id}-*" if pr_id else "*"
    qa_root = qa_workdirs_root()
    scratch_qa = scratch_base() / "qa"
    out: list[tuple[Path | None, Path]] = []
    seen: set[str] = set()
    run_names = set()
    for base in (qa_root, scratch_qa):
        if base.is_dir():
            run_names.update(p.name for p in base.glob(pattern) if p.is_dir())
    for run_name in sorted(run_names):
        if exclude_run and run_name == exclude_run:
            continue
        run_dir = qa_root / run_name
        candidates = list((run_dir.glob("s-*/scratch")) if run_dir.is_dir() else [])
        if (scratch_qa / run_name).is_dir():
            candidates += [p for p in (scratch_qa / run_name).glob("s-*")
                           if p.is_dir()]
        for sc in candidates:
            if str(sc) in seen:
                continue
            seen.add(str(sc))
            out.append((run_dir if run_dir.is_dir() else None, sc))
    return out


def plan(pr_id: str | None = None, exclude_run: str | None = None) -> Outcome:
    """What :func:`reclaim` would remove, and what is held (and why)."""
    out = Outcome()
    sources = container_mount_sources()
    if sources is None:
        out.problem = "the container runtime could not list containers"
        return out
    mount_points: list[str] | None = None   # read once, on the first store
    for run_dir, scratch in scenario_scratch_dirs(pr_id, exclude_run):
        p = ScratchPlan(scratch=scratch, run_dir=run_dir)
        held = next((s for s in sources if _related(s, str(scratch))), None)
        if held:
            p.held = f"a container still mounts {held}"
        else:
            p.held = _run_held(run_dir)
        if not p.held:
            p.items = find_disposables(scratch)
            for d in p.items:
                if d.kind != "store":
                    continue
                if mount_points is None:
                    mount_points = _mount_points()
                if _mounts_under(d.path, mount_points):
                    p.held = f"{d.path} has an active mount"
                    break
        out.plans.append(p)
    return out


def _du(path: Path) -> int | None:
    if path.is_file():
        try:
            return path.stat().st_blocks * 512
        except OSError:
            return None
    cmd = ["du", "-sx", "--block-size=1", str(path)]
    if "podman" in _runtime():
        r = _rt("unshare", *cmd, timeout=300)
    else:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    try:
        return int(r.stdout.split()[0])
    except (ValueError, IndexError):
        return None


def _delete(d: Disposable) -> str:
    """Remove *d*; '' on success, else the error."""
    try:
        if d.kind == "archive":
            d.path.unlink()
            return ""
        target = d.path
        claimed = (target if target.name.startswith(CLAIM_PREFIX) else
                   target.with_name(f"{CLAIM_PREFIX}{target.name}-{os.getpid()}"))
        if "podman" in _runtime():
            # Files (and possibly the parent) are owned by sub-UIDs.
            script = ('if [ "$1" != "$2" ]; then mv -- "$1" "$2" || exit 1; '
                      'fi; rm -rf --one-file-system -- "$2"')
            r = _rt("unshare", "sh", "-c", script, "reclaim", str(target),
                    str(claimed), timeout=1800)
            if r.returncode == 0 and not target.exists() and not claimed.exists():
                return ""
            return (r.stderr or "").strip()[:300] or "still present"
        if claimed != target:
            target.rename(claimed)
        shutil.rmtree(claimed, ignore_errors=True)
        return "" if not claimed.exists() else "still present"
    except OSError as exc:
        return str(exc)


def reclaim(pr_id: str | None = None, exclude_run: str | None = None,
            dry_run: bool = False, reason: str = "manual") -> Outcome:
    """Remove the disposables of every unheld scenario scratch dir."""
    out = plan(pr_id, exclude_run)
    for p in out.plans:
        if p.held or not p.items:
            continue
        for d in p.items:
            d.bytes = _du(d.path)
        if dry_run:
            continue
        done: list[Disposable] = []
        for d in p.items:
            err = _delete(d)
            if err:
                out.failed.append((d, err))
                _log.warning("reclaim: could not remove %s: %s", d.path, err)
            else:
                out.removed.append(d)
                done.append(d)
        if done:
            _append_record(p.scratch, done, reason)
    if out.removed or out.failed:
        _log.info("reclaim(%s, %s): %s", pr_id or "*", reason, out.summary())
    return out


def _append_record(scratch: Path, done: list[Disposable], reason: str) -> None:
    rec_path = scratch / RECLAIM_RECORD
    try:
        existing = json.loads(rec_path.read_text())
        if not isinstance(existing, list):
            existing = []
    except (OSError, json.JSONDecodeError):
        existing = []
    existing.append({
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reason": reason,
        "removed": [{"path": str(d.path), "kind": d.kind, "bytes": d.bytes}
                    for d in done],
    })
    try:
        rec_path.write_text(json.dumps(existing, indent=2) + "\n")
    except OSError:
        _log.debug("reclaim: could not write %s", rec_path, exc_info=True)


def reclaim_in_background(pr_id: str, exclude_run: str | None = None,
                          reason: str = "qa-start") -> threading.Thread:
    """Run :func:`reclaim` in a daemon thread (QA start must not wait)."""
    def _run() -> None:
        try:
            reclaim(pr_id, exclude_run=exclude_run, reason=reason)
        except Exception:
            _log.warning("background reclaim for %s failed", pr_id,
                         exc_info=True)
    t = threading.Thread(target=_run, name=f"reclaim-{pr_id}", daemon=True)
    t.start()
    return t
