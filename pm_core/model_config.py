"""Per-session-type model and quality targeting.

Resolves which model to use for a given session type based on a
configuration hierarchy:

    CLI --model flag  >  PR-level override  >  project.yaml model_config
    >  global ~/.pm/settings  >  built-in defaults

Quality tiers map human-friendly labels to concrete model identifiers:

    high      -> claude-opus-4-20250514   (reviews, critical decisions)
    standard  -> claude-sonnet-4-20250514 (implementation, QA)
    economy   -> claude-haiku-4-5-20251001 (watchers, high-volume tasks)

For external/local model servers, configure a provider via ``pm provider``
(see providers.py) and reference it in model_config:

    project.yaml:
      project:
        model_config:
          session_models:
            watcher: provider:ollama    # use the "ollama" provider
            qa: economy                 # use a quality tier
            review: claude-opus-4-20250514  # use a specific model ID

Values prefixed with ``provider:`` are resolved via the provider system
and return a provider name instead of a model identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pm_core.paths import configure_logger, get_global_setting_value

_log = configure_logger("pm.model_config")

# ── Quality tiers ────────────────────────────────────────────────────

QUALITY_TIERS: dict[str, str] = {
    "high": "claude-opus-4-20250514",
    "standard": "claude-sonnet-4-20250514",
    "economy": "claude-haiku-4-5-20251001",
}

# ── Session types and their default quality tier ─────────────────────

SESSION_TYPES = ("impl", "review", "qa", "watcher", "merge")

DEFAULT_SESSION_MODELS: dict[str, str] = {
    "review": "high",
    "impl": "standard",
    "qa": "standard",
    "merge": "standard",
    "watcher": "economy",
}

_PROVIDER_PREFIX = "provider:"


@dataclass
class ModelResolution:
    """Result of resolving a model for a session type.

    Either ``model`` or ``provider`` will be set, not both.
    - model: a concrete model identifier to pass via --model
    - provider: a provider name to pass via the provider system
    """
    model: str | None = None
    provider: str | None = None


def resolve_model(
    session_type: str,
    *,
    cli_model: str | None = None,
    pr_model: str | None = None,
    project_data: dict | None = None,
) -> str | None:
    """Resolve the model to use for a session.

    Returns a concrete model identifier string, or None to use the
    Claude CLI default (i.e. don't pass --model).

    For provider-based resolution, use ``resolve_model_and_provider``
    instead — this function ignores ``provider:`` prefixed values and
    falls through to the next level.

    Resolution order (first non-None wins):
        1. cli_model        — explicit --model flag
        2. pr_model         — per-PR override in project.yaml
        3. project config   — model_config.session_models.<type> in project.yaml
        4. global setting   — ~/.pm/settings/model-<type>
        5. built-in default — DEFAULT_SESSION_MODELS -> QUALITY_TIERS
    """
    result = resolve_model_and_provider(
        session_type,
        cli_model=cli_model,
        pr_model=pr_model,
        project_data=project_data,
    )
    return result.model


def resolve_model_and_provider(
    session_type: str,
    *,
    cli_model: str | None = None,
    pr_model: str | None = None,
    project_data: dict | None = None,
) -> ModelResolution:
    """Resolve model and/or provider for a session type.

    Returns a ModelResolution with either a model ID or a provider name.
    Values prefixed with ``provider:`` (e.g. ``provider:ollama``) are
    resolved as provider names and returned in ``resolution.provider``.
    All other values are expanded through quality tiers and returned in
    ``resolution.model``.
    """
    # Build effective tier map (project custom tiers override built-in)
    tiers = dict(QUALITY_TIERS)
    if project_data:
        custom = project_data.get("project", {}).get("model_config", {}).get("quality_tiers", {})
        tiers.update(custom)

    def _resolve_value(value: str) -> ModelResolution:
        if value.startswith(_PROVIDER_PREFIX):
            return ModelResolution(provider=value[len(_PROVIDER_PREFIX):])
        return ModelResolution(model=tiers.get(value, value))

    # 1. CLI override
    if cli_model:
        return _resolve_value(cli_model)

    # 2. PR-level override
    if pr_model:
        return _resolve_value(pr_model)

    # 3. Project-level config
    if project_data:
        mc = project_data.get("project", {}).get("model_config", {})
        session_models = mc.get("session_models", {})
        if session_type in session_models:
            return _resolve_value(session_models[session_type])

    # 4. Global setting
    global_val = get_global_setting_value(f"model-{session_type}")
    if global_val:
        return _resolve_value(global_val)

    # 5. Built-in default tier -> concrete model
    tier = DEFAULT_SESSION_MODELS.get(session_type)
    if tier:
        model_id = tiers.get(tier)
        if model_id:
            return ModelResolution(model=model_id)

    return ModelResolution()


def _expand_tier(value: str) -> str:
    """If value is a tier name (high/standard/economy), expand to model ID."""
    return QUALITY_TIERS.get(value, value)


def get_model_config_summary(project_data: dict | None = None) -> dict[str, str]:
    """Return the effective model for each session type (for display)."""
    result = {}
    for st in SESSION_TYPES:
        resolution = resolve_model_and_provider(st, project_data=project_data)
        if resolution.provider:
            result[st] = f"provider:{resolution.provider}"
        elif resolution.model:
            result[st] = resolution.model
        else:
            result[st] = "(default)"
    return result


def get_pr_model_override(pr_entry: dict) -> str | None:
    """Extract per-PR model override from a PR entry."""
    return pr_entry.get("model")
