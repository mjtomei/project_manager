"""Tests for bench test generation — prompt building and variant selection."""

from pathlib import Path
from unittest import mock

from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, RequestStats, Runner
from pm_core.bench.test_gen import (
    _build_prompt,
    _extract_func_name,
    _merge_test_suites,
    generate_tests,
    sample_test_subset,
    split_test_functions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _exercise(**overrides):
    defaults = dict(
        language="python",
        slug="hello-world",
        description="# Hello World\nWrite a function that returns 'Hello, World!'.",
        starter_code={"hello_world.py": "def hello():\n    pass\n"},
        reference_tests={"hello_world_test.py": "def test_hello():\n    assert hello() == 'Hello, World!'\n"},
        path=Path("/tmp/fake"),
    )
    defaults.update(overrides)
    return Exercise(**defaults)


# ---------------------------------------------------------------------------
# Tests — _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_includes_language(self):
        prompt = _build_prompt(_exercise())
        assert "Language: python" in prompt

    def test_includes_description(self):
        prompt = _build_prompt(_exercise())
        assert "Hello World" in prompt

    def test_includes_starter_code(self):
        prompt = _build_prompt(_exercise())
        assert "def hello():" in prompt

    def test_includes_test_hint_for_known_language(self):
        prompt = _build_prompt(_exercise())
        assert "pytest" in prompt

    def test_no_hint_for_unknown_language(self):
        prompt = _build_prompt(_exercise(language="fortran"))
        assert "Language: fortran" in prompt
        # No crash, just no hint
        assert "Test framework hint: \n" in prompt


# ---------------------------------------------------------------------------
# Tests — generate_tests
# ---------------------------------------------------------------------------

class TestGenerateTests:
    def test_picks_longest_result(self):
        results = [
            GenerationResult(content="short", stats=RequestStats()),
            GenerationResult(content="this is the longest test code of all", stats=RequestStats()),
            GenerationResult(content="medium length code", stats=RequestStats()),
        ]
        runner = mock.MagicMock(spec=Runner)
        runner.generate.return_value = results

        code, gen_results = generate_tests(_exercise(), runner, "test-model")

        assert code == "this is the longest test code of all"
        assert len(gen_results) == 3

    def test_strips_markdown_fences(self):
        results = [
            GenerationResult(
                content="```python\ndef test_hello():\n    assert True\n```",
                stats=RequestStats(),
            ),
        ]
        runner = mock.MagicMock(spec=Runner)
        runner.generate.return_value = results

        code, _ = generate_tests(_exercise(), runner, "test-model", num_variants=1)

        assert "```" not in code
        assert "def test_hello():" in code

    def test_respects_num_variants(self):
        runner = mock.MagicMock(spec=Runner)
        runner.generate.return_value = [
            GenerationResult(content="test", stats=RequestStats()),
            GenerationResult(content="test2", stats=RequestStats()),
        ]

        generate_tests(_exercise(), runner, "test-model", num_variants=2)

        call_kwargs = runner.generate.call_args[1]
        assert len(call_kwargs["temperatures"]) == 2

    def test_custom_temperatures_trimmed(self):
        runner = mock.MagicMock(spec=Runner)
        runner.generate.return_value = [
            GenerationResult(content="test", stats=RequestStats()),
        ]

        generate_tests(
            _exercise(), runner, "test-model",
            num_variants=1, temperatures=[0.1, 0.9, 1.0],
        )

        call_kwargs = runner.generate.call_args[1]
        assert call_kwargs["temperatures"] == [0.1]

    def test_empty_results(self):
        runner = mock.MagicMock(spec=Runner)
        runner.generate.return_value = []

        code, gen_results = generate_tests(_exercise(), runner, "test-model")

        assert code == ""
        assert gen_results == []

    def test_all_empty_content(self):
        results = [
            GenerationResult(content="", stats=RequestStats()),
            GenerationResult(content="   ", stats=RequestStats()),
        ]
        runner = mock.MagicMock(spec=Runner)
        runner.generate.return_value = results

        code, _ = generate_tests(_exercise(), runner, "test-model", num_variants=2)

        assert code == ""

    def test_chain_mode_calls_complete_sequentially(self):
        """Chain mode should call runner.complete() N times, not runner.generate()."""
        runner = mock.MagicMock(spec=Runner)
        runner.complete.side_effect = [
            GenerationResult(content="def test_a():\n    pass", stats=RequestStats()),
            GenerationResult(content="def test_b():\n    pass", stats=RequestStats()),
        ]

        code, results = generate_tests(
            _exercise(), runner, "test-model", num_variants=2, chain=True,
        )

        assert runner.complete.call_count == 2
        runner.generate.assert_not_called()
        assert len(results) == 2
        # Merged output should contain both test functions
        assert "test_a" in code
        assert "test_b" in code

    def test_chain_mode_passes_prior_suites_in_prompt(self):
        """Second call in chain mode should include the first suite in the prompt."""
        runner = mock.MagicMock(spec=Runner)
        runner.complete.side_effect = [
            GenerationResult(content="def test_first():\n    pass", stats=RequestStats()),
            GenerationResult(content="def test_second():\n    pass", stats=RequestStats()),
        ]

        generate_tests(_exercise(), runner, "test-model", num_variants=2, chain=True)

        # First call: no prior suites
        first_msgs = runner.complete.call_args_list[0][1]["messages"]
        assert "Previous Test Suites" not in first_msgs[1]["content"]

        # Second call: should reference first suite
        second_msgs = runner.complete.call_args_list[1][1]["messages"]
        assert "Previous Test Suites" in second_msgs[1]["content"]
        assert "test_first" in second_msgs[1]["content"]


# ---------------------------------------------------------------------------
# Tests — _extract_func_name
# ---------------------------------------------------------------------------

class TestExtractFuncName:
    def test_python(self):
        assert _extract_func_name("def test_hello():\n    pass", "python") == "test_hello"

    def test_go(self):
        assert _extract_func_name("func TestAdd(t *testing.T) {", "go") == "TestAdd"

    def test_rust(self):
        assert _extract_func_name("fn test_basic() {", "rust") == "test_basic"

    def test_javascript(self):
        assert _extract_func_name("test('adds numbers', () => {", "javascript") == "adds numbers"

    def test_unknown_language_returns_none(self):
        assert _extract_func_name("def test_x(): pass", "cpp") is None

    def test_no_match_returns_none(self):
        assert _extract_func_name("# just a comment", "python") is None


# ---------------------------------------------------------------------------
# Tests — _merge_test_suites
# ---------------------------------------------------------------------------

class TestMergeTestSuites:
    def test_single_suite_returned_as_is(self):
        code = "def test_a():\n    pass"
        assert _merge_test_suites([code], "python") == code

    def test_deduplicates_by_function_name(self):
        suite1 = "import pytest\n\ndef test_a():\n    assert 1\n\ndef test_b():\n    assert 2"
        suite2 = "import pytest\n\ndef test_a():\n    assert 99\n\ndef test_c():\n    assert 3"
        merged = _merge_test_suites([suite1, suite2], "python")
        # test_a should appear only once (from suite1), test_c should be added
        assert merged.count("test_a") == 1
        assert "test_b" in merged
        assert "test_c" in merged

    def test_empty_list(self):
        assert _merge_test_suites([], "python") == ""


# ---------------------------------------------------------------------------
# Tests — split_test_functions
# ---------------------------------------------------------------------------

class TestSplitTestFunctions:
    def test_python_split(self):
        code = (
            "import pytest\n"
            "from hello import hello\n"
            "\n"
            "def test_hello():\n"
            "    assert hello() == 'Hello'\n"
            "\n"
            "def test_world():\n"
            "    assert hello() == 'World'\n"
        )
        header, funcs = split_test_functions(code, "python")
        assert "import pytest" in header
        assert len(funcs) == 2
        assert "def test_hello():" in funcs[0]
        assert "def test_world():" in funcs[1]

    def test_python_preserves_header(self):
        code = (
            "import os\n"
            "import sys\n"
            "\n"
            "CONSTANT = 42\n"
            "\n"
            "def test_one():\n"
            "    pass\n"
        )
        header, funcs = split_test_functions(code, "python")
        assert "import os" in header
        assert "CONSTANT = 42" in header
        assert len(funcs) == 1

    def test_no_tests_returns_empty_list(self):
        code = "import os\n# no tests here\n"
        header, funcs = split_test_functions(code, "python")
        assert header == code
        assert funcs == []

    def test_go_split(self):
        code = (
            "package main\n"
            "\n"
            "import \"testing\"\n"
            "\n"
            "func TestAdd(t *testing.T) {\n"
            "    // test add\n"
            "}\n"
            "\n"
            "func TestSub(t *testing.T) {\n"
            "    // test sub\n"
            "}\n"
        )
        header, funcs = split_test_functions(code, "go")
        assert "package main" in header
        assert len(funcs) == 2

    def test_unknown_language(self):
        code = "some test code"
        header, funcs = split_test_functions(code, "fortran")
        assert header == ""
        assert funcs == [code]


# ---------------------------------------------------------------------------
# Tests — sample_test_subset
# ---------------------------------------------------------------------------

class TestSampleTestSubset:
    def test_samples_n_tests(self):
        import random
        funcs = ["def test_a():\n    pass", "def test_b():\n    pass",
                 "def test_c():\n    pass", "def test_d():\n    pass"]
        header = "import pytest"
        result = sample_test_subset(funcs, header, 2, rng=random.Random(42))
        assert "import pytest" in result
        # Exactly 2 test functions in the output
        assert result.count("def test_") == 2

    def test_returns_all_when_n_ge_len(self):
        funcs = ["def test_a():\n    pass", "def test_b():\n    pass"]
        header = "import pytest"
        result = sample_test_subset(funcs, header, 5)
        assert result.count("def test_") == 2

    def test_empty_header(self):
        funcs = ["def test_a():\n    pass"]
        result = sample_test_subset(funcs, "", 1)
        assert result.startswith("def test_a")

    def test_deterministic_with_rng(self):
        import random
        funcs = [f"def test_{c}():\n    pass" for c in "abcdefgh"]
        r1 = sample_test_subset(funcs, "", 3, rng=random.Random(99))
        r2 = sample_test_subset(funcs, "", 3, rng=random.Random(99))
        assert r1 == r2
