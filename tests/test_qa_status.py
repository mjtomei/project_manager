"""Tests for the QA status mirror's focus-safe window switching.

The mirror runs as a standalone script (launched by path) and keeps its own
copy of the focus-safe switch resolver.  These tests guard the same invariant
as ``caller_switch_target`` in ``pm_core.tmux`` (pr-0b4e1a9): a focus-mutating
``select-window`` must target only the caller's OWN client's session and must
never hijack an arbitrary attached grouped session.
"""

from unittest.mock import patch, MagicMock

from pm_core import qa_status


class TestCallerSwitchTarget:
    @patch.dict("os.environ", {}, clear=True)
    def test_no_tmux_pane_returns_none(self):
        assert qa_status._caller_switch_target("proj") is None

    @patch.dict("os.environ", {"TMUX_PANE": "%1"})
    @patch("pm_core.qa_status.subprocess.run")
    def test_in_base_session_returns_it(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="proj\n", stderr="")
        assert qa_status._caller_switch_target("proj") == "proj"

    @patch.dict("os.environ", {"TMUX_PANE": "%1"})
    @patch("pm_core.qa_status.subprocess.run")
    def test_in_grouped_session_returns_it(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="proj~3\n", stderr="")
        assert qa_status._caller_switch_target("proj") == "proj~3"

    @patch.dict("os.environ", {"TMUX_PANE": "%1"})
    @patch("pm_core.qa_status.subprocess.run")
    def test_in_different_group_returns_none(self, mock_run):
        """Caller in a different project's session is not this base's client —
        no arbitrary grouped session is targeted."""
        mock_run.return_value = MagicMock(returncode=0, stdout="otherproj\n", stderr="")
        assert qa_status._caller_switch_target("proj") is None


class TestSwitchToWindow:
    @patch("pm_core.qa_status._caller_switch_target", return_value="proj~2")
    @patch("pm_core.qa_status.subprocess.run")
    def test_switch_targets_caller_session(self, mock_run, mock_cst):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        qa_status._switch_to_window("proj", "scenario-1")
        cmd = mock_run.call_args[0][0]
        assert "select-window" in cmd
        assert "proj~2:scenario-1" in cmd

    @patch("pm_core.qa_status._caller_switch_target", return_value=None)
    @patch("pm_core.qa_status.subprocess.run")
    def test_no_caller_client_does_not_switch(self, mock_run, mock_cst):
        """No identifiable caller → no select-window (must not hijack an
        arbitrary attached grouped session)."""
        qa_status._switch_to_window("proj", "scenario-1")
        mock_run.assert_not_called()
