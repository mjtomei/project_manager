"""Tests for the plans pane and extract_plan_intro."""

import inspect
import re

import pytest
from rich.text import Text

from pm_core.plans.parser import extract_plan_intro
from pm_core.tui.plans_pane import PlansPane


class TestExtractPlanIntro:
    """Tests for extract_plan_intro."""

    def test_empty_text(self):
        assert extract_plan_intro("") == ""

    def test_title_only(self):
        assert extract_plan_intro("# My Plan") == ""

    def test_title_and_description(self):
        text = "# My Plan\n\nThis is the intro paragraph.\nSecond line."
        result = extract_plan_intro(text)
        assert result == "This is the intro paragraph.\nSecond line."

    def test_stops_at_h2(self):
        text = "# Title\n\nIntro text here.\n\n## Motivation\n\nMore text."
        result = extract_plan_intro(text)
        assert result == "Intro text here."
        assert "Motivation" not in result
        assert "More text" not in result

    def test_no_title(self):
        text = "Some text without a title.\n\n## Section\n\nBody."
        result = extract_plan_intro(text)
        assert result == "Some text without a title."

    def test_real_plan_format(self):
        text = (
            "# Multi-candidate test-driven code generation\n"
            "\n"
            "Improve local LLM coding performance by separating test generation from solution\n"
            "generation and selecting the best candidate via test pass rate.\n"
            "\n"
            "## Motivation\n"
            "\n"
            "Current coding agents use a single model.\n"
        )
        result = extract_plan_intro(text)
        assert "Improve local LLM" in result
        assert "test pass rate" in result
        assert "Motivation" not in result


class TestPlansPane:
    """Tests for the PlansPane widget."""

    def test_initializes_empty(self):
        pane = PlansPane()
        assert pane._plans == []
        assert pane.selected_index == 0

    def test_selected_plan_id_none_when_empty(self):
        pane = PlansPane()
        assert pane.selected_plan_id is None

    def test_update_plans(self):
        pane = PlansPane()
        plans = [
            {"id": "plan-001", "name": "First", "file": "f.md", "status": "draft", "intro": "", "pr_count": 3},
            {"id": "plan-002", "name": "Second", "file": "g.md", "status": "draft", "intro": "", "pr_count": 0},
        ]
        pane.update_plans(plans)
        assert len(pane._plans) == 2
        assert pane.selected_plan_id == "plan-001"

    def test_selected_plan_id_after_index_change(self):
        pane = PlansPane()
        plans = [
            {"id": "plan-001", "name": "First", "file": "f.md", "status": "draft", "intro": "", "pr_count": 0},
            {"id": "plan-002", "name": "Second", "file": "g.md", "status": "draft", "intro": "", "pr_count": 0},
        ]
        pane.update_plans(plans)
        pane.selected_index = 1
        assert pane.selected_plan_id == "plan-002"

    def test_index_clamped_on_shorter_list(self):
        pane = PlansPane()
        plans = [
            {"id": "plan-001", "name": "First", "file": "f.md", "status": "draft", "intro": "", "pr_count": 0},
            {"id": "plan-002", "name": "Second", "file": "g.md", "status": "draft", "intro": "", "pr_count": 0},
        ]
        pane.update_plans(plans)
        pane.selected_index = 1
        # Now update with shorter list
        pane.update_plans([plans[0]])
        assert pane.selected_index == 0

    def test_render_returns_text(self):
        pane = PlansPane()
        result = pane.render()
        assert isinstance(result, Text)

    def test_render_shows_empty_message(self):
        pane = PlansPane()
        result = pane.render()
        assert "No plans yet" in result.plain

    def test_render_shows_plan_names(self):
        pane = PlansPane()
        pane.update_plans([
            {"id": "plan-001", "name": "Import from repo", "file": "f.md", "status": "draft", "intro": "", "pr_count": 2},
        ])
        result = pane.render()
        text = result.plain
        assert "plan-001" in text
        assert "Import from repo" in text
        assert "draft" in text
        assert "2 PRs" in text

    def test_render_shows_intro(self):
        pane = PlansPane()
        pane.update_plans([
            {"id": "plan-001", "name": "Test", "file": "f.md", "status": "draft",
             "intro": "This is the intro text.", "pr_count": 0},
        ])
        result = pane.render()
        assert "This is the intro text." in result.plain

    def test_render_shows_shortcuts(self):
        pane = PlansPane()
        result = pane.render()
        text = result.plain
        assert "add" in text
        assert "review" in text
        assert "load" in text
        assert "edit" in text
        assert "back" in text

    def test_key_action_mapping(self):
        """Verify _KEY_ACTIONS maps keys to the correct action strings."""
        pane = PlansPane()
        expected = {
            "a": "add",
            "D": "deps",
            "l": "load",
            "e": "edit",
            "c": "review",
        }
        assert pane._KEY_ACTIONS == expected

    def test_handler_routes_match_key_actions(self):
        """Verify handle_plan_action routes each action to the matching pm command."""
        from pm_core.tui.pane_ops import handle_plan_action
        src = inspect.getsource(handle_plan_action)
        # For pane-launching actions, verify the action check and the
        # command string use the SAME action word.
        for action in ("review",):
            # Find: action == "<action>" ... pm plan <action>
            pattern = rf'action\s*==\s*"{action}".*?_launch_in_plans_window\(.*?pm plan {action}'
            assert re.search(pattern, src, re.DOTALL), (
                f"action '{action}' does not route to 'pm plan {action}' in handle_plan_action"
            )
        # load runs inline (no pane) via _run_command
        pattern = r'action\s*==\s*"load".*?_run_command\(.*?plan load'
        assert re.search(pattern, src, re.DOTALL), (
            "action 'load' does not route to 'plan load' via _run_command in handle_plan_action"
        )

    def test_render_singular_pr(self):
        pane = PlansPane()
        pane.update_plans([
            {"id": "plan-001", "name": "Test", "file": "f.md", "status": "draft", "intro": "", "pr_count": 1},
        ])
        result = pane.render()
        assert "1 PR" in result.plain
        # Should NOT have "1 PRs"
        assert "1 PRs" not in result.plain


