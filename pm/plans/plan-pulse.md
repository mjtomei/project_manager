# Pulse — Developer Productivity Agent

A standalone developer productivity and wellbeing optimization agent. Tracks code
health, developer state, and environmental signals to recommend the right task at
the right time, manage energy through breaks, and use psychology-informed messaging
to sustain flow and motivation. All inference is automatic — no manual check-ins.

Pulse is a general-purpose Python package with its own CLI, config, and plugin
interface. It has no dependency on any specific project management tool — consumers
integrate via the Tracker plugin interface, Task protocol, and callback-based
notification system.

## Vision

A developer who never has to think about when to take a break, what to work on next,
or whether they're pushing too hard. Pulse observes signals (git activity, time of day,
wearable data, presence) and provides gentle, psychology-backed nudges — the right task
at the right energy level, breaks before burnout, and variable reward messaging that
sustains motivation without being annoying.

## Scope

- **Metrics store**: generic time-series SQLite database for all signal data
- **Tracker plugin system**: ABC + lifecycle + registry for extensible data sources
- **Built-in trackers**: git activity patterns, code churn, Apple Health, webcam presence
- **Energy inference**: circadian + signals → 0–1 energy/focus score, no manual input
- **Task matching**: generic Task protocol, difficulty scoring, flow-state matching
- **Break scheduling**: work/break intervals with meal awareness
- **Motivation system**: variable reward messaging from a virtual PM persona
- **Reading list**: YAML-backed reading list with context-aware recommendations
- **Notification delivery**: core + desktop + callback backend (no TUI-specific code)
- **Configuration**: YAML config at `~/.pulse/config.yaml`, CLI at `pulse`

## Goals

1. Maximize sustained productive flow by matching task recommendations to developer state
2. Reduce burnout by proactively scheduling breaks, meals, and variety
3. Track code quality signals (churn, file stability) to surface problem areas
4. Use variable reinforcement and subtle cues to maintain motivation without being annoying
5. Surface relevant reading material at natural pause points
6. Keep all components loosely coupled — any tracker or helper can be added/removed independently
7. Remain domain-independent — no assumptions about the consumer's project management tool

## Key Design Decisions

### Metrics Store
SQLite database at `~/.pulse/metrics.db` for time-series data. Schema:
`(id, timestamp, source, metric, value REAL, metadata JSON)`. Chosen over flat files
for query flexibility (time ranges, aggregations). Each tracker writes to its own
source namespace. Retention policy: raw data for 90 days, daily aggregates indefinitely.

### Tracker Plugin Interface
Abstract base class `Tracker` with `start()`, `stop()`, `poll() -> list[Metric]`,
and `interval_seconds`. Registry discovers trackers from `pulse/trackers/` package.
Each tracker is independently configurable via `~/.pulse/config.yaml`. Trackers run
in background threads managed by the consumer's lifecycle, or can be polled by CLI.

### Energy Model (Inference-Only)
No manual input. Combines:
- Circadian/ultradian prior (time-of-day baseline, configurable chronotype)
- Git activity signals (commit frequency, session duration, gap detection)
- Wearable data when available (heart rate variability = best focus proxy)
- Presence data when available (time at desk, break detection)
Outputs a 0–1 energy score and recommended task depth (shallow/moderate/deep).

### Task Protocol
Generic `Task` protocol: `id`, `description`, `estimated_files`, `dep_depth`,
`historical_cycle_time`. Any consumer wraps their work items to implement this
protocol. The difficulty scorer and flow matcher operate on abstract Tasks, not
any specific PR or issue type.

### Variable Reward Schedule
Based on variable-ratio reinforcement (most effective for sustained engagement).
Not every achievement triggers a message — probability increases with streak length
and decreases with message frequency. Categories: celebration, encouragement,
surprise, curiosity. Tone adapts: fewer messages when deep in work, more during
transitions.

### Notification Delivery
Pluggable backend: desktop (notify-send / osascript), callback (consumer registers
a function), mobile (future stub). Each notification has priority (low/medium/high)
and the delivery backend filters by priority. The `CallbackBackend` lets any consumer
(TUI, web app, etc.) receive notifications without pulse knowing about the consumer's
UI framework.

### Reading List Architecture
Stored in `~/.pulse/reading.yaml`. Sources:
- arXiv API for papers matching configurable keywords
- HN Algolia API for top stories matching interests
- Curated book lists (seeded, user-extensible)
Recommendations triggered at natural pause points (break time, post-achievement, low energy).

