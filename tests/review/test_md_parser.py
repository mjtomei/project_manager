from pathlib import Path

from pm_core.review import md_parser

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_response_blocks_mixed_provenance():
    text = (FIXTURES / "response_cycle.md").read_text()
    blocks = md_parser.parse_response_blocks(text)
    assert [b.id for b in blocks] == ["change-1", "change-2"]
    assert [b.provenance for b in blocks] == ["reviewer-comment", "audit-entry"]
    assert "Sharma" in blocks[0].fields["after"]
    assert blocks[1].fields["suggested-verdict"] == "modify"
    assert blocks[0].interactions == []


def test_parse_response_doc_preamble():
    text = (FIXTURES / "response_cycle.md").read_text()
    doc = md_parser.parse_response_doc(text)
    assert doc.preamble.startswith("# Review response")
    assert "## §3 — sycophancy framing" in doc.preamble
    assert len(doc.blocks) == 2


def test_parse_audit_doc_canonical_format():
    text = (FIXTURES / "audit_cycle.md").read_text()
    doc = md_parser.parse_audit_doc(text)
    assert len(doc.entries) == 3

    andreas = doc.entries[0]
    assert "Andreas 2022" in andreas.citation_header
    assert andreas.cluster.startswith("I. §1")
    assert andreas.tier == "1"
    assert andreas.verdict == "over-characterizes"
    assert "author-side modeling" in andreas.change_proposed
    assert "Andreas (2022) shows LMs model" in andreas.doc_passage
    assert any("Sumers" in c for c in andreas.surfaced_citations)
    assert len(andreas.surfaced_citations) == 2

    sharma = doc.entries[1]
    assert sharma.verdict == "faithful"
    assert sharma.flag is not None
    assert sharma.surfaced_citations == []

    openai = doc.entries[2]
    assert openai.cluster.startswith("II. §3")


def test_parse_audit_doc_skips_incomplete_trailing_entry():
    # The live audit-browse view reads this file while the audit loop is still
    # writing it. A trailing entry that has a header (and partial body) but no
    # `**Verdict:**` yet must be skipped, not surfaced half-populated — and the
    # parse must not raise.
    text = (FIXTURES / "audit_cycle.md").read_text()
    partial = text + (
        "\n---\n\n"
        "### Lu 2026, \"Assistant Axis\" — [arXiv:2601.00001](https://arxiv.org/abs/2601.00001)\n\n"
        "**Tier:** 1\n\n"
        "**Doc passage as currently written:**\n\n"
        "> The model has a single assistant axis.\n\n"
        "**What the source actually says:**\n\n"
        "> (still being written by the audit agent...)\n"
    )
    doc = md_parser.parse_audit_doc(partial)
    headers = [e.citation_header for e in doc.entries]
    assert not any("Lu 2026" in h for h in headers)
    # The complete entries are still parsed.
    assert len(doc.entries) == 3
    assert all(e.verdict for e in doc.entries)


def test_parse_state_phase_transition():
    text = (FIXTURES / "state.md").read_text()
    state = md_parser.parse_state(text)
    assert state.current_cycle == 3
    assert state.current_phase == "awaiting-human-review"
    assert state.mode == "human-reviewed"
    assert state.last_transition == "2026-05-20T14:32:00Z"


def test_parse_focus_timestamp():
    text = (FIXTURES / "focus.md").read_text()
    focus = md_parser.parse_focus(text)
    assert focus.view == "audit-browse"
    assert focus.cycle == 3
    assert focus.target == "andreas-2022"
    assert focus.timestamp == "2026-05-20T15:30:00Z"


def test_parse_response_block_with_arrow_in_value():
    # A `-->` inside a YAML value (research passages contain arrows like
    # "input --> output") must not be mistaken for the closing fence: YAML
    # indents the value under its key, so the real close is the bare `-->` line.
    text = (
        "<!-- proposed-change\n"
        "id: change-x\n"
        "provenance: reviewer-comment\n"
        "after: |\n"
        "  The pipeline maps input --> output across stages.\n"
        "status: pending\n"
        "-->\n"
    )
    blocks = md_parser.parse_response_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].id == "change-x"
    assert "input --> output" in blocks[0].fields["after"]
    assert blocks[0].fields["status"] == "pending"


def test_parse_response_blocks_skips_unclosed_trailing_block():
    # A trailing block still being written (no closing fence yet) is skipped,
    # and earlier complete blocks still parse.
    text = (
        "<!-- proposed-change\n"
        "id: change-1\n"
        "status: pending\n"
        "-->\n\n"
        "<!-- proposed-change\n"
        "id: change-2\n"
        "status: pen"
    )
    blocks = md_parser.parse_response_blocks(text)
    assert [b.id for b in blocks] == ["change-1"]


def test_parse_interaction_log_from_block():
    text = """<!-- proposed-change
id: x
provenance: reviewer-comment
interactions:
  - event: viewed
    at: 2026-05-20T10:00:00Z
    duration-ms: 1500
  - event: accept-as-suggested
    at: 2026-05-20T10:00:01Z
-->"""
    blocks = md_parser.parse_response_blocks(text)
    log = md_parser.parse_interaction_log(blocks[0])
    assert [e["event"] for e in log] == ["viewed", "accept-as-suggested"]
    assert log[0]["duration-ms"] == 1500
