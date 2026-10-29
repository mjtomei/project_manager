"""LLM provider configuration for pm sessions.

Supports multiple provider types:
  - claude: Default Anthropic Claude API (no extra config needed)
  - local: Local model via Anthropic-compatible API (Ollama 0.14+,
    LM Studio 0.4.1+, llama.cpp).  Recommended for local models.
  - openai: OpenAI-compatible API endpoint (vLLM, etc.).
    Use only if your server doesn't speak the Anthropic Messages API.
  - router: A host-local Anthropic-compatible endpoint that holds its own
    upstream credentials (an account router or proxy).  pm only points
    Claude at it (ANTHROPIC_BASE_URL from ``api_base``), checks that it
    answers and, in container mode, bridges it into containers.  Signing in
    and refreshing the router's credentials happen outside pm, as for
    plain claude.  See
    pm_core/worker_route.py.

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

      my-router:
        type: router
        api_base: http://127.0.0.1:<port>   # where the router listens
        model: <model as the router names it>
        effort: high                        # optional default effort
        # All optional:
        classifier_model: <model for the auto-mode classifier>
        launcher: <host executable used instead of claude>
        remedy: <hint shown when a check finds the router down>
        env: {VAR: value}       # extra env; VAR: null drops a default
        unset_env: [VAR, ...]   # replaces the router default list
        probe_models: [...]     # models 'pm provider test --live' accepts

    default: claude

Provider resolution order:
  1. Explicit --provider flag
  2. PM_PROVIDER environment variable
  3. Per-session provider setting (~/.pm/sessions/{tag}/provider)
  4. Default from providers.yaml
  5. Falls back to "claude" (built-in, no config needed)
"""

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from pm_core.paths import configure_logger, pm_home, session_dir

_log = configure_logger("pm.providers")

PROVIDERS_FILE = "providers.yaml"

# Built-in provider that requires no configuration
BUILTIN_CLAUDE = "claude"

PROVIDER_TYPES = ("local", "openai", "claude", "router")

# Claude Code env vars that pick the model for aliases, background calls and
# subagents.  A router provider pins them all to its model by default.  The
# fable alias is what a skill's or slash command's ``model: fable``
# frontmatter and the /model picker's Fable entry switch the main loop to.
ROUTER_ALIAS_ENV_VARS = (
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "ANTHROPIC_SMALL_FAST_MODEL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
)


# Pin every subagent to one model.  CLAUDE_CODE_SUBAGENT_MODEL alone is only
# a default (Claude Code >= 2.1.251): an Agent call's ``model`` parameter or
# an agent definition's ``model`` frontmatter still wins, and the built-in
# Explore/Plan agents ignore it.  FORCE (>= 2.1.257) makes it override all
# of those -- without it a child asking for e.g. ``fable`` leaves the
# session's route and runs on the caller's own account.
SUBAGENT_MODEL_ENV = "CLAUDE_CODE_SUBAGENT_MODEL"
SUBAGENT_FORCE_ENV = "CLAUDE_CODE_SUBAGENT_MODEL_FORCE"

# Auto permission mode's classifier picks its own model and, without a
# setting, sends it unprefixed -- on a router that may mean another
# backend.  A router provider names the model to send instead
# (``classifier_model``).  Best effort only: Claude Code >= 2.1.311 prefers
# an account's server-configured classifier model over this variable
# (accepted by the user, 2026-10-27; see the pr-592e4bd impl spec).
AUTO_MODE_MODEL_ENV = "CLAUDE_CODE_AUTO_MODE_MODEL"

