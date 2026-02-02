"""Tests for pm_core.plan_parser."""

from pm_core.plan_parser import parse_plan_prs


def test_parse_empty():
    assert parse_plan_prs("") == []
    assert parse_plan_prs("# Plan\n\nSome content") == []


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
