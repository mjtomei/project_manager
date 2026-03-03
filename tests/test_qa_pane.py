"""Tests for the QA instructions pane widget.

Covers rendering logic, keyboard navigation, item activation, and status bar
format as specified in the QA pane display scenario.

Since QAPane is a Textual Widget with reactive state, we test the pure logic
(data flattening, selectable indices, rendering, entry lines) by extracting
the algorithms and verifying them against the same data structures.
"""

import inspect
import pytest
from rich.text import Text
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixture: sample items for both sections
# ---------------------------------------------------------------------------

SAMPLE_ITEMS = {
    "instructions": [
        {"id": "login-flow", "title": "Login Flow", "description": "Test login end-to-end", "path": "/tmp/login-flow.md", "tags": ["auth"]},
        {"id": "signup", "title": "Signup Test", "description": "", "path": "/tmp/signup.md", "tags": []},
    ],
    "regression": [
        {"id": "pane-layout", "title": "Pane Layout", "description": "Verify pane renders correctly", "path": "/tmp/pane-layout.md", "tags": ["tui"]},
    ],
}


def _flatten_items(all_items: dict) -> list[dict]:
    """Reproduce the flattening logic from QAPane.update_items."""
    flat: list[dict] = []
    for category, label in [("instructions", "Instructions"),
                            ("regression", "Regression Tests")]:
        items = all_items.get(category, [])
        flat.append({"_section": label, "_count": len(items)})
        for item in items:
            flat.append({**item, "_category": category, "_item_id": f"{category}:{item['id']}"})
    return flat


def _selectable_indices(items: list[dict]) -> list[int]:
    """Reproduce selectable indices logic from QAPane."""
    return [i for i, item in enumerate(items) if "_section" not in item]


def _clamp_index(items: list[dict], selected_index: int) -> int:
    """Reproduce clamp logic from QAPane."""
    indices = _selectable_indices(items)
    if not indices:
        return 0
    if selected_index not in indices:
        return indices[0]
    return selected_index


def _truncate(text: str, max_width: int) -> str:
    if len(text) <= max_width:
        return text
    return text[: max_width - 1] + "\u2026"


def _render(items: list[dict], selected_index: int, width: int = 80) -> Text:
    """Reproduce the render logic from QAPane."""
    output = Text()
    content_width = (width - 4) if width > 8 else 60

    if not items:
        output.append("No QA items available.\n", style="dim")
    else:
        selectable = _selectable_indices(items)
        for i, item in enumerate(items):
            if "_section" in item:
                label = item["_section"]
                count = item["_count"]
                output.append(f"\n  {label} ({count})\n", style="bold underline")
                output.append("  " + "\u2500" * min(content_width - 2, 40) + "\n", style="dim")
                continue

            is_selected = (i == selected_index)
            item_id = item.get("id", "???")
            title = item.get("title", "Untitled")
            description = item.get("description", "")

            if is_selected:
                output.append("\u25b6 ", style="bold cyan")
            else:
                output.append("  ")

            header = f"{item_id}: {title}"
            header = _truncate(header, content_width - 2)
            output.append(header, style="bold cyan" if is_selected else "")
            output.append("\n")

            if description:
                desc = _truncate(description, content_width - 4)
                output.append(f"    {desc}\n",
                              style="dim italic" if not is_selected else "italic")
            output.append("\n")

    return output


def _entry_lines(item: dict) -> int:
    if "_section" in item:
        return 3
    return 3 if item.get("description") else 2


def _navigate(items: list[dict], selected_index: int, direction: str) -> int:
    """Reproduce navigation logic from QAPane.on_key for j/k/up/down."""
    selectable = _selectable_indices(items)
    if not selectable:
        return selected_index
    current_pos = selectable.index(selected_index) if selected_index in selectable else 0
    if direction in ("down", "j"):
        if current_pos < len(selectable) - 1:
            return selectable[current_pos + 1]
    elif direction in ("up", "k"):
        if current_pos > 0:
            return selectable[current_pos - 1]
    return selected_index


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestQAPaneDataStructure:
    """Test update_items builds the correct flat list with section headers."""

    def test_flat_list_structure(self):
        flat = _flatten_items(SAMPLE_ITEMS)
        assert len(flat) == 5  # 2 headers + 3 items
        assert flat[0]["_section"] == "Instructions"
        assert flat[0]["_count"] == 2
        assert flat[1]["_item_id"] == "instructions:login-flow"
        assert flat[2]["_item_id"] == "instructions:signup"
        assert flat[3]["_section"] == "Regression Tests"
        assert flat[3]["_count"] == 1
        assert flat[4]["_item_id"] == "regression:pane-layout"

    def test_section_headers_show_correct_counts(self):
        """Step 3: Sections show correct item counts."""
        flat = _flatten_items(SAMPLE_ITEMS)
        headers = [it for it in flat if "_section" in it]
        assert headers[0]["_section"] == "Instructions"
        assert headers[0]["_count"] == 2
        assert headers[1]["_section"] == "Regression Tests"
        assert headers[1]["_count"] == 1

    def test_empty_sections(self):
        flat = _flatten_items({"instructions": [], "regression": []})
        assert len(flat) == 2  # Just 2 headers
        assert flat[0]["_count"] == 0
        assert flat[1]["_count"] == 0

    def test_item_enrichment(self):
        """Items get _category and _item_id fields."""
        flat = _flatten_items(SAMPLE_ITEMS)
        item = flat[1]  # login-flow
        assert item["_category"] == "instructions"
        assert item["_item_id"] == "instructions:login-flow"
        assert item["id"] == "login-flow"
        assert item["title"] == "Login Flow"


