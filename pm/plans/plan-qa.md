# Fully Specified Project from project.yaml

Goal: a project fully specified by project.yaml where auto-starting the final PR
yields a high probability of producing fully user-ready software with all planned
features. Once an initial iteration is working, enable automated proposals and
testing of methods for improving performance and efficiency — including generating
equivalent or higher quality code with fewer tokens, and producing code that is
more robust to adversarial agents. This also serves as a foundation for creating
new LLM benchmarks that match real-world usage far better than existing ones —
fully specified projects with QA pipelines produce measurable, reproducible
end-to-end outcomes (feature completeness, test pass rates, token efficiency,
robustness) on realistic software engineering tasks rather than isolated coding
puzzles.

## Phase 1: Core QA Pipeline

### PR: Add optional quality assurance step with test instruction library and review-QA loop
- **description**: Add an optional QA / manual testing step between review and merge. Creates a review-QA loop: QA changes re-trigger review, review changes re-trigger QA, loop terminates when QA passes with no changes for N iterations (default 1). Includes a test instruction library (pm/instructions/) with titles and short descriptions, a TUI pane for browsing/editing instructions, QA session recording as PR notes, automatic QA work directory creation, a flow for QA on existing features via dummy PRs or standalone mode, and updates to the INPUT_REQUIRED flow since QA replaces most manual testing needs from review.
- **depends_on**:

---

### PR: Add pm pr qa CLI command for full QA loop
- **description**: CLI command (pm pr qa <pr_id>) that starts the full QA loop for a PR. Works from TUI command bar or CLI. Follows the same pattern as pm pr start, pm pr review, pm pr merge.
- **depends_on**:

---

### PR: Persist generated QA tests across iterations of the QA loop
- **description**: QA test plans and results persist across loop iterations for incremental testing, test history tracking, and stability detection. Storage alongside QA work directory or as structured PR QA notes.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

### PR: Support user stories at PR creation and edit time for QA test generation
- **description**: Attach user stories to PRs at creation (--story) or via edit screen. Stories guide QA test generation toward acceptance-style end-to-end tests from the user perspective. Stored as a PR field in project.yaml, passed to QA agent during test planning.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

### PR: Add pause-after-QA-plan mode with global setting, prefix key, and per-PR field
- **description**: Pause QA execution after test generation for user review/approval. Three activation methods: global setting (qa_pause_after_plan in project.yaml), prefix key for single QA run, per-PR field (qa_pause). Priority: per-PR overrides global, prefix key overrides both.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

### PR: QA start responsiveness with progress feedback
- **description**: TUI popup/overlay showing real-time progress during QA session preparation. Shows each step as it runs (loading state, generating prompts, creating workdir, launching windows, starting sessions). Auto-dismisses when QA window is ready, shows errors inline.
- **depends_on**:

---

### PR: Resume QA scenario polling after INPUT_REQUIRED with follow-up verdict loop
- **description**: When a QA scenario emits INPUT_REQUIRED, keep polling for a follow-up verdict instead of finalizing. Mirrors the review loop's poll_for_follow_up_verdict pattern. Moves scenario to a waiting_for_input set while continuing to poll other scenarios concurrently.
- **depends_on**:

---

## Phase 1b: Container Infrastructure

### PR: Isolate QA scenario workers in containers
- **description**: Run QA scenario workers inside containers instead of directly on the host. Provides isolation so workers can safely install packages, modify system state, and exercise destructive test scenarios. Container lifecycle managed by pm. Support configurable base images and resource limits.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

### PR: Add interactive Scenario 0 and fix QA scenario window bugs
- **description**: Add a persistent interactive Claude session (Scenario 0) in the container workdir that launches alongside the QA planner for manual testing. Fix bugs: scenario windows closing on verdict, broken window switching from scenarios pane.
- **depends_on**: Isolate QA scenario workers in containers

---

### PR: Enable git push from inside containers scoped to PR branch
- **description**: Inject git credentials at container creation time so container sessions can push to their PR branch. Scoped to the single PR branch. Works across GitHub, bare git, and local backends with both HTTPS and SSH.
- **depends_on**: Isolate QA scenario workers in containers

---

### PR: Add pm container command to build project-specific Docker images
- **description**: pm container subcommand that launches a Claude session to analyze project dependencies and generate a Dockerfile with all project deps preinstalled on the base image. Supports iterative builds.
- **depends_on**:

---

### PR: Embed session tag in container names and consolidate push proxies
- **description**: Embed TUI session tag in container names (pm-{session_tag}-{label}-{suffix}) for session-scoped container management. Consolidate to one push proxy per (session, branch) pair instead of per container.
- **depends_on**:

---

### PR: Session cleanup for stale containers and push proxies
- **description**: Cleanup function for containers and proxies whose tmux window no longer exists. Runs on TUI startup, session close (via tmux hook), and via pm session cleanup CLI.
- **depends_on**: Embed session tag in container names and consolidate push proxies

