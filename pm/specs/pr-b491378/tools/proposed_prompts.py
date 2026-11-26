"""PROPOSED prompt text for pr-b491378 (spec tooling — NOT product code).

Nothing in pm imports this file.  It holds the exact wording proposed in
``../impl.md`` ("Full prompts for approval") so the inline text, the rendered
files under ``../prompts/`` and the diffs are produced from one source.  After
approval the implementation moves this wording into ``pm_core/prompt_gen.py``
(``generate_checkpoint_prompt`` and ``_checkpoint_result_block``) and
``pm_core/checkpoint.py``; this module is then deleted.

Composition reuses the real builders' helpers (``_format_pr_notes``,
``_signoff_return_block``, ``tui_section``, ``_plan_sibling_line``,
``notes.notes_for_prompt``, ``_beginner_addendum``) so every shared block is
byte-identical to what the other prompts already send.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pm_core import notes, store
from pm_core import prompt_gen as pg
from pm_core.prompt_bounds import (PLAN_CONTEXT_MAX_SIBLINGS, PLAN_LIST_BUDGET,
                                   bounded_join, fit_prompt)

# ---------------------------------------------------------------------------
# Inputs.  Every field is a runtime value; the placeholder render passes
# «LABELLED» strings, the example renders pass real registry values.
# ---------------------------------------------------------------------------


@dataclass
class QARun:
    loop_id: str
    completed_at: str
    head: str
    reason: str          # one of REASON_TEXT's values (already rendered)
    note_id: str
    qa_workdir: str
    captures: str


@dataclass
class Request:
    req_id: str
    by: str
    at: str
    reason: str


@dataclass
class PriorCheckpoint:
    ckpt_id: str
    completed_at: str
    head: str
    outcomes: str
    path: str


@dataclass
class Resume:
    attempt: str
    prev_end: str
    prev_transcript: str
    draft_note: str      # "" or "; a draft assessment exists at `<path>`"


@dataclass
class CheckpointContext:
    ckpt_id: str
    assessment_path: str
    impl_spec_path: str
    qa_spec_path: str
    threshold: str | None          # None when the trigger is request-only
    threshold_source: str          # ", the default" or ", set in project.yaml"
    count: str
    since: str                     # "the PR started" / "checkpoint X completed at T"
    runs: list[QARun] = field(default_factory=list)
    requests: list[Request] = field(default_factory=list)
    prior: list[PriorCheckpoint] = field(default_factory=list)
    resume: Resume | None = None
    plan_file: str = ""
    spec_text: str | None = None   # None => spec missing
    covered_run_ids: str = ""
    covered_request_ids: str = ""


# Rendered reason for a counted run (pm_core/qa_loop.py:6189-6205 sources).
REASON_TEXT = {
    "scenarios": "scenario verdicts",
    "verification": "verification rejected a PASS",
    "planner_changes": "the QA planner committed code changes",
    "input_wait_changes": "the PR changed during an INPUT_REQUIRED wait",
}

OUTCOMES = ("keep", "corrections", "spec_clarification",
            "spec_change_proposal", "follow_up", "breakup_referral")


# ---------------------------------------------------------------------------
# P1 — the checkpoint session prompt.
# ---------------------------------------------------------------------------

def _trigger_block(c: CheckpointContext) -> str:
    parts = []
    if c.threshold is not None:
        parts.append(
            f"This PR has {c.count} completed QA runs that ended NEEDS_WORK "
            f"since {c.since} (the project setting "
            f"`checkpoint-after-qa-failures` is {c.threshold}"
            f"{c.threshold_source}). Only whole QA runs that finished with an "
            "overall NEEDS_WORK verdict count; individual scenario results, "
            "review iterations, infrastructure retries, stopped or "
            "incomplete runs and INPUT_REQUIRED waits do not. A round whose "
            "fixes were useful still counts — the point is to check whether "
            "the rounds share a cause, not to judge them.")
    if c.requests:
        lines = "\n".join(
            f"- {r.req_id} by {r.by} at {r.at}: {r.reason}" for r in c.requests)
        lead = ("An early checkpoint was also requested:"
                if c.threshold is not None else
                "An early checkpoint was requested before the threshold was "
                "reached:")
        parts.append(
            f"{lead}\n{lines}\nTreat each stated reason as a lead to check "
            "against the evidence, not as a conclusion.")
    return "\n\n".join(parts)


def _spec_block(c: CheckpointContext, review_spec: bool) -> str:
    if c.spec_text is None:
        return f"""
