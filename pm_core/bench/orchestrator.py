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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from pm_core.bench.exercises import Exercise, load_exercises
from pm_core.bench.executor import ScoreResult, execute_stdin_stdout, execute_tests
from pm_core.bench.runner import Runner
from pm_core.bench.solve import Candidate, HyperParams, generate_candidates
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

    # Cost — separated so pr-018 can analyze tournament overhead independently
    tournament_tokens: int = 0
    baseline_tokens: int = 0
    tokens_used: int = 0  # total (tournament + baseline)
    wall_clock_seconds: float = 0.0

    error: str | None = None


@dataclass
class BenchmarkRun:
    """Full benchmark run results."""

    model: str
    num_candidates: int
    languages: list[str]
    source: str = "polyglot"  # "polyglot" or "livecodebench"
    hyper: HyperParams | None = None
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
        hyper_dict = None
        if self.hyper:
            hyper_dict = {
                "variant": self.hyper.variant,
                "temperature": self.hyper.temperature,
                "chain": self.hyper.chain,
                "test_subset_size": self.hyper.test_subset_size,
            }
        return {
            "schema_version": 3,
            "source": self.source,
            "model": self.model,
            "num_candidates": self.num_candidates,
            "languages": self.languages,
            "hyperparams": hyper_dict,
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
                    "tournament_tokens": r.tournament_tokens,
                    "baseline_tokens": r.baseline_tokens,
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
    hyper: HyperParams | None = None,
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

    def _sum_tokens(gen_results: list) -> int:
        """Sum total_tokens from GenerationResult or Candidate objects."""
        total = 0
        for r in gen_results:
            stats = getattr(r, "stats", None) or getattr(
                getattr(r, "generation_result", None), "stats", None
            )
            if stats:
                total += stats.total_tokens
        return total

    is_stdin = exercise.source == "livecodebench"

    try:
        if is_stdin:
            # Stdin/stdout path: no test generation, score directly
            # Step 1: Generate N candidate solutions
            if progress_callback:
                progress_callback(f"generating {num_candidates} candidates")
            candidates = generate_candidates(
                exercise, runner, model,
                num_candidates=num_candidates,
                hyper=hyper,
            )

            # Step 2: Score each candidate against stdin/stdout tests (parallel)
            if progress_callback:
                progress_callback("scoring candidates (stdin/stdout)")
            with ThreadPoolExecutor() as pool:
                futures = [
                    pool.submit(execute_stdin_stdout, exercise, cand.code)
                    for cand in candidates
                ]
                scored: list[tuple[Candidate, ScoreResult]] = [
                    (cand, f.result())
                    for cand, f in zip(candidates, futures)
                ]

            # Step 3: Pick the best candidate
            best_candidate, best_result = max(scored, key=lambda x: x[1].score)
            result.tournament_best_gen_score = best_result.score
            result.tournament_score = best_result.score

            result.tournament_tokens = _sum_tokens(candidates)

            # Baseline: single pass
            if progress_callback:
                progress_callback("running baseline")
            baseline_candidates = generate_candidates(
                exercise, runner, model, num_candidates=1
            )
            baseline_result = execute_stdin_stdout(
                exercise, baseline_candidates[0].code
            )
            result.baseline_score = baseline_result.score
            result.baseline_tokens = _sum_tokens(baseline_candidates)
        else:
            # Standard polyglot path: generate tests → tournament → reference tests
            # Step 1: Generate tests from description
            if progress_callback:
                progress_callback("generating tests")
            gen_test_code, test_results = generate_tests(
                exercise, runner, model, num_variants=3,
                chain=hyper.chain if hyper else False,
            )
            result.generated_test_code = gen_test_code

            # Step 2: Generate N candidate solutions
            if progress_callback:
                progress_callback(f"generating {num_candidates} candidates")
            candidates = generate_candidates(
                exercise, runner, model,
                num_candidates=num_candidates,
                tests=gen_test_code,
                hyper=hyper,
            )

            # Step 3: Score each candidate against generated tests (parallel)
            if progress_callback:
                progress_callback("scoring candidates")
            with ThreadPoolExecutor() as pool:
                futures = [
                    pool.submit(execute_tests, exercise, cand.code, gen_test_code)
                    for cand in candidates
                ]
                scored = [
                    (cand, f.result())
                    for cand, f in zip(candidates, futures)
                ]

            # Step 4: Pick the best candidate
            best_candidate, best_gen_result = max(scored, key=lambda x: x[1].score)
            result.tournament_best_gen_score = best_gen_result.score

            # Step 5: Score best candidate against reference tests
            if progress_callback:
                progress_callback("scoring against reference")
            ref_result = execute_tests(exercise, best_candidate.code)
            result.tournament_score = ref_result.score

            result.tournament_tokens = _sum_tokens(test_results) + _sum_tokens(candidates)

            # Baseline: single pass, scored against reference tests
            if progress_callback:
                progress_callback("running baseline")
            baseline_candidates = generate_candidates(
                exercise, runner, model, num_candidates=1
            )
            baseline_result = execute_tests(exercise, baseline_candidates[0].code)
            result.baseline_score = baseline_result.score
            result.baseline_tokens = _sum_tokens(baseline_candidates)

    except ConnectionError as exc:
        result.error = f"Backend connection error: {exc}"
    except (OSError, ValueError, RuntimeError) as exc:
        result.error = str(exc)

    result.wall_clock_seconds = time.monotonic() - start
    result.tokens_used = result.tournament_tokens + result.baseline_tokens

    return result


def run_benchmark(
    model: str,
    num_candidates: int = 8,
    *,
    source: str = "polyglot",
    languages: list[str] | None = None,
    slugs: list[str] | None = None,
    difficulty: str | None = None,
    hyper: HyperParams | None = None,
    parallel: int = 1,
    progress_callback: Callable[[str], None] | None = None,
) -> BenchmarkRun:
    """Run the full benchmark across all matching exercises.

    Args:
        model: Model name (as reported by /v1/models endpoint).
        num_candidates: Number of candidates per exercise for tournament.
        source: Exercise source — "polyglot" or "livecodebench".
        languages: Filter to these languages (default: all).
        slugs: Filter to these exercise slugs.
        difficulty: Filter by difficulty (livecodebench only): easy/medium/hard.
        parallel: Number of exercises to run concurrently (default: 1).
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

    # Load exercises from the requested source
    if source == "livecodebench":
        from pm_core.bench.exercises_livecodebench import (
            load_exercises as load_lcb,
        )

        try:
            exercises = load_lcb(difficulty=difficulty)
        except FileNotFoundError:
            raise FileNotFoundError(
                "LiveCodeBench cache not found. "
                "Run `pm bench exercises --source livecodebench` first."
            ) from None
    else:
        try:
            exercises = load_exercises()
        except FileNotFoundError:
            raise FileNotFoundError(
                "Exercise cache not found. "
                "Run `pm bench exercises` first to download."
            ) from None

    if languages:
        lang_set = set(languages)
        exercises = [e for e in exercises if e.language in lang_set]
    if slugs:
        exercises = [
            e for e in exercises
            if any(s.lower() in e.slug.lower() for s in slugs)
        ]

    if not exercises:
        filter_desc = []
        if languages:
            filter_desc.append(f"languages={','.join(languages)}")
        if slugs:
            filter_desc.append(f"slugs={','.join(slugs)}")
        if difficulty:
            filter_desc.append(f"difficulty={difficulty}")
        raise ValueError(
            f"No exercises found matching filters: {', '.join(filter_desc)}. "
            "Run `pm bench exercises` to see available exercises."
        )

    langs_used = sorted(set(e.language for e in exercises))

    run = BenchmarkRun(
        model=model,
        num_candidates=num_candidates,
        languages=langs_used,
        source=source,
        hyper=hyper,
    )

    bench_start = time.monotonic()
    total = len(exercises)

    def _run_one(i: int, exercise: Exercise) -> ExerciseResult:
        def _progress(msg: str, _ex=exercise, _i=i):
            if progress_callback:
                progress_callback(
                    f"[{_i + 1}/{total}] {_ex.language}/{_ex.slug}: {msg}"
                )

        _progress("starting")
        ex_result = run_exercise_tournament(
            exercise, runner, model, num_candidates,
            hyper=hyper,
            progress_callback=_progress,
        )

        # Print intermediate result
        if progress_callback:
            if ex_result.error:
                _progress(f"ERROR — {ex_result.error}")
            else:
                delta = ex_result.tournament_score - ex_result.baseline_score
                _progress(
                    f"tournament={ex_result.tournament_score:.0%} "
                    f"baseline={ex_result.baseline_score:.0%} "
                    f"delta={delta:+.0%}"
                )

        return ex_result

    if parallel > 1:
        # Run exercises in parallel — vLLM continuous batching handles
        # concurrent requests, so this improves GPU utilization even
        # when individual exercises use chain mode (sequential generation).
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures = [
                pool.submit(_run_one, i, ex)
                for i, ex in enumerate(exercises)
            ]
            for future in futures:
                run.results.append(future.result())
    else:
        for i, exercise in enumerate(exercises):
            run.results.append(_run_one(i, exercise))

    run.total_tokens = runner.metrics.total_tokens
    run.total_wall_clock_seconds = time.monotonic() - bench_start

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
        agg_delta = run.tournament_aggregate - run.baseline_aggregate
        lines.append(
            f"{'AGGREGATE':<12} {f'{len(scored)} exercises':<30} "
            f"{run.tournament_aggregate:>9.0%} {run.baseline_aggregate:>10.0%} "
            f"{agg_delta:>+7.0%}"
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
