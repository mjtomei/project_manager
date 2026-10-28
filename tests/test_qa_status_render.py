"""Tests for the QA status dashboard renderer (``pm_core.qa_status._render``).

The error branch replaces the scenario table, so it must still report the
run's overall verdict — an error block explains *why* the run stopped without
naming the outcome (e.g. INPUT_REQUIRED when the planner produced no plan).
"""

import re

from pm_core.qa_status import _render

_ANSI = re.compile(r"\033\[[0-9;]*m")


def _plain(status, rows=24, cols=100):
    return _ANSI.sub("", _render(status, 0, rows, cols))


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
