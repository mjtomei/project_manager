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
