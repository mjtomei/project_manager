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
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pm_core import qa_instructions
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
_DEFAULT_VERIFICATION_MAX_RETRIES = 3


def _get_max_scenarios() -> int:
    """Read qa-max-scenarios from global settings, or _DEFAULT_MAX_SCENARIOS."""
    from pm_core.paths import get_global_setting_value
    val = get_global_setting_value("qa-max-scenarios", "")
    try:
        return max(0, int(val))
    except ValueError:
        return _DEFAULT_MAX_SCENARIOS


def _get_verification_max_retries() -> int:
    """Read qa-verify-retries from global settings (default: 3)."""
    from pm_core.paths import get_global_setting_value
    val = get_global_setting_value("qa-verify-retries", "")
    try:
        return max(0, int(val))
    except ValueError:
        return _DEFAULT_VERIFICATION_MAX_RETRIES


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
    pane_id: str | None = None
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

    Scans ``~/.pm/workdirs/qa/{pr_id}-*/s-*`` dirs (excluding the
    current run) to find the max index, so new scenarios continue numbering
    from where previous runs left off.
    """
    qa_root = Path.home() / ".pm" / "workdirs" / "qa"
    max_idx = 0
    for d in qa_root.glob(f"{pr_id}-*/s-*"):
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
                            branch: str = "") -> tuple[Path, Path]:
    """Create an isolated working area for one QA scenario.

    Everything for a single scenario lives under one directory::

        {qa_workdir}/s-{N}/
            repo/       — ``git clone --local`` of the target repo
            scratch/    — empty dir for throwaway test projects

    The clone checks out *branch* (the PR branch) so the scenario can
    commit and push fixes directly.

    Falls back to a plain empty directory when *repo_root* is None (legacy).

    Returns ``(clone_path, scratch_path)``.
    """
    from pm_core import git_ops

    scenario_dir = qa_workdir / f"s-{scenario_index}"
    scenario_dir.mkdir(parents=True, exist_ok=True)

    scratch = scenario_dir / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    if repo_root is None:
        repo_dir = scenario_dir / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        return repo_dir, scratch

    clone_path = scenario_dir / "repo"

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

    return clone_path, scratch


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

# Number of lines before the verdict to use as a fingerprint for
# detecting stale re-detections of the same verdict.
_VERDICT_CONTEXT_LINES = 5


def _verdict_context_fingerprint(content: str, verdict: str) -> str:
    """Return the lines immediately before *verdict* in *content*.

    Searches from the bottom of *content* (matching the behaviour of
    ``extract_verdict_from_content``) and returns the
    ``_VERDICT_CONTEXT_LINES`` lines that precede the verdict keyword.
    Two captures with the same fingerprint mean the verdict hasn't
    changed — it's the same stale output.
    """
    lines = content.strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        cleaned = re.sub(r'[*`]', '', lines[i]).strip()
        if cleaned == verdict:
            start = max(0, i - _VERDICT_CONTEXT_LINES)
            return "\n".join(lines[start:i])
    return ""


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
                       verifying_scenarios: set[int] | None = None,
                       queued_scenarios: set[int] | None = None,
                       verification_failures: dict[int, int] | None = None) -> None:
    """Atomically write the qa_status.json file."""
    _verifying = verifying_scenarios or set()
    _queued = queued_scenarios or set()
    _verify_fails = verification_failures or {}
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
        fails = _verify_fails.get(s.index, 0)
        if s.index in _verifying:
            if fails:
                verdict = f"{verdict} (verifying:{fails})" if verdict else f"verifying:{fails}"
            else:
                verdict = f"{verdict} (verifying)" if verdict else "verifying"
        elif s.index in _queued:
            verdict = "queued"
        elif not verdict and fails:
            # Back to pending after verification flagged it — show retry count
            verdict = f"(retrying:{fails})"
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

def parse_qa_plan(output: str, pm_root: Path | None = None) -> list[QAScenario]:
    """Parse planner output into a list of QAScenarios.

    Expected format (ALL CAPS markers, no markdown):

    QA_PLAN_START

    SCENARIO 1: Scenario Title
    FOCUS: What to test
    INSTRUCTION: filename.md (optional)
    STEPS: Key test steps

    SCENARIO 2: ...

    QA_PLAN_END

    When *pm_root* is provided, INSTRUCTION values are resolved against the
    instruction library with fuzzy matching.  The stored ``instruction_path``
    is a relative path like ``instructions/foo.md`` (relative to ``pm/qa/``).
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
            raw_ref = instr_m.group(1).strip()
            if raw_ref.lower() not in ("none", "n/a", "-"):
                if pm_root is not None:
                    resolved = qa_instructions.resolve_instruction_ref(
                        pm_root, raw_ref)
                    if resolved:
                        category, fname = resolved
                        instruction_path = f"{category}/{fname}"
                        if fname != Path(raw_ref).name:
                            _log.info(
                                "Scenario %d: fuzzy-matched instruction "
                                "%r -> %s", index, raw_ref, instruction_path,
                            )
                    else:
                        _log.warning(
                            "Scenario %d references unknown instruction "
                            "%r — ignoring INSTRUCTION field", index,
                            raw_ref,
                        )
                else:
                    # No pm_root for resolution — store raw value
                    instruction_path = raw_ref

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

    session_type should be "qa_planning" for the planner, "qa_scenario"
    for scenario workers, or "qa_verification" for the verification step.
    Falls back to "qa" config if the specific type is not configured.
    """
    from pm_core.model_config import resolve_model_and_provider, get_pr_model_override
    return resolve_model_and_provider(
        session_type,
        pr_model=get_pr_model_override(pr_data),
        project_data=project_data,
    )


# ---------------------------------------------------------------------------
# Step concretization — verify planned steps against actual code
# ---------------------------------------------------------------------------

_CONCRETIZE_VERDICTS = ("REFINED_STEPS_END",)
_CONCRETIZE_KEYWORDS = ("REFINED_STEPS_START", "REFINED_STEPS_END")
_CONCRETIZE_GRACE = 15


def _build_concretization_prompt(scenario: QAScenario, pr_branch: str,
                                  base_branch: str) -> str:
    """Build a prompt that verifies and refines scenario steps against code."""
    return f"""You are refining the test steps for QA scenario {scenario.index}: "{scenario.title}"

