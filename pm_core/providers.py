"""LLM provider configuration for pm sessions.

Supports multiple provider types:
  - claude: Default Anthropic Claude API (no extra config needed)
  - openai: OpenAI-compatible API endpoint (Ollama, llama.cpp, vLLM, etc.)

Configuration is stored in ~/.pm/providers.yaml:

    providers:
      ollama:
        type: openai
        api_base: http://localhost:11434/v1
        api_key: ollama
        model: llama3.1:70b
        capabilities: [code, review]

      vllm:
        type: openai
        api_base: http://localhost:8000/v1
        model: codellama/CodeLlama-34b

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
    """Configuration for an LLM provider."""
    name: str
    type: str = "claude"  # "claude" or "openai"
    api_base: str = ""
    api_key: str = ""
    model: str = ""
    capabilities: list[str] = field(default_factory=list)

    def env_vars(self) -> dict[str, str]:
        """Return environment variables needed to use this provider.

        For openai-type providers, sets OPENAI_BASE_URL and OPENAI_API_KEY
        so Claude Code can use them with --model openai:model-name.
        """
        if self.type == "claude":
            env: dict[str, str] = {}
            if self.api_base:
                env["ANTHROPIC_BASE_URL"] = self.api_base
            if self.api_key:
                env["ANTHROPIC_API_KEY"] = _resolve_env_ref(self.api_key)
            if self.model:
                env["ANTHROPIC_MODEL"] = self.model
            return env

        if self.type == "openai":
            env = {}
            if self.api_base:
                env["OPENAI_BASE_URL"] = self.api_base
            if self.api_key:
                # Resolve env var references like ${VLLM_API_KEY}
                env["OPENAI_API_KEY"] = _resolve_env_ref(self.api_key)
            return env

        return {}

    def model_flag(self) -> str | None:
        """Return the --model flag value for claude CLI, or None."""
        if self.type == "openai" and self.model:
            return f"openai:{self.model}"
        if self.type == "claude" and self.model:
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
        type=entry.get("type", "openai"),
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


# Models with strong function-calling / tool-use support, ordered by size.
# RAM estimates assume Q4_K_M quantization via Ollama.
RECOMMENDED_MODELS: list[RecommendedModel] = [
    RecommendedModel(
        name="Qwen 2.5 Coder 7B",
        ollama_tag="qwen2.5-coder:7b",
        param_billions=7,
        ram_gb_required=5,
        notes="Best small model for code + tool use",
    ),
    RecommendedModel(
        name="Llama 3.1 8B",
        ollama_tag="llama3.1:8b",
        param_billions=8,
        ram_gb_required=5,
        notes="Strong general-purpose with tool use",
    ),
    RecommendedModel(
        name="Mistral Nemo 12B",
        ollama_tag="mistral-nemo:12b",
        param_billions=12,
        ram_gb_required=8,
        notes="Good tool use, larger context window",
    ),
    RecommendedModel(
        name="Qwen 2.5 Coder 14B",
        ollama_tag="qwen2.5-coder:14b",
        param_billions=14,
        ram_gb_required=10,
        notes="Strong code generation + tool use",
    ),
    RecommendedModel(
        name="Qwen 2.5 Coder 32B",
        ollama_tag="qwen2.5-coder:32b",
        param_billions=32,
        ram_gb_required=20,
        notes="Excellent code + tool use, needs more RAM",
    ),
    RecommendedModel(
        name="Llama 3.1 70B",
        ollama_tag="llama3.1:70b",
        param_billions=70,
        ram_gb_required=42,
        notes="Top-tier local model, requires significant RAM/VRAM",
    ),
]


def _get_system_memory_gb() -> float | None:
    """Detect total system RAM in GB. Returns None if detection fails."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return kb / (1024 * 1024)
    except (OSError, ValueError, IndexError):
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

    lines = ["  Recommended models with tool-use support:"]
    if available is not None:
        mem_source = "VRAM" if (vram or 0) >= (ram or 0) else "RAM"
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

    @property
    def ok(self) -> bool:
        return self.reachable and self.tool_use is not False

    @property
    def warnings(self) -> list[str]:
        msgs = []
        if not self.reachable:
            msgs.append(f"Endpoint not reachable: {self.reachable_detail}")
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

    Args:
        provider: The provider to test.
        check_tools: If True and provider is openai-type with a model,
            send a test chat completion with a tool definition.

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

    # 1. Connectivity: GET /models
    models_url = api_base.rstrip("/") + "/models"
    try:
        req = urllib.request.Request(models_url)
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")
        with urllib.request.urlopen(req, timeout=5) as resp:
            result.reachable = True
            result.reachable_detail = f"{models_url} (HTTP {resp.status})"
    except urllib.error.URLError as e:
        result.reachable_detail = f"{models_url}: {e.reason}"
        return result
    except Exception as e:
        result.reachable_detail = str(e)
        return result

    # 2. Tool-use check
    if not check_tools or provider.type != "openai" or not provider.model:
        return result

    chat_url = api_base.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": provider.model,
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
