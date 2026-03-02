"""Tests for tree layout algorithm and TUI message factory."""

from pm_core.graph import count_crossings
from pm_core.tui import item_message
from pm_core.tui.tree_layout import (
    compute_tree_layout, TreeLayout, _activity_sort_key,
    _find_connected_components, _NODE_W, _H_GAP, COMPONENT_GAP_CHARS,
)


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
        # x_char = margin (2) + col_idx (0) * COL_WIDTH (30) = 2
        assert layout.node_positions["pr-a"] == (2, 0)


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
        # x_char positions: margin=2, COL_WIDTH=30
        cols = [self.layout.node_positions[pid][0] for pid in self.layout.ordered_ids]
        assert cols == [2, 32, 62]

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
        assert self.layout.node_positions["pr-a"][0] == 2  # margin

    def test_children_column_one(self):
        assert self.layout.node_positions["pr-b"][0] == 32  # margin + COL_WIDTH
        assert self.layout.node_positions["pr-c"][0] == 32

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
        assert self.layout.node_positions["pr-a"][0] == 2   # layer 0
        assert self.layout.node_positions["pr-b"][0] == 32  # layer 1
        assert self.layout.node_positions["pr-c"][0] == 32  # layer 1
        assert self.layout.node_positions["pr-d"][0] == 62  # layer 2

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

    def test_shared_parents_siblings_adjacent(self):
        """Two siblings sharing both parents should be adjacent, not split.

        This tests the "best-of-sweeps" fix: forward sweeps correctly group
        siblings but backward sweeps can undo this when all siblings share
        the same children.  Without tracking the best ordering, the final
        backward sweep leaves a worse ordering.

            R1   R2            R1   R2
           / \\  /            / \\   |
          A   B  C           A   B  C
          |   |              |   |  |
          D   |   E          D   |  E
           \\ | /              \\  | /
             F                  F

        A and B depend on R1; C depends on R2.
        D depends on A; E depends on B+C; F depends on D+E.
        Without fix: E placed between D and C, creating crossings.
        """
        prs = [
            _pr("pr-r1"),
            _pr("pr-r2"),
            _pr("pr-a", depends_on=["pr-r1"]),
            _pr("pr-b", depends_on=["pr-r1"]),
            _pr("pr-c", depends_on=["pr-r2"]),
            _pr("pr-d", depends_on=["pr-a"]),
            _pr("pr-e", depends_on=["pr-b", "pr-c"]),
            _pr("pr-f", depends_on=["pr-d", "pr-e"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == 0

    def test_sweep_oscillation_keeps_best(self):
        """Regression test: backward sweep must not undo forward improvements.

        K2,2 siblings (aa, cc) sharing parents (p1, p2) with a third
        node (bb) on a different chain but whose ID sorts between them.
        The backward sweep gives all three the same child barycenter and
        re-sorts alphabetically, splitting the siblings apart.

            R1     R2
           / \\    /
          P1  P2  P3
         / \\  |   |
        aa  cc bb  (aa+cc share P1+P2; bb depends on P3)
          \\  | /
            M1
        """
        prs = [
            _pr("pr-r1"),
            _pr("pr-r2"),
            _pr("pr-p1", depends_on=["pr-r1"]),
            _pr("pr-p2", depends_on=["pr-r1"]),
            _pr("pr-p3", depends_on=["pr-r1", "pr-r2"]),
            _pr("pr-aa", depends_on=["pr-p1", "pr-p2"]),
            _pr("pr-cc", depends_on=["pr-p1", "pr-p2"]),
            _pr("pr-bb", depends_on=["pr-p3"]),
            _pr("pr-m1", depends_on=["pr-aa", "pr-cc", "pr-bb"]),
        ]
        layout = compute_tree_layout(prs)
        crossings = count_crossings(layout.node_positions, prs)
        # K2,2 has 1 unavoidable crossing; must not have extra
        assert crossings <= 1
        # aa and cc must be adjacent (both share parents p1+p2)
        row_aa = layout.node_positions["pr-aa"][1]
        row_cc = layout.node_positions["pr-cc"][1]
        assert abs(row_aa - row_cc) == 1


# ---------------------------------------------------------------------------
# Brute-force optimality tests
# ---------------------------------------------------------------------------


def _brute_force_min_crossings(prs):
    """Compute the minimum possible crossings by trying all layer permutations.

    For each layer, try every permutation of nodes.  For each combination
    of permutations across layers, count the crossings and return the
    minimum.  This is O(product(n_i!) for each layer i) — only feasible
    for small graphs.
    """
    from itertools import permutations, product
    from pm_core.graph import compute_layers

    layers = compute_layers(prs)
    pr_ids = set(p["id"] for p in prs)
    parents_of = {}
    for pr in prs:
        parents_of[pr["id"]] = [d for d in (pr.get("depends_on") or []) if d in pr_ids]

    # Generate all possible orderings per layer
    layer_perms = [list(permutations(layer)) for layer in layers]

    best = float("inf")
    for combo in product(*layer_perms):
        # Build ordinal positions
        ordinal = {}
        for layer in combo:
            for i, node in enumerate(layer):
                ordinal[node] = i

        # Count crossings between adjacent layers
        crossings = 0
        for col in range(1, len(combo)):
            edges = []
            for node in combo[col]:
                for parent in parents_of.get(node, []):
                    if parent in ordinal:
                        edges.append((ordinal[parent], ordinal[node]))
            for i in range(len(edges)):
                for j in range(i + 1, len(edges)):
                    if (edges[i][0] - edges[j][0]) * (edges[i][1] - edges[j][1]) < 0:
                        crossings += 1
            if crossings >= best:
                break  # prune
        best = min(best, crossings)

    return best


class TestBruteForceOptimality:
    """Verify the heuristic matches brute-force optimal on small graphs."""

    def test_linear_chain(self):
        prs = [_pr("pr-a"), _pr("pr-b", depends_on=["pr-a"]), _pr("pr-c", depends_on=["pr-b"])]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == _brute_force_min_crossings(prs)

    def test_diamond(self):
        prs = [
            _pr("pr-a"),
            _pr("pr-b", depends_on=["pr-a"]),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-b", "pr-c"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == _brute_force_min_crossings(prs)

    def test_w_graph(self):
        prs = [
            _pr("pr-a"), _pr("pr-b"),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-a", "pr-b"]),
            _pr("pr-e", depends_on=["pr-b"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == _brute_force_min_crossings(prs)

    def test_two_chains(self):
        prs = [
            _pr("pr-a"), _pr("pr-b"),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-b"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == _brute_force_min_crossings(prs)

    def test_reverse_dep_order(self):
        """A(row 0)→D, B(row 1)→C — requires reordering to avoid crossing."""
        prs = [
            _pr("pr-a"), _pr("pr-b"),
            _pr("pr-c", depends_on=["pr-b"]),
            _pr("pr-d", depends_on=["pr-a"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == _brute_force_min_crossings(prs)

    def test_fan_in(self):
        prs = [
            _pr("pr-a"), _pr("pr-b"), _pr("pr-c"),
            _pr("pr-d", depends_on=["pr-a", "pr-b", "pr-c"]),
        ]
        layout = compute_tree_layout(prs)
        assert count_crossings(layout.node_positions, prs) == _brute_force_min_crossings(prs)

    def test_k22_with_third_chain(self):
        """The food project pattern — K2,2 plus a separate chain.

        Brute force confirms the minimum is 1 (K2,2 unavoidable).
        """
        prs = [
            _pr("pr-r1"), _pr("pr-r2"),
            _pr("pr-p1", depends_on=["pr-r1"]),
            _pr("pr-p2", depends_on=["pr-r1"]),
            _pr("pr-p3", depends_on=["pr-r1", "pr-r2"]),
            _pr("pr-aa", depends_on=["pr-p1", "pr-p2"]),
            _pr("pr-cc", depends_on=["pr-p1", "pr-p2"]),
            _pr("pr-bb", depends_on=["pr-p3"]),
            _pr("pr-m1", depends_on=["pr-aa", "pr-cc", "pr-bb"]),
        ]
        layout = compute_tree_layout(prs)
        heuristic = count_crossings(layout.node_positions, prs)
        optimal = _brute_force_min_crossings(prs)
        assert heuristic == optimal, f"heuristic={heuristic} > optimal={optimal}"

    def test_complex_test_graph(self):
        """12-node graph from plan-tl-test with 6 layers."""
        prs = [
            _pr("pr-tl01"), _pr("pr-tl02"),
            _pr("pr-tl03", depends_on=["pr-tl01"]),
            _pr("pr-tl04", depends_on=["pr-tl01"]),
            _pr("pr-tl05", depends_on=["pr-tl02", "pr-tl03"]),
            _pr("pr-tl06", depends_on=["pr-tl02", "pr-tl04"]),
            _pr("pr-tl07", depends_on=["pr-tl04"]),
            _pr("pr-tl08", depends_on=["pr-tl03", "pr-tl05"]),
            _pr("pr-tl09", depends_on=["pr-tl05", "pr-tl06", "pr-tl07"]),
            _pr("pr-tl10", depends_on=["pr-tl06"]),
            _pr("pr-tl11", depends_on=["pr-tl08", "pr-tl09"]),
            _pr("pr-tl12", depends_on=["pr-tl10", "pr-tl11"]),
        ]
        layout = compute_tree_layout(prs)
        heuristic = count_crossings(layout.node_positions, prs)
        optimal = _brute_force_min_crossings(prs)
        assert heuristic == optimal, f"heuristic={heuristic} > optimal={optimal}"


# ---------------------------------------------------------------------------
# Activity sort key tests
# ---------------------------------------------------------------------------


class TestActivitySortKey:
    """Tests for the _activity_sort_key used in crossing minimization seeding."""

    def test_status_priority_order(self):
        """in_progress < in_review < pending < merged < closed."""
        pr_map = {
            "a": {"id": "a", "status": "closed"},
            "b": {"id": "b", "status": "in_progress"},
            "c": {"id": "c", "status": "pending"},
            "d": {"id": "d", "status": "merged"},
            "e": {"id": "e", "status": "in_review"},
        }
        keys = {pid: _activity_sort_key(pid, pr_map) for pid in pr_map}
        ordered = sorted(pr_map.keys(), key=lambda pid: keys[pid])
        assert ordered == ["b", "e", "c", "d", "a"]

    def test_recent_timestamp_sorts_first(self):
        """Within the same status, more recent timestamps should sort first."""
        pr_map = {
            "old": {"id": "old", "status": "in_progress",
                    "started_at": "2024-01-01T00:00:00+00:00"},
            "new": {"id": "new", "status": "in_progress",
                    "started_at": "2024-06-15T00:00:00+00:00"},
        }
        key_old = _activity_sort_key("old", pr_map)
        key_new = _activity_sort_key("new", pr_map)
        assert key_new < key_old, "More recent timestamp should sort first"

    def test_timestamp_before_no_timestamp(self):
        """PRs with timestamps should sort before PRs without timestamps."""
        pr_map = {
            "with_ts": {"id": "with_ts", "status": "pending",
                        "started_at": "2024-01-01T00:00:00+00:00"},
            "no_ts": {"id": "no_ts", "status": "pending"},
        }
        key_with = _activity_sort_key("with_ts", pr_map)
        key_without = _activity_sort_key("no_ts", pr_map)
        assert key_with < key_without, "PR with timestamp should sort before PR without"

    def test_missing_pr_sorts_last(self):
        """Unknown PR IDs should sort after all known statuses."""
        pr_map = {"known": {"id": "known", "status": "closed"}}
        key_known = _activity_sort_key("known", pr_map)
        key_unknown = _activity_sort_key("unknown", pr_map)
        assert key_known < key_unknown

    def test_uses_most_recent_timestamp(self):
        """Default chain: updated_at > merged_at > reviewed_at > started_at > created_at."""
        pr_map = {
            "pr": {"id": "pr", "status": "merged",
                   "started_at": "2024-01-01T00:00:00+00:00",
                   "reviewed_at": "2024-03-01T00:00:00+00:00",
                   "merged_at": "2024-06-01T00:00:00+00:00"},
            "pr2": {"id": "pr2", "status": "merged",
                    "started_at": "2024-01-01T00:00:00+00:00",
                    "reviewed_at": "2024-03-01T00:00:00+00:00"},
        }
        # pr has merged_at (most recent), pr2 only has reviewed_at
        # So pr should sort before pr2 (merged_at is more recent)
        key1 = _activity_sort_key("pr", pr_map)
        key2 = _activity_sort_key("pr2", pr_map)
        assert key1 < key2

    def test_updated_at_takes_priority(self):
        """updated_at should be preferred over other timestamps."""
        pr_map = {
            "pr_updated": {"id": "pr_updated", "status": "in_progress",
                           "updated_at": "2024-06-01T00:00:00+00:00",
                           "started_at": "2024-01-01T00:00:00+00:00"},
            "pr_old": {"id": "pr_old", "status": "in_progress",
                       "started_at": "2024-05-01T00:00:00+00:00"},
        }
        key_updated = _activity_sort_key("pr_updated", pr_map)
        key_old = _activity_sort_key("pr_old", pr_map)
        assert key_updated < key_old

    def test_created_at_fallback(self):
        """created_at is used when no other timestamps are set."""
        pr_map = {
            "new": {"id": "new", "status": "pending",
                    "created_at": "2024-06-01T00:00:00+00:00"},
            "old": {"id": "old", "status": "pending",
                    "created_at": "2024-01-01T00:00:00+00:00"},
        }
        key_new = _activity_sort_key("new", pr_map)
        key_old = _activity_sort_key("old", pr_map)
        assert key_new < key_old

    def test_sort_field_parameter(self):
        """sort_field restricts sorting to a specific timestamp field."""
        pr_map = {
            "pr_a": {"id": "pr_a", "status": "in_review",
                     "started_at": "2024-06-01T00:00:00+00:00",
                     "reviewed_at": "2024-01-01T00:00:00+00:00"},
            "pr_b": {"id": "pr_b", "status": "in_review",
                     "started_at": "2024-01-01T00:00:00+00:00",
                     "reviewed_at": "2024-06-01T00:00:00+00:00"},
        }
        # With sort_field="started_at", pr_a (June) should sort before pr_b (Jan)
        key_a = _activity_sort_key("pr_a", pr_map, sort_field="started_at")
        key_b = _activity_sort_key("pr_b", pr_map, sort_field="started_at")
        assert key_a < key_b
        # With sort_field="reviewed_at", pr_b (June) should sort before pr_a (Jan)
        key_a = _activity_sort_key("pr_a", pr_map, sort_field="reviewed_at")
        key_b = _activity_sort_key("pr_b", pr_map, sort_field="reviewed_at")
        assert key_b < key_a


# ---------------------------------------------------------------------------
# Connected components tests
# ---------------------------------------------------------------------------


class TestConnectedComponents:
    """Tests for _find_connected_components."""

    def test_single_pr(self):
        prs = [_pr("pr-a")]
        comps = _find_connected_components(prs, {"pr-a"})
        assert len(comps) == 1
        assert comps[0][0]["id"] == "pr-a"

    def test_two_independent(self):
        prs = [_pr("pr-a"), _pr("pr-b")]
        comps = _find_connected_components(prs, {"pr-a", "pr-b"})
        assert len(comps) == 2

    def test_chain_is_one_component(self):
        prs = [_pr("pr-a"), _pr("pr-b", depends_on=["pr-a"])]
        comps = _find_connected_components(prs, {"pr-a", "pr-b"})
        assert len(comps) == 1
        ids = {pr["id"] for pr in comps[0]}
        assert ids == {"pr-a", "pr-b"}

    def test_diamond_is_one_component(self):
        prs = [
            _pr("pr-a"),
            _pr("pr-b", depends_on=["pr-a"]),
            _pr("pr-c", depends_on=["pr-a"]),
            _pr("pr-d", depends_on=["pr-b", "pr-c"]),
        ]
        comps = _find_connected_components(prs, {p["id"] for p in prs})
        assert len(comps) == 1

    def test_ignores_deps_outside_pr_ids(self):
        """Dependencies on filtered-out PRs should not merge components."""
        prs = [_pr("pr-a"), _pr("pr-b", depends_on=["pr-z"])]
        comps = _find_connected_components(prs, {"pr-a", "pr-b"})
        assert len(comps) == 2


# ---------------------------------------------------------------------------
# Component packing / max_width tests
# ---------------------------------------------------------------------------


class TestComponentPacking:
    """Tests for side-by-side component layout and max_width wrapping."""

    def test_independent_prs_side_by_side(self):
        """Two independent PRs should be placed in the same row band."""
        prs = [_pr("pr-a"), _pr("pr-b")]
        layout = compute_tree_layout(prs, max_width=200)
        row_a = layout.node_positions["pr-a"][1]
        row_b = layout.node_positions["pr-b"][1]
        assert row_a == row_b, "Independent PRs should share a row when width allows"

    def test_side_by_side_x_gap(self):
        """Side-by-side independent PRs have COMPONENT_GAP_CHARS between them."""
        prs = [_pr("pr-a"), _pr("pr-b")]
        layout = compute_tree_layout(prs, max_width=200)
        x_a = layout.node_positions["pr-a"][0]
        x_b = layout.node_positions["pr-b"][0]
        # Second node's x should be: first node's x + NODE_W + COMPONENT_GAP_CHARS
        if x_a < x_b:
            gap = x_b - (x_a + _NODE_W)
        else:
            gap = x_a - (x_b + _NODE_W)
        assert gap == COMPONENT_GAP_CHARS

    def test_wraps_to_new_row_when_too_wide(self):
        """Components that exceed max_width should wrap to a new row band."""
        prs = [_pr("pr-a"), _pr("pr-b"), _pr("pr-c")]
        # Set max_width so only 2 single-node components fit side by side
        # Each node needs: margin(2) + NODE_W(24) = 26 for first,
        # + COMPONENT_GAP(12) + NODE_W(24) = 62 for second
        narrow_width = 65  # fits 2 but not 3
        layout = compute_tree_layout(prs, max_width=narrow_width)
        rows = [layout.node_positions[pid][1] for pid in ["pr-a", "pr-b", "pr-c"]]
        # At least two should share a row, and at least one should be different
        assert len(set(rows)) == 2, f"Expected 2 row bands, got rows={rows}"

    def test_no_max_width_all_side_by_side(self):
        """Without max_width, independent PRs should all be on the same row."""
        prs = [_pr(f"pr-{i}") for i in range(5)]
        layout = compute_tree_layout(prs, max_width=None)
        rows = {layout.node_positions[pid][1] for pid in layout.ordered_ids}
        assert len(rows) == 1, "All independent PRs should share a row without width limit"

    def test_connected_component_stays_together(self):
        """PRs in a dependency chain are in one component and not split."""
        prs = [
            _pr("pr-a"),
            _pr("pr-b", depends_on=["pr-a"]),
            _pr("pr-c"),  # independent
        ]
        layout = compute_tree_layout(prs, max_width=200)
        # pr-a and pr-b should be in different columns (layers)
        x_a = layout.node_positions["pr-a"][0]
        x_b = layout.node_positions["pr-b"][0]
        assert x_a != x_b, "Chained PRs should be in different columns"
        # pr-c should be side-by-side with the chain (same row band)
        row_a = layout.node_positions["pr-a"][1]
        row_c = layout.node_positions["pr-c"][1]
        assert row_a == row_c, "Independent PR should share row band with chain"
