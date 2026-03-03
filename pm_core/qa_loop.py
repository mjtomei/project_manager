"""QA loop: planning + parallel execution of QA scenarios.

Two-phase process:
  Phase 1 — Planning: A Claude session analyzes the PR and generates
  a structured test plan.
  Phase 2 — Execution: Each scenario from the plan becomes a child
  QA session, running as parallel panes inside a single QA tmux window.

Verdicts (shared with review):
  PASS           — Scenario passed, no issues found.
  NEEDS_WORK     — Issues found (child may have committed fixes).
  INPUT_REQUIRED — Genuine ambiguity requiring human judgment.
"""

import re
import secrets
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pm_core.paths import configure_logger
from pm_core.loop_shared import (
    find_claude_pane,
    get_pm_session,
    extract_verdict_from_content,
    VERDICT_TAIL_LINES,
    VerdictStabilityTracker,
)

_log = configure_logger("pm.qa_loop")

# QA verdicts (same namespace as review)
VERDICT_PASS = "PASS"
VERDICT_NEEDS_WORK = "NEEDS_WORK"
VERDICT_INPUT_REQUIRED = "INPUT_REQUIRED"

ALL_VERDICTS = (VERDICT_PASS, VERDICT_NEEDS_WORK, VERDICT_INPUT_REQUIRED)
_QA_KEYWORDS = ("INPUT_REQUIRED", "NEEDS_WORK", "PASS")

_POLL_INTERVAL = 5
_TICK_INTERVAL = 1
_VERDICT_GRACE_PERIOD = 30  # QA sessions take a while to run
_PLANNER_TIMEOUT = 60 * 60  # seconds to wait for planner output
_PLANNER_GRACE = 15  # seconds before accepting planner completion
_DEFAULT_MAX_SCENARIOS = 0  # 0 = unlimited


def _get_max_scenarios() -> int:
    """Read qa-max-scenarios from global settings, or _DEFAULT_MAX_SCENARIOS."""
    from pm_core.paths import get_global_setting_value
    val = get_global_setting_value("qa-max-scenarios", "")
    try:
        return max(0, int(val))
    except ValueError:
        return _DEFAULT_MAX_SCENARIOS

def _tail_has_marker_on_own_line(content: str, marker: str,
                                 tail_lines: int = VERDICT_TAIL_LINES) -> bool:
    """Check if *marker* appears as the entire content of a line in the tail.

    Same whole-line matching strategy as the review loop's
    ``match_verdict()`` — the marker must be the full line (after
    stripping whitespace and markdown formatting), not a substring.
    """
    lines = content.strip().splitlines()
    tail = lines[-tail_lines:] if len(lines) > tail_lines else lines
    for line in tail:
        cleaned = re.sub(r'[*`]', '', line).strip()
        if cleaned == marker:
            return True
    return False


@dataclass
class QAScenario:
    """A single QA scenario from the test plan."""
    index: int
    title: str
    focus: str
    instruction_path: str | None = None
    steps: str = ""
    pane_id: str | None = None


@dataclass
class QALoopState:
    """Tracks the state of a running QA session."""
    pr_id: str
    running: bool = False
    stop_requested: bool = False
    loop_id: str = field(default_factory=lambda: secrets.token_hex(2))
    iteration: int = 0
    planning_phase: bool = True
    plan_output: str = ""
    scenarios: list[QAScenario] = field(default_factory=list)
    scenario_verdicts: dict[int, str] = field(default_factory=dict)
    latest_verdict: str = ""
    latest_output: str = ""
    made_changes: bool = False
    qa_workdir: str | None = None
    # Set by qa_loop_ui after the completion callback has run once
    _ui_complete_notified: bool = False


# ---------------------------------------------------------------------------
# Workdir management
# ---------------------------------------------------------------------------

