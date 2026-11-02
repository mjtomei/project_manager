# QA Spec: Picker popup — per-session window-selected indicator (● / ○)

PR: pr-48cb564 / GitHub #218

## Summary of the change (user-facing)

The PR action picker (opened with **prefix+P** in a pm tmux session) lists
each action of a PR as its own row (`start`, `review`, `qa`, `merge`). Each
action row corresponds to a tmux **window** for that PR. The change adds a
per-session "who is looking at this window right now" indicator in the leading
column of each action row:

- **●** (filled dot) — the action's window is the **currently-selected window
  in the caller's own tmux session** (the session that pressed prefix+P).
- **○** (open circle) — the action's window is the currently-selected window
  in **some other attached grouped session** (a collaborator's client has it
  focused right now), and the caller is *not* focused on it.
- **blank** (a single space) — the window is open but is not the active window
  of any *attached* session.

Priority: if both apply (the caller and another session are both focused on
the window), show **●**.

A pm session is a tmux session group: a (usually unattached) **base** session
plus one **grouped** session per attached client (`base~1`, `base~2`, …). Each
attached client can have a different active window. The indicator is computed
by querying every session in the group for its active window, but only
sessions with a client actually attached count.

This is a **snapshot** — the indicators reflect state at the moment the popup
opens; they do not live-update while it is open (out of scope).

---

## 1. Requirements (Given / When / Then)

### R1 — Caller's own active window is marked ●
- **Given** a pm session where the caller's client is focused on a PR's impl
  window (e.g. the `start` action window).
- **When** the user opens the PR action picker with prefix+P.
- **Then** the `start` action row for that PR shows the **●** indicator in its
  leading column, and the other action rows for that PR are blank (no other
  session is viewing them).

### R2 — Another session's active window is marked ○
- **Given** a pm session with two attached clients: the caller focused on PR's
  impl (`start`) window, and a second grouped client focused on the PR's
  `review` window.
