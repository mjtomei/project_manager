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

    def test_byte_bound_applies_without_a_pointer(self):
        """A caller that passes max_bytes but no pointer must still get a real
        byte bound — silently ignoring max_bytes is the bug the line bound was
        supposed to prevent (one enormous line defeats the line count)."""
        out = bounded_lines("y" * 400_000, max_lines=500, max_bytes=1_000)
        assert prompt_bytes(out) <= 1_000
        assert "truncated" in out


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

    def test_sibling_titles_are_byte_bounded_too(self):
        """The sibling cap is a *count* cap, and the lines carry user-authored
        titles: 25 siblings with long titles measured 180 KB — over the argv
        limit — so the listing needs a byte budget as well."""
        pr = _pr(notes=[_note(i) for i in range(300)], plan="pl-1")
        siblings = [_pr(f"pr-s{i:03d}", plan="pl-1", title="LONGTITLE " * 800)
                    for i in range(200)]
        p = prompt_gen.generate_review_prompt(_data(pr, siblings), "pr-x")
        _assert_bounded(p, "pm pr list --plan pl-1")

    def test_dependency_titles_are_byte_bounded(self):
        deps = [f"pr-d{i:03d}" for i in range(40)]
        pr = _pr(depends_on=deps)
        others = [_pr(d, title="LONGTITLE " * 800) for d in deps]
        p = prompt_gen.generate_prompt(_data(pr, others), "pr-x")
        _assert_bounded(p, "pm pr graph")


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

    def test_sibling_titles_are_byte_bounded_too(self):
        """Same count-cap-only defect as the review prompt's sibling block."""
        pr = _pr(notes=[_note(i) for i in range(300)], plan="pl-1")
        siblings = [_pr(f"pr-s{i:03d}", plan="pl-1", title="LONGTITLE " * 800)
                    for i in range(200)]
        p = prompt_gen.generate_signoff_prompt(_data(pr, siblings), "pr-x")
        _assert_bounded(p, "pm pr list --plan pl-1")

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
        monkeypatch.setattr("pm_core.paths.captures_dir",
                            lambda pr_id: Path("/cap") / pr_id)
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

    def test_integration_path_lists_are_byte_bounded_too(self, monkeypatch):
        """A count cap does not bound a listing whose items are filesystem
        paths: 20 of ~4 KB (PATH_MAX) measured 200 KB in the sign-off prompt,
        and that block is *static* text — fit_prompt cannot shrink it, so the
        whole prompt went over PROMPT_ARG_LIMIT and the launcher had to fire
        for a builder this PR exists to bound."""
        # Resolving the marker's pointer would otherwise create the real
        # captures dir as a side effect.
        monkeypatch.setattr("pm_core.paths.captures_dir",
                            lambda pr_id: Path("/cap") / pr_id)
        long_paths = [f"{'d' * 4000}/f{i}.py" for i in range(20)]
        pr = _pr(integration={
            "base_branch": "master", "base_sha": "a" * 40,
            "target_repo": "r", "status": "conflict",
            "overlap": long_paths, "conflicts": long_paths})
        p = prompt_gen.generate_signoff_prompt(_data(pr), "pr-x")
        _assert_bounded(p)
        # The abbreviation must name where the full record lives.
        assert "more; read /cap/pr-x/integration.json" in p

    def test_return_block_bounds_long_integration_paths(self, monkeypatch):
        """Same defect in the block the impl / review / QA-planner prompts
        inline via format_signoff_return."""
        from pm_core.signoff import format_signoff_return
        monkeypatch.setattr("pm_core.paths.captures_dir",
                            lambda pr_id: Path("/cap") / pr_id)
        long_paths = [f"{'d' * 4000}/f{i}.py" for i in range(20)]
        block = format_signoff_return(_pr(signoff_return={
            "verdict": "NEEDS_WORK", "hop": "impl", "reason": "conflict",
            "reviewed_head": "b" * 40,
            "integration": {"base_branch": "master", "base_sha": "a" * 40,
                            "target_repo": "r", "status": "conflict",
                            "conflicts": long_paths, "overlap": long_paths}}))
        assert prompt_bytes(block) < 25_000, prompt_bytes(block)
        assert "more;" in block

    def test_integration_marker_falls_back_to_pr_show(self, monkeypatch):
        monkeypatch.setattr("pm_core.paths.captures_dir", lambda pr_id: None)
        block = prompt_gen._signoff_integration_block(
            _pr(integration={"base_branch": "master", "base_sha": "a" * 40,
                             "target_repo": "r", "status": "clean",
                             "conflicts": [f"c{i}.py" for i in range(100)]}),
            "pr-x")
        assert "(+80 more; run `pm pr show pr-x`)" in block

    def test_integration_marker_resolves_the_container_mount(self, monkeypatch):
        """impl / review / QA-planner prompts run in containers, where the
        captures dir is bind-mounted at /pm-captures and the host
        `~/.pm/sessions/...` path does not exist.  The marker must resolve
        through the container-aware `captures_dir`, not `captures_root`."""
        from pm_core import integration
        monkeypatch.setattr("pm_core.paths.captures_dir",
                            lambda pr_id: Path("/pm-captures"))
        assert (integration.integration_pointer("pr-x")
                == "read /pm-captures/integration.json")

    def test_return_block_does_not_resolve_the_pointer_when_nothing_is_dropped(
            self, monkeypatch):
        """Resolving the pointer calls captures_dir(), which *creates* the
        PR's captures directory.  Building a prompt must not touch the
        filesystem, so the pointer is resolved only when a path list is
        actually abbreviated."""
        from pm_core.signoff import format_signoff_return

        def _boom(pr_id):
            raise AssertionError("pointer resolved with nothing omitted")

        monkeypatch.setattr("pm_core.paths.captures_dir", _boom)
        ret = format_signoff_return(_pr(signoff_return={
            "verdict": "NEEDS_WORK", "hop": "impl", "reason": "conflict",
            "reviewed_head": "b" * 40,
            "integration": {"base_branch": "master", "base_sha": "a" * 40,
                            "target_repo": "r", "status": "conflict",
                            "conflicts": ["c1.py"], "overlap": ["f1.py"]}}))
        assert "c1.py" in ret and "f1.py" in ret

    def test_return_block_resolves_the_pointer_only_when_a_list_is_dropped(
            self, monkeypatch):
        from pm_core.signoff import format_signoff_return
        monkeypatch.setattr("pm_core.paths.captures_dir",
                            lambda pr_id: Path("/cap") / pr_id)
        ret = format_signoff_return(_pr(signoff_return={
            "verdict": "NEEDS_WORK", "hop": "impl", "reason": "conflict",
            "reviewed_head": "b" * 40,
            "integration": {"base_branch": "master", "base_sha": "a" * 40,
                            "target_repo": "r", "status": "conflict",
                            "conflicts": [f"c{i}.py" for i in range(100)]}}))
        assert "(+80 more; read /cap/pr-x/integration.json)" in ret

    def _many_scenarios(self, tmp_path, monkeypatch, n=60):
        status = tmp_path / "qa_status.json"
        status.write_text(json.dumps({
            "overall": "PASS",
            "scenarios": [{"index": i, "title": f"S{i}", "verdict": "PASS",
                           "verdict_reason": "r" * 300} for i in range(n)],
        }))
        monkeypatch.setattr("pm_core.paths.latest_qa_status_path",
                            lambda pr_id: status)
        return status

    def test_qa_scenario_marker_resolves_the_container_mount(self, tmp_path,
                                                             monkeypatch):
        """The sign-off session runs in a container, where the live
        qa_status.json (a host path under ~/.pm/workdirs/qa/) does not exist.
        The marker must name the per-scenario verdicts under the captures dir,
        which is bind-mounted at /pm-captures — naming the workdir file is the
        same host-path defect the integration marker had."""
        status = self._many_scenarios(tmp_path, monkeypatch)
        monkeypatch.setattr("pm_core.paths.captures_dir",
                            lambda pr_id: Path("/pm-captures"))
        block = prompt_gen._signoff_qa_scenarios_block("pr-x")
        assert "(+20 more scenarios" in block
        assert "/pm-captures/scenarios/" in block
        assert str(status) not in block

    def test_qa_scenario_marker_falls_back_to_the_captures_path_command(
            self, tmp_path, monkeypatch):
        self._many_scenarios(tmp_path, monkeypatch)
        monkeypatch.setattr("pm_core.paths.captures_dir", lambda pr_id: None)
        block = prompt_gen._signoff_qa_scenarios_block("pr-x")
        assert "(+20 more scenarios" in block
        assert "pm qa captures-path pr-x" in block

    def test_pr_notes_markers_name_the_concrete_pr_id(self):
        """The omission marker is the only recovery path for the abbreviated
        notes; a literal `<pr-id>` placeholder is not runnable, and the same
        block already carries the concrete id from fit_prompt's pointer."""
        pr = _pr(notes=[_note(i, size=300) for i in range(120)])
        block = prompt_gen._format_pr_notes(pr)
        assert "pm pr note list pr-x" in block
        assert "<pr-id>" not in block

    def test_abbreviation_marker_matches_what_was_abbreviated(self):
        """When a single note exceeds the whole budget, *no* note is rendered
        in full — including the newest.  The marker must not claim only the
        "older" ones were abbreviated, or the session reads a summary of the
        newest handoff as if it were the full text."""
        # One giant note: its full text cannot fit, so every line is a summary.
        pr = _pr(notes=[_note(0, size=60_000)])
        block = prompt_gen._format_pr_notes(pr)
        assert "notes are abbreviated" in block
        assert "older notes are abbreviated" not in block
        assert "pm pr note list pr-x" in block

    def test_abbreviation_marker_says_older_when_the_newest_is_full(self):
        """The complementary case: newest notes kept in full, older ones
        summarized — the marker must say so."""
        notes = [_note(i, size=300) for i in range(120)]
        notes[-1]["text"] = "newest handoff"
        block = prompt_gen._format_pr_notes(_pr(notes=notes))
        assert "older notes are abbreviated" in block
        assert "newest handoff" in block


