"""Ownership-aware cleanup of leaked pm containers and push proxies.

Every *running* rootless-podman container holds kernel session-keyring keys;
leaked containers from finished runs, merged PRs and dead sessions exhaust
the keyring quota until no new container can ``run``/``exec``.  This module
decides which containers are still owned and removes the rest.

A container is **owned** — never removed here — when any of:

1. a live tmux pane was started with its exact name (or id) in
   ``#{pane_start_command}``, on the tmux server recorded in its
   ``pm.tmux_socket`` label, the default server, the current server, or the
   shared-session socket for its tag;
2. it is explicitly retained (``pm container retain``);
3. it is being launched: its per-name launch lock is held, or it was created
   less than ``LAUNCH_GRACE`` seconds ago.

Everything else in scope is removed (bounded parallel), after re-checking
ownership under the container's launch lock so a concurrent launch/restart
can't lose a live container.  Shared push proxies are stopped only when the
runtime reports no container left for their session + PR.

The same :func:`reconcile` backs the automatic passes (TUI startup and
periodic, QA run start, pre-launch keyring relief) and the manual
``pm container reap`` / ``pm session cleanup`` commands.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pm_core import container as container_mod
from pm_core.paths import configure_logger

_log = configure_logger("pm.container_reaper")

LAUNCH_GRACE = 120  # seconds a fresh container may exist without a pane
REMOVE_WORKERS = 4
_TERMINAL_PR_STATES = ("merged", "closed")


# ---------------------------------------------------------------------------
# Retention markers
# ---------------------------------------------------------------------------

def _retain_dir() -> Path:
    return container_mod.container_state_dir() / "retain"


def _retention_path(name: str, container_id: str = "") -> Path:
    if container_id:
        # Names may change through the runtime; retention follows this ID in
        # its runtime store, not a mutable name or an ID cloned into another store.
        domain = json.dumps(_runtime_domain(), sort_keys=True)
        key = hashlib.sha256(f"{domain}\0{container_id}".encode()).hexdigest()
        return _retain_dir() / f"{key}.json"
    return _retain_dir() / name


# An immutable ContextVar value keeps nested calls in one lifecycle operation
# cheap without sharing mutable caches across threads or retaining stale daemon
# identities between operations. Unknown identities are deliberately not cached.
_domain_cache = contextvars.ContextVar("container_runtime_domain", default=None)


@contextlib.contextmanager
def runtime_domain_scope():
    """Reuse successful runtime identity probes only within this operation."""
    if _domain_cache.get() is not None:
        yield
        return
    token = _domain_cache.set((None, None))
    try:
        yield
    finally:
        _domain_cache.reset(token)


def _runtime_domain() -> dict | None:
    from pm_core.push_proxy import runtime_domain
    cached = _domain_cache.get()
    if cached is None:
        return runtime_domain()
    # Runtime selection and config/connection environment may change even in
    # a nested operation. Do not reuse another store's identity in that case.
    key = (container_mod._get_runtime(), os.getcwd(), tuple(sorted(os.environ.items())))
    if cached[0] == key:
        return dict(cached[1])
    domain = runtime_domain()
    if domain is not None:
        _domain_cache.set((key, dict(domain)))
    else:
        _domain_cache.set((None, None))
    return domain


def _retain_record(name: str, container_id: str = "") -> dict | None:
    try:
        rec = json.loads(_retention_path(name, container_id).read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) else {}


def is_retained(name: str, container_id: str = "") -> bool:
    """True when *name* is retained — and, when both ids are known, only for
    the very container that was retained: a replacement launched later
    under the same name is not."""
    rec = _retain_record(name, container_id) if container_id else None
    if rec is None:
        rec = _retain_record(name)  # pre-identity-key marker
    if rec is None and not container_id:
        return name in retained_names()
    if rec is None and container_id:
        # Compatibility with name+ID keyed markers from before rename support.
        domain = _runtime_domain()
        return any(r.get("id") == container_id
                   and (domain is None or r.get("runtime_domain") in (None, domain))
                   for _, r in _retention_records())
    if rec is None:
        return False
    domain = rec.get("runtime_domain")
    current_domain = _runtime_domain() if domain is not None else None
    if current_domain is not None and domain != current_domain:
        return False
    rec_id = str(rec.get("id") or "")
    return not rec_id or not container_id or rec_id == container_id


def _write_retention(name: str, note: str, container_id: str) -> None:
    d = _retain_dir()
    d.mkdir(parents=True, exist_ok=True)
    _retention_path(name, container_id).write_text(json.dumps(
        {"name": name, "note": note, "at": int(time.time()), "id": container_id,
         "runtime_domain": _runtime_domain()}))


def retain(name: str, note: str = "", container_id: str = "") -> None:
    with container_mod.launch_lock(name) as locked:
        if not locked:
            raise container_mod.ContainerError(f"Cannot retain '{name}': lifecycle lock unavailable")
        _write_retention(name, note, container_id)


def retain_current(name: str, note: str = "") -> str:
    """Inspect and retain atomically with respect to launch/removal."""
    name = container_mod.canonical_container_name(name)
    with container_mod.launch_lock(name) as locked:
        if not locked:
            raise container_mod.ContainerError(f"Cannot retain '{name}': lifecycle lock unavailable")
        cid = container_mod.current_container_id(name)
        if not cid:
            raise container_mod.ContainerError(
                f"No container named {name}, or its identity is unknown; cannot retain.")
        _write_retention(name, note, cid)
    return name


def _retention_records() -> list[tuple[Path, dict]]:
    records = []
    try:
        paths = list(_retain_dir().glob("*"))
    except FileNotFoundError:
        return records
    for path in paths:
        try:
            rec = json.loads(path.read_text())
            if isinstance(rec, dict):
                records.append((path, {"name": path.name, **rec}))
        except (OSError, ValueError):
            records.append((path, {"name": path.name}))
    return records


def unretain(name: str) -> bool:
    domain = _runtime_domain()
    removed = False
    records = _retention_records()
    # A stale same-name marker may belong to a removed allocation while the
    # current container was retained under its old name before a rename.
    cid = container_mod.current_container_id(name)
    for path, rec in records:
        if rec.get("name") != name and (not cid or rec.get("id") != cid):
            continue
        recorded = rec.get("runtime_domain")
        if recorded is not None and recorded != domain:
            continue
        path.unlink(missing_ok=True)
        removed = True
    return removed


def retained_names() -> list[str]:
    return sorted({rec["name"] for _, rec in _retention_records()})


def _prune_retain_markers(inventory: dict[str, str], since: float) -> None:
    """Drop retention markers whose container is gone or was replaced.

    *inventory* maps every existing pm container name to its id (full
    passes only), so a marker can't outlive the container it was set on.
    Markers written at or after *since* (the pass's listing time) are kept:
    they may name a container launched after the listing.
    """
    domain = _runtime_domain()
    if domain is None:
        return
    existing_ids = set(inventory.values())
    for path, rec in _retention_records():
        if rec.get("runtime_domain") != domain:
            continue  # another runtime's absence proves nothing about this marker
        name = rec["name"]
        if (rec.get("id") in existing_ids
                or not rec.get("id") and name in inventory):
            continue
        try:
            # "at" has whole-second resolution, so compare against the
            # truncated listing time (errs on keeping the marker).
            if float(rec.get("at") or 0) >= int(since):
                continue
        except (TypeError, ValueError):
            pass
        path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Durable, identity-bound owner releases
# ---------------------------------------------------------------------------

def _release_dir() -> Path:
    return container_mod.container_state_dir() / "release"


def restart_generation(name: str) -> str | None:
    try:
        return container_mod.cleanup_generation(name)
    except OSError:
        return None


def allocation_generation(name: str, cid: str) -> str | None:
    """Use the ID epoch after renames; preserve legacy name-only generations."""
    try:
        path = container_mod._identity_generation_path(cid)
        if path.exists():
            return path.read_text().strip()
        return restart_generation(name)
    except OSError:
        return None


def capture_identity(name: str) -> tuple[str, str] | None:
    try:
        cid = container_mod.current_container_id(name)
        generation = restart_generation(name)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (cid, generation) if cid and generation is not None else None


def _record_release(name: str, cid: str, generation: str, reason: str) -> None:
    directory = _release_dir()
    directory.mkdir(parents=True, exist_ok=True)
    # Runtime names/IDs are normally safe; hash unusual input instead of
    # letting an alias or malformed state escape the release directory.
    domain = _runtime_domain()
    domain_key = hashlib.sha256(json.dumps(domain, sort_keys=True).encode()).hexdigest()[:16]
    key = f"{name}@{cid}-{domain_key}"
    if generation:
        key += "-" + hashlib.sha256(generation.encode()).hexdigest()[:16]
    if len(key) > 220 or not re.fullmatch(r"[A-Za-z0-9_.@-]+", key):
        key = hashlib.sha256(key.encode()).hexdigest()
    fd, temp = tempfile.mkstemp(dir=directory, prefix=".release-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump({"name": name, "id": cid, "generation": generation,
                       "at": time.time(), "reason": reason,
                       "runtime_domain": domain, "domain_required": True}, stream)
        os.replace(temp, directory / f"{key}.json")
    finally:
        Path(temp).unlink(missing_ok=True)


def _release_records() -> list[tuple[Path, dict]]:
    records = []
    for path in _release_dir().glob("*.json"):
        try:
            rec = json.loads(path.read_text())
            if (isinstance(rec, dict) and isinstance(rec.get("name"), str)
                    and rec["name"] and isinstance(rec.get("id"), str) and rec["id"]
                    and isinstance(rec.get("generation"), str)
                    and isinstance(rec.get("at"), (int, float))):
                records.append((path, rec))
        except (OSError, ValueError):
            pass
    return records


def _current_release_records() -> list[tuple[Path, dict]]:
    """Only this runtime's releases may override live ownership.

    Preserve legacy unscoped records, but new unknown-domain requests are
    diagnostic only. They cannot grant cleanup authority in any runtime.
    """
    domain = _runtime_domain()
    return [(path, rec) for path, rec in _release_records()
            if (rec.get("runtime_domain") is not None
                and rec["runtime_domain"] == domain)
            or (rec.get("runtime_domain") is None and not rec.get("domain_required"))]


def pending_releases() -> dict[str, dict]:
    return {rec["name"]: rec for _, rec in sorted(
        _current_release_records(), key=lambda item: item[1].get("at", 0))}


def _prune_releases(out: "Outcome", scope: "Scope", since: float) -> None:
    inventory = {d.info.name: d.info for d in out.decisions}
    by_id = {d.info.id: d.info for d in out.decisions}
    domain = _runtime_domain()
    for path, rec in _release_records():
        if domain is None or rec.get("runtime_domain") != domain:
            continue
        if rec.get("at", 0) >= since:
            continue
        info = by_id.get(rec["id"]) or inventory.get(rec["name"])
        absent = info is None and (scope == Scope() or
                                  scope.names is not None and rec["name"] in scope.names)
        stale = info is not None and (
            info.id != rec["id"] or
            allocation_generation(rec["name"], info.id) not in (None, rec["generation"]))
        if absent or stale or info is not None and info.name in out.removed:
            path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Container inventory
# ---------------------------------------------------------------------------

@dataclass
class ContainerInfo:
    name: str
    id: str = ""
    running: bool = False
    status: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    session_tag: str | None = None
    pr_id: str | None = None
    kind: str | None = None
    loop_id: str | None = None
    created: float | None = None

    @property
    def tmux_socket(self) -> str:
        return self.labels.get(container_mod.LABEL_TMUX_SOCKET, "")

    @property
    def project_root(self) -> str:
        return self.labels.get(container_mod.LABEL_PROJECT, "")


def _info_from(name: str, cid: str, running: bool, status: str,
               labels: dict[str, str]) -> ContainerInfo | None:
    managed = labels.get(container_mod.LABEL_MANAGED) == "1"
    parsed = container_mod.parse_container_name(name)
    if not managed and parsed is None:
        return None  # not a pm container
    info = ContainerInfo(name=name, id=cid, running=running, status=status,
                         labels=labels)
    if managed:
        info.session_tag = labels.get(container_mod.LABEL_SESSION) or None
        info.pr_id = labels.get(container_mod.LABEL_PR) or None
        info.kind = labels.get(container_mod.LABEL_KIND) or None
        info.loop_id = labels.get(container_mod.LABEL_LOOP) or None
        try:
            info.created = float(labels.get(container_mod.LABEL_CREATED, ""))
        except ValueError:
            info.created = None
    if parsed is not None:
        info.session_tag = info.session_tag or parsed.session_tag
        info.kind = info.kind or parsed.kind
        info.pr_id = info.pr_id or parsed.pr_id()
        if info.loop_id is None and parsed.kind == "qa" and info.pr_id:
            rest = parsed.rest[len(info.pr_id) + 1:]
            m = re.match(r"(.+)-s\d+$", rest)
            info.loop_id = m.group(1) if m else None
    return info


def list_containers() -> list[ContainerInfo] | None:
    """All pm containers (any state), or None when the runtime is unavailable."""
    names: dict[str, None] = {}
    # A managed allocation may have been renamed. Labels remain authoritative
    # for its ownership and shared proxy; the name query also includes legacy
    # unlabeled containers. Never accept a partial inventory from either query.
    for managed in (False, True):
        selector = (f"label={container_mod.LABEL_MANAGED}=1" if managed
                    else f"name={container_mod.CONTAINER_PREFIX}")
        try:
            ps = container_mod._run_runtime(
                "ps", "-a", "--filter", selector,
                "--format", "{{.Names}}", check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if ps.returncode != 0:
            return None
        for line in (ps.stdout or "").splitlines():
            name = line.strip()
            if name and (managed or name.startswith(container_mod.CONTAINER_PREFIX)):
                names[name] = None
    if not names:
        return []
    # _inspect rechecks the managed label/name rather than trusting runtime
    # substring filters, and rejects missing or malformed rows.
    return _inspect(list(names), timeout=60)


_INSPECT_FMT = ("{{.Name}}\t{{.Id}}\t{{.State.Running}}\t{{.State.Status}}\t"
                "{{json .Config.Labels}}")


def _inspect(names: list[str], timeout: int) -> list[ContainerInfo] | None:
    """ContainerInfo for *names*, or None if the inventory is incomplete.

    Missing rows are not proof of absence: full reconciles use this inventory
    to prune retention and failure records, so a failed inspect must fail closed.
    """
    try:
        insp = container_mod._run_runtime("inspect", "--format", _INSPECT_FMT,
                                          *names, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if insp.returncode != 0:
        # A vanished container can fail the batch too; retry on the next pass
        # rather than guess whether missing rows mean removal or runtime failure.
        return None
    out: list[ContainerInfo] = []
    seen: set[str] = set()
    for line in (insp.stdout or "").splitlines():
        # Podman 3.x renders template tabs through a tabwriter as spaces.
        # Only the labels JSON may contain whitespace within a field.
        parts = line.split(None, 4)
        if len(parts) < 5:
            return None
        name = parts[0].lstrip("/").strip()
        try:
            labels = json.loads(parts[4])
        except ValueError:
            return None
        if labels is None:
            labels = {}  # unlabeled legacy container
        if not isinstance(labels, dict):
            return None
        info = _info_from(name, parts[1].strip(), parts[2].strip() == "true",
                          parts[3].strip(), {str(k): str(v) for k, v in labels.items()})
        if info is not None and name not in seen:
            out.append(info)
        seen.add(name)
    # Ownership lookups may pass a container ID or /name; inspect returns its
    # canonical name. Require every requested row without rejecting aliases.
    return out if len(seen) == len(set(names)) else None


# ---------------------------------------------------------------------------
# tmux pane ownership
# ---------------------------------------------------------------------------

@dataclass
class _Server:
    key: str            # cache key
    args: list[str]     # tmux socket args (-S path / -L name)
    socket_file: str    # path whose existence tells "server could exist"


def _server_for_socket(path: str) -> _Server:
    return _Server(key=f"S:{path}", args=["-S", path], socket_file=path)


def _default_server() -> _Server:
    uid = os.getuid()
    tmpdir = os.environ.get("TMUX_TMPDIR") or "/tmp"
    return _Server(key="L:default", args=["-L", "default"],
                   socket_file=os.path.join(tmpdir, f"tmux-{uid}", "default"))


def _servers_for(info: ContainerInfo) -> list[_Server]:
    servers: list[_Server] = []
    if info.tmux_socket:
        servers.append(_server_for_socket(info.tmux_socket))
    servers.append(_default_server())
    for env_sock in (os.environ.get("PM_TMUX_SOCKET", ""),
                     os.environ.get("TMUX", "").split(",", 1)[0]):
        if env_sock:
            servers.append(_server_for_socket(env_sock))
    if info.session_tag:
        try:
            from pm_core.paths import shared_socket_path
            servers.append(_server_for_socket(str(shared_socket_path(info.session_tag))))
        except Exception:
            pass
    uniq: dict[str, _Server] = {}
    for s in servers:
        uniq.setdefault(os.path.realpath(s.socket_file) if s.socket_file else s.key, s)
    return list(uniq.values())


@dataclass
class _PaneSnapshot:
    """``None`` panes means the server exists but couldn't be queried."""
    panes: list[tuple[str, str, str]] | None  # (pane_id, session, start_cmd)


class _PaneCache:
    def __init__(self) -> None:
        self._cache: dict[str, _PaneSnapshot] = {}

    def get(self, server: _Server, fresh: bool = False) -> _PaneSnapshot:
        if not fresh and server.key in self._cache:
            return self._cache[server.key]
        snap = _query_server(server)
        self._cache[server.key] = snap
        return snap


def _query_server(server: _Server) -> _PaneSnapshot:
    if server.socket_file:
        try:
            os.stat(server.socket_file)
        except FileNotFoundError:
            return _PaneSnapshot(panes=[])  # no server → no panes
        except OSError:
            return _PaneSnapshot(panes=None)  # inaccessible is not absent
    env = {k: v for k, v in os.environ.items() if k != "TMUX"}
    try:
        r = subprocess.run(
            ["tmux", *server.args, "list-panes", "-a", "-F",
             "#{pane_dead}\t#{pane_id}\t#{session_name}\t#{pane_start_command}"],
            capture_output=True, text=True, timeout=5, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return _PaneSnapshot(panes=None)
    if r.returncode != 0:
        err = (r.stderr or "").lower()
        if "no server running" in err or ("error connecting" in err
                                          and "no such file" in err):
            return _PaneSnapshot(panes=[])
        return _PaneSnapshot(panes=None)
    panes = []
    for line in r.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) < 4 or parts[0] == "1":
            continue
        panes.append((parts[1], parts[2], parts[3]))
    return _PaneSnapshot(panes=panes)


def _token_re(token: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(token)
                      + r"(?![A-Za-z0-9_.-])")


def _owner_panes(info: ContainerInfo, cache: _PaneCache,
                 fresh: bool = False) -> tuple[list[str], bool]:
    """(owning pane ids, indeterminate) for *info*."""
    pats = [_token_re(info.name)]
    if info.id:
        pats.append(_token_re(info.id))
    owners: list[str] = []
    indeterminate = False
    try:
        if container_mod.activity_owner(info.name, info.id):
            owners.append("interactive client")
    except (container_mod.ContainerError, OSError):
        indeterminate = True
    for server in _servers_for(info):
        snap = cache.get(server, fresh=fresh)
        if snap.panes is None:
            indeterminate = True
            continue
        for pane_id, _sess, cmd in snap.panes:
            if any(p.search(cmd) for p in pats):
                owners.append(pane_id)
    return owners, indeterminate


def live_owner_panes(name: str, container_id: str = "", *, strict: bool = False) -> list[str]:
    """Live tmux panes started for container *name* (fresh query).

    The container's own labels are consulted so the tmux server it was
    launched from (``pm.tmux_socket``) is searched even when that isn't
    this process's server. Raises ContainerError when ownership cannot be
    established; destructive recovery must not interpret unknown as unowned.
    """
    if not strict and container_mod.activity_owner(name):
        return ["interactive client"]
    found = _inspect([name], timeout=10)
    if not found:
        raise container_mod.ContainerError(
            f"Container '{name}' ownership unknown: could not inspect ownership metadata")
    info = found[0]
    info.id = container_id or info.id
    if info.session_tag is None:
        parsed = container_mod.parse_container_name(name)
        if parsed:
            info.session_tag = parsed.session_tag
    owners, indeterminate = _owner_panes(info, _PaneCache(), fresh=True)
    if indeterminate and (strict or not owners):
        raise container_mod.ContainerError(
            f"Container '{name}' ownership unknown: tmux server unreachable")
    return owners


def _session_alive(tag: str, cache: _PaneCache) -> bool | None:
    info = ContainerInfo(name="", session_tag=tag)
    sess = f"pm-{tag}"
    unknown = False
    for server in _servers_for(info):
        snap = cache.get(server)
        if snap.panes is None:
            unknown = True
            continue
        if any(s == sess or s.startswith(sess + "~") for _p, s, _c in snap.panes):
            return True
    return None if unknown else False


# ---------------------------------------------------------------------------
# PR status lookup
# ---------------------------------------------------------------------------

class _PrStatus:
    def __init__(self) -> None:
        self._by_root: dict[str, dict[str, str]] = {}
        self._current_root: str | None = None

    def _load(self, root: str) -> dict[str, str]:
        if root not in self._by_root:
            statuses: dict[str, str] = {}
            try:
                from pm_core.store import load
                data = load(Path(root), validate=False)
                for pr in data.get("prs") or []:
                    if pr.get("id"):
                        statuses[pr["id"]] = pr.get("status") or ""
            except Exception:
                pass
            self._by_root[root] = statuses
        return self._by_root[root]

    def status(self, info: ContainerInfo) -> str | None:
        if not info.pr_id:
            return None
        root = info.project_root
        if not root:
            if self._current_root is None:
                self._current_root = container_mod._current_project_root()
            root = self._current_root
        if not root:
            return None
        return self._load(root).get(info.pr_id)


# ---------------------------------------------------------------------------
# Decisions + reconcile
# ---------------------------------------------------------------------------

@dataclass
class Scope:
    pr_id: str | None = None
    session_tag: str | None = None
    kinds: set[str] | None = None
    loop_id: str | None = None
    names: set[str] | None = None
    include_retained: bool = False
    # The run that owns these containers is releasing them: its own panes
    # don't count as owners and the launch grace doesn't apply (retention
    # and in-flight launches still do).
    owner_release: bool = False
    expected_ids: dict[str, str] = field(default_factory=dict)
    expected_generations: dict[str, str] = field(default_factory=dict)

    def matches(self, info: ContainerInfo) -> bool:
        if (self.names is not None and info.name not in self.names
                and not (self.owner_release and info.id in self.expected_ids.values())):
            return False
        if self.pr_id and info.pr_id != self.pr_id:
            return False
        if self.session_tag and info.session_tag != self.session_tag:
            return False
        if self.kinds and info.kind not in self.kinds:
            return False
        if self.loop_id and info.loop_id != self.loop_id:
            return False
        return True

    def describe(self) -> str:
        bits = []
        if self.session_tag:
            bits.append(f"session {self.session_tag}")
        if self.pr_id:
            bits.append(f"PR {self.pr_id}")
        if self.kinds:
            bits.append("kind " + "/".join(sorted(self.kinds)))
        if self.loop_id:
            bits.append(f"QA loop {self.loop_id}")
        if self.names is not None:
            bits.append(f"{len(self.names)} named container(s)")
        if self.owner_release:
            bits.append("released by owner")
        return ", ".join(bits) or "all pm containers"


@dataclass
class Decision:
    info: ContainerInfo
    action: str  # "remove" | "keep"
    reason: str
    # Released by the run that launched it: its own panes don't keep it.
    released: bool = False
    release_generation: str | None = None
    release_name: str = ""  # original name for pre-ID generation compatibility


@dataclass
class Outcome:
    scope: str = ""
    decisions: list[Decision] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)
    release_refused: dict[str, str] = field(default_factory=dict)
    # Failed removals of containers their run released (retried as released).
    released_failures: set[str] = field(default_factory=set)
    proxies_released: list[str] = field(default_factory=list)
    # Kept containers near their PID limit: (name, pids, limit, reason kept).
    pid_pressure: list[tuple[str, int, int, str]] = field(default_factory=list)
    running_before: int | None = None
    running_after: int | None = None
    keyring_before: str = ""
    keyring_after: str = ""
    error: str = ""
    skipped: bool = False
    dry_run: bool = False

    @property
    def to_remove(self) -> list[Decision]:
        return [d for d in self.decisions if d.action == "remove"]

    def summary(self) -> str:
        if self.skipped:
            return "container cleanup already running elsewhere — skipped"
        if self.error:
            return f"container cleanup unavailable: {self.error}"
        kept = len([d for d in self.decisions if d.action == "keep"])
        if self.dry_run:
            head = f"would remove {len(self.to_remove)}, keep {kept}"
        else:
            head = (f"removed {len(self.removed)}, kept {kept}, "
                    f"failed {len(self.failures)}")
        if self.proxies_released:
            head += f", stopped {len(self.proxies_released)} unused proxy(ies)"
        counts = []
        if self.running_before is not None:
            after = ("" if self.running_after is None or self.dry_run
                     else f" → {self.running_after}")
            counts.append(f"running {self.running_before}{after}")
        if self.keyring_before:
            after = ("" if not self.keyring_after or self.dry_run
                     else f" → {self.keyring_after}")
            counts.append(f"keyring {self.keyring_before}{after}")
        if self.pid_pressure:
            head += f", {len(self.pid_pressure)} near PID limit"
        return head + (f" ({'; '.join(counts)})" if counts else "")


