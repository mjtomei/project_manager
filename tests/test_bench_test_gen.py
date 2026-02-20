"""Tests for bench test generation — prompt building and variant selection."""

from pathlib import Path
from unittest import mock

from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, RequestStats, Runner
from pm_core.bench.test_gen import _build_prompt, generate_tests


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
