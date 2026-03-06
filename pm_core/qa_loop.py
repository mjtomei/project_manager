"""QA loop: planning + parallel execution of QA scenarios.

Two-phase process:
  Phase 1 — Planning: A Claude session analyzes the PR and generates
  a structured test plan.
  Phase 2 — Execution: Each scenario from the plan becomes a child
  QA session, running in its own tmux window (qa-{display_id}-s{N}).

Verdicts (shared with review):
  PASS           — Scenario passed, no issues found.
  NEEDS_WORK     — Issues found (child may have committed fixes).
  INPUT_REQUIRED — Genuine ambiguity requiring human judgment.
"""

import json
import re
import secrets
import subprocess
import sys
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
    window_name: str | None = None
    worktree_path: str | None = None
    worktree_branch: str | None = None
    container_name: str | None = None


@dataclass
class QALoopState:
    """Tracks the state of a running QA session."""
    pr_id: str
    running: bool = False
    stop_requested: bool = False
    loop_id: str = field(default_factory=lambda: secrets.token_hex(8))
    iteration: int = 0
    planning_phase: bool = True
    plan_output: str = ""
    scenarios: list[QAScenario] = field(default_factory=list)
    scenario_verdicts: dict[int, str] = field(default_factory=dict)
    latest_verdict: str = ""
    latest_output: str = ""
    made_changes: bool = False
    qa_workdir: str | None = None
    pre_qa_head: str | None = None
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


def create_scenario_workdir(qa_workdir: Path, scenario_index: int,
                            repo_root: Path | None = None,
                            pr_id: str = "",
                            loop_id: str = "") -> tuple[Path, str, Path, Path | None]:
    """Create a worktree + scratch dir + venv for one QA scenario.

    When *repo_root* is provided (worktree mode), creates:
      - ``{qa_workdir}/worktree-{N}/``  — git worktree (isolated branch)
      - ``{qa_workdir}/scratch-{N}/``   — empty temp dir for throwaway tests
      - ``{qa_workdir}/venv-{N}/``      — ``--system-site-packages`` venv

    Falls back to a plain empty directory when *repo_root* is None (legacy).

    Returns ``(worktree_path, branch_name, scratch_path, venv_path)``.
    ``venv_path`` is ``None`` in legacy mode.
    """
    from pm_core import git_ops

    scratch = qa_workdir / f"scratch-{scenario_index}"
    scratch.mkdir(parents=True, exist_ok=True)

    if repo_root is None:
        # Legacy: plain empty directory, no worktree
        d = qa_workdir / f"scenario-{scenario_index}"
        d.mkdir(parents=True, exist_ok=True)
        return d, "", scratch, None

    branch_name = f"qa-tmp-{pr_id}-{loop_id}-s{scenario_index}"
    wt_path = qa_workdir / f"worktree-{scenario_index}"

    # Clean up stale worktree/branch from a previous attempt.
    # Always prune first — a previous run may have deleted the worktree
    # directory without calling `git worktree remove`, leaving a stale
    # entry that prevents branch deletion and re-creation.
    git_ops.run_git("worktree", "prune", cwd=repo_root, check=False)
    if wt_path.exists():
        git_ops.remove_worktree(repo_root, wt_path)
    git_ops.delete_branch(repo_root, branch_name)

    git_ops.create_worktree(repo_root, branch_name, wt_path)

    # Create a --system-site-packages venv so pip installs stay local
    venv_path = qa_workdir / f"venv-{scenario_index}"
    if not venv_path.exists():
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", "--system-site-packages",
                 str(venv_path)],
                check=True, capture_output=True,
            )
        except Exception:
            _log.warning("Failed to create venv for scenario %d, continuing without",
                         scenario_index)
            venv_path = None
    return wt_path, branch_name, scratch, venv_path


def _setup_worktree_override(worktree_path: Path) -> None:
    """Configure the worktree so Claude sessions in it use the correct pm_core.

    Computes the session tag for the worktree and sets the override path
    to point at the parent of the currently-running ``pm_core`` package.
    """
    import pm_core
    from pm_core.paths import get_session_tag, set_override_path

    tag = get_session_tag(start_path=worktree_path)
    if not tag:
        _log.warning("Could not get session tag for worktree %s", worktree_path)
        return

    pm_core_parent = Path(pm_core.__file__).parent.parent
    set_override_path(tag, pm_core_parent)
    _log.info("Set override for worktree %s (tag=%s) → %s",
              worktree_path, tag, pm_core_parent)


