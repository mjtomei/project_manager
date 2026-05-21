from pm_core.review import context, paths


def _write_methodology(root, names):
    d = root / "docs/adversarial-review"
    d.mkdir(parents=True, exist_ok=True)
    for name in names:
        (d / name).write_text(f"BODY OF {name}")


def test_concatenates_present_methodology_files(tmp_path):
    root = tmp_path
    _write_methodology(root, ["METHODOLOGY.md", "CITATION_USE_AUDIT.md", "CITATION_CRAWL.md"])
    out = context.build_context(root, "rid", "some topic", "topic")
    assert "BODY OF METHODOLOGY.md" in out
    assert "BODY OF CITATION_USE_AUDIT.md" in out
    assert "BODY OF CITATION_CRAWL.md" in out
    # framing instruction names the review dir
    assert str(paths.dir_for(root, "rid")) in out
    # topic preamble
    assert "Target (topic): some topic" in out


def test_missing_methodology_files_are_noted_not_fatal(tmp_path):
    root = tmp_path
    _write_methodology(root, ["CITATION_CRAWL.md"])  # only one present
    out = context.build_context(root, "rid", "t", "topic")
    assert "BODY OF CITATION_CRAWL.md" in out
    assert "skipped" in out  # missing ones noted


def test_includes_state_md_on_resume(tmp_path):
    root = tmp_path
    paths.state_path(root, "rid").write_text("current-cycle: 2\ncurrent-phase: awaiting-human-review\n")
    out = context.build_context(root, "rid", "t", "topic")
    assert "current-phase: awaiting-human-review" in out
    assert "STATE.md" in out


def test_file_target_inlines_contents(tmp_path):
    root = tmp_path
    (root / "art.md").write_text("THE ARTIFACT TEXT")
    out = context.build_context(root, "art-md", "art.md", "file")
    assert "THE ARTIFACT TEXT" in out
    assert "Target (file): art.md" in out


def test_large_file_target_is_not_inlined(tmp_path):
    root = tmp_path
    marker = "UNIQUE_BODY_MARKER"
    (root / "big.md").write_text(marker + "x" * (context._MAX_INLINE_BYTES + 10))
    out = context.build_context(root, "big-md", "big.md", "file")
    assert marker not in out  # body not inlined
    assert "is large" in out  # pointer note instead
    assert "Target (file): big.md" in out
