"""Render current and proposed prompts for pr-b491378 (spec tooling only).

    PYTHONPATH=/workspace python3 pm/specs/pr-b491378/tools/render_prompts.py

Writes ../prompts/current/*.txt (master's builders, verbatim), and
../prompts/proposed/*.txt plus ../prompts/diff/*.diff (proposed wording from
proposed_prompts.py).  Runtime values are «PLACEHOLDERS»; see impl.md's
placeholder table.  A throwaway project and HOME under a temp dir keep the
real repo, ~/.pm settings (beginner-mode, spec-mode, auto-cleanup) and
notes.txt out of the render, so global-setting blocks render as absent.
"""
import difflib
import os
import sys
import tempfile
from pathlib import Path

SPEC = Path(__file__).resolve().parents[1]
OUT = SPEC / "prompts"
TMP = Path(tempfile.mkdtemp(prefix="pr-b491378-render-"))
os.environ["HOME"] = str(TMP / "home")
sys.path.insert(0, str(SPEC / "tools"))
sys.path.insert(0, str(SPEC.parents[2]))

PROJ, WD = TMP / "proj", TMP / "wd"
(PROJ / "pm").mkdir(parents=True)
(WD / "pm" / "specs" / "«PR_ID»").mkdir(parents=True)
(WD / "pm" / "specs" / "«PR_ID»" / "impl.md").write_text("«IMPL_SPEC_TEXT»\n")
(PROJ / "pm" / "notes.txt").write_text(
    "## General\n\n«SESSION_NOTES_GENERAL»\n\n## Implementation\n\n"
    "«SESSION_NOTES_IMPLEMENTATION»\n\n## Review\n\n«SESSION_NOTES_REVIEW»\n\n"
    "## QA\n\n## Merge\n\n## Watcher\n\n")
(PROJ / "pm" / "project.yaml").write_text("project: {name: x}\nplans: []\nprs: []\n")
os.chdir(PROJ)

from pm_core import prompt_gen  # noqa: E402
import proposed_prompts as pp  # noqa: E402


def data_for(backend="github", *, review_spec=True, bug=False, spec=True):
    pr = {"id": "«PR_ID»", "title": "«PR_TITLE»", "status": "in_review",
          "branch": "«BRANCH»", "plan": "bugs" if bug else "«PLAN_ID»",
          "description": "«PR_DESCRIPTION»", "depends_on": [],
          "gh_pr": "«GH_PR_URL»" if backend == "github" else None,
          "workdir": str(WD if spec else TMP / "nowd"),
          "notes": [{"id": "note-0000000", "text": "«PR_NOTE_TEXT»",
                     "created_at": "«NOTE_CREATED_AT»",
                     "last_edited": "«NOTE_CREATED_AT»"}]}
    if review_spec:
        pr["review_spec"] = True
    sib = {"id": "«SIBLING_PR_ID»", "title": "«SIBLING_PR_TITLE»",
           "status": "«SIBLING_STATUS»", "plan": pr["plan"], "branch": "b"}
    return {"project": {"name": "«PROJECT»", "base_branch": "«BASE_BRANCH»",
                        "backend": backend},
            "plans": [{"id": "«PLAN_ID»", "name": "«PLAN_NAME»", "file": "p.md"},
                      {"id": "bugs", "name": "", "file": "bugs.md"}],
            "prs": [pr, sib]}


RUN = pp.QARun("«LOOP_ID»", "«COMPLETED_AT»", "«HEAD_SHORT»", "«REASON»",
               "«QA_NOTE_ID»", "«QA_WORKDIR»", "«CAPTURES_DIR»")
REQ = pp.Request("«REQUEST_ID»", "«REQUESTED_BY»", "«REQUESTED_AT»",
                 "«REQUEST_REASON»")
PRIOR = pp.PriorCheckpoint("«PREV_CHECKPOINT_ID»", "«PREV_COMPLETED_AT»",
                           "«PREV_HEAD_SHORT»", "«PREV_OUTCOMES»",
                           "«PREV_ASSESSMENT_PATH»")
RESUME = pp.Resume("«ATTEMPT»", "«PREVIOUS_ATTEMPT_END»",
                   "«PREVIOUS_TRANSCRIPT»",
                   "«; a draft assessment exists at `<path>` — or empty»")


def ctx(*, threshold=True, request=False, prior=False, resume=False,
        spec=True):
    return pp.CheckpointContext(
        ckpt_id="«CHECKPOINT_ID»",
        assessment_path="pm/specs/«PR_ID»/checkpoints/«CHECKPOINT_ID».md",
        impl_spec_path="pm/specs/«PR_ID»/impl.md",
        qa_spec_path="pm/specs/«PR_ID»/qa.md",
        threshold="«THRESHOLD»" if threshold else None,
        threshold_source="«THRESHOLD_SOURCE»", count="«COUNT»",
        since="«SINCE»", runs=[RUN] if threshold else [],
        requests=[REQ] if request else [], prior=[PRIOR] if prior else [],
        resume=RESUME if resume else None, plan_file="«PLAN_FILE»",
        spec_text="«IMPL_SPEC_TEXT»" if spec else None,
        covered_run_ids="«COVERED_RUN_IDS»",
        covered_request_ids="«COVERED_REQUEST_IDS»")


RESULT = pp.CheckpointResult(
    "«CHECKPOINT_ID»", "«COMPLETED_AT»", "«REVIEWED_HEAD_SHORT»",
    "«OUTCOMES»", "«HUMAN_QUESTION»",
    "pm/specs/«PR_ID»/checkpoints/«CHECKPOINT_ID».md",
    "pm/specs/«PR_ID»/impl.md", "«ASSESSMENT_DIGEST»")

