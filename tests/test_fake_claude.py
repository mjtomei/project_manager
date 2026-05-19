"""Tests for pm_core.fake_claude and the pm fake-claude CLI command."""

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import call, patch

import pytest

from pm_core.fake_claude import (
    ALL_VERDICTS,
    ALL_VERDICT_CHOICES,
    NO_VERDICT,
    SINGLE_LINE_VERDICTS,
    BLOCK_VERDICTS,
    SESSION_TYPE_VERDICTS,
    run_fake_claude,
    validate_session_verdicts,
    _resolve_block_name,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "fake_claude"
BIN_FAKE_CLAUDE = Path(__file__).parent.parent / "bin" / "fake-claude"


# ---------------------------------------------------------------------------
# _resolve_block_name
# ---------------------------------------------------------------------------

class TestResolveBlockName:
    def test_direct_name(self):
        assert _resolve_block_name("FLAGGED") == "FLAGGED"
        assert _resolve_block_name("REFINED_STEPS") == "REFINED_STEPS"
        assert _resolve_block_name("QA_PLAN") == "QA_PLAN"

    def test_end_marker_resolves(self):
        assert _resolve_block_name("FLAGGED_END") == "FLAGGED"
        assert _resolve_block_name("REFINED_STEPS_END") == "REFINED_STEPS"
        assert _resolve_block_name("QA_PLAN_END") == "QA_PLAN"

    def test_case_insensitive(self):
        assert _resolve_block_name("flagged") == "FLAGGED"
        assert _resolve_block_name("flagged_end") == "FLAGGED"

    def test_unknown_returns_none(self):
        assert _resolve_block_name("PASS") is None
        assert _resolve_block_name("UNKNOWN") is None


# ---------------------------------------------------------------------------
# run_fake_claude — single-line verdicts
# ---------------------------------------------------------------------------

class TestRunFakeClaudeSingleLine:
    def _capture(self, **kwargs) -> str:
        buf = StringIO()
        with patch("sys.stdout", buf):
            run_fake_claude(**kwargs)
        return buf.getvalue()

    @pytest.mark.parametrize("verdict", SINGLE_LINE_VERDICTS)
    def test_single_line_verdict_present(self, verdict):
        out = self._capture(verdict=verdict, preamble=0)
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        assert verdict in lines, f"Expected {verdict!r} in output lines: {lines}"

    @pytest.mark.parametrize("verdict", SINGLE_LINE_VERDICTS)
    def test_verdict_on_own_line(self, verdict):
        out = self._capture(verdict=verdict, preamble=0)
        for line in out.splitlines():
            if line.strip() == verdict:
                break
        else:
            pytest.fail(f"{verdict!r} not found as a standalone line in:\n{out}")

    def test_preamble_lines_written(self):
        out = self._capture(verdict="PASS", preamble=5)
        non_empty = [l for l in out.splitlines() if l.strip() and l.strip() != "PASS"]
        assert len(non_empty) == 5

    def test_preamble_zero(self):
        out = self._capture(verdict="PASS", preamble=0)
        non_empty = [l for l in out.splitlines() if l.strip() and l.strip() != "PASS"]
        assert len(non_empty) == 0

    def test_preamble_large(self):
        # Should cycle through _PREAMBLE_LINES without IndexError
        out = self._capture(verdict="PASS", preamble=25)
        lines = [l for l in out.splitlines() if l.strip() and l.strip() != "PASS"]
        assert len(lines) == 25


# ---------------------------------------------------------------------------
# run_fake_claude — block verdicts
# ---------------------------------------------------------------------------

class TestRunFakeClaudeBlockVerdicts:
    def _capture(self, **kwargs) -> str:
        buf = StringIO()
        with patch("sys.stdout", buf):
            run_fake_claude(**kwargs)
        return buf.getvalue()

    @pytest.mark.parametrize("block_name,markers", BLOCK_VERDICTS.items())
    def test_start_and_end_markers_present(self, block_name, markers):
        start, end = markers
        out = self._capture(verdict=block_name, preamble=0)
        assert start in out, f"Expected {start!r} in output"
        assert end in out, f"Expected {end!r} in output"

    @pytest.mark.parametrize("block_name,markers", BLOCK_VERDICTS.items())
    def test_start_before_end(self, block_name, markers):
        start, end = markers
        out = self._capture(verdict=block_name, preamble=0)
        assert out.index(start) < out.index(end)

    def test_custom_body_included(self):
        out = self._capture(verdict="FLAGGED", preamble=0, body="custom failure text")
        assert "custom failure text" in out

    def test_default_body_included(self):
        out = self._capture(verdict="FLAGGED", preamble=0)
        assert "FAILED" in out

    def test_end_marker_as_verdict(self):
        """Passing FLAGGED_END as --verdict should also work."""
        out = self._capture(verdict="FLAGGED_END", preamble=0)
        assert "FLAGGED_START" in out
        assert "FLAGGED_END" in out

    def test_body_between_markers(self):
        out = self._capture(verdict="REFINED_STEPS", preamble=0, body="step A\nstep B")
        lines = out.splitlines()
        start_idx = next(i for i, l in enumerate(lines) if "REFINED_STEPS_START" in l)
        end_idx = next(i for i, l in enumerate(lines) if "REFINED_STEPS_END" in l)
        body_lines = [l for l in lines[start_idx + 1:end_idx] if l.strip()]
        assert any("step A" in l for l in body_lines)
        assert any("step B" in l for l in body_lines)


# ---------------------------------------------------------------------------
# run_fake_claude — delays
# ---------------------------------------------------------------------------

class TestRunFakeClaudeDelay:
    def test_delay_zero_no_sleep(self):
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep") as mock_sleep:
            run_fake_claude(verdict="PASS", preamble=0, delay=0.0)
        mock_sleep.assert_not_called()

    def test_delay_calls_sleep(self):
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep") as mock_sleep:
            run_fake_claude(verdict="PASS", preamble=0, delay=1.5)
        mock_sleep.assert_called_once_with(1.5)

    def test_preamble_delay_between_lines(self):
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep") as mock_sleep:
            run_fake_claude(verdict="PASS", preamble=3, preamble_delay=0.5)
        # Should sleep between lines 0→1 and 1→2 (not after the last line)
        preamble_sleeps = [c for c in mock_sleep.call_args_list if c == call(0.5)]
        assert len(preamble_sleeps) == 2

    def test_preamble_delay_zero_no_sleep(self):
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep") as mock_sleep:
            run_fake_claude(verdict="PASS", preamble=3, preamble_delay=0.0)
        mock_sleep.assert_not_called()

    def test_preamble_delay_single_line_no_sleep(self):
        """With preamble=1 there are no inter-line gaps."""
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep") as mock_sleep:
            run_fake_claude(verdict="PASS", preamble=1, preamble_delay=1.0)
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# run_fake_claude — body lines (generated, batched)
# ---------------------------------------------------------------------------

class TestRunFakeClaudeBodyLines:
    def _capture(self, **kwargs) -> str:
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep"):
            run_fake_claude(**kwargs)
        return buf.getvalue()

    def test_body_lines_zero_no_extra_output(self):
        out_with = self._capture(verdict="PASS", preamble=2, body_lines=0)
        out_without = self._capture(verdict="PASS", preamble=2)
        assert out_with == out_without

    def test_body_lines_adds_output(self):
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep"):
            run_fake_claude(verdict="PASS", preamble=0, body_lines=5)
        lines = [l for l in buf.getvalue().splitlines() if l.strip() and l.strip() != "PASS"]
        assert len(lines) == 5

    def test_body_lines_cycles_through_pool(self):
        """More body_lines than pool size should not raise."""
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep"):
            run_fake_claude(verdict="PASS", preamble=0, body_lines=30)
        lines = [l for l in buf.getvalue().splitlines() if l.strip() and l.strip() != "PASS"]
        assert len(lines) == 30

    def test_body_delay_between_batches(self):
        with patch("sys.stdout", StringIO()), patch("time.sleep") as mock_sleep:
            # 6 lines, batch=2 → 3 batches → 2 inter-batch sleeps (not after last)
            run_fake_claude(verdict="PASS", preamble=0,
                            body_lines=6, body_batch=2, body_delay=0.3)
        body_sleeps = [c for c in mock_sleep.call_args_list if c == call(0.3)]
        assert len(body_sleeps) == 2

    def test_body_delay_batch1_one_sleep_per_line(self):
        with patch("sys.stdout", StringIO()), patch("time.sleep") as mock_sleep:
            # 4 lines, batch=1 → sleep after lines 1,2,3 (not line 4)
            run_fake_claude(verdict="PASS", preamble=0,
                            body_lines=4, body_batch=1, body_delay=0.2)
        body_sleeps = [c for c in mock_sleep.call_args_list if c == call(0.2)]
        assert len(body_sleeps) == 3

    def test_body_delay_zero_no_sleep(self):
        with patch("sys.stdout", StringIO()), patch("time.sleep") as mock_sleep:
            run_fake_claude(verdict="PASS", preamble=0,
                            body_lines=5, body_batch=1, body_delay=0.0)
        mock_sleep.assert_not_called()

    def test_body_lines_appear_before_verdict(self):
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep"):
            run_fake_claude(verdict="PASS", preamble=0, body_lines=3)
        out = buf.getvalue()
        # PASS must come after the body lines
        body_line = "Examining the test harness configuration…"
        assert out.index(body_line) < out.index("PASS")

    def test_body_lines_and_preamble_combined(self):
        buf = StringIO()
        with patch("sys.stdout", buf), patch("time.sleep"):
            run_fake_claude(verdict="PASS", preamble=2, body_lines=3)
        lines = [l for l in buf.getvalue().splitlines() if l.strip() and l.strip() != "PASS"]
        assert len(lines) == 5  # 2 preamble + 3 body


# ---------------------------------------------------------------------------
# run_fake_claude — stream mode
# ---------------------------------------------------------------------------

class TestRunFakeClaudeStream:
    def test_stream_mode_produces_same_content(self):
        """Stream mode should emit the same text as non-stream, just delayed."""
        from io import StringIO as _SIO

        with patch("time.sleep"):
            buf_stream = _SIO()
            with patch("sys.stdout", buf_stream):
                run_fake_claude(verdict="PASS", preamble=2, stream=True)

            buf_normal = _SIO()
            with patch("sys.stdout", buf_normal):
                run_fake_claude(verdict="PASS", preamble=2, stream=False)

        assert buf_stream.getvalue() == buf_normal.getvalue()

    def test_stream_mode_sleeps_per_character(self):
        with patch("sys.stdout", StringIO()), patch("time.sleep") as mock_sleep:
            run_fake_claude(verdict="PASS", preamble=0, stream=True)
        # Should have slept at least once per character
        assert mock_sleep.call_count > 0

    def test_custom_char_delay(self):
        with patch("sys.stdout", StringIO()), patch("time.sleep") as mock_sleep:
            run_fake_claude(verdict="PASS", preamble=0, stream=True, char_delay=0.05)
        assert all(c == call(0.05) for c in mock_sleep.call_args_list)


# ---------------------------------------------------------------------------
# Fixture file content validation
# ---------------------------------------------------------------------------

class TestFixtures:
    """Verify fixture files match the output of run_fake_claude."""

    @pytest.mark.parametrize("verdict,filename", [
        ("PASS", "pass.txt"),
        ("NEEDS_WORK", "needs_work.txt"),
        ("INPUT_REQUIRED", "input_required.txt"),
        ("VERIFIED", "verified.txt"),
        ("READY", "ready.txt"),
        ("FINALIZE_DONE", "finalize_done.txt"),
        ("FINALIZE_BLOCKED", "finalize_blocked.txt"),
    ])
    def test_single_line_fixture_contains_verdict(self, verdict, filename):
        fixture = FIXTURES_DIR / filename
        content = fixture.read_text()
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        assert verdict in lines, f"{verdict!r} not found as standalone line in {filename}"

    @pytest.mark.parametrize("block_name,filename", [
        ("FLAGGED", "flagged.txt"),
        ("REFINED_STEPS", "refined_steps.txt"),
        ("REFINER_REJECT", "refiner_reject.txt"),
        ("QA_PLAN", "qa_plan.txt"),
    ])
    def test_block_fixture_contains_markers(self, block_name, filename):
        fixture = FIXTURES_DIR / filename
        content = fixture.read_text()
        start, end = BLOCK_VERDICTS[block_name]
        assert start in content, f"{start!r} missing from {filename}"
        assert end in content, f"{end!r} missing from {filename}"


# ---------------------------------------------------------------------------
# Verdict detection integration: output passes loop_shared.extract_verdict
# ---------------------------------------------------------------------------

class TestVerdictDetection:
    """Ensure fake-claude output is detectable by the real verdict detector."""

    def _capture(self, **kwargs) -> str:
        buf = StringIO()
        with patch("sys.stdout", buf):
            run_fake_claude(**kwargs)
        return buf.getvalue()

    @staticmethod
    def _detect(content: str, verdicts: tuple[str, ...]) -> str | None:
        """Scan content line-by-line for a verdict keyword.

        Mirrors how production verdict detection
        (``pm_core.loop_shared.match_verdict``) keys on a keyword that is the
        entire content of a line.
        """
        from pm_core.loop_shared import match_verdict
        for line in content.splitlines():
            hit = match_verdict(line, verdicts)
            if hit:
                return hit
        return None

    def test_pass_detected_by_extract_verdict(self):
        out = self._capture(verdict="PASS", preamble=3)
        result = self._detect(
            out, ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"))
        assert result == "PASS"

    def test_needs_work_detected(self):
        out = self._capture(verdict="NEEDS_WORK", preamble=3)
        result = self._detect(
            out, ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"))
        assert result == "NEEDS_WORK"

    def test_input_required_detected(self):
        out = self._capture(verdict="INPUT_REQUIRED", preamble=3)
        result = self._detect(
            out, ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"))
        assert result == "INPUT_REQUIRED"

    def test_verified_detected(self):
        out = self._capture(verdict="VERIFIED", preamble=3)
        result = self._detect(out, ("VERIFIED", "FLAGGED_END"))
        assert result == "VERIFIED"

    def test_flagged_end_detected(self):
        out = self._capture(verdict="FLAGGED", preamble=3)
        result = self._detect(out, ("VERIFIED", "FLAGGED_END"))
        assert result == "FLAGGED_END"

    def test_refined_steps_end_detected(self):
        out = self._capture(verdict="REFINED_STEPS", preamble=3)
        result = self._detect(out, ("REFINED_STEPS_END",))
        assert result == "REFINED_STEPS_END"


# ---------------------------------------------------------------------------
# run_fake_claude — no-verdict (NONE) sessions
# ---------------------------------------------------------------------------

class TestRunFakeClaudeNoVerdict:
    def _capture(self, **kwargs) -> str:
        kwargs.setdefault("hold", 0)  # don't block the test on stdin
        buf = StringIO()
        with patch("sys.stdout", buf):
            run_fake_claude(**kwargs)
        return buf.getvalue()

    @pytest.mark.parametrize("verdict", [None, "NONE", "none"])
    def test_no_verdict_emits_no_keyword(self, verdict):
        out = self._capture(verdict=verdict, preamble=3)
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        # Preamble prose only — no verdict keyword, no block markers.
        assert len(lines) == 3
        for v in ALL_VERDICTS:
            assert v not in lines
        for start, end in BLOCK_VERDICTS.values():
            assert start not in lines and end not in lines

    def test_no_verdict_still_writes_body_lines(self):
        out = self._capture(verdict="NONE", preamble=2, body_lines=4)
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 6

    def test_hold_sleeps_then_returns(self):
        with patch("pm_core.fake_claude.time.sleep") as mock_sleep:
            self._capture(verdict="NONE", preamble=0, hold=2.5)
        assert call(2.5) in mock_sleep.call_args_list

    def test_hold_zero_does_not_sleep_or_block(self):
        with patch("pm_core.fake_claude.time.sleep") as mock_sleep:
            self._capture(verdict="NONE", preamble=0, hold=0)
        assert call(0) not in mock_sleep.call_args_list

    def test_hold_none_blocks_on_stdin(self):
        # hold=None must read stdin until EOF — emulates staying open until
        # the pane's tty closes.  A finite StringIO returns immediately.
        buf = StringIO()
        with patch("sys.stdout", buf), \
             patch("sys.stdin", StringIO("")) as fake_stdin:
            run_fake_claude(verdict="NONE", preamble=1, hold=None)
        # stdin was consumed (read to EOF)
        assert fake_stdin.read() == ""


# ---------------------------------------------------------------------------
# bin/fake-claude executable
# ---------------------------------------------------------------------------

class TestBinFakeClaude:
    def test_executable_exists(self):
        assert BIN_FAKE_CLAUDE.exists(), f"bin/fake-claude not found at {BIN_FAKE_CLAUDE}"

    def test_executable_bit_set(self):
        import os
        mode = BIN_FAKE_CLAUDE.stat().st_mode
        assert mode & 0o111, "bin/fake-claude is not executable"

    def test_pass_verdict_output(self):
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE), "--verdict", "PASS", "--preamble", "1"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        assert "PASS" in lines

    def test_needs_work_verdict_output(self):
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE), "--verdict", "NEEDS_WORK", "--preamble", "0"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "NEEDS_WORK" in result.stdout

    def test_flagged_block_output(self):
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE), "--verdict", "FLAGGED",
             "--preamble", "0", "--body", "test failure"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "FLAGGED_START" in result.stdout
        assert "test failure" in result.stdout
        assert "FLAGGED_END" in result.stdout

    def test_no_verdict_output(self):
        """--verdict NONE emits output but no verdict keyword; --hold 0 exits."""
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE), "--verdict", "NONE",
             "--preamble", "2", "--hold", "0"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        assert len(lines) == 2
        for v in ALL_VERDICTS:
            assert v not in lines

    def test_no_verdict_blocks_until_stdin_closes(self):
        """Without --hold, a no-verdict session stays open until stdin EOF."""
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE), "--verdict", "NONE",
             "--preamble", "1"],
            input="",  # closing stdin (EOF) lets the held-open session exit
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0

    def test_invalid_verdict_fails(self):
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE), "--verdict", "INVALID_VERDICT"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_body_lines_flag(self):
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE), "--verdict", "PASS",
             "--preamble", "0", "--body-lines", "3"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        lines = [l for l in result.stdout.splitlines() if l.strip() and l.strip() != "PASS"]
        assert len(lines) == 3

    def test_help_flag(self):
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "verdict" in result.stdout.lower()
        assert "body-lines" in result.stdout
        assert "body-batch" in result.stdout
        assert "preamble-delay" in result.stdout


