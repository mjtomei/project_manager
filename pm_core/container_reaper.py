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

import json
import os
import re
import subprocess
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


def is_retained(name: str) -> bool:
    return (_retain_dir() / name).exists()


def retain(name: str, note: str = "") -> None:
    d = _retain_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps({"note": note, "at": int(time.time())}))


def unretain(name: str) -> bool:
    try:
        (_retain_dir() / name).unlink()
        return True
    except FileNotFoundError:
        return False


def retained_names() -> list[str]:
    try:
        return sorted(p.name for p in _retain_dir().iterdir())
    except OSError:
        return []


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
    try:
        ps = container_mod._run_runtime(
            "ps", "-a", "--filter", f"name={container_mod.CONTAINER_PREFIX}",
            "--format", "{{.Names}}", check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if ps.returncode != 0:
        return None
    names = [ln.strip() for ln in (ps.stdout or "").splitlines()
             if ln.strip().startswith(container_mod.CONTAINER_PREFIX)]
    if not names:
        return []
    fmt = ("{{.Name}}\t{{.Id}}\t{{.State.Running}}\t{{.State.Status}}\t"
           "{{json .Config.Labels}}")
    try:
        insp = container_mod._run_runtime("inspect", "--format", fmt, *names,
                                          check=False, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out: list[ContainerInfo] = []
    seen: set[str] = set()
    # A container that vanished between ps and inspect makes inspect exit
    # non-zero but still print the others — parse whatever came back.
    for line in (insp.stdout or "").splitlines():
        parts = line.split("\t", 4)
        if len(parts) < 5:
            continue
        name = parts[0].lstrip("/").strip()
        try:
            labels = json.loads(parts[4]) or {}
        except ValueError:
            labels = {}
        info = _info_from(name, parts[1].strip(), parts[2].strip() == "true",
                          parts[3].strip(), {str(k): str(v) for k, v in labels.items()})
        if info is not None and name not in seen:
            seen.add(name)
            out.append(info)
    return out


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
    if server.socket_file and not os.path.exists(server.socket_file):
        return _PaneSnapshot(panes=[])  # no server → no panes
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
        if "no server running" in err or "error connecting" in err and "no such file" in err:
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
    for server in _servers_for(info):
        snap = cache.get(server, fresh=fresh)
        if snap.panes is None:
            indeterminate = True
            continue
        for pane_id, _sess, cmd in snap.panes:
            if any(p.search(cmd) for p in pats):
                owners.append(pane_id)
    return owners, indeterminate


def live_owner_panes(name: str, container_id: str = "") -> list[str]:
    """Live tmux panes started for container *name* (fresh query)."""
    info = ContainerInfo(name=name, id=container_id)
    parsed = container_mod.parse_container_name(name)
    if parsed:
        info.session_tag = parsed.session_tag
    owners, _ = _owner_panes(info, _PaneCache(), fresh=True)
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

    def matches(self, info: ContainerInfo) -> bool:
        if self.names is not None and info.name not in self.names:
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
        return ", ".join(bits) or "all pm containers"


@dataclass
class Decision:
    info: ContainerInfo
    action: str  # "remove" | "keep"
    reason: str


@dataclass
class Outcome:
    scope: str = ""
    decisions: list[Decision] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)
    proxies_released: list[str] = field(default_factory=list)
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
        return head + (f" ({'; '.join(counts)})" if counts else "")


def _decide(info: ContainerInfo, scope: Scope, cache: _PaneCache,
            prs: _PrStatus, now: float) -> Decision:
    if is_retained(info.name) and not scope.include_retained:
        return Decision(info, "keep", "explicitly retained (pm container retain)")
    owners, indeterminate = _owner_panes(info, cache)
    if owners:
        return Decision(info, "keep", f"owned by live pane {', '.join(owners)}")
    if info.created is not None and now - info.created < LAUNCH_GRACE:
        return Decision(info, "keep", "launching (no pane yet)")
    with container_mod.launch_lock(info.name, timeout=0) as free:
        if not free:
            return Decision(info, "keep", "launch in progress")
    status = prs.status(info)
    if status in _TERMINAL_PR_STATES:
        return Decision(info, "remove", f"PR {info.pr_id} is {status}, no owning pane")
    if indeterminate:
        return Decision(info, "keep", "tmux server unreachable — ownership unknown")
    if info.session_tag:
        alive = _session_alive(info.session_tag, cache)
        if alive is False:
            return Decision(info, "remove", f"tmux session pm-{info.session_tag} gone")
    what = "QA run finished or superseded" if info.kind == "qa" else "attempt ended"
    return Decision(info, "remove", f"no owning pane ({what})")


def _remove_checked(d: Decision, scope: Scope) -> tuple[bool, str]:
    """Remove *d* after re-checking ownership under its launch lock."""
    info = d.info
    with container_mod.launch_lock(info.name, timeout=0) as free:
        if not free:
            return False, "skipped: launch started concurrently"
        if is_retained(info.name) and not scope.include_retained:
            return False, "skipped: retained concurrently"
        owners, _ = _owner_panes(info, _PaneCache(), fresh=True)
        if owners:
            return False, f"skipped: pane {', '.join(owners)} attached concurrently"
        try:
            container_mod.remove_container(info.name)
        except Exception as e:
            return False, f"error: {e}"
    return True, ""


def _release_unused_proxies(scope: Scope) -> list[str]:
    from pm_core import push_proxy
    released: list[str] = []
    for prox in push_proxy.list_shared_proxies():
        if scope.session_tag and prox["session_tag"] != scope.session_tag:
            continue
        if scope.pr_id and prox["pr_id"] != scope.pr_id:
            continue
        try:
            if push_proxy.release_proxy_if_unused(prox["session_tag"], prox["pr_id"]):
                released.append(f"{prox['session_tag']}/{prox['pr_id']}")
        except Exception:
            _log.warning("proxy release for %s failed", prox, exc_info=True)
    return released


def plan(scope: Scope | None = None) -> Outcome:
    """Classify containers in *scope* without changing anything."""
    scope = scope or Scope()
    out = Outcome(scope=scope.describe(), dry_run=True)
    infos = list_containers()
    if infos is None:
        out.error = f"{container_mod._get_runtime()} is not available"
        return out
    cache, prs, now = _PaneCache(), _PrStatus(), time.time()
    for info in infos:
        if scope.matches(info):
            out.decisions.append(_decide(info, scope, cache, prs, now))
    return out


def _run(scope: Scope, dry_run: bool, reason: str) -> Outcome:
    with container_mod._file_lock("reaper", timeout=0 if reason != "manual" else 60) as got:
        if not got:
            return Outcome(scope=scope.describe(), skipped=True, dry_run=dry_run)
        out = plan(scope)
        out.dry_run = dry_run
        out.running_before = container_mod.running_container_count()
        out.keyring_before = container_mod.keyring_summary()
        if out.error or dry_run:
            return out
        targets = out.to_remove
        if targets:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(REMOVE_WORKERS, len(targets))) as ex:
                results = list(ex.map(lambda d: (d, _remove_checked(d, scope)), targets))
            for d, (ok, msg) in results:
                if ok:
                    out.removed.append(d.info.name)
                elif msg.startswith("error:"):
                    out.failures[d.info.name] = msg[len("error: "):]
                else:
                    d.action, d.reason = "keep", msg
        try:
            out.proxies_released = _release_unused_proxies(scope)
        except Exception:
            _log.warning("proxy sweep failed", exc_info=True)
        out.running_after = container_mod.running_container_count()
        out.keyring_after = container_mod.keyring_summary()
        _record(out, scope, reason)
        if out.removed or out.failures:
            _log.info("reconcile[%s] %s: %s — removed=%s failures=%s", reason,
                      out.scope, out.summary(), out.removed, out.failures)
        return out


