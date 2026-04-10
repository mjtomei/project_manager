"""Tests for pm_core.plan_parser."""

from pm_core.plan_parser import extract_field, parse_plan_children, parse_plan_prs, parse_split_prs


def test_parse_empty():
    assert parse_plan_prs("") == []
    assert parse_plan_prs("# Plan\n\nSome content") == []
    assert parse_plan_children("") == []
    assert parse_plan_children("# Plan\n\nSome content") == []


def test_parse_single_pr():
    text = """\
# My Plan

Some description.

## PRs

### PR: Add user auth
- **description**: Implement JWT auth
- **tests**: Unit tests for token gen
- **files**: src/auth.py, tests/test_auth.py
- **depends_on**:
"""
    result = parse_plan_prs(text)
    assert len(result) == 1
    assert result[0]["title"] == "Add user auth"
    assert result[0]["description"] == "Implement JWT auth"
    assert result[0]["tests"] == "Unit tests for token gen"
    assert result[0]["files"] == "src/auth.py, tests/test_auth.py"
    assert result[0]["depends_on"] == ""


def test_parse_multiple_prs_with_depends():
    text = """\
# Plan

## PRs

### PR: First PR
- **description**: Do the first thing
- **tests**: Test first
- **files**: a.py
- **depends_on**:

---

### PR: Second PR
- **description**: Do the second thing
- **tests**: Test second
- **files**: b.py
- **depends_on**: First PR
"""
    result = parse_plan_prs(text)
    assert len(result) == 2
    assert result[0]["title"] == "First PR"
    assert result[0]["depends_on"] == ""
    assert result[1]["title"] == "Second PR"
    assert result[1]["depends_on"] == "First PR"


def test_parse_stops_at_next_section():
    text = """\
## PRs

### PR: Only PR
- **description**: Something
- **tests**: Tests
- **files**: f.py
- **depends_on**:

## Notes

This should not be parsed.
"""
    result = parse_plan_prs(text)
    assert len(result) == 1
    assert result[0]["title"] == "Only PR"


def test_parse_missing_fields():
    text = """\
## PRs

### PR: Minimal PR
- **description**: Just a description
"""
    result = parse_plan_prs(text)
    assert len(result) == 1
    assert result[0]["title"] == "Minimal PR"
    assert result[0]["description"] == "Just a description"
    assert result[0]["tests"] == ""
    assert result[0]["files"] == ""
    assert result[0]["depends_on"] == ""


# --- parse_plan_children tests ---


def test_parse_children_multiple():
    text = """\
# Hierarchical Plans

Overview of the project.

## Plans

### Plan: Auth overhaul
- **summary**: Rework authentication to use OAuth2
- **status**: active
- **id**: plan-a1b2c3d

---

### Plan: API v2
- **summary**: New versioned API endpoints
- **status**: draft
- **id**: plan-e4f5a6b
"""
    result = parse_plan_children(text)
    assert len(result) == 2
    assert result[0]["title"] == "Auth overhaul"
    assert result[0]["summary"] == "Rework authentication to use OAuth2"
    assert result[0]["status"] == "active"
    assert result[0]["id"] == "plan-a1b2c3d"
    assert result[1]["title"] == "API v2"
    assert result[1]["summary"] == "New versioned API endpoints"
    assert result[1]["status"] == "draft"
    assert result[1]["id"] == "plan-e4f5a6b"


def test_parse_children_with_prs_section():
    text = """\
# Big Plan

## Plans

### Plan: Sub-plan A
- **summary**: First child
- **status**: done
- **id**: plan-1111111

## PRs

### PR: Some PR
- **description**: A PR in the parent plan
- **tests**: Test it
- **files**: foo.py
- **depends_on**:
"""
    children = parse_plan_children(text)
    assert len(children) == 1
    assert children[0]["title"] == "Sub-plan A"
    assert children[0]["status"] == "done"

    prs = parse_plan_prs(text)
    assert len(prs) == 1
    assert prs[0]["title"] == "Some PR"


