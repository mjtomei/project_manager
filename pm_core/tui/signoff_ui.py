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
from pm_core.tui.auto_start import CONFIRM_HOLD_SECONDS

_log = configure_logger("pm.tui.signoff_ui")

# Hand-off outcome lines ("→ sign-off", a lock "waits" or "Error:") are
# forced and held like auto-start's other confirmations: under skip_qa they
# follow the sticky "Review loop done … PASS" line in the same frame, which
# dropped them unseen (S50).  The hold queues them behind the line before.
_SHOWN = {"force": True, "hold": CONFIRM_HOLD_SECONDS}


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


def _lock_waits(app) -> set:
    """PR ids whose sign-off hand-off already said it waits for the lock."""
    s = getattr(app, "_signoff_lock_waits", None)
    if not isinstance(s, set):
        s = set()
        app._signoff_lock_waits = s
    return s


def start_signoff(app, pr_id: str,
                  lock_timeout: float = store.LOCK_TIMEOUT_SECONDS
                  ) -> bool | None:
    """Hand a QA-passed (or skip_qa review-passed) PR to the sign-off step.

    Transitions ``qa`` (or ``in_review`` under ``skip_qa``) -> ``sign_off``
    and runs one :func:`step`, which adopts an existing fresh verdict or
    launches the router window in the background.

    Callers that retry on the poll timer (a QA completion follow-up, the
    scheduler pass) pass ``lock_timeout=store.NO_WAIT``: while another pm
    process holds the lock (an open ``pm edit``) it says so once and
    returns False, without a 2 s wait or an "Error:" line per retry
    (RQ38).  A one-shot caller (the skip_qa review PASS, which nothing
    retries) keeps the default wait, so a brief holder does not lose the
    hand-off.
    """
    if not _driven(app, pr_id):
        _lock_waits(app).discard(pr_id)
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

    waiting = _lock_waits(app)
    try:
        store.locked_update(app._root, apply, timeout=lock_timeout)
    except store.StoreLockTimeout as e:
        if lock_timeout == store.NO_WAIT:
            if pr_id not in waiting:
                waiting.add(pr_id)
                _log.warning("start_signoff: %s waits for the project.yaml "
                             "lock", pr_id)
                app.log_message(
                    f"Sign-off for {pr_id} waits for project.yaml to be "
                    f"unlocked: {store.LOCK_BUSY_REASON}", **_SHOWN)
            return False
        waiting.discard(pr_id)
        app.log_message(f"Error: {e}", **_SHOWN)
        _log.warning("start_signoff: StoreLockTimeout for %s: %s", pr_id, e)
        return False
    except store.ProjectYamlParseError as e:
        waiting.discard(pr_id)
        # Forced only for the one-shot caller: a retried one meets the same
        # unloadable file on every tick.
        app.log_message(f"Error: {e}",
                        **(_SHOWN if lock_timeout != store.NO_WAIT else {}))
        _log.warning("start_signoff: %s for %s: %s", type(e).__name__, pr_id, e)
        return False  # project.yaml could not be loaded: retry
    waiting.discard(pr_id)
    if moved["from"]:
        _log.info("start_signoff: %s %s -> sign_off", pr_id, moved["from"])
        _launched_at(app).pop(pr_id, None)
        _reload(app)
        app.log_message(f"Auto-start: {pr_id} → sign-off", **_SHOWN)
    step(app, pr_id)


# A launch that fails to produce a window (no tmux, CLI error) would
# otherwise be retried — synchronously — on every 5 s poll.  Only the
# "window gone" relaunch is throttled: a fresh sign_off entry or a stale-run
# relaunch always launches.
RELAUNCH_BACKOFF_SECONDS = 60.0


def _launched_at(app) -> dict:
    d = getattr(app, "_signoff_launched_at", None)
    if not isinstance(d, dict):
        d = {}
        app._signoff_launched_at = d
    return d


