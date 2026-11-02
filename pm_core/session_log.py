"""Native session identities for pm-launched Claude sessions.

pm never copies, freezes or archives Claude's session history: Claude keeps
every session's JSONL under ``~/.claude/projects/<mangled-cwd>/<sid>.jsonl``
for its configured ``cleanupPeriodDays``.  What pm needs is the *mapping*
from its own identity of a launch — project/PR, phase, driver run, review
loop, iteration and attempt — to that native session.  Each launch records
its own identity here, once, when its command is built
(:func:`pm_core.claude_launcher.build_claude_shell_cmd` ``launch=``), and
collectors read the native log of the exact session they launched.

Storage: one append-only JSON-lines ledger per *subject* (a PR id, or
``watcher-<type>``) at ``<runtime dir>/sessions/<subject>.jsonl``, beside the
per-PR runtime state (``~/.pm/runtime/<pm-session>/``).  Lines are only ever
appended; pm never rewrites, truncates or deletes a ledger or a native log.
Two events:

* ``launch`` — a session was launched (or an existing session adopted) under
  an identity.  ``log`` is the native JSONL path Claude writes for the cwd it
  runs in; ``legacy`` names a pre-upgrade ``pm/transcripts`` entry the record
  was adopted from, ``adopted_from`` the run an adopted session came from.
* ``retire`` — the session is no longer the current run of its phase (a
  sign-off bounce).  Its log and records stay: history, not state.

Missing logs are reported, never substituted: a record whose native log is
absent (never written, or pruned by Claude's retention) reads as "no verdict"
and :func:`missing_message` says so.

Upgrade compatibility is read-only and bounded: :func:`resolve` adopts a
run's pre-upgrade ``pm/transcripts/<run>/<name>`` entry once, only when the
ledger knows nothing of that phase+run, and never touches the legacy file.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from pm_core.paths import configure_logger

_log = configure_logger("pm.session_log")

LEDGER_DIRNAME = "sessions"
ARTIFACTS_DIRNAME = "launch-artifacts"
# Pre-upgrade tree under the project's pm root (read-only compatibility).
LEGACY_DIRNAME = "transcripts"
# The CLI auto-sequence driver's run id (legacy dir: auto-sequence/<pr>/).
AUTO_SEQUENCE_RUN = "auto-sequence"
_SCHEMA = 1
_SID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_CONTENT_SID_RE = re.compile(r'"sessionId"\s*:\s*"([0-9a-f-]{36})"')


@dataclass(frozen=True)
class SessionLaunch:
    """The identity a caller gives a launch (see ``build_claude_shell_cmd``)."""
    subject: str
    phase: str
    run_id: str = ""
    loop_id: str = ""
    iteration: int | None = None
    attempt: int | None = None
    # Sign-off: the HEAD the run reviews and its integration base.
    head: str = ""
    base: str = ""


@dataclass(frozen=True)
class SessionRecord:
    """One ledger ``launch`` event, with ``retired`` applied."""
    subject: str
    phase: str
    session_id: str
    log: str
    cwd: str = ""
    run_id: str = ""
    loop_id: str = ""
    iteration: int | None = None
    attempt: int | None = None
    head: str = ""
    base: str = ""
    at: str = ""
    legacy: str = ""
    adopted_from: str = ""
    retired: str = ""


def is_session_id(value) -> bool:
    return isinstance(value, str) and bool(_SID_RE.match(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _runtime_root() -> Path:
    from pm_core import runtime_state
    return runtime_state._runtime_dir()


def ledger_path(subject: str) -> Path:
    safe = subject.replace("/", "_").replace("\\", "_")
    return _runtime_root() / LEDGER_DIRNAME / f"{safe}.jsonl"


def artifacts_dir() -> Path:
    """Where failed-launch stdout/stderr artifacts are kept."""
    return _runtime_root() / ARTIFACTS_DIRNAME


def _append(subject: str, event: dict) -> None:
    path = ledger_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(event, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            # A write torn by a crash leaves no newline: start on a fresh
            # line so this record is not swallowed by the torn one.
            size = os.fstat(fd).st_size
            if size and os.pread(fd, 1, size - 1) != b"\n":
                data = b"\n" + data
            while data:
                data = data[os.write(fd, data):]
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _events(subject: str) -> list[dict]:
    path = ledger_path(subject)
    try:
        with open(path, "rb") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                raw = f.read()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except FileNotFoundError:
        return []
    except OSError as e:
        _log.warning("session ledger %s unreadable: %s", path, e)
        return []
    out = []
    for line in raw.decode(errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue  # a torn line never hides the others
        if isinstance(ev, dict) and is_session_id(ev.get("session_id")):
            out.append(ev)
    return out


def _int_or_none(value):
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else None


def _record(ev: dict) -> SessionRecord:
    def s(key):
        v = ev.get(key)
        return v if isinstance(v, str) else ""
    return SessionRecord(
        subject=s("subject"), phase=s("phase"), session_id=ev["session_id"],
        log=s("log"), cwd=s("cwd"), run_id=s("run"), loop_id=s("loop"),
        iteration=_int_or_none(ev.get("iteration")),
        attempt=_int_or_none(ev.get("attempt")),
        head=s("head"), base=s("base"), at=s("at"), legacy=s("legacy"),
        adopted_from=s("adopted_from"))


def register(launch: SessionLaunch, session_id: str, cwd: str, *,
             log: str | Path | None = None, legacy: str = "",
             adopted_from: str = "") -> SessionRecord:
    """Append a ``launch`` event for *session_id* under *launch*'s identity.

    *log* defaults to Claude's native JSONL for *cwd* (the directory Claude
    runs in: ``/workspace`` for a container launch, whose config dir is the
    host's).  Passing *log* adopts an existing session (no copy is made).
    """
    if not is_session_id(session_id):
        raise ValueError(f"not a session id: {session_id!r}")
    if log is None:
        from pm_core.claude_launcher import transcript_path_for
        log = transcript_path_for(cwd, session_id)
    event = {
        "v": _SCHEMA, "event": "launch", "at": _now(),
        "subject": launch.subject, "phase": launch.phase,
        "session_id": session_id, "cwd": cwd or "", "log": str(log),
        "run": launch.run_id or "", "loop": launch.loop_id or "",
        "iteration": launch.iteration, "attempt": launch.attempt,
        "head": launch.head or "", "base": launch.base or "",
    }
    if legacy:
        event["legacy"] = legacy
    if adopted_from:
        event["adopted_from"] = adopted_from
    _append(launch.subject, event)
    _log.info("session_log: %s %s %s run=%s loop=%s i=%s a=%s session=%s "
              "log=%s%s", "adopted" if (legacy or adopted_from) else "launch",
              launch.subject, launch.phase, launch.run_id, launch.loop_id,
              launch.iteration, launch.attempt, session_id, log,
              f" legacy={legacy}" if legacy else "")
    return _record(event)


def adopt(launch: SessionLaunch, session_id: str,
          log: str | Path) -> SessionRecord:
    """Record an existing session *session_id* under *launch*'s identity.

    No copy is made: the record names the session's native *log*.  It keeps
    the cwd the session's own launch recorded, and ``adopted_from`` names
    that launch's run (``unrecorded`` for a session pm never recorded, e.g.
    one another driver launched without a run).
    """
    prior = by_session(launch.subject, session_id)
    return register(launch, session_id, prior.cwd if prior else "", log=log,
                    adopted_from=(prior.run_id if prior else "")
                    or "unrecorded")


def retire(subject: str, session_id: str, reason: str) -> None:
    """Mark *session_id* as no longer the current run of its phase."""
    if not is_session_id(session_id):
        return
    _append(subject, {"v": _SCHEMA, "event": "retire", "at": _now(),
                      "session_id": session_id, "reason": reason or "retired"})
    _log.info("session_log: retired %s session %s (%s)", subject, session_id,
              reason)


def records(subject: str) -> list[SessionRecord]:
    """Every launch record of *subject*, oldest first, ``retired`` applied.

    A ``retire`` event retires the session's earlier records; a later
    launch/adoption of the same session is current again.
    """
    out: list[SessionRecord] = []
    for ev in _events(subject):
        kind = ev.get("event")
        if kind == "launch":
            out.append(_record(ev))
        elif kind == "retire":
            reason = ev.get("reason") if isinstance(ev.get("reason"), str) \
                else "retired"
            sid = ev["session_id"]
            out = [replace(r, retired=reason or "retired")
                   if r.session_id == sid and not r.retired else r
                   for r in out]
    return out


def find(subject: str, *, phase: str | None = None,
         run_id: str | None = None, loop_id: str | None = None,
         iteration: int | None = None, session_id: str | None = None,
         include_retired: bool = False) -> list[SessionRecord]:
    """Records of *subject* matching every given field, oldest first."""
    out = []
    for r in records(subject):
        if r.retired and not include_retired:
            continue
        if phase is not None and r.phase != phase:
            continue
        if run_id is not None and r.run_id != run_id:
            continue
        if loop_id is not None and r.loop_id != loop_id:
            continue
        if iteration is not None and r.iteration != iteration:
            continue
        if session_id is not None and r.session_id != session_id:
            continue
        out.append(r)
    return out


def latest(subject: str, **filters) -> SessionRecord | None:
    found = find(subject, **filters)
    return found[-1] if found else None


def by_session(subject: str, session_id: str | None) -> SessionRecord | None:
    """The latest record of exactly *session_id* (retired ones included)."""
    if not is_session_id(session_id):
        return None
    return latest(subject, session_id=session_id, include_retired=True)


# ---------------------------------------------------------------------------
# Native logs
# ---------------------------------------------------------------------------

def find_native_log(session_id: str | None) -> Path | None:
    """Claude's JSONL for *session_id* wherever its project dir is.

    The session id is unique, so this is a lookup by name across project
    dirs (pr-488b748: Claude's runtime cwd can differ from the one pm
    predicted), never a read of history.
    """
    if not is_session_id(session_id):
        return None
    projects = Path.home() / ".claude" / "projects"
    try:
        matches = list(projects.glob(f"*/{session_id}.jsonl"))
    except OSError:
        return None
    if not matches:
        return None
    try:
        return max(matches, key=lambda m: m.stat().st_mtime)
    except OSError:
        return matches[0]


def log_path(record: SessionRecord) -> Path:
    """The record's native log (or, when absent, its expected path).

    Pollers keep re-reading the returned path, so a log that appears later
    is seen; :mod:`pm_core.verdict_transcript` applies the same session-id
    lookup when the predicted directory never materialises.
    """
    p = Path(record.log)
    if p.exists():
        return p
    return find_native_log(record.session_id) or p


def log_of(subject: str, session_id: str | None) -> Path | None:
    """Native log of exactly *session_id*: its recorded path (see
    :func:`log_path`), else — a session pm never recorded, e.g. one a
    pre-upgrade launch named only by its symlink — the lookup by id."""
    rec = by_session(subject, session_id)
    if rec is not None:
        return log_path(rec)
    return find_native_log(session_id)


def log_state(record: SessionRecord) -> str:
    """``present`` or ``missing`` (never written, or pruned by Claude)."""
    return "present" if log_path(record).exists() else "missing"


def retention_days() -> int | None:
    """Claude's configured ``cleanupPeriodDays`` (read-only), or None.

    Read from Claude's config dir: ``$CLAUDE_CONFIG_DIR`` when set (Claude
    then never reads ``~/.claude/settings.json``, so falling back to it
    would report a retention Claude does not apply), else ``~/.claude``.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or \
        str(Path.home() / ".claude")
    try:
        data = json.loads((Path(config_dir) / "settings.json").read_text())
    except (OSError, ValueError):
        return None
    value = data.get("cleanupPeriodDays") if isinstance(data, dict) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def missing_suffix(record: SessionRecord | None) -> str:
    """``"; <missing_message>"`` when *record*'s log is missing, else ``""``.

    For collectors giving up on a session (its pane is gone): the report
    says whether the session left any log, never borrowing another's.
    """
    if record is None or log_state(record) == "present":
        return ""
    return f"; {missing_message(record)}"


