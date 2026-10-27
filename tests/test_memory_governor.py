"""Tests for pm_core.memory_governor."""

from unittest.mock import patch, MagicMock

import pytest

from pm_core import memory_governor as mg
from pm_core.memory_governor import (
    parse_memory,
    parse_runtime_memory,
    infer_container_type,
    load_stats,
    save_stats,
    record_sample,
    project_memory,
    check_single_container_fits,
    get_stop_idle_policy,
    format_memory_status,
    capture_and_record,
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

    def test_signoff_and_qa_debug(self):
        assert infer_container_type("pm-repo-abc123-signoff-pr-abc") == "signoff"
        assert infer_container_type("pm-qa-debug-instr-1-dbg2") == "qa_debug"

    def test_impl_with_pr_id(self):
        assert infer_container_type("pm-impl-pr-001") == "impl"
        assert infer_container_type("pm-repo-abc123-impl-pr-eb2dbfc") == "impl"
        assert infer_container_type("pm-repo-abc123-impl-pr-eb2dbfc-2") == "impl"

    def test_session_tag_words_do_not_decide_the_type(self):
        """Regression: the session tag comes from the project name, so a
        project called e.g. impl-tools or my-signoff-bot used to put every
        container's samples under the wrong type."""
        assert infer_container_type("pm-impl-tools-ab12-review-pr-1a2b") == "review"
        assert infer_container_type("pm-my-signoff-bot-ab12-impl-pr-1a2b") == "impl"
        assert infer_container_type("pm-review-ui-ab12-signoff-pr-1a2b") == "signoff"
        assert infer_container_type(
            "pm-impl-tools-ab12-qa-pr-1a2b-0123abcd-s2") == "qa_scenario"
        assert infer_container_type("pm-qa-lab-ab12-impl-pr-1a2b") == "impl"

    def test_unknown(self):
        assert infer_container_type("pm-watcher") is None
        assert infer_container_type("not-a-pm-container") is None
        assert infer_container_type("pm-review-ui-ab12-notes") is None


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
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path), \
             patch("pm_core.launch_queue.pm_home", return_value=tmp_path):
            record_sample("qa_scenario", 5100, 12.5)
            stats = load_stats()
            assert "qa_scenario" in stats
            samples = stats["qa_scenario"]["samples"]
            assert len(samples) == 1
            assert samples[0]["memory_mb"] == 5100
            assert samples[0]["age_minutes"] == 12.5

    def test_record_sample_trims_to_history_size(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path), \
             patch("pm_core.launch_queue.pm_home", return_value=tmp_path), \
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
    def test_peak_samples_use_90th_percentile(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path):
            for mb in (1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000):
                record_sample("qa_scenario", mb, 10.0, kind="peak")
            # nearest-rank p90 of 10 samples is the 9th
            assert project_memory("qa_scenario") == 9000

    def test_few_samples_project_their_max(self, tmp_path):
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path):
            record_sample("qa_scenario", 5000, 10.0, kind="peak")
            record_sample("qa_scenario", 5200, 12.0, kind="peak")
            assert project_memory("qa_scenario") == 5200

    def test_snapshot_samples_are_inflated(self, tmp_path):
        """End-of-life usage is not the peak: snapshots get growth headroom."""
        with patch("pm_core.memory_governor.pm_home", return_value=tmp_path):
            record_sample("impl", 4000, 60.0)  # default kind: snapshot
            assert project_memory("impl") == int(4000 * mg._SNAPSHOT_GROWTH_FACTOR)

    def test_legacy_samples_without_kind_are_snapshots(self):
        stats = {"impl": {"samples": [{"memory_mb": 2000, "age_minutes": 5}]}}
        assert project_memory("impl", stats=stats) == int(
            2000 * mg._SNAPSHOT_GROWTH_FACTOR)

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
# Runtime measurement
# ---------------------------------------------------------------------------

