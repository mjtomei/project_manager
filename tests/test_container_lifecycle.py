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


class TestPidsUsage:
    @pytest.mark.parametrize("stats_sep,inspect_sep", [
        ("\t", "\t"), ("  ", "\t"), ("\t", "  "), ("  ", "  "),
    ])
    def test_runtime_whitespace(self, monkeypatch, stats_sep, inspect_sep):
        name = "pm-repo-ab12-review-pr-aaaa"
        monkeypatch.setattr(reaper, "list_containers", lambda: [_info(name)])
        def runtime(command, *args, **kwargs):
            if command == "stats":
                return _cp(out=f"{name}{stats_sep}2041\n")
            return _cp(out=f"/{name}{inspect_sep}2048\n")
        monkeypatch.setattr(cm, "_run_runtime", runtime)
        assert cm.pids_usage() == {name: (2041, 2048)}
        assert cm.pids_pressure() == [(name, 2041, 2048)]


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
# Reaper inventory / decisions
# ---------------------------------------------------------------------------

class TestReaperInventory:
    @pytest.mark.parametrize("separator", ["\t", "  "])
    def test_inspect_accepts_podman_tabwriter_output(self, monkeypatch, separator):
        name = "pm-repo-ab12-impl-pr-1a2b3c"
        labels = ('{"pm.managed":"1","pm.session_tag":"repo-ab12",'
                  '"pm.pr_id":"pr-1a2b3c","pm.project_root":"/path with spaces"}')
        row = separator.join([name, "a" * 64, "true", "running", labels])
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: _cp(out=row + "\n"))
        infos = reaper._inspect([name], timeout=60)
        assert len(infos) == 1
        assert infos[0].name == name
        assert infos[0].id == "a" * 64
        assert infos[0].running
        assert infos[0].session_tag == "repo-ab12"
        assert infos[0].pr_id == "pr-1a2b3c"
        assert infos[0].project_root == "/path with spaces"

    @pytest.mark.parametrize("identifier", ["a" * 64, "aaaaaaaaaaaa",
                                             "/pm-review-pr-aaaa"])
    def test_owner_lookup_resolves_runtime_identifier(self, monkeypatch, identifier):
        name = "pm-review-pr-aaaa"
        row = (f"/{name}\t{'a' * 64}\ttrue\trunning\t"
               '{"pm.tmux_socket":"/custom/owner.sock"}\n')
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: _cp(out=row))
        owner = MagicMock(return_value=(["%1"], False))
        monkeypatch.setattr(reaper, "_owner_panes", owner)
        assert reaper.live_owner_panes(identifier) == ["%1"]
        info = owner.call_args.args[0]
        assert info.name == name
        assert info.id == "a" * 64
        assert info.tmux_socket == "/custom/owner.sock"

    @pytest.mark.parametrize("labels", ["null", "{}"])
    def test_inspect_accepts_unlabeled_legacy_container(self, monkeypatch, labels):
        name = "pm-review-pr-aaaa"
        row = f"/{name}\tid\ttrue\trunning\t{labels}\n"
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: _cp(out=row))
        infos = reaper._inspect([name], timeout=60)
        assert len(infos) == 1
        assert infos[0].pr_id == "pr-aaaa"

    @pytest.mark.parametrize("rc,output", [
        (1, ""),
        (1, "partial"),
        (0, "partial"),
        (0, "malformed"),
        (0, "bad-json"),
        (0, "non-object-labels"),
    ])
    def test_incomplete_inventory_preserves_records_until_retry(
            self, fake_env, monkeypatch, rc, output):
        kept = "pm-repo-ab12-review-pr-aaaa"
        orphan = "pm-repo-ab12-impl-pr-bbbb"
        fake_env["containers"] = [_info(kept), _info(orphan)]
        reaper.retain(kept, container_id="id-" + kept)
        TestReaperOwnership._backdate_marker(kept)
        reaper._record(reaper.Outcome(failures={kept: "previous timeout"}),
                       Scope(), "manual")
        before = reaper.last_state()
        rows = [f"{name}\tid-{name}\ttrue\trunning\t{{}}\n"
                for name in (kept, orphan)]
        outputs = {
            "": "",
            "partial": rows[1],
            "malformed": rows[0] + orphan + "\n",
            "bad-json": rows[0] + rows[1].replace("{}", "{broken"),
            "non-object-labels": rows[0] + rows[1].replace("{}", "[]"),
        }
        response = _cp(rc, outputs[output], "inspect failed" if rc else "")
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: response)
        monkeypatch.setattr(reaper, "list_containers",
                            lambda: reaper._inspect([kept, orphan], timeout=60))
        proxies = MagicMock(return_value=([], True))
        monkeypatch.setattr(reaper, "_release_unused_proxies", proxies)

        out = reaper.reconcile(reason="manual")
        assert out.error
        assert not fake_env["removed"]
        assert reaper.is_retained(kept, "id-" + kept)
        assert reaper.last_state() == before
        proxies.assert_not_called()

        response = _cp(out="".join(rows))
        out = reaper.reconcile(reason="manual")
        assert not out.error
        assert out.removed == [orphan]
        assert reaper.is_retained(kept, "id-" + kept)
        assert kept in reaper.pending_failures()  # retention defers the failed cleanup


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


