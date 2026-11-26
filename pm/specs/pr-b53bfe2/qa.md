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
- `tui/review_loop_ui.py` + `claude_launcher.pane_transcript_path` +
  `tmux.pane_start_command`: the orphan trust watch for Claude panes the
  TUI's idle tracker cannot register (`5a293bf1`, revised in review 80f0
  i1/i2, `af1a3fd4` and `ac7522e0`; duplicate-report guard `211cfb95`,
  reviewed in review 1317 i1)
- `cli/guide.py`: the TUI guide/assist pane (`pm guide` in a pm tmux pane)
  calls `prepare_workspace(os.getcwd())` for real Claude only (`911e75b7`,
  fake-guide skip `24796646`, reviewed in review 5a14 i1)
- `qa_loop.parse_qa_plan`: the plan body never starts before the last
  `QA_PLAN_START` ahead of the final `QA_PLAN_END` (`4c3fb81c`, reviewed
  in review 5a14 i1)
- `pm/specs/pr-b53bfe2/impl.md`

The current QA round (round 7, supervisor recovery 2026-10-14) has
exactly **one** scenario. It executes the section below **in full**,
together with the shared **Setup**, **Harness notes** and the new
**Process hygiene (round 7, do this first)** note. The planner output only
names the section; the concretizer and worker must read the whole section
here, every W story:

- **SCENARIO 15: Workflow and container trust** → section
  "Workflow and container trust" (W1–W6)

The other two groups are **not** rerun this round. Round 6 S12 (host trust
H1–H7) and S14 (local merge M1–M5) are PASS and independently VERIFIED on
app code `17d4f39a`. The head since then differs only in `pm/project.yaml`
and this spec (no app code), so those verified results carry forward as the
host and local-merge coverage for this head. Rerun them only if app code
changes.

Scenario numbers map to sections as follows: host = 12/9/6/3, workflow/
container = 15/13/10/7/4, local merge = 14/11/8/5. In the section texts
below, "Scenario 6/7/8" means the host/workflow/merge scenario of the
current round (this round: only the workflow/container one, 15).

The runner must launch exactly as many scenarios as were planned (1).
A planned/launched mismatch is itself a FAIL to report.

### Earlier rounds

- Run #230 round 1–2 (Scenarios 1 and 2) ran against older code: S1 found
  and fixed bugs, S2 ended INPUT_REQUIRED.
- Round 3 on `6f64e2c7` (run `pr-b53bfe2-6a3fbfb2c02d32ea`):
  - S3 host trust: **PASS** (H1–H6 live; filed `pr-d72df02`).
  - S4 workflow/container: **NEEDS_WORK**. Every W Then held, including
    real container QA worker activity (W6.7), except W3.5: a review pane
    left at the trust dialog after a hard TUI kill was never watched again.
    Fixed in `5a293bf1` (orphan trust watch), then revised in review 80f0
    (`af1a3fd4`, `ac7522e0`). Filed `pr-5d66709`, `pr-1710f9a`,
    `pr-f2f9ef8`, `pr-1e9c117`, `pr-dc4dd45`. Harness incident: see
    Harness notes, captures.
  - S5 local merge: **INPUT_REQUIRED**. All trust Thens held; the M2 "TUI
    follow-up" and the M5 sequence did not match this spec because of two
    pre-existing, out-of-scope merge bugs (`pr-c50d365`, `pr-ea04ba8`).
    Resolved in Ambiguity 7: the spec was wrong, M2 and M5 are corrected
    below, and both bugs stay tracked.
- Round 4 on `5e372554` (run `pr-b53bfe2-2cc2adbed8e7c053`):
  - S6 host trust: **NEEDS_WORK** only because it made an app fix. Every
    H Then held, including the first live test of the orphan watch. Live
    bug fixed in `211cfb95`: after a review loop ended in the trust ERROR,
    the orphan watch re-posted the same red line about 35s later. Now
    reviewed (review 1317 i1). Filed `pr-c9e69fb`: shell `pm pr start`
    panes have no `--session-id` and are never trust-watched, so the
    round-4 H7.1 text and the "Shell launches" note were wrong (corrected
    below).
  - S7 workflow/container: **INPUT_REQUIRED**. Every trust Then W1–W6 held
    live, including real container QA workers (W6.7) and the W3.5
    hard-kill orphan watch. Only W3.3 "resume" failed, on pre-existing
    `pr-9f97a8f` (TUI `s` never resumes). That also makes `pr-d76385d`
    unreachable. Filed `pr-f8acf21`. Resolved in Ambiguity 10: W3.3 is
    corrected below.
  - S8 local merge: **INPUT_REQUIRED**. Every trust Then held. Two M2a/M3
    Thens did not match as written: an "Updating master in the PR workdir
    … CONFLICT" line the concretizer expected in M2a cannot appear there,
    and real Claude asked for input on genuinely ambiguous same-line
    conflicts. Resolved in Ambiguity 9: both were spec errors, and M2–M4
    are corrected below.
