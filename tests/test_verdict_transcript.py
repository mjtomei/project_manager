"""Tests for pm_core.verdict_transcript.extract_verdict_from_transcript."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pm_core.verdict_transcript import (
    extract_verdict_from_transcript,
    extract_verdict_reason_from_transcript,
)


VERDICTS = ("INPUT_REQUIRED", "NEEDS_WORK", "PASS")


def _assistant_line(text: str, *, uuid: str = "",
                    timestamp: str = "") -> str:
    rec = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }
    if uuid:
        rec["uuid"] = uuid
    if timestamp:
        rec["timestamp"] = timestamp
    return json.dumps(rec)


def _user_line(text: str, *, is_meta: bool = False) -> str:
    rec = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }
    if is_meta:
        rec["isMeta"] = True
    return json.dumps(rec)


def _tool_result_line() -> str:
    return json.dumps({
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "content": "ok"}],
        },
        "toolUseResult": {"stdout": "ok"},
    })


def _thinking_line(text: str) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "thinking", "thinking": text}],
        },
    })


def _tool_use_line(name: str, tool_input: dict) -> str:
    return json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_1", "name": name,
                        "input": tool_input}],
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
# pr-8efa789 — verdicts survive non-task wakeup turns
# ---------------------------------------------------------------------------

# Real shapes from the confirmed reproductions.
SCENARIO_44_VERDICT = (
    "CP3a verified with real review-pane evidence. CP3b verified. CP4 and CP5 "
    "were not exercisable in the available wall-time.\n"
    "Reason: CP4/CP5 could not be exercised in the available wall-time\n"
    "INPUT_REQUIRED"
)
SCENARIO_44_POSTSCRIPT = (
    "Scenario 44 is complete; verdict already submitted as INPUT_REQUIRED "
    "with captures pushed. No further work to do — ending the loop."
)
AUTONOMOUS_TICK = (
    "# Autonomous loop tick (dynamic pacing)\n\n"
    "Run the autonomous check using the loop instructions established "
    "earlier in this conversation. If you cannot find them, treat this as a "
    "no-op tick.\n\n"
    "You scheduled this tick via the ScheduleWakeup tool (not a recurring "
    "cron)."
)
MONITOR_EVENT = (
    "<task-notification>\n"
    "<task-id>bm7243e64</task-id>\n"
    '<summary>Monitor event: "QA scenario 71 background check"</summary>\n'
    "<event>captures pushed to the PR branch</event>\n"
    "</task-notification>"
)
SCHEDULED_TASK_WAKEUP = (
    "[SCHEDULED TASK - AUTOMATED FIRING OF A CONFIGURED PROMPT]\n"
    "This turn was started automatically by a schedule, not typed live by "
    "the user.\n\nYou are running QA scenario 44: drive the steps."
)


def test_verdict_survives_dynamic_loop_wakeup(tmp_path: Path) -> None:
    """Real scenario-44 replay: verdict, dynamic /loop tick, postscript."""
    p = _write(tmp_path, [
        _user_line('You are running QA scenario 44: "INPUT_REQUIRED gate"'),
        _assistant_line("Running the scenario steps..."),
        _assistant_line(SCENARIO_44_VERDICT, uuid="turn-verdict-44"),
        _user_line(AUTONOMOUS_TICK, is_meta=True),
        _assistant_line(SCENARIO_44_POSTSCRIPT, uuid="turn-postscript-44"),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "INPUT_REQUIRED"


def test_reason_comes_from_verdict_turn_not_postscript(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line(SCENARIO_44_VERDICT),
        _user_line(AUTONOMOUS_TICK, is_meta=True),
        _assistant_line(SCENARIO_44_POSTSCRIPT),
    ])
    assert extract_verdict_reason_from_transcript(p) == (
        "CP4/CP5 could not be exercised in the available wall-time"
    )


def test_verdict_survives_monitor_task_notification(tmp_path: Path) -> None:
    """#249 S71 replay: PASS, Monitor task-notification, postscript."""
    p = _write(tmp_path, [
        _user_line('You are running QA scenario 71: "Finalize close-out"'),
        _assistant_line("Reason: finalize pane showed FINALIZE_DONE\nPASS",
                        uuid="turn-verdict-71"),
        _user_line(MONITOR_EVENT),
        _assistant_line("Monitor reported the captures were pushed; nothing "
                        "else to do.", uuid="turn-postscript-71"),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"


def test_verdict_survives_fixed_interval_loop_delivery(tmp_path: Path) -> None:
    """A scheduled-task /loop delivery re-sends the task prompt, but it is an
    automated re-fire, not live user input — the verdict stays sticky."""
    p = _write(tmp_path, [
        _user_line("You are running QA scenario 44"),
        _assistant_line("Reason: steps done\nINPUT_REQUIRED"),
        _user_line(SCHEDULED_TASK_WAKEUP),
        _assistant_line("Already submitted INPUT_REQUIRED; ending the loop."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "INPUT_REQUIRED"


def test_newest_verdict_after_wakeup_wins(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("old\nINPUT_REQUIRED"),
        _user_line(AUTONOMOUS_TICK, is_meta=True),
        _assistant_line("Actually re-ran the steps.\nReason: fixed\nPASS"),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"
    assert extract_verdict_reason_from_transcript(p) == "fixed"


def test_verifier_feedback_supersedes_prior_verdict(tmp_path: Path) -> None:
    """The QA loop's verifier follow-up is a genuine re-evaluation request."""
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: all good\nPASS"),
        _user_line("Your verdict was reviewed and flagged: no runtime "
                   "evidence — Please re-evaluate this scenario."),
        _assistant_line("Looking at it again; no verdict yet."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_genuine_new_task_supersedes_prior_verdict(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: all good\nPASS"),
        _user_line("Now also check the finalize pane and report back."),
        _assistant_line("Working on the finalize pane; no verdict yet."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_retry_prompt_supersedes_prior_verdict(tmp_path: Path) -> None:
    """pr-6566901 re-sends the original prompt into the same session on a
    retry; that must not resurrect the earlier verdict."""
    p = _write(tmp_path, [
        _user_line("You are running QA scenario 44"),
        _assistant_line("Reason: partial\nNEEDS_WORK"),
        _user_line("You are running QA scenario 44"),
        _assistant_line("Re-running the steps; no verdict yet."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_stop_hook_feedback_is_a_barrier(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: done\nPASS"),
        _user_line("Stop hook feedback: you have uncommitted changes — "
                   "finish them before stopping.", is_meta=True),
        _assistant_line("Committing the remaining changes."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_tool_result_records_are_not_turn_barriers(tmp_path: Path) -> None:
    """A verdict in a non-final assistant text record of a tool-using turn is
    still found when later tool results and text follow it."""
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: verified live\nPASS"),
        _tool_result_line(),
        _assistant_line("Saving the capture manifest."),
        _tool_result_line(),
        _assistant_line("Done; no further commentary."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"


def test_system_reminder_only_record_is_transparent(tmp_path: Path) -> None:
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: done\nPASS"),
        _user_line("<system-reminder>\nAnother Claude session sent a "
                   "message while you were working.\n</system-reminder>"),
        _assistant_line("Acknowledged; nothing to add."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"


def test_find_verdict_turn_carries_identity(tmp_path: Path) -> None:
    from pm_core.verdict_transcript import find_verdict_turn

    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: verified\nPASS",
                        uuid="turn-verdict-1",
                        timestamp="2026-05-13T14:00:00.000Z"),
        _user_line(AUTONOMOUS_TICK, is_meta=True),
        _assistant_line(SCENARIO_44_POSTSCRIPT, uuid="turn-postscript-1"),
    ])
    hit = find_verdict_turn(p, VERDICTS)
    assert hit is not None
    assert hit.verdict == "PASS"
    assert hit.turn_id == "turn-verdict-1"
    assert hit.timestamp == "2026-05-13T14:00:00.000Z"
    assert "Reason: verified" in hit.text
    assert SCENARIO_44_POSTSCRIPT not in hit.text


def test_hit_text_covers_whole_verdict_turn(tmp_path: Path) -> None:
    """Markers written in an earlier record of the verdict's turn must be in
    ``hit.text``: poll_for_verdict callers (concretization, verification
    reasons) parse them out of the returned text."""
    from pm_core.loop_shared import extract_between_markers
    from pm_core.verdict_transcript import find_verdict_turn

    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("REFINED_STEPS_START\n1. run the scenario"),
        _assistant_line("REFINED_STEPS_END"),
    ])
    hit = find_verdict_turn(p, ("REFINED_STEPS_END", "REFINER_REJECT_END"))
    assert hit is not None
    assert extract_between_markers(
        hit.text, "REFINED_STEPS_START", "REFINED_STEPS_END") == (
            "1. run the scenario")
    # The turn walk must not cross the user record that opened it.
    assert "go" not in hit.text


def test_hit_text_keeps_turn_text_after_a_tool_result(tmp_path: Path) -> None:
    """A tool result inside the verdict's turn must not truncate ``hit.text``.

    Tool results belong to the assistant tool-use turn, so the text records
    written after them are still part of the same turn and must survive.
    """
    from pm_core.verdict_transcript import find_verdict_turn

    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: verified live\nPASS"),
        _tool_result_line(),
        _assistant_line("Captures pushed to the PR branch."),
    ])
    hit = find_verdict_turn(p, VERDICTS)
    assert hit is not None
    assert hit.verdict == "PASS"
    assert "Reason: verified live" in hit.text
    assert "Captures pushed to the PR branch." in hit.text
    # The turn walk must not cross the prompt that opened the turn.
    assert "go" not in hit.text


def test_hit_text_stops_at_a_wakeup_turn(tmp_path: Path) -> None:
    """Text after a non-task wakeup belongs to a later turn, not the
    verdict's — it must not be folded into ``hit.text``."""
    from pm_core.verdict_transcript import find_verdict_turn

    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: done\nPASS"),
        _tool_result_line(),
        _assistant_line("Captures pushed."),
        _user_line(AUTONOMOUS_TICK, is_meta=True),
        _assistant_line(SCENARIO_44_POSTSCRIPT),
    ])
    hit = find_verdict_turn(p, VERDICTS)
    assert hit is not None
    assert "Captures pushed." in hit.text
    assert SCENARIO_44_POSTSCRIPT not in hit.text


def test_extract_reason_from_text() -> None:
    from pm_core.verdict_transcript import extract_reason_from_text

    assert extract_reason_from_text(
        "Some text\nReason: first\nmore\n**Reason**: second\nPASS") == "second"
    assert extract_reason_from_text("") == ""
    assert extract_reason_from_text("no reason here") == ""


def test_compaction_summary_is_transparent(tmp_path: Path) -> None:
    """Claude Code appends a compaction summary as a plain user record; it
    must not hide a verdict emitted before compaction."""
    summary = json.dumps({
        "type": "user",
        "isCompactSummary": True,
        "message": {"role": "user", "content": [{
            "type": "text",
            "text": "This session is being continued from a previous "
                    "conversation that ran out of context. The summary "
                    "below covers the earlier portion of the conversation.",
        }]},
    })
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: done\nPASS"),
        summary,
        _assistant_line("Continuing after compaction; nothing to add."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"


def test_multiple_system_reminder_blocks_are_transparent(tmp_path: Path) -> None:
    """A record carrying several reminder blocks is a system notice, not a
    task boundary."""
    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: done\nPASS"),
        _user_line("<system-reminder>\nNotice one.\n</system-reminder>\n"
                   "<system-reminder>\nNotice two.\n</system-reminder>"),
        _assistant_line("Acknowledged; nothing to add."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) == "PASS"


def test_verdict_in_thinking_block_is_not_a_verdict(tmp_path: Path) -> None:
    """A keyword inside a thinking block is not visible output.

    The task-scoped scan reaches records the latest-turn scan never entered,
    so a thinking block that reasons about the verdict keyword must not be
    reported as the worker's verdict.
    """
    p = _write(tmp_path, [
        _user_line("go"),
        _thinking_line("The instructions want INPUT_REQUIRED when blocked.\n"
                       "INPUT_REQUIRED"),
        _assistant_line("Still working; no verdict yet."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_verdict_in_tool_use_input_is_not_a_verdict(tmp_path: Path) -> None:
    """A Grep pattern / written file containing the keyword is not a verdict.

    Real reproduction: a QA worker greps the worktree for ``INPUT_REQUIRED``
    and a later /loop wakeup postscript follows.  The task-scoped scan must
    not read the tool_use input as the verdict.
    """
    p = _write(tmp_path, [
        _user_line("You are running QA scenario 44"),
        _tool_use_line("Grep", {"pattern": "INPUT_REQUIRED", "path": "."}),
        _tool_result_line(),
        _assistant_line("The keyword only appears in the instructions."),
        _user_line(AUTONOMOUS_TICK, is_meta=True),
        _assistant_line("Still working on the scenario."),
    ])
    assert extract_verdict_from_transcript(p, VERDICTS) is None


def test_hit_text_contains_the_verdict_after_a_wakeup(tmp_path: Path) -> None:
    """``VerdictHit.text`` always carries the verdict.

    ``poll_for_verdict`` returns this text and callers re-parse it (e.g.
    ``parse_review_verdict``), so a hit whose text lacked the keyword would
    make the returned text disagree with the detected verdict.
    """
    from pm_core.verdict_transcript import find_verdict_turn

    p = _write(tmp_path, [
        _user_line("go"),
        _assistant_line("Reason: done\nPASS"),
        _user_line(AUTONOMOUS_TICK, is_meta=True),
        _assistant_line(SCENARIO_44_POSTSCRIPT),
    ])
    hit = find_verdict_turn(p, VERDICTS)
    assert hit is not None and hit.verdict == "PASS"
    assert "PASS" in hit.text.splitlines()
