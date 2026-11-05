"""Fuzzy matching and ranked selection for PRs and plans in the TUI.

Pure functions only — no Textual imports — so ranking is unit-testable.
Used solely by the ``pr select`` / ``plan select`` command-bar commands and
the ``]`` / ``[`` result-cycling keys; every other command keeps exact id
resolution.
"""

from __future__ import annotations

import re

# Scoring weights.  An exact id always outranks any non-exact combination
# (500 + 200 + 100 + 50 < 1000), and an id prefix outranks any combination
# of title/description/plan matches (200 + 100 + 50 < 500).
EXACT_ID = 1000
ID_PREFIX = 500
TITLE = 200
DESCRIPTION = 100
PLAN_NAME = 50

_BARE_NUMBER = re.compile(r"#?(\d+)")

# Canonical pm ids carry their identity in the hash (``pr-5f30bdf``), and
# notes, commits and QA reports refer to PRs by that hash alone.  The command
# bar accepts it without the ``pr-`` prefix: an exact hash names the PR, and
# a hash prefix of four or more hex characters is an id-prefix match.  The
# length floor keeps one- and two-character queries matching titles rather
# than turning every PR whose hash starts with them into an id hit, and
# legacy numeric ids (``pr-001``) keep the old behaviour.
_CANONICAL_PR_ID = re.compile(r"pr-([0-9a-f]{7})")
_HASH_QUERY = re.compile(r"[0-9a-f]{4,7}")


def _text(value) -> str:
    """Lower-cased string form of a field that may be missing or None."""
    return value.lower() if isinstance(value, str) else ""


def _id_hash(pr: dict) -> str:
    """The hash part of a canonical ``pr-<7 hex>`` id, else ``""``."""
    m = _CANONICAL_PR_ID.fullmatch(_text(pr.get("id")))
    return m.group(1) if m else ""


def _norm(query: str) -> str:
    return " ".join((query or "").split()).lower()


def _gh_number(pr: dict) -> int | None:
    num = pr.get("gh_pr_number")
    return num if isinstance(num, int) and not isinstance(num, bool) else None


def is_exact_pr_match(pr: dict, query: str) -> bool:
    """True if *query* names *pr* exactly, the way ``_resolve_pr_id`` does.

    Accepts the raw pm id (``pr-942aa21``), the display id (``#125``), a
    bare GitHub number (``125``) and the id's hash on its own
    (``942aa21``).  Case-insensitive.
    """
    q = _norm(query)
    if not q:
        return False
    if _text(pr.get("id")) == q:
        return True
    if q == _id_hash(pr):
        return True
    gh = _gh_number(pr)
    m = _BARE_NUMBER.fullmatch(q)
    return gh is not None and m is not None and int(m.group(1)) == gh


def score_pr(pr: dict, query: str, plan_map: dict) -> float:
    """Score a PR against a query string (0 = no match).

    Scoring weights (higher = better match):
      - Exact ID match:     1000  (raw ID, display ID ``#125``, bare ``125``
                                   or the id's hash alone)
      - ID prefix match:     500  (raw or display ID, or a hash prefix of
                                   four or more hex characters)
      - Title substring:     200
      - Description substr:  100
      - Plan name/id substr:  50

    Multiple field matches combine additively.
    """
    q = _norm(query)
    if not q:
        return 0.0
    score = 0.0

    pr_id = _text(pr.get("id"))
    gh = _gh_number(pr)
    display_id = f"#{gh}" if gh is not None else pr_id

    if is_exact_pr_match(pr, q):
        score += EXACT_ID
    elif (pr_id.startswith(q) or display_id.startswith(q)
          or (_HASH_QUERY.fullmatch(q) and _id_hash(pr).startswith(q))):
        score += ID_PREFIX

    if q in _text(pr.get("title")):
        score += TITLE

    if q in _text(pr.get("description")):
        score += DESCRIPTION

    plan_id = pr.get("plan")
    if isinstance(plan_id, str) and plan_id:
        plan = plan_map.get(plan_id) or {}
        if q in _text(plan.get("name")) or q in _text(plan_id):
            score += PLAN_NAME

    return score


def score_plan(plan: dict, query: str) -> float:
    """Score a plan against a query string (0 = no match).

    Scoring weights:
      - Exact ID match:    1000
      - ID prefix match:    500
      - Name substring:     200
    """
    q = _norm(query)
    if not q:
        return 0.0
    score = 0.0

    plan_id = _text(plan.get("id"))
    if plan_id == q:
        score += EXACT_ID
    elif plan_id.startswith(q):
        score += ID_PREFIX

    if q in _text(plan.get("name")):
        score += TITLE

    return score


def _rank(items: list[dict], scorer, cursor_index: int,
          positions: dict[str, int] | None) -> list[dict]:
    """Rank *items* by score (desc), then by distance to *cursor_index*.

    With *positions* (id -> navigation index), distance is measured in that
    index space and items without a position sort after positioned ones of
    the same score.  Without it, the item's list index is used.  Entries
    without a usable string id, and repeated ids, are skipped.
    """
    scored = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            continue
        seen.add(item_id)
        s = scorer(item)
        if s <= 0:
            continue
        if positions is None:
            dist = (0, abs(i - cursor_index))
        elif item_id in positions:
            dist = (0, abs(positions[item_id] - cursor_index))
        else:
            dist = (1, 0)
        scored.append((-s, dist, i, item))
    scored.sort(key=lambda x: x[:3])
    return [x[3] for x in scored]


def fuzzy_match_prs(prs: list[dict], query: str, plan_map: dict,
                    cursor_index: int = 0,
                    positions: dict[str, int] | None = None) -> list[dict]:
    """Return PRs matching *query*, ranked by score descending.

    Ties are broken by proximity to *cursor_index* (closer = preferred),
    measured in *positions* (pr id -> tree navigation index) when given.
    """
    return _rank(prs, lambda pr: score_pr(pr, query, plan_map),
                 cursor_index, positions)


def fuzzy_match_plans(plans: list[dict], query: str,
                      cursor_index: int = 0,
                      positions: dict[str, int] | None = None) -> list[dict]:
    """Return plans matching *query*, ranked by score descending.

    Ties are broken by proximity to *cursor_index*, measured in *positions*
    (plan id -> index) when given, else the plan's list index.
    """
    return _rank(plans, lambda plan: score_plan(plan, query),
                 cursor_index, positions)
