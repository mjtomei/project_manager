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

Gated vs autonomous is the ``project.sign_off_autonomous`` flag (default gated —
the conservative bias).  On genuine ambiguity the router emits
``SIGNOFF_BLOCKED`` and escalates rather than merging.
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


def is_signoff_autonomous(data: dict) -> bool:
    """Whether sign-off auto-merges on a verified PASS.

    Reads ``project.sign_off_autonomous`` (default ``False`` — gated, i.e. a
    verified PASS is held for a human rather than merged).  Mirrors the
    ``project.skip_qa`` config pattern.
    """
    project = (data or {}).get("project") or {}
    return bool(project.get("sign_off_autonomous"))


def signoff_window_name(pr_entry: dict) -> str:
    """The tmux window name for a PR's sign-off window (e.g. ``signoff-#42``)."""
    return f"signoff-{_pr_display_id(pr_entry)}"


def _dir_has_content(path: Path) -> bool:
    """True when *path* is a directory containing at least one file (recursive)."""
    if not path.is_dir():
        return False
    return any(p.is_file() for p in path.rglob("*"))


def bug_fix_capture_status(pr_id: str,
                           session_tag: str | None = None) -> tuple[bool, bool]:
    """Return ``(has_pre_fix, has_post_fix)`` for a bug PR's impl captures.

    Bug-fix implementations write their *primary* evidence to
    ``$CAP/impl/pre-fix/`` (the reproduction on pre-fix code) and
    ``$CAP/impl/post-fix/`` (the post-fix verification) — see
    ``bug_fix_prompts``.  Sign-off requires BOTH to exist for a bug PR; a fix
    with either missing has not actually been demonstrated.

    Each is considered present only when its directory holds at least one file.
    """
    from pm_core.paths import captures_dir

    base = captures_dir(pr_id, session_tag=session_tag)
    if base is None:
        return (False, False)
    impl = base / "impl"
    return (_dir_has_content(impl / "pre-fix"),
            _dir_has_content(impl / "post-fix"))


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


def launch_signoff_window(data: dict, pr_entry: dict, *, fresh: bool = False,
                          background: bool = False,
                          transcript: str | None = None,
                          session_name: str | None = None) -> None:
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
        data, pr_id, session_name=pm_session)

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


def act_on_signoff_verdict(root: Path, pr_id: str, verdict: str | None, *,
                           autonomous: bool,
                           bug_captures_ok: bool | None = None) -> str:
    """Execute the routed hop for a sign-off *verdict*.

    Performs the status transition (guarded on the PR still being in
    ``sign_off`` so a concurrent sync that already moved it isn't clobbered)
    and returns a short hop token describing what pm should do next:

    * ``"merge"``   — autonomous + verified PASS; caller performs the merge.
                      (The router never merges; pm executes it.)
    * ``"held"``    — gated + verified PASS; PR stays in ``sign_off`` awaiting
                      a human.
    * ``"qa"``      — transitioned ``sign_off -> qa``; caller relaunches QA.
    * ``"review"``  — transitioned ``sign_off -> in_review``; caller relaunches
                      a review-loop iteration.
    * ``"impl"``    — transitioned ``sign_off -> in_progress``; caller
                      relaunches implementation.
    * ``"blocked"`` — escalate; PR stays in ``sign_off``.
    * ``"unknown"`` — no recognized verdict (still running / no decision yet).

    Note: ``"merge"`` and ``"held"`` do NOT themselves change status — merge
    sets ``merged`` via the existing merge path; a held PASS legitimately
    stays in ``sign_off``.

    ``bug_captures_ok`` is the bug-PR capture gate (``None`` when not a bug
    PR / not applicable).  When ``False`` (a bug PR is missing its pre-fix or
    post-fix capture) the fix has not been demonstrated, so a ``SIGNOFF_MERGE``
    is **overridden** to an impl bounce regardless of what the router emitted —
    a missing-capture bug PR can never reach merge.  This is the deterministic
    safety net behind the prompt's instruction to route ``SIGNOFF_IMPL``.
    """
    # Hard gate: a bug PR with a missing pre/post-fix capture must never merge.
    if bug_captures_ok is False and verdict == SIGNOFF_MERGE:
        verdict = SIGNOFF_IMPL

    if verdict == SIGNOFF_MERGE:
        return "merge" if autonomous else "held"
    if verdict == SIGNOFF_BLOCKED:
        return "blocked"

    hop_status = {
        SIGNOFF_REQA: ("qa", "qa"),
        SIGNOFF_REVIEW: ("review", "in_review"),
        SIGNOFF_IMPL: ("impl", "in_progress"),
    }.get(verdict or "")
    if hop_status is None:
        return "unknown"

    hop, to_status = hop_status
    transitioned = {"ok": False}

    def _apply(data):
        pr = store.get_pr(data, pr_id)
        if pr and pr.get("status") == "sign_off":
            pr["status"] = to_status
            _record_status_timestamp(pr, to_status)
            transitioned["ok"] = True

    store.locked_update(root, _apply)
    if not transitioned["ok"]:
        # PR was no longer in sign_off (e.g. moved by a concurrent sync).
        return "unknown"
    return hop
