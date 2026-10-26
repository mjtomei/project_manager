"""LLM provider configuration for pm sessions.

Supports multiple provider types:
  - claude: Default Anthropic Claude API (no extra config needed)
  - local: Local model via Anthropic-compatible API (Ollama 0.14+,
    LM Studio 0.4.1+, llama.cpp).  Recommended for local models.
  - openai: OpenAI-compatible API endpoint (vLLM, etc.).
    Use only if your server doesn't speak the Anthropic Messages API.
  - router: A host-local Anthropic-compatible router (e.g. the claude-mixed
    router) that picks the upstream account from a model prefix such as
    ``work/``.  Credentials stay with the router; pm only points Claude at
    it.  See pm_core/worker_route.py.

Configuration is stored in ~/.pm/providers.yaml:

    providers:
      ollama:
        type: local
        api_base: http://localhost:11434
        model: qwen3.5
        capabilities: [code, review]

      vllm:
        type: openai
        api_base: http://localhost:8000/v1
        model: codellama

      claude-work:
        type: router
        api_base: http://127.0.0.1:8790
        model: work/claude-opus-5-5
        launcher: ~/.local/bin/claude-mixed   # optional, host workers only
        credentials_file: ~/.claude-work/.credentials.json  # expiry check
        refresh_command: claude-work-ping              # optional

    default: claude

Provider resolution order:
  1. Explicit --provider flag
  2. PM_PROVIDER environment variable
  3. Per-session provider setting (~/.pm/sessions/{tag}/provider)
  4. Default from providers.yaml
  5. Falls back to "claude" (built-in, no config needed)
"""

import os
from dataclasses import dataclass, field
from typing import Any

from pm_core.paths import configure_logger, pm_home, session_dir

_log = configure_logger("pm.providers")

PROVIDERS_FILE = "providers.yaml"

# Built-in provider that requires no configuration
BUILTIN_CLAUDE = "claude"

PROVIDER_TYPES = ("local", "openai", "claude", "router")

# Claude Code env vars that pick the model for aliases, background calls and
# subagents.  A router provider pins them all to its model by default.  The
# fable alias is what a skill's or slash command's ``model: fable``
# frontmatter and the /model picker's Fable entry switch the main loop to.
ROUTER_ALIAS_ENV_VARS = (
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
)


# Pin every subagent to one model.  CLAUDE_CODE_SUBAGENT_MODEL alone is only
# a default (Claude Code >= 2.1.251): an Agent call's ``model`` parameter or
# an agent definition's ``model`` frontmatter still wins, and the built-in
# Explore/Plan agents ignore it.  FORCE (>= 2.1.257) makes it override all
# of those -- without it a child asking for e.g. ``fable`` leaves the
# session's route and runs on the caller's own account.
SUBAGENT_MODEL_ENV = "CLAUDE_CODE_SUBAGENT_MODEL"
SUBAGENT_FORCE_ENV = "CLAUDE_CODE_SUBAGENT_MODEL_FORCE"

# Auto permission mode's classifier picks its own model: it refuses an
# Opus-class or Sonnet 5.5 ANTHROPIC_DEFAULT_SONNET_MODEL (and the same in
# CLAUDE_CODE_AUTO_MODE_MODEL) and falls back to its Sonnet 5 default, sent
# without a route prefix -- on the router, to the main account.  A router
# session therefore sends that default through its route.
AUTO_MODE_MODEL_ENV = "CLAUDE_CODE_AUTO_MODE_MODEL"
CLASSIFIER_DEFAULT_MODEL = "claude-sonnet-5"


def route_classifier_model(model: str | None) -> str | None:
    """The auto-mode classifier model for a router session on *model*.

    Claude Code's own classifier default under the route's prefix
    (``work/claude-opus-5-5[1m]`` -> ``work/claude-sonnet-5``).  None for a
    model without a prefix: the router sends it, and so the default
    classifier, to the same backend.  None too when the route does not
    serve Claude models (``deepseek/…``, ``z-ai/…``, ``chatgpt/…``): such a
    prefix names another vendor's models, so ``<prefix>/claude-sonnet-5``
    would be a model no backend has, and the classifier is left to Claude.
    """
    if not model or "/" not in model:
        return None
    prefix, name = model.split("/", 1)
    if not name.startswith("claude-"):
        return None
    return f"{prefix}/{CLASSIFIER_DEFAULT_MODEL}"


