"""Tests for pm_core.regression_prompts.build_regression_test_prompt."""

from pm_core.regression_prompts import build_regression_test_prompt


def test_basic_assembly_no_file_bugs():
    out = build_regression_test_prompt(
        session="pm-test-abc",
        pane_id="%5",
        title="TUI startup smoke",
        body="check that the TUI renders.",
        file_bugs=False,
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
    # No bug-filing addendum without file_bugs.
    assert "Bug Filing" not in out


def test_file_bugs_adds_addendum():
    out = build_regression_test_prompt(
        session="pm-test-abc",
        pane_id=None,
        title="t",
        body="b",
        file_bugs=True,
    )
    assert "## Bug Filing" in out
    assert "pm pr add" in out
    assert "--plan bugs" in out
    # Pointer to capture, not just commands.
    assert "pm/qa/captures/regression/" in out
    # The "no fixes here" prohibition is preserved.
    assert "do **not** attempt to fix them" in out
    assert "fixes belong in a separate bug-fix PR session" in out


def test_no_pane_omits_pane_line():
    out = build_regression_test_prompt(
        session="pm-test-abc",
        pane_id=None,
        title="t",
        body="b",
        file_bugs=False,
    )
    assert "The TUI pane ID is" not in out
