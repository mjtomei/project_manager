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
from pm_core.command_surface import parse_qa_command


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


def test_pr_qa_help_states_the_always_nonzero_exit():
    """`pm pr qa` exits 1 even on the valid path — it performs no action.

    A driving Claude session that reads the exit status as failure will
    retry or work around the command, which is exactly the failure this PR
    fixes.  The help must say so.
    """
    out = " ".join(_help("pr", "qa").split())
    assert "exits 1 even when the PR is valid" in out


def test_pr_qa_help_states_the_cli_has_no_fresh_flag():
    """The absence of `--fresh` on the CLI must read as deliberate.

    The command bar accepts `pr qa <id> --fresh`; the CLI is diagnostic
    only.  Without this line an operator types `pm pr qa <id> --fresh` and
    gets a bare Click "no such option" error.
    """
    out = _help("pr", "qa")
    assert "no --fresh or --loop flag" in out


def test_pr_edit_help_names_every_field_it_edits():
    """`pm pr edit` edits more than the summary used to admit.

    The docstring said "title, description, dependencies, or status" while
    the command also takes `--plan` and, with no options, opens the
    interactive editor the TUI's `e` / Enter uses.  A complete-help sweep
    must not hide a field behind its own summary.
    """
    out = " ".join(_help("pr", "edit").split()).lower()
    for token in ("title", "description", "dependencies", "status", "plan",
                  "interactive editor"):
        assert token in out, f"{token!r} missing from `pm pr edit --help`"
    # The summary line itself, not just the options table.
    assert "edit an existing pr: title" in out


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


def test_pr_review_help_does_not_call_zz_d_a_toggle():
    """`zz d` always starts a fresh loop; it does not stop one.

    ``start_or_stop_loop``'s own docstring says the toggle behaviour was
    removed (a running loop is superseded, not merely stopped), but the new
    equivalent-forms block advertised "start/stop" — a claim the code
    contradicts, in a help surface this PR added.
    """
    out = " ".join(_help("pr", "review").split())
    assert "zz d start/stop" not in out
    assert "zz d start the review loop" in out


def test_pr_merge_help_names_tui_keys_and_no_fresh():
    out = _help("pr", "merge")
    assert "TUI" in out and "g" in out and "G" in out
    assert "no --fresh" in out
    # The companion flag is real and belongs in the equivalent-forms line.
    assert "pm pr merge [--companion] [PR_ID]" in out


def test_pr_merge_help_names_the_real_retry_path():
    """A refusal invalidates the approval; re-running merge alone cannot work.

    The help used to say "Re-run `pm pr merge` to retry", which contradicts
    the sentence before it ("returning the PR to sign-off"): after a refusal
    the gate has no valid approval, so the next step is a fresh sign-off.
    """
    out = " ".join(_help("pr", "merge").split())
    assert "pm pr signoff --fresh <id>" in out
    assert "Re-run `pm pr merge` to retry" not in out


def test_pr_signoff_help_names_routed_form_and_record():
    out = _help("pr", "signoff")
    assert "--fresh" in out
    assert "record" in out and "integrate" in out
    # The main-tree `i` is the router (focus-or-open).  A fresh sign-off is
    # the PR action picker's `z i` chord — the picker header advertises
    # "i=fresh signoff" — so the help must name that route, not claim the
    # TUI cannot do one.
    assert "no TUI key" not in out
    assert "fresh restart is CLI/command-bar only" not in out
    flat = " ".join(out.split())
    assert "z i" in flat and "prefix P" in flat


def test_pr_merge_help_names_the_picker_fresh_signoff_chord():
    """A refused merge needs a fresh sign-off; the picker can do one.

    The help used to say "there is no fresh-restart key", but the PR action
    picker (prefix P) maps `z i` to `pr signoff --fresh`.  Sending the
    operator to the CLI only hid a working TUI route.
    """
    flat = " ".join(_help("pr", "merge").split())
    assert "z i" in flat and "prefix P" in flat
    assert "no fresh-restart key" not in flat
    # Pin the claim to the code it describes: the picker's z chord really
    # maps the sign-off key to `--fresh`.
    from pm_core.cli.session import _MODIFIED_ACTION_CMDS
    assert _MODIFIED_ACTION_CMDS[("z", "signoff")] == \
        "pr signoff --fresh {pr_id}"


def test_cli_merge_deliberately_rejects_fresh():
    """`--fresh` is meaningless for merge (there is no session to restart).

    The help says so; this asserts the CLI really has no such option, so the
    documented absence cannot silently become a supported flag.
    """
    result = CliRunner().invoke(cli, ["pr", "merge", "--fresh"])
    assert result.exit_code != 0, result.output
    assert "No such option" in result.output, result.output


@pytest.mark.parametrize("mode", command_surface.QA_MODIFIER_MODES)
def test_pr_qa_cli_flag_spelling_gets_the_same_hint(tmp_path, mode):
    """`pm pr qa <id> --fresh` is a command-bar spelling with the flag.

    The positional spellings already reach ``pr_qa``'s corrective hint; the
    flag spelling — the one the PR description asks to accept everywhere, and
    the one a driving Claude session is most likely to guess — still died on
    Click's ``No such option '--fresh'`` (exit 2).  It must reach the same
    hint naming the command-bar form and TUI key, in either position, and
    must not run QA.
    """
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\nprs: []\n")
    flag = f"--{mode}"
    for args in (["qa", flag], ["qa", flag, "pr-001"],
                 ["qa", "pr-001", flag]):
        with mock.patch.object(pr_mod, "state_root", return_value=tmp_path):
            result = CliRunner().invoke(pr_mod.pr, args)
        assert result.exit_code == 1, (args, result.output)
        assert "No such option" not in result.output, (args, result.output)
        assert "command bar" in result.output, (args, result.output)
        assert f"pr qa {mode} <id>" in result.output, (args, result.output)
        assert command_surface.QA_MODE_KEYS[mode] in result.output, (
            args, result.output)


def test_pr_qa_flag_spelling_does_not_swallow_help():
    """`--fresh` must not turn `pm pr qa --fresh --help` into an error.

    Help wins: the flag is dropped so Click renders the help, which states
    outright that the CLI has no ``--fresh``.
    """
    out = _help("pr", "qa", "--fresh")
    assert "QA modes" in out
    assert "no --fresh or --loop flag" in " ".join(out.split())


@pytest.mark.parametrize("name", ["start", "review", "merge", "signoff"])
def test_lifecycle_help_matches_the_shared_table(name):
    """The hand-written equivalent blocks and the shared table agree.

    start/review/merge/signoff prose differs, so those blocks are not
    generated from ``command_surface``; this is the drift guard for them
    (it would have caught merge's missing ``[--companion]``).  The
    expected form is read from the table, not retyped here.
    """
    cli_form = next(
        cli for form, cli, _keys, _desc in command_surface.COMMAND_BAR_COMMANDS
        if form.startswith(f"pr {name} "))
    assert cli_form in " ".join(_help("pr", name).split())


def test_pr_signoff_accepts_the_help_alias():
    """`pm pr signoff help` shows help like every other command.

    `_SignoffGroup` routes an unknown first token to `run` as a PR id, so
    before this it answered "PR 'help' not found." — the one group where
    the documented `pm <cmd> help` alias did not work.
    """
    result = CliRunner().invoke(cli, ["pr", "signoff", "help"])
    assert result.exit_code == 0, result.output
    assert "Sign-off: PR-level review" in result.output


def test_every_group_accepts_the_help_alias():
    """`pm <group> help` must work on every group, not just most.

    ``HelpGroup`` is inherited by groups created with ``@<parent>.group``,
    but a group defined standalone and attached with ``cli.add_command``
    (``pm project``, ``pm model``) used the plain ``click.Group`` and
    answered "No such command 'help'".  The alias is documented as working
    everywhere, so this walks every group in the tree.
    """
    runner = CliRunner()
    for path, _group in _groups(cli):
        # The root group has a real `help` command (it prints HELP_TEXT,
        # which has no "Usage:" line); every other group uses the alias.
        if not path:
            continue
        result = runner.invoke(cli, [*path, "help"])
        assert result.exit_code == 0, (
            f"`pm {' '.join([*path, 'help'])}` failed: {result.output}")
        assert "Usage:" in result.output


def test_help_alias_does_not_depend_on_the_click_option_restart(monkeypatch):
    """The `help` alias renders help itself, on every supported Click.

    Rewriting ``help`` to ``--help`` and letting ``resolve_command`` retry
    only works on Click >= 8.2: earlier versions restart option parsing from
    ``ctx.args`` (still holding the original ``help`` token), so the flag is
    lost and the command dies with "No such command '--help'".  Click 8.1.x
    is inside the ``click>=8.0`` range this project declares, so the alias
    must not reach the version-specific retry at all.

    The stand-in below is Click 8.1's ``Group.resolve_command``: it differs
    from 8.4's only in re-parsing ``ctx.args`` instead of the rewritten
    ``args``.
    """

    def resolve_command_81(self, ctx, args):
        cmd_name = args[0]
        cmd = self.get_command(ctx, cmd_name)
        if cmd is None and ctx.token_normalize_func is not None:
            cmd_name = ctx.token_normalize_func(cmd_name)
            cmd = self.get_command(ctx, cmd_name)
        if cmd is None and not ctx.resilient_parsing:
            if cmd_name.startswith("-"):
                self.parse_args(ctx, ctx.args)  # Click 8.1 passes ctx.args
            ctx.fail(f"No such command {cmd_name!r}.")
        return cmd_name if cmd else None, cmd, args[1:]

    monkeypatch.setattr(click.Group, "resolve_command", resolve_command_81)
    result = CliRunner().invoke(cli, ["pr", "signoff", "help"])
    assert result.exit_code == 0, result.output
    assert "Sign-off: PR-level review" in result.output


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


def test_top_level_help_names_the_tui_driving_commands():
    """A driving session's own interface is in the summary, not only prompts.

    The injected prompts tell a Claude session to act through `pm tui send`
    (and read the screen with `pm tui view`), but `pm help` listed neither,
    so the operator reading the summary could not find the mechanism.
    """
    for command in ("pm tui view", "pm tui send"):
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
            # ``pm session home|kill|mobile|name|tag`` names several
            # subcommands; every alternative must exist, not just the first
            # (a stale ``kill`` behind a live ``home`` used to pass).
            parts = tok.split("|")
            if isinstance(cmd, click.Group) and parts[0] in cmd.commands:
                unknown = [p for p in parts if p not in cmd.commands]
                assert not unknown, (
                    f"HELP_TEXT names unknown subcommand(s) {unknown}: "
                    f"{stripped!r}")
                resolved.extend(parts)
                cmd = cmd.commands[parts[0]]
                continue
            # The path may stop at an argument placeholder (`<x>`, `[x]`), a
            # flag (`--x`), or the capitalized description.  Anything else is
            # a command name and must have resolved above.  Checking the
            # first character (not ``isalpha()``) covers hyphenated names
            # such as ``auto-sequence`` / ``fake-claude`` / ``spec-approve``,
            # which a lowercase-only test silently skipped.
            if parts[0][0] in "<[-" or parts[0][0].isupper():
                break
            raise AssertionError(
                f"HELP_TEXT names an unknown command: {stripped!r}")
        assert resolved, f"HELP_TEXT names an unknown command: {stripped!r}"


# ---------------------------------------------------------------------------
# Command bar
# ---------------------------------------------------------------------------

def test_command_surface_table_contains_qa_forms():
    text = command_surface.command_bar_help_text()
    for token in ("pr qa fresh", "pr qa loop", "z t", "zz t", "pr start",
                  "--fresh", "--loop"):
        assert token in text


