"""Provider management CLI commands."""

import click

from pm_core.cli import cli


@cli.group("provider")
def provider_group():
    """Manage LLM providers for Claude sessions.

    Configure local LLM providers (Ollama, vLLM, llama.cpp) as alternatives
    to the default Claude API.  Providers are stored in ~/.pm/providers.yaml.
    """


@provider_group.command("list")
def provider_list():
    """List all configured providers."""
    from pm_core.providers import list_providers, get_default_provider

    default = get_default_provider()
    providers = list_providers()

    for p in providers:
        marker = " (default)" if p.name == default else ""
        if p.type == "claude" and not p.api_base:
            click.echo(f"  {p.name}{marker}  [built-in]")
        else:
            model_str = f"  model={p.model}" if p.model else ""
            click.echo(f"  {p.name}{marker}  type={p.type}  api_base={p.api_base}{model_str}")
            if p.capabilities:
                click.echo(f"    capabilities: {', '.join(p.capabilities)}")


@provider_group.command("add")
@click.argument("name")
@click.option("--type", "ptype", default="openai", type=click.Choice(["openai", "claude"]),
              help="Provider type (default: openai)")
@click.option("--api-base", required=True, help="API base URL (e.g. http://localhost:11434/v1)")
@click.option("--api-key", default="", help="API key (or ${ENV_VAR} reference)")
@click.option("--model", default="", help="Model name")
@click.option("--capabilities", default="", help="Comma-separated capability tags")
def provider_add(name: str, ptype: str, api_base: str, api_key: str,
                 model: str, capabilities: str):
    """Add a new LLM provider.

    \b
    Examples:
      pm provider add ollama --api-base http://localhost:11434/v1 --model llama3.1:70b
      pm provider add vllm --api-base http://localhost:8000/v1 --api-key '${VLLM_KEY}' --model codellama
    """
    from pm_core.providers import load_providers, save_providers

    config = load_providers()
    if "providers" not in config:
        config["providers"] = {}

    config["providers"][name] = {
        "type": ptype,
        "api_base": api_base,
    }
    if api_key:
        config["providers"][name]["api_key"] = api_key
    if model:
        config["providers"][name]["model"] = model
    if capabilities:
        config["providers"][name]["capabilities"] = [c.strip() for c in capabilities.split(",")]

    save_providers(config)
    click.echo(f"Added provider '{name}' ({ptype}: {api_base})")


@provider_group.command("remove")
@click.argument("name")
def provider_remove(name: str):
    """Remove a configured provider."""
    from pm_core.providers import load_providers, save_providers, get_default_provider

    if name == "claude":
        click.echo("Cannot remove the built-in 'claude' provider.", err=True)
        raise SystemExit(1)

    config = load_providers()
    providers = config.get("providers", {})
    if name not in providers:
        click.echo(f"Provider '{name}' not found.", err=True)
        raise SystemExit(1)

    del providers[name]
    # Reset default if we removed the default provider
    if config.get("default") == name:
        config["default"] = "claude"
    save_providers(config)
    click.echo(f"Removed provider '{name}'")


@provider_group.command("default")
@click.argument("name")
def provider_default(name: str):
    """Set the default provider.

    \b
    Examples:
      pm provider default ollama
      pm provider default claude
    """
    from pm_core.providers import load_providers, set_default_provider

    if name != "claude":
        config = load_providers()
        if name not in config.get("providers", {}):
            click.echo(f"Provider '{name}' not found. Add it first with 'pm provider add'.",
                        err=True)
            raise SystemExit(1)

    set_default_provider(name)
    click.echo(f"Default provider set to '{name}'")


@provider_group.command("test")
@click.argument("name", required=False)
def provider_test(name: str | None):
    """Test connectivity to a provider.

    If NAME is omitted, tests the default provider.
    """
    from pm_core.providers import get_provider

    provider = get_provider(name)
    click.echo(f"Testing provider '{provider.name}' (type={provider.type})...")

    if provider.type == "claude":
        if not provider.api_base:
            click.echo("  Built-in Claude provider — no endpoint to test.")
            click.echo("  Use 'claude --version' to verify the CLI is installed.")
            return

    env = provider.env_vars()
    api_base = env.get("OPENAI_BASE_URL") or env.get("ANTHROPIC_BASE_URL") or provider.api_base
    if not api_base:
        click.echo("  No API base URL configured.", err=True)
        raise SystemExit(1)

    # Try to reach the endpoint
    import urllib.request
    import urllib.error
    models_url = api_base.rstrip("/") + "/models"
    try:
        req = urllib.request.Request(models_url)
        api_key = env.get("OPENAI_API_KEY") or env.get("ANTHROPIC_API_KEY")
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            click.echo(f"  Connected to {models_url} (HTTP {resp.status})")
    except urllib.error.URLError as e:
        click.echo(f"  Failed to connect to {models_url}: {e.reason}", err=True)
        raise SystemExit(1)
    except Exception as e:
        click.echo(f"  Error: {e}", err=True)
        raise SystemExit(1)

    click.echo("  Provider is reachable.")
