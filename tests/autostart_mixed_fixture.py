"""Realistic auto-start reports (shared by tests and demos).

:func:`mixed_inputs` — five targets rendered as one dependency forest:

- ``#238`` (auto-merge) shares ``#235`` with the wait-for-merge chain
  ``#240``; it was added first, so ``#235`` sits under it, carrying the
  chain's hold as an exception (``wait-for-merge ← #240``) and naming
  ``#240`` as "also needed by";
- ``#240`` (wait-for-merge) → ``#234`` → ``#233`` (review running) and
  ``#231`` (signed off, held: MANUAL MERGE); ``#240`` also depends on
  ``#231`` directly (a diamond inside one tree);
- ``#239`` (wait-for-merge, QA INPUT_REQUIRED) → ``#237`` (QA spec review)
  and ``#241``, itself an auto-merge *target* in review INPUT_REQUIRED that
  ``#239``'s closure holds (a target that is another target's dependency);
- ``#242`` (auto-merge) signed off, auto-merge pending (not a human wait).

Human action now: ``#236`` (impl spec review), ``#231``, ``#239``,
``#237``, ``#241``.

:func:`edge_inputs` — unusual graphs: a dependency cycle between two
targets, a target whose PR is gone, a pending PR blocked on a missing and a
closed PR, a dependency reached only through a merged PR, and two distinct
local PRs that share one GitHub number.
"""

from pm_core import autostart_state as st


def _pr(pid, status="pending", deps=None, gh=None, title=None, **extra):
    d = {"id": pid, "title": title or f"T {pid}", "branch": f"b-{pid}",
         "status": status, "depends_on": deps or []}
    if gh:
        d["gh_pr_number"] = gh
    d.update(extra)
    return d


def mixed_inputs() -> dict:
    prs = [
        _pr("pr-0a1b2c3", "sign_off", gh=231,
            title="Add structured status API for autostart runs"),
        _pr("pr-1c2d3e4", "in_review", gh=233,
            title="CLI controls for autostart targets with JSON replies"),
        _pr("pr-2e3f4a5", "qa", gh=235,
            title="Shared tmux window registry used by every runner"),
        _pr("pr-3f4a5b6", "pending", deps=["pr-1c2d3e4", "pr-0a1b2c3"],
            gh=234, title="Document autostart policies and the runs popup"),
        _pr("pr-4a5b6c7", "pending",
            deps=["pr-3f4a5b6", "pr-2e3f4a5", "pr-0a1b2c3"], gh=240,
            title="Ship multi-target autostart with live runs popup and "
                  "wait-for-merge chains across dependent PRs"),
        _pr("pr-5b6c7d8", "in_progress", gh=236,
            title="Theme tokens for the TUI",
            spec_pending={"phase": "impl"}),
        _pr("pr-6c7d8e9", "pending", deps=["pr-2e3f4a5", "pr-5b6c7d8"],
            gh=238, title="Runs popup UI polish"),
        _pr("pr-7d8e9f0", "qa", gh=237, title="Benchmark harness",
            spec_pending={"phase": "qa"}),
        _pr("pr-8e9f0a1", "in_review", gh=241, title="Status cache layer"),
        _pr("pr-9f0a1b2", "qa", deps=["pr-7d8e9f0", "pr-8e9f0a1"], gh=239,
            title="Speed up status rendering for large plans"),
        _pr("pr-aa1b2c3", "sign_off", gh=242, title="Hotfix: popup crash"),
    ]
    targets = {
        "pr-6c7d8e9": {},                          # auto-merge, added first
        "pr-4a5b6c7": {"wait_for_merge": True},  # wait chain
        "pr-9f0a1b2": {"wait_for_merge": True},  # wait, QA INPUT_REQUIRED
        "pr-8e9f0a1": {},                          # auto-merge, #239's dep
        "pr-aa1b2c3": {},                          # auto-merge, signed off
    }
    return {
        "prs": prs,
        "targets": targets,
        "enabled": True,
        "run_id": "20261022-0915",
        "owner": {"session": "pm-project_manager-c5a1006b", "pid": 4242},
        "review_loops": {
            "pr-1c2d3e4": {"running": True, "iteration": 3,
                           "verdict": "NEEDS_WORK", "input_required": False},
            "pr-8e9f0a1": {"running": False, "iteration": 2, "verdict": "",
                           "input_required": True},
        },
        "qa_loops": {
            "pr-2e3f4a5": {"running": True, "planning": False, "total": 5,
                           "done": 2, "counts": {"PASS": 2}},
            "pr-9f0a1b2": {"running": False, "verdict": "INPUT_REQUIRED"},
        },
        "signoff": {
            "pr-0a1b2c3": {"verdict": "SIGNOFF_MERGE", "fresh": True},
            "pr-aa1b2c3": {"verdict": "SIGNOFF_MERGE", "fresh": True},
        },
        "windows": {"review-#233": "@4", "qa-#235-s2": "@7", "#236": "@8",
                    "qa-#239": "@9", "review-#241": "@10",
                    "signoff-#231": "@11"},
        "generated_at": "2026-10-22T09:15:00Z",
    }


def mixed_status() -> dict:
    return st.build_status(mixed_inputs())


def edge_inputs() -> dict:
    prs = [
        # Two targets that depend on each other (a dependency cycle).
        _pr("pr-c1c1c1c", "in_progress", deps=["pr-c2c2c2c"], gh=301,
            title="Cycle side one"),
        _pr("pr-c2c2c2c", "in_review", deps=["pr-c1c1c1c"], gh=302,
            title="Cycle side two"),
        # A pending target blocked on a missing PR and a closed one.
        _pr("pr-b0b0b0b", "pending", deps=["pr-gone000", "pr-c0c0c0c"],
            gh=303, title="Blocked on what is not there"),
        _pr("pr-c0c0c0c", "closed", gh=304, title="Abandoned base"),
        # A dependency reached only through a merged intermediate.
        _pr("pr-d0d0d0d", "qa", deps=["pr-m0m0m0m"], gh=305,
            title="Target over a merged base"),
        _pr("pr-m0m0m0m", "merged", deps=["pr-e0e0e0e"], gh=306,
            title="Merged intermediate"),
        _pr("pr-e0e0e0e", "in_progress", gh=307, title="Late base fix"),
        # Two distinct local PRs that share one GitHub number.
        _pr("pr-f1f1f1f", "in_progress", gh=310, title="Twin one"),
        _pr("pr-f2f2f2f", "in_progress", gh=310, title="Twin two"),
        _pr("pr-f0f0f0f", "pending", deps=["pr-f1f1f1f", "pr-f2f2f2f"],
            gh=311, title="Needs both twins"),
    ]
    targets = {pid: {} for pid in ("pr-c1c1c1c", "pr-c2c2c2c", "pr-b0b0b0b",
                                   "pr-gone999", "pr-d0d0d0d", "pr-f0f0f0f")}
    return {
        "prs": prs,
        "targets": targets,
        "enabled": True,
        "run_id": "20261102-0100",
        "impl_idle": {"pr-f1f1f1f": "waiting", "pr-f2f2f2f": "waiting"},
        "windows": {"#301": "@1", "#307": "@2", "#310": "@3"},
        "generated_at": "2026-11-02T01:00:00Z",
    }


def edge_status() -> dict:
    return st.build_status(edge_inputs())
