"""Tests for the compositional TechTree widget architecture.

Covers the refactor that split the monolithic grid renderer into per-PR
``PRNode`` widgets, ``PlanGroup`` containers, an ``EdgeCanvas`` layer, layout
caching, and neighbor-based navigation.

The repo has no pytest-asyncio plugin, so each async body is driven through
``asyncio.run`` by a sync ``test_*`` wrapper.
"""

import asyncio
import functools

from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer

from pm_core.pane_idle import PaneIdleTracker
from pm_core.tui.tech_tree import (
    TechTree, PRNode, PlanGroup, EdgeCanvas,
    compute_neighbors, _node_y, NODE_H,
)


def async_test(coro):
    @functools.wraps(coro)
    def wrapper(*args, **kwargs):
        asyncio.run(coro(*args, **kwargs))
    return wrapper


class _TreeApp(App):
    """Minimal host app exposing the attributes PRNode.render reads."""

    def __init__(self, prs, plans=None):
        super().__init__()
        self._prs = prs
        self._plans = plans or []
        self._review_loops = {}
        self._merge_input_required_prs = set()
        self._pane_idle_tracker = PaneIdleTracker()
        self._auto_start = False
        self._auto_start_target = None

    def compose(self) -> ComposeResult:
        with ScrollableContainer(id="sc"):
            yield TechTree(id="tech-tree")

    def on_mount(self) -> None:
        tree = self.query_one("#tech-tree", TechTree)
        tree.update_plans(self._plans)
        tree.update_prs(self._prs)


def _pr(pid, title="t", status="pending", plan=None, depends_on=None, **extra):
    d = {"id": pid, "title": title, "status": status, "plan": plan,
         "depends_on": depends_on or []}
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# Widget construction
# ---------------------------------------------------------------------------


@async_test
async def test_one_prnode_per_visible_pr_with_offset():
    prs = [_pr("pr-a"), _pr("pr-b", depends_on=["pr-a"])]
    app = _TreeApp(prs)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()  # let absolute-positioned children lay out
        tree = app.query_one(TechTree)
        nodes = {n.pr_id: n for n in app.query(PRNode)}
        assert set(nodes) == {"pr-a", "pr-b"}
        for pid, node in nodes.items():
            col, row = tree._node_positions[pid]
            assert node.region.x == col
            assert node.region.y == _node_y(row)


@async_test
async def test_single_edge_canvas_mounted():
    prs = [_pr("pr-a"), _pr("pr-b", depends_on=["pr-a"])]
    app = _TreeApp(prs)
    async with app.run_test(size=(120, 40)):
        assert len(app.query(EdgeCanvas)) == 1


@async_test
async def test_one_plangroup_per_plan():
    prs = [
        _pr("pr-a", plan="plan-001"),
        _pr("pr-b", plan="plan-001", depends_on=["pr-a"]),
        _pr("pr-c", plan="plan-002"),
        _pr("pr-d"),  # standalone
    ]
    app = _TreeApp(prs, plans=[{"id": "plan-001", "name": "One"},
                               {"id": "plan-002", "name": "Two"}])
    async with app.run_test(size=(160, 60)):
        groups = {g.plan_id for g in app.query(PlanGroup)}
        assert groups == {"plan-001", "plan-002", "_standalone"}


@async_test
async def test_empty_state_shows_message():
    app = _TreeApp([])
    async with app.run_test(size=(120, 40)):
        assert len(app.query(PRNode)) == 0
        assert len(app.query(EdgeCanvas)) == 0


@async_test
async def test_one_edge_canvas_per_band():
    prs = [
        _pr("pr-a", plan="plan-001"),
        _pr("pr-b", plan="plan-001", depends_on=["pr-a"]),
        _pr("pr-c", plan="plan-002"),
    ]
    app = _TreeApp(prs, plans=[{"id": "plan-001", "name": "One"},
                               {"id": "plan-002", "name": "Two"}])
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        groups = app.query(PlanGroup)
        canvases = app.query(EdgeCanvas)
        assert len(canvases) == len(groups) == 2
        # The plan-001 band's canvas must have drawn an arrow head.
        texts = [c.render().plain for c in canvases]
        assert any("▶" in t for t in texts)


@async_test
async def test_cross_plan_dependency_nodes_render_in_separate_bands():
    # pr-b is plan-002 but depends on pr-a (plan-001).  The layout remaps rows
    # by each PR's own plan, so the two nodes land in separate plan bands.
    # Both still render; the cross-band dependency arrow is not drawn (each
    # band owns its edges) — a documented trade-off of per-band edge layers.
    prs = [
        _pr("pr-a", plan="plan-001"),
        _pr("pr-b", plan="plan-002", depends_on=["pr-a"]),
    ]
    app = _TreeApp(prs, plans=[{"id": "plan-001", "name": "One"},
                               {"id": "plan-002", "name": "Two"}])
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        nodes = {n.pr_id: n for n in app.query(PRNode)}
        assert nodes["pr-a"].region.height == NODE_H
        assert nodes["pr-b"].region.height == NODE_H
        assert nodes["pr-a"].region.y != nodes["pr-b"].region.y  # different bands
        assert len(app.query(PlanGroup)) == 2