# ---------------------------------------------------------------------------
# ALL_VERDICTS completeness
# ---------------------------------------------------------------------------

class TestAllVerdicts:
    def test_all_verdicts_non_empty(self):
        assert len(ALL_VERDICTS) > 0

    def test_single_line_verdicts_in_all(self):
        for v in SINGLE_LINE_VERDICTS:
            assert v in ALL_VERDICTS, f"{v!r} missing from ALL_VERDICTS"

    def test_block_names_in_all(self):
        for name in BLOCK_VERDICTS:
            assert name in ALL_VERDICTS, f"Block name {name!r} missing from ALL_VERDICTS"

    def test_block_end_markers_in_all(self):
        for _, end in BLOCK_VERDICTS.values():
            assert end in ALL_VERDICTS, f"End marker {end!r} missing from ALL_VERDICTS"


# ---------------------------------------------------------------------------
# SESSION_TYPE_VERDICTS + validate_session_verdicts
# ---------------------------------------------------------------------------

class TestSessionTypeVerdicts:
    def test_all_session_types_present(self):
        from pm_core.model_config import SESSION_TYPES
        for st in SESSION_TYPES:
            assert st in SESSION_TYPE_VERDICTS, f"{st!r} missing from SESSION_TYPE_VERDICTS"

    def test_review_verdicts(self):
        allowed = SESSION_TYPE_VERDICTS["review"]
        assert "PASS" in allowed
        assert "NEEDS_WORK" in allowed
        assert "INPUT_REQUIRED" in allowed
        assert "PASS_WITH_SUGGESTIONS" not in allowed
        assert "VERIFIED" not in allowed
        assert "FLAGGED" not in allowed

    def test_qa_scenario_verdicts(self):
        allowed = SESSION_TYPE_VERDICTS["qa_scenario"]
        assert "PASS" in allowed
        assert "NEEDS_WORK" in allowed
        assert "INPUT_REQUIRED" in allowed
        assert "QA_PLAN" not in allowed
        assert "VERIFIED" not in allowed

    def test_qa_verification_verdicts(self):
        allowed = SESSION_TYPE_VERDICTS["qa_verification"]
        assert "VERIFIED" in allowed
        assert "FLAGGED" in allowed
        assert "PASS" not in allowed

    def test_qa_planning_verdicts(self):
        allowed = SESSION_TYPE_VERDICTS["qa_planning"]
        assert "QA_PLAN" in allowed
        assert "PASS" not in allowed

    def test_qa_concretize_verdicts(self):
        allowed = SESSION_TYPE_VERDICTS["qa_concretize"]
        assert "REFINED_STEPS" in allowed
        assert "REFINER_REJECT" in allowed
        assert "PASS" not in allowed   # refiner never emits the worker verdict

    def test_qa_finalize_verdicts(self):
        allowed = SESSION_TYPE_VERDICTS["qa_finalize"]
        assert "FINALIZE_DONE" in allowed
        assert "FINALIZE_BLOCKED" in allowed

    def test_watcher_verdicts(self):
        # Watchers emit READY / INPUT_REQUIRED — they are NOT no-verdict.
        allowed = SESSION_TYPE_VERDICTS["watcher"]
        assert "READY" in allowed
        assert "INPUT_REQUIRED" in allowed
        assert "PASS" not in allowed

    def test_impl_has_no_verdicts(self):
        assert SESSION_TYPE_VERDICTS["impl"] == ()

    def test_merge_has_no_verdicts(self):
        assert SESSION_TYPE_VERDICTS["merge"] == ()

    @pytest.mark.parametrize("st", [
        "plan", "meta", "guide", "cluster", "container",
        "qa_author", "qa_regression", "discuss", "watcher_review",
    ])
    def test_non_loop_session_types_registered_as_no_verdict(self, st):
        # Non-PR/QA-loop interactive sessions: registered so they can be
        # faked selectively, but they emit no verdict.
        assert st in SESSION_TYPE_VERDICTS
        assert SESSION_TYPE_VERDICTS[st] == ()
        # validation accepts an empty verdict set and rejects any verdict
        assert validate_session_verdicts(st, {}) == []
        assert validate_session_verdicts(st, {"PASS": 1}) != []

    def test_validate_valid_config(self):
        assert validate_session_verdicts("review", {"PASS": 70, "NEEDS_WORK": 30}) == []

    def test_validate_invalid_verdict(self):
        errors = validate_session_verdicts("review", {"VERIFIED": 100})
        assert len(errors) == 1
        assert "VERIFIED" in errors[0]
        assert "review" in errors[0]

    def test_validate_wrong_session_type_verdict(self):
        # QA_PLAN makes no sense in a review session
        errors = validate_session_verdicts("review", {"QA_PLAN": 1})
        assert errors

    def test_validate_unknown_session_type(self):
        errors = validate_session_verdicts("nonexistent", {"PASS": 1})
        assert errors
        assert "nonexistent" in errors[0]

    def test_validate_empty_verdicts_for_verdicted_type(self):
        # Empty verdicts dict is fine (means "use defaults")
        assert validate_session_verdicts("review", {}) == []

    def test_validate_verdicts_for_no_verdict_type(self):
        errors = validate_session_verdicts("impl", {"PASS": 1})
        assert errors

    def test_validate_empty_verdicts_for_no_verdict_type(self):
        # impl with empty verdicts = fine (nothing to fake)
        assert validate_session_verdicts("impl", {}) == []


