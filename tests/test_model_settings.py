"""Model / provider / effort configuration per PR and project.

Covers the effort order (PR > provider > project), which setting decided
each value, provider env overrides, pm_core.model_settings edits, the
``pm pr model`` and ``pm provider edit/show`` CLIs, the TUI model popup
(``o``) and the tree's ⇄ badge.
"""

import asyncio
import functools

import pytest
import yaml
from click.testing import CliRunner

from pm_core import model_settings, store
from pm_core.model_config import (
    resolve_model_and_provider, validate_model_config,
)
from pm_core.providers import ProviderConfig, launch_env

ROUTE = "rt"


@pytest.fixture
def pm_home_dir(tmp_path, monkeypatch):
    home = tmp_path / "pmhome"
    home.mkdir()
    for mod in ("pm_core.providers", "pm_core.router_route"):
        monkeypatch.setattr(f"{mod}.pm_home", lambda: home)
    for var in ("PM_PROVIDER", "PM_MODEL", "PM_EFFORT",
                "CLAUDE_CODE_EFFORT_LEVEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("pm_core.model_config.get_global_setting_value",
                        lambda name, default="": default)
    return home


def _providers(home, **providers):
    (home / "providers.yaml").write_text(
        yaml.safe_dump({"providers": providers}))


def _router(**extra):
    entry = {"type": "router", "api_base": "http://127.0.0.1:1",
             "model": "rt/big"}
    entry.update(extra)
    return entry


def _project(**model_config):
    return {"project": {"name": "t", "repo": "/r", "base_branch": "master",
                        "model_config": model_config},
            "prs": []}


# ---------------------------------------------------------------------------
# Effort order and sources
# ---------------------------------------------------------------------------

class TestEffortOrder:
    def test_provider_beats_project(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(effort="low")})
        data = _project(session_models={"impl": f"provider:{ROUTE}"},
                        session_effort={"impl": "high"})
        res = resolve_model_and_provider("impl", project_data=data)
        assert (res.provider, res.effort) == (ROUTE, "low")
        assert (res.source, res.effort_source) == (
            "project impl", f"provider {ROUTE}")

    def test_project_applies_when_provider_sets_none(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router()})
        data = _project(session_models={"impl": f"provider:{ROUTE}"},
                        session_effort={"impl": "high"})
        res = resolve_model_and_provider("impl", project_data=data)
        assert (res.effort, res.effort_source) == ("high", "project impl")

    def test_pr_beats_provider_role_beats_pr_wide(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(effort="low")})
        pr = {"id": "pr-1", "model": f"provider:{ROUTE}", "effort": "medium",
              "session_effort": {"review": "high"}}
        impl = resolve_model_and_provider("impl", pr_entry=pr,
                                          project_data=_project())
        signoff = resolve_model_and_provider("signoff", pr_entry=pr,
                                             project_data=_project())
        assert (impl.effort, impl.effort_source) == ("medium", "PR")
        # signoff falls back to the review role entry
        assert (signoff.effort, signoff.effort_source) == ("high", "PR review")
        assert signoff.source == "PR"

    def test_pm_effort_beats_everything(self, pm_home_dir, monkeypatch):
        monkeypatch.setenv("PM_EFFORT", "low")
        pr = {"id": "pr-1", "effort": "high"}
        res = resolve_model_and_provider("impl", pr_entry=pr,
                                         project_data=_project())
        assert (res.effort, res.effort_source) == ("low", "PM_EFFORT")

    def test_invalid_pr_effort_is_ignored_and_reported(self, pm_home_dir):
        data = _project(session_effort={"impl": "medium"})
        pr = {"id": "pr-1", "effort": "turbo",
              "session_effort": {"impl": "ultra", "bogus": "low"}}
        data["prs"] = [pr]
        res = resolve_model_and_provider("impl", pr_entry=pr,
                                         project_data=data)
        assert (res.effort, res.effort_source) == ("medium", "project impl")
        problems = "\n".join(validate_model_config(data))
        assert "prs[pr-1].effort: invalid effort 'turbo'" in problems
        assert "session_effort['impl']: invalid effort 'ultra'" in problems
        assert "unknown session type 'bogus'" in problems

    def test_pr_role_model_source(self, pm_home_dir):
        pr = {"id": "pr-1", "model": "opus",
              "session_models": {"qa": "sonnet"}}
        res = resolve_model_and_provider("qa_scenario", pr_entry=pr,
                                         project_data=_project())
        assert (res.model, res.source) == ("sonnet", "PR qa")


# ---------------------------------------------------------------------------
# Provider env overrides (no environment-specific defaults)
# ---------------------------------------------------------------------------

