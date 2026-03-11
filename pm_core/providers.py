"""LLM provider configuration for pm sessions.

Supports multiple provider types:
  - claude: Default Anthropic Claude API (no extra config needed)
  - local: Local model via Anthropic-compatible API (Ollama 0.14+,
    LM Studio 0.4.1+, llama.cpp).  Recommended for local models.
  - openai: OpenAI-compatible API endpoint (vLLM, etc.).
    Use only if your server doesn't speak the Anthropic Messages API.

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
    """
    name: str
    type: str = "claude"  # "claude", "local", or "openai"
    api_base: str = ""
    api_key: str = ""
    model: str = ""
    capabilities: list[str] = field(default_factory=list)

    def env_vars(self) -> dict[str, str]:
        """Return environment variables needed to use this provider."""
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
            return env

        if self.type == "openai":
            env = {}
            if self.api_base:
                env["OPENAI_BASE_URL"] = self.api_base
            if self.api_key:
                env["OPENAI_API_KEY"] = _resolve_env_ref(self.api_key)
            return env

        return {}

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


def get_provider(name: str | None = None) -> ProviderConfig:
    """Resolve and return a provider configuration.

    Resolution order:
      1. Explicit name parameter
      2. PM_PROVIDER environment variable
      3. Per-session provider setting
      4. Default from providers.yaml
      5. Built-in "claude" provider
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
    anthropic_api: bool | None = None  # None = not tested
    anthropic_api_detail: str = ""
    inference_ok: bool | None = None  # None = not tested
    inference_detail: str = ""

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
        if self.anthropic_api is True and self.anthropic_api_detail:
            msgs.append(self.anthropic_api_detail)
        return msgs

    def capabilities_summary(self) -> dict[str, Any]:
        """Return a structured summary of tested capabilities."""
        return {
            "reachable": self.reachable,
            "anthropic_api": self.anthropic_api,
            "tool_use": self.tool_use,
            "context_window": self.context_window,
            "inference": self.inference_ok,
        }


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

    # 3. For openai providers, probe for Anthropic Messages API support
    if provider.type == "openai" and provider.model:
        _check_anthropic_api_support(api_base, api_key, provider.model, result)

    # 4. Tool-use check (also validates inference)
    if not check_tools or not provider.model:
        return result

    if provider.type == "local":
        result = _check_tools_anthropic(api_base, api_key, provider.model, result)
    elif provider.type == "openai":
        result = _check_tools_openai(api_base, api_key, provider.model, result)

    # Derive inference status from tool-use test (which sends a real prompt)
    if result.tool_use is not None:
        result.inference_ok = True  # Got a response = inference works
        result.inference_detail = "model produced output"

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


def _check_anthropic_api_support(
    api_base: str, api_key: str, model: str,
    result: ProviderTestResult,
) -> None:
    """Probe whether an openai-type provider also supports the Anthropic Messages API.

    If /v1/messages responds (even with an error other than 404), the server
    likely supports the Anthropic API natively, and the user should consider
    switching to type=local for better Claude Code compatibility.
    """
    import json
    import urllib.request
    import urllib.error

    # Strip trailing /v1 since openai api_base typically includes it already
    base = api_base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    messages_url = base + "/v1/messages"
    # Send a minimal request to see if the endpoint exists
    payload = json.dumps({
        "model": model,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "hi"}],
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            # Got a successful response — Anthropic API is supported
            result.anthropic_api = True
            result.anthropic_api_detail = (
                "Server supports Anthropic Messages API (/v1/messages). "
                "Consider using type=local instead of type=openai for "
                "better Claude Code compatibility."
            )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            result.anthropic_api = False
            result.anthropic_api_detail = "Anthropic Messages API not available"
        else:
            # Non-404 error means the endpoint exists but rejected our request
            result.anthropic_api = True
            result.anthropic_api_detail = (
                "Server supports Anthropic Messages API (/v1/messages). "
                "Consider using type=local instead of type=openai for "
                "better Claude Code compatibility."
            )
    except (urllib.error.URLError, Exception):
        result.anthropic_api = False
        result.anthropic_api_detail = "Anthropic Messages API not available"


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
