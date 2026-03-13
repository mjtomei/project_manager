"""Per-session-type model and quality targeting.

Resolves which model to use for a given session type based on a
configuration hierarchy:

    PM_MODEL env var  >  PR-level override  >  project.yaml model_config
    >  global ~/.pm/settings  >  (no default — use CLI setting)

Effort level resolution:

    PM_EFFORT env var  >  project.yaml session_effort
    >  global ~/.pm/settings  >  (no default — use CLI setting)

When no override is configured at any level, no --model or --effort flag
is passed to the Claude CLI, so it uses whatever model is configured in
the user's CLI settings.

Quality tiers and model name shortcuts are available for use with
``pm model set``:

    high / opus    -> claude-opus-4-6-20250514
    medium / sonnet -> claude-sonnet-4-6-20250514
    low / haiku    -> claude-haiku-4-5-20251001

For external/local model servers, configure a provider via ``pm provider``
(see providers.py) and reference it in model_config:

    project.yaml:
      project:
        model_config:
          session_models:
            watcher: provider:ollama    # use the "ollama" provider
            qa: low                     # use a quality tier
            review: opus               # use a model name shortcut

Values prefixed with ``provider:`` are resolved via the provider system
and return a provider name instead of a model identifier.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pm_core.paths import configure_logger, get_global_setting_value

_log = configure_logger("pm.model_config")

# ── Quality tiers ────────────────────────────────────────────────────

QUALITY_TIERS: dict[str, str] = {
    "high": "claude-opus-4-6-20250514",
    "medium": "claude-sonnet-4-6-20250514",
    "low": "claude-haiku-4-5-20251001",
    # Model name shortcuts
    "opus": "claude-opus-4-6-20250514",
    "sonnet": "claude-sonnet-4-6-20250514",
    "haiku": "claude-haiku-4-5-20251001",
}

# ── Session types ────────────────────────────────────────────────────

SESSION_TYPES = ("impl", "review", "qa", "watcher", "merge")

_PROVIDER_PREFIX = "provider:"

# Valid effort levels for the Claude CLI --effort flag.
# Only Sonnet and Opus support effort; Haiku does not.
EFFORT_LEVELS = ("low", "medium", "high")

# Models that do NOT support the --effort flag
_NO_EFFORT_MODELS = {
    QUALITY_TIERS["haiku"],  # claude-haiku-4-5-20251001
}


@dataclass
class ModelResolution:
    """Result of resolving a model for a session type.

    Either ``model`` or ``provider`` will be set, not both.
    - model: a concrete model identifier to pass via --model
    - provider: a provider name to pass via the provider system
    - effort: effort level to pass via --effort (low, medium, high)
    """
    model: str | None = None
    provider: str | None = None
    effort: str | None = None


def resolve_model(
    session_type: str,
    *,
    pr_model: str | None = None,
    project_data: dict | None = None,
) -> str | None:
    """Resolve the model to use for a session.

    Returns a concrete model identifier string, or None to use the
    Claude CLI default (i.e. don't pass --model).

    For provider-based resolution, use ``resolve_model_and_provider``
    instead — this function ignores ``provider:`` prefixed values and
    falls through to the next level.
    """
    result = resolve_model_and_provider(
        session_type,
        pr_model=pr_model,
        project_data=project_data,
    )
    return result.model


def resolve_model_and_provider(
    session_type: str,
    *,
    pr_model: str | None = None,
    project_data: dict | None = None,
) -> ModelResolution:
    """Resolve model and/or provider for a session type.

    Returns a ModelResolution with either a model ID or a provider name,
    plus an effort level.  Values prefixed with ``provider:`` (e.g.
    ``provider:ollama``) are resolved as provider names.  All other
    values are expanded through quality tiers.
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

    # --- Model / provider resolution ---
    # 1. PM_MODEL env var
    if (env_model := os.environ.get("PM_MODEL")):
        resolution = _resolve_value(env_model)
    # 2. PR-level override
    elif pr_model:
        resolution = _resolve_value(pr_model)
    # 3. Project-level config
    elif project_data and session_type in (
        project_data.get("project", {}).get("model_config", {}).get("session_models", {})
    ):
        resolution = _resolve_value(
            project_data["project"]["model_config"]["session_models"][session_type]
        )
    # 4. Global setting (~/.pm/settings/model-<type>)
    elif (global_val := get_global_setting_value(f"model-{session_type}")):
        resolution = _resolve_value(global_val)
    # 5. No default — let the Claude CLI use its own setting
    else:
        resolution = ModelResolution()

    # --- Effort resolution (independent of model) ---
    # 1. PM_EFFORT env var
    if (env_effort := os.environ.get("PM_EFFORT")):
        resolution.effort = env_effort
    else:
        # 2. Project-level effort config
        effort = None
        if project_data:
            mc = project_data.get("project", {}).get("model_config", {})
            effort = mc.get("session_effort", {}).get(session_type)
        # 3. Global setting (~/.pm/settings/effort-<type>)
        if not effort:
            effort = get_global_setting_value(f"effort-{session_type}") or None
        # No built-in default — let the CLI use its own setting
        resolution.effort = effort

    # Suppress effort for models that don't support it (e.g. Haiku)
    if resolution.effort and resolution.model in _NO_EFFORT_MODELS:
        _log.debug("Suppressing effort=%s for model %s (not supported)",
                   resolution.effort, resolution.model)
        resolution.effort = None

    return resolution


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
