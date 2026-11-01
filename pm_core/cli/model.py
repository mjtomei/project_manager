"""CLI commands for model configuration."""

import dataclasses
import os

import click

from pm_core.cli.helpers import state_root
from pm_core.model_config import EFFORT_LEVELS, SESSION_TYPES

# Single source of truth — kept in sync with model_config.SESSION_TYPES.
_SESSION_TYPES = list(SESSION_TYPES)


@click.group("model")
def model():
    """View and configure per-session-type model targeting."""
    pass


@model.command("show")
def model_show():
    """Show effective model for each session type."""
    from pm_core import model_settings, store
    from pm_core.model_config import (
        MARKED_EFFORT_STATUSES,
        SESSION_TYPES,
        config_block,
        project_model_config,
        resolve_model_and_provider,
    )

    root = state_root()
    data = store.load(root)

    # A model_config (or block) that is not a mapping cannot be resolved
    # per type.  Still list the PR overrides and the problems below: this
    # is where a model setting problem is meant to be found.
    mc = project_model_config(data)
    resolvable = isinstance(mc, dict) and all(
        isinstance(config_block(mc, block), dict)
        for block in ("session_models", "session_effort"))

    # Effort notes already printed above, so a problem that repeats one is
    # not printed twice below.
    seen_notes: set[str] = set()
    if resolvable:
        click.echo("Effective config per session type:")
        click.echo(f"  {'type':15s}  {'model':40s} {'effort':8s}")
        click.echo(f"  {'─'*15}  {'─'*40} {'─'*8}")
        effort_notes: list[str] = []
        # Printed notes are deduped per (route, note): the wording does not
        # name the route, so two roles on different routes with the same
        # level are two findings, while a route-wide fact repeats for every
        # role it decides.
        seen_role_notes: set[tuple[str | None, str]] = set()
        marked = False
        for st in SESSION_TYPES:
            res = resolve_model_and_provider(st, project_data=data)
            if res.provider:
                model_str = f"provider:{res.provider}"
            elif res.model:
                model_str = res.model
            else:
                model_str = "(default)"
            effort_str = model_settings.effort_mark(
                model_settings.effort_text(res), res.effort_status)
            marked = marked or res.effort_status in MARKED_EFFORT_STATUSES
            click.echo(f"  {st:15s}  {model_str:40s} {effort_str:8s}")
            for note in res.effort_notes:
                # ``seen_notes`` stays flat: it also suppresses the same
                # finding in the problems section below.
                seen_notes.add(note)
                key = (res.provider, note)
                if key in seen_role_notes:
                    continue
                seen_role_notes.add(key)
                effort_notes.append(f"  ! {st}: {note}")
        click.echo()
        if effort_notes:
            # Explain ``*`` only when a row actually carries it; a note can
            # exist without one (e.g. an unverified route, an ambient
            # override on a plain model).
            click.echo("Effort notes"
                       + (" (* = not confirmed by pm)" if marked else "")
                       + ":")
            for line in effort_notes:
                click.echo(line)
            click.echo()

    # Show project-level overrides if any
    if not resolvable:
        click.echo("Effective config not shown: model_config is malformed "
                   "(see the problems below).")
    elif mc:
        click.echo("Project-level overrides (project.yaml):")
        for st, val in config_block(mc, "session_models").items():
            click.echo(f"  {st:14s} model  -> {val}")
        for st, val in config_block(mc, "session_effort").items():
            click.echo(f"  {st:14s} effort -> {val}")
    else:
        click.echo("No project-level model_config in project.yaml (using defaults).")

    # PR overrides win over everything above except PM_MODEL.
    pr_lines = []
    for pr in data.get("prs") or []:
        for kind, role_key in (("model", "session_models"),
                               ("effort", "session_effort")):
            if pr.get(kind):
                pr_lines.append(f"  {pr.get('id')}  {kind}  -> {pr[kind]}")
            roles = pr.get(role_key)
            if isinstance(roles, dict):
                for st, val in roles.items():
                    pr_lines.append(f"  {pr.get('id')}  {st} {kind}  -> {val}")
    if pr_lines:
        click.echo()
        click.echo("PR overrides (project.yaml prs[]: model, session_models, "
                   "effort, session_effort; 'pm pr model show <pr>' for one "
                   "PR's roles):")
        for line in pr_lines:
            click.echo(line)

    # Router providers: where each explicitly routed role actually goes.
    # Any role may be routed; the setting is explicit per role.
    from pm_core import router_route
    from pm_core.container import is_container_mode_enabled
    from pm_core.model_config import PR_SESSION_TYPES, get_pr_model_override
    # In container mode only some types run in a container (and reach the
    # route through its bridge); the rest stay on the host (S58).  This is
    # placement, not routing eligibility.
    in_containers = is_container_mode_enabled()

    def describe(st, res):
        return router_route.describe(
            res, container=(in_containers
                            and st in router_route.CONTAINER_SESSION_TYPES))

    route_lines = []
    for st in SESSION_TYPES if resolvable else ():
        res = resolve_model_and_provider(st, project_data=data)
        if res.provider:
            route_lines.append(f"  {st:14s} {describe(st, res)}")
    # A PR override that selects a route sends that PR's sessions there
    # too; resolved per type as its launches do (one line per distinct
    # route, naming the types it covers).  Only the types the override
    # decides: the others (and the project-wide watcher) follow the
    # project lines above.  PM_MODEL beats every PR override, so then no
    # override decides anything (the lines above already show its route).
    pr_routes = resolvable and not os.environ.get("PM_MODEL")
    for pr in (data.get("prs") or []) if pr_routes else ():
        if not (pr.get("model") or isinstance(pr.get("session_models"), dict)):
            continue
        # Grouped by route without the effort: a project session_effort
        # (e.g. qa_scenario high) must not split one route into several
        # lines, none of them "all types" (S55).  The path (via=) does
        # split it: in container mode impl/review/sign-off/refiner/worker
        # take the bridge, the other types the host.
        routes: dict[str, list[tuple[str, object]]] = {}
        for st in PR_SESSION_TYPES:
            pr_model = get_pr_model_override(pr, st)
            # A non-string PR model (hand-edited) selects no route; it is
            # listed under the problems below rather than crashing here.
            if not pr_model or not isinstance(pr_model, str):
                continue
            res = resolve_model_and_provider(
                st, pr_model=pr_model, project_data=data, pr_entry=pr)
            if res.provider:
                # The effort is reported per role below, so strip it here
                # (including a provider env level) to key the route line.
                key = describe(st, dataclasses.replace(
                    res, effort=None, effort_env_level=None,
                    effort_status="none", effort_notes=[]))
                routes.setdefault(key, []).append((st, res))
        for items in routes.values():
            types = [st for st, _ in items]
            label = ("all types" if len(types) == len(PR_SESSION_TYPES)
                     else ", ".join(types))
            efforts: dict[str, list[str]] = {}
            for st, res in items:
                # The level the role runs: pm's own, else one a provider
                # env block assigns, else the CLI default.
                efforts.setdefault(res.effort or res.effort_env_level
                                   or "(default)", []).append(st)
            res = items[0][1]
            if len(efforts) > 1:
                common = max(efforts, key=lambda e: len(efforts[e]))
                summary = ", ".join(f"{e} ({', '.join(sts)})"
                                    for e, sts in efforts.items()
                                    if e != common)
                # A mixed summary is not one level, so it cannot carry one
                # role's verification status: "high (impl), max otherwise
                # (unsupported)" would read as if every role were
                # unsupported.  The per-role table above names each one.
                res = dataclasses.replace(
                    res, effort=f"{summary}, {common} otherwise",
                    effort_status="none")
            route_lines.append(
                f"  {pr.get('id')} ({label}) {describe(items[0][0], res)}")
    if route_lines:
        click.echo()
        click.echo("Routes (roles set to a provider):")
        for line in route_lines:
            click.echo(line)

    # Surface invalid model_config entries — unknown session types are
    # silently ignored at resolution time, so a typo would otherwise just
    # never take effect.
    from pm_core.model_config import validate_model_config
    # A project-level route-effort finding is already one of the effort
    # notes above (the same sentence, from the same helper); print it once.
    # A PR's finding keeps its line: the prefix names where it is.
    problems = [p for p in validate_model_config(data)
                if p.startswith("prs[")
                or not any(p.endswith(note) for note in seen_notes)]
    if problems:
        click.echo()
        click.echo("⚠ Problems in project.yaml model settings:")
        for p in problems:
            click.echo(f"  • {p}")


