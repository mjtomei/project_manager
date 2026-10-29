# pr-62ad13d — QA spec: `pm pr close` is a non-destructive lifecycle action

Implementation spec: `pm/specs/pr-62ad13d/impl.md`.
Regression suite: `tests/test_pr_close.py` (62 tests) plus
`tests/test_fake_github.py`, `tests/test_cli_helpers.py`,
`tests/test_store_validation.py`, `tests/test_watcher_loop.py`.

Spec last synced against head `292c738d` (2026-10-29), after the
review iterations that added the QA/sign-off reopen guards, the watcher
prompt's `closed` lifecycle line, the `--remove` dependent wording, and the
`closed_at` centralisation in `_record_status_timestamp`.

Change under test: `pm_core/cli/pr.py:pr_close()` (with
`pm_core/cli/helpers.py:_record_status_timestamp`,
`_terminal_status_at_lock`, `pm_core/pr_utils.py:TERMINAL_PR_STATES`,
`pm_core/pr_sync.py`, `pm_core/tui/sync.py`, `pm_core/cli/pr.py:pr_cleanup`,
`pm_core/fake_github.py`).

The original bug: `pm pr close` deleted the registry entry, ran
`gh pr close --delete-branch`, and `shutil.rmtree`'d the workdir — even with
`--keep-branch`. Closing `#163` (superseded by `#167`) erased its explanatory
note and forced a registry rebuild from Git. QA must first prove that no
longer happens, then probe the surfaces around it (dependents, launch
commands, GitHub sync, explicit cleanup, TUI, concurrency).

Vocabulary used below: a *terminal* record is `status` `merged` or `closed`;
*terminal record retention* means the YAML entry, its notes/description/
dependencies/evidence, the remote branch, and the local workdir all survive
`pm pr close`.

## 1. Requirements (Given / When / Then)

### R1 — Default close keeps the registry record and every field on it
GIVEN a project with a PR whose record carries a title, description,
dependencies, notes (e.g. "Superseded by #167; keep me."), a branch, a
workdir, plan, GitHub fields and lifecycle timestamps,
WHEN the user closes that PR with no flags,
THEN the command exits 0 and reports the PR as closed (status `closed`);
`pm pr show <id>` still lists the same title, description, branch, workdir and
notes; the status line reads `closed`; and every other field is unchanged
apart from the closure timestamp and `updated_at`.

### R2 — Default close leaves the workdir byte-identical
GIVEN a PR workdir containing a modified tracked file, an untracked file, an
ignored file (e.g. `.cache/blob.bin`), and a `captures/qa/` evidence file,
WHEN the user closes the PR,
THEN the directory still exists and every file has the same content as before
the close (no `git clean`, `reset`, stash/drop, or `rmtree` happened), and the
CLI output says the workdir was kept.

### R3 — GitHub PR is closed without deleting the branch
GIVEN a GitHub-backed project whose PR record has a GitHub PR number and whose
head branch exists on the (stand-in) remote,
WHEN the user closes the PR,
THEN the output says the GitHub PR was closed, the stand-in GitHub shows that
PR as `CLOSED`, and the head branch still exists on the remote.

### R4 — `--keep-github` leaves the GitHub PR alone
GIVEN a GitHub-backed PR that is still open on GitHub,
WHEN the user closes it with `--keep-github`,
THEN the local record becomes `closed`, the stand-in GitHub PR state is
unchanged, and the output describes the GitHub PR as unchanged (it must not
claim the PR is "open", since the local status is not a GitHub state).

### R5 — `--keep-branch` is an accepted no-op
GIVEN any open PR with a branch,
WHEN the user closes it with `--keep-branch`,
THEN the command succeeds with no deprecation error, the record is `closed`,
and the branch (local and remote) still exists. `pm pr close --help` documents
the flag as a deprecated no-op.

### R6 — A PR with no GitHub PR closes locally
GIVEN a local/vanilla-backed project (or a GitHub-backed record with no PR
number),
WHEN the user closes the PR,
THEN no GitHub operation is attempted, the record becomes `closed`, and the
workdir and branch are kept.

### R7 — A stale workdir reference is preserved, not cleaned
GIVEN a closed-candidate PR whose `workdir` field points at a path that no
longer exists,
WHEN the user closes it,
THEN the close succeeds and `pm pr show` still prints that workdir path
(close never repairs or prunes).

