"""The native session ledger (pm_core.session_log) and the launch boundary.

pm records each launch's own identity — PR, phase, driver run, loop,
iteration, attempt — with Claude's native session id and log path, and never
links, copies, freezes or deletes a log.  Pre-upgrade ``pm/transcripts``
entries are read (never written) by a bounded adoption.
"""

import json
import os
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pm_core import session_log
from pm_core.session_log import SessionLaunch

PR = "pr-led"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


def _sid():
    return str(uuid.uuid4())


def _launch(phase="review", **kw):
    return SessionLaunch(subject=PR, phase=phase, **kw)


def _turn(text, sid=None):
    rec = {"type": "assistant",
           "message": {"content": [{"type": "text", "text": text}]}}
    if sid:
        rec["sessionId"] = sid
    return json.dumps(rec) + "\n"


# --- ledger ------------------------------------------------------------------

def test_register_records_identity_and_native_log(tmp_path):
    from pm_core.claude_launcher import transcript_path_for
    sid = _sid()
    rec = session_log.register(
        _launch(run_id="autostart-x", loop_id="abcd1234", iteration=2,
                attempt=3), sid, "/workspace")
    assert rec.log == str(transcript_path_for("/workspace", sid))
    (got,) = session_log.records(PR)
    assert got == rec
    assert (got.run_id, got.loop_id, got.iteration, got.attempt) == \
        ("autostart-x", "abcd1234", 2, 3)
    # Ledger only: nothing written next to the log, no pm/transcripts.
    assert not Path(rec.log).exists()
    assert session_log.ledger_path(PR).parent.name == "sessions"


def test_ledger_is_append_only_and_survives_a_torn_line():
    a, b = _sid(), _sid()
    session_log.register(_launch(iteration=1), a, "/w")
    with open(session_log.ledger_path(PR), "a") as f:
        f.write('{"event": "launch", "session_id": "')   # torn write
    session_log.register(_launch(iteration=2), b, "/w")
    assert [r.session_id for r in session_log.records(PR)] == [a, b]


def test_find_filters_and_by_session():
    a, b, c = _sid(), _sid(), _sid()
    session_log.register(_launch(run_id="r1", loop_id="l1", iteration=1), a, "/w")
    session_log.register(_launch(run_id="r1", loop_id="l2", iteration=1), b, "/w")
    session_log.register(_launch(phase="impl", run_id="r1"), c, "/w")
    assert [r.session_id for r in session_log.find(
        PR, phase="review", loop_id="l2", iteration=1)] == [b]
    assert session_log.latest(PR, phase="review", run_id="r1").session_id == b
    assert session_log.by_session(PR, c).phase == "impl"
    assert session_log.by_session(PR, "not-a-session") is None
    # Ledgers are per subject: another PR shares nothing.
    assert session_log.records("pr-other") == []


def test_retired_current_session_never_falls_back_to_an_older_one():
    old, new = _sid(), _sid()
    session_log.register(_launch(phase="signoff", run_id="r"), old, "/w")
    session_log.register(_launch(phase="signoff", run_id="r"), new, "/w")
    session_log.retire(PR, new, "bounced")
    assert session_log.resolve(PR, "signoff", "r") is None
    # History is kept: both sessions are still listed.
    recs = session_log.records(PR)
    assert [(r.session_id, bool(r.retired)) for r in recs] == \
        [(old, False), (new, True)]
    # A later adoption of the same session is current again.
    session_log.register(_launch(phase="signoff", run_id="r"), new, "/w",
                         adopted_from="r0")
    assert session_log.resolve(PR, "signoff", "r").session_id == new


# --- native logs -------------------------------------------------------------

def test_log_path_follows_the_session_id_when_the_slug_differs(home):
    sid = _sid()
    rec = session_log.register(_launch(), sid, "/predicted/cwd")
    real = home / ".claude" / "projects" / "-actual-cwd" / f"{sid}.jsonl"
    real.parent.mkdir(parents=True)
    real.write_text(_turn("hi"))
    assert session_log.log_path(rec) == real
    assert session_log.log_state(rec) == "present"


def test_missing_log_is_reported_not_substituted(home):
    sid, other = _sid(), _sid()
    rec = session_log.register(_launch(), sid, "/w")
    # Another session's log exists; it must never stand in.
    (home / ".claude" / "projects" / "-w").mkdir(parents=True)
    (home / ".claude" / "projects" / "-w" / f"{other}.jsonl").write_text(
        _turn("PASS"))
    assert session_log.log_state(rec) == "missing"
    assert session_log.log_path(rec) == Path(rec.log)
    (home / ".claude").mkdir(exist_ok=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"cleanupPeriodDays": 365000}))
    msg = session_log.missing_message(rec)
    assert sid in msg and "cleanupPeriodDays=365000" in msg
    assert "will not substitute another session" in msg


