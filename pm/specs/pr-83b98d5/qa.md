# QA Spec: Merge PR notes from both main and workdir project.yaml into prompts

## Requirements

1. **Workdir note loading**: `_format_pr_notes(pr, workdir=...)` loads the workdir's `pm/project.yaml` via `store.find_project_root(start=workdir)` + `store.load(validate=False)` + `store.get_pr()`, then collects notes from the matching PR entry.

2. **Merge and deduplication**: Notes from main and workdir are merged. When both contain a note with the same `id`, the version with the later `last_edited` timestamp wins. Falls back to `created_at` when `last_edited` is absent.

3. **Sorting**: The merged note list is sorted by `created_at` ascending.

4. **Graceful degradation**: If the workdir path is None, empty, nonexistent, has no `project.yaml`, or lacks the PR entry, the function silently falls back to main-only notes (no exception raised).

5. **All 5 callers updated**: Every call site passes `workdir=pr.get("workdir")`:
   - `generate_prompt` (line ~131)
   - `generate_review_prompt` (line ~220)
   - `generate_qa_planner_prompt` (line ~871)
   - `generate_qa_interactive_prompt` (line ~991)
   - `generate_qa_child_prompt` (line ~1110)

6. **No mutation**: The function must not mutate the `pr` dict or notes lists from either source (uses `list()` copies).

7. **Notes without IDs**: Notes lacking an `id` field are included unconditionally (cannot be deduplicated).

## Setup

- Tests run via `python -m pytest tests/test_pr_notes.py -x -q` from the project root (`/home/mjtomei/project_manager`).
- The `_make_workdir_state(tmp_path, pr_id, notes)` helper creates a realistic workdir with `pm/project.yaml` containing a single PR.
- No external services, tmux, or Claude sessions are required. All tests are unit-level using pytest `tmp_path` fixtures.

## Edge Cases

1. **Workdir is None** — behaves identically to pre-PR behavior.
2. **Workdir path doesn't exist on disk** — catches exception, returns main-only notes.
3. **Workdir project.yaml exists but PR ID not found** — `get_pr` returns None, falls back gracefully.
4. **Both sources have zero notes** — returns empty string.
5. **Only workdir has notes, main has none** — workdir notes appear.
6. **Only main has notes, workdir has none** — main notes appear (standard behavior).
7. **Duplicate note IDs, main version newer** — main version kept.
8. **Duplicate note IDs, workdir version newer** — workdir version kept.
9. **Notes missing `last_edited`** — dedup falls back to `created_at` comparison.
10. **Notes missing `id`** — included unconditionally (no dedup possible).
11. **Workdir `store.load()` raises exception** (corrupt YAML) — caught by broad `except Exception`, degrades gracefully.

## Pass/Fail Criteria

**Pass**: All 40 existing tests in `tests/test_pr_notes.py` pass. The 11 new `TestFormatPrNotesWorkdirMerge` tests specifically verify the merge logic. All 5 callers pass `workdir=pr.get("workdir")`.

**Fail**:
- Any test failure in `test_pr_notes.py`.
- A caller of `_format_pr_notes` that doesn't pass the `workdir` kwarg.
- An exception raised when the workdir is missing or malformed instead of graceful degradation.
- Mutation of the input `pr` dict or notes lists.
- Incorrect dedup (wrong note version kept based on timestamps).
- Incorrect sort order of merged notes.

## Ambiguities

1. **What if `last_edited` is present but empty string?**
   - Resolution: The code uses `n.get("last_edited") or n.get("created_at", "")` — the `or` handles both `None` and `""`, falling back to `created_at`. This is correct behavior.

2. **Should `store.load()` be called with `validate=False`?**
   - Resolution: Yes. The workdir project.yaml may be in a partially-modified state (e.g., mid-implementation). `validate=False` avoids rejecting valid data due to strict validation rules. The implementation correctly uses this.

3. **What about notes without an `id`?**
   - Resolution: The code uses `id(n)` (Python object identity) as the dict key for id-less notes, making them always unique. This means duplicate id-less notes with identical text would both appear, but this is an acceptable edge case since id-less notes are legacy/unusual.

4. **Thread safety of `store.load()` calls from prompt generation?**
   - Resolution: Not a concern — prompt generation is single-threaded, and the file is read-only from this function's perspective.

## Mocks

**No mocks required.** All tests use real filesystem operations via pytest's `tmp_path` fixture. `store.save()` + `store.load()` + `store.find_project_root()` operate on temp directories. The `TestPromptGenNotes` integration tests mock `store.find_project_root` and `notes.notes_for_prompt` because those callers need them, but the core `_format_pr_notes` tests do not need mocks — they create real workdir state on disk.