def subagent_pin_env(model: str | None,
                     provider: "ProviderConfig | None" = None) -> dict[str, str]:
    """Env that runs every subagent of a session on *model*.

    *model* is the session's effective ``--model`` value, kept verbatim
    (route prefix such as ``work/`` and context suffix such as ``[1m]``
    included).  A router provider's explicit ``alias_models`` entry for
    CLAUDE_CODE_SUBAGENT_MODEL takes its place.  Empty when pm selected no
    model: the session then runs on the CLI default and pm has nothing to
    enforce.
    """
    if not model:
        return {}
    pinned = ((provider.alias_models.get(SUBAGENT_MODEL_ENV)
               if provider is not None else None) or model)
    return {SUBAGENT_MODEL_ENV: pinned, SUBAGENT_FORCE_ENV: "1"}


# Set by a routed launch next to ANTHROPIC_BASE_URL, naming the URL pm put
# there, so a pm process started inside that session knows the inherited
# ANTHROPIC_BASE_URL is a route's and not the user's own.
ROUTE_BASE_URL_ENV = "PM_ROUTE_BASE_URL"

# The model-routing variables pm decides on every launch.  A launch sets the
# ones its selection needs and removes the others, so nothing a caller's
# environment carries (pm run inside a routed session exports all of them)
# picks a model or account for it.  ANTHROPIC_BASE_URL is removed only when
# it is a route's (_is_route_base_url): any other value is the user's own
# endpoint and stays.
LAUNCH_ROUTING_ENV_VARS = (*ROUTER_ALIAS_ENV_VARS, SUBAGENT_FORCE_ENV,
                           AUTO_MODE_MODEL_ENV, ROUTE_BASE_URL_ENV)


def _is_route_base_url(url: str | None, environ) -> bool:
    """Whether an inherited ANTHROPIC_BASE_URL is a route's.

    It is when it is the URL a routed launch recorded (ROUTE_BASE_URL_ENV),
    or the address of a router configured here, on the host or as its
    in-container forwarder (a session started before that marker existed,
    or by the host claude-mixed launcher).
    """
    if not url:
        return False
    url = url.rstrip("/")
    if url == (environ.get(ROUTE_BASE_URL_ENV) or "").rstrip("/"):
        return True
    from pm_core import worker_route
    for p in list_providers():
        if p.type != "router" or not p.api_base:
            continue
        try:
            urls = {p.api_base, worker_route.container_base_url(p)}
        except ValueError:
            urls = {p.api_base}
        if url in {u.rstrip("/") for u in urls}:
            return True
    return False


def launch_env(provider: "ProviderConfig", env: dict[str, str],
               model: str | None, environ=None,
               ) -> tuple[dict[str, str], tuple[str, ...]]:
    """``(assign, unset)``: the environment of one launch.

    *env* is what the selected *provider* contributes (its ``env_vars()``,
    or a router's container variant) and *model* the session's effective
    ``--model`` (None: the CLI default).  pm's own selection decides every
    LAUNCH_ROUTING_ENV_VARS entry: the subagent pin follows *model*, a
    routed launch records its URL, and every routing variable the
    selection does not set is unset rather than inherited from *environ*
    (the caller's environment, default ``os.environ``).  So are the
    provider's own unset_env_vars and an inherited route ANTHROPIC_BASE_URL
    when the selection names none.  Everything else is left as it is.
    """
    environ = os.environ if environ is None else environ
    assign = {**env, **subagent_pin_env(model, provider)}
    if provider.type == "router" and assign.get("ANTHROPIC_BASE_URL"):
        assign[ROUTE_BASE_URL_ENV] = assign["ANTHROPIC_BASE_URL"]
    unset = [*provider.unset_env_vars(), *LAUNCH_ROUTING_ENV_VARS]
    if ("ANTHROPIC_BASE_URL" not in assign
            and _is_route_base_url(environ.get("ANTHROPIC_BASE_URL"), environ)):
        unset.append("ANTHROPIC_BASE_URL")
    return assign, tuple(dict.fromkeys(v for v in unset if v not in assign))


class ProviderNotFoundError(LookupError):
    """An explicitly named provider is not configured in providers.yaml."""


