"""Route QA execution workers through a host-local account router.

A *route* is a ``type: router`` provider in ``~/.pm/providers.yaml`` (see
pm_core.providers) selected for the ``qa_scenario`` session type only:

    pm model set qa_scenario provider:claude-work --effort high --project

The router (e.g. the claude-mixed router on ``127.0.0.1:8790``) picks the
upstream account from the model prefix (``work/...``) and holds that
account's credentials, so pm only ever passes the router URL and model
names to Claude -- never a token.

This module owns everything route-specific outside the launch command:

  * :func:`describe` -- the ``route=... model=... via=...`` line shown in QA
    logs and status so the selection is visible without credentials;
  * :func:`check_route` -- preflight used before every worker launch,
    retry and queued launch.  QA never launches a worker on a route that
    fails it (no silent fallback to the main account);
  * the host side of the container bridge (pm_core.route_bridge): QA
    containers run under slirp4netns and cannot reach the host loopback,
    so the router is exposed to them only through a 0600 Unix socket in a
    0700 directory that is bind-mounted into route-enabled QA containers.
"""

from __future__ import annotations

import datetime as _dt
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from pm_core import route_bridge
from pm_core.paths import configure_logger, pm_home
from pm_core.providers import ProviderConfig, ProviderNotFoundError, get_provider

_log = configure_logger("pm.worker_route")

# The only session type whose launches are routed / gated.
WORKER_SESSION_TYPE = "qa_scenario"

_BRIDGE_DIRNAME = "route-bridge"
# Unix socket paths are limited to 107 bytes.
_SOCK_PATH_MAX = 100
# Credentials expiring within this window count as expired: a worker may
# run for a long time after launch.
_EXPIRY_MARGIN_S = 120
# refresh_command is attempted at most this often per route.
_REFRESH_COOLDOWN_S = 300
_last_refresh: dict[str, float] = {}
_bridge_lock = threading.Lock()


@dataclass
class RouteStatus:
    """Outcome of :func:`check_route`.

    ``route`` is None when workers are not routed (main account) -- that
    is always ``ok``.
    """
    ok: bool
    route: str | None = None
    problem: str = ""
    remedy: str = ""

    def message(self) -> str:
        if self.ok:
            return ""
        label = f"work route '{self.route}'" if self.route else "work route"
        return f"{label} unavailable: {self.problem}. Remedy: {self.remedy}"


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------

def router_for(resolution) -> ProviderConfig | None:
    """Return the router provider a model resolution selects, else None.

    Raises :class:`ProviderNotFoundError` when the resolution names a
    provider that is not configured (rather than silently using the
    built-in claude provider).
    """
    name = getattr(resolution, "provider", None)
    if not name:
        return None
    cfg = get_provider(name, strict=True)
    return cfg if cfg.type == "router" else None


def router_address(cfg: ProviderConfig) -> tuple[str, int]:
    """(host, port) of the router from its ``api_base``."""
    u = urlparse(cfg.api_base)
    if not u.hostname:
        raise ValueError(f"api_base {cfg.api_base!r} has no host")
    port = u.port or (443 if u.scheme == "https" else 80)
    return u.hostname, port


def container_base_url(cfg: ProviderConfig) -> str:
    """ANTHROPIC_BASE_URL inside a container: the in-container forwarder
    always listens on 127.0.0.1 at the router's port."""
    u = urlparse(cfg.api_base)
    _, port = router_address(cfg)
    return f"{u.scheme or 'http'}://127.0.0.1:{port}{u.path.rstrip('/')}"


def container_ensure_cmd(cfg: ProviderConfig) -> str:
    """Shell step run in the container before claude (``ensure && claude``).

    Runs the stdlib-only bridge *file* from the read-only /opt/pm-src
    mount in isolated mode: ``-m pm_core...`` would import whatever
    pm_core the cwd (/workspace, the project under test) holds.
    """
    from pm_core.container import _CONTAINER_PM_SRC
    _, port = router_address(cfg)
    sock = f"{route_bridge.CONTAINER_SOCKET_DIR}/{route_bridge.SOCKET_NAME}"
    script = f"{_CONTAINER_PM_SRC}/pm_core/route_bridge.py"
    return (f"python3 -I {script} "
            f"ensure {sock} {port} {shlex.quote(cfg.name)}")


def bridge_host_argv(sock: Path, host: str, port: int) -> list[str]:
    """argv for the detached host bridge: this install's bridge file in
    isolated mode, so neither the caller's cwd nor PYTHONPATH can swap in
    another pm_core."""
    return [sys.executable, "-I", str(Path(route_bridge.__file__).resolve()),
            "host", str(sock), host, str(port)]


