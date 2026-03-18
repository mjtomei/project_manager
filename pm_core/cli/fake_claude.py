"""CLI command: pm fake-claude — scriptable Claude replacement for integration testing."""

import click

from pm_core.cli import cli
from pm_core.fake_claude import ALL_VERDICTS


@cli.command("fake-claude")
@click.option("--verdict", required=True,
              type=click.Choice(ALL_VERDICTS, case_sensitive=False),
              help="Verdict to emit.")
@click.option("--preamble", default=3, show_default=True,
              help="Number of filler prose lines before the verdict.")
@click.option("--delay", default=0.0, show_default=True,
              help="Seconds to sleep before writing the verdict.")
@click.option("--body", default=None,
              help="Custom text between START/END markers (block verdicts only).")
@click.option("--stream", is_flag=True, default=False,
              help="Write output character-by-character to simulate streaming.")
def fake_claude_cmd(verdict: str, preamble: int, delay: float, body: str | None,
                    stream: bool) -> None:
    """Emit a verdict for integration testing without calling the real Claude API.

    Writes N lines of realistic filler prose (--preamble), optionally sleeps
    (--delay), then emits the requested verdict.

    Single-line verdicts (PASS, PASS_WITH_SUGGESTIONS, NEEDS_WORK,
    INPUT_REQUIRED, VERIFIED) are written as a bare keyword on its own line.

    Block-style verdicts (FLAGGED, REFINED_STEPS, QA_PLAN) are written as
    a START marker, an optional body (--body), and an END marker.

    \b
    Examples:
      pm fake-claude --verdict PASS
      pm fake-claude --verdict NEEDS_WORK --preamble 5 --delay 2
      pm fake-claude --verdict FLAGGED --body "Step 1: FAILED"
      pm fake-claude --verdict QA_PLAN --preamble 0
      pm fake-claude --verdict PASS --stream
    """
    from pm_core.fake_claude import run_fake_claude
    run_fake_claude(
        verdict=verdict,
        preamble=preamble,
        delay=delay,
        body=body,
        stream=stream,
    )
