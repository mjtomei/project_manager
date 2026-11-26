"""Shared, read-only image cache for nested container engines.

Nested rootless podman engines (QA scenario containers, impl/review
containers, a test project's container-mode pm inside them) used to get the
pm-dev image by building it, ``podman save``/``load``-ing it or expanding it
into a private VFS store — 16–19 GB per engine for a ~2 GB image.  This
module prepares the image's unpacked layers **once per image version** on
local disk and lets every engine use them read-only:

* **Entry** — ``<cache>/entries/<key>/`` holds an overlay store (``store/``)
  with exactly one image (all its host tags), mapping probes (``probe/``)
  and ``entry.json``.  ``key`` comes from the image ID, so a rebuilt image
  gets a new entry and tags that share an ID share one.
* **Preparation** — a short-lived prep container is started from the image
  itself with the same ``--userns=keep-id`` and nested-podman flags as
  every consumer, the entry dir mounted where consumers mount it, and the
  host streams ``podman save <ref>`` into ``podman load`` inside it (no
  archive file).  Preparing under the consumers' user namespace is what
  makes the files' ownership right for them.  One ``flock`` per key
  coordinates simultaneous requests from threads and processes.
* **Consumers** — :func:`pm_core.container.create_container` mounts the
  entry read-only at :data:`CONSUMER_MOUNT` and writes the default user's
  ``~/.config/containers/storage.conf`` (overlay, fuse-overlayfs, a private
  writable graphroot on container-local disk, and the store as an
  ``additionalimagestores`` entry).  Rootless podman honours
  ``additionalimagestores`` only from that *user* config (or
  ``--storage-opt``), never from ``/etc/containers/storage.conf``.
* **Depth** — each keep-id level shifts non-root UIDs by one, so an entry is
  valid only for engines at the level it was prepared for.  A pm running
  inside a consumer reuses the entry for the containers it launches (its
  engine is a consumer) but never prepares a deeper one; the mapping probes
  make a mismatched mount fail loudly instead of yielding wrong ownership.

Missing, incompatible or failed caches are launch errors: pm never falls
back to building the image, VFS or host execution while the cache is on.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.image_cache")

# In-container location of the mounted entry (read-only for consumers).
CONSUMER_MOUNT = "/var/lib/pm-image-cache"
CONSUMER_STORE = f"{CONSUMER_MOUNT}/store"
ENTRY_FILE = "entry.json"
# Runtime labels: consumers of an entry, and its prep container.
CACHE_LABEL = "pm.image-cache"
PREP_LABEL = "pm.image-cache-prep"
# Env var naming the mount inside consumers (informational; detection uses
# the fixed path so ``env -i`` shells still find it).
CONSUMER_ENV = "PM_IMAGE_CACHE"

MODE_SETTING = "container-image-cache"
MODES = ("auto", "on", "off")
# Diagnostic/test override of the mode setting.
MODE_ENV = "PM_IMAGE_CACHE_MODE"

FORMAT_VERSION = 1
MOUNT_PROGRAM = "/usr/bin/fuse-overlayfs"
ENGINE_CONFIG_MARK = "# pm-engine-config v1"
PREP_RUNROOT = "/tmp/pm-cache-prep"

LOCK_TIMEOUT = 1800.0   # wait for another process's preparation
PREP_TIMEOUT = 1800     # save | load of one image
_STEP_TIMEOUT = 120
_ABANDONED_PREP_AGE = 3600.0

# Probe files: (name, expected "uid:gid" through `podman unshare stat`).
_PROBES = (("uid0", "0:0"), ("uid1", "1:1"))


class ImageCacheError(RuntimeError):
    """The shared image cache cannot serve this launch (actionable message)."""


def _off_remedy() -> str:
    return (f"or, to launch without the shared cache (each nested engine then "
            f"needs its own copy of the image), run "
            f"'pm set {MODE_SETTING} off'")


# ---------------------------------------------------------------------------
# Mode and roles
# ---------------------------------------------------------------------------

def mode() -> str:
    """The configured cache mode: ``auto`` (default), ``on`` or ``off``."""
    raw = os.environ.get(MODE_ENV, "").strip().lower()
    if not raw:
        from pm_core.paths import get_global_setting_value
        raw = get_global_setting_value(MODE_SETTING, "auto").strip().lower()
    return raw if raw in MODES else "auto"


def in_container() -> bool:
    """True when this process runs inside a podman/docker container."""
    return Path("/run/.containerenv").exists() or Path("/.dockerenv").exists()


def consumer_entry_path() -> Path | None:
    """``entry.json`` of the entry mounted into this container, or None.

    None when no entry is mounted or the cache is turned ``off``.
    """
    if mode() == "off":
        return None
    p = Path(CONSUMER_MOUNT) / ENTRY_FILE
    return p if p.is_file() else None


def is_consumer() -> bool:
    """True inside a container launched with a shared cache entry."""
    return consumer_entry_path() is not None


def read_consumer_entry() -> dict | None:
    p = consumer_entry_path()
    if p is None:
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def provider_enabled(runtime: str, nested_podman: bool) -> bool:
    """Should this pm prepare entries and mount them into containers?

    Only for podman launches that get the nested-podman flags.  ``auto``
    provides on a host (not inside a container); ``on`` provides anywhere.
    Never inside a consumer: the entry would be one keep-id level too deep
    for the containers it launches (see the module docstring).
    """
    if "podman" not in runtime or not nested_podman:
        return False
    m = mode()
    if m == "off" or is_consumer():
        return False
    return m == "on" or not in_container()


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

def cache_root() -> Path:
    """The local cache root (``image-cache-dir`` or ``~/.pm/image-cache``)."""
    from pm_core.paths import (IMAGE_CACHE_DIR_SETTING, NonLocalPathError,
                               configured_dir, pm_home, require_local_path)
    root = configured_dir(IMAGE_CACHE_DIR_SETTING) or (pm_home() / "image-cache")
    try:
        require_local_path(root, "The shared image cache",
                           IMAGE_CACHE_DIR_SETTING)
    except NonLocalPathError as exc:
        raise ImageCacheError(str(exc)) from exc
    (root / "entries").mkdir(parents=True, exist_ok=True)
    (root / "locks").mkdir(parents=True, exist_ok=True)
    return root


def entry_key(image_id: str) -> str:
    """Directory key of the entry for *image_id* (full ID, ``sha256:`` ok)."""
    hexid = image_id.split(":", 1)[-1].strip().lower()
    if len(hexid) < 20 or any(c not in "0123456789abcdef" for c in hexid):
        raise ImageCacheError(f"unexpected image ID {image_id!r}")
    return hexid[:20]


@dataclass
class CacheEntry:
    key: str
    path: Path
    meta: dict = field(default_factory=dict)

    @property
    def image_id(self) -> str:
        return str(self.meta.get("image_id", ""))

    @property
    def names(self) -> list[str]:
        return list(self.meta.get("names") or [])

    @property
    def store(self) -> Path:
        return self.path / "store"


def load_entry(key: str, root: Path | None = None) -> CacheEntry | None:
    """The published entry *key*, or None when absent/incomplete."""
    root = root or cache_root()
    d = root / "entries" / key
    try:
        meta = json.loads((d / ENTRY_FILE).read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if (not isinstance(meta, dict)
            or meta.get("format_version") != FORMAT_VERSION
            or meta.get("key") != key or not (d / "store").is_dir()):
        return None
    return CacheEntry(key=key, path=d, meta=meta)


def list_entries(root: Path | None = None) -> list[CacheEntry]:
    root = root or cache_root()
    out = []
    for d in sorted((root / "entries").iterdir()):
        if d.name.startswith("."):
            continue
        e = load_entry(d.name, root)
        out.append(e or CacheEntry(key=d.name, path=d, meta={}))
    return out


def _runtime() -> str:
    from pm_core.container import _get_runtime
    return _get_runtime()


def _rt(*args: str, timeout: int = _STEP_TIMEOUT,
        check: bool = False) -> subprocess.CompletedProcess:
    from pm_core.container import _run_runtime
    return _run_runtime(*args, check=check, timeout=timeout)


def resolve_image(image_ref: str) -> tuple[str, list[str]]:
    """Return (full image ID, RepoTags) of *image_ref* on this runtime."""
    r = _rt("image", "inspect", image_ref, timeout=30)
    if r.returncode != 0:
        raise ImageCacheError(
            f"image '{image_ref}' is not available to {_runtime()}: "
            f"{(r.stderr or '').strip()[:300]}. Build or pull it first "
            f"('pm container build-base' builds pm-dev:latest), then retry")
    try:
        info = json.loads(r.stdout)[0]
        image_id = str(info["Id"])
        tags = [t for t in (info.get("RepoTags") or []) if t]
    except (ValueError, LookupError, TypeError) as exc:
        raise ImageCacheError(
            f"could not read the ID of image '{image_ref}': {exc}") from exc
    return image_id, tags


def ensure_prepared(image_ref: str) -> CacheEntry:
    """Return the entry for *image_ref*'s current image ID, preparing it once.

    Warm path: one ``image inspect`` and a file read.  Cold path: under the
    per-key lock, re-check, then :func:`_prepare`.  Raises
    :class:`ImageCacheError` with the cause and remedies on any failure.
    """
    from pm_core.store import bounded_flock
    root = cache_root()
    image_id, tags = resolve_image(image_ref)
    key = entry_key(image_id)
    entry = load_entry(key, root)
    if entry and entry.image_id == image_id:
        return entry
    lock = root / "locks" / f"{key}.lock"
    _log.info("image cache: preparing %s (%s) — one-time per image version",
              image_ref, key)
    with bounded_flock(lock, LOCK_TIMEOUT) as got:
        if not got:
            raise ImageCacheError(
                f"timed out after {int(LOCK_TIMEOUT)}s waiting for another "
                f"process to prepare the shared image cache for "
                f"'{image_ref}' (lock {lock}). Check for a stuck "
                f"'pm-image-cache-prep-*' container ({_runtime()} ps -a), "
                f"remove it and retry; " + _off_remedy())
        entry = load_entry(key, root)
        if entry and entry.image_id == image_id:
            return entry
        entry = _prepare(root, image_ref, image_id, tags, key)
    try:
        gc(dry_run=False, protect={key})
    except Exception:
        _log.warning("image cache: eviction after preparing %s failed",
                     key, exc_info=True)
    return entry


def _prep_flags() -> list[str]:
    return ["--root", CONSUMER_STORE,
            "--runroot", PREP_RUNROOT, "--storage-driver", "overlay",
            "--storage-opt", f"overlay.mount_program={MOUNT_PROGRAM}"]


def _prepare(root: Path, image_ref: str, image_id: str, tags: list[str],
             key: str) -> CacheEntry:
    """Build entry *key* in a private dir and publish it with one rename."""
    from pm_core import container as container_mod
    runtime = _runtime()
    if "podman" not in runtime:
        raise ImageCacheError("the shared image cache requires podman")
    entries = root / "entries"
    token = secrets.token_hex(3)
    prep_dir = entries / f".prep-{key}-{os.getpid()}-{token}"
    prep_dir.mkdir(parents=True)
    name = f"pm-image-cache-prep-{key[:12]}-{token}"
    t0 = time.monotonic()
    try:
        # Same user namespace and nested-podman flags as every consumer
        # (create_container), mounted where consumers mount it.
        run = _rt("run", "-d", "--name", name,
                  "--label", f"{PREP_LABEL}={key}",
                  "--userns=keep-id",
                  *container_mod._nested_podman_run_args(),
                  "-v", f"{prep_dir}:{CONSUMER_MOUNT}",
                  image_id, "sleep", "infinity", timeout=_STEP_TIMEOUT)
        if run.returncode != 0:
            raise ImageCacheError(
                f"could not start the cache preparation container from "
                f"'{image_ref}': {(run.stderr or '').strip()[:400]}")
        # Same subuid fit as every consumer (create_container), so the prep
        # engine's user namespace — and so the store's file ownership — is
        # the one consumers at this level get.
        container_mod.fit_subids(name, os.getuid())
        # The whole entry dir is published by one rename once entry.json is
        # written, so a half-loaded store is never mistaken for a usable one.
        flags = _prep_flags()
        _exec_ok(name, ["mkdir", "-p", CONSUMER_STORE,
                        f"{CONSUMER_MOUNT}/probe"], "create the store")
        _stream_load(runtime, image_ref, name, flags)
        loaded = _exec_ok(name, ["podman", *flags, "image", "inspect",
                                 image_id], "inspect the loaded image")
        try:
            info = json.loads(loaded.stdout)[0]
            loaded_id = str(info["Id"])
            names = [t for t in (info.get("RepoTags") or []) if t]
        except (ValueError, LookupError, TypeError) as exc:
            raise ImageCacheError(
                f"could not read the loaded image: {exc}") from exc
        if loaded_id.split(":")[-1] != image_id.split(":")[-1]:
            raise ImageCacheError(
                f"the loaded image ID {loaded_id[:19]} differs from "
                f"{image_ref}'s ID {image_id[:19]} (was the image rebuilt "
                f"during preparation?); retry")
        for tag in tags:
            if tag not in names:
                _exec_ok(name, ["podman", *flags, "tag", image_id, tag],
                         f"tag {tag}")
                names.append(tag)
        probe_cmds = " && ".join(
            [f"cd {CONSUMER_MOUNT}/probe"]
            + [f": > {p} && chown {ids} {p} && chmod 0444 {p}"
               for p, ids in _PROBES])
        _exec_ok(name, ["podman", "unshare", "sh", "-c", probe_cmds],
                 "write the UID/GID mapping probes")
        du = _exec_ok(name, ["podman", "unshare", "du", "-s",
                             "--block-size=1", f"{CONSUMER_MOUNT}/store"],
                      "measure the store")
        try:
            store_bytes = int(du.stdout.split()[0])
        except (ValueError, IndexError):
            store_bytes = None
        ver = _rt("version", "--format", "{{.Client.Version}}", timeout=30)
        meta = {
            "format_version": FORMAT_VERSION,
            "key": key,
            "image_id": image_id,
            "image_ref": image_ref,
            "names": names,
            "runtime": runtime,
            "runtime_version": (ver.stdout or "").strip(),
            "driver": "overlay",
            "mount_program": MOUNT_PROGRAM,
            "userns": "keep-id",
            "consumer_mount": CONSUMER_MOUNT,
            "probes": dict(_PROBES),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "prep_seconds": round(time.monotonic() - t0, 1),
            "store_bytes": store_bytes,
        }
        (prep_dir / ENTRY_FILE).write_text(json.dumps(meta, indent=2) + "\n")
    except BaseException:
        _remove_quietly(name)
        _remove_tree(prep_dir)
        raise
    _remove_quietly(name)
    final = entries / key
    if final.exists():
        # An incomplete/unreadable leftover (load_entry returned None).
        _remove_tree(final)
    os.rename(prep_dir, final)
    _log.info("image cache: prepared %s (%s) in %.1fs, %s bytes", image_ref,
              key, meta["prep_seconds"], meta["store_bytes"])
    return CacheEntry(key=key, path=final, meta=meta)


def _exec_ok(name: str, argv: list[str], what: str,
             timeout: int = _STEP_TIMEOUT) -> subprocess.CompletedProcess:
    r = _rt("exec", name, *argv, timeout=timeout)
    if r.returncode != 0:
        raise ImageCacheError(
            f"cache preparation failed to {what}: "
            f"{(r.stderr or r.stdout or '').strip()[:400]}")
    return r


def _stream_load(runtime: str, image_ref: str, name: str,
                 flags: list[str]) -> None:
    """``<runtime> save image_ref | <runtime> exec -i name podman load``."""
    with tempfile.TemporaryFile() as save_err, \
            tempfile.TemporaryFile() as load_err:
        save = subprocess.Popen([runtime, "save", image_ref],
                                stdout=subprocess.PIPE, stderr=save_err)
        try:
            load = subprocess.Popen(
                [runtime, "exec", "-i", name, "podman", *flags, "load"],
                stdin=save.stdout, stdout=subprocess.DEVNULL,
                stderr=load_err)
        except BaseException:
            save.kill()
            save.wait()
            raise
        assert save.stdout is not None
        save.stdout.close()  # load owns the read end now
        try:
            load_rc = load.wait(timeout=PREP_TIMEOUT)
            save_rc = save.wait(timeout=60)
        except subprocess.TimeoutExpired:
            load.kill()
            save.kill()
            load.wait()
            save.wait()
            raise ImageCacheError(
                f"cache preparation (save | load of '{image_ref}') did not "
                f"finish within {PREP_TIMEOUT}s")
        if save_rc != 0 or load_rc != 0:
            save_err.seek(0)
            load_err.seek(0)
            detail = (save_err.read().decode("utf-8", "replace").strip()
                      or load_err.read().decode("utf-8", "replace").strip())
            raise ImageCacheError(
                f"cache preparation could not copy '{image_ref}' into the "
                f"cache (save rc={save_rc}, load rc={load_rc}): "
                f"{detail[:400]}")


def _remove_quietly(name: str) -> None:
    try:
        from pm_core.container import remove_container
        remove_container(name)
    except Exception:
        _log.warning("image cache: could not remove %s", name, exc_info=True)


def _remove_tree(path: Path) -> bool:
    """Delete *path*, whose files may be owned by sub-UIDs (podman unshare)."""
    if not path.exists():
        return True
    runtime = _runtime()
    if "podman" in runtime:
        r = _rt("unshare", "rm", "-rf", "--one-file-system", str(path),
                timeout=600)
        if r.returncode == 0 and not path.exists():
            return True
    shutil.rmtree(path, ignore_errors=True)
    return not path.exists()


# ---------------------------------------------------------------------------
# Eviction
# ---------------------------------------------------------------------------

def _labelled_keys(label: str) -> set[str] | None:
    """Values of *label* over every container (any state); None on error."""
    r = _rt("ps", "-a", "--filter", f"label={label}", "--format", "json",
            timeout=30)
    if r.returncode != 0:
        return None
    try:
        rows = json.loads(r.stdout or "[]") or []
    except json.JSONDecodeError:
        return None
    keys = set()
    for row in rows:
        labels = row.get("Labels") or {}
        if isinstance(labels, dict) and labels.get(label):
            keys.add(str(labels[label]))
    return keys


def referenced_keys() -> set[str] | None:
    """Keys of entries some container (consumer or prep) still uses."""
    users = _labelled_keys(CACHE_LABEL)
    preps = _labelled_keys(PREP_LABEL)
    if users is None or preps is None:
        return None
    return users | preps


def _image_present(image_id: str) -> bool | None:
    r = _rt("image", "exists", image_id, timeout=30)
    if r.returncode == 0:
        return True
    if r.returncode == 1:
        return False
    return None


def plan_gc(all_unreferenced: bool = False,
            protect: set[str] | None = None) -> tuple[list[tuple[Path, str]], str]:
    """Return ([(path, reason)], problem) for entries safe to delete.

    Never selects an entry a container (any state) references, the
    configured image's entry, or anything when the runtime cannot be
    listed (*problem* then says why).
    """
    root = cache_root()
    refs = referenced_keys()
    if refs is None:
        return [], "the container runtime could not list containers"
    protect = set(protect or ())
    try:
        from pm_core.container import load_container_config
        cfg_id, _ = resolve_image(load_container_config().image)
        protect.add(entry_key(cfg_id))
    except Exception:
        pass
    out: list[tuple[Path, str]] = []
    now = time.time()
    for d in sorted((root / "entries").iterdir()):
        if d.name.startswith(".prep-"):
            key = d.name.split("-")[1] if d.name.count("-") >= 2 else ""
            try:
                age = now - d.stat().st_mtime
            except OSError:
                continue
            if key not in refs and age > _ABANDONED_PREP_AGE:
                out.append((d, "abandoned preparation"))
            continue
        if d.name in refs or d.name in protect:
            continue
        entry = load_entry(d.name, root)
        if entry is None:
            out.append((d, "incomplete entry"))
            continue
        present = _image_present(entry.image_id)
        if present is False:
            out.append((d, "image no longer on the host, no consumers"))
        elif present and all_unreferenced:
            out.append((d, "no consumers (--all-unreferenced)"))
    return out, ""


def gc(dry_run: bool = False, all_unreferenced: bool = False,
       protect: set[str] | None = None) -> dict:
    """Evict unreferenced, stale entries; return a summary."""
    plan, problem = plan_gc(all_unreferenced=all_unreferenced, protect=protect)
    summary = {"removed": [], "failed": [], "planned": [], "problem": problem}
    for path, reason in plan:
        summary["planned"].append((str(path), reason))
        if dry_run:
            continue
        if _remove_tree(path):
            summary["removed"].append((str(path), reason))
            _log.info("image cache: evicted %s (%s)", path, reason)
        else:
            summary["failed"].append((str(path), reason))
    return summary


# ---------------------------------------------------------------------------
# Consumer side
# ---------------------------------------------------------------------------

def consumer_run_args(entry: CacheEntry) -> list[str]:
    """``run`` flags that mount *entry* read-only into a consumer."""
    return ["-v", f"{entry.path}:{CONSUMER_MOUNT}:ro",
            "--label", f"{CACHE_LABEL}={entry.key}",
            "-e", f"{CONSUMER_ENV}={CONSUMER_MOUNT}"]


def _engine_hash(home: str) -> str:
    return hashlib.sha256(home.encode()).hexdigest()[:8]


def engine_config_text(home: str, *, isolated: bool = False,
                       store: str | None = None) -> dict[str, str]:
    """``{filename: text}`` of the containers config for an engine at *home*.

    The default engine keeps podman's default runroot/tmp dir.  An
    *isolated* engine (a second engine in the same container) gets its own
    short runroot and tmp dir so two engines never share runtime state.
    """
    home = home.rstrip("/") or "/"
    store = store or CONSUMER_STORE
    graphroot = f"{home}/.local/share/containers/storage"
    lines = [
        ENGINE_CONFIG_MARK,
        "# Written by pm. Image layers come read-only from the shared,",
        "# host-prepared image cache; this engine's writable layers stay in",
        "# graphroot (local disk). See the Nested Containers QA instruction.",
        "[storage]",
        'driver = "overlay"',
        f'graphroot = "{graphroot}"',
    ]
    files: dict[str, str] = {}
    if isolated:
        base = f"/tmp/pm-eng-{_engine_hash(home)}"
        lines.append(f'runroot = "{base}/run"')
        files["containers.conf"] = "\n".join([
            ENGINE_CONFIG_MARK,
            "# Written by pm: this engine's own runtime tmp dir.",
            "[engine]",
            f'tmp_dir = "{base}/tmp"',
            "",
        ])
    lines += [
        "",
        "[storage.options]",
        f'additionalimagestores = ["{store}"]',
        "",
        "[storage.options.overlay]",
        f'mount_program = "{MOUNT_PROGRAM}"',
        "",
    ]
    files["storage.conf"] = "\n".join(lines)
    return files


def consumer_setup_script(home: str) -> str:
    """Shell step (run in the container's setup) writing the default
    engine's config from :func:`engine_config_text`."""
    d = f"{home}/.config/containers"
    parts = [f"mkdir -p {shlex.quote(d)}"]
    for fname, text in engine_config_text(home).items():
        parts.append(f"printf %s {shlex.quote(text)} > "
                     f"{shlex.quote(d + '/' + fname)}")
    return " && ".join(parts)


def _config_dir(home: str) -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg and home == os.environ.get("HOME"):
        return Path(xdg) / "containers"
    return Path(home) / ".config" / "containers"


def write_engine_config(home: str | None = None, *, force: bool = False,
                        isolated: bool | None = None) -> dict[str, Path]:
    """Write the engine config for *home* (default ``$HOME``) in a consumer.

    *isolated* defaults to True for any home but the container user's own.
    Refuses (``ImageCacheError``) outside a consumer, on a network
    filesystem, or over an existing file pm did not write unless *force*.
    """
    from pm_core.paths import NonLocalPathError, require_local_path
    if not is_consumer():
        raise ImageCacheError(
            f"no shared image cache is mounted here ({CONSUMER_MOUNT}/"
            f"{ENTRY_FILE} missing); this container was launched without "
            f"it. Nothing was written.")
    home = os.path.abspath(home or os.environ.get("HOME") or str(Path.home()))
    if isolated is None:
        from pm_core.container import _CONTAINER_HOME
        isolated = home != _CONTAINER_HOME
    graphroot = Path(home) / ".local" / "share" / "containers" / "storage"
    try:
        require_local_path(graphroot, "Container storage (graphroot)")
    except NonLocalPathError as exc:
        raise ImageCacheError(str(exc)) from exc
    fuse = _fuse_graphroot_problem(graphroot)
    if fuse:
        raise ImageCacheError(fuse)
    cdir = _config_dir(home)
    files = engine_config_text(home, isolated=isolated)
    for fname in files:
        p = cdir / fname
        if p.exists() and not force:
            try:
                ours = p.read_text().startswith(ENGINE_CONFIG_MARK)
            except OSError:
                ours = False
            if not ours:
                raise ImageCacheError(
                    f"{p} exists and was not written by pm; it would hide "
                    f"the shared image store. Rerun with --force to replace "
                    f"it, or add \"{CONSUMER_STORE}\" to its "
                    f"additionalimagestores and set mount_program = "
                    f"\"{MOUNT_PROGRAM}\" yourself.")
    cdir.mkdir(parents=True, exist_ok=True)
    written = {}
    for fname, text in files.items():
        (cdir / fname).write_text(text)
        written[fname] = cdir / fname
    return written


def _fuse_graphroot_problem(graphroot: Path) -> str | None:
    """A graphroot on a FUSE filesystem cannot hold container mounts.

    Inside a container launched from inside another container the root
    filesystem is the parent engine's fuse-overlayfs mount; podman there
    "mounts" containers without invoking the mount program and every
    workload then fails with "executable file not found".  A bind-mounted
    directory (``/scratch``) works.
    """
    from pm_core.paths import filesystem_type
    fstype = filesystem_type(graphroot) or ""
    if fstype == "fuse" or fstype.startswith("fuse."):
        return (f"{graphroot} is on a FUSE filesystem ({fstype}) — this "
                f"container's root filesystem is itself a fuse-overlayfs "
                f"mount, where podman cannot mount containers. Put this "
                f"engine's HOME on a bind-mounted directory such as "
                f"/scratch (HOME=/scratch/engines/<name> pm container "
                f"engine-setup)")
    return None


def engine_config_problem(home: str | None = None) -> str | None:
    """Why *home*'s engine would not see the shared store, or None."""
    home = os.path.abspath(home or os.environ.get("HOME") or str(Path.home()))
    p = _config_dir(home) / "storage.conf"
    try:
        text = p.read_text()
    except FileNotFoundError:
        return (f"{p} is missing, so podman with HOME={home} does not see "
                f"the shared store; run 'pm container engine-setup'")
    except OSError as exc:
        return f"{p} is unreadable: {exc}"
    if CONSUMER_STORE not in text:
        return (f"{p} does not list {CONSUMER_STORE} in "
                f"additionalimagestores; run 'pm container engine-setup "
                f"--force' to replace it")
    if MOUNT_PROGRAM not in text:
        return (f"{p} does not set mount_program = \"{MOUNT_PROGRAM}\"; "
                f"overlay cannot run on this filesystem without it")
    return None


def _mount_options(mount_point: str) -> str | None:
    from pm_core import paths
    try:
        lines = Path(paths._MOUNTINFO).read_text().splitlines()
    except OSError:
        return None
    opts = None
    for line in lines:
        parts = line.split()
        if len(parts) > 5 and paths._unescape_mount_path(parts[4]) == mount_point:
            opts = parts[5]
    return opts


@dataclass
class CheckResult:
    ok: bool
    lines: list[tuple[bool, str]] = field(default_factory=list)

    def add(self, ok: bool, text: str) -> None:
        self.lines.append((ok, text))
        if not ok:
            self.ok = False

    def problems(self) -> list[str]:
        return [t for ok, t in self.lines if not ok]


def consumer_check(image_ref: str | None = None,
                   home: str | None = None) -> CheckResult:
    """Verify the shared cache works for the engine at *home* (in-container).

    Checks the mount (present, read-only), overlay support (``/dev/fuse``,
    fuse-overlayfs), the engine config, graphroot locality, the UID/GID
    mapping probes and that the image is visible read-only.
    """
    from pm_core.paths import NonLocalPathError, require_local_path
    res = CheckResult(ok=True)
    entry = read_consumer_entry()
    if entry is None:
        res.add(False, f"no shared image cache mounted at {CONSUMER_MOUNT} "
                       f"(this container was launched without it, or "
                       f"'{MODE_SETTING}' is off)")
        return res
    res.add(True, f"cache entry {entry.get('key')}: "
                  f"{', '.join(entry.get('names') or []) or entry.get('image_id')}")
    opts = _mount_options(CONSUMER_MOUNT)
    if opts is None:
        res.add(False, f"{CONSUMER_MOUNT} is not a mount point")
    elif "ro" not in opts.split(","):
        res.add(False, f"{CONSUMER_MOUNT} is mounted read-write ({opts}); "
                       f"the shared store must be read-only")
    else:
        res.add(True, f"{CONSUMER_MOUNT} mounted read-only")
    if not Path("/dev/fuse").exists() or not Path(MOUNT_PROGRAM).exists():
        res.add(False, f"overlay support missing (/dev/fuse or "
                       f"{MOUNT_PROGRAM} absent): the container needs the "
                       f"nested_podman flags and an image with fuse-overlayfs")
    else:
        res.add(True, "fuse-overlayfs available")
    home = os.path.abspath(home or os.environ.get("HOME") or str(Path.home()))
    problem = engine_config_problem(home)
    res.add(problem is None, problem or f"engine config for HOME={home} "
                                        f"uses the shared store")
    graphroot = Path(home) / ".local" / "share" / "containers" / "storage"
    try:
        require_local_path(graphroot, "Container storage (graphroot)")
        fuse = _fuse_graphroot_problem(graphroot)
        res.add(fuse is None, fuse or f"graphroot {graphroot} is on local disk")
    except NonLocalPathError as exc:
        res.add(False, str(exc))
    env = {**os.environ, "HOME": home}
    probe_dir = f"{CONSUMER_MOUNT}/probe"
    try:
        r = subprocess.run(
            ["podman", "unshare", "stat", "-c", "%n %u:%g"]
            + [f"{probe_dir}/{p}" for p, _ in _PROBES],
            capture_output=True, text=True, timeout=60, env=env)
        seen = {Path(ln.split()[0]).name: ln.split()[1]
                for ln in r.stdout.splitlines() if len(ln.split()) == 2}
        bad = [f"{p} is {seen.get(p, '?')}, expected {want}"
               for p, want in _PROBES if seen.get(p) != want]
        if r.returncode != 0 or bad:
            res.add(False, "UID/GID mapping does not match the cache: "
                           + ("; ".join(bad) or (r.stderr or "").strip()[:200])
                           + ". The entry was prepared for engines at another "
                             "nesting level; it cannot be used here")
        else:
            res.add(True, "UID/GID mapping matches the cache (probes 0:0, 1:1)")
    except (OSError, subprocess.TimeoutExpired) as exc:
        res.add(False, f"could not run 'podman unshare': {exc}")
    want = image_ref or entry.get("image_id") or ""
    try:
        r = subprocess.run(["podman", "image", "inspect", want],
                           capture_output=True, text=True, timeout=60, env=env)
        if r.returncode != 0:
            res.add(False, f"image '{want}' is not visible to the engine "
                           f"(cache holds {', '.join(entry.get('names') or [])})")
        else:
            iid = str(json.loads(r.stdout)[0].get("Id", ""))
            from_cache = iid.split(":")[-1] == str(entry.get("image_id")).split(":")[-1]
            res.add(from_cache, f"image '{want}' visible"
                    + (" from the shared store" if from_cache else
                       f" but it is {iid[:12]}, not the cached image — a "
                       f"private copy shadows the shared one"))
    except (OSError, subprocess.TimeoutExpired, ValueError, LookupError) as exc:
        res.add(False, f"could not inspect image '{want}': {exc}")
    return res


_checked_homes: set[str] = set()


def ensure_consumer_engine(home: str | None = None) -> None:
    """Make the engine at *home* use the mounted cache (nested pm launches).

    Writes the config when it is missing (never over a foreign one) and
    checks the mapping probes once per home per process.  Raises
    :class:`ImageCacheError` with the fix.
    """
    home = os.path.abspath(home or os.environ.get("HOME") or str(Path.home()))
    if home in _checked_homes:
        return
    p = _config_dir(home) / "storage.conf"
    if not p.exists():
        write_engine_config(home)
    problem = engine_config_problem(home)
    if problem:
        raise ImageCacheError(problem)
    probe_dir = f"{CONSUMER_MOUNT}/probe"
    r = subprocess.run(
        ["podman", "unshare", "stat", "-c", "%u:%g"]
        + [f"{probe_dir}/{p}" for p, _ in _PROBES],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "HOME": home})
    got = r.stdout.split()
    if r.returncode != 0 or got != [want for _, want in _PROBES]:
        raise ImageCacheError(
            f"the shared image cache at {CONSUMER_MOUNT} was prepared for "
            f"engines at another user-namespace level (probes read "
            f"{' '.join(got) or (r.stderr or '').strip()[:200]}, expected "
            f"0:0 1:1); it cannot serve this engine. Launch from a container "
            f"whose cache matches, or " + _off_remedy())
    _checked_homes.add(home)


def missing_in_consumer_message(image_ref: str) -> str:
    entry = read_consumer_entry() or {}
    names = ", ".join(entry.get("names") or []) or entry.get("image_id", "?")
    return (
        f"Image '{image_ref}' is not in the shared image cache mounted at "
        f"{CONSUMER_MOUNT} (it holds {names}). Inside a cache consumer pm "
        f"does not build, pull or import images — that would recreate the "
        f"per-engine copies the cache exists to avoid — and it does not fall "
        f"back to VFS or the host.\n\nTo fix: use one of the cached images "
        f"('pm container set image <name>'), build a small fixture on top of "
        f"one, or have the host prepare this image ('pm container cache "
        f"prepare --image {image_ref}' on the host, then relaunch this "
        f"container); " + _off_remedy() + ".")
