"""Sign-off step for the TUI auto-start scheduler.

The TUI is an auto-sequence driver just like ``pm pr auto-sequence``: a QA
PASS (or, with ``skip_qa``, a review PASS) hands the PR to the ``sign_off``
step, and the same state machine (:func:`pm_core.signoff.step_signoff`)
adopts / records / routes the router's verdict.  Only a fresh
``SIGNOFF_MERGE`` on the current HEAD reaches ``_maybe_auto_merge`` — O then
stops with the ready line, A merges.  Bounce verdicts restart the matching
TUI loop (QA, review loop, implementation); ``SIGNOFF_BLOCKED`` waits for a
human.

Everything here is auto-start-only and scoped to the target closures; the
manual ``i`` key (``pr_view.signoff_pr``) stays recommendation-only.
"""

from pm_core.paths import configure_logger
from pm_core import store

_log = configure_logger("pm.tui.signoff_ui")


def _driven(app, pr_id: str) -> bool:
    from pm_core.tui import auto_start as _auto_start
    return bool(app._root) and _auto_start.is_enabled(app) \
        and _auto_start.in_scope(app, pr_id)


def _acted(app) -> dict:
    """``{pr_id: (verdict, sha, policy)}`` of terminal outcomes already acted on."""
    d = getattr(app, "_signoff_acted", None)
    if not isinstance(d, dict):
        d = {}
        app._signoff_acted = d
    return d


def _reload(app) -> None:
    load = getattr(app, "_load_state", None)
    if callable(load):
        load()
    else:
        try:
            app._data = store.load(app._root)
        except store.ProjectYamlParseError:
            pass


def _load_pr(app, pr_id: str) -> dict | None:
    try:
        data = store.load(app._root)
    except (store.ProjectYamlParseError, OSError) as e:
        _log.warning("signoff_ui: %s", e)
        return None
    return store.get_pr(data, pr_id)


def start_signoff(app, pr_id: str) -> None:
    """Hand a QA-passed (or skip_qa review-passed) PR to the sign-off step.

    Transitions ``qa`` (or ``in_review`` under ``skip_qa``) -> ``sign_off``
    and runs one :func:`step`, which adopts an existing fresh verdict or
    launches the router window in the background.
    """
    if not _driven(app, pr_id):
        return
    project = (app._data or {}).get("project") or {}
    entry = ("qa", "in_review") if project.get("skip_qa") else ("qa",)
    from pm_core.cli.helpers import _record_status_timestamp

    moved = {"from": None}

    def apply(data):
        p = store.get_pr(data, pr_id)
        if p and p.get("status") in entry:
            moved["from"] = p["status"]
            p["status"] = "sign_off"
            _record_status_timestamp(p, "sign_off")

    try:
        store.locked_update(app._root, apply)
    except (store.StoreLockTimeout, store.ProjectYamlParseError) as e:
        app.log_message(f"Error: {e}")
        _log.warning("start_signoff: %s for %s: %s", type(e).__name__, pr_id, e)
        return
    if moved["from"]:
        _log.info("start_signoff: %s %s -> sign_off", pr_id, moved["from"])
        _reload(app)
        app.log_message(f"Auto-start: {pr_id} → sign-off")
    step(app, pr_id)


def _launch(app, pr_id: str, tdir) -> None:
    from pm_core.tui import pr_view
    from pm_core import signoff as signoff_mod
    try:
        tdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        app.log_message(f"[red]Cannot create transcript dir[/] {tdir}: {e}")
        return
    transcript = signoff_mod.signoff_transcript(tdir, pr_id)
    pr_view.run_command(
        app, f"pr signoff --background --transcript {transcript} {pr_id}")


