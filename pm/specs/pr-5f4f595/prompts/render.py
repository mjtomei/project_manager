"""Render the affected prompts with representative context.

Usage: python3 render.py <repo> <out_dir>

<repo> is either the PR workdir (current master behaviour, "before") or the
scratch prototype worktree ("after").  Data-heavy runtime inputs (PR
description, notes, spec body, QA verdict listing, session notes, QA library
listing, scenario steps) are replaced with clearly labelled placeholders so
the rendered text shows every pm-authored sentence verbatim.
"""
import os
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(repo))
os.chdir(repo)

from pm_core import prompt_gen, spec_gen, notes as notes_mod  # noqa: E402
from pm_core import qa_instructions  # noqa: E402
from pm_core.qa_loop import QAScenario  # noqa: E402

PH = "⟦{}⟧"

SESSION = "pm-project_manager-c5a1006b"
PR_ID = "pr-5f4f595"
BRANCH = "pm/pr-5f4f595-sign-off-report-review-qa-efficiency-recommendatio"
WORKDIR = ("/home/matt/.pm/workdirs/project-manager-828c8d0a/"
           "pm-pr-5f4f595-sign-off-report-review-qa-efficiency-66205ce0")

# Revision placeholders survive the [:8]/[:12] slicing the builders apply.
HEAD, BASE, MBASE, TREE = "⟦head⟧", "⟦base⟧", "⟦mbase⟧", "⟦tree⟧"


def make_pr(**over):
    pr = {
        "id": PR_ID,
        "title": ("Sign-off report: review/QA efficiency, plan feedback and "
                  "full human prompt review"),
        "plan": "plan-regression",
        "branch": BRANCH,
        "status": "sign_off",
        "gh_pr": "https://github.com/mjtomei/project_manager/pull/289",
        "gh_pr_number": 289,
        "workdir": WORKDIR,
        "review_spec": True,
        "description": PH.format(
            "PR DESCRIPTION — this PR's description from project.yaml, "
            "inlined whole"),
        "depends_on": ["pr-8e693f6", "pr-2680fbf"],
        "notes": [],
        "integration": {
            "target_repo": "https://github.com/mjtomei/project_manager.git",
            "base_branch": "master",
            "base_sha": BASE,
            "head": HEAD,
            "merge_base": MBASE,
            "status": "clean",
            "candidate_tree": TREE,
            "base_files_count": 3,
            "overlap": ["pm/project.yaml"],
        },
    }
    pr.update(over)
    return pr


def make_data(pr, backend="github"):
    sib = lambda i, s: {"id": f"⟦sibling-{i}⟧", "plan": "plan-regression",
                        "title": "⟦sibling PR title⟧", "status": s}
    return {
        "project": {"name": "project-manager",
                    "repo": "https://github.com/mjtomei/project_manager.git",
                    "base_branch": "master", "backend": backend},
        "plans": [{"id": "plan-regression",
                   "name": "Automated regression and bug fix loop",
                   "file": "plans/plan-regression.md", "status": "draft"},
                  {"id": "bugs", "name": "", "file": "bugs.md"},
                  {"id": "improvements", "name": "", "file": "improvements.md"}],
        "prs": [pr, sib(1, "merged"), sib(2, "pending"),
                {"id": "pr-8e693f6", "title": "Sign-off UI: per-PR BDD report "
                 "+ all-PR behavior dashboard (HTML)", "status": "merged",
                 "plan": "plan-regression"},
                {"id": "pr-2680fbf", "title": "QA scenario planner creates new "
                 "regression test when none fits", "status": "merged",
                 "plan": "plan-regression"}],
    }


# --- placeholders for data-heavy runtime inputs ---------------------------
NOTES = ("\n## PR Notes\n" + PH.format(
    "PR NOTES — every note on this PR (main + workdir project.yaml), "
    "one '- <text> (<timestamp>)' bullet each, newest in full; older notes "
    "summarized only when the prompt is over its size limit, with a marker "
    "naming `pm pr note list <pr-id>`") + "\n")
prompt_gen._format_pr_notes = lambda pr, workdir=None: NOTES
spec_gen.get_spec = lambda pr, phase: PH.format(
    f"{phase.upper()} SPEC BODY — pm/specs/<pr-id>/{phase}.md, inlined whole")
prompt_gen._beginner_addendum = lambda: ""
_real_load_sections = notes_mod.load_sections
notes_mod.load_sections = lambda root: {
    s: PH.format(f"SESSION NOTES — the '{s}' section of pm/notes.txt; the "
                 "whole block is omitted when that section is empty")
    for s in _real_load_sections(root)}
qa_instructions.instruction_summary_for_prompt = lambda root, **k: PH.format(
    "QA LIBRARY LISTING — instructions and artifact recipes in pm/qa/, "
    "with paths and descriptions")