def test_command_bar_forms_carry_no_pm_prefix():
    """The command bar runs the sub-command directly.

    ``run_command`` invokes ``pm_core.wrapper`` with the typed tokens as
    argv, so a leading ``pm`` is passed through as a subcommand and fails
    ("No such command 'pm'").  The table's command-bar column must therefore
    never spell a form ``pm ...`` — that is the CLI column.
    """
    for form, _cli, _keys, _desc in command_surface.COMMAND_BAR_COMMANDS:
        assert not form.startswith("pm "), form
    # The catch-all row says the prefix is dropped, not repeated.
    assert any(form == "<command> [args]"
               for form, *_rest in command_surface.COMMAND_BAR_COMMANDS)


def test_getting_started_plan_keys_match_the_plans_pane():
    """The getting-started block must name keys the plans pane accepts.

    ``PlansPane`` binds a/w/c/l/e/D; ``v`` is *blocked* in the plans view
    (``check_action``) and ``Enter`` opens the plan file.  The block used to
    say ``v=view`` and omit ``D``, so the help named a key that does nothing
    and hid one that does.
    """
    from pm_core.cli import _getting_started_text

    # The plan-key block is unconditional; stub repo detection so the test
    # does not shell out to git or depend on the cwd being a repo.
    import pm_core.cli as cli_mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli_mod, "_detect_git_repo", lambda: None)
        text = " ".join(_getting_started_text().split())
    assert "Enter=view file" in text
    assert "D=deps" in text
    assert "v=view" not in text


def test_help_does_not_claim_session_starts_a_notes_editor():
    """`pm session` no longer starts the notes pane.

    ``_session_start`` says so explicitly ("Notes pane is no longer
    auto-started — press ``n`` in the TUI"), yet both the top-level summary
    and the getting-started guide still promised "TUI + notes editor".  A
    help sweep that leaves the session description advertising a pane it no
    longer opens sends the operator looking for something that is not
    there.  The accurate pointer is the ``n`` key (documented by
    ``pm tui keys`` as "Open notes").
    """
    from pm_core.cli import HELP_TEXT, _getting_started_text
    import pm_core.cli as cli_mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli_mod, "_detect_git_repo", lambda: None)
        getting_started = " ".join(_getting_started_text().split())

    for text in (HELP_TEXT, getting_started):
        assert "notes editor" not in text
    assert "n opens notes" in HELP_TEXT
    assert "press n" in getting_started
    # The notes pane is still reachable and documented.
    keys = CliRunner().invoke(cli, ["tui", "keys"]).output
    assert re.search(r"^\s*n\s{2,}Open notes", keys, re.M)


def test_help_screen_lines_escape_textual_markup():
    lines = command_surface.command_bar_rows_textual()
    assert any("\\[--fresh]" in line for line in lines)
    assert not any(re.search(r"(?<!\\)\[", line) for line in lines), \
        "unescaped '[' would be parsed as Textual markup"


def _render_help_screen(**kwargs) -> str:
    """Render the `?` screen and return its text, whitespace-normalized."""
    import asyncio

    from textual.app import App

    from pm_core.tui.screens import HelpScreen

    class _HelpApp(App):
        CSS = HelpScreen.CSS

        def on_mount(self) -> None:
            self.push_screen(HelpScreen(**kwargs))

    async def render() -> str:
        app = _HelpApp()
        async with app.run_test(size=(80, 50)) as pilot:
            await pilot.pause()
            chunks = []
            for label in app.screen.query("#help-container Label"):
                lines = [label.render_line(i).text
                         for i in range(label.region.height)]
                chunks.append(" ".join(lines))
            return re.sub(r"\s+", " ", " ".join(chunks))

    return asyncio.run(render())


def test_help_screen_renders_the_whole_command_bar_section():
    """The `?` screen must not clip the half that matters.

    ``.help-row`` used to be one line tall with a natural (overflowing)
    width, so every row was cut at the 50-column container — exactly where
    the CLI/TUI equivalents start.  The rows now wrap; assert the rendered
    text (whitespace-normalized, since wrapping breaks lines at spaces)
    contains the ends of the longest rows.
    """
    text = _render_help_screen()
    for tail in (
        # command-bar table, second line of the longest rows
        "TUI: s / z s / S / z S",
        "TUI: zz t",
        "CLI: pm pr merge [--companion] [PR_ID] TUI: g / G",
        "pr qa <id> --loop = pr qa loop <id>",
        # rows this PR lengthened in the keybinding list
        "Watcher prefix: ww list, wf focus, ws start/stop, wr review",
        "Cleanup, then: ys start, yd review, yt QA",
        # z modifies every pane action, not just s/S/d/t (incl. the `wr`
        # watcher-review chord)
        "s S d t e v n L H c, wr; zz d / zz t: loop",
        # the one App binding neither surface listed before
        "Reload state from disk (no sync)",
        # the PR-action rows now carry the same modifier keys as
        # `pm tui keys` (they had drifted: `d` named only `zz d`, `s`/`g`
        # named no modifier, and `Y` was missing)
        "Start selected PR (z s: fresh, S: companion)",
        "Review (z d: fresh, zz d: loop)",
        "Merge PR (G: companion pane)",
        "Cleanup PR workdir",
    ):
        assert tail in text, f"{tail!r} clipped from the ? screen"


_TREE_ONLY_HELP_ROWS = (
    "Start QA on selected PR",
    "Launch Claude session",
    "Start PR with companion pane",
    "Merge with companion pane",
    # The loop chords run the same tree-view actions (`review_pr` /
    # `start_qa_on_pr`).  In the QA view `d` is intercepted as "debug item",
    # so `zz d` there debugs instead of starting a loop.
    "Start loop",
    "Start QA loop",
    # `z` modifies those same pane actions; in the alternate views most are
    # blocked or intercepted by the focused pane.
    "Prefix: restart the pane",
)


def test_help_screen_lists_tree_only_actions_in_the_tree_view():
    text = _render_help_screen()
    for row in _TREE_ONLY_HELP_ROWS:
        assert row in text, f"{row!r} missing from the tree-view ? screen"


@pytest.mark.parametrize("kwargs, kept", [
    ({"in_plans": True}, "Toggle plans view"),
    ({"in_qa": True}, "Toggle QA library view"),
])
def test_help_screen_omits_actions_blocked_in_that_view(kwargs, kept):
    """The `?` screen must not name keys the current view ignores.

    `check_action` blocks `t` (start_qa_on_pr), `S`/`G`
    (start/merge companion) and `c` (launch_claude) in both the plans and
    QA views, and the loop chords (`zz d` / `zz t`) drive the same blocked
    tree actions — in the QA view `d` is even intercepted as "debug item".
    A context-sensitive help screen that still lists them sends the
    operator to a key that does nothing (or, for `zz d` in QA, the wrong
    thing).  Only `c` was guarded before (and only for the plans view).
    """
    text = _render_help_screen(**kwargs)
    for blocked in _TREE_ONLY_HELP_ROWS:
        assert blocked not in text, f"{blocked!r} listed in {kwargs}"
    assert kept in text


def test_tui_keys_enter_names_the_qa_view_action():
    """`pm tui keys` must cover Enter in the QA view too.

    Enter edits the selected PR in the tree, opens the plan file in the
    plans view, and runs the selected item in the QA view; naming only the
    first two left the QA view undocumented.
    """
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    flat = " ".join(out.split())
    assert "plans view: view plan file" in flat
    assert "QA view: run item" in flat


def test_tui_keys_documents_the_plans_and_qa_views():
    """`pm tui keys` covers the keys of both alternate views.

    The `?` screen has Plans/QA sections; `pm tui keys` listed only the
    toggle keys (`p`, `q`), so an operator inside either view had no
    reference for the keys that work there.  `d` (debug) in the QA view was
    also missing from the `?` screen even though the status bar names it.
    """
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    assert "Plans view (p):" in out and "QA view (q):" in out
    plans_block = out.split("Plans view (p):", 1)[1].split("QA view (q):", 1)[0]
    for key in ("Enter", "a", "e", "w", "c", "l", "D", "p"):
        assert re.search(rf"^\s*{re.escape(key)}\s{{2,}}\S", plans_block, re.M), (
            f"plans-view key {key!r} missing from `pm tui keys`")
    qa_block = out.split("QA view (q):", 1)[1].split("Tmux prefix bindings:", 1)[0]
    for key in ("Enter", "e", "d", "a", "q"):
        assert re.search(rf"^\s*{re.escape(key)}\s{{2,}}\S", qa_block, re.M), (
            f"QA-view key {key!r} missing from `pm tui keys`")


def test_help_screen_qa_view_lists_the_debug_key():
    text = _render_help_screen(in_qa=True)
    for row in ("Run selected item", "Edit item", "Debug item",
                "Add instruction"):
        assert row in text


def test_tui_keys_matches_the_shared_table():
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    assert "Command bar (press /):" in out
    for token in ("pr qa fresh", "pr qa loop", "z t", "zz t", "pr merge",
                  "--fresh", "--loop"):
        assert token in out
    # Master's #136/#284 surface is part of the command bar too.  These
    # arrived with the base merge and were missing from the shared table and
    # `pm tui keys` until the merge reconciliation added them (the parity
    # test used a hand list, so nothing caught it).
    for token in ("pr select <query>", "plan select <query>",
                  "qa regression <test-id>", "] / [ cycle matches"):
        assert token in out, token
    assert "] / [            Cycle fuzzy match results" in out
    # ... and the `?` screen renders the same rows from the shared table.
    rows = " ".join(command_surface.command_bar_rows_textual())
    for token in ("pr select", "plan select", "qa regression"):
        assert token in rows, token


def test_tui_keys_lists_every_binding_the_help_screen_shows():
    """`pm tui keys` was a strict subset of the `?` screen.

    Both are help surfaces; a direct binding listed in one and missing from
    the other is the drift this PR exists to stop.  (The `?` screen is
    context-sensitive, so compare bindings, not layout.)
    """
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    for binding in ("x", "X", "f", "F", "v", "M", "H", "m", "C", "/",
                    "z", "R", "ctrl+r", "prefix P", "prefix M", "prefix R",
                    "h"):
        assert re.search(rf"^\s*{re.escape(binding)}\s{{2,}}\S", out, re.M), (
            f"{binding!r} missing from `pm tui keys`")
    # The `?` screen's own bindings were documented only in its footer; the
    # CLI reference now carries them too.
    assert "Help screen (?):" in out
    assert "Discuss pm" in out


def test_tui_keys_documents_prefix_keys_as_prefixes():
    """`w` and `y` are prefixes, not direct bindings.

    `w` alone only arms the watcher prefix (`wf` focuses); saying
    "w — Focus watcher window" would send an operator pressing `w` to a
    hint line instead of the action.
    """
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    assert "Focus watcher window" not in out
    for token in ("Watcher prefix:", "wf focus", "ww list", "wr review"):
        assert token in out
    assert "ys start" in out and "yd review" in out and "yt QA" in out


def test_picker_chord_help_names_the_fzf_requirement():
    """The picker's z/zz chords exist only in the fzf picker.

    Without fzf the PR action picker falls back to a numbered line menu
    that has no chord handling (a `z` press is not a shortcut and closes
    the popup).  Both help surfaces documented the chords unconditionally,
    so an operator without fzf was sent to a key that does not exist there
    — the same class of claim-versus-code drift this PR sweeps.
    """
    flat = " ".join(CliRunner().invoke(cli, ["tui", "keys"]).output.split())
    assert "z s/d/t/i fresh zz d/t loop (requires fzf" in flat
    assert "z s/d/t/i fresh, zz d/t loop — requires fzf" in _render_help_screen()


