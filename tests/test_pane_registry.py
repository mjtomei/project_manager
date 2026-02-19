"""Tests for pane registry I/O functions in pm_core.pane_registry."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.pane_registry import (
    _get_window_data,
    _iter_all_panes,
    load_registry,
    save_registry,
    register_pane,
    unregister_pane,
    kill_and_unregister,
    find_live_pane_by_role,
    _reconcile_registry,
)


@pytest.fixture
def registry_dir(tmp_path):
    """Patch registry_dir to use a tmp directory, return that directory."""
    with patch("pm_core.pane_registry.registry_dir", return_value=tmp_path):
        yield tmp_path


class TestLoadRegistry:
    def test_missing_file_returns_default(self, registry_dir):
        data = load_registry("test-session")
        assert data["session"] == "test-session"
        assert data["windows"] == {}
        assert data["generation"] == ""

    def test_loads_existing_file(self, registry_dir):
        registry_file = registry_dir / "test-session.json"
        content = {
            "session": "test-session",
            "windows": {
                "1": {
                    "panes": [{"id": "%1", "role": "tui", "order": 0, "cmd": "pm _tui"}],
                    "user_modified": False,
                },
            },
            "generation": "123",
        }
        registry_file.write_text(json.dumps(content))
        data = load_registry("test-session")
        assert "1" in data["windows"]
        assert len(data["windows"]["1"]["panes"]) == 1
        assert data["windows"]["1"]["panes"][0]["id"] == "%1"

    def test_corrupted_json_returns_default(self, registry_dir):
        registry_file = registry_dir / "test-session.json"
        registry_file.write_text("not valid json {{{")
        data = load_registry("test-session")
        assert data["session"] == "test-session"
        assert data["windows"] == {}

    def test_grouped_session_uses_base_name(self, registry_dir):
        registry_file = registry_dir / "test-session.json"
        content = {
            "session": "test-session",
            "windows": {
                "0": {
                    "panes": [{"id": "%5", "role": "claude", "order": 0, "cmd": "claude"}],
                    "user_modified": False,
                },
            },
        }
        registry_file.write_text(json.dumps(content))
        # Loading with grouped session name should find the base session file
        data = load_registry("test-session~2")
        assert len(data["windows"]["0"]["panes"]) == 1
        assert data["windows"]["0"]["panes"][0]["id"] == "%5"

    def test_old_format_migration(self, registry_dir):
        """Old flat format (panes at top level) is migrated to multi-window."""
        registry_file = registry_dir / "test-session.json"
        old_format = {
            "session": "test-session",
            "window": "2",
            "panes": [
                {"id": "%1", "role": "tui", "order": 0, "cmd": "pm _tui"},
                {"id": "%2", "role": "claude", "order": 1, "cmd": "claude"},
            ],
            "user_modified": True,
        }
        registry_file.write_text(json.dumps(old_format))
        data = load_registry("test-session")
        # Should be migrated to multi-window format
        assert "windows" in data
        assert "panes" not in data  # flat panes removed
        assert "2" in data["windows"]
        wdata = data["windows"]["2"]
        assert len(wdata["panes"]) == 2
        assert wdata["user_modified"] is True
        assert wdata["panes"][0]["id"] == "%1"


class TestSaveRegistry:
    def test_creates_file(self, registry_dir):
        data = {"session": "my-session", "windows": {}, "generation": ""}
        save_registry("my-session", data)
        file_path = registry_dir / "my-session.json"
        assert file_path.exists()
        saved = json.loads(file_path.read_text())
        assert saved == data

    def test_overwrites_existing(self, registry_dir):
        data1 = {"session": "s", "windows": {}, "generation": ""}
        save_registry("s", data1)
        data2 = {
            "session": "s",
            "windows": {"1": {"panes": [{"id": "%1"}], "user_modified": True}},
            "generation": "123",
        }
        save_registry("s", data2)
        saved = json.loads((registry_dir / "s.json").read_text())
        assert "1" in saved["windows"]
        assert len(saved["windows"]["1"]["panes"]) == 1


class TestLoadSaveRoundTrip:
    def test_round_trip(self, registry_dir):
        data = {
            "session": "rt-session",
            "windows": {
                "2": {
                    "panes": [
                        {"id": "%10", "role": "tui", "order": 0, "cmd": "pm _tui"},
                        {"id": "%11", "role": "claude", "order": 1, "cmd": "claude"},
                    ],
                    "user_modified": False,
                },
            },
            "generation": "456",
        }
        save_registry("rt-session", data)
        loaded = load_registry("rt-session")
        assert loaded == data

    def test_round_trip_empty_windows(self, registry_dir):
        data = {"session": "empty", "windows": {}, "generation": ""}
        save_registry("empty", data)
        loaded = load_registry("empty")
        assert loaded == data


class TestGetWindowData:
    def test_creates_entry_on_demand(self):
        data = {"windows": {}}
        wdata = _get_window_data(data, "0")
        assert wdata == {"panes": [], "user_modified": False}
        assert "0" in data["windows"]

    def test_returns_existing_entry(self):
        data = {"windows": {"0": {"panes": [{"id": "%1"}], "user_modified": True}}}
        wdata = _get_window_data(data, "0")
        assert wdata["user_modified"] is True
        assert len(wdata["panes"]) == 1

    def test_creates_windows_dict_if_missing(self):
        data = {}
        wdata = _get_window_data(data, "1")
        assert "windows" in data
        assert "1" in data["windows"]
        assert wdata["panes"] == []


class TestIterAllPanes:
    def test_yields_from_all_windows(self):
        data = {
            "windows": {
                "0": {"panes": [{"id": "%1", "role": "tui"}, {"id": "%2", "role": "claude"}]},
                "1": {"panes": [{"id": "%3", "role": "notes"}]},
            }
        }
        results = list(_iter_all_panes(data))
        assert len(results) == 3
        assert ("0", {"id": "%1", "role": "tui"}) in results
        assert ("0", {"id": "%2", "role": "claude"}) in results
        assert ("1", {"id": "%3", "role": "notes"}) in results

    def test_empty_windows(self):
        data = {"windows": {}}
        assert list(_iter_all_panes(data)) == []

    def test_no_windows_key(self):
        data = {}
        assert list(_iter_all_panes(data)) == []


class TestRegisterPane:
    def test_registers_first_pane(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        data = load_registry("sess")
        wdata = data["windows"]["0"]
        assert len(wdata["panes"]) == 1
        pane = wdata["panes"][0]
        assert pane["id"] == "%1"
        assert pane["role"] == "tui"
        assert pane["order"] == 0
        assert pane["cmd"] == "pm _tui"

    def test_registers_second_pane_increments_order(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        register_pane("sess", "0", "%2", "claude", "claude")
        data = load_registry("sess")
        wdata = data["windows"]["0"]
        assert len(wdata["panes"]) == 2
        assert wdata["panes"][0]["order"] == 0
        assert wdata["panes"][1]["order"] == 1

    def test_registers_in_different_windows(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        register_pane("sess", "1", "%2", "review", "pm review")
        data = load_registry("sess")
        assert len(data["windows"]["0"]["panes"]) == 1
        assert len(data["windows"]["1"]["panes"]) == 1
        assert data["windows"]["0"]["panes"][0]["role"] == "tui"
        assert data["windows"]["1"]["panes"][0]["role"] == "review"

    def test_registers_multiple_panes(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        register_pane("sess", "0", "%2", "claude", "claude")
        register_pane("sess", "0", "%3", "notes", "pm notes")
        data = load_registry("sess")
        wdata = data["windows"]["0"]
        assert len(wdata["panes"]) == 3
        roles = [p["role"] for p in wdata["panes"]]
        assert roles == ["tui", "claude", "notes"]


class TestUnregisterPane:
    def test_removes_existing_pane(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        register_pane("sess", "0", "%2", "claude", "claude")
        unregister_pane("sess", "%1")
        data = load_registry("sess")
        wdata = data["windows"]["0"]
        assert len(wdata["panes"]) == 1
        assert wdata["panes"][0]["id"] == "%2"

    def test_noop_for_nonexistent_pane(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        unregister_pane("sess", "%99")
        data = load_registry("sess")
        assert len(data["windows"]["0"]["panes"]) == 1

    def test_removes_across_windows(self, registry_dir):
        """unregister_pane searches all windows."""
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        register_pane("sess", "1", "%2", "claude", "claude")
        unregister_pane("sess", "%2")
        data = load_registry("sess")
        assert len(data["windows"]["0"]["panes"]) == 1
        assert len(data["windows"]["1"]["panes"]) == 0

    def test_removes_all_panes(self, registry_dir):
        register_pane("sess", "0", "%1", "tui", "pm _tui")
        unregister_pane("sess", "%1")
        data = load_registry("sess")
        assert len(data["windows"]["0"]["panes"]) == 0


class TestKillAndUnregister:
    @patch("pm_core.pane_registry.unregister_pane")
    @patch("subprocess.run")
    @patch("pm_core.tmux._tmux_cmd", return_value=["tmux", "kill-pane", "-t", "%5"])
    def test_kills_and_unregisters(self, mock_cmd, mock_run, mock_unreg):
        kill_and_unregister("sess", "%5")
        mock_run.assert_called_once_with(["tmux", "kill-pane", "-t", "%5"], check=False)
        mock_unreg.assert_called_once_with("sess", "%5")


class TestFindLivePaneByRole:
    @patch("pm_core.pane_registry.load_registry")
    @patch("pm_core.tmux.get_pane_indices")
    def test_returns_pane_id_when_alive(self, mock_indices, mock_load):
        mock_load.return_value = {
            "session": "sess",
            "windows": {
                "0": {
                    "panes": [
                        {"id": "%1", "role": "tui"},
                        {"id": "%2", "role": "claude"},
                    ],
                },
            },
        }
        mock_indices.return_value = [("%1", 0), ("%2", 1)]
        result = find_live_pane_by_role("sess", "claude")
        assert result == "%2"

    @patch("pm_core.pane_registry.load_registry")
    @patch("pm_core.tmux.get_pane_indices")
    def test_returns_none_when_dead(self, mock_indices, mock_load):
        mock_load.return_value = {
            "session": "sess",
            "windows": {
                "0": {"panes": [{"id": "%1", "role": "tui"}]},
            },
        }
        # Pane %1 not in live panes
        mock_indices.return_value = [("%5", 0)]
        result = find_live_pane_by_role("sess", "tui")
        assert result is None

    @patch("pm_core.pane_registry.load_registry")
    def test_returns_none_when_role_not_in_registry(self, mock_load):
        mock_load.return_value = {
            "session": "sess",
            "windows": {
                "0": {"panes": [{"id": "%1", "role": "tui"}]},
            },
        }
        result = find_live_pane_by_role("sess", "nonexistent")
        assert result is None

    @patch("pm_core.pane_registry.load_registry")
    def test_returns_none_when_no_panes(self, mock_load):
        mock_load.return_value = {
            "session": "sess",
            "windows": {},
        }
        result = find_live_pane_by_role("sess", "tui")
        assert result is None

    @patch("pm_core.pane_registry.load_registry")
    @patch("pm_core.tmux.get_pane_indices")
    def test_window_scoping(self, mock_indices, mock_load):
        """When window is specified, only search that window."""
        mock_load.return_value = {
            "session": "sess",
            "windows": {
                "0": {"panes": [{"id": "%1", "role": "claude"}]},
                "1": {"panes": [{"id": "%2", "role": "claude"}]},
            },
        }
        mock_indices.return_value = [("%2", 0)]
        # Search only window "1"
        result = find_live_pane_by_role("sess", "claude", window="1")
        assert result == "%2"
        # Should only query window "1"
        mock_indices.assert_called_once_with("sess", "1")

    @patch("pm_core.pane_registry.load_registry")
    @patch("pm_core.tmux.get_pane_indices")
    def test_searches_all_windows_without_scope(self, mock_indices, mock_load):
        """Without window scope, searches all windows."""
        mock_load.return_value = {
            "session": "sess",
            "windows": {
                "0": {"panes": [{"id": "%1", "role": "tui"}]},
                "1": {"panes": [{"id": "%2", "role": "claude"}]},
            },
        }
        # Window 0 has %1 alive, window 1 has %2 alive
        def get_indices(session, window):
            if window == "0":
                return [("%1", 0)]
            return [("%2", 0)]
        mock_indices.side_effect = get_indices
        result = find_live_pane_by_role("sess", "claude")
        assert result == "%2"


class TestReconcileRegistry:
    @patch("pm_core.pane_registry.save_registry")
    @patch("pm_core.pane_registry.load_registry")
    @patch("pm_core.tmux.get_pane_indices")
    def test_removes_dead_panes(self, mock_indices, mock_load, mock_save):
        mock_load.return_value = {
            "session": "sess",
            "windows": {
                "0": {
                    "panes": [
                        {"id": "%1", "role": "tui"},
                        {"id": "%2", "role": "claude"},
                    ],
                    "user_modified": False,
                },
            },
        }
        # Only %1 is alive
        mock_indices.return_value = [("%1", 0)]
        removed = _reconcile_registry("sess", "0")
        assert removed == ["%2"]

    @patch("pm_core.pane_registry.save_registry")
    @patch("pm_core.pane_registry.load_registry")
    @patch("pm_core.tmux.get_pane_indices")
    def test_no_removal_when_all_alive(self, mock_indices, mock_load, mock_save):
        mock_load.return_value = {
            "session": "sess",
            "windows": {
                "0": {
                    "panes": [{"id": "%1", "role": "tui"}],
                    "user_modified": False,
                },
            },
        }
        mock_indices.return_value = [("%1", 0)]
        removed = _reconcile_registry("sess", "0")
        assert removed == []
        mock_save.assert_not_called()

    @patch("pm_core.pane_registry.save_registry")
    @patch("pm_core.pane_registry.load_registry")
    @patch("pm_core.tmux.get_pane_indices")
    def test_skips_when_no_live_panes_but_registry_has_panes(self, mock_indices, mock_load, mock_save):
        """Don't wipe registry if window doesn't exist (no live panes returned)."""
        mock_load.return_value = {
            "session": "sess",
            "windows": {
                "0": {
                    "panes": [{"id": "%1", "role": "tui"}],
                    "user_modified": False,
                },
            },
        }
        mock_indices.return_value = []
        removed = _reconcile_registry("sess", "0")
        assert removed == []
        mock_save.assert_not_called()
