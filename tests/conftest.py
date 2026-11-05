"""Shared test helpers for pm_core tests."""

import os

import pytest

# Load the CLI package before any test patches a launcher function.  Its
# modules bind names such as ``claude_launcher.prepare_workspace`` at import
# time, so a first import under a ``patch`` (e.g. qa_loop's lazy
# ``pm_core.cli.helpers`` import) keeps the mock for the rest of the run.
import pm_core.cli  # noqa: F401
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


@pytest.fixture(autouse=True)
def _no_qa_launch_records(monkeypatch):
    """Keep QA launch records out of the real ``~/.pm/workdirs/qa``.

    Launching a detached QA driver writes its run record under the home
    directory, which most tests do not redirect; one leaked record would
    make later tests' PRs look driven.  Tests of the records restore
    ``qa_loop.write_launch_record`` with their own HOME.
    """
    from pm_core import qa_loop
    monkeypatch.setattr(qa_loop, "write_launch_record",
                        lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _isolated_claude_config(tmp_path_factory, monkeypatch):
    """Point Claude's global config at a temp dir.

    Launch helpers bootstrap workspace trust into ``.claude.json``; tests
    must never write the real one.
    """
    monkeypatch.setenv("CLAUDE_CONFIG_DIR",
                       str(tmp_path_factory.mktemp("claude-config")))


@pytest.fixture(autouse=True)
def _no_inherited_routing_env(monkeypatch):
    """Run every test as if from a plain shell, not a routed session.

    The suite often runs inside a pm session whose launch set the route's
    model aliases, pins and ANTHROPIC_BASE_URL (providers.launch_env), and
    launch builders react to such inherited values.  Tests that exercise
    that set them themselves.
    """
    from pm_core.providers import LAUNCH_ROUTING_ENV_VARS
    # CLAUDE_CODE_EFFORT_LEVEL is read by model_config's effort resolution
    # (it overrides --effort inside the CLI), so an inherited value would
    # change every effort the suite asserts.  Tests that exercise it set it.
    for var in (*LAUNCH_ROUTING_ENV_VARS, "ANTHROPIC_BASE_URL",
                "CLAUDE_CODE_EFFORT_LEVEL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _restore_environment():
    """Undo every process-environment change a test makes.

    The code under test deliberately exports ``PM_TMUX_SOCKET`` (and, for
    shared sessions, ``PM_SHARE_MODE``) into the process environment:
    ``helpers._use_tmux_socket``, ``session._resolve_session_socket`` and
    ``tmux.export_ambient_socket`` all write it.  ``monkeypatch`` cannot
    undo a value the *code* sets, so a test that mocks tmux broadly — e.g.
    ``review_launch_retry``'s process-wide ``subprocess.run`` stub, which
    makes every ``session_exists`` probe succeed — leaves the value behind
    and a later test asserting on an exact tmux command sees a stray
    ``-S <socket>``.  That is how the suite used to become order-dependent
    (``test_session_socket_isolation.py`` kept a module-local copy of this
    fixture; ``test_tmux.py``'s command assertions are the canary).

    Snapshotting the environment is the one form that also covers values
    pm sets itself.  A missing variable is removed again rather than set
    to an empty string, so code that tests the variable for truthiness
    behaves exactly as it did at the start of the test.
    """
    saved = dict(os.environ)
    try:
        yield
    finally:
        for key in set(os.environ) - set(saved):
            del os.environ[key]
        for key, value in saved.items():
            os.environ[key] = value


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
