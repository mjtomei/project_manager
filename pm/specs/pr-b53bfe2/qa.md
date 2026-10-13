# QA spec: pr-b53bfe2, Resolve workspace trust across all automated workflow sessions

This spec is grounded in `git diff master...HEAD`:

- `pm_core/workspace_trust.py`
- `claude_launcher.py`: `prepare_workspace`, `WorkspacePromptWatch`, and the
  `cd <cwd> &&` launch prefix
- `container.py`: config seeding
- Trust watches in `loop_shared`, `qa_loop`, `review_loop` and `pane_idle`
- `cli/trust.py`
- `cli/pr.py`: review split cwd
- `cli/meta.py`: meta cwd
- `pm/specs/pr-b53bfe2/impl.md`

The QA plan has exactly two scenarios. Each one executes one of the two named
sections below in full, together with the shared **Setup**:

- **SCENARIO 1: Host trust policy and configuration** → section
  "Host trust policy and configuration"
- **SCENARIO 2: Workflow and container trust** → section
  "Workflow and container trust"

## Run disclosures (read first)

- **Supervised run.** This is QA planning run #230. The supervisor manually
  accepted the outer host planner and Scenario-0 trust prompts on verified pm
  checkout paths. So this run is supervised: it is **not** an unattended
  autostart qualification trial. Do not report it as one.
- **The planner edited application code.** Commit `7d79fce1` registered
  `trust-prompt-grace-seconds` in `pm_core/cli/__init__.py`. That setting is
  documented, but `pm set` used to reject it as "Unknown setting". The
  commit adds the regression test
  `tests/test_workspace_trust.py::test_grace_setting_is_configurable_via_pm_set`
  (fails before the fix, passes after).
  - This edit is **unreviewed**. It must go through another review pass
    before sign-off.
  - All-PASS QA does **not** make it reviewed. The host controller lacks
    the planner-code-change guard.
  - Scenario reports must repeat this disclosure.
- **No more app edits during planning.** Findings from these scenarios are
  fixed or filed through the normal flow, as the steps say.
- **Every known remaining bug** must end with one of: a fix (commit), a
  tracking PR, or an explicit UNRESOLVED verdict. A bug being nonblocking
  never excuses leaving it untracked. Already tracked:
  - `pr-7e0eec4`: the container copies `$HOME/.claude.json` and ignores
    `CLAUDE_CONFIG_DIR`.
  - `pr-8c0d680`: the known `/workspace` host-dir limit.
  - `pr-b8561ac`: the old host terminal-intake planner bug, where terminal
    capture truncates a complete plan.

## Background facts (verified with claude 2.1.296)

- **Where trust is stored.** Claude keeps trust in
  `$CLAUDE_CONFIG_DIR/.claude.json` (else `~/.claude.json`), as
  `projects[<path>].hasTrustDialogAccepted`.
  - Claude only walks up to the git root when it looks for trust. So
    trusting a parent above a checkout does not cover the checkout.
  - Claude writes this file under the mkdir lock `<config>.lock`, which goes
    stale after 10s.
- **The dialog.** It reads: "Accessing workspace: <path> … ❯ No, exit /
  Yes, I trust this folder".
  - It defaults to **No, exit**, so a blind Enter kills the session.
  - `--dangerously-skip-permissions` does **not** bypass it.
  - `claude -p` (print mode) never shows it. Print mode therefore cannot
    prove the prompt is gone: **every trust smoke test must be an
    interactive `claude` in a tmux pane.**
- **Cost.** The dialog appears before any API call, so observing it costs
  nothing. A session that gets past it submits its prompt, which costs API.
- **What pm approves.** pm approves only these paths:
  - anything at or under `~/.pm/workdirs`;
  - paths listed by `pm trust add`, stored in
    `~/.pm/settings/trusted-workspaces`.
  - Paths are compared after realpath.
  - pm never writes trust for a parent, for home, or for `/`.
- **fake-claude.** Launches through fake-claude skip the bootstrap, by
  design.

## Setup (both scenarios)

