"""Immutable per-attempt transcript archives (pr-9ee4d64).

A sign-off return re-runs impl, restarts the review loop at iteration 1 and
re-runs sign-off inside one auto-start run.  Canonical transcript paths are
reused, so the pre-return sessions used to vanish from the run archive; and
an obsolete review loop's completion callback could freeze a newer loop's
live transcript into an early copy, hiding the verdict it appended later.

These tests pin the fixes: archive-on-replace, ownership-checked
finalization, and loop-scoped iteration transcript names.
"""

import json
import os
import types
import uuid
from pathlib import Path

import pytest

from pm_core import claude_launcher as cl
from pm_core import review_loop as rl


def _record(text: str) -> str:
    return json.dumps({
        "type": "assistant",
        "uuid": "u-" + uuid.uuid4().hex,
        "message": {"content": [{"type": "text", "text": text}]},
    })


def _native(cwd: Path, sid: str, text: str) -> Path:
    path = cl.transcript_path_for(str(cwd), sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_record(text) + "\n")
    return path


def _link(path: Path, target: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        path.unlink()
    path.symlink_to(target)
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    run = tmp_path / "run"
    run.mkdir()
    cwd = tmp_path / "work"
    cwd.mkdir()
    return types.SimpleNamespace(tmp=tmp_path, run=run, cwd=cwd)


def _sid() -> str:
    return str(uuid.uuid4())


# --- archive-on-replace ---------------------------------------------------

def test_new_launch_archives_previous_session(env):
    """Reusing a canonical transcript path preserves the outgoing session."""
    old_sid = _sid()
    old = _native(env.cwd, old_sid, "PRE-RETURN ROUTER SIGNOFF_IMPL")
    canon = env.run / "signoff-pr-abc.jsonl"
    _link(canon, old)

    cl.build_claude_shell_cmd(prompt="rework", transcript=str(canon),
                              cwd=str(env.cwd))

    archive = cl.transcript_archive_dir(canon) / f"signoff-pr-abc.{old_sid}.jsonl"
    assert archive.is_symlink()
    assert Path(os.readlink(archive)) == old
    assert "PRE-RETURN ROUTER SIGNOFF_IMPL" in archive.read_text()
    # The canonical path is the new attempt, not the archived one.
    assert cl.session_id_from_transcript(canon) != old_sid


def test_archive_entries_are_immutable(env):
    """A second replacement adds an entry; it never overwrites the first."""
    first_sid = _sid()
    first = _native(env.cwd, first_sid, "FIRST SESSION")
    canon = env.run / "impl-pr-abc.jsonl"
    _link(canon, first)

    cl.build_claude_shell_cmd(prompt="rework 1", transcript=str(canon),
                              cwd=str(env.cwd))
    cl.build_claude_shell_cmd(prompt="rework 2", transcript=str(canon),
                              cwd=str(env.cwd))

    adir = cl.transcript_archive_dir(canon)
    first_archive = adir / f"impl-pr-abc.{first_sid}.jsonl"
    assert "FIRST SESSION" in first_archive.read_text()
    entries = sorted(p.name for p in adir.iterdir())
    assert len(entries) == 2  # first session + the intermediate attempt
    assert first_archive.name in entries


def test_archive_transcript_of_frozen_file(env):
    """A finalized (regular-file) transcript is archived, not deleted."""
    canon = env.run / "impl-pr-abc.jsonl"
    canon.write_text(_record("FROZEN PRE-RETURN") + "\n")
    archive = cl.archive_transcript(canon)
    assert archive is not None and archive.is_file()
    assert "FROZEN PRE-RETURN" in archive.read_text()
    assert not canon.exists()


def test_archive_missing_path_is_noop(env):
    assert cl.archive_transcript(env.run / "nope.jsonl") is None


def test_launch_survives_an_already_archived_session(env):
    """A pre-existing archive entry must not leave the canonical in place.

    The archive entry can already exist as a frozen copy (written by an
    earlier finalize) while the canonical link still points at the same
    session.  The launch must still replace the canonical, not raise
    FileExistsError and strand the workflow.
    """
    sid = _sid()
    native = _native(env.cwd, sid, "SESSION")
    canon = env.run / "impl-pr-abc.jsonl"
    _link(canon, native)
    adir = cl.transcript_archive_dir(canon)
    adir.mkdir()
    (adir / f"impl-pr-abc.{sid}.jsonl").write_text("SESSION\n")

    cl.build_claude_shell_cmd(prompt="rework", transcript=str(canon),
                              cwd=str(env.cwd))

    assert canon.is_symlink()
    assert cl.session_id_from_transcript(canon) != sid
    # The pre-existing entry is untouched (immutable).
    assert (adir / f"impl-pr-abc.{sid}.jsonl").read_text() == "SESSION\n"


def test_identical_archive_match_is_scoped_to_the_same_stem(env):
    """A different step's entry is never mistaken for this transcript's copy.

    Frozen files are keyed by mtime+size, so a naive directory-wide match
    could drop a transcript that was never archived.
    """
    canon = env.run / "impl-pr-abc.jsonl"
    canon.write_text(_record("IMPL CONTENT") + "\n")
    adir = cl.transcript_archive_dir(canon)
    adir.mkdir()
    other = adir / "signoff-pr-abc.deadbeef.jsonl"
    other.write_text(_record("IMPL CONTENT") + "\n")
    st = canon.stat()
    os.utime(other, ns=(st.st_atime_ns, st.st_mtime_ns))

    archived = cl.archive_transcript(canon)

    assert archived is not None
    assert archived.name.startswith("impl-pr-abc.")
    assert archived != other
    assert "IMPL CONTENT" in archived.read_text()
    assert "IMPL CONTENT" in other.read_text()  # untouched


def test_frozen_session_is_not_archived_twice(env):
    """Finalize archives the session; a later replacement does not duplicate
    it under a second name."""
    sid = _sid()
    canon = env.run / "impl-pr-abc.jsonl"
    _link(canon, _native(env.cwd, sid, "SESSION"))
    assert cl.finalize_transcript(canon) is True
    adir = cl.transcript_archive_dir(canon)
    assert [p.name for p in adir.iterdir()] == [f"impl-pr-abc.{sid}.jsonl"]

    cl.build_claude_shell_cmd(prompt="rework", transcript=str(canon),
                              cwd=str(env.cwd))
    assert [p.name for p in adir.iterdir()] == [f"impl-pr-abc.{sid}.jsonl"]


# --- ownership-checked finalization --------------------------------------

def test_finalize_with_wrong_session_leaves_link_live(env):
    """An obsolete callback must not freeze the current attempt's link."""
    owner = _sid()
    live = _native(env.cwd, owner, "LOOP 2 EARLY")
    canon = env.run / "review-pr-abc-i1.jsonl"
    _link(canon, live)

    assert cl.finalize_transcript(canon, session_id=_sid()) is False
    assert canon.is_symlink()

    with live.open("a") as f:
        f.write(_record("NEEDS_WORK") + "\n")
    assert "NEEDS_WORK" in canon.read_text()


def test_finalize_with_matching_session_freezes(env):
    owner = _sid()
    live = _native(env.cwd, owner, "VERDICT PASS")
    canon = env.run / "review-pr-abc-i1.jsonl"
    _link(canon, live)

    assert cl.finalize_transcript(canon, session_id=owner) is True
    assert not canon.is_symlink()
    assert "VERDICT PASS" in canon.read_text()
    # The immutable archive copy survives independently of the native file.
    archive = cl.transcript_archive_dir(canon) / f"review-pr-abc-i1.{owner}.jsonl"
    assert archive.is_file()
    assert "VERDICT PASS" in archive.read_text()


def test_finalize_leaves_a_redirected_link_live(env, monkeypatch):
    """A link redirected between read and replacement is never clobbered."""
    old = _native(env.cwd, _sid(), "OLD")
    new = _native(env.cwd, _sid(), "NEW")
    canon = env.run / "signoff-pr-abc.jsonl"
    _link(canon, old)

    real = cl._freeze_archive_copy

    def _redirect_then_freeze(p, raw, target, sid):
        _link(canon, new)          # a new attempt took the path
        return real(p, raw, target, sid)

    monkeypatch.setattr(cl, "_freeze_archive_copy", _redirect_then_freeze)
    assert cl.finalize_transcript(canon) is False
    assert canon.is_symlink()
    assert Path(os.readlink(canon)) == new


def test_finalize_transcript_dir_includes_archives(env):
    canon = env.run / "signoff-pr-abc.jsonl"
    live = _native(env.cwd, _sid(), "LIVE")
    _link(canon, live)
    archived = cl.archive_transcript(canon)
    # Re-point the canonical at another session so both links are finalizable.
    live2 = _native(env.cwd, _sid(), "LIVE 2")
    _link(canon, live2)

    assert cl.finalize_transcript_dir(env.run) == 2
    assert canon.is_file() and not canon.is_symlink()
    assert archived.is_file() and not archived.is_symlink()


# --- loop-scoped review iteration names ----------------------------------

def test_review_loops_use_distinct_iteration_paths(env):
    a = rl.iteration_transcript(env.run, "pr-abc", "aaaa", 1)
    b = rl.iteration_transcript(env.run, "pr-abc", "bbbb", 1)
    assert a != b
    assert a.endswith("review-pr-abc-aaaa-i1.jsonl")
    assert b.endswith("review-pr-abc-bbbb-i1.jsonl")


def test_resolve_iteration_transcript_falls_back_to_legacy(env):
    legacy = env.run / "review-pr-abc-i2.jsonl"
    legacy.write_text("")
    assert rl.resolve_iteration_transcript(
        env.run, "pr-abc", "aaaa", 2) == str(legacy)


def test_review_completion_finalizes_only_its_own_loop(env, monkeypatch):
    """The 2026-10-28 failure: an obsolete loop's late completion froze the
    newer loop's shared ``review-i1`` live transcript."""
    from pm_core.tui import review_loop_ui

    loop1 = rl.ReviewLoopState(pr_id="pr-abc", loop_id="aaaa",
                               _transcript_dir=str(env.run))
    loop2 = rl.ReviewLoopState(pr_id="pr-abc", loop_id="bbbb",
                               _transcript_dir=str(env.run))
    s1, s2 = _sid(), _sid()
    loop1.iteration_sessions[1] = s1
    loop2.iteration_sessions[1] = s2
    n1 = _native(env.cwd, s1, "LOOP 1 PASS")
    n2 = _native(env.cwd, s2, "LOOP 2 EARLY")
    p1 = Path(rl.iteration_transcript(env.run, "pr-abc", "aaaa", 1))
    p2 = Path(rl.iteration_transcript(env.run, "pr-abc", "bbbb", 1))
    _link(p1, n1)
    _link(p2, n2)

    monkeypatch.setattr(review_loop_ui, "_is_active_loop",
                        lambda state: False)
    review_loop_ui._on_complete_from_thread(None, loop1)

    # Loop 1's own iteration is frozen; loop 2's live link is untouched.
    assert p1.is_file() and not p1.is_symlink()
    assert p2.is_symlink()
    with n2.open("a") as f:
        f.write(_record("NEEDS_WORK") + "\n")
    assert "NEEDS_WORK" in p2.read_text()


# --- sign-off retire keeps history ---------------------------------------

def test_retire_signoff_run_archives_transcript(env, monkeypatch):
    from pm_core import signoff
    from pm_core import tmux as tmux_mod

    sid = _sid()
    native = _native(env.cwd, sid, "ROUTER SIGNOFF_IMPL")
    canon = signoff.signoff_transcript(env.run, "pr-abc")
    _link(canon, native)
    signoff.stamp_signoff_launch(canon, "deadbeef")

    monkeypatch.setattr(tmux_mod, "find_window_by_name", lambda *a, **k: None)
    signoff.retire_signoff_run("pm-x", {"id": "pr-abc"}, env.run)

    assert not canon.exists() and not canon.is_symlink()
    assert signoff.signoff_launched_sha(env.run, "pr-abc") is None
    archive = cl.transcript_archive_dir(canon) / f"signoff-pr-abc.{sid}.jsonl"
    assert "ROUTER SIGNOFF_IMPL" in archive.read_text()


# --- bulk finalize on disable --------------------------------------------

def _fake_app(env, loops=None, session=None, prs=None):
    return types.SimpleNamespace(
        _root=env.tmp,
        _auto_start_run_id="run",
        _review_loops=loops or {},
        _session_name=session,
        _data={"prs": prs or []},
    )


def test_disable_skips_a_running_review_loop(env):
    from pm_core.tui import auto_start

    state = rl.ReviewLoopState(pr_id="pr-abc", loop_id="aaaa", running=True)
    app = _fake_app(env, loops={"pr-abc": state})
    tdir = auto_start.get_transcript_dir(app)
    tdir.mkdir(parents=True)
    live = _native(env.cwd, _sid(), "STILL RUNNING")
    p = Path(rl.iteration_transcript(tdir, "pr-abc", "aaaa", 1))
    _link(p, live)
    # An idle sibling proves the sweep actually ran over this directory.
    idle = tdir / "impl-pr-abc.jsonl"
    _link(idle, _native(env.cwd, _sid(), "IDLE"))

    auto_start._finalize_all_transcripts(app)

    assert p.is_symlink()  # the live collector keeps seeing appends
    with live.open("a") as f:
        f.write(_record("NEEDS_WORK") + "\n")
    assert "NEEDS_WORK" in p.read_text()
    assert idle.is_file() and not idle.is_symlink()


def test_disable_skips_a_running_watcher_transcript(env):
    """`_disable` finalizes before stopping the watcher, so the watcher's
    in-flight transcript must be treated as live."""
    from pm_core.tui import auto_start

    class _Manager:
        def list_watchers(self):
            return [{"id": "auto-start-abcd", "type": "auto-start",
                     "running": True}]

    app = _fake_app(env)
    app._watcher_manager = _Manager()
    tdir = auto_start.get_transcript_dir(app)
    tdir.mkdir(parents=True)
    live = _native(env.cwd, _sid(), "WATCHER ITERATION")
    p = tdir / "auto-start-i3.jsonl"
    _link(p, live)
    idle = tdir / "impl-pr-abc.jsonl"
    _link(idle, _native(env.cwd, _sid(), "IDLE"))

    auto_start._finalize_all_transcripts(app)

    assert p.is_symlink()
    with live.open("a") as f:
        f.write(_record("READY") + "\n")
    assert "READY" in p.read_text()
    assert idle.is_file() and not idle.is_symlink()


def test_watcher_completion_skips_a_live_review_loop(env):
    """The auto-start watcher shares its run dir with auto-start review
    loops; a completing watcher must not freeze a loop still polling."""
    from pm_core.tui import watcher_ui

    state = rl.ReviewLoopState(pr_id="pr-abc", loop_id="aaaa", running=True)
    app = _fake_app(env, loops={"pr-abc": state})
    tdir = env.run
    live = _native(env.cwd, _sid(), "LOOP STILL RUNNING")
    p = Path(rl.iteration_transcript(tdir, "pr-abc", "aaaa", 1))
    _link(p, live)
    idle = tdir / "auto-start-i2.jsonl"
    _link(idle, _native(env.cwd, _sid(), "WATCHER DONE"))

    watcher_ui._on_complete_from_thread(
        app, types.SimpleNamespace(_transcript_dir=str(tdir),
                                   latest_verdict="READY", iteration=2))

    assert p.is_symlink()
    with live.open("a") as f:
        f.write(_record("NEEDS_WORK") + "\n")
    assert "NEEDS_WORK" in p.read_text()
    assert idle.is_file() and not idle.is_symlink()


def test_live_owners_follow_step_windows(env, monkeypatch):
    """A live step window marks that step's canonical transcript live."""
    from pm_core import tmux as tmux_mod
    from pm_core.tui import auto_start

    app = _fake_app(env, session="pm-x", prs=[
        {"id": "pr-abc", "gh_pr_number": 241},
    ])
    monkeypatch.setattr(tmux_mod, "list_windows",
                        lambda session: [{"name": "#241"},
                                         {"name": "signoff-#241"}])
    exact, prefixes = auto_start._live_transcript_owners(app)
    assert "impl-pr-abc.jsonl" in exact
    assert "signoff-pr-abc.jsonl" in exact
    assert "review-pr-abc.jsonl" not in exact
    assert prefixes == set()


def test_disable_finalizes_idle_transcripts_and_archives(env):
    from pm_core.tui import auto_start

    app = _fake_app(env)
    tdir = env.tmp / "transcripts" / "run"
    tdir.mkdir(parents=True)
    canon = tdir / "impl-pr-abc.jsonl"
    _link(canon, _native(env.cwd, _sid(), "DONE"))
    archived = tdir / "archive" / "impl-pr-abc.old.jsonl"
    archived.parent.mkdir()
    archived.symlink_to(_native(env.cwd, _sid(), "ARCHIVED DONE"))

    auto_start._finalize_all_transcripts(app)

    assert canon.is_file() and not canon.is_symlink()
    assert archived.is_file() and not archived.is_symlink()
