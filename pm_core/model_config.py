"""Per-session-type model and quality targeting.

Resolves which model to use for a given session type based on a
configuration hierarchy:

    PM_MODEL env var  >  PR session_models  >  PR model  >  project.yaml model_config
    >  global ~/.pm/settings  >  (no default — use CLI setting)

Effort level resolution:

    PM_EFFORT env var  >  PR session_effort  >  PR effort
    >  the selected provider's effort  >  project.yaml session_effort
    >  global ~/.pm/settings  >  (no default — use CLI setting)

A PR's ``session_models`` / ``session_effort`` entries apply to one role
(with the same parent-role fallback as the project blocks); its ``model``
/ ``effort`` to every role.  ``pm pr model`` and the TUI's model popup
(``o``) edit them.

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
and return a provider name instead of a model identifier.  Any role in
``SESSION_TYPES`` may be routed; the setting is explicit per role, and a
role with no setting of its own follows its parent role (with nothing
configured at all it runs plain Claude on the CLI default).

Scenario 0 (``qa_interactive``) additionally keeps applying a pre-split
plain-model ``qa_scenario`` setting; see
:func:`_legacy_s0_resolution` for what that compatibility shim does and
does not inherit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

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

# Valid effort levels for the Claude CLI --effort flag.  This is the set the
# installed harness accepts (claude --help, 2.1.316: low, medium, high,
# xhigh, max).  ``None`` means "pass no --effort" and is distinct from any
# level.  A model or route may accept only a subset; see
# :func:`accepted_efforts_of` and ``ModelResolution.effort_status``.
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# The ambient Claude Code variable that overrides --effort for a session.
# ``auto``/``unset`` (and blank) mean "no override".
AMBIENT_EFFORT_ENV = "CLAUDE_CODE_EFFORT_LEVEL"

# Models that do NOT support the --effort flag
_NO_EFFORT_MODELS = {
    "haiku",
    "claude-haiku-4-5-20251001",
}

# supported_efforts metadata older than this is reported as stale.  It is
# still used (the alternative -- refusing a working route -- is worse), but
# never presented as fresh.
EFFORT_METADATA_STALE_DAYS = 30

# ``ModelResolution.effort_status`` values the displays mark (``*`` in the
# effort column, ``(overridden)`` on a route line) so a level pm could not
# confirm never reads as verified.  ``unverified`` is deliberately not
# marked: it is named in the effort notes so route tables stay readable.
MARKED_EFFORT_STATUSES = ("unsupported", "overridden")

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
    - effort: effort level to pass via --effort (low, medium, high, xhigh,
      max), or None to pass nothing (the CLI default)

    ``effort_requested`` is the level a setting selected before suppression
    (Haiku, an ambient override), so display can distinguish "nothing was
    configured" from "configured but not applicable".  ``effort_status``
    says how far PM can verify the level:

    - ``none``: nothing selected; the CLI default applies
    - ``cli``: a plain Claude model; the CLI/model decides
    - ``ok``: the selected route declares the level supported
    - ``unverified``: routed, but the route declares no supported_efforts
    - ``unsupported``: the route declares the level unsupported
    - ``not_applicable``: the model does not take effort (Haiku)
    - ``overridden``: CLAUDE_CODE_EFFORT_LEVEL decides the session (set
      ambiently or by the provider's own ``env:`` block)
    """
    model: str | None = None
    provider: str | None = None
    effort: str | None = None
    # Which setting decided each (for display): "PM_MODEL", "PR qa",
    # "PR", "provider x", "project qa_scenario", "global qa", ...  None
    # when nothing did (the CLI default).
    source: str | None = None
    # The setting that chose the effort, or the ambient variable's name.
    # Kept for a suppressed (not applicable) level too, where it names the
    # setting that asked for the level shown as "xhigh (n/a)".
    effort_source: str | None = None
    effort_requested: str | None = None
    effort_status: str = "none"
    effort_notes: list[str] = field(default_factory=list)
    # The level a provider's own ``env:`` block applies through
    # CLAUDE_CODE_EFFORT_LEVEL.  It overrides --effort inside the CLI, so
    # display shows it as the effective level (``effort`` stays None: pm
    # passes nothing, the provider's variable decides).  None unless the
    # assignment differs from what pm passes.
    effort_env_level: str | None = None
    # The Claude levels the selected route declares it accepts, or None
    # when it declares none.
    supported_efforts: tuple[str, ...] | None = None


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
    pr_entry: dict | None = None,
    use_env: bool = True,
) -> ModelResolution:
    """Resolve model and/or provider for a session type.

    Returns a ModelResolution with either a model ID or a provider name,
    plus an effort level.  Values prefixed with ``provider:`` (e.g.
    ``provider:ollama``) are resolved as provider names.  All other
    values are passed through as-is to the Claude CLI's --model flag
    (bare names like ``sonnet`` are resolved by the CLI itself).

    *pr_entry* is the PR the session belongs to: its model override (unless
    *pr_model* is given) and its effort settings apply.  *use_env* False
    ignores ``PM_MODEL`` / ``PM_EFFORT`` / ``CLAUDE_CODE_EFFORT_LEVEL``, so
    configuration checks see the configured settings rather than the
    caller's environment.
    """
    def _resolve_value(value: str) -> ModelResolution:
        if value.startswith(_PROVIDER_PREFIX):
            return ModelResolution(provider=value[len(_PROVIDER_PREFIX):])
        return ModelResolution(model=value)

    # Types to try: the requested type, then its fallback (e.g. qa_planning -> qa)
    fallback = _FALLBACK_TYPES.get(session_type)
    type_chain = (session_type, fallback) if fallback else (session_type,)
    if not isinstance(pr_entry, dict):
        pr_entry = None
    pr_source = "PR"
    if pr_model is None and pr_entry is not None:
        pr_model, role = _pr_override(pr_entry, "session_models", "model",
                                      session_type)
        pr_source = f"PR {role}" if role else "PR"

    # --- Model / provider resolution ---
    # 1. PM_MODEL env var
    if use_env and (env_model := os.environ.get("PM_MODEL")):
        resolution = _resolve_value(env_model)
        resolution.source = "PM_MODEL"
    # 2. PR-level override
    elif pr_model:
        resolution = _resolve_value(pr_model)
        resolution.source = pr_source
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
                resolution.source = f"project {st}"
                break
        # 4. Global setting (~/.pm/settings/model-<type>)
        if resolution is None:
            for st in type_chain:
                if (global_val := get_global_setting_value(f"model-{st}")):
                    resolution = _resolve_value(global_val)
                    resolution.source = f"global {st}"
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

    # Scenario 0 (qa_interactive) from before that type existed: a project
    # or global plain-model ``qa_scenario`` keeps applying to it.  Resolved
    # here so launches and every view agree.  Kept for compatibility: see
    # _legacy_s0_resolution for what it does (and must never) inherit.
    legacy = None
    if (session_type == "qa_interactive"
            and not resolution.model and not resolution.provider):
        legacy = _legacy_s0_resolution(project_data, use_env=use_env)
        if legacy is not None:
            resolution.model = legacy.model
            resolution.source = f"{legacy.source} (s0 legacy)"

    # --- Effort resolution ---
    notes: list[str] = []
    effort, effort_source = None, None
    # 1. PM_EFFORT env var.  Validated here: an invalid value must never
    #    reach --effort (validate_model_config reports configured ones).
    if use_env and (env_effort := os.environ.get("PM_EFFORT")):
        if is_effort_level(env_effort):
            effort, effort_source = env_effort, "PM_EFFORT"
        else:
            notes.append(f"ignoring invalid PM_EFFORT={env_effort!r} "
                         f"(valid: {list(EFFORT_LEVELS)})")
    # 2. The PR's role / PR-wide effort
    if not effort and pr_entry is not None:
        effort, role = _pr_override(pr_entry, "session_effort", "effort",
                                    session_type)
        effort_source = (f"PR {role}" if role else "PR") if effort else None
    # 3. The selected provider's own default effort
    if not effort and resolution.provider:
        effort = provider_effort(resolution.provider)
        effort_source = f"provider {resolution.provider}" if effort else None
    if not effort:
        # 4. Project-level effort config (try specific type, then fallback)
        effort_map = config_block(project_model_config(project_data),
                                  "session_effort")
        for st in type_chain:
            # A blank, non-string or unknown level counts as absent, as for
            # models (validate_model_config reports it).
            if is_effort_level(effort_map.get(st)):
                effort, effort_source = effort_map[st], f"project {st}"
                break
    # 5. Global setting (~/.pm/settings/effort-<type>)
    if not effort:
        for st in type_chain:
            level = get_global_setting_value(f"effort-{st}") or None
            if level and is_effort_level(level):
                effort, effort_source = level, f"global {st}"
                break
    # 6. Built-in default
    if not effort:
        for st in type_chain:
            level = DEFAULT_SESSION_EFFORT.get(st)
            if level and is_effort_level(level):
                effort, effort_source = level, "built-in"
                break
    if not effort and legacy is not None and legacy.effort:
        effort, effort_source = legacy.effort, legacy.effort_source

    # 7. The ambient Claude Code variable.  It overrides --effort inside the
    #    CLI, so pm must not report a different level than the one the
    #    session will use.  When pm has its own selection, pm wins and the
    #    launch unsets this variable (claude_launcher); with no pm
    #    selection, the ambient value is the session's level.  A provider
    #    that assigns the variable in its own ``env:`` block is explicit
    #    configuration: the launcher keeps it, so that value -- not the
    #    ambient one -- is what the session runs.
    ambient_level, ambient_raw = normalize_ambient_effort(
        os.environ.get(AMBIENT_EFFORT_ENV) if use_env else None)
    ambient_source = False
    if ambient_raw is not None and ambient_level is None:
        notes.append(f"ignoring invalid {AMBIENT_EFFORT_ENV}={ambient_raw!r} "
                     f"(valid: {list(EFFORT_LEVELS)})")
    elif ambient_level is not None and not effort:
        effort, effort_source = ambient_level, AMBIENT_EFFORT_ENV
        ambient_source = True
    # Whether the provider's own env block assigns the variable at all (a
    # level, ``auto``/``unset`` or a blank value): the launcher keeps any
    # such assignment, so a note below must not claim pm unsets it.  Only
    # read when there is something to reconcile, so the common launch path
    # keeps its single providers.yaml read.
    assigned_raw = (provider_effort_env(resolution.provider)
                    if ambient_level is not None else None)
    assigned_level = normalize_ambient_effort(assigned_raw)[0]

    # Suppress effort for models that don't support it (e.g. Haiku)
    resolution.effort_requested = effort
    if effort and resolution.model in _NO_EFFORT_MODELS:
        _log.debug("Suppressing effort=%s for model %s (not supported)",
                   effort, resolution.model)
        notes.append(f"effort={effort} suppressed: {resolution.model} does "
                     "not support the --effort flag")
        if ambient_level is not None:
            notes.append(
                f"{AMBIENT_EFFORT_ENV}={ambient_level} remains in the "
                "environment; pm passes no --effort for this model")
        # Keep ``effort_source``: the table shows the requested level as
        # "xhigh (n/a)", and "decided by: effort: project impl" is what
        # asked for it.  Nothing is passed to --effort (effort is None).
        effort = None
        resolution.effort_status = "not_applicable"
    elif ambient_source and assigned_level in (None, effort):
        notes.append(
            f"{AMBIENT_EFFORT_ENV}={ambient_level} selected the effort "
            "for this session (pm passes it as --effort)")
    elif (ambient_level is not None and effort and ambient_level != effort
          and assigned_raw is None):
        # A provider assignment is reported by _note_provider_effort_env;
        # claiming pm unsets the variable would contradict it (and be false:
        # the launcher keeps a provider's own value, even an ``auto`` one
        # that only means "no override").
        notes.append(
            f"{AMBIENT_EFFORT_ENV}={ambient_level} would override "
            f"--effort for the session; pm unsets it so {effort} "
            "applies")

    resolution.effort = effort
    # ``effort_source`` stays set for a suppressed (not applicable) level:
    # it names the setting that asked for the level the table shows as
    # "xhigh (n/a)".  With nothing selected at all there is no source.
    resolution.effort_source = (effort_source
                                if effort
                                or resolution.effort_status == "not_applicable"
                                else None)
    resolution.effort_notes = notes
    if resolution.effort_status != "not_applicable":
        _apply_effort_verification(resolution, effort)
        if effort and effort_source == AMBIENT_EFFORT_ENV:
            # The source, not the level's support, is the headline; the
            # verification notes (if any) are still in effort_notes.
            resolution.effort_status = "overridden"

    return resolution


