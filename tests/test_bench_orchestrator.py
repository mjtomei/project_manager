"""Tests for pm_core.bench.orchestrator.

Tests the tournament selection pipeline with mocked LLM and executor dependencies.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pm_core.bench.exercises import Exercise
from pm_core.bench.executor import ScoreResult
from pm_core.bench.orchestrator import (
    BenchmarkRun,
    ExerciseResult,
    format_results_table,
    run_exercise_tournament,
    save_results_json,
)
from pm_core.bench.runner import CostMetrics, GenerationResult, OllamaRunner
from pm_core.bench.solve import Candidate


def _make_exercise(language="python", slug="two-fer") -> Exercise:
    return Exercise(
        language=language,
        slug=slug,
        description="Create a sentence like 'One for X, one for me.'",
        starter_code='def two_fer(name="you"):\n    pass\n',
        reference_tests='def test_no_name():\n    assert two_fer() == "One for you, one for me."\n',
        exercise_dir=Path("/fake/exercises/python/two-fer"),
    )


def _make_gen_result(text="def two_fer(): pass", temp=0.7) -> GenerationResult:
    return GenerationResult(
        text=text,
        model="test-model",
        temperature=temp,
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        wall_clock_seconds=1.0,
    )


class TestTournamentSelection:
    """Test that tournament selection picks the highest-scoring candidate."""

    @patch("pm_core.bench.orchestrator.execute_tests")
    @patch("pm_core.bench.orchestrator.generate_candidates")
    @patch("pm_core.bench.orchestrator.generate_tests")
    def test_picks_best_candidate(self, mock_gen_tests, mock_gen_cands, mock_execute):
        exercise = _make_exercise()
        runner = MagicMock(spec=OllamaRunner)
        runner.metrics = CostMetrics()

        # generate_tests returns test code and results
        mock_gen_tests.return_value = ("def test_basic(): pass", [_make_gen_result()])

        # generate_candidates returns 3 candidates
        candidates = [
            Candidate(code="bad1", temperature=0.0, prompt_variant="direct",
                      model="m", generation_result=_make_gen_result()),
            Candidate(code="best", temperature=0.5, prompt_variant="chain_of_thought",
                      model="m", generation_result=_make_gen_result()),
            Candidate(code="bad2", temperature=1.0, prompt_variant="test_driven",
                      model="m", generation_result=_make_gen_result()),
        ]
        # First call returns tournament candidates, second returns baseline
        mock_gen_cands.side_effect = [
            candidates,
            [Candidate(code="baseline", temperature=0.0, prompt_variant="direct",
                        model="m", generation_result=_make_gen_result())],
        ]

        # Scoring: bad1=0.3, best=0.9, bad2=0.5 on gen tests
        # Then best against ref tests = 0.8, baseline against ref tests = 0.4
        mock_execute.side_effect = [
            ScoreResult(passed=3, total=10, score=0.3),   # bad1 vs gen tests
            ScoreResult(passed=9, total=10, score=0.9),   # best vs gen tests
            ScoreResult(passed=5, total=10, score=0.5),   # bad2 vs gen tests
            ScoreResult(passed=8, total=10, score=0.8),   # best vs ref tests
            ScoreResult(passed=4, total=10, score=0.4),   # baseline vs ref tests
        ]

        result = run_exercise_tournament(exercise, runner, "m", num_candidates=3)

        assert result.tournament_score == 0.8
        assert result.baseline_score == 0.4
        assert result.tournament_best_gen_score == 0.9
        assert result.error is None

        # The best candidate (score=0.9) should be the one scored against ref tests
        # execute_tests call 4 (index 3) should use "best" code
        ref_call = mock_execute.call_args_list[3]
        assert ref_call[0][1] == "best"  # candidate_code arg

    @patch("pm_core.bench.orchestrator.execute_tests")
    @patch("pm_core.bench.orchestrator.generate_candidates")
    @patch("pm_core.bench.orchestrator.generate_tests")
    def test_handles_all_failing_candidates(self, mock_gen_tests, mock_gen_cands, mock_execute):
        exercise = _make_exercise()
        runner = MagicMock(spec=OllamaRunner)
        runner.metrics = CostMetrics()

        mock_gen_tests.return_value = ("tests", [_make_gen_result()])
        mock_gen_cands.side_effect = [
            [Candidate(code="c1", temperature=0.0, prompt_variant="direct",
                       model="m", generation_result=_make_gen_result())],
            [Candidate(code="bl", temperature=0.0, prompt_variant="direct",
                       model="m", generation_result=_make_gen_result())],
        ]

        mock_execute.side_effect = [
            ScoreResult(passed=0, total=5, score=0.0),   # c1 vs gen tests
            ScoreResult(passed=0, total=5, score=0.0),   # c1 vs ref tests
            ScoreResult(passed=0, total=5, score=0.0),   # baseline
        ]

        result = run_exercise_tournament(exercise, runner, "m", num_candidates=1)

        assert result.tournament_score == 0.0
        assert result.baseline_score == 0.0
        assert result.error is None

    @patch("pm_core.bench.orchestrator.execute_tests")
    @patch("pm_core.bench.orchestrator.generate_candidates")
    @patch("pm_core.bench.orchestrator.generate_tests")
    def test_records_error_on_connection_failure(self, mock_gen_tests, mock_gen_cands, mock_execute):
        exercise = _make_exercise()
        runner = MagicMock(spec=OllamaRunner)
        runner.metrics = CostMetrics()

        mock_gen_tests.side_effect = ConnectionError("Ollama down")

        result = run_exercise_tournament(exercise, runner, "m", num_candidates=3)

        assert result.error is not None
        assert "connection" in result.error.lower() or "ollama" in result.error.lower()


class TestBenchmarkRun:
    """Test BenchmarkRun aggregate calculations."""

    def test_aggregate_scores(self):
        run = BenchmarkRun(model="m", num_candidates=8, languages=["python"])
        run.results = [
            ExerciseResult(language="python", slug="a", tournament_score=0.8, baseline_score=0.4),
            ExerciseResult(language="python", slug="b", tournament_score=0.6, baseline_score=0.6),
            ExerciseResult(language="python", slug="c", tournament_score=1.0, baseline_score=0.2),
        ]

        assert run.tournament_aggregate == pytest.approx(0.8)
        assert run.baseline_aggregate == pytest.approx(0.4)

    def test_aggregate_excludes_errors(self):
        run = BenchmarkRun(model="m", num_candidates=8, languages=["python"])
        run.results = [
            ExerciseResult(language="python", slug="a", tournament_score=1.0, baseline_score=0.5),
            ExerciseResult(language="python", slug="b", error="failed"),
        ]

        # Only the non-error result should count
        assert run.tournament_aggregate == pytest.approx(1.0)
        assert run.baseline_aggregate == pytest.approx(0.5)
        assert run.num_errors == 1

    def test_empty_run(self):
        run = BenchmarkRun(model="m", num_candidates=8, languages=[])
        assert run.tournament_aggregate == 0.0
        assert run.baseline_aggregate == 0.0
        assert run.tokens_per_exercise() == 0.0


class TestFormatResultsTable:
    """Test terminal table output."""

    def test_basic_table(self):
        run = BenchmarkRun(
            model="qwen3:32b",
            num_candidates=8,
            languages=["python"],
            total_tokens=5000,
            total_wall_clock_seconds=120.5,
        )
        run.results = [
            ExerciseResult(
                language="python", slug="two-fer",
                tournament_score=0.8, baseline_score=0.4,
                tokens_used=2500, wall_clock_seconds=60.0,
            ),
            ExerciseResult(
                language="python", slug="leap",
                tournament_score=1.0, baseline_score=1.0,
                tokens_used=2500, wall_clock_seconds=60.0,
            ),
        ]

        table = format_results_table(run)
        assert "qwen3:32b" in table
        assert "two-fer" in table
        assert "leap" in table
        assert "AGGREGATE" in table
        assert "5,000" in table  # total tokens

    def test_table_shows_errors(self):
        run = BenchmarkRun(model="m", num_candidates=8, languages=["go"])
        run.results = [
            ExerciseResult(language="go", slug="broken", error="timeout"),
        ]

        table = format_results_table(run)
        assert "ERROR" in table
        assert "1 exercises had errors" in table


class TestSaveResultsJson:
    """Test JSON output."""

    def test_saves_valid_json(self, tmp_path):
        run = BenchmarkRun(
            model="test-model",
            num_candidates=4,
            languages=["python"],
            total_tokens=1000,
            total_wall_clock_seconds=30.0,
        )
        run.results = [
            ExerciseResult(
                language="python", slug="hello",
                tournament_score=1.0, baseline_score=0.5,
                num_candidates=4, tokens_used=1000,
                wall_clock_seconds=30.0,
            ),
        ]

        out_path = tmp_path / "results.json"
        save_results_json(run, out_path)

        import json
        data = json.loads(out_path.read_text())
        assert data["model"] == "test-model"
        assert data["num_candidates"] == 4
        assert data["tournament_aggregate"] == 1.0
        assert data["baseline_aggregate"] == 0.5
        assert len(data["results"]) == 1
        assert data["results"][0]["slug"] == "hello"
        assert data["total_tokens"] == 1000
        assert data["tokens_per_exercise"] == 1000.0
