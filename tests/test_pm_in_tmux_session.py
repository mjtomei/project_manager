"""Tests for PM_IN_TMUX_SESSION env-var propagation and consumption.

When pm runs under tmux, the wrapper sets PM_IN_TMUX_SESSION=1, and pm
sub-commands use it to default to TUI-parity behavior — specifically,
`pm pr merge` defaults to --resolve-window so conflicts launch a Claude
window the same way the TUI command bar does.
"""


class TestWrapperSetsEnv:
    def test_pm_in_tmux_session_set_when_tmux_is_set(self):
        from pm_core import wrapper
        env = {"TMUX": "/tmp/tmux-1000/default,1234,0"}
        wrapper._mark_tmux_session(env)
        assert env.get("PM_IN_TMUX_SESSION") == "1"

    def test_pm_in_tmux_session_unset_when_tmux_unset(self):
        from pm_core import wrapper
        env = {}
        wrapper._mark_tmux_session(env)
        assert "PM_IN_TMUX_SESSION" not in env


class TestPrMergeDefaultsResolveWindow:
    def test_env_var_enables_resolve_window_default(self, monkeypatch):
        """With PM_IN_TMUX_SESSION=1 pr merge should default
        resolve_window to True so picker / shell-pane invocations match
        the TUI command-bar behavior."""
        from pm_core.cli import pr as pr_mod
        monkeypatch.setenv("PM_IN_TMUX_SESSION", "1")
        assert pr_mod._resolve_window_default() is True

    def test_env_var_unset_keeps_default_off(self, monkeypatch):
        from pm_core.cli import pr as pr_mod
        monkeypatch.delenv("PM_IN_TMUX_SESSION", raising=False)
        assert pr_mod._resolve_window_default() is False