def create_qa_workdir(pr_id: str, loop_id: str) -> Path:
    """Create the QA session workdir: ~/.pm/workdirs/qa/{pr_id}-{loop_id}/."""
    workdir = Path.home() / ".pm" / "workdirs" / "qa" / f"{pr_id}-{loop_id}"
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def create_scenario_workdir(qa_workdir: Path, scenario_index: int) -> Path:
    """Create an empty child subdirectory for a scenario."""
    d = qa_workdir / f"scenario-{scenario_index}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# QA window naming
# ---------------------------------------------------------------------------

def _compute_qa_window_name(pr_data: dict) -> str:
    """Compute the QA tmux window name from PR data."""
    from pm_core.cli.helpers import _pr_display_id
    display_id = _pr_display_id(pr_data)
    return f"qa-{display_id}"


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

def parse_qa_plan(output: str) -> list[QAScenario]:
    """Parse planner output into a list of QAScenarios.

    Expected format (ALL CAPS markers, no markdown):

    QA_PLAN_START

    SCENARIO 1: Scenario Title
    FOCUS: What to test
    INSTRUCTION: path/to/file.md (optional)
    STEPS: Key test steps

    SCENARIO 2: ...

    QA_PLAN_END
    """
    scenarios: list[QAScenario] = []

    # The prompt template also contains example markers, so we can't
    # rely on matching START/END pairs.  Instead, find the last
    # QA_PLAN_END and scan backwards for the real SCENARIO 1: line.
    end_m = list(re.finditer(r'QA_PLAN_END', output))
    if end_m:
        end_pos = end_m[-1].start()
        # Find the last "SCENARIO 1:" before that END marker
        s1_matches = list(re.finditer(
            r'^[ \t]*SCENARIO\s+1:', output[:end_pos], re.MULTILINE,
        ))
        start_pos = s1_matches[-1].start() if s1_matches else 0
        body = output[start_pos:end_pos]
    else:
        body = output

    # Split on SCENARIO N: lines
    chunks = re.split(r'^[ \t]*SCENARIO\s+', body, flags=re.MULTILINE)

    for chunk in chunks[1:]:  # skip preamble before first SCENARIO
        lines = chunk.strip().splitlines()
        if not lines:
            continue

        # Parse heading: "1: Scenario Title"
        heading = lines[0].strip()
        hm = re.match(r'(\d+)[:.]\s*(.+)', heading)
        if not hm:
            continue
        index = int(hm.group(1))
        title = hm.group(2).strip()

        focus = ""
        instruction_path = None
        steps = ""

        rest = "\n".join(lines[1:])

        focus_m = re.search(r'^[ \t]*FOCUS:\s*(.+)', rest, re.MULTILINE)
        if focus_m:
            focus = focus_m.group(1).strip()

        instr_m = re.search(r'^[ \t]*INSTRUCTION:\s*(.+)', rest, re.MULTILINE)
        if instr_m:
            path_str = instr_m.group(1).strip()
            if path_str.lower() not in ("none", "n/a", "-"):
                instruction_path = path_str

        # STEPS: capture everything until the next field or end of chunk
        steps_m = re.search(
            r'^[ \t]*STEPS:\s*(.+?)(?=\n[ \t]*(?:FOCUS|INSTRUCTION|SCENARIO):|\Z)',
            rest, re.MULTILINE | re.DOTALL,
        )
        if steps_m:
            steps = steps_m.group(1).strip()

        # Reject placeholder/example scenarios (e.g. from prompt template)
        _placeholder_titles = {"Scenario Title", "..."}
        if title in _placeholder_titles or title.startswith("<"):
            _log.warning("Skipping placeholder scenario %d: %r", index, title)
            continue

        scenarios.append(QAScenario(
            index=index,
            title=title,
            focus=focus or title,
            instruction_path=instruction_path,
            steps=steps,
        ))

    return scenarios


# ---------------------------------------------------------------------------
# Core orchestration
# ---------------------------------------------------------------------------