def missing_message(record: SessionRecord) -> str:
    days = retention_days()
    retention = (f"cleanupPeriodDays={days}" if days is not None
                 else "Claude's default cleanupPeriodDays")
    return (f"native log of {record.phase} session {record.session_id} "
            f"({record.subject}) is missing at {record.log}: the session "
            f"never wrote it, or Claude pruned it ({retention}); pm keeps no "
            f"copy and will not substitute another session")


# ---------------------------------------------------------------------------
# Pre-upgrade pm/transcripts (read-only, bounded)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LegacyLink:
    path: Path
    session_id: str
    log: Path
    head: str = ""
    base: str = ""


def run_id_from_legacy_path(path: str | Path) -> str:
    """The run a pre-upgrade ``--transcript`` path named (its directory)."""
    p = Path(path)
    if p.parent.parent.name == AUTO_SEQUENCE_RUN:
        return AUTO_SEQUENCE_RUN
    return p.parent.name


def launch_run_id(run_id: str | None, legacy_transcript: str | None) -> str:
    """The driver run of a CLI launch: ``--run-id``, else the run a
    deprecated ``--transcript`` path names (an old-code parent mid-upgrade).
    Nothing is ever written at that path."""
    if run_id:
        return run_id
    if legacy_transcript:
        _log.info("deprecated --transcript %s: run id only, no file written",
                  legacy_transcript)
        return run_id_from_legacy_path(legacy_transcript)
    return ""


