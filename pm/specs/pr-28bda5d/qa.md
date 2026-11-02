# QA Spec — pr-28bda5d: home window redraws only on actual content change

## Summary

The pm-home tmux window runs a long-lived loop that renders `pm pr list
-t --open`. Previously it cleared and repainted the screen every 5
seconds (plus on sentinel touch), which made a quiet project flicker
once per tick and pushed the absolute clock in the header. This PR
changes the loop to **redraw only when the rendered content actually
changes**:

- The loop wakes on a short tick (~0.75s), on a sentinel-file touch, or
  on a terminal resize (SIGWINCH). Each wake is only a *check*; whether
  to repaint is decided by hashing the rendered output and comparing to
  the last-painted hash.
- Rendering is now **width- and height-aware**: lines are truncated to
  the pane width with an ellipsis, and only the most-recent N PRs that
  fit the pane height are shown, with a `(… and M more)` footer when the
  list overflows. The most-recent PR (sorted `updated_at` desc) is at
  the top and stays visible — no terminal scrolling.
- The absolute clock (`updated HH:MM:SS`) is replaced by a coarse
  relative staleness label (`updated just now` / `Nm ago` / `Nh ago`)
  derived from when content last changed, so the header itself does not
  drive a per-second repaint.
- A `refresh_home(session=None)` helper touches the sentinel; it is now
  invoked in lockstep from the two central mutation hooks
  (`trigger_tui_reload`, which every mutating CLI command already fires,
  and `runtime_state.set_action_state` on real transitions only).

## Shared resources touched by the diff

These are the named resources accessed from more than one caller; each
must be exercised under concurrent use:

1. **Sentinel file** `~/.pm/runtime/home-refresh-<base-session>` —
   touched by `PrListProvider.refresh` / `refresh_home` from every
   mutating CLI command (via `trigger_tui_reload`) and from
   `set_action_state`; polled (stat'd) by the home loop. The single
   wake-up channel between many writers and one reader.
2. **The pm-home pane stdout / TTY** — written (cleared + repainted)
   only by the loop, only on a hash change. Read by the user / capture.
3. **`project.yaml` (store.load)** — read on every loop tick by
   `_render_content`; written by mutating CLI commands.
4. **The pm-home tmux window** — one per session; its size feeds the
   width/height-aware render, and SIGWINCH to its process is the resize
   wake.

## Setup (cross-cutting)

Per `tui-manual-test.md`:

1. Install the editable pm clone and confirm `pm which` points at it
   (override `PYTHONPATH` so the container's `/opt/pm-src` master copy
   does not shadow it). If `pm` is unavailable in the container, run
   `./install.sh --local` from the pm repo.
2. Create a throwaway git project, `pm init --backend local --no-import`.
3. Add PRs with `pm pr add` to reach the fixture state the scenario
   needs (a handful for nominal cases; many — more than a short pane is
   tall — for the overflow case). Bootstrapping mixed statuses by
   editing `project.yaml` directly is allowed *only* during setup; once
   the session is running, all mutations go through the pm CLI/TUI.
4. Start the session (`pm session 2>/dev/null || true`) — this creates
   the tmux session and the `pm-home` window running the loop. Inspect
   the pm-home pane with `tmux capture-pane -p` and drive pm commands
   from a *separate pane inside the test session* (never the worker's
   own shell session).

## Requirements (Given / When / Then)

### R1 — Quiet project produces a quiet window (no timer redraw)
- **Given** a running pm session whose pm-home window shows the open-PR
  list and no pm command is run.
- **When** the user watches the pm-home pane idle for ~30 seconds.
- **Then** the pane is not cleared or repainted on any tick — its
  content stays visually stable (no flicker / no screen-clear), and the
  relative staleness label does not flip within the first minute (stays
  `just now`).

### R2 — A state mutation redraws the window promptly
- **Given** a running pm session with at least one open PR shown in
  pm-home.
- **When** the user runs a state-mutating pm command from another pane
  (e.g. `pm pr edit <id> --status in_review`, or `pr add`, `close`,
  `merge`, `start`).
- **Then** the pm-home pane redraws within ~1 second to reflect the new
  state (the changed PR's status/line updates, a new PR appears, a
  closed/merged PR disappears).

### R3 — Redundant sentinel touch with no real change does not redraw
- **Given** a running pm session with a stable open-PR list in pm-home.
- **When** the sentinel file is touched (e.g. `touch
  ~/.pm/runtime/home-refresh-<base>`) with no underlying project change.
- **Then** the loop wakes, recomputes the hash, finds no diff, and does
  **not** repaint — the pane content is unchanged and no clear occurs.

### R4 — Resize redraws immediately and fits the new width
- **Given** a running pm session whose pm-home list has lines long
  enough to be affected by width.
- **When** the user changes the pane width (e.g. tmux split/resize so the
  pane is narrower or wider).
- **Then** the pane redraws promptly (driven by SIGWINCH, not waiting a
  full tick), every line is truncated/fitted to the new width, and there
  is no leftover wrapped/soft-wrapped output from the previous width.

### R5 — Narrow pane truncates titles cleanly
- **Given** a running pm session with PRs whose lines exceed a narrow
  width.
- **When** the user makes the pane very narrow (mobile-mode width).
- **Then** each line is truncated to the width with a trailing ellipsis
  (`…`), with no soft-wrap artifacts and no line exceeding the pane
  width.

### R6 — Overflow shows most-recent-first with a "+M more" footer
- **Given** a running pm session whose project has more open PRs than the
  pm-home pane is tall.
- **When** the user views the pm-home pane.
- **Then** only the most-recent N PRs that fit are shown, the *top* of
  the list (most recent, `updated_at` desc) is visible (the oldest are
  hidden, not the reverse), and the last visible row is a footer reading
  `(… and M more)` where M is the number of hidden PRs. The pane does
  not scroll past the header.

### R7 — Header shows relative staleness, not an absolute clock
- **Given** a running pm session showing the pm-home list.
- **When** the user reads the header line.
- **Then** the header shows a relative freshness label (`updated just
  now`, then `updated Nm ago`, then `updated Nh ago`) and does **not**
  contain an absolute `HH:MM:SS` wall-clock time. The label is derived
  from the last content change, and a bucket flip (e.g. crossing one
  minute) triggers exactly one repaint, not a per-second one.

### R8 — Action-state transitions kick the window
- **Given** a running pm session where a PR action (review/qa/etc.)
  changes state through the normal pm flow.
- **When** the action transitions to a new state (start, finish, clear).
- **Then** pm-home redraws to reflect the change. (A no-op repeat
  heartbeat write of the same state does not, but that is below the
  user-visible surface — verified at R2/R3 granularity by whether a
  redraw appears.)

## Edge Cases (Given / When / Then)

### E1 — Concurrent mutations from multiple panes
- **Given** a running pm session with the pm-home loop active.
- **When** two or more panes/actors run mutating pm commands at nearly
  the same time, each touching the same sentinel file.
- **Then** the loop converges to a single correct final render reflecting
  all mutations, with no corruption, no crash, and no missed final
  update (the last writer's change is reflected). Rapid-fire touches
  collapse into at most a small number of repaints, not one per touch.

### E2 — Project fails to load
- **Given** a running pm session whose `project.yaml` is temporarily
  unreadable or malformed.
- **When** the loop ticks and tries to render.
- **Then** the pane shows a single truncated error line (`pm pr list
  (home): error loading project: …` or `render error: …`) instead of
  crashing, and the long-lived loop keeps running; once the project is
  readable again a subsequent change repaints the normal list.

### E3 — Present-but-null `project:` key
- **Given** a project whose `project.yaml` has a `project:` key set to
  null (and PRs present).
- **When** the pm-home loop renders.
- **Then** it renders the PR list normally (active_pr simply absent) and
  does **not** get stuck on a persistent "render error" (regression
  guard from review i6).

### E4 — Empty list / no open PRs
- **Given** a running pm session with no open PRs (all closed/merged or
  none added).
- **When** the user views pm-home.
- **Then** the body shows `No open PRs.` under the header, truncated to
  width, with no footer.

### E5 — Tiny / degenerate pane size
- **Given** a running pm session with a pm-home pane only one or two rows
  tall, or one column wide.
- **When** the loop renders.
- **Then** output is clamped to the pane height (no scrolling that pushes
  the header off-screen) and to the width (a 1-column pane yields `…`),
  with no crash.

### E6 — refresh_home outside a resolvable session
- **Given** a context where no tmux session can be resolved (not inside
  tmux, or the session doesn't exist).
- **When** a mutation hook calls `refresh_home`.
- **Then** it silently no-ops (no error surfaced to the user, the
  mutating command still succeeds). A broken/raising kick must never
  break the underlying state write or CLI command.

## Pass / Fail Criteria

**Pass:**
- Idle window does not clear/repaint within a tick window; relative label
  stable for the first minute (R1).
- A real mutation repaints within ~1s; a redundant sentinel touch does
  not repaint (R2, R3).
- Resize repaints promptly with all lines fitted to the new width and no
  leftover wrap (R4); narrow width truncates with `…` (R5).
- Overflow shows the most-recent N at top + `(… and M more)` footer, with
  oldest hidden and no scroll (R6).
- Header uses relative phrasing, never an `HH:MM:SS` clock (R7).
- Error/null/empty/tiny inputs degrade gracefully without crashing the
  loop (E2–E5).
- Concurrent mutations converge to one correct final render (E1).
- A mutation when no session is resolvable doesn't error the command
  (E6).

**Fail:**
- The pane clears/repaints on a quiet tick (flicker returns).
- A real mutation is not reflected within a couple of seconds.
- A no-op sentinel touch causes a visible repaint.
- Resize leaves wrapped/overflowing lines or stale wider text.
- Overflow shows the oldest PRs / the bottom of the list, or omits the
  `(… and M more)` footer, or scrolls the header off-screen.
- The header still prints an absolute clock.
- Any input (null project key, malformed yaml, 1-row pane) crashes or
  permanently wedges the loop on an error line.
- A mutation command fails or errors because the home kick raised.

## Ambiguities (resolved)

- **Exact tick / timing thresholds.** The PR mentions 0.5–1s; the
  implementation uses `TICK_SECONDS = 0.75` with a ≤0.1s inner sleep.
  Tests assert "within ~1s" rather than an exact value, to stay robust
  to the chosen constant.
- **Staleness bucket boundaries.** Resolved to the implemented buckets:
  `just now` (<60s), `Nm ago` (<60m), `Nh ago` (otherwise). "No flip in
  the first minute" follows from the `<60s = just now` bucket.
- **How resize is exercised.** The PR text references tmux
  split-pane/kill-pane changing width; resolved to driving any width
  change to the pm-home pane (resize/split) and observing SIGWINCH-driven
  repaint, rather than a specific tmux command.
- **Driving the home pane.** The home window is a tmux *window*
  (`pm-home`) running the loop; observed via `tmux capture-pane` and
  driven indirectly through pm commands in a sibling pane. No direct
  import of loop internals — all exercise is through the running session,
  per the user's QA guidance.