## Constraints

- All data stays local — no cloud telemetry, no external analytics
- Camera/wearable features are strictly opt-in with clear privacy controls
- Notification frequency is capped (max N per hour, configurable)
- Trackers must be fault-tolerant — one failing tracker cannot crash others
- The system should be useful even with zero optional trackers (just git-based metrics)
- No dependencies on any specific project management tool or TUI framework

## Configuration

`~/.pulse/config.yaml` example:
```yaml
trackers:
  git_activity: {enabled: true}
  code_churn: {enabled: true}
  apple_health: {enabled: false, export_path: ~/health-export/}
  presence: {enabled: false, camera_index: 0}

energy_model:
  chronotype: intermediate  # early_bird | intermediate | night_owl
  work_hours: [9, 22]

breaks:
  work_minutes: 52
  break_minutes: 17
  meals: [{name: lunch, window: [12, 13]}, {name: dinner, window: [18, 19]}]
  snack_suggestions: true

notifications:
  desktop: true
  mobile: false
  max_per_hour: 8

virtual_pm:
  enabled: true
  personality: encouraging  # encouraging | matter_of_fact | playful
  reward_base_probability: 0.3

reading:
  interests: [distributed-systems, programming-languages, ml-theory]
  include_non_technical: true
  sources: [arxiv, hn, books]
```

## PRs

### PR: Metrics data model and SQLite store
- **description**: Create `pulse/store.py` with a SQLite-backed time-series store. Schema: (id INTEGER PRIMARY KEY, timestamp TEXT, source TEXT, metric TEXT, value REAL, metadata TEXT). API: `record(source, metric, value, metadata=None)`, `query(source=None, metric=None, from_ts=None, to_ts=None) -> list[Row]`, `aggregate(metric, period='day', fn='avg')`. DB location: `~/.pulse/metrics.db` (auto-created). Add retention cleanup: raw rows older than 90 days are pruned on startup, daily aggregates kept indefinitely. Create `pulse/__init__.py` with package metadata and public API exports.
- **tests**: store round-trip (record + query), time-range filtering, aggregation (daily avg/sum/max), retention pruning deletes old rows but keeps aggregates, concurrent writes don't corrupt, missing DB auto-creates
- **files**: pulse/__init__.py (create), pulse/store.py (create), tests/test_store.py (create)
- **depends_on**:

---

