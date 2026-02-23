"""Tests for tree layout algorithm and TUI message factory."""

from pm_core.graph import count_crossings
from pm_core.tui import item_message
from pm_core.tui.tree_layout import compute_tree_layout, TreeLayout


# ---------------------------------------------------------------------------
# Message factory tests
# ---------------------------------------------------------------------------

class TestItemMessage:
    """Tests for the item_message factory."""

    def test_returns_two_classes(self):
        sel, act = item_message("Foo", "foo_id")
        assert sel is not act

    def test_class_names(self):
        sel, act = item_message("Widget", "widget_id")
        assert sel.__name__ == "WidgetSelected"
        assert act.__name__ == "WidgetActivated"

    def test_handler_names(self):
        """Handler names must match Textual's CamelCase→snake_case conversion."""
        sel, act = item_message("PR", "pr_id")
        assert sel.handler_name == "on_prselected"
        assert act.handler_name == "on_practivated"

        sel2, act2 = item_message("Plan", "plan_id")
        assert sel2.handler_name == "on_plan_selected"
        assert act2.handler_name == "on_plan_activated"

        sel3, act3 = item_message("Test", "test_id")
        assert sel3.handler_name == "on_test_selected"
        assert act3.handler_name == "on_test_activated"

    def test_field_accessible(self):
        sel, act = item_message("Item", "item_id")
        msg = sel("abc-123")
        assert msg.item_id == "abc-123"
        msg2 = act("xyz-789")
        assert msg2.item_id == "xyz-789"

    def test_docstrings(self):
        sel, act = item_message("Plan", "plan_id")
        assert "selected" in sel.__doc__.lower()
        assert "enter" in act.__doc__.lower()

    def test_are_message_subclasses(self):
        from textual.message import Message
        sel, act = item_message("X", "x_id")
        assert issubclass(sel, Message)
        assert issubclass(act, Message)


# ---------------------------------------------------------------------------
# Tree layout tests
# ---------------------------------------------------------------------------

def _pr(pr_id, depends_on=None, status="pending", plan=None):
    """Helper to build a minimal PR dict."""
    d = {"id": pr_id, "status": status}
    if depends_on:
        d["depends_on"] = depends_on
    if plan:
        d["plan"] = plan
    return d


class TestEmptyInputs:
    def test_empty_list(self):
        layout = compute_tree_layout([])
        assert layout.ordered_ids == []
        assert layout.node_positions == {}

    def test_single_pr(self):
        layout = compute_tree_layout([_pr("pr-a")])
        assert layout.ordered_ids == ["pr-a"]
        assert layout.node_positions["pr-a"] == (0, 0)


class TestLinearChain:
    """A -> B -> C should place nodes in successive columns, same row."""

    def setup_method(self):
        self.prs = [
            _pr("pr-a"),
            _pr("pr-b", depends_on=["pr-a"]),
            _pr("pr-c", depends_on=["pr-b"]),
        ]
        self.layout = compute_tree_layout(self.prs)

    def test_order(self):
        assert self.layout.ordered_ids == ["pr-a", "pr-b", "pr-c"]

    def test_columns(self):
        cols = [self.layout.node_positions[pid][0] for pid in self.layout.ordered_ids]
        assert cols == [0, 1, 2]

    def test_same_row(self):
        rows = {self.layout.node_positions[pid][1] for pid in self.layout.ordered_ids}
        assert len(rows) == 1  # all on the same row


class TestFanOut:
    """A with two children B and C in the next column."""

    def setup_method(self):
        self.prs = [
            _pr("pr-a"),
            _pr("pr-b", depends_on=["pr-a"]),
            _pr("pr-c", depends_on=["pr-a"]),
        ]
        self.layout = compute_tree_layout(self.prs)

    def test_parent_column_zero(self):
        assert self.layout.node_positions["pr-a"][0] == 0

    def test_children_column_one(self):
        assert self.layout.node_positions["pr-b"][0] == 1
        assert self.layout.node_positions["pr-c"][0] == 1

    def test_children_different_rows(self):
        row_b = self.layout.node_positions["pr-b"][1]
        row_c = self.layout.node_positions["pr-c"][1]
        assert row_b != row_c

    def test_first_child_shares_parent_row(self):
        row_a = self.layout.node_positions["pr-a"][1]
        row_b = self.layout.node_positions["pr-b"][1]
        assert row_b == row_a