def test_z_prefix_names_every_action_it_modifies():
    """`z` is not limited to s/S/d/t.

    ``_consume_z`` is also read by ``edit_plan``, ``view_plan``,
    ``launch_notes``, ``view_log``, ``launch_guide``, ``launch_claude`` and
    ``launch_watcher_review`` (the ``wr`` chord), so a row naming only
    s/S/d/t (as this sweep first wrote it) both hides working chords and
    misstates the prefix.  ``m`` consumes ``z`` but does not support a
    fresh restart, so it must not be named.
    """
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    assert "(s S d t e v n L H c, wr; zz d / zz t: loop)" in out
    assert "Prefix before s/S/d/t:" not in out


def test_tui_keys_documents_enter_as_edit():
    """Enter opens the edit screen, as the `?` screen says.

    Selection is the cursor; the old "Select/expand PR" line described a
    behaviour that does not exist (``TechTree`` posts PRSelected then calls
    ``action_edit_plan``), so the two help surfaces disagreed.
    """
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    assert re.search(r"^\s*Enter\s{2,}Edit selected PR", out, re.M)
    assert "Select/expand" not in out


@pytest.mark.parametrize("cmd", ["help", "?", "commands", "command bar",
                                 "command-bar", "help pr"])
def test_command_bar_help_opens_the_help_screen(cmd):
    """`help` in the command bar shows the screen, not one truncated line.

    Before this the command shelled out to `pm help`, whose multi-line
    output the command bar displays as a single (last) line — no help.
    """
    from types import SimpleNamespace

    from pm_core.tui import pr_view

    shown = []
    app = SimpleNamespace(action_show_help=lambda: shown.append(True),
                          action_unfocus_command=lambda: None,
                          log_message=lambda *a, **k: None)
    pr_view.handle_command_submitted(app, cmd)
    assert shown == [True]


def test_command_bar_help_returns_focus_to_the_view():
    """The bar keeps focus across a screen push/pop.

    Every other command-bar path hands focus back to the tree / plans pane;
    the help branch must too, or the next keystroke after closing help is
    typed into the command bar instead of moving the tree (`?` leaves the
    tree focused, so the two routes disagreed).
    """
    from types import SimpleNamespace

    from pm_core.tui import pr_view

    calls = []
    app = SimpleNamespace(
        action_unfocus_command=lambda: calls.append("unfocus"),
        action_show_help=lambda: calls.append("help"),
        log_message=lambda *a, **k: None)
    pr_view.handle_command_submitted(app, "help")
    assert calls == ["unfocus", "help"]


def test_command_bar_returns_focus_to_the_qa_pane():
    """In the QA view, focus must go back to the QA pane, not the hidden tree.

    The command bar keeps focus across a command, and every branch ended
    with "plans pane else tech-tree" — so in the QA view the QA pane's keys
    (j/k, Enter, e, d, a) went dead until the user left and re-entered the
    view.  ``action_unfocus_command`` already handled all three views; the
    command branches now share one helper that does too.
    """
    from types import SimpleNamespace

    from pm_core.tui import pr_view

    focused = []

    def query_one(selector, *rest):
        return SimpleNamespace(focus=lambda: focused.append(selector))

    app = SimpleNamespace(
        _root=None, _inflight_pr_action=None, _plans_visible=False,
        _qa_visible=True,
        log_message=lambda *a, **k: None, query_one=query_one)

    pr_view.handle_command_submitted(app, "pr qa --frosh")

    assert focused == ["#qa-pane"], focused


def test_command_bar_autostart_returns_focus_to_the_qa_pane():
    """The autostart branch was the one command path still focusing the tree.

    Every other command-bar branch was switched to the shared
    ``_refocus_active_view`` helper, but ``autostart …`` kept a bare
    ``#tech-tree`` focus — so in the QA view it deadened the QA pane's keys
    (j/k, Enter, e, d, a) until the view was re-entered, exactly the bug the
    helper fixes everywhere else.
    """
    from types import SimpleNamespace
    from unittest import mock

    from pm_core.tui import auto_start, pr_view

    focused = []

    def query_one(selector, *rest):
        return SimpleNamespace(focus=lambda: focused.append(selector))

    app = SimpleNamespace(
        _root=None, _inflight_pr_action=None, _plans_visible=False,
        _qa_visible=True,
        log_message=lambda *a, **k: None, query_one=query_one)

    with mock.patch.object(auto_start, "handle_command"):
        pr_view.handle_command_submitted(app, "autostart status")

    assert focused == ["#qa-pane"], focused


@pytest.mark.parametrize("cmd", ["review-loop #999", "edit #999"])
def test_command_bar_unknown_id_hands_focus_back(cmd):
    """A typo'd id must not leave the next keystroke in the command bar.

    The review-loop and edit branches returned on a failed id resolution
    without the focus hand-back every other path performs, so after the
    not-found remedy the tree/QA keys were still going into the bar's Input.
    """
    from types import SimpleNamespace
    from unittest import mock

    from pm_core.tui import pr_view

    focused = []

    def query_one(selector, *rest):
        return SimpleNamespace(focus=lambda: focused.append(selector),
                               select_pr=lambda *a, **k: None)

    app = SimpleNamespace(
        _root=Path("/nonexistent"), _inflight_pr_action=None,
        _plans_visible=False, _qa_visible=True,
        log_message=lambda *a, **k: None, query_one=query_one)

    with mock.patch.object(pr_view, "_resolve_command_bar_pr",
                           return_value=None):
        pr_view.handle_command_submitted(app, cmd)

    assert focused == ["#qa-pane"], focused


def _command_bar_app(logs):
    """A minimal app double for command-bar paths that only log + refocus."""
    from types import SimpleNamespace

    focused = []

    def query_one(selector, *rest):
        return SimpleNamespace(focus=lambda: focused.append(selector),
                               select_pr=lambda *a, **k: None)

    app = SimpleNamespace(
        _root=None, _inflight_pr_action=None, _plans_visible=False,
        _qa_visible=False,
        log_message=lambda m, **k: logs.append(m), query_one=query_one)
    return app, focused


def test_command_bar_unmatched_quote_is_a_message_not_a_crash():
    """An apostrophe in a note is a typo, not a TUI crash.

    ``shlex.split`` raises on an unmatched quote, and the exception escaped
    the command-bar handler — Textual treats an exception in a message
    handler as fatal, so `pr note add pr-001 don't forget` killed the TUI.
    The popup runner already answers "Invalid command syntax"; the command
    bar must do the same and name the fix.
    """
    from pm_core.tui import pr_view

    logs: list[str] = []
    app, focused = _command_bar_app(logs)

    pr_view.handle_command_submitted(app, "pr note add pr-001 don't forget")

    assert any("Invalid command syntax" in m for m in logs), logs
    assert any("pr note add pr-001 'text'" in m for m in logs), logs
    assert focused == ["#tech-tree"], focused


def test_command_bar_unmatched_quote_clears_the_busy_guard():
    """The guard the prefix loop set must not survive the parse failure.

    ``pr start …`` is recorded as an in-flight action before the command is
    parsed; if a quoting error returned without clearing it, every later PR
    action would answer "Busy: pr start \"unclosed".
    """
    from pm_core.tui import pr_view

    logs: list[str] = []
    app, _focused = _command_bar_app(logs)

    pr_view.handle_command_submitted(app, 'pr start "unclosed')

    assert app._inflight_pr_action is None
    assert any("Invalid command syntax" in m for m in logs), logs


@pytest.mark.parametrize("token", ["stop", "cancel", "off"])
def test_review_loop_stop_is_refused_with_the_cancel_path(token):
    """`review-loop stop` is a removed spelling, not a missing PR id.

    The toggle was removed (``zz d`` always starts a fresh loop).  Treating
    the token as a PR id answered "PR not found: stop — see pr list", which
    sends the operator to a listing command for a command that does not
    exist.  It must name how a loop is actually cancelled.
    """
    from pm_core.tui import pr_view

    logs: list[str] = []
    app, focused = _command_bar_app(logs)

    pr_view.handle_command_submitted(app, f"review-loop {token}")

    assert any("no stop command" in m for m in logs), logs
    assert any("Ctrl+R" in m for m in logs), logs
    assert not any("PR not found" in m for m in logs), logs
    assert focused == ["#tech-tree"], focused


def test_review_loop_start_token_is_still_accepted():
    """The picker's `zz d` chord queues `review-loop start <id>`.

    The optional `start` token must keep working: it is skipped when the PR
    id is taken, so the stop-token guard must not swallow it.
    """
    from unittest import mock

    from pm_core.tui import pr_view, review_loop_ui

    logs: list[str] = []
    tree = mock.Mock()
    app, _focused = _command_bar_app(logs)
    app.query_one = lambda selector, *rest: tree
    app._root = Path("/nonexistent")

    with mock.patch.object(pr_view, "_resolve_command_bar_pr",
                           return_value={"id": "pr-001"}), \
         mock.patch.object(review_loop_ui, "start_or_stop_loop") as start:
        pr_view.handle_command_submitted(app, "review-loop start pr-001")

    tree.select_pr.assert_called_once_with("pr-001")
    start.assert_called_once_with(app)
    assert not logs, logs


def test_non_github_backend_remedies_name_a_working_command(tmp_path,
                                                            monkeypatch):
    """A wrong-backend refusal must not point at another GitHub-only command.

    `pm pr sync` and `pm plan import` are not substitutes: the first
    refuses for the same reason and the second bootstraps a plan from an
    existing repo.
    """
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\nprs: []\n")
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path):
        sync = CliRunner().invoke(pr_mod.pr, ["sync-github"])
        imp = CliRunner().invoke(pr_mod.pr, ["import-github"])

    assert sync.exit_code == 1, sync.output
    assert "pm pr merge <pr-id>" in sync.output
    assert "pm pr sync' instead" not in sync.output
    assert imp.exit_code == 1, imp.output
    assert "pm pr add <title>" in imp.output
    assert "pm plan import" not in imp.output


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


@pytest.mark.parametrize("cmd,expected", [
    ("pr qa fresh pr-001", ("pr-001", "qa", True)),
    ("pr qa pr-001 --fresh", ("pr-001", "qa", True)),
    ("pr qa --fresh pr-001", ("pr-001", "qa", True)),
    ("pr qa loop pr-001", ("pr-001", "qa", True)),
    ("pr qa pr-001 --loop", ("pr-001", "qa", True)),
    ("pr qa pr-001", ("pr-001", "qa", False)),
    # Rejected by the command bar, so there is no window to wait for.
    ("pr qa --bogus pr-001", (None, None, False)),
])
def test_popup_spinner_parses_both_qa_spellings(cmd, expected):
    """The popup spinner must see the flag spellings as a fresh restart.

    ``pm _popup-cmd`` routes any ``pr qa …`` through the TUI command bar,
    then ``_wait_for_tui_command`` parses the same text to decide whether
    to wait for a rebuilt window.  When only the positional spelling was
    recognised, ``pr qa <id> --fresh`` (which the command bar now accepts)
    looked like a plain run, so the spinner switched to the stale window
    the restart was about to kill.
    """
    from pm_core.cli.session import _parse_tui_action

    assert _parse_tui_action(cmd) == expected


