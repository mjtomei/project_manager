"""Provider management CLI commands."""

import click

from pm_core.cli import cli
from pm_core.model_config import EFFORT_LEVELS


@cli.group("provider")
def provider_group():
    """Manage LLM providers for Claude sessions.

    Configure local LLM providers (Ollama, vLLM, llama.cpp) as alternatives
    to the default Claude API.  Providers are stored in ~/.pm/providers.yaml.
    """


@provider_group.command("list")
def provider_list():
    """List all configured providers."""
    from pm_core.providers import (
        get_default_provider, invalid_provider_entries, list_providers,
        providers_file_problem,
    )

    default = get_default_provider()
    providers = list_providers()

    for p in providers:
        marker = " (default)" if p.name == default else ""
        if p.type == "claude" and not p.api_base:
            click.echo(f"  {p.name}{marker}  [built-in]")
        elif p.type == "router":
            effort = f"  effort={p.effort}" if p.effort else ""
            click.echo(f"  {p.name}{marker}  type=router  api_base={p.api_base}"
                       f"  model={p.model or '(unset)'}{effort}")
            for line in _router_detail_lines(p):
                click.echo(f"    {line}")
        else:
            model_str = f"  model={p.model}" if p.model else ""
            if p.effort:
                model_str += f"  effort={p.effort}"
            click.echo(f"  {p.name}{marker}  type={p.type}  api_base={p.api_base}{model_str}")
            if p.capabilities:
                click.echo(f"    capabilities: {', '.join(p.capabilities)}")
    for name, problem in invalid_provider_entries().items():
        click.echo(f"  {name}  INVALID ENTRY: {problem}")
    for line in _retired_key_lines():
        click.echo(f"  {line}")
    problem = providers_file_problem()
    if problem:  # read as no providers: say why rather than list nothing
        click.echo(f"  NOT READ: {problem}; fix it by hand")


def _retired_key_lines(name: str | None = None) -> list[str]:
    """Warnings for providers.yaml entries that still set keys pm ignores."""
    from pm_core.providers import _provider_entries, retired_keys
    lines = []
    for pname, entry in _provider_entries().items():
        if name is not None and pname != name:
            continue
        keys = retired_keys(entry)
        if keys:
            lines.append(
                f"{pname}: ignoring {', '.join(keys)} (pm no longer checks or "
                "refreshes credentials; manage them outside pm, remove with "
                f"'pm provider edit {pname} "
                + " ".join(f"--clear {k}" for k in keys) + "')")
    return lines


def _router_detail_lines(p) -> list[str]:
    """Credential-free details of a router provider (paths, never contents)."""
    lines = [f"launcher: {p.launcher or 'claude'}"
             " (host sessions; containers run claude through the route "
             "bridge)"]
    if p.remedy:
        lines.append(f"remedy: {p.remedy}")
    from pm_core.providers import AUTO_MODE_MODEL_ENV
    classifier = p.env_vars().get(AUTO_MODE_MODEL_ENV)
    lines.append("auto-mode classifier: "
                 + (classifier or "not set (Claude picks it; set one with "
                    f"'pm provider edit {p.name} --classifier-model <model>')"))
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


def _load_for_edit() -> dict:
    """providers.yaml to change; exits with an Error line when pm cannot
    read it (it is then left as it is, never overwritten)."""
    from pm_core.providers import ProvidersFileError, load_providers_for_edit
    try:
        return load_providers_for_edit()
    except ProvidersFileError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)


