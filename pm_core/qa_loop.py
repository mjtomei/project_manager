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
    poll_for_verdict,
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
_SCENARIO_MAX_RETRIES = 10  # max times to relaunch a dead scenario
_SCENARIO_RETRY_BASE = 5  # base seconds for exponential backoff


def _get_max_scenarios() -> int:
    """Read qa-max-scenarios from global settings, or _DEFAULT_MAX_SCENARIOS."""
    from pm_core.paths import get_global_setting_value
    val = get_global_setting_value("qa-max-scenarios", "")
    try:
        return max(0, int(val))
    except ValueError:
        return _DEFAULT_MAX_SCENARIOS

def _is_verification_enabled() -> bool:
    """Check if PASS verdict verification is enabled (default: True).

    Controlled by the ``qa-verify-pass`` global setting.  Set to ``0``
    or ``false`` to disable.
    """
    from pm_core.paths import get_global_setting_value
    val = get_global_setting_value("qa-verify-pass", "").strip().lower()
    if val in ("0", "false", "no", "off", "disabled"):
        return False
    return True


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
    container_name: str | None = None
    transcript_path: str | None = None


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
    qa_workdir: str | None = None
    # Scenario 0 (interactive) — tracked separately, never polled for verdicts
    scenario_0: QAScenario | None = None
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


def _scenario_transcript_path(qa_workdir: str | Path, scenario_index: int) -> str:
    """Return the path where a scenario's transcript symlink should live."""
    return str(Path(qa_workdir) / f"transcript-s{scenario_index}.jsonl")


def _next_scenario_offset(pr_id: str, current_loop_id: str) -> int:
    """Find the highest scenario index used in previous runs for this PR.

    Scans ``~/.pm/workdirs/qa/{pr_id}-*/worktree-*`` dirs (excluding the
    current run) to find the max index, so new scenarios continue numbering
    from where previous runs left off.
    """
    qa_root = Path.home() / ".pm" / "workdirs" / "qa"
    max_idx = 0
    for d in qa_root.glob(f"{pr_id}-*/worktree-*"):
        # Skip the current run
        if current_loop_id and d.parent.name == f"{pr_id}-{current_loop_id}":
            continue
        try:
            idx = int(d.name.split("-", 1)[1])
            max_idx = max(max_idx, idx)
        except (ValueError, IndexError):
            pass
    return max_idx


def create_scenario_workdir(qa_workdir: Path, scenario_index: int,
                            repo_root: Path | None = None,
                            pr_id: str = "",
                            loop_id: str = "",
                            branch: str = "") -> tuple[Path, Path, Path | None]:
    """Create an isolated clone + scratch dir + venv for one QA scenario.

    When *repo_root* is provided, creates:
      - ``{qa_workdir}/worktree-{N}/``  — ``git clone --local`` of the repo
      - ``{qa_workdir}/scratch-{N}/``   — empty temp dir for throwaway tests
      - ``{qa_workdir}/venv-{N}/``      — ``--system-site-packages`` venv

    The clone checks out *branch* (the PR branch) so the scenario can
    commit and push fixes directly.

    Falls back to a plain empty directory when *repo_root* is None (legacy).

    Returns ``(clone_path, scratch_path, venv_path)``.
    ``venv_path`` is ``None`` in legacy mode.
    """
    from pm_core import git_ops

    scratch = qa_workdir / f"scratch-{scenario_index}"
    scratch.mkdir(parents=True, exist_ok=True)

    if repo_root is None:
        d = qa_workdir / f"scenario-{scenario_index}"
        d.mkdir(parents=True, exist_ok=True)
        return d, scratch, None

    clone_path = qa_workdir / f"worktree-{scenario_index}"

    # Clean up stale clone from a previous run
    if clone_path.exists():
        import shutil
        shutil.rmtree(clone_path, ignore_errors=True)

    # Create a local clone — fast (hardlinks objects) and standalone
    # (proper .git directory, no worktree pointer issues).
    clone_args = ["clone", "--local", str(repo_root), str(clone_path)]
    if branch:
        clone_args.extend(["--branch", branch])
    git_ops.run_git(*clone_args)

    # The clone's origin points to the PR workdir (repo_root).  The push
    # proxy handles local-path origins: it fetches into the PR workdir
    # (updating its branch ref) and then forwards to the real upstream.
    # This keeps all local copies in sync.

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
    return clone_path, scratch, venv_path


