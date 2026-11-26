"""pm/architecture.md prompt awareness.

Covers ``notes.architecture_section`` (absent / small / over-budget documents)
and its wiring into the plan (``cli/plan.py``), implementation, bug-fix and
review (``prompt_gen.py``) prompts: with a document the prompts carry the
architecture guidance and the "File Structural Debt" filing rule; without one
they carry neither.
"""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pm_core import notes, prompt_gen, store
from pm_core.cli import cli
from pm_core.prompt_bounds import ARCHITECTURE_BUDGET, prompt_bytes


ARCH_HEADER = "## Project Architecture"
DEBT_HEADER = "## File Structural Debt, Don't Just Comment It"
DEBT_LIST_CMD = "`pm pr list --plan improvements`"
DEBT_ADD_CMD = "`pm pr add '<title>' --plan improvements --description"
DEBT_NOTE_CMD = "`pm pr note add <pr-id> '<where you hit it"
DEBT_CITE = "tracked in <pr-id>"
# Strings that only the architecture block (or the bug-fix lines gated on it)
# put in a prompt.  A prompt built without the document must contain none.
ARCH_ONLY = (ARCH_HEADER, DEBT_HEADER, DEBT_LIST_CMD, DEBT_ADD_CMD,
             "architecture.md", "Project Architecture", "Design Matrix")

PROVENANCE = "Provenance: analysed at commit 0000000 on 2026-11-26."
CHANGE_LOG_TAIL = "- newest change-log entry: FR9 split out of FR4"
SMALL_DOC = f"""# Architecture

{PROVENANCE}

## FRs / DPs
- FR1 / DP1: persistence — store.py
- FR2 / DP2: prompts — prompt_gen.py

## Design Matrix
       DP1 DP2
FR1  [  X   0 ]
FR2  [  X   X ]

## Change log
{CHANGE_LOG_TAIL}
"""


