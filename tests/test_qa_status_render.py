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


def _launch_failure_status():
    return {
        "pr_id": "pr-1ae871a",
        "scenarios": [
            {"index": 0, "title": "Interactive Session", "verdict": "interactive"},
            {"index": 1, "title": "S92 E scenario 1", "verdict": "PASS"},
            {"index": 2, "title": "S92 E scenario 2", "verdict": "",
             "verdict_reason": "launch failed: Container 'pm-t-qa-pr-1ae871a-l-s2' "
                               "could not start its push proxy. Runtime error: push "
                               "proxy did not become ready at /tmp/pm-push-proxy-t/push.sock"},
            {"index": 3, "title": "S92 E scenario 3", "verdict": "PASS"},
            {"index": 4, "title": "S92 E scenario 4", "verdict": "PASS"},
        ],
        "overall": "INPUT_REQUIRED",
        "error": "1 scenario(s) failed to launch (no verdict): Container "
                 "'pm-t-qa-pr-1ae871a-l-s2' could not start its push proxy. Runtime "
                 "error: push proxy did not become ready at /tmp/pm-push-proxy-t/"
                 "push.sock (workdir=/home/u/.pm/workdirs/qa/pr-1ae871a-l/s-2/repo, "
                 "branch=pm/pr-1ae871a-e)",
    }


def test_short_narrow_pane_keeps_header_error_and_table_on_screen():
    """An 80x24 QA window gives the status pane 39x12: a full render scrolled
    the header and the ERROR block off the top and wrapped the key hint."""
    cols, rows = 39, 12
    lines = _text(_launch_failure_status(), cols=cols, rows=rows).split("\n")
    assert len(lines) == rows
    assert all(len(l) <= cols for l in lines)
    assert lines[0].startswith("QA Status: pr-1ae871a")
    err = next(i for i, l in enumerate(lines) if l.strip() == "ERROR")
    assert lines[err + 1].strip().startswith("1 scenario(s) failed to launch")
    assert lines[err + 1].rstrip().endswith("…")
    table = next(i for i, l in enumerate(lines) if "Scenario" in l and "Verdict" in l)
    assert err < table
    out = "\n".join(lines)
    for n in (1, 3, 4):
        assert re.search(rf"{n}\s+S92 E scen\S*\s+PASS", out)
    assert "↳ launch failed:" in out
    assert "Overall: INPUT_REQUIRED" in out


def test_full_error_kept_when_the_pane_is_tall_enough():
    lines = _text(_launch_failure_status(), cols=99, rows=40).split("\n")
    out = " ".join(l.strip() for l in lines)
    assert "branch=pm/pr-1ae871a-e)" in out
    assert "j/k: navigate  Enter: go to window  q: quit" in out
    assert "…" not in out.split("#  Scenario")[0]


def test_key_hint_and_progress_never_wider_than_the_pane():
    status = _launch_failure_status()
    status.update(overall="", error="")
    status["scenarios"][2]["verdict"] = "PASS (verifying)"
    for cols in (30, 39, 44):
        lines = _text(status, cols=cols, rows=40).split("\n")
        hint = [l for l in lines if "j/k" in l]
        progress = [l for l in lines if "Progress:" in l]
        assert hint and progress
        assert all(len(l.rstrip()) <= cols for l in hint + progress)
