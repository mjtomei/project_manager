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
    # Captures now live outside the repo under ~/.pm/sessions/...
    assert "captures/regression/" in out
    assert ".pm/sessions/" in out
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
    assert "capture" in out.lower()
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


def test_awkward_session_name_is_shell_quoted_in_the_examples():
    """A session name with a space must be quoted in the copyable commands.

    The name is derived from the repo directory, so an unquoted example
    (``pm tui view -s pm-my repo``) is two arguments and Click rejects it.
    Ordinary names stay bare, so the prompt is unchanged for them (pinned
    by the tests above).
    """
    out = build_regression_test_prompt(
        session="pm-my repo",
        pane_id=None,
        title="t",
        body="b",
        file_findings=False,
    )
    assert "pm tui view -s 'pm-my repo'" in out
    assert "pm tui send <keys> -s 'pm-my repo'" in out
    assert "tmux list-panes -t 'pm-my repo'" in out
    assert "cat ~/.pm/pane-registry/'pm-my repo'.json" in out
    # The prose line is a description, not a command: unchanged.
    assert "You are testing against tmux session: pm-my repo" in out


def test_discovery_prompt_quotes_the_session_window_target(monkeypatch):
    """The discovery watcher's ``tmux list-panes -t`` example is a command.

    Same rule as the examples above: a session name with a space (it comes
    from the repo directory) split the ``session:window`` target into two
    arguments.  The whole target is one shell word; an ordinary name stays
    bare and no name keeps the placeholder (review-loop b48f i19).
    """
    from pm_core import prompt_gen

    def no_project():
        raise FileNotFoundError

    monkeypatch.setattr(prompt_gen.store, "find_project_root", no_project)

    def target_line(session_name):
        out = prompt_gen.generate_discovery_supervisor_prompt(
            {}, session_name=session_name)
        return next(line for line in out.splitlines()
                    if line.startswith("tmux list-panes -t "))

    assert target_line("pm-my repo-abc").startswith(
        "tmux list-panes -t 'pm-my repo-abc:discovery' -F")
    assert target_line("pm-repo-abc").startswith(
        "tmux list-panes -t pm-repo-abc:discovery -F")
    assert target_line(None).startswith(
        "tmux list-panes -t <session>:discovery -F")
