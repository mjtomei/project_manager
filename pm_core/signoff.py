"""Sign-off step — the dedicated lifecycle stage between ``qa`` and ``merged``.

Sign-off is a first-class PR step (status ``sign_off``) with its own tmux
window, mirroring the review/QA windows.  A Claude pane drives a *comprehensive*
review — walking every QA scenario and every step, aggregating evidence across
*all* stages (implementation repro/verify captures under ``impl/`` plus the
per-scenario captures under ``scenarios/<n>/``), reading the diff vs master, and
weighing the PR's scope.  It then emits a single **routing verdict** that pm
executes as the PR's next hop.

The router is *advisory + executor*: the Claude pane decides and records an audit
trail of ``pm pr note`` entries (so an autonomous merge is inspectable), but it
**never edits code** — every fix happens in impl/qa so it re-passes review+qa.
pm reads the emitted verdict (same transcript-polling mechanic as qa-finalize)
and performs the routed transition.

Sign-off **always gates at merge**: ``SIGNOFF_MERGE`` is a *recommendation*
(``ready_to_merge``) — sign-off never merges, and the autonomous-vs-gated merge
decision lives in the plan auto-start watcher (pr-ff9b728), not here.  On genuine
ambiguity the router emits ``SIGNOFF_BLOCKED`` and escalates rather than merging.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from pm_core import store
from pm_core import tmux as tmux_mod
from pm_core import prompt_gen
from pm_core.shell import shell_quote
from pm_core.cli.helpers import (
    _log,
    _pr_display_id,
    _record_status_timestamp,
)

# --- Routing verdicts ------------------------------------------------------
# The Claude pane emits exactly one of these on its own line.  pm polls the
# transcript for them (extract_verdict_from_transcript) and executes the hop.
SIGNOFF_MERGE = "SIGNOFF_MERGE"      # verified PASS -> merge (or human gate)
SIGNOFF_REQA = "SIGNOFF_REQA"        # PASS-unverified / misframed scenario -> re-qa
SIGNOFF_REVIEW = "SIGNOFF_REVIEW"    # a code change happened during QA -> review + qa
SIGNOFF_IMPL = "SIGNOFF_IMPL"        # real gap -> back to implementation
SIGNOFF_BLOCKED = "SIGNOFF_BLOCKED"  # ambiguity / out-of-scope / blocking PR -> escalate

SIGNOFF_VERDICTS = (
    SIGNOFF_MERGE,
    SIGNOFF_REQA,
    SIGNOFF_REVIEW,
    SIGNOFF_IMPL,
    SIGNOFF_BLOCKED,
)

# Distinct display markers per sign-off verdict (single source of truth for
# both the TUI tech tree and `pm pr list`).  Kept here (core, no TUI deps) so
# CLI and TUI render the recorded verdict identically.
SIGNOFF_VERDICT_ICONS = {
    SIGNOFF_MERGE: "▲",    # recommend merge (forward)
    SIGNOFF_REQA: "↻",     # re-qa
    SIGNOFF_REVIEW: "↩",   # back to review
    SIGNOFF_IMPL: "⇤",     # back to implementation
    SIGNOFF_BLOCKED: "⊘",  # escalate / hold
}

SIGNOFF_VERDICT_STYLES = {
    SIGNOFF_MERGE: "bold green",
    SIGNOFF_REQA: "bold magenta",
    SIGNOFF_REVIEW: "bold cyan",
    SIGNOFF_IMPL: "bold yellow",
    SIGNOFF_BLOCKED: "bold red",
}


def signoff_verdict_icon(verdict: str | None) -> str:
    """Return the display icon for a sign-off *verdict* (empty if unknown)."""
    return SIGNOFF_VERDICT_ICONS.get(verdict or "", "")


def signoff_window_name(pr_entry: dict) -> str:
    """The tmux window name for a PR's sign-off window (e.g. ``signoff-#42``)."""
    return f"signoff-{_pr_display_id(pr_entry)}"


