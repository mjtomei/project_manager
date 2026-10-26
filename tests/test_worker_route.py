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
    LAUNCH_ROUTING_ENV_VARS, ProviderConfig, ProviderNotFoundError,
    ROUTER_ALIAS_ENV_VARS, get_provider, launch_env,
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

    def test_fable_alias_is_pinned(self, pm_home_dir):
        # S61: a skill or slash command with `model: fable`, or /model ->
        # Fable, switched a routed session's main loop to claude-fable-5-1,
        # which the router sends to the main account.  Claude Code resolves
        # the fable alias through ANTHROPIC_DEFAULT_FABLE_MODEL.
        _write_providers(pm_home_dir)
        cmd = TestBuildShellCmd()._build(provider=ROUTE)
        assert _cmd_env(cmd)["ANTHROPIC_DEFAULT_FABLE_MODEL"] == MODEL

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

    def test_plain_model_stays_on_claude(self, pm_home_dir):
        cmd = self._build(model="claude-opus-5-5", effort="high")
        # No route, no key handling; only the subagent pin (TestSubagentPin)
        # and none of the routing variables it does not set
        # (TestInheritedRoutingEnv).
        assert cmd == ("env -u ANTHROPIC_DEFAULT_OPUS_MODEL "
                       "-u ANTHROPIC_DEFAULT_SONNET_MODEL "
                       "-u ANTHROPIC_DEFAULT_HAIKU_MODEL "
                       "-u ANTHROPIC_DEFAULT_FABLE_MODEL "
                       "-u ANTHROPIC_SMALL_FAST_MODEL "
                       "-u CLAUDE_CODE_AUTO_MODE_MODEL -u PM_ROUTE_BASE_URL "
                       "CLAUDE_CODE_SUBAGENT_MODEL=claude-opus-5-5 "
                       "CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 "
                       "claude --model claude-opus-5-5 --effort high")

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


def _cmd_env(cmd: str) -> dict[str, str]:
    """The ``NAME=value`` assignments a built command sets for claude."""
    import re
    import shlex
    return dict(w.split("=", 1) for w in shlex.split(cmd)
                if re.match(r"[A-Z_][A-Z0-9_]*=", w))


