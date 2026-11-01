"""Render representative prompts with REAL context (spec tooling only).

    PYTHONPATH=/workspace python3 pm/specs/pr-b491378/tools/render_examples.py

For the three evidence PRs, rebuild the PR as it stood when its second
counted QA run completed — registry notes up to that time, the implementation
spec as committed then (``git show <commit>:<path>``) — and render:

* the proposed checkpoint prompt (ckpt-1; for pr-f38005f also ckpt-2);
* the proposed review-loop prompt for the iteration after the checkpoint,
  with the example assessment (../examples/) digested into it and the
  completion PR note pm would write.

Values that pre-feature history did not record (the reviewed HEAD, the
session tag of the captures dir) are rendered as «NOT_RECORDED…» markers.
The PR description is the registry's current text (it may have been edited
after the trigger time).  Output: ../prompts/examples/*.txt.
"""
import copy
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

SPEC = Path(__file__).resolve().parents[1]
REPO = SPEC.parents[2]
OUT = SPEC / "prompts" / "examples"
OUT.mkdir(parents=True, exist_ok=True)
TMP = Path(tempfile.mkdtemp(prefix="pr-b491378-examples-"))
os.environ["HOME"] = str(TMP / "home")
sys.path.insert(0, str(SPEC / "tools"))
sys.path.insert(0, str(REPO))
os.chdir(REPO)

from pm_core import prompt_gen  # noqa: E402
import proposed_prompts as pp  # noqa: E402

try:
    from yaml import CSafeLoader as Loader
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as Loader

DATA = yaml.load(open(REPO / "pm" / "project.yaml"), Loader=Loader)
SESSION = "pm-project_manager-c5a1006b"
NOT_HEAD = "«NOT_RECORDED_BEFORE_THIS_FEATURE»"
CAPS = "~/.pm/sessions/«SESSION_TAG»/captures/{pr}"

CASES = [
    # pr, ckpt, trigger time, [(loop_id, note_id, completed_at)], spec commit, prior
    ("pr-f38005f", "ckpt-1", "2026-04-09T18:18:02Z",
     [("d8d59509902b0358", "note-60be829", "2026-04-07T22:51Z"),
      ("bdca24011d0bf8cd", "note-ed85f13", "2026-04-09T18:18Z")], None, []),
    ("pr-f38005f", "ckpt-2", "2026-04-09T23:47:57Z",
     [("1fd1b3aeb3203659", "note-2ffde86", "2026-04-09T21:20Z"),
      ("c31d04be54fae4fa", "note-5482f04", "2026-04-09T23:47Z")], None,
     [pp.PriorCheckpoint("ckpt-1", "«COMPLETED_AT_OF_CKPT_1»", NOT_HEAD,
                         "corrections, spec_clarification",
                         "pm/specs/pr-f38005f/checkpoints/ckpt-1.md")]),
    ("pr-8e693f6", "ckpt-1", "2026-05-26T13:25:00Z",
     [("47b30e4a8869f42d", "note-596f78b", "2026-05-26T04:06Z"),
      ("bb8854012f0ad8f2", "note-083c051", "2026-05-26T13:25Z")],
     "54c36ad6", []),
    ("pr-2d5f712", "ckpt-1", "2026-05-26T01:29:43Z",
     [("ad009382b7b0e6d6", "note-094efa5", "2026-05-25T23:42Z"),
      ("a953490cbd95dbd7", "note-c9aeedc", "2026-05-26T01:29Z")],
     "ae6373d5", []),
]


def pr_at(pr_id, when, spec_commit):
    data = copy.deepcopy(DATA)
    pr = next(p for p in data["prs"] if p["id"] == pr_id)
    pr["notes"] = [n for n in pr.get("notes") or []
                   if str(n.get("created_at") or "") <= when]
    for k in ("signoff", "signoff_return", "integration", "merge_integrity",
              "merged_at", "signed_off_at"):
        pr.pop(k, None)
    pr["status"] = "in_review"
    wd = TMP / f"wd-{pr_id}-{when[:10]}"
    if spec_commit:
        spec = subprocess.run(
            ["git", "show", f"{spec_commit}:pm/specs/{pr_id}/impl.md"],
            capture_output=True, text=True, check=True).stdout
        (wd / "pm" / "specs" / pr_id).mkdir(parents=True, exist_ok=True)
        (wd / "pm" / "specs" / pr_id / "impl.md").write_text(spec)
    else:
        spec = None
        wd.mkdir(parents=True, exist_ok=True)
    pr["workdir"] = str(wd)
    return data, pr, spec