def _decide(info: ContainerInfo, scope: Scope, cache: _PaneCache,
            prs: _PrStatus, now: float,
            pending_release: dict[str, str] | None = None,
            release_records: list[dict] | None = None) -> Decision:
    if scope.owner_release and info.name in scope.expected_ids:
        if info.id != scope.expected_ids[info.name]:
            return Decision(info, "keep", "replaced since owner release")
        generation = restart_generation(info.name)
        if generation != scope.expected_generations.get(info.name):
            return Decision(info, "keep", "restarted or generation unknown since owner release")
    if is_retained(info.name, info.id) and not scope.include_retained:
        return Decision(info, "keep", "explicitly retained (pm container retain)")
    if container_mod.launch_in_progress(info.name):
        return Decision(info, "keep", "launch in progress")
    releases = release_records or []
    matching = [rec for rec in releases if rec["id"] == info.id]
    if matching:
        for rec in matching:
            generation = allocation_generation(rec["name"], info.id)
            if generation is None:
                return Decision(info, "keep", "cleanup generation unknown")
            if generation == rec["generation"]:
                return Decision(info, "remove", "released by its run", released=True,
                                release_generation=generation,
                                release_name=rec["name"])
    if (not releases and _is_pending_release(info, pending_release or {})
            and restart_generation(info.name) == ""):
        # Its run already let it go but the removal failed; the run's panes
        # are still exec'd into it and would otherwise "own" it forever.
        return Decision(info, "remove", "released by its run (retrying failed removal)",
                        released=True)
    owners, indeterminate = _owner_panes(info, cache)
    if owners:
        return Decision(info, "keep", f"owned by live pane {', '.join(owners)}")
    try:
        attaching = container_mod.recent_launch(info.name, LAUNCH_GRACE, info.id)
    except OSError:
        return Decision(info, "keep", "launch lease unreadable — ownership unknown")
    if attaching or info.created is not None and now - info.created < LAUNCH_GRACE:
        return Decision(info, "keep", "launching (no pane yet)")
    if indeterminate:
        # Unknown beats merged: a pane we can't see may still be in use.
        # The next pass retries.
        return Decision(info, "keep", "tmux server unreachable — ownership unknown")
    status = prs.status(info)
    if status in _TERMINAL_PR_STATES:
        return Decision(info, "remove", f"PR {info.pr_id} is {status}, no owning pane")
    if info.session_tag:
        alive = _session_alive(info.session_tag, cache)
        if alive is False:
            return Decision(info, "remove", f"tmux session pm-{info.session_tag} gone")
    what = "QA run finished or superseded" if info.kind == "qa" else "attempt ended"
    return Decision(info, "remove", f"no owning pane ({what})")


