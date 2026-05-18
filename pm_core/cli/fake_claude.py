"""CLI command: pm fake-claude — scriptable Claude replacement for integration testing."""

import click

from pm_core.cli import cli
from pm_core.fake_claude import ALL_VERDICT_CHOICES


@cli.command("fake-claude")
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
def fake_claude_cmd(verdict: str, preamble: int, preamble_delay: float,
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
      pm fake-claude --verdict PASS
      pm fake-claude --verdict NEEDS_WORK --preamble 5 --delay 2
      pm fake-claude --verdict FLAGGED --body "Step 1: FAILED"
      pm fake-claude --verdict QA_PLAN --preamble 0
      pm fake-claude --verdict PASS --stream --char-delay 0.005
      pm fake-claude --verdict PASS --body-lines 20 --body-batch 5 --body-delay 1
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
