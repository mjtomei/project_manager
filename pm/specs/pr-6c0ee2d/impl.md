# Spec: pr-6c0ee2d — `pm/architecture.md` state + prompt awareness

Plan: `pm/plans/plan-axiomatic-design.md` (PR 1 of the plan; PRs 2–4 and every
refactor PR depend on it).

## 1. Requirements (grounded in the code)

### R1 — `pm/architecture.md` is a first-class pm state document
- Lives at `root / "architecture.md"` where `root` is the pm state root
  (`store.find_project_root()` / `state_root()`), so it works for both the
  in-repo `pm/` dir and a standalone `--dir` pm repo (plan "Constraints").
- Modeled on `pm/notes.txt` in `pm_core/notes.py`: plain file I/O, **zero
  analyzer code**, free-form markdown. The module docstring documents the
  recommended layout (provenance header with date / git commit / model; FRs;
  disjoint DPs mapped to modules/dirs; Design Matrix `[A]`; known coupling
  debt; FR/DP change log, newest last). Nothing parses that layout.
- Committed (not gitignored). `ensure_notes_file()` does **not** create it: an
  empty placeholder would flip the "exists" gate in every prompt. Creating
  it is PR 2's job (bootstrap/regeneration).
- New helpers in `pm_core/notes.py`:
  - `ARCHITECTURE_FILENAME = "architecture.md"`
  - `load_architecture(root) -> str`: stripped content, `""` when missing,
    empty or unreadable.
  - `architecture_pointer(root) -> str`: how a session names the file:
    `pm/architecture.md` for an in-repo pm dir (`store.is_internal_pm_dir`),
    otherwise the absolute path `root/architecture.md`.
- The prompt block lives in a new `pm_core/architecture_prompts.py` (next to
  `bug_fix_prompts` / `regression_prompts`), not in `notes.py`: the plan's
  target table puts `notes` in DP2 ("notes primitives") and role prompt
  modules in DP7, so rewording a role's guidance must not touch the state
  module (review-loop 322e i1):
  - `PROMPT_TYPES = ("plan", "impl", "review")`
  - `architecture_section(root, prompt_type, *, pr_id=None,
    max_bytes=ARCHITECTURE_BUDGET) -> str`: the prompt block (see R2).
    Returns `""` when there's no document. `pr_id` fills the impl guidance's
    `pm pr note add` command (placeholder `<pr-id>` when omitted).

### R2 — Bounded prompt-section helper (mirrors `notes.notes_section`)
- `architecture_section` returns:
  ``## Project Architecture (`<pointer>`)`` → role-specific awareness
  guidance (instruction text, never truncated) → the document excerpt →
  `## File Structural Debt, Don't Just Comment It` rule (instruction text,
  never truncated).
- Only the **document excerpt** is bounded, via
  `prompt_bounds.bounded_text(text, max_bytes=ARCHITECTURE_BUDGET,
  pointer="`<architecture_pointer>`", label="architecture document")`. That keeps the
  head (provenance, FRs/DPs, matrix: 75%) and the tail (latest change-log
  entries: 25%) and inserts a marker naming the file.
- `pm_core/prompt_bounds.py`: add `ARCHITECTURE_BUDGET = 16_000` and extend
  the module docstring's "What is bounded" list with a third kind: on-disk
  reference documents the session can read in full (`pm/architecture.md`).
  The guidance around the excerpt stays instruction text and is inlined
  whole.
- `prompt_type` ∈ {`"plan"`, `"impl"`, `"review"`}. An unknown type raises
  `ValueError` so a typo can't silently drop the guidance.

### R3 — Awareness wording per role
Common to all roles: read the FRs/DPs/matrix in the document instead of
re-deriving the architecture; keep changes inside the DP(s) they belong to;
don't add upward `*` coupling (a lower-order DP depending on a higher-order
one, **including lazy/function-level imports**) or hidden shared-state cycles
(module globals, shared files, app attributes written by one DP and read by
another); note when a change legitimately introduces a new FR/DP.
- **plan** (`pm plan add`, `breakdown`, `review` pre- and post-load,
  `import`): map each proposed PR to the DP(s) it touches (name them in the
  description when not obvious); order PRs so dependencies flow down the
  matrix; when the plan legitimately introduces a new FR/DP or moves a module
  between DPs, say so explicitly in the plan file (what, where it sits in the
  matrix order, why) so `pm/architecture.md` can be updated.
- **impl** (`generate_prompt`; bug-fix PRs get this too): locate the DP(s)
  the task touches before designing; when the PR legitimately introduces a
  new FR/DP or remaps modules, record it with
  `pm pr note add <pr-id> 'architecture: …'`. Edit `pm/architecture.md`
  directly only when the PR's task says to. The sign-off flow (plan PR 3)
  owns keeping it current, which avoids every concurrent PR conflicting on
  one shared document.