class TestClassifierRoute:
    """Auto permission mode's classifier stays on the session's account.

    QA S59/S61 (pr-1071c5a): the classifier refuses an Opus-class
    ANTHROPIC_DEFAULT_SONNET_MODEL (and an Opus-class
    CLAUDE_CODE_AUTO_MODE_MODEL) and falls back to its Sonnet 5 default,
    requested without ``work/``, which the router sends to the main
    account.  ``work/claude-sonnet-5`` kept it on the real work route.
    """

    CLASSIFIER = "work/claude-sonnet-5"
    _build = staticmethod(TestBuildShellCmd()._build)

    @staticmethod
    def _shell_env(cmd, var="CLAUDE_CODE_AUTO_MODE_MODEL"):
        """What *var* is in claude's environment when *cmd* runs."""
        import re
        exe = re.search(r" claude(?= |$)", cmd)  # the executable word
        probe = cmd[:exe.start()] + f" sh -c 'echo \"${{{var}-unset}}\"'"
        return subprocess.run(["sh", "-c", probe], capture_output=True,
                              text=True, check=True).stdout.strip()

    @pytest.mark.parametrize("model", [MODEL, f"{MODEL}[1m]"])
    def test_router_sends_the_classifier_default_through_its_route(self, model):
        p = ProviderConfig(name=ROUTE, type="router", api_base="http://x:1",
                           model=model)
        assert p.env_vars()["CLAUDE_CODE_AUTO_MODE_MODEL"] == self.CLASSIFIER

    @pytest.mark.parametrize("container", [False, True])
    def test_routed_launch_carries_it_over_an_inherited_value(
            self, pm_home_dir, monkeypatch, container):
        monkeypatch.setenv("CLAUDE_CODE_AUTO_MODE_MODEL", "claude-sonnet-5")
        _write_providers(pm_home_dir, model=f"{MODEL}[1m]")
        cmd = self._build(provider=ROUTE, container=container)
        assert _cmd_env(cmd)["CLAUDE_CODE_AUTO_MODE_MODEL"] == self.CLASSIFIER
        if not container:
            assert self._shell_env(cmd) == self.CLASSIFIER

    def test_live_probe_cmd_carries_it(self, pm_home_dir):
        _write_providers(pm_home_dir)
        cfg = get_provider(ROUTE, strict=True)
        cmd = worker_route._probe_shell_cmd(cfg, "sid", container=False)
        assert _cmd_env(cmd)["CLAUDE_CODE_AUTO_MODE_MODEL"] == self.CLASSIFIER

    def test_live_probe_cmd_unsets_what_launches_unset(self, pm_home_dir,
                                                       monkeypatch):
        # The probe checks the route the way sessions use it: no stray key,
        # and an unpinned route drops another route's classifier pin.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stray")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok-stray")
        monkeypatch.setenv("CLAUDE_CODE_AUTO_MODE_MODEL", self.CLASSIFIER)
        _write_providers(pm_home_dir, model="z-ai/glm-5.3-flash")
        cfg = get_provider(ROUTE, strict=True)
        cmd = worker_route._probe_shell_cmd(cfg, "sid", container=False)
        for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
                    "CLAUDE_CODE_AUTO_MODE_MODEL"):
            assert self._shell_env(cmd, var) == "unset", var

    def test_alias_models_entry_wins(self):
        p = ProviderConfig(name=ROUTE, type="router", api_base="http://x:1",
                           model=MODEL, alias_models={
                               "CLAUDE_CODE_AUTO_MODE_MODEL": "work/other"})
        assert p.env_vars()["CLAUDE_CODE_AUTO_MODE_MODEL"] == "work/other"

    # Route models the host router lists (GET /v1/models, review c189 i2:
    # /pm-captures/review-c189-i2/router-v1-models.txt).  It lists no
    # claude-sonnet-5 under the deepseek/, z-ai/ or chatgpt/ prefixes, which
    # the DeepSeek, GLM and Astra trial routes use.
    UNPINNED = ["claude-opus-5-5",  # unprefixed: the router's default backend
                "deepseek/deepseek-v4.1-flash-1017", "z-ai/glm-5.3-flash",
                "chatgpt/gpt-6-astra-high"]

    @pytest.mark.parametrize("model", UNPINNED)
    def test_route_without_claude_models_leaves_the_classifier_to_claude(
            self, model):
        p = ProviderConfig(name=ROUTE, type="router", api_base="http://x:1",
                           model=model)
        assert "CLAUDE_CODE_AUTO_MODE_MODEL" not in p.env_vars()
        assert "CLAUDE_CODE_AUTO_MODE_MODEL" in launch_env(p, p.env_vars(),
                                                           model, {})[1]

    @pytest.mark.parametrize("model", UNPINNED)
    def test_unpinned_route_drops_another_routes_inherited_value(
            self, pm_home_dir, monkeypatch, model):
        # pm run inside a work-routed session exports work/claude-sonnet-5;
        # it must not put this route's classifier on the work account.
        monkeypatch.setenv("CLAUDE_CODE_AUTO_MODE_MODEL", self.CLASSIFIER)
        _write_providers(pm_home_dir, model=model)
        cmd = self._build(provider=ROUTE)
        assert "CLAUDE_CODE_AUTO_MODE_MODEL=" not in cmd
        assert self._shell_env(cmd) == "unset"
        from pm_core.claude_launcher import _resolve_provider
        _, _, run_env = _resolve_provider(provider=ROUTE)
        assert "CLAUDE_CODE_AUTO_MODE_MODEL" not in run_env

    def test_pinned_route_does_not_also_unset_it(self):
        p = ProviderConfig(name=ROUTE, type="router", api_base="http://x:1",
                           model=MODEL)
        assert "CLAUDE_CODE_AUTO_MODE_MODEL" not in launch_env(
            p, p.env_vars(), MODEL, {})[1]

    @pytest.mark.parametrize("model", [None, "claude-opus-5-5"])
    def test_main_account_session_drops_an_inherited_value(
            self, pm_home_dir, monkeypatch, model):
        # A routed caller's pin would put a main session's classifier on
        # the work route (or on a model main cannot serve).
        monkeypatch.setenv("CLAUDE_CODE_AUTO_MODE_MODEL", self.CLASSIFIER)
        cmd = self._build(model=model)
        assert "CLAUDE_CODE_AUTO_MODE_MODEL=" not in cmd
        assert self._shell_env(cmd) == "unset"

    def test_claude_provider_with_its_own_endpoint_drops_it_too(
            self, pm_home_dir, monkeypatch):
        # Every claude-type session is a main-account one, whatever its URL.
        import yaml
        (pm_home_dir / "providers.yaml").write_text(yaml.safe_dump(
            {"providers": {"proxy": {"type": "claude",
                                     "api_base": "http://127.0.0.1:1",
                                     "model": "claude-opus-5-5"}}}))
        monkeypatch.setenv("CLAUDE_CODE_AUTO_MODE_MODEL", self.CLASSIFIER)
        cmd = self._build(provider="proxy")
        assert self._shell_env(cmd) == "unset"

    def test_print_launchers_drop_it_for_main_and_set_it_for_routes(
            self, pm_home_dir, monkeypatch):
        from pm_core.claude_launcher import _resolve_provider
        for var in ("PM_MODEL", "PM_PROVIDER", "CLAUDE_CODE_SUBAGENT_MODEL",
                    "CLAUDE_CODE_SUBAGENT_MODEL_FORCE"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("CLAUDE_CODE_AUTO_MODE_MODEL", self.CLASSIFIER)
        _, _, run_env = _resolve_provider(model="claude-opus-5-5")
        assert "CLAUDE_CODE_AUTO_MODE_MODEL" not in run_env
        _write_providers(pm_home_dir)
        monkeypatch.setenv("CLAUDE_CODE_AUTO_MODE_MODEL", "claude-sonnet-5")
        _, _, run_env = _resolve_provider(provider=ROUTE)
        assert run_env["CLAUDE_CODE_AUTO_MODE_MODEL"] == self.CLASSIFIER

    def test_local_provider_sets_only_its_own_alias_models(self):
        # The launch environment comes from pm's selection for every
        # provider type (user decision 2026-10-26): a local endpoint gets no
        # inherited classifier pin, and its own alias_models are what it
        # sets.
        p = ProviderConfig(name="ollama", type="local",
                           api_base="http://localhost:11434", model="qwen")
        assert "CLAUDE_CODE_AUTO_MODE_MODEL" in launch_env(
            p, p.env_vars(), "qwen", {})[1]
        p.alias_models = {"CLAUDE_CODE_AUTO_MODE_MODEL": "qwen-small",
                          "ANTHROPIC_SMALL_FAST_MODEL": "qwen-small"}
        assign, unset = launch_env(p, p.env_vars(), "qwen", {})
        assert assign["CLAUDE_CODE_AUTO_MODE_MODEL"] == "qwen-small"
        assert assign["ANTHROPIC_SMALL_FAST_MODEL"] == "qwen-small"
        assert not {"CLAUDE_CODE_AUTO_MODE_MODEL",
                    "ANTHROPIC_SMALL_FAST_MODEL"} & set(unset)

    def test_openai_provider_sets_its_own_alias_models(self):
        # Review c189 i7: alias_models is honoured for the openai type too.
        p = ProviderConfig(name="vllm", type="openai",
                           api_base="http://localhost:8000/v1", model="coder",
                           alias_models={"ANTHROPIC_SMALL_FAST_MODEL": "small"})
        assign, unset = launch_env(p, p.env_vars(), p.model_flag(), {})
        assert assign["ANTHROPIC_SMALL_FAST_MODEL"] == "small"
        assert "ANTHROPIC_SMALL_FAST_MODEL" not in unset
        assert "ANTHROPIC_DEFAULT_OPUS_MODEL" in unset

    def test_provider_list_names_the_classifier_route(self, pm_home_dir):
        from pm_core.cli.provider import _router_detail_lines
        _write_providers(pm_home_dir)
        lines = _router_detail_lines(get_provider(ROUTE, strict=True))
        assert f"auto-mode classifier: {self.CLASSIFIER}" in lines
        _write_providers(pm_home_dir, model="deepseek/deepseek-v4.1-flash-1017")
        lines = _router_detail_lines(get_provider(ROUTE, strict=True))
        assert any(line.startswith("auto-mode classifier: not pinned")
                   for line in lines)
        # It names what launches set, so an alias_models entry wins here too.
        _write_providers(pm_home_dir, alias_models={
            "CLAUDE_CODE_AUTO_MODE_MODEL": "work/other"})
        lines = _router_detail_lines(get_provider(ROUTE, strict=True))
        assert "auto-mode classifier: work/other" in lines


class TestInheritedRoutingEnv:
    """pm builds each launch's routing environment from its own selection.

    Review c189 i6: a pm process started inside a work-routed session
    inherits everything that session's launch set (model aliases, subagent
    and classifier pins, the route's ANTHROPIC_BASE_URL).  A no-model
    session then ran its whole main loop as ``work/claude-opus-5-5`` (the
    CLI default resolves through ANTHROPIC_DEFAULT_OPUS_MODEL), and a main
    session's fable/haiku/background calls followed the route.  User
    decision 2026-10-26: set what the selection needs, unset every other
    pm-controlled routing variable, keep everything else.
    """

    _build = TestBuildShellCmd._build
    WORK_URL = "http://127.0.0.1:8790"

    @pytest.fixture
    def routed_parent(self, pm_home_dir, monkeypatch):
        """The environment a work-routed session's launch exported."""
        _write_providers(pm_home_dir, api_base=self.WORK_URL,
                         model=f"{MODEL}[1m]")
        cfg = get_provider(ROUTE, strict=True)
        assign, _ = launch_env(cfg, cfg.env_vars(), cfg.model, {})
        for k, v in assign.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("UNRELATED_SETTING", "kept")
        return assign

    @staticmethod
    def _claude_env(cmd: str) -> dict[str, str]:
        """claude's environment when *cmd* runs in a real shell."""
        import re
        exe = re.search(r" (claude|\S*fake-claude)(?= |$)", cmd)
        probe = cmd[:exe.start()] + " env -0"
        out = subprocess.run(["sh", "-c", probe], capture_output=True,
                             check=True).stdout.decode()
        return dict(e.split("=", 1) for e in out.split("\0") if "=" in e)

    def _assert_no_route(self, env):
        leaked = {v: env[v] for v in (*LAUNCH_ROUTING_ENV_VARS,
                                      "ANTHROPIC_BASE_URL")
                  if v in env and not v.startswith("CLAUDE_CODE_SUBAGENT")}
        assert leaked == {}
        assert env["UNRELATED_SETTING"] == "kept"

    def test_routed_launch_records_its_url(self, routed_parent):
        assert routed_parent["PM_ROUTE_BASE_URL"] == self.WORK_URL
        assert routed_parent["ANTHROPIC_DEFAULT_OPUS_MODEL"] == f"{MODEL}[1m]"

    @pytest.mark.parametrize("resume", [False, True])
    def test_no_model_session_runs_on_the_cli_default(self, routed_parent,
                                                      resume):
        cmd = self._build(session_id="abc", resume=resume)
        env = self._claude_env(cmd)
        self._assert_no_route(env)
        assert "CLAUDE_CODE_SUBAGENT_MODEL" not in env
        assert "CLAUDE_CODE_SUBAGENT_MODEL_FORCE" not in env

    def test_plain_model_session_is_main_only(self, routed_parent):
        env = self._claude_env(self._build(model="claude-opus-5-5"))
        self._assert_no_route(env)
        assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == "claude-opus-5-5"

    def test_routed_launch_sets_its_own_values(self, routed_parent,
                                               pm_home_dir):
        # Another route over the work parent: its URL, its pins, no
        # work/ value left behind (its classifier is left to Claude).
        _write_providers(pm_home_dir, api_base="http://127.0.0.1:8791",
                         model="deepseek/deepseek-v4.1-flash-1017")
        env = self._claude_env(self._build(provider=ROUTE))
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8791"
        assert env["PM_ROUTE_BASE_URL"] == "http://127.0.0.1:8791"
        assert {env[v] for v in ROUTER_ALIAS_ENV_VARS} == {
            "deepseek/deepseek-v4.1-flash-1017"}
        assert "CLAUDE_CODE_AUTO_MODE_MODEL" not in env
        assert not any(v.startswith("work/") for v in env.values())

    def test_container_launches(self, routed_parent, pm_home_dir):
        # The route's in-container URL is the parent's too; a main session's
        # container gets the host's ANTHROPIC_BASE_URL and SMALL_FAST by
        # name (container._CLAUDE_ENV_VARS), so its command drops them.
        cmd = self._build(model="claude-opus-5-5", container=True)
        assert "-u ANTHROPIC_BASE_URL " in cmd
        assert "-u ANTHROPIC_SMALL_FAST_MODEL " in cmd
        cmd = self._build(provider=ROUTE, container=True)
        assert _cmd_env(cmd)["PM_ROUTE_BASE_URL"] == "http://127.0.0.1:8790"

    def test_users_own_endpoint_stays(self, pm_home_dir, monkeypatch):
        # Not a route's URL (no marker, no router configured there): the
        # user's own setting, e.g. a proxy or a QA main stub.
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:19611")
        env = self._claude_env(self._build(model="claude-opus-5-5"))
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:19611"

    @pytest.mark.parametrize("url", [WORK_URL, WORK_URL + "/",
                                     "http://localhost:8790"])
    def test_configured_route_url_is_recognised_without_the_marker(
            self, pm_home_dir, monkeypatch, url):
        # A parent from before the marker, or the host claude-mixed
        # launcher: its URL is a router configured here (host form, or the
        # in-container forwarder at the same port).
        _write_providers(pm_home_dir, api_base="http://localhost:8790/")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
        env = self._claude_env(self._build(model="claude-opus-5-5"))
        assert "ANTHROPIC_BASE_URL" not in env

    def test_provider_with_its_own_endpoint_keeps_it(self, routed_parent,
                                                     pm_home_dir):
        import yaml
        (pm_home_dir / "providers.yaml").write_text(yaml.safe_dump(
            {"providers": {"proxy": {"type": "claude",
                                     "api_base": "http://127.0.0.1:2",
                                     "model": "claude-opus-5-5"}}}))
        env = self._claude_env(self._build(provider="proxy"))
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:2"
        assert "ANTHROPIC_DEFAULT_FABLE_MODEL" not in env
        # Not a route: no marker, so a pm run inside this session keeps
        # the proxy as the user's own endpoint (review c189 i7).
        assert "PM_ROUTE_BASE_URL" not in env

    def test_non_router_provider_url_is_not_a_route(self, pm_home_dir,
                                                    monkeypatch):
        # Review c189 i7: only routers' addresses are recognised without
        # the marker; a claude/local provider configured at the inherited
        # URL is the user's own endpoint.
        import yaml
        (pm_home_dir / "providers.yaml").write_text(yaml.safe_dump(
            {"providers": {"proxy": {"type": "claude",
                                     "api_base": "http://127.0.0.1:2"},
                           "ollama": {"type": "local",
                                      "api_base": "http://127.0.0.1:3"}}}))
        for url in ("http://127.0.0.1:2", "http://127.0.0.1:3"):
            monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
            env = self._claude_env(self._build(model="claude-opus-5-5"))
            assert env["ANTHROPIC_BASE_URL"] == url

    def test_marker_alone_identifies_the_route(self, pm_home_dir,
                                               monkeypatch):
        # Review c189 i7: where no router is configured (a pm process in a
        # container has no providers.yaml) the marker is the only signal,
        # and the URL pm recorded may end in "/".
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8790/")
        monkeypatch.setenv("PM_ROUTE_BASE_URL", "http://127.0.0.1:8790/")
        env = self._claude_env(self._build(model="claude-opus-5-5"))
        assert "ANTHROPIC_BASE_URL" not in env
        assert "PM_ROUTE_BASE_URL" not in env

    def test_malformed_router_address_does_not_break_launches(
            self, pm_home_dir, monkeypatch):
        # Review c189 i7: a router whose api_base has no host has no
        # in-container form; launches with an inherited endpoint still
        # build (and keep a URL that is not that router's).
        _write_providers(pm_home_dir, api_base="not a url")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:19611")
        env = self._claude_env(self._build(model="claude-opus-5-5"))
        assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:19611"

    @pytest.mark.parametrize("providers", [
        {"broken": None},
        {"r": "router"},
        {"r": {"type": "router", "api_base": 8790, "model": MODEL}},
        {"r": {"type": "router", "api_base": "http://127.0.0.1:8790",
               "alias_models": ["x"]}},
        ["a", "b"],
    ], ids=["null_entry", "string_entry", "int_api_base", "list_aliases",
            "list_block"])
    def test_malformed_provider_entries_do_not_break_launches(
            self, pm_home_dir, monkeypatch, providers):
        # Review c189 i8: recognising an inherited route URL read every
        # entry through list_providers, so one hand-edited entry that is
        # not a provider made every launch without its own
        # ANTHROPIC_BASE_URL raise (AttributeError), while the user's own
        # endpoint was inherited; such launches built before R9.
        import yaml
        (pm_home_dir / "providers.yaml").write_text(
            yaml.safe_dump({"providers": providers}))
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:19611")
        for kw in ({}, {"model": "claude-opus-5-5"}):
            env = self._claude_env(self._build(**kw))
            assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:19611"
        from pm_core.claude_launcher import _resolve_provider
        run_env = _resolve_provider()[2]  # None: os.environ unchanged
        assert (run_env or os.environ)["ANTHROPIC_BASE_URL"] == (
            "http://127.0.0.1:19611")

    def test_router_beside_a_malformed_entry_is_still_recognised(
            self, pm_home_dir, monkeypatch):
        import yaml
        (pm_home_dir / "providers.yaml").write_text(yaml.safe_dump(
            {"providers": {"broken": None,
                           ROUTE: {"type": "router", "model": MODEL,
                                   "api_base": "http://127.0.0.1:8790"}}}))
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8790")
        env = self._claude_env(self._build(model="claude-opus-5-5"))
        assert "ANTHROPIC_BASE_URL" not in env

    def test_launch_env_reads_the_given_environment(self, pm_home_dir):
        # The caller's environment is a parameter: os.environ is clean
        # here (conftest), the passed one is a routed parent's.
        cfg = ProviderConfig(name="claude")
        parent = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9",
                  "PM_ROUTE_BASE_URL": "http://127.0.0.1:9"}
        assert "ANTHROPIC_BASE_URL" in launch_env(cfg, {}, None, parent)[1]
        assert "ANTHROPIC_BASE_URL" not in launch_env(
            cfg, {}, None, {"ANTHROPIC_BASE_URL": "http://127.0.0.1:9"})[1]

    def test_print_launchers(self, routed_parent):
        from pm_core.claude_launcher import _resolve_provider
        _, _, run_env = _resolve_provider()
        self._assert_no_route(run_env)
        _, _, run_env = _resolve_provider(model="claude-opus-5-5")
        self._assert_no_route(run_env)
        _, _, run_env = _resolve_provider(provider=ROUTE)
        assert run_env["ANTHROPIC_DEFAULT_FABLE_MODEL"] == f"{MODEL}[1m]"

    def test_fake_claude_gets_the_same_env(self, routed_parent):
        from pm_core.claude_launcher import build_claude_shell_cmd
        with patch("pm_core.paths.fake_claude_config_for_type",
                   return_value={"verdicts": {"PASS": 1}}), \
             patch("pm_core.claude_launcher.log_shell_command"):
            cmd = build_claude_shell_cmd(session_type="qa_scenario")
        assert "fake-claude" in cmd
        self._assert_no_route(self._claude_env(cmd))

    def test_bridge_turn_drops_the_parents_routing(self, routed_parent,
                                                   monkeypatch, tmp_path):
        import asyncio
        from pm_core import bridge
        seen = {}

        async def fake_exec(*cmd, env=None, **kw):
            seen.update(env)
            raise RuntimeError("stop")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr("shutil.which", lambda name: "/bin/claude")
        b = bridge.Bridge.__new__(bridge.Bridge)
        b.session_id, b.cwd = None, str(tmp_path)
        with pytest.raises(RuntimeError):
            asyncio.run(b._invoke_claude("hi"))
        self._assert_no_route(seen)


