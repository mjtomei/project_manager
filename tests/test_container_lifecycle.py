"""Container lifecycle: ownership-aware reaping, verified reuse, launch errors.

Covers pr-1139060: leaked running containers exhaust the rootless keyring /
PID limits; reuse of half-set-up containers; QA run-end release.
"""

import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core import container as cm
from pm_core import container_reaper as reaper
from pm_core.container_reaper import ContainerInfo, Scope


def _cp(rc=0, out="", err=""):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr=err)


# ---------------------------------------------------------------------------
# Name parsing / error classification / keyring parsing
# ---------------------------------------------------------------------------

class TestParseContainerName:
    def test_tagged_kinds(self):
        for kind in ("impl", "review", "signoff"):
            p = cm.parse_container_name(f"pm-repo-ab12-{kind}-pr-1a2b3c")
            assert (p.kind, p.session_tag, p.pr_id()) == (kind, "repo-ab12", "pr-1a2b3c")

    def test_qa_with_loop_and_scenario(self):
        p = cm.parse_container_name("pm-repo-ab12-qa-pr-1a2b3c-loop9-s10")
        assert (p.kind, p.session_tag, p.pr_id()) == ("qa", "repo-ab12", "pr-1a2b3c")

    def test_legacy_untagged(self):
        p = cm.parse_container_name("pm-review-pr-00ff")
        assert (p.kind, p.session_tag, p.pr_id()) == ("review", None, "pr-00ff")

    def test_tag_containing_kind_word(self):
        p = cm.parse_container_name("pm-review-tool-cafe-impl-pr-beef")
        assert (p.kind, p.session_tag, p.pr_id()) == ("impl", "review-tool-cafe", "pr-beef")

    def test_qa_debug_not_qa(self):
        p = cm.parse_container_name("pm-qa-debug-instr-abc")
        assert p.kind == "qa-debug"

    def test_not_pm(self):
        assert cm.parse_container_name("redis") is None


class TestClassifyRuntimeError:
    @pytest.mark.parametrize("text,kind", [
        ("Error: unable to start container process: unable to join session "
         "keyring: unable to create session key: disk quota exceeded", "keyring"),
        ("runc: fork/exec: cannot allocate memory", "memory"),
        ("sh: Cannot fork", "pids"),
        ("bash: fork: retry: Resource temporarily unavailable", "pids"),
        ("Error: pm-dev:latest: image not known", "image"),
        ("something else", "runtime"),
        ("", "runtime"),
    ])
    def test_kinds(self, text, kind):
        assert cm.classify_runtime_error(text) == kind


class TestKeyring:
    TEXT = ("    0:   120 119/119 115/1000000 2079/25000000\n"
            "100000:   200 200/200 198/200 3910/20000\n")

    def test_usage_and_pressure(self):
        with patch.object(Path, "read_text", return_value=self.TEXT):
            rows = cm.keyring_usage()
            assert rows[100000] == {"keys": 198, "max_keys": 200,
                                    "bytes": 3910, "max_bytes": 20000}
            worst = cm.keyring_pressure(0.9)
            assert worst["uid"] == 100000
            assert "198/200 keys" in cm.keyring_summary()

    def test_unreadable(self):
        with patch.object(Path, "read_text", side_effect=OSError):
            assert cm.keyring_usage() is None
            assert cm.keyring_pressure() is None


class TestLaunchError:
    def test_keyring_message_keeps_cause_and_recovery(self):
        err_text = "unable to create session key: disk quota exceeded"
        with patch.object(cm, "keyring_summary", return_value="uid 100000: 199/200 keys"), \
             patch.object(cm, "running_container_count", return_value=71):
            e = cm.launch_error("pm-x-review-pr-1", "keyring", err_text)
        msg = str(e)
        assert e.kind == "keyring" and e.stderr == err_text
        assert err_text in msg
        assert "pm container reap" in msg
        assert "71 running" in msg
        assert "pm session cleanup" not in msg
        assert "memory" not in msg.split("Runtime error")[0]

    def test_pids_message_names_restart(self):
        e = cm.launch_error("pm-x-qa-pr-1-l-s28", "pids", "sh: Cannot fork")
        assert "pm container restart pm-x-qa-pr-1-l-s28" in str(e)
        assert "Cannot fork" in str(e)


# ---------------------------------------------------------------------------
# Reaper decisions
# ---------------------------------------------------------------------------

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
    """Fake tmux: one server with the given pane start commands."""

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

    def _status(self, info):
        return state["statuses"].get(info.pr_id)
    monkeypatch.setattr(reaper._PrStatus, "status", _status)

    def _remove(name):
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
    monkeypatch.setattr(reaper, "_release_unused_proxies", lambda scope: [])
    return state