### PR: Tracker plugin interface and registry
- **description**: Create `pulse/tracker.py` with abstract base class `Tracker`: methods `start()`, `stop()`, `poll() -> list[Metric]`, property `interval_seconds`, property `source_name`. `Metric` is a dataclass: `(metric: str, value: float, metadata: dict | None, timestamp: datetime | None)`. Create `pulse/registry.py`: auto-discovers tracker classes from `pulse/trackers/` package via entry points or direct import scan. `TrackerRegistry` manages lifecycle: `start_all()`, `stop_all()`, `poll_all()`. Each tracker runs in its own daemon thread with error isolation (one crashing tracker logs error but doesn't affect others). Configuration loaded from `~/.pulse/config.yaml` — trackers not listed or `enabled: false` are skipped. Create `pulse/trackers/__init__.py`.
- **tests**: tracker ABC enforcement (must implement poll), registry discovers trackers from package, start/stop lifecycle, error isolation (one tracker raising doesn't stop others), config filtering (disabled trackers skipped), poll aggregation across multiple trackers
- **files**: pulse/tracker.py (create), pulse/registry.py (create), pulse/trackers/__init__.py (create), tests/test_tracker_registry.py (create)
- **depends_on**: Metrics data model and SQLite store

---

### PR: Git activity pattern tracker
- **description**: Create `pulse/trackers/git_activity.py` implementing `Tracker`. Analyzes git log timestamps to detect: active session windows (commits within 30-min gaps = same session), session start/end times, hour-of-day activity distribution, burst detection (3+ commits within 10 minutes = deep focus). Emits: `activity.session_start`, `activity.session_end`, `activity.session_duration_min`, `activity.hour_distribution.<hour>`, `activity.burst_detected`. This is the primary signal for the energy model's time-of-day component. Also tracks: time since last commit (staleness signal), average gap between commits within sessions. Poll interval: 2 minutes.
- **tests**: session detection from commit timestamps (gaps split sessions), burst detection, hour distribution histogram, handles single-commit sessions, handles timezone correctly, handles empty repo gracefully
- **files**: pulse/trackers/git_activity.py (create), tests/test_git_activity_tracker.py (create)
- **depends_on**: Tracker plugin interface and registry

---

### PR: Code churn tracker
- **description**: Create `pulse/trackers/code_churn.py` implementing `Tracker`. Polls git log to compute: lines added/removed per recent commit, file stability scores (inverse of change frequency over last 30 days). Emits metrics: `churn.lines_added`, `churn.lines_removed`, `churn.file_stability.<path>`. Poll interval: 5 minutes (checks for new commits since last poll). Metadata includes commit hash. This is a generic git-only tracker — no project management concepts, just raw code churn signals.
- **tests**: parse git log output for add/remove counts, file stability calculation over mock commit history, handles empty repo gracefully, handles merge commits correctly
- **files**: pulse/trackers/code_churn.py (create), tests/test_code_churn_tracker.py (create)
- **depends_on**: Tracker plugin interface and registry

---

### PR: Apple Health wearable connector
- **description**: Create `pulse/trackers/apple_health.py` implementing `Tracker`. Imports health data from Apple Health XML export (the standard export format from the Health app). Parses: heart rate (HKQuantityTypeIdentifierHeartRate), heart rate variability (HKQuantityTypeIdentifierHeartRateVariabilitySDNN), step count, active energy burned. Watches a configured export directory for new exports. Converts to standard Metric format: `health.heart_rate`, `health.hrv`, `health.steps`, `health.active_energy`. The HRV metric is the most valuable signal for the energy model — high HRV correlates with cognitive readiness. Handles large XML files efficiently (streaming parser, not DOM). Deduplicates entries by timestamp to handle re-imports. Poll interval: checks for new export files every 30 minutes.
- **tests**: parse sample Apple Health XML (minimal fixture), extract heart rate records, HRV extraction, deduplication on re-import, handles missing/empty export, streaming parser doesn't load entire file into memory
- **files**: pulse/trackers/apple_health.py (create), tests/test_apple_health_tracker.py (create), tests/fixtures/sample_health_export.xml (create — minimal fixture)
- **depends_on**: Tracker plugin interface and registry

---

### PR: Webcam presence tracker
- **description**: Create `pulse/trackers/presence.py` implementing `Tracker`. Uses OpenCV (cv2) for lightweight face detection to determine if the developer is at their desk. Privacy-first design: no images are stored or transmitted, only boolean presence and timestamps. Detection: captures a single frame at each poll, runs Haar cascade face detector, emits `presence.at_desk` (1.0 or 0.0) and `presence.session_duration_min` (continuous presence time). Optional posture signal: if face position is significantly lower than baseline, emit `presence.posture_warning`. Requires explicit opt-in (`enabled: true` in config) and shows a one-time consent notice on first activation. Camera index configurable for multi-camera setups. Graceful fallback: if cv2 not installed, tracker registers but reports unavailable. Poll interval: 60 seconds.
- **tests**: mock cv2 capture and face detection, presence toggle on face detected/not, session duration accumulation, posture detection (face position delta), graceful degradation without cv2, consent gate (first run requires acknowledgment), config-driven camera index
- **files**: pulse/trackers/presence.py (create), tests/test_presence_tracker.py (create)
- **depends_on**: Tracker plugin interface and registry

---

### PR: Notification delivery system
- **description**: Create `pulse/notifications.py` with pluggable notification backends. `Notification` dataclass: `(title, body, category, priority: low|medium|high, action: str|None)`. Backend interface: `NotificationBackend.send(notification)`. Implementations: (1) `DesktopNotificationBackend` — uses `notify-send` on Linux, `osascript` on macOS, (2) `CallbackBackend` — accepts a callable, invokes it with the notification object so any consumer (TUI, web app, etc.) can receive notifications without pulse knowing about the consumer's framework, (3) `MobileNotificationBackend` — stub that writes to `~/.pulse/mobile_queue.json` for future implementation. `NotificationManager` routes notifications to appropriate backends based on priority config. Rate limiting: configurable max-per-hour cap, minimum gap between notifications (default 2 min). Config in `~/.pulse/config.yaml` under `notifications:`.
- **tests**: notification routing by priority, rate limiting (cap per hour, min gap), desktop backend constructs correct command, callback backend invokes callable, manager respects disabled backends, stub mobile backend logs without error
- **files**: pulse/notifications.py (create), tests/test_notifications.py (create)
- **depends_on**:

---

### PR: Energy and focus inference model
- **description**: Create `pulse/energy_model.py`. Combines available signals to infer developer energy (0–1) and recommended task depth. Signal sources (gracefully degraded when unavailable): (1) **Circadian prior** — sinusoidal model with configurable chronotype (peaks at 10am and 3pm for intermediate, shifted ±2h for early_bird/night_owl), (2) **Git activity** — recent commit frequency and session duration from activity tracker (long active session with slowing commits → declining energy), (3) **Time since last break** — linear decay after configured work interval, (4) **Wearable HRV** — if available, HRV is the gold-standard focus proxy (high HRV = good recovery = high capacity), (5) **Presence** — if available, time-at-desk without breaks. Weights are learned over time via simple exponential moving average of "prediction vs. actual productivity" (measured by subsequent commit velocity). Output: `EnergyState(energy: float, focus: float, recommended_depth: str, confidence: float, signals: dict)`.
- **tests**: circadian model produces expected curve shape, chronotype shift works, git activity signal extraction, graceful degradation (missing signals don't crash), weight combination, energy decay over time without breaks, recommended depth mapping
- **files**: pulse/energy_model.py (create), tests/test_energy_model.py (create)
- **depends_on**: Metrics data model and SQLite store, Git activity pattern tracker

---

### PR: Task difficulty scorer
- **description**: Create `pulse/difficulty.py`. Scores tasks on a 0–1 difficulty scale using a generic `Task` protocol: `(id: str, description: str, estimated_files: int, dep_depth: int, historical_cycle_time: float | None)`. Scoring signals: (1) description length and complexity (word count, technical term density), (2) estimated file count, (3) dependency chain depth (deeper in graph = harder contextually), (4) historical cycle time if available. Output: `DifficultyScore(value: float, level: 'shallow'|'moderate'|'deep', signals: dict)`. Levels: shallow < 0.33, moderate 0.33–0.66, deep > 0.66. The Task protocol is a runtime-checkable `Protocol` class so any consumer can wrap their work items (PRs, issues, tickets) without inheriting from a base class.
- **tests**: scoring with minimal description, scoring with rich description, dependency depth contribution, historical data integration, level thresholds, Task protocol compliance check
- **files**: pulse/difficulty.py (create), tests/test_difficulty.py (create)
- **depends_on**: Metrics data model and SQLite store

---

### PR: Flow state task matcher
- **description**: Create `pulse/flow_matcher.py`. Recommends the best task to work on next by matching energy model output to task difficulty scores. Algorithm: (1) get candidate tasks (consumer provides a list of Task objects), (2) score each by difficulty, (3) get current energy state, (4) rank by |task_difficulty - energy_level| (closest match = best flow), with tiebreakers: prefer tasks with more dependents (unblocks more work), add variety bonus if last N tasks were all same difficulty. Output: ranked list of `Recommendation(task_id, score, reason: str)`. The matcher takes tasks and energy state as inputs — it does not know how to fetch them from any specific system.
- **tests**: basic matching (high energy → hard task), variety bonus application, handles empty task list, handles missing energy data (falls back to difficulty-only sort), unblock bonus for tasks with dependents, ranking stability
- **files**: pulse/flow_matcher.py (create), tests/test_flow_matcher.py (create)
- **depends_on**: Task difficulty scorer, Energy and focus inference model

---

### PR: Break and rest scheduler
- **description**: Create `pulse/breaks.py`. Manages work/break intervals with meal awareness. `BreakScheduler` tracks: work start time, accumulated work time, last break time, upcoming meal windows. Triggers break notifications via the notification system at configurable intervals (default: 52 min work / 17 min break, based on DeskTime research). Meal awareness: if a meal window is approaching within 20 minutes, suggests combining break with meal. Break types: micro (stretch, 2 min), standard (walk, 17 min), meal (eat, 30-45 min). Snack suggestions: configurable list of healthy snacks, randomly selected during standard breaks. Post-break: scheduler emits "welcome back" event that consumers can listen to for triggering task recommendations. Also tracks break compliance (did the user actually stop committing during break?) to calibrate future suggestions. State persisted in metrics DB so breaks survive restarts.
- **tests**: break trigger at correct interval, meal window detection, break type selection, snack randomization, compliance detection (commits during break), state persistence and restoration, configurable intervals
- **files**: pulse/breaks.py (create), tests/test_breaks.py (create)
- **depends_on**: Notification delivery system, Energy and focus inference model

---

### PR: Variable reward messaging engine
- **description**: Create `pulse/virtual_pm.py`. An automated persona that sends motivating messages using psychology-backed scheduling. Core mechanism: **variable-ratio reinforcement** — not every event triggers a message. Base probability starts at config value (default 0.3), modulated by: streak length (longer streak → higher probability of celebration), time since last message (longer gap → higher probability), current activity level (deep work detected → suppress messages). Message categories: (1) **celebration** — achievement completed, streak milestone, velocity record, (2) **encouragement** — long session, difficult task started, returning from break, (3) **surprise** — unprompted positive message, interesting stat, (4) **curiosity** — reading suggestion, "did you know" about the codebase. Each category has a pool of message templates with personality variants (encouraging/matter_of_fact/playful, configurable). Anti-annoyance: hard cap on messages per hour, exponential backoff if user doesn't interact after message, "quiet hours" config option.
- **tests**: variable ratio fires at approximately configured rate over many events, streak modulation increases probability, suppression during deep work, personality variant selection, rate limiting, quiet hours respected, message template rendering with context variables
- **files**: pulse/virtual_pm.py (create), tests/test_virtual_pm.py (create)
- **depends_on**: Notification delivery system, Energy and focus inference model

---

### PR: Reading list manager
- **description**: Create `pulse/reading.py`. Manages a personal reading list stored in `~/.pulse/reading.yaml`. Data model: `ReadingItem(id, title, url, source, category: 'project'|'broadening'|'leisure', status: 'queued'|'reading'|'completed'|'archived', added_at, notes, tags)`. API: `add_item(url, title=None, category=None)`, `list_items(status=None, category=None)`, `mark_done(id)`, `archive(id)`, `suggest() -> ReadingItem | None`. YAML storage keeps it simple and diffable. Items can also be added programmatically by the recommender. Duplicate URL detection prevents re-adding the same resource.
- **tests**: add/list/done/archive lifecycle, category filtering, status transitions, YAML round-trip, handles empty reading list, duplicate URL detection
- **files**: pulse/reading.py (create), tests/test_reading.py (create)
- **depends_on**:

---

### PR: Context-aware reading recommender
- **description**: Create `pulse/reading_recommender.py`. Generates reading suggestions based on configurable interests and developer state. Sources: (1) **arXiv** — search arXiv API for papers matching configured keywords, (2) **Hacker News** — query HN Algolia API for top stories matching interests, (3) **Books** — maintain a curated seed list of seminal works in CS, design, psychology, and productivity; expand based on configured interests. Recommendation timing: triggered during breaks (via break scheduler), post-achievement, or low-energy periods (light reading). Recommendation algorithm: score by relevance (keyword overlap), recency (prefer newer for HN, classic for books), and novelty (don't re-recommend). Integrates with notification system for delivery and reading list for storage.
- **tests**: keyword extraction from config, arXiv API query construction (mock HTTP), HN API query construction (mock HTTP), book matching against interests, recommendation scoring and ranking, no re-recommendation of completed items, timing integration with break events
- **files**: pulse/reading_recommender.py (create), tests/test_reading_recommender.py (create)
- **depends_on**: Reading list manager, Notification delivery system, Energy and focus inference model

---

### PR: Configuration and CLI
- **description**: Create `pulse/config.py` for configuration loading and validation, and `pulse/cli.py` for the standalone CLI. Config: `load_config(path=None) -> Config` loads from `~/.pulse/config.yaml` with defaults for missing keys. `init_config()` creates the file with sensible defaults. `Config` dataclass with typed access to all sections. CLI commands (via Click): `pulse init` — create config with defaults, `pulse energy` — show current inferred energy level, `pulse trackers` — list registered trackers and status, `pulse query [--source X] [--metric X] [--from DATE] [--to DATE]` — ad-hoc metric inspection, `pulse reading add/list/done/archive/suggest` — reading list management, `pulse break` — show time until next break. Entry point: `pulse` console script in pyproject.toml. This PR wires all the components together — on startup, CLI reads config, initializes store, discovers trackers, and makes energy/break/reading available.
- **tests**: init creates valid YAML with all expected keys, config loading with defaults, config loading with overrides, CLI commands produce expected output (mock store), handles missing config file (uses defaults), handles corrupt config file (resets with warning)
- **files**: pulse/config.py (create), pulse/cli.py (create), tests/test_config.py (create), tests/test_cli.py (create)
- **depends_on**: Tracker plugin interface and registry, Notification delivery system, Energy and focus inference model, Break and rest scheduler, Variable reward messaging engine, Reading list manager