def _completed(stdout="", rc=0, stderr=""):
    return MagicMock(returncode=rc, stdout=stdout, stderr=stderr)


class TestParseRuntimeMemory:
    def test_docker_binary_units(self):
        assert parse_runtime_memory("1.5GiB") == 1536
        assert parse_runtime_memory("500MiB") == 500

    def test_podman_decimal_units(self):
        # Podman (go-units HumanSize) prints SI units: 1.06GB = 1.06e9 bytes
        assert parse_runtime_memory("1.06GB") == 1011
        assert parse_runtime_memory("512kB") == 1
        assert parse_runtime_memory("48.13MB") == 46

    def test_no_figure_is_an_error_not_zero(self):
        for value in ("--", "", "N/A"):
            with pytest.raises(ValueError):
                parse_runtime_memory(value)


class TestRuntimeStats:
    def _run(self, *results):
        it = iter(results)
        return patch("pm_core.memory_governor.subprocess.run",
                     side_effect=lambda *a, **k: next(it))

    def test_uses_configured_runtime(self):
        with patch("pm_core.container._get_runtime", return_value="podman"), \
             self._run(_completed("pm-a-impl-pr-1|1.06GB / 128.5GB\n"
                                  "other|9GB / 128GB\n")) as run:
            assert mg.get_pm_container_memory() == {"pm-a-impl-pr-1": 1011}
        assert run.call_args[0][0][:2] == ["podman", "stats"]
        # Podman's tabwriter turns a tab separator into padding spaces
        # (seen live on podman 3.4), so the format must not use one.
        assert run.call_args[0][0][-1] == "{{.Name}}|{{.MemUsage}}"

    def test_no_containers_is_empty_not_error(self):
        with patch("pm_core.container._get_runtime", return_value="docker"), \
             self._run(_completed("")):
            assert mg.get_pm_container_memory() == {}

    def test_stats_failure_raises(self):
        """e.g. one cgroup-less container makes podman stats fail for all."""
        err = "Error: cannot run top on container x: this container does not have a cgroup"
        with patch("pm_core.container._get_runtime", return_value="podman"), \
             self._run(_completed("", rc=125, stderr=err)):
            with pytest.raises(mg.MemoryMeasurementError, match="does not have a cgroup"):
                mg.get_pm_container_memory()

    def test_missing_figure_raises(self):
        with patch("pm_core.container._get_runtime", return_value="podman"), \
             self._run(_completed("pm-qa-pr-1-l-s1|-- / --\n")):
            with pytest.raises(mg.MemoryMeasurementError, match="pm-qa-pr-1-l-s1"):
                mg.get_pm_container_memory()

    def test_zero_usage_raises(self):
        with patch("pm_core.container._get_runtime", return_value="docker"), \
             self._run(_completed("pm-impl-pr-1|0B / 0B\n")):
            with pytest.raises(mg.MemoryMeasurementError, match="0 memory"):
                mg.get_pm_container_memory()

    def test_runtime_missing_raises(self):
        with patch("pm_core.container._get_runtime", return_value="podman"), \
             patch("pm_core.memory_governor.subprocess.run",
                   side_effect=FileNotFoundError("podman")):
            with pytest.raises(mg.MemoryMeasurementError, match="unavailable"):
                mg.get_pm_container_memory()

    def test_started_at_formats(self):
        docker = mg._parse_started_at("2026-10-27T14:11:38.697525333Z")
        podman = mg._parse_started_at("2026-10-27 14:11:38.697525333 +0000 UTC")
        assert docker == podman
        assert docker.tzinfo is not None

    @pytest.mark.parametrize("raw", [
        "2026-10-27 14:11:38.69 +0000 UTC",      # podman, zeros trimmed
        "2026-10-27T14:11:38.69Z",               # docker RFC3339Nano
        "2026-10-27T14:11:38.6900Z",
        "2026-10-27 14:11:38 +0000 UTC",         # whole second
    ])
    def test_started_at_trimmed_fractions(self, raw):
        # Go trims trailing zeros; Python 3.10 only parses 3 or 6 digits.
        parsed = mg._parse_started_at(raw)
        assert parsed.tzinfo is not None
        assert parsed.second == 38
        assert parsed.microsecond in (690000, 0)

    def test_peak_read_from_cgroup(self):
        with patch("pm_core.container._get_runtime", return_value="podman"), \
             self._run(_completed("1275113472\n")) as run:
            assert mg.capture_container_peak("pm-x") == 1217
        assert run.call_args[0][0] == ["podman", "exec", "pm-x", "cat",
                                       "/sys/fs/cgroup/memory.peak"]

    def test_peak_falls_back_to_cgroup_v1_then_none(self):
        with patch("pm_core.container._get_runtime", return_value="docker"), \
             self._run(_completed("", rc=1), _completed("", rc=1)):
            assert mg.capture_container_peak("pm-x") is None