# What a router provider removes from its sessions' environment unless its
# ``unset_env`` says otherwise: the router authenticates upstream itself,
# so a stray key or token would only make Claude Code prompt about it
# (blocking an unattended worker).
ROUTER_DEFAULT_UNSET = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def subagent_pin_env(model: str | None,
                     provider: "ProviderConfig | None" = None) -> dict[str, str]:
    """Env that runs every subagent of a session on *model*.

    *model* is the session's effective ``--model`` value, kept verbatim
    (any route prefix and context suffix such as ``[1m]`` included).  The
    provider's own ``alias_models`` / ``env`` entries (``env`` wins, as in
    ``env_vars``) override both variables: a value replaces pm's, a null
    ``env`` value drops it (a null pin drops FORCE too).  Empty when pm
    selected no model: the session then runs on the CLI default and pm has
    nothing to enforce.
    """
    if not model:
        return {}
    own: dict[str, str | None] = {}
    if provider is not None:
        own.update(provider.alias_models)
        own.update(provider.env)
    if SUBAGENT_MODEL_ENV in own and own[SUBAGENT_MODEL_ENV] is None:
        return {}
    pin = {SUBAGENT_MODEL_ENV: own.get(SUBAGENT_MODEL_ENV) or model}
    force = own.get(SUBAGENT_FORCE_ENV, "1")
    if force is not None:
        pin[SUBAGENT_FORCE_ENV] = force
    return pin


# Set by a routed launch next to ANTHROPIC_BASE_URL, naming the URL pm put
# there, so a pm process started inside that session knows the inherited
# ANTHROPIC_BASE_URL is a route's and not the user's own.
ROUTE_BASE_URL_ENV = "PM_ROUTE_BASE_URL"

# The model-routing variables pm decides on every launch.  A launch sets the
# ones its selection needs and removes the others, so nothing a caller's
# environment carries (pm run inside a routed session exports all of them)
# picks a model or account for it.  ANTHROPIC_BASE_URL is removed only when
# it is a route's (_is_route_base_url): any other value is the user's own
# endpoint and stays.
LAUNCH_ROUTING_ENV_VARS = (*ROUTER_ALIAS_ENV_VARS, SUBAGENT_FORCE_ENV,
                           AUTO_MODE_MODEL_ENV, ROUTE_BASE_URL_ENV)


def _is_route_base_url(url: str | None, environ) -> bool:
    """Whether an inherited ANTHROPIC_BASE_URL is a route's.

    It is when it is the URL a routed launch recorded (ROUTE_BASE_URL_ENV),
    or the address of a router configured here, on the host or as its
    in-container forwarder (a session started before that marker existed,
    or by a host launcher that points Claude at the router itself).
    """
    if not url:
        return False
    url = url.rstrip("/")
    if url == (environ.get(ROUTE_BASE_URL_ENV) or "").rstrip("/"):
        return True
    return url in _configured_router_urls()


def _configured_router_urls() -> set[str]:
    """Host and in-container addresses of the routers configured here.

    Read on every launch that inherits an ANTHROPIC_BASE_URL, so the
    entries are read raw: one with no usable address (hand-edited
    providers.yaml: a null entry, a non-string api_base) is skipped and
    never fails a launch that does not use it, and a router whose other
    fields are broken (list_providers leaves it out) still names its
    address.
    """
    from pm_core import worker_route
    urls = set()
    for name, entry in _provider_entries().items():
        if not isinstance(entry, dict) or entry.get("type") != "router":
            continue
        base = entry.get("api_base")
        if not isinstance(base, str) or not base:
            continue
        urls.add(base)
        try:
            urls.add(worker_route.container_base_url(
                ProviderConfig(name=str(name), type="router", api_base=base)))
        except ValueError:
            pass
    return {u.rstrip("/") for u in urls}


# Launch variables whose values pm never prints, logs or puts in a pane
# command (an ``env`` entry may carry a key, e.g. ANTHROPIC_CUSTOM_HEADERS).
SECRET_ENV_VAR_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL",
                        "AUTH", "HEADER")


def is_secret_env_var(name: str) -> bool:
    """Whether launch variable *name* may hold a credential."""
    return any(part in name.upper() for part in SECRET_ENV_VAR_PARTS)


