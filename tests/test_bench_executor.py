"""Tests for bench executor — test output parsing and scoring."""

import pytest

from pm_core.bench.executor import (
    ScoreResult,
    _count_tests_from_output,
    _parse_counts,
    _parse_test_output,
)


# ---------------------------------------------------------------------------
# _count_tests_from_output — all-passing output
# ---------------------------------------------------------------------------

class TestCountTestsFromOutput:
    def test_pytest_passed(self):
        output = "===== 5 passed in 0.03s ====="
        assert _count_tests_from_output(output) == 5

    def test_go_pass_lines(self):
        output = (
            "--- PASS: TestLeap (0.00s)\n"
            "--- PASS: TestLeap2 (0.00s)\n"
            "PASS\n"
            "ok  \texercism/leap\t0.001s\n"
        )
        assert _count_tests_from_output(output) == 2

    def test_cargo_test_ok(self):
        output = (
            "running 5 tests\n"
            "test test_1 ... ok\n"
            "test test_2 ... ok\n"
            "test test_3 ... ok\n"
            "test test_4 ... ok\n"
            "test test_5 ... ok\n"
            "\n"
            "test result: ok. 5 passed; 0 failed; 0 ignored; 0 measured\n"
        )
        assert _count_tests_from_output(output) == 5

    def test_jest_all_passed(self):
        output = (
            "PASS ./hello.spec.js\n"
            "Tests:        3 passed, 3 total\n"
            "Time:         0.5s\n"
        )
        assert _count_tests_from_output(output) == 3

    def test_unknown_output_defaults_to_one(self):
        assert _count_tests_from_output("all good") == 1

    def test_empty_output_defaults_to_one(self):
        assert _count_tests_from_output("") == 1


# ---------------------------------------------------------------------------
# _parse_counts — failing output
# ---------------------------------------------------------------------------

class TestParseCounts:
    def test_pytest_mixed(self):
        output = "===== 2 passed, 3 failed in 0.05s ====="
        passed, total = _parse_counts(output)
        assert passed == 2
        assert total == 5

    def test_pytest_with_errors(self):
        output = "===== 1 passed, 2 failed, 1 error in 0.05s ====="
        passed, total = _parse_counts(output)
        assert passed == 1
        assert total == 4  # 1 passed + 2 failed + 1 error

    def test_pytest_all_failed(self):
        output = "===== 4 failed in 0.02s ====="
        passed, total = _parse_counts(output)
        assert passed == 0
        assert total == 4

    def test_go_mixed(self):
        output = (
            "--- PASS: TestA (0.00s)\n"
            "--- PASS: TestB (0.00s)\n"
            "--- FAIL: TestC (0.00s)\n"
            "FAIL\n"
        )
        passed, total = _parse_counts(output)
        assert passed == 2
        assert total == 3

    def test_cargo_test_failed(self):
        output = (
            "running 3 tests\n"
            "test test_1 ... ok\n"
            "test test_2 ... ok\n"
            "test test_3 ... FAILED\n"
            "\n"
            "test result: FAILED. 2 passed; 1 failed; 0 ignored\n"
        )
        passed, total = _parse_counts(output)
        assert passed == 2
        assert total == 3

    def test_jest_mixed(self):
        output = (
            "FAIL ./hello.spec.js\n"
            "Tests:        2 failed, 3 passed, 5 total\n"
        )
        passed, total = _parse_counts(output)
        assert passed == 3
        assert total == 5

    def test_jest_no_failed_prefix(self):
        # jest sometimes omits the failed count in the summary
        output = "Tests:        4 passed, 4 total\n"
        passed, total = _parse_counts(output)
        assert passed == 4
        assert total == 4

    def test_compilation_error_returns_zero(self):
        output = "error[E0433]: failed to resolve: use of undeclared crate"
        passed, total = _parse_counts(output)
        assert passed == 0
        assert total == 0

    def test_empty_output_returns_zero(self):
        passed, total = _parse_counts("")
        assert passed == 0
        assert total == 0


# ---------------------------------------------------------------------------
# _parse_test_output — full parsing pipeline
# ---------------------------------------------------------------------------

class TestParseTestOutput:
    def test_all_pass_returncode_zero(self):
        output = "===== 3 passed in 0.01s ====="
        result = _parse_test_output(output, returncode=0)
        assert result.passed == 3
        assert result.total == 3
        assert result.score == 1.0
        assert result.error is None

    def test_partial_failure(self):
        output = "===== 2 passed, 1 failed in 0.03s ====="
        result = _parse_test_output(output, returncode=1)
        assert result.passed == 2
        assert result.total == 3
        assert result.score == pytest.approx(2 / 3)
        assert result.error is None

    def test_compilation_error_sets_error_field(self):
        output = "SyntaxError: invalid syntax"
        result = _parse_test_output(output, returncode=1)
        assert result.passed == 0
        assert result.total == 1  # max(0, 1)
        assert result.score == 0.0
        assert result.error == "compilation_or_parse_error"

    def test_raw_output_preserved(self):
        output = "some test output here"
        result = _parse_test_output(output, returncode=0)
        assert result.raw_output == output


# ---------------------------------------------------------------------------
# ScoreResult defaults
# ---------------------------------------------------------------------------

class TestScoreResult:
    def test_defaults(self):
        r = ScoreResult()
        assert r.passed == 0
        assert r.total == 0
        assert r.score == 0.0
        assert r.raw_output == ""
        assert r.error is None
        assert r.timed_out is False
