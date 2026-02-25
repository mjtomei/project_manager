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

> **Note:** PRs 012–016 (runner, exercise loader, test gen, solve, executor) were
> closed without merging and consolidated into pr-017. The original PR sections are
> preserved below for reference but marked as superseded.

### PR: Local model runner with OpenAI-compatible API
- **status**: closed — superseded by pr-017
- **description**: Create a module that manages local LLM inference via the OpenAI-compatible API exposed by local serving backends. Support three backends with automatic platform detection: llama.cpp server on macOS, sglang and vllm on Linux.
- **files**: pm_core/bench/runner.py, pm_core/cli/bench.py

---

### PR: Aider polyglot exercise loader
- **status**: closed — superseded by pr-017
- **description**: Load the Exercism exercises used by aider's polyglot benchmark. Parse exercises into a structured format with filtering by language and exercise name.
- **files**: pm_core/bench/exercises.py, pm_core/cli/bench.py

---

### PR: Test generation from problem descriptions
- **status**: closed — superseded by pr-017
- **description**: Generate test cases from exercise problem descriptions using a local model. Deduplicate and validate generated tests.
- **files**: pm_core/bench/test_gen.py

---

### PR: Multi-candidate solution generation
- **status**: closed — superseded by pr-017
- **description**: Produce N candidate solutions using temperature and prompt variant diversity.
- **files**: pm_core/bench/solve.py

---

### PR: Test execution and candidate scoring
- **status**: closed — superseded by pr-017
- **description**: Run test suites against candidates in isolated environments with 6-language support.
- **files**: pm_core/bench/executor.py

---

### PR: Benchmark: multi-candidate code generation with tournament selection
- **description**: Collapsed implementation of the full benchmark pipeline. Includes: OpenAI-compatible multi-backend runner (llama.cpp/sglang/vllm), Exercism exercise loader from aider's polyglot-benchmark, test generation from problem descriptions, multi-candidate solution generation, test execution with 6-language support, and tournament orchestrator with baseline comparison, cost metrics, and JSON export. CLI commands: `pm bench models`, `pm bench exercises`, `pm bench run`. Features added during implementation: vLLM reasoning mode support, chain mode (`--chain`) for sequential generation with prior-attempt context, parallel exercise execution (`-j`), and separate tournament/baseline token accounting (schema v2). Supersedes pr-012 through pr-016.
- **tests**: 44 unit tests covering runner (backend detection, URL config, health checks, chat completion, parallel generation, cost metrics), exercises (parsing, filtering, heuristic fallback), and orchestrator (scoring, formatting, JSON roundtrip)
- **files**: pm_core/bench/runner.py, pm_core/bench/exercises.py, pm_core/bench/test_gen.py, pm_core/bench/solve.py, pm_core/bench/executor.py, pm_core/bench/orchestrator.py, pm_core/bench/_utils.py, pm_core/bench/__init__.py, pm_core/cli/bench.py, pm_core/paths.py
- **depends_on**:
- **manual_testing**: INPUT_REQUIRED — requires a running local inference backend (llama.cpp, sglang, or vllm) with a loaded model. `pm bench models` validates connectivity. `pm bench exercises` requires network access to clone aider's benchmark repo. `pm bench run` exercises the full pipeline and requires language toolchains (pytest for Python, go test, cargo test, npm/jest, javac/junit, g++) for multi-language execution.
- **results**: Python (34 exercises): 120B chain+reasoning T=53.8% B=50.1% (+3.7pp); 20B chain T=42.7% B=35.5% (+7.2pp). Reasoning mode is the biggest lever.

---

### PR: EvalPlus benchmark loader (HumanEval+ and MBPP+)
- **description**: Add EvalPlus (HumanEval+ 164 problems, MBPP+ 378 problems) as an exercise source. Python-only function-completion with 80x expanded assert-based test suites — structurally identical to the existing Exercism/Python path. Public leaderboard (evalplus.github.io, 100+ models) enables direct comparison: Qwen2.5-Coder-32B 87.2%/75.1% HE+/MBPP+, DeepSeek-V2 84.8%/76.2%, Qwen2.5-Coder-7B 84.1%/71.7%. Download from HuggingFace JSONL, cache under `~/.cache/pm-bench/evalplus/`. Add `--source evalplus` flag to `pm bench exercises` and `pm bench run`.
- **tests**: Unit tests for JSONL parsing, Exercise field mapping. Integration: download dataset, verify 164+378 exercises. Manual eval: 20B first (`PM_BENCH_URL=http://localhost:30001 pm bench run openai/gpt-oss-20b -n 8 --chain --temperature 0.0 -j 4 --source evalplus`), then 120B.
- **files**: pm_core/bench/exercises_evalplus.py, pm_core/cli/bench.py (--source flag), pm_core/bench/exercises.py (refactor for pluggable sources)
- **depends_on**: Benchmark: multi-candidate code generation with tournament selection
- **manual_testing**: INPUT_REQUIRED — requires running vLLM backend. Eval order: 20B then 120B. Compare against published pass@1 to gauge tournament selection effectiveness.

---

