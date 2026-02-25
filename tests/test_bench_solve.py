"""Tests for bench solution generation — candidate distribution and prompt building."""

from pathlib import Path
from unittest import mock

import pytest

from pm_core.bench.exercises import Exercise
from pm_core.bench.runner import GenerationResult, RequestStats, Runner
from pm_core.bench.solve import (
    Candidate,
    HyperParams,
    PROMPT_VARIANTS,
    _build_chain_context,
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


# ---------------------------------------------------------------------------
# Tests — HyperParams
# ---------------------------------------------------------------------------

class TestHyperParams:
    def test_defaults_are_none_and_false(self):
        hp = HyperParams()
        assert hp.variant is None
        assert hp.temperature is None
        assert hp.chain is False
        assert hp.test_subset_size is None

    def test_validate_passes_for_defaults(self):
        HyperParams().validate()  # should not raise

    def test_validate_rejects_unknown_variant(self):
        hp = HyperParams(variant="unknown")
        with pytest.raises(ValueError, match="Unknown variant"):
            hp.validate()

    def test_validate_rejects_negative_temperature(self):
        hp = HyperParams(temperature=-0.1)
        with pytest.raises(ValueError, match="Temperature"):
            hp.validate()

    def test_validate_rejects_temperature_above_2(self):
        hp = HyperParams(temperature=2.1)
        with pytest.raises(ValueError, match="Temperature"):
            hp.validate()

    def test_validate_accepts_valid_temperature(self):
        HyperParams(temperature=0.0).validate()
        HyperParams(temperature=1.5).validate()
        HyperParams(temperature=2.0).validate()

    def test_validate_rejects_zero_test_subset(self):
        hp = HyperParams(test_subset_size=0)
        with pytest.raises(ValueError, match="test_subset_size"):
            hp.validate()

    def test_validate_accepts_valid_variant(self):
        for v in PROMPT_VARIANTS:
            HyperParams(variant=v).validate()


# ---------------------------------------------------------------------------
# Tests — _build_chain_context
# ---------------------------------------------------------------------------

class TestBuildChainContext:
    def test_includes_prior_solutions(self):
        ctx = _build_chain_context(["solution_1", "solution_2"])
        assert "Attempt 1" in ctx
        assert "solution_1" in ctx
        assert "Attempt 2" in ctx
        assert "solution_2" in ctx
        assert "DIFFERENT approach" in ctx


# ---------------------------------------------------------------------------
# Tests — generate_candidates with HyperParams
# ---------------------------------------------------------------------------

class TestGenerateCandidatesHyper:
    def _mock_runner(self, n):
        runner = mock.MagicMock(spec=Runner)
        runner.complete_batch.return_value = [
            GenerationResult(content=f"solution {i}", model="m", stats=RequestStats())
            for i in range(n)
        ]
        return runner

    def test_fixed_variant(self):
        runner = self._mock_runner(4)
        hyper = HyperParams(variant="direct")
        candidates = generate_candidates(
            _exercise(), runner, "m", num_candidates=4, hyper=hyper,
        )
        assert all(c.prompt_variant == "direct" for c in candidates)

    def test_fixed_temperature(self):
        runner = self._mock_runner(4)
        hyper = HyperParams(temperature=0.7)
        candidates = generate_candidates(
            _exercise(), runner, "m", num_candidates=4, hyper=hyper,
        )
        assert all(c.temperature == 0.7 for c in candidates)

    def test_chain_mode_uses_sequential_calls(self):
        """Chain mode should call runner.complete() sequentially, not complete_batch()."""
        runner = mock.MagicMock(spec=Runner)
        runner.complete.side_effect = [
            GenerationResult(content=f"solution {i}", model="m", stats=RequestStats())
            for i in range(3)
        ]
        hyper = HyperParams(chain=True)
        candidates = generate_candidates(
            _exercise(), runner, "m", num_candidates=3, hyper=hyper,
        )

        assert len(candidates) == 3
        assert runner.complete.call_count == 3
        runner.complete_batch.assert_not_called()

    def test_chain_mode_passes_prior_solutions(self):
        """Second and subsequent calls should include prior solutions in prompt."""
        runner = mock.MagicMock(spec=Runner)
        runner.complete.side_effect = [
            GenerationResult(content="sol_0", model="m", stats=RequestStats()),
            GenerationResult(content="sol_1", model="m", stats=RequestStats()),
        ]
        hyper = HyperParams(chain=True)
        generate_candidates(
            _exercise(), runner, "m", num_candidates=2, hyper=hyper,
        )

        # First call: no prior solutions
        first_msgs = runner.complete.call_args_list[0][1]["messages"]
        assert "Previous Attempts" not in first_msgs[0]["content"]

        # Second call: should contain first solution
        second_msgs = runner.complete.call_args_list[1][1]["messages"]
        assert "sol_0" in second_msgs[0]["content"]

    def test_test_subsets_produces_different_tests(self):
        """With test_subset_size, each candidate should get a different test sample."""
        runner = self._mock_runner(4)
        test_code = (
            "import pytest\n\n"
            "def test_a():\n    pass\n\n"
            "def test_b():\n    pass\n\n"
            "def test_c():\n    pass\n\n"
            "def test_d():\n    pass\n"
        )
        # Use test_driven variant so tests appear in all prompts
        hyper = HyperParams(variant="test_driven", test_subset_size=2)
        generate_candidates(
            _exercise(), runner, "m", num_candidates=4,
            tests=test_code, hyper=hyper,
        )

        # Each request should have test code with subsets applied
        requests = runner.complete_batch.call_args[1]["requests"]
        prompts = [r[0][0]["content"] for r in requests]
        for p in prompts:
            assert "test_" in p
            # Each subset should have exactly 2 test functions
            assert p.count("def test_") == 2

    def test_backward_compat_no_hyper(self):
        """Without hyper, behavior is unchanged: cycles variants + ramps temps."""
        runner = self._mock_runner(3)
        candidates = generate_candidates(
            _exercise(), runner, "m", num_candidates=3,
        )
        variants_used = [c.prompt_variant for c in candidates]
        variant_keys = list(PROMPT_VARIANTS.keys())
        for i in range(3):
            assert variants_used[i] == variant_keys[i % len(variant_keys)]