class TestReaperOwnership:
    def test_exact_pane_match_no_scenario_suffix_collision(self, fake_env):
        """A live qa-*-s1 pane of ANOTHER PR/loop must not keep s1 alive,
        and the s1 container's pane must not keep s10."""
        mine = "pm-repo-ab12-qa-pr-aaaa-loopA-s1"
        other_pr = "pm-repo-ab12-qa-pr-bbbb-loopB-s1"
        s10 = "pm-repo-ab12-qa-pr-aaaa-loopA-s10"
        fake_env["containers"] = [_info(mine), _info(other_pr), _info(s10)]
        fake_env["panes"] = _Panes([f"podman exec -it {other_pr} bash -c 'claude'"])
        out = reaper.reconcile(reason="manual")
        assert sorted(out.removed) == sorted([mine, s10])
        kept = [d for d in out.decisions if d.action == "keep"]
        assert [d.info.name for d in kept] == [other_pr]

    def test_container_id_in_trap_counts_as_owner(self, fake_env):
        c = _info("pm-repo-ab12-review-pr-aaaa", id="deadbeef" * 8)
        fake_env["containers"] = [c]
        fake_env["panes"] = _Panes([f"bash -c 'trap \"podman rm -f {c.id}\" EXIT; x'"])
        assert reaper.reconcile(reason="manual").removed == []

    def test_retained_kept_unless_included(self, fake_env):
        name = "pm-repo-ab12-impl-pr-aaaa"
        fake_env["containers"] = [_info(name)]
        fake_env["statuses"] = {"pr-aaaa": "merged"}
        reaper.retain(name, "discussion")
        out = reaper.reconcile(reason="manual")
        assert out.removed == []
        assert "retained" in out.decisions[0].reason
        out = reaper.reconcile(Scope(include_retained=True), reason="manual")
        assert out.removed == [name]

    def test_retention_does_not_carry_over_to_a_replacement(self, fake_env):
        """A marker set on one container must not retain a later container
        launched under the same name, and is pruned once its container is
        gone (full passes)."""
        name = "pm-repo-ab12-review-pr-aaaa"
        reaper.retain(name, "discussion", container_id="old-id")
        fake_env["containers"] = [_info(name, id="new-id")]
        out = reaper.reconcile(reason="manual")
        assert out.removed == [name]
        assert not reaper.is_retained(name)  # pruned with its container

    def test_retention_marker_pruned_when_container_gone(self, fake_env):
        kept, gone = "pm-repo-ab12-impl-pr-aaaa", "pm-repo-ab12-impl-pr-bbbb"
        fake_env["containers"] = [_info(kept)]
        reaper.retain(kept, container_id="id-" + kept)
        reaper.retain(gone, container_id="id-" + gone)
        reaper.reconcile(Scope(pr_id="pr-aaaa"), reason="manual")
        assert reaper.is_retained(gone)  # scoped passes don't prune
        reaper.reconcile(reason="manual")
        assert reaper.retained_names() == [kept]

    def test_launch_grace_and_launch_lock(self, fake_env):
        fresh = _info("pm-repo-ab12-impl-pr-aaaa", created=time.time())
        locked = _info("pm-repo-ab12-review-pr-aaaa")
        fake_env["containers"] = [fresh, locked]
        with cm.launch_lock(locked.name, timeout=0) as got:
            assert got
            out = reaper.reconcile(reason="manual")
        assert out.removed == []
        reasons = {d.info.name: d.reason for d in out.decisions}
        assert "launching" in reasons[fresh.name]
        assert "launch in progress" in reasons[locked.name]

    def test_merged_pr_and_dead_session_reasons(self, fake_env):
        merged = _info("pm-repo-ab12-impl-pr-aaaa")
        dead = _info("pm-gone-1234-review-pr-bbbb", session_tag="gone-1234")
        fake_env["containers"] = [merged, dead]
        fake_env["statuses"] = {"pr-aaaa": "merged"}
        out = reaper.reconcile(reason="manual")
        reasons = {d.info.name: d.reason for d in out.decisions}
        assert "merged" in reasons[merged.name]
        assert "gone" in reasons[dead.name]
        assert sorted(out.removed) == sorted([merged.name, dead.name])

    def test_unknown_tmux_keeps_even_merged(self, fake_env):
        fake_env["containers"] = [_info("pm-repo-ab12-impl-pr-aaaa")]
        fake_env["statuses"] = {"pr-aaaa": "merged"}
        fake_env["panes"] = _Panes([], indeterminate=True)
        out = reaper.reconcile(reason="manual")
        assert out.removed == []
        assert "unknown" in out.decisions[0].reason

    def test_recheck_under_lock_skips_concurrent_attach(self, fake_env, monkeypatch):
        name = "pm-repo-ab12-impl-pr-aaaa"
        fake_env["containers"] = [_info(name)]
        calls = {"n": 0}
        orig = reaper._owner_panes

        def _owner(info, cache, fresh=False):
            calls["n"] += 1
            if fresh:  # the re-check: a pane attached meanwhile
                return ["%7"], False
            return orig(info, cache, fresh)
        monkeypatch.setattr(reaper, "_owner_panes", _owner)
        out = reaper.reconcile(reason="manual")
        assert out.removed == []
        assert "attached concurrently" in out.decisions[0].reason

    def test_recheck_under_lock_skips_replaced_container(self, fake_env, monkeypatch):
        """A relaunch between plan and removal swapped in a new container of
        the same name (no pane attached yet): removal by name must not hit it."""
        name = "pm-repo-ab12-review-pr-aaaa"
        fake_env["containers"] = [_info(name)]
        monkeypatch.setattr(cm, "current_container_id", lambda n: "id-replacement")
        out = reaper.reconcile(reason="manual")
        assert out.removed == [] and fake_env["removed"] == []
        assert "replaced by a newer launch" in out.decisions[0].reason

    def test_dry_run_removes_nothing(self, fake_env):
        fake_env["containers"] = [_info("pm-repo-ab12-impl-pr-aaaa")]
        out = reaper.reconcile(dry_run=True, reason="dry-run")
        assert fake_env["removed"] == []
        assert out.to_remove and "would remove 1" in out.summary()

    def test_failures_recorded_then_cleared(self, fake_env):
        name = "pm-repo-ab12-impl-pr-aaaa"
        fake_env["containers"] = [_info(name)]
        fake_env["fail"] = {name}
        out = reaper.reconcile(reason="periodic")
        assert name in out.failures
        assert name in reaper.pending_failures()
        fake_env["fail"] = set()
        out = reaper.reconcile(reason="periodic")
        assert out.removed == [name]
        assert reaper.pending_failures() == {}

    def test_owner_release_ignores_own_panes_but_not_retention(self, fake_env):
        a = "pm-repo-ab12-qa-pr-aaaa-L-s1"
        b = "pm-repo-ab12-qa-pr-aaaa-L-s2"
        fake_env["containers"] = [_info(a, created=time.time()), _info(b)]
        fake_env["panes"] = _Panes([f"podman exec -it {a} x", f"podman exec -it {b} x"])
        reaper.retain(b)
        out = reaper.release_containers([a, b], owner_release=True)
        assert out.removed == [a]

    def test_failed_owner_release_is_retried_despite_live_pane(self, fake_env):
        """A run-end release that failed must not leave the container owned by
        the run's own still-live pane: later passes retry it as released."""
        name = "pm-repo-ab12-qa-pr-aaaa-L-s1"
        other = "pm-repo-ab12-qa-pr-aaaa-L-s2"
        fake_env["containers"] = [_info(name), _info(other)]
        fake_env["panes"] = _Panes([f"podman exec -it {name} x",
                                    f"podman exec -it {other} x"])
        fake_env["fail"] = {name}
        out = reaper.release_containers([name], owner_release=True)
        assert name in out.failures
        assert reaper.pending_failures()[name]["owner_release"] is True

        fake_env["fail"] = set()
        out = reaper.reconcile(reason="periodic")
        assert out.removed == [name]  # the other live-pane container is kept
        assert reaper.pending_failures() == {}

    def test_failed_owner_release_does_not_take_a_recreated_container(self, fake_env):
        """The retry marker is bound to the released container's id: a new
        container launched under the same name keeps its live-pane owner."""
        name = "pm-repo-ab12-qa-pr-aaaa-L-s1"
        fake_env["containers"] = [_info(name)]
        fake_env["panes"] = _Panes([f"podman exec -it {name} x"])
        fake_env["fail"] = {name}
        reaper.release_containers([name], owner_release=True)
        assert reaper.pending_failures()[name]["id"] == "id-" + name

        fake_env["fail"] = set()
        fake_env["containers"] = [_info(name, id="id-replacement")]
        out = reaper.reconcile(reason="periodic")
        assert out.removed == []
        assert "owned by live pane" in out.decisions[0].reason

    def test_pid_pressure_reported_for_kept(self, fake_env, monkeypatch):
        name = "pm-repo-ab12-qa-pr-aaaa-L-s28"
        fake_env["containers"] = [_info(name)]
        fake_env["panes"] = _Panes([f"podman exec -it {name} claude"])
        monkeypatch.setattr(cm, "pids_pressure",
                            lambda threshold=0.9: [(name, 2041, 2048)])
        out = reaper.reconcile(reason="manual")
        assert out.removed == []
        assert out.pid_pressure and out.pid_pressure[0][:3] == (name, 2041, 2048)
        assert "near PID limit" in out.summary()

    def test_runtime_unavailable_is_outcome_not_exception(self, monkeypatch):
        monkeypatch.setattr(reaper, "list_containers", lambda: None)
        out = reaper.reconcile(reason="manual")
        assert out.error and out.removed == []