@model.command("set")
@click.argument("session_type", type=click.Choice(_SESSION_TYPES))
@click.argument("model_value")
@click.option("--effort", type=click.Choice(list(EFFORT_LEVELS)),
              default="medium", help="Effort level (default: medium)")
@click.option("--project", "use_project", is_flag=True, default=False,
              help="Set in project.yaml instead of global settings")
def model_set(session_type: str, model_value: str, effort: str, use_project: bool):
    """Set the model and effort for a session type.

    MODEL_VALUE can be a model name shortcut (opus, sonnet, haiku),
    a full model ID, or provider:NAME to use a configured provider
    (see ``pm provider``).

    By default sets the global override (~/.pm/settings). Use --project
    to set in project.yaml instead.
    """
    if use_project:
        from pm_core import store
        from pm_core.model_config import config_block, project_model_config
        root = state_root()

        def apply(data):
            # A blank block (entries all commented out) is filled in.
            mc = project_model_config(data)
            data.setdefault("project", {})["model_config"] = mc
            for block, value in (("session_models", model_value),
                                 ("session_effort", effort)):
                mc[block] = config_block(mc, block)
                mc[block][session_type] = value

        store.locked_update(root, apply)
        click.echo(f"Set project model for '{session_type}' to '{model_value}' (effort: {effort})")
    else:
        from pm_core.paths import set_global_setting_value
        set_global_setting_value(f"model-{session_type}", model_value)
        set_global_setting_value(f"effort-{session_type}", effort)
        click.echo(f"Set global model for '{session_type}' to '{model_value}' (effort: {effort})")

    # A level the selected route declares unsupported is still written (the
    # metadata is dated), but the success line must not be the only feedback.
    from pm_core import model_settings
    data = None
    if use_project:
        from pm_core import store
        data = store.load(state_root())
    warn = model_settings.effort_warning(data, session_type)
    if warn:
        click.echo(f"Warning: {warn}", err=True)