def _is_pending_release(info: ContainerInfo, pending: dict[str, str]) -> bool:
    """True when *info* is the very container whose owner release failed.

    Bound to the container id: a replacement created under the same name
    belongs to a new launch and must go through the normal ownership checks.
    """
    if info.name not in pending:
        return False
    rec_id = pending[info.name]
    return bool(rec_id and info.id and rec_id == info.id)


def _remove_checked(d: Decision, scope: Scope) -> tuple[bool, str]:
    """Remove *d* after re-checking ownership under its launch lock."""
    info = d.info
    with container_mod.launch_lock(info.name, timeout=0) as free:
        if not free:
            return False, "skipped: launch started concurrently"
        if is_retained(info.name, info.id) and not scope.include_retained:
            return False, "skipped: retained concurrently"
        if info.id:
            # A relaunch between plan() and now replaced the container under
            # the same name; its pane may not exist yet, so the pane re-check
            # below can't protect it.  Removal is by name, so compare ids.
            try:
                current = container_mod.current_container_id(info.name)
            except (OSError, subprocess.TimeoutExpired) as e:
                # Raising here would abort the whole pass and lose the
                # record of removals already done; fail just this one.
                return False, f"error: could not re-check container id: {e}"
            if current is None:
                return False, "error: container identity unknown during removal re-check"
            if current and current != info.id:
                return False, "skipped: replaced by a newer launch"
            if current == "":
                # Missing by name does not prove the allocation is gone: an
                # external runtime rename can race the inventory. Keep its
                # release until a fresh pass acquires the new name's lock.
                try:
                    remaining = container_mod.current_container_id(info.id)
                except (OSError, subprocess.TimeoutExpired) as e:
                    return False, f"error: could not re-check allocation id: {e}"
                if remaining is None:
                    return False, "error: allocation identity unknown after name disappeared"
                if remaining:
                    return False, "skipped: container renamed since inventory"
        if d.release_generation is not None:
            generation = allocation_generation(d.release_name or info.name, info.id)
            if generation is None:
                return False, "error: cleanup generation unknown during removal re-check"
            if generation != d.release_generation:
                return False, "skipped: container restarted since owner release"
        if not d.released:
            try:
                if container_mod.recent_launch(info.name, LAUNCH_GRACE, info.id):
                    return False, "skipped: new owner attaching"
            except OSError:
                return False, "skipped: launch lease unreadable — ownership unknown"
            owners, indeterminate = _owner_panes(info, _PaneCache(), fresh=True)
            if owners:
                return False, f"skipped: pane {', '.join(owners)} attached concurrently"
            if indeterminate:
                return False, "skipped: tmux server unreachable — ownership unknown"
        try:
            container_mod.remove_container(info.name)
        except Exception as e:
            return False, f"error: {e}"
    return True, ""