class TestProviderEnv:
    def test_null_env_drops_a_router_default(self):
        p = ProviderConfig(name=ROUTE, type="router", api_base="http://x:1",
                           model="rt/big",
                           env={"ANTHROPIC_SMALL_FAST_MODEL": None,
                                "EXTRA": "1"})
        env = p.env_vars()
        assert "ANTHROPIC_SMALL_FAST_MODEL" not in env
        assert env["EXTRA"] == "1"
        assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "rt/big"
        # Dropped, so the launch unsets an inherited value instead.
        assert "ANTHROPIC_SMALL_FAST_MODEL" in launch_env(
            p, env, "rt/big", {})[1]

    def test_unset_env_replaces_the_router_default(self):
        p = ProviderConfig(name=ROUTE, type="router", api_base="http://x:1",
                           model="rt/big", unset_env=[])
        assert p.unset_env_vars() == ()
        p.unset_env = ["ONLY_THIS"]
        assert p.unset_env_vars() == ("ONLY_THIS",)
        assert ProviderConfig(name="r", type="router").unset_env_vars() == (
            "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

    @pytest.mark.parametrize("own, pin, force", [
        ({}, "rt/big", "1"),
        ({"alias_models": {"CLAUDE_CODE_SUBAGENT_MODEL": "rt/small"}},
         "rt/small", "1"),
        # env is the newer alias_models and wins over it
        ({"alias_models": {"CLAUDE_CODE_SUBAGENT_MODEL": "rt/small"},
          "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "rt/tiny"}}, "rt/tiny", "1"),
        ({"env": {"CLAUDE_CODE_SUBAGENT_MODEL_FORCE": None}}, "rt/big", None),
        ({"env": {"CLAUDE_CODE_SUBAGENT_MODEL": None}}, None, None),
    ])
    def test_env_overrides_the_subagent_pin(self, own, pin, force):
        p = ProviderConfig(name=ROUTE, type="router", api_base="http://x:1",
                           model="rt/big", **own)
        assign, unset = launch_env(
            p, p.env_vars(), "rt/big",
            {"CLAUDE_CODE_SUBAGENT_MODEL": "inherited",
             "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"})
        assert assign.get("CLAUDE_CODE_SUBAGENT_MODEL") == pin
        assert assign.get("CLAUDE_CODE_SUBAGENT_MODEL_FORCE") == force
        # A dropped pin is removed, never inherited from the caller.
        for var, value in (("CLAUDE_CODE_SUBAGENT_MODEL", pin),
                           ("CLAUDE_CODE_SUBAGENT_MODEL_FORCE", force)):
            assert (var in unset) == (value is None)

    def test_env_applies_to_other_types(self):
        p = ProviderConfig(name="o", type="local", api_base="http://x:1",
                           env={"FOO": "bar"})
        assert p.env_vars()["FOO"] == "bar"

    @pytest.mark.parametrize("entry, problem", [
        ({"env": {"A": 1}}, "'env' must map"),
        ({"unset_env": "A"}, "'unset_env' must be a list"),
        ({"probe_models": [1]}, "'probe_models' must be a list"),
        ({"effort": "ultra"}, "unknown effort"),
        ({"classifier_model": 3}, "'classifier_model' must be a string"),
    ])
    def test_bad_new_fields_are_invalid_entries(self, entry, problem):
        from pm_core.providers import _entry_problem
        assert problem in _entry_problem({**_router(), **entry})


# ---------------------------------------------------------------------------
# model_settings edits and rows
# ---------------------------------------------------------------------------

class TestEdits:
    def test_set_and_unset_pr_values(self):
        pr = {"id": "pr-1"}
        model_settings.set_pr_value(pr, "model", "opus")
        model_settings.set_pr_value(pr, "model", "sonnet", ["signoff"])
        model_settings.set_pr_value(pr, "effort", "high", ["qa", "review"])
        assert pr == {"id": "pr-1", "model": "opus",
                      "session_models": {"signoff": "sonnet"},
                      "session_effort": {"qa": "high", "review": "high"}}
        model_settings.set_pr_value(pr, "model", None)
        assert "model" not in pr and pr["session_models"]
        model_settings.set_pr_value(pr, "model", None, ["signoff"])
        assert "session_models" not in pr
        model_settings.clear_pr(pr, "effort")
        assert pr == {"id": "pr-1"}

    def test_bad_role_and_effort_are_refused(self):
        with pytest.raises(ValueError, match="unknown session type"):
            model_settings.set_pr_value({}, "model", "opus", ["watcher"])
        with pytest.raises(ValueError, match="invalid effort"):
            model_settings.set_pr_value({}, "effort", "ultra")

    def test_set_project_value_and_cleanup(self):
        data = _project()
        model_settings.set_project_value(data, "model", "qa_scenario",
                                         "provider:rt")
        model_settings.set_project_value(data, "effort", "qa_scenario", "high")
        assert data["project"]["model_config"] == {
            "session_models": {"qa_scenario": "provider:rt"},
            "session_effort": {"qa_scenario": "high"}}
        model_settings.set_project_value(data, "model", "qa_scenario", None)
        model_settings.set_project_value(data, "effort", "qa_scenario", None)
        assert "model_config" not in data["project"]

    def test_check_model_value(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router()})
        assert model_settings.check_model_value("opus") is None
        assert model_settings.check_model_value(f"provider:{ROUTE}") is None
        assert "not configured" in model_settings.check_model_value(
            "provider:nope")

    def test_role_rows_name_command_and_problem(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(launcher="/opt/launch")})
        data = _project()
        pr = {"id": "pr-1", "model": f"provider:{ROUTE}",
              "session_models": {"merge": "provider:gone"}}
        host = {r.role: r for r in model_settings.role_rows(
            data, pr, container_mode=False)}
        assert host["impl"].command == "/opt/launch"
        assert host["impl"].model == "rt/big"
        assert host["impl"].route == ROUTE
        assert "not configured" in host["merge"].problem
        assert "watcher" not in host  # a project session
        cont = {r.role: r for r in model_settings.role_rows(
            data, pr, container_mode=True)}
        assert cont["impl"].command == "claude (container route bridge)"
        assert cont["qa_planning"].command == "/opt/launch"  # host role

    def test_role_rows_show_the_s0_legacy_model(self, pm_home_dir):
        """A plain-model project ``qa_scenario`` from before
        ``qa_interactive`` still runs s0; the rows say so, as the launch
        does (they used to show the CLI default)."""
        from pm_core import qa_loop
        data = _project(session_models={"qa_scenario": "sonnet"},
                        session_effort={"qa_scenario": "low"})
        pr = {"id": "pr-1"}
        rows = {r.role: r for r in model_settings.role_rows(
            data, pr, container_mode=False)}
        s0 = rows["qa_interactive"]
        assert (s0.value, s0.effort) == ("sonnet", "low")
        assert s0.source == "project qa_scenario (s0 legacy)"
        assert s0.effort_source == "project qa_scenario"
        launch = qa_loop._resolve_interactive_model(pr, data)
        assert (launch.model, launch.effort) == ("sonnet", "low")
        # A route never follows: s0 stays on the CLI default.
        _providers(pm_home_dir, **{ROUTE: _router()})
        routed = _project(session_models={"qa_scenario": f"provider:{ROUTE}"})
        s0 = {r.role: r for r in model_settings.role_rows(
            routed, pr, container_mode=False)}["qa_interactive"]
        assert (s0.value, s0.source) == ("(default)", "(CLI default)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@pytest.fixture
def project_root(tmp_path, monkeypatch, pm_home_dir):
    root = tmp_path / "pm"
    root.mkdir()
    data = _project()
    data["prs"] = [{"id": "pr-001", "title": "T", "status": "pending",
                    "branch": "b"}]
    store.save(data, root)
    from pm_core.cli import pr as pr_mod
    monkeypatch.setattr(pr_mod, "state_root", lambda: root)
    monkeypatch.setattr("pm_core.container.is_container_mode_enabled",
                        lambda: False)
    return root


def _cli(*args):
    from pm_core.cli import cli
    return CliRunner().invoke(cli, list(args))


class TestPrModelCLI:
    def test_set_show_unset(self, project_root, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(effort="low")})
        r = _cli("pr", "model", "set", "pr-001", f"provider:{ROUTE}")
        assert r.exit_code == 0, r.output
        r = _cli("pr", "model", "set", "pr-001", "opus", "--role", "signoff",
                 "--effort", "high")
        assert r.exit_code == 0, r.output
        pr = store.get_pr(store.load(project_root), "pr-001")
        assert pr["model"] == f"provider:{ROUTE}"
        assert pr["session_models"] == {"signoff": "opus"}
        assert pr["session_effort"] == {"signoff": "high"}
        r = _cli("pr", "model", "show", "pr-001")
        assert r.exit_code == 0, r.output
        impl = next(l for l in r.output.splitlines() if l.strip().startswith("impl "))
        assert f"provider:{ROUTE} [rt/big]" in impl
        assert f"model: PR; effort: provider {ROUTE}" in impl
        signoff = next(l for l in r.output.splitlines()
                       if l.strip().startswith("signoff "))
        assert "opus" in signoff and "effort: PR signoff" in signoff
        r = _cli("pr", "model", "unset", "pr-001", "--all")
        assert r.exit_code == 0, r.output
        pr = store.get_pr(store.load(project_root), "pr-001")
        assert not model_settings.has_pr_override(pr)

    def test_unknown_provider_is_refused_unwritten(self, project_root):
        r = _cli("pr", "model", "set", "pr-001", "provider:nope")
        assert r.exit_code == 1 and "not configured" in r.output
        pr = store.get_pr(store.load(project_root), "pr-001")
        assert "model" not in pr

    def test_set_needs_something(self, project_root):
        r = _cli("pr", "model", "set", "pr-001")
        assert r.exit_code == 1 and "VALUE and/or --effort" in r.output


class TestProviderEditShow:
    def test_edit_keeps_other_fields(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(launcher="/opt/l",
                                                  remedy="start it")})
        r = _cli("provider", "edit", ROUTE, "--effort", "high",
                 "--env", "FOO=bar", "--drop-env", "ANTHROPIC_SMALL_FAST_MODEL",
                 "--clear", "launcher")
        assert r.exit_code == 0, r.output
        entry = yaml.safe_load((pm_home_dir / "providers.yaml").read_text())[
            "providers"][ROUTE]
        assert entry["effort"] == "high" and entry["remedy"] == "start it"
        assert entry["env"] == {"FOO": "bar",
                                "ANTHROPIC_SMALL_FAST_MODEL": None}
        assert "launcher" not in entry

    def test_edit_refuses_an_invalid_result(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router()})
        before = (pm_home_dir / "providers.yaml").read_text()
        r = _cli("provider", "edit", ROUTE, "--clear", "model")
        assert r.exit_code == 1 and "--model is required" in r.output
        assert (pm_home_dir / "providers.yaml").read_text() == before

    def test_show_redacts_keys(self, pm_home_dir):
        _providers(pm_home_dir, local={"type": "local",
                                       "api_base": "http://x:1",
                                       "api_key": "sk-SECRET"})
        r = _cli("provider", "show", "local")
        assert r.exit_code == 0, r.output
        assert "SECRET" not in r.output
        assert "api_key: set" in r.output
        assert "ANTHROPIC_API_KEY=<redacted>" in r.output

    def test_show_redacts_auth_bearing_env(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(env={
            "ANTHROPIC_CUSTOM_HEADERS": "Authorization: Bearer HDRSECRET",
            "MY_PASSWORD": "PWSECRET", "PLAIN": "shown"})})
        r = _cli("provider", "show", ROUTE)
        assert r.exit_code == 0, r.output
        assert "SECRET" not in r.output
        assert "ANTHROPIC_CUSTOM_HEADERS=<redacted>" in r.output
        assert "PLAIN=shown" in r.output

    def test_show_router_status_and_env(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(classifier_model="rt/s")})
        r = _cli("provider", "show", ROUTE)
        assert r.exit_code == 0, r.output
        assert "CLAUDE_CODE_AUTO_MODE_MODEL=rt/s" in r.output
        assert "status: route 'rt' unavailable" in r.output