def test_popup_spinner_resolves_display_ids():
    """The spinner's state/window lookups need the internal id.

    The command bar accepts ``pr-001``, ``42`` and ``#42`` (the ids the CLI
    prints), and the picker routes the typed command through the TUI.  The
    runtime-state key and the ``qa-<display>`` window name use different
    spellings, so the parsed id must be resolved before the spinner polls
    — otherwise ``pr qa #42 --fresh`` starts QA for the right PR while the
    spinner watches a window that can never appear.
    """
    from pm_core.cli.session import _resolve_spinner_ids

    data = {"prs": [{"id": "pr-001", "gh_pr_number": 42}]}
    assert _resolve_spinner_ids(data, "pr-001") == ("pr-001", "#42")
    assert _resolve_spinner_ids(data, "#42") == ("pr-001", "#42")
    assert _resolve_spinner_ids(data, "42") == ("pr-001", "#42")
    # Unknown ids keep the typed spelling and match no window, as before.
    assert _resolve_spinner_ids(data, "nope") == ("nope", None)


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


def test_parse_qa_command_errors_survive_tui_markup():
    """The command-bar hint must not be eaten by Textual markup.

    The usage text (and a typo'd token) can contain brackets.  Textual's
    and rich's own `escape` only escape a bracket that opens a *recognised*
    tag, so `[PR_ID]` slips through and the whole segment disappears from
    the log line.  `escape_markup` must round-trip through the parser.
    """
    from textual.content import Content

    with pytest.raises(ValueError) as exc:
        parse_qa_command(["pr-001", "pr-002"])
    shown = Content.from_markup(
        command_surface.escape_markup(f"QA: {exc.value}")).plain
    assert "pr qa [fresh|loop] [PR_ID]" in shown

    with pytest.raises(ValueError) as exc:
        parse_qa_command(["pr-001", "[odd]"])
    shown = Content.from_markup(
        command_surface.escape_markup(f"QA: {exc.value}")).plain
    assert "[odd]" in shown


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


def test_busy_guard_keeps_bracketed_command_text():
    """The in-flight command is user-typed; its brackets must survive.

    ``guard_pr_action`` renders the raw typed command into the "Busy"
    remedy.  Textual's markup parser swallows ``[x]`` / ``[OK]``, so a
    bracketed token vanished from the message that names it — the same
    class of bug the QA and not-found remedies escaped elsewhere.
    """
    from types import SimpleNamespace

    from textual.content import Content

    from pm_core.tui import pr_view

    logs = []
    app = SimpleNamespace(
        _inflight_pr_action="pr qa [x]",
        log_message=lambda msg, **kw: logs.append(msg),
        clear_log_message_later=lambda *a, **kw: None,
    )
    assert pr_view.guard_pr_action(app, "pr start pr-001") is False
    assert Content.from_markup(logs[0]).plain == (
        "Busy: pr qa [x] — wait for it to finish")


def test_command_bar_qa_resolves_a_github_display_id(tmp_path):
    """`pm pr qa` prints `#N` for a GitHub PR; the command bar must accept it.

    The QA branch used ``store.get_pr`` (internal id only), so the exact
    command the CLI prints failed with "PR not found: #42".  It now resolves
    the same identifiers as the CLI: ``pr-001``, ``42``, ``#42``.
    """
    from types import SimpleNamespace
    from unittest import mock

    from pm_core.tui import pr_view, qa_loop_ui

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: github\n  base_branch: master\n"
        "prs:\n- id: pr-001\n  title: T\n  status: in_review\n"
        "  gh_pr_number: 42\n")
    logs = []
    app = SimpleNamespace(
        _root=tmp_path, _inflight_pr_action=None, _plans_visible=False,
        log_message=lambda msg, **kw: logs.append(msg),
        query_one=lambda *a, **k: mock.Mock())

    with mock.patch.object(qa_loop_ui, "focus_or_start_qa") as focus:
        pr_view.handle_command_submitted(app, "pr qa #42")

    focus.assert_called_once_with(app, "pr-001")
    assert not logs, logs


def test_command_bar_qa_unknown_id_names_the_listing_command(tmp_path):
    """A typo'd PR id in the command bar must name the way to see them.

    The branch used to answer a bare "PR not found: <id>"; every other
    not-found path now names `pr list`.
    """
    from types import SimpleNamespace
    from unittest import mock

    from pm_core.tui import pr_view

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\nprs: []\n")
    logs = []
    app = SimpleNamespace(
        _root=tmp_path, _inflight_pr_action=None, _plans_visible=False,
        log_message=lambda msg, **kw: logs.append(msg),
        query_one=lambda *a, **k: mock.Mock())

    pr_view.handle_command_submitted(app, "pr qa pr-999")

    assert "PR not found: pr-999" in logs[-1]
    assert "pr list" in logs[-1]

    # A bracketed typo must survive Textual markup: the remedy names the id.
    pr_view.handle_command_submitted(app, "pr qa [x]")
    assert "[x]" in logs[-1]


def test_command_bar_qa_no_selection_names_the_requested_mode():
    """A fresh/loop request with no PR must not fall back to a plain run.

    The remedy used to say `pr qa <id>` even when the user typed `--fresh`,
    i.e. it named a different action than the one they asked for.
    """
    from types import SimpleNamespace

    from pm_core.tui import pr_view

    logs = []
    app = SimpleNamespace(
        _root=None, _inflight_pr_action=None, _plans_visible=False,
        log_message=lambda msg, **kw: logs.append(msg),
        query_one=lambda *a, **k: SimpleNamespace(selected_pr_id=None,
                                                  focus=lambda: None))

    pr_view.handle_command_submitted(app, "pr qa --fresh")

    assert "pr qa fresh <id>" in logs[-1]
    # The TUI key must match the mode too: `t` is the plain run, `z t` is
    # the fresh restart the user asked for.
    assert "TUI: z t" in logs[-1]


@pytest.mark.parametrize("cmd,handler", [
    ("pr qa pr-001", "focus_or_start_qa"),
    ("pr qa fresh pr-001", "fresh_start_qa"),
    ("pr qa pr-001 --fresh", "fresh_start_qa"),
    ("pr qa --fresh pr-001", "fresh_start_qa"),
    ("pr qa loop pr-001", "start_or_stop_qa_loop"),
    ("pr qa pr-001 --loop", "start_or_stop_qa_loop"),
])
def test_command_bar_qa_dispatches_each_mode(cmd, handler):
    """The two spellings must reach the same handler, not only the parser.

    ``parse_qa_command`` equivalence is asserted above; this pins the
    dispatch table, so a new spelling cannot be accepted and then fall
    through to a plain run (which would leave a stale window for `fresh`).
    """
    from types import SimpleNamespace
    from unittest import mock

    from pm_core.tui import pr_view, qa_loop_ui

    logs = []
    tree = mock.Mock()
    tree.selected_pr_id = None
    app = SimpleNamespace(
        _root=Path("/nonexistent"), _inflight_pr_action=None,
        _plans_visible=False,
        log_message=lambda msg, **kw: logs.append(msg),
        query_one=lambda *a, **k: tree)

    with mock.patch.object(pr_view, "_resolve_command_bar_pr",
                           return_value={"id": "pr-001"}), \
            mock.patch.object(qa_loop_ui, handler) as dispatched:
        pr_view.handle_command_submitted(app, cmd)

    dispatched.assert_called_once_with(app, "pr-001")
    assert not logs, logs
    # QA is handled directly, so the in-flight guard must be released.
    assert app._inflight_pr_action is None


def _github_display_id_app(tmp_path, logs, tree):
    """An app double over a GitHub-backed PR whose display id is `#42`."""
    from types import SimpleNamespace

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: github\n  base_branch: master\n"
        "prs:\n- id: pr-001\n  title: T\n  status: in_review\n"
        "  gh_pr_number: 42\n")
    return SimpleNamespace(
        _root=tmp_path, _inflight_pr_action=None, _plans_visible=False,
        log_message=lambda msg, **kw: logs.append(msg),
        query_one=lambda *a, **k: tree)


def test_command_bar_edit_and_review_loop_resolve_a_github_display_id(
        tmp_path):
    """Every command-bar branch resolves ids the way the CLI does.

    `pr qa #42` was fixed to accept the display id `pm pr qa` prints for a
    GitHub PR; `edit` and `review-loop` kept using ``store.get_pr``
    (internal id only), so the same command failed there.  They now share
    ``_resolve_command_bar_pr`` and select the resolved internal id.
    """
    from unittest import mock

    from pm_core.tui import pane_ops, pr_view, review_loop_ui

    logs = []
    tree = mock.Mock()
    app = _github_display_id_app(tmp_path, logs, tree)

    with mock.patch.object(pane_ops, "edit_plan") as edit:
        pr_view.handle_command_submitted(app, "edit #42")
    tree.select_pr.assert_called_once_with("pr-001")
    edit.assert_called_once_with(app)
    assert not logs, logs

    tree.reset_mock()
    with mock.patch.object(review_loop_ui, "start_or_stop_loop") as start:
        pr_view.handle_command_submitted(app, "review-loop #42")
    tree.select_pr.assert_called_once_with("pr-001")
    start.assert_called_once_with(app)
    assert not logs, logs


def test_review_loop_stop_remedy_names_the_loop_command():
    """`pm pr review` opens a one-shot review, not a loop.

    The remedy must name the command-bar `review-loop` form (TUI `zz d`);
    pairing a plain review with `zz d` would send the operator to a
    different action than the one named.
    """
    from types import SimpleNamespace

    from pm_core.tui import review_loop_ui

    logs = []
    app = SimpleNamespace(_review_loops={},
                          log_message=lambda msg, **kw: logs.append(msg))
    review_loop_ui._stop_loop(app, "pr-001")
    assert "review-loop pr-001" in logs[-1]
    assert "zz d" in logs[-1]
    assert "one-shot" in logs[-1]


def test_watcher_stop_names_the_requested_type():
    """`ws` toggles only auto-start, so it is not the answer for other types.

    `pm watcher stop <type>` cannot stop anything (it prints guidance), but
    it must answer for the type it was asked about: naming `ws`
    unconditionally sent an operator with a `bug-fix-impl` watcher to a
    chord that does nothing to it.
    """
    runner = CliRunner()
    auto = runner.invoke(cli, ["watcher", "stop"]).output
    assert "press 'ws'" in auto

    other = runner.invoke(cli, ["watcher", "stop", "bug-fix-impl"]).output
    assert "bug-fix-impl" in other
    assert "press 'ws'" not in other
    assert "Ctrl+C" in other


def test_watcher_already_running_does_not_promise_watcher_stop():
    """`pm watcher stop` only prints guidance; it stops nothing.

    A remedy that says "stop it with `pm watcher stop`" is a dead end, so
    the message points at it for guidance and names the real TUI route.
    """
    from types import SimpleNamespace
    from unittest import mock

    from pm_core.tui import watcher_ui

    logs = []
    manager = mock.Mock()
    manager.find_by_type.return_value = SimpleNamespace(
        state=SimpleNamespace(running=True))
    app = SimpleNamespace(_watcher_manager=manager,
                          log_message=lambda msg, **kw: logs.append(msg))

    with mock.patch("pm_core.tmux.in_tmux", return_value=True):
        watcher_ui.start_watcher(app, watcher_type="auto-start")

    assert "already running" in logs[-1]
    assert "see `pm watcher stop auto-start`" in logs[-1]
    assert "stop it with `pm watcher stop" not in logs[-1]


def test_watcher_already_running_names_the_requested_type():
    """The stop guidance must name the type that is actually running.

    ``pm watcher stop`` answers for the type it is asked about (``ws`` only
    toggles auto-start), so a bare ``pm watcher stop`` sent the operator of a
    ``bug-fix-impl`` watcher to auto-start guidance.
    """
    from types import SimpleNamespace
    from unittest import mock

    from pm_core.tui import watcher_ui

    logs = []
    manager = mock.Mock()
    manager.find_by_type.return_value = SimpleNamespace(
        state=SimpleNamespace(running=True))
    app = SimpleNamespace(_watcher_manager=manager,
                          log_message=lambda msg, **kw: logs.append(msg))

    with mock.patch("pm_core.tmux.in_tmux", return_value=True):
        watcher_ui.start_watcher(app, watcher_type="bug-fix-impl")

    assert "pm watcher stop bug-fix-impl" in logs[-1]