class TestReaperOwnership:
    def test_before_count_reuses_full_inventory(self, fake_env, monkeypatch):
        fake_env["containers"] = [
            _info("pm-repo-ab12-review-pr-aaaa"),
            _info("pm-repo-ab12-review-pr-bbbb"),
            _info("pm-repo-ab12-review-pr-cccc", running=False),
        ]
        count = MagicMock(return_value=0)
        monkeypatch.setattr(cm, "running_container_count", count)
        scope = Scope(pr_id="pr-aaaa")
        preview = reaper.reconcile(scope, dry_run=True)
        assert preview.running_before == 2  # global, not just scoped decisions
        count.assert_not_called()
        outcome = reaper.reconcile(scope)
        assert outcome.running_before == 2
        count.assert_called_once_with()  # fresh post-removal count

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

    @staticmethod
    def _backdate_marker(name, seconds=60):
        import json
        f = next(path for path, rec in reaper._retention_records() if rec["name"] == name)
        rec = json.loads(f.read_text())
        rec["at"] -= seconds
        f.write_text(json.dumps(rec))

    def test_retention_does_not_carry_over_to_a_replacement(self, fake_env):
        """A marker set on one container must not retain a later container
        launched under the same name, and is pruned once its container is
        gone (full passes)."""
        name = "pm-repo-ab12-review-pr-aaaa"
        reaper.retain(name, "discussion", container_id="old-id")
        self._backdate_marker(name)
        fake_env["containers"] = [_info(name, id="new-id")]
        out = reaper.reconcile(reason="manual")
        assert out.removed == [name]
        assert not reaper.is_retained(name)  # pruned with its container

    def test_retention_marker_pruned_when_container_gone(self, fake_env):
        kept, gone = "pm-repo-ab12-impl-pr-aaaa", "pm-repo-ab12-impl-pr-bbbb"
        fake_env["containers"] = [_info(kept)]
        reaper.retain(kept, container_id="id-" + kept)
        reaper.retain(gone, container_id="id-" + gone)
        self._backdate_marker(gone)
        reaper.reconcile(Scope(pr_id="pr-aaaa"), reason="manual")
        assert reaper.is_retained(gone)  # scoped passes don't prune
        reaper.reconcile(reason="manual")
        assert reaper.retained_names() == [kept]

    def test_marker_written_during_pass_is_not_pruned(self, fake_env, monkeypatch):
        """A retain of a container launched after the pass listed containers
        must survive that pass's marker pruning."""
        late = "pm-repo-ab12-review-pr-cccc"
        orig = reaper.plan

        def _plan(scope=None):
            out = orig(scope)
            reaper.retain(late, container_id="id-" + late)  # concurrent retain
            return out
        monkeypatch.setattr(reaper, "plan", _plan)
        reaper.reconcile(reason="manual")
        assert reaper.is_retained(late, "id-" + late)

    def test_include_retained_is_still_a_full_pass(self, fake_env):
        """--include-retained is a retention policy, not a scope filter."""
        name = "pm-repo-ab12-review-pr-aaaa"
        fake_env["containers"] = [_info(name)]
        reaper.retain(name, "discussion", container_id="id-" + name)
        self._backdate_marker(name)
        lock = cm.container_state_dir() / "locks" / f"container-{name}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("")
        old = time.time() - 7200
        import os
        os.utime(lock, (old, old))

        out = reaper.reconcile(Scope(include_retained=True), reason="manual")

        assert out.removed == [name]
        assert not reaper.is_retained(name, "id-" + name), "marker outlived its container"
        assert not lock.exists(), "a removed container's old lock file is prunable"

    def test_unprunable_marker_does_not_discard_the_pass(self, fake_env, monkeypatch):
        """A marker that cannot be unlinked must not erase the pass outcome.

        Pruning runs after removals but before the outcome is persisted, so an
        escaping OSError would lose the removals and their failures.
        """
        name, gone = "pm-repo-ab12-review-pr-aaaa", "pm-repo-ab12-review-pr-bbbb"
        fake_env["containers"] = [_info(name)]
        reaper.retain(gone)  # name-keyed marker for a container that is gone
        self._backdate_marker(gone)
        real_unlink = Path.unlink

        def unlink(self, *args, **kwargs):
            if self.name == gone:
                raise PermissionError("denied")
            return real_unlink(self, *args, **kwargs)
        monkeypatch.setattr(Path, "unlink", unlink)

        out = reaper.reconcile(reason="manual")

        assert not out.error
        assert out.removed == [name]
        assert reaper.last_state().get("removed") == [name]

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

    def test_recheck_keeps_unknown_owner(self, fake_env, monkeypatch):
        info = _info("pm-repo-ab12-review-pr-aaaa")
        monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **kw: ([], True))
        decision = reaper.Decision(info, "remove", "no owning pane")
        removed, reason = reaper._remove_checked(decision, Scope())
        assert not removed and "unknown" in reason
        assert fake_env["removed"] == []

    @pytest.mark.parametrize("failure", ["inspect", "tmux"])
    def test_live_owner_lookup_refuses_unknown(self, monkeypatch, failure):
        name = "pm-repo-ab12-review-pr-aaaa"
        monkeypatch.setattr(reaper, "_inspect",
                            lambda *a, **kw: None if failure == "inspect" else [_info(name)])
        monkeypatch.setattr(reaper, "_owner_panes", lambda *a, **kw: ([], True))
        with pytest.raises(cm.ContainerError, match="ownership unknown"):
            reaper.live_owner_panes(name)

    def test_recheck_under_lock_skips_replaced_container(self, fake_env, monkeypatch):
        """A relaunch between plan and removal swapped in a new container of
        the same name (no pane attached yet): removal by name must not hit it."""
        name = "pm-repo-ab12-review-pr-aaaa"
        fake_env["containers"] = [_info(name)]
        monkeypatch.setattr(cm, "current_container_id", lambda n: "id-replacement")
        out = reaper.reconcile(reason="manual")
        assert out.removed == [] and fake_env["removed"] == []
        assert "replaced by a newer launch" in out.decisions[0].reason

    def test_id_recheck_timeout_fails_only_that_container(self, fake_env, monkeypatch):
        """A runtime timeout while re-checking one container's id must not
        abort the pass (and lose the record of the other removals)."""
        import subprocess
        slow, other = "pm-repo-ab12-review-pr-aaaa", "pm-repo-ab12-impl-pr-bbbb"
        fake_env["containers"] = [_info(slow), _info(other)]

        def _cid(name):
            if name == slow:
                raise subprocess.TimeoutExpired("podman inspect", 10)
            return "id-" + name
        monkeypatch.setattr(cm, "current_container_id", _cid)
        out = reaper.reconcile(reason="manual")
        assert out.removed == [other] and not out.error
        assert slow in out.failures and slow in reaper.pending_failures()

    @pytest.mark.parametrize("present", [False, True])
    def test_full_pass_retires_only_vanished_proxy_failures(
            self, fake_env, tmp_path, monkeypatch, present):
        """A proxy that no longer exists cannot be retried; keep real ones."""
        from pm_core import push_proxy
        key = "push proxy tag/pr-aaaa"
        reaper._record(reaper.Outcome(failures={key: "runtime inventory unavailable"}),
                       Scope(), "manual")
        assert key in reaper.pending_failures()
        proxy_dir = tmp_path / "proxy"
        if present:
            proxy_dir.mkdir()
        monkeypatch.setattr(push_proxy, "_shared_sock_dir_path",
                            lambda tag, pr: str(proxy_dir))
        out = reaper.reconcile(reason="manual")
        assert not out.error
        assert (key in reaper.pending_failures()) is present

    def test_proxy_failure_actionable_tracks_its_target(self, fake_env):
        """An unshared release is retryable only while its record survives."""
        releases = cm.container_state_dir() / "proxy-releases"
        releases.mkdir(parents=True)
        key = "push proxy unshared abc123"
        assert reaper._proxy_failure_actionable(key) is False
        (releases / "abc123.json").write_text("{}")
        assert reaper._proxy_failure_actionable(key) is True
        # Shapes the helper does not understand stay visible.
        assert reaper._proxy_failure_actionable("push proxy sweep") is True

    def test_worker_exception_fails_only_that_container(self, fake_env, monkeypatch):
        """A crashed removal worker must not discard the pass's other results."""
        broken, other = "pm-repo-ab12-review-pr-aaaa", "pm-repo-ab12-impl-pr-bbbb"
        fake_env["containers"] = [_info(broken), _info(other)]
        original = reaper._remove_checked

        def _checked(decision, scope):
            if decision.info.name == broken:
                raise RuntimeError("worker crashed")
            return original(decision, scope)

        monkeypatch.setattr(reaper, "_remove_checked", _checked)
        out = reaper.reconcile(reason="manual")
        assert out.removed == [other]
        assert not out.error
        assert "worker crashed" in out.failures[broken]
        assert broken in reaper.pending_failures()

    @pytest.mark.parametrize("released", [False, True])
    def test_unknown_identity_never_removes_by_name(self, fake_env, monkeypatch, released):
        info = _info("pm-repo-ab12-review-pr-aaaa")
        fake_env["containers"] = [info]
        monkeypatch.setattr(cm, "current_container_id", lambda name: None)
        decision = reaper.Decision(info, "remove", "released", released=released)
        removed, reason = reaper._remove_checked(decision, Scope())
        assert not removed and "unknown" in reason
        assert fake_env["removed"] == []

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

    @pytest.mark.parametrize("replacement", [False, True])
    @pytest.mark.parametrize("protection", ["live", "retained"])
    def test_automatic_failure_tracks_allocation_identity(
            self, fake_env, replacement, protection):
        name = "pm-repo-ab12-review-pr-aaaa"
        original = _info(name)
        fake_env["containers"] = [original]
        fake_env["fail"] = {name}
        assert name in reaper.reconcile(reason="periodic").failures

        current = _info(name, id="replacement") if replacement else original
        fake_env["containers"] = [current]
        fake_env["fail"] = set()
        if protection == "live":
            fake_env["panes"] = _Panes([f"podman exec -it {name} worker"])
        else:
            reaper.retain(name, container_id=current.id)
        assert not reaper.reconcile(reason="periodic").removed
        assert (name in reaper.pending_failures()) is not replacement
        if not replacement:
            failure = reaper.pending_failures()[name]
            assert failure["id"] == original.id
            assert not failure.get("owner_release")

    def test_owner_release_ignores_own_panes_but_not_retention(self, fake_env):
        a = "pm-repo-ab12-qa-pr-aaaa-L-s1"
        b = "pm-repo-ab12-qa-pr-aaaa-L-s2"
        fake_env["containers"] = [_info(a, created=time.time()), _info(b)]
        fake_env["panes"] = _Panes([f"podman exec -it {a} x", f"podman exec -it {b} x"])
        reaper.retain(b)
        out = reaper.release_containers([a, b], owner_release=True,
                                        expected_ids={n: "id-" + n for n in (a, b)},
                                        expected_generations={a: "", b: ""})
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
        out = reaper.release_containers([name], owner_release=True,
                                  expected_ids={name: "id-" + name},
                                  expected_generations={name: ""})
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
        reaper.release_containers([name], owner_release=True,
                                  expected_ids={name: "id-" + name},
                                  expected_generations={name: ""})
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

    def test_live_owner_panes_searches_the_labeled_tmux_server(self, monkeypatch, tmp_path):
        """Reuse/restart guards must find a pane on the server the container
        was launched from, even when it isn't this process's server."""
        name = "pm-repo-ab12-review-pr-aaaa"
        sock = str(tmp_path / "other-tmux.sock")
        Path(sock).touch()
        labels = ('{"pm.managed":"1","pm.kind":"review",'
                  f'"pm.tmux_socket":"{sock}"}}')
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k: MagicMock(
            returncode=0, stdout=f"{name}\tcid1\ttrue\trunning\t{labels}\n"))
        monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
        monkeypatch.delenv("TMUX", raising=False)

        def _query(server):
            if server.socket_file == sock:
                return reaper._PaneSnapshot(
                    panes=[("%7", "pm-repo-ab12", f"podman exec -it {name} claude")])
            return reaper._PaneSnapshot(panes=[])
        monkeypatch.setattr(reaper, "_query_server", _query)
        assert reaper.live_owner_panes(name) == ["%7"]


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
        monkeypatch.setattr(cm, "remove_container", lambda name, **kw: removed.append(name))
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
        rt = _Runtime(exec=_exec, restart=_restart, inspect=lambda *a:
                      _cp(out='"2026-10-26T00:00:00Z"' if "{{json .State.StartedAt}}" in a else "cid"))
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

    @pytest.mark.parametrize("kind,stderr", [("pids", "sh: Cannot fork"),
                                             ("incomplete", "")])
    def test_unknown_owner_blocks_recovery(self, monkeypatch, no_claude_json, kind, stderr):
        rt = _Runtime(exec=lambda *a: _cp(126 if stderr else 1, err=stderr))
        removed = self._setup(monkeypatch, rt)

        def unknown(*args):
            raise cm.ContainerError("ownership unknown: tmux server unreachable")

        monkeypatch.setattr(reaper, "live_owner_panes", unknown)
        with pytest.raises(cm.ContainerError, match="ownership unknown") as exc:
            cm._ensure_reusable("c", Path("/w"), None, session_tag=None, pr_id=None)
        if kind == "pids":
            assert exc.value.kind == "pids" and stderr in str(exc.value)
        assert not rt.ran("restart") and removed == []

    def test_restart_timeout_does_not_claim_removal(self, monkeypatch):
        monkeypatch.setattr(cm, "current_container_id", lambda _: "cid")
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k:
                            _cp(out='"2026-10-26T00:00:00Z"' if a[0] == "inspect" else ""))

        def _timeout(name, **kwargs):
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
        monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
        monkeypatch.setattr(cm, "image_exists", lambda *a: True)
        monkeypatch.setattr(cm, "keyring_pressure", lambda *a, **k: None)
        monkeypatch.setattr(cm, "_SETUP_TIMEOUT", 0.3)
        monkeypatch.setattr(cm, "_SETUP_POLL_INTERVAL", 0.05)
        removed = []
        monkeypatch.setattr(cm, "remove_container", lambda name, **kw: removed.append(name))
        return removed

    def test_proxy_lock_timeout_aborts_before_start(self, monkeypatch, no_claude_json):
        import contextlib
        from pm_core import push_proxy
        rt = _Runtime()
        self._patch(monkeypatch, rt)
        monkeypatch.setattr(cm, "proxy_lock", lambda *a, **kw: contextlib.nullcontext(False))
        start = MagicMock(return_value="/unused/push.sock")
        monkeypatch.setattr(push_proxy, "start_push_proxy", start)
        with pytest.raises(cm.ContainerLaunchError, match="proxy lock"):
            cm.create_container("pm-t-impl-pr-1", cm.ContainerConfig(), Path("/w"),
                                session_tag="t", pr_id="pr-1", allowed_push_branch="branch")
        start.assert_not_called()
        assert not rt.ran("run")

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
        # The fixture exposes a stopped prior ID but no valid attempt metadata
        # for the failed run; only the identity-pinned stopped allocation is removed.
        assert removed.count("pm-t-impl-pr-1") == 1

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
        assert "release_on_exit" in cmd and "abc123" in cmd
        assert "rm -f pm-t-review-pr-1" not in cmd


