"""Tests for pm_core.verdict_transcript.extract_verdict_from_transcript."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pm_core.verdict_transcript import (
    extract_verdict_from_transcript,
    extract_verdict_reason_from_transcript,
    latest_turn_state,
)


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


def _local_command_line(text: str) -> str:
    # Claude Code writes slash-command output as a plain-string user record.
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": text},
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


def test_dangling_symlink_falls_back_to_session_id_glob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Reproduce pr-488b748: build_claude_shell_cmd points the symlink at a
    # mangled-cwd dir Claude never writes to (the cwd we *passed* in), but
    # the real JSONL lands in a sibling dir derived from Claude's actual
    # runtime cwd. The reader must locate it by session_id.
    sid = "abcdef01-2345-6789-abcd-ef0123456789"
    fake_home = tmp_path / "home"
    projects = fake_home / ".claude" / "projects"
    expected_dir = projects / "-where-we-thought"
    actual_dir = projects / "-where-claude-actually-wrote"
    expected_dir.mkdir(parents=True)
    actual_dir.mkdir(parents=True)

    real_jsonl = actual_dir / f"{sid}.jsonl"
    real_jsonl.write_text("\n".join([
        _user_line("q"),
        _assistant_line("Verdict on its own line:\nPASS\n"),
    ]) + "\n")

    # Symlink points into the empty expected_dir — its target never exists.
    symlink = tmp_path / "iter-1.jsonl"
    symlink.symlink_to(expected_dir / f"{sid}.jsonl")

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    assert extract_verdict_from_transcript(symlink, VERDICTS) == "PASS"


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


def test_reason_basic(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("did the steps\nReason: feature works end to end\nPASS"),
    ])
    assert extract_verdict_reason_from_transcript(p) == "feature works end to end"


def test_reason_picks_last_in_turn(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: early thought\nmore work\nReason: final summary\nPASS"),
    ])
    assert extract_verdict_reason_from_transcript(p) == "final summary"


def test_reason_ignores_prior_turn(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("first"),
        _assistant_line("Reason: stale from earlier\nPASS"),
        _user_line("re-evaluate"),
        _assistant_line("did it again\nReason: fresh take\nNEEDS_WORK"),
    ])
    assert extract_verdict_reason_from_transcript(p) == "fresh take"


def test_reason_tolerates_bold(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("**Reason:** bold form\nPASS"),
    ])
    assert extract_verdict_reason_from_transcript(p) == "bold form"


def test_reason_missing_returns_empty(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("just a verdict\nPASS"),
    ])
    assert extract_verdict_reason_from_transcript(p) == ""


def test_reason_missing_file() -> None:
    assert extract_verdict_reason_from_transcript(None) == ""


# ---------------------------------------------------------------------------
# latest_turn_state — the fresh-autostart implementation handoff signal
# ---------------------------------------------------------------------------

def _assistant_tool_line() -> str:
    return json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "editing"},
                        {"type": "tool_use", "id": "t1", "name": "Edit",
                         "input": {}}],
            "stop_reason": "tool_use",
        },
    })


def _meta_line(kind: str) -> str:
    return json.dumps({"type": kind, "message": {}})


def test_turn_state_missing_paths() -> None:
    assert latest_turn_state(None) == "unknown"
    assert latest_turn_state("/nonexistent/none.jsonl") == "unknown"


def test_turn_state_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    assert latest_turn_state(p) == "unknown"


def test_turn_state_complete_after_meta_records(tmp_path: Path) -> None:
    # Real transcripts append system/meta records after the final assistant
    # message; they are not turn boundaries.
    p = _write(tmp_path, [
        _user_line("do it"),
        _assistant_line("done"),
        _meta_line("system"),
        _meta_line("last-prompt"),
    ])
    assert latest_turn_state(p) == "complete"


def test_turn_state_ignores_local_command_records(tmp_path: Path) -> None:
    # A slash command (e.g. /model) left after the final assistant message is
    # a user-typed record but not a submitted prompt: it must not read as a
    # pending turn (which would stall the fresh-autostart handoff forever).
    p = _write(tmp_path, [
        _user_line("do it"),
        _assistant_line("done"),
        _local_command_line("<command-name>/model</command-name>"),
        _local_command_line("<local-command-stdout>Set model</local-command-stdout>"),
    ])
    assert latest_turn_state(p) == "complete"


def test_turn_state_ignores_task_notification_records(tmp_path: Path) -> None:
    # A background-task completion is injected as a user record after the
    # turn ended; it is not a prompt and must not look like pending work.
    p = _write(tmp_path, [
        _user_line("do it"),
        _assistant_line("done"),
        _local_command_line("<task-notification>\n<task-id>x</task-id>\n"
                            "</task-notification>"),
    ])
    assert latest_turn_state(p) == "complete"


def test_turn_state_ignores_meta_user_records(tmp_path: Path) -> None:
    meta = json.dumps({
        "type": "user", "isMeta": True,
        "message": {"role": "user", "content": "injected context"},
    })
    p = _write(tmp_path, [_user_line("do it"), _assistant_line("done"), meta])
    assert latest_turn_state(p) == "complete"


def test_turn_state_tool_use_block_is_in_progress(tmp_path: Path) -> None:
    p = _write(tmp_path, [_user_line("do it"), _assistant_tool_line()])
    assert latest_turn_state(p) == "in_progress"


def test_turn_state_tool_use_stop_reason_without_block(tmp_path: Path) -> None:
    rec = json.loads(_assistant_line("calling"))
    rec["message"]["stop_reason"] = "tool_use"
    p = _write(tmp_path, [_user_line("do it"), json.dumps(rec)])
    assert latest_turn_state(p) == "in_progress"


def test_turn_state_pending_user_record_is_in_progress(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("do it"),
        _assistant_line("done"),
        _user_line("one more thing"),
    ])
    assert latest_turn_state(p) == "in_progress"


def test_turn_state_large_final_record_is_found(tmp_path: Path) -> None:
    # A final assistant record larger than the first tail window must not
    # read as "unknown" (which would stall the handoff forever).
    big = "x" * (600 * 1024)
    p = _write(tmp_path, [_user_line("go"), _assistant_line(big)])
    assert latest_turn_state(p) == "complete"