# The other way out of a ProviderNotFoundError (its message names the
# first: adding the provider), quoted where a launch reports one.
PROVIDER_SETTING_HINT = ("or change the model setting that selects it "
                         "('pm model show' lists them, PR overrides included)")


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider.

    Provider types:
      - claude: Default Anthropic Claude API (no extra config needed)
      - local: Local model via Anthropic-compatible API (Ollama 0.14+,
        LM Studio 0.4.1+, llama.cpp).  Uses ANTHROPIC_BASE_URL.
        This is the recommended approach for local models.
      - openai: OpenAI-compatible API endpoint (vLLM, older Ollama, etc.).
        Uses OPENAI_BASE_URL with --model openai:name prefix.  Use this
        only if your server doesn't speak the Anthropic Messages API.
      - router: host-local account router (claude-mixed).  Uses
        ANTHROPIC_BASE_URL only; the router holds the credentials.  The
        router-only fields (launcher, credentials_file, refresh_command,
        remedy, alias_models) are consumed by pm_core.worker_route and
        claude_launcher.
    """
    name: str
    type: str = "claude"  # "claude", "local", "openai", or "router"
    api_base: str = ""
    api_key: str = ""
    model: str = ""
    capabilities: list[str] = field(default_factory=list)
    # router-only
    launcher: str = ""
    credentials_file: str = ""
    refresh_command: str = ""
    remedy: str = ""
    alias_models: dict[str, str] = field(default_factory=dict)

    def env_vars(self) -> dict[str, str]:
        """Return environment variables needed to use this provider."""
        if self.type == "router":
            # Never an API key or token: the router injects the account's
            # credentials itself.  Pin Claude Code's alias/background
            # models to the route so no request falls through to the
            # caller's own account.
            env = {}
            if self.api_base:
                env["ANTHROPIC_BASE_URL"] = self.api_base
            # Routed ids (work/...) are not names Claude Code knows; without
            # this it refuses them on context-window grounds (as claude-mixed
            # does).
            env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] = "1"
            if self.model:
                for var in ROUTER_ALIAS_ENV_VARS:
                    env[var] = self.model
            classifier = route_classifier_model(self.model)
            if classifier:
                env[AUTO_MODE_MODEL_ENV] = classifier
            for var, value in self.alias_models.items():
                env[var] = value
            if self.model:
                env[SUBAGENT_FORCE_ENV] = "1"
            return env

        if self.type in ("claude", "local"):
            env: dict[str, str] = {}
            if self.api_base:
                env["ANTHROPIC_BASE_URL"] = self.api_base
            if self.api_key:
                env["ANTHROPIC_API_KEY"] = _resolve_env_ref(self.api_key)
            elif self.type == "local":
                # Local servers typically don't need a real key
                env["ANTHROPIC_API_KEY"] = ""
                env["ANTHROPIC_AUTH_TOKEN"] = "ollama"
            if self.type == "claude" and self.model:
                env["ANTHROPIC_MODEL"] = self.model
            # launch_env unsets every alias a launch does not set, so this
            # is where a provider's own alias models go.
            env.update(self.alias_models)
            return env

        if self.type == "openai":
            env = {}
            if self.api_base:
                env["OPENAI_BASE_URL"] = self.api_base
            if self.api_key:
                env["OPENAI_API_KEY"] = _resolve_env_ref(self.api_key)
            env.update(self.alias_models)
            return env

        return {}

    def unset_env_vars(self) -> tuple[str, ...]:
        """Environment variables to remove for this provider's sessions.

        Only what this provider type removes on top of launch_env's
        routing variables: a router authenticates upstream itself, so a
        stray API key or auth token in the caller's environment would only
        make Claude Code prompt about it (blocking an unattended worker) --
        the same variables the claude-mixed launcher unsets.
        """
        if self.type == "router":
            return ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        return ()

    def model_flag(self) -> str | None:
        """Return the --model flag value for claude CLI, or None."""
        if self.type == "openai" and self.model:
            return f"openai:{self.model}"
        if self.model:
            # local and claude types use model name directly
            return self.model
        return None

    def has_capability(self, cap: str) -> bool:
        """Check if this provider has a specific capability."""
        if not self.capabilities:
            return True  # No restrictions = can do anything
        return cap in self.capabilities


def _resolve_env_ref(value: str) -> str:
    """Resolve ${VAR_NAME} references in config values."""
    if value.startswith("${") and value.endswith("}"):
        var_name = value[2:-1]
        return os.environ.get(var_name, "")
    return value


def _config_to_provider(name: str, entry: dict) -> ProviderConfig:
    """Build a ProviderConfig from a providers.yaml entry."""
    return ProviderConfig(
        name=name,
        type=entry.get("type", "local"),
        api_base=entry.get("api_base", ""),
        api_key=entry.get("api_key", ""),
        model=entry.get("model", ""),
        capabilities=entry.get("capabilities", []),
        launcher=entry.get("launcher", ""),
        credentials_file=entry.get("credentials_file", ""),
        refresh_command=entry.get("refresh_command", ""),
        remedy=entry.get("remedy", ""),
        alias_models=dict(entry.get("alias_models") or {}),
    )


def _providers_path():
    """Return path to ~/.pm/providers.yaml."""
    return pm_home() / PROVIDERS_FILE


def load_providers() -> dict[str, Any]:
    """Load the providers.yaml config file.

    Returns the raw parsed YAML dict, or empty dict if file doesn't exist.
    """
    path = _providers_path()
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text()) or {}
    except Exception as e:
        _log.warning("Failed to load %s: %s", path, e)
        return {}


def save_providers(data: dict[str, Any]) -> None:
    """Write the providers config to ~/.pm/providers.yaml."""
    import yaml
    path = _providers_path()
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
    _log.info("Saved provider config to %s", path)


def get_provider(name: str | None = None, *,
                 strict: bool = False) -> ProviderConfig:
    """Resolve and return a provider configuration.

    Resolution order:
      1. Explicit name parameter
      2. PM_PROVIDER environment variable
      3. Per-session provider setting
      4. Default from providers.yaml
      5. Built-in "claude" provider

    With *strict*, an explicit *name* that is not configured raises
    :class:`ProviderNotFoundError` instead of falling back to the built-in
    claude provider (which would bill the caller's own account).
    """
    # 1. Explicit name
    resolved = name

    # 2. Environment variable
    if not resolved:
        resolved = os.environ.get("PM_PROVIDER")

    # 3. Per-session setting
    if not resolved:
        sd = session_dir()
        if sd:
            provider_file = sd / "provider"
            if provider_file.exists():
                try:
                    resolved = provider_file.read_text().strip()
                except (OSError, IOError):
                    pass

    # Load config once for steps 4-5 and provider lookup
    config = load_providers()

    # 4. Default from config
    if not resolved:
        resolved = config.get("default")

    # 5. Built-in claude
    if not resolved or resolved == BUILTIN_CLAUDE:
        return ProviderConfig(name=BUILTIN_CLAUDE)

    # Look up the named provider in config
    providers = config.get("providers", {})
    if resolved not in providers:
        if strict and name:
            raise ProviderNotFoundError(
                f"provider {name!r} is not configured in {_providers_path()} "
                f"(add it with 'pm provider add {name} ...')")
        _log.warning("Provider %r not found in config, falling back to claude", resolved)
        return ProviderConfig(name=BUILTIN_CLAUDE)

    return _config_to_provider(resolved, providers[resolved])


def list_providers() -> list[ProviderConfig]:
    """List all configured providers (including built-in claude)."""
    result = [ProviderConfig(name=BUILTIN_CLAUDE)]
    config = load_providers()
    for name, entry in config.get("providers", {}).items():
        result.append(_config_to_provider(name, entry))
    return result


def set_session_provider(provider_name: str, session_tag: str | None = None) -> None:
    """Set the provider for the current session."""
    sd = session_dir(session_tag)
    if sd:
        (sd / "provider").write_text(provider_name + "\n")
        _log.info("Set session provider to %r", provider_name)


def get_default_provider() -> str:
    """Get the configured default provider name."""
    config = load_providers()
    return config.get("default", BUILTIN_CLAUDE)


def set_default_provider(name: str) -> None:
    """Set the default provider in providers.yaml."""
    config = load_providers()
    config["default"] = name
    save_providers(config)


# ---------------------------------------------------------------------------
# Recommended models for local tool-use
# ---------------------------------------------------------------------------

@dataclass
class RecommendedModel:
    """A model known to work well with Claude Code's tool-use patterns."""
    name: str
    ollama_tag: str
    param_billions: float
    ram_gb_required: float  # Approximate RAM/VRAM for Q4 quantization
    notes: str


# Models known to work well with Claude Code locally, ordered by size.
# These support tool calling and have sufficient context windows (64k+).
# RAM estimates assume quantized weights via Ollama.
#
# Sources:
#   - https://docs.ollama.com/integrations/claude-code
#   - https://unsloth.ai/docs/basics/claude-code
#   - https://github.com/Alorse/cc-compatible-models
RECOMMENDED_MODELS: list[RecommendedModel] = [
    RecommendedModel(
        name="GLM 4.7 Flash",
        ollama_tag="glm-4.7-flash",
        param_billions=10,
        ram_gb_required=7,
        notes="128k context, tool calling, fast — best for limited hardware",
    ),
    RecommendedModel(
        name="Qwen 3 Coder",
        ollama_tag="qwen3-coder",
        param_billions=15,
        ram_gb_required=10,
        notes="Dedicated coding model, strong tool use",
    ),
    RecommendedModel(
        name="Qwen 3.5 35B-A3B (MoE)",
        ollama_tag="qwen3.5",
        param_billions=35,
        ram_gb_required=24,
        notes="Top pick — strong agentic + coding, MoE so fast",
    ),
    RecommendedModel(
        name="Kimi K2.5",
        ollama_tag="kimi-k2.5",
        param_billions=72,
        ram_gb_required=48,
        notes="Very capable, recommended by Ollama for Claude Code",
    ),
    RecommendedModel(
        name="Qwen 3 Coder Next (MoE)",
        ollama_tag="qwen3-coder-next",
        param_billions=80,
        ram_gb_required=48,
        notes="256k context, specialized for agentic coding workflows",
    ),
]

# Minimum context window for Claude Code (per Ollama docs)
MIN_CONTEXT_TOKENS = 64_000


def _get_system_memory_gb() -> float | None:
    """Detect total system RAM in GB. Returns None if detection fails.

    Works on Linux (/proc/meminfo) and macOS (sysctl hw.memsize).
    On unified memory systems (Apple Silicon, NVIDIA Spark), system RAM
    is the pool available for both CPU and GPU workloads.
    """
    # Linux
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass

    # macOS (Apple Silicon has unified memory — this is the full pool)
    import subprocess
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip()) / (1024 ** 3)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass

    return None


