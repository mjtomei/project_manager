"""App-level tests for fuzzy ``pr select`` / ``plan select`` and ]/[ cycling.

Drives the real TechTree, CommandBar, ``pr_view.handle_command_submitted``
and ProjectManagerApp's binding/check_action/action methods inside a small
host App on a disposable temp project (no tmux, no live TUI).
"""

import asyncio
import functools

import pytest
from textual import events
from textual.app import App
from textual.containers import Container
from textual.widget import Widget

from pm_core import store
from pm_core.tui import pr_view
from pm_core.tui.app import ProjectManagerApp
from pm_core.tui.command_bar import CommandBar, CommandSubmitted
from pm_core.tui.tech_tree import TechTree


def async_test(coro):
    @functools.wraps(coro)
    def wrapper(*args, **kwargs):
        asyncio.run(coro(*args, **kwargs))
    return wrapper


def _pr(pr_id, title="", plan=None, status="pending", gh=None, desc="",
        deps=None):
    pr = {"id": pr_id, "title": title, "description": desc, "status": status,
          "branch": f"b/{pr_id}", "depends_on": deps or []}
    if plan:
        pr["plan"] = plan
    if gh is not None:
        pr["gh_pr_number"] = gh
    return pr


PLANS = [
    {"id": "tui-ux", "name": "TUI and UX improvements", "status": "active"},
    {"id": "watchers", "name": "Watcher framework and session health",
     "status": "active"},
    {"id": "empty", "name": "Nothing here yet", "status": "active"},
    {"id": "watch-merged", "name": "Watch archive", "status": "active"},
]

PRS = [
    _pr("pr-111aaaa", "Command bar polish", plan="tui-ux", gh=101),
    _pr("pr-942aa21", "Spec generation step", plan="tui-ux", gh=125,
        desc="Generate an implementation spec"),
    _pr("pr-333cccc", "Watcher restart", plan="watchers", gh=130),
    _pr("pr-444dddd", "Watcher health probe", plan="watchers",
        deps=["pr-333cccc"]),
    _pr("pr-555eeee", "Old spec cleanup", plan="tui-ux", status="merged",
        gh=90),
    _pr("pr-666ffff", "Archived watcher", plan="watch-merged",
        status="merged"),
    _pr("pr-777gggg", "Standalone helper"),
]


class _Pane(Widget, can_focus=True):
    pass


class Host(App):
    BINDINGS = [b for b in ProjectManagerApp.BINDINGS
                if b.action in ("fuzzy_next", "fuzzy_prev")]

    check_action = ProjectManagerApp.check_action
    action_fuzzy_next = ProjectManagerApp.action_fuzzy_next
    action_fuzzy_prev = ProjectManagerApp.action_fuzzy_prev
    _command_bar_in_use = ProjectManagerApp._command_bar_in_use
    _focus_current_view = ProjectManagerApp._focus_current_view
    # Key order behind a command-bar Enter (and the release after submit).
    on_event = ProjectManagerApp.on_event
    _dispatch_terminal_key = ProjectManagerApp._dispatch_terminal_key
    _release_held_keys = ProjectManagerApp._release_held_keys
    _command_bar_focused = ProjectManagerApp._command_bar_focused
    on_command_submitted = ProjectManagerApp.on_command_submitted
    HELD_KEYS_TIMEOUT = ProjectManagerApp.HELD_KEYS_TIMEOUT

    def __init__(self, root, data):
        super().__init__()
        self._root = root
        self._data = data
        self._write_queue = None
        self._command_pending = False
        self._command_buffer = []
        self._plans_visible = False
        self._qa_visible = False
        self._current_guide_step = None
        self._inflight_pr_action = None
        self._fuzzy_results = []
        self._fuzzy_index = 0
        self._fuzzy_kind = ""
        self._held_keys = None
        self._held_keys_timer = None
        self.messages = []
        self.normal_view_calls = 0

    def compose(self):
        with Container(id="tree-container"):
            yield TechTree(id="tech-tree")
        yield _Pane(id="plans-pane")
        yield _Pane(id="qa-pane")
        yield CommandBar(id="command-bar")

    def on_mount(self):
        tree = self.query_one("#tech-tree", TechTree)
        tree.update_plans(self._data.get("plans") or [])
        tree.update_prs(self._data.get("prs") or [])
        tree.focus()

    def log_message(self, msg, *args, **kwargs):
        self.messages.append(msg)
        return len(self.messages)

    def _show_normal_view(self):
        self.normal_view_calls += 1
        self._plans_visible = False
        self._qa_visible = False

    def _capture_frame(self, *args, **kwargs):
        pass

    # helpers
    @property
    def tree(self) -> TechTree:
        return self.query_one("#tech-tree", TechTree)

    @property
    def last(self) -> str:
        return self.messages[-1] if self.messages else ""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr("pm_core.paths.get_global_setting",
                        lambda name, *a, **k: False)
    root = tmp_path / "pm"
    root.mkdir()
    data = {"project": {"name": "t", "repo": "/r", "base_branch": "master",
                        "active_pr": "pr-777gggg"},
            "plans": [dict(p) for p in PLANS],
            "prs": [dict(p) for p in PRS]}
    store.save(data, root)
    return root


