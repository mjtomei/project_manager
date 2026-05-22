# QA Spec — pr-abcf70f: FakeClaudeSession

## Overview

This PR adds `pm fake-claude` (and a `bin/fake-claude` standalone) — a scriptable
Claude replacement that emits realistic-looking output ending in a chosen verdict
keyword (or stays open as a no-verdict session). It is wired into all the
launch sites (`launch_claude`, `launch_claude_print_background`,
`launch_claude_in_tmux`) so any pm flow can be redirected to the fake by writing a
JSON config to `~/.pm/sessions/<tag>/fake-claude`. The fake also writes a
Claude-format JSONL transcript and emits the `idle_prompt` hook event when given a
session id so that production verdict polling (`loop_shared.poll_for_verdict` →
`extract_verdict_from_transcript`) works end-to-end. Scope extensions:
no-verdict sessions + `_all` catch-all; verdict-surface audit closing drift gaps
in watcher / qa_concretize / qa_finalize; `qa_concretize` and `qa_finalize`
promoted to first-class `model_config.SESSION_TYPES`; `validate_model_config()`
flags unknown keys and bad effort levels.

## Shared resources touched
- `~/.pm/sessions/<tag>/fake-claude` JSON config (per-session, multi-pane reader)
- `~/.claude/projects/<mangled-cwd>/<session-id>.jsonl` transcript files
- `~/.pm/hooks/<session-id>.json` hook event files (read by poller across panes)
- `bin/fake-claude` executable on the resolved Claude path
- `project.yaml` `model_config` block (validated by new validator, written by
  `pm model set`)

## Requirements

### R1 — Run fake-claude CLI with a single-line verdict
- GIVEN the user has installed pm with the fake-claude binary available
- WHEN the user runs `pm fake-claude --verdict PASS`
- THEN the command exits 0, prints preamble prose lines, a blank line, and the
  bare keyword `PASS` on its own line.

### R2 — Run fake-claude CLI with a block verdict and custom body
- GIVEN the user has installed pm
- WHEN the user runs `pm fake-claude --verdict FLAGGED --body "Step 1: FAILED"`
- THEN the output contains a `FLAGGED_START` line, then `Step 1: FAILED`, then
  `FLAGGED_END` on its own line.

### R3 — Run fake-claude with timing controls
- GIVEN the user wants to simulate a slow session
- WHEN they run `pm fake-claude --verdict NEEDS_WORK --preamble 5 --delay 2`
- THEN five preamble lines stream out, the process sleeps ~2 seconds, then the
  verdict `NEEDS_WORK` is written before exit.

### R4 — Streamed character output
- GIVEN the user wants to simulate character-by-character streaming
- WHEN they run `pm fake-claude --verdict PASS --stream --char-delay 0.005`
- THEN the output arrives gradually (visible character pacing in the recording)
  and ends with the `PASS` keyword.

### R5 — No-verdict session stays open
- GIVEN the user wants to fake an impl/watcher/merge-style session
- WHEN they run `pm fake-claude --verdict NONE --hold 2`
- THEN preamble prose is written, no verdict keyword is emitted, and the
  process exits ~2 seconds later (not immediately).

### R6 — Reject unknown verdicts at the CLI
- GIVEN the user invokes the CLI
- WHEN they pass `--verdict BOGUS`
- THEN the command exits non-zero with a usage error naming the valid choices.

### R7 — Redirect a pm flow to fake-claude via session config
- GIVEN the user is inside a pm session whose tag exists and a fake-claude JSON
  config has been written into the session directory mapping `review` to
  `{"verdicts": {"PASS": 100}}`
- WHEN the user launches anything that ordinarily spawns Claude for that session
  type (e.g. the review loop)
- THEN the launched pane runs the fake binary instead of real Claude, the
  poller observes a `PASS` verdict (via the transcript + idle hook), and the
  loop advances as if real Claude had said `PASS`.

### R8 — `_all` catch-all fakes every session type
- GIVEN the user wants every Claude session in a project to be faked
- WHEN they write a fake-claude config with only an `_all` entry (no per-type
  keys) and then trigger any pm command that would launch a Claude session
- THEN every such session runs the fake as a no-verdict session and stays open
  until the pane closes (no real Claude is invoked).