def legacy_dir(root: Path, run_id: str, subject: str) -> Path | None:
    from pm_core.autostart_state import valid_run_id
    if root is None or not valid_run_id(run_id):
        return None
    base = Path(root) / LEGACY_DIRNAME
    if run_id == AUTO_SEQUENCE_RUN:
        return base / AUTO_SEQUENCE_RUN / subject
    return base / run_id


def _sid_from_content(path: Path) -> str | None:
    try:
        with open(path, "r", errors="replace") as f:
            for _ in range(50):
                line = f.readline()
                if not line:
                    break
                m = _CONTENT_SID_RE.search(line)
                if m and is_session_id(m.group(1)):
                    return m.group(1)
    except OSError:
        return None
    return None


def read_legacy_link(path: str | Path) -> LegacyLink | None:
    """Session behind a pre-upgrade transcript entry, read-only.

    A symlink names its native target; a frozen copy names its session in
    its content and, when the native log is gone, is itself the only
    remaining evidence.  A ``.head`` sidecar (sign-off) gives HEAD/base.
    """
    p = Path(path)
    try:
        if p.is_symlink():
            target = Path(os.readlink(p))
            if not target.is_absolute():
                target = p.parent / target
            sid = target.stem
            if not is_session_id(sid):
                return None
            log = target if target.exists() else (find_native_log(sid)
                                                  or target)
        elif p.is_file():
            sid = _sid_from_content(p)
            if not sid:
                return None
            log = find_native_log(sid) or p
        else:
            return None
    except OSError:
        return None
    head = base = ""
    try:
        lines = p.with_suffix(".head").read_text().split()
        head = lines[0] if lines else ""
        base = lines[1] if len(lines) > 1 else ""
    except OSError:
        pass
    return LegacyLink(path=p, session_id=sid, log=log, head=head, base=base)