# ---------------------------------------------------------------------------
# Verified reuse / setup failure cleanup
# ---------------------------------------------------------------------------

class _Runtime:
    """Scriptable ``_run_runtime`` replacement keyed on the subcommand."""

    def __init__(self, **handlers):
        self.handlers = handlers
        self.calls = []

    def __call__(self, *args, check=True, timeout=30):
        self.calls.append(args)
        h = self.handlers.get(args[0])
        r = h(*args) if callable(h) else (h or _cp(0, "cid\n"))
        if check and r.returncode != 0:
            raise subprocess.CalledProcessError(r.returncode, list(args),
                                                output=r.stdout, stderr=r.stderr)
        return r

    def ran(self, sub):
        return [c for c in self.calls if c[0] == sub]


@pytest.fixture
def no_claude_json(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "_host_claude_json", lambda: tmp_path / "none.json")


class TestEnsureReusable:
    def _setup(self, monkeypatch, rt, owners=()):
        monkeypatch.setattr(cm, "_run_runtime", rt)
        monkeypatch.setattr(cm, "container_is_running", lambda n: True)
        monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
        monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: list(owners))
        removed = []
        monkeypatch.setattr(cm, "remove_container", removed.append)
        return removed

    def test_complete_is_reused(self, monkeypatch, no_claude_json):
        rt = _Runtime()
        removed = self._setup(monkeypatch, rt)
        assert cm._ensure_reusable("c", Path("/w"), None,
                                   session_tag=None, pr_id=None) == "cid"
        assert removed == []

    def test_ready_but_unfinished_is_finished_in_place(self, monkeypatch, no_claude_json):
        state = {"complete": False}

        def _exec(*args):
            if cm.SETUP_COMPLETE_SENTINEL in " ".join(args) and "touch" not in args:
                return _cp(0) if state["complete"] else _cp(1)
            if "touch" in args:
                state["complete"] = True
            return _cp(0)
        rt = _Runtime(exec=_exec)
        removed = self._setup(monkeypatch, rt)
        assert cm._ensure_reusable("c", Path("/w"), None,
                                   session_tag=None, pr_id=None) == "cid"
        assert removed == []
        assert any("touch" in c for c in rt.ran("exec"))

    def test_never_set_up_is_removed_for_recreate(self, monkeypatch, no_claude_json):
        rt = _Runtime(exec=lambda *a: _cp(1))
        removed = self._setup(monkeypatch, rt)
        assert cm._ensure_reusable("c", Path("/w"), None,
                                   session_tag=None, pr_id=None) is None
        assert removed == ["c"]

    def test_incomplete_with_live_owner_is_not_killed(self, monkeypatch, no_claude_json):
        rt = _Runtime(exec=lambda *a: _cp(1))
        removed = self._setup(monkeypatch, rt, owners=["%3"])
        with pytest.raises(cm.ContainerLaunchError) as ei:
            cm._ensure_reusable("c", Path("/w"), None, session_tag=None, pr_id=None)
        assert ei.value.kind == "incomplete"
        assert removed == []

    def test_missing_claude_json_is_incomplete(self, monkeypatch, tmp_path):
        host = tmp_path / ".claude.json"
        host.write_text("{}")
        monkeypatch.setattr(cm, "_host_claude_json", lambda: host)
        seen = []

        def _exec(*args):
            seen.append(args)
            if "test -s" in " ".join(args):
                return _cp(1)  # sentinel present, config missing
            return _cp(1)
        rt = _Runtime(exec=_exec)
        removed = self._setup(monkeypatch, rt)
        assert cm._ensure_reusable("c", Path("/w"), None,
                                   session_tag=None, pr_id=None) is None
        assert removed == ["c"]
        assert any(".claude.json" in " ".join(a) for a in seen)

    def test_pid_exhausted_unowned_is_restarted_in_place(self, monkeypatch, no_claude_json):
        state = {"restarted": False}

        def _exec(*args):
            return _cp(0) if state["restarted"] else _cp(126, err="sh: Cannot fork")

        def _restart(*args):
            state["restarted"] = True
            return _cp(0)
        rt = _Runtime(exec=_exec, restart=_restart)
        removed = self._setup(monkeypatch, rt)
        assert cm._ensure_reusable("c", Path("/w"), None,
                                   session_tag=None, pr_id=None) == "cid"
        assert rt.ran("restart") and removed == []

    def test_pid_exhausted_owned_raises_real_cause(self, monkeypatch, no_claude_json):
        rt = _Runtime(exec=lambda *a: _cp(126, err="sh: Cannot fork"))
        removed = self._setup(monkeypatch, rt, owners=["%5"])
        with pytest.raises(cm.ContainerLaunchError) as ei:
            cm._ensure_reusable("c", Path("/w"), None, session_tag=None, pr_id=None)
        assert ei.value.kind == "pids"
        assert "Cannot fork" in str(ei.value) and "%5" in str(ei.value)
        assert not rt.ran("restart") and removed == []

    def test_restart_timeout_does_not_claim_removal(self, monkeypatch):
        monkeypatch.setattr(cm, "_run_runtime", _Runtime())

        def _timeout(name):
            raise cm.launch_error(name, "timeout", "sentinel missing",
                                  stage="finish setup")
        monkeypatch.setattr(cm, "_wait_for_setup", _timeout)
        with pytest.raises(cm.ContainerLaunchError) as ei:
            cm.restart_container("c")
        assert "removed" not in str(ei.value)
        assert "sentinel missing" in str(ei.value)