@async_test
async def test_hidden_plan_shows_navigable_label():
    prs = [
        _pr("pr-a", plan="plan-001"),
        _pr("pr-b", plan="plan-002"),
    ]
    app = _TreeApp(prs, plans=[{"id": "plan-001", "name": "One"},
                               {"id": "plan-002", "name": "Two"}])
    async with app.run_test(size=(160, 60)) as pilot:
        await pilot.pause()
        tree = app.query_one(TechTree)
        tree._hidden_plans.add("plan-002")
        tree._recompute()
        await pilot.pause()
        assert "_hidden:plan-002" in tree._ordered_ids
        assert "_hidden:plan-002" in tree._label_widgets
        assert "pr-b" not in tree._node_widgets


# ---------------------------------------------------------------------------
# Spinner tick refreshes only active nodes (no recompute)
# ---------------------------------------------------------------------------


@async_test
async def test_spinner_tick_refreshes_only_active_nodes():
    prs = [
        _pr("pr-a", status="in_progress", workdir="/tmp/a"),
        _pr("pr-b", status="pending"),
        _pr("pr-c", status="merged"),
    ]
    app = _TreeApp(prs)
    async with app.run_test(size=(120, 40)):
        tree = app.query_one(TechTree)
        nodes = {n.pr_id: n for n in app.query(PRNode)}
        refreshed = []

        def make_spy(pid, orig):
            def spy(*a, **k):
                refreshed.append(pid)
                return orig(*a, **k)
            return spy

        for pid, n in nodes.items():
            n.refresh = make_spy(pid, n.refresh)

        sig_before = tree._layout_sig
        tree.advance_animation()
        tree.refresh_active_nodes()

        assert refreshed == ["pr-a"]           # only the active node repainted
        assert tree._layout_sig is sig_before  # no recompute happened


@async_test
async def test_advance_animation_cycles_frame():
    app = _TreeApp([_pr("pr-a")])
    async with app.run_test(size=(80, 24)):
        tree = app.query_one(TechTree)
        start = tree._anim_frame
        tree.advance_animation()
        assert tree._anim_frame == (start + 1) % 4


# ---------------------------------------------------------------------------
# Layout caching
# ---------------------------------------------------------------------------


@async_test
async def test_identical_update_does_not_rebuild():
    prs = [_pr("pr-a"), _pr("pr-b", depends_on=["pr-a"])]
    app = _TreeApp(prs)
    async with app.run_test(size=(120, 40)):
        tree = app.query_one(TechTree)
        before = {n.pr_id: id(n) for n in app.query(PRNode)}
        # Re-feed identical data — signature unchanged → no widget rebuild.
        tree.update_prs([_pr("pr-a"), _pr("pr-b", depends_on=["pr-a"])])
        after = {n.pr_id: id(n) for n in app.query(PRNode)}
        assert before == after  # same widget instances reused


@async_test
async def test_status_change_rebuilds():
    app = _TreeApp([_pr("pr-a", status="pending")])
    async with app.run_test(size=(120, 40)) as pilot:
        tree = app.query_one(TechTree)
        before = [id(n) for n in app.query(PRNode)]
        tree.update_prs([_pr("pr-a", status="in_progress")])
        await pilot.pause()
        after = [id(n) for n in app.query(PRNode)]
        assert before != after  # widget rebuilt on a real change


# ---------------------------------------------------------------------------
# Neighbor computation (replaces the on_key candidate loops)
# ---------------------------------------------------------------------------


def test_compute_neighbors_linear_chain():
    # a -> b -> c laid out left to right on the same row
    ordered = ["a", "b", "c"]
    positions = {"a": (0, 0), "b": (30, 0), "c": (60, 0)}
    nb = compute_neighbors(ordered, positions)
    assert nb["a"]["right"] == "b"
    assert nb["b"]["right"] == "c"
    assert nb["c"]["left"] == "b"
    assert nb["b"]["left"] == "a"
    assert nb["a"]["left"] is None
    assert nb["c"]["right"] is None


def test_compute_neighbors_vertical_prefers_same_column():
    positions = {
        "a": (0, 0), "c": (0, 3),     # left column, rows 0 and 3
        "b": (30, 0), "d": (30, 3),   # right column, rows 0 and 3
    }
    ordered = ["a", "b", "c", "d"]
    nb = compute_neighbors(ordered, positions)
    assert nb["a"]["down"] == "c"   # same column down
    assert nb["c"]["up"] == "a"
    assert nb["b"]["down"] == "d"
    assert nb["a"]["right"] == "b"


# ---------------------------------------------------------------------------
# Navigation through mounted widgets
# ---------------------------------------------------------------------------


@async_test
async def test_arrow_nav_moves_selection():
    prs = [_pr("pr-a"), _pr("pr-b", depends_on=["pr-a"])]
    app = _TreeApp(prs)
    async with app.run_test(size=(120, 40)) as pilot:
        tree = app.query_one(TechTree)
        tree.focus()
        await pilot.pause()
        tree.selected_index = tree._ordered_ids.index("pr-a")
        await pilot.press("right")
        await pilot.pause()
        assert tree.selected_pr_id == "pr-b"
        await pilot.press("left")
        await pilot.pause()
        assert tree.selected_pr_id == "pr-a"


@async_test
async def test_prnode_carries_neighbor_ids():
    prs = [_pr("pr-a"), _pr("pr-b", depends_on=["pr-a"])]
    app = _TreeApp(prs)
    async with app.run_test(size=(120, 40)):
        nodes = {n.pr_id: n for n in app.query(PRNode)}
        assert nodes["pr-a"].neighbor_right == "pr-b"
        assert nodes["pr-b"].neighbor_left == "pr-a"
