"""Tests for session registry functions in pm_core.claude_launcher."""

import json
from pathlib import Path

import pytest

from pm_core.claude_launcher import (
    load_session,
    save_session,
    clear_session,
    _parse_session_id,
    SESSION_REGISTRY,
)


@pytest.fixture
def tmp_pm_root(tmp_path):
    """Create a temporary PM root directory."""
    return tmp_path


class TestLoadSession:
    def test_returns_none_when_file_missing(self, tmp_pm_root):
        assert load_session(tmp_pm_root, "guide:no_project") is None

    def test_returns_none_when_key_missing(self, tmp_pm_root):
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text(json.dumps({"other:key": {"session_id": "abc123"}}))
        assert load_session(tmp_pm_root, "guide:no_project") is None

    def test_returns_session_id_when_exists(self, tmp_pm_root):
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text(json.dumps({
            "guide:no_project": {"session_id": "sess-abc123", "timestamp": "2024-01-01T00:00:00Z"}
        }))
        assert load_session(tmp_pm_root, "guide:no_project") == "sess-abc123"

    def test_returns_none_on_corrupted_json(self, tmp_pm_root):
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text("not valid json {{{")
        assert load_session(tmp_pm_root, "guide:no_project") is None

    def test_returns_none_when_entry_has_no_session_id(self, tmp_pm_root):
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text(json.dumps({
            "guide:no_project": {"timestamp": "2024-01-01T00:00:00Z"}  # no session_id
        }))
        assert load_session(tmp_pm_root, "guide:no_project") is None


class TestSaveSession:
    def test_creates_new_file_if_missing(self, tmp_pm_root):
        save_session(tmp_pm_root, "guide:no_project", "sess-new123")

        registry = tmp_pm_root / SESSION_REGISTRY
        assert registry.exists()
        data = json.loads(registry.read_text())
        assert data["guide:no_project"]["session_id"] == "sess-new123"
        assert "timestamp" in data["guide:no_project"]

    def test_adds_entry_to_existing_registry(self, tmp_pm_root):
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text(json.dumps({
            "existing:key": {"session_id": "existing-sess", "timestamp": "2024-01-01T00:00:00Z"}
        }))

        save_session(tmp_pm_root, "guide:no_project", "sess-new123")

        data = json.loads(registry.read_text())
        assert data["existing:key"]["session_id"] == "existing-sess"
        assert data["guide:no_project"]["session_id"] == "sess-new123"

    def test_overwrites_existing_entry(self, tmp_pm_root):
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text(json.dumps({
            "guide:no_project": {"session_id": "old-sess", "timestamp": "2024-01-01T00:00:00Z"}
        }))

        save_session(tmp_pm_root, "guide:no_project", "new-sess")

        data = json.loads(registry.read_text())
        assert data["guide:no_project"]["session_id"] == "new-sess"

    def test_timestamp_is_iso_format(self, tmp_pm_root):
        save_session(tmp_pm_root, "guide:no_project", "sess-123")

        registry = tmp_pm_root / SESSION_REGISTRY
        data = json.loads(registry.read_text())
        timestamp = data["guide:no_project"]["timestamp"]
        # Should be parseable as ISO format and contain timezone info
        assert "T" in timestamp
        assert "+" in timestamp or "Z" in timestamp


class TestClearSession:
    def test_removes_key_from_registry(self, tmp_pm_root):
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text(json.dumps({
            "guide:no_project": {"session_id": "sess-123", "timestamp": "2024-01-01T00:00:00Z"},
            "other:key": {"session_id": "other-sess", "timestamp": "2024-01-01T00:00:00Z"},
        }))

        clear_session(tmp_pm_root, "guide:no_project")

        data = json.loads(registry.read_text())
        assert "guide:no_project" not in data
        assert "other:key" in data

    def test_noop_when_registry_missing(self, tmp_pm_root):
        # Should not raise
        clear_session(tmp_pm_root, "guide:no_project")
        assert not (tmp_pm_root / SESSION_REGISTRY).exists()

    def test_noop_when_key_missing(self, tmp_pm_root):
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text(json.dumps({
            "other:key": {"session_id": "other-sess", "timestamp": "2024-01-01T00:00:00Z"},
        }))

        clear_session(tmp_pm_root, "guide:no_project")

        data = json.loads(registry.read_text())
        assert "other:key" in data

    def test_handles_corrupted_json(self, tmp_pm_root):
        registry = tmp_pm_root / SESSION_REGISTRY
        registry.write_text("not valid json")

        # Should not raise
        clear_session(tmp_pm_root, "guide:no_project")


class TestParseSessionId:
    def test_extracts_from_json_line(self):
        stderr = '{"type":"system","session_id":"sess-abc123","timestamp":1234567890}\n'
        assert _parse_session_id(stderr) == "sess-abc123"

    def test_returns_none_when_no_json(self):
        stderr = "Some regular output\nAnother line\n"
        assert _parse_session_id(stderr) is None

    def test_returns_none_when_no_session_id_field(self):
        stderr = '{"type":"system","timestamp":1234567890}\n'
        assert _parse_session_id(stderr) is None

    def test_handles_multiple_json_lines(self):
        stderr = (
            '{"type":"init","timestamp":1234567890}\n'
            '{"type":"system","session_id":"sess-abc123","timestamp":1234567891}\n'
            '{"type":"done","timestamp":1234567892}\n'
        )
        assert _parse_session_id(stderr) == "sess-abc123"

    def test_ignores_non_json_mixed_with_json(self):
        stderr = (
            "Starting claude...\n"
            '{"type":"system","session_id":"sess-abc123"}\n'
            "Done.\n"
        )
        assert _parse_session_id(stderr) == "sess-abc123"

    def test_handles_empty_string(self):
        assert _parse_session_id("") is None

    def test_handles_whitespace_only(self):
        assert _parse_session_id("   \n\n  \n") is None

    def test_returns_first_session_id_found(self):
        stderr = (
            '{"session_id":"first-sess"}\n'
            '{"session_id":"second-sess"}\n'
        )
        assert _parse_session_id(stderr) == "first-sess"
