"""Per-session command history and popup scrollback.

Both pm command surfaces, the prefix+M popup (``pm _popup-cmd``) and the
TUI command bar (``/``), record submitted commands in one file per pm
session, ``~/.pm/sessions/<tag>/command_history``, one command per line
and newest last.  A command typed in either surface can then be recalled
from the other.

The popup also keeps a bounded transcript of the commands it ran and
their output in ``popup_scrollback.jsonl``.  It re-renders the tail of
that transcript when it opens and pages through all of it with PgUp, so
dismissing and reopening the popup keeps its scrollback.

Both files are keyed by the pm session tag (the ``pm-<tag>`` tmux session
name without its prefix), never by the caller's cwd.  The popup often runs
from a PR workdir, which would otherwise hash to a different session.
Without a tag nothing is persisted (see :func:`history_path`).

Writers serialize on a sidecar ``.lock`` file.  That file is never
replaced, so a trim's atomic rename cannot leave a waiting writer
appending to the unlinked old inode.  Readers take no lock: a trim swaps
the file in with ``os.replace``, so a read sees either the old or the new
contents, and blank lines are dropped.  History is a convenience, so a
racing read that misses the newest entry is acceptable.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pm_core import paths

_log = paths.configure_logger("pm.command_history")

HISTORY_FILENAME = "command_history"
TRANSCRIPT_FILENAME = "popup_scrollback.jsonl"

# Commands kept in the shared history file.
HISTORY_CAP = 1000
# Popup transcript bounds: whole entries are dropped oldest-first until
# both limits hold, and one entry's output is cut to its tail so a single
# huge listing cannot evict everything else.
TRANSCRIPT_MAX_ENTRIES = 200
TRANSCRIPT_MAX_BYTES = 1_000_000
TRANSCRIPT_MAX_OUTPUT_CHARS = 64_000


def tag_for_session(session_name: str | None) -> str | None:
    """Session tag for tmux session *session_name* (``pm-<tag>[~N]``).

    None when the name is empty or not a pm session name.
    """
    if not session_name:
        return None
    base = session_name.split("~")[0]
    tag = base.removeprefix("pm-")
    return tag if tag and tag != base else None


def _session_file(tag: str | None, name: str) -> Path | None:
    # Deliberately no cwd fallback (paths.session_dir(None) would derive
    # a tag from the cwd): another session's history must never leak in.
    if not tag:
        return None
    sd = paths.session_dir(tag)
    return sd / name if sd else None


def history_path(tag: str | None) -> Path | None:
    """The shared command-history file for session *tag* (None: no tag)."""
    return _session_file(tag, HISTORY_FILENAME)


def transcript_path(tag: str | None) -> Path | None:
    """The popup scrollback transcript for session *tag* (None: no tag)."""
    return _session_file(tag, TRANSCRIPT_FILENAME)


def file_signature(path: Path | None) -> tuple[int, int, int] | None:
    """Cheap change token for *path*: (inode, mtime_ns, size), or None."""
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    with open(path.with_name(path.name + ".lock"), "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _replace_contents(path: Path, text: str) -> None:
    """Atomically replace *path* with *text* (caller holds the lock)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [ln for ln in text.splitlines() if ln.strip()]


def normalize_command(cmd: str) -> str:
    """One-line form of *cmd* for the history file ('' to skip it)."""
    return " ".join(cmd.split("\n")).replace("\r", " ").strip()


def append_history(cmd: str, tag: str | None) -> bool:
    """Append *cmd* to session *tag*'s history, trimming to HISTORY_CAP.

    Returns False when nothing was written: no tag, an empty command, or
    an I/O error (logged).  History is best-effort and never raises.
    """
    line = normalize_command(cmd)
    path = history_path(tag)
    if not line or path is None:
        return False
    try:
        with _locked(path):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            lines = _read_lines(path)
            if len(lines) > HISTORY_CAP:
                _replace_contents(path, "".join(
                    ln + "\n" for ln in lines[-HISTORY_CAP:]))
    except OSError as e:
        _log.warning("command history append failed (%s): %s", path, e)
        return False
    return True