### R8 — Repeat close is idempotent and never rewrites closure history
GIVEN a PR that is already `closed`,
WHEN the user closes it again,
THEN it exits 0, the entry is still present and `closed`, notes are not
duplicated, the original closure timestamp is unchanged, and a previously
failed GitHub close is re-attempted (so the retry path works).

### R9 — `--remove` deletes only the registry entry
GIVEN a PR with a workdir, a branch, notes and a GitHub PR,
WHEN the user runs `pm pr close <id> --remove`,
THEN the entry is gone from `pm pr list`/`pm pr show`, while the workdir (with
all its files), the branch, and the GitHub PR handling are exactly as
documented: the branch and workdir are kept, the output names only the
resources the entry actually had, and it warns that the retained workdir and
any live windows/containers are no longer tracked by pm.
GIVEN the removed PR was the project's active PR,
WHEN the removal completes,
THEN the active pointer moves to another non-terminal PR, or is cleared when
none remains.

### R10 — Closed PRs are terminal for the lifecycle commands; dependents stay blocked
GIVEN a closed PR that a pending PR depends on,
WHEN the user closes it,
THEN a warning names the dependent PR(s) and states they remain blocked, and
offers the two ways out (reopen, or drop the dependency); the dependent's
status and `depends_on` are unchanged and it does not become "ready".
WHEN the user then tries to start, review, run QA, sign off, merge or
auto-advance the closed PR,
THEN each refuses (or, for auto-advance, reports `closed` and stops) with a
message naming the concrete reopen command `pm pr edit <id> --status pending`,
and nothing is launched or published. All five refusals share one sentence
(`helpers._closed_reopen_hint`), so a drift between them is a defect.
WHEN a watcher/auto-start session is launched against the project,
THEN the lifecycle description it reads says `closed` is retained history,
terminal like `merged`, never satisfies a dependency, and must not be merged
to unblock dependents.
WHEN the user tries to re-add a PR with the same title and description,
THEN the duplicate message names the closed status and the reopen command.
WHEN the user removes the closed record with `--remove` and it had dependents,
THEN the warning says the dependents depend on the *removed* record and are
blocked without it (not that a closed status blocks them), and points at
dropping the dependency (re-adding mints a new id).

### R11 — Reopen and re-close maintain one closure time; merges are protected
GIVEN a closed PR,
WHEN the user reopens it with `pm pr edit <id> --status pending` and later
closes it again,
THEN the reopen clears the closure timestamp (the record no longer claims a
closure it is not in) and the second close records a fresh one.
GIVEN a PR recorded as `merged`,
WHEN the user tries to close it,
THEN the close is refused and the message points at `--remove`; with
`--remove` the registry entry is deleted while the branch and workdir are
kept, no GitHub close is attempted, and the output describes the GitHub PR as
left unchanged ("the PR is recorded as merged") rather than asserting a
GitHub state. With `--remove --keep-github` the keep-github sentence takes
precedence and never says "open".

### R12 — GitHub sync never reopens a locally closed or merged record
GIVEN a PR closed locally with `--keep-github` while its GitHub PR is still
open,
WHEN the user runs `pm pr sync-github` (or the TUI performs its startup
sync),
THEN the local status stays `closed` and the closure timestamp survives; a
merge newly discovered on GitHub still finalizes the record as `merged`
(`merged_at` recorded and the now-stale `closed_at` dropped).
GIVEN a locally `merged` record whose GitHub PR is open or closed,
WHEN the user runs `pm pr sync-github`,
THEN the record stays `merged` with its merge evidence intact.
GIVEN a `closed` record and a GitHub OPEN state discovered while the command
(or the TUI startup sync) is mid-round-trip,
WHEN the sync applies its results under the store lock,
THEN the concurrent closure wins: the record is not rewritten to `in_review`,
and a merge discovered in the same round still finalizes it.