# Options shared by ``add`` and ``edit``: every providers.yaml field except
# type and name.  ``edit`` leaves a field alone when its option is absent.
_FIELD_OPTIONS = [
    click.option("--api-base", default=None,
                 help="API base URL; for a router, where it listens "
                      "(Claude gets it as ANTHROPIC_BASE_URL)"),
    click.option("--api-key", default=None,
                 help="API key (or ${ENV_VAR} reference); not for routers"),
    click.option("--model", default=None, help="Model name"),
    click.option("--effort", default=None,
                 type=click.Choice(list(EFFORT_LEVELS)),
                 help="Default effort for sessions on this provider (a PR's "
                      "own effort setting wins)"),
    click.option("--capabilities", default=None,
                 help="Comma-separated capability tags"),
    click.option("--launcher", default=None,
                 help="router: host executable used instead of claude"),
    click.option("--remedy", default=None,
                 help="router: hint shown when 'pm provider test' or "
                      "'show' finds the router down"),
    click.option("--classifier-model", default=None,
                 help="router: model for Claude Code's auto-mode "
                      "permission classifier"),
    click.option("--env", "env_set", multiple=True, metavar="VAR=VALUE",
                 help="Extra environment variable (repeatable)"),
    click.option("--drop-env", multiple=True, metavar="VAR",
                 help="Remove a variable the provider type sets by default "
                      "(repeatable)"),
    click.option("--unset-env", multiple=True, metavar="VAR",
                 help="router: variables removed from its sessions "
                      "(repeatable; replaces the default "
                      "ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN)"),
    click.option("--probe-model", multiple=True,
                 help="router: model name the backend may report to "
                      "'pm provider test --live' (repeatable)"),
]

_LIST_FIELDS = {"capabilities", "unset_env", "probe_models"}
_CLEARABLE = ("api_key", "model", "effort", "capabilities", "launcher",
              "remedy", "classifier_model", "env", "unset_env",
              "probe_models", "alias_models",
              # retired keys pm ignores (providers.RETIRED_PROVIDER_KEYS)
              "credentials_file", "refresh_command")


def _field_options(f):
    for opt in reversed(_FIELD_OPTIONS):
        f = opt(f)
    return f


def _apply_fields(entry: dict, opts: dict) -> None:
    """Write the given option values into a providers.yaml *entry*."""
    for key in ("api_base", "api_key", "model", "effort", "launcher",
                "remedy", "classifier_model"):
        if opts.get(key) is not None:
            entry[key] = opts[key]
    if opts.get("capabilities") is not None:
        entry["capabilities"] = [c.strip() for c in
                                 opts["capabilities"].split(",") if c.strip()]
    env = dict(entry.get("env") or {})
    for item in opts.get("env_set") or ():
        var, sep, value = item.partition("=")
        if not sep or not var:
            raise click.BadParameter(f"{item!r} is not VAR=VALUE",
                                     param_hint="--env")
        env[var] = value
    for var in opts.get("drop_env") or ():
        env[var] = None
    if env:
        entry["env"] = env
    if opts.get("unset_env"):
        entry["unset_env"] = list(opts["unset_env"])
    if opts.get("probe_model"):
        entry["probe_models"] = list(opts["probe_model"])


def _check_entry(name: str, entry: dict) -> None:
    from pm_core.providers import _entry_problem
    problem = _entry_problem(entry)
    if entry.get("type") == "router":
        if entry.get("api_key"):
            problem = ("a router holds its own credentials; --api-key is not "
                       "used for router providers")
        elif not entry.get("model"):
            problem = ("--model is required for a router provider (the model "
                       "name as the router expects it)")
        elif not entry.get("api_base"):
            problem = "--api-base is required for a router provider"
    if problem:
        click.echo(f"Error: provider {name!r}: {problem}", err=True)
        raise SystemExit(1)


@provider_group.command("add")
@click.argument("name")
@click.option("--type", "ptype", default="local",
              type=click.Choice(["local", "openai", "claude", "router"]),
              help="Provider type: local (Ollama/llama.cpp, recommended), "
                   "openai (OpenAI-compatible), claude (Anthropic API), "
                   "router (a host-local Anthropic-compatible endpoint that "
                   "holds its own credentials)")