## Implementation Spec — MISSING

This PR has no implementation spec (`{c.impl_spec_path}` does not exist).
Work from the description, the PR notes and the code. If the missing spec is
itself part of the problem — for example, the rounds keep disagreeing about
what is required — say so in the assessment.
"""
    if review_spec:
        authority = ("The owner approved this spec at the spec-review gate. Any "
                     "change to its text — even a clarification — needs the "
                     "owner's approval before anyone applies it.")
    else:
        authority = ("A clarification that changes no requirement, acceptance "
                     "criterion, scope or user decision may be applied by the "
                     "next review iteration; anything else needs the owner's "
                     "approval.")
    return f"""
## Implementation Spec (`{c.impl_spec_path}`)

Read the spec as evidence of what was intended, not as proof that every
design choice in it is still right. Do not edit it in this session; record
any problem with it in the assessment (see Steps). {authority}

{c.spec_text}
"""


def _runs_block(c: CheckpointContext) -> str:
    if not c.runs:
        body = "No completed NEEDS_WORK QA runs since the last checkpoint."
    else:
        body = "\n".join(
            f"- run {r.loop_id} — completed {r.completed_at} on HEAD {r.head}; "
            f"NEEDS_WORK from {r.reason}; note {r.note_id}; QA workdir "
            f"`{r.qa_workdir}`; verdicts `{r.captures}/scenarios/<n>/verdict.md`"
            for r in c.runs)
    return f"""
## QA runs covered by this checkpoint

Each line is one completed QA run that ended NEEDS_WORK. Its per-scenario
results are in the matching `QA NEEDS_WORK:` PR note above, and each
scenario's verdict is in its captures directory. The QA spec, when present,
is `{c.qa_spec_path}` — its requirements are part of the acceptance evidence.

{body}
"""


def _prior_block(c: CheckpointContext) -> str:
    if not c.prior:
        return ""
    lines = "\n".join(
        f"- {p.ckpt_id} — completed {p.completed_at} on HEAD {p.head}; "
        f"outcomes: {p.outcomes}; assessment `{p.path}`" for p in c.prior)
    return f"""
## Earlier checkpoints

Read these first. Do not re-open an outcome that an earlier checkpoint or the
owner settled unless new evidence bears on it, and say what that evidence is.

{lines}
"""


def _resume_block(c: CheckpointContext) -> str:
    if not c.resume:
        return ""
    r = c.resume
    return f"""
## Resuming an earlier attempt

This is attempt {r.attempt} of checkpoint {c.ckpt_id}. The previous attempt
did not complete: {r.prev_end}. Its transcript is
`{r.prev_transcript}`{r.draft_note}. Continue from that evidence rather
than starting over: read the transcript and keep the valid parts of any
draft. Do not delete the draft or anything else the previous attempt left
behind.
"""


def _plan_context(data: dict, pr: dict, pr_id: str) -> str:
    plan_ref = pr.get("plan")
    plan = store.get_plan(data, plan_ref) if plan_ref else None
    if not plan:
        return ""
    sibs = [p for p in data.get("prs") or []
            if p.get("plan") == plan_ref and p["id"] != pr_id]
    if not sibs:
        return ""
    lines = bounded_join(
        sibs, pg._plan_sibling_line, max_items=PLAN_CONTEXT_MAX_SIBLINGS,
        max_bytes=PLAN_LIST_BUDGET,
        omitted_note=lambda n: f"... (+{n} more; run `pm pr list --plan {plan['id']}`)")
    return f"""