# ---------------------------------------------------------------------------
# QA window naming
# ---------------------------------------------------------------------------

def _compute_qa_window_name(pr_data: dict) -> str:
    """Compute the main QA tmux window name from PR data."""
    from pm_core.cli.helpers import _pr_display_id
    display_id = _pr_display_id(pr_data)
    return f"qa-{display_id}"


def _scenario_window_name(pr_data: dict, scenario_index: int) -> str:
    """Compute the tmux window name for a single scenario.

    Returns e.g. ``qa-#116-s3``.
    """
    from pm_core.cli.helpers import _pr_display_id
    display_id = _pr_display_id(pr_data)
    return f"qa-{display_id}-s{scenario_index}"


# Alias for backward compat with tests; prefer find_claude_pane directly.
_get_scenario_pane = find_claude_pane


def _cleanup_stale_scenario_windows(session: str, pr_data: dict,
                                    include_main: bool = True) -> None:
    """Kill stale scenario windows and optionally the main QA window.

    Args:
        session: tmux session name.
        pr_data: PR data dict (needs ``id`` and optionally ``gh_pr_number``).
        include_main: When True (default), also kill the main ``qa-{id}``
            window.  Pass False after execution to keep the main window
            alive so its status pane can display the aggregated verdict.
    """
    from pm_core import tmux as tmux_mod
    from pm_core.cli.helpers import _pr_display_id

    display_id = _pr_display_id(pr_data)
    qa_prefix = f"qa-{display_id}-s"
    main_name = f"qa-{display_id}"

    all_windows = tmux_mod.list_windows(session)
    for win in all_windows:
        if win["name"].startswith(qa_prefix):
            _log.info("Killing stale QA window %s", win["name"])
            tmux_mod.kill_window(session, win["id"])
        elif include_main and win["name"] == main_name:
            _log.info("Killing stale QA window %s", win["name"])
            tmux_mod.kill_window(session, win["id"])


# ---------------------------------------------------------------------------
# Status file management
# ---------------------------------------------------------------------------

def _write_status_file(status_path: Path, pr_id: str,
                       scenarios: list[QAScenario],
                       scenario_verdicts: dict[int, str],
                       overall: str = "") -> None:
    """Atomically write the qa_status.json file."""
    data = {
        "pr_id": pr_id,
        "scenarios": [
            {
                "index": s.index,
                "title": s.title,
                "verdict": scenario_verdicts.get(s.index, ""),
                "window_name": s.window_name or "",
            }
            for s in scenarios
        ],
        "overall": overall,
    }
    tmp_path = status_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    tmp_path.rename(status_path)


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
    placeholder_titles = {"Scenario Title", "..."}

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
        if title in placeholder_titles or title.startswith("<"):
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
# Worktree merge-back
# ---------------------------------------------------------------------------

def _merge_scenario_commits(state: QALoopState, repo_root: Path | None,
                            pr_data: dict) -> None:
    """Cherry-pick scenario worktree commits back to the PR branch.

    For each scenario with a worktree branch that has commits ahead of
    ``state.pre_qa_head``, cherry-picks those commits onto the PR branch.
    Pushes the PR branch once at the end if any commits were picked.
    """
    from pm_core import git_ops

    if not repo_root or not state.pre_qa_head:
        return

    any_picked = False
    for scenario in state.scenarios:
        if not scenario.worktree_branch:
            continue

        result = git_ops.cherry_pick_range(
            repo_root, scenario.worktree_branch, state.pre_qa_head,
        )
        if result["picked"] > 0:
            any_picked = True
            state.made_changes = True
            _log.info("Merged %d commit(s) from scenario %d (%d skipped)",
                      result["picked"], scenario.index, result["skipped"])

    # Push once if any commits were cherry-picked
    if any_picked:
        branch = pr_data.get("branch", "")
        if branch:
            git_ops.run_git("push", "origin", branch,
                            cwd=repo_root, check=False)
            _log.info("Pushed merged QA commits to %s", branch)


# ---------------------------------------------------------------------------
# Scenario launching helpers
# ---------------------------------------------------------------------------

