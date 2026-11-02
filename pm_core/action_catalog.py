"""Shared PR action catalog.

Surface-neutral definitions of PR actions that the terminal PR actions
pane (``pm _popup-picker`` in :mod:`pm_core.cli.session`) renders, and
that the planned mobile actions pane (pr-72c8695) will render from the
same records.  Session-launching actions (start/review/qa/sign-off/merge)
still live in ``session.py``'s tables until pr-72c8695 moves them here;
this module currently holds the *view* actions — read-only actions that
show information instead of launching or attaching to a session.

A view action supplies a ``query`` (PR id + project.yaml record →
JSON-able model) and a ``render`` (model → text lines).  Every surface
calls those two functions, so the CLI, the terminal pane and a web pane
show the same data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ActionDef:
    key: str                 # stable identifier (also the row label)
    label: str               # human-readable name
    kind: str                # "session" | "view"
    shortcut: str            # picker key
    cli: str                 # equivalent ``pm`` command template ({pr_id})
    description: str
    # Statuses the action is offered for; ``None`` means every status,
    # including merged/closed.
    statuses: tuple[str, ...] | None = None
    query: Callable[..., dict] | None = None
    render: Callable[..., list[str]] | None = None
    badge: Callable[[dict], str] | None = None

    def available_for(self, status: str) -> bool:
        return self.statuses is None or status in self.statuses


def _history_query(pr_id: str, pr: dict | None = None) -> dict:
    from pm_core import history_query
    return history_query.build_history(pr_id, pr=pr)


def _history_render(model: dict, width: int = 80) -> list[str]:
    from pm_core import history_query
    return history_query.render_text(model, width=width)


def _history_badge(model: dict) -> str:
    from pm_core import history_query
    return history_query.summary_badge(model)


HISTORY = ActionDef(
    key="history",
    label="History",
    kind="view",
    shortcut="H",
    cli="pr history {pr_id}",
    description=("Past action attempts with timings and outcomes, plus the "
                 "timers and holds PM is waiting on"),
    statuses=None,  # stays available after merge
    query=_history_query,
    render=_history_render,
    badge=_history_badge,
)

VIEW_ACTIONS: tuple[ActionDef, ...] = (HISTORY,)


def view_actions(status: str | None = None) -> list[ActionDef]:
    """View actions offered for a PR in *status* (all when ``None``)."""
    return [a for a in VIEW_ACTIONS
            if status is None or a.available_for(status)]


def get(key: str) -> ActionDef | None:
    return next((a for a in VIEW_ACTIONS if a.key == key), None)
