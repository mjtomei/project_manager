"""Shared command history + popup transcript (pm_core.command_history)."""

from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
import threading
import time

import pytest

from pm_core import command_history as ch

TAG = "demo-c5a1006b"


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def _session_dir(home, tag=TAG):
    return home / ".pm" / "sessions" / tag


# --- tag resolution ---------------------------------------------------------

@pytest.mark.parametrize("name,tag", [
    ("pm-demo-c5a1006b", "demo-c5a1006b"),
    ("pm-demo-c5a1006b~3", "demo-c5a1006b"),
    ("demo-c5a1006b", None),
    ("pm-", None),
    ("", None),
    (None, None),
])
def test_tag_for_session(name, tag):
    assert ch.tag_for_session(name) == tag


# --- history ------------------------------------------------------------------

def test_append_and_read_roundtrip(tmp_home):
    assert ch.append_history("pr list", TAG)
    assert ch.append_history("plan show plan-1", TAG)
    assert ch.read_history(TAG) == ["pr list", "plan show plan-1"]
    assert (_session_dir(tmp_home) / "command_history").read_text() == (
        "pr list\nplan show plan-1\n")


def test_empty_commands_skipped_and_newlines_flattened():
    assert not ch.append_history("", TAG)
    assert not ch.append_history("   \n", TAG)
    assert ch.append_history("pr note add pr-1 'a\nb'\r", TAG)
    assert ch.read_history(TAG) == ["pr note add pr-1 'a b'"]


def test_no_tag_persists_nothing_and_never_uses_cwd(tmp_home):
    """Without a session tag nothing is written, even though the cwd is
    a git repo that paths.session_dir(None) would derive a tag from."""
    assert not ch.append_history("pr list", None)
    assert ch.read_history(None) == []
    assert ch.history_path(None) is None
    assert ch.transcript_path(None) is None
    assert not (tmp_home / ".pm" / "sessions").exists() or not any(
        (tmp_home / ".pm" / "sessions").rglob("command_history"))


def test_sessions_are_isolated():
    ch.append_history("from a", "a-11111111")
    ch.append_history("from b", "b-22222222")
    assert ch.read_history("a-11111111") == ["from a"]
    assert ch.read_history("b-22222222") == ["from b"]


def test_trim_to_cap(monkeypatch):
    monkeypatch.setattr(ch, "HISTORY_CAP", 5)
    for i in range(20):
        ch.append_history(f"c{i}", TAG)
    assert ch.read_history(TAG) == [f"c{i}" for i in range(15, 20)]


def test_read_limit():
    for i in range(10):
        ch.append_history(f"c{i}", TAG)
    assert ch.read_history(TAG, limit=3) == ["c7", "c8", "c9"]
    assert ch.read_history(TAG, limit=0) == []


def test_missing_file_returns_empty():
    assert ch.read_history("never-00000000") == []


def test_signature_changes_on_append():
    path = ch.history_path(TAG)
    assert ch.file_signature(path) is None
    ch.append_history("one", TAG)
    first = ch.file_signature(path)
    ch.append_history("two", TAG)
    assert first is not None and ch.file_signature(path) != first


def test_writers_serialize_on_sidecar_lock(tmp_home):
    """Appends wait for the sidecar lock, which a trim never replaces."""
    ch.append_history("seed", TAG)
    lock_path = _session_dir(tmp_home) / "command_history.lock"
    done = threading.Event()
    with open(lock_path, "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        t = threading.Thread(
            target=lambda: (ch.append_history("blocked", TAG), done.set()))
        t.start()
        time.sleep(0.3)
        assert not done.is_set(), "append ignored the sidecar lock"
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    t.join(5)
    assert done.is_set()
    assert ch.read_history(TAG) == ["seed", "blocked"]


def _writer(home, tag, prefix, n):
    os.environ["HOME"] = home
    from pm_core import command_history as c
    for i in range(n):
        c.append_history(f"{prefix}{i}", tag)


