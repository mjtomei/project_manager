"""Tests for bench orchestrator — tournament selection and result formatting."""

from pathlib import Path

import pytest

from pm_core.bench.orchestrator import (
    BenchmarkRun,
    ExerciseResult,
    format_results_table,
    save_results_json,
)


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
                           tokens_used=500, wall_clock_seconds=5.0),
        ]
        d = run.to_dict()
        assert d["schema_version"] == 1
        assert d["model"] == "test"
        assert d["num_candidates"] == 4
        assert d["total_tokens"] == 1000
        assert len(d["results"]) == 1
        assert d["results"][0]["slug"] == "hello"
        assert d["results"][0]["generated_test_code"] == "def test_hello(): pass"


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
