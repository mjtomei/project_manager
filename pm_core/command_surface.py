"""Single source of truth for pm's command-bar / CLI / TUI equivalents.

Three surfaces render the tables below verbatim, so a new mode or
keybinding cannot be documented in one place and missed in another — the
failure this PR fixes (``pr qa fresh`` existed in the command bar but was
absent from ``pm pr qa --help``):

* ``pm pr qa --help`` (the QA modes table),
* the TUI ``?`` HelpScreen, and
* ``pm tui keys``.

``pm pr start/review/merge/signoff --help`` carry hand-written equivalent
blocks (their prose differs), and the same forms appear in their docstrings
— update those next to this table.

This module must not import from :mod:`pm_core.cli` or :mod:`pm_core.tui`:
both sides import it.
"""

from __future__ import annotations

# (mode, command-bar form, TUI keys, description)
QA_MODES: tuple[tuple[str, str, str, str], ...] = (
    ("run", "pr qa [PR_ID]", "t",
     "focus an existing run, or start one"),
    ("fresh", "pr qa fresh [PR_ID]", "z t",
     "fresh restart: stop and start over"),
    ("loop", "pr qa loop [PR_ID]", "zz t",
     "start or stop the repeating QA loop"),
)

# ``run`` is the plain form, not a modifier: the command bar does not accept
# a ``run`` token (nor ``--run``).  Both views are derived from ``QA_MODES``
# so a new mode reaches the command-bar parser, the CLI's positional-mode
# hint and the TUI-key lookup without a second list to drift.
QA_MODIFIER_MODES: tuple[str, ...] = tuple(
    mode for mode, *_rest in QA_MODES if mode != "run")
QA_MODE_KEYS: dict[str, str] = {
    mode: keys for mode, _form, keys, _desc in QA_MODES}
_QA_FLAGS: dict[str, str] = {
    f"--{mode}": mode for mode in QA_MODIFIER_MODES}


def parse_qa_command(args: list[str]) -> tuple[str | None, str | None]:
    """Parse ``pr qa`` arguments into ``(mode, pr_id)``.

    Accepts both spellings, anywhere in the argument list::

        pr qa fresh pr-001
        pr qa pr-001 --fresh
        pr qa --loop pr-001

    ``mode`` is ``None`` (plain one-shot run), ``"fresh"`` or ``"loop"``.
    Raises :class:`ValueError` with a corrective message for a conflicting
    mode or an unknown option — a typo must not silently start the wrong
    kind of run.

    Lives here, not in the TUI, because the CLI's popup spinner parses the
    same queued command to decide whether to wait for a rebuilt window
    (``fresh``/``loop`` kill and recreate it).  Both surfaces therefore
    accept exactly the modes the shared table documents.
    """
    mode: str | None = None
    pr_id: str | None = None
    for tok in args:
        if tok in _QA_FLAGS:
            candidate = _QA_FLAGS[tok]
        elif tok in QA_MODIFIER_MODES:
            candidate = tok
        elif tok.startswith("-"):
            raise ValueError(
                f"unknown QA option {tok!r} — use --fresh or --loop "
                f"(or the positional forms `fresh` / `loop`)")
        elif pr_id is None:
            pr_id = tok
            continue
        else:
            raise ValueError(
                f"unexpected extra argument {tok!r} — usage: "
                f"pr qa [fresh|loop] [PR_ID]")
        if mode is not None and mode != candidate:
            raise ValueError(
                f"conflicting QA modes {mode!r} and {candidate!r} — pick "
                f"one of `fresh` or `loop`")
        mode = candidate
    return mode, pr_id


# The command bar accepts either spelling for a QA mode, anywhere in the
# argument list.  Rendered next to the QA rows so `pm pr qa --help`,
# `pm tui keys` and the `?` HelpScreen all document the flag forms (the
# positional-only table would otherwise hide `pr qa <id> --fresh`).  Kept as
# short lines so a narrow terminal wraps cleanly.
QA_FLAG_NOTE_LINES: tuple[str, ...] = (
    "Flag spellings work anywhere:",
    "  pr qa <id> --fresh = pr qa fresh <id>",
    "  pr qa <id> --loop = pr qa loop <id>",
)

# The QA rows are derived from QA_MODES: the CLI form is always diagnostic
# only, so deriving keeps the two tables from drifting (the module's whole
# point).  A new QA mode added above shows up here automatically.
_QA_COMMAND_BAR_ROWS: tuple[tuple[str, str, str, str], ...] = tuple(
    (form, "pm pr qa [PR_ID] (diagnostic only)", keys, desc)
    for _mode, form, keys, desc in QA_MODES
)

