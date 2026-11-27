"""Tear down all live resources for a PR across implementation, review, and QA."""

from pm_core import container as container_mod
from pm_core import pane_registry, push_proxy
from pm_core import runtime_state
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


def cleanup_pr_resources(session: str | None, pr: dict, *,
                         wait_reclaim: bool = False) -> dict:
    """Remove every live resource for *pr*.

    Kills tmux windows, removes QA containers (and their push-proxy sockets
    via remove_container), and prunes the pane registry. Then reclaims the
    container stores and image archives its QA scenarios left in scratch
    (pm_core.storage_reclaim: only what no remaining container mounts; the
    checkouts, captures and other scratch files stay) — in a background
    thread unless *wait_reclaim* (a CLI process must wait, or its exit
    would cut the deletion short). Safe to call when no resources exist.
    Returns a summary dict::

        {"windows": [...], "containers": [...], "registry_windows": [...],
         "sockets": [...], "reclaimed": [...] | "background",
         "reclaim_failed": [(path, error), ...],   # waited reclaim only
         "reclaim_busy": [scratch, ...]}  # left to another reclaim (ditto)
    """
    pr_id = pr["id"]
    display_id = _pr_display_id(pr)
    summary = {"windows": [], "containers": [], "registry_windows": [],
               "sockets": [], "runtime_state": False, "reclaimed": [],
               "reclaim_failed": [], "reclaim_busy": []}

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

    # Disposable scenario engine stores / image exports, now that this PR's
    # containers are gone (whatever still mounts a scratch dir keeps it).
    try:
        from pm_core import storage_reclaim
        if wait_reclaim:
            out = storage_reclaim.reclaim(pr_id, reason="pr-cleanup")
            summary["reclaimed"] = [str(d.path) for d in out.removed]
            summary["reclaim_failed"] = [(str(d.path), err)
                                         for d, err in out.failed]
            summary["reclaim_busy"] = [str(p.scratch) for p in out.plans
                                       if p.held == storage_reclaim.BUSY]
        else:
            storage_reclaim.reclaim_in_background(pr_id, reason="pr-cleanup")
            summary["reclaimed"] = "background"
    except Exception as e:  # pragma: no cover - best effort
        _log.warning("scenario storage reclaim failed: %s", e)

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

    # Drop the per-PR runtime state file so the next QA/review-loop run
    # starts from a clean slate. The file at
    # ~/.pm/runtime/{pm-session}/{pr_id}.json holds every action entry
    # (qa, review-loop, review, start, merge);
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
    if isinstance(summary.get("reclaimed"), list) and summary["reclaimed"]:
        parts.append(f"{len(summary['reclaimed'])} scenario store(s)/export(s)")
    if summary.get("reclaim_failed"):
        parts.append(f"{len(summary['reclaim_failed'])} reclaim failure(s)")
    return ", ".join(parts) if parts else "nothing to clean"
