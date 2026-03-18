"""Tests for pm_core.fake_claude and the pm fake-claude CLI command."""

import subprocess
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import call, patch

import pytest

from pm_core.fake_claude import (
    ALL_VERDICTS,
    SINGLE_LINE_VERDICTS,
    BLOCK_VERDICTS,
    run_fake_claude,
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
        ("PASS_WITH_SUGGESTIONS", "pass_with_suggestions.txt"),
        ("NEEDS_WORK", "needs_work.txt"),
        ("INPUT_REQUIRED", "input_required.txt"),
        ("VERIFIED", "verified.txt"),
    ])
    def test_single_line_fixture_contains_verdict(self, verdict, filename):
        fixture = FIXTURES_DIR / filename
        content = fixture.read_text()
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        assert verdict in lines, f"{verdict!r} not found as standalone line in {filename}"

    @pytest.mark.parametrize("block_name,filename", [
        ("FLAGGED", "flagged.txt"),
        ("REFINED_STEPS", "refined_steps.txt"),
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

    def test_pass_detected_by_extract_verdict(self):
        from pm_core.loop_shared import extract_verdict_from_content
        out = self._capture(verdict="PASS", preamble=3)
        result = extract_verdict_from_content(
            out,
            verdicts=("PASS", "PASS_WITH_SUGGESTIONS", "NEEDS_WORK", "INPUT_REQUIRED"),
            keywords=("PASS_WITH_SUGGESTIONS", "INPUT_REQUIRED", "NEEDS_WORK", "PASS"),
        )
        assert result == "PASS"

    def test_needs_work_detected(self):
        from pm_core.loop_shared import extract_verdict_from_content
        out = self._capture(verdict="NEEDS_WORK", preamble=3)
        result = extract_verdict_from_content(
            out,
            verdicts=("PASS", "PASS_WITH_SUGGESTIONS", "NEEDS_WORK", "INPUT_REQUIRED"),
            keywords=("PASS_WITH_SUGGESTIONS", "INPUT_REQUIRED", "NEEDS_WORK", "PASS"),
        )
        assert result == "NEEDS_WORK"

    def test_input_required_detected(self):
        from pm_core.loop_shared import extract_verdict_from_content
        out = self._capture(verdict="INPUT_REQUIRED", preamble=3)
        result = extract_verdict_from_content(
            out,
            verdicts=("PASS", "PASS_WITH_SUGGESTIONS", "NEEDS_WORK", "INPUT_REQUIRED"),
            keywords=("PASS_WITH_SUGGESTIONS", "INPUT_REQUIRED", "NEEDS_WORK", "PASS"),
        )
        assert result == "INPUT_REQUIRED"

    def test_verified_detected(self):
        from pm_core.loop_shared import extract_verdict_from_content
        out = self._capture(verdict="VERIFIED", preamble=3)
        result = extract_verdict_from_content(
            out,
            verdicts=("VERIFIED", "FLAGGED_END"),
            keywords=("VERIFIED", "FLAGGED_START", "FLAGGED_END"),
        )
        assert result == "VERIFIED"

    def test_flagged_end_detected(self):
        from pm_core.loop_shared import extract_verdict_from_content
        out = self._capture(verdict="FLAGGED", preamble=3)
        result = extract_verdict_from_content(
            out,
            verdicts=("VERIFIED", "FLAGGED_END"),
            keywords=("VERIFIED", "FLAGGED_START", "FLAGGED_END"),
        )
        assert result == "FLAGGED_END"

    def test_refined_steps_end_detected(self):
        from pm_core.loop_shared import extract_verdict_from_content
        out = self._capture(verdict="REFINED_STEPS", preamble=3)
        result = extract_verdict_from_content(
            out,
            verdicts=("REFINED_STEPS_END",),
            keywords=("REFINED_STEPS_START", "REFINED_STEPS_END"),
        )
        assert result == "REFINED_STEPS_END"


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