### R13 — Cleanup is separate and explicit
GIVEN a PR just closed by the user,
WHEN the user follows the close output to `pm pr cleanup <id>` with a dirty
workdir,
THEN the first attempt is refused unless `--force` is given, `--force` removes
the workdir, the registry entry survives with its workdir reference cleared,
and the closure status/notes are untouched.
GIVEN exactly one terminal (merged or closed) PR with an existing workdir,
WHEN the user runs `pm pr cleanup` with no id,
THEN it auto-selects that PR (instead of answering "No merged PRs …").
GIVEN several terminal PRs with workdirs,
WHEN the user runs `pm pr cleanup` with no id,
THEN it lists them and asks for an id rather than guessing.
GIVEN a hand-edited `project.yaml` entry with no `id`,
WHEN the user runs `pm pr cleanup --all` or `--prune`,
THEN the malformed entry is skipped (no traceback, and `--all` does not fail
after deleting a workdir) and the valid entries are still cleaned.

### R14 — A GitHub failure never triggers a destructive local fallback
GIVEN a GitHub-backed PR where the `gh` close call fails (scripted failure,
or no usable `gh` at all),
WHEN the user closes the PR,
THEN a warning is printed, the command still exits 0, the local record becomes
`closed`, and the entry, notes, branch and workdir are all intact.

### R15 — Close tears down no live resources and the TUI reflects the closure
GIVEN a running pm TUI session (dedicated test socket) with a live window for
the PR and that PR as the active PR,
WHEN the user closes the PR from the CLI,
THEN the TUI drops it from the default tree view (it is reachable when the
status filter is cycled to closed), the active marker moves off it, the live
window is still alive, and the workdir still exists. Only the explicit
`pm pr cleanup --resources <id>` removes the live window.
Note (known gap, filed as pr-a3b86b7): `closed` has no dedicated show/hide
toggle like `merged`; the status-filter cycle is the only way to reveal it.
QA records this if observed but does not fail this PR for it.

### R16 — Concurrent close keeps one consistent history
GIVEN one project and two or more actors (separate processes/containers)
operating at once,
WHEN two closes race, or a close races `pm pr close --remove`, or a close
races `pm pr sync-github` (GitHub OPEN), a close races `pm pr start` or
`pm pr review`, a close races a reopen (`pm pr edit --status pending`), or a
close races the explicit `pm pr cleanup` / `pm pr cleanup --all`,
THEN every invocation ends without a traceback, the final registry state is
one of the legal outcomes (closed with history intact, or removed once — never
a half-written entry, and never `pending` while still carrying `closed_at`),
a closed record is never resurrected to an active status or re-pointed as
active, and the workdir is never deleted by a close (only by the explicit
cleanup that ran alongside it).
GIVEN another process holds the `project.yaml` store lock longer than the
close's 2-second timeout,
WHEN the user closes a PR,
THEN the command fails with a clear lock-timeout message naming the lock file
and no partial entry is written; retrying after the holder exits succeeds.

## 2. Setup (cross-cutting, described as user steps)

1. Install this branch: `./install.sh --local` (or `pip install -e .` in a
   venv) and confirm `pm which` points at the branch checkout, not
   `/opt/pm-src`.
2. **Isolation is mandatory** (incident 2026-10-29): use a throwaway `HOME`
   (`export HOME=<sandbox>/home`) so all `~/.pm` state, session tags,
   fake-github state and breadcrumbs are disposable; a dedicated tmux socket
   (`export PM_TMUX_SOCKET=<sandbox>/tmux.sock`) for anything that starts a
   session; and unset any inherited `TMUX`/`TMUX_PANE` before creating a
   fixture session (set them deliberately, to the fixture's own pane, when a
   command needs them). Never operate on, attach to, or kill the user's real
   tmux session, and never write global tmux options or shared `~/.pm`
   breadcrumbs.
3. Create a throwaway project: `mkdir <sandbox>/proj && cd <sandbox>/proj &&
   git init && git commit --allow-empty -m init`, then
   `pm init --backend local --no-import` (or `--backend github --no-import`
   for GitHub scenarios).
4. GitHub-backed scenarios use pm's own stand-in, never real GitHub:
   `TAG=$(pm session tag)` then
   `pm fake-github config set --tag "$TAG" '{"git_backed": true,
   "prs":[{"head":"pm/<id>-<slug>","title":"…","draft":false}]}'`.
   `pm fake-github config show --tag "$TAG"` reads the stand-in's state
   (PR states), and the stand-in's backing repo
   `~/.pm/sessions/$TAG/fake-github/remote.git` is where a branch must still
   exist after a close. Scripted failures use the config's `scripts` list.
