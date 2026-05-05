# pr-28bda5d — home window: redraw only on actual content change

## Requirements

1. **Hash-diff redraw in `_loop_main`** (`pm_core/home_window/pr_list.py:109`).
   Replace the unconditional 5s timer redraw with: short tick (~0.5s),
   sentinel touch, and SIGWINCH all serve as 'check' triggers; only
   write to stdout when the hash of `_render_once()`'s output differs
   from the last written hash.

2. **Width- and height-aware `_render_once`** (`pm_core/home_window/pr_list.py:75`).
   Read `os.get_terminal_size()`; truncate each line to width with
   ellipsis; print only the first N rows that fit (height − header
   lines − optional footer); when truncated, append `(… and M more)`.
   Renderer is already sorted descending by `updated_at` so `prs[0]`
   is the most recent and stays visible at the top.

3. **SIGWINCH handler.** Install a signal handler that sets a wake
   flag so the inter-tick sleep wakes immediately on resize.

4. **Drop absolute clock from header.** The current
   `(updated HH:MM:SS)` changes every second. Replace with relative
   staleness (`(updated 8s ago)`) derived from a tracked
   last-content-changed timestamp — recomputed cheaply each tick so
   the relative phrasing itself does not force redraws once it
   stabilises into the same bucket.

5. **`refresh_home(session=None)` helper** in
   `pm_core/home_window/__init__.py`. Resolves the active session
   (mirrors `_get_pm_session` / `_find_tui_pane` logic), gets the
   active provider, calls `provider.refresh(session)`. Tolerates
   "not in tmux" / "no session" silently.

6. **Call-site audit.** Mutating commands and `set_action_state`
   should kick the home window. With hash-diff in place, redundant
   calls are free.

## Implicit requirements

- The hash used for comparison must include width/height inputs since
  resizing genuinely changes rendered output (already implicit via
  width-truncated lines and N-fitted rows).
- `_render_once` must not take width/height from environment; the
  pm-home loop is attached to the pane TTY, so `os.get_terminal_size()`
  on stdout returns correct dims.
- The relative-time header must use a *bucket* (whole seconds /
  minutes) so it doesn't change on every tick when content is stable
  — otherwise the hash always differs and we redraw on every tick,
  defeating the whole change.
  - Resolution: round to whole seconds for <60s, then minutes. Hash
    diffs only when the bucket flips, which is exactly the cadence
    the user wants for staleness perception.
- SIGWINCH is process-global; only register it once, in `_loop_main`.

## Resolutions to implementation choices

- **Header staleness format**: `(updated Ns ago)` for N<60,
  `(updated Nm ago)` for 1≤N<60, `(updated Nh ago)` beyond. Use
  monotonic-tracked `last_content_change` time updated when hash
  diffs.
- **Width truncation**: simple character truncation with `…`
  appended when the line is over width; no ANSI/wide-char awareness
  — `format_pr_line` produces plain ASCII per current code.
- **Footer**: `(… and M more)` only when M > 0.
- **Refresh wiring**: rather than touching every CLI mutation site,
  hook `refresh_home()` into the existing `trigger_tui_reload`
  helper (`pm_core/cli/helpers.py:464`) and into
  `runtime_state.set_action_state` (`pm_core/runtime_state.py:112`).
  Existing callsites (>20 in pr.py alone) all already call
  `trigger_tui_refresh`; piggy-backing keeps the diff small and
  guarantees coverage. The standalone `refresh_home(session=None)`
  helper is exposed on the package for future direct callers.
- **Tick cadence**: 0.75s — fast enough that sentinel/winch latency
  is imperceptible without burning CPU on idle panes.
- **Signal restoration**: use `signal.signal` only when running as
  the loop process (i.e. inside `_loop_main`). Importing the module
  in tests must not register handlers.

## Edge cases

- Tiny panes: if `height < 3` (header + ruler), still emit at least
  the header line (truncated). No crash.
- `os.get_terminal_size()` may raise `OSError` if stdout isn't a
  TTY (e.g. when capturing for tests). Fall back to (80, 24).
- Sentinel file removed mid-run: `stat()` raises `FileNotFoundError`
  — already handled; treat as 0.0.
- Concurrent grouped sessions: the sentinel is keyed on the base
  session, so any grouped session's writer wakes the loop. No
  change.
- Stdout buffer behaviour: we currently write entire screen-clear +
  body each redraw. Keep that — partial updates are out of scope.

## Out of scope (per description)
inotify, live deltas, scrollable home pane.