class TestDiamond:
    """A -> B, A -> C, B -> D, C -> D (diamond dependency)."""

    def setup_method(self):
        self.prs = [
            _pr("pr-a"),
            _pr("pr-b", depends_on=["pr-a"]),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-b", "pr-c"]),
        ]
        self.layout = compute_tree_layout(self.prs)

    def test_columns(self):
        assert self.layout.node_positions["pr-a"][0] == 0
        assert self.layout.node_positions["pr-b"][0] == 1
        assert self.layout.node_positions["pr-c"][0] == 1
        assert self.layout.node_positions["pr-d"][0] == 2

    def test_no_overlap(self):
        """No two nodes share the same (col, row) position."""
        positions = list(self.layout.node_positions.values())
        assert len(positions) == len(set(positions))


class TestFiltering:
    def test_status_filter(self):
        prs = [
            _pr("pr-a", status="pending"),
            _pr("pr-b", status="merged"),
        ]
        layout = compute_tree_layout(prs, status_filter="pending")
        assert "pr-a" in layout.ordered_ids
        assert "pr-b" not in layout.ordered_ids

    def test_hide_merged(self):
        prs = [
            _pr("pr-a", status="pending"),
            _pr("pr-b", status="merged"),
        ]
        layout = compute_tree_layout(prs, hide_merged=True)
        assert "pr-a" in layout.ordered_ids
        assert "pr-b" not in layout.ordered_ids

    def test_status_filter_overrides_hide_merged(self):
        """When filtering for 'merged', hide_merged should not apply."""
        prs = [
            _pr("pr-a", status="pending"),
            _pr("pr-b", status="merged"),
        ]
        layout = compute_tree_layout(prs, status_filter="merged", hide_merged=True)
        assert "pr-b" in layout.ordered_ids
        assert "pr-a" not in layout.ordered_ids

    def test_hidden_plans(self):
        prs = [
            _pr("pr-a", plan="plan-001"),
            _pr("pr-b", plan="plan-002"),
        ]
        layout = compute_tree_layout(prs, hidden_plans={"plan-001"})
        assert "pr-a" not in layout.ordered_ids
        assert "pr-b" in layout.ordered_ids

    def test_hidden_plan_labels(self):
        prs = [
            _pr("pr-a", plan="plan-001"),
            _pr("pr-b", plan="plan-002"),
        ]
        layout = compute_tree_layout(prs, hidden_plans={"plan-001"})
        assert "_hidden:plan-001" in layout.ordered_ids
        assert "plan-001" in layout.hidden_plan_label_rows
        assert "_hidden:plan-001" in layout.hidden_label_ids

    def test_all_filtered_returns_empty(self):
        prs = [_pr("pr-a", status="merged")]
        layout = compute_tree_layout(prs, status_filter="pending")
        assert layout.ordered_ids == []

    def test_hide_closed_by_default(self):
        """Closed PRs are hidden by default (hide_closed=True)."""
        prs = [
            _pr("pr-a", status="pending"),
            _pr("pr-b", status="closed"),
        ]
        layout = compute_tree_layout(prs)
        assert "pr-a" in layout.ordered_ids
        assert "pr-b" not in layout.ordered_ids

    def test_status_filter_closed_overrides_hide_closed(self):
        """Filtering for 'closed' shows closed PRs even with hide_closed=True."""
        prs = [
            _pr("pr-a", status="pending"),
            _pr("pr-b", status="closed"),
        ]
        layout = compute_tree_layout(prs, status_filter="closed")
        assert "pr-b" in layout.ordered_ids
        assert "pr-a" not in layout.ordered_ids

    def test_hide_closed_false_shows_closed(self):
        """Setting hide_closed=False shows closed PRs in the unfiltered view."""
        prs = [
            _pr("pr-a", status="pending"),
            _pr("pr-b", status="closed"),
        ]
        layout = compute_tree_layout(prs, hide_closed=False)
        assert "pr-a" in layout.ordered_ids
        assert "pr-b" in layout.ordered_ids