def _setup_clone_override(clone_path: Path) -> None:
    """Configure a clone so Claude sessions in it use the correct pm_core.

    Computes the session tag for the clone and sets the override path
    to point at the parent of the currently-running ``pm_core`` package.
    """
    import pm_core
    from pm_core.paths import get_session_tag, set_override_path

    tag = get_session_tag(start_path=clone_path)
    if not tag:
        _log.warning("Could not get session tag for clone %s", clone_path)
        return

    pm_core_parent = Path(pm_core.__file__).parent.parent
    set_override_path(tag, pm_core_parent)
    _log.info("Set override for clone %s (tag=%s) → %s",
              clone_path, tag, pm_core_parent)


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

    Returns e.g. ``qa-#116-s3`` (or ``qa-#116-s0`` for the interactive session).
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
                       overall: str = "",
                       scenario_0: QAScenario | None = None,
                       verifying_scenarios: set[int] | None = None) -> None:
    """Atomically write the qa_status.json file."""
    _verifying = verifying_scenarios or set()
    all_scenarios = []
    if scenario_0 and scenario_0.window_name:
        all_scenarios.append({
            "index": 0,
            "title": scenario_0.title,
            "verdict": "interactive",
            "window_name": scenario_0.window_name or "",
        })
    for s in scenarios:
        verdict = scenario_verdicts.get(s.index, "")
        if s.index in _verifying:
            verdict = f"{verdict} (verifying)" if verdict else "verifying"
        all_scenarios.append({
            "index": s.index,
            "title": s.title,
            "verdict": verdict,
            "window_name": s.window_name or "",
        })
    data = {
        "pr_id": pr_id,
        "scenarios": all_scenarios,
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
# Model resolution helper
# ---------------------------------------------------------------------------

def _resolve_qa_model(pr_data: dict, project_data: dict | None = None,
                      session_type: str = "qa"):
    """Resolve model/provider for a QA session type.

    session_type should be "qa_planning" for the planner or "qa_scenario"
    for scenario workers.  Falls back to "qa" config if the specific type
    is not configured.
    """
    from pm_core.model_config import resolve_model_and_provider, get_pr_model_override
    return resolve_model_and_provider(
        session_type,
        pr_model=get_pr_model_override(pr_data),
        project_data=project_data,
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Scenario 0 — interactive session
# ---------------------------------------------------------------------------

def _launch_scenario_0(
    state: QALoopState,
    data: dict,
    pr_data: dict,
    session: str,
    repo_root: Path | None,
    workdir_path: str,
) -> QAScenario | None:
    """Launch Scenario 0: a persistent interactive Claude session.

    Returns the QAScenario object (not added to state.scenarios — it is
    tracked separately so it is never polled for verdicts).
    """
    from pm_core import tmux as tmux_mod, prompt_gen
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core.container import is_container_mode_enabled, _docker_available
    from pm_core import container as container_mod
    _qa_resolution = _resolve_qa_model(pr_data, data, session_type="qa_scenario")

    scenario = QAScenario(
        index=0,
        title="Interactive Session",
        focus="Manual testing and exploration",
    )

    branch = pr_data.get("branch", "")
    try:
        clone_path, scratch_path, venv_path = create_scenario_workdir(
            Path(state.qa_workdir), 0,
            repo_root=repo_root,
            pr_id=state.pr_id,
            loop_id=state.loop_id,
            branch=branch,
        )
    except Exception:
        _log.warning("Failed to create workdir for Scenario 0, skipping")
        return None

    scenario.worktree_path = str(clone_path)

    if repo_root:
        _setup_clone_override(clone_path)

    # Scenario 0 always runs on the host (not in a container) so the user
    # has full access to host tools, git credentials, and the TUI session.
    child_prompt = prompt_gen.generate_qa_interactive_prompt(
        data, state.pr_id,
        workdir=str(clone_path),
        session_name=session,
        worktree_mode=bool(repo_root),
        scratch_dir=str(scratch_path),
    )

    claude_cmd = build_claude_shell_cmd(
        prompt=child_prompt,
        model=_qa_resolution.model, provider=_qa_resolution.provider, effort=_qa_resolution.effort)
    if venv_path:
        claude_cmd = f"VIRTUAL_ENV={venv_path} PATH={venv_path}/bin:$PATH {claude_cmd}"
    final_cmd = claude_cmd
    scenario_cwd = str(clone_path) if repo_root else workdir_path

    win_name = _scenario_window_name(pr_data, 0)
    try:
        tmux_mod.new_window(session, win_name, final_cmd,
                            cwd=scenario_cwd, switch=False)
        scenario.window_name = win_name
    except Exception:
        _log.warning("Failed to create window for Scenario 0")
        return None

    _log.info("Launched Scenario 0 (interactive) in window %s", win_name)
    return scenario


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
    _qa_resolution = _resolve_qa_model(pr_data, data, session_type="qa_scenario")

    branch = pr_data.get("branch", "")

    for scenario in state.scenarios:
        if state.stop_requested:
            break

        try:
            clone_path, scratch_path, venv_path = create_scenario_workdir(
                Path(state.qa_workdir), scenario.index,
                repo_root=repo_root,
                pr_id=state.pr_id,
                loop_id=state.loop_id,
                branch=branch,
            )
        except Exception:
            _log.warning("Failed to create workdir for scenario %d, skipping",
                         scenario.index)
            continue
        scenario.worktree_path = str(clone_path)

        if repo_root:
            _setup_clone_override(clone_path)

        scenario_cwd = str(clone_path) if repo_root else workdir_path
        transcript = _scenario_transcript_path(state.qa_workdir, scenario.index)

        child_prompt = prompt_gen.generate_qa_child_prompt(
            data, state.pr_id, scenario,
            workdir=str(clone_path),
            session_name=session,
            worktree_mode=bool(repo_root),
            scratch_dir=str(scratch_path),
        )
        child_cmd = build_claude_shell_cmd(
            prompt=child_prompt,
            model=_qa_resolution.model, provider=_qa_resolution.provider, effort=_qa_resolution.effort,
            transcript=transcript, cwd=scenario_cwd)

        # Activate the scenario venv so pip installs stay local
        if venv_path:
            child_cmd = f"VIRTUAL_ENV={venv_path} PATH={venv_path}/bin:$PATH {child_cmd}"

        win_name = _scenario_window_name(pr_data, scenario.index)
        try:
            tmux_mod.new_window(session, win_name, child_cmd,
                                cwd=scenario_cwd, switch=False)
            scenario.window_name = win_name
            scenario.transcript_path = transcript
        except Exception:
            _log.warning("Failed to create window for scenario %d",
                         scenario.index)
        if scenario.window_name:
            _log.info("Launched scenario %d (%s) in window %s",
                       scenario.index, scenario.title, win_name)
        else:
            _log.warning("Scenario %d (%s) window creation failed",
                          scenario.index, scenario.title)


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
      1. A local clone of the repo (standalone .git, no worktree pointers)
      2. A detached container with the clone mounted at /workspace
      3. A push proxy scoped to the PR branch
      4. A tmux window running ``docker exec -it <container> claude ...``

    The user sees the same tmux windows as in non-container mode, but the
    claude process is isolated inside the container.  Polling and verdict
    extraction happen via tmux pane capture, identical to the tmux path.
    """
    from pm_core import tmux as tmux_mod, prompt_gen
    from pm_core import container as container_mod
    from pm_core.claude_launcher import build_claude_shell_cmd
    _qa_resolution = _resolve_qa_model(pr_data, data, session_type="qa_scenario")

    config = container_mod.load_container_config()
    branch = pr_data.get("branch", "")

    # Derive session tag from tmux session name for container naming and
    # shared push proxies.
    _session_tag = session.removeprefix("pm-") if session else None

    for scenario in state.scenarios:
        if state.stop_requested:
            break

        try:
            clone_path, scratch_path, venv_path = create_scenario_workdir(
                Path(state.qa_workdir), scenario.index,
                repo_root=repo_root,
                pr_id=state.pr_id,
                loop_id=state.loop_id,
                branch=branch,
            )
        except Exception:
            _log.warning("Failed to create workdir for scenario %d, skipping",
                         scenario.index)
            continue
        scenario.worktree_path = str(clone_path)

        # In container mode, paths inside the container are fixed
        container_workdir = container_mod._CONTAINER_WORKDIR
        container_scratch = container_mod._CONTAINER_SCRATCH

        # Transcript symlink lives on the host; cwd must match what Claude
        # sees inside the container so the mangled project dir is correct.
        transcript = _scenario_transcript_path(state.qa_workdir, scenario.index)

        child_prompt = prompt_gen.generate_qa_child_prompt(
            data, state.pr_id, scenario,
            workdir=container_workdir,
            session_name=None,  # No tmux session inside containers
            worktree_mode=bool(repo_root),
            scratch_dir=container_scratch,
        )
        claude_cmd = build_claude_shell_cmd(
            prompt=child_prompt,
            model=_qa_resolution.model, provider=_qa_resolution.provider, effort=_qa_resolution.effort,
            transcript=transcript, cwd=container_workdir)

        # Create container with push proxy for the PR branch.
        # All QA scenarios for the same PR share a single push proxy.
        cname = container_mod.qa_container_name(
            state.pr_id, state.loop_id, scenario.index,
            session_tag=_session_tag,
        )
        try:
            container_mod.create_qa_container(
                name=cname,
                config=config,
                workdir=clone_path,
                scratch_path=scratch_path,
                allowed_push_branch=branch or None,
                session_tag=_session_tag,
                pr_id=state.pr_id,
            )
            scenario.container_name = cname
        except Exception:
            _log.error("Failed to create container for scenario %d — aborting scenario",
                       scenario.index, exc_info=True)
            continue

        # Build docker exec command and launch in a tmux window.
        # cleanup=False: containers stay alive with their windows; orphans
        # are cleaned up at the start of the next QA run.
        exec_cmd = container_mod.build_exec_cmd(cname, claude_cmd, cleanup=False)
        win_name = _scenario_window_name(pr_data, scenario.index)
        try:
            tmux_mod.new_window(session, win_name, exec_cmd,
                                cwd=workdir_path, switch=False)
            scenario.window_name = win_name
            scenario.transcript_path = transcript
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
# Scenario retry helpers
# ---------------------------------------------------------------------------

def _relaunch_scenario_window(
    scenario: QAScenario,
    state: QALoopState,
    data: dict,
    pr_data: dict,
    session: str,
    workdir_path: str,
) -> bool:
    """Re-create the tmux window for a scenario whose window died.

    The worktree / container should still exist — we just need to launch
    a new ``docker exec`` (container mode) or ``claude`` (host mode) in a
    fresh tmux window.

    Returns True if the window was recreated successfully.
    """
    from pm_core import tmux as tmux_mod, prompt_gen
    from pm_core.claude_launcher import build_claude_shell_cmd
    from pm_core.container import is_container_mode_enabled, _docker_available
    from pm_core import container as container_mod
    _qa_resolution = _resolve_qa_model(pr_data, data, session_type="qa_scenario")

    win_name = _scenario_window_name(pr_data, scenario.index)
    use_containers = is_container_mode_enabled() and _docker_available()

    # New transcript for the relaunched session (old one is stale)
    transcript = _scenario_transcript_path(state.qa_workdir, scenario.index)

    try:
        if use_containers and scenario.container_name:
            # Container still running — just re-exec into it
            container_workdir = container_mod._CONTAINER_WORKDIR
            container_scratch = container_mod._CONTAINER_SCRATCH
            child_prompt = prompt_gen.generate_qa_child_prompt(
                data, state.pr_id, scenario,
                workdir=container_workdir,
                session_name=None,
                worktree_mode=bool(scenario.worktree_path),
                scratch_dir=container_scratch,
            )
            claude_cmd = build_claude_shell_cmd(
                prompt=child_prompt,
                model=_qa_resolution.model, provider=_qa_resolution.provider, effort=_qa_resolution.effort,
                transcript=transcript, cwd=container_workdir)
            exec_cmd = container_mod.build_exec_cmd(
                scenario.container_name, claude_cmd, cleanup=False)
            tmux_mod.new_window(session, win_name, exec_cmd,
                                cwd=workdir_path, switch=False)
        else:
            # Host mode — worktree still exists
            wt_path = scenario.worktree_path or workdir_path
            child_prompt = prompt_gen.generate_qa_child_prompt(
                data, state.pr_id, scenario,
                workdir=str(wt_path),
                session_name=session,
                worktree_mode=bool(scenario.worktree_path),
                scratch_dir=str(Path(state.qa_workdir) / f"scratch-{scenario.index}"),
            )
            child_cmd = build_claude_shell_cmd(
                prompt=child_prompt,
                model=_qa_resolution.model, provider=_qa_resolution.provider, effort=_qa_resolution.effort,
                transcript=transcript, cwd=str(wt_path))
            venv_path = Path(state.qa_workdir) / f"venv-{scenario.index}"
            if venv_path.is_dir():
                child_cmd = f"VIRTUAL_ENV={venv_path} PATH={venv_path}/bin:$PATH {child_cmd}"
            tmux_mod.new_window(session, win_name, child_cmd,
                                cwd=str(wt_path), switch=False)

        scenario.window_name = win_name
        scenario.transcript_path = transcript
        _log.info("Relaunched scenario %d in window %s", scenario.index, win_name)
        return True
    except Exception:
        _log.warning("Failed to relaunch scenario %d", scenario.index, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Verdict polling helpers
# ---------------------------------------------------------------------------

def _poll_tmux_verdicts(
    state: QALoopState,
    data: dict,
    pr_data: dict,
    session: str,
    workdir_path: str,
    status_path: Path,
    _notify,
) -> None:
    """Poll tmux scenario windows for verdicts.

    When a PASS verdict is accepted, verification runs in a split pane
    to check that the scenario genuinely exercised its test cases.  If
    verification flags a scenario, a follow-up message is sent to the
    scenario's pane and the scenario goes back to pending.
    """
    from pm_core import tmux as tmux_mod

    verify_enabled = _is_verification_enabled()
    if verify_enabled:
        _log.info("PASS verdict verification is enabled")
    else:
        _log.info("PASS verdict verification is disabled (qa-verify-pass)")

    tracker = VerdictStabilityTracker()
    pending = {s.index for s in state.scenarios if s.window_name}
    retry_counts: dict[int, int] = {}  # scenario_index -> retries used
    # Track how many verification failures each scenario has had
    verification_failures: dict[int, int] = {}
    # Scenarios currently being verified (in a background thread)
    verifying: set[int] = set()
    # Results from background verification threads
    verification_results: dict[int, tuple[bool, str]] = {}
    verification_lock = threading.Lock()

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
                           state.scenario_verdicts,
                           scenario_0=state.scenario_0)

    grace_start = time.monotonic()

    def _run_verification(scenario: QAScenario, verdict: str, content: str):
        """Background thread: run verification in a visible pane."""
        try:
            passed, reason = _verify_single_scenario(
                scenario, verdict, content, pr_data, data,
                session=session,
            )
        except Exception:
            _log.warning("Verification thread crashed for scenario %d",
                         scenario.index, exc_info=True)
            passed, reason = True, ""  # trust original on failure
        with verification_lock:
            verification_results[scenario.index] = (passed, reason)
            # NOTE: do NOT discard from ``verifying`` here — the main
            # loop must process the result first.  If we discard now
            # and ``pending`` is also empty the loop exits before it
            # sees the result (race condition).

    while (pending or verifying) and not state.stop_requested:
        time.sleep(_POLL_INTERVAL)

        in_grace = (time.monotonic() - grace_start) < _VERDICT_GRACE_PERIOD
        verdicts_changed = False

        # Check for completed verifications
        with verification_lock:
            completed_verifications = dict(verification_results)
            verification_results.clear()

        for scenario_idx, (passed, reason) in completed_verifications.items():
            verifying.discard(scenario_idx)
            scenario = next(s for s in state.scenarios if s.index == scenario_idx)
            if passed:
                _log.info("Verification passed for scenario %d (%s)",
                          scenario_idx, scenario.title)
                # Verdict already set; mark as genuinely complete
                state.latest_output = (
                    f"Scenario {scenario_idx} ({scenario.title}): "
                    f"{state.scenario_verdicts[scenario_idx]} (verified)"
                )
                _notify()
            else:
                fails = verification_failures.get(scenario_idx, 0) + 1
                verification_failures[scenario_idx] = fails
                _log.info("Verification FLAGGED scenario %d (%s), attempt %d: %s",
                          scenario_idx, scenario.title, fails, reason)

                if fails > _VERIFICATION_MAX_RETRIES:
                    # Too many verification failures — mark NEEDS_WORK
                    _log.warning("Scenario %d failed verification %d times — "
                                 "marking NEEDS_WORK", scenario_idx, fails)
                    state.scenario_verdicts[scenario_idx] = VERDICT_NEEDS_WORK
                    state.latest_output = (
                        f"Scenario {scenario_idx} ({scenario.title}): "
                        f"NEEDS_WORK (failed verification)"
                    )
                    verdicts_changed = True
                    _notify()
                else:
                    # Send the scenario a follow-up message and put back in pending
                    pane_id = _get_scenario_pane(session, scenario.window_name)
                    if pane_id:
                        followup_msg = (
                            f"Your verdict was reviewed and flagged: {reason} — "
                            f"Please re-evaluate this scenario. Make sure you "
                            f"actually execute the test steps (run commands, "
                            f"create test files, verify runtime behavior). "
                            f"Do not just read code. "
                            f"End with a new verdict on its own line "
                            f"(PASS / NEEDS_WORK / INPUT_REQUIRED)."
                        )
                        tmux_mod.send_keys(pane_id, followup_msg)
                        _log.info("Sent follow-up message to scenario %d pane",
                                  scenario_idx)
                        # Clear verdict and put back in pending
                        state.scenario_verdicts.pop(scenario_idx, None)
                        tracker.reset(f"qa-{state.pr_id}-{scenario_idx}")
                        pending.add(scenario_idx)
                        state.latest_output = (
                            f"Scenario {scenario_idx} ({scenario.title}): "
                            f"re-evaluating after verification"
                        )
                        verdicts_changed = True
                        _notify()
                    else:
                        _log.warning("Cannot send follow-up to scenario %d — "
                                     "window gone, marking NEEDS_WORK",
                                     scenario_idx)
                        state.scenario_verdicts[scenario_idx] = VERDICT_NEEDS_WORK
                        state.latest_output = (
                            f"Scenario {scenario_idx} ({scenario.title}): "
                            f"NEEDS_WORK (window gone during verification)"
                        )
                        verdicts_changed = True
                        _notify()

        for scenario in state.scenarios:
            if scenario.index not in pending or not scenario.window_name:
                continue

            pane_id = _get_scenario_pane(session, scenario.window_name)
            if pane_id is None:
                retries = retry_counts.get(scenario.index, 0)
                if retries < _SCENARIO_MAX_RETRIES:
                    backoff = _SCENARIO_RETRY_BASE * (2 ** retries)
                    _log.warning(
                        "Scenario %d window died — retry %d/%d "
                        "(backoff %.0fs)",
                        scenario.index, retries + 1,
                        _SCENARIO_MAX_RETRIES, backoff)
                    time.sleep(backoff)
                    if _relaunch_scenario_window(
                        scenario, state, data, pr_data,
                        session, workdir_path,
                    ):
                        retry_counts[scenario.index] = retries + 1
                        # Reset grace period for this retry
                        grace_start = time.monotonic()
                        continue
                _log.warning("Scenario %d window exited without verdict "
                             "(retries exhausted)",
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

                # Only PASS verdicts need verification — NEEDS_WORK and
                # INPUT_REQUIRED already indicate problems were found.
                if verdict == VERDICT_PASS and verify_enabled:
                    state.latest_output = (
                        f"Scenario {scenario.index} ({scenario.title}): "
                        f"{verdict} — verifying..."
                    )
                    _notify()

                    verifying.add(scenario.index)
                    t = threading.Thread(
                        target=_run_verification,
                        args=(scenario, verdict, content),
                        daemon=True,
                        name=f"qa-verify-{state.pr_id}-{scenario.index}",
                    )
                    t.start()
                else:
                    state.latest_output = (
                        f"Scenario {scenario.index} ({scenario.title}): "
                        f"{verdict}"
                    )
                    _notify()

        if verdicts_changed or completed_verifications:
            with verification_lock:
                verifying_snapshot = set(verifying)
            _write_status_file(status_path, state.pr_id, state.scenarios,
                               state.scenario_verdicts,
                               scenario_0=state.scenario_0,
                               verifying_scenarios=verifying_snapshot)


# ---------------------------------------------------------------------------
# Verdict verification
# ---------------------------------------------------------------------------

# Maximum pane output lines to include in the verification prompt.
# Large outputs are truncated to keep the prompt manageable.
_VERIFICATION_MAX_PANE_LINES = 500

# Maximum number of times a scenario can fail verification before being
# marked NEEDS_WORK.  After this many failures the scenario is not sent
# another follow-up message.
_VERIFICATION_MAX_RETRIES = 1


def _build_verification_prompt(scenario: QAScenario, verdict: str,
                                pane_output: str | None = None,
                                pane_output_path: str | None = None) -> str:
    """Build a prompt for Claude to verify a single scenario's verdict.

    The prompt asks Claude to determine whether the scenario genuinely
    exercised its test cases or just exited without doing real work.

    If *pane_output_path* is provided the prompt tells the verifier to
    read the file (keeps the prompt small).  Otherwise *pane_output* is
    inlined (truncated to ``_VERIFICATION_MAX_PANE_LINES``).
    """
    if pane_output_path:
        is_jsonl = pane_output_path.endswith(".jsonl")
        format_hint = (
            " The file is in JSON Lines format (one JSON object per line) "
            "— each line represents a conversation turn with role, content, "
            "and tool use/result fields."
            if is_jsonl else ""
        )
        output_section = (
            f"The scenario produced the verdict: **{verdict}**\n\n"
            f"The full session transcript has been saved to:\n"
            f"  {pane_output_path}\n\n"
            f"Read that file to review the scenario output.{format_hint}"
        )
    else:
        text = pane_output or ""
        lines = text.splitlines()
        if len(lines) > _VERIFICATION_MAX_PANE_LINES:
            truncated = lines[:_VERIFICATION_MAX_PANE_LINES]
            text = "\n".join(truncated) + (
                f"\n\n[... truncated {len(lines) - _VERIFICATION_MAX_PANE_LINES}"
                f" more lines ...]"
            )
        output_section = (
            f"The scenario produced the verdict: **{verdict}**\n\n"
            f"Here is the full output from the scenario session:\n\n"
            f"<scenario_output>\n{text}\n</scenario_output>"
        )

    return f"""You are verifying the output of QA scenario {scenario.index}: "{scenario.title}"

## Scenario Definition

**Focus**: {scenario.focus}

**Steps**:
{scenario.steps}

## Scenario Output

{output_section}

## Your Task

This scenario claimed **PASS**.  Your job is to verify that the PASS is genuine — that the scenario actually did the work it was supposed to do.

Check for these problems:
1. **Did the scenario actually execute the test steps?** Look for evidence of commands being run, test files being created, tests being executed, and runtime behavior being verified. A scenario that only read code or declared PASS without running anything is NOT a genuine pass.
2. **Does the output support the PASS verdict?** The output should show the test steps being executed and succeeding. If the output shows errors, failures, incomplete work, or skipped steps, the PASS is not justified.
3. **Did the scenario complete its work?** Look for signs that the scenario crashed, timed out, or was interrupted before finishing all test steps.

## Response Format

Respond with EXACTLY one of these on its own line:

VERIFIED — The PASS is genuine: the scenario executed its test steps and they succeeded.
FLAGGED — The PASS is not justified: the scenario did not properly exercise its test cases, or the output contradicts a PASS.

If FLAGGED, include a brief explanation (1-2 sentences) of what went wrong BEFORE the FLAGGED verdict."""


_VERIFICATION_VERDICTS = ("VERIFIED", "FLAGGED")


def _verify_single_scenario(
    scenario: QAScenario,
    verdict: str,
    pane_output: str,
    pr_data: dict,
    project_data: dict | None = None,
    session: str | None = None,
) -> tuple[bool, str]:
    """Verify a single scenario's verdict in a visible tmux pane.

    Splits the scenario's tmux window to create a verification pane
    running an interactive Claude session.  The user can see the
    verification happening live.  Polls the pane for VERIFIED/FLAGGED,
    then closes it.

    Returns (passed, reason) where passed is True if the scenario was
    verified, and reason is the explanation if it was flagged.

    If the scenario has a transcript file (``.jsonl`` written by Claude
    CLI), the verifier is pointed at that file so it can read the full
    structured session.  Otherwise the pane output is inlined with
    truncation as a fallback.
    """
    from pm_core import tmux as tmux_mod
    from pm_core.claude_launcher import build_claude_shell_cmd, finalize_transcript

    resolution = _resolve_qa_model(pr_data, project_data,
                                   session_type="qa_verification")

    # Prefer the transcript file if it exists (finalize first so the
    # symlink is replaced with a real copy that survives pruning).
    transcript_path = scenario.transcript_path
    if transcript_path:
        try:
            finalize_transcript(Path(transcript_path))
        except Exception:
            _log.debug("Could not finalize transcript for scenario %d",
                       scenario.index, exc_info=True)
        if not Path(transcript_path).exists():
            _log.warning("Transcript for scenario %d not found at %s, "
                         "falling back to pane output",
                         scenario.index, transcript_path)
            transcript_path = None

    prompt = _build_verification_prompt(
        scenario, verdict,
        pane_output_path=transcript_path,
        pane_output=pane_output if not transcript_path else None,
    )

    # Find the scenario's pane to split
    scenario_pane = _get_scenario_pane(session, scenario.window_name) if session else None
    if not scenario_pane:
        _log.warning("Verification: cannot find scenario %d pane, "
                     "trusting original verdict", scenario.index)
        return True, ""

    # Build the verification claude command
    verify_cmd = build_claude_shell_cmd(
        prompt=prompt,
        model=resolution.model,
        provider=resolution.provider,
        effort=resolution.effort,
    )

    # Split the scenario window using the standard pane management system
    # so it works with mobile mode and portrait monitors.
    from pm_core import pane_layout, pane_registry

    _log.info("Verification: splitting pane for scenario %d (%s) "
              "[source=%s]",
              scenario.index, scenario.title,
              "transcript" if transcript_path else "pane")
    try:
        verify_pane = tmux_mod.split_pane_at(
            scenario_pane, "v", verify_cmd, background=True,
        )
    except Exception:
        _log.warning("Verification: failed to split pane for scenario %d, "
                     "trusting original verdict",
                     scenario.index, exc_info=True)
        return True, ""

    # Register the pane and rebalance using standard layout management.
    # Failures here are non-fatal — we still poll and clean up the pane.
    win_id = None
    try:
        wid_result = subprocess.run(
            tmux_mod._tmux_cmd("display", "-t", scenario_pane,
                               "-p", "#{window_id}"),
            capture_output=True, text=True,
        )
        win_id = wid_result.stdout.strip() or None
        if win_id:
            pane_registry.register_pane(
                session, win_id, verify_pane,
                f"qa-verify-s{scenario.index}", verify_cmd,
            )
            pane_layout.rebalance(session, win_id)
    except Exception:
        _log.debug("Verification: registration/rebalance failed for "
                   "scenario %d, continuing with polling",
                   scenario.index, exc_info=True)

    # Poll the verification pane for VERIFIED or FLAGGED
    try:
        content = poll_for_verdict(
            verify_pane,
            verdicts=_VERIFICATION_VERDICTS,
            keywords=_VERIFICATION_VERDICTS,
            grace_period=_VERDICT_GRACE_PERIOD,
            poll_interval=_POLL_INTERVAL,
            tick_interval=_TICK_INTERVAL,
            log_prefix=f"qa-verify-{scenario.index}",
        )
    except Exception:
        _log.warning("Verification: polling failed for scenario %d",
                     scenario.index, exc_info=True)
        content = None

    # Clean up the verification pane now that polling is done
    try:
        pane_registry.kill_and_unregister(session, verify_pane)
        if win_id:
            pane_layout.rebalance(session, win_id)
    except Exception:
        _log.debug("Verification: cleanup failed for scenario %d pane",
                   scenario.index, exc_info=True)

    # Parse the result
    passed, reason = True, ""
    if content:
        v = extract_verdict_from_content(
            content,
            verdicts=_VERIFICATION_VERDICTS,
            keywords=_VERIFICATION_VERDICTS,
            log_prefix=f"qa-verify-{scenario.index}",
        )
        if v == "VERIFIED":
            _log.info("Verification: scenario %d VERIFIED", scenario.index)
        elif v == "FLAGGED":
            # Extract reason from content — look for lines before FLAGGED
            reason_lines = []
            for line in content.strip().splitlines():
                cleaned = re.sub(r'[*`]', '', line).strip()
                if cleaned == "FLAGGED":
                    break
                if cleaned and cleaned not in _VERIFICATION_VERDICTS:
                    reason_lines.append(cleaned)
            reason = " ".join(reason_lines[-3:]) if reason_lines else (
                "Scenario did not properly exercise test cases"
            )
            _log.info("Verification: scenario %d FLAGGED: %s",
                      scenario.index, reason)
            passed = False
        else:
            _log.warning("Verification: unexpected verdict %r for scenario %d, "
                         "trusting original", v, scenario.index)
    else:
        _log.warning("Verification: pane disappeared or timed out for "
                     "scenario %d, trusting original", scenario.index)

    return passed, reason


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
    _qa_planning_resolution = _resolve_qa_model(pr_data, store.load(pm_root), session_type="qa_planning")

    state.running = True
    session = get_pm_session()
    if not session:
        _log.error("No pm session found")
        state.running = False
        state.latest_verdict = "ERROR"
        state.latest_output = "No pm session found"
        return state

    window_name = _compute_qa_window_name(pr_data)
    data = store.load(pm_root)

    # Find the PR entry inside the freshly loaded data so _ensure_workdir
    # updates the same dict that gets saved.
    pr_id = pr_data.get("id", state.pr_id)
    live_pr = next((p for p in data.get("prs", []) if p.get("id") == pr_id), None)
    if live_pr is None:
        _log.error("QA aborted: PR %s not found in project data", pr_id)
        state.running = False
        state.latest_verdict = "ERROR"
        state.latest_output = f"PR {pr_id} not found in project data"
        return state

    workdir_path = live_pr.get("workdir")
    if not workdir_path or not Path(workdir_path).is_dir():
        from pm_core.cli.helpers import _ensure_workdir
        workdir_path = _ensure_workdir(data, live_pr, pm_root)
    if not workdir_path or not Path(workdir_path).is_dir():
        _log.error("QA aborted: workdir for %s does not exist and could not be created", state.pr_id)
        state.running = False
        state.latest_verdict = "ERROR"
        state.latest_output = f"Workdir for {state.pr_id} does not exist on this machine and could not be created"
        return state

    # Create QA workdir
    if not state.qa_workdir:
        qa_wd = create_qa_workdir(state.pr_id, state.loop_id)
        state.qa_workdir = str(qa_wd)

    # Status file path (inside QA workdir)
    status_path = Path(state.qa_workdir) / "qa_status.json"

    # Determine execution mode (container vs tmux) early — needed by both
    # the planning phase (orphan cleanup, Scenario 0) and execution phase.
    from pm_core.container import is_container_mode_enabled, _docker_available
    use_containers = is_container_mode_enabled()
    if use_containers:
        if _docker_available():
            _log.info("Container mode enabled for QA execution")
        else:
            _log.warning("Container mode enabled but Docker unavailable "
                         "— falling back to host execution")
            use_containers = False

    def _notify():
        if on_update:
            on_update(state)

    # --- Phase 1: Planning (if no scenarios pre-loaded) ---
    if state.planning_phase and not state.scenarios:
        _log.info("QA planning phase for %s", state.pr_id)
        state.latest_output = "Planning QA scenarios..."
        _notify()

        scenario_start = _next_scenario_offset(state.pr_id, state.loop_id) + 1
        planner_prompt = prompt_gen.generate_qa_planner_prompt(
            data, state.pr_id, session,
            scenario_start=scenario_start,
        )
        cmd = build_claude_shell_cmd(
            prompt=planner_prompt,
            model=_qa_planning_resolution.model, provider=_qa_planning_resolution.provider, effort=_qa_planning_resolution.effort)

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

        # Clean up orphaned containers from previous runs whose tmux
        # windows no longer exist.
        if use_containers:
            from pm_core import container as container_mod
            _stag = session.removeprefix("pm-") if session else None
            container_mod.cleanup_orphaned_qa_containers(
                session, state.pr_id, session_tag=_stag)

        # Launch Scenario 0 (interactive) right after stale cleanup so
        # the user can start exploring while the planner runs.
        repo_root_early = (Path(workdir_path)
                           if workdir_path and Path(workdir_path).is_dir()
                           else None)
        if not state.scenario_0:
            state.scenario_0 = _launch_scenario_0(
                state, data, pr_data, session, repo_root_early, workdir_path,
            )
            if state.scenario_0:
                state.latest_output = "Scenario 0 (interactive) ready"
                _notify()
                _write_status_file(status_path, state.pr_id, state.scenarios,
                                   state.scenario_verdicts,
                                   scenario_0=state.scenario_0)

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
        # Strategy: capture pane content, look for QA_PLAN_END, then
        # try parsing.  The prompt template also contains QA_PLAN_END
        # with placeholder scenarios, so we only accept when parsing
        # yields real (non-placeholder) scenarios.  This avoids the
        # false-positive from the prompt's own markers.
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

            if has_end and elapsed >= _PLANNER_GRACE:
                # Try parsing — only accept if we get real scenarios
                trial = parse_qa_plan(content)
                if trial:
                    _log.info("planner poll: parsed %d scenario(s), accepting",
                              len(trial))
                    state.plan_output = content
                    plan_found = True
                    break
                else:
                    _log.info("planner poll: has_end but 0 scenarios, "
                              "likely prompt template — continuing")

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

        # Verify scenario numbering starts at scenario_start.
        # The planner is told to start from scenario_start, but if it
        # didn't follow instructions, renumber to be safe.
        expected = scenario_start
        needs_renumber = False
        for sc in state.scenarios:
            if sc.index != expected:
                needs_renumber = True
                break
            expected += 1
        if needs_renumber:
            _log.info("Renumbering %d scenario(s) to start at %d "
                      "(planner used wrong numbering)",
                      len(state.scenarios), scenario_start)
            for i, sc in enumerate(state.scenarios):
                sc.index = scenario_start + i

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

    repo_root = Path(workdir_path) if workdir_path and Path(workdir_path).is_dir() else None

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
                       state.scenario_verdicts,
                       scenario_0=state.scenario_0)

    state.latest_output = f"Running {len(state.scenarios)} scenario(s)..."
    _notify()

    # --- Poll for verdicts (always via tmux — containers also use tmux windows) ---
    _poll_tmux_verdicts(state, data, pr_data, session, workdir_path,
                        status_path, _notify)

    # --- Cleanup ---
    # Keep scenario windows AND containers alive so users can inspect
    # results, review logs, and debug issues after the verdict.
    # Orphaned containers (whose windows have been closed) are cleaned
    # up at the start of the next QA run instead.

    # --- Aggregate verdicts ---
    verdicts = list(state.scenario_verdicts.values())

    # Determine overall verdict
    if VERDICT_NEEDS_WORK in verdicts:
        state.latest_verdict = VERDICT_NEEDS_WORK
    elif VERDICT_INPUT_REQUIRED in verdicts:
        state.latest_verdict = VERDICT_INPUT_REQUIRED
    else:
        state.latest_verdict = VERDICT_PASS

    # Write final status file with overall verdict
    _write_status_file(status_path, state.pr_id, state.scenarios,
                       state.scenario_verdicts, overall=state.latest_verdict,
                       scenario_0=state.scenario_0)

    state.running = False
    summary_parts = []
    for s in state.scenarios:
        v = state.scenario_verdicts.get(s.index, "?")
        summary_parts.append(f"{s.title}: {v}")
    state.latest_output = f"QA complete: {state.latest_verdict} — " + "; ".join(summary_parts)

    _log.info("QA complete for %s: %s",
              state.pr_id, state.latest_verdict)
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
