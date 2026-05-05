"""Tests for the home_window provider seam and pr-list rendering."""

from unittest.mock import patch

import pm_core.home_window as home_window
from pm_core.cli.helpers import format_pr_line
from pm_core.home_window.pr_list import (
    PrListProvider,
    _format_relative,
    _render_content,
    _truncate,
)


def _render_once(width: int = 80, height: int = 24) -> str:
    body = _render_content(width, height)
    return f"pm pr list -t --open\n{'=' * 20}\n{body}"


class TestRegistry:
    def test_default_provider_is_pr_list(self):
        provider = home_window.get_active_provider()
        assert provider.name == "pr-list"
        assert provider.window_name == "pm-home"

    def test_unknown_provider_falls_back_to_pr_list(self, capsys):
        with patch("pm_core.home_window.get_global_setting_value",
                   return_value="does-not-exist"):
            provider = home_window.get_active_provider()
        assert provider.name == "pr-list"
        err = capsys.readouterr().err
        assert "does-not-exist" in err

    def test_register_adds_to_registry(self):
        class Dummy:
            name = "dummy-test-provider"
            window_name = "pm-dummy"

            def ensure_window(self, session):  # pragma: no cover
                return self.window_name

            def refresh(self, session):  # pragma: no cover
                pass

        d = Dummy()
        home_window.register(d)
        assert home_window._REGISTRY["dummy-test-provider"] is d


class TestParkIfOnSafety:
    def test_no_op_outside_tmux(self):
        with patch("pm_core.home_window.tmux_mod.in_tmux", return_value=False):
            assert home_window.park_if_on("pm-x", "@1") == []

    def test_no_op_when_session_missing(self):
        with patch("pm_core.home_window.tmux_mod.in_tmux", return_value=True), \
             patch("pm_core.home_window.tmux_mod.session_exists", return_value=False):
            assert home_window.park_if_on("pm-x", "@1") == []

    def test_no_op_with_empty_args(self):
        assert home_window.park_if_on(None, "@1") == []
        assert home_window.park_if_on("pm-x", None) == []

    def test_no_op_when_no_sessions_on_target(self):
        with patch("pm_core.home_window.tmux_mod.in_tmux", return_value=True), \
             patch("pm_core.home_window.tmux_mod.session_exists", return_value=True), \
             patch("pm_core.home_window.tmux_mod.sessions_on_window", return_value=[]):
            assert home_window.park_if_on("pm-x", "@1") == []


class TestEnsureHomeWindow:
    def test_no_op_outside_tmux(self):
        with patch("pm_core.home_window.tmux_mod.in_tmux", return_value=False):
            assert home_window.ensure_home_window("pm-x") is None

    def test_no_op_no_session(self):
        with patch("pm_core.home_window.tmux_mod.in_tmux", return_value=True):
            assert home_window.ensure_home_window(None) is None


class TestPrListProvider:
    def test_refresh_no_session_dir_safe(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pm_core.home_window.pr_list.pm_home",
                            lambda: tmp_path)
        provider = PrListProvider()
        provider.refresh("pm-test")
        assert (tmp_path / "runtime" / "home-refresh-pm-test").exists()

    def test_refresh_strips_grouped_session_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pm_core.home_window.pr_list.pm_home",
                            lambda: tmp_path)
        PrListProvider().refresh("pm-test~2")
        # Sentinel keyed by base session, not grouped suffix
        assert (tmp_path / "runtime" / "home-refresh-pm-test").exists()

    def test_render_once_handles_load_failure(self):
        with patch("pm_core.store.find_project_root",
                   side_effect=FileNotFoundError("no project")):
            out = _render_once()
        assert "error loading project" in out

    def test_render_once_renders_open_prs(self):
        fake_data = {
            "project": {"active_pr": "pr-1"},
            "prs": [
                {"id": "pr-1", "title": "Open PR", "status": "in_progress",
                 "updated_at": "2026-01-01T10:00:00+00:00"},
                {"id": "pr-2", "title": "Closed PR", "status": "closed"},
            ],
        }
        with patch("pm_core.store.find_project_root", return_value="/tmp"), \
             patch("pm_core.store.load", return_value=fake_data):
            out = _render_once()
        assert "Open PR" in out
        assert "Closed PR" not in out
        assert "pm pr list -t --open" in out


class TestRenderHelpers:
    def test_format_relative_buckets_sub_minute_to_just_now(self):
        # Sub-minute granularity must NOT change with each second, or the
        # paint hash flips every tick and the home window flickers.
        assert _format_relative(0) == "just now"
        assert _format_relative(1) == "just now"
        assert _format_relative(8) == "just now"
        assert _format_relative(59) == "just now"

    def test_format_relative_minute_and_hour_buckets(self):
        assert _format_relative(60) == "1m ago"
        assert _format_relative(125) == "2m ago"
        assert _format_relative(3600) == "1h ago"
        assert _format_relative(7200) == "2h ago"

    def test_truncate_short_line_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_truncate_long_line_appends_ellipsis(self):
        assert _truncate("abcdefghij", 5) == "abcd…"

    def test_truncate_zero_or_negative_width(self):
        assert _truncate("abc", 0) == ""
        assert _truncate("abc", -1) == ""

    def test_truncate_width_one(self):
        assert _truncate("abcdef", 1) == "…"

    def test_render_content_overflow_emits_more_footer(self):
        prs = [
            {"id": f"pr-{i}", "title": f"T{i}", "status": "in_progress",
             "updated_at": f"2026-01-{i:02d}T10:00:00+00:00"}
            for i in range(1, 11)
        ]
        with patch("pm_core.store.find_project_root", return_value="/tmp"), \
             patch("pm_core.store.load", return_value={"prs": prs,
                                                       "project": {}}):
            body = _render_content(80, 5)
        # height=5 -> rows_for_prs=3, overflow -> visible 2 + footer
        assert "and" in body and "more" in body
        # most recent (highest date) should be visible, oldest hidden
        assert "T10" in body  # most recent
        assert "T1:" not in body  # oldest hidden (no plain "T1:" form)


class TestFormatPrLine:
    def test_active_marker(self):
        line = format_pr_line({"id": "pr-1", "title": "t", "status": "pending"},
                              active_pr="pr-1")
        assert " *" in line

    def test_no_active_marker_when_inactive(self):
        line = format_pr_line({"id": "pr-1", "title": "t", "status": "pending"},
                              active_pr="pr-2")
        assert " *" not in line

    def test_timestamp_optional(self):
        no_ts = format_pr_line({"id": "pr-1", "title": "t", "status": "pending",
                                "updated_at": "2026-01-01T10:00:00+00:00"},
                               with_timestamp=False)
        with_ts = format_pr_line({"id": "pr-1", "title": "t", "status": "pending",
                                  "updated_at": "2026-01-01T10:00:00+00:00"},
                                 with_timestamp=True)
        assert "[2026-01-01" in with_ts
        assert "[2026-01-01" not in no_ts