class TestPlanGrouping:
    def test_single_plan_no_labels(self):
        prs = [_pr("pr-a", plan="plan-001"), _pr("pr-b", plan="plan-001")]
        layout = compute_tree_layout(prs)
        assert layout.plan_label_rows == {}
        assert layout.plan_group_order == []

    def test_two_plans_produces_labels(self):
        prs = [
            _pr("pr-a", plan="plan-001"),
            _pr("pr-b", plan="plan-002"),
        ]
        layout = compute_tree_layout(prs)
        assert "plan-001" in layout.plan_label_rows
        assert "plan-002" in layout.plan_label_rows

    def test_standalone_comes_last(self):
        prs = [
            _pr("pr-a"),  # no plan → standalone
            _pr("pr-b", plan="plan-001"),
        ]
        layout = compute_tree_layout(prs)
        assert layout.plan_group_order[-1] == "_standalone"

    def test_plan_groups_ordered_by_id(self):
        prs = [
            _pr("pr-a", plan="plan-003"),
            _pr("pr-b", plan="plan-001"),
            _pr("pr-c", plan="plan-002"),
        ]
        layout = compute_tree_layout(prs)
        named = [g for g in layout.plan_group_order if g != "_standalone"]
        assert named == sorted(named)


class TestNoOverlap:
    """No two nodes should share the same position in any layout."""

    def test_wide_graph(self):
        """5 independent PRs (no deps) should all get unique positions."""
        prs = [_pr(f"pr-{i}") for i in range(5)]
        layout = compute_tree_layout(prs)
        positions = list(layout.node_positions.values())
        assert len(positions) == len(set(positions))

    def test_complex_graph(self):
        """Multiple roots with shared children."""
        prs = [
            _pr("pr-a"),
            _pr("pr-b"),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-a", "pr-b"]),
            _pr("pr-e", depends_on=["pr-c", "pr-d"]),
        ]
        layout = compute_tree_layout(prs)
        positions = list(layout.node_positions.values())
        assert len(positions) == len(set(positions))


# ---------------------------------------------------------------------------
# Crossing count utility tests
# ---------------------------------------------------------------------------