- Round 5 on `c86e1caf` (run `pr-b53bfe2-90290adcb8ef20bf`):
  - S9 host trust: **NEEDS_WORK** only because it made an app fix. Every
    H Then held, including the first post-review live test of `211cfb95`
    (H7.6) and H5 10/10. Gap fixed in `911e75b7`: the TUI guide/assist
    pane (`H`, `pm guide` in a pm tmux pane) never called
    `prepare_workspace`, so an unapproved project root logged no "not
    approved" line and approved dirs got no bootstrap. Review 5a14 i1
    reviewed it and made it skip a fake guide (`24796646`). Filed
    `pr-629c47e` (the other TUI interactive panes: `c`, discuss, watcher
    review, QA author have the same gap).
  - S10 workflow/container: **NEEDS_WORK** only because it made an app
    fix. Every trust Then held live, including real container workers
    (W6.7), the W3.5 orphan accept and the container hard-kill variant of
    `211cfb95`. W3.3 terminal resume continued the earlier conversation.
    Fixed in `4c3fb81c`: W3.4's planner plan was numbered from 2, and the
    terminal plan parse reached back to a committed qa.md SCENARIO line
    echoed in the prompt (planned 1, launched 2). Reviewed in review
    5a14 i1. `pr-f8acf21` reproduced; W3.6 terminal resume with bootstrap
    defeated sits silently at "No, exit" (`pr-d76385d`).
  - S11 local merge: **PASS**. M1–M5 incl. M2a/M2b/M2c, M4b and
    concurrency held live. Merge intent was carried in the PR **title**
    (the merge prompt does not include the PR description; M2 corrected
    below).
- The head changed after round 5 (`911e75b7`, `4c3fb81c`, `24796646`).
  `4c3fb81c` touches the QA plan parse used by every QA run, and
  `911e75b7` changes what the TUI guide pane does at launch. So round 6
  reran all three sections on `17d4f39a`.
- Round 6 on `17d4f39a` (run `pr-b53bfe2-9aa25d894ed5e3ca`):
  - S12 host trust: **PASS**, independently VERIFIED. Every H Then held,
    including the first post-review live tests of `911e75b7`/`24796646`
    (H2.5 guide pane, real and fake) and `211cfb95` (H7.6). Carried
    forward as host coverage (see above).
  - S14 local merge: **PASS**, independently VERIFIED. M1–M5 incl.
    M2a/M2b/M2c, M4b and concurrency. Carried forward as local-merge
    coverage.
  - S13 workflow/container: **no verdict, no coverage.** The worker died
    and all 10 relaunches failed because the scenario container's PID 1
    (`sleep infinity`) never reaped orphaned children of the harness's own
    polling scripts: 1951 zombies (mostly `w35c.sh`, `w35.sh`, which used
    repeated shell process substitution) hit the 2048 PID cap
    (`pids.events max=134`, `oom_kill=0`). Filed `pr-2111fa0`; evidence
    `shepherd-20261014/s13-exhaustion.json`, `s13-process-table.txt`.
    Its partial recordings under `scenarios/13` are **not** fresh coverage
    and must not be cited as passing evidence. `4c3fb81c` (W1.5/W3.4
    planned = launched) therefore still has no post-review live test in
    the workflow path; S15 provides it.

## Run disclosures (read first)

- **Supervised run.** This round is supervised validation. The outer host
  still lacks #231 and `pr-b8561ac`, and the supervisor may accept outer
  planner/QA trust prompts on verified pm checkout paths. It is **not** an
  unattended autostart qualification trial. Do not report it as one, and
  state in every report whether any outer trust prompt was accepted
  manually.
- **App edits so far and their review state.** The run #230 planner and
  QA edits (`7d79fce1` grace setting, `f650a308` locked `pm trust`
  add/remove with rollback, `8cd40e87` blocked-planner status pane,
  `37ad95eb` QA log markup, `3130d141`/`0c84b817` per-pane accept budget,
  `c056b32a` concretizer reason) were reviewed in review 356c i1 and passed
  live in round 3. The local merge change (`bca1d21a`, `d1b791f9`) was
  reviewed in 356c i3 (`3c7df387`) and its trust Thens passed live in
  round 3. The round-3 QA fix `5a293bf1` (orphan trust watch) was reviewed
  and revised in review 80f0 i1/i2 (`af1a3fd4`, `ac7522e0`), and passed
  live in round 4. The round-4 QA fix `211cfb95` (orphan watch does not
  re-report a pane this TUI already reported) was reviewed in review
  1317 i1 and passed live in round 5 (H7.6 and the W3.5 container
  variant). The round-5 QA fixes `911e75b7` (guide/assist pane bootstrap)
  and `4c3fb81c` (plan parse never starts before the last
  `QA_PLAN_START`) were reviewed in review 5a14 i1, which also made the
  guide skip bootstrap under a fake guide (`24796646`). Round 6 S12
  live-tested the guide pane after review (H2.5 PASS, VERIFIED). **This
  round is the first post-review live test of `4c3fb81c` in the workflow
  path**: W1.5 and W3.4 must show planned = launched.
- **Any app edit made in this round is unreviewed.** Commit it with a
  fail-before/pass-after regression test, name the commit in the report, and
  state that it needs another review pass before fresh sign-off. An all-PASS
  QA run does **not** review it. The planner itself makes no app edits.
