"""Tests for the PR resource cleanup primitives."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from pm_core import container as container_mod
from pm_core import pane_registry, pr_cleanup, runtime_state


class TestCleanupPrContainers:
    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_legacy_prefix(self, mock_runtime, mock_remove):
        mock_runtime.return_value = MagicMock(
            returncode=0,
            stdout="pm-qa-pr-001-loop1-s0\npm-qa-pr-001-loop1-s1\n",
        )
        removed = container_mod.cleanup_pr_containers("pr-001")
        assert removed == ["pm-qa-pr-001-loop1-s0", "pm-qa-pr-001-loop1-s1"]
        assert mock_remove.call_count == 2

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_session_tagged_and_legacy_dedup(self, mock_runtime, mock_remove):
        # Two prefix queries — one for tagged, one for legacy. Same container
        # appears in both: dedup.
        mock_runtime.side_effect = [
            MagicMock(returncode=0, stdout="pm-mysess-qa-pr-001-l1-s0\n"),
            MagicMock(returncode=0, stdout="pm-mysess-qa-pr-001-l1-s0\npm-qa-pr-001-l2-s0\n"),
        ]
        removed = container_mod.cleanup_pr_containers("pr-001", session_tag="mysess")
        assert removed == ["pm-mysess-qa-pr-001-l1-s0", "pm-qa-pr-001-l2-s0"]
        assert mock_remove.call_count == 2

    @patch("pm_core.container.remove_container")
    @patch("pm_core.container._run_runtime")
    def test_no_containers(self, mock_runtime, mock_remove):
        mock_runtime.return_value = MagicMock(returncode=0, stdout="")
        removed = container_mod.cleanup_pr_containers("pr-001")
        assert removed == []
        mock_remove.assert_not_called()

    @patch("pm_core.container._run_runtime")
    def test_parallel_removal(self, mock_runtime):
        # Simulate four containers each taking 0.5s to remove. Sequential
        # would be ~2s; parallel must finish closer to 0.5s.
        names = [f"pm-qa-pr-001-l1-s{i}" for i in range(4)]
        mock_runtime.return_value = MagicMock(
            returncode=0, stdout="\n".join(names) + "\n")

        def slow_remove(name):
            time.sleep(0.5)

        with patch("pm_core.container.remove_container", side_effect=slow_remove):
            t0 = time.monotonic()
            removed = container_mod.cleanup_pr_containers("pr-001")
            elapsed = time.monotonic() - t0

        assert sorted(removed) == sorted(names)
        # Generous bound — sequential would be 2.0s; parallel ~0.5s.
        assert elapsed < 1.5, f"removal not parallel: {elapsed:.2f}s"


class TestUnregisterWindows:
    def test_removes_listed_windows(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pane_registry, "registry_dir", lambda: tmp_path)
        # Seed a registry with three windows
        pane_registry.register_pane("s", "winA", "%1", "claude", "x")
        pane_registry.register_pane("s", "winB", "%2", "claude", "x")
        pane_registry.register_pane("s", "winC", "%3", "claude", "x")

        removed = pane_registry.unregister_windows("s", ["winA", "winC", "missing"])
        assert sorted(removed) == ["winA", "winC"]

        data = pane_registry.load_registry("s")
        assert list(data.get("windows", {}).keys()) == ["winB"]


class TestCleanupPrResources:
    @patch("pm_core.pr_cleanup.tmux_mod")
    @patch("pm_core.pr_cleanup.pane_registry")
    @patch("pm_core.pr_cleanup.container_mod")
    @patch("pm_core.pr_cleanup.kill_pr_windows")
    def test_orchestration(self, mock_kill, mock_container, mock_registry, mock_tmux):
        mock_kill.return_value = ["pr-001", "qa-pr-001"]
        mock_container.cleanup_pr_containers.return_value = ["pm-qa-pr-001-l1-s0"]
        mock_tmux.list_windows.return_value = []
        mock_registry.load_registry.return_value = {"windows": {}}
        mock_registry.unregister_windows.return_value = ["pr-001"]

        pr = {"id": "pr-001"}
        summary = pr_cleanup.cleanup_pr_resources("pm-mysess", pr)

        assert summary["windows"] == ["pr-001", "qa-pr-001"]
        assert summary["containers"] == ["pm-qa-pr-001-l1-s0"]
        assert summary["registry_windows"] == ["pr-001"]
        # Session tag should strip the pm- prefix
        mock_container.cleanup_pr_containers.assert_called_once_with(
            "pr-001", session_tag="mysess")

    def test_clears_runtime_state_file(self, tmp_path, monkeypatch):
        # Reproducer for the stale-state bug: after cleanup, a fresh
        # set_action_state call must see no prior actions.
        monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: tmp_path)
        runtime_state.set_action_state("pr-001", "qa", "running",
                                       loop_id="abc")
        runtime_state.set_action_state("pr-001", "review-loop", "running",
                                       loop_id="def")
        assert runtime_state.runtime_path("pr-001").exists()

        with patch("pm_core.pr_cleanup.kill_pr_windows", return_value=[]), \
             patch("pm_core.pr_cleanup.container_mod") as mc, \
             patch("pm_core.pr_cleanup.pane_registry") as mr, \
             patch("pm_core.pr_cleanup.tmux_mod") as mt:
            mc.cleanup_pr_containers.return_value = []
            mr.load_registry.return_value = {"windows": {}}
            mr.unregister_windows.return_value = []
            mt.list_windows.return_value = []
            summary = pr_cleanup.cleanup_pr_resources(
                "pm-mysess", {"id": "pr-001"})

        assert summary["runtime_state"] is True
        assert not runtime_state.runtime_path("pr-001").exists()
        assert runtime_state.get_pr_actions("pr-001") == {}

    def test_format_summary_empty(self):
        empty = {"windows": [], "containers": [], "registry_windows": [],
                 "sockets": [], "runtime_state": False}
        assert pr_cleanup.format_summary(empty) == "nothing to clean"

    def test_format_summary_partial(self):
        s = {"windows": ["a", "b"], "containers": [], "registry_windows": ["c"],
             "sockets": [], "runtime_state": False}
        out = pr_cleanup.format_summary(s)
        assert "2 window" in out
        assert "1 registry" in out
