"""Render every prompt pr-30888b1 changes, with labelled ⟦…⟧ placeholders.

Usage (run against any checkout; PYTHONPATH picks the tree that renders):

    PYTHONPATH=<tree> python render.py <out_dir>

Writes one file per prompt into <out_dir>.  Run it once on this branch and
once on an origin/master worktree, then diff the two directories.  impl.md's
Appendix A is generated from the branch render (see build_appendix.py).

Prompts that no longer exist on a tree (e.g. ``plan breakdown`` on this
branch) are written as ``<name>.absent``.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from pm_core import store

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

TUI = "⟦tui_section — the 'Interacting with the TUI' block, rendered in tui_section.txt; empty when no pm tmux session⟧\n"
NOTES = "⟦notes_block — notes.notes_section(root): the project's pm/notes.txt sections; empty when none⟧\n"


def _listing(items, formatter, **kw):
    items = list(items)
    if not items:
        return ""
    return ("⟦bounded listing — one line per PR: `  <pr-id>: <title> [<status>]"
            "…`; capped at 40 lines / 20 KB, then `  ... (+N more; run `pm pr "
            "list` to see all PRs)`⟧")


def _state(root: Path, plan_body: str, prs: int) -> None:
    data = {"project": {"name": "proj", "repo": "/repo", "base_branch": "master"},
            "plans": [{"id": "pl-001", "name": "Plan", "file": "plans/pl-001.md"}],
            "prs": [{"id": f"pr-{i:03d}", "title": f"T{i}", "plan": "pl-other",
                     "status": "pending", "depends_on": []} for i in range(prs)]}
    store.save(data, root)
    (root / "plans").mkdir(exist_ok=True)
    (root / "plans" / "pl-001.md").write_text(plan_body)


def _cli_prompt(argv, root: Path) -> str:
    from pm_core.cli import cli
    import pm_core.cli.plan as plan_mod
    with patch.object(plan_mod, "find_claude", return_value=None), \
            patch.object(plan_mod, "_get_pm_session", return_value="⟦session⟧"), \
            patch.object(plan_mod, "tui_section", return_value=TUI), \
            patch.object(plan_mod.notes, "notes_section", return_value=NOTES), \
            patch.object(plan_mod, "bounded_join", side_effect=_listing):
        res = CliRunner().invoke(cli, ["-C", str(root)] + argv)
    out = res.output
    if res.exit_code != 0 or "---\n" not in out:
        return None
    body = out.split("---\n", 1)[1].rsplit("\n---", 1)[0]
    return body


def _write(name: str, text: str | None) -> None:
    if text is None:
        (OUT / f"{name}.absent").write_text("")
    else:
        (OUT / f"{name}.txt").write_text(text if text.endswith("\n") else text + "\n")


def _scrub(text: str, root: Path, plan_id: str | None = None,
           name: str | None = None) -> str:
    text = text.replace(str(root), "⟦pm_root⟧")
    if plan_id:
        text = text.replace(plan_id, "⟦plan_id⟧")
    if name:
        text = text.replace(f'"{name}"', '"⟦name⟧"')
    return text


# 1. plan add — with existing PRs (listing shown) ------------------------
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    _state(root, "# Plan\n", prs=3)
    name = "NAME"
    body = _cli_prompt(["plan", "add", name], root)
    new_id = [p["id"] for p in store.load(root)["plans"] if p["id"] != "pl-001"][0]
    _write("plan_add", _scrub(body, root, new_id, name) if body else None)

# 1b. plan add — empty project (no listing) -------------------------------
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    _state(root, "# Plan\n", prs=0)
    body = _cli_prompt(["plan", "add", "NAME"], root)
    new_id = [p["id"] for p in store.load(root)["plans"] if p["id"] != "pl-001"][0]
    _write("plan_add_no_existing_prs", _scrub(body, root, new_id, "NAME") if body else None)

# 2. plan breakdown (removed by this PR) ----------------------------------
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    _state(root, "# Plan\n", prs=3)
    body = _cli_prompt(["plan", "breakdown", "pl-001"], root)
    _write("plan_breakdown", _scrub(body, root, "pl-001") if body else None)

# 3. plan review — pre-load (no PRs linked to the plan yet) ----------------
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    _state(root, "# Plan\n", prs=3)
    body = _cli_prompt(["plan", "review", "pl-001"], root)
    _write("plan_review_preload", _scrub(body, root, "pl-001") if body else None)

# 4. background check prompts -------------------------------------------
from pm_core.plans.review import REVIEW_PROMPTS
for key in ("plan-add", "plan-breakdown"):
    tmpl = REVIEW_PROMPTS.get(key)
    _write(f"check_{key}", tmpl.format(path="⟦plan_path⟧") if tmpl else None)

# 5. guide setup prompt at has_plan_draft -------------------------------
from pm_core import guide
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    _state(root, "# Plan\n\nDraft.\n", prs=0)
    state, ctx = guide.detect_state(root)
    assert state == "has_plan_draft", state
    with patch.object(guide.notes, "notes_section", return_value=NOTES), \
            patch.object(guide, "_beginner_mode_guide_section",
                         return_value="⟦beginner_mode_section — depends on the global beginner-mode setting⟧"), \
            patch("pm_core.prompt_gen.tui_section", return_value=TUI):
        text = guide.build_setup_prompt(state, ctx, root, session_name="⟦session⟧")
    text = _scrub(text, root).replace("Name: proj", "Name: ⟦project_name⟧").replace(
        "Repo: /repo", "Repo: ⟦repo⟧")
    _write("guide_setup_has_plan_draft", text)
    _write("guide_step_description_has_plan_draft",
           guide.STEP_DESCRIPTIONS["has_plan_draft"])

# 6. prompt_gen forbidden lists -----------------------------------------
from pm_core import prompt_gen
_write("tui_section", prompt_gen.tui_section("⟦session⟧"))
with patch.object(prompt_gen, "tui_section", return_value=TUI):
    _write("watcher_review", prompt_gen.generate_watcher_review_prompt(
        session_name="⟦session⟧", meta_pm_root="⟦meta_pm_root⟧",
        transcript_dir=None))

print("rendered into", OUT)
