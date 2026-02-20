# Multi-candidate test-driven code generation

Improve local LLM coding performance by separating test generation from solution
generation and selecting the best candidate via test pass rate. The core insight:
verification is easier than generation. A small model that scores 40% on coding
benchmarks when generating solutions in a single pass can score much higher when
it generates multiple candidates and selects using self-generated tests.

This targets local compute and Omerta networks — decentralized, privacy-preserving
compute infrastructure where tasks can be distributed across heterogeneous hardware
without exposing proprietary code to centralized API providers.

## Motivation

Current coding agents (claude-code, aider, cursor) use a single model in a
single forward pass. Claude Opus scores ~72% on aider's polyglot benchmark;
local models like Qwen3 32B score ~40%. But most of that gap is generation
quality, not verification quality. If we:

1. Generate test cases from a problem description (easier than solving)
2. Generate N candidate solutions (diverse models, temperatures, prompts)
3. Score candidates by test pass rate and select the best

...we can close the gap using only local compute.

## Hierarchical generation and verification

The approach applies hierarchically, mirroring how humans reason about software.
At each level, generation and verification are separated — you can generate
candidate architectures without verifying they follow good engineering practices,
just as you can generate candidate implementations without verifying they pass
tests. This separation is what enables backtracking: if implementation-level
failures cluster around a particular interface, that's a signal to backtrack and
regenerate at the interface level, the same way a human architect restructures
when they realize a module boundary is wrong mid-implementation.

- **Architecture level**: Generate candidate module decompositions. Verify against
  software engineering principles (separation of concerns, dependency direction).
  Multiple worker models can vote on candidate architectures. Backtrack here if
  implementation-level failures cluster around an interface.
- **Interface level**: Generate candidate function signatures and type definitions.
  Verify ergonomics and edge case coverage. This is where "interface agreement"
  happens — when there are many worker models, this becomes a voting process
  where models propose and rank interfaces before any implementation begins.
- **Implementation level**: Generate candidate function bodies. Verify by running
  tests. This is the most mechanical level and benefits most from brute-force
  multi-candidate generation.

At every level, prompts and model selection can be iteratively improved. Track
which prompt variants and models produce the best results at each hierarchy level,
and feed that back into the generation process. Over time this becomes a training
signal — models can be fine-tuned on the successful outputs at each level.

The hierarchy also determines continuous improvement priority: code on hot paths
and frequently-touched modules deserves optimization cycles. Stable utility code
that passes its tests doesn't. Signals include git blame frequency, test coverage
gaps, and integration test failure clustering.

For the benchmark proof of concept, we focus on the implementation level only
(Exercism problems have a fixed interface). The hierarchy support comes later.

## Continuous improvement with fixed local compute

Fixed local compute changes the economics: instead of paying per-token for a
cloud API, you have always-on hardware. This motivates treating code quality as
a background process rather than a one-shot interaction.

- **Return early, keep refining**: Return a good-enough solution to the user
  immediately but don't stop working. Continue generating candidates and running
  tests in the background. Notify the user when a meaningfully better solution
  is found.
- **Background architecture improvement**: Workers focus on pieces of code that
  aren't currently under construction. Stable modules with low test coverage or
  poor performance get improvement cycles without blocking active development.
- **Performance optimization**: Continuously improve wall clock time and memory
  usage by caching tasks that have recently been worked on. Profile results from
  test runs feed back into optimization priorities.
- **Test coverage expansion**: Anywhere there's a stable interface with low
  coverage, generate additional tests in the background. This both improves the
  verification layer and catches regressions.

## Heterogeneous compute and escalation

Different hardware has different capabilities. A consumer GPU running a 32B model,
a workstation with a 70B model, and a cloud API with Opus-class capability form
a natural escalation ladder. Test pass rate is the objective signal for routing:

- **Budget allocation by difficulty**: Problems with a lower percentage of passing
  tests receive more of the continuous compute budget. Easy problems get solved
  by the cheapest local model and don't consume further resources.
- **Escalation to stronger models**: When a local model plateaus on a problem
  after N attempts, escalate to a larger local model, then to a cloud API.
  The accumulated test suite makes each escalation more efficient — the stronger
  model inherits the verification work already done.
- **Escalation to expert programmers**: Some tasks still exceed model capabilities.
  The test suite and failed candidate history provide rich context for a human
  expert taking over. This naturally provides a mechanism for integrating human
  expertise where it's most valuable.
- **Distributed employment platform**: The escalation mechanism can eventually
  integrate with markets — a distributed platform where tasks are posted with
  their test suites, difficulty signals, and bounties. Workers (models or humans)
  compete on solutions scored by the same test-pass-rate metric. Omerta networks
  provide the privacy and trust layer for distributing proprietary code tasks.