**Instruction:** `pm/qa/instructions/tui-manual-test.md` (throwaway project,
`pm session`, fake-claude).

**Artifact recipes:**

- `pm/qa/artifacts/tmux-screen-recording.md` for TUI and pane evidence.
- `pm/qa/artifacts/cli-recording.md` for CLI evidence.
- Save every capture under the per-PR captures directory named in the
  worker prompt.
- Keep **both** kinds of evidence:
  - the original blocked path ("pre-fix / blocked");
  - the repaired path ("post-fix").

Steps:

1. **Install the exact published head.**
   - Clone or check out the pushed PR branch head that contains this file.
   - Run `./install.sh --local` from that clone (or use the venv plus
     `PYTHONPATH` override in tui-manual-test.md).
   - `pm which` must print that clone.
   - Record `git rev-parse HEAD` in every manifest.
2. **Isolate Claude config and auth. Never edit the real host config.**
   - Run only inside the scenario container. Never touch the outer host's
     `~/.claude.json`, `~/.claude/` or `~/.pm`.
   - Make a scratch config dir, e.g. `$SCRATCH/claude-cfg` (mode 0700):
     - copy the container's `~/.claude.json` into it;
     - if a credentials file exists, copy `~/.claude/.credentials.json`
       into it as `.credentials.json` (mode 0600).
   - Export `CLAUDE_CONFIG_DIR` to the scratch dir, both in your shell and
     in the test tmux session's global environment (`tmux set-environment
     -g`), **before** launching pm sessions. Both pm and Claude honour it.
   - Exception: container mode reads `$HOME/.claude.json` regardless (bug
     `pr-7e0eec4`). Scenario 2 handles that by using a scratch HOME, as
     described there.
   - Back up whatever file you modify before editing it.
3. **Do not leak credentials into evidence.**
   - Never copy `.credentials.json`, `oauthAccount`, API keys, env dumps, or
     raw pm launch logs into captures. Launch commands can carry tokens or
     env.
   - When you show `.claude.json` contents, filter them with jq to the
     `projects` entries under test, e.g.
     `jq '.projects | with_entries(select(.key|test("workdirs|trust-test")))'`.
   - Redact before saving. Inspect pm logs locally and quote only the
     relevant line, e.g. `workspace trust: … not approved`.
4. **Create the throwaway project** with `pm init --backend local
   --no-import` and a few small PRs (tui-manual-test.md). Start the
   session with `pm session`.
5. **Shorten the grace:** `pm set trust-prompt-grace-seconds 30`. Confirm
   `pm set list` shows it. This is the planner-made fix, so record whether it
   worked.
6. **Stuck-dialog stand-in.** Some failure paths need a dialog that never
   goes away. A real dialog for an approved dir would be auto-accepted, so
   real Claude cannot produce this.
   - Write an executable named `claude` in a scratch bin dir. It must:
     - print the verbatim dialog for its cwd (copy `TRUST_SCREEN` from
       `tests/test_workspace_trust.py`, `❯` on "No, exit");
     - read raw keys and append each one (as named text, e.g. `DOWN`,
       `ENTER`, `UP`) to a log file;
     - redraw the cursor on Up/Down;
     - never leave the dialog.
   - Prepend the bin dir to PATH in the test tmux session's environment only
     while a step says to use it, and remove it afterwards.
   - A session type with no fake-claude entry (and no `_all`) runs whatever
     `claude` is on PATH, so you can mix fake-claude with the stand-in or
     with real Claude per session type.
7. **Real Claude** (`claude` 2.1.296+ on PATH) for the positive paths.
   - Keep real-Claude prompts small (one tiny PR, `pm set qa-max-scenarios
     1`) to bound API cost.
   - Prove "no dialog" by capturing the pane continuously (pipe-pane / the
     tmux recipe) from launch until the first real output. A single late
     snapshot is not enough.

## Host trust policy and configuration

Scenario 1 covers host policy, config writes, the CLI, locks and bounded
refusal. All of it runs on the host path, with no pm containers.

### H1. The original bug reproduces pre-fix and is fixed post-fix

1. Run the reproduction tests from the diff with the PR install's Python:
   - `pytest -q tests/test_workspace_trust.py`, in full;
   - name in the report
     `TestLaunchBoundary::test_host_launch_bootstraps_fresh_checkout`,
     `test_qa_planner_blocked_fails_fast_without_finalizer`,
     `test_zero_scenarios_skip_finalizer` and
     `test_grace_setting_is_configurable_via_pm_set`.
   - All must pass.
   - Then check out `master` (or `git stash` the relevant files) and show
     that the #229 reproduction tests fail or are absent there. Restore
     afterwards.
2. **Pre-fix evidence (interactive).**
   - Given: a fresh git checkout under `~/.pm/workdirs/trust-test-<rand>/repo`
     with no entry in the isolated config.
   - When: in a tmux pane there, run
     `claude --dangerously-skip-permissions`.
   - Then:
     - the dialog for that path is shown, which proves the bypass flag
       does not establish trust;
     - nothing proceeds without keys.
   - Record the pane and exit it with Esc.
3. **Post-fix.**
   - Given: another fresh checkout under `~/.pm/workdirs`, also with no
     entry.
   - When: the user launches it through pm, e.g. starting a PR in the
     TUI, so the launch goes through `build_claude_shell_cmd`.
   - Then:
     - the isolated config gains `hasTrustDialogAccepted: true` for that
       checkout before Claude starts;
     - the interactive Claude pane goes straight to work with no dialog
       and no manual keys;
     - the launch does not add `--dangerously-skip-permissions` unless
       skip-permissions is enabled for the session.

### H2. Unapproved workspaces stay explicit

1. **Given** a git project outside `~/.pm/workdirs`, e.g. the throwaway
   project's own root under `/tmp`, that has not been authorized.
2. Check `pm trust status <proj>`:
   - it prints `approved: no` and `trusted:  no`;
   - it prints `Authorize with: pm trust add <proj>`.
3. **When** pm launches an interactive Claude session whose cwd is that
   project root (any TUI-launched session that runs in the project root,
   e.g. plan/guide/assist):
   - **Then** the dialog appears for that path;
   - pm sends no keys;
   - the isolated config gains no entry for it;
   - pm's log has `workspace trust: <path> not approved` (quote that line
     only).
4. `pm trust status` in a `~/.pm/workdirs/...` dir prints `approved: yes`.

### H3. `pm trust` CLI

1. `pm trust add <proj>`:
   - prints `Authorized <proj> (trusted)`;
   - `pm trust status` now shows yes/yes;
   - `pm trust list` shows the workdirs root plus `<proj> (authorized)`;
   - relaunching the H2 session shows no dialog.
2. `pm trust add` the same path again prints `(already)`, with no
   duplicate in `list`.
3. **Boundaries:**
   - a subdirectory of `<proj>` is approved;
   - the parent of `<proj>` is not;
   - a prefix-sibling `<proj>2` is not;
   - a symlink pointing at `<proj>` is approved.
4. **Refusals, each with a clear message and nothing written:**
   - `pm trust add ~`, `/`, `/home` (and `$HOME/..`) are refused with
     "refusing to authorize …"; no new authorized root, no config entry;
   - a nonexistent path is rejected with a click usage error.
5. `pm trust remove <proj>`:
   - prints `Removed <proj>` and disappears from `list`;
   - `status` shows `approved: no`;
   - Claude's own entry is still present, as documented.
   - Removing it again fails with "is not an authorized root".
6. **Edge cases:**
   - `CLAUDE_CONFIG_DIR` pointing at a not-yet-existing dir: `pm trust add`
     creates it and writes the config.
   - An unparseable config (write `{broken` into a scratch config): `pm
     trust add` fails with an actionable "could not read …" message and the
     file is left byte-identical. Restore the config afterwards.
   - `pm help` / `pm --help` lists the `pm trust` commands.

### H4. Config integrity and locks (shared resources)

1. **Given** the isolated config already holds unrelated keys and project
   entries with other fields, e.g. `allowedTools`, `numStartups`, an
   existing project with `lastCost`, at mode 0600.
2. **When** pm bootstraps a new workdir, **then**:
   - only that key is added;
   - every other key is preserved, verified with a jq diff;
   - the mode stays 0600;
   - no `.claude.json.lock` dir and no `.claude.json.pm-*` temp file is
     left behind.
3. **Stale lock:** create `<config>.lock` as a directory and backdate it by
   more than 10s (`touch -d '-1 min'`). Then:
   - the next pm launch, or `pm trust add`, removes it and succeeds;
   - the log shows "removing stale lock".
4. **Held lock:** keep `<config>.lock` fresh (touch it every second) for
   about 25s while starting a PR session with real Claude. Then:
   - the launch is not hung forever: bootstrap gives up after about 15s
     and logs a could-not-lock warning;
   - once the lock is released, the dialog that appears for the approved
     PR workdir is accepted by pm with cursor keys (Down, Enter);
   - the session proceeds with no manual keys.
   - Record the timeline.

### H5. Concurrent use (two or more actors on the shared files)

1. **Config writers.** At the same time:
   - (a) 4 PR sessions are started at once from separate shells/panes, with
     the stand-in `claude` on PATH (bootstrap still runs; it is not the
     fake);
   - (b) a real interactive `claude` session runs in another
     `~/.pm/workdirs` checkout (Claude writes the config too);
   - (c) two shells each run a loop of `pm trust add` over 5 distinct
     scratch project dirs.
2. **Then:**
   - the config is valid JSON;
   - every started workdir and every added dir has
     `hasTrustDialogAccepted: true`;
   - the unrelated keys from H4 survive;
   - no lock or temp leftovers remain.
3. **Authorization list.** After (c), `pm trust list` must contain **all 10**
   authorized dirs.
   - `~/.pm/settings/trusted-workspaces` is a plain read-modify-write with
     no lock, so lost updates are a **suspected bug**.
   - If any are missing, reproduce it at least twice. Then either fix it
     through the normal flow (commit on this PR with a regression test,
     flagged for review) or file it with `pm pr add … --plan bugs` and
     reference the PR id.
   - Do not leave it untracked.

### H6. Bounded, actionable refusal on the host

Uses the stand-in and `trust-prompt-grace-seconds` 30.

1. **Planner blocked.**
   - Given: fake-claude configured only for `qa_concretize`,
     `qa_verification` and `qa_finalize` (no `qa_planning` entry and no
     `_all`), and the stand-in `claude` on PATH.
   - When: the user starts QA on a PR from the TUI.
   - Then:
     - within about grace + 15s, QA ends `INPUT_REQUIRED`;
     - the TUI/QA status shows the error text: "QA planning did not start",
       the path, `pm trust add <path>`, and "not QA coverage";
     - no scenario windows and **no finalizer** window are launched;
     - the planner pane stays open showing the dialog;
     - the stand-in key log shows at most 2 accept attempts, each Down then
       Enter, and never an Enter sent while the cursor was on "No, exit".
   - Compare the wall-clock time with the pre-fix behaviour of a 1-hour
     wait, quoted from impl.md.
2. **TUI "needs you".**
   - Given: the stand-in on PATH.
   - When: the user starts an implementation session for a PR from the
     TUI.
   - Then: the impl pane is shown in the TUI's "needs you" /
     waiting-for-input state while the dialog is visible. It is not shown
     as plain busy.
   - Remove the stand-in, restart the session with real Claude, and the
     state clears.
3. **Review loop blocked.** With the stand-in for `review`, a review loop
   ends in ERROR with the trust message (path plus remedy) instead of
   polling forever.

## Workflow and container trust

Scenario 2 covers every workflow role, reused workdirs, restart, the
fallback, the zero-scenario path and containers.

### W1. Full QA on a fresh checkout with real Claude (acceptance; the #229 path)

1. **Given:**
   - a tiny PR whose workdir is freshly created by pm;
   - **no** trust entries for it, its QA dir, or any scenario clone in the
     isolated config;
   - `pm set qa-max-scenarios 1`;
   - no fake-claude config.
2. **When** the user starts QA from the TUI.
3. **Then:**
   - the planner pane never shows the dialog (continuous capture);
   - a real plan with at least 1 scenario is parsed;
   - a scenario worker runs in a new clone (`qa/<pr>-<loop>/s-1/repo`),
     visibly does work, and reaches a verdict;
   - verification runs (VERIFIED or a reasoned outcome);
   - the finalizer runs and reaches FINALIZE_DONE;
   - the config gains entries for the PR workdir and the scenario clone.
4. Window creation or registry status alone does **not** count. Show
   plan text, worker activity and verdicts.

### W2. Every role starts without the dialog

Use real Claude. Each role must launch in its approved workdir and start with
no dialog and no manual keys. Capture each pane from launch, then stop it
after it starts working, to bound cost:

- implementation (`pm pr start` / TUI);
- review loop;
- QA planner, concretizer, scenario worker, verifier and finalizer (from W1);
- sign-off (or the sign-off launch path as the TUI drives it);
- merge resolution: create a merge conflict on a PR branch, then trigger
  merge so pm launches the resolution Claude session;
- `pm meta` (meta workdir under `~/.pm/workdirs`).

For the review pane, **assert the pane's current directory is the PR
workdir**, not the TUI's project dir (`tmux display -p
'#{pane_current_path}'`). The pane command starts with `cd <workdir> &&`.
This was the live R9 finding.

### W3. Reused untrusted workdirs, restart and handoff

1. **Given** a PR that already has a workdir from an earlier start. Delete
   its trust entry from the isolated config to simulate a pre-fix workdir.
2. **Review restart:**
   - When: the user re-runs the review loop.
   - Then: the entry is re-written, there is no dialog, and the review
     reaches a verdict.
3. **Resume:**
   - When: the user kills the impl window and starts the PR again, which
     resumes the earlier session.
   - Then: the resumed Claude session shows no dialog and continues the
     earlier conversation.
4. **Interrupted QA:**
   - When: QA is stopped mid-run (quit and restart the TUI / `pm session`)
     and QA is started again.
   - Then: the restarted run re-bootstraps any new clones, never sits at
     the dialog, and produces its own nonempty plan and worker activity.
5. **Adopted review:**
   - If a review pane was left in flight across a TUI restart, the adopted
     review continues.
   - If it is sitting at the dialog for its approved workdir, pm accepts
     it with cursor keys.

### W4. Explicit fallback for a visible dialog (approved workdir)

1. **Given** a session whose bootstrap could not take effect: start a
   review or impl with real Claude while bootstrap is defeated, e.g. by
   holding a fresh lock as in H4.4.
2. **Then:**
   - the dialog is visible briefly;
   - pm selects "Yes, I trust this folder" with Up/Down + Enter, using at
     most 2 attempts;
   - the session proceeds;
   - the pm log shows "accepting prompt … for approved workdir".
3. **Dialog-like text later in a session** must not trigger keys or a
   false block:
   - Start a real review or worker session and, in its first turn, have it
     print the verbatim `TRUST_SCREEN` text, e.g. ask it to `cat` this
     module's test fixture.
   - The session is not interrupted and no keys are sent. Check the
     stand-in-free pane log and the pm log.

### W5. Zero-scenario and blocked-scenario behaviour

1. **Zero scenarios:**
   - Given: fake-claude `qa_planning` emits `QA_PLAN` with a body that has
     no `SCENARIO` blocks.
   - When: the user starts QA.
   - Then:
     - QA ends without launching **any** finalizer window;
     - the pm log has "QA finalize: skipped … no scenarios ran";
     - the outcome is not presented as QA coverage.
2. **Trust-blocked worker:**
   - Given: fake-claude for `qa_planning` (2 scenarios), `qa_concretize`,
     `qa_verification` and `qa_finalize`, with **no** `qa_scenario` entry,
     and the stand-in `claude` on PATH.
   - When: the user starts QA.
   - Then:
     - within about grace + 15s, both scenarios are `INPUT_REQUIRED` with
       reason "blocked at workspace-trust prompt: …" (path plus `pm trust
       add`);
     - the run completes; it does not wait for the 1h timeout;
     - queued scenarios still launch.
3. **Trust-blocked concretizer:** variant with the stand-in for
   `qa_concretize` instead. The scenario reason starts with "blocked at
   workspace-trust prompt", not "refiner rejected".

### W6. Container sessions (nested podman)

1. **Isolation for containers.** Container mode copies `$HOME/.claude.json`
   and ignores `CLAUDE_CONFIG_DIR` (bug `pr-7e0eec4`).
   - Run the container part with a scratch `HOME`, e.g. a throwaway user
     home inside the scenario container, holding a copied `.claude.json`
     and credentials.
   - Alternatively, confirm the scenario container's `~/.claude.json` is
     itself a disposable copy, and back it up first.
   - Never touch the outer host file.
   - Record which approach you used, and whether you observed `pr-7e0eec4`.
2. **Given:**
   - `project: nested_podman: true` in the test project.yaml (bootstrap
     exception per tui-manual-test.md);
   - `pm container enable`;
   - a fresh PR.
3. **When** the user starts the PR's review (or impl) so pm creates a new
   container.
4. **Then:**
   - inside the container, `~/.claude.json` has `projects["/workspace"]`
     trusted;
   - the host-side config (the one in use) has **no** `/workspace` entry;
   - the container Claude pane starts with no dialog and reaches work or a
     verdict;
   - the launch command uses `-w /workspace` and has no host `cd` prefix.
5. **Reused container:** relaunch the same role in the running container.
   There is no dialog and no new seeding is needed.
6. **Pre-fix container simulation:**
   - Strip `projects["/workspace"]` from the running container's
     `.claude.json` with podman exec + jq, then relaunch a review loop.
   - The dialog shows `/workspace` and pm auto-accepts it via cursor keys,
     because the launch workdir is approved and `/workspace` is not a host
     dir.
   - The pm-on-a-host-`/workspace` limitation is tracked in `pr-8c0d680`.
     Note if it applies to your environment.
7. **Container QA:**
   - Run W1's QA with container mode on and `qa-max-scenarios 1`.
   - The scenario container worker starts with no dialog and reaches a
     verdict.
   - If cost or time forces truncation, record exactly what ran.

## Pass / fail

**Pass:** every Then above is observed on a user surface and captured. The
surfaces are:

- pane recordings;
- CLI output;
- TUI/QA status;
- filtered config contents.

**Fail:** any one of these:

- an automated pm session in an approved dir sits at the dialog, or needs
  manual keys;
- pm writes trust for, or auto-accepts, an unapproved dir;
- a blind Enter is sent while the cursor is on "No, exit";
- a blocked session waits longer than grace + about 15s without an
  actionable message;
- a finalizer is launched after a trust-blocked or zero-scenario plan;
- the config is corrupted, loses keys or mode, or leaves lock or temp files
  behind;
- an authorization is lost under concurrency and goes untracked;
- evidence contains credentials.

**Report requirements:**

- Every bug found must be reported with a fix commit, a tracking PR id, or
  an UNRESOLVED verdict.
- Each scenario report must repeat the Run disclosures:
  - the run was supervised;
  - the planner app edit `7d79fce1` is unreviewed and must be reviewed
    again before sign-off.

## Ambiguities (resolved)

1. **Real vs fake Claude.** The dialog exists only in real interactive
   Claude, and fake-claude skips bootstrap. So:
   - positive paths use real Claude;
   - stuck-dialog failure paths use the stand-in, because a real dialog for
     an approved dir is auto-accepted.
2. **The project's own base checkout** is not auto-approved (impl
   decision). It serves as the natural unapproved dir.
3. **Isolation.** `CLAUDE_CONFIG_DIR` for host paths, and a scratch HOME for
   container paths (because of `pr-7e0eec4`).
4. **Watcher-framework subsumption** (pr-3032fb6) is not relied on.
