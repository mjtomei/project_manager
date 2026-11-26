# QA spec — pr-1cb6e15: `pm pr review` must not regress qa/sign_off to in_review

## Context

`pm pr review` used to fall through to its `in_progress → in_review` status
write for any status it did not explicitly guard (`merged`, `in_review`,
`pending`). On a PR that is in `qa` or `sign_off` this silently moved the PR
**backwards** to `in_review` while the QA loop / sign-off router was
mid-flight. The sign-off driver refuses to collect a verdict unless the PR is
still `sign_off`, so the original verdict was stranded (incident on #243).

The fix makes `pm pr review` on `qa`/`sign_off` an **inspection**: it focuses
the PR's existing `review-<display>` window, writes nothing, and starts no
agent. `--fresh` / `--review-loop` are refused there; `--no-window` is a
no-op; `closed` is refused like `merged`. `in_progress`, `in_review`,
`pending`, `merged` keep their previous behavior.

## Setup (cross-cutting)

- A throwaway pm project (`pm init --backend local --no-import`) with a git
  repo and a git-backed workdir, in a `pm session` tmux session.
- PRs can be placed in `qa` / `sign_off` through the normal user surface
  (`pm pr edit <id> --status qa|sign_off`) after they have passed through
  review — or by driving review/QA with `fake-claude`.
- A review window from the earlier review is represented by a tmux window
  named `review-<display>` (for a local PR, `review-<pr-id>`; for a
  GitHub-numbered PR, `review-#42`) in the pm session. Either leave the real
  window opened by an earlier `pm pr review`, or create the window with the
  same name and a harmless command.
- `fake-claude` supplies deterministic verdicts for live QA/sign-off flows;
  `fake-github` supplies a draft PR for the GitHub backend.
- The project's `pm/project.yaml` is the single source of truth for status,
  timestamps, `signoff`, `signoff_return` and `integration` records.

---

## Requirements

### R1 — Plain inspection of a `qa` PR leaves everything unchanged

**Given** a PR whose status is `qa` and whose earlier review window
(`review-<display>`) is open in the pm session,
**When** the user runs `pm pr review <pr-id>` from a shell inside that
session,
**Then**
- the command exits 0 and prints one line saying the PR is in QA and that
  its status was not changed,
- the PR's status is still `qa`, and its `reviewed_at`/status timestamps,
  sign-off record, return record, integration record and all other metadata
  are byte-for-byte unchanged,
- the existing review window is focused (the user's client switches to it),
- no new tmux window is created, no Claude session/agent starts, and no
  second review container is launched.

### R2 — Plain inspection of a `sign_off` PR behaves identically

**Given** a PR whose status is `sign_off` with an open `review-<display>`
window,
**When** the user runs `pm pr review <pr-id>`,
**Then** the same as R1, with the message naming sign-off: the PR stays
`sign_off`, the review window is focused, and nothing is written or started.

### R3 — Inspection with no review window still changes nothing

**Given** a PR in `qa` (or `sign_off`) with **no** `review-<display>` window
open,
**When** the user runs `pm pr review <pr-id>`,
**Then** the command exits 0, tells the user there is no review window to
open and that the status is unchanged / no new review was started, and no
window, container or agent is created.

### R4 — `--fresh` and `--review-loop` are refused on a later phase

**Given** a PR in `qa` or `sign_off`,
**When** the user runs `pm pr review --fresh <pr-id>` or
`pm pr review --review-loop <pr-id>`,
**Then** the command fails with a nonzero exit and an error (on stderr)
saying a fresh review is refused while the PR is in that phase and pointing
at plain `pm pr review` for inspection; the PR's status and records are
unchanged, no window is created or killed, and no agent starts.

### R5 — `--no-window` on a later phase is a no-op

**Given** a PR in `qa` or `sign_off`,
**When** the user (or an auto-review caller) runs
`pm pr review --no-window <pr-id>`,
**Then** the command exits 0, prints a short "status unchanged" line, does
not focus or create a window, and writes nothing.

### R6 — `closed` is refused like `merged`

**Given** a PR whose status is `closed` (or `merged`),
**When** the user runs `pm pr review <pr-id>`,
**Then** the command fails with a nonzero exit and says the PR is already
`closed`/`merged`; the status is unchanged and no review is started.

### R7 — Phases before the review step are unchanged

**Given** a PR in `in_progress`,
**When** the user runs `pm pr review <pr-id>`,
**Then** the PR moves to `in_review`, a review window is opened, and the
GitHub draft (when the backend is GitHub) is marked ready — the pre-fix
behavior.

**Given** a PR already in `in_review`,
**When** the user runs `pm pr review <pr-id>`,
**Then** the command says it is already `in_review` and opens/refocuses the
review window without a status change.

**Given** a PR in `pending`,
**When** the user runs `pm pr review <pr-id>`,
**Then** the command refuses and points at `pm pr start`.

### R8 — GitHub-backed `qa`/`sign_off` inspection makes no GitHub change

**Given** a GitHub-backed project with a PR in `qa` whose GitHub PR is still
a draft,
**When** the user runs `pm pr review <pr-id>`,
**Then** the GitHub PR remains a draft (no ready-for-review upgrade, no
network mutation) and the pm status stays `qa`.

### R9 — TUI `d` on a later-phase PR only switches/focuses

**Given** a `qa` PR selected in the TUI with an existing `review-<display>`
window,
**When** the user presses `d`,
**Then** the TUI switches to the review window and logs that it switched;
the PR stays `qa`.

**Given** a `qa` PR selected in the TUI with no review window,
**When** the user presses `d`,
**Then** the spawned `pm pr review` produces exactly one visible log line
naming the phase and saying the status was unchanged; the PR stays `qa` and
no agent starts.

### R10 — Picker surfaces the inspection notice and refusals

**Given** a `qa` PR and the PR action picker open,
**When** the user chooses the review action,
**Then** the popup shows the same single inspection line ("… is in QA —
… without changing status") and the PR stays `qa`.

**Given** the same PR and picker,
**When** the user chooses the fresh-review chord (`z d`),
**Then** the popup shows an error (`pm error: … refused …`) and waits for
dismissal, and the PR stays `qa`.

### R11 — A review loop cannot be started against a later-phase PR

**Given** a `qa` PR selected in the TUI,
**When** the user starts a review loop (`zz d`),
**Then** the loop stops with an error surfacing the refusal, no review
window/agent is created, and the PR stays `qa` (the QA phase keeps running
undisturbed).

### R12 — A live QA loop survives the user opening the review

**Given** a `qa` PR whose QA loop is mid-flight (fake-claude driving it, the
`qa-<display>` window alive),
**When** the user opens the earlier review through `pm pr review <pr-id>`
and through the picker,
**Then** the PR stays `qa`, the QA window keeps running and is not killed or
restarted, no review agent starts, and when QA finishes its own verdict still
routes: `NEEDS_WORK` moves the PR to `in_review` exactly once (and a review
iteration starts), or `PASS` moves it to `sign_off`.

### R13 — A live sign-off routes its original verdict exactly once

**Given** a `sign_off` PR with a launched sign-off router (fake-claude
carries `SIGNOFF_MERGE` in the driver transcript) and the PR's workdir at a
known HEAD,
**When** the user opens the review via the real CLI and via the picker
between the launch stamp and the driver tick, and then the auto-sequence
driver ticks,
**Then**
- the PR is still `sign_off` after the inspection(s), with `signoff`,
  `signoff_return`, `integration`, workdir dirty files, captures and drafts
  unchanged, and no second agent/window started,
- the tick adopts the **original** `SIGNOFF_MERGE` exactly once: one
  `pr["signoff"]` record bound to that HEAD, and the step reports
  `ready_to_merge`,
- a second tick does not re-route or duplicate the verdict,
- the PR is not auto-merged (it remains in `sign_off` awaiting the merge
  decision).

### R14 — Concurrent inspections do not corrupt state

**Given** a `qa` PR and a concurrent phase driver writing `project.yaml`
(e.g. a QA tick or repeated `pm pr auto-sequence`),
**When** two inspection invocations run at the same time (two shells, or CLI
plus picker) — and one of them is `--fresh`,
**Then** both plain inspections exit 0, the `--fresh` one is refused, the PR
stays `qa`, `project.yaml` remains valid (no lost writes, no duplicated PRs),
exactly one `review-<display>` window exists, and no agent starts.

---

## Edge cases and failure modes

- **Outside tmux.** `pm pr review` on a `qa` PR from a plain shell exits 0
  and prints the "no review window to open / status unchanged" line; it does
  not error and does not create anything.
- **GitHub-numbered PR.** When the PR is keyed by `#42`/`42`, the existing
  `review-#42` window is the one focused, and the message uses `#42`.
- **`--transcript` supplied** (TUI passes one): ignored on the inspection
  path; no transcript symlink or session is created.
- **No PR id.** Inference still only selects `in_progress` PRs; a later-phase
  PR is reached by explicit id or by picker/TUI selection.
- **Refocus failure.** If switching to the review window fails (e.g. the
  window vanished between lookup and select), the command still exits 0,
  says no window could be opened, and leaves the status unchanged.
- **Sign-off return belonging to `in_review`.** A pending REVIEW return is
  not cleared by inspection (only `_launch_review_window` clears it), so an
  in-flight return is not consumed.
- **`merged` message preserved.** The merged refusal text still names
  `merged`; `closed` gets the parallel message.

## Pass/Fail criteria

A scenario passes when every Then above is observed from the user's surface:
the status/records in `pm/project.yaml` (read through `pm pr show`/`pm pr
list` or a direct read) are unchanged, the printed/rendered messages appear
on the documented stream (stdout for inspection notices, stderr for
refusals), tmux windows behave as described (focused, not created/killed),
and live QA/sign-off verdicts route exactly once. Any status regression
(`qa`/`sign_off` → `in_review`), any newly created review window/agent on
the inspection path, any lost metadata/dirty work, any duplicated or dropped
sign-off verdict, or any auto-merge is a failure. The new regression tests
in `tests/test_pr.py` and the picker stdout test in
`tests/test_popup_picker.py` must pass on the PR branch (and the core
reproduction test must fail against the base revision of
`pm_core/cli/pr.py`).

## Ambiguities resolved

1. **`--fresh` on `qa`/`sign_off`: refuse or silently inspect?** Resolved:
   refuse with a nonzero exit. It is the only option that distinguishes an
   explicit fresh review from inspection and guarantees the running phase
   never gets a second agent or a HEAD change.
2. **No review window on a later-phase PR: create one?** Resolved: no.
   Creating one launches a review agent and can clear a sign-off return
   claim — exactly the churn the fix forbids. Print "no review window".
3. **Is `closed` in scope?** Resolved: yes, refused like `merged` (today it
   would be resurrected to `in_review`).
4. **Does the TUI's own `d` fast path need the new message?** Resolved: no.
   It already focuses an existing window without a subprocess or state
   change; the notice matters on the spawned-CLI path.
5. **Should a review loop be startable on a later-phase PR?** Resolved: no —
   its first iteration calls `pr review --fresh --review-loop`, which is
   refused, so the loop errors out before starting an agent.

No unresolved ambiguities.
