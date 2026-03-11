"""Per-session-type model and quality targeting.

Resolves which model to use for a given session type based on a
configuration hierarchy:

    CLI --model flag  >  PR-level override  >  project.yaml model_config
    >  global ~/.pm/settings  >  built-in defaults

Quality tiers map human-friendly labels to concrete model identifiers:

    high      -> claude-opus-4-20250514   (reviews, critical decisions)
    standard  -> claude-sonnet-4-20250514 (implementation, QA)
    economy   -> claude-haiku-4-5-20251001 (watchers, high-volume tasks)
"""

from __future__ import annotations

import logging
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

    Resolution order (first non-None wins):
        1. cli_model        — explicit --model flag
        2. pr_model         — per-PR override in project.yaml
        3. project config   — model_config.session_models.<type> in project.yaml
        4. global setting   — ~/.pm/settings/model-<type>
        5. built-in default — DEFAULT_SESSION_MODELS -> QUALITY_TIERS
    """
    # Build effective tier map (project custom tiers override built-in)
    tiers = dict(QUALITY_TIERS)
    if project_data:
        custom = project_data.get("project", {}).get("model_config", {}).get("quality_tiers", {})
        tiers.update(custom)

    def _expand(value: str) -> str:
        return tiers.get(value, value)

    # 1. CLI override
    if cli_model:
        return _expand(cli_model)

    # 2. PR-level override
    if pr_model:
        return _expand(pr_model)

    # 3. Project-level config
    if project_data:
        mc = project_data.get("project", {}).get("model_config", {})
        session_models = mc.get("session_models", {})
        if session_type in session_models:
            return _expand(session_models[session_type])

    # 4. Global setting
    global_val = get_global_setting_value(f"model-{session_type}")
    if global_val:
        return _expand(global_val)

    # 5. Built-in default tier -> concrete model
    tier = DEFAULT_SESSION_MODELS.get(session_type)
    if tier:
        return tiers.get(tier)

    return None


def _expand_tier(value: str) -> str:
    """If value is a tier name (high/standard/economy), expand to model ID."""
    return QUALITY_TIERS.get(value, value)


def get_model_config_summary(project_data: dict | None = None) -> dict[str, str]:
    """Return the effective model for each session type (for display)."""
    result = {}
    for st in SESSION_TYPES:
        model = resolve_model(st, project_data=project_data)
        result[st] = model or "(default)"
    return result


def get_pr_model_override(pr_entry: dict) -> str | None:
    """Extract per-PR model override from a PR entry."""
    return pr_entry.get("model")