## Plan Context
This PR is part of plan "{plan['name']}" ({plan['id']}). Other PRs in this plan:
{lines}
"""


_BUG_RULE = (
    "\n- This is a bug-fix PR: its reproduction test and its pre-fix and "
    "post-fix evidence are acceptance constraints. Do not propose removing "
    "or weakening them.")


def generate_checkpoint_prompt(data: dict, pr_id: str, c: CheckpointContext,
                               session_name: str | None = None) -> str:
    pr = store.get_pr(data, pr_id)
    if not pr:
        raise ValueError(f"PR {pr_id} not found")
    title = pr.get("title", "")
    description = (pr.get("description") or "").strip()
    branch = pr.get("branch", f"pm/{pr_id}")
    project = data.get("project", {})
    base = project.get("base_branch", "master")
    local = project.get("backend", "vanilla") == "local"
    plan_ref = pr.get("plan")
    plan = store.get_plan(data, plan_ref) if plan_ref else None
    review_spec = bool(pr.get("review_spec"))
    bug = pg._is_bug_pr(pr)

    plan_line = (f'Part of plan "{plan["name"]}" ({plan["id"]}); plan file: '
                 f"`{c.plan_file}`." if plan else
                 "Standalone PR (not part of a plan).")
    general_notes, review_notes = "", ""
    try:
        root = store.find_project_root()
        general_notes, review_notes = notes.notes_for_prompt(root, "review")
    except FileNotFoundError:
        pass
    tui_block = pg.tui_section(session_name) if session_name else ""
    pr_notes_block = pg._format_pr_notes(pr, workdir=pr.get("workdir"))
    signoff_return = pg._signoff_return_block(pr)
    plan_context = _plan_context(data, pr, pr_id)

    if local:
        diff_ref, pull_step, push = base, "", ""
        log_range = f"{base}..HEAD"
    else:
        diff_ref, log_range = f"origin/{base}", f"origin/{base}..HEAD"
        pull_step = (f"1. Pull the latest changes for `{branch}` from the "
                     "remote. Do not discard or reset local changes you find; "
                     "leave them as they are.\n")
        push = f" && git push origin {branch}"
    n = 2 if pull_step else 1
    push_note = ("" if local else
                 "\n   If the push fails, say so in your final summary; never "
                 "force-push.")

    def _assemble(parts: dict[str, str]) -> str:
        return f"""You are running an architecture and specification checkpoint for PR {pr_id}: "{title}"

This session is managed by `pm`. Run `pm help` to see available commands.

## Task

Step back over the whole PR before its next review iteration. Repeated review
and QA rounds can fix real problems one at a time while hiding a shared
cause, a design that is getting harder to keep correct, or a specification
that asks for the wrong thing. Look at the PR as a whole — its goal, its
complete diff, its spec and everything the review and QA rounds found — and
write a short, evidence-linked assessment that helps the next round. You do
not change code in this session.

A justified "keep the current approach" is a complete and valid outcome.
There is no quota of changes, refactors or proposals to produce, and many
checkpoints should recommend no redesign.

This checkpoint does not judge whether the PR is ready, and it does not
replace review, QA or sign-off. The problems QA found still have to be fixed,
those fixes still need a review iteration that ends NEEDS_WORK and another
review after it, and QA still has to pass afterwards.

## Why this checkpoint is running

{_trigger_block(c)}

## Original goal

{description}