def _get_gpu_memory_gb() -> float | None:
    """Detect total GPU VRAM in GB via nvidia-smi. Returns None if unavailable."""
    import subprocess
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Sum all GPUs, nvidia-smi reports in MiB
            total_mib = sum(int(line.strip()) for line in result.stdout.strip().splitlines())
            return total_mib / 1024
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def get_recommended_models() -> list[tuple[RecommendedModel, bool]]:
    """Return recommended models with a flag indicating if they fit in memory.

    Uses the larger of system RAM and GPU VRAM as the available memory,
    since models can run on either (CPU via RAM or GPU via VRAM).

    Returns:
        List of (model, fits_in_memory) tuples, ordered by size.
    """
    ram = _get_system_memory_gb()
    vram = _get_gpu_memory_gb()

    # Use whichever is larger (user might run on CPU or GPU)
    available = max(ram or 0, vram or 0) or None

    result = []
    for model in RECOMMENDED_MODELS:
        if available is not None:
            fits = available >= model.ram_gb_required
        else:
            fits = True  # Can't detect, assume it fits
        result.append((model, fits))
    return result


def format_model_recommendations() -> str:
    """Format recommended models as a human-readable string.

    Includes memory detection and marks models that won't fit.
    """
    ram = _get_system_memory_gb()
    vram = _get_gpu_memory_gb()
    available = max(ram or 0, vram or 0) or None

    lines = ["  Recommended models for Claude Code (require 64k+ context):"]
    if available is not None:
        if vram and ram and vram > ram:
            mem_source = "GPU VRAM"
        elif vram and ram and abs(vram - ram) < 2:
            mem_source = "unified memory"
        else:
            mem_source = "system RAM"
        lines.append(f"  (detected {available:.0f} GB {mem_source})")
    lines.append("")

    models_with_fit = get_recommended_models()
    for model, fits in models_with_fit:
        marker = "  " if fits else "x "
        fit_note = "" if fits else f" (needs {model.ram_gb_required:.0f} GB)"
        lines.append(
            f"    {marker}{model.ollama_tag:<25s} "
            f"{model.ram_gb_required:>2.0f} GB  {model.notes}{fit_note}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Provider health checks
# ---------------------------------------------------------------------------

@dataclass
class ProviderTestResult:
    """Result of testing a provider's connectivity and capabilities."""
    reachable: bool = False
    reachable_detail: str = ""
    tool_use: bool | None = None  # None = not tested
    tool_use_detail: str = ""
    context_window: int | None = None  # Detected context length, or None
    context_window_detail: str = ""

    @property
    def ok(self) -> bool:
        ctx_ok = (
            self.context_window is None
            or self.context_window >= MIN_CONTEXT_TOKENS
        )
        return self.reachable and self.tool_use is not False and ctx_ok

    @property
    def warnings(self) -> list[str]:
        msgs = []
        if not self.reachable:
            msgs.append(f"Endpoint not reachable: {self.reachable_detail}")
        if self.context_window is not None and self.context_window < MIN_CONTEXT_TOKENS:
            msgs.append(
                f"Context window too small: {self.context_window:,} tokens "
                f"(Claude Code needs at least {MIN_CONTEXT_TOKENS:,})\n"
                f"  {self.context_window_detail}"
            )
        if self.tool_use is False:
            warning = (
                f"Tool use not supported: {self.tool_use_detail}\n"
                "  Claude Code relies on function calling for agentic workflows.\n"
                "  This model may not work correctly.\n"
                "\n"
                + format_model_recommendations()
            )
            msgs.append(warning)
        return msgs


def check_provider(provider: ProviderConfig, check_tools: bool = True) -> ProviderTestResult:
    """Test a provider's connectivity and tool-use support.

    For 'local' type: tests Anthropic Messages API (/v1/messages)
    For 'openai' type: tests OpenAI chat completions (/chat/completions)

    Args:
        provider: The provider to test.
        check_tools: If True and provider has a model configured,
            send a test request with a tool definition.

    Returns:
        ProviderTestResult with reachable/tool_use status and details.
    """
    import json
    import urllib.request
    import urllib.error

    result = ProviderTestResult()
    env = provider.env_vars()
    api_base = (
        env.get("OPENAI_BASE_URL")
        or env.get("ANTHROPIC_BASE_URL")
        or provider.api_base
    )
    if not api_base:
        result.reachable_detail = "no API base URL configured"
        return result

    api_key = env.get("OPENAI_API_KEY") or env.get("ANTHROPIC_API_KEY") or ""

    # 1. Connectivity check
    # For local (Anthropic-compatible): try /api/tags (Ollama) then /models
    # For openai: try /models
    check_urls = []
    if provider.type == "local":
        check_urls.append(api_base.rstrip("/") + "/api/tags")
    check_urls.append(api_base.rstrip("/") + "/models")

    for check_url in check_urls:
        try:
            req = urllib.request.Request(check_url)
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                result.reachable = True
                result.reachable_detail = f"{check_url} (HTTP {resp.status})"
                break
        except (urllib.error.URLError, Exception):
            continue

    if not result.reachable:
        result.reachable_detail = f"{check_urls[-1]}: connection failed"
        return result

    # 2. Context window check (best-effort)
    if provider.model:
        _check_context_window(api_base, api_key, provider, result)

    # 3. Tool-use check
    if not check_tools or not provider.model:
        return result

    if provider.type == "local":
        result = _check_tools_anthropic(api_base, api_key, provider.model, result)
    elif provider.type == "openai":
        result = _check_tools_openai(api_base, api_key, provider.model, result)

    return result


def _check_context_window(
    api_base: str, api_key: str, provider: ProviderConfig,
    result: ProviderTestResult,
) -> None:
    """Try to detect the model's context window size.

    For Ollama: POST /api/show with model name to get model_info.
    Falls back silently if the endpoint doesn't support this.
    """
    import json
    import urllib.request
    import urllib.error

    if provider.type == "local":
        # Try Ollama's /api/show endpoint
        show_url = api_base.rstrip("/") + "/api/show"
        try:
            payload = json.dumps({"name": provider.model}).encode()
            req = urllib.request.Request(
                show_url, data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())

            # Ollama returns model_info with context_length or
            # parameters with num_ctx
            model_info = body.get("model_info", {})
            # Look through model_info keys for context_length
            for key, value in model_info.items():
                if "context_length" in key and isinstance(value, (int, float)):
                    result.context_window = int(value)
                    break

            if result.context_window is None:
                # Try parameters string
                params = body.get("parameters", "")
                for line in params.splitlines():
                    if "num_ctx" in line:
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            result.context_window = int(parts[-1])
                            break

            if result.context_window is not None:
                if result.context_window < MIN_CONTEXT_TOKENS:
                    result.context_window_detail = (
                        f"Increase with: ollama run {provider.model} "
                        f"/set parameter num_ctx {MIN_CONTEXT_TOKENS}"
                    )
                else:
                    result.context_window_detail = "OK"

        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, ValueError, Exception):
            pass  # Best-effort — don't fail if we can't detect


