"""Per-session-type model and quality targeting.

Resolves which model to use for a given session type based on a
configuration hierarchy:

    PM_MODEL env var  >  PR-level override  >  project.yaml model_config
    >  global ~/.pm/settings  >  (no default — use CLI setting)

Effort level resolution:

    PM_EFFORT env var  >  project.yaml session_effort
    >  global ~/.pm/settings  >  (no default — use CLI setting)

Model values like ``sonnet``, ``opus``, ``haiku`` are passed directly to
the Claude CLI's ``--model`` flag, which resolves them to the latest
version automatically.

For external/local model servers, configure a provider via ``pm provider``
(see providers.py) and reference it in model_config:

    project.yaml:
      project:
        model_config:
          session_models:
            watcher: provider:ollama    # use the "ollama" provider
            review: opus               # use a model name shortcut

Values prefixed with ``provider:`` are resolved via the provider system
and return a provider name instead of a model identifier.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from pm_core.paths import configure_logger, get_global_setting_value

_log = configure_logger("pm.model_config")

# ── Known model names (for display and haiku effort suppression) ─────

# Bare names like "sonnet", "opus", "haiku" are passed directly to the
# Claude CLI which resolves them to the latest version automatically.
# We only need to know about haiku to suppress the --effort flag.
_HAIKU_PATTERNS = ("haiku",)

# ── Session types ────────────────────────────────────────────────────

SESSION_TYPES = ("impl", "review", "qa", "qa_planning", "qa_scenario", "qa_verification", "watcher", "supervisor", "merge")

DEFAULT_SESSION_MODELS: dict[str, str] = {
    # Empty — use Claude CLI defaults unless explicitly configured via
    # project.yaml, global settings, or PM_MODEL env var.
}


_PROVIDER_PREFIX = "provider:"

# Sub-types that fall back to a parent type when not explicitly configured.
_FALLBACK_TYPES: dict[str, str] = {
    "qa_planning": "qa",
    "qa_scenario": "qa",
    "qa_verification": "qa",
    "supervisor": "watcher",
}

# Valid effort levels for the Claude CLI --effort flag.
# Only Sonnet and Opus support effort; Haiku does not.
EFFORT_LEVELS = ("low", "medium", "high")

# Models that do NOT support the --effort flag
_NO_EFFORT_MODELS = {
    "haiku",
    "claude-haiku-4-5-20251001",
}

DEFAULT_SESSION_EFFORT: dict[str, str] = {
    # Supervisors default to high effort — they need Opus-level analysis
    # to effectively coach lower-effort sessions.
    "supervisor": "high",
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
    values are passed through as-is to the Claude CLI's --model flag
    (bare names like ``sonnet`` are resolved by the CLI itself).
    """
    def _resolve_value(value: str) -> ModelResolution:
        if value.startswith(_PROVIDER_PREFIX):
            return ModelResolution(provider=value[len(_PROVIDER_PREFIX):])
        return ModelResolution(model=value)

    # Types to try: the requested type, then its fallback (e.g. qa_planning -> qa)
    fallback = _FALLBACK_TYPES.get(session_type)
    type_chain = (session_type, fallback) if fallback else (session_type,)

    # --- Model / provider resolution ---
    # 1. PM_MODEL env var
    if (env_model := os.environ.get("PM_MODEL")):
        resolution = _resolve_value(env_model)
    # 2. PR-level override
    elif pr_model:
        resolution = _resolve_value(pr_model)
    # 3. Project-level config (try specific type, then fallback)
    else:
        resolution = None
        session_models = (
            project_data.get("project", {}).get("model_config", {}).get("session_models", {})
            if project_data else {}
        )
        for st in type_chain:
            if st in session_models:
                resolution = _resolve_value(session_models[st])
                break
        # 4. Global setting (~/.pm/settings/model-<type>)
        if resolution is None:
            for st in type_chain:
                if (global_val := get_global_setting_value(f"model-{st}")):
                    resolution = _resolve_value(global_val)
                    break
        # 5. Built-in default tier -> concrete model
        if resolution is None:
            for st in type_chain:
                tier = DEFAULT_SESSION_MODELS.get(st)
                if tier:
                    model_id = tiers.get(tier)
                    resolution = ModelResolution(model=model_id) if model_id else ModelResolution()
                    break
        if resolution is None:
            resolution = ModelResolution()

    # --- Effort resolution (independent of model) ---
    # 1. PM_EFFORT env var
    if (env_effort := os.environ.get("PM_EFFORT")):
        resolution.effort = env_effort
    else:
        # 2. Project-level effort config (try specific type, then fallback)
        effort = None
        if project_data:
            mc = project_data.get("project", {}).get("model_config", {})
            effort_map = mc.get("session_effort", {})
            for st in type_chain:
                if st in effort_map:
                    effort = effort_map[st]
                    break
        # 3. Global setting (~/.pm/settings/effort-<type>)
        if not effort:
            for st in type_chain:
                effort = get_global_setting_value(f"effort-{st}") or None
                if effort:
                    break
        # 4. Built-in default
        if not effort:
            for st in type_chain:
                effort = DEFAULT_SESSION_EFFORT.get(st)
                if effort:
                    break
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
