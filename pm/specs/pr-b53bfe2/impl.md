# pr-b53bfe2 — Resolve workspace trust across all automated workflow sessions

## Ground truth (verified against claude 2.1.296 in this environment)

- Claude Code stores workspace trust in its global config file
  (`$CLAUDE_CONFIG_DIR/.claude.json`, else `~/.claude.json`) under
  `projects[<path>].hasTrustDialogAccepted`.
- The trust check (`aH`/`Ow`/`Mw` in the bundled CLI) accepts the config's
  project path (git root of cwd, else resolved cwd) or any ancestor of cwd
  **bounded by the git root**. Trusting a parent above a checkout (e.g.
  `~/.pm/workdirs`) does NOT cover the checkout, so every git checkout pm
  creates needs its own entry.
- Accepting the dialog writes `projects[<git root>] = {...existing,
  hasTrustDialogAccepted: true}` under a `proper-lockfile` lock whose lock
  path is `<config>.lock` (an mkdir lock, 10s stale timeout), then an atomic
  write.
- The dialog ("Accessing workspace: <path> … Is this a project you created
  or one you trust? … ❯ No, exit / Yes, I trust this folder") defaults to
  **No, exit**; pressing Enter blindly kills the session.
- `--dangerously-skip-permissions` does NOT bypass the dialog (reproduced:
  `$CAP/impl/pre-fix/skip-permissions-still-blocked`).
- `claude -p` (print mode) skips the dialog, so `launch_claude_print*`
  needs no change.
- Pre-fix repro: `$CAP/impl/pre-fix/host-planner-blocked` — the host QA
  planner command built by `build_claude_shell_cmd(session_type="qa_planning")`
  in a fresh checkout sat at the dialog for the full wait and never ran the
  prompt.

## Requirements

R1. **Trust bootstrap at the launch boundary (host).**
`pm_core/claude_launcher.build_claude_shell_cmd` and `launch_claude` are
the existing session-launch boundary used by every workflow role
(impl `cli/pr.py:pr_start`, review `cli/pr.py:pr_review` via
`review_loop`, merge `cli/pr.py:pr_merge`, sign-off `signoff.py`,
QA planner/Scenario 0/concretizer/worker/verifier/finalizer in
`qa_loop.py`, watcher `cli/watcher.py`). When a real (non-fake) Claude is
launched on the host with a `cwd`, the launcher calls a provider-level
`prepare_workspace(cwd)` that writes the trust entry for that checkout
before the command runs. Container launches (`write_dir` set and differing
from `cwd`) are skipped here — see R2.

R2. **Trust bootstrap for container sessions.**
`container.create_container` copies the host `.claude.json` into the
container. The copy is seeded with `projects["/workspace"]`
(`_CONTAINER_WORKDIR`) trusted when the host workdir being mounted is an
approved PM workdir. The host file is not modified for the container path.

R3. **Narrow scope.** Only approved paths are trusted:
- PM-created workdirs: anything at or under `paths.workdirs_base()`
  (`~/.pm/workdirs/` — PR clones, `qa/<pr>-<loop>/s-N/repo` scenario
  clones, meta workdirs);
- paths the user explicitly authorizes with `pm trust add <path>`
  (stored in `~/.pm/settings/trusted-workspaces`, one path per line).
Paths are compared after `realpath`. No parent/home/`/` trust is ever
written; the entry is written for the checkout itself (and its git root
when that root is itself approved). This is separate from
`--dangerously-skip-permissions`; neither implies the other.

R4. **Provider boundary.** The Claude-specific mechanics (config path,
lock protocol, JSON key, dialog text and key handling) live in
`pm_core/workspace_trust.py` as a `ClaudeWorkspaceTrust` runtime registered
under `"claude"`. pm code outside the launcher reaches it only through
`claude_launcher` (`prepare_workspace`, `WorkspacePromptWatch`,
`WorkspaceTrustBlocked`). Another runtime can register its own
implementation (`register_trust_runtime`); a runtime without one gets a
no-op that reports `unsupported` rather than failing.

R5. **Explicit handling of the known prompt (fallback).** If the dialog is
still seen for an approved workdir (e.g. a container created before this
fix, a config-write race), the watchdog selects "Yes, I trust this folder"
by reading the cursor position from the screen (Up/Down to that row, then
Enter), never blind Enter. At most 2 attempts per pane: the count is kept
on the tmux pane (`@pm_trust_accept_attempts`), so the QA loop's watch,
the TUI idle tracker's watch and per-call CLI trackers share one budget.
When the dialog names a host directory, that directory decides (it must
itself be approved — a session that started outside its intended approved
workdir is never trusted by proxy); only an unreadable or container-internal
(`/workspace…`) path falls back to the launch workdir — any other shown path
that is not a host directory is refused.  A path that hard-wraps in a narrow
pane is rejoined from its continuation lines before it is checked. Detection requires a line-anchored
option row, and the watch ends for good once the session transcript JSONL
exists (Claude writes it only after the dialog), so dialog-like text later in
the first turn — e.g. a reviewer or QA worker displaying this module or a
captured dialog — never sends keys or reports a false block.

R6. **Bounded, actionable failure.**
- `WorkspacePromptWatch(pane_id, workdir)` checks the pane at most every
  5s; if the dialog stays visible for longer than the grace (default 120s,
  global setting `trust-prompt-grace-seconds`, settable with `pm set`), it reports a message naming
  the path and the fix (`pm trust add <path>` or accept in the pane, then
  restart).
- QA planner (`qa_loop.run_qa_sync`): the planner pane is watched until its
  first idle turn; if the watch fires (dialog visible past the grace — a
  failed bootstrap is caught this way too, after the R5 accept attempt),
  planning stops with `INPUT_REQUIRED` and a `_error` explaining the trust
  block; no execution phase and **no finalizer** run. The qa_status
  pane is still split beside the planner so the error is visible in the
  QA window, not only in the log.
- Zero scenarios after planning (any cause): the finalizer is skipped
  (`_execute_and_finalize`), since there are no scenario pushes to
  reconcile. This removes the second #229 hang.
- `loop_shared.poll_for_verdict` (review loop, watchers, QA finalize,
  verifier, concretizer) raises `WorkspaceTrustBlocked` when the watch
  fires. The review loop already maps exceptions to `ERROR` + message; QA
  callers catch it and record the reason.
- QA scenario workers (`_poll_tmux_verdicts`): a worker that never gets
  past the dialog is marked `INPUT_REQUIRED` with reason
  "blocked at workspace-trust prompt …". Workers are watched from launch,
  not after the verdict grace. A scenario whose concretizer was blocked
  (no worker session) keeps its reason and is settled at once rather than
  later overwritten with "no session id". `qa:<pr>:s<n>` tracker keys
  belong to `qa_loop_ui`; the impl-idle poller must not unregister them
  (doing so reset the watch, and its accept budget, on every tick).
- `pane_idle.PaneIdleTracker.poll` (TUI-tracked impl/sign-off/merge panes):
  before the first hook event, a trust-blocked pane is reported as
  `waiting_for_input` (the TUI's existing "needs you" state).  The tracker
  has no launch workdir, so the R5 auto-accept fires only when the dialog
  names an approved host directory (a pre-fix container showing
  `/workspace` stays "needs you"; new containers are seeded per R2).
- Panes an earlier TUI launched (found by QA S4 after a hard TUI kill): the
  tracker can't register them, because their transcript symlinks live in
  the old TUI's run dir. `_poll_impl_idle` still trust-watches such an
  impl/review pane. `claude_launcher.pane_transcript_path` recovers the
  session id from the pane's start command (`--session-id`/`--resume`) and
  the cwd from its `cd` prefix (`/workspace` for a container exec, else the
  PR workdir), and the watch runs with the PR workdir. That gives the same
  R5 accept by cursor, the shared per-pane budget, and one sticky report
  after the grace. Only the trust watch is added: idle tracking and
  auto-advance for those panes are unchanged (pr-5d66709).

R7. **Unknown/unapproved workspace behavior stays explicit.** For a cwd
outside the approved roots nothing is written; the launcher logs
`workspace trust: <path> not approved`, the dialog appears as before, and
the R6 failure path names `pm trust add <path>` as the remedy.  A merge
resolution window that still opens in an unapproved directory (the
vanilla/GitHub pull-from-origin window runs in the project root, pr-19990de)
prints the same remedy when it opens, since nothing watches that pane for a
bounded failure.

R8. **CLI.** `pm trust status [PATH]`, `pm trust add PATH`,
`pm trust remove PATH`, `pm trust list`. `add` records the authorization
and bootstraps the entry immediately; `remove` drops the authorization (it
does not edit Claude's config — revoking Claude trust remains a Claude
action).  `add` refuses the home directory and any directory containing it
(`/`, `/home`), which would amount to blanket trust.  `add`/`remove`
serialize on an flock beside `trusted-workspaces` and replace the file
atomically (parallel adds otherwise lost roots); an `add` whose bootstrap
fails removes the root it added, so a failed command leaves nothing
authorized.

R9. **Launch cwd == bootstrapped cwd.** Trusting a checkout only helps if
Claude actually runs there. Found live: `cli/pr.py:_launch_review_window`
split the review Claude pane with no `-c`, so tmux started it in the
*calling* process's cwd (the TUI's `pm/` dir); the reviewer sat at the trust
prompt for that dir while the PR checkout (correctly trusted) went unused,
and its transcript landed outside the path the loop polls. Fixes: the review
split passes `cwd=workdir`, and `build_claude_shell_cmd` prefixes host
launches with `cd <cwd> &&` so every role runs in the directory it
bootstrapped regardless of how the pane was created. Container launches are
unchanged (`exec -w /workspace`).

R10. **Local-backend merge resolution runs in the PR workdir** (user
decision 2026-10-13, option (a); found by QA as pr-e835d8f, together with
pr-a75da60). Before, `pm pr merge` merged onto the workdir's stale
`<base>`, so the fast-forward into the main repo failed and
`_pull_from_workdir` opened the resolution window in the main repo — the
project root, which pm deliberately does not auto-trust and which holds the
user's own work — where it sat at the trust dialog. Now:
- before the PR merge, `_sync_workdir_base` fetches `<base>` from the main
  repo into the workdir and merges it (fast-forward when possible; never a
  reset, so an earlier unpropagated merge commit is kept). Independent PRs
  merge straight through (pr-a75da60); a real conflict surfaces in the PR
  workdir and the window opens there.
- at propagation (`_propagate_to_repo`), if the main repo's `<base>` has
  commits the workdir's lacks (it moved since the workdir merge), it is
  integrated into the workdir the same way and the fast-forward retried; a
  conflict opens the window in the PR workdir. The TUI's existing MERGED →
  `--propagation-only` follow-up then fast-forwards the main repo.
- any other failure in the main repo itself (fetch error, uncommitted work
  blocking the fast-forward after the auto-stash) is reported with
  `pm pr merge --propagation-only <pr>` as the next step and exits non-zero;
  no Claude session is sent into the main repo, and nothing there is reset.
- the local merge prompt tells Claude its result must contain the main
  repo's current `<base>` and `<branch>` and not to touch the main repo.
  The old pull-from-workdir prompt variant (resolve in the main repo) is
  gone.
The project root is still never trusted automatically. Out of scope here
and tracked as pr-19990de: the vanilla/GitHub pull-from-origin window, and the
vanilla workdir's `<base>` not being fast-forwarded to `origin/<base>`.

## Implicit requirements

- The config write must not clobber concurrent Claude writes: take the same
  `<config>.lock` mkdir lock (stale after 10s), re-read inside the lock,
  merge only the one key, write to a temp file in the same directory, keep
  the file mode (0600), and `os.replace`. A missing config file is created
  with just `projects`; an unparseable one is left untouched (error outcome).
- Bootstrap is idempotent and cheap for already-trusted paths (no write when
  the entry is already true), since it runs on every launch, including
  resumes (`--resume`) and relaunches.
- Fake-claude launches skip bootstrap (no real dialog; keeps tests hermetic).
- Restart/session handoff: resumed loops re-launch through the same
  boundary, so they re-bootstrap; adopted in-flight panes are covered by the
  watchdog (R5/R6).
- Unit tests must not touch the real `~/.claude.json`: tests point
  `CLAUDE_CONFIG_DIR` at a tmp dir (the launcher honours it), and a test
  guard verifies this.

## Ambiguities (resolved)

1. *Should the project's own base checkout (pm root) be auto-approved?* No.
   Automated sessions run in PM-created workdirs; the base checkout is the
   user's interactive space. The user can `pm trust add` it. Local-backend
   merge resolution therefore moved into the PR workdir (R10) rather than
   trusting the root.
2. *Grace period length.* 120s default (configurable): long enough for a
   human watching to accept manually, ~30x shorter than the 1h planner
   timeout.
3. *Container trust mechanism.* Seed the copied config rather than setting
   `CLAUDE_CODE_SANDBOXED` (undocumented, broader effects).
4. *Finalizer with zero scenarios.* Skip it: it only reconciles scenario
   pushes, and there are none.
5. *Watcher-framework subsumption note (pr-3032fb6).* Not relied on; this
   PR delivers the fix directly as the task requires.

## Edge cases

- Symlinked workdirs: both the absolute and the realpath key are written when
  they differ and both are approved.
- Non-git dirs (`~/.pm/workdirs/qa/<pr>-<hex>`): cwd key written; Claude's
  unbounded parent walk also finds it.
- Container reuse (`wrap_claude_cmd` reuses a running container): the
  config copied at creation already carries the trust; a pre-fix container
  is covered by R5 auto-accept.
- Concurrent launches (parallel scenario clones) serialize on the lock.
- Stale `.lock` dir left by a crashed writer: removed after 10s, like
  proper-lockfile.
- CLAUDE_CONFIG_DIR set: config path follows it.
