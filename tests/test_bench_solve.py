"""Tests for bench solution generation — candidate distribution and prompt building."""

from pathlib import Path
from unittest import mock

import pytest

from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, RequestStats, Runner
from pm_core.bench.solve import (
    Candidate,
    PROMPT_VARIANTS,
    _build_prompt,
    generate_candidates,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _exercise(**overrides):
    defaults = dict(
        language="python",
        slug="two-fer",
        description="# Two Fer\nCreate a sentence like 'One for X, one for me.'",
        starter_code={"two_fer.py": "def two_fer(name='you'):\n    pass\n"},
        reference_tests={"two_fer_test.py": "def test():\n    pass\n"},
        path=Path("/tmp/fake"),
    )
    defaults.update(overrides)
    return Exercise(**defaults)


# ---------------------------------------------------------------------------
# Tests — _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_direct_variant(self):
        prompt = _build_prompt(_exercise(), "direct")
        assert "Language: python" in prompt
        assert "Two Fer" in prompt
        assert "Implement the solution" in prompt

    def test_chain_of_thought_variant(self):
        prompt = _build_prompt(_exercise(), "chain_of_thought")
        assert "Think step by step" in prompt

    def test_test_driven_variant_includes_tests(self):
        prompt = _build_prompt(_exercise(), "test_driven", tests="def test_foo(): pass")
        assert "def test_foo(): pass" in prompt
        assert "## Tests" in prompt

    def test_test_driven_without_tests_omits_section(self):
        prompt = _build_prompt(_exercise(), "test_driven")
        assert "## Tests" not in prompt

    def test_includes_starter_code(self):
        prompt = _build_prompt(_exercise(), "direct")
        assert "def two_fer" in prompt


# ---------------------------------------------------------------------------
# Tests — generate_candidates
# ---------------------------------------------------------------------------

class TestGenerateCandidates:
    def _mock_runner(self, n):
        runner = mock.MagicMock(spec=Runner)
        runner.complete_batch.return_value = [
            GenerationResult(content=f"solution {i}", model="m", stats=RequestStats())
            for i in range(n)
        ]
        return runner

    def test_returns_correct_number(self):
        runner = self._mock_runner(4)
        candidates = generate_candidates(_exercise(), runner, "m", num_candidates=4)

        assert len(candidates) == 4
        assert all(isinstance(c, Candidate) for c in candidates)

    def test_cycles_through_variants(self):
        n = 6
        runner = self._mock_runner(n)
        candidates = generate_candidates(_exercise(), runner, "m", num_candidates=n)

        variants_used = [c.prompt_variant for c in candidates]
        variant_keys = list(PROMPT_VARIANTS.keys())
        for i in range(n):
            assert variants_used[i] == variant_keys[i % len(variant_keys)]

    def test_single_candidate_uses_zero_temp(self):
        runner = self._mock_runner(1)
        candidates = generate_candidates(_exercise(), runner, "m", num_candidates=1)

        assert candidates[0].temperature == 0.0

    def test_strips_markdown_fences(self):
        runner = mock.MagicMock(spec=Runner)
        runner.complete_batch.return_value = [
            GenerationResult(
                content="```python\ndef two_fer():\n    return 'One for you'\n```",
                model="m",
                stats=RequestStats(),
            ),
        ]

        candidates = generate_candidates(_exercise(), runner, "m", num_candidates=1)

        assert "```" not in candidates[0].code
        assert "def two_fer():" in candidates[0].code

    def test_custom_temperatures(self):
        runner = self._mock_runner(3)
        candidates = generate_candidates(
            _exercise(), runner, "m",
            num_candidates=3, temperatures=[0.1, 0.5, 0.9],
        )

        assert candidates[0].temperature == 0.1
        assert candidates[1].temperature == 0.5
        assert candidates[2].temperature == 0.9

    def test_passes_tests_to_test_driven_variant(self):
        runner = self._mock_runner(3)
        generate_candidates(
            _exercise(), runner, "m",
            num_candidates=3, tests="test code here",
        )

        call_args = runner.complete_batch.call_args
        requests = call_args[1]["requests"]
        # Variant order: direct(0), chain_of_thought(1), test_driven(2)
        test_driven_msg = requests[2][0][0]["content"]
        assert "test code here" in test_driven_msg

    def test_batch_request_sent(self):
        runner = self._mock_runner(4)
        generate_candidates(_exercise(), runner, "m", num_candidates=4)

        runner.complete_batch.assert_called_once()
        call_args = runner.complete_batch.call_args
        assert len(call_args[1]["requests"]) == 4


# ---------------------------------------------------------------------------
# Tests — Candidate dataclass
# ---------------------------------------------------------------------------

class TestCandidateDataclass:
    def test_fields(self):
        c = Candidate(
            code="pass",
            temperature=0.5,
            prompt_variant="direct",
            model="test-model",
            generation_result=GenerationResult(stats=RequestStats()),
        )
        assert c.code == "pass"
        assert c.temperature == 0.5
        assert c.prompt_variant == "direct"
        assert c.model == "test-model"
