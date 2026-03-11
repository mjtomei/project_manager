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
            msgs.append(
                f"Tool use not supported: {self.tool_use_detail}\n"
                "  Claude Code relies on function calling for agentic workflows.\n"
                "  This model may not work correctly. Consider using a model\n"
                "  with strong tool-use support, or restrict this provider's\n"
                "  capabilities to non-agentic tasks."
            )
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
