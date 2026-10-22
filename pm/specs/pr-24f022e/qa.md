# QA spec — pr-24f022e: popup-dispatched pm commands run the session's pm_core

## What changed (summary)

- `_run_picker_command` (prefix+P picker, direct route) and `_popup-cmd` (prefix+M
  runner) no longer spawn `python -m pm_core.wrapper` in the popup's cwd. Instead they
  spawn `python -c <bootstrap> <dispatcher_root> <session_tag> <args…>`. The bootstrap
  drops cwd from `sys.path`, imports the wrapper from the dispatcher's own pm_core, and
  calls the new `wrapper.main_for_session(tag)`.
- `main_for_session` resolves code only from the tmux session tag: override(tag), then
  pm_root(tag) (`<pm_root>/../pm_core`), then the dispatcher's own code
  (`chosen_via=dispatcher`). It never walks the cwd. It logs
  `wrapper: argv0=… selected_root=… chosen_via=… session_tag=…` to the pm debug log.
- `wrapper.main()` (all other callers) is unchanged apart from a helper extraction.
  Commands typed in a shell inside a workdir still use `cwd_walk`.
- The child's cwd and `PM_PROJECT` are unchanged. The `tui:` route is unchanged.

## Setup (cross-cutting)

S1. Install pm from the PR branch (`./install.sh --local`, or the venv steps in
    `tui-manual-test.md`). Make sure `PYTHONPATH` does not shadow it, unless a story
    says otherwise.
S2. **pm-source-tracking test project.** Create a throwaway git repo that contains a
    copy of this branch's `pm_core/` at its top level, commit it, and run
    `pm init --backend local --no-import`. Add one or two PRs. The session's pm_root is
    then `<proj>/pm`, and `<proj>/pm_core/cli` exists, so the session's code resolves
    via `chosen_via=pm_root`.
S3. Configure fake-claude for the session (`pm fake-claude config set '{"_all": {}}'`),
    so PR windows open without real Claude.
S4. Start the session (`pm session`). Attach a client through a separate recorder
    session (`tmux-screen-recording.md`) so `display-popup` has a client to draw on.
S5. **PR workdir with unmerged code.** Run `pr start <pr>` (TUI or CLI) to create the
    PR's workdir clone and window. In that workdir, edit and commit a visible change to
    its `pm_core`: for example, make `pm which` print a `WORKDIR-CODE` marker, and/or
    make `pr merge` refuse with `DECOY MERGE GATE`. That workdir's pm_core now differs
    from the session's.
S6. Popups are opened with the session's real prefix+P / prefix+M key bindings, sent
    through the attached client. The recorder attach captures what appears on screen.
    The pm debug log lives under `~/.pm/debug/`.

## Requirements

R1. **Runner uses session code from a PR workdir window.**
    Given the session from S2–S5 and the PR window focused (pane cwd = PR workdir),
    When the user opens the prefix+M runner and runs `which`,
    Then the popup prints the session project's `pm_core` path, not the workdir's, with
    no `WORKDIR-CODE` marker. The debug log has a line with `chosen_via=pm_root`,
    `selected_root=<session project root>` and `session_tag=<session tag>`.

R2. **Picker action uses session code (original bug).**
    Given the same PR window, where the workdir's `pr merge` has a decoy gate that
    refuses,
    When the user opens the prefix+P picker and chooses **merge** for that PR,
    Then the merge proceeds as it would from the TUI. The decoy refusal does not appear.
    The debug log shows the child with `chosen_via=pm_root` and the session's root (not
    `chosen_via=cwd_walk` with the workdir's wrapper as argv0).

R3. **Shell invocation in the workdir is unchanged.**
    Given the PR window,
    When the user types `pm which` in that window's shell,
    Then it prints the workdir's `pm_core` (with the marker) and the log shows
    `chosen_via=cwd_walk`.

R4. **State still comes from the session project.**
    Given the PR window,
    When the user runs `pr list` (or `pr note add …`) in the prefix+M runner,
    Then it lists or modifies the session's `pm/project.yaml` (the session's PR ids),
    not any project.yaml in the workdir.