def _app(root, **overrides):
    if overrides:
        # On disk too: without a write queue, persisting active_pr goes
        # through store.locked_update, which reloads app._data from disk.
        data = store.load(root)
        data.update(overrides)
        store.save(data, root)
    return Host(root, store.load(root))


async def _cmd(app, pilot, text):
    pr_view.handle_command_submitted(app, text)
    await pilot.pause()


def _active(root):
    return store.load(root)["project"]["active_pr"]


# ---------------------------------------------------------------------------
# pr select
# ---------------------------------------------------------------------------

@async_test
async def test_pr_select_title_match_moves_cursor_and_persists(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _cmd(app, pilot, "pr select spec")
        assert app.tree.selected_pr_id == "pr-942aa21"
        # title+description (300) beats the merged "Old spec cleanup" (200),
        # which is still shown: hide_merged is off in this fixture.
        assert app._fuzzy_kind == "pr"
        assert app._fuzzy_results == ["pr-942aa21", "pr-555eeee"]
        from textual.content import Content
        assert Content.from_markup(app.last).plain == \
            "Selected: #125 Spec generation step [2 matches]"
        assert _active(project) == "pr-942aa21"
        assert app._data["project"]["active_pr"] == "pr-942aa21"


@async_test
async def test_pr_select_via_command_bar_typing(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.query_one("#command-bar", CommandBar).focus()
        await pilot.pause()
        await pilot.press(*"pr select watcher h", "enter")
        await pilot.pause()
        assert app.tree.selected_pr_id == "pr-444dddd"
        assert isinstance(app.focused, TechTree)


@pytest.mark.parametrize("query, expected", [
    ("pr-942aa21", "pr-942aa21"),
    ("#125", "pr-942aa21"),
    ("125", "pr-942aa21"),
    ("PR-333CCCC", "pr-333cccc"),
    ("pr-44", "pr-444dddd"),
])
def test_pr_select_exact_and_partial_ids(project, query, expected):
    @async_test
    async def run():
        app = _app(project)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            await _cmd(app, pilot, f"pr select {query}")
            assert app.tree.selected_pr_id == expected
            assert _active(project) == expected
    run()


@async_test
async def test_exact_id_of_filtered_pr_does_not_land_elsewhere(project):
    """An exact id names one PR; if it is filtered out, the cursor must not
    move to another PR that merely mentions the id."""
    prs = [dict(p) for p in PRS]
    prs[0]["description"] = "follow-up to pr-555eeee"
    app = _app(project, prs=prs)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.tree._hide_merged = True
        app.tree._recompute()
        before = app.tree.selected_pr_id
        app._fuzzy_results = ["pr-333cccc"]
        await _cmd(app, pilot, "pr select pr-555eeee")
        assert app.tree.selected_pr_id == before
        assert "hidden by the current filters" in app.last
        assert app._fuzzy_results == []
        assert _active(project) == "pr-777gggg"


@async_test
async def test_filtered_matches_skipped_and_counted(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.tree._hide_merged = True
        app.tree._recompute()
        await _cmd(app, pilot, "pr select spec")
        assert app._fuzzy_results == ["pr-942aa21"]
        assert "1 hidden by filters" in app.last
        # Every match filtered -> no move, explained
        await _cmd(app, pilot, "pr select archived")
        assert app.tree.selected_pr_id == "pr-942aa21"
        assert "No visible PR matches" in app.last
        assert app._fuzzy_results == []


@async_test
async def test_tie_prefers_match_nearest_cursor_in_tree_order(project):
    """pr-333cccc and pr-444dddd both score 250 for "watcher" (title +
    plan id); the one nearer the tree cursor wins."""
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        for pr_id in ("pr-444dddd", "pr-333cccc", "pr-444dddd"):
            app.tree.select_pr(pr_id)
            await _cmd(app, pilot, "pr select watcher")
            assert app.tree.selected_pr_id == pr_id
            assert app._fuzzy_results[-1] == "pr-666ffff"  # 200 < 250


@async_test
async def test_pr_select_no_match_and_usage(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _cmd(app, pilot, "pr select watcher")
        kept = list(app._fuzzy_results)
        assert len(kept) == 3
        # Usage error: no match command ran -> list untouched
        await _cmd(app, pilot, "pr select")
        assert app.last == "Usage: pr select <query>"
        assert app._fuzzy_results == kept
        await _cmd(app, pilot, "pr select    ")
        assert app._fuzzy_results == kept
        # A failed new search replaces (clears) the list
        await _cmd(app, pilot, "pr select zzzz-nothing")
        assert "No PR matches for 'zzzz-nothing'" in app.last
        assert app._fuzzy_results == []


@async_test
async def test_pr_select_quotes_and_markup_are_safe(project):
    prs = [dict(p) for p in PRS] + [
        _pr("pr-888hhhh", "[WIP] user's [b]draft[/b]", gh=140)]
    app = _app(project, prs=prs)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _cmd(app, pilot, "pr select user's")
        assert app.tree.selected_pr_id == "pr-888hhhh"
        await _cmd(app, pilot, 'pr select "[wip]"')
        assert app.tree.selected_pr_id == "pr-888hhhh"
        from textual.content import Content
        plain = Content.from_markup(app.last).plain
        assert "[WIP] user's [b]draft[/b]" in plain
        await _cmd(app, pilot, "pr select [/nope")
        Content.from_markup(app.last)  # must not raise


# ---------------------------------------------------------------------------
# plan select
# ---------------------------------------------------------------------------

@async_test
async def test_plan_select_expands_collapsed_plan_and_goes_to_first_pr(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.tree._hidden_plans.add("watchers")
        app.tree._recompute()
        assert "pr-333cccc" not in app.tree._ordered_ids
        # On the collapsed label: "watchers" and "watch-merged" both score
        # 700 (id prefix + name); the tie goes to the plan nearer the cursor.
        app.tree.selected_index = app.tree._ordered_ids.index("_hidden:watchers")
        await _cmd(app, pilot, "plan select watch")
        assert "watchers" not in app.tree._hidden_plans
        first = next(pid for pid in app.tree._ordered_ids
                     if app.tree._pr_map[pid].get("plan") == "watchers")
        assert app.tree.selected_pr_id == first == "pr-333cccc"
        assert _active(project) == "pr-333cccc"
        assert app._fuzzy_kind == "plan"
        assert app._fuzzy_results[0] == "watchers"
        from textual.content import Content
        assert Content.from_markup(app.last).plain == (
            "Plan: watchers: Watcher framework and session health"
            " → #130 [2 matches]")


@async_test
async def test_plan_tie_prefers_plan_nearest_cursor_in_tree_order(project):
    """Tree order (plan groups sorted by id) decides plan ties, not the
    plans' order in project.yaml: there "watchers" sits next to "tui-ux",
    but in the tree "watch-merged" does."""
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        order = app.tree._ordered_ids
        assert order.index("pr-666ffff") < order.index("pr-333cccc")
        app.tree.select_pr("pr-111aaaa")  # tui-ux, top of the tree
        await _cmd(app, pilot, "plan select watch")
        assert app.tree.selected_pr_id == "pr-666ffff"
        assert app._fuzzy_results == ["watch-merged", "watchers"]
        app.tree.select_pr("pr-777gggg")  # standalone, bottom of the tree
        await _cmd(app, pilot, "plan select watch")
        assert app.tree.selected_pr_id == "pr-333cccc"
        assert app._fuzzy_results == ["watchers", "watch-merged"]


@async_test
async def test_plan_tie_ranks_plan_with_nothing_shown_last(project):
    """A tied plan whose PRs are all filtered out never outranks one the
    cursor can reach: "watch-merged" (merged only) loses the tie."""
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app.tree._hide_merged = True
        app.tree._recompute()
        app.tree.select_pr("pr-111aaaa")
        await _cmd(app, pilot, "plan select watch")
        assert app.tree.selected_pr_id == "pr-333cccc"
        assert app._fuzzy_results == ["watchers"]


@async_test
async def test_plan_select_first_pr_follows_tree_order_not_yaml_order(project):
    prs = [dict(p) for p in PRS]
    # In YAML order the dependent PR comes first; the tree lays the root first.
    i3 = next(i for i, p in enumerate(prs) if p["id"] == "pr-333cccc")
    i4 = next(i for i, p in enumerate(prs) if p["id"] == "pr-444dddd")
    prs[i3], prs[i4] = prs[i4], prs[i3]
    app = _app(project, prs=prs)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _cmd(app, pilot, "plan select watchers")
        order = [pid for pid in app.tree._ordered_ids
                 if app.tree._pr_map.get(pid, {}).get("plan") == "watchers"]
        assert app.tree.selected_pr_id == order[0]


@async_test
async def test_plan_select_empty_plan_and_all_filtered(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        before = app.tree.selected_pr_id
        app._fuzzy_results = ["pr-111aaaa"]
        await _cmd(app, pilot, "plan select nothing here")
        assert "has no PRs" in app.last
        assert app._fuzzy_results == []
        assert app.tree.selected_pr_id == before
        app.tree._hide_merged = True
        app.tree._recompute()
        await _cmd(app, pilot, "plan select watch-merged")
        assert "all 1 PR hidden by filters" in app.last
        assert app.tree.selected_pr_id == before


@async_test
async def test_plan_select_cycles_by_plan(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _cmd(app, pilot, "plan select watch")
        assert set(app._fuzzy_results) == {"watchers", "watch-merged"}
        first_plan = app._fuzzy_results[0]
        await pilot.press("right_square_bracket")
        await pilot.pause()
        second_plan = app._fuzzy_results[1]
        sel = app.tree.selected_pr_id
        assert app.tree._pr_map[sel].get("plan") == second_plan
        assert app.last.startswith("Match 2/2:")
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert app.tree._pr_map[app.tree.selected_pr_id].get("plan") == first_plan


# ---------------------------------------------------------------------------
# ] / [ cycling
# ---------------------------------------------------------------------------

@async_test
async def test_cycle_forward_backward_wraps_and_persists(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _cmd(app, pilot, "pr select watcher")
        results = list(app._fuzzy_results)
        assert len(results) == 3
        assert app.tree.selected_pr_id == results[0]
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert app.tree.selected_pr_id == results[1]
        assert _active(project) == results[1]
        assert app.last.startswith("Match 2/3:")
        await pilot.press("right_square_bracket", "right_square_bracket")
        await pilot.pause()
        assert app.tree.selected_pr_id == results[0]  # wrapped
        await pilot.press("left_square_bracket")
        await pilot.pause()
        assert app.tree.selected_pr_id == results[2]
        assert app.last.startswith("Match 3/3:")


@async_test
async def test_new_search_replaces_list_across_kinds(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _cmd(app, pilot, "pr select watcher")
        assert app._fuzzy_kind == "pr"
        await _cmd(app, pilot, "plan select tui")
        assert app._fuzzy_kind == "plan"
        assert app._fuzzy_results == ["tui-ux"]
        await _cmd(app, pilot, "pr select spec")
        assert app._fuzzy_kind == "pr"
        assert "tui-ux" not in app._fuzzy_results


@async_test
async def test_cycle_without_results(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        before = app.tree.selected_pr_id
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert "No match results to cycle" in app.last
        assert app.tree.selected_pr_id == before


@async_test
async def test_cycle_skips_entries_no_longer_navigable(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _cmd(app, pilot, "pr select spec")
        assert app._fuzzy_results == ["pr-942aa21", "pr-555eeee"]
        app.tree._hide_merged = True
        app.tree._recompute()
        await pilot.press("right_square_bracket")
        await pilot.pause()
        # pr-555eeee is now hidden -> skipped, wraps back to pr-942aa21
        assert app.tree.selected_pr_id == "pr-942aa21"
        assert app.last.startswith("Match 1/2:")


@async_test
async def test_brackets_typed_in_command_bar_do_not_cycle(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        await _cmd(app, pilot, "pr select watcher")
        sel = app.tree.selected_pr_id
        idx = app._fuzzy_index
        bar = app.query_one("#command-bar", CommandBar)
        bar.focus()
        await pilot.pause()
        await pilot.press("left_square_bracket", "right_square_bracket")
        await pilot.pause()
        assert bar.value == "[]"
        assert app._fuzzy_index == idx
        assert app.tree.selected_pr_id == sel


@async_test
async def test_key_after_command_bar_enter_waits_for_the_command(project):
    """QA repro (pr-6aa74c6 s7): under a stream of reloads the Enter's trip
    back up to the App (Input's ``enter`` binding) outlasted the gap to the
    next key, so ``]`` was forwarded to the still-focused bar and
    ``pr select spec]`` was submitted ("No PR matches").  Posting both keys
    back to back reproduces that ordering deterministically."""
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        bar = app.query_one("#command-bar", CommandBar)
        bar.focus()
        await pilot.pause()
        await pilot.press(*"pr select watcher")
        app.post_message(events.Key("enter", "\r"))
        app.post_message(events.Key("right_square_bracket", "]"))
        for _ in range(3):
            await pilot.pause()
        assert not any("No PR matches" in m for m in app.messages)
        assert app.messages[-2].startswith("Selected:")
        assert app.messages[-1].startswith("Match 2/")
        assert app.tree.selected_pr_id == app._fuzzy_results[1]
        assert bar.value == ""
        assert isinstance(app.focused, TechTree)
        assert app._held_keys is None


@async_test
async def test_keys_held_behind_empty_enter_are_replayed(project):
    """An Enter on an empty bar submits nothing and keeps focus there; the
    keys held behind it still arrive, in order, in the bar."""
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        bar = app.query_one("#command-bar", CommandBar)
        bar.focus()
        await pilot.pause()
        app.post_message(events.Key("enter", "\r"))
        for ch in "pr":
            app.post_message(events.Key(ch, ch))
        for _ in range(3):
            await pilot.pause()
        assert bar.value == "pr"
        assert app.focused is bar
        assert app._held_keys is None
        assert app.messages == []


# ---------------------------------------------------------------------------
# View switching / focus
# ---------------------------------------------------------------------------

@async_test
async def test_select_from_plans_view_switches_to_tree(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app._plans_visible = True
        await _cmd(app, pilot, "pr select watcher restart")
        assert app.normal_view_calls == 1
        assert not app._plans_visible
        assert isinstance(app.focused, TechTree)
        app._qa_visible = True
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert app.normal_view_calls == 2


@async_test
async def test_no_match_from_plans_view_stays_in_plans(project):
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        app._plans_visible = True
        await _cmd(app, pilot, "plan select zzzz")
        assert app._plans_visible
        assert app.normal_view_calls == 0
        assert app.focused is app.query_one("#plans-pane")
        app._plans_visible = False
        app._qa_visible = True
        await _cmd(app, pilot, "pr select")
        assert app.focused is app.query_one("#qa-pane")


@pytest.mark.parametrize("view, pane", [
    ("plans", "#plans-pane"), ("qa", "#qa-pane"), (None, "#tech-tree")])
def test_escape_from_command_bar_focuses_current_view(project, view, pane):
    """``_focus_current_view`` is shared by Esc in the command bar and the
    select commands: both land on the visible view's widget."""
    @async_test
    async def run():
        app = _app(project)
        async with app.run_test(size=(160, 50)) as pilot:
            await pilot.pause()
            app._plans_visible = view == "plans"
            app._qa_visible = view == "qa"
            bar = app.query_one("#command-bar", CommandBar)
            bar.focus()
            bar.value = "pr sel"
            await pilot.pause()
            ProjectManagerApp.action_unfocus_command(app)
            await pilot.pause()
            assert bar.value == ""
            assert app.focused is app.query_one(pane)
    run()


@async_test
async def test_other_commands_keep_exact_resolution(project):
    """Fuzzy resolution is confined to the select commands: ``edit <id>``
    with a partial id must still be refused, not fuzzily retargeted."""
    from unittest.mock import patch
    app = _app(project)
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        before = app.tree.selected_pr_id
        with patch("pm_core.tui.pane_ops.edit_plan") as edit:
            await _cmd(app, pilot, "edit spec")
        edit.assert_not_called()
        assert app.last == "PR not found: spec"
        assert app.tree.selected_pr_id == before


# ---------------------------------------------------------------------------
# Help screen (historical QA NEEDS_WORK: bracket keys row)
# ---------------------------------------------------------------------------

@async_test
async def test_help_screen_documents_fuzzy_keys_with_valid_markup():
    from textual.content import Content
    from textual.widgets import Label
    from pm_core.tui.screens import HelpScreen

    class _HelpHost(App):
        def on_mount(self):
            self.push_screen(HelpScreen())

    app = _HelpHost()
    async with app.run_test(size=(120, 80)) as pilot:
        await pilot.pause()
        rows = {}
        for label in app.screen.query(Label):
            content = label.render()
            assert isinstance(content, Content)
            rows[content.plain] = content
        cycle = [c for p, c in rows.items() if "Cycle fuzzy match results" in p]
        assert len(cycle) == 1
        assert cycle[0].plain == "  ] / [  Cycle fuzzy match results"
        # Only the two key glyphs are bold — the description is not.
        bold = sorted((s.start, s.end) for s in cycle[0].spans
                      if "bold" in str(s.style))
        assert bold == [(2, 3), (6, 7)]
        assert "  /pr select <query>  Fuzzy-find PR" in rows
        assert "  /plan select <query>  Fuzzy-find plan" in rows
