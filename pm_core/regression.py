"""Regression test runner.

Launches all regression test scenarios as Claude sessions in tmux windows,
polls for verdicts, manages concurrency, and produces a summary report.

Usage:
    pm qa regression [--max-parallel N] [--filter TAG] [--timeout SECS]
"""

import json
import os
import time
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pm_core.paths import configure_logger
from pm_core.loop_shared import (
    extract_verdict_from_content,
    VERDICT_TAIL_LINES,
)

_log = configure_logger("pm.regression")

# Verdicts recognised by the runner
VERDICT_PASS = "PASS"
VERDICT_NEEDS_WORK = "NEEDS_WORK"
VERDICT_INPUT_REQUIRED = "INPUT_REQUIRED"
ALL_VERDICTS = (VERDICT_PASS, VERDICT_NEEDS_WORK, VERDICT_INPUT_REQUIRED)
_KEYWORDS = ("INPUT_REQUIRED", "NEEDS_WORK", "PASS")

_POLL_INTERVAL = 5  # seconds between polls
_DEFAULT_TIMEOUT = 30 * 60  # 30 minutes per scenario
_DEFAULT_MAX_PARALLEL = 4


@dataclass
class RegressionScenario:
    """A single regression scenario to run."""
    id: str
    title: str
    description: str
    tags: list[str]
    instruction_path: str
    # Assigned at launch time
    window_name: str | None = None
    workdir: str | None = None


@dataclass
class ScenarioResult:
    """Result of a single scenario execution."""
    scenario_id: str
    title: str
    verdict: str  # PASS, NEEDS_WORK, INPUT_REQUIRED, TIMEOUT, ERROR
    duration_secs: float = 0.0
    detail: str = ""


@dataclass
class RegressionState:
    """Tracks overall regression run state."""
    run_id: str = field(default_factory=lambda: secrets.token_hex(6))
    scenarios: list[RegressionScenario] = field(default_factory=list)
    results: list[ScenarioResult] = field(default_factory=list)
    running: bool = False
    start_time: float = 0.0
    # Active scenarios currently running (index into scenarios list)
    active: list[int] = field(default_factory=list)
    # Queue of scenarios waiting to run (index into scenarios list)
    pending: list[int] = field(default_factory=list)


def load_regression_scenarios(pm_root: Path,
                              filter_tags: list[str] | None = None,
                              ) -> list[RegressionScenario]:
    """Load all regression test files, optionally filtering by tags."""
    from pm_core import qa_instructions

    items = qa_instructions.list_regression_tests(pm_root)
    scenarios = []
    for item in items:
        tags = item.get("tags") or []
        if filter_tags:
            # Include if any filter tag matches
            if not any(t in tags for t in filter_tags):
                continue
        scenarios.append(RegressionScenario(
            id=item["id"],
            title=item["title"],
            description=item.get("description", ""),
            tags=tags,
            instruction_path=item["path"],
        ))
    return scenarios


def _build_regression_prompt(scenario: RegressionScenario,
                             session_name: str | None = None) -> str:
    """Build the Claude prompt for a regression scenario."""
    tui_block = ""
    if session_name:
        from pm_core.prompt_gen import tui_section
        tui_block = tui_section(session_name)

    return f"""You are running a regression test scenario.

## Scenario: {scenario.title}

{scenario.description}

## Instruction

Read the full test procedure at: `{scenario.instruction_path}`
Follow its steps exactly.
{tui_block}
## Verdict

When you have completed all test steps, end your response with exactly one
verdict keyword on its own line:

- **PASS** — All checks passed
- **NEEDS_WORK** — Issues found (describe them above the verdict)
- **INPUT_REQUIRED** — Need human input to proceed

IMPORTANT: Always end your response with the verdict keyword on its own line.""".strip()


