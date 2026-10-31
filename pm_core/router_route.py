"""Run sessions through a host-local router (an Anthropic-compatible
endpoint that holds its own upstream credentials).

A *route* is a ``type: router`` provider in ``~/.pm/providers.yaml`` (see
pm_core.providers).  It is selected like any model, per role: every role
in ``model_config.SESSION_TYPES`` may be routed, and the setting is
explicit -- a role with no setting of its own follows its parent role,
and with nothing configured at all runs plain ``claude`` on the CLI
default.  For example

    pm model set impl provider:<name> --project
    pm model set signoff provider:<name> --project
    pm model set qa_scenario provider:<name> --project

or per PR (``pm pr model set <pr> provider:<name> [--role ...]``).  How the
router picks its upstream is its own business; pm only ever passes the
provider's ``api_base`` and model names to Claude -- never a token.

This module owns everything route-specific outside the launch command:

  * :func:`describe` -- the ``route=... model=... via=...`` line shown in
    session logs and status so the selection is visible without
    credentials;
  * :func:`setup_problem` -- the provider settings a launch cannot work
    without.  :func:`launch_parts` raises :class:`RouteSetupError` for them,
    so the session fails like any other launch of a misconfigured provider
    and never falls back to another provider or account;
  * :func:`check_route` -- the diagnostic behind ``pm provider test`` /
    ``show`` and the TUI provider list (is the router answering now?).
    Launches do not consult it: a router that is down is an API failure
    inside the session, handled like one on the default provider;
  * the host side of the container bridge (pm_core.route_bridge):
    containers run under slirp4netns and cannot reach the host loopback,
    so the router is exposed to them only through a 0600 Unix socket in a
    0700 directory that is bind-mounted into route-enabled containers.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from pm_core import route_bridge
from pm_core.paths import configure_logger, pm_home
from pm_core.providers import (ProviderConfig, ProviderEntryError,
                               ProviderNotFoundError,
                               ProvidersFileUnreadableError, get_provider,
                               launch_env)

_log = configure_logger("pm.router_route")

# The QA session types that run in scenario containers (refiner, worker):
# a scenario container mounts the bridge for whichever of them is routed.
# Placement only -- routing eligibility is not limited to these types: any
# role in the model-config set may select a provider, on the host or
# through the bridge.
SCENARIO_CONTAINER_TYPES = ("qa_concretize", "qa_scenario")
# Session types that run inside a pm container in container mode, so a
# route reaches them through the container bridge: impl, review and
# sign-off (wrap_claude_cmd) and the QA refiner/worker (scenario
# containers).  Every other type (planner, s0, verifier, finalizer, merge)
# runs on the host.  Placement only: it decides the launch path and the
# bridge mount, never whether a role may be routed.
CONTAINER_SESSION_TYPES = ("impl", "review", "signoff") + SCENARIO_CONTAINER_TYPES
# A PR's own override wins over the project setting, so a remedy that
# moves a session off the route names it first.
_PR_OVERRIDE_REMEDY = ("change the PR's model setting if it selects this "
                       "route ('pm pr model show <pr>')")
# How to move sessions off the route, quoted in remedies.
_OFF_ROUTE_REMEDY = (f"move its sessions off this route: {_PR_OVERRIDE_REMEDY}"
                     ", or 'pm model set <session-type> <model> --project'")

_BRIDGE_DIRNAME = "route-bridge"
# Unix socket paths are limited to 107 bytes.
_SOCK_PATH_MAX = 100
_bridge_lock = threading.Lock()


class RouteSetupError(ProviderEntryError):
    """A router provider whose own settings cannot launch a session (no
    model, an unusable api_base or launcher, a container bridge that cannot
    be set up).  A ProviderNotFoundError, so every launch surface reports
    it as it reports a missing provider instead of launching elsewhere."""


@dataclass
class RouteStatus:
    """Outcome of :func:`check_route`.

    ``route`` is None when the session is not routed -- that is always
    ``ok``.
    """
    ok: bool
    route: str | None = None
    problem: str = ""
    remedy: str = ""

    def message(self) -> str:
        if self.ok:
            return ""
        label = f"route '{self.route}'" if self.route else "route"
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


def setup_problem(cfg: ProviderConfig, *,
                  container: bool) -> tuple[str, str] | None:
    """``(problem, remedy)`` when router *cfg*'s settings cannot launch a
    session (in a container when *container*), else None.

    Settings only: whether the router answers right now is not checked
    (see :func:`check_route`).
    """
    where = pm_home() / "providers.yaml"
    if not cfg.model:
        return ("no model configured",
                f"set its 'model' in {where} "
                f"('pm provider edit {cfg.name} --model <model>')")
    try:
        router_address(cfg)
    except ValueError as exc:
        return str(exc), f"fix its api_base in {where}"
    if not container and cfg.launcher:
        launcher = os.path.expanduser(cfg.launcher)
        if not (os.path.isfile(launcher) and os.access(launcher, os.X_OK)):
            return (f"launcher {cfg.launcher} is not an executable file",
                    f"install it or remove 'launcher' from {where}")
    return None


def _setup_error(cfg: ProviderConfig, problem: str,
                 remedy: str) -> RouteSetupError:
    return RouteSetupError(f"provider '{cfg.name}': {problem}. "
                           f"Remedy: {remedy}")


def require_setup(resolution, *, container: bool = False) -> None:
    """Raise :class:`~pm_core.providers.ProviderNotFoundError` (a
    :class:`RouteSetupError` for a router's own settings) when
    *resolution*'s provider cannot launch a session."""
    cfg = router_for(resolution)
    if cfg is not None:
        bad = setup_problem(cfg, container=container)
        if bad:
            raise _setup_error(cfg, *bad)


def launch_parts(cfg: ProviderConfig, *,
                 container: bool) -> tuple[str, dict[str, str], str]:
    """``(prefix, env, exe)`` for a claude launch on router *cfg*.

    In a container: the bridge-ensure step (``prefix`` ends in ``&&``),
    ``ANTHROPIC_BASE_URL`` pointed at the in-container forwarder and plain
    ``claude``.  On the host: no prefix, the router env and the route's
    ``launcher`` when configured.  Raises :class:`RouteSetupError` when
    :func:`setup_problem` finds one.
    """
    bad = setup_problem(cfg, container=container)
    if bad:
        raise _setup_error(cfg, *bad)
    env = cfg.env_vars()
    if container:
        env["ANTHROPIC_BASE_URL"] = container_base_url(cfg)
        return container_ensure_cmd(cfg) + " && ", env, "claude"
    exe = (shlex.quote(os.path.expanduser(cfg.launcher)) if cfg.launcher
           else "claude")
    return "", env, exe


def bridge_host_argv(sock: Path, host: str, port: int) -> list[str]:
    """argv for the detached host bridge: this install's bridge file in
    isolated mode, so neither the caller's cwd nor PYTHONPATH can swap in
    another pm_core."""
    return [sys.executable, "-I", str(Path(route_bridge.__file__).resolve()),
            "host", str(sock), host, str(port)]


def describe(resolution, *, container: bool = False) -> str:
    """One-line, credential-free description of where a session runs."""
    effort = getattr(resolution, "effort", None) or "(default)"
    try:
        cfg = router_for(resolution)
    except ProviderEntryError:
        return (f"route={resolution.provider} (INVALID ENTRY in "
                f"providers.yaml) effort={effort}")
    except ProvidersFileUnreadableError:
        return (f"route={resolution.provider} (providers.yaml UNREADABLE) "
                f"effort={effort}")
    except ProviderNotFoundError:
        return (f"route={resolution.provider} (NOT CONFIGURED) "
                f"effort={effort}")
    if cfg is None:
        if getattr(resolution, "provider", None):
            return (f"route=provider:{resolution.provider} "
                    f"model={resolution.model or '(provider)'} effort={effort}")
        return (f"route=none model={resolution.model or '(default)'} "
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


def _secure_bridge_dir(route: str) -> Path:
    """Create the route's bridge dir as a private (0700) directory.

    Raises OSError unless it is a real directory owned by this user: it
    is bind-mounted into containers, so a pre-planted symlink (possible
    for the shared /tmp fallback) must never redirect that mount.
    """
    d = bridge_dir(route)
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = os.lstat(d)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise OSError(f"{d} is not a directory owned by uid {os.getuid()}")
    os.chmod(d, 0o700)
    return d


def ensure_host_bridge(cfg: ProviderConfig) -> Path:
    """Start the host-side socket -> router bridge if it is not running.

    The bridge is a detached process (survives TUI restarts) shared by
    every container on the route.  Returns the socket path; callers check
    :func:`route_bridge.unix_connectable` for liveness.
    """
    with _bridge_lock:
        d = _secure_bridge_dir(cfg.name)
        sock = d / route_bridge.SOCKET_NAME
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


def container_mounts(resolution, *, strict: bool = False) -> dict[Path, str]:
    """Extra rw mounts a container needs for *resolution*'s route.

    Empty when it is not a router provider.  Starts the host bridge so the
    bind source exists before the container is created.  *strict* raises
    (:class:`~pm_core.providers.ProviderNotFoundError` /
    :class:`RouteSetupError`) when the provider or the bridge cannot be
    set up.  Otherwise such a problem leaves the mount out, or mounts the
    empty directory: the session's in-container bridge step then fails
    and its launch fails with it.
    """
    try:
        cfg = router_for(resolution)
    except ProviderNotFoundError:
        if strict:
            raise
        return {}
    if cfg is None:
        return {}
    try:
        sock = ensure_host_bridge(cfg)
        if strict and not route_bridge.unix_connectable(str(sock)):
            raise OSError(f"host route bridge at {sock} is not accepting "
                          "connections")
    except (OSError, ValueError) as exc:
        if strict:
            raise _setup_error(
                cfg, f"cannot set up the host route bridge: {exc}",
                f"run 'pm provider test {cfg.name} --container' on the "
                "host and fix what it reports") from exc
        _log.warning("could not start route bridge for %s", cfg.name,
                     exc_info=True)
        # Still mount the (empty) dir so a bridge started later reaches
        # this container -- but only a dir that is safe to mount.
        try:
            sock = _secure_bridge_dir(cfg.name) / route_bridge.SOCKET_NAME
        except OSError:
            _log.warning("route bridge dir for %s is unsafe to mount",
                         cfg.name, exc_info=True)
            return {}
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
# Diagnostic (pm provider test / show, TUI provider list)
# ---------------------------------------------------------------------------

def check_route(resolution, *, container: bool = False,
                container_name: str | None = None) -> RouteStatus:
    """Report whether *resolution*'s route works right now.

    Always ok for unrouted resolutions.  For a router provider checks its
    settings (:func:`setup_problem`), the router's TCP port and, for
    containers, the host bridge, the container's socket mount and the
    in-container forwarder.  Credentials are not pm's: the router (or
    whatever signs it in) manages them.  *container_name* implies
    *container*.  A diagnostic only: launches neither run nor wait on it.
    """
    container = container or bool(container_name)
    try:
        cfg = router_for(resolution)
    except ProviderNotFoundError as exc:
        return RouteStatus(
            False, getattr(resolution, "provider", None), problem=str(exc),
            remedy=((f"fix {pm_home() / 'providers.yaml'} by hand"
                     if isinstance(exc, ProvidersFileUnreadableError) else
                     "configure the provider on this host")
                    + f", or {_OFF_ROUTE_REMEDY}"))
    if cfg is None:
        return RouteStatus(True)

    def fail(problem: str, remedy: str) -> RouteStatus:
        return RouteStatus(False, cfg.name, problem=problem, remedy=remedy)

    bad = setup_problem(cfg, container=container)
    if bad:
        return fail(*bad)
    host, port = router_address(cfg)

    if not route_bridge.tcp_connectable(host, port):
        return fail(f"router not reachable at {host}:{port}",
                    cfg.remedy or
                    (f"start the router listening on {host}:{port} (or fix "
                     "the provider's api_base)"))

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
                            "remove the container so its next launch "
                            "creates it with the mount")
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
    prefix, env, exe = launch_parts(cfg, container=container)
    env, unset_vars = launch_env(cfg, env, cfg.model)
    unset = "".join(f"-u {v} " for v in unset_vars)
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
    if not tpath.exists():
        # The session id is unique: find the transcript wherever Claude's
        # cwd mangling put it rather than report it missing.
        found = sorted((Path.home() / ".claude" / "projects").glob(
            f"*/{sid}.jsonl"))
        if found:
            tpath = found[0]
    out["transcript"] = str(tpath) if tpath.exists() else None
    out["transcript_models"] = _transcript_models(tpath)
    ev = None
    for _ in range(20):
        ev = hook_events.read_event(sid)
        if ev:
            break
        time.sleep(0.25)
    out["hook_event"] = (ev or {}).get("event_type")
    ran = r.returncode == 0 and not payload.get("is_error")
    # Every model Claude requested must be the route's own: any other name
    # (a background or subagent call that escaped the alias pins) may have
    # been sent to whatever the router does with unknown names.
    routed = (bool(out["models"])
              and all(m == cfg.model for m in out["models"]))
    # The probe is evidence that routed sessions keep their transcript and
    # hooks, so missing evidence is a failure, not a vacuous pass.
    missing = []
    if out["transcript"] is None:
        missing.append(f"no transcript for session {sid} under "
                       f"{tpath.parent.parent} (expected {tpath})")
    elif not out["transcript_models"]:
        missing.append(f"transcript {tpath} records no model")
    if not out["hook_event"]:
        missing.append(f"no pm hook event recorded for session {sid} "
                       f"(expected {hook_events.event_path(sid)}); check "
                       "that pm's Claude hooks are installed")
    if ran and routed and missing and not out.get("error"):
        out["error"] = "missing evidence: " + "; ".join(missing)
    out["ok"] = (ran and routed and not missing
                 and all(model_on_route(cfg, m)
                         for m in out["transcript_models"]))
    return out


def model_on_route(cfg: ProviderConfig, model: str) -> bool:
    """Whether a model the transcript records is one the route may report.

    The transcript holds what the backend answered with, which a router
    may rename (strip its own prefix, pick a dated id).  pm assumes no
    such convention: without ``probe_models`` any recorded model is
    accepted (and shown); with it, the recorded model must be the route's
    ``model`` (a ``[...]`` context-window suffix is a Claude Code selector,
    never part of the name sent) or one of ``probe_models``."""
    if not cfg.probe_models:
        return True
    base = re.sub(r"\[[^\]]*\]$", "", cfg.model)
    return model in (cfg.model, base, *cfg.probe_models)