class TestCreateFailureCleanup:
    def _patch(self, monkeypatch, rt):
        monkeypatch.setattr(cm, "_run_runtime", rt)
        monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
        monkeypatch.setattr(cm, "container_is_running", lambda n: False)
        monkeypatch.setattr(cm, "image_exists", lambda *a: True)
        monkeypatch.setattr(cm, "keyring_pressure", lambda *a, **k: None)
        monkeypatch.setattr(cm, "_SETUP_TIMEOUT", 0.3)
        monkeypatch.setattr(cm, "_SETUP_POLL_INTERVAL", 0.05)
        removed = []
        monkeypatch.setattr(cm, "remove_container", removed.append)
        return removed

    def test_run_failure_keeps_runtime_stderr(self, monkeypatch, no_claude_json):
        err = ("Error: unable to start container process: unable to join "
               "session keyring: unable to create session key: disk quota exceeded")
        rt = _Runtime(run=_cp(126, err=err))
        removed = self._patch(monkeypatch, rt)
        with pytest.raises(cm.ContainerLaunchError) as ei:
            cm.create_container("pm-t-impl-pr-1", cm.ContainerConfig(), Path("/w"))
        assert ei.value.kind == "keyring"
        assert "disk quota exceeded" in str(ei.value)
        assert "pm container reap" in str(ei.value)
        assert removed.count("pm-t-impl-pr-1") == 2  # pre-clean + partial discard

    def test_setup_timeout_removes_partial(self, monkeypatch, no_claude_json):
        rt = _Runtime(exec=lambda *a: _cp(1))
        removed = self._patch(monkeypatch, rt)
        with pytest.raises(cm.ContainerLaunchError) as ei:
            cm.create_container("pm-t-impl-pr-1", cm.ContainerConfig(), Path("/w"))
        assert ei.value.kind == "timeout"
        assert removed[-1] == "pm-t-impl-pr-1"
        assert "pm session cleanup" not in str(ei.value)

    def test_claude_json_copy_failure_is_launch_failure(self, monkeypatch, tmp_path):
        host = tmp_path / ".claude.json"
        host.write_text("{}")
        monkeypatch.setattr(cm, "_host_claude_json", lambda: host)
        rt = _Runtime(cp=_cp(125, err="Error: no space left on device"))
        removed = self._patch(monkeypatch, rt)
        with pytest.raises(cm.ContainerLaunchError) as ei:
            cm.create_container("pm-t-impl-pr-1", cm.ContainerConfig(), Path("/w"))
        assert "no space left" in str(ei.value)
        assert removed[-1] == "pm-t-impl-pr-1"
        # never marked complete
        assert not any("touch" in c and cm.SETUP_COMPLETE_SENTINEL in c
                       for c in rt.ran("exec"))

    def test_success_labels_and_reaping_pid1(self, monkeypatch, no_claude_json):
        rt = _Runtime()
        self._patch(monkeypatch, rt)
        cm.create_container("pm-t-qa-pr-1-L-s3", cm.ContainerConfig(), Path("/w"),
                            session_tag="t", pr_id="pr-1", kind="qa",
                            loop_id="L", scenario=3)
        run = rt.ran("run")[0]
        labels = {run[i + 1] for i, a in enumerate(run) if a == "--label"}
        assert {"pm.managed=1", "pm.kind=qa", "pm.loop_id=L", "pm.scenario=3",
                "pm.session_tag=t", "pm.pr_id=pr-1"} <= labels
        assert "exec sleep infinity" not in run[-1]
        assert "wait $!" in run[-1]
        assert any(cm.SETUP_COMPLETE_SENTINEL in c for c in rt.ran("exec"))


