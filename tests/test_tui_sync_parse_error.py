"""Tests for ProjectYamlParseError handling in store.load and TUI sync."""

import asyncio
import types
from unittest.mock import patch, MagicMock

import pytest

from pm_core import store
from pm_core.tui.sync import background_sync


class TestStoreLoadParseError:
    """store.load raises ProjectYamlParseError on invalid YAML."""

    def test_invalid_yaml_raises_parse_error(self, tmp_path):
        yaml_file = tmp_path / "project.yaml"
        yaml_file.write_text(":\n  - :\n  bad: [unterminated")

        with pytest.raises(store.ProjectYamlParseError, match="not valid YAML"):
            store.load(tmp_path)


class TestBackgroundSyncParseError:
    """background_sync catches ProjectYamlParseError and leaves app unchanged."""

    def test_corrupt_yaml_skips_sync(self):
        app = types.SimpleNamespace(
            _root="/original/root",
            _data={"original": True},
            _current_guide_step=None,
        )
        original_root = app._root
        original_data = app._data.copy()

        with patch.object(
            store,
            "find_project_root",
            return_value="/some/root",
        ), patch.object(
            store,
            "load",
            side_effect=store.ProjectYamlParseError("corrupt"),
        ), patch(
            "pm_core.tui.frame_capture.load_capture_config",
        ), patch("pm_core.tui.sync._log") as mock_log:
            asyncio.run(background_sync(app))

        # app._data and app._root unchanged
        assert app._root == original_root
        assert app._data == original_data

        # Warning was logged
        mock_log.warning.assert_called_once()
        assert "Skipping sync" in mock_log.warning.call_args[0][0]


class TestKillMergedPrWindows:
    """_kill_merged_pr_windows must run full cleanup, not just kill windows."""

    def test_invokes_cleanup_pr_resources(self):
        from pm_core.tui import sync as sync_mod

        pr = {"id": "pr-abc", "branch": "feat/x"}
        app = types.SimpleNamespace(
            _session_name="pm-test",
            _data={"prs": [pr]},
        )

        with patch("pm_core.tmux.session_exists", return_value=True), \
             patch("pm_core.pr_cleanup.cleanup_pr_resources",
                   return_value={"windows": ["x"], "containers": ["c1", "c2"],
                                 "registry_windows": [], "sockets": [],
                                 "runtime_state": True}) as mock_cleanup:
            sync_mod._kill_merged_pr_windows(app, {"pr-abc"})

        mock_cleanup.assert_called_once_with("pm-test", pr)


class TestLoadStateParseError:
    """app._load_state catches ProjectYamlParseError and keeps previous state."""

    def test_corrupt_yaml_keeps_previous_data(self):
        """_load_state should log a warning and keep app._data unchanged on corrupt YAML."""
        from pm_core.tui.app import ProjectManagerApp

        previous_data = {"project": {"name": "test"}, "prs": [{"id": "pr-001"}]}

        with patch.object(
            store,
            "find_project_root",
            return_value="/some/root",
        ), patch.object(
            store,
            "load",
            side_effect=store.ProjectYamlParseError("corrupt"),
        ), patch("pm_core.tui.app._log") as mock_log:
            app = types.SimpleNamespace(
                _root="/some/root",
                _data=previous_data.copy(),
                _plans_visible=False,
                _qa_visible=False,
                _update_display=MagicMock(),
                _show_normal_view=MagicMock(),
            )
            # Call _load_state as unbound method with our namespace
            ProjectManagerApp._load_state(app)

        # app._data should be unchanged (not wiped to {})
        assert app._data == previous_data

        # Warning was logged
        mock_log.warning.assert_called_once()
        assert "corrupt" in str(mock_log.warning.call_args[0][1])
