"""View and change which command, model and effort each session runs with.

Shared by ``pm pr model`` / ``pm model`` and the TUI's model popup (``o``):

* :func:`role_rows` -- per session type, the effective model/provider,
  effort, command and route, and which setting decided each;
* :func:`set_pr_value` / :func:`set_project_value` -- edit a PR's or the
  project's settings on a loaded project.yaml dict (callers wrap them in
  ``store.locked_update``);
* :func:`check_model_value` -- refuse a ``provider:<name>`` that is not
  configured before it is written.

Credentials never appear here: a provider contributes its name, model,
launcher path and api_base only.
"""

from __future__ import annotations

from dataclasses import dataclass

from pm_core.model_config import (
    EFFORT_LEVELS, PR_SESSION_TYPES, SESSION_TYPES, _is_model_value,
    config_block, project_model_config, resolve_model_and_provider,
)

# PR-level keys: the all-role value and the per-role mapping.
_PR_KEYS = {"model": ("model", "session_models"),
            "effort": ("effort", "session_effort")}
_PROJECT_BLOCKS = {"model": "session_models", "effort": "session_effort"}


@dataclass
class RoleRow:
    role: str
    value: str          # "provider:<name>", a model name, or "(default)"
    model: str          # the --model the session gets, or "(default)"
    effort: str         # level or "(default)"
    command: str        # executable the session starts
    route: str          # router provider name, other provider, or "none"
    source: str         # setting that chose ``value`` ("(CLI default)")
    effort_source: str
    problem: str = ""   # provider not configured / invalid entry


def role_rows(data: dict, pr: dict | None = None, *,
              container_mode: bool | None = None) -> list[RoleRow]:
    """Effective settings per session type for *pr* (or the project).

    With a PR only the types a PR decides are listed (the watcher is a
    project session).
    """
    from pm_core import router_route
    from pm_core.providers import ProviderNotFoundError, get_provider
    if container_mode is None:
        from pm_core.container import is_container_mode_enabled
        container_mode = is_container_mode_enabled()
    rows = []
    for st in (PR_SESSION_TYPES if pr is not None else SESSION_TYPES):
        res = resolve_model_and_provider(st, pr_entry=pr, project_data=data)
        value = (f"provider:{res.provider}" if res.provider
                 else res.model or "(default)")
        model, command, route, problem = res.model, "claude", "none", ""
        if res.provider:
            route = res.provider
            try:
                cfg = get_provider(res.provider, strict=True)
            except ProviderNotFoundError as exc:
                cfg, problem = None, str(exc)
            if cfg is not None:
                model = model or cfg.model_flag()
                in_container = (container_mode and st in
                                router_route.CONTAINER_SESSION_TYPES)
                if cfg.type == "router" and cfg.launcher and not in_container:
                    command = cfg.launcher
                elif cfg.type == "router" and in_container:
                    command = "claude (container route bridge)"
        rows.append(RoleRow(
            role=st, value=value, model=model or "(default)",
            effort=res.effort or "(default)", command=command, route=route,
            source=res.source or "(CLI default)",
            effort_source=res.effort_source or "(CLI default)",
            problem=problem))
    return rows


def format_rows(rows: list[RoleRow]) -> list[str]:
    """Plain-text table of *rows* (CLI and TUI)."""
    head = ("role", "model / provider", "effort", "command", "decided by")
    table = [head] + [
        (r.role, r.value + (f" [{r.model}]" if r.value.startswith("provider:")
                            and r.model != "(default)" else ""),
         r.effort, r.command,
         f"model: {r.source}; effort: {r.effort_source}")
        for r in rows]
    widths = [max(len(row[i]) for row in table) for i in range(4)]
    lines = []
    for row in table:
        lines.append("  ".join(row[i].ljust(widths[i]) for i in range(4))
                     + "  " + row[4])
    for r in rows:
        if r.problem:
            lines.append(f"! {r.role}: {r.problem}")
    return lines


def check_model_value(value: str) -> str | None:
    """Why *value* cannot be selected, or None.  Only ``provider:<name>``
    values are checked (any other value is a model name for the CLI)."""
    if not isinstance(value, str) or not value.strip():
        return "a model value must be a non-empty string"
    if not value.startswith("provider:"):
        return None
    from pm_core.providers import ProviderNotFoundError, get_provider
    try:
        get_provider(value[len("provider:"):], strict=True)
    except ProviderNotFoundError as exc:
        return str(exc)
    return None


def _check_roles(roles, allowed) -> None:
    for role in roles or ():
        if role not in allowed:
            raise ValueError(f"unknown session type {role!r} "
                             f"(one of {', '.join(allowed)})")


def set_pr_value(pr: dict, kind: str, value: str | None,
                 roles: list[str] | None = None) -> None:
    """Set (or with *value* None remove) a PR's ``model`` or ``effort``.

    Without *roles* the PR-wide value changes; with them, those roles'
    entries.  Removing the PR-wide value keeps the role entries.
    """
    all_key, role_key = _PR_KEYS[kind]
    _check_roles(roles, PR_SESSION_TYPES)
    if kind == "effort" and value is not None and value not in EFFORT_LEVELS:
        raise ValueError(f"invalid effort {value!r} "
                         f"(one of {', '.join(EFFORT_LEVELS)})")
    if not roles:
        if value is None:
            pr.pop(all_key, None)
        else:
            pr[all_key] = value
        return
    entries = pr.get(role_key)
    entries = dict(entries) if isinstance(entries, dict) else {}
    for role in roles:
        if value is None:
            entries.pop(role, None)
        else:
            entries[role] = value
    if entries:
        pr[role_key] = entries
    else:
        pr.pop(role_key, None)


def clear_pr(pr: dict, kind: str) -> None:
    """Remove every PR-level *kind* setting (PR-wide and per role)."""
    for key in _PR_KEYS[kind]:
        pr.pop(key, None)


def set_project_value(data: dict, kind: str, role: str,
                      value: str | None) -> None:
    """Set (or with *value* None remove) the project's *kind* for *role*."""
    _check_roles([role], SESSION_TYPES)
    if kind == "effort" and value is not None and value not in EFFORT_LEVELS:
        raise ValueError(f"invalid effort {value!r} "
                         f"(one of {', '.join(EFFORT_LEVELS)})")
    block = _PROJECT_BLOCKS[kind]
    mc = project_model_config(data)
    if not isinstance(mc, dict):
        raise ValueError("project.yaml model_config is not a mapping; fix "
                         "it by hand")
    entries = config_block(mc, block)
    if not isinstance(entries, dict):
        raise ValueError(f"project.yaml model_config.{block} is not a "
                         "mapping; fix it by hand")
    entries = dict(entries)
    if value is None:
        entries.pop(role, None)
    else:
        entries[role] = value
    if entries:
        mc[block] = entries
    else:
        mc.pop(block, None)
    project = data.setdefault("project", {})
    if mc:
        project["model_config"] = mc
    else:
        project.pop("model_config", None)


def has_pr_override(pr: dict) -> bool:
    """Whether *pr* sets any model or effort of its own.  A blank or
    non-string entry counts as absent, as at launch and in the rows."""
    for all_key, role_key in _PR_KEYS.values():
        if _is_model_value(pr.get(all_key)):
            return True
        entries = pr.get(role_key)
        if isinstance(entries, dict):
            if any(_is_model_value(v) for v in entries.values()):
                return True
        elif entries is not None:  # malformed: the rows report it
            return True
    return False
