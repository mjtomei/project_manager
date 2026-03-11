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