def test_session_home_names_pm_session_outside_a_session():
    """`pm session home` must name the command that creates a session.

    It said only "Not inside a pm tmux session.", which is a dead end: the
    corrective command is `pm session`, as every other must-be-in-the-TUI
    refusal now says.
    """
    from unittest import mock

    with mock.patch("pm_core.cli.helpers._get_pm_session", return_value=None):
        result = CliRunner().invoke(cli, ["session", "home"])

    assert result.exit_code == 1, result.output
    assert "pm session" in result.output


def test_rebalance_names_pm_session_outside_tmux():
    """`pm rebalance` is another must-be-in-the-TUI refusal."""
    from unittest import mock

    from pm_core.cli import session as session_mod

    with mock.patch.object(session_mod.tmux_mod, "in_tmux",
                           return_value=False):
        result = CliRunner().invoke(cli, ["rebalance"])

    assert result.exit_code == 1, result.output
    assert "pm session" in result.output


def test_help_names_a_real_autostart_command():
    """`pm tui keys` must not point at a command that does not exist.

    The auto-start paragraph said `autostart target X`; the group has no
    `target` subcommand (it is `autostart add`), so an operator copying the
    form got "No such command 'target'".
    """
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    assert "autostart add X" in out
    assert "autostart target" not in out


def test_help_does_not_claim_bare_autostart_disables_it():
    """Bare `pm autostart` prints its help; it does not toggle auto-start off.

    The auto-start paragraph said "Bare `autostart` only turns auto-start
    off", but the group has no such behaviour: disabling is `A` with no PR
    selected or `autostart clear`.  An operator relying on the old line
    would type a command that does nothing.
    """
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    flat = " ".join(out.split())
    assert "Bare `autostart` only turns auto-start off" not in flat
    assert "`A` with no PR selected (or `autostart clear`) turns auto-start off" in flat
    # And the command really does print its help rather than disable
    # anything (the exit code varies across Click versions).
    result = CliRunner().invoke(cli, ["autostart"])
    assert "Usage:" in result.output
    assert "Manage auto-start targets" in result.output


def test_tui_send_examples_match_the_current_bindings():
    """`pm tui send`'s examples described the old guide keys.

    `g` is Merge and `x` is hide/show plan group; the guide is `H`.  An
    operator copying "g (launch guide)" would merge a PR instead.
    """
    out = " ".join(CliRunner().invoke(cli, ["tui", "send", "--help"]).output.split())
    assert "(launch guide)" in out
    assert "(merge the selected PR)" in out
    assert "dismiss guide" not in out
    assert "hide/show plan group" in out


def test_prompt_texts_do_not_reference_removed_pr_done():
    """The injected prompts list commands that launch sessions.

    `pm pr done` no longer exists (the review step is `pm pr review`); a
    driving session that reads the list as a menu would try a command that
    answers "No such command".
    """
    root = Path(__file__).resolve().parents[1]
    for rel in ("pm_core/prompt_gen.py", "pm_core/tui/pane_ops.py"):
        assert "pm pr done" not in (root / rel).read_text(), rel


def test_help_text_does_not_name_removed_commands():
    """`pm help` must not send an operator to a command that no longer exists.

    The sweep removed ``pm pr done`` from the injected prompts but left
    ``(replaces `pm tui test`)`` on the ``pm qa regression`` line: the old
    command is gone, so the parenthetical read as a runnable command and
    answered "No such command".  The help surface now names the directory
    the tests live in instead.
    """
    for removed in ("pm tui test", "pm pr done"):
        assert removed not in HELP_TEXT, removed


def test_review_window_no_workdir_names_the_start_command(tmp_path, capsys):
    """A window that cannot open for lack of a workdir names the way to make one."""
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    pr = {"id": "pr-001", "title": "T", "status": "in_progress"}
    with mock.patch.object(pr_mod.tmux_mod, "has_tmux", return_value=True), \
            mock.patch.object(pr_mod.tmux_mod, "in_tmux", return_value=True), \
            mock.patch.object(pr_mod, "_get_pm_session",
                              return_value="pm-proj-1234"), \
            mock.patch.object(pr_mod.tmux_mod, "session_exists",
                              return_value=True), \
            mock.patch.object(pr_mod, "state_root", return_value=tmp_path), \
            mock.patch.object(pr_mod, "_ensure_workdir", return_value=None):
        pr_mod._launch_review_window({"project": {}}, dict(pr))

    out = capsys.readouterr().out
    assert "pm pr start pr-001" in out
    assert "TUI: s" in out


def test_merge_window_no_workdir_names_the_start_command(tmp_path, capsys):
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    pr = {"id": "pr-001", "title": "T", "status": "sign_off"}
    with mock.patch.object(pr_mod.tmux_mod, "has_tmux", return_value=True), \
            mock.patch.object(pr_mod.tmux_mod, "in_tmux", return_value=True), \
            mock.patch.object(pr_mod, "_get_pm_session",
                              return_value="pm-proj-1234"), \
            mock.patch.object(pr_mod.tmux_mod, "session_exists",
                              return_value=True):
        pr_mod._launch_merge_window({"project": {}}, dict(pr), "err")

    out = capsys.readouterr().out
    assert "pm pr start pr-001" in out
    assert "TUI: s" in out


def test_signoff_window_no_workdir_names_the_start_command(tmp_path, capsys):
    from unittest import mock

    from pm_core import signoff
    from pm_core.cli import helpers

    pr = {"id": "pr-001", "title": "T", "status": "qa"}
    with mock.patch.object(signoff.tmux_mod, "has_tmux", return_value=True), \
            mock.patch.object(signoff.tmux_mod, "in_tmux", return_value=True), \
            mock.patch.object(helpers, "_get_pm_session",
                              return_value="pm-proj-1234"), \
            mock.patch.object(signoff.tmux_mod, "session_exists",
                              return_value=True), \
            mock.patch.object(helpers, "state_root", return_value=tmp_path), \
            mock.patch.object(helpers, "_ensure_workdir", return_value=None):
        signoff.launch_signoff_window({"project": {}}, dict(pr))

    out = capsys.readouterr().out
    assert "pm pr start pr-001" in out
    assert "TUI: s" in out


def test_require_pr_names_the_listing_command(capsys):
    with pytest.raises(SystemExit):
        _require_pr({"prs": [{"id": "pr-001"}]}, "pr-999")
    assert "pm pr list" in capsys.readouterr().err


def test_require_plan_names_the_listing_command(capsys):
    with pytest.raises(SystemExit):
        _require_plan({"plans": [{"id": "bugs"}]}, "nope")
    assert "pm plan list" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
    ["add", "T", "--depends-on", "pr-999"],
    ["edit", "pr-001", "--depends-on", "pr-999"],
])
def test_depends_on_unknown_ids_names_the_listing_command(tmp_path, args):
    """`--depends-on` with a typo'd id names `pm pr list`.

    Both scaffolders stopped at "Unknown PR IDs", unlike every other
    not-found refusal in the sweep (`_require_pr`, `pm autostart add`), so
    the operator had to guess how to find a real id.
    """
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\n"
        "prs:\n  - id: pr-001\n    title: T\n    status: pending\n")
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(pr_mod.pr, args)

    assert result.exit_code == 1, result.output
    assert "Unknown PR IDs" in result.output
    assert "pm pr list" in result.output


def test_provider_show_not_found_names_the_listing_command(tmp_path):
    """`pm provider show` must name `pm provider list`, like `remove` does.

    ``_echo_provider`` reported only "provider 'x' is not configured in
    <path>"; the sibling ``provider remove`` refusal already named the
    listing command.
    """
    from unittest import mock

    with mock.patch("pm_core.providers.pm_home", return_value=tmp_path):
        result = CliRunner().invoke(cli, ["provider", "show", "nope"])
    assert result.exit_code == 1, result.output
    assert "pm provider list" in result.output


def test_no_tui_ipc_message_names_pm_session():
    """A queued command with no TUI must name how to start one.

    `pm autostart add …` surfaces this ``TuiIpcResult.message`` verbatim.
    "No TUI is running" alone is a dead end (the fix is to start a session),
    so it names `pm session` like every `pm tui *` refusal.
    """
    from unittest import mock

    from pm_core.cli import helpers

    with mock.patch.object(
            helpers, "_read_tui_owner",
            return_value=(Path("/nonexistent"), None, None, "no pidfile")):
        _pid, _raw, _desc, err = helpers._validate_tui_owner("pm-proj-1234")

    assert err is not None and err.reason == "no_pidfile"
    assert "pm session" in err.message


def test_qa_debug_no_session_names_pm_session(tmp_path, monkeypatch):
    """`pm qa debug` outside a session must name `pm session`.

    It said only "Run inside a pm tmux session", which does not tell the
    operator the command that creates one.
    """
    import pm_core.loop_shared as loop_shared
    import pm_core.qa_instructions as qa_instr
    import pm_core.store as store_mod

    from pm_core.cli import qa as qa_mod

    monkeypatch.setattr(qa_mod, "state_root", lambda: tmp_path)
    monkeypatch.setattr(
        qa_instr, "get_instruction",
        lambda root, iid, category=None: {"id": iid, "title": "T"})
    monkeypatch.setattr(store_mod, "load",
                        lambda root: {"project": {}, "prs": []})
    monkeypatch.setattr(loop_shared, "get_pm_session", lambda: None)

    result = CliRunner().invoke(qa_mod.cli, ["qa", "debug", "instr-1"])
    assert result.exit_code == 1, result.output
    assert "pm session" in result.output


def test_signoff_no_candidate_names_the_prerequisite(tmp_path):
    """A missing sign-off candidate names the stage before it, not a guess.

    The remedy used to say "run QA first" in every project; under `skip_qa`
    sign-off follows review, so that sends the operator to a stage the
    project never runs.
    """
    result = _lifecycle_refusal(tmp_path, ["signoff"], status="in_review")
    assert result.exit_code == 1, result.output
    out = " ".join(result.output.split())
    assert "No PR is ready for sign-off" in out
    assert "pass QA before sign-off" in out
    assert "pm pr list" in out

    result = _lifecycle_refusal(tmp_path, ["signoff"], status="pending",
                                skip_qa=True)
    assert result.exit_code == 1, result.output
    out = " ".join(result.output.split())
    assert "pass review before sign-off" in out


def test_signoff_infers_in_review_under_skip_qa(tmp_path):
    """`skip_qa` makes `in_review` a sign-off entry state; infer it.

    The bare-command inference filtered on sign_off/qa only, so on a
    `skip_qa` project it reported "nothing to do" while an `in_review` PR
    was waiting for exactly this step (the status check below already
    accepts it).
    """
    from unittest import mock

    from pm_core import signoff as signoff_mod
    from pm_core.cli import pr as pr_mod

    data = {"project": {"base_branch": "master", "backend": "vanilla",
                        "skip_qa": True},
            "prs": [{"id": "pr-001", "title": "T", "status": "in_review"}]}
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path), \
            mock.patch.object(pr_mod.store, "load", return_value=data), \
            mock.patch.object(pr_mod.store, "locked_update"), \
            mock.patch.object(signoff_mod, "launch_signoff_window"):
        result = CliRunner().invoke(pr_mod.pr, ["signoff"])

    assert "No PR is ready for sign-off" not in result.output
    assert "Auto-selected pr-001" in result.output


