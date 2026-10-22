# Sensorium — Typed Substrate for the Shared Environment pm Interacts With

(the shared world streams perceive and act on: pm's own CLI, pm's own artifacts, the host/runtime filesystem, container resources, the tmux namespace, branch refs, captures of non-textual side effects — typed primitives so the mind reads/writes via contracts instead of ad-hoc shell-outs and FS hacks)

> Names settled during the agent-wrapper refactor: `Artifact` (was `EditableArtifact`), `Stream` / `Emission` / `EmissionLog` / `Mind` inherited from [[plan-mind]]. `Payload` (the typed-payload Protocol from plan-mind) is distinct from `Artifact` (the on-disk shared mutable thing defined in this plan).

## Framing

### On the term *Sensorium*

The word is Latin: `sensus` (sense) + `-orium` (place) — "the seat of sensation." Newton (1713) used it for the integrating field of perception, famously extending it to "God's sensorium" being all of space. Through the 17th–18th centuries it meant the perceiver's own apparatus (the brain, the central nervous system as the integrator of senses). Modern usage, especially in anthropology-of-the-senses (David Howes and successors) and in process philosophy, has drifted toward the broader sense of "the totality of what is perceivable" — the field of perception itself rather than the apparatus that perceives.

We use the term in a **deliberately dual** sense, holding both timeframes at once:

- **Sensorium as ultimate scope** — everything streams of consciousness may be able to perceive. The internet, every computer, every peripheral, every artifact published by every other mind, every public signal. The entire perceivable world. pm controls only a small piece of this — the git repo, the local filesystem, the resources pm directly coordinates (see the currently-typed slice below). Streams reach the rest through their runtime's normal tools (web fetch, shell, MCP, anything the runtime exposes); the wrapper doesn't try to type those interactions.
- **Sensorium as currently-typed slice** — the parts pm has actually wrapped with typed primitives: pm's CLI surface as `PmCommand`, pm's own artifacts as the `Artifact` family, resources we coordinate via `ResourceLease`, captures via `CaptureBundle`, redaction at our write boundaries. The slice grows over time as more of the broader sensorium becomes worth typing.

