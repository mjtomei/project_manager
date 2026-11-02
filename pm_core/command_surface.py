"""Single source of truth for pm's command-bar / CLI / TUI equivalents.

Three surfaces document the same actions:

* ``pm <command> --help`` (Click),
* the TUI ``?`` HelpScreen, and
* ``pm tui keys``.

They all render from the tables below so a new mode or keybinding cannot be
documented in one place and missed in another — the failure this PR fixes
(``pr qa fresh`` existed in the command bar but was absent from
``pm pr qa --help``).

This module must not import from :mod:`pm_core.cli` or :mod:`pm_core.tui`:
both sides import it.
"""

from __future__ import annotations

# (mode, command-bar form, TUI keys, description)
QA_MODES: tuple[tuple[str, str, str, str], ...] = (
    ("run", "pr qa [PR_ID]", "t",
     "focus an existing run, or start one"),
    ("fresh", "pr qa fresh [PR_ID]", "z t",
     "fresh restart: stop, kill old windows, start over"),
    ("loop", "pr qa loop [PR_ID]", "zz t",
     "start or stop the repeating QA loop"),
)

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

# (command-bar form, CLI form, TUI keys, description)
COMMAND_BAR_COMMANDS: tuple[tuple[str, str, str, str], ...] = (
    ("pr start [--fresh] [--companion] [PR_ID]",
     "pm pr start [--fresh] [--companion] [PR_ID]",
     "s / z s / S / z S", "start implementation"),
    ("pr review [--fresh] [PR_ID]",
     "pm pr review [--fresh] [PR_ID]",
     "d / z d / zz d", "review; z d fresh, zz d loop"),
    *_QA_COMMAND_BAR_ROWS,
    ("pr merge [PR_ID]",
     "pm pr merge [PR_ID]",
     "g / G", "publish a signed-off PR"),
    ("pr signoff [--fresh] [PR_ID]",
     "pm pr signoff [--fresh] [PR_ID]",
     "i", "sign-off router"),
    ("review-loop [PR_ID]",
     "(TUI only)",
     "zz d", "review loop"),
    ("edit [PR_ID]",
     "pm pr edit PR_ID",
     "e / Enter", "edit PR details"),
    ("autostart add|remove|list|status|clear …",
     "pm autostart …",
     "O / A / a", "auto-start targets and runs"),
    ("plan add <name>",
     "pm plan add <name>",
     "p then a", "add a plan"),
    ("<any pm command>",
     "pm <command>",
     "—", "everything else runs through the CLI"),
)


def _escape_markup(text: str) -> str:
    """Escape ``[`` so Textual renders a literal bracket (for ``[--fresh]``)."""
    return text.replace("[", "\\[")


def qa_mode_lines(*, textual: bool = False, indent: str = "  ") -> list[str]:
    """Render the QA modes as one line each (command bar + TUI key)."""
    lines = []
    for _mode, form, keys, desc in QA_MODES:
        line = f"{indent}{form:<26} = TUI {keys:<5}  {desc}"
        lines.append(_escape_markup(line) if textual else line)
    return lines


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
            head = _escape_markup(head)
            detail = _escape_markup(detail)
        lines.extend([head, detail])
    return lines


def _flag_note_lines(indent: str, *, textual: bool = False) -> list[str]:
    lines = [f"{indent}{line}" for line in QA_FLAG_NOTE_LINES]
    return [_escape_markup(line) for line in lines] if textual else lines


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
    header = "Command bar (press /):"
    return "\n".join([header, *command_bar_lines(indent="  "), "",
                      *_flag_note_lines("  ")])


def command_bar_help_lines_textual() -> list[str]:
    """The command-bar section for the TUI ``?`` HelpScreen (escaped markup)."""
    return [command_bar_help_text().splitlines()[0],
            *command_bar_lines(textual=True, indent="  "),
            "",
            *_flag_note_lines("  ", textual=True)]