def step(app, pr_id: str) -> None:
    """Advance one in-scope ``sign_off`` PR through the shared state machine."""
    from pm_core.tui import auto_start as _auto_start
    from pm_core import signoff as signoff_mod

    if not _driven(app, pr_id):
        return
    if pr_id in (getattr(app, "_pending_merge_prs", None) or set()):
        return  # merge-conflict tracking owns it now
    session = getattr(app, "_session_name", None)
    if not session:
        return
    pr = _load_pr(app, pr_id)
    if not pr or pr.get("status") != "sign_off":
        return

    tdir = _auto_start.get_transcript_dir(app)
    result = signoff_mod.step_signoff(app._root, pr, session=session, tdir=tdir)
    _log.info("signoff step %s: %r", pr_id, result)

    if result.action == "running":
        return
    if result.action == "launch":
        _acted(app).pop(pr_id, None)
        if result.stale:
            _reload(app)
            app.log_message(
                f"Sign-off for {pr_id} is stale (HEAD moved) — re-running")
        _launch(app, pr_id, tdir)
        return

    hop = result.hop
    _reload(app)
    if hop in ("ready_to_merge", "blocked"):
        key = (result.verdict, result.sha, _auto_start.policy_for(app, pr_id))
        if _acted(app).get(pr_id) == key:
            return
        _acted(app)[pr_id] = key
    else:
        _acted(app).pop(pr_id, None)

    if hop == "ready_to_merge":
        from pm_core.tui.review_loop_ui import _maybe_auto_merge
        _maybe_auto_merge(app, pr_id)
    elif hop == "blocked":
        app.log_message(
            f"[red bold]Sign-off BLOCKED[/] for {pr_id} — needs a human "
            "decision (see the sign-off report)", sticky=30)
    elif hop == "qa":
        app.log_message(f"Sign-off routed {pr_id} back to QA (SIGNOFF_REQA)")
        app._qa_loops.pop(pr_id, None)
        # Drop the finished run's PASS record: it would otherwise read as
        # "QA passed" to the catch-up hand-off before the new run starts.
        try:
            from pm_core import runtime_state as _rs
            _rs.set_action_state(pr_id, "qa", None)
        except Exception:
            _log.debug("runtime_state qa clear failed", exc_info=True)
        from pm_core.tui import qa_loop_ui
        qa_loop_ui.start_qa(app, pr_id)
    elif hop == "review":
        app.log_message(
            f"Sign-off routed {pr_id} back to review (SIGNOFF_REVIEW)")
        app._review_loops.pop(pr_id, None)
        fresh = _load_pr(app, pr_id)
        from pm_core.tui.review_loop_ui import _start_loop
        _start_loop(app, pr_id, fresh, transcript_dir=str(tdir))
    elif hop == "impl":
        app.log_message(
            f"Sign-off routed {pr_id} back to implementation (SIGNOFF_IMPL)")
        app._review_loops.pop(pr_id, None)
        app.run_worker(_relaunch_impl(app, pr_id))


async def _relaunch_impl(app, pr_id: str) -> None:
    """``pm pr start --fresh --background``: a bounce must relaunch the agent
    (an idle impl window would otherwise short-circuit the start)."""
    from pm_core.tui import auto_start as _auto_start
    launching = _auto_start._launching(app)
    launching.add(pr_id)
    try:
        await _auto_start._start_pr_quiet(app, pr_id, fresh=True)
    except Exception as e:
        _log.exception("signoff_ui: impl relaunch failed for %s", pr_id)
        app.log_message(f"Auto-start error: {e}")
    finally:
        launching.discard(pr_id)


def advance_all(app, prs: list[dict] | None = None) -> None:
    """Scheduler pass: drive every in-scope sign-off PR one step, and hand
    QA-passed PRs whose completion callback was missed (restart) to sign-off.
    """
    from pm_core.tui import auto_start as _auto_start
    if not app._root or not _auto_start.is_enabled(app):
        return
    if prs is None:
        prs = (app._data or {}).get("prs") or []
    for pr in list(prs):
        pr_id = pr.get("id")
        if not pr_id or not _auto_start.in_scope(app, pr_id, prs):
            continue
        status = pr.get("status")
        try:
            if status == "sign_off":
                step(app, pr_id)
            elif (status == "qa" and pr_id not in app._qa_loops
                  and _auto_start.recorded_qa_verdict(pr_id) == "PASS"):
                start_signoff(app, pr_id)
        except Exception:
            _log.exception("signoff_ui: advance failed for %s", pr_id)