@_field_options
@click.option("--skip-check", is_flag=True, help="Skip connectivity and tool-use checks")
def provider_add(name: str, ptype: str, skip_check: bool, **opts):
    """Add a new LLM provider.

    Automatically tests connectivity and tool-use support before adding.
    If issues are found, you'll be prompted to confirm.

    The default type is 'local' which uses the Anthropic-compatible API
    that Ollama 0.14+ and LM Studio 0.4.1+ support natively.

    Select a provider for sessions with 'pm model set <type>
    provider:<name>' (project/global) or 'pm pr model set <pr>
    provider:<name>' (one PR).

    \b
    Examples:
      pm provider add ollama --api-base http://localhost:11434 --model qwen3.5
      pm provider add llama-cpp --api-base http://localhost:8001 --model glm-4.7-flash
      pm provider add vllm --type openai --api-base http://localhost:8000/v1 --model codellama
      pm provider add my-router --type router --api-base http://127.0.0.1:<port> \\
          --model <model as the router names it> --effort high
    """
    from pm_core.providers import (_config_to_provider, check_provider,
                                   providers_lock, save_providers)

    if not opts.get("api_base"):
        click.echo("Error: --api-base is required.", err=True)
        raise SystemExit(1)
    entry: dict = {"type": ptype}
    _apply_fields(entry, opts)
    _check_entry(name, entry)
    if ptype == "router":
        skip_check = True  # checked by 'pm provider test' instead

    config = _load_for_edit()  # before the check, which may prompt

    if not skip_check:
        click.echo(f"Checking provider '{name}'...")
        result = check_provider(_config_to_provider(name, entry))
        _display_test_result(result)

        if result.warnings:
            click.echo()
            for warning in result.warnings:
                click.echo(f"  Warning: {warning}", err=True)
            click.echo()
            if not click.confirm("Add this provider anyway?"):
                click.echo("Aborted.")
                raise SystemExit(1)

    with providers_lock():  # re-read: another edit may have saved meanwhile
        config = _load_for_edit()
        config["providers"][name] = entry
        save_providers(config)
    click.echo(f"Added provider '{name}' ({ptype}: {entry['api_base']})")


@provider_group.command("edit")
@click.argument("name")
@click.option("--type", "ptype", default=None,
              type=click.Choice(["local", "openai", "claude", "router"]),
              help="Change the provider type")
@_field_options
@click.option("--clear", "clear", multiple=True,
              type=click.Choice(_CLEARABLE),
              help="Remove a field (repeatable)")
def provider_edit(name: str, ptype: str | None, clear: tuple, **opts):
    """Change fields of a configured provider.

    Only the given options change; the rest of the entry is kept.

    \b
    Examples:
      pm provider edit my-router --effort high
      pm provider edit my-router --classifier-model <model>
      pm provider edit my-router --clear launcher
    """
    from pm_core.providers import providers_lock, save_providers

    with providers_lock():
        config = _load_for_edit()
        entry = config["providers"].get(name)
        if not isinstance(entry, dict):
            click.echo(f"Error: provider {name!r} is not configured (add it "
                       f"with 'pm provider add {name} ...')", err=True)
            raise SystemExit(1)
        entry = dict(entry)
        for key in clear:
            entry.pop(key, None)
        if ptype:
            entry["type"] = ptype
        _apply_fields(entry, opts)
        _check_entry(name, entry)
        config["providers"][name] = entry
        save_providers(config)
    click.echo(f"Updated provider '{name}'")
    _echo_provider(name)


@provider_group.command("show")
@click.argument("name")
def provider_show(name: str):
    """Show one provider: its settings, launch environment and status.

    Secrets are never printed: an API key shows as its ${VAR} reference
    or 'set'.
    """
    _echo_provider(name, status=True)


def _echo_provider(name: str, status: bool = False) -> None:
    from pm_core.providers import ProviderNotFoundError, get_provider
    try:
        p = get_provider(name, strict=True)
    except ProviderNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    for line in provider_detail_lines(p, status=status):
        click.echo(line)


def provider_detail_lines(p, *, status: bool = False) -> list[str]:
    """Credential-free description of provider *p* (also used by the TUI)."""
    from pm_core.providers import (BUILTIN_CLAUDE, get_default_provider,
                                   is_secret_env_var, launch_env)
    default = " (default)" if p.name == get_default_provider() else ""
    lines = [f"{p.name}{default}  type={p.type}"]
    if p.name == BUILTIN_CLAUDE and not p.api_base:
        lines.append("  built-in: plain claude with its own sign-in")
        return lines
    key = ("" if not p.api_key else p.api_key if p.api_key.startswith("${")
           else "set")
    for label, value in (("api_base", p.api_base), ("api_key", key),
                         ("model", p.model), ("effort", p.effort),
                         ("capabilities", ", ".join(p.capabilities)),
                         ("probe_models", ", ".join(p.probe_models))):
        if value:
            lines.append(f"  {label}: {value}")
    if p.type == "router":
        lines.extend(f"  {line}" for line in _router_detail_lines(p))
    assign, unset = launch_env(p, p.env_vars(), p.model_flag(), environ={})
    if assign:
        lines.append("  launch env:")
        for var, value in assign.items():
            secret = is_secret_env_var(var) and value
            lines.append(f"    {var}={'<redacted>' if secret else value}")
    if unset:
        lines.append(f"  launch unsets: {', '.join(unset)}")
    lines.extend(f"  warning: {line}" for line in _retired_key_lines(p.name))
    if status and p.type == "router":
        from pm_core import router_route
        from pm_core.model_config import ModelResolution
        st = router_route.check_route(ModelResolution(provider=p.name))
        lines.append("  status: OK" if st.ok else f"  status: {st.message()}")
    return lines