# --- Verdict record + adoption --------------------------------------------
# A sign-off run records its routing verdict durably on the PR so a later
# auto-sequence tick can ADOPT it (no wasted re-run) instead of relaunching.
# The record is ``pr["signoff"] = {verdict, sha, ts, origin}`` where *sha* is
# the branch HEAD the verdict was computed against; a record is "fresh" when
# its sha matches the current HEAD (no code change since).

def head_sha(workdir: str | None) -> str | None:
    """Return the git HEAD sha of *workdir*, or None if unavailable."""
    if not workdir or not Path(workdir).exists():
        return None
    from pm_core import git_ops
    r = git_ops.run_git("rev-parse", "HEAD", cwd=workdir, check=False)
    sha = (r.stdout or "").strip()
    return sha or None


def record_signoff_verdict(root: Path, pr_id: str, verdict: str,
                           sha: str | None, origin: str) -> None:
    """Durably record a sign-off *verdict* on the PR (``pr['signoff']``).

    *origin* is ``"manual"`` (a hand-triggered ``pm pr signoff`` whose router
    self-recorded) or ``"auto-sequence"`` (the driver recorded a transcript
    verdict).  Recording is NOT acting — it never changes status; only
    :func:`apply_signoff_hop` (auto-sequence only) mutates state.
    """
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()

    def _apply(data):
        pr = store.get_pr(data, pr_id)
        if pr is not None:
            pr["signoff"] = {
                "verdict": verdict, "sha": sha, "ts": ts, "origin": origin,
            }

    store.locked_update(root, _apply)


def fresh_recorded_verdict(pr: dict, current_sha: str | None) -> str | None:
    """Return the recorded verdict if it is fresh (record sha == *current_sha*).

    Fresh means the verdict was computed against the current branch HEAD (no
    code change since), so auto-sequence can adopt it instead of relaunching.
    Returns None when there is no record, it carries no verdict, the sha is
    unknown, or the record is stale.
    """
    record = (pr or {}).get("signoff") or {}
    verdict = record.get("verdict")
    sha = record.get("sha")
    if verdict and sha and current_sha and sha == current_sha:
        return verdict
    return None


def latest_signoff_verdict(pr: dict) -> str | None:
    """Return the most recently recorded sign-off verdict, fresh or not.

    Used for display (icons / ``pm pr list``); does not consider staleness.
    """
    return ((pr or {}).get("signoff") or {}).get("verdict") or None


def _evidence_pane_cmd(pr_id: str, display_id: str, title: str,
                       workdir: str, diff_ref: str) -> str:
    """Build the left ("evidence") pane shell command.

    Prints the cross-stage evidence surface the sign-off reviewer reads:
    the per-PR captures tree (impl/ + scenarios/), the QA status, and the
    full diff vs the base branch.  This is the plain shell stand-in for the
    richer behavior-report surface (pr-8e693f6); the rich surface links from
    here once it lands.

    All user-controlled values (title) are ``shell_quote``'d — an apostrophe
    in a PR title would otherwise break the surrounding shell quoting and
    kill the pane before tmux registers the window.
    """
    shell = os.environ.get("SHELL", "/bin/bash")
    header = f"=== Sign-off: {display_id} — {title} ==="
    return (
        f"cd {shell_quote(workdir)}"
        f" && {{ echo {shell_quote(header)}"
        f" && echo ''"
        f" && echo '--- Cross-stage evidence (captures) ---'"
        f" && CAP=\"$(pm qa captures-path {shell_quote(pr_id)} 2>/dev/null)\""
        f" && if [ -n \"$CAP\" ] && [ -d \"$CAP\" ]; then"
        f"      find \"$CAP\" -maxdepth 3 -print | sort;"
        f"    else echo '(no captures found)'; fi"
        f" && echo ''"
        f" && echo '--- QA status (latest qa_status.json) ---'"
        f" && QS=$(ls -t \"$HOME\"/.pm/workdirs/qa/{shell_quote(pr_id)}-*/qa_status.json"
        f"        2>/dev/null | head -1)"
        f" && if [ -n \"$QS\" ]; then cat \"$QS\"; else echo '(no qa status)'; fi"
        f" && echo ''"
        f" && echo '--- Change summary ---'"
        f" && git --no-pager diff --stat {diff_ref}...HEAD"
        f" && echo ''"
        f" && echo '--- Full diff ---'"
        f" && git --no-pager diff {diff_ref}...HEAD"
        f"; }} | less -R"
        f"; exec {shell}"
    )