def describe(resolution, *, container: bool = False) -> str:
    """One-line, credential-free description of where workers run."""
    effort = getattr(resolution, "effort", None) or "(default)"
    try:
        cfg = router_for(resolution)
    except ProviderNotFoundError:
        return (f"route={resolution.provider} (NOT CONFIGURED) "
                f"effort={effort}")
    if cfg is None:
        if getattr(resolution, "provider", None):
            return (f"route=provider:{resolution.provider} "
                    f"model={resolution.model or '(provider)'} effort={effort}")
        return (f"route=main model={resolution.model or '(default)'} "
                f"effort={effort} via=claude")
    if container:
        via = "container-bridge"
    elif cfg.launcher:
        via = f"launcher:{cfg.launcher}"
    else:
        via = "host"
    model = getattr(resolution, "model", None) or cfg.model or "(unset)"
    return f"route={cfg.name} model={model} effort={effort} via={via}"


# ---------------------------------------------------------------------------
# Host bridge
# ---------------------------------------------------------------------------

def bridge_dir(route: str) -> Path:
    """Host directory holding the route's bridge socket.

    The directory (not the socket) is what containers mount, so it is
    never removed: a restarted bridge's new socket stays visible to
    containers that are already running.
    """
    d = pm_home() / _BRIDGE_DIRNAME / route
    if len(str(d / route_bridge.SOCKET_NAME)) > _SOCK_PATH_MAX:
        digest = hashlib.sha256(route.encode()).hexdigest()[:12]
        d = pm_home() / _BRIDGE_DIRNAME / digest
        if len(str(d / route_bridge.SOCKET_NAME)) > _SOCK_PATH_MAX:
            d = Path(f"/tmp/pm-route-{os.getuid()}-{digest}")
    return d


def bridge_socket(route: str) -> Path:
    return bridge_dir(route) / route_bridge.SOCKET_NAME


