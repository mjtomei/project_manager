# Spec: pr-0b4e1a9 — pr start window-switch hijacks an arbitrary attached grouped session

## Problem (grounded)

Focus-mutating tmux helpers in `pm_core/tmux.py` resolve *which session to
switch* through `current_or_base_session(base)` (tmux.py:501-529), whose
docstring says it returns "the best session to target for **query
operations**". Its fallback chain is safe for read-only queries but wrong for
focus changes:

1. In tmux and current pane's session is in the group **and attached** →
   return current. (correct caller)
2. Otherwise (not in tmux, or current session has no client — e.g. `pr start`
   from a plain CLI shell, or caller in a *different* project's session) →
   loop `list_grouped_sessions(base)` and return the **first attached grouped
   session found**, regardless of what window it is viewing.
3. Fallback: the base session.

Three callers route focus changes through this and inherit the hazard:

- `new_window` (tmux.py:134-159) — `select-window` after `-d` create when
  `switch=True`.
- `new_window_get_pane` (tmux.py:162-193) — same, then returns the pane id.
- `select_window` (tmux.py:402-413) — every switch-to-existing-window.

Consequence: when the caller's own client can't be identified, step 2 grabs
an arbitrary attached grouped session and `select-window` **hijacks whatever
that session was viewing** (observed: a session mid-review-loop yanked onto a
freshly-started PR window).

## Requirements (restated, grounded)

R1. Focus-mutating switches (`new_window`/`new_window_get_pane` with
`switch=True`, and `select_window`) must target **only the caller's own
client's session**, resolved via `$TMUX`/`$TMUX_PANE`
(`in_tmux()` + `get_session_name()`), never an arbitrary attached grouped
session.

R2. When the caller's own client **cannot** be identified (not in tmux, or
current pane's session is not in this base's group), **no session's active
window may change**. `new_window`/`new_window_get_pane` already create the
window with `-d` (detached); they must simply skip the `select-window`.
`select_window` must skip the switch and report it did not switch.

R3. The caller's own client, **when identifiable**, still switches to the
new/target window (preserve today's correct behavior, incl. the PR-actions
popup spinner at session.py:1509-1522 whose `display-popup -E` runs in-tmux
with `$TMUX_PANE` set to the origin session).

R4. `current_or_base_session` keeps its existing query-only behavior for
genuine read-only callers (e.g. `pane_layout.py:92`, `qa_status.py` mirror,
`get_window_id`). Only focus changes stop routing through it.

## Implementation

Add a focus-safe resolver in `pm_core/tmux.py`:

```python
def caller_switch_target(base: str) -> str | None:
    """Return the caller's OWN grouped session for a focus-mutating switch,
    or None when the caller's client can't be identified."""
    if in_tmux():
        current = get_session_name()
        if current and (current == base or current.startswith(base + "~")):
            return current
    return None
```

No attached-client check is needed: by construction the caller is *in* that
session, and switching the caller's own (possibly detached) session steals
nobody's focus. The key difference from `current_or_base_session` is the
**absence of the step-2 arbitrary-grouped fallback** — unidentifiable caller
→ `None`.

Rewire:
- `new_window`: replace `current = current_or_base_session(session)` /
  unconditional `select-window` with `target = caller_switch_target(session)`;
  only `select-window` when `target` is truthy, else log "no caller client,
  left detached".
- `new_window_get_pane`: same, before discovering the pane id (pane discovery
  is unaffected by switch).
- `select_window`: `target = caller_switch_target(session)`; if `None`, log
  and `return False` (did not switch); else `select-window` and return
  `rc == 0` as before.

Update `current_or_base_session` docstring to state it is query-only and must
not be used for focus changes (point to `caller_switch_target`).

## Implicit requirements

- All in-tmux callers (TUI: `app.py`, `pr_view.py`, `pane_ops.py`,
  `qa_loop_ui.py`; review/QA loops in `qa_loop.py`, `pane_layout.py:635`;
  popup spinner `session.py:1516`) run with `$TMUX_PANE` in the group, so
  `caller_switch_target` returns their own session — behavior unchanged for
  them. Verified none branch on `select_window`'s bool as a hard failure
  (all fire-and-forget or log-only).
- `home_window.park` (init.py:191-207) already guards `in_tmux()` before
  `select_window`; `park_if_on` uses `select_window_in_session` (explicit
  target) and is untouched.
- `-d` on `new-window` already prevents the *base* session from switching, so
  R2's "create detached" needs no new tmux flag — just skip the follow-up
  `select-window`.

## Edge cases

- Caller in a *different* project's tmux session running `pr start` for this
  project: pre-fix step 2 would hijack a grouped session of *this* project;
  post-fix `get_session_name()` is not in this base's group → `None` → no
  switch. (Covered by R2; this is a hijack case beyond the reported CLI-shell
  one and is now also fixed.)
- Caller's own session is detached (background process inside tmux): returns
  the caller session; `select-window` on a clientless session is harmless.
- `select_window` now returns `False` when it intentionally skipped (no
  caller). Honest "did not switch"; no caller treats this as an error path.

## Ambiguities

None unresolved. Resolved decisions:
- Drop the attached-client check in the focus-safe resolver (caller is by
  definition present in its own session). 
- `select_window` returns `False` (not `True`) on intentional skip, since the
  contract is "switched to window" and it did not.

## Acceptance → tests (`tests/test_tmux.py`)

- `caller_switch_target`: in-tmux same/grouped → returns it; not in tmux →
  None; in tmux but different group → None.
- `new_window` / `new_window_get_pane`: caller identifiable → `select-window`
  issued targeting the caller; **caller NOT identifiable (with attached
  grouped sessions present) → NO `select-window` issued** (fails pre-fix —
  the arbitrary-session hijack — passes post-fix).
- `select_window`: identifiable → switches caller, returns rc==0; not
  identifiable → returns False, no `select-window`.
- Update existing tests that patch `current_or_base_session` for these three
  functions to patch `caller_switch_target` instead.
