from pm_core.review import paths


def test_reviews_root_and_dir_for_creates(tmp_path):
    root = tmp_path
    assert paths.reviews_root(root) == root / "docs/adversarial-review/reviews"

    d = paths.dir_for(root, "regression")
    assert d == root / "docs/adversarial-review/reviews/regression"
    assert d.is_dir()  # created on first access


def test_dir_for_no_create(tmp_path):
    d = paths.dir_for(tmp_path, "nope", create=False)
    assert not d.exists()


def test_per_review_file_paths(tmp_path):
    root = tmp_path
    rid = "topic-x"
    assert paths.state_path(root, rid).name == "STATE.md"
    assert paths.focus_path(root, rid).name == "UI_FOCUS.md"
    assert paths.notes_path(root, rid).name == "NOTES.md"
    # all live in the per-review dir (no artifact suffix on filenames)
    assert paths.state_path(root, rid).parent == paths.dir_for(root, rid)


def test_cycle_paths(tmp_path):
    cp = paths.cycle_paths(tmp_path, "rid", 3)
    assert cp["review"].name == "REVIEW_CYCLE_3.md"
    assert cp["audit"].name == "CITATION_AUDIT_CYCLE_3.md"
    assert cp["response"].name == "REVIEW_RESPONSE_CYCLE_3.md"


def test_methodology_paths_order(tmp_path):
    mp = paths.methodology_paths(tmp_path)
    names = [p.name for p in mp]
    assert names == ["METHODOLOGY.md", "CITATION_USE_AUDIT.md", "CITATION_CRAWL.md"]
    assert all(p.parent == tmp_path / "docs/adversarial-review" for p in mp)
