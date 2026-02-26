"""Tests for bench orchestrator — tournament selection and result formatting."""

from pathlib import Path
from unittest import mock

import pytest

from pm_core.bench.exercises import Exercise
from pm_core.bench.executor import ScoreResult
from pm_core.bench.orchestrator import (
    BenchmarkRun,
    ExerciseResult,
    format_results_table,
    run_benchmark,
    run_exercise_tournament,
    save_results_json,
)
from pm_core.bench.runner import CostMetrics, GenerationResult, RequestStats, Runner
from pm_core.bench.solve import Candidate, HyperParams


class TestBenchmarkRun:
    def test_aggregate_scores(self):
        run = BenchmarkRun(model="test", num_candidates=8, languages=["python"])
        run.results = [
            ExerciseResult(language="python", slug="a", tournament_score=0.8, baseline_score=0.4),
            ExerciseResult(language="python", slug="b", tournament_score=1.0, baseline_score=0.6),
        ]
        assert run.tournament_aggregate == pytest.approx(0.9)
        assert run.baseline_aggregate == pytest.approx(0.5)

    def test_aggregate_ignores_errors(self):
        run = BenchmarkRun(model="test", num_candidates=8, languages=["python"])
        run.results = [
            ExerciseResult(language="python", slug="a", tournament_score=1.0, baseline_score=0.5),
            ExerciseResult(language="python", slug="b", error="failed"),
        ]
        assert run.tournament_aggregate == 1.0
        assert run.num_errors == 1

    def test_empty_run(self):
        run = BenchmarkRun(model="test", num_candidates=8, languages=[])
        assert run.tournament_aggregate == 0.0
        assert run.tokens_per_exercise() == 0.0

    def test_to_dict_roundtrip(self):
        run = BenchmarkRun(model="test", num_candidates=4, languages=["python"],
                           total_tokens=1000, total_wall_clock_seconds=10.5)
        run.results = [
            ExerciseResult(language="python", slug="hello",
                           tournament_score=0.8, baseline_score=0.4,
                           generated_test_code="def test_hello(): pass",
                           tournament_tokens=400, baseline_tokens=100,
                           tokens_used=500, wall_clock_seconds=5.0),
        ]
        d = run.to_dict()
        assert d["schema_version"] == 3
        assert d["model"] == "test"
        assert d["num_candidates"] == 4
        assert d["total_tokens"] == 1000
        assert d["hyperparams"] is None
        assert len(d["results"]) == 1
        assert d["results"][0]["slug"] == "hello"
        assert d["results"][0]["generated_test_code"] == "def test_hello(): pass"
        assert d["results"][0]["tournament_tokens"] == 400
        assert d["results"][0]["baseline_tokens"] == 100

    def test_to_dict_with_hyperparams(self):
        hyper = HyperParams(variant="direct", temperature=0.7, chain=True, test_subset_size=3)
        run = BenchmarkRun(model="test", num_candidates=4, languages=["python"],
                           hyper=hyper)
        d = run.to_dict()
        assert d["hyperparams"] == {
            "variant": "direct",
            "temperature": 0.7,
            "chain": True,
            "test_subset_size": 3,
        }


class TestFormatResultsTable:
    def test_basic_formatting(self):
        run = BenchmarkRun(model="qwen3-32b", num_candidates=8,
                           languages=["python"], total_tokens=5000,
                           total_wall_clock_seconds=30.0)
        run.results = [
            ExerciseResult(language="python", slug="hello-world",
                           tournament_score=1.0, baseline_score=0.5,
                           tokens_used=2500, num_candidates=8),
        ]
        table = format_results_table(run)
        assert "qwen3-32b" in table
        assert "hello-world" in table
        assert "AGGREGATE" in table
        assert "Total tokens: 5,000" in table

    def test_error_exercise(self):
        run = BenchmarkRun(model="m", num_candidates=8, languages=["python"])
        run.results = [
            ExerciseResult(language="python", slug="broken", error="connection failed"),
        ]
        table = format_results_table(run)
        assert "ERROR" in table
        assert "1 exercises had errors" in table


class TestSaveResultsJson:
    def test_save_and_load(self, tmp_path):
        import json
        run = BenchmarkRun(model="test", num_candidates=4, languages=["python"])
        run.results = [
            ExerciseResult(language="python", slug="hello",
                           tournament_score=0.8, baseline_score=0.4),
        ]
        out = tmp_path / "results.json"
        save_results_json(run, out)
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["model"] == "test"
        assert len(data["results"]) == 1