def _prerender_captures_markdown(pr_id: str, session_name: str | None) -> None:
    """Pre-render every ``.md`` under the PR's captures dir to a sibling
    ``.md.html`` so the sign-off agent can link the rendered HTML rather than
    raw markdown (which browsers display as plaintext over ``file://``).

    Deterministic: runs in-process before the agent starts and is idempotent.
    Failures are logged and swallowed — the agent can still run without the
    rendered siblings.
    """
    try:
        from pm_core.paths import captures_dir
        from pm_core.markdown_render import render_md_file

        tag = session_name.removeprefix("pm-") if session_name else None
        cap = captures_dir(pr_id, session_tag=tag)
        if cap is None or not cap.is_dir():
            return
        for md in cap.rglob("*.md"):
            try:
                render_md_file(md)
            except Exception as exc:  # noqa: BLE001
                _log.warning("pre-render %s failed: %s", md, exc)
    except Exception as exc:  # noqa: BLE001
        _log.warning("captures markdown pre-render skipped: %s", exc)


def launch_signoff_window(data: dict, pr_entry: dict, *, fresh: bool = False,
                          background: bool = False,
                          transcript: str | None = None,
                          session_name: str | None = None,
                          origin: str = "manual") -> None:
    """Launch a tmux sign-off window: evidence pane + Claude review pane.

    Mirrors ``pm_core.cli.pr._launch_review_window``: existing-window fast
    path (switch unless ``fresh``), capture watching sessions on a fresh
    rebuild, two panes registered in the pane registry with roles
    ``signoff-evidence`` / ``signoff-claude``, switch watching sessions onto
    the new window, then rebalance.
    """
    # Imported lazily to avoid a heavy import cycle at module import time.
    from pm_core.cli.helpers import _get_pm_session, _ensure_workdir, state_root
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core import pane_layout, pane_registry, home_window
    from pm_core.model_config import (
        resolve_model_and_provider, get_pr_model_override,
    )

    if not tmux_mod.has_tmux() or not tmux_mod.in_tmux():
        print("Sign-off window requires tmux.")
        return

    pm_session = session_name or _get_pm_session()
    if not pm_session or not tmux_mod.session_exists(pm_session):
        print(f"Sign-off window: tmux session '{pm_session}' not found.")
        return

    workdir = pr_entry.get("workdir")
    if not workdir or not Path(workdir).exists():
        root = state_root()
        workdir = _ensure_workdir(data, pr_entry, root)
        if not workdir:
            print(f"Sign-off window: no workdir for {pr_entry['id']}. "
                  "Start the PR first.")
            return

    pr_id = pr_entry["id"]
    display_id = _pr_display_id(pr_entry)
    title = pr_entry.get("title", "")
    base_branch = data.get("project", {}).get("base_branch", "master")
    window_name = signoff_window_name(pr_entry)

    # Fast path: existing window + not fresh -> just switch.
    existing = tmux_mod.find_window_by_name(pm_session, window_name)
    sessions_on_signoff: list[str] = []
    if existing:
        if fresh:
            sessions_on_signoff = tmux_mod.sessions_on_window(
                pm_session, existing["id"])
            home_window.park_if_on(pm_session, existing["id"])
            tmux_mod.kill_window(pm_session, existing["id"])
            print(f"Killed existing sign-off window '{window_name}'")
        else:
            tmux_mod.select_window(pm_session, existing["id"])
            print(f"Switched to existing sign-off window '{window_name}'")
            return

    _resolution = resolve_model_and_provider(
        "signoff",
        pr_model=get_pr_model_override(pr_entry),
        project_data=data,
    )

    signoff_prompt = prompt_gen.generate_signoff_prompt(
        data, pr_id, session_name=pm_session, origin=origin)

    # Container cwd quirk mirrors review: Claude's cwd is /workspace inside a
    # container, so the transcript symlink + prompt file must target the
    # mounted host path via write_dir.
    from pm_core.container import (
        is_container_mode_enabled, _CONTAINER_WORKDIR,
        wrap_claude_cmd, ContainerError, remove_container, _make_container_name,
    )
    if is_container_mode_enabled():
        _claude_cwd = _CONTAINER_WORKDIR
        _claude_write_dir = workdir
    else:
        _claude_cwd = workdir
        _claude_write_dir = None

    claude_cmd = build_claude_shell_cmd(
        prompt=signoff_prompt,
        transcript=transcript,
        cwd=_claude_cwd,
        write_dir=_claude_write_dir,
        model=_resolution.model,
        provider=_resolution.provider,
        effort=_resolution.effort,
        session_type="signoff")

    _prerender_captures_markdown(pr_id, pm_session)

    branch = pr_entry.get("branch", "")
    if is_container_mode_enabled():
        remove_container(_make_container_name(f"signoff-{pr_id}"))
        _stag = pm_session.removeprefix("pm-") if pm_session else None
        try:
            claude_cmd, _cname = wrap_claude_cmd(
                claude_cmd, workdir, label=f"signoff-{pr_id}",
                allowed_push_branch=branch,
                session_tag=_stag,
                pr_id=pr_id)
        except ContainerError as e:
            print(str(e))
            return

    # background -> don't steal focus (auto-sequence); explicit switch below
    # moves exactly the sessions that were watching the old window.
    switch = not background

    backend_name = data.get("project", {}).get("backend", "vanilla")
    diff_ref = base_branch if backend_name == "local" else f"origin/{base_branch}"

    try:
        evidence_cmd = _evidence_pane_cmd(
            pr_id, display_id, title, workdir, diff_ref)
        evidence_pane = tmux_mod.new_window_get_pane(
            pm_session, window_name, evidence_cmd, workdir, switch=switch)
        if not evidence_pane:
            print(f"Sign-off window: failed to create tmux window '{window_name}'.")
            return

        claude_pane = tmux_mod.split_pane_at(
            evidence_pane, "h", claude_cmd, background=True)

        wid_result = subprocess.run(
            tmux_mod._tmux_cmd("display", "-t", evidence_pane, "-p",
                               "#{window_id}"),
            capture_output=True, text=True,
        )
        signoff_win_id = wid_result.stdout.strip()
        if signoff_win_id:
            tmux_mod.set_shared_window_size(pm_session, signoff_win_id)
            panes = [(claude_pane, "signoff-claude", claude_cmd)]
            if evidence_pane:
                panes.append((evidence_pane, "signoff-evidence", "evidence-shell"))
            for pane_id, role, cmd in panes:
                pane_registry.register_pane(
                    pm_session, signoff_win_id, pane_id, role, cmd)

            def _reset_user_modified(raw):
                d = pane_registry._prepare_registry_data(raw, pm_session)
                wd = pane_registry.get_window_data(d, signoff_win_id)
                wd["user_modified"] = False
                return d

            pane_registry.locked_read_modify_write(
                pane_registry.registry_path(pm_session), _reset_user_modified)

        if sessions_on_signoff:
            tmux_mod.switch_sessions_to_window(
                sessions_on_signoff, pm_session, window_name)

        if signoff_win_id:
            pane_layout.rebalance(pm_session, signoff_win_id)

        print(f"Opened sign-off window '{window_name}'")
    except Exception as e:
        _log.warning("Failed to launch sign-off window: %s", e)
        print(f"Sign-off window error: {e}")