# ---------------------------------------------------------------------------
# TUI
# ---------------------------------------------------------------------------

def async_test(coro):
    @functools.wraps(coro)
    def wrapper(*args, **kwargs):
        asyncio.run(coro(*args, **kwargs))
    return wrapper


def _screen_app(root, pr_id):
    from textual.app import App
    from pm_core.tui.model_screen import ModelSettingsScreen

    class _App(App):
        def on_mount(self):
            self.screen_obj = ModelSettingsScreen(root, pr_id)
            self.push_screen(self.screen_obj)
    return _App()


@async_test
async def test_tui_applies_a_provider_to_every_role(project_root, pm_home_dir):
    _providers(pm_home_dir, **{ROUTE: _router()})
    app = _screen_app(project_root, "pr-001")
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        # Row 0 = all roles; picker: (clear), provider:claude, provider:rt
        await pilot.press("enter", "down", "down", "enter")
        await pilot.pause()
        pr = store.get_pr(store.load(project_root), "pr-001")
        assert pr["model"] == f"provider:{ROUTE}"
        assert "->" in str(app.screen_obj.query_one("#model-status").render())
        # e on the impl row (row 1) cycles its own effort: none -> low
        await pilot.press("down", "e")
        await pilot.pause()
        pr = store.get_pr(store.load(project_root), "pr-001")
        assert pr["session_effort"] == {"impl": "low"}


@async_test
async def test_tui_project_view_sets_project_role(project_root, pm_home_dir):
    _providers(pm_home_dir, **{ROUTE: _router()})
    app = _screen_app(project_root, "pr-001")
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        await pilot.press("p")  # project view: row 0 = impl
        await pilot.press("enter", "down", "down", "enter")
        await pilot.pause()
        data = store.load(project_root)
        assert data["project"]["model_config"]["session_models"] == {
            "impl": f"provider:{ROUTE}"}
        body = str(app.screen_obj.query_one("#model-body").render())
        assert "Providers" in body and f"{ROUTE}  type=router" in body


@async_test
async def test_tui_refuses_a_busy_project_file(project_root, pm_home_dir,
                                              monkeypatch):
    def busy(*a, **k):
        raise store.StoreLockTimeout("held by pm edit")
    monkeypatch.setattr(store, "locked_update", busy)
    app = _screen_app(project_root, "pr-001")
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        status = str(app.screen_obj.query_one("#model-status").render())
        assert "Not saved: held by pm edit" in status


def test_effort_cycle():
    from pm_core.tui.model_screen import next_effort
    assert [next_effort(x) for x in
            (None, "low", "medium", "high", "xhigh", "max", "bad")] == [
        "low", "medium", "high", "xhigh", "max", None, "low"]


@async_test
async def test_tree_badge_marks_pr_with_its_own_settings():
    from tests.test_tech_tree_widgets import _TreeApp, _pr
    from pm_core.tui.tech_tree import PRNode
    app = _TreeApp([_pr("pr-a"), _pr("pr-b", session_effort={"qa": "high"})])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        rows = {n.pr_id: n.render().plain.splitlines()[1]
                for n in app.query(PRNode)}
        assert "⇄" not in rows["pr-a"]
        assert rows["pr-b"].rstrip().endswith("⇄ │")