- **review** (`generate_review_prompt`, incl. review-loop mode): treat the
  document as the baseline; flag new upward coupling, lazy imports that
  sidestep a cycle, new cross-DP shared mutable state, modules that map to no
  DP, and changes that blur two DPs together. A new upward edge →
  **NEEDS_WORK** (stated in the review guidance); an orphan workaround
  comment (no improvements PR id) → **NEEDS_WORK** (stated once, in the
  debt rule's review lead). A contested FR/DP boundary change that needs
  human judgment → **INPUT_REQUIRED**. Check that a legitimately new FR/DP
  was noted.

### R4 — "File Structural Debt, Don't Just Comment It" rule
Reuses the `regression_prompts._filing_addendum` command pattern
(`pm pr list --plan improvements`, `pm pr add … --plan improvements
--description …`, `pm pr note add <pr-id> …`). Whenever an agent must add an
out-of-scope workaround, a defensive guard, a lazy import to sidestep a cycle,
or a duplicated invariant check:
1. `pm pr list --plan improvements` to look for an existing PR on the same
   structural problem;
2. if one exists, `pm pr note add <pr-id> '<where it bit, what workaround>'`
   so recurring pain self-prioritizes;
3. otherwise `pm pr add '<title>' --plan improvements --description '<root
   coupling, where it bites, the workaround, the proper fix>'`;
4. reference that PR id in the code comment next to the workaround instead
   of an orphan historical tag (bare scenario number, date, "temporary
   hack").

Role variants: plan sessions apply it to workarounds or debt a plan accepts
(and reference the id in the plan). Review sessions check the diff for it and
follow it themselves when fixing in review-loop mode.

### R5 — Wiring
- `pm_core/prompt_gen.py`
  - `generate_prompt`: compute `arch_block = architecture_section(root,
    "impl", pr_id=pr_id)` once when `root` resolves, and insert it after the spec preamble,
    before the bug-fix block. Static for this build (outside `fit_prompt`'s
    shrinkable blocks, already self-bounded).
  - `generate_review_prompt`: `arch_block = architecture_section(root,
    "review", pr_id=pr_id)` inserted after the plan context. When present, the
    "Architectural review" step gains a bullet pointing at it.
  - Pass `has_architecture=bool(arch_block)` to the bug-fix blocks.
- `pm_core/bug_fix_prompts.py`
  - `_bug_fix_flow_block(pr, has_architecture=False)`: when True, step 3
    ("Fix") adds: fix the root cause inside the owning DP; a guard, lazy
    import or duplicated check that papers over coupling falls under **File
    Structural Debt** (file/append an improvements PR and cite its id).
  - `_bug_fix_review_block(pr, has_architecture=False)`: when True, add a
    checklist bullet: the fix addresses the root cause rather than masking
    coupling, and any accepted workaround cites a filed `improvements` PR id.
  - With the default `False`, output is byte-identical to today (existing
    tests and callers are unaffected).
- `pm_core/cli/plan.py`: `plan add`, `plan breakdown`, `plan review` (both
  prompt branches) and `plan import` (`_run_plan_import`) append
  `architecture_section(root, "plan")` just before the TUI/notes tail.
  `plan deps` and `plan fix` are left alone (dependency-graph edits and
  review-finding fixes, not plan shaping).

### R6 — Tests
New `tests/test_prompt_gen.py` (all hermetic: `store.find_project_root`
monkeypatched to a tmp `pm/` dir; plan CLI driven with `-C <tmp root>` and
`find_claude` patched to `None` so the prompt is printed):
- `architecture_section`: absent → `""`; whitespace-only → `""`; unreadable
  (a directory at that path) → `""`; small doc inlined verbatim with no
  truncation marker; over budget → excerpt bounded (block ≤ budget + static
  guidance), head (provenance) and tail (latest change log) kept, marker
  names the pointer; in-repo vs standalone pointer; role variants differ;
  unknown role raises; non-UTF-8 bytes don't crash.
- Prompt generation with/without `architecture.md`: impl, review
  (incl. review-loop), bug-fix impl + bug-fix review, and plan
  add/breakdown/review/import include the architecture header, the debt
  rule and its `pm pr list --plan improvements` command when present, and
  contain none of them when absent.

## 2. Implicit requirements
- **No behaviour change without the doc.** Every new string is gated on a
  non-empty `pm/architecture.md`; absent → prompts are byte-identical to
  today. The existing bug-fix tests that call the blocks directly keep passing.
- **No import cycles.** `notes` (DP2) imports only `store` (DP1);
  `architecture_prompts` (DP7) imports `notes` and `prompt_bounds` (DP2) —
  downward only, all top-level.
- `fit_prompt` re-renders several times, so the block is computed once,
  outside `_assemble`.
- `generate_review_prompt` currently binds `root` only inside its `try`. The
  architecture lookup must sit inside the same `FileNotFoundError` guard so a
  missing project root still yields a prompt.
- The guidance names commands that exist: `pm pr list --plan`, `pm pr add
  --plan --description`, `pm pr note add` (verified in `cli/pr.py`).
  `pm pr add --plan improvements` works even when the project has no
  `improvements` plan entry (the plan id isn't validated), so filing works on
  projects PR 2 hasn't touched yet.
- PRs filed / notes added from a workdir land in the workdir's
  `project.yaml` and travel to master on merge. That's the same mechanism
  the existing Incidental Bugs and PR-notes guidance relies on.

## 3. Ambiguities (resolved)
1. **Gate the structural-debt rule on the doc's existence?** The task's test
   line says prompts include the rule "when `pm/architecture.md` exists and
   stay clean when absent". → Gated together with the awareness block.
2. **Bounding vs. the "instructions are never truncated" policy in
   `prompt_bounds`.** The task explicitly asks for graceful abbreviation with
   a pointer. → Only the document *excerpt* is bounded: it's an on-disk
   reference the session can read in full. The surrounding guidance and the
   debt rule are inlined whole. The `prompt_bounds` docstring is updated to
   name this third bounded kind.
3. **Who updates `pm/architecture.md` when an FR/DP is added?** → Plans note
   it in the plan file. Impl sessions record a PR note, and edit the doc only
   when their task says to (the plan's refactor PRs do). Sign-off (PR 3)
   owns routine updates. This avoids conflicts from concurrent PRs editing one
   document.
4. **Pointer form.** → `pm/architecture.md` for in-repo pm dirs (matches
   the `pm/specs/...` convention impl sessions already use in their clone).
   The absolute path for standalone pm dirs, whose clones contain no `pm/`.
5. **Budget size.** → `ARCHITECTURE_BUDGET = 16_000` bytes. Impl static text
   runs ~19 KB and PR notes ≤ 35 KB. 16 KB fits a Level-1 matrix for ~15
   FR/DPs plus the debt list, and the full doc is one read away. The block
   is not handed to `fit_prompt` as shrinkable: it's already bounded, and
   anything over the argv limit goes through the launcher's file-backed
   bootstrap.
6. **Which plan prompts?** → add, breakdown, review (pre- and post-load),
   import. Not deps or fix (see R5).
7. **Where tests live.** The task names `tests/test_prompt_gen.py`, which
   doesn't exist yet → create it.

## 4. Edge cases
- Doc with only whitespace → treated as absent.
- Path exists but is a directory, or reading raises `OSError` → treated as
  absent. It's an optional reference, and a prompt builder must not crash on
  it. Undecodable bytes are read with `errors="replace"`.
- A doc far over budget, or with multi-byte UTF-8 → `bounded_text` measures
  bytes and cuts on character boundaries.
- No project root (`FileNotFoundError`) → no block, as with notes.
- Review of a PR that itself edits `pm/architecture.md`: the inlined copy is
  the base pm root's (pre-PR) version, which is the right baseline. The diff
  shows the PR's edits.
- Impl session resuming on a branch that already edited the doc: the inlined
  copy is the base root's. The guidance tells the agent to read the file
  (its workdir copy) for the full or latest text.
- Existing non-hermetic tests that build prompts against the real repo's
  `pm/` will start seeing the block once the dogfood baseline lands (plan
  PR 4). No current test asserts its absence, and new tests are hermetic.
- Conflict surface with in-flight `pr-30888b1` (#104, folds `plan breakdown`
  into `plan add` and deletes `plan_breakdown`): plan.py changes are one-line
  insertions per prompt, so a rebase stays trivial. Whichever PR merges
  second must (1) drop this PR's `arch_block` lines from the deleted
  `plan_breakdown` (a modify/delete conflict in plan.py), and (2) drop the
  `"breakdown"` entry from `_PLAN_COMMANDS` in `tests/test_prompt_gen.py`.
  That test file merges cleanly but then fails 2 `TestPlanPrompts::*[breakdown]`
  cases with "No such command" (found by pr-30888b1 review 4efb i1's trial
  merge). `plan add` already carries the block, so nothing else is needed.
  The breakdown wiring stays here because master still has the command
  (review-loop 322e i1).