- **Every known remaining bug** must end with one of: a fix (commit), a
  tracking PR, or an explicit UNRESOLVED verdict. A bug being nonblocking
  never excuses leaving it untracked. Before filing, check this list and
  `pm pr list --plan bugs` for duplicates. Already tracked:
  - `pr-7e0eec4`: the container copies `$HOME/.claude.json` and ignores
    `CLAUDE_CONFIG_DIR`.
  - `pr-8c0d680`: the known `/workspace` host-dir limit.
  - `pr-b8561ac`: the old host terminal-intake planner bug, where terminal
    capture truncates a complete plan.
  - `pr-d72df02`: a killed impl pane keeps the cyan busy spinner.
  - `pr-5d66709`: an in-flight review loop is not adopted after a hard TUI
    kill (only the trust-dialog part is fixed here).
  - `pr-1710f9a`: bootstrap takes the config lock even when already
    trusted.
  - `pr-f2f9ef8`: TUI start resets tmux hook arrays.
  - `pr-1e9c117`: `captures_dir()` uses the `/pm-captures` mount for any
    PR when `PM_CAPTURES_PR` is unset.
  - `pr-dc4dd45`: the blocked message says `pm trust add` for an already
    approved dir.
  - `pr-c50d365`: manual merges (TUI `g` / command bar) get no TUI MERGED
    follow-up (`--propagation-only` must be run by hand).
  - `pr-ea04ba8`: a vanilla merge always fails the dual-pushurl push to the
    checked-out main repo and opens a spurious window.
  - `pr-19990de`: vanilla/GitHub pull-from-origin resolution still runs in
    the project root.
  - `pr-9e37213`: the orphan trust watch caches a transient tmux
    start-command read failure as "no session" for the pane's lifetime
    (review 80f0 i3).
  - `pr-d76385d`: a resumed session's existing transcript ends every trust
    watch at once, so a dialog after a trust reset is never accepted or
    reported (review 80f0 i3; tracker, orphan and loop watches).
    Unreachable until `pr-9f97a8f` is fixed (round 4 S7).
  - `pr-9f97a8f`: TUI `s` on a PR whose impl window was closed starts a
    fresh session instead of resuming. Only the terminal fall-through
    path (`pm pr start` with no tmux) resumes.
  - `pr-c9e69fb`: shell `pm pr start` impl panes have no `--session-id`,
    so they are never trust-watched.
  - `pr-f8acf21`: stopping a QA run still launches queued workers and a
    finalizer, then records QA PASS with unrun scenarios. Watch for it in
    W3.4, and never count such a PASS as coverage.
  - `pr-2111fa0`: the scenario container's PID 1 (`sleep infinity`) does
    not reap orphaned children; harness pollers exhausted the PID cap in
    round 6 S13. Harness-side mitigation is in Harness notes ("Process
    hygiene").
  - `pr-629c47e`: the TUI `c`, discuss, watcher-review and QA-author panes
    run Claude in the project root without consulting workspace trust (no
    "not approved" log line, no bootstrap). Only the guide/assist pane is
    fixed here (`911e75b7`).

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
     `pr-7e0eec4`). Scenario 7 (W6) handles that by using a scratch
     HOME, as described there.
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

## Harness notes (learned in earlier rounds; read before driving)

- **Process hygiene (round 7, do this first).** Round 6 S13 died of PID
  exhaustion caused by the test harness, not by pm (`pr-2111fa0`: the
  scenario container's PID 1 does not reap orphans). Before driving any
  story:
  - Do not write pollers that spawn a background child or a shell process
    substitution (`<(...)`, `>(...)`, `cmd &` without `wait`) on every
    iteration. Prefer one bounded Python poller per wait
    (`subprocess.run` with a timeout, a deadline, `time.sleep`), or a
    shell loop that runs only foreground commands and `wait`s any child it
    starts. Every poll loop must have a deadline and end with a concrete
    finding (timeout → record what was observed), never loop forever.
  - Long-lived helpers (pipe-pane writers, key loggers, lock holders) are
    started once, their PIDs recorded, and killed and `wait`ed when the
    story ends.
  - Monitor the container's process budget: at start and after each W
    story record `ps -eo stat= | grep -c '^Z'` (zombies), the total
    process count, and `cat /sys/fs/cgroup/pids.current pids.max
    pids.events` (if present). If zombies grow by more than ~50 within a
    story, stop, find the leaking script, fix it, and note it in the
    report. If the budget gets near the cap, end the scenario with a
    concrete finding (counts, offending command names) instead of letting
    the worker be killed.
  - Include the start/end process and zombie counts in the report.
  - Do not reuse round 6's `w35.sh`/`w35c.sh` scripts or anything else
    under `scenarios/13`; write new ones under `scenarios/15`.

- **Round-5 lessons.**
  - `tmux pipe-pane -o` toggles: starting a second pipe on a pane (e.g. a
    hook plus a poller) closes the first. Use one pipe per pane and verify
    it is still open (`#{pane_pipe}`).
  - The scratch-HOME OAuth copy goes stale when the outer host rotates its
    token. If real Claude starts failing auth mid-run, re-copy
    `.credentials.json` (never into captures).
  - `pm container enable` is global. Disable it again when container
    stories are done.
  - While the stand-in `claude` symlink is swapped in, the Claude Code
    tool shell's `grep` (aliased to `claude -G`) and `pm trust` probes of
    `claude` hang. Use `/usr/bin/grep` and keep swap windows short.
  - A round-4 S8 `pipe-pane` was still appending to
    `scenarios/8/panes/pm-home.22.log` from outside during round 5. Growth
    of that one file is not a contamination by your scenario; name it in
    the report if your start/end listings differ only there.
  - Do not run `pm notes` (an editor) inside a pane you are capturing for
    a story; edit `pm/notes.txt` directly.

- **Evidence authenticity.** Round 3's `scenarios/1`–`3` `prompt.md`,
  `scenario.json` and `verdict.md` were overwritten by nested fixture
  metadata (moved to `scenarios/4/contamination`; originals lost). Do
  **not** cite those files, or anything under `contamination`, as
  evidence. Round-3 evidence that may be cited is limited to recordings
  and logs written by the scenario itself (e.g. `scenarios/4/W3-*`,
  `scenarios/5/*`, `impl/{pre,post}-fix/*`).
- **Capture isolation for this round.** Scenario 15 writes only under
  `scenarios/15/` and never deletes or rewrites another scenario's files
  or earlier rounds' files (including round 6's `scenarios/12`–`14`,
  which hold verified and preserved evidence). At the end, list your
  directory with sizes and mtimes in the report and confirm that
  `scenarios/1`–`14` were not modified during your run (compare a listing
  taken at start with one taken at the end).
