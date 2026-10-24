"""TUI-mount sweep of ~/.pm/runtime entries (shared by every project)."""

from pm_core import runtime_state as rs


def test_sweep_limited_to_given_prs_keeps_another_projects_live_entries():
    """S36: a second project's TUI mount swept the live QA entries of the
    first project's running runs, so their picker rows lost [working] for
    good (the QA mirror only rewrites on a new pane registration)."""
    rs.set_action_state("pr-own", "qa", "running", panes={"s1": {"session_id": "a"}})
    rs.set_action_state("pr-other", "qa", "running", panes={"s4": {"session_id": "b"}})
    rs.set_action_state("pr-other", "review", "done", verdict="PASS")

    assert rs.sweep_stale_states("tui-mount", pr_ids={"pr-own"}) == 1

    assert rs.get_action_state("pr-own", "qa") == {}
    assert rs.get_action_state("pr-other", "qa")["state"] == "running"
    assert rs.get_action_state("pr-other", "review")["state"] == "done"


def test_sweep_without_pr_ids_clears_every_in_flight_entry():
    rs.set_action_state("pr-own", "qa", "running")
    rs.set_action_state("pr-other", "start", "idle")
    assert rs.sweep_stale_states("tui-restart") == 2
    assert rs.get_action_state("pr-other", "start") == {}
