"""Tests for plan validation in store.load()."""

import pytest

from pm_core import store


@pytest.fixture
def tmp_pm_root(tmp_path):
    """Create a temporary PM root directory."""
    root = tmp_path / "pm"
    root.mkdir()
    return root


def _write_yaml(root, content):
    (root / "project.yaml").write_text(content)


# ---------------------------------------------------------------------------
# Plan status validation
# ---------------------------------------------------------------------------

class TestPlanStatusValidation:
    """Plans with invalid statuses are normalized to 'draft'."""

    def test_valid_status_unchanged(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: draft\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][0]["status"] == "draft"

    def test_invalid_status_normalized(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: bogus\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][0]["status"] == "draft"

    def test_missing_status_normalized(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][0]["status"] == "draft"


# ---------------------------------------------------------------------------
# Parent field — valid cases
# ---------------------------------------------------------------------------

class TestPlanParentValid:
    """Plans with valid parent references load without error."""

    def test_null_parent_is_root(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: draft\n    parent: null\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][0]["parent"] is None

    def test_missing_parent_backfilled_as_null(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: draft\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][0]["parent"] is None

    def test_valid_parent_reference(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: Root\n    file: a.md\n    status: draft\n    parent: null\n"
            "  - id: plan-002\n    name: Child\n    file: b.md\n    status: draft\n    parent: plan-001\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][0]["parent"] is None
        assert data["plans"][1]["parent"] == "plan-001"

    def test_deep_hierarchy_chain(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: Root\n    file: a.md\n    status: draft\n    parent: null\n"
            "  - id: plan-002\n    name: Mid\n    file: b.md\n    status: draft\n    parent: plan-001\n"
            "  - id: plan-003\n    name: Leaf\n    file: c.md\n    status: draft\n    parent: plan-002\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][2]["parent"] == "plan-002"

    def test_multiple_roots(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: draft\n    parent: null\n"
            "  - id: plan-002\n    name: B\n    file: b.md\n    status: draft\n    parent: null\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][0]["parent"] is None
        assert data["plans"][1]["parent"] is None


# ---------------------------------------------------------------------------
# Parent field — invalid references
# ---------------------------------------------------------------------------

class TestPlanParentInvalid:
    """Plans with invalid parent references raise PlanValidationError."""

    def test_nonexistent_parent_raises(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: draft\n    parent: plan-999\n"
        )
        with pytest.raises(store.PlanValidationError, match="non-existent parent"):
            store.load(tmp_pm_root)

    def test_invalid_parent_skipped_when_validate_false(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: draft\n    parent: plan-999\n"
        )
        data = store.load(tmp_pm_root, validate=False)
        assert data["plans"][0]["parent"] == "plan-999"


# ---------------------------------------------------------------------------
# Cycle detection
# ---------------------------------------------------------------------------

class TestPlanCycleDetection:
    """Cycles in the parent hierarchy raise PlanValidationError."""

    def test_self_referencing_parent(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: draft\n    parent: plan-001\n"
        )
        with pytest.raises(store.PlanValidationError, match="Cycle"):
            store.load(tmp_pm_root)

    def test_two_node_cycle(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: draft\n    parent: plan-002\n"
            "  - id: plan-002\n    name: B\n    file: b.md\n    status: draft\n    parent: plan-001\n"
        )
        with pytest.raises(store.PlanValidationError, match="Cycle"):
            store.load(tmp_pm_root)

    def test_three_node_cycle(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: draft\n    parent: plan-003\n"
            "  - id: plan-002\n    name: B\n    file: b.md\n    status: draft\n    parent: plan-001\n"
            "  - id: plan-003\n    name: C\n    file: c.md\n    status: draft\n    parent: plan-002\n"
        )
        with pytest.raises(store.PlanValidationError, match="Cycle"):
            store.load(tmp_pm_root)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestPlanValidationEdgeCases:
    """Edge cases for plan validation."""

    def test_empty_plans_list(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans: []\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"] == []

    def test_null_plans(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans: null\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"] is None
