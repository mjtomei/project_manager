"""Owner-release safety of the container reaper (review-loop 6427 i4).

An owner release ("the run that launched these containers is done with
them") must be bound to the identity the owner captured — container id
and host restart generation — recorded durably before any inventory or
lock, and retried by later passes without ever taking a replacement or a
restarted container that a newer launch now relies on.
"""

import json
import os
import subprocess
import time

import pytest

from pm_core import container as cm
from pm_core import container_reaper as reaper
from pm_core.container_reaper import ContainerInfo, Scope


def _info(name, **kw):
    p = cm.parse_container_name(name)
    defaults = dict(id="id-" + name, running=True, status="running",
                    session_tag=p.session_tag if p else None,
                    pr_id=p.pr_id() if p else None,
                    kind=p.kind if p else None,
                    created=time.time() - 3600)
    defaults.update(kw)
    return ContainerInfo(name=name, **defaults)


class _Panes:
    def __init__(self, cmds, sessions=("pm-repo-ab12",), indeterminate=False):
        self.cmds = list(cmds)
        self.sessions = sessions
        self.indeterminate = indeterminate

    def query(self, server):
        if self.indeterminate:
            return reaper._PaneSnapshot(panes=None)
        panes = [(f"%{i}", self.sessions[0], c) for i, c in enumerate(self.cmds)]
        if not panes:
            panes = [("%99", s, "bash") for s in self.sessions]
        return reaper._PaneSnapshot(panes=panes)


@pytest.fixture
def fake_env(monkeypatch):
    state = {"containers": [], "panes": _Panes([]), "removed": [],
             "statuses": {}, "fail": set()}

    monkeypatch.setattr(reaper, "list_containers", lambda: list(state["containers"]))
    monkeypatch.setattr(reaper, "_query_server", lambda s: state["panes"].query(s))
    monkeypatch.setattr(reaper, "_servers_for",
                        lambda info: [reaper._Server("k", [], "")])
    monkeypatch.setattr(reaper._PrStatus, "status",
                        lambda self, info: state["statuses"].get(info.pr_id))

    def _remove(name, *, container_id=None):
        if container_id:
            assert any(c.id == container_id and c.name == name for c in state["containers"])
        if name in state["fail"]:
            raise cm.ContainerError(f"container {name} still present after 10 s")
        state["removed"].append(name)
        state["containers"] = [c for c in state["containers"] if c.name != name]
    monkeypatch.setattr(cm, "remove_container", _remove)
    monkeypatch.setattr(cm, "current_container_id", lambda name: next(
        (c.id for c in state["containers"] if c.name == name), ""))
    monkeypatch.setattr(cm, "running_container_count",
                        lambda: len(state["containers"]))
    monkeypatch.setattr(cm, "keyring_summary", lambda: "")
    monkeypatch.setattr(cm, "pids_pressure", lambda threshold=0.9: [])
    monkeypatch.setattr(reaper, "_release_unused_proxies",
                        lambda scope, failures, checked=None: ([], True))
    return state


NAME = "pm-repo-ab12-qa-pr-aaaa-L-s1"
OTHER = "pm-repo-ab12-qa-pr-aaaa-L-s2"


def _owned(*names):
    return _Panes([f"podman exec -it {n} bash -c 'claude'" for n in names])


def _identity(*names, generation=""):
    return (dict((n, "id-" + n) for n in names),
            dict((n, generation) for n in names))


def _release(names, **kw):
    ids, gens = _identity(*names)
    kw.setdefault("expected_ids", ids)
    kw.setdefault("expected_generations", gens)
    return reaper.release_containers(list(names), owner_release=True, **kw)


def _write_generation(name, value):
    marker = cm._restart_generation_path(name)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(value)


# ---------------------------------------------------------------------------
# Identity-bound owner release
# ---------------------------------------------------------------------------

