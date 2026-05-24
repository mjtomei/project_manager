"""Tear down all live resources for a PR across implementation, review, and QA."""

from pm_core import container as container_mod
from pm_core import pane_registry, push_proxy
from pm_core import runtime_state
from pm_core import tmux as tmux_mod
from pm_core.cli.helpers import kill_pr_windows, pr_window_names
from pm_core.paths import configure_logger

_log = configure_logger("pm.pr_cleanup")


def _candidate_window_names(pr: dict, session: str) -> list[str]:
    # Derive the exact window names + scenario prefix from the shared helper
    # so this registry-unregister path can't drift from kill_pr_windows / the
    # terminal-status sweep when a new window type is added.
    exact_names, qa_prefix = pr_window_names(pr)
    base = list(exact_names)
    try:
        for w in tmux_mod.list_windows(session):
            name = w.get("name", "")
            if name.startswith(qa_prefix):
                base.append(name)
    except Exception as e:  # pragma: no cover
        _log.warning("list_windows failed: %s", e)
    # Also include any registry windows matching the QA scenario prefix that
    # have outlived their tmux windows.
    try:
        reg = pane_registry.load_registry(session)
        for name in reg.get("windows", {}):
            if name.startswith(qa_prefix) and name not in base:
                base.append(name)
    except Exception as e:  # pragma: no cover
        _log.warning("load_registry failed: %s", e)
    return base


def cleanup_pr_resources(session: str | None, pr: dict) -> dict:
    """Remove every live resource for *pr*.

    Kills tmux windows, removes QA containers (and their push-proxy sockets
    via remove_container), and prunes the pane registry. Safe to call when
    no resources exist. Returns a summary dict::

        {"windows": [...], "containers": [...], "registry_windows": [...],
         "sockets": [...]}
    """
    pr_id = pr["id"]
    summary = {"windows": [], "containers": [], "registry_windows": [],
               "sockets": [], "runtime_state": False}

    if session:
        try:
            summary["windows"] = kill_pr_windows(session, pr)
        except Exception as e:  # pragma: no cover
            _log.warning("kill_pr_windows failed: %s", e)

    session_tag = session.removeprefix("pm-") if session else None
    try:
        summary["containers"] = container_mod.cleanup_pr_containers(
            pr_id, session_tag=session_tag)
    except Exception as e:  # pragma: no cover
        _log.warning("cleanup_pr_containers failed: %s", e)

    # Best-effort socket cleanup for any container we found (remove_container
    # already calls stop_push_proxy, but cover the case where a socket lingers
    # without its container).
    for cname in summary["containers"]:
        try:
            push_proxy.stop_push_proxy(cname)
            summary["sockets"].append(cname)
        except Exception:
            pass

    if session:
        try:
            window_names = _candidate_window_names(pr, session)
            summary["registry_windows"] = pane_registry.unregister_windows(
                session, window_names)
        except Exception as e:  # pragma: no cover
            _log.warning("unregister_windows failed: %s", e)

    # Drop the per-PR runtime state file so the next QA/review-loop run
    # starts from a clean slate. The file at ~/.pm/runtime/{pr_id}.json
    # holds every action entry (qa, review-loop, review, start, merge);
    # leaving it behind makes the picker think those loops are still
    # running after we've torn their panes/containers down.
    try:
        runtime_state.runtime_path(pr_id).unlink(missing_ok=True)
        summary["runtime_state"] = True
    except OSError as e:  # pragma: no cover
        _log.warning("runtime_state unlink failed: %s", e)

    _log.info("cleanup_pr_resources(%s): windows=%d containers=%d registry=%d",
              pr_id, len(summary["windows"]), len(summary["containers"]),
              len(summary["registry_windows"]))
    return summary


def format_summary(summary: dict) -> str:
    parts = []
    if summary["windows"]:
        parts.append(f"{len(summary['windows'])} window(s)")
    if summary["containers"]:
        parts.append(f"{len(summary['containers'])} container(s)")
    if summary["registry_windows"]:
        parts.append(f"{len(summary['registry_windows'])} registry entry(s)")
    return ", ".join(parts) if parts else "nothing to clean"