# ---------------------------------------------------------------------------
# run_exercise_tournament — integration with mocked runner and executor
# ---------------------------------------------------------------------------

def _make_exercise():
    return Exercise(
        language="python",
        slug="hello-world",
        description="# Hello World",
        starter_code={"hello_world.py": "def hello(): pass"},
        reference_tests={"hello_world_test.py": "def test(): pass"},
        path=Path("/tmp/fake"),
    )


def _gen_result(content="code"):
    return GenerationResult(
        content=content, model="m",
        stats=RequestStats(10, 5, 15, 0.5),
    )


class TestRunExerciseTournament:
    def test_full_pipeline(self):
        """Verify tournament flow: gen tests → gen candidates → score → pick best → reference score."""
        exercise = _make_exercise()

        runner = mock.MagicMock(spec=Runner)
        runner.metrics = CostMetrics()

        # generate_tests calls runner.generate (returns 3 test variants)
        runner.generate.return_value = [
            _gen_result("def test_1(): pass"),
            _gen_result("def test_2(): pass\ndef test_3(): pass"),  # longest → picked
            _gen_result("def test_short(): pass"),
        ]

        # generate_candidates calls runner.complete_batch (returns N candidates)
        runner.complete_batch.return_value = [
            _gen_result("solution_a"),
            _gen_result("solution_b"),
        ]

        # Mock execute_tests to return predictable scores:
        # - First 2 calls: scoring candidates against generated tests
        # - Third call: scoring best candidate against reference tests
        # - Fourth call: baseline scoring
        score_sequence = [
            ScoreResult(passed=1, total=2, score=0.5),   # candidate A vs gen tests
            ScoreResult(passed=2, total=2, score=1.0),   # candidate B vs gen tests (best)
            ScoreResult(passed=3, total=4, score=0.75),   # best (B) vs reference tests
            ScoreResult(passed=1, total=4, score=0.25),   # baseline vs reference tests
        ]

        with mock.patch("pm_core.bench.orchestrator.generate_tests") as mock_gen_tests, \
             mock.patch("pm_core.bench.orchestrator.generate_candidates") as mock_gen_cands, \
             mock.patch("pm_core.bench.orchestrator.execute_tests") as mock_exec:

            mock_gen_tests.return_value = ("def test_gen(): pass", [_gen_result()])
            mock_gen_cands.side_effect = [
                # Tournament candidates
                [
                    Candidate(code="sol_a", temperature=0.0, prompt_variant="direct",
                              model="m", generation_result=_gen_result()),
                    Candidate(code="sol_b", temperature=0.5, prompt_variant="chain_of_thought",
                              model="m", generation_result=_gen_result()),
                ],
                # Baseline candidate
                [
                    Candidate(code="sol_baseline", temperature=0.0, prompt_variant="direct",
                              model="m", generation_result=_gen_result()),
                ],
            ]
            mock_exec.side_effect = score_sequence

            result = run_exercise_tournament(exercise, runner, "m", num_candidates=2)

        assert result.error is None
        assert result.tournament_score == 0.75
        assert result.tournament_best_gen_score == 1.0
        assert result.baseline_score == 0.25
        assert result.num_candidates == 2
        assert result.generated_test_code == "def test_gen(): pass"

        # Verify best candidate (sol_b, score=1.0) was scored against reference
        ref_call = mock_exec.call_args_list[2]
        assert ref_call[0][1] == "sol_b"

        # Verify baseline was generated with num_candidates=1
        baseline_gen_call = mock_gen_cands.call_args_list[1]
        assert baseline_gen_call[1]["num_candidates"] == 1

        # Token accounting: summed from returned GenerationResult objects
        # Tournament: 1 test gen result (15 tokens) + 2 candidates (15 each) = 45
        assert result.tournament_tokens == 45
        # Baseline: 1 candidate (15 tokens) = 15
        assert result.baseline_tokens == 15
        assert result.tokens_used == 60  # tournament + baseline

    def test_connection_error_captured(self):
        exercise = _make_exercise()
        runner = mock.MagicMock(spec=Runner)
        runner.metrics = CostMetrics()

        with mock.patch("pm_core.bench.orchestrator.generate_tests",
                        side_effect=ConnectionError("refused")):
            result = run_exercise_tournament(exercise, runner, "m", num_candidates=2)

        assert result.error is not None
        assert "connection" in result.error.lower()

    def test_hyper_passed_to_tournament_not_baseline(self):
        """Hyperparams should be forwarded to tournament candidates but not baseline."""
        exercise = _make_exercise()
        runner = mock.MagicMock(spec=Runner)
        runner.metrics = CostMetrics()

        hyper = HyperParams(variant="direct", temperature=0.5)

        with mock.patch("pm_core.bench.orchestrator.generate_tests") as mock_gt, \
             mock.patch("pm_core.bench.orchestrator.generate_candidates") as mock_gc, \
             mock.patch("pm_core.bench.orchestrator.execute_tests") as mock_ex:

            mock_gt.return_value = ("test_code", [])
            mock_gc.side_effect = [
                # Tournament candidates
                [
                    Candidate(code="sol_a", temperature=0.5, prompt_variant="direct",
                              model="m", generation_result=_gen_result()),
                ],
                # Baseline candidate
                [
                    Candidate(code="sol_baseline", temperature=0.0, prompt_variant="direct",
                              model="m", generation_result=_gen_result()),
                ],
            ]
            mock_ex.return_value = ScoreResult(passed=1, total=1, score=1.0)

            run_exercise_tournament(
                exercise, runner, "m", num_candidates=1,
                hyper=hyper,
            )

        # Tournament call (first) should have hyper
        tournament_call = mock_gc.call_args_list[0]
        assert tournament_call[1]["hyper"] is hyper

        # Baseline call (second) should NOT have hyper
        baseline_call = mock_gc.call_args_list[1]
        assert baseline_call[1].get("hyper") is None

    def test_progress_callback_called(self):
        exercise = _make_exercise()
        runner = mock.MagicMock(spec=Runner)
        runner.metrics = CostMetrics()

        messages = []

        with mock.patch("pm_core.bench.orchestrator.generate_tests") as mock_gt, \
             mock.patch("pm_core.bench.orchestrator.generate_candidates") as mock_gc, \
             mock.patch("pm_core.bench.orchestrator.execute_tests") as mock_ex:

            mock_gt.return_value = ("test_code", [])
            mock_gc.return_value = [
                Candidate(code="s", temperature=0.0, prompt_variant="direct",
                          model="m", generation_result=_gen_result()),
            ]
            mock_ex.return_value = ScoreResult(passed=1, total=1, score=1.0)

            run_exercise_tournament(
                exercise, runner, "m", num_candidates=1,
                progress_callback=messages.append,
            )

        assert any("generating tests" in m for m in messages)
        assert any("scoring" in m for m in messages)