def test_status_next_step_maps_lifecycle_order():
    from pm_core.cli.pr import _next_step_for_status

    assert "pm pr start pr-001" in _next_step_for_status("pr-001", "pending")
    assert "pm pr review pr-001" in _next_step_for_status("pr-001", "in_progress")
    assert "pm pr signoff pr-001" in _next_step_for_status("pr-001", "qa")
    assert "pm pr merge pr-001" in _next_step_for_status("pr-001", "sign_off")
    assert "pm pr show pr-001" in _next_step_for_status("pr-001", "merged")


def test_status_next_step_does_not_name_the_diagnostic_qa_command():
    """`pm pr qa` only prints the command-bar form; it never starts QA.

    A remedy that says "run QA with `pm pr qa`" sends the operator in a
    circle: that command answers with another instruction and exits 1.
    The in_review step must name the action that actually starts QA.
    """
    from pm_core.cli.pr import _next_step_for_status

    remedy = _next_step_for_status("pr-001", "in_review")
    assert "pm pr qa" not in remedy
    assert "pr qa pr-001" in remedy
    assert "press t" in remedy


def test_pr_qa_wrong_status_names_the_next_command(tmp_path):
    """The CLI's own refusal must carry the same corrective command."""
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\n"
        "prs:\n- id: pr-001\n  title: T\n  status: pending\n")
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(pr_mod.pr, ["qa", "pr-001"])

    assert result.exit_code == 1, result.output
    assert "pm pr start pr-001" in result.output


def test_pr_qa_valid_pr_prints_the_command_bar_form(tmp_path):
    """The valid path is the motivating failure's fix, and still exits 1.

    `pm pr qa` never starts QA: on a valid in_review PR it prints the
    command-bar form (and the TUI keys) and exits 1.  Without this test the
    documented behavior — and the fact that exit 1 is not a failure — was
    only asserted in the help text.
    """
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\n"
        "prs:\n- id: pr-001\n  title: T\n  status: in_review\n")
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path), \
            mock.patch.object(pr_mod, "_get_pm_session", return_value=None):
        result = CliRunner().invoke(pr_mod.pr, ["qa", "pr-001"])

    assert result.exit_code == 1, result.output
    assert "pr qa pr-001" in result.output
    assert "z t" in result.output and "zz t" in result.output
    assert "pm session" in result.output


@pytest.mark.parametrize("status", ["merged", "closed"])
def test_pr_cd_terminal_pr_does_not_name_the_start_command(tmp_path, status):
    """`pm pr start` refuses a terminal PR, so it cannot recreate its workdir.

    `pm pr cd <merged-id>` on a PR whose workdir was cleaned up used to say
    "Create it with 'pm pr start <id>'" — a command that answers "already
    merged" and exits.  The remedy must name what can actually be done.
    """
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\n"
        f"prs:\n- id: pr-001\n  title: T\n  status: {status}\n"
        "  workdir: /nonexistent/workdir\n")
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(pr_mod.pr, ["cd", "pr-001"])

    assert result.exit_code == 1, result.output
    assert "pm pr start" not in result.output
    assert "pm pr show pr-001" in result.output
    assert status in result.output


def test_pr_cd_missing_workdir_still_names_the_start_command(tmp_path):
    """A PR that can still start keeps the start remedy."""
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\n"
        "prs:\n- id: pr-001\n  title: T\n  status: in_progress\n"
        "  workdir: /nonexistent/workdir\n")
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(pr_mod.pr, ["cd", "pr-001"])

    assert result.exit_code == 1, result.output
    assert "pm pr start pr-001" in result.output


def _lifecycle_refusal(tmp_path, args, *, status, skip_qa=False):
    """Invoke a `pm pr …` lifecycle command over a one-PR fixture."""
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    project = {"base_branch": "master", "backend": "vanilla"}
    if skip_qa:
        project["skip_qa"] = True
    data = {"project": project,
            "prs": [{"id": "pr-001", "title": "T", "status": status}]}
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path), \
            mock.patch.object(pr_mod.store, "load", return_value=data):
        return CliRunner().invoke(pr_mod.pr, args)


def test_merge_no_candidate_names_the_listing_not_a_presumed_step(tmp_path):
    """No candidate does not mean "sign-off is next".

    The missing PR may be pending (start first), in QA, or already merged,
    so the remedy must send the operator to `pm pr list` for the status
    rather than asserting that sign-off is the immediate step.  (The i14
    note claimed this was already fixed; the message still said "sign-off
    comes first".)
    """
    result = _lifecycle_refusal(tmp_path, ["merge"], status="pending")
    assert result.exit_code == 1, result.output
    out = " ".join(result.output.split())
    assert "pm pr list" in out
    assert "sign-off comes first" not in out


def test_signoff_refusal_expected_states_follow_skip_qa(tmp_path):
    """With `skip_qa` there is no QA stage: sign-off follows review.

    The refusal listed "qa or sign_off" and said "runs after QA" even on a
    project that never runs QA, sending the operator to a stage that does
    not exist there.
    """
    result = _lifecycle_refusal(tmp_path, ["signoff", "pr-001"],
                                status="in_progress", skip_qa=True)
    assert result.exit_code == 1, result.output
    out = " ".join(result.output.split())
    assert "sign-off runs after review" in out
    assert "in_review" in out

    # The default project keeps the QA wording its tests pin.
    result = _lifecycle_refusal(tmp_path, ["signoff", "pr-001"],
                                status="in_progress")
    assert result.exit_code == 1, result.output
    assert "sign-off runs after QA" in result.output


@pytest.mark.parametrize("mode", command_surface.QA_MODIFIER_MODES)
def test_pr_qa_cli_rejects_the_reversed_two_token_form(tmp_path, mode):
    """`pm pr qa pr-001 fresh` is a command-bar spelling too.

    The mode may follow the id (`pr qa <id> fresh`), which the command bar
    accepts.  Only the mode-first order was tolerated, so this one still
    died on Click's ``Got unexpected extra argument (fresh)`` (exit 2)
    instead of naming the command-bar route.
    """
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\nprs: []\n")
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(pr_mod.pr, ["qa", "pr-001", mode])

    assert result.exit_code == 1, result.output
    assert "Got unexpected extra argument" not in result.output
    assert "command bar" in result.output
    assert f"pr qa {mode} <id>" in result.output


@pytest.mark.parametrize("mode", command_surface.QA_MODIFIER_MODES)
def test_pr_qa_cli_rejects_the_two_token_command_bar_form(tmp_path, mode):
    """`pm pr qa fresh pr-001` must reach the hint, not Click's usage error.

    This two-token form is exactly what the help tells the operator to type
    in the command bar, and what a driving Claude session pastes onto the
    CLI.  Click used to answer ``Got unexpected extra argument (pr-001)``
    (exit 2) before ``pr_qa`` could name the command-bar route and the TUI
    key — the motivating failure's other surface.
    """
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\nprs: []\n")
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(pr_mod.pr, ["qa", mode, "pr-001"])

    assert result.exit_code == 1, result.output
    assert "Got unexpected extra argument" not in result.output
    assert "command bar" in result.output
    assert f"pr qa {mode} <id>" in result.output
    assert command_surface.QA_MODE_KEYS[mode] in result.output


def test_pr_qa_mode_token_does_not_swallow_help():
    """The CLI-tolerance rewrite must leave option handling to Click."""
    out = _help("pr", "qa", "fresh")
    assert "QA modes" in out