class TestOwnerReleaseIdentity:
    def test_owner_release_with_identity_ignores_own_pane(self, fake_env):
        fake_env["containers"] = [_info(NAME), _info(OTHER)]
        fake_env["panes"] = _owned(NAME, OTHER)
        out = _release([NAME])
        assert out.removed == [NAME]
        assert fake_env["containers"][0].name == OTHER
        assert reaper.pending_releases() == {}

    def test_owner_release_without_identity_is_refused(self, fake_env):
        """No captured id/generation: the name must go through the regular
        ownership checks, never be owner-released on its name alone."""
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        out = reaper.release_containers([NAME], owner_release=True)
        assert out.removed == [] and fake_env["removed"] == []
        assert NAME in out.release_refused
        assert "owned by live pane" in out.decisions[0].reason
        assert reaper.pending_releases() == {}

    def test_refusal_dropped_when_ordinary_checks_remove_it(self, fake_env):
        """An identity-less release the regular checks complete is not "deferred".

        Old resume snapshots carry no captured id/generation.  The ordinary
        ownership checks remove an unowned container anyway, so reporting that
        as "cleanup deferred ... retry with pm container reap" would contradict
        the removal and leave a message no retry can clear.
        """
        fake_env["containers"] = [_info(NAME)]
        out = reaper.release_containers([NAME], owner_release=True)
        assert out.removed == [NAME]
        assert NAME not in out.release_refused

    @pytest.mark.parametrize("missing", ["id", "generation"])
    def test_partial_identity_is_refused(self, fake_env, missing):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        ids, gens = _identity(NAME)
        if missing == "id":
            ids = {}
        else:
            gens = {}
        out = reaper.release_containers([NAME], owner_release=True,
                                        expected_ids=ids, expected_generations=gens)
        assert out.removed == []
        assert missing in out.release_refused[NAME]

    def test_scope_flag_alone_never_owner_releases(self, fake_env):
        """``Scope(owner_release=True)`` without a recorded identity is not an
        owner release: a live pane still keeps the container."""
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        out = reaper.reconcile(Scope(names={NAME}, owner_release=True),
                               reason="manual")
        assert out.removed == [] and fake_env["removed"] == []

    def test_regular_release_stays_ownership_checked(self, fake_env):
        """Even with identity supplied, the default release keeps a container
        a live pane uses."""
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        ids, gens = _identity(NAME)
        out = reaper.release_containers([NAME], expected_ids=ids,
                                        expected_generations=gens)
        assert out.removed == []
        assert reaper.pending_releases() == {}

    def test_release_does_not_take_a_replacement_inventoried_later(self, fake_env):
        """The run queued the release for id-NAME; by the time the pass
        inventories, a relaunch holds the name with a new id and a pane."""
        fake_env["containers"] = [_info(NAME, id="id-replacement")]
        fake_env["panes"] = _owned(NAME)
        out = _release([NAME])
        assert out.removed == [] and fake_env["removed"] == []
        assert "replaced" in out.decisions[0].reason
        assert reaper.pending_releases() == {}  # stale request pruned

    def test_release_request_for_gone_container_is_dropped(self, fake_env):
        fake_env["containers"] = [_info(OTHER)]
        out = _release([NAME])
        assert out.removed == []
        assert reaper.pending_releases() == {}

    def test_retained_container_is_kept_but_request_survives(self, fake_env):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        reaper.retain(NAME, "look", container_id="id-" + NAME)
        out = _release([NAME])
        assert out.removed == []
        assert "retained" in out.decisions[0].reason
        assert NAME in reaper.pending_releases()
        reaper.unretain(NAME)
        out = reaper.reconcile(reason="periodic")
        assert out.removed == [NAME]
        assert reaper.pending_releases() == {}


# ---------------------------------------------------------------------------
# Durable intent: inventory / lock failures, keep decisions, retries
# ---------------------------------------------------------------------------