@async_test
async def test_tree_badge_follows_a_settings_change():
    # A popup save changes only the PR's model fields; the tree must rebuild
    # the node so ⇄ appears (and goes once the settings are cleared).
    from tests.test_tech_tree_widgets import _TreeApp, _pr
    from pm_core.tui.tech_tree import PRNode, TechTree

    def row(app, pr_id):
        return {n.pr_id: n.render().plain.splitlines()[1]
                for n in app.query(PRNode)}[pr_id]

    app = _TreeApp([_pr("pr-a"), _pr("pr-b")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert "⇄" not in row(app, "pr-a")
        tree = app.query_one("#tech-tree", TechTree)
        tree.update_prs([_pr("pr-a", model="provider:x"), _pr("pr-b")])
        await pilot.pause()
        assert row(app, "pr-a").rstrip()[:-1].rstrip().endswith("⇄")
        assert "⇄" not in row(app, "pr-b")
        tree.update_prs([_pr("pr-a"), _pr("pr-b")])
        await pilot.pause()
        assert "⇄" not in row(app, "pr-a")


@async_test
async def test_tui_popup_is_wide_enough_for_every_row(project_root,
                                                     pm_home_dir):
    # Rows run past 140 columns (the "decided by" column); on a wide
    # terminal the popup must show them whole, not clip that column.
    _providers(pm_home_dir, **{ROUTE: _router(
        launcher="/opt/shared-team-tools/bin/route-launcher-wrapper-v2")})
    app = _screen_app(project_root, "pr-001")
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.press("enter", "down", "down", "enter")  # PR-wide route
        await pilot.pause()
        body = app.screen_obj.query_one("#model-body")
        longest = max(len(line) for line in body.render().plain.splitlines())
        assert longest > 136  # wider than the old 140-column box held
        box = app.screen_obj.query_one("#model-container")
        assert box.content_region.width >= longest


@async_test
async def test_tui_project_view_shows_ok_route_status(project_root,
                                                      pm_home_dir,
                                                      monkeypatch):
    # "[OK]" reads as a markup tag to textual; the popup must still show it.
    from pm_core import router_route
    _providers(pm_home_dir, **{ROUTE: _router()})
    monkeypatch.setattr(router_route, "check_route",
                        lambda res: router_route.RouteStatus(
                            ok=True, route=res.provider))
    app = _screen_app(project_root, "pr-001")
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        body = app.screen_obj.query_one("#model-body").render().plain
        line = next(x for x in body.splitlines()
                    if x.strip().startswith(f"{ROUTE}  type=router"))
        assert line.rstrip().endswith("[OK]")


@async_test
async def test_tui_long_refusal_wraps_inside_the_popup(project_root,
                                                      pm_home_dir,
                                                      monkeypatch):
    long = "held by pm edit; " + "the remedy names a command. " * 12
    def busy(*a, **k):
        raise store.StoreLockTimeout(long)
    monkeypatch.setattr(store, "locked_update", busy)
    app = _screen_app(project_root, "pr-001")
    async with app.run_test(size=(200, 50)) as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        status = app.screen_obj.query_one("#model-status")
        box = app.screen_obj.query_one("#model-container")
        assert status.region.width <= box.content_region.width
        assert status.region.height > 1
        assert status.render().plain.rstrip().endswith("command.")


def test_badge_ignores_blank_entries():
    # Hand-edited blank entries select nothing (launches and the rows treat
    # them as absent), so they don't earn the ⇄ badge either.
    assert not model_settings.has_pr_override(
        {"id": "p", "session_models": {"signoff": None},
         "session_effort": {"impl": "  "}, "model": ""})
    assert model_settings.has_pr_override(
        {"id": "p", "session_models": {"signoff": None, "impl": "opus"}})
    assert model_settings.has_pr_override({"id": "p", "effort": "high"})
    assert model_settings.has_pr_override({"id": "p", "session_models": "x"})


# ---------------------------------------------------------------------------
# Effort vocabulary and route capability metadata
# ---------------------------------------------------------------------------

class TestEffortCapability:
    def test_native_levels_are_accepted(self, pm_home_dir):
        from pm_core.model_config import EFFORT_LEVELS
        assert EFFORT_LEVELS == ("low", "medium", "high", "xhigh", "max")
        data = _project(session_effort={"impl": "xhigh", "review": "max"})
        assert resolve_model_and_provider("impl", project_data=data).effort \
            == "xhigh"
        assert resolve_model_and_provider("review", project_data=data).effort \
            == "max"

    def test_plain_model_status_is_cli(self, pm_home_dir):
        data = _project(session_effort={"impl": "xhigh"})
        res = resolve_model_and_provider("impl", pr_model="opus",
                                         project_data=data)
        assert (res.effort, res.effort_status) == ("xhigh", "cli")

    def test_route_without_metadata_is_unverified(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router()})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert res.effort_status == "unverified"
        assert any("declares no supported_efforts" in n
                   for n in res.effort_notes)

    def test_route_supported_level_is_ok(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["max", "high", "low"])})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert res.effort_status == "ok"
        assert res.supported_efforts == ("low", "high", "max")

    def test_route_unsupported_level_still_launches_but_is_marked(
            self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["max", "high", "low"])})
        data = _project(session_effort={"impl": "xhigh"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert (res.effort, res.effort_status) == ("xhigh", "unsupported")
        assert any("is not in the selected route's supported_efforts" in n
                   for n in res.effort_notes)

    def test_non_claude_levels_are_dropped_from_the_intersection(
            self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["none", "high"])})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert res.supported_efforts == ("high",)

    def test_haiku_is_not_applicable(self, pm_home_dir):
        data = _project(session_effort={"impl": "xhigh"})
        res = resolve_model_and_provider("impl", pr_model="haiku",
                                         project_data=data)
        assert (res.effort, res.effort_status, res.effort_requested) == \
            (None, "not_applicable", "xhigh")

    def test_stale_metadata_is_noted(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["high"],
            supported_efforts_checked_at="2020-01-01")})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert res.effort_status == "ok"
        assert any("days old" in n for n in res.effort_notes)

    def test_stale_date_without_a_list_is_not_noted(self, pm_home_dir):
        """A date alone is not metadata: nothing is stale about a list the
        route does not declare, and the note would read as a finding."""
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts_checked_at="2020-01-01")})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert res.effort_status == "unverified"
        assert not any("days old" in n for n in res.effort_notes)

    def test_a_non_list_declaration_is_not_read(self):
        """A hand-built config whose supported_efforts is a string must not
        be substring-matched ("high" is in "xhigh")."""
        from pm_core.model_config import accepted_efforts_of
        cfg = ProviderConfig(name="p", type="claude",
                             supported_efforts="xhigh")
        assert accepted_efforts_of(cfg) is None

    def test_pm_setting_wins_over_ambient_env(self, pm_home_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "xhigh")
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider("impl", project_data=data)
        assert (res.effort, res.effort_source) == ("high", "project impl")
        assert any("pm unsets it" in n for n in res.effort_notes)

    def test_ambient_env_is_the_source_with_no_pm_setting(
            self, pm_home_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "xhigh")
        res = resolve_model_and_provider("impl")
        assert (res.effort, res.effort_source, res.effort_status) == \
            ("xhigh", "CLAUDE_CODE_EFFORT_LEVEL", "overridden")

    def test_ambient_auto_is_absent(self, pm_home_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "auto")
        res = resolve_model_and_provider("impl")
        assert (res.effort, res.effort_status) == (None, "none")

    def test_invalid_pm_effort_is_ignored_and_noted(self, pm_home_dir,
                                                    monkeypatch):
        monkeypatch.setenv("PM_EFFORT", "turbo")
        res = resolve_model_and_provider("impl")
        assert res.effort is None
        assert any("invalid PM_EFFORT" in n for n in res.effort_notes)

    def test_effort_env_classification(self):
        """One classifier decides what an assignment does, so the launch
        warning, the notes and `pm provider show` cannot disagree."""
        from pm_core.model_config import classify_effort_env
        assert classify_effort_env("xhigh") == ("level", "xhigh")
        assert classify_effort_env("XHIGH") == ("level", "xhigh")
        for value in ("auto", "unset", "", "  ", "AUTO"):
            assert classify_effort_env(value) == ("no_override", None)
        assert classify_effort_env("turbo") == ("unknown", None)

    def test_validate_warns_on_unsupported_route_level(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low"])})
        data = _project(session_models={"impl": f"provider:{ROUTE}"},
                        session_effort={"impl": "max"})
        problems = "\n".join(validate_model_config(data))
        assert "supported_efforts" in problems and "max" in problems

    def test_validate_warns_on_unsupported_pr_wide_effort(self, pm_home_dir):
        """The PR-wide ``effort`` decides every PR role too, so it is
        checked against each role's route -- once, not once per role."""
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low"])})
        data = _project()
        data["prs"] = [{"id": "pr-1", "effort": "max",
                        "session_models": {"impl": f"provider:{ROUTE}"}}]
        problems = validate_model_config(data)
        matching = [p for p in problems if "supported_efforts" in p]
        assert len(matching) == 1, matching
        assert matching[0].startswith("prs[pr-1].effort: ")

    def test_validate_does_not_blame_the_pr_wide_effort_for_a_role_override(
            self, pm_home_dir):
        """A role's own ``session_effort`` entry decides its level, so its
        unsupported level is reported under the role, not as the PR-wide
        effort (which is supported)."""
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low"])})
        data = _project()
        data["prs"] = [{"id": "pr-1", "effort": "low",
                        "session_models": {"impl": f"provider:{ROUTE}"},
                        "session_effort": {"impl": "max"}}]
        problems = validate_model_config(data)
        assert not any(p.startswith("prs[pr-1].effort:") for p in problems), \
            problems
        matching = [p for p in problems if "supported_efforts" in p]
        assert len(matching) == 1, matching
        assert matching[0].startswith("prs[pr-1] impl: ")

    def test_validate_accepts_a_supported_pr_wide_effort(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["max", "high"])})
        data = _project()
        data["prs"] = [{"id": "pr-1", "effort": "max",
                        "session_models": {"impl": f"provider:{ROUTE}"}}]
        assert validate_model_config(data) == []

    def test_empty_supported_efforts_is_unsupported_not_unverified(
            self, pm_home_dir):
        """[] declares "accepts none", distinct from "declares nothing"."""
        _providers(pm_home_dir, **{ROUTE: _router(supported_efforts=[])})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert (res.effort_status, res.supported_efforts) == ("unsupported",
                                                              ())

    def test_provider_env_assignment_overrides_pm_effort_visibly(
            self, pm_home_dir):
        """The launcher keeps a provider's own CLAUDE_CODE_EFFORT_LEVEL, so
        the display must not report pm's --effort as what runs."""
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low", "high", "xhigh"],
            env={"CLAUDE_CODE_EFFORT_LEVEL": "xhigh"})})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert (res.effort, res.effort_status) == ("high", "overridden")
        assert any("sets CLAUDE_CODE_EFFORT_LEVEL=xhigh" in n
                   for n in res.effort_notes)

    def test_provider_env_auto_is_no_override_not_an_unknown_level(
            self, pm_home_dir):
        """"auto" is a valid Claude value meaning "no override": the note
        must not call it an unknown level."""
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "auto"})})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert (res.effort, res.effort_status) == ("high", "unverified")
        assert any("(no override); --effort high applies" in n
                   for n in res.effort_notes)
        assert not any("not a Claude effort level" in n
                       for n in res.effort_notes)

    def test_provider_env_assignment_outside_the_route_list_is_named(
            self, pm_home_dir):
        """The level the provider's env forces is checked against the
        route's declared list too, not reported as if it were supported.
        """
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low"],
            env={"CLAUDE_CODE_EFFORT_LEVEL": "max"})})
        data = _project(session_effort={"impl": "low"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert res.effort_status == "overridden"
        assert any("does not declare 'max'" in n for n in res.effort_notes)

    def test_provider_env_assignment_with_no_pm_effort_is_noted(
            self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "max"})})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=_project())
        assert (res.effort, res.effort_status) == (None, "overridden")
        assert res.effort_env_level == "max"
        assert any("sets CLAUDE_CODE_EFFORT_LEVEL=max" in n
                   for n in res.effort_notes)
        assert any("for this provider's sessions" in n
                   for n in res.effort_notes)

    def test_provider_env_assignment_with_no_pm_effort_is_displayed(
            self, pm_home_dir):
        """The session runs the provider's level, so the effort column must
        not say "(default)" and the source must name the provider."""
        from pm_core.router_route import describe
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "max"})})
        data = _project(session_models={"impl": f"provider:{ROUTE}"})
        rows = model_settings.role_rows(data, None)
        impl = next(r for r in rows if r.role == "impl")
        assert model_settings.effort_cell(impl) == "max *"
        assert impl.effort_source == f"provider {ROUTE} env"
        lines = model_settings.format_rows([impl])
        assert any("effort: provider rt env" in line for line in lines)
        res = resolve_model_and_provider("impl", project_data=data)
        assert "effort=max (overridden)" in describe(res)

    def test_provider_env_assignment_matching_pm_level_is_not_a_conflict(
            self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "high"})})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert res.effort_status != "overridden"
        assert not any("CLAUDE_CODE_EFFORT_LEVEL" in n
                       for n in res.effort_notes)

    def test_provider_env_assignment_does_not_claim_pm_unsets_the_ambient(
            self, pm_home_dir, monkeypatch):
        """Both an ambient variable and a provider assignment: the launcher
        keeps the provider's value, so the note must not say pm unsets the
        ambient one (that would name a level the session does not run)."""
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "xhigh")
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "max"})})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert (res.effort, res.effort_status) == ("high", "overridden")
        assert not any("pm unsets it" in n for n in res.effort_notes)
        assert any("sets CLAUDE_CODE_EFFORT_LEVEL=max" in n
                   for n in res.effort_notes)

    def test_provider_env_no_override_assignment_is_still_an_assignment(
            self, pm_home_dir, monkeypatch):
        """``auto`` is an assignment too: the launcher exports it (so the
        ambient value is replaced, not removed), and the note must say that
        rather than claim pm unsets the ambient variable."""
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "xhigh")
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "auto"})})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        # The route declares no supported_efforts: unverified, not overridden
        # -- "auto" changes nothing about which level runs.
        assert (res.effort, res.effort_status) == ("high", "unverified")
        assert not any("pm unsets it" in n for n in res.effort_notes)
        assert any("(no override); --effort high applies" in n
                   for n in res.effort_notes)

    def test_provider_env_blank_assignment_is_no_override(
            self, pm_home_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "xhigh")
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": ""})})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert not any("pm unsets it" in n for n in res.effort_notes)
        assert any("(no override); --effort high applies" in n
                   for n in res.effort_notes)
        assert not any("not a Claude effort level" in n
                       for n in res.effort_notes)

    def test_haiku_with_ambient_only_never_claims_passing_the_level(
            self, pm_home_dir, monkeypatch):
        """Ambient xhigh is the only selection and Haiku suppresses it, so
        "pm passes it as --effort" would contradict the suppression note."""
        monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "xhigh")
        res = resolve_model_and_provider("impl", pr_model="haiku",
                                         project_data=_project())
        assert (res.effort, res.effort_status, res.effort_requested) == \
            (None, "not_applicable", "xhigh")
        assert not any("pm passes it as --effort" in n
                       for n in res.effort_notes)
        assert any("pm passes no --effort for this model" in n
                   for n in res.effort_notes)

    def test_default_provider_env_assignment_is_reported(self, pm_home_dir):
        """With no provider selected the launch still resolves
        providers.yaml's ``default:`` entry, so that entry's env block
        decides the session's level; "(default)" would name a level the
        session does not run."""
        (pm_home_dir / "providers.yaml").write_text(yaml.safe_dump({
            "default": "home",
            "providers": {"home": {
                "type": "claude",
                "env": {"CLAUDE_CODE_EFFORT_LEVEL": "max"}}}}))
        res = resolve_model_and_provider("impl", project_data=_project())
        assert (res.effort, res.effort_status, res.effort_env_level) == \
            (None, "overridden", "max")
        assert res.effort_source == "provider home env"
        assert any("provider 'home' sets CLAUDE_CODE_EFFORT_LEVEL=max" in n
                   for n in res.effort_notes)

    def test_default_provider_env_assignment_overrides_pm_effort_visibly(
            self, pm_home_dir):
        """The same entry overrides pm's own ``--effort`` too, so the note
        must say so instead of claiming pm unsets the variable."""
        (pm_home_dir / "providers.yaml").write_text(yaml.safe_dump({
            "default": "home",
            "providers": {"home": {
                "type": "claude",
                "env": {"CLAUDE_CODE_EFFORT_LEVEL": "max"}}}}))
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider("impl", project_data=data)
        assert (res.effort, res.effort_status) == ("high", "overridden")
        assert any("applies it instead of --effort high" in n
                   for n in res.effort_notes)
        assert not any("pm unsets it" in n for n in res.effort_notes)

    def test_pm_provider_env_assignment_is_reported_only_for_launches(
            self, pm_home_dir, monkeypatch):
        """``get_provider(None)`` honors PM_PROVIDER, so a launch runs that
        provider's env; a configuration check must not depend on the
        caller's environment."""
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "xhigh"})})
        monkeypatch.setenv("PM_PROVIDER", ROUTE)
        res = resolve_model_and_provider("impl", project_data=_project())
        assert res.effort_env_level == "xhigh"
        assert any(f"provider {ROUTE!r} sets" in n for n in res.effort_notes)
        checked = resolve_model_and_provider("impl", project_data=_project(),
                                             use_env=False)
        assert (checked.effort_status, checked.effort_env_level) == \
            ("none", None)

    def test_unreadable_route_is_not_reported_as_declaring_nothing(
            self, pm_home_dir):
        """A broken entry and a route with no metadata are different
        findings; the note must not invent an absent supported_efforts."""
        _providers(pm_home_dir, **{ROUTE: {"type": "bogus"}})
        data = _project(session_effort={"impl": "high"})
        res = resolve_model_and_provider(
            "impl", pr_model=f"provider:{ROUTE}", project_data=data)
        assert res.effort_status == "unverified"
        assert any("could not be read" in n for n in res.effort_notes)
        assert not any("declares no supported_efforts" in n
                       for n in res.effort_notes)