def _launch_scenario(scenario: RegressionScenario,
                     session: str,
                     run_id: str,
                     workdir_base: Path,
                     session_name: str | None = None) -> str | None:
    """Launch a scenario in a tmux window. Returns pane_id or None."""
    from pm_core import tmux as tmux_mod
    from pm_core.claude_launcher import build_claude_shell_cmd

    window_name = f"reg-{run_id[:6]}-{scenario.id[:20]}"
    scenario.window_name = window_name

    # Create a workdir for this scenario
    workdir = workdir_base / scenario.id
    workdir.mkdir(parents=True, exist_ok=True)
    scenario.workdir = str(workdir)

    prompt = _build_regression_prompt(scenario, session_name=session_name)
    cmd = build_claude_shell_cmd(prompt=prompt)

    # Use the repo root as cwd so Claude has access to the code
    cwd = os.getcwd()

    pane_id = tmux_mod.new_window_get_pane(session, window_name, cmd, cwd=cwd)
    _log.info("launched scenario %s in window %s (pane %s)",
              scenario.id, window_name, pane_id)
    return pane_id


def _poll_scenario(pane_id: str, prompt_text: str) -> str | None:
    """Check a scenario pane for a verdict. Returns verdict or None."""
    from pm_core import tmux as tmux_mod
    from pm_core.loop_shared import build_prompt_verdict_lines

    if not tmux_mod.pane_exists(pane_id):
        return "ERROR"  # pane died

    content = tmux_mod.capture_pane(pane_id, full_scrollback=True)
    if not content:
        return None

    prompt_lines = build_prompt_verdict_lines(prompt_text, _KEYWORDS)
    verdict = extract_verdict_from_content(
        content, ALL_VERDICTS, _KEYWORDS, prompt_lines,
        tail_lines=VERDICT_TAIL_LINES,
    )
    return verdict


def run_regression(
    pm_root: Path,
    session: str,
    max_parallel: int = _DEFAULT_MAX_PARALLEL,
    timeout: int = _DEFAULT_TIMEOUT,
    filter_tags: list[str] | None = None,
    on_update: Callable[[RegressionState], None] | None = None,
    session_name: str | None = None,
) -> RegressionState:
    """Run all regression tests, managing concurrency and polling.

    Args:
        pm_root: Path to pm/ directory.
        session: tmux session to create windows in.
        max_parallel: Max scenarios running concurrently.
        timeout: Per-scenario timeout in seconds.
        filter_tags: Only run scenarios with matching tags.
        on_update: Callback invoked on state changes.
        session_name: Base PM session name for TUI commands.

    Returns:
        Final RegressionState with all results.
    """
    from pm_core import tmux as tmux_mod

    scenarios = load_regression_scenarios(pm_root, filter_tags)
    if not scenarios:
        _log.info("no regression scenarios found")
        state = RegressionState()
        state.results = []
        return state

    state = RegressionState(
        scenarios=scenarios,
        running=True,
        start_time=time.time(),
        pending=list(range(len(scenarios))),
    )

    workdir_base = Path(os.path.expanduser(
        f"~/.pm/workdirs/regression/{state.run_id}"
    ))
    workdir_base.mkdir(parents=True, exist_ok=True)

    # Track active scenario pane IDs, prompts, and start times
    active_panes: dict[int, str] = {}  # scenario index -> pane_id
    active_prompts: dict[int, str] = {}  # scenario index -> prompt text
    active_starts: dict[int, float] = {}  # scenario index -> start time
    # Stability: require 2 consecutive polls with same verdict
    stability: dict[int, tuple[str, int]] = {}  # index -> (verdict, count)

    def _launch_next():
        """Launch pending scenarios up to max_parallel."""
        while state.pending and len(state.active) < max_parallel:
            idx = state.pending.pop(0)
            scenario = state.scenarios[idx]
            prompt = _build_regression_prompt(scenario, session_name=session_name)
            pane_id = _launch_scenario(
                scenario, session, state.run_id, workdir_base,
                session_name=session_name,
            )
            if pane_id:
                state.active.append(idx)
                active_panes[idx] = pane_id
                active_prompts[idx] = prompt
                active_starts[idx] = time.time()
                stability[idx] = ("", 0)
            else:
                state.results.append(ScenarioResult(
                    scenario_id=scenario.id,
                    title=scenario.title,
                    verdict="ERROR",
                    detail="Failed to launch tmux window",
                ))

    _launch_next()
    if on_update:
        on_update(state)

    # Poll loop
    while state.active or state.pending:
        time.sleep(_POLL_INTERVAL)

        finished = []
        for idx in list(state.active):
            scenario = state.scenarios[idx]
            pane_id = active_panes[idx]
            elapsed = time.time() - active_starts[idx]

            # Grace period: don't check for verdicts in first 30 seconds
            if elapsed < 30:
                continue

            verdict = _poll_scenario(pane_id, active_prompts[idx])

            if verdict == "ERROR":
                finished.append((idx, "ERROR", elapsed, "Pane exited unexpectedly"))
                continue

            if verdict and verdict in ALL_VERDICTS:
                prev_verdict, count = stability[idx]
                if verdict == prev_verdict:
                    count += 1
                else:
                    count = 1
                stability[idx] = (verdict, count)
                if count >= 2:
                    finished.append((idx, verdict, elapsed, ""))
                continue

            # Check timeout
            if elapsed > timeout:
                finished.append((idx, "TIMEOUT", elapsed,
                                 f"Exceeded {timeout}s timeout"))

        for idx, verdict, elapsed, detail in finished:
            scenario = state.scenarios[idx]
            state.active.remove(idx)
            del active_panes[idx]
            del active_prompts[idx]
            del active_starts[idx]
            del stability[idx]
            state.results.append(ScenarioResult(
                scenario_id=scenario.id,
                title=scenario.title,
                verdict=verdict,
                duration_secs=elapsed,
                detail=detail,
            ))
            _log.info("scenario %s: %s (%.0fs)", scenario.id, verdict, elapsed)

        # Launch more if slots freed up
        _launch_next()

        if on_update:
            on_update(state)

    state.running = False

    # Write report
    _write_report(state, workdir_base)

    return state


