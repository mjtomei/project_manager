"""Unit tests for QA finalize wiring in qa_loop.py and qa_finalize_prompt.py.

Covers:
- QALoopState.finalize_verdict default is None.
- build_qa_finalize_prompt content: all input fields rendered, both
  verdict tokens emitted as list items, empty-scenario and None-field
  rendering paths.
- _run_qa_finalize_pane None-return paths: missing workdir, missing
  tmux window, unverified PASS gate.
- run_qa_sync wiring of `state.finalize_verdict` and `[finalize: …]`
  suffix in `state.latest_output` — verified textually since driving
  the full pipeline would require monkeypatching >12 helpers and a
  live tmux/pm session (see NOTE below).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from pm_core.qa_finalize_prompt import build_qa_finalize_prompt
from pm_core.qa_loop import (
    QALoopState,
    QAScenario,
    _run_qa_finalize_pane,
)


# --- (a) -----------------------------------------------------------------

def test_finalize_verdict_default_none():
    state = QALoopState(pr_id="pr-test")
    assert state.finalize_verdict is None


# --- (b) -----------------------------------------------------------------

def test_build_qa_finalize_prompt_contains_all_fields():
    out = build_qa_finalize_prompt(
        pr_id="pr-abc",
        pr_title="Some title",
        branch="feat/x",
        pr_workdir="/tmp/wd",
        scenario_worktrees=[(1, "PASS", "/tmp/w1"),
                            (2, "NEEDS_WORK", "/tmp/w2")],
        overall_verdict="PASS",
    )
    for needle in ("pr-abc", "Some title", "feat/x", "/tmp/wd",
                   "PASS", "Scenario 1", "/tmp/w1",
                   "Scenario 2", "NEEDS_WORK", "/tmp/w2",
                   "FINALIZE_DONE", "FINALIZE_BLOCKED"):
        assert needle in out, f"missing {needle!r} in prompt"
    # Each verdict token begins a list item (line starts with "- `TOKEN`").
    assert re.search(r"^- `FINALIZE_DONE`", out, re.MULTILINE)
    assert re.search(r"^- `FINALIZE_BLOCKED`", out, re.MULTILINE)


# --- (c) -----------------------------------------------------------------

def test_build_qa_finalize_prompt_empty_scenarios():
    out = build_qa_finalize_prompt(
        pr_id="pr-x", pr_title="t", branch="b", pr_workdir="/wd",
        scenario_worktrees=[], overall_verdict="PASS",
    )
    assert "(no scenarios ran)" in out


# --- (d) -----------------------------------------------------------------

def test_build_qa_finalize_prompt_none_fields_render():
    out = build_qa_finalize_prompt(
        pr_id="pr-x", pr_title="t", branch="b", pr_workdir="/wd",
        scenario_worktrees=[(3, None, None)], overall_verdict="PASS",
    )
    assert "verdict=?" in out
    assert "worktree=(none)" in out


# --- (e) -----------------------------------------------------------------

def test_run_qa_finalize_pane_returns_none_when_workdir_missing():
    state = QALoopState(pr_id="x")
    assert _run_qa_finalize_pane(
        state, {}, "pm-test", "qa", None,
    ) is None


# --- (f) -----------------------------------------------------------------

def test_run_qa_finalize_pane_returns_none_when_window_missing(
    monkeypatch, tmp_path,
):
    import pm_core.tmux as tmux_mod
    monkeypatch.setattr(tmux_mod, "find_window_by_name",
                        lambda *a, **kw: None)
    state = QALoopState(pr_id="x")
    assert _run_qa_finalize_pane(
        state, {}, "pm-test", "qa-window", str(tmp_path),
    ) is None


# --- (g) -----------------------------------------------------------------

def test_run_qa_finalize_pane_returns_none_when_pass_unverified(tmp_path):
    state = QALoopState(pr_id="x")
    state.scenario_verdicts = {1: "PASS"}
    state.verified_scenarios = set()
    # Gate fires before any tmux access (lines 388-395).
    assert _run_qa_finalize_pane(
        state, {}, "pm-test", "qa", str(tmp_path),
    ) is None


# --- (h) wiring test, textual-assertion fallback -------------------------
# NOTE: A full integration test would require monkeypatching >12 helpers
# (get_pm_session, store.load, _run_qa_finalize_pane, _launch_scenarios_*,
# _poll_tmux_verdicts, _persist_scenario_verdicts, _write_status_file,
# tmux.find_window_by_name, tmux.get_pane_indices, create_qa_workdir,
# _get_qa_spec, plus state/scenarios pre-population) and would still
# touch tmux/subprocess paths that can't be cleanly patched. Per the
# scenario instructions, downgrade to a textual assertion on the wiring
# in run_qa_sync. Search the whole file rather than a hardcoded line
# slice so the tests survive cosmetic shifts in qa_loop.py.

_QA_LOOP_PATH = Path(__file__).resolve().parent.parent / "pm_core" / "qa_loop.py"


def _qa_loop_src() -> str:
    return _QA_LOOP_PATH.read_text()


def test_run_qa_sync_finalize_suffix_in_latest_output():
    src = _qa_loop_src()
    assert "state.finalize_verdict = _run_qa_finalize_pane(" in src, \
        "expected run_qa_sync to assign state.finalize_verdict"
    assert 'f" [finalize: {state.finalize_verdict}]"' in src, \
        "expected [finalize: …] suffix wired into latest_output"
    # Suffix is only added when verdict truthy.
    assert "if state.finalize_verdict:" in src


# --- (i) exception-swallowing wiring, textual fallback -------------------

def test_run_qa_sync_swallows_finalize_exception():
    """The finalize-pane call must be wrapped in try/except so a crash
    there doesn't sink the whole QA loop. Find the assignment, then
    verify a try/except logs the exception nearby."""
    lines = _qa_loop_src().splitlines()
    target = "state.finalize_verdict = _run_qa_finalize_pane("
    idx = next((i for i, ln in enumerate(lines) if target in ln), None)
    assert idx is not None, f"could not find {target!r} in qa_loop.py"
    # Look in a small window around the call for try/except/log.
    window = "\n".join(lines[max(0, idx - 5):idx + 10])
    assert "try:" in window
    assert "except Exception:" in window
    assert "_log.exception(" in window, \
        "finalize-pane exception should be logged via _log.exception"
