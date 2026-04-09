"""Tests for pm_core.memory_governor."""

import json
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pm_core.memory_governor import (
    parse_memory,
    infer_container_type,
    load_stats,
    save_stats,
    record_sample,
    project_memory,
    check_launch,
    check_single_container_fits,
    get_stop_idle_policy,
    format_memory_status,
    capture_and_record,
    get_history_size,
)


# ---------------------------------------------------------------------------
# parse_memory
# ---------------------------------------------------------------------------

class TestParseMemory:
    def test_gigabytes(self):
        assert parse_memory("8g") == 8192
        assert parse_memory("8G") == 8192
        assert parse_memory("8gb") == 8192
        assert parse_memory("8GiB") == 8192

    def test_megabytes(self):
        assert parse_memory("500m") == 500
        assert parse_memory("500MB") == 500
        assert parse_memory("500MiB") == 500

    def test_fractional(self):
        assert parse_memory("1.5g") == 1536
        assert parse_memory("1.5GiB") == 1536

    def test_kilobytes(self):
        assert parse_memory("1024k") == 1

    def test_terabytes(self):
        assert parse_memory("1t") == 1024 * 1024

    def test_whitespace(self):
        assert parse_memory("  8g  ") == 8192
        assert parse_memory("8 g") == 8192

    def test_invalid(self):
        with pytest.raises(ValueError):
            parse_memory("not_a_number")
        with pytest.raises(ValueError):
            parse_memory("")

    def test_min_1mb(self):
        # Very small values round up to at least 1 MB
        assert parse_memory("1k") >= 1


# ---------------------------------------------------------------------------
# infer_container_type
# ---------------------------------------------------------------------------

class TestInferContainerType:
    def test_impl(self):
        assert infer_container_type("pm-impl") == "impl"
        assert infer_container_type("pm-repo-abc123-impl") == "impl"

    def test_review(self):
        assert infer_container_type("pm-review-pr-abc") == "review"
        assert infer_container_type("pm-repo-abc123-review-pr-abc") == "review"

    def test_qa_scenario(self):
        assert infer_container_type("pm-qa-pr-abc-loop123-s0") == "qa_scenario"
        assert infer_container_type("pm-repo-abc123-qa-pr-abc-loop123-s3") == "qa_scenario"

    def test_qa_planner(self):
        assert infer_container_type("pm-qa-planner") == "qa_planner"
        assert infer_container_type("pm-repo-abc123-qa-planner") == "qa_planner"

    def test_unknown(self):
        assert infer_container_type("pm-watcher") is None
        assert infer_container_type("not-a-pm-container") is None


# ---------------------------------------------------------------------------
# Stats persistence
# ---------------------------------------------------------------------------

class TestStats:
    def test_load_missing_file(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path):
            stats = load_stats()
            assert stats == {}

    def test_save_and_load(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path):
            data = {"impl": {"samples": [{"memory_mb": 4200, "age_minutes": 30}]}}
            save_stats(data)
            loaded = load_stats()
            assert loaded == data

    def test_corrupt_file(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path):
            (tmp_path / "container-stats.json").write_text("not valid json{{{")
            stats = load_stats()
            assert stats == {}

    def test_record_sample_creates_entry(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path):
            record_sample("qa_scenario", 5100, 12.5)
            stats = load_stats()
            assert "qa_scenario" in stats
            samples = stats["qa_scenario"]["samples"]
            assert len(samples) == 1
            assert samples[0]["memory_mb"] == 5100
            assert samples[0]["age_minutes"] == 12.5

    def test_record_sample_trims_to_history_size(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path), \
             patch("pm_core.memory_governor.get_history_size", return_value=3):
            for i in range(5):
                record_sample("impl", 4000 + i * 100, 30.0)
            stats = load_stats()
            samples = stats["impl"]["samples"]
            assert len(samples) == 3
            # Should have the last 3 samples
            assert samples[0]["memory_mb"] == 4200
            assert samples[2]["memory_mb"] == 4400


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

class TestProjection:
    def test_with_samples(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path):
            record_sample("qa_scenario", 5000, 10.0)
            record_sample("qa_scenario", 5200, 12.0)
            projected = project_memory("qa_scenario")
            assert projected == 5100  # average of 5000 and 5200

    def test_single_sample_used(self, tmp_path):
        """Even one sample should be used instead of the default."""
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path):
            record_sample("impl", 3500, 60.0)
            projected = project_memory("impl")
            assert projected == 3500

    def test_no_samples_uses_default_projection(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path), \
             patch("pm_core.memory_governor.get_global_setting_value") as mock_setting:
            def _setting(name, default=""):
                if name == "container-system-memory-default-projection":
                    return "6g"
                return default
            mock_setting.side_effect = _setting
            projected = project_memory("review")
            assert projected == 6144  # 6 GiB

    def test_no_samples_no_default_uses_memory_limit(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path), \
             patch("pm_core.memory_governor.get_global_setting_value",
                   return_value=""):
            mock_config = MagicMock()
            mock_config.memory_limit = "8g"
            with patch("pm_core.container.load_container_config",
                       return_value=mock_config):
                projected = project_memory("review")
                assert projected == 8192


# ---------------------------------------------------------------------------
# Gate check
# ---------------------------------------------------------------------------