class TestProviderEffortMetadata:
    def test_add_round_trips_supported_efforts(self, pm_home_dir):
        r = _cli("provider", "add", ROUTE, "--type", "router",
                 "--api-base", "http://127.0.0.1:1", "--model", "rt/big",
                 "--supported-efforts", "low,high,max",
                 "--supported-efforts-source", "GET /models",
                 "--supported-efforts-checked-at", "2026-10-31")
        assert r.exit_code == 0, r.output
        from pm_core.providers import get_provider
        p = get_provider(ROUTE, strict=True)
        assert p.supported_efforts == ["low", "high", "max"]
        assert p.supported_efforts_source == "GET /models"
        assert p.supported_efforts_checked_at == "2026-10-31"

    def test_show_names_accepted_levels_and_provenance(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["none", "high", "max"],
            supported_efforts_source="catalog",
            supported_efforts_checked_at="2026-10-31")})
        r = _cli("provider", "show", ROUTE)
        assert r.exit_code == 0, r.output
        assert "accepted Claude levels: high, max" in r.output
        assert "non-Claude levels kept for provenance: none" in r.output
        assert "supported_efforts source: catalog" in r.output

    def test_show_prints_a_future_date_without_a_negative_age(
            self, pm_home_dir):
        """A future ``checked_at`` (a typo, or a clock that moved back) has
        no meaningful age: print the date alone, never "(-3 days old)"."""
        from datetime import date, timedelta
        future = (date.today() + timedelta(days=3)).isoformat()
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["high"],
            supported_efforts_checked_at=future)})
        r = _cli("provider", "show", ROUTE)
        assert r.exit_code == 0, r.output
        assert f"supported_efforts checked: {future}" in r.output
        assert "days old" not in r.output

    def test_list_names_supported_efforts(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low", "high"])})
        r = _cli("provider", "list")
        assert r.exit_code == 0, r.output
        assert "supported_efforts=low,high" in r.output

    def test_show_names_an_effort_env_assignment(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "xhigh"})})
        r = _cli("provider", "show", ROUTE)
        assert r.exit_code == 0, r.output
        assert "effort env: CLAUDE_CODE_EFFORT_LEVEL=xhigh" in r.output
        assert "overrides --effort" in r.output

    def test_show_does_not_call_auto_an_override(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "auto"})})
        r = _cli("provider", "show", ROUTE)
        assert r.exit_code == 0, r.output
        assert ("effort env: CLAUDE_CODE_EFFORT_LEVEL=auto "
                "(no override; --effort applies)") in r.output

    def test_show_names_a_blank_assignment_as_no_override(self, pm_home_dir):
        """A blank value is still an exported assignment ("no override"),
        so it is shown rather than dropped from the output."""
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": ""})})
        r = _cli("provider", "show", ROUTE)
        assert r.exit_code == 0, r.output
        assert ("effort env: CLAUDE_CODE_EFFORT_LEVEL= "
                "(no override; --effort applies)") in r.output

    @pytest.mark.parametrize("efforts", ["high", [1], ["high", 2], [""]])
    def test_bad_supported_efforts_is_an_invalid_entry(self, pm_home_dir,
                                                       efforts):
        """A hand-edited list that is not a list of names fails the entry,
        so a launch reports it instead of guessing around it."""
        _providers(pm_home_dir, **{ROUTE: _router(supported_efforts=efforts)})
        from pm_core.providers import invalid_provider_entries
        assert ROUTE in invalid_provider_entries()

    def test_bad_checked_at_is_an_invalid_entry(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts_checked_at="yesterday")})
        from pm_core.providers import invalid_provider_entries
        assert ROUTE in invalid_provider_entries()

    def test_clear_removes_the_metadata(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["high"], supported_efforts_source="x")})
        r = _cli("provider", "edit", ROUTE, "--clear", "supported_efforts",
                 "--clear", "supported_efforts_source")
        assert r.exit_code == 0, r.output
        entry = yaml.safe_load((pm_home_dir / "providers.yaml").read_text())[
            "providers"][ROUTE]
        assert "supported_efforts" not in entry
        assert "supported_efforts_source" not in entry


