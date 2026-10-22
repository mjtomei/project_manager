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
        elif p.type == "router":
            click.echo(f"  {p.name}{marker}  type=router  api_base={p.api_base}"
                       f"  model={p.model or '(unset)'}")
            for line in _router_detail_lines(p):
                click.echo(f"    {line}")
        else:
            model_str = f"  model={p.model}" if p.model else ""
            click.echo(f"  {p.name}{marker}  type={p.type}  api_base={p.api_base}{model_str}")
            if p.capabilities:
                click.echo(f"    capabilities: {', '.join(p.capabilities)}")


def _router_detail_lines(p) -> list[str]:
    """Credential-free details of a router provider (paths, never contents)."""
    lines = [f"launcher: {p.launcher or 'claude (with ANTHROPIC_BASE_URL)'}"
             " (host workers; containers use the route bridge)"]
    if p.credentials_file:
        from pm_core import worker_route
        try:
            exp = worker_route.credentials_expiry(p.credentials_file)
            state = ("expiry unknown" if exp is None else
                     f"expires {worker_route._fmt_time(exp)}")
        except FileNotFoundError:
            state = "MISSING"
        lines.append(f"credentials file: {p.credentials_file} ({state})")
    if p.refresh_command:
        lines.append(f"refresh command: {p.refresh_command}")
    return lines


def _display_test_result(result) -> None:
    """Print test result details to the terminal."""
    if result.reachable:
        click.echo(f"  Connectivity: OK ({result.reachable_detail})")
    else:
        click.echo(f"  Connectivity: FAILED ({result.reachable_detail})", err=True)

    if result.context_window is not None:
        from pm_core.providers import MIN_CONTEXT_TOKENS
        if result.context_window >= MIN_CONTEXT_TOKENS:
            click.echo(f"  Context window: OK ({result.context_window:,} tokens)")
        else:
            click.echo(
                f"  Context window: TOO SMALL ({result.context_window:,} tokens, "
                f"need {MIN_CONTEXT_TOKENS:,}+)",
                err=True,
            )

    if result.tool_use is True:
        click.echo(f"  Tool use: OK ({result.tool_use_detail})")
    elif result.tool_use is False:
        click.echo(f"  Tool use: FAILED ({result.tool_use_detail})", err=True)


@provider_group.command("add")
@click.argument("name")
@click.option("--type", "ptype", default="local",
              type=click.Choice(["local", "openai", "claude", "router"]),
              help="Provider type: local (Ollama/llama.cpp, recommended), "
                   "openai (OpenAI-compatible), claude (Anthropic API), "
                   "router (host account router such as claude-mixed's)")
@click.option("--api-base", required=True, help="API base URL (e.g. http://localhost:11434/v1)")
@click.option("--api-key", default="", help="API key (or ${ENV_VAR} reference)")
@click.option("--model", default="", help="Model name")
@click.option("--capabilities", default="", help="Comma-separated capability tags")
@click.option("--skip-check", is_flag=True, help="Skip connectivity and tool-use checks")
@click.option("--launcher", default="",
              help="router: host executable used instead of claude")
@click.option("--credentials-file", default="",
              help="router: credentials.json whose expiresAt is checked "
                   "before launches (only the expiry is read)")
@click.option("--refresh-command", default="",
              help="router: command run once when those credentials expired")
def provider_add(name: str, ptype: str, api_base: str, api_key: str,
                 model: str, capabilities: str, skip_check: bool,
                 launcher: str, credentials_file: str, refresh_command: str):
    """Add a new LLM provider.

    Automatically tests connectivity and tool-use support before adding.
    If issues are found, you'll be prompted to confirm.

    The default type is 'local' which uses the Anthropic-compatible API
    that Ollama 0.14+ and LM Studio 0.4.1+ support natively.

    \b
    Examples:
      pm provider add ollama --api-base http://localhost:11434 --model qwen3.5
      pm provider add llama-cpp --api-base http://localhost:8001 --model glm-4.7-flash
      pm provider add vllm --type openai --api-base http://localhost:8000/v1 --model codellama
      pm provider add claude-work --type router --api-base http://127.0.0.1:8790 \\
          --model work/claude-opus-5-5 \\
          --credentials-file ~/.claude-work/.credentials.json
    """
    from pm_core.providers import (
        ProviderConfig, load_providers, save_providers, check_provider,
    )

    # Build a temporary ProviderConfig to test before saving
    caps = [c.strip() for c in capabilities.split(",")] if capabilities else []
    provider = ProviderConfig(
        name=name, type=ptype, api_base=api_base,
        api_key=api_key, model=model, capabilities=caps,
    )

    if ptype == "router":
        if api_key:
            click.echo("A router holds its own credentials; --api-key is not "
                       "used for router providers.", err=True)
            raise SystemExit(1)
        if not model:
            click.echo("--model is required for a router provider "
                       "(e.g. work/claude-opus-5-5).", err=True)
            raise SystemExit(1)
        skip_check = True  # checked by 'pm provider test' instead

    if not skip_check:
        click.echo(f"Checking provider '{name}'...")
        result = check_provider(provider)
        _display_test_result(result)

        if result.warnings:
            click.echo()
            for warning in result.warnings:
                click.echo(f"  Warning: {warning}", err=True)
            click.echo()
            if not click.confirm("Add this provider anyway?"):
                click.echo("Aborted.")
                raise SystemExit(1)

    config = load_providers()
    if "providers" not in config:
        config["providers"] = {}

    entry: dict = {"type": ptype, "api_base": api_base}
    if api_key:
        entry["api_key"] = api_key
    if model:
        entry["model"] = model
    if caps:
        entry["capabilities"] = caps
    for key, val in (("launcher", launcher),
                     ("credentials_file", credentials_file),
                     ("refresh_command", refresh_command)):
        if val:
            entry[key] = val

    config["providers"][name] = entry
    save_providers(config)
    click.echo(f"Added provider '{name}' ({ptype}: {api_base})")