def _legacy_s0_resolution(project_data: dict | None,
                          *, use_env: bool = True) -> ModelResolution | None:
    """The pre-``qa_interactive`` ``qa_scenario`` setting Scenario 0 keeps.

    Scenario 0 used to run as ``qa_scenario``, so a project or global
    plain-model ``qa_scenario`` from before the split must keep deciding
    the interactive session.  It is consulted only when neither
    ``qa_interactive`` nor its ``qa`` parent selects anything (the normal
    chain in :func:`resolve_model_and_provider`).

    This is a compatibility shim, not a route.  It reads project/global
    settings only -- a PR's ``session_models`` worker exception is not
    such a config and never moves s0 -- and it inherits only a plain
    model (and that setting's effort).  A ``qa_scenario`` that selects a
    provider is the workers' route and is deliberately not inherited: s0
    never follows workers onto a route, whose bridge, account or effort
    may not be what the user wants for the session they drive.

    Retiring the shim would silently move s0 to the CLI default for every
    config that sets only ``qa_scenario``, so it is retained.  Setting
    ``qa_interactive`` explicitly takes control, and ``pm pr model show``
    (and the TUI) label an inherited value ``(s0 legacy)``.
    """
    legacy = resolve_model_and_provider("qa_scenario",
                                        project_data=project_data,
                                        use_env=use_env)
    return legacy if legacy.model and not legacy.provider else None


