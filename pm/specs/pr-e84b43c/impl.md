# pr-e84b43c — Watcher review session: Claude pane with work-log access

## Summary

Add a new TUI keybinding that launches a Claude pane configured as a "watcher
review" session: a conversational human surface for the autonomous watchers
defined in `plan-regression`. The session has read access to the three
watchers' work logs, current PR/plan state, and per-test transcripts; it
opens with a summary of recent activity and is chat-driven afterwards.

## Requirements (grounded in code)

1. **TUI keybinding launches the session.**
   Add a watcher-review action in `pm_core/tui/app.py`. Existing precedent:
   `Binding("w", "focus_watcher", ...)` at app.py:154 enters a "w prefix"
   mode dispatched in `on_key()` (app.py:181-199) with sub-keys `w`/`f`/`s`.
   Add a new sub-key — `wr` — that dispatches to a new
   `_action_watcher_review` method.

2. **Action delegates to a new pane_ops helper.**
   Following the pattern of `launch_claude` (pane_ops.py:312-356) and
   `launch_discuss` (pane_ops.py:359-419), add
   `launch_watcher_review(app)` in `pm_core/tui/pane_ops.py` that:
   - Resolves the meta workdir's `pm/` root via
     `pm_core.cli.meta.ensure_meta_workdir()` (same call already used in
     `launch_meta` and `watcher_ui.ensure_watcher_plans`) to find where the
     watcher logs live.
   - Builds a Claude prompt (see #4 below) and invokes
     `claude_launcher.find_claude` / `build_claude_shell_cmd` to construct
     the shell command.
   - Calls `launch_pane(app, cmd, "watcher-review", fresh=fresh)` so the
     existing pane-dedup logic handles re-entry.

3. **System prompt grants read access and explains architecture.**
   The prompt (built by a new helper `generate_watcher_review_prompt(...)`
   in `pm_core/prompt_gen.py`, mirroring `generate_discovery_supervisor_prompt`
   at prompt_gen.py:832) must include:
   - Pointers to the three work logs:
     `<meta_pm_root>/watchers/discovery.log`,
     `<meta_pm_root>/watchers/bug-fix-impl.log`,
     `<meta_pm_root>/watchers/improvement-fix-impl.log`.
     (The first path matches what `generate_discovery_supervisor_prompt`
     already uses at prompt_gen.py:875. The other two follow the names in
     `plan-regression.md` and the conventions of `pr-e3a711c` /
     `pr-d39a7fb` even though those watchers aren't merged yet.)
   - Instruction to begin by reading those logs (with `tail`-style
     commands that tolerate missing files) plus `pm pr list` and
     `pm pr graph` for project state, then produce a one-screen summary
     covering activity per watcher since the last review.
   - A short architecture explainer naming the three watchers, what each
     does, and where their transcripts live (the watcher transcript dir
     used by `auto_start.get_transcript_dir`).
   - The standard `tui_section(session_name)` block (prompt_gen.py:28) so
     the session knows how to drive the TUI for follow-up actions.
   - Read-only safe-to-run commands list (mirror the list in `launch_claude`
     at pane_ops.py:333-339): `pm pr list`, `pm plan list`, `pm pr graph`.
   - Write actions guidance: pausing a watcher (would need to use
     `pm tui send ws`) or adding to `notes.txt` Watcher section
     (`pm notes` or direct file edit) require explicit human confirmation
     before running. Direct write commands like `pm pr start`/`pm pr done`
     are forbidden (same rule as `launch_claude`).

4. **Opening summary turn.**
   The prompt's first instruction is "Begin by reading the three watcher
   logs and producing a summary of activity since the last review,
   organized by watcher: discovered/filed/fixed/merged/stuck." After the
   summary, await user input.

5. **Conversational from there.**
   No special parsing — it's an ordinary interactive Claude session
   (no `--print`, hook events, or verdict polling). Same shape as
   `launch_claude` / `launch_discuss`.

## Implicit Requirements

- **Pane lifecycle reuse.** `launch_pane` (pane_ops.py:153) already
  dedups by role, so pressing `wr` when the review pane is open should
  refocus it rather than spawn a duplicate. The `z`-prefixed `fresh=True`
  flow (`app._consume_z()`) gives the user an escape hatch for restart.
- **Tolerate missing logs.** Bug-fix and improvement-fix watcher PRs
  (`pr-e3a711c`, `pr-d39a7fb`) are not yet merged. The prompt must use
  `tail -n 40 <log> 2>/dev/null || echo "(log not yet present)"`-style
  commands so the session works gracefully today and starts being useful
  the moment those watchers ship.
- **Path resolution.** Watcher logs live under the meta workdir's `pm/`
  directory (the same path watchers themselves write to via
  `meta_pm_root` injected through their prompts). Resolve it once via
  `ensure_meta_workdir()` and pass the absolute path into the prompt
  template. Falling back to the current project root's `pm/` is OK if
  the meta workdir cannot be ensured (matches the `launch_meta`
  fallback semantics).
- **No new `pm pr add` for this PR.** The session itself does not file
  bugs or improvements; it observes and explains. (`launch_claude` is
  already a precedent for read-mostly Claude panes.)
- **Bindings table updated.** Add the binding to the Textual `BINDINGS`
  list with `show=False` (since it's a `w`-prefix sub-key, not a
  top-level keybinding) — matches how `wf`/`ws` are not separately
  declared in BINDINGS but dispatched in `on_key`.
- **Help/discoverability.** Update the user-visible hint in the `w`
  prefix log message at app.py:205 so the new sub-key shows up:
  `(w=list f=focus s=start/stop r=review)`.

## Ambiguities (resolved)

- **Sub-key choice for the keybinding.** Could be `r` (review),
  `c` (chat), `v` (view). Resolved to `r` for "review" — matches the
  PR title ("Watcher review session") and doesn't conflict with the
  existing sub-keys `w`, `f`, `s`. (The top-level `r` binding is
  refresh; that's unaffected because we're inside the `w` prefix mode.)

- **What if the watcher logs path is just `pm/watchers/...` vs
  `<meta>/pm/watchers/...`?** The discovery prompt uses
  `<meta_pm_root>/watchers/<name>.log` where `meta_pm_root` is "pm"
  by default but is overridden when running in the meta workdir.
  Resolved: call `ensure_meta_workdir()` and use the resulting
  `<meta_workdir>/pm/watchers/<name>.log` as the absolute log path,
  matching what the watchers actually write.

- **Should the session also tail per-test transcripts?** The PR
  description says yes ("can also tail per-test transcripts"). Resolved:
  the prompt mentions the watcher transcript directory location
  (`auto_start.get_transcript_dir`) and tells Claude to `ls` /`tail` it
  on demand rather than reading every transcript up-front (would blow
  context). No code changes — Claude has shell access.

- **Should write-confirmation be enforced by code (e.g. wrapping `pm
  notes` behind a confirmation prompt)?** No — same model as
  `launch_claude`: it's *prompt-level* guidance. The human is sitting
  in the pane and approves any command Claude runs via the standard
  Claude Code permission UI. Resolved: prompt only; no harness changes.

## Edge Cases

- **Meta workdir doesn't exist.** `ensure_meta_workdir()` creates it on
  first call (per `launch_meta` precedent). The session will work even
  on a fresh project, just with empty logs.
- **Not in a tmux session.** `launch_pane` will fail naturally; no extra
  guard needed beyond the existing `app._session_name` check used by
  other launchers.
- **Multiple review panes across windows.** `launch_pane` dedups on the
  string `role`, so `"watcher-review"` keeps it singleton per TUI
  instance.
- **`z` prefix for fresh restart.** `app._consume_z()` is honoured so
  `zwr` reopens the pane fresh, dropping prior conversation history —
  matches the convention used by `launch_claude`.
- **Plan-regression watchers other than discovery aren't merged yet.**
  The session opens, reads what it can, and reports "(no entries yet)"
  for missing logs. It is still useful right now for inspecting
  discovery activity alone.

## Manual test plan

1. Start a TUI session with the watchers framework available.
2. Press `wr` — confirm a Claude pane opens labelled `watcher-review`.
3. Confirm the session opens with a summary turn covering all three
   watcher logs (treating missing logs gracefully).
4. Ask a follow-up: "why was the last bug deduped against another?".
   Confirm the session reads the discovery log to answer.
5. Ask the session to "add a note to the watcher section saying
   'prioritise auth-flow regressions'". Confirm it asks for human
   confirmation, then performs the edit (via `pm notes` or direct
   write to `notes.txt`).
6. After the next discovery watcher tick, verify the new note flows
   through `notes_for_prompt(root, "watcher")` into the watcher prompt.
