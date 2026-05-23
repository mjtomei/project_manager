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

    def test_active_status_unchanged(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: active\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][0]["status"] == "active"

    def test_done_status_unchanged(self, tmp_pm_root):
        _write_yaml(tmp_pm_root,
            "project:\n  name: test\nplans:\n"
            "  - id: plan-001\n    name: A\n    file: a.md\n    status: done\n"
        )
        data = store.load(tmp_pm_root)
        assert data["plans"][0]["status"] == "done"

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


# ---------------------------------------------------------------------------
# YAML backend (libyaml C loader/dumper + project.libyaml flag)
# see pm_core/store.py:_yaml_loader / _yaml_dumper
# ---------------------------------------------------------------------------

class TestYamlBackend:
    """libyaml acceleration must round-trip correctly; the C dumper is gated by
    the project.libyaml flag so pure-Python output stays byte-stable when pinned.
    A long multi-line description is included because that is where the C and
    pure-Python dumpers actually diverge (scalar line-wrapping)."""

    _LONG = (
        "Split notes.txt into sections.\n\nThis is a deliberately long "
        "multi-line description with enough words to force the YAML dumper to "
        "wrap the scalar, which is exactly where libyaml and pure-Python differ "
        "in their line-folding choices. " * 3
    )

    def _representative(self, *, libyaml=None):
        project = {"name": "demo", "repo": "/r", "base_branch": "main",
                   "active_pr": "pr-0003", "hide_merged": False}
        if libyaml is not None:
            project["libyaml"] = libyaml
        return {
            "project": project,
            "plans": [{"id": "plan-001", "name": "bugs",
                       "description": "fixes — café résumé ✓"}],
            "prs": [
                {"id": "pr-0001", "title": "Title with 'quotes' and café ✓",
                 "branch": "b-1", "status": "pending", "depends_on": [],
                 "description": self._LONG, "gh_pr_number": None,
                 "created_at": "2026-01-01T00:00:00",
                 "updated_at": "2026-05-22T18:00:00Z"},
                {"id": "pr-0002", "title": "second", "branch": "b-2",
                 "status": "done", "depends_on": ["pr-0001"],
                 "description": "", "gh_pr_number": 42,
                 # quoting-sensitive scalars must survive as strings
                 "quirk": "007", "flagish": "true", "tildey": "~"},
            ],
        }

    def _expected_pure_python(self, data):
        import yaml
        return yaml.dump(data, Dumper=yaml.SafeDumper, default_flow_style=False,
                         sort_keys=False, allow_unicode=True)

    def _body(self, root):
        return (root / "project.yaml").read_text()[len(store._YAML_HEADER):]

    def test_round_trip_default(self, tmp_pm_root):
        data = self._representative()
        store.save(data, tmp_pm_root)
        loaded = store.load(tmp_pm_root, validate=False)
        assert loaded["project"] == data["project"]
        assert loaded["prs"] == data["prs"]
        # timestamp-shaped values must stay strings, not become datetime
        assert isinstance(loaded["prs"][0]["created_at"], str)

    def test_loader_is_byte_irrelevant(self, tmp_pm_root):
        # C loader and pure-Python loader must parse identically.
        import yaml
        text = self._expected_pure_python(self._representative())
        assert yaml.load(text, Loader=store._yaml_loader()) == \
            yaml.load(text, Loader=yaml.SafeLoader)

    def test_flag_off_matches_pure_python_bytes(self, tmp_pm_root):
        # libyaml: false must pin byte-for-byte pure-Python output, even for the
        # long multi-line description where the C dumper would wrap differently.
        data = self._representative(libyaml=False)
        store.save(data, tmp_pm_root)
        assert self._body(tmp_pm_root) == self._expected_pure_python(data)

    def test_default_matches_pure_python_bytes(self, tmp_pm_root):
        # With the flag absent, the dumper must default to byte-stable
        # pure-Python output — not the C dumper. This guards the regression
        # where a dropped project.libyaml flag silently re-enabled the C
        # dumper and reformatted the whole file on the next save.
        data = self._representative()  # no libyaml key at all
        assert "libyaml" not in data["project"]
        store.save(data, tmp_pm_root)
        assert self._body(tmp_pm_root) == self._expected_pure_python(data)

    def test_reserialization_fixed_point(self, tmp_pm_root):
        # Within a mode, dump -> load -> dump must not drift.
        for flag in (True, False):
            data = self._representative(libyaml=flag)
            store.save(data, tmp_pm_root)
            first = self._body(tmp_pm_root)
            store.save(store.load(tmp_pm_root, validate=False), tmp_pm_root)
            assert self._body(tmp_pm_root) == first
