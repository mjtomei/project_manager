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


def test_binary_file_target_degrades_gracefully(tmp_path):
    # A non-UTF-8 file target (e.g. `pm review paper.pdf`) must not crash the
    # context build — it points the session at the file instead.
    root = tmp_path
    (root / "paper.pdf").write_bytes(b"%PDF-1.4\n\xff\xfe\x00\x01binary\x80\x90")
    out = context.build_context(root, "paper-pdf", "paper.pdf", "file")
    assert "could not read" in out
    assert "Target (file): paper.pdf" in out


def test_missing_file_target_is_noted(tmp_path):
    out = context.build_context(tmp_path, "gone-md", "gone.md", "file")
    assert "file not found" in out
    assert "Target (file): gone.md" in out


def test_parallel_workflows_clause_is_unconditional(tmp_path):
    """note-0970084: every build_context output asks the session to use the
    workflow skill on the four phases, regardless of target type."""
    for target_type, target in (("topic", "t"),
                                ("file", "doc.md"),
                                ("plan", "plans/plan-x.md")):
        out = context.build_context(tmp_path, "rid", target, target_type)
        assert "## Parallel workflows" in out, target_type
        assert "workflow skill" in out, target_type
        for phase in ("audit phase", "review phase", "response phase"):
            assert phase in out, f"{phase} missing for {target_type}"
        # apply phase is explicitly sequential
        assert "apply phase sequentially" in out, target_type


def test_parallel_workflows_clause_precedes_target(tmp_path):
    """Directives should appear before the target preamble so the session reads
    them as instructions, not as an addendum to the artifact text."""
    out = context.build_context(tmp_path, "rid", "t", "topic")
    assert out.index("## Parallel workflows") < out.index("## Target")