@pytest.mark.parametrize("mode", command_surface.QA_MODIFIER_MODES)
def test_pr_qa_cli_rejects_a_command_bar_mode_with_a_hint(tmp_path, mode):
    """`pm pr qa fresh` must say the mode is command-bar only.

    The CLI form is diagnostic and has no modes.  Without this hint the mode
    reads as a missing PR id ("PR 'fresh' not found") — the same
    discoverability failure this PR fixes, one surface over.  The mode set
    and its TUI key are read from the shared table, so a new mode cannot be
    accepted in the command bar and un-hinted on the CLI.
    """
    from unittest import mock

    from pm_core.cli import pr as pr_mod

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\nprs: []\n")
    with mock.patch.object(pr_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(pr_mod.pr, ["qa", mode])

    assert result.exit_code == 1, result.output
    assert "command bar" in result.output
    assert f"pr qa {mode} <id>" in result.output
    assert command_surface.QA_MODE_KEYS[mode] in result.output


def test_qa_launch_without_a_tmux_name_names_pm_session(tmp_path, monkeypatch):
    """`pm qa launch`'s last must-be-in-the-TUI refusal must name `pm session`.

    It said only "No tmux session detected." — a dead end, unlike the
    `requires tmux` refusal immediately above it in the same command.
    """
    import pm_core.tmux as tmux_mod
    from pm_core.cli import qa as qa_mod
    import pm_core.qa_instructions as qa_instr

    monkeypatch.setattr(qa_mod, "state_root", lambda: tmp_path)
    monkeypatch.setattr(
        qa_instr, "get_instruction",
        lambda root, iid, category=None: {"id": iid, "title": "T"})
    monkeypatch.setattr(tmux_mod, "has_tmux", lambda: True)
    monkeypatch.setattr(tmux_mod, "in_tmux", lambda: True)
    monkeypatch.setattr(tmux_mod, "get_session_name", lambda: None)

    result = CliRunner().invoke(cli, ["qa", "launch", "instruction:abc"])
    assert result.exit_code == 1, result.output
    assert "pm session" in result.output


def test_model_screen_not_found_names_the_listing_command(tmp_path):
    """The model modal's not-found line names `pr list`, like every other.

    It is the last user-facing TUI not-found message without the listing
    command (the spec review, plan file and QA item were fixed in the first
    pass).  The modal can outlive its PR: a state reload while it is open
    leaves ``_pr()`` empty.
    """
    from pm_core.tui.model_screen import ModelSettingsScreen

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\nprs: []\n")
    screen = ModelSettingsScreen(tmp_path, "pr-999")
    screen._load()
    shown = " ".join(screen._table_lines())
    assert "pr-999" in shown
    assert "pr list" in shown


def test_model_screen_save_not_found_names_the_listing_command(tmp_path):
    """The modal's save refusal names `pr list` too.

    ``_apply`` reloads under the store lock; a PR removed in the meantime
    surfaced as a bare "Not saved: PR <id> not found" in the status line —
    the same dead end as the rendering path fixed above.
    """
    from unittest import mock

    from pm_core.tui import model_screen

    (tmp_path / "project.yaml").write_text(
        "project:\n  backend: vanilla\n  base_branch: master\nprs: []\n")
    screen = model_screen.ModelSettingsScreen(tmp_path, "pr-999")
    screen._load()

    def fake_update(root, edit):
        edit({"project": {}, "prs": []})  # the PR vanished before the save

    with mock.patch.object(model_screen.store, "locked_update", fake_update):
        screen._apply("model", "claude-sonnet-5-5")

    assert "not found" in screen._status
    assert "pr list" in screen._status


def test_plan_actions_report_a_missing_plan_file(tmp_path):
    """Enter / `e` on a plan whose file is missing must say so.

    Both returned silently, so the key looked broken; `v`
    (``view_plan``) already named `pm plan list`.  A live plan in this
    project (`plan-b6aac3d`) has no file on disk, so the state is
    reachable, not hypothetical.  An empty ``file`` must not resolve to
    the project root — which exists — and open the editor on the whole
    project.
    """
    from types import SimpleNamespace

    from pm_core.tui import pane_ops

    logs = []
    app = SimpleNamespace(
        _root=tmp_path,
        _data={"plans": [
            {"id": "plan-gone", "file": "plans/plan-gone.md"},
            {"id": "plan-nofile", "file": ""},
        ]},
        log_message=lambda msg, **kw: logs.append(msg),
    )

    pane_ops.launch_plan_activated(app, "plan-gone")
    assert "Plan file not found" in logs[-1]
    assert "pm plan list" in logs[-1]

    pane_ops.handle_plan_action(app, "edit", "plan-gone")
    assert "Plan file not found" in logs[-1]
    assert "pm plan list" in logs[-1]

    pane_ops.handle_plan_action(app, "edit", "plan-nofile")
    assert "Plan file not found" in logs[-1]
    assert str(tmp_path) not in logs[-1], (
        "an empty plan file must not resolve to the project root")

    pane_ops.launch_plan_activated(app, "plan-unknown")
    assert "plan-unknown" in logs[-1]
    assert "pm plan list" in logs[-1]


@pytest.mark.parametrize("launcher", ["launch_claude", "launch_discuss",
                                      "launch_watcher_review"])
def test_claude_not_found_names_the_install_remedy(launcher):
    """A missing Claude binary is a user-facing not-found error too.

    The three pane launchers logged a bare "Claude CLI not found" and
    returned, so the key read as broken with no way forward.
    `claude_launcher` itself already raises "install it first"; the TUI
    message now says the same.
    """
    from types import SimpleNamespace
    from unittest import mock

    from pm_core.tui import pane_ops

    logs = []
    app = SimpleNamespace(
        _root=None,
        _session_name="s",
        _consume_z=lambda: 0,
        log_message=lambda msg, **kw: logs.append(msg),
    )
    with mock.patch("pm_core.claude_launcher.find_claude", return_value=None):
        getattr(pane_ops, launcher)(app)
    assert "Claude CLI not found" in logs[-1]
    assert "install" in logs[-1].lower()


def test_cli_launchers_name_the_install_remedy(tmp_path):
    """The two CLI launchers that print a fallback prompt say what to do.

    `pm plan add` and the TUI pane launchers name the remedy ("copy-paste
    this prompt into Claude Code" / "install Claude Code first").  `pm
    container build` and `pm meta` printed a bare "Claude CLI not found"
    followed by an unexplained prompt, so the fallback read as an error
    rather than an instruction.
    """
    from unittest import mock

    from pm_core.cli import container as container_mod
    from pm_core.cli import meta as meta_mod

    with mock.patch.object(container_mod, "_get_pm_session",
                           return_value=None), \
         mock.patch.object(container_mod, "state_root",
                           return_value=tmp_path), \
         mock.patch.object(container_mod, "_build_container_build_prompt",
                           return_value="p"), \
         mock.patch("pm_core.store.load",
                    return_value={"project": {"name": "t"}}), \
         mock.patch("pm_core.store.is_internal_pm_dir", return_value=True), \
         mock.patch("pm_core.container.load_container_config",
                    return_value=mock.MagicMock(image="pm-dev:latest")), \
         mock.patch("pm_core.claude_launcher.find_claude",
                    return_value=None):
        result = CliRunner().invoke(container_mod.container_build, [])

    assert result.exit_code != 0
    assert "install Claude Code first" in result.output
    assert "copy-paste this prompt" in result.output

    fake_git = mock.MagicMock(returncode=0, stdout="master\n")
    with mock.patch.object(meta_mod, "_get_session_name_for_cwd",
                           return_value="pm-proj-1234"), \
         mock.patch.object(meta_mod, "ensure_meta_workdir",
                           return_value=tmp_path), \
         mock.patch.object(meta_mod.git_ops, "run_git",
                           return_value=fake_git), \
         mock.patch.object(meta_mod.git_ops, "checkout_branch",
                           return_value=None), \
         mock.patch.object(meta_mod, "_build_meta_prompt",
                           return_value="p"), \
         mock.patch.object(meta_mod, "_get_pm_session", return_value=None), \
         mock.patch("pm_core.claude_launcher.find_claude",
                    return_value=None):
        result = CliRunner().invoke(meta_mod.meta_cmd, ["a task"])

    assert result.exit_code != 0
    assert "install Claude Code first" in result.output
    assert "copy-paste this prompt" in result.output


def test_help_screen_uses_the_shared_command_bar_header():
    """The `?` screen and `pm tui keys` must title the section the same way.

    QA scenario 6 read "Command bar (press /):" (the shared header) while
    the screen rendered "Command Bar", so the two help surfaces disagreed
    on the one thing this PR unifies.  The screen now renders
    ``COMMAND_BAR_HEADER`` itself.
    """
    text = _render_help_screen()
    assert command_surface.COMMAND_BAR_HEADER in text
    out = CliRunner().invoke(cli, ["tui", "keys"]).output
    assert command_surface.COMMAND_BAR_HEADER in out


def test_command_bar_rows_helper_cannot_drop_a_row():
    """The rows helper is the screen's source; there is no slicing.

    The HelpScreen used to slice the section helper's first element to drop
    the header, so a change to that element would have silently dropped a
    row from the `?` screen.
    """
    rows = command_surface.command_bar_rows_textual()
    assert command_surface.COMMAND_BAR_HEADER not in rows
    assert rows[0].strip().startswith("pr start")
    assert any("pr qa fresh" in row for row in rows)


# ---------------------------------------------------------------------------
# Plan-name reconciliation
# ---------------------------------------------------------------------------

def test_watcher_list_names_the_plans_the_watchers_drive():
    """`pm watcher list` is a live plan-name surface, not just a type list.

    R22 names it alongside `pm watcher start --help`: the improvement-fix
    watcher must read as driving `plan=improvements`.  It used to print only
    the display name, window and interval, so the plan name — the thing this
    PR reconciles — never appeared.
    """
    out = CliRunner().invoke(cli, ["watcher", "list"]).output
    assert "plan=improvements" in out
    assert "plan=bugs" in out
    assert not re.search(r"\bplan=ux\b", out)

    # Both surfaces R22 names must agree: start --help already said
    # plan=improvements; the list output now does too.
    start_help = CliRunner().invoke(cli, ["watcher", "start", "--help"]).output
    assert "plan=improvements" in start_help
    assert not re.search(r"\bplan=ux\b", start_help)


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


def test_no_stale_ux_plan_name_in_docs():
    """The plan rename reaches the docs too, not only the code.

    The spec's section D lists ``pm/plans/plan-regression.md`` and
    ``pm/docs/literature-review.md`` alongside the prompt/watcher modules;
    the code-only scan above would not catch a regression in either.  A
    line that also names ``improvements`` is the explanatory pairing ("the
    stale id is ``plan=ux``, the real plan is ``improvements``") and is
    allowed.  Historical records (``pm/specs/**``, adversarial reviews) are
    deliberately out of scope.
    """
    root = Path(__file__).resolve().parents[1]
    paths = [root / "pm" / "plans" / "plan-regression.md",
             root / "pm" / "docs" / "literature-review.md"]
    offenders = []
    for path in paths:
        for lineno, line in enumerate(
                path.read_text(errors="ignore").splitlines(), 1):
            if "tui-ux" in line or "improvements" in line:
                continue
            if re.search(r"\bux\b", line):
                offenders.append(f"{path.relative_to(root)}:{lineno}: "
                                 f"{line.strip()}")
    assert not offenders, "stale plan=ux references:\n" + "\n".join(offenders)


def test_tui_ux_plan_is_not_rewritten():
    root = Path(__file__).resolve().parents[1]
    project = (root / "pm" / "project.yaml").read_text()
    assert "tui-ux" in project
    assert "plan=improvements" in (root / "pm_core" / "prompt_gen.py").read_text()


# ---------------------------------------------------------------------------
# The last un-remediated dead ends (review-loop 6a82 i5)
# ---------------------------------------------------------------------------

def test_view_plan_without_a_plan_names_the_assign_action():
    """`v` on a standalone PR must not be a dead end.

    ``view_plan`` answered only "No plan associated with this PR", so the
    documented ``v View plan file`` key read as broken.  The plan is
    assignable from the TUI (`M`) or the CLI (`pm pr edit <id> --plan`),
    and the sibling plan-file dead ends already name their fix.
    """
    from types import SimpleNamespace

    from pm_core.tui import pane_ops

    logs = []
    tree = SimpleNamespace(selected_pr_id="pr-001")
    app = SimpleNamespace(
        _root=Path("/nonexistent"),
        _data={"prs": [{"id": "pr-001", "title": "T", "plan": None}],
               "plans": []},
        _consume_z=lambda: 0,
        query_one=lambda selector, *rest: tree,
        _get_plan_for_pr=lambda pr: None,
        log_message=lambda msg, **kw: logs.append(msg),
    )

    pane_ops.view_plan(app)

    assert "No plan associated with pr-001" in logs[-1]
    assert "`M`" in logs[-1]
    assert "pm pr edit pr-001 --plan" in logs[-1]


def test_connect_key_names_how_to_start_a_shared_session(monkeypatch):
    """`C` outside a shared session must name how to get one.

    "Not a shared session" was a bare refusal: there is no connect command
    to show, and nothing said how a session becomes shared.
    """
    from types import SimpleNamespace

    from pm_core.tui import pane_ops

    monkeypatch.delenv("PM_TMUX_SOCKET", raising=False)
    logs = []
    app = SimpleNamespace(
        log_message=lambda msg, **kw: logs.append(msg),
        clear_log_message_later=lambda *a, **k: None,
        push_screen=lambda *a, **k: None,
    )

    pane_ops.show_connect(app)

    assert "Not a shared session" in logs[-1]
    assert "pm session --global" in logs[-1]


def test_stale_tui_pidfile_messages_name_pm_session(tmp_path, monkeypatch):
    """A dead/absent TUI owner must name the command that starts one.

    These messages surface from `pm autostart …` in a plain shell, where
    "restart the TUI" is impossible — there is no TUI to press Ctrl+R in,
    and the stale pidfile is removed.  `pm session` is the action.
    """
    from pm_core.cli import helpers

    pidfile = tmp_path / "tui.pid"
    monkeypatch.setattr(helpers, "_tui_pidfile_for_session",
                        lambda session: pidfile)

    # A dead owner: the legacy bare-pid format, pointing at no process.
    # Far above /proc/sys/kernel/pid_max, so no live process can collide.
    pidfile.write_text(str(2 ** 30 - 1))
    _path, _raw, _desc, error = helpers._validate_tui_owner("pm-x")
    assert error is not None and error.ok is False
    assert "is not running" in error.message
    assert "pm session" in error.message

    # An unreadable file: no descriptor to trust at all.
    pidfile.write_bytes(b"\xff\xfe\x00garbage")
    _path, _raw, _desc, error = helpers._validate_tui_owner("pm-x")
    assert error is not None and error.ok is False
    assert "unreadable" in error.message
    assert "pm session" in error.message


def test_invalid_qa_item_id_names_the_library(tmp_path):
    """A malformed QA item id must point at the listing command."""
    from types import SimpleNamespace

    from pm_core.tui import pane_ops

    logs = []
    app = SimpleNamespace(_root=tmp_path,
                          log_message=lambda msg, **kw: logs.append(msg))

    pane_ops.launch_qa_item(app, "not-a-qualified-id")

    assert "Invalid QA item id" in logs[-1]
    assert "pm qa list" in logs[-1]


def test_qa_scaffold_already_exists_names_the_edit_command(tmp_path):
    """`pm qa add-instruction` on an existing file must say how to edit it."""
    from unittest import mock

    from pm_core.cli import qa as qa_mod

    existing = tmp_path / "qa" / "instructions" / "foo.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("# existing\n")

    with mock.patch.object(qa_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(qa_mod.qa, ["add-instruction", "foo"])

    assert result.exit_code == 1, result.output
    assert "Already exists" in result.output
    assert "pm qa edit foo" in result.output


def test_qa_mocks_add_existing_names_the_edit_command(tmp_path):
    """The mock scaffolder's already-exists refusal names the editor."""
    from unittest import mock

    from pm_core.cli import qa as qa_mod

    existing = tmp_path / "qa" / "mocks" / "foo.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("# existing\n")

    with mock.patch.object(qa_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(qa_mod.qa, ["mocks", "add", "foo"])

    assert result.exit_code == 1, result.output
    assert "Mock already exists" in result.output
    assert "pm qa mocks edit foo" in result.output


# ---------------------------------------------------------------------------
# The sweep's last two dead ends (review-loop 6a82 i6)
# ---------------------------------------------------------------------------

def test_signal_stale_tui_names_pm_session(tmp_path, monkeypatch):
    """A TUI that vanished between validation and the signal names `pm session`.

    ``_signal_tui``'s stale-owner message said only "restart the TUI" — but
    the process is gone and its pidfile is removed, so there is no TUI to
    press Ctrl+R in.  This is the same dead end the ``_validate_tui_owner``
    messages fixed in i5; the signal path was missed.
    """
    from pm_core import tui_pidfile
    from pm_core.cli import helpers

    pidfile = tmp_path / "tui.pid"
    pidfile.write_text("descriptor")
    desc = tui_pidfile.TuiPidfile(
        pid=1234, caps=frozenset({tui_pidfile.CAP_COMMAND}), starttime=1)

    monkeypatch.setattr(
        helpers, "_validate_tui_owner",
        lambda session: (pidfile, "descriptor", desc, None))
    monkeypatch.setattr(
        helpers, "_tui_command_queue_for_session",
        lambda session: tmp_path / "queue")
    monkeypatch.setattr(
        helpers, "_signal_tui", lambda pid, sig, starttime=None: "process is not running")

    result = helpers.submit_tui_command("pm-x", "pr list")

    assert result.ok is False
    assert result.reason == "stale_pidfile"
    assert "pm session" in result.message
    assert "restart the TUI" not in result.message


def test_empty_tui_pidfile_names_both_restart_routes(tmp_path, monkeypatch):
    """A permanently empty pidfile has no TUI to restart either.

    The "still starting up" message named only Ctrl+R.  If the TUI was
    killed between its O_EXCL create and its first write the file stays
    empty forever, and the caller may have no TUI at all.
    """
    from pm_core.cli import helpers

    pidfile = tmp_path / "tui.pid"
    pidfile.write_text("")
    monkeypatch.setattr(helpers, "_tui_pidfile_for_session",
                        lambda session: pidfile)

    _path, _raw, _desc, error = helpers._validate_tui_owner("pm-x")

    assert error is not None and error.ok is False
    assert "pm session" in error.message
    assert "Ctrl+R" in error.message


def test_qa_author_artifact_existing_names_the_edit_command(tmp_path):
    """`pm qa author-artifact` on an existing recipe is not a dead end.

    The other two scaffolders (`add-instruction`, `mocks add`) name the
    editor in their already-exists refusal; this third site was missed.
    """
    from unittest import mock

    from pm_core.cli import qa as qa_mod

    existing = tmp_path / "qa" / "artifacts" / "foo.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("# existing\n")

    with mock.patch.object(qa_mod, "state_root", return_value=tmp_path):
        result = CliRunner().invoke(qa_mod.qa, ["author-artifact", "foo"])

    assert result.exit_code == 1, result.output
    assert "Already exists" in result.output
    assert "pm qa edit foo" in result.output


def test_qa_launch_invalid_item_id_names_the_library():
    """The CLI's malformed-id refusal names the listing command.

    Its TUI sibling (`launch_qa_item`) was fixed in i5; the CLI surface
    gave only the expected format, which does not say which ids exist.
    """
    from pm_core.cli import qa as qa_mod

    result = CliRunner().invoke(qa_mod.qa, ["launch", "not-a-qualified-id"])

    assert result.exit_code == 1, result.output
    assert "Invalid QA item id" in result.output
    assert "pm qa list" in result.output


# ---------------------------------------------------------------------------
# i8: the remaining remedy-less surfaces
# ---------------------------------------------------------------------------

def test_autostart_owner_messages_name_pm_session(tmp_path):
    """`pm autostart …` in a plain shell names the command that starts a TUI.

    The "no pm session" branch already did, but the three pidfile branches
    (missing / stale / dead pid) said only "is not running" — a dead end for
    a caller with no TUI.  They surface from the documented `pm autostart`
    commands, not just internally (the same class as the stale-pidfile
    messages fixed in `helpers._validate_tui_owner`).
    """
    from unittest import mock

    from pm_core.cli import autostart as autostart_mod

    missing = tmp_path / "missing.pid"
    with mock.patch.object(autostart_mod, "_tui_pidfile_for_session",
                           return_value=missing):
        with pytest.raises(autostart_mod._Fail) as exc:
            autostart_mod._resolve_owner("pm-x")
    assert "pm session" in exc.value.message, exc.value.message

    stale = tmp_path / "stale.pid"
    stale.write_text("")  # unreadable -> stale
    with mock.patch.object(autostart_mod, "_tui_pidfile_for_session",
                           return_value=stale):
        with pytest.raises(autostart_mod._Fail) as exc:
            autostart_mod._resolve_owner("pm-x")
    assert "pm session" in exc.value.message, exc.value.message

    # The dead-pid branch: a readable pid whose process is gone.  Patch
    # `kill` rather than pick a "free" pid, which could be reused.
    dead = tmp_path / "dead.pid"
    dead.write_text("999999")
    with mock.patch.object(autostart_mod, "_tui_pidfile_for_session",
                           return_value=dead), \
            mock.patch.object(autostart_mod.os, "kill",
                              side_effect=ProcessLookupError):
        with pytest.raises(autostart_mod._Fail) as exc:
            autostart_mod._resolve_owner("pm-x")
    assert "pm session" in exc.value.message, exc.value.message


def test_autostart_unknown_and_terminal_prs_name_the_listing(tmp_path):
    """`pm autostart add` refusals name how to see the real ids/statuses.

    "unknown PR id(s)" / "already merged/closed" stopped at the refusal, so
    the operator had to guess the listing command.
    """
    from unittest import mock

    from pm_core.cli import autostart as autostart_mod

    data = {"project": {"repo_id": "r"},
            "prs": [{"id": "pr-001", "title": "T", "status": "pending"}]}
    with mock.patch.object(autostart_mod, "state_root",
                           return_value=tmp_path), \
            mock.patch.object(autostart_mod.store, "load", return_value=data):
        with pytest.raises(autostart_mod._Fail) as exc:
            autostart_mod._validate(("nope",), for_add=True)
    assert "pm pr list" in exc.value.message, exc.value.message

    merged = {"project": {"repo_id": "r"},
              "prs": [{"id": "pr-001", "title": "T", "status": "merged"}]}
    with mock.patch.object(autostart_mod, "state_root",
                           return_value=tmp_path), \
            mock.patch.object(autostart_mod.store, "load", return_value=merged):
        with pytest.raises(autostart_mod._Fail) as exc:
            autostart_mod._validate(("pr-001",), for_add=True)
    assert "pm pr list" in exc.value.message, exc.value.message


def test_signoff_skip_qa_refusal_does_not_advertise_qa(tmp_path):
    """Under `skip_qa` the refusal must not list `qa` as an expected state.

    The message said "sign-off runs after review (expected qa, in_review,
    sign_off)" — the expected list contradicted the sentence.  `qa` stays
    accepted (a record can predate the setting) but is not advertised.
    """
    result = _lifecycle_refusal(tmp_path, ["signoff", "pr-001"],
                                status="in_progress", skip_qa=True)
    assert result.exit_code == 1, result.output
    out = " ".join(result.output.split())
    assert "sign-off runs after review" in out
    assert "expected in_review, sign_off" in out


@pytest.mark.parametrize("cmd", ["pr qa --help", "pr qa -h",
                                 "pr start --help"])
def test_command_bar_help_flag_opens_the_help_screen(cmd):
    """`--help` / `-h` works in the command bar, like every other surface.

    The bar runs commands through the CLI and logs only the last stdout
    line, so a multi-line `--help` came out as one useless line — and
    `pr qa --help` (the command this PR exists to make discoverable) died
    as "unknown QA option".  It now opens the same screen `help` opens.
    """
    from types import SimpleNamespace

    from pm_core.tui import pr_view

    calls = []
    app = SimpleNamespace(
        action_unfocus_command=lambda: calls.append("unfocus"),
        action_show_help=lambda: calls.append("help"),
        log_message=lambda *a, **k: None,
        _inflight_pr_action=None)

    pr_view.handle_command_submitted(app, cmd)

    assert calls == ["unfocus", "help"], calls
    # The guard loop runs after the help branch; nothing may be left armed.
    assert app._inflight_pr_action is None


@pytest.mark.parametrize("cmd", [
    "pr note add pr-001 'see --help'",
    # A flag *word* inside a multi-word quoted phrase is still one value to
    # the CLI.  Splitting on whitespace instead of with `shlex` matched the
    # bare `-h` / `--help` token and opened the help screen instead of
    # running the command.
    "pr note add pr-001 'mention -h as a flag'",
    'pr note add pr-001 "see --help for details"',
    "pr add 'Fix -h handling'",
])
def test_command_bar_help_flag_leaves_quoted_text_alone(monkeypatch, cmd):
    """A `--help` inside a quoted argument is text, not the help flag.

    The check tokenizes with `shlex` — the same splitter `run_command` uses
    to build the CLI's argv — so a quoted phrase reaches the command as one
    value and cannot open the help screen; a bare `--help` is Click's own
    eager flag, so intercepting that matches the CLI.
    """
    from types import SimpleNamespace

    from pm_core.tui import pr_view

    ran = []
    monkeypatch.setattr(pr_view, "run_command",
                        lambda *a, **k: ran.append(a[1]))
    shown = []
    app = SimpleNamespace(
        action_unfocus_command=lambda: None,
        action_show_help=lambda: shown.append(True),
        log_message=lambda *a, **k: None,
        _inflight_pr_action=None, _plans_visible=False, _qa_visible=False,
        _root=None,
        query_one=lambda *a, **k: SimpleNamespace(focus=lambda: None))

    pr_view.handle_command_submitted(app, cmd)

    assert shown == [], shown
    assert ran == [cmd], ran


@pytest.mark.parametrize("stderr_text, expected", [
    # R35/E18: the remedy is printed first, trailing context after it.
    ("Unknown PR IDs in --depends-on: bogus — run 'pm pr list' to see "
     "every PR.\nAvailable PRs: pr-1, pr-2\n",
     "Unknown PR IDs in --depends-on: bogus — run 'pm pr list' to see "
     "every PR."),
    ("Note 'bogus' not found on pr-1 — run 'pm pr note list pr-1' to see "
     "them.\nAvailable notes:\n  note-1: First note\n",
     "Note 'bogus' not found on pr-1 — run 'pm pr note list pr-1' to see "
     "them."),
    # Backticked and bare spellings are remedies too.
    ("No PRs.\nRun `pm pr list` to see them.\n", "Run `pm pr list` to see them."),
    # Click's usage block: the corrective line is the last one.
    ("Usage: pm pr qa [OPTIONS]\nTry 'pm pr qa --help' for help.\n\n"
     "Error: No such option: --nope\n", "Error: No such option: --nope"),
    # A traceback's final line stays the last line.
    ("Traceback (most recent call last):\n  ...\nValueError: boom\n",
     "ValueError: boom"),
    ("", ""),
])
def test_pick_error_line_prefers_the_remedy(stderr_text, expected):
    """The bar shows one line, so a failure logs the corrective one."""
    assert command_surface.pick_error_line(stderr_text) == expected