{plan_line}
{parts['notes']}{signoff_return}{_spec_block(c, review_spec)}{_runs_block(c)}{_prior_block(c)}{_resume_block(c)}{parts['plan']}{tui_block}{general_notes}
## Steps
{pull_step}{n}. Read the complete change, not only the last patch:
   - `git diff {diff_ref}...HEAD` — the whole PR
   - `git log --format='%h %ad %s' --date=short {log_range}` — how it got here; review-loop fixes are prefixed `review-loop <id> i<N>:`
   - the PR notes above (review and QA fix notes, incidental fixes, user decisions) and the QA runs listed above, including the `verdict.md` of each NEEDS_WORK scenario
{n+1}. Map the interfaces the PR touches: callers of changed functions, durable records and file formats it reads or writes, CLI and TUI surfaces, prompts, and other PRs working nearby (`pm pr list`; the plan context above).
{n+2}. Look for problems that span rounds:
   - repeated symptoms with a common cause — group the rounds' findings by cause, not by scenario
   - special cases, flags, retries or guards accumulating one fix at a time
   - two mechanisms doing the same job, or a new mechanism duplicating an existing one
   - complexity the actual need does not require, and a simpler design that would still meet it
   Then check the other direction: if the rounds found unrelated local defects that were fixed and stayed fixed, say so — that is evidence the approach is sound.
{n+3}. Question the specification. For each requirement the rounds kept running into, decide whether it is:
   - ambiguous (reasonable readers disagree about what it requires),
   - outdated (the code, the PR notes or a user decision has moved past it),
   - over-constrained (it prescribes a mechanism where the need is an outcome), or
   - internally conflicting (two requirements cannot both hold).
   Keep these apart from genuine implementation bugs (a sound requirement the code does not meet yet) and from necessary safety and acceptance constraints, which stay even when they are costly to satisfy.
{n+4}. Decide. Choose every outcome the evidence supports:
   - **keep** — the current approach is sound; say why the rounds do not point to a design problem.
   - **corrections** — concrete changes within this PR for the next review iteration to make: what, where, why, and how it will be verified. You do not make them.
   - **spec_clarification** — wording that resolves an ambiguity without changing any requirement, acceptance criterion, scope or user decision.
   - **spec_change_proposal** — a change to a requirement, acceptance criterion or scope. Only the owner can approve it.
   - **follow_up** — separately scoped work that should not be done in this PR (see Rules for filing).
   - **breakup_referral** — only when independently useful parts of this PR could land materially earlier and that gain outweighs extraction, duplicate review/QA and coordination costs. Staying together is the default; size and the number of rounds never justify a split on their own.
{n+5}. Write the assessment (format below) to `{c.assessment_path}`, then commit only that file{'' if local else ' and push'}:
   `git add {c.assessment_path} && git commit -m "checkpoint {c.ckpt_id}: architecture/spec assessment" -- {c.assessment_path}{push}`{push_note}

## Rules

- Do not change source code, tests, fixtures, the implementation or QA spec, the PR description, plan files or project settings. The only file you create or commit is the assessment.
- Do not revert, reset, stash, clean or delete anything. Dirty files, drafts, fixtures, captures, transcripts and earlier assessments stay exactly as they are.
- Useful incidental fixes stay in this PR by default; do not recommend moving them out to make the PR smaller.
- Do not weaken or waive anything: no lowering of QA assertions or acceptance criteria, no "pass with follow-ups", no skipped review round. Every fix you recommend still goes through a review iteration that ends NEEDS_WORK, another review, and QA.
- Decisions the user has made — in the description, in PR notes or in the approved spec — stand. You may question one only by asking the owner; never recommend acting against it.
- You cannot change merge policy, clear holds, approve specs or start other PRs.
- Follow-up work: search before filing (`pm pr list --plan {plan_ref or '<plan-id>'}`, `pm pr list --plan bugs`, `pm pr list`). If a matching PR exists, add a note to it (`pm pr note add <pr-id> '<text>'`) instead of filing. Otherwise file it as pending work: `pm pr add '<title>' --plan <plan-id> --description '<problem, evidence, link to {c.assessment_path}>'`. Filing does not start it — never run `pm pr start`. List every PR you filed or reused in the assessment.
- A breakup referral is a recommendation for the owner. Do not run `pm pr split`.{_BUG_RULE if bug else ''}

## Assessment format

Keep it short: a reader should get the decision from the summary in under a minute, and the whole file should rarely need more than about 80 lines. Link evidence (note ids, scenario verdict paths, commits, `file:line`) instead of pasting it.

