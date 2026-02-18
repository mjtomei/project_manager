"""Tests for pm_core.graph — dependency graph logic."""

from pm_core.graph import (
    build_adjacency,
    topological_sort,
    ready_prs,
    blocked_prs,
    compute_layers,
    render_static_graph,
)


# ---------------------------------------------------------------------------
# build_adjacency
# ---------------------------------------------------------------------------

class TestBuildAdjacency:
    def test_empty_input(self):
        assert build_adjacency([]) == {}

    def test_no_dependencies(self):
        prs = [{"id": "a"}, {"id": "b"}]
        assert build_adjacency(prs) == {}

    def test_linear_chain(self):
        """a -> b -> c"""
        prs = [
            {"id": "a"},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},
        ]
        adj = build_adjacency(prs)
        assert adj == {"a": ["b"], "b": ["c"]}

    def test_diamond_graph(self):
        """a -> b, a -> c, b -> d, c -> d"""
        prs = [
            {"id": "a"},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["a"]},
            {"id": "d", "depends_on": ["b", "c"]},
        ]
        adj = build_adjacency(prs)
        assert set(adj["a"]) == {"b", "c"}
        assert adj["b"] == ["d"]
        assert adj["c"] == ["d"]

    def test_depends_on_none(self):
        prs = [{"id": "a", "depends_on": None}]
        assert build_adjacency(prs) == {}

    def test_depends_on_empty_list(self):
        prs = [{"id": "a", "depends_on": []}]
        assert build_adjacency(prs) == {}


# ---------------------------------------------------------------------------
# topological_sort
# ---------------------------------------------------------------------------

class TestTopologicalSort:
    def test_empty(self):
        assert topological_sort([]) == []

    def test_single_pr(self):
        assert topological_sort([{"id": "a"}]) == ["a"]

    def test_linear_chain(self):
        prs = [
            {"id": "a"},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},
        ]
        result = topological_sort(prs)
        assert result.index("a") < result.index("b") < result.index("c")

    def test_diamond(self):
        prs = [
            {"id": "a"},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["a"]},
            {"id": "d", "depends_on": ["b", "c"]},
        ]
        result = topological_sort(prs)
        assert result.index("a") < result.index("b")
        assert result.index("a") < result.index("c")
        assert result.index("b") < result.index("d")
        assert result.index("c") < result.index("d")

    def test_skips_unknown_deps(self):
        """Deps referencing IDs not in the PR list are ignored."""
        prs = [
            {"id": "a", "depends_on": ["missing"]},
        ]
        result = topological_sort(prs)
        assert result == ["a"]

    def test_independent_prs(self):
        prs = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result = topological_sort(prs)
        assert set(result) == {"a", "b", "c"}

    def test_cycle_omits_nodes(self):
        """Cyclic nodes never reach in-degree 0 and are omitted."""
        prs = [
            {"id": "a", "depends_on": ["b"]},
            {"id": "b", "depends_on": ["a"]},
        ]
        result = topological_sort(prs)
        assert result == []


# ---------------------------------------------------------------------------
# ready_prs
# ---------------------------------------------------------------------------

class TestReadyPrs:
    def test_empty(self):
        assert ready_prs([]) == []

    def test_no_deps_pending(self):
        prs = [{"id": "a", "status": "pending"}]
        result = ready_prs(prs)
        assert len(result) == 1
        assert result[0]["id"] == "a"

    def test_all_deps_merged(self):
        prs = [
            {"id": "a", "status": "merged"},
            {"id": "b", "status": "pending", "depends_on": ["a"]},
        ]
        result = ready_prs(prs)
        assert [p["id"] for p in result] == ["b"]

    def test_unmerged_dep_blocks(self):
        prs = [
            {"id": "a", "status": "in_progress"},
            {"id": "b", "status": "pending", "depends_on": ["a"]},
        ]
        assert ready_prs(prs) == []

    def test_non_pending_excluded(self):
        """Only 'pending' PRs are returned, not in_progress or merged."""
        prs = [
            {"id": "a", "status": "in_progress"},
            {"id": "b", "status": "merged"},
        ]
        assert ready_prs(prs) == []

    def test_partial_deps_merged(self):
        prs = [
            {"id": "a", "status": "merged"},
            {"id": "b", "status": "in_progress"},
            {"id": "c", "status": "pending", "depends_on": ["a", "b"]},
        ]
        assert ready_prs(prs) == []