class TestSubagentPin:
    """Every subagent runs on the session's effective model.

    CLAUDE_CODE_SUBAGENT_MODEL alone is a default that an Agent call's
    ``model``, an agent definition's frontmatter and the built-in
    Explore/Plan agents all bypass; on a router, a bypassing child asking
    for an unprefixed model lands on the router's default (main) account.
    """

    _build = TestBuildShellCmd._build

    @staticmethod
    def _pin(cmd):
        env = _cmd_env(cmd)
        return (env.get("CLAUDE_CODE_SUBAGENT_MODEL"),
                env.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE"))

    def test_router_env_forces_its_model(self):
        p = ProviderConfig(name=ROUTE, type="router", api_base="http://x:1",
                           model=MODEL)
        env = p.env_vars()
        assert env["CLAUDE_CODE_SUBAGENT_MODEL"] == MODEL
        assert env["CLAUDE_CODE_SUBAGENT_MODEL_FORCE"] == "1"

    def test_host_route(self, pm_home_dir):
        _write_providers(pm_home_dir)
        assert self._pin(self._build(provider=ROUTE)) == (MODEL, "1")

    def test_container_route(self, pm_home_dir):
        _write_providers(pm_home_dir)
        cmd = self._build(provider=ROUTE, container=True)
        assert cmd.split(" && ")[0].startswith("python3 -I ")
        assert self._pin(cmd) == (MODEL, "1")

    def test_resume_keeps_pin(self, pm_home_dir):
        _write_providers(pm_home_dir)
        cmd = self._build(provider=ROUTE, session_id="abc", resume=True)
        assert "--resume abc" in cmd
        assert self._pin(cmd) == (MODEL, "1")

    def test_effective_model_kept_verbatim(self, pm_home_dir):
        # An explicit model beats the provider's; the pin follows it with
        # its route prefix and context suffix intact.
        _write_providers(pm_home_dir)
        cmd = self._build(provider=ROUTE, model=f"{MODEL}[1m]")
        assert f"--model '{MODEL}[1m]'" in cmd
        assert self._pin(cmd) == (f"{MODEL}[1m]", "1")

    def test_plain_model(self, pm_home_dir):
        cmd = self._build(model="claude-opus-5-5[1m]")
        assert self._pin(cmd) == ("claude-opus-5-5[1m]", "1")
        assert "ANTHROPIC_BASE_URL" not in cmd

    def test_no_model_selected_sets_nothing(self, pm_home_dir):
        # The CLI default model: pm has no selection to enforce, and only
        # removes a pin the caller's environment may carry.
        assert self._build() == ("env -u ANTHROPIC_DEFAULT_OPUS_MODEL "
                                 "-u ANTHROPIC_DEFAULT_SONNET_MODEL "
                                 "-u ANTHROPIC_DEFAULT_HAIKU_MODEL "
                                 "-u ANTHROPIC_DEFAULT_FABLE_MODEL "
                                 "-u ANTHROPIC_SMALL_FAST_MODEL -u CLAUDE_CODE_SUBAGENT_MODEL "
                                 "-u CLAUDE_CODE_SUBAGENT_MODEL_FORCE "
                                 "-u CLAUDE_CODE_AUTO_MODE_MODEL -u PM_ROUTE_BASE_URL claude")

    def test_no_model_drops_an_inherited_pin(self, pm_home_dir, monkeypatch):
        # S61: pm running inside a routed session (its own pin exported)
        # launched a no-model PR on the main endpoint; the inherited
        # work/ pin sent every child to a model main cannot serve (404).
        import subprocess
        monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", f"{MODEL}[1m]")
        monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "1")
        cmd = self._build()
        assert self._pin(cmd) == (None, None)
        assert "--model" not in cmd
        probe = cmd.rsplit(" claude", 1)[0] + (
            " sh -c 'echo \"${CLAUDE_CODE_SUBAGENT_MODEL-unset}"
            " ${CLAUDE_CODE_SUBAGENT_MODEL_FORCE-unset}\"'")
        out = subprocess.run(["sh", "-c", probe], capture_output=True,
                             text=True, check=True).stdout
        assert out.split() == ["unset", "unset"]

    def test_selected_model_is_not_unset(self, pm_home_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", f"{MODEL}[1m]")
        cmd = self._build(model="claude-opus-5-5")
        assert "-u CLAUDE_CODE_SUBAGENT_MODEL" not in cmd
        assert self._pin(cmd) == ("claude-opus-5-5", "1")

    def test_alias_override_is_forced(self, pm_home_dir):
        _write_providers(pm_home_dir, alias_models={
            "CLAUDE_CODE_SUBAGENT_MODEL": "work/claude-sonnet-5-5"})
        cmd = self._build(provider=ROUTE)
        assert self._pin(cmd) == ("work/claude-sonnet-5-5", "1")

    def test_pin_beats_inherited_values(self, pm_home_dir, monkeypatch):
        # A pane inheriting another session's pin (or a bare default)
        # still gets this session's model: assignments are command-scoped.
        monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "claude-fable-5-1")
        monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", raising=False)
        _write_providers(pm_home_dir)
        cmd = self._build(provider=ROUTE)
        assert self._pin(cmd) == (MODEL, "1")

    def test_fake_claude_gets_the_same_env(self, pm_home_dir):
        from pm_core.claude_launcher import build_claude_shell_cmd
        _write_providers(pm_home_dir)
        with patch("pm_core.paths.fake_claude_config_for_type",
                   return_value={"verdicts": {"PASS": 1}}), \
             patch("pm_core.claude_launcher.log_shell_command"):
            cmd = build_claude_shell_cmd(provider=ROUTE,
                                         session_type="qa_scenario")
        assert "fake-claude" in cmd
        assert self._pin(cmd) == (MODEL, "1")

    @pytest.mark.parametrize("session_type", [
        "impl", "review", "qa", "qa_planning", "qa_scenario", "qa_concretize",
        "qa_verification", "qa_finalize", "qa_interactive", "signoff",
        "watcher", "merge"])
    def test_every_role_on_a_routed_pr(self, pm_home_dir, session_type):
        # pr-592e4bd itself: prs[].model = provider:claude-work for all roles.
        _write_providers(pm_home_dir)
        res = resolve_model_and_provider(session_type, pr_model=f"provider:{ROUTE}",
                                         project_data=PROJECT)
        cmd = self._build(model=res.model, provider=res.provider,
                          effort=res.effort, session_type=session_type)
        assert f"--model {MODEL}" in cmd
        assert self._pin(cmd) == (MODEL, "1")

    def test_print_launchers_pin_run_env(self, pm_home_dir, monkeypatch):
        from pm_core import claude_launcher
        monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", "claude-fable-5-1")
        _write_providers(pm_home_dir)
        runs = []

        class _R:
            returncode, stdout = 0, ""

        def _run(cmd, **kw):
            runs.append((cmd, kw.get("env")))
            return _R()

        with patch("pm_core.claude_launcher.find_claude", return_value="claude"), \
             patch("pm_core.claude_launcher._fake_claude_config_for_type",
                   return_value=None), \
             patch("pm_core.claude_launcher._skip_permissions", return_value=False), \
             patch("pm_core.claude_launcher.log_shell_command"), \
             patch("pm_core.claude_launcher.prepare_workspace"), \
             patch("pm_core.claude_launcher.save_session"), \
             patch("pm_core.claude_launcher.load_session", return_value=None), \
             patch("subprocess.run", side_effect=_run):
            claude_launcher.launch_claude_print("p", provider=ROUTE,
                                                model=f"{MODEL}[1m]")
            claude_launcher.launch_claude_print("p", model="claude-opus-5-5")
            claude_launcher.launch_claude("p", "k", Path("/tmp"), provider=ROUTE)
        (c1, e1), (c2, e2), (c3, e3) = runs
        assert c1[c1.index("--model") + 1] == f"{MODEL}[1m]"
        assert (e1["CLAUDE_CODE_SUBAGENT_MODEL"],
                e1["CLAUDE_CODE_SUBAGENT_MODEL_FORCE"]) == (f"{MODEL}[1m]", "1")
        assert "ANTHROPIC_API_KEY" not in e1
        assert (e2["CLAUDE_CODE_SUBAGENT_MODEL"],
                e2["CLAUDE_CODE_SUBAGENT_MODEL_FORCE"]) == ("claude-opus-5-5", "1")
        assert (e3["CLAUDE_CODE_SUBAGENT_MODEL"],
                e3["CLAUDE_CODE_SUBAGENT_MODEL_FORCE"]) == (MODEL, "1")

    def test_print_launcher_without_model_drops_an_inherited_pin(
            self, pm_home_dir, monkeypatch):
        from pm_core.claude_launcher import _resolve_provider
        monkeypatch.delenv("PM_MODEL", raising=False)
        monkeypatch.delenv("PM_PROVIDER", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", raising=False)
        # A routed caller's classifier pin, which main sessions also drop
        # (TestClassifierRoute); set when the suite runs in a routed session.
        monkeypatch.delenv("CLAUDE_CODE_AUTO_MODE_MODEL", raising=False)
        # Nothing to drop (conftest clears the routing variables): the
        # process environment is used as is.
        assert _resolve_provider()[2] is None
        monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL", f"{MODEL}[1m]")
        monkeypatch.setenv("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "1")
        monkeypatch.setenv("S61_KEEP", "kept")
        _, model_flag, run_env = _resolve_provider()
        assert model_flag is None
        assert "CLAUDE_CODE_SUBAGENT_MODEL" not in run_env
        assert "CLAUDE_CODE_SUBAGENT_MODEL_FORCE" not in run_env
        assert run_env["S61_KEEP"] == "kept"

    def test_live_probe_cmd_is_pinned(self, pm_home_dir):
        _write_providers(pm_home_dir)
        cfg = get_provider(ROUTE, strict=True)
        cmd = worker_route._probe_shell_cmd(cfg, "sid", container=False)
        assert self._pin(cmd) == (MODEL, "1")


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
        assert ("CLAUDE_CODE_SUBAGENT_MODEL=claude-opus-5-5 "
                "CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 ") in cmd

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
            assert (f"CLAUDE_CODE_SUBAGENT_MODEL={MODEL} " in cmd
                    and "CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1 " in cmd)
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
             patch("pm_core.tmux.pane_exists", return_value=True), \
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

    @pytest.mark.parametrize("mode", ["container", "tmux"])
    def test_worker_split_after_window_closed_is_not_a_launch(
            self, tmp_path, caplog, mode):
        """PR cleanup (TUI Y) closes the refiner's window under a running
        loop: the worker split then fails.  That is logged without a
        traceback and never as "Launched scenario"."""
        import logging
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=11, title="t", focus="f")
        state = qa_loop.QALoopState(pr_id="pr-1", qa_workdir=str(tmp_path))
        state.scenarios = [sc]
        gone = subprocess.CalledProcessError(1, ["tmux", "split-window"])
        with patch("pm_core.qa_loop._route_checker",
                   return_value=lambda: _status(True)), \
             patch("pm_core.qa_loop._route_mounts", return_value={}), \
             patch("pm_core.container.load_container_config"), \
             patch("pm_core.container.create_qa_container"), \
             patch("pm_core.qa_loop.create_scenario_workdir",
                   return_value=(tmp_path / "repo", tmp_path / "scratch")), \
             patch("pm_core.qa_loop._build_concretize_cmd",
                   return_value="refiner"), \
             patch("pm_core.qa_loop._build_scenario_run_cmd",
                   return_value=("worker", str(tmp_path))), \
             patch("pm_core.tmux.new_window_get_pane", return_value="%56"), \
             patch("pm_core.tmux.split_pane_at", side_effect=gone), \
             patch("pm_core.tmux.pane_exists", return_value=False), \
             patch("pm_core.qa_loop._concretize_scenario",
                   return_value=(None, None)), \
             patch.object(qa_loop._log, "handlers",
                          qa_loop._log.handlers + [caplog.handler]), \
             caplog.at_level(logging.INFO, logger="pm.qa_loop"):
            launch = (qa_loop._launch_scenarios_in_containers
                      if mode == "container"
                      else qa_loop._launch_scenarios_in_tmux)
            launch(state, {}, {"id": "pr-1"}, "sess", None, str(tmp_path))
        msgs = [r.getMessage() for r in caplog.records]
        assert not any(m.startswith("Launched scenario") for m in msgs), msgs
        assert not any(r.exc_info for r in caplog.records)
        assert any("refiner pane %56 is gone" in m for m in msgs), msgs
        assert sc.pane_id is None

    def test_worker_split_failure_with_live_refiner_keeps_traceback(
            self, caplog, monkeypatch):
        """Real tmux: an unexpected split failure (refiner pane still
        there) is logged with its traceback, and the refiner pane is
        closed, so the poll loop finds no pane in the scenario window
        (dead worker: relaunch) instead of taking the refiner for the
        worker through its first-pane fallback."""
        import logging
        import shutil
        import subprocess
        import tempfile
        from pm_core import qa_loop
        if not shutil.which("tmux"):
            pytest.skip("tmux not installed")
        d = tempfile.mkdtemp(prefix="pmsp", dir="/tmp")
        sock = os.path.join(d, "s")
        monkeypatch.setenv("PM_TMUX_SOCKET", sock)
        t = ["tmux", "-S", sock]

        def tm(*a):
            return subprocess.run(t + list(a), check=True, capture_output=True,
                                  text=True).stdout.strip()
        sc = qa_loop.QAScenario(index=3, title="t", focus="f")
        try:
            tm("new-session", "-d", "-s", "sess", "-n", "main", "sleep 60")
            refiner = tm("new-window", "-d", "-P", "-F", "#{pane_id}", "-t",
                         "sess:", "-n", "qa-s3", "sleep 60")
            assert qa_loop.find_claude_pane("sess", "qa-s3") == refiner
            with patch("pm_core.tmux.split_pane_at",
                       side_effect=RuntimeError("boom")), \
                 patch.object(qa_loop._log, "handlers",
                              qa_loop._log.handlers + [caplog.handler]), \
                 caplog.at_level(logging.INFO, logger="pm.qa_loop"):
                assert qa_loop._split_worker_pane(sc, refiner, "w", "/") is None
            assert caplog.records and all(r.exc_info for r in caplog.records)
            assert qa_loop.find_claude_pane("sess", "qa-s3") is None
        finally:
            subprocess.run(t + ["kill-server"], capture_output=True)
            shutil.rmtree(d, ignore_errors=True)

    def test_split_failure_traceback_names_the_tmux_error(
            self, caplog, monkeypatch):
        """Real tmux: a split into a window too small for a new pane is
        logged with a traceback whose last line carries tmux's reason
        ("no space for new pane"), not only the exit status."""
        import logging
        import shutil
        import subprocess
        import tempfile
        from pm_core import qa_loop
        if not shutil.which("tmux"):
            pytest.skip("tmux not installed")
        d = tempfile.mkdtemp(prefix="pmsp", dir="/tmp")
        sock = os.path.join(d, "s")
        monkeypatch.setenv("PM_TMUX_SOCKET", sock)
        t = ["tmux", "-S", sock]

        def tm(*a):
            return subprocess.run(t + list(a), check=True, capture_output=True,
                                  text=True).stdout.strip()
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        try:
            tm("new-session", "-d", "-s", "sess", "-n", "main", "sleep 60")
            refiner = tm("new-window", "-d", "-P", "-F", "#{pane_id}", "-t",
                         "sess:", "-n", "qa-s1", "sleep 60")
            tm("resize-window", "-t", "sess:qa-s1", "-y", "2")
            with patch.object(qa_loop._log, "handlers",
                              qa_loop._log.handlers + [caplog.handler]), \
                 caplog.at_level(logging.INFO, logger="pm.qa_loop"):
                assert qa_loop._split_worker_pane(
                    sc, refiner, "sleep 1", "/") is None
            rec = [r for r in caplog.records if r.exc_info]
            assert rec, caplog.records
            last = caplog.text.rstrip().splitlines()[-1]
            assert "no space for new pane" in last, caplog.text
        finally:
            subprocess.run(t + ["kill-server"], capture_output=True)
            shutil.rmtree(d, ignore_errors=True)

    @pytest.mark.parametrize("mode", ["container", "tmux"])
    def test_closed_refiner_window_skips_the_worker_route_gate(
            self, tmp_path, caplog, mode):
        """PR cleanup closes the refiner's window (and removes its
        container) under a stopping run: the worker is not gated on its
        route, which would report the container being removed as an
        unusable route ("worker waiting — ... Remedy: ...")."""
        import logging
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=5, title="t", focus="f")
        state = qa_loop.QALoopState(pr_id="pr-1", qa_workdir=str(tmp_path))
        state.scenarios = [sc]
        gates = []

        def gate(state, pr_data, data, scenario, session_type, **kw):
            gates.append(session_type)
            return session_type != "qa_scenario"
        with patch("pm_core.qa_loop._route_gate", side_effect=gate), \
             patch("pm_core.qa_loop._route_checker",
                   return_value=lambda: _status(True)), \
             patch("pm_core.qa_loop._route_mounts", return_value={}), \
             patch("pm_core.container.load_container_config"), \
             patch("pm_core.container.create_qa_container"), \
             patch("pm_core.qa_loop.create_scenario_workdir",
                   return_value=(tmp_path / "repo", tmp_path / "scratch")), \
             patch("pm_core.qa_loop._build_concretize_cmd",
                   return_value="refiner"), \
             patch("pm_core.qa_loop._build_scenario_run_cmd",
                   return_value=("worker", str(tmp_path))), \
             patch("pm_core.tmux.new_window_get_pane", return_value="%38"), \
             patch("pm_core.tmux.split_pane_at") as split, \
             patch("pm_core.tmux.pane_exists", return_value=False), \
             patch("pm_core.qa_loop._concretize_scenario",
                   return_value=(None, None)), \
             patch.object(qa_loop._log, "handlers",
                          qa_loop._log.handlers + [caplog.handler]), \
             caplog.at_level(logging.INFO, logger="pm.qa_loop"):
            launch = (qa_loop._launch_scenarios_in_containers
                      if mode == "container"
                      else qa_loop._launch_scenarios_in_tmux)
            launch(state, {}, {"id": "pr-1"}, "sess", None, str(tmp_path))
        msgs = [r.getMessage() for r in caplog.records]
        assert "qa_scenario" not in gates, gates
        split.assert_not_called()
        assert any("refiner pane %38 is gone" in m for m in msgs), msgs
        assert any("worker pane not created" in m for m in msgs), msgs
        assert not any(m.startswith("Launched scenario") for m in msgs), msgs
        assert sc.pane_id is None

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

    def test_recovered_route_does_not_claim_resume_of_a_dead_pane(self):
        """The stalled pane died before the route came back: no nudge is
        sent, so the status must not say the session was resumed."""
        from pm_core import qa_loop
        state = qa_loop.QALoopState(pr_id="pr-1")
        statuses = iter([_status(False), _status(True)])
        watch = qa_loop._RouteStallWatch(state, lambda: next(statuses), "w")
        with patch("pm_core.tmux.send_keys") as send:
            assert watch.on_idle_without_verdict("%5", None)
            stalled_msg = state.latest_output
            with patch("pm_core.tmux.pane_exists", return_value=False), \
                 patch("pm_core.qa_loop._route_clock", return_value=1e12):
                watch.tick()
        send.assert_not_called()
        assert watch.stalled_pane is None
        assert state.latest_output == stalled_msg
        assert "resumed" not in (state.latest_output or "")

    def test_nudge_send_failure_does_not_claim_resume(self, tmp_path):
        """The pane dies between the liveness check and the nudge: the
        failed send is not reported as a resume."""
        from pm_core import qa_loop
        tr = tmp_path / "t.jsonl"
        tr.write_text(json.dumps(_api_error_record("e1")) + "\n")
        state = qa_loop.QALoopState(pr_id="pr-1")
        watch = qa_loop._RouteStallWatch(state, lambda: _status(True), "w")
        with patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.tmux.send_keys",
                   side_effect=RuntimeError("can't find pane")):
            assert watch.on_idle_without_verdict("%5", str(tr))
        assert "resumed" not in (state.latest_output or "")

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

    def test_reminder_to_a_vanished_pane_does_not_end_the_run(self, tmp_path):
        """The pane dies between the tick's liveness check and the
        reminder: the failed send is logged and verdict collection goes
        on (an exception here used to crash the whole QA thread)."""
        import subprocess
        from pm_core import qa_loop
        tr = tmp_path / "t.jsonl"
        tr.write_text("")
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

        def send(p, m):
            sent.append(m)
            raise subprocess.CalledProcessError(1, ["tmux", "send-keys"])
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
             patch("pm_core.tmux.send_keys", side_effect=send):
            self._poll(state, tmp_path, [worker_route.RouteStatus(True)])
        assert len(sent) == 1 and sent[0].startswith("Reminder: your verdict")
        assert state.scenario_verdicts[1] == "PASS"

    def test_flagged_followup_to_a_vanished_pane_is_input_required(
            self, tmp_path):
        """Verification flags a PASS and the worker pane dies between the
        liveness check and the follow-up: the scenario is settled as
        INPUT_REQUIRED like a window already gone, instead of the send
        error ending the whole QA run."""
        import subprocess
        from pm_core import qa_loop
        tr = tmp_path / "t.jsonl"
        tr.write_text("")
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        sc.window_name, sc.session_id, sc.pane_id = "w1", "sid-1", "%5"
        sc.transcript_path = str(tr)
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        t0 = time.time() + 1e4
        sent = []

        def send(p, m):
            sent.append(m)
            raise subprocess.CalledProcessError(1, ["tmux", "send-keys"])
        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
             patch("pm_core.qa_loop._get_verification_max_retries",
                   return_value=2), \
             patch("pm_core.qa_loop._verify_single_scenario",
                   return_value=(False, "ran nothing", None)), \
             patch("pm_core.hook_events.read_event",
                   return_value={"event_type": "idle_prompt",
                                 "timestamp": t0}), \
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   return_value="PASS"), \
             patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
                   return_value=""), \
             patch("pm_core.tmux.pane_exists", return_value=True), \
             patch("pm_core.tmux.send_keys", side_effect=send), \
             patch("pm_core.qa_loop._is_verification_enabled",
                   return_value=True), \
             patch("pm_core.qa_loop._route_checker",
                   return_value=lambda: worker_route.RouteStatus(True)), \
             patch("pm_core.qa_loop._write_resume_file"):
            qa_loop._poll_tmux_verdicts(state, {}, {}, "sess", "/tmp/w",
                                        tmp_path / "status.json",
                                        lambda *a: None)
        assert len(sent) == 1 and sent[0].startswith("Your verdict was "
                                                     "reviewed and flagged")
        assert state.scenario_verdicts[1] == "INPUT_REQUIRED"
        assert "window gone" in state.scenario_verdict_reasons[1]

    def test_flag_followup_never_lands_in_another_pane(self, tmp_path):
        """Host mode: the worker pane dies while its verifier runs, and the
        window's first pane is the still-live refiner.  The flag follow-up
        must not be typed into that pane; the scenario settles as
        INPUT_REQUIRED (window gone) instead."""
        from pm_core import qa_loop
        tr = tmp_path / "t.jsonl"
        tr.write_text("")
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        sc.window_name, sc.session_id, sc.pane_id = "w1", "sid-1", "%5"
        sc.transcript_path = str(tr)
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        t0 = time.time() + 1e4
        dead = set()
        sent = []

        def verify(*a, **k):
            dead.add("%5")  # worker pane killed while the verifier ran
            return (False, "ran nothing", None)
        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
             patch("pm_core.qa_loop._get_verification_max_retries",
                   return_value=2), \
             patch("pm_core.qa_loop._verify_single_scenario",
                   side_effect=verify), \
             patch("pm_core.qa_loop._get_scenario_pane", return_value="%3"), \
             patch("pm_core.qa_loop._relaunch_scenario_window",
                   side_effect=lambda *a: setattr(
                       state, "stop_requested", True)) as relaunch, \
             patch("pm_core.hook_events.read_event",
                   return_value={"event_type": "idle_prompt",
                                 "timestamp": t0}), \
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   return_value="PASS"), \
             patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
                   return_value=""), \
             patch("pm_core.tmux.pane_exists",
                   side_effect=lambda p: p not in dead), \
             patch("pm_core.tmux.send_keys",
                   side_effect=lambda p, m: sent.append((p, m))), \
             patch("pm_core.qa_loop._is_verification_enabled",
                   return_value=True), \
             patch("pm_core.qa_loop._route_checker",
                   return_value=lambda: worker_route.RouteStatus(True)), \
             patch("pm_core.qa_loop._write_resume_file"):
            qa_loop._poll_tmux_verdicts(state, {}, {}, "sess", "/tmp/w",
                                        tmp_path / "status.json",
                                        lambda *a: None)
        assert sent == []
        relaunch.assert_not_called()
        assert state.scenario_verdicts[1] == "INPUT_REQUIRED"
        assert "window gone" in state.scenario_verdict_reasons[1]

    def test_dead_worker_is_not_taken_for_the_refiner_pane(self, tmp_path):
        """Host mode: a worker dies while its route is down, and the
        window's first pane is the still-live refiner.  Later ticks must
        still see the worker as gone (not poll the refiner as if it were
        the worker), so it is relaunched once the route answers."""
        from pm_core import qa_loop
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        sc.window_name, sc.session_id, sc.pane_id = "w1", "sid-1", "%5"
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.scenarios = [sc]
        relaunches = []
        ticks = {"n": 0}
        t0 = time.time() + 1e4

        def relaunch(scenario, *a):
            relaunches.append(scenario.index)
            scenario.pane_id, scenario.session_id = "%9", "sid-2"
            return True

        def sleep(_):
            ticks["n"] += 1
            if ticks["n"] > 50:  # bound the buggy (never relaunched) case
                state.stop_requested = True
        with patch("pm_core.qa_loop._get_scenario_pane", return_value="%3"), \
             patch("pm_core.qa_loop._relaunch_scenario_window",
                   side_effect=relaunch), \
             patch("pm_core.qa_loop.time.sleep", side_effect=sleep), \
             patch("pm_core.qa_loop._VERDICT_GRACE_PERIOD", 0), \
             patch("pm_core.qa_loop._get_verdict_reminder_timeout",
                   return_value=None), \
             patch("pm_core.hook_events.read_event", side_effect=lambda sid: {
                 "event_type": "idle_prompt",
                 "timestamp": t0 + (sid == "sid-2")}), \
             patch("pm_core.qa_loop.extract_verdict_from_transcript",
                   side_effect=lambda *a: (
                       "PASS" if sc.session_id == "sid-2" else None)), \
             patch("pm_core.qa_loop.extract_verdict_reason_from_transcript",
                   return_value=""), \
             patch("pm_core.tmux.pane_exists",
                   side_effect=lambda p: p != "%5"), \
             patch("pm_core.tmux.send_keys") as send:
            self._poll(state, tmp_path, [_status(False)] * 3 + [_status(True)])
        assert relaunches == [1]
        assert state.scenario_verdicts[1] == "PASS"
        assert not [c for c in send.call_args_list if c.args[0] == "%3"]

    def test_relaunch_reuses_the_window_its_refiner_keeps_alive(
            self, monkeypatch):
        """Real tmux: only the worker pane of qa-<pr>-sN died; the refiner
        pane keeps the window.  The relaunched worker is a new pane in that
        same window (never the refiner pane, never a second window of the
        same name); with the window gone it gets a fresh window."""
        import shutil
        import subprocess
        import tempfile
        from pm_core import qa_loop
        if not shutil.which("tmux"):
            pytest.skip("tmux not installed")
        d = tempfile.mkdtemp(prefix="pmrl", dir="/tmp")
        sock = os.path.join(d, "s")
        monkeypatch.setenv("PM_TMUX_SOCKET", sock)
        t = ["tmux", "-S", sock]

        def tm(*a):
            return subprocess.run(t + list(a), check=True, capture_output=True,
                                  text=True).stdout.strip()

        def windows():
            return tm("list-panes", "-s", "-t", "sess", "-F",
                      "#{window_name} #{window_id} #{pane_id}").splitlines()
        sc = qa_loop.QAScenario(index=1, title="t", focus="f")
        state = qa_loop.QALoopState(pr_id="pr-1")
        state.qa_workdir = d
        pr_data = {"id": "pr-1"}
        win = qa_loop._scenario_window_name(pr_data, 1)
        try:
            tm("new-session", "-d", "-s", "sess", "-n", "main", "sleep 60")
            refiner = tm("new-window", "-d", "-P", "-F", "#{pane_id}", "-t",
                         "sess:", "-n", win, "sleep 60")
            worker = tm("split-window", "-d", "-v", "-t", refiner, "-P", "-F",
                        "#{pane_id}", "sleep 60")
            sc.window_name, sc.pane_id = win, worker
            tm("kill-pane", "-t", worker)
            with patch("pm_core.qa_loop._build_scenario_run_cmd",
                       return_value=("sleep 60", d)), \
                 patch("pm_core.qa_loop._resolve_qa_model"), \
                 patch("pm_core.container.is_container_mode_enabled",
                       return_value=False), \
                 patch("pm_core.pane_layout.register_and_rebalance"):
                assert qa_loop._relaunch_scenario_window(
                    sc, state, {}, pr_data, "sess", d)
                first = sc.pane_id
                rows = [r.split() for r in windows() if r.startswith(win + " ")]
                assert first not in (refiner, worker)
                assert {r[2] for r in rows} == {refiner, first}
                assert len({r[1] for r in rows}) == 1  # one window
                # The whole window gone: a fresh window, one of that name.
                tm("kill-window", "-t", rows[0][1])
                assert qa_loop._relaunch_scenario_window(
                    sc, state, {}, pr_data, "sess", d)
                rows = [r.split() for r in windows() if r.startswith(win + " ")]
                assert [r[2] for r in rows] == [sc.pane_id]
        finally:
            subprocess.run(t + ["kill-server"], capture_output=True)
            shutil.rmtree(d, ignore_errors=True)

    def test_submit_survives_pane_dying_during_enters(self):
        """_send_submitted: the message typed, then the pane dies — the
        Enters stop quietly; a pane that cannot take the message raises."""
        import subprocess
        from pm_core import qa_loop
        calls = []

        def send(p, m):
            calls.append(m)
            if m == "":
                raise subprocess.CalledProcessError(1, ["tmux"])
        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.tmux.send_keys", side_effect=send):
            qa_loop._send_submitted("%5", "hi")
        assert calls == ["hi", ""]
        with patch("pm_core.qa_loop.time.sleep"), \
             patch("pm_core.tmux.send_keys",
                   side_effect=subprocess.CalledProcessError(1, ["tmux"])):
            with pytest.raises(subprocess.CalledProcessError):
                qa_loop._send_submitted("%5", "hi")

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
            "model": re.sub(r"\[[^\]]*\]$", "", model.split("/")[-1]),
            "content": "ok"}}) + "\n")
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

    def _probe(self, cwd, model=MODEL):
        cfg = ProviderConfig(name=ROUTE, type="router",
                             api_base="http://127.0.0.1:1", model=model)
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

    def test_1m_route_model_matches_the_transcript_model(self, probe_env):
        # QA S59: a route model with a context suffix (work/x[1m]) is sent
        # as work/x plus the 1M beta header, and real Claude records plain
        # x in the transcript, so a healthy route printed "Live: FAILED -
        # model mismatch".
        cwd = probe_env / "probe"
        cwd.mkdir()
        out = self._probe(cwd, model=f"{MODEL}[1m]")
        assert out["transcript_models"] == ["claude-opus-5-5"]
        assert out["ok"], out

    def test_transcript_model_off_the_route_still_fails(self):
        cfg = ProviderConfig(name=ROUTE, type="router",
                             api_base="http://127.0.0.1:1", model=f"{MODEL}[1m]")
        assert worker_route.model_on_route(cfg, "claude-opus-5-5")
        assert worker_route.model_on_route(cfg, f"{MODEL}[1m]")
        assert not worker_route.model_on_route(cfg, "claude-fable-5-1")
        assert not worker_route.model_on_route(cfg, "opus-5-5")

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