def _check_tools_anthropic(
    api_base: str, api_key: str, model: str, result: ProviderTestResult,
) -> ProviderTestResult:
    """Test tool use via Anthropic Messages API (/v1/messages)."""
    import json
    import urllib.request
    import urllib.error

    messages_url = api_base.rstrip("/") + "/v1/messages"
    payload = json.dumps({
        "model": model,
        "max_tokens": 100,
        "messages": [
            {"role": "user", "content": "What is 2+2? Use the calculator tool."}
        ],
        "tools": [{
            "name": "calculator",
            "description": "Evaluate a math expression",
            "input_schema": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The math expression to evaluate"
                    }
                },
                "required": ["expression"]
            }
        }],
    }).encode()

    try:
        req = urllib.request.Request(
            messages_url, data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key or "no-key",
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())

        # Anthropic format: content is a list of blocks
        content_blocks = body.get("content", [])
        has_tool_use = any(
            block.get("type") == "tool_use" for block in content_blocks
        )
        stop_reason = body.get("stop_reason", "")

        if has_tool_use or stop_reason == "tool_use":
            result.tool_use = True
            result.tool_use_detail = "model produced a tool call"
        else:
            result.tool_use = False
            text = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    text = (block.get("text") or "")[:80]
                    break
            result.tool_use_detail = f"model did not use the tool (response: {text})"

    except urllib.error.HTTPError as e:
        result.tool_use = False
        error_body = ""
        try:
            error_body = e.read().decode()[:200]
        except Exception:
            pass
        detail = f"HTTP {e.code}"
        if e.code == 400:
            detail += " — server may not support the Anthropic Messages API tools format"
        if error_body:
            detail += f" ({error_body})"
        result.tool_use_detail = detail
    except urllib.error.URLError as e:
        result.tool_use = False
        result.tool_use_detail = str(e.reason)
    except Exception as e:
        result.tool_use = False
        result.tool_use_detail = str(e)

    return result