@provider_group.command("remove")
@click.argument("name")
def provider_remove(name: str):
    """Remove a configured provider."""
    from pm_core.providers import providers_lock, save_providers

    if name == "claude":
        click.echo("Cannot remove the built-in 'claude' provider.", err=True)
        raise SystemExit(1)

    with providers_lock():
        config = _load_for_edit()
        providers = config["providers"]
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
    from pm_core.providers import set_default_provider

    config = _load_for_edit()
    if name != "claude":
        if name not in config["providers"]:
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

    For a router provider, runs the same preflight pm runs before every
    routed launch (router port, launcher, and with --container the bridge
    into a container); --live sends one prompt.
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
    from pm_core import router_route
    from pm_core.model_config import ModelResolution

    click.echo(f"  Router: {provider.api_base}  model: {provider.model}")
    for line in _router_detail_lines(provider):
        click.echo(f"  {line}")
    res = ModelResolution(provider=provider.name)
    st = router_route.check_route(res, container=in_container)
    if not st.ok:
        click.echo(f"  Preflight: FAILED — {st.message()}", err=True)
        raise SystemExit(1)
    click.echo("  Preflight (host): OK")
    if not in_container:
        if live:
            _report_probe(router_route.live_probe(provider), provider)
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
            extra_rw_mounts=router_route.container_mounts(res))
        st = router_route.check_route(res, container=True,
                                      container_name=name)
        if not st.ok:
            click.echo(f"  Container route: FAILED — {st.message()}", err=True)
            raise SystemExit(1)
        click.echo(f"  Container route: OK (127.0.0.1 in {name} -> "
                   f"{router_route.bridge_socket(provider.name)} -> "
                   f"{provider.api_base})")
        if live:
            _report_probe(router_route.live_probe(provider,
                                                  container_name=name),
                          provider)
    finally:
        container_mod.remove_container(name)
        shutil.rmtree(workdir, ignore_errors=True)


def _probe_mismatch(out: dict, provider) -> str:
    """Why a probe that reported no error failed, naming the models."""
    from pm_core.router_route import model_on_route
    requested = out.get("models") or []
    if not requested:
        return f"no model requested; expected only {provider.model}"
    off = [m for m in requested if m != provider.model]
    if off:
        return (f"model mismatch: Claude requested {', '.join(off)}; "
                f"expected only {provider.model}")
    off = [m for m in out.get("transcript_models") or []
           if not model_on_route(provider, m)]
    if off:
        return (f"model mismatch: the transcript records {', '.join(off)}; "
                f"expected {provider.model} or a probe model "
                f"({', '.join(provider.probe_models)})")
    return (f"live prompt failed (exit={out.get('exit')} "
            f"reply={out.get('result')!r})")


def _report_probe(out: dict, provider) -> None:
    click.echo(f"  Live prompt: exit={out.get('exit')} "
               f"reply={out.get('result')!r}")
    click.echo(f"  Models requested: {', '.join(out.get('models') or []) or '(none)'}")
    click.echo(f"  Transcript: {out.get('transcript') or '(none)'} "
               f"models={', '.join(out.get('transcript_models') or []) or '(none)'}")
    click.echo(f"  Hook event: {out.get('hook_event') or '(none)'}")
    if not out.get("ok"):
        why = out.get("error") or _probe_mismatch(out, provider)
        click.echo(f"  Live: FAILED — {why}", err=True)
        raise SystemExit(1)
    click.echo("  Live: OK")