- **When** the caller opens the picker with prefix+P.
- **Then** the `start` row shows **●** (caller's window) and the `review` row
  shows **○** (the other client's window); all other rows are blank.

### R3 — Same window viewed by caller and another session shows ●
- **Given** a pm session with two attached clients both focused on the *same*
  PR window (the impl window).
- **When** the caller opens the picker.
- **Then** that window's row shows **●** (the caller takes priority); it does
  **not** show ○.

### R4 — Window viewed by nobody is blank
- **Given** a PR with multiple open action windows, none of which is the active
  window in any attached session.
- **When** the caller opens the picker.
- **Then** those rows have a blank leading indicator (a single space) while
  still showing their other tags (`[open]`, status), and the column stays
  aligned with rows that do carry a dot.

### R5 — Column alignment / row format preserved
- **Given** a picker showing a mix of ●, ○, and blank rows.
- **When** the user reads the picker.
- **Then** the action label, `[open]` tag, and status tag all line up across
  rows regardless of which indicator a row has (the indicator occupies one
  fixed leading cell).

### R6 — Indicator coexists with existing tags
- **Given** an action window that is both open and being viewed by another
  session (e.g. a `review` window a collaborator is on).
- **When** the caller opens the picker.
- **Then** that row shows both the **○** indicator and the **[open]** tag (and
  any live status tag such as `[working]`), without one clobbering the other.

---

## 2. Setup (cross-cutting)

Tests run against a throwaway pm project (see `tui-manual-test.md`):
- Init a local-backend pm project with at least one PR that has multiple
  windowed actions available for its status (an `in_progress` / `in_review`
  PR exposes `start`/`review`/`qa`/`merge` rows).
- Start a pm tmux session, and to exercise the multi-session axis, create and
  **attach** additional grouped clients to the same session group (a second
  `pm session` attach, or `tmux attach -t base` inside a pty-bearing pane per
  the tmux-screen-recording recipe). Each attached client can be pointed at a
  different window via tmux window selection.
- Drive the picker the way a user does: press prefix+P from the client whose
  perspective is under test, and observe the rendered rows.

The shared resource under test is the **tmux session group's per-session
active-window state**, read live at popup time via `display-message` on each
session. Multiple attached clients on different windows is the normal,
intended concurrent configuration for this feature.

---

## 3. Edge Cases (Given / When / Then)

### E1 — Caller on a non-PR window
- **Given** the caller's client is focused on a non-PR window (e.g. the `main`/
  TUI window), while another attached client views a PR's `qa` window.
- **When** the caller opens the picker.
- **Then** no action row carries **●** (the caller's active window matches no
  action window), but the `qa` row carries **○** (the collaborator's view).

### E2 — Unattached base session does not contribute ○
- **Given** a session group whose base session has an "active window" in tmux's
  bookkeeping but **no client attached**, plus one attached grouped client.
- **When** the attached client opens the picker.
- **Then** the base session's bookkeeping active window does **not** produce a
  spurious ○ — only attached sessions contribute indicators.

### E3 — Navigating to another PR (h/l)
- **Given** two PRs each with open windows; the caller is on PR-A's impl window
  and a second client is on PR-B's `review` window; the picker is open.
- **When** the user navigates the picker from PR-A to PR-B (h/l keys).
- **Then** PR-B's `review` row shows **○** (the collaborator viewing it) and
  PR-B's rows generally show no **●** (the caller is not focused on any of
  PR-B's windows). This is the headline "see what a collaborator is looking
  at" use case.

### E4 — QA scenario window with a suffix
- **Given** a PR whose live QA window is a scenario-suffixed window (e.g.
  `qa-#170-s1`) and a second client is focused on it.
- **When** the caller opens the picker.
- **Then** the single `qa` action row reflects that focus with **○** (or **●**
  if the caller is the one on it) — the suffix variant is matched, not just the
  bare `qa-#170` name.

### E5 — Multiple other sessions on the same window
- **Given** two distinct grouped clients (neither the caller) both focused on
  the same PR window.
- **When** the caller opens the picker.
- **Then** that row shows a single **○** (set membership, not a count) and no
  duplicate/garbled indicator.

### E6 — tmux query failure / degenerate group
- **Given** a single-client session group (only the caller attached), or a
  situation where per-session active-window queries return nothing useful.
- **When** the caller opens the picker.
- **Then** the picker still renders correctly: in the single-client case the
  caller's current window shows **●** and the rest blank; on total query
  failure all rows fall back to blank without an error or crash.

---

## 4. Pass / Fail Criteria

**Pass:**
- The leading indicator on each action row matches the rule: ● for the caller's
  active window, ○ for another attached session's active window, blank
  otherwise, with ● winning ties (R1–R3, E1, E3, E5).
- Unattached sessions never contribute ○ (E2).
- Suffixed QA windows are matched (E4).
- Columns stay aligned and existing `[open]`/status tags still render (R4–R6).
- No crash, traceback, or hang when opening the picker in any of the above
  configurations, including single-client and query-failure (E6).

**Fail:**
- Wrong glyph for a window's focus state (e.g. ○ where the caller is focused, ●
  for a collaborator's window, or a dot where nobody is focused).
- An unattached base session producing a phantom ○.
- A suffixed QA window not being recognized.
- Misaligned columns or a clobbered `[open]`/status tag.
- Any exception, popup failure, or hang triggered by the new active-window
  querying.

---

## 5. Ambiguities (resolved)

- **A1 — Replace vs augment the prior phase dot.** The picker previously showed
  a single phase-derived ● ("the window the caller is viewing"). The new
  indicator **replaces** that in the real popup path (the popup always supplies
  the active-window map); the phase fallback is retained only when no map is
  supplied. Resolved per impl.md A1; not a separate user-facing behavior.
- **A2 — "Attached" definition.** ○/blank are computed over *attached* sessions
  only; the base session typically has no client and is excluded. Resolved per
  impl.md IR2 / E2.
- **A3 — Glyph width.** Both ● and ○ render in one cell matching the existing
  leading column; no alignment change beyond the existing format.

No **[UNRESOLVED]** ambiguities.