_LOCK_FILE_MAX_AGE = 3600


def _prune_lock_files(inventory: set[str]) -> None:
    """Drop launch-lock files of containers that no longer exist.

    One file is created per launched container name (QA names embed the
    loop id), so without pruning they accumulate forever.  A file is only
    unlinked while we hold its lock and once it is old enough that no
    launch of that name can still be starting.
    """
    lock_dir = container_mod.container_state_dir() / "locks"
    try:
        entries = list(lock_dir.glob("container-*.lock"))
    except OSError:
        return
    now = time.time()
    for path in entries:
        name = path.name[len("container-"):-len(".lock")]
        if name in inventory:
            continue
        try:
            if now - path.stat().st_mtime < _LOCK_FILE_MAX_AGE:
                continue
        except OSError:
            continue
        with container_mod.launch_lock(name, timeout=0) as free:
            if free:
                path.unlink(missing_ok=True)


def spawn_detached_reap(pr_id: str | None = None,
                        session_tag: str | None = None) -> None:
    """Run ``pm container reap`` for a scope in a detached process.

    For short-lived CLI paths (e.g. a merge) that must not wait for
    removals nor leave a daemon thread to be killed at exit.
    """
    import sys
    cmd = [sys.executable, "-m", "pm_core.wrapper", "container", "reap"]
    if pr_id:
        cmd += ["--pr", pr_id]
    if session_tag:
        cmd += ["--session", session_tag]
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        _log.warning("could not spawn detached reap for %s", pr_id, exc_info=True)