R5. **Picker other direct actions** (start / review / signoff, including z-modified
    `--fresh` variants) also run session code. **`tui:` actions** (edit, qa, review-loop
    loops) are still routed to the TUI command bar, which acts on them.

R6. **Runner `tui:` re-route unchanged.** Typing `review-loop …` or `pr qa …` in the
    prefix+M runner still hands the command to the TUI instead of running it directly.

## Edge cases

E1. **Ordinary (non-pm-source) project.** Given a session for a plain project with
    no `pm_core` beside `pm/`, and a window cd'd into some directory that contains a pm
    source checkout, When the user runs `which` via prefix+M, Then it prints the
    installed/dispatcher pm_core (`chosen_via=dispatcher`), never the cwd's checkout.
    `pr list` in the runner still shows the session's PRs.
E2. **Session override active** (as `pm meta` sets
    `~/.pm/sessions/<tag>/override`). Given an override for the session's tag pointing
    at another pm checkout, When prefix+M runs `which`, Then the override's pm_core
    runs (`chosen_via=override`). An override keyed to the *workdir's* tag (cwd-derived)
    is ignored by popup children.
E3. **PYTHONPATH shadow.** Given `PYTHONPATH` set to a different pm_core (e.g. master
    at `/opt/pm-src`, as review containers do), When prefix+M runs `which`, Then the
    session's pm_core still wins (`chosen_via=pm_root`, selected root first on path).
E4. **Grouped session** (second attached client, session name `pm-<tag>~2`). Popups
    from that client resolve the same tag and session code.
E5. **Runner errors.** An unknown command or a failing command (e.g. `pr show
    pr-nonexistent`) shows the error and keeps the popup open until dismissed. An
    unterminated quote shows `Invalid command syntax`. Esc / Ctrl+C during a running
    command closes the popup at once. An empty input closes the popup.
E6. **Deleted workdir / pm_root missing.** If the PR workdir the window was in has
    been deleted, or the session's pm_root file is missing, the popup child still runs
    (dispatcher code, never crashes on cwd) and prints a sensible result or error.
E7. **Concurrency.** Two clients (grouped sessions), each focused on a different PR
    workdir whose pm_core differs, open runners/pickers at the same time and run
    commands that write project.yaml (e.g. `pr note add`). Both children run session
    code, both writes persist, and the debug log has a session-code resolution line for
    each child. A shell `pm which` running at the same moment in a workdir still
    resolves via cwd_walk.

## Pass / Fail criteria

- PASS: every popup-dispatched child (picker direct route, prefix+M runner) runs the
  session's pm_core, shown both by output (`which` path, no decoy markers, merge
  succeeds) and by the debug log (`chosen_via=pm_root|override|dispatcher`, never
  `cwd_walk`, with `session_tag=` set). Shell invocations in workdirs still use
  `cwd_walk`. `tui:` routing, error display, abort keys and PM_PROJECT state handling
  behave as before. The reproduction tests in `tests/test_popup_session_code.py`
  pass on the branch and fail with master's `session.py`/`wrapper.py`.
- FAIL: any decoy/workdir marker appears in popup output. Or the log shows
  `chosen_via=cwd_walk` for a popup child, or the child reads the wrong project.yaml.
  Or a shell invocation in a workdir stops using cwd_walk, or popups crash (traceback,
  `main_for_session` missing, exit before output).

## Ambiguities (resolved)

- *No pm_core next to pm_root (ordinary repo):* the child runs the dispatcher's code
  (`chosen_via=dispatcher`), per the impl spec. It must never cwd_walk.
- *Override precedence:* an override for the **session** tag beats pm_root, matching
  `main()`'s order. Cwd-keyed overrides are ignored for popup children.
- *"Cwd-dependent commands behave the same":* verified indirectly. The child's cwd is
  not changed (no `cwd=` passed), and state keeps coming from `PM_PROJECT`. No pm
  command prints its cwd directly, so scenarios check that runner commands behave the
  same apart from which code runs.
- *How to open popups headlessly:* through the session's own key bindings, sent to an
  attached client (recorder attach). If key injection to the client isn't possible,
  running the binding's popup body through `tmux display-popup` on that client is an
  acceptable equivalent. It is the same command the binding runs.