def qa_workdir(pr, note_id):
    note = next(n for n in pr["notes"] if n["id"] == note_id)
    return re.search(r"\(workdir: ([^)]+)\)", note["text"]).group(1)


def digest(path: Path) -> str:
    text = path.read_text()
    body = text.split("\n---\n", 1)[1]
    keep = ("Summary", "Current-PR corrections", "Specification",
            "Questions for the owner")
    out = []
    for sec in re.split(r"\n(?=## )", body):
        m = re.match(r"## (.+)\n", sec)
        if m and m.group(1).strip() in keep:
            out.append(f"**{m.group(1).strip()}**\n" + sec[m.end():].strip())
    return "\n\n".join(out)


def front(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---\n")[1])


for pr_id, ckpt, when, runs, spec_commit, prior in CASES:
    data, pr, spec = pr_at(pr_id, when, spec_commit)
    c = pp.CheckpointContext(
        ckpt_id=ckpt,
        assessment_path=f"pm/specs/{pr_id}/checkpoints/{ckpt}.md",
        impl_spec_path=f"pm/specs/{pr_id}/impl.md",
        qa_spec_path=f"pm/specs/{pr_id}/qa.md",
        threshold="2", threshold_source=", the default", count=str(len(runs)),
        since=("the PR started" if not prior else
               f"checkpoint {prior[-1].ckpt_id} completed"),
        runs=[pp.QARun(lid, at, NOT_HEAD, pp.REASON_TEXT["scenarios"], nid,
                       qa_workdir(pr, nid), CAPS.format(pr=pr_id))
              for lid, nid, at in runs],
        prior=prior, plan_file=f"pm/plans/{pr.get('plan')}.md"
        if pr.get("plan") not in ("bugs", "improvements") else
        f"pm/{pr.get('plan')}.md",
        spec_text=spec,
        covered_run_ids=", ".join(r[0] for r in runs), covered_request_ids="")
    name = f"{pr_id}-{ckpt}-checkpoint"
    (OUT / f"{name}.txt").write_text(pp.generate_checkpoint_prompt(
        data, pr_id, c, session_name=SESSION) + "\n")
    print(name, (OUT / f"{name}.txt").stat().st_size, "B")

    ex = SPEC / "examples" / f"{pr_id}-{ckpt}.md"
    if not ex.exists():
        continue
    fm = front(ex)
    if fm["human_question"] == "blocking":
        # The checkpoint ends INPUT_REQUIRED; the next review only runs after
        # the owner answers.  Rendering it would mean inventing that answer.
        continue
    outcomes = ", ".join(fm["outcomes"])
    pr["notes"].append({
        "id": "note-ckpt001", "created_at": "«CHECKPOINT_COMPLETED_AT»",
        "last_edited": "«CHECKPOINT_COMPLETED_AT»",
        "text": pp.note_complete(
            ckpt, "2 completed QA NEEDS_WORK runs (threshold 2)",
            ", ".join(fm["covers_qa_runs"]), NOT_HEAD, outcomes,
            fm["human_question"], ", ".join(fm["followups"]) or "none",
            f"pm/specs/{pr_id}/checkpoints/{ckpt}.md")})
    before = prompt_gen.generate_review_prompt(
        data, pr_id, session_name=SESSION, review_loop=True,
        review_iteration=1, review_loop_id="«LOOP_ID»")
    result = pp.CheckpointResult(
        ckpt, "«CHECKPOINT_COMPLETED_AT»", NOT_HEAD, outcomes,
        fm["human_question"], f"pm/specs/{pr_id}/checkpoints/{ckpt}.md",
        f"pm/specs/{pr_id}/impl.md", digest(ex))
    name = f"{pr_id}-{ckpt}-next-review-loop"
    (OUT / f"{name}.txt").write_text(pp.patch_review_prompt(
        before, pr_id, result, bool(pr.get("review_spec"))) + "\n")
    print(name, (OUT / f"{name}.txt").stat().st_size, "B")
