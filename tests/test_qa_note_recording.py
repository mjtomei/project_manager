"""Tests for QA note recording on PR after completion.

Verifies:
- Note format: "QA {verdict}: {s1}: {v1}; {s2}: {v2} [changes committed] (workdir: {path})"
- "[changes committed]" only when made_changes is true
- Workdir path included when set
- Note has id, created_at, last_edited fields
- Running QA again appends (not replaces) notes
- Note ID generation avoids collisions
"""

import re
from unittest.mock import MagicMock

from pm_core import store
from pm_core.qa_loop import QALoopState, QAScenario
from pm_core.tui.qa_loop_ui import _record_qa_note


def _make_app(tmp_path, notes=None):
    """Create a mock app with a real project.yaml backing."""
    pr = {
        "id": "pr-001",
        "plan": None,
        "title": "Test PR",
        "branch": "pm/pr-001-test",
        "status": "qa",
        "depends_on": [],
        "description": "A test PR",
        "agent_machine": None,
        "gh_pr": None,
        "gh_pr_number": None,
    }
    if notes is not None:
        pr["notes"] = notes
    data = {
        "project": {"name": "test", "repo": "/tmp/fake", "base_branch": "master"},
        "plans": [],
        "prs": [pr],
    }
    store.save(data, tmp_path)
    app = MagicMock()
    app._root = tmp_path
    return app


def _make_state(pr_id="pr-001", scenarios=None, verdicts=None,
                verdict="PASS", made_changes=False, qa_workdir=None):
    """Build a QALoopState with given parameters."""
    if scenarios is None:
        scenarios = [
            QAScenario(index=1, title="Login Flow", focus="auth"),
            QAScenario(index=2, title="Dashboard", focus="rendering"),
        ]
    state = QALoopState(pr_id=pr_id)
    state.scenarios = scenarios
    state.scenario_verdicts = verdicts or {1: "PASS", 2: "PASS"}
    state.latest_verdict = verdict
    state.made_changes = made_changes
    state.qa_workdir = qa_workdir
    return state


TS_RE = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"