def is_effort_level(value) -> bool:
    """Whether *value* is one of the levels the harness accepts."""
    return isinstance(value, str) and value in EFFORT_LEVELS


def normalize_ambient_effort(value) -> tuple[str | None, str | None]:
    """``(level, raw)`` for a ``CLAUDE_CODE_EFFORT_LEVEL`` value.

    ``auto``/``unset``/blank mean "no override" and yield ``(None, None)``.
    An unrecognised value yields ``(None, raw)`` so callers can report it.
    """
    if value is None:
        return None, None
    raw = value.strip()
    if not raw or raw.lower() in ("auto", "unset"):
        return None, None
    level = raw.lower()
    return (level, raw) if level in EFFORT_LEVELS else (None, raw)


def _provider_config_or_error(provider_name: str | None):
    """``(cfg, why)`` for *provider_name*: its ProviderConfig, or None.

    Read raw for display: a missing or invalid entry yields ``(None, why)``
    (the launch itself reports it with its one-line error).  Never raises.
    """
    if not provider_name:
        return None, None
    try:
        from pm_core.providers import get_provider
        return get_provider(provider_name, strict=True), None
    except Exception as exc:  # a broken entry is reported by the launch itself
        return None, str(exc) or type(exc).__name__


def _provider_config(provider_name: str | None):
    """The ProviderConfig of *provider_name*, or None (see above)."""
    return _provider_config_or_error(provider_name)[0]