def _plans_view_app():
    """A bare App that shows PlansPane inside #plans-container with the real
    TUI CSS (``height: auto`` pane, padding, scrolling container), so layout
    and scroll behave as in the plans view."""
    from textual.app import App, ComposeResult
    from textual.containers import Vertical

    from pm_core.tui.app import ProjectManagerApp

    class _PlansApp(App):
        CSS = ProjectManagerApp.CSS + "\n#plans-container { display: block; }"

        def compose(self) -> ComposeResult:
            with Vertical(id="plans-container"):
                yield PlansPane(id="plans-pane")

    return _PlansApp()


class TestPlansPaneHeightTracksContent:
    """The pane is ``height: auto``; adding a plan while the plans view is
    open must grow it, or the footer (a=add c=review ...) is clipped.
    Before the fix update_plans() called refresh() without layout=True, so
    the pane kept its one-plan height and the footer vanished after ``a``
    added a second plan, even across p/p toggles (QA S3, pr-30888b1)."""

    @staticmethod
    def _plan(i, intro="Body line."):
        return {"id": f"plan-00{i}", "name": f"Plan {i}", "file": f"p{i}.md",
                "status": "draft", "intro": intro, "pr_count": 0}

    def _visible_lines(self, plan_lists):
        import asyncio

        async def run():
            app = _plans_view_app()
            snapshots = []
            async with app.run_test(size=(100, 40)) as pilot:
                pane = app.query_one("#plans-pane", PlansPane)
                for plans in plan_lists:
                    pane.update_plans(plans)
                    await pilot.pause()
                    snapshots.append([
                        pane.render_line(y).text
                        for y in range(pane.size.height)])
            return snapshots
        return asyncio.run(run())

    def test_footer_visible_after_plan_added(self):
        one, two = self._visible_lines([
            [self._plan(1)],
            [self._plan(1), self._plan(2)],
        ])
        assert any("a=add" in line for line in one)
        assert any("Plan 2" in line for line in two)
        assert any("a=add" in line and "p=back" in line for line in two)

    def test_footer_visible_after_intro_grows(self):
        _, grown = self._visible_lines([
            [self._plan(1)],
            [self._plan(1, intro="Line one.\nLine two.\nLine three.")],
        ])
        assert any("Line three." in line for line in grown)
        assert any("a=add" in line for line in grown)


