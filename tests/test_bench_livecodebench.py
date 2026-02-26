"""Tests for LiveCodeBench exercise loader and stdin/stdout executor."""

import json
from pathlib import Path

import pytest

from pm_core.bench.exercises import Exercise
from pm_core.bench.executor import ScoreResult, execute_stdin_stdout
from pm_core.bench.exercises_livecodebench import (
    _normalize_difficulty,
    _parse_problem,
    _parse_test_cases,
)


# ---------------------------------------------------------------------------
# _parse_test_cases
# ---------------------------------------------------------------------------

class TestParseTestCases:
    def test_plain_json(self):
        cases = [{"input": "1 2\n", "output": "3\n"}]
        result = _parse_test_cases(json.dumps(cases))
        assert len(result) == 1
        assert result[0]["input"] == "1 2\n"
        assert result[0]["output"] == "3\n"

    def test_empty_string(self):
        assert _parse_test_cases("") == []

    def test_invalid_json(self):
        assert _parse_test_cases("not json at all") == []

    def test_non_list_json(self):
        assert _parse_test_cases('"just a string"') == []

    def test_multiple_cases(self):
        cases = [
            {"input": "1\n", "output": "1\n"},
            {"input": "2\n", "output": "4\n"},
            {"input": "3\n", "output": "9\n"},
        ]
        result = _parse_test_cases(json.dumps(cases))
        assert len(result) == 3


# ---------------------------------------------------------------------------
# _normalize_difficulty
# ---------------------------------------------------------------------------

class TestNormalizeDifficulty:
    def test_leetcode_difficulties(self):
        assert _normalize_difficulty("Easy") == "easy"
        assert _normalize_difficulty("Medium") == "medium"
        assert _normalize_difficulty("Hard") == "hard"

    def test_case_insensitive(self):
        assert _normalize_difficulty("EASY") == "easy"
        assert _normalize_difficulty("HARD") == "hard"

    def test_atcoder_labels(self):
        assert _normalize_difficulty("A") == "easy"
        assert _normalize_difficulty("B") == "easy"
        assert _normalize_difficulty("C") == "medium"
        assert _normalize_difficulty("D") == "medium"
        assert _normalize_difficulty("E") == "hard"

    def test_unknown_defaults_to_medium(self):
        assert _normalize_difficulty("unknown") == "medium"
        assert _normalize_difficulty("") == "medium"


# ---------------------------------------------------------------------------
# _parse_problem
# ---------------------------------------------------------------------------

class TestParseProblem:
    def _make_row(self, **overrides):
        base = {
            "question_id": "q123",
            "question_title": "Two Sum",
            "question_content": "Given two numbers, return their sum.",
            "starter_code": "",
            "difficulty": "Easy",
            "platform": "LeetCode",
            "public_test_cases": json.dumps([
                {"input": "1 2\n", "output": "3\n"},
            ]),
            "private_test_cases": json.dumps([
                {"input": "3 4\n", "output": "7\n"},
                {"input": "0 0\n", "output": "0\n"},
            ]),
            "metadata": "{}",
        }
        base.update(overrides)
        return base

    def test_basic_parsing(self):
        ex = _parse_problem(self._make_row())
        assert ex is not None
        assert ex.slug == "two-sum"
        assert ex.language == "python"
        assert ex.source == "livecodebench"
        assert ex.difficulty == "easy"
        assert ex.platform == "leetcode"
        assert "Given two numbers" in ex.description

    def test_test_cases_merged(self):
        ex = _parse_problem(self._make_row())
        tests = json.loads(ex.reference_tests["_stdin_stdout_tests.json"])
        # 1 public + 2 private = 3 total
        assert len(tests) == 3

    def test_empty_content_returns_none(self):
        assert _parse_problem(self._make_row(question_content="")) is None
        assert _parse_problem(self._make_row(question_content="   ")) is None

    def test_no_test_cases_returns_none(self):
        row = self._make_row(public_test_cases="", private_test_cases="")
        assert _parse_problem(row) is None

    def test_starter_code_stored(self):
        starter = "def solve():\n    pass\n"
        ex = _parse_problem(self._make_row(starter_code=starter))
        assert "solution.py" in ex.starter_code
        assert ex.starter_code["solution.py"] == starter

    def test_empty_starter_code(self):
        ex = _parse_problem(self._make_row(starter_code=""))
        assert ex.starter_code == {}

    def test_slug_sanitization(self):
        ex = _parse_problem(self._make_row(question_title="Hello, World! #2"))
        assert ex.slug == "hello-world-2"


# ---------------------------------------------------------------------------
# execute_stdin_stdout
# ---------------------------------------------------------------------------