class TestCheckLaunch:
    def test_no_target_always_allows(self):
        with patch("pm_core.memory_governor.get_memory_target", return_value=None):
            allowed, reason = check_launch("impl")
            assert allowed is True
            assert reason == ""

    def test_within_budget(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=48 * 1024), \
             patch("pm_core.memory_governor.get_current_used_mb",
                   return_value=30 * 1024), \
             patch("pm_core.memory_governor.project_memory",
                   return_value=8 * 1024):
            allowed, reason = check_launch("impl")
            assert allowed is True

    def test_exceeds_budget(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=48 * 1024), \
             patch("pm_core.memory_governor.get_current_used_mb",
                   return_value=44 * 1024), \
             patch("pm_core.memory_governor.project_memory",
                   return_value=8 * 1024):
            allowed, reason = check_launch("impl")
            assert allowed is False
            assert "Memory gate" in reason

    def test_multiple_count(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=48 * 1024), \
             patch("pm_core.memory_governor.get_current_used_mb",
                   return_value=10 * 1024), \
             patch("pm_core.memory_governor.project_memory",
                   return_value=5 * 1024):
            # 10G + 3*5G = 25G <= 48G
            allowed, _ = check_launch("qa_scenario", count=3)
            assert allowed is True
            # 10G + 10*5G = 60G > 48G
            allowed, _ = check_launch("qa_scenario", count=10)
            assert allowed is False

    def test_measurement_failure_allows(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=48 * 1024), \
             patch("pm_core.memory_governor.get_current_used_mb",
                   return_value=None):
            allowed, _ = check_launch("impl")
            assert allowed is True


class TestCheckSingleFits:
    def test_projection_exceeds_target(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=8 * 1024), \
             patch("pm_core.memory_governor.project_memory",
                   return_value=16 * 1024):
            fits, reason = check_single_container_fits("impl")
            assert fits is False
            assert "exceeds" in reason

    def test_projection_within_target(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=48 * 1024), \
             patch("pm_core.memory_governor.project_memory",
                   return_value=8 * 1024):
            fits, _ = check_single_container_fits("impl")
            assert fits is True


# ---------------------------------------------------------------------------
# Stop-on-idle policy
# ---------------------------------------------------------------------------

class TestStopIdlePolicy:
    def test_defaults(self):
        with patch("pm_core.memory_governor.get_global_setting_value") as mock:
            # Return the default by passing it through
            mock.side_effect = lambda name, default: default
            assert get_stop_idle_policy("qa_scenario") is True   # default on
            assert get_stop_idle_policy("qa_planner") is True    # default on
            assert get_stop_idle_policy("impl") is False          # default off
            assert get_stop_idle_policy("review") is False        # default off

    def test_override_on(self):
        with patch("pm_core.memory_governor.get_global_setting_value",
                   return_value="on"):
            assert get_stop_idle_policy("impl") is True

    def test_override_off(self):
        with patch("pm_core.memory_governor.get_global_setting_value",
                   return_value="off"):
            assert get_stop_idle_policy("qa_scenario") is False


# ---------------------------------------------------------------------------
# Format memory status
# ---------------------------------------------------------------------------

class TestFormatMemoryStatus:
    def test_no_target(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=None):
            assert format_memory_status() == ""

    def test_pm_scope(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=48 * 1024), \
             patch("pm_core.memory_governor.get_current_used_mb",
                   return_value=34 * 1024), \
             patch("pm_core.memory_governor.get_global_setting_value",
                   return_value="pm"):
            result = format_memory_status()
            assert "34G" in result
            assert "48G" in result
            assert "(pm)" in result

    def test_system_scope(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=56 * 1024), \
             patch("pm_core.memory_governor.get_current_used_mb",
                   return_value=52 * 1024), \
             patch("pm_core.memory_governor.get_global_setting_value",
                   return_value="system"):
            result = format_memory_status()
            assert "52G" in result
            assert "56G" in result
            assert "(sys)" in result


# ---------------------------------------------------------------------------
# capture_and_record integration
# ---------------------------------------------------------------------------

class TestCaptureAndRecord:
    def test_unknown_type_skips(self):
        with patch("pm_core.memory_governor.infer_container_type",
                   return_value=None), \
             patch("pm_core.memory_governor.record_sample") as mock_record:
            capture_and_record("unknown-container")
            mock_record.assert_not_called()

    def test_docker_failure_skips(self):
        with patch("pm_core.memory_governor.infer_container_type",
                   return_value="impl"), \
             patch("pm_core.memory_governor.capture_container_memory",
                   return_value=None), \
             patch("pm_core.memory_governor.record_sample") as mock_record:
            capture_and_record("pm-impl")
            mock_record.assert_not_called()

    def test_successful_capture(self):
        with patch("pm_core.memory_governor.infer_container_type",
                   return_value="impl"), \
             patch("pm_core.memory_governor.capture_container_memory",
                   return_value=4200), \
             patch("pm_core.memory_governor.get_container_age_minutes",
                   return_value=45.0), \
             patch("pm_core.memory_governor.record_sample") as mock_record:
            capture_and_record("pm-impl")
            mock_record.assert_called_once_with("impl", 4200, 45.0)

    def test_record_sample_integration(self, tmp_path):
        with patch("pm_core.memory_governor.infer_container_type",
                   return_value="impl"), \
             patch("pm_core.memory_governor.capture_container_memory",
                   return_value=5325), \
             patch("pm_core.memory_governor.get_container_age_minutes",
                   return_value=45.0), \
             patch("pm_core.memory_governor.pm_home",
                   return_value=tmp_path):
            capture_and_record("pm-impl")
            stats = load_stats()
            assert "impl" in stats
            samples = stats["impl"]["samples"]
            assert len(samples) == 1
            assert samples[0]["memory_mb"] == 5325
            assert samples[0]["age_minutes"] == 45.0
            assert "recorded_at" in samples[0]