def accepted_efforts_of(cfg) -> tuple[str, ...] | None:
    """The Claude levels *cfg* declares, or None.

    ``None`` means the route declares no ``supported_efforts`` (PM cannot
    verify it), which is distinct from an empty tuple (a route that
    declares it accepts none of the Claude levels).  Values outside
    ``EFFORT_LEVELS`` in the declaration (e.g. OpenRouter's ``none``) are
    dropped: they are not Claude levels and are never passed to --effort.
    Display code that already holds a ``ProviderConfig`` uses this so it
    does not re-read providers.yaml.
    """
    if cfg is None:
        return None
    declared = getattr(cfg, "supported_efforts", None)
    if declared is None:
        return None
    return tuple(level for level in EFFORT_LEVELS if level in declared)


def effort_env_of(cfg) -> str | None:
    """The effort variable *cfg* assigns, for an already-loaded config.

    See :func:`provider_effort_env`.
    """
    if cfg is None:
        return None
    if AMBIENT_EFFORT_ENV in cfg.env:
        value = cfg.env[AMBIENT_EFFORT_ENV]
    elif AMBIENT_EFFORT_ENV in cfg.alias_models:
        value = cfg.alias_models[AMBIENT_EFFORT_ENV]
    else:
        return None
    # A blank value is still an assignment: the launcher exports it, so it
    # is not a variable pm removes (Claude Code reads it as "no override").
    return value if isinstance(value, str) else None


