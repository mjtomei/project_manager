"""Tests for pm_core.bench.exercises_evalplus — EvalPlus exercise loading."""

import json
from pathlib import Path

import pytest

from pm_core.bench.exercises_evalplus import (
    _extract_entry_point,
    _parse_evalplus_record,
    _slug_to_module,
    _strip_bare_check_call,
    _task_id_to_slug,
    _transform_test_code,
    load_evalplus_exercises,
)


# ---------------------------------------------------------------------------
# Slug / module helpers
# ---------------------------------------------------------------------------

class TestTaskIdToSlug:
    def test_humaneval_format(self):
        assert _task_id_to_slug("HumanEval/0") == "humaneval-0"
        assert _task_id_to_slug("HumanEval/163") == "humaneval-163"

    def test_mbpp_int_format(self):
        assert _task_id_to_slug("2") == "mbpp-2"
        assert _task_id_to_slug("500") == "mbpp-500"


class TestSlugToModule:
    def test_replaces_hyphens(self):
        assert _slug_to_module("humaneval-0") == "humaneval_0"
        assert _slug_to_module("mbpp-123") == "mbpp_123"

    def test_no_hyphens(self):
        assert _slug_to_module("simple") == "simple"


# ---------------------------------------------------------------------------
# Entry point extraction
# ---------------------------------------------------------------------------

class TestExtractEntryPoint:
    def test_simple_function(self):
        code = "def similar_elements(test_tup1, test_tup2):\n  return tuple(set(test_tup1))\n"
        assert _extract_entry_point(code) == "similar_elements"

    def test_with_imports(self):
        code = "import math\n\ndef compute(x):\n    return math.sqrt(x)\n"
        assert _extract_entry_point(code) == "compute"

    def test_no_function(self):
        assert _extract_entry_point("x = 42") is None

    def test_empty(self):
        assert _extract_entry_point("") is None


# ---------------------------------------------------------------------------
# Test code transformation
# ---------------------------------------------------------------------------

# Minimal HumanEval+-style test (uses `candidate` variable).
_HE_STYLE_TEST = """\
import numpy as np

def is_floats(x) -> bool:
    return isinstance(x, float)

def assertion(out, exp, atol):
    assert out == exp

inputs = [[[1.0, 2.0], 0.5], [[1.0, 2.0], 0.01]]
results = [True, False]
for i, (inp, exp) in enumerate(zip(inputs, results)):
    assertion(candidate(*inp), exp, 0)
"""

# Minimal MBPP+-style test (calls function by name).
_MBPP_STYLE_TEST = """\
import numpy as np

def is_floats(x) -> bool:
    return isinstance(x, float)

def assertion(out, exp, atol):
    assert out == exp

inputs = [[(3, 4, 5), (5, 7, 4)]]
results = [(4, 5)]
for i, (inp, exp) in enumerate(zip(inputs, results)):
    assertion(similar_elements(*inp), exp, 0)
"""

# Old-style check(candidate) test.
_CHECK_STYLE_TEST = """\
METADATA = {'author': 'jt'}

def check(candidate):
    assert candidate(1) == 2
    assert candidate(3) == 4

check(double)
"""


class TestTransformTestCode:
    def test_humaneval_style_has_import(self):
        result = _transform_test_code(_HE_STYLE_TEST, "has_close", "humaneval_0")
        assert "from humaneval_0 import *" in result

    def test_humaneval_style_has_candidate_assignment(self):
        result = _transform_test_code(_HE_STYLE_TEST, "has_close", "humaneval_0")
        assert "candidate = has_close" in result

    def test_humaneval_style_has_test_function(self):
        result = _transform_test_code(_HE_STYLE_TEST, "has_close", "humaneval_0")
        assert "def test_check():" in result

    def test_humaneval_style_loop_is_indented(self):
        result = _transform_test_code(_HE_STYLE_TEST, "has_close", "humaneval_0")
        # The for loop should be inside test_check, hence indented.
        assert "    for i, (inp, exp)" in result

    def test_humaneval_style_helpers_at_module_level(self):
        result = _transform_test_code(_HE_STYLE_TEST, "has_close", "humaneval_0")
        # is_floats and assertion should NOT be indented inside test_check.
        assert "def is_floats" in result
        assert "def assertion" in result

    def test_mbpp_style_preserves_function_call(self):
        result = _transform_test_code(_MBPP_STYLE_TEST, "similar_elements", "mbpp_2")
        assert "from mbpp_2 import *" in result
        assert "similar_elements(*inp)" in result

    def test_check_style_fallback(self):
        result = _transform_test_code(_CHECK_STYLE_TEST, "double", "test_mod")
        assert "from test_mod import *" in result
        assert "def test_check():" in result
        assert "check(double)" in result
        # The bare check(double) call at the end should be removed from setup.
        lines_before_test = result.split("def test_check():")[0]
        # Should not have a bare check(double) outside the test function.
        assert "check(double)" not in lines_before_test


# ---------------------------------------------------------------------------
# Strip bare check call
# ---------------------------------------------------------------------------

class TestStripBareCheckCall:
    def test_removes_last_check(self):
        lines = ["def check(c):", "    assert c(1)", "", "check(foo)"]
        cleaned, found = _strip_bare_check_call(lines)
        assert found is True
        assert "check(foo)" not in "\n".join(cleaned)

    def test_preserves_check_definition(self):
        lines = ["def check(c):", "    assert c(1)", "check(foo)"]
        cleaned, _ = _strip_bare_check_call(lines)
        assert "def check(c):" in cleaned

    def test_no_bare_check(self):
        lines = ["def check(c):", "    assert c(1)"]
        cleaned, found = _strip_bare_check_call(lines)
        assert found is False
        assert len(cleaned) == 2