class TestExecTrapById:
    def test_trap_removes_by_id(self, monkeypatch):
        monkeypatch.setattr(cm, "_get_runtime", lambda: "podman")
        cmd = cm.build_exec_cmd("pm-t-review-pr-1", "claude", container_id="abc123")
        assert "rm -f abc123" in cmd
        assert "rm -f pm-t-review-pr-1" not in cmd


class TestFileLock:
    def test_lock_on_unlinked_inode_is_not_kept(self, monkeypatch):
        """A lock won on a file the reaper just unlinked must be retaken on
        the recreated path, or two launches could both 'hold' it."""
        path = cm._lock_path("container-x")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        real_flock = cm.fcntl.flock
        state = {"swapped": False}

        def _flock(fd, op):
            real_flock(fd, op)
            if op & cm.fcntl.LOCK_EX and not state["swapped"]:
                state["swapped"] = True  # reaper prunes + a launcher recreates
                path.unlink()
                path.write_text("")
        monkeypatch.setattr(cm.fcntl, "flock", _flock)
        with cm.launch_lock("x", timeout=1) as got:
            assert got
            # The lock now held is on the current file: a second try fails.
            monkeypatch.setattr(cm.fcntl, "flock", real_flock)
            with cm.launch_lock("x", timeout=0) as again:
                assert not again


