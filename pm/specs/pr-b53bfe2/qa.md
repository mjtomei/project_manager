# QA spec: pr-b53bfe2, Resolve workspace trust across all automated workflow sessions

This spec is grounded in `git diff master...HEAD`:

- `pm_core/workspace_trust.py`
- `claude_launcher.py`: `prepare_workspace`, `WorkspacePromptWatch`, and the
  `cd <cwd> &&` launch prefix
- `container.py`: config seeding
- Trust watches in `loop_shared`, `qa_loop`, `review_loop` and `pane_idle`
- `cli/trust.py`
- `cli/pr.py`: review split cwd; local-backend merge sync/propagation
  (R10, `_sync_workdir_base`, `_propagate_to_repo`, `_launch_merge_window`)
- `cli/meta.py`: meta cwd
- `cli/__init__.py`: `trust-prompt-grace-seconds` setting
- `pm/specs/pr-b53bfe2/impl.md`

The current QA round (after review 356c i3) has exactly three scenarios.
Each one executes one of the named sections below **in full**, together with
the shared **Setup**. The planner output only names the section; the
concretizer and worker must read the whole section here, every H/W/M story:

- **SCENARIO 3: Host trust policy and configuration** → section
  "Host trust policy and configuration" (H1–H6)
- **SCENARIO 4: Workflow and container trust** → section
  "Workflow and container trust" (W1–W6)
- **SCENARIO 5: Local merge trust** → section "Local merge trust" (M1–M5)

The runner must launch exactly as many scenarios as were planned (3).
A planned/launched mismatch is itself a FAIL to report.

Earlier rounds: run #230 ran Scenarios 1 and 2 against older code. S1
found and fixed bugs, so its result is not a PASS for the current head; S2
ended INPUT_REQUIRED. **No earlier coverage counts as PASS for this round.**

## Run disclosures (read first)

- **Supervised run.** This round is supervised validation. The outer host
  still lacks #231 and the supervisor may accept outer planner/QA trust
  prompts on verified pm checkout paths. It is **not** an unattended
  autostart qualification trial. Do not report it as one, and state in
  every report whether any outer trust prompt was accepted manually.
- **App edits so far and their review state.** The run #230 planner and
  QA edits (`7d79fce1` grace setting, `f650a308` locked `pm trust`
  add/remove with rollback, `8cd40e87` blocked-planner status pane,
  `37ad95eb` QA log markup, `3130d141`/`0c84b817` per-pane accept budget,
  `c056b32a` concretizer reason) were reviewed in review 356c i1. The local
  merge change (`bca1d21a`, `d1b791f9`) was reviewed in 356c i3
  (`3c7df387`). These are reviewed, but **this QA round is their first live
  test**, so Scenarios 3–5 must exercise each of them.
- **Any app edit made in this round is unreviewed.** Commit it with a
  fail-before/pass-after regression test, name the commit in the report, and
  state that it needs another review pass before fresh sign-off. An all-PASS
  QA run does **not** review it. The planner itself makes no app edits.
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

## Setup (all scenarios)

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

Scenario 3 covers host policy, config writes, the CLI, locks and bounded
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

