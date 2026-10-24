"""Tests for prompt-size bounds (pr-ace66e5).

Prompts are delivered to claude as one argv entry.  Linux caps a single
argument at MAX_ARG_STRLEN (128 KiB); exceeding it fails ``execve`` with
E2BIG.  Builders that inline collections must keep their output within
``PROMPT_ARG_LIMIT`` and, when they trim, name what was omitted plus a way to
read the full detail.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from pm_core import prompt_gen, spec_gen, store
from pm_core.claude_launcher import (
    _materialize_oversized_prompt, build_claude_shell_cmd,
)
from pm_core.cli import cli
from pm_core.prompt_bounds import (
    PROMPT_ARG_LIMIT, PromptTooLargeError, bounded_join, bounded_lines,
    bounded_text, prompt_bytes, prompt_fits,
)
from pm_core.qa_finalize_prompt import build_qa_finalize_prompt
from pm_core.qa_loop import (
    QAScenario, _build_concretization_prompt, _build_verification_prompt,
)


@pytest.fixture(autouse=True)
def _isolated_pm_root(tmp_path, monkeypatch):
    """Point builders at a throwaway pm/ root.

    Builders read notes / the QA library and write spec dirs relative to the
    project root; without this they would read the real repo's ``pm/`` (and
    create spec dirs there).
    """
    root = tmp_path / "pm"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(store, "find_project_root", lambda *a, **k: root)
    return root


def _note(i, size=2000):
    return {"id": f"note-{i:04d}", "text": f"note {i} " + "x" * size,
            "created_at": f"2026-01-{i % 28 + 1:02d}T00:00:00Z"}


def _pr(pr_id="pr-x", **kw):
    pr = {"id": pr_id, "title": "T", "description": "D",
          "branch": f"pm/{pr_id}", "status": "in_progress",
          "depends_on": [], "workdir": "", "plan": None, "notes": []}
    pr.update(kw)
    return pr


def _data(pr, siblings=None, plans=None):
    prs = [pr] + (siblings or [])
    if plans is None:
        plan_ids = sorted({p.get("plan") for p in prs if p.get("plan")})
        plans = [{"id": pid, "name": f"plan {pid}",
                  "file": f"plans/{pid}.md"} for pid in plan_ids]
    return {"project": {"name": "p", "base_branch": "master",
                        "backend": "github", "repo": "r"},
            "prs": prs, "plans": plans}


def _assert_bounded(prompt, *needles):
    size = prompt_bytes(prompt)
    assert size <= PROMPT_ARG_LIMIT, f"prompt is {size} bytes"
    for needle in needles:
        assert needle in prompt, f"missing pointer: {needle!r}"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class TestPromptBytes:
    def test_counts_utf8_bytes(self):
        assert prompt_bytes("abc") == 3
        assert prompt_bytes("é") == 2
        assert prompt_bytes("") == 0

    def test_prompt_fits(self):
        assert prompt_fits("x" * 10, limit=10)
        assert not prompt_fits("x" * 11, limit=10)


class TestBoundedJoin:
    def test_max_items(self):
        out = bounded_join([1, 2, 3, 4], str, max_items=2,
                           omitted_note=lambda n: f"(+{n})")
        assert out == "1\n2\n(+2)"

    def test_max_bytes(self):
        out = bounded_join(["aaaa", "bbbb", "cccc"], str, max_bytes=9)
        assert out.startswith("aaaa\nbbbb")
        assert "omitted" in out

    def test_keep_newest_restores_order(self):
        out = bounded_join([1, 2, 3, 4], str, max_items=2, keep="newest",
                           omitted_note=lambda n: f"(+{n})")
        assert out == "3\n4\n(+2)"

    def test_empty_returns_empty_without_marker(self):
        assert bounded_join([], str) == ""

    def test_no_omission_no_marker(self):
        assert bounded_join(["a", "b"], str, max_items=5) == "a\nb"


class TestBoundedText:
    def test_passthrough_under_budget(self):
        assert bounded_text("short", max_bytes=100, pointer="p") == "short"

    def test_head_tail_and_pointer(self):
        out = bounded_text("h" * 500 + "t" * 500, max_bytes=200,
                           pointer="`pm pr spec p impl`", label="spec")
        assert prompt_bytes(out) <= 200
        assert "truncated" in out
        assert "`pm pr spec p impl`" in out
        assert out.startswith("h") and out.endswith("t")

    def test_multibyte_boundary_not_split(self):
        out = bounded_text("é" * 1000, max_bytes=101, pointer="p", label="x")
        assert prompt_bytes(out) <= 101
        assert "é" in out

    def test_marker_survives_tiny_budget(self):
        out = bounded_text("z" * 5000, max_bytes=10, pointer="POINTER", label="x")
        assert "POINTER" in out


class TestBoundedLines:
    def test_passthrough(self):
        assert bounded_lines("a\nb\nc", max_lines=5) == "a\nb\nc"

    def test_truncates_head_and_tail(self):
        text = "\n".join(str(i) for i in range(100))
        out = bounded_lines(text, max_lines=10)
        assert "lines omitted" in out
        assert out.startswith("0") and out.endswith("99")

    def test_byte_bound_with_pointer(self):
        text = "\n".join("x" * 100 for _ in range(100))
        out = bounded_lines(text, max_lines=100, max_bytes=300,
                            pointer="file X", label="out")
        assert prompt_bytes(out) <= 300
        assert "file X" in out


# ---------------------------------------------------------------------------
# prompt_gen builders
# ---------------------------------------------------------------------------

class TestPrNotesBounding:
    def test_many_notes_bounded_with_pointer(self):
        pr = _pr(notes=[_note(i) for i in range(300)])
        p = prompt_gen.generate_prompt(_data(pr), "pr-x")
        _assert_bounded(p, "pm pr note list")

    def test_small_notes_stay_full(self):
        pr = _pr(notes=[{"id": "n1", "text": "keepme", "created_at": ""}])
        p = prompt_gen.generate_prompt(_data(pr), "pr-x")
        assert "keepme" in p
        assert "pm pr note list" not in p

    def test_full_and_bounded_renders_both_end_with_newline(self):
        """The block is embedded in prompts; both renderings must terminate
        the section so following blocks cannot run into the last note."""
        small = prompt_gen._format_pr_notes(
            _pr(notes=[{"id": "n1", "text": "hi", "created_at": ""}]))
        big = prompt_gen._format_pr_notes(_pr(notes=[_note(i) for i in range(300)]))
        assert small.endswith("\n") and big.endswith("\n")

    def test_abbreviated_notes_say_so(self):
        """Newest notes are kept in full and older ones summarized; the
        summary must be explained, not silent."""
        pr = _pr(notes=[_note(i, size=300) for i in range(120)])
        block = prompt_gen._format_pr_notes(pr)
        assert "abbreviated" in block
        assert "pm pr note list" in block


class TestReviewPromptBounding:
    def test_many_siblings_and_notes(self):
        pr = _pr(notes=[_note(i) for i in range(300)], plan="pl-1")
        siblings = [_pr(f"pr-s{i:03d}", plan="pl-1", title="S" * 200)
                    for i in range(200)]
        p = prompt_gen.generate_review_prompt(_data(pr, siblings), "pr-x")
        _assert_bounded(p, "pm pr list --plan pl-1", "pm pr note list")


class TestSignoffPromptBounding:
    def test_many_notes_scenarios_and_integration(self, tmp_path, monkeypatch):
        status = tmp_path / "qa_status.json"
        status.write_text(json.dumps({
            "overall": "PASS",
            "scenarios": [{"index": i, "title": "S" * 100, "verdict": "PASS",
                           "verdict_reason": "r" * 500} for i in range(100)],
        }))
        monkeypatch.setattr("pm_core.paths.latest_qa_status_path",
                            lambda pr_id: status)
        pr = _pr(
            notes=[_note(i) for i in range(300)],
            integration={"base_branch": "master", "base_sha": "a" * 40,
                         "target_repo": "r", "status": "clean",
                         "overlap": [f"f{i}.py" for i in range(200)],
                         "conflicts": [f"c{i}.py" for i in range(200)]},
        )
        p = prompt_gen.generate_signoff_prompt(_data(pr), "pr-x")
        _assert_bounded(p, "pm pr note list")

    def test_signoff_return_block_bounds_integration_paths(self):
        """The return block (appended to impl/review/QA prompts) inlines the
        same overlap/conflict path lists; bound them like the sign-off one."""
        from pm_core.signoff import format_signoff_return
        pr = _pr(signoff_return={
            "verdict": "NEEDS_WORK", "hop": "impl", "reason": "conflict",
            "reviewed_head": "b" * 40,
            "integration": {
                "base_branch": "master", "base_sha": "a" * 40,
                "target_repo": "r", "status": "conflict",
                "conflicts": [f"c{i}.py" for i in range(500)],
                "overlap": [f"f{i}.py" for i in range(500)],
            },
        })
        block = format_signoff_return(pr)
        assert prompt_bytes(block) < 5_000
        assert "(+480 more" in block

    def test_signoff_return_block_bounds_when_embedded_in_prompts(self):
        pr = _pr(notes=[_note(i) for i in range(300)], signoff_return={
            "verdict": "NEEDS_WORK", "hop": "impl", "reason": "r" * 200,
            "reviewed_head": "b" * 40,
            "integration": {
                "base_branch": "master", "base_sha": "a" * 40,
                "target_repo": "r", "status": "conflict",
                "conflicts": [f"c{i}.py" for i in range(2000)],
                "overlap": [f"f{i}.py" for i in range(2000)],
            },
        })
        p = prompt_gen.generate_prompt(_data(pr), "pr-x")
        _assert_bounded(p, "pm pr note list", "(+1980 more")

    def test_integration_markers_name_the_full_record(self, monkeypatch):
        """An abbreviated path list must say where the rest can be read —
        `(+N more)` on its own is silent loss."""
        monkeypatch.setattr(
            "pm_core.integration.integration_json_path",
            lambda pr_id: Path("/cap") / pr_id / "integration.json")
        integ = {"base_branch": "master", "base_sha": "a" * 40,
                 "target_repo": "r", "status": "clean",
                 "overlap": [f"f{i}.py" for i in range(200)],
                 "conflicts": [f"c{i}.py" for i in range(200)]}
        block = prompt_gen._signoff_integration_block(_pr(integration=integ),
                                                      "pr-x")
        assert "(+180 more" in block
        assert "/cap/pr-x/integration.json" in block

        from pm_core.signoff import format_signoff_return
        ret = format_signoff_return(_pr(signoff_return={
            "verdict": "NEEDS_WORK", "hop": "impl", "reason": "conflict",
            "reviewed_head": "b" * 40, "integration": integ}))
        assert "(+180 more" in ret
        assert "/cap/pr-x/integration.json" in ret

    def test_integration_marker_falls_back_to_pr_show(self, monkeypatch):
        monkeypatch.setattr("pm_core.integration.integration_json_path",
                            lambda pr_id: None)
        block = prompt_gen._signoff_integration_block(
            _pr(integration={"base_branch": "master", "base_sha": "a" * 40,
                             "target_repo": "r", "status": "clean",
                             "conflicts": [f"c{i}.py" for i in range(100)]}),
            "pr-x")
        assert "(+80 more; run `pm pr show pr-x`)" in block


class TestQaPromptsBounding:
    def test_planner_many_notes(self):
        pr = _pr(notes=[_note(i) for i in range(300)])
        p = prompt_gen.generate_qa_planner_prompt(_data(pr), "pr-x")
        _assert_bounded(p, "pm pr note list")

    def test_interactive_many_notes(self):
        pr = _pr(notes=[_note(i) for i in range(300)])
        p = prompt_gen.generate_qa_interactive_prompt(
            _data(pr), "pr-x", "/tmp/w")
        _assert_bounded(p, "pm pr note list")

    def test_child_many_artifacts_and_huge_steps(self):
        pr = _pr()
        scenario = QAScenario(
            index=1, title="S", focus="F",
            artifact_paths=[f"/tmp/recipe-{i}.md" for i in range(100)],
            steps="GIVEN x\n" * 20000,
        )
        p = prompt_gen.generate_qa_child_prompt(
            _data(pr), "pr-x", scenario, workdir="/tmp/w",
            captures_root="/tmp/cap")
        _assert_bounded(p, "pm qa list")


class TestMergeAndWatcherBounding:
    def test_merge_huge_error(self):
        pr = _pr()
        p = prompt_gen.generate_merge_prompt(
            _data(pr), "pr-x", "E" * 200000)
        _assert_bounded(p, "re-run the failed update")

    def test_watcher_many_managed_prs(self):
        prs = [_pr(f"pr-{i:03d}",
                   depends_on=([f"pr-{i-1:03d}"] if i else []))
               for i in range(200)]
        data = {"project": {"name": "p", "base_branch": "master"},
                "prs": prs, "plans": []}
        p = prompt_gen.generate_watcher_prompt(
            data, auto_start_targets=["pr-199"])
        _assert_bounded(p, "pm pr list")


# ---------------------------------------------------------------------------
# spec_gen / qa_instructions / qa_finalize / qa_loop
# ---------------------------------------------------------------------------

class TestSpecBounding:
    def test_huge_spec_bounded_with_pointer(self, monkeypatch):
        monkeypatch.setattr(spec_gen, "get_spec", lambda pr, phase: "s" * 200000)
        pr = _pr()
        block = spec_gen.format_spec_for_prompt(pr, "impl")
        # SPEC_BUDGET bounds the spec text; the template adds a few hundred
        # bytes of framing.
        assert prompt_bytes(block) <= 31_000
        assert "pm pr spec" in block
        assert "truncated" in block

    def test_prior_spec_in_spec_prompt_bounded(self, monkeypatch):
        monkeypatch.setattr(spec_gen, "get_spec", lambda pr, phase: "s" * 200000)
        pr = _pr()
        prompt = spec_gen._build_spec_prompt(
            {"project": {"base_branch": "master"}}, pr, "qa")
        assert prompt_bytes(prompt) <= 40_000


class TestQaInstructionsBounding:
    def _write_items(self, directory, n, body="body"):
        directory.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (directory / f"item-{i:03d}.md").write_text(
                f"---\ntitle: Item {i}\ndescription: desc {i}\n---\n{body}\n")

    def test_instruction_summary_caps_each_category(self, _isolated_pm_root):
        from pm_core import qa_instructions
        self._write_items(_isolated_pm_root / "qa" / "instructions", 60)
        self._write_items(_isolated_pm_root / "qa" / "artifacts", 60)
        out = qa_instructions.instruction_summary_for_prompt(_isolated_pm_root)
        assert out.count("- **Item ") <= 40  # 20 per category
        assert "more; run `pm qa list`" in out

    def test_mocks_for_prompt_bounded(self, _isolated_pm_root):
        from pm_core import qa_instructions
        self._write_items(_isolated_pm_root / "qa" / "mocks", 40,
                          body="m" * 3000)
        out = qa_instructions.mocks_for_prompt(_isolated_pm_root)
        assert prompt_bytes(out) <= 12_000 + 400


class TestQaFinalizeBounding:
    def test_many_scenarios_bounded(self):
        worktrees = [(i, "PASS", f"/tmp/s{i}") for i in range(100)]
        p = build_qa_finalize_prompt(
            pr_id="pr-x", pr_title="T", branch="b", pr_workdir="/tmp/w",
            scenario_worktrees=worktrees, overall_verdict="PASS")
        _assert_bounded(p, "qa_resume.json")


class TestQaLoopPromptsBounding:
    def test_concretization_huge_instruction_and_steps(self):
        scenario = QAScenario(index=1, title="S", focus="F",
                              steps="GIVEN x\n" * 20000)
        p = _build_concretization_prompt(
            scenario, "b", "master",
            instruction_content="i" * 200000, pr_id="pr-x")
        _assert_bounded(p, "instruction file")

    def test_verification_many_artifacts_and_huge_output(self):
        scenario = QAScenario(
            index=1, title="S", focus="F", steps="GIVEN x\n" * 20000,
            artifact_paths=[f"/tmp/recipe-{i}.md" for i in range(100)])
        p = _build_verification_prompt(
            scenario, "PASS", pane_output="line\n" * 100000)
        _assert_bounded(p, "pm qa list")

    def test_verification_long_lines_bounded(self):
        """The line bound alone does not bound the prompt: a single enormous
        line is one line.  The byte cap must catch it and name the transcript
        so the verifier can still read the rest."""
        scenario = QAScenario(index=1, title="S", focus="F",
                              steps="GIVEN x\n" * 20000)
        p = _build_verification_prompt(
            scenario, "PASS", pane_output="y" * 400_000)
        _assert_bounded(p, "the full scenario transcript")


# ---------------------------------------------------------------------------
# notes
# ---------------------------------------------------------------------------

class TestNotesBounding:
    def test_notes_for_prompt_bounded(self, _isolated_pm_root):
        from pm_core import notes as notes_mod
        (_isolated_pm_root / "notes.txt").write_text(
            "## General\n" + "g" * 100000 + "\n\n"
            "## Implementation\n" + "i" * 100000 + "\n")
        general, specific = notes_mod.notes_for_prompt(
            _isolated_pm_root, "impl")
        assert prompt_bytes(general) <= 8_000 + 400
        assert prompt_bytes(specific) <= 8_000 + 400
        assert "pm notes" in general

    def test_notes_section_bounded(self, _isolated_pm_root):
        from pm_core import notes as notes_mod
        (_isolated_pm_root / "notes.txt").write_text(
            "## General\n" + "g" * 100000 + "\n")
        block = notes_mod.notes_section(_isolated_pm_root)
        assert prompt_bytes(block) <= 8_000 + 400
        assert "pm notes" in block


# ---------------------------------------------------------------------------
# launcher guard
# ---------------------------------------------------------------------------

class TestLauncherGuard:
    def test_shell_cmd_uses_bootstrap_over_limit(self, tmp_path):
        huge = "x" * (PROMPT_ARG_LIMIT + 1000)
        with patch("pm_core.claude_launcher.log_shell_command"), \
             patch("pm_core.paths.skip_permissions_enabled", return_value=False):
            cmd = build_claude_shell_cmd(prompt=huge, cwd=str(tmp_path))
        assert "$(cat" not in cmd
        assert "Read that file" in cmd
        files = list((tmp_path / "pm" / "prompts").glob("pm_prompt_*.txt"))
        assert files and files[0].read_text() == huge

    def test_shell_cmd_small_prompt_uses_cat(self, tmp_path):
        with patch("pm_core.claude_launcher.log_shell_command"), \
             patch("pm_core.paths.skip_permissions_enabled", return_value=False):
            cmd = build_claude_shell_cmd(prompt="hello", cwd=str(tmp_path))
        assert "$(cat" in cmd

    def test_shell_cmd_no_writable_dir_raises(self):
        huge = "x" * (PROMPT_ARG_LIMIT + 1)
        with patch("pm_core.claude_launcher.log_shell_command"), \
             patch("pm_core.paths.skip_permissions_enabled", return_value=False):
            with pytest.raises(PromptTooLargeError):
                build_claude_shell_cmd(prompt=huge)

    def test_materialize_passthrough(self):
        argv, tmp = _materialize_oversized_prompt("hello", cwd=None)
        assert argv == "hello" and tmp is None

    def test_materialize_writes_full_prompt(self, tmp_path):
        huge = "y" * (PROMPT_ARG_LIMIT + 5)
        argv, tmp = _materialize_oversized_prompt(huge, cwd=str(tmp_path))
        assert tmp is not None
        assert Path(tmp).read_text() == huge
        assert "Read that file" in argv
        assert prompt_bytes(argv) < 1000
        Path(tmp).unlink()

    def test_materialize_no_location_raises(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        # No cwd/write_dir and mkstemp fails -> clear error, not OSError.
        with patch("pm_core.claude_launcher.tempfile.mkstemp",
                   side_effect=OSError("no temp")):
            with pytest.raises(PromptTooLargeError):
                _materialize_oversized_prompt("z" * (PROMPT_ARG_LIMIT + 1))


# ---------------------------------------------------------------------------
# pm pr show
# ---------------------------------------------------------------------------

def _make_state(tmp_path, notes=None):
    pr = {
        "id": "pr-001", "plan": None, "title": "Test PR",
        "branch": "pm/pr-001-test", "status": "in_progress",
        "depends_on": [], "description": "A test PR",
        "agent_machine": None, "gh_pr": None, "gh_pr_number": None,
    }
    if notes is not None:
        pr["notes"] = notes
    data = {
        "project": {"name": "test", "repo": "/tmp/fake",
                    "base_branch": "master"},
        "plans": [], "prs": [pr],
    }
    store.save(data, tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# pm_core/cli/plan.py builders
# ---------------------------------------------------------------------------

def _make_plan_state(tmp_path, plan_prs, other_prs):
    plan = {"id": "pl-001", "name": "Plan", "file": "plans/pl-001.md"}
    prs = []
    for i in range(plan_prs):
        prs.append({"id": f"pr-p{i:03d}", "title": f"Plan PR {i}",
                    "plan": "pl-001", "status": "pending", "depends_on": [],
                    "description": "d" * 500, "branch": None, "workdir": None,
                    "gh_pr_number": None, "notes": []})
    for i in range(other_prs):
        prs.append({"id": f"pr-o{i:03d}", "title": f"Other PR {i}",
                    "plan": "pl-002", "status": "pending", "depends_on": [],
                    "description": "d" * 500, "branch": None, "workdir": None,
                    "gh_pr_number": None, "notes": []})
    data = {"project": {"name": "test", "repo": "/tmp/fake",
                        "base_branch": "master"},
            "plans": [plan], "prs": prs}
    store.save(data, tmp_path)
    (tmp_path / "plans").mkdir(exist_ok=True)
    (tmp_path / "plans" / "pl-001.md").write_text("# Plan\n\n## PRs\n")
    return tmp_path


class TestPlanPromptBounding:
    """The plan builders print their prompt when claude is unavailable, so
    the printed output is the assembled prompt (plus a short banner)."""

    def test_plan_review_many_prs_bounded(self, tmp_path):
        root = _make_plan_state(tmp_path, plan_prs=300, other_prs=300)
        with patch("pm_core.cli.plan.find_claude", return_value=None):
            result = CliRunner().invoke(
                cli, ["-C", str(root), "plan", "review", "pl-001"])
        assert result.exit_code == 0, result.output
        assert prompt_bytes(result.output) <= PROMPT_ARG_LIMIT + 300

    def test_plan_deps_many_prs_bounded(self, tmp_path):
        root = _make_plan_state(tmp_path, plan_prs=200, other_prs=0)
        with patch("pm_core.cli.plan.find_claude", return_value=None):
            result = CliRunner().invoke(cli, ["-C", str(root), "plan", "deps"])
        assert result.exit_code == 0, result.output
        assert prompt_bytes(result.output) <= PROMPT_ARG_LIMIT + 300

    def test_plan_breakdown_many_existing_prs_bounded(self, tmp_path):
        root = _make_plan_state(tmp_path, plan_prs=0, other_prs=300)
        with patch("pm_core.cli.plan.find_claude", return_value=None):
            result = CliRunner().invoke(
                cli, ["-C", str(root), "plan", "breakdown", "pl-001"])
        assert result.exit_code == 0, result.output
        assert prompt_bytes(result.output) <= PROMPT_ARG_LIMIT + 300


def _make_big_plan_state(tmp_path, n_prs, n_plans, desc_size, plan_size):
    """A project with large PR descriptions and many large plan files.

    Realistic magnitudes taken from this repo: descriptions reach 11 KB and
    there are 22 plan files totalling ~500 KB.  A per-item cap alone is not
    enough for these builders — the aggregate is what blows the argv limit.
    """
    plans = [{"id": f"pl-{i:03d}", "name": f"Plan {i}",
              "file": f"plans/pl-{i:03d}.md", "status": "draft"}
             for i in range(n_plans)]
    prs = [{"id": f"pr-{i:03d}", "title": f"PR {i}", "plan": None,
            "status": "pending", "depends_on": [],
            "description": "d" * desc_size, "branch": None, "workdir": None,
            "gh_pr_number": None, "notes": []}
           for i in range(n_prs)]
    data = {"project": {"name": "test", "repo": "/tmp/fake",
                        "base_branch": "master"},
            "plans": plans, "prs": prs}
    store.save(data, tmp_path)
    (tmp_path / "plans").mkdir(exist_ok=True)
    for p in plans:
        (tmp_path / p["file"]).write_text("# Plan\n\n" + "p" * plan_size + "\n")
    return tmp_path


class TestPlanDepsAndFixBounding:
    """`pm plan deps` inlines every PR description and every plan file, and
    `pm plan fix` inlines every plan file.  Both were still unbounded after
    the first pass: 312 KB and ~500 KB on this repo's real data, because the
    count cap and the per-file budget do not bound their product."""

    def test_plan_deps_bounds_descriptions_and_plan_files(self, tmp_path):
        root = _make_big_plan_state(tmp_path, n_prs=60, n_plans=22,
                                    desc_size=11_000, plan_size=40_000)
        with patch("pm_core.cli.plan.find_claude", return_value=None):
            result = CliRunner().invoke(cli, ["-C", str(root), "plan", "deps"])
        assert result.exit_code == 0, result.output
        # Bounded, and both abbreviations name where the full text lives.
        _assert_bounded(result.output, "pm pr show", "omitted to fit the prompt")

    def test_plan_fix_bounds_plan_context(self, tmp_path):
        root = _make_big_plan_state(tmp_path, n_prs=0, n_plans=22,
                                    desc_size=0, plan_size=40_000)
        review = tmp_path / "review.txt"
        review.write_text("Step: plan add\nStatus: NEEDS_FIX\n\n"
                          "## Review Findings\nthin plan\n\n"
                          "## Fix Command\npm plan fix --review x\n")
        with patch("pm_core.cli.plan.find_claude", return_value=None):
            result = CliRunner().invoke(
                cli, ["-C", str(root), "plan", "fix", "--review", str(review)])
        assert result.exit_code == 0, result.output
        _assert_bounded(result.output, "plan files under", "truncated")


class TestPrShowCommand:
    def test_prints_full_detail(self, tmp_path):
        root = _make_state(tmp_path, notes=[
            {"id": "note-abc", "text": "important handoff",
             "created_at": "2026-01-01T00:00:00Z"}])
        result = CliRunner().invoke(
            cli, ["-C", str(root), "pr", "show", "pr-001"])
        assert result.exit_code == 0, result.output
        assert "Test PR" in result.output
        assert "A test PR" in result.output
        assert "important handoff" in result.output

    def test_unknown_id_errors(self, tmp_path):
        root = _make_state(tmp_path)
        result = CliRunner().invoke(
            cli, ["-C", str(root), "pr", "show", "nope"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_prints_integration_record(self, tmp_path, monkeypatch):
        """`pm pr show` is the fallback pointer for abbreviated integration
        path lists, so it has to print that record."""
        monkeypatch.setattr("pm_core.integration.integration_json_path",
                            lambda pr_id: Path("/cap") / pr_id / "integration.json")
        root = _make_state(tmp_path)
        data = store.load(root)
        data["prs"][0]["integration"] = {
            "base_branch": "master", "base_sha": "a" * 40,
            "target_repo": "r", "status": "clean",
            "overlap": ["a.py", "b.py"], "conflicts": ["c.py"]}
        store.save(data, root)
        result = CliRunner().invoke(
            cli, ["-C", str(root), "pr", "show", "pr-001"])
        assert result.exit_code == 0, result.output
        assert "Conflicts (1): c.py" in result.output
        assert "Overlap (2): a.py, b.py" in result.output
        assert "Full record: /cap/pr-001/integration.json" in result.output