# Hops that carry a state side-effect (a sign_off -> X status transition).
# ready_to_merge / blocked / unknown carry NO state change.
_BOUNCE_HOP_STATUS = {"qa": "qa", "review": "in_review", "impl": "in_progress"}


def decide_signoff_hop(verdict: str | None) -> str:
    """Pure DECISION half of sign-off routing — maps a verdict to a hop token.

    This function has **no side effects**: it never touches project state. It is
    safe to call from any context (including a manual / recommendation-only
    ``pm pr signoff``).  The state mutation lives in :func:`apply_signoff_hop`,
    which is invoked ONLY from the auto-sequence driver — so a sign-off verdict
    can cause an actual transition (for ANY hop, not just merge) only under
    auto-sequence.

    Sign-off **always gates at merge**: ``SIGNOFF_MERGE`` is always a
    *recommendation* (``"ready_to_merge"``) — sign-off never merges. The actual
    auto-merge-vs-hold decision belongs to the plan auto-start watcher
    (pr-ff9b728) per its per-plan config.

    Returns one of:

    * ``"ready_to_merge"`` — the router recommends merge; the PR stays in
      ``sign_off`` (pm/the watcher decides the merge).
    * ``"qa"`` / ``"review"`` / ``"impl"`` — a bounce (apply_signoff_hop will
      transition sign_off -> qa / in_review / in_progress).
    * ``"blocked"`` — escalate; the PR stays in ``sign_off``.
    * ``"unknown"`` — no recognized verdict (still running / no decision yet).
    """
    if verdict == SIGNOFF_MERGE:
        return "ready_to_merge"
    if verdict == SIGNOFF_BLOCKED:
        return "blocked"
    return {
        SIGNOFF_REQA: "qa",
        SIGNOFF_REVIEW: "review",
        SIGNOFF_IMPL: "impl",
    }.get(verdict or "", "unknown")