class TestFileLock:
    def test_unwritable_lock_is_not_acquired(self, monkeypatch):
        monkeypatch.setattr(cm.os, "open", MagicMock(side_effect=PermissionError("read-only state")))
        with cm._file_lock("unavailable", timeout=0) as acquired:
            assert acquired is False

    def test_launch_aborts_when_lock_cannot_be_created(self, monkeypatch):
        monkeypatch.setattr(cm.os, "open", MagicMock(side_effect=PermissionError("read-only state")))
        create = MagicMock()
        monkeypatch.setattr(cm, "_ensure_reusable", lambda *a, **kw: None)
        monkeypatch.setattr(cm, "_create_fresh", create)
        with pytest.raises(cm.ContainerLaunchError, match="launch lock"):
            cm.create_container("pm-t-impl-pr-1", cm.ContainerConfig(), Path("/w"))
        create.assert_not_called()

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

class TestSafeDiscard:
    @pytest.mark.parametrize("case", ["unknown-id", "unknown-owner", "owned", "retained", "busy", "replaced"])
    def test_keeps_unproven_or_owned_container(self, monkeypatch, case):
        import contextlib
        name = "pm-repo-ab12-review-pr-aaaa"
        monkeypatch.setattr(cm, "launch_lock", lambda *a, **kw: contextlib.nullcontext(case != "busy"))
        monkeypatch.setattr(cm, "current_container_id", lambda n: None if case == "unknown-id" else "cid")
        monkeypatch.setattr(reaper, "is_retained", lambda *a: case == "retained")
        def owners(*args):
            if case == "unknown-owner":
                raise cm.ContainerError("ownership unknown")
            return ["%1"] if case == "owned" else []
        monkeypatch.setattr(reaper, "live_owner_panes", owners)
        remove = MagicMock()
        monkeypatch.setattr(cm, "remove_container", remove)
        assert not cm.discard_unowned_container(name, container_id="old" if case == "replaced" else "cid")
        remove.assert_not_called()

    def test_removes_exact_id_under_name_lock(self, monkeypatch):
        import contextlib
        from pm_core import push_proxy
        name = "pm-repo-ab12-review-pr-aaaa"
        held = []
        @contextlib.contextmanager
        def lock(n, **kwargs):
            assert n == name
            held.append(n)
            yield True
            held.pop()
        monkeypatch.setattr(cm, "launch_lock", lock)
        monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
        def owners(*args):
            assert held == [name]
            return []
        monkeypatch.setattr(reaper, "live_owner_panes", owners)
        removed = []
        def remove(identifier):
            assert held == [name]
            removed.append(identifier)
        monkeypatch.setattr(cm, "remove_container", remove)
        stopped = MagicMock()
        monkeypatch.setattr(push_proxy, "stop_push_proxy", stopped)
        assert cm.discard_unowned_container(name)
        assert removed == ["cid"]
        stopped.assert_called_once_with(name)

    def test_remove_failure_is_best_effort_and_keeps_proxy(self, monkeypatch):
        from pm_core import push_proxy
        name = "pm-repo-ab12-review-pr-aaaa"
        monkeypatch.setattr(cm, "current_container_id", lambda n: "cid")
        monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
        monkeypatch.setattr(cm, "remove_container", MagicMock(side_effect=cm.ContainerError("still present")))
        stopped = MagicMock()
        monkeypatch.setattr(push_proxy, "stop_push_proxy", stopped)
        assert not cm.discard_unowned_container(name)
        stopped.assert_not_called()


