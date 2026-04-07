# Implementation Spec: Merge PR notes from both main and workdir project.yaml

## Requirements

1. **Modify `_format_pr_notes`** (`pm_core/prompt_gen.py:31-41`) to accept an optional workdir path and merge notes from both the main project.yaml and the workdir's project.yaml.

2. **Load workdir PR entry**: When a workdir path is provided and `<workdir>/pm/project.yaml` (or `<workdir>/project.yaml`) exists, load it via `store.load()` and find the matching PR entry using `store.get_pr()`.

3. **Deduplicate by note ID**: When notes exist in both sources, prefer the version with the later `last_edited` timestamp. Notes with unique IDs are included from either source.

4. **Sort merged notes by `created_at`**: The final merged list should be sorted chronologically.

5. **Update all callers**: All 5 call sites of `_format_pr_notes` must pass the workdir path:
   - `generate_prompt` (line 94) — `pr.get("workdir")` available via the `pr` dict
   - `generate_review_prompt` (line 183) — `pr` dict available
   - `generate_qa_planner_prompt` (line 834) — `pr` dict available; `workdir` already extracted at line 810
   - `generate_qa_interactive_prompt` (line 954) — `pr_workdir` already extracted at line 951
   - `generate_qa_child_prompt` (line 1073) — `pr` dict available

## Implicit Requirements

1. **Graceful degradation**: If the workdir path doesn't exist, or `project.yaml` is missing/unparseable, or the PR entry isn't found in the workdir data, fall back silently to main-only notes (current behavior).

2. **No mutation of caller data**: The function must not modify the `pr` dict or its notes list from either source.

3. **Handle both PM directory layouts**: The workdir's project.yaml could be at `<workdir>/pm/project.yaml` (internal PM dir) or `<workdir>/project.yaml` (standalone). Use `store.find_project_root(workdir)` to locate it correctly.

4. **Notes may lack `last_edited`**: Older notes might only have `created_at`. The deduplication logic must fall back to `created_at` when `last_edited` is absent.

5. **Notes may lack `id`**: Edge case — if a note has no `id` field, it should still be included (can't be deduplicated, just passed through).

## Ambiguities

1. **What is the workdir path?**
   - The `pr` dict has a `workdir` field (string path) set when a worktree is created.
   - **Resolution**: Use `pr.get("workdir")` as the workdir path. This is the canonical location.

2. **Should `_format_pr_notes` call `store.load()` or accept pre-loaded workdir data?**
   - Loading inside the function is simpler for callers but adds I/O.
   - **Resolution**: Load inside `_format_pr_notes`. The function is called once per prompt generation; the I/O cost is negligible. This keeps the caller change minimal (just passing a path string).

3. **How to find project root in workdir?**
   - The workdir is a clone of the repo. If pm runs "internally" (pm/ subdir), the project.yaml is at `<workdir>/pm/project.yaml`.
   - **Resolution**: Use `store.find_project_root(start=workdir_path)` which handles both layouts. Wrap in try/except for graceful degradation.

4. **What if the same note was edited differently in both locations?**
   - **Resolution**: Per task description, prefer the version with the later `last_edited` timestamp. This is the most intuitive "last writer wins" approach.

## Edge Cases

1. **Workdir is None or empty string**: Skip workdir loading entirely, return main-only notes.

2. **Workdir path doesn't exist on disk**: `find_project_root` will raise `FileNotFoundError`; catch and fall back.

3. **Workdir project.yaml exists but PR entry is missing**: `get_pr` returns None; treat as no workdir notes.

4. **Both sources have zero notes**: Return empty string (existing behavior).

5. **Only workdir has notes, main has none**: Return workdir notes only.

6. **Notes with duplicate IDs but identical content**: Dedup still picks one (by timestamp), result is correct.

7. **`store.load()` raises `ProjectYamlParseError`**: Catch broadly to avoid breaking prompt generation.

## Implementation Plan

1. Modify `_format_pr_notes(pr, workdir=None)` signature.
2. Add workdir note loading logic with `store.find_project_root()` + `store.load()` + `store.get_pr()`.
3. Merge notes by building a dict keyed by note ID, preferring later `last_edited`.
4. Sort by `created_at`.
5. Update all 5 call sites to pass `workdir=pr.get("workdir")`.
