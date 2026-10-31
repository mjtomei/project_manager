# Candidate brief-generation prompt — pr-c3e2f70

This file is the **complete, reviewable prompt text**. It is inserted
verbatim (as a module-level constant) into
`pm_core/prompt_gen.py::generate_watcher_prompt`, as section **4** after
"Surface Issues Needing Human Input" (the following sections renumber
4→5, 5→6, 6→7). Nothing else in the watcher prompt changes.

The text contains no f-string placeholders and no braces, so it can be
concatenated into the existing f-string unchanged. The only dynamic data is
the `input_briefs` array that the watcher reads from
`pm autostart status --json` at run time (see
[`brief_prompt_example.md`](brief_prompt_example.md) for a rendered payload).

## Composed instructions in this prompt

The section composes five instruction blocks; all of them are part of the
candidate text below:

1. **Eligibility contract** — read `input_briefs`; never compute eligibility;
   `needs_brief: false` means skip; sign-off/merge waits never appear; a failed
   status command means skip this iteration.
2. **Context-reading contract** — `pm pr show`, `pm pr note list`, and the
   loop pane or `evidence` file; never send input to the loop pane.
3. **Content contract** — the three generic questions, ~150 words (≤ ~200),
   plain language, PR identifier + link to the original question/evidence,
   options weighed on simplest-sufficient / maintenance & code quality / user
   impact / delivery, estimates only from observed project history.
4. **Format contract** — the exact `[input-brief] …` first line and the exact
   recommendation-only closing line, written through `pm pr note add/edit`.
5. **Guardrails** — the brief answers nothing, resumes nothing, waives no QA,
   authorizes no merge, and never changes the watcher's `READY` verdict.

## The complete prompt text (verbatim)

```markdown
### 4. Prepare Input-Required Briefs

When a review or QA loop has been waiting on `INPUT_REQUIRED` for at least
5 minutes, prepare a short brief so the user can read it — or discuss it on a
call — without reconstructing the history.

**Eligibility is already computed.** Run `pm autostart status --json` and read
the `input_briefs` array. Each entry is one waiting PR and carries:

- `pr_id`, `display_id`, `title`, `status`, `phase` (`review` or `qa`)
- `wait_since` (UTC) and `age_seconds`
- `window` (the loop window) and `evidence` (a transcript or QA status path,
  when known)
- `gh_pr` (the GitHub PR URL)
- `fingerprint` (the current question identity)
- `note_id` (the existing brief for this same wait, or null)
- `needs_brief` (true when the brief is missing or the question changed)

Do not compute eligibility yourself. `needs_brief: false` means the brief for
this exact wait and question is already on the PR: do nothing. Sign-off and
merge approval waits never appear in `input_briefs`; never brief them. If the
command fails (for example no TUI owner), skip briefs this iteration.

**Read before writing.** Use the existing surfaces only:

- `pm pr show <pr_id>` — description, notes, GitHub link. For QA, the
  `QA INPUT_REQUIRED:` note names the failing scenarios and the QA workdir.
- `pm pr note list <pr_id>` — earlier notes, including any earlier brief.
- The question and the discussion around it: capture the loop window with
  `tmux capture-pane -p -t <window> -S -`, or read `evidence` when it is a
  file. Do not send input to the loop pane.

**Write the brief.** Roughly 150 words of plain language (do not exceed
about 200), answering:

1. What does this PR do?
2. What is the `INPUT_REQUIRED` about, and what input is needed?
3. What are the practical options and their main tradeoffs? Weigh the
   simplest sufficient approach, maintenance and code quality, impact on
   users, and what each option does to delivery. Give a brief recommendation
   when the evidence supports one.

Name the PR identifier and include a link to the original question/evidence:
the `gh_pr` URL plus the window name or the `evidence` path. If an estimate
helps (how often something happens, how long a step takes), base it on what
this project's notes and history actually show; never invent time or cost
estimates.

**Note format.** Write the text to a temp file, then add it as a PR note. The
first line must be exactly:

[input-brief] pr=<pr_id> phase=<review|qa> wait-since=<wait_since> fp=<fingerprint>

Then the brief, then exactly this closing line:

_Recommendation only — this does not answer the question, resume work, waive QA, or authorize a merge._

Use `pm pr note add <pr_id> "$(cat /tmp/input-brief.txt)"`, or
`pm pr note edit <pr_id> <note_id> "$(cat /tmp/input-brief.txt)"` when
`note_id` is set.

The brief is informational. Do not answer the question, send keys to the loop
pane, restart the loop, change PR status, or run sign-off/merge commands.
Briefs never change your verdict: emit **READY** whether or not you wrote one.
```

## Notes for the reviewer

- The 5-minute threshold appears in the prompt as user-facing wording; the
  authoritative constant is `input_brief.BRIEF_THRESHOLD_SECONDS = 300` used by
  `build_status` to decide `needs_brief`. The prompt never re-derives it.
- The prompt names no model, no cost, and no deadline. The only estimate it
  permits is one grounded in observed project history.
- "Sign-off and merge approval waits never appear in `input_briefs`" is a
  promise made by `build_input_briefs` (status/phase filter), not something the
  watcher has to check.