- **Captures (round-3 incident).** Never unset `PM_CAPTURES_PR`. In round 3
  a nested throwaway QA run inside S4 wrote its own `prompt.md`,
  `scenario.json` and `verdict.md` into the real `/pm-captures` mount and
  overwrote other scenarios' evidence (bug `pr-1e9c117`). Keep
  `PM_CAPTURES_PR` set to this PR id in every shell and in the test tmux
  session's environment, and before the first nested QA run confirm that a
  throwaway PR's captures land under the throwaway session's own
  `~/.pm/sessions/<tag>/captures/<pr>` and not in `/pm-captures`. Only write
  into your own scenario's captures subdirectory.
- **git proxy.** Scenario containers have `~/.local/bin/git` as a push proxy
  that also forwards fetch/pull to the outer workdir. That breaks the
  local-path fetches the local merge uses (`_sync_workdir_base`,
  `_propagate_to_repo`, the merge prompt) and real-git tests. Put
  `/usr/bin` first on PATH (or move the proxy aside) for throwaway-project
  work, and restore it before pushing anything for this PR.
- **Login-shell PATH.** pm panes take the TUI process's PATH (login shells
  prepend `~/.local/bin`), not the tmux global env. To make the stand-in or
  fake-claude win, swap the `~/.local/bin/claude` symlink (back it up) or
  start the TUI with the right PATH.
- **Claude settings.** `tui=fullscreen` in Claude settings triggers the
  planner transcript bug `pr-b8561ac`; leave it out of the scratch config.
- **CLAUDE_CONFIG_DIR and pm.** pm reads transcripts from
  `~/.claude/projects` and hooks from `~/.claude/settings.json` regardless
  of `CLAUDE_CONFIG_DIR`. With a scratch `CLAUDE_CONFIG_DIR`, symlink
  `$CFG/projects -> ~/.claude/projects` and copy `~/.claude/settings.json`
  into `$CFG`, or use the scratch-HOME route (W6.1) for everything.
- **Scratch HOME (W6.1 route).** `/home/pm/.claude` in scenario containers is
  a bind mount of the outer host's `~/.claude`. For container work, run pm
  under a scratch HOME (copy `.claude.json`, `.credentials.json`,
  `settings.json` minus hooks/tui, `.profile`, `.gitconfig`; a
  `.local/bin` with only `claude` and fake-claude) with `CLAUDE_CONFIG_DIR`,
  `PM_HOST_HOME`, `ANTHROPIC_API_KEY` and `CLAUDECODE` unset. Round 3 got
  real container hook events and worker activity this way.
- **Containers.** Review containers are removed when their window dies, so
  container reuse is only reachable via the impl container or the QA
  concretizer→worker container. Host `/workspace` exists in this
  environment, so a dialog showing `/workspace` is never auto-accepted
  (`pr-8c0d680`).
- **QA with fake planners.** Fake-planner QA needs
  `pm/specs/<pr>/qa.md` committed in the throwaway PR workdir (spec gate).
  A plan with zero scenarios only ends when the planner pane exits;
  otherwise the 1h planner timeout applies. `qa-max-scenarios` is a
  concurrency cap, not a plan-size cap.
- **Sign-off route.** TUI `t` from `in_progress` never reaches `qa`; drive
  sign-off on a PR already in `qa` (round 3 used `d` then `t`).
- **Merges in throwaway projects.** TUI `g` is refused by the sign-off gate
  (no fresh SIGNOFF_MERGE), so the TUI route is the command bar
  `pr merge --resolve-window --no-signoff-check <pr>`. That route has no
  MERGED follow-up (`pr-c50d365`); only auto-start merges get one.
- **`pm meta`** sets the session override to a GitHub-master clone and
  removes `~/.pm/sessions/<tag>` on exit, which wipes a fake-claude config,
  so run it last.