class TestDurableReleaseIntent:
    def test_intent_survives_unavailable_inventory(self, fake_env, monkeypatch):
        fake_env["containers"] = [_info(NAME), _info(OTHER)]
        fake_env["panes"] = _owned(NAME, OTHER)
        monkeypatch.setattr(reaper, "list_containers", lambda: None)
        out = _release([NAME])
        assert out.error and fake_env["removed"] == []
        assert reaper.pending_releases()[NAME]["id"] == "id-" + NAME

        monkeypatch.setattr(reaper, "list_containers",
                            lambda: list(fake_env["containers"]))
        out = reaper.reconcile(reason="periodic")  # automatic pass retries it
        assert out.removed == [NAME]
        assert reaper.pending_releases() == {}

    def test_intent_survives_busy_reaper_lock(self, fake_env):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        with cm._file_lock("reaper", timeout=0) as got:
            assert got
            out = _release([NAME], reason="auto")  # non-blocking kind of pass
        assert out.skipped and fake_env["removed"] == []
        assert NAME in reaper.pending_releases()
        out = reaper.reconcile(reason="startup")
        assert out.removed == [NAME]

    def test_failed_removal_is_retried_and_visible(self, fake_env):
        fake_env["containers"] = [_info(NAME), _info(OTHER)]
        fake_env["panes"] = _owned(NAME, OTHER)
        fake_env["fail"] = {NAME}
        out = _release([NAME])
        assert NAME in out.failures
        rec = reaper.pending_failures()[NAME]
        assert rec["owner_release"] is True and rec["id"] == "id-" + NAME
        fake_env["fail"] = set()
        out = reaper.reconcile(reason="periodic")
        assert out.removed == [NAME]
        assert reaper.pending_failures() == {}
        assert reaper.pending_releases() == {}

    def test_keep_by_launch_lock_preserves_intent_and_error(self, fake_env):
        """A pass that has to keep the container (launch lock held) must not
        erase the pending release nor hide its last error."""
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        fake_env["fail"] = {NAME}
        _release([NAME])
        assert NAME in reaper.pending_failures()
        fake_env["fail"] = set()
        with cm.launch_lock(NAME, timeout=0) as got:
            assert got
            out = reaper.reconcile(reason="periodic")
        assert out.removed == []
        assert "launch in progress" in out.decisions[0].reason
        assert NAME in reaper.pending_failures(), "error hidden by keep"
        assert NAME in reaper.pending_releases()
        out = reaper.reconcile(reason="periodic")
        assert out.removed == [NAME]
        assert reaper.pending_failures() == {}

    def test_keep_by_concurrent_launch_lock_at_removal(self, fake_env, monkeypatch):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        orig = reaper.plan

        def _plan(scope=None):
            out = orig(scope)
            fake_env["hold"] = cm.launch_lock(NAME, timeout=0)
            assert fake_env["hold"].__enter__()
            return out
        monkeypatch.setattr(reaper, "plan", _plan)
        out = _release([NAME])
        fake_env["hold"].__exit__(None, None, None)
        assert out.removed == [] and "launch started concurrently" in out.decisions[0].reason
        assert NAME in reaper.pending_releases()
        monkeypatch.setattr(reaper, "plan", orig)
        assert reaper.reconcile(reason="periodic").removed == [NAME]

    def test_request_pruned_once_container_is_gone(self, fake_env):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        fake_env["fail"] = {NAME}
        _release([NAME])
        assert NAME in reaper.pending_releases()
        fake_env["containers"] = []  # someone else removed it
        reaper.reconcile(reason="periodic")
        assert reaper.pending_releases() == {}
        assert reaper.pending_failures() == {}

    def test_request_written_during_pass_is_not_pruned(self, fake_env, monkeypatch):
        orig = reaper.plan

        def _plan(scope=None):
            out = orig(scope)
            reaper._record_release(OTHER, "id-" + OTHER, "", "late")
            return out
        monkeypatch.setattr(reaper, "plan", _plan)
        reaper.reconcile(reason="periodic")
        assert OTHER in reaper.pending_releases()

    def test_marker_write_failure_is_reported_not_silent(self, fake_env, monkeypatch):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        monkeypatch.setattr(reaper, "_record_release",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        out = _release([NAME])
        assert out.removed == []
        assert "disk full" in out.release_refused[NAME]


# ---------------------------------------------------------------------------
# Restart generation
# ---------------------------------------------------------------------------

class TestRestartGeneration:
    def test_restart_generation_values(self, tmp_path, monkeypatch):
        assert reaper.restart_generation(NAME) == ""
        _write_generation(NAME, "abc\n")
        assert reaper.restart_generation(NAME) == "abc"
        monkeypatch.setattr(cm, "_restart_generation_path",
                            lambda n: tmp_path / "nodir" / "x")
        (tmp_path / "nodir").write_text("")  # NotADirectoryError
        assert reaper.restart_generation(NAME) is None

    def test_capture_identity(self, fake_env):
        fake_env["containers"] = [_info(NAME)]
        _write_generation(NAME, "g1")
        assert reaper.capture_identity(NAME) == ("id-" + NAME, "g1")
        assert reaper.capture_identity(OTHER) is None  # absent
        fake_env["containers"] = [_info(OTHER)]
        assert reaper.capture_identity(OTHER) == ("id-" + OTHER, "")

    def test_capture_identity_unknown_is_none(self, fake_env, monkeypatch):
        fake_env["containers"] = [_info(NAME)]
        monkeypatch.setattr(cm, "current_container_id", lambda n: None)
        assert reaper.capture_identity(NAME) is None
        monkeypatch.setattr(cm, "current_container_id", lambda n: "id-" + NAME)
        monkeypatch.setattr(reaper, "restart_generation", lambda n: None)
        assert reaper.capture_identity(NAME) is None

    def test_restarted_container_is_not_owner_released(self, fake_env):
        """``restart_container`` bumped the generation after the run captured
        it: the restarted container belongs to the recovery, keep it."""
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        _write_generation(NAME, "after-restart")
        out = _release([NAME])  # captured generation ""
        assert out.removed == [] and fake_env["removed"] == []
        assert "restarted" in out.decisions[0].reason
        assert reaper.pending_releases() == {}  # void request pruned

    def test_matching_generation_is_released(self, fake_env):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        _write_generation(NAME, "g1")
        ids, gens = _identity(NAME, generation="g1")
        out = reaper.release_containers([NAME], owner_release=True,
                                        expected_ids=ids, expected_generations=gens)
        assert out.removed == [NAME]

    def test_unknown_generation_defers_release(self, fake_env, monkeypatch):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        monkeypatch.setattr(reaper, "restart_generation", lambda n: None)
        out = _release([NAME])
        assert out.removed == []
        assert "generation unknown" in out.decisions[0].reason
        assert NAME in reaper.pending_releases()
        monkeypatch.setattr(reaper, "restart_generation", lambda n: "")
        assert reaper.reconcile(reason="periodic").removed == [NAME]

    def test_failed_release_after_restart_retries_same_generation(self, fake_env):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        fake_env["fail"] = {NAME}
        _write_generation(NAME, "g1")
        _release([NAME], expected_generations={NAME: "g1"})
        assert reaper.pending_failures()[NAME]["generation"] == "g1"
        fake_env["fail"] = set()
        assert reaper.reconcile(reason="periodic").removed == [NAME]

    def test_late_old_exit_cannot_overwrite_new_generation_request(self, fake_env):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        _write_generation(NAME, "g1")
        reaper._record_release(NAME, "id-" + NAME, "g1", "current")
        reaper._record_release(NAME, "id-" + NAME, "", "late-old-exit")
        assert reaper.reconcile(reason="periodic").removed == [NAME]

    def test_final_recheck_sees_restart_under_lock(self, fake_env):
        """A restart between plan() and the locked removal changes the
        generation; the removal must re-read it under the launch lock."""
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        ids, gens = _identity(NAME)  # generation "" (no marker yet)
        reaper._record_release(NAME, ids[NAME], gens[NAME], "release")
        out = reaper.plan()
        decision, = out.decisions
        assert decision.action == "remove" and decision.released
        # The restart lands after the plan was taken.
        _write_generation(NAME, "restarted-meanwhile")
        ok, reason = reaper._remove_checked(decision, reaper.Scope())
        assert not ok and "restarted" in reason
        assert fake_env["removed"] == []

    def test_legacy_release_still_applies_after_the_name_is_reused(self, fake_env):
        """A replacement's marker must not invalidate a pre-ID release.

        The legacy generation lives under the recorded name.  Once a
        replacement holds that name its marker says nothing about the old
        allocation, whose release (and its retry) must still apply.
        """
        old, cid, renamed = NAME, "id-" + NAME, "renamed-worker"
        fake_env["containers"] = [_info(renamed, id=cid),
                                  _info(old, id="replacement-id")]
        fake_env["panes"] = _Panes(
            [f"podman exec -it {renamed} bash -c 'claude'"])
        reaper._record_release(old, cid, "", "pane-exit")
        _write_generation(old, "replacement-generation")

        out = reaper.reconcile(reason="periodic")

        assert renamed in out.removed
        assert reaper.pending_releases() == {}

    def test_pending_release_retry_respects_a_reuse(self, fake_env):
        """The failed-removal retry must not delete a container reused since.

        The retry carries no release record (that is why the fallback runs),
        so its recorded generation is the only thing that can tell the
        container apart from a later launch that reused the allocation.
        """
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        reaper._record(
            reaper.Outcome(failures={NAME: "rm refused"},
                           released_failures={NAME},
                           decisions=[reaper.Decision(
                               _info(NAME), "remove", "released by its run",
                               released=True, release_generation="g1")]),
            reaper.Scope(names={NAME}), "qa-run-end")
        assert reaper.pending_failures()[NAME]["owner_release"]

        _write_generation(NAME, "g2")  # a launch reused the allocation

        out = reaper.reconcile(reason="periodic")
        assert NAME not in out.removed
        # The old request no longer describes the new attachment, so it is
        # retired rather than retried against it.
        assert NAME not in reaper.pending_failures()

    def test_final_recheck_unknown_generation_fails_closed(self, fake_env, monkeypatch):
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        calls = {"n": 0}
        orig = reaper.restart_generation

        def _gen(name):
            calls["n"] += 1
            return None if calls["n"] > 2 else orig(name)
        monkeypatch.setattr(reaper, "restart_generation", _gen)
        out = _release([NAME])
        assert fake_env["removed"] == []
        assert NAME in out.failures and "generation" in out.failures[NAME]
        assert NAME in reaper.pending_releases()


# ---------------------------------------------------------------------------
# tmux socket probing
# ---------------------------------------------------------------------------

class TestQueryServer:
    def test_missing_socket_means_no_panes(self, tmp_path):
        server = reaper._server_for_socket(str(tmp_path / "none.sock"))
        assert reaper._query_server(server).panes == []

    def test_unreadable_socket_dir_is_indeterminate(self, tmp_path, monkeypatch):
        """EACCES on the socket path is not proof that no server runs."""
        sock = str(tmp_path / "locked" / "default")
        real_stat = os.stat

        def _stat(path, *a, **kw):
            if str(path) == sock:
                raise PermissionError(13, "Permission denied", sock)
            return real_stat(path, *a, **kw)
        monkeypatch.setattr(os, "stat", _stat)
        ran = []
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **kw: ran.append(a) or (_ for _ in ()).throw(OSError()))
        snap = reaper._query_server(reaper._server_for_socket(sock))
        assert snap.panes is None

    def test_socket_exists_queries_tmux(self, tmp_path, monkeypatch):
        sock = tmp_path / "default"
        sock.touch()
        # The start command is last: any ':' of its own stay in that field.
        command = f"podman exec -it {NAME} sh -c 'echo a:b'"
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0, stdout=f"0:%1:pm-x:123:{command}\n", stderr=""))
        monkeypatch.setattr(reaper, "_pane_process_commands", lambda pids: {123: []})
        snap = reaper._query_server(reaper._server_for_socket(str(sock)))
        assert snap.panes == [("%1", "pm-x", command)]

    def test_pane_format_has_no_control_character_separator(self, tmp_path, monkeypatch):
        """tmux rewrites a tab separator to '_' unless the client is UTF-8.

        A mangled row is unparseable, which would report every container as
        ownership-unknown and silently disable automatic cleanup.
        """
        sock = tmp_path / "default"
        sock.touch()
        captured = {}

        def run(args, **kwargs):
            captured["fmt"] = args[args.index("-F") + 1]
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", run)
        reaper._query_server(reaper._server_for_socket(str(sock)))
        fmt = captured["fmt"]
        assert not any(ch in fmt for ch in "\t\n\r"), fmt