class TestEffortDisplay:
    def test_unsupported_level_is_marked_and_noted(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low", "high"])})
        data = _project(session_models={"impl": f"provider:{ROUTE}"},
                        session_effort={"impl": "xhigh"})
        rows = model_settings.role_rows(data, None)
        impl = next(r for r in rows if r.role == "impl")
        assert impl.effort_status == "unsupported"
        lines = model_settings.format_rows(rows)
        assert any(l.startswith("impl ") and "xhigh *" in l for l in lines)
        assert any("is not in the selected route's supported_efforts" in l
                   for l in lines)
        # The marker is explained once, as a footnote (not a column).
        assert any(l.startswith("* effort not confirmed by pm")
                   for l in lines)

    def test_the_same_note_on_two_routes_is_printed_for_each(
            self, pm_home_dir):
        """The note wording does not name the route, so the dedup must be
        keyed by route: the same level on two routes is two findings."""
        _providers(pm_home_dir,
                   **{ROUTE: _router(supported_efforts=["low"]),
                      "rt2": _router(supported_efforts=["low"])})
        data = _project(session_models={"impl": f"provider:{ROUTE}",
                                        "review": "provider:rt2"},
                        session_effort={"impl": "max", "review": "max"})
        rows = model_settings.role_rows(data, None)
        lines = model_settings.format_rows(rows)
        assert any(l.startswith("impl ") and "max *" in l for l in lines)
        assert any(l.startswith("review ") and "max *" in l for l in lines)
        notes = [l for l in lines
                 if "is not in the selected route's supported_efforts" in l]
        assert len(notes) == 2, notes

    def test_one_note_for_two_roles_on_the_same_route(self, pm_home_dir):
        """A route-wide fact repeats for every role it decides, so it is
        printed once, not once per role."""
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low"])})
        data = _project(session_models={"impl": f"provider:{ROUTE}",
                                        "review": f"provider:{ROUTE}"},
                        session_effort={"impl": "max", "review": "max"})
        lines = model_settings.format_rows(
            model_settings.role_rows(data, None))
        notes = [l for l in lines
                 if "is not in the selected route's supported_efforts" in l]
        assert len(notes) == 1, notes

    def test_unverified_is_noted_without_the_inline_mark(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router()})
        data = _project(session_models={"impl": f"provider:{ROUTE}"},
                        session_effort={"impl": "high"})
        rows = model_settings.role_rows(data, None)
        impl = next(r for r in rows if r.role == "impl")
        assert impl.effort_status == "unverified"
        lines = model_settings.format_rows(rows)
        assert any(l.startswith("impl ") and "high  " in l for l in lines)
        assert any("declares no supported_efforts" in l for l in lines)
        # No marker, so no marker legend either.
        assert not any(l.startswith("* effort not confirmed by pm")
                       for l in lines)

    def test_provider_env_conflict_is_marked_and_noted(self, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            env={"CLAUDE_CODE_EFFORT_LEVEL": "max"})})
        data = _project(session_models={"impl": f"provider:{ROUTE}"},
                        session_effort={"impl": "high"})
        rows = model_settings.role_rows(data, None)
        impl = next(r for r in rows if r.role == "impl")
        assert impl.effort_status == "overridden"
        assert model_settings.effort_cell(impl) == "high *"
        lines = model_settings.format_rows(rows)
        assert any("CLAUDE_CODE_EFFORT_LEVEL=max" in l for l in lines)

    def test_model_show_names_the_requested_level_for_haiku(
            self, project_root, pm_home_dir, monkeypatch):
        """`pm model show` and `pm pr model show` agree: a suppressed level
        stays visible as the requested one, never as the CLI default."""
        import pm_core.cli.model as model_cli
        monkeypatch.setattr(model_cli, "state_root", lambda: project_root)
        data = store.load(project_root)
        data["project"]["model_config"] = {
            "session_models": {"impl": "haiku"},
            "session_effort": {"impl": "xhigh"}}
        store.save(data, project_root)
        r = _cli("model", "show")
        assert r.exit_code == 0, r.output
        assert "xhigh (n/a)" in r.output
        assert "does not support the --effort flag" in r.output

    def test_model_show_marks_an_unsupported_level(self, project_root,
                                                   pm_home_dir, monkeypatch):
        """The CLI column uses the same marker as the role table."""
        import pm_core.cli.model as model_cli
        monkeypatch.setattr(model_cli, "state_root", lambda: project_root)
        _providers(pm_home_dir, **{ROUTE: _router(supported_efforts=["low"])})
        data = store.load(project_root)
        data["project"]["model_config"] = {
            "session_models": {"impl": f"provider:{ROUTE}"},
            "session_effort": {"impl": "max"}}
        store.save(data, project_root)
        r = _cli("model", "show")
        assert r.exit_code == 0, r.output
        impl = next(l for l in r.output.splitlines()
                    if l.strip().startswith("impl "))
        assert "max *" in impl
        # One finding, one line: the effort note and the problems section
        # say the same sentence, so it is printed once, not twice.
        assert r.output.count(
            "not in the selected route's supported_efforts") == 1

    def test_model_show_prints_a_note_for_each_route(
            self, project_root, pm_home_dir, monkeypatch):
        """The note wording does not name the route, so two roles on two
        routes with the same level are two findings, not one."""
        import pm_core.cli.model as model_cli
        monkeypatch.setattr(model_cli, "state_root", lambda: project_root)
        _providers(pm_home_dir,
                   **{ROUTE: _router(supported_efforts=["low"]),
                      "rt2": _router(supported_efforts=["low"])})
        data = store.load(project_root)
        data["project"]["model_config"] = {
            "session_models": {"impl": f"provider:{ROUTE}",
                               "review": "provider:rt2"},
            "session_effort": {"impl": "max", "review": "max"}}
        store.save(data, project_root)
        r = _cli("model", "show")
        assert r.exit_code == 0, r.output
        notes = [l for l in r.output.splitlines()
                 if l.strip().startswith("! ")]
        assert len(notes) == 2, notes

    def test_mixed_effort_route_summary_is_not_marked(
            self, project_root, pm_home_dir, monkeypatch):
        """A route line whose roles run different levels carries a summary,
        not one role's verification status: "max (impl), high otherwise
        (unsupported)" would read as if every role were unsupported.  The
        per-role table above names each one."""
        import pm_core.cli.model as model_cli
        monkeypatch.setattr(model_cli, "state_root", lambda: project_root)
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["high"])})
        data = store.load(project_root)
        data["prs"][0]["model"] = f"provider:{ROUTE}"
        data["prs"][0]["session_effort"] = {"impl": "max", "review": "high"}
        store.save(data, project_root)
        r = _cli("model", "show")
        assert r.exit_code == 0, r.output
        route = next(l for l in r.output.splitlines()
                     if l.strip().startswith("pr-001 ") and "route=" in l)
        assert "otherwise" in route
        assert "unsupported" not in route
        # The per-role table still reports the unsupported level, and the
        # problems section keeps the PR finding.
        assert "prs[pr-001] impl: effort 'max' is not in" in r.output
        roles = _cli("pr", "model", "show", "pr-001")
        assert roles.exit_code == 0, roles.output
        assert "max *" in roles.output

    def test_describe_marks_unsupported(self, pm_home_dir):
        from pm_core.router_route import describe
        from pm_core.model_config import ModelResolution
        _providers(pm_home_dir, **{ROUTE: _router()})
        res = ModelResolution(provider=ROUTE, effort="xhigh",
                              effort_status="unsupported")
        assert describe(res) == (f"route={ROUTE} model=rt/big "
                                 "effort=xhigh (unsupported) via=host")

    def test_describe_leaves_verified_level_bare(self, pm_home_dir):
        from pm_core.router_route import describe
        from pm_core.model_config import ModelResolution
        _providers(pm_home_dir, **{ROUTE: _router()})
        res = ModelResolution(provider=ROUTE, effort="high",
                              effort_status="ok")
        assert describe(res) == (f"route={ROUTE} model=rt/big "
                                 "effort=high via=host")


