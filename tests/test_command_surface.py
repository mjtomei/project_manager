"""Command-surface consistency: help, corrective errors, and flags.

Covers pr-fa9f172:

* every command's ``--help`` renders, and each group lists its real
  (non-hidden) subcommands;
* the QA modes that exist in the TUI command bar are documented in
  ``pm pr qa --help`` (the motivating ``pr qa fresh`` discoverability miss);
* the command bar accepts ``--fresh`` / ``--loop`` as equivalents of the
  positional modes;
* key wrong-state errors name a corrective command;
* the stale ``plan=ux`` name is gone from the live code surface while
  ``tui-ux`` (a different, real plan) survives.
"""

from __future__ import annotations

import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from pm_core import command_surface
from pm_core.cli import HELP_TEXT, cli
from pm_core.cli.helpers import _require_plan, _require_pr
from pm_core.tui.pr_view import parse_qa_command


# ---------------------------------------------------------------------------
# Help completeness
# ---------------------------------------------------------------------------

def _help(*args: str) -> str:
    result = CliRunner().invoke(cli, [*args, "--help"])
    assert result.exit_code == 0, result.output
    return result.output


def test_pr_qa_help_lists_every_command_bar_mode():
    out = _help("pr", "qa")
    for token in ("fresh", "loop", "z t", "zz t", "--fresh", "--loop",
                  "pr qa fresh", "pr qa loop"):
        assert token in out, f"{token!r} missing from `pm pr qa --help`"
    # The CLI form is diagnostic; it must not claim to start the loop.
    assert "does not launch QA" in out


def test_pr_qa_help_points_at_the_single_instruction_interface():
    out = _help("pr", "qa")
    assert "pm qa run" in out


def test_pr_start_help_names_fresh_and_tui_keys():
    out = _help("pr", "start")
    assert "--fresh" in out
    for key in ("z s", "S", "companion"):
        assert key in out


def test_pr_review_help_names_fresh_and_loop_keys():
    out = _help("pr", "review")
    assert "--fresh" in out
    for key in ("z d", "zz d"):
        assert key in out


def test_pr_merge_help_names_tui_keys_and_no_fresh():
    out = _help("pr", "merge")
    assert "TUI" in out and "g" in out and "G" in out
    assert "no --fresh" in out


def test_pr_signoff_help_names_routed_form_and_record():
    out = _help("pr", "signoff")
    assert "--fresh" in out
    assert "record" in out and "integrate" in out


def _leaf_commands(cmd, path=()):
    if isinstance(cmd, click.Group):
        for name, sub in cmd.commands.items():
            yield from _leaf_commands(sub, (*path, name))
    else:
        yield path


def _groups(cmd, path=()):
    if isinstance(cmd, click.Group):
        yield path, cmd
        for name, sub in cmd.commands.items():
            yield from _groups(sub, (*path, name))


def test_every_command_help_renders():
    runner = CliRunner()
    for path in _leaf_commands(cli):
        result = runner.invoke(cli, [*path, "--help"])
        assert result.exit_code == 0, f"{path}: {result.output}\n{result.exception}"


def test_every_group_lists_its_visible_subcommands():
    runner = CliRunner()
    for path, group in _groups(cli):
        if not path:
            continue
        out = runner.invoke(cli, [*path, "--help"]).output
        for name, sub in group.commands.items():
            if getattr(sub, "hidden", False):
                continue
            assert name in out, f"{' '.join(path)} help omits {name!r}"


def test_top_level_help_lists_the_missing_lifecycle_commands():
    for command in ("pm pr merge", "pm pr qa", "pm pr auto-sequence",
                    "pm pr spec", "pm tui keys"):
        assert command in HELP_TEXT, f"{command!r} missing from HELP_TEXT"


def test_help_text_only_names_real_commands():
    """Every ``pm ...`` path in HELP_TEXT resolves in the Click tree.

    Resolution walks the whole command path, not just the first token, so a
    renamed or removed subcommand (``pm pr qa`` before it existed) fails here
    instead of merely shortening the resolved prefix.
    """
    for line in HELP_TEXT.splitlines():
        stripped = line.strip()
        if not stripped.startswith("pm "):
            continue
        toks = stripped.split()[1:]
        if not toks or toks[0].startswith("—"):
            continue
        cmd = cli
        resolved = []
        for tok in toks:
            tok = tok.split("|")[0]
            if isinstance(cmd, click.Group) and tok in cmd.commands:
                resolved.append(tok)
                cmd = cmd.commands[tok]
            else:
                # The path may stop at an argument placeholder, a flag, or
                # the capitalized description.  A lowercase word is a command
                # name that does not exist.
                is_stale = (tok[0] not in "<[-" and tok.isalpha()
                            and tok.islower())
                assert not is_stale, \
                    f"HELP_TEXT names an unknown command: {stripped!r}"
                break
        assert resolved, f"HELP_TEXT names an unknown command: {stripped!r}"