- **Shell launches.** `pm pr start` from a shell without `--transcript`
  has no `--session-id` in its pane command. It is not registered by the
  TUI idle tracker and is **not** trust-watched by the orphan watch either
  (`pr-c9e69fb`, design limit in impl.md R6). The orphan watch is reachable
  only for panes whose start command carries a session id that the current
  TUI cannot register: TUI-launched impl/review panes after a hard TUI kill
  and `pm session`, or a hand-made window whose command has
  `--session-id`.
- **Accept key pattern.** The first accept attempt is Down then Enter. A
  second attempt is Enter only, because the cursor is already on "Yes". A
  stand-in key log therefore reads `DOWN@no, ENTER@yes[, ENTER@yes]`. The
  failure condition is any `ENTER@no`.
- **Resume route.** TUI `s` never resumes (`pr-9f97a8f`). The path that
  resumes is the terminal fall-through: `pm pr start <pr>` from a shell
  with no tmux on PATH (e.g. `env PATH=<PATH without tmux> pm pr start`),
  which runs `launch_claude --resume` via the `pr:start:<pr>` session key.
- **Auto-start merge route (M2b).** `_attempt_merge` runs `pr merge`
  without `--no-signoff-check`, and `pm autostart add` defaults to
  `--stop-before-merge`. Reaching `_maybe_auto_merge` needs all of:
  `pm autostart add --auto-merge <pr>`; `pm project set skip-qa on`; a
  SIGNOFF_MERGE at the workdir HEAD (a `report.html` with
  `<meta name="pm-signoff-verdict" content="SIGNOFF_MERGE">` under
  `~/.pm/sessions/<tag>/captures/<pr>/`, then `pm pr signoff record
  <pr>`); and a fake review PASS while the merge stays real Claude. MERGED
  detection then needs pm hooks in `$CFG/settings.json` and
  `$CFG/projects` symlinked to `~/.claude/projects`.

## Host trust policy and configuration

Scenario 6 covers host policy, config writes, the CLI, locks and bounded
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
5. **TUI guide/assist pane (`911e75b7` + `24796646`, first live test after
   review).**
   - Given: the unapproved project root from step 1, real Claude for
     `guide` (no fake-claude `guide`/`_all` entry).
   - When: the user opens guide/assist from the TUI (`H`).
   - Then: the guide pane shows the dialog for the project root, pm sends
     no keys, the config gains no entry, and pm's log has
     `workspace trust: <root> not approved`. (Round 5 pre-fix: no log
     line at all.)
   - Then: after `pm trust add <root>`, closing the guide pane and opening
     it again from the TUI shows no dialog, and the config has the root's
     entry written before Claude starts.
   - Fake guide: with a fake-claude `guide` entry and the root's entry
     removed again, opening the guide writes **no** trust entry and logs
     no trust line (a fake guide has no dialog, like `launch_claude`).
   - Record, without failing, that `c`/discuss panes still log nothing
     (`pr-629c47e`); add a note there if the scope differs.

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
   - `~/.pm/settings/trusted-workspaces` is written under a flock with an
     atomic replace since `f650a308`, so 10/10 is expected.
   - If any are missing, reproduce it at least twice. Then either fix it
     (commit on this PR with a regression test, flagged unreviewed) or file
     it with `pm pr add … --plan bugs` and reference the PR id.
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
     - the stand-in key log shows at most 2 accept attempts (see the
       accept key pattern in Harness notes), and never an Enter sent while
       the cursor was on "No, exit".
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

### H7. Orphan trust watch for panes the current TUI cannot register

The TUI trust-watches every impl/review pane it finds but cannot register
with its idle tracker, as long as the pane's start command carries a Claude
`--session-id`. In practice that means panes an earlier TUI launched (after
a hard kill). It recovers the Claude session from the pane's start
command. Shell `pm pr start` panes have no session id and are not watched
(`pr-c9e69fb`). Uses the stand-in, grace 30s, and the stand-in key log.

1. **Shell-started impl at a stuck dialog (design limit).**
   - Given: the TUI is running; the stand-in `claude` is on PATH for the
     shell; a PR with an approved workdir.
   - When: the user starts that PR's implementation from a separate shell
     (`pm pr start <pr>`, not the TUI).
   - Then:
     - the pane command has no `--session-id`;
     - the stand-in key log stays empty and the TUI posts no trust message
       for the pane, even after grace + 30s;
     - the TUI stays responsive.
   - This is the known limit tracked in `pr-c9e69fb`. Record it; it is not
     a FAIL of this round. If keys or a message do appear, report that the
     limit no longer holds and add a note on `pr-c9e69fb`.
2. **Hard TUI kill with real Claude: the fallback actually unblocks.**
   - Given: a TUI-launched impl pane with real Claude at the dialog for a
     fresh approved workdir. Defeat bootstrap by holding a fresh
     `<config>.lock` as in H4.4, and kill the TUI before its own watch
     accepts (or delete the entry right after launch).
   - When: the user hard-kills the TUI process (not `pm tui restart`),
     releases the lock and runs `pm session` again.
   - Then: the dialog is visible briefly, the new TUI accepts it by cursor
     within a few seconds, the session reaches its first real output, and
     the config gains the entry.