def test_missing_suffix_only_for_a_missing_log(home):
    rec = session_log.register(_launch(), _sid(), "/w")
    assert session_log.missing_suffix(None) == ""
    assert session_log.missing_suffix(rec).startswith("; native log of ")
    Path(rec.log).parent.mkdir(parents=True)
    Path(rec.log).write_text(_turn("hi"))
    assert session_log.missing_suffix(rec) == ""


def test_adopt_keeps_the_sessions_cwd_and_names_its_run():
    sid = _sid()
    session_log.register(_launch(run_id="autostart-a"), sid, "/wd")
    rec = session_log.adopt(_launch(run_id="run-b", loop_id="l1",
                                    iteration=1), sid, "/native/log.jsonl")
    assert (rec.cwd, rec.adopted_from, rec.log, rec.run_id) == \
        ("/wd", "autostart-a", "/native/log.jsonl", "run-b")
    # A session pm never recorded (another driver's, no run) is named so.
    other = session_log.adopt(_launch(run_id="run-b"), _sid(), "/x.jsonl")
    assert (other.cwd, other.adopted_from) == ("", "unrecorded")
    with pytest.raises(ValueError):
        session_log.adopt(_launch(), "not-a-session", "/x.jsonl")


def test_retention_is_read_never_written(home, monkeypatch):
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"cleanupPeriodDays": 30}))
    before = settings.read_bytes()
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert session_log.retention_days() == 30
    assert settings.read_bytes() == before


# --- launch boundary -----------------------------------------------------------

def test_build_registers_the_launch_and_links_nothing(tmp_path):
    from pm_core.claude_launcher import build_claude_shell_cmd
    wd = tmp_path / "wd"
    wd.mkdir()
    sid = _sid()
    cmd = build_claude_shell_cmd(
        prompt="go", cwd="/workspace", write_dir=str(wd), session_id=sid,
        session_type="review",
        launch=_launch(run_id="r", loop_id="l", iteration=1, attempt=1))
    assert f"--session-id {sid}" in cmd
    rec = session_log.by_session(PR, sid)
    assert (rec.cwd, rec.loop_id, rec.iteration) == ("/workspace", "l", 1)
    assert rec.log.endswith(f"/-workspace/{sid}.jsonl")
    assert not list(tmp_path.rglob("*.jsonl"))  # no link, no copy


def test_build_generates_a_session_when_none_is_given(tmp_path):
    from pm_core.claude_launcher import build_claude_shell_cmd
    cmd = build_claude_shell_cmd(prompt="go", cwd=str(tmp_path),
                                 session_type="impl",
                                 launch=_launch(phase="impl", run_id="r"))
    (rec,) = session_log.records(PR)
    assert f"--session-id {rec.session_id}" in cmd
    assert "--resume" not in cmd


def test_a_launch_that_fails_to_build_records_nothing(tmp_path):
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core.providers import ProviderNotFoundError
    with pytest.raises(ProviderNotFoundError):
        build_claude_shell_cmd(prompt="go", cwd=str(tmp_path),
                               provider="no-such-provider",
                               launch=_launch(phase="impl"))
    assert session_log.records(PR) == []


def test_launch_requires_cwd():
    from pm_core.claude_launcher import build_claude_shell_cmd
    with pytest.raises(ValueError):
        build_claude_shell_cmd(prompt="go", launch=_launch())


# --- legacy pm/transcripts (read-only) -----------------------------------------

def _tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        st = os.lstat(p)
        out[str(p)] = (st.st_ino, os.readlink(p) if p.is_symlink()
                       else p.read_bytes() if p.is_file() else None)
    return out


def test_resolve_adopts_a_legacy_link_once_without_touching_it(tmp_path, home):
    root = tmp_path / "pm"
    tdir = root / "transcripts" / "autostart-x"
    tdir.mkdir(parents=True)
    sid = _sid()
    native = home / ".claude" / "projects" / "-wd" / f"{sid}.jsonl"
    native.parent.mkdir(parents=True)
    native.write_text(_turn("SIGNOFF_MERGE"))
    (tdir / f"signoff-{PR}.jsonl").symlink_to(native)
    (tdir / f"signoff-{PR}.head").write_text("abc123\nbase456\n")
    before = _tree(root)

    rec = session_log.resolve(PR, "signoff", "autostart-x",
                              legacy_name=f"signoff-{PR}.jsonl", root=root)
    assert (rec.session_id, rec.log, rec.head, rec.base) == \
        (sid, str(native), "abc123", "base456")
    assert rec.legacy == str(tdir / f"signoff-{PR}.jsonl")
    assert _tree(root) == before
    # Adopted once: later reads are ledger-only.
    again = session_log.resolve(PR, "signoff", "autostart-x",
                                legacy_name=f"signoff-{PR}.jsonl", root=root)
    assert again == rec and len(session_log.records(PR)) == 1