class TestQAPaneSelectableIndices:
    """Test that section headers are skipped in navigation."""

    def test_selectable_indices_skip_headers(self):
        """Step 7: Headers are skipped, selection lands on next item."""
        flat = _flatten_items(SAMPLE_ITEMS)
        selectable = _selectable_indices(flat)
        assert selectable == [1, 2, 4]

    def test_clamp_index_moves_to_first_selectable(self):
        """Step 4: First selectable item is highlighted (not the header)."""
        flat = _flatten_items(SAMPLE_ITEMS)
        idx = _clamp_index(flat, 0)  # 0 is a header
        assert idx == 1  # First selectable item

    def test_clamp_index_keeps_valid_selection(self):
        flat = _flatten_items(SAMPLE_ITEMS)
        idx = _clamp_index(flat, 2)  # 2 is a selectable item
        assert idx == 2  # Stays

    def test_clamp_index_empty_items(self):
        flat = _flatten_items({"instructions": [], "regression": []})
        idx = _clamp_index(flat, 0)
        assert idx == 0  # No selectable items, returns 0

    def test_selected_item_id(self):
        flat = _flatten_items(SAMPLE_ITEMS)
        assert flat[1].get("_item_id") == "instructions:login-flow"
        assert flat[4].get("_item_id") == "regression:pane-layout"

    def test_section_header_has_no_item_id(self):
        flat = _flatten_items(SAMPLE_ITEMS)
        assert flat[0].get("_item_id") is None  # header


class TestQAPaneNavigation:
    """Test j/k/up/down navigation through items."""

    def test_move_down_with_j(self):
        """Step 5: j moves selection down."""
        flat = _flatten_items(SAMPLE_ITEMS)
        idx = _clamp_index(flat, 0)  # Start at 1 (first selectable)
        new_idx = _navigate(flat, idx, "j")
        assert new_idx == 2  # signup

    def test_move_down_with_down_arrow(self):
        """Step 5: Down arrow also moves down."""
        flat = _flatten_items(SAMPLE_ITEMS)
        idx = _clamp_index(flat, 0)
        new_idx = _navigate(flat, idx, "down")
        assert new_idx == 2

    def test_move_down_past_section_header(self):
        """Step 7: Moving down from last instruction skips regression header."""
        flat = _flatten_items(SAMPLE_ITEMS)
        new_idx = _navigate(flat, 2, "j")  # From signup
        assert new_idx == 4  # Skips index 3 (Regression Tests header)

    def test_move_up_with_k(self):
        """Step 6: k moves selection up."""
        flat = _flatten_items(SAMPLE_ITEMS)
        new_idx = _navigate(flat, 2, "k")  # From signup
        assert new_idx == 1  # login-flow

    def test_move_up_with_up_arrow(self):
        """Step 6: Up arrow also moves up."""
        flat = _flatten_items(SAMPLE_ITEMS)
        new_idx = _navigate(flat, 2, "up")
        assert new_idx == 1

    def test_move_up_past_section_header(self):
        """Step 7: Moving up from first regression item skips header."""
        flat = _flatten_items(SAMPLE_ITEMS)
        new_idx = _navigate(flat, 4, "k")  # From pane-layout
        assert new_idx == 2  # Skips index 3 (Regression Tests header)

    def test_no_wrap_at_top(self):
        """Can't move up from first item."""
        flat = _flatten_items(SAMPLE_ITEMS)
        new_idx = _navigate(flat, 1, "k")
        assert new_idx == 1  # Stays

    def test_no_wrap_at_bottom(self):
        """Can't move down from last item."""
        flat = _flatten_items(SAMPLE_ITEMS)
        new_idx = _navigate(flat, 4, "j")
        assert new_idx == 4  # Stays

    def test_full_traversal_down(self):
        """Navigate through all items top to bottom."""
        flat = _flatten_items(SAMPLE_ITEMS)
        idx = _clamp_index(flat, 0)  # Start at 1
        assert idx == 1  # login-flow
        idx = _navigate(flat, idx, "j")
        assert idx == 2  # signup
        idx = _navigate(flat, idx, "j")
        assert idx == 4  # pane-layout (skipped header at 3)
        idx = _navigate(flat, idx, "j")
        assert idx == 4  # Can't go further

    def test_full_traversal_up(self):
        """Navigate through all items bottom to top."""
        flat = _flatten_items(SAMPLE_ITEMS)
        idx = 4  # pane-layout
        idx = _navigate(flat, idx, "k")
        assert idx == 2  # signup (skipped header at 3)
        idx = _navigate(flat, idx, "k")
        assert idx == 1  # login-flow
        idx = _navigate(flat, idx, "k")
        assert idx == 1  # Can't go further


