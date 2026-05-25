"""Tests for the home_window provider seam and pr-list rendering."""

from unittest.mock import patch

import pm_core.home_window as home_window
from pm_core.cli.helpers import format_pr_line
from pm_core.home_window.pr_list import (
    DEFAULT_SIZE,
    PrListProvider,
    _PaintState,
    _compose,
    _format_relative,
    _hash,
    _render_content,
    _terminal_size,
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


class TestRefreshHome:
    def test_no_op_when_session_unresolvable(self):
        # No explicit session and none resolvable -> silent no-op, no
        # provider lookup attempted.
        with patch("pm_core.cli.helpers._get_pm_session", return_value=None), \
             patch("pm_core.home_window.get_active_provider") as gp:
            home_window.refresh_home()
            gp.assert_not_called()

    def test_no_op_outside_tmux(self):
        with patch("pm_core.home_window.tmux_mod.has_tmux", return_value=False), \
             patch("pm_core.home_window.get_active_provider") as gp:
            home_window.refresh_home("pm-x")
            gp.assert_not_called()

    def test_no_op_when_session_missing(self):
        with patch("pm_core.home_window.tmux_mod.has_tmux", return_value=True), \
             patch("pm_core.home_window.tmux_mod.session_exists",
                   return_value=False), \
             patch("pm_core.home_window.get_active_provider") as gp:
            home_window.refresh_home("pm-x")
            gp.assert_not_called()

    def test_touches_provider_when_session_live(self):
        from unittest.mock import MagicMock
        provider = MagicMock()
        with patch("pm_core.home_window.tmux_mod.has_tmux", return_value=True), \
             patch("pm_core.home_window.tmux_mod.session_exists",
                   return_value=True), \
             patch("pm_core.home_window.get_active_provider",
                   return_value=provider):
            home_window.refresh_home("pm-x")
            provider.refresh.assert_called_once_with("pm-x")


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

    def test_truncate_measures_display_width_not_codepoints(self):
        # The PR status emoji (⏳) is a 2-cell glyph. Truncating by
        # code-point count would yield a string that renders one cell
        # wider than the pane and soft-wraps, scrolling the header off
        # screen. Measure in display cells so the result never exceeds
        # the requested width.
        from pm_core.home_window.pr_list import _display_width

        line = "  ⏳ pr-1234567: a really long PR title that overflows"
        for width in (1, 5, 10, 20, 40):
            out = _truncate(line, width)
            assert _display_width(out) <= width, (width, out)
        # A line that fits in cells (even if it contains a wide glyph) is
        # returned unchanged.
        assert _truncate("⏳ ok", 5) == "⏳ ok"

    def test_truncate_fits_every_status_emoji_from_format_pr_line(self):
        # Regression for pr-9330dec: the home window truncates lines that
        # come from format_pr_line, which prepends a 2-cell status glyph
        # from PR_STATUS_ICONS. Drive the *real* formatter for *every*
        # status (not just a hardcoded ⏳) and assert the truncated line
        # never exceeds the pane width at boundary widths. Counting code
        # points instead of cells would make every one of these overflow
        # by at least one cell and soft-wrap on a narrow pane. This also
        # guards against a future status emoji that east_asian_width
        # classifies as narrow, which the single-literal test above misses.
        from pm_core.cli.helpers import PR_STATUS_ICONS
        from pm_core.home_window.pr_list import _display_width

        long_title = "an extremely long pull-request title that overflows"
        for status, icon in PR_STATUS_ICONS.items():
            assert _display_width(icon) == 2, (status, icon)
            line = format_pr_line(
                {"id": "pr-1234567", "title": long_title, "status": status},
                with_timestamp=True,
            )
            # Widths around the leading "  <icon> " prefix boundary, where
            # an off-by-one cell miscount would surface as a soft-wrap.
            for width in (3, 4, 5, 6, 7, 10, 20, 40):
                out = _truncate(line, width)
                assert _display_width(out) <= width, (status, width, out)

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

    def test_compose_clamps_to_pane_height(self):
        # The composed screen must never exceed `height` lines. The loop
        # writes it with NO trailing newline, so a screen of exactly
        # `height` lines lands on the bottom row without scrolling the
        # header off the top.
        prs = [
            {"id": f"pr-{i}", "title": f"T{i}", "status": "in_progress",
             "updated_at": f"2026-01-{i:02d}T10:00:00+00:00"}
            for i in range(1, 11)
        ]
        height = 6
        with patch("pm_core.store.find_project_root", return_value="/tmp"), \
             patch("pm_core.store.load", return_value={"prs": prs,
                                                       "project": {}}):
            body = _render_content(80, height)
        screen = _compose("pm pr list -t --open  (updated just now)",
                          body, 80, height)
        assert len(screen.split("\n")) <= height

    def test_compose_clamps_oversized_body_by_line_count(self):
        # Guards against clamping by element count instead of line count:
        # a multi-line body that exceeds the height must still be cut to
        # `height` lines, even if _render_content's own budgeting is
        # bypassed (here we hand _compose a deliberately oversized body).
        body = "\n".join(f"row{i}" for i in range(20))
        screen = _compose("header", body, 80, height=5)
        lines = screen.split("\n")
        assert len(lines) == 5
        assert lines[0] == "header"

    def test_terminal_size_falls_back_when_not_a_tty(self):
        # os.get_terminal_size raises OSError when stdout isn't a TTY
        # (e.g. captured under pytest); the loop must keep rendering.
        with patch("pm_core.home_window.pr_list.os.get_terminal_size",
                   side_effect=OSError):
            assert _terminal_size() == DEFAULT_SIZE

    def test_render_content_null_project_key(self):
        # A present-but-null `project:` in project.yaml (store.load returns
        # raw YAML) must not blow up with AttributeError — it should render
        # the PR list with no active marker, not surface a "render error".
        prs = [{"id": "pr-1", "title": "Open PR", "status": "in_progress",
                "updated_at": "2026-01-01T10:00:00+00:00"}]
        with patch("pm_core.store.find_project_root", return_value="/tmp"), \
             patch("pm_core.store.load",
                   return_value={"prs": prs, "project": None}):
            body = _render_content(80, 24)
        assert "Open PR" in body
        assert "error" not in body

    def test_render_content_empty_list(self):
        with patch("pm_core.store.find_project_root", return_value="/tmp"), \
             patch("pm_core.store.load",
                   return_value={"prs": [], "project": {}}):
            body = _render_content(80, 24)
        assert body == "No open PRs."

    def test_render_content_load_failure_truncated_to_width(self):
        # Error path must respect width too (it goes straight to stdout).
        with patch("pm_core.store.find_project_root",
                   side_effect=FileNotFoundError("boom")):
            wide = _render_content(80, 24)
            narrow = _render_content(20, 24)
        assert "error loading project" in wide
        # Narrow render is truncated to width with an ellipsis, never overflows.
        assert all(len(line) <= 20 for line in narrow.split("\n"))
        assert narrow.endswith("…")

    def test_tiny_pane_still_emits_header_no_crash(self):
        # Spec edge case: height < 3 (header + ruler) must not crash and
        # must still surface at least the (truncated) header line.
        prs = [
            {"id": f"pr-{i}", "title": f"Title number {i}",
             "status": "in_progress",
             "updated_at": f"2026-01-{i:02d}T10:00:00+00:00"}
            for i in range(1, 6)
        ]
        for height in (1, 2):
            with patch("pm_core.store.find_project_root", return_value="/tmp"), \
                 patch("pm_core.store.load", return_value={"prs": prs,
                                                           "project": {}}):
                body = _render_content(80, height)
            screen = _compose("pm pr list -t --open  (updated just now)",
                              body, 80, height)
            lines = screen.split("\n")
            assert len(lines) <= height
            assert lines[0].startswith("pm pr list")


class TestPaintState:
    """Guards the PR's headline invariant: a quiet pm is a quiet pm-home.

    The loop body that drives this is an infinite select/sleep, so the
    decision lives in _PaintState.step() where it can be exercised
    deterministically with injected monotonic times.
    """

    def _ch(self, body: str, size: str = "80x24") -> str:
        return _hash(size, body)

    def test_first_step_paints(self):
        st = _PaintState(now=1000.0)
        should, label = st.step(self._ch("body"), 1000.0)
        assert should is True
        assert label == "just now"

    def test_no_repaint_when_content_and_bucket_stable(self):
        st = _PaintState(now=1000.0)
        ch = self._ch("body")
        assert st.step(ch, 1000.0)[0] is True   # first paint
        # Same content, still inside the "just now" bucket -> no repaint,
        # even across many sub-second ticks. This is the anti-flicker core.
        assert st.step(ch, 1000.75)[0] is False
        assert st.step(ch, 1030.0)[0] is False
        assert st.step(ch, 1059.0)[0] is False

    def test_repaint_on_staleness_bucket_flip(self):
        st = _PaintState(now=1000.0)
        ch = self._ch("body")
        st.step(ch, 1000.0)                      # paint, "just now"
        assert st.step(ch, 1059.0)[0] is False   # still "just now"
        should, label = st.step(ch, 1061.0)      # 61s -> "1m ago"
        assert should is True
        assert label == "1m ago"

    def test_content_change_resets_staleness_to_just_now(self):
        st = _PaintState(now=1000.0)
        st.step(self._ch("body1"), 1000.0)
        should, label = st.step(self._ch("body1"), 1061.0)  # drift into 1m
        assert should is True and label == "1m ago"
        # New content at t=1100 -> the "last changed" clock resets, so the
        # staleness phrasing snaps back to "just now".
        should, label = st.step(self._ch("body2"), 1100.0)
        assert should is True
        assert label == "just now"

    def test_resize_changes_content_hash_and_repaints(self):
        # Width/height are folded into content_hash by the loop, so a
        # resize is a genuine content change -> repaint.
        st = _PaintState(now=1000.0)
        st.step(self._ch("b", "80x24"), 1000.0)
        should, _ = st.step(self._ch("b", "100x40"), 1000.5)
        assert should is True


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
