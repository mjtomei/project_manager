# QA Spec: pr-30888b1, fold plan breakdown into plan add

## What changed (user-facing)

- `pm plan add <name>` (TUI: `p` then `a`) now runs one session that develops
  the plan **and** breaks it into PRs. The prompt asks the session to:
  - discuss the breakdown with the user;
  - use the `### PR:` format, with entries separated by `---`;
  - start from the source document's PR list when NAME points to a document that has one;
  - read a bounded "Existing PRs in this project" listing;
  - follow the guidelines and the manual-testing guidance;
  - close by pointing at `pm plan load <id>` (key `l`), then optionally `pm plan review <id>` (key `c`).
- `pm plan breakdown` has been removed and now fails with Click's `No such command 'breakdown'`.
  This also removes its `--prs` and `--fresh` options.
- TUI plans view: `w` no longer means breakdown.
  - It is gone from the footer and from the `?` help screen.
  - Pressing `w` now falls through to the app-wide `w …` watcher prefix.
- Recovery when a plan has no `## PRs` section: `pm plan load` now says
  `Run 'pm plan review <id>' (key c in the plans view) to propose a ## PRs section, or add one to the plan file directly`.
  The pre-load `pm plan review` prompt gains a paragraph telling the session
  to propose a breakdown first when the plan has none.
- Help and docs:
  - `pm help` COMMANDS, `pm getting-started`, `pm plan --help` and `pm plan add --help` no longer mention breakdown.
  - The plans-view key list reads `a=add c=review l=load e=edit …`.
- Guide:
  - The `has_plan_draft` step label is now "Finish plan with PR breakdown". The TUI guide status bar shows it.
  - The `pm guide` setup prompt describes the flow `a` → `c` → `l`, says `a` writes the plan and its `## PRs`, and has a section "If the plan has no PRs yet" that points at `c`.
- The background plan-add check (`REVIEW_PROMPTS["plan-add"]`) now requires
  both a plan body and a `## PRs` section. (It is not observable today; see
  Ambiguity A2.)

## 1. Requirements

**R1: Plan add prompt carries the breakdown.**
- Given an initialized project with a few existing PRs.
- When the user runs `pm plan add "Dark mode"`.
- Then:
  - the command prints `Created plan plan-…: Dark mode` and the plan-file path;
  - `pm plan list` shows the new plan as `[draft]`;
  - the plan file contains the `# Dark mode` template;
  - the prompt handed to the session states the goal as developing the plan *and* breaking it into PRs, written to that plan file;
  - the prompt contains the `### PR:` / description / tests / files / depends_on format and the `---` separator;
  - the prompt lists the existing PRs (id, title, status, depends-on);
  - the prompt has the Guidelines list, including the manual-testing paragraph;
  - the prompt ends by telling the user to run `pm plan load <id>` (key `l`), optionally `pm plan review <id>` (key `c`), and that it is safe to close the pane;
  - no part of the prompt mentions `pm plan breakdown` or the `w` key.

**R2: Fresh project.**
- Given an initialized project with no PRs.
- When the user runs `pm plan add`.
- Then the prompt has no "Existing PRs in this project" block. "Separate PR entries with --- lines." is followed by a blank line and then "Guidelines:", with no dangling header.

**R3: Source document.**
- Given a design doc in the repo that already proposes PRs.
- When the user runs `pm plan add docs/design.md`.
- Then the prompt tells the session to read that file and says "If the source document already proposes PRs, start from that list."

**R4: No Claude installed.**
- Given no `claude` on PATH.
- When the user runs `pm plan add X`.
- Then the full prompt from R1 is printed under "Claude CLI not found. Copy-paste this prompt into Claude Code:", the command exits 0, and the plan is still registered.

**R5: Load after plan add.**
- Given the plan add session has written a plan body plus a `## PRs` section (3 PRs, one depending on another by title).
- When the user runs `pm plan load <id>`, or presses `l` on the plan in the TUI.
- Then:
  - it reports "Found 3 PRs", "Created …" lines and "Loaded 3 PRs from plan <id>";
  - `pm pr list` and `pm pr graph` show the PRs under that plan with the dependency resolved;
  - the TUI tech tree shows them.
- A second load reports every PR as "Skipped … (already exists)".

**R6: Breakdown command removed.**
- Given any initialized project.
- When the user runs `pm plan breakdown`, `pm plan breakdown <id>`, or `pm plan breakdown --prs "a,b"`.
- Then each prints `Error: No such command 'breakdown'` with a non-zero exit code, and no session is launched and no state is changed.

**R7: Help surfaces.**
- When the user reads `pm help`, `pm getting-started`, `pm plan --help` or `pm plan add --help`.
- Then:
  - no breakdown command or `w=breakdown` key appears;
  - `plan add` is described as adding a plan and breaking it into PRs;
  - the plan key list reads `a=add  c=review  l=load …`.
- In an uninitialized directory, `pm help` shows the getting-started text with the same content.

