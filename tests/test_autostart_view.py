"""Compact, highlighted auto-start status (pr-8700be3).

Shared layout (``pm_core.autostart_view``) used by ``pm autostart status``
and the TUI runs popup: duplicate suppression, width/wrapping, red
human-action labels, plain/JSON output, and CLI/TUI agreement.
"""

import asyncio
import json
import re
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from rich.cells import cell_len

from pm_core import autostart_state as st
from pm_core import autostart_view as view

from autostart_mixed_fixture import mixed_inputs, mixed_status

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
            "explicit_hold": False, "held_by": ["pr-4a5b6c7"]}
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
    def test_wait_policy_stated_once_per_group(self):
        text = _text()
        wait_group = text.split("◎ #238")[0]
        assert wait_group.count("wait-for-merge") == 2  # header + title word
        assert "[wait-for-merge]" in _row_block(text, "◎ #240")
        assert "← #240" not in wait_group
        # Blockers name PRs and status only — no hold cause per blocker.
        assert "blocked on #233 (in_review), #231 (sign_off)" in wait_group

    def test_meaningful_exceptions_kept(self):
        text = _text()
        # Shared dep of an auto-merge target held by the wait chain.
        auto_group = text.split("◎ #238")[1].split("◎ #239")[0]
        assert "[wait-for-merge ← #240]" in auto_group
        assert "also needed by #240" in auto_group
        # Explicit stop mark on a dep under a stop-before-merge target.
        assert "[stop-before-merge]" in _row_block(text, "└ #241")

    def test_flat_mode_keeps_blocker_hold_causes(self):
        status = mixed_status()
        run = next(r for r in status["runs"] if r["pr_id"] == "pr-3f4a5b6")
        names = view.display_names(status)
        assert view.reason_text(run, grouped=True, names=names) == \
            "blocked on #233 (in_review), #231 (sign_off)"
        # Without a group no row explains the hold, so the cause stays;
        # the holding target is named by its display id, like its row.
        assert view.reason_text(run, grouped=False, names=names) == (
            "blocked on #233 (in_review, wait-for-merge ← #240), "
            "#231 (sign_off, wait-for-merge ← #240)")

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

    def test_header_wraps(self):
        head = _text(60).split("◎")[0].splitlines()
        assert len(head) > 1 and all(cell_len(ln) <= 60 for ln in head)
        assert head[1].startswith("  ")

    def test_metadata_labels_are_not_split(self):
        # "run X" / "owner X" / "⧉ window" wrap as a whole, not mid-label.
        text = _text(40)
        assert "  run 20261022-0915" in text
        assert "owner pm-project_manager-c5a1006b" in text
        assert "⧉ review-#233" in text

    @pytest.mark.parametrize("width", range(30, 100))
    def test_separators_never_start_or_end_a_line(self, width):
        # A " · " at a break is swallowed: the break itself separates.
        inp = mixed_inputs()
        inp["targets"], inp["all_mode"] = {}, True  # header wraps at 99
        for status in (mixed_status(), st.build_status(inp)):
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

    def test_header_lists_who_needs_you(self):
        need = view.needs_human(mixed_status())
        assert {r["pr_id"] for r in need} == NEED_YOU
        head = _text().split("◎")[0]
        assert "⚠ 5 need you: #231, #236, #239, #237, #241" in \
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
                out["width"] = screen._width
                out["selected"] = screen._selected_key
                out["body_w"] = screen.query_one(
                    "#runs-body", Static).content_region.width

    asyncio.run(body())
    return out


def _red_ids(text) -> set[str]:
    """PR ids on popup lines carrying the red attention style."""
    ids = set()
    plain = text.plain
    for span in text.spans:
        # The popup body is Textual Content: the attention label is the
        # only span with a red (ANSI 1) background.
        bg = getattr(span.style, "background", None)
        if getattr(bg, "ansi", None) == 1:
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

    def test_navigation_moves_over_wrapped_rows(self):
        out = _popup((80, 70), keys=["j", "j"])
        assert out["selected"] == ("pr-4a5b6c7", "pr-1c2d3e4")
        sel = [ln for ln in out["body"].plain.splitlines()
               if ln.startswith("▶")]
        assert len(sel) == 1 and "#233" in sel[0]