# ---------------------------------------------------------------------------
# Snapshot + admission
# ---------------------------------------------------------------------------

def _settings(**values):
    """Patch governor settings: keys like system_memory_target='48g'."""
    table = {f"container-{k.replace('_', '-')}": v for k, v in values.items()}
    return patch("pm_core.memory_governor.get_global_setting_value",
                 side_effect=lambda name, default="": table.get(name, default))


def _host(total_g, avail_g):
    return mg.HostMemory(total_g * 1024, avail_g * 1024)


class TestSnapshot:
    def test_inactive_without_target(self):
        with _settings():
            snap = mg.take_snapshot()
        assert not snap.active and not snap.error

    def test_invalid_target_is_an_error(self):
        with _settings(system_memory_target="48 gigs"):
            snap = mg.take_snapshot()
        assert "invalid system-memory-target" in snap.error
        ok, reason = mg.admit(snap, 1024)
        assert not ok and "invalid" in reason

    def test_pm_scope_stats_failure_is_an_error(self):
        with _settings(system_memory_target="48g"), \
             patch("pm_core.memory_governor.read_host_memory", return_value=_host(64, 40)), \
             patch("pm_core.memory_governor.get_pm_container_memory",
                   side_effect=mg.MemoryMeasurementError("stats failed")):
            snap = mg.take_snapshot(stats={})
        assert snap.error and "stats failed" in snap.error
        assert mg.admit(snap, 1)[0] is False

    def test_pm_scope_counts_growth_to_projection(self):
        stats = {"qa_scenario": {"samples": [{"memory_mb": 6000, "kind": "peak"}]}}
        running = {"pm-t-qa-pr-1-l-s1": 1000, "pm-t-qa-pr-1-l-s2": 7000}
        with _settings(system_memory_target="48g"), \
             patch("pm_core.memory_governor.read_host_memory", return_value=_host(64, 40)), \
             patch("pm_core.memory_governor.get_pm_container_memory",
                   return_value=running):
            snap = mg.take_snapshot(stats=stats)
        assert snap.measured_mb == 8000
        assert snap.growth_mb == 5000           # s1 may still grow to 6000
        assert snap.used_mb == 13000
        assert snap.running_names == set(running)

    def test_system_scope_without_stats_assumes_full_growth(self):
        stats = {"impl": {"samples": [{"memory_mb": 4096, "kind": "peak"}]}}
        with _settings(system_memory_target="56g", system_memory_scope="system"), \
             patch("pm_core.memory_governor.read_host_memory", return_value=_host(64, 40)), \
             patch("pm_core.memory_governor.get_pm_container_memory",
                   side_effect=mg.MemoryMeasurementError("no cgroup")), \
             patch("pm_core.memory_governor.list_running_pm_containers",
                   return_value=["pm-t-impl-pr-1"]):
            snap = mg.take_snapshot(stats=stats)
        assert not snap.error
        assert snap.measured_mb == 24 * 1024
        assert snap.growth_mb == 4096
        assert snap.used_mb == 24 * 1024 + 4096

    def test_unreadable_host_memory_on_linux_is_an_error(self):
        with _settings(system_memory_target="48g"), \
             patch("pm_core.memory_governor.platform.system", return_value="Linux"), \
             patch("pm_core.memory_governor.read_host_memory", return_value=None):
            snap = mg.take_snapshot(stats={})
        assert "host memory unreadable" in snap.error

    def test_invalid_reserve_is_an_error(self):
        with _settings(system_memory_target="48g", system_memory_reserve="lots"), \
             patch("pm_core.memory_governor.read_host_memory", return_value=_host(64, 40)):
            snap = mg.take_snapshot(stats={})
        assert "system-memory-reserve" in snap.error


