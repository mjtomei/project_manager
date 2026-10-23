"""Tests for QA worker routing through a host router provider.

Covers pm_core.worker_route, pm_core.route_bridge, the router provider
type, the launcher boundary (claude_launcher.build_claude_shell_cmd) and
the QA loop's route gating / role isolation.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from pm_core import route_bridge, worker_route
from pm_core.model_config import ModelResolution, resolve_model_and_provider
from pm_core.providers import (
    ProviderConfig, ProviderNotFoundError, ROUTER_ALIAS_ENV_VARS, get_provider,
)

ROUTE = "claude-work"
MODEL = "work/claude-opus-5-5"


@pytest.fixture
def short_dir():
    # Unix socket paths are limited to ~107 bytes; pytest's tmp_path is long.
    d = tempfile.mkdtemp(prefix="pmrt-", dir="/tmp")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def pm_home_dir(short_dir, monkeypatch):
    """Isolated ~/.pm holding providers.yaml and the route-bridge dir."""
    home = short_dir / "pm"
    home.mkdir()
    for mod in ("pm_core.providers", "pm_core.worker_route"):
        monkeypatch.setattr(f"{mod}.pm_home", lambda: home)
    monkeypatch.delenv("PM_PROVIDER", raising=False)
    monkeypatch.delenv("PM_MODEL", raising=False)
    monkeypatch.delenv("PM_EFFORT", raising=False)
    worker_route._last_refresh.clear()
    return home


def _write_providers(home: Path, **entry):
    import yaml
    base = {"type": "router", "api_base": "http://127.0.0.1:1", "model": MODEL}
    base.update(entry)
    (home / "providers.yaml").write_text(
        yaml.safe_dump({"providers": {ROUTE: base}}))


def _listener():
    """A TCP server on a free loopback port (accepting nothing yet)."""
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(16)
    return s, s.getsockname()[1]


def _creds(path: Path, expires_in_s: float):
    path.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "sk-ant-oat-SECRET-ACCESS",
        "refreshToken": "sk-ant-ort-SECRET-REFRESH",
        "expiresAt": int((time.time() + expires_in_s) * 1000)}}))


PROJECT = {"project": {"model_config": {
    "session_models": {
        "qa": "claude-opus-5-5",
        "qa_planning": "claude-opus-5-5",
        "qa_concretize": f"provider:{ROUTE}",
        "qa_scenario": f"provider:{ROUTE}",
        "qa_verification": "claude-opus-5-5",
        "qa_finalize": "claude-opus-5-5",
        "impl": "claude-opus-5-5",
        "review": "claude-opus-5-5",
        "signoff": "claude-opus-5-5",
    },
    "session_effort": {st: "high" for st in (
        "qa", "qa_planning", "qa_concretize", "qa_scenario",
        "qa_verification", "qa_finalize", "impl", "review", "signoff")},
}}}


# ---------------------------------------------------------------------------
# Provider type
# ---------------------------------------------------------------------------

class TestRouterProvider:
    def test_env_points_at_router_and_pins_every_model(self):
        p = ProviderConfig(name=ROUTE, type="router",
                           api_base="http://127.0.0.1:8790", model=MODEL)
        env = p.env_vars()
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8790"
        # Unprefixed models would reach the router's default (main) account.
        for var in ROUTER_ALIAS_ENV_VARS:
            assert env[var] == MODEL
        assert env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] == "1"
        assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"} & set(env)
        assert p.unset_env_vars() == ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        assert p.model_flag() == MODEL

    def test_alias_override(self):
        p = ProviderConfig(name=ROUTE, type="router", api_base="http://x:1",
                           model=MODEL,
                           alias_models={"ANTHROPIC_SMALL_FAST_MODEL":
                                         "work/claude-haiku-5-5"})
        assert p.env_vars()["ANTHROPIC_SMALL_FAST_MODEL"] == "work/claude-haiku-5-5"

    def test_strict_lookup_raises_for_unconfigured(self, pm_home_dir):
        with pytest.raises(ProviderNotFoundError):
            get_provider("nope", strict=True)
        # Non-strict keeps the historical fallback.
        assert get_provider("nope").name == "claude"

    def test_loads_router_fields(self, pm_home_dir):
        _write_providers(pm_home_dir, launcher="~/bin/claude-mixed",
                         credentials_file="~/.claude-work/.credentials.json",
                         refresh_command="claude-work-ping")
        p = get_provider(ROUTE, strict=True)
        assert (p.type, p.launcher, p.refresh_command) == (
            "router", "~/bin/claude-mixed", "claude-work-ping")


# ---------------------------------------------------------------------------
# Launcher boundary
# ---------------------------------------------------------------------------

class TestResolveProvider:
    def test_router_run_env_drops_stray_keys(self, pm_home_dir, monkeypatch):
        """launch_claude* paths (subprocess env) unset the same variables
        build_claude_shell_cmd removes with ``env -u``."""
        from pm_core.claude_launcher import _resolve_provider
        _write_providers(pm_home_dir, api_base="http://127.0.0.1:8790")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stray")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-stray")
        env, flag, run_env = _resolve_provider(ROUTE)
        assert flag == MODEL
        assert run_env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8790"
        assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"} & set(run_env)

    def test_other_providers_keep_environment(self, pm_home_dir, monkeypatch):
        from pm_core.claude_launcher import _resolve_provider
        import yaml
        (pm_home_dir / "providers.yaml").write_text(yaml.safe_dump(
            {"providers": {"loc": {"type": "local",
                                   "api_base": "http://127.0.0.1:1",
                                   "model": "m"}}}))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stray")
        _, _, run_env = _resolve_provider("loc")
        # The local provider's own key settings are left in place.
        assert run_env["ANTHROPIC_API_KEY"] == ""
        assert run_env["ANTHROPIC_AUTH_TOKEN"] == "ollama"


class TestBuildShellCmd:
    def _build(self, **kw):
        from pm_core.claude_launcher import build_claude_shell_cmd
        with patch("pm_core.paths.skip_permissions_enabled", return_value=False), \
             patch("pm_core.paths.fake_claude_config_for_type", return_value=None), \
             patch("pm_core.claude_launcher.log_shell_command"):
            return build_claude_shell_cmd(**kw)

    def test_host_worker_cmd(self, pm_home_dir):
        _write_providers(pm_home_dir, api_base="http://127.0.0.1:8790",
                         credentials_file="/creds/.credentials.json")
        cmd = self._build(provider=ROUTE, effort="high", session_id="s" * 8)
        assert cmd.startswith(
            "env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN "
            "ANTHROPIC_BASE_URL=http://127.0.0.1:8790 ")
        assert f" claude --model {MODEL} --effort high --session-id" in cmd
        assert "route_bridge" not in cmd
        assert "credentials" not in cmd

    def test_host_launcher_replaces_claude(self, pm_home_dir):
        _write_providers(pm_home_dir, launcher="/opt/bin/claude-mixed")
        cmd = self._build(provider=ROUTE)
        assert " /opt/bin/claude-mixed --model" in cmd
        assert " claude --model" not in cmd

    def test_container_cmd_ensures_bridge_first(self, pm_home_dir):
        _write_providers(pm_home_dir, api_base="http://localhost:8790",
                         launcher="/opt/bin/claude-mixed")
        cmd = self._build(provider=ROUTE, container=True)
        ensure, _, rest = cmd.partition(" && ")
        # Isolated file run from the read-only pm source, not ``-m``: the
        # container's cwd (/workspace) may hold a different pm_core.
        assert ensure == ("python3 -I /opt/pm-src/pm_core/route_bridge.py "
                          "ensure /run/pm-route/router.sock 8790 claude-work")
        assert "ANTHROPIC_BASE_URL=http://127.0.0.1:8790 " in rest
        assert " claude --model" in rest  # host launcher is not used inside
        assert "claude-mixed" not in cmd

    def test_unconfigured_provider_raises(self, pm_home_dir):
        with pytest.raises(ProviderNotFoundError):
            self._build(provider="missing-route")

    def test_plain_model_unchanged(self, pm_home_dir):
        cmd = self._build(model="claude-opus-5-5", effort="high")
        assert cmd == "claude --model claude-opus-5-5 --effort high"

    def test_fake_claude_has_no_ensure_step(self, pm_home_dir):
        from pm_core.claude_launcher import build_claude_shell_cmd
        _write_providers(pm_home_dir)
        with patch("pm_core.paths.fake_claude_config_for_type",
                   return_value={"verdicts": {"PASS": 1}}), \
             patch("pm_core.claude_launcher.log_shell_command"):
            cmd = build_claude_shell_cmd(provider=ROUTE, container=True,
                                         session_type="qa_scenario")
        assert "fake-claude" in cmd
        assert "route_bridge" not in cmd


# ---------------------------------------------------------------------------
# Role isolation
# ---------------------------------------------------------------------------

class TestRoleIsolation:
    def test_only_refiner_and_worker_are_routed(self, pm_home_dir):
        for st in ("qa_concretize", "qa_scenario"):
            res = resolve_model_and_provider(st, project_data=PROJECT)
            assert (res.provider, res.effort) == (ROUTE, "high")
        for st in ("qa", "qa_planning", "qa_verification", "qa_finalize",
                   "qa_interactive", "impl", "review", "signoff"):
            res = resolve_model_and_provider(st, project_data=PROJECT)
            assert (res.model, res.provider, res.effort) == (
                "claude-opus-5-5", None, "high"), st

    def test_scenario_0_stays_on_main(self):
        from pm_core.qa_loop import _resolve_interactive_model
        res = _resolve_interactive_model({}, PROJECT)
        assert (res.model, res.provider, res.effort) == (
            "claude-opus-5-5", None, "high")

    def test_scenario_0_legacy_plain_qa_scenario_model(self):
        from pm_core.qa_loop import _resolve_interactive_model
        legacy = {"project": {"model_config": {
            "session_models": {"qa_scenario": "claude-sonnet-5-5"}}}}
        assert _resolve_interactive_model({}, legacy).model == "claude-sonnet-5-5"
        routed_only = {"project": {"model_config": {
            "session_models": {"qa_scenario": f"provider:{ROUTE}"}}}}
        res = _resolve_interactive_model({}, routed_only)
        assert (res.model, res.provider) == (None, None)

    def test_launch_scenario_0_command(self, pm_home_dir, tmp_path):
        from pm_core import qa_loop
        _write_providers(pm_home_dir)
        state = qa_loop.QALoopState(pr_id="pr-1", qa_workdir=str(tmp_path))
        clone = tmp_path / "clone"
        clone.mkdir()
        with patch("pm_core.qa_loop.create_scenario_workdir",
                   return_value=(clone, tmp_path / "scratch")), \
             patch("pm_core.qa_loop._setup_clone_override"), \
             patch("pm_core.prompt_gen.generate_qa_interactive_prompt",
                   return_value="hi"), \
             patch("pm_core.claude_launcher.prepare_workspace"), \
             patch("pm_core.paths.fake_claude_config_for_type", return_value=None), \
             patch("pm_core.tmux.new_window_get_pane", return_value="%1") as nw, \
             patch("pm_core.tmux.pane_window_id", return_value=None):
            qa_loop._launch_scenario_0(state, PROJECT, {"id": "pr-1"}, "sess",
                                       repo_root=tmp_path, workdir_path=str(tmp_path))
        cmd = nw.call_args[0][2]
        assert " claude" in cmd and "--model claude-opus-5-5" in cmd
        assert "ANTHROPIC_BASE_URL" not in cmd and "work/" not in cmd

    def test_refiner_and_worker_commands_routed(self, pm_home_dir, tmp_path):
        from pm_core import qa_loop
        _write_providers(pm_home_dir)
        sc = qa_loop.QAScenario(index=1, title="t", focus="f", steps="s")
        sc.worktree_path = str(tmp_path)
        state = qa_loop.QALoopState(pr_id="pr-1", qa_workdir=str(tmp_path))
        with patch("pm_core.paths.fake_claude_config_for_type", return_value=None), \
             patch("pm_core.claude_launcher.prepare_workspace"), \
             patch("pm_core.qa_loop._write_scenario_capture_file"), \
             patch("pm_core.prompt_gen.generate_qa_child_prompt", return_value="p"):
            ref = qa_loop._build_concretize_cmd(sc, {}, PROJECT, cwd=str(tmp_path))
            run, _ = qa_loop._build_scenario_run_cmd(
                sc, state, PROJECT, str(tmp_path / "t.jsonl"),
                qa_loop._resolve_qa_model({}, PROJECT, "qa_scenario"),
                session="sess", workdir_path=str(tmp_path))
            ver = resolve_model_and_provider("qa_verification", project_data=PROJECT)
        for cmd in (ref, run):
            assert f"--model {MODEL}" in cmd and "--effort high" in cmd
            assert "ANTHROPIC_BASE_URL=http://127.0.0.1:1" in cmd
        assert ver.provider is None

    def test_container_worker_cmd_uses_bridge(self, pm_home_dir, tmp_path):
        from pm_core import qa_loop
        _write_providers(pm_home_dir)
        sc = qa_loop.QAScenario(index=2, title="t", focus="f", steps="s")
        sc.worktree_path = str(tmp_path)
        sc.container_name = "pm-qa-x"
        state = qa_loop.QALoopState(pr_id="pr-1", qa_workdir=str(tmp_path))
        with patch("pm_core.paths.fake_claude_config_for_type", return_value=None), \
             patch("pm_core.qa_loop._write_scenario_capture_file"), \
             patch("pm_core.prompt_gen.generate_qa_child_prompt", return_value="p"), \
             patch("pm_core.container._get_runtime", return_value="podman"):
            run, _ = qa_loop._build_scenario_run_cmd(
                sc, state, PROJECT, str(tmp_path / "t.jsonl"),
                qa_loop._resolve_qa_model({}, PROJECT, "qa_scenario"),
                session=None, workdir_path=str(tmp_path))
        assert run.startswith("podman exec -it pm-qa-x bash -c ")
        assert "route_bridge.py ensure /run/pm-route/router.sock 1" in run


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

class TestCheckRoute:
    def test_unrouted_is_ok(self, pm_home_dir):
        assert worker_route.check_route(ModelResolution(model="x")).ok
        assert worker_route.check_route(ModelResolution()).ok

    def test_missing_provider(self, pm_home_dir):
        st = worker_route.check_route(ModelResolution(provider="ghost"))
        assert not st.ok and "not configured" in st.problem
        assert "pm model set qa_scenario" in st.remedy

    def test_router_down(self, pm_home_dir):
        s, port = _listener()
        s.close()
        _write_providers(pm_home_dir, api_base=f"http://127.0.0.1:{port}")
        st = worker_route.check_route(ModelResolution(provider=ROUTE))
        assert not st.ok and f"127.0.0.1:{port}" in st.problem
        assert "start the router" in st.remedy

    def test_expired_credentials(self, pm_home_dir, short_dir):
        s, port = _listener()
        creds = short_dir / "creds.json"
        _creds(creds, -3600)
        _write_providers(pm_home_dir, api_base=f"http://127.0.0.1:{port}",
                         credentials_file=str(creds))
        try:
            st = worker_route.check_route(ModelResolution(provider=ROUTE))
        finally:
            s.close()
        assert not st.ok and "sign-in expired" in st.problem
        assert "sign in" in st.remedy
        assert "SECRET" not in st.message()

    def test_valid_credentials_ok(self, pm_home_dir, short_dir):
        s, port = _listener()
        creds = short_dir / "creds.json"
        _creds(creds, 3600)
        _write_providers(pm_home_dir, api_base=f"http://127.0.0.1:{port}",
                         credentials_file=str(creds))
        try:
            st = worker_route.check_route(ModelResolution(provider=ROUTE))
        finally:
            s.close()
        assert st.ok and st.route == ROUTE

    def test_refresh_command_runs_once_then_cools_down(self, pm_home_dir, short_dir):
        s, port = _listener()
        creds = short_dir / "creds.json"
        _creds(creds, -10)
        marker = short_dir / "ran"
        # The refresh "succeeds" the first time: it rewrites the expiry.
        refresh = (f"echo x >> {marker}; {sys.executable} -c "
                   f"\"import json,time;json.dump({{'claudeAiOauth':"
                   f"{{'expiresAt':int(time.time()*1000)+3600000}}}},"
                   f"open('{creds}','w'))\"")
        _write_providers(pm_home_dir, api_base=f"http://127.0.0.1:{port}",
                         credentials_file=str(creds), refresh_command=refresh)
        try:
            assert worker_route.check_route(ModelResolution(provider=ROUTE)).ok
            _creds(creds, -10)
            st = worker_route.check_route(ModelResolution(provider=ROUTE))
        finally:
            s.close()
        assert not st.ok  # second expiry within the cooldown: not re-run
        assert marker.read_text().count("x") == 1

    def test_missing_launcher(self, pm_home_dir):
        s, port = _listener()
        _write_providers(pm_home_dir, api_base=f"http://127.0.0.1:{port}",
                         launcher="/nonexistent/claude-mixed")
        try:
            host = worker_route.check_route(ModelResolution(provider=ROUTE))
            cont = worker_route.check_route(ModelResolution(provider=ROUTE),
                                            container=True)
        finally:
            s.close()
            for p in pm_home_dir.glob("route-bridge/*/router.sock"):
                p.unlink()
        assert not host.ok and "launcher" in host.problem
        assert cont.ok  # containers never use the host launcher

    def test_container_without_mount(self, pm_home_dir):
        s, port = _listener()
        _write_providers(pm_home_dir, api_base=f"http://127.0.0.1:{port}")
        try:
            with patch("pm_core.worker_route.container_has_route_mount",
                       return_value=False):
                st = worker_route.check_route(ModelResolution(provider=ROUTE),
                                              container_name="pm-qa-old")
        finally:
            s.close()
            for p in pm_home_dir.glob("route-bridge/*/router.sock"):
                p.unlink()
        assert not st.ok and "without the route socket mount" in st.problem
        assert "restart QA" in st.remedy

    def test_describe_is_credential_free(self, pm_home_dir):
        _write_providers(pm_home_dir, credentials_file="/c/.credentials.json")
        res = ModelResolution(provider=ROUTE, effort="high")
        assert worker_route.describe(res) == (
            f"route={ROUTE} model={MODEL} effort=high via=host")
        assert worker_route.describe(res, container=True).endswith(
            "via=container-bridge")
        assert worker_route.describe(ModelResolution(
            model="claude-opus-5-5", effort="high")) == (
            "route=main model=claude-opus-5-5 effort=high via=claude")


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------

def _delayed_upstream(port_holder, pause):
    """Upstream that answers each connection with 'first', pauses, then
    'second' and closes (a model stream with a long thinking gap)."""
    srv, port = _listener()
    port_holder.append(port)

    def handle(conn):
        # Readiness probes (unix_connectable) open and close a connection
        # through the bridge without sending anything.
        if not conn.recv(100):
            conn.close()
            return
        conn.sendall(b"first;")
        time.sleep(pause)
        conn.sendall(b"second;")
        conn.close()

    def run():
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
    threading.Thread(target=run, daemon=True).start()


def _read_all(sock: socket.socket) -> bytes:
    out = b""
    while True:
        b = sock.recv(100)
        if not b:
            return out
        out += b


class TestBridge:
    def test_stream_survives_pause_longer_than_connect_timeout(
            self, short_dir, monkeypatch):
        """Regression: the connect timeout stayed on the upstream socket,
        so a stream pausing past it was cut off (EOF after 10 s)."""
        monkeypatch.setattr(route_bridge, "CONNECT_TIMEOUT", 0.3)
        ports: list[int] = []
        _delayed_upstream(ports, pause=1.0)
        sock = str(short_dir / "r.sock")
        threading.Thread(target=route_bridge.run_host_bridge,
                         args=(sock, "127.0.0.1", ports[0]),
                         daemon=True).start()
        for _ in range(50):
            if route_bridge.unix_connectable(sock):
                break
            time.sleep(0.05)
        c = socket.socket(socket.AF_UNIX)
        c.connect(sock)
        c.sendall(b"req")
        try:
            assert _read_all(c) == b"first;second;"
        finally:
            c.close()
            os.unlink(sock)

    def test_unix_side_has_no_stream_timeout(self, short_dir, monkeypatch):
        monkeypatch.setattr(route_bridge, "CONNECT_TIMEOUT", 0.3)
        sock_path = str(short_dir / "u.sock")
        srv = socket.socket(socket.AF_UNIX)
        srv.bind(sock_path)
        srv.listen(1)
        threading.Thread(target=lambda: srv.accept(), daemon=True).start()
        s = route_bridge._connect_unix(sock_path)
        assert s.gettimeout() is None
        s.close()
        srv.close()

    def test_host_bridge_and_container_forwarder_end_to_end(self, short_dir):
        """host bridge (subprocess) + ensure forwarder, both started from a
        cwd whose pm_core would shadow ours (regression: ``-m`` imported
        the cwd's pm_core and could not find route_bridge)."""
        shadow = short_dir / "shadow"
        (shadow / "pm_core").mkdir(parents=True)
        (shadow / "pm_core" / "__init__.py").write_text(
            "raise SystemExit('shadow pm_core imported')\n")
        ports: list[int] = []
        _delayed_upstream(ports, pause=0.2)
        sock_dir = short_dir / "mnt"
        sock_dir.mkdir()
        sock = sock_dir / "router.sock"
        env = dict(os.environ, PYTHONPATH=str(shadow))
        host = subprocess.Popen(
            worker_route.bridge_host_argv(sock, "127.0.0.1", ports[0]),
            cwd=shadow, env=env, stderr=subprocess.PIPE)
        try:
            for _ in range(50):
                if route_bridge.unix_connectable(str(sock)):
                    break
                time.sleep(0.1)
            assert route_bridge.unix_connectable(str(sock)), host.stderr.read1()
            fwd_s, fwd_port = _listener()
            fwd_s.close()
            script = Path(route_bridge.__file__).resolve()
            r = subprocess.run(
                [sys.executable, "-I", str(script), "ensure", str(sock),
                 str(fwd_port), ROUTE],
                cwd=shadow, env=env, capture_output=True, text=True, timeout=20)
            assert r.returncode == 0, r.stderr
            # Idempotent: a second ensure sees the forwarder listening.
            r2 = subprocess.run(
                [sys.executable, "-I", str(script), "ensure", str(sock),
                 str(fwd_port)], cwd=shadow, env=env, capture_output=True,
                text=True, timeout=20)
            assert r2.returncode == 0, r2.stderr
            c = socket.create_connection(("127.0.0.1", fwd_port), timeout=5)
            c.sendall(b"req")
            assert _read_all(c) == b"first;second;"
            c.close()
        finally:
            host.kill()
            host.wait()
            # Removing the mounted dir stops the container-side forwarder.
            shutil.rmtree(sock_dir, ignore_errors=True)

    def test_ensure_fails_without_socket(self, short_dir):
        script = Path(route_bridge.__file__).resolve()
        r = subprocess.run(
            [sys.executable, "-I", str(script), "ensure",
             str(short_dir / "missing.sock"), "1", ROUTE],
            capture_output=True, text=True, timeout=20)
        assert r.returncode == route_bridge.EXIT_ROUTE_UNAVAILABLE
        assert "not mounted" in r.stderr and "Remedy" in r.stderr

    def test_ensure_host_bridge_restarts_and_keeps_dir(self, pm_home_dir):
        s, port = _listener()
        cfg = ProviderConfig(name=ROUTE, type="router",
                             api_base=f"http://127.0.0.1:{port}", model=MODEL)
        try:
            sock = worker_route.ensure_host_bridge(cfg)
            assert route_bridge.unix_connectable(str(sock))
            assert oct(sock.parent.stat().st_mode & 0o777) == "0o700"
            assert oct(sock.stat().st_mode & 0o777) == "0o600"
            ino = sock.parent.stat().st_ino
            sock.unlink()  # bridge exits; next ensure starts a new one
            sock2 = worker_route.ensure_host_bridge(cfg)
            assert sock2 == sock and route_bridge.unix_connectable(str(sock))
            assert sock.parent.stat().st_ino == ino  # same dir for mounts
        finally:
            s.close()
            sock.unlink(missing_ok=True)

    @pytest.mark.parametrize("replace", [False, True])
    def test_host_bridge_exits_when_socket_removed_or_replaced(
            self, short_dir, replace):
        # A detached bridge must not outlive its socket: removal, or a
        # newer bridge binding the same path, ends it.
        sock = str(short_dir / "x.sock")
        t = threading.Thread(target=route_bridge.run_host_bridge,
                             args=(sock, "127.0.0.1", 1), daemon=True)
        t.start()
        for _ in range(50):
            if route_bridge.unix_connectable(sock):
                break
            time.sleep(0.05)
        assert route_bridge.unix_connectable(sock)
        os.unlink(sock)
        newer = None
        if replace:
            newer = socket.socket(socket.AF_UNIX)
            newer.bind(sock)
        try:
            t.join(timeout=5)
            assert not t.is_alive()
        finally:
            if newer is not None:
                newer.close()
                os.unlink(sock)

    def test_symlinked_bridge_dir_is_refused(self, pm_home_dir, short_dir,
                                             monkeypatch):
        # A pre-planted symlink (e.g. the shared /tmp fallback) must not
        # redirect the container bind mount to its target.
        target = short_dir / "victim"
        target.mkdir(mode=0o755)
        link = short_dir / "planted"
        link.symlink_to(target)
        monkeypatch.setattr(worker_route, "bridge_dir", lambda route: link)
        cfg = ProviderConfig(name=ROUTE, type="router",
                             api_base="http://127.0.0.1:1", model=MODEL)
        with pytest.raises(OSError, match="not a directory owned"):
            worker_route.ensure_host_bridge(cfg)
        with patch("pm_core.worker_route.get_provider", return_value=cfg):
            assert worker_route.container_mounts(
                ModelResolution(provider=ROUTE)) == {}
        assert oct(target.stat().st_mode & 0o777) == "0o755"
        assert not (target / route_bridge.SOCKET_NAME).exists()

    def test_long_route_name_socket_path_fits(self, pm_home_dir):
        p = worker_route.bridge_socket("r" * 200)
        assert len(str(p)) <= 100


# ---------------------------------------------------------------------------
# QA loop gating
# ---------------------------------------------------------------------------

def _status(ok):
    return worker_route.RouteStatus(
        ok, ROUTE, *(() if ok else ("router not reachable at 127.0.0.1:8790",
                                    "start the router")))


def _api_error_record(uid):
    """A transcript record as Claude Code writes it when a request still
    fails after its own retries and the turn ends on the error."""
    return {"type": "assistant", "uuid": uid, "isApiErrorMessage": True,
            "error": "server_error", "message": {"model": "<synthetic>",
            "content": [{"type": "text",
                         "text": "API Error: Connection dropped (ECONNRESET)"}]}}


class TestAwaitRoute:
    def test_waits_then_launches(self):
        from pm_core import qa_loop
        state = qa_loop.QALoopState(pr_id="pr-1")
        seen = []
        state._notify_cb = lambda: seen.append(state.latest_output)
        results = iter([_status(False), _status(False), _status(True)])
        with patch("pm_core.qa_loop._ROUTE_RECHECK_INTERVAL", 0), \
             patch("pm_core.qa_loop.time.sleep"):
            assert qa_loop._await_route(state, lambda: next(results), "S1 worker")
        assert "router not reachable" in seen[0] and "start the router" in seen[0]
        assert len(seen) == 2  # repeated failure is not re-announced
        assert "available — launching" in seen[-1]
        assert not state.scenario_verdicts

    def test_stop_while_waiting(self):
        from pm_core import qa_loop
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.stop_requested = True
        assert not qa_loop._await_route(state, lambda: _status(False), "S1")

    def test_fake_claude_skips_gate(self, pm_home_dir):
        from pm_core import qa_loop
        with patch("pm_core.paths.fake_claude_config_for_type",
                   return_value={"verdicts": {"PASS": 1}}):
            check = qa_loop._route_checker({}, PROJECT, "qa_scenario",
                                           session_tag="t")
            assert check().ok  # provider is not even configured


class TestPollLoopRouteGating:
    def _poll(self, state, tmp_path, statuses, **kw):
        from pm_core import qa_loop
        it = iter(statuses)
        last = [statuses[-1]]

        def checker(*a, **k):
            def check():
                try:
                    last[0] = next(it)
                except StopIteration:
                    pass
                return last[0]
            return check
        with patch("pm_core.qa_loop._route_checker", side_effect=checker), \
             patch("pm_core.qa_loop._ROUTE_RECHECK_INTERVAL", 0), \
             patch("pm_core.qa_loop._is_verification_enabled", return_value=False), \
             patch("pm_core.qa_loop._write_resume_file"):
            qa_loop._poll_tmux_verdicts(state, {}, {}, "sess", "/tmp/w",
                                        tmp_path / "status.json",
                                        lambda *a: None, **kw)

    def test_dead_worker_relaunch_waits_without_spending_retries(self, tmp_path):
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        sc.window_name, sc.session_id = "w1", "sid-1"
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        relaunches = []

        def relaunch(scenario, *a):
            relaunches.append(time.time())
            scenario.pane_id = "%9"
            return True
        panes = {"n": 0}

        def get_pane(session, win):
            panes["n"] += 1
            return None if panes["n"] <= 4 else "%9"
        ev = {"event_type": "idle_prompt", "timestamp": time.time() + 1e4}
        with patch("pm_core.qa_loop._get_scenario_pane", side_effect=get_pane), \
             patch("pm_core.qa_loop._relaunch_scenario_window",
                   side_effect=relaunch), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
             patch("pm_core.hook_events.read_event", return_value=ev), \
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   return_value="PASS"), \
             patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
                   return_value=""), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            # down for 3 checks: three dead-pane polls defer, then relaunch
            self._poll(state, tmp_path,
                       [_status(False)] * 3 + [_status(True)])
        assert len(relaunches) == 1
        assert state.scenario_verdicts[1] == "PASS"

    def test_stopped_run_does_not_gate_or_defer_dead_worker(self, tmp_path):
        """``z t`` stops the run, then kills its windows and removes its
        containers: the stopped loop must not run the route check (an exec
        into the dying container) or announce a relaunch deferral."""
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        sc.window_name, sc.session_id = "w1", "sid-1"
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        seen = []
        state._notify_cb = lambda: seen.append(state.latest_output)

        def stop_on_sleep(_):
            state.stop_requested = True
        with patch("pm_core.qa_loop._get_scenario_pane", return_value=None), \
             patch("pm_core.qa_loop._relaunch_scenario_window") as relaunch, \
             patch("pm_core.qa_loop.time.sleep", side_effect=stop_on_sleep):
            self._poll(state, tmp_path, [_status(False)])
        relaunch.assert_not_called()
        assert not [o for o in seen if "deferred" in (o or "")]
        assert 1 not in state.scenario_verdicts

    def test_stop_during_route_wait_leaves_scenario_unverdicted(self, tmp_path):
        """A scenario stopped in its initial route wait has no window; the
        launch-failed INPUT_REQUIRED marking must not give it a verdict."""
        from pm_core import qa_loop
        waited = qa_loop.QAScenario(index=1, title="w", focus="f")
        failed = qa_loop.QAScenario(index=2, title="x", focus="f")
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [waited, failed]
        state.stop_requested = True
        qa_loop._note_route_wait_stopped(state, waited)
        with patch("pm_core.qa_loop.time.sleep"):
            self._poll(state, tmp_path, [_status(False)])
        assert 1 not in state.scenario_verdicts
        assert state.scenario_verdict_reasons[1] == (
            "stopped while waiting for the work route")
        # a genuine launch failure is still marked
        assert state.scenario_verdicts[2] == "INPUT_REQUIRED"

    def test_queued_scenario_stays_queued_while_route_down(self, tmp_path):
        from pm_core import qa_loop
        queued = qa_loop.QAScenario(index=2, title="q", focus="f")
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [queued]
        ticks = {"n": 0}

        def sleep(_):
            ticks["n"] += 1
            if ticks["n"] > 3:
                state.stop_requested = True
        with patch("pm_core.qa_loop.time.sleep", side_effect=sleep), \
             patch("pm_core.qa_loop._launch_scenarios_in_tmux") as launch:
            self._poll(state, tmp_path, [_status(False)],
                       queued_scenarios=[queued], concurrency_cap=1)
        launch.assert_not_called()
        assert 2 not in state.scenario_verdicts
        assert "deferred" in state.latest_output
        assert "start the router" in state.latest_output

    def test_queued_scenario_launches_once_route_recovers(self, tmp_path):
        """No other scenario is running, so no verdict event refills the
        slot: the deferred queue is retried on every poll tick."""
        from pm_core import qa_loop
        queued = qa_loop.QAScenario(index=2, title="q", focus="f")
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [queued]
        launched = []

        def launch(st, *a, **k):
            sc = st.scenarios[0]
            launched.append(sc.index)
            state.stop_requested = True  # done once it is launched
            sc.window_name = "w2"
        ticks = {"n": 0}

        def sleep(_):
            ticks["n"] += 1
            if ticks["n"] > 50:  # fail rather than hang
                state.stop_requested = True
        with patch("pm_core.qa_loop.time.sleep", side_effect=sleep), \
             patch("pm_core.qa_loop._launch_scenarios_in_tmux",
                   side_effect=launch):
            self._poll(state, tmp_path,
                       [_status(False)] * 4 + [_status(True)],
                       queued_scenarios=[queued], concurrency_cap=1)
        assert launched == [2]
        assert 2 not in state.scenario_verdicts

    def test_route_failure_after_queue_check_requeues_without_blocking(
            self, tmp_path):
        """The route dies between the queue check and the launch gate: the
        launch must not wait inside the verdict-collection loop.  The
        scenario goes back to the queue unchanged while the running
        scenario's verdict is still collected, and launches once the route
        is back."""
        from pm_core import qa_loop
        running = qa_loop.QAScenario(index=1, title="r", focus="f")
        running.window_name, running.session_id = "w1", "sid-1"
        running.pane_id = "%5"
        queued = qa_loop.QAScenario(index=2, title="q", focus="f",
                                    instruction_path="instructions/q.md")
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [running, queued]
        route = {"up": True}

        def checker(*a, **k):
            return lambda: _status(route["up"])
        launches = []

        def launch(st, *a, _route_deferred=None, **k):
            sc = st.scenarios[0]
            launches.append(sc.instruction_path)
            sc.instruction_path = None  # preparation rewrites the scenario
            if len(launches) == 1:
                route["up"] = False  # router dies right after the check
                with patch("pm_core.qa_loop._await_route",
                           side_effect=AssertionError("blocking wait")):
                    assert not qa_loop._route_gate(
                        st, {}, {}, sc, "qa_concretize",
                        deferred=_route_deferred)
                return
            sc.window_name, sc.session_id, sc.pane_id = "w2", "sid-2", "%6"

        ticks = {"n": 0}

        def sleep(_):
            ticks["n"] += 1
            if ticks["n"] == 3:
                route["up"] = True
            if ticks["n"] > 50:  # fail rather than hang
                state.stop_requested = True
        ev = {"event_type": "idle_prompt", "timestamp": time.time() + 1e4}
        with patch("pm_core.qa_loop._route_checker", side_effect=checker), \
             patch("pm_core.qa_loop._ROUTE_RECHECK_INTERVAL", 0), \
             patch("pm_core.qa_loop._is_verification_enabled",
                   return_value=False), \
             patch("pm_core.qa_loop._write_resume_file"), \
             patch("pm_core.qa_loop._launch_scenarios_in_tmux",
                   side_effect=launch), \
             patch("pm_core.qa_loop.time.sleep", side_effect=sleep), \
             patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
             patch("pm_core.hook_events.read_event", return_value=ev), \
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   return_value="PASS"), \
             patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
                   return_value=""), \
             patch("pm_core.tmux.pane_exists", return_value=True):
            qa_loop._poll_tmux_verdicts(
                state, {}, {}, "sess", "/tmp/w", tmp_path / "status.json",
                lambda *a: None, queued_scenarios=[queued],
                concurrency_cap=2)
        # Second launch saw the restored scenario, not the mutated one.
        assert launches == ["instructions/q.md", "instructions/q.md"]
        assert state.scenario_verdicts == {1: "PASS", 2: "PASS"}

    def test_queued_launch_status_keeps_remaining_queue(self, tmp_path):
        """Dequeuing one scenario passes the rest of the queue to the
        launch's dashboard write, so they stay "queued" (not "pending")."""
        from pm_core import qa_loop
        q2 = qa_loop.QAScenario(index=2, title="b", focus="f")
        q3 = qa_loop.QAScenario(index=3, title="c", focus="f")
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [q2, q3]
        seen = []

        def launch(st, *a, _status_queued=None, **k):
            seen.append((st.scenarios[0].index, set(_status_queued)))
            state.stop_requested = True
            st.scenarios[0].window_name = "w"
        ticks = {"n": 0}

        def sleep(_):
            ticks["n"] += 1
            if ticks["n"] > 50:  # fail rather than hang
                state.stop_requested = True
        with patch("pm_core.qa_loop.time.sleep", side_effect=sleep), \
             patch("pm_core.qa_loop._launch_scenarios_in_tmux",
                   side_effect=launch):
            self._poll(state, tmp_path, [_status(True)],
                       queued_scenarios=[q2, q3], concurrency_cap=1)
        assert seen == [(2, {3})]

    def test_launch_status_write_marks_queued(self, tmp_path):
        """The prep-phase dashboard write of a launch batch lists the whole
        run, with queued scenarios as "queued"."""
        from pm_core import qa_loop
        scs = [qa_loop.QAScenario(index=i, title=f"t{i}", focus="f")
               for i in (1, 2, 3)]
        state = qa_loop.QALoopState(pr_id="pr-1", qa_workdir=str(tmp_path))
        state.scenarios = scs[:1]
        seen = {}

        def concretize(*a, **k):
            status = json.loads((tmp_path / "qa_status.json").read_text())
            seen.update({s["index"]: s["verdict"] for s in status["scenarios"]})
            return None, "stop here"
        with patch("pm_core.qa_loop._route_checker",
                   return_value=lambda: _status(True)), \
             patch("pm_core.qa_loop.create_scenario_workdir",
                   return_value=(tmp_path / "repo", tmp_path / "scratch")), \
             patch("pm_core.qa_loop._build_concretize_cmd",
                   return_value="refiner"), \
             patch("pm_core.tmux.new_window_get_pane", return_value="%9"), \
             patch("pm_core.qa_loop._concretize_scenario",
                   side_effect=concretize):
            qa_loop._launch_scenarios_in_tmux(
                state, {}, {"id": "pr-1"}, "sess", None, str(tmp_path),
                _status_scenarios=scs, _status_queued={2, 3})
        assert seen == {1: "", 2: "queued", 3: "queued"}

    def test_queued_launch_gate_does_not_create_windows(self, tmp_path):
        """_launch_scenarios_in_tmux with a deferral dict never opens the
        refiner window when the route is down."""
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=4, title="t", focus="f")
        state = qa_loop.QALoopState(pr_id="pr-1", qa_workdir=str(tmp_path))
        state.scenarios = [sc]
        deferred = {}
        with patch("pm_core.qa_loop._route_checker",
                   return_value=lambda: _status(False)), \
             patch("pm_core.qa_loop.create_scenario_workdir",
                   return_value=(tmp_path / "repo", tmp_path / "scratch")), \
             patch("pm_core.qa_loop._await_route",
                   side_effect=AssertionError("blocking wait")), \
             patch("pm_core.tmux.new_window_get_pane") as new_window:
            qa_loop._launch_scenarios_in_tmux(
                state, {}, {"id": "pr-1"}, "sess", None, str(tmp_path),
                _route_deferred=deferred)
        new_window.assert_not_called()
        assert list(deferred) == [4] and not deferred[4].ok
        assert not sc.window_name and 4 not in state.scenario_verdicts

    @pytest.mark.parametrize("failing", ["qa_concretize", "qa_scenario"])
    def test_deferred_container_launch_removes_its_container(
            self, tmp_path, failing):
        """A queued container launch deferred at either gate removes the
        container it created: the relaunch re-clones the workdir, and a
        container reused by name would keep its bind mount on the deleted
        clone."""
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=4, title="t", focus="f")
        state = qa_loop.QALoopState(pr_id="pr-1", qa_workdir=str(tmp_path))
        state.scenarios = [sc]
        deferred = {}

        def checker(pr, data, session_type, **k):
            return lambda: _status(session_type != failing)
        with patch("pm_core.qa_loop._route_checker", side_effect=checker), \
             patch("pm_core.qa_loop._route_mounts", return_value={}), \
             patch("pm_core.container.load_container_config"), \
             patch("pm_core.container.create_qa_container"), \
             patch("pm_core.container.remove_container") as remove, \
             patch("pm_core.qa_loop.create_scenario_workdir",
                   return_value=(tmp_path / "repo", tmp_path / "scratch")), \
             patch("pm_core.qa_loop._build_concretize_cmd",
                   return_value="refiner"), \
             patch("pm_core.tmux.new_window_get_pane", return_value="%9"), \
             patch("pm_core.tmux.kill_window"), \
             patch("pm_core.qa_loop._concretize_scenario",
                   return_value=(None, None)), \
             patch("pm_core.qa_loop._await_route",
                   side_effect=AssertionError("blocking wait")):
            qa_loop._launch_scenarios_in_containers(
                state, {}, {"id": "pr-1"}, "sess", None, str(tmp_path),
                _route_deferred=deferred)
        assert list(deferred) == [4]
        remove.assert_called_once_with(sc.container_name)

    def test_idle_without_verdict_on_down_route_then_resume(self, tmp_path):
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        sc.window_name, sc.session_id, sc.pane_id = "w1", "sid-1", "%5"
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        t0 = time.time() + 1e4
        events = iter([{"event_type": "idle_prompt", "timestamp": t0}] * 3
                      + [{"event_type": "idle_prompt", "timestamp": t0 + 5}] * 50)
        verdicts = iter([None, "PASS"])
        sent = []
        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
             patch("pm_core.qa_loop._get_verdict_reminder_timeout",
                   return_value=0), \
             patch("pm_core.hook_events.read_event",
                   side_effect=lambda sid: next(events)), \
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   side_effect=lambda *a: next(verdicts)), \
             patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
                   return_value=""), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda p, m: sent.append(m)):
            self._poll(state, tmp_path, [_status(False), _status(True)])
        # No verdict reminder while the route was down; one resume nudge,
        # followed by the Enters that submit it.
        assert sent == [qa_loop._RouteStallWatch.NUDGE, "", ""]
        assert state.scenario_verdicts[1] == "PASS"

    def test_api_error_turn_on_recovered_route_is_resumed_once(self, tmp_path):
        """The outage ends between Claude giving up (API error ends the
        turn) and its idle notification a minute later: the route already
        answers, and the worker is resumed anyway -- once per error."""
        from pm_core import qa_loop
        tr = tmp_path / "t.jsonl"
        tr.write_text(json.dumps({"type": "user", "message": {"content": "go"}})
                      + "\n" + json.dumps(_api_error_record("e1")) + "\n")
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        sc.window_name, sc.session_id, sc.pane_id = "w1", "sid-1", "%5"
        sc.transcript_path = str(tr)
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        t0 = time.time() + 1e4
        events = iter([{"event_type": "idle_prompt", "timestamp": t0}] * 3
                      + [{"event_type": "idle_prompt", "timestamp": t0 + 5}] * 3
                      + [{"event_type": "idle_prompt", "timestamp": t0 + 9}] * 50)
        verdicts = iter([None, None, "PASS"])
        sent = []
        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
             patch("pm_core.qa_loop._get_verdict_reminder_timeout",
                   return_value=None), \
             patch("pm_core.hook_events.read_event",
                   side_effect=lambda sid: next(events)), \
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   side_effect=lambda *a: next(verdicts)), \
             patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
                   return_value=""), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda p, m: sent.append(m)):
            self._poll(state, tmp_path, [_status(True)])
        # The second idle still ends on the same error record: no re-nudge.
        assert sent == [qa_loop._RouteStallWatch.NUDGE, "", ""]
        assert state.scenario_verdicts[1] == "PASS"

    def test_healthy_route_idle_without_api_error_is_not_resumed(self, tmp_path):
        from pm_core import qa_loop
        tr = tmp_path / "t.jsonl"
        tr.write_text(json.dumps({"type": "assistant", "message": {
            "content": [{"type": "text", "text": "still working"}]}}) + "\n")
        watch = qa_loop._RouteStallWatch(
            qa_loop.QALoopState(pr_id="pr-1"), lambda: _status(True), "w")
        with patch("pm_core.tmux.send_keys") as send:
            assert not watch.on_idle_without_verdict("%5", str(tr))
            assert not watch.on_idle_without_verdict("%5", None)
        send.assert_not_called()

    def test_api_error_resumes_are_capped(self, tmp_path):
        from pm_core import qa_loop
        tr = tmp_path / "t.jsonl"
        watch = qa_loop._RouteStallWatch(
            qa_loop.QALoopState(pr_id="pr-1"), lambda: _status(True), "w")
        results = []
        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.tmux.send_keys"):
            for i in range(qa_loop._RouteStallWatch.MAX_ERROR_RESUMES + 2):
                tr.write_text(json.dumps(_api_error_record(f"e{i}")) + "\n")
                results.append(watch.on_idle_without_verdict("%5", str(tr)))
        assert results.count(True) == qa_loop._RouteStallWatch.MAX_ERROR_RESUMES

    def test_api_error_on_unrouted_session_is_not_resumed(self, tmp_path):
        """A main-account (unrouted) worker's API error is not a route
        outage: it keeps the usual reminder handling, with no nudge."""
        from pm_core import qa_loop
        tr = tmp_path / "t.jsonl"
        tr.write_text(json.dumps(_api_error_record("e1")) + "\n")
        watch = qa_loop._RouteStallWatch(
            qa_loop.QALoopState(pr_id="pr-1"),
            lambda: worker_route.RouteStatus(True), "w")
        with patch("pm_core.tmux.send_keys") as send:
            assert not watch.on_idle_without_verdict("%5", str(tr))
        send.assert_not_called()

    def test_unrouted_api_error_idle_gets_submitted_reminder(self, tmp_path):
        """An unrouted worker idles on an API error: no route nudge, and
        the verdict reminder is followed by the Enters that submit it
        (a single text+Enter burst can sit unsent in Claude's prompt)."""
        from pm_core import qa_loop
        tr = tmp_path / "t.jsonl"
        tr.write_text(json.dumps(_api_error_record("e1")) + "\n")
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        sc.window_name, sc.session_id, sc.pane_id = "w1", "sid-1", "%5"
        sc.transcript_path = str(tr)
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        t0 = time.time() + 1e4
        events = iter([{"event_type": "idle_prompt", "timestamp": t0}] * 3
                      + [{"event_type": "idle_prompt", "timestamp": t0 + 5}] * 50)
        verdicts = iter([None, "PASS"])
        sent = []
        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
             patch("pm_core.qa_loop._get_verdict_reminder_timeout",
                   return_value=120), \
             patch("pm_core.hook_events.read_event",
                   side_effect=lambda sid: next(events)), \
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   side_effect=lambda *a: next(verdicts)), \
             patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
                   return_value=""), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda p, m: sent.append(m)):
            self._poll(state, tmp_path, [worker_route.RouteStatus(True)])
        assert len(sent) == 3 and sent[0].startswith("Reminder: your verdict")
        assert sent[1:] == ["", ""]
        assert state.scenario_verdicts[1] == "PASS"

    def test_relaunched_worker_gets_a_fresh_route_watch(self, tmp_path):
        """A worker stalled on the route dies and is relaunched once the
        route answers: the dead session's stalled pane is not "resumed"
        and the new session starts with its own API-error budget."""
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        sc.window_name, sc.session_id, sc.pane_id = "w1", "sid-1", "%5"
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        seen = []
        state._notify_cb = lambda: seen.append(state.latest_output)
        dead = set()
        t0 = time.time() + 1e4

        def relaunch(scenario, *a):
            scenario.pane_id, scenario.session_id = "%9", "sid-2"
            return True

        def verdict(*a):
            if sc.pane_id == "%5":
                dead.add("%5")
                return None
            return "PASS"
        with patch("pm_core.qa_loop._get_scenario_pane", return_value=None), \
             patch("pm_core.qa_loop._relaunch_scenario_window",
                   side_effect=relaunch), \
             patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
             patch("pm_core.qa_loop._get_verdict_reminder_timeout",
                   return_value=None), \
             patch("pm_core.hook_events.read_event", side_effect=lambda sid: {
                 "event_type": "idle_prompt",
                 "timestamp": t0 + (sid == "sid-2")}), \
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   side_effect=verdict), \
             patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
                   return_value=""), \
             patch("pm_core.tmux.pane_exists",
                   side_effect=lambda p: p not in dead), \
             patch("pm_core.tmux.send_keys") as send:
            self._poll(state, tmp_path, [_status(False), _status(True)])
        assert any("worker stalled" in (o or "") for o in seen)
        assert not [o for o in seen if "recovered — resumed" in (o or "")]
        send.assert_not_called()
        assert state.scenario_verdicts[1] == "PASS"

    def test_repeat_deferral_after_recovery_is_surfaced_again(self):
        """Same failure message as the previous deferral, but the route
        recovered in between: the TUI must show the new deferral."""
        from pm_core import qa_loop
        state = qa_loop.QALoopState(pr_id="pr-1")
        watch = qa_loop._RouteStallWatch(state, lambda: _status(True),
                                         "Queued scenario launch")
        with patch("pm_core.qa_loop._notify_state"):
            watch.remember(_status(False))
            watch.surface(_status(False), "deferred")
            first = state.latest_output
            watch.surface(_status(False), "deferred")  # still down: once
            state.latest_output = "Scenario 2 (b): PASS (verified)"
            watch.remember(_status(True))
            watch.surface(_status(False), "deferred")
        assert first.startswith("Queued scenario launch deferred — ")
        assert state.latest_output == first

    def test_resumed_container_worker_checks_its_container(self, tmp_path):
        """Restart adoption: the resumed state carries container_name, and
        the relaunch gate checks that container's route mount."""
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=3, title="t", focus="f")
        sc.window_name, sc.session_id, sc.container_name = "w3", "s3", "pm-qa-c3"
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        calls = []
        ticks = {"n": 0}

        def sleep(_):
            ticks["n"] += 1
            if ticks["n"] > 2:
                state.stop_requested = True

        def checker(*a, **k):
            calls.append(k)
            return lambda: _status(False)
        with patch("pm_core.qa_loop._route_checker", side_effect=checker), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value=None), \
             patch("pm_core.qa_loop._relaunch_scenario_window") as relaunch, \
             patch("pm_core.qa_loop.time.sleep", side_effect=sleep), \
             patch("pm_core.qa_loop._is_verification_enabled", return_value=False), \
             patch("pm_core.qa_loop._write_resume_file"):
            qa_loop._poll_tmux_verdicts(state, {}, {}, "sess", "/tmp/w",
                                        tmp_path / "status.json",
                                        lambda *a: None, use_containers=True)
        relaunch.assert_not_called()
        assert {"session_tag": None, "container": True,
                "container_name": "pm-qa-c3"} in calls
        assert 3 not in state.scenario_verdicts


