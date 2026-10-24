"""CLI commands for model configuration."""

import click

from pm_core.cli.helpers import state_root
from pm_core.model_config import SESSION_TYPES

# Single source of truth — kept in sync with model_config.SESSION_TYPES.
_SESSION_TYPES = list(SESSION_TYPES)


@click.group("model")
def model():
    """View and configure per-session-type model targeting."""
    pass


@model.command("show")
def model_show():
    """Show effective model for each session type."""
    from pm_core import store
    from pm_core.model_config import (
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

    if resolvable:
        click.echo("Effective config per session type:")
        click.echo(f"  {'type':14s}   {'model':40s} {'effort':8s}")
        click.echo(f"  {'─'*14}   {'─'*40} {'─'*8}")
        for st in SESSION_TYPES:
            res = resolve_model_and_provider(st, project_data=data)
            if res.provider:
                model_str = f"provider:{res.provider}"
            elif res.model:
                model_str = res.model
            else:
                model_str = "(default)"
            effort_str = res.effort or "(default)"
            click.echo(f"  {st:14s}   {model_str:40s} {effort_str:8s}")
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
        if pr.get("model"):
            pr_lines.append(f"  {pr.get('id')}  model  -> {pr['model']}")
        roles = pr.get("session_models")
        if isinstance(roles, dict):
            for st, val in roles.items():
                pr_lines.append(f"  {pr.get('id')}  {st} model  -> {val}")
    if pr_lines:
        click.echo()
        click.echo("PR overrides (project.yaml prs[]: model, session_models):")
        for line in pr_lines:
            click.echo(line)

    # Router providers (worker routes): where those sessions actually go.
    from pm_core import worker_route
    shown = False
    for st in SESSION_TYPES if resolvable else ():
        res = resolve_model_and_provider(st, project_data=data)
        if not res.provider:
            continue
        if not shown:
            click.echo()
            click.echo("Routes:")
            shown = True
        click.echo(f"  {st:14s} {worker_route.describe(res)}")

    # Surface invalid model_config entries — unknown session types are
    # silently ignored at resolution time, so a typo would otherwise just
    # never take effect.
    from pm_core.model_config import validate_model_config
    problems = validate_model_config(data)
    if problems:
        click.echo()
        click.echo("⚠ Problems in project.yaml model settings:")
        for p in problems:
            click.echo(f"  • {p}")


@model.command("set")
@click.argument("session_type", type=click.Choice(_SESSION_TYPES))
@click.argument("model_value")
@click.option("--effort", type=click.Choice(["low", "medium", "high"]),
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