```markdown
---
checkpoint: {c.ckpt_id}
pr: {pr_id}
reviewed_head: <full SHA of the HEAD you reviewed>
base: {base}@<full SHA of the base you diffed against>
covers_qa_runs: [{c.covered_run_ids}]
covers_requests: [{c.covered_request_ids}]
outcomes: [<one or more of: {', '.join(OUTCOMES)}>]
human_question: <none | non_blocking | answered>
followups: [<PR ids filed or reused; empty if none>]
---
# Checkpoint {c.ckpt_id} — {pr_id}

## Summary
<2-5 lines: the decision and the main reason>

## What was considered
- <hypothesis or concern> — evidence: <links> — conclusion: <held or ruled out, and why>

## Current-PR corrections
- <change> — where: <file/function> — why: <evidence> — verify by: <test, scenario or check>
(or "None.")

## Specification
- <requirement, quoted> — <ambiguous | outdated | over-constrained | conflicting> — proposed: <text> — <clarification | requirement change, needs owner approval>
(or "No problems found with the spec.")

## Follow-up work
- <PR id, filed or reused> — <scope, and why it is not in this PR>
(or "None.")

## Breakup
<"Not recommended" and why; or the smallest useful partition, what stays here, affected dependents, remaining checks and the expected timeline benefit>

## Expected benefit and tradeoffs
<what the next rounds gain in quality or verification, and what it costs>

## Questions for the owner
- <question> — <blocking | non-blocking>
(or "None.")
```

## Finishing

End your response with exactly one of these keywords on its own line:

- **CHECKPOINT_COMPLETE** — the assessment is written and committed{'' if local else ' and pushed'}. Give its path and commit just before this line. pm validates the file, records the checkpoint as complete, and starts the next review iteration with your assessment in its prompt.
- **INPUT_REQUIRED** — the owner has to answer before the next round can usefully proceed (for example, the next round depends on a requirement change only the owner can approve). Ask specific questions and give the options you see. The owner answers in this pane; then record the question and the owner's answer in the assessment, set `human_question: answered`, commit it, and end with **CHECKPOINT_COMPLETE**. Questions that do not block the next round go in the assessment as non-blocking instead.

Do not output **PASS** or **NEEDS_WORK** — this checkpoint does not judge whether the PR is ready.
{review_notes}{pg._beginner_addendum()}""".strip()

    return fit_prompt(_assemble, {
        "notes": (pr_notes_block, f"`pm pr note list {pr_id}`", "PR notes"),
        "plan": (plan_context, f"`pm pr list --plan {plan_ref}`" if plan_ref
                 else "`pm pr list`", "plan context"),
    })


# ---------------------------------------------------------------------------
# P2/P3 — the checkpoint result block added to the review and implementation
# prompts, and P2's early-request bullet.
# ---------------------------------------------------------------------------

@dataclass
class CheckpointResult:
    ckpt_id: str
    completed_at: str
    head: str
    outcomes: str
    human_question: str
    path: str
    impl_spec_path: str
    digest: str          # Summary + corrections + spec + questions sections


def checkpoint_result_block(r: CheckpointResult, *, role: str,
                            review_spec: bool, pr_id: str) -> str:
    if review_spec:
        spec_rule = (
            "- The owner approved this PR's spec: do not apply the "
            "checkpoint's spec clarifications or proposed changes yourself. "
            "If this session cannot proceed without one, ask with "
            "INPUT_REQUIRED.")
    else:
        spec_rule = (
            "- You may apply its spec clarifications (no requirement change) "
            f"to `{r.impl_spec_path}`, citing {r.ckpt_id}. Proposed "
            "requirement changes wait for the owner: do not apply them or "
            "judge this PR against them.")
    if role == "review":
        lead = "Use it as evidence for this review, not as a verdict:"
        first = ("- It does not replace this review. The problems QA found "
                 "still have to be fixed and reviewed, and the verdict rules "
                 "below are unchanged.")
        work = ("- If its current-PR corrections are not in the code yet "
                f"(compare `git log {r.head}..HEAD`), make the ones you agree "
                "with in this iteration along with the QA fixes, and explain "
                "any you decline — the code may show the checkpoint was wrong.")
    else:
        lead = "Use it as evidence for this session, not as orders:"
        first = ("- It does not change what you were returned here to do, and "
                 "everything you change still goes through review and QA.")
        work = ("- Make its current-PR corrections that are not in the code yet "
                f"(compare `git log {r.head}..HEAD`) and that you agree with; "
                f"record any you decline with `pm pr note add {pr_id} '<why>'`.")
    return f"""
## Architecture/Spec Checkpoint {r.ckpt_id}