_bg_lock = threading.Lock()
_bg_running = False


def reconcile(scope: Scope | None = None, *, dry_run: bool = False,
              wait: bool = True, reason: str = "auto",
              on_done: Callable[[Outcome], None] | None = None) -> Outcome | None:
    """Remove unowned pm containers in *scope* (default: everything).

    ``wait=False`` runs in a daemon thread (coalesced: a pass already
    running in this process absorbs the request) and returns None.  Never
    raises; problems are reported in the returned :class:`Outcome`.
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
        if _bg_running:
            return None
        _bg_running = True

    def _bg() -> None:
        global _bg_running
        try:
            _go()
        finally:
            with _bg_lock:
                _bg_running = False

    threading.Thread(target=_bg, daemon=True, name="pm-container-reaper").start()
    return None


def release_containers(names: list[str], *, reason: str = "release",
                       wait: bool = True) -> Outcome | None:
    """Release specific containers a run owned and no longer needs.

    Goes through the same ownership checks, so a container a human is still
    using (live pane) or retained is kept.
    """
    if not names:
        return Outcome(scope="no containers")
    return reconcile(Scope(names=set(names)), wait=wait, reason=reason)


# ---------------------------------------------------------------------------
# Persisted outcome (failures stay visible and retryable)
# ---------------------------------------------------------------------------

def _state_file() -> Path:
    return container_mod.container_state_dir() / "reaper.json"


def last_state() -> dict:
    try:
        return json.loads(_state_file().read_text())
    except (OSError, ValueError):
        return {}


def _record(out: Outcome, scope: Scope, reason: str) -> None:
    prev = last_state()
    failures = dict(prev.get("failures") or {})
    for d in out.decisions:
        failures.pop(d.info.name, None)
    for name, err in out.failures.items():
        failures[name] = {"error": err, "at": int(time.time()), "reason": reason}
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
    return dict(last_state().get("failures") or {})