for sub in ("current", "proposed", "diff"):
    (OUT / sub).mkdir(parents=True, exist_ok=True)


def emit(name, before, after):
    if before is not None:
        (OUT / "current" / f"{name}.txt").write_text(before + "\n")
    (OUT / "proposed" / f"{name}.txt").write_text(after + "\n")
    a = [] if before is None else (before + "\n").splitlines(True)
    d = difflib.unified_diff(a, (after + "\n").splitlines(True),
                             f"current/{name}.txt" if before is not None else "/dev/null",
                             f"proposed/{name}.txt")
    (OUT / "diff" / f"{name}.diff").write_text("".join(d))
    print(f"{name}: {len(after.encode())} B")


S = "«PM_SESSION»"
# P1 checkpoint prompt variants (new; no "current").
for name, dkw, ckw, sess in [
    ("checkpoint-github-review_spec-threshold", {}, {}, S),
    ("checkpoint-github-review_spec-request_only", {}, {"threshold": False, "request": True}, S),
    ("checkpoint-github-review_spec-resume_both_prior", {}, {"request": True, "prior": True, "resume": True}, S),
    ("checkpoint-github-spec_prompt_mode", {"review_spec": False}, {}, S),
    ("checkpoint-github-missing_spec", {"review_spec": False, "spec": False}, {"spec": False}, S),
    ("checkpoint-github-bug_pr", {"review_spec": False, "bug": True}, {}, S),
    ("checkpoint-local-review_spec", {"backend": "local"}, {}, S),
    ("checkpoint-github-review_spec-no_tui", {}, {}, None),
]:
    emit(name, None, pp.generate_checkpoint_prompt(
        data_for(**dkw), "«PR_ID»", ctx(**ckw), session_name=sess))

# P2 review prompt: loop + single, with and without a completed checkpoint.
for backend in ("github", "local"):
    for rs in (True, False):
        tag = f"{backend}-{'review_spec' if rs else 'spec_prompt_mode'}"
        for loop in (True, False):
            kind = "review-loop" if loop else "review-single"
            kw = dict(review_loop=True, review_iteration=7,
                      review_loop_id="«LOOP_ID»") if loop else {}
            before = prompt_gen.generate_review_prompt(
                data_for(backend, review_spec=rs), "«PR_ID»", session_name=S, **kw)
            emit(f"{kind}-{tag}-after_checkpoint", before,
                 pp.patch_review_prompt(before, "«PR_ID»", RESULT, rs))
            emit(f"{kind}-{tag}-no_checkpoint", before,
                 pp.patch_review_prompt(before, "«PR_ID»", None, rs))
for name, dkw in [("review-loop-github-missing_spec-after_checkpoint",
                   {"review_spec": False, "spec": False}),
                  ("review-loop-github-bug_pr-after_checkpoint",
                   {"review_spec": False, "bug": True})]:
    before = prompt_gen.generate_review_prompt(
        data_for(**dkw), "«PR_ID»", session_name=S, review_loop=True,
        review_iteration=7, review_loop_id="«LOOP_ID»")
    emit(name, before, pp.patch_review_prompt(before, "«PR_ID»", RESULT,
                                              dkw.get("review_spec", True)))

# P3 implementation prompt.
for backend in ("github", "local"):
    for rs in (True, False):
        tag = f"{backend}-{'review_spec' if rs else 'spec_prompt_mode'}"
        before = prompt_gen.generate_prompt(
            data_for(backend, review_spec=rs), "«PR_ID»", session_name=S)
        emit(f"impl-{tag}-after_checkpoint", before,
             pp.patch_impl_prompt(before, "«PR_ID»", RESULT, rs))
before = prompt_gen.generate_prompt(
    data_for(review_spec=False, bug=True), "«PR_ID»", session_name=S)
emit("impl-github-bug_pr-after_checkpoint", before,
     pp.patch_impl_prompt(before, "«PR_ID»", RESULT, False))

# P4/P5 watcher prompts.
for fn in ("generate_bug_fix_impl_prompt", "generate_improvement_fix_impl_prompt"):
    before = getattr(prompt_gen, fn)(data_for(review_spec=False), session_name=S)
    emit(fn.replace("generate_", "watcher-").replace("_prompt", ""), before,
         pp.patch_watcher_prompt(before))

before = prompt_gen.generate_watcher_prompt(
    data_for(review_spec=False), session_name=S, iteration=3,
    loop_id="«WATCHER_LOOP_ID»", auto_start_target="«AUTO_START_TARGET»",
    meta_pm_root="«META_PM_ROOT»")
emit("watcher-auto_start", before, pp.patch_autostart_watcher_prompt(before))

# "Every other switch flipped" variants, shown in full in impl.md §1 so each
# conditional segment appears in at least one complete text.
emit("checkpoint-ALT-local-spec_prompt_mode-bug_pr-request_only-resume-prior-no_tui",
     None, pp.generate_checkpoint_prompt(
         data_for("local", review_spec=False, bug=True), "«PR_ID»",
         ctx(threshold=False, request=True, prior=True, resume=True),
         session_name=None))
before = prompt_gen.generate_review_prompt(
    data_for("local", review_spec=False, bug=True), "«PR_ID»", session_name=S)
emit("review-single-ALT-local-spec_prompt_mode-bug_pr-after_checkpoint", before,
     pp.patch_review_prompt(before, "«PR_ID»", RESULT, False))
before = prompt_gen.generate_prompt(
    data_for("local", review_spec=False, bug=True), "«PR_ID»", session_name=S)
emit("impl-ALT-local-spec_prompt_mode-bug_pr-after_checkpoint", before,
     pp.patch_impl_prompt(before, "«PR_ID»", RESULT, False))