def _check_tools_openai(
    api_base: str, api_key: str, model: str, result: ProviderTestResult,
) -> ProviderTestResult:
    """Test tool use via OpenAI chat completions API."""
    import json
    import urllib.request
    import urllib.error

    chat_url = api_base.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model,
        "max_tokens": 100,
        "messages": [
            {"role": "user", "content": "What is 2+2? Use the calculator tool."}
        ],
        "tools": [{
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Evaluate a math expression",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "The math expression to evaluate"
                        }
                    },
                    "required": ["expression"]
                }
            }
        }],
        "tool_choice": "auto",
    }).encode()

    try:
        req = urllib.request.Request(
            chat_url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())

        choices = body.get("choices", [])
        if not choices:
            result.tool_use = False
            result.tool_use_detail = "empty response from model"
            return result

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])
        finish_reason = choices[0].get("finish_reason", "")

        if tool_calls or finish_reason == "tool_calls":
            result.tool_use = True
            result.tool_use_detail = "model produced a tool call"
        else:
            result.tool_use = False
            content = (message.get("content") or "")[:80]
            result.tool_use_detail = f"model did not use the tool (response: {content})"

    except urllib.error.HTTPError as e:
        result.tool_use = False
        error_body = ""
        try:
            error_body = e.read().decode()[:200]
        except Exception:
            pass
        detail = f"HTTP {e.code}"
        if e.code == 400:
            detail += " — server may not support the 'tools' parameter"
        if error_body:
            detail += f" ({error_body})"
        result.tool_use_detail = detail
    except urllib.error.URLError as e:
        result.tool_use = False
        result.tool_use_detail = str(e.reason)
    except Exception as e:
        result.tool_use = False
        result.tool_use_detail = str(e)

    return result
