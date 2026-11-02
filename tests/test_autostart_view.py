"""Compact, highlighted auto-start status (pr-8700be3).

Shared layout (``pm_core.autostart_view``) used by ``pm autostart status``
and the TUI runs popup: one dependency forest with one row per PR,
duplicate suppression, width/wrapping, red human-action labels, plain/JSON
output, and CLI/TUI agreement.
"""

import asyncio
import json
import os
import re
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from rich.cells import cell_len

from pm_core import autostart_state as st
from pm_core import autostart_view as view

from autostart_mixed_fixture import (
    _pr, edge_status, mixed_inputs, mixed_status,
)

ANSI = re.compile(r"\x1b\[[0-9;]*m")
NEED_YOU = {"pr-0a1b2c3", "pr-5b6c7d8", "pr-9f0a1b2", "pr-7d8e9f0",
            "pr-8e9f0a1"}


def _text(width=99, color=False, status=None):
    return st.format_text(status or mixed_status(), width=width, color=color)


def _row_block(text: str, head: str) -> str:
    """The lines of the first row whose first line starts with *head*
    (after indentation), up to the next row."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith(head):
            out = [ln]
            for nxt in lines[i + 1:]:
                if nxt.lstrip()[:1] in ("◎", "└"):
                    break
                out.append(nxt)
            return "\n".join(out)
    raise AssertionError(f"no row {head!r} in\n{text}")


# ---------------------------------------------------------------------------
# Structured data (JSON) — full, plus additive presentation fields
# ---------------------------------------------------------------------------

class TestStructured:
    def test_json_reason_keeps_full_text_and_adds_fields(self):
        s = mixed_status()
        runs = {r["pr_id"]: r for r in s["runs"]}
        docs = runs["pr-3f4a5b6"]
        # Full reason unchanged for machine readers (hold causes included).
        assert "wait-for-merge ← pr-4a5b6c7" in docs["reason"]
        assert [b["pr_id"] for b in docs["blockers"]] == \
            ["pr-1c2d3e4", "pr-0a1b2c3"]
        assert docs["blockers"][1] == {
            "pr_id": "pr-0a1b2c3", "display_id": "#231", "status": "sign_off",
            "held_by": ["pr-4a5b6c7"]}
        rv = runs["pr-1c2d3e4"]
        assert rv["reason"] == "review iteration 3 (last NEEDS_WORK)"
        assert rv["short_reason"] == "last NEEDS_WORK"
        assert rv["attention"] is None
        assert json.loads(json.dumps(s, default=sorted)) is not None

    def test_attention_codes(self):
        runs = {r["pr_id"]: r for r in mixed_status()["runs"]}
        got = {pid: (r["attention"], r["attention_label"])
               for pid, r in runs.items() if r["attention"]}
        assert got == {
            "pr-0a1b2c3": ("manual_merge", "MANUAL MERGE"),
            "pr-5b6c7d8": ("spec_review", "IMPL SPEC REVIEW"),
            "pr-7d8e9f0": ("spec_review", "QA SPEC REVIEW"),
            "pr-9f0a1b2": ("input_required", "INPUT_REQUIRED"),
            "pr-8e9f0a1": ("input_required", "INPUT_REQUIRED"),
        }
        # Configured wait-for-merge on a running PR is not a human wait;
        # neither is a signed-off auto-merge target.
        assert runs["pr-1c2d3e4"]["policy"] == st.POLICY_WAIT
        assert runs["pr-1c2d3e4"]["attention"] is None
        assert runs["pr-aa1b2c3"]["attention"] is None
        tgt = {t["pr_id"]: t for t in mixed_status()["targets"]}
        assert tgt["pr-9f0a1b2"]["attention"] == "input_required"
        assert tgt["pr-4a5b6c7"]["attention"] is None

    def test_qa_spec_pending_surfaced_during_qa(self):
        # Previously only in_progress checked spec_pending: a pending QA
        # spec showed as a plain queued QA.
        prs = [{"id": "q", "status": "qa", "depends_on": [],
                "spec_pending": {"phase": "qa"}}]
        s = st.build_status({"prs": prs, "targets": {"q": {}}})
        r = s["runs"][0]
        assert (r["state"], r["attention"]) == ("waiting", "spec_review")
        assert r["reason"] == "QA spec awaiting review — press V"

    def test_other_human_waits(self):
        base = {"targets": {"p": {}}}
        perm = st.build_status({**base, "prs": [
            {"id": "p", "status": "in_progress", "depends_on": []}],
            "windows": {"p": "@1"}, "impl_idle": {"p": "waiting"}})
        assert perm["runs"][0]["attention"] == "permission"
        blocked = st.build_status({**base, "prs": [
            {"id": "p", "status": "sign_off", "depends_on": []}],
            "signoff": {"p": {"verdict": "SIGNOFF_BLOCKED", "fresh": True}}})
        assert blocked["runs"][0]["attention"] == "decision"
        merge_ir = st.build_status({**base, "prs": [
            {"id": "p", "status": "qa", "depends_on": []}],
            "merge_input_required": {"p"}})
        assert merge_ir["runs"][0]["attention"] == "input_required"
        recorded = st.build_status({**base, "prs": [
            {"id": "p", "status": "qa", "depends_on": []}],
            "qa_loops": {"p": {"verdict": "INPUT_REQUIRED", "recorded": True}}})
        assert recorded["runs"][0]["attention"] == "input_required"


# ---------------------------------------------------------------------------
# Duplicate suppression
# ---------------------------------------------------------------------------

class TestDedupe:
    def test_wait_policy_stated_once_per_tree(self):
        text = _text()
        wait_tree = text.split("◎ #240")[1].split("◎ #239")[0]
        # The label once, plus the title's own "wait-for-merge chains".
        assert wait_tree.count("wait-for-merge") == 2
        assert "[wait-for-merge]" in _row_block(text, "◎ #240")
        assert "← #240" not in wait_tree
        # Blockers name PRs and status only — no hold cause per blocker.
        assert "blocked on #233 (in_review), #231 (sign_off)" in wait_tree

    def test_meaningful_exceptions_kept(self):
        text = _text()
        # A dependency shared with the wait chain but placed under the
        # auto-merge target that reached it first: the hold is not implied
        # by its tree, so it is named, with the other dependent.
        shared = _row_block(text, "└ #235")
        assert "[wait-for-merge ← #240]" in shared
        assert "also needed by #240" in shared
        # An auto-merge target that a wait target's closure holds.
        nested = " ".join(_row_block(text, "◎ #241").split())
        assert "[auto-merge] [wait-for-merge ← #239]" in nested

    def test_exception_stated_once_per_subtree(self):
        # A chain placed under an auto-merge target but held by a wait
        # target elsewhere: the exception is on the topmost held PR only;
        # everything below it is in that PR's closure, so held the same way.
        prs = [_pr("A", deps=["X"]), _pr("X", "in_progress", deps=["Y"]),
               _pr("Y", "in_progress", deps=["Z"]), _pr("Z", "in_progress"),
               _pr("W", deps=["V"]), _pr("V", deps=["X"])]
        status = st.build_status({"prs": prs, "targets": {
            "A": {}, "W": {"wait_for_merge": True}}})
        text = st.format_text(status)
        assert text.count("wait-for-merge ← W") == 1
        assert "[wait-for-merge ← W]" in _row_block(text, "└ X")
        rows = {r["pr_id"]: r for r in st.status_rows(status)}
        assert rows["Z"]["ancestors"] == ["A", "X", "Y"]
        assert rows["Z"]["inherited"] == ["A", "X", "Y", "W"]
        for pid in ("Y", "Z"):
            assert st.policy_labels(rows[pid]) == []

    def test_blockers_name_prs_and_status_only(self):
        status = mixed_status()
        run = next(r for r in status["runs"] if r["pr_id"] == "pr-3f4a5b6")
        names = view.display_names(status)
        assert view.reason_text(run, names=names) == \
            "blocked on #233 (in_review), #231 (sign_off)"
        # The full reason (``--json``) keeps the hold causes.
        assert "wait-for-merge ← pr-4a5b6c7" in run["reason"]

    def test_phase_and_progress_once(self):
        text = _text()
        review = _row_block(text, "└ #233")
        assert "review #3" in review and "last NEEDS_WORK" in review
        assert "iteration" not in review
        qa = _row_block(text, "└ #235")
        assert qa.count("2/5") == 1 and "scenario" not in qa
        ir = _row_block(text, "◎ #239")
        assert ir.count("INPUT_REQUIRED") == 1
        signed = _row_block(text, "└ #231")
        assert "signed off — press g to merge" in signed
        assert "held by" not in signed and "SIGNOFF_MERGE" not in signed
        # A spec-review label names its phase; no bare phase token after it.
        impl_spec = _row_block(text, "└ #236").splitlines()[0]
        assert "IMPL SPEC REVIEW" in impl_spec
        assert "REVIEW impl" not in impl_spec
        qa_spec = _row_block(text, "└ #237").splitlines()[0]
        assert "QA SPEC REVIEW" in qa_spec and "REVIEW qa" not in qa_spec

    @pytest.mark.parametrize("status,extra,token,short", [
        ("pending", {"launching": {"pr-x"}}, "impl", "launching"),
        ("in_progress", {"launching": {"pr-x"}}, "impl", "launching"),
        ("in_progress", {}, "impl", "no window"),
        ("in_progress", {"windows": {"#9": "@1"},
                         "impl_idle": {"pr-x": "idle"}},
         "impl", "idle; review transition pending"),
        ("in_review", {"windows": {"review-#9": "@1"}}, "review",
         "window open (no loop)"),
        ("in_review", {}, "review", "loop starts on next scheduler pass"),
        ("qa", {}, "qa", "starts on next scheduler pass"),
        ("sign_off", {}, "sign-off",
         "no window; relaunches on next scheduler pass"),
        ("sign_off", {"signoff": {"pr-x": {"verdict": "SIGNOFF_MERGE",
                                           "fresh": False}}}, "sign-off",
         "SIGNOFF_MERGE stale (HEAD moved); relaunches against current HEAD"),
        ("sign_off", {"signoff": {"pr-x": {
            "verdict": "SIGNOFF_MERGE", "fresh": False,
            "stale_reason": "base moved"}}}, "sign-off",
         "SIGNOFF_MERGE stale (base moved); re-runs against the current base"),
        ("sign_off", {"signoff": {"pr-x": {
            "verdict": "SIGNOFF_BLOCKED", "fresh": True}}}, "sign-off",
         "SIGNOFF_BLOCKED — read the report and decide"),
        ("qa", {"qa_loops": {"pr-x": {"error": "boom"}}}, "qa", "error: boom"),
        ("sign_off", {"pending_merge": {"pr-x"}, "signoff": {"pr-x": {
            "verdict": "SIGNOFF_MERGE", "fresh": True}}}, "merge",
         "attempt failed; no merge window"),
    ])
    def test_reason_does_not_repeat_the_phase_token(self, status, extra,
                                                    token, short):
        # ``QUEUED qa — QA starts on next scheduler pass`` names the phase
        # twice; the token says it once, the JSON reason keeps the full text.
        s = st.build_status({"prs": [_pr("pr-x", status, gh=9)],
                             "targets": {"pr-x": {}}, **extra})
        run = s["runs"][0]
        assert run["short_reason"] == short
        assert run["reason"] != short
        first, detail = st.format_text(s).splitlines()[1:3]
        assert f" {token} [auto-merge]" in first
        assert detail.strip() == short + (" · ⧉ " + run["window"]["name"]
                                          if run["window"] else "")

    def test_spec_review_label_hides_held_phase_progress(self):
        # The live path to a QA spec review: QA ended INPUT_REQUIRED for the
        # missing spec, then the spec was flagged.  The recorded verdict's
        # ``qa INPUT_REQUIRED`` progress must not follow the label.
        inp = mixed_inputs()
        inp["qa_loops"]["pr-7d8e9f0"] = {"running": False, "total": 0,
                                         "verdict": "INPUT_REQUIRED",
                                         "recorded": True}
        qa_spec = _row_block(_text(status=st.build_status(inp)), "└ #237")
        first = qa_spec.splitlines()[0]
        assert "QA SPEC REVIEW" in first and "REVIEW qa" not in first
        assert "INPUT_REQUIRED" not in qa_spec

    def test_old_owner_without_short_reason_falls_back(self):
        s = mixed_status()
        for r in s["runs"]:
            for k in ("short_reason", "attention", "attention_label",
                      "blockers"):
                r.pop(k)
        text = st.format_text(s)
        assert "review iteration 3 (last NEEDS_WORK)" in text
        assert "⚠" not in text


# ---------------------------------------------------------------------------
# One dependency forest: one canonical row per local PR id
# ---------------------------------------------------------------------------

def _heads(text: str) -> list[str]:
    """First lines of every row (``◎`` target / ``└`` dependency)."""
    return [ln for ln in text.splitlines() if ln.lstrip()[:1] in ("◎", "└")]


def _shape(status) -> list[tuple]:
    return [(r["pr_id"], r["depth"], r["kind"], r["parent"])
            for r in st.status_rows(status)]


def _graph(prs, targets, **inp):
    return st.build_status({"prs": prs, "targets": targets, **inp})


def _p(pid, status="pending", deps=(), **kw):
    return {"id": pid, "title": f"T {pid}", "status": status,
            "depends_on": list(deps), **kw}


class TestForest:
    def test_every_pr_has_exactly_one_row(self):
        status = mixed_status()
        rows = st.status_rows(status)
        ids = [r["pr_id"] for r in rows]
        assert sorted(ids) == sorted(r["pr_id"] for r in status["runs"])
        assert len(ids) == len(set(ids))
        heads = _heads(_text())
        assert len(heads) == len(ids)
        for r in status["runs"]:
            assert sum(r["pr_id"] in h for h in heads) == 1, r["pr_id"]

    def test_mixed_tree_shape(self):
        assert _shape(mixed_status()) == [
            ("pr-6c7d8e9", 0, "target", None),        # #238 auto
            ("pr-2e3f4a5", 1, "dep", "pr-6c7d8e9"),   # #235 shared
            ("pr-5b6c7d8", 1, "dep", "pr-6c7d8e9"),   # #236
            ("pr-4a5b6c7", 0, "target", None),        # #240 wait chain
            ("pr-3f4a5b6", 1, "dep", "pr-4a5b6c7"),   # #234
            ("pr-1c2d3e4", 2, "dep", "pr-3f4a5b6"),   # #233
            ("pr-0a1b2c3", 2, "dep", "pr-3f4a5b6"),   # #231 (diamond)
            ("pr-9f0a1b2", 0, "target", None),        # #239 wait
            ("pr-7d8e9f0", 1, "dep", "pr-9f0a1b2"),   # #237
            ("pr-8e9f0a1", 1, "target", "pr-9f0a1b2"),  # #241 nested target
            ("pr-aa1b2c3", 0, "target", None),        # #242
        ]

    def test_relationships_kept_as_references(self):
        rows = {r["pr_id"]: r for r in st.status_rows(mixed_status())}
        # Shared across trees, and a diamond inside one tree: the other
        # dependent is named once on the canonical row.
        assert rows["pr-2e3f4a5"]["also"] == ["pr-4a5b6c7"]
        assert rows["pr-0a1b2c3"]["also"] == ["pr-4a5b6c7"]
        # The tree parent is not repeated as a reference.
        assert rows["pr-1c2d3e4"]["also"] == []
        text = _text()
        assert "also needed by #240" in _row_block(text, "└ #231")
        # The nested target keeps its target marker and own policy.
        assert _row_block(text, "◎ #241").startswith("  ◎ #241")

    def test_target_also_dependency_is_not_a_second_root(self):
        prs = [_p("t1", deps=["t2"]), _p("t2", "in_progress")]
        # Whichever order the targets were added in.
        for order in (["t1", "t2"], ["t2", "t1"]):
            status = _graph(prs, {t: {} for t in order})
            assert _shape(status) == [("t1", 0, "target", None),
                                      ("t2", 1, "target", "t1")]

    def test_diamond_and_shared_dependency(self):
        prs = [_p("a", "in_progress"), _p("b", deps=["a"]),
               _p("c", deps=["a"]), _p("t", deps=["b", "c"]),
               _p("u", deps=["a"])]
        status = _graph(prs, {"t": {}, "u": {"wait_for_merge": True}})
        assert _shape(status) == [
            ("t", 0, "target", None), ("b", 1, "dep", "t"),
            ("a", 2, "dep", "b"), ("c", 1, "dep", "t"),
            ("u", 0, "target", None)]
        rows = {r["pr_id"]: r for r in st.status_rows(status)}
        assert rows["a"]["also"] == ["c", "u"]
        # u holds a (wait-for-merge) but is not its ancestor here.
        assert st.policy_labels(rows["a"]) == [("wait-for-merge ← u",
                                                "exception")]
        text = st.format_text(status)
        assert [h.lstrip()[:4] for h in _heads(text)].count("└ a ") == 1
        assert "also needed by c, u" in text

    def test_multiple_roots_follow_target_order(self):
        prs = [_p("x", "in_progress"), _p("y", "in_progress"),
               _p("z", "in_progress")]
        status = _graph(prs, {"z": {}, "x": {}, "y": {}})
        assert [r["pr_id"] for r in st.status_rows(status)] == ["z", "x", "y"]

    def test_cycles_are_shown_once_and_named(self):
        text = st.format_text(edge_status())
        rows = {r["pr_id"]: r for r in st.status_rows(edge_status())}
        assert rows["pr-c1c1c1c"]["depth"] == 0
        assert rows["pr-c2c2c2c"]["parent"] == "pr-c1c1c1c"
        assert rows["pr-c2c2c2c"]["cycle"] == ["pr-c1c1c1c"]
        assert rows["pr-c1c1c1c"]["also"] == []  # the back edge is the cycle
        assert "↻ dependency cycle: needs #301" in " ".join(
            _row_block(text, "◎ #302").split())
        assert sum("#301" in h for h in _heads(text)) == 1

    def test_cycle_below_a_target(self):
        prs = [_p("t", deps=["a"]), _p("a", "in_progress", deps=["b"]),
               _p("b", "in_progress", deps=["a"])]
        status = _graph(prs, {"t": {}})
        assert _shape(status) == [("t", 0, "target", None),
                                  ("a", 1, "dep", "t"), ("b", 2, "dep", "a")]
        rows = {r["pr_id"]: r for r in st.status_rows(status)}
        assert rows["b"]["cycle"] == ["a"] and rows["a"]["also"] == []

    def test_self_dependency_does_not_loop(self):
        status = _graph([_p("s", "in_progress", deps=["s"])], {"s": {}})
        (row,) = st.status_rows(status)
        assert row["cycle"] == ["s"]

    def test_missing_and_closed_references(self):
        text = st.format_text(edge_status())
        assert "blocked on pr-gone000 (missing), #304 (closed)" in text
        gone = _row_block(text, "◎ pr-gone999")
        assert "FAILED" in gone and "PR not found" in gone
        assert "done" not in gone.splitlines()[0]
        # Neither the closed nor the missing PR gets a row of its own.
        assert not any("#304" in h or "pr-gone000" in h
                       for h in _heads(text))

    def test_dependency_behind_a_merged_pr_hangs_under_its_target(self):
        rows = {r["pr_id"]: r for r in st.status_rows(edge_status())}
        assert rows["pr-e0e0e0e"]["parent"] == "pr-d0d0d0d"
        assert rows["pr-e0e0e0e"]["also"] == []

    def test_same_github_number_stays_two_rows(self):
        status = edge_status()
        text = st.format_text(status)
        twins = [h for h in _heads(text) if "#310" in h]
        assert len(twins) == 2
        assert "pr-f1f1f1f" in twins[0] and "pr-f2f2f2f" in twins[1]
        # References use the unique pm id where the display id is shared.
        names = view.display_names(status)
        assert names["pr-f1f1f1f"] == "pr-f1f1f1f"
        assert names["pr-f0f0f0f"] == "#311"
        assert "blocked on pr-f1f1f1f (in_progress), pr-f2f2f2f " \
            "(in_progress)" in " ".join(text.split())
        assert "⚠ 2 need you: pr-f1f1f1f, pr-f2f2f2f" in text

    def test_closed_blocker_sharing_a_github_number_is_named_by_pm_id(self):
        # A closed PR and the local PR that took over its GitHub number:
        # ``blocked on #40 (closed), #40 (in_progress)`` would read as one
        # PR, so the blocker reason names both by their unique pm ids.
        status = _graph([
            _p("pr-t", deps=["pr-old", "pr-new"], gh_pr_number=50),
            _p("pr-old", "closed", gh_pr_number=40),
            _p("pr-new", "in_progress", gh_pr_number=40)], {"pr-t": {}})
        text = st.format_text(status)
        assert "blocked on pr-old (closed), pr-new (in_progress)" in text
        assert "└ #40 pr-new PAUSED impl" in text
        # No collision: a closed blocker keeps its display id.
        assert "blocked on pr-gone000 (missing), #304 (closed)" in \
            st.format_text(edge_status())

    def test_order_is_deterministic(self):
        assert _text() == _text()
        a = st.format_text(edge_status())
        # The same graph, runs listed in another order by an older owner.
        s = edge_status()
        s["runs"] = list(reversed(s["runs"]))
        assert [r["pr_id"] for r in st.status_rows(s)] == \
            [r["pr_id"] for r in st.status_rows(edge_status())]
        assert st.format_text(s) == a

    def test_deep_chain_indent_is_capped_to_the_width(self):
        prs = [_p(f"c{i}", "in_progress", deps=[f"c{i + 1}"])
               for i in range(20)] + [_p("c20", "in_progress")]
        status = _graph(prs, {"c0": {}})
        for width in (30, 45, 99):
            text = st.format_text(status, width=width)
            assert all(cell_len(ln) <= width for ln in text.splitlines())
            assert len(_heads(text)) == 21
        # Wide enough: every level indents.
        assert "  " * 20 + "└ c20" in st.format_text(status, width=99)


# ---------------------------------------------------------------------------
# Width / wrapping
# ---------------------------------------------------------------------------

WORDS = re.compile(r"\S+")


class TestWidth:
    @pytest.mark.parametrize("width", [99, 80, 72, 60, 45, 30])
    def test_every_line_fits(self, width):
        for ln in _text(width).splitlines():
            assert cell_len(ln) <= width, (width, ln)

    def test_default_is_99_columns_and_nothing_is_cut(self):
        text = _text()
        assert max(cell_len(ln) for ln in text.splitlines()) <= 99
        # Wrapping never drops a word: long titles continue on the next
        # line instead of being truncated.
        title = next(p for p in mixed_inputs()["prs"]
                     if p["id"] == "pr-4a5b6c7")["title"]
        assert " ".join(WORDS.findall(title)) in " ".join(
            WORDS.findall(_row_block(text, "◎ #240")))
        assert " ".join(WORDS.findall(title)) in " ".join(
            WORDS.findall(_row_block(_text(45), "◎ #240")))

    def test_continuation_lines_are_indented_under_the_row(self):
        block = _row_block(_text(60), "└ #235")
        first, *rest = block.splitlines()
        assert first.startswith("  └ ")
        assert rest and all(ln.startswith("      ") for ln in rest)

    def test_multiline_reason_keeps_the_indent(self):
        inp = mixed_inputs()
        inp["qa_loops"]["pr-2e3f4a5"] = {
            "running": False, "error": "Traceback:\n  boom\tline"}
        text = st.format_text(st.build_status(inp), 60)
        assert "\t" not in text
        block = _row_block(text, "└ #235")
        # ``FAILED qa`` already names the phase: the reason is the error.
        assert "error: Traceback: boom line" in " ".join(block.split())
        assert "QA error" not in block
        first, *rest = block.splitlines()
        assert rest and all(ln.startswith("      ") for ln in rest)
        assert all(cell_len(ln) <= 60 for ln in text.splitlines())

    def test_header_wraps(self):
        head = _text(60).split("◎")[0].splitlines()
        assert len(head) > 1 and all(cell_len(ln) <= 60 for ln in head)
        assert head[1].startswith("  ")

    def test_metadata_labels_are_not_split(self):
        # "run X" / "owner X" / "⧉ window" wrap as a whole, not mid-label.
        lines = _text(40).splitlines()
        for label in ("run 20261022-0915", "owner pm-project_manager-c5a1006b",
                      "⧉ review-#233"):
            assert any(label in ln for ln in lines), label

    @pytest.mark.parametrize("width", range(30, 100))
    def test_separators_never_start_or_end_a_line(self, width):
        # A " · " at a break is swallowed: the break itself separates.
        off = mixed_inputs()
        off["targets"] = {}  # an off header with run + owner
        for status in (mixed_status(), edge_status(), st.build_status(off)):
            for ln in st.format_text(status, width=width).splitlines():
                assert not ln.strip().startswith("·"), ln
                assert not ln.rstrip().endswith("·"), ln

    def test_wide_characters_counted_by_cells(self):
        inp = mixed_inputs()
        for p in inp["prs"]:
            if p["id"] == "pr-6c7d8e9":
                p["title"] = "界面 主题 🎨 对比 " * 6
        text = st.format_text(st.build_status(inp), width=50)
        for ln in text.splitlines():
            assert cell_len(ln) <= 50, ln
        assert text.count("🎨") == 6

    def test_styling_does_not_count_toward_width(self):
        for ln in _text(60, color=True).splitlines():
            assert cell_len(ANSI.sub("", ln)) <= 60

    def test_escape_sequences_never_reach_the_output(self):
        # A title or reason carrying terminal escapes (a QA error copied
        # from coloured tool output): plain output has no ESC bytes, widths
        # count only what is shown, and colour output only has our SGR.
        inp = mixed_inputs()
        for p in inp["prs"]:
            if p["id"] == "pr-6c7d8e9":
                p["title"] = "Fix \x1b[31mred\x1b[0m popup\x07 \x1b]0;t\x07ok"
        inp["qa_loops"]["pr-2e3f4a5"] = {
            "running": False, "error": "boom \x1b[1;33mwarn\x1b[0m\x00 end"}
        status = st.build_status(inp)
        plain = st.format_text(status, width=40)
        assert "\x1b" not in plain and "\x07" not in plain
        assert "\x00" not in plain
        assert "Fix red popup ok" in " ".join(_row_block(plain, "◎ #238").split())
        assert "error: boom warn end" in " ".join(
            _row_block(plain, "└ #235").split())
        assert all(cell_len(ln) <= 40 for ln in plain.splitlines())
        colored = st.format_text(status, width=40, color=True)
        assert ANSI.sub("", colored) == plain
        popup = "".join(view.to_rich(ln).plain
                        for ln in view.report_lines(status, 40))
        assert "\x1b" not in popup
        # The JSON keeps the data verbatim.
        assert "\x1b[1;33m" in next(
            r for r in status["runs"] if r["pr_id"] == "pr-2e3f4a5")["reason"]

    @pytest.mark.parametrize("width", range(30, 100))
    def test_labels_wider_than_a_line_break_between_words(self, width):
        # A single label wider than the line (several wait holders, a long
        # owner session, a launch-retry token) breaks at its inner spaces,
        # never mid-word through a PR id or session name.
        prs = [_pr("pr-aaaaaaa", "in_review", title="Shared base")] + [
            _pr(p, deps=["pr-aaaaaaa"]) for p in
            ("pr-bbbbbbb", "pr-ccccccc", "pr-ddddddd", "pr-eeeeeee")]
        status = st.build_status({
            "prs": prs, "enabled": True,
            "targets": {"pr-bbbbbbb": {}, **{
                p: {"wait_for_merge": True}
                for p in ("pr-ccccccc", "pr-ddddddd", "pr-eeeeeee")}},
            "review_loops": {"pr-aaaaaaa": {
                "running": True, "iteration": 3, "attempts": 2,
                "verdict": "LAUNCH_FAILED"}},
            "owner": {"session": "pm-project_manager-c5a1006b"},
        })
        text = st.format_text(status, width=width)
        assert "review #3 (launch retry 2)" in " ".join(text.split())
        assert "[wait-for-merge ← pr-ccccccc, pr-ddddddd, pr-eeeeeee]" in \
            " ".join(text.split())
        for ln in text.splitlines():
            assert cell_len(ln) <= width, ln
            for word in ln.split():
                assert not re.fullmatch(r"\[?pr-[a-e]{1,6}", word), ln
                assert not word.startswith(("pm-project_manager-",
                                            "manager-")) or \
                    word == "pm-project_manager-c5a1006b", ln
        # The lead word of a label stays with its value when both fit.
        assert "[wait-for-merge ←" in text

    def test_overlong_token_is_split_not_overflowing(self):
        lines = view.wrap([("x" * 50, "id")], 30, "    ")
        assert all(cell_len(view.plain(ln)) <= 30 for ln in lines)
        assert "".join(view.plain(ln).strip() for ln in lines) == "x" * 50


# ---------------------------------------------------------------------------
# Highlighting
# ---------------------------------------------------------------------------

RED_LABEL = "\x1b[1;37;41m"


class TestHighlight:
    def test_human_waits_have_red_labels(self):
        text = _text(color=True)
        for label in ("MANUAL MERGE", "IMPL SPEC REVIEW", "QA SPEC REVIEW",
                      "INPUT_REQUIRED"):
            assert f"{RED_LABEL}{label}\x1b[0m" in text, label
        assert text.count(RED_LABEL) == 5

    def test_running_under_wait_policy_is_not_red(self):
        text = _text(color=True)
        for head in ("└ \x1b[0m\x1b[1m#233", "◎ \x1b[0m\x1b[1m#240"):
            line = next(ln for ln in text.splitlines() if head in ln)
            assert "\x1b[1;37;41m" not in line and "\x1b[1;31m" not in line
        assert "\x1b[32mRUNNING" in text

    def test_text_labels_without_color(self):
        text = _text()
        assert "\x1b" not in text
        for label in ("MANUAL MERGE", "IMPL SPEC REVIEW", "QA SPEC REVIEW",
                      "INPUT_REQUIRED"):
            assert label in text

    def test_popup_colours_round_to_the_cli_colours(self):
        # Textual swaps named ANSI colours for theme RGB, which a 16-colour
        # pane (TERM=screen) showed as magenta labels and red WAITING.
        from rich.color import ColorSystem
        from rich.style import Style

        def ansi(style, attr):
            c = getattr(Style.parse(style), attr)
            return c and c.downgrade(ColorSystem.STANDARD).number

        for role, style in view.ROLE_STYLES.items():
            popup = view.POPUP_STYLES[role]
            assert "red" not in popup and "yellow" not in popup, role
            for attr in ("color", "bgcolor"):
                assert ansi(popup, attr) == ansi(style, attr), (role, attr)
        assert ansi(view.POPUP_STYLES["attention"], "bgcolor") == 1
        assert ansi(view.POPUP_STYLES["state_waiting"], "color") == 3

    def test_header_lists_who_needs_you(self):
        need = view.needs_human(mixed_status())
        assert {r["pr_id"] for r in need} == NEED_YOU
        head = _text().split("◎")[0]
        # Report order (one forest row each), so the list reads like the
        # rows below it.
        assert "⚠ 5 need you: #236, #231, #239, #237, #241" in \
            " ".join(head.split())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_status(*args, env=None):
    from pm_core.cli import cli
    with patch("pm_core.cli.autostart._request",
               return_value={"ok": True, "status": mixed_status()}):
        return CliRunner().invoke(cli, ["autostart", "status", *args],
                                  env=env or {})


class TestCLI:
    def test_redirected_output_is_plain_99(self):
        res = _cli_status(env={"COLUMNS": None, "NO_COLOR": None})
        assert res.exit_code == 0, res.output
        assert "\x1b" not in res.output
        assert max(cell_len(ln) for ln in res.output.splitlines()) <= 99
        assert "MANUAL MERGE" in res.output

    def test_width_option(self):
        res = _cli_status("--width", "60")
        assert max(cell_len(ln) for ln in res.output.splitlines()) <= 60

    def test_width_follows_the_terminal_up_to_99(self, monkeypatch):
        from pm_core.cli import autostart as cli_as

        class Tty:
            def isatty(self):
                return True

        # A narrower terminal narrows the report; a wider one stops at 99.
        for cols, want in (("60", 60), ("200", 99), ("10", view.MIN_WIDTH)):
            monkeypatch.setenv("COLUMNS", cols)
            assert cli_as._status_width(None) == want
            res = _cli_status(env={"COLUMNS": cols, "NO_COLOR": None})
            assert max(cell_len(ln) for ln in res.output.splitlines()) \
                <= want
        # --width wins over the terminal.
        assert cli_as._status_width(45) == 45
        # Redirected with no COLUMNS: 99, whatever the real terminal is.
        monkeypatch.delenv("COLUMNS")
        assert cli_as._status_width(None) == 99
        monkeypatch.setattr(cli_as.sys, "stdout", Tty())
        with patch("shutil.get_terminal_size",
                   return_value=os.terminal_size((72, 24))):
            assert cli_as._status_width(None) == 72

    def test_color_flag_and_no_color(self):
        assert RED_LABEL in _cli_status("--color").output
        assert "\x1b" not in _cli_status("--no-color").output

    def test_color_auto_detection(self, monkeypatch):
        from pm_core.cli import autostart as cli_as

        class Tty:
            def isatty(self):
                return True

        monkeypatch.setattr(cli_as.sys, "stdout", Tty())
        monkeypatch.delenv("NO_COLOR", raising=False)
        monkeypatch.setenv("TERM", "xterm")
        assert cli_as._status_color(None) is True
        monkeypatch.setenv("NO_COLOR", "1")
        assert cli_as._status_color(None) is False
        assert cli_as._status_color(True) is True
        monkeypatch.delenv("NO_COLOR")
        monkeypatch.setenv("TERM", "dumb")
        assert cli_as._status_color(None) is False

    def test_json_is_full_status_without_ansi(self):
        res = _cli_status("--json", "--color")
        assert "\x1b" not in res.output
        data = json.loads(res.output)
        assert data.pop("ok") is True
        assert data == json.loads(json.dumps(mixed_status(), default=sorted))
        assert data["schema"] == st.SCHEMA


# ---------------------------------------------------------------------------
# TUI runs popup — same layout, same human-action set
# ---------------------------------------------------------------------------

def _popup(size, keys=()):
    from textual.app import App
    from textual.widgets import Static
    from pm_core.tui.screens import AutoRunsScreen

    status = mixed_status()
    out = {}

    class Host(App):
        def log_message(self, msg, **kw):
            pass

    async def body():
        app = Host()
        with patch("pm_core.tui.auto_start.build_status",
                   return_value=status):
            async with app.run_test(size=size) as pilot:
                app.push_screen(AutoRunsScreen())
                await pilot.pause()
                await pilot.pause()
                for k in keys:
                    await pilot.press(k)
                await pilot.pause()
                screen = app.screen
                out["body"] = screen.query_one("#runs-body", Static).render()
                out["title"] = screen.query_one("#runs-title", Static).render()
                out["footer"] = screen.query_one(
                    "#runs-footer", Static).render()
                out["width"] = screen._width
                out["selected"] = screen._selected_key
                out["body_w"] = screen.query_one(
                    "#runs-body", Static).content_region.width
                container = screen.query_one("#runs-container")
                out["viewport"] = container.content_region
                out["footer_region"] = screen.query_one(
                    "#runs-footer", Static).region
                # Screen rows of the selected row's lines.
                body_w = screen.query_one("#runs-body", Static)
                lines = out["body"].plain.splitlines()
                first = next(i for i, ln in enumerate(lines)
                             if ln.startswith("▶"))
                last = first
                while (last + 1 < len(lines)
                       and lines[last + 1].startswith("    ")
                       and lines[last + 1].lstrip()[:1] not in ("◎", "└")):
                    last += 1
                y0 = (body_w.virtual_region.y + first
                      - int(container.scroll_y) + out["viewport"].y)
                out["selected_rows"] = (y0, y0 + last - first + 1)

    asyncio.run(body())
    return out


def _red_ids(text) -> set[str]:
    """PR ids on popup lines carrying the red attention style."""
    ids = set()
    plain = text.plain
    for span in text.spans:
        # The popup body is Textual Content: the attention label is the
        # only span with a red background (explicit RGB, see POPUP_STYLES).
        bg = getattr(span.style, "background", None)
        if bg is not None and (bg.r, bg.g, bg.b) == (0xd7, 0, 0):
            line = plain[:span.start].rsplit("\n", 1)[-1]
            ids.add(re.findall(r"pr-[0-9a-f]{7}", line)[-1])
    return ids


class TestPopup:
    def test_wide_popup_matches_cli_and_fits(self):
        out = _popup((160, 70))
        body = out["body"]
        assert out["width"] == 99
        lines = body.plain.splitlines()
        assert all(cell_len(ln) <= out["body_w"] for ln in lines)
        # Same rows as the CLI report, plus the 2-column selection gutter.
        cli = _text(99)
        header_len = len(cli.split("◎")[0].splitlines())
        assert [ln[2:] for ln in lines] == cli.splitlines()[header_len:]
        assert _red_ids(body) == NEED_YOU
        # The selection is a background bar: reverse would invert the
        # selected row's red attention label.
        assert not any(getattr(sp.style, "reverse", None)
                       for sp in body.spans)
        assert "⚠ 5 need you" in out["title"].plain
        assert all(cell_len(ln) <= 99
                   for ln in out["title"].plain.splitlines())

    def test_narrow_popup_wraps_to_its_width(self):
        out = _popup((64, 70))
        lines = out["body"].plain.splitlines()
        assert out["width"] < 64
        assert all(cell_len(ln) <= out["body_w"] for ln in lines), lines
        assert _red_ids(out["body"]) == NEED_YOU
        assert all(cell_len(ln) <= out["body_w"]
                   for ln in out["title"].plain.splitlines())

    @pytest.mark.parametrize("cols", [44, 64, 74])
    def test_footer_hint_wraps_without_dangling_separators(self, cols):
        lines = _popup((cols, 70))["footer"].plain.splitlines()
        assert len(lines) > 1
        for ln in lines:
            assert not ln.strip().startswith("·"), lines
            assert not ln.rstrip().endswith("·"), lines

    @pytest.mark.parametrize("size", [(50, 50), (140, 20)])
    def test_footer_hint_stays_in_view_when_rows_overflow(self, size):
        # The rows scroll; the key hint is docked below them and the
        # selected row is scrolled clear of it, down to the last row.
        for keys in ((), ("j",) * 12):
            out = _popup(size, keys=keys)
            footer, viewport = out["footer_region"], out["viewport"]
            assert footer.height and viewport.contains_region(footer)
            y0, y1 = out["selected_rows"]
            assert viewport.y <= y0 and y1 <= footer.y

    def test_navigation_moves_over_wrapped_rows(self):
        # #238, #235, #236, #240, #234, #233: one stop per PR.
        out = _popup((80, 70), keys=["j"] * 5)
        assert out["selected"] == "pr-1c2d3e4"
        sel = [ln for ln in out["body"].plain.splitlines()
               if ln.startswith("▶")]
        assert len(sel) == 1 and "#233" in sel[0]

    def test_rows_are_one_per_pr_like_the_cli(self):
        out = _popup((160, 70), keys=["j"] * 40)
        heads = [ln for ln in out["body"].plain.splitlines()
                 if ln[2:].lstrip()[:1] in ("◎", "└")]
        ids = [re.findall(r"pr-[0-9a-f]{7}", ln)[0] for ln in heads]
        assert len(ids) == len(set(ids)) == len(mixed_status()["runs"])
        # j past the end stays on the last row.
        assert out["selected"] == ids[-1] == "pr-aa1b2c3"
