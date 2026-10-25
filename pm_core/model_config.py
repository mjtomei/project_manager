"""Per-session-type model and quality targeting.

Resolves which model to use for a given session type based on a
configuration hierarchy:

    PM_MODEL env var  >  PR session_models  >  PR model  >  project.yaml model_config
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

SESSION_TYPES = ("impl", "review", "qa", "qa_planning", "qa_scenario",
                 "qa_concretize", "qa_verification", "qa_finalize",
                 "qa_interactive", "signoff", "watcher", "merge")

# The types a PR's ``model`` / ``session_models`` can decide.  The watcher
# is a project session (``pm watcher`` resolves it with no PR), so a PR
# override never reaches it.
PR_SESSION_TYPES = tuple(st for st in SESSION_TYPES if st != "watcher")

DEFAULT_SESSION_MODELS: dict[str, str] = {
    # Empty — use Claude CLI defaults unless explicitly configured via
    # project.yaml, global settings, or PM_MODEL env var.
}


_PROVIDER_PREFIX = "provider:"

# Sub-types that fall back to a parent type when not explicitly configured.
_FALLBACK_TYPES: dict[str, str] = {
    "qa_planning": "qa",
    "qa_scenario": "qa",
    "qa_concretize": "qa",
    "qa_verification": "qa",
    "qa_finalize": "qa",
    # Scenario 0, the persistent interactive QA session.  Separate from
    # qa_scenario (autonomous workers) so routing workers to another
    # account never moves the session the user remote-controls.
    "qa_interactive": "qa",
    "signoff": "review",
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
    # Empty — use Claude CLI defaults unless explicitly configured via
    # project.yaml, global settings, or PM_EFFORT env var.
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
        session_models = config_block(project_model_config(project_data),
                                      "session_models")
        for st in type_chain:
            # A blank or non-string entry (hand-edited YAML) counts as
            # absent, as for a PR's role entries: it must not raise at
            # every launch of the type (or in `pm model show`).
            if _is_model_value(session_models.get(st)):
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
        effort_map = config_block(project_model_config(project_data),
                                  "session_effort")
        for st in type_chain:
            # A blank or non-string level counts as absent, as for models
            # (validate_model_config reports it).
            if _is_model_value(effort_map.get(st)):
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


def validate_model_config(project_data: dict | None) -> list[str]:
    """Return a list of problems with project.yaml's model settings: the
    ``model_config`` block and each PR's ``session_models``.

    An empty list means valid. Checks that:

    - ``session_models`` / ``session_effort`` keys are known session types
      (``SESSION_TYPES``);
    - ``session_models`` values are model names (other values are ignored);
    - ``session_effort`` values are valid effort levels (``EFFORT_LEVELS``);
    - each PR's ``model`` is a model name;
    - each PR's ``session_models`` is a mapping keyed by the types a PR
      decides (``PR_SESSION_TYPES``), with model-name values (other values
      are ignored).

    Unknown keys are silently ignored by ``resolve_model_and_provider`` — a
    typo'd session type would otherwise just never take effect — so this is
    surfaced as a warning (e.g. by ``pm model show``) rather than raised.
    """
    if not project_data:
        return []
    mc = project_model_config(project_data)
    errors: list[str] = []
    if not isinstance(mc, dict):
        errors.append("model_config must be a mapping")
        mc = {}
    known = sorted(SESSION_TYPES)
    for block in ("session_models", "session_effort"):
        entries = config_block(mc, block)
        if not isinstance(entries, dict):
            errors.append(f"model_config.{block} must be a mapping")
            continue
        for st in entries:
            if st not in SESSION_TYPES:
                errors.append(
                    f"model_config.{block}: unknown session type {st!r}. "
                    f"Valid types: {known}"
                )
            elif block == "session_models" and not _is_model_value(entries[st]):
                errors.append(
                    f"model_config.session_models[{st!r}]: {entries[st]!r} "
                    "is not a model name or 'provider:<name>' (ignored)")
    effort_entries = config_block(mc, "session_effort")
    if isinstance(effort_entries, dict):
        for st, level in effort_entries.items():
            if level not in EFFORT_LEVELS:
                errors.append(
                    f"model_config.session_effort[{st!r}]: invalid effort "
                    f"{level!r}. Valid levels: {list(EFFORT_LEVELS)}"
                )
    # A PR's role exceptions are ignored the same way, so a typo would
    # leave that role on the PR-wide model.
    for pr in project_data.get("prs") or []:
        if not isinstance(pr, dict):
            continue
        # A non-string PR ``model`` (hand-edited YAML) is not guessed
        # around: launches that fall back to it fail, so say so here.
        # An empty one ('', 0, [], ...) selects nothing at launch
        # (``resolve_model_and_provider`` skips a falsy PR model), so the
        # project settings apply and it is only ignored.
        model = pr.get("model")
        if model is not None and not _is_model_value(model):
            effect = ("launches that use it fail" if model
                      else "ignored; the project settings apply")
            errors.append(f"prs[{pr.get('id')}].model: {model!r} is "
                          f"not a model name or 'provider:<name>' ({effect})")
        if pr.get("session_models") is None:
            continue
        where = f"prs[{pr.get('id')}].session_models"
        entries = pr["session_models"]
        if not isinstance(entries, dict):
            errors.append(f"{where} must be a mapping")
            continue
        for st, val in entries.items():
            if st not in PR_SESSION_TYPES:
                if st in SESSION_TYPES:
                    errors.append(
                        f"{where}: {st!r} is not a PR session; a PR "
                        "override never reaches it (ignored). Set it with "
                        f"'pm model set {st} <model> --project'")
                else:
                    errors.append(f"{where}: unknown session type {st!r}. "
                                  f"Valid types: {sorted(PR_SESSION_TYPES)}")
            elif not _is_model_value(val):
                errors.append(f"{where}[{st!r}]: {val!r} is not a model "
                              "name or 'provider:<name>' (ignored)")
    return errors


def get_pr_model_override(pr_entry: dict,
                          session_type: str | None = None) -> str | None:
    """Select a PR's role override, falling back to its all-role model.

    For example, ``model: provider:deepseek-flash`` with
    ``session_models: {signoff: provider:claude-work}`` keeps the experimental
    model for development while routing sign-off to Claude. Role inheritance
    matches project configuration (e.g. qa_scenario -> qa, signoff -> review).
    """
    models = pr_entry.get("session_models")
    if session_type and isinstance(models, dict):
        for role in (session_type, _FALLBACK_TYPES.get(session_type)):
            # A blank or non-string entry (hand-edited YAML) counts as
            # absent: it must neither drop the PR model for that role nor
            # raise at every launch of it.
            if role and _is_model_value(models.get(role)):
                return models[role]
    return pr_entry.get("model")


def _is_model_value(value) -> bool:
    """A usable model value: a model name or ``provider:<name>`` (also
    used for effort levels: a non-blank string)."""
    return isinstance(value, str) and bool(value.strip())


def project_model_config(project_data: dict | None):
    """``project.model_config`` of *project_data*; ``{}`` when absent.

    A blank block (``model_config:`` or ``session_models:`` whose entries
    are all commented out) loads as None.  It selects nothing, so it reads
    as empty here and in ``config_block``, like a blank entry, rather than
    failing every launch and ``pm model set`` (the remedy route errors
    name).  Any other non-mapping is returned as is: it is malformed
    (``validate_model_config``) and launches fail rather than guess.
    """
    if not project_data:
        return {}
    mc = (project_data.get("project") or {}).get("model_config")
    return {} if mc is None else mc


def config_block(mc: dict, block: str):
    """``mc[block]`` (``session_models`` / ``session_effort``); ``{}`` when
    absent or blank."""
    entries = mc.get(block)
    return {} if entries is None else entries