def _launch(app, pr_id: str, tdir, force: bool = False) -> None:
    import time
    from pm_core import signoff as signoff_mod
    if pr_id in _inflight(app):
        # A launch slower than the backoff (container start) is still
        # running; a second ``pm pr signoff`` would only queue on its lock.
        _log.debug("signoff: %s launch still in flight", pr_id)
        return
    launched = _launched_at(app)
    now = time.monotonic()
    last = launched.get(pr_id)
    if not force and last is not None and now - last < RELAUNCH_BACKOFF_SECONDS:
        _log.debug("signoff: %s launched <%ds ago, not relaunching",
                   pr_id, RELAUNCH_BACKOFF_SECONDS)
        return
    # Logged here, past the in-flight / backoff gates: step() asks for a
    # launch on every poll while the window is gone, and an INFO line per
    # skipped poll read as a relaunch every 5 s in the L log.
    _log.info("signoff: launching router for %s (stale=%s)", pr_id, force)
    launched[pr_id] = now
    try:
        tdir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        app.log_message(f"[red]Cannot create transcript dir[/] {tdir}: {e}")
        return
    transcript = signoff_mod.signoff_transcript(tdir, pr_id)
    _inflight(app).add(pr_id)
    app.run_worker(_launch_quiet(app, pr_id, transcript))


def _inflight(app) -> set:
    """PR ids whose ``pm pr signoff`` launch worker has not finished."""
    s = getattr(app, "_signoff_launch_inflight", None)
    if not isinstance(s, set):
        s = set()
        app._signoff_launch_inflight = s
    return s


