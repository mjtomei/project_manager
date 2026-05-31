# Spec — PR pr-a6ef6be: Session-launching CLI commands + project.yaml review registry

PR 1 of plan `plans/plan-litreview.md` (plan-3119574). Ships the registry,
path resolution, methodology-context loader, the two session-launching CLI
commands (`pm review <target>`, `pm plan literature-review <plan>`), the
`pm review ui` route, and the TUI plans-pane `r` keybinding + active-review
badge. Independent of the walker UI (PRs 2–5).

---

## 1. Requirements (grounded in the codebase)

### 1.1 `pm_core/review/registry.py` — `project.yaml` reviews list

A new top-level `reviews:` key in `project.yaml`, sibling to `plans:`/`prs:`.
Entry shape (per plan §"`pm/project.yaml` schema addition"):

```yaml
reviews:
  - id: <kebab-slug>
    target: <path-or-topic-string>
    target-type: plan | file | topic
    status: active | archived
```

APIs (all take the pm `root: Path` = `store.find_project_root()` result, i.e.
the `pm/` dir):

- `get_review(data: dict, review_id: str) -> dict | None` — mirrors
  `store.get_plan(data, id)` (read from already-loaded data, no I/O).
- `create_review(root, review_id, target, target_type) -> dict` — append a new
  entry with `status: "active"` via `store.locked_update`; returns the entry.
- `set_status(root, review_id, status) -> None` — mutate one entry's `status`
  via `store.locked_update`.
- `list_active(root) -> list[dict]` — load + filter `status == "active"`.

Round-trip preservation: all writes go through `store.locked_update`
(`pm_core/store.py:243`), which load-modifies-saves the whole dict, so
`project`, `plans`, `prs`, and any other top-level keys are preserved
untouched. `store.load` validates only `prs`/`plans`, so an unknown `reviews:`
key passes through cleanly. **Requirement met by reusing `locked_update`** — do
not hand-roll YAML writes.

Use `make_review_entry(...)` helper (parallel to `store.make_plan_entry`,
`store.py:177`) to centralize the dict shape. Key name choice: store
`target-type` and keep `status` as plain strings. (project.yaml uses
hyphenated keys elsewhere only in plan-litreview's schema; existing entries use
underscores like `depends_on`. We follow the plan's literal `target-type`
spelling since the walker-UI PRs read it back.)

### 1.2 `pm_core/review/paths.py` — review-id → directory + file paths