# ---------------------------------------------------------------------------
# Session-file fake-claude override (paths.py)
# ---------------------------------------------------------------------------

_SAMPLE_CONFIG = {
    "_defaults": {"preamble": 3, "delay": 0.0},
    "review": {"verdicts": {"PASS": 70, "NEEDS_WORK": 20, "INPUT_REQUIRED": 10}},
    "qa_scenario": {"verdicts": {"PASS": 80, "NEEDS_WORK": 15, "INPUT_REQUIRED": 5}},
    "qa_verification": {"verdicts": {"VERIFIED": 80, "FLAGGED": 20}},
    "qa_planning": {"verdicts": {"QA_PLAN": 100}},
}


class TestFakeClaudeConfig:
    """Tests for fake_claude_config / fake_claude_config_for_type /
    set_fake_claude_config / clear_fake_claude."""

    def _setup(self, tmp_path, monkeypatch, tag="test-tag"):
        monkeypatch.setattr("pm_core.paths.sessions_dir", lambda: tmp_path)
        monkeypatch.setattr("pm_core.paths.get_session_tag", lambda **kw: tag)
        return tag

    def test_returns_none_when_no_file(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config
        self._setup(tmp_path, monkeypatch)
        assert fake_claude_config("nonexistent-tag") is None

    def test_round_trip(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        set_fake_claude_config(tag, _SAMPLE_CONFIG)
        assert fake_claude_config(tag) == _SAMPLE_CONFIG

    def test_clear_removes_file(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config, set_fake_claude_config, clear_fake_claude
        tag = self._setup(tmp_path, monkeypatch)
        set_fake_claude_config(tag, _SAMPLE_CONFIG)
        assert fake_claude_config(tag) is not None
        clear_fake_claude(tag)
        assert fake_claude_config(tag) is None

    def test_invalid_json_returns_none(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        sd = tmp_path / tag
        sd.mkdir(parents=True, exist_ok=True)
        (sd / "fake-claude").write_text("not valid json")
        assert fake_claude_config(tag) is None

    def test_set_raises_on_invalid_verdict(self, tmp_path, monkeypatch):
        from pm_core.paths import set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        bad_config = {"review": {"verdicts": {"VERIFIED": 100}}}  # VERIFIED not valid for review
        with pytest.raises(ValueError, match="VERIFIED"):
            set_fake_claude_config(tag, bad_config)

    def test_set_raises_on_unknown_session_type(self, tmp_path, monkeypatch):
        from pm_core.paths import set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="nonexistent"):
            set_fake_claude_config(tag, {"nonexistent": {"verdicts": {"PASS": 1}}})

    def test_set_raises_on_verdict_in_no_verdict_type(self, tmp_path, monkeypatch):
        from pm_core.paths import set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        with pytest.raises(ValueError):
            set_fake_claude_config(tag, {"impl": {"verdicts": {"PASS": 1}}})

    def test_defaults_and_binary_keys_are_not_validated_as_session_types(self, tmp_path, monkeypatch):
        from pm_core.paths import set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        # Should not raise
        set_fake_claude_config(tag, {
            "_defaults": {"preamble": 3},
            "binary": "/path/to/fake-claude",
            "review": {"verdicts": {"PASS": 1}},
        })

    # fake_claude_config_for_type

    def test_for_type_returns_none_without_session_type(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config_for_type, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        set_fake_claude_config(tag, _SAMPLE_CONFIG)
        assert fake_claude_config_for_type(None, tag) is None

    def test_for_type_returns_none_for_absent_type(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config_for_type, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        set_fake_claude_config(tag, _SAMPLE_CONFIG)
        # "impl" not in _SAMPLE_CONFIG → don't fake
        assert fake_claude_config_for_type("impl", tag) is None

    def test_for_type_returns_merged_config(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config_for_type, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        set_fake_claude_config(tag, _SAMPLE_CONFIG)
        result = fake_claude_config_for_type("review", tag)
        assert result is not None
        # verdicts from per-type config
        assert result["verdicts"] == {"PASS": 70, "NEEDS_WORK": 20, "INPUT_REQUIRED": 10}
        # preamble merged from _defaults
        assert result["preamble"] == 3

    def test_for_type_per_type_overrides_defaults(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config_for_type, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        config = {
            "_defaults": {"preamble": 5, "delay": 1.0},
            "review": {"verdicts": {"PASS": 1}, "preamble": 2},
        }
        set_fake_claude_config(tag, config)
        result = fake_claude_config_for_type("review", tag)
        assert result["preamble"] == 2   # per-type wins
        assert result["delay"] == 1.0    # from defaults

    def test_for_type_propagates_top_level_binary(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config_for_type, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        config = {
            "binary": "/custom/fake",
            "review": {"verdicts": {"PASS": 1}},
        }
        set_fake_claude_config(tag, config)
        result = fake_claude_config_for_type("review", tag)
        assert result["binary"] == "/custom/fake"

    # _all catch-all ("fake everything") mode

    def test_all_catches_absent_session_type(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config_for_type, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        config = {
            "_defaults": {"preamble": 4},
            "_all": {"delay": 0.2},
            "review": {"verdicts": {"PASS": 1}},
        }
        set_fake_claude_config(tag, config)
        # "impl" has no entry → falls back to _all (no-verdict catch-all)
        result = fake_claude_config_for_type("impl", tag)
        assert result is not None
        assert "verdicts" not in result        # no-verdict session
        assert result["delay"] == 0.2          # from _all
        assert result["preamble"] == 4         # from _defaults

    def test_all_catches_none_session_type(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config_for_type, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        set_fake_claude_config(tag, {"_all": {"preamble": 1}})
        result = fake_claude_config_for_type(None, tag)
        assert result is not None
        assert "verdicts" not in result

    def test_explicit_type_wins_over_all(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config_for_type, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        config = {
            "_all": {"delay": 9.0},
            "review": {"verdicts": {"PASS": 1}, "delay": 1.0},
        }
        set_fake_claude_config(tag, config)
        result = fake_claude_config_for_type("review", tag)
        assert result["verdicts"] == {"PASS": 1}   # explicit entry, not _all
        assert result["delay"] == 1.0

    def test_set_raises_on_verdicts_in_all(self, tmp_path, monkeypatch):
        from pm_core.paths import set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="_all"):
            set_fake_claude_config(tag, {"_all": {"verdicts": {"PASS": 1}}})


# ---------------------------------------------------------------------------
# Launcher fake-claude integration (_pick_fake_verdict, _fake_claude_args,
# find_claude, build_claude_shell_cmd)
# ---------------------------------------------------------------------------

class TestFakeClaudeLauncher:
    def test_pick_fake_verdict_respects_weights(self):
        from pm_core.claude_launcher import _pick_fake_verdict
        # With only one option, always picks that option.
        for _ in range(20):
            assert _pick_fake_verdict({"NEEDS_WORK": 1}) == "NEEDS_WORK"

    def test_pick_fake_verdict_samples_from_keys(self):
        from pm_core.claude_launcher import _pick_fake_verdict
        results = {_pick_fake_verdict({"PASS": 1, "NEEDS_WORK": 1}) for _ in range(100)}
        assert "PASS" in results
        assert "NEEDS_WORK" in results

    def test_fake_claude_args_includes_verdict(self):
        from pm_core.claude_launcher import _fake_claude_args
        args = _fake_claude_args({"verdicts": {"PASS": 1}})
        assert "--verdict" in args
        assert "PASS" in args

    def test_fake_claude_args_passes_preamble(self):
        from pm_core.claude_launcher import _fake_claude_args
        args = _fake_claude_args({"verdicts": {"PASS": 1}, "preamble": 7})
        assert "--preamble" in args
        idx = args.index("--preamble")
        assert args[idx + 1] == "7"

    def test_fake_claude_args_passes_delay(self):
        from pm_core.claude_launcher import _fake_claude_args
        args = _fake_claude_args({"verdicts": {"PASS": 1}, "delay": 2.5})
        assert "--delay" in args
        idx = args.index("--delay")
        assert args[idx + 1] == "2.5"

    def test_fake_claude_args_passes_body_lines(self):
        from pm_core.claude_launcher import _fake_claude_args
        args = _fake_claude_args({"verdicts": {"PASS": 1}, "body_lines": 10})
        assert "--body-lines" in args

    def test_fake_claude_args_no_verdicts_emits_none(self):
        """A config with no verdicts (no-verdict / _all catch-all) emits NONE."""
        from pm_core.claude_launcher import _fake_claude_args
        args = _fake_claude_args({"preamble": 2})
        idx = args.index("--verdict")
        assert args[idx + 1] == "NONE"

    def test_fake_claude_args_empty_verdicts_emits_none(self):
        from pm_core.claude_launcher import _fake_claude_args
        args = _fake_claude_args({"verdicts": {}})
        idx = args.index("--verdict")
        assert args[idx + 1] == "NONE"

    def test_fake_claude_args_passes_hold(self):
        from pm_core.claude_launcher import _fake_claude_args
        args = _fake_claude_args({"hold": 5})
        assert "--hold" in args
        idx = args.index("--hold")
        assert args[idx + 1] == "5"

    def test_find_claude_always_uses_shutil_which(self, monkeypatch):
        """find_claude no longer checks fake config — session_type is required."""
        from pm_core import claude_launcher
        monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/claude")
        assert claude_launcher.find_claude() == "/usr/local/bin/claude"

    def test_fake_config_for_type_returns_none_without_type(self, monkeypatch):
        from pm_core import claude_launcher
        monkeypatch.setattr("pm_core.paths.fake_claude_config_for_type",
                            lambda st, tag=None: None)
        assert claude_launcher._fake_claude_config_for_type(None) is None

    def test_build_shell_cmd_uses_fake_binary_with_session_type(self, monkeypatch):
        from pm_core import claude_launcher
        review_config = {"verdicts": {"PASS": 1}, "preamble": 3}
        monkeypatch.setattr("pm_core.paths.fake_claude_config_for_type",
                            lambda st, tag=None: review_config if st == "review" else None)
        cmd = claude_launcher.build_claude_shell_cmd(
            prompt="test prompt", session_type="review")
        assert str(claude_launcher._FAKE_CLAUDE_BIN) in cmd
        assert "--verdict" in cmd
        assert "PASS" in cmd

    def test_build_shell_cmd_no_fake_when_config_resolves_none(self, monkeypatch):
        """When config resolution returns None (no entry, no _all), use real claude."""
        from pm_core import claude_launcher
        monkeypatch.setattr("pm_core.paths.fake_claude_config_for_type",
                            lambda st, tag=None: None)
        monkeypatch.setattr("pm_core.paths.skip_permissions_enabled", lambda tag=None: False)
        cmd = claude_launcher.build_claude_shell_cmd(prompt="hi", session_type="impl")
        assert "--verdict" not in cmd

    def test_build_shell_cmd_no_session_type_uses_real_claude(self, monkeypatch):
        from pm_core import claude_launcher
        monkeypatch.setattr("pm_core.paths.fake_claude_config_for_type",
                            lambda st, tag=None: None)
        monkeypatch.setattr("pm_core.paths.skip_permissions_enabled", lambda tag=None: False)
        cmd = claude_launcher.build_claude_shell_cmd(prompt="hi")
        assert "--verdict" not in cmd

    def test_build_shell_cmd_no_verdict_config_emits_none(self, monkeypatch):
        """A no-verdict config (e.g. impl via _all catch-all) emits --verdict NONE."""
        from pm_core import claude_launcher
        no_verdict_config = {"preamble": 2, "hold": 3}
        monkeypatch.setattr("pm_core.paths.fake_claude_config_for_type",
                            lambda st, tag=None: no_verdict_config)
        cmd = claude_launcher.build_claude_shell_cmd(
            prompt="hi", session_type="impl")
        assert str(claude_launcher._FAKE_CLAUDE_BIN) in cmd
        assert "--verdict NONE" in cmd
        assert "--hold 3" in cmd

    def test_launch_claude_uses_fake_binary(self, monkeypatch, tmp_path):
        """launch_claude must invoke fake-claude binary, not the real claude."""
        from pm_core import claude_launcher
        fake_bin = "/custom/fake-claude"
        fc_config = {"verdicts": {"PASS": 1}, "binary": fake_bin}
        monkeypatch.setattr("pm_core.claude_launcher._fake_claude_config_for_type",
                            lambda st: fc_config if st == "review" else None)
        captured = []
        monkeypatch.setattr("subprocess.run",
                            lambda cmd, **kw: (captured.append(cmd), type("R", (), {"returncode": 0})())[-1])
        claude_launcher.launch_claude(
            "prompt", session_key="k", pm_root=tmp_path,
            session_type="review")
        assert captured, "subprocess.run was not called"
        assert captured[0][0] == fake_bin
        assert "--verdict" in captured[0]

    def test_launch_claude_works_without_real_claude_on_path(self, monkeypatch, tmp_path):
        """launch_claude must not require the real claude binary when fake is configured."""
        from pm_core import claude_launcher
        fake_bin = "/custom/fake-claude"
        fc_config = {"verdicts": {"PASS": 1}, "binary": fake_bin}
        monkeypatch.setattr("pm_core.claude_launcher._fake_claude_config_for_type",
                            lambda st: fc_config if st == "review" else None)
        monkeypatch.setattr("pm_core.claude_launcher.find_claude", lambda: None)
        captured = []
        monkeypatch.setattr("subprocess.run",
                            lambda cmd, **kw: (captured.append(cmd), type("R", (), {"returncode": 0})())[-1])
        # Must not raise FileNotFoundError even though find_claude() returns None
        claude_launcher.launch_claude(
            "prompt", session_key="k", pm_root=tmp_path,
            session_type="review")
        assert captured and captured[0][0] == fake_bin

    def test_launch_claude_print_uses_fake_binary(self, monkeypatch):
        """launch_claude_print must invoke fake-claude binary, not the real claude."""
        from pm_core import claude_launcher
        fake_bin = "/custom/fake-claude"
        fc_config = {"verdicts": {"NEEDS_WORK": 1}, "binary": fake_bin}
        monkeypatch.setattr("pm_core.claude_launcher._fake_claude_config_for_type",
                            lambda st: fc_config if st == "review" else None)
        captured = []

        class _FakeResult:
            returncode = 0
            stdout = "NEEDS_WORK\n"

        monkeypatch.setattr("subprocess.run",
                            lambda cmd, **kw: (captured.append(cmd), _FakeResult())[-1])
        claude_launcher.launch_claude_print("prompt", session_type="review")
        assert captured, "subprocess.run was not called"
        assert captured[0][0] == fake_bin
        assert "--verdict" in captured[0]

    def test_launch_claude_print_works_without_real_claude_on_path(self, monkeypatch):
        """launch_claude_print must not require real claude when fake is configured."""
        from pm_core import claude_launcher
        fake_bin = "/custom/fake-claude"
        fc_config = {"verdicts": {"PASS": 1}, "binary": fake_bin}
        monkeypatch.setattr("pm_core.claude_launcher._fake_claude_config_for_type",
                            lambda st: fc_config if st == "review" else None)
        monkeypatch.setattr("pm_core.claude_launcher.find_claude", lambda: None)
        captured = []

        class _FakeResult:
            returncode = 0
            stdout = "PASS\n"

        monkeypatch.setattr("subprocess.run",
                            lambda cmd, **kw: (captured.append(cmd), _FakeResult())[-1])
        result = claude_launcher.launch_claude_print("prompt", session_type="review")
        assert captured and captured[0][0] == fake_bin
        assert "PASS" in result

    def test_launch_claude_print_background_uses_fake_binary(self, monkeypatch):
        """launch_claude_print_background must invoke fake-claude binary."""
        import threading
        from pm_core import claude_launcher
        fake_bin = "/custom/fake-claude"
        fc_config = {"verdicts": {"PASS": 1}, "binary": fake_bin}
        monkeypatch.setattr("pm_core.claude_launcher._fake_claude_config_for_type",
                            lambda st: fc_config if st == "review" else None)
        captured = []

        class _FakeResult:
            returncode = 0
            stdout = "PASS\n"
            stderr = ""

        monkeypatch.setattr("subprocess.run",
                            lambda cmd, **kw: (captured.append(cmd), _FakeResult())[-1])
        done = threading.Event()
        claude_launcher.launch_claude_print_background(
            "prompt", session_type="review",
            callback=lambda *a: done.set())
        done.wait(timeout=5)
        assert captured, "subprocess.run was not called"
        assert captured[0][0] == fake_bin
        assert "--verdict" in captured[0]


# ---------------------------------------------------------------------------
# bin/fake-claude: --verdict optional + parse_known_args
# ---------------------------------------------------------------------------

class TestBinFakeClaudeOptionalVerdict:
    def test_no_verdict_defaults_to_pass(self):
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE), "--preamble", "0"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout

    def test_ignores_claude_flags(self):
        """Claude-specific flags passed by the launcher must be silently ignored."""
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE),
             "--verdict", "NEEDS_WORK",
             "--preamble", "0",
             "--dangerously-skip-permissions",
             "--model", "claude-opus-4-5",
             "--resume", "some-session-id",
             "some prompt text"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "NEEDS_WORK" in result.stdout

    def test_print_flag_ignored(self):
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE),
             "--verdict", "PASS", "--preamble", "0",
             "-p", "some prompt"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout


# ---------------------------------------------------------------------------
# Transcript + hook emission — the inputs production verdict detection reads
# ---------------------------------------------------------------------------

class TestTranscriptAndHook:
    """When a session_id is given the fake must produce a Claude-format JSONL
    transcript and an ``idle_prompt`` hook event, because the production
    poller (``loop_shared.poll_for_verdict``) is hook+JSONL driven and never
    scrapes pane content.
    """

    SID = "abcdef01-2345-6789-abcd-ef0123456789"

    def _run(self, tmp_path, monkeypatch, **kwargs):
        """Run the fake with HOME + cwd redirected into *tmp_path*."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.chdir(tmp_path)
        kwargs.setdefault("preamble", 2)
        kwargs.setdefault("hold", 0)  # emit hook once, don't block
        buf = StringIO()
        with patch("sys.stdout", buf):
            run_fake_claude(session_id=self.SID, **kwargs)
        return buf.getvalue()

    def _transcript_path(self, tmp_path):
        from pm_core.fake_claude import _claude_transcript_path
        return _claude_transcript_path(self.SID)

    def test_transcript_file_written(self, tmp_path, monkeypatch):
        self._run(tmp_path, monkeypatch, verdict="PASS")
        assert self._transcript_path(tmp_path).exists()

    def test_transcript_verdict_detectable(self, tmp_path, monkeypatch):
        """The written transcript must be readable by the real detector."""
        from pm_core.verdict_transcript import extract_verdict_from_transcript
        self._run(tmp_path, monkeypatch, verdict="NEEDS_WORK")
        verdict = extract_verdict_from_transcript(
            str(self._transcript_path(tmp_path)),
            ("PASS", "NEEDS_WORK", "INPUT_REQUIRED"))
        assert verdict == "NEEDS_WORK"

    def test_transcript_block_verdict_detectable(self, tmp_path, monkeypatch):
        from pm_core.verdict_transcript import extract_verdict_from_transcript
        self._run(tmp_path, monkeypatch, verdict="FLAGGED")
        verdict = extract_verdict_from_transcript(
            str(self._transcript_path(tmp_path)), ("VERIFIED", "FLAGGED_END"))
        assert verdict == "FLAGGED_END"

    def test_transcript_assistant_text_is_full_output(self, tmp_path, monkeypatch):
        """read_latest_assistant_text must return the fake's full stdout."""
        from pm_core.verdict_transcript import read_latest_assistant_text
        out = self._run(tmp_path, monkeypatch, verdict="PASS")
        text = read_latest_assistant_text(str(self._transcript_path(tmp_path)))
        assert text == out

    def test_transcript_markers_extractable(self, tmp_path, monkeypatch):
        """Block markers in the transcript survive for extract_between_markers."""
        from pm_core.verdict_transcript import read_latest_assistant_text
        from pm_core.loop_shared import extract_between_markers
        self._run(tmp_path, monkeypatch, verdict="REFINED_STEPS",
                  body="1. do a thing\n2. do another")
        text = read_latest_assistant_text(str(self._transcript_path(tmp_path)))
        body = extract_between_markers(
            text, "REFINED_STEPS_START", "REFINED_STEPS_END")
        assert body == "1. do a thing\n2. do another"

    def _hook_path(self, tmp_path):
        # Read the hook file directly: ``hook_events._HOOKS_BASE`` is captured
        # at import time from the real home, so it ignores a monkeypatched
        # ``Path.home`` (in production both processes see the real home and
        # agree).
        return tmp_path / ".pm" / "hooks" / f"{self.SID}.json"

    def test_idle_hook_event_written(self, tmp_path, monkeypatch):
        self._run(tmp_path, monkeypatch, verdict="PASS")
        hook = self._hook_path(tmp_path)
        assert hook.exists()
        ev = json.loads(hook.read_text())
        assert ev["event_type"] == "idle_prompt"
        assert ev["session_id"] == self.SID
        assert float(ev["timestamp"]) > 0

    def test_no_session_id_writes_no_transcript(self, tmp_path, monkeypatch):
        """Without a session_id the fake only writes stdout (CLI use)."""
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.chdir(tmp_path)
        buf = StringIO()
        with patch("sys.stdout", buf):
            run_fake_claude(verdict="PASS", preamble=1)  # no session_id
        assert not (tmp_path / ".claude").exists()
        assert not (tmp_path / ".pm" / "hooks").exists()

    def test_hold_refreshes_hook(self, tmp_path, monkeypatch):
        """While held open, the idle hook is re-emitted on a fresh timestamp."""
        from pm_core import fake_claude
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        monkeypatch.chdir(tmp_path)

        # Drive the clock deterministically — wall-clock resolution is too
        # coarse on some hosts to distinguish two back-to-back emissions.
        ticks = iter([100.0, 200.0])
        monkeypatch.setattr(fake_claude.time, "time", lambda: next(ticks))

        hook = self._hook_path(tmp_path)
        fake_claude._emit_idle_hook(self.SID)
        first = json.loads(hook.read_text())["timestamp"]
        fake_claude._emit_idle_hook(self.SID)
        second = json.loads(hook.read_text())["timestamp"]
        assert first == 100.0
        assert second == 200.0

    def test_no_verdict_session_with_id_writes_transcript(self, tmp_path, monkeypatch):
        """No-verdict sessions with a session_id still produce a transcript."""
        self._run(tmp_path, monkeypatch, verdict="NONE")
        assert self._transcript_path(tmp_path).exists()


class TestTranscriptHookCLI:
    """End-to-end: the bin/fake-claude executable writes transcript + hook."""

    SID = "11112222-3333-4444-5555-666677778888"

    def test_executable_writes_transcript_and_hook(self, tmp_path):
        import os
        env = {**os.environ, "HOME": str(tmp_path)}
        result = subprocess.run(
            [sys.executable, str(BIN_FAKE_CLAUDE),
             "--verdict", "PASS", "--preamble", "1",
             "--session-id", self.SID, "--hold", "0"],
            capture_output=True, text=True, timeout=10,
            cwd=str(tmp_path), env=env,
        )
        assert result.returncode == 0
        assert "PASS" in result.stdout
        mangled = str(tmp_path).replace("/", "-").replace(".", "-")
        transcript = (tmp_path / ".claude" / "projects" / mangled
                      / f"{self.SID}.jsonl")
        assert transcript.exists()
        assert '"type": "assistant"' in transcript.read_text()
        hook = tmp_path / ".pm" / "hooks" / f"{self.SID}.json"
        assert hook.exists()


class TestFakeArgsSessionId:
    def test_fake_claude_args_includes_session_id(self):
        from pm_core.claude_launcher import _fake_claude_args
        args = _fake_claude_args({"verdicts": {"PASS": 1}}, session_id="sid-123")
        assert "--session-id" in args
        assert args[args.index("--session-id") + 1] == "sid-123"

    def test_fake_claude_args_omits_session_id_when_none(self):
        from pm_core.claude_launcher import _fake_claude_args
        args = _fake_claude_args({"verdicts": {"PASS": 1}})
        assert "--session-id" not in args

    def test_build_shell_cmd_threads_session_id(self, monkeypatch):
        from pm_core import claude_launcher
        cfg = {"verdicts": {"PASS": 1}}
        monkeypatch.setattr("pm_core.paths.fake_claude_config_for_type",
                            lambda st, tag=None: cfg if st == "review" else None)
        cmd = claude_launcher.build_claude_shell_cmd(
            prompt="p", session_type="review", session_id="sid-xyz")
        assert "--session-id sid-xyz" in cmd


# ---------------------------------------------------------------------------
# Scripted verdict sequences (multi-iteration loop scenarios)
# ---------------------------------------------------------------------------

class TestScriptedVerdictValidation:
    def test_list_form_accepted(self):
        assert validate_session_verdicts("review", ["NEEDS_WORK", "PASS"]) == []

    def test_list_form_with_override_dicts(self):
        seq = [{"verdict": "FLAGGED", "body": "Step 3"}, {"verdict": "VERIFIED"}]
        assert validate_session_verdicts("qa_verification", seq) == []

    def test_list_rejects_invalid_verdict(self):
        errors = validate_session_verdicts("review", ["PASS", "VERIFIED"])
        assert errors and "VERIFIED" in errors[0]

    def test_list_rejects_malformed_entry(self):
        errors = validate_session_verdicts("review", ["PASS", 42])
        assert errors and "malformed" in errors[0]

    def test_list_rejects_entry_missing_verdict_key(self):
        errors = validate_session_verdicts("review", [{"body": "x"}])
        assert errors and "malformed" in errors[0]

    def test_sequence_dict_form_accepted(self):
        verdicts = {"sequence": ["NEEDS_WORK", "PASS"], "wrap": True}
        assert validate_session_verdicts("review", verdicts) == []

    def test_list_rejected_for_no_verdict_type(self):
        errors = validate_session_verdicts("impl", ["PASS"])
        assert errors and "never emits a verdict" in errors[0]

    def test_empty_list_ok_for_no_verdict_type(self):
        assert validate_session_verdicts("impl", []) == []


class TestSetFakeClaudeConfigScripted:
    def _setup(self, tmp_path, monkeypatch, tag="scripted-tag"):
        monkeypatch.setattr("pm_core.paths.sessions_dir", lambda: tmp_path)
        monkeypatch.setattr("pm_core.paths.get_session_tag", lambda **kw: tag)
        return tag

    def test_list_form_writes(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        cfg = {"review": {"verdicts": ["NEEDS_WORK", "PASS"]}}
        set_fake_claude_config(tag, cfg)
        assert fake_claude_config(tag) == cfg

    def test_list_form_invalid_verdict_raises(self, tmp_path, monkeypatch):
        from pm_core.paths import set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="VERIFIED"):
            set_fake_claude_config(tag, {"review": {"verdicts": ["VERIFIED"]}})

    def test_sequence_dict_form_writes(self, tmp_path, monkeypatch):
        from pm_core.paths import fake_claude_config, set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        cfg = {"qa_verification": {"verdicts": {
            "sequence": [{"verdict": "FLAGGED", "body": "X"}, {"verdict": "VERIFIED"}],
            "wrap": True,
        }}}
        set_fake_claude_config(tag, cfg)
        assert fake_claude_config(tag) == cfg


class TestScriptedCursorAdvance:
    def _setup(self, tmp_path, monkeypatch, tag="cursor-tag"):
        monkeypatch.setattr("pm_core.paths.sessions_dir", lambda: tmp_path)
        monkeypatch.setattr("pm_core.paths.get_session_tag", lambda **kw: tag)
        return tag

    def test_clamp_to_last_advances_and_clamps(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _advance_scripted_cursor
        tag = self._setup(tmp_path, monkeypatch)
        # 3-entry sequence, clamp (wrap=False)
        slots = [_advance_scripted_cursor(tag, "review", 3, False) for _ in range(5)]
        assert slots == [0, 1, 2, 2, 2]

    def test_wrap_cycles(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _advance_scripted_cursor
        tag = self._setup(tmp_path, monkeypatch)
        slots = [_advance_scripted_cursor(tag, "review", 3, True) for _ in range(5)]
        assert slots == [0, 1, 2, 0, 1]

    def test_independent_per_session_type(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _advance_scripted_cursor
        tag = self._setup(tmp_path, monkeypatch)
        a = _advance_scripted_cursor(tag, "review", 2, False)
        b = _advance_scripted_cursor(tag, "qa_verification", 2, False)
        assert a == 0 and b == 0
        a2 = _advance_scripted_cursor(tag, "review", 2, False)
        assert a2 == 1  # review advanced; qa_verification untouched

    def test_state_file_written(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _advance_scripted_cursor
        tag = self._setup(tmp_path, monkeypatch)
        _advance_scripted_cursor(tag, "review", 3, False)
        state = json.loads((tmp_path / tag / "fake-claude.state").read_text())
        assert state == {"review": 1}

    def test_single_entry_sequence(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _advance_scripted_cursor
        tag = self._setup(tmp_path, monkeypatch)
        slots = [_advance_scripted_cursor(tag, "review", 1, False) for _ in range(3)]
        assert slots == [0, 0, 0]


class TestFakeClaudeArgsScripted:
    def _setup(self, tmp_path, monkeypatch, tag="scripted-args-tag"):
        monkeypatch.setattr("pm_core.paths.sessions_dir", lambda: tmp_path)
        monkeypatch.setattr("pm_core.paths.get_session_tag", lambda **kw: tag)
        return tag

    def test_list_form_progresses_through_sequence(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _fake_claude_args
        tag = self._setup(tmp_path, monkeypatch)
        cfg = {"verdicts": ["NEEDS_WORK", "PASS"]}
        v1 = _fake_claude_args(cfg, session_type="review", session_tag=tag)
        v2 = _fake_claude_args(cfg, session_type="review", session_tag=tag)
        v3 = _fake_claude_args(cfg, session_type="review", session_tag=tag)
        assert v1[v1.index("--verdict") + 1] == "NEEDS_WORK"
        assert v2[v2.index("--verdict") + 1] == "PASS"
        # Clamp-to-last: a third invocation still emits PASS, never NONE.
        assert v3[v3.index("--verdict") + 1] == "PASS"

    def test_entry_overrides_layer_over_base(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _fake_claude_args
        tag = self._setup(tmp_path, monkeypatch)
        cfg = {
            "preamble": 5,
            "verdicts": [{"verdict": "FLAGGED", "body": "Step 3: FAILED", "preamble": 1},
                         {"verdict": "VERIFIED"}],
        }
        v1 = _fake_claude_args(cfg, session_type="qa_verification", session_tag=tag)
        assert v1[v1.index("--verdict") + 1] == "FLAGGED"
        assert v1[v1.index("--body") + 1] == "Step 3: FAILED"
        # Per-entry preamble (1) wins over base preamble (5).
        assert v1[v1.index("--preamble") + 1] == "1"
        v2 = _fake_claude_args(cfg, session_type="qa_verification", session_tag=tag)
        assert v2[v2.index("--verdict") + 1] == "VERIFIED"
        # No body override on entry 2 — flag absent.
        assert "--body" not in v2
        # Base preamble restored.
        assert v2[v2.index("--preamble") + 1] == "5"

    def test_sequence_dict_with_wrap(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _fake_claude_args
        tag = self._setup(tmp_path, monkeypatch)
        cfg = {"verdicts": {"sequence": ["NEEDS_WORK", "PASS"], "wrap": True}}
        verdicts = []
        for _ in range(5):
            a = _fake_claude_args(cfg, session_type="review", session_tag=tag)
            verdicts.append(a[a.index("--verdict") + 1])
        assert verdicts == ["NEEDS_WORK", "PASS", "NEEDS_WORK", "PASS", "NEEDS_WORK"]

    def test_weighted_dict_form_still_works(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _fake_claude_args
        tag = self._setup(tmp_path, monkeypatch)
        cfg = {"verdicts": {"PASS": 1}}
        a = _fake_claude_args(cfg, session_type="review", session_tag=tag)
        assert a[a.index("--verdict") + 1] == "PASS"
        # No state file should appear for weighted-random configs.
        assert not (tmp_path / tag / "fake-claude.state").exists()

    def test_empty_sequence_emits_none(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _fake_claude_args
        tag = self._setup(tmp_path, monkeypatch)
        a = _fake_claude_args({"verdicts": []}, session_type="review", session_tag=tag)
        assert a[a.index("--verdict") + 1] == "NONE"

    def test_session_type_none_falls_back_to_slot_zero(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import _fake_claude_args
        self._setup(tmp_path, monkeypatch)
        cfg = {"verdicts": ["NEEDS_WORK", "PASS"]}
        # Without session_type the cursor cannot key itself — always slot 0.
        for _ in range(3):
            a = _fake_claude_args(cfg)
            assert a[a.index("--verdict") + 1] == "NEEDS_WORK"


class TestPeekFakeVerdicts:
    def _setup(self, tmp_path, monkeypatch, tag="peek-tag"):
        monkeypatch.setattr("pm_core.paths.sessions_dir", lambda: tmp_path)
        monkeypatch.setattr("pm_core.paths.get_session_tag", lambda **kw: tag)
        return tag

    def test_peek_reports_scripted_and_weighted(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import peek_fake_verdicts, _advance_scripted_cursor
        from pm_core.paths import set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        set_fake_claude_config(tag, {
            "review": {"verdicts": ["NEEDS_WORK", "PASS"]},
            "qa_verification": {"verdicts": {"VERIFIED": 1}},
            "_all": {},
        })
        peek = peek_fake_verdicts(tag)
        assert peek["review"] == "NEEDS_WORK"
        assert peek["qa_verification"] == "<random>"
        # Advance the review cursor; peek should reflect the new position.
        _advance_scripted_cursor(tag, "review", 2, False)
        assert peek_fake_verdicts(tag)["review"] == "PASS"

    def test_peek_does_not_advance_cursor(self, tmp_path, monkeypatch):
        from pm_core.claude_launcher import peek_fake_verdicts
        from pm_core.paths import set_fake_claude_config
        tag = self._setup(tmp_path, monkeypatch)
        set_fake_claude_config(tag, {"review": {"verdicts": ["NEEDS_WORK", "PASS"]}})
        for _ in range(3):
            assert peek_fake_verdicts(tag)["review"] == "NEEDS_WORK"
        assert not (tmp_path / tag / "fake-claude.state").exists()