### PR: LiveCodeBench competitive programming loader
- **description**: Add LiveCodeBench (880+ problems from LeetCode/AtCoder/Codeforces, continuously updated) as an exercise source. Stdin/stdout evaluation format — requires a new execution path in executor.py that pipes input to the candidate program and compares stdout to expected output (instead of running a test file via pytest). Continuously updated post-training-cutoff to reduce contamination. Download from HuggingFace (`livecodebench/code_generation_lite`), cache under `~/.cache/pm-bench/livecodebench/`. Add `--source livecodebench` and `--difficulty easy/medium/hard` flags.
- **tests**: Unit tests for dataset parsing, stdin/stdout executor path with known-correct solutions. Integration: download dataset, verify 880+ exercises. Manual eval: start with `--difficulty easy` on 20B to validate stdin/stdout executor, then full range, then 120B.
- **files**: pm_core/bench/exercises_livecodebench.py, pm_core/bench/executor.py (stdin/stdout path), pm_core/cli/bench.py (--source, --difficulty flags)
- **depends_on**: Benchmark: multi-candidate code generation with tournament selection
- **manual_testing**: INPUT_REQUIRED — requires running vLLM backend. The stdin/stdout execution path is new and needs end-to-end validation. Eval order: 20B easy → 20B full → 120B full.

---

### PR: BigCodeBench real-world task loader
- **description**: Add BigCodeBench (1,140 tasks, 148 hard subset) as an exercise source. Tasks require real library APIs (pandas, numpy, http.client, matplotlib) with unittest+mock-based tests — hardest benchmark, most realistic. Public leaderboard: GPT-4o 61.1%/51.1% complete/instruct, Qwen2.5-Coder-32B ~49.6%. Use instruct_prompt mode (NL instructions, better fit for chat models). Download from HuggingFace (`bigcode/bigcodebench`), cache under `~/.cache/pm-bench/bigcodebench/`. pytest discovers unittest tests natively so basic executor works, but library deps from the `libs` field must be installed. Add `--source bigcodebench`, `--hard`, and `--mode complete/instruct` flags.
- **tests**: Unit tests for dataset parsing, both prompt modes, libs extraction. Integration: download dataset, verify 1,140 exercises (148 hard). Manual eval: 20B hard subset first (`--hard`, ~148 problems), then full set, then 120B. Compare against GPT-4o 51.1% instruct.
- **files**: pm_core/bench/exercises_bigcodebench.py, pm_core/cli/bench.py (--source, --hard, --mode flags)
- **depends_on**: Benchmark: multi-candidate code generation with tournament selection
- **manual_testing**: INPUT_REQUIRED — requires running vLLM backend and library deps installed in pm venv (pandas, numpy, matplotlib, etc.). Eval order: 20B hard → 20B full → 120B hard.

---

### PR: Baseline measurement and analysis
- **description**: Add a CLI command `pm bench analyze` that reads benchmark result JSON files produced by the orchestrator and generates comparison reports. Run the benchmark via `pm bench run` in single-pass mode (N=1, no test generation) to establish the baseline, then with tournament (N=8, N=16) and compare. Produce a report showing: baseline vs tournament scores per language, per exercise difficulty tier (easy/medium/hard, based on baseline pass rate — easy: >66% of models solve it, hard: <33%), and aggregate. Include cost analysis — total tokens generated, wall-clock time, and tokens-per-correct-exercise for each configuration, so the accuracy improvement can be weighed against the compute cost (e.g., "N=16 tournament scores 58% vs 40% baseline but costs 20x the tokens"). Identify which exercises benefit most from multi-candidate generation (large delta) vs which are insensitive (model either always gets it or never does). Save analysis results to a JSON file for tracking over time.
- **tests**: Unit tests for report generation and difficulty tier classification with mock benchmark result JSON. Test cost metric aggregation logic. Integration test (marked slow) that reads real orchestrator output JSON (from a previous `pm bench run`) and produces a valid analysis report
- **files**: pm_core/bench/analysis.py, pm_core/cli/bench.py
- **depends_on**: Benchmark: multi-candidate code generation with tournament selection

---

### PR: Generated test quality analysis
- **description**: Add a CLI command `pm bench test-quality` that analyzes how well generated tests compare to reference tests. This is critical for validating the plan's core assumption (`pm/plans/plan-002.md`) that verification is easier than generation — if generated tests are poor, tournament selection breaks down regardless of candidate quality. Reads benchmark result JSON from the orchestrator, which includes both generated and reference test outcomes per candidate. Measure: (1) coverage overlap — run each candidate against both generated and reference tests and compute rank correlation (do generated tests rank candidates in the same order as reference tests?), (2) false positives — identify generated tests that pass on candidates that fail all reference tests (using the failed candidates already present in benchmark results), (3) diversity — count distinct pass/fail signatures across generated tests (more signatures = more behavioral coverage). Cross-reference with benchmark results: do exercises where generated tests diverge most from reference tests also show the largest gap between tournament-selected and oracle-selected (best candidate scored against reference tests) scores?
- **tests**: Unit tests for rank correlation, false positive detection, and diversity metrics using synthetic candidate score data. Integration test (marked slow) that reads real orchestrator output JSON and produces a valid test quality report
- **files**: pm_core/bench/test_analysis.py, pm_core/cli/bench.py
- **depends_on**: Benchmark: multi-candidate code generation with tournament selection
