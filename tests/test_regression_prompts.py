"""Tests for pm_core.regression_prompts.build_regression_test_prompt."""

from pm_core.regression_prompts import build_regression_test_prompt


def test_basic_assembly_no_findings():
    out = build_regression_test_prompt(
        session="pm-test-abc",
        pane_id="%5",
        title="TUI startup smoke",
        body="check that the TUI renders.",
        file_findings=False,
    )
    # Session Context block carries the session and pane id.
    assert "## Session Context" in out
    assert "pm-test-abc" in out
    assert "The TUI pane ID is: %5" in out
    # Captures block present and points at the right convention.
    assert "## Captures" in out
    assert "pm/qa/captures/regression/" in out
    # Test body interpolated.
    assert "## QA Regression Test: TUI startup smoke" in out
    assert "check that the TUI renders." in out
    # No findings addendum without file_findings.
    assert "Filing Findings" not in out


def test_file_findings_addendum_covers_bugs_and_improvements():
    out = build_regression_test_prompt(
        session="pm-test-abc",
        pane_id=None,
        title="t",
        body="b",
        file_findings=True,
    )
    assert "## Filing Findings" in out
    # Bug filing path.
    assert "--plan bugs" in out
    # Improvement filing path.
    assert "--plan improvements" in out
    # Pointer-to-capture guidance present.
    assert "pm/qa/captures/regression/" in out
    # No-fixes-here prohibition preserved.
    assert "don't fix it here" in out
    # Verdict-vs-filing separation kept.
    assert "Filing is independent of your verdict" in out


def test_no_pane_omits_pane_line():
    out = build_regression_test_prompt(
        session="pm-test-abc",
        pane_id=None,
        title="t",
        body="b",
        file_findings=False,
    )
    assert "The TUI pane ID is" not in out