class TestAdmit:
    def _snap(self, used_g, target_g=48, growth_g=0, host=None, reserve_g=None):
        return mg.MemorySnapshot(
            target_mb=target_g * 1024, used_mb=used_g * 1024,
            measured_mb=(used_g - growth_g) * 1024, growth_mb=growth_g * 1024,
            host=host, reserve_mb=None if reserve_g is None else reserve_g * 1024)

    def test_fits(self):
        assert mg.admit(self._snap(30), 8 * 1024) == (True, "")

    def test_over_target_names_every_term(self):
        ok, reason = mg.admit(self._snap(34, growth_g=4), 8 * 1024, 8 * 1024)
        assert not ok
        assert "30G used" in reason and "4G expected growth" in reason
        assert "8G reserved" in reason and "48G target" in reason

    def test_host_reserve_preserved(self):
        """pm-scope target fits but the host would drop below its reserve."""
        snap = self._snap(10, growth_g=2, host=_host(64, 12), reserve_g=6)
        ok, reason = mg.admit(snap, 5 * 1024)
        assert not ok and "host headroom" in reason
        assert mg.admit(snap, 3 * 1024)[0] is True

    def test_parse_reserve(self):
        assert mg.parse_reserve("10%", 65536) == 6553
        assert mg.parse_reserve("8g", 65536) == 8192
        with pytest.raises(ValueError):
            mg.parse_reserve("150%", 1)


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

    def test_invalid_target_does_not_fit(self):
        with _settings(system_memory_target="banana"):
            fits, reason = check_single_container_fits("impl")
        assert fits is False and "invalid" in reason


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

    def test_transcript_touched_since(self, tmp_path):
        t = tmp_path / "t.jsonl"
        t.write_text("{}")
        import os
        os.utime(t, (1000.0, 1000.0))
        assert mg.transcript_touched_since(str(t), 990.0) is True
        assert mg.transcript_touched_since(str(t), 999.0) is False  # slack
        assert mg.transcript_touched_since(None, 0.0) is False
        assert mg.transcript_touched_since(str(tmp_path / "gone"), 0.0) is False


# ---------------------------------------------------------------------------
# Memory status
# ---------------------------------------------------------------------------

