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
    for mod in ("pm_core.providers", "pm_core.worker_route"):
        monkeypatch.setattr(f"{mod}.pm_home", lambda: home)
    for var in ("PM_PROVIDER", "PM_MODEL", "PM_EFFORT"):
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
              "session_effort": {"impl": "max", "bogus": "low"}}
        data["prs"] = [pr]
        res = resolve_model_and_provider("impl", pr_entry=pr,
                                         project_data=data)
        assert (res.effort, res.effort_source) == ("medium", "project impl")
        problems = "\n".join(validate_model_config(data))
        assert "prs[pr-1].effort: invalid effort 'turbo'" in problems
        assert "session_effort['impl']: invalid effort 'max'" in problems
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

    def test_env_applies_to_other_types(self):
        p = ProviderConfig(name="o", type="local", api_base="http://x:1",
                           env={"FOO": "bar"})
        assert p.env_vars()["FOO"] == "bar"

    @pytest.mark.parametrize("entry, problem", [
        ({"env": {"A": 1}}, "'env' must map"),
        ({"unset_env": "A"}, "'unset_env' must be a list"),
        ({"probe_models": [1]}, "'probe_models' must be a list"),
        ({"effort": "max"}, "unknown effort"),
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
            model_settings.set_pr_value({}, "effort", "max")

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
    assert [next_effort(x) for x in (None, "low", "medium", "high", "bad")] == [
        "low", "medium", "high", None, "low"]


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
