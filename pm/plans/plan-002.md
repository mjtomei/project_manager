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

### PR: Local model runner with Ollama integration
- **description**: Create a module that manages local LLM inference via Ollama's API. Support sending prompts to a configurable model, collecting responses, and running multiple generations with different temperatures in parallel. Include a simple CLI command (`pm bench models`) that lists available Ollama models and validates connectivity.
- **tests**: Unit tests for API interaction (mock Ollama responses), integration test that checks Ollama connectivity and lists models
- **files**: pm_core/bench/runner.py, pm_core/cli.py
- **depends_on**:

---

### PR: Aider polyglot exercise loader
- **description**: Load the Exercism exercises used by aider's polyglot benchmark. Each exercise has a problem description, starter code, and a reference test suite. Parse exercises into a structured format: {language, slug, description, starter_code, reference_tests}. Support filtering by language and exercise name. Download or reference the exercise set from aider's benchmark repo.
- **tests**: Test that exercises load correctly, test filtering by language, test that at least 200 exercises are available across the 6 languages (C++, Go, Java, JavaScript, Python, Rust)
- **files**: pm_core/bench/exercises.py, pm_core/cli.py
- **depends_on**:

---

### PR: Test generation from problem descriptions
- **description**: Given an exercise's problem description and starter code (but NOT the reference tests), generate test cases using a local model. Use the problem description and function signatures to produce tests that verify correctness. Generate tests at multiple temperatures and with prompt variations to increase diversity. Deduplicate and validate generated tests (must parse, must be syntactically valid, must reference the correct function names). Return a merged test suite.
- **tests**: Test that generated tests are syntactically valid for each supported language, test deduplication logic, test that generated tests cover basic cases from the problem description
- **files**: pm_core/bench/test_gen.py
- **depends_on**: Local model runner with Ollama integration, Aider polyglot exercise loader

---

### PR: Multi-candidate solution generation
- **description**: Given an exercise's starter code, problem description, and a test suite (either generated or reference), produce N candidate solutions using a local model. Vary temperature (0.0 to 1.0), prompt format (direct, chain-of-thought, example-driven), and optionally model (if multiple Ollama models are available). Each candidate is a complete file that should compile and pass the tests. Return candidates as a list of {code, temperature, prompt_variant, model}.
- **tests**: Test that N candidates are generated with requested diversity, test that candidates contain syntactically valid code, test deduplication of identical solutions
- **files**: pm_core/bench/solve.py
- **depends_on**: Local model runner with Ollama integration, Aider polyglot exercise loader

---

### PR: Test execution and candidate scoring
- **description**: Run a test suite against a candidate solution in a sandboxed environment. Support the 6 polyglot languages (C++, Go, Java, JavaScript, Python, Rust) with appropriate build/test commands for each. Return per-test pass/fail results and an overall score. Score candidates as (passing_tests / total_tests). Handle compilation failures, timeouts, and runtime errors gracefully. Use subprocess with timeout to prevent hangs.
- **tests**: Test scoring logic with mock test results, test timeout handling, test that each language's build/test command is correct, integration test running a simple Python exercise end-to-end
- **files**: pm_core/bench/executor.py
- **depends_on**: Aider polyglot exercise loader

---

### PR: Benchmark orchestrator with tournament selection
- **description**: Wire together the full pipeline: for each exercise, (1) generate tests from the description, (2) generate N candidate solutions, (3) score each candidate against the generated tests, (4) pick the best candidate, (5) score the best candidate against the reference tests to get the final result. Compare the tournament score against a single-pass baseline (N=1, reference tests only). Report results as a table showing per-exercise and aggregate scores. Add CLI command `pm bench run` with options for model, N candidates, languages, and exercise filter.
- **tests**: End-to-end test with a small subset of exercises (2-3 per language), test that tournament selection picks the highest-scoring candidate, test that results are reported correctly
- **files**: pm_core/bench/orchestrator.py, pm_core/cli.py
- **depends_on**: Test generation from problem descriptions, Multi-candidate solution generation, Test execution and candidate scoring

---

### PR: Baseline measurement and analysis
- **description**: Run the benchmark in single-pass mode (N=1, no test generation) to establish the baseline score for each local model. Then run with test generation + tournament (N=8, N=16) and compare. Produce a report showing: baseline vs tournament scores per language, per exercise difficulty tier, and aggregate. Identify which exercises benefit most from multi-candidate generation (large delta) vs which are insensitive (model either always gets it or never does). Save results to a JSON file for tracking over time.
- **tests**: Test report generation with mock benchmark results, test JSON output format
- **files**: pm_core/bench/analysis.py, pm_core/cli.py
- **depends_on**: Benchmark orchestrator with tournament selection

---

### PR: Generated test quality analysis
- **description**: Compare generated tests against reference tests to understand test generation quality. Measure: (1) coverage overlap — what fraction of reference test cases are covered by generated tests, (2) false positives — generated tests that pass on wrong solutions, (3) diversity — how many distinct behaviors are tested. This analysis reveals whether test generation is the bottleneck (if generated tests are poor, even good solutions won't be selected correctly) and guides improvements to test generation prompts.
- **tests**: Test analysis metrics with synthetic test suites, test that false positive detection works
- **files**: pm_core/bench/test_analysis.py
- **depends_on**: Benchmark orchestrator with tournament selection
