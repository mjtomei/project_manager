# Refactor New File Inventory

Companion to [refactor-migration-map.md](refactor-migration-map.md). Lists every NEW file in the proposed `pm_core/` structure with its purpose and contents. Cross-references the plans where each file is specified.

Origin column:
- **NEW** — net-new file with no current source
- **EXTRACTED** — content extracted from one or more existing pm_core files (see migration map for the source set)
- **RENAMED** — single existing file renamed (rare; mostly bootstrap.py and push_proxy.py)

## What's actually new

The refactor adds a typed substrate that pm doesn't have today, organized around three boundaries — the mind (streams, their interactions, lifecycle, supervision), the sensorium (pm's typed slice of the shared world), and cross-mind interaction (a narrow Artifact-mediated layer). What's net-new versus extracted falls roughly along these lines.

**Most genuinely new content lives in three packages.** `pm_core/mind/` introduces a coherent data layer — typed Emissions with visibility tiers and schema versioning, a TagRegistry that catalogs every emission type the system knows about, a typed Channel hierarchy replacing string mailbox names, lifecycle and termination enums, a consolidated `StreamPolicy` collecting per-stream knobs that today live scattered across qa_loop / review_loop / watcher_base / auto_start. `pm_core/runtime/` introduces the RuntimePlugin Protocol — the single execution seam — with concrete implementations for tmux-host, tmux-container, tmux-sandbox, raw-API, managed-agent, hybrid composition, and a fake for testing; Claude CLI flag construction lives here, translated from per-stream capability declarations rather than hand-built at each launch site. `pm_core/supervisors/` introduces the Supervisor Protocol and the concrete loop orchestrators that own per-PR and per-plan multi-stream lifecycles — the loops themselves live here, not in any Stream.

**The Stream subclass framework is also new** even though most of the per-role logic comes from existing files. `pm_core/streams/` introduces a typed Stream base with `__init_subclass__` validation, a `PRActionStream` lifecycle marker, the `InputType` Protocol for typed prompts and messages, and one file per role that co-locates the Stream subclass with its prompt classes. The 25-ish existing roles already exist as code in qa_loop / review_loop / watchers / wrapper-mode dispatch; what's new is the typed family that catches missing registrations at import or in CI rather than at runtime, and a single source of truth for what each role emits and accepts.

**Several entirely new substrates appear** for capabilities pm doesn't have today: `pm_core/payloads/` for typed payload values that flow inside Emissions and prompt inputs (replacing today's dict/string interchange); `pm_core/sensorium/` for typed shared mutable state with schema validation, atomic write, ACL, and change-notify (Artifact, ResourceLease, PathView, CaptureBundle, RedactionPolicy, WorkdirRegistry, PmCommand); `pm_core/collaboration/` for the narrow case where two pm minds want typed Artifact sharing without relying on the public sensorium (ProjectIdentity, PublishedArtifact, three Transport implementations); `pm_core/watchdog/` for typed observability policies; `pm_core/tui/pr_actions/` for the typed TUI bindings paired with PRActionStream subclasses, with a programmatic completeness check; and a top-level `pm_core/mind.py` that defines the singleton Mind class — pm doesn't have a single source of truth for cross-stream state today, and Mind becomes it.

## What's being extracted, and where the deduplication happens