class TestEffortRoundTrip:
    def test_validate_accepts_the_new_levels(self, pm_home_dir):
        data = _project(session_effort={"impl": "xhigh", "review": "max"})
        assert validate_model_config(data) == []

    def test_pm_effort_xhigh(self, pm_home_dir, monkeypatch):
        monkeypatch.setenv("PM_EFFORT", "xhigh")
        res = resolve_model_and_provider("impl")
        assert (res.effort, res.effort_source) == ("xhigh", "PM_EFFORT")

    def test_model_set_project_round_trips_max(self, project_root,
                                               pm_home_dir, monkeypatch):
        import pm_core.cli.model as model_cli
        monkeypatch.setattr(model_cli, "state_root", lambda: project_root)
        r = _cli("model", "set", "impl", "opus", "--effort", "max",
                 "--project")
        assert r.exit_code == 0, r.output
        data = store.load(project_root)
        assert data["project"]["model_config"]["session_effort"]["impl"] \
            == "max"
        assert resolve_model_and_provider("impl", project_data=data).effort \
            == "max"

    def test_model_set_global_round_trips_xhigh(self, project_root,
                                                pm_home_dir, monkeypatch):
        written: dict[str, str] = {}
        monkeypatch.setattr(
            "pm_core.model_config.get_global_setting_value",
            lambda name, default="": written.get(name, default))
        monkeypatch.setattr("pm_core.paths.set_global_setting_value",
                            lambda name, value: written.__setitem__(name,
                                                                    value))
        r = _cli("model", "set", "impl", "opus", "--effort", "xhigh")
        assert r.exit_code == 0, r.output
        assert written["effort-impl"] == "xhigh"
        res = resolve_model_and_provider("impl")
        assert (res.effort, res.effort_source) == ("xhigh", "global impl")

    def test_pr_model_set_round_trips_xhigh(self, project_root, pm_home_dir):
        r = _cli("pr", "model", "set", "pr-001", "opus", "--effort", "xhigh")
        assert r.exit_code == 0, r.output
        pr = store.get_pr(store.load(project_root), "pr-001")
        assert pr["effort"] == "xhigh"
        r = _cli("pr", "model", "show", "pr-001")
        assert r.exit_code == 0, r.output
        assert "xhigh" in r.output