def test_parse_children_no_section():
    text = """\
# Plan with only PRs

## PRs

### PR: Only PR
- **description**: Something
- **tests**: Tests
- **files**: f.py
- **depends_on**:
"""
    assert parse_plan_children(text) == []


def test_parse_children_empty_section():
    text = """\
# Plan with empty Plans section

## Plans

## PRs

### PR: Some PR
- **description**: A PR
- **tests**: Tests
- **files**: f.py
- **depends_on**:
"""
    assert parse_plan_children(text) == []


def test_parse_children_prs_before_plans():
    """## PRs appears before ## Plans — both parsers still work."""
    text = """\
# Plan

## PRs

### PR: First PR
- **description**: Do something
- **tests**: Tests
- **files**: a.py
- **depends_on**:

## Plans

### Plan: Child plan
- **summary**: A child
- **status**: active
- **id**: plan-ffff000
"""
    children = parse_plan_children(text)
    assert len(children) == 1
    assert children[0]["title"] == "Child plan"
    assert children[0]["summary"] == "A child"
    assert children[0]["status"] == "active"
    assert children[0]["id"] == "plan-ffff000"

    prs = parse_plan_prs(text)
    assert len(prs) == 1
    assert prs[0]["title"] == "First PR"


def test_parse_children_title_only():
    """Plan blocks with only titles — missing fields default to empty string."""
    text = """\
## Plans

### Plan: Bare plan
"""
    result = parse_plan_children(text)
    assert len(result) == 1
    assert result[0]["title"] == "Bare plan"
    assert result[0]["summary"] == ""
    assert result[0]["status"] == ""
    assert result[0]["id"] == ""


def test_extract_field_summary_status_id():
    body = """\
- **summary**: Build the new auth system
- **status**: active
- **id**: plan-abc1234
"""
    assert extract_field(body, "summary") == "Build the new auth system"
    assert extract_field(body, "status") == "active"
    assert extract_field(body, "id") == "plan-abc1234"
    assert extract_field(body, "nonexistent") == ""


# --- parse_split_prs tests ---


def test_parse_split_prs_empty():
    assert parse_split_prs("") == []
    assert parse_split_prs("# Some doc\n\nNo child PRs here.") == []


def test_parse_split_prs_single():
    text = """\
## Child PRs

### PR: Extract auth middleware
- **description**: Pull out the auth middleware into its own module
- **branch**: pm/split-pr-abc1234-extract-auth
- **depends_on**:
"""
    result = parse_split_prs(text)
    assert len(result) == 1
    assert result[0]["title"] == "Extract auth middleware"
    assert result[0]["description"] == "Pull out the auth middleware into its own module"
    assert result[0]["branch"] == "pm/split-pr-abc1234-extract-auth"
    assert result[0]["depends_on"] == ""


def test_parse_split_prs_multiple_with_deps():
    text = """\
## Child PRs

### PR: Add database schema
- **description**: Create the new tables
- **branch**: pm/split-pr-abc1234-db-schema
- **depends_on**:

---

### PR: Add API endpoints
- **description**: REST endpoints for the new feature
- **branch**: pm/split-pr-abc1234-api-endpoints
- **depends_on**: Add database schema

---

### PR: Add frontend components
- **description**: React components for the UI
- **branch**: pm/split-pr-abc1234-frontend
- **depends_on**: Add API endpoints
"""
    result = parse_split_prs(text)
    assert len(result) == 3
    assert result[0]["title"] == "Add database schema"
    assert result[0]["depends_on"] == ""
    assert result[1]["title"] == "Add API endpoints"
    assert result[1]["depends_on"] == "Add database schema"
    assert result[2]["title"] == "Add frontend components"
    assert result[2]["branch"] == "pm/split-pr-abc1234-frontend"
    assert result[2]["depends_on"] == "Add API endpoints"


def test_parse_split_prs_missing_fields():
    text = """\
## Child PRs

### PR: Minimal child
- **description**: Just a description
"""
    result = parse_split_prs(text)
    assert len(result) == 1
    assert result[0]["title"] == "Minimal child"
    assert result[0]["description"] == "Just a description"
    assert result[0]["branch"] == ""
    assert result[0]["depends_on"] == ""