def _launch_scenarios_in_tmux(
    state: QALoopState,
    data: dict,
    pr_data: dict,
    session: str,
    repo_root: Path | None,
    workdir_path: str,
) -> None:
    """Launch each scenario in its own tmux window (with worktree isolation)."""
    from pm_core import tmux as tmux_mod, prompt_gen
    from pm_core.claude_launcher import build_claude_shell_cmd

    for scenario in state.scenarios:
        if state.stop_requested:
            break

        try:
            wt_path, wt_branch, scratch_path, venv_path = create_scenario_workdir(
                Path(state.qa_workdir), scenario.index,
                repo_root=repo_root,
                pr_id=state.pr_id,
                loop_id=state.loop_id,
            )
        except Exception:
            _log.warning("Failed to create workdir for scenario %d, skipping",
                         scenario.index)
            continue
        scenario.worktree_path = str(wt_path)
        scenario.worktree_branch = wt_branch

        # Set up override so Claude in the worktree uses the correct pm_core
        if wt_branch:
            _setup_worktree_override(wt_path)

        child_prompt = prompt_gen.generate_qa_child_prompt(
            data, state.pr_id, scenario,
            workdir=str(wt_path),
            session_name=session,
            worktree_mode=bool(wt_branch),
            scratch_dir=str(scratch_path),
        )
        child_cmd = build_claude_shell_cmd(prompt=child_prompt)

        # Activate the scenario venv so pip installs stay local
        if venv_path:
            child_cmd = f"VIRTUAL_ENV={venv_path} PATH={venv_path}/bin:$PATH {child_cmd}"

        # Launch window with cwd=worktree_path so Claude has the full codebase
        scenario_cwd = str(wt_path) if wt_branch else workdir_path
        win_name = _scenario_window_name(pr_data, scenario.index)
        try:
            tmux_mod.new_window(session, win_name, child_cmd,
                                cwd=scenario_cwd, switch=False)
            scenario.window_name = win_name
        except Exception:
            _log.warning("Failed to create window for scenario %d",
                         scenario.index)
        if scenario.window_name:
            _log.info("Launched scenario %d (%s) in window %s (worktree=%s)",
                       scenario.index, scenario.title, win_name,
                       bool(wt_branch))
        else:
            _log.warning("Scenario %d (%s) window creation failed (worktree=%s)",
                          scenario.index, scenario.title, bool(wt_branch))


def _launch_scenarios_in_containers(
    state: QALoopState,
    data: dict,
    pr_data: dict,
    session: str,
    repo_root: Path | None,
    workdir_path: str,
) -> None:
    """Launch each scenario in a Docker container, presented via a tmux window.

    Each scenario gets:
      1. A detached container (``sleep infinity``) with the worktree mounted
      2. A tmux window running ``docker exec -it <container> claude ...``

    The user sees the same tmux windows as in non-container mode, but the
    claude process is isolated inside the container.  Polling and verdict
    extraction happen via tmux pane capture, identical to the tmux path.
    """
    from pm_core import tmux as tmux_mod, prompt_gen
    from pm_core import container as container_mod
    from pm_core.claude_launcher import build_claude_shell_cmd

    config = container_mod.load_container_config()

    for scenario in state.scenarios:
        if state.stop_requested:
            break

        try:
            wt_path, wt_branch, scratch_path, venv_path = create_scenario_workdir(
                Path(state.qa_workdir), scenario.index,
                repo_root=repo_root,
                pr_id=state.pr_id,
                loop_id=state.loop_id,
            )
        except Exception:
            _log.warning("Failed to create workdir for scenario %d, skipping",
                         scenario.index)
            continue
        scenario.worktree_path = str(wt_path)
        scenario.worktree_branch = wt_branch

        # In container mode, paths inside the container are fixed
        container_workdir = container_mod._CONTAINER_WORKDIR
        container_scratch = container_mod._CONTAINER_SCRATCH

        child_prompt = prompt_gen.generate_qa_child_prompt(
            data, state.pr_id, scenario,
            workdir=container_workdir,
            session_name=None,  # No tmux session inside containers
            worktree_mode=bool(wt_branch),
            scratch_dir=container_scratch,
        )
        claude_cmd = build_claude_shell_cmd(prompt=child_prompt)

        # Create and start the detached container
        cname = container_mod.qa_container_name(
            state.pr_id, state.loop_id, scenario.index,
        )
        # QA containers get push access scoped to the PR branch
        pr_branch = pr_data.get("branch", "")
        try:
            container_mod.create_qa_container(
                name=cname,
                config=config,
                repo_root=repo_root or Path(workdir_path),
                worktree_path=wt_path,
                scratch_path=scratch_path,
                allowed_push_branch=pr_branch,
            )
            scenario.container_name = cname
        except Exception:
            _log.warning("Failed to create container for scenario %d",
                         scenario.index)
            continue

        # Build docker exec command and launch in a tmux window.
        # cleanup=False: QA containers are batch-removed by cleanup_qa_containers
        exec_cmd = container_mod.build_exec_cmd(cname, claude_cmd, cleanup=False)
        win_name = _scenario_window_name(pr_data, scenario.index)
        try:
            tmux_mod.new_window(session, win_name, exec_cmd,
                                cwd=workdir_path, switch=False)
            scenario.window_name = win_name
        except Exception:
            _log.warning("Failed to create window for scenario %d",
                         scenario.index)

        if scenario.window_name:
            _log.info("Launched scenario %d (%s) in container %s (window %s)",
                       scenario.index, scenario.title, cname, win_name)
        else:
            _log.warning("Scenario %d (%s) container/window creation failed",
                          scenario.index, scenario.title)