def _write_report(state: RegressionState, workdir: Path) -> Path:
    """Write JSON + text report to workdir. Returns report path."""
    report_path = workdir / "report.json"

    passed = sum(1 for r in state.results if r.verdict == VERDICT_PASS)
    failed = sum(1 for r in state.results
                 if r.verdict in (VERDICT_NEEDS_WORK, "ERROR", "TIMEOUT"))
    input_req = sum(1 for r in state.results
                    if r.verdict == VERDICT_INPUT_REQUIRED)
    total = len(state.results)
    elapsed = time.time() - state.start_time

    report = {
        "run_id": state.run_id,
        "total": total,
        "passed": passed,
        "failed": failed,
        "input_required": input_req,
        "elapsed_secs": round(elapsed, 1),
        "results": [
            {
                "id": r.scenario_id,
                "title": r.title,
                "verdict": r.verdict,
                "duration_secs": round(r.duration_secs, 1),
                "detail": r.detail,
            }
            for r in state.results
        ],
    }
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    # Also write human-readable text report
    txt_path = workdir / "report.txt"
    lines = [
        f"Regression Test Report — {state.run_id}",
        f"{'=' * 50}",
        f"Total: {total}  |  Pass: {passed}  |  Fail: {failed}"
        + (f"  |  Input Required: {input_req}" if input_req else ""),
        f"Elapsed: {elapsed:.0f}s",
        "",
    ]
    for r in state.results:
        status = "✓" if r.verdict == VERDICT_PASS else "✗"
        lines.append(f"  {status} {r.scenario_id}: {r.verdict} ({r.duration_secs:.0f}s)")
        if r.detail:
            lines.append(f"    {r.detail}")
    lines.append("")
    txt_path.write_text("\n".join(lines))

    _log.info("report written to %s", report_path)
    return report_path


def format_summary(state: RegressionState) -> str:
    """Format a human-readable summary of results."""
    passed = sum(1 for r in state.results if r.verdict == VERDICT_PASS)
    failed = sum(1 for r in state.results
                 if r.verdict in (VERDICT_NEEDS_WORK, "ERROR", "TIMEOUT"))
    input_req = sum(1 for r in state.results
                    if r.verdict == VERDICT_INPUT_REQUIRED)
    total = len(state.results)
    elapsed = time.time() - state.start_time if state.start_time else 0

    lines = [
        f"Regression results: {passed}/{total} passed"
        + (f", {failed} failed" if failed else "")
        + (f", {input_req} need input" if input_req else ""),
        f"Elapsed: {elapsed:.0f}s",
    ]

    # Show failures first
    for r in state.results:
        if r.verdict != VERDICT_PASS:
            lines.append(f"  FAIL {r.scenario_id}: {r.verdict}"
                         + (f" — {r.detail}" if r.detail else ""))

    return "\n".join(lines)