class TestNoteFormat:
    def test_basic_pass_format(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state(verdict="PASS", verdicts={1: "PASS", 2: "PASS"})
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        assert note["text"] == "QA PASS: Login Flow: PASS; Dashboard: PASS"

    def test_needs_work_format(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state(verdict="NEEDS_WORK",
                            verdicts={1: "NEEDS_WORK", 2: "PASS"})
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        assert note["text"] == "QA NEEDS_WORK: Login Flow: NEEDS_WORK; Dashboard: PASS"

    def test_input_required_format(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state(verdict="INPUT_REQUIRED",
                            verdicts={1: "PASS", 2: "INPUT_REQUIRED"})
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        assert note["text"] == "QA INPUT_REQUIRED: Login Flow: PASS; Dashboard: INPUT_REQUIRED"

    def test_unknown_verdict_shows_question_mark(self, tmp_path):
        """Scenario with no recorded verdict shows '?'."""
        app = _make_app(tmp_path)
        state = _make_state(verdict="PASS", verdicts={1: "PASS"})  # scenario 2 missing
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        assert "Dashboard: ?" in note["text"]


class TestChangesCommitted:
    def test_no_changes_no_marker(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state(made_changes=False)
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert "[changes committed]" not in pr["notes"][0]["text"]

    def test_changes_committed_present(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state(made_changes=True)
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert "[changes committed]" in pr["notes"][0]["text"]

    def test_changes_committed_before_workdir(self, tmp_path):
        """[changes committed] should appear before (workdir: ...) in the text."""
        app = _make_app(tmp_path)
        state = _make_state(made_changes=True, qa_workdir="/tmp/qa-work")
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        text = pr["notes"][0]["text"]
        assert "[changes committed]" in text
        assert "(workdir: /tmp/qa-work)" in text
        # Order: committed before workdir
        assert text.index("[changes committed]") < text.index("(workdir:")


class TestWorkdirPath:
    def test_workdir_included(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state(qa_workdir="/home/user/.pm/workdirs/qa/pr-001-abc123")
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert "(workdir: /home/user/.pm/workdirs/qa/pr-001-abc123)" in pr["notes"][0]["text"]

    def test_no_workdir_no_path(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state(qa_workdir=None)
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert "(workdir:" not in pr["notes"][0]["text"]


class TestNoteFields:
    def test_has_id(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state()
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        assert "id" in note
        assert note["id"].startswith("note-")

    def test_has_created_at(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state()
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        assert "created_at" in note
        assert re.match(TS_RE, note["created_at"])

    def test_has_last_edited(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state()
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        assert "last_edited" in note
        assert re.match(TS_RE, note["last_edited"])

    def test_created_at_equals_last_edited(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state()
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        note = pr["notes"][0]
        assert note["created_at"] == note["last_edited"]


class TestNoteAppending:
    def test_second_note_appended(self, tmp_path):
        """Running QA again appends a new note, doesn't replace old one."""
        app = _make_app(tmp_path)
        state1 = _make_state(verdict="NEEDS_WORK",
                             verdicts={1: "NEEDS_WORK", 2: "PASS"})
        _record_qa_note(app, state1)

        state2 = _make_state(verdict="PASS",
                             verdicts={1: "PASS", 2: "PASS"})
        _record_qa_note(app, state2)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 2
        assert "NEEDS_WORK" in pr["notes"][0]["text"]
        assert pr["notes"][1]["text"] == "QA PASS: Login Flow: PASS; Dashboard: PASS"

    def test_existing_notes_preserved(self, tmp_path):
        """QA notes append to existing manual notes."""
        existing = [{"id": "note-manual", "text": "Manual note",
                     "created_at": "2026-01-01T00:00:00Z",
                     "last_edited": "2026-01-01T00:00:00Z"}]
        app = _make_app(tmp_path, notes=existing)
        state = _make_state()
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 2
        assert pr["notes"][0]["text"] == "Manual note"
        assert pr["notes"][1]["text"].startswith("QA PASS:")

    def test_three_qa_runs_three_notes(self, tmp_path):
        app = _make_app(tmp_path)
        for verdict in ["NEEDS_WORK", "NEEDS_WORK", "PASS"]:
            state = _make_state(verdict=verdict,
                                verdicts={1: verdict, 2: "PASS"})
            _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 3


class TestNoteIdCollision:
    def test_same_text_gets_different_ids(self, tmp_path):
        """Two identical QA runs should still get unique note IDs.

        Since the note text is identical, generate_note_id must detect
        the collision and extend the hash.
        """
        app = _make_app(tmp_path)
        state = _make_state()
        _record_qa_note(app, state)
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 2
        id1 = pr["notes"][0]["id"]
        id2 = pr["notes"][1]["id"]
        assert id1 != id2
        assert id1.startswith("note-")
        assert id2.startswith("note-")

    def test_collision_avoidance_unit(self):
        """generate_note_id extends hash when colliding."""
        nid1 = store.generate_note_id("pr-001", "same text")
        nid2 = store.generate_note_id("pr-001", "same text",
                                       existing_ids={nid1})
        assert nid1 != nid2
        # Second ID should be longer (extended hash)
        assert len(nid2) > len(nid1)

    def test_multiple_collisions(self):
        """Chain of collisions all produce unique IDs."""
        ids = set()
        text = "collision test"
        for _ in range(5):
            nid = store.generate_note_id("pr-001", text, existing_ids=ids)
            assert nid not in ids
            ids.add(nid)
        assert len(ids) == 5


class TestEdgeCases:
    def test_no_root(self, tmp_path):
        """No crash when app._root is None."""
        app = MagicMock()
        app._root = None
        state = _make_state()
        _record_qa_note(app, state)  # Should not raise

    def test_unknown_pr(self, tmp_path):
        """No crash when PR not found."""
        app = _make_app(tmp_path)
        state = _make_state(pr_id="pr-nonexistent")
        _record_qa_note(app, state)  # Should not raise

    def test_empty_scenarios(self, tmp_path):
        """Note recorded even with no scenarios."""
        app = _make_app(tmp_path)
        state = _make_state(scenarios=[], verdicts={}, verdict="PASS")
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert len(pr["notes"]) == 1
        assert pr["notes"][0]["text"] == "QA PASS: "

    def test_single_scenario(self, tmp_path):
        app = _make_app(tmp_path)
        state = _make_state(
            scenarios=[QAScenario(index=1, title="Only Test", focus="all")],
            verdicts={1: "PASS"},
            verdict="PASS",
        )
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        assert pr["notes"][0]["text"] == "QA PASS: Only Test: PASS"

    def test_full_format_with_all_parts(self, tmp_path):
        """Complete note with verdict, scenarios, changes, and workdir."""
        app = _make_app(tmp_path)
        state = _make_state(
            verdict="NEEDS_WORK",
            verdicts={1: "PASS", 2: "NEEDS_WORK"},
            made_changes=True,
            qa_workdir="/home/user/.pm/workdirs/qa/pr-001-deadbeef",
        )
        _record_qa_note(app, state)

        data = store.load(tmp_path)
        pr = store.get_pr(data, "pr-001")
        text = pr["notes"][0]["text"]
        expected = (
            "QA NEEDS_WORK: Login Flow: PASS; Dashboard: NEEDS_WORK "
            "[changes committed] "
            "(workdir: /home/user/.pm/workdirs/qa/pr-001-deadbeef)"
        )
        assert text == expected
