"""Tests for pm_core.bench.solve — multi-candidate solution generation.

Tests cover:
- Temperature schedule generation
- Prompt building for each variant
- Code extraction from various model response formats
- Candidate generation with mocked runner
- Deduplication of identical solutions
- Diversity verification (candidate count, variant distribution)
"""

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, RequestStats, Runner
from pm_core.bench.solve import (
    PROMPT_VARIANTS,
    Candidate,
    build_prompt,
    deduplicate_candidates,
    extract_code,
    generate_candidates,
    generate_candidates_for_exercise,
    temperature_schedule,
)


# --- Fixtures ---


def _make_runner(responses: list[str] | None = None) -> MagicMock:
    """Create a mock Runner that returns canned responses."""
    runner = MagicMock(spec=Runner)
    if responses is None:
        responses = ['def two_fer(name="you"):\n    return f"One for {name}, one for me."']

    results = []
    for i, text in enumerate(responses):
        results.append(
            GenerationResult(
                content=text,
                model="test-model",
                temperature=0.0,
                stats=RequestStats(
                    prompt_tokens=100,
                    completion_tokens=50,
                    total_tokens=150,
                    wall_clock_seconds=1.0,
                ),
                finish_reason="stop",
            )
        )

    # Cycle through responses if fewer than needed
    def side_effect(**kwargs):
        idx = runner.complete.call_count - 1
        result = results[idx % len(results)]
        # Update temperature to match what was requested
        result = GenerationResult(
            content=result.content,
            model=result.model,
            temperature=kwargs.get("temperature", 0.0),
            stats=result.stats,
            finish_reason=result.finish_reason,
        )
        return result

    runner.complete.side_effect = side_effect
    return runner


def _make_exercise(
    language="python",
    slug="two-fer",
    description="Create a sentence like 'One for X, one for me.'",
) -> Exercise:
    return Exercise(
        language=language,
        slug=slug,
        description=description,
        starter_code={"two_fer.py": 'def two_fer(name="you"):\n    pass\n'},
        reference_tests={
            "two_fer_test.py": (
                'def test_no_name():\n'
                '    assert two_fer() == "One for you, one for me."\n'
            )
        },
        path=Path("/fake/exercises/python/two-fer"),
    )


# --- Temperature Schedule ---


class TestTemperatureSchedule:

    def test_single_candidate(self):
        assert temperature_schedule(1) == [0.0]

    def test_two_candidates(self):
        assert temperature_schedule(2) == [0.0, 1.0]

    def test_three_candidates(self):
        assert temperature_schedule(3) == [0.0, 0.5, 1.0]

    def test_eight_candidates(self):
        temps = temperature_schedule(8)
        assert len(temps) == 8
        assert temps[0] == 0.0
        assert temps[-1] == 1.0
        # Monotonically increasing
        for i in range(1, len(temps)):
            assert temps[i] > temps[i - 1]

    def test_zero_candidates(self):
        assert temperature_schedule(0) == [0.0]

    def test_large_n(self):
        temps = temperature_schedule(100)
        assert len(temps) == 100
        assert temps[0] == 0.0
        assert temps[-1] == 1.0
        assert all(0.0 <= t <= 1.0 for t in temps)


# --- Code Extraction ---


class TestExtractCode:

    def test_plain_code(self):
        code = 'def hello():\n    return "hi"'
        assert extract_code(code) == code

    def test_fenced_with_language(self):
        text = '```python\ndef hello():\n    return "hi"\n```'
        assert extract_code(text) == 'def hello():\n    return "hi"'

    def test_fenced_without_language(self):
        text = '```\ndef hello():\n    return "hi"\n```'
        assert extract_code(text) == 'def hello():\n    return "hi"'

    def test_fenced_with_surrounding_text(self):
        text = (
            "Here is the solution:\n\n"
            "```python\n"
            'def hello():\n    return "hi"\n'
            "```\n\n"
            "This works because..."
        )
        assert extract_code(text) == 'def hello():\n    return "hi"'

    def test_unclosed_fence(self):
        text = '```python\ndef hello():\n    return "hi"'
        assert extract_code(text) == 'def hello():\n    return "hi"'

    def test_multiple_blocks_picks_longest(self):
        text = (
            "```python\nimport os\n```\n\n"
            "```python\n"
            "import os\n\n"
            'def solve():\n    return os.getcwd()\n'
            "```"
        )
        result = extract_code(text)
        assert "def solve" in result

    def test_empty_string(self):
        assert extract_code("") == ""

    def test_whitespace_only(self):
        assert extract_code("   \n  ") == ""

    def test_rust_fenced(self):
        text = '```rust\nfn main() {\n    println!("hello");\n}\n```'
        assert extract_code(text) == 'fn main() {\n    println!("hello");\n}'

    def test_go_fenced(self):
        text = '```go\npackage main\n\nfunc main() {}\n```'
        assert extract_code(text) == "package main\n\nfunc main() {}"


# --- Prompt Building ---