class TestMemoryStatus:
    def _status(self, used_mb, scope="pm", error=""):
        snap = mg.MemorySnapshot(target_mb=48 * 1024, scope=scope,
                                 used_mb=used_mb, measured_mb=used_mb,
                                 error=error)
        with patch("pm_core.memory_governor.take_snapshot", return_value=snap):
            return mg.compute_memory_status()

    def test_no_target(self):
        with patch("pm_core.memory_governor.get_memory_target",
                   return_value=None):
            assert mg.compute_memory_status() == ""

    def test_pm_scope(self):
        assert self._status(34 * 1024) == "mem 34G/48G (pm)"

    def test_system_scope(self):
        assert self._status(52 * 1024, scope="system") == "mem 52G/48G (sys)"

    def test_fractional_and_sub_gigabyte(self):
        assert self._status(1536) == "mem 1.5G/48G (pm)"
        assert self._status(500) == "mem 500M/48G (pm)"

    def test_unmeasurable_is_shown_not_hidden(self):
        """Regression: a failed measurement used to blank the indicator."""
        assert self._status(None, error="stats failed") == "mem ?/48G (pm) unmeasurable"

    def test_blocked_launch_shown(self):
        mg.record_blocked("impl pr-1", "over target")
        mg.record_blocked("review pr-2", "over target")
        assert self._status(1024).endswith("blocked: review pr-2 +1")
        mg.clear_blocked("review pr-2")
        mg.clear_blocked("impl pr-1")
        assert "blocked" not in self._status(1024)

    def test_format_memory_status_never_measures_inline(self):
        """The UI-thread accessor returns cached text; refresh is async."""
        import threading
        release = threading.Event()

        def slow():
            release.wait(5)
            return "mem 1G/48G (pm)"

        with patch("pm_core.memory_governor.compute_memory_status", side_effect=slow):
            assert format_memory_status() == ""     # returns at once
            release.set()
            for t in threading.enumerate():
                if t.name == "pm-memory-status":
                    t.join(5)
            assert format_memory_status(max_age=float("inf")) == "mem 1G/48G (pm)"


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

    def test_runtime_failure_skips(self):
        with patch("pm_core.memory_governor.infer_container_type",
                   return_value="impl"), \
             patch("pm_core.memory_governor.capture_container_peak",
                   return_value=None), \
             patch("pm_core.memory_governor.capture_container_memory",
                   return_value=None), \
             patch("pm_core.memory_governor.record_sample") as mock_record:
            capture_and_record("pm-impl")
            mock_record.assert_not_called()

    def test_prefers_cgroup_peak(self):
        with patch("pm_core.memory_governor.capture_container_peak",
                   return_value=6100), \
             patch("pm_core.memory_governor.capture_container_memory") as snap, \
             patch("pm_core.memory_governor.get_container_age_minutes",
                   return_value=45.0), \
             patch("pm_core.memory_governor.record_sample") as mock_record:
            capture_and_record("pm-impl")
        snap.assert_not_called()
        mock_record.assert_called_once_with("impl", 6100, 45.0, kind="peak")

    def test_falls_back_to_snapshot(self):
        with patch("pm_core.memory_governor.capture_container_peak",
                   return_value=None), \
             patch("pm_core.memory_governor.capture_container_memory",
                   return_value=4200), \
             patch("pm_core.memory_governor.get_container_age_minutes",
                   return_value=45.0), \
             patch("pm_core.memory_governor.record_sample") as mock_record:
            capture_and_record("pm-impl")
        mock_record.assert_called_once_with("impl", 4200, 45.0, kind="snapshot")

    def test_record_sample_integration(self, tmp_path):
        with patch("pm_core.memory_governor.capture_container_peak",
                   return_value=None), \
             patch("pm_core.memory_governor.capture_container_memory",
                   return_value=5325), \
             patch("pm_core.memory_governor.get_container_age_minutes",
                   return_value=45.0), \
             patch("pm_core.memory_governor.pm_home",
                   return_value=tmp_path), \
             patch("pm_core.launch_queue.pm_home",
                   return_value=tmp_path):
            capture_and_record("pm-impl")
            stats = load_stats()
            assert "impl" in stats
            samples = stats["impl"]["samples"]
            assert len(samples) == 1
            assert samples[0]["memory_mb"] == 5325
            assert samples[0]["kind"] == "snapshot"
            assert samples[0]["age_minutes"] == 45.0
            assert "recorded_at" in samples[0]

    def test_busy_lock_skips_sample_without_blocking(self):
        from pm_core.launch_queue import GovernorLockTimeout
        with patch("pm_core.launch_queue.governor_lock",
                   side_effect=GovernorLockTimeout("busy")):
            record_sample("impl", 100, 1.0)  # must not raise
        assert load_stats() == {}
