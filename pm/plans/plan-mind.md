# Mind — Typed Substrate for Persistent Dynamic Streams

(a single wrapper abstraction over every Claude session / watcher / scenario worker so they compose into a typed, queryable, runtime-pluggable graph of streams of consciousness — replacing today's tmux-launch + regex-verdict-extraction + pane-stalling-on-INPUT_REQUIRED machinery)

> Names settled during the agent-wrapper refactor: `Mind` (was `AgentGraph`), `Stream` (was `AgentSessionHandle`), `Emission` (was `TaggedOutput`), `EmissionLog` (was `StructuredOutputLog`), `StreamTranscript` (was `SessionTranscript`), `InputType` (was `PromptType`), `Supervisor` (was `Manager`). `stream_id` everywhere replaces `agent_id` / `session_id`.

## Framing

The abstraction this plan defines is a substrate for managing **streams of consciousness** (text streams, for now) and their interactions. The collection of all such streams is a **mind** — conscious and unconscious by analogy to human cognition. Code generation is one possible side effect of a stream, not the thing being modeled; this plan must make sense for any text-emitting stream regardless of whether it has code, web, shell, or any other side-effect capabilities.

What lives where:

- **This plan (the mind)** — streams, the collection that holds them, how they emit, listen, sleep, wake, are scheduled, are budgeted, are supervised. Plus the typed I/O substrate they use to interact (Emission, InputType, Payload base).
- **plan-sensorium (the shared environment pm interacts with)** — editable artifacts, resource leases on shared external resources (tmux window names, branch refs, container names, workdirs), path views between host and runtime filesystem, captures of non-textual side effects, host-code overrides, write-time redaction. The sensorium notifies the mind via Emissions on a well-known schema; the mind reads/writes via typed sensorium primitives. **The sensorium is also the ambient substrate two minds on different machines already share through today** — git, filesystem, project artifacts — without needing explicit plumbing.
- **plan-collaboration (cross-mind interaction)** — the typed substrate and policy layer for two cases the ambient sensorium does NOT cover: (1) minds that are separate entities with their own goals and may need to surface disagreements they can't immediately resolve; (2) tasks whose complexity exceeds one project's coordination capacity, requiring compression between components in forms like public docs, releases, and stable interfaces. Federation transport, sender identity attestation, cross-boundary visibility, and redaction are the substrate; the rest of plan-collaboration is the policy and on-ramp built on it.

### Mind is per-project-per-machine; restartable streams enable cross-machine handoff

One `Mind` exists per running pm process. Two developers running pm on their respective checkouts of the same project each have their own Mind; they interact through the sensorium (git, shared filesystem). A Mind does not currently span machines.

**Restartable streams enable a useful intermediate capability today** — mind-handoff across machines without active cross-machine coordination. Because every stream is restartable from its durable `EmissionLog` + typed `InputType` history (no reliance on runtime-internal snapshot like `claude --resume`), if Mind M1 on machine A starts a long-running stream and machine A goes down, Mind M2 on machine B with access to the same project state can pick up the same `(role, instance_key)` stream and continue. M2 reads the EmissionLog, replays the InputType chain, instantiates a fresh runtime, and resumes. This is the ambient cross-machine continuation property the "no `claude --resume` reliance" design choice unlocks — every stream is handoff-able as long as the project state (including `pm/.mindlog.db` + `pm/.transcripts/`) is reachable from the receiving machine.

**Cross-machine minds — actively running streams on different machines coordinated as one logical Mind — is future work, intentionally deferred.** The architecture admits it (the EmissionLog is the durable record; Mailbox impl can be made cross-machine via Redis/NATS as already noted; Channel addressing is project-namespaced). What's missing today is the machine-level Mailbox transport and leader-election semantics for which machine is authoritative on which stream. Not in scope for this refactor.

The three plans share one dependency-ordered PR sequence (see each plan's "Implementation PR sequence" section).

## Thesis

pm's coordination layer is currently a patchwork: `BaseWatcher` ticks driving idle-prompt hook regex extraction; `qa_loop.py` spawning tmux panes per scenario and polling for verdicts; `review_loop.py` repeating the same pattern with its own state machine; `bridge.py` reimplementing dual-control over a Unix socket; per-watcher `pm/watchers/<name>.log` files as ad-hoc verdict storage; INPUT_REQUIRED stalling the pane it was raised on. Every new stream role reimplements some subset of: session launch, verdict detection, persistence, escalation, cross-stream visibility.

This plan replaces that patchwork with a typed 11-primitive substrate. The wrapper owns lifecycle, addressability, persistence, inter-stream control flow, and typed input/output. It does NOT own prompt generation (prompts become typed objects), code reading (code stays the arbiter of truth), or role-specific decision logic. Roles compose primitives at runtime; the graph wires itself.

The end state is a substrate on which persistent, dynamic graphs of streams work together — addressable across runtime swaps, queryable across sessions, pluggable across execution backends (tmux today, containers tomorrow, model-built-in sandboxes when they ship).

## Design principles (load-bearing, non-negotiable)

1. **Targeted communication is always typed.** Stream↔stream and stream↔human messages flow as `Emission` envelopes posted to a `Mailbox` or appended to a `EmissionLog`. Untagged free text stays in the runtime's chat transcript and is unaddressable from other streams. The current chat interface does not change to support this.
2. **Side effect is the arbiter of truth.** No primitive exposes a peer-summary payload type. Verdict schemas carry control-flow fields plus typed references to canonical content in the sensorium (git diff at sha, file at path, log slice, transcript slice). The canonical record of what a stream did lives in the sensorium or its untagged transcript, never in a summarized peer message. Compressing source into a payload requires extending the schema, which is the design-review choke point. **Code-as-truth** is the pm-on-pm specialization of this general invariant: review reads the diff via ArtifactRef, impl does not hand off an "impl summary."
3. **Prompts and messages are typed.** Today's `prompt_gen.py` string-template functions become `InputType` classes with explicit input dataclasses. The same typing discipline that catches missing fields on outputs catches missing fields on inputs.
4. **Artifacts and instructions are typed.** `RegressionSpec`, `ImplInstructions`, `TestFixture`, `MockSpec`, `QAScenarioRef`, `RepoCheckout`, `GitDiffAtSha` etc. are typed dataclasses (`Payload` subclasses) that compose into both `Emission` payloads and `InputType` inputs. No loose strings on the boundary.
5. **Persistence has two modes: keep-warm and log-replay regen.** No reliance on runtime-internal snapshot/resume (`claude --resume`, container snapshots, model session ids). The mind keeps streams warm when it can, and rebuilds them from typed inputs when it can't. Log-replay always works for any runtime — including ones where pm has no visibility into the runtime's internal state. This is what makes the abstraction portable across Claude versions, alternative models, and runtimes that go cold without warning.
6. **Every prompt and message is written assuming context loss.** Streams must work correctly when their conversation context disappears at any point. This sidesteps context-length limits and the need for compaction primitives — the system's prompts and `deliver_message` payloads always carry enough state for the receiver to reconstruct what's relevant. **This is a convention, not a structural invariant** — context-loss resilience is a property of the prompt's content, not something the type system can require. The discipline is enforced by (a) documentation on every `InputType` subclass, (b) the review-prompt audit category in [[plan-quality]] Track A, and (c) pm's existing practice (each watcher tick rebuilds its own context — preserved through the refactor).
6. **Detection is hook OR poll.** `RuntimePlugin` exposes both `on_output(handler)` and `poll_outputs()`; runtimes declare via `capabilities()`. Roles don't care which; the wrapper shims uniformly.
7. **Delivery is preempt OR next-checkpoint.** `Mailbox.post(out, deliver='preempt'|'next-checkpoint')`. Today's idle-prompt mid-session injection is preempt; today's tick-checks-mailbox is next-checkpoint. Both first-class.
8. **Supervisors own visibility and supervision.** Session health, restart, escalation are Supervisor responsibilities, not separate watcher loops or one-off watchdogs.
9. **RuntimePlugin is the only execution seam.** Coordination primitives never reach into runtime internals. Display surface (tmux vs headless) and isolation (host / pm-managed Docker / Anthropic's sandbox-runtime / Anthropic Managed Agents) are orthogonal axes composed inside concrete runtimes. Adding a new isolation mechanism plugs in by implementing the Protocol — zero changes to mailbox wiring, callback registration, persistence policy, or anything else.
10. **Budget is between-stream, not within-turn.** The mind decides which streams to instantiate, when to terminate, and per-mind caps. It does NOT interrupt a stream mid-turn to enforce token limits. Cost telemetry is observed via Emission, governance acts on stream lifecycle.
11. **Idempotency by primary key.** `(stream_id, tag, correlation_id)` is the primary key for emission semantics — duplicate posts coalesce, callbacks fire at most once per key over a registry's lifetime. This is what makes the persistence fallback chain safe: log-replay regen cannot double-fire downstream verdicts.
12. **pm owns every stream's complete log.** The `EmissionLog` (structured) and `StreamTranscript` (raw chat/output) are written by the wrapper as the runtime produces output. We do not depend on Claude Code's internal JSONL transcripts, on tmux pane scrollback, or on any other runtime-internal artifact for the durable record. `RuntimePlugin.on_output` / `poll_outputs` is the canonical source; the wrapper tees into pm's own files. This is what lets `Mind.transcript_of(stream_id)` and `Mind.log_of(stream_id)` work identically across `TmuxHostRuntime`, `TmuxContainerRuntime`, `RawApiRuntime`, `ManagedAgentRuntime`, and `TmuxSandboxRuntime`, and what survives runtime upgrades / format churn.
13. **Mind primitives serve mind-layer concerns; runtime IPC stays in the runtime/TUI layer.** `Emission` + `Mailbox` are stream-to-stream and stream-to-human channels; `EmissionLog` is the durable record of stream behavior; `Artifact` is the typed surface for files humans and agents both edit; `ResourceLease` coordinates non-file resources pm orchestrates across streams (tmux windows, workdirs, branches, containers, push-proxy sockets). The test for "should this graduate to a mind primitive?" is whether the data has meaning at the stream/mind layer or only inside the runtime/TUI machinery. Cross-process plumbing between non-stream actors — the TUI cmd-queue file that external CLI processes drop commands into, the home-window refresh-sentinel that pm CLI invocations touch to wake the polling renderer, `cli/helpers.py`'s `trigger_tui_*` family of signal files, `hook_events.py`'s runtime-internal event-type catalog (translated to typed `Emission`s only at the `runtime/hook_entry.py` boundary), the claude session-id registry that TmuxHostRuntime keeps for `--resume` continuity — all stay as runtime IPC. Promoting them to `Mailbox`/`EmissionLog`/`Artifact` would dilute what those primitives mean and pull non-stream code into the mind layer. The flock-replacement story is "every *stream-relevant* coordination concern fits Artifact/ResourceLease/EmissionLog/Mailbox"; runtime-internal flock'd queue files and sentinel-touch notifications are plumbing, not stream coordination.

## The 12 primitives

### 1. `Emission` (dataclass)

Immutable envelope for every structured emission. The only currency of inter-stream communication.

```python
@dataclass(frozen=True)
class Emission:
    tag: str                          # dotted: verdict.review.pass, request.user-attention.merge-conflict
    payload: dict                     # schema-validated, contains Payload instances as typed fields
    stream_id: str
    correlation_id: Optional[str]
    ts: datetime
    visibility: VisibilityTier        # enum: private | user_internal | public | Party(project_id) — default private
    schema_version: str               # pinned schema version of (tag, payload type)
    dedup_key: Optional[str]          # optional content-hash dedup beyond (stream_id, tag, correlation_id)
    def log_ref(self) -> LogRef
```

- **Tag namespace** is the typed `TagRegistry` (see "Typed sibling-sets" below) — absorbs pr-1d8b2b7's VerdictRegistry. Each tag is a typed `Tag(name, payload_schema, source_role, schema_version)` record. `EmissionLog.append` validates against the registry; unregistered tags fail.
- **Visibility tier** is enforced by within-mind Mailbox routing (a receiver scoped to `user-internal` cannot subscribe to `private`) and is the structural backing for plan-collaboration's quiet-defaults invariant. Cross-mind enforcement (refuse to transmit below recipient party's authorized tier) lives in plan-collaboration's Transport layer at the publish seam.
- **Idempotency primary key** is `(stream_id, tag, correlation_id)`. Duplicate posts coalesce in `EmissionLog`; `CallbackRegistry` handlers fire at most once per unique key over their registration lifetime. `dedup_key` is an optional content-hash override for cases where the same logical emission carries different correlation_ids across resumes.

### 2. `InputType` (Protocol)

Typed prompt/message renderer — the structured-input counterpart to `Emission`.

```python
class InputType(Protocol):
    kind: Literal['system', 'message']     # boot-time system prompt vs mid-session message
    inputs: type                            # the dataclass type render() accepts
    schema_version: str                     # pinned version for log-replay fidelity
    def render(self, inputs) -> str
    def required_capabilities(self) -> set[str]   # e.g. {'repo_mount', 'shell_exec'}
    @classmethod
    def upgrade(cls, prior_payload: dict, prior_version: str) -> dict:    # optional migration hook
        ...
```

**Concrete classes live in the same file as the Stream subclass that uses them.** `pm_core/streams/impl.py` contains both `ImplStream` and `ImplSystemPrompt` (plus any `ImplMessage*` classes for typed mid-session messages). Same for every other role. There is no separate `pm_core/prompts/` directory. Today's `prompt_gen.py` (2326 lines), `bug_fix_prompts.py`, `qa_finalize_prompt.py`, `regression_prompts.py`, `spec_gen.py` extract into typed `InputType` classes that live alongside their consuming Stream subclass. Cross-stream reusable text fragments (tui_section, sync_tips, beginner_addendum, filing_addendum, signoff_qa_scenarios_block, etc.) live in `pm_core/streams/_shared_prompts.py` and are imported by the `InputType` subclasses that need them.

```python
@dataclass
class ReviewSystemPromptInputs:
    diff: GitDiffAtSha                       # Payload, not a peer summary
    prior_findings_log_query: LogQuery
    notes_for_prompt: str

class ReviewSystemPrompt(InputType):
    kind = 'system'
    inputs = ReviewSystemPromptInputs
    def render(self, i): ...
```

### 3. `Payload` (Protocol)

Base for typed dataclasses that compose into both `Emission` payloads and `InputType` inputs.

```python
class Payload(Protocol):
    id: str
    kind: str
    schema_version: str
    def to_payload(self) -> dict
    @classmethod
    def from_payload(cls, data: dict) -> 'Payload'
    @classmethod
    def upgrade(cls, prior_payload: dict, prior_version: str) -> dict:    # optional migration hook
        ...
```

Starter set (lives in `pm_core/payloads/`): `RegressionSpec`, `ImplInstructions`, `TestFixture`, `MockSpec`, `QAScenarioRef`, `RepoCheckout`, `GitDiffAtSha`, `LogQuery`, `ContainerSnapshot`, `TranscriptSlice`, `FailureReason`. Each carries typed references to canonical content — sha + path + range, log-query, container snapshot id — never peer-summarized prose.

`FailureReason` carries the typed termination cause:

```python
@dataclass
class FailureReason(Payload):
    kind: TerminationReason          # enum below
    detail: str
    exit_code: Optional[int]
    retryable: bool
```

`TerminationReason` enum (in `pm_core/mind/lifecycle.py`):

```python
class TerminationReason(StrEnum):
    completed_normally = 'completed_normally'
    user_killed = 'user_killed'
    cancelled = 'cancelled'              # parent cancel cascade
    timed_out = 'timed_out'
    crashed = 'crashed'
    oom = 'oom'
    network_lost = 'network_lost'
    budget_exhausted = 'budget_exhausted'
    paywall_inaccessible = 'paywall_inaccessible'
    model_refusal = 'model_refusal'
```

Carried on the `stream.lifecycle.terminated` Emission payload; Supervisor.supervise emits it. Concrete RuntimePlugins map their failure modes to it.

### 4. `EmissionLog` (concrete)

Per-stream append-only queryable log. First-class durable state; survives runtime swaps and process restarts. SQLite-backed at `pm/.mindlog.db`.

```python
class EmissionLog:
    def append(self, out: Emission) -> LogRef
    def query(self, tags: list[str]=None, since: ts=None, where: dict=None, last_n: int=None) -> list[Emission]
    def latest(self, tag: str) -> Optional[Emission]
    def slice(self, ref: LogRef, around: int=0) -> list[Emission]
```

Every `Emission` is appended here before being routed to any subscriber — the log is the durable record, mailbox routing is derived.

`(stream_id, tag, correlation_id)` is the primary key. `append()` is idempotent: a duplicate emission (same key) returns the prior `LogRef` and emits no new mailbox routing. This is what keeps the persistence fallback chain safe on resume — log-replay regen cannot double-fire downstream callbacks.

### 5. `Mailbox` (concrete)

Named, addressable channel. Fans `Emission`s from one publisher to N subscribers on their own clock.

```python
class Mailbox:
    name: str
    allowed_posters: Optional[set[str]]   # role names or stream_ids; None = open (today's default)
    allowed_subscribers: Optional[set[str]]

    def post(self, out: Emission,
             deliver: Literal['preempt', 'next-checkpoint'] = 'next-checkpoint',
             supersedes: Optional[LogRef] = None) -> MsgId
    def subscribe(self, handler, tag_glob: str = '*') -> SubId
    def stream(self, filter_tag: str = '*') -> AsyncIterator[Emission]
    def latest(self, tag: str = None) -> Optional[Emission]
    def list_glob(self, pattern: str) -> list[str]
```

**Within-mind authority.** `allowed_posters` and `allowed_subscribers` give per-channel ACL for sensitive within-mind mailboxes (e.g. only the signoff-router can post to `merge:trigger`; only the meta-development stream can subscribe to `runtime.host-override`). `None` preserves today's open default. The graph stamps `Emission.stream_id` at emit so posters cannot self-attest a different identity. Cross-mind identity attestation is plan-collaboration's concern.

**Visibility-aware routing.** A subscriber whose effective visibility tier is below the `Emission.visibility` of an incoming message does not receive it. This is the structural backing for plan-collaboration's quiet-defaults invariant within a single mind; cross-mind enforcement happens at plan-collaboration's Transport layer (publishing an Artifact whose visibility is below the recipient's authorized tier raises before any data crosses the wire).

- **preempt** — receiver Stream interrupts current turn (today's idle-prompt injection).
- **next-checkpoint** — queues until receiver naturally pulls (today's tick-checks-file).

A receiver's Stream declares which modes it accepts per tag-glob; a `preempt` post to a receiver that doesn't accept preemption on that tag falls through to `next-checkpoint` (never silently dropped).

Default impl is in-process; swap for Redis/NATS to span containers and machines without role-code changes.

**Channel naming is typed.** Mailbox names compose via the `Channel` value-object hierarchy (see "Typed sibling-sets" below): `Mind.mailbox(PRChannel(42, 'review-verdicts'))` instead of `Mind.mailbox('pr:42:review-verdicts')`. `Mailbox.name` remains a string for serialization and glob subscription, but call sites construct channels type-safely.

### 6. `CallbackRegistry` (concrete)

Generalizes today's `poll_for_verdict` loop.

```python
class CallbackRegistry:
    def on(self, tag: str, handler, from_stream: str = None,
           where: Callable = None, once: bool = False,
           deliver: Literal['preempt', 'next-checkpoint'] = 'next-checkpoint') -> CbId
    def wait_for(self, tag: str, *, from_stream: str = None,
                 not_before: Optional[datetime] = None,
                 predicate: Optional[Callable[[Emission], bool]] = None,
                 grace_period: Optional[timedelta] = None,
                 timeout: Optional[float] = None) -> Emission
    def cancel(self, cb: CbId) -> None
```

Implemented over `Mailbox` + `EmissionLog`; not a separate transport.

`wait_for` grace + predicate eliminate today's hand-rolled `VERDICT_GRACE_PERIOD` post-emit timestamp filters scattered across watchers, review-loop, QA verification, QA finalize, and QA scenario:

- `not_before` — first match must have `ts >= not_before` (debounce premature parses).
- `grace_period` — first match must be `grace_period` past wait_for start; matches arriving earlier are buffered and revisited after the window.
- `predicate` — content-aware filter (e.g. payload state field equals 'pass', confidence above threshold).

`on(...)` handlers fire at most once per `(stream_id, tag, correlation_id)` over the callback's lifetime — same idempotency primary key as the log. This is what makes the persistence fallback chain safe.

### 6b. `StreamTranscript` (concrete)

Per-session append-only raw chat/output stream. Stores **everything the runtime emitted** — agent prose, tool calls, tool results, stderr — that isn't a structured `Emission`. The complement to `EmissionLog`: tagged outputs go to the log, untagged free text goes to the transcript.

```python
class StreamTranscript:
    def append(self, chunk: ChatChunk) -> TranscriptRef
    def read(self, since: ts = None, until: ts = None) -> Iterator[ChatChunk]
    def tail(self, n: int = 100) -> list[ChatChunk]
    def grep(self, pattern: str, regex: bool = False, after_lines: int = 0, before_lines: int = 0) -> list[TranscriptSlice]
    def slice(self, start: TranscriptRef, end: TranscriptRef) -> TranscriptSlice
    def ref_at(self, ts: datetime) -> TranscriptRef
```

The `RuntimePlugin`'s output stream emits both `Emission`s and untagged `ChatChunk`s; `Stream` routes the first to `EmissionLog` + Mailbox, the second to `StreamTranscript`. Both are durable across runtime swaps; both are queryable from other streams via `Mind.transcript_of(stream_id)` and `Mind.log_of(stream_id)`.

**The transcript is pm-owned, not Claude-owned.** Today pm reads Claude Code's internal JSONL transcripts (`~/.claude/projects/<name>/transcripts/*.jsonl`) via `pm_core/verdict_transcript.py` to reconstruct what a session said. That is fragile — the format can change, the files can be GC'd, and runtimes other than Claude Code don't produce them at all. Under this refactor, `StreamTranscript` is written by the wrapper as the runtime emits output: `RuntimePlugin.on_output(handler)` (or `poll_outputs()`) is the canonical source, the wrapper tees every `ChatChunk` into the per-stream append-only file at `pm/.transcripts/<stream_id>.log`. The wrapper's record is the authoritative record of what the stream said; Claude Code's internal transcripts become an implementation detail of `TmuxHostRuntime` / `TmuxContainerRuntime` that pm no longer reads from.

This makes the transcript portable across runtimes: `RawApiRuntime`, `ManagedAgentRuntime`, `TmuxSandboxRuntime` all feed the same `on_output` stream, all produce the same shape of `StreamTranscript`. Other streams reading the transcript via `Mind.transcript_of(stream_id)` get the same surface regardless of which runtime produced it.

Storage backend is intentionally separate from the structured log — transcripts are flat per-stream files (one append-only buffer per stream id), the log is SQLite. The volume and access patterns differ by orders of magnitude.

`TranscriptSlice` is a first-class `Payload` — a `Emission` payload can carry `TranscriptSlice(stream_id, start_ref, end_ref)` as typed evidence. A verifier emits `verdict.qa-verify.refuted` with `evidence_slices: list[TranscriptSlice]` pointing into the scenario worker's raw transcript; the downstream consumer can read the slices directly. **This is the code-as-truth path for "I want to see what they actually said"** — the evidence is canonical raw output, not paraphrased.

Code-as-truth tension resolved: reading another stream's transcript is *not* the peer-summary anti-pattern. The transcript is canonical source-of-truth output (equivalent to reading stderr or a log file the agent wrote); summarization would be a downstream consumer collapsing that into prose and passing it on. The invariant is "no payload field carries summarized prose," not "no agent reads another's output." The transcript primitive makes the reading typed and auditable rather than scraping a tmux pane buffer.

### 7. `AttentionRequest` (concrete)

First-class human escalation. Reserved tag prefix `request.user-attention.*`. Resolves through normal mailbox machinery — dashboard is a Mailbox subscriber.

```python
class AttentionService:
    def raise_(self, tag: str, payload: dict, blocking: bool = False,
               reply_to: str = None, expires_at: ts = None) -> AttId
    def await_resolution(self, att: AttId) -> Emission
    def resolve(self, att: AttId, reply: dict) -> None
```

Replaces today's INPUT_REQUIRED-stalls-the-pane pattern. Watcher raises, hibernates, dashboard surfaces, human resolves, callback wakes the stream.

**Compare with Takeover semantics** (see Stream section): `AttentionRequest` is the agent asking the human for input on a typed question, expecting a typed reply. Takeover is the human silently substituting as the speaker on a running stream — no typed question, no typed reply, the loop is paused for an indefinite period. Both exist; they don't replace each other.

### 8. `RuntimePlugin` (Protocol)

The only execution seam. Coordination never reaches past this boundary.

```python
class RuntimePlugin(Protocol):
    def instantiate(self, stream_id: str, system_prompt: str) -> RuntimeInstance
    def send_input(self, instance, payload: str | dict) -> None
    def on_output(self, instance, handler) -> SubId         # hook-based detection
    def poll_outputs(self, instance) -> list[Emission]      # poll-based detection
    def terminate(self, instance) -> None
    def capabilities(self) -> RuntimeCapabilities
        # interactive_tty: bool, repo_mount: bool, shell_exec: bool,
        # supports_hooks: bool, supports_poll: bool,
        # reports_cost: bool,
        # network_egress: bool, sandboxed_bash: bool,
        # max_inline_input_bytes: int,
        # attach_hint: Optional[str]
```

**No snapshot/resume in the Protocol.** Per design principle 5, the wrapper does not depend on runtime-internal snapshot/resume. The Protocol intentionally omits a `snapshot()` method and a `snapshot=` parameter on `instantiate()`. If a concrete runtime internally optimizes warm-restart behavior, that's its private business — the wrapper neither sees nor relies on it. Persistence above the Protocol is `keep-warm` (the runtime instance stays alive between events) or `log-replay regen` (rebuild from typed inputs into a fresh instance). Both work for any runtime.

**Large-prompt contract.** `send_input(payload)` MUST handle payloads larger than the underlying transport limit (tmux argv ~16KB, container exec ulimits). Spool-to-host-file fallback is acceptable: the runtime materializes the payload to a host-visible scratch path (`pm/prompts/<sid>.txt`) and instructs the runtime to read it (`$(cat ...)` for shell-based runtimes, file-attach for managed runtimes). Callers detect spooling via `capabilities().max_inline_input_bytes`; InputType.render() can negotiate brief vs. verbose against target capabilities.

**Cost telemetry.** Runtimes that can report token/cost usage set `reports_cost=True` and emit `telemetry.cost` Emission instances (payload: `UsageEvent` Payload — input_tokens, output_tokens, cost_usd, model) per turn. Consumed by Budget primitives (below).

**Two orthogonal axes.** Display (tmux pane vs headless) and isolation (host / pm-managed Docker / Anthropic-provided sandbox) compose independently — `RuntimePlugin` implementations are concrete points in that grid, not alternatives along one axis. Today pm has *both* containerized and uncontainerized sessions, and both run in tmux windows; the tmux pane is the interaction/display surface, containerization is an isolation policy on top.

Concrete implementations:

- `TmuxHostRuntime` — claude in a tmux pane on the host. Today's default; wraps `launch_pane` / `claude_launcher.py`.
- `TmuxContainerRuntime` — claude in a tmux pane that execs into a pm-managed Docker container (per-PR / per-scenario containers from plan-qa). Wraps today's `pm_core/container.py` glue. Same tmux interaction surface as `TmuxHostRuntime`; the difference is the isolation policy.
- `TmuxSandboxRuntime` — claude in a tmux pane wrapped by `@anthropic-ai/sandbox-runtime` (Anthropic's beta OS-level sandbox via Seatbelt on macOS / bubblewrap on Linux). Same tmux UX, with deny-by-default filesystem + network isolation, no Docker required. Useful where pm's container is overkill but host execution is too permissive.
- `RawApiRuntime` — headless loop over the Anthropic SDK. No tmux, no isolation beyond the host. Use case: wake-on-callback ticks where no human is attached.
- `ManagedAgentRuntime` — Anthropic Managed Agents (available today; April 2026 release). Two sub-variants depending on platform config: cloud sandbox (Anthropic-hosted gVisor container) or self-hosted sandbox (Anthropic orchestrates, pm provides an environment worker). Headless from pm's perspective; pm interacts via Managed Agents' polling/webhook contract.
- `HybridRuntime` — composes two runtimes under one Stream id (e.g. `TmuxHostRuntime` for interactive sessions when a human is attached, `RawApiRuntime` for headless wake-ups, sharing one log).
- `FakeClaudeRuntime` — test impl. Today's `FakeClaudeSession` scripted-verdict machinery maps directly onto this.

Out of scope as a plugin: **Claude Code on the Web** (Anthropic-hosted cloud VM). UI-only trigger, not programmatically launchable from pm, so it cannot implement the Protocol. **Sandboxed Bash tool** (Claude Code's built-in Seatbelt/bubblewrap sandbox for Bash commands only) — too narrow to model as a RuntimePlugin; it's a property of how a runtime configures Claude Code, not a runtime in itself. Roles that need it set a capability flag (`sandboxed_bash=True`) which `TmuxHostRuntime`/`TmuxContainerRuntime`/`TmuxSandboxRuntime` honor by passing the appropriate Claude Code config.

`RuntimeCapabilities` lets roles declare hard requirements (`interactive_tty=True` for `guide-setup`, `repo_mount=True` for impl, `network_egress=False` for sensitive QA, `sandboxed_bash=True` for untrusted-code runs); the graph rejects incompatible plugin assignments at session-open. The capability surface is also how a role expresses "I need isolation but don't care which mechanism" — the graph picks `TmuxContainerRuntime` or `TmuxSandboxRuntime` based on project policy.

### 9. `Stream` (concrete)

Stable, addressable identity for a logical stream across the full PR/plan/project lifecycle. Owns the persistence fallback chain.

```python
@dataclass
class StreamPolicy:
    persistence: list[str] = ('keep-warm', 'log-replay')   # log-replay = rebuild from typed inputs; no runtime-internal snapshot reliance
    budget: Optional[BudgetPolicy] = None
    cascade_on_parent_terminate: bool = True

class Stream:
    id: str                              # composed as role:instance_key; stable across runtime swaps
    role: str                            # discoverable label for Mind.streams(role=)
    instance_key: str                    # disambiguator within a role (pr id, scenario idx, cycle id, counter, random)
    log: EmissionLog
    transcript: StreamTranscript        # raw chat/output stream
    policy: StreamPolicy
    parent: Optional['Stream']
    control_owner: ControlOwner          # agent | human — see Takeover below

    def emit(self, tag: str, payload: dict, mailbox: Optional[str] = None,
             deliver: Literal['preempt', 'next-checkpoint'] = 'next-checkpoint',
             visibility: VisibilityTier = 'private',
             correlation_id: Optional[str] = None,
             dedup_key: Optional[str] = None) -> LogRef
    def deliver_message(self, message: InputType,                     # subsequent turn on SAME conversation
                        inputs: Payload,
                        deliver: Literal['preempt', 'next-checkpoint'] = 'next-checkpoint') -> None
    def resume(self) -> None             # walks the fallback chain
    def hibernate(self) -> None          # tear down runtime instance, keep id+log+transcript; subsequent resume() walks the fallback chain
    def subscribe(self, mailbox: str, handler) -> SubId
    def on(self, tag: str, handler, from_stream: str = None, **kw) -> CbId
    def request_attention(self, tag: str, payload: dict, blocking: bool = False) -> AttId

    # cancellation + cleanup
    def spawn_child(self, id: str, role: str, runtime: RuntimePlugin,
                    policy: StreamPolicy, system_prompt: InputType, inputs: Payload) -> 'Stream'
    def cancel(self, reason: TerminationReason) -> None
    def on_cancel(self, handler: Callable[[TerminationReason], None]) -> CbId

    # takeover (see "Takeover semantics" below)
    def request_human_takeover(self, requester: str, reason: str = '') -> TakeoverHandle
    def release_human_takeover(self, handle: TakeoverHandle) -> None

    # liveness query — callers check before deliver_message when they need to differentiate
    def status(self) -> LifecycleState    # never_started | queued | running | hibernated | terminated — same enum as Supervisor.state()

    # phase-state rendering — InputType.render() includes this in the system prompt for any multi-phase role
    def render_phase_context(self) -> str
        """Query EmissionLog for the latest phase.* emission and return a 'Current phase: X. Prior steps: …'
        prelude. Empty string for roles with no phase tags. This is how restartability and phase awareness
        compose: the prompt always re-renders against the durable log, so a cold restart sees the same
        phase context a keep-warm continuation would. See [[plan-quality]] Track A: phase-awareness audit."""

    # persistence policy is the fallback chain, in order:
    # 1. keep-warm           — runtime stays alive between events
    # 2. log-replay regen    — universal: rebuild system prompt by replaying InputType inputs from log; instantiate fresh runtime. The wrapper never depends on runtime-internal snapshots — those are fragile across Claude versions, alternative models, and runtimes that go cold without warning.
```

`resume()` walks the chain top-down; first available wins. Log-replay is always available (the log is durable), which is what makes the wrapper truly runtime-portable.

**Session identity = role + instance_key.** Every session has a `role` (discoverable, shared across instances of the same kind: `impl`, `review`, `qa-scenario`, `citation-audit`, `plan-add`) and an `instance_key` that disambiguates within the role. Today's natural instance keys: `impl:42` (PR 42), `qa-scenario:42:s3` (PR 42 scenario 3), `review:42:c2` (PR 42 review cycle 2), `plan-add:plan-quality` (one per plan). The full `id` is `role + ':' + instance_key`.

**Blind / fresh-cycle sessions fall out of instance_key choice, not a separate flag.** A role that must have no memory of prior cycles — blind reviewer, fresh QA scenario, per-cycle citation-audit conductor, plan-add invoked with fresh-flag — picks a new `instance_key` per invocation (incrementing counter, fresh random, or a derivable key like `:c<cycle_id>`). With a new id, the log/transcript lookup finds nothing to rehydrate, and the fallback chain naturally instantiates cold. The blindness is structural via addressing, not a flag. The log is still appended under the new id (audit trail), but no prior session's log is consulted.

**Parent/child cancellation cascade.** `spawn_child()` creates a child handle whose lifecycle is linked to the parent. When the parent terminates (for any reason in `TerminationReason`), children with `cascade_on_parent_terminate=True` receive `cancel(parent.termination_reason)`. `on_cancel(handler)` registers pre-terminate cleanup (e.g. `git merge --abort` for the merge-conflict-resolver, container teardown for QA scenarios). Supervisor exposes `cancel_correlation(correlation_id)` to terminate every session sharing a correlation_id at once.

**Subsequent turns on the same conversation.** `deliver_message(message, inputs)` renders the typed `InputType` against its inputs dataclass and feeds the rendered text to `RuntimePlugin.send_input` on the *same* runtime instance. The receiver sees the new input as a turn in the same conversation context as everything before. This is the mechanism the shape-improvements audit validated for ~14 of 24 roles: instead of spawning a fresh session per event (verdict, tick, review iteration, signoff re-run), the role becomes one persistent stream and successive events arrive as `deliver_message` on the same stream. Context accumulates correctly; verdict-of-verdict reasoning becomes possible; tokens stop being spent re-loading evidence on every event.

`CallbackRegistry` handlers can compose either pattern: a handler that spawns a new stream calls `mind.stream(role_class=..., ...)`; a handler that delivers to an existing one calls `existing_stream.deliver_message(...)`. Both are first-class.

### Persistent-stream-default shape (guidance, not invariant)

The shape-improvements audit found that ~14 of 24 implemented roles want persistent-per-instance semantics rather than spawn-per-event. The default shape recommendation for new role implementations:

1. **Identify the natural instance scope** — per-PR, per-scenario, per-plan, per-project, per-cycle. Use that as the `instance_key`.
2. **Make the role a single persistent stream per instance key**, woken via `Mind.schedule(...)` (tick-driven roles) or `CallbackRegistry.on(...)` (event-driven roles).
3. **Subsequent turns arrive via `deliver_message`** on the same stream, not as new stream instantiations.
4. **Peers consume typed Emissions and ArtifactRef-pointed evidence** rather than receiving paraphrased summaries.

Roles that should *not* be persistent (`LoopMode.kill_restart` on their primary input tag, or new `instance_key` per invocation):

- **`ReviewStream`** — review iterations are intentionally fresh-start. A new reader finds issues the accumulated reviewer misses. This is design intent, not a limitation. `review.requested` carries `LoopMode.kill_restart` in `ReviewStream.loop_mode_overrides`.
- **Truly one-shot artifact producers** — plan-add, plan-import, qa-author. The role completes one task and is done.
- **Human-paced single-conversation sessions** — discuss-session.
- **Leaf workers whose context genuinely resets every tick** — auto-start-watcher (each tick reads project state fresh).

The audit identified these (auto-start-watcher, qa-author, discuss, discovery-supervisor, plan-add, meta-development) as NO_CHANGE / NICE-TO-HAVE — the abstraction correctly accommodates them too.

**The token-savings claim is unverified.** The shape-improvements audit argued persistent streams reduce token cost because tool calls don't repeat. The maintainer is skeptical because context accumulates over time, and accumulated-context turns may cost as much as or more than fresh-start turns. Worth measuring during the streams PR (PR5/6 in plan-mind's sequence) on a couple of HIGH_LEVERAGE roles before committing the rest of the codebase to the pattern. The architectural benefits (verdict-of-verdict reasoning, takeover-friendly, simpler peer subscription) are real regardless.

### Takeover semantics

A human can take over a running stream — pause its scheduled re-fires, talk freely on the same conversation, then release control and the loop resumes from where it was. Today missing from pm; the user explicitly flagged this gap.

```python
class ControlOwner(StrEnum):
    agent = 'agent'       # default — runtime is autonomously driven
    human = 'human'       # human is the speaker; scheduled emissions pause / buffer

@dataclass(frozen=True)
class TakeoverHandle:
    stream_id: str
    requester: str
    acquired_at: datetime
```

**Mechanics.**
- `Stream.request_human_takeover(requester, reason)` flips `control_owner` to `human`, emits `stream.control.taken-over`. The runtime stops receiving agent-driven `send_input` (or other automated turns); a human can `send_input` freely via the TUI.
- Scheduled emissions targeting this stream (via `Mind.schedule(...)`) and Mailbox messages with `deliver='next-checkpoint'` are **buffered** rather than delivered; preempt-mode emissions still pass through *unless* the receiver opts out for the takeover window (per-tag accept-policy). Emergency `request.user-attention.critical` tags always pass.
- `Stream.release_human_takeover(handle)` flips control back to `agent`, emits `stream.control.released`, and replays buffered emissions in arrival order (subject to the buffer policy — FIFO, coalesce-by-tag, drop-old, max-N).
- TUI surface: a keybinding on any pane representing a stream (`p` for "pause and take over"); status icon shows control owner; release emits an Emission that supervisors subscribe to so any paused loops resume.

**Buffer policy** (declared on `StreamPolicy`):

```python
@dataclass
class TakeoverBufferPolicy:
    on_overflow: Literal['drop_oldest', 'coalesce_by_tag', 'reject'] = 'coalesce_by_tag'
    max_buffered: int = 100
    bypass_tags: set[str] = frozenset({'request.user-attention.critical'})
```

**Why takeover ≠ AttentionRequest.** AttentionRequest is "agent asks human for input on a typed question" — the agent is still in control, blocked on a typed reply that closes the loop. Takeover is "human silently substitutes as the speaker on a running stream" — the agent loop is paused, the conversation is fully human-driven for an indefinite period, the human ends it on their own time. Both exist; they don't replace each other.

### Tag-driven loop semantics

Streams subscribe to tags. When an emission with tag `T` arrives at an *existing* stream `S`, what should happen — continue the same conversation, or kill and restart with a fresh `instance_key`? The decision is per-tag, with per-stream overrides:

```python
class LoopMode(StrEnum):
    continue_existing = 'continue_existing'   # deliver_message to the existing stream
    kill_restart = 'kill_restart'             # terminate the existing stream, instantiate fresh with new instance_key

@dataclass
class Tag:
    name: str
    payload_schema: type[Payload]
    source_role: type[Stream]
    schema_version: str = '1'
    default_loop_mode: LoopMode = LoopMode.continue_existing

class Stream:
    loop_mode_overrides: ClassVar[dict[str, LoopMode]] = {}   # per-tag-glob overrides
```

Dispatch logic (in `CallbackRegistry` / `Mind.schedule` delivery):

```python
mode = receiver.loop_mode_overrides.get(tag.name, tag.default_loop_mode)
if mode == LoopMode.continue_existing and receiver.status() == LifecycleState.running:
    receiver.deliver_message(message, inputs)
elif mode == LoopMode.kill_restart:
    receiver.cancel(TerminationReason.completed_normally)
    mind.stream(role=type(receiver), instance_key=next_instance_key(receiver), ...)
```

**Why this is per-tag, not per-stream-class.** A given Stream subclass might accept ticks (continue_existing) AND a "blind reset" tag (kill_restart). The tag carries the semantics of what the emission means; the stream may override per-tag.

**ReviewStream uses `kill_restart` for review iterations.** Review's whole point is that a fresh reader finds issues the accumulated reviewer misses. The user explicitly carved review out of the persistent-stream-default pattern: review iterations should not continue the same context. Concretely:

```python
class ReviewStream(Stream):
    loop_mode_overrides = {'review.requested': LoopMode.kill_restart}
```

Watchers use `continue_existing` (the default) for their tick tags — the value of a watcher is exactly its accumulated context across ticks.

### Liveness checks on send

When a caller wants to `deliver_message` to a stream they hold a handle to, they can query liveness first:

```python
class LifecycleState(StrEnum):
    never_started = 'never_started'   # declared (or referenced by id) but never instantiated
    queued = 'queued'                 # admission-controlled by Supervisor.set_quota; waiting for a slot
    running = 'running'               # runtime instantiated, receiving inputs / emitting
    hibernated = 'hibernated'         # paused; resumes via keep-warm or log-replay (see Stream.resume)
    terminated = 'terminated'         # final; cannot be resumed (a new instance_key starts a fresh stream)

# Caller-side guard:
if existing.status() == LifecycleState.terminated:
    new = mind.stream(role=ReviewStream, instance_key=f'review:{pr_id}:c{cycle+1}', ...)
    new.deliver_message(message, inputs)
else:
    existing.deliver_message(message, inputs)
```

`deliver_message` itself: if the stream is `hibernated`, auto-resumes via the policy chain (keep-warm if available, else log-replay regen). If `terminated`, raises `StreamTerminated`. If `running`, delivers directly.

Most callers will go through the `CallbackRegistry` dispatch which handles `LoopMode` automatically; direct `deliver_message` callers (the TUI, debugging) use the liveness guard explicitly.

### 10. `Mind` (concrete)

Top-level registry / factory. The only object roles import directly.

```python
class Mind:
    # stream creation / lifecycle — role is a Stream subclass, not a string
    def stream(self, role: type[Stream], instance_key: str,
                runtime: RuntimePlugin, policy: StreamPolicy,
                inputs: Payload) -> Stream                    # input_type taken from role class
    def shutdown(self, stream_id: str) -> None

    # discovery — by Stream subclass, not by string
    def streams(self, role: Optional[type[Stream]] = None,
                 alive_only: bool = True) -> list[Stream]
    def list_transcripts(self, since: Optional[datetime] = None) -> list[tuple[str, StreamTranscript]]

    # channels + records — Channel value object preferred over raw string
    def mailbox(self, channel: Channel | str) -> Mailbox
    def log_of(self, stream_id: str) -> EmissionLog
    def transcript_of(self, stream_id: str) -> StreamTranscript

    # scheduling — emits an Emission on a chosen mailbox at the right time
    def schedule(self, tag: str, cron_or_interval: str | timedelta,
                 target: Channel, payload: dict,
                 visibility: VisibilityTier = VisibilityTier.private) -> ScheduleId
    def cancel_schedule(self, sid: ScheduleId) -> None

    # supervision
    def manager(self, kind: str) -> Supervisor

    # services
    callbacks: CallbackRegistry
    attention: AttentionService
```

Single-process today; replace internals (Mailbox impl, log store) to span machines without role-code changes.

**`Mind` is the singleton per project.** One pm checkout runs at most one `Mind`. The Mind is the single source of truth for what streams exist, what they've emitted, what their transcripts contain, what's hibernated, what's scheduled. Every UI surface (TUI, web dashboard, popup picker, status spinner), every CLI command (`pm pr list`, `pm watcher status`, `pm review`), and every other stream (`Mind.streams(role=X)` discovery from another stream's handler) goes through the Mind to read or mutate state.

**TUI is a thin layer over the Mind.** It does not own any state of its own beyond rendering / input-event-routing. Concretely:

- TUI reads via `Mind.streams(role=)`, `Mind.log_of(stream_id)`, `Mind.transcript_of(stream_id)`, `Mind.supervisor(...).known_streams()`, etc. — the same surface any stream uses.
- TUI subscribes to `Mind` lifecycle and emission events via `CallbackRegistry.on(...)` (e.g. `mind.callbacks.on('stream.lifecycle.*', tui.on_lifecycle)`) to refresh on changes — no polling.
- TUI writes via typed actions: `stream.deliver_message(...)`, `stream.request_human_takeover(...)`, `mind.attention.resolve(...)`, `mind.stream(role=..., instance_key=..., ...)` — no special TUI-only mutation path.
- TUI keybindings derive from the typed `PRActionTUIType` hierarchy in `pm_core/tui/pr_actions/` (one subclass per PRActionStream), with `__init_subclass__` validation plus a TUI-startup completeness check against `PRActionStream.__subclasses__()` — not hard-coded.
- TUI panes representing streams subscribe to the stream's `StreamTranscript` for live display.

This means the TUI is replaceable: a web dashboard, voice interface, or remote-control session can substitute by reading/writing through the same `Mind` surface. The architecture validates by being able to run `pm` with `--no-tui` and have everything still work — the TUI becomes one of many possible views.

**Short-lived external CLI processes** (popup picker, status spinner, `home_window/`) connect to the project's Mind via SQLite read access on `pm/.mindlog.db` (read-only) without instantiating a full Mind instance. Reads of `EmissionLog.query(...)` and lifecycle states are safe in this read-only mode. Writes go through the running Mind via socket or signal (mechanism deferred to the Mind class + bootstrap PR which lands the singleton enforcement).

**Role discovery.** `Mind.streams(role=ReviewStream, alive_only=True)` returns every live stream with that role; `Mind.streams(role=None, alive_only=False)` enumerates all known. Replaces today's hardcoded watcher names in watcher-review-session and the per-role mailbox-name parsing scattered across discovery-supervisor / health-check-auditor / summary-agent.

**Scheduling.** `mind.schedule(tag, cron_or_interval, target_mailbox, payload)` emits an `Emission` onto the named mailbox at the right time; consumers wire via `CallbackRegistry.on(...)`. Persisted alongside the log so schedules survive restart. Covers periodic radar runs, summary-at-multi-granularity, session-linker cadence, anchor tournament reruns, health-check sweeps, self-maintenance loops. Today's `BaseWatcher` tick loop becomes `mind.schedule('watcher.tick.<name>', interval='120s', target=Channel.watcher_tick('<name>'), payload={...})`.

**Schedule interaction with Takeover.** When a scheduled emission targets a stream in `ControlOwner.human` state, the emission is buffered per the stream's `TakeoverBufferPolicy` rather than delivered. Buffered emissions deliver in arrival order when the human releases control. Critical-tag emissions (in `bypass_tags`) still deliver.

### 11. `Supervisor` (Protocol)

Owns visibility and supervision over a set of streams. Subsumes today's `pm/watchers/<name>.log`-as-ad-hoc-state, session-health watcher, and supervisor watcher patterns.

```python
# LifecycleState is defined in pm_core/mind/lifecycle.py (see Stream.status documentation above)
# — same StrEnum used by Stream.status() and Supervisor.state(): never_started | queued | running | hibernated | terminated.

@dataclass
class StreamRecord:
    """Lightweight descriptor of a stream the Supervisor knows about, instantiated or not."""
    stream_id: str                       # role:instance_key
    role: str                            # the Stream subclass name
    instance_key: str
    state: LifecycleState
    parent_id: Optional[str] = None
    policy: Optional[StreamPolicy] = None
    last_emission_at: Optional[datetime] = None

class Supervisor(Protocol):
    def known_streams(self) -> list[StreamRecord]
    def state(self, stream_id: str) -> LifecycleState
    def running(self) -> list[Stream]
    def resumable(self) -> list[StreamRecord]      # state == hibernated; resumes via keep-warm or log-replay
    def never_started(self) -> list[StreamRecord]  # declared / referenced but never instantiated
    def health_check(self, stream_id: str) -> HealthReport
    def supervise(self, stream_id: str) -> None    # apply policy: revive hung, restart dead, raise AttentionRequest if stuck
    def on_state_change(self, handler) -> SubId

    # quotas / admission control
    def set_quota(self, scope_glob: str, max_concurrent: int) -> None
    # cancellation
    def cancel_correlation(self, correlation_id: str,
                           reason: TerminationReason = TerminationReason.cancelled) -> None
```

**Lifecycle Emission contract.** Every Supervisor MUST emit `stream.lifecycle.<state>` Emission instances to a well-known mailbox (`mind.mailbox(LifecycleGlobalChannel())`) on each transition. Payload carries `FailureReason` on `terminated` if applicable. This makes lifecycle observability cross-session-addressable via `CallbackRegistry.on('stream.lifecycle.terminated', from_stream='impl:42')` rather than tied to a particular Supervisor's Python handlers. Per-Supervisor `on_state_change(handler)` remains as a convenience over the same stream.

**Quota / admission control.** `set_quota('qa-scenario:*', max_concurrent=4)` caps concurrent runtime instantiation. `Mind.stream(...)` blocks or returns a queued handle (state `queued`) when at cap; emits `session.queued` / `session.admitted` Emission instances. Pairs naturally with `BudgetPolicy` for cost-aware admission.

Concrete Supervisors (all live in `pm_core/supervisors/`):

- `WatcherSupervisor` — owns all watcher streams; supervises tick health.
- `PRStreamSupervisor` — owns all sessions tied to one PR (impl, review, qa scenarios, signoff, merge-resolver). Knows which are running, hibernated-resumable, never-started. Drives the PR lifecycle.
- `PlanStreamSupervisor` — owns plan-add, plan-breakdown, plan-review sessions across a plan's lifetime.
- `MindSupervisor` — top-level Supervisor over Supervisors; the place observability/dashboarding hooks attach.

The TUI watchdog (today's pr-923f22b in current form) becomes a typed `WatchdogPolicy` class (in `pm_core/watchdog/`) that subscribes to `Supervisor.on_state_change(...)`, runs typed health checks on lifecycle anomalies, and raises `AttentionRequest`s into the dashboard mailbox. Not a primitive — a typed consumer of Supervisor state.

## Loop orchestration: where loop semantics live

When a Stream uses `LoopMode.kill_restart` (review iterations, blind QA passes, fresh-cycle plans), each iteration is a brand-new Stream with a fresh `instance_key`. That raises a natural question: **if the participants live one iteration, where does the loop live?**

**The loop lives in the Supervisor that orchestrates the participants.** Not in any Stream's lifetime. Not as a separate Stream subclass. The Supervisor subscribes to the relevant Emissions, decides when to issue the next iteration's emission, and spawns a fresh Stream when needed.

Concrete example — the review loop, owned by `PRStreamSupervisor`:

```python
class PRStreamSupervisor(Supervisor):
    pr_id: int
    review_cycle: int = 0                                # state in the Supervisor, not in any Stream

    def __init__(self, pr_id: int):
        self.pr_id = pr_id
        self.callbacks.on('impl.lifecycle.commit-landed', from_stream=f'impl:{pr_id}',
                          handler=self._on_commit)
        self.callbacks.on('verdict.review.needs-work', handler=self._on_review_needs_work)
        self.callbacks.on('verdict.review.pass', handler=self._on_review_pass)

    def _on_commit(self, em: Emission):
        """Impl landed a commit. Spawn a fresh ReviewStream iteration."""
        self.review_cycle += 1
        self.mind.stream(
            role=ReviewStream,
            instance_key=f'review:{self.pr_id}:c{self.review_cycle}',     # fresh key = fresh stream
            runtime=self.tmux_host_runtime,
            policy=StreamPolicy(...),
            inputs=ReviewSystemPromptInputs(...))
        # Prior review:<pr>:c<N-1> Stream is terminated by kill_restart dispatch; this is fresh start

    def _on_review_needs_work(self, em: Emission):
        """Review found issues. Tell ImplStream what to fix; the loop continues
        when ImplStream commits its fix."""
        impl = self.mind.streams(role=ImplStream, instance_key=f'impl:{self.pr_id}')[0]
        impl.deliver_message(ImplReviewFeedbackMessage(findings_ref=em.payload['findings']))

    def _on_review_pass(self, em: Emission):
        """Review passed. Advance to QA phase."""
        self.mind.stream(role=QaPlanningStream, instance_key=f'qa-plan:{self.pr_id}', ...)
```

Three actors, three lifetimes:

| Actor | Lifetime | What it does |
|---|---|---|
| `ImplStream(impl:<pr>)` | **persistent** for PR's life | Makes commits, responds to review feedback messages |
| `ReviewStream(review:<pr>:c<N>)` | **one cycle** | Reads diff, emits verdict, terminates |
| `PRStreamSupervisor(pr:<pr>)` | **persistent** for PR's life | Orchestrates everything: spawns review iterations, delivers feedback, advances to QA on pass |

The participants don't know they're in a loop. `ReviewStream` is a one-shot run from its own perspective — read the diff, decide, emit verdict, done. `ImplStream` just receives messages and acts on them. The loop is the supervisor's responsibility.

**Per-PR orchestrations beyond review** follow the same pattern:

- **QA scenario fan-out + verification** — on `verdict.review.pass`, spawn `QaPlanningStream`; on `phase.qa-plan.complete`, spawn N `QaScenarioStream`s in parallel; subscribe to per-scenario verdicts; barrier on all PASS or any FAIL.
- **Signoff with HEAD-change re-run** — on `verdict.qa.finalize.pass`, spawn `SignoffStream`; on `pr.head-changed` while signoff running, re-issue `signoff.requested` (kill_restart).
- **Merge with conflict resolution** — on `verdict.signoff.merge`, spawn `MergeStream`; on `merge.conflict.raised`, spawn `MergeConflictResolverStream`; resume merge after conflict resolution.

All of these are code in `PRStreamSupervisor`. The "shape" of each loop is different (linear-cycle vs fan-out-barrier vs retry-with-resolver), so a single `LoopStream` primitive would either be too generic to be useful or just a thin alias for a Supervisor method. We don't introduce one; if we end up reimplementing the same loop pattern across multiple Supervisors, that's an extraction refactor later.

**`PlanStreamSupervisor` works the same way** for plan-lifecycle loops (plan-add → plan-breakdown → plan-review-cycle).

**Why not a separate `LoopStream` Stream subclass:**

- A `LoopStream` would need to know what its participants are (their Stream classes), how to compose them, when to restart vs continue, how to gate on barriers. That's exactly what `Supervisor` does today.
- Pushing loop semantics into a Stream subclass would create a layering problem: Streams represent single conversations / one unit of work; an orchestrator over multiple units isn't a conversation.
- The kill_restart loop mode on a tag is the only Stream-layer primitive needed for loops. Everything else is `Supervisor` orchestration code.

## How Emissions are generated

An Emission can come from three sources. Naming them explicitly because they have different timing characteristics that matter for designing prompts and supervisors.

### 1. Runtime-detected events

The runtime knows when its session boots, when a turn ends, when the runtime instance dies, when token usage crosses a threshold. These are runtime-internal observations the wrapper turns into Emissions:

- `stream.lifecycle.*` (instantiated, running, hibernated, terminated)
- `telemetry.cost` per turn (from `reports_cost`-capable runtimes)
- `stream.fault.runtime-died` (process crash, network loss)
- `session.queued` / `session.admitted` (from Supervisor quota gates)

Driven by `RuntimePlugin` capabilities and `Supervisor` logic. No agent involvement; immediate.

### 2. Mind-internal emissions

The mind itself emits some Emissions without consulting the runtime or the agent:

- `mind.schedule(...)` firing on its cron tick
- `Mailbox.post(...)` driven by another stream's emission cascade
- `attention.resolved.*` when a human resolves an `AttentionRequest` via the dashboard
- `artifact.<name>.changed` when a sensorium Artifact is mutated

Driven by Mind / Mailbox / CallbackRegistry / sensorium. No agent involvement; immediate.

### 3. Agent-written tagged markers extracted from the output stream

**This is how phase emissions and most stream-internal verdicts actually get generated.** The agent does not have a separate emission API; it writes structured-output markers inline in its conversation text. The runtime's `on_output(handler)` (hook-based) or `poll_outputs()` (poll-based) scanner detects these markers and emits the typed Emission to the mind.

**Why this matters:** the agent does not stop after each phase. It generates a spec and keeps going to implementation; the runtime extracts the `phase.impl.spec-proposed` emission from the spec section of the agent's output, the mind routes it to subscribers, and the agent has already moved on. The only natural pauses in the agent's stream are when an `AttentionRequest` is raised (because the prompt instructs the agent to await human input before continuing) or when the turn ends.

The marker format is the same boundary-aware tagged-output format the existing `verdict_transcript.py` + `loop_shared.match_verdict` consume — promoted to a typed extractor on the runtime side. Example (the agent writes this in its conversation; nothing else changes):

```
I've drafted the implementation spec. Here it is for review:

[... spec content ...]

<<<EMISSION phase.impl.spec-proposed>>>
{"spec_artifact_id": "spec:42:impl", "version": 3}
<<<END>>>

Now I'll wait for approval before proceeding. If approved, I'll implement against the spec...
```

The runtime's output scanner detects `<<<EMISSION ... >>>` blocks, parses the tag + payload against `TagRegistry`, and calls `Stream.emit(...)`. The agent's text stream continues unaffected — its output remains the human-readable conversation; the markers are simply parsed alongside.

**Implications:**

- **Prompts must instruct the agent to emit markers at the right points.** This is now an `InputType` documentation responsibility. The prompt explicitly tells the agent: "When you finish the spec, output `<<<EMISSION phase.impl.spec-proposed>>>{...payload...}<<<END>>>`. When you finish implementation and the PR is ready for review, output `<<<EMISSION impl.lifecycle.ready-for-review>>>...`."
- **`ALLOWED_VERDICTS` on each `InputType`** lists the tags the agent is allowed to write — same role as today's `SESSION_TYPE_VERDICTS`, just per-prompt instead of centralized. The extractor validates against this set.
- **Polling cadence** for poll-based runtimes (those without `supports_hooks`) governs how soon a written emission lands in the mind. Default is the runtime's `poll_outputs()` interval; aggressive cadence (~250ms) for runtimes that need responsive verdict detection.
- **Multiple emissions per turn** are common — a long phase-rich turn might emit 3-5 phase markers + a final verdict. The runtime extracts each in order; the mind routes each through Mailbox/CallbackRegistry independently.
- **Failed extraction** (a marker the agent wrote but didn't match any registered tag) → `stream.fault.unknown-tag` emission with the offending text. The agent's stream continues; the malformed marker becomes a flag for prompt-author review.

This is the model `loop_shared.match_verdict` already implements today, formalized: extraction is the runtime's responsibility, the parser is `StreamTranscript.latest_verdict` + a `<<<EMISSION>>>` block extractor, and `InputType.ALLOWED_VERDICTS` is the per-stream allowlist.

## Lifecycle phases inside a Stream

Some roles have meaningful internal phases — generate-spec → wait-for-approval → implement; generate-qa-plan → wait-for-approval → run-scenarios. **These are not separate Stream subclasses.** They are phases of one Stream's lifecycle. The Stream's prompt-set carries phase-specific InputTypes; transitions emit `phase.*` Emissions that supervisors can subscribe to.

```python
class ImplStream(Stream):
    input_type = ImplSystemPrompt              # the initial system prompt (covers all phases)
    output_emissions = {
        'phase.impl.spec-proposed',            # initial spec rendered
        'phase.impl.spec-revised',             # human asked for changes
        'phase.impl.spec-approved',            # phase transition gate
        'phase.impl.commit-landed',
        'impl.lifecycle.ready-for-review',
        ...
    }

    # phase flow lives in role logic — emit spec.proposed, raise AttentionRequest for approval,
    # consume the typed reply, then proceed. No separate SpecGenStream.
```

**Spec generation specifically:** `ImplStream`'s initial system prompt (the `ImplSystemPrompt`) instructs the agent to draft the spec first and write a `<<<EMISSION phase.impl.spec-proposed>>>` marker when done. The agent does NOT stop after writing the marker — it continues with implementation work in the same turn unless the prompt also tells it to raise an attention request for human approval. The runtime's output scanner extracts the marker and emits `phase.impl.spec-proposed`. The mind reacts based on `StreamPolicy.auto_approve_spec`:

- `auto_approve_spec=True` — the supervisor doesn't intervene; the agent's continued implementation work proceeds. The spec is just a recorded milestone.
- `auto_approve_spec=False` — the supervisor raises an `AttentionRequest` for human approval. The prompt also instructs the agent to write `<<<EMISSION request.user-attention.spec-approval-needed>>>` and **then** wait (this is the natural stopping point — the agent is following its instructions to await human input).
- On approval (Emission `attention.resolved.spec-approval` delivered as a message), the agent continues. On rejection / revision request, the supervisor `deliver_message`s the revisions and the agent re-drafts.

Same shape for `QaPlanningStream` (qa spec → optional approval gate → scenarios). The `SpecArtifact` is the typed on-disk record (see plan-sensorium); the generation flow is internal to the impl/planning stream. **The key timing point: the agent's natural pauses are AttentionRequests, not phase emissions.** Phase emissions are observation markers extracted while the agent continues to work.

This avoids fragmenting per-PR work across multiple Stream subclasses that have to coordinate via Mailbox just to hand off a typed artifact. One conceptual unit of work = one Stream lifetime.

## Tmux pane / window management and focus

Streams whose runtime is a Tmux* variant own a tmux pane. The pane's lifecycle is the runtime's lifecycle:

- **`TmuxHostRuntime.instantiate(stream_id, ...)`** creates the tmux window/pane (using `pane_layout.py` + `pane_registry.py` substrate). Pane id is bound to `stream_id`.
- **Keep-warm policy** keeps the pane alive between Emission deliveries (the pane displays the in-progress conversation).
- **`Stream.hibernate()`** tears down the runtime — the tmux pane closes too. On `resume()`, the runtime instantiates a new pane via the persistence chain.
- **`Stream.terminate()`** closes the pane permanently. Per-PR teardown (today's `pr_cleanup.py`) becomes the `Supervisor.cancel_correlation('pr:42')` path: every Stream in the PR's subtree terminates, every pane closes.

**Focus is a Stream method.** TUI focus changes go through:

```python
class Stream:
    def focus(self) -> None:
        """Bring this stream's display surface to the foreground (tmux select-window for Tmux* runtimes; no-op for headless runtimes)."""
        self.runtime.focus(self.instance_id)
```

The TUI doesn't query a separate pane registry. To focus a PR's impl stream: `mind.streams(role=ImplStream, instance_key=str(pr_id))[0].focus()`. Mind+Stream is the single source of truth; pane id lives inside the runtime instance.

`pm_core/tmux.py`, `pm_core/tui/pane_layout.py`, `pm_core/tui/pane_registry.py` STAY as substrate the Tmux* runtimes use. The runtime is the consumer; no other code touches the registry. The `pane_registry`'s role-based dedup logic (today's `_launch_pane()` reusing panes by role+key) becomes the runtime's `instantiate()` checking for an existing instance with matching `stream_id` before creating new.

**Companion pane** (today: a secondary shell pane attached to a PR window): TUI/Tmux visualization detail — declared by the action's `PRActionTUIType` subclass via `companion_panes: ClassVar[list[CompanionPaneSpec]]` in `pm_core/tui/pr_actions/`. The mind-layer Stream doesn't know about it; the TUI sets up companion panes alongside the main pane when it instantiates the display for a stream. No separate Stream subclass; companion shells aren't agents.

**External-process TUI IPC** (today: SIGUSR1 state-reload, SIGUSR2 command-queue file, popup-picker → TUI command delivery): becomes a **`TUICommandChannel`** in `pm_core/mind/channels.py` — a file-backed `Channel` subclass whose subscribers are local-process readers (the TUI subscribes; external popup-picker writes). The suppress-switch focus-cancellation handshake becomes a short-lived `AttentionRequest` with `ControlOwner=tui_user` and TTL.

## Claude CLI flag consolidation

Today: `--resume`, `--dangerously-skip-permissions`, `--model`, `--allowedTools`, etc. construction scattered across `claude_launcher.py`, `bridge.py`, `wrapper.py`, `cli/pr.py`. New:

- **The Runtime owns CLI flag construction.** `TmuxHostRuntime` and `RawApiRuntime` each know how to translate (Stream policy + capabilities) into Claude CLI args.
- **Streams declare requirements** via `required_capabilities: ClassVar[set[str]]` (e.g. `{'sandboxed_bash', 'repo_mount'}`) and `StreamPolicy` fields.
- **`StreamPolicy.trust_runtime: TrustLevel`** governs `--dangerously-skip-permissions`. `TrustLevel.sandboxed` → flag omitted; `TrustLevel.dangerous` → flag set; `TrustLevel.default` → policy-resolved at runtime.
- **Resume continuity** — keep-warm uses `--resume <session_id>` is not a thing (we dropped that reliance). Keep-warm means the runtime instance literally stays alive; no flag needed.

Mapping table (lives in `pm_core/runtime/tmux_host.py` as a documented dispatch):

| Stream/Policy field | Translated flag |
|---|---|
| `required_capabilities={'sandboxed_bash'}` | (default; no flag) |
| `policy.trust_runtime=TrustLevel.dangerous` | `--dangerously-skip-permissions` |
| `policy.model` | `--model <name>` |
| `Stream.required_capabilities` filtered against `RuntimeCapabilities.shell_exec` | rejected at instantiate-time if incompatible |
| `policy.allowed_tools` | `--allowedTools <list>` |

No CLI flag construction happens outside the runtime impls. Migration step in the runtime PR: every `subprocess.run(['claude', ...])` call site in today's pm_core/ either moves into a Runtime impl or becomes a `Mind.stream(role=X, runtime=..., policy=...)` call that lets the Runtime construct flags.

## Mind-level governance: Budget

Budget is **between-stream, not within-turn**. We do not interrupt a running stream's turn to enforce token limits. The mind decides which streams to instantiate, when to terminate, and per-mind caps; cost telemetry from `RuntimePlugin` (when `reports_cost=True`) informs those decisions.

```python
@dataclass
class BudgetPolicy:
    max_tokens: Optional[int] = None       # cumulative input+output tokens
    max_usd: Optional[float] = None        # cumulative cost
    max_wallclock: Optional[timedelta] = None
    scope: Literal['session', 'correlation', 'mind'] = 'session'

@dataclass
class UsageEvent(Payload):
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
```

- Runtimes that report cost emit `telemetry.cost` Emission instances (payload `UsageEvent`) per turn.
- `BudgetPolicy` attached to `Stream.policy.budget` aggregates `UsageEvent` for that session (or correlation group, or mind) and on exceedance emits `budget.exceeded` to a well-known mailbox.
- `Supervisor.supervise` subscribes to `budget.exceeded` and applies policy: terminate with `TerminationReason.budget_exhausted`, escalate via `AttentionRequest`, or both.
- Cross-mind per-relationship rate limits are plan-collaboration's concern and built on the same telemetry stream.

The deliberate non-goal: stopping a stream mid-turn. Budget is a coarse governor over which streams exist and persist, not a token-by-token interrupt.

## Typed sibling-sets: roles, tags, channels, tiers, statuses

The categories below were strings in the pre-refactor codebase. Each is a sibling-set where adding an N+1th instance was a recipe for the convention-not-type failure mode (the missed `signoff` registration and missed TUI keybinding from plan-quality are both this pattern). Each becomes a typed family with structural integrity.

### Stream subclasses: one class per role

`Stream` becomes an abstract base; every role is a `Stream` subclass. The subclass IS the role identity — no separate role-string namespace.

```python
class Stream:
    """Base. Subclasses are the roles."""
    input_type: ClassVar[type[InputType]]                # required
    output_emissions: ClassVar[set[str]]                 # required: tags this role emits
    required_capabilities: ClassVar[set[str]] = set()    # default: none
    fake_runtime_script: ClassVar[Optional[dict]] = None # required for testable roles

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if cls is not PRActionStream:                    # base classes excepted
            missing = [a for a in ('input_type', 'output_emissions')
                       if not hasattr(cls, a)]
            if missing:
                raise StreamRegistrationError(f"{cls.__name__} missing {missing}")
            for tag in cls.output_emissions:
                if tag not in TagRegistry.tags:
                    raise StreamRegistrationError(f"{cls.__name__}.output_emissions includes unregistered tag {tag!r}")
```

Concrete roles (each in `pm_core/streams/`):

```python
class ImplStream(Stream):
    input_type = ImplSystemPrompt
    output_emissions = {
        'impl.lifecycle.ready-for-review',
        'impl.lifecycle.needs-clarification',
        'note.impl.design-choice',
    }
    required_capabilities = {'repo_mount', 'shell_exec'}

class ReviewStream(Stream): ...
class SignoffStream(Stream): ...
class QaScenarioStream(Stream): ...
# etc — one class per role in the 25-role enumeration
```

`Mind.stream(role_class: type[Stream], instance_key: str, ...)` accepts the class itself, not a string. `Mind.streams(role=ImplStream)` enumerates instances of the role. Forgetting to register an `InputType`, a `fake_runtime_script`, or an output tag in `TagRegistry` fails at import — not at first launch, not at first verdict.

This is the structural fix [[plan-quality]] proposed for the missed `signoff` session-type registration. The three convention sites (`SESSION_TYPES`, `SESSION_TYPE_VERDICTS`, launch-site string) collapse into one: the `Stream` subclass declaration.

### `PRActionStream`: mind-layer lifecycle marker

PR-lifecycle actions (impl, review, qa, signoff, merge, conflict-resolve) are a sibling-set. `PRActionStream` extends `Stream` with the one mind-layer attribute that distinguishes them — **which `PRStatus` they drive**.

```python
class PRActionStream(Stream):
    pr_lifecycle_state: ClassVar[PRStatus]            # required: which PR status this stream drives

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if not hasattr(cls, 'pr_lifecycle_state'):
            raise StreamRegistrationError(f"{cls.__name__} missing pr_lifecycle_state")

class ImplStream(PRActionStream):
    pr_lifecycle_state = PRStatus.in_progress
    # ... plus Stream-base required attributes (input_type, output_emissions, required_capabilities)

class SignoffStream(PRActionStream):
    pr_lifecycle_state = PRStatus.signoff
    # ...
```

**TUI affordances live in TUI code, not on the Stream subclass.** Keybindings, glyphs, companion-pane specs, and tmux window naming are visualization concerns; they belong in `pm_core/tui/pr_actions/`, not on the mind-layer Stream class. A web dashboard, voice interface, or remote-control client wouldn't use any of them; they'd have their own equivalent typed family in their own directory.

The structural-integrity property (plan-quality's missed-keybinding example) is preserved by a typed `PRActionTUIType` hierarchy that mirrors the mind-side `PRActionStream` hierarchy:

```python
# pm_core/tui/pr_actions/base.py
class PRActionTUIType:
    """Base. Subclasses are TUI bindings for PRActionStream subclasses (one per action)."""
    stream_class: ClassVar[type[PRActionStream]]      # required
    keybinding: ClassVar[Keybinding]                  # required
    glyph: ClassVar[str]                              # required
    window_role: ClassVar[str]                        # required: tmux window naming
    companion_panes: ClassVar[list[CompanionPaneSpec]] = ()

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        missing = [a for a in ('stream_class', 'keybinding', 'glyph', 'window_role')
                   if not hasattr(cls, a)]
        if missing:
            raise PRActionTUIRegistrationError(f"{cls.__name__} missing TUI binding: {missing}")

# pm_core/tui/pr_actions/impl.py
class ImplActionTUI(PRActionTUIType):
    stream_class = ImplStream
    keybinding = Keybinding(key='s', label='Start')
    glyph = '⚙'
    window_role = 'impl'

# pm_core/tui/pr_actions/signoff.py
class SignoffActionTUI(PRActionTUIType):
    stream_class = SignoffStream
    keybinding = Keybinding(key='o', label='Sign off')
    glyph = '✓'
    window_role = 'signoff'
    companion_panes = [CompanionPaneSpec(...)]        # signoff's evidence pane

# ... one PRActionTUIType subclass per PRActionStream subclass
```

Two layers of structural enforcement:

1. **`PRActionTUIType.__init_subclass__`** fails at import if a TUI subclass is missing required attributes (keybinding, glyph, window_role, stream_class). Catches partial registration of new actions.
2. **TUI startup completeness check** — `set(PRActionStream.__subclasses__())` must equal `{c.stream_class for c in PRActionTUIType.__subclasses__()}`. Catches `PRActionStream` subclasses added without a paired TUI binding.

The completeness check lives in `pm_core/tui/pr_actions/_registry.py` and runs from two callers — TUI startup AND a pytest test — so CI catches the bug before it reaches the TUI:

```python
# pm_core/tui/pr_actions/_registry.py
def _load_all_subclasses() -> None:
    """Force-import every PRActionStream + PRActionTUIType subclass module so
    PRActionStream.__subclasses__() returns the complete set. Python's
    __subclasses__() only sees classes that have been imported."""
    import pm_core.streams           # pm_core/streams/__init__.py imports each role module
    import pm_core.tui.pr_actions    # pm_core/tui/pr_actions/__init__.py imports each binding module

def check_pr_action_bindings_complete() -> None:
    """Asserts every PRActionStream subclass has a PRActionTUIType binding and vice versa.
    Called from TUI startup AND a pytest test."""
    _load_all_subclasses()
    mind_actions: set[type[PRActionStream]] = set(PRActionStream.__subclasses__())
    tui_bindings_by_stream: dict[type[PRActionStream], type[PRActionTUIType]] = {
        c.stream_class: c for c in PRActionTUIType.__subclasses__()
    }

    missing_tui = [c.__name__ for c in mind_actions if c not in tui_bindings_by_stream]
    orphan_tui = [c.__name__ for c in PRActionTUIType.__subclasses__()
                  if c.stream_class not in mind_actions]
    duplicate_tui = [c.__name__ for c, count in collections.Counter(
        b.stream_class for b in PRActionTUIType.__subclasses__()).items() if count > 1]

    problems = []
    if missing_tui:
        problems.append(f"PRActionStream subclasses without TUI bindings: {sorted(missing_tui)}")
    if orphan_tui:
        problems.append(f"PRActionTUIType subclasses whose stream_class is not a registered PRActionStream: {sorted(orphan_tui)}")
    if duplicate_tui:
        problems.append(f"Multiple PRActionTUIType subclasses bound to the same stream_class: {sorted(duplicate_tui)}")
    if problems:
        raise PRActionBindingsIncomplete("\n".join(problems))
```

```python
# pm_core/tui/app.py — TUI startup
def main():
    check_pr_action_bindings_complete()   # fail fast before opening any panes
    ...

# tests/test_pr_action_bindings.py — runs in CI
def test_pr_action_bindings_complete():
    """If this fails, you added a PRActionStream subclass without a paired PRActionTUIType
    (or vice versa). Add the binding under pm_core/tui/pr_actions/<role>.py."""
    check_pr_action_bindings_complete()
```

**Two import-guarantees** are load-bearing:

- `pm_core/streams/__init__.py` imports each `PRActionStream` subclass module so the class is registered with Python before `__subclasses__()` is consulted. Adding a new role file means adding one import line.
- `pm_core/tui/pr_actions/__init__.py` does the same for the TUI side.

`_load_all_subclasses()` does both imports defensively before checking so the test doesn't depend on a particular import order elsewhere.

**Failure modes the check catches:**

1. New `PRActionStream` subclass added without its `PRActionTUIType` (the original missed-signoff-keybinding case).
2. `PRActionTUIType` subclass orphaned — points at a `PRActionStream` that was deleted/renamed.
3. Two `PRActionTUIType` subclasses bound to the same `PRActionStream` (duplicate binding).
4. Missing required ClassVar on a `PRActionTUIType` subclass — caught at import by `__init_subclass__`, fires before this check runs.

Adding a new front-end (web dashboard, voice client) means one new typed family in its own directory plus one new completeness-check function with the same shape. Adding a new PR action: one mind-side `PRActionStream` subclass + one TUI-side `PRActionTUIType` subclass + one line in each `__init__.py`. Forgetting any of those fails CI.

**`Stream.focus()` stays on the base** — it's polymorphic over runtimes that have a display surface (delegates to `runtime.focus(instance_id)`; no-op for headless runtimes). Calling `mind.streams(role=ImplStream)[0].focus()` is meaningful whether the display is tmux, a web pane, or a voice-prompt foregrounding.

### `PRStatus`: typed lifecycle states

```python
class PRStatus(StrEnum):
    pending = 'pending'
    in_progress = 'in_progress'
    in_review = 'in_review'
    qa = 'qa'
    signoff = 'signoff'
    blocked = 'blocked'
    merged = 'merged'
    closed = 'closed'

    @classmethod
    def is_terminal(cls, status: 'PRStatus | str') -> bool:
        return cls(status) in _TERMINAL_PR_STATUSES

TERMINAL_PR_STATUSES: frozenset[PRStatus] = frozenset({PRStatus.merged, PRStatus.closed})
_TERMINAL_PR_STATUSES = TERMINAL_PR_STATUSES  # alias for the classmethod
```

Project.yaml status fields, PR-status filters, watcher policies all consume this enum rather than strings. Forgetting to add a new status (and updating sibling code: TUI glyph, valid_statuses set, lifecycle transitions) fails at startup when a `PRActionStream` subclass declares a `pr_lifecycle_state` not in the enum.

**Display + ordering tables (co-located with `PRStatus`).** Today the same status-shape knowledge is scattered across five+ files that already drift (the audit found `cli/__init__.py:407-410`'s emoji dict lacks `blocked`, `tech_tree.py:27-36/86-95/98-107` keeps unicode glyphs + fg + bg in three parallel dicts, `tree_layout.py:343-351`'s `status_priority` defaults unknown members to 5, and `cli/__init__.py:411` hardcodes the filter-cycle order). The refactor consolidates all of this into tables owned by `pm_core/mind/lifecycle.py` next to `PRStatus`:

```python
@dataclass(frozen=True)
class PRStatusDisplay:
    glyph: str          # terminal-safe unicode (TUI tech_tree)
    emoji: str          # rich display (CLI pm status, graph.py)
    fg: str             # Textual style foreground (tech_tree STATUS_STYLES)
    bg: str             # Textual background (tech_tree STATUS_BG)
    sort_priority: int  # tree_layout._pr_sort_key ordering (no defaulting)

PR_STATUS_DISPLAY: dict[PRStatus, PRStatusDisplay] = { ... }   # one row per enum member; enforced exhaustive by a startup assert

# Filter cycle: derived, not hardcoded.
STATUS_FILTER_CYCLE: tuple[PRStatus | None, ...] = (None, *PRStatus)
```

An `__init_subclass__`-style module-load assertion verifies `set(PR_STATUS_DISPLAY) == set(PRStatus)` so adding a new status without a display row fails at import (the failure mode that produced today's `blocked`-only-in-helpers drift). `cli/__init__.py:407-410`, `cli/helpers.py:262-271`, `graph.py:142-151`, `tech_tree.py:27-36/86-95/98-107`, and `tree_layout.py:343-351` all delete their local dicts and read `PR_STATUS_DISPLAY` instead. The `pm status` CLI emoji vs. TUI glyph split is resolved by exposing both fields on every row (caller picks `.emoji` or `.glyph`).

**Terminal-status consolidation.** `PRStatus.is_terminal()` replaces `pm_core/cli/session.py:953 _TERMINAL_STATUSES` and the four inline `{"merged","closed"}` checks at `qa_loop.py:2972, 3060, 3095, 3147` and `home_window/pr_list.py:156`. The picker's `applicable_statuses` ClassVar on `PRActionTUIType` derives from "non-terminal" by default.

### `TagRegistry` and typed `Tag` records

Emission tags become explicit registry entries with payload schemas and source role.

```python
@dataclass(frozen=True)
class Tag:
    name: str                                # 'verdict.review.pass'
    payload_schema: type[Payload]       # what the payload must conform to
    source_role: type[Stream]                # which role emits this tag
    schema_version: str = '1'

class TagRegistry:
    tags: ClassVar[dict[str, Tag]] = {}

    @classmethod
    def register(cls, tag: Tag) -> None
    @classmethod
    def lookup(cls, name: str) -> Tag        # raises UnknownTagError
    @classmethod
    def for_role(cls, role: type[Stream]) -> set[Tag]
```

`Emission.tag` stays a string at the call site (composable, glob-able) but `EmissionLog.append` validates against `TagRegistry`. Unregistered tags raise `UnknownTagError`. Stream subclasses' `output_emissions` is validated against this registry at import (see `Stream.__init_subclass__` above). `FakeClaudeRuntime` derives its scripted-verdict set from `TagRegistry.for_role(cls)` instead of maintaining a parallel dict — eliminating today's `fake_claude.SESSION_TYPE_VERDICTS` drift.

### `Channel`: typed mailbox value objects

Mailbox names are typed value objects. Stops `pr:42:review-verdict` vs. `pr:42:review-verdicts` typos by making channels structured constructions.

```python
class Channel:
    """Base. Renders to a Mailbox.name string but is constructed type-safely."""
    def name(self) -> str: ...

@dataclass(frozen=True)
class PRChannel(Channel):
    pr_id: int
    kind: Literal['impl-lifecycle', 'review-verdicts', 'signoff-verdict', 'attention:responses']
    def name(self) -> str:
        return f'pr:{self.pr_id}:{self.kind}'

@dataclass(frozen=True)
class ScenarioChannel(Channel):
    pr_id: int
    scenario_idx: int
    kind: Literal['verdict', 'verify-verdict', 'fixture-state']
    def name(self) -> str:
        return f'scenario:{self.pr_id}:{self.scenario_idx}:{self.kind}'

@dataclass(frozen=True)
class LifecycleGlobalChannel(Channel):
    def name(self) -> str:
        return 'lifecycle:global'

@dataclass(frozen=True)
class AttentionGlobalChannel(Channel):
    def name(self) -> str:
        return 'attention:global'

@dataclass(frozen=True)
class ArtifactChangeChannel(Channel):
    artifact_name: str
    def name(self) -> str:
        return f'sensorium:artifact:{self.artifact_name}'
```

`Mind.mailbox(PRChannel(42, 'review-verdicts'))` is the typed call. `Mailbox` retains the string `.name` for serialization and glob subscription, but consumers compose channel objects.

**Mailbox addressing convention (binding across all three plans).** Every call site that resolves a mailbox MUST construct a typed `Channel` value object — never a raw string. The string form is a rendering of the channel for storage / serialization / glob subscription only. This convention applies uniformly:

- **plan-mind** — typed Channel subclasses (`PRChannel`, `ScenarioChannel`, `LifecycleGlobalChannel`, `AttentionGlobalChannel`, `ArtifactChangeChannel`).
- **plan-sensorium** — `Artifact.apply()` posts to `mind.mailbox(ArtifactChangeChannel(self.name))`; `ResourceLease` posts to a typed `LeaseChannel(self.key)` (defined alongside `ResourceKey`); `CaptureService` posts to `CaptureChannel(test_id)`.
- **plan-collaboration** — cross-mind interaction is Artifact-mediated (not channel-routed); there are no cross-mind Channels. ProjectIdentity uses the URI shape `pm://<project_id>` for naming peer minds, but it isn't a Channel — it's an identity value type.

Reviewers and CI should flag any `mind.mailbox('literal-string')` as a violation — promote to a typed `Channel` subclass and add to the hierarchy.

### `VisibilityTier`: proper enum, not stringly-Literal

```python
class VisibilityTier(Enum):
    private = 'private'
    user_internal = 'user-internal'
    public = 'public'

@dataclass(frozen=True)
class Party(VisibilityTier):
    """Parameterized variant: visibility scoped to one external party (project_id)."""
    project_id: str
    def __str__(self): return f'party:{self.project_id}'
```

Used on `Emission.visibility`, `Stream` accept-visibility-tier policy, and plan-collaboration's Transport layer for cross-mind publication gating (plan-collaboration consumes the enum directly). Catches typos like `private_` or `user_internal_to_me` that a Literal string couldn't.

## Invariants the tree enforces

1. Targeted inter-stream communication flows ONLY as `Emission` posted to a `Mailbox` or appended to a `EmissionLog`. Untagged chat is unaddressable from other streams.
2. No primitive exposes a peer-summary payload type. Verdict schemas carry control-flow fields plus typed `Payload` references. Source code is never duplicated into a tagged payload.
3. Every `Emission` is appended to the stream's `EmissionLog` before being routed to any subscriber.
4. `Stream` identity is stable across runtime instances and process restarts; the wrapper owns persistence and may swap `RuntimePlugin` instances under a stable handle id.
5. `RuntimePlugin` is the only seam where execution touches a model/container/tmux. Coordination primitives never reach into runtime internals.
6. `AttentionRequest`s are first-class graph nodes: stable ids, addressable, resolved through a typed reply delivered via the same mailbox/callback machinery.
7. Graph edges (subscriptions, callbacks) are wired at runtime via `Mind`; no role hard-codes the identity of another role at deploy time.
8. Prompts and messages flow through typed `InputType.render(inputs)`; no untyped string interpolation on the input boundary.
9. Session health, restart, escalation are `Supervisor` responsibilities; no role implements its own supervision.
10. The `EmissionLog` and `StreamTranscript` are the authoritative records of what a stream emitted. They are written by the wrapper from `RuntimePlugin.on_output` / `poll_outputs`, not derived from runtime-internal artifacts. No code reads Claude Code's internal JSONL transcripts, tmux scrollback, or container stdout files after the fact to reconstruct stream history.

## Code-as-truth, structurally enforced

Three mechanisms make summary-handoff drift impossible to commit without explicit design-review:

1. **No peer-summary payload type exists.** Verdict schemas have `state`, `refs`, `decision`; no `summary: str` field. Adding one requires extending the schema, which is the choke point.
2. **`RuntimePlugin` exposes `read_artifact(ref)` but no `inject_peer_summary()`.** Upstream context is pulled via `Payload` (code) or `EmissionLog.query` (decisions), both pointing at canonical sources.
3. **`CallbackRegistry` binds on tag presence, not payload content.** A downstream consumer of `verdict.review.pass` literally cannot be handed reviewer prose because the schema has no prose field.

The typing extends to inputs too: a `InputType` that wants peer-summary prose must declare a `peer_summary: str` field on its inputs dataclass — same choke point as adding it to a verdict schema. Today's loose-string `prompt_gen.py` had no such gate.

## Pluggability story

`RuntimePlugin` is the single seam. A role declares `mind.stream(id, role, runtime=X, persistence=Y)` where X implements the Protocol. Today's host-side `launch_pane` becomes `TmuxHostRuntime`; today's pm-managed Docker-in-tmux sessions become `TmuxContainerRuntime`; `@anthropic-ai/sandbox-runtime` becomes `TmuxSandboxRuntime`; Anthropic Managed Agents (cloud or self-hosted variant) become `ManagedAgentRuntime`. Each is a ~200-500 line plugin implementing `instantiate/send_input/on_output/poll_outputs/terminate/capabilities`. Adding a new isolation mechanism in the future means writing a new plugin and registering it in the graph factory; existing roles opt in by changing the `runtime=` kwarg. Zero changes to mailbox wiring, callback registration, attention requests, or persistence.

`HybridRuntime` composes two plugins under one `Stream` id so a role can be interactive-Tmux when a human is attached and headless-API when waking on a callback, sharing one log.

`RuntimeCapabilities` lets roles declare hard requirements (`interactive_tty=True` for guide-setup) and the graph rejects incompatible plugin assignments at session-open rather than failing mid-run.

## Additions from the file-migration-map audit

These are files / sections the migration-map audit surfaced as either load-bearing entries the proposed structure missed, or clarifications needed to absorb existing pm_core functionality cleanly.

### Bootstrap entry point — `pm_core/bootstrap.py` (was `wrapper.py`)

The pm console-scripts entry point does `sys.path` manipulation, session-override resolution, cwd-walk to find local pm_core, and pm_root persistence. It MUST run before pm_core is importable. It cannot literally "move into Stream/Runtime" — there's no Mind to import yet. Rename `wrapper.py` → `bootstrap.py` and list under **Stays**. (Correction per consolidation audit: earlier wording attributed "impl mode / discuss mode / meta-dev mode" dispatch to wrapper.py; in fact wrapper.py contains only session-tag / IPC / path-shim logic. The impl entry point is `cli/pr.py pr start`; meta-dev is `cli/meta.py meta_cmd`; discuss is `pane_ops.launch_discuss` from the TUI. Each of those CLI entries becomes a one-line shim that picks the right `Stream` subclass from a freshly-imported `Mind` after `bootstrap.py` completes its pre-import work.)

### Hook receiver CLI shim — `pm_core/runtime/hook_entry.py`

Claude Code hooks invoke a shippable executable from `~/.claude/settings.json`. RuntimePlugin classes can't be invoked as CLI entry points. `pm_core/runtime/hook_entry.py` is a thin `python -m pm_core.runtime.hook_entry` (or `console_scripts: pm-hook-receiver`) that forwards events to the appropriate `RuntimePlugin` handler in the running pm process via the EmissionLog / Mailbox.

### Push proxy runtime sibling — `pm_core/runtime/push_proxy.py`

The ~870 LOC git-push-proxy daemon (PushProxy server, `resolve_real_origin`, shared-socket lifecycle, `__main__`) is its own runtime sibling — not buried inside `tmux_container.py`. `TmuxContainerRuntime` consumes it for per-container push-redirect; the push proxy itself runs as a long-lived host-side service.

### Shared prompt fragments — `pm_core/streams/_shared_prompts.py`

About 10 reusable text blocks in today's `prompt_gen.py` are shared across 5+ prompts: `tui_section`, sync tips, beginner addendum, filing addendum, out-of-scope-bugs, signoff QA scenarios block, etc. Living in `pm_core/streams/_shared_prompts.py`, imported into the typed `InputType` subclasses (which now live alongside their Stream subclass — see Stream subclasses section). Without this shared module, the same paragraph would duplicate across many Stream files.

### Plan-stream variants — `pm_core/streams/plan/{deps,import_,fix}.py`

Plan-development streams beyond add/breakdown/review: `plan_deps`, `plan_import` (also called from init), `plan_fix` (also `--review` variant). Same shape as the other plan-streams.

### Watcher type-string registry — `pm_core/streams/watchers/__init__.py`

TUI and CLI today look up watchers by string (`get_watcher_class('auto-start')`). Under the typed Stream hierarchy, this becomes a small mapping module:

```python
# pm_core/streams/watchers/__init__.py
WATCHER_REGISTRY: dict[str, type[Stream]] = {
    'auto-start': AutoStartWatcherStream,
    'bug-fix-impl': BugFixImplWatcherStream,
    'improvement-fix-impl': ImprovementFixImplWatcherStream,
    'discovery-supervisor': DiscoverySupervisorStream,
    'watcher-review': WatcherReviewStream,
}
```

External-string callers (TUI keybindings, CLI args) resolve via the registry; internal callers use the class directly. Adding a watcher means one entry plus the class.

### Cross-process EmissionLog reads

Several short-lived external CLI processes (popup picker, status spinner, `home_window/`) need to observe in-flight stream state without instantiating a full `Mind`. The SQLite-backed `EmissionLog` at `pm/.mindlog.db` MUST be reachable by these readers in read-only mode. `EmissionLog.query(...)` works from any process with read permission; documented as a contract here. If a richer-than-SQLite backend ever replaces it, the cross-process read interface must be preserved.

### Per-stream policy consolidation — `pm_core/mind/policy.py`

Several per-stream knobs are scattered across today's qa_loop, review_loop, watcher_base, auto_start. Consolidate on `StreamPolicy`:

```python
@dataclass
class StreamPolicy:
    persistence: list[str] = ('keep-warm', 'log-replay')   # log-replay = rebuild from typed inputs; no runtime-internal snapshot reliance
    budget: Optional[BudgetPolicy] = None
    cascade_on_parent_terminate: bool = True
    takeover: TakeoverBufferPolicy = ...
    loop_mode_overrides: dict[str, LoopMode] = field(default_factory=dict)   # per-tag overrides (see Tag-driven loop semantics below)
    stop_before_merge: bool = False              # auto-sequence "armed but don't auto-merge"
    consecutive_pass_threshold: int = 2          # how many passes before declaring done
    max_iterations: Optional[int] = None         # None = unlimited; positive int caps the loop; 0 is illegal and rejected at construction (audit NG-3: today's 0=unlimited sentinel in watcher_base.py is NOT carried forward — it was a silent-regression hazard). Supervisors that loop a Stream MUST honor this: None = "drive until external termination"; N > 0 = "raise TerminationReason.iteration_cap_reached after N iterations".
    retention: 'RetentionPolicy' = ...           # how long to keep transcript/log on terminate
```

### `ALLOWED_VERDICTS` per-prompt class attribute

Today's centralized `SESSION_TYPE_VERDICTS` table in `fake_claude.py` becomes a per-`InputType` class attribute. Each `InputType` references **canonical tag names** from `pm_core/mind/tags.py` (the `Tag` records registered with `TagRegistry`) rather than restating string literals:

```python
# pm_core/mind/tags.py — canonical tag constants registered once
VERDICT_REVIEW_PASS = Tag('verdict.review.pass', ReviewVerdictPayload, ReviewStream)
VERDICT_REVIEW_NEEDS_WORK = Tag('verdict.review.needs-work', ReviewVerdictPayload, ReviewStream)
VERDICT_WATCHER_READY = Tag('verdict.watcher.ready', WatcherVerdictPayload, WatcherStream)
INPUT_REQUIRED_REVIEW = Tag('request.user-attention.review-blocked', AttentionPayload, ReviewStream)
# (one Tag per emitted signal; lives in tags.py alongside TagRegistry.register calls)

class ReviewSystemPrompt(InputType):
    ALLOWED_VERDICTS: ClassVar[set[Tag]] = {VERDICT_REVIEW_PASS, VERDICT_REVIEW_NEEDS_WORK, INPUT_REQUIRED_REVIEW}
    ...
```

**Why typed Tag refs, not raw strings.** The audit (NG-1) flagged that today's `qa_loop.py:42-46` and `review_loop.py:43-48` independently declare `VERDICT_PASS = "PASS"` / `VERDICT_NEEDS_WORK = "NEEDS_WORK"` / `VERDICT_INPUT_REQUIRED = "INPUT_REQUIRED"`. Per-`InputType` `ALLOWED_VERDICTS` sets that restate string literals would carry the same drift mode forward — two prompts could land on slightly different spellings. By making `ALLOWED_VERDICTS` a set of `Tag` records pulled from `mind/tags.py`, the spelling exists in exactly one place; renaming a tag updates every InputType that references it. A CI grep test forbids tag-name string literals (`re.search(r'verdict\.\w+|request\.user-attention\.\w+'`)) outside `mind/tags.py` and `tests/`.

`FakeClaudeRuntime` derives its scripted-verdict set by reading `ALLOWED_VERDICTS` from every `InputType` it knows about. Same source of truth as the per-Stream `output_emissions` (which validates against `TagRegistry`).

### Persistence-policy heuristic per role kind

The shape-improvements audit found persistence policy was handwaved across roles. Default heuristic (lives in this plan as guidance for `StreamPolicy.persistence` defaults):

| Role kind | Recommended policy chain |
|---|---|
| Tick-driven watcher (auto-start, bug-fix-impl, improvement-fix-impl) | `keep-warm` (cheap; sleep between ticks) → `log-replay` (rebuild from typed inputs if evicted) |
| Per-PR persistent (impl, signoff-router) | `keep-warm` (sub-second wake when human pokes the pane) → `log-replay` (rebuild from log + typed inputs if evicted) |
| Per-scenario persistent (qa-scenario, qa-verification) | `keep-warm` while supervisor expects more verdicts → `log-replay` (keep-warm cost amortizes across re-verifications) |
| One-shot blind (plan-add, qa-author, **review-loop**, blind review cycle) | no persistence — new `instance_key` per invocation, runtime is cold-started; fresh-start is the design intent |
| Long-running discussion (guide-assist, watcher-review, discuss) | `keep-warm` (humans expect responsiveness) → `log-replay` |
| Heavy-resource (container-build) | `keep-warm` + `ResourceLease` (the container is the persistent resource) → `log-replay` (re-instantiate container from typed RepoCheckout + build instructions) |

These are defaults — roles override per-instance.

### Additional StreamPolicy fields (from v2 file-migration audit)

```python
@dataclass
class StreamPolicy:
    # ... existing fields ...
    remind_on_grace: Optional[tuple[InputType, timedelta]] = None    # if no verdict within grace, deliver reminder + reset timer
    max_consecutive_attention_requests: int = 3                       # repeated INPUT_REQUIRED → demote to next-checkpoint or terminate
    repeated_attention_action: Literal['demote', 'terminate', 'raise_to_user'] = 'demote'
    trust_runtime: 'TrustLevel' = TrustLevel.default                  # translates to Claude CLI flags inside the Runtime
    auto_approve_spec: bool = False                                   # for ImplStream / QaPlanningStream phase gating
    allowed_tools: Optional[list[str]] = None                         # passed through as Claude --allowedTools
    model: Optional[str] = None                                       # passed through as Claude --model
```

Covers today's: qa_loop's verdict-reminder-timeout (GAP-5), review_loop/watcher_base's "repeated INPUT_REQUIRED → READY/NEEDS_WORK fallback" (GAP-8), self-driving-QA per-PR override (GAP-11; though that may also need a per-PR override field on `PRStreamSupervisor`, see below).

### AttentionRequest semantics on stream death

`AttentionService` auto-cancels every outstanding `AttentionRequest` whose holder Stream transitions to a terminal `LifecycleState`. The auto-cancel emits an `attention.abandoned` Emission carrying the original `AttId` + the holder's `TerminationReason`. Subscribers (the TUI dashboard, supervisors) react by clearing the request from the user's queue and optionally re-raising under a different holder.

### Two-phase merge state machine

`MergeStream` owns the workdir-merge phase. On success it emits `phase.merge.workdir-complete` and transitions to `MergePropagationStream` (sibling Stream, same instance_key) that runs the `--propagation-only` step (push to main repo origin). Each phase emits its own `request.user-attention.merge-conflict` on conflict; the resolver is `MergeConflictResolverStream` invoked per-phase. Two phases = two streams because they have meaningfully different policy (workdir merge is reversible; propagation is final).

### Per-PR Supervisor overrides

`PRStreamSupervisor` accepts per-PR override fields that supersede `StreamPolicy` for that PR's stream subtree:

```python
class PRStreamSupervisor(Supervisor):
    overrides: dict[int, PROverride] = field(default_factory=dict)

@dataclass
class PROverride:
    self_driving: Optional[bool] = None              # force self-driving QA on/off
    stop_before_merge: Optional[bool] = None         # arm/disarm "stop before merge"
    auto_approve_spec: Optional[bool] = None
```

Today's `app._self_driving_qa` set by TUI gesture sets `overrides[pr_id].self_driving = True`. Streams in the PR subtree consult their supervisor's override before falling back to `StreamPolicy`.

### Shared Claude JSONL codec

`pm_core/runtime/_claude_jsonl.py` is a small private helper shared between:
- `TmuxHostRuntime` (reads Claude Code's on-disk JSONL transcripts as part of `poll_outputs`)
- `FakeClaudeRuntime` (writes the same format so TmuxHostRuntime can be tested against fake)

Single reader/writer pair avoids drift. No public API outside `pm_core/runtime/`.

### Pm-self-reentry — `pm_core/runtime/reentry.py`

Hidden CLI flags `--background`, `--transcript`, `--origin`, `--propagation-only` form a protocol pm uses to re-enter itself as a subprocess for specific modes (detached launches, supervisor sub-invocations, merge propagation step). Consolidated in `runtime/reentry.py`; `bootstrap.py` dispatches between `hook_entry` mode (Claude Code hook callback), `reentry` mode (pm subprocess of itself), and `normal` mode (user invocation).

### TUICommandChannel

`pm_core/mind/channels.py` gets a `TUICommandChannel` value-object subclass. Backing implementation is file-based (a command-queue file in `~/.pm/runtime/<mind_id>/tui-commands.log`); subscribers poll-and-truncate. Used by:
- External popup-picker writing commands the running TUI should execute (e.g. "switch to PR 42's review")
- Suppress-switch focus-cancellation (today's `request_suppress_switch` / `consume_suppress_switch`)

Same `Channel` typing convention as the rest; TUI subscribes via `mind.callbacks.on(TUICommandChannel(), handler)`. File-backed delivery is a transport detail; the Channel surface is unified.

### `StreamTranscript.latest_verdict(allowed)` helper

```python
class StreamTranscript:
    # ... existing methods ...
    def latest_verdict(self, allowed: set[str]) -> Optional[str]:
        """Boundary-aware verdict-keyword match (rejects 'PASS this file' but accepts '**PASS**'
        or 'PASS' alone, longest-match-first against `allowed`). Markdown/code tolerant.
        Replaces loop_shared.match_verdict from today's codebase."""
```

Single canonical implementation. `InputType.ALLOWED_VERDICTS` classvar provides the `allowed` set per-Stream.

### `pm log emissions` CLI subcommand

`pm_core/cli/log.py` gains `pm log emissions [--stream <id>] [--tag <pattern>] [--since <ts>] [--visibility <tier>]` over `EmissionLog`. The existing `pm log` text-log inspector stays for legacy log files; subcommands keep them distinct.

### Merge-restart marker → EmissionLog replay

Today's `auto_start.py` + `tui/sync.py` write a merge-restart marker file so the TUI knows to resume watchers after restarting itself post-merge. Under the new model: terminate is logged as `stream.lifecycle.terminated(reason=intentional_restart)`; `MindSupervisor.startup()` replays the lifecycle log to reconstitute watcher streams that were running pre-restart. The marker file is deleted; the replay logic lives in `supervisors/mind.py`.

### Lease reconcile on Supervisor startup

`pm_core/sensorium/leases.py` gains a `ResourceLease.reconcile(key_prefix: str, holder_filter: Callable)` classmethod. `PRStreamSupervisor.startup()` and `WatcherSupervisor.startup()` invoke it to release leases whose holder Stream is no longer in `running` lifecycle. Replaces today's `_cleanup_stale_scenario_windows` + `pr_cleanup` catch-all sweeps.

### Stays bucket (explicit enumeration)

The migration audit flagged that several modules currently in pm_core have no entry in either the new structure OR the deletes list — risk of accidental drop during the refactor. Explicit Stays list:

- `pm_core/backend.py` (PR backends)
- `pm_core/claude_launcher.py` (consumed by TmuxHostRuntime)
- `pm_core/providers.py`, `pm_core/model_config.py` (model/provider config)
- `pm_core/store.py` (project.yaml read/write — consumed by `ProjectYamlArtifact` in plan-sensorium)
- `pm_core/plan_parser.py`, `pm_core/plans/parser.py`
- `pm_core/notes.py` (consumed by `NotesSectionArtifact`)
- `pm_core/paths.py` (mostly; some pieces split out — see plan-sensorium)
- `pm_core/graph.py` (dependency graph computation)
- `pm_core/gh_ops.py`, `pm_core/git_ops.py`, `pm_core/pr_sync.py` (git/GitHub ops)
- `pm_core/shell.py` (`shlex.quote` helpers; 21 LOC)
- `pm_core/cluster/` (clustering for plan-001)
- `pm_core/bench/` (benchmark harness; out-of-scope-for-refactor research code)
- `pm_core/fake_github.py` (test fake)
- `pm_core/home_window/`, `pm_core/tui/` (UI rendering; `tui/auto_start.py`, `tui/qa_status.py`, `tui/watcher_ui.py`, `tui/review_loop_ui.py`, `tui/qa_loop_ui.py` shrink to thin delegators over Streams/Supervisors — see "TUI integration shim" pattern below)
- `pm_core/tmux.py`, `pm_core/tui/pane_layout.py`, `pm_core/tui/pane_registry.py` (foundational substrate consumed by all Tmux* runtimes)
- `pm_core/cli/` (CLI command surface — pm CLI itself stays; only `pm watcher` / `pm review-loop` / `pm qa` command groups change to delegate to Streams/Supervisors)

### TUI integration shim pattern

Many `pm_core/tui/*_ui.py` files (review_loop_ui, qa_loop_ui, watcher_ui, auto_start) become thin delegators: they translate user input into `Stream.deliver_message(...)` calls and translate `CallbackRegistry.on(...)` callbacks into TUI updates. They're not deleted, but they shrink to 50-200 LOC each.

## Implementation PR sequence

Nine PRs in dependency order, each landing one package (or two closely-related packages). Per-PR sections include Purpose, Scope, Public API summary, Invariants, Dependencies, Test plan, Migration plan, Open questions. Internal design is self-documenting from the code; details that don't fit a section live in [refactor-new-files.md](refactor-new-files.md) (per-file inventory) and [refactor-migration-map.md](refactor-migration-map.md) (per-source-file disposition).

The dependency order is strict: PR N can be merged when PR N-1 is in. PRs can be reviewed in parallel; merge waits on the topological predecessor.

### PR: `pm_core/payloads/` — typed payload values

**Purpose.** Introduce the typed-payload-value substrate that flows inside `Emission` payloads and `InputType` inputs. Replaces today's dict/string interchange on the boundary between roles.

**Scope.**
- In: `Payload` Protocol with `schema_version` + `upgrade()` migration hook; concrete subclasses `RegressionSpec`, `ImplInstructions`, `TestFixture`, `MockSpec`, `QAScenarioRef`, `RepoCheckout`, `GitDiffAtSha`, `LogQuery`, `ContainerSnapshot`, `TranscriptSlice`, `FailureReason`, `UsageEvent`. Per-file at `pm_core/payloads/`.
- Out: on-disk shared mutable Artifacts (those land in plan-sensorium's Artifact substrate PR); Stream / Emission / EmissionLog (those land in the next PR).

**Public API.** `Payload` Protocol: `id: str`, `kind: str`, `schema_version: str`, `to_payload() -> dict`, classmethod `from_payload(data)`, optional `upgrade(prior_payload, prior_version) -> dict`. Each concrete subclass is a frozen dataclass implementing the Protocol with typed fields specific to its content kind (sha + path + range for `GitDiffAtSha`; tags + payload predicate for `LogQuery`; cause + retryability for `FailureReason`; etc.). Full type signatures per concrete class.

**Invariants.**
- Every payload value round-trips through `to_payload` / `from_payload` losslessly.
- `schema_version` is monotonically increasing per subclass; `upgrade(prior, version)` migrates older payloads to the current schema.
- No `summary: str` field on any subclass — code-as-truth enforced at the type level.

**Dependencies.** None (foundation package).

**Test plan.** Round-trip serialization per subclass. Schema-version `upgrade()` hook fires when reading older versions. Property test: composing a payload into a dict and reconstructing preserves all fields.

**Migration plan.** No existing pm_core file maps directly. Concrete `Payload` subclasses are new; they will be referenced by later PRs that retire `dict` / `str` interchange. PR delivers the substrate; no source files are retired.

**Open questions.**
- Which subclasses are in this PR's starter set vs. added with the Stream subclasses that consume them? Lean: full starter set in this PR so later PRs can import without circular work.

### PR: `pm_core/mind/` — mind primitives package

**Purpose.** Introduce the inert data layer of the mind: Emissions, the log/transcript pair, mailboxes, callbacks, attention service, tags, channels, lifecycle enums, stream policy, budget policy.

**Scope.**
- In: `pm_core/mind/emissions.py`, `log.py`, `transcript.py`, `mailbox.py`, `callbacks.py`, `attention.py`, `tags.py`, `channels.py`, `lifecycle.py`, `policy.py`. Includes `AttentionService` auto-cancellation on stream-terminal transition. Includes `StreamPolicy.remind_on_grace` + `max_consecutive_attention_requests` + `repeated_attention_action` + `trust_runtime` + `auto_approve_spec` + `allowed_tools` + `model` fields.
- Out: `Stream` class (next PR group); `Mind` class (final PR); RuntimePlugin Protocol (next PR).

**Public API.** See plan §1-7 and §11-Channels for the full primitive list. Key types: `Emission(tag, payload, stream_id, correlation_id, ts, visibility, schema_version, dedup_key)`; `EmissionLog.append/query/latest/slice`; `StreamTranscript.append/read/tail/grep/slice/ref_at/latest_verdict`; `Mailbox.post(out, deliver: 'preempt'|'next-checkpoint', supersedes) / subscribe / stream / latest / list_glob`; `CallbackRegistry.on / wait_for(*, not_before, predicate, grace_period, timeout) / cancel`; `AttentionService.raise_/await_resolution/resolve` with auto-cancel on holder termination; `Tag`, `TagRegistry`, `LoopMode`; `Channel` base + `PRChannel`, `ScenarioChannel`, `LifecycleGlobalChannel`, `AttentionGlobalChannel`, `ArtifactChangeChannel`, `LeaseChannel`, `CaptureChannel`, `TUICommandChannel`; `LifecycleState`, `TerminationReason`, `VisibilityTier` (with `Party(project_id)`), `PRStatus`, `ControlOwner` enums; `StreamPolicy`, `BudgetPolicy`, `UsageEvent` (as a `Payload`), `TakeoverBufferPolicy`, `RetentionPolicy`.

**Invariants.**
- `(stream_id, tag, correlation_id)` is the primary key for emission semantics; duplicate `append`s coalesce; `on(...)` handlers fire at most once per primary key.
- Every emission is appended to `EmissionLog` before routing through any `Mailbox`.
- Targeted communication flows ONLY as `Emission` on a `Mailbox` or as an append to `EmissionLog`; untagged free text in `StreamTranscript` is unaddressable from other streams.
- `AttentionRequest` outstanding when holder transitions to terminal `LifecycleState` is auto-cancelled with `attention.abandoned` emission.

**Dependencies.** `pm_core/payloads/` (Payload Protocol for typed emission payloads and `UsageEvent`). External: `sqlite3`.

**Test plan.** Contract tests for the primary-key idempotency. Mailbox preempt vs next-checkpoint delivery semantics. CallbackRegistry grace-period + predicate behavior. AttentionService auto-cancel on stream death. TagRegistry validation rejecting unknown tags on append. Channel-name rendering round-trip. Persistence: EmissionLog and StreamTranscript survive process restart.

**Migration plan.** Sources retired (corrected per consolidation audit to enumerate all destinations):
- `runtime_state.py` fans into FIVE destinations: structured event records → `mind/log.py`; lifecycle/termination/action-state enums → `mind/lifecycle.py`; `request_suppress_switch / consume_suppress_switch` → `mind/attention.py`; `derive_action_status` + Claude-pane tracking → `runtime/tmux_host.py`; per-PR action-failure payload → `payloads/failure_reason.py`.
- Per-watcher `pm/watchers/<name>.log` (→ `EmissionLog` queries).
- `verdict_transcript.py` JSONL-text scanning parts → `mind/transcript.latest_verdict`; verdict emission at runtime boundary → `runtime/hook_entry.py`.
- pr-1d8b2b7 partial VerdictRegistry → `mind/tags.py` TagRegistry.
- `bridge.py` fans into FOUR destinations: `_invoke_claude` body → `runtime/raw_api.py`; CLI argv construction → `runtime/_claude_cli_flags.py`; busy/ack semantics → `mind/mailbox.py`; AGENT/HUMAN mode toggle → `mind/attention.py` here; stdin Enter-toggle → `runtime/tmux_host.py`.

Once this package lands, the next PR (runtime) can construct emissions; until then no consumers exist.

**Dependency boundary with the runtime PR.** `StreamTranscript.latest_verdict` operates on plain `ChatChunk` text (boundary-aware keyword matcher + `<<<EMISSION>>>` block scanner). It does NOT parse Claude Code's JSONL transcript format — that knowledge lives in `runtime/_claude_jsonl.py` (next PR) and converts JSONL to ChatChunks before they reach `StreamTranscript.append`. This keeps the mind primitives independent of any specific runtime's wire format. Concrete consequence: this PR can ship `StreamTranscript.latest_verdict` as a fully working text scanner against synthetic ChatChunks in tests; the runtime PR wires Claude Code's actual JSONL through `_claude_jsonl.py` → `Stream.append_to_transcript` → `StreamTranscript`.

**Open questions.**
- Per-Mailbox redaction rules vs global RedactionPolicy in plan-sensorium — defer to plan-sensorium's RedactionPolicy land.

### PR: `pm_core/runtime/` Protocol + tmux runtimes

**Purpose.** Introduce the single execution seam and the two runtimes pm uses today: TmuxHostRuntime (host-side Claude in tmux) and TmuxContainerRuntime (containerized Claude in tmux). Plus the host-side push-proxy daemon and the Claude Code hook CLI shim.

**Scope.**
- In: `runtime/protocol.py` (RuntimePlugin Protocol, RuntimeCapabilities, **no `snapshot()`** method or param); `runtime/tmux_host.py` + `runtime/tmux_container.py` (the two production runtimes; own Claude CLI flag construction translating Stream.required_capabilities + StreamPolicy.trust_runtime/model/allowed_tools → CLI args); `runtime/fake.py` (FakeClaudeRuntime); `runtime/push_proxy.py` (the host-side daemon); `runtime/hook_entry.py` (the Claude Code hook CLI); `runtime/_claude_jsonl.py` (private shared codec — converts Claude Code's on-disk JSONL into the plain `ChatChunk`s that flow into `Stream.append_to_transcript` → `StreamTranscript`; consumed by `TmuxHostRuntime.poll_outputs` for reads and `FakeClaudeRuntime` for writes; the JSONL format never leaks past this module into mind primitives).
- Out: RawApiRuntime, ManagedAgentRuntime, TmuxSandboxRuntime, HybridRuntime, reentry (next PR).

**Public API.** `RuntimePlugin` Protocol: `instantiate(stream_id, system_prompt) -> RuntimeInstance`, `send_input(instance, payload)`, `on_output(instance, handler) -> SubId`, `poll_outputs(instance) -> list[Emission]`, `terminate(instance)`, `capabilities() -> RuntimeCapabilities`, `focus(instance)`. `RuntimeCapabilities` dataclass with `interactive_tty`, `repo_mount`, `shell_exec`, `supports_hooks`, `supports_poll`, `reports_cost`, `network_egress`, `sandboxed_bash`, `max_inline_input_bytes`, `attach_hint`. Per-runtime CLI flag mapping documented in `tmux_host.py` docstring.

**Invariants.**
- Wrapper has zero dependency on runtime-internal snapshot. `RuntimePlugin` does not expose `snapshot()`. Resumption is via keep-warm OR log-replay regen, both of which work without runtime cooperation beyond the documented Protocol.
- Every output the runtime observes becomes `Stream.append_to_transcript(chunk)` and (for structured `<<<EMISSION>>>` blocks) `Stream.emit(...)`. No pm code reads Claude Code's internal JSONL after this PR lands.
- Claude CLI flag construction lives only inside Runtime impls; no other code spells out `--resume` / `--dangerously-skip-permissions` / `--allowedTools` / `--model`.
- Stream's typed `required_capabilities` is the only input the runtime consults for capability-driven flags.

**Dependencies.** `pm_core/mind/` (Emission, Stream stub for the append callback, EmissionLog). External: subprocess + libtmux + ad-hoc tmux session management.

**Test plan.** TmuxHostRuntime instantiate / send_input / poll_outputs against `FakeClaudeRuntime`. RuntimeCapabilities consistency between runtimes that should share flags. CLI flag construction property tests: every (capabilities, policy) combination produces a stable flag list. `_claude_jsonl` round-trip: FakeClaudeRuntime writes a session and TmuxHostRuntime parses it identically. push_proxy startup/shutdown + git-push redirect contract.

**Migration plan.** Sources retired: `bridge.py` streaming/session-id portions (→ raw_api in next PR, but the JSONL parsing is shared via `_claude_jsonl` here); **`claude_launcher.py` DELETES with content split** — Claude CLI flag construction + `build_claude_shell_cmd` + `launch_claude*` + `find_claude` + `find_editor` + `_skip_permissions` + `_resolve_provider` move into `tmux_host.py`; transcript path / session-id helpers (`transcript_path_for`, `session_id_from_transcript`, `finalize_transcript`, `_parse_session_id`, `_claude_project_dir`) move into `_claude_jsonl.py`; the new shared CLI-flag helper lands at `runtime/_claude_cli_flags.py`; `launch_bridge_in_tmux` deletes outright (see additional-runtimes PR for the bridge decision); if any helpers turn out to be genuinely shared across multiple Tmux* runtimes, they consolidate into a private `runtime/_claude_helpers.py`. `hook_install.py` + `hook_events.py` + `hook_receiver.py` (→ `runtime/hook_entry.py`); `push_proxy.py` (renamed to `runtime/push_proxy.py`); `container.py` (→ `tmux_container.py`); `fake_claude.py` (→ `runtime/fake.py`); `pane_idle.py` (→ TmuxHostRuntime internals).

**Cross-package destinations** (corrected per consolidation audit — these sources also feed mind/* and sensorium/*, not just runtime/*):
- `hook_events.py` event schema → `mind/emissions.py`; `wait_for_event` → `mind/callbacks.py`.
- `pane_idle.py` `became_idle` → `mind/callbacks.py`; `get_transcript_path` → `mind/transcript.py`; `waiting_for_input` → `mind/attention.py`.
- `verdict_transcript.py` JSONL record-shape parsing → `_claude_jsonl.py`; verdict extraction at runtime boundary → `runtime/hook_entry.py`; plain-text matching → `mind/transcript.latest_verdict`.
- `container.py` identity (ContainerKey) → `sensorium/leases.py`; mechanism → `runtime/tmux_container.py`.

Existing launch sites in qa_loop / review_loop / watchers continue to work via legacy paths until next PRs migrate them.

**Open questions.**
- `runtime/hook_entry.py` Stays vs Renamed: today's `hook_receiver.py` is what Claude Code invokes; the file content moves but the entry-point name in `~/.claude/settings.json` may need migration. Decide on backward-compat shim during PR.
- `_claude_jsonl.py` location: nested under `runtime/` (private to runtime impls) vs sibling. Lean: nested + leading underscore.

### PR: Additional runtime impls

**Purpose.** Add the remaining `RuntimePlugin` implementations that aren't blocking pm's current functionality but round out the runtime taxonomy.

**Scope.**
- In: `runtime/raw_api.py` (RawApiRuntime — absorbs bridge.py's `_invoke_claude` loop + session-id continuity, using the Anthropic SDK directly; **no socket protocol, no external-process control plane**); `runtime/managed_agent.py` (ManagedAgentRuntime — Anthropic Managed Agents); `runtime/tmux_sandbox.py` (TmuxSandboxRuntime — `@anthropic-ai/sandbox-runtime`); `runtime/hybrid.py` (HybridRuntime composing two runtimes under one stream id); `runtime/reentry.py` (pm-self-reentry CLI flags handling for `--background`/`--transcript`/`--origin`/`--propagation-only`).
- Out: Existing TmuxHostRuntime/TmuxContainerRuntime/FakeClaudeRuntime call sites (those keep using the prior PR's impls).

**Public API.** Each is a `RuntimePlugin` impl. `RawApiRuntime` uses Anthropic SDK directly, no tmux. `ManagedAgentRuntime` interacts via Managed Agents' polling/webhook contract; two sub-variants (cloud sandbox vs self-hosted). `HybridRuntime(primary: RuntimePlugin, secondary: RuntimePlugin)` exposes a single capabilities set (union of both); composes lifecycles. `runtime/reentry.py` is a CLI dispatcher invoked by `bootstrap.py` for re-entry modes.

**Invariants.** Same as prior PR (no snapshot, single execution seam). Each new impl declares its full `RuntimeCapabilities`. HybridRuntime preserves the invariant that the composed instance has consistent capabilities (rejects pairs with conflicting required flags).

**Dependencies.** Prior PR (`pm_core/runtime/`). External: `anthropic` SDK for `raw_api.py`; potentially `@anthropic-ai/sandbox-runtime` shell-out for `tmux_sandbox.py`.

**Test plan.** RawApiRuntime against the same Stream tests as TmuxHostRuntime (substitutability). HybridRuntime composing TmuxHost + RawApi; verify capability union and lifecycle. reentry parses each documented flag and dispatches correctly.

**Migration plan.** Sources retired (continuing from prior PR): `bridge.py` + `bridge_client.py` fully retire. The Unix-socket protocol (`take_control` / `release_control` / `send` / `status` JSON-lines server + matching `BridgeClient`) deletes outright — pm has no external-process control plane after this PR. Today's only consumer (`cli/cluster.py --bridged` flag via `claude_launcher.launch_bridge_in_tmux`) also deletes: `cluster_exploration` stream uses `RawApiRuntime` directly when programmatic control is wanted. Human takeover, which today flows via socket commands, flows via `AttentionService` + `ControlOwner` (defined in the mind primitives PR) — humans take over via the TUI, not via an external process. Hidden CLI flags from `cli/pr.py` / `cli/watcher.py` consolidate into `runtime/reentry.py`.

**Open questions.**
- `ManagedAgentRuntime` MVP cloud-sandbox vs self-hosted: pick one for PR coverage; the other is a follow-on. Lean: cloud-sandbox first (less infra).
- `HybridRuntime` capability conflict resolution policy: reject vs subtract vs take-primary. Lean: reject with explicit error.

### PR: `pm_core/streams/` substrate + PR-action roles

**Purpose.** Introduce the typed Stream framework plus the per-PR-action role files. PR-action roles (impl, review, signoff, merge, conflict-resolver) are the most exercised by existing pm flows; landing them first validates the framework against real usage.

**Scope.**
- In: `streams/_protocol.py` or `streams/base.py` (InputType Protocol, Stream base with `__init_subclass__` validation, `Stream.render_phase_context` helper, `Stream.deliver_message`/status/spawn_child/cancel/on_cancel/request_human_takeover/release_human_takeover/focus, persistence chain `keep-warm → log-replay`); `streams/pr_action.py` (PRActionStream base — only `pr_lifecycle_state: ClassVar[PRStatus]`); `streams/_shared_prompts.py` (cross-stream reusable text fragments — tui_section, sync tips, beginner addendum, filing addendum, signoff_qa_scenarios_block, etc.); `streams/impl.py` + `streams/review.py` + `streams/signoff.py` + `streams/merge.py` (each containing the Stream subclass + its co-located InputType + any message classes). `streams/__init__.py` importing every role file.
- Out: QA streams (next PR); watcher streams (next PR); plan/guide/meta/cluster/container/discuss streams (next PR).

**Public API.** `Stream` (see plan-mind §9); `PRActionStream`; `InputType` Protocol with `ALLOWED_VERDICTS: ClassVar[set[str]]`; `ImplStream(PRActionStream)` + `ImplSystemPrompt(InputType)` + `ImplReviewFeedbackMessage(InputType)` + spec-gen phase handling; `ReviewStream(PRActionStream)` + `ReviewSystemPrompt(InputType)` with `loop_mode_overrides = {'review.requested': LoopMode.kill_restart}`; `SignoffStream(PRActionStream)` + `SignoffSystemPrompt`; `MergeStream(PRActionStream)` + `MergePropagationStream(PRActionStream)` + `MergeConflictResolverStream(PRActionStream)` + their InputTypes.

**Invariants.**
- Every Stream subclass declares `input_type`, `output_emissions`, `required_capabilities`. `__init_subclass__` fails import on missing.
- Every `output_emissions` tag is in `TagRegistry`.
- Every `InputType.ALLOWED_VERDICTS` matches the emitting role's `output_emissions`.
- `ReviewStream` cannot survive a `review.requested` emission — kill_restart semantics enforced at dispatch.
- ImplStream's phase emissions (`phase.impl.spec-proposed`, `phase.impl.spec-approved`, `impl.lifecycle.commit-landed`, etc.) are agent-written markers extracted by the runtime.

**Dependencies.** `pm_core/mind/` (everything), `pm_core/runtime/` (`RuntimePlugin` for the runtime= kwarg type, `_claude_jsonl` codec for output parsing of `<<<EMISSION>>>` markers), `pm_core/payloads/` (`Payload` types for InputType inputs dataclass fields and Emission payloads).

**Test plan.** Stream-base `__init_subclass__` validation: missing attribute fails import; tag in `output_emissions` not in TagRegistry fails import. PRActionStream lifecycle-state matches a `PRStatus` enum value. `<<<EMISSION>>>` marker extraction round-trip: agent writes a marker into stream output → runtime extracts → emission lands in EmissionLog. ReviewStream kill_restart: emitting `review.requested` while a `ReviewStream` is `running` terminates it before spawning the new one. ImplStream phase context: `render_phase_context()` returns expected prelude based on latest `phase.*` emission.

**Migration plan.** Sources retired: `prompt_gen.py` (review/impl/signoff/merge prompt builders) → ImplSystemPrompt + ReviewSystemPrompt + SignoffSystemPrompt + MergeSystemPrompt + MergePropagationSystemPrompt + MergeConflictResolverSystemPrompt; `review_loop.py` per-iteration logic → ReviewStream; `signoff.py` → SignoffStream + the per-PR Supervisor orchestration (next PR group); `wrapper.py` impl-mode → ImplStream; merge logic in `cli/pr.py` → MergeStream + MergePropagationStream; spec_gen.py extracted prompts → ImplSpecPrompt internal variant inside `streams/impl.py`. Source files that delete after the next two PRs land: `prompt_gen.py`, `bug_fix_prompts.py`, `qa_finalize_prompt.py`, `regression_prompts.py`, `spec_gen.py`, `review_loop.py`.

**Open questions.**
- Whether `<<<EMISSION>>>` marker format and the verdict-keyword fallback both fire (dual-extract during transition), or just one. Lean: marker format first, fallback to verdict-keyword for backward compat during transition; deprecate verdict-keyword after final stream PR.
- Spec generation phase encoding: as a `phase.impl.*` tag + AttentionRequest gating, or as a typed `ImplSpecPrompt` variant before `ImplSystemPrompt`. Lean: phased single prompt + tag (no separate prompt variant).

### PR: All remaining Stream roles

**Purpose.** Land every remaining Stream subclass: QA roles, watcher roles, plan/guide roles, plus the singleton-style roles (meta_development, cluster_exploration, container_build, discuss).

**Scope.**
- In: `streams/qa_planning.py` + `qa_scenario.py` + `qa_concretize.py` + `qa_verification.py` + `qa_finalize.py` + `qa_author.py` + `qa_regression.py`; `streams/watchers/{auto_start, bug_fix_impl, improvement_fix_impl, discovery_supervisor, watcher_review}.py` + `streams/watchers/__init__.py` (WATCHER_REGISTRY); `streams/plan/{add, breakdown, review, deps, import_, fix}.py`; `streams/guide/{setup, assist}.py` with `STEP_ORDER` / `STEP_DESCRIPTIONS` / `SETUP_STATES` ClassVars on GuideSetupStream; `streams/meta_development.py`, `cluster_exploration.py`, `container_build.py`, `discuss.py` (with both `DiscussSystemPrompt` and `OnboardLearnSystemPrompt` variants).
- Out: PRStreamSupervisor / WatcherSupervisor / PlanStreamSupervisor that orchestrate these streams (next PR).

**Public API.** One Stream subclass + its InputType(s) per file. Each follows the framework laid down in the prior PR. `WATCHER_REGISTRY: dict[str, type[Stream]]` for string-to-class lookup. GuideSetupStream.STEP_ORDER ClassVars for `tui/guide_progress.py` consumption.

**Invariants.** Same as prior PR for each new Stream subclass. Auto-start-watcher remains tick-driven and stateless per-tick (NO_CHANGE shape from the audit). Watcher Streams use `LoopMode.continue_existing` on their tick tags; review-loop already kill_restart.

**Dependencies.** Prior PR (streams substrate + PRActionStream + Impl/Review/Signoff/Merge).

**Test plan.** One contract test per Stream subclass: instantiation, expected emission set, required capabilities. WATCHER_REGISTRY round-trip: every entry resolves to a registered Stream. GuideSetupStream STEP_ORDER consumed by tui/guide_progress.py without breakage.

**Migration plan.** Sources retired: `qa_loop.py` per-role logic (→ qa_* streams); `qa_authoring.py` (→ qa_author); `qa_finalize_prompt.py` + `qa_instructions.py` library knowledge (the library knowledge moves to plan-sensorium's Artifact substrate PR; the prompt portion lands in `qa_finalize.py` here); `regression_prompts.py` + `bug_fix_prompts.py` (→ regression / bug-fix-impl-watcher streams + watcher_review); `watcher_base.py` + `watcher_manager.py` per-watcher logic (→ streams/watchers/*; the manager / supervision part lands next PR); `cli/plan.py` plan-mode invocations (→ streams/plan/*; CLI surface remains for end-user invocation); `guide.py` (→ streams/guide/*); `cli/meta.py meta_cmd + _build_meta_prompt` (→ `streams/meta_development.py` — corrected per consolidation audit; previously misattributed to `wrapper.py`); `pane_ops.launch_discuss` + `launch_claude` generic-discuss flow (→ `streams/discuss.py` — corrected per consolidation audit).

**Open questions.**
- Whether to split this into two PRs (QA in one, the rest in the other). Lean: keep as one PR — the dependency on the prior streams-substrate PR is what matters; within this PR the roles are independent.

### PR: `pm_core/supervisors/` + `pm_core/watchdog/`

**Purpose.** Land the loop-orchestrator Supervisors that drive multi-stream coordination (review cycles, QA fan-out, signoff, merge with conflict resolution) plus the typed watchdog policies that surface lifecycle anomalies to humans.

**Scope.**
- In: `supervisors/protocol.py` (Supervisor Protocol + StreamRecord dataclass); `supervisors/watcher.py` (WatcherSupervisor + lease reconcile on startup); `supervisors/pr_stream.py` (PRStreamSupervisor — the review-loop driver + QA fan-out orchestrator + signoff + merge orchestration; per-PR overrides for self_driving / stop_before_merge / auto_approve_spec); `supervisors/plan_stream.py`; `supervisors/mind.py` (top-level MindSupervisor + `startup()` EmissionLog replay reconstitution); `supervisors/health.py` + `supervisors/coach.py`. `watchdog/policy.py` (base); `watchdog/staleness.py` (supersedes pr-923f22b); `watchdog/long_running.py`; `watchdog/budget_alarm.py`; `watchdog/orphaned_lease.py`; `watchdog/repeated_attention.py`; `watchdog/tui.py` (TUIDisplayWatchdog — single TUI consumption point).
- Out: TUI bindings (next PR); Mind class / bootstrap (final PR).

**Public API.** `Supervisor` Protocol (see plan-mind §11). `StreamRecord(stream_id, role, instance_key, state, parent_id, policy, last_emission_at)`. PRStreamSupervisor handler methods for `impl.lifecycle.commit-landed` → spawn fresh review iteration, `verdict.review.needs-work` → deliver impl feedback, `verdict.review.pass` → advance to QA, etc. (see plan-mind "Loop orchestration" section for full code example). `WatchdogPolicy` base + concrete subclasses subscribing to Supervisor + tag emissions.

**Invariants.**
- Loops live in Supervisors; Streams are participants, not orchestrators.
- Supervisor health-check / restart / escalation are internal supervision; Watchdog policies are external observers.
- `MindSupervisor.startup()` replays EmissionLog to reconstitute pre-restart watcher streams — no merge-restart marker file is consulted.
- `ResourceLease.reconcile()` is called on every Supervisor startup.

**Dependencies.** Stream framework + roles (prior two PRs); `pm_core/mind/` for Emission/EmissionLog/CallbackRegistry/AttentionService. Sensorium's ResourceLease (lands in plan-sensorium's resource coordination PR) is referenced — circular-ish; resolve via stub-import or sequence the resource coordination PR before this one.

**Test plan.** PRStreamSupervisor review-loop integration test: ImplStream emits commit-landed → fresh ReviewStream spawned with bumped instance_key → ReviewStream emits needs-work → ImplStream receives feedback message → cycle repeats. PRStreamSupervisor QA fan-out: planning → N scenarios → barrier on all-pass. Each Watchdog policy fires in the expected scenario. Lease reconcile sweeps a planted stale lease.

**Migration plan.** Sources retired: `watcher_manager.py` (→ WatcherSupervisor); the orchestration parts of `qa_loop.py` (→ PRStreamSupervisor); the orchestration parts of `review_loop.py` (→ PRStreamSupervisor); `pr_cleanup.py` (→ Supervisor teardown + ResourceLease.reconcile); `signoff.py` auto-sequence driver (→ PRStreamSupervisor) — **including `signoff.py:393 _BOUNCE_HOP_STATUS` and `decide_signoff_hop()`, which migrate into PRStreamSupervisor's verdict-routing layer keyed on `PRStatus` enum values (resolves the `"review"` hop-token vs `"in_review"` status-token naming drift the audit flagged)**; `pr-923f22b` watchdog (→ `watchdog/staleness.py`); `qa_status.py` watchdog parts (→ `watchdog/staleness.py` + `watchdog/tui.py`); `pr-18ac983` (→ Supervisor.supervise health policy); `pr-871dbf5` supervisor watchers (→ `supervisors/coach.py`); merge-restart marker file (→ `MindSupervisor.startup()` replay).

**Open questions.**
- Whether `health.py` and `coach.py` are separate Supervisors or policies installed on the existing concrete Supervisors. Lean: policies on the concrete ones; `health.py` and `coach.py` provide reusable policy objects.
- Watchdog's relationship with Supervisor: does Watchdog subscribe via Supervisor.on_state_change exclusively, or does it also subscribe directly to tag emissions? Lean: both — state-change for lifecycle, tag emissions for budget/attention/lease events.

### PR: `pm_core/tui/pr_actions/` — typed TUI bindings

**Purpose.** Land the typed TUI binding family paired with PRActionStream subclasses. Catches the missed-keybinding failure mode (plan-quality's motivating example) at TUI startup and in CI. The same typed family also drives the `prefix+P` PR-action picker popup (today implemented in `pm_core/cli/session.py` with its own hard-coded duplicate maps: `_ALL_ACTIONS`, `_ACTION_WINDOW_PATTERNS`, `_LIST_ACTIONS`, `_SHORTCUT_FOLD_INTO`, `_STATUS_PHASE`, `_MODIFIED_ACTION_CMDS`, `_SHORTCUT_KEYS`). After this PR there is one source of action knowledge across `app.py` keybindings AND the picker.

**Scope.**
- In: `tui/pr_actions/_registry.py` (`check_pr_action_bindings_complete()` runs at TUI startup AND as a pytest test); `tui/pr_actions/base.py` (`PRActionTUIType` base with `__init_subclass__` validation, `Keybinding`, `CompanionPaneSpec` dataclasses); `tui/pr_actions/{impl, review, qa, signoff, merge, ...}.py` (one binding per PRActionStream subclass); `tui/pr_actions/__init__.py` importing each binding module.
- In: rewire `pm_core/cli/session.py` PR-action picker (prefix+P) to enumerate `PRActionTUIType.__subclasses__()` filtered by PR status, removing the duplicate `_ALL_ACTIONS` / `_ACTION_WINDOW_PATTERNS` / `_LIST_ACTIONS` / `_SHORTCUT_FOLD_INTO` / `_STATUS_PHASE` / `_MODIFIED_ACTION_CMDS` / `_SHORTCUT_KEYS` constants.
- In: rewire the *other* window-name consumers identified by the duplication audit to enumerate `PRActionTUIType.__subclasses__()` and read `window_role` instead of hardcoding the `(?:review-|merge-|qa-|signoff-)?` alternation. Sites identified by audit rounds 1 + 2: `pm_core/cli/session.py:981-988` (`_current_window_pr_id` regex builder + `_current_window_phase`); `pm_core/tui/sync.py:22` (`_kill_merged_pr_windows`); `pm_core/cli/helpers.py:326-327` (`kill_pr_windows` prefix list); `pm_core/cli/pr.py:1135` (`f"review-{display_id}"`), `:1608` (`f"merge-{display_id}"`), `:3072` (`f"qa-{display_id}"`); `pm_core/tui/pr_view.py:188` (`f"review-{display_id}"`), `:241` (`f"signoff-{display_id}"`); `pm_core/tui/review_loop_ui.py:79, 138, 692, 899, 970` (review-window references throughout the review-loop UI delegator). Most of these absorb transitively (review_loop_ui collapses into thin delegators per migration-map; cli/pr.py thins to Stream delegators; pr_view rewires through `Mind.stream(role=...)`), but the f-string sites are explicitly named so a reviewer doesn't leave them as residual literals. After this PR there is no string-literal `"review-"`/`"qa-"`/`"merge-"`/`"signoff-"` prefix anywhere outside the `PRActionTUIType` subclasses themselves.
- Out: The TUI's actual rendering code (lives in `pm_core/tui/app.py`, unchanged structurally).

**Public API.** `PRActionTUIType` base with ClassVars:
- `stream_class: type[PRActionStream]` — backlink to the mind-layer Stream
- `keybinding: Keybinding` — main-screen key (today's `Binding(...)` in `app.py`)
- `picker_shortcut: str | None` — the letter pressed inside the prefix+P picker (`s/e/d/t/g`); `None` for shortcut-only-via-modifier actions
- `command_template: str` — the `pm`/`tui:` command the picker executes (today's `_ALL_ACTIONS` second slot)
- `window_role: str | None` — tmux window-name pattern; `None` for actions that don't open their own window (edit)
- `applicable_statuses: frozenset[PRStatus]` — replaces `_actions_for_status()` filtering
- `picker_list_row: bool` — whether the action gets its own picker row vs. shortcut-only (replaces `_LIST_ACTIONS`)
- `fold_into: str | None` — for shortcut-only actions whose status badge displays on another action's row (replaces `_SHORTCUT_FOLD_INTO`)
- `phase_label: str | None` — for actions that name a PR phase (replaces `_STATUS_PHASE`)
- `modifier_variants: dict[str, str] = {}` — z/zz chord → command-template override (replaces `_MODIFIED_ACTION_CMDS`)
- `glyph: str`, `companion_panes: list[CompanionPaneSpec] = ()` — as before
One subclass per PRActionStream subclass with concrete ClassVars. `check_pr_action_bindings_complete()` callable from TUI startup or a pytest test.

**Invariants.**
- Every `PRActionStream` subclass has a matching `PRActionTUIType` subclass (asserted at TUI startup + in pytest).
- Every `PRActionTUIType` subclass's `stream_class` is a registered `PRActionStream` subclass.
- No two `PRActionTUIType` subclasses bind to the same `PRActionStream`, share a main `keybinding`, or share a `picker_shortcut`.
- The set of `PRActionTUIType` subclasses with `picker_list_row=True` matches what the prefix+P picker enumerates — no parallel registry in `cli/session.py`.
- Every `fold_into` value names an existing `PRActionTUIType` (no orphan folds).
- No string-literal `"review-"` / `"qa-"` / `"merge-"` / `"signoff-"` window-name prefix appears outside `PRActionTUIType` subclasses. Enforced by a CI grep test (`tests/test_no_hardcoded_window_prefixes.py`) that scans `pm_core/` for those literals.

**Dependencies.** Stream framework + PR-action roles. `pm_core/tui/app.py` rewires its keybinding/glyph/window-naming logic to consult `PRActionTUIType` subclasses. `pm_core/cli/session.py` picker code-path rewires to consult the same subclass list — both call sites use one source.

**Test plan.** `tests/test_pr_action_bindings.py` asserts completeness for every PRActionStream subclass. Property tests: adding a hypothetical PRActionStream without a binding fails the check; adding it with a binding passes; adding two bindings with the same `picker_shortcut` fails. Picker parity test: enumerate `PRActionTUIType` and assert the picker would render the same labels/shortcuts the user sees. TUI startup runs the check and fails with a clear error.

**Migration plan.** Hard-coded `Binding(...)` tuples in `pm_core/tui/app.py` (today's bug source) migrate to `PRActionTUIType` subclasses. `tui/app.py` iterates `PRActionTUIType.__subclasses__()` to build its keybinding/glyph/icon-mapping registries. In `pm_core/cli/session.py` the picker constants delete: `_ALL_ACTIONS`, `_MODIFIED_ACTION_CMDS`, `_ACTION_WINDOW_PATTERNS`, `_LIST_ACTIONS`, `_SHORTCUT_FOLD_INTO`, `_STATUS_PHASE`, `_SHORTCUT_KEYS`, `_actions_for_status()`; `_resolve_for()` consults `PRActionTUIType` subclasses filtered by `applicable_statuses`. The prefix+M pm-command-runner popup is unaffected (it's not a PR-action surface).

**Open questions.**
- Whether the `_check_complete` test should be a generic pytest fixture or a dedicated test file. Lean: dedicated test file `tests/test_pr_action_bindings.py` for discoverability.
- Where the picker's fzf-input formatting lives — on `PRActionTUIType` (a `picker_row(pr_state) -> str` method) or in a single picker-renderer in `cli/session.py` that reads the ClassVars. Lean: renderer in `cli/session.py`; ClassVars stay pure data so non-fzf renderers (web, voice) can read the same source.

### PR: `pm_core/mind.py` Mind class + `pm_core/bootstrap.py` entry shim

**Purpose.** Land the top-level `Mind` singleton class that's the single source of truth for cross-stream state, plus the renamed `bootstrap.py` entry-point shim. With this PR, pm has a complete typed substrate; subsequent work is consumer migration.

**Scope.**
- In: `pm_core/mind.py` (Mind class — singleton-per-project enforcement; `stream/streams/shutdown/list_transcripts/mailbox/log_of/transcript_of/schedule/cancel_schedule/supervisor` methods + `callbacks`/`attention` properties); `pm_core/bootstrap.py` (renamed from `wrapper.py` — dispatches between hook_entry / reentry / normal modes via `runtime/hook_entry.py` and `runtime/reentry.py` from the additional-runtimes PR).
- In: `pm_core/_path_constants.py` — a tiny module with ONLY standard-library imports (`pathlib`) defining the complete per-session on-disk vocabulary:
    - `PM_HOME = Path.home() / ".pm"`
    - `SESSIONS_SUBDIR = "sessions"`
    - `PM_ROOT_FILENAME = "pm_root"` (wrapper.py:144 / paths.py:515,527)
    - `OVERRIDE_FILENAME = "override"` (wrapper.py:39 / paths.py:548,562) — audit PC-2
    - `FAKE_CLAUDE_FILENAME = "fake-claude"` + `FAKE_CLAUDE_STATE_FILENAME = "fake-claude.state"` (paths.py:292,409,424) — audit PC-2 extension
    - `PM_SHARE_MODE_ENV = "PM_SHARE_MODE"`
  Both `bootstrap.py` (which must run BEFORE `pm_core` is importable for the user's CLI invocation) and `paths.py` derive from these constants. Eliminates the silent on-disk-contract drift the audit flagged between `pm_core/wrapper.py:39, 144` and `pm_core/paths.py:292, 409, 424, 507-537, 540-562`. CI grep test forbids string literals `"pm_root"` / `"override"` / `"fake-claude"` / `"fake-claude.state"` in `pm_core/` outside this module. Includes parity test `tests/test_bootstrap_session_tag_matches_paths.py` covering `PM_SHARE_MODE` hashing and `use_github_name=True` branches.
- Out: any consumer migration (those happen in follow-on PRs after the trio is established).

**Public API.** `Mind` class — methods listed above. Singleton-per-project: `Mind` constructor enforces that no other `Mind` exists in the current process; tests can override via a `_reset_for_tests()` helper. `bootstrap.py` is a CLI entry point; the public surface is the dispatch behavior, not Python API.

**Invariants.**
- Exactly one `Mind` per running pm process. Multiple `Mind()` calls in the same process raise `MindAlreadyExistsError`.
- `bootstrap.py` always runs before `pm_core.mind.Mind` is importable for the user's CLI invocation. The dispatch routes are mutually exclusive (hook_entry mode XOR reentry mode XOR normal mode).
- The TUI is a thin layer over Mind — every TUI read/write of stream state goes through Mind, no separate caches.

**Dependencies.** Every prior PR. Bootstrap depends on `runtime/hook_entry.py` + `runtime/reentry.py` (additional-runtimes PR).

**Test plan.** Mind singleton enforcement: two Mind() calls raise. `Mind.streams(role=)` discovery returns expected streams. `Mind.schedule(...)` persistence: schedules survive Mind restart (via EmissionLog replay through MindSupervisor.startup). TUI startup integration: TUI initializes against Mind and renders correctly. Bootstrap dispatch matrix: each of the three modes invoked correctly.

**Migration plan.** Source retired: `pm_core/wrapper.py` (renamed to `bootstrap.py`; some of wrapper.py's mode-dispatch logic relocates to the runtime entry routes). All consumers of "the current pm state" (`tui/app.py`, `cli/*` commands, `home_window/*`) update their imports to consult `Mind` rather than directly reading `runtime_state.py` / `pm/watchers/<name>.log` / etc. After this PR lands, the migration sketch's deletions (`bridge.py`, `bridge_client.py`, `verdict_transcript.py`, `loop_shared.py`, `runtime_state.py`, `qa_loop.py`, `review_loop.py`, `watcher_base.py`, `watcher_manager.py`, `pane_idle.py`, `qa_status.py`, etc.) all complete.

**Open questions.**
- Single-process singleton enforcement: do we need a multi-process variant ever? The cross-machine-mind future (deferred) would, but not in this refactor.
- Backward-compat shim for `pm_core.wrapper` imports during transition: keep a stub `pm_core/wrapper.py` that re-exports from `bootstrap.py` for one release, or break cleanly. Lean: break cleanly; deletion is the point.

## Disposition table for existing items

### Bulk-approved: ship as-is (no changes from refactor)

The refactor sits below or beside TUI/CLI/UX/git-plumbing surfaces.

**Plans:** plan-e4fa5cb, plan-c493724, tui-ux, onboarding, plan-cb4ef69, plan-ambient, plan-state, plan-66d430f, plan-b6aac3d, improvements.

**PRs:** pr-7f01e33, pr-ff68ef5, pr-30888b1, pr-92301fc, pr-7f958f3, pr-156a4d0, pr-fd54424, pr-0b827df, pr-6aa74c6, pr-ac12b47, pr-9a5b86e, pr-fc6db6a, pr-1735d44, pr-4db3696, pr-4702a11, pr-cfe24ea, pr-fcaa434, pr-3526677, pr-e5b4dd8, pr-fe4ca5d, pr-f74988c, pr-23d97f8, pr-6f542a2, pr-c1f8086, pr-d887f4c, pr-ca6981c, pr-9330dec, pr-9b96145, pr-8d8b360, pr-8409c64, pr-8e693f6.

### Bulk-approved: ship now, mechanical port to TmuxHostRuntime/Stream after the runtime + streams PRs land

Single-call-site `launch_pane` / pane registry / `runtime_state` touches. Logic and policy survive intact.

pr-b764a0c, pr-89296d3, pr-cb2a29d, pr-0b4e1a9, pr-c41f029, pr-3d1fa55, pr-a6ef6be, pr-8aa9411, plan-3119574, plan-ff4f1a7.

### Bulk-approved: hold pending the supervisors PR; re-scope phase breakdown atop new primitives

Plans that invent coordination primitives the refactor delivers natively. Re-scoping (not rewriting from scratch) is the right move.

plan-self-improve, plan-984dfeb, watchers.

### Bulk-approved: hold pending the runtime PR; port to TmuxContainerRuntime + Mind

pr-eb2dbfc (memory governor), pr-438028c (loop_daemon).

### Bulk-approved: supersede + rewrite from scratch

plan-qa (out of date independent of refactor), bugs.txt (unstructured backlog, same treatment).

If we identify a refactor gap during the rewrite, review together before discarding the original.

### Bulk-approved: absorbed into refactor

- **pr-1d8b2b7 (VerdictRegistry)** — becomes the `Emission` tag-schema registry in the mind primitives PR.

### Bulk-approved: supersede; close, harvest policy, re-encode in refactor

- **pr-923f22b (TUI watchdog)** — re-encoded as typed `WatchdogPolicy` consuming Supervisor state in the supervisors + watchdog PR (`watchdog/staleness.py` specifically). Harvest any policy nuance before close.
- **pr-18ac983 (session health watcher)** — re-encoded inside `Supervisor.supervise` keep-warm chain in the supervisors PR. Harvest staleness thresholds and retry-after policy before close.
- **pr-871dbf5 (supervisor watchers)** — re-encoded as a Supervisor subclass / policy in the supervisors PR (`supervisors/coach.py`). Harvest prompt template (becomes a `InputType`) and coverage policy.

### Bulk-approved: in-flight PRs that hold for refactor

- **pr-ff9b728 (auto-start watcher)** — waits for the remaining-streams PR; rewrites against new primitives.
- **plan-regression Phase 10 (regressions-as-scenarios)** — held; sequence after the supervisors PR lands. The feature is naturally a typed `InputType` + typed `Payload` (`RegressionSpec`) composition under `PRStreamSupervisor`.

### Individual review (none remaining)

All open items resolved.

## Suggested sequence

1. **Clear the queue** — merge the ~41 ship-as-is items and the ~10 mechanical-port items on master.
2. **Run the 13 refactor PRs in dependency order** — see the per-plan "Implementation PR sequence" sections above. Roughly: payloads → mind primitives → runtime substrate → streams substrate + roles → supervisors + watchdog → TUI bindings → Mind class + bootstrap (plan-mind's 9 PRs), interleaved with plan-sensorium's 3 PRs (Artifact substrate → resource coordination → side-effects + redaction) and finishing with plan-collaboration's cross-mind PR.
3. **Re-scope** plan-self-improve, plan-984dfeb, watchers Phase 2/3 after the supervisors PR lands. Rewrite plan-qa and bugs.txt fresh under the new substrate.

## Interaction examples

### Example A — impl → review → signoff → merge with code-as-truth respected end-to-end

1. `impl-session` emits `Emission(tag='impl.lifecycle.ready-for-review', payload={pr:42, head_sha:'abc', concerns:[]})` → appended to its `EmissionLog` and posted to mailbox `pr:42:impl-lifecycle`. No prose, no summary field on the schema.
2. `review-loop`'s Stream has `callbacks.on('impl.lifecycle.ready-for-review', from_stream='impl:42')`; on receipt the wrapper renders a `ReviewSystemPrompt` whose `prior_findings_log_query` returns `verdict.review.needs-work` entries from its own log. No impl summary injected. Reviewer reads diff via `GitDiffAtSha(base, head='abc')` — pulled by the runtime, not summarized into the prompt.
3. Reviewer emits `Emission(tag='verdict.review.pass', payload={pr:42, head_sha:'abc', confidence:0.9})` to `pr:42:review-verdicts`. Payload schema has no prose field.
4. `signoff-router`'s callback on `verdict.review.pass` fires; router rehydrates (log-replay policy: read its own log + query review's log for tagged findings only + query `pr:42:scenario:*:verdict` mailbox). Router reads diff via `GitDiffAtSha` itself.
5. Router emits `verdict.signoff.merge` to `pr:42:signoff-verdict`. Merge-driver's callback fires, runs `gh pr merge`. On conflict, raises `merge-conflict-resolver` Stream for `pr:42:merge-resolver` which reads conflict hunks via `GitDiffAtSha` from the working tree and reads impl's `note.impl.design-choice` tagged outputs from impl's log for intent — never a summary.

### Example B — QA scenario worker posting verdict via mailbox + verifier subscribing with callback

1. `qa-scenario-session('pr:42:s3')` executes scenario, emits `Emission(tag='verdict.scenario.pass', payload={scenario_idx:3, branch_sha:'abc', evidence_refs:[LogQuery(...)]})` posted to mailbox `scenario:42:3:verdict`.
2. `qa-verification-session('pr:42:s3')` registered `callbacks.on(tag='verdict.scenario.pass', from_stream='qa-scenario:42:s3')` at boot. Callback fires, verifier resumes via the persistence chain (keep-warm if its runtime is still alive, else log-replay regen from the EmissionLog + InputType inputs), reads scenario spec from its own log + fixture via `TestFixture` Payload (pointer from mailbox `scenario:42:3:fixture-state`), independently re-executes assertions. Does NOT consume any "evidence summary" from the scenario worker.
3. Verifier emits `verdict.qa-verify.verified` to `scenario:42:3:verify-verdict` and signals `pr:42:finalize-gate`.
4. `qa-finalize-session` has subscribed to `pr:42:scenario:*:verdict` and `pr:42:verifier:*:verdict`; its gating predicate (`Mailbox.latest` queries) sees every PASS has a matching ACCEPT, fires its callback, runs cleanup + push, emits `verdict.qa.finalize.done`.

### Example C — stream requesting user attention via dashboard with resumption

1. `qa-concretize-session` hits two plausible user-facing surfaces for the same Given step. Calls `mind.attention.raise_(tag='request.user-attention.surface-ambiguous', payload={scenario_id:'s7', candidate_surfaces:['pm foo','pm bar'], question:'which surface satisfies When?'}, blocking=False, reply_to='pr:42:attention:responses')` → returns AttId.
2. Same call appends a Emission to refiner's EmissionLog (audit) and posts to mailbox `attention:global` which the TUI dashboard subscribes to.
3. Refiner registers `callbacks.on(tag='attention.resolved.surface-ambiguous', where=lambda m: m.payload['att_id']==att_id, once=True, handler=self.resume_with)`. Refiner Stream hibernates — runtime instance torn down; id+log+transcript stay durable.
4. Human resolves on dashboard; `AttentionService.resolve(att_id, reply={'surface':'pm bar'})` posts `Emission(tag='attention.resolved.surface-ambiguous', payload={att_id, reply:{...}})` to `pr:42:attention:responses`.
5. Callback wakes refiner: `mind.stream(role=RefinerStream, instance_key='42').resume()` walks the persistence chain (keep-warm if still alive, else log-replay regen — replays InputType inputs from EmissionLog into a fresh runtime), feeds reply as structured input, refiner proceeds with the chosen surface and emits `verdict.refiner.refined`.

## Open questions

- Keep-warm eviction policy on Tmux roles — how long does a stream stay warm before its runtime is torn down to free resources? Idle-evict after N minutes is the obvious answer; specific N to determine in the runtime PR's instrumentation.
- Cross-process Mailbox: in-process default works for single-pm; `cluster-exploration-session` and `meta-development-session` imply multi-process. Defer to Redis backend after the trio's substrate is stable.
- **Cross-machine minds (deferred future work).** Today one Mind exists per pm process per machine. Restartable streams already enable handoff (machine A fails, machine B picks up the same `role:instance_key` and continues from EmissionLog + InputType replay). Actively coordinated multi-machine Minds — leader election per stream, machine-spanning Mailbox transport, distributed schedule — are out of scope for this refactor but the architecture admits them (project-namespaced channels, Redis-backed Mailbox post-trio, log as durable substrate). Worth recording so the design choices that enable it (no `claude --resume` reliance, project-relative EmissionLog path, machine-agnostic InputType replay) are not regressed.
- `AttentionRequest` correlation when one root cause raises N requests across N scenarios — proposed as a `correlation_id` field on the `Emission` envelope rather than a new primitive. Validate when the dashboard surface lands (downstream of the Mind class PR).
- Fixture lease / mutex for sibling scenarios sharing a container — provided by `ResourceLease` in plan-sensorium. The wrapper exposes lease state via Emission notifications but doesn't define the lease primitive itself.
- Concrete starter set of `Payload` subclasses for the payloads PR — the list above is provisional. Final list determined by which prompts/messages get extracted first into the `pm_core/streams/` per-role files.
- Instance-key conventions — `role:instance_key` is the universal addressing scheme but the formation of instance_keys is per-role (PR id, scenario idx, cycle counter, random). The tag registry should document the canonical instance-key shape for each role so cross-session callbacks can address them without guessing.
- **Token-savings claim is unverified.** The shape-improvements audit argued persistent streams save tokens because tool calls don't repeat across turns. Skeptical position: accumulated context grows over time and may cost as much or more than fresh-start turns. Measure on impl + bug-fix-impl-watcher + qa-verification in the streams PR(s). Worst case: keep the architectural benefits (verdict-of-verdict reasoning, takeover-friendly, simpler peer subscription) without the token claim.
- Pane lifecycle under persistent streams — multiple roles (qa-scenario, qa-verification, container-build) rely on tmux panes for human inspection. Persistent stream + many ticks doesn't map cleanly to "one pane per session" today; the TUI shim layer needs an explicit "pane shows current activity, scrollback shows hibernated history" model.
- Resource cleanup differentiation on hibernate vs terminate — container mounts, sockets, worktrees release semantics differ. Hibernate should preserve; terminate should release. `on_cancel(handler)` covers terminate; needs a `on_hibernate(handler)` counterpart for partial release (drop runtime, keep container).
- StreamTranscript read-side latency on live streams — verifier-style peers reading the scenario worker's transcript want fresh evidence with no observable lag. Probably fine for flat-file append + tail, but worth validating under the actual write rate.
- Fresh-start UX for persistent roles — `instance_key` answers the structural question (new key = new stream) but the user-facing controls (`--fresh`, `pm <role> reset`) need to be defined so users can request blind invocations consistently.
- For plan-984dfeb (living artifacts): are PARALLEL_OK / COUNTER_PROPOSAL / ABSORB / DISSIPATE shapes core `Emission` conventions (and thus part of the tag registry) or higher-layer schemas built on top? Decide during plan-984dfeb re-scope, not in this plan.

## Status counts

- pending: 0 (none filed yet; `pm plan load plan-agent-wrapper` after approval)
- in_progress: 0
- merged: 0