def test_frozen_legacy_copy_is_kept_as_the_only_evidence(tmp_path):
    root = tmp_path / "pm"
    tdir = root / "transcripts" / "autostart-x"
    tdir.mkdir(parents=True)
    sid = _sid()
    copy = tdir / f"merge-{PR}.jsonl"
    copy.write_text(_turn("MERGED", sid=sid))   # native pruned, copy remains
    rec = session_log.resolve(PR, "merge", "autostart-x",
                              legacy_name=f"merge-{PR}.jsonl", root=root)
    assert rec.session_id == sid and rec.log == str(copy)
    assert copy.read_text() == _turn("MERGED", sid=sid)


def test_legacy_entry_is_ignored_once_the_ledger_has_the_run(tmp_path, home):
    root = tmp_path / "pm"
    tdir = root / "transcripts" / "r"
    tdir.mkdir(parents=True)
    (tdir / f"impl-{PR}.jsonl").symlink_to(tmp_path / f"{_sid()}.jsonl")
    new = _sid()
    session_log.register(_launch(phase="impl", run_id="r"), new, "/w")
    rec = session_log.resolve(PR, "impl", "r",
                              legacy_name=f"impl-{PR}.jsonl", root=root)
    assert rec.session_id == new


def test_legacy_auto_sequence_dir_and_run_ids():
    assert session_log.run_id_from_legacy_path(
        "/p/pm/transcripts/autostart-a-1/impl-x.jsonl") == "autostart-a-1"
    assert session_log.run_id_from_legacy_path(
        "/p/pm/transcripts/auto-sequence/pr-1/review-pr-1-i2.jsonl") == \
        "auto-sequence"
    assert session_log.legacy_dir(Path("/p"), "auto-sequence", "pr-1") == \
        Path("/p/transcripts/auto-sequence/pr-1")
    # Malformed saved run ids never name a path outside the legacy root.
    assert session_log.legacy_dir(Path("/p"), "../../etc", "pr-1") is None


# --- CLI surfaces --------------------------------------------------------------

def test_deprecated_transcript_option_only_names_the_run(tmp_path):
    """An old-code parent mid-upgrade still passes ``--transcript``: the new
    child derives the run from it and writes nothing there."""
    from pm_core.cli import pr as pr_mod
    legacy = tmp_path / "pm" / "transcripts" / "autostart-a" / "impl-x.jsonl"
    assert pr_mod._launch_run_id("", str(legacy)) == "autostart-a"
    assert pr_mod._launch_run_id("explicit", str(legacy)) == "explicit"
    assert pr_mod._review_launch_identity("", str(legacy), None, 2) == \
        {"run_id": "autostart-a", "session_id": None, "attempt": 2}
    assert not legacy.parent.exists()


def test_pr_sessions_lists_identities_with_log_state(tmp_path, home):
    from pm_core.cli import pr as pr_mod
    present, gone = _sid(), _sid()
    rec = session_log.register(
        _launch(run_id="autostart-x", loop_id="l1", iteration=1, attempt=1),
        present, "/wd")
    Path(rec.log).parent.mkdir(parents=True)
    Path(rec.log).write_text(_turn("NEEDS_WORK"))
    session_log.register(_launch(phase="signoff", run_id="autostart-x",
                                 head="c0ffee" * 6), gone, "/wd")
    session_log.retire(PR, gone, "sign-off run retired")
    with patch.object(pr_mod, "state_root", return_value=tmp_path), \
            patch.object(pr_mod.store, "load",
                         return_value={"prs": [], "project": {}}):
        out = CliRunner().invoke(pr_mod.pr_sessions, [PR]).output
        js = json.loads(CliRunner().invoke(
            pr_mod.pr_sessions, [PR, "--json", "--phase", "signoff"]).output)
    lines = out.strip().splitlines()
    assert len(lines) == 2
    assert f"session={present}" in lines[0] and "log[present]" in lines[0]
    assert "loop=l1 i1 attempt=1" in lines[0]
    assert f"session={gone}" in lines[1] and "log[missing]" in lines[1]
    assert "retired: sign-off run retired" in lines[1]
    assert [(r["session_id"], r["log_state"]) for r in js] == \
        [(gone, "missing")]


def test_watcher_sessions_lists_iterations(tmp_path):
    from pm_core.cli import cli
    sid = _sid()
    session_log.register(
        SessionLaunch(subject=session_log.watcher_subject("discovery"),
                      phase="watcher", run_id="discovery-1", loop_id="ab",
                      iteration=4), sid, str(tmp_path))
    out = CliRunner().invoke(cli, ["watcher", "sessions", "discovery"]).output
    assert "discovery:" in out and f"session={sid}" in out and " i4 " in out
