"""``pm review <target>`` and ``pm review ui`` — launch literature-review sessions.

``pm review <target>`` opens its own tmux pane running a Claude session against
the augmented-cycle methodology context.  ``pm review ui`` routes to the walker
server (shipped in a later PR).  The pane-launch seam, registry resume-or-create
flow, artifact-id derivation, and context build are shared with
``pm plan literature-review`` (see :mod:`pm_core.cli.plan`).
"""

from datetime import datetime, timezone
from pathlib import Path

import click

from pm_core import store
from pm_core.cli import cli
from pm_core.review import registry, paths, context

REVIEW_ROLE = "literature-review"


# --- artifact-id derivation -------------------------------------------------

def derive_artifact_id(target: str, target_type: str) -> str:
    """Derive a review id from a target.

    - ``file``  → slugified basename (including extension): ``notes.md`` → ``notes-md``
    - ``plan``  → plan filename stem: ``plan-regression.md`` → ``plan-regression``
    - ``topic`` → slugified topic string
    """
    if target_type == "plan":
        return store.slugify(Path(target).stem)
    if target_type == "file":
        return store.slugify(Path(target).name)
    return store.slugify(target)


def _resolve_target_type(data: dict, target: str) -> str:
    """Classify a ``pm review`` target as plan / file / topic.

    Order: an existing plan id wins; then an existing file path; else topic.
    """
    plan_ids = {p.get("id") for p in (data.get("plans") or [])}
    if target in plan_ids:
        return "plan"
    candidate = Path(target)
    if candidate.exists() or (Path.cwd() / target).exists():
        return "file"
    return "topic"


def _resolve_plan_file(data: dict, target: str) -> str:
    """Return the stored plan ``file`` path for a plan target (id or path)."""
    for plan in data.get("plans") or []:
        if plan.get("id") == target or plan.get("file") == target:
            return plan.get("file", target)
    return target


# --- initial STATE.md -------------------------------------------------------

def write_initial_state(root: Path, review_id: str) -> None:
    """Write a minimal initial STATE.md for a freshly-created review.

    PR 2's ``md_writer.update_state`` is the canonical writer; this inline
    version keeps PR 1 self-contained until that lands.
    """
    state = paths.state_path(root, review_id)
    if state.exists():
        return
    now = datetime.now(timezone.utc).isoformat()
    state.write_text(
        "current-cycle: 0\n"
        "current-phase: not-started\n"
        "mode: human-reviewed\n"
        f"last-transition: {now}\n"
    )


# --- pane launch ------------------------------------------------------------

def launch_review_session(prompt: str, *, cwd: str, pm_root: Path | None = None,
                          role: str = REVIEW_ROLE,
                          target_window: str | None = None,
                          session_key: str = "review") -> None:
    """Launch a Claude review session in a tmux pane (or foreground).

    When inside tmux, splits a new pane (in ``target_window`` if given, else the
    active window), runs ``claude`` there, and registers it under ``role``.
    When not in tmux, falls back to a foreground ``claude`` run so the command
    still works from a plain terminal.  ``pm review`` passes
    ``target_window=None`` (its own pane); ``pm plan literature-review`` passes
    the plan's window id (same code path, different pane parent).

    ``cwd`` is Claude's working directory (the repo root — where the prompt
    file lands under ``pm/prompts/`` and where the session operates).
    ``pm_root`` is the pm dir used for Claude's session registry; it defaults to
    ``cwd`` for callers that don't distinguish the two.
    """
    from pm_core import tmux
    from pm_core.claude_launcher import build_claude_shell_cmd, launch_claude, find_claude

    pm_root = Path(pm_root) if pm_root is not None else Path(cwd)

    if not find_claude():
        click.echo("Claude CLI not found. Copy-paste this prompt into Claude Code:")
        click.echo(f"---\n{prompt}\n---")
        return

    if not tmux.in_tmux():
        launch_claude(prompt, session_key=session_key, pm_root=pm_root, cwd=cwd)
        return

    try:
        session = tmux.get_session_name()
    except Exception:
        session = None
    if not session:
        launch_claude(prompt, session_key=session_key, pm_root=pm_root, cwd=cwd)
        return

    # Already inside the target window — e.g. the TUI created this pane in the
    # plan's window and ran the command here. Run claude foreground in the
    # current pane instead of splitting an extra one, matching `pm plan review`.
    # (The standalone `pm review` / terminal path falls through and splits.)
    if target_window is not None and tmux.current_window_id() == target_window:
        launch_claude(prompt, session_key=session_key, pm_root=pm_root, cwd=cwd)
        return

    cmd = build_claude_shell_cmd(prompt=prompt, cwd=cwd)
    window = target_window if target_window is not None else tmux.get_window_id(session)
    try:
        from pm_core import pane_layout
        direction = pane_layout.preferred_split_direction(session, window)
    except Exception:
        direction = "v"
    pane_id = tmux.split_pane(session, direction, cmd, window=window)

    from pm_core import pane_registry
    pane_registry.register_pane(session, window, pane_id, role, cmd)
    try:
        tmux.select_pane(pane_id)
    except Exception:
        pass