@pytest.mark.parametrize("state", ["down", "fresh", "reused_mounted",
                                   "reused_unmounted"])
def test_workflow_container_route_mount_and_fail_closed(pm_home_dir, monkeypatch, state):
    """The shared impl/review/signoff wrapper never launches an unavailable
    route, and never reuses a running container that lacks the route mount
    (create_container reuses by name; the ensure step would refuse there)."""
    from pm_core import container as cm
    from unittest.mock import Mock
    _write_providers(pm_home_dir)
    ready = state != "down"
    monkeypatch.setattr(cm, "is_container_mode_enabled", lambda: True)
    monkeypatch.setattr(cm, "load_container_config", lambda: cm.ContainerConfig())
    monkeypatch.setattr(cm, "_make_container_name", lambda *a, **k: "review-test")
    monkeypatch.setattr(cm, "container_is_running",
                        lambda name: state.startswith("reused"))
    monkeypatch.setattr(worker_route, "container_has_route_mount",
                        lambda name: state == "reused_mounted")
    create = Mock()
    monkeypatch.setattr(cm, "create_container", create)
    monkeypatch.setattr(cm, "build_exec_cmd", lambda name, cmd, **kw: cmd)
    monkeypatch.setattr("pm_core.push_proxy.get_proxy_socket_path", lambda name: None)
    check = Mock(return_value=worker_route.RouteStatus(
        ready, ROUTE, "router offline" if not ready else "", "start router"))
    monkeypatch.setattr(worker_route, "check_route", check)
    bridge = {Path("/bridge"): "/run/pm-route"}
    mounts = Mock(return_value=bridge)
    monkeypatch.setattr(worker_route, "container_mounts", mounts)
    existing = {Path("/evidence"): "/evidence"}
    if state in ("down", "reused_unmounted"):
        match = ("router offline" if state == "down"
                 else "review-test is running without the route socket mount")
        with pytest.raises(cm.ContainerError, match=match):
            cm.wrap_claude_cmd("ROUTED", "/w", provider=ROUTE, extra_rw_mounts=existing,
                               session_type="review")
        create.assert_not_called()
        assert mounts.called == (state != "down")
    else:
        cmd, name = cm.wrap_claude_cmd("ROUTED", "/w", provider=ROUTE,
                                       extra_rw_mounts=existing,
                                       session_type="review")
        assert (cmd, name) == ("ROUTED", "review-test")
        assert create.call_args.kwargs["extra_rw_mounts"] == {**existing, **bridge}
        assert existing == {Path("/evidence"): "/evidence"}
    assert check.call_args.args[0].provider == ROUTE
    assert check.call_args.kwargs == {"container": True,
                                      "session_type": "review"}