class TestRunBenchmark:
    def test_slug_filter_uses_substring_match(self):
        """Verify slugs filter uses substring matching consistently."""
        runner = mock.MagicMock(spec=Runner)
        runner.list_models.return_value = [{"id": "m"}]
        runner.metrics = CostMetrics()

        hello_ex = Exercise(
            language="python", slug="hello-world",
            description="desc", starter_code={}, reference_tests={},
            path=Path("/tmp/fake"),
        )
        leap_ex = Exercise(
            language="go", slug="leap",
            description="desc", starter_code={}, reference_tests={},
            path=Path("/tmp/fake"),
        )

        with mock.patch("pm_core.bench.orchestrator.Runner.create", return_value=runner), \
             mock.patch("pm_core.bench.orchestrator.load_exercises",
                        return_value=[hello_ex, leap_ex]), \
             mock.patch("pm_core.bench.orchestrator.run_exercise_tournament") as mock_run:
            mock_run.return_value = ExerciseResult(language="python", slug="hello-world")

            # "hello" should substring-match "hello-world"
            run = run_benchmark("m", slugs=["hello"])
            assert len(run.results) == 1

            # Multiple slugs should also substring-match
            mock_run.return_value = ExerciseResult(language="python", slug="hello-world")
            run = run_benchmark("m", slugs=["hello", "lea"])
            assert len(run.results) == 2

    def test_missing_exercise_cache_gives_friendly_error(self):
        runner = mock.MagicMock(spec=Runner)
        runner.list_models.return_value = [{"id": "m"}]

        with mock.patch("pm_core.bench.orchestrator.Runner.create", return_value=runner), \
             mock.patch("pm_core.bench.orchestrator.load_exercises",
                        side_effect=FileNotFoundError("Exercise cache not found")):
            with pytest.raises(FileNotFoundError, match="pm bench exercises"):
                run_benchmark("m")