# ---------------------------------------------------------------------------
# Shared push proxy release
# ---------------------------------------------------------------------------

class TestProxyRelease:
    def test_kept_while_any_container_uses_it(self, monkeypatch):
        from pm_core import push_proxy
        monkeypatch.setattr(cm, "containers_for_pr",
                            lambda tag, pr: {"pm-t-impl-pr-1"})
        killed = []
        monkeypatch.setattr(push_proxy, "_kill_proxy_socket", killed.append)
        assert push_proxy.release_proxy_if_unused("t", "pr-1") is False
        assert killed == []

    def test_stopped_when_runtime_reports_none(self, monkeypatch):
        from pm_core import push_proxy
        monkeypatch.setattr(cm, "containers_for_pr", lambda tag, pr: set())
        killed = []
        monkeypatch.setattr(push_proxy, "_kill_proxy_socket", killed.append)
        push_proxy.release_proxy_if_unused("t", "pr-1")
        assert len(killed) == 1

    def test_unknown_runtime_does_nothing(self, monkeypatch):
        from pm_core import push_proxy
        monkeypatch.setattr(cm, "containers_for_pr", lambda tag, pr: None)
        killed = []
        monkeypatch.setattr(push_proxy, "_kill_proxy_socket", killed.append)
        assert push_proxy.release_proxy_if_unused("t", "pr-1") is None
        assert killed == []

    def test_foreign_per_container_proxy_stopped_on_remove(self, monkeypatch, tmp_path):
        """A qa-debug/untagged container removed by another process (the
        reaper) still has its private proxy stopped."""
        import tempfile
        from pm_core import push_proxy
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        name = "pm-qa-debug-abc-123"
        sock_dir = tmp_path / f"{push_proxy._SOCKET_DIR_PREFIX}{name}"
        sock_dir.mkdir()
        (sock_dir / "push.sock").write_text("")
        killed = []
        monkeypatch.setattr(push_proxy, "_kill_proxy_socket", killed.append)
        push_proxy.stop_push_proxy(name)
        assert killed == [str(sock_dir / "push.sock")]

    def test_legacy_listing_skips_per_container_proxy_dirs(self):
        """An untagged container's private proxy dir (``…-pm-impl-pr-x``)
        has the legacy shared-dir shape but must not be swept as shared —
        its "session" would match no container and the live proxy die."""
        import secrets
        import shutil
        from pm_core import push_proxy
        hx = secrets.token_hex(4)
        private = Path(f"/tmp/{push_proxy._SOCKET_DIR_PREFIX}pm-impl-pr-{hx}")
        shared = Path(f"/tmp/{push_proxy._SOCKET_DIR_PREFIX}legacytag{hx}-pr-{hx}")
        try:
            private.mkdir()
            shared.mkdir()
            found = {(p["session_tag"], p["pr_id"])
                     for p in push_proxy.list_shared_proxies()}
            assert (f"legacytag{hx}", f"pr-{hx}") in found
            assert ("pm-impl", f"pr-{hx}") not in found
        finally:
            shutil.rmtree(private, ignore_errors=True)
            shutil.rmtree(shared, ignore_errors=True)

    def test_legacy_symlinked_shared_proxy_is_listed(self):
        """A pre-owner-file shared proxy with a long tag lives in a hashed
        dir behind a long-name symlink; the symlink identifies it."""
        import secrets
        import shutil
        from pm_core import push_proxy
        hx = secrets.token_hex(4)
        real = Path(f"/tmp/{push_proxy._SOCKET_DIR_PREFIX}{hx}hashed")
        link = Path(f"/tmp/{push_proxy._SOCKET_DIR_PREFIX}longtag{hx}-pr-{hx}")
        try:
            real.mkdir()
            link.symlink_to(real)
            found = [(p["session_tag"], p["pr_id"])
                     for p in push_proxy.list_shared_proxies()]
            assert found.count((f"longtag{hx}", f"pr-{hx}")) == 1
        finally:
            link.unlink(missing_ok=True)
            shutil.rmtree(real, ignore_errors=True)

    def test_reused_proxy_without_owner_file_gets_one(self, monkeypatch, tmp_path):
        import json
        from pm_core import push_proxy
        sock_dir = tmp_path / "proxy"
        sock_dir.mkdir()
        (sock_dir / "push.sock").write_text("")
        monkeypatch.setattr(push_proxy, "_shared_sock_dir", lambda t, p: str(sock_dir))
        monkeypatch.setattr(push_proxy, "proxy_is_alive", lambda s: True)
        push_proxy.start_push_proxy("pm-t-impl-pr-1", "/w", "b",
                                    session_tag="t", pr_id="pr-1")
        owner = json.loads((sock_dir / push_proxy._OWNER_FILE).read_text())
        assert (owner["session_tag"], owner["pr_id"]) == ("t", "pr-1")
        push_proxy._proxy_refs.pop(push_proxy._shared_proxy_key("t", "pr-1"), None)
        push_proxy._container_to_proxy_key.pop("pm-t-impl-pr-1", None)

    def test_foreign_shared_container_leaves_private_paths_alone(self, monkeypatch, tmp_path):
        import tempfile
        from pm_core import push_proxy
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        released = []
        monkeypatch.setattr(push_proxy, "release_proxy_if_unused",
                            lambda tag, pr, exclude=(): released.append((tag, pr)))
        killed = []
        monkeypatch.setattr(push_proxy, "_kill_proxy_socket", killed.append)
        push_proxy.stop_push_proxy("pm-t-impl-pr-1a2b")
        assert released == [("t", "pr-1a2b")]
        assert killed == []