# ---------------------------------------------------------------------------
# blocked_prs
# ---------------------------------------------------------------------------

class TestBlockedPrs:
    def test_empty(self):
        assert blocked_prs([]) == []

    def test_no_deps_not_blocked(self):
        prs = [{"id": "a", "status": "pending"}]
        assert blocked_prs(prs) == []

    def test_unmerged_dep_blocks(self):
        prs = [
            {"id": "a", "status": "in_progress"},
            {"id": "b", "status": "pending", "depends_on": ["a"]},
        ]
        result = blocked_prs(prs)
        assert [p["id"] for p in result] == ["b"]

    def test_all_deps_merged_not_blocked(self):
        prs = [
            {"id": "a", "status": "merged"},
            {"id": "b", "status": "pending", "depends_on": ["a"]},
        ]
        assert blocked_prs(prs) == []

    def test_blocked_status_included(self):
        prs = [
            {"id": "a", "status": "in_progress"},
            {"id": "b", "status": "blocked", "depends_on": ["a"]},
        ]
        result = blocked_prs(prs)
        assert [p["id"] for p in result] == ["b"]

    def test_in_review_status_excluded(self):
        prs = [
            {"id": "a", "status": "in_progress"},
            {"id": "b", "status": "in_review", "depends_on": ["a"]},
        ]
        assert blocked_prs(prs) == []


# ---------------------------------------------------------------------------
# compute_layers
# ---------------------------------------------------------------------------

class TestComputeLayers:
    def test_empty(self):
        result = compute_layers([])
        assert result == [[]]

    def test_single_pr(self):
        result = compute_layers([{"id": "a"}])
        assert result == [["a"]]

    def test_linear_chain(self):
        prs = [
            {"id": "a"},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["b"]},
        ]
        result = compute_layers(prs)
        assert len(result) == 3
        assert result[0] == ["a"]
        assert result[1] == ["b"]
        assert result[2] == ["c"]

    def test_diamond(self):
        prs = [
            {"id": "a"},
            {"id": "b", "depends_on": ["a"]},
            {"id": "c", "depends_on": ["a"]},
            {"id": "d", "depends_on": ["b", "c"]},
        ]
        result = compute_layers(prs)
        assert result[0] == ["a"]
        assert set(result[1]) == {"b", "c"}
        assert result[2] == ["d"]

    def test_unknown_dep_returns_zero(self):
        """Deps referencing non-existent PRs are treated as layer 0."""
        prs = [{"id": "a", "depends_on": ["missing"]}]
        result = compute_layers(prs)
        assert result == [[], ["a"]]

    def test_independent_all_layer_zero(self):
        prs = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result = compute_layers(prs)
        assert len(result) == 1
        assert set(result[0]) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# render_static_graph
# ---------------------------------------------------------------------------

class TestRenderStaticGraph:
    def test_empty(self):
        assert render_static_graph([]) == "No PRs defined."

    def test_single_pending(self):
        prs = [{"id": "pr-1", "title": "Fix bug", "status": "pending"}]
        result = render_static_graph(prs)
        assert "⏳" in result
        assert "pr-1" in result
        assert "Fix bug" in result

    def test_shows_deps(self):
        prs = [
            {"id": "a", "title": "Base", "status": "merged"},
            {"id": "b", "title": "Next", "status": "pending", "depends_on": ["a"]},
        ]
        result = render_static_graph(prs)
        assert "<- [a]" in result

    def test_shows_machine(self):
        prs = [{"id": "a", "title": "T", "status": "pending", "agent_machine": "laptop"}]
        result = render_static_graph(prs)
        assert "(laptop)" in result

    def test_layer_separator(self):
        prs = [
            {"id": "a", "title": "Base"},
            {"id": "b", "title": "Next", "depends_on": ["a"]},
        ]
        result = render_static_graph(prs)
        assert "│" in result
        assert "▼" in result

    def test_status_icons(self):
        for status, icon in [
            ("pending", "⏳"), ("in_progress", "🔨"),
            ("in_review", "👀"), ("merged", "✅"), ("blocked", "🚫"),
        ]:
            prs = [{"id": "x", "title": "T", "status": status}]
            assert icon in render_static_graph(prs)