## Scenario

**Focus**: {scenario.focus}

**Planned steps**:
{scenario.steps}

## Your Task

The steps are a rough draft generated by a planner. There may be mistakes in
commands, file paths, function names, or expected outputs.  Your job is
to verify each step against the actual codebase and produce corrected
steps. You can also add or remove steps.

## Output Format

Output the refined steps between markers:

REFINED_STEPS_START
<your corrected steps here — numbered, concrete, executable>
REFINED_STEPS_END

IMPORTANT: Your response must end with REFINED_STEPS_END. Do not include any text after it."""


def _build_concretize_cmd(
    scenario: QAScenario,
    pr_data: dict,
    project_data: dict,
    cwd: str,
    container_name: str | None = None,
) -> str:
    """Build the shell command for the concretization step."""
    from pm_core.claude_launcher import build_claude_shell_cmd

    resolution = _resolve_qa_model(pr_data, project_data,
                                   session_type="qa_scenario")
    base_branch = project_data.get("project", {}).get("base_branch", "master")
    pr_branch = pr_data.get("branch", "")

    prompt = _build_concretization_prompt(scenario, pr_branch, base_branch)
    claude_cmd = build_claude_shell_cmd(
        prompt=prompt,
        model=resolution.model, provider=resolution.provider,
        effort=resolution.effort, cwd=cwd,
    )

    if container_name:
        from pm_core import container as container_mod
        return container_mod.build_exec_cmd(
            container_name, claude_cmd, cleanup=False)
    return claude_cmd


def _concretize_scenario(
    scenario: QAScenario,
    pr_data: dict,
    project_data: dict,
    pane_id: str,
) -> str | None:
    """Poll a concretization pane and return refined steps.

    The concretizer command should already be running in *pane_id*.
    Polls for REFINED_STEPS_END and extracts the refined steps.
    Returns None if concretization failed/timed out.
    The pane is left open for user review.
    """
    from pm_core import tmux as tmux_mod

    base_branch = project_data.get("project", {}).get("base_branch", "master")
    pr_branch = pr_data.get("branch", "")
    prompt = _build_concretization_prompt(scenario, pr_branch, base_branch)

    _log.info("Concretization started for scenario %d in pane %s",
              scenario.index, pane_id)

    # Poll for REFINED_STEPS_END — uses prompt_text filtering to skip
    # the example marker in the prompt itself.
    content = poll_for_verdict(
        pane_id,
        verdicts=_CONCRETIZE_VERDICTS,
        keywords=_CONCRETIZE_KEYWORDS,
        prompt_text=prompt,
        grace_period=_CONCRETIZE_GRACE,
        poll_interval=_POLL_INTERVAL,
        tick_interval=_TICK_INTERVAL,
        log_prefix=f"qa-concretize-{scenario.index}",
    )

    if not content:
        _log.warning("Concretization timed out or pane died for scenario %d",
                     scenario.index)
        return None

    # Parse refined steps — use extract_between_markers which finds the
    # last START/END pair (skipping the prompt's example markers).
    from pm_core.loop_shared import extract_between_markers
    refined = extract_between_markers(
        content, "REFINED_STEPS_START", "REFINED_STEPS_END")
    if refined:
        _log.info("Concretization produced %d chars of refined steps "
                  "for scenario %d", len(refined), scenario.index)
        return refined

    _log.warning("Concretization output missing REFINED_STEPS markers "
                 "for scenario %d", scenario.index)
    return None


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
        clone_path, scratch_path = create_scenario_workdir(
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

    final_cmd = build_claude_shell_cmd(
        prompt=child_prompt,
        model=_qa_resolution.model, provider=_qa_resolution.provider, effort=_qa_resolution.effort)
    scenario_cwd = str(clone_path) if repo_root else workdir_path

    win_name = _scenario_window_name(pr_data, 0)
    try:
        pane_id = tmux_mod.new_window_get_pane(session, win_name, final_cmd,
                                               cwd=scenario_cwd, switch=False)
        scenario.window_name = win_name
        scenario.pane_id = pane_id
    except Exception:
        _log.warning("Failed to create window for Scenario 0")
        return None

    _log.info("Launched Scenario 0 (interactive) in window %s", win_name)
    return scenario


# ---------------------------------------------------------------------------
# Scenario launching helpers
# ---------------------------------------------------------------------------

def _install_instruction_file(pm_root: Path, scenario: QAScenario,
                              scratch_path: Path,
                              scratch_dir: str) -> None:
    """Copy the instruction file into the scenario's scratch area.

    The instruction library lives in the pm project, not in the target repo.
    This copies the referenced file into ``{scratch_path}/qa-instructions/``
    and rewrites ``scenario.instruction_path`` to the absolute path as seen
    by the agent (``{scratch_dir}/qa-instructions/{filename}``).

    *scratch_path* is the host-side path; *scratch_dir* is the path the
    agent sees (same on host, ``/scratch`` in containers).
    """
    if not scenario.instruction_path:
        return
    # instruction_path is e.g. "instructions/tui-manual-test.md"
    src = pm_root / "qa" / scenario.instruction_path
    if not src.is_file():
        _log.warning("Instruction file %s not found — clearing instruction_path",
                      src)
        scenario.instruction_path = None
        return
    dest_dir = scratch_path / "qa-instructions"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    import shutil
    shutil.copy2(src, dest)
    scenario.instruction_path = f"{scratch_dir}/qa-instructions/{src.name}"
    _log.info("Copied instruction %s -> %s", src, dest)


def _launch_scenarios_in_tmux(
    state: QALoopState,
    data: dict,
    pr_data: dict,
    session: str,
    repo_root: Path | None,
    workdir_path: str,
    pm_root: Path | None = None,
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
            clone_path, scratch_path = create_scenario_workdir(
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

        if pm_root:
            _install_instruction_file(pm_root, scenario, scratch_path,
                                      scratch_dir=str(scratch_path))

        scenario_cwd = str(clone_path) if repo_root else workdir_path
        transcript = _scenario_transcript_path(state.qa_workdir, scenario.index)

        win_name = _scenario_window_name(pr_data, scenario.index)

        # Create window with concretizer command
        concretize_cmd = _build_concretize_cmd(
            scenario, pr_data, data, cwd=scenario_cwd)
        try:
            concretize_pane = tmux_mod.new_window_get_pane(
                session, win_name, concretize_cmd,
                cwd=scenario_cwd, switch=False)
        except Exception:
            concretize_pane = None
        if not concretize_pane:
            _log.warning("Failed to create window for scenario %d",
                         scenario.index)
            continue

        # Poll concretization for refined steps
        refined_steps = _concretize_scenario(
            scenario, pr_data, data, concretize_pane,
        )
        if refined_steps:
            scenario.steps = refined_steps

        # Launch the main scenario in a split pane
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

        try:
            scenario_pane = tmux_mod.split_pane_at(
                concretize_pane, "v", child_cmd, background=True)
            scenario.window_name = win_name
            scenario.pane_id = scenario_pane
            scenario.transcript_path = transcript
        except Exception:
            _log.warning("Failed to split scenario pane for scenario %d",
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
    pm_root: Path | None = None,
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
            clone_path, scratch_path = create_scenario_workdir(
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

        # Copy instruction file into scratch (mounted at /scratch in container)
        if pm_root:
            _install_instruction_file(pm_root, scenario, scratch_path,
                                      scratch_dir=container_scratch)

        # Transcript symlink lives on the host; cwd must match what Claude
        # sees inside the container so the mangled project dir is correct.
        transcript = _scenario_transcript_path(state.qa_workdir, scenario.index)

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

        win_name = _scenario_window_name(pr_data, scenario.index)

        # Create window with concretizer command (runs inside container)
        concretize_cmd = _build_concretize_cmd(
            scenario, pr_data, data, cwd=container_workdir,
            container_name=cname)
        try:
            concretize_pane = tmux_mod.new_window_get_pane(
                session, win_name, concretize_cmd,
                cwd=workdir_path, switch=False)
        except Exception:
            concretize_pane = None
        if not concretize_pane:
            _log.warning("Failed to create window for scenario %d",
                         scenario.index)
            continue

        # Poll concretization for refined steps
        refined_steps = _concretize_scenario(
            scenario, pr_data, data, concretize_pane,
        )
        if refined_steps:
            scenario.steps = refined_steps

        # Launch the main scenario in a split pane
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

        # cleanup=False: containers stay alive with their windows; orphans
        # are cleaned up at the start of the next QA run.
        exec_cmd = container_mod.build_exec_cmd(cname, claude_cmd, cleanup=False)
        try:
            scenario_pane = tmux_mod.split_pane_at(
                concretize_pane, "v", exec_cmd, background=True)
            scenario.window_name = win_name
            scenario.pane_id = scenario_pane
            scenario.transcript_path = transcript
        except Exception:
            _log.warning("Failed to split scenario pane for scenario %d",
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
            pane_id = tmux_mod.new_window_get_pane(session, win_name, exec_cmd,
                                                   cwd=workdir_path, switch=False)
        else:
            # Host mode — worktree still exists
            wt_path = scenario.worktree_path or workdir_path
            child_prompt = prompt_gen.generate_qa_child_prompt(
                data, state.pr_id, scenario,
                workdir=str(wt_path),
                session_name=session,
                worktree_mode=bool(scenario.worktree_path),
                scratch_dir=str(Path(state.qa_workdir) / f"s-{scenario.index}" / "scratch"),
            )
            child_cmd = build_claude_shell_cmd(
                prompt=child_prompt,
                model=_qa_resolution.model, provider=_qa_resolution.provider, effort=_qa_resolution.effort,
                transcript=transcript, cwd=str(wt_path))
            pane_id = tmux_mod.new_window_get_pane(session, win_name, child_cmd,
                                                   cwd=str(wt_path), switch=False)

        scenario.window_name = win_name
        scenario.pane_id = pane_id
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
    queued_scenarios: list[QAScenario] | None = None,
    concurrency_cap: int = 0,
    use_containers: bool = False,
    repo_root: Path | None = None,
    pm_root: Path | None = None,
) -> None:
    """Poll tmux scenario windows for verdicts.

    When a PASS verdict is accepted, verification runs in a split pane
    to check that the scenario genuinely exercised its test cases.  If
    verification flags a scenario, a follow-up message is sent to the
    scenario's pane and the scenario goes back to pending.

    If *queued_scenarios* is provided, queued scenarios are launched as
    running scenarios complete, respecting *concurrency_cap*.
    """
    from pm_core import tmux as tmux_mod

    verify_enabled = _is_verification_enabled()
    verify_max_retries = _get_verification_max_retries()
    if verify_enabled:
        _log.info("PASS verdict verification is enabled (max retries: %d)",
                  verify_max_retries)
    else:
        _log.info("PASS verdict verification is disabled (qa-verify-pass)")

    # Queue of scenarios waiting to be launched
    _launch_queue: list[QAScenario] = list(queued_scenarios or [])
    _queued_indices: set[int] = {s.index for s in _launch_queue}

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
    # Fingerprint of the lines before the verdict when it was last
    # accepted — used to detect stale re-detections.
    verdict_context: dict[int, str] = {}

    # Scenarios that failed to create a window get INPUT_REQUIRED immediately
    # (but skip queued scenarios — they don't have windows yet by design)
    has_failed_creation = False
    for scenario in state.scenarios:
        if not scenario.window_name and scenario.index not in _queued_indices:
            _log.warning("Scenario %d has no window — marking INPUT_REQUIRED",
                         scenario.index)
            state.scenario_verdicts[scenario.index] = VERDICT_INPUT_REQUIRED
            has_failed_creation = True
    if has_failed_creation:
        _write_status_file(status_path, state.pr_id, state.scenarios,
                           state.scenario_verdicts,
                           scenario_0=state.scenario_0,
                           queued_scenarios=_queued_indices)

    grace_start = time.monotonic()

    def _run_verification(scenario: QAScenario, verdict: str, content: str):
        """Background thread: run verification in a visible pane."""
        _log.info("Verification thread started for scenario %d (%s), "
                  "scenario.pane_id=%s, scenario.window_name=%s",
                  scenario.index, scenario.title,
                  scenario.pane_id, scenario.window_name)
        try:
            passed, reason, _vpane = _verify_single_scenario(
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

    def _launch_next_queued():
        """Launch the next queued scenario if concurrency allows."""
        if not _launch_queue:
            return
        # Count currently active (pending + verifying)
        active = len(pending) + len(verifying)
        if concurrency_cap > 0 and active >= concurrency_cap:
            return
        scenario = _launch_queue.pop(0)
        _queued_indices.discard(scenario.index)
        _log.info("Launching queued scenario %d (%s), %d remain in queue",
                  scenario.index, scenario.title, len(_launch_queue))
        # Launch this single scenario by temporarily swapping state.scenarios
        orig = state.scenarios
        state.scenarios = [scenario]
        if use_containers:
            _launch_scenarios_in_containers(
                state, data, pr_data, session, repo_root, workdir_path,
                pm_root=pm_root,
            )
        else:
            _launch_scenarios_in_tmux(
                state, data, pr_data, session, repo_root, workdir_path,
                pm_root=pm_root,
            )
        state.scenarios = orig
        if scenario.window_name:
            pending.add(scenario.index)
        else:
            # Window creation failed — mark INPUT_REQUIRED so this
            # scenario isn't silently lost (which could cause a false
            # overall PASS).
            _log.warning("Queued scenario %d window creation failed — "
                         "marking INPUT_REQUIRED", scenario.index)
            state.scenario_verdicts[scenario.index] = VERDICT_INPUT_REQUIRED

    # Fill any open slots that were freed by initial workdir failures.
    # Scenarios that fail workdir creation are marked INPUT_REQUIRED without
    # entering ``pending``, so their slots would otherwise stay empty until
    # a later verdict triggers ``_launch_next_queued``.
    for _ in range(len(_launch_queue)):
        _launch_next_queued()  # returns immediately once cap is reached

    while (pending or verifying or _launch_queue) and not state.stop_requested:
        time.sleep(_POLL_INTERVAL)

        in_grace = (time.monotonic() - grace_start) < _VERDICT_GRACE_PERIOD
        verdicts_changed = False

        # Check for completed verifications
        with verification_lock:
            completed_verifications = dict(verification_results)
            verification_results.clear()

        for scenario_idx, (passed, reason) in completed_verifications.items():
            verifying.discard(scenario_idx)
            scenario = next(
                (s for s in state.scenarios if s.index == scenario_idx), None
            )
            if scenario is None:
                _log.warning("Verification result for unknown scenario %d — ignoring",
                             scenario_idx)
                continue
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

                if fails > verify_max_retries:
                    # Too many verification failures — mark NEEDS_WORK
                    _log.warning("Scenario %d failed verification %d times — "
                                 "marking NEEDS_WORK", scenario_idx, fails)
                    state.scenario_verdicts[scenario_idx] = VERDICT_NEEDS_WORK
                    state.latest_output = (
                        f"Scenario {scenario_idx} ({scenario.title}): "
                        f"NEEDS_WORK (failed verification: {reason})"
                    )
                    verdicts_changed = True
                    _notify()
                else:
                    # Send the scenario a follow-up message and put back in pending.
                    # Use the stored pane_id to target the original scenario
                    # pane, not the verification pane that may now be pane 0.
                    pane_id = scenario.pane_id or _get_scenario_pane(session, scenario.window_name)
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
                        # Send extra Enters to ensure the message is
                        # submitted — sometimes newlines don't trigger.
                        for _ in range(2):
                            time.sleep(1)
                            tmux_mod.send_keys(pane_id, "")
                        _log.info("Sent follow-up message to scenario %d pane",
                                  scenario_idx)
                        # Clear verdict and put back in pending.
                        # Keep verdict_context so the old stale PASS is
                        # still recognised and skipped — only a genuinely
                        # new verdict (with different surrounding lines)
                        # will be accepted.
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
                                     "window gone, marking INPUT_REQUIRED",
                                     scenario_idx)
                        state.scenario_verdicts[scenario_idx] = VERDICT_INPUT_REQUIRED
                        state.latest_output = (
                            f"Scenario {scenario_idx} ({scenario.title}): "
                            f"INPUT_REQUIRED (window gone during verification)"
                        )
                        verdicts_changed = True
                        _notify()

        for scenario in state.scenarios:
            if scenario.index not in pending or not scenario.window_name:
                continue

            pane_id = scenario.pane_id or _get_scenario_pane(session, scenario.window_name)
            if pane_id and not tmux_mod.pane_exists(pane_id):
                pane_id = None
                scenario.pane_id = None
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
                _launch_next_queued()
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

            # Check if this is the same stale verdict we already
            # accepted by comparing the lines immediately before the
            # verdict keyword.  New output means a genuine re-verdict.
            if verdict:
                ctx = _verdict_context_fingerprint(content, verdict)
                prev_ctx = verdict_context.get(scenario.index)
                if prev_ctx is not None and ctx == prev_ctx:
                    # Same context before the verdict — stale, skip
                    continue

            key = f"qa-{state.pr_id}-{scenario.index}"
            if tracker.update(key, verdict):
                if verdict:
                    verdict_context[scenario.index] = _verdict_context_fingerprint(content, verdict)
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
                    # Scenario fully done — launch next queued if available
                    _launch_next_queued()

        # Launch queued scenarios after verified completions too
        if completed_verifications:
            _launch_next_queued()

        if verdicts_changed or completed_verifications:
            with verification_lock:
                verifying_snapshot = set(verifying)
            _write_status_file(status_path, state.pr_id, state.scenarios,
                               state.scenario_verdicts,
                               scenario_0=state.scenario_0,
                               verifying_scenarios=verifying_snapshot,
                               queued_scenarios=_queued_indices,
                               verification_failures=verification_failures)


# ---------------------------------------------------------------------------
# Verdict verification
# ---------------------------------------------------------------------------

# Maximum pane output lines to include in the verification prompt.
# Large outputs are truncated to keep the prompt manageable.
_VERIFICATION_MAX_PANE_LINES = 500


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
            # Keep both head and tail so the verifier sees setup AND verdict
            head_lines = _VERIFICATION_MAX_PANE_LINES // 4
            tail_lines = _VERIFICATION_MAX_PANE_LINES - head_lines
            omitted = len(lines) - head_lines - tail_lines
            text = (
                "\n".join(lines[:head_lines])
                + f"\n\n[... {omitted} lines omitted ...]\n\n"
                + "\n".join(lines[-tail_lines:])
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

### Step 1: Build a checklist

Before looking at what the scenario did, enumerate each numbered step from the scenario definition above. For each step, write a one-line summary of what concrete action or observation it requires. This is your checklist.

### Step 2: Match each step against the transcript

Go through your checklist and, for each step, find **specific evidence** in the transcript that the step was actually executed. Evidence means tool calls (Bash commands, file writes) and their results — not just the scenario's commentary or assertions about what it did.

Mark each step as:
- **DONE** — clear evidence the step was executed and succeeded
- **SKIPPED** — no evidence the step was attempted
- **SUBSTITUTED** — the scenario did something different from what the step asked for (e.g., wrote a unit test instead of running the described end-to-end workflow, or read code instead of executing it)
- **FAILED** — the step was attempted but produced errors or unexpected results

### Step 3: Make your judgment

- If ANY step is SKIPPED or SUBSTITUTED, the verdict is **FLAGGED**. A scenario that works around missing tools by substituting different methodology (e.g., unit tests instead of runtime testing, code review instead of execution) has not completed its steps — it should have reported INPUT_REQUIRED instead of PASS.
- If all steps are DONE but some FAILED, the verdict is **FLAGGED**.
- Only if all steps are DONE and succeeded is the verdict **VERIFIED**.

### Common false-pass patterns to watch for

- **Code reading as proof**: The scenario reads the source code, confirms the logic looks correct, and declares PASS — but never actually runs anything. Reading code is not testing.
- **Substituted methodology**: The scenario can't run the prescribed steps (e.g., a CLI tool isn't available), so it writes its own unit tests or mocks instead. Even if those tests pass, the scenario did not follow its steps.
- **Partial execution**: The scenario runs some steps but skips the hard ones (e.g., sets up a project but never starts the actual process under test).
- **Tests pass but wrong tests**: The scenario runs a pre-existing test suite and reports PASS, but the existing tests don't cover the specific behavior the scenario steps describe.

## Response Format

Present your step-by-step checklist with the DONE/SKIPPED/SUBSTITUTED/FAILED annotations, then respond with EXACTLY one of:

If the PASS is genuine:
VERIFIED

If the PASS is not justified, wrap your explanation in markers:
FLAGGED_START
<explanation of what went wrong — can be multiple lines>
FLAGGED_END

IMPORTANT: Your response must end with either VERIFIED or the FLAGGED_START...FLAGGED_END block. Do not include any text after your final verdict marker."""


