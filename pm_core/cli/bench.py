"""Bench commands for the pm CLI.

Registers the ``bench`` group for running coding benchmarks with
tournament selection using local LLM inference.
"""

from pathlib import Path

import click

from pm_core.cli import cli


@cli.group()
def bench():
    """Run coding benchmarks with tournament selection."""


@bench.command("models")
@click.option("--url", default=None, help="Override server URL (default: auto-detect)")
def bench_models(url):
    """List models available on the local inference backend."""
    from pm_core.bench.runner import Runner

    runner = Runner.create(base_url=url) if url else Runner.create()
    if not runner.health_check():
        click.echo(f"Cannot reach server at {runner.base_url}")
        raise SystemExit(1)
    models = runner.list_models()
    if not url:
        click.echo(f"Backend: {runner.backend.value}")
    click.echo(f"Server:  {runner.base_url}")

    click.echo(f"Models:  {len(models)}")
    for m in models:
        click.echo(f"  - {m['id']}")


@bench.command("exercises")
@click.option("--language", "-l", default=None, help="Filter by language")
@click.option("--source", type=click.Choice(["exercism", "bigcodebench"]),
              default="exercism", help="Exercise source")
@click.option("--hard", is_flag=True, default=False,
              help="BigCodeBench: use the 148-problem hard subset")
@click.option("--mode", type=click.Choice(["complete", "instruct"]),
              default="instruct", help="BigCodeBench: prompt mode")
def bench_exercises(language, source, hard, mode):
    """List available benchmark exercises."""
    if source == "bigcodebench":
        from pm_core.bench.exercises_bigcodebench import (
            download_dataset,
            get_all_required_libs,
            load_bigcodebench_exercises,
        )

        download_dataset(hard=hard)
        if hard:
            download_dataset(hard=False, quiet=True)
        exercises = load_bigcodebench_exercises(hard_only=hard, mode=mode)

        click.echo(f"Source: BigCodeBench ({'hard' if hard else 'full'}, {mode} mode)")
        click.echo(f"Total exercises: {len(exercises)}")

        libs = get_all_required_libs(hard_only=hard)
        if libs:
            click.echo(f"\nRequired libraries ({len(libs)}):")
            for lib in sorted(libs):
                click.echo(f"  {lib}")
    else:
        from pm_core.bench.exercises import sync_exercises, load_exercises

        sync_exercises()
        exercises = load_exercises(language=language)

        by_lang: dict[str, int] = {}
        for ex in exercises:
            by_lang[ex.language] = by_lang.get(ex.language, 0) + 1

        click.echo(f"Total exercises: {len(exercises)}")
        for lang in sorted(by_lang):
            click.echo(f"  {lang}: {by_lang[lang]}")

        if language:
            click.echo("")
            for ex in exercises:
                click.echo(f"  {ex.slug}")


@bench.command("run")
@click.argument("model")
@click.option("-n", "--candidates", default=8, help="Candidates per exercise")
@click.option("-l", "--language", "languages", multiple=True, help="Filter languages")
@click.option("-e", "--exercise", "exercise_filter", default=None,
              help="Filter exercises by slug substring")
@click.option("-o", "--output", "output_path", default=None,
              help="Output JSON file path")
@click.option("--variant", type=click.Choice(["direct", "chain_of_thought", "test_driven"]),
              default=None, help="Lock all candidates to one prompt variant")
@click.option("--temperature", type=float, default=None,
              help="Lock all candidates to one temperature (0.0-2.0)")
@click.option("--chain", is_flag=True, default=False,
              help="Generate sequentially; each candidate sees prior solutions")
@click.option("--test-subsets", type=int, default=None,
              help="Each candidate gets a random sample of N test functions")
@click.option("-j", "--parallel", type=click.IntRange(min=1), default=1,
              help="Number of exercises to run concurrently (default: 1)")
@click.option("--source", type=click.Choice(["exercism", "bigcodebench"]),
              default="exercism", help="Exercise source")
@click.option("--hard", is_flag=True, default=False,
              help="BigCodeBench: use the 148-problem hard subset")
@click.option("--mode", type=click.Choice(["complete", "instruct"]),
              default="instruct", help="BigCodeBench: prompt mode")
def bench_run(model, candidates, languages, exercise_filter, output_path,
              variant, temperature, chain, test_subsets, parallel,
              source, hard, mode):
    """Run benchmark with tournament selection.

    MODEL is the model name as reported by the backend's /v1/models endpoint.
    """
    from pm_core.bench.orchestrator import (
        format_results_table,
        run_benchmark,
        save_results_json,
    )
    from pm_core.bench.solve import HyperParams

    # Build and validate hyperparams
    hyper = None
    if any(v is not None for v in (variant, temperature, test_subsets)) or chain:
        hyper = HyperParams(
            variant=variant,
            temperature=temperature,
            chain=chain,
            test_subset_size=test_subsets,
        )
        hyper.validate()

        parts = []
        if variant:
            parts.append(f"variant={variant}")
        if temperature is not None:
            parts.append(f"temperature={temperature}")
        if chain:
            parts.append("chain=on")
        if test_subsets:
            parts.append(f"test_subsets={test_subsets}")
        click.echo(f"Hyperparams: {', '.join(parts)}")

    # Load exercises from the selected source
    loaded_exercises = None
    if source == "bigcodebench":
        from pm_core.bench.exercises_bigcodebench import load_bigcodebench_exercises

        source_desc = f"bigcodebench-{'hard' if hard else 'full'} ({mode})"
        click.echo(f"Source: {source_desc}")
        loaded_exercises = load_bigcodebench_exercises(
            hard_only=hard, mode=mode,
            slug=exercise_filter,
        )
        # BigCodeBench is python-only; don't pass exercise_filter again
        exercise_filter = None

    click.echo(f"Starting benchmark: model={model}, N={candidates}")

    def on_progress(msg):
        print(f"  {msg}", flush=True)

    run = run_benchmark(
        model,
        num_candidates=candidates,
        exercises=loaded_exercises,
        languages=list(languages) if languages else None,
        slugs=[exercise_filter] if exercise_filter else None,
        hyper=hyper,
        parallel=parallel,
        progress_callback=on_progress,
    )

    click.echo("")
    click.echo(format_results_table(run))

    if output_path:
        out = Path(output_path)
        save_results_json(run, out)
        click.echo(f"\nResults saved to {out}")