COMMAND_BAR_HEADER: str = "Command bar (press /):"

# (command-bar form, CLI form, TUI keys, description)
COMMAND_BAR_COMMANDS: tuple[tuple[str, str, str, str], ...] = (
    ("pr start [--fresh] [--companion] [PR_ID]",
     "pm pr start [--fresh] [--companion] [PR_ID]",
     "s / z s / S / z S", "start implementation"),
    ("pr review [--fresh] [PR_ID]",
     "pm pr review [--fresh] [PR_ID]",
     "d / z d / zz d", "review; z d fresh, zz d loop"),
    *_QA_COMMAND_BAR_ROWS,
    ("pr merge [--companion] [PR_ID]",
     "pm pr merge [--companion] [PR_ID]",
     "g / G", "publish a signed-off PR"),
    ("pr signoff [--fresh] [PR_ID]",
     "pm pr signoff [--fresh] [PR_ID]",
     "i", "sign-off router (fresh: CLI/command bar only)"),
    ("review-loop [PR_ID]",
     "pm pr review --review-loop [PR_ID] (one iteration)",
     "zz d", "review loop (TUI-driven)"),
    ("edit [PR_ID]",
     "pm pr edit PR_ID",
     "e / Enter", "edit PR details"),
    ("autostart add|remove|list|status|clear …",
     "pm autostart …",
     "O add / A toggle / a runs", "auto-start targets and runs"),
    ("plan add <name>",
     "pm plan add <name>",
     "p then a", "add a plan"),
    # The command bar runs the sub-command directly: typing `pm pr list`
    # would pass "pm" to the wrapper and fail ("No such command 'pm'"), so
    # the command-bar form must not carry the `pm` prefix.
    ("<command> [args]",
     "pm <command> [args]",
     "—", "everything else runs through the CLI"),
)


def escape_markup(text: str) -> str:
    """Escape every ``[`` so Textual renders a literal bracket.

    Textual's own ``escape`` (and rich's) only escapes a bracket that opens
    a markup tag it recognises, so ``[PR_ID]`` and ``[--fresh]`` slip
    through and are swallowed as (invalid) tags.  Replace every ``[``:
    Textual renders ``\\[`` as a literal bracket in every case.  A trailing
    backslash gets a space so it cannot escape a tag that follows.
    """
    text = text.replace("[", "\\[")
    return text + " " if text.endswith("\\") else text


def qa_mode_lines(*, indent: str = "  ") -> list[str]:
    """Render the QA modes as one line each (command bar + TUI key)."""
    return [f"{indent}{form:<26} = TUI {keys:<5}  {desc}"
            for _mode, form, keys, desc in QA_MODES]


def command_bar_lines(*, textual: bool = False, indent: str = "  ") -> list[str]:
    """Render the command-bar / CLI / TUI equivalence table.

    Two lines per command keeps the table readable in a narrow terminal:
    the form and what it does, then the CLI and TUI equivalents.
    """
    lines = []
    for form, cli, keys, desc in COMMAND_BAR_COMMANDS:
        head = f"{indent}{form}  — {desc}"
        detail = f"{indent}    CLI: {cli}   TUI: {keys}"
        if textual:
            head = escape_markup(head)
            detail = escape_markup(detail)
        lines.extend([head, detail])
    return lines


def _flag_note_lines(indent: str, *, textual: bool = False) -> list[str]:
    lines = [f"{indent}{line}" for line in QA_FLAG_NOTE_LINES]
    return [escape_markup(line) for line in lines] if textual else lines


def qa_help_table() -> str:
    """The QA modes block embedded in ``pm pr qa --help``.

    No blank line between the table and the note: this fragment lives inside
    a Click ``\\b`` block, and a blank line would end the block, so Click
    would re-wrap (and mangle) the note's aligned lines.
    """
    return "\n".join([*qa_mode_lines(indent="    "),
                      *_flag_note_lines("    ")])


def command_bar_help_text() -> str:
    """The command-bar section for ``pm tui keys`` (plain text)."""
    return "\n".join([COMMAND_BAR_HEADER, *command_bar_lines(indent="  "), "",
                      *_flag_note_lines("  ")])


def command_bar_help_lines_textual() -> list[str]:
    """The command-bar section for the TUI ``?`` HelpScreen (escaped markup)."""
    return [COMMAND_BAR_HEADER,
            *command_bar_lines(textual=True, indent="  "),
            "",
            *_flag_note_lines("  ", textual=True)]
