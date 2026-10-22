"""A realistic mixed auto-start report (shared by tests and demos).

Targets: a wait-for-merge chain, an auto-merge target sharing a dependency
with it, a stop-before-merge target, and an auto-merge target that is
signed off.  Covers running review/QA, INPUT_REQUIRED (review, QA), both
spec-review phases, manual-merge waits (wait hold + stop mark), an
inherited-policy exception and overlapping dependency holds.
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
            deps=["pr-3f4a5b6", "pr-2e3f4a5"], gh=240,
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
        "pr-4a5b6c7": {"wait_for_merge": True},  # wait chain
        "pr-6c7d8e9": {},                          # auto-merge
        "pr-9f0a1b2": {},                          # stop (in stop set)
        "pr-aa1b2c3": {},                          # auto-merge, signed off
    }
    return {
        "prs": prs,
        "targets": targets,
        "enabled": True,
        "run_id": "20261022-0915",
        "owner": {"session": "pm-project_manager-c5a1006b", "pid": 4242},
        "stop_before_merge": {"pr-9f0a1b2", "pr-8e9f0a1"},
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
