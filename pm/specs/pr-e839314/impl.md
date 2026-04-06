# Impl Spec for PR pr-e839314: Plan parser support for `## Plans` section

## Requirements

1. **`parse_plan_children()` function** in `pm_core/plan_parser.py` — Parse a `## Plans` section from a plan markdown file, returning a list of dicts. Each dict has keys: `title`, `summary`, `status`, `id`. This mirrors the pattern of `parse_plan_prs()` (line 24) which parses `## PRs` sections into structured dicts.

   Expected markdown format:
   ```
   ## Plans

   ### Plan: <title>
   - **summary**: One-line summary of the child plan
   - **status**: draft | active | done
   - **id**: plan-<hash>

   ---

   ### Plan: <title>
   ...
   ```

   The function should:
   - Find `## Plans` by regex (`^## Plans\s*$`), analogous to how `parse_plan_prs()` finds `## PRs` (line 39)
   - Stop at the next `## ` heading (but not `###`), same boundary logic as line 46-48
   - Split on `### Plan:` headings, analogous to `### PR:` splitting (line 51)
   - Extract title from the first line after splitting
   - Extract `summary`, `status`, and `id` fields using `extract_field()` (line 79)

2. **`extract_field()` support for `summary`** — The existing `extract_field(body, field)` function at line 79 is generic: it matches `- **<field>**: <value>`. It already supports any field name, so `extract_field(body, "summary")` works without modification. No code change needed — this requirement is satisfied by the existing implementation. Tests should verify it works for summary, status, and id.

3. **Parsing only** — No load/write behavior. `parse_plan_children()` only returns parsed data; it does not interact with `store.py`, `project.yaml`, or the filesystem.

4. **Tests** in `tests/test_plan_parser.py`:
   - Test parsing a plan file with `## Plans` section containing multiple children
   - Test parsing a plan with both `## Plans` and `## PRs` sections (both parsers coexist)
   - Test parsing a plan with no `## Plans` section (returns empty list)
   - Test `extract_field()` for summary, status, and id fields

## Implicit Requirements

1. **Section ordering independence** — `## Plans` and `## PRs` sections can appear in any order in the same file. Each parser finds its own section header independently via regex, so they don't interfere. Tests should verify both orderings.

2. **Consistent boundary handling** — The `## Plans` section ends at the next `## ` heading (not `###`), the same rule used by `parse_plan_prs()`. This means `### Plan:` headings within the section are not treated as section boundaries.

3. **Missing fields default to empty string** — Like PR parsing, any missing field should return `""` via `extract_field()` (line 84 returns `""` on no match). A child plan block with only a title and no fields should produce `{"title": "...", "summary": "", "status": "", "id": ""}`.

4. **`---` separators stripped** — Same as PR parsing (line 60), horizontal rule separators between child plan blocks should be removed before field extraction.

5. **Module docstring update** — The module docstring (line 1) currently says "Parse the ## PRs section from a plan file." It should be broadened to cover both sections.

## Ambiguities

1. **Heading prefix: `### Plan:` vs `### Child:` vs other?**
   - Resolution: Use `### Plan:` to match the `### PR:` convention. The section header `## Plans` already establishes context, and `### Plan:` is the most natural parallel.

2. **Should `id` be required or optional?**
   - Resolution: Optional, same as all other fields. When parsing a plan file that was written by hand or before IDs were assigned, `id` will be `""`. The caller (future load logic) is responsible for generating IDs when missing.

3. **Field name: `summary` vs `description`?**
   - Resolution: Use `summary` as specified in the task. This distinguishes child plan summaries from PR descriptions and aligns with the one-line-overview nature of the field (vs multi-line PR descriptions).

4. **Return type: list of dicts vs list of dataclasses/TypedDicts?**
   - Resolution: Plain dicts, matching `parse_plan_prs()` return type. No dataclasses or TypedDicts are used elsewhere in the parser module.

## Edge Cases

1. **Empty `## Plans` section** — Section header exists but no `### Plan:` blocks. Should return `[]`.

2. **`## Plans` with no fields, just titles** — Each block has only a title line. Should return dicts with empty string values for summary/status/id.

3. **Whitespace in field values** — `extract_field()` already strips whitespace (line 84). Values like `  draft  ` should become `"draft"`.

4. **Plan with only `## Plans` and no `## PRs`** — `parse_plan_prs()` returns `[]`, `parse_plan_children()` returns the children. Both work independently.

5. **`## Plans` appearing before introductory text** — `extract_plan_intro()` stops at the first `## ` heading. If `## Plans` comes first, the intro is everything before it. This is existing behavior and unaffected.