def run_qa_sync(
    state: QALoopState,
    pm_root: Path,
    pr_data: dict,
    on_update: Callable[[QALoopState], None] | None = None,
    max_scenarios: int | None = None,
) -> QALoopState:
    """Orchestrate QA planning + parallel execution (blocking).

    1. Launch planning session in QA window, poll for plan output
    2. Parse plan into scenarios
    3. Launch child panes (one per scenario) inside the QA window
    4. Poll all child panes for verdicts
    5. Aggregate verdicts, detect changes via git status
    6. Set final state

    Returns the updated state.
    """
    from pm_core import tmux as tmux_mod, prompt_gen, git_ops, store
    from pm_core import pane_layout, pane_registry
    from pm_core.claude_launcher import build_claude_shell_cmd

    state.running = True
    session = get_pm_session()
    if not session:
        _log.error("No pm session found")
        state.running = False
        state.latest_verdict = "ERROR"
        state.latest_output = "No pm session found"
        return state

    window_name = _compute_qa_window_name(pr_data)
    workdir_path = pr_data.get("workdir") or str(pm_root)

    # Create QA workdir
    if not state.qa_workdir:
        qa_wd = create_qa_workdir(state.pr_id, state.loop_id)
        state.qa_workdir = str(qa_wd)

    data = store.load(pm_root)

    def _notify():
        if on_update:
            on_update(state)

    # --- Phase 1: Planning (if no scenarios pre-loaded) ---
    if state.planning_phase and not state.scenarios:
        _log.info("QA planning phase for %s", state.pr_id)
        state.latest_output = "Planning QA scenarios..."
        _notify()

        planner_prompt = prompt_gen.generate_qa_planner_prompt(
            data, state.pr_id, session,
        )
        cmd = build_claude_shell_cmd(prompt=planner_prompt)

        # Kill any stale QA window from a previous run
        existing = tmux_mod.find_window_by_name(session, window_name)
        if existing:
            _log.info("Killing stale QA window %s", window_name)
            tmux_mod.kill_window(session, existing["index"])

        # Create QA window with planner pane
        tmux_mod.new_window(session, window_name, cmd, cwd=workdir_path)
        time.sleep(2)  # let tmux register the new window

        # Wait for the planner to finish (poll for plan output)
        planner_pane = find_claude_pane(session, window_name)
        _log.info("Planner pane: %s (window=%s)", planner_pane, window_name)
        if not planner_pane:
            _log.error("Could not find planner pane")
            state.running = False
            state.latest_verdict = "ERROR"
            state.latest_output = "Could not find planner pane"
            return state

        # Poll until the planner produces a QA Plan or exits.
        # Same strategy as the review loop's verdict detection:
        #   - Only scan the tail of the pane (last VERDICT_TAIL_LINES)
        #   - Require QA_PLAN_END to be the entire line content
        #   - Grace period: the prompt template also has QA_PLAN_END on
        #     its own line, so we wait _PLANNER_GRACE seconds for Claude
        #     to generate enough output to push the prompt out of the tail.
        plan_found = False
        deadline = time.monotonic() + _PLANNER_TIMEOUT
        poll_start = time.monotonic()
        while time.monotonic() < deadline:
            if state.stop_requested:
                break
            if not tmux_mod.pane_exists(planner_pane):
                _log.info("Planner pane exited")
                break

            content = tmux_mod.capture_pane(planner_pane, full_scrollback=True)
            elapsed = time.monotonic() - poll_start
            has_end = _tail_has_marker_on_own_line(content, "QA_PLAN_END")
            _log.info("planner poll: has_end=%s content_len=%d elapsed=%.0fs",
                      has_end, len(content), elapsed)

            if elapsed >= _PLANNER_GRACE and has_end:
                state.plan_output = content
                plan_found = True
                break

            time.sleep(5)

        if not plan_found and not state.plan_output:
            # Try capturing whatever the planner produced
            if planner_pane and tmux_mod.pane_exists(planner_pane):
                state.plan_output = tmux_mod.capture_pane(
                    planner_pane, full_scrollback=True
                )

        # Parse the plan
        if state.plan_output:
            state.scenarios = parse_qa_plan(state.plan_output)

        if not state.scenarios:
            _log.warning("Planner produced no scenarios for %s", state.pr_id)
            state.running = False
            state.latest_verdict = VERDICT_INPUT_REQUIRED
            state.latest_output = "Planner produced no parseable scenarios — needs human review"
            _notify()
            return state

        # Limit scenarios if a cap is configured
        cap = max_scenarios if max_scenarios is not None else _get_max_scenarios()
        if cap > 0 and len(state.scenarios) > cap:
            state.scenarios = state.scenarios[:cap]

        state.planning_phase = False
        state.latest_output = f"Plan: {len(state.scenarios)} scenario(s)"
        _notify()

    # --- Phase 2: Execution ---
    _log.info("QA execution phase: %d scenarios for %s",
              len(state.scenarios), state.pr_id)

    # Record HEAD sha before execution so we can detect new commits later
    pre_qa_head = None
    if workdir_path and Path(workdir_path).is_dir():
        try:
            result = git_ops.run_git(
                "rev-parse", "HEAD", cwd=workdir_path, check=False,
            )
            if result.returncode == 0:
                pre_qa_head = result.stdout.strip()
        except Exception:
            pass

    # Ensure the QA window exists and get the base pane for splitting
    win = tmux_mod.find_window_by_name(session, window_name)
    if not win:
        base_pane = tmux_mod.new_window_get_pane(
            session, window_name, "echo 'QA execution'", cwd=workdir_path,
            switch=False,
        )
    else:
        panes = tmux_mod.get_pane_indices(session, win["index"])
        base_pane = panes[0][0] if panes else None

    # Derive window ID from the base pane for registry/layout ops
    qa_win_id = None
    if base_pane:
        wid_result = subprocess.run(
            tmux_mod._tmux_cmd("display", "-t", base_pane, "-p", "#{window_id}"),
            capture_output=True, text=True,
        )
        qa_win_id = wid_result.stdout.strip() or None
        if qa_win_id:
            tmux_mod.set_shared_window_size(session, qa_win_id)

    # Launch child panes
    for scenario in state.scenarios:
        if state.stop_requested:
            break

        child_workdir = create_scenario_workdir(
            Path(state.qa_workdir), scenario.index
        )
        child_prompt = prompt_gen.generate_qa_child_prompt(
            data, state.pr_id, scenario, str(child_workdir), session,
        )
        child_cmd = build_claude_shell_cmd(prompt=child_prompt)

        # Split a new pane in the QA window
        pane_id = None
        if base_pane:
            try:
                pane_id = tmux_mod.split_pane_at(
                    base_pane, "v", child_cmd, background=True,
                )
            except Exception:
                _log.warning("Failed to split pane for scenario %d "
                             "(window may be too small for more panes)",
                             scenario.index)
        scenario.pane_id = pane_id
        _log.info("Launched scenario %d (%s) in pane %s",
                   scenario.index, scenario.title, pane_id)

        # Register pane and rebalance after each split so the next
        # split has enough room in the window.
        if pane_id and qa_win_id:
            try:
                pane_registry.register_pane(
                    session, qa_win_id, pane_id,
                    f"qa-scenario-{scenario.index}", child_cmd,
                )
                reg = pane_registry.load_registry(session)
                wdata = pane_registry.get_window_data(reg, qa_win_id)
                wdata["user_modified"] = False
                pane_registry.save_registry(session, reg)
                pane_layout.rebalance(session, qa_win_id)
            except Exception:
                _log.exception("Failed to register/rebalance scenario %d",
                               scenario.index)

    # Register planner pane too (it's still in the window)
    if base_pane and qa_win_id:
        try:
            pane_registry.register_pane(
                session, qa_win_id, base_pane, "qa-planner", "planner",
            )
            pane_layout.rebalance(session, qa_win_id)
        except Exception:
            _log.exception("Failed to register planner pane")

    state.latest_output = f"Running {len(state.scenarios)} scenario(s)..."
    _notify()

    # --- Poll all child panes for verdicts ---
    tracker = VerdictStabilityTracker()
    pending = {s.index for s in state.scenarios if s.pane_id}
    grace_start = time.monotonic()

    while pending and not state.stop_requested:
        time.sleep(_POLL_INTERVAL)

        in_grace = (time.monotonic() - grace_start) < _VERDICT_GRACE_PERIOD

        for scenario in state.scenarios:
            if scenario.index not in pending or not scenario.pane_id:
                continue

            if not tmux_mod.pane_exists(scenario.pane_id):
                # Pane exited without verdict — treat as inconclusive,
                # not as a pass.  A crashed or unexpectedly-exited pane
                # should not silently pass QA.
                _log.warning("Scenario %d pane exited without verdict",
                             scenario.index)
                state.scenario_verdicts[scenario.index] = VERDICT_INPUT_REQUIRED
                pending.discard(scenario.index)
                continue

            if in_grace:
                continue

            content = tmux_mod.capture_pane(
                scenario.pane_id, full_scrollback=True,
            )
            verdict = extract_verdict_from_content(
                content,
                verdicts=ALL_VERDICTS,
                keywords=_QA_KEYWORDS,
                log_prefix=f"qa-{scenario.index}",
            )

            key = f"qa-{state.pr_id}-{scenario.index}"
            if tracker.update(key, verdict):
                state.scenario_verdicts[scenario.index] = verdict
                pending.discard(scenario.index)
                _log.info("Scenario %d (%s) verdict: %s",
                          scenario.index, scenario.title, verdict)
                state.latest_output = (
                    f"Scenario {scenario.index} ({scenario.title}): {verdict}"
                )
                _notify()

    # --- Aggregate verdicts ---
    verdicts = list(state.scenario_verdicts.values())

    # Check for changes via git status (uncommitted files)
    if workdir_path and Path(workdir_path).is_dir():
        try:
            result = git_ops.run_git(
                "status", "--porcelain", cwd=workdir_path, check=False,
            )
            if result.stdout.strip():
                state.made_changes = True
        except Exception:
            pass

        # Check if HEAD moved since QA started (new commits by QA scenarios)
        if pre_qa_head:
            try:
                result = git_ops.run_git(
                    "rev-parse", "HEAD", cwd=workdir_path, check=False,
                )
                if result.returncode == 0 and result.stdout.strip() != pre_qa_head:
                    state.made_changes = True
            except Exception:
                pass

    # Determine overall verdict
    if VERDICT_NEEDS_WORK in verdicts or state.made_changes:
        state.latest_verdict = VERDICT_NEEDS_WORK
    elif VERDICT_INPUT_REQUIRED in verdicts:
        state.latest_verdict = VERDICT_INPUT_REQUIRED
    else:
        state.latest_verdict = VERDICT_PASS

    state.running = False
    summary_parts = []
    for s in state.scenarios:
        v = state.scenario_verdicts.get(s.index, "?")
        summary_parts.append(f"{s.title}: {v}")
    state.latest_output = f"QA complete: {state.latest_verdict} — " + "; ".join(summary_parts)
    if state.made_changes:
        state.latest_output += " [changes committed]"

    _log.info("QA complete for %s: %s (changes=%s)",
              state.pr_id, state.latest_verdict, state.made_changes)
    _notify()
    return state


def start_qa_background(
    state: QALoopState,
    pm_root: Path,
    pr_data: dict,
    on_update: Callable[[QALoopState], None] | None = None,
    max_scenarios: int | None = None,
) -> threading.Thread:
    """Start QA in a background thread. Returns the thread."""
    def _run():
        try:
            run_qa_sync(state, pm_root, pr_data, on_update, max_scenarios)
        except Exception:
            _log.exception("QA background thread crashed for %s", state.pr_id)
            state.running = False
            state.latest_verdict = "ERROR"
            state.latest_output = "QA thread crashed"
            if on_update:
                on_update(state)

    t = threading.Thread(target=_run, daemon=True, name=f"qa-{state.pr_id}")
    t.start()
    return t