Constants and functions resolve everything under
`<root>/docs/adversarial-review/` (root is the `pm/` dir, so this is
`pm/docs/adversarial-review/`, matching the plan's `pm/docs/...` paths).

- `REVIEWS_SUBDIR = "docs/adversarial-review/reviews"` (relative to root).
- `reviews_root(root) -> Path` → `root / REVIEWS_SUBDIR`.
- `dir_for(root, review_id, *, create=True) -> Path` →
  `reviews_root(root) / review_id`; `mkdir(parents=True, exist_ok=True)` when
  `create` (the plan: "Creates the per-review directory on first access").
- `state_path(root, id)` → `<dir>/STATE.md`
- `focus_path(root, id)` → `<dir>/UI_FOCUS.md`
- `notes_path(root, id)` → `<dir>/NOTES.md`
- `cycle_paths(root, id, n) -> dict` → the three per-cycle files:
  `{"review": REVIEW_CYCLE_<n>.md, "audit": CITATION_AUDIT_CYCLE_<n>.md,
  "response": REVIEW_RESPONSE_CYCLE_<n>.md}` under `<dir>`.

Methodology file constants (top-level, shared across reviews) also live here so
`context.py` and future PRs share them:
`METHODOLOGY_FILE = "docs/adversarial-review/METHODOLOGY.md"`,
`CITATION_USE_AUDIT_FILE = "docs/adversarial-review/CITATION_USE_AUDIT.md"`,
`CITATION_CRAWL_FILE = "docs/adversarial-review/CITATION_CRAWL.md"`, plus a
`methodology_paths(root) -> list[Path]` helper.

### 1.3 `pm_core/review/context.py` — methodology-context loader

`build_context(root, review_id, target, target_type) -> str` returns the prompt
string handed to the launched Claude session. Per plan §`context.py`, it
concatenates, in order:

1. A framing instruction (verbatim intent from the plan): "you are running the
   augmented adversarial-review cycle on the target below; produce
   `REVIEW_CYCLE_N.md`, then the audit loop, then `REVIEW_RESPONSE_CYCLE_N.md`,
   per the methodology files. State lives in your review's directory at
   `<review-dir>/`." `<review-dir>` is the absolute `dir_for(root, id)`.
2. `METHODOLOGY.md`, `CITATION_USE_AUDIT.md`, `CITATION_CRAWL.md` — each read
   from `methodology_paths(root)` **if present**, each under a labeled header
   (e.g. `## METHODOLOGY.md`). Missing files are skipped with a one-line note
   rather than erroring (these three files do not all exist in the repo yet —
   only `CITATION_CRAWL.md` is present today; the others are authored
   elsewhere). This keeps the command usable before the docs land and lets the
   "concatenates expected files" test drive it with fixtures.
3. The review's `STATE.md` if it exists (resume case), under its own header.
4. A target preamble: the resolved `target` plus `target-type`, and for
   file/plan targets the file contents (or a pointer to read it) so the session
   knows what artifact it reviews. Per PR note (2026-05-21): `_target_preamble`
   stats the file first and only inlines when under `_MAX_INLINE_BYTES`
   (80 KB) — larger targets get a "read it yourself" pointer so the assembled
   prompt stays under the argv/shell limit. `UnicodeDecodeError`/`OSError` on
   read (e.g. a PDF/binary target) degrades to a pointer rather than crashing
   `run_review`.

Factor the file list so the test can assert "concatenates expected files" by
checking each present fixture's content appears in the output and missing ones
are noted.

**Per PR note (note-0970084, 2026-05-30): workflows-aware parallelization.**
`build_context` unconditionally appends a `## Parallel workflows` clause
(constant `_PARALLEL_WORKFLOWS_CLAUSE`) before the `## Target` section. The
clause tells the session to use the workflow skill on four phases and names
the per-phase unit of work: audit (per citation per pass), review (per prompt
block — substance/structure/accessibility/prose), response (per proposed
change). The apply phase runs sequentially. The skill handles fan-out
and reduction; the clause doesn't re-specify its mechanics. Companion
methodology-doc edits (METHODOLOGY.md, CITATION_USE_AUDIT.md) land whenever
those docs are authored — not blocking on this PR.

### 1.4 `pm_core/review/cli.py` — `pm review <target>` + `pm review ui` + shared launch

Registered on the top-level `cli` group following the existing submodule
pattern (`pm_core/cli/__init__.py:684` imports each submodule at the bottom to
trigger `@cli`-decorator registration). Add `from pm_core.review import cli as
review_cli` (aliased to avoid clashing with `pm_core.cli`) to that import line.

`pm review` is a single Click **command** taking one `target` argument plus
`--port` (Click groups can't cleanly mix an arbitrary positional target with a
named subcommand; a command with explicit "ui" dispatch is simpler and matches
the plan's "`ui` is the only other dispatch — anything else is a target"):

```
@cli.command("review")
@click.argument("target")
@click.option("--port", default=8765, type=int)
def review(target, port):
    if target == "ui":
        _run_ui_server(port); return
    run_review(target, root=store.find_project_root())
```

`_run_ui_server(port)` — thin route to the walker server (PR 3). In this PR it
attempts `from pm_core.review.ui import server` and runs it, else prints
"walker UI ships in a later PR" and exits cleanly. The PR-1 requirement is only
that `ui` **routes here** and is never treated as a topic target; the test
mocks this function and asserts it is called for `target == "ui"` and *not*
called (and `run_review` *is* called) for any other target.

`run_review(target, *, root)` — the core, unit-testable flow:

1. **Resolve target-type + artifact id** (§1.6):
   - target is an existing plan id in `data["plans"]` → `target-type=plan`, id
     = plan-file stem.
   - else `Path(target)` exists (relative to repo root / cwd) → `file`, id =
     slugified basename.
   - else → `topic`, id = slugified topic string.
2. **Resume-or-create** against the registry (§1.7).
3. **Build context** via `context.build_context`.
4. **Launch session pane** via the shared `launch_review_session(...)` with
   `target_window=None` (own pane) and `role="literature-review"`.

Shared launcher `launch_review_session(prompt, *, cwd, role="literature-review",
target_window=None, session=None)`:

- Resolve `session` via `tmux.get_session_name()` when not passed.
- If in tmux and session resolves: build the claude command string with
  `claude_launcher.build_claude_shell_cmd(prompt=prompt, cwd=cwd)`, split a new
  pane with `tmux.split_pane(session, direction, cmd, window=target_window)`
  (direction via `pane_layout.preferred_split_direction` when available, else
  `"v"`), register it with `pane_registry.register_pane(session, window,
  pane_id, role, cmd)`, and `tmux.select_pane(pane_id)`.
- If not in tmux: fall back to foreground `claude_launcher.launch_claude(prompt,
  session_key=f"review:{id}", pm_root=root)` so the command still works from a
  plain terminal. (Mirrors how every existing plan command degrades when
  `claude` is present but tmux is not.)

This single helper is the "Same code path, different pane parent" the plan
calls for — `pm review` passes `target_window=None`; `pm plan literature-review`
passes the plan's window id.

### 1.5 `pm_core/cli/plan.py` — `pm plan literature-review <plan>`

New `@plan.command("literature-review")` (Click normalizes the function name;
register the command name explicitly as `"literature-review"`). Follows the
shape of `plan_review` (`plan.py:259`):

1. `plan_id = _auto_select_plan(data, plan_id)`; `plan_entry =
   _require_plan(data, plan_id)`; verify `plan_path` exists.
2. artifact id = plan-file stem (`Path(plan_entry["file"]).stem`).
3. resume-or-create against the registry with `target=plan_entry["file"]`,
   `target_type="plan"`.
4. `context.build_context(...)`.
5. Resolve the plan's tmux window by name using the TUI's convention
   (`pane_ops._plans_window_name(plan_id)` → `tmux.find_window_by_name(session,
   name)`), then `launch_review_session(..., target_window=win["id"],
   role="literature-review")`. If the window isn't found (command run outside an
   active TUI session), fall back to `target_window=None` (own pane / foreground).

To avoid a heavy TUI import in the CLI path, expose the window-name convention
as a small shared constant/helper rather than importing the whole
`pane_ops`/textual stack — e.g. read `pane_ops._plans_window_name` lazily inside
the function, or duplicate the one-line `plan_id or fallback` rule in
`review/cli.py`. (Plan window name today is just `plan_id`; keep that in one
place.)

### 1.6 Artifact-id derivation

Per task + plan §"Project registration":

- **file** target → `store.slugify(Path(target).name)` (full basename,
  *including* extension; the plan deliberately contrasts "file basename
  slugified" with "plan filename stem"). e.g. `notes.md` → `notes-md`.
- **plan** target → `Path(plan_file).stem` (no extension). e.g.
  `plan-regression.md` → `plan-regression`. (Slugify defensively too.)
- **topic** target → `store.slugify(topic)`. e.g. `"Sycophancy framing"` →
  `sycophancy-framing`.

Implement as `derive_artifact_id(target, target_type) -> str` in `review/cli.py`
(or a small `ids.py`) so the test can exercise all three branches directly.

### 1.7 Resume vs create vs archived-warn

Per plan §"CLI behavior on existing vs new reviews":

- registry hit + `status == "active"` → **resume**: reuse the entry + its
  directory; `build_context` includes the existing `STATE.md`; launch a new
  pane against the directory. (No project.yaml mutation.)
- registry hit + `status == "archived"` → **warn**: print a message telling the
  user to unarchive (e.g. `pm review unarchive <id>` — out of scope to fully
  implement, but the message names the action) or pick a new id; **do not
  launch**. Return without creating a pane.
- registry miss → **create**: `registry.create_review(...)`, `paths.dir_for(...,
  create=True)`, write an initial `STATE.md` (no cycles yet) via a minimal
  writer, then launch.

The initial `STATE.md` content: the PR-2 `md_writer.update_state` is the
canonical writer but PR 2 is independent and may not have landed. To stay
self-contained, PR 1 writes a minimal initial state inline (e.g.
`current-cycle: 0`, `current-phase: not-started`, `mode: human-reviewed`,
`last-transition: <utc>`), matching the `STATE.md` YAML shape in the plan. A
follow-up can swap in `md_writer.update_state` once available. Keep the inline
writer tiny and local.

### 1.8 `pm_core/tui/plans_pane.py` — `r` keybinding + active-review badge

- Add `"r": "literature-review"` to `PlansPane._KEY_ACTIONS`
  (`plans_pane.py:148`) and a footer hint (`r`=review). The comment there says
  "keep in sync with on_plan_action in app.py" → the handler is
  `pane_ops.handle_plan_action` (`pane_ops.py:613`), which gets a new
  `elif action == "literature-review"` branch that invokes
  `pm plan literature-review <plan>` (see §1.9).
- **Active-review badge**: `update_plans` already receives per-plan dicts. The
  app builds those dicts (in `app.py`/`pane_ops`); add an
  `active_review: bool` field derived from `registry.list_active(root)` keyed by
  the plan's id (a plan has an active review when an active entry has
  `target-type == "plan"` and its artifact id == the plan's stem, or
  `target` == the plan id/file). `render()` appends a small badge (e.g. ` ✦`
  or ` [review]`) to the plan header when `plan.get("active_review")`.

### 1.9 TUI dispatch for the `r` action

In `pane_ops.handle_plan_action` add:

```python
elif action == "literature-review":
    if plan_id:
        _launch_in_plans_window(app, plan_id,
            f"pm plan literature-review {plan_id}", "literature-review")
```

`_launch_in_plans_window` (`pane_ops.py:554`) already creates/【finds the
per-plan window and registers the pane with the given role — so the pane lands
in the plan's window with role `literature-review`. The `pm plan
literature-review` process then runs claude in that pane (foreground), exactly
like `pm plan review`.

**Reconciling the two launch paths.** There are two ways `pm plan
literature-review` reaches a pane:

- From the **TUI** `r` key: the TUI's `_launch_in_plans_window` creates the
  pane in the plan window and runs the command there; the command sees it is
  already in the plan window and launches claude **foreground** (its
  `launch_review_session` finds the current pane's window == plan window, or
  simply runs foreground claude). This is the same model as `pm plan review`.
- From a **plain terminal** (`pm plan literature-review <id>` typed directly):
  the command resolves the plan window and splits a pane there itself.

To keep this coherent and testable, `launch_review_session` is the single seam:
when invoked and *already inside* the target pane context (TUI case) it runs
claude foreground; when invoked standalone it splits/targets a window. The unit
test for "pane-launch invokes tmux with the expected role" mocks tmux and
asserts `register_pane`/`split_pane` is called with `role="literature-review"`
in the standalone path. See Ambiguity A1 for the resolution rationale.

### 1.10 Tests (`tests/review/`)

Co-locate with existing `tests/review/test_md_parser.py` etc. New files:
`test_registry.py`, `test_paths.py`, `test_context.py`, `test_review_cli.py`,
`test_plan_literature_review.py`, `test_plans_pane_keybinding.py`. Fixtures
under `tests/review/fixtures/` (registry YAML states; methodology doc stubs).

Coverage required by the task:

1. Registry round-trip preserves other yaml keys (`project`/`plans`/`prs`
   survive a `create_review` / `set_status`).
2. Resume vs create vs archived-warn against fixture registry states (active →
   no new entry + launch called; missing → entry created + dir + STATE.md +
   launch; archived → warning + no launch).
3. Artifact-id derivation across file/plan/topic targets.
4. Methodology-context loader concatenates expected files (present fixtures
   appear; missing noted; STATE.md included on resume).
5. `pm review ui` routes to `_run_ui_server` (mocked) and is **not** treated as
   a topic; any other target calls `run_review` and not `_run_ui_server`.
6. Plans-pane keybinding: `r` is in `_KEY_ACTIONS` mapping to
   `"literature-review"`; `handle_plan_action` dispatches it to
   `_launch_in_plans_window` with role `literature-review` (mock the launcher).
7. Pane-launch invokes tmux with the expected role: `launch_review_session`
   (standalone path, tmux mocked) calls `split_pane` + `register_pane` with
   `role="literature-review"`.

Use `tmp_path` as the pm root, write a minimal `project.yaml` via `store.save`
or `store.init_project`, and monkeypatch `tmux`/`claude_launcher` so no real
panes or claude processes spawn (the task flags pane/TUI behavior as
human-guided; units mock the boundary).

---

## 2. Implicit Requirements

- **No circular import.** `review/cli.py` imports `cli` from `pm_core.cli`;
  registration happens via the bottom-of-file import in
  `pm_core/cli/__init__.py`, after `cli` is defined — same as every other
  submodule. The `review_cli` alias avoids shadowing `pm_core.cli`.
- **`store.load` tolerates `reviews:`.** Confirmed: validation touches only
  `prs`/`plans`; extra keys pass through and are preserved by `save`.
- **Slugify bounds.** `store.slugify` lowercases, dashes non-alnum, strips, and
  truncates to 50 chars — ids stay branch/dir-safe. Reuse it; don't reinvent.
- **Directory creation is idempotent** (`mkdir(exist_ok=True)`), safe to call on
  both resume and create.
- **`reviews:` (yaml key) ≠ `pm/reviews/` (dir).** `pm_core/plans/review.py`
  already uses `root / "reviews"` for plan-add/breakdown *review-check* markdown
  files. That is a different concept; this PR's registry uses the yaml
  `reviews:` key and the `docs/adversarial-review/reviews/` directory. No
  collision, but name things clearly to avoid confusion.
- **Foreground fallback when `claude`/tmux absent.** Every existing launcher
  degrades to printing the prompt when `find_claude()` is None; preserve that
  so the commands don't hard-crash in CI/headless contexts.
- **Badge data plumbing.** The plans-pane badge needs `active_review` in each
  plan dict; whatever code currently builds those dicts (app refresh path) must
  be extended to compute it from `registry.list_active`. Locate and update that
  builder, not just the renderer.
- **`pm review ui --port` parsing** must not collide with target parsing —
  `--port` is only meaningful for `ui`; harmless otherwise.

---

## 3. Ambiguities

### A1 — Where does pane management live: CLI command vs TUI? **[RESOLVED]**
The plan says both commands "open a new pane … running claude" (CLI does it) and
"Same code path, different pane parent," yet every existing plan command runs
claude **foreground** and lets the TUI's `_launch_in_plans_window` place the
pane. Resolution: a single shared `launch_review_session` seam. The TUI `r`
path reuses the existing `_launch_in_plans_window` (pane created by TUI, command
runs claude foreground) so it matches `pm plan review` exactly; the standalone
`pm review` / direct `pm plan literature-review` path splits its own pane via
`tmux.split_pane` + `pane_registry.register_pane`. Both ultimately register a
pane with `role="literature-review"`. This satisfies both the "own pane" and
"plan window" requirements and keeps the unit tests at the tmux boundary.

**Implementation note (review-loop 2909 i1).** `launch_review_session`
distinguishes the two cases with `tmux.current_window_id()`: when the command
is already running *inside* the target window (the TUI `r` path — the pane was
created by `_launch_in_plans_window` in the plan window), it runs claude
**foreground** in that pane rather than splitting a second one. Only the
standalone path (`target_window=None`, or a terminal whose current window is not
the plan window) splits + registers a new pane. The earlier draft always split
when in tmux, which produced a transient extra "launcher" pane in the TUI flow
that self-closed via its EXIT trap — functionally tolerable but divergent from
`pm plan review`. The foreground-detection restores parity.

### A2 — Plan-target artifact id: `stem` vs the example `regression`. **[RESOLVED]**
Plan's example shows `id: regression` for `target: pm/plans/plan-regression.md`,
but the task says "plan filename stem" (= `plan-regression`). The example is
illustrative; the literal rule wins → use `Path(file).stem`. Documented in §1.6.

### A3 — File-target id keeps the extension. **[RESOLVED]**
"file basename (slugified)" taken literally includes the extension
(`notes.md` → `notes-md`), deliberately contrasted with the plan's "stem" for
plan targets. Implemented literally; flagged here in case review prefers the
extension stripped — trivial to change in `derive_artifact_id`.

### A4 — Initial `STATE.md` writer. **[RESOLVED]**
`md_writer.update_state` (PR 2) is the canonical writer but PR 2 is independent.
PR 1 writes a minimal initial `STATE.md` inline (cycle 0 / not-started) to stay
self-contained; swap to `md_writer.update_state` when PR 2 lands.

### A5 — `pm review ui` server is PR 3. **[RESOLVED]**
PR 1 only implements the **route** (`_run_ui_server`), which no-ops with a
"ships later" message if the server module is absent. The test covers routing,
not the server.

No **[UNRESOLVED]** ambiguities.

---

## 4. Edge Cases

- **Target that is both a plan id and an existing file path.** Resolution order
  prefers plan id (registry lookup first), so `pm review plan-foo` reviews the
  plan even if a file `plan-foo` happens to exist in cwd. Documented order in
  §1.4.
- **Topic strings with shell-special chars / spaces.** Passed as a single argv
  entry; `slugify` sanitizes for the id; the raw topic is stored verbatim in
  `target`. A target with *no* alphanumerics (e.g. `"???"`) slugifies to the
  empty string; `run_review` rejects this up front (clear error, no registry
  entry / dir / `STATE.md`) rather than creating a degenerate review whose
  empty id collapses `dir_for` onto the shared `reviews/` root.
- **Resume after the review directory was deleted.** Registry hit but dir
  missing → `dir_for(create=True)` recreates it; `STATE.md` won't exist so
  `build_context` omits it (degrades to a fresh-start prompt). Acceptable.
- **Create when `reviews:` key is absent or `null`.** `create_review` must
  initialize `data["reviews"] = []` when `None`/missing (same guard as
  `plan_add` does for `data["plans"]`).
- **Id collision across target types.** Two different targets can slugify to the
  same id (e.g. a topic "regression" and `plan-regression`'s stem differ, but a
  file `regression` and topic "regression" collide). If a *create* would reuse
  an existing **active** id with a different target, treat as resume of that id
  (registry is keyed by id). This is the documented resume-by-id behavior; note
  it but don't add collision-suffixing in PR 1 (the walker UI assumes id ==
  directory).
- **`pm plan literature-review` with no plan / multiple plans.**
  `_auto_select_plan` already errors helpfully when ambiguous; reuse it.
- **Plan window not present when run from terminal.** `find_window_by_name`
  returns None → fall back to own-pane/foreground launch; no crash.
- **`store.locked_update` lock contention.** Inherited 2 s timeout +
  `StoreLockTimeout`; same exposure as all other writers. No special handling.
- **Badge for archived reviews.** Only `list_active` drives the badge, so an
  archived review shows no badge — matches "plans with an active review."

---

## 5. Implementation order

1. `review/paths.py` (pure, no deps) + `test_paths.py`.
2. `review/registry.py` (uses `store`) + `test_registry.py`.
3. `review/context.py` (uses `paths`) + `test_context.py`.
4. `review/cli.py`: `derive_artifact_id`, `run_review`, `launch_review_session`,
   `_run_ui_server`, the `review` command; register in `cli/__init__.py`.
   + `test_review_cli.py`.
5. `cli/plan.py`: `literature-review` subcommand + `test_plan_literature_review.py`.
6. `tui/plans_pane.py` keybinding + badge; `pane_ops.handle_plan_action`
   dispatch; plan-dict builder `active_review` field +
   `test_plans_pane_keybinding.py`.
7. Run full `pytest tests/review/`; smoke the CLI help; human-guided TUI/tmux
   verification (flagged in task).