def _big_doc(size: int) -> str:
    """A document over *size* bytes whose head and tail are recognizable."""
    filler = "".join(f"- FR{i} / DP{i}: module_{i}.py\n" for i in range(size // 20))
    doc = f"# Architecture\n\n{PROVENANCE}\n\n{filler}\n## Change log\n{CHANGE_LOG_TAIL}\n"
    assert prompt_bytes(doc) > size
    return doc


@pytest.fixture
def pm_root(tmp_path, monkeypatch):
    """A throwaway standalone pm root the prompt builders resolve to.

    Without this the builders would read the real repo's ``pm/`` — and its
    ``architecture.md`` once one is committed.
    """
    root = tmp_path / "pm"
    root.mkdir()
    monkeypatch.setattr(store, "find_project_root", lambda *a, **k: root)
    return root


def _write_arch(root, text=SMALL_DOC):
    (root / notes.ARCHITECTURE_FILENAME).write_text(text)


def _assert_aware(prompt: str):
    assert ARCH_HEADER in prompt
    assert PROVENANCE in prompt
    assert DEBT_HEADER in prompt
    assert DEBT_LIST_CMD in prompt
    assert DEBT_ADD_CMD in prompt
    assert DEBT_NOTE_CMD in prompt
    assert DEBT_CITE in prompt


def _assert_clean(prompt: str):
    for needle in ARCH_ONLY:
        assert needle not in prompt, needle


# ---------------------------------------------------------------------------
# notes.architecture_section
# ---------------------------------------------------------------------------

class TestArchitectureSection:
    @pytest.mark.parametrize("prompt_type", ["plan", "impl", "review"])
    def test_absent_returns_empty(self, tmp_path, prompt_type):
        assert notes.architecture_section(tmp_path, prompt_type) == ""

    def test_whitespace_only_counts_as_absent(self, tmp_path):
        _write_arch(tmp_path, "  \n\n\t\n")
        assert notes.architecture_section(tmp_path, "impl") == ""

    def test_unreadable_counts_as_absent(self, tmp_path):
        # A directory at the path: reading raises IsADirectoryError.  The
        # document is optional context, so a prompt must still build.
        (tmp_path / notes.ARCHITECTURE_FILENAME).mkdir()
        assert notes.load_architecture(tmp_path) == ""
        assert notes.architecture_section(tmp_path, "impl") == ""

    def test_undecodable_bytes_do_not_crash(self, tmp_path):
        (tmp_path / notes.ARCHITECTURE_FILENAME).write_bytes(
            b"# Architecture\n\xff\xfe bad bytes\nFR1 / DP1\n")
        block = notes.architecture_section(tmp_path, "impl")
        assert "FR1 / DP1" in block

    def test_ensure_notes_file_does_not_create_it(self, tmp_path):
        # Creating a placeholder would switch the guidance on for every
        # project, so only an explicit document does.
        notes.ensure_notes_file(tmp_path)
        assert not (tmp_path / notes.ARCHITECTURE_FILENAME).exists()

    def test_small_document_inlined_whole(self, tmp_path):
        _write_arch(tmp_path)
        block = notes.architecture_section(tmp_path, "impl")
        assert SMALL_DOC.strip() in block
        assert "truncated to fit" not in block
        _assert_aware(block)

    def test_over_budget_document_is_abbreviated_with_pointer(self, tmp_path):
        doc = _big_doc(3 * ARCHITECTURE_BUDGET)
        _write_arch(tmp_path, doc)
        block = notes.architecture_section(tmp_path, "impl")
        pointer = notes.architecture_pointer(tmp_path)
        # The excerpt is bounded and its marker names the file to read.
        assert "architecture document truncated to fit" in block
        assert f"Read the full text: `{pointer}`" in block
        # Head (provenance, FRs) and tail (newest change-log entry) survive.
        assert PROVENANCE in block
        assert CHANGE_LOG_TAIL in block
        # Bounded: the excerpt budget plus the fixed guidance/rule text.
        static = notes.architecture_section(tmp_path, "impl", max_bytes=0)
        assert prompt_bytes(block) <= ARCHITECTURE_BUDGET + prompt_bytes(static)
        assert prompt_bytes(block) < prompt_bytes(doc)

    def test_guidance_and_rule_survive_abbreviation(self, tmp_path):
        # Only the document excerpt is bounded; the instructions are whole.
        _write_arch(tmp_path, _big_doc(3 * ARCHITECTURE_BUDGET))
        block = notes.architecture_section(tmp_path, "review", max_bytes=500)
        _assert_aware(block)
        assert "**NEEDS_WORK**" in block
        assert "**INPUT_REQUIRED**" in block

    def test_multibyte_document_bounded_in_bytes(self, tmp_path):
        _write_arch(tmp_path, "# Architektur — Übersicht\n" + "ü" * 40_000)
        block = notes.architecture_section(tmp_path, "plan", max_bytes=4_000)
        static = notes.architecture_section(tmp_path, "plan", max_bytes=0)
        assert prompt_bytes(block) <= 4_000 + prompt_bytes(static)

    def test_pointer_in_repo_pm_dir(self, tmp_path):
        (tmp_path / ".git").mkdir()
        root = tmp_path / "pm"
        root.mkdir()
        _write_arch(root)
        assert notes.architecture_pointer(root) == "pm/architecture.md"
        assert "`pm/architecture.md`" in notes.architecture_section(root, "impl")

    def test_pointer_standalone_pm_dir_is_absolute(self, tmp_path):
        # A standalone pm dir is not part of the target repo's clones, so
        # only the absolute path resolves.
        _write_arch(tmp_path)
        expected = str(tmp_path / "architecture.md")
        assert notes.architecture_pointer(tmp_path) == expected
        assert f"`{expected}`" in notes.architecture_section(tmp_path, "impl")

    def test_role_guidance_differs(self, tmp_path):
        _write_arch(tmp_path)
        plan = notes.architecture_section(tmp_path, "plan")
        impl = notes.architecture_section(tmp_path, "impl", pr_id="pr-abc")
        review = notes.architecture_section(tmp_path, "review")
        assert "While planning:" in plan
        assert "say so explicitly in the plan file" in plan
        assert "cite its id in the plan" in plan
        assert "While implementing:" in impl
        assert "pm pr note add pr-abc 'architecture:" in impl
        assert "While reviewing" in review
        assert "**NEEDS_WORK**" in review
        assert "review-loop mode" in review
        for block in (plan, impl, review):
            _assert_aware(block)
            # Common awareness: reuse the map, no upward or hidden coupling.
            assert "instead of re-deriving" in block
            assert "upward `*` coupling" in block
            assert "lazy (function-level) import" in block
            assert "hidden shared-state cycles" in block

    def test_impl_note_command_without_pr_id_uses_placeholder(self, tmp_path):
        _write_arch(tmp_path)
        block = notes.architecture_section(tmp_path, "impl")
        assert "pm pr note add <pr-id> 'architecture:" in block

    def test_unknown_prompt_type_raises_even_without_document(self, tmp_path):
        with pytest.raises(ValueError):
            notes.architecture_section(tmp_path, "qa")


# ---------------------------------------------------------------------------
# prompt_gen: implementation, bug-fix and review prompts
# ---------------------------------------------------------------------------

def _data(pr: dict) -> dict:
    return {
        "project": {"base_branch": "master", "backend": "github"},
        "prs": [pr],
        "plans": [],
    }


_FEATURE = {"id": "pr-f", "title": "Feature", "description": "do it"}
_BUG = {"id": "pr-b", "title": "Bug", "plan": "bugs", "description": "broken"}


class TestImplPrompt:
    def test_includes_architecture_when_present(self, pm_root):
        _write_arch(pm_root)
        p = prompt_gen.generate_prompt(_data(dict(_FEATURE)), "pr-f")
        _assert_aware(p)
        assert "While implementing:" in p
        assert "pm pr note add pr-f 'architecture:" in p

    def test_clean_when_absent(self, pm_root):
        p = prompt_gen.generate_prompt(_data(dict(_FEATURE)), "pr-f")
        _assert_clean(p)

    def test_clean_without_project_root(self, monkeypatch):
        def _missing(*a, **k):
            raise FileNotFoundError("no project.yaml")
        monkeypatch.setattr(store, "find_project_root", _missing)
        p = prompt_gen.generate_prompt(_data(dict(_FEATURE)), "pr-f")
        _assert_clean(p)

    def test_large_document_keeps_prompt_bounded(self, pm_root):
        doc = _big_doc(100_000)
        _write_arch(pm_root, doc)
        p = prompt_gen.generate_prompt(_data(dict(_FEATURE)), "pr-f")
        assert "architecture document truncated to fit" in p
        assert CHANGE_LOG_TAIL in p
        _write_arch(pm_root, SMALL_DOC)
        small = prompt_gen.generate_prompt(_data(dict(_FEATURE)), "pr-f")
        # The document adds at most its excerpt budget over a small one.
        assert prompt_bytes(p) <= prompt_bytes(small) + ARCHITECTURE_BUDGET


class TestBugFixPrompts:
    def test_impl_bug_flow_points_at_architecture_when_present(self, pm_root):
        _write_arch(pm_root)
        p = prompt_gen.generate_prompt(_data(dict(_BUG)), "pr-b")
        _assert_aware(p)
        assert "Bug Fix Flow" in p
        flow = p[p.index("## Bug Fix Flow"):]
        assert "inside the DP that owns it" in flow
        assert "File\n   Structural Debt, Don't Just Comment It" in flow

    def test_impl_bug_flow_clean_when_absent(self, pm_root):
        p = prompt_gen.generate_prompt(_data(dict(_BUG)), "pr-b")
        assert "Bug Fix Flow" in p
        _assert_clean(p)
        assert "inside the DP that owns it" not in p

    def test_review_bug_checklist_points_at_architecture_when_present(self, pm_root):
        _write_arch(pm_root)
        r = prompt_gen.generate_review_prompt(_data(dict(_BUG)), "pr-b")
        _assert_aware(r)
        checklist = r[r.index("## Bug Fix Review Checklist"):]
        assert "inside the owning DP" in checklist
        assert "cites a filed `improvements` PR id" in checklist

    def test_review_bug_checklist_clean_when_absent(self, pm_root):
        r = prompt_gen.generate_review_prompt(_data(dict(_BUG)), "pr-b")
        assert "Bug Fix Review Checklist" in r
        _assert_clean(r)
        assert "inside the owning DP" not in r

    def test_blocks_unchanged_by_default(self):
        # Callers that don't pass has_architecture get today's text.
        pr = dict(_BUG)
        assert "Project Architecture" not in prompt_gen._bug_fix_flow_block(pr)
        assert "Project Architecture" not in prompt_gen._bug_fix_review_block(pr)


class TestReviewPrompt:
    def test_includes_architecture_when_present(self, pm_root):
        _write_arch(pm_root)
        r = prompt_gen.generate_review_prompt(_data(dict(_FEATURE)), "pr-f")
        _assert_aware(r)
        assert "While reviewing" in r
        # The architectural-review step points at the block.
        steps = r[r.index("## Steps"):]
        assert "**Project Architecture** above" in steps

    def test_clean_when_absent(self, pm_root):
        r = prompt_gen.generate_review_prompt(_data(dict(_FEATURE)), "pr-f")
        _assert_clean(r)
        assert "**Project Architecture** above" not in r

    def test_review_loop_inherits_architecture(self, pm_root):
        _write_arch(pm_root)
        r = prompt_gen.generate_review_prompt(
            _data(dict(_FEATURE)), "pr-f", review_loop=True,
            review_iteration=1, review_loop_id="abcd")
        _assert_aware(r)
        assert "Review Loop Mode" in r


# ---------------------------------------------------------------------------
# cli/plan.py: plan add / breakdown / review / import
# ---------------------------------------------------------------------------

def _plan_state(root, with_prs: bool):
    plan = {"id": "pl-001", "name": "Plan", "file": "plans/pl-001.md"}
    prs = []
    if with_prs:
        prs.append({"id": "pr-p1", "title": "Plan PR", "plan": "pl-001",
                    "status": "pending", "depends_on": [],
                    "description": "d", "branch": None, "workdir": None,
                    "gh_pr_number": None, "notes": []})
    data = {"project": {"name": "test", "repo": "/tmp/fake",
                        "base_branch": "master"},
            "plans": [plan], "prs": prs}
    store.save(data, root)
    (root / "plans").mkdir(exist_ok=True)
    (root / "plans" / "pl-001.md").write_text("# Plan\n\n## PRs\n")


_PLAN_COMMANDS = {
    "add": ["plan", "add", "new-plan"],
    "breakdown": ["plan", "breakdown", "pl-001"],
    "review-preload": ["plan", "review", "pl-001"],
    "review-postload": ["plan", "review", "pl-001"],
    "import": ["plan", "import", "--name", "Imported"],
}


def _plan_prompt(root, which: str) -> str:
    _plan_state(root, with_prs=(which == "review-postload"))
    # Without claude the builders print the assembled prompt.
    with patch("pm_core.cli.plan.find_claude", return_value=None), \
         patch("pm_core.cli.plan.trigger_tui_refresh"), \
         patch("pm_core.cli.plan._get_pm_session", return_value=None):
        result = CliRunner().invoke(
            cli, ["-C", str(root)] + _PLAN_COMMANDS[which])
    assert result.exit_code == 0, result.output
    return result.output


class TestPlanPrompts:
    @pytest.mark.parametrize("which", sorted(_PLAN_COMMANDS))
    def test_includes_architecture_when_present(self, pm_root, which):
        _write_arch(pm_root)
        out = _plan_prompt(pm_root, which)
        _assert_aware(out)
        assert "While planning:" in out
        assert "cite its id in the plan" in out

    @pytest.mark.parametrize("which", sorted(_PLAN_COMMANDS))
    def test_clean_when_absent(self, pm_root, which):
        out = _plan_prompt(pm_root, which)
        _assert_clean(out)

    def test_plan_deps_is_not_a_planning_prompt(self, pm_root):
        # deps edits the dependency graph only; it carries no FR/DP guidance.
        _write_arch(pm_root)
        _plan_state(pm_root, with_prs=True)
        with patch("pm_core.cli.plan.find_claude", return_value=None), \
             patch("pm_core.cli.plan._get_pm_session", return_value=None):
            result = CliRunner().invoke(cli, ["-C", str(pm_root), "plan", "deps"])
        assert result.exit_code == 0, result.output
        assert ARCH_HEADER not in result.output
