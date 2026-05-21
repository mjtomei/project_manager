import shutil
import threading
from pathlib import Path

from pm_core.review import md_parser, md_writer

FIXTURES = Path(__file__).parent / "fixtures"


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    dst = tmp_path / name
    shutil.copy(FIXTURES / name, dst)
    return dst


def test_response_block_round_trip(tmp_path):
    path = _copy_fixture("response_cycle.md", tmp_path)
    md_writer.update_response_block(
        path,
        "change-1",
        {
            "human-verdict": "accept",
            "human-rationale": "matches my reading of Sharma",
            "status": "accepted-as-suggested",
        },
    )
    blocks = md_parser.parse_response_blocks(path.read_text())
    by_id = {b.id: b for b in blocks}
    assert by_id["change-1"].fields["human-verdict"] == "accept"
    assert by_id["change-1"].fields["status"] == "accepted-as-suggested"
    # change-2 was not touched.
    assert by_id["change-2"].fields["status"] == "pending"
    assert by_id["change-2"].fields["suggested-verdict"] == "modify"
    # Preamble is preserved.
    assert "# Review response — cycle 3" in path.read_text()


def test_append_interaction_concurrency(tmp_path):
    path = _copy_fixture("response_cycle.md", tmp_path)
    N_PER_THREAD = 25
    N_THREADS = 4

    def worker(tid: int):
        for k in range(N_PER_THREAD):
            md_writer.append_interaction(
                path,
                "change-1",
                {"event": "viewed", "thread": tid, "k": k},
            )

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    blocks = md_parser.parse_response_blocks(path.read_text())
    target = next(b for b in blocks if b.id == "change-1")
    log = md_parser.parse_interaction_log(target)
    assert len(log) == N_PER_THREAD * N_THREADS
    # Every (thread, k) pair lands exactly once.
    seen = {(e["thread"], e["k"]) for e in log}
    assert seen == {(t, k) for t in range(N_THREADS) for k in range(N_PER_THREAD)}


def test_update_state_atomic(tmp_path):
    path = tmp_path / "STATE.md"
    md_writer.update_state(
        path,
        {
            "current-cycle": 3,
            "current-phase": "awaiting-human-review",
            "mode": "human-reviewed",
            "last-transition": "2026-05-20T14:32:00Z",
        },
    )
    state = md_parser.parse_state(path.read_text())
    assert state.current_phase == "awaiting-human-review"

    # Phase transition.
    md_writer.update_state(
        path,
        {
            "current-cycle": 3,
            "current-phase": "applying",
            "mode": "human-reviewed",
        },
    )
    state2 = md_parser.parse_state(path.read_text())
    assert state2.current_phase == "applying"
    assert state2.last_transition is not None  # auto-stamped


def test_update_focus_timestamp_ordering(tmp_path):
    path = tmp_path / "UI_FOCUS.md"
    md_writer.update_focus(
        path,
        {"view": "changes", "cycle": 3, "timestamp": "2026-05-20T15:00:00Z"},
    )
    md_writer.update_focus(
        path,
        {
            "view": "audit-browse",
            "cycle": 3,
            "target": "andreas-2022",
            "timestamp": "2026-05-20T15:30:00Z",
        },
    )
    focus = md_parser.parse_focus(path.read_text())
    assert focus.view == "audit-browse"
    assert focus.target == "andreas-2022"
    assert focus.timestamp == "2026-05-20T15:30:00Z"

    # Without an explicit timestamp the writer stamps now-UTC.
    md_writer.update_focus(path, {"view": "dashboard", "cycle": 3})
    focus2 = md_parser.parse_focus(path.read_text())
    assert focus2.timestamp is not None
    assert focus2.timestamp > "2026-05-20T15:30:00Z"


def test_append_note_preserves_prior_content(tmp_path):
    path = _copy_fixture("notes.md", tmp_path)
    original = path.read_text()
    md_writer.append_note(
        path,
        "General",
        "Walker started cycle 3 walk.",
        timestamp="2026-05-20T16:00:00Z",
    )
    new = path.read_text()
    # Prior entries preserved verbatim.
    assert "Initial setup observations." in new
    assert "Need to revisit Andreas 2022 in cycle 4." in new
    # New entry appended under General.
    assert "[2026-05-20T16:00:00Z]" in new
    assert "Walker started cycle 3 walk." in new
    # Citations section untouched in position.
    assert new.index("## Citations") > new.index("Walker started cycle 3 walk.")


def test_append_note_creates_section(tmp_path):
    path = _copy_fixture("notes.md", tmp_path)
    md_writer.append_note(
        path,
        "Process",
        "Tried a new bulk-accept filter.",
        timestamp="2026-05-20T17:00:00Z",
    )
    text = path.read_text()
    assert "## Process" in text
    assert "Tried a new bulk-accept filter." in text


def test_append_note_creates_file(tmp_path):
    path = tmp_path / "NOTES.md"
    md_writer.append_note(
        path, "General", "First note.", timestamp="2026-05-20T18:00:00Z"
    )
    text = path.read_text()
    assert "## General" in text
    assert "[2026-05-20T18:00:00Z]" in text
    assert "First note." in text


def test_append_note_keeps_blank_line_before_following_header(tmp_path):
    # Appending to a non-last section must not glue the new entry onto the
    # next `## ` header (which would stop it rendering as a heading).
    path = _copy_fixture("notes.md", tmp_path)
    md_writer.append_note(path, "General", "Walker started.", timestamp="T1")
    text = path.read_text()
    assert "Walker started.\n\n## Citations" in text


def test_append_note_new_section_keeps_blank_line_before_header(tmp_path):
    path = _copy_fixture("notes.md", tmp_path)
    md_writer.append_note(path, "Process", "New entry.", timestamp="T1")
    text = path.read_text()
    assert "\n\n## Process\n" in text


def test_update_response_block_preserves_literal_blocks(tmp_path):
    # Multi-line fields must round-trip as readable `|` blocks, not
    # single-quoted scalars with embedded blank lines.
    path = _copy_fixture("response_cycle.md", tmp_path)
    md_writer.update_response_block(path, "change-1", {"human-verdict": "accept"})
    text = path.read_text()
    assert "after: |" in text
    assert "before: |" in text
    # Empty fields stay bare, not `null`.
    assert "human-rationale: null" not in text
