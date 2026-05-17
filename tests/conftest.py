"""Shared test helpers for pm_core tests."""

import pytest

from pm_core.fake_github import FakeGitHubBackend


@pytest.fixture
def fake_github():
    """Install a FakeGitHubBackend as the `gh` transport for the test.

    Mirrors how a FakeClaudeSession fixture swaps the Claude session: the
    fake is installed via gh_ops.gh_runner for the duration of the test and
    the previous transport is restored on teardown. Yields the backend so
    tests can seed PRs, script failures, and assert on recorded calls.
    """
    backend = FakeGitHubBackend()
    with backend.installed():
        yield backend


def simulate_terminal_wrap(text: str, width: int = 80) -> str:
    """Simulate how a terminal wraps long lines at a given column width.

    This mimics what tmux capture-pane returns when the prompt text is
    displayed on the command line.  Each input line is broken into chunks
    of ``width`` characters.
    """
    out = []
    for line in text.splitlines():
        while len(line) > width:
            out.append(line[:width])
            line = line[width:]
        out.append(line)
    return "\n".join(out)