## PRs

### PR: Local model runner with OpenAI-compatible API
- **description**: Create a module that manages local LLM inference via the OpenAI-compatible API exposed by local serving backends (see `pm/plans/plan-002.md` for the broader multi-candidate generation strategy). Support three backends with automatic platform detection: llama.cpp server on macOS, sglang and vllm on Linux. All three expose the same OpenAI-compatible chat/completions endpoint, so the core runner uses a single HTTP client with backend-specific server management (health checks, model listing). Server URL is configured via `PM_BENCH_URL` environment variable with a sensible default per backend (e.g. `http://localhost:8080` for llama.cpp, `http://localhost:30000` for sglang). Support sending prompts to a configurable model, collecting responses, and running multiple generations with different temperatures in parallel. Track token counts and wall-clock time per request for downstream cost analysis. Include a CLI command (`pm bench models`) that detects the available backend, lists loaded models, and validates connectivity.
- **tests**: Unit tests for API interaction (mock OpenAI-compatible responses), test platform detection logic, test that all three backends use the same request/response format. Integration test (requires running backend, marked slow/CI-optional) that checks connectivity and lists models
- **files**: pm_core/bench/runner.py, pm_core/cli/bench.py
- **depends_on**:

---

### PR: Aider polyglot exercise loader
- **description**: Load the Exercism exercises used by aider's polyglot benchmark (https://github.com/Aider-AI/aider — see `benchmark/` directory for exercise structure). Each exercise has a problem description, starter code, and a reference test suite. Parse exercises into a structured format: {language, slug, description, starter_code, reference_tests}. Support filtering by language and exercise name. Clone or download the exercise set from aider's benchmark repo and cache it locally under `~/.cache/pm-bench/exercises/`. Include a CLI command (`pm bench exercises`) that downloads/updates the exercise cache and lists available exercises with optional `--language` filter.
- **tests**: Unit tests for exercise parsing with fixture data (a few sample exercises checked into the test directory). Integration test (marked slow, requires network) that clones the repo and verifies at least 200 exercises are available across the 6 languages (C++, Go, Java, JavaScript, Python, Rust). Test filtering by language and exercise name
- **files**: pm_core/bench/exercises.py, pm_core/cli/bench.py
- **depends_on**:

---

### PR: Test generation from problem descriptions
- **description**: Given an exercise's problem description and starter code (but NOT the reference tests), generate test cases using a local model. The core insight from the plan (`pm/plans/plan-002.md`): verification is easier than generation — a model that scores poorly on single-pass coding can generate useful tests that filter better solutions from multiple candidates. Use the problem description and function signatures to produce tests that verify correctness. Generate tests at multiple temperatures and with prompt variations to increase diversity. Deduplicate and validate generated tests (must parse, must be syntactically valid, must reference the correct function names). Return a merged test suite as a single source file string per language's test convention.
- **tests**: Unit tests for deduplication logic and syntax validation using hardcoded test snippets (no LLM needed). Integration test (marked slow, requires running backend) that loads a real exercise via the exercise loader, calls the runner to generate tests, and validates the output is syntactically correct and references the right function names
- **files**: pm_core/bench/test_gen.py
- **depends_on**: Local model runner with OpenAI-compatible API, Aider polyglot exercise loader

---

### PR: Multi-candidate solution generation
- **description**: Given an exercise's starter code, problem description, and a test suite (either generated or reference), produce N candidate solutions using a local model. Vary temperature (0.0 to 1.0) and prompt format (direct, chain-of-thought, example-driven). Multi-model support (querying different models on the same backend) is a stretch goal — the initial implementation should work well with a single model and temperature/prompt diversity. Each candidate is a complete file that should compile and pass the tests. Return candidates as a list of {code, temperature, prompt_variant, model}. See `pm/plans/plan-002.md` for how candidate diversity feeds into tournament selection.
- **tests**: Unit tests for prompt construction, candidate deduplication, and response parsing using mock runner responses (no LLM needed). Integration test (marked slow, requires running backend) that loads a real exercise, generates N=4 candidates via the runner, and verifies they are syntactically valid and diverse (not all identical)
- **files**: pm_core/bench/solve.py
- **depends_on**: Local model runner with OpenAI-compatible API, Aider polyglot exercise loader

---