QA_HEAD = "\nOverall QA verdict: **PASS**\n\n"
QA_LIST = (
    "- Scenario 1 — " + PH.format("scenario title") + ": **PASS** — "
    + PH.format("verdict reason, ≤ 240 chars") + "\n"
    "- Scenario 2 — " + PH.format("scenario title") + ": **PASS** — "
    + PH.format("verdict reason") + "\n")
prompt_gen._signoff_qa_scenarios_parts = lambda pr_id: (QA_HEAD, QA_LIST)


def write(name, text):
    text = text.replace(str(repo), "/workspace")
    (out / name).write_text(text.rstrip() + "\n")


# --- sign-off --------------------------------------------------------------
pr = make_pr()
write("signoff.txt", prompt_gen.generate_signoff_prompt(
    make_data(pr), PR_ID, session_name=SESSION))

# Variants
pr_nogh = make_pr(gh_pr=None, gh_pr_number=None)
write("signoff-variant-no-github.txt", prompt_gen.generate_signoff_prompt(
    make_data(pr_nogh, backend="local"), PR_ID, session_name=SESSION))

pr_bug = make_pr(plan="bugs", title="Bug: " + PH.format("bug title"))
data_bug = make_data(pr_bug)
write("signoff-variant-bug.txt", prompt_gen.generate_signoff_prompt(
    data_bug, PR_ID, session_name=SESSION))

pr_conf = make_pr()
pr_conf["integration"] = dict(pr_conf["integration"], status="conflict",
                              candidate_tree=None,
                              conflicts=["pm/project.yaml"])
write("signoff-variant-conflict.txt", prompt_gen.generate_signoff_prompt(
    make_data(pr_conf), PR_ID, session_name=SESSION))

pr_noint = make_pr(integration=None)
write("signoff-variant-no-integration.txt", prompt_gen.generate_signoff_prompt(
    make_data(pr_noint), PR_ID, session_name=SESSION))

pr_ret = make_pr(signoff_return={
    "verdict": "SIGNOFF_REQA", "hop": "qa",
    "reason": PH.format("pm-signoff-reason of the previous report"),
    "reviewed_head": "⟦prev-head⟧", "awaiting": None,
    "integration": {"target_repo": "https://github.com/mjtomei/project_manager.git",
                    "base_branch": "master", "base_sha": BASE,
                    "status": "clean"},
    "applied": {"from_head": "⟦prev-head⟧", "merge_sha": "⟦merge⟧",
                "base_sha": BASE},
    "ts": "⟦timestamp⟧"})
write("signoff-variant-previous-return.txt",
      prompt_gen.generate_signoff_prompt(make_data(pr_ret), PR_ID,
                                         session_name=SESSION))

# --- other session prompts ---------------------------------------------------
pr_impl = make_pr(status="in_progress", integration=None)
write("impl.txt", prompt_gen.generate_prompt(
    make_data(pr_impl), PR_ID, session_name=SESSION))

pr_rev = make_pr(status="in_review", integration=None)
write("review.txt", prompt_gen.generate_review_prompt(
    make_data(pr_rev), PR_ID, session_name=SESSION))
write("review-loop.txt", prompt_gen.generate_review_prompt(
    make_data(pr_rev), PR_ID, session_name=SESSION, review_loop=True,
    review_iteration=2, review_loop_id="⟦loop⟧"))

pr_qa = make_pr(status="qa", integration=None)
write("qa-planner.txt", prompt_gen.generate_qa_planner_prompt(
    make_data(pr_qa), PR_ID, session_name=SESSION, scenario_start=1))

scn = QAScenario(
    index=3, title=PH.format("scenario title"),
    focus=PH.format("scenario focus"),
    instruction_path="⟦scratch⟧/qa-instructions/tui-manual-test.md",
    artifact_paths=["⟦scratch⟧/qa-artifacts/tmux-screen-recording.md"],
    steps=PH.format("SCENARIO STEPS — the refined GIVEN/WHEN/THEN triples, "
                    "inlined whole"))
write("qa-scenario-worktree.txt", prompt_gen.generate_qa_child_prompt(
    make_data(pr_qa), PR_ID, scn, workdir="⟦scenario clone⟧",
    session_name=SESSION, worktree_mode=True, scratch_dir="⟦scratch⟧",
    captures_root="/pm-captures"))
write("qa-scenario-plain.txt", prompt_gen.generate_qa_child_prompt(
    make_data(pr_qa), PR_ID, scn, workdir="⟦scenario dir⟧",
    session_name=SESSION, worktree_mode=False, scratch_dir="⟦scratch⟧",
    captures_root="/pm-captures"))
write("qa-interactive.txt", prompt_gen.generate_qa_interactive_prompt(
    make_data(pr_qa), PR_ID, workdir="⟦scenario 0 clone⟧",
    session_name=SESSION, worktree_mode=True, scratch_dir="⟦scratch⟧"))
write("qa-standalone.txt", prompt_gen.generate_standalone_qa_prompt(
    make_data(pr_qa), "tui-manual-test", session_name=SESSION))
print("rendered into", out)