@model.command("unset")
@click.argument("session_type", type=click.Choice(_SESSION_TYPES))
@click.option("--project", "use_project", is_flag=True, default=False,
              help="Remove from project.yaml instead of global settings")
def model_unset(session_type: str, use_project: bool):
    """Remove the model and effort override for a session type."""
    if use_project:
        from pm_core import store
        from pm_core.model_config import config_block, project_model_config
        root = state_root()
        removed = False

        def apply(data):
            nonlocal removed
            mc = project_model_config(data)
            for key in ("session_models", "session_effort"):
                mapping = config_block(mc, key)
                if session_type in mapping:
                    del mapping[session_type]
                    removed = True
                    if not mapping and key in mc:
                        del mc[key]
            if not mc and "model_config" in data.get("project", {}):
                del data["project"]["model_config"]

        store.locked_update(root, apply)
        if removed:
            click.echo(f"Removed project overrides for '{session_type}'")
        else:
            click.echo(f"No project overrides set for '{session_type}'")
    else:
        from pm_core.paths import pm_home
        removed = False
        for prefix in ("model", "effort"):
            f = pm_home() / "settings" / f"{prefix}-{session_type}"
            if f.exists():
                f.unlink()
                removed = True
        if removed:
            click.echo(f"Removed global overrides for '{session_type}'")
        else:
            click.echo(f"No global overrides set for '{session_type}'")


# Register with the main CLI
from pm_core.cli import cli  # noqa: E402
cli.add_command(model)