# ---------------------------------------------------------------------------
# Live probe evidence (pm provider test --live)
# ---------------------------------------------------------------------------

# Stand-in for claude -p: writes its transcript where real Claude does (every
# non-alphanumeric cwd character -> '-', so '_' too) and, unless told not
# to, the pm hook event for its session.
_PROBE_CLAUDE = r"""#!/usr/bin/env python3
import json, os, re, sys
sid = sys.argv[sys.argv.index("--session-id") + 1]
model = sys.argv[sys.argv.index("--model") + 1]
home = os.environ["HOME"]
if os.environ.get("PROBE_TRANSCRIPT", "1") == "1":
    d = os.path.join(home, ".claude", "projects",
                     re.sub(r"[^a-zA-Z0-9]", "-", os.getcwd()))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, sid + ".jsonl"), "w") as f:
        f.write(json.dumps({"type": "assistant", "message": {
            "model": model.split("/")[-1], "content": "ok"}}) + "\n")
if os.environ.get("PROBE_HOOK", "1") == "1":
    hooks = os.environ["PROBE_HOOKS_DIR"]
    os.makedirs(hooks, exist_ok=True)
    with open(os.path.join(hooks, sid + ".json"), "w") as f:
        json.dump({"event_type": "Stop", "session_id": sid}, f)
print(json.dumps({"result": "ok", "is_error": False,
                  "modelUsage": {model: {}}}))
"""