@provider_group.command("remove")
@click.argument("name")
def provider_remove(name: str):
    """Remove a configured provider."""
    from pm_core.providers import load_providers, save_providers

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
@click.option("--quick", is_flag=True, help="Only test connectivity, skip tool-use check")
@click.option("--container", "in_container", is_flag=True,
              help="router: test the route from a throwaway pm container")
@click.option("--live", is_flag=True,
              help="router: also send a harmless tools-disabled prompt "
                   "through the route and check the model used")
def provider_test(name: str | None, quick: bool, in_container: bool,
                  live: bool):
    """Test connectivity and tool-use support for a provider.

    Checks that the endpoint is reachable and that the model can handle
    function calling (required for Claude Code's agentic workflows).
    If NAME is omitted, tests the default provider.

    For a router provider, runs the same preflight QA runs before every
    routed launch (router port, credential expiry, launcher, and with
    --container the bridge into a container); --live sends one prompt.
    """
    from pm_core.providers import (
        get_provider, check_provider, ProviderNotFoundError,
    )

    try:
        provider = get_provider(name, strict=bool(name))
    except ProviderNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    click.echo(f"Testing provider '{provider.name}' (type={provider.type})...")

    if provider.type == "router":
        _test_router(provider, in_container=in_container, live=live)
        return

    if provider.type == "claude" and not provider.api_base:
        click.echo("  Built-in Claude provider — no endpoint to test.")
        click.echo("  Use 'claude --version' to verify the CLI is installed.")
        return

    result = check_provider(provider, check_tools=not quick)
    _display_test_result(result)

    if not result.reachable:
        raise SystemExit(1)

    if result.tool_use is None and provider.type == "openai" and not provider.model:
        click.echo("  Tool use: SKIPPED (no model configured)")
    elif result.tool_use is False:
        click.echo()
        for warning in result.warnings:
            click.echo(f"  {warning}", err=True)


def _test_router(provider, *, in_container: bool, live: bool) -> None:
    from pm_core import worker_route
    from pm_core.model_config import ModelResolution

    click.echo(f"  Router: {provider.api_base}  model: {provider.model}")
    for line in _router_detail_lines(provider):
        click.echo(f"  {line}")
    res = ModelResolution(provider=provider.name)
    st = worker_route.check_route(res, container=in_container)
    if not st.ok:
        click.echo(f"  Preflight: FAILED — {st.message()}", err=True)
        raise SystemExit(1)
    click.echo("  Preflight (host): OK")
    if not in_container:
        if live:
            _report_probe(worker_route.live_probe(provider), provider)
        return

    import secrets
    import shutil
    import tempfile
    from pathlib import Path
    from pm_core import container as container_mod
    name = f"pm-route-test-{secrets.token_hex(4)}"
    workdir = Path(tempfile.mkdtemp(prefix="pm-route-test-"))
    click.echo(f"  Creating throwaway container {name}...")
    try:
        container_mod.create_container(
            name=name, config=container_mod.load_container_config(),
            workdir=workdir,
            extra_rw_mounts=worker_route.container_mounts(res))
        st = worker_route.check_route(res, container=True,
                                      container_name=name)
        if not st.ok:
            click.echo(f"  Container route: FAILED — {st.message()}", err=True)
            raise SystemExit(1)
        click.echo(f"  Container route: OK (127.0.0.1 in {name} -> "
                   f"{worker_route.bridge_socket(provider.name)} -> "
                   f"{provider.api_base})")
        if live:
            _report_probe(worker_route.live_probe(provider,
                                                  container_name=name),
                          provider)
    finally:
        container_mod.remove_container(name)
        shutil.rmtree(workdir, ignore_errors=True)


def _report_probe(out: dict, provider) -> None:
    click.echo(f"  Live prompt: exit={out.get('exit')} "
               f"reply={out.get('result')!r}")
    click.echo(f"  Models requested: {', '.join(out.get('models') or []) or '(none)'}")
    click.echo(f"  Transcript: {out.get('transcript') or '(none)'} "
               f"models={', '.join(out.get('transcript_models') or []) or '(none)'}")
    click.echo(f"  Hook event: {out.get('hook_event') or '(none)'}")
    if not out.get("ok"):
        why = out.get("error") or (f"model mismatch; expected only "
                                   f"{provider.model}")
        click.echo(f"  Live: FAILED — {why}", err=True)
        raise SystemExit(1)
    click.echo("  Live: OK")
