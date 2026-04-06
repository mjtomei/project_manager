# QA Spec for PR pr-e839314: Plan parser support for `## Plans` section

## Requirements

1. **`parse_plan_children(text)` returns correct dicts** — Given markdown with a `## Plans` section containing `### Plan:` blocks, returns a list of dicts each with keys: `title`, `summary`, `status`, `id`. Field values are extracted from `- **field**: value` lines within each block.

2. **Section boundary handling** — The `## Plans` section ends at the next `## ` heading (not `###`). Content after the next `## ` heading is not included in results.

3. **Section ordering independence** — `## Plans` and `## PRs` can appear in any order. Each parser (`parse_plan_children`, `parse_plan_prs`) finds its own section independently and returns correct results regardless of ordering.

4. **Missing fields default to empty string** — If a `### Plan:` block omits any of `summary`, `status`, or `id`, those keys are present in the result dict with value `""`.

5. **`---` separator handling** — Horizontal rule separators between blocks are stripped and do not affect parsing.

6. **No regression in `parse_plan_prs()`** — The `_parse_section()` refactoring must preserve all existing `parse_plan_prs()` behavior. All pre-existing PR parsing tests must continue to pass.

7. **`extract_field()` works for new field names** — `extract_field(body, "summary")`, `extract_field(body, "status")`, and `extract_field(body, "id")` return correct values. `extract_field(body, "nonexistent")` returns `""`.

8. **Parsing only — no side effects** — `parse_plan_children()` does not read/write files, touch `project.yaml`, or interact with any external system.

## Setup

- No special setup required. This is a pure-function parsing module with no external dependencies.
- Run tests with: `python -m pytest tests/test_plan_parser.py -v`
- The module under test is `pm_core/plan_parser.py`.

## Edge Cases

1. **Empty input** — `parse_plan_children("")` returns `[]`.
2. **No `## Plans` section** — Text with other sections but no `## Plans` returns `[]`.
3. **Empty `## Plans` section** — Section header exists but no `### Plan:` blocks inside returns `[]`.
4. **Title-only blocks** — `### Plan: Foo` with no field lines returns `{"title": "Foo", "summary": "", "status": "", "id": ""}`.
5. **`## Plans` after `## PRs`** — Both parsers work correctly regardless of section order.
6. **`## Plans` before `## PRs`** — Same as above, reversed.
7. **Whitespace in field values** — Leading/trailing whitespace in values is stripped by `extract_field()`.
8. **Case sensitivity of section header** — `## Plans` must be exact (not `## plans` or `## PLANS`). The regex uses `re.escape(section)` without `re.IGNORECASE` for the section header match.
9. **Field name case sensitivity** — `extract_field()` uses `re.IGNORECASE` for field names, so `**Summary**:` and `**summary**:` both match.
10. **Multiple `## Plans` sections** — Only the first occurrence is parsed (regex `re.search` finds the first match).

## Pass/Fail Criteria

- **Pass**: All 12 existing tests in `tests/test_plan_parser.py` pass. `parse_plan_children()` returns correct results for all documented input formats. `parse_plan_prs()` behavior is unchanged from before the refactoring. No import errors or runtime exceptions.
- **Fail**: Any test failure. Incorrect field values. Missing keys in returned dicts. `parse_plan_prs()` regression. Unexpected exceptions on valid input.

## Ambiguities

1. **Should `## Plans` header matching be case-sensitive?**
   - Resolution: Yes. The `_parse_section()` helper uses `re.escape(section)` without `re.IGNORECASE` for the `## <section>` header match. This matches the existing `parse_plan_prs()` behavior where `## PRs` is case-sensitive. The field extraction within blocks *is* case-insensitive (line 89 uses `re.IGNORECASE`).

2. **What happens with duplicate `## Plans` sections?**
   - Resolution: Only the first is parsed. `re.search()` returns the first match. This is the same behavior as `parse_plan_prs()` with duplicate `## PRs` sections.

3. **Should `### Plan:` prefix be case-sensitive?**
   - Resolution: Yes. `re.escape(block_prefix)` is used without `re.IGNORECASE`. `### plan:` would not match. This mirrors `### PR:` behavior.

## Mocks

No mocks are needed. This PR modifies a pure parsing module (`pm_core/plan_parser.py`) with no external dependencies — no filesystem access, no network calls, no database, no subprocess invocations. All functions are pure: text in, structured data out. Tests exercise the functions directly with inline string fixtures.