def provider_effort_env(provider_name: str | None) -> str | None:
    """The ``CLAUDE_CODE_EFFORT_LEVEL`` a provider's env block assigns.

    ``alias_models`` is the older name for ``env`` and ``env`` wins where
    both set it, as in ``ProviderConfig._apply_env``.  A null value drops
    the variable rather than assigning one, so it yields None.  Any other
    value -- a level, ``auto``/``unset``, or a blank -- is the provider's
    explicit configuration: the launcher keeps it (it is never unset) and
    Claude Code applies it instead of ``--effort``.
    """
    return effort_env_of(_provider_config(provider_name))


def metadata_age_of(cfg) -> int | None:
    """Age in days of *cfg*'s metadata date, for an already-loaded config."""

    if cfg is None:
        return None
    raw = getattr(cfg, "supported_efforts_checked_at", "") or ""
    if not raw:
        return None
    try:
        from datetime import date
        checked = date.fromisoformat(str(raw))
    except ValueError:
        return None
    return (date.today() - checked).days


def unsupported_effort_problem(resolution: ModelResolution) -> str | None:
    """Why *resolution*'s effort is declared unsupported, or None.

    Shared by the display (``pm model show``'s notes, the set-time
    warnings) so the same finding reads the same everywhere.
    """
    if not (resolution.effort and resolution.effort_status == "unsupported"):
        return None
    return (f"effort {resolution.effort!r} is not in the selected route's "
            f"supported_efforts {list(resolution.supported_efforts or ())} "
            "(the router may reject or ignore it)")


def _note_provider_effort_env(resolution: ModelResolution,
                              effort: str | None, cfg=None,
                              accepted: tuple[str, ...] | None = None) -> None:
    """Note a provider env block that assigns the ambient effort variable.

    The launcher keeps a provider's explicit assignment (it is the user's
    own configuration) instead of unsetting it, so Claude Code applies
    that value rather than ``--effort``.  The display must not report pm's
    level as the one that runs.  *accepted* (the route's declared levels)
    lets the note say when the assigned level is not among them.
    """
    assigned = effort_env_of(cfg)
    if assigned is None:
        return
    level, _raw = normalize_ambient_effort(assigned)
    if level is None:
        no_override = (not assigned.strip()
                       or assigned.strip().lower() in ("auto", "unset"))
        if no_override:
            # "auto"/"unset" (and blank) are valid Claude values meaning
            # "no override": the provider assigns one explicitly, so
            # --effort still applies.
            resolution.effort_notes.append(
                f"provider {resolution.provider!r} sets "
                f"{AMBIENT_EFFORT_ENV}={assigned!r} (no override); "
                + (f"--effort {effort} applies" if effort
                   else "the CLI default applies"))
        else:
            resolution.effort_notes.append(
                f"provider {resolution.provider!r} sets {AMBIENT_EFFORT_ENV}="
                f"{assigned!r}, which is not a Claude effort level pm knows")
        return
    if level == effort:
        return
    # The assignment decides the session's level: display it (the effort
    # column would otherwise say "(default)" while the session runs this).
    resolution.effort_env_level = level
    if effort is None:
        resolution.effort_source = f"provider {resolution.provider} env"
    note = (f"provider {resolution.provider!r} sets {AMBIENT_EFFORT_ENV}="
            f"{level}; Claude Code applies it "
            + (f"instead of --effort {effort}" if effort
               else "for this provider's sessions"))
    if accepted is not None and level not in accepted:
        note += (f"; the route does not declare {level!r} in "
                 "supported_efforts")
    resolution.effort_notes.append(note)
    resolution.effort_status = "overridden"


