"""pm log — inspect the session log file."""

import re
import sys

import click

from pm_core.cli import cli
from pm_core.paths import command_log_file


@cli.group("log", invoke_without_command=True)
@click.pass_context
def log_group(ctx):
    """Tail / search the pm session log.

    With no subcommand, follows the log in real time (like tail -f).
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(log_tail)


# -- pm log (default): live tail -------------------------------------------

@log_group.command("tail")
@click.option("-n", "--lines", default=20, help="Number of initial lines to show")
@click.option("--source", default=None, help="Filter to a specific source prefix")
def log_tail(lines: int, source: str | None):
    """Follow the session log in real time (tail -f)."""
    import subprocess

    log_path = command_log_file()
    if not log_path.exists():
        click.echo(f"No log file yet: {log_path}", err=True)
        raise SystemExit(1)

    if source is None:
        # Simple case: just exec tail -f
        try:
            proc = subprocess.Popen(
                ["tail", "-n", str(lines), "-f", str(log_path)],
                stdout=sys.stdout, stderr=sys.stderr,
            )
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
        return

    # Filtered follow: read existing lines then poll
    _tail_filtered(log_path, lines, source)


def _tail_filtered(log_path, initial_lines: int, source: str):
    """Follow a log file, only printing lines matching [source]."""
    import time

    bracket = f"[{source}]"
    # Print last N matching lines from existing content
    try:
        all_lines = log_path.read_text().splitlines()
    except OSError:
        all_lines = []
    matching = [l for l in all_lines if bracket in l]
    for line in matching[-initial_lines:]:
        click.echo(line)

    # Follow new lines
    try:
        with open(log_path) as f:
            # Seek to end
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    if bracket in line:
                        click.echo(line, nl=False)
                else:
                    time.sleep(0.1)
    except KeyboardInterrupt:
        pass


# -- pm log show ------------------------------------------------------------

@log_group.command("show")
@click.option("-n", "--lines", default=0, help="Last N lines (0 = all)")
@click.option("--source", default=None, help="Filter to a specific source prefix")
def log_show(lines: int, source: str | None):
    """Print the session log (or last N lines)."""
    log_path = command_log_file()
    if not log_path.exists():
        click.echo(f"No log file yet: {log_path}", err=True)
        raise SystemExit(1)

    try:
        all_lines = log_path.read_text().splitlines()
    except OSError as exc:
        click.echo(f"Error reading log: {exc}", err=True)
        raise SystemExit(1)

    if source:
        bracket = f"[{source}]"
        all_lines = [l for l in all_lines if bracket in l]

    if lines > 0:
        all_lines = all_lines[-lines:]

    for line in all_lines:
        click.echo(line)


# -- pm log grep <pattern> --------------------------------------------------

@log_group.command("grep")
@click.argument("pattern")
@click.option("--source", default=None, help="Filter to a specific source prefix")
@click.option("-i", "--ignore-case", is_flag=True, help="Case-insensitive matching")
def log_grep(pattern: str, source: str | None, ignore_case: bool):
    """Search the session log with a regex pattern."""
    log_path = command_log_file()
    if not log_path.exists():
        click.echo(f"No log file yet: {log_path}", err=True)
        raise SystemExit(1)

    flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error as exc:
        click.echo(f"Invalid regex: {exc}", err=True)
        raise SystemExit(1)

    try:
        all_lines = log_path.read_text().splitlines()
    except OSError as exc:
        click.echo(f"Error reading log: {exc}", err=True)
        raise SystemExit(1)

    if source:
        bracket = f"[{source}]"
        all_lines = [l for l in all_lines if bracket in l]

    found = False
    for line in all_lines:
        if regex.search(line):
            click.echo(line)
            found = True

    if not found:
        raise SystemExit(1)


# -- pm log clear ------------------------------------------------------------

@log_group.command("clear")
@click.confirmation_option(prompt="Truncate the session log?")
def log_clear():
    """Truncate the session log file."""
    log_path = command_log_file()
    if not log_path.exists():
        click.echo("No log file to clear.")
        return
    log_path.write_text("")
    click.echo(f"Cleared {log_path}")


# -- pm log path -------------------------------------------------------------

@log_group.command("path")
def log_path_cmd():
    """Print the log file path (for piping to external tools)."""
    click.echo(command_log_file())


# -- pm log sources ----------------------------------------------------------

@log_group.command("sources")
def log_sources():
    """List all source prefixes seen in the log."""
    log_path = command_log_file()
    if not log_path.exists():
        click.echo(f"No log file yet: {log_path}", err=True)
        raise SystemExit(1)

    bracket_re = re.compile(r"^\d{2}:\d{2}:\d{2}\s+\w+\s+\[([^\]]+)\]")
    sources: set[str] = set()
    try:
        for line in log_path.read_text().splitlines():
            m = bracket_re.search(line)
            if m:
                sources.add(m.group(1))
    except OSError as exc:
        click.echo(f"Error reading log: {exc}", err=True)
        raise SystemExit(1)

    for s in sorted(sources):
        click.echo(s)