def _release_unused_proxies(scope: Scope, failures: dict[str, str]) -> list[str]:
    from pm_core import push_proxy
    released = push_proxy.retry_unshared_releases(scope, failures)
    domain = push_proxy.runtime_domain()
    if domain is None:
        return released
    for prox in push_proxy.list_shared_proxies():
        if prox.get("runtime_domain") != domain:
            continue
        if scope.session_tag and prox["session_tag"] != scope.session_tag:
            continue
        if scope.pr_id and prox["pr_id"] != scope.pr_id:
            continue
        key = f"{prox['session_tag']}/{prox['pr_id']}"
        try:
            result = push_proxy.release_proxy_if_unused(prox["session_tag"], prox["pr_id"])
            if result:
                released.append(key)
            elif result is None:
                failures[f"push proxy {key}"] = "runtime inventory unavailable; proxy preserved"
        except Exception as exc:
            failures[f"push proxy {key}"] = str(exc)
            _log.warning("proxy release for %s failed", prox, exc_info=True)
    return released


@runtime_domain_scope()
def plan(scope: Scope | None = None) -> Outcome:
    """Classify containers in *scope* without changing anything."""
    scope = scope or Scope()
    out = Outcome(scope=scope.describe(), dry_run=True)
    infos = list_containers()
    if infos is None:
        out.error = f"{container_mod._get_runtime()} is not available"
        return out
    cache, prs, now = _PaneCache(), _PrStatus(), time.time()
    pending_release = {
        n: str(f.get("id") or "") for n, f in pending_failures().items()
        if isinstance(f, dict) and f.get("owner_release")}
    releases: dict[str, list[dict]] = {}
    for _, rec in _current_release_records():
        releases.setdefault(rec["id"], []).append(rec)
    for info in infos:
        if scope.matches(info):
            out.decisions.append(_decide(info, scope, cache, prs, now,
                                         pending_release, releases.get(info.id)))
    return out