Scenario 4 covers every workflow role, reused workdirs, restart, the
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
- merge resolution is covered separately in Scenario 5 ("Local merge
  trust"); W2 does not repeat it;
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
7. **Container QA (actual worker activity is required).** Run #230 never
   launched a container worker: hook events could not reach pm from the
   nested container, so QA had no session id to poll. Before the QA run,
   make the hook path work the supported way:
   - run pm itself (`pm session`) with the same `HOME` whose `.claude.json`
     the container copies (the scratch HOME from step 1), so pm's hook
     installer writes `$HOME/.pm/hook_receiver.py` and the hooks in
     `$HOME/.claude/settings.json`, and `create_container` bind-mounts that
     `$HOME/.pm/hooks` into the container;
   - smoke-test it: start a container review for the PR and confirm a hook
     event file for its session appears under `$HOME/.pm/hooks` on the host
     side after the first turn. Record the listing.
   Then run W1's QA with container mode on and `qa-max-scenarios 1`:
   - the scenario container worker starts with no dialog, visibly works and
     reaches a verdict; verification and the finalizer run.
   - If hook events still never arrive, do not call it PASS. File a bug
     (`pm pr add … --plan bugs`, with the exact mount/receiver evidence),
     mark container QA worker coverage **UNRESOLVED / missing**, and still
     show container worker activity through the W6.4 review reaching a
     verdict.
   - If cost or time forces truncation, record exactly what ran.

## Local merge trust

Scenario 5 covers merge resolution, a role named in acceptance. It runs on
the host path with the **local** backend (`pm init --backend local`), real
Claude for the resolution window, and the isolated config from Setup. Seed
uncommitted user work in the main repo (e.g. an untracked `notes.txt` and a
modified tracked file) before M1 and check it is untouched after every story.
Reference run: impl captures `post-fix/local-merge-*`.
First run `pytest -q tests/test_local_merge_sync.py` with the PR install's
Python (real git; all must pass) and record the output.

### M1. Independent PRs merge with no window (pr-a75da60)

- Given two PRs that touch different files, both with workdirs.
- When the user merges the first, then the second, from the TUI.
- Then both merges reach `merged` with no `merge-<pr>` window, the main
  repo's base contains both commits, and the project root gains no trust
  entry in the isolated config.

### M2. A real conflict is resolved in the PR workdir (pr-e835d8f)

- Given two PRs that edit the same lines; the first is merged.
- When the user merges the second from the TUI.
- Then:
  - a `merge-<pr>` window opens and its `#{pane_current_path}` is the
    **PR workdir**, not the project root (record it);
  - the pane shows no trust dialog (continuous capture from launch) and no
    manual keys are sent;
  - the PR workdir has `hasTrustDialogAccepted: true`; the project root has
    no entry;
  - after Claude resolves and reports MERGED, the TUI's follow-up
    (`pm pr merge --propagation-only`) fast-forwards the main repo with no
    second window, and the PR shows `merged`.

### M3. The main repo's base moves during the merge

- Given a PR whose workdir merge has finished but not propagated (e.g.
  answer the M2 window slowly, or stop after the workdir merge), and a new
  commit is then made on the main repo's base.
- When propagation runs.
- Then the new commit is integrated in the PR workdir and the fast-forward
  retried. A non-conflicting commit propagates with no window; a
  conflicting one opens the window in the PR workdir again. The main repo
  is never reset and keeps both histories.

### M4. A main-repo-side failure exits without a window

- Given a main-repo state that blocks the fast-forward, e.g. a
  `.git/index.lock` in the main repo, or uncommitted changes that conflict
  with the incoming files.
- When the user merges a PR.
- Then `pm pr merge` exits non-zero with a message that names
  `pm pr merge --propagation-only <pr>`; no Claude window opens in the
  project root; nothing in the main repo is reset or lost. After the
  blocker is cleared, the printed command completes the merge.
- Note in the report whether the TUI leaves the PR pending until the user
  runs the command (known benign behaviour from review i3).

### M5. Unapproved merge window stays explicit

- Given the vanilla/GitHub-style pull-from-origin path, which still opens
  in the project root (out of scope, pr-19990de), or any merge window in an
  unapproved dir.
- Then pm prints the `pm trust add <dir>` remedy when the window opens,
  sends no keys to the dialog and writes no trust for the root. If this
  path cannot be driven without a GitHub remote, say so and cite
  pr-19990de; do not mark it PASS.

### Concurrency

While M2's window is open, start a review loop on a third PR and run
`pm trust add` on a scratch dir from another shell. The config stays valid
JSON with all three trust entries and no lock or temp leftovers.

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
- a merge resolution window opens in the project root for a local-backend
  merge, or uncommitted main-repo work is lost;
- a container scenario is reported PASS without a container worker actually
  working;
- the number of launched scenarios differs from the planned number;
- evidence contains credentials.

**Report requirements:**

- Every bug found must be reported with a fix commit, a tracking PR id, or
  an UNRESOLVED verdict.
- Each scenario report must repeat the Run disclosures:
  - the run was supervised, and whether any outer trust prompt was
    accepted manually;
  - any app edit made in this round is unreviewed and needs another review
    pass before fresh sign-off.

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
5. **Merge resolution (pr-e835d8f).** Supervisor chose option (a): local
   merges resolve in the PR workdir (R10). The project root is still never
   auto-trusted. The vanilla/GitHub pull-from-origin window is out of scope
   (pr-19990de).
6. **Container worker hooks.** The supported route is running pm under the
   same HOME the container copies, so the hook receiver and hooks dir are
   the ones mounted (W6.7). A failure there is filed, not waived.
