"""qa_status._find_attached_session: a session name survives the round trip.

The dashboard runs in a pane of the pm session and switches the client's
session to the window it follows.  The session it finds comes from tmux,
and a user's own view of the session may be named with a leading space
(S118/S121/S124: "however it is named").  Stripping the whole listing
trimmed such a name, so the lookup returned a session that does not exist
and the switch targeted nothing (review-loop 9d4c i3).
"""

import subprocess

from pm_core import qa_status


def _completed(argv, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, returncode, stdout, stderr)


def test_keeps_a_leading_space_in_the_view_name(monkeypatch):
    """Both the pane query and the listing keep the name's leading space."""
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
    monkeypatch.delenv("TMUX", raising=False)

    def fake_run(argv, **kwargs):
        if "#{session_name}:#{session_group}:#{session_attached}" in argv:
            # The listing's first row is the view's name, which starts with
            # a space.  (The pane query below must find it first; this is
            # the fallback, and it must not trim the name either.)
            return _completed(argv, stdout=" lead x:pm-x:1\npm-x::1\n")
        if "#{session_name}:#{session_group}" in argv:
            return _completed(argv, stdout=" lead x:pm-x\n")
        if "#{session_attached}" in argv:
            # Only the untrimmed name is a session tmux can address; the
            # trimmed one is what the pre-fix code asked for.
            if argv[argv.index("-t") + 1] == " lead x":
                return _completed(argv, stdout="1\n")
            return _completed(argv, returncode=1,
                              stderr="can't find session: lead x")
        return _completed(argv, returncode=1, stderr="unexpected query")

    monkeypatch.setattr(qa_status.subprocess, "run", fake_run)

    assert qa_status._find_attached_session("pm-x") == " lead x"