# Opportunistic passes skip when another process is already reconciling (it
# covers them); explicit releases and manual runs wait their turn.
_SKIP_IF_BUSY = frozenset({"auto", "startup", "periodic", "keyring-pressure"})


@runtime_domain_scope()
def _run(scope: Scope, dry_run: bool, reason: str) -> Outcome:
    timeout = 0 if reason in _SKIP_IF_BUSY else 120
    with container_mod._file_lock("reaper", timeout=timeout) as got:
        if not got:
            return Outcome(scope=scope.describe(), skipped=True, dry_run=dry_run)
        listed_at = time.time()
        out = plan(scope)
        out.dry_run = dry_run
        if out.error:
            return out
        out.running_before = container_mod.running_container_count()
        out.keyring_before = container_mod.keyring_summary()
        if dry_run:
            if scope.names is None:
                _note_pid_pressure(out)
            return out
        targets = out.to_remove
        if targets:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(REMOVE_WORKERS, len(targets))) as ex:
                # Each worker inherits the successful inventory-time probe,
                # but gets its own context so nested changes cannot race peers.
                futures = [(d, ex.submit(contextvars.copy_context().run,
                                         _remove_checked, d, scope)) for d in targets]
                results = [(d, future.result()) for d, future in futures]
            for d, (ok, msg) in results:
                if ok:
                    out.removed.append(d.info.name)
                elif msg.startswith("error:"):
                    out.failures[d.info.name] = msg[len("error: "):]
                    if d.released:
                        out.released_failures.add(d.info.name)
                else:
                    d.action, d.reason = "keep", msg
        try:
            out.proxies_released = _release_unused_proxies(scope, out.failures)
        except Exception as exc:
            out.failures["push proxy sweep"] = str(exc)
            _log.warning("proxy sweep failed", exc_info=True)
        out.running_after = container_mod.running_container_count()
        out.keyring_after = container_mod.keyring_summary()
        if scope.names is None:
            _note_pid_pressure(out)
        full_pass = scope == Scope()
        inventory = {d.info.name for d in out.decisions}
        _prune_releases(out, scope, listed_at)
        _record(out, scope, reason, inventory=inventory if full_pass else None)
        if full_pass:
            _prune_lock_files(inventory)
            _prune_retain_markers({d.info.name: d.info.id for d in out.decisions
                                   if d.info.name not in out.removed},
                                  since=listed_at)
        if out.removed or out.failures:
            _log.info("reconcile[%s] %s: %s — removed=%s failures=%s", reason,
                      out.scope, out.summary(), out.removed, out.failures)
        return out