# ---------------------------------------------------------------------------
# Verdict polling helpers
# ---------------------------------------------------------------------------

def _poll_tmux_verdicts(
    state: QALoopState,
    session: str,
    status_path: Path,
    _notify,
) -> None:
    """Poll tmux scenario windows for verdicts."""
    from pm_core import tmux as tmux_mod

    tracker = VerdictStabilityTracker()
    pending = {s.index for s in state.scenarios if s.window_name}

    # Scenarios that failed to create a window get INPUT_REQUIRED immediately
    has_failed_creation = False
    for scenario in state.scenarios:
        if not scenario.window_name:
            _log.warning("Scenario %d has no window — marking INPUT_REQUIRED",
                         scenario.index)
            state.scenario_verdicts[scenario.index] = VERDICT_INPUT_REQUIRED
            has_failed_creation = True
    if has_failed_creation:
        _write_status_file(status_path, state.pr_id, state.scenarios,
                           state.scenario_verdicts)

    grace_start = time.monotonic()

    while pending and not state.stop_requested:
        time.sleep(_POLL_INTERVAL)

        in_grace = (time.monotonic() - grace_start) < _VERDICT_GRACE_PERIOD
        verdicts_changed = False

        for scenario in state.scenarios:
            if scenario.index not in pending or not scenario.window_name:
                continue

            pane_id = _get_scenario_pane(session, scenario.window_name)
            if pane_id is None:
                _log.warning("Scenario %d window exited without verdict",
                             scenario.index)
                state.scenario_verdicts[scenario.index] = VERDICT_INPUT_REQUIRED
                pending.discard(scenario.index)
                verdicts_changed = True
                continue

            if in_grace:
                continue

            content = tmux_mod.capture_pane(
                pane_id, full_scrollback=True,
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
                verdicts_changed = True
                _log.info("Scenario %d (%s) verdict: %s",
                          scenario.index, scenario.title, verdict)
                state.latest_output = (
                    f"Scenario {scenario.index} ({scenario.title}): {verdict}"
                )
                _notify()

        if verdicts_changed:
            _write_status_file(status_path, state.pr_id, state.scenarios,
                               state.scenario_verdicts)



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
    3. Launch each scenario in its own tmux window
    4. Poll all scenario windows for verdicts
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

    # Status file path (inside QA workdir)
    status_path = Path(state.qa_workdir) / "qa_status.json"

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

        # If the main QA window already exists, remember which sessions
        # were watching it so we can switch them to the replacement window
        # (same pattern as the review loop's --fresh window replacement).
        sessions_on_qa: list[str] = []
        existing_win = tmux_mod.find_window_by_name(session, window_name)
        if existing_win:
            sessions_on_qa = tmux_mod.sessions_on_window(
                session, existing_win["id"],
            )
            _cleanup_stale_scenario_windows(session, pr_data)

        # Create QA window with planner pane (switch=False; we handle
        # session switching explicitly below to preserve focus)
        tmux_mod.new_window(session, window_name, cmd, cwd=workdir_path,
                            switch=False)
        time.sleep(2)  # let tmux register the new window

        # Switch sessions that were watching the old QA window to the new one
        if sessions_on_qa:
            tmux_mod.switch_sessions_to_window(
                sessions_on_qa, session, window_name)
        elif not existing_win:
            # First-time creation — select the window so user sees it
            tmux_mod.select_window(session, window_name)

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
            _log.info("QA plan parsed: %d scenario(s) for %s",
                      len(state.scenarios), state.pr_id)

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
    state.pre_qa_head = None
    repo_root = Path(workdir_path) if workdir_path and Path(workdir_path).is_dir() else None
    if repo_root:
        try:
            result = git_ops.run_git(
                "rev-parse", "HEAD", cwd=workdir_path, check=False,
            )
            if result.returncode == 0:
                state.pre_qa_head = result.stdout.strip()
        except Exception:
            pass

    # Determine execution mode (container vs tmux)
    from pm_core.container import is_container_mode_enabled, _docker_available
    use_containers = is_container_mode_enabled()
    if use_containers:
        if _docker_available():
            _log.info("Container mode enabled for QA execution")
        else:
            _log.warning("Container mode enabled but Docker unavailable "
                         "— falling back to host execution")
            use_containers = False

    # Ensure the main QA window exists (has the planner pane)
    win = tmux_mod.find_window_by_name(session, window_name)
    planner_pane = None
    if not win:
        planner_pane = tmux_mod.new_window_get_pane(
            session, window_name, "echo 'QA execution'", cwd=workdir_path,
            switch=False,
        )
    else:
        panes = tmux_mod.get_pane_indices(session, win["index"])
        planner_pane = panes[0][0] if panes else None

    if use_containers:
        _launch_scenarios_in_containers(
            state, data, pr_data, session, repo_root, workdir_path,
        )
    else:
        _launch_scenarios_in_tmux(
            state, data, pr_data, session, repo_root, workdir_path,
        )

    # Add status pane to the main QA window (split planner pane horizontally)
    if planner_pane:
        try:
            # Use the script path directly (avoids PYTHONPATH issues)
            _qa_status_script = Path(__file__).parent / "qa_status.py"
            status_cmd = (
                f"python3 {_qa_status_script} {status_path} {session}"
            )
            status_pane = tmux_mod.split_pane_at(
                planner_pane, "h", status_cmd, background=True,
            )

            # Register both panes and rebalance the main window only
            qa_win = tmux_mod.find_window_by_name(session, window_name)
            if qa_win:
                qa_win_id = None
                wid_result = subprocess.run(
                    tmux_mod._tmux_cmd("display", "-t", planner_pane,
                                       "-p", "#{window_id}"),
                    capture_output=True, text=True,
                )
                qa_win_id = wid_result.stdout.strip() or None
                if qa_win_id:
                    pane_registry.register_pane(
                        session, qa_win_id, planner_pane,
                        "qa-planner", "planner",
                    )
                    pane_registry.register_pane(
                        session, qa_win_id, status_pane,
                        "qa-status", status_cmd,
                    )
                    pane_layout.rebalance(session, qa_win_id)
        except Exception:
            _log.exception("Failed to create status pane")

    # Write initial status file
    _write_status_file(status_path, state.pr_id, state.scenarios,
                       state.scenario_verdicts)

    state.latest_output = f"Running {len(state.scenarios)} scenario(s)..."
    _notify()

    # --- Poll for verdicts (always via tmux — containers also use tmux windows) ---
    _poll_tmux_verdicts(state, session, status_path, _notify)

    # --- Cleanup ---
    # Kill ALL windows matching the qa-{display_id}-s* pattern (not just
    # known scenarios) to catch stale duplicates from previous runs.
    # Keep the main QA window alive so its status pane can display the
    # aggregated verdict and the user can focus it with 't'.
    _cleanup_stale_scenario_windows(session, pr_data, include_main=False)
    if use_containers:
        from pm_core import container as container_mod
        container_mod.cleanup_qa_containers(state.pr_id, state.loop_id)

    # --- Merge back scenario worktree commits ---
    _merge_scenario_commits(state, repo_root, pr_data)

    # --- Worktree cleanup ---
    if repo_root:
        for scenario in state.scenarios:
            if scenario.worktree_path:
                git_ops.remove_worktree(repo_root, Path(scenario.worktree_path))
            if scenario.worktree_branch:
                git_ops.delete_branch(repo_root, scenario.worktree_branch)

    # --- Aggregate verdicts ---
    verdicts = list(state.scenario_verdicts.values())

    # Check for uncommitted files in the main workdir
    if repo_root:
        try:
            result = git_ops.run_git(
                "status", "--porcelain", cwd=workdir_path, check=False,
            )
            if result.stdout.strip():
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

    # Write final status file with overall verdict
    _write_status_file(status_path, state.pr_id, state.scenarios,
                       state.scenario_verdicts, overall=state.latest_verdict)

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
