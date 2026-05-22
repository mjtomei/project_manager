"""CLI command: pm fake-claude — scriptable Claude replacement for integration testing."""

import click

from pm_core.cli import cli
from pm_core.fake_claude import ALL_VERDICT_CHOICES


@cli.group("fake-claude")
def fake_claude() -> None:
    """Scriptable Claude stand-in for integration testing.

    \b
    Subcommands:
      emit    Emit a verdict (the stand-in binary's behaviour).
      config  Manage the per-session fake-claude config that redirects a
              pm flow to the fake (set / show / clear).
    """


@fake_claude.command("emit")
@click.option("--verdict", required=True,
              type=click.Choice(ALL_VERDICT_CHOICES, case_sensitive=False),
              help="Verdict to emit; NONE runs a no-verdict session.")
@click.option("--preamble", default=3, show_default=True,
              help="Number of filler prose lines before the generated body.")
@click.option("--preamble-delay", default=0.0, show_default=True,
              help="Seconds to sleep between each preamble line.")
@click.option("--delay", default=0.0, show_default=True,
              help="Seconds to sleep immediately before writing the verdict.")
@click.option("--body", default=None,
              help="Custom text between START/END markers (block verdicts only).")
@click.option("--body-lines", default=0, show_default=True,
              help="Number of extra generated lines to emit before the verdict.")
@click.option("--body-batch", default=1, show_default=True,
              help="Lines per emission batch (used with --body-delay).")
@click.option("--body-delay", default=0.0, show_default=True,
              help="Seconds to sleep between each --body-batch chunk.")
@click.option("--stream", is_flag=True, default=False,
              help="Write output character-by-character to simulate streaming.")
@click.option("--char-delay", default=0.015, show_default=True,
              help="Per-character sleep when --stream is active (seconds).")
@click.option("--hold", type=float, default=None,
              help="Seconds to stay open after output (no-verdict sessions, "
                   "and verdict sessions when --session-id is set). Omitted "
                   "blocks until stdin closes; 0 exits immediately.")
@click.option("--session-id", default=None,
              help="Claude session id. When set, the fake also writes a "
                   "Claude-format JSONL transcript and emits the idle_prompt "
                   "hook event, then stays open.")
def emit_cmd(verdict: str, preamble: int, preamble_delay: float,
             delay: float, body: str | None,
             body_lines: int, body_batch: int, body_delay: float,
             stream: bool, char_delay: float, hold: float | None,
             session_id: str | None) -> None:
    """Emit a verdict for integration testing without calling the real Claude API.

    Output sequence: preamble lines → generated body lines (batched) →
    pre-verdict sleep → verdict block.

    Single-line verdicts (PASS, NEEDS_WORK, INPUT_REQUIRED, VERIFIED, READY,
    FINALIZE_DONE, FINALIZE_BLOCKED) are written as a bare keyword on its own
    line.

    Block-style verdicts (FLAGGED, REFINED_STEPS, REFINER_REJECT, QA_PLAN) are
    written as a START marker, an optional body (--body), and an END marker.

    NONE runs a no-verdict session (impl/watcher/merge): output but no
    verdict keyword, and the process stays open like a real interactive
    session — see --hold.

    Use --body-lines / --body-batch / --body-delay together to emit content
    in timed batches before the verdict — useful for testing that the verdict
    poller does not accept keywords from earlier prompt output while real
    output is still arriving.

    \b
    Examples:
      pm fake-claude emit --verdict PASS
      pm fake-claude emit --verdict NEEDS_WORK --preamble 5 --delay 2
      pm fake-claude emit --verdict FLAGGED --body "Step 1: FAILED"
      pm fake-claude emit --verdict QA_PLAN --preamble 0
      pm fake-claude emit --verdict PASS --stream --char-delay 0.005
      pm fake-claude emit --verdict PASS --body-lines 20 --body-batch 5 --body-delay 1
    """
    from pm_core.fake_claude import run_fake_claude
    run_fake_claude(
        verdict=verdict,
        preamble=preamble,
        preamble_delay=preamble_delay,
        delay=delay,
        body=body,
        body_lines=body_lines,
        body_batch=body_batch,
        body_delay=body_delay,
        stream=stream,
        char_delay=char_delay,
        hold=hold,
        session_id=session_id,
    )