5. Build realistic PR records through the product: `pm pr add …`,
   `pm pr note add …`, `pm pr edit …`, `pm push`, and `pm pr start` (with no
   Claude binary on PATH so start records state and prints the prompt instead
   of launching a model). Only use direct `project.yaml` edits for the
   bootstrap that the product cannot express (e.g. seeding a status), and say
   so in the manifest.
6. For live-resource/TUI scenarios, drive the TUI on the dedicated socket
   (`pm session` from the project dir) and inspect it with `pm tui view` /
   `tmux -L … capture-pane`; clean up only that socket's session.

## 3. Edge cases and failure modes

- Closing by GitHub number (`pm pr close #163`) and by bare number resolves to
  the same retained record.
- Closing a never-started `pending` PR (no workdir, no branch on the remote)
  succeeds and clears an active pointer that named it.
- Closing the active PR while other PRs exist vs. when none remain (pointer
  moves vs. becomes empty).
- Closing a PR whose entry has a hand-edited dependent record with no `id`
  must still close cleanly (warning scan tolerates it) — no traceback after
  the status was persisted.
- `--remove` on a PR that another process removed first reports that it was
  removed concurrently instead of claiming a removal.
- `--keep-github` combined with `--remove` on a merged record: GitHub is left
  alone, the message never says "open".
- Close with the store lock contended (another `pm` process running) either
  waits and succeeds or fails cleanly — never a half-written entry.
- A workdir that is a symlink or lives outside the project tree is untouched.

## 4. Pass / fail criteria

A scenario passes when every Then clause is observable in the captured
evidence (CLI output, recordings, stand-in GitHub state, file hashes/listings,
tmux captures) and no step requires a human to hand-repair state. A scenario
fails when: the entry is gone or mutated beyond status/timestamps after a
default close; any file in the workdir is missing or changed; the remote branch
is gone; a GitHub call is made when it must not be (or vice versa); a closed
record is started/reviewed/merged/auto-advanced; a dependent is silently
unblocked; a lifecycle guard message does not name a working reopen path; or
close deletes/kills any live resource.

Regression priority: R1/R2/R3 are the original bug and must be demonstrated
directly. R9, R10, R12, R14, R16 are the regressions most likely to be
introduced by the fix (registry removal semantics, terminal-status guards,
sync overwrite, destructive fallback, locking).

## 5. Ambiguities

- **What `--remove` does to GitHub** — resolved in the implementation spec
  (A1): `--remove` is registry-only for *local* resources but still closes the
  GitHub PR unless `--keep-github`. QA treats the help text and output as the
  contract.
- **Active pointer on close** — resolved (A2): move to the first remaining
  non-terminal PR, else clear; a pointer naming a different PR is never
  touched.
- **Closure timestamp on repeat close** — resolved (A6): only a fresh closure
  from a non-closed status records a time; legacy closed entries stay without
  one; restating `closed` keeps the original.
- **Live resources on close** — resolved (A4): close never reclaims windows or
  containers; that is `pm pr cleanup --resources`. The cross-PR interaction
  with pr-3d1fa55/#217 (a sync sweep that would reclaim windows for `closed`)
  is tracked on that PR, out of scope here; QA should not treat a sweep from
  another PR's code as this PR's failure, but should record it if observed.
- **Test-infra caveat, not a product contract:** the out-of-process
  fake-github persists `state.json` with a load→run→save cycle that assumes
  serial `gh` calls. Two genuinely simultaneous `pm` processes can race that
  file; a scenario that races close with sync should assert product invariants
  (registry state, workdir, branch) and, if the stand-in's own state file is
  inconsistent, re-seed and re-run before reporting anything.
- **Prior QA run** (2026-10-29, head `b99217f8`): scenarios 1-9 ran; 1, 2,
  4-9 PASS and scenario 3 NEEDS_WORK because `pm pr review`'s refusal omitted
  the reopen command. That was fixed in `b99217f8` and re-verified. The head
  has since advanced to `292c738d` (QA/sign-off reopen guards via one shared
  helper, the watcher prompt's `closed` lifecycle line, `--remove` dependent
  wording for merged records, `closed_at` centralised in
  `_record_status_timestamp`, `pm pr cleanup --all`/`--prune` tolerating
  malformed entries). Prior evidence is not a pass for the current head.
- No **[UNRESOLVED]** ambiguities: the user clarification of 2026-10-28
  (retain YAML entry, remote branch, local workdir; no automatic cleanup)
  settles the open questions this spec would otherwise raise.