3. **Hard TUI restart, budget across restarts.**
   - Given: a TUI-launched impl pane at the stand-in dialog that already
     received its accept attempts.
   - When: the user hard-kills the TUI process and starts `pm session`
     again.
   - Then: the pane gets **no** further Enter (the per-pane budget spans
     restarts; total stays at most 2), and the new TUI reports the blocked
     pane once (one red line naming the path and the remedy, not repeated
     on later polls).
4. **No false fires.**
   - Panes with no Claude session id in their start command (e.g. a plain
     shell window named like an impl window) get no keys and no message.
   - A pane past the dialog that later prints dialog-like text (`cat` the
     `TRUST_SCREEN` fixture in a real session) gets no keys and no message.
   - Once the pane is gone (window killed), nothing more is logged for it.
5. **Unapproved cwd stays explicit.** A hand-made Claude window named like
   a PR window, whose start command has `--session-id` and `cd`s into an
   unapproved dir (e.g. the throwaway project root), gets no keys, and pm
   writes no trust for that dir.
6. **No duplicate report after a trust-blocked review loop (`211cfb95`,
   first live test after review).**
   - Given: the stand-in on PATH for `review`, grace 30s.
   - When: the user starts a review loop from the TUI and waits until it
     ends in ERROR with the trust message (H6.3), then waits another 90s.
   - Then: the TUI log shows the red trust line for that pane **once**;
     the orphan watch does not post it again on later polls.
   - Then: the user hard-kills the TUI and runs `pm session` again. The
     restarted TUI reports the still-blocked review pane exactly once, and
     sends no further Enter.
   - Record the pre-fix comparison from round 4 (duplicate red line about
     35s later; captures `scenarios/6`).

## Workflow and container trust