**R8: TUI plans view.**
- Given the TUI is open on a project whose setup is complete.
- When the user opens the plans view (`p`).
- Then the footer shows `a=add c=review l=load e=edit D=deps p=back`, with no `w=breakdown`.
- `?` in the plans view lists Plan Actions a / e / c / l, with no "Break plan into PRs" row.

**R9: `w` in the plans view.**
- Given the plans view with a plan selected.
- When the user presses `w`.
- Then:
  - no breakdown pane or window is opened, and no `pm plan breakdown` runs;
  - the log line shows the watcher prefix hint `w … (w=list f=focus s=start/stop r=review)`;
  - Escape, a non-matching key, or 2 s of inactivity cancels it;
  - the plans view stays usable.

**R10: TUI add.**
- Given the plans view.
- When the user presses `a`, enters a title, and confirms.
- Then:
  - a per-plan tmux window named after the plan id opens, running `pm plan add <title>` (with fake-claude, the pane shows the fake session and stays open);
  - the new plan appears in the plans list;
  - later `Enter` (view), `e` (edit) and `c` (review) on that plan open panes in the **same** per-plan window.

**R11: Load with no PRs.**
- Given a plan whose file has a body but no `## PRs` section, for example because the plan add session was closed early.
- When the user runs `pm plan load <id>`, or presses `l` in the TUI.
- Then:
  - the command fails (non-zero exit; in the TUI, an error in the log);
  - the error names `pm plan review <id>` (key `c`) and editing the plan file directly, and does not suggest `pm plan add` or `pm plan breakdown`;
  - no PRs are created and no new plan entry appears.

**R12: Pre-load review covers a missing breakdown.**
- Given the same plan, with no PRs loaded.
- When the user runs `pm plan review <id>`, or presses `c`.
- Then the review prompt says that if the plan file has no `## PRs` section yet, the session should propose a breakdown, agree it with the user, write it in the FORMAT shown, and then run the checks.

**R13: Post-load review unchanged.**
- Given a plan whose PRs are already loaded.
- When the user runs `pm plan review <id>`.
- Then the progress-review prompt is used (assess progress, COVERAGE / CONSISTENCY / ITERATION) and the "no `## PRs` yet" paragraph does not appear.

**R14: Guide in a plan-draft state.**
- Given a project with one plan, no `## PRs` in its file and no PRs loaded.
- When the user opens the TUI.
- Then:
  - it starts in guide mode;
  - the status bar reads `pm Guide    Finish plan with PR breakdown`;
  - the guide progress shows Plan file done, with PRs loaded next/pending.
- When the user runs `pm guide` with no Claude on PATH:
  - the printed setup prompt says `a` develops the plan **and** writes `## PRs`;
  - it has the "If the plan has no PRs yet" section pointing at `c`;
  - it gives the plans-view flow as `a` → `c` → `l`;
  - it does not mention `w`, `pm plan breakdown` or "Break plan into PRs".

**R15: Guide auto-load.**
- Given the plan file has gained a `## PRs` section and no PRs are loaded.
- When the user runs `pm guide`.
- Then it prints "Loading PRs from plan file...", loads the PRs, and moves on to the next step.
- The TUI guide refresh no longer shows "Finish plan with PR breakdown".

**R16: Bounded listing.**
- Given a project with about 300 existing PRs, some with very long titles.
- When the user runs `pm plan add "New plan"`.
- Then:
  - the existing-PR listing shows at most 40 lines followed by `... (+N more; run \`pm pr list\` to see all PRs)`;
  - the session launches normally (no "Argument list too long");
  - the prompt handed to Claude stays within one argv entry, or is delivered by the launcher's file-backed path.

## 2. Setup

- Install pm from this branch. Follow `pm/qa/instructions/tui-manual-test.md`:
  a venv with `pip install -e .`, then `export PYTHONPATH=<clone>`, and check `pm which`.
- Throwaway project: `git init` a temp dir, then `pm init --backend local --no-import`, then `pm pr add …` for the existing PRs.
- **Claude stand-ins** (real Claude is not available to QA):
  - **Plain-shell stories that need to see the prompt:** put an executable `claude` early on PATH that records its last argv entry to a file (and copies that file if the argument is a path), then exits 0. Run pm as `env PATH=<standbin>:$PATH pm …`.
  - **"Claude not installed" stories:** run with a PATH that has no `claude`. The printed copy-paste prompt is then the visible surface.
  - **TUI / pane flows:** tmux panes do **not** inherit a custom PATH. Use the bundled fake instead:
    `pm fake-claude config set --tag <session-tag> '{"_all": {}}'`.
    Plan / guide sessions are no-verdict, so the fake prints output and stays open.
- **Standing in for the plan session's output:** the fake does not write files.
  To get "the session wrote the plan and its PRs", write the plan file in the
  format the prompt asks for: a body, then `## PRs`, then `### PR:` entries
  with description / tests / files / depends_on, separated by `---`.
  This is what Claude would have produced.
- Hand-editing `pm/project.yaml` is bootstrap-only. It is not needed here.