def apply_signoff_hop(root: Path, pr_id: str, hop: str) -> str:
    """SIDE-EFFECT half of sign-off routing — perform a bounce hop's transition.

    **Auto-sequence only.**  Keeping the mutation here (separate from the pure
    :func:`decide_signoff_hop`) enforces the invariant that a sign-off verdict
    only ever changes state under the auto-sequence driver; manual
    ``pm pr signoff`` decides/recommends but never mutates.

    For a bounce hop (``qa`` / ``review`` / ``impl``) this transitions
    ``sign_off -> qa / in_review / in_progress`` (guarded on the PR still being
    in ``sign_off`` so a concurrent sync isn't clobbered), returning the hop, or
    ``"unknown"`` if the PR already left ``sign_off``.  ``ready_to_merge`` /
    ``blocked`` / ``unknown`` carry no state change and are returned unchanged
    (the PR legitimately stays in ``sign_off`` — pm/the watcher owns the merge).
    """
    to_status = _BOUNCE_HOP_STATUS.get(hop)
    if to_status is None:
        return hop  # ready_to_merge / blocked / unknown: no state change

    transitioned = {"ok": False}

    def _apply(data):
        pr = store.get_pr(data, pr_id)
        if pr and pr.get("status") == "sign_off":
            pr["status"] = to_status
            _record_status_timestamp(pr, to_status)
            # Consume the recorded verdict: a bounce sends the PR back through a
            # step that may NOT change the branch HEAD (re-qa never commits), so
            # leaving the record in place would let a later sign_off re-entry
            # re-adopt the same (now spent) fresh verdict and loop forever.
            pr.pop("signoff", None)
            transitioned["ok"] = True

    store.locked_update(root, _apply)
    return hop if transitioned["ok"] else "unknown"