Scenario 7 covers every workflow role, reused workdirs, restart, the
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
5. **Planned = launched (`4c3fb81c`).** Quote the planner's final plan and
   the TUI/pm log line "QA plan parsed: N". N must equal the number of
   SCENARIO blocks in the planner's own final plan and the number of
   scenario windows launched. The throwaway PR's committed qa.md must
   contain a line-start `SCENARIO` heading (as round 5's did) so the
   echoed-prompt case is exercised; if the planner numbers from 2 or
   higher, that is the exact pre-fix case.

### W2. Every role starts without the dialog

Use real Claude. Each role must launch in its approved workdir and start with
no dialog and no manual keys. Capture each pane from launch, then stop it
after it starts working, to bound cost:

- implementation (`pm pr start` / TUI);
- review loop;
- QA planner, concretizer, scenario worker, verifier and finalizer (from W1);
- sign-off (or the sign-off launch path as the TUI drives it);
- merge resolution is covered separately in Scenario 8 ("Local merge
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
   - When: the user kills the impl window and starts the PR again through
     the route that resumes: the terminal fall-through (see Resume route in
     Harness notes).
   - Then: the resumed Claude session (`--resume`) shows no dialog, the
     config entry is re-written first, and the session continues the
     earlier conversation.
   - Also press TUI `s` on that PR once and record what happens. A fresh
     session instead of a resume is pre-existing `pr-9f97a8f`, not a FAIL
     here; the fresh session must still start with no dialog.
4. **Interrupted QA:**
   - When: QA is stopped mid-run (quit and restart the TUI / `pm session`)
     and QA is started again.
   - Then: the restarted run re-bootstraps any new clones, never sits at
     the dialog, and produces its own nonempty plan and worker activity.
5. **Review left at the dialog across a hard TUI kill (round-3 failure,
   fixed by the orphan watch; regression check).**
   - Given: a review loop with real Claude whose pane sits at the dialog
     for its approved workdir (bootstrap defeated, e.g. entry deleted and a
     fresh lock held until the TUI is killed).
   - When: the user hard-kills the TUI process and runs `pm session` again.
   - Then:
     - the new TUI accepts the dialog by cursor within a few seconds
       (at most 2 attempts total for that pane) and the review session
       reaches a verdict in its pane;
     - record the pre-fix comparison from round 3 (pane sat at the dialog
       5+ minutes; captures `scenarios/4/W3-adopted-review`).
   - The loop itself is not adopted after a hard kill (`pr-5d66709`):
     report whether the verdict is collected, but do not fail W3.5 on that.
   - A graceful restart (`pm tui restart`, breadcrumb) adopts the loop:
     show the adopted review continues and reaches a verdict.
   - Container variant, if the environment allows: the same with a
     container review pane. The dialog shows `/workspace`; with host
     `/workspace` present (`pr-8c0d680`) expect a single report, not an
     accept. Record which happened.
6. **Known edge cases left by review 80f0 i3 (reproduce, confirm
   tracking).** Both are filed; the goal is to confirm the live scope, not
   to fix them in this round unless the fix is small and gets a
   fail-before/pass-after test (then flag it unreviewed).
   - **Resumed session after trust reset (`pr-d76385d`).** Given a PR whose
     impl session already ran (its transcript exists). Kill its window,
     delete its `projects[<workdir>]` entry from the config in use, and
     defeat bootstrap (hold a fresh `<config>.lock` for about 25s). When the
     user starts the PR again (resume). Then record what the pane shows and
     whether pm accepts the dialog, marks the pane "needs you", or reports
     after the grace. Expected per the bug: the dialog sits unaccepted and
     unreported. Record the outcome against `pr-d76385d`, and add a pm
     note on that PR if the scope differs (e.g. also review/QA resumes).
     In round 4 TUI `s` never resumed (`pr-9f97a8f`), so this was
     unreachable. Try the terminal fall-through resume too: it bootstraps
     trust but has no trust watch, so with bootstrap defeated record
     whether the dialog sits there. Record "unreachable via TUI, tracked in
     `pr-d76385d`/`pr-9f97a8f`" if nothing new shows up.
   - **Transient start-command read failure (`pr-9e37213`).** Only a code
     path for an injected failure reaches this; do not patch the app to
     simulate it. If a user-level route exists (e.g. briefly making the tmux
     socket unreadable while a restarted TUI first polls an orphan pane at
     the stand-in dialog), try it once and record the result; otherwise
     write "not driven live, tracked in `pr-9e37213`".

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
7. **Container QA (actual worker activity is required).** Round 3
   achieved this for the first time (scratch-HOME route, hooks arrived, 3
   container scenarios reached PASS/VERIFIED/FINALIZE_DONE). Repeat it on
   the current head with the same route and keep the evidence; a regression
   here is a FAIL. Run #230 never launched a container worker: hook events could not reach pm from the
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

Scenario 8 covers merge resolution, a role named in acceptance. It runs on
the host path with the **local** backend (`pm init --backend local`), real
Claude for the resolution window, and the isolated config from Setup. Seed
uncommitted user work in the main repo (e.g. an untracked `user-work.txt`,
not `notes.txt`, to avoid confusion with `pm/notes.txt`, and a modified
tracked file) before M1 and check it is untouched after every story.
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

Give every conflict PR a **title** that names the winning side (e.g.
"D: shared.txt line 2 - on conflict keep this PR line"), and/or a
`## Merge` section in pm notes, so a real Claude window can resolve it
without asking. The merge prompt (`generate_merge_prompt`) includes only
the PR title, the git error and the General/Merge/Local pm notes sections,
**not** the PR description, so a description alone does not reach Claude.
M2c covers the ambiguous case on purpose (neutral title, no notes).

**M2a. Manual merge (command bar).**

- Given two PRs that edit the same lines; the first is merged. The second
  PR's title names the winning side.
- When the user merges the second from the TUI command bar
  (`pr merge --resolve-window --no-signoff-check <pr>`).
- Then:
  - the TUI shows "Opened merge resolution window". It does **not** show
    an "Updating master in the PR workdir … CONFLICT" line here: with this
    Given the base sync is a clean fast-forward and the conflict is at the
    PR-branch merge. That line only appears in M3;
  - a `merge-<pr>` window opens and its `#{pane_current_path}` is the
    **PR workdir**, not the project root (record it);
  - the pane shows no trust dialog (continuous capture from launch) and no
    manual keys are sent;
  - Claude resolves it without asking and reports MERGED in the window;
  - the PR workdir has `hasTrustDialogAccepted: true`; the project root has
    no entry;
  - the TUI does not follow up (`pr-c50d365`, pre-existing); the user runs
    `pm pr merge --propagation-only <pr>`, which fast-forwards the main
    repo with no second window, and the PR shows `merged`. This is
    expected, not a failure of this PR.

**M2b. Auto-start merge.**

- Given a third conflicting PR (title names the winning side) set up for
  the auto-start merge route in Harness notes. It must already be
  `in_review` before `pm autostart add` (a shell-started fake impl is
  untracked, `pr-c9e69fb`), or re-add the target after it gets there.
- When auto-start reaches the merge.
- Then the window opens in the PR workdir with no dialog, Claude reports
  MERGED without input, and the TUI runs `pm pr merge --propagation-only`
  itself ("Step 1 merged" / "✓ Merged … conflict resolved by Claude"). The
  PR shows `merged`, with no second window.

**M2c. Ambiguous conflict asks, explicitly.**

- Given a conflicting PR with **no** stated intent and a genuinely
  ambiguous same-line edit.
- When the user merges it from the command bar.
- Then the window opens in the PR workdir with no dialog, and Claude asks
  which side to keep (INPUT_REQUIRED) instead of guessing. This is the
  expected outcome. The tester answers once after the first output; then
  MERGED and propagation follow as in M2a.

### M3. The main repo's base moves during the merge

- Given a PR whose workdir merge has finished but not propagated, and a
  new commit is then made on the main repo's base. Recipe (round 5): put a
  `.git/index.lock` in the main repo before step 1 (the merge exits 1
  after the workdir merge), remove the lock, commit on the main repo's
  base, then run `pm pr merge --propagation-only --resolve-window <pr>`.
- When propagation runs.
- Then the new commit is integrated in the PR workdir and the fast-forward
  retried. A non-conflicting commit propagates with no window. A
  conflicting one shows "Updating master in the PR workdir … CONFLICT" and
  opens the window in the PR workdir again. The main repo is never reset
  and keeps both histories.

### M4. A main-repo-side failure exits without a window

- Given a `.git/index.lock` in the main repo, which blocks the
  fast-forward.
- When the user merges a PR.
- Then `pm pr merge` exits non-zero with a message that names
  `pm pr merge --propagation-only <pr>`; no Claude window opens in the
  project root; nothing in the main repo is reset or lost. After the
  blocker is cleared, the printed command completes the merge.
- Note in the report whether the TUI leaves the PR pending until the user
  runs the command (known benign behaviour from review i3).

### M4b. Dirty main-repo files that overlap the merge are kept

- Given uncommitted changes in the main repo to a file that the incoming
  PR also changes.
- When the user merges the PR.
- Then the merge does not fail: propagation stashes the main-repo changes
  (including untracked files), fast-forwards, restores them ("Restored N
  stashed file(s).") and exits 0. The user's edits are still there
  afterwards. If the restore conflicts, pm prints "stash pop had
  conflicts" and the stash still exists; nothing is lost.

### M5. Unapproved merge window stays explicit

- Given the vanilla/GitHub-style pull-from-origin path, which still opens
  in the project root (out of scope, `pr-19990de`). With the vanilla
  backend the first `pm pr merge` always fails its dual-pushurl push to the
  checked-out main repo and opens a spurious window in the PR workdir
  (`pr-ea04ba8`, pre-existing); the root window is reached by a second
  `pm pr merge --propagation-only <pr>` with a diverged main repo. That
  sequence is expected.
- Then, for the root window: pm prints the `pm trust add <dir>` remedy when
  it opens, sends no keys to the dialog, and writes no trust for the root;
  the dialog stays on "No, exit". The spurious workdir window shows no
  dialog. If this path cannot be driven, say so and cite `pr-19990de`;
  do not mark it PASS.

### Concurrency

While an M2 window is open, start a review loop on another PR and run
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
- evidence contains credentials;
- the worker dies of harness resource exhaustion (PIDs/zombies) instead
  of ending with a concrete finding (see "Process hygiene");
- a scenario overwrites or deletes another scenario's or an earlier round's
  captures, or cites the contaminated round-3 `scenarios/1`–`3` metadata
  as evidence;
- a bug is left with only a "nonblocking" label and no fix, tracking PR
  or UNRESOLVED verdict.

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
7. **Pre-existing merge follow-up bugs (round-3 S5 INPUT_REQUIRED).** Both
   are pre-existing on master and are not trust bugs: `pr-c50d365` (manual
   merges get no MERGED follow-up; the local merge resolved in the workdir
   on master too, so propagation was already needed) and `pr-ea04ba8`
   (vanilla dual-pushurl push). They stay tracked in their own PRs. M2 and
   M5 now state the real sequence instead of failing on it. The supervisor
   can still choose to fix them here; until then they are not blockers for
   this PR.
8. **Orphan watch scope.** The orphan watch only trust-watches; it does not
   adopt idle tracking or loops (`pr-5d66709`). H7 and W3.5 test only the
   trust behaviour plus what the user sees in the pane. Shell
   `pm pr start` panes are outside it (`pr-c9e69fb`).
9. **Round-4 S8 INPUT_REQUIRED items.** Both were spec errors, not product
   bugs. (1) The "Updating master in the PR workdir … CONFLICT" line
   belongs to a base-sync conflict (M3), not to a PR-branch conflict
   (M2a); surfacing the PR-branch conflict text in the TUI is not
   required. (2) A merge window that asks on a genuinely ambiguous
   conflict is correct behaviour. So M2a/M2b give conflict PRs a stated
   intent, and M2c expects the question. M4 was split into M4 (index.lock)
   and M4b (dirty overlap is stashed and restored), as the round-4
   concretizer found in the code. The supervisor may still ask for TUI
   conflict text as a separate change.
10. **Round-4 S7 W3.3 resume.** TUI `s` not resuming is pre-existing
    (`pr-9f97a8f`, on master too) and is not a trust bug. Acceptance asks
    that resumed work starts without the dialog; W3.3 now drives the
    terminal fall-through resume, which does resume, and W3.2/W3.4/W3.5
    cover review restart, QA restart and TUI restart handoff. TUI `s` is
    still exercised and its fresh session must still start with no
    dialog. The supervisor may still choose to fix `pr-9f97a8f` here;
    then `pr-d76385d` must be tested with it.
11. **Round-5 corrections and new coverage (round 6).** The S11
    concretizer found that the merge prompt never includes the PR
    description, so M2 now carries the winning side in the PR title (or a
    `## Merge` pm notes section); round-4 Z resolving hands-off was
    incidental. The M3 "stop after the workdir merge" recipe is the
    index.lock route. The round-5 app fixes `911e75b7` (guide pane) and
    `4c3fb81c` (plan parse) are reviewed (review 5a14 i1) and get their
    first post-review live tests in H2.5 and W1.5/W3.4. The other TUI
    interactive panes with the same guide gap stay tracked in
    `pr-629c47e`; the supervisor may still choose to fix them here.
12. **Round 7 scope (supervisor recovery 2026-10-14).** Only the
    workflow/container group runs (SCENARIO 15). Round 6 S12 and S14 are
    PASS and independently VERIFIED on `17d4f39a`; the head since then
    changes no app code, so they carry forward and are not rerun. S13
    gets no credit: it died of harness-caused PID exhaustion
    (`pr-2111fa0`), so S15 must follow "Process hygiene" before driving
    anything. If S15 makes any app edit, the result is NEEDS_WORK and the
    edit goes back through review; a rerun of S12/S14 is then needed only
    if the edit touches their code paths.