class TestProxyRelease:
    @pytest.mark.parametrize("local", [False, True])
    def test_last_live_user_never_excluded_from_inventory(self, monkeypatch, local):
        from pm_core import push_proxy as pp
        name, key = "pm-repo-ab12-review-pr-aaaa", "repo-ab12\0pr-aaaa"
        monkeypatch.setattr(pp, "_container_to_proxy_key", {name: key} if local else {})
        monkeypatch.setattr(pp, "_proxy_refs", {key: {name}} if local else {})
        monkeypatch.setattr(pp, "_active_proxies", {})
        monkeypatch.setattr(cm, "containers_for_pr", lambda *a: {name})
        kill = MagicMock()
        monkeypatch.setattr(pp, "_kill_proxy_socket", kill)
        pp.stop_push_proxy(name)
        kill.assert_not_called()

    @pytest.mark.parametrize("stderr", ["permission denied", "cannot connect to Podman socket", ""])
    def test_inspect_error_does_not_claim_removed(self, monkeypatch, stderr):
        from pm_core import push_proxy
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: _cp(125, err=stderr))
        stopped = MagicMock()
        monkeypatch.setattr(push_proxy, "stop_push_proxy", stopped)
        with pytest.raises(cm.ContainerError, match="Cannot inspect mounted push proxy"):
            cm.remove_container("pm-repo-ab12-review-pr-aaaa")
        stopped.assert_not_called()

    @pytest.mark.parametrize("stderr", [
        "Error: No such container: pm-repo-ab12-review-pr-aaaa",
        "Error: No such object: pm-repo-ab12-review-pr-aaaa",
        'Error: no container with name or ID "pm-repo-ab12-review-pr-aaaa" found: no such container',
    ])
    def test_confirmed_absence_releases_proxy(self, monkeypatch, stderr):
        from pm_core import push_proxy
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: _cp(1, err=stderr))
        stopped = MagicMock()
        monkeypatch.setattr(push_proxy, "stop_push_proxy", stopped)
        name = "pm-repo-ab12-review-pr-aaaa"
        cm.remove_container(name)
        stopped.assert_called_once_with(name)

    def test_failed_removal_does_not_release_proxy(self, monkeypatch):
        from pm_core import push_proxy
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **kw: _cp(out='[{"Config":{"Labels":{}}}]'))
        ticks = iter([0, 11])
        monkeypatch.setattr(cm.time, "monotonic", lambda: next(ticks))
        stopped = MagicMock()
        monkeypatch.setattr(push_proxy, "stop_push_proxy", stopped)
        with pytest.raises(cm.ContainerError, match="still present"):
            cm.remove_container("pm-repo-ab12-review-pr-aaaa")
        stopped.assert_not_called()

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

    def test_local_shared_proxy_kept_when_runtime_unknown(self, monkeypatch):
        from pm_core import push_proxy as pp
        name, key = "pm-repo-ab12-review-pr-aaaa", "repo-ab12\0pr-aaaa"
        monkeypatch.setattr(pp, "_container_to_proxy_key", {name: key})
        monkeypatch.setattr(pp, "_proxy_refs", {key: {name}})
        monkeypatch.setattr(pp, "_active_proxies", {key: "/unused/push.sock"})
        monkeypatch.setattr(cm, "containers_for_pr", lambda *a: None)
        kill = MagicMock()
        monkeypatch.setattr(pp, "_kill_proxy_socket", kill)
        pp.stop_push_proxy(name)
        kill.assert_not_called()
        assert key in pp._active_proxies

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

    def test_reused_proxy_without_owner_file_is_not_attributed(self, monkeypatch, tmp_path):
        import json
        from pm_core import push_proxy
        sock_dir = tmp_path / "proxy"
        sock_dir.mkdir()
        (sock_dir / "push.sock").write_text("")
        monkeypatch.setattr(push_proxy, "_shared_sock_dir", lambda t, p: str(sock_dir))
        monkeypatch.setattr(push_proxy, "proxy_is_alive", lambda s: True)
        push_proxy.start_push_proxy("pm-t-impl-pr-1", "/w", "b",
                                    session_tag="t", pr_id="pr-1")
        assert not (sock_dir / push_proxy._OWNER_FILE).exists()
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
        monkeypatch.setattr(cm, "pids_usage", lambda: {})
        restarted = []
        monkeypatch.setattr(cm, "restart_container", restarted.append)
        r = CliRunner().invoke(cli, ["container", "restart", "pm-x-review-pr-1"])
        assert r.exit_code == 1 and "%4" in r.output and restarted == []

    @pytest.mark.parametrize("force", [False, True])
    def test_restart_checks_owner_after_acquiring_launch_lock(self, monkeypatch, force):
        from contextlib import contextmanager
        from click.testing import CliRunner
        from pm_core.cli import cli
        owners = []

        @contextmanager
        def lock(name, **kwargs):
            # A concurrent launch attaches its pane before we acquire its lock.
            owners.append("%7")
            yield True

        monkeypatch.setattr(cm, "launch_lock", lock)
        monkeypatch.setattr(cm, "pids_usage", lambda: {})
        monkeypatch.setattr(cm, "current_container_id", lambda n: "cid1")
        monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: list(owners))
        restarted = []
        monkeypatch.setattr(cm, "restart_container",
                            lambda n, **kw: restarted.append((n, kw.get("container_id"))))
        name = "pm-x-review-pr-1"
        args = ["container", "restart", name] + (["--force"] if force else [])
        r = CliRunner().invoke(cli, args)
        assert r.exit_code == (0 if force else 1), r.output
        # The restart pins the allocation the ownership check just saw.
        assert restarted == ([(name, "cid1")] if force else [])
        if not force:
            assert "%7" in r.output

    @pytest.mark.parametrize("force", [False, True])
    def test_restart_unknown_owner_requires_force(self, monkeypatch, force):
        from click.testing import CliRunner
        from pm_core.cli import cli

        def unknown(*args):
            raise cm.ContainerError("ownership unknown: runtime unavailable")

        monkeypatch.setattr(reaper, "live_owner_panes", unknown)
        monkeypatch.setattr(cm, "pids_usage", lambda: {})
        monkeypatch.setattr(cm, "current_container_id", lambda n: "cid1")
        restarted = []
        monkeypatch.setattr(cm, "restart_container",
                            lambda n, **kw: restarted.append((n, kw.get("container_id"))))
        name = "pm-x-review-pr-1"
        r = CliRunner().invoke(cli, ["container", "restart", name]
                               + (["--force"] if force else []))
        assert r.exit_code == (0 if force else 1), r.output
        assert restarted == ([(name, "cid1")] if force else [])
        if not force:
            assert "ownership unknown" in r.output and "--force" in r.output

    def test_restart_unowned_reports_pids(self, monkeypatch):
        from click.testing import CliRunner
        from pm_core.cli import cli
        name = "pm-x-review-pr-1"
        monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
        monkeypatch.setattr(cm, "current_container_id", lambda n: "cid1")
        usage = iter([{name: (2041, 2048)}, {name: (3, 2048)}])
        monkeypatch.setattr(cm, "pids_usage", lambda: next(usage))
        held = []
        monkeypatch.setattr(cm, "restart_container",
                            lambda n, **kw: held.append(cm.launch_in_progress(n)))
        r = CliRunner().invoke(cli, ["container", "restart", name])
        assert r.exit_code == 0, r.output
        assert held == [True]  # restarted under its launch lock
        assert "2041/2048 → 3/2048" in r.output

    def test_restart_reports_missing_host_setup_as_success(self, monkeypatch):
        """A restart that keeps the filesystem but lacks the completion marker
        is a success, not a failed recovery.

        Every container created before ``SETUP_COMPLETE_SENTINEL`` existed
        lacks one, and ``pm container restart`` is the remedy the PID/keyring
        messages print, so reporting failure here would contradict them.
        """
        from click.testing import CliRunner
        from pm_core.cli import cli
        name = "pm-x-review-pr-1"
        monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
        monkeypatch.setattr(cm, "current_container_id", lambda n: "cid1")
        usage = iter([{name: (2041, 2048)}, {name: (3, 2048)}])
        monkeypatch.setattr(cm, "pids_usage", lambda: next(usage))

        def restart(n, **kw):
            raise cm.launch_error(n, "incomplete",
                                  "setup markers missing after restart",
                                  stage="restart")
        monkeypatch.setattr(cm, "restart_container", restart)
        r = CliRunner().invoke(cli, ["container", "restart", name])
        assert r.exit_code == 0, r.output
        assert "2041/2048 → 3/2048" in r.output
        assert "next launch finishes" in r.output

    def test_restart_refuses_unverifiable_allocation(self, monkeypatch):
        """An unanswered identity probe must not restart an unchecked name."""
        from click.testing import CliRunner
        from pm_core.cli import cli
        monkeypatch.setattr(reaper, "live_owner_panes", lambda *a: [])
        monkeypatch.setattr(cm, "pids_usage", lambda: {})
        monkeypatch.setattr(cm, "current_container_id", lambda n: None)
        restarted = []
        monkeypatch.setattr(cm, "restart_container", lambda n, **kw: restarted.append(n))
        r = CliRunner().invoke(cli, ["container", "restart", "pm-x-review-pr-1"])
        assert r.exit_code == 1 and "retry" in r.output
        assert restarted == []

    def test_session_cleanup_scopes_to_current_tag(self, fake_env, monkeypatch):
        from click.testing import CliRunner
        from pm_core.cli import cli
        from pm_core.cli import helpers
        monkeypatch.setattr(helpers, "_get_pm_session", lambda: "pm-repo-ab12~2")
        fake_env["containers"] = [_info("pm-repo-ab12-impl-pr-aaaa"),
                                  _info("pm-other-cd34-impl-pr-aaaa")]
        r = CliRunner().invoke(cli, ["session", "cleanup"])
        assert r.exit_code == 0, r.output
        assert "session repo-ab12" in r.output
        assert fake_env["removed"] == ["pm-repo-ab12-impl-pr-aaaa"]

    @pytest.mark.parametrize("separator", ["\t", "  "])
    def test_cleanup_continues_past_failure(self, monkeypatch, separator):
        """`pm container cleanup` reports a stuck container instead of
        aborting the rest (remove_container now raises when it can't)."""
        from click.testing import CliRunner
        from pm_core.cli import cli
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k: _cp(
            out=f"pm-a-impl-pr-1{separator}Up\npm-a-review-pr-1{separator}Up\n"))
        removed = []

        def _rm(name, *, container_id):
            if "review" in name:
                raise cm.ContainerError("still present after 10 s")
            removed.append(name)
        monkeypatch.setattr(cm, "remove_container", _rm)
        r = CliRunner().invoke(cli, ["container", "cleanup"])
        assert r.exit_code == 1
        assert removed == ["pm-a-impl-pr-1"]
        assert "FAILED" in r.output and "Removed 1 container(s)." in r.output

    @pytest.mark.parametrize("error", ["missing", "timeout"])
    def test_cleanup_reports_unavailable_runtime(self, monkeypatch, error):
        """A missing or hung runtime is a diagnostic, not a traceback."""
        import subprocess as _subprocess
        from click.testing import CliRunner
        from pm_core.cli import cli

        def _rt(*a, **k):
            if error == "timeout":
                raise _subprocess.TimeoutExpired(["podman", *a], k.get("timeout"))
            raise FileNotFoundError("podman")
        monkeypatch.setattr(cm, "_run_runtime", _rt)
        r = CliRunner().invoke(cli, ["container", "cleanup"])
        assert r.exit_code == 1
        assert "Failed to list containers" in r.output

    def test_cleanup_skips_non_pm_substring_matches(self, monkeypatch):
        """The runtime's name filter matches substrings: a user's "npm-cache"
        container must never be removed by `pm container cleanup`."""
        from click.testing import CliRunner
        from pm_core.cli import cli
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k: _cp(
            out="npm-cache\tUp\npm-a-impl-pr-1\tUp\n"))
        removed = []
        monkeypatch.setattr(cm, "remove_container", lambda name, **kw: removed.append(name))
        r = CliRunner().invoke(cli, ["container", "cleanup"])
        assert r.exit_code == 0, r.output
        assert removed == ["pm-a-impl-pr-1"]


