# Spec: Picker popup — per-session window-selected state (● vs ○)

PR: pr-48cb564 / GitHub #218

## Background — how the picker actually works

The task description imagines the picker as "a list of active PR windows with
status emoji (⏳ 🔨 …)". The real implementation
(`pm_core/cli/session.py:popup_picker_cmd`, ~line 1626; rows built by
`_build_picker_lines`, ~line 1057) is an **action picker for one PR at a
time**:

- It shows one PR's header line plus one **action row** per windowed action:
  `start`, `review`, `qa`, `merge` (`_LIST_ACTIONS`). `h`/`l` navigate between
  PRs that have open windows.
- Each action row corresponds to a tmux **window** via
  `_ACTION_WINDOW_PATTERNS`:
  - `start`  → `{display_id}`            (e.g. `#170`, the impl window)
  - `review` → `review-{display_id}`
  - `qa`     → `qa-{display_id}`         (scenario suffixes possible: `qa-#170-s1`)
  - `merge`  → `merge-{display_id}`
- A `●` already appears at the start of the matching **phase** row
  (`indicator = "●" if label == phase` at session.py:1118). `phase` is
  `_current_window_phase(window_name)` for the *home* PR (the window the picker
  was invoked from) — i.e. it already marks "the window the caller's own
  session is currently viewing". For navigated-to PRs `phase == ""`, so no dot.

So the "PR windows in the picker list" are precisely these action-row windows,
and the existing `●` is already a (window-name-derived) form of the caller's
"currently-selected window" indicator. This change **generalizes** that single
dot into a tmux-queried, per-session indicator and adds the `○` case.

## 1. Requirements (grounded)

R1. For each action row in the picker, prepend an indicator:
- `●` — that action's window is the active window in the **caller's own**
  tmux session (the `session` arg passed to `popup_picker_cmd`, captured by the
  popup body at session.py:60 as `#{session_name}`).
- `○` — that action's window is the active window in **some other grouped
  session** that has a client attached.
- ` ` (single space) — open but not the active window of any attached session.

R2. Both apply → show `●` (caller takes priority). Implemented as: test `●`
first, fall back to `○`.

R3. Determine the per-session active windows by iterating
`tmux_mod.list_grouped_sessions(base)` (plus `base` itself) and querying each
session's active window id via `tmux display-message -t <session> -p
#{window_id}`. Build a map `session_name -> active window_id`. Add a small
helper for this in session.py (`_session_active_windows`).

R4. Resolve each action row's window **name** to a window **id** so it can be
compared against the active-window map. Use the existing
`tmux_mod.list_windows(base)` call (already made at session.py:1669 for
`open_windows`) to build a `name -> id` map in the same pass.

R5. Render: the indicator occupies the existing leading indicator column so
columns line up. Current format `"  {indicator} {label:<18s}{open_tag}{status_tag}"`
is preserved; only how `indicator` is computed changes. The result reads e.g.
`  ● start            [open] [working]` / `  ○ review` / `    qa`.

R6. Tests: synthetic group (caller-session + two grouped sessions); verify the
indicator is `●` / `○` / blank correctly, including (a) same window active in
caller AND another session → `●`, (b) active only in another → `○`, (c)
unselected → blank.

## 2. Implicit requirements

- IR1. **Backward compatibility of `_build_picker_lines`.** The new
  active-window info is passed via new optional params. When absent (existing
  callers / existing tests like `test_phase_indicator_shown`), fall back to the
  current phase-based `●`. The window-id path is used only when the caller
  supplies the active-window map (the real popup always does).
- IR2. **"Attached" filtering.** The blank rule says "not active in any
  *attached* session", and `○` means "any *client other than the caller* has it
  focused". The base session is typically unattached (TUI runs in grouped
  sessions). So the active-window map must include only sessions with ≥1 client
  attached. Query `#{session_attached}` alongside `#{window_id}` and skip
  sessions reporting `0`. The caller is attached by construction (it is driving
  the popup), so it is naturally included.
- IR3. **QA scenario windows.** A `qa` row's window can be `qa-#170` or
  `qa-#170-s1` etc. Mirror the existing open-tag prefix match
  (session.py:1127): a `qa` row resolves to *every* window whose name equals
  `qa-{display_id}` or starts with `qa-{display_id}-`. Mark `●`/`○` if **any**
  of those windows is the caller's / another session's active window.
- IR4. **Caller key match.** `session` (from `#{session_name}`) must key into
  the map identically to `list_grouped_sessions` output (`base` or `base~N`).
  Both derive from `#{session_name}`, so they match.

## 3. Ambiguities (resolved)

- A1. *Does the new indicator replace or augment the phase `●`?* **Replace**
  (in the real popup path). The phase `●` already means "the window the caller
  is viewing", which is the window-id `●` case. Unifying avoids two conflicting
  dots in the same column. The phase path is retained only as the
  no-active-map fallback (IR1), keeping current behavior/tests intact.
- A2. *Include the unattached base session's "active window" as `○`?* **No** —
  filtered out by IR2; an unattached session has no client focusing it.
- A3. *`●` vs `○` glyph width / alignment.* Both render in one cell, matching
  the existing `●`/space column; no width handling change needed.
- A4. *What if tmux queries fail (empty map)?* `name_to_wid` still comes from
  `list_windows`; with an empty active map all rows render blank. Same tmux
  surface backs both calls, so in practice if `list_windows` works the
  active-window query works too. Acceptable.

No **[UNRESOLVED]** ambiguities.

## 4. Edge cases

- E1. Picker invoked from a non-PR window (`current_pr`/home None): the caller's
  active window won't match any action row → no `●`; other sessions can still
  contribute `○`. Correct.
- E2. Navigating (`h`/`l`) to a different PR: caller isn't viewing it, so its
  rows get `●` only if (unusually) the caller's active window id collides; `○`
  appears where a grouped session is viewing one of that PR's windows. This is
  the headline use case (see what a collaborator is looking at).
- E3. Single-user, single (base) session: only the caller in the map; behaves
  exactly like the old phase `●` (caller's current window dotted, rest blank).
- E4. Multiple grouped sessions viewing the same window: still one `○` (or `●`
  if the caller is among them) — set membership, not a count.
- E5. A window that is open but no session's active window: `[open]` tag still
  shown by existing logic, indicator blank. The two are independent.

## 5. Implementation plan

1. `pm_core/tmux.py`: add `attached_active_window(session, socket_path=None) ->
   str | None` — one `display-message -p "#{session_attached} #{window_id}"`
   call; returns the window id only when attached count != 0, else None.
2. `pm_core/cli/session.py`:
   - add `_session_active_windows(base) -> dict[str, str]` iterating
     `[base] + list_grouped_sessions(base)` via `attached_active_window`.
   - in `popup_picker_cmd`: capture `all_windows = list_windows(base)` once;
     derive `open_windows` and `name_to_wid`; compute `active_map`,
     `caller_wid = active_map.get(session)`, `other_wids = {wid for s,wid in
     active_map.items() if s != session}`; thread these into `_resolve_for` →
     `_build_picker_lines`.
   - `_build_picker_lines`: new optional params `caller_wid`, `other_wids`,
     `name_to_wid`. When `name_to_wid is not None`, compute indicator from
     window ids (with qa prefix-match per IR3); else keep phase fallback.
3. Tests in `tests/test_popup_picker.py`: render-level cases passing the new
   params directly, plus a `_session_active_windows` test mocking
   `tmux_mod`.