def legacy_session(root: Path | None, run_id: str, name: str,
                   subject: str) -> LegacyLink | None:
    d = legacy_dir(root, run_id, subject) if root is not None else None
    return read_legacy_link(d / name) if d is not None else None


def resolve(subject: str, phase: str, run_id: str, *,
            loop_id: str | None = None, iteration: int | None = None,
            legacy_name: str | None = None,
            root: Path | None = None) -> SessionRecord | None:
    """The current session of *phase* in driver run *run_id*.

    The newest ledger record of phase+run — None when it was retired (an
    older record never becomes current again).  When the ledger knows
    nothing of this phase+run, a pre-upgrade ``pm/transcripts`` entry
    *legacy_name* is adopted once — appended as a record naming it — so
    later reads are ledger-only.
    """
    rec = latest(subject, phase=phase, run_id=run_id, loop_id=loop_id,
                 iteration=iteration, include_retired=True)
    if rec is not None:
        return None if rec.retired else rec
    if not legacy_name or root is None:
        return None
    link = legacy_session(root, run_id, legacy_name, subject)
    if link is None or by_session(subject, link.session_id) is not None:
        return None
    return register(
        SessionLaunch(subject=subject, phase=phase, run_id=run_id,
                      loop_id=loop_id or "", iteration=iteration,
                      head=link.head, base=link.base),
        link.session_id, "", log=link.log, legacy=str(link.path))


