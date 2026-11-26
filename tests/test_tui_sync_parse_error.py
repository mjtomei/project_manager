"""Tests for ProjectYamlParseError handling in store.load and TUI sync."""

import asyncio
import types
from unittest.mock import patch, MagicMock

import pytest

from pm_core import store
from pm_core.tui.sync import background_sync
from pm_core.tui.sync import guide as sync_guide


class TestStoreLoadParseError:
    """store.load raises ProjectYamlParseError on invalid YAML."""

    def test_invalid_yaml_raises_parse_error(self, tmp_path):
        yaml_file = tmp_path / "project.yaml"
        yaml_file.write_text(":\n  - :\n  bad: [unterminated")

        with pytest.raises(store.ProjectYamlParseError, match="not valid YAML"):
            store.load(tmp_path)


_UNLOADABLE = [
    store.ProjectYamlParseError("corrupt"),
    # A clean merge whose plans do not validate (S44): the background
    # sync timer re-raised it and the TUI exited.
    store.PlanValidationError("corrupt: Plan plan-child references "
                              "non-existent parent 'plan-base'"),
]


class TestBackgroundSyncParseError:
    """background_sync skips an unloadable project.yaml and leaves app unchanged."""

    @pytest.mark.parametrize("error", _UNLOADABLE,
                             ids=lambda e: type(e).__name__)
    def test_corrupt_yaml_skips_sync(self, error):
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
            side_effect=error,
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
    """app._load_state keeps previous state on an unloadable project.yaml."""

    @pytest.mark.parametrize("error", _UNLOADABLE,
                             ids=lambda e: type(e).__name__)
    def test_corrupt_yaml_keeps_previous_data(self, error):
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
            side_effect=error,
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


class TestMissingProjectFileKeepsRoot:
    """A checkout or rebase briefly unlinks project.yaml (S44).

    While the project's pm dir still exists, neither the background sync
    nor a state reload may drop the root: the QA resume scan stops adopting
    orphaned runs while ``app._root`` is None.
    """

    def test_background_sync_skips_while_pm_dir_exists(self, tmp_path):
        app = types.SimpleNamespace(
            _root=tmp_path, _data={"prs": [{"id": "pr-001"}]},
            _current_guide_step=None)
        with patch.object(store, "find_project_root",
                          side_effect=FileNotFoundError("No project.yaml found")), \
             patch("pm_core.tui.frame_capture.load_capture_config"), \
             patch("pm_core.tui.sync._log") as mock_log:
            asyncio.run(background_sync(app))
        assert app._root == tmp_path
        assert app._data == {"prs": [{"id": "pr-001"}]}
        assert "Skipping sync" in mock_log.warning.call_args[0][0]

    def test_background_sync_skip_names_the_missing_file(self, tmp_path):
        """The cwd lookup's "cd into your repo" advice does not fit a TUI
        whose project file is briefly gone: name the missing path (S45)."""
        app = types.SimpleNamespace(
            _root=tmp_path, _data={"prs": [{"id": "pr-001"}]},
            _current_guide_step=None)
        with patch.object(store, "find_project_root",
                          side_effect=FileNotFoundError(
                              "No project.yaml found. Either cd into your repo, "
                              "use 'pm -C /path/to/pm-dir', or set PM_PROJECT")), \
             patch("pm_core.tui.frame_capture.load_capture_config"), \
             patch("pm_core.tui.sync._log") as mock_log:
            asyncio.run(background_sync(app))
        reason = str(mock_log.warning.call_args[0][1])
        assert reason == ("[Errno 2] No such file or directory: "
                          f"'{tmp_path / 'project.yaml'}'")

    def test_background_sync_without_a_root_still_resets(self, tmp_path):
        app = types.SimpleNamespace(
            _root=tmp_path / "gone", _data={"prs": [{"id": "pr-001"}]},
            _current_guide_step="no_project")
        with patch.object(store, "find_project_root",
                          side_effect=FileNotFoundError("No project.yaml found")), \
             patch("pm_core.tui.frame_capture.load_capture_config"), \
             patch.object(sync_guide, "detect_state",
                          return_value=("no_project", None)):
            asyncio.run(background_sync(app))
        assert app._root is None
        assert app._data == {}

    def test_load_state_keeps_previous_data_while_pm_dir_exists(self, tmp_path):
        from pm_core.tui.app import ProjectManagerApp

        previous = {"project": {"name": "test"}, "prs": [{"id": "pr-001"}]}
        app = types.SimpleNamespace(
            _root=tmp_path, _data=dict(previous),
            _plans_visible=False, _qa_visible=False,
            _update_display=MagicMock(), _show_normal_view=MagicMock())
        with patch.object(store, "load",
                          side_effect=FileNotFoundError(
                              f"[Errno 2] No such file or directory: "
                              f"'{tmp_path}/project.yaml'")):
            ProjectManagerApp._load_state(app)
        assert app._root == tmp_path
        assert app._data == previous
        app._show_normal_view.assert_called_once()