class TestBuildPrompt:

    def test_direct_variant(self):
        messages = build_prompt(
            language="python",
            description="Do the thing.",
            starter_code="def thing(): pass",
            variant="direct",
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "python" in messages[0]["content"].lower()
        assert messages[1]["role"] == "user"
        assert "Do the thing." in messages[1]["content"]
        assert "def thing(): pass" in messages[1]["content"]
        assert "ONLY" in messages[1]["content"]

    def test_chain_of_thought_variant(self):
        messages = build_prompt(
            language="go",
            description="Solve it.",
            starter_code="func solve() {}",
            variant="chain_of_thought",
        )
        user_msg = messages[1]["content"]
        assert "step by step" in user_msg.lower()
        assert "Solve it." in user_msg

    def test_example_driven_variant(self):
        messages = build_prompt(
            language="rust",
            description="Implement it.",
            starter_code="fn solve() {}",
            variant="example_driven",
            tests="fn test_basic() { assert_eq!(1, 1); }",
        )
        user_msg = messages[1]["content"]
        assert "test cases" in user_msg.lower()
        assert "test_basic" in user_msg

    def test_includes_tests_in_prompt(self):
        messages = build_prompt(
            language="python",
            description="Solve.",
            starter_code="pass",
            variant="direct",
            tests="def test_it(): assert True",
        )
        user_msg = messages[1]["content"]
        assert "test_it" in user_msg

    def test_empty_starter_code_omitted(self):
        messages = build_prompt(
            language="python",
            description="Solve.",
            starter_code="",
            variant="direct",
        )
        user_msg = messages[1]["content"]
        assert "Starter Code" not in user_msg

    def test_system_prompt_mentions_language(self):
        messages = build_prompt(
            language="javascript",
            description="x",
            starter_code="x",
            variant="direct",
        )
        assert "javascript" in messages[0]["content"].lower()

    def test_all_variants_have_prompts(self):
        for variant in PROMPT_VARIANTS:
            messages = build_prompt(
                language="python",
                description="test",
                starter_code="pass",
                variant=variant,
            )
            assert len(messages) == 2


# --- Candidate Generation ---


class TestGenerateCandidates:

    def test_generates_requested_number(self):
        runner = _make_runner(["def solve(): return 42"])
        candidates = generate_candidates(
            language="python",
            description="Return 42.",
            starter_code="def solve(): pass",
            runner=runner,
            model="test-model",
            num_candidates=5,
        )
        assert len(candidates) == 5
        assert runner.complete.call_count == 5

    def test_single_candidate(self):
        runner = _make_runner(["def solve(): return 1"])
        candidates = generate_candidates(
            language="python",
            description="Return 1.",
            starter_code="def solve(): pass",
            runner=runner,
            model="test-model",
            num_candidates=1,
        )
        assert len(candidates) == 1
        assert candidates[0].temperature == 0.0

    def test_candidate_fields(self):
        runner = _make_runner(["def solve(): return 42"])
        candidates = generate_candidates(
            language="python",
            description="Return 42.",
            starter_code="def solve(): pass",
            runner=runner,
            model="test-model",
            num_candidates=1,
        )
        c = candidates[0]
        assert c.code == "def solve(): return 42"
        assert c.temperature == 0.0
        assert c.prompt_variant == "direct"
        assert c.model == "test-model"
        assert c.generation_result is not None

    def test_cycles_through_variants(self):
        runner = _make_runner(["code"] * 6)
        candidates = generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=6,
        )
        variants = [c.prompt_variant for c in candidates]
        expected = ["direct", "chain_of_thought", "example_driven"] * 2
        assert variants == expected

    def test_uses_temperature_schedule(self):
        runner = _make_runner(["code"] * 3)
        candidates = generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=3,
        )
        temps = [c.temperature for c in candidates]
        assert temps == [0.0, 0.5, 1.0]

    def test_custom_temperatures(self):
        runner = _make_runner(["code"] * 3)
        candidates = generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=3,
            temperatures=[0.1, 0.5, 0.9],
        )
        temps = [c.temperature for c in candidates]
        assert temps == [0.1, 0.5, 0.9]

    def test_extracts_code_from_fenced_response(self):
        runner = _make_runner(['```python\ndef solve():\n    return 42\n```'])
        candidates = generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=1,
        )
        assert candidates[0].code == "def solve():\n    return 42"

    def test_passes_model_to_runner(self):
        runner = _make_runner(["code"])
        generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="qwen3:32b",
            num_candidates=1,
        )
        call_kwargs = runner.complete.call_args[1]
        assert call_kwargs["model"] == "qwen3:32b"

    def test_passes_temperature_to_runner(self):
        runner = _make_runner(["code"] * 3)
        generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=3,
        )
        temps_passed = [
            c[1]["temperature"] for c in runner.complete.call_args_list
        ]
        assert temps_passed == [0.0, 0.5, 1.0]

    def test_dict_starter_code(self):
        runner = _make_runner(["code"])
        generate_candidates(
            language="python",
            description="x",
            starter_code={"main.py": "def main(): pass", "util.py": "X = 1"},
            runner=runner,
            model="m",
            num_candidates=1,
        )
        user_msg = runner.complete.call_args[1]["messages"][1]["content"]
        assert "main.py" in user_msg
        assert "util.py" in user_msg

    def test_includes_tests_in_prompt(self):
        runner = _make_runner(["code"])
        generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=1,
            tests="def test_it(): assert True",
        )
        user_msg = runner.complete.call_args[1]["messages"][1]["content"]
        assert "test_it" in user_msg

    def test_dict_tests(self):
        runner = _make_runner(["code"])
        generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=1,
            tests={"test_main.py": "def test_it(): assert True"},
        )
        user_msg = runner.complete.call_args[1]["messages"][1]["content"]
        assert "test_it" in user_msg

    def test_max_tokens_forwarded(self):
        runner = _make_runner(["code"])
        generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=1,
            max_tokens=8192,
        )
        call_kwargs = runner.complete.call_args[1]
        assert call_kwargs["max_tokens"] == 8192


