"""``pm autostart`` — control the TUI scheduler's auto-start target set.

The target collection is owned by the running TUI (the session scheduler);
these commands never run a scheduler of their own.  Each command is sent
over the existing session command queue (``trigger_tui_command``: SIGUSR2 +
``tui-<session>.cmd-queue``) as ``autostart <verb> … --reply <id>``; the TUI
applies it on its event loop and writes a JSON reply to
``~/.pm/autostart-replies/<id>.json`` which this command reads back.

Exit codes: 0 ok · 1 invalid input (nothing changed) or an owner-side
failure reported in the reply · 2 owner unavailable or timed out (nothing
sent / no reply).
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

import click

from pm_core import store
from pm_core.autostart_state import (
    POLICY_AUTO, POLICY_FLAGS, POLICY_STOP, POLICY_WAIT, REPLY_DIR,
    TERMINAL_STATUSES, format_text,
)
from pm_core.cli import cli
from pm_core.cli.helpers import (
    _canonical_session, _find_tui_pane, _resolve_pr_id,
    _tui_pidfile_for_session, state_root, trigger_tui_command,
)
from pm_core.paths import configure_logger, pm_home

_log = configure_logger("pm.cli.autostart")

EXIT_INVALID = 1
EXIT_OWNER = 2


class _Fail(Exception):
    def __init__(self, code: int, error: str, message: str, **extra):
        super().__init__(message)
        self.code = code
        self.error = error
        self.message = message
        self.extra = extra


def _emit_fail(f: _Fail, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps({"ok": False, "error": f.error,
                               "message": f.message, **f.extra}, indent=2))
    else:
        click.echo(f"Error ({f.error}): {f.message}", err=True)
    raise SystemExit(f.code)


def _resolve_owner(session: str | None) -> tuple[str, int]:
    """Return ``(session, pid)`` of the live TUI that owns auto-start."""
    if session:
        sess = _canonical_session(session)
    else:
        _, sess = _find_tui_pane(None)
        if not sess:
            raise _Fail(EXIT_OWNER, "owner_unavailable",
                        "no pm session with a running TUI found "
                        "(start one with `pm session`, or pass -s SESSION)")
        sess = _canonical_session(sess)
    pidfile = _tui_pidfile_for_session(sess)
    if not pidfile.exists():
        raise _Fail(EXIT_OWNER, "owner_unavailable",
                    f"TUI for session {sess} is not running (no pidfile)",
                    session=sess)
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 0)
        if _is_zombie(pid):
            raise ProcessLookupError(pid)
    except (ValueError, OSError):
        raise _Fail(EXIT_OWNER, "owner_unavailable",
                    f"TUI for session {sess} is not running (stale pidfile)",
                    session=sess)
    return sess, pid


def _is_zombie(pid: int) -> bool:
    """True when *pid* has exited but not been reaped yet.

    ``kill(pid, 0)`` succeeds on a zombie, so a killed TUI whose tmux server
    hasn't reaped it would look alive and the CLI would wait out the full
    timeout before misreporting it as busy (``owner_timeout``).
    """
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False  # no procfs (macOS) — fall back to kill(pid, 0)
    # State is the first field after the parenthesised comm.
    return stat.rpartition(")")[2].split()[:1] == ["Z"]


def _validate(ids: tuple[str, ...], *, for_add: bool) -> list[str]:
    """Resolve ids to canonical pm ids; reject unknown (and, for add,
    merged/closed) PRs before anything is sent to the owner."""
    if not ids:
        raise _Fail(EXIT_INVALID, "usage", "no PR ids given")
    try:
        data = store.load(state_root())
    except FileNotFoundError as e:
        # Keep the --json contract: report it like any other invalid input.
        raise _Fail(EXIT_INVALID, "no_project", str(e))
    resolved, unknown, terminal = [], [], []
    for raw in ids:
        pr = _resolve_pr_id(data, raw)
        if not pr:
            unknown.append(raw)
            continue
        if for_add and pr.get("status") in TERMINAL_STATUSES:
            terminal.append(pr["id"])
            continue
        if pr["id"] not in resolved:
            resolved.append(pr["id"])
    if unknown:
        raise _Fail(EXIT_INVALID, "unknown_pr",
                    f"unknown PR id(s): {', '.join(unknown)}", invalid=unknown)
    if terminal:
        raise _Fail(EXIT_INVALID, "terminal_pr",
                    f"already merged/closed: {', '.join(terminal)}",
                    invalid=terminal)
    return resolved


def _request(session: str | None, args: list[str], timeout: float) -> dict:
    """Send ``autostart <args> --reply ID`` to the owner and wait for the reply."""
    sess, pid = _resolve_owner(session)
    reply_id = f"{int(time.time())}-{secrets.token_hex(4)}"
    reply = pm_home() / REPLY_DIR / f"{reply_id}.json"
    cmd = " ".join(["autostart", *args, "--reply", reply_id])
    _log.info("autostart cli: session=%s pid=%d cmd=%r", sess, pid, cmd)
    if not trigger_tui_command(sess, cmd):
        raise _Fail(EXIT_OWNER, "owner_unavailable",
                    f"could not signal the TUI for session {sess}", session=sess)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if reply.exists():
            try:
                payload = json.loads(reply.read_text())
            except (OSError, json.JSONDecodeError):
                time.sleep(0.05)
                continue
            reply.unlink(missing_ok=True)
            return payload
        time.sleep(0.1)
    raise _Fail(EXIT_OWNER, "owner_timeout",
                f"TUI for session {sess} did not reply within {timeout:g}s "
                f"(busy or restarting); the command may still be applied",
                session=sess)


def _require_status(payload: dict) -> dict:
    """The reply's status dict; an ok reply without one is an owner-side
    failure (``build_status`` raised), never an empty success."""
    status = payload.get("status")
    if payload.get("ok") and not status:
        raise _Fail(EXIT_INVALID, "status_unavailable",
                    payload.get("message") or "owner returned no status")
    return status or {}


def _finish(payload: dict, as_json: bool, text_fn) -> None:
    if as_json:
        click.echo(json.dumps(payload, indent=2, default=sorted))
    else:
        text_fn(payload)
    if not payload.get("ok"):
        if not as_json:
            click.echo(f"Error ({payload.get('error')}): {payload.get('message')}",
                       err=True)
        raise SystemExit(EXIT_INVALID)


_session_opt = click.option("--session", "-s", default=None,
                            help="pm tmux session that owns auto-start")
_timeout_opt = click.option("--timeout", default=10.0, show_default=True,
                            type=float, help="Seconds to wait for the TUI reply")
_json_opt = click.option("--json", "as_json", is_flag=True,
                         help="Machine-readable JSON output")


def _print_changes(payload: dict) -> None:
    for c in payload.get("changes") or []:
        action = c.get("action")
        if action == "fresh_reset":
            click.echo(f"fresh: {c.get('pr_id')} "
                       f"({c.get('from_status')} → in_progress)")
            continue
        if action == "already_waiting":
            click.echo(f"already waiting: {c.get('pr_id')} "
                       f"(implementation turn in progress)")
            continue
        pol = c.get("policy")
        pol_s = f" ({pol.replace('_', '-')})" if pol else ""
        prev = c.get("previous_policy")
        if prev:
            pol_s = f" ({pol.replace('_', '-')}; was {prev.replace('_', '-')})"
        click.echo(f"{action}: {c.get('pr_id')}{pol_s}")
    if payload.get("message"):
        click.echo(payload["message"])
    for f in payload.get("failed") or []:
        click.echo(f"failed: {f.get('pr_id')} ({f.get('error')}): "
                   f"{f.get('message')}", err=True)
    if payload.get("released"):
        click.echo("released merge hold: " + ", ".join(payload["released"]))
    st = payload.get("status") or {}
    targets = [t["pr_id"] for t in st.get("targets") or []]
    click.echo(f"auto-start {st.get('mode', '?')}; targets: "
               f"{', '.join(targets) if targets else '(none)'}")


@cli.group("autostart")
def autostart():
    """Manage auto-start targets owned by the running TUI.

    Auto-start drives an explicit set of target PRs: it schedules the
    union of their dependency closures (shared dependencies once), runs
    impl → review → QA for each, and stops at each target's merge policy.
    Adding is additive and idempotent; removing a target never kills a
    running window or a dependency another target still needs.  An empty
    target set means auto-start is OFF (never "all pending PRs"; that is
    the explicit command-bar `autostart all`).

    \b
    Policies (per target, also set by the O / A keys):
      stop-before-merge  (--stop-before-merge, the default for new CLI
                         targets, and O) — stop the target when ready to
                         merge; press g after sign-off
      auto-merge         (--auto-merge, and A) — merge via `pm pr merge`,
                         which still enforces the sign-off gate
      wait-for-merge     (--wait-for-merge) — hold the target AND every
                         transitive prerequisite for a manual merge; each
                         PR runs impl → review → QA → sign-off, then waits
                         for g / `pm pr merge`; that merge starts the
                         newly unblocked dependents automatically

    A dependency shared by several targets is held if any active
    wait-for-merge target needs it or it has its own stop mark; removing
    the target (or changing its policy) releases only the holds it caused.

    \b
    Fresh autostart (`pm autostart fresh`, TUI `z O` / `z A`) is the explicit
    workflow reset for a reviewed PR you sent back to implementation after
    feedback: it keeps the live session, retires the old review/QA/sign-off
    state, and waits for the current implementation turn before one fresh
    review.  Plain `add` never rewinds.

    \b
    Examples:
      pm autostart add pr-abc123 pr-def456
      pm autostart add 229 --auto-merge
      pm autostart add pr-final --wait-for-merge   # whole chain, manual merges
      pm autostart fresh pr-abc123                 # back to impl after feedback
      pm autostart remove pr-abc123
      pm autostart list --json
      pm autostart status --json

    TUI: press `a` for the live runs popup, `z O` / `z A` for fresh autostart; the
    command bar accepts the same verbs (`autostart add X`, `autostart
    fresh X`, `autostart status`, ...).
    """


@autostart.command("add")
@click.argument("pr_ids", nargs=-1)
@click.option("--stop-before-merge", "stop", is_flag=True,
              help="Stop the target before merge (default for new targets)")
@click.option("--auto-merge", "auto", is_flag=True,
              help="Merge automatically when ready (sign-off gate still applies)")
@click.option("--wait-for-merge", "wait", is_flag=True,
              help="Hold the target and all its transitive prerequisites "
                   "for a manual merge (g / pm pr merge); merging one "
                   "starts its newly ready dependents")
@_session_opt
@_timeout_opt
@_json_opt
def autostart_add(pr_ids, stop, auto, wait, session, timeout, as_json):
    """Add PR_IDS as auto-start targets (additive, idempotent).

    Re-adding a target without a policy flag keeps its current policy; a
    flag replaces it.  At most one policy flag may be given.

    \b
    Run a whole dependency chain with manual merges:
      pm autostart add pr-final --wait-for-merge
    Every unmerged prerequisite of pr-final starts as soon as its own
    dependencies are merged, runs implementation → review → QA → fresh
    sign-off, then shows "waiting for manual merge".  Merge it (g in the
    TUI, or `pm pr merge`) and the scheduler starts whatever that merge
    unblocked — no further autostart command needed.
    """
    try:
        chosen = [p for p, on in ((POLICY_STOP, stop), (POLICY_AUTO, auto),
                                  (POLICY_WAIT, wait)) if on]
        if len(chosen) > 1:
            flags = ", ".join(POLICY_FLAGS[p] for p in chosen)
            raise _Fail(EXIT_INVALID, "conflicting_flags",
                        f"conflicting merge policies: {flags}")
        ids = _validate(pr_ids, for_add=True)
        args = ["add", *ids]
        if chosen:
            args.append(POLICY_FLAGS[chosen[0]])
        payload = _request(session, args, timeout)
    except _Fail as f:
        _emit_fail(f, as_json)
    _finish(payload, as_json, _print_changes)


@autostart.command("fresh")
@click.argument("pr_ids", nargs=-1)
@click.option("--stop-before-merge", "stop", is_flag=True,
              help="Stop the target before merge (default for new targets)")
@click.option("--auto-merge", "auto", is_flag=True,
              help="Merge automatically when ready (sign-off gate still applies)")
@click.option("--wait-for-merge", "wait", is_flag=True,
              help="Hold the target and all its transitive prerequisites "
                   "for a manual merge (g / pm pr merge)")
@_session_opt
@_timeout_opt
@_json_opt
def autostart_fresh(pr_ids, stop, auto, wait, session, timeout, as_json):
    """Return reviewed PR_IDS to implementation after feedback (z O / z A).

    Use this when a PR already reached review/QA/sign-off, you stopped the
    loop, resumed its *existing* implementation pane with feedback, and want
    auto-start to take the changed PR through a fresh review, QA and
    sign-off again.

    The PR is atomically returned to ``in_progress``; obsolete review-loop,
    QA and sign-off ownership is retired (historical evidence is kept), and
    the existing implementation session is adopted — never killed or
    relaunched.  Auto-start then waits for the current implementation turn to
    finish before starting exactly one fresh review.

    Plain ``pm autostart add`` stays a continuation from the current phase;
    it never rewinds a PR.  Repeating ``fresh`` while an attempt is already
    waiting is a no-op.
    """
    try:
        chosen = [p for p, on in ((POLICY_STOP, stop), (POLICY_AUTO, auto),
                                  (POLICY_WAIT, wait)) if on]
        if len(chosen) > 1:
            flags = ", ".join(POLICY_FLAGS[p] for p in chosen)
            raise _Fail(EXIT_INVALID, "conflicting_flags",
                        f"conflicting merge policies: {flags}")
        ids = _validate(pr_ids, for_add=True)
        args = ["fresh", *ids]
        if chosen:
            args.append(POLICY_FLAGS[chosen[0]])
        payload = _request(session, args, timeout)
    except _Fail as f:
        _emit_fail(f, as_json)
    _finish(payload, as_json, _print_changes)


@autostart.command("remove")
@click.argument("pr_ids", nargs=-1)
@_session_opt
@_timeout_opt
@_json_opt
def autostart_remove(pr_ids, session, timeout, as_json):
    """Remove PR_IDS from the target set.

    Stops future scheduling for PRs only that target needed; never kills a
    running window/loop, and dependencies still needed by another target
    keep running.  Removing the last target turns auto-start off.
    """
    try:
        ids = _validate(pr_ids, for_add=False)
        payload = _request(session, ["remove", *ids], timeout)
    except _Fail as f:
        _emit_fail(f, as_json)
    _finish(payload, as_json, _print_changes)


@autostart.command("clear")
@_session_opt
@_timeout_opt
@_json_opt
def autostart_clear(session, timeout, as_json):
    """Remove every target (auto-start off). Running windows are kept."""
    try:
        payload = _request(session, ["clear"], timeout)
    except _Fail as f:
        _emit_fail(f, as_json)
    _finish(payload, as_json, _print_changes)


@autostart.command("list")
@_session_opt
@_timeout_opt
@_json_opt
def autostart_list(session, timeout, as_json):
    """List targets and their merge policies."""
    try:
        payload = _request(session, ["list"], timeout)
        st = _require_status(payload)
    except _Fail as f:
        _emit_fail(f, as_json)
    out = {"ok": payload.get("ok", False), "schema": st.get("schema"),
           "owner": st.get("owner"), "mode": st.get("mode"),
           "targets": [{k: t.get(k) for k in
                        ("pr_id", "title", "policy", "effective_policy",
                         "held_by", "added_at", "source")}
                       for t in st.get("targets") or []]}
    if not out["ok"]:
        out["error"] = payload.get("error")
        out["message"] = payload.get("message")

    def text(_p):
        click.echo(f"Auto-start: {out['mode']}")
        if not out["targets"]:
            click.echo("No auto-start targets.")
        for t in out["targets"]:
            # Name only *other* wait targets; a wait target's own hold is
            # already its policy.
            others = [x for x in t.get("held_by") or [] if x != t["pr_id"]]
            held = f" (held by {', '.join(others)})" if others else ""
            click.echo(f"  {t['pr_id']}  {t['policy'].replace('_', '-')}"
                       f"{held}  {t.get('title') or ''}")
    _finish(out if as_json else payload, as_json, text)


@autostart.command("status")
@_session_opt
@_timeout_opt
@_json_opt
def autostart_status(session, timeout, as_json):
    """Show what each target and its dependency runs are doing.

    Same structured representation (schema pm.autostart.status/1) the TUI
    runs popup (key `a`) renders: phase, running/waiting/paused/failed/
    completed state, reason, review iteration / QA progress, tmux window.
    """
    try:
        payload = _request(session, ["status"], timeout)
        status = _require_status(payload)
    except _Fail as f:
        _emit_fail(f, as_json)
    if as_json:
        if not payload.get("ok"):
            status = {**status, "ok": False, "error": payload.get("error"),
                      "message": payload.get("message")}
        click.echo(json.dumps(status, indent=2, default=sorted))
        if not payload.get("ok"):
            raise SystemExit(EXIT_INVALID)
        return
    _finish(payload, False, lambda _p: click.echo(format_text(status)))
