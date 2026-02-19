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
    from pm_core.bench.runner import Runner, _get_server_url, _probe_health

    if url:
        if not _probe_health(url):
            click.echo(f"Cannot reach server at {url}")
            raise SystemExit(1)
        from pm_core.bench.runner import list_models
        models = list_models(url)
        click.echo(f"Server: {url}")
    else:
        runner = Runner.create()
        models = runner.list_models()
        click.echo(f"Backend: {runner.backend.value}")
        click.echo(f"Server:  {runner.base_url}")

    click.echo(f"Models:  {len(models)}")
    for m in models:
        click.echo(f"  - {m['id']}")


@bench.command("exercises")
@click.option("--language", "-l", default=None, help="Filter by language")
def bench_exercises(language):
    """List available benchmark exercises."""
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
def bench_run(model, candidates, languages, exercise_filter, output_path):
    """Run benchmark with tournament selection.

    MODEL is the model name as reported by the backend's /v1/models endpoint.
    """
    from pm_core.bench.orchestrator import (
        format_results_table,
        run_benchmark,
        save_results_json,
    )

    click.echo(f"Starting benchmark: model={model}, N={candidates}")

    def on_progress(msg):
        click.echo(f"  {msg}")

    run = run_benchmark(
        model,
        num_candidates=candidates,
        languages=list(languages) if languages else None,
        slugs=[exercise_filter] if exercise_filter else None,
        progress_callback=on_progress,
    )

    click.echo("")
    click.echo(format_results_table(run))

    if output_path:
        out = Path(output_path)
    else:
        out = Path(f"bench-{model}-n{candidates}.json")

    save_results_json(run, out)
    click.echo(f"\nResults saved to {out}")