def _apply_effort_verification(resolution: ModelResolution,
                               effort: str | None) -> None:
    """Fill effort status/notes for *effort* on *resolution* in place."""
    notes = resolution.effort_notes
    cfg, cfg_error = _provider_config_or_error(resolution.provider)
    if not effort:
        # Nothing selected: the CLI default applies.  No note -- the route's
        # declared levels are shown by `pm provider list/show`, and a note
        # here would read as a warning for a perfectly valid configuration.
        resolution.effort_status = "none"
        resolution.supported_efforts = accepted_efforts_of(cfg)
        _note_provider_effort_env(resolution, effort, cfg,
                                  resolution.supported_efforts)
        return

    accepted = accepted_efforts_of(cfg)
    resolution.supported_efforts = accepted
    if accepted is None:
        if resolution.provider:
            resolution.effort_status = "unverified"
            # A route whose entry cannot be read is not the same finding as
            # one that declares no levels; say which, so the note is never
            # a false statement about the file.
            if cfg_error:
                notes.append(f"route {resolution.provider!r} could not be "
                             "read; the level cannot be verified")
            else:
                notes.append(f"route {resolution.provider!r} declares no "
                             "supported_efforts; the level cannot be "
                             "verified")
        else:
            resolution.effort_status = "cli"
    elif effort in accepted:
        resolution.effort_status = "ok"
    else:
        resolution.effort_status = "unsupported"
        problem = unsupported_effort_problem(resolution)
        if problem:
            notes.append(problem)
    age = metadata_age_of(cfg)
    if age is not None and age > EFFORT_METADATA_STALE_DAYS:
        notes.append(
            f"supported_efforts metadata is {age} days old; refresh it "
            "(pm provider edit <name> --supported-efforts ...)")
    _note_provider_effort_env(resolution, effort, cfg, accepted)


def provider_effort(name: str) -> str | None:
    """The ``effort`` a providers.yaml entry sets, else None.

    Read raw: a missing or broken entry sets nothing here (the launch
    itself reports it with its remedy)."""
    try:
        from pm_core.providers import _provider_entries
        entry = _provider_entries().get(name)
    except Exception:
        return None
    effort = entry.get("effort") if isinstance(entry, dict) else None
    return effort if effort in EFFORT_LEVELS else None


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


def _route_effort_warnings(project_data: dict | None, roles_levels,
                           *, pr_entry: dict | None = None,
                           prefix: str = "") -> list[str]:
    """Warnings for explicit (role, level) settings the route rejects.

    Configuration-only (``use_env=False``): the caller's environment is not
    part of what project.yaml declares.  A warning, not an error: the
    metadata is dated and the launch still passes the level (see
    ``ModelResolution.effort_status``).
    """
    out = []
    for st, _ in roles_levels:
        res = resolve_model_and_provider(st, project_data=project_data,
                                         pr_entry=pr_entry, use_env=False)
        problem = unsupported_effort_problem(res)
        if problem:
            out.append(f"{prefix}{st}: {problem}")
    return out


