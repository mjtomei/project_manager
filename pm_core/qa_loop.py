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
    display_id = pr_data.get("display_id") or pr_data.get("id", "unknown")
    return f"qa-{display_id}"


# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

def parse_qa_plan(output: str) -> list[QAScenario]:
    """Parse planner output into a list of QAScenarios.

    Expected format:
    ## QA Plan

    ### 1. [Scenario Title]
    - **focus**: What to test
    - **instruction**: path/to/file.md (optional)
    - **steps**: Key test steps

    ### 2. ...
    """
    scenarios: list[QAScenario] = []

    # Split on ### headings
    chunks = re.split(r'^###\s+', output, flags=re.MULTILINE)

    for chunk in chunks[1:]:  # skip preamble before first ###
        lines = chunk.strip().splitlines()
        if not lines:
            continue

        # Parse heading: "1. Scenario Title" or "1. [Scenario Title]"
        heading = lines[0].strip()
        m = re.match(r'(\d+)\.\s*\[?(.*?)\]?\s*$', heading)
        if not m:
            continue
        index = int(m.group(1))
        title = m.group(2).strip()

        focus = ""
        instruction_path = None
        steps = ""

        body = "\n".join(lines[1:])
        # Extract structured fields
        focus_m = re.search(r'\*\*focus\*\*:\s*(.+)', body)
        if focus_m:
            focus = focus_m.group(1).strip()

        instr_m = re.search(r'\*\*instruction\*\*:\s*(.+)', body)
        if instr_m:
            path_str = instr_m.group(1).strip()
            if path_str.lower() not in ("none", "n/a", "-"):
                instruction_path = path_str

        steps_m = re.search(r'\*\*steps\*\*:\s*(.+)', body, re.DOTALL)
        if steps_m:
            steps = steps_m.group(1).strip()
            # Trim at the next field or heading
            steps = re.split(r'\n\s*-\s*\*\*', steps)[0].strip()

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
    max_scenarios: int = 5,
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

        # Create QA window with planner pane
        tmux_mod.new_window(session, window_name, cmd, cwd=workdir_path)

        # Wait for the planner to finish (poll for plan output)
        planner_pane = find_claude_pane(session, window_name)
        if not planner_pane:
            _log.error("Could not find planner pane")
            state.running = False
            state.latest_verdict = "ERROR"
            state.latest_output = "Could not find planner pane"
            return state

        # Poll until the planner produces a QA Plan or exits
        plan_found = False
        for _ in range(120):  # up to 10 minutes
            if state.stop_requested:
                break
            if not tmux_mod.pane_exists(planner_pane):
                _log.info("Planner pane exited")
                break

            content = tmux_mod.capture_pane(planner_pane, full_scrollback=True)
            if "## QA Plan" in content or "### 1." in content:
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
            state.latest_verdict = VERDICT_PASS
            state.latest_output = "Planner produced no scenarios — defaulting to PASS"
            _notify()
            return state

        # Limit scenarios
        if len(state.scenarios) > max_scenarios:
            state.scenarios = state.scenarios[:max_scenarios]

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
        if base_pane:
            pane_id = tmux_mod.split_pane_at(
                base_pane, "v", child_cmd, background=True,
            )
        else:
            pane_id = None
        scenario.pane_id = pane_id
        _log.info("Launched scenario %d (%s) in pane %s",
                   scenario.index, scenario.title, pane_id)

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
                # Pane exited without verdict
                _log.warning("Scenario %d pane exited without verdict",
                             scenario.index)
                state.scenario_verdicts[scenario.index] = VERDICT_PASS
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
    max_scenarios: int = 5,
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