# --- Exercise Convenience Wrapper ---


class TestGenerateCandidatesForExercise:

    def test_unpacks_exercise(self):
        exercise = _make_exercise()
        runner = _make_runner(["code"])
        candidates = generate_candidates_for_exercise(
            exercise, runner, "test-model", num_candidates=1,
        )
        assert len(candidates) == 1
        user_msg = runner.complete.call_args[1]["messages"][1]["content"]
        assert "One for X" in user_msg  # description
        assert "two_fer" in user_msg  # starter code

    def test_uses_reference_tests_as_fallback(self):
        exercise = _make_exercise()
        runner = _make_runner(["code"])
        generate_candidates_for_exercise(
            exercise, runner, "m", num_candidates=1,
        )
        user_msg = runner.complete.call_args[1]["messages"][1]["content"]
        assert "test_no_name" in user_msg

    def test_custom_tests_override_reference(self):
        exercise = _make_exercise()
        runner = _make_runner(["code"])
        generate_candidates_for_exercise(
            exercise, runner, "m", num_candidates=1,
            tests="def test_custom(): pass",
        )
        user_msg = runner.complete.call_args[1]["messages"][1]["content"]
        assert "test_custom" in user_msg
        assert "test_no_name" not in user_msg


# --- Deduplication ---


class TestDeduplicateCandidates:

    def test_removes_exact_duplicates(self):
        candidates = [
            Candidate(code="def f(): return 1", temperature=0.0,
                      prompt_variant="direct", model="m"),
            Candidate(code="def f(): return 1", temperature=0.5,
                      prompt_variant="chain_of_thought", model="m"),
            Candidate(code="def f(): return 2", temperature=1.0,
                      prompt_variant="example_driven", model="m"),
        ]
        result = deduplicate_candidates(candidates)
        assert len(result) == 2
        assert result[0].code == "def f(): return 1"
        assert result[1].code == "def f(): return 2"

    def test_keeps_first_occurrence(self):
        candidates = [
            Candidate(code="A", temperature=0.0, prompt_variant="direct", model="m"),
            Candidate(code="A", temperature=1.0, prompt_variant="chain_of_thought", model="m"),
        ]
        result = deduplicate_candidates(candidates)
        assert len(result) == 1
        assert result[0].temperature == 0.0
        assert result[0].prompt_variant == "direct"

    def test_handles_whitespace_differences(self):
        candidates = [
            Candidate(code="  code  ", temperature=0.0, prompt_variant="direct", model="m"),
            Candidate(code="code", temperature=0.5, prompt_variant="chain_of_thought", model="m"),
        ]
        result = deduplicate_candidates(candidates)
        assert len(result) == 1

    def test_all_unique(self):
        candidates = [
            Candidate(code=f"code_{i}", temperature=0.0,
                      prompt_variant="direct", model="m")
            for i in range(5)
        ]
        result = deduplicate_candidates(candidates)
        assert len(result) == 5

    def test_empty_list(self):
        assert deduplicate_candidates([]) == []

    def test_single_candidate(self):
        c = Candidate(code="x", temperature=0.0, prompt_variant="direct", model="m")
        assert deduplicate_candidates([c]) == [c]


# --- Diversity Verification ---


class TestDiversity:
    """Verify that candidate generation produces diverse outputs."""

    def test_variant_coverage_with_enough_candidates(self):
        """With N >= 3, all prompt variants should be used."""
        runner = _make_runner(["code"] * 9)
        candidates = generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=9,
        )
        variants_used = {c.prompt_variant for c in candidates}
        assert variants_used == set(PROMPT_VARIANTS.keys())

    def test_temperature_spread(self):
        """Candidates should span the full temperature range."""
        runner = _make_runner(["code"] * 8)
        candidates = generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=8,
        )
        temps = [c.temperature for c in candidates]
        assert min(temps) == 0.0
        assert max(temps) == 1.0

    def test_each_candidate_has_unique_temp_variant_pair(self):
        """With 3 candidates, each gets a different variant."""
        runner = _make_runner(["code"] * 3)
        candidates = generate_candidates(
            language="python",
            description="x",
            starter_code="pass",
            runner=runner,
            model="m",
            num_candidates=3,
        )
        pairs = [(c.temperature, c.prompt_variant) for c in candidates]
        # All pairs should be unique
        assert len(set(pairs)) == 3