def launch_env(provider: "ProviderConfig", env: dict[str, str],
               model: str | None, environ=None,
               ) -> tuple[dict[str, str], tuple[str, ...]]:
    """``(assign, unset)``: the environment of one launch.

    *env* is what the selected *provider* contributes (its ``env_vars()``,
    or a router's container variant) and *model* the session's effective
    ``--model`` (None: the CLI default).  pm's own selection decides every
    LAUNCH_ROUTING_ENV_VARS entry: the subagent pin follows *model*, a
    routed launch records its URL, and every routing variable the
    selection does not set is unset rather than inherited from *environ*
    (the caller's environment, default ``os.environ``).  So are the
    provider's own unset_env_vars and an inherited route ANTHROPIC_BASE_URL
    when the selection names none.  Everything else is left as it is.
    """
    environ = os.environ if environ is None else environ
    assign = {**env, **subagent_pin_env(model, provider)}
    if provider.type == "router" and assign.get("ANTHROPIC_BASE_URL"):
        assign[ROUTE_BASE_URL_ENV] = assign["ANTHROPIC_BASE_URL"]
    unset = [*provider.unset_env_vars(), *LAUNCH_ROUTING_ENV_VARS]
    if ("ANTHROPIC_BASE_URL" not in assign
            and _is_route_base_url(environ.get("ANTHROPIC_BASE_URL"), environ)):
        unset.append("ANTHROPIC_BASE_URL")
    return assign, tuple(dict.fromkeys(v for v in unset if v not in assign))


class ProviderNotFoundError(LookupError):
    """An explicitly named provider is not configured in providers.yaml."""


class ProviderEntryError(ProviderNotFoundError):
    """A providers.yaml entry that cannot be read as a provider.

    Hand-edited YAML: a null or string entry, a non-string field, an
    unknown type, a list alias_models.  A ProviderNotFoundError, so every
    launch surface reports it as it reports a missing provider (one
    ``Error:`` line, ``QA stopped: …``) and nothing
    falls back to the built-in claude provider.
    """


class ProvidersFileUnreadableError(ProviderNotFoundError):
    """A named provider was not found because pm cannot read providers.yaml
    (not valid YAML, not a mapping, a ``providers`` block that is not a
    mapping), which it then reads as having no providers.  The message
    names the file's problem: "add it with 'pm provider add'" would be
    wrong (the entry may well be there) and that command refuses such a
    file (:class:`ProvidersFileError`)."""