class TestListNamesPrefixGuard:
    def test_substring_matches_are_dropped(self, monkeypatch):
        calls = []

        def _rt(*a, **k):
            calls.append(a)
            if a[0] == "inspect":
                return _cp(out='/pm-a-impl-pr-1\tcid\ttrue\trunning\t{}\n')
            if f"label={cm.LABEL_MANAGED}=1" in a:
                return _cp()  # this fixture contains only unlabeled legacy names
            return _cp(out="npm-cache\npm-a-impl-pr-1\nmy-pm-thing\n")
        monkeypatch.setattr(cm, "_run_runtime", _rt)
        assert cm.running_container_count() == 1
        assert any(f"label={cm.LABEL_MANAGED}=1" in call for call in calls)
        assert cm.containers_for_pr("a", "pr-1") == {"pm-a-impl-pr-1"}
        removed = []
        monkeypatch.setattr(cm, "remove_container", lambda name, **kw: removed.append(name))
        assert cm.cleanup_all_containers() == 1
        assert removed == ["pm-a-impl-pr-1"]

    def test_runtime_failure_is_unknown(self, monkeypatch):
        monkeypatch.setattr(cm, "_run_runtime", lambda *a, **k: _cp(rc=1))
        assert cm.running_container_count() is None
        assert cm.containers_for_pr("a", "pr-1") is None
        assert cm.cleanup_all_containers() == 0


