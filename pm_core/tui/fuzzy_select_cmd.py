"""Command handlers for 'pr select' and 'plan select' with fuzzy matching.

Both commands rank candidates (see :mod:`pm_core.tui.fuzzy_select`), move
the tree cursor to the best match and keep the full ranked list on the app
(``_fuzzy_results`` / ``_fuzzy_index`` / ``_fuzzy_kind``) for the ``]`` /
``[`` cycling keys.  The list holds stable local pm ids (PR ids for
``pr select``, plan ids for ``plan select``), never display ids.

Scope is deliberately narrow: these handlers only move the cursor and
persist ``active_pr`` (exactly what arrow-key navigation does).  No other
command resolves ids fuzzily.
"""

from __future__ import annotations

import re
import shlex

from pm_core import store
from pm_core.cli.helpers import _pr_display_id
# The shared escaper (this module used to import it from the model screen,
# where it lived before the command-surface sweep made it common).
from pm_core.command_surface import escape_markup as escape

_SELECT_RE = re.compile(r"(pr|plan)\s+select(?:\s+(.*))?", re.DOTALL)

_FILTER_HINT = "X: merged, f: status filter"


# ---------------------------------------------------------------------------
# Parsing / dispatch
# ---------------------------------------------------------------------------

def parse_select_command(cmd: str) -> tuple[str, str] | None:
    """Return ``(kind, query)`` for ``pr select …`` / ``plan select …``.

    *kind* is ``"pr"`` or ``"plan"``; *query* is the remainder with shell
    quotes removed when it parses (``"spec gen"`` -> ``spec gen``), else the
    raw text (``user's``), whitespace-collapsed.  Returns None for any other
    command.
    """
    m = _SELECT_RE.fullmatch(cmd.strip())
    if not m:
        return None
    rest = (m.group(2) or "").strip()
    try:
        words = shlex.split(rest)
    except ValueError:
        words = rest.split()
    return m.group(1), " ".join(" ".join(words).split())


def handle_select_command(app, kind: str, query: str) -> None:
    """Dispatch a parsed select command (usage message on empty query)."""
    if not query:
        app.log_message(f"Usage: {kind} select <query>")
        return
    if kind == "pr":
        handle_pr_select(app, query)
    else:
        handle_plan_select(app, query)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tree(app):
    from pm_core.tui.tech_tree import TechTree
    return app.query_one("#tech-tree", TechTree)


def _set_results(app, ids: list[str], kind: str) -> None:
    app._fuzzy_results = list(ids)
    app._fuzzy_index = 0
    app._fuzzy_kind = kind if ids else ""


def _clear_results(app) -> None:
    _set_results(app, [], "")


def _ensure_tree_view(app) -> None:
    if app._plans_visible or app._qa_visible:
        app._show_normal_view()


def _goto_pr(app, pr_id: str) -> None:
    """Move the cursor to *pr_id* and persist it as the active PR."""
    from pm_core.tui import pr_view
    _ensure_tree_view(app)
    _tree(app).select_pr(pr_id)
    pr_view.persist_active_pr(app, pr_id)


def _pr_label(pr: dict) -> str:
    title = pr.get("title")
    title = title if isinstance(title, str) else ""
    return escape(f"{_pr_display_id(pr)} {title}".rstrip())


def _pr_ref(app, pr_id: str) -> str:
    """Escaped display id (``#N``, else the local id) for *pr_id*."""
    pr = store.get_pr(app._data, pr_id)
    return escape(_pr_display_id(pr) if pr else pr_id)


def _plan_label(plan: dict) -> str:
    name = plan.get("name")
    name = name if isinstance(name, str) else ""
    return escape(f"{plan['id']}: {name}" if name else plan["id"])


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _suffix(count: int, hidden: int = 0) -> str:
    """`` [N matches, M hidden by filters]`` (markup-escaped), or ''."""
    parts = []
    if count > 1:
        parts.append(_plural(count, "match", "matches"))
    if hidden:
        parts.append(f"{hidden} hidden by filters")
    return escape(f" [{', '.join(parts)}]") if parts else ""


# ---------------------------------------------------------------------------
# pr select
# ---------------------------------------------------------------------------