def _make_stdin_exercise(test_cases, *, starter_code=None):
    """Create a minimal Exercise with stdin/stdout test cases."""
    return Exercise(
        language="python",
        slug="test-problem",
        description="Test problem",
        starter_code={"solution.py": starter_code} if starter_code else {},
        reference_tests={
            "_stdin_stdout_tests.json": json.dumps(test_cases),
        },
        path=Path("/tmp"),
        source="livecodebench",
        difficulty="easy",
    )


class TestExecuteStdinStdout:
    def test_correct_solution_full_score(self):
        """A program that correctly echoes input + 1 should get full marks."""
        cases = [
            {"input": "5\n", "output": "6\n"},
            {"input": "0\n", "output": "1\n"},
            {"input": "99\n", "output": "100\n"},
        ]
        ex = _make_stdin_exercise(cases)
        code = "n = int(input())\nprint(n + 1)\n"
        result = execute_stdin_stdout(ex, code)
        assert result.score == 1.0
        assert result.passed == 3
        assert result.total == 3
        assert result.error is None

    def test_wrong_solution_zero_score(self):
        cases = [
            {"input": "5\n", "output": "6\n"},
            {"input": "0\n", "output": "1\n"},
        ]
        ex = _make_stdin_exercise(cases)
        code = "print('wrong')\n"
        result = execute_stdin_stdout(ex, code)
        assert result.score == 0.0
        assert result.passed == 0

    def test_partial_score(self):
        """First case correct, second wrong."""
        cases = [
            {"input": "hello\n", "output": "hello\n"},
            {"input": "world\n", "output": "WORLD\n"},
        ]
        ex = _make_stdin_exercise(cases)
        # Just echoes input — correct for first, wrong for second
        code = "print(input())\n"
        result = execute_stdin_stdout(ex, code)
        assert result.passed == 1
        assert result.total == 2
        assert result.score == pytest.approx(0.5)

    def test_multiline_output(self):
        """Programs producing multiple lines of output."""
        cases = [
            {"input": "3\n", "output": "1\n2\n3\n"},
        ]
        ex = _make_stdin_exercise(cases)
        code = "n = int(input())\nfor i in range(1, n+1):\n    print(i)\n"
        result = execute_stdin_stdout(ex, code)
        assert result.score == 1.0

    def test_trailing_whitespace_ignored(self):
        """Trailing spaces/newlines shouldn't cause failures."""
        cases = [
            {"input": "hi\n", "output": "hi\n"},
        ]
        ex = _make_stdin_exercise(cases)
        # Output has trailing spaces
        code = "print(input() + '  ')\n"
        result = execute_stdin_stdout(ex, code)
        # _normalize_output strips trailing whitespace per line
        assert result.score == 1.0

    def test_syntax_error_handled(self):
        cases = [{"input": "1\n", "output": "1\n"}]
        ex = _make_stdin_exercise(cases)
        code = "def broken(\n"
        result = execute_stdin_stdout(ex, code)
        assert result.score == 0.0
        assert result.passed == 0

    def test_empty_test_cases(self):
        ex = Exercise(
            language="python",
            slug="empty",
            description="empty",
            starter_code={},
            reference_tests={"_stdin_stdout_tests.json": "[]"},
            path=Path("/tmp"),
            source="livecodebench",
        )
        result = execute_stdin_stdout(ex, "pass\n")
        assert result.error == "Empty test case list"

    def test_no_test_key(self):
        ex = Exercise(
            language="python",
            slug="no-tests",
            description="no tests",
            starter_code={},
            reference_tests={},
            path=Path("/tmp"),
            source="livecodebench",
        )
        result = execute_stdin_stdout(ex, "pass\n")
        assert result.error == "No stdin/stdout test cases found"

    def test_timeout_handling(self):
        cases = [{"input": "1\n", "output": "1\n"}]
        ex = _make_stdin_exercise(cases)
        code = "import time\ntime.sleep(100)\n"
        result = execute_stdin_stdout(ex, code, timeout=1)
        assert result.passed == 0
        assert result.timed_out is True

    def test_two_sum_competitive_style(self):
        """Classic competitive programming problem: read two ints, print sum."""
        cases = [
            {"input": "1 2\n", "output": "3\n"},
            {"input": "10 20\n", "output": "30\n"},
            {"input": "-5 5\n", "output": "0\n"},
        ]
        ex = _make_stdin_exercise(cases)
        code = "a, b = map(int, input().split())\nprint(a + b)\n"
        result = execute_stdin_stdout(ex, code)
        assert result.score == 1.0
        assert result.passed == 3