def driver_pane_session(subject: str, phase: str, run_id: str, pane_id: str,
                        *, loop_id: str | None = None,
                        legacy_name: str | None = None,
                        root: Path | None = None) -> SessionRecord | None:
    """The session *pane_id* runs, when it is this driver's current *phase*.

    The driver's current session is :func:`resolve`'s record for
    phase+run.  A pane whose start command shows a session id must run
    exactly that session — a pane another driver launched is not ours, and
    its idle event says nothing about this driver's work (S79).  A pane that
    shows none (still starting) counts as the run's current session.
    """
    rec = resolve(subject, phase, run_id, loop_id=loop_id,
                  legacy_name=legacy_name, root=root)
    if rec is None:
        return None
    try:
        from pm_core.claude_launcher import pane_session_id
        sid = pane_session_id(pane_id)
    except Exception:
        sid = None
    if sid and sid != rec.session_id:
        return None
    return rec


def format_records(recs: list[SessionRecord]) -> list[str]:
    """Human-readable lines for ``pm pr sessions`` / ``pm watcher sessions``."""
    lines = []
    for r in recs:
        ident = [r.phase]
        if r.run_id:
            ident.append(f"run={r.run_id}")
        if r.loop_id:
            ident.append(f"loop={r.loop_id}")
        if r.iteration is not None:
            ident.append(f"i{r.iteration}")
        if r.attempt is not None:
            ident.append(f"attempt={r.attempt}")
        if r.head:
            ident.append(f"head={r.head[:12]}")
        log = log_path(r)   # one lookup: a missing log globs project dirs
        state = "present" if log.exists() else "missing"
        flags = []
        if r.retired:
            flags.append(f"retired: {r.retired}")
        if r.legacy:
            flags.append(f"adopted from {r.legacy}")
        elif r.adopted_from:
            flags.append(f"adopted from run {r.adopted_from}")
        line = (f"{r.at}  {' '.join(ident)}  session={r.session_id}  "
                f"log[{state}]={log}")
        if flags:
            line += "  (" + "; ".join(flags) + ")"
        lines.append(line)
    return lines


def records_as_json(recs: list[SessionRecord]) -> list[dict]:
    out = []
    for r in recs:
        d = dict(r.__dict__)
        log = log_path(r)
        d["log"] = str(log)
        d["log_state"] = "present" if log.exists() else "missing"
        out.append(d)
    return out


def watcher_subject(watcher_type: str) -> str:
    """Ledger subject of a watcher type (watchers have no PR)."""
    return f"watcher-{watcher_type}"