class TestFitPrompt:
    def test_passthrough_when_it_fits(self):
        from pm_core.prompt_bounds import fit_prompt
        blocks = {"a": ("aaa", "`pm a`", "a block")}
        out = fit_prompt(lambda p: f"S|{p['a']}|E", blocks)
        assert out == "S|aaa|E"

    def test_shrinks_largest_block_with_a_pointer(self):
        from pm_core.prompt_bounds import fit_prompt
        blocks = {
            "small": ("s" * 100, "`pm small`", "small block"),
            "big": ("b" * 5000, "`pm big`", "big block"),
        }
        out = fit_prompt(lambda p: f"S|{p['small']}|{p['big']}|E", blocks,
                         limit=3_000)
        assert prompt_bytes(out) <= 3_000
        # The small block is untouched; the big one carries a pointer.
        assert "s" * 100 in out
        assert "`pm big`" in out
        assert "truncated" in out

    def test_never_shrinks_a_block_below_min_bytes(self):
        from pm_core.prompt_bounds import fit_prompt
        blocks = {"a": ("a" * 4_000, "`pm a`", "a block")}
        # Static text alone is over the limit, so nothing can fix it here and
        # the render is left for the launcher guard.
        out = fit_prompt(lambda p: "S" * 10_000 + p["a"], blocks, limit=5_000)
        assert prompt_bytes(out) > 5_000
        # A block shrinks towards the floor and no further.
        out = fit_prompt(lambda p: p["a"], blocks, limit=2_000)
        assert 1_500 < prompt_bytes(out) <= 2_000

    def test_unfittable_prompt_returns_the_render_unchanged(self):
        """When shrinking cannot reach the limit, the blocks stay intact.

        Static text alone over the limit means no shrink can fit the prompt,
        so it will be delivered by the launcher's file-backed bootstrap —
        abbreviating the blocks would only lose detail the session could have
        read in full.
        """
        from pm_core.prompt_bounds import fit_prompt
        block = "a" * 4_000
        blocks = {"a": (block, "`pm a`", "a block")}
        out = fit_prompt(lambda p: "S" * 10_000 + p["a"], blocks, limit=5_000)
        assert prompt_bytes(out) > 5_000
        assert out == "S" * 10_000 + block
        assert "truncated" not in out

    def test_partial_shrink_still_returns_the_render_unchanged(self):
        """A shrink that gets closer but still does not fit is discarded."""
        from pm_core.prompt_bounds import fit_prompt
        a, b = "a" * 20_000, "b" * 20_000
        blocks = {"a": (a, "`pm a`", "a block"), "b": (b, "`pm b`", "b block")}
        out = fit_prompt(lambda p: "S" * 118_000 + p["a"] + p["b"], blocks,
                         limit=120_000)
        assert prompt_bytes(out) > 120_000
        # Both blocks are whole: the abbreviated render would have been closer
        # to the limit but still over it, so it is not what gets delivered.
        assert out == "S" * 118_000 + a + b

    def test_empty_blocks_are_left_alone(self):
        from pm_core.prompt_bounds import fit_prompt
        blocks = {"a": ("", "`pm a`", "a block"),
                  "b": ("b" * 5_000, "`pm b`", "b block")}
        out = fit_prompt(lambda p: p["a"] + "|" + p["b"], blocks, limit=3_000)
        assert prompt_bytes(out) <= 3_000
        assert "`pm b`" in out
        assert "`pm a`" not in out