A whole-PR architecture and specification checkpoint completed {r.completed_at} on HEAD {r.head} (outcomes: {r.outcomes}; owner question: {r.human_question}). Read the full assessment at `{r.path}`. Its summary and requested changes:

{r.digest}

{lead}
{first}
{work}
{spec_rule}
- Follow-ups it lists are filed, not started; they do not remove anything from this PR's scope.
"""


EARLY_REQUEST_ANCHOR = (
    "   - Consider likely future changes beyond the current PR list — does "
    "this PR paint the codebase into a corner or leave good extension points?\n")


def early_request_bullet(pr_id: str) -> str:
    return (
        "   - If the same kind of problem keeps coming back across rounds, "
        "fixes keep adding special cases, or the spec seems to require "
        "something the evidence shows is wrong, you can ask for an early "
        "whole-PR checkpoint: `pm pr checkpoint request "
        f"{pr_id} --reason '<evidence: note ids, scenarios, commits>'`. It "
        "runs before the next review iteration and does not change this "
        "review's verdict.\n")


_REVIEW_INSERT_BEFORE = ("\n## Plan Context\n", "\n## Interacting with the TUI\n",
                         "\n## Session Notes\n", "\n## Steps\n")
_IMPL_INSERT_BEFORE = ("\n## Bug Fix Flow\n", "\n## PR Notes — Handoff Channel\n")


def _insert_before_first(text: str, anchors: tuple[str, ...], block: str,
                         start_after: str) -> str:
    base = text.index(start_after)
    hits = [text.find(a, base) for a in anchors]
    hits = [h for h in hits if h >= 0]
    at = min(hits)
    return text[:at] + "\n" + block.strip("\n") + "\n" + text[at:]


def patch_review_prompt(text: str, pr_id: str, result: CheckpointResult | None,
                        review_spec: bool) -> str:
    """Current review prompt -> proposed review prompt."""
    assert EARLY_REQUEST_ANCHOR in text
    text = text.replace(EARLY_REQUEST_ANCHOR,
                        EARLY_REQUEST_ANCHOR + early_request_bullet(pr_id), 1)
    if result is not None:
        spec_head = ("\n## Implementation Spec\n" if "\n## Implementation Spec\n"
                     in text else "\n## Implementation Spec — MISSING\n")
        text = _insert_before_first(
            text, _REVIEW_INSERT_BEFORE,
            checkpoint_result_block(result, role="review",
                                    review_spec=review_spec, pr_id=pr_id),
            spec_head)
    return text


def patch_impl_prompt(text: str, pr_id: str, result: CheckpointResult | None,
                      review_spec: bool) -> str:
    """Current implementation prompt -> proposed implementation prompt."""
    if result is None:
        return text
    return _insert_before_first(
        text, _IMPL_INSERT_BEFORE,
        checkpoint_result_block(result, role="impl", review_spec=review_spec,
                                pr_id=pr_id),
        "\n## Task\n")


# ---------------------------------------------------------------------------
# P4/P5 — watcher prompts: new `pm pr auto-sequence` status lines.
# ---------------------------------------------------------------------------

_BUG_STEP2_ANCHOR = "- `paused: spec_pending` → spec needs approval. Note in the log; emit\n  INPUT_REQUIRED at end of tick.\n"
_BUG_STEP2_NEW = """- `running: checkpoint (ckpt-<n>)` or `checkpoint: complete (ckpt-<n>),
  continuing review (iteration N)` → an architecture/spec checkpoint is
  running or just finished before the next review iteration. Progress; no
  action needed this tick.
- `paused: input_required (checkpoint)` → the checkpoint pane is waiting for
  the owner. Note in the log; do **not** escalate via watcher INPUT_REQUIRED
  (the pane already surfaced it).
- `paused: checkpoint_blocked (ckpt-<n>)` → the checkpoint used up its
  attempts and needs the owner (`pm pr checkpoint status <pr-id>` shows why).
  Note in the log; emit INPUT_REQUIRED at end of tick.