def _note_pid_pressure(out: Outcome) -> None:
    """Flag kept containers close to their PID limit.

    Unowned exhausted containers were just removed like any leftover; an
    owned one may hold a live session, so it is reported (with the restart
    command) rather than restarted behind the user's back.
    """
    kept = {d.info.name: d.reason for d in out.decisions
            if d.action == "keep" and d.info.running}
    if not kept:
        return
    try:
        hot = container_mod.pids_pressure()
    except Exception:
        _log.debug("PID usage probe failed", exc_info=True)
        return
    out.pid_pressure = [(n, c, lim, kept[n]) for n, c, lim in hot if n in kept]
    for n, c, lim, why in out.pid_pressure:
        _log.warning("container %s at %d/%d PIDs (%s)", n, c, lim, why)


_bg_lock = threading.Lock()
_bg_running = False
_bg_queue: list[tuple[Scope, bool, str, Callable[[Outcome], None] | None]] = []


def reconcile(scope: Scope | None = None, *, dry_run: bool = False,
              wait: bool = True, reason: str = "auto",
              on_done: Callable[[Outcome], None] | None = None) -> Outcome | None:
    """Remove unowned pm containers in *scope* (default: everything).

    ``wait=False`` queues the pass for one background daemon thread per
    process (identical pending requests are coalesced, distinct scopes are
    all run) and returns None.  Never raises; problems are reported in the
    returned :class:`Outcome`.
    """
    scope = scope or Scope()

    def _go() -> Outcome:
        try:
            out = _run(scope, dry_run, reason)
        except Exception as e:  # pragma: no cover - defensive
            _log.warning("reconcile failed", exc_info=True)
            out = Outcome(scope=scope.describe(), error=str(e))
        if on_done:
            try:
                on_done(out)
            except Exception:
                _log.debug("reconcile on_done failed", exc_info=True)
        return out

    if wait:
        return _go()

    global _bg_running
    with _bg_lock:
        if not any(q[0] == scope and q[1] == dry_run and q[3] is None
                   for q in _bg_queue) or on_done is not None:
            _bg_queue.append((scope, dry_run, reason, on_done))
        if _bg_running:
            return None
        _bg_running = True

    threading.Thread(target=_drain_bg_queue, daemon=True,
                     name="pm-container-reaper").start()
    return None