# ---------------------------------------------------------------------------
# QA: run-end release and launch failures
# ---------------------------------------------------------------------------

class TestQARelease:
    def _state(self):
        from pm_core import qa_loop
        st = qa_loop.QALoopState(pr_id="pr-aaaa")
        st.loop_id = "L"
        st.scenarios = [
            qa_loop.QAScenario(index=i, title=f"s{i}", focus="",
                               container_name=f"pm-t-qa-pr-aaaa-L-s{i}",
                               pane_id=f"%{i}")
            for i in (1, 2, 3)
        ]
        st.scenario_verdicts = {1: qa_loop.VERDICT_PASS,
                                2: qa_loop.VERDICT_INPUT_REQUIRED,
                                3: qa_loop.VERDICT_NEEDS_WORK}
        return st

    def test_releases_all_but_input_required_and_viewed(self, monkeypatch):
        from pm_core import qa_loop, tmux
        st = self._state()
        monkeypatch.setattr(qa_loop, "_viewed_window_ids", lambda s: {"@3"})
        monkeypatch.setattr(tmux, "pane_window_id",
                            lambda p: {"%1": "@1", "%3": "@3"}.get(p))
        got = {}

        def _release(names, **kw):
            got["names"], got["kw"] = names, kw
            return reaper.Outcome(removed=list(names))
        monkeypatch.setattr(reaper, "release_containers", _release)
        assert qa_loop._release_scenario_containers(st, "pm-t") is False
        assert got["names"] == ["pm-t-qa-pr-aaaa-L-s1"]
        assert got["kw"]["owner_release"] is True

    def test_failed_release_is_visible(self, monkeypatch):
        from pm_core import qa_loop
        st = self._state()
        st.scenario_verdicts = {1: qa_loop.VERDICT_PASS}
        st.latest_output = "QA complete: X"
        monkeypatch.setattr(qa_loop, "_viewed_window_ids", lambda s: set())
        monkeypatch.setattr(reaper, "release_containers",
                            lambda names, **kw: reaper.Outcome(
                                failures={names[0]: "boom"}))
        assert qa_loop._release_scenario_containers(st, "pm-t") is True
        assert "pm container reap" in st.latest_output

    def test_skipped_release_is_retried_in_background(self, monkeypatch):
        from pm_core import qa_loop
        st = self._state()
        st.scenario_verdicts = {1: qa_loop.VERDICT_PASS}
        monkeypatch.setattr(qa_loop, "_viewed_window_ids", lambda s: set())
        calls = []

        def _release(names, **kw):
            calls.append(kw)
            return reaper.Outcome(skipped=True) if kw.get("wait", True) else None
        monkeypatch.setattr(reaper, "release_containers", _release)
        qa_loop._release_scenario_containers(st, "pm-t")
        assert len(calls) == 2
        assert calls[1]["wait"] is False and calls[1]["owner_release"] is True

    def test_launch_failure_is_not_a_verdict(self):
        from pm_core import qa_loop
        st = self._state()
        st.scenario_verdicts = {}
        qa_loop._record_launch_failure(st, st.scenarios[0],
                                       "Container 'x' could not start: Cannot fork")
        assert 1 not in st.scenario_verdicts
        assert qa_loop._is_launch_failure(st, 1)
        assert "launch failed" in qa_loop.qa_outcome_detail(st)