# The other way out of a ProviderNotFoundError (its message names the
# first: adding the provider), quoted where a launch reports one.
PROVIDER_SETTING_HINT = ("or change the model setting that selects it "
                         "('pm model show' lists them, PR overrides included)")


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
      - router: host-local Anthropic-compatible endpoint that holds its
        own credentials.  Uses ANTHROPIC_BASE_URL only.  The router-only
        fields (launcher, remedy, classifier_model, unset_env,
        probe_models) are consumed by
        pm_core.worker_route and claude_launcher.

    Every type may set ``effort`` (the default effort of the sessions it
    runs; a PR's own effort setting wins, see model_config) and ``env``
    (extra variables; for a router a null value drops one of its
    defaults).  ``alias_models`` is the older name for ``env``.
    """
    name: str
    type: str = "claude"  # "claude", "local", "openai", or "router"
    api_base: str = ""
    api_key: str = ""
    model: str = ""
    capabilities: list[str] = field(default_factory=list)
    # router-only
    launcher: str = ""
    remedy: str = ""
    alias_models: dict[str, str] = field(default_factory=dict)
    classifier_model: str = ""
    unset_env: list[str] | None = None
    probe_models: list[str] = field(default_factory=list)
    # every type
    effort: str = ""
    env: dict[str, str | None] = field(default_factory=dict)

    def _apply_env(self, env: dict[str, str]) -> dict[str, str]:
        """*env* plus ``alias_models`` and ``env``; a null ``env`` value
        removes that variable (e.g. one of a router's defaults)."""
        env.update(self.alias_models)
        for var, value in self.env.items():
            if value is None:
                env.pop(var, None)
            else:
                env[var] = value
        return env

    def env_vars(self) -> dict[str, str]:
        """Return environment variables needed to use this provider.

        Values are resolved (``${VAR}`` references are expanded).  They are
        for the launched process's environment only: callers must not
        interpolate them into a shell command string, because that string is
        logged and kept as the tmux ``#{pane_start_command}``.
        """
        if self.type == "router":
            # Never an API key or token: the router injects the account's
            # credentials itself.  Pin Claude Code's alias/background
            # models to the route so no request falls through to the
            # caller's own account.
            env = {}
            if self.api_base:
                env["ANTHROPIC_BASE_URL"] = self.api_base
            # A router's model ids are often not names Claude Code knows;
            # without this it refuses them on context-window grounds.
            env["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] = "1"
            if self.model:
                for var in ROUTER_ALIAS_ENV_VARS:
                    env[var] = self.model
                env[SUBAGENT_FORCE_ENV] = "1"
            if self.classifier_model:
                env[AUTO_MODE_MODEL_ENV] = self.classifier_model
            env = self._apply_env(env)
            # A dropped pin leaves nothing to force (as subagent_pin_env).
            if (SUBAGENT_MODEL_ENV not in env
                    and SUBAGENT_FORCE_ENV not in self.env):
                env.pop(SUBAGENT_FORCE_ENV, None)
            return env
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
            # launch_env unsets every alias a launch does not set, so this
            # is where a provider's own alias models go.
            return self._apply_env(env)

        if self.type == "openai":
            env = {}
            if self.api_base:
                env["OPENAI_BASE_URL"] = self.api_base
            if self.api_key:
                env["OPENAI_API_KEY"] = _resolve_env_ref(self.api_key)
            return self._apply_env(env)

        return {}

    def unset_env_vars(self) -> tuple[str, ...]:
        """Environment variables to remove for this provider's sessions.

        Only what this provider removes on top of launch_env's routing
        variables: its ``unset_env`` when set, else for a router
        ROUTER_DEFAULT_UNSET.
        """
        if self.unset_env is not None:
            return tuple(self.unset_env)
        if self.type == "router":
            return ROUTER_DEFAULT_UNSET
        return ()

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


_PROVIDER_STR_FIELDS = ("type", "api_base", "api_key", "model", "launcher",
                        "remedy", "classifier_model", "effort")
# Keys earlier pm versions read (credential expiry checks and refresh).
# Credentials are managed outside pm, so an entry that still has them works
# as before; pm ignores them and 'pm provider list/show' says so.
RETIRED_PROVIDER_KEYS = ("credentials_file", "refresh_command")


def retired_keys(entry) -> list[str]:
    """The RETIRED_PROVIDER_KEYS a providers.yaml *entry* still sets."""
    if not isinstance(entry, dict):
        return []
    return [k for k in RETIRED_PROVIDER_KEYS if entry.get(k) is not None]


_PROVIDER_LIST_FIELDS = ("capabilities", "unset_env", "probe_models")


def _entry_problem(entry) -> str | None:
    """Why a providers.yaml entry is not a provider, or None if it is."""
    if not isinstance(entry, dict):
        return f"expected a mapping, got {type(entry).__name__}"
    for key in _PROVIDER_STR_FIELDS:
        value = entry.get(key)
        if value is not None and not isinstance(value, str):
            return f"{key!r} must be a string"
    if entry.get("type") and entry["type"] not in PROVIDER_TYPES:
        return (f"unknown type {entry['type']!r} "
                f"(one of {', '.join(PROVIDER_TYPES)})")
    for key in _PROVIDER_LIST_FIELDS:
        value = entry.get(key)
        if value is not None and not (
                isinstance(value, list)
                and all(isinstance(c, str) for c in value)):
            return f"{key!r} must be a list of names"
    aliases = entry.get("alias_models")
    if aliases is not None and not (
            isinstance(aliases, dict)
            and all(isinstance(k, str) and isinstance(v, str)
                    for k, v in aliases.items())):
        return "'alias_models' must map variable names to model names"
    env = entry.get("env")
    if env is not None and not (
            isinstance(env, dict)
            and all(isinstance(k, str) and (v is None or isinstance(v, str))
                    for k, v in env.items())):
        return "'env' must map variable names to strings (or null)"
    from pm_core.model_config import EFFORT_LEVELS
    if entry.get("effort") and entry["effort"] not in EFFORT_LEVELS:
        return (f"unknown effort {entry['effort']!r} "
                f"(one of {', '.join(EFFORT_LEVELS)})")
    return None


def _config_to_provider(name: str, entry: dict) -> ProviderConfig:
    """Build a ProviderConfig from a providers.yaml entry.

    Raises :class:`ProviderEntryError` for an entry that is not a provider
    (it used to surface as an AttributeError/ValueError traceback from
    whichever launch first touched the bad field).
    """
    problem = _entry_problem(entry)
    if problem:
        raise ProviderEntryError(
            f"provider {name!r} in {_providers_path()} is not a valid "
            f"entry: {problem} (fix it there, or replace it with "
            f"'pm provider add {name} ...')")
    return ProviderConfig(
        name=name,
        type=entry.get("type") or "local",
        api_base=entry.get("api_base") or "",
        api_key=entry.get("api_key") or "",
        model=entry.get("model") or "",
        capabilities=entry.get("capabilities") or [],
        launcher=entry.get("launcher") or "",
        remedy=entry.get("remedy") or "",
        alias_models=dict(entry.get("alias_models") or {}),
        classifier_model=entry.get("classifier_model") or "",
        unset_env=(list(entry["unset_env"])
                   if entry.get("unset_env") is not None else None),
        probe_models=list(entry.get("probe_models") or []),
        effort=entry.get("effort") or "",
        env=dict(entry.get("env") or {}),
    )


def _providers_path():
    """Return path to ~/.pm/providers.yaml."""
    return pm_home() / PROVIDERS_FILE


def _read_providers_file() -> tuple[dict[str, Any], str | None]:
    """``(data, problem)``: providers.yaml as a mapping, or ``({}, why)``
    when the file is there but cannot be read as one."""
    path = _providers_path()
    if not path.exists():
        return {}, None
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except OSError as e:
        _log.warning("Failed to read %s: %s", path, e)
        return {}, f"it cannot be read ({e.strerror or e})"
    except Exception as e:
        _log.warning("Failed to load %s: %s", path, e)
        mark = getattr(e, "problem_mark", None)
        return {}, "it is not valid YAML" + (
            f" (line {mark.line + 1})" if mark is not None else "")
    if not isinstance(data, dict):
        _log.warning("Ignoring %s: not a mapping", path)
        return {}, "it is not a mapping"
    return data, None


def load_providers() -> dict[str, Any]:
    """Load the providers.yaml config file.

    Returns the raw parsed YAML dict, or empty dict if file doesn't exist
    (or cannot be read as a mapping).
    """
    return _read_providers_file()[0]


def _provider_block(data: dict[str, Any]) -> tuple[dict, str | None]:
    """``(entries, problem)`` for the ``providers`` block of a read file: a
    blank block (every entry commented out) is empty, one that is not a
    mapping is ``({}, why)``."""
    entries = data.get("providers")
    if entries is None:
        return {}, None
    if not isinstance(entries, dict):
        return {}, "its 'providers' block is not a mapping"
    return entries, None


def providers_file_problem() -> str | None:
    """``"<path>: <why>"`` when pm reads providers.yaml as having no
    providers although the file is there, else None."""
    data, problem = _read_providers_file()
    problem = problem or _provider_block(data)[1]
    return f"{_providers_path()}: {problem}" if problem else None


class ProvidersFileError(ValueError):
    """providers.yaml cannot be changed: pm cannot read it as a mapping."""


def load_providers_for_edit() -> dict[str, Any]:
    """providers.yaml to change and save back, its ``providers`` block a
    mapping (a blank block, e.g. every entry commented out, reads as empty).

    Raises :class:`ProvidersFileError` when the file is there but pm cannot
    read it (not valid YAML, not a mapping, a ``providers`` block that is
    not a mapping): saving over it would lose what the user wrote, and
    ``load_providers`` reads such a file as empty.
    """
    data, problem = _read_providers_file()
    if problem is None:
        data["providers"], problem = _provider_block(data)
    if problem:
        raise ProvidersFileError(
            f"{_providers_path()} cannot be changed: {problem}. Fix it by "
            "hand (pm left it unchanged).")
    return data


@contextmanager
def providers_lock():
    """Hold the providers.yaml edit lock (an flock on a sidecar
    ``providers.yaml.lock``) across a read-modify-write, so concurrent
    ``pm provider`` edits never lose one another's changes.  Readers need
    no lock: :func:`save_providers` replaces the file atomically."""
    import fcntl
    path = _providers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(PROVIDERS_FILE + ".lock"), "a") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def save_providers(data: dict[str, Any]) -> None:
    """Write the providers config to ~/.pm/providers.yaml.

    The file may hold a literal API key, so it is always owner-only
    (0600).  A private temporary file in the same directory is replaced
    onto the target: ``mkstemp`` creates at 0600 regardless of the umask,
    and ``os.replace`` swaps the inode, which also tightens an existing
    permissive file (``write_text`` truncates in place and would leave its
    mode alone) and means a reader never sees a truncated file.  Swapping
    the inode also means a symlinked target is replaced by a regular file
    rather than written through — safer for a credentials file, and
    intentional.  Callers that read, change and save hold
    :func:`providers_lock`.
    """
    import yaml

    path = _providers_path()
    text = yaml.dump(data, default_flow_style=False, sort_keys=False)
    fd, tmp = tempfile.mkstemp(prefix=".providers.yaml.pm-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _log.info("Saved provider config to %s", path)


def get_provider(name: str | None = None, *,
                 strict: bool = False) -> ProviderConfig:
    """Resolve and return a provider configuration.

    Resolution order:
      1. Explicit name parameter
      2. PM_PROVIDER environment variable
      3. Per-session provider setting
      4. Default from providers.yaml
      5. Built-in "claude" provider

    With *strict*, an explicit *name* that is not configured raises
    :class:`ProviderNotFoundError` instead of falling back to the built-in
    claude provider (which would bill the caller's own account).
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
    providers = _provider_block(config)[0]
    if resolved not in providers:
        if strict and name:
            unreadable = providers_file_problem()  # "<path>: <why>"
            if unreadable:
                raise ProvidersFileUnreadableError(
                    f"provider {name!r} cannot be looked up in {unreadable}; "
                    "fix the file by hand")
            raise ProviderNotFoundError(
                f"provider {name!r} is not configured in {_providers_path()} "
                f"(add it with 'pm provider add {name} ...')")
        _log.warning("Provider %r not found in config, falling back to claude", resolved)
        return ProviderConfig(name=BUILTIN_CLAUDE)

    return _config_to_provider(resolved, providers[resolved])


def list_providers() -> list[ProviderConfig]:
    """List all configured providers (including built-in claude).

    Entries that are not providers are left out
    (:func:`invalid_provider_entries` names them).
    """
    result = [ProviderConfig(name=BUILTIN_CLAUDE)]
    for name, entry in _provider_entries().items():
        if _entry_problem(entry) is None:
            result.append(_config_to_provider(name, entry))
    return result


def invalid_provider_entries() -> dict[str, str]:
    """``{name: problem}`` for the providers.yaml entries that are not
    providers."""
    return {name: problem for name, entry in _provider_entries().items()
            if (problem := _entry_problem(entry))}


def _provider_entries() -> dict:
    return _provider_block(load_providers())[0]


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
    """Set the default provider in providers.yaml.

    Raises :class:`ProvidersFileError` when the file cannot be changed.
    """
    with providers_lock():
        config = load_providers_for_edit()
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
        return msgs


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

    # 3. Tool-use check
    if not check_tools or not provider.model:
        return result

    if provider.type == "local":
        result = _check_tools_anthropic(api_base, api_key, provider.model, result)
    elif provider.type == "openai":
        result = _check_tools_openai(api_base, api_key, provider.model, result)

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