class TestLiveProbe:
    @pytest.fixture
    def probe_env(self, short_dir, monkeypatch):
        bindir = short_dir / "bin"
        bindir.mkdir()
        exe = bindir / "claude"
        exe.write_text(_PROBE_CLAUDE)
        exe.chmod(0o755)
        home = short_dir / "home"
        home.mkdir()
        hooks = home / ".pm" / "hooks"
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
        monkeypatch.setenv("PROBE_HOOKS_DIR", str(hooks))
        monkeypatch.setattr("pm_core.hook_events._HOOKS_BASE", hooks)
        monkeypatch.setattr("pm_core.worker_route.time.sleep", lambda s: None)
        return short_dir

    def _probe(self, cwd):
        cfg = ProviderConfig(name=ROUTE, type="router",
                             api_base="http://127.0.0.1:1", model=MODEL)
        return worker_route.live_probe(cfg, cwd=str(cwd))

    def test_underscore_cwd_finds_transcript(self, probe_env):
        # Supervisor-found: tempfile.mkdtemp suffixes may contain '_'; Claude
        # writes -tmp-pm-route-probe-xxxx-/, which pm used to miss and then
        # still report Live OK with transcript (none).
        cwd = probe_env / "pm-route-probe-020ea4s_"
        cwd.mkdir()
        out = self._probe(cwd)
        assert out["ok"], out
        assert out["transcript"] and "probe-020ea4s-" in out["transcript"]
        assert out["transcript_models"] == ["claude-opus-5-5"]
        assert out["hook_event"] == "Stop"

    def test_missing_transcript_is_a_failure(self, probe_env, monkeypatch):
        monkeypatch.setenv("PROBE_TRANSCRIPT", "0")
        cwd = probe_env / "probe"
        cwd.mkdir()
        out = self._probe(cwd)
        assert not out["ok"]
        assert out["transcript"] is None
        assert "missing evidence" in out["error"]
        assert "no transcript" in out["error"]

    def test_missing_hook_event_is_a_failure(self, probe_env, monkeypatch):
        monkeypatch.setenv("PROBE_HOOK", "0")
        cwd = probe_env / "probe"
        cwd.mkdir()
        out = self._probe(cwd)
        assert not out["ok"]
        assert out["transcript"] is not None
        assert "no pm hook event" in out["error"]

    def test_cli_reports_missing_evidence(self, probe_env, pm_home_dir,
                                          monkeypatch):
        monkeypatch.setenv("PROBE_TRANSCRIPT", "0")
        s, port = _listener()
        try:
            _write_providers(pm_home_dir, api_base=f"http://127.0.0.1:{port}")
            from click.testing import CliRunner
            from pm_core.cli import cli
            r = CliRunner().invoke(cli, ["provider", "test", ROUTE, "--live"])
        finally:
            s.close()
        assert r.exit_code == 1, r.output
        assert "Live: FAILED" in r.output and "missing evidence" in r.output
        assert "Live: OK" not in r.output