# ---------------------------------------------------------------------------
# builders whose per-block budgets sum past the limit
# ---------------------------------------------------------------------------

class TestBudgetCoordination:
    """Every block at its own budget at once must still fit one argv entry.

    The per-block budgets bound each block individually, but a PR that is
    large in several dimensions at once (many notes, a big spec, many
    scenarios, a long description, a big notes.txt) can sum past
    PROMPT_ARG_LIMIT — the sign-off prompt's static text alone is ~19 KB.
    """

    def _pathological(self, _isolated_pm_root, monkeypatch,
                      desc_bytes=40_000):
        status = _isolated_pm_root / "qa_status.json"
        status.write_text(json.dumps({
            "overall": "PASS",
            "scenarios": [{"index": i, "title": "T" * 400, "verdict": "PASS",
                           "verdict_reason": "r" * 4000} for i in range(200)],
        }))
        monkeypatch.setattr("pm_core.paths.latest_qa_status_path",
                            lambda _pr_id: status)
        monkeypatch.setattr(spec_gen, "get_spec", lambda pr, phase: "s" * 200000)
        (_isolated_pm_root / "notes.txt").write_text(
            "## General\n" + "g" * 60000 + "\n")
        pr = _pr(
            description="D" * desc_bytes,
            notes=[_note(i) for i in range(400)],
            plan="pl-1",
            integration={"base_branch": "master", "base_sha": "a" * 40,
                         "target_repo": "r", "status": "conflict",
                         "overlap": [f"f{i}.py" for i in range(500)],
                         "conflicts": [f"c{i}.py" for i in range(500)]},
        )
        siblings = [_pr(f"pr-s{i:03d}", plan="pl-1",
                        title="LONGTITLE " * 600) for i in range(200)]
        return pr, _data(pr, siblings)

    def test_signoff_fits_when_every_block_is_large(self, _isolated_pm_root,
                                                    monkeypatch):
        pr, data = self._pathological(_isolated_pm_root, monkeypatch)
        p = prompt_gen.generate_signoff_prompt(data, "pr-x")
        _assert_bounded(p, "pm pr note list pr-x")
        # The sign-off routing contract must survive the shrink.
        assert "pm-signoff-verdict" in p

    def test_review_fits_when_every_block_is_large(self, _isolated_pm_root,
                                                   monkeypatch):
        pr, data = self._pathological(_isolated_pm_root, monkeypatch)
        p = prompt_gen.generate_review_prompt(data, "pr-x")
        _assert_bounded(p)

    def test_impl_fits_when_every_block_is_large(self, _isolated_pm_root,
                                                 monkeypatch):
        # A long PR description alone can push the impl prompt over.
        pr, data = self._pathological(_isolated_pm_root, monkeypatch,
                                      desc_bytes=80_000)
        p = prompt_gen.generate_prompt(data, "pr-x")
        _assert_bounded(p, "pm pr show pr-x")

    def test_planner_fits_when_every_block_is_large(self, _isolated_pm_root,
                                                    monkeypatch):
        pr, data = self._pathological(_isolated_pm_root, monkeypatch)
        p = prompt_gen.generate_qa_planner_prompt(data, "pr-x")
        _assert_bounded(p, "pm pr show pr-x")

    def test_small_prompts_are_byte_identical(self, _isolated_pm_root,
                                              monkeypatch):
        """The fit path must not touch prompts that already fit."""
        monkeypatch.setattr("pm_core.paths.latest_qa_status_path",
                            lambda _pr_id: None)
        pr = _pr(notes=[_note(i) for i in range(3)])
        data = _data(pr)
        p = prompt_gen.generate_signoff_prompt(data, "pr-x")
        assert "truncated to fit the prompt size limit" not in p
        assert prompt_bytes(p) < 40_000


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

    def test_child_artifact_paths_are_byte_bounded_too(self):
        """The listing inlines full paths (not basenames), so the 20-item cap
        alone leaves the product unbounded — the same defect as the plan
        listings."""
        pr = _pr()
        scenario = QAScenario(
            index=1, title="S", focus="F",
            artifact_paths=[f"/scratch/qa-artifacts/{'a' * 4000}-{i}.md"
                            for i in range(20)],
            steps="GIVEN x\n" * 200,
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

    def test_watcher_target_list_is_bounded_too(self):
        """The target list sits right beside the bounded managed list and is
        built from the same user-set collection, so it needs the same cap."""
        targets = [f"pr-{i:03d}" for i in range(120)]
        prs = [_pr(t) for t in targets]
        data = {"project": {"name": "p", "base_branch": "master"},
                "prs": prs, "plans": []}
        p = prompt_gen.generate_watcher_prompt(data, auto_start_targets=targets)
        line = next(l for l in p.splitlines()
                    if l.startswith("Auto-start targets:"))
        assert "(+80 more; run `pm autostart list`)" in line
        assert "**pr-119**" not in line

    def test_comma_separated_markers_do_not_double_space(self, monkeypatch):
        """bounded_join appends the marker after ``separator`` (", "), so a
        marker that also starts with a space renders as ",  (+N more" — one
        stray space in the prompt text the session reads."""
        targets = [f"pr-{i:03d}" for i in range(120)]
        prs = [_pr(t) for t in targets]
        data = {"project": {"name": "p", "base_branch": "master"},
                "prs": prs, "plans": []}
        p = prompt_gen.generate_watcher_prompt(data, auto_start_targets=targets)
        for line in p.splitlines():
            if "(+" in line and "more" in line:
                assert ",  (+" not in line, line

        monkeypatch.setattr("pm_core.paths.captures_dir",
                            lambda pr_id: Path("/cap") / pr_id)
        integ = {"base_branch": "master", "base_sha": "a" * 40,
                 "target_repo": "r", "status": "clean",
                 "overlap": [f"f{i}.py" for i in range(200)],
                 "conflicts": [f"c{i}.py" for i in range(200)]}
        block = prompt_gen._signoff_integration_block(_pr(integration=integ),
                                                      "pr-x")
        assert ",  (+" not in block

        from pm_core.signoff import format_signoff_return
        ret = format_signoff_return(_pr(signoff_return={
            "verdict": "NEEDS_WORK", "hop": "impl", "reason": "conflict",
            "reviewed_head": "b" * 40, "integration": integ}))
        assert ",  (+" not in ret


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
    def _write_items(self, directory, n, body="body", desc=None):
        directory.mkdir(parents=True, exist_ok=True)
        for i in range(n):
            description = desc(i) if desc else f"desc {i}"
            (directory / f"item-{i:03d}.md").write_text(
                f"---\ntitle: Item {i}\ndescription: {description}\n---\n{body}\n")

    def test_instruction_summary_caps_each_category(self, _isolated_pm_root):
        from pm_core import qa_instructions
        self._write_items(_isolated_pm_root / "qa" / "instructions", 60)
        self._write_items(_isolated_pm_root / "qa" / "artifacts", 60)
        out = qa_instructions.instruction_summary_for_prompt(_isolated_pm_root)
        assert out.count("- **Item ") <= 40  # 20 per category
        assert "more; run `pm qa list`" in out

    def test_instruction_summary_bounds_long_descriptions(self,
                                                          _isolated_pm_root):
        """A count cap alone does not bound the listing.

        Descriptions are user-authored free text: 20 items per category with
        multi-KB descriptions measured ~300 KB (over PROMPT_ARG_LIMIT) before
        the byte budgets were added.  This is the block the QA planner prompt
        (the one that hit E2BIG in the field) inlines.
        """
        from pm_core import qa_instructions
        from pm_core.prompt_bounds import LIBRARY_TOTAL_BUDGET
        for category in ("instructions", "regression", "artifacts"):
            self._write_items(_isolated_pm_root / "qa" / category, 50,
                              desc=lambda i: "d" * 5000)
        out = qa_instructions.instruction_summary_for_prompt(
            _isolated_pm_root, include_regression=True)
        # Bounded by the aggregate budget (plus the truncation marker).
        assert prompt_bytes(out) <= LIBRARY_TOTAL_BUDGET + 400
        assert "pm qa list" in out
        assert prompt_bytes(out) < PROMPT_ARG_LIMIT

    def test_instruction_summary_small_library_unchanged(self,
                                                         _isolated_pm_root):
        """A realistic library passes through with no markers."""
        from pm_core import qa_instructions
        for category in ("instructions", "regression", "artifacts"):
            self._write_items(_isolated_pm_root / "qa" / category, 5)
        out = qa_instructions.instruction_summary_for_prompt(
            _isolated_pm_root, include_regression=True)
        assert out.count("- **Item ") == 15
        assert "truncated" not in out
        assert "more; run" not in out

    def test_planner_prompt_bounded_with_pathological_library(
            self, _isolated_pm_root):
        """The assembled planner prompt stays argv-safe too."""
        self._write_items(_isolated_pm_root / "qa" / "instructions", 50,
                          desc=lambda i: "d" * 5000)
        self._write_items(_isolated_pm_root / "qa" / "artifacts", 50,
                          desc=lambda i: "d" * 5000)
        pr = _pr(notes=[_note(i) for i in range(60)])
        prompt = prompt_gen.generate_qa_planner_prompt(_data(pr), "pr-x")
        _assert_bounded(prompt, "pm qa list")

    def test_mocks_for_prompt_bounded(self, _isolated_pm_root):
        from pm_core import qa_instructions
        self._write_items(_isolated_pm_root / "qa" / "mocks", 40,
                          body="m" * 3000)
        out = qa_instructions.mocks_for_prompt(_isolated_pm_root)
        assert prompt_bytes(out) <= 12_000 + 400
        # The aggregate bound owns the degradation and names the command that
        # lists every mock (a per-mock omission note could never fire, since
        # the listing passes no max_items/max_bytes).
        assert "pm qa mocks list" in out


class TestQaFinalizeBounding:
    def test_many_scenarios_bounded(self):
        worktrees = [(i, "PASS", f"/tmp/s{i}") for i in range(100)]
        p = build_qa_finalize_prompt(
            pr_id="pr-x", pr_title="T", branch="b", pr_workdir="/tmp/w",
            scenario_worktrees=worktrees, overall_verdict="PASS")
        _assert_bounded(p, "qa_resume.json")

    def test_long_worktree_paths_are_byte_bounded_too(self):
        """The listing is count-capped, but its lines carry worktree paths
        whose length is bounded only by PATH_MAX: 40 of them can still exceed
        the argv limit — the same cap-times-item-size defect the PR/plan and
        sibling listings had, so it needs a byte budget as well."""
        worktrees = [(i, "PASS", "/tmp/" + "d" * 4_000) for i in range(40)]
        p = build_qa_finalize_prompt(
            pr_id="pr-x", pr_title="T", branch="b", pr_workdir="/tmp/w",
            scenario_worktrees=worktrees, overall_verdict="PASS")
        _assert_bounded(p, "qa_resume.json")

    def test_small_listing_is_unchanged(self):
        worktrees = [(1, "PASS", "/tmp/s1"), (2, "FAIL", None)]
        p = build_qa_finalize_prompt(
            pr_id="pr-x", pr_title="T", branch="b", pr_workdir="/tmp/w",
            scenario_worktrees=worktrees, overall_verdict="PASS")
        assert "- Scenario 1: verdict=PASS, worktree=/tmp/s1" in p
        assert "- Scenario 2: verdict=FAIL, worktree=(none)" in p
        assert "more scenarios" not in p


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

    def test_materialize_writes_to_write_dir_but_names_cwd(self, tmp_path):
        """In container mode the file lands on the host workdir (write_dir)
        while claude reads it through the container path (cwd); the bootstrap
        must name the path claude can actually open."""
        host = tmp_path / "host"
        host.mkdir()
        huge = "y" * (PROMPT_ARG_LIMIT + 5)
        argv, tmp = _materialize_oversized_prompt(
            huge, cwd="/container/wd", write_dir=str(host))
        assert tmp is not None and tmp.startswith(str(host))
        assert "/container/wd/pm/prompts/" in argv
        assert str(host) not in argv
        assert Path(tmp).read_text() == huge
        Path(tmp).unlink()

    def test_materialize_falls_back_to_cwd_when_write_dir_unusable(self, tmp_path):
        huge = "y" * (PROMPT_ARG_LIMIT + 5)
        argv, tmp = _materialize_oversized_prompt(
            huge, cwd=str(tmp_path), write_dir=str(tmp_path / "missing"))
        assert tmp is not None and tmp.startswith(str(tmp_path))
        assert str(tmp_path) in argv
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

def _make_plan_state(tmp_path, plan_prs, other_prs, title_size=0):
    plan = {"id": "pl-001", "name": "Plan", "file": "plans/pl-001.md"}
    pad = "T" * title_size
    prs = []
    for i in range(plan_prs):
        prs.append({"id": f"pr-p{i:03d}", "title": f"Plan PR {i}{pad}",
                    "plan": "pl-001", "status": "pending", "depends_on": [],
                    "description": "d" * 500, "branch": None, "workdir": None,
                    "gh_pr_number": None, "notes": []})
    for i in range(other_prs):
        prs.append({"id": f"pr-o{i:03d}", "title": f"Other PR {i}{pad}",
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

    def test_plan_lists_bound_long_titles_too(self, tmp_path):
        """The plan listings are count-capped, but their lines carry
        user-authored titles — a byte budget has to bound the product."""
        root = _make_plan_state(tmp_path, plan_prs=40, other_prs=300,
                                title_size=4_000)
        for argv in (["plan", "review", "pl-001"], ["plan", "breakdown", "pl-001"],
                     ["plan", "deps"]):
            with patch("pm_core.cli.plan.find_claude", return_value=None):
                result = CliRunner().invoke(cli, ["-C", str(root)] + argv)
            assert result.exit_code == 0, (argv, result.output)
            assert prompt_bytes(result.output) <= PROMPT_ARG_LIMIT + 300, argv


class TestGuidePromptBounding:
    """`pm guide`'s assist prompt inlines one line per plan (the same
    count-times-item-size listing the PR/plan builders bound)."""

    def _plans(self, n, name_size):
        return [{"id": f"pl-{i:03d}", "name": "PLANNAME " * (name_size // 9),
                 "file": f"plans/pl-{i:03d}.md"} for i in range(n)]

    def test_assist_prompt_bounds_the_plan_listing(self):
        from pm_core import guide
        data = _data(_pr(), plans=self._plans(200, 4_000))
        p = guide.build_assist_prompt(data, None)
        _assert_bounded(p, "pm plan list")

    def test_assist_prompt_small_plan_list_is_unchanged(self):
        from pm_core import guide
        plans = [{"id": f"pl-{i:03d}", "name": f"Plan {i}",
                  "file": f"plans/pl-{i:03d}.md"} for i in range(3)]
        p = guide.build_assist_prompt(_data(_pr(), plans=plans), None)
        for plan in plans:
            assert f"  - {plan['id']}: {plan['name']}" in p
        assert "more; run `pm plan list`" not in p

    def test_assist_prompt_without_plans(self):
        from pm_core import guide
        p = guide.build_assist_prompt(_data(_pr(), plans=[]), None)
        assert "  (no plans yet)" in p


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
