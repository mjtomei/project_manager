"""Tear down all live resources for a PR across implementation, review, and QA."""

from pm_core import container as container_mod
from pm_core import pane_registry, push_proxy
from pm_core import tmux as tmux_mod
from pm_core.cli.helpers import _pr_display_id, kill_pr_windows
from pm_core.paths import configure_logger

_log = configure_logger("pm.pr_cleanup")


def _candidate_window_names(display_id: str, session: str) -> list[str]:
    base = [display_id, f"review-{display_id}", f"merge-{display_id}",
            f"qa-{display_id}"]
    qa_prefix = f"qa-{display_id}-s"
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
    display_id = _pr_display_id(pr)
    summary = {"windows": [], "containers": [], "registry_windows": [],
               "sockets": []}

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
            window_names = _candidate_window_names(display_id, session)
            summary["registry_windows"] = pane_registry.unregister_windows(
                session, window_names)
        except Exception as e:  # pragma: no cover
            _log.warning("unregister_windows failed: %s", e)

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