# ---------------------------------------------------------------------------
# Full record parsing
# ---------------------------------------------------------------------------

_HUMANEVAL_RECORD = {
    "task_id": "HumanEval/0",
    "prompt": (
        "from typing import List\n\n"
        "def has_close_elements(numbers: List[float], threshold: float) -> bool:\n"
        '    """Check if any two numbers are closer than threshold."""\n'
    ),
    "canonical_solution": "    pass\n",
    "entry_point": "has_close_elements",
    "test": _HE_STYLE_TEST,
}

_MBPP_RECORD = {
    "task_id": 2,
    "prompt": "Write a function to find the shared elements from the given two lists.",
    "code": "def similar_elements(test_tup1, test_tup2):\n  return tuple(set(test_tup1) & set(test_tup2))\n",
    "test": _MBPP_STYLE_TEST,
}


class TestParseEvalplusRecord:
    def test_humaneval_basic_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._exercises_dir", lambda: tmp_path
        )
        ex = _parse_evalplus_record(_HUMANEVAL_RECORD)
        assert ex is not None
        assert ex.language == "python"
        assert ex.slug == "humaneval-0"
        assert ex.description == _HUMANEVAL_RECORD["prompt"]
        assert ex.starter_code == {}
        assert len(ex.reference_tests) == 1

    def test_humaneval_test_file_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._exercises_dir", lambda: tmp_path
        )
        ex = _parse_evalplus_record(_HUMANEVAL_RECORD)
        assert "humaneval_0_test.py" in ex.reference_tests

    def test_humaneval_exercise_dir_created(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._exercises_dir", lambda: tmp_path
        )
        ex = _parse_evalplus_record(_HUMANEVAL_RECORD)
        assert (tmp_path / "humaneval-0").is_dir()
        assert (tmp_path / "humaneval-0" / "humaneval_0_test.py").is_file()

    def test_mbpp_basic_fields(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._exercises_dir", lambda: tmp_path
        )
        ex = _parse_evalplus_record(_MBPP_RECORD)
        assert ex is not None
        assert ex.slug == "mbpp-2"
        assert ex.language == "python"

    def test_mbpp_entry_point_from_code(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._exercises_dir", lambda: tmp_path
        )
        ex = _parse_evalplus_record(_MBPP_RECORD)
        test_content = list(ex.reference_tests.values())[0]
        assert "candidate = similar_elements" in test_content

    def test_missing_fields_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._exercises_dir", lambda: tmp_path
        )
        assert _parse_evalplus_record({}) is None
        assert _parse_evalplus_record({"task_id": "X"}) is None
        assert _parse_evalplus_record({"task_id": "X", "prompt": "p"}) is None

    def test_no_entry_point_no_code_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._exercises_dir", lambda: tmp_path
        )
        record = {"task_id": "X/0", "prompt": "p", "test": "t"}
        assert _parse_evalplus_record(record) is None


# ---------------------------------------------------------------------------
# load_evalplus_exercises
# ---------------------------------------------------------------------------

class TestLoadEvalplusExercises:
    @pytest.fixture
    def evalplus_cache(self, tmp_path, monkeypatch):
        """Create a fake evalplus cache with a few records."""
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._evalplus_dir", lambda: tmp_path
        )
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._exercises_dir",
            lambda: tmp_path / "exercises",
        )

        # Write minimal JSONL files.
        he_records = [_HUMANEVAL_RECORD]
        mbpp_records = [_MBPP_RECORD]

        (tmp_path / "humaneval_plus.jsonl").write_text(
            "\n".join(json.dumps(r) for r in he_records), encoding="utf-8"
        )
        (tmp_path / "mbpp_plus.jsonl").write_text(
            "\n".join(json.dumps(r) for r in mbpp_records), encoding="utf-8"
        )

        return tmp_path

    def test_loads_both_datasets(self, evalplus_cache):
        exercises = load_evalplus_exercises()
        assert len(exercises) == 2
        slugs = {e.slug for e in exercises}
        assert "humaneval-0" in slugs
        assert "mbpp-2" in slugs

    def test_filter_by_slug(self, evalplus_cache):
        exercises = load_evalplus_exercises(slug="humaneval")
        assert len(exercises) == 1
        assert exercises[0].slug == "humaneval-0"

    def test_sorted_output(self, evalplus_cache):
        exercises = load_evalplus_exercises()
        ids = [e.id for e in exercises]
        assert ids == sorted(ids)

    def test_no_cache_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "pm_core.bench.exercises_evalplus._evalplus_dir",
            lambda: tmp_path / "nonexistent",
        )
        with pytest.raises(FileNotFoundError):
            load_evalplus_exercises()


# ---------------------------------------------------------------------------
# Integration: transformed test is valid Python
# ---------------------------------------------------------------------------

class TestTransformedTestIsValid:
    """Verify the transformed test file is syntactically valid."""

    def test_humaneval_compiles(self):
        code = _transform_test_code(_HE_STYLE_TEST, "has_close", "humaneval_0")
        compile(code, "<test>", "exec")

    def test_mbpp_compiles(self):
        code = _transform_test_code(_MBPP_STYLE_TEST, "similar_elements", "mbpp_2")
        compile(code, "<test>", "exec")

    def test_check_style_compiles(self):
        code = _transform_test_code(_CHECK_STYLE_TEST, "double", "test_mod")
        compile(code, "<test>", "exec")