@fake_claude.group("config")
def config() -> None:
    """Manage the per-session fake-claude config.

    The config lives at ``~/.pm/sessions/<tag>/fake-claude`` and maps each
    session type to the verdict(s) it should emit. When present, pm flows for
    that session run the fake instead of real Claude; when absent, real Claude
    is used. See ``tests/fixtures/fake_claude/example-config.json`` for a
    reference to start from.
    """


def _resolve_tag(tag: str | None) -> str:
    """Return *tag* or the current session's tag, erroring if neither resolves."""
    from pm_core.paths import get_session_tag
    resolved = tag or get_session_tag()
    if not resolved:
        raise click.ClickException(
            "No session tag: run this inside a pm session or pass --tag.")
    return resolved


@config.command("set")
@click.argument("config_json", required=False)
@click.option("--file", "-f", "file_path", type=click.Path(exists=True, dir_okay=False),
              help="Read the config JSON from this file instead of an argument.")
@click.option("--tag", "-t", default=None,
              help="Session tag to write for (default: current session).")
def config_set_cmd(config_json: str | None, file_path: str | None,
                   tag: str | None) -> None:
    """Validate and write a fake-claude config for a session.

    The JSON may be passed inline as the argument, via --file, or on stdin
    (precedence in that order). Verdict/session-type pairings are validated
    against the catalogue; invalid pairings are reported and nothing is written.

    \b
    Examples:
      pm fake-claude config set '{"_all": {}, "review": {"verdicts": ["PASS"]}}'
      pm fake-claude config set --file cfg.json
      pm fake-claude config set < cfg.json
    """
    import json
    from pathlib import Path
    from pm_core.paths import set_fake_claude_config

    if config_json is not None:
        raw = config_json
        source = "argument"
    elif file_path is not None:
        raw = Path(file_path).read_text()
        source = file_path
    else:
        if click.get_text_stream("stdin").isatty():
            raise click.ClickException(
                "No config given: pass JSON as an argument, --file, or on stdin.")
        raw = click.get_text_stream("stdin").read()
        source = "stdin"

    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        raise click.ClickException(f"Invalid JSON from {source}: {e}")
    if not isinstance(cfg, dict):
        raise click.ClickException("Config must be a JSON object (mapping).")

    resolved = _resolve_tag(tag)
    try:
        set_fake_claude_config(resolved, cfg)
    except ValueError as e:
        raise click.ClickException(str(e))
    click.echo(f"Wrote fake-claude config for session {resolved!r}.")


@config.command("show")
@click.option("--tag", "-t", default=None,
              help="Session tag to read (default: current session).")
def config_show_cmd(tag: str | None) -> None:
    """Print the fake-claude config for a session (or note its absence)."""
    import json
    from pm_core.paths import fake_claude_config

    resolved = _resolve_tag(tag)
    cfg = fake_claude_config(resolved)
    if cfg is None:
        click.echo(f"No fake-claude config for session {resolved!r} "
                   "(flows use real Claude).")
        return
    click.echo(json.dumps(cfg, indent=2))


@config.command("clear")
@click.option("--tag", "-t", default=None,
              help="Session tag to clear (default: current session).")
def config_clear_cmd(tag: str | None) -> None:
    """Remove the fake-claude config for a session (flows revert to real Claude)."""
    from pm_core.paths import clear_fake_claude

    resolved = _resolve_tag(tag)
    clear_fake_claude(resolved)
    click.echo(f"Cleared fake-claude config for session {resolved!r}.")
