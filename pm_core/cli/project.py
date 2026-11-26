"""CLI commands for project-level settings."""

import click

from pm_core.cli.helpers import state_root

# Project-level boolean settings: name → description
_PROJECT_BOOLEAN_SETTINGS = {
    "skip-qa": "Skip QA step in auto-start flow (review PASS goes straight to merge)",
}

_PROJECT_SETTING_DEFAULTS = {
    "skip-qa": "off",
}

# Map CLI names (kebab-case) to project.yaml keys (snake_case)
_YAML_KEY = {
    "skip-qa": "skip_qa",
}


@click.group("project")
def project():
    """View and configure project-level settings."""
    pass


@project.command("set")
@click.argument("setting")
@click.argument("value", required=False, default=None)
def project_set(setting, value):
    """Configure a project-level setting.

    Run 'pm project set list' to see all settings and their current values.

    Boolean settings (on/off):

      skip-qa     Skip QA in auto-start: review PASS merges directly
    """
    if setting in ("list", "ls", "l"):
        _list_project_settings()
        return
    if value is None:
        raise click.UsageError("Missing argument 'VALUE'.")

    known = set(_PROJECT_BOOLEAN_SETTINGS)
    if setting not in known:
        click.echo(f"Unknown project setting: {setting}", err=True)
        click.echo(f"Available: {', '.join(sorted(known))}", err=True)
        raise SystemExit(1)

    if setting in _PROJECT_BOOLEAN_SETTINGS:
        if value not in ("on", "off"):
            click.echo(f"Setting '{setting}' takes 'on' or 'off'", err=True)
            raise SystemExit(1)
        _set_project_bool(setting, value == "on")

    click.echo(f"{setting} = {value}")


def _set_project_bool(setting: str, enabled: bool) -> None:
    """Write a boolean setting to project.yaml."""
    from pm_core import store

    root = state_root()
    data = store.load(root)
    key = _YAML_KEY[setting]
    data.setdefault("project", {})[key] = enabled
    store.save(data, root)


def _list_project_settings():
    """Print all project-level settings and their current values."""
    from pm_core import store

    root = state_root()
    data = store.load(root)
    project = data.get("project") or {}

    click.echo("Project settings:")
    for name in sorted(_PROJECT_BOOLEAN_SETTINGS):
        key = _YAML_KEY[name]
        raw = project.get(key)
        if raw is None:
            val = _PROJECT_SETTING_DEFAULTS.get(name, "off")
            marker = " (default)"
        else:
            val = "on" if raw else "off"
            marker = ""
        desc = _PROJECT_BOOLEAN_SETTINGS[name]
        click.echo(f"  {name:<22} {val}{marker}    {desc}")


# Register with the main CLI
from pm_core.cli import cli  # noqa: E402
cli.add_command(project)
