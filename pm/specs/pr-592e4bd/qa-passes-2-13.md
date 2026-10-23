# pr-592e4bd — QA spec §2 Setup: completed delta passes 2–13 (S7–S33)

Moved here verbatim from `qa.md` §2 (Setup), right after "Lessons from
the first QA run", in review loop a183 i1 (2026-10-23). This keeps the QA
planner / sign-off / review prompts under Linux MAX_ARG_STRLEN
(pr-ace66e5). Every pass below is complete. Their requirements are RQ1–RQ34
and E1–E10 in `qa.md`, which still apply. This file keeps each pass's
delta scope, the harness it reused and its harness gotchas. The text is
unchanged (list items keep their `qa.md` indentation).

  - Second-pass handoff: prior captures live under the PR capture root
    `scenarios/1..6` (1,2,5,6 independently verified; 3/4 produced fixes
    0b1edfca/c5d7d64f, since reviewed). Reuse/adapt their fixture scripts
    (stand-in-only `apiKeyHelper`: `scenarios/5/scripts`) but write to NEW
    scenario capture paths; inspect hardcoded output paths first and never
    overwrite prior captures. Put fake-claude on the scratch HOME's PATH.
  - Clean up fixtures by the exact PIDs / argv / socket paths you started;
    broad `ps | awk` / `pkill -f` matching killed a QA executor.
  - Probe/bridge sources (worker_route.py, route_bridge.py,
    cli/provider.py, container.py) are unchanged since the real
    host + rootless-container work-account smoke with underscore cwd
    (`host-work-route-smoke-20261022T195845Z`) and still match a4cec139;
    later product changes are in qa_loop.py (0b1edfca, c5d7d64f,
    b97c0e3d, acdb i3/i4), push_proxy.py (dbb88ea8) and
    tui/qa_loop_ui.py resume selection (60574f28, aea1fb8a, acdb i1–i3).
  - Out of scope, filed: pr-8f8ae78 (worker launch after a dead refiner
    pane logs Launched but creates no pane and burns a retry), pr-09f01da
    (in-container pm shim imports a shadow project pm_core, so *faked*
    workers break in shadow projects — RQ18 checks use real/routed
    workers or a project without fake workers), pr-1139060 (-sN orphan
    sweep matching another PR's window), pr-173e11e (live probe leaves an
    empty temp dir), pr-3c7ce04 (login-expired pane).
  - Third pass (S11+), delta-only per supervisor handoff: review acdb i5
    PASS at 53419df2; QA2 S7/S8 independently verified PASS; S9/S10
    exercised every story and ended NEEDS_WORK only for their own code
    changes. Unchanged coverage kept as evidence, not rerun: RQ1–RQ4,
    RQ9/RQ10 startup-failure matrix and E1–E3/E7 (S7/S8), bridge/transport
    RQ8/E4–E6 and the real work-account host+container smoke
    (host-work-route-smoke-20261022T195845Z, sources hash-checked).
    Fresh live verification needed: RQ16 at BOTH gates (refiner gate:
    route lost between container create and refiner launch; worker gate:
    route lost after the refiner replies), RQ19 restart selection
    (queued-tail overlap, older unfinished orphan vs newer run completed
    while the TUI was down, empty-plan newer run, live-owner kept), and
    light re-observation of RQ17/RQ18 plus RQ12/RQ14 gating on adopted
    runs. Reuse driver scripts from capture scenarios/9 and /10; key
    waits on the fresh run's loop id / terminal state, not on counts of
    completion lines.
  - Fourth pass (S13+), delta-only: S11/S12 held their stories and ended
    NEEDS_WORK only for their own code changes (1b6e2c68, 7c401141,
    ea78b9d1, c23a2021) plus review 8a99 i1/i2 (ea6b9e17, e47dc12d).
    Everything else stays as evidence (S7–S12 captures). Review 8a99 i3
    PASS on e47dc12d (3446 tests, independent mutation checks,
    captures review-8a99-i3). Already live post-fix and not rerun: RQ20
    routed resume incl. exact route-recovers-before-idle timing and RQ22
    repeat deferral (S11 post-fix/race, r2), RQ23 1b6e2c68/ea78b9d1
    stories (S12 story1/4). Fresh live verification only for the delta:
    RQ20 unrouted side + cap, RQ21 (ea6b9e17), RQ23 supersede-vs-write
    race and restart (e47dc12d), c23a2021 log line. Run in a scratch
    session only — never restart the production TUI or resume its held
    runs. Reuse scenarios/11 and /12 scripts after reading their
    Deviations (separate PR-id vs capture-dir variables, abort when
    selection fails; bounded fresh-run waits, no self-matching pgrep);
    render terminal video with VFR ffmpeg. To provoke an API-error turn on a healthy
    route, make the stub router answer the messages endpoint with a
    non-retryable error (HTTP 400/529 body in Anthropic error shape) or
    drop the connection for a chosen number of requests while still
    listening (preflight stays healthy); Claude's idle notification comes
    about a minute after the error turn. For the unrouted case point
    `ANTHROPIC_BASE_URL` at the "main" stub and make it fail the same way.
    TUI restart = kill -9 the pid in `~/.pm/tui-<session>.pid`, then
    `pm session </dev/null`. Out of scope, filed: pr-0f85376 (finalization
    INTERRUPTED when a completed run is recovered after a dead driver).
  - Fifth pass (S15+), delta-only: S13/S14 held their stories. The only
    later product changes are review 590d i1/i2 (887a0b18 `_send_submitted`
    for every pane message, reminder failure no longer crashes the QA
    thread; ff2c2474 verification pane races). Fresh live verification only
    for RQ24, in host and container mode. Drive the verifier with a
    fake-claude scripted sequence for `qa_verification` (e.g.
    `{"sequence": ["FLAGGED_END", "VERIFIED"]}` with a `delay` long enough
    to kill panes while it works) and keep workers routed real Claude on
    the stub router so that follow-ups go into a real prompt box. Kill
    single panes by the pane id shown in the pm log/`tmux list-panes`, not
    whole windows, unless the story says window. Set
    `qa-verdict-reminder-timeout` low for the reminder story and make the
    stub answer the worker without a verdict line.
    QA5 handoff harness lessons (S13/S14 REPORTs): use the exact TUI/pm
    log path from those reports; their env.sh clears variables, so pass
    values as positional args; never copy rotating OAuth credentials;
    scratch containers on slirp4netns; no `pgrep -f` self-matching and
    no `kill -0` completion waits on zombies; convert recordings with VFR.
    Kept as-is (do not strengthen): S14 numbering clarification 590a39ab.
    Known separately: #245 queued-startup ownership, pr-04dfffb.
    QA5 clarifications (supervisor, before S15/S16 refinement):
    (1) `podman inspect` Config.Env of a QA container legitimately holds
    the values passed by name (`-e NAME`, values via the runtime process
    env) -- that is the intended delivery (RQ15, S14 evidence). The
    no-secret check covers generated argv/commands, pm logs, pane output
    and captures; if container env is inspected, record a count only,
    never require absence and never copy values into captures.
    (2) Dead-window container cleanup with two PRs running the same `-sN`
    indices can hit the known orphan-sweep collision pr-1139060 (#241).
    A lingering dead-window container, or a sweep that touches the other
    PR's same-`sN` container, is attributed to pr-1139060 and recorded as
    an observation, not a new pr-592e4bd requirement. Pane-loss and
    recovery checks (no crash or hang, INPUT_REQUIRED or a relaunch
    through the route gate, no misdirected message, no false "resumed")
    stay as required.
  - Sixth pass (S17+), delta-only: S15/S16 held their stories and ended
    NEEDS_WORK only for their own code changes (32961096, 296c08a7,
    75649ae4), all reviewed sound in review b62f i1. The only product
    changes since are push_proxy.py (b62f i1 8a3d3412 stop lock, i2
    130e8ab9 daemon socket ownership); probe/bridge/launcher sources and
    qa_loop.py logic are unchanged. Fresh live verification only for
    RQ26, in container mode (host mode has no push proxy). Keep routed
    workers real Claude on the stub router so the route gate is real
    (RQ16 deferral path); push checks may be run by the tester from
    inside a scenario container (`git push` of the PR branch and of a
    disallowed branch), as a worker would. Count proxy daemons by the
    exact socket path in their argv (`ps -o pid,lstart,args`), never by
    `pgrep -f` patterns that match the shell running the check; compare
    socket birth time, not inode (overlay fs). Out of scope, filed:
    pr-748e708 (impl/review containers from a separate `pm pr start`
    process share the QA proxy key, and per-process refs mean QA teardown
    can stop a proxy an impl container still uses): record as an
    observation only.
  - Seventh pass (S19+), delta-only: S17/S18 held their RQ26 stories.
    The only product changes since are qa_loop.py `_split_worker_pane`
    (a2ff954c from S17, review ab29 i2 ded27fcd). Fresh live
    verification is needed only for RQ27, in host and container mode.
    Initial and queued launches use the same code path. Keep refiners
    and workers routed real Claude on the stub router, so the refiner
    can be held at the stub (control file) until the split moment.
    - To make tmux refuse the split while the refiner is alive, run
      `tmux resize-window -t <pm session>:qa-<pr>-sN -y 2` on the held
      refiner's window (this sets that window's window-size to manual
      only), then release the refiner. Checked on tmux 3.4: a 2-line
      window gives "no space for new pane", rc 1. The relaunch opens
      a new window at normal size.
    - The closed-window case is the user (or `Y`) closing the
      `qa-<pr>-sN` window while its refiner is held. The refiner then
      reports a pane death, the planner draft steps are used, and the
      split hits a gone pane.
    - Retry backoff is `_SCENARIO_RETRY_BASE * 2**n`. Key waits on the
      log lines, not on fixed sleeps.
    - Reuse the S15/S16/S17 harness scripts (stub.py, stubctl.sh,
      env.sh, seed_home.sh). Write to new capture dirs.
    - pr-8f8ae78 covers this same path. a2ff954c fixes its false
      "Launched" line. Still open there, and by design here: the
      retry the relaunch spends and the blocking backoff sleep. Record
      "retry 1/10" as expected, not a failure.
    - Out of scope, already filed: pr-1139060, pr-748e708.
  - Eighth pass (S21+), final acceptance on the current head. S19 (host)
    and S20 (container) held RQ27. S20's only code change 2314f1a8
    (TmuxCommandError naming tmux's stderr for every failing tmux
    command run with check; closed refiner skips the worker route gate)
    was replayed live post-fix in both modes (S19 replay on d9338561, S20
    post-fix) and reviewed in 6c6f i1. Probe, bridge, launcher, provider
    and container sources are unchanged since a4cec139, the commit the
    real work-account host and container smoke ran on. qa_loop.py,
    push_proxy.py and TUI resume have had about 26 fixes since the S7/S8
    core matrix (b6cec11a). Each fix was checked live on its own, but
    never all together. This pass is therefore a consolidated end-to-end
    regression on the current head. It does not re-probe single fixes in
    isolation. Run one long host-mode run and one long two-PR
    container-mode run. Each covers, in one session: the role split (stub
    request log plus the main stub), routing visibility, transcripts and
    hooks, a startup outage with automatic recovery, a mid-run outage
    with queued, stalled and dead workers, a PASS-verification round trip
    with a flag follow-up, stop and fresh start, and a TUI restart with
    resume. Container mode adds the bridge, the push proxy and the no-secret
    checks. Reuse the S15–S20 harness (stub.py, stubctl.sh, env.sh,
    seed_home.sh, the verifier main stub from S15). Write to new capture
    dirs. Treat any Then that fails as a regression in the combined head.
    Known items stay observations: pr-1139060, pr-748e708, pr-8f8ae78
    (retry 1/10 on a failed split), pr-04dfffb, pr-d1d0139, pr-3c7ce04,
    pr-0f85376, pr-09f01da, pr-3201ea8.
  - Ninth pass (S24+), delta-only. S21–S23 held on the combined head.
    S21 and S22 ended NEEDS_WORK only for their own fixes: ee3d0644
    (finalize ran with verification off), 2ff602fc (a stopped run spawned
    no finalizer). Review 3ce6 i1 found both sound. Review 3ce6 i2
    (54ff5a68) changed the finalize gate to use the poll's
    `qa-verify-pass` reading. That last change has never run live. All
    three are in `_run_qa_finalize_pane`. Fresh live verification is
    needed only for RQ28 and RQ29, in host mode. The finalize logic is
    the same in both modes, and S23 already held container-mode finalize
    on 2ff602fc. Keep refiners and workers as routed real Claude on the
    stub router, held per (PR, scenario, role) from the control file, so
    PASS timing is controlled. Fake `qa_planning`, a `qa_verification`
    VERIFIED with a delay long enough to see the verifier pane, and
    `qa_finalize` FINALIZE_DONE. A fake finalizer is enough. The fix
    decides whether a finalizer launches, not what it does.
    `qa-verify-pass` is a global setting (`pm set qa-verify-pass on|off`),
    shared by every run in the session. Read the TUI "QA complete: …
    [finalize: …]" line and the pm "QA complete for <pr>: … (finalize=…)"
    line, not only qa_status.json. Reuse the S21/S22 harness scripts
    (stub.py, stubctl.sh, env.sh, seed_home.sh) and write to NEW capture
    dirs. S23 spec slip, kept as is: the resume log line counts every
    restored scenario ("3 scenario(s), 1 queued" for 2 live and 1
    queued). Known items stay observations: pr-1139060, pr-0f85376 (a
    finalization INTERRUPTED on a dead-driver recovery), pr-04dfffb,
    pr-8f8ae78.
  - Tenth pass (S26+), delta-only. S24 and S25 held RQ28 and RQ29 with
    no product change other than 89414241 (S24: start the TUI poll timer
    when a QA run is registered), and review 433b i1 fb7af748 (keep the
    timer until the finished run's second tick). Both are in the TUI
    poll timer only. The QA loop, routing, finalize and container code
    are unchanged, so fresh live verification is needed only for RQ30,
    in host mode (the timer does not depend on the mode). The failure
    only shows when nothing else keeps the timer alive. Use PRs that have
    never had QA (no `workdir` in project.yaml), no other PR in progress
    with a workdir, no review loop and no watcher, and check that before
    each story. A PR's first QA run itself persists its workdir (see the
    RQ30 clarification), so this holds only for the first run in a
    fresh project. Record disk state and the cached-state reload points
    separately. Measure the gap between the pm "QA complete for <pr>"
    line and the TUI message, the `qa_resume.json` removal and the
    picker `[done …]` badge. Pre-fix the gap was about 95 s (up to
    300 s). Pass is a few seconds. Keep refiners and workers routed real
    Claude on the stub router, held per (PR, scenario, role), so finish
    times are controlled. The stub needs a worker reply ending in
    NEEDS_WORK or INPUT_REQUIRED for the non-PASS stories. Fake
    `qa_planning` and `qa_finalize`. Verification can stay off. Reuse
    the S24/S25 harness scripts and write to new capture dirs. Known
    items stay observations: pr-0f85376, pr-1139060, pr-04dfffb.
    QA10 handoff (supervisor, 2026-10-23): 89414241 and fb7af748 were
    independently PASSed at 624f2112. The production root TUI still runs
    old master: restart and load the candidate only in a scratch TUI
    session (kill -9 the scratch pid in `~/.pm/tui-<session>.pid`, then
    `pm session </dev/null`). Other production QA stays held. Make no
    production setting or model changes. Recording: copy the renderer
    from the S24 scripts (`/pm-captures/scenarios/24/scripts`): ffmpeg
    `-vsync vfr` with a 1/100 time base, keeping the .cast and GIF,
    then frame-count, duration and decode checks. The S25 scripts use
    `-vsync vfr -enc_time_base 1/100 -video_track_timescale 100`. Never
    reuse an older default-CFR render line. It duplicates frames for
    hours. S24 REPORT: the first story's original .cast is missing (logs
    and screens present), later stories are recorded. Check that every
    story's .cast exists before rendering.
  - Eleventh pass (S28+), delta-only. S26/S27 held RQ30. The only
    product changes since are the S26 TUI fixes f57c500c (repaint after
    a QA NEEDS_WORK transition) and 991addf9 + 0697e450 (held and forced
    zz t "restarting QA" line), reviewed in 1298 i1/i2 (impl.md §5 item
    23). They are in `_on_qa_complete` only, so fresh live verification
    is needed only for RQ31, in host mode. Keep refiners and workers
    routed real Claude on the stub router, held per (PR, scenario,
    role), so finish times are controlled; the worker reply decides the
    verdict (pass / needs_work / input_required, as extended in S26).
    `qa-pass-count` is the file `~/.pm/settings/qa-pass-count` in the
    scratch HOME (`pm set` does not know it). A sticky line from another
    PR is easiest from a `zz d` review loop whose fake `review` session
    emits INPUT_REQUIRED. Measure what the TUI log line shows from the
    TUI pane capture and the .cast (frame times), not only from `L`,
    because the bug was a line recorded in `L` but never painted. The
    tech-tree box status is read from the TUI pane, compared with
    project.yaml. Reuse the S26 harness and write to new capture dirs.
    Scratch TUI session only; no production settings or model changes.
    Known items stay observations: pr-0f85376, pr-1139060, pr-04dfffb.
  - Twelfth pass (S30+), delta-only. S28/S29 held RQ31. The only
    product changes since are tree-node marker precedence in
    `pm_core/tui/tech_tree.py` (9cc2fb6b from S29, replayed live there
    for the masked-spinner case only; review 4f28 i1 84662f7f moved it
    into `_get_loop_marker(qa_live=)` and never ran live). Fresh live
    verification is needed only for RQ32, in host mode (rendering does
    not depend on the mode). Read markers from the TUI pane capture and
    the .cast frames (spinner frames change every tick, so assert the
    marker family, not one glyph). A finished loop: `zz d` on an
    in_review PR with a fake `review` session (use `idle_once_after`,
    impl.md §5 item 24(b)), then `z d`. A running loop: start QA with
    `t` while that loop is still running (start_qa does not refuse it).
    QA `waiting`: workers run without the session's
    dangerously-skip-permissions file and the stub router answers a
    worker turn with a Bash `tool_use`, so real Claude shows a
    permission prompt; if that cannot be produced, record it and keep
    the active-state Thens. `⏸M` needs a merge window INPUT_REQUIRED
    (`merge-<id>` window, transcript `merge-<pr>.jsonl`) on an in_review
    or sign_off PR, discovered by the TUI, before QA starts on that PR;
    reach it through `pm pr merge` with a main-checkout update that
    needs input. If no user flow reaches it, say so in the REPORT and
    rely on `test_merge_input_marker_survives_live_qa`; do not inject
    TUI state. Reuse the S28/S29 harness and write to new capture dirs.
    Scratch TUI session only; no production settings or model changes.
    Known items stay observations: pr-97614ed, pr-89296d3 note-18c906b
    (Ctrl+C in a review pane never ends an INPUT_REQUIRED wait; use
    `z d`), pr-0f85376, pr-1139060.
  - Thirteenth pass (S32+), delta-only. S30/S31 held RQ32 and ended
    NEEDS_WORK only for their own fixes: 94f36a18 (`poll_qa_state` drops
    a replaced run's `qa:<pr>:s*` tracker keys; RQ33) and c97aaf9c
    (`_finalize_all_transcripts` keeps transcripts a reader still polls
    when auto-start turns off; RQ34). Review 03a7 i1 found both sound;
    c3d3f978 is test-only. Each fix was replayed live only by the
    scenario that found it, so fresh live verification is needed only
    for RQ33 and RQ34, in host mode (neither depends on the mode). Keep
    refiners and workers routed real Claude on the stub router, held per
    (PR, scenario, role) from the control file, so mid-turn and finish
    times are controlled. For RQ34 the `⏸M` path follows the S31 recipe
    (vanilla project with a `file://` origin, auto-start target, fake
    review/QA PASS and a sign-off that merges, the main checkout diverged
    by an unpushed commit so the fast-forward fails and the `merge-<id>`
    window opens with its transcript; the merge prompt is real Claude on
    the main stub, answering INPUT_REQUIRED first and MERGED after the
    user replies). Auto-start is turned off before the MERGED reply.
    Check transcript files in the auto-start run directory with
    `ls -l`/`stat` (symlink vs regular file) before and after the turn
    off. Read markers and log lines from the TUI pane capture and the
    .cast, and from `L`/pm logs. Reuse the S30/S31 harness and write to
    new capture dirs. Scratch TUI session only; no production settings or
    model changes. Known items stay observations: pr-b2db183, pr-237d610,
    pr-97614ed, pr-89296d3 note-18c906b, pr-0f85376, pr-1139060.