_VERIFICATION_VERDICTS = ("VERIFIED", "FLAGGED_END")
_VERIFICATION_KEYWORDS = ("VERIFIED", "FLAGGED_START", "FLAGGED_END")


def _extract_flagged_reason(content: str) -> str:
    """Extract the reason text between FLAGGED_START and FLAGGED_END markers.

    Uses extract_between_markers which finds the *last* pair, skipping
    the prompt template's example markers.
    """
    from pm_core.loop_shared import extract_between_markers
    reason = extract_between_markers(
        content, "FLAGGED_START", "FLAGGED_END", require_end=False)
    return reason or "Scenario did not properly exercise test cases"


def _verify_single_scenario(
    scenario: QAScenario,
    verdict: str,
    pane_output: str,
    pr_data: dict,
    project_data: dict | None = None,
    session: str | None = None,
) -> tuple[bool, str, str | None]:
    """Verify a single scenario's verdict in a visible tmux pane.

    Splits the scenario's tmux window to create a verification pane
    running an interactive Claude session.  The user can see the
    verification happening live.  Polls the pane for VERIFIED/FLAGGED,
    then closes it.

    Returns (passed, reason, verify_pane_id) where passed is True if the scenario was
    verified, and reason is the explanation if it was flagged.

    If the scenario has a transcript file (``.jsonl`` written by Claude
    CLI), the verifier is pointed at that file so it can read the full
    structured session.  Otherwise the pane output is inlined with
    truncation as a fallback.
    """
    from pm_core import tmux as tmux_mod
    from pm_core.claude_launcher import build_claude_shell_cmd

    resolution = _resolve_qa_model(pr_data, project_data,
                                   session_type="qa_verification")

    # Prefer the transcript file if it exists.  Do NOT finalize (copy)
    # the symlink — the scenario may still be running (e.g. after a
    # verification follow-up) and the live symlink target has the latest
    # content.  Resolve the symlink so the verifier reads the live file.
    transcript_path = scenario.transcript_path
    if transcript_path:
        tp = Path(transcript_path)
        if tp.is_symlink():
            resolved = str(tp.resolve())
            if Path(resolved).exists():
                transcript_path = resolved
            else:
                transcript_path = None
        elif not tp.exists():
            transcript_path = None
        if not transcript_path:
            _log.warning("Transcript for scenario %d not found at %s, "
                         "falling back to pane output",
                         scenario.index, scenario.transcript_path)

    prompt = _build_verification_prompt(
        scenario, verdict,
        pane_output_path=transcript_path,
        pane_output=pane_output if not transcript_path else None,
    )

    # Find the scenario's pane to split — prefer stored pane_id
    scenario_pane = scenario.pane_id or (
        _get_scenario_pane(session, scenario.window_name) if session else None
    )
    if not scenario_pane:
        _log.warning("Verification: cannot find scenario %d pane, "
                     "trusting original verdict", scenario.index)
        return True, "", None

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

    _log.info("Verification: splitting pane %s for scenario %d (%s) "
              "[source=%s]",
              scenario_pane, scenario.index, scenario.title,
              "transcript" if transcript_path else "pane")
    try:
        verify_pane = tmux_mod.split_pane_at(
            scenario_pane, "v", verify_cmd, background=True,
        )
    except Exception:
        _log.warning("Verification: failed to split pane for scenario %d, "
                     "trusting original verdict",
                     scenario.index, exc_info=True)
        return True, "", None
    _log.info("Verification: created verify_pane=%s for scenario %d "
              "(split from scenario_pane=%s)",
              verify_pane, scenario.index, scenario_pane)

    # Register the pane and rebalance using the same pattern as the
    # review window: register panes, reset user_modified, then rebalance.
    win_id = None
    try:
        win_id = tmux_mod.pane_window_id(scenario_pane)
        if win_id:
            tmux_mod.set_shared_window_size(session, win_id)
            pane_registry.register_pane(
                session, win_id, verify_pane,
                f"qa-verify-s{scenario.index}", verify_cmd,
            )
            # Reset user_modified so rebalance works correctly (the
            # after-split-window hook sets it before panes are registered).
            reg = pane_registry.load_registry(session)
            wdata = pane_registry.get_window_data(reg, win_id)
            wdata["user_modified"] = False
            pane_registry.save_registry(session, reg)
            pane_layout.rebalance(session, win_id)
    except Exception:
        _log.debug("Verification: registration/rebalance failed for "
                   "scenario %d, continuing with polling",
                   scenario.index, exc_info=True)

    # Poll the verification pane for VERIFIED or FLAGGED.
    # Pass prompt_text so the prompt's example FLAGGED_END marker
    # is filtered out — only the verifier's actual output counts.
    _log.info("Verification: polling verify_pane=%s for scenario %d "
              "(prompt_text=%d chars)",
              verify_pane, scenario.index, len(prompt))
    try:
        content = poll_for_verdict(
            verify_pane,
            verdicts=_VERIFICATION_VERDICTS,
            keywords=_VERIFICATION_KEYWORDS,
            prompt_text=prompt,
            grace_period=_VERDICT_GRACE_PERIOD,
            poll_interval=_POLL_INTERVAL,
            tick_interval=_TICK_INTERVAL,
            log_prefix=f"qa-verify-{scenario.index}",
        )
    except Exception:
        _log.warning("Verification: polling failed for scenario %d",
                     scenario.index, exc_info=True)
        content = None

    # Leave the verification pane open so the user can review it.
    # It will be cleaned up when the scenario window is killed.

    # Parse the result
    passed, reason = True, ""
    if content:
        _log.info("Verification: got %d chars of content from verify_pane=%s "
                  "for scenario %d", len(content), verify_pane, scenario.index)
        v = extract_verdict_from_content(
            content,
            verdicts=_VERIFICATION_VERDICTS,
            keywords=_VERIFICATION_KEYWORDS,
            prompt_text=prompt,
            log_prefix=f"qa-verify-{scenario.index}",
        )
        if v == "VERIFIED":
            _log.info("Verification: scenario %d VERIFIED", scenario.index)
        elif v == "FLAGGED_END":
            # Extract reason between FLAGGED_START and FLAGGED_END markers
            reason = _extract_flagged_reason(content)
            _log.info("Verification: scenario %d FLAGGED: %s",
                      scenario.index, reason)
            passed = False
        else:
            _log.warning("Verification: unexpected verdict %r for scenario %d "
                         "(verify_pane=%s), trusting original",
                         v, scenario.index, verify_pane)
    else:
        _log.warning("Verification: pane disappeared or timed out for "
                     "scenario %d (verify_pane=%s), trusting original",
                     scenario.index, verify_pane)

    return passed, reason, verify_pane


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
                trial = parse_qa_plan(content, pm_root=pm_root)
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
            state.scenarios = parse_qa_plan(state.plan_output, pm_root=pm_root)
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

        state.planning_phase = False
        state.latest_output = f"Plan: {len(state.scenarios)} scenario(s)"
        _notify()

    # --- Phase 2: Execution ---
    # Determine concurrency cap (0 = launch all at once)
    concurrency_cap = max_scenarios if max_scenarios is not None else _get_max_scenarios()
    if concurrency_cap > 0:
        launch_scenarios = state.scenarios[:concurrency_cap]
        queued_scenarios = state.scenarios[concurrency_cap:]
    else:
        launch_scenarios = state.scenarios
        queued_scenarios = []

    _log.info("QA execution phase: %d scenarios for %s (%d to launch, %d queued)",
              len(state.scenarios), state.pr_id,
              len(launch_scenarios), len(queued_scenarios))

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

    # Only launch the initial batch — queued scenarios are launched later
    # as running scenarios complete (handled by _poll_tmux_verdicts).
    all_scenarios = state.scenarios
    state.scenarios = launch_scenarios
    if use_containers:
        _launch_scenarios_in_containers(
            state, data, pr_data, session, repo_root, workdir_path,
            pm_root=pm_root,
        )
    else:
        _launch_scenarios_in_tmux(
            state, data, pr_data, session, repo_root, workdir_path,
            pm_root=pm_root,
        )
    state.scenarios = all_scenarios

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
                qa_win_id = tmux_mod.pane_window_id(planner_pane)
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

    # Mark queued scenarios in the status file
    queued_indices = {s.index for s in queued_scenarios}

    # Write initial status file
    _write_status_file(status_path, state.pr_id, state.scenarios,
                       state.scenario_verdicts,
                       scenario_0=state.scenario_0,
                       queued_scenarios=queued_indices)

    state.latest_output = f"Running {len(state.scenarios)} scenario(s)..."
    _notify()

    # --- Poll for verdicts (always via tmux — containers also use tmux windows) ---
    _poll_tmux_verdicts(state, data, pr_data, session, workdir_path,
                        status_path, _notify,
                        queued_scenarios=queued_scenarios,
                        concurrency_cap=concurrency_cap,
                        use_containers=use_containers,
                        repo_root=repo_root,
                        pm_root=pm_root)

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