# ---------------------------------------------------------------------------
# Marker file format
# ---------------------------------------------------------------------------

class TestReleaseMarkers:
    def test_marker_is_atomic_json_per_name_and_id(self):
        reaper._record_release(NAME, "id-1", "g", "qa-run-end")
        files = sorted(p.name for p in reaper._release_dir().iterdir())
        assert len(files) == 1 and files[0].startswith(f"{NAME}@id-1-")
        rec = json.loads((reaper._release_dir() / files[0]).read_text())
        assert rec["name"] == NAME and rec["id"] == "id-1"
        assert rec["generation"] == "g" and rec["reason"] == "qa-run-end"
        reaper._record_release(NAME, "id-2", "g", "pane-exit")
        assert set(reaper.pending_releases()) == {NAME}
        assert reaper.pending_releases()[NAME]["id"] == "id-2"

    def test_corrupt_marker_is_ignored(self, fake_env):
        d = reaper._release_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{NAME}@bad.json").write_text("{not json")
        fake_env["containers"] = [_info(NAME)]
        fake_env["panes"] = _owned(NAME)
        out = reaper.reconcile(reason="periodic")
        assert out.removed == []
        assert reaper.pending_releases() == {}
        assert list(d.iterdir())  # preserve corrupt evidence; never authorize deletion