def _drain_bg_queue() -> None:
    global _bg_running
    while True:
        with _bg_lock:
            if not _bg_queue:
                _bg_running = False
                return
            scope, dry_run, reason, on_done = _bg_queue.pop(0)
        reconcile(scope, dry_run=dry_run, wait=True, reason=reason,
                  on_done=on_done)


@runtime_domain_scope()
def release_containers(names: list[str], *, reason: str = "release",
                       wait: bool = True,
                       owner_release: bool = False,
                       expected_ids: dict[str, str] | None = None,
                       expected_generations: dict[str, str] | None = None) -> Outcome | None:
    """Release specific containers a run no longer needs.

    By default goes through the full ownership checks, so a container a
    human is still using (live pane) is kept.  ``owner_release=True`` is for
    the run that launched them: its own panes are being ended on purpose.
    It must supply the captured container IDs and recovery generations; these
    are persisted before inventory/locking so a later pass can retry safely.
    Missing identity falls back to ordinary ownership checks, never name-only
    force removal. Retention and an in-flight launch defer the request.
    """
    if not names:
        return Outcome(scope="no containers")
    refused = {}
    if owner_release:
        for name in names:
            cid = (expected_ids or {}).get(name)
            generation = (expected_generations or {}).get(name)
            if not cid or generation is None:
                refused[name] = "owner release requires captured id and generation"
                continue
            try:
                _record_release(name, cid, generation, reason)
                if _runtime_domain() is None:
                    refused[name] = "runtime domain unknown; owner release needs an identity-verified retry"
            except OSError as exc:
                refused[name] = f"could not persist owner release: {exc}"
        if refused:
            _log.warning("Owner release refused: %s", refused)
    out = reconcile(Scope(names=set(names), owner_release=owner_release,
                          expected_ids=dict(expected_ids or {}),
                          expected_generations=dict(expected_generations or {})),
                    wait=wait, reason=reason)
    if out is not None:
        out.release_refused.update(refused)
    return out


# ---------------------------------------------------------------------------
# Persisted outcome (failures stay visible and retryable)
# ---------------------------------------------------------------------------

def _state_file() -> Path:
    domain = _runtime_domain()
    if domain is None:
        return container_mod.container_state_dir() / "reaper.json"
    key = hashlib.sha256(json.dumps(domain, sort_keys=True).encode()).hexdigest()[:16]
    return container_mod.container_state_dir() / f"reaper-{key}.json"


def last_state() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except (OSError, ValueError):
        return {}


def _record(out: Outcome, scope: Scope, reason: str,
            inventory: set[str] | None = None) -> None:
    """Persist the outcome; *inventory* (full-scope passes) prunes failures
    for containers that no longer exist."""
    prev = last_state()
    failures = dict(prev.get("failures") or {})
    domain = _runtime_domain()
    if inventory is not None and domain is not None:
        failures = {k: v for k, v in failures.items()
                    if k in inventory or k.startswith("push proxy ")}
    for proxy in out.proxies_released:
        failures.pop(f"push proxy {proxy}", None)
    if "push proxy sweep" not in out.failures:
        failures.pop("push proxy sweep", None)
    for d in out.decisions:
        if domain is None:
            continue  # unknown inventory domain cannot retire legacy failures
        previous = failures.get(d.info.name, {})
        if (d.info.name in out.removed or
                previous.get("id") and previous["id"] != d.info.id or
                previous.get("owner_release") and
                restart_generation(d.info.name) not in (None, previous.get("generation", ""))):
            failures.pop(d.info.name, None)
    ids = {d.info.name: d.info.id for d in out.decisions}
    for name, err in out.failures.items():
        failures[name] = {"error": err, "at": int(time.time()), "reason": reason}
        if name in out.released_failures:
            failures[name]["owner_release"] = True
            if ids.get(name):
                failures[name]["id"] = ids[name]
            decision = next((d for d in out.decisions if d.info.name == name), None)
            if decision and decision.release_generation is not None:
                failures[name]["generation"] = decision.release_generation
    state = {
        "last_run": int(time.time()),
        "last_reason": reason,
        "last_scope": out.scope,
        "last_summary": out.summary(),
        "removed": out.removed,
        "failures": failures,
    }
    try:
        f = _state_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        os.replace(tmp, f)
    except OSError:
        _log.debug("could not record reaper state", exc_info=True)


def pending_failures() -> dict[str, dict]:
    failures = dict(last_state().get("failures") or {})
    for name, rec in pending_releases().items():
        failures.setdefault(name, {**rec, "owner_release": True,
                                   "error": "owner release pending; retry with pm container reap"})
    for _, rec in _release_records():
        if rec.get("domain_required") and rec.get("runtime_domain") is None:
            failures.setdefault(rec["name"], {**rec, "owner_release": False,
                "error": "release runtime domain unknown; inspect ownership before retrying cleanup"})
    return failures