"""
_STEP3_ANCHOR = "- `paused: spec_pending` — spec is awaiting human review. Same:\n  log and move on.\n"
_STEP3_NEW = """- `running: checkpoint (ckpt-<n>)` / `checkpoint: complete (ckpt-<n>),
  continuing review (iteration N)` — an architecture/spec checkpoint is
  running or just finished; come back next tick.
- `paused: input_required (checkpoint)` — the checkpoint pane is waiting
  for the owner. **Do not** escalate to watcher-level INPUT_REQUIRED; log
  and move on.
- `paused: checkpoint_blocked (ckpt-<n>)` — the checkpoint used up its
  attempts and needs the owner (`pm pr checkpoint status <pr-id>`). Log it
  explicitly and surface it in your verdict.
"""


def patch_watcher_prompt(text: str) -> str:
    out = text
    if _BUG_STEP2_ANCHOR in out:
        out = out.replace(_BUG_STEP2_ANCHOR, _BUG_STEP2_ANCHOR + _BUG_STEP2_NEW, 1)
    n = out.count(_STEP3_ANCHOR)
    assert n <= 1, n
    if n:
        out = out.replace(_STEP3_ANCHOR, _STEP3_ANCHOR + _STEP3_NEW, 1)
    assert out != text, "no watcher anchor matched"
    return out


_AUTO_NORMAL_ANCHOR = ("- A review loop showing multiple iterations (⟳N in the TUI) -- this is "
                       "normal, the loop\n  iterates until PASS.\n")
_AUTO_NORMAL_NEW = """- A review loop whose first iteration after a QA NEEDS_WORK is an
  architecture/spec checkpoint (its pane ends with `CHECKPOINT_COMPLETE`, or with
  `INPUT_REQUIRED` while it waits for the owner) -- this is normal; the loop then
  continues with an ordinary review iteration.
"""
_AUTO_ABNORMAL_ANCHOR = ("- PR in `in_review` with no active review loop and no recent "
                         "review activity\n")
_AUTO_ABNORMAL_NEW = """- PR in `in_review` whose architecture/spec checkpoint is blocked
  (`pm pr checkpoint status <pr-id>` says `blocked`) -- only the owner can retry or
  skip it; restarting the review loop will not clear it. Report it; do not retry it.
"""


def patch_autostart_watcher_prompt(text: str) -> str:
    assert text.count(_AUTO_NORMAL_ANCHOR) == 1
    out = text.replace(_AUTO_NORMAL_ANCHOR, _AUTO_NORMAL_ANCHOR + _AUTO_NORMAL_NEW)
    # The "Abnormal states" list appears twice in the current prompt (a
    # pre-existing duplication); add the line to every copy.
    assert out.count(_AUTO_ABNORMAL_ANCHOR) >= 1
    return out.replace(_AUTO_ABNORMAL_ANCHOR,
                       _AUTO_ABNORMAL_ANCHOR + _AUTO_ABNORMAL_NEW)


# ---------------------------------------------------------------------------
# P6 — composed handoff text written by pm (PR notes), injected into every
# later prompt's "## PR Notes" section.
# ---------------------------------------------------------------------------

def note_complete(ckpt_id, trigger, runs, head, outcomes, hq, followups, path):
    return (f"Architecture/spec checkpoint {ckpt_id} complete ({trigger}; "
            f"covers QA runs {runs}; reviewed HEAD {head}): outcomes "
            f"{outcomes}; owner question: {hq}; follow-ups: {followups}. "
            f"Assessment: {path}. The next review iteration receives it; QA "
            "findings still need fixes, another review and QA.")


def note_blocked(ckpt_id, attempts, last_error):
    return (f"Architecture/spec checkpoint {ckpt_id} blocked after {attempts} "
            f"attempts without a valid assessment (last: {last_error}). Review "
            "will not continue until the owner runs `pm pr checkpoint retry "
            "<pr-id>` or `pm pr checkpoint skip <pr-id> --reason '<why>'`; "
            "evidence from every attempt is kept.")


def note_skipped(ckpt_id, reason, runs):
    return (f"Architecture/spec checkpoint {ckpt_id} skipped by the owner "
            f"(covers QA runs {runs}): {reason}. The interval restarts; QA "
            "findings still need fixes, another review and QA.")
