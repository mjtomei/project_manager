"""Command handlers for 'pr select' and 'plan select' with fuzzy matching."""

import logging

from pm_core.paths import configure_logger

_log = configure_logger("pm.tui.fuzzy_select_cmd")


def handle_pr_select(app, query: str) -> None:
    """Handle 'pr select <query>' — fuzzy match against PRs and navigate."""
    from pm_core.tui.tech_tree import TechTree
    from pm_core.tui.fuzzy_select import fuzzy_match_prs
    from pm_core.cli.helpers import _pr_display_id

    prs = app._data.get("prs") or []
    if not prs:
        app.log_message("No PRs available")
        return

    tree = app.query_one("#tech-tree", TechTree)
    plan_map = {p["id"]: p for p in (app._data.get("plans") or [])}

    results = fuzzy_match_prs(prs, query, plan_map, cursor_index=tree.selected_index)
    if not results:
        app.log_message(f"No PR matches for '{query}'")
        app._fuzzy_results = []
        return

    # Store ranked result list for cycling
    app._fuzzy_results = [pr["id"] for pr in results]
    app._fuzzy_index = 0
    app._fuzzy_kind = "pr"

    # Switch to tree view if in plans/QA view
    if app._plans_visible or app._qa_visible:
        app._show_normal_view()

    # Navigate to best match
    best = results[0]
    tree.select_pr(best["id"])
    display = _pr_display_id(best)
    title = best.get("title", "")
    count = len(results)
    suffix = f" [{count} match{'es' if count != 1 else ''}]" if count > 1 else ""
    app.log_message(f"Selected: {display} {title}{suffix}")


def handle_plan_select(app, query: str) -> None:
    """Handle 'plan select <query>' — fuzzy match against plans, navigate to first PR."""
    from pm_core.tui.tech_tree import TechTree
    from pm_core.tui.fuzzy_select import fuzzy_match_plans

    plans = app._data.get("plans") or []
    if not plans:
        app.log_message("No plans available")
        return

    results = fuzzy_match_plans(plans, query)
    if not results:
        app.log_message(f"No plan matches for '{query}'")
        app._fuzzy_results = []
        return

    best_plan = results[0]
    plan_id = best_plan["id"]
    plan_name = best_plan.get("name", "")

    # Find PRs belonging to this plan
    prs = app._data.get("prs") or []
    plan_prs = [pr for pr in prs if pr.get("plan") == plan_id]

    if not plan_prs:
        app.log_message(f"Plan '{plan_name or plan_id}' has no PRs")
        app._fuzzy_results = []
        return

    # Store all plan-PR IDs as the result list (for cycling through plans)
    # Use first PR of each matched plan for cycling
    app._fuzzy_results = []
    for plan in results:
        pid = plan["id"]
        first_pr = next((pr for pr in prs if pr.get("plan") == pid), None)
        if first_pr:
            app._fuzzy_results.append(first_pr["id"])
    app._fuzzy_index = 0
    app._fuzzy_kind = "plan"

    # Switch to tree view if in plans/QA view
    if app._plans_visible or app._qa_visible:
        app._show_normal_view()

    # Navigate to first PR in the best matching plan
    tree = app.query_one("#tech-tree", TechTree)
    first_pr = plan_prs[0]
    tree.select_pr(first_pr["id"])  # select_pr auto-expands collapsed plans

    count = len(results)
    suffix = f" [{count} match{'es' if count != 1 else ''}]" if count > 1 else ""
    app.log_message(f"Plan: {plan_id}: {plan_name} → {first_pr['id']}{suffix}")


def cycle_fuzzy(app, direction: int = 1) -> None:
    """Cycle through the fuzzy match result list.

    direction: +1 for next (]), -1 for prev ([).
    """
    if not app._fuzzy_results:
        app.log_message("No match results to cycle (use /pr select or /plan select)")
        return

    app._fuzzy_index = (app._fuzzy_index + direction) % len(app._fuzzy_results)
    target_id = app._fuzzy_results[app._fuzzy_index]
    pos = app._fuzzy_index + 1
    total = len(app._fuzzy_results)

    if app._fuzzy_kind == "pr":
        from pm_core.tui.tech_tree import TechTree
        from pm_core.cli.helpers import _pr_display_id
        from pm_core import store

        # Switch to tree view if needed
        if app._plans_visible or app._qa_visible:
            app._show_normal_view()

        tree = app.query_one("#tech-tree", TechTree)
        tree.select_pr(target_id)
        pr = store.get_pr(app._data, target_id)
        if pr:
            display = _pr_display_id(pr)
            title = pr.get("title", "")
            app.log_message(f"Match {pos}/{total}: {display} {title}")
        else:
            app.log_message(f"Match {pos}/{total}: {target_id}")
    elif app._fuzzy_kind == "plan":
        from pm_core.tui.tech_tree import TechTree
        from pm_core import store

        if app._plans_visible or app._qa_visible:
            app._show_normal_view()

        tree = app.query_one("#tech-tree", TechTree)
        tree.select_pr(target_id)
        pr = store.get_pr(app._data, target_id)
        plan_id = pr.get("plan", "") if pr else ""
        plan = store.get_plan(app._data, plan_id) if plan_id else None
        plan_name = plan.get("name", "") if plan else ""
        app.log_message(f"Match {pos}/{total}: {plan_id}: {plan_name} → {target_id}")