def read_history(tag: str | None, limit: int | None = None) -> list[str]:
    """Session *tag*'s commands, oldest first (the last *limit* if given)."""
    path = history_path(tag)
    if path is None:
        return []
    lines = _read_lines(path)
    if limit is not None:
        lines = lines[-limit:] if limit > 0 else []
    return lines


# --- popup transcript ---------------------------------------------------

_OSC_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?")
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ESC2_RE = re.compile(r"\x1b[@-Z\\^_]|\x1b[()][0-9A-Za-z]")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f]")


def clean_output(text: str) -> str:
    """Make captured terminal output safe to replay later.

    Keeps SGR colour codes and drops other escape sequences: cursor
    movement, line clearing, titles, alternate-screen switches.  A
    carriage return overwrites its line, as on a terminal, so a spinner's
    frames collapse to the final one.
    """
    text = text.replace("\r\n", "\n")
    text = _OSC_RE.sub("", text)
    text = _CSI_RE.sub(lambda m: m.group(0) if m.group(0).endswith("m") else "",
                       text)
    text = _ESC2_RE.sub("", text)
    text = "\n".join(ln.rsplit("\r", 1)[-1] for ln in text.split("\n"))
    return _CTRL_RE.sub("", text)


def _truncate_output(text: str) -> str:
    if len(text) <= TRANSCRIPT_MAX_OUTPUT_CHARS:
        return text
    cut = len(text) - TRANSCRIPT_MAX_OUTPUT_CHARS
    tail = text[cut:]
    nl = tail.find("\n")
    if 0 <= nl < 200:  # start the kept tail on a line boundary
        cut += nl + 1
        tail = tail[nl + 1:]
    return f"[... {cut} earlier characters omitted ...]\n{tail}"


def make_entry(cmd: str, output: str = "", status: str | None = None) -> dict:
    """A transcript entry: the command, its cleaned output and a status
    note such as ``exit 2`` / ``aborted`` (None for plain success)."""
    return {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cmd": cmd,
        "output": _truncate_output(clean_output(output)),
        "status": status,
    }


def append_transcript(entry: dict, tag: str | None) -> bool:
    """Append *entry* to session *tag*'s popup transcript and trim it."""
    path = transcript_path(tag)
    if path is None:
        return False
    line = json.dumps(entry, ensure_ascii=False)
    try:
        with _locked(path):
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            lines = _read_lines(path)
            size = sum(len(ln.encode("utf-8")) + 1 for ln in lines)
            if len(lines) > TRANSCRIPT_MAX_ENTRIES or size > TRANSCRIPT_MAX_BYTES:
                keep = lines[-TRANSCRIPT_MAX_ENTRIES:]
                size = sum(len(ln.encode("utf-8")) + 1 for ln in keep)
                while len(keep) > 1 and size > TRANSCRIPT_MAX_BYTES:
                    size -= len(keep.pop(0).encode("utf-8")) + 1
                _replace_contents(path, "".join(ln + "\n" for ln in keep))
    except OSError as e:
        _log.warning("popup transcript append failed (%s): %s", path, e)
        return False
    return True


def read_transcript(tag: str | None) -> list[dict]:
    """Session *tag*'s popup transcript entries, oldest first.

    Lines that do not parse (e.g. a torn line from a racing read) are
    skipped.
    """
    path = transcript_path(tag)
    if path is None:
        return []
    out = []
    for ln in _read_lines(path):
        try:
            entry = json.loads(ln)
        except ValueError:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("cmd"), str):
            out.append(entry)
    return out


def clear_transcript(tag: str | None) -> bool:
    """Empty session *tag*'s popup transcript."""
    path = transcript_path(tag)
    if path is None:
        return False
    try:
        with _locked(path):
            _replace_contents(path, "")
    except OSError as e:
        _log.warning("popup transcript clear failed (%s): %s", path, e)
        return False
    return True
