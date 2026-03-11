"""Fuzzy matching and ranked selection for PRs and plans in the TUI."""


def _fuzzy_contains(haystack: str, needle: str) -> bool:
    """Case-insensitive substring match."""
    return needle.lower() in haystack.lower()


def score_pr(pr: dict, query: str, plan_map: dict) -> float:
    """Score a PR against a query string.

    Scoring weights (higher = better match):
      - Exact ID match:     1000
      - Display ID match:   900  (e.g. #125)
      - ID prefix match:    500
      - Title substring:    200
      - Description substr: 100
      - Plan name substr:    50

    Multiple field matches combine additively.
    """
    q = query.lower()
    score = 0.0

    pr_id = pr.get("id", "")
    title = pr.get("title", "")
    description = pr.get("description", "")
    plan_id = pr.get("plan", "")

    # Display ID (e.g. "#125")
    gh_num = pr.get("gh_pr_number")
    display_id = f"#{gh_num}" if gh_num else pr_id

    # Exact ID match (raw or display)
    if pr_id.lower() == q or display_id.lower() == q:
        score += 1000
    # ID prefix match
    elif pr_id.lower().startswith(q) or display_id.lower().startswith(q):
        score += 500

    # Title substring
    if _fuzzy_contains(title, query):
        score += 200

    # Description substring
    if _fuzzy_contains(description, query):
        score += 100

    # Plan name substring
    if plan_id:
        plan = plan_map.get(plan_id, {})
        plan_name = plan.get("name", "")
        if _fuzzy_contains(plan_name, query) or _fuzzy_contains(plan_id, query):
            score += 50

    return score


def score_plan(plan: dict, query: str) -> float:
    """Score a plan against a query string.

    Scoring weights:
      - Exact ID match:    1000
      - ID prefix match:    500
      - Name substring:     200
    """
    q = query.lower()
    score = 0.0

    plan_id = plan.get("id", "")
    name = plan.get("name", "")

    if plan_id.lower() == q:
        score += 1000
    elif plan_id.lower().startswith(q):
        score += 500

    if _fuzzy_contains(name, query):
        score += 200

    return score


def fuzzy_match_prs(prs: list[dict], query: str, plan_map: dict,
                    cursor_index: int = 0) -> list[dict]:
    """Return PRs matching query, ranked by score descending.

    Ties are broken by proximity to cursor_index (closer = preferred).
    Returns list of PR dicts with score > 0.
    """
    scored = []
    for i, pr in enumerate(prs):
        s = score_pr(pr, query, plan_map)
        if s > 0:
            scored.append((s, abs(i - cursor_index), pr))

    # Sort: highest score first, then closest to cursor
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [item[2] for item in scored]


def fuzzy_match_plans(plans: list[dict], query: str,
                      cursor_index: int = 0) -> list[dict]:
    """Return plans matching query, ranked by score descending.

    Returns list of plan dicts with score > 0.
    """
    scored = []
    for i, plan in enumerate(plans):
        s = score_plan(plan, query)
        if s > 0:
            scored.append((s, abs(i - cursor_index), plan))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [item[2] for item in scored]