def _run_writers(home, writers, n):
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_writer, args=(str(home), TAG, f"w{w}-", n))
             for w in range(writers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0


def test_concurrent_appends_no_loss(tmp_home):
    _run_writers(tmp_home, writers=4, n=25)
    out = ch.read_history(TAG)
    assert sorted(out) == sorted(f"w{w}-{i}" for w in range(4) for i in range(25))


def test_concurrent_appends_while_trimming(tmp_home, monkeypatch):
    """Writers racing trims (atomic replace) keep exactly the cap and
    never interleave or tear lines."""
    monkeypatch.setattr(ch, "HISTORY_CAP", 20)
    _run_writers(tmp_home, writers=4, n=40)
    out = ch.read_history(TAG)
    assert len(out) == 20
    assert all(line.startswith("w") and "-" in line for line in out)
    text = (_session_dir(tmp_home) / "command_history").read_text()
    assert text.endswith("\n") and text.count("\n") == 20


# --- transcript -----------------------------------------------------------------

def test_transcript_roundtrip_and_status():
    ch.append_transcript(ch.make_entry("pr list", "a\nb\n"), TAG)
    ch.append_transcript(ch.make_entry("pr show x", "nope\n", "exit 1"), TAG)
    entries = ch.read_transcript(TAG)
    assert [(e["cmd"], e["output"], e["status"]) for e in entries] == [
        ("pr list", "a\nb\n", None), ("pr show x", "nope\n", "exit 1")]
    assert all(e["ts"] for e in entries)


def test_transcript_trims_by_entries(monkeypatch):
    monkeypatch.setattr(ch, "TRANSCRIPT_MAX_ENTRIES", 3)
    for i in range(7):
        ch.append_transcript(ch.make_entry(f"c{i}", "x\n"), TAG)
    assert [e["cmd"] for e in ch.read_transcript(TAG)] == ["c4", "c5", "c6"]


def test_transcript_trims_by_bytes(monkeypatch):
    monkeypatch.setattr(ch, "TRANSCRIPT_MAX_BYTES", 1000)
    for i in range(10):
        ch.append_transcript(ch.make_entry(f"c{i}", "y" * 300), TAG)
    entries = ch.read_transcript(TAG)
    assert 1 <= len(entries) <= 3
    assert entries[-1]["cmd"] == "c9"
    assert ch.transcript_path(TAG).stat().st_size <= 1000


def test_entry_output_keeps_tail(monkeypatch):
    monkeypatch.setattr(ch, "TRANSCRIPT_MAX_OUTPUT_CHARS", 50)
    out = "".join(f"line {i:03d}\n" for i in range(40))
    entry = ch.make_entry("pr list", out)
    assert entry["output"].startswith("[... ")
    assert entry["output"].endswith("line 039\n")
    assert "line 000" not in entry["output"]


def test_torn_transcript_line_skipped():
    ch.append_transcript(ch.make_entry("ok", ""), TAG)
    with open(ch.transcript_path(TAG), "a") as fh:
        fh.write('{"cmd": "torn", "outp')
    assert [e["cmd"] for e in ch.read_transcript(TAG)] == ["ok"]


def test_clear_transcript():
    ch.append_transcript(ch.make_entry("ok", ""), TAG)
    assert ch.clear_transcript(TAG)
    assert ch.read_transcript(TAG) == []


def test_transcript_is_json_lines():
    ch.append_transcript(ch.make_entry("pr list", "é ✓\n"), TAG)
    line = ch.transcript_path(TAG).read_text(encoding="utf-8").strip()
    assert json.loads(line)["output"] == "é ✓\n"


# --- clean_output -----------------------------------------------------------------

def test_clean_output_keeps_sgr_drops_cursor_control():
    raw = ("\x1b]0;title\x07\x1b[1mbold\x1b[0m\r\n"
           "\x1b[2K\x1b[1Gspin 1\rspin 2\rdone\r\n"
           "\x1b[?25lhidden\x1b[?25h\x07\n")
    assert ch.clean_output(raw) == "\x1b[1mbold\x1b[0m\ndone\nhidden\n"


def test_clean_output_plain_text_unchanged():
    assert ch.clean_output("a\tb\nc\n") == "a\tb\nc\n"
