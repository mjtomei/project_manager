"""Tab completion shared by the prefix+M popup and the TUI command bar."""

from __future__ import annotations

import os
from unittest import mock

import click
import pytest

from pm_core.cli.completion import PmCompleter, common_prefix

PROJECT_YAML = """\
project: {name: demo, repo: /tmp/demo, base_branch: master, backend: local}
plans:
- {id: plan-001, name: Alpha, status: active}
- {id: plan-abc, name: Beta, status: active}
prs:
- {id: pr-0000001, title: one, branch: b1, status: in_progress, gh_pr_number: 193}
- {id: pr-0000002, title: two, branch: b2, status: merged, gh_pr_number: 195}
- {id: pr-abc1234, title: three, branch: b3, status: pending}
"""


@pytest.fixture
def root(tmp_path):
    pm = tmp_path / "pm"
    pm.mkdir()
    (pm / "project.yaml").write_text(PROJECT_YAML)
    return pm


def _toy_group() -> click.Group:
    @click.group()
    def top():
        pass

    @top.group()
    def pr():
        pass

    @pr.command("edit")
    @click.argument("pr_id")
    @click.option("--plan", default=None)
    @click.option("--depends-on", "depends_on", default=None)
    @click.option("--draft", is_flag=True)
    def pr_edit(pr_id, plan, depends_on, draft):
        pass

    @pr.group("note")
    def pr_note():
        pass

    @pr_note.command("add")
    @click.argument("pr_id")
    @click.argument("text")
    def note_add(pr_id, text):
        pass

    @pr.command("spec")
    @click.argument("pr_id")
    @click.argument("phase", type=click.Choice(["impl", "qa"]))
    def pr_spec(pr_id, phase):
        pass

    @top.group()
    def plan():
        pass

    @plan.command("review")
    @click.argument("plan_id")
    def plan_review(plan_id):
        pass

    @top.command("_secret", hidden=True)
    def secret():
        pass

    @top.command("status", hidden=True)
    def hidden_status():
        pass

    return top


@pytest.fixture
def toy(root):
    return PmCompleter(root, group=_toy_group())


def _words(c: PmCompleter, line: str) -> list[str]:
    return c.complete_line(line)[1]


def test_top_level_subcommands_skip_hidden(toy):
    assert _words(toy, "") == ["plan", "pr", "review-loop"]
    assert _words(toy, "p") == ["plan", "pr"]


def test_nested_group_and_positional_pr_ids(toy):
    assert _words(toy, "pr ") == ["edit", "note", "spec"]
    assert _words(toy, "pr edit ") == [
        "#193", "#195", "pr-0000001", "pr-0000002", "pr-abc1234"]
    assert _words(toy, "pr note add ") == _words(toy, "pr edit ")
    # Second positional of note add is free text: nothing to offer.
    assert _words(toy, "pr note add pr-abc1234 ") == []


def test_gh_number_prefix(toy):
    start, words = toy.complete_line("pr edit #19")
    assert start == len("pr edit ")
    assert words == ["#193", "#195"]
    assert _words(toy, "pr edit pr-a") == ["pr-abc1234"]


def test_plan_ids_and_choice(toy):
    assert _words(toy, "plan review ") == ["plan-001", "plan-abc"]
    assert _words(toy, "pr spec pr-0000001 ") == ["impl", "qa"]
    assert _words(toy, "pr spec pr-0000001 q") == ["qa"]


def test_options(toy):
    assert _words(toy, "pr edit pr-1 --") == ["--depends-on", "--draft", "--help", "--plan"]
    assert _words(toy, "pr edit pr-1 --plan ") == ["plan-001", "plan-abc"]
    assert _words(toy, "pr edit pr-1 --plan=plan-a") == ["--plan=plan-abc"]
    assert _words(toy, "pr edit --depends-on pr-0000001,pr-a") == [
        "pr-0000001,pr-abc1234"]
    # A flag takes no value: the next word is the positional again.
    assert "pr-abc1234" in _words(toy, "pr edit --draft ")
    # The option value is consumed, so the PR id is still positional 0.
    assert "#193" in _words(toy, "pr edit --plan plan-001 ")


def test_unknown_word_offers_nothing(toy):
    assert _words(toy, "bogus ") == []
    assert _words(toy, "pr bogus ") == []


def test_review_loop_carve_out(toy):
    assert _words(toy, "review-loop ")[0] == "start"
    assert "pr-abc1234" in _words(toy, "review-loop start ")
    assert _words(toy, "review-loop start pr-abc1234 ") == []


def test_unbalanced_quote_does_not_raise(toy):
    assert _words(toy, "pr note add pr-1 'unterminated ") == []


def test_reloads_when_project_yaml_changes(toy, root):
    assert "pr-new0001" not in _words(toy, "pr edit ")
    text = PROJECT_YAML + "- {id: pr-new0001, title: new, branch: b4, status: pending}\n"
    (root / "project.yaml").write_text(text)
    st = (root / "project.yaml").stat()
    os.utime(root / "project.yaml", ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert "pr-new0001" in _words(toy, "pr edit ")


def test_malformed_yaml_keeps_previous_ids(toy, root):
    assert "pr-abc1234" in _words(toy, "pr edit ")
    (root / "project.yaml").write_text("prs: [unclosed\n")
    assert "pr-abc1234" in _words(toy, "pr edit ")


def test_no_root_completes_commands_only():
    c = PmCompleter(None, group=_toy_group())
    assert _words(c, "pr ") == ["edit", "note", "spec"]
    assert _words(c, "pr edit ") == []


def test_loads_project_once_while_unchanged(toy):
    with mock.patch("pm_core.cli.completion.store.load",
                    wraps=__import__("pm_core.store", fromlist=["load"]).load) as load:
        _words(toy, "pr edit ")
        _words(toy, "pr edit #")
        _words(toy, "plan review ")
    assert load.call_count == 1


def test_real_cli_tree(root):
    c = PmCompleter(root)
    top = _words(c, "")
    assert {"pr", "plan", "session", "review-loop"} <= set(top)
    assert not any(w.startswith("_") for w in top)
    assert "edit" in _words(c, "pr ")
    assert _words(c, "pr edit #19") == ["#193", "#195"]
    assert "pr-abc1234" in _words(c, "pr note add ")
    assert _words(c, "plan breakdown ") == ["plan-001", "plan-abc"]
    assert "--depends-on" in _words(c, "pr add 'x' --")
    assert _words(c, "pr add 'x' --plan pl") == ["plan-001", "plan-abc"]


def test_readline_state_protocol(toy):
    fake_rl = mock.MagicMock()
    fake_rl.get_line_buffer.return_value = "pr edit #19"
    fake_rl.get_endidx.return_value = len("pr edit #19")
    with mock.patch.dict("sys.modules", {"readline": fake_rl}):
        got = []
        state = 0
        while (w := toy.readline_complete("#19", state)) is not None:
            got.append(w)
            state += 1
    assert got == ["#193", "#195"]


def test_common_prefix():
    assert common_prefix(["pr-abc1", "pr-abd2"]) == "pr-ab"
    assert common_prefix(["x"]) == "x"
    assert common_prefix([]) == ""