@pytest.mark.parametrize("failure", ["router_down", "expired", "unconfigured"])
def test_workflow_role_remedy_says_relaunch_not_qa_wait(pm_home_dir, monkeypatch,
                                                         failure):
    """impl/review/sign-off are refused once (ContainerError), not waited
    for, so their remedy must not promise QA's automatic launch or point at
    the QA session types; the QA gate keeps its wording."""
    from pm_core.model_config import ModelResolution
    creds = pm_home_dir / "creds.json"
    _creds(creds, -60)
    _write_providers(pm_home_dir, **({"credentials_file": str(creds)}
                                     if failure == "expired" else {}))
    monkeypatch.setattr(route_bridge, "tcp_connectable",
                        lambda *a, **k: failure != "router_down")
    res = ModelResolution(provider="nope" if failure == "unconfigured" else ROUTE)
    qa = worker_route.check_route(res, container=True)
    impl = worker_route.check_route(res, container=True, session_type="impl")
    assert not qa.ok and not impl.ok and qa.problem == impl.problem
    assert "QA" not in impl.remedy and "qa_" not in impl.remedy
    if failure != "unconfigured":
        assert "QA launches the session automatically" in qa.remedy
        assert "then launch the impl session again" in impl.remedy
    if failure != "router_down":  # these also name the main-account way out
        assert "pm model set qa_scenario" in qa.remedy
        assert "'pm model set impl <model> --project'" in impl.remedy
        # A PR override wins over the project setting, and since per-PR
        # role exceptions either of its keys can be what selects the route.
        for st in (qa, impl):
            assert "PR's 'session_models' entry or 'model' override" in st.remedy


def test_unrouted_provider_reuses_a_running_container_untouched(pm_home_dir, monkeypatch):
    """A non-router provider adds no mount and no reuse refusal."""
    from pm_core import container as cm
    from unittest.mock import Mock
    _write_providers(pm_home_dir)
    monkeypatch.setattr(cm, "is_container_mode_enabled", lambda: True)
    monkeypatch.setattr(cm, "load_container_config", lambda: cm.ContainerConfig())
    monkeypatch.setattr(cm, "_make_container_name", lambda *a, **k: "impl-test")
    monkeypatch.setattr(cm, "container_is_running", lambda name: True)
    has_mount = Mock(return_value=False)
    monkeypatch.setattr(worker_route, "container_has_route_mount", has_mount)
    create = Mock()
    monkeypatch.setattr(cm, "create_container", create)
    monkeypatch.setattr(cm, "build_exec_cmd", lambda name, cmd, **kw: cmd)
    monkeypatch.setattr("pm_core.push_proxy.get_proxy_socket_path", lambda name: None)
    assert cm.wrap_claude_cmd("CMD", "/w", provider="claude") == ("CMD", "impl-test")
    has_mount.assert_not_called()
    assert create.call_args.kwargs["extra_rw_mounts"] == {}