class TestPlansPaneYieldsToChordPrefix:
    """``w`` (watcher) and ``y`` (cleanup-then) are app-level prefixes.
    With one armed, the plans pane must leave the next key to
    ``ProjectManagerApp.on_key``.  Before the fix ``w c r`` in the plans
    view opened a plan review (the pane stopped ``c``), left the prefix
    armed, and the ``r`` then launched a watcher review session; ``w l``
    and ``w e`` did the same (QA S10, pr-30888b1)."""

    def _press(self, *keys):
        import asyncio

        from textual.app import App, ComposeResult

        from pm_core.tui.app import ProjectManagerApp

        class Host(App):
            _command_pending = False
            _w_mode = False
            _y_mode = False
            _z_count = 0
            _w_cancel_timer = None
            _y_cancel_timer = None
            _prefix_hint_seq = 0
            on_key = ProjectManagerApp.on_key
            chord_prefix_armed = ProjectManagerApp.chord_prefix_armed
            _command_bar = ProjectManagerApp._command_bar
            _cancel_w_mode = ProjectManagerApp._cancel_w_mode
            _cancel_y_mode = ProjectManagerApp._cancel_y_mode

            def __init__(self):
                super().__init__()
                self.logged: list[str] = []
                self.watcher: list[str] = []
                self.plan_actions: list[str] = []

            def compose(self) -> ComposeResult:
                yield PlansPane(id="plans-pane")

            def check_action(self, action, parameters):
                return True

            def log_message(self, msg, *args, **kwargs):
                self.logged.append(Text.from_markup(msg).plain)
                return len(self.logged)

            def _clear_prefix_hint(self):
                pass

            def _action_watcher_list(self):
                self.watcher.append("list")

            def _action_focus_watcher(self):
                self.watcher.append("focus")

            def _action_watcher_toggle(self):
                self.watcher.append("toggle")

            def _action_watcher_review(self):
                self.watcher.append("review")

            def on_plan_action(self, message):
                self.plan_actions.append(message.action)

        async def run():
            app = Host()
            async with app.run_test(size=(100, 30)) as pilot:
                pane = app.query_one("#plans-pane", PlansPane)
                pane.update_plans([
                    {"id": f"plan-00{i}", "name": f"Plan {i}", "file": f"p{i}.md",
                     "status": "draft", "intro": "", "pr_count": 0}
                    for i in (1, 2)])
                pane.focus()
                await pilot.pause()
                await pilot.press(*keys)
                await pilot.pause()
                return (app.plan_actions, app.watcher, app.logged,
                        pane.selected_index, app._w_mode, app._y_mode)
        return asyncio.run(run())

    @pytest.mark.parametrize("key", ["c", "l", "e", "a", "D"])
    def test_w_then_plan_key_cancels_without_action(self, key):
        actions, watcher, logged, _, w_mode, _ = self._press("w", key, "r")
        assert actions == []
        assert logged[-1] == "w cancelled"
        # The r after the cancelled chord is not a watcher review.
        assert watcher == []
        assert w_mode is False

    def test_w_then_j_does_not_move_selection(self):
        _, _, logged, index, w_mode, _ = self._press("w", "j")
        assert index == 0
        assert logged[-1] == "w cancelled"
        assert w_mode is False

    def test_w_chords_still_dispatch(self):
        _, watcher, _, _, _, _ = self._press("w", "r", "w", "w")
        assert watcher == ["review", "list"]

    def test_y_then_plan_key_cancels_without_action(self):
        actions, _, logged, _, _, y_mode = self._press("y", "c")
        assert actions == []
        assert logged[-1] == "y cancelled"
        assert y_mode is False

    def test_plan_keys_fire_without_prefix(self):
        actions, watcher, _, index, _, _ = self._press("c", "j", "l", "e")
        assert actions == ["review", "load", "edit"]
        assert index == 1
        assert watcher == []


class TestPlansPaneScrollReachesFooter:
    """Once the list overflows, moving to the last plan must also scroll the
    shortcut footer into view.  Before the fix, _scroll_selected_into_view
    ignored the pane's top padding and stopped at the last plan's own
    lines, so at 80x24 with 7 plans the footer stayed 2-3 rows below the
    viewport (QA S9, pr-30888b1; spec R8)."""

    FOOTER = "D=deps p=back"

    @staticmethod
    def _plans(n):
        return [{"id": f"plan-{i:03d}", "name": f"Plan {i}", "file": f"p{i}.md",
                 "status": "draft", "intro": "Body line.", "pr_count": 0}
                for i in range(1, n + 1)]

    def _run(self, n, keys):
        """Show *n* plans at 80x24, press *keys* one at a time and return
        (on-screen text, container scroll_y) after each key."""
        import asyncio
        import html

        def screen_text(app):
            svg = re.sub(r"<[^>]+>", "", app.export_screenshot())
            return re.sub(r"\s+", " ", html.unescape(svg))

        async def run():
            app = _plans_view_app()
            states = []
            async with app.run_test(size=(80, 24)) as pilot:
                pane = app.query_one("#plans-pane", PlansPane)
                container = app.query_one("#plans-container")
                pane.update_plans(self._plans(n))
                pane.focus()
                await pilot.pause()
                for key in keys:
                    await pilot.press(key)
                    await pilot.pause()
                    states.append((screen_text(app), container.scroll_y))
            return states
        return asyncio.run(run())

    def test_last_plan_brings_footer_into_view(self):
        states = self._run(10, ["j"] * 9)
        text, _ = states[-1]
        assert "▶ plan-010: Plan 10" in text
        assert self.FOOTER in text

    def test_footer_hidden_until_last_plan(self):
        # The list really overflows: the footer is off screen mid-list.
        states = self._run(10, ["j"] * 5)
        text, _ = states[-1]
        assert "▶ plan-006: Plan 6" in text
        assert self.FOOTER not in text

    def test_back_to_first_plan_scrolls_to_top(self):
        states = self._run(10, ["j"] * 9 + ["k"] * 9)
        text, scroll_y = states[-1]
        assert scroll_y == 0
        assert "▶ plan-001: Plan 1 " in text
        assert self.FOOTER not in text