class TestCountCrossings:
    def test_no_edges(self):
        prs = [_pr("pr-a"), _pr("pr-b")]
        positions = {"pr-a": (0, 0), "pr-b": (0, 1)}
        assert count_crossings(positions, prs) == 0

    def test_parallel_edges_no_crossing(self):
        """A(row 0)→C(row 0), B(row 1)→D(row 1): parallel, no crossing."""
        prs = [
            _pr("pr-a"),
            _pr("pr-b"),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-b"]),
        ]
        positions = {"pr-a": (0, 0), "pr-b": (0, 1), "pr-c": (1, 0), "pr-d": (1, 1)}
        assert count_crossings(positions, prs) == 0

    def test_crossed_edges(self):
        """A(row 0)→D(row 1), B(row 1)→C(row 0): X-crossing."""
        prs = [
            _pr("pr-a"),
            _pr("pr-b"),
            _pr("pr-c", depends_on=["pr-b"]),
            _pr("pr-d", depends_on=["pr-a"]),
        ]
        positions = {"pr-a": (0, 0), "pr-b": (0, 1), "pr-c": (1, 0), "pr-d": (1, 1)}
        assert count_crossings(positions, prs) == 1

    def test_linear_chain_no_crossing(self):
        prs = [
            _pr("pr-a"),
            _pr("pr-b", depends_on=["pr-a"]),
            _pr("pr-c", depends_on=["pr-b"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == 0


# ---------------------------------------------------------------------------
# Crossing minimization tests
# ---------------------------------------------------------------------------


class TestCrossingMinimization:
    """Tests that the Sugiyama barycenter algorithm avoids crossings."""

    def test_interleaved_chains_no_crossing(self):
        """Two chains A→C and B→D should not cross.

        A naive alphabetical ordering could put C before D when their
        parent positions suggest otherwise.
        """
        prs = [
            _pr("pr-a"),
            _pr("pr-b"),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-b"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == 0
        # Horizontal edges: each child should share its parent's row
        assert layout.node_positions["pr-c"][1] == layout.node_positions["pr-a"][1]
        assert layout.node_positions["pr-d"][1] == layout.node_positions["pr-b"][1]

    def test_reverse_dep_order_no_crossing(self):
        """A(row 0)→D, B(row 1)→C — barycenter should order C before D.

        Without crossing minimization, alphabetical order puts C, D which
        could still work, but reversed parent order requires reordering.
        """
        prs = [
            _pr("pr-a"),
            _pr("pr-b"),
            _pr("pr-c", depends_on=["pr-b"]),
            _pr("pr-d", depends_on=["pr-a"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == 0

    def test_fan_in_no_crossing(self):
        """Multiple roots merging into one node should not cross."""
        prs = [
            _pr("pr-a"),
            _pr("pr-b"),
            _pr("pr-c"),
            _pr("pr-d", depends_on=["pr-a", "pr-b", "pr-c"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == 0

    def test_three_chains_no_crossing(self):
        """Three independent chains should all be horizontal."""
        prs = [
            _pr("pr-a"),
            _pr("pr-b"),
            _pr("pr-c"),
            _pr("pr-d", depends_on=["pr-a"]),
            _pr("pr-e", depends_on=["pr-b"]),
            _pr("pr-f", depends_on=["pr-c"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == 0
        # Each child on same row as parent
        for parent, child in [("pr-a", "pr-d"), ("pr-b", "pr-e"), ("pr-c", "pr-f")]:
            assert layout.node_positions[parent][1] == layout.node_positions[child][1]

    def test_w_graph_minimizes_crossings(self):
        """W-shaped graph: two roots each feeding into two shared children.

            A   B
           / \\ / \\
          C   D   E

        This is a case where naive ordering can produce crossings.
        """
        prs = [
            _pr("pr-a"),
            _pr("pr-b"),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-a", "pr-b"]),
            _pr("pr-e", depends_on=["pr-b"]),
        ]
        layout = compute_tree_layout(prs)
        crossings = count_crossings(layout.node_positions, prs)
        assert crossings == 0
        # D should be between C and E vertically
        row_c = layout.node_positions["pr-c"][1]
        row_d = layout.node_positions["pr-d"][1]
        row_e = layout.node_positions["pr-e"][1]
        assert min(row_c, row_e) <= row_d <= max(row_c, row_e)

    def test_diamond_zero_crossings(self):
        """Standard diamond A→B,C and B,C→D should have 0 crossings."""
        prs = [
            _pr("pr-a"),
            _pr("pr-b", depends_on=["pr-a"]),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-b", "pr-c"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == 0

    def test_backward_sweep_improves_root_order(self):
        """Backward sweep should reorder layer 0 based on child positions.

        Layer 0: [A, B, C]  (C connects to layer-1 node near A's children)
        The backward sweep should notice this and reorder accordingly.
        """
        prs = [
            _pr("pr-a"),
            _pr("pr-b"),
            _pr("pr-c"),
            _pr("pr-d", depends_on=["pr-a"]),
            _pr("pr-e", depends_on=["pr-c"]),
            _pr("pr-f", depends_on=["pr-d", "pr-e"]),
        ]
        layout = compute_tree_layout(prs)
        # No crossing is the goal
        assert count_crossings(layout.node_positions, prs) == 0

    def test_horizontal_edges_maximized(self):
        """In a simple tree, single-dependency edges should be horizontal."""
        #    A
        #   / \
        #  B   C
        #  |   |
        #  D   E
        prs = [
            _pr("pr-a"),
            _pr("pr-b", depends_on=["pr-a"]),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-b"]),
            _pr("pr-e", depends_on=["pr-c"]),
        ]
        layout = compute_tree_layout(prs)
        # B→D and C→E should be horizontal
        assert layout.node_positions["pr-b"][1] == layout.node_positions["pr-d"][1]
        assert layout.node_positions["pr-c"][1] == layout.node_positions["pr-e"][1]
        assert count_crossings(layout.node_positions, prs) == 0