@pytest.mark.parametrize("route_ok", [True, False])
def test_impl_start_builds_and_wraps_for_the_selected_route(tmp_path, monkeypatch, route_ok):
    """`pm pr start` in container mode builds the impl command for the
    container on the selected route and hands the provider to the shared
    wrapper; a route the wrapper refuses launches no window (exit 1)."""
    import yaml
    from types import SimpleNamespace
    from unittest.mock import MagicMock, Mock
    from click.testing import CliRunner
    from pm_core import container as cm, store
    from pm_core.cli import pr as pr_mod
    pm_dir = tmp_path / "pm"
    pm_dir.mkdir()
    workdir = tmp_path / "work"
    workdir.mkdir()
    # The PR-wide model stays on main; only impl is routed, by a role
    # exception (f1865615), which must reach the impl resolution.
    store.save({"project": {"name": "t", "repo": str(tmp_path), "base_branch": "master"},
                "prs": [{"id": "pr-001", "title": "T", "branch": "pm/pr-001",
                         "status": "in_progress", "workdir": str(workdir),
                         "model": "opus",
                         "session_models": {"impl": f"provider:{ROUTE}"}}]}, pm_dir)
    tmux = MagicMock()
    tmux.session_exists.return_value = True
    tmux.find_window_by_name.return_value = None
    tmux.new_window_get_pane.return_value = "%1"
    build = Mock(return_value="ROUTED")
    wrap = Mock(return_value=("WRAPPED", "impl-pr-001"))
    if not route_ok:
        wrap.side_effect = cm.ContainerError("work route 'claude-work' unavailable: x")
    committed = SimpleNamespace(returncode=0, stdout=yaml.safe_dump(store.load(pm_dir)),
                                stderr="")
    monkeypatch.setattr(pr_mod.git_ops, "run_git", lambda *a, **k: committed)
    monkeypatch.setattr(pr_mod, "tmux_mod", tmux)
    monkeypatch.setattr(pr_mod, "pane_registry", MagicMock())
    monkeypatch.setattr(pr_mod, "pane_layout", MagicMock())
    monkeypatch.setattr(pr_mod, "prompt_gen", MagicMock())
    monkeypatch.setattr(pr_mod, "find_claude", lambda: "/usr/bin/claude")
    monkeypatch.setattr(pr_mod, "build_claude_shell_cmd", build)
    monkeypatch.setattr(pr_mod, "state_root", lambda: pm_dir)
    monkeypatch.setattr(pr_mod, "_get_pm_session", lambda: "pm-sess")
    monkeypatch.setattr(cm, "wrap_claude_cmd", wrap)
    monkeypatch.setattr(cm, "is_container_mode_enabled", lambda: True)
    resolved = []
    monkeypatch.setattr("pm_core.model_config.resolve_model_and_provider",
                        lambda st, **k: resolved.append((st, k["pr_model"])) or
                        SimpleNamespace(model=None, provider=ROUTE, effort="high"))
    result = CliRunner().invoke(pr_mod.pr, ["start", "pr-001"])
    assert resolved == [("impl", f"provider:{ROUTE}")]
    kw = build.call_args.kwargs
    assert (kw["session_type"], kw["container"], kw["provider"]) == ("impl", True, ROUTE)
    assert kw["cwd"] == cm._CONTAINER_WORKDIR and kw["write_dir"] == str(workdir)
    assert wrap.call_args.kwargs["provider"] == ROUTE
    assert wrap.call_args.kwargs["session_type"] == "impl"  # names the remedy
    if route_ok:
        assert result.exit_code == 0, result.output
        launched = tmux.new_window.call_args or tmux.new_window_get_pane.call_args
        assert "WRAPPED" in launched.args
    else:
        assert result.exit_code == 1
        assert "unavailable" in result.output
        tmux.new_window.assert_not_called()
        tmux.new_window_get_pane.assert_not_called()


def _launch_on_missing_provider(provider="missing-route", **kw):
    """The real launcher with a provider this host does not configure."""
    from pm_core.claude_launcher import build_claude_shell_cmd
    with patch("pm_core.claude_launcher.log_shell_command"):
        return build_claude_shell_cmd(provider=provider, **kw)


def test_unconfigured_provider_is_a_clean_cli_error(pm_home_dir, monkeypatch, capsys):
    """`pm pr start/review/signoff/merge` build their command before any
    route gate, so a missing provider raised a traceback whose last line
    held the remedy; the review loop shows only stderr[:500] of
    `pm pr review`, which cut it off.  It is now one `Error:` line."""
    import pm_core.cli as cli_mod
    monkeypatch.setattr(cli_mod, "cli", lambda: _launch_on_missing_provider(
        session_type="review", container=True))
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("Error: provider 'missing-route' is not configured")
    assert "Traceback" not in err
    head = err[:500]  # review_loop._launch_review_window's detail
    assert "pm provider add missing-route" in head  # configure it, or
    assert "'pm model show' lists them, PR overrides included" in head


@pytest.mark.parametrize("starter", ["start_qa_background", "resume_qa_background"])
def test_unconfigured_provider_explains_a_stopped_qa_run(pm_home_dir, starter, caplog):
    """Planner, s0, verifier and finalizer launch without a route gate, so
    a missing provider ended the run with a bare "QA thread crashed".

    QA S64: the pm log still recorded it as "QA background thread crashed"
    with a full traceback; it is one warning line now."""
    import logging
    from pm_core import qa_loop
    state = qa_loop.QALoopState(pr_id="pr-001")
    sync = "run_qa_sync" if starter == "start_qa_background" else "resume_qa_sync"
    with patch.object(qa_loop._log, "handlers",
                      qa_loop._log.handlers + [caplog.handler]), \
            caplog.at_level(logging.DEBUG, logger="pm.qa_loop"), \
            patch.object(qa_loop, sync, side_effect=lambda *a, **k:
                         _launch_on_missing_provider(session_type="qa_planning")):
        getattr(qa_loop, starter)(state, Path("/nonexistent"), {"id": "pr-001"}).join(5)
    assert (state.running, state.latest_verdict) == (False, "ERROR")
    assert state.latest_output.startswith(
        "QA stopped: provider 'missing-route' is not configured")
    assert "'pm model show' lists them" in state.latest_output
    assert state.latest_output.endswith("then start QA again")
    ends = [r for r in caplog.records if "pr-001" in r.getMessage()]
    assert [(r.levelname, r.exc_info) for r in ends] == [("WARNING", None)]
    assert ends[0].getMessage().startswith(
        "QA stopped for pr-001: provider 'missing-route' is not configured")
    assert "crashed" not in caplog.text


# Review c189 i9: a hand-edited entry for the *selected* provider used to
# raise AttributeError/ValueError from whichever launch step touched the
# bad field (a traceback, "QA thread crashed", a crashed `pm model show`).
# It is now a ProviderNotFoundError (ProviderEntryError), reported like a
# missing provider on every surface, and never a fallback to plain claude.
_BAD_ENTRIES = {
    "null": None,
    "string": "router",
    "int_api_base": {"type": "router", "api_base": 8790, "model": MODEL},
    "int_model": {"type": "router", "api_base": "http://127.0.0.1:8790",
                  "model": 5},
    "unknown_type": {"type": "routr", "api_base": "http://127.0.0.1:8790",
                     "model": MODEL},
    "list_aliases": {"type": "router", "api_base": "http://127.0.0.1:8790",
                     "model": MODEL, "alias_models": ["x"]},
    "int_capabilities": {"type": "router", "api_base": "http://127.0.0.1:8790",
                         "model": MODEL, "capabilities": 5},
}


def _write_entry(home: Path, entry):
    import yaml
    (home / "providers.yaml").write_text(
        yaml.safe_dump({"providers": {ROUTE: entry}}))


@pytest.mark.parametrize("case", list(_BAD_ENTRIES))
def test_invalid_selected_entry_is_reported_like_a_missing_provider(
        pm_home_dir, case):
    from pm_core.claude_launcher import _resolve_provider, build_claude_shell_cmd
    from pm_core.providers import ProviderEntryError
    _write_entry(pm_home_dir, _BAD_ENTRIES[case])
    for strict in (True, False):  # never the non-strict claude fallback
        with pytest.raises(ProviderEntryError,
                           match=f"provider '{ROUTE}' in .*providers.yaml "
                                 "is not a valid entry"):
            get_provider(ROUTE, strict=strict)
    with pytest.raises(ProviderNotFoundError):
        build_claude_shell_cmd(prompt="hi", provider=ROUTE)
    with pytest.raises(ProviderNotFoundError):
        _resolve_provider(ROUTE)
    res = ModelResolution(provider=ROUTE, effort="high")
    st = worker_route.check_route(res)  # the QA gates wait on this
    assert not st.ok and "is not a valid entry" in st.problem
    assert "Remedy:" in st.message()
    assert worker_route.describe(res) == (
        f"route={ROUTE} (INVALID ENTRY in providers.yaml) effort=high")
    assert worker_route.container_mounts(res) == {}


def test_invalid_selected_entry_is_a_clean_cli_error(pm_home_dir, monkeypatch,
                                                     capsys):
    import pm_core.cli as cli_mod
    _write_entry(pm_home_dir, None)
    monkeypatch.setattr(cli_mod, "cli", lambda: _launch_on_missing_provider(
        ROUTE, session_type="review", container=True))
    with pytest.raises(SystemExit) as exc:
        cli_mod.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith(f"Error: provider '{ROUTE}' in ")
    assert "expected a mapping, got NoneType" in err
    assert f"'pm provider add {ROUTE} ...'" in err and "Traceback" not in err


def test_provider_list_and_test_name_an_invalid_entry(pm_home_dir):
    import yaml
    (pm_home_dir / "providers.yaml").write_text(yaml.safe_dump({"providers": {
        "broken": None,
        "caps": {"type": "local", "api_base": "http://x", "capabilities": 5},
        ROUTE: {"type": "router", "api_base": "http://127.0.0.1:8790",
                "model": MODEL}}}))
    cli = TestProviderCLI()
    r = cli._run("list")
    assert r.exit_code == 0, r.output
    assert f"{ROUTE}  type=router" in r.output
    assert "broken  INVALID ENTRY: expected a mapping, got NoneType" in r.output
    # Was joined raw (TypeError for 5; "c, o, d, e" for a string).
    assert ("caps  INVALID ENTRY: 'capabilities' must be a list of names"
            in r.output)
    r = cli._run("test", "broken")
    assert r.exit_code == 1 and "is not a valid entry" in r.output


def test_valid_entries_with_null_fields_still_load(pm_home_dir):
    # A key left blank (`launcher:`) reads as unset, as an absent key does.
    _write_entry(pm_home_dir, {"type": "router", "api_base":
                               "http://127.0.0.1:8790", "model": MODEL,
                               "launcher": None, "alias_models": None})
    p = get_provider(ROUTE, strict=True)
    assert (p.launcher, p.alias_models, p.model) == ("", {}, MODEL)


@pytest.mark.parametrize("text", ["- a\n- b\n", f"providers: [{ROUTE}]\n"],
                         ids=["list_file", "list_block"])
def test_non_mapping_providers_file_is_ignored(pm_home_dir, text):
    (pm_home_dir / "providers.yaml").write_text(text)
    assert get_provider().name == "claude"
    # Named, it is not found -- and the error says why (review c189 i11).
    with pytest.raises(ProviderNotFoundError, match="is not a mapping"):
        get_provider(ROUTE, strict=True)


# Review c189 i10: since i9 a blank `providers:` block (every entry
# commented out) reads as no providers, so launches say "add it with 'pm
# provider add ...'", but add/remove/default indexed the block and raised
# TypeError.  And i9 reads a non-mapping file as empty, so `pm provider add`
# overwrote it (pre-i9 it crashed before writing).
_ADD_ROUTE = ("add", ROUTE, "--type", "router", "--api-base",
              "http://127.0.0.1:8790", "--model", MODEL)