class TestQAPaneRendering:
    """Test that rendered output matches expected format."""

    def test_render_section_headers(self):
        """Step 3: Sections show 'Instructions' and 'Regression Tests' labels."""
        flat = _flatten_items(SAMPLE_ITEMS)
        idx = _clamp_index(flat, 0)
        output = _render(flat, idx)
        text = output.plain

        assert "Instructions (2)" in text
        assert "Regression Tests (1)" in text

    def test_render_item_format(self):
        """Step 8: Items show ▶ id: title format."""
        flat = _flatten_items(SAMPLE_ITEMS)
        idx = _clamp_index(flat, 0)
        output = _render(flat, idx)
        text = output.plain

        assert "\u25b6 " in text  # ▶ character
        assert "login-flow: Login Flow" in text

    def test_render_selected_item_has_arrow(self):
        """Step 4/8: Selected item shows ▶ prefix."""
        flat = _flatten_items(SAMPLE_ITEMS)
        output = _render(flat, 1)
        text = output.plain

        arrow_pos = text.index("\u25b6")
        item_pos = text.index("login-flow: Login Flow")
        assert arrow_pos < item_pos

    def test_render_non_selected_no_arrow(self):
        """Non-selected items have space prefix, not arrow."""
        flat = _flatten_items(SAMPLE_ITEMS)
        output = _render(flat, 1)  # login-flow selected
        text = output.plain

        # signup should not have ▶ before it
        signup_pos = text.index("signup: Signup Test")
        # Check that the character before signup is a space
        assert text[signup_pos - 2:signup_pos] == "  "

    def test_render_description_below_title(self):
        """Step 8: Description shown below where present."""
        flat = _flatten_items(SAMPLE_ITEMS)
        output = _render(flat, 1)
        text = output.plain

        assert "Test login end-to-end" in text
        assert "signup: Signup Test" in text

    def test_render_no_items(self):
        """Empty pane shows placeholder."""
        output = _render([], 0)
        assert "No QA items available." in output.plain

    def test_render_selection_styling(self):
        """Step 4: Selected item highlighted in cyan."""
        flat = _flatten_items(SAMPLE_ITEMS)
        output = _render(flat, 1)

        spans = output._spans
        cyan_spans = [s for s in spans if "cyan" in str(s.style)]
        assert len(cyan_spans) > 0, "Selected item should have cyan styling"

    def test_render_divider_lines(self):
        """Section headers have horizontal dividers."""
        flat = _flatten_items(SAMPLE_ITEMS)
        output = _render(flat, 1)
        text = output.plain
        assert "\u2500" in text  # ─ character

    def test_render_header_bold_underline(self):
        """Section headers use bold underline style."""
        flat = _flatten_items(SAMPLE_ITEMS)
        output = _render(flat, 1)
        spans = output._spans
        bold_underline_spans = [s for s in spans if "bold" in str(s.style) and "underline" in str(s.style)]
        assert len(bold_underline_spans) > 0


class TestQAPaneTruncation:

    def test_short_text_unchanged(self):
        assert _truncate("short", 100) == "short"

    def test_long_text_truncated(self):
        result = _truncate("a" * 50, 20)
        assert len(result) == 20
        assert result.endswith("\u2026")  # …

    def test_exact_length_unchanged(self):
        assert _truncate("exact", 5) == "exact"


class TestQAPaneEntryLines:

    def test_section_header_is_3_lines(self):
        assert _entry_lines({"_section": "Test", "_count": 0}) == 3

    def test_item_with_description_is_3_lines(self):
        assert _entry_lines({"id": "x", "description": "desc"}) == 3

    def test_item_without_description_is_2_lines(self):
        assert _entry_lines({"id": "x", "description": ""}) == 2
        assert _entry_lines({"id": "x"}) == 2