def handle_pr_select(app, query: str) -> None:
    """Handle 'pr select <query>' — fuzzy match against PRs and navigate."""
    from pm_core.tui.fuzzy_select import fuzzy_match_prs, is_exact_pr_match

    prs = app._data.get("prs") or []
    if not prs:
        app.log_message("No PRs available")
        _clear_results(app)
        return

    tree = _tree(app)
    plan_map = {p["id"]: p for p in (app._data.get("plans") or [])
                if isinstance(p, dict) and isinstance(p.get("id"), str)}
    ranked = fuzzy_match_prs(prs, query, plan_map,
                             cursor_index=tree.selected_index,
                             positions=tree.pr_nav_positions())
    if not ranked:
        app.log_message(f"No PR matches for '{escape(query)}'")
        _clear_results(app)
        return

    visible = [pr for pr in ranked if tree.is_navigable(pr["id"])]
    hidden = len(ranked) - len(visible)

    # An exact id is authoritative: never land on a different PR that
    # merely mentions it because the named PR is filtered out.
    exact = [pr for pr in ranked if is_exact_pr_match(pr, query)]
    if exact and not any(tree.is_navigable(pr["id"]) for pr in exact):
        app.log_message(f"{_pr_label(exact[0])} is hidden by the current "
                        f"filters ({_FILTER_HINT})")
        _clear_results(app)
        return

    if not visible:
        app.log_message(f"No visible PR matches for '{escape(query)}' "
                        f"({hidden} hidden by filters — {_FILTER_HINT})")
        _clear_results(app)
        return

    _set_results(app, [pr["id"] for pr in visible], "pr")
    best = visible[0]
    _goto_pr(app, best["id"])
    app.log_message(f"Selected: {_pr_label(best)}{_suffix(len(visible), hidden)}")


# ---------------------------------------------------------------------------
# plan select
# ---------------------------------------------------------------------------

def handle_plan_select(app, query: str) -> None:
    """Handle 'plan select <query>' — fuzzy match plans, go to first PR."""
    from pm_core.tui.fuzzy_select import fuzzy_match_plans

    plans = app._data.get("plans") or []
    if not plans:
        app.log_message("No plans available")
        _clear_results(app)
        return

    tree = _tree(app)
    # Ties go to the plan whose landing PR is nearest the cursor in tree
    # order (the same index space as pr select's tie-break).
    ranked = fuzzy_match_plans(plans, query,
                               cursor_index=tree.selected_index,
                               positions=tree.plan_nav_positions())
    if not ranked:
        app.log_message(f"No plan matches for '{escape(query)}'")
        _clear_results(app)
        return

    best = ranked[0]
    total, shown = tree.plan_pr_counts(best["id"])
    if not total:
        app.log_message(f"Plan '{_plan_label(best)}' has no PRs")
        _clear_results(app)
        return
    if not shown:
        app.log_message(f"Plan '{_plan_label(best)}': all "
                        f"{_plural(total, 'PR')} hidden by filters "
                        f"({_FILTER_HINT})")
        _clear_results(app)
        return

    cyclable = [plan["id"] for plan in ranked
                if tree.plan_pr_counts(plan["id"])[1]]
    _set_results(app, cyclable, "plan")

    _ensure_tree_view(app)
    first = tree.first_pr_in_plan(best["id"])
    if first is None:  # defensive: counts said a PR is shown
        app.log_message(f"Plan '{_plan_label(best)}' has no visible PRs")
        return
    _goto_pr(app, first)
    app.log_message(f"Plan: {_plan_label(best)} → {_pr_ref(app, first)}"
                    f"{_suffix(len(cyclable))}")


# ---------------------------------------------------------------------------
# ] / [ cycling
# ---------------------------------------------------------------------------

def _resolve_entry(app, tree, entry_id: str) -> str | None:
    """PR id to put the cursor on for a result entry, or None if the entry
    is no longer navigable (deleted, filtered out, plan emptied)."""
    if app._fuzzy_kind == "plan":
        if store.get_plan(app._data, entry_id) is None:
            return None
        return tree.first_pr_in_plan(entry_id)
    return entry_id if tree.is_navigable(entry_id) else None


def cycle_fuzzy(app, direction: int = 1) -> None:
    """Cycle through the fuzzy match result list.

    direction: +1 for next (]), -1 for prev ([).  Entries that are no
    longer navigable are skipped; the list itself is left intact.
    """
    results = app._fuzzy_results
    if not results:
        app.log_message("No match results to cycle (use /pr select or /plan select)")
        return

    tree = _tree(app)
    total = len(results)
    index = app._fuzzy_index
    target = None
    for _ in range(total):
        index = (index + direction) % total
        target = _resolve_entry(app, tree, results[index])
        if target is not None:
            break
    if target is None:
        app.log_message("No match results are visible any more "
                        f"({_FILTER_HINT})")
        return

    app._fuzzy_index = index
    _goto_pr(app, target)
    pos = index + 1

    if app._fuzzy_kind == "plan":
        plan = store.get_plan(app._data, results[index]) or {"id": results[index]}
        app.log_message(f"Match {pos}/{total}: {_plan_label(plan)} → "
                        f"{_pr_ref(app, target)}")
    else:
        pr = store.get_pr(app._data, target)
        label = _pr_label(pr) if pr else escape(target)
        app.log_message(f"Match {pos}/{total}: {label}")