def test_provider_edits_fill_a_blank_providers_block(pm_home_dir):
    path = pm_home_dir / "providers.yaml"
    path.write_text("default: claude\nproviders:\n  # claude-work: ...\n")
    cli = TestProviderCLI()
    for args, out in ((("remove", "x"), "Provider 'x' not found."),
                      (("default", "x"), "Provider 'x' not found.")):
        r = cli._run(*args)
        assert (r.exit_code, type(r.exception)) == (1, SystemExit), r.output
        assert out in r.output
    r = cli._run(*_ADD_ROUTE)  # the remedy the launch error names
    assert r.exit_code == 0, r.output
    assert get_provider(ROUTE, strict=True).model == MODEL
    assert cli._run("default", ROUTE).exit_code == 0
    assert get_provider().name == ROUTE


@pytest.mark.parametrize("text,why", [
    ("- a\n- b\n", "it is not a mapping"),
    (f"providers: [{ROUTE}]\n", "its 'providers' block is not a mapping"),
    ("providers:\n  a: [\n", "it is not valid YAML (line 3)"),
], ids=["list_file", "list_block", "bad_yaml"])
def test_provider_edits_leave_an_unreadable_file_alone(pm_home_dir, monkeypatch,
                                                      text, why):
    from pm_core.providers import ProvidersFileError, set_default_provider
    path = pm_home_dir / "providers.yaml"
    path.write_text(text)
    cli = TestProviderCLI()
    # Refused before the endpoint check, which may ask to confirm.
    monkeypatch.setattr("pm_core.providers.check_provider",
                        lambda p: pytest.fail("checked a provider it cannot save"))
    for args in (_ADD_ROUTE, ("add", "ollama", "--api-base", "http://x"),
                 ("remove", ROUTE), ("default", ROUTE), ("default", "claude")):
        r = cli._run(*args)
        assert (r.exit_code, type(r.exception)) == (1, SystemExit), r.output
        assert f"Error: {path} cannot be changed: {why}." in r.output
        assert path.read_text() == text
    with pytest.raises(ProvidersFileError):
        set_default_provider("claude")
    assert path.read_text() == text


# Review c189 i11: pm reads a providers.yaml it cannot read (one stray tab,
# a list block) as having no providers, so every routed launch, the QA route
# gate and `pm provider test` said the route "is not configured ... (add it
# with 'pm provider add ...')" -- an entry the file may well hold, and a
# command i10 makes refuse such a file -- while `pm provider list` showed
# nothing wrong.  They now name the file's problem.
_UNREADABLE = {
    "bad_yaml": (f"providers:\n  {ROUTE}:\n    type: router\n"
                 f"\tmodel: {MODEL}\n", "it is not valid YAML (line 4)"),
    "list_block": (f"providers: [{ROUTE}]\n",
                   "its 'providers' block is not a mapping"),
    "list_file": (f"- {ROUTE}\n", "it is not a mapping"),
    "directory": (None, "it cannot be read (Is a directory)"),
}


@pytest.mark.parametrize("case", list(_UNREADABLE))
def test_unreadable_providers_file_is_named_not_reported_missing(
        pm_home_dir, case):
    from pm_core.claude_launcher import _resolve_provider, build_claude_shell_cmd
    from pm_core.providers import ProvidersFileUnreadableError
    text, why = _UNREADABLE[case]
    path = pm_home_dir / "providers.yaml"
    if text is None:
        path.mkdir()
    else:
        path.write_text(text)
    for launch in (lambda: get_provider(ROUTE, strict=True),
                   lambda: build_claude_shell_cmd(prompt="hi", provider=ROUTE),
                   lambda: _resolve_provider(ROUTE)):
        with pytest.raises(ProvidersFileUnreadableError) as exc:
            launch()
        assert str(exc.value) == (f"provider '{ROUTE}' cannot be looked up "
                                  f"in {path}: {why}; fix the file by hand")
    assert get_provider().name == "claude"  # nothing selected: unchanged
    res = ModelResolution(provider=ROUTE, effort="high")
    st = worker_route.check_route(res)  # the QA gates wait on this
    assert not st.ok and why in st.problem
    assert st.remedy.startswith(f"fix {path} by hand, or ")
    assert worker_route.describe(res) == (
        f"route={ROUTE} (providers.yaml UNREADABLE) effort=high")
    assert worker_route.container_mounts(res) == {}
    cli = TestProviderCLI()
    r = cli._run("list")
    assert r.exit_code == 0, r.output
    assert f"  NOT READ: {path}: {why}; fix it by hand" in r.output
    r = cli._run("test", ROUTE)
    assert r.exit_code == 1 and why in r.output
    assert "pm provider add" not in r.output


def test_readable_file_without_the_provider_still_says_add_it(pm_home_dir):
    from pm_core.providers import ProvidersFileUnreadableError
    for text in ("providers:\n  # claude-work: ...\n",
                 "providers:\n  other: {type: local, api_base: http://x}\n"):
        (pm_home_dir / "providers.yaml").write_text(text)
        with pytest.raises(ProviderNotFoundError,
                           match=f"add it with 'pm provider add {ROUTE}") as exc:
            get_provider(ROUTE, strict=True)
        assert not isinstance(exc.value, ProvidersFileUnreadableError)
        r = TestProviderCLI()._run("list")
        assert r.exit_code == 0 and "NOT READ" not in r.output


@pytest.mark.parametrize("starter,default", [
    ("start_qa_background", "QA thread crashed"),
    ("resume_qa_background", "QA resume thread crashed")])
def test_other_qa_thread_crashes_keep_their_message(starter, default, caplog):
    import logging
    from pm_core import qa_loop
    state = qa_loop.QALoopState(pr_id="pr-001")
    sync = "run_qa_sync" if starter == "start_qa_background" else "resume_qa_sync"
    with patch.object(qa_loop._log, "handlers",
                      qa_loop._log.handlers + [caplog.handler]), \
            caplog.at_level(logging.DEBUG, logger="pm.qa_loop"), \
            patch.object(qa_loop, sync, side_effect=RuntimeError("boom")):
        getattr(qa_loop, starter)(state, Path("/nonexistent"), {"id": "pr-001"}).join(5)
    assert (state.latest_verdict, state.latest_output) == ("ERROR", default)
    crash = [r for r in caplog.records if "crashed for pr-001" in r.getMessage()]
    assert len(crash) == 1 and crash[0].levelname == "ERROR" and crash[0].exc_info


# Review a5a3 i1: `pm pr auto-sequence` runs QA in a detached
# `pm pr qa-run-bg` driver whose output goes to /dev/null and which writes
# no qa_status.json before the planner launches.  A provider setup error of
# a gate-less QA session (planner, s0, verifier, finalizer) ended that driver
# with a traceback in the pm log only, and every later tick relaunched it
# ("running: qa (launched)") with no remedy anywhere it reports.
_UNGATED_ROLES = ["qa_planning", "qa_interactive", "qa_verification",
                  "qa_finalize"]


@pytest.mark.parametrize("role", _UNGATED_ROLES)
def test_ungated_qa_provider_check_raises(pm_home_dir, role):
    from pm_core import qa_loop
    pr = {"id": "pr-001", "session_models": {role: "provider:missing-route"}}
    with pytest.raises(ProviderNotFoundError, match="missing-route"):
        qa_loop.check_ungated_qa_providers(pr, {})


@pytest.mark.parametrize("pr", [
    {"id": "pr-001"},
    # Routed roles wait at their route gate with a remedy instead.
    {"id": "pr-001", "session_models": {"qa_scenario": "provider:missing-route",
                                        "qa_concretize": "provider:missing-route"}},
])
def test_ungated_qa_provider_check_passes(pm_home_dir, pr):
    from pm_core import qa_loop
    qa_loop.check_ungated_qa_providers(pr, {})


def test_ungated_qa_provider_check_reports_bad_entry(pm_home_dir):
    from pm_core import qa_loop
    (pm_home_dir / "providers.yaml").write_text(
        "providers:\n  claude-work: just a string\n")
    pr = {"id": "pr-001", "model": "provider:claude-work"}
    with pytest.raises(ProviderNotFoundError, match="providers.yaml"):
        qa_loop.check_ungated_qa_providers(pr, {})


@pytest.mark.parametrize("role", _UNGATED_ROLES)
def test_auto_sequence_qa_launch_is_a_clean_error(pm_home_dir, role,
                                                  monkeypatch, capsys):
    import pm_core.cli as cli_mod
    from pm_core.cli import pr as pr_cli
    pr = {"id": "pr-001", "status": "qa",
          "session_models": {role: "provider:missing-route"}}
    monkeypatch.setattr(pr_cli.store, "load",
                        lambda root: {"project": {}, "prs": [pr]})
    with patch.object(pr_cli.subprocess, "Popen") as popen:
        monkeypatch.setattr(cli_mod, "cli", lambda: pr_cli._launch_qa_detached(
            Path("/nonexistent"), "pr-001"))
        with pytest.raises(SystemExit) as exc:
            cli_mod.main()
    popen.assert_not_called()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("Error: provider 'missing-route' is not configured")
    assert "'pm model show' lists them, PR overrides included" in err
    assert "Traceback" not in err


def test_auto_sequence_qa_launch_spawns_driver_when_configured(pm_home_dir,
                                                               monkeypatch):
    from pm_core.cli import pr as pr_cli
    pr = {"id": "pr-001", "status": "qa",
          "session_models": {"qa_scenario": "provider:missing-route"}}
    monkeypatch.setattr(pr_cli.store, "load",
                        lambda root: {"project": {}, "prs": [pr]})
    with patch.object(pr_cli.subprocess, "Popen") as popen:
        pr_cli._launch_qa_detached(Path("/nonexistent"), "pr-001")
    assert popen.call_args.args[0][-2:] == ["qa-run-bg", "pr-001"]


@pytest.mark.parametrize("error,level", [
    ("provider", "WARNING"), ("other", "ERROR")])
def test_detached_qa_driver_logs_provider_error_without_traceback(
        pm_home_dir, tmp_path, caplog, error, level):
    """The driver logged a provider setup error as "QA crashed" with a
    traceback, as the TUI QA threads did before bad02547."""
    import logging
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_cli
    from pm_core import qa_loop
    pr = {"id": "pr-001", "status": "qa"}
    data = {"project": {}, "prs": [pr]}
    side = ((lambda *a, **k: _launch_on_missing_provider(
        session_type="qa_planning")) if error == "provider"
        else RuntimeError("boom"))
    with patch.object(qa_loop._log, "handlers",
                      qa_loop._log.handlers + [caplog.handler]), \
            caplog.at_level(logging.DEBUG, logger="pm.qa_loop"), \
            patch.object(pr_cli, "state_root", return_value=tmp_path), \
            patch.object(pr_cli.store, "load", return_value=data), \
            patch.object(pr_cli.store, "locked_update"), \
            patch("pm_core.signoff.clear_return_awaiting"), \
            patch.object(qa_loop, "run_qa_sync", side_effect=side):
        result = CliRunner().invoke(pr_cli.pr_qa_run_bg, ["pr-001"], obj=data)
    assert result.exit_code == 1
    ends = [r for r in caplog.records if "pr-001" in r.getMessage()]
    assert [r.levelname for r in ends] == [level]
    if error == "provider":
        assert ends[0].exc_info is None
        assert ends[0].getMessage().startswith(
            "QA stopped for pr-001: provider 'missing-route' is not configured")
    else:
        assert ends[0].exc_info
        assert ends[0].getMessage() == "pr_qa_run_bg: QA crashed for pr-001"


# QA S65: the sign-off `qa` hop tick applies the hop (status qa, return
# awaiting qa) before 3e9f6b19's provider check refuses the launch.  The run
# sign-off judged still has its qa-<pr> window open, so every tick after the
# fix took that window for the re-run starting ("running: qa") and QA was
# never launched again.
def _reqa_tick(tmp_path, data, *, window=True, status_path=None):
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_cli
    with patch.object(pr_cli, "state_root", return_value=tmp_path), \
            patch.object(pr_cli.store, "load", return_value=data), \
            patch.object(pr_cli.store, "locked_update",
                         side_effect=lambda root, fn, **kw: fn(data)), \
            patch.object(pr_cli, "_get_pm_session", return_value="pm-test"), \
            patch.object(pr_cli, "trigger_tui_refresh"), \
            patch.object(pr_cli, "_check_signoff_verdict",
                         return_value="SIGNOFF_REQA"), \
            patch.object(pr_cli, "_retire_signoff_window"), \
            patch.object(pr_cli, "_qa_status_for",
                         return_value=("PASS", status_path)), \
            patch.object(pr_cli.tmux_mod, "find_window_by_name",
                         return_value={"id": "@9"} if window else None), \
            patch.object(pr_cli.subprocess, "Popen") as popen:
        result = CliRunner().invoke(pr_cli.pr_auto_sequence, ["pr-001"])
    return result, popen


