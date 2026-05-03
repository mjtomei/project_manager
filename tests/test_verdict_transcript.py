"""Tests for pm_core.verdict_transcript.extract_verdict_from_transcript."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pm_core.verdict_transcript import extract_verdict_from_transcript


VERDICTS = ("INPUT_REQUIRED", "NEEDS_WORK", "PASS")


def _assistant_line(text: str) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    })


def _user_line(text: str) -> str:
    return json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    })


def _write(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(lines) + "\n")
    return p


def test_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert extract_verdict_from_transcript(tmp_path / "missing.jsonl", VERDICTS) is None


def test_returns_none_for_none_path() -> None:
    assert extract_verdict_from_transcript(None, VERDICTS) is None


def test_returns_none_for_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_latest_turn_verdict(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("first"),
        _assistant_line("Looks good.\nPASS\n"),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"


def test_verdict_as_entire_text(tmp_path: Path) -> None:
    p = _write(tmp_path, [_user_line("go"), _assistant_line("PASS")])
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"


def test_longest_match_wins(tmp_path: Path) -> None:
    # Verdicts list has no prefix overlap today, but the extractor still
    # scans longest-first defensively so a future longer verdict would
    # win over any shorter prefix.
    custom = ("PASS", "PASS_EXTRA")
    p = _write(tmp_path, [
        _user_line("review"),
        _assistant_line("Summary.\nPASS_EXTRA\n"),
    ])
    assert extract_verdict_from_transcript(p, custom) == "PASS_EXTRA"


def test_incidental_mention_not_matched(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("q"),
        _assistant_line("I will PASS this test to the next agent."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_only_latest_turn_scanned(tmp_path: Path) -> None:
    # Older turn emits PASS.  Latest turn emits nothing notable — we
    # must NOT return the stale PASS from the previous turn.
    p = _write(tmp_path, [
        _user_line("first"),
        _assistant_line("all good\nPASS\n"),
        _user_line("follow-up question"),
        _assistant_line("Here is some commentary without a verdict."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_latest_turn_overrides_older(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("first"),
        _assistant_line("PASS\n"),
        _user_line("reconsider"),
        _assistant_line("After review:\nNEEDS_WORK\n"),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "NEEDS_WORK"


def test_meta_lines_within_turn_ignored(tmp_path: Path) -> None:
    # A last-prompt / permission-mode meta record between the user
    # message and the assistant response must not break detection.
    lines = [
        _user_line("go"),
        json.dumps({"type": "permission-mode", "permissionMode": "bypassPermissions"}),
        _assistant_line("Done.\nPASS\n"),
    ]
    p = _write(tmp_path, lines)
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"


def test_multiple_assistant_records_in_same_turn(tmp_path: Path) -> None:
    # Thinking + tool_use + final text — all are "assistant" records.
    # Verdict in the last one still wins.
    lines = [
        _user_line("q"),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "..."}]}}),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}}),
        _assistant_line("Summary here.\nNEEDS_WORK\n"),
    ]
    p = _write(tmp_path, lines)
    assert extract_verdict_from_transcript(p, VERDICTS) == "NEEDS_WORK"


def test_empty_verdicts_returns_none(tmp_path: Path) -> None:
    p = _write(tmp_path, [_user_line("q"), _assistant_line("PASS")])
    assert extract_verdict_from_transcript(p, ()) is None


def test_markdown_bold_verdict(tmp_path: Path) -> None:
    # Reviewers commonly wrap their verdict in markdown bold.  Must match.
    p = _write(tmp_path, [
        _user_line("q"),
        _assistant_line("Summary.\n\n**NEEDS_WORK**\n"),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "NEEDS_WORK"


def test_markdown_code_verdict(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("q"),
        _assistant_line("`PASS`\n"),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"


def test_bold_incidental_still_rejected(tmp_path: Path) -> None:
    # Markdown tolerance must not swallow incidental prose mentions.
    p = _write(tmp_path, [
        _user_line("q"),
        _assistant_line("I will **PASS** this along to the next agent."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_longer_verdict_not_masked_by_shorter_prefix(tmp_path: Path) -> None:
    # If the extractor naively scans PASS first it would match only PASS
    # when the real verdict is a longer PASS_* variant.  Longest-first
    # guards against that regardless of which verdicts are registered.
    custom = ("PASS", "PASS_AND_THEN_SOME")
    p = _write(tmp_path, [
        _user_line("q"),
        _assistant_line("PASS_AND_THEN_SOME\n"),
    ])
    assert extract_verdict_from_transcript(p, custom) == "PASS_AND_THEN_SOME"