class TestNotApplicableEffort:
    def test_haiku_shows_requested_level_as_n_a(self, pm_home_dir):
        data = _project(session_models={"impl": "haiku"},
                        session_effort={"impl": "xhigh"})
        rows = model_settings.role_rows(data, None)
        impl = next(r for r in rows if r.role == "impl")
        assert impl.effort_status == "not_applicable"
        assert model_settings.effort_cell(impl) == "xhigh (n/a)"
        assert any("suppressed" in n for n in impl.effort_notes)

    def test_suppressed_level_keeps_the_source_that_asked_for_it(
            self, pm_home_dir):
        """"xhigh (n/a)" beside "effort: project impl", never "CLI
        default": the requested level did come from a setting."""
        data = _project(session_models={"impl": "haiku"},
                        session_effort={"impl": "xhigh"})
        impl = next(r for r in model_settings.role_rows(data, None)
                    if r.role == "impl")
        assert impl.effort_source == "project impl"
        lines = model_settings.format_rows([impl])
        assert any("effort: project impl" in line for line in lines)


class TestSetTimeEffortWarnings:
    def test_pr_model_set_warns_on_unsupported_route_level(
            self, project_root, pm_home_dir):
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low"])})
        r = _cli("pr", "model", "set", "pr-001", f"provider:{ROUTE}",
                 "--effort", "max")
        assert r.exit_code == 0, r.output
        assert "Warning" in r.output and "supported_efforts" in r.output

    def test_model_set_warns_on_unsupported_route_level(
            self, project_root, pm_home_dir, monkeypatch):
        import pm_core.cli.model as model_cli
        monkeypatch.setattr(model_cli, "state_root", lambda: project_root)
        _providers(pm_home_dir, **{ROUTE: _router(
            supported_efforts=["low"])})
        r = _cli("model", "set", "impl", f"provider:{ROUTE}",
                 "--effort", "max", "--project")
        assert r.exit_code == 0, r.output
        assert "Warning" in r.output and "supported_efforts" in r.output