---

### PR: Container memory governor: dynamic memory limits with per-type stop policy and QA queuing
- **description**: Memory governor that projects consumption before launching containers. Configurable target max memory, per-type stop-on-idle policy (docker stop preserving overlay), memory projection from rolling averages, launch gating with QA scenario queuing when memory is tight. TUI status bar integration.
- **depends_on**:

---

## Phase 1c: QA Reliability and Lifecycle

### PR: Add QA scenario verification step before final verdict
- **description**: Verification step after all scenarios complete: checks for silently failed/timed out scenarios, validates verdicts match actual output, ensures no scenarios were skipped. Retries failed scenarios before producing the overall verdict. Prevents false PASS from crashed or empty scenarios.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

### PR: QA verdict collection survives TUI restart
- **description**: Move verdict polling from TUI daemon threads into the qa_status.py process that runs in the QA status pane. Status pane polls scenario tmux panes and writes to qa_status.json. TUI reads qa_status.json for lifecycle transitions. Verdict collection tied to status pane lifetime, not TUI lifetime.
- **depends_on**:

---

### PR: Check NEEDS_WORK verdicts for unpushed changes and redirect to INPUT_REQUIRED
- **description**: When a QA scenario returns NEEDS_WORK, verify the session actually pushed commits. If HEAD is unchanged, send a follow-up asking it to switch to INPUT_REQUIRED. Prevents false NEEDS_WORK from sessions that found issues but couldn't fix them.
- **depends_on**: Add QA scenario verification step before final verdict

---

### PR: Batched QA scenario execution
- **description**: Batch scenarios into configurable worker sessions instead of one session per scenario. Workers grouped by shared context. Each worker runs assigned scenarios sequentially with per-scenario reports and approval flow. Reduces session count, eliminates redundant diff review, lowers token usage.
- **depends_on**:

---

### PR: Auto-extract QA-relevant notes from implementation and review session transcripts
- **description**: Background Claude session (--print mode) that mines impl and review transcripts for QA-relevant information — changes, decisions, workarounds, edge cases, known limitations. Adds findings as structured QA-verify notes on the PR. Runs after impl/review sessions exit or on demand.
- **depends_on**:

---

### PR: FakeClaudeSession: scriptable Claude replacement for integration testing
- **description**: Fake Claude executable that emits specified verdicts with configurable preamble, delay, and streaming. Supports single-line and block-style verdicts. Installed as bin/fake-claude for overriding claude binary in tests. Covers verdict detection, review loop iterations, QA loop completion without real API calls.
- **depends_on**:

---

## Phase 1d: Spec Generation

### PR: Add spec generation step between PR phases
- **description**: Optional spec step that bridges natural-language PR descriptions and each phase. Produces per-phase specs (spec_impl, spec_review, spec_qa) grounded in actual code. Surfaces implicit requirements. Three modes: auto (no pause), review (always pause), prompt (pause on ambiguity or user request). Each phase's spec builds on previous phases.
- **depends_on**:

---

### PR: Implement review phase spec (spec_review) with mock planning
- **description**: Implement spec_review: what to verify, implicit requirements, edge cases, and a mocks section defining mock strategy for each external dependency. Injected into review prompt. Mocks section also surfaced in QA. QA scenarios should test progressively: unit -> FakeClaudeSession integration -> real integration.
- **depends_on**: Add spec generation step between PR phases

---

## Phase 2: Review Quality

### PR: Pattern-extraction review pipeline: parallel similar-code analysis with hazard aggregation before verdict
- **description**: Multi-stage parallel pipeline: (1) decompose diff into tasks, (2) find similar code per task, (3) extract invariants and tricky bits from each location, (4) aggregate and diff against new code to produce HAZARD signals. Catches deviations from established patterns the reviewer would miss without deep cross-codebase knowledge.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

### PR: Pattern-extraction pipeline: similarity and difficulty scoring for model routing
- **description**: Extend pattern-extraction with per-location similarity and complexity scores. Scores route extraction sessions to appropriate model tiers (strongest for high-similarity + non-trivial, lighter otherwise). Aggregation session weights hazard confidence by source score. Conservative scoring — defaults toward stronger models.
- **depends_on**: Pattern-extraction review pipeline: parallel similar-code analysis with hazard aggregation before verdict

---

### PR: Adversarial review with voting step to balance false positives
- **description**: Two-phase review: (1) adversarial pass assuming bugs exist, (2) voting/validation pass filtering false positives. Each issue must have concrete explanation, failure scenario, and proposed fix to survive. Configurable intensity, voter count, consensus threshold.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop, Review benchmark runner with multi-judge scoring

---

## Phase 3: Review/QA Benchmarking

### PR: Review and QA regression benchmark suite with real-world bug test cases
- **description**: Benchmark suite for testing review/QA changes against known bugs. Sources: our post-merge bugs, OSS AI project bugs, OSS non-AI project bugs. Runner presents buggy code to review/QA, scores detection. Tracks precision and recall. Supports A/B testing of prompts, models, and configs.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop

---

### PR: Review benchmark corpus format and internal test cases
- **description**: TestCase dataclass, load_corpus() loader with filtering, corpus version hashing, ~16 internal YAML test cases from our fix commits. pm bench review list CLI. Unit tests.
- **depends_on**: Review and QA regression benchmark suite with real-world bug test cases

---

### PR: Review benchmark runner with multi-judge scoring
- **description**: ReviewBenchRunner with parameterized config, Claude CLI invocation in --print mode, multi-judge scoring panel (Prometheus rubric, 1-5 scale, majority vote, agreement tracking). CaseResult with metrics. pm bench review run/report CLI. Result persistence in ~/.pm/bench/review/.
- **depends_on**: Review benchmark corpus format and internal test cases

---

### PR: Agent-driven corpus miner for OSS repos
- **description**: Three-stage agent pipeline: discovery (find fix commits), tracing (blame back to introducing commit), classification (generate metadata). Candidates staged for human review.
- **depends_on**: Review benchmark corpus format and internal test cases

---

### PR: ELO ranking and IRT difficulty calibration for review benchmark
- **description**: Bradley-Terry ELO ranking across runs with IRT-based difficulty calibration (2PL model). Enables adaptive evaluation with fewer cases. pm bench review compare/leaderboard CLI.
- **depends_on**: Review benchmark runner with multi-judge scoring

---

### PR: Open source bug corpus for review/QA benchmarking
- **description**: Run corpus miner against OSS repos: ml-framework, ml-inference, database, language-runtime, web-framework, hardware-rtl. 3-5 cases per type, targeting 50-100 total.
- **depends_on**: Agent-driven corpus miner for OSS repos

---

### PR: Auto-extract QA and review regression test cases from git history
- **description**: Run corpus miner against our own repo targeting 50+ known fix commits. All internal bugs with clear introducing commits become benchmark cases.
- **depends_on**: Agent-driven corpus miner for OSS repos

---

### PR: Review/QA model comparison: benchmark results and analysis for local vs frontier models
- **description**: Run benchmark suite across Opus, Sonnet, and gpt-oss-120b. Measure detection rate, false positive rate, iteration count, cost, wall clock time. Per-category breakdown, failure mode analysis, cost-adjusted quality score. Publish results and recommended model configs per session type.
- **depends_on**: Open source bug corpus for review/QA benchmarking, Auto-extract QA and review regression test cases from git history, Per-PR model override: associate a model with a PR so all sessions use it, ELO ranking and IRT difficulty calibration for review benchmark

---

## Phase 4: Local Model Integration

### PR: Harden local LLM integration: model selection, real QA testing, init setup, and provider verification
- **description**: Make local models always visible in /models. QA scenarios exercise real local endpoints. pm init detects hardware and sets up a small fallback model. pm provider verifies v1/messages support, tests inference capability, reports limitations.
- **depends_on**: Add local LLM provider support via OpenAI-compatible API

---

### PR: Add built-in Anthropic-to-OpenAI translation proxy for local LLM providers
- **description**: Zero-dependency translation proxy (pm_core/anthropic_proxy.py) between Anthropic Messages API and OpenAI chat completions. Handles streaming SSE, tool use round-trips, vision, thinking model support, token counting. Auto-starts when a local provider lacks /v1/messages. Health check endpoint for lifecycle watcher.
- **depends_on**: Harden local LLM integration: model selection, real QA testing, init setup, and provider verification

---

### PR: Automated local model setup with optimal tool-call and performance settings
- **description**: Interactive prompt during pm init / pm provider add that automates local model configuration. Detects server type (Ollama, vLLM, SGLang), applies optimal settings for tool calling, context length, sampling. One-command setup goal.
- **depends_on**: Harden local LLM integration: model selection, real QA testing, init setup, and provider verification

---

### PR: Per-PR model override: associate a model with a PR so all sessions use it
- **description**: Per-PR model field in project.yaml overriding default and phase-specific models. pm pr model CLI, prompt_gen sets env vars, container passthrough, TUI display. Flows to all session types: impl, review, QA planner, QA children.
- **depends_on**: Harden local LLM integration: model selection, real QA testing, init setup, and provider verification

---

## Phase 5: Automated Optimization

### PR: Add automated performance and efficiency proposal framework
- **description**: Framework for automatically proposing and testing methods to improve code generation performance and efficiency. Includes metrics collection (token usage, code quality scores, test pass rates), A/B testing infrastructure for comparing approaches, and a feedback loop that evaluates proposals against baseline measurements. Targets: generating equivalent or higher quality code with fewer tokens, and producing code that is more performant and robust to adversarial inputs.
- **depends_on**: Add optional quality assurance step with test instruction library and review-QA loop, Persist generated QA tests across iterations of the QA loop