def validate_model_config(project_data: dict | None) -> list[str]:
    """Return a list of problems with project.yaml's model settings: the
    ``model_config`` block and each PR's ``session_models``.

    An empty list means valid. Checks that:

    - ``session_models`` / ``session_effort`` keys are known session types
      (``SESSION_TYPES``);
    - ``session_models`` values are model names (other values are ignored);
    - ``session_effort`` values are valid effort levels (``EFFORT_LEVELS``);
    - a configured effort the selected route's ``supported_efforts``
      excludes (a warning: the metadata is dated and the launch still
      passes the level, see :func:`unsupported_effort_problem`);
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
        errors.extend(_route_effort_warnings(
            project_data,
            [(st, level) for st, level in effort_entries.items()
             if st in SESSION_TYPES and is_effort_level(level)]))
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
        efforts = pr.get("session_effort")
        role_efforts = efforts if isinstance(efforts, dict) else {}
        effort = pr.get("effort")
        if effort is not None and effort not in EFFORT_LEVELS:
            errors.append(f"prs[{pr.get('id')}].effort: invalid effort "
                          f"{effort!r} (ignored). Valid levels: "
                          f"{list(EFFORT_LEVELS)}")
        elif is_effort_level(effort):
            # The PR-wide effort decides every role without an entry of its
            # own (a role's own session_effort entry is checked, and
            # reported, by _route_effort_warnings below), so the same
            # rejected level on one route is one finding, not one per role
            # (the roles' routes may differ, so check each).
            seen_problems: list[str] = []
            for st in PR_SESSION_TYPES:
                if is_effort_level(role_efforts.get(st)):
                    continue
                problem = unsupported_effort_problem(
                    resolve_model_and_provider(
                        st, project_data=project_data, pr_entry=pr,
                        use_env=False))
                if problem and problem not in seen_problems:
                    seen_problems.append(problem)
                    errors.append(f"prs[{pr.get('id')}].effort: {problem}")
        if efforts is not None:
            where = f"prs[{pr.get('id')}].session_effort"
            if not isinstance(efforts, dict):
                errors.append(f"{where} must be a mapping")
            else:
                for st, level in efforts.items():
                    if st not in PR_SESSION_TYPES:
                        errors.append(f"{where}: unknown session type "
                                      f"{st!r}. Valid types: "
                                      f"{sorted(PR_SESSION_TYPES)}")
                    elif level not in EFFORT_LEVELS:
                        errors.append(f"{where}[{st!r}]: invalid effort "
                                      f"{level!r} (ignored). Valid levels: "
                                      f"{list(EFFORT_LEVELS)}")
                errors.extend(_route_effort_warnings(
                    project_data,
                    [(st, level) for st, level in efforts.items()
                     if st in PR_SESSION_TYPES and is_effort_level(level)],
                    pr_entry=pr, prefix=f"prs[{pr.get('id')}] "))
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

    For example, ``model: provider:experimental`` with
    ``session_models: {signoff: provider:my-router}`` keeps the experimental
    model for development while routing sign-off elsewhere. Role inheritance
    matches project configuration (e.g. qa_scenario -> qa, signoff -> review).
    """
    return _pr_override(pr_entry, "session_models", "model", session_type)[0]


def _pr_override(pr_entry: dict, role_key: str, all_key: str,
                 session_type: str | None):
    """``(value, role)``: the PR's *role_key* entry for *session_type* (or
    its parent role), else its *all_key* value with role None."""
    # A blank or non-string entry (hand-edited YAML) counts as absent: it
    # must neither drop the PR-wide value for that role nor raise at every
    # launch of it.  So does an unknown effort level (validate_model_config
    # reports it).
    usable = ((lambda v: is_effort_level(v)) if role_key == "session_effort"
              else _is_model_value)
    entries = pr_entry.get(role_key)
    if session_type and isinstance(entries, dict):
        for role in (session_type, _FALLBACK_TYPES.get(session_type)):
            if role and usable(entries.get(role)):
                return entries[role], role
    value = pr_entry.get(all_key)
    if role_key == "session_effort" and not usable(value):
        value = None
    return value, None


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