### R9 — Per-type entry wins over `_all`
- GIVEN both `_all` and an explicit `review` entry exist in the session config
- WHEN a review pane is launched
- THEN the review pane uses the explicit `review` config (emits its verdict),
  while other session types fall back to `_all` (no verdict).

### R10 — Verdict catalogue covers every emitting session type
- GIVEN the documented session types (impl, review, qa, qa_planning,
  qa_scenario, qa_concretize, qa_verification, qa_finalize, watcher, merge)
- WHEN a user configures the fake for each one with verdicts permitted for that
  type
- THEN the config is accepted; configuring an invalid pairing (e.g.
  `qa_verification` with `PASS`, or any verdict on `impl`/`merge`/`watcher`'s
  catch-all-only types) is rejected at write time with an error listing the
  offending pairs.

### R11 — model_config gains qa_concretize and qa_finalize
- GIVEN the user opens `pm model show`
- WHEN they look at the session-type list
- THEN `qa_concretize` and `qa_finalize` appear as independently
  model-targetable, and `pm model set qa_concretize <model>` succeeds (round
  trips through project.yaml).

### R12 — model_config validation warnings in `pm model show`
- GIVEN the user adds an unknown session-type key or an invalid effort level to
  the `model_config` block of project.yaml
- WHEN they run `pm model show`
- THEN the unknown key / bad effort surfaces as a warning, while previously
  recognised entries are still listed unchanged.

### R13 — Fake writes JSONL transcript + idle hook when given a session id
- GIVEN a poller is waiting on the production verdict-detection path for a
  specific session id
- WHEN the fake is launched with `--session-id <id> --verdict PASS`
- THEN a JSONL file appears under
  `~/.claude/projects/<mangled-cwd>/<id>.jsonl` containing an assistant turn
  with the fake's full text, an `idle_prompt` hook event is written under
  `~/.pm/hooks/<id>.json`, and the poller resolves to `PASS` and the loop
  advances. The fake stays open after writing, simulating a real session in
  its pane, and the hook event is periodically refreshed until the pane is
  killed.

### R14 — Fake without session id exits immediately for verdicts
- GIVEN the user invokes `fake-claude --verdict PASS` directly from a shell
- WHEN the command finishes writing
- THEN the process exits (does not hang) and no transcript/hook files are
  written under `~/.claude` or `~/.pm/hooks` for this invocation.

## Setup
Each scenario starts in a fresh container with the pm repository checked out
to this branch and pm installed via `./install.sh --local`. Scenarios that
exercise the real launch sites also initialise a throwaway pm project + a
session tag so that `~/.pm/sessions/<tag>/fake-claude` is a valid drop point.

## Edge Cases

### E1 — Empty verdicts for catch-all-only session types
GIVEN the user writes a fake-claude config that puts `verdicts` under `_all`.
WHEN the config is written.
THEN the writer warns that `_all` is a no-verdict catch-all and rejects the
write (or strips the verdicts and warns).

### E2 — Block verdict accepted under either short name or end marker
GIVEN the user passes `--verdict FLAGGED_END` (the end-marker form).
WHEN the CLI runs.
THEN it is treated identically to `--verdict FLAGGED` (emits both START and
END markers around the default body).

### E3 — Body delay does not let verdict pollers latch onto stale tokens
GIVEN a fake configured with `--body-lines 20 --body-batch 5 --body-delay 1`
and a verdict at the end.
WHEN a verdict poller watches the session.
THEN the poller only resolves once the trailing verdict actually arrives,
not on any keyword that may incidentally appear earlier in the prose.

### E4 — Stale or absent session config falls back to real Claude
GIVEN no fake-claude config exists for the active session tag.
WHEN a pm flow launches Claude.
THEN the fake is not used; the launch follows the normal path (and surfaces a
real error if Claude is not installed).

### E5 — Hold semantics
GIVEN the user runs `pm fake-claude --verdict NONE` with no `--hold`.
WHEN stdin remains open.
THEN the process blocks until stdin closes; with `--hold 0` it exits
immediately; with `--hold N` it exits after N seconds.

### E6 — Concurrent fake panes share the session config file safely
GIVEN two fake-claude panes are launched simultaneously under the same
session tag (e.g. a watcher pane and a review pane).
WHEN both read the same JSON config and write transcripts/hook events for
distinct session ids in parallel.
THEN each pane's behaviour is correct in isolation, transcripts/hook events
for the two ids do not collide, and the config reader does not race-fail.