def ensure_host_bridge(cfg: ProviderConfig) -> Path:
    """Start the host-side socket -> router bridge if it is not running.

    The bridge is a detached process (survives TUI restarts) shared by
    every container on the route.  Returns the socket path; callers check
    :func:`route_bridge.unix_connectable` for liveness.
    """
    d = bridge_dir(cfg.name)
    sock = d / route_bridge.SOCKET_NAME
    with _bridge_lock:
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
        if route_bridge.unix_connectable(str(sock)):
            return sock
        host, port = router_address(cfg)
        # Cross-process lock: two QA loops must not race two bridges onto
        # one socket path.
        with open(d / ".lock", "w") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)
            if route_bridge.unix_connectable(str(sock)):
                return sock
            proc = subprocess.Popen(
                bridge_host_argv(sock, host, port),
                start_new_session=True, cwd="/",
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(50):
                if route_bridge.unix_connectable(str(sock)):
                    break
                time.sleep(0.1)
            else:
                _log.warning("route bridge for %s (pid=%d) did not come up "
                             "at %s", cfg.name, proc.pid, sock)
                return sock
            _log.info("route bridge for %s started: pid=%d %s -> %s:%d",
                      cfg.name, proc.pid, sock, host, port)
    return sock


def container_mounts(resolution) -> dict[Path, str]:
    """Extra rw mounts a QA container needs for the worker route.

    Empty when workers are not routed.  Starts the host bridge so the
    bind source exists before the container is created.
    """
    try:
        cfg = router_for(resolution)
    except ProviderNotFoundError:
        return {}
    if cfg is None:
        return {}
    try:
        sock = ensure_host_bridge(cfg)
    except (OSError, ValueError):
        _log.warning("could not start route bridge for %s", cfg.name,
                     exc_info=True)
        d = bridge_dir(cfg.name)
        d.mkdir(parents=True, exist_ok=True)
        sock = d / route_bridge.SOCKET_NAME
    return {sock.parent: route_bridge.CONTAINER_SOCKET_DIR}


def container_has_route_mount(name: str) -> bool | None:
    """Whether container *name* has the route socket dir mounted.

    None when it cannot be inspected (e.g. the container is gone).
    """
    from pm_core.container import _run_runtime
    try:
        r = _run_runtime("inspect", "-f",
                         "{{range .Mounts}}{{.Destination}}\n{{end}}", name,
                         check=False, timeout=10)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return route_bridge.CONTAINER_SOCKET_DIR in r.stdout.split()


def ensure_in_container(cfg: ProviderConfig, name: str) -> tuple[bool, str]:
    """Run the in-container ensure step via ``exec``; (ok, stderr text)."""
    from pm_core.container import _run_runtime
    try:
        r = _run_runtime("exec", name, "bash", "-c", container_ensure_cmd(cfg),
                         check=False, timeout=20)
    except Exception as exc:
        return False, str(exc)
    return r.returncode == 0, (r.stderr or "").strip()


# ---------------------------------------------------------------------------
# Credentials (expiry only -- token values are never read into pm state)
# ---------------------------------------------------------------------------

def credentials_expiry(path: str) -> float | None:
    """Epoch seconds at which the OAuth credentials in *path* expire.

    Reads only ``claudeAiOauth.expiresAt``.  None when unknown.  Raises
    FileNotFoundError when the file is missing.
    """
    p = Path(os.path.expanduser(path))
    try:
        data = json.loads(p.read_text())
    except FileNotFoundError:
        raise
    except (OSError, ValueError):
        return None
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    exp = (oauth or {}).get("expiresAt") if isinstance(oauth, dict) else None
    if not isinstance(exp, (int, float)):
        return None
    return exp / 1000.0 if exp > 1e11 else float(exp)


def _fmt_time(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).astimezone().strftime(
        "%Y-%m-%d %H:%M %Z")


def _run_refresh(cfg: ProviderConfig) -> None:
    """Run the route's refresh_command (output discarded: it may print
    account details).  Throttled per route."""
    now = time.monotonic()
    if now - _last_refresh.get(cfg.name, -1e9) < _REFRESH_COOLDOWN_S:
        return
    _last_refresh[cfg.name] = now
    try:
        r = subprocess.run(cfg.refresh_command, shell=True, timeout=120,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        _log.info("route %s: refresh_command exited %d", cfg.name, r.returncode)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log.warning("route %s: refresh_command failed: %s", cfg.name, exc)


def _signin_remedy(cfg: ProviderConfig) -> str:
    if cfg.remedy:
        return cfg.remedy
    hint = (f"run '{cfg.refresh_command}' or sign in again"
            if cfg.refresh_command else "sign in to that account again")
    return (f"{hint} so {cfg.credentials_file} holds a valid session; QA "
            f"launches the worker automatically once it is valid "
            f"(or run workers on the main account: 'pm model set "
            f"{WORKER_SESSION_TYPE} <model> --project')")


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

def check_route(resolution, *, container: bool = False,
                container_name: str | None = None,
                try_refresh: bool = True) -> RouteStatus:
    """Validate that a worker can be launched on *resolution*'s route.

    Always ok for unrouted resolutions.  For a router provider checks the
    config, the router's TCP port, credential expiry, the launcher (host
    workers) and, for containers, the host bridge, the container's socket
    mount and the in-container forwarder.
    """
    try:
        cfg = router_for(resolution)
    except ProviderNotFoundError as exc:
        return RouteStatus(
            False, getattr(resolution, "provider", None), problem=str(exc),
            remedy=(f"configure the provider on this host, or run workers on "
                    f"the main account with 'pm model set "
                    f"{WORKER_SESSION_TYPE} <model> --project'"))
    if cfg is None:
        return RouteStatus(True)

    def fail(problem: str, remedy: str) -> RouteStatus:
        return RouteStatus(False, cfg.name, problem=problem, remedy=remedy)

    where = pm_home() / "providers.yaml"
    if not cfg.model:
        return fail("no model configured",
                    f"set 'model: work/<model>' for it in {where}")
    try:
        host, port = router_address(cfg)
    except ValueError as exc:
        return fail(str(exc), f"fix its api_base in {where}")

    if not container and cfg.launcher:
        launcher = os.path.expanduser(cfg.launcher)
        if not (os.path.isfile(launcher) and os.access(launcher, os.X_OK)):
            return fail(f"launcher {cfg.launcher} is not an executable file",
                        f"install it or remove 'launcher' from {where}")

    if not route_bridge.tcp_connectable(host, port):
        return fail(f"router not reachable at {host}:{port}",
                    "start the router (e.g. the claude-mixed router "
                    f"listening on {host}:{port}); QA launches the worker "
                    "automatically once it answers")

    if cfg.credentials_file:
        try:
            exp = credentials_expiry(cfg.credentials_file)
        except FileNotFoundError:
            return fail(f"credentials file {cfg.credentials_file} not found",
                        _signin_remedy(cfg))
        if exp is not None and exp <= time.time() + _EXPIRY_MARGIN_S:
            if try_refresh and cfg.refresh_command:
                _run_refresh(cfg)
                try:
                    exp = credentials_expiry(cfg.credentials_file)
                except FileNotFoundError:
                    exp = 0.0
            if exp is not None and exp <= time.time() + _EXPIRY_MARGIN_S:
                return fail(f"account sign-in expired at {_fmt_time(exp)}",
                            _signin_remedy(cfg))

    if container:
        try:
            sock = ensure_host_bridge(cfg)
        except OSError as exc:
            return fail(f"cannot start the host route bridge: {exc}",
                        "check permissions on "
                        f"{bridge_dir(cfg.name)}")
        if not route_bridge.unix_connectable(str(sock)):
            return fail(f"host route bridge at {sock} is not accepting "
                        "connections",
                        f"run 'pm provider test {cfg.name} --container' on "
                        "the host and fix what it reports")
        if container_name:
            mounted = container_has_route_mount(container_name)
            if mounted is False:
                return fail(f"container {container_name} was created without "
                            "the route socket mount",
                            "restart QA for this PR so its containers are "
                            "recreated with the route mount")
            if mounted:
                ok, err = ensure_in_container(cfg, container_name)
                if not ok:
                    return fail(f"in-container forwarder failed in "
                                f"{container_name}: {err or 'unknown error'}",
                                f"run 'pm provider test {cfg.name} "
                                "--container' and fix what it reports")

    return RouteStatus(True, cfg.name)


# ---------------------------------------------------------------------------
# Live probe (pm provider test --live)
# ---------------------------------------------------------------------------

PROBE_PROMPT = "Reply with exactly: ok"


def _probe_shell_cmd(cfg: ProviderConfig, session_id: str, *,
                     container: bool) -> str:
    """Tools-disabled one-shot claude call through the route."""
    env = cfg.env_vars()
    exe = "claude"
    prefix = ""
    if container:
        env["ANTHROPIC_BASE_URL"] = container_base_url(cfg)
        prefix = container_ensure_cmd(cfg) + " && "
    elif cfg.launcher:
        exe = shlex.quote(os.path.expanduser(cfg.launcher))
    unset = "".join(f"-u {v} " for v in cfg.unset_env_vars())
    assigns = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
    return (f"{prefix}env {unset}{assigns} {exe} -p {shlex.quote(PROBE_PROMPT)}"
            f" --model {shlex.quote(cfg.model)} --tools '' --output-format json"
            f" --session-id {session_id}")


def _transcript_models(path: Path) -> list[str]:
    models: list[str] = []
    try:
        for line in path.read_text().splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            m = ((rec.get("message") or {}).get("model")
                 if isinstance(rec, dict) else None)
            if m and m not in models:
                models.append(m)
    except OSError:
        pass
    return models


def live_probe(cfg: ProviderConfig, *, container_name: str | None = None,
               cwd: str | None = None, timeout: float = 180) -> dict:
    """Run a harmless prompt through the route and report what came back.

    Returns ``ok``, ``exit``, ``result`` (the reply), ``models`` (models
    claude reports it used), ``transcript`` / ``transcript_models`` (the
    JSONL claude wrote under ~/.claude/projects) and ``hook_event`` (the
    last pm hook event type for the session).  Never includes request
    headers or credentials.
    """
    import tempfile
    import uuid
    from pm_core import hook_events
    from pm_core.claude_launcher import transcript_path_for

    sid = str(uuid.uuid4())
    if container_name:
        from pm_core.container import _CONTAINER_WORKDIR, _get_runtime
        run_cwd = _CONTAINER_WORKDIR
        inner = _probe_shell_cmd(cfg, sid, container=True)
        argv = [_get_runtime(), "exec", "-w", run_cwd, container_name,
                "bash", "-c", inner]
        popen_cwd = None
    else:
        run_cwd = cwd or tempfile.mkdtemp(prefix="pm-route-probe-")
        argv = ["bash", "-c", _probe_shell_cmd(cfg, sid, container=False)]
        popen_cwd = run_cwd
    out: dict = {"session_id": sid}
    try:
        r = subprocess.run(argv, cwd=popen_cwd, capture_output=True,
                           text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        out.update(ok=False, exit=None, error=f"timed out after {timeout:.0f}s")
        return out
    out["exit"] = r.returncode
    payload: dict = {}
    try:
        payload = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        pass
    out["result"] = payload.get("result")
    out["models"] = sorted((payload.get("modelUsage") or {}).keys())
    if r.returncode != 0 or payload.get("is_error"):
        out["error"] = (payload.get("result") or r.stderr.strip()[-800:]
                        or "no output")
    tpath = transcript_path_for(run_cwd, sid)
    out["transcript"] = str(tpath) if tpath.exists() else None
    out["transcript_models"] = _transcript_models(tpath)
    ev = None
    for _ in range(20):
        ev = hook_events.read_event(sid)
        if ev:
            break
        time.sleep(0.25)
    out["hook_event"] = (ev or {}).get("event_type")
    out["ok"] = (r.returncode == 0 and not payload.get("is_error")
                 # Requested models must all carry the route prefix: an
                 # unprefixed one would have gone to the router's default
                 # (main) account.
                 and bool(out["models"])
                 and all(m == cfg.model for m in out["models"])
                 and all(model_on_route(cfg, m)
                         for m in out["transcript_models"]))
    return out


def model_on_route(cfg: ProviderConfig, model: str) -> bool:
    """Whether *model* is the route's model as requested (``work/x``) or
    as the upstream names it after the router strips the prefix (``x``,
    which is what lands in the transcript)."""
    return model == cfg.model or cfg.model.endswith("/" + model)
