from pm_core import store
from pm_core.review import registry


def _seed_root(tmp_path):
    data = {
        "project": {"name": "demo", "repo": "x", "base_branch": "master"},
        "plans": [{"id": "plan-1", "name": "P", "file": "plans/plan-1.md",
                   "status": "draft", "parent": None}],
        "prs": [{"id": "pr-1", "title": "T", "status": "pending"}],
    }
    store.save(data, tmp_path)
    return tmp_path


def test_create_review_preserves_other_keys(tmp_path):
    root = _seed_root(tmp_path)
    registry.create_review(root, "regression", "plans/plan-1.md", "plan")

    data = store.load(root)
    # new entry present and well-formed
    entry = registry.get_review(data, "regression")
    assert entry == {
        "id": "regression",
        "target": "plans/plan-1.md",
        "target-type": "plan",
        "status": "active",
    }
    # surrounding structure untouched
    assert data["project"]["name"] == "demo"
    assert [p["id"] for p in data["plans"]] == ["plan-1"]
    assert [p["id"] for p in data["prs"]] == ["pr-1"]


def test_create_review_idempotent(tmp_path):
    root = _seed_root(tmp_path)
    registry.create_review(root, "r", "t.md", "file")
    registry.create_review(root, "r", "t.md", "file")
    data = store.load(root)
    assert len([r for r in data["reviews"] if r["id"] == "r"]) == 1


def test_set_status_and_list_active(tmp_path):
    root = _seed_root(tmp_path)
    registry.create_review(root, "a", "a.md", "file")
    registry.create_review(root, "b", "b.md", "file")
    registry.set_status(root, "b", "archived")

    active = registry.list_active(root)
    assert {r["id"] for r in active} == {"a"}
    # other keys still intact after status mutation
    assert store.load(root)["project"]["name"] == "demo"


def test_set_status_rejects_bad_value(tmp_path):
    root = _seed_root(tmp_path)
    registry.create_review(root, "a", "a.md", "file")
    import pytest
    with pytest.raises(ValueError):
        registry.set_status(root, "a", "deleted")


def test_create_review_when_reviews_key_absent(tmp_path):
    root = _seed_root(tmp_path)  # no reviews key
    registry.create_review(root, "first", "f.md", "file")
    assert registry.get_review(store.load(root), "first") is not None