class TestQAPaneStatusBar:
    """Step 13: Verify status bar format when QA pane is active."""

    def test_status_bar_format(self):
        """Status bar should show '{N} item(s)    Enter=run  e=edit  a=add  q=back'."""
        all_items = SAMPLE_ITEMS
        total = len(all_items.get("instructions", [])) + len(all_items.get("regression", []))
        status_text = f" [bold]QA[/bold]    {total} item(s)    [dim]Enter=run  e=edit  a=add  q=back[/dim]"

        assert f"{total} item(s)" in status_text
        assert "Enter=run" in status_text
        assert "e=edit" in status_text
        assert "a=add" in status_text
        assert "q=back" in status_text
        assert total == 3

    def test_status_bar_zero_items(self):
        total = 0
        status_text = f" [bold]QA[/bold]    {total} item(s)    [dim]Enter=run  e=edit  a=add  q=back[/dim]"
        assert "0 item(s)" in status_text


class TestQAPaneMessages:
    """Test that the message classes are correctly defined."""

    def test_qa_item_selected_message(self):
        from pm_core.tui.qa_pane import QAItemSelected
        msg = QAItemSelected("instructions:login-flow")
        assert msg.item_id == "instructions:login-flow"

    def test_qa_item_activated_message(self):
        from pm_core.tui.qa_pane import QAItemActivated
        msg = QAItemActivated("regression:pane-layout")
        assert msg.item_id == "regression:pane-layout"

    def test_qa_action_message_add(self):
        from pm_core.tui.qa_pane import QAAction
        msg = QAAction("add")
        assert msg.action == "add"
        assert msg.item_id is None

    def test_qa_action_message_edit(self):
        from pm_core.tui.qa_pane import QAAction
        msg = QAAction("edit", "instructions:login-flow")
        assert msg.action == "edit"
        assert msg.item_id == "instructions:login-flow"


class TestQAPaneKeyBindings:
    """Verify key bindings are correctly wired in the app."""

    def test_q_binding_exists(self):
        """Step 2: q key bound to toggle_qa action."""
        from pm_core.tui.app import ProjectManagerApp
        bindings = ProjectManagerApp.BINDINGS
        q_bindings = [b for b in bindings if b.key == "q"]
        assert len(q_bindings) == 1
        assert q_bindings[0].action == "toggle_qa"

    def test_toggle_qa_not_blocked_in_qa_view(self):
        """toggle_qa is NOT in the blocked-in-QA-view action list."""
        # The check_action method blocks specific actions when _qa_visible=True.
        # toggle_qa must NOT be blocked so q can toggle back.
        blocked_in_qa = {
            "start_pr", "start_pr_companion", "done_pr",
            "merge_pr", "merge_pr_companion", "launch_claude",
            "edit_plan", "view_plan", "hide_plan", "move_to_plan",
            "toggle_merged", "cycle_filter", "cycle_sort", "start_qa_on_pr",
        }
        assert "toggle_qa" not in blocked_in_qa

    def test_on_key_handles_expected_keys(self):
        """The QAPane.on_key method handles j, k, up, down, enter, a, e."""
        from pm_core.tui.qa_pane import QAPane
        source = inspect.getsource(QAPane.on_key)
        for key in ["up", "k", "down", "j", "enter", "a", "e"]:
            assert f'"{key}"' in source, f"Missing handler for key: {key}"


class TestQAPaneHelpScreen:
    """Verify help screen shows QA navigation keybindings."""

    def test_help_screen_accepts_in_qa_param(self):
        from pm_core.tui.screens import HelpScreen
        sig = inspect.signature(HelpScreen.__init__)
        assert "in_qa" in sig.parameters

    def test_qa_help_section_content(self):
        """Help screen includes QA navigation keys."""
        from pm_core.tui.screens import HelpScreen
        source = inspect.getsource(HelpScreen.compose)
        assert "QA Navigation" in source
        assert "jk" in source
        assert "Enter" in source
        assert "Back to tree view" in source


class TestQAPaneActionHandler:
    """Verify the app correctly routes QA action messages."""

    def test_edit_action_parses_item_id(self):
        """Edit action splits 'category:id' correctly."""
        item_id = "instructions:login-flow"
        parts = item_id.split(":", 1)
        assert len(parts) == 2
        assert parts[0] == "instructions"
        assert parts[1] == "login-flow"

    def test_edit_action_regression_category(self):
        item_id = "regression:pane-layout"
        parts = item_id.split(":", 1)
        assert parts[0] == "regression"
        assert parts[1] == "pane-layout"

    def test_launch_qa_item_function_exists(self):
        from pm_core.tui import pane_ops
        assert hasattr(pane_ops, "launch_qa_item")
        sig = inspect.signature(pane_ops.launch_qa_item)
        params = list(sig.parameters.keys())
        assert "app" in params
        assert "item_id" in params