class TestScenarioContainerReensure:
    """QA resume re-ensures a scenario container the reaper may have taken."""

    def _setup(self, tmp_path):
        from pm_core import qa_loop
        st = qa_loop.QALoopState(pr_id="pr-aaaa")
        st.loop_id, st.session_tag = "L", "t"
        clone = tmp_path / "s1" / "clone"
        clone.mkdir(parents=True)
        sc = qa_loop.QAScenario(index=1, title="s1", focus="",
                                container_name="pm-t-qa-pr-aaaa-L-s1",
                                worktree_path=str(clone))
        st.scenarios = [sc]
        return qa_loop, st, sc

    def test_failure_recorded_then_cleared_on_recovery(self, tmp_path, monkeypatch):
        qa_loop, st, sc = self._setup(tmp_path)
        monkeypatch.setattr(cm, "load_container_config", lambda: MagicMock())
        calls = []

        def _create(**kw):
            calls.append(kw)
            if len(calls) == 1:
                raise cm.launch_error(kw["name"], "keyring", "disk quota exceeded key")
            return "cid"
        monkeypatch.setattr(cm, "create_qa_container", _create)
        assert qa_loop._ensure_scenario_container(sc, st, {"branch": "b"}) is False
        assert qa_loop._is_launch_failure(st, 1) and 1 not in st.scenario_verdicts
        assert qa_loop._ensure_scenario_container(sc, st, {"branch": "b"}) is True
        assert not qa_loop._is_launch_failure(st, 1)
        assert calls[-1]["loop_id"] == "L" and calls[-1]["scenario"] == 1
        assert calls[-1]["scratch_path"] == Path(sc.worktree_path).parent / "scratch"


class TestLockFilePrune:
    def test_prunes_only_old_files_of_gone_containers(self, monkeypatch):
        import os
        lock_dir = cm.container_state_dir() / "locks"
        lock_dir.mkdir(parents=True)
        old = time.time() - reaper._LOCK_FILE_MAX_AGE - 10
        paths = {}
        for n in ("gone-old", "gone-new", "alive-old"):
            p = lock_dir / f"container-pm-{n}.lock"
            p.touch()
            if n.endswith("old"):
                os.utime(p, (old, old))
            paths[n] = p
        held = lock_dir / "container-pm-held-old.lock"
        with cm.launch_lock("pm-held-old", timeout=0) as got:
            assert got
            os.utime(held, (old, old))
            reaper._prune_lock_files({"pm-alive-old"})
        assert not paths["gone-old"].exists()
        assert paths["gone-new"].exists()  # a launch may still be starting
        assert paths["alive-old"].exists()
        assert held.exists()  # in use right now