# --- core flow --------------------------------------------------------------

def run_review(target: str, *, root: Path, target_type: str | None = None,
               target_window: str | None = None) -> str | None:
    """Resume-or-create a review against ``target`` and launch its session.

    Returns the review id, or None when nothing was launched (archived warning).
    """
    data = store.load(root)
    if target_type is None:
        target_type = _resolve_target_type(data, target)

    stored_target = target
    if target_type == "plan":
        stored_target = _resolve_plan_file(data, target)

    review_id = derive_artifact_id(stored_target, target_type)
    if not review_id:
        click.echo(
            f"Could not derive a review id from target {target!r} — it has no "
            "alphanumeric characters. Pick a more descriptive target.",
            err=True,
        )
        return None
    existing = registry.get_review(data, review_id)

    if existing and existing.get("status") == "archived":
        click.echo(
            f"Review '{review_id}' is archived. Unarchive it with "
            f"`pm review unarchive {review_id}` or pick a new target id.",
            err=True,
        )
        return None

    if existing:
        click.echo(f"Resuming review '{review_id}'.")
        paths.dir_for(root, review_id)  # ensure dir exists
    else:
        registry.create_review(root, review_id, stored_target, target_type)
        paths.dir_for(root, review_id)
        write_initial_state(root, review_id)
        click.echo(f"Created review '{review_id}'.")

    prompt = context.build_context(root, review_id, stored_target, target_type)
    # Claude runs from the repo root (the dir containing ``pm/``), matching every
    # other launcher — so prompt files land in ``<repo>/pm/prompts/`` and the
    # session can reach the whole repo. ``root`` itself (the pm dir) stays the
    # session-registry home. (Standalone PM repos keep root == repo root.)
    claude_cwd = root.parent if root.name == "pm" else root
    launch_review_session(
        prompt, cwd=str(claude_cwd), pm_root=root, role=REVIEW_ROLE,
        target_window=target_window, session_key=f"review:{review_id}",
    )
    return review_id


def _run_ui_server(port: int) -> None:
    """Route ``pm review ui`` to the walker server (shipped in a later PR)."""
    try:
        from pm_core.review.ui import server  # noqa: F401
    except ImportError:
        click.echo("The walker UI ships in a later PR — not available yet.")
        return
    server.run(port=port)  # pragma: no cover - exercised in the UI PR


# --- command ----------------------------------------------------------------

@cli.command("review")
@click.argument("target")
@click.option("--port", default=8765, type=int, help="Port for `pm review ui`.")
def review(target: str, port: int):
    """Launch a literature-review session against TARGET.

    TARGET is a plan id, a file path, or a topic string.  The special value
    ``ui`` launches the walker server instead.
    """
    if target == "ui":
        _run_ui_server(port)
        return
    # Honor the global -C / PM_PROJECT override (state_root), same as every
    # other command — find_project_root alone would ignore it.
    from pm_core.cli.helpers import state_root
    run_review(target, root=state_root())