def _judged_run(tmp_path):
    """A PASS qa_status.json written before sign-off routed back."""
    path = tmp_path / "qa_status.json"
    path.write_text("{}")
    os.utime(path, (1, 1))
    return path


def test_reqa_hop_refused_then_fixed_launches_over_judged_window(
        pm_home_dir, tmp_path):
    pr = {"id": "pr-001", "title": "T", "status": "sign_off",
          "branch": "pm/pr-001",
          "session_models": {"qa_planning": "provider:missing-route"}}
    data = {"project": {}, "prs": [pr]}
    old = _judged_run(tmp_path)

    result, popen = _reqa_tick(tmp_path, data, status_path=old)
    assert isinstance(result.exception, ProviderNotFoundError)
    assert "sign_off: re-qa" not in result.output
    popen.assert_not_called()
    assert pr["status"] == "qa"
    assert pr["signoff_return"]["awaiting"] == "qa"
    # Refused before claiming: the tick after the fix is not held off.
    assert "launch_claim" not in pr["signoff_return"]

    for _ in range(2):  # still broken: same error, nothing claimed
        result, popen = _reqa_tick(tmp_path, data, status_path=old)
        assert isinstance(result.exception, ProviderNotFoundError)
        popen.assert_not_called()
        assert "launch_claim" not in pr["signoff_return"]

    del pr["session_models"]
    result, popen = _reqa_tick(tmp_path, data, status_path=old)
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "running: qa (launched)"
    assert popen.call_args.args[0][-2:] == ["qa-run-bg", "pr-001"]
    assert pr["signoff_return"]["launch_claim"]["hop"] == "qa"

    # The driver has not cleared ``awaiting`` yet: a second tick leaves it.
    result, popen = _reqa_tick(tmp_path, data, status_path=old)
    assert result.output.strip() == "running: qa"
    popen.assert_not_called()

    # Once the driver starts (clears ``awaiting``) its window is the run's.
    pr["signoff_return"]["awaiting"] = None
    result, popen = _reqa_tick(tmp_path, data, status_path=old)
    assert result.output.strip() == "running: qa"
    popen.assert_not_called()


def test_reqa_hop_claims_its_launch(pm_home_dir, tmp_path):
    """The hop tick's own driver is not doubled by the next tick."""
    pr = {"id": "pr-001", "title": "T", "status": "sign_off",
          "branch": "pm/pr-001"}
    data = {"project": {}, "prs": [pr]}
    old = _judged_run(tmp_path)
    result, popen = _reqa_tick(tmp_path, data, status_path=old)
    assert result.exit_code == 0, result.output
    assert "sign_off: re-qa" in result.output
    popen.assert_called_once()
    result, popen = _reqa_tick(tmp_path, data, status_path=old, window=False)
    assert result.output.strip() == "running: qa"
    popen.assert_not_called()


# QA S66 (RQ46 open points a, b; provider broken mid-run; TUI t replay).
# (a) The review-PASS tick moved the PR to qa before the provider check, so
# after a refused launch the next qa tick read the earlier run's
# qa_status.json (a stale NEEDS_WORK bounced the PR back to review, every
# other tick) or, with that status ignored, an earlier qa-<pr> window
# ("running: qa" with no launch ever retried).  (b) With qa-verify-pass off the
# check still resolved the verifier, which such a run never launches.
def _review_pass_tick(pr, data):
    from click.testing import CliRunner
    from pm_core.cli import pr as pr_cli
    with patch.object(pr_cli, "state_root", return_value=Path("/nonexistent")), \
            patch.object(pr_cli.store, "load", return_value=data), \
            patch.object(pr_cli, "_get_pm_session", return_value="pm-test"), \
            patch.object(pr_cli, "_auto_seq_transcript_dir",
                         return_value=Path(tempfile.mkdtemp())), \
            patch.object(pr_cli, "_check_review_verdict",
                         return_value=("PASS", 2)), \
            patch.object(pr_cli, "trigger_tui_refresh"), \
            patch.object(pr_cli.store, "locked_update",
                         side_effect=lambda root, fn, **k: fn(data)), \
            patch.object(pr_cli.subprocess, "Popen") as popen:
        result = CliRunner().invoke(pr_cli.pr_auto_sequence, [pr["id"]])
    return result, popen


def test_review_pass_tick_refuses_before_moving_the_pr_to_qa(pm_home_dir):
    pr = {"id": "pr-001", "status": "in_review", "branch": "b",
          "session_models": {"qa_planning": "provider:missing-route"}}
    data = {"project": {}, "prs": [pr]}
    result, popen = _review_pass_tick(pr, data)
    assert isinstance(result.exception, ProviderNotFoundError)
    popen.assert_not_called()
    # Still in review: the next tick retries the launch (same error) and
    # never acts on an earlier QA run's status or window.
    assert pr["status"] == "in_review"
    del pr["session_models"]
    result, popen = _review_pass_tick(pr, data)
    assert result.exit_code == 0 and result.output.strip() == "advanced: qa"
    assert pr["status"] == "qa"
    assert popen.call_args.args[0][-2:] == ["qa-run-bg", "pr-001"]


@pytest.mark.parametrize("verify", [True, False])
def test_verifier_provider_is_checked_only_when_verification_runs(
        pm_home_dir, verify):
    from pm_core import qa_loop
    pr = {"id": "pr-001",
          "session_models": {"qa_verification": "provider:missing-route"}}
    with patch.object(qa_loop, "_is_verification_enabled", return_value=verify):
        if verify:
            with pytest.raises(ProviderNotFoundError, match="missing-route"):
                qa_loop.check_ungated_qa_providers(pr, {})
        else:
            qa_loop.check_ungated_qa_providers(pr, {})
        pr["session_models"] = {"qa_finalize": "provider:missing-route"}
        with pytest.raises(ProviderNotFoundError, match="missing-route"):
            qa_loop.check_ungated_qa_providers(pr, {})


# A provider broken mid-run (after the launch check): each verification
# ended "Verification thread crashed" with a traceback, flagged the worker
# ("verification thread crashed") and, after the retries, marked it
# NEEDS_WORK; a broken finalizer gave "Failed to run QA finalize pane" with a
# traceback after the overall PASS was published (finalize=None), which the
# next tick took on to sign-off.  Now the run stops with the setup error
# (one "QA stopped" warning, see _log_thread_end) and records no verdict.
def test_verifier_setup_error_stops_the_run_without_flagging_the_worker(
        pm_home_dir, tmp_path):
    import itertools
    from pm_core import qa_loop
    sc = qa_loop.QAScenario(index=1, title="S1", focus="t")
    sc.window_name, sc.pane_id, sc.session_id = "qa-pr-001-s1", "%1", "sid-1"
    state = qa_loop.QALoopState(pr_id="pr-001")
    state.qa_workdir = str(tmp_path)
    state.scenarios = [sc]
    event = {"event_type": "idle_prompt", "timestamp": time.time() + 1000,
             "session_id": "sid-1"}
    spins = itertools.count()

    def sleep(_):
        assert next(spins) < 2000, "poll loop never stopped"

    with patch.object(qa_loop, "_verify_single_scenario",
                      side_effect=lambda *a, **k: _launch_on_missing_provider(
                          session_type="qa_verification")), \
            patch.object(qa_loop, "_send_submitted") as follow_up, \
            patch.object(qa_loop.time, "sleep", side_effect=sleep), \
            patch.object(qa_loop.time, "monotonic",
                         side_effect=itertools.count(0, 100)), \
            patch("pm_core.hook_events.read_event", return_value=event), \
            patch.object(qa_loop, "extract_verdict_from_transcript",
                         return_value="PASS"), \
            patch("pm_core.tmux.capture_pane", return_value="PASS"), \
            patch("pm_core.tmux.pane_exists", return_value=True), \
            patch.object(qa_loop, "_is_verification_enabled", return_value=True):
        with pytest.raises(ProviderNotFoundError, match="missing-route"):
            qa_loop._poll_tmux_verdicts(state, {}, {}, "sess", str(tmp_path),
                                        tmp_path / "status.json",
                                        lambda *a: None)
    follow_up.assert_not_called()
    assert qa_loop.VERDICT_NEEDS_WORK not in state.scenario_verdicts.values()


def test_finalizer_setup_error_stops_the_run_before_the_overall(
        pm_home_dir, tmp_path):
    from pm_core import qa_loop
    state = qa_loop.QALoopState(pr_id="pr-001")
    state.scenarios = [qa_loop.QAScenario(index=1, title="A", focus="a")]
    state.scenario_verdicts = {1: qa_loop.VERDICT_PASS}
    pr = {"id": "pr-001", "branch": "b",
          "session_models": {"qa_finalize": "provider:missing-route"}}
    with patch.object(qa_loop, "_poll_tmux_verdicts"), \
            patch.object(qa_loop, "_write_status_file") as write_status, \
            patch.object(qa_loop, "_write_resume_file"), \
            patch.object(qa_loop, "_persist_scenario_verdicts"), \
            patch.object(qa_loop, "_run_qa_finalize_pane") as finalize, \
            pytest.raises(ProviderNotFoundError, match="missing-route"):
        qa_loop._execute_and_finalize(
            state, tmp_path, pr, {}, "pm-test", "qa-w", str(tmp_path),
            tmp_path / "status.json", None, use_containers=False,
            concurrency_cap=0, queued_scenarios=[], notify=lambda: None)
    finalize.assert_not_called()
    assert not [c for c in write_status.call_args_list
                if c.kwargs.get("overall")]
    # Broken between that check and the launch: still a stop, not a crash.
    pr["session_models"] = {}
    finalize.side_effect = lambda *a, **k: _launch_on_missing_provider(
        session_type="qa_finalize")
    with patch.object(qa_loop, "_poll_tmux_verdicts"), \
            patch.object(qa_loop, "_write_status_file"), \
            patch.object(qa_loop, "_write_resume_file"), \
            patch.object(qa_loop, "_persist_scenario_verdicts"), \
            patch.object(qa_loop, "_run_qa_finalize_pane", finalize), \
            pytest.raises(ProviderNotFoundError):
        qa_loop._execute_and_finalize(
            state, tmp_path, pr, {}, "pm-test", "qa-w", str(tmp_path),
            tmp_path / "status.json", None, use_containers=False,
            concurrency_cap=0, queued_scenarios=[], notify=lambda: None)


# TUI t replay of bad02547: "QA stopped: <problem>; <remedy>, then start QA
# again" was replaced on the command bar within a second by "QA finished for
# <pr>: ERROR", and the stopped run recorded an empty "QA ERROR:  (workdir:
# ...)" note, so the PR carried two QA notes after the rerun.
@pytest.mark.parametrize("error", ["provider", "other"])
def test_tui_keeps_a_setup_stop_on_screen_and_records_no_note(
        pm_home_dir, tmp_path, error):
    from unittest.mock import MagicMock
    from pm_core import qa_loop
    from pm_core.tui import qa_loop_ui
    state = qa_loop.QALoopState(pr_id="pr-001")
    side = ((lambda *a, **k: _launch_on_missing_provider(
        session_type="qa_planning")) if error == "provider"
        else RuntimeError("boom"))
    with patch.object(qa_loop, "run_qa_sync", side_effect=side):
        qa_loop.start_qa_background(state, Path("/nonexistent"),
                                    {"id": "pr-001"}).join(5)
    assert state.setup_stop is (error == "provider")
    app = MagicMock()
    app._root = tmp_path
    app._self_driving_qa = {}
    with patch.object(qa_loop_ui, "_record_qa_note", return_value=True) as note:
        assert qa_loop_ui._on_qa_complete(app, state)
    shown = [c.args[0] for c in app.log_message.call_args_list]
    if error == "provider":
        note.assert_not_called()
        assert shown[-1].startswith("QA \\[pr-001]: QA stopped: provider "
                                    "'missing-route' is not configured")
        assert shown[-1].endswith(", then start QA again")
    else:
        note.assert_called_once()
        assert shown[-1] == "QA finished for pr-001: ERROR"