async def _launch_quiet(app, pr_id: str, transcript) -> None:
    """``pm pr signoff --background --transcript <t> <pr>`` off the event loop.

    Like ``auto_start._start_pr_quiet``: the launch can take a while (prompt
    build, container start), so it must not run synchronously in the 5 s
    poll.  The relaunch backoff covers the window that is not up yet.
    """
    import asyncio
    import sys
    from rich.markup import escape
    from pm_core.tui._shell import _run_shell_async

    cmd = [sys.executable, "-m", "pm_core.wrapper", "pr", "signoff",
           "--background", "--transcript", str(transcript), pr_id]
    proc = None
    try:
        proc = await _run_shell_async(
            cmd, cwd=str(app._root) if app._root else None,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except Exception as e:
        # A hung launch would keep holding the per-PR launch lock, so every
        # later relaunch would only queue behind it: kill it.
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        _log.exception("signoff_ui: launch failed for %s", pr_id)
        app.log_message(f"[red]Sign-off launch failed[/] for {pr_id}: "
                        f"{escape(str(e))}")
        return
    finally:
        _inflight(app).discard(pr_id)
    if proc.returncode != 0:
        err = (stderr.decode(errors="replace") if stderr else "").strip()
        _log.warning("signoff_ui: pm pr signoff %s exit=%s: %s",
                     pr_id, proc.returncode, err[:200])
        # Text, not markup (as auto_start's failed `pm pr start` line): a
        # stray "[...]" in the reason would be dropped, and "[/...]" makes
        # the log line refuse the whole message.
        reason = err.splitlines()[-1] if err else f"exit {proc.returncode}"
        app.log_message(f"[red]Sign-off launch failed[/] for {pr_id}: "
                        f"{escape(reason)}")
    else:
        _log.info("signoff_ui: pm pr signoff %s launched", pr_id)
    _reload(app)


def _entered_signoff_epoch(pr: dict) -> float | None:
    """``signed_off_at`` (set on every sign_off entry) as epoch seconds."""
    from datetime import datetime
    ts = pr.get("signed_off_at")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _adopt_orphaned_run(app, pr: dict, tdir, session: str) -> None:
    """Move the PR's live router run from an earlier auto-start run dir into *tdir*.

    A user restart (Ctrl+R) leaves auto-start off, so re-arming creates a new
    ``autostart-*`` run dir, but the router window launched under the old
    dir keeps writing its transcript there.  :func:`step_signoff` only reads
    *tdir*, so the adopted window read as "running" forever and its verdict
    was never recorded (pr-5410ae4).  When *tdir* holds no run of its own,
    no launch is in flight and the PR's sign-off window is alive, move the
    newest stamped run of another auto-start run dir (``manual-*`` dirs and
    unstamped runs are never adopted) launched since the PR entered
    ``sign_off`` (transcript + launch stamp) into *tdir*.  ``step_signoff``
    then binds it to HEAD as usual: recorded when its stamp is the current
    HEAD, retired as stale otherwise.  Moving (not copying) keeps a consumed
    verdict from being replayed by a later sign_off entry.
    """
    from pm_core import signoff as signoff_mod
    pr_id = pr["id"]
    own = signoff_mod.signoff_transcript(tdir, pr_id)
    own_stamp = signoff_mod.signoff_launch_stamp(own)
    if own.is_symlink() or own.exists() or own_stamp.exists():
        return
    if pr_id in _inflight(app) or not app._root:
        return
    since = _entered_signoff_epoch(pr)
    best = None
    for stamp in (app._root / "transcripts").glob(f"*/{own_stamp.name}"):
        if stamp.parent == tdir or stamp.parent.name.startswith("manual-"):
            continue
        try:
            mtime = stamp.stat().st_mtime
        except OSError:
            continue
        if since is not None and mtime < since - 1:
            continue  # a run from an earlier sign_off episode
        if best is None or mtime > best[0]:
            best = (mtime, stamp)
    if best is None or signoff_mod.signoff_window_pane(session, pr) is None:
        return
    stamp = best[1]
    transcript = signoff_mod.signoff_transcript(stamp.parent, pr_id)
    try:
        tdir.mkdir(parents=True, exist_ok=True)
        if transcript.is_symlink() or transcript.exists():
            transcript.rename(own)
        stamp.rename(own_stamp)
    except OSError as e:
        _log.warning("signoff: adopting %s run from %s failed: %s",
                     pr_id, stamp.parent.name, e)
        return
    _log.info("signoff: %s adopted router run from %s", pr_id, stamp.parent.name)


def step(app, pr_id: str, pr: dict | None = None) -> None:
    """Advance one in-scope ``sign_off`` PR through the shared state machine.

    *pr* is the PR's entry freshly read from disk (``advance_all`` loads
    project.yaml once per pass); None re-reads it.
    """
    from pm_core.tui import auto_start as _auto_start
    from pm_core import signoff as signoff_mod

    if not _driven(app, pr_id):
        return
    if pr_id in (getattr(app, "_pending_merge_prs", None) or set()):
        return  # published; its post-merge update window owns it now
    session = getattr(app, "_session_name", None)
    if not session:
        return
    if pr is None:
        pr = _load_pr(app, pr_id)
    if not pr or pr.get("status") != "sign_off":
        return

    tdir = _auto_start.get_transcript_dir(app)
    _adopt_orphaned_run(app, pr, tdir, session)
    result = signoff_mod.step_signoff(app._root, pr, session=session, tdir=tdir)
    _log.debug("signoff step %s: %r", pr_id, result)

    if result.action == "running":
        return
    if result.action == "launch":
        _acted(app).pop(pr_id, None)
        if result.stale:
            _reload(app)
            app.log_message(
                f"Sign-off for {pr_id} is stale ({result.reason or 'HEAD moved'})"
                " — re-running")
        _launch(app, pr_id, tdir, force=result.stale)
        return

    hop = result.hop
    if hop in ("ready_to_merge", "blocked"):
        key = (result.verdict, result.sha, _auto_start.policy_for(app, pr_id))
        if _acted(app).get(pr_id) == key:
            # Already acted; the adopted record changed nothing on disk, so
            # skip the full TUI reload this terminal state would otherwise
            # repeat on every 5 s poll until the user presses g.
            return
        _acted(app)[pr_id] = key
    else:
        _acted(app).pop(pr_id, None)
        _launched_at(app).pop(pr_id, None)
    _reload(app)  # verdict record / hop status written behind the TUI's back
    _log.info("signoff: %s routed %s -> %s", pr_id, result.verdict, hop)
    if result.coerced and hop != "unknown":
        app.log_message(f"[yellow]Sign-off {pr_id}:[/] {result.coerced}",
                        sticky=15)

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
        # (The hop's return record holds the launch claim, so a concurrent
        # `pm pr auto-sequence` tick doesn't relaunch — kill — our window.)
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
    from pm_core import signoff as signoff_mod
    if not app._root or not _auto_start.is_enabled(app):
        return
    if prs is None:
        prs = (app._data or {}).get("prs") or []
    disk = None  # project.yaml read at most once per pass (it can be large)
    for pr in list(prs):
        pr_id = pr.get("id")
        if not pr_id or not _auto_start.in_scope(app, pr_id, prs):
            continue
        status = pr.get("status")
        try:
            if status == "sign_off":
                if disk is None:
                    disk = store.load(app._root)
                step(app, pr_id, store.get_pr(disk, pr_id))
            elif (status == "qa" and pr_id not in app._qa_loops
                  and _auto_start.recorded_qa_verdict(pr_id, pr) == "PASS"
                  and signoff_mod.return_awaiting(pr) != "qa"):
                # (A sign-off REQA return still waiting for its QA run must
                # not be handed back to sign-off on the old PASS.)
                # Retried on the next pass, so never wait for the lock.
                start_signoff(app, pr_id, lock_timeout=store.NO_WAIT)
        except Exception:
            _log.exception("signoff_ui: advance failed for %s", pr_id)
