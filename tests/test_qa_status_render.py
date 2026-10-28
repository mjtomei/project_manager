"""Tests for the QA status dashboard renderer (``pm_core.qa_status._render``).

The error block explains *why* a run stopped without naming the outcome, so
the dashboard must still report the run's overall verdict next to it (e.g.
INPUT_REQUIRED when the planner produced no plan) and must keep the scenario
rows visible — a planner-recovery exhaustion leaves the interactive
Scenario 0 listed.  Only a run with nothing else to show falls back to the
error-only view.
"""

import re

from pm_core.qa_status import _render

_ANSI = re.compile(r"\033\[[0-9;]*m")


def _plain(status, rows=24, cols=100, selected=0):
    return _ANSI.sub("", _render(status, selected, rows, cols))


def test_error_block_reports_overall_verdict():
    status = {
        "pr_id": "pr-abc123",
        "scenarios": [],
        "overall": "INPUT_REQUIRED",
        "error": "No parseable scenarios found in planner output.",
    }
    out = _plain(status)
    assert "ERROR" in out
    assert "No parseable scenarios found in planner output." in out
    assert "Overall: INPUT_REQUIRED" in out


def test_error_block_without_overall_omits_the_line():
    status = {
        "pr_id": "pr-abc123",
        "scenarios": [],
        "overall": "",
        "error": "Waiting for the spec.",
    }
    out = _plain(status)
    assert "ERROR" in out
    assert "Overall:" not in out


def test_error_block_still_shows_scenarios_and_overall():
    status = {
        "pr_id": "pr-abc",
        "scenarios": [
            {
                "index": 0,
                "title": "Interactive Session",
                "verdict": "interactive",
                "window_name": "qa-pr-abc-s0",
            },
        ],
        "overall": "INPUT_REQUIRED",
        "error": (
            "QA planning did not produce a complete QA_PLAN block.\n"
            "\n"
            "qa-planner: recovery made no progress."
        ),
    }

    out = _plain(status, rows=30)

    assert "QA Status: pr-abc" in out
    assert "ERROR" in out
    assert "QA planning did not produce a complete QA_PLAN block." in out
    # The scenario row and the terminal verdict must not be hidden by the
    # error block.
    assert "Interactive Session" in out
    assert "Overall: INPUT_REQUIRED" in out


def test_error_without_scenarios_keeps_the_error_only_view():
    status = {
        "pr_id": "pr-abc",
        "scenarios": [],
        "overall": "",
        "error": "QA spec missing: pm/specs/pr-abc/qa.md",
    }

    out = _plain(status, rows=30)

    assert "ERROR" in out
    assert "QA spec missing" in out
    # No empty table header / Overall line when there is nothing to show.
    assert "Scenario" not in out
    assert "Overall:" not in out
