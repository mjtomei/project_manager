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

import contextlib
import hashlib
import json
import os
import re
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
    try:
        (root / "entries").mkdir(parents=True, exist_ok=True)
        (root / "locks").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        # e.g. image-cache-dir names a local SSD that is not mounted yet.
        raise ImageCacheError(
            f"the shared image cache cannot be created at {root}: {exc}. "
            f"Make it writable, or set '{IMAGE_CACHE_DIR_SETTING}' to a "
            f"writable local directory (pm set {IMAGE_CACHE_DIR_SETTING} "
            f"<path>), then retry; " + _off_remedy()) from exc
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


def _rt(*args: str, timeout: int = _STEP_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a runtime command, never raising for a runtime that is missing
    (rc 127) or hung (rc 124): every caller's failure path then applies —
    an actionable :class:`ImageCacheError` (which ``create_container``
    turns into ``ContainerError``), or "cannot tell" in eviction."""
    from pm_core.container import _run_runtime
    try:
        return _run_runtime(*args, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args, 124, "", f"'{_runtime()} {args[0]}' did not finish "
                           f"within {timeout}s")
    except OSError as exc:
        return subprocess.CompletedProcess(
            args, 127, "", f"could not run {_runtime()}: {exc}")


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
    try:
        with bounded_flock(lock, LOCK_TIMEOUT) as got:
            if not got:
                raise ImageCacheError(
                    f"timed out after {int(LOCK_TIMEOUT)}s waiting for "
                    f"another process to prepare the shared image cache for "
                    f"'{image_ref}' (lock {lock}). Check for a stuck "
                    f"'pm-image-cache-prep-*' container ({_runtime()} ps "
                    f"-a), remove it and retry; " + _off_remedy())
            entry = load_entry(key, root)
            if entry and entry.image_id == image_id:
                return entry   # another process prepared it while we waited
            entry = _prepare(root, image_ref, image_id, tags, key)
    except OSError as exc:
        # The lock file, the prep dir, entry.json or the publishing rename
        # (a full disk, a permission change): still the cache's actionable
        # error, never a bare traceback that callers would report as a
        # runtime failure.
        raise ImageCacheError(
            f"preparing the shared image cache for '{image_ref}' under "
            f"{root} failed: {exc}. Fix the cause and retry; "
            + _off_remedy()) from exc
    try:
        gc(dry_run=False, protect={key})
    except Exception:
        _log.warning("image cache: eviction after preparing %s failed",
                     key, exc_info=True)
    return entry


def status_line(image_ref: str, runtime: str, nested_podman: bool) -> str:
    """The ``Image cache:`` line of ``pm container status``.

    The mode, plus whichever applies here: the mounted entry (inside a
    consumer), why the cache is not used, or the entry for *image_ref*
    on a provider (only looked up: this never prepares anything).
    """
    m = mode()
    if m == "off":
        return "off"
    consumer = read_consumer_entry()
    if consumer:
        return (f"{m} (consumer of {consumer.get('key')}: "
                f"{', '.join(consumer.get('names') or [])})")
    if "podman" not in runtime or not nested_podman:
        return f"{m} (not used: needs podman and a nested_podman project)"
    if not provider_enabled(runtime, nested_podman):
        return f"{m} (not provided from inside a container; 'on' forces it)"
    try:
        image_id, _ = resolve_image(image_ref)
        entry = load_entry(entry_key(image_id))
    except ImageCacheError as exc:
        return f"{m} — {exc}"
    if entry is None:
        # podman reports a bare hex ID (docker prefixes "sha256:"); show
        # the 12-digit short ID that `podman images` and the consumer's
        # missing-image error use.
        short_id = image_id.removeprefix("sha256:")[:12]
        return (f"{m} — no entry for {image_ref} ({short_id}) yet; the "
                f"next launch prepares it, or run 'pm container cache "
                f"prepare'")
    size = entry.meta.get("store_bytes")
    size_s = f", {size / 1e9:.2f} GB" if isinstance(size, int) else ""
    return (f"{m} — entry {entry.key} for {image_ref} (prepared "
            f"{entry.meta.get('created_at') or '?'}{size_s})")


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
    _clear_stale_preps(entries, key)
    final = entries / key
    if final.exists():
        # An unusable leftover (load_entry returned None) that this
        # preparation would replace — never while a container mounts it.
        _refuse_replacing_used_entry(final, key, image_ref)
    _log.info("image cache: preparing %s (%s) — one-time per image version",
              image_ref, key)
    token = secrets.token_hex(3)
    prep_dir = entries / f".prep-{key}-{os.getpid()}-{token}"
    prep_dir.mkdir(parents=True)
    name = f"pm-image-cache-prep-{key[:12]}-{token}"
    t0 = time.monotonic()
    try:
        # Same user namespace and nested-podman flags as every consumer
        # (create_container), mounted where consumers mount it.
        # ``sleep infinity`` is the container's PID 1, which ignores
        # SIGTERM: without --stop-timeout 0 every ``rm -f`` of this
        # container (publish, failure cleanup, a waiter clearing a killed
        # preparer's leftover) waits podman's 10 s stop timeout before the
        # SIGKILL, with the per-key lock held and every launch waiting.
        run = _rt("run", "-d", "--name", name,
                  "--label", f"{PREP_LABEL}={key}",
                  "--stop-timeout", "0",
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
        # ``save`` resolved *image_ref* when it started, which may be after
        # it was rebuilt or retagged (since resolve_image above): then the
        # store holds another image ID, and inspecting it by *image_id*
        # would only say "image not known".  Read which ID was loaded.
        listed = _exec_ok(name, ["podman", *flags, "images", "--all",
                                 "--quiet", "--no-trunc"],
                          "list the loaded image")
        loaded_ids = [i.split(":")[-1] for i in listed.stdout.split()]
        if loaded_ids and image_id.split(":")[-1] not in loaded_ids:
            raise ImageCacheError(_rebuilt_message(
                loaded_ids[0], image_ref, image_id))
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
            raise ImageCacheError(_rebuilt_message(loaded_id, image_ref,
                                                   image_id))
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
        du = _exec_ok(name, ["podman", "unshare", "du", "-sx",
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
    try:
        if final.exists():
            # The unusable leftover checked above: no container uses it.
            _remove_tree(final)
        os.rename(prep_dir, final)
    except OSError:
        _remove_tree(prep_dir)
        raise
    _log.info("image cache: prepared %s (%s) in %.1fs, %s bytes", image_ref,
              key, meta["prep_seconds"], meta["store_bytes"])
    return CacheEntry(key=key, path=final, meta=meta)


def _rebuilt_message(loaded_id: str, image_ref: str, image_id: str) -> str:
    loaded_id = loaded_id.split(":")[-1]
    image_id = image_id.split(":")[-1]
    return (f"the loaded image ID {loaded_id[:12]} differs from "
            f"{image_ref}'s ID {image_id[:12]} when this preparation "
            f"started: '{image_ref}' was rebuilt or retagged during "
            f"preparation, and nothing was published. Retry (launch again "
            f"or run 'pm container cache prepare'): the next preparation "
            f"copies its current image")


def _entry_users(key: str) -> list[str] | None:
    """Names of the containers (any state) launched from entry *key*;
    None when the runtime cannot list them."""
    r = _rt("ps", "-a", "--filter", f"label={CACHE_LABEL}={key}",
            "--format", "{{.Names}}", timeout=30)
    if r.returncode != 0:
        return None
    return (r.stdout or "").split()


def _refuse_replacing_used_entry(final: Path, key: str,
                                 image_ref: str) -> None:
    """Raise unless no container uses the unusable entry dir *final*.

    Every consumer bind-mounts its entry's directory itself, so deleting
    it to publish a fresh one empties the store under each consumer's
    nested engine — its images and running containers break, with no
    message — while the fresh entry, a new directory, never reaches them.
    """
    users = _entry_users(key)
    if users == []:
        return
    what = (f"the shared image cache entry {key} for '{image_ref}' at "
            f"{final} is unusable (its {ENTRY_FILE} is missing, unreadable "
            f"or from another pm version)")
    if users is None:
        raise ImageCacheError(
            f"{what}, and the containers that may still use it could not "
            f"be listed, so pm will not replace it: deleting a store a "
            f"container has mounted breaks the images and containers "
            f"inside it. Check '{_runtime()} ps -a --filter "
            f"label={CACHE_LABEL}={key}', then retry; " + _off_remedy())
    shown = ", ".join(users[:5]) + (f" and {len(users) - 5} more"
                                    if len(users) > 5 else "")
    raise ImageCacheError(
        f"{what}, but {len(users)} container(s) launched from it still "
        f"mount it: {shown}. pm will not replace it while they do: "
        f"deleting it breaks the images and containers inside them. Once "
        f"their work is done, remove them ('{_runtime()} rm -f <name>') "
        f"and retry, and the next launch prepares a fresh entry; "
        + _off_remedy())


def _clear_stale_preps(entries: Path, key: str) -> None:
    """Remove prep containers and dirs of *key* left by a killed preparer.

    Called with the key's lock held, so no other preparation of *key* can
    be running: anything still carrying its prep label or name is stale.
    """
    r = _rt("ps", "-a", "--filter", f"label={PREP_LABEL}={key}",
            "--format", "{{.Names}}", timeout=30)
    for stale in (r.stdout or "").split() if r.returncode == 0 else []:
        _log.info("image cache: removing stale prep container %s", stale)
        _remove_quietly(stale)
    for d in entries.glob(f".prep-{key}-*"):
        _remove_tree(d)


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
            # A dead load makes save fail with SIGPIPE (rc 141): report the
            # side that failed first.
            src = load_err if load_rc != 0 else save_err
            src.seek(0)
            detail = _podman_error(src.read().decode("utf-8", "replace"))
            msg = (f"cache preparation could not copy '{image_ref}' into "
                   f"the cache (save rc={save_rc}, load rc={load_rc}): "
                   f"{detail[:400]}")
            if load_rc in (126, 127):
                # ``exec … podman load`` found no runnable podman in the
                # image itself: no retry or prepare can fix that.
                msg = (msg.rstrip(".") + ". '" + image_ref + "' has no "
                       "podman, so it cannot run nested podman or serve "
                       "the shared cache: choose an image that has one "
                       "('pm container set image <image>'; 'pm container "
                       "build-base' builds pm-dev:latest)")
            raise ImageCacheError(msg)


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


def _image_state(image_id: str) -> str | None:
    """How the host runtime holds *image_id*: ``"absent"``, ``"untagged"``
    (still stored, but no tag or digest names it — what a rebuild of its
    tag leaves behind until the host's images are pruned), ``"named"``, or
    None when the runtime cannot tell."""
    r = _rt("image", "exists", image_id, timeout=30)
    if r.returncode == 1:
        return "absent"
    if r.returncode != 0:
        return None
    r = _rt("image", "inspect", image_id, timeout=30)
    if r.returncode != 0:
        return None
    try:
        info = json.loads(r.stdout)[0]
    except (ValueError, LookupError, TypeError):
        return None
    if not isinstance(info, dict):
        return None
    return "named" if (info.get("RepoTags") or info.get("RepoDigests")) \
        else "untagged"


def plan_gc(all_unreferenced: bool = False,
            protect: set[str] | None = None) -> tuple[list[tuple[Path, str]], str]:
    """Return ([(path, reason)], problem) for entries safe to delete.

    Selects unreferenced entries whose image is gone from the host or
    superseded (untagged: its tag was rebuilt), all unreferenced ones with
    *all_unreferenced*, and abandoned preparations; in cache roots an
    earlier ``image-cache-dir`` named (:func:`_earlier_cache_roots`), every
    unreferenced entry older than an hour.  Never selects an entry a
    container (any state) references, the configured image's entry in the
    current root, or anything when the runtime cannot be listed (*problem*
    then says why).
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
    for r in [root] + _earlier_cache_roots(root):
        try:
            dirs = sorted((r / "entries").iterdir())
        except OSError:
            continue
        for d in dirs:
            reason = _gc_reason(d, r == root, refs, protect, now,
                                all_unreferenced)
            if reason:
                out.append((d, reason))
    return out, ""


def _earlier_cache_roots(current: Path) -> list[Path]:
    """Cache roots ``image-cache-dir`` named before, and the default, that
    still hold entries.  No launch prepares or mounts from them any more,
    so their unreferenced entries are evicted whatever their image's state
    (their files are sub-UID owned: hard to delete by hand)."""
    from pm_core.paths import IMAGE_CACHE_DIR_SETTING, earlier_dirs, pm_home
    # Compared by real path: an earlier spelling of the current root (a
    # symlink to it, or a value with '..') is the current root, whose
    # configured image's entry gc must keep.
    seen = {os.path.realpath(current)}
    out: list[Path] = []
    for d in earlier_dirs(IMAGE_CACHE_DIR_SETTING) + [pm_home() / "image-cache"]:
        real = os.path.realpath(d)
        if real not in seen and (d / "entries").is_dir():
            seen.add(real)
            out.append(d)
    return out


def _gc_reason(d: Path, current: bool, refs: set[str], protect: set[str],
               now: float, all_unreferenced: bool) -> str | None:
    """Why :func:`plan_gc` evicts the entry or prep dir *d*, or None."""
    try:
        age = now - d.stat().st_mtime
    except OSError:
        return None
    if d.name.startswith(".prep-"):
        key = d.name.split("-")[1] if d.name.count("-") >= 2 else ""
        if key not in refs and age > _ABANDONED_PREP_AGE:
            return "abandoned preparation"
        return None
    if d.name in refs:
        return None
    if not current:
        # Not within the hour: a preparer that resolved the cache root
        # before the setting changed may have just published it there and
        # not yet launched the container that mounts it.
        if age > _ABANDONED_PREP_AGE:
            return "left in an earlier image-cache-dir, no consumers"
        return None
    if d.name in protect:
        return None
    entry = load_entry(d.name, d.parent.parent)
    if entry is None:
        return "incomplete entry"
    state = _image_state(entry.image_id)
    if state == "absent":
        return "image no longer on the host, no consumers"
    if state == "untagged":
        # Superseded: its tag now names a rebuilt image, so no launch by
        # tag can select it again.  The host keeps the old image until its
        # images are pruned, which pm never does; without this, every
        # rebuild of pm-dev left a full entry behind.
        return "image superseded (untagged on the host), no consumers"
    if state == "named" and all_unreferenced:
        return "no consumers (--all-unreferenced)"
    return None


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


def _graphroot(home: str) -> Path:
    """The private writable graphroot of the engine at *home* (the one
    :func:`engine_config_text` configures)."""
    return Path(home) / ".local" / "share" / "containers" / "storage"


def engine_config_text(home: str, *, isolated: bool = False
                       ) -> dict[str, str]:
    """``{filename: text}`` of the containers config for an engine at *home*.

    The default engine keeps podman's default runroot/tmp dir.  An
    *isolated* engine (a second engine in the same container) gets its own
    short runroot and tmp dir so two engines never share runtime state.
    """
    home = home.rstrip("/") or "/"
    graphroot = _graphroot(home)
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
        f'additionalimagestores = ["{CONSUMER_STORE}"]',
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
                        isolated: bool | None = None,
                        kept: list[Path] | None = None) -> dict[str, Path]:
    """Write the engine config for *home* (default ``$HOME``) in a consumer.

    *isolated* defaults to True for any home but the container user's own.
    Refuses (``ImageCacheError``) outside a consumer, on a network or FUSE
    filesystem, or over an existing file pm did not write unless *force* —
    except that such a file which already has everything this engine needs
    (what the refusal asks to add) is kept as it is and appended to *kept*.
    Returns the files written.
    """
    if not is_consumer():
        raise ImageCacheError(
            f"no shared image cache is mounted here ({CONSUMER_MOUNT}/"
            f"{ENTRY_FILE} missing); this container was launched without "
            f"it. Nothing was written.")
    home = os.path.abspath(home or os.environ.get("HOME") or str(Path.home()))
    if isolated is None:
        isolated = _is_isolated(home)
    problem = _graphroot_problem(home)
    if problem:
        raise ImageCacheError(problem)
    cdir = _config_dir(home)
    files = engine_config_text(home, isolated=isolated)
    keep: list[Path] = []
    for fname in files:
        p = cdir / fname
        if p.exists() and not force:
            try:
                ours = p.read_text().startswith(ENGINE_CONFIG_MARK)
            except OSError:
                ours = False
            if ours:
                continue
            # The user followed the refusal's advice by hand: keep their
            # file (and its other settings) rather than ask again for what
            # it already has.
            if _foreign_config_complete(fname, home, isolated):
                keep.append(p)
                continue
            raise ImageCacheError(_foreign_config_message(
                p, fname, home, isolated=isolated))
    cdir.mkdir(parents=True, exist_ok=True)
    written = {}
    for fname, text in files.items():
        if cdir / fname in keep:
            continue
        (cdir / fname).write_text(text)
        written[fname] = cdir / fname
    if kept is not None:
        kept.extend(keep)
    return written


def _foreign_config_complete(fname: str, home: str, isolated: bool) -> bool:
    """Whether *home*'s *fname*, a file pm did not write, already has what
    :func:`_foreign_config_message` asks it to add."""
    if fname == "storage.conf":
        return engine_config_problem(home) is None
    return not isolated or _configured_tmp_dir(home) is not None


def _is_isolated(home: str) -> bool:
    """An engine at any HOME but the container user's own is a second
    engine in this container: it needs its own runroot and tmp dir."""
    from pm_core.container import _CONTAINER_HOME
    return home != _CONTAINER_HOME


def _isolated_runroot(home: str) -> str:
    return f"/tmp/pm-eng-{_engine_hash(home)}/run"


def _foreign_config_message(path: Path, fname: str, home: str, *,
                            isolated: bool = True) -> str:
    """Why :func:`write_engine_config` will not replace *path*, and what to
    add to it instead — specific to the file, since a scenario's own
    ``containers.conf`` (e.g. its network mode) has nothing to do with the
    image store."""
    if fname == "storage.conf":
        why = "it would hide the shared image store"
        if isolated:
            # Without its own runroot a second engine shares podman's
            # default one, and the engines' container mount records then
            # overwrite each other (exec into the other's containers fails).
            add = (f"add \"{CONSUMER_STORE}\" to its additionalimagestores, "
                   f"set mount_program = \"{MOUNT_PROGRAM}\" and give it "
                   f"its own runroot = \"{_isolated_runroot(home)}\" under "
                   f"[storage]")
        else:
            add = (f"add \"{CONSUMER_STORE}\" to its additionalimagestores "
                   f"and set mount_program = \"{MOUNT_PROGRAM}\"")
    else:
        why = ("this engine needs its own runtime tmp dir, so it does not "
               "share runtime state with another engine in this container")
        add = (f"add tmp_dir = \"/tmp/pm-eng-{_engine_hash(home)}/tmp\" "
               f"under its [engine] table")
    return (f"{path} exists and was not written by pm; {why}. Either {add} "
            f"yourself, or rerun with --force to replace it (its other "
            f"settings are then lost).")


def overlay_support_problem() -> str | None:
    """Why engines here cannot mount overlay layers, or None."""
    missing = [p for p in ("/dev/fuse", MOUNT_PROGRAM) if not Path(p).exists()]
    if not missing:
        return None
    return (f"overlay support is unavailable in this container "
            f"({' and '.join(missing)} missing), so an engine here cannot "
            f"mount the shared image's layers. Relaunch the container from a "
            f"project with 'nested_podman: true' (which passes /dev/fuse) and "
            f"an image that ships fuse-overlayfs. pm does not fall back to VFS")


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


def _graphroot_problem(home: str) -> str | None:
    """Why the graphroot of the engine at *home* cannot hold its
    containers — network storage, or a FUSE filesystem — or None."""
    from pm_core.paths import NonLocalPathError, require_local_path
    graphroot = _graphroot(home)
    try:
        require_local_path(graphroot, "Container storage (graphroot)")
    except NonLocalPathError as exc:
        return str(exc)
    return _fuse_graphroot_problem(graphroot)


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
    if _is_isolated(home) and not re.search(r"^\s*runroot\s*=", text, re.M):
        return (f"{p} sets no runroot, so this engine shares podman's default "
                f"runtime dir with the other engines in this container and "
                f"their container mount records overwrite each other; add "
                f"runroot = \"{_isolated_runroot(home)}\" under its [storage] "
                f"table, or run 'pm container engine-setup --force' to "
                f"replace it")
    return None


def _db_path(home: str) -> Path:
    """The libpod state database of the engine at *home* (podman 3.x)."""
    return _graphroot(home) / "libpod" / "bolt_state.db"


def _configured_value(home: str, fname: str, key: str) -> str | None:
    """The string *key* in *home*'s containers config file *fname*, or
    None."""
    try:
        text = (_config_dir(home) / fname).read_text()
    except OSError:
        return None
    # A TOML basic ("...") or literal ('...') string.
    m = re.search(rf"""^\s*{key}\s*=\s*(?:"([^"]+)"|'([^']+)')""", text,
                  re.M)
    return (m.group(1) or m.group(2)) if m else None


def _configured_runroot(home: str) -> str | None:
    """The runroot *home*'s storage.conf sets, or None."""
    return _configured_value(home, "storage.conf", "runroot")


def _configured_tmp_dir(home: str) -> str | None:
    """The tmp_dir *home*'s containers.conf sets, or None."""
    return _configured_value(home, "containers.conf", "tmp_dir")


def _podman_out(home: str, *args: str) -> str | None:
    """stdout of ``podman <args>`` run with HOME=*home*, None on failure."""
    try:
        r = subprocess.run(["podman", *args], capture_output=True, text=True,
                           timeout=60, env={**os.environ, "HOME": home})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _engine_runtime_dirs(home: str) -> tuple[str, str | None] | None:
    """``(runroot, tmp dir)`` podman with HOME=*home* uses, or None when
    podman fails.  ``podman info`` reports only the runroot; the tmp dir
    comes from its debug log ("Using tmp dir ..."), None if absent."""
    try:
        r = subprocess.run(
            ["podman", "info", "--format", "{{.Store.RunRoot}}",
             "--log-level=debug"],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HOME": home})
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    tmp = re.findall(r'msg="Using tmp dir ([^"]+)"', r.stderr or "")
    return (r.stdout or "").strip(), (tmp[-1] if tmp else None)


def runroot_problem(home: str) -> str | None:
    """Why the engine at *home* does not use the runtime dirs (runroot and
    tmp dir) its config sets.

    Podman records an engine's runtime dirs (runroot and tmp dir) in its
    database when the first podman command with that HOME creates it, and
    later commands keep those over storage.conf and containers.conf (podman
    3.4 logs "Overriding run root/tmp dir ... from database" only at debug
    level).  An engine that ran before pm wrote its config — 'pm container
    enable' and 'pm container status' run 'podman info', and so does any
    podman command run between completing a hand-written storage.conf and
    'pm container engine-setup' writing containers.conf — therefore keeps
    podman's default runtime dirs, shared with the other engines in this
    container.  None when they match, when the config sets no runroot (the
    default engine), or when podman cannot tell (the mapping probes report
    that).
    """
    want = _configured_runroot(home)
    if not want:
        return None
    dirs = _engine_runtime_dirs(home)
    if dirs is None:
        return None
    got, got_tmp = dirs
    want_tmp = _configured_tmp_dir(home)
    if got and got != want:
        what = f"runroot {got}, not the {want} its storage.conf sets"
    elif want_tmp and got_tmp and got_tmp != want_tmp:
        what = (f"tmp dir {got_tmp}, not the {want_tmp} its containers.conf "
                f"sets")
    else:
        return None
    return (f"podman with HOME={home} uses {what}: the engine's database "
            f"{_db_path(home)} predates that config and podman keeps the "
            f"runtime dirs recorded there, so this engine shares runtime "
            f"state with the other engines in this container")


_ENGINE_OBJECTS = (
    ("container", ("ps", "-a", "--format", "{{.Names}}"), "podman rm -af"),
    ("pod", ("pod", "ps", "--format", "{{.Name}}"), "podman pod rm -af"),
    ("volume", ("volume", "ls", "--format", "{{.Name}}"),
     "podman volume rm -af"),
)


def reset_stale_engine_db(home: str | None = None) -> Path | None:
    """Make the engine at *home* use the runtime dirs its config sets.

    When its database predates the config (:func:`runroot_problem`) and
    holds no containers, pods or volumes, it is removed; the next podman
    command recreates it with the configured runroot and tmp dir.  It holds
    nothing else — images and layers live in the graphroot and the shared
    store, which stay.  Returns the removed database's path, else None.
    Raises :class:`ImageCacheError` when the database is in use or the
    reset did not take.
    """
    from pm_core.store import bounded_flock
    home = os.path.abspath(home or os.environ.get("HOME") or str(Path.home()))
    if not _configured_runroot(home):
        return None
    lock = _config_dir(home) / ".pm-engine.lock"
    with bounded_flock(lock, 120) as got:
        if not got:
            raise ImageCacheError(
                f"timed out after 120s waiting for another pm process to "
                f"check the engine at HOME={home} (lock {lock})")
        problem = runroot_problem(home)
        if not problem:
            return None
        held: list[str] = []
        fixes: list[str] = []
        for kind, args, fix in _ENGINE_OBJECTS:
            out = _podman_out(home, *args)
            if out is None:
                raise ImageCacheError(
                    f"{problem}; pm could not list the engine's {kind}s to "
                    f"reset that database ('podman {' '.join(args[:2])}' "
                    f"failed)")
            if out.split():
                held += [f"{kind} {n}" for n in out.split()]
                fixes.append(fix)
        if held:
            shown = ", ".join(held[:5]) + (", …" if len(held) > 5 else "")
            raise ImageCacheError(
                f"{problem}. pm resets that database only while it is empty, "
                f"and it holds {shown}: remove them (HOME={home} "
                f"{'; '.join(fixes)}) and retry")
        db = _db_path(home)
        try:
            db.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise ImageCacheError(
                f"{problem}; removing that database failed: {exc}") from exc
        problem = runroot_problem(home)
        if problem:
            raise ImageCacheError(f"{problem} (still, after pm reset it)")
    _log.info("image cache: reset the engine database of HOME=%s; it "
              "predated pm's engine config", home)
    return db


def _discard_check_db(home: str) -> None:
    """Remove the database of the engine at *home* that a check's own podman
    calls just created, while the engine holds no containers, pods or
    volumes.

    Podman keeps the runtime dirs recorded when a command first creates an
    engine's database over later config edits (:func:`runroot_problem`).
    Checking a config that is still being written by hand — the Nested
    Containers recipe's "edit the file, then 'pm container cache check'" —
    would otherwise pin podman's default runroot before the user adds the
    engine's own.  The next podman command recreates the database from the
    config as it then stands.
    """
    from pm_core.store import bounded_flock
    db = _db_path(home)
    if not db.exists():
        return
    lock = _config_dir(home) / ".pm-engine.lock"
    try:
        held = (bounded_flock(lock, 120) if lock.parent.is_dir()
                else contextlib.nullcontext(True))
        with held as got:
            if not got:
                return
            for _kind, args, _fix in _ENGINE_OBJECTS:
                out = _podman_out(home, *args)
                if out is None or out.split():
                    return      # cannot tell, or in use since: keep it
            db.unlink()
    except OSError:
        pass                    # unlockable config dir, or already gone


def _mount_options(mount_point: str) -> str | None:
    """Options of the topmost mount at *mount_point*, or None."""
    from pm_core.paths import read_mountinfo
    opts = None
    for m in read_mountinfo() or []:
        if m.mount_point == mount_point:
            opts = m.options
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
    overlay = overlay_support_problem()
    res.add(overlay is None, overlay or "fuse-overlayfs available")
    home = os.path.abspath(home or os.environ.get("HOME") or str(Path.home()))
    # The podman calls below create the engine's database when it has none
    # yet; a check must not leave one behind (see _discard_check_db).
    fresh_engine = not _db_path(home).exists()
    try:
        _check_engine(res, image_ref, entry, home)
    finally:
        if fresh_engine:
            _discard_check_db(home)
    return res


def _check_engine(res: CheckResult, image_ref: str | None, entry: dict,
                  home: str) -> None:
    """:func:`consumer_check`'s checks of the engine at *home*."""
    problem = engine_config_problem(home)
    if problem is None:
        problem = runroot_problem(home)
        if problem:
            problem += ("; the next pm launch with this HOME, or 'pm "
                        "container engine-setup', resets it while it holds "
                        "no containers")
    res.add(problem is None, problem or f"engine config for HOME={home} "
                                        f"uses the shared store")
    problem = _graphroot_problem(home)
    res.add(problem is None,
            problem or f"graphroot {_graphroot(home)} is on local disk")
    env = {**os.environ, "HOME": home}
    try:
        bad = _probe_mismatches(home)
    except ImageCacheError as exc:
        res.add(False, str(exc))
    else:
        if bad:
            res.add(False, "UID/GID mapping does not match the cache: "
                           + "; ".join(bad) + ". The entry was prepared for "
                           "engines at another nesting level; it cannot be "
                           "used here")
        else:
            res.add(True, "UID/GID mapping matches the cache "
                          "(probes 0:0, 1:1)")
    want = image_ref or entry.get("image_id") or ""
    try:
        r = subprocess.run(["podman", "image", "inspect", want],
                           capture_output=True, text=True, timeout=60, env=env)
        if r.returncode != 0:
            res.add(False, f"image '{want}' is not visible to the engine "
                           f"(cache holds {', '.join(entry.get('names') or [])}"
                           f"): {_podman_error(r.stderr)}")
        else:
            iid = str(json.loads(r.stdout)[0].get("Id", ""))
            from_cache = iid.split(":")[-1] == str(entry.get("image_id")).split(":")[-1]
            res.add(from_cache, f"image '{want}' visible"
                    + (" from the shared store" if from_cache else
                       f" but it is {iid[:12]}, not the cached image — a "
                       f"private copy shadows the shared one"))
    except (OSError, subprocess.TimeoutExpired, ValueError, LookupError) as exc:
        res.add(False, f"could not inspect image '{want}': {exc}")


_checked_homes: set[str] = set()


def ensure_consumer_engine(home: str | None = None) -> None:
    """Make the engine at *home* use the mounted cache (nested pm launches).

    Writes the config when it is missing (never over a foreign one) and
    checks the graphroot and the mapping probes once per home per process.
    Raises :class:`ImageCacheError` with the fix.
    """
    home = os.path.abspath(home or os.environ.get("HOME") or str(Path.home()))
    if home in _checked_homes:
        return
    overlay = overlay_support_problem()
    if overlay:
        raise ImageCacheError(overlay)
    # Also when the config already exists — the default engine's always
    # does (create_container writes it): on a FUSE root filesystem (a
    # consumer launched from inside a container) its launches would
    # otherwise fail later with podman's "executable file not found".
    graphroot = _graphroot_problem(home)
    if graphroot:
        raise ImageCacheError(graphroot)
    p = _config_dir(home) / "storage.conf"
    if not p.exists():
        write_engine_config(home)
    problem = engine_config_problem(home)
    if problem:
        # The foreign config may be deliberate (a storage-driver test's own
        # engine): then the cache, not the config, is what to turn off.
        raise ImageCacheError(f"{problem}; " + _off_remedy())
    # The config only takes effect once podman's database agrees with it:
    # pm itself ran 'podman info' with this HOME before writing it.
    reset_stale_engine_db(home)
    bad = _probe_mismatches(home)
    if bad:
        raise ImageCacheError(
            f"the shared image cache at {CONSUMER_MOUNT} was prepared for "
            f"engines at another user-namespace level ({'; '.join(bad)}), "
            f"so its files would show the wrong owners here; it cannot "
            f"serve this engine. Launch from a container whose cache "
            f"matches, " + _off_remedy())
    _checked_homes.add(home)


def _probe_mismatches(home: str) -> list[str]:
    """Mapping probes whose owner, as the engine at *home* sees it through
    ``podman unshare stat``, differs from the one recorded at preparation
    (``["uid1 is 65534:65534, expected 1:1", ...]``; empty when all match).

    Raises :class:`ImageCacheError` when the probes cannot be read.
    """
    probe_dir = f"{CONSUMER_MOUNT}/probe"
    try:
        r = subprocess.run(
            ["podman", "unshare", "stat", "-c", "%n %u:%g"]
            + [f"{probe_dir}/{p}" for p, _ in _PROBES],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HOME": home})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ImageCacheError(
            f"could not run 'podman unshare' to read the shared image "
            f"cache's mapping probes (HOME={home}): {exc}") from exc
    if r.returncode != 0:
        raise ImageCacheError(
            f"could not read the shared image cache's mapping probes with "
            f"'podman unshare' (HOME={home}): {_podman_error(r.stderr)}")
    seen = {Path(ln.split()[0]).name: ln.split()[1]
            for ln in r.stdout.splitlines() if len(ln.split()) == 2}
    return [f"{p} is {seen.get(p, '?')}, expected {want}"
            for p, want in _PROBES if seen.get(p) != want]


def _podman_error(stderr: str | None) -> str:
    """The meaningful part of podman's stderr (drops logrus warnings)."""
    lines = [ln for ln in (stderr or "").strip().splitlines()
             if ln.strip() and not ln.startswith("time=")]
    return (" ".join(lines) or "no error output")[:300]


def missing_in_consumer_message(image_ref: str) -> str:
    entry = read_consumer_entry() or {}
    names = [str(n) for n in entry.get("names") or []]
    short_id = str(entry.get("image_id") or "").removeprefix("sha256:")[:12]
    held = ", ".join(names) or short_id or "?"
    if names and short_id:
        held += f", image {short_id}"
    use = names[0] if names else short_id or "<name>"
    by_id = f", or its ID {short_id}" if names and short_id else ""
    # Entries are immutable and keyed by image ID, so a tag added on the host
    # after the entry was prepared never reaches it: relaunching this
    # container from that tag mounts the same entry and fails here again.
    # Only the names (or ID) the entry already holds work for such an alias.
    return (
        f"Image '{image_ref}' is not in the shared image cache mounted at "
        f"{CONSUMER_MOUNT} (it holds {held}). Inside a cache consumer pm "
        f"does not build, pull or import images — that would recreate the "
        f"per-engine copies the cache exists to avoid — and it does not fall "
        f"back to VFS or the host.\n\nTo fix: use the cached image "
        f"('pm container set image {use}'{by_id}). That is also the fix "
        f"when '{image_ref}' is another tag of the cached image: an entry "
        f"keeps the names its image had when it was prepared, so a tag "
        f"added on the host afterwards is not in it, and relaunching this "
        f"container from that tag mounts the same entry. Or build a small "
        f"fixture on top of the cached image. Or, if '{image_ref}' is a "
        f"different image, launch this container from it — a container sees "
        f"only the entry of the image it was launched from, so on the host "
        f"run 'pm container set image {image_ref}' and relaunch this "
        f"container (that launch prepares the image's entry); "
        + _off_remedy() + ".")
