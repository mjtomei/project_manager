"""Benchmark orchestrator with tournament selection.

Wires together the full pipeline: for each exercise, generate tests from the
description, generate N candidate solutions, score each candidate against the
generated tests, pick the best, then score the best against reference tests.

Compares tournament selection against a single-pass baseline (N=1, reference
tests only) and collects cost metrics.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.bench.exercises import Exercise, load_exercises
from pm_core.bench.executor import ScoreResult, execute_tests
from pm_core.bench.runner import Runner
from pm_core.bench.solve import Candidate, generate_candidates
from pm_core.bench.test_gen import generate_tests


@dataclass
class ExerciseResult:
    """Result of running the benchmark on a single exercise."""

    language: str
    slug: str

    # Tournament: gen tests → gen N candidates → score → pick best → reference score
    tournament_score: float = 0.0
    tournament_best_gen_score: float = 0.0
    num_candidates: int = 0

    # Baseline: single-pass, N=1, scored against reference tests
    baseline_score: float = 0.0

    # Generated test code (stored for downstream analysis, e.g. pr-019)
    generated_test_code: str = ""

    # Cost
    tokens_used: int = 0
    wall_clock_seconds: float = 0.0

    error: str | None = None


@dataclass
class BenchmarkRun:
    """Full benchmark run results."""

    model: str
    num_candidates: int
    languages: list[str]
    results: list[ExerciseResult] = field(default_factory=list)
    total_tokens: int = 0
    total_wall_clock_seconds: float = 0.0

    @property
    def tournament_aggregate(self) -> float:
        scored = [r for r in self.results if r.error is None]
        if not scored:
            return 0.0
        return sum(r.tournament_score for r in scored) / len(scored)

    @property
    def baseline_aggregate(self) -> float:
        scored = [r for r in self.results if r.error is None]
        if not scored:
            return 0.0
        return sum(r.baseline_score for r in scored) / len(scored)

    @property
    def num_exercises(self) -> int:
        return len(self.results)

    @property
    def num_errors(self) -> int:
        return sum(1 for r in self.results if r.error is not None)

    def tokens_per_exercise(self) -> float:
        if not self.results:
            return 0.0
        return self.total_tokens / len(self.results)

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "model": self.model,
            "num_candidates": self.num_candidates,
            "languages": self.languages,
            "tournament_aggregate": self.tournament_aggregate,
            "baseline_aggregate": self.baseline_aggregate,
            "total_tokens": self.total_tokens,
            "total_wall_clock_seconds": self.total_wall_clock_seconds,
            "tokens_per_exercise": self.tokens_per_exercise(),
            "num_exercises": self.num_exercises,
            "num_errors": self.num_errors,
            "results": [
                {
                    "language": r.language,
                    "slug": r.slug,
                    "tournament_score": r.tournament_score,
                    "tournament_best_gen_score": r.tournament_best_gen_score,
                    "baseline_score": r.baseline_score,
                    "num_candidates": r.num_candidates,
                    "generated_test_code": r.generated_test_code,
                    "tokens_used": r.tokens_used,
                    "wall_clock_seconds": r.wall_clock_seconds,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


def run_exercise_tournament(
    exercise: Exercise,
    runner: Runner,
    model: str,
    num_candidates: int,
    *,
    progress_callback: Callable[[str], None] | None = None,
) -> ExerciseResult:
    """Run the full tournament pipeline on a single exercise.

    Steps:
    1. Generate tests from the description (not reference tests)
    2. Generate N candidate solutions
    3. Score each candidate against the generated tests
    4. Pick the best candidate (highest score on generated tests)
    5. Score the best candidate against reference tests → tournament score

    Also runs a single-pass baseline (N=1, reference tests only) for comparison.
    """
    result = ExerciseResult(
        language=exercise.language,
        slug=exercise.slug,
        num_candidates=num_candidates,
    )

    start = time.monotonic()
    tokens_before = runner.metrics.total_tokens

    try:
        # Step 1: Generate tests from description
        if progress_callback:
            progress_callback("generating tests")
        gen_test_code, _test_results = generate_tests(
            exercise, runner, model, num_variants=3
        )
        result.generated_test_code = gen_test_code

        # Step 2: Generate N candidate solutions
        if progress_callback:
            progress_callback(f"generating {num_candidates} candidates")
        candidates = generate_candidates(
            exercise, runner, model,
            num_candidates=num_candidates,
            tests=gen_test_code,
        )

        # Step 3: Score each candidate against generated tests
        if progress_callback:
            progress_callback("scoring candidates")
        scored: list[tuple[Candidate, ScoreResult]] = []
        for cand in candidates:
            test_result = execute_tests(
                exercise, cand.code, gen_test_code
            )
            scored.append((cand, test_result))

        # Step 4: Pick the best candidate
        best_candidate, best_gen_result = max(scored, key=lambda x: x[1].score)
        result.tournament_best_gen_score = best_gen_result.score

        # Step 5: Score best candidate against reference tests
        if progress_callback:
            progress_callback("scoring against reference")
        ref_result = execute_tests(exercise, best_candidate.code)
        result.tournament_score = ref_result.score

        # Baseline: single pass, scored against reference tests
        if progress_callback:
            progress_callback("running baseline")
        baseline_candidates = generate_candidates(
            exercise, runner, model, num_candidates=1
        )
        baseline_result = execute_tests(exercise, baseline_candidates[0].code)
        result.baseline_score = baseline_result.score

    except ConnectionError as exc:
        result.error = f"Backend connection error: {exc}"
    except Exception as exc:
        result.error = str(exc)

    result.wall_clock_seconds = time.monotonic() - start
    result.tokens_used = runner.metrics.total_tokens - tokens_before

    return result


def run_benchmark(
    model: str,
    num_candidates: int = 8,
    *,
    languages: list[str] | None = None,
    slugs: list[str] | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> BenchmarkRun:
    """Run the full benchmark across all matching exercises.

    Args:
        model: Model name (as reported by /v1/models endpoint).
        num_candidates: Number of candidates per exercise for tournament.
        languages: Filter to these languages (default: all).
        slugs: Filter to these exercise slugs.
        progress_callback: Called with status message updates.
    """
    runner = Runner.create()

    # Validate model exists
    available = runner.list_models()
    model_ids = [m["id"] for m in available]
    if model not in model_ids:
        raise ValueError(
            f"Model '{model}' not found. Available: {', '.join(model_ids)}"
        )

    # Load exercises
    exercises = load_exercises(
        language=languages[0] if languages and len(languages) == 1 else None,
        slug=slugs[0] if slugs and len(slugs) == 1 else None,
    )

    # Apply multi-language/slug filters if needed
    if languages and len(languages) > 1:
        exercises = [e for e in exercises if e.language in languages]
    if slugs and len(slugs) > 1:
        exercises = [e for e in exercises if e.slug in slugs]

    if not exercises:
        raise ValueError("No exercises found matching the given filters.")

    langs_used = sorted(set(e.language for e in exercises))

    run = BenchmarkRun(
        model=model,
        num_candidates=num_candidates,
        languages=langs_used,
    )

    for i, exercise in enumerate(exercises):
        def _progress(msg: str, _ex=exercise, _i=i):
            if progress_callback:
                progress_callback(
                    f"[{_i + 1}/{len(exercises)}] {_ex.language}/{_ex.slug}: {msg}"
                )

        _progress("starting")
        ex_result = run_exercise_tournament(
            exercise, runner, model, num_candidates,
            progress_callback=_progress,
        )
        run.results.append(ex_result)

    run.total_tokens = runner.metrics.total_tokens
    run.total_wall_clock_seconds = runner.metrics.total_wall_clock_seconds

    return run


def format_results_table(run: BenchmarkRun) -> str:
    """Format benchmark results as a terminal table."""
    lines: list[str] = []

    lines.append(f"Benchmark: {run.model} | N={run.num_candidates} | "
                 f"Languages: {', '.join(run.languages)}")
    lines.append("=" * 80)
    lines.append("")

    header = (f"{'Language':<12} {'Exercise':<30} {'Tournament':>10} "
              f"{'Baseline':>10} {'Delta':>8} {'Tokens':>8}")
    lines.append(header)
    lines.append("-" * 80)

    by_lang: dict[str, list[ExerciseResult]] = {}
    for r in run.results:
        by_lang.setdefault(r.language, []).append(r)

    for lang in sorted(by_lang):
        for r in by_lang[lang]:
            if r.error:
                status = f"{'ERROR':<10} {'':>10} {'':>8} {r.tokens_used:>8}"
                lines.append(f"{r.language:<12} {r.slug:<30} {status}")
            else:
                delta = r.tournament_score - r.baseline_score
                delta_str = f"{delta:+.0%}"
                lines.append(
                    f"{r.language:<12} {r.slug:<30} "
                    f"{r.tournament_score:>9.0%} {r.baseline_score:>10.0%} "
                    f"{delta_str:>8} {r.tokens_used:>8}"
                )
        lines.append("")

    lines.append("-" * 80)
    scored = [r for r in run.results if r.error is None]
    if scored:
        agg_tourn = sum(r.tournament_score for r in scored) / len(scored)
        agg_base = sum(r.baseline_score for r in scored) / len(scored)
        agg_delta = agg_tourn - agg_base
        lines.append(
            f"{'AGGREGATE':<12} {f'{len(scored)} exercises':<30} "
            f"{agg_tourn:>9.0%} {agg_base:>10.0%} {agg_delta:>+7.0%}"
        )
    if run.num_errors > 0:
        lines.append(f"  ({run.num_errors} exercises had errors)")

    lines.append("")
    lines.append(f"Total tokens: {run.total_tokens:,}")
    lines.append(f"Total time:   {run.total_wall_clock_seconds:.1f}s")
    lines.append(f"Tokens/exercise: {run.tokens_per_exercise():,.0f}")

    return "\n".join(lines)


def save_results_json(run: BenchmarkRun, path: Path) -> None:
    """Save benchmark results to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run.to_dict(), indent=2))
