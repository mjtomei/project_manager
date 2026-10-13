"""Shared test helpers for pm_core tests."""

import pytest

from pm_core.fake_github import FakeGitHubBackend


@pytest.fixture(autouse=True)
def _isolated_runtime_state(tmp_path_factory, monkeypatch):
    """Keep runtime_state out of the real ``~/.pm/runtime``.

    Auto-start scheduling reads recorded QA verdicts from runtime_state, so
    entries leaked by one test (or a live pm session on the same machine)
    must not steer another test.  Tests that patch ``_runtime_dir``
    themselves still win (their monkeypatch is applied later).
    """
    from pm_core import runtime_state
    d = tmp_path_factory.mktemp("runtime")
    monkeypatch.setattr(runtime_state, "_runtime_dir", lambda: d)


@pytest.fixture
def fake_github():
    """Install a pure-metadata FakeGitHubBackend as the `gh` transport.

    Mirrors how a FakeClaudeSession fixture swaps the Claude session: the
    fake is installed via gh_ops.gh_runner for the duration of the test and
    the previous transport is restored on teardown. Yields the backend so
    tests can seed PRs, script failures, and assert on recorded calls.

    No git repo backs this one — use ``fake_github_repo`` for tests whose
    `gh` operations need real git state behind them.
    """
    backend = FakeGitHubBackend()
    with backend.installed():
        yield backend


@pytest.fixture
def fake_github_repo(tmp_path):
    """Install a git-backed FakeGitHubBackend as the `gh` transport.

    The fake owns a real local git repo (``backend.git_repo``) acting as the
    remote, so git-affecting `gh` operations (pr create, pr merge) produce
    genuine git history — letting merge-with-pull and similar flows run
    end-to-end without hand-mocking git_ops.
    """
    backend = FakeGitHubBackend.with_git_repo(tmp_path / "fake-gh")
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