Both readings coexist by design. When we say "the sensorium includes the public web" we're using the ultimate-scope reading; when we say "the Sensorium plan documents the typed slice" we're using the currently-typed reading. [[plan-collaboration]] uses the term in the ultimate-scope sense — cross-mind interaction happens in the broader perceivable world (most often via the public sensorium pm doesn't control), and plan-collaboration types a narrow piece of it for the cases where pm guarantees matter.

The wrapper substrate in [[plan-mind]] models **streams of consciousness** (the mind). This plan models the sensorium in the currently-typed sense — pm's contribution to what minds can perceive with schema, ACL, change-notify, atomic writes. The ultimate-scope sensorium is the horizon this plan grows toward, not the surface it currently delivers.

**What this plan does** is document the TYPED PRIMITIVES pm provides over its **own slice** of the sensorium — the parts pm-the-tool manages and can offer schema validation, atomic writes, change-notify, and ACL for. Outside this slice, streams still touch the sensorium freely via their runtime; pm just doesn't promise typed handling.

What's in pm's slice (this plan):

- pm's own CLI surface as a typed callable interface for streams (`PmCommand` hierarchy).
- pm's own artifacts (`project.yaml`, plan files, notes, QA specs, spec files, etc.) as typed mutable shared state via the `Artifact` family.
- Resources with mutual-exclusion semantics that pm coordinates — tmux window names, branch refs, container names, workdirs, leader slots — via `ResourceLease`.
- Non-textual artifacts pm captures as side-effect deposits (screenshots, log files, binary captures) via `CaptureBundle`.
- Host-code-override mechanisms (e.g. meta-development binding a sibling pm checkout into the running pm's `sys.path`).
- Write-time redaction at pm's durable-record boundaries (filtering secrets out of transcripts and structured-output logs before they persist).
- Host/runtime path duality when streams run in containers pm operates.

What's NOT pm's slice (and isn't documented here):

- The whole rest of the sensorium — the open web, third-party APIs, GitHub, hardware, other minds' published state. Streams interact with these via their runtime's existing tools, without typed primitives from pm.
- Stream lifecycle, scheduling, supervision, addressability, persistence, budget, lifecycle observability — all in plan-mind.
- Typed primitives for sharing pm-typed Artifacts across mind boundaries (the narrow case where two minds both want pm's Artifact features without relying on the broad public sensorium) — in plan-collaboration.

**Sensorium-as-ambient-cross-mind-substrate.** The reason two minds on separate machines on the same project already share state through git/filesystem/Artifacts is that they share access to the *broader* sensorium — git, GitHub, the filesystem. They don't need any pm-specific transport for that. Plan-collaboration's typed cross-mind primitives are for the narrower case where pm-specific guarantees (schema, ACL, change-notify) matter and the public sensorium doesn't provide them.

### The sensorium is also the ambient cross-mind substrate

Two minds operating on separate machines on the same project already interact through the sensorium today — committed git state, synced project files, shared filesystem. One developer's Mind writes `pm/plans/plan-X.md` and commits; another developer pulls and their Mind sees the updated `PlanArtifact` via its change-notify. **No collaboration plumbing required for this — the sensorium IS the substrate.** Filesystem permissions + the underlying sync mechanism (git, rsync, network filesystem) act as the authority layer; no explicit identity attestation is needed because the parties already trust each other at the filesystem level.

[[plan-collaboration]] is for two distinct cases the sensorium does NOT cover:

1. **Minds with their own goals that may disagree** — separate entities (different teams, different projects, different priorities) need typed language for surfacing disagreements they can't immediately resolve. Filesystem sharing has no semantics for "I think your X is wrong"; the federation primitives in plan-collaboration do.
2. **Task complexity exceeding one project** — when a project must split into multiple components, the compression between them takes shapes like public docs, releases, stable interfaces, versioned dependencies. Plan-collaboration's federation is the typed substrate for that compression.

A single pm project + ambient sensorium is sufficient when neither applies — one team, one mind, no inter-project boundary. Plan-collaboration kicks in when the project either splits or interacts with parties whose goals are not aligned by default.

## Design principles

1. **Sensorium notifies the mind via Emission.** Every mutation of a sensorium primitive (an artifact write, a lease acquired, a capture deposited) emits a Emission on a well-known schema (`artifact.<name>.changed`, `lease.<key>.acquired`, `capture.<bundle>.appended`). Streams subscribe via the mind's CallbackRegistry. The sensorium does not have its own message bus.
2. **Side effect is the arbiter of truth.** Sensorium primitives expose typed read surfaces (`read() -> (data, version)`, `grep`, file-bytes-at-sha) but never paraphrase. A stream that wants to know what's in an artifact reads the artifact, not a summary.
3. **Atomic write or no write.** Mutations to schema-bound sensorium artifacts use tempfile + rename, optimistic-lock by version, ACL by write tier. A torn write must not be observable.
4. **Host/runtime path duality is first-class.** When a stream runs in a container, paths have dual views (host_path, runtime_path). The sensorium provides typed mapping; streams don't hand-construct paths.
5. **Redaction happens at write seam, not at read.** Secrets filtered before they enter the durable record. Reading is unredacted because the data was redacted on the way in.
6. **No primitive owns lifecycle of streams.** The sensorium can lock resources (preventing two streams from claiming the same tmux window) but does not start, stop, supervise, or budget streams. Those are mind concerns.

## Primitives

### 1. `Artifact` (concrete)

A persistent on-disk mutable artifact used as a coordination channel between streams and humans. **Schema-bound, version-tracked, ACL-guarded, change-notifying.** Not every file on disk is an `Artifact` — `Artifact`s are specifically the files where two or more parties (humans + streams, or multiple streams) write and read coordinated state, where typed schema + atomic write + change-notify matter. Source code, build outputs, single-writer scratch files, and read-only data are ordinary files, not `Artifact`s.

[[plan-984dfeb]] (living artifacts) builds on top: a living artifact has all the `Artifact` machinery plus a "wants" schema, a negotiation protocol, and split/merge/absorb/dissipate lifecycle operations. This plan delivers the substrate; living-artifacts adds the negotiation layer.

```python
class Artifact:
    name: str
    path: Path                                       # canonical host path
    schema: type[Payload]                       # Payload subclass that validates content
    write_acl: Optional[set[type[Stream]]] = None    # Stream subclasses allowed to apply edits; None = open

    def read(self) -> tuple[Payload, int]                          # (data, version)
    def propose_edit(self, edit: Edit) -> ProposedEdit
    def apply(self, edit: Edit, base_version: int) -> int               # returns new version; raises VersionConflict
    def history(self, limit: int = 50) -> list[Edit]
    def on_change(self, handler) -> SubId                               # convenience over the global notification

    # watched-editor support
    def open_in_editor(self, who: str = '$EDITOR') -> EditorHandle      # spawns $EDITOR, returns handle
    def watch_for_save(self, handle: EditorHandle) -> AsyncIterator[Edit]   # mtime-poll → yields each saved edit

    # cross-artifact link convention
    @classmethod
    def resolve_link(cls, ref: str) -> Optional['Artifact']             # '[[pr-42]]' / '[[plan-quality]]' → typed Artifact handle
```

**Watched-editor support** is on the base class — every Artifact subclass inherits it. Today's per-Artifact-type editor logic (open the file in $EDITOR, watch mtime, parse on save) becomes one implementation in `Artifact`. The handle survives across saves so the human can iterate.

### External writes (bypassing `apply()`)

`apply()` is the typed-API write path that runs ACL + schema validation + atomic-write + change-notify. **It is not the only way the underlying file can change.** A human running `vim pm/project.yaml`, an agent using a raw `Write` tool, a `git pull` updating a tracked file, or any external process changes the file without going through `apply()`. The Artifact primitive cannot prevent this — the filesystem doesn't know about pm's ACL. What it CAN do is detect and reconcile.

```python
class Artifact:
    def _on_external_change(self, new_mtime: float, new_sha: str) -> None:
        """Called by the file-watch background task when a change is detected
        that did not come from this Artifact's apply()."""
        try:
            data = self.schema.from_payload(self._parse_file())
        except SchemaError as e:
            mind.attention.raise_(
                tag='request.user-attention.artifact-schema-broken',
                payload={'artifact_name': self.name, 'path': str(self.path), 'error': str(e)},
                blocking=False,
            )
            return                           # do not bump version; do not emit changed
        new_version = self._bump_version()
        mind.mailbox(ArtifactChangeChannel(self.name)).post(
            Emission(
                tag=f'artifact.{self.name}.externally-changed',
                payload={'version': new_version, 'sha': new_sha, 'editor_stream_id': None},
                visibility=VisibilityTier.private,
                ...
            )
        )
```

**Two distinct change tags:** `artifact.<name>.changed` (came through typed `apply()` — has `editor_stream_id`) and `artifact.<name>.externally-changed` (file mutated outside the typed API — no editor identity, may have come from `vim`/`git pull`/`Write`/anything). Streams that care about provenance subscribe to one or both:

- A change-driven trigger (e.g. plan-review-stream re-runs when `plan-quality.md` changes) subscribes to BOTH and treats them equivalently.
- An audit trail (who edited what when) subscribes to `.changed` only — external changes have no identity to log.
- A schema-validation watcher subscribes to `.externally-changed` to surface unauthorized-shape writes (today's "someone hand-edited project.yaml and broke a field" failure mode becomes a typed `AttentionRequest`).

**Schema-invalid external writes don't bump the version** — the parse failure raises an `AttentionRequest` and leaves the in-mind version unchanged. The Artifact is effectively "broken on disk" until a human resolves. Subsequent `apply()` attempts still use the last-known-good version, so an in-flight agent edit doesn't compound with a broken hand-edit.

**ACL on external writes** is intentionally NOT enforced (filesystem can't); the model is observe-and-react, not gate. If you want hard enforcement, use filesystem ACLs or a hook on the typed write path that refuses non-typed writes — both are out of scope here.

### Schema-aware interactive editing — `Artifact.edit_interactively`

Today's `pm pr edit <pr_id>` and `pm plan edit <plan_id>` open the file in `$EDITOR` and trust the user. Schema-aware editing closes that loop:

```python
class Artifact:
    def edit_interactively(self, who: str = '$EDITOR', max_attempts: int = 3,
                           surface: Literal['cli', 'tui'] = 'cli') -> int:
        """Open the editor on this artifact; on save, validate; on error,
        show errors and re-open. Returns final version on success, or
        raises EditAbandoned after max_attempts."""
        for attempt in range(max_attempts):
            handle = self.open_in_editor(who)
            edit = await_next_save(handle)
            try:
                return self.apply(edit, base_version=self.current_version)
            except (SchemaError, VersionConflict) as e:
                self._show_edit_error(e, surface)        # CLI: stderr; TUI: error panel
                # editor stays open with the user's invalid content; loop continues on next save
        raise EditAbandoned(f"{self.name}: could not validate after {max_attempts} attempts")
```

**CLI surface.** The current `$EDITOR` flow + validate-on-save + reopen-with-errors covers the immediate case. `pm pr edit <pr_id>` becomes a `PmCommand` that materializes the appropriate Artifact (today: a slice of `ProjectYamlArtifact`; longer term: per-PR `PrArtifact` subclass) and calls `edit_interactively(surface='cli')`. Same shape for `pm plan edit <plan_id>` over `PlanArtifact`, `pm regression edit <id>` over `QaRegressionArtifact`, etc.

**TUI surface.** A typed form widget per schema kind, generated from the `Payload` schema via `dataclasses.fields()` introspection. Field types map to widgets (`str` → text input, `bool` → checkbox, `Literal[...]` → select, `list[...]` → repeatable section, nested dataclass → sub-form). The form's "Save" button calls `apply()` directly with the form-validated content — no roundtrip through a text representation that could re-introduce schema errors. The same `Artifact` base method dispatches to the right surface based on the `surface=` argument.

**Subsumes today's CLI commands.** Today's `pm pr edit` / `pm plan edit` / `pm note edit` / `pm watcher edit` (when they exist as ad-hoc CLI handlers) all become one-line `PmCommand` subclasses delegating to `Artifact.edit_interactively`. The typed-form TUI variant is the natural next step; the CLI variant ships in the Artifact substrate PR (plan-sensorium's first refactor PR).

**Change notification.** On successful `apply`, emits `Emission(tag='artifact.<name>.changed', payload={'version': N, 'edit_id': ..., 'editor_stream_id': ...})` to the typed channel `mind.mailbox(ArtifactChangeChannel(self.name))`. Streams in the mind subscribe via `CallbackRegistry.on('artifact.<name>.changed', ...)`.

**Atomic write.** Writes go to `<path>.tmp.<editor_id>.<ts>` then rename onto `<path>`. Versioning via a sidecar `<path>.version` updated in the same transaction. `apply()` raises `VersionConflict` if `base_version != current_version`; caller re-reads and re-proposes.

**Schema validation.** `Edit` payloads are validated against `Artifact.schema` before write. A bad edit raises `SchemaError` and never lands.

**Typed registrations.** Each registered editable artifact is itself a typed subclass of `Artifact`, not a registry entry constructed from strings.

```python
class ProjectYamlArtifact(Artifact):
    path = Path('pm/project.yaml')
    schema = Project
    write_acl = {ImplStream, PlanAddStream, PlanReviewStream, SignoffStream, ...}    # Stream subclasses, not strings

class PlanArtifact(Artifact):
    def __init__(self, plan_id: str):
        self.path = Path(f'pm/plans/{plan_id}.md')
        self.plan_id = plan_id
    schema = Plan
    write_acl = {PlanAddStream, PlanReviewStream, PlanEditStream, HumanWriter}

class NotesSectionArtifact(Artifact):
    def __init__(self, scope: str):
        self.path = Path(f'pm/notes/{scope}.txt')
    schema = NotesSection
    write_acl = None    # open

class RegressionSpecArtifact(Artifact):
    def __init__(self, id: str):
        self.path = Path(f'pm/qa/regression/{id}.md')
    schema = RegressionSpec
    write_acl = {QaAuthorStream, QaRegressionStream, HumanWriter}
```

The typed subclass IS the registration. `write_acl` is a set of `Stream` subclass types, not role strings — adding a Stream subclass that should have edit permission means updating the typed set; orphan ACL entries (referencing deleted Stream subclasses) fail at import.

More typed subclasses (surfaced by the file-migration audit; land in the Artifact substrate PR):

```python
class SpecArtifact(Artifact):
    """Per-PR spec files at pm/specs/<pr-id>/<phase>.md — impl spec, qa spec, review spec.
    Dual workdir/local lookup precedence: prefer per-workdir copy, fall back to repo-level.
    Approval workflow: human approves spec before downstream streams consume it."""
    def __init__(self, pr_id: int, phase: Literal['impl', 'qa', 'review']):
        self.path = self._resolve_dual_lookup(pr_id, phase)
        self.pr_id, self.phase = pr_id, phase
    schema = Spec
    write_acl = {SpecGenStream, ImplStream, ReviewStream, QaPlanningStream, HumanWriter}

class QaLibraryArtifact(Artifact):
    """qa/{instructions,regression,artifacts,mocks}/*.md library files with YAML frontmatter.
    One typed sub-subclass per qa library kind."""
    kind: ClassVar[Literal['instructions', 'regression', 'artifacts', 'mocks']]

class QaInstructionsArtifact(QaLibraryArtifact):
    kind = 'instructions'
    def __init__(self, id: str): self.path = Path(f'pm/qa/instructions/{id}.md')
    schema = QaInstructions
    write_acl = {QaAuthorStream, HumanWriter}

class QaMocksArtifact(QaLibraryArtifact):
    kind = 'mocks'
    def __init__(self, id: str): self.path = Path(f'pm/qa/mocks/{id}.md')
    schema = QaMockSpec
    write_acl = {QaAuthorStream, QaPlanningStream, HumanWriter}

# similar for QaRegressionArtifact, QaArtifactsArtifact

class ReviewFileArtifact(Artifact):
    """Plan-review .txt files written/parsed/listed for NEEDS_FIX surfacing.
    Consumed by `pm plan fix --review`."""
    def __init__(self, plan_id: str, review_id: str):
        self.path = Path(f'pm/plans/reviews/{plan_id}-{review_id}.txt')
    schema = PlanReview
    write_acl = {PlanReviewStream, HumanWriter}
```

**Starter set (Artifact substrate PR):** `ProjectYamlArtifact`, `PlanArtifact`, `NotesSectionArtifact`, `RegressionSpecArtifact`, `SpecArtifact`, `QaInstructionsArtifact`, `QaMocksArtifact`, `QaRegressionArtifact`, `QaArtifactsArtifact`, `ReviewFileArtifact`.

**Deferred to plan-radar / plan-3119574 implementations:** `RadarItemArtifact` (subsumes plan-radar's earlier Artifact primitive), plan-3119574 walker UI artifacts (`ReviewStateArtifact`, `UiFocusArtifact`, `NotesArtifact`, per-cycle `ReviewCycleArtifact` / `CitationAuditCycleArtifact` / `ReviewResponseCycleArtifact`). Walker UI streams subscribe to these via `CallbackRegistry.on(ArtifactChangeChannel('review-cycle-2'), ...)`.

### 2. `ResourceLease` (concrete)

Mutual-exclusion (or bounded-concurrent) access to a named external resource. Replaces today's ad-hoc tmux-window-name collisions, sentinel files, and per-watcher distributed locks.

```python
class ResourceKey:
    """Base. Subclasses are typed leaseable-resource families. Renders to a string for storage."""
    def name(self) -> str: ...

@dataclass(frozen=True)
class TmuxWindowKey(ResourceKey):
    window_name: str
    def name(self) -> str: return f'tmux:window:{self.window_name}'

@dataclass(frozen=True)
class WorkdirKey(ResourceKey):
    path: Path
    def name(self) -> str: return f'workdir:{self.path}'

@dataclass(frozen=True)
class BranchRefKey(ResourceKey):
    ref: str
    def name(self) -> str: return f'branch:{self.ref}'

@dataclass(frozen=True)
class ContainerKey(ResourceKey):
    container_name: str
    def name(self) -> str: return f'container:{self.container_name}'

@dataclass(frozen=True)
class ChampionSlotKey(ResourceKey):
    target_id: str
    def name(self) -> str: return f'champion:{self.target_id}'

@dataclass(frozen=True)
class LeaderSlotKey(ResourceKey):
    role: str                                  # 'signoff-router', 'plan-walker', etc.
    def name(self) -> str: return f'leader:{self.role}'

# Added per locking-story consolidation — graduations of today's flock-based primitives.

@dataclass(frozen=True)
class PaneRoleKey(ResourceKey):
    session: str
    window: str
    role: str                                  # 'impl', 'review', 'qa-N', 'signoff', etc.
    def name(self) -> str: return f'pane:{self.session}/{self.window}/{self.role}'

@dataclass(frozen=True)
class PushProxySocketKey(ResourceKey):
    container_id: str                          # one proxy per container
    def name(self) -> str: return f'push-proxy:{self.container_id}'

@dataclass(frozen=True)
class MergeSlotKey(ResourceKey):
    pr_id: int
    def name(self) -> str: return f'merge:{self.pr_id}'

class ResourceLease:
    key: ResourceKey                           # typed, not a free string
    holder: str                                # stream_id of the current holder, or empty
    expires_at: Optional[datetime]
    max_holders: int = 1                       # bounded-concurrent if > 1

    def acquire(self, holder_stream_id: str, ttl: timedelta) -> bool          # False if held by another and not expired
    def release(self, holder_stream_id: str) -> None
    def renew(self, holder_stream_id: str, ttl: timedelta) -> None
    def status(self) -> LeaseStatus
```

**Typed `ResourceKey` hierarchy closes the leaseable-resource set.** Adding a new resource family means adding a `ResourceKey` subclass; using a non-existent family fails at type-check, not at first acquire. Catches today's ad-hoc resource-name typos.

Backed by rows in `pm/.mindlog.db` (the mind's SQLite store, shared infrastructure). Emits `Emission(tag='lease.<key>.acquired' | 'lease.<key>.released' | 'lease.<key>.expired', ...)` so streams react (e.g. plan-walker leader Apply-button enable, qa-finalize merge gate).

**Covers:** tmux window dedup, workdir mutex, branch-ref mutex, container-name mutex, champion-of-target slot, leader election for plan-walker.

### 3. `PathView` + `RepoCheckout` (Payload + service)

Host-vs-runtime path duality made first-class. Sensorium service on top of the mind's `RepoCheckout` Payload.

```python
@dataclass
class RepoCheckout(Payload):        # Payload lives in the mind; sensorium adds the resolution service
    host_path: str
    runtime_path: str                    # what the stream sees from inside its runtime (e.g. /workspace)
    branch: str
    sha: str

@dataclass
class FileArtifact(Payload):
    logical_name: str                    # 'qa-spec.md', 'failing-test-output.log'
    host_path: Optional[str]
    runtime_path: Optional[str]
    bytes_or_path: bytes | str
    lifetime: Literal['session', 'persistent'] = 'session'

class PathService:
    def for_runtime(self, host_path: str, runtime: RuntimePlugin) -> str
    def for_host(self, runtime_path: str, runtime: RuntimePlugin) -> str
    def materialize(self, file: FileArtifact, runtime: RuntimePlugin) -> str    # writes to runtime-visible scratch dir, returns runtime_path
```

`RuntimePlugin.path_map(host_path) -> runtime_path` is the per-runtime contract; `PathService` is the sensorium-side composer. `materialize()` is what `RuntimePlugin.send_input` uses internally when spooling large prompts to a host-visible file the runtime can `cat`.

### 4. `CaptureBundle` (Payload + service)

Non-textual artifacts deposited by streams as side effects: screenshots, log files, binary captures, video, etc. Today scattered across `~/.pm/sessions/<tag>/captures/`.

```python
@dataclass
class CaptureBundle(Payload):
    root: RepoCheckout                   # dual-path root
    test_id: str
    timestamp: datetime
    files: list[str]                     # relative to root

class CaptureService:
    def open(self, stream_id: str, test_id: str) -> CaptureBundle
    def append(self, bundle: CaptureBundle, filename: str, content: bytes) -> None
    def list(self, stream_id: str) -> list[CaptureBundle]
    def gc(self, older_than: timedelta) -> None
```

Emits `Emission(tag='capture.<test_id>.appended', payload={'bundle': CaptureBundle, 'file': str})` so QA-finalize / dashboards can react.

### 5. `HostCodeOverride` (Payload + service)

Typed binding of an alternate pm checkout into the running pm's `sys.path`. Today: meta-development writes `~/.pm/sessions/<tag>/override` + a shell hack.

```python
@dataclass
class HostCodeOverride(Payload):
    checkout: RepoCheckout
    scope: Literal['session', 'global']
    cleanup_on: Literal['terminate', 'manual']
    bound_for: str                       # stream_id that owns the binding

class HostOverrideService:
    def bind(self, override: HostCodeOverride) -> None
    def clear(self, stream_id: str) -> None
    def active(self) -> list[HostCodeOverride]
```

Cleanup on session terminate hooks into the mind's `Stream.on_cancel(handler)`. Eliminates the `; rm -rf` shell hack.

### 6. `RedactionPolicy` (service)

Write-time filter applied at every durable-record boundary: `StreamTranscript.append`, `EmissionLog.append`, `Artifact.apply`. Mind's primitives consult this service before persisting.

```python
class RedactionPolicy:
    rules: list[RedactionRule]           # regex, callable, or Payload.sensitive flag

    def filter_chunk(self, chunk: ChatChunk) -> ChatChunk
    def filter_payload(self, payload: dict, schema: type[Payload]) -> dict
    def add_rule(self, rule: RedactionRule) -> None
```

**Default rules (lands in the side-effects + redaction PR):** common secret patterns — `sk-...`, `ghp_...`, `Bearer ...`, environment-variable values in tokenized lists, AWS access keys, GCP service-account JSON. Per-Mind configurable. Type-aware via optional `sensitive: bool` field on `Payload` subclasses.

Redaction is at the **write seam, not the read seam**: redacted data never enters the durable record. Reading is unredacted because there's nothing to unredact. This avoids "redaction policy drift" bugs where the same byte stream is filtered differently depending on who's reading.

### 7. `PmCommand` typed hierarchy (Payload + service)

Typed pm CLI invocation. Today every role hand-rolls shell command construction (`subprocess.run(['pm', 'pr', 'start', ...])`). Replaced with a typed `PmCommand` hierarchy — one subclass per pm subcommand, each declaring its input dataclass and expected output emission.

```python
class PmCommand(Payload):
    """Base. Subclasses are concrete pm subcommands."""
    inputs: ClassVar[type]                       # required: input dataclass
    output_emission: ClassVar[Optional[type[Payload]]] = None    # what the command produces
    cwd: RepoCheckout

    def to_argv(self) -> list[str]: ...          # subclass-specific argv construction

@dataclass
class PrStartCommand(PmCommand):
    @dataclass
    class Inputs:
        pr_id: int
        force: bool = False
    inputs_value: Inputs
    output_emission = PRLifecycleStarted
    def to_argv(self): return ['pm', 'pr', 'start', str(self.inputs_value.pr_id)] + (['--force'] if self.inputs_value.force else [])

@dataclass
class PlanAddCommand(PmCommand):
    @dataclass
    class Inputs:
        slug: str
        from_file: Optional[Path] = None
    inputs_value: Inputs
    output_emission = PlanAdded
    def to_argv(self): ...

# ... one class per pm subcommand
```

```python
class PmCommandService:
    def invoke(self, command: PmCommand, runtime: RuntimePlugin) -> Emission
    def known(self) -> set[type[PmCommand]]      # introspection over registered subclasses
```

**Auto-generation path.** `PmCommand` subclasses are generated from pm's existing argparse/Click definitions by a script that runs in CI. Drift between the typed surface and the actual CLI fails CI rather than at runtime. Hand-rolled `PmCommand` subclasses for commands argparse can't introspect cleanly (a small minority).

The typed hierarchy is the structural contract between pm-the-tool and the mind's streams. A stream invoking `pm pr start` does it through `PrStartCommand(inputs_value=...)`, which the service materializes into the right shell invocation in the runtime. Output is parsed back into the typed `output_emission`. Adding a new pm subcommand without adding a `PmCommand` subclass means streams cannot invoke it — structural enforcement that pm's typed and CLI surfaces stay in lock-step.

This is how the mind interacts with pm's own surface: as a sensory channel with a typed contract, not as bare shell.

### 8. `WorkdirRegistry` + `Workdir` (concrete)

Per-PR git workdir provisioning, locking, checkout, and cross-workdir coordination (stash/unstash around merges). Today scattered across `cli/helpers.py`, `cli/pr.py`, `qa_loop.py` (`_ensure_workdir`, `_clone_workdir`, scenario clone setup, cross-workdir overlap stash).

```python
@dataclass
class Workdir(Payload):
    pr_id: int
    purpose: Literal['impl', 'scenario', 'review', 'merge-resolve']
    host_path: Path
    runtime_path: Path                          # what the runtime sees if mounted into a container
    branch: str
    sha: str                                    # current HEAD as of last sync
    lease: ResourceLease                        # WorkdirKey lease owned by the streams using this workdir

class WorkdirRegistry:
    def ensure(self, pr_id: int, purpose: str, branch: str,
               clone_from: Optional[Path] = None) -> Workdir
    def by_pr(self, pr_id: int) -> list[Workdir]
    def stash_overlaps(self, around_workdir: Workdir) -> StashHandle
    def unstash(self, handle: StashHandle) -> None
    def reap(self, workdir: Workdir) -> None       # called via Stream.on_cancel
```

**Cross-workdir overlap stash** captures the today's-painful case: a merge in workdir A touches files also being edited in workdir B; the merge needs B's local changes stashed temporarily, then unstashed when the merge completes (or fails). `WorkdirRegistry` owns this coordination so no individual stream has to reason about it.

**Resource leasing** integrates with `ResourceLease`: every `Workdir` holds a `WorkdirKey` lease owned by the stream that ensured it. Cleanup hooks into the stream's `on_cancel` handler.

**Container-mounted workdirs**: When `TmuxContainerRuntime` mounts a workdir into the container, `Workdir.runtime_path` records the in-container view. `PathService` resolves host/runtime queries; `TmuxContainerRuntime.path_map(host)` returns the runtime view.

Emits `Emission(tag='workdir.<pr_id>.<purpose>.ready' | '.stashed' | '.unstashed' | '.reaped', ...)`.

## Implementation PR sequence

Three PRs landing the sensorium substrate in dependency order, interleaved with plan-mind's PR sequence. Each PR specifies Purpose, Scope, Public API, Invariants, Dependencies, Test plan, Migration plan, Open questions. Internal design is self-documenting from the code; details that don't fit a section live in [refactor-new-files.md](refactor-new-files.md) (per-file inventory) and [refactor-migration-map.md](refactor-migration-map.md) (per-source-file disposition).

### PR: Artifact substrate

**Purpose.** Land the typed on-disk shared mutable Artifact substrate — Artifact base with watched-editor / schema-aware editor / external-write detection / atomic apply with debounce / link resolution, plus every typed Artifact subclass for pm-managed files.

**Scope.**
- In: `sensorium/artifact/base.py` (Artifact base with `apply(edit, base_version, debounce=)`, `open_in_editor`, `watch_for_save`, `edit_interactively(surface='cli'|'tui')`, `resolve_link`, `_on_external_change`); `sensorium/artifact/_frontmatter.py` (shared YAML helper); concrete subclasses `ProjectYamlArtifact`, `PlanArtifact`, `NotesSectionArtifact`, `RegressionSpecArtifact`, `SpecArtifact`, `ReviewFileArtifact`; QA library subtree `sensorium/artifact/qa_library/{instructions, mocks, regression, artifacts, status}.py`; placeholder registrations for radar and walker-UI artifacts (deferred to plan-radar / plan-3119574 implementations).
- In: `sensorium/artifact/_plan_markdown.py` — `PlanMarkdownSchema` owning the single source for plan-file structure: `PR_FIELDS = ("description", "tests", "files", "depends_on")`, section markers (`PRS_SECTION = "PRs"`, `PR_BLOCK_PREFIX = "### PR:"`, `PLANS_SECTION = "Plans"`, `PLAN_BLOCK_PREFIX = "### Plan:"`), `format_pr(pr_dict) -> str` renderer, `format_spec_for_prompt() -> str` prompt-fragment renderer, and `parse_plan_prs(text)` parser. Consumed by `PlanArtifact`, `cli/plan.py:120-124/221-225/845-850`, `cluster/output.py:16/26-30`, the `streams/plan/{add,breakdown,import_}.py` InputTypes (plan-mind), and the watcher augmentation prompts (`prompts/watcher/*`). Eliminates the four parallel hardcodings the audit identified (G6/G7/G8). Includes a CI test asserting every plan-prompt builder that needs the field list imports `PR_FIELDS` rather than re-listing it.
- Out: ResourceLease, PathService, captures, host overrides, redaction, workdirs, PmCommand (later PRs).

**Public API.** `Artifact` base class with the methods above. Each typed subclass binds `path: Path`, `schema: type[Payload]`, `write_acl: Optional[set[type[Stream]]]`. Artifact properties: optimistic-lock version, change-notify Emission, atomic write via tempfile+rename, schema validation on apply. `Artifact.resolve_link(ref) -> Optional['Artifact']` for `[[...]]` cross-artifact references.

**Invariants.**
- Atomic write: no torn writes are observable. Either the new version commits with bumped sidecar `.version` file, or the file is unchanged.
- Optimistic lock: `apply(edit, base_version)` with `base_version != current_version` raises `VersionConflict`.
- ACL gate: write_acl checked at `apply` time; non-typed external writes are observed but not gated (detected via `_on_external_change`).
- Two distinct change tags: `artifact.<name>.changed` (typed apply with editor_stream_id) and `artifact.<name>.externally-changed` (no editor identity).
- Schema-invalid external writes raise `AttentionRequest`, do NOT bump version.

**Dependencies.** `pm_core/mind/` (Emission, Channel for ArtifactChangeChannel, AttentionService, VisibilityTier). `pm_core/payloads/` (Payload Protocol for schema type).

**Test plan.** Round-trip apply: write via apply, read returns same content. VersionConflict raised on stale base_version. External write detection: external `vim` save fires `artifact.<name>.externally-changed`. Schema-invalid external write raises AttentionRequest, version unchanged. `edit_interactively` validate-on-save flow: schema error reopens editor with errors visible. `resolve_link('[[pr-42]]')` returns the right Artifact. `_frontmatter.py` parses and validates YAML headers consistently.

**Migration plan.** Sources retired: `pm_core/editor.py` (→ Artifact.open_in_editor + watch_for_save on base); `pm_core/qa_instructions.py` (→ qa_library/* artifacts); `pm_core/plans/review.py` (→ ReviewFileArtifact); `pm_core/store.py` WriteQueue + locked_update sections (→ Artifact.apply debounce path; `store.py` load/parse stays). `pm_core/spec_gen.py` write surface (→ SpecArtifact). `pm_core/qa_status.py` parse parts (→ QaStatusArtifact in qa_library/status). Frontmatter parsing scattered across qa_instructions, plans/parser, review/md_parser consolidates to `_frontmatter.py`. Plan-markdown structural knowledge in `pm_core/plans/parser.py:74-93` (PR_FIELDS, `## PRs` heading, `### PR:` block prefix), `pm_core/cli/plan.py:117/120-124/219-225/845-850`, `pm_core/cluster/output.py:16/26-30`, and `pm_core/prompt_gen.py:1045-1048` consolidates to `PlanMarkdownSchema` in `sensorium/artifact/_plan_markdown.py`; the original sites delete their inline literals and call the schema.

**Open questions.**
- Debounce semantics for `Artifact.apply(debounce=)` — coalesce-by-keys vs strict last-write-wins per window. Lean: last-write-wins (TUI per-keypress is the motivating case).
- Whether sensorium uses its own SQLite for version metadata or sidecar `.version` files. Lean: sidecar files (simpler; one Artifact = one path + one sidecar).

### PR: Resource coordination — leases, workdirs, paths

**Purpose.** Land typed `ResourceLease` over named shared resources (tmux windows, branches, containers, workdirs, champion/leader slots) plus typed `WorkdirRegistry` that owns per-PR / per-scenario workdir provisioning + cross-workdir stash coordination + the host/runtime path-duality service.

**Scope.**
- In: `sensorium/leases.py` (ResourceLease + ResourceKey hierarchy: TmuxWindowKey, WorkdirKey, BranchRefKey, ContainerKey, ChampionSlotKey, LeaderSlotKey, **PaneRoleKey** (per-pane mutex; absorbs today's `pane_registry.py`), **PushProxySocketKey** (one proxy per container; absorbs today's `push_proxy.py` mutex), **MergeSlotKey** (per-PR merge mutex; absorbs today's `trigger_tui_merge_lock` marker); `acquire/release/renew/status` + classmethod `reconcile(key_prefix, holder_filter)`); `sensorium/workdirs.py` (WorkdirRegistry + Workdir + ScenarioWorkdir + stash_overlaps/unstash + reap); `sensorium/paths.py` (PathService for_runtime/for_host/materialize + FileArtifact).
- Out: Captures, host overrides, redaction, PmCommand (next PR).

**Public API.** `ResourceLease` with the methods above. Typed `ResourceKey` subclasses rendering to disambiguated keys. `WorkdirRegistry.ensure(pr_id, purpose, branch, clone_from)`, `by_pr(pr_id)`, `stash_overlaps(around_workdir)`, `unstash(handle)`, `reap(workdir)`. `ScenarioWorkdir(Workdir)` carrying clone-override file metadata. `PathService.materialize(file, runtime)` powering large-prompt spool.

**Invariants.**
- `ResourceLease.acquire` returns False if held by a non-expired non-self holder; True if acquired.
- `ResourceLease.reconcile()` releases leases whose holder Stream is no longer in `running` lifecycle.
- Workdir provisioning is idempotent for the same `(pr_id, purpose, branch)`.
- Cross-workdir stash is reversible: `stash_overlaps` returns a handle whose `unstash` restores the original state.

**Dependencies.** Prior PR (Artifact substrate). `pm_core/mind/` (Emission for lease state, EmissionLog for lease storage via SQLite, LifecycleState for reconcile holder-filter). `pm_core/runtime/` (RuntimePlugin for `path_map` in PathService).

**Test plan.** Lease contention: two acquires on the same key with different holders — second returns False until release. Lease reconcile: planted stale lease + holder Stream in terminated state → reconcile releases. WorkdirRegistry.ensure idempotency. stash_overlaps + unstash round-trip preserves the workdir. PathService host/runtime path mapping with mounted containers.

**Migration plan.** Sources retired: today's fcntl locks for cross-stream-coordinated resources — `signoff.py` per-PR launch lock (→ TmuxWindowKey lease); workdir provisioning fcntl at `cli/helpers.py:565, 717-744, 748` (→ WorkdirKey lease); `qa_loop.py` tmux-window collision dedup (→ TmuxWindowKey). **`store.py`'s project.yaml fcntl explicitly STAYS** — its append/replace semantics need plain flock; ProjectYamlArtifact wraps the call site without promoting the lock to ResourceLease. Other flock sites route elsewhere by design: `runtime_state.py` → EmissionLog (mind/log.py); `review/md_writer.py` → Artifact atomic write; `pane_registry.py` STAYS as TUI substrate; `tui/app.py` cmd-queue STAYS; `claude_launcher.py` session-id registry → runtime/tmux_host.py. `_ensure_workdir`, `_clone_workdir`, `create_scenario_workdir`, `_setup_clone_override` across cli/helpers, cli/pr, qa_loop (→ WorkdirRegistry + Workdir + ScenarioWorkdir). Cross-workdir overlap stash logic (→ WorkdirRegistry.stash_overlaps). `_cleanup_stale_scenario_windows` from qa_loop + the catch-all sweep from `pr_cleanup.py` (→ ResourceLease.reconcile). Path-handling helpers in `paths.py` (host/runtime path parts → PathService; the global-settings parts stay).

**Open questions.**
- Lease backend: SQLite rows in `pm/.mindlog.db` vs flat files. Lean: SQLite rows (transactional, queryable).
- ScenarioWorkdir clone-override file format: stays as today's shell-source file or migrates to typed config. Lean: stays as shell-source for compatibility; type system tracks the path, not the content.

### PR: Side-effects + redaction + PmCommand

**Purpose.** Land capture (non-textual side-effect deposits), host-code override (meta-dev's sys.path binding), write-time redaction at sensorium boundaries, and the typed `PmCommand` hierarchy for typed pm CLI invocations from streams.

**Scope.**
- In: `sensorium/captures.py` (CaptureBundle + CaptureService); `sensorium/host_overrides.py` (HostCodeOverride + HostOverrideService); `sensorium/redaction.py` (RedactionPolicy at StreamTranscript.append + EmissionLog.append + Artifact.apply write seams); `sensorium/commands/base.py` (PmCommand base) + `sensorium/commands/generated.py` (auto-generated from argparse) + `sensorium/commands/handrolled.py` + `sensorium/commands/service.py`.
- Out: Cross-mind sharing of these (that's plan-collaboration).

**Public API.** `CaptureBundle(Payload)` + `CaptureService.open/append/list/gc`. `HostCodeOverride(Payload)` + `HostOverrideService.bind/clear/active`. `RedactionPolicy.filter_chunk/filter_payload/add_rule` with default secret-pattern rules. `PmCommand(Payload)` base with `inputs: ClassVar[type]`, `output_emission: ClassVar[Optional[type[Payload]]]`, `to_argv() -> list[str]`. Auto-generated subclasses for each pm subcommand. `PmCommandService.invoke(command, runtime) -> Emission`.

**Invariants.**
- Redaction is at the write seam, never at read; once filtered, data does not appear unredacted.
- HostCodeOverride cleanup hooks fire on Stream `on_cancel`.
- Every pm-CLI invocation from a Stream goes through `PmCommand`; raw `subprocess.run(['pm', ...])` calls in stream code fail CI lint (a custom check).
- CI lock-step: `generated.py` is regenerated from argparse/Click definitions and asserted equal in CI.

**Dependencies.** `pm_core/mind/` (Emission, AttentionRequest); `pm_core/payloads/` (Payload Protocol for CaptureBundle / HostCodeOverride / PmCommand bases); `pm_core/runtime/` (RuntimePlugin for command.invoke); `pm_core/sensorium/artifact/` (prior sensorium PR for Artifact base); `pm_core/sensorium/paths.py` (prior sensorium PR for CaptureBundle path handling).

**Test plan.** RedactionPolicy: default rules redact `sk-...`, `ghp_...`, Bearer tokens, env-var-like patterns. Adding a rule applies to future writes only (historical data unchanged). CaptureService gc removes only old bundles. HostCodeOverride cleanup fires on Stream on_cancel. PmCommand auto-generation: argparse diff vs `generated.py` is empty in CI. Typed PmCommand invocation: argv construction matches expected pm CLI form.

**Migration plan.** Sources retired: today's `~/.pm/sessions/<tag>/captures/` glue (→ CaptureService); meta-dev's `~/.pm/sessions/<tag>/override` + shell rm hack (→ HostCodeOverride + HostOverrideService with typed cleanup); ad-hoc `subprocess.run(['pm', ...])` calls scattered across stream code (→ PmCommand subclasses). Secret-filtering shell hacks (→ RedactionPolicy default rules).

**Open questions.**
- PmCommand auto-generation handles ~90% of subcommands cleanly; the dynamic-dispatch subcommands (~10%) need hand-rolled subclasses. Process for keeping these in sync. Lean: CI assertion that every argparse subcommand is covered by either generated or handrolled.
- Whether `RedactionPolicy` defaults apply universally or are opt-in per Stream. Lean: opt-out via `StreamPolicy.skip_default_redaction: bool` field; defaults apply to every Stream that doesn't opt out.

## Disposition for items that move to this plan

- **Plan-radar's "Artifact primitive"** — provided by `Artifact` here. Plan-radar drops it from scope and depends on plan-sensorium.
- **Plan-radar's "navigation primitive"** — stays in plan-radar's scope as a radar-introduced concept. Plan-sensorium contributes only the small `Artifact.resolve_link(ref)` helper for the `[[...]]` link convention; the radar's information organization is its own family of Artifact subclasses (defined in plan-radar Track B).
- **G-EDITABLE-ARTIFACTS, G-LEASE, G-PATH-MAPPING, G-CAPTURE-BUNDLE, G-HOST-OVERRIDE, G-REDACTION** from the completeness audit fold in here as the primitives above.
- **Today's `pm_core/container.py`** stays in the mind plan (it wraps a runtime), but the resource-naming/dedup parts of it (container names, workdirs) become `ResourceLease`-managed.

## Invariants the sensorium enforces

1. Every mutation of a sensorium primitive emits a Emission onto a well-known mailbox in the mind. The mind does not poll the sensorium.
2. Schema-bound writes are atomic, version-checked, ACL-gated. Schema errors and version conflicts surface as explicit exceptions, never as silent data loss.
3. Redaction happens at write, not read. Once filtered, data never appears unredacted.
4. The sensorium owns no stream lifecycle. Cleanup tied to a stream (host overrides, leases, capture bundle gc) hooks into the mind's `on_cancel` callbacks.
5. Host/runtime path duality is type-mediated. No role hand-constructs `runtime_path` from `host_path`.
6. pm CLI invocations from streams flow through typed `PmCommand` subclasses, not raw subprocess. The CI-enforced auto-generation from argparse/Click is the contract.

## Additions from v2 file-migration audit

### `ScenarioWorkdir` — typed `Workdir` subclass

Per-scenario isolated clone with override file (today: `create_scenario_workdir` + `_setup_clone_override` in qa_loop.py). Subclass of `Workdir`:

```python
@dataclass
class ScenarioWorkdir(Workdir):
    parent_pr_id: int
    scenario_idx: int
    override_file_path: Path                    # the clone-override file pm writes
    # purpose = 'scenario' inherited; pr_id inherited as parent_pr_id
```

Owned by `QaScenarioStream` via the typed Workdir flow; reaped on stream cancel.

### Shared YAML-frontmatter parser

`pm_core/sensorium/artifact/_frontmatter.py` — small helper used by `QaInstructionsArtifact`, `QaMocksArtifact`, `QaRegressionArtifact`, `PlanArtifact`, `SpecArtifact`, `RadarItemArtifact`, walker UI artifacts. Single source of YAML-frontmatter parse + validate. Imported by each Artifact subclass that needs it.

### `QaStatusArtifact` — typed signoff evidence

`pm_core/sensorium/artifact/qa_library/status.py` — typed read surface over QA status that `SignoffStream`'s evidence pane reads instead of shell-globbing `~/.pm/workdirs/qa/<pr>-*/qa_status.json`. Schema captures: per-scenario verdict, last-update timestamp, evidence-bundle refs, currently-blocking attentions.

### `Artifact.apply` debounce — absorbs `store.WriteQueue` / `store.locked_update`

```python
class Artifact:
    def apply(self, edit: Edit, base_version: int,
              debounce: Optional[timedelta] = None) -> int:
        """Apply with optional debounce. With debounce, calls within the window
        coalesce into one write at the trailing edge (last-write-wins per window).
        Used by TUI per-keypress mutations on ProjectYamlArtifact."""
```

`store.WriteQueue` and `store.locked_update` logic move into `Artifact.apply`. Today's high-frequency mutations (TUI per-keypress updates to `project.yaml`) opt in via `debounce=timedelta(milliseconds=200)`. Atomic-write + optimistic-lock semantics preserved; debounce is a delivery-rate filter, not a consistency relaxation.

`pm_core/store.py` mostly stays (load/parse logic); the `WriteQueue` / `locked_update` blocks delete in favor of the Artifact base.

### `STEP_ORDER` lives on `GuideSetupStream`

Today's `pm_core/guide.py` exports `STEP_ORDER` / `STEP_DESCRIPTIONS` / `SETUP_STATES` consumed by `tui/guide_progress.py`. These become `ClassVar` on `GuideSetupStream` (in `pm_core/streams/guide/setup.py`):

```python
class GuideSetupStream(Stream):
    STEP_ORDER: ClassVar[list[GuideStep]] = [...]
    STEP_DESCRIPTIONS: ClassVar[dict[GuideStep, str]] = {...}
```

`tui/guide_progress.py` imports from there. `guide.py` itself dissolves (the wrapping logic also moves into the Stream).

## Open questions

- Whether `Artifact` history is bounded (last N edits) or unbounded — depends on edit volume per artifact. Lean: bounded by default (50), configurable per artifact.
- Whether `ResourceLease` rows in the SQLite log expire via wallclock or via the mind's lifecycle observability stream (lease released when holder session terminates). Lean: both — wallclock TTL as a backstop, lifecycle-driven release as the normal path.
- `RedactionPolicy` rule precedence and update model — does a new rule retroactively apply? It cannot (data already written), so adding a rule covers future writes only. Document this clearly.
- `PmCommand` subclass set sourcing — generation from argparse/Click is the lean. Open: what happens for subcommands whose argument parsing is dynamic (subparser dispatch with reflection); those may need hand-rolled subclasses. Estimate: <10% of commands need this.

## Status counts

- pending: 0 (none filed yet; `pm plan load plan-sensorium` after approval)
- in_progress: 0
- merged: 0