## 3. Edge Cases

**E1: Concurrent plan adds with different names, plus a load.**
- Given a project whose TUI is open.
- When these run at the same moment:
  - actor A adds plan "Alpha" via the TUI;
  - actor B runs `pm plan add "Beta"` from a shell;
  - actor C runs `pm plan load` for an already broken-down plan "Gamma".
- Then:
  - `pm plan list` shows Alpha, Beta and Gamma once each, with distinct ids and files;
  - Gamma's PRs are loaded exactly once;
  - the TUI plans view shows all three after refresh;
  - Alpha and Beta have separate per-plan windows;
  - no `project.yaml` write is lost.

**E2: The same plan loaded twice at once.**
- When TUI `l` and CLI `pm plan load <id>` run concurrently on one plan.
- Then each PR exists once (ids are deterministic and the locked append dedups), and the dependencies are intact.

**E3: Same-name concurrent plan add (pre-existing).**
- When two or three `pm plan add "Same"` run in parallel.
- Then today they register duplicate entries with one id and a shared plan file.
- This was verified during planning and filed as pr-2b9d002. Record the result; it is not a regression from this PR.

**E4: Leftover breakdown review file.**
- Given an upgraded project that still has `pm/reviews/plan-breakdown-<ts>.txt` from an older pm.
- When the user runs `pm plan fixes` and `pm plan fix --review <that file>`.
- Then it is listed with its fix command, and the fix launches a fix session (the step name is read from the file) instead of erroring on the removed step.

**E5: Breakdown typed into the TUI command bar.**
- When the user types `plan breakdown` in the TUI command bar (`/`).
- Then an error is shown in the log and the TUI keeps running.

**E6: Plan add closed before writing PRs, then re-review.**
- After R11/R12, the user writes PRs through the review session (stand-in: write the `## PRs` section), then presses `l`.
- Then the PRs load into the **same** plan id, and no second plan entry is created.

**E7: Malformed PR fields (pre-existing; tracked by pr-5cee3d5).**
- Given a hand-edited `depends_on: 7`.
- Then `plan add` crashes with `TypeError: can only join an iterable` while building the existing-PR listing, after the plan entry is registered. `pm pr list` / `pm pr graph` crash the same way on master.
- This is out of scope for pass/fail. pr-5cee3d5 owns the `graph.deps_of` fix and must port it to `plan_add._existing_line`.

## 4. Pass/Fail Criteria

**Pass:**
- Every Then in R1–R16 and E1, E2, E4, E5, E6 is observed on the user surface: command output, the recorded or printed prompt, `pm plan list` / `pm pr list` / `pm pr graph`, TUI renders, tmux windows and panes, and the TUI log line.
- No live user surface mentions `pm plan breakdown`, `w=breakdown` or "Break plan into PRs".

**Fail:**
- any surface still offers breakdown;
- `w` in the plans view launches anything plan-related;
- the plan add prompt lacks the breakdown instructions, the format, or the load-first closing;
- the existing-PR listing is unbounded, or the launch fails;
- `plan load` on a PR-less plan suggests `plan add` or `plan breakdown`;
- the pre-load review prompt lacks the propose-breakdown paragraph;
- the guide still shows a breakdown step;
- a concurrent different-name add or load loses or duplicates entries.

**Not failures for this PR:**
- E3 (pr-2b9d002) and E7 (pr-5cee3d5);
- the background check never reporting (A2, pr-e2cd753);
- `v=view` in `pm getting-started` with no `v` key (pre-existing; pr-fa9f172 rewords it).

## 5. Ambiguities (all resolved)

**A1: Which Claude?**
Real Claude is unavailable. The prompt content is verified through the recording stand-in or the "Claude CLI not found" printout. TUI flows use fake-claude. Model behavior (whether Claude actually produces a good breakdown) is out of scope; the instructions it receives are in scope.

**A2: Background plan-add check.**
`review_step` runs `claude -p` in a daemon thread that dies when `pm plan add` exits. No `pm/reviews/plan-add-*` file and no PASS / NEEDS_FIX pane ever appears. This was reproduced while planning, is the same on master, and is filed as pr-e2cd753. Scenarios must not assert on the check's verdict. The working recovery path is `plan review` (R12).

**A3: What should `w` do in the plans view now?**
It falls through to the app-wide `w` watcher prefix, the same as in the tree view (impl spec, Implicit Requirements). Pass means no breakdown action happens and the TUI stays responsive. The watcher hint appearing is expected.

**A4: `--prs` seed option.**
It was dropped and was not moved to `plan add`. A file-path NAME together with the "start from that list" sentence replaces it (impl spec Ambiguity 1). `pm plan add --prs` should fail as an unknown option.

**A5: Cross-PR conflicts** (pr-6c0ee2d, pr-5cee3d5, pr-3526677, pr-fa9f172, pr-fe4ca5d).
These are handled by notes on those PRs and do not affect what is tested on this branch.

No **[UNRESOLVED]** items.
