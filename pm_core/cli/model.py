"""CLI commands for model configuration."""

import click

from pm_core.cli.helpers import state_root


@click.group("model")
def model():
    """View and configure per-session-type model targeting."""
    pass


@model.command("show")
def model_show():
    """Show effective model for each session type."""
    from pm_core import store
    from pm_core.model_config import (
        SESSION_TYPES, QUALITY_TIERS, DEFAULT_SESSION_MODELS,
        DEFAULT_SESSION_EFFORT, get_model_config_summary,
        resolve_model_and_provider,
    )

    root = state_root()
    data = store.load(root)

    click.echo("Quality tiers:")
    for tier in ("high", "medium", "low"):
        click.echo(f"  {tier:10s} -> {QUALITY_TIERS[tier]}")
    click.echo()
    click.echo("Model shortcuts:")
    for name in ("opus", "sonnet", "haiku"):
        click.echo(f"  {name:10s} -> {QUALITY_TIERS[name]}")
    click.echo()

    click.echo("Effective config per session type:")
    click.echo(f"  {'type':10s}   {'model':40s} {'effort':8s}")
    click.echo(f"  {'─'*10}   {'─'*40} {'─'*8}")
    for st in SESSION_TYPES:
        res = resolve_model_and_provider(st, project_data=data)
        if res.provider:
            model_str = f"provider:{res.provider}"
        elif res.model:
            model_str = res.model
        else:
            model_str = "(default)"
        effort_str = res.effort or "n/a"
        click.echo(f"  {st:10s}   {model_str:40s} {effort_str:8s}")
    click.echo()

    # Show project-level overrides if any
    mc = data.get("project", {}).get("model_config", {})
    if mc:
        click.echo("Project-level overrides (project.yaml):")
        session_models = mc.get("session_models", {})
        for st, val in session_models.items():
            click.echo(f"  {st:10s} -> {val}")
        custom_tiers = mc.get("quality_tiers", {})
        if custom_tiers:
            click.echo("Custom quality tiers:")
            for tier, model_id in custom_tiers.items():
                click.echo(f"  {tier:10s} -> {model_id}")
    else:
        click.echo("No project-level model_config in project.yaml (using defaults).")


@model.command("set")
@click.argument("session_type", type=click.Choice(["impl", "review", "qa", "watcher", "merge"]))
@click.argument("model_value")
def model_set(session_type: str, model_value: str):
    """Set the global default model for a session type.

    MODEL_VALUE can be a quality tier (high, medium, low), a model name
    (opus, sonnet, haiku), a full model ID, or provider:NAME to use a
    configured provider (see ``pm provider``).
    """
    from pm_core.paths import set_global_setting_value
    set_global_setting_value(f"model-{session_type}", model_value)
    click.echo(f"Set global model for '{session_type}' to '{model_value}'")


@model.command("unset")
@click.argument("session_type", type=click.Choice(["impl", "review", "qa", "watcher", "merge"]))
def model_unset(session_type: str):
    """Remove the global default model override for a session type."""
    from pm_core.paths import pm_home
    f = pm_home() / "settings" / f"model-{session_type}"
    if f.exists():
        f.unlink()
        click.echo(f"Removed global model override for '{session_type}'")
    else:
        click.echo(f"No global model override set for '{session_type}'")


# Register with the main CLI
from pm_core.cli import cli  # noqa: E402
cli.add_command(model)
