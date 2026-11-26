# Representative rendered prompt and example brief — pr-c3e2f70

The instruction text is **verbatim** from
[`brief_prompt.md`](brief_prompt.md) ("The complete prompt text"). It is
static: the only rendering is the `input_briefs` payload the watcher reads
from `pm autostart status --json`, plus the PR context it reads from
`pm pr show` / `pm pr note list` / the loop pane. Those are shown below for a
representative PR, followed by the brief that this prompt produces.

The PR record used here is real (`pr-438028c`, GitHub #199, in review). The
review question is illustrative: it is the scope decision named in that PR's
own description (whether to externalize loop state in this PR or a follow-up).

## 1. What the watcher reads: `pm autostart status --json` (excerpt)

```json
{
  "schema": "pm.autostart.status/1",
  "mode": "targets",
  "runs": [
    {
      "pr_id": "pr-438028c",
      "display_id": "#199",
      "title": "Remove popup-cmd carve-outs by giving 'pr qa' and 'review-loop start' real CLI window management",
      "status": "in_review",
      "phase": "review",
      "state": "waiting",
      "reason": "review INPUT_REQUIRED (iteration 4)",
      "window": {"name": "review-#199", "id": "@412"},
      "review": {
        "iteration": 4,
        "verdict": "INPUT_REQUIRED",
        "running": true,
        "input_required": true,
        "input_required_since": "2026-10-28T09:41:00+00:00"
      }
    }
  ],
  "input_briefs": [
    {
      "pr_id": "pr-438028c",
      "display_id": "#199",
      "title": "Remove popup-cmd carve-outs by giving 'pr qa' and 'review-loop start' real CLI window management",
      "status": "in_review",
      "phase": "review",
      "wait_since": "2026-10-28T09:41:00+00:00",
      "age_seconds": 431,
      "window": "review-#199",
      "evidence": "/home/matt/.pm/transcripts/auto-6c1f0a/review-pr-438028c-i4.jsonl",
      "gh_pr": "https://github.com/mjtomei/project_manager/pull/199",
      "fingerprint": "review:4",
      "note_id": null,
      "needs_brief": true
    }
  ]
}
```

`needs_brief: true` because no `[input-brief]` note exists for this wait.
After the note is written, the next status reports `needs_brief: false` with
the same `wait_since` and `fingerprint`, and the watcher writes nothing.

## 2. What the watcher reads: PR context

`pm pr show pr-438028c` (excerpt — the real description):

```
Title: Remove popup-cmd carve-outs by giving 'pr qa' and 'review-loop start' real CLI window management
Status: in_review
GitHub: https://github.com/mjtomei/project_manager/pull/199

## Description
## Goal
Eliminate the two special-case routing branches in `popup_cmd_cmd` ...
After pr-fcaa434 ... the routing list shouldn't need to grow ... but the
*existing* two carve-outs are still there. Get rid of them by giving the
underlying CLI commands their own tmux-aware launchers ...

### 2. `pm pr review-loop start <pr_id>` (new CLI command)
... Loop state (currently `app._review_loops`) needs to externalize to
runtime_state — pr-55c265f and pr-f27b882 are already pushing that direction
...
```

The review pane at `review-#199` (excerpt of the question; illustrative):

```
I've implemented the CLI window management, but `pm pr qa loop` and
`pm pr review-loop start` still need to register loop state, which lives in
`app._qa_loops` / `app._review_loops` in the TUI process. Should I
externalize that to runtime_state in this PR, or leave it as a follow-up and
keep the CLI paths unable to start loops?

INPUT_REQUIRED
```

## 3. The rendered prompt (brief-generation portion)

The watcher receives section 4 of the watcher prompt exactly as written in
`brief_prompt.md`. With the payload above, the operative instructions render
to:

> **Eligibility is already computed.** Run `pm autostart status --json` and
> read the `input_briefs` array. […] `needs_brief: false` means the brief for
> this exact wait and question is already on the PR: do nothing. […]
>
> **Read before writing.** […] `pm pr show <pr_id>` […] `pm pr note list
> <pr_id>` […] capture the loop window with
> `tmux capture-pane -p -t <window> -S -`, or read `evidence` when it is a
> file. […]
>
> **Write the brief.** Roughly 150 words of plain language […]
>
> **Note format.** […] first line must be exactly:
>
> `[input-brief] pr=<pr_id> phase=<review|qa> wait-since=<wait_since> fp=<fingerprint>`
>
> […] closing line: `_Recommendation only — this does not answer the
> question, resume work, waive QA, or authorize a merge._`

For the entry above, the watcher's concrete inputs are:

| Field | Value |
|---|---|
| `pr_id` / `display_id` | `pr-438028c` / `#199` |
| `phase` / `wait_since` | `review` / `2026-10-28T09:41:00+00:00` |
| `age_seconds` | 431 (7m 11s ≥ 300) |
| `window` / `evidence` | `review-#199` / `…/review-pr-438028c-i4.jsonl` |
| `gh_pr` | `https://github.com/mjtomei/project_manager/pull/199` |
| `fingerprint` | `review:4` |
| `note_id` / `needs_brief` | `null` / `true` |

Rendered for this entry: *pr-438028c (#199) has been waiting on review
`INPUT_REQUIRED` for 431 s (≥ 300 s); `needs_brief` is true; write the brief
and add it as a PR note.*

It writes the brief to a temp file and runs:

```
pm pr note add pr-438028c "$(cat /tmp/input-brief.txt)"
```

## 4. The example short brief (145 words)

```
[input-brief] pr=pr-438028c phase=review wait-since=2026-10-28T09:41:00+00:00 fp=review:4
This PR removes the two popup-command carve-outs (`pr qa` and `review-loop
start`) by giving those commands real CLI window management, so the picker no
longer hands them to the TUI. Review asks whether externalizing
`app._qa_loops`/`app._review_loops` to runtime_state belongs in this PR or a
follow-up.

Options: (a) do it here — the new handlers must register loop state to start
a QA or review loop, so the feature is only complete with it; the diff grows,
but the carve-outs can actually be deleted. (b) Follow-up — keeps this PR
small, but the new CLI paths would bypass loop registration or keep a TUI
round-trip, making the carve-out removal cosmetic. The description notes
pr-55c265f and pr-f27b882 are already pushing the same externalization, so the
work is aligned, not speculative. Recommendation: (a), scoped to the two loop
registrations this PR needs; leave the wider refactor to those PRs.

_Recommendation only — this does not answer the question, resume work, waive QA, or authorize a merge._
```

## What the user sees

- `pm pr note list pr-438028c` / `pm pr show pr-438028c` show the brief with
  its note id and timestamp.
- The next review/QA/impl session prompt for the PR carries the brief in its
  PR-notes block (bounded), so the intervention discussion starts from it.
- No other surface changes: PR status, review iteration, sign-off record, and
  the loop pane are untouched.