class TestMaxRunningClamp:
    def test_clamp(self, monkeypatch):
        from pm_core import qa_loop
        monkeypatch.setattr(cm, "max_running_containers", lambda: 10)
        monkeypatch.setattr(cm, "running_container_count", lambda: 8)
        assert qa_loop._clamp_to_container_headroom(0) == 2
        assert qa_loop._clamp_to_container_headroom(1) == 1
        monkeypatch.setattr(cm, "running_container_count", lambda: 12)
        assert qa_loop._clamp_to_container_headroom(5) == 1

    def test_unlimited(self, monkeypatch):
        from pm_core import qa_loop
        monkeypatch.setattr(cm, "max_running_containers", lambda: 0)
        assert qa_loop._clamp_to_container_headroom(0) == 0
        assert qa_loop._clamp_to_container_headroom(3) == 3


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class TestReapCLI:
    def test_dry_run_preview(self, fake_env):
        from click.testing import CliRunner
        from pm_core.cli import cli
        fake_env["containers"] = [_info("pm-repo-ab12-impl-pr-aaaa")]
        fake_env["statuses"] = {"pr-aaaa": "merged"}
        r = CliRunner().invoke(cli, ["container", "reap", "--dry-run"])
        assert r.exit_code == 0, r.output
        assert "remove" in r.output and "merged" in r.output
        assert "would remove 1" in r.output
        assert fake_env["removed"] == []

    def test_reap_summary_and_failure_exit(self, fake_env):
        from click.testing import CliRunner
        from pm_core.cli import cli
        bad = "pm-repo-ab12-review-pr-aaaa"
        fake_env["containers"] = [_info("pm-repo-ab12-impl-pr-aaaa"), _info(bad)]
        fake_env["fail"] = {bad}
        r = CliRunner().invoke(cli, ["container", "reap"])
        assert r.exit_code == 1
        assert "removed 1" in r.output and "failed 1" in r.output
        assert "FAILED" in r.output

    def test_retain_roundtrip(self, monkeypatch):
        from click.testing import CliRunner
        from pm_core.cli import cli
        monkeypatch.setattr(cm, "current_container_id",
                            lambda name: "cid1" if name == "pm-x-impl-pr-1" else "")
        r = CliRunner().invoke(cli, ["container", "retain", "pm-nope-impl-pr-2"])
        assert r.exit_code == 1 and "No container" in r.output
        assert not reaper.is_retained("pm-nope-impl-pr-2")
        r = CliRunner().invoke(cli, ["container", "retain", "pm-x-impl-pr-1"])
        assert r.exit_code == 0 and reaper.is_retained("pm-x-impl-pr-1", "cid1")
        assert not reaper.is_retained("pm-x-impl-pr-1", "cid2")
        r = CliRunner().invoke(cli, ["container", "retain", "--release", "pm-x-impl-pr-1"])
        assert r.exit_code == 0 and not reaper.is_retained("pm-x-impl-pr-1")

    def test_restart_refuses_live_owner(self, monkeypatch):
        from click.testing import CliRunner
        from pm_core.cli import cli
        monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: ["%4"])
        restarted = []
        monkeypatch.setattr(cm, "restart_container", restarted.append)
        r = CliRunner().invoke(cli, ["container", "restart", "pm-x-review-pr-1"])
        assert r.exit_code == 1 and "%4" in r.output and restarted == []

    def test_cleanup_continues_past_failure(self, monkeypatch):
        """`pm container cleanup` reports a stuck container instead of
        aborting the rest (remove_container now raises when it can't)."""
        from click.testing import CliRunner
        from pm_core.cli import cli
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k: _cp(
            out="pm-a-impl-pr-1\tUp\npm-a-review-pr-1\tUp\n"))
        removed = []

        def _rm(name):
            if "review" in name:
                raise cm.ContainerError("still present after 10 s")
            removed.append(name)
        monkeypatch.setattr(cm, "remove_container", _rm)
        r = CliRunner().invoke(cli, ["container", "cleanup"])
        assert r.exit_code == 1
        assert removed == ["pm-a-impl-pr-1"]
        assert "FAILED" in r.output and "Removed 1 container(s)." in r.output

    def test_cleanup_skips_non_pm_substring_matches(self, monkeypatch):
        """The runtime's name filter matches substrings: a user's "npm-cache"
        container must never be removed by `pm container cleanup`."""
        from click.testing import CliRunner
        from pm_core.cli import cli
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k: _cp(
            out="npm-cache\tUp\npm-a-impl-pr-1\tUp\n"))
        removed = []
        monkeypatch.setattr(cm, "remove_container", removed.append)
        r = CliRunner().invoke(cli, ["container", "cleanup"])
        assert r.exit_code == 0, r.output
        assert removed == ["pm-a-impl-pr-1"]


class TestListNamesPrefixGuard:
    def test_substring_matches_are_dropped(self, monkeypatch):
        calls = []

        def _rt(*a, **k):
            calls.append(a)
            return _cp(out="npm-cache\npm-a-impl-pr-1\nmy-pm-thing\n")
        monkeypatch.setattr(cm, "_run_runtime", _rt)
        assert cm.running_container_count() == 1
        assert "-a" not in calls[-1]  # running only
        assert cm.containers_for_pr("a", "pr-1") == {"pm-a-impl-pr-1"}
        removed = []
        monkeypatch.setattr(cm, "remove_container", removed.append)
        assert cm.cleanup_all_containers() == 1
        assert removed == ["pm-a-impl-pr-1"]

    def test_runtime_failure_is_unknown(self, monkeypatch):
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k: _cp(rc=1))
        assert cm.running_container_count() is None
        assert cm.containers_for_pr("a", "pr-1") is None
        assert cm.cleanup_all_containers() == 0