def test_transcript_path_matches_claude_mangling():
    from pm_core.claude_launcher import transcript_path_for
    p = transcript_path_for("/tmp/pm-route-probe-020ea4s_/a.b c", "sid")
    assert p.parent.name == "-tmp-pm-route-probe-020ea4s--a-b-c"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestProviderCLI:
    def _run(self, *args):
        from click.testing import CliRunner
        from pm_core.cli import cli
        return CliRunner().invoke(cli, ["provider", *args])

    def test_add_router_and_list_without_secrets(self, pm_home_dir, short_dir):
        creds = short_dir / "creds.json"
        _creds(creds, 3600)
        r = self._run("add", ROUTE, "--type", "router",
                      "--api-base", "http://127.0.0.1:8790", "--model", MODEL,
                      "--credentials-file", str(creds))
        assert r.exit_code == 0, r.output
        r = self._run("list")
        assert f"{ROUTE}  type=router  api_base=http://127.0.0.1:8790" in r.output
        assert str(creds) in r.output and "expires" in r.output
        assert "SECRET" not in r.output

    def test_add_router_rejects_api_key_and_requires_model(self, pm_home_dir):
        r = self._run("add", ROUTE, "--type", "router", "--api-base",
                      "http://127.0.0.1:8790", "--model", MODEL,
                      "--api-key", "sk-x")
        assert r.exit_code == 1
        r = self._run("add", ROUTE, "--type", "router", "--api-base",
                      "http://127.0.0.1:8790")
        assert r.exit_code == 1 and "--model is required" in r.output

    def test_test_reports_remedy(self, pm_home_dir):
        s, port = _listener()
        s.close()
        _write_providers(pm_home_dir, api_base=f"http://127.0.0.1:{port}")
        r = self._run("test", ROUTE)
        assert r.exit_code == 1
        assert "Preflight: FAILED" in r.output and "Remedy:" in r.output

    def test_test_unknown_provider(self, pm_home_dir):
        r = self._run("test", "ghost")
        assert r.exit_code == 1 and "not configured" in r.output
