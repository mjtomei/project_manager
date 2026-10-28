"""Rendering of the QA status pane (pm_core/qa_status.py)."""

import re

from pm_core.qa_status import _render

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _text(status, cols=120, rows=40):
    return _ANSI.sub("", _render(status, selected=0, rows=rows, cols=cols))


def test_error_without_scenarios_shows_only_the_error():
    out = _text({"pr_id": "pr-1", "scenarios": [], "overall": "INPUT_REQUIRED",
                 "error": "No QA spec found"})
    assert "ERROR" in out and "No QA spec found" in out
    assert "Scenario" not in out


def test_launch_failure_error_keeps_the_scenario_table():
    """A run-end launch-failure error must not hide the other verdicts."""
    reason = ("launch failed: Container 'pm-t-qa-pr-1-x-s2' could not start. "
              "Runtime error: boom")
    out = _text({
        "pr_id": "pr-1",
        "scenarios": [
            {"index": 1, "title": "one", "verdict": "PASS", "verdict_reason": ""},
            {"index": 2, "title": "two", "verdict": "", "verdict_reason": reason},
            {"index": 3, "title": "three", "verdict": "PASS", "verdict_reason": ""},
        ],
        "overall": "INPUT_REQUIRED",
        "error": "1 scenario(s) failed to launch (no verdict): Container "
                 "'pm-t-qa-pr-1-x-s2' could not start. Runtime error: boom",
    })
    assert "ERROR" in out
    assert "failed to launch (no verdict)" in out
    assert re.search(r"1\s+one\s+PASS", out)
    assert re.search(r"3\s+three\s+PASS", out)
    assert "↳ launch failed: Container 'pm-t-qa-pr-1-x-s2' could not start" in out
    assert "Overall: INPUT_REQUIRED" in out


def test_long_error_is_wrapped_to_the_pane_width():
    """Terminal-wrapped lines would push the header off a full-height pane."""
    cols = 60
    out = _text({"pr_id": "pr-1", "scenarios": [], "overall": "",
                 "error": "x " * 100}, cols=cols, rows=20)
    lines = out.split("\n")
    assert all(len(l) <= cols for l in lines)
    assert any("QA Status: pr-1" in l for l in lines)