About half the new files extract their content from one or more existing pm_core files. The plans collectively retire ~30 existing files and split their content across the new tree — `bridge.py`'s `_invoke_claude` body absorbs into `raw_api.py` while the socket protocol + `BridgeClient` + `--bridged` flag + `launch_bridge_in_tmux` all delete outright (no external-process control plane survives); `claude_launcher.py` fans into `tmux_host.py` (launch/CLI-flag/registry/binary-discovery) + `_claude_jsonl.py` (transcript-path helpers) + `fake.py` (scripted-verdict subsystem); the four `tech_tree.py` parallel status tables (icons/styles/bg/filter-cycle) + the three independent emoji dicts in `cli/__init__.py`/`cli/helpers.py`/`graph.py` + `tree_layout.status_priority` + `cli/pr.py click.Choice` literal all collapse into one `PR_STATUS_DISPLAY` table co-located with the `PRStatus` enum in `mind/lifecycle.py`; the plan-markdown structure (PR_FIELDS, `### PR:` headings, renderer) collapses from **five** sites (corrected per consolidation audit; the fifth is `plans/review.py:23, 37 REVIEW_PROMPTS` which embeds the same structure) into `sensorium/artifact/_plan_markdown.py` consumed by `PlanArtifact`, `PlanAddStream`, `PlanBreakdownStream`, `PlanImportStream`, AND `PlanReviewStream`; `cli/session.py`'s seven PR-action constants (`_ALL_ACTIONS`, `_MODIFIED_ACTION_CMDS`, `_ACTION_WINDOW_PATTERNS`, `_LIST_ACTIONS`, `_SHORTCUT_FOLD_INTO`, `_STATUS_PHASE`, `_SHORTCUT_KEYS`) + the regex builder + `pr_cleanup.py:14-15` (the actual hardcoded prefix list — corrected per consolidation audit; the earlier-cited `tui/sync.py:22` is a function def with no literal list) + `cli/helpers.py:326-327` + the residual window-name f-string sites in `tui/review_loop_ui.py:79/138/692/899/970`, `tui/pr_view.py:188/210/241`, `qa_loop.py:328/338/360`, `signoff.py:83`, `cli/qa.py:672/721`, `tui/app.py:1409` collapse into `PRActionTUIType` ClassVars (one source for both main-screen keybindings and the prefix+P picker — no string-literal window-name prefix anywhere outside the typed bindings); `review_loop.py` becomes the per-iteration ReviewStream plus the loop orchestration in PRStreamSupervisor; `qa_loop.py` (corrected per consolidation audit; previously said "six per-role Streams") becomes FIVE per-role Streams (planning, scenario, concretize, verification, finalize — regression is NOT sourced from qa_loop.py; it comes from `regression_prompts.py` and lands in a separate `streams/regression.py`) plus the QA fan-out orchestration in PRStreamSupervisor. The bulk of qa_loop.py's content actually fans further — knobs to `mind/policy.py`, transcript helpers to `mind/transcript.py`, typed verdicts/payloads to `payloads/*`, workdir provisioning to `sensorium/workdirs.py`, captures to `sensorium/captures.py`, container launch to `runtime/tmux_container.py`, mocks-author to `streams/qa_author.py` per `_generate_new_mock` / `generate_new_mocks`, and various CLI/model-config helpers to `model_config.py` + `cli/`; `watcher_base.py` + `watcher_manager.py` become the Stream base plus WatcherSupervisor; `prompt_gen.py` (2326 lines) plus the **five** sibling prompt files (corrected per consolidation audit; the fifth is `qa_authoring.py:45 build_authoring_prompt`) distribute into one or more InputType classes per role co-located with the Stream — note that some streams (impl, review) carry a system prompt PLUS follow-on message types, so "one InputType per role" is approximate. `generate_merge_prompt` and `generate_discovery_supervisor_prompt` were previously self-flagged MISSING_FROM_PLAN; their destinations are now explicitly `streams/merge.py::MergeSystemPrompt` and `streams/watchers/discovery_supervisor.py::DiscoverySupervisorSystemPrompt`; `verdict_transcript.py` + `loop_shared.py` split between StreamTranscript helpers, CallbackRegistry semantics, and the shared Claude JSONL codec; `runtime_state.py` folds into EmissionLog + the lifecycle enums + Supervisor state; `store.py`'s flock + WriteQueue + locked_update vanish (graduated into `ProjectYamlArtifact.apply`'s atomic-write + optimistic-version + debounce path — store.py keeps only YAML parse/load); `notes.py`'s load/save_sections vanish similarly (graduated into `NotesSectionArtifact.apply` — notes.py keeps only the section-format parser); `paths.py`'s untyped global-settings KV store becomes `GlobalSettingsArtifact` with a typed schema authored by `model_config.py`; `paths.py`'s `get/set_override_path` becomes `HostOverrideArtifact`; `paths.py`'s fake_claude_config family becomes `FakeClaudeConfigArtifact`; `hook_install.py`'s settings.json mutation becomes `ClaudeHooksArtifact` (with `TmuxHostRuntime` owning only the policy of which hooks to install); `plans/parser.py` deletes entirely — its parser body folds into `PlanArtifact.parse_prs()` consuming `PlanMarkdownSchema`. The migration map has the per-responsibility detail; what's worth flagging here is the deduplication these extractions enable.

**The single most repeated pattern in today's codebase is verdict-keyword knowledge** — what tags exist, what each role is allowed to emit, how to parse them out of a chat stream. Today this lives in five places that drift independently: `fake_claude.SESSION_TYPE_VERDICTS` (a dict), each watcher's `VERDICTS` tuple plus its `parse_verdict()` regex, scattered per-prompt instructions telling Claude what to write, ad-hoc grep across pane buffers in qa_status / review_loop_ui, and pr-1d8b2b7's partial VerdictRegistry attempt. The refactor consolidates this to one TagRegistry plus per-InputType `ALLOWED_VERDICTS` class attributes; FakeClaudeRuntime derives its scripted set from those rather than maintaining a parallel registry, and the boundary-aware match logic lives once on `StreamTranscript.latest_verdict()` instead of being reimplemented in each watcher.

**Shared prompt fragments are the next-largest dedup.** About ten reusable text blocks — `tui_section`, sync tips, beginner addendum, filing addendum, out-of-scope-bugs, signoff QA scenarios block, manual-testing guidance, notes-for-prompt, mocks-for-prompt, spec-generation preamble — appear copy-pasted across 5+ prompt builders in `prompt_gen.py` today. They consolidate to one `streams/_shared_prompts.py` module that the per-role InputType classes import.

**File-level mutex and resource coordination consolidate for the resources that pm orchestrates across streams.** `ResourceLease` covers: `signoff.py`'s per-PR launch lock (→ `TmuxWindowKey` lease); workdir provisioning's per-PR clone lock at `cli/helpers.py:565, 717-744, 748 _clone_workdir` (→ `WorkdirKey` lease); `qa_loop.py`'s tmux-window-name collision dedup (→ `TmuxWindowKey` lease); branch-ref mutexes for merge/push (→ `BranchRefKey`); container-name dedup at `container.py` (→ `ContainerKey`); future champion-of-target / leader-election slots (→ `ChampionSlotKey` / `LeaderSlotKey` — currently aspirational, no extant code). One `reconcile()` classmethod sweeps stale leases on Supervisor startup, complementing today's `_cleanup_stale_scenario_windows` and the catch-all `pr_cleanup` sweep.

**Explicitly NOT routed to ResourceLease — fcntl sites whose semantics belong elsewhere.** The audit (consolidation round) found seven flock sites that this claim could be misread to absorb; each routes elsewhere per the migration map: `store.py` `_lock`/`locked_update`/`StoreLockTimeout` STAYS in `store.py` (its callers go through `ProjectYamlArtifact.apply` debounce path, but the underlying fcntl on project.yaml stays); `runtime_state.py:55, 92, 129` per-PR action-state flock → `mind/log.py` (EmissionLog append-only file); `review/md_writer.py:11-61` flock → `sensorium/artifact/base.py` (Artifact atomic write); `pane_registry.py:8-98` flock STAYS as foundational TUI substrate; `claude_launcher.py:89-125` session-type advance flock → `runtime/tmux_host.py`'s session-id registry; `tui/app.py:1104-1118` cmd-queue flock STAYS in app.py; `cli/helpers.py:565` second flock site → covered by the workdir-clone lease above. These distinctions matter because flipping one of them to `ResourceLease` would break invariants the receiving destination relies on (append-only ordering for EmissionLog, atomic-write semantics for Artifact, etc.).

**Workdir provisioning** is a third focused dedup — `_ensure_workdir` in `cli/helpers.py`, `_clone_workdir` in `cli/pr.py`, per-scenario clone setup in `qa_loop.py`, and cross-workdir overlap stash/unstash around merges all centralize in `sensorium/workdirs.py` as `WorkdirRegistry` + typed `Workdir` / `ScenarioWorkdir` subclasses.

**Mode-toggle / INPUT_REQUIRED / human-takeover semantics** appear across SEVEN subsystems today (corrected per consolidation audit; previously stated as four): `bridge.py`'s AGENT/HUMAN mode toggle (driven by socket commands from an external process); `review_loop.py`'s INPUT_REQUIRED stalling at `:317-333` + repeated-INPUT_REQUIRED demotion at `:337`; `watcher_base.py`'s INPUT_REQUIRED stalling at `:303-378` + demotion at `:354`; `qa_loop.py`'s per-iteration INPUT_REQUIRED-as-verdict at 10 sites (`:1615, 1854, 2130, 2211, 2326, 2366, 2382, 3199, 3239, 3418`); `runtime_state.py:270-292`'s `request_suppress_switch / consume_suppress_switch` (the actual implementation — `qa_loop_ui.py` is only a consumer); `cli/session.py:1511, 1556` third suppress_switch consumer; `tui/review_loop_ui.py`'s `_handle_merge_input_required` (map:2239). These collapse into `AttentionService` + `AttentionRequest` + `ControlOwner` **for loop-level human stalls** plus `StreamPolicy.max_consecutive_attention_requests` **for the demotion logic**. Per-scenario INPUT_REQUIRED inside qa_loop is NOT an AttentionRequest — those route to `QaVerificationStream` / `PRStreamSupervisor` as typed Emissions. Bridge's socket-driven path doesn't survive — humans take over via the TUI raising an AttentionRequest, not via an external process toggling a mode flag.

**Claude Code's on-disk JSONL transcript format** is touched by today's `claude_launcher.py` (transcript-path / session-id helpers — the *primary* source) and `verdict_transcript.py` (record-shape parsing only — `extract_verdict_from_transcript` and `read_latest_assistant_text` route to `mind/transcript.py` and `runtime/hook_entry.py`, NOT this codec). These merge to one private `_claude_jsonl.py` codec shared between `TmuxHostRuntime` (read) and `FakeClaudeRuntime` (write). The codec scope is strictly record-shape + on-disk path conventions; verdict extraction and assistant-text scraping are higher-layer concerns owned by `StreamTranscript`.

**Restart and resume markers** scatter today across a merge-restart marker file (`auto_start.py` + `tui/sync.py`), `qa_resume.json` (qa_loop), per-watcher state files, and ad-hoc breadcrumbs. All retire in favor of EmissionLog replay — `MindSupervisor.startup()` reconstitutes pre-restart state from the durable log.

**TUI keybindings, glyphs, and window naming** today live as a hardcoded tuple of bindings in `pm_core/tui/app.py` that must be kept in sync by hand with the action set — exactly the convention-not-type failure mode plan-quality flagged. They consolidate into the typed `PRActionTUIType` hierarchy with a programmatic completeness check that fails CI if a binding is missing for any PRActionStream subclass.

**YAML-frontmatter parsing** today exists as exactly one `---`-delimited parser at `qa_instructions.py:71-91 _parse_frontmatter` (corrected per consolidation audit — earlier wording named six sources, most of which were aspirational). `_frontmatter.py` collapses that one site while standing up the shared helper for FUTURE consumers (PlanArtifact, SpecArtifact, RadarItemArtifact, walker_ui artifacts) so their first implementations don't reintroduce per-artifact parsers. `review/md_parser.py:21-37` parses YAML inside fenced code blocks (a different shape — its `_StringTimestampLoader` stays private and routes to `walker_ui.py`); `spec_gen.py`'s `---` is a prompt-template separator, not frontmatter; plan files have no frontmatter today.

**Hand-built pm CLI shellouts** scatter across many sites as `subprocess.run(['pm', 'pr', 'start', ...])` calls. They consolidate into a typed `PmCommand` hierarchy auto-generated from pm's argparse/Click definitions (CI-enforced lock-step), so streams call into pm's surface through typed value objects instead of stringly-typed argv arrays.

The net effect is that adding a new role, a new emission type, a new editable artifact, or a new pm CLI command becomes a single typed change in one obvious place — and forgetting any required attachment (verdict registration, fake-runtime script, TUI binding, schema declaration) becomes a structural failure rather than a silent drift bug.

## Contents

1. [`pm_core/mind/`](#pm_coremind) — mind primitives (was `pm_core/agent/`)
2. [`pm_core/runtime/`](#pm_coreruntime) — RuntimePlugin Protocol + concrete impls
3. [`pm_core/streams/`](#pm_corestreams) — Stream subclasses + co-located InputType prompts
4. [`pm_core/payloads/`](#pm_coreartifacts) — typed Payload payload subclasses
5. [`pm_core/supervisors/`](#pm_coresupervisors) — Supervisor Protocol + concrete loop orchestrators
6. [`pm_core/watchdog/`](#pm_corewatchdog) — typed WatchdogPolicy
7. [`pm_core/sensorium/`](#pm_coresensorium) — sensorium primitives + on-disk Artifact subclasses
8. [`pm_core/collaboration/`](#pm_corecollaboration) — cross-mind substrate
9. [`pm_core/tui/pr_actions/`](#pm_coretuipr_actions) — typed TUI bindings for PR actions
10. [Top-level files](#top-level-files) — `mind.py`, `bootstrap.py`

---

## `pm_core/mind/`

The inert mind primitives — the data layer streams and supervisors compose. Was `pm_core/agent/` pre-refactor. Plan: [plan-mind](plan-mind.md).

### `pm_core/mind/__init__.py`
NEW. Re-exports the primary types (`Emission`, `EmissionLog`, `Stream`, `Mailbox`, `CallbackRegistry`, `AttentionRequest`, `Channel`, …) so callers can `from pm_core.mind import …`.

### `pm_core/mind/emissions.py`
NEW. `Emission` envelope dataclass: `tag`, `payload`, `stream_id`, `correlation_id`, `ts`, `visibility: VisibilityTier`, `schema_version: str`, `dedup_key: Optional[str]`. Frozen. `log_ref()` helper. The only currency of inter-stream communication.

### `pm_core/mind/log.py`
EXTRACTED (from `runtime_state.py` action-state flock JSON + `pm/watchers/<name>.log` ad-hoc storage). `EmissionLog`: SQLite-backed at `pm/.mindlog.db`. Methods: `append(Emission) -> LogRef` (idempotent on `(stream_id, tag, correlation_id)` primary key), `query(tags, since, where, last_n)`, `latest(tag)`, `slice(ref, around)`. Read-accessible from short-lived external processes (popup picker, status spinner, `home_window/`). New helper: `pm log emissions` CLI subcommand reads this.

**Note on what does NOT come from `verdict_transcript.py`** (corrected per consolidation audit): `verdict_transcript.py`'s body routes mostly to `StreamTranscript` (mind/transcript.py) + `runtime/hook_entry.py` for verdict emission; only its structural-event-log subset (if any survives) lands here. `runtime_state.py` itself fans into FIVE destinations, of which EmissionLog is the largest — see the `mind-pkg-migration` note below for the complete list (`mind/log.py`, `mind/lifecycle.py`, `mind/attention.py`, `runtime/tmux_host.py`, `payloads/failure_reason.py`).

### `pm_core/mind/transcript.py`
EXTRACTED (from `verdict_transcript.py` JSONL-text scraping + `loop_shared.py:45 match_verdict` boundary-aware matcher + bridge.py per-turn streaming chunks). `StreamTranscript`: flat per-stream append-only files at `pm/.transcripts/<stream_id>.log`. Methods: `append(ChatChunk) -> TranscriptRef`, `read(since, until)`, `tail(n)`, `grep(pattern, regex, after_lines, before_lines)`, `slice(start, end)`, `ref_at(ts)`, `latest_verdict(allowed: set[str])` (the boundary-aware verdict-keyword matcher absorbed from `loop_shared.match_verdict`). pm-owned; NOT derived from Claude Code's internal JSONL — the JSONL record-shape parsing lives in `runtime/_claude_jsonl.py` and never leaks past the runtime boundary, while bridge.py's per-turn streaming I/O parsing goes to `RawApiRuntime`. Only the plain-text + boundary-aware-matcher subset lands on StreamTranscript.

### `pm_core/mind/mailbox.py`
EXTRACTED (bridge.py's busy/ack signal — the only existing message-passing primitive in pm) + NEW (named channels, ACLs, tag-glob subscriptions, visibility-aware routing). `Mailbox`: named channel with `allowed_posters`/`allowed_subscribers` ACL + visibility-aware routing. Methods: `post(out, deliver: 'preempt'|'next-checkpoint', supersedes)`, `subscribe(handler, tag_glob)`, `stream(filter_tag)`, `latest(tag)`, `list_glob(pattern)`. In-process default; future Redis-backed for cross-process.

**On what does NOT migrate here.** The audit (consolidation round, G3) flagged that earlier wording credited "watcher inter-process state" as a source — incorrect. `watcher_base.py:68` + `watcher_manager.py:25` use `threading.Lock` + stop flags only (in-process); they have no inter-process state to extract. The genuine cross-process channel in pm today is bridge.py's Unix socket, which DELETES outright (no replacement) — `Mailbox` is in-process by default and reaches cross-process only via a future Redis backend. `runtime_state.py:55, 92, 129` is the only flock'd JSON file pm has today, and it correctly routes to `EmissionLog` (mind/log.py), not `Mailbox`.

### `pm_core/mind/callbacks.py`
EXTRACTED (from `loop_shared.poll_for_verdict` + `idle_prompt` + per-watcher polling). `CallbackRegistry`: `on(tag, handler, from_stream, where, once, deliver)`, `wait_for(tag, *, from_stream, not_before, predicate, grace_period, timeout)`, `cancel(cb)`. Once-per-`(stream_id, tag, correlation_id)` handler semantics.

### `pm_core/mind/attention.py`
EXTRACTED (from bridge.py mode toggle + INPUT_REQUIRED loop-stall handling at `review_loop.py:317-333` and `watcher_base.py:303-378` + suppress_switch impl at `runtime_state.py:270-292` consumed by `qa_loop_ui.py` + `cli/session.py:1511,1556` + `tui/review_loop_ui.py _handle_merge_input_required`). `AttentionService` + `AttentionRequest`. Reserved tag prefix `request.user-attention.*`. Methods: `raise_(tag, payload, blocking, reply_to, expires_at)`, `await_resolution(att)`, `resolve(att, reply)`. Auto-cancels outstanding requests when the holder Stream transitions to terminal `LifecycleState`, emitting `attention.abandoned`. Suppress-switch / focus-steal cancellation modeled as short-lived `AttentionRequest` with `ControlOwner=tui_user` + TTL. **Demotion** (`review_loop.py:337` / `watcher_base.py:354` "repeated INPUT_REQUIRED → READY/NEEDS_WORK fallback") routes to `StreamPolicy.max_consecutive_attention_requests` + `repeated_attention_action`, not to AttentionService itself. **Per-scenario INPUT_REQUIRED** inside qa_loop (10 sites listed in the consolidation paragraph above) is a typed verdict Emission on `QaVerificationStream`, not an AttentionRequest.

### `pm_core/mind/tags.py`
EXTRACTED (absorbs `pr-1d8b2b7` VerdictRegistry). `Tag` dataclass: `name`, `payload_schema: type[Payload]`, `source_role: type[Stream]`, `schema_version: str = '1'`, `default_loop_mode: LoopMode = LoopMode.continue_existing`. `TagRegistry`: class-level `tags: dict[str, Tag]`, `register(tag)`, `lookup(name)`, `for_role(role)`. Pre-registers all today's verdict tags at PR1. `LoopMode` StrEnum (`continue_existing | kill_restart`).

### `pm_core/mind/channels.py`
NEW. `Channel` base + value-object subclasses: `PRChannel(pr_id, kind)`, `ScenarioChannel(pr_id, scenario_idx, kind)`, `LifecycleGlobalChannel()`, `AttentionGlobalChannel()`, `ArtifactChangeChannel(artifact_name)`, `LeaseChannel(key: ResourceKey)`, `CaptureChannel(test_id)`, `TUICommandChannel()` (file-backed; subscribers are local-process readers). Each renders to a string via `name()`; consumers always construct the typed object, never raw strings.

### `pm_core/mind/lifecycle.py`
EXTRACTED (PRStatus from `pr_utils.py` + termination states scattered across `runtime_state.py`/`watcher_base.py` + status icon/style/priority tables collapsed from `cli/__init__.py`, `cli/helpers.py`, `graph.py`, `tech_tree.py`, `tree_layout.py`). Enums: `LifecycleState` (`never_started | queued | running | hibernated | terminated`), `TerminationReason` (`completed_normally | user_killed | cancelled | timed_out | crashed | oom | network_lost | budget_exhausted | paywall_inaccessible | model_refusal`), `VisibilityTier` (`private | user_internal | public` with parameterized `Party(project_id)`), `PRStatus` (`pending | in_progress | in_review | qa | signoff | blocked | merged | closed`; adds `blocked` as a first-class member — today only `cli/helpers.py:262-271` knows about it), `ControlOwner` (`agent | human`).

Also owns the single source of PR-status display + lifecycle helpers consumed everywhere else: `PRStatus.is_terminal()` classmethod + `TERMINAL_PR_STATUSES: frozenset[PRStatus] = {PRStatus.merged, PRStatus.closed}` (replaces `cli/session.py:953 _TERMINAL_STATUSES` + four inline `{"merged","closed"}` checks in `qa_loop.py` + `home_window/pr_list.py:156`); `PRStatusDisplay` frozen dataclass with `glyph` (terminal-safe unicode for TUI), `emoji` (rich CLI), `fg`/`bg` (Textual styles), `sort_priority` (tree-layout ordering); `PR_STATUS_DISPLAY: dict[PRStatus, PRStatusDisplay]` with one row per enum member, asserted exhaustive at module load (`set(PR_STATUS_DISPLAY) == set(PRStatus)`); `STATUS_FILTER_CYCLE: tuple[PRStatus | None, ...] = (None, *PRStatus)`. The four parallel tables in `tech_tree.py` (STATUS_ICONS, STATUS_STYLES, STATUS_BG, STATUS_FILTER_CYCLE), the emoji dicts in `cli/__init__.py`/`cli/helpers.py`/`graph.py`, the `tree_layout.status_priority` map, and the `cli/pr.py:315-316 click.Choice` literal all become reads from this module.

### `pm_core/mind/policy.py`
EXTRACTED (consolidates per-stream knobs scattered across qa_loop, review_loop, watcher_base, auto_start). `StreamPolicy` dataclass: `persistence: list[str] = ('keep-warm', 'log-replay')`, `budget: Optional[BudgetPolicy]`, `cascade_on_parent_terminate: bool`, `loop_mode_overrides: dict[str, LoopMode]`, `takeover: TakeoverBufferPolicy`, `stop_before_merge: bool`, `consecutive_pass_threshold: int`, `max_iterations: Optional[int]` (None = unlimited; positive int = cap; 0 is illegal — rejected at construction. Audit NG-3 fix; replaces watcher_base.py's silent `0=unlimited` sentinel.), `remind_on_grace: Optional[tuple[InputType, timedelta]]`, `max_consecutive_attention_requests: int`, `repeated_attention_action: Literal['demote','terminate','raise_to_user']`, `trust_runtime: TrustLevel`, `auto_approve_spec: bool`, `allowed_tools: Optional[list[str]]`, `model: Optional[str]`. Also `BudgetPolicy(max_tokens, max_usd, max_wallclock, scope)`, `UsageEvent` Payload, `TakeoverBufferPolicy(on_overflow, max_buffered, bypass_tags)`.

---

## `pm_core/runtime/`

The single execution seam. Each RuntimePlugin implementation owns Claude CLI flag construction for its concrete runtime; Streams declare requirements via `required_capabilities` and `StreamPolicy.trust_runtime` and the runtime translates. Plan: [plan-mind](plan-mind.md).

### `pm_core/runtime/__init__.py`
NEW. Re-exports `RuntimePlugin`, the concrete runtime classes, and `RuntimeCapabilities`.

### `pm_core/runtime/protocol.py`
NEW. `RuntimePlugin` Protocol: `instantiate(stream_id, system_prompt) -> RuntimeInstance`, `send_input(instance, payload)`, `on_output(instance, handler) -> SubId`, `poll_outputs(instance) -> list[Emission]`, `terminate(instance)`, `capabilities() -> RuntimeCapabilities`, `focus(instance)` (for runtimes with a display surface). **No `snapshot()` method, no `snapshot=` instantiate param** — wrapper does not depend on runtime-internal snapshot/resume. `RuntimeCapabilities` dataclass: `interactive_tty`, `repo_mount`, `shell_exec`, `supports_hooks`, `supports_poll`, `reports_cost`, `network_egress`, `sandboxed_bash`, `max_inline_input_bytes`, `attach_hint`.

### `pm_core/runtime/tmux_host.py`
EXTRACTED (from `claude_launcher.py` launch/CLI-flag/session-registry/binary-discovery surface + `pane_idle.py` + `hook_install.py` runtime parts). `TmuxHostRuntime`: wraps today's `launch_pane`. Owns Claude CLI flag construction (translates `Stream.required_capabilities` + `StreamPolicy.trust_runtime/model/allowed_tools` into `--dangerously-skip-permissions`, `--model`, `--allowedTools`, etc. — mapping table documented inline). Owns `find_claude / find_editor / _skip_permissions / _resolve_provider` and the session-id registry (`load_session / save_session / clear_session`). Uses `tmux.py` + `tui/pane_layout.py` + `tui/pane_registry.py` substrate. Pane lifecycle = runtime lifecycle. Reads Claude Code's internal JSONL via `_claude_jsonl.py` shared codec. `focus()` calls `tmux select-window`. **`claude_launcher.py` deletes entirely as part of this extraction** — its transcript-path helpers go to `_claude_jsonl.py`, its fake-claude scripted-verdict subsystem goes to `runtime/fake.py`, and `launch_bridge_in_tmux` deletes outright with the bridge subsystem.

### `pm_core/runtime/tmux_container.py`
EXTRACTED (from `container.py`). `TmuxContainerRuntime`: pm-managed Docker per plan-qa. Wraps today's container.py + per-PR Docker glue. Consumes `push_proxy.py`. Same Claude CLI surface as TmuxHostRuntime; difference is isolation.

### `pm_core/runtime/tmux_sandbox.py`
NEW. `TmuxSandboxRuntime`: wraps `@anthropic-ai/sandbox-runtime` (Anthropic's Seatbelt/bubblewrap sandbox). Same tmux UX as TmuxHostRuntime with deny-by-default filesystem + network isolation, no Docker required.

### `pm_core/runtime/raw_api.py`
EXTRACTED (from `bridge.py`'s `_invoke_claude` body — the per-tick SDK call + stream-json I/O parsing only). `RawApiRuntime`: headless loop over the Anthropic SDK. No tmux, no isolation beyond the host. Per-stream session-id continuity. Use case: wake-on-callback ticks where no human is attached.

*Note on what does NOT survive from bridge.py:* the Unix-socket JSON command surface (status / take_control / release_control / send) and `BridgeClient` delete outright — pm has no external-process control plane after this refactor. The only consumer (`cli/cluster.py --bridged` flag + `launch_bridge_in_tmux`) also deletes; cluster_exploration uses `RawApiRuntime` directly when programmatic control is wanted. Human takeover, which today flows via socket commands, flows via `AttentionService` + `ControlOwner` — humans take over via the TUI, not via an external process.

### `pm_core/runtime/managed_agent.py`
NEW. `ManagedAgentRuntime`: Anthropic Managed Agents (April 2026 release). Two sub-variants: cloud sandbox (Anthropic-hosted gVisor container) and self-hosted sandbox (pm provides an environment worker). Headless from pm's perspective; interaction via Managed Agents' polling/webhook contract.

### `pm_core/runtime/hybrid.py`
NEW. `HybridRuntime`: composes two runtimes under one `Stream` id (e.g. `TmuxHostRuntime` for interactive when a human is attached, `RawApiRuntime` for headless wake-ups, sharing one log).

### `pm_core/runtime/fake.py`
EXTRACTED (from `fake_claude.py` + the scripted-verdict subsystem of `claude_launcher.py`: `_fake_claude_config_for_type / _pick_fake_verdict / _clamp_cursor / _advance_scripted_cursor / _resolve_fake_verdict / _fake_claude_args / peek_fake_verdicts` + `paths.py`'s fake_claude_config family per migration-map L1382: `fake_claude_config`, `set_fake_claude_config`, `clear_fake_claude`, plus the `fake-claude` / `fake-claude.state` filename constants which move to `pm_core/_path_constants.py`). `FakeClaudeRuntime`: test impl. Today's `FakeClaudeSession` scripted-verdict machinery maps directly. Derives its scripted-verdict set from each `InputType.ALLOWED_VERDICTS` rather than maintaining a parallel `SESSION_TYPE_VERDICTS` dict. Writes Claude-format JSONL via the shared codec so TmuxHostRuntime can test against it.

### `pm_core/runtime/_claude_cli_flags.py`
NEW. Private shared helper owning Claude CLI flag construction. Single function `build_claude_argv(*, claude_bin, system_prompt, model, effort, allowed_tools, skip_permissions, resume, input_format, extra) -> list[str]` consumed by `TmuxHostRuntime` (foreground/tmux/print launchers) AND `RawApiRuntime` (`_invoke_claude` body). Replaces today's 5+ independent argv builders in `claude_launcher.py` + `bridge.py` (audit NG-2). No other module spells out `--dangerously-skip-permissions` / `--model` / `--effort` / `--resume` / `--input-format stream-json` after this PR. Snapshot test `tests/test_claude_cli_flags.py` pins the argv shape for each capability combination; renaming a flag updates one place.

### `pm_core/runtime/_claude_jsonl.py`
EXTRACTED (from `claude_launcher.py`'s transcript-path/session-id helpers: `transcript_path_for / session_id_from_transcript / _claude_project_dir / finalize_transcript / _parse_session_id`) + parts of `verdict_transcript.py`'s JSONL parsing. Private shared codec for Claude Code's on-disk JSONL transcript format. Used by `TmuxHostRuntime` (reads) and `FakeClaudeRuntime` (writes). Single reader/writer pair avoids format drift. No public API outside `pm_core/runtime/`. The JSONL format never leaks past this module into mind primitives — `StreamTranscript.latest_verdict` operates on plain text via the boundary-aware verdict-keyword scanner.

### `pm_core/runtime/hook_entry.py`
EXTRACTED (from `hook_receiver.py` + the receiver-script-payload + sweep portion of `hook_install.py`; **the bulk of `hook_install.py` actually moves to `runtime/tmux_host.py` and `runtime/tmux_container.py`** — only the entry-script body lands here). Shippable CLI invoked by Claude Code hooks from `~/.claude/settings.json`. Forwards events to the appropriate RuntimePlugin handler in the running pm process. Installable via `console_scripts: pm-hook-receiver`.

### `pm_core/runtime/push_proxy.py`
RENAMED (from `pm_core/push_proxy.py`). ~870 LOC git-push-proxy daemon. PushProxy server, `resolve_real_origin`, shared-socket lifecycle, `__main__`. Consumed by `TmuxContainerRuntime` for per-container push redirect.

### `pm_core/runtime/reentry.py`
NEW. Handles pm-self-reentry hidden CLI flags for pm subprocesses re-entering itself. Two flag sets consolidate here (corrected per consolidation audit; earlier wording named only the cli/pr.py set):
- From `cli/pr.py`: `--background`, `--transcript`, `--origin`, `--propagation-only` (detached launches, supervisor sub-invocations, merge propagation step).
- From `cli/watcher.py:84-93`: `--transcript`, `--auto-start-target`, `--meta-pm-root`, `--watcher-type`, and the `--iteration N` re-entrant pattern (the latter was previously self-flagged at migration-map GAP-14 as unresolved; this PR resolves it by absorbing the iteration counter into `WatcherSupervisor` + `TmuxHostRuntime`'s in-process loop, so the `--iteration N` flag itself can DELETE rather than relocate).
`bootstrap.py` dispatches between hook-receiver / pm-reentry / normal modes; `runtime/reentry.py` owns the post-dispatch flag parsing.

---

## `pm_core/streams/`

One file per role. Each file contains the `Stream` subclass AND its co-located `InputType` (system prompt + any message types). Cross-stream reusable text fragments in `_shared_prompts.py`. Plan: [plan-mind](plan-mind.md).

### `pm_core/streams/__init__.py`
NEW. Imports every role module so `PRActionStream.__subclasses__()` returns the complete set for the TUI completeness check.

### `pm_core/streams/_protocol.py` (or in `base.py`)
NEW. `InputType` Protocol: `kind: 'system'|'message'`, `inputs: type` (dataclass), `schema_version: str`, `ALLOWED_VERDICTS: set[str]`, `render(inputs) -> str`, `required_capabilities() -> set[str]`, optional `upgrade(prior_payload, prior_version)` migration hook.

### `pm_core/streams/_shared_prompts.py`
EXTRACTED (from `prompt_gen.py`'s reused text blocks). Cross-stream reusable text fragments: `tui_section`, `sync_tips`, `beginner_addendum`, `filing_addendum`, `out_of_scope_bugs`, `signoff_qa_scenarios_block`, `manual_testing_guidance`, `notes_for_prompt`, `instruction_summary_for_prompt`, `mocks_for_prompt`, `spec_generation_preamble`, `format_spec_for_prompt`, `extract_between_markers`.

Also owns the shared **phase-label vocabulary** (audit round-3 gap): `class Phase(StrEnum)` with members `impl`, `qa` (extensible — `review`, `merge`, `signoff` if other prompt builders need them), each exposing `.prose` ("implementation" / "QA") and `.heading` ("Implementation Spec" / "QA Spec") via mapped properties. Consumed by both `prompts/spec_gen.py::_build_spec_prompt` (today's `spec_gen.py:507-508` `{"impl": "implementation", "qa": "QA"}` dict) and `prompts/_shared.py::format_spec_for_prompt` (today's `spec_gen.py:692-696` `{"impl": "Implementation Spec", "qa": "QA Spec"}` dict). The two dicts collapse into one source; the round-3 audit noted that splitting the two helpers across files actually made the duplication harder to spot post-refactor — the `Phase` enum prevents that. CI grep test forbids `"implementation"` / `"Implementation Spec"` / `"QA Spec"` string literals in prompt builders outside this module.

### `pm_core/streams/base.py`
NEW. `Stream` base class with `__init_subclass__` validating required ClassVars (`input_type`, `output_emissions`, `required_capabilities`, optional `fake_runtime_script`). Methods: `emit`, `deliver_message(message, inputs, deliver)`, `resume`, `hibernate`, `subscribe`, `on`, `request_attention`, `spawn_child`, `cancel`, `on_cancel`, `request_human_takeover`, `release_human_takeover`, `status() -> LifecycleState`, `focus()` (delegates to runtime). Persistence chain `keep-warm → log-replay`. `loop_mode_overrides: ClassVar[dict[str, LoopMode]]` for per-tag overrides.

### `pm_core/streams/pr_action.py`
NEW. `PRActionStream(Stream)` base with required ClassVar `pr_lifecycle_state: PRStatus`. No TUI fields — those live in `pm_core/tui/pr_actions/`.

### `pm_core/streams/impl.py`
EXTRACTED (from `prompt_gen.py:140 generate_prompt` (the impl/work-session prompt — NOT a `generate_impl_prompt` symbol, which doesn't exist; corrected per consolidation audit) + `spec_gen.py generate_spec` orchestration + the impl-window launch path at `cli/pr.py:976 _launch_review_window` + `_add_companion_pane`). `ImplStream(PRActionStream)` + `ImplSystemPrompt(InputType)` + `ImplReviewFeedbackMessage(InputType)` + `ImplSpecPrompt(InputType)` (internal variant used during the spec-gen sub-phase). Note that this stream class hosts TWO InputType classes (the system prompt and the review-feedback message) — `streams/impl.py` and `streams/review.py` are examples where the "one InputType per Stream" framing in the top-of-file summary is approximate; some streams legitimately need a system prompt plus follow-on message types. Lifecycle: spec-gen phase → AttentionRequest if not auto-approved → impl phase → commits. Emits `phase.impl.spec-proposed`, `phase.impl.spec-approved`, `impl.lifecycle.commit-landed`, `impl.lifecycle.ready-for-review`, `note.impl.design-choice`, `request.user-attention.spec-approval-needed`.

### `pm_core/streams/review.py`
EXTRACTED (`review_loop.py` actually fans across ~7 destinations — this file owns ~4 of the original 16 symbols). `ReviewStream(PRActionStream)` + `ReviewSystemPrompt(InputType)` (the `prompt_gen.generate_review_prompt` body lands here; the system prompt class lives in this same `streams/review.py` file — the earlier ambiguous "review_system.py" was not a new file, just an alternate name floated for the class). `loop_mode_overrides = {'review.requested': LoopMode.kill_restart}` — each iteration is a fresh stream. Reads diff via `GitDiffAtSha` Payload. Emits `verdict.review.pass`, `verdict.review.needs-work`. Per-iteration; PRStreamSupervisor drives the loop.

**review_loop.py fan-out beyond this file** (per consolidation audit): window naming + launch → `runtime/tmux_host.py`; `_poll_for_verdict` + `_VERDICT_GRACE_PERIOD` → `mind/callbacks.py::CallbackRegistry.wait_for(grace_period=)`; `_wait_for_follow_up_verdict` → `mind/attention.py`; `should_stop` + `max_iterations` → `mind/policy.py::StreamPolicy`; `start_review_loop_background` → `supervisors/pr_stream.py`; `PaneKilledError` → `mind/lifecycle.py`; `ReviewIteration` event → `mind/emissions.py`.

### `pm_core/streams/qa_planning.py`
EXTRACTED (from `qa_loop.py` planner phase). `QaPlanningStream(PRActionStream)` + `QaPlanningSystemPrompt(InputType)`. Phase-gen for QA spec → optional approval → emits `phase.qa-plan.complete` with list of `QAScenarioRef`s.

### `pm_core/streams/qa_scenario.py`
EXTRACTED (from `qa_loop.py` per-scenario). `QaScenarioStream(PRActionStream)` + `QaScenarioSystemPrompt(InputType)`. One instance per (pr, scenario_idx). Emits `verdict.scenario.pass`/`verdict.scenario.fail`/`request.user-attention.*`.

### `pm_core/streams/qa_concretize.py`
EXTRACTED (from `qa_loop.py` refiner). `QaConcretizeStream` + `QaConcretizeSystemPrompt`. Refines abstract scenarios to concrete steps with mock spec resolution.

### `pm_core/streams/qa_verification.py`
EXTRACTED (from `qa_loop.py` verifier). `QaVerificationStream` + `QaVerificationSystemPrompt`. Reads scenario worker's transcript via `TranscriptSlice`, independently re-executes assertions. Emits `verdict.qa-verify.verified` / `verdict.qa-verify.refuted`.

### `pm_core/streams/qa_finalize.py`
EXTRACTED (from `qa_loop.py` finalize + `qa_finalize_prompt.py`). `QaFinalizeStream` + `QaFinalizeSystemPrompt`. Aggregates per-scenario verdicts, runs cleanup + push.

### `pm_core/streams/qa_author.py`
EXTRACTED (from `qa_authoring.py`). `QaAuthorStream` + `QaAuthoringSystemPrompt`. Interactive scenario authoring under TmuxHostRuntime.

### `pm_core/streams/qa_regression.py`
EXTRACTED (from `qa_loop.py` regression flavor + `regression_prompts.py`). `QaRegressionStream` + `QaRegressionSystemPrompt` + `BugReproduceMessage`. Interactive authoring with coverage claims posted to a shared mailbox.

### `pm_core/streams/signoff.py`
EXTRACTED (from `signoff.py` — but most of `signoff.py` fans elsewhere; this stream owns only the agent-facing system prompt + emission contract). `SignoffStream(PRActionStream)` + `SignoffSystemPrompt`. Two internal evaluations (evidence-supports-diff, anti-shortcut/meta-QA). Reads `QaStatusArtifact` for evidence pane. Emits `verdict.signoff.merge`/`verdict.signoff.needs-work`.

**signoff.py fan-out beyond this file** (corrected per consolidation audit): `record_signoff_verdict` → `sensorium/artifact/project_yaml.py::ProjectYamlArtifact` (PR-record write); `fcntl launch lock` → `sensorium/leases.py::TmuxWindowKey` lease; container-mode handling → `runtime/tmux_container.py`; `_BOUNCE_HOP_STATUS` + `decide_signoff_hop()` + `apply_signoff_hop()` → `supervisors/pr_stream.py::PRStreamSupervisor` verdict-routing; `head_sha()` git helper DELETES (callers use `git_ops`). So named destinations are `[SignoffStream, SignoffSystemPrompt, ProjectYamlArtifact.record_signoff_verdict, TmuxWindowKey lease, TmuxContainerRuntime, PRStreamSupervisor.signoff_routing]`.

### `pm_core/streams/merge.py`
EXTRACTED (from `signoff.py` merge resolver + `cli/pr.py` merge flow + `prompt_gen.generate_merge_prompt`). `MergeStream(PRActionStream)` + `MergePropagationStream` + `MergeConflictResolverStream` + `MergeSystemPrompt` + `MergePropagationSystemPrompt`. Two-phase: workdir merge → propagation-only (`--propagation-only`). Conflict resolver invoked per-phase; reads conflict hunks via `GitDiffAtSha` and reads ImplStream's `note.impl.design-choice` log entries for intent.

### `pm_core/streams/meta_development.py`
EXTRACTED (from `cli/meta.py:54 meta_cmd` + `cli/meta.py:255 _build_meta_prompt` — corrected per consolidation audit; meta-dev lives in `cli/meta.py`, not `wrapper.py`). `MetaDevelopmentStream` + `MetaDevelopmentSystemPrompt`. Reads other streams' EmissionLogs for regression blame; uses `LogQuery` + `TranscriptSlice` for canonical evidence. Composes with `HostCodeOverride` sensorium artifact for binding sibling pm checkout.

### `pm_core/streams/cluster_exploration.py`
EXTRACTED. `ClusterExplorationStream` + system prompt. Cross-repo navigation via project-namespaced channels.

### `pm_core/streams/container_build.py`
EXTRACTED (from `container.py` build flow + container build prompts). `ContainerBuildStream` + `ContainerBuildSystemPrompt`. HybridRuntime: Tmux for authoring, RawAPI for auto-rebuilds. Reads docker logs via `ArtifactRef`.

### `pm_core/streams/discuss.py`
EXTRACTED (from `pane_ops.launch_discuss` at `tui/screens.py:308` + the `launch_claude` "generic discuss pm" flow + the relevant prompt body that today lives inline in those launchers; corrected per consolidation audit — `wrapper.py` has no discuss mode). `DiscussStream` + `DiscussSystemPrompt` + `OnboardLearnSystemPrompt` (two flavors — discuss for work, onboard-learn for the guide-mode learn variant). Queries other streams' EmissionLogs; emits recommendations + confirm-apply attention requests.

### `pm_core/streams/watchers/__init__.py`
EXTRACTED (from `watchers/__init__.py` string-to-class lookup). `WATCHER_REGISTRY: dict[str, type[Stream]]` — string `'auto-start'` → `AutoStartWatcherStream`, etc. External-string callers (TUI keybindings, CLI args) resolve through here.

### `pm_core/streams/watchers/auto_start.py`
EXTRACTED (from `watchers/auto_start_watcher.py`). `AutoStartWatcherStream` + `AutoStartTickPrompt`. Tick-driven via `Mind.schedule(interval='120s')`. Stays per-tick stateless per the shape-improvements audit's NO_CHANGE designation.

### `pm_core/streams/watchers/bug_fix_impl.py`
EXTRACTED (from `watchers/bug_fix_impl_watcher.py` + `bug_fix_prompts.py`). `BugFixImplWatcherStream` + `BugFixImplTickPrompt`. Tick-driven via `Mind.schedule`. Persistent across ticks (continue_existing).

### `pm_core/streams/watchers/improvement_fix_impl.py`
EXTRACTED. `ImprovementFixImplWatcherStream` + system prompt. Tick-driven (30min interval). Persistent.

### `pm_core/streams/watchers/discovery_supervisor.py`
EXTRACTED (from `watchers/discovery_supervisor.py` + `prompt_gen.generate_discovery_supervisor_prompt`). `DiscoverySupervisorStream` + `DiscoverySupervisorSystemPrompt`.

### `pm_core/streams/watchers/watcher_review.py`
EXTRACTED (from `watchers/` watcher-review + `prompt_gen.generate_watcher_review_prompt`). `WatcherReviewStream` + `WatcherReviewSystemPrompt`. Persistent per project; queries other watchers' EmissionLogs.

### `pm_core/streams/plan/add.py`
EXTRACTED (from `cli/plan.py` plan-add flow + `prompt_gen.generate_plan_prompt`). `PlanAddStream` + `PlanAddSystemPrompt`. Writes to `PlanArtifact`.

### `pm_core/streams/plan/breakdown.py`
EXTRACTED. `PlanBreakdownStream` + `PlanBreakdownSystemPrompt`. Reads plan file (via `PlanArtifact.read`) + project state; emits structured PR list back into plan.

### `pm_core/streams/plan/review.py`
EXTRACTED (from `plans/review.py`). `PlanReviewStream` + `PlanReviewSystemPrompt`. Persistent per plan; receives `phase.plan.review-requested` after each plan command completion. Writes `ReviewFileArtifact`.

### `pm_core/streams/plan/deps.py`
EXTRACTED (from `cli/plan.py` plan_deps flow). `PlanDepsStream` + `PlanDepsSystemPrompt`.

### `pm_core/streams/plan/import_.py`
EXTRACTED (from `cli/plan.py` plan_import flow + `cli/init.py`). `PlanImportStream` + `PlanImportSystemPrompt`.

### `pm_core/streams/plan/fix.py`
EXTRACTED (from `cli/plan.py` plan_fix flow). `PlanFixStream` + `PlanFixSystemPrompt` (handles both default and `--review` variants).

### `pm_core/streams/guide/setup.py`
EXTRACTED (from `guide.py` setup mode + `STEP_ORDER`/`STEP_DESCRIPTIONS`/`SETUP_STATES`). `GuideSetupStream` + `GuideSetupSystemPrompt`. ClassVars: `STEP_ORDER: list[GuideStep]`, `STEP_DESCRIPTIONS: dict[GuideStep, str]`, `SETUP_STATES: ...`. `tui/guide_progress.py` imports from here.

### `pm_core/streams/guide/assist.py`
EXTRACTED. `GuideAssistStream` + `GuideAssistSystemPrompt`. HybridRuntime: Tmux for chat + RawAPI for shadow re-rank ticks under one stream id.

---

## `pm_core/payloads/`

Typed `Payload` payload subclasses — the typed values that appear inside `Emission` payloads and `InputType` inputs. Distinct from `pm_core/sensorium/artifact/` (on-disk shared mutable Artifacts). Plan: [plan-mind](plan-mind.md).

### `pm_core/payloads/__init__.py`
NEW. Re-exports all Payload subclasses.

### `pm_core/payloads/base.py`
NEW. `Payload` Protocol: `id: str`, `kind: str`, `schema_version: str`, `to_payload() -> dict`, classmethod `from_payload(data)`, optional `upgrade(prior_payload, prior_version)` hook.

### `pm_core/payloads/regression_spec.py`
EXTRACTED. `RegressionSpec` typed dataclass for regression test specs.

### `pm_core/payloads/impl_instructions.py`
NEW. `ImplInstructions` typed dataclass — instructions handed to ImplStream.

### `pm_core/payloads/test_fixture.py`
NEW. `TestFixture` typed reference to a fixture used by QA scenarios.

### `pm_core/payloads/mock_spec.py`
EXTRACTED (from QA mock generation). `MockSpec` typed: `target_symbol`, `behavior`, `validation_rules`. QA mock-generator emits these; scenarios consume via typed inputs.

### `pm_core/payloads/qa_scenario_ref.py`
NEW. `QAScenarioRef` typed reference carrying `mocks: list[MockSpec]`, `fixture: TestFixture`, `instructions: QAScenarioInstructions`.

### `pm_core/payloads/repo_checkout.py`
NEW. `RepoCheckout` typed: `host_path`, `runtime_path`, `branch`, `sha`. Sensorium's `PathService` resolves host↔runtime path duality.

### `pm_core/payloads/git_diff.py`
NEW. `GitDiffAtSha` typed: `base_sha`, `head_sha`, `paths: Optional[list[Path]]`. The typed reference to a diff that review streams consume.

### `pm_core/payloads/log_query.py`
NEW. `LogQuery` typed query into an `EmissionLog`: `tag`, `from_stream`, `since`, `where`, `last_n`. Resolves to a list of `Emission`.

### `pm_core/payloads/container_snapshot.py`
NEW. `ContainerSnapshot` typed reference to a container snapshot id (sensorium-side concept, NOT a wrapper-internal snapshot).

### `pm_core/payloads/transcript_slice.py`
NEW. `TranscriptSlice` typed: `stream_id`, `start_ref: TranscriptRef`, `end_ref: TranscriptRef`. The first-class typed reference verifier streams use to cite evidence from another stream's untagged transcript.

### `pm_core/payloads/failure_reason.py`
NEW. `FailureReason` typed: `kind: TerminationReason`, `detail: str`, `exit_code: Optional[int]`, `retryable: bool`. Carried on `stream.lifecycle.terminated` payloads.

### `pm_core/payloads/usage_event.py`
NEW. `UsageEvent` typed: `input_tokens`, `output_tokens`, `cost_usd`, `model`. Payload for `telemetry.cost` Emissions.

---

## `pm_core/supervisors/`

Supervisor Protocol + concrete loop orchestrators. **Loops live here, not in Streams.** Plan: [plan-mind](plan-mind.md).

### `pm_core/supervisors/__init__.py`
NEW. Re-exports `Supervisor`, the concrete Supervisor classes, `StreamRecord`.

### `pm_core/supervisors/protocol.py`
NEW. `Supervisor` Protocol: `known_streams() -> list[StreamRecord]`, `state(stream_id) -> LifecycleState`, `running() -> list[Stream]`, `resumable() -> list[StreamRecord]`, `never_started() -> list[StreamRecord]`, `health_check(stream_id)`, `supervise(stream_id)`, `on_state_change(handler)`, `set_quota(scope_glob, max_concurrent)`, `cancel_correlation(correlation_id, reason)`. `StreamRecord` dataclass: `stream_id`, `role`, `instance_key`, `state`, `parent_id`, `policy`, `last_emission_at`.

### `pm_core/supervisors/watcher.py`
EXTRACTED (from `watcher_manager.py` orchestration only). `WatcherSupervisor`: owns all watcher streams. Supervises tick health. Subscribes to `Mind.schedule`-driven tick channels. Implements lease reconcile on startup (releases stale leases from prior crashed runs). **watcher_manager.py fans further** (per consolidation audit): `list_watchers` aggregation → `watchdog/tui.py`; per-watcher lookups → `supervisors/protocol.py::StreamRecord`; emission dedup → `mind/emissions.py`.

### `pm_core/supervisors/pr_stream.py`
EXTRACTED (from `qa_loop.py` orchestration + `review_loop.py` orchestration + `pr_cleanup.py` + per-PR signoff/merge driving + `signoff.py::_BOUNCE_HOP_STATUS / decide_signoff_hop / apply_signoff_hop`). `PRStreamSupervisor`: owns ORCHESTRATION ONLY — per-action Streams (`ReviewStream`, `SignoffStream`, `MergeStream`, `Qa*Stream`) absorb the bulk of the original per-action logic; this supervisor owns the cross-action lifecycle wiring. **Orchestrates the review loop**: spawns fresh ReviewStream iterations with bumped instance_key on `impl.lifecycle.commit-landed`; delivers feedback to ImplStream on `verdict.review.needs-work`; advances to QA on `verdict.review.pass`. **Orchestrates QA scenario fan-out**: spawns N QaScenarioStreams; barriers on all PASS or any FAIL. **Orchestrates signoff** including the hop-routing keyed on `PRStatus` enum values (resolves the `"review"` vs `"in_review"` token drift from signoff.py:393). **Orchestrates merge with conflict resolution**. Per-PR overrides field: `overrides: dict[int, PROverride]` (self_driving, stop_before_merge, auto_approve_spec).

### `pm_core/supervisors/plan_stream.py`
EXTRACTED. `PlanStreamSupervisor`: owns plan-add, plan-breakdown, plan-review, plan-deps, plan-import, plan-fix streams across a plan's lifetime. Orchestrates the plan-add → breakdown → review cycle.

### `pm_core/supervisors/mind.py`
NEW. `MindSupervisor`: top-level Supervisor over the others. The observability/dashboarding hook attachment point. Implements `startup()` that replays `EmissionLog` to reconstitute watcher streams that were running pre-restart (subsumes today's merge-restart marker file).

### `pm_core/supervisors/health.py`
EXTRACTED (supersedes `pr-18ac983` session-health-watcher). Health-check policies invoked by `Supervisor.supervise`. Lives at Supervisor layer, not as a separate watcher.

### `pm_core/supervisors/coach.py`
EXTRACTED (supersedes `pr-871dbf5` supervisor-watchers). "Coach lower-effort sessions" policies invoked by Supervisor.

---

## `pm_core/watchdog/`

Typed `WatchdogPolicy` classes that observe Supervisor lifecycle events and surface them to humans. Plan: [plan-mind](plan-mind.md).

### `pm_core/watchdog/__init__.py`
NEW. Re-exports `WatchdogPolicy` and the concrete policy classes.

### `pm_core/watchdog/policy.py`
NEW. `WatchdogPolicy` base. Subclasses subscribe to `Supervisor.on_state_change(...)` and to specific Emission tags via `CallbackRegistry`, run typed health checks on lifecycle anomalies, and raise `AttentionRequest`s when they fire. The distinction from `Supervisor.supervise` (which IS the supervision policy): supervisors decide what to do internally (restart, terminate, escalate); watchdogs are third-party observers that surface state to humans / dashboards / other front-ends. A web dashboard would subscribe to the same watchdog policies the TUI does.

### `pm_core/watchdog/staleness.py`
EXTRACTED (supersedes `pr-923f22b` thread-death watchdog only — corrected per consolidation audit; earlier wording credited `qa_status.py` watchdog parts and `tui/auto_start.py` "is it still working?" indicators, but `qa_status.py` actually routes to `watchdog/tui.py` + `runtime/tmux_host.py` and `tui/auto_start.py` contains no health-indicator code). If a "stuck Claude pane" detector is desired, the source is `pane_idle.py` + `runtime_state.py:sweep_stale_states`, both routed elsewhere; this watchdog covers the higher-level "stream in `running` state but emitting nothing" case only. `StalenessWatchdog`: flags streams that have transitioned to `running` but haven't emitted anything for a configurable window.

### `pm_core/watchdog/long_running.py`
NEW. `LongRunningWatchdog`: flags streams that have been `running` past a configurable wallclock threshold without emitting a terminal verdict. Distinct from staleness — the stream IS emitting, but the conversation has been going too long. Useful for catching prompt loops that never converge.

### `pm_core/watchdog/budget_alarm.py`
NEW. `BudgetAlarmWatchdog`: subscribes to `telemetry.cost` Emissions; fires `AttentionRequest`s when a stream's cumulative spend crosses `StreamPolicy.budget` warning thresholds (separate from the hard cap that triggers `budget.exhausted` and termination). Surfaces "approaching limit" warnings before the supervisor terminates.

### `pm_core/watchdog/orphaned_lease.py`
NEW. `OrphanedLeaseWatchdog`: subscribes to `stream.lifecycle.terminated` + `lease.<key>.*`; detects leases whose holder has terminated without the release firing (transport-level crash, network partition). Triggers `ResourceLease.reconcile()` to clean up. Complements the `Supervisor.startup()` reconcile pass for in-flight detection.

### `pm_core/watchdog/repeated_attention.py`
NEW. `RepeatedAttentionWatchdog`: subscribes to `request.user-attention.*` per stream; if N attention requests fire in a window, demotes the stream per `StreamPolicy.repeated_attention_action`. Distinct from `Supervisor.supervise` (which acts on stream lifecycle) — this acts on the user-attention escalation pattern.

### `pm_core/watchdog/tui.py`
NEW. `TUIDisplayWatchdog`: not a state-anomaly watchdog like the others — instead, the TUI-side consumer that subscribes to ALL the other watchdogs' `AttentionRequest` emissions and renders them in the dashboard with appropriate icons / colors / sort order. The single TUI integration point for watchdog state. Equivalent web-dashboard consumer would be `pm_core/dashboard/watchdog.py` (out of scope for this refactor).

---

## `pm_core/sensorium/`

Typed primitives for pm's slice of the broader sensorium. Plan: [plan-sensorium](plan-sensorium.md).

### `pm_core/sensorium/__init__.py`
NEW. Re-exports public API.

### `pm_core/sensorium/artifact/base.py`
EXTRACTED (from `editor.py`) + WRAPS (`store.WriteQueue` and `store.locked_update` — corrected per consolidation audit; those routines STAY in `store.py` per migration-map L929-933, and Artifact.apply delegates to them rather than absorbing them). `Artifact` base: `read() -> (data, version)`, `propose_edit(edit)`, `apply(edit, base_version, debounce: Optional[timedelta]=None)`, `history(limit)`, `on_change(handler)`, `open_in_editor(who='$EDITOR') -> EditorHandle`, `watch_for_save(handle) -> AsyncIterator[Edit]`, `edit_interactively(who, max_attempts, surface='cli'|'tui')` (schema-aware editor with validate-on-save + reopen-on-error), `resolve_link(ref) -> Optional['Artifact']` (the `[[...]]` link convention), `_on_external_change` (file-watch detects external mutations, emits `artifact.<name>.externally-changed`). Atomic write via tempfile + rename. Optimistic-lock via sidecar `.version`. Debounce coalesces high-frequency mutations.

### `pm_core/sensorium/artifact/_frontmatter.py`
NEW. Shared YAML-frontmatter parser used by QaLibraryArtifact subclasses, PlanArtifact, SpecArtifact, RadarItemArtifact, walker_ui artifacts.

### `pm_core/sensorium/artifact/_plan_markdown.py`
NEW. `PlanMarkdownSchema` — single source for plan-file *structure*: module-level `PR_FIELDS = ("description", "tests", "files", "depends_on")`, section markers (`PRS_SECTION = "PRs"`, `PR_BLOCK_PREFIX = "### PR:"`, `PLANS_SECTION = "Plans"`, `PLAN_BLOCK_PREFIX = "### Plan:"`), `format_pr(pr_dict) -> str` renderer, `format_spec_for_prompt() -> str` prompt-fragment renderer, and `parse_plan_prs(text) -> list[PRRecord]` parser. The four sites that today encode this knowledge independently — `pm_core/plans/parser.py:74-93`, `pm_core/cli/plan.py:117/120-124/219-225/845-850`, `pm_core/cluster/output.py:16/26-30`, `pm_core/prompt_gen.py:1045-1048` — all consume from here after this PR. `PlanArtifact` delegates parse/render to this module; the plan-related streams (`PlanAddStream`, `PlanBreakdownStream`, `PlanImportStream`) import `PR_FIELDS` rather than re-listing it in prompt strings. Includes a CI test asserting no other file in `pm_core/` references the literal strings `"### PR:"` or `("description", "tests", "files", "depends_on")` outside this module. Eliminates audit gaps G6/G7/G8.

### `pm_core/sensorium/artifact/project_yaml.py`
EXTRACTED (from `store.py` — and **the project.yaml fcntl + WriteQueue + locked_update mechanics fully graduate** into `Artifact.apply`'s atomic-write + optimistic-version + debounce path; `store.py` keeps only YAML parse/load after this PR — no more flock under the Artifact wrapper). `ProjectYamlArtifact(Artifact)`: path `pm/project.yaml`, schema `Project`, `write_acl = {ImplStream, PlanAddStream, ..., SignoffStream}`. Cross-process coordination becomes optimistic via the sidecar `.version` file (writers retry on stale version) rather than pessimistic via flock.

### `pm_core/sensorium/artifact/plan.py`
EXTRACTED (from `plans/parser.py` callers AND `plans/parser.py` ITSELF). `PlanArtifact(Artifact)`: path `pm/plans/<id>.md`, schema `Plan`, `write_acl = {PlanAddStream, PlanReviewStream, PlanEditStream, HumanWriter}`. Owns `parse_prs()` / `parse_plans()` (the body of today's `plans/parser.py`) by delegating structural knowledge to `_plan_markdown.py::PlanMarkdownSchema` and frontmatter parsing to `_frontmatter.py`. **`pm_core/plans/parser.py` deletes entirely** — three files where two now do (Artifact + Schema). Callers `from pm_core.plans.parser import parse_plan_prs` rewrite to `PlanArtifact.read().parse_prs()`.

### `pm_core/sensorium/artifact/notes.py`
EXTRACTED (from `notes.py` — and **the load/save_sections mechanics fully graduate** into `Artifact.apply`'s atomic-write + optimistic-version path; `notes.py` keeps only the section-format parser/serializer after this PR). `NotesSectionArtifact(Artifact)`: path `pm/notes/<scope>.txt`, schema `NotesSection`. Open write_acl.

### `pm_core/sensorium/artifact/global_settings.py`
NEW. `GlobalSettingsArtifact(Artifact)`: path `~/.pm/settings.json` (or wherever paths.py's `get_global_setting_value` reads/writes today), schema `GlobalSettings` (typed fields for `provider`, `default_model`, `effort`, capture flags, observability flags, etc. — the full key set today's free-form KV store accepts). Replaces the untyped `get_global_setting_value` / `set_global_setting_value` getters in `paths.py` and pairs with `model_config.py`'s provider/model resolution (model_config.py becomes the typed schema definition + resolver; the persistence + change-notify lives on the Artifact). Closes the "schema-less files that should be typed Artifacts" gap from the consolidation discussion.

### `pm_core/sensorium/artifact/host_override.py`
NEW. `HostOverrideArtifact(Artifact)`: path `~/.pm/sessions/<tag>/override`, schema `SessionOverride` (the workdir/branch override the user (and `pm pr meta`) edits). Replaces today's `paths.py` raw file getters/setters around the override file with typed schema validation + change-notify so the TUI sees overrides update without polling. Sibling under sensorium's host-overrides subtree alongside `HostCodeOverride`.

### `pm_core/sensorium/artifact/fake_claude_config.py`
NEW. `FakeClaudeConfigArtifact(Artifact)`: path `~/.pm/sessions/<tag>/fake-claude` (+ `.state` sidecar). Schema `FakeClaudeConfig` (scripted-verdict cursor, per-session-type config overrides). Replaces `paths.py`'s `fake_claude_config / set_fake_claude_config / clear_fake_claude` and the marker-file pattern. Consumed by `FakeClaudeRuntime` (`runtime/fake.py`) for test-driven scripted verdicts. The filename constants live in `pm_core/_path_constants.py`.

### `pm_core/sensorium/artifact/claude_hooks.py`
NEW. `ClaudeHooksArtifact(Artifact)`: path `~/.claude/settings.json` (the user's Claude Code settings file). Schema `ClaudeHookSettings` (the hook list pm installs/maintains). Sensorium HostCodeOverride family — pm writes to a file outside our repo to register hook callbacks; that mutation is a typed Artifact apply with schema validation + change-notify (so a `RuntimePlugin` can detect external hook config changes and re-register if needed). Replaces today's ad-hoc `hook_install.py` settings-file mutation logic; the hook-payload generation moves to `runtime/hook_entry.py` (per the existing plan), but the file write goes through this Artifact.

### `pm_core/sensorium/artifact/regression_spec.py`
EXTRACTED (from `qa_instructions.py` + `qa/regression/*` callers). `RegressionSpecArtifact`: path `pm/qa/regression/<id>.md`, schema `RegressionSpec`.

### `pm_core/sensorium/artifact/spec.py`
EXTRACTED (from `spec_gen.py` write surface). `SpecArtifact`: per-PR phase specs at `pm/specs/<pr-id>/<phase>.md` where phase ∈ {impl, qa, review}. Dual workdir/local lookup precedence. Approval workflow.

### `pm_core/sensorium/artifact/qa_library/instructions.py`
EXTRACTED (from `qa_instructions.py`). `QaInstructionsArtifact`: `pm/qa/instructions/<id>.md` with YAML frontmatter.

### `pm_core/sensorium/artifact/qa_library/mocks.py`
EXTRACTED. `QaMocksArtifact`: `pm/qa/mocks/<id>.md`.

### `pm_core/sensorium/artifact/qa_library/regression.py`
EXTRACTED. `QaRegressionArtifact`: `pm/qa/regression/<id>.md`.

### `pm_core/sensorium/artifact/qa_library/artifacts.py`
EXTRACTED. `QaArtifactsArtifact`: `pm/qa/artifacts/<id>.md` (artifact recipes — screenshots, recordings).

### `pm_core/sensorium/artifact/qa_library/status.py`
NEW. `QaStatusArtifact`: typed read surface over QA status that `SignoffStream`'s evidence pane reads instead of shell-globbing `~/.pm/workdirs/qa/<pr>-*/qa_status.json`. Per-scenario verdict, last-update timestamp, evidence-bundle refs, currently-blocking attentions.

### `pm_core/sensorium/artifact/review_file.py`
EXTRACTED (from `plans/review.py` write/parse/list flow). `ReviewFileArtifact`: `pm/plans/reviews/<plan_id>-<review_id>.txt` for NEEDS_FIX surfacing; consumed by `pm plan fix --review`.

### `pm_core/sensorium/artifact/radar_item.py`
NEW. The radar's information structure as typed Artifacts: `RadarThreadArtifact`, `RadarItemArtifact`, `RadarCommentArtifact`, `RadarTagArtifact`. Subsumes plan-radar's earlier editable-artifacts primitive.

### `pm_core/sensorium/artifact/walker_ui.py`
EXTRACTED (from `review/md_parser.py` + `review/md_writer.py`). Walker UI artifacts for plan-3119574: `ReviewStateArtifact`, `UiFocusArtifact`, `NotesArtifact`, per-cycle `ReviewCycleArtifact` / `CitationAuditCycleArtifact` / `ReviewResponseCycleArtifact`. Walker UI streams subscribe via `CallbackRegistry.on(ArtifactChangeChannel('review-cycle-2'), ...)`.

### `pm_core/sensorium/leases.py`
NEW. `ResourceLease` + `ResourceKey` hierarchy (`TmuxWindowKey`, `WorkdirKey`, `BranchRefKey`, `ContainerKey`, `ChampionSlotKey`, `LeaderSlotKey`). Methods: `acquire(holder_stream_id, ttl)`, `release(holder_stream_id)`, `renew(holder_stream_id, ttl)`, `status()`. Classmethod `reconcile(key_prefix, holder_filter)` for sweeping stale leases on Supervisor startup. Emits `lease.<key>.acquired/released/expired` Emissions.

### `pm_core/sensorium/paths.py`
EXTRACTED (from `paths.py` runtime-path parts). `PathService`: `for_runtime(host_path, runtime) -> str`, `for_host(runtime_path, runtime) -> str`, `materialize(file, runtime) -> str` (powers large-prompt spool). `FileArtifact` Payload.

### `pm_core/sensorium/captures.py`
EXTRACTED (from `~/.pm/sessions/<tag>/captures/` glue). `CaptureBundle` Payload + `CaptureService` with `open(session_id, test_id)`, `append(bundle, filename, content)`, `list(session_id)`, `gc(older_than)`.

### `pm_core/sensorium/host_overrides.py`
EXTRACTED (from meta-dev `~/.pm/sessions/<tag>/override` glue). `HostCodeOverride` Payload + `HostOverrideService`. Cleanup-on-terminate hooks into `Stream.on_cancel`.

### `pm_core/sensorium/redaction.py`
NEW. `RedactionPolicy`: rules (regex/callable/`sensitive: bool` Payload flag) applied at `StreamTranscript.append` + `EmissionLog.append` + `Artifact.apply` write seams. Default rules cover common secret patterns. Per-AgentGraph configurable.

### `pm_core/sensorium/workdirs.py`
EXTRACTED (from `cli/helpers.py` + `cli/pr.py` + `qa_loop.py` workdir provisioning). `WorkdirRegistry` + `Workdir` Payload + `ScenarioWorkdir(Workdir)` subclass (per-scenario isolated clone with override file). Methods: `ensure(pr_id, purpose, branch, clone_from)`, `by_pr(pr_id)`, `stash_overlaps(around_workdir)`, `unstash(handle)`, `reap(workdir)`. Cross-workdir overlap stash/unstash around merges. Integrates with `ResourceLease` via `WorkdirKey`.

### `pm_core/sensorium/commands/base.py`
NEW. `PmCommand(Payload)` base: `inputs: ClassVar[type]`, `output_emission: ClassVar[Optional[type[Payload]]]`, `cwd: RepoCheckout`, `to_argv() -> list[str]`.

### `pm_core/sensorium/commands/generated.py`
NEW. Auto-generated `PmCommand` subclasses from pm's argparse/Click definitions (CI-enforced lock-step). One subclass per pm subcommand.

### `pm_core/sensorium/commands/handrolled.py`
NEW. Hand-rolled `PmCommand` subclasses for subcommands argparse can't introspect cleanly (<10% of commands).

### `pm_core/sensorium/commands/service.py`
NEW. `PmCommandService.invoke(command, runtime) -> Emission`, `known() -> set[type[PmCommand]]`.

---

## `pm_core/collaboration/`

Narrow typed cross-mind substrate. Cross-mind interaction is **Artifact-mediated**, not message-passed. No FederatedMailbox, no SignedEmission. Plan: [plan-collaboration](plan-collaboration.md).

### `pm_core/collaboration/__init__.py`
NEW. Re-exports `ProjectIdentity`, `PartyRelationship`, `IdentityService`, `Transport` Protocol.

### `pm_core/collaboration/identity.py`
NEW. `ProjectIdentity(Payload)`: `project_id`, `display_name`, `signing_pubkey`, `party_relationships: dict[str, PartyRelationship]`. `PartyRelationship(visibility, redaction_rules, transport, inbound_write_policy)`. `IdentityService`: `attribute(artifact, version) -> ProjectIdentity` (who authored from transport metadata), `sign_version(artifact, edit)` (optional; transport-level signing default), `verify_version(artifact, version)`.

### `pm_core/collaboration/published_artifact.py`
NEW. Extension to `Artifact` base. `Artifact.published_to: set[str]`, `publish_visibility: dict[str, VisibilityTier]`, `publish_to_project(project_id, tier)`, `unpublish(project_id)`. `apply()` on a published Artifact triggers transport sync to all `published_to` projects.

### `pm_core/collaboration/transport/protocol.py`
NEW. `Transport` Protocol: `publish(artifact, edit, to: ProjectIdentity) -> PublishReceipt`, `fetch(from_project, artifact_name, since_version) -> list[Edit]`, `subscribe(from_project, artifact_glob, handler) -> SubId`, `authenticated_as() -> ProjectIdentity`. Synchronizes Artifact STATE, not Emissions.

### `pm_core/collaboration/transport/git.py`
NEW. Git-backed Transport. Publication = commit + push to a configured remote. Fetch = pull. Auth via commit signatures + push permissions. The default; no infrastructure dependency.

### `pm_core/collaboration/transport/https.py`
NEW. HTTPS Transport. Push/pull against a small relay or peer-to-peer endpoint. Lower-latency for live channels. Auth via mutual TLS or signed bearer tokens.

### `pm_core/collaboration/transport/tmux_socket.py`
NEW. Same-host shared tmux socket Transport. Uses pm's existing `SHARED_SOCKET_DIR` + Unix-group permissions + share-users. For pair-style local collaboration between two minds on one machine. Same `RemoteEndpoint` shape as `git`/`https`.

---

## `pm_core/tui/pr_actions/`

Typed TUI bindings for PR actions — sibling-set with mind-side `PRActionStream`. Plan: [plan-mind](plan-mind.md) (PRActionTUIType section).

### `pm_core/tui/pr_actions/__init__.py`
NEW. Imports every binding module so `PRActionTUIType.__subclasses__()` returns the complete set for the completeness check.

### `pm_core/tui/pr_actions/_registry.py`
NEW. `check_pr_action_bindings_complete()`: runs at TUI startup AND as a pytest test (`tests/test_pr_action_bindings.py`). Asserts every `PRActionStream` subclass has a paired `PRActionTUIType` and vice versa. Also asserts no two bindings share a main `keybinding.key` or a `picker_shortcut`, and every `fold_into` value names an existing binding. `_load_all_subclasses()` defensively imports `pm_core.streams` + `pm_core.tui.pr_actions`. Catches: missing TUI binding for a new PRActionStream, orphan TUI binding for a deleted Stream, duplicate bindings, orphan fold_into references, missing required ClassVars (caught earlier by `__init_subclass__`).

### `pm_core/tui/pr_actions/base.py`
NEW. `PRActionTUIType` base with `__init_subclass__` validation. Required ClassVars: `stream_class: type[PRActionStream]`, `keybinding: Keybinding` (main-screen key), `picker_shortcut: str | None` (letter in prefix+P picker), `command_template: str` (the `pm`/`tui:` command the picker executes), `window_role: str | None` (tmux window-name pattern; `None` = no window opens), `applicable_statuses: frozenset[PRStatus]`, `picker_list_row: bool`, `glyph: str`. Optional: `fold_into: str | None`, `phase_label: str | None`, `modifier_variants: dict[str, str] = {}` (z/zz → command-template override), `companion_panes: list[CompanionPaneSpec] = ()`. `Keybinding` dataclass: `key`, `label`, `show_in_help`. `CompanionPaneSpec` dataclass.

**Picker consolidation.** These ClassVars subsume `pm_core/cli/session.py`'s hard-coded duplicates: `_ALL_ACTIONS` (now `command_template` + `applicable_statuses`), `_ACTION_WINDOW_PATTERNS` (now `window_role`), `_LIST_ACTIONS` (now `picker_list_row`), `_SHORTCUT_FOLD_INTO` (now `fold_into`), `_STATUS_PHASE` (now `phase_label`), `_MODIFIED_ACTION_CMDS` (now `modifier_variants`), `_SHORTCUT_KEYS` (now `picker_shortcut`). The prefix+P picker code-path in `cli/session.py` enumerates `PRActionTUIType.__subclasses__()` filtered by `applicable_statuses`; the completeness check asserts both call sites (main-screen keybindings AND picker enumeration) see the same set.

### `pm_core/tui/pr_actions/impl.py`
NEW. `ImplActionTUI(PRActionTUIType)`: `stream_class=ImplStream`, `keybinding=Keybinding(key='s', label='Start')`, `glyph='⚙'`, `window_role='impl'`.

### `pm_core/tui/pr_actions/review.py`
NEW. `ReviewActionTUI`: `stream_class=ReviewStream`, `keybinding=Keybinding(key='d', label='Review')`, `glyph='👀'`, `window_role='review'`.

### `pm_core/tui/pr_actions/qa.py`
NEW. `QaActionTUI`: `stream_class=QaPlanningStream` (or a composite type for the QA orchestration), `keybinding=Keybinding(key='t', label='QA')`, `glyph='🧪'`, `window_role='qa'`. Subsequent qa_scenario panes are companion panes of this action.

### `pm_core/tui/pr_actions/signoff.py`
NEW. `SignoffActionTUI`: `stream_class=SignoffStream`, `keybinding=Keybinding(key='o', label='Sign off')`, `glyph='✓'`, `window_role='signoff'`, `companion_panes=[CompanionPaneSpec(role='evidence', source=QaStatusArtifact)]`.

### `pm_core/tui/pr_actions/merge.py`
NEW. `MergeActionTUI`: `stream_class=MergeStream`, `keybinding=Keybinding(key='g', label='Merge')`, `glyph='↪'`, `window_role='merge'`.

### `pm_core/tui/pr_actions/cleanup.py`
NEW. `CleanupActionTUI`: `stream_class=None` (no Stream — cleanup invokes `PRStreamSupervisor.teardown(pr_id)` directly, not via a Stream subclass), `keybinding=Keybinding(key='Y', label='Cleanup')`, `glyph='🧹'`, `window_role=None` (no window opens), `picker_list_row=True`, `applicable_statuses=frozenset(PRStatus) - {PRStatus.pending}`, `command_template='pm pr cleanup {pr_id}'`. The completeness check is relaxed to accept `stream_class=None` for supervisor-driven actions; the `_registry.py` check distinguishes `PRActionTUIType` subclasses with `stream_class=None` (no PRActionStream sibling required) from those with a typed `stream_class` (paired with a PRActionStream subclass). Closes audit gap G2 — `cleanup_pr Y` was previously a first-class PR action with no typed home.

---

## Top-level files

### `pm_core/mind.py`
NEW. `Mind` class — top-level factory, singleton per project. Methods: `stream(role: type[Stream], instance_key, runtime, policy, inputs) -> Stream`, `shutdown(stream_id)`, `streams(role: Optional[type[Stream]], alive_only) -> list[Stream]`, `list_transcripts(since)`, `mailbox(channel: Channel | str) -> Mailbox`, `log_of(stream_id) -> EmissionLog`, `transcript_of(stream_id) -> StreamTranscript`, `schedule(tag, cron_or_interval, target: Channel, payload, visibility) -> ScheduleId`, `cancel_schedule(sid)`, `supervisor(kind) -> Supervisor`. Properties: `callbacks: CallbackRegistry`, `attention: AttentionService`. Singleton enforcement (one pm process = one Mind). TUI is a thin layer over this surface.

### `pm_core/bootstrap.py`
RENAMED (from `pm_core/wrapper.py`). Console-scripts entry point. sys.path manipulation, session-override resolution, cwd-walk to find local pm_core, pm_root persistence. Runs before pm_core is importable. Dispatches between modes: `hook_entry` (Claude Code hook callback → `runtime/hook_entry.py`), `reentry` (pm subprocess of itself → `runtime/reentry.py`), `normal` (user invocation → `pm_core.cli`).

### `pm_core/_path_constants.py`
NEW. Tiny stdlib-only module — `from pathlib import Path` and nothing else — owning the complete per-session on-disk vocabulary: `PM_HOME = Path.home() / ".pm"`, `SESSIONS_SUBDIR = "sessions"`, `PM_ROOT_FILENAME = "pm_root"`, `OVERRIDE_FILENAME = "override"`, `FAKE_CLAUDE_FILENAME = "fake-claude"`, `FAKE_CLAUDE_STATE_FILENAME = "fake-claude.state"`, `PM_SHARE_MODE_ENV = "PM_SHARE_MODE"`. Exists because `bootstrap.py` must run BEFORE `pm_core` is importable (so it can't depend on `paths.py`), but `bootstrap._get_session_tag` / `_find_active_override` / `_pm_core_from_pm_root` and `paths.get_session_tag` / override-file / fake-claude-config readers MUST agree on the on-disk contract or sessions silently diverge (audit G5 + PC-2). Both call sites import only this module to derive paths. CI grep test forbids string literals `"pm_root"` / `"override"` / `"fake-claude"` / `"fake-claude.state"` in `pm_core/` outside this module. Parity test `tests/test_bootstrap_session_tag_matches_paths.py` covers PM_SHARE_MODE hashing and `use_github_name=True`.

---

## Consolidation-audit corrections (remaining nits)

The top-down audit caught wording fixes scattered across many entries — recording them here once so a reader scanning the per-file descriptions sees the corrections without each entry growing a paragraph:

- **`bridge-py-fans`** — `bridge.py` fans into FOUR destinations, not just `raw_api.py`: `runtime/raw_api.py` (`_invoke_claude`), `runtime/_claude_cli_flags.py` (argv), `mind/mailbox.py` (busy/ack), `mind/attention.py` (AGENT/HUMAN mode toggle), with stdin Enter-toggle absorbed into `runtime/tmux_host.py`.
- **`claude-launcher-fans`** — four destinations now: `tmux_host.py`, `_claude_jsonl.py`, `fake.py`, plus the new `_claude_cli_flags.py`.
- **`pr-status-display-collapse`** — source list also includes `pr_utils.VALID_PR_STATES` (set membership for status validation).
- **`watcher-base-manager-split`** — destinations are not just Stream base + WatcherSupervisor; display aggregation → `watchdog/tui.py`, policy knobs → `mind/policy.py`.
- **`runtime-state-folds`** — also feeds `mind/attention.py` (suppress_switch) and `runtime/tmux_host.py` (`derive_action_status`).
- **`shared-prompts-consolidate`** — `_OUT_OF_SCOPE_BUGS_BLOCK` constant gets an explicit MOVES bullet; attribution for `filing_addendum / manual_testing_guidance / notes_for_prompt / mocks_for_prompt / spec_generation_preamble` corrected to point at `regression_prompts.py / cli/plan.py / notes.py / qa_instructions.py / spec_gen.py` rather than `prompt_gen.py`.
- **`reconcile-consolidates-cleanup`** — `ResourceLease.reconcile()` *complements* `PRStreamSupervisor.shutdown` + `TmuxHostRuntime` startup invariant + `OrphanedLeaseWatchdog`; it does not replace them.
- **`workdir-provisioning-consolidate`** — `_clone_workdir` lives in `cli/helpers.py:748`, not `cli/pr.py`.
- **`restart-markers-retire`** — only `auto_start.py` writes/reads the restart marker; `tui/sync.py` is not an author (drop from list).
- **`lifecycle-extract`** — source list also includes `cli/pr.py:315-316 click.Choice` literal, for symmetry with the destination description.
- **`stream-policy-extract`** — also absorbs `tui/app.py`'s in-memory `_stop_before_merge` / `_self_driving_qa` / `_review_loops` policy-shaped dicts.
- **`shared-prompts-phase-collapse`** — `pm_core/notes.py:312 _PROMPT_SPECIFIC` is the third site collapsed into the `Phase` enum (alongside `spec_gen.py:507-508` and `:692-696`).
- **`supervisors-watchdog-migration`** — merge-restart marker file: `MindSupervisor.startup()` EmissionLog replay subsumes it (resolves the migration-map "Not in plan" flag). `qa_status.py` "stuck pane" detection logic routes to `watchdog/staleness.py` (or `pane_idle.py` if a per-pane idle detector is desired).

## File counts by package

| Package | Files |
|---|---|
| `pm_core/mind/` | 10 |
| `pm_core/runtime/` | 12 |
| `pm_core/streams/` | ~30 (incl. _shared_prompts, _protocol, base, pr_action, all roles, watchers/, plan/, guide/) |
| `pm_core/payloads/` | 13 |
| `pm_core/supervisors/` | 7 |
| `pm_core/watchdog/` | 8 |
| `pm_core/sensorium/` | ~29 (incl. artifact/, artifact/qa_library/, leases, paths, captures, host_overrides, redaction, workdirs, commands/, `artifact/_plan_markdown.py`, plus four new Artifact subclasses from the locking-story consolidation: `global_settings.py`, `host_override.py`, `fake_claude_config.py`, `claude_hooks.py`) |
| `pm_core/collaboration/` | 6 |
| `pm_core/tui/pr_actions/` | 9 |
| top-level | 3 (`mind.py`, `bootstrap.py`, `_path_constants.py`) |

**Total new file count: ~116.** Roughly equal to the count of existing pm_core/ files that delete or substantially-move (~62), plus genuinely net-new infrastructure (~54).

See [refactor-migration-map.md](refactor-migration-map.md) for the existing-file ↔ new-file mapping with per-responsibility detail.