# ---------------------------------------------------------------------------
# Command bar
# ---------------------------------------------------------------------------

def test_command_surface_table_contains_qa_forms():
    text = command_surface.command_bar_help_text()
    for token in ("pr qa fresh", "pr qa loop", "z t", "zz t", "pr start",
                  "--fresh", "--loop"):
        assert token in text


def test_help_screen_lines_escape_textual_markup():
    lines = command_surface.command_bar_help_lines_textual()
    assert any("\\[--fresh]" in line for line in lines)
    assert not any(re.search(r"(?<!\\)\[", line) for line in lines), \
        "unescaped '[' would be parsed as Textual markup"


def test_tui_keys_matches_the_shared_table():
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    assert "Command bar (press /):" in out
    for token in ("pr qa fresh", "pr qa loop", "z t", "zz t", "pr merge",
                  "--fresh", "--loop"):
        assert token in out


@pytest.mark.parametrize("args,expected", [
    ([], (None, None)),
    (["pr-001"], (None, "pr-001")),
    (["fresh", "pr-001"], ("fresh", "pr-001")),
    (["pr-001", "--fresh"], ("fresh", "pr-001")),
    (["--fresh", "pr-001"], ("fresh", "pr-001")),
    (["--fresh"], ("fresh", None)),
    (["loop", "pr-001"], ("loop", "pr-001")),
    (["pr-001", "--loop"], ("loop", "pr-001")),
    (["--loop", "42"], ("loop", "42")),
])
def test_parse_qa_command_accepts_both_spellings(args, expected):
    assert parse_qa_command(args) == expected


def test_parser_accepts_every_documented_qa_mode():
    """The documented modes and the parser cannot drift apart.

    A mode added to the shared table must be accepted by the command bar
    (and vice versa: an undocumented spelling is rejected).
    """
    for mode, _form, _keys, _desc in command_surface.QA_MODES:
        if mode == "run":  # the plain form, not a modifier
            continue
        assert parse_qa_command([mode]) == (mode, None)
        assert parse_qa_command([f"--{mode}"]) == (mode, None)
    with pytest.raises(ValueError):
        parse_qa_command(["--resume", "pr-001"])


@pytest.mark.parametrize("args", [
    ["fresh", "loop", "pr-001"],
    ["--fresh", "--loop", "pr-001"],
    ["pr-001", "--frosh"],
    ["pr-001", "pr-002"],
])
def test_parse_qa_command_rejects_conflicts_and_typos(args):
    with pytest.raises(ValueError) as exc:
        parse_qa_command(args)
    assert "fresh" in str(exc.value) or "option" in str(exc.value)


# ---------------------------------------------------------------------------
# Corrective errors
# ---------------------------------------------------------------------------

def test_qa_already_running_names_the_restart_command():
    from pm_core.tui.qa_loop_ui import _qa_held_remedy, _qa_running_remedy

    running = _qa_running_remedy("pr-001")
    assert "pr qa fresh pr-001" in running
    assert "z t" in running
    held = _qa_held_remedy("pr-001")
    assert "pr qa fresh pr-001" in held and "zz t" in held


def test_require_pr_names_the_listing_command(capsys):
    with pytest.raises(SystemExit):
        _require_pr({"prs": [{"id": "pr-001"}]}, "pr-999")
    assert "pm pr list" in capsys.readouterr().err


def test_require_plan_names_the_listing_command(capsys):
    with pytest.raises(SystemExit):
        _require_plan({"plans": [{"id": "bugs"}]}, "nope")
    assert "pm plan list" in capsys.readouterr().err


def test_status_next_step_maps_lifecycle_order():
    from pm_core.cli.pr import _next_step_for_status

    assert "pm pr start pr-001" in _next_step_for_status("pr-001", "pending")
    assert "pm pr review pr-001" in _next_step_for_status("pr-001", "in_progress")
    assert "pm pr signoff pr-001" in _next_step_for_status("pr-001", "qa")
    assert "pm pr merge pr-001" in _next_step_for_status("pr-001", "sign_off")
    assert "pm pr show pr-001" in _next_step_for_status("pr-001", "merged")


# ---------------------------------------------------------------------------
# Plan-name reconciliation
# ---------------------------------------------------------------------------

def test_no_stale_ux_plan_name_in_code():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in (root / "pm_core").rglob("*.py"):
        text = path.read_text(errors="ignore")
        for match in re.finditer(r"\bux\b", text):
            line = text.count("\n", 0, match.start()) + 1
            context = text.splitlines()[line - 1]
            if "tui-ux" in context:
                continue
            offenders.append(f"{path.relative_to(root)}:{line}: {context.strip()}")
    assert not offenders, "stale plan=ux references:\n" + "\n".join(offenders)


def test_tui_ux_plan_is_not_rewritten():
    root = Path(__file__).resolve().parents[1]
    project = (root / "pm" / "project.yaml").read_text()
    assert "tui-ux" in project
    assert "plan=improvements" in (root / "pm_core" / "prompt_gen.py").read_text()