### PR: Test execution and candidate scoring
- **description**: Run a test suite against a candidate solution in an isolated environment. Use temporary directories with copies of the exercise scaffold — each candidate gets its own temp directory, solution file is written in, and the language-appropriate test runner is invoked via subprocess with a timeout. Support the 6 polyglot languages with appropriate build/test commands: `pytest` for Python, `go test` for Go, `cargo test` for Rust, `npm test` / `jest` for JavaScript, `javac` + `junit` for Java, `cmake` + `ctest` or `g++` + run for C++. Return per-test pass/fail results and an overall score. Score candidates as (passing_tests / total_tests). Handle compilation failures, timeouts, and runtime errors gracefully.
- **tests**: Unit tests for scoring logic with mock test results, test timeout handling, test that each language's build/test command is constructed correctly. Integration test that loads a real Python exercise via the exercise loader, writes a known-correct solution, runs the executor against the reference tests, and verifies a perfect score
- **files**: pm_core/bench/executor.py
- **depends_on**: Aider polyglot exercise loader

---

### PR: Benchmark orchestrator with tournament selection
- **description**: Wire together the full pipeline from `pm/plans/plan-002.md`: for each exercise, (1) generate tests from the description, (2) generate N candidate solutions, (3) score each candidate against the generated tests, (4) pick the best candidate, (5) score the best candidate against the reference tests to get the final result. The pipeline embodies the plan's core insight — separating verification (test generation) from generation (solution candidates) lets weaker models punch above their weight through selection pressure. Compare the tournament score against a single-pass baseline (N=1, reference tests only). Collect cost metrics from the runner (total tokens, wall-clock time, tokens per exercise) alongside scores. Report results as a terminal table showing per-exercise and aggregate scores, and save raw results to a JSON file. Add CLI command `pm bench run` with options for model, N candidates, languages, and exercise filter.
- **tests**: Unit test that tournament selection picks the highest-scoring candidate from mock scores. Integration test (marked slow, requires running backend) that runs the full pipeline on 1-2 Python exercises end-to-end: exercises loaded from cache, tests generated via runner, candidates generated via runner, candidates scored via executor, best selected, and final score computed against reference tests. Verify the JSON output contains all expected fields
- **files**: pm_core/bench/orchestrator.py, pm_core/cli/bench.py
- **depends_on**: Test generation from problem descriptions, Multi-candidate solution generation, Test execution and candidate scoring

---

### PR: Baseline measurement and analysis
- **description**: Add a CLI command `pm bench analyze` that reads benchmark result JSON files produced by the orchestrator and generates comparison reports. Run the benchmark via `pm bench run` in single-pass mode (N=1, no test generation) to establish the baseline, then with tournament (N=8, N=16) and compare. Produce a report showing: baseline vs tournament scores per language, per exercise difficulty tier (easy/medium/hard, based on baseline pass rate — easy: >66% of models solve it, hard: <33%), and aggregate. Include cost analysis — total tokens generated, wall-clock time, and tokens-per-correct-exercise for each configuration, so the accuracy improvement can be weighed against the compute cost (e.g., "N=16 tournament scores 58% vs 40% baseline but costs 20x the tokens"). Identify which exercises benefit most from multi-candidate generation (large delta) vs which are insensitive (model either always gets it or never does). Save analysis results to a JSON file for tracking over time.
- **tests**: Unit tests for report generation and difficulty tier classification with mock benchmark result JSON. Test cost metric aggregation logic. Integration test (marked slow) that reads real orchestrator output JSON (from a previous `pm bench run`) and produces a valid analysis report
- **files**: pm_core/bench/analysis.py, pm_core/cli/bench.py
- **depends_on**: Benchmark orchestrator with tournament selection

---

### PR: Generated test quality analysis
- **description**: Add a CLI command `pm bench test-quality` that analyzes how well generated tests compare to reference tests. This is critical for validating the plan's core assumption (`pm/plans/plan-002.md`) that verification is easier than generation — if generated tests are poor, tournament selection breaks down regardless of candidate quality. Reads benchmark result JSON from the orchestrator, which includes both generated and reference test outcomes per candidate. Measure: (1) coverage overlap — run each candidate against both generated and reference tests and compute rank correlation (do generated tests rank candidates in the same order as reference tests?), (2) false positives — identify generated tests that pass on candidates that fail all reference tests (using the failed candidates already present in benchmark results), (3) diversity — count distinct pass/fail signatures across generated tests (more signatures = more behavioral coverage). Cross-reference with benchmark results: do exercises where generated tests diverge most from reference tests also show the largest gap between tournament-selected and oracle-selected (best candidate scored against reference tests) scores?
- **tests**: Unit tests for rank correlation, false positive detection, and diversity metrics using synthetic candidate score data. Integration test (marked slow) that reads real orchestrator output JSON and produces a valid test quality report
- **files**: pm_core/bench/test_analysis.py, pm_core/cli/bench.py
- **depends_on**: Benchmark orchestrator with tournament selection