### E7 — Multi-pane fake redirect, end-to-end through a loop
GIVEN a review loop set up with a multi-iteration script: review pane
configured to emit `NEEDS_WORK` once then `PASS`, impl pane configured under
`_all`.
WHEN the loop runs.
THEN it advances through the iterations driven entirely by the fake (no real
Claude calls), state transitions match what real verdicts would have caused,
and the loop terminates on the final `PASS`.

## Pass/Fail Criteria
A scenario passes when every THEN clause is directly observable in the
captured artifact (CLI recording / tmux capture / file listing) without
inferring it from source code. It fails if any THEN is contradicted, missing,
or only observable via internal probes the user would not run.

## Ambiguities
None unresolved. Resolutions taken:
- "Common verdicts" in the description → tested via the documented catalogue
  in `SESSION_TYPE_VERDICTS` rather than an arbitrary subset.
- "Streaming" timing → asserted qualitatively (visible pacing in the
  recording) rather than numerically.
- Whether `_all` overrides explicit per-type entries → resolved per code:
  explicit entries win.
- Config-writing surface (R7–R10, E1): there is NO `pm` CLI subcommand that
  writes the fake-claude config. The user-facing surfaces are (a) dropping a
  JSON file at `~/.pm/sessions/<tag>/fake-claude` directly — read verbatim, NOT
  validated; and (b) the documented `paths.set_fake_claude_config(tag, cfg)`
  helper that a test author calls from a setup script — this is the only path
  that validates and raises `ValueError` on bad verdict/session-type pairings
  or `verdicts` under `_all`. Validation-rejection THENs (R10/E1) are therefore
  observed against the helper (the realistic surface for this test-infra
  feature), not a CLI.
- No `pm fake-claude peek` CLI shipped. The proposed peek debug aid exists only
  as the library helper `claude_launcher.peek_fake_verdicts(tag)`; do not plan a
  peek CLI scenario.
- End-to-end loop driver (R7, R13, E7): the lightweight, container-free driver
  is the **review loop** — it launches a Claude pane in a tmux window in the same
  session and polls the verdict via the hook+transcript path, no Docker needed.
  Used for the review-loop redirect scenarios (covered by prior runs).
- Container-mode QA loop driver (R10 verdict surfaces end-to-end): the full QA
  loop (`pm pr qa-run-bg <pr_id>` / TUI `/pr qa <pr_id>`) walks
  planning → concretize → scenario → verification → finalize, spawning a nested
  container per scenario when the `container-enabled` global setting is on.
  Nesting IS supported in this environment (pm runs podman and supports
  podman-in-podman), so the container-mode QA loop is achievable here and is the
  realistic surface for the qa-phase verdicts (qa_planning QA_PLAN,
  qa_concretize REFINED_STEPS/REFINER_REJECT, qa_scenario PASS/NEEDS_WORK,
  qa_verification VERIFIED/FLAGGED, qa_finalize FINALIZE_DONE/FINALIZE_BLOCKED).
  Earlier runs only validated these at config level; this run drives them
  through the live loop. (An earlier note wrongly cited docker-in-docker as a
  blocker — corrected: podman-in-podman works.)
- Container-mode prerequisites (resolved since the 2026-05-21 05:13 run, which
  came back INPUT_REQUIRED because the QA refiner judged the flow undriveable):
  that rejection was caused by two pm bugs that are now FIXED on-branch in
  commit 0597dc1 — (a) the default runtime now auto-detects podman instead of
  hardcoding docker (so `is_container_mode_enabled() and _runtime_available()`
  is true with only podman present), and (b) the nested `podman run` now emits
  `--uts=host`, which skips the `sethostname(2)` syscall that previously failed
  with "Operation not permitted" one container deep. The `--uts=host` flags are
  gated behind a per-project opt-in: the **test project** must set
  `nested_podman: true` under its `project:` block (bootstrap-only project.yaml
  edit, per tui-manual-test.md) before launching the QA loop, otherwise the
  inner `podman run` still dies on `sethostname`. Container mode itself is
  enabled through the normal surface (`pm container enable`). The `pm-dev:latest`
  worker image is present on the host (with auto-build fallback in
  container.py), so image availability is no longer a blocker. Container-mode QA
  loop scenarios are therefore drivable in this run; their STEPS must include
  the `nested_podman: true` opt-in and `pm container enable` as setup.
