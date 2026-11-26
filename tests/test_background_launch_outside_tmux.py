"""Background (auto-sequence) review and sign-off launches from a shell
outside tmux open their window in the project's pm session; a foreground
launch there still needs tmux (RQ47: a tick outside tmux never got past
"Review window requires tmux." and still printed review_relaunched)."""

import pytest

from pm_core import signoff, tmux as tmux_mod
from pm_core.cli import pr as pr_mod


@pytest.fixture
def outside_tmux(monkeypatch):
    monkeypatch.setattr(tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(tmux_mod, "in_tmux", lambda: False)
    monkeypatch.setattr(pr_mod, "_get_pm_session", lambda: "pm-proj-1234")
    monkeypatch.setattr("pm_core.cli.helpers._get_pm_session",
                        lambda: "pm-proj-1234")
    # Stop right after the gate: the session lookup is the next step.
    monkeypatch.setattr(tmux_mod, "session_exists",
                        lambda name, socket_path=None: False)


PR = {"id": "pr-001", "title": "T", "branch": "b", "status": "in_review"}


@pytest.mark.parametrize("background, expected", [
    (True, "Review window: tmux session 'pm-proj-1234' not found."),
    (False, "Review window requires tmux."),
])
def test_review_window_gate(outside_tmux, capsys, background, expected):
    pr_mod._launch_review_window({"project": {}}, dict(PR),
                                 background=background)
    assert capsys.readouterr().out.strip() == expected


@pytest.mark.parametrize("background, expected", [
    (True, "Sign-off window: tmux session 'pm-proj-1234' not found."),
    (False, "Sign-off window requires tmux."),
])
def test_signoff_window_gate(outside_tmux, capsys, background, expected):
    signoff.launch_signoff_window({"project": {}}, dict(PR),
                                  background=background)
    assert capsys.readouterr().out.strip() == expected
