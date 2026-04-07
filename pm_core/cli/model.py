"""CLI commands for model configuration."""

import click

from pm_core.cli.helpers import state_root

_SESSION_TYPES = ["impl", "review", "qa", "qa_planning", "qa_scenario", "qa_verification", "watcher", "merge"]


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
        resolve_model_and_provider,
    )

    root = state_root()
    data = store.load(root)

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
    mc = data.get("project", {}).get("model_config", {})
    if mc:
        click.echo("Project-level overrides (project.yaml):")
        session_models = mc.get("session_models", {})
        for st, val in session_models.items():
            click.echo(f"  {st:14s} model  -> {val}")
        session_effort = mc.get("session_effort", {})
        for st, val in session_effort.items():
            click.echo(f"  {st:14s} effort -> {val}")
    else:
        click.echo("No project-level model_config in project.yaml (using defaults).")

    # Show configured local/external providers (always shown)
    from pm_core.providers import list_providers
    providers = [p for p in list_providers() if p.type != "claude" or p.api_base]
    click.echo()
    click.echo("Available local/external providers:")
    if providers:
        click.echo(f"  {'name':15s} {'type':8s} {'model':25s} {'api_base'}")
        click.echo(f"  {'─'*15} {'─'*8} {'─'*25} {'─'*30}")
        for p in providers:
            model_str = p.model or "(none)"
            click.echo(f"  {p.name:15s} {p.type:8s} {model_str:25s} {p.api_base}")
        click.echo()
        click.echo("  Use with: pm model set <type> provider:<name>")
        click.echo("  Example:  pm model set watcher provider:ollama")
    else:
        click.echo("  (none configured — add with: pm provider add ollama --api-base http://localhost:11434)")


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
        root = state_root()
        data = store.load(root)
        mc = data.setdefault("project", {}).setdefault("model_config", {})
        mc.setdefault("session_models", {})[session_type] = model_value
        mc.setdefault("session_effort", {})[session_type] = effort
        store.save(data, root)
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
        root = state_root()
        data = store.load(root)
        mc = data.get("project", {}).get("model_config", {})
        removed = False
        for key in ("session_models", "session_effort"):
            mapping = mc.get(key, {})
            if session_type in mapping:
                del mapping[session_type]
                removed = True
                if not mapping and key in mc:
                    del mc[key]
        if not mc and "model_config" in data.get("project", {}):
            del data["project"]["model_config"]
        if removed:
            store.save(data, root)
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
